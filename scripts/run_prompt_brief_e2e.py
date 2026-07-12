"""Stage the canonical prompt-to-project workflow without hiding review gates.

The harness exercises ``POST /projects/from-brief`` exactly as the product
does.  It has three deliberately separate modes:

* ``preflight`` (also accepted as ``dry-run``) compiles and records the current
  prompt contracts without a provider or database call.
* ``contract`` runs the canonical HTTP API against deterministic offline image
  agent doubles.  It proves warning-preview, observability, atomicity, and
  explicit-acceptance behavior without using provider credits.
* ``live`` uses the configured image agent.  It is cost-guarded and stops at
  every warning unless the corresponding ``--test-accept-*`` flag is present.

Warning acceptance in this script is always attributed to an unapproved test
actor.  It is never founder, designer, factory, or GIA-trained cofounder
approval.

Examples::

    PYTHONPATH=src uv run python scripts/run_prompt_brief_e2e.py RUN_NAME
    PYTHONPATH=src uv run python scripts/run_prompt_brief_e2e.py RUN_NAME \
        --mode dry-run
    PYTHONPATH=src uv run python scripts/run_prompt_brief_e2e.py RUN_NAME \
        --mode contract
    PYTHONPATH=src uv run python scripts/run_prompt_brief_e2e.py RUN_NAME \
        --mode live --confirm-paid-provider-calls
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from facetta.api.projects import ProjectFromBriefRequest  # noqa: E402
from facetta.config import load_env_file  # noqa: E402
from facetta.db import (  # noqa: E402
    Base,
    Design,
    DesignVersion,
    ImageAsset,
    ImageAttempt,
    ImageRun,
    ImageRunReview,
    Project,
    get_db,
)
from facetta.image_agent import (  # noqa: E402
    CheckSeverity,
    ImageOperation,
    ImageQualityReport,
    JewelryImageAgent,
    ProviderImage,
    QualityCheck,
    QualityVerdict,
    build_image_plan,
)
from facetta.image_agent.prompts import (  # noqa: E402
    MAX_PROVIDER_PROMPT_CHARS,
    compile_initial_prompt,
)
from facetta.main import app  # noqa: E402
from facetta.project_backbone import (  # noqa: E402
    BriefProjectGeneration,
    BriefProjectGenerator,
    get_brief_project_generator,
)
from facetta.ring_evals import (  # noqa: E402
    RING_GOLDEN_CASES,
    build_ring_golden_spec,
)
from facetta.spec import Spec  # noqa: E402
from facetta.warning_candidates import (  # noqa: E402
    clear_warning_candidates_for_tests,
)


EXPECTED_PROMPT_VERSIONS = {
    "concept": "concept-generate.v1",
    "spec_render": "spec-render.v3",
}
DEFAULT_BRIEF = (
    "Create one refined engagement ring with a round brilliant diamond center, "
    "four-claw basket, 18k yellow gold, a narrow 1.8 mm half-round polished "
    "shank, no halo, and no side stones. Use a neutral studio presentation."
)
TEST_ACTOR = "usr_prompt_test_actor"
PRODUCT_COUNT_KEYS = ("designs", "versions", "assets", "projects")


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _response_body(response) -> dict[str, Any]:
    try:
        value = response.json()
    except Exception:
        value = {"raw": response.text[:4000]}
    return value if isinstance(value, dict) else {"body": value}


def _png(color: tuple[int, int, int] = (196, 168, 96)) -> bytes:
    output = BytesIO()
    Image.new("RGB", (96, 96), color).save(output, format="PNG")
    return output.getvalue()


def _database_counts(session_factory: sessionmaker[Session]) -> dict[str, int]:
    models = {
        "designs": Design,
        "versions": DesignVersion,
        "assets": ImageAsset,
        "projects": Project,
        "image_runs": ImageRun,
        "image_attempts": ImageAttempt,
        "image_run_reviews": ImageRunReview,
    }
    with session_factory() as db:
        return {
            label: int(
                db.scalar(select(func.count()).select_from(model)) or 0
            )
            for label, model in models.items()
        }


def _product_counts(counts: dict[str, int]) -> dict[str, int]:
    return {key: counts[key] for key in PRODUCT_COUNT_KEYS}


@contextmanager
def _isolated_client(
    generator: BriefProjectGenerator | None = None,
) -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
    """Use the production router with an isolated, disposable database."""

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False)

    def override_db():
        session = sessions()
        try:
            yield session
        finally:
            session.close()

    previous_overrides = dict(app.dependency_overrides)
    clear_warning_candidates_for_tests()
    app.dependency_overrides[get_db] = override_db
    if generator is not None:
        app.dependency_overrides[get_brief_project_generator] = (
            lambda: generator
        )
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client, sessions
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)
        clear_warning_candidates_for_tests()
        engine.dispose()


def _save_image_response(response, path_without_suffix: Path) -> str:
    media_type = response.headers.get("content-type", "").split(";", 1)[0]
    suffix = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }.get(media_type, ".bin")
    path = path_without_suffix.with_suffix(suffix)
    path.write_bytes(response.content)
    return path.name


def _save_run_evidence(
    client: TestClient,
    run_id: str,
    path: Path,
) -> dict[str, Any]:
    response = client.get(f"/image-runs/{run_id}")
    body = _response_body(response)
    evidence = {"http_status": response.status_code, "body": body}
    _write_json(path, evidence)
    if response.status_code != 200:
        raise RuntimeError(
            f"image run '{run_id}' was not readable: {response.status_code}"
        )
    return body


def _download_project_evidence(
    client: TestClient,
    project: dict[str, Any],
    outdir: Path,
) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    for index, raw in enumerate(project.get("assets", []), start=1):
        if not isinstance(raw, dict) or not isinstance(raw.get("image_url"), str):
            continue
        response = client.get(raw["image_url"])
        artifact = {
            "asset_id": raw.get("asset_id"),
            "capability": raw.get("capability"),
            "http_status": response.status_code,
        }
        if response.status_code == 200:
            artifact["file"] = _save_image_response(
                response,
                outdir / f"project-asset-{index:02d}-{raw.get('capability', 'image')}",
            )
        assets.append(artifact)

    for index, run_id in enumerate(project.get("image_run_ids", []), start=1):
        if isinstance(run_id, str):
            _save_run_evidence(
                client,
                run_id,
                outdir / f"project-image-run-{index:02d}.json",
            )
    return assets


def _exercise_flow(
    client: TestClient,
    sessions: sessionmaker[Session],
    request: ProjectFromBriefRequest,
    outdir: Path,
    *,
    test_accept_concept_warning: bool,
    test_accept_spec_warning: bool,
) -> dict[str, Any]:
    """Run the API and stop at warnings unless a named test flag allows them."""

    before = _database_counts(sessions)
    response = client.post(
        "/projects/from-brief",
        json=request.model_dump(mode="json"),
    )
    step = 1
    warning_boundaries: list[dict[str, Any]] = []
    accepted_warning_stages: list[str] = []

    while True:
        body = _response_body(response)
        _write_json(
            outdir / f"stage-{step:02d}-response.json",
            {"http_status": response.status_code, "body": body},
        )

        if response.status_code != 202:
            break
        warning = body.get("warning_candidate")
        if not isinstance(warning, dict):
            raise RuntimeError("202 response omitted warning_candidate")
        if body.get("project") is not None:
            raise RuntimeError("warning response must not contain a project")
        stage = str(warning.get("creation_stage"))
        if stage not in {"concept", "spec_render"}:
            raise RuntimeError(f"unknown brief warning stage '{stage}'")
        preview_url = warning.get("preview_url")
        if not isinstance(preview_url, str):
            raise RuntimeError("warning response omitted preview_url")
        preview_response = client.get(preview_url)
        if preview_response.status_code != 200:
            raise RuntimeError(
                f"warning preview failed: {preview_response.status_code}"
            )
        preview_name = _save_image_response(
            preview_response,
            outdir / f"stage-{step:02d}-{stage}-warning-preview",
        )
        run_id = body.get("image_run_id")
        if not isinstance(run_id, str):
            raise RuntimeError("warning response omitted image_run_id")
        run = _save_run_evidence(
            client,
            run_id,
            outdir / f"stage-{step:02d}-{stage}-image-run.json",
        )
        at_boundary = _database_counts(sessions)
        no_partial_product = _product_counts(at_boundary) == _product_counts(before)
        if not no_partial_product:
            raise RuntimeError("a warning candidate created partial project records")

        allowed = (
            test_accept_concept_warning
            if stage == "concept"
            else test_accept_spec_warning
        )
        boundary = {
            "stage": stage,
            "candidate_id": warning.get("candidate_id"),
            "run_id": run_id,
            "prompt_contract_version": run.get("prompt_contract_version"),
            "preview_file": preview_name,
            "project_records_unchanged": no_partial_product,
            "accepted_by_harness": allowed,
            "acceptance_role": (
                "unapproved_test_actor" if allowed else "none"
            ),
            "founder_approval": False,
            "designer_approval": False,
            "gia_cofounder_approval": False,
        }
        warning_boundaries.append(boundary)
        _write_json(outdir / f"stage-{step:02d}-{stage}-boundary.json", boundary)
        if not allowed:
            after = _database_counts(sessions)
            return {
                "status": f"stopped_for_{stage}_review",
                "http_status": response.status_code,
                "warning_boundaries": warning_boundaries,
                "accepted_warning_stages": accepted_warning_stages,
                "database_before": before,
                "database_after": after,
                "partial_product_records": False,
                "founder_approval": False,
            }

        candidate_id = warning.get("candidate_id")
        if not isinstance(candidate_id, str):
            raise RuntimeError("warning response omitted candidate_id")
        accepted_warning_stages.append(stage)
        response = client.post(
            f"/projects/from-brief/candidates/{candidate_id}/accept",
            json={"created_by": request.owner},
        )
        step += 1

    after = _database_counts(sessions)
    if response.status_code >= 400:
        no_partial_product = _product_counts(after) == _product_counts(before)
        persistence = {
            "terminal_http_status": response.status_code,
            "database_before": before,
            "database_after": after,
            "product_counts_before": _product_counts(before),
            "product_counts_after": _product_counts(after),
            "partial_product_records": not no_partial_product,
        }
        _write_json(outdir / "terminal-failure-persistence.json", persistence)
        if not no_partial_product:
            raise RuntimeError("terminal failure left partial project records")
        run_id = body.get("image_run_id")
        if isinstance(run_id, str):
            _save_run_evidence(
                client,
                run_id,
                outdir / "terminal-failure-image-run.json",
            )
        return {
            "status": "terminal_failure",
            "http_status": response.status_code,
            "error": body,
            "warning_boundaries": warning_boundaries,
            "accepted_warning_stages": accepted_warning_stages,
            **persistence,
            "founder_approval": False,
        }

    if response.status_code not in {200, 201}:
        raise RuntimeError(f"unexpected final HTTP status {response.status_code}")
    project = body
    _write_json(outdir / "project.json", project)
    artifacts = _download_project_evidence(client, project, outdir)
    return {
        "status": "project_created",
        "http_status": response.status_code,
        "project_id": project.get("root_id"),
        "design_id": project.get("design_id"),
        "active_asset_id": project.get("active_asset_id"),
        "active_design_version": project.get("active_design_version"),
        "warning_boundaries": warning_boundaries,
        "accepted_warning_stages": accepted_warning_stages,
        "acceptance_role": (
            "unapproved_test_actor" if accepted_warning_stages else "qa_pass"
        ),
        "founder_approval": False,
        "designer_approval": False,
        "gia_cofounder_approval": False,
        "database_before": before,
        "database_after": after,
        "artifacts": artifacts,
    }


def _representative_spec() -> Spec:
    return build_ring_golden_spec(RING_GOLDEN_CASES[0])


def _prompt_contracts(brief: str, variant: int) -> dict[str, Any]:
    spec = _representative_spec()
    concept_plan = build_image_plan(
        ImageOperation.CONCEPT_GENERATE,
        brief,
        expected_output=(
            "one unbranded, client-reviewable ring concept on a neutral studio "
            "background"
        ),
        variant=variant,
    )
    concept_image = _png()
    spec_plan = build_image_plan(
        ImageOperation.SPEC_RENDER,
        "Create the spec-aligned hero render for the approved concept",
        spec=spec,
        source_image=concept_image,
        expected_output=(
            "one photorealistic ring render that preserves concept identity and "
            "matches every visible validated specification fact"
        ),
        variant=variant,
    )
    concept_prompt = compile_initial_prompt(concept_plan)
    spec_prompt = compile_initial_prompt(spec_plan)
    observed = {
        "concept": concept_plan.prompt_version,
        "spec_render": spec_plan.prompt_version,
    }
    if observed != EXPECTED_PROMPT_VERSIONS:
        raise RuntimeError(
            "prompt contracts changed; review this harness before running live: "
            f"expected {EXPECTED_PROMPT_VERSIONS}, observed {observed}"
        )
    lengths = {
        "concept": len(concept_prompt),
        "spec_render": len(spec_prompt),
    }
    if any(length > MAX_PROVIDER_PROMPT_CHARS for length in lengths.values()):
        raise RuntimeError(f"compiled provider prompt exceeds limit: {lengths}")
    return {
        "expected_versions": EXPECTED_PROMPT_VERSIONS,
        "observed_versions": observed,
        "provider_prompt_limit_chars": MAX_PROVIDER_PROMPT_CHARS,
        "prompt_lengths": lengths,
        "concept": {
            "operation": concept_plan.operation.value,
            "prompt_version": concept_plan.prompt_version,
            "input_hash": concept_plan.input_hash,
            "normalized_intent": concept_plan.normalized_intent,
            "compiled_prompt": concept_prompt,
        },
        "spec_render": {
            "operation": spec_plan.operation.value,
            "prompt_version": spec_plan.prompt_version,
            "input_hash": spec_plan.input_hash,
            "source_hash": spec_plan.source_hash,
            "spec_visual_hash": spec_plan.spec_visual_hash,
            "normalized_intent": spec_plan.normalized_intent,
            "compiled_prompt": spec_prompt,
        },
    }


def run_preflight(
    outdir: Path,
    request: ProjectFromBriefRequest,
) -> dict[str, Any]:
    contracts = _prompt_contracts(request.brief, request.variant)
    result = {
        "mode": "preflight",
        "live": False,
        "provider_calls": 0,
        "request": request.model_dump(mode="json"),
        "prompt_contracts": contracts,
        "review_policy": {
            "warning_auto_accept": False,
            "explicit_test_flags": [
                "--test-accept-concept-warning",
                "--test-accept-spec-warning",
            ],
            "test_flag_role": "unapproved_test_actor",
            "founder_approval": False,
        },
    }
    _write_json(outdir / "results.json", result)
    (outdir / "report.md").write_text(
        "# Prompt-to-project preflight\n\n"
        "Validated `POST /projects/from-brief` input and compiled "
        "`concept-generate.v1` plus `spec-render.v3`. No provider or database "
        "call was made. Warnings remain explicit review boundaries.\n"
    )
    return result


class _OfflineProvider:
    def __init__(self, image: bytes) -> None:
        self.image = image

    def execute(self, *_args, **_kwargs) -> ProviderImage:
        return ProviderImage(
            image_bytes=self.image,
            cached=True,
            provider_request_id="offline-contract",
            usage={"contract_test": True},
            cost=0,
        )


class _OfflineEvaluator:
    def __init__(self, verdict: QualityVerdict) -> None:
        self.verdict = verdict

    def evaluate(self, *_args, **_kwargs) -> ImageQualityReport:
        passed = self.verdict is QualityVerdict.PASS
        warning = self.verdict is QualityVerdict.WARN
        return ImageQualityReport(
            verdict=self.verdict,
            checks=(QualityCheck(
                code=(
                    "offline_contract_pass"
                    if passed
                    else (
                        "offline_designer_review_required"
                        if warning
                        else "offline_terminal_hard_gate_failure"
                    )
                ),
                passed=passed,
                severity=(
                    CheckSeverity.WARNING if warning else CheckSeverity.HARD
                ),
                message=(
                    "offline contract candidate passed"
                    if passed
                    else (
                        "offline contract candidate requires designer review"
                        if warning
                        else "offline contract candidate failed a hard gate"
                    )
                ),
                evidence={"offline": True},
            ),),
            score=96 if passed else 88,
            notes=("Deterministic offline contract evidence; not visual approval.",),
        )


def _offline_agent_result(
    operation: ImageOperation,
    verdict: QualityVerdict,
    *,
    brief: str,
    spec: Spec | None = None,
    source_image: bytes | None = None,
    color: tuple[int, int, int],
):
    plan = build_image_plan(
        operation,
        brief,
        spec=spec,
        source_image=source_image,
    )
    return JewelryImageAgent(
        _OfflineProvider(_png(color)),
        _OfflineEvaluator(verdict),
    ).run(plan, source_image=source_image)


def _offline_pass_generation(
    brief: str,
    variant: int,
    *,
    reviewed_concept=None,
) -> BriefProjectGeneration:
    del variant
    spec = _representative_spec()
    concept = reviewed_concept or _offline_agent_result(
        ImageOperation.CONCEPT_GENERATE,
        QualityVerdict.PASS,
        brief=brief,
        color=(192, 160, 76),
    )
    spec_render = _offline_agent_result(
        ImageOperation.SPEC_RENDER,
        QualityVerdict.PASS,
        brief="Create the spec-aligned hero render for the approved concept",
        spec=spec,
        source_image=concept.image_bytes,
        color=(210, 198, 172),
    )
    return BriefProjectGeneration(
        concept_image=concept.image_bytes,
        spec_render=spec_render.image_bytes,
        spec=spec,
        quality_verdict="pass",
        quality_report={
            "verdict": "pass",
            "stage": "spec_render",
            "offline_contract": True,
        },
        concept_run=concept,
        spec_render_run=spec_render,
    )


def _offline_concept_warning(
    brief: str,
    variant: int,
) -> BriefProjectGeneration:
    del variant
    concept = _offline_agent_result(
        ImageOperation.CONCEPT_GENERATE,
        QualityVerdict.WARN,
        brief=brief,
        color=(178, 146, 68),
    )
    return BriefProjectGeneration(
        concept_image=concept.image_bytes,
        spec_render=b"",
        spec=None,
        quality_verdict="warn",
        quality_report={
            "verdict": "warn",
            "stage": "concept",
            "offline_contract": True,
        },
        concept_run=concept,
    )


def _offline_spec_warning(
    brief: str,
    variant: int,
) -> BriefProjectGeneration:
    del variant
    spec = _representative_spec()
    concept = _offline_agent_result(
        ImageOperation.CONCEPT_GENERATE,
        QualityVerdict.PASS,
        brief=brief,
        color=(192, 160, 76),
    )
    spec_render = _offline_agent_result(
        ImageOperation.SPEC_RENDER,
        QualityVerdict.WARN,
        brief="Create the spec-aligned hero render for the approved concept",
        spec=spec,
        source_image=concept.image_bytes,
        color=(202, 192, 168),
    )
    return BriefProjectGeneration(
        concept_image=concept.image_bytes,
        spec_render=spec_render.image_bytes,
        spec=spec,
        quality_verdict="warn",
        quality_report={
            "verdict": "warn",
            "stage": "spec_render",
            "offline_contract": True,
        },
        concept_run=concept,
        spec_render_run=spec_render,
    )


def _offline_terminal_failure(
    brief: str,
    variant: int,
) -> BriefProjectGeneration:
    plan = build_image_plan(
        ImageOperation.CONCEPT_GENERATE,
        brief,
        variant=variant,
    )
    # The closed-loop agent raises after its bounded policy is exhausted. The
    # canonical API then persists run/attempt evidence but no product records.
    JewelryImageAgent(
        _OfflineProvider(_png((170, 80, 80))),
        _OfflineEvaluator(QualityVerdict.FAIL),
    ).run(plan)
    raise RuntimeError("offline terminal evaluator unexpectedly returned")


def _contract_scenario(
    outdir: Path,
    request: ProjectFromBriefRequest,
    generator: BriefProjectGenerator,
    *,
    test_accept_concept_warning: bool,
    test_accept_spec_warning: bool,
    continuation: Callable[..., BriefProjectGeneration] | None = None,
) -> dict[str, Any]:
    import facetta.trusted_brief as trusted_brief

    original_continuation = trusted_brief.continue_trusted_brief_project
    if continuation is not None:
        trusted_brief.continue_trusted_brief_project = continuation
    try:
        with _isolated_client(generator) as (client, sessions):
            return _exercise_flow(
                client,
                sessions,
                request,
                outdir,
                test_accept_concept_warning=test_accept_concept_warning,
                test_accept_spec_warning=test_accept_spec_warning,
            )
    finally:
        trusted_brief.continue_trusted_brief_project = original_continuation


def run_contract(
    outdir: Path,
    request: ProjectFromBriefRequest,
    *,
    test_accept_concept_warning: bool,
    test_accept_spec_warning: bool,
) -> dict[str, Any]:
    contracts = _prompt_contracts(request.brief, request.variant)
    scenarios: dict[str, dict[str, Any]] = {}

    pass_dir = outdir / "pass"
    pass_dir.mkdir()
    scenarios["pass"] = _contract_scenario(
        pass_dir,
        request,
        _offline_pass_generation,
        test_accept_concept_warning=False,
        test_accept_spec_warning=False,
    )

    concept_dir = outdir / "concept-warning"
    concept_dir.mkdir()

    def continuation(brief, variant, concept, *, agent=None):
        del agent
        return _offline_pass_generation(
            brief,
            variant,
            reviewed_concept=concept,
        )

    scenarios["concept_warning"] = _contract_scenario(
        concept_dir,
        request,
        _offline_concept_warning,
        test_accept_concept_warning=test_accept_concept_warning,
        test_accept_spec_warning=False,
        continuation=continuation,
    )

    spec_dir = outdir / "spec-warning"
    spec_dir.mkdir()
    scenarios["spec_warning"] = _contract_scenario(
        spec_dir,
        request,
        _offline_spec_warning,
        test_accept_concept_warning=False,
        test_accept_spec_warning=test_accept_spec_warning,
    )

    failure_dir = outdir / "terminal-failure"
    failure_dir.mkdir()
    scenarios["terminal_failure"] = _contract_scenario(
        failure_dir,
        request,
        _offline_terminal_failure,
        test_accept_concept_warning=False,
        test_accept_spec_warning=False,
    )
    terminal = scenarios["terminal_failure"]
    if terminal["status"] != "terminal_failure":
        raise RuntimeError("offline terminal-failure scenario did not fail")
    if terminal["partial_product_records"]:
        raise RuntimeError("terminal failure left partial product records")

    result = {
        "mode": "contract",
        "live": False,
        "provider_calls": 0,
        "provider_cost": 0,
        "request": request.model_dump(mode="json"),
        "prompt_contracts": contracts,
        "test_acceptance_flags": {
            "concept_warning": test_accept_concept_warning,
            "spec_render_warning": test_accept_spec_warning,
        },
        "test_actor": request.owner,
        "test_actor_is_founder": False,
        "test_actor_is_designer_approval": False,
        "scenarios": scenarios,
    }
    _write_json(outdir / "results.json", result)
    (outdir / "report.md").write_text(
        "# Prompt-to-project contract evaluation\n\n"
        "The canonical HTTP route passed deterministic offline contract checks. "
        "Warning candidates were saved with previews and image-run evidence. "
        "No warning was accepted unless its explicit test flag was supplied. "
        "Terminal quality failure created no partial design, version, asset, or "
        "project records. Any flagged acceptance is an unapproved test actor, "
        "not founder, designer, factory, or GIA approval.\n"
    )
    return result


def run_live(
    outdir: Path,
    request: ProjectFromBriefRequest,
    *,
    confirm_paid_provider_calls: bool,
    test_accept_concept_warning: bool,
    test_accept_spec_warning: bool,
) -> dict[str, Any]:
    if not confirm_paid_provider_calls:
        raise SystemExit(
            "live mode can use provider credits; rerun with "
            "--confirm-paid-provider-calls"
        )
    load_env_file(ROOT / ".env")
    if not os.getenv("XAI_KEY"):
        raise SystemExit("live prompt-to-project evaluation requires XAI_KEY")
    contracts = _prompt_contracts(request.brief, request.variant)
    with _isolated_client() as (client, sessions):
        workflow = _exercise_flow(
            client,
            sessions,
            request,
            outdir,
            test_accept_concept_warning=test_accept_concept_warning,
            test_accept_spec_warning=test_accept_spec_warning,
        )
    result = {
        "mode": "live",
        "live": True,
        "request": request.model_dump(mode="json"),
        "prompt_contracts": contracts,
        "provider_readiness": {
            "grok_configured": True,
            "fallback_configured": bool(os.getenv("FAL_KEY")),
        },
        "test_acceptance_flags": {
            "concept_warning": test_accept_concept_warning,
            "spec_render_warning": test_accept_spec_warning,
        },
        "test_actor": request.owner,
        "test_actor_is_founder": False,
        "test_actor_is_designer_approval": False,
        "workflow": workflow,
    }
    _write_json(outdir / "results.json", result)
    (outdir / "report.md").write_text(
        "# Prompt-to-project live evaluation\n\n"
        f"Final workflow status: `{workflow['status']}`. Warning previews and "
        "image-run evidence are stored beside this report. The harness stopped "
        "at every warning not covered by an explicit test flag. Any flagged "
        "acceptance proves mechanics only and is not founder, designer, factory, "
        "or GIA-trained cofounder approval.\n"
    )
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_name")
    parser.add_argument(
        "--mode",
        choices=("preflight", "dry-run", "contract", "live"),
        default="preflight",
    )
    parser.add_argument("--brief", default=DEFAULT_BRIEF)
    parser.add_argument("--owner", default=TEST_ACTOR)
    parser.add_argument("--title", default="Prompt-to-project evaluation")
    parser.add_argument("--variant", type=int, default=0)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=ROOT / "docs" / "evals",
    )
    parser.add_argument("--confirm-paid-provider-calls", action="store_true")
    parser.add_argument("--test-accept-concept-warning", action="store_true")
    parser.add_argument("--test-accept-spec-warning", action="store_true")
    return parser


def main() -> None:
    args = _parser().parse_args()
    request = ProjectFromBriefRequest(
        brief=args.brief,
        owner=args.owner,
        title=args.title,
        collection="Prompt workflow evaluation",
        tags=["prompt-to-project", "manual-evaluation"],
        variant=args.variant,
    )
    outdir = args.output_root / args.run_name
    outdir.mkdir(parents=True, exist_ok=False)
    _write_json(outdir / "request.json", request.model_dump(mode="json"))

    if args.mode in {"preflight", "dry-run"}:
        result = run_preflight(outdir, request)
    elif args.mode == "contract":
        result = run_contract(
            outdir,
            request,
            test_accept_concept_warning=args.test_accept_concept_warning,
            test_accept_spec_warning=args.test_accept_spec_warning,
        )
    else:
        result = run_live(
            outdir,
            request,
            confirm_paid_provider_calls=args.confirm_paid_provider_calls,
            test_accept_concept_warning=args.test_accept_concept_warning,
            test_accept_spec_warning=args.test_accept_spec_warning,
        )
    print(json.dumps({
        "mode": result["mode"],
        "output": str(outdir),
        "live": result["live"],
    }, indent=2))


if __name__ == "__main__":
    main()

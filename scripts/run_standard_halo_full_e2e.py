"""Run a staged, live standard-halo designer-reference evaluation.

This manual harness uses founder-supplied ``image-112.jpg`` as an immutable
source, pairs it with explicit *test-designer* facts, independently audits the
visible-component mapping, then exercises the canonical trusted workflow:

    imported plate -> line art -> spec color -> beauty render -> approval
    -> deterministic factory pack

Every physical value is an editable reference estimate.  The script stops at
each human-review boundary unless the matching ``--test-*`` flag is supplied.
Those flags prove mechanics with an unapproved test actor; they never represent
founder, designer, factory, or GIA-trained cofounder acceptance.

Usage::

    PYTHONPATH=src uv run python scripts/run_standard_halo_full_e2e.py RUN_NAME
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from facetta.config import load_env_file  # noqa: E402
from facetta.db import Base, get_db  # noqa: E402
from facetta.dimension_provenance import (  # noqa: E402
    ESTIMATE_DISCLAIMER,
    with_reference_dimension_estimates,
)
from facetta.main import app  # noqa: E402
from facetta.image_identity import spec_visual_hash  # noqa: E402
from facetta.source_component_audit import (  # noqa: E402
    SourceComponentAuditError,
    audit_source_component_coverage,
)
from facetta.source_component_coverage import (  # noqa: E402
    SourceComponentCoverage,
    SourceVisibleComponent,
    source_component_factory_blockers,
)
from facetta.source_component_resolution import (  # noqa: E402
    valid_source_component_spec_paths,
)
from facetta.spec import Spec  # noqa: E402
from facetta.validation import validate_spec  # noqa: E402
from facetta.vocabulary import get_vocabulary  # noqa: E402


SOURCE = Path(
    "/Users/mattfb/.codex/attachments/"
    "c2fd41d0-b236-43ef-ada9-e9479718c771/image-112.jpg"
)
DESIGNER = "usr_test_designer"
TEST_ACTOR = "usr_test_actor_unapproved"


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _client() -> TestClient:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False)

    def override():
        session = sessions()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override
    return TestClient(app)


def _stone_carat(
    species: str,
    cut: str,
    length_mm: float,
    width_mm: float,
    depth_mm: float,
) -> float:
    vocabulary = get_vocabulary()
    return round(
        length_mm
        * width_mm
        * depth_mm
        * vocabulary.species(species).sg
        * vocabulary.cut(cut).shape_factor
        / 200,
        3,
    )


def _coverage() -> SourceComponentCoverage:
    components = (
        (
            "stone.center",
            "One oval blue center stone shown in the top and profile views.",
            ("stone",),
        ),
        (
            "stone.halo",
            "One continuous halo group of small round colorless stones.",
            ("side_stones[0]",),
        ),
        (
            "assembly.primary",
            "One complete oval halo ring assembly shown from multiple views.",
            ("template",),
        ),
        (
            "setting.primary",
            "Raised prong basket and gallery supporting the center and halo.",
            ("setting",),
        ),
        (
            "metal.body",
            "One continuous white-metal body across head, gallery, and shank.",
            ("metal",),
        ),
        (
            "band.shank",
            "One plain lower ring shank connected to the raised halo head.",
            ("band",),
        ),
    )
    return SourceComponentCoverage(
        source_kind="designer_plate",
        components=tuple(
            SourceVisibleComponent(
                component_id=component_id,
                source_view="plate_composite",
                source_description=description,
                source_confidence=0.9,
                canonical_spec_paths=paths,
            )
            for component_id, description, paths in components
        ),
    )


def _estimated_spec() -> Spec:
    center_dimensions = (9.0, 7.0, 4.3)
    halo_dimensions = (2.0, 2.0, 1.2)
    raw = {
        "schema_version": 1,
        "design_id": "dsn_eval_standard_halo_112",
        "version": 1,
        "created_by": DESIGNER,
        "created_at": "2026-07-11T00:00:00Z",
        "jewelry_type": "ring",
        "template": "halo_prong",
        "mode": "pro",
        "stone": {
            "species": "sapphire",
            "cut": "oval_brilliant",
            "carat": _stone_carat(
                "sapphire", "oval_brilliant", *center_dimensions
            ),
            "dimensions_mm": {
                "length": center_dimensions[0],
                "width": center_dimensions[1],
                "depth": center_dimensions[2],
            },
            "color": {
                "trade": "Royal Blue",
                "gia": "vivid blue, medium-dark tone, strong saturation",
            },
            "count": 1,
            "position": "center",
            "phenomena": [],
        },
        "setting": {
            "style": "6_prong_basket",
            "prong_count": 6,
            "prong_tip_mm": 0.8,
            "gallery_height_mm": 5.0,
        },
        "metal": {
            "material": "gold",
            "karat": 18,
            "color": "white",
            "finish": "high_polish",
        },
        "band": {
            "profile": "half_round",
            "width_mm": 2.0,
            "thickness_mm": 1.6,
        },
        "ring_size": {"system": "US", "value": 6.5},
        "side_stones": [{
            "species": "diamond",
            "cut": "round_brilliant",
            "carat": _stone_carat(
                "diamond", "round_brilliant", *halo_dimensions
            ),
            "dimensions_mm": {
                "length": halo_dimensions[0],
                "width": halo_dimensions[1],
                "depth": halo_dimensions[2],
            },
            "color": {"trade": "F", "gia": "colorless"},
            "count": 14,
            "position": "halo",
            "phenomena": [],
        }],
        "notes_to_factory": (
            "LIVE WORKFLOW TEST ONLY. Stone identity, fourteen-stone halo, "
            "ring size, six-prong setting, and every numeric value are explicit test-"
            "designer assumptions used to exercise the workflow. They are not "
            "measurements extracted from image-112.jpg and are not authority "
            "to manufacture the pictured third-party design. Center and halo "
            "carat weights are modeled estimates from the stated dimensions. "
            + ESTIMATE_DISCLAIMER
        ),
        "source_component_coverage": _coverage().model_dump(mode="json"),
    }
    spec = with_reference_dimension_estimates(
        Spec.model_validate(raw),
        source="founder evaluation source image-112.jpg",
        method="reference_vision",
        confidence=0.4,
    )
    result = validate_spec(spec, get_vocabulary())
    if not result.ok:
        raise RuntimeError(json.dumps(
            [issue.as_detail() for issue in result.issues], indent=2
        ))
    return result.spec


def _response_body(response) -> dict[str, Any]:
    try:
        value = response.json()
    except Exception:
        value = {"raw": response.text[:4000]}
    return value if isinstance(value, dict) else {"body": value}


def _record_response(response) -> dict[str, Any]:
    return {
        "http_status": response.status_code,
        "body": _response_body(response),
    }


def _image_suffix(response) -> str:
    content_type = response.headers.get("content-type", "").lower()
    return ".jpg" if "jpeg" in content_type else ".webp" if "webp" in content_type else ".png"


def _save_image_response(outdir: Path, stem: str, response) -> str | None:
    if response.status_code != 200:
        return None
    filename = stem + _image_suffix(response)
    (outdir / filename).write_bytes(response.content)
    return filename


def _save_candidate(
    client: TestClient,
    outdir: Path,
    stem: str,
    candidate: dict[str, Any],
) -> str | None:
    return _save_image_response(
        outdir,
        stem,
        client.get(candidate["preview_url"]),
    )


def _save_asset(
    client: TestClient,
    outdir: Path,
    stem: str,
    asset_id: str,
) -> str | None:
    return _save_image_response(
        outdir,
        stem,
        client.get(f"/assets/{asset_id}/image"),
    )


def _latest_derived(project: dict[str, Any], capability: str) -> dict[str, Any]:
    matches = [
        asset for asset in project["derived_assets"]
        if asset["capability"] == capability
    ]
    if not matches:
        raise RuntimeError(f"accepted project has no {capability} asset")
    return matches[-1]


def _accept_candidate(
    client: TestClient,
    candidate: dict[str, Any],
    design_version: int,
) -> dict[str, Any]:
    response = client.post(
        f"/image-runs/{candidate['run_id']}/candidates/"
        f"{candidate['candidate_id']}/accept",
        json={
            "expected_design_version": design_version,
            "created_by": TEST_ACTOR,
        },
    )
    if response.status_code != 201:
        raise RuntimeError(
            "candidate acceptance failed "
            f"{response.status_code}: {response.text[:1600]}"
        )
    return response.json()


def _factory_files(outdir: Path, archive: bytes) -> list[str]:
    names: list[str] = []
    with zipfile.ZipFile(BytesIO(archive)) as pack:
        for name in pack.namelist():
            names.append(name)
            if name in {
                "validated-spec.json",
                "facetta-sheet.svg",
                "facetta-sheet.dxf",
                "approval-manifest.json",
            } or name.startswith(("approved-reference.", "discussion-line-art.")):
                (outdir / name).write_bytes(pack.read(name))
    return names


def _write_readme(outdir: Path, run_name: str, stage: str) -> None:
    (outdir / "README.md").write_text(
        f"# Standard halo full E2E — {run_name}\n\n"
        f"Stopped at stage: `{stage}`.\n\n"
        "The founder-supplied source is used only as a local evaluation "
        "reference. All dimensions, carat weights, material choices, stone "
        "count, and ring size are editable test-designer estimates—not image "
        "measurements or manufacturing truth. Third-party captions, social "
        "IDs, signatures, logos, and watermarks must not survive into an "
        "accepted candidate.\n\n"
        "Any candidate confirmation or checklist response recorded by "
        f"`{TEST_ACTOR}` proves workflow mechanics only. It is not founder, "
        "designer, factory, or GIA-trained cofounder approval.\n"
    )


def run(
    run_name: str,
    *,
    dry_run: bool = False,
    audit_only: bool = False,
    audited_spec_path: Path | None = None,
    test_accept_line_art: bool = False,
    exercise_colored_illustration: bool = False,
    test_confirm_color: bool = False,
    test_accept_beauty_warning: bool = False,
    test_approve_factory: bool = False,
    line_view: str = "front",
) -> None:
    load_env_file(ROOT / ".env")
    outdir = ROOT / "docs" / "evals" / run_name
    outdir.mkdir(parents=True, exist_ok=True)
    source_bytes = SOURCE.read_bytes()
    spec = _estimated_spec()
    result: dict[str, Any] = {
        "run_name": run_name,
        "live": not dry_run,
        "source": str(SOURCE),
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "source_policy": (
            "Local evaluation only. Do not publish, train on, or treat as a "
            "customer-owned production asset. Remove all third-party branding."
        ),
        "estimate_disclaimer": ESTIMATE_DISCLAIMER,
        "test_actor_disclosure": (
            "All optional confirmations and approvals are automated test-actor "
            "mechanics, not founder, designer, factory, or GIA acceptance."
        ),
        "provider_scope": (
            "two source-coverage vision passes only; no image generation, "
            "project API, product asset, approval, or factory-pack call"
            if audit_only else "full staged workflow"
        ),
        "flags": {
            "audit_only": audit_only,
            "test_accept_line_art": test_accept_line_art,
            "exercise_colored_illustration": exercise_colored_illustration,
            "test_confirm_color": test_confirm_color,
            "test_accept_beauty_warning": test_accept_beauty_warning,
            "test_approve_factory": test_approve_factory,
            "line_view": line_view,
        },
        "estimated_spec_before_audit": spec.model_dump(mode="json"),
    }
    _write_json(outdir / "estimated-spec-before-audit.json", result["estimated_spec_before_audit"])
    if dry_run:
        result["stage"] = "dry_run_validated"
        _write_json(outdir / "result.json", result)
        _write_readme(outdir, run_name, result["stage"])
        return

    if audited_spec_path is not None:
        reused = Spec.model_validate(json.loads(audited_spec_path.read_text()))
        expected = spec.model_dump(mode="json")
        observed = reused.model_dump(mode="json")
        expected["source_component_coverage"] = None
        observed["source_component_coverage"] = None
        if observed != expected:
            raise RuntimeError(
                "reused exact-fact audit does not match the current test spec"
            )
        audited_coverage = reused.source_component_coverage
        if audited_coverage is None or any(
            component.independent_audit is None
            or component.independent_audit.verdict != "pass"
            for component in audited_coverage.components
        ):
            raise RuntimeError(
                "reused audited spec does not contain all-pass audit evidence"
            )
        spec = spec.model_copy(update={
            "source_component_coverage": audited_coverage,
        })
        result["source_coverage_audit_reused_from"] = str(
            audited_spec_path.resolve()
        )
    else:
        raw_audit_evidence: dict[str, object] = {}
        try:
            audited_coverage = audit_source_component_coverage(
                source_bytes,
                spec.source_component_coverage,
                spec=spec,
                evidence_sink=raw_audit_evidence.update,
            )
        except SourceComponentAuditError as exc:
            result["stage"] = "source_coverage_audit_failed"
            if raw_audit_evidence:
                result["source_coverage_raw_evidence"] = raw_audit_evidence
            result["source_coverage_audit_error"] = {
                "type": type(exc).__name__,
                "detail": str(exc),
                "debug_evidence": getattr(exc, "debug_evidence", None),
            }
            _write_json(outdir / "result.json", result)
            _write_readme(outdir, run_name, result["stage"])
            return
        result["source_coverage_raw_evidence"] = raw_audit_evidence
        spec = spec.model_copy(update={
            "source_component_coverage": audited_coverage,
        })
    validated = validate_spec(spec, get_vocabulary())
    if not validated.ok:
        raise RuntimeError(json.dumps(
            [issue.as_detail() for issue in validated.issues], indent=2
        ))
    spec = validated.spec
    blockers = source_component_factory_blockers(
        audited_coverage,
        valid_spec_paths=valid_source_component_spec_paths(spec),
        current_spec_visual_hash=spec_visual_hash(spec),
    )
    result["source_coverage_audit"] = audited_coverage.model_dump(mode="json")
    result["source_coverage_blockers"] = [
        blocker.model_dump(mode="json") for blocker in blockers
    ]
    result["audited_spec"] = spec.model_dump(mode="json")
    _write_json(outdir / "audited-estimated-spec.json", result["audited_spec"])
    if blockers:
        result["stage"] = "source_coverage_review_required"
        _write_json(outdir / "result.json", result)
        _write_readme(outdir, run_name, result["stage"])
        return
    if audit_only:
        result["stage"] = "source_coverage_audit_complete"
        _write_json(outdir / "result.json", result)
        _write_readme(outdir, run_name, result["stage"])
        return

    client = _client()
    created_response = client.post("/projects/from-image", json={
        "image_base64": base64.b64encode(source_bytes).decode(),
        "media_type": "image/jpeg",
        "spec": spec.model_dump(mode="json"),
        "owner": DESIGNER,
        "title": "Standard halo image-112 trusted E2E",
        "collection": "Founder reference acceptance",
        "tags": ["ring", "halo", "image-112", "live-eval"],
    })
    result["project_creation"] = _record_response(created_response)
    if created_response.status_code != 201:
        result["stage"] = "project_creation_failed"
        _write_json(outdir / "result.json", result)
        _write_readme(outdir, run_name, result["stage"])
        return
    project = created_response.json()
    project_id = project["root_id"]
    active_asset_id = project["active_asset_id"]
    design_version = project["active_design_version"]

    line_response = client.post(f"/projects/{project_id}/line-art", json={
        "created_by": DESIGNER,
        "expected_asset_id": active_asset_id,
        "expected_design_version": design_version,
        "view": line_view,
        "source_region_description": (
            "the single face-up ring drawing in the upper-left of the source "
            "plate; exclude both lower profile/side drawings and all captions"
        ),
        "source_region": {
            "x": 0.08,
            "y": 0.12,
            "width": 0.55,
            "height": 0.38,
        },
        "variant": 0,
    })
    result["line_art"] = _record_response(line_response)
    if line_response.status_code != 202:
        result["stage"] = "line_art_failed"
        _write_json(outdir / "result.json", result)
        _write_readme(outdir, run_name, result["stage"])
        return
    line = line_response.json()
    line_candidate = line["candidate"]
    result["line_art_candidate_file"] = _save_candidate(
        client, outdir, "line-art-candidate", line_candidate
    )
    result["line_art_run"] = _record_response(
        client.get(f"/image-runs/{line['image_run_id']}")
    )
    if not test_accept_line_art:
        result["stage"] = "line_art_review_required"
        _write_json(outdir / "result.json", result)
        _write_readme(outdir, run_name, result["stage"])
        return

    project = _accept_candidate(client, line_candidate, design_version)
    line_asset = _latest_derived(project, "LINE_ART")
    result["line_art_test_actor_acceptance"] = {
        "asset_id": line_asset["asset_id"],
        "created_by": TEST_ACTOR,
    }
    render_source_asset_id = line_asset["asset_id"]
    if exercise_colored_illustration:
        color_response = client.post(
            f"/projects/{project_id}/line-art/{line_asset['asset_id']}/colorize",
            json={
                "created_by": DESIGNER,
                "expected_asset_id": active_asset_id,
                "expected_design_version": design_version,
                "variant": 0,
            },
        )
        result["color"] = _record_response(color_response)
        if color_response.status_code == 201:
            color = color_response.json()
            render_source_asset_id = color["asset_id"]
            result["colored_line_art_file"] = _save_asset(
                client, outdir, "colored-line-art", render_source_asset_id
            )
            if not test_confirm_color:
                result["stage"] = "color_review_required"
                _write_json(outdir / "result.json", result)
                _write_readme(outdir, run_name, result["stage"])
                return
        elif color_response.status_code == 202:
            color = color_response.json()
            color_candidate = color["candidate"]
            result["colored_line_art_candidate_file"] = _save_candidate(
                client, outdir, "colored-line-art-candidate", color_candidate
            )
            result["color_run"] = _record_response(
                client.get(f"/image-runs/{color['image_run_id']}")
            )
            if not test_confirm_color:
                result["stage"] = "color_review_required"
                _write_json(outdir / "result.json", result)
                _write_readme(outdir, run_name, result["stage"])
                return
            project = _accept_candidate(
                client, color_candidate, design_version
            )
            render_source_asset_id = _latest_derived(
                project, "COLORED_LINE_ART"
            )["asset_id"]
            result["color_test_actor_acceptance"] = {
                "asset_id": render_source_asset_id,
                "created_by": TEST_ACTOR,
            }
            result["colored_line_art_test_accepted_file"] = _save_asset(
                client,
                outdir,
                "colored-line-art-test-accepted",
                render_source_asset_id,
            )
        else:
            result["stage"] = "color_failed"
            _write_json(outdir / "result.json", result)
            _write_readme(outdir, run_name, result["stage"])
            return

    beauty_response = client.post(f"/projects/{project_id}/render", json={
        "created_by": DESIGNER,
        "expected_asset_id": active_asset_id,
        "source_asset_id": render_source_asset_id,
        "expected_design_version": design_version,
        "instruction": (
            "Turn the exact confirmed black line geometry into one clean "
            "photorealistic three-quarter fine-jewelry beauty render using the "
            "validated material and stone facts. Preserve every line-defined "
            "stone, prong, setting, gallery, band contour, count, and proportion. "
            "Show one ring only on a neutral light "
            "gray studio background. Remove source-platform captions, social "
            "IDs, signatures, logos, watermarks, borders, and markup."
        ),
        "variant": 0,
    })
    result["beauty_render"] = _record_response(beauty_response)
    if beauty_response.status_code == 201:
        beauty = beauty_response.json()
        beauty_asset_id = beauty["asset_id"]
        result["beauty_file"] = _save_asset(
            client, outdir, "beauty-render", beauty_asset_id
        )
    elif beauty_response.status_code == 202:
        beauty = beauty_response.json()
        beauty_candidate = beauty["warning_candidate"]
        result["beauty_candidate_file"] = _save_candidate(
            client, outdir, "beauty-render-candidate", beauty_candidate
        )
        result["beauty_run"] = _record_response(
            client.get(f"/image-runs/{beauty['image_run_id']}")
        )
        if not test_accept_beauty_warning:
            result["stage"] = "beauty_review_required"
            _write_json(outdir / "result.json", result)
            _write_readme(outdir, run_name, result["stage"])
            return
        project = _accept_candidate(client, beauty_candidate, design_version)
        beauty_asset_id = project["active_asset_id"]
        result["beauty_test_actor_acceptance"] = {
            "asset_id": beauty_asset_id,
            "created_by": TEST_ACTOR,
        }
        result["beauty_test_accepted_file"] = _save_asset(
            client, outdir, "beauty-render-test-accepted", beauty_asset_id
        )
    else:
        result["stage"] = "beauty_render_failed"
        _write_json(outdir / "result.json", result)
        _write_readme(outdir, run_name, result["stage"])
        return

    project_response = client.get(f"/projects/{project_id}")
    project = project_response.json()
    result["project_before_approval"] = _record_response(project_response)
    if project["active_asset_id"] != beauty_asset_id:
        raise RuntimeError("beauty render is not the exact active revision")
    if not test_approve_factory:
        result["stage"] = "factory_approval_required"
        _write_json(outdir / "result.json", result)
        _write_readme(outdir, run_name, result["stage"])
        return

    checklist_response = client.post(
        f"/assets/{beauty_asset_id}/checklist",
        json={"mode": "auto_pin", "created_by": TEST_ACTOR},
    )
    result["checklist"] = _record_response(checklist_response)
    if checklist_response.status_code != 201:
        result["stage"] = "checklist_creation_failed"
        _write_json(outdir / "result.json", result)
        _write_readme(outdir, run_name, result["stage"])
        return
    checklist = checklist_response.json()
    result["checklist_responses"] = []
    for item in checklist["items"]:
        response = client.post(
            f"/assets/{beauty_asset_id}/checklist/respond",
            json={
                "item_key": item["key"],
                "approved": True,
                "created_by": TEST_ACTOR,
            },
        )
        result["checklist_responses"].append(_record_response(response))
        if response.status_code != 201:
            raise RuntimeError(
                f"checklist item {item['key']} failed: {response.text[:1200]}"
            )

    manifest_response = client.get(f"/projects/{project_id}/factory-pack")
    result["factory_manifest"] = _record_response(manifest_response)
    archive_response = client.get(f"/projects/{project_id}/factory-pack.zip")
    result["factory_archive_http_status"] = archive_response.status_code
    if manifest_response.status_code != 200 or archive_response.status_code != 200:
        result["stage"] = "factory_pack_failed"
        _write_json(outdir / "result.json", result)
        _write_readme(outdir, run_name, result["stage"])
        return
    archive = archive_response.content
    (outdir / "factory-pack.zip").write_bytes(archive)
    result["factory_pack_files"] = _factory_files(outdir, archive)
    final_response = client.get(f"/projects/{project_id}")
    result["final_project"] = _record_response(final_response)
    final_project = final_response.json()
    if not (
        final_project["factory_ready"]
        and final_project["active_asset_id"] == beauty_asset_id
        and final_project["pinned_revision"]["asset_id"] == beauty_asset_id
        and not final_project["factory_blockers"]
    ):
        raise RuntimeError("final exact-revision factory invariants failed")
    result["stage"] = "factory_pack_complete_test_actor_only"
    _write_json(outdir / "result.json", result)
    _write_readme(outdir, run_name, result["stage"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_name")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--audit-only",
        action="store_true",
        help=(
            "stop after blind inventory, exact-fact mapping, validation, and "
            "blocker calculation; never call image generation or project APIs"
        ),
    )
    parser.add_argument(
        "--audited-spec",
        type=Path,
        help=(
            "reuse an all-pass audited spec from an earlier staged run; the "
            "script revalidates that every non-audit spec fact is identical"
        ),
    )
    parser.add_argument("--test-accept-line-art", action="store_true")
    parser.add_argument(
        "--exercise-colored-illustration",
        action="store_true",
        help=(
            "exercise the optional spec-colored technical-illustration stage; "
            "the default efficient path renders directly from confirmed line art"
        ),
    )
    parser.add_argument(
        "--test-confirm-color",
        action="store_true",
        help=(
            "continue only after the saved color candidate has been visually "
            "inspected; also accepts a warning candidate with the test actor"
        ),
    )
    parser.add_argument("--test-accept-beauty-warning", action="store_true")
    parser.add_argument("--test-approve-factory", action="store_true")
    parser.add_argument(
        "--line-view",
        choices=("front", "three_quarter", "side"),
        default="front",
    )
    args = parser.parse_args()
    run(
        args.run_name,
        dry_run=args.dry_run,
        audit_only=args.audit_only,
        audited_spec_path=args.audited_spec,
        test_accept_line_art=args.test_accept_line_art,
        exercise_colored_illustration=args.exercise_colored_illustration,
        test_confirm_color=args.test_confirm_color,
        test_accept_beauty_warning=args.test_accept_beauty_warning,
        test_approve_factory=args.test_approve_factory,
        line_view=args.line_view,
    )


if __name__ == "__main__":
    main()

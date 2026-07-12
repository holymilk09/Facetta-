"""Replay one live prompt candidate into the trusted necklace factory workflow.

Without ``--confirmed-spec`` the script performs only live candidate-to-draft
reading/auditing and stops for explicit review. With a reviewed spec file it
replays the recorded live image run, audits that exact candidate against the
corrected spec, promotes it, performs test-designer approval, and writes the
deterministic factory archive. No provider output is described as factory truth.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from facetta.api.specs import PhotoRequest, from_photo
from facetta.config import load_env_file
from facetta.creative_workflow import get_creative_prompt_generator
from facetta.db import (
    Base,
    Design,
    DesignVersion,
    ImageAsset,
    ImageRun,
    Project,
    get_db,
)
from facetta.image_agent import (
    ImageAgentResult,
    ImageAttemptSummary,
    ImageOperation,
    ImageQualityReport,
    ImageRunStatus,
    ImageRunSummary,
    build_image_plan,
)
from facetta.main import app
from facetta.spec import Spec


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _response_body(response: JSONResponse) -> object:
    return json.loads(bytes(response.body))


def _draft(
    *,
    candidate_path: Path,
    output_dir: Path,
    notes: str,
    actor: str,
) -> int:
    candidate = candidate_path.read_bytes()
    result = from_photo(PhotoRequest(
        image_base64=base64.b64encode(candidate).decode("ascii"),
        media_type=("image/png" if candidate.startswith(b"\x89PNG")
                    else "image/jpeg"),
        notes=notes,
        created_by=actor,
        run_independent_audit=True,
    ))
    common = {
        "stage": "candidate_draft",
        "candidate": str(candidate_path),
        "candidate_sha256": hashlib.sha256(candidate).hexdigest(),
        "actor": actor,
        "founder_approved": False,
        "gia_cofounder_approved": False,
        "factory_authoritative": False,
    }
    if isinstance(result, JSONResponse):
        _write_json(output_dir / "results.json", {
            **common,
            "status": "draft_failed",
            "error": _response_body(result),
        })
        return 2
    if not isinstance(result, Spec):
        raise RuntimeError("photo draft endpoint returned an invalid contract")
    _write_json(output_dir / "draft-spec.json", result.model_dump(mode="json"))
    coverage = result.source_component_coverage
    _write_json(output_dir / "results.json", {
        **common,
        "status": "designer_spec_review_required",
        "draft_spec": "draft-spec.json",
        "jewelry_type": result.jewelry_type,
        "template": result.template,
        "source_component_count": len(coverage.components) if coverage else 0,
        "audit_verdicts": ({
            component.component_id: (
                component.independent_audit.verdict
                if component.independent_audit else "missing"
            )
            for component in coverage.components
        } if coverage else {}),
        "next": (
            "Review and correct every visible stone/material/component fact; "
            "supply or confirm dimensions and chain production details; then "
            "rerun with --confirmed-spec."
        ),
    })
    return 0


def _prepare_test_designer_spec(
    *,
    candidate_path: Path,
    output_dir: Path,
    actor: str,
) -> int:
    draft_path = output_dir / "draft-spec.json"
    if not draft_path.exists():
        raise SystemExit("run the draft stage before preparing corrections")
    candidate = candidate_path.read_bytes()
    candidate_sha = hashlib.sha256(candidate).hexdigest()
    raw = json.loads(draft_path.read_text())
    raw["created_by"] = actor
    raw["setting"] = {
        "style": "custom_leaf_motif",
        "prong_count": None,
        "prong_tip_mm": None,
        "gallery_height_mm": None,
    }
    raw["chain"].update({
        "pendant_connection": "split_chain",
        "geometry": {
            "construction": "open_link",
            "chain_width_mm": 1.2,
            "profile_thickness_mm": 0.45,
            "end_ring_outer_diameter_mm": 2.5,
            "link_thickness_mm": 0.25,
            "links_soldered": True,
            "links": [{
                "role": "standard",
                "length_mm": 2.4,
                "inside_length_mm": 1.9,
                "inside_width_mm": 0.7,
            }],
        },
        # A generated image cannot invent a supplier SKU or exact custom
        # drawing. Keep this absent and factory-blocking.
        "production": None,
    })
    raw["design_form"] = {
        "elements": [{
            "element_id": "vine_assembly",
            "role": "pendant_structure",
            "label": "Asymmetric branching vine and tapered drop",
            "confirmed_form_description": (
                "One asymmetric two-branch vine assembly carrying five "
                "marquise emerald leaf settings, round diamond dew-drop "
                "accents, small pavé metal leaf motifs, and one long tapered "
                "polished metal drop. Preserve the exact candidate topology."
            ),
            "symmetry": "asymmetric",
            "instance_count": 1,
            "regions": [{
                "view": "front",
                "polygons": [{
                    "points": [
                        {"x": 0.10, "y": 0.27},
                        {"x": 0.92, "y": 0.27},
                        {"x": 0.92, "y": 0.97},
                        {"x": 0.10, "y": 0.97},
                    ],
                }],
            }],
            "definition": {
                "kind": "visual_reference_only",
                "asset_id": "candidate_asset_replaced_at_runtime",
                "asset_sha256": candidate_sha,
            },
        }],
    }
    provenance = raw.setdefault("dimension_provenance", {})
    for path in (
        "chain.geometry.chain_width_mm",
        "chain.geometry.profile_thickness_mm",
        "chain.geometry.end_ring_outer_diameter_mm",
        "chain.geometry.link_thickness_mm",
        "chain.geometry.links[0].length_mm",
        "chain.geometry.links[0].inside_length_mm",
        "chain.geometry.links[0].inside_width_mm",
    ):
        provenance[path] = {
            "status": "estimated_from_reference",
            "method": "reference_vision",
            "source": "selected prompt candidate",
            "confidence": 0.35,
            "note": "Internal test-designer estimate; verify against chain sample.",
        }
    coverage = raw["source_component_coverage"]
    coverage["audited_spec_visual_hash"] = None
    for component in coverage["components"]:
        component["independent_audit"] = None
        component["designer_confirmation"] = None
        if component["component_id"] == "setting.primary":
            component["canonical_spec_paths"] = [
                "setting",
                "design_form.elements[vine_assembly]",
            ]
            component["source_description"] = (
                "custom leaf-motif holders integrated into the vine assembly"
            )
        if component["component_id"] == "assembly.primary":
            component["canonical_spec_paths"] = [
                "template",
                "design_form.elements[vine_assembly]",
            ]
            component["source_description"] = (
                "asymmetric two-branch vine and tapered-drop topology"
            )
    raw["notes_to_factory"] = (
        "INTERNAL TEST-DESIGNER DRAFT — NOT FOR PRODUCTION. Five marquise "
        "emerald leaves and round diamond accents are image-visible. All listed "
        "dimensions remain estimates. Exact vine geometry is pinned only to the "
        "visual candidate, and the chain has no approved production reference; "
        "both conditions must remain factory blockers."
    )
    confirmed = Spec.model_validate(raw)
    destination = output_dir / "test-designer-confirmed-spec.json"
    _write_json(destination, confirmed.model_dump(mode="json"))
    _write_json(output_dir / "results.json", {
        "status": "test_designer_spec_prepared",
        "stage": "spec_correction",
        "candidate": str(candidate_path),
        "candidate_sha256": candidate_sha,
        "confirmed_spec": destination.name,
        "actor": actor,
        "founder_approved": False,
        "gia_cofounder_approved": False,
        "factory_authoritative": False,
        "intentional_factory_blockers": [
            "visual_reference_not_dimensioned",
            "chain_production_reference_missing",
        ],
        "next": (
            "Re-audit the corrected mappings against the exact candidate, "
            "confirm only inconclusive visible facts, and prove factory export "
            "remains blocked."
        ),
    })
    return 0


def _recorded_result(candidate_path: Path) -> ImageAgentResult:
    summary_path = candidate_path.parent / "summary.json"
    summary = json.loads(summary_path.read_text())
    prompt = str(summary["designer_prompt"])
    variant = int(summary["variant"])
    plan = build_image_plan(
        ImageOperation.CREATIVE_GENERATE,
        prompt,
        variant=variant,
        style_constraints=(
            "fine-jewelry product rendering with believable material response",
            "clean presentation with the complete jewelry piece reviewable",
            "designer-facing concept quality rather than generic clip art",
        ),
    )
    if plan.prompt_version != summary["prompt_version"]:
        raise SystemExit(
            "recorded candidate prompt version no longer matches the current plan"
        )
    quality = ImageQualityReport.model_validate(summary["quality"])
    attempts = tuple(
        ImageAttemptSummary.model_validate(item)
        for item in summary["attempts"]
    )
    run = ImageRunSummary(
        status=ImageRunStatus.REVIEW_REQUIRED,
        operation=plan.operation,
        normalized_intent=plan.normalized_intent,
        prompt_version=plan.prompt_version,
        source_hash=None,
        spec_visual_hash=plan.spec_visual_hash,
        variant=plan.variant,
        verdict=quality.verdict,
        attempts=attempts,
        selected_attempt=attempts[-1].attempt_number,
        output_hash=str(summary["candidate_sha256"]),
    )
    return ImageAgentResult(
        plan=plan,
        run=run,
        image_bytes=candidate_path.read_bytes(),
        quality=quality,
        accepted=False,
        review_required=True,
    )


def _api_json(response) -> object:
    try:
        return response.json()
    except Exception:
        return {"raw": response.text}


def _continue_with_confirmed_spec(
    *,
    candidate_path: Path,
    output_dir: Path,
    confirmed_spec_path: Path,
    actor: str,
) -> int:
    recorded = _recorded_result(candidate_path)
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db():
        with Session() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_creative_prompt_generator] = (
        lambda: (lambda _prompt, _variant: recorded)
    )
    client = TestClient(app)
    evidence: dict[str, object] = {
        "stage": "prompt_candidate_to_factory_gate",
        "candidate": str(candidate_path),
        "candidate_sha256": hashlib.sha256(
            candidate_path.read_bytes()).hexdigest(),
        "recorded_image_run_replayed": True,
        "new_image_generation_calls": 0,
        "actor": actor,
        "founder_approved": False,
        "gia_cofounder_approved": False,
        "factory_authoritative": False,
    }
    try:
        created = client.post("/projects/from-prompt", json={
            "prompt": recorded.plan.intent,
            "variation_count": 1,
            "starting_variant": recorded.plan.variant,
            "owner": actor,
            "title": "Internal floral lariat factory-readiness test",
            "collection": "Internal E2E",
            "tags": ["prompt-live-replay", "necklace", "not-for-production"],
        })
        if created.status_code != 201:
            evidence.update({
                "status": "project_creation_failed",
                "http_status": created.status_code,
                "error": _api_json(created),
            })
            _write_json(output_dir / "results.json", evidence)
            return 2
        project = created.json()
        candidate_id = project["revisions"][0]["asset_id"]
        raw_spec = json.loads(confirmed_spec_path.read_text())
        definition = raw_spec["design_form"]["elements"][0]["definition"]
        definition["asset_id"] = candidate_id
        confirmed = Spec.model_validate(raw_spec)

        audited_response = client.post(
            f"/projects/{project['id']}/creative-candidates/"
            f"{candidate_id}/source-coverage/resolve",
            json={
                "spec": confirmed.model_dump(mode="json"),
                "resolutions": [],
                "created_by": actor,
                "run_independent_audit": True,
            },
        )
        audited_body = _api_json(audited_response)
        _write_json(output_dir / "corrected-source-reaudit.json", audited_body)
        if audited_response.status_code != 200 or not isinstance(audited_body, dict):
            evidence.update({
                "status": "corrected_source_reaudit_failed",
                "http_status": audited_response.status_code,
            })
            _write_json(output_dir / "results.json", evidence)
            return 2
        audited_spec = Spec.model_validate(audited_body["spec"])
        coverage = audited_spec.source_component_coverage
        if coverage is None:
            raise RuntimeError("corrected re-audit lost source coverage")
        hard_failures = [
            component.component_id
            for component in coverage.components
            if (
                component.independent_audit is None
                or component.independent_audit.verdict == "fail"
                or component.unresolved_reason is not None
            )
        ]
        if hard_failures:
            evidence.update({
                "status": "spec_or_mapping_correction_required",
                "hard_failure_component_ids": hard_failures,
                "factory_authoritative": False,
            })
            _write_json(output_dir / "results.json", evidence)
            return 0

        inconclusive = [
            component
            for component in coverage.components
            if (
                component.independent_audit is not None
                and component.independent_audit.verdict == "inconclusive"
            )
        ]
        if inconclusive:
            confirmations = []
            for component in inconclusive:
                designer_target = component.component_id == "metal.body"
                confirmations.append({
                    "component_id": component.component_id,
                    "basis": (
                        "designer_defined_target" if designer_target
                        else "visible_source"
                    ),
                    "confirmed_description": (
                        "Internal test designer confirms the platinum target; "
                        "the raster proves only white-metal appearance."
                        if designer_target else
                        "Internal test designer reviewed the exact candidate "
                        f"and confirms this mapped component: {component.source_description}"
                    ),
                })
            confirmation_response = client.post(
                f"/projects/{project['id']}/creative-candidates/"
                f"{candidate_id}/source-coverage/confirm",
                json={
                    "spec": audited_spec.model_dump(mode="json"),
                    "confirmations": confirmations,
                    "created_by": actor,
                },
            )
            confirmation_body = _api_json(confirmation_response)
            _write_json(
                output_dir / "test-designer-confirmations.json",
                confirmation_body,
            )
            if confirmation_response.status_code != 200:
                evidence.update({
                    "status": "inconclusive_confirmation_failed",
                    "http_status": confirmation_response.status_code,
                })
                _write_json(output_dir / "results.json", evidence)
                return 2
            audited_spec = Spec.model_validate(confirmation_body["spec"])

        promoted_response = client.post(
            f"/projects/{project['id']}/creative-candidates/"
            f"{candidate_id}/promote",
            json={
                "spec": audited_spec.model_dump(mode="json"),
                "created_by": actor,
            },
        )
        promoted_body = _api_json(promoted_response)
        _write_json(output_dir / "promoted-project.json", promoted_body)
        if promoted_response.status_code != 200 or not isinstance(promoted_body, dict):
            evidence.update({
                "status": "promotion_failed",
                "http_status": promoted_response.status_code,
            })
            _write_json(output_dir / "results.json", evidence)
            return 2

        active_id = str(promoted_body["active_asset_id"])
        checklist_response = client.post(
            f"/assets/{active_id}/checklist",
            json={"created_by": actor, "mode": "auto_pin"},
        )
        checklist = checklist_response.json()
        for item in checklist.get("items", []):
            response = client.post(
                f"/assets/{active_id}/checklist/respond",
                json={
                    "item_key": item["key"],
                    "approved": True,
                    "note": (
                        "Internal E2E fact acceptance only; this does not "
                        "resolve recorded factory blockers."
                    ),
                    "created_by": actor,
                },
            )
            if response.status_code != 201:
                raise RuntimeError(
                    f"checklist response failed: {response.status_code} {response.text}"
                )
        final_project = client.get(f"/projects/{project['id']}").json()
        _write_json(output_dir / "approved-blocked-project.json", final_project)
        pack_response = client.get(f"/projects/{project['id']}/factory-pack")
        pack_body = _api_json(pack_response)
        _write_json(output_dir / "factory-pack-block.json", pack_body)
        sheet_response = client.get(
            f"/designs/{promoted_body['design_id']}/versions/1/sheet.svg"
        )
        if sheet_response.status_code == 200:
            (output_dir / "draft-facetta-sheet.svg").write_bytes(
                sheet_response.content)
        dxf_response = client.get(
            f"/designs/{promoted_body['design_id']}/versions/1/sheet.dxf"
        )
        dxf_body = _api_json(dxf_response)
        _write_json(output_dir / "draft-dxf-block.json", dxf_body)
        with Session() as db:
            counts = {
                "projects": db.scalar(select(func.count()).select_from(Project)),
                "designs": db.scalar(select(func.count()).select_from(Design)),
                "versions": db.scalar(
                    select(func.count()).select_from(DesignVersion)),
                "assets": db.scalar(select(func.count()).select_from(ImageAsset)),
                "image_runs": db.scalar(select(func.count()).select_from(ImageRun)),
            }
        blockers = final_project.get("factory_blockers", [])
        blocker_codes = sorted({item["code"] for item in blockers})
        expected_blockers = {
            "visual_reference_not_dimensioned",
            "chain_production_reference_missing",
        }
        safe = (
            pack_response.status_code == 409
            and expected_blockers.issubset(set(blocker_codes))
            and final_project.get("factory_ready") is False
            and sheet_response.status_code == 200
            and sheet_response.headers.get(
                "X-Facetta-Sheet-Authority"
            ) == "preliminary_not_for_production"
            and b"REFERENCE-DEFINED GEOMETRY WITHHELD" in sheet_response.content
            and b"FACTORY PRODUCTION ONLY" not in sheet_response.content
            and dxf_response.status_code == 409
            and isinstance(dxf_body, dict)
            and dxf_body.get("code") == "factory_geometry_incomplete"
        )
        evidence.update({
            "status": (
                "factory_release_blocked_as_designed"
                if safe else "factory_gate_regression"
            ),
            "project_id": project["id"],
            "candidate_asset_id": candidate_id,
            "promoted_asset_id": active_id,
            "design_id": promoted_body["design_id"],
            "design_version": 1,
            "source_reaudit_inconclusive_count": len(inconclusive),
            "factory_ready": final_project.get("factory_ready"),
            "factory_blocker_codes": blocker_codes,
            "factory_pack_http_status": pack_response.status_code,
            "factory_pack_error": pack_body,
            "draft_sheet": (
                "draft-facetta-sheet.svg"
                if sheet_response.status_code == 200 else None
            ),
            "draft_sheet_authority": sheet_response.headers.get(
                "X-Facetta-Sheet-Authority"
            ),
            "dxf_http_status": dxf_response.status_code,
            "dxf_error": dxf_body,
            "database_counts": counts,
            "factory_authoritative": False,
        })
        _write_json(output_dir / "results.json", evidence)
        return 0 if safe else 3
    finally:
        app.dependency_overrides.clear()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--confirmed-spec", type=Path)
    parser.add_argument("--prepare-test-confirmed-spec", action="store_true")
    parser.add_argument("--actor", default="usr_internal_designer_e2e")
    parser.add_argument("--notes", default=(
        "Prompt-selected platinum floral lariat necklace. Exactly five "
        "marquise emerald leaves and one long polished tapered drop are "
        "designer-required. Diamond accents are visible. All dimensions are "
        "estimates until explicitly confirmed."
    ))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    load_env_file()
    if args.prepare_test_confirmed_spec:
        return _prepare_test_designer_spec(
            candidate_path=args.candidate,
            output_dir=args.output_dir,
            actor=args.actor,
        )
    if args.confirmed_spec is not None:
        return _continue_with_confirmed_spec(
            candidate_path=args.candidate,
            output_dir=args.output_dir,
            confirmed_spec_path=args.confirmed_spec,
            actor=args.actor,
        )
    return _draft(
        candidate_path=args.candidate,
        output_dir=args.output_dir,
        notes=args.notes,
        actor=args.actor,
    )


if __name__ == "__main__":
    raise SystemExit(main())

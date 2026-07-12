"""Run a live persisted necklace chain-style catalog evaluation.

This manual evaluation has two deliberately different source modes:

* ``--generated-control`` creates one clean, single-necklace control that may
  proceed only after an independent source-component audit passes.
* The default founder plate contains two separate necklace assemblies. Its
  second assembly is explicitly unresolved, so it is a negative control that
  must stop before project persistence.

All dimensions and production references are explicit test-actor values used
to exercise the workflow. They are not claims about a pictured design and
never become founder approval.

Usage:
    PYTHONPATH=src uv run python scripts/run_necklace_chain_catalog_eval.py RUN_NAME
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from facetta.config import load_env_file  # noqa: E402
from facetta.db import Base, get_db  # noqa: E402
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
    "c2fd41d0-b236-43ef-ada9-e9479718c771/image-33.jpg"
)


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _write_readme(
    outdir: Path,
    *,
    run_name: str,
    generated_control: bool,
    stage: str,
) -> None:
    if generated_control:
        source_note = (
            "The source is a generated single-necklace reliability control. "
            "It can be persisted only after independent component coverage "
            "passes with no factory blockers."
        )
    else:
        source_note = (
            "Founder-supplied image-33.jpg is an intentional multi-design "
            "negative control. Its second complete necklace remains explicitly "
            "unresolved, so the correct outcome is to stop before persistence."
        )
    (outdir / "README.md").write_text(
        f"# Necklace chain catalog live eval — {run_name}\n\n"
        f"Stage: `{stage}`.\n\n"
        f"{source_note}\n\n"
        "If source coverage passes, the catalog requests cable to curb while "
        "freezing the flower pendant, stones, setting, clasp, length, drape, "
        "and non-chain geometry. Raster-unprovable dimensions remain a "
        "designer-review warning; no warning candidate is accepted "
        "automatically. Test dimensions and references are workflow fixtures, "
        "not factory authorization.\n"
    )


def _coverage(*, generated_control: bool) -> SourceComponentCoverage:
    """Describe every expected major necklace component before blind audit."""
    components = [
        SourceVisibleComponent(
            component_id="assembly.primary",
            source_view="plate_composite",
            source_description=(
                "One complete flower-pendant necklace assembly selected for "
                "this specification."
            ),
            source_confidence=0.95,
            canonical_spec_paths=("template",),
        ),
        SourceVisibleComponent(
            component_id="chain.primary",
            source_view="plate_composite",
            source_description=(
                "One thin yellow-gold cable chain attached to the selected "
                "flower pendant; no clasp is visible in the source."
            ),
            source_confidence=0.9,
            canonical_spec_paths=("chain",),
        ),
        SourceVisibleComponent(
            component_id="pendant.primary",
            source_view="plate_composite",
            source_description=(
                "One small five-petal flower pendant connected to the selected "
                "chain."
            ),
            source_confidence=0.95,
            canonical_spec_paths=("pendant",),
        ),
        SourceVisibleComponent(
            component_id="stone.center",
            source_view="plate_composite",
            source_description=(
                "One green square cushion center stone in the selected flower."
            ),
            source_confidence=0.95,
            canonical_spec_paths=("stone",),
        ),
        SourceVisibleComponent(
            component_id="stone.petals",
            source_view="plate_composite",
            source_description=(
                "One group of exactly five white pear-shaped stones arranged "
                "as petals around the green center."
            ),
            source_confidence=0.9,
            canonical_spec_paths=("side_stones[0]",),
        ),
        SourceVisibleComponent(
            component_id="setting.primary",
            source_view="plate_composite",
            source_description=(
                "The visible gold setting structure holding the center and "
                "petal stones in the selected flower head."
            ),
            source_confidence=0.82,
            canonical_spec_paths=("setting",),
        ),
        SourceVisibleComponent(
            component_id="metal.body",
            source_view="plate_composite",
            source_description=(
                "Yellow-gold metal across the selected chain, pendant, and "
                "stone-setting structure."
            ),
            source_confidence=0.92,
            canonical_spec_paths=("metal",),
        ),
    ]
    if not generated_control:
        components.append(SourceVisibleComponent(
            component_id="assembly.secondary",
            source_view="plate_composite",
            source_description=(
                "A second complete flower-pendant necklace assembly is visible "
                "in the lower-left of the founder plate."
            ),
            source_confidence=0.99,
            unresolved_reason=(
                "No designer-confirmed source-region selection or separate "
                "specification identifies how this second necklace should be "
                "represented."
            ),
        ))
    return SourceComponentCoverage(
        source_kind=(
            "imported_reference" if generated_control else "designer_plate"
        ),
        components=tuple(components),
    )


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


def _source_spec(
    *,
    dimension_source: str = "founder eval image-33.jpg",
    generated_control: bool = False,
) -> Spec:
    raw = {
        "schema_version": 1,
        "design_id": "dsn_eval_founder_flower_necklace",
        "version": 1,
        "created_by": "usr_test_designer",
        "created_at": "2026-07-11T00:00:00Z",
        "jewelry_type": "necklace",
        "template": "cluster_pendant",
        "mode": "pro",
        "stone": {
            "species": "emerald",
            "cut": "cushion",
            "carat": 0.46,
            "dimensions_mm": {"length": 5.0, "width": 5.0, "depth": 3.1},
            "color": {"trade": "Muzo Green", "gia": "medium vivid green"},
            "clarity": None,
            "origin": None,
            "treatment": None,
            "phenomena": [],
        },
        "setting": {
            "style": "prong_cluster",
            "prong_count": 4,
            "prong_tip_mm": 0.6,
        },
        "metal": {
            "material": "gold",
            "karat": 18,
            "color": "yellow",
            "finish": "high_polish",
        },
        "pendant": {
            "bail_inner_diameter_mm": 3.0,
            "bail_height_mm": 4.0,
            "drop_mm": 18.0,
        },
        "chain": {
            "style": "cable",
            "length_mm": 450.0,
            "clasp": "lobster",
            "pendant_connection": "slides_through_bail",
            "geometry": {
                "construction": "open_link",
                "chain_width_mm": 1.0,
                "profile_thickness_mm": 0.35,
                "end_ring_outer_diameter_mm": 2.0,
                "link_thickness_mm": 0.2,
                "links_soldered": True,
                "links": [{
                    "role": "standard",
                    "length_mm": 2.0,
                    "inside_length_mm": 1.5,
                    "inside_width_mm": 0.6,
                }],
            },
            "production": {
                "mode": "custom",
                "reference_kind": "dimensioned_drawing",
                "reference": "eval-source-cable-geometry-v1",
            },
        },
        "side_stones": [{
            "species": "diamond",
            "cut": "pear",
            "carat": 0.05,
            "dimensions_mm": {"length": 3.0, "width": 2.0, "depth": 1.3},
            "color": {"trade": "colorless", "gia": "F"},
            "clarity": None,
            "origin": None,
            "treatment": None,
            "phenomena": [],
            "count": 5,
            "position": "flower_petals",
        }],
        "notes_to_factory": (
            "LIVE WORKFLOW TEST ONLY. Test-actor geometry approximates the "
            "visible flower necklace and is not a measurement or license to "
            "manufacture the pictured third-party design."
        ),
        "dimension_provenance": {
            path: {
                "status": "estimated_from_reference",
                "method": "reference_vision",
                "source": dimension_source,
                "confidence": 0.45,
                "note": "Test estimate; designer measurement required.",
            }
            for path in (
                "stone.dimensions_mm.length",
                "stone.dimensions_mm.width",
                "stone.dimensions_mm.depth",
                "pendant.bail_inner_diameter_mm",
                "pendant.bail_height_mm",
                "pendant.drop_mm",
                "chain.geometry.chain_width_mm",
                "chain.geometry.profile_thickness_mm",
                "chain.geometry.end_ring_outer_diameter_mm",
                "chain.geometry.link_thickness_mm",
                "chain.geometry.links[0].length_mm",
                "chain.geometry.links[0].inside_length_mm",
                "chain.geometry.links[0].inside_width_mm",
            )
        },
        "source_component_coverage": _coverage(
            generated_control=generated_control
        ).model_dump(mode="json"),
    }
    spec = Spec.model_validate(raw)
    validation = validate_spec(spec, get_vocabulary())
    if not validation.ok:
        raise RuntimeError(json.dumps([
            issue.as_detail() for issue in validation.issues
        ], indent=2))
    return validation.spec


def run(run_name: str, *, generated_control: bool = False) -> None:
    load_env_file(ROOT / ".env")
    outdir = ROOT / "docs" / "evals" / run_name
    outdir.mkdir(parents=True, exist_ok=True)
    if generated_control:
        from facetta.render import generate_image

        source_bytes, _ = generate_image(
            "One and only one fine-jewelry necklace laid flat in a clean "
            "front-facing catalog composition. A single small five-petal "
            "yellow-gold flower pendant with one square cushion green emerald "
            "center and exactly five pear-shaped white diamond petals. Attach "
            "it to one thin, delicate, uniform yellow-gold cable chain. The "
            "chain ends exit the top of frame; no clasp is visible. Neutral "
            "light-gray background, even studio lighting. No second necklace, "
            "no duplicate pendant, no text, labels, signature, logo, watermark, "
            "social ID, border, hands, props, or packaging.",
            model="grok_direct",
            discriminator="necklace-chain-clean-control.v1",
        )
        (outdir / "generated-source-control.jpg").write_bytes(source_bytes)
        source_label = "generated clean single-necklace control"
    else:
        source_bytes = SOURCE.read_bytes()
        source_label = str(SOURCE)

    source_mode = (
        "generated_single_design_control" if generated_control
        else "founder_multi_design_negative_control"
    )
    result: dict[str, object] = {
        "run_name": run_name,
        "live": True,
        "source": source_label,
        "source_mode": source_mode,
        "source_policy": (
            "Generated control used only for internal reliability evaluation; "
            "not a manufacturing authorization."
            if generated_control else
            "Founder-supplied test reference only; no training, publication, "
            "ownership claim, or manufacturing authorization."
        ),
        "expected_source_outcome": (
            "audit_may_pass_and_allow_persistence"
            if generated_control else
            "unresolved_second_assembly_blocks_persistence"
        ),
        "test_actor_disclosure": (
            "All source and target measurements and drawing IDs are explicit "
            "workflow-test values. They are not designer/founder/GIA approval."
        ),
    }
    spec = _source_spec(
        dimension_source=source_label,
        generated_control=generated_control,
    )
    result["pre_audit_source_spec"] = spec.model_dump(mode="json")

    coverage = spec.source_component_coverage
    if coverage is None:  # pragma: no cover - constructed above
        raise AssertionError("new necklace imports require source coverage")
    try:
        audited_coverage = audit_source_component_coverage(
            source_bytes,
            coverage,
            spec=spec,
        )
    except SourceComponentAuditError as exc:
        result["stage"] = "source_coverage_audit_failed"
        result["source_coverage_audit_error"] = {
            "type": type(exc).__name__,
            "detail": str(exc),
            "debug_evidence": getattr(exc, "debug_evidence", None),
        }
        _write_json(outdir / "results.json", result)
        _write_readme(
            outdir,
            run_name=run_name,
            generated_control=generated_control,
            stage=str(result["stage"]),
        )
        print(json.dumps({
            "stage": result["stage"],
            "result": str(outdir / "results.json"),
        }, indent=2))
        return

    spec = spec.model_copy(update={
        "source_component_coverage": audited_coverage,
    })
    validated = validate_spec(spec, get_vocabulary())
    if not validated.ok:
        result["stage"] = "post_audit_spec_validation_failed"
        result["validation_issues"] = [
            issue.as_detail() for issue in validated.issues
        ]
        _write_json(outdir / "results.json", result)
        _write_readme(
            outdir,
            run_name=run_name,
            generated_control=generated_control,
            stage=str(result["stage"]),
        )
        return
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
    result["source_spec"] = spec.model_dump(mode="json")
    _write_json(outdir / "audited-source-spec.json", result["source_spec"])
    if blockers:
        result["stage"] = "source_coverage_review_required"
        result["project_persisted"] = False
        _write_json(outdir / "results.json", result)
        _write_readme(
            outdir,
            run_name=run_name,
            generated_control=generated_control,
            stage=str(result["stage"]),
        )
        print(json.dumps({
            "stage": result["stage"],
            "blocker_count": len(blockers),
            "result": str(outdir / "results.json"),
        }, indent=2))
        return

    client = _client()

    from facetta.media import sniff_media_type

    created_response = client.post("/projects/from-image", json={
        "image_base64": base64.b64encode(source_bytes).decode(),
        "media_type": sniff_media_type(source_bytes),
        "spec": spec.model_dump(mode="json"),
        "owner": "usr_test_designer",
        "title": "Flower-necklace chain isolation eval",
        "collection": "Designer workflow acceptance",
        "tags": ["necklace", "chain-catalog", "live-eval"],
    })
    if created_response.status_code != 201:
        try:
            creation_body = created_response.json()
        except Exception:
            creation_body = {"raw": created_response.text[:1600]}
        result["stage"] = "project_creation_failed"
        result["project_persisted"] = False
        result["project_creation"] = {
            "http_status": created_response.status_code,
            "body": creation_body,
        }
        _write_json(outdir / "results.json", result)
        _write_readme(
            outdir,
            run_name=run_name,
            generated_control=generated_control,
            stage=str(result["stage"]),
        )
        print(json.dumps({
            "stage": result["stage"],
            "http_status": created_response.status_code,
            "result": str(outdir / "results.json"),
        }, indent=2))
        return
    created = created_response.json()
    result["project_persisted"] = True
    result["project"] = created
    apply_response = client.post(
        f"/assets/{created['active_asset_id']}/catalog/apply",
        json={
            "component_path": "chain.style",
            "option_id": "curb",
            "expected_design_version": 1,
            "created_by": "usr_test_designer",
            "variant": 0,
            "chain_geometry": {
                "construction": "open_link",
                "chain_width_mm": 1.4,
                "profile_thickness_mm": 0.45,
                "end_ring_outer_diameter_mm": 2.4,
                "link_thickness_mm": 0.25,
                "links_soldered": True,
                "links": [{
                    "role": "standard",
                    "length_mm": 2.6,
                    "inside_length_mm": 2.0,
                    "inside_width_mm": 0.8,
                }],
            },
            "chain_production": {
                "mode": "custom",
                "reference_kind": "dimensioned_drawing",
                "reference": "eval-target-curb-geometry-v1",
            },
        },
    )
    try:
        apply_body = apply_response.json()
    except Exception:
        apply_body = {"raw": apply_response.text}

    candidate_file = None
    image_run = None
    if apply_response.status_code in {201, 202}:
        run_id = apply_body["image_run_id"]
        run_response = client.get(f"/image-runs/{run_id}")
        image_run = run_response.json() if run_response.status_code == 200 else {
            "status": run_response.status_code,
            "body": run_response.text,
        }
        if apply_response.status_code == 201:
            image_response = client.get(f"/assets/{apply_body['asset_id']}/image")
            candidate_file = "accepted-chain-edit.png"
        else:
            image_response = client.get(
                apply_body["warning_candidate"]["preview_url"]
            )
            candidate_file = "warning-chain-edit.png"
        if image_response.status_code == 200:
            (outdir / candidate_file).write_bytes(image_response.content)

    result["stage"] = (
        "catalog_apply_completed"
        if apply_response.status_code in {201, 202}
        else "catalog_apply_failed"
    )
    result["catalog_apply"] = {
        "http_status": apply_response.status_code,
        "body": apply_body,
    }
    result["image_run"] = image_run
    result["candidate_file"] = candidate_file
    result["auto_accepted_warning"] = False
    _write_json(outdir / "results.json", result)
    _write_readme(
        outdir,
        run_name=run_name,
        generated_control=generated_control,
        stage=str(result["stage"]),
    )
    print(json.dumps({
        "http_status": apply_response.status_code,
        "result": str(outdir / "results.json"),
        "candidate": candidate_file,
    }, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_name")
    parser.add_argument(
        "--generated-control",
        action="store_true",
        help="generate a clean single-necklace control before the persisted edit",
    )
    args = parser.parse_args()
    run(args.run_name, generated_control=args.generated_control)


if __name__ == "__main__":
    main()

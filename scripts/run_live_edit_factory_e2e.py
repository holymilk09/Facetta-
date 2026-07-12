"""Interactive live proof: reviewed render -> isolated edit -> factory pack.

This harness uses an in-memory database and a synthetic low-information source
that already passed `REFERENCE_RENDER`. It performs a real blind-first source
coverage audit, imports the exact audited spec, requests one isolated yellow-
to-rose gold catalog edit, pauses for operator visual review, then exercises
the exact-version checklist and factory pack. The operator is not represented
as founder, customer, or GIA approval.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
import zipfile
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from facetta.config import load_env_file  # noqa: E402
from facetta.db import Base, get_db  # noqa: E402
from facetta.dimension_provenance import (  # noqa: E402
    with_reference_dimension_estimates,
)
from facetta.image_identity import spec_visual_hash  # noqa: E402
from facetta.main import app  # noqa: E402
from facetta.source_component_audit import (  # noqa: E402
    audit_source_component_coverage,
)
from facetta.source_component_coverage import (  # noqa: E402
    source_component_factory_blockers,
)
from facetta.source_component_confirmation import (  # noqa: E402
    SourceComponentConfirmationInput,
    confirm_source_components,
)
from facetta.source_component_resolution import (  # noqa: E402
    valid_source_component_spec_paths,
)
from facetta.source_component_seed import (  # noqa: E402
    seed_imported_reference_coverage,
)
from facetta.spec import Spec  # noqa: E402
from facetta.validation import validate_spec  # noqa: E402
from facetta.vocabulary import get_vocabulary  # noqa: E402


SOURCE = (
    ROOT / "docs/evals/reference-render-low-information-sketch-live-v2-2026-07-11/"
    "candidate.jpg"
)


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _spec() -> Spec:
    raw = {
        "schema_version": 1,
        "design_id": "dsn_live_low_information_ring",
        "version": 1,
        "created_by": "usr_operator_review_not_founder",
        "created_at": datetime.now(UTC).isoformat(),
        "jewelry_type": "ring",
        "template": "solitaire_prong",
        "mode": "pro",
        "stone": {
            "species": "emerald",
            "cut": "oval_brilliant",
            "carat": 1.04,
            "dimensions_mm": {"length": 8.0, "width": 6.0, "depth": 4.0},
            "color": {"trade": "Muzo Green", "gia": "vivid green"},
            "clarity": {"system": "gia_type_iii", "grade": "VS"},
            "origin": None,
            "treatment": None,
            "phenomena": [],
            "count": 1,
            "position": "center",
        },
        "setting": {
            "style": "4_prong_basket",
            "prong_count": 4,
            "prong_tip_mm": 0.8,
            "gallery_height_mm": 4.0,
        },
        "metal": {
            "material": "gold",
            "karat": 18,
            "color": "yellow",
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
            "carat": 0.03,
            "dimensions_mm": {"length": 2.0, "width": 2.0, "depth": 1.2},
            "color": {"trade": "F", "gia": "colorless"},
            "clarity": {"system": "gia_diamond", "grade": "VS2"},
            "origin": None,
            "treatment": None,
            "phenomena": [],
            "count": 6,
            "position": "shoulders",
        }],
        "notes_to_factory": (
            "Synthetic live workflow fixture. Every dimension is a reference "
            "estimate pending designer measurement; unseen gallery construction "
            "is not source-observed factory truth."
        ),
    }
    validated = validate_spec(Spec.model_validate(raw), get_vocabulary())
    if not validated.ok:
        raise RuntimeError([issue.as_detail() for issue in validated.issues])
    return with_reference_dimension_estimates(
        validated.spec,
        source="synthetic low-information reference render",
        method="reference_vision",
        confidence=0.4,
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
        with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = override
    return TestClient(app)


def _expect(label: str, response, statuses: tuple[int, ...]) -> dict:
    if response.status_code not in statuses:
        raise RuntimeError(
            f"{label} returned {response.status_code}: {response.text[:1600]}")
    print(f"OK {label} [{response.status_code}]", flush=True)
    return response.json()


def _save_pack(outdir: Path, content: bytes) -> list[str]:
    names: list[str] = []
    with zipfile.ZipFile(BytesIO(content)) as archive:
        for name in archive.namelist():
            names.append(name)
            if (name.endswith((".json", ".svg", ".dxf"))
                    or name.startswith("discussion-line-art.")):
                (outdir / name).write_bytes(archive.read(name))
    return names


def run(run_name: str) -> int:
    load_env_file(ROOT / ".env")
    outdir = ROOT / "docs/evals" / run_name
    outdir.mkdir(parents=True, exist_ok=True)
    source = SOURCE.read_bytes()
    spec = _spec()
    seeded = seed_imported_reference_coverage(spec)
    audited = audit_source_component_coverage(source, seeded, spec=spec)
    spec = spec.model_copy(update={"source_component_coverage": audited})
    blockers = source_component_factory_blockers(
        audited,
        valid_spec_paths=valid_source_component_spec_paths(spec),
        current_spec_visual_hash=spec_visual_hash(spec),
        current_source_hash=hashlib.sha256(source).hexdigest(),
    )
    _write_json(outdir / "audited-spec-v1.json", spec.model_dump(mode="json"))
    _write_json(outdir / "source-audit.json", {
        "blockers": [item.model_dump(mode="json") for item in blockers],
        "component_count": len(audited.components),
        "audited_spec_visual_hash": audited.audited_spec_visual_hash,
    })
    if blockers:
        confirmation_descriptions = {
            "stone.group.001": (
                "visible_source",
                "Exactly three round shoulder stones are visible on each side, six total.",
            ),
            "setting.primary": (
                "visible_source",
                "Exactly four center-stone prongs are visible around the oval stone.",
            ),
            "metal.body": (
                "visible_source",
                "Yellow gold is visibly used for the ring shank and center setting.",
            ),
            "band.shank": (
                "designer_defined_target",
                "Half-round 2.0 x 1.6 mm shank is the intended manufacturing target; its cross-section is not measured from this source.",
            ),
        }
        confirmable = all(
            item.code == "source_component_audit_inconclusive"
            and item.component_id in confirmation_descriptions
            for item in blockers
        )
        if not confirmable:
            print("STOP non-confirmable source coverage blockers; no project created",
                  flush=True)
            return 2
        print(f"REVIEW source facts in {SOURCE}", flush=True)
        print(
            "Type CONFIRM only if the visible counts are correct and the stated "
            "shank dimensions are accepted as a designer-defined estimate:",
            flush=True,
        )
        if sys.stdin.readline().strip() != "CONFIRM":
            print("STOP operator did not confirm inconclusive source facts",
                  flush=True)
            return 2
        spec = confirm_source_components(
            spec,
            source,
            tuple(SourceComponentConfirmationInput(
                component_id=item.component_id,
                basis=confirmation_descriptions[item.component_id][0],
                confirmed_description=confirmation_descriptions[item.component_id][1],
            ) for item in blockers),
            reviewer="usr_operator_review_not_founder",
        )
        blockers = source_component_factory_blockers(
            spec.source_component_coverage,
            valid_spec_paths=valid_source_component_spec_paths(spec),
            current_spec_visual_hash=spec_visual_hash(spec),
            current_source_hash=hashlib.sha256(source).hexdigest(),
        )
        _write_json(
            outdir / "designer-confirmed-spec-v1.json",
            spec.model_dump(mode="json"),
        )
        if blockers:
            print("STOP confirmed source coverage still has blockers", flush=True)
            return 2

    client = _client()
    created = _expect(
        "create project from independently audited reference",
        client.post("/projects/from-image", json={
            "image_base64": base64.b64encode(source).decode(),
            "media_type": "image/jpeg",
            "spec": spec.model_dump(mode="json"),
            "owner": "usr_operator_review_not_founder",
            "title": "Low-information ring isolated-edit live proof",
        }),
        (201,),
    )
    project_id = created["root_id"]
    source_asset_id = created["active_asset_id"]
    edit_response = client.post(
        f"/assets/{source_asset_id}/catalog/apply",
        json={
            "component_path": "metal.color",
            "option_id": "rose",
            "expected_design_version": 1,
            "created_by": "usr_operator_review_not_founder",
            "variant": 5,
        },
    )
    edit = _expect(
        "isolated yellow-to-rose gold edit",
        edit_response,
        (201, 202, 422, 502, 503),
    )
    _write_json(outdir / "edit-response.json", {
        "http_status": edit_response.status_code,
        "body": edit,
    })
    if edit_response.status_code not in {201, 202}:
        print("STOP edit did not produce a reviewable candidate", flush=True)
        return 3

    if edit_response.status_code == 202:
        warning = edit["warning_candidate"]
        edited_bytes = client.get(warning["preview_url"]).content
        edited_name = "rose-gold-edit-warning.png"
    else:
        edited_bytes = client.get(f"/assets/{edit['asset_id']}/image").content
        edited_name = "rose-gold-edit.png"
    (outdir / edited_name).write_bytes(edited_bytes)
    print(f"REVIEW {outdir / edited_name}", flush=True)
    print("Type ACCEPT to continue to specification approval and factory pack:",
          flush=True)
    if sys.stdin.readline().strip() != "ACCEPT":
        print("STOP operator did not accept visual candidate", flush=True)
        return 4

    if edit_response.status_code == 202:
        project = _expect(
            "operator accepts warning candidate",
            client.post(
                f"/image-runs/{warning['run_id']}/candidates/"
                f"{warning['candidate_id']}/accept",
                json={
                    "expected_design_version": 1,
                    "created_by": "usr_operator_review_not_founder",
                },
            ),
            (201,),
        )
        run_id = warning["run_id"]
    else:
        project = edit["project"]
        run_id = edit["image_run_id"]
    active_id = project["active_asset_id"]
    if project["active_design_version"] != 2:
        raise RuntimeError("isolated edit did not create immutable spec v2")
    if project["spec"]["metal"]["color"] != "rose":
        raise RuntimeError("isolated edit did not persist rose-gold spec truth")

    checklist = _expect(
        "create exact edited-revision checklist",
        client.post(f"/assets/{active_id}/checklist", json={
            "mode": "auto_pin",
            "created_by": "usr_operator_review_not_founder",
        }),
        (201,),
    )
    answers = []
    for item in checklist["items"]:
        answers.append(_expect(
            f"operator test-approves {item['key']}",
            client.post(f"/assets/{active_id}/checklist/respond", json={
                "item_key": item["key"],
                "approved": True,
                "created_by": "usr_operator_review_not_founder",
            }),
            (201,),
        ))
    manifest = _expect(
        "build exact edited factory manifest",
        client.get(f"/projects/{project_id}/factory-pack"),
        (200,),
    )
    archive_response = client.get(f"/projects/{project_id}/factory-pack.zip")
    if archive_response.status_code != 200:
        raise RuntimeError(archive_response.text)
    (outdir / "factory-pack.zip").write_bytes(archive_response.content)
    pack_names = _save_pack(outdir, archive_response.content)
    final_project = _expect(
        "reload final project", client.get(f"/projects/{project_id}"), (200,))
    image_run = _expect(
        "read isolated-edit image run", client.get(f"/image-runs/{run_id}"), (200,))
    result = {
        "run_name": run_name,
        "live": True,
        "synthetic_source": True,
        "operator_disclosure": (
            "Visual review and checklist responses were performed by a Codex "
            "test operator, not the founder, a customer, or the GIA-trained cofounder."
        ),
        "source": str(SOURCE.relative_to(ROOT)),
        "source_audit_blockers": [],
        "created_project": created,
        "edit_http_status": edit_response.status_code,
        "edit": edit,
        "edited_image": edited_name,
        "image_run": image_run,
        "reviewed_project": project,
        "checklist": checklist,
        "checklist_answers": answers,
        "factory_manifest": manifest,
        "factory_pack_files": pack_names,
        "final_project": final_project,
    }
    _write_json(outdir / "result.json", result)
    print(f">> artifacts: {outdir}", flush=True)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_name")
    args = parser.parse_args()
    raise SystemExit(run(args.run_name))


if __name__ == "__main__":
    main()

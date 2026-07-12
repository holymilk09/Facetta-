"""Run the canonical designer-reference acceptance path against live Grok.

This is a manual, provider-backed evaluation and is never run in CI.  It uses
the founder-supplied leaf-ring reference that exposed the missing side-stone
failure, pairs it with an explicit test-designer-confirmed specification, then
proves:

    imported reference -> line drawing -> explicit line confirmation ->
    specification color -> exact-revision approval -> factory pack

The script labels its automated checklist and line-art decisions as test-actor
mechanics.  They are not founder or GIA approval.

Usage:
    PYTHONPATH=src uv run python scripts/run_designer_corrected_e2e.py RUN_NAME
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import zipfile
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
from facetta.main import app  # noqa: E402
from facetta.spec import Spec  # noqa: E402
from facetta.validation import validate_spec  # noqa: E402
from facetta.vocabulary import get_vocabulary  # noqa: E402


REFERENCE = (
    ROOT / "docs/evals/designer-product-photo-live-2026-07-11/"
    "warning-product-photo.png"
)
SOURCE_RESULT = (
    ROOT / "docs/evals/designer-reference-e2e-2026-07-11/result.json"
)


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _expect(label: str, response, statuses: tuple[int, ...]) -> dict:
    if response.status_code not in statuses:
        raise RuntimeError(
            f"{label} returned {response.status_code}: {response.text[:1200]}"
        )
    value = response.json()
    print(f"OK {label} [{response.status_code}]", flush=True)
    return value


def _corrected_spec() -> Spec:
    source = json.loads(SOURCE_RESULT.read_text())
    data = source["from_image"]["body"]["spec"]
    data["design_id"] = "dsn_test_designer_confirmed_leaf"
    data["created_by"] = "usr_test_designer"
    data["template"] = "leaf_shoulder_prong"
    data["side_stones"] = [
        {
            "species": "diamond",
            "cut": "marquise",
            "carat": 0.015,
            "dimensions_mm": {"length": 2.5, "width": 1.3, "depth": 0.8},
            "color": {"trade": "colorless", "gia": "F"},
            "clarity": None,
            "origin": None,
            "treatment": None,
            "phenomena": [],
            "count": 12,
            "position": "pave_leaves",
        },
        {
            "species": "diamond",
            "cut": "round_brilliant",
            "carat": 0.007,
            "dimensions_mm": {"length": 1.2, "width": 1.2, "depth": 0.73},
            "color": {"trade": "colorless", "gia": "F"},
            "clarity": None,
            "origin": None,
            "treatment": None,
            "phenomena": [],
            "count": 24,
            "position": "pave_leaves",
        },
    ]
    data["notes_to_factory"] = (
        "TEST DESIGNER-CONFIRMED SPEC: emerald center and diamond-set leaf "
        "shoulders. Side-stone sizes and counts are explicit test values for "
        "workflow validation, not measurements extracted from the photograph."
    )
    spec = Spec.model_validate(data)
    result = validate_spec(spec, get_vocabulary())
    if not result.ok:
        raise RuntimeError(
            "corrected test spec failed validation: "
            + json.dumps([issue.as_detail() for issue in result.issues])
        )
    return result.spec


def _client() -> TestClient:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False)

    def override():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override
    return TestClient(app)


def _save_factory_files(outdir: Path, archive: bytes) -> list[str]:
    names: list[str] = []
    with zipfile.ZipFile(BytesIO(archive)) as pack:
        for name in pack.namelist():
            names.append(name)
            if name in {
                "validated-spec.json",
                "facetta-sheet.svg",
                "facetta-sheet.dxf",
                "approval-manifest.json",
            } or name.startswith("discussion-line-art."):
                (outdir / name).write_bytes(pack.read(name))
    return names


def run(run_name: str, *, test_accept_color_warning: bool = False) -> None:
    load_env_file(ROOT / ".env")
    outdir = ROOT / "docs/evals" / run_name
    outdir.mkdir(parents=True, exist_ok=True)
    client = _client()
    source_bytes = REFERENCE.read_bytes()
    spec = _corrected_spec()
    _write_json(outdir / "corrected-test-spec.json", spec.model_dump(mode="json"))

    created = _expect(
        "create project from corrected reference",
        client.post(
            "/projects/from-image",
            json={
                "image_base64": base64.b64encode(source_bytes).decode(),
                "media_type": "image/jpeg",
                "spec": spec.model_dump(mode="json"),
                "owner": "usr_test_designer",
                "title": "Leaf ring corrected-spec live acceptance",
                "collection": "Founder reference acceptance",
                "tags": ["ring", "leaf", "corrected-spec", "live-eval"],
            },
        ),
        (201,),
    )
    project_id = created["root_id"]
    active_asset_id = created["active_asset_id"]

    line = _expect(
        "create line-art candidate",
        client.post(
            f"/projects/{project_id}/line-art",
            json={
                "created_by": "usr_test_designer",
                "expected_asset_id": active_asset_id,
                "expected_design_version": 1,
                "view": "three_quarter",
            },
        ),
        (202,),
    )
    line_candidate = line["candidate"]
    line_bytes = client.get(line_candidate["preview_url"]).content
    (outdir / "line-art-candidate.png").write_bytes(line_bytes)
    line_run = _expect(
        "read line-art run",
        client.get(f"/image-runs/{line['image_run_id']}"),
        (200,),
    )

    confirmed = _expect(
        "test actor confirms line-art mechanics",
        client.post(
            f"/image-runs/{line_candidate['run_id']}/candidates/"
            f"{line_candidate['candidate_id']}/accept",
            json={
                "expected_design_version": 1,
                "created_by": "usr_test_actor_unapproved",
            },
        ),
        (201,),
    )
    line_asset = next(
        asset
        for asset in confirmed["derived_assets"]
        if asset["capability"] == "LINE_ART"
    )

    color_response = client.post(
        f"/projects/{project_id}/line-art/{line_asset['asset_id']}/colorize",
        json={
            "created_by": "usr_test_designer",
            "expected_asset_id": active_asset_id,
            "expected_design_version": 1,
        },
    )
    color = _expect(
        "color confirmed line art",
        color_response,
        (201, 202, 422, 502, 503),
    )
    color_review_project = None
    if color_response.status_code == 201:
        colored_asset_id = color["asset_id"]
        colored_bytes = client.get(f"/assets/{colored_asset_id}/image").content
        (outdir / "colored-line-art.png").write_bytes(colored_bytes)
    elif color_response.status_code == 202:
        candidate = color["candidate"]
        colored_bytes = client.get(candidate["preview_url"]).content
        (outdir / "colored-line-art-warning.png").write_bytes(colored_bytes)
        if test_accept_color_warning:
            color_review_project = _expect(
                "test actor accepts reviewed color warning",
                client.post(
                    f"/image-runs/{candidate['run_id']}/candidates/"
                    f"{candidate['candidate_id']}/accept",
                    json={
                        "expected_design_version": 1,
                        "created_by": "usr_test_actor_unapproved",
                    },
                ),
                (201,),
            )
            colored_asset = next(
                asset
                for asset in color_review_project["derived_assets"]
                if asset["capability"] == "COLORED_LINE_ART"
            )
            delivered = client.get(
                f"/assets/{colored_asset['asset_id']}/image").content
            (outdir / "colored-line-art-test-accepted.png").write_bytes(delivered)
    color_run = _expect(
        "read color run",
        client.get(f"/image-runs/{color['image_run_id']}"),
        (200,),
    )

    checklist = _expect(
        "create exact-revision checklist",
        client.post(
            f"/assets/{active_asset_id}/checklist",
            json={
                "mode": "auto_pin",
                "created_by": "usr_test_actor_unapproved",
            },
        ),
        (201,),
    )
    checklist_responses: list[dict] = []
    for item in checklist["items"]:
        checklist_responses.append(
            _expect(
                f"test-approve checklist item {item['key']}",
                client.post(
                    f"/assets/{active_asset_id}/checklist/respond",
                    json={
                        "item_key": item["key"],
                        "approved": True,
                        "created_by": "usr_test_actor_unapproved",
                    },
                ),
                (201,),
            )
        )

    manifest = _expect(
        "build factory-pack manifest",
        client.get(f"/projects/{project_id}/factory-pack"),
        (200,),
    )
    archive_response = client.get(f"/projects/{project_id}/factory-pack.zip")
    if archive_response.status_code != 200:
        raise RuntimeError(
            f"factory-pack zip returned {archive_response.status_code}: "
            f"{archive_response.text[:1200]}"
        )
    archive = archive_response.content
    (outdir / "factory-pack.zip").write_bytes(archive)
    pack_files = _save_factory_files(outdir, archive)

    final_project = _expect(
        "reload final project",
        client.get(f"/projects/{project_id}"),
        (200,),
    )
    result = {
        "run_name": run_name,
        "live": True,
        "source": str(REFERENCE.relative_to(ROOT)),
        "disclosure": (
            "Line-art confirmation and checklist approval were performed by "
            "an automated test actor to prove mechanics; they are not founder "
            "or GIA-trained cofounder acceptance."
        ),
        "corrected_spec": spec.model_dump(mode="json"),
        "project_created": created,
        "line_art": line,
        "line_art_run": line_run,
        "line_art_confirmed_project": confirmed,
        "color": {
            "http_status": color_response.status_code,
            "body": color,
            "run": color_run,
            "test_actor_review_project": color_review_project,
        },
        "checklist": checklist,
        "checklist_responses": checklist_responses,
        "factory_manifest": manifest,
        "factory_pack_files": pack_files,
        "final_project": final_project,
    }
    _write_json(outdir / "result.json", result)
    (outdir / "README.md").write_text(
        f"# Corrected designer-reference E2E — {run_name}\n\n"
        "This live Grok run exercises the canonical imported-reference, "
        "line-art confirmation, specification color, exact-revision approval, "
        "and deterministic factory-pack path. The test specification explicitly "
        "records the diamond leaf stones that the prior sparse photo read missed.\n\n"
        "The automated test actor proves workflow mechanics only. It is not "
        "founder, designer, or GIA-trained cofounder visual approval."
        + (
            " The explicit test flag also exercised acceptance of a warning "
            "candidate after visual inspection.\n"
            if test_accept_color_warning else "\n"
        )
    )
    print(f">> artifacts: {outdir}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_name")
    parser.add_argument(
        "--test-accept-color-warning",
        action="store_true",
        help=(
            "exercise warning acceptance with an explicitly non-founder test "
            "actor after the candidate is written for inspection"
        ),
    )
    args = parser.parse_args()
    run(
        args.run_name,
        test_accept_color_warning=args.test_accept_color_warning,
    )


if __name__ == "__main__":
    main()

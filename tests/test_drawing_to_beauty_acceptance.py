"""Designer drawing -> confirmed line/color -> beauty -> factory acceptance.

The critical contract under test is source continuity.  Once a designer has
confirmed line art and the spec has colored that geometry, the beauty render
must use those exact colored bytes as its control source.  Falling back to the
original imported drawing would make the visible confirmation stages a dead
end even though every individual endpoint still looked green.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import facetta.api.specs as specs_mod
import facetta.image_agent as image_agent_mod
from conftest import HALO_SPEC, audited_import_spec
from facetta.db import Base, ImageAsset, ImageRun, get_db, new_id
from facetta.image_agent import (
    CheckSeverity,
    ImageOperation,
    ImageQualityReport,
    JewelryImageAgent,
    ProviderImage,
    QualityCheck,
    QualityVerdict,
)
from facetta.image_identity import spec_visual_hash
from facetta.main import app
from facetta.spec import Spec
from facetta.warning_candidates import clear_warning_candidates_for_tests


def _png(color: tuple[int, int, int]) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (180, 220), color).save(buffer, format="PNG")
    return buffer.getvalue()


DRAWING = _png((224, 218, 207))
LINE_ART = _png((250, 250, 250))
COLORED_LINE_ART = _png((46, 72, 106))
BEAUTY_RENDER = _png((91, 103, 121))
COMPETING_RENDER = _png((128, 116, 102))


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@pytest.fixture
def workflow():
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

    clear_warning_candidates_for_tests()
    app.dependency_overrides[get_db] = override
    yield TestClient(app), session_factory
    clear_warning_candidates_for_tests()
    app.dependency_overrides.clear()


def _draft_and_audited_spec() -> tuple[Spec, object]:
    raw = copy.deepcopy(HALO_SPEC)
    raw["dimension_provenance"] = {
        "band.width_mm": {
            "status": "estimated_from_reference",
            "method": "reference_vision",
            "source": "designer hand drawing",
            "confidence": 0.55,
            "note": "Designer must verify before manufacturing.",
        },
    }
    raw["source_component_coverage"] = {
        "source_kind": "designer_plate",
        "components": [{
            "component_id": "assembly.primary",
            "source_view": "plate_composite",
            "source_description": (
                "Oval halo ring with a four-prong center and plain shank."
            ),
            "source_confidence": 0.91,
            "canonical_spec_paths": [
                "stone",
                "side_stones[0]",
                "setting",
                "metal",
                "band",
            ],
        }],
    }
    draft = Spec.model_validate(raw)
    audited_raw = draft.model_dump(mode="json")
    audited_raw["source_component_coverage"]["components"][0][
        "independent_audit"
    ] = {
        "kind": "independent_component_audit",
        "verdict": "pass",
        "auditor": "skeptical-source-component-audit.v2",
        "source_view": "plate_composite",
        "observed_description": (
            "Blind inventory and exact mapping agree on the complete ring."
        ),
        "evidence_sha256": _sha256(DRAWING),
    }
    audited = Spec.model_validate(audited_raw)
    return draft, audited.source_component_coverage


def _install_plate_read(monkeypatch) -> None:
    draft, audited_coverage = _draft_and_audited_spec()
    monkeypatch.setattr(
        specs_mod,
        "read_design_plate",
        lambda image, **kwargs: {
            "jewelry_type": "ring",
            "source_view": "plate_composite",
            "stones": [
                {"qty": 1, "type": "oval sapphire", "confidence": 0.94},
                {"qty": 8, "type": "round diamond halo", "confidence": 0.89},
            ],
            "metal": "18k white gold",
            "assembly": "four-prong halo ring with a plain shank",
            "measurements": [],
        },
    )
    monkeypatch.setattr(
        specs_mod.plate_spec_layer,
        "compile_plate_spec",
        lambda read, **kwargs: (
            draft,
            ["INDEPENDENT SOURCE-COVERAGE AUDIT REQUIRED before factory release"],
        ),
    )
    monkeypatch.setattr(
        specs_mod,
        "audit_source_component_coverage",
        lambda image, coverage, *, spec: audited_coverage.model_copy(update={
            "audited_spec_visual_hash": spec_visual_hash(spec),
        }),
    )


def _install_image_agent(
    monkeypatch,
    *,
    beauty_verdict: QualityVerdict = QualityVerdict.PASS,
) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []
    real_agent = JewelryImageAgent

    class Provider:
        def execute(
            self,
            plan,
            route,
            prompt,
            *,
            source_image,
            mask_bytes,
        ):
            if plan.operation is ImageOperation.SPEC_RENDER:
                output = BEAUTY_RENDER
                stage = "beauty"
            elif "monochrome" in plan.expected_output.lower():
                output = LINE_ART
                stage = "line_art"
            else:
                output = COLORED_LINE_ART
                stage = "color"
            calls.append({
                "stage": stage,
                "plan": plan,
                "source_image": source_image,
                "mask_bytes": mask_bytes,
            })
            return ProviderImage(
                image_bytes=output,
                provider_request_id=f"req_{stage}",
            )

    class Evaluator:
        def evaluate(self, plan, candidate, *, source_image, mask_bytes):
            verdict = (
                beauty_verdict
                if plan.operation is ImageOperation.SPEC_RENDER
                else QualityVerdict.PASS
            )
            return ImageQualityReport(
                verdict=verdict,
                checks=(QualityCheck(
                    code="designer_source_continuity",
                    passed=verdict is QualityVerdict.PASS,
                    severity=(
                        CheckSeverity.WARNING
                        if verdict is QualityVerdict.WARN
                        else CheckSeverity.HARD
                    ),
                    message=(
                        "designer must review a subtle source-continuity detail"
                        if verdict is QualityVerdict.WARN
                        else "candidate preserves the confirmed designer source"
                    ),
                ),),
                score=88 if verdict is QualityVerdict.WARN else 98,
            )

    class FakeAgent:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, plan, *, source_image=None, mask_bytes=None):
            return real_agent(Provider(), Evaluator()).run(
                plan,
                source_image=source_image,
                mask_bytes=mask_bytes,
            )

    monkeypatch.setattr(image_agent_mod, "JewelryImageAgent", FakeAgent)
    return calls


def _approve(client: TestClient, asset_id: str) -> None:
    created = client.post(
        f"/assets/{asset_id}/checklist",
        json={"created_by": "usr_designer", "mode": "auto_pin"},
    )
    assert created.status_code == 201, created.text
    for item in created.json()["items"]:
        response = client.post(
            f"/assets/{asset_id}/checklist/respond",
            json={
                "item_key": item["key"],
                "approved": True,
                "created_by": "usr_designer",
            },
        )
        assert response.status_code == 201, response.text


def test_confirmed_colored_line_art_is_the_beauty_render_control_source(
    workflow,
    monkeypatch,
):
    client, session_factory = workflow
    _install_plate_read(monkeypatch)
    calls = _install_image_agent(monkeypatch)

    plate = client.post("/specs/from-plate", json={
        "image_base64": base64.b64encode(DRAWING).decode(),
        "created_by": "usr_designer",
        "run_independent_audit": True,
    })
    assert plate.status_code == 200, plate.text
    plate_body = plate.json()
    assert plate_body["requires_designer_confirmation"] is True
    assert plate_body["source_coverage_audit"] == {
        "status": "pass",
        "blocker_count": 0,
    }

    created = client.post("/projects/from-image", json={
        "image_base64": base64.b64encode(DRAWING).decode(),
        "media_type": "image/png",
        "spec": plate_body["spec"],
        "owner": "usr_designer",
        "title": "Confirmed hand-drawn halo",
    })
    assert created.status_code == 201, created.text
    project = created.json()
    root_id = project["root_id"]
    active_v1 = project["active_asset_id"]

    line = client.post(f"/projects/{root_id}/line-art", json={
        "created_by": "usr_designer",
        "expected_asset_id": active_v1,
        "expected_design_version": 1,
        "view": "three_quarter",
        "source_region_description": (
            "the single face-up ring drawing selected by the designer"
        ),
    })
    assert line.status_code == 202, line.text
    line_candidate = line.json()["candidate"]
    confirmed = client.post(
        f"/image-runs/{line_candidate['run_id']}/candidates/"
        f"{line_candidate['candidate_id']}/accept",
        json={
            "expected_design_version": 1,
            "created_by": "usr_designer",
        },
    )
    assert confirmed.status_code == 201, confirmed.text
    line_asset = next(
        item for item in confirmed.json()["derived_assets"]
        if item["capability"] == "LINE_ART"
    )

    color = client.post(
        f"/projects/{root_id}/line-art/{line_asset['asset_id']}/colorize",
        json={
            "created_by": "usr_designer",
            "expected_asset_id": active_v1,
            "expected_design_version": 1,
        },
    )
    assert color.status_code == 201, color.text
    colored_asset = next(
        item for item in color.json()["project"]["derived_assets"]
        if item["capability"] == "COLORED_LINE_ART"
    )

    render_calls_before = sum(
        call["stage"] == "beauty" for call in calls
    )
    foreign = client.post("/projects/from-image", json={
        "image_base64": base64.b64encode(DRAWING).decode(),
        "media_type": "image/png",
        "spec": plate_body["spec"],
        "owner": "usr_other_designer",
        "title": "Foreign project",
    })
    assert foreign.status_code == 201, foreign.text
    foreign_source = client.post(f"/projects/{root_id}/render", json={
        "created_by": "usr_designer",
        "expected_asset_id": active_v1,
        "source_asset_id": foreign.json()["active_asset_id"],
        "expected_design_version": 1,
    })
    assert foreign_source.status_code == 422, foreign_source.text
    assert foreign_source.json()["code"] == "beauty_source_invalid"
    assert sum(call["stage"] == "beauty" for call in calls) == (
        render_calls_before
    )

    stale = client.post(f"/projects/{root_id}/render", json={
        "created_by": "usr_designer",
        "expected_asset_id": "ast_stale_primary",
        "source_asset_id": colored_asset["asset_id"],
        "expected_design_version": 1,
    })
    assert stale.status_code == 409, stale.text
    assert stale.json()["code"] == "stale_asset_revision"
    assert sum(call["stage"] == "beauty" for call in calls) == (
        render_calls_before
    )

    rendered = client.post(f"/projects/{root_id}/render", json={
        "created_by": "usr_designer",
        "expected_asset_id": active_v1,
        "source_asset_id": colored_asset["asset_id"],
        "expected_design_version": 1,
        "instruction": (
            "Create a photorealistic beauty render from the exact designer-"
            "confirmed colored line art and validated specification."
        ),
    })
    assert rendered.status_code == 201, rendered.text
    render_body = rendered.json()
    beauty_asset_id = render_body["asset_id"]
    beauty_call = next(call for call in calls if call["stage"] == "beauty")
    assert beauty_call["source_image"] == COLORED_LINE_ART
    assert beauty_call["plan"].source_hash == _sha256(COLORED_LINE_ART)

    with session_factory() as db:
        beauty = db.get(ImageAsset, beauty_asset_id)
        run = db.get(ImageRun, render_body["image_run_id"])
        assert beauty.parent_asset_id == colored_asset["asset_id"]
        assert bytes(beauty.image) == BEAUTY_RENDER
        assert run.source_asset_id == colored_asset["asset_id"]
        assert run.accepted_asset_id == beauty_asset_id

    final_project = client.get(f"/projects/{root_id}").json()
    assert final_project["active_asset_id"] == beauty_asset_id
    assert final_project["active_design_version"] == 1
    assert final_project["primary_revision_count"] == 2

    sibling_line_id = new_id("ast")
    sibling_color_id = new_id("ast")
    with session_factory() as db:
        db.add_all([
            ImageAsset(
                id=sibling_line_id,
                root_id=root_id,
                parent_asset_id=active_v1,
                design_id=None,
                design_version=1,
                capability="LINE_ART",
                instruction="abandoned alternative line branch",
                image=LINE_ART,
                media_type="image/png",
                created_by="usr_designer",
            ),
            ImageAsset(
                id=sibling_color_id,
                root_id=root_id,
                parent_asset_id=sibling_line_id,
                design_id=None,
                design_version=1,
                capability="COLORED_LINE_ART",
                instruction="abandoned alternative color branch",
                image=COLORED_LINE_ART,
                media_type="image/png",
                created_by="usr_designer",
            ),
        ])
        db.commit()

    beauty_calls_before_sibling = sum(
        call["stage"] == "beauty" for call in calls
    )
    sibling = client.post(f"/projects/{root_id}/render", json={
        "created_by": "usr_designer",
        "expected_asset_id": beauty_asset_id,
        "source_asset_id": sibling_color_id,
        "expected_design_version": 1,
    })
    assert sibling.status_code == 409, sibling.text
    assert sibling.json()["code"] == "beauty_source_branch_mismatch"
    assert sum(call["stage"] == "beauty" for call in calls) == (
        beauty_calls_before_sibling
    )

    rerendered = client.post(f"/projects/{root_id}/render", json={
        "created_by": "usr_designer",
        "expected_asset_id": beauty_asset_id,
        "source_asset_id": colored_asset["asset_id"],
        "expected_design_version": 1,
        "instruction": "Re-render from the confirmed colored control ancestor.",
        "variant": 1,
    })
    assert rerendered.status_code == 201, rerendered.text
    final_beauty_asset_id = rerendered.json()["asset_id"]
    assert sum(call["stage"] == "beauty" for call in calls) == (
        beauty_calls_before_sibling + 1
    )
    with session_factory() as db:
        final_beauty = db.get(ImageAsset, final_beauty_asset_id)
        final_run = db.get(ImageRun, rerendered.json()["image_run_id"])
        assert final_beauty.parent_asset_id == colored_asset["asset_id"]
        assert final_run.source_asset_id == colored_asset["asset_id"]

    _approve(client, final_beauty_asset_id)
    approved = client.get(f"/projects/{root_id}").json()
    assert approved["state"] == "factory_ready"
    pack = client.get(f"/projects/{root_id}/factory-pack")
    assert pack.status_code == 200, pack.text
    manifest = pack.json()
    assert manifest["asset_id"] == final_beauty_asset_id
    assert manifest["dimensions"]["has_estimates"] is True
    assert "not measurements" in manifest["dimensions"]["disclaimer"]
    assert manifest["authority"]["discussion_only"] == [
        "discussion-line-art.png"
    ]
    approved_reference = next(
        item for item in manifest["files"]
        if item["name"] == "approved-reference.png"
    )
    assert approved_reference["sha256"] == _sha256(BEAUTY_RENDER)


def test_confirmed_line_art_can_directly_control_spec_colored_beauty(
    workflow,
    monkeypatch,
):
    client, session_factory = workflow
    _install_plate_read(monkeypatch)
    calls = _install_image_agent(monkeypatch)

    plate = client.post("/specs/from-plate", json={
        "image_base64": base64.b64encode(DRAWING).decode(),
        "created_by": "usr_designer",
        "run_independent_audit": True,
    })
    assert plate.status_code == 200, plate.text
    created = client.post("/projects/from-image", json={
        "image_base64": base64.b64encode(DRAWING).decode(),
        "media_type": "image/png",
        "spec": plate.json()["spec"],
        "owner": "usr_designer",
        "title": "Direct confirmed-line-to-beauty",
    })
    assert created.status_code == 201, created.text
    project = created.json()
    root_id = project["root_id"]
    active_v1 = project["active_asset_id"]

    line = client.post(f"/projects/{root_id}/line-art", json={
        "created_by": "usr_designer",
        "expected_asset_id": active_v1,
        "expected_design_version": 1,
        "view": "three_quarter",
        "source_region_description": "the designer-selected face-up view",
        "source_region": {
            "x": 0.1,
            "y": 0.1,
            "width": 0.5,
            "height": 0.5,
        },
    })
    assert line.status_code == 202, line.text
    assert line.json()["source_selection"] == {
        "x": 0.1,
        "y": 0.1,
        "width": 0.5,
        "height": 0.5,
    }
    with Image.open(io.BytesIO(calls[0]["source_image"])) as selected:
        assert selected.size == (90, 110)
    candidate = line.json()["candidate"]
    confirmed = client.post(
        f"/image-runs/{candidate['run_id']}/candidates/"
        f"{candidate['candidate_id']}/accept",
        json={
            "expected_design_version": 1,
            "created_by": "usr_designer",
        },
    )
    assert confirmed.status_code == 201, confirmed.text
    line_asset = next(
        item for item in confirmed.json()["derived_assets"]
        if item["capability"] == "LINE_ART"
    )
    with session_factory() as db:
        confirmed_line_bytes = bytes(
            db.get(ImageAsset, line_asset["asset_id"]).image
        )

    rendered = client.post(f"/projects/{root_id}/render", json={
        "created_by": "usr_designer",
        "expected_asset_id": active_v1,
        "source_asset_id": line_asset["asset_id"],
        "expected_design_version": 1,
        "instruction": (
            "Turn the exact confirmed line geometry into a photorealistic "
            "beauty render using the validated material and stone facts."
        ),
    })
    assert rendered.status_code == 201, rendered.text
    body = rendered.json()
    beauty_call = next(call for call in calls if call["stage"] == "beauty")
    assert beauty_call["source_image"] == confirmed_line_bytes
    assert beauty_call["plan"].source_hash == _sha256(confirmed_line_bytes)

    with session_factory() as db:
        beauty = db.get(ImageAsset, body["asset_id"])
        run = db.get(ImageRun, body["image_run_id"])
        assert beauty.parent_asset_id == line_asset["asset_id"]
        assert run.source_asset_id == line_asset["asset_id"]
        assert run.accepted_asset_id == beauty.id


def test_beauty_warning_is_temporary_reviewable_and_stale_safe(
    workflow,
    monkeypatch,
):
    client, session_factory = workflow
    created = client.post("/projects/from-image", json={
        "image_base64": base64.b64encode(DRAWING).decode(),
        "media_type": "image/png",
        "spec": audited_import_spec(HALO_SPEC),
        "owner": "usr_designer",
        "title": "Beauty warning review",
    })
    assert created.status_code == 201, created.text
    project = created.json()
    root_id = project["root_id"]
    active_v1 = project["active_asset_id"]
    design_id = project["design_id"]

    line_id = new_id("ast")
    colored_id = new_id("ast")
    with session_factory() as db:
        db.add_all([
            ImageAsset(
                id=line_id,
                root_id=root_id,
                parent_asset_id=active_v1,
                design_id=None,
                design_version=1,
                capability="LINE_ART",
                instruction="designer-confirmed line art",
                image=LINE_ART,
                media_type="image/png",
                created_by="usr_designer",
            ),
            ImageAsset(
                id=colored_id,
                root_id=root_id,
                parent_asset_id=line_id,
                design_id=None,
                design_version=1,
                capability="COLORED_LINE_ART",
                instruction="spec-colored confirmed line art",
                image=COLORED_LINE_ART,
                media_type="image/png",
                created_by="usr_designer",
            ),
        ])
        db.commit()

    _install_image_agent(
        monkeypatch,
        beauty_verdict=QualityVerdict.WARN,
    )
    warned = client.post(f"/projects/{root_id}/render", json={
        "created_by": "usr_designer",
        "expected_asset_id": active_v1,
        "source_asset_id": colored_id,
        "expected_design_version": 1,
    })
    assert warned.status_code == 202, warned.text
    warned_body = warned.json()
    candidate = warned_body["warning_candidate"]
    assert candidate["candidate_id"].startswith("cand_")
    assert candidate["asset_capability"] == "SPEC_RENDER"
    assert candidate["operation"] == "SPEC_RENDER"
    assert "image_b64" not in warned.text
    preview = client.get(candidate["preview_url"])
    assert preview.status_code == 200
    assert preview.content == BEAUTY_RENDER
    held_project = client.get(f"/projects/{root_id}").json()
    assert held_project["active_asset_id"] == active_v1
    assert held_project["primary_revision_count"] == 1
    assert held_project["item_count"] == 3
    held_run = client.get(f"/image-runs/{candidate['run_id']}").json()
    assert held_run["status"] == "review_required"
    assert held_run["accepted_asset_id"] is None

    competing_id = new_id("ast")
    with session_factory() as db:
        db.add(ImageAsset(
            id=competing_id,
            root_id=root_id,
            parent_asset_id=colored_id,
            design_id=None,
            design_version=1,
            capability="SPEC_RENDER",
            instruction="a newer competing beauty revision",
            image=COMPETING_RENDER,
            media_type="image/png",
            created_by="usr_designer",
        ))
        db.commit()

    stale = client.post(
        f"/image-runs/{candidate['run_id']}/candidates/"
        f"{candidate['candidate_id']}/accept",
        json={
            "expected_design_version": 1,
            "created_by": "usr_designer",
        },
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["code"] == "stale_asset_revision"
    after_stale = client.get(f"/projects/{root_id}").json()
    assert after_stale["active_asset_id"] == competing_id
    assert after_stale["primary_revision_count"] == 2
    assert after_stale["item_count"] == 4

    fresh = client.post(f"/projects/{root_id}/render", json={
        "created_by": "usr_designer",
        "expected_asset_id": competing_id,
        "source_asset_id": colored_id,
        "expected_design_version": 1,
        "variant": 1,
    })
    assert fresh.status_code == 202, fresh.text
    fresh_candidate = fresh.json()["warning_candidate"]
    accepted = client.post(
        f"/image-runs/{fresh_candidate['run_id']}/candidates/"
        f"{fresh_candidate['candidate_id']}/accept",
        json={
            "expected_design_version": 1,
            "created_by": "usr_designer",
        },
    )
    assert accepted.status_code == 201, accepted.text
    accepted_project = accepted.json()
    accepted_id = accepted_project["active_asset_id"]
    assert accepted_project["active_revision"]["capability"] == "SPEC_RENDER"
    assert accepted_project["active_design_version"] == 1
    assert accepted_project["primary_revision_count"] == 3
    assert accepted_project["item_count"] == 5
    assert len(client.get(f"/designs/{design_id}").json()["versions"]) == 1

    with session_factory() as db:
        asset = db.get(ImageAsset, accepted_id)
        assert asset.parent_asset_id == colored_id
        assert bytes(asset.image) == BEAUTY_RENDER
    reviewed_run = client.get(
        f"/image-runs/{fresh_candidate['run_id']}"
    ).json()
    assert reviewed_run["stored_status"] == "review_required"
    assert reviewed_run["status"] == "accepted"
    assert reviewed_run["accepted_asset_id"] == accepted_id

"""Composed trusted-workflow acceptance from text brief to factory ZIP.

This deliberately crosses the public workflow boundaries instead of proving
the same rules in isolation.  The language and image providers are
deterministic seams; project/spec/asset/run/checklist persistence, optimistic
concurrency, structural scope guarding, QA evidence, approval invalidation,
and factory-pack assembly all run through their production paths.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import facetta.api.assets as assets_mod
import facetta.grokedit as grokedit
from conftest import HALO_SPEC
from facetta.agent import Annotation, resolve_target
from facetta.db import (
    ApprovalChecklist,
    Base,
    DesignVersion,
    ImageAsset,
    ImageAttempt,
    ImageRun,
    get_db,
)
from facetta.image_agent import (
    CheckSeverity,
    DesignerEditDomain,
    ImageOperation,
    ImageQualityReport,
    JewelryImageAgent,
    ProviderImage,
    QualityCheck,
    QualityVerdict,
)
from facetta.main import app
from facetta.project_backbone import (
    BriefProjectGeneration,
    get_brief_project_generator,
)
from facetta.spec import Spec


def _png(color: tuple[int, int, int]) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (200, 300), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _marked_center(source: bytes) -> bytes:
    image = Image.open(io.BytesIO(source)).convert("RGB")
    draw = ImageDraw.Draw(image)
    draw.ellipse((58, 35, 142, 119), outline=(255, 0, 0), width=5)
    draw.line((142, 77, 178, 52), fill=(255, 0, 0), width=5)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


CONCEPT = _png((218, 210, 198))
SPEC_RENDER_V1 = _png((180, 184, 191))
SPEC_RENDER_V2 = _png((198, 168, 52))
MARKED_CENTER = _marked_center(SPEC_RENDER_V1)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@pytest.fixture
def workflow():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(bind=engine, autoflush=False)
    Base.metadata.create_all(engine)
    brief_calls: list[tuple[str, int]] = []

    def override_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    def generate(brief: str, variant: int) -> BriefProjectGeneration:
        brief_calls.append((brief, variant))
        return BriefProjectGeneration(
            concept_image=CONCEPT,
            spec_render=SPEC_RENDER_V1,
            spec=Spec.model_validate(copy.deepcopy(HALO_SPEC)),
            quality_verdict="pass",
            quality_report={
                "verdict": "pass",
                "stage": "spec_render",
                "checks": ["brief translated to a validated halo-ring spec"],
            },
        )

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_brief_project_generator] = lambda: generate
    try:
        yield TestClient(app), session_factory, brief_calls
    finally:
        app.dependency_overrides.clear()


def _approve(client: TestClient, asset_id: str) -> dict:
    created = client.post(
        f"/assets/{asset_id}/checklist",
        json={"created_by": "usr_designer", "mode": "auto_pin"},
    )
    assert created.status_code == 201, created.text
    checklist = created.json()
    for item in checklist["items"]:
        response = client.post(
            f"/assets/{asset_id}/checklist/respond",
            json={
                "item_key": item["key"],
                "approved": True,
                "created_by": "usr_designer",
            },
        )
        assert response.status_code == 201, response.text
    state = client.get(f"/assets/{asset_id}/checklist")
    assert state.status_code == 200, state.text
    assert state.json()["status"]["all_approved"] is True
    assert state.json()["pin_state"]["pinned"] is True
    return checklist


def test_text_brief_scoped_color_refinement_reaches_exact_factory_pack(
    workflow,
    monkeypatch,
):
    client, session_factory, brief_calls = workflow

    created_response = client.post("/projects/from-brief", json={
        "brief": (
            "Create an oval diamond halo ring in polished 18k white gold, "
            "with eight round diamond halo stones and a plain two millimeter band."
        ),
        "owner": "usr_designer",
        "title": "Oval diamond halo",
        "collection": "Studio acceptance",
        "tags": ["halo", "client-review"],
        "variant": 4,
    })
    assert created_response.status_code == 201, created_response.text
    created = created_response.json()
    root_id = created["root_id"]
    design_id = created["design_id"]
    asset_v1 = created["active_asset_id"]

    assert brief_calls == [(
        "Create an oval diamond halo ring in polished 18k white gold, "
        "with eight round diamond halo stones and a plain two millimeter band.",
        4,
    )]
    assert created["state"] == "refining"
    assert created["active_revision"]["capability"] == "SPEC_RENDER"
    assert created["active_design_version"] == 1
    assert created["primary_revision_count"] == 1
    assert created["spec"]["stone"]["color"] == {
        "trade": "D",
        "gia": "colorless",
        "hue_code": None,
        "tone": None,
        "saturation": None,
    }

    first_checklist = _approve(client, asset_v1)
    approved_v1 = client.get(f"/projects/{root_id}").json()
    assert approved_v1["state"] == "factory_ready"
    assert approved_v1["approval"]["design_version"] == 1
    assert client.get(f"/projects/{root_id}/factory-pack").status_code == 200

    read_calls: list[tuple[bytes, bytes]] = []

    def read_markup(clean: bytes, marked: bytes) -> dict[str, object]:
        read_calls.append((clean, marked))
        return {
            "annotations": [{
                "region_description": "the oval center diamond only",
                "change_instruction": (
                    "Change only the center diamond from colorless to fancy "
                    "yellow; preserve its cut, dimensions, setting, halo, "
                    "metal, and band."
                ),
                "target_section": "stone",
                "target_ref": "A",
                "handwriting": "centre -> vivid yellow",
                "confidence": 0.98,
            }],
            "understood_as": (
                "Understood as: make only center stone A fancy yellow; "
                "nothing else changes."
            ),
            "needs_clarification": False,
            "clarification": "",
        }

    monkeypatch.setattr(assets_mod, "read_markup", read_markup)
    read_response = client.post(f"/assets/{asset_v1}/markup/read", json={
        "marked_image_base64": base64.b64encode(MARKED_CENTER).decode(),
        "created_by": "usr_designer",
    })
    assert read_response.status_code == 200, read_response.text
    reading = read_response.json()
    assert read_calls == [(SPEC_RENDER_V1, MARKED_CENTER)]
    assert reading["expected_design_version"] == 1
    assert reading["interpretation"] == {
        "target_region": "the oval center diamond only",
        "requested_change": (
            "Change only the center diamond from colorless to fancy yellow; "
            "preserve its cut, dimensions, setting, halo, metal, and band."
        ),
        "impact": "specification",
        "target_spec_reference": "A",
        "target_section": "stone",
        "target_index": None,
        "target_element_id": None,
        "target_component_id": None,
        "frozen_elements": [
            "all specification sections outside the named target",
            "all jewelry structure outside the marked region",
        ],
        "confidence": 0.98,
        "clarification_question": None,
        "understood_as": (
            "Understood as: make only center stone A fancy yellow; "
            "nothing else changes."
        ),
    }
    markup_asset_id = reading["markup_asset_id"]

    # Read is audit-only: the exact approved primary remains active and the
    # immutable spec version has not moved.
    after_read = client.get(f"/projects/{root_id}").json()
    assert after_read["active_asset_id"] == asset_v1
    assert after_read["active_design_version"] == 1
    assert after_read["state"] == "factory_ready"
    assert next(
        item for item in after_read["derived_assets"]
        if item["asset_id"] == markup_asset_id
    )["capability"] == "MARKUP_NOTES"

    planner_calls: list[tuple[str, str]] = []

    def fake_grok_json(system: str, user: str) -> dict[str, object]:
        planner_calls.append((system, user))
        proposed = copy.deepcopy(created["spec"])
        proposed["stone"]["color"]["trade"] = "Fancy Yellow"
        proposed["stone"]["color"]["gia"] = "fancy yellow"

        # A deliberately over-helpful language-model proposal.  The real
        # scope guard must report and discard every one of these changes.
        proposed["metal"]["color"] = "yellow"
        proposed["band"]["width_mm"] = 7.0
        proposed["side_stones"][0]["count"] = 10
        proposed["notes_to_factory"] = "Redesign the whole mounting."
        return {
            "spec": proposed,
            "changed_fields": ["the model claims it redesigned several fields"],
            "isolate_ref": "A",
            "message": "Center stone color changed.",
        }

    monkeypatch.setattr(grokedit, "_chat_json", fake_grok_json)

    image_calls: list[dict[str, object]] = []
    evaluation_calls: list[dict[str, object]] = []

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
            image_calls.append({
                "plan": plan,
                "route": route,
                "prompt": prompt,
                "source_image": source_image,
                "mask_bytes": mask_bytes,
            })
            return ProviderImage(
                image_bytes=SPEC_RENDER_V2,
                provider_request_id="req_center_fancy_yellow",
                usage={"images": 1},
                cost=0.04,
            )

    class Evaluator:
        def evaluate(
            self,
            plan,
            candidate,
            *,
            source_image,
            mask_bytes,
        ):
            evaluation_calls.append({
                "plan": plan,
                "candidate": candidate,
                "source_image": source_image,
                "mask_bytes": mask_bytes,
            })
            return ImageQualityReport(
                verdict=QualityVerdict.PASS,
                checks=(
                    QualityCheck(
                        code="requested_center_color_applied",
                        passed=True,
                        severity=CheckSeverity.HARD,
                        message="the center is visibly fancy yellow",
                    ),
                    QualityCheck(
                        code="protected_structure_consistent",
                        passed=True,
                        severity=CheckSeverity.HARD,
                        message="halo, setting, metal, and band did not drift",
                        evidence={"outside_mask_drift": 0.01},
                    ),
                ),
                score=99,
            )

    monkeypatch.setattr(
        assets_mod,
        "_trusted_image_agent",
        lambda: JewelryImageAgent(Provider(), Evaluator()),
    )
    monkeypatch.setattr(
        assets_mod,
        "check_design_consistency",
        lambda source, candidate: {
            "checked": True,
            "consistent": True,
            "differences": [],
            "severity": "none",
        },
    )

    confirmed_annotation = {
        "region_description": reading["interpretation"]["target_region"],
        "change_instruction": reading["interpretation"]["requested_change"],
        "target_section": reading["interpretation"]["target_section"],
        "target_ref": reading["interpretation"]["target_spec_reference"],
    }

    with session_factory() as db:
        before_stale = {
            "versions": db.scalar(select(func.count()).select_from(DesignVersion)),
            "assets": db.scalar(select(func.count()).select_from(ImageAsset)),
            "runs": db.scalar(select(func.count()).select_from(ImageRun)),
        }
    stale = client.post(f"/assets/{asset_v1}/markup/apply", json={
        "annotations": [confirmed_annotation],
        "markup_asset_id": markup_asset_id,
        "expected_design_version": 9,
        "created_by": "usr_designer",
    })
    assert stale.status_code == 409, stale.text
    assert stale.json()["code"] == "stale_design_version"
    assert planner_calls == []
    assert image_calls == []
    with session_factory() as db:
        assert {
            "versions": db.scalar(select(func.count()).select_from(DesignVersion)),
            "assets": db.scalar(select(func.count()).select_from(ImageAsset)),
            "runs": db.scalar(select(func.count()).select_from(ImageRun)),
        } == before_stale

    applied_response = client.post(f"/assets/{asset_v1}/markup/apply", json={
        "annotations": [confirmed_annotation],
        "markup_asset_id": markup_asset_id,
        "expected_design_version": 1,
        "created_by": "usr_designer",
    })
    assert applied_response.status_code == 201, applied_response.text
    applied = applied_response.json()
    asset_v2 = applied["final_asset_id"]
    run_id = applied["image_run_id"]

    assert len(planner_calls) == 1
    assert "Edit ONLY stone" in planner_calls[0][1]
    assert len(image_calls) == len(evaluation_calls) == 1
    plan = image_calls[0]["plan"]
    assert plan.operation is ImageOperation.LOCAL_EDIT
    assert plan.edit_domains == (DesignerEditDomain.CENTER_STONE_COLOR,)
    assert plan.source_spec_facts["stone"]["color"]["trade"] == "D"
    assert plan.spec_facts["stone"]["color"]["trade"] == "Fancy Yellow"
    assert image_calls[0]["source_image"] == SPEC_RENDER_V1
    assert image_calls[0]["mask_bytes"] is not None
    assert plan.source_hash == _sha256(SPEC_RENDER_V1)
    assert plan.mask_hash == _sha256(image_calls[0]["mask_bytes"])
    assert evaluation_calls[0]["candidate"] == SPEC_RENDER_V2

    assert applied["design_version"] == 2
    assert applied["spec_version"] == 2
    assert applied["revision"]["revision"] == 2
    assert applied["revision"]["asset"]["asset_id"] == asset_v2
    assert applied["revision"]["asset"]["design_version"] == 2
    assert applied["qa"]["verdict"] == "pass"
    assert applied["qa"]["score"] == 99
    assert applied["qa"]["failed_checks"] == []
    assert applied["routing"] == {
        "attempt_count": 1,
        "used_retry": False,
        "used_fallback": False,
        "cache_hit": False,
        "run_id": run_id,
    }
    assert applied["spec_change"] == [
        {
            "path": "stone.color.gia",
            "label": "center stone colour gia",
            "before": "colorless",
            "after": "fancy yellow",
            "kind": "changed",
        },
        {
            "path": "stone.color.trade",
            "label": "center stone colour trade colour",
            "before": "D",
            "after": "Fancy Yellow",
            "kind": "changed",
        },
    ]
    assert any("spec.metal.color" in item for item in applied["ignored_fields"])
    assert any("spec.band.width_mm" in item for item in applied["ignored_fields"])
    assert any("spec.side_stones[0].count" in item
               for item in applied["ignored_fields"])
    assert any("spec.notes_to_factory" in item
               for item in applied["ignored_fields"])

    v1 = client.get(f"/designs/{design_id}/versions/1").json()
    v2 = client.get(f"/designs/{design_id}/versions/2").json()
    assert v1["stone"]["color"]["trade"] == "D"
    assert v2["stone"]["color"]["trade"] == "Fancy Yellow"
    assert v2["stone"]["color"]["gia"] == "fancy yellow"
    assert v2["stone"]["cut"] == v1["stone"]["cut"]
    assert v2["stone"]["dimensions_mm"] == v1["stone"]["dimensions_mm"]
    assert v2["metal"] == v1["metal"]
    assert v2["band"] == v1["band"]
    assert v2["setting"] == v1["setting"]
    assert v2["side_stones"] == v1["side_stones"]
    assert v2["notes_to_factory"] == v1["notes_to_factory"]

    with session_factory() as db:
        persisted_asset = db.get(ImageAsset, asset_v2)
        persisted_run = db.get(ImageRun, run_id)
        attempts = list(db.scalars(select(ImageAttempt).where(
            ImageAttempt.run_id == run_id
        )))
        old_checklist = db.get(ApprovalChecklist, first_checklist["checklist_id"])
        assert persisted_asset is not None
        assert bytes(persisted_asset.image) == SPEC_RENDER_V2
        assert persisted_asset.parent_asset_id == asset_v1
        assert persisted_asset.design_version == 2
        assert persisted_run is not None
        assert persisted_run.project_root_id == root_id
        assert persisted_run.source_asset_id == asset_v1
        assert persisted_run.accepted_asset_id == asset_v2
        assert persisted_run.status == "accepted"
        assert len(attempts) == 1
        assert attempts[0].provider_request_id == "req_center_fancy_yellow"
        assert attempts[0].qa_verdict == "pass"
        assert old_checklist is not None
        assert old_checklist.asset_id == asset_v1

    # The historical v1 sign-off remains auditable, but cannot approve v2.
    # Factory handoff now resolves the active revision and refuses the old pin.
    awaiting_reapproval = client.get(f"/projects/{root_id}").json()
    assert awaiting_reapproval["active_asset_id"] == asset_v2
    assert awaiting_reapproval["active_design_version"] == 2
    assert awaiting_reapproval.get("approval") is None
    assert awaiting_reapproval["state"] == "refining"
    assert awaiting_reapproval["factory_ready"] is False
    blocked_pack = client.get(f"/projects/{root_id}/factory-pack")
    assert blocked_pack.status_code == 409, blocked_pack.text
    assert blocked_pack.json()["code"] == "approval_required"

    second_checklist = _approve(client, asset_v2)
    approved_v2 = client.get(f"/projects/{root_id}").json()
    assert approved_v2["state"] == "factory_ready"
    assert approved_v2["pinned_revision"]["asset_id"] == asset_v2
    assert approved_v2["approval"]["checklist_id"] == second_checklist["checklist_id"]
    assert approved_v2["approval"]["design_version"] == 2

    manifest_response = client.get(f"/projects/{root_id}/factory-pack")
    assert manifest_response.status_code == 200, manifest_response.text
    manifest = manifest_response.json()
    assert manifest["project_id"] == root_id
    assert manifest["design_id"] == design_id
    assert manifest["design_version"] == 2
    assert manifest["asset_id"] == asset_v2
    assert manifest["visual_revision"] == 2
    assert manifest["checklist"]["id"] == second_checklist["checklist_id"]
    assert manifest["checklist"]["status"]["all_approved"] is True
    assert manifest["qa_summary"]["status"] == "accepted"
    assert manifest["qa_summary"]["image_run_id"] == run_id
    assert manifest["qa_summary"]["operation"] == "LOCAL_EDIT"
    assert manifest["qa_summary"]["verdict"] == "pass"
    assert manifest["qa_summary"]["attempt_count"] == 1
    schedule_names = [
        item["name"] for item in manifest["files"]
        if item["name"].startswith("facetta-schedule-")
    ]
    assert schedule_names
    assert manifest["authority"]["factory_truth"] == [
        "validated-spec.json",
        *schedule_names,
    ]
    assert manifest["authority"]["dimensional_diagram_only"] == [
        "facetta-sheet.svg",
    ]
    assert manifest["authority"]["release_status"] == "factory_review_only"
    assert manifest["authority"]["exchange_reference_only"] == [
        "facetta-sheet.dxf",
    ]
    assert manifest["authority"]["visual_reference_only"] == [
        "approved-reference.png"
    ]
    assert next(
        item for item in manifest["files"]
        if item["name"] == "facetta-sheet.dxf"
    )["authoritative"] is False

    archive_response = client.get(f"/projects/{root_id}/factory-pack.zip")
    assert archive_response.status_code == 200, archive_response.text
    with zipfile.ZipFile(io.BytesIO(archive_response.content)) as archive:
        assert set(archive.namelist()) == {
            "validated-spec.json",
            "facetta-sheet.svg",
            "facetta-sheet.dxf",
            *schedule_names,
            "approved-reference.png",
            "approval-manifest.json",
        }
        packed_spec = json.loads(archive.read("validated-spec.json"))
        packed_manifest = json.loads(archive.read("approval-manifest.json"))
        assert packed_spec == v2
        assert archive.read("approved-reference.png") == SPEC_RENDER_V2
        assert packed_manifest == manifest
        for item in manifest["files"]:
            assert _sha256(archive.read(item["name"])) == item["sha256"]


def test_only_positive_shape_language_widens_center_edit_scope():
    """Current-shape context must not silently grant reshape authority."""
    spec = Spec.model_validate(copy.deepcopy(HALO_SPEC))
    prose_cases = (
        ("set the center color to yellow on the oval stone", ("stone", None)),
        ("change species to sapphire but keep oval cut", ("stone", None)),
        ("change the oval to marquise", ("stone_assembly", None)),
        ("make the center stone marquise", ("stone_assembly", None)),
    )
    for instruction, expected in prose_cases:
        assert resolve_target(
            spec,
            Annotation(ref="A", instruction=instruction),
        ) == expected

    # A typed UI/catalog control can remove prose ambiguity explicitly.
    assert resolve_target(
        spec,
        Annotation(
            section="center_shape",
            instruction="set the selected center outline",
        ),
    ) == ("stone_assembly", None)

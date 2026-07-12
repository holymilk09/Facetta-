"""Exact-revision approval, image-run evidence, and factory-pack handoff."""

import base64
import copy
import hashlib
import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from conftest import HALO_SPEC, NECKLACE_SPEC, audited_import_spec
from facetta.db import (
    ApprovalChecklist,
    Base,
    Design,
    DesignVersion,
    FeedbackEvent,
    ImageAsset,
    ImageAttempt,
    ImageRun,
    Project,
    get_db,
    new_id,
)
from facetta.main import app
from facetta.project_backbone import (
    PersistedProjectInput,
    persist_project_derived_asset,
    persist_project_v1,
)
from facetta.spec import Spec


def _png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (80, 80), (184, 174, 160)).save(out, format="PNG")
    return out.getvalue()


def _dimensioned_full_assembly() -> dict:
    return {
        "element_id": "assembly.full",
        "role": "full_assembly",
        "label": "Confirmed custom assembly",
        "confirmed_form_description": "Complete custom front profile.",
        "symmetry": "asymmetric",
        "instance_count": 1,
        "regions": [{
            "view": "front",
            "polygons": [{"points": [
                {"x": 0.1, "y": 0.1},
                {"x": 0.9, "y": 0.1},
                {"x": 0.9, "y": 0.9},
                {"x": 0.1, "y": 0.9},
            ]}],
        }],
        "definition": {
            "kind": "dimensioned_profile",
            "scope": "full_assembly",
            "view": "front",
            "coordinate_system": "x_right_y_up",
            "paths": [{
                "path_id": "assembly.outline",
                "purpose": "outline",
                "closed": True,
                "points": [
                    {"x_mm": -10.0, "y_mm": -20.0},
                    {"x_mm": 10.0, "y_mm": -20.0},
                    {"x_mm": 8.0, "y_mm": 20.0},
                    {"x_mm": -8.0, "y_mm": 20.0},
                ],
                "nominal_width_mm": None,
            }],
            "profile_thickness_mm": 1.5,
            "dimension_status": "designer_confirmed_estimate",
            "source_asset_id": "ast_confirmed_profile",
            "source_asset_sha256": "e" * 64,
            "confirmed_by": "usr_gia",
            "confirmed_at": "2026-07-12T10:30:00Z",
            "manufacturing_notes": "Prototype dimensions; verify at bench.",
        },
    }


@pytest.fixture
def trusted_client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)

    def override():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override
    yield TestClient(app), Session
    app.dependency_overrides.clear()


def _project(client: TestClient, spec: dict | None = None) -> tuple[dict, bytes]:
    image = _png()
    response = client.post("/projects/from-image", json={
        "image_base64": base64.b64encode(image).decode(),
        "media_type": "image/png",
        "spec": audited_import_spec(spec or HALO_SPEC),
        "owner": "usr_gia",
        "title": "Approved halo",
    })
    assert response.status_code == 201, response.text
    return response.json(), image


def _persist_necklace_project(Session, spec: dict) -> tuple[dict, bytes]:
    """Seed domain-valid necklace state while the public create slice is ring-only."""
    image = _png()
    with Session() as db:
        result = persist_project_v1(
            db,
            PersistedProjectInput(
                spec=Spec.model_validate(spec),
                primary_image=image,
                primary_capability="IMPORTED_REFERENCE",
                primary_instruction="designer-confirmed necklace reference",
                primary_media_type="image/png",
            ),
            owner="usr_gia",
            title="Approved necklace",
        )
    return {
        "root_id": result.root_id,
        "active_asset_id": result.root_id,
    }, image


def _approve(client: TestClient, asset_id: str) -> dict:
    created = client.post(f"/assets/{asset_id}/checklist", json={
        "created_by": "usr_gia", "mode": "auto_pin"})
    assert created.status_code == 201, created.text
    body = created.json()
    for item in body["items"]:
        response = client.post(f"/assets/{asset_id}/checklist/respond", json={
            "item_key": item["key"],
            "approved": True,
            "created_by": "usr_gia",
        })
        assert response.status_code == 201, response.text
    return body


def test_factory_pack_requires_and_exports_exact_approval(trusted_client):
    client, _ = trusted_client
    project, source = _project(client)
    project_id = project["root_id"]
    asset_id = project["active_revision"]["asset_id"]

    blocked = client.get(f"/projects/{project_id}/factory-pack")
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "approval_required"

    checklist = _approve(client, asset_id)
    manifest_response = client.get(f"/projects/{project_id}/factory-pack")
    assert manifest_response.status_code == 200, manifest_response.text
    manifest = manifest_response.json()
    assert manifest["asset_id"] == asset_id
    assert manifest["design_version"] == 1
    assert manifest["checklist"]["id"] == checklist["checklist_id"]
    factory_truth = manifest["authority"]["factory_truth"]
    assert factory_truth[:1] == ["validated-spec.json"]
    schedule_names = [
        item["name"] for item in manifest["files"]
        if item["name"].startswith("facetta-schedule-")
    ]
    assert schedule_names
    assert factory_truth[1:] == schedule_names
    assert manifest["authority"]["authoritative_fact_records"] == factory_truth
    assert manifest["authority"]["dimensional_diagram_only"] == [
        "facetta-sheet.svg"]
    assert manifest["authority"]["production_authority"] == []
    assert manifest["authority"]["release_status"] == "factory_review_only"
    assert manifest["authority"]["exchange_reference_only"] == [
        "facetta-sheet.dxf"]
    assert "drawing-exchange reference only" in manifest["authority"]["note"]
    assert "not a production drawing" in manifest["authority"]["note"]
    svg = next(
        file for file in manifest["files"]
        if file["name"] == "facetta-sheet.svg")
    assert svg["authoritative"] is False
    dxf = next(
        file for file in manifest["files"]
        if file["name"] == "facetta-sheet.dxf")
    assert dxf["authoritative"] is False
    reference = next(
        file for file in manifest["files"]
        if file["name"].startswith("approved-reference."))
    assert reference["authoritative"] is False
    assert reference["sha256"] == hashlib.sha256(source).hexdigest()

    archive_response = client.get(f"/projects/{project_id}/factory-pack.zip")
    assert archive_response.status_code == 200, archive_response.text
    repeated = client.get(f"/projects/{project_id}/factory-pack.zip")
    assert repeated.content == archive_response.content
    with zipfile.ZipFile(io.BytesIO(archive_response.content)) as archive:
        expected_names = {
            "validated-spec.json", "facetta-sheet.svg", "facetta-sheet.dxf",
            "approved-reference.png", "approval-manifest.json",
            *schedule_names,
        }
        assert set(archive.namelist()) == expected_names
        stored = json.loads(archive.read("approval-manifest.json"))
        assert stored == manifest
        assert archive.read("approved-reference.png") == source
        assert "RING" in archive.read("facetta-sheet.svg").decode()
        schedule = archive.read("facetta-schedule-1.svg").decode()
        assert "FACTORY FACT SCHEDULE" in schedule
        assert f"PAGE 1 / {len(schedule_names)}" in schedule


def test_exact_checklist_rejects_a_different_valid_spec_atomically(
    trusted_client,
):
    client, Session = trusted_client
    project, _source = _project(client)
    asset_id = project["active_revision"]["asset_id"]
    mismatched = copy.deepcopy(audited_import_spec(HALO_SPEC))
    mismatched["band"]["width_mm"] += 0.1

    rejected = client.post(f"/assets/{asset_id}/checklist", json={
        "created_by": "usr_gia",
        "mode": "auto_pin",
        "spec": mismatched,
    })
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["code"] == "checklist_spec_mismatch"
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(ApprovalChecklist)) == 0
    blocked = client.get(f"/projects/{project['root_id']}/factory-pack")
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "approval_required"

    omitted = client.post(f"/assets/{asset_id}/checklist", json={
        "created_by": "usr_gia", "mode": "explicit_pin",
    })
    assert omitted.status_code == 201, omitted.text

    other, _ = _project(client)
    other_asset = other["active_revision"]["asset_id"]
    matching = client.post(f"/assets/{other_asset}/checklist", json={
        "created_by": "usr_gia",
        "mode": "explicit_pin",
        "spec": audited_import_spec(HALO_SPEC),
    })
    assert matching.status_code == 201, matching.text


def test_factory_pack_uses_confirmed_custom_profile_not_hidden_template(
    trusted_client,
):
    client, _ = trusted_client
    spec = json.loads(json.dumps(HALO_SPEC))
    spec["design_form"] = {"elements": [_dimensioned_full_assembly()]}
    project, _ = _project(client, spec)
    _approve(client, project["active_asset_id"])

    archive_response = client.get(
        f"/projects/{project['root_id']}/factory-pack.zip"
    )

    assert archive_response.status_code == 200, archive_response.text
    with zipfile.ZipFile(io.BytesIO(archive_response.content)) as archive:
        sheet = archive.read("facetta-sheet.svg").decode()
        dxf = archive.read("facetta-sheet.dxf").decode()
        manifest = json.loads(archive.read("approval-manifest.json"))
    assert 'data-facetta-form-authority="dimensioned_profile"' in sheet
    assert 'data-profile-path="assembly.outline"' in sheet
    assert "DESIGNER-CONFIRMED ESTIMATES" in sheet
    assert "POLYLINE" in dxf
    assert "CIRCLE" not in dxf
    assert manifest["dimensions"]["has_estimates"] is True
    assert any(
        item["field_path"].endswith("profile_thickness_mm")
        for item in manifest["dimensions"]["estimated_fields"]
    )


def test_factory_pack_discloses_reference_estimates_in_manifest_and_sheet(
    trusted_client,
):
    client, _ = trusted_client
    spec = json.loads(json.dumps(HALO_SPEC))
    spec["dimension_provenance"] = {
        "band.width_mm": {
            "status": "estimated_from_reference",
            "method": "reference_vision",
            "source": "imported jewelry reference",
            "confidence": 0.42,
            "note": "Verify against a known scale.",
        },
        "stone.dimensions_mm.length": {
            "status": "designer_confirmed",
            "method": "designer_input",
            "source": "designer annotation",
            "confidence": 1.0,
        },
    }
    project, _ = _project(client, spec)
    asset_id = project["active_revision"]["asset_id"]
    _approve(client, asset_id)

    response = client.get(f"/projects/{project['root_id']}/factory-pack")
    assert response.status_code == 200, response.text
    manifest = response.json()
    assert manifest["dimensions"]["has_estimates"] is True
    assert manifest["dimensions"]["estimated_fields"] == [{
        "field_path": "band.width_mm",
        "value": 2.0,
        "unit": "mm",
        "status": "estimated_from_reference",
        "method": "reference_vision",
        "source": "imported jewelry reference",
        "confidence": 0.42,
        "note": "Verify against a known scale.",
    }]
    assert "not measurements" in manifest["dimensions"]["disclaimer"]
    assert "ESTIMATED" in manifest["authority"]["note"]
    fact_plan = manifest["factory_sheet_fact_plan"]
    assert fact_plan["schema_version"] == "facetta.factory-sheet-plan.v1"
    assert fact_plan["pending_confirmation_count"] == 0
    assert fact_plan["estimated_fact_count"] == 1
    assert next(
        item for item in fact_plan["dimensions"]
        if item["field_path"] == "band.width_mm"
    )["status"] == "estimated_from_reference"
    assert [(row["ref"], row["count"]) for row in fact_plan["stones"]] == [
        ("A", 1), ("B", 8)]

    archive_response = client.get(
        f"/projects/{project['root_id']}/factory-pack.zip")
    with zipfile.ZipFile(io.BytesIO(archive_response.content)) as archive:
        sheet = archive.read("facetta-sheet.svg").decode()
        stored = json.loads(archive.read("validated-spec.json"))
    assert "ESTIMATED DIMENSIONS" in sheet
    assert stored["dimension_provenance"]["band.width_mm"]["status"] == (
        "estimated_from_reference")


def test_legacy_necklace_stays_readable_but_chain_blocks_factory_release(
    trusted_client,
):
    client, Session = trusted_client
    project, _ = _persist_necklace_project(Session, NECKLACE_SPEC)
    _approve(client, project["active_asset_id"])

    detail = client.get(f"/projects/{project['root_id']}").json()
    assert detail["state"] == "approved"
    assert detail["factory_ready"] is False
    chain_blockers = [
        blocker for blocker in detail["factory_blockers"]
        if blocker["subject_kind"] == "chain"
    ]
    assert {blocker["code"] for blocker in chain_blockers} == {
        "chain_geometry_missing",
        "chain_production_reference_missing",
        "chain_pendant_connection_missing",
    }

    pack = client.get(f"/projects/{project['root_id']}/factory-pack")
    assert pack.status_code == 409, pack.text
    assert pack.json()["code"] == "chain_manufacturing_incomplete"


def test_dimensioned_referenced_chain_is_exact_factory_truth(trusted_client):
    client, Session = trusted_client
    spec = json.loads(json.dumps(NECKLACE_SPEC))
    spec["chain"].update({
        "pendant_connection": "slides_through_bail",
        "geometry": {
            "construction": "open_link",
            "chain_width_mm": 2.0,
            "profile_thickness_mm": 0.6,
            "end_ring_outer_diameter_mm": 1.8,
            "link_thickness_mm": 0.35,
            "links_soldered": True,
            "links": [{
                "role": "standard",
                "length_mm": 3.8,
                "inside_length_mm": 3.1,
                "inside_width_mm": 1.3,
            }],
        },
        "production": {
            "mode": "stock",
            "reference_kind": "supplier_sku",
            "reference": "RG-CABLE-2MM-18Y",
        },
    })
    spec["dimension_provenance"] = {
        "chain.geometry.chain_width_mm": {
            "status": "estimated_from_reference",
            "method": "reference_vision",
            "source": "designer necklace image",
            "confidence": 0.55,
        },
    }
    project, _ = _persist_necklace_project(Session, spec)
    _approve(client, project["active_asset_id"])

    detail = client.get(f"/projects/{project['root_id']}").json()
    assert detail["state"] == "factory_ready"
    assert detail["factory_blockers"] == []
    pack = client.get(f"/projects/{project['root_id']}/factory-pack")
    assert pack.status_code == 200, pack.text
    manifest = pack.json()
    assert manifest["dimensions"]["estimated_fields"][0]["field_path"] == (
        "chain.geometry.chain_width_mm")

    archive = client.get(
        f"/projects/{project['root_id']}/factory-pack.zip")
    with zipfile.ZipFile(io.BytesIO(archive.content)) as bundle:
        sheet = bundle.read("facetta-sheet.svg").decode()
        dxf = bundle.read("facetta-sheet.dxf").decode()
        stored = json.loads(bundle.read("validated-spec.json"))
    assert "RG-CABLE-2MM-18Y" in sheet
    assert "end-ring OD 1.8 mm" in dxf
    assert stored["chain"]["production"]["reference"] == "RG-CABLE-2MM-18Y"


def test_import_blocks_unresolved_or_unaudited_source_components_atomically(
    trusted_client,
):
    client, Session = trusted_client
    spec = json.loads(json.dumps(HALO_SPEC))
    spec["source_component_coverage"] = {
        "source_kind": "designer_plate",
        "components": [
            {
                "component_id": "stone.center",
                "source_view": "plate_composite",
                "source_description": "Oval center stone.",
                "source_confidence": 0.92,
                "canonical_spec_paths": ["stone"],
            },
            {
                "component_id": "stone.assembly_hint.shoulder",
                "source_view": "plate_composite",
                "source_description": "Diamond leaf shoulder groups.",
                "source_confidence": 0.81,
                "unresolved_reason": (
                    "The plate reader omitted the visible shoulder stones."
                ),
            },
        ],
    }
    image = _png()
    blocked = client.post("/projects/from-image", json={
        "image_base64": base64.b64encode(image).decode(),
        "media_type": "image/png",
        "spec": audited_import_spec(spec),
        "owner": "usr_gia",
        "title": "Blocked incomplete import",
    })
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["code"] == "source_component_coverage_incomplete"
    codes = {
        blocker["code"] for blocker in blocked.json()["factory_blockers"]
    }
    assert "source_component_unresolved" in codes
    assert "source_component_not_independently_audited" in codes
    shoulder = next(
        blocker for blocker in blocked.json()["factory_blockers"]
        if blocker["component_id"] == "stone.assembly_hint.shoulder"
        and blocker["code"] == "source_component_unresolved"
    )
    assert shoulder["component_id"] == "stone.assembly_hint.shoulder"
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(Design)) == 0
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 0
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 0
        assert db.scalar(select(func.count()).select_from(Project)) == 0


def test_passing_source_component_audit_preserves_factory_handoff(
    trusted_client,
):
    client, _ = trusted_client
    spec = json.loads(json.dumps(HALO_SPEC))
    spec["source_component_coverage"] = {
        "source_kind": "designer_plate",
        "components": [{
            "component_id": "stone.center",
            "source_view": "plate_composite",
            "source_description": "Oval center stone.",
            "source_confidence": 0.92,
            "canonical_spec_paths": ["stone"],
            "independent_audit": {
                "kind": "independent_component_audit",
                "verdict": "pass",
                "auditor": "skeptical-vision-audit.v1",
                "source_view": "plate_composite",
                "observed_description": (
                    "The source center stone and mapped spec agree."
                ),
                "evidence_sha256": "a" * 64,
            },
        }],
    }
    project, _ = _project(client, spec)
    _approve(client, project["active_asset_id"])

    detail = client.get(f"/projects/{project['root_id']}").json()
    assert detail["state"] == "factory_ready"
    assert detail["factory_blockers"] == []
    pack = client.get(f"/projects/{project['root_id']}/factory-pack")
    assert pack.status_code == 200, pack.text


def test_import_blocks_audited_mapping_to_removed_spec_path_atomically(
    trusted_client,
):
    client, Session = trusted_client
    spec = json.loads(json.dumps(HALO_SPEC))
    assert len(spec["side_stones"]) == 1
    spec["source_component_coverage"] = {
        "source_kind": "imported_reference",
        "components": [{
            "component_id": "stone.group.002",
            "source_view": "three_quarter",
            "source_description": (
                "Second shoulder stone group from the prior specification."
            ),
            "source_confidence": 0.9,
            "canonical_spec_paths": ["side_stones[1]"],
            "independent_audit": {
                "kind": "independent_component_audit",
                "verdict": "pass",
                "auditor": "skeptical-source-component-audit.v2",
                "source_view": "three_quarter",
                "observed_description": (
                    "The former source group matched before it was removed."
                ),
                "evidence_sha256": "b" * 64,
            },
        }],
    }
    image = _png()
    blocked = client.post("/projects/from-image", json={
        "image_base64": base64.b64encode(image).decode(),
        "media_type": "image/png",
        "spec": audited_import_spec(spec),
        "owner": "usr_gia",
        "title": "Blocked stale source path",
    })
    assert blocked.status_code == 409, blocked.text
    blockers = blocked.json()["factory_blockers"]
    assert blockers[0]["code"] == "source_component_path_missing"
    assert "side_stones[1]" in blockers[0]["message"]
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(Design)) == 0
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 0
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 0
        assert db.scalar(select(func.count()).select_from(Project)) == 0


def test_factory_pack_labels_confirmed_line_art_as_discussion_only(
    trusted_client,
):
    client, Session = trusted_client
    project, _ = _project(client)
    asset_id = project["active_asset_id"]
    drawing = _png()
    with Session() as db:
        persisted = persist_project_derived_asset(
            db,
            root_id=project["root_id"],
            parent_asset_id=asset_id,
            image=drawing,
            capability="LINE_ART",
            instruction="designer-confirmed geometry discussion drawing",
            design_version=1,
            created_by="usr_gia",
        )
        assert persisted.asset_id
    _approve(client, asset_id)

    manifest = client.get(
        f"/projects/{project['root_id']}/factory-pack").json()
    assert manifest["authority"]["discussion_only"] == [
        "discussion-line-art.png"]
    discussion = next(
        item for item in manifest["files"]
        if item["name"] == "discussion-line-art.png")
    assert discussion["authoritative"] is False

    archive_response = client.get(
        f"/projects/{project['root_id']}/factory-pack.zip")
    with zipfile.ZipFile(io.BytesIO(archive_response.content)) as archive:
        assert archive.read("discussion-line-art.png") == drawing


def test_checklist_no_routes_exact_revision_through_canonical_markup(
        trusted_client):
    client, _ = trusted_client
    project, _ = _project(client)
    asset_id = project["active_revision"]["asset_id"]
    created = client.post(f"/assets/{asset_id}/checklist", json={
        "created_by": "usr_gia", "mode": "auto_pin"})
    assert created.status_code == 201, created.text

    response = client.post(f"/assets/{asset_id}/checklist/respond", json={
        "item_key": "band",
        "approved": False,
        "note": "widen the band to 2.2 mm",
        "created_by": "usr_gia",
    })

    assert response.status_code == 201, response.text
    change = response.json()["change_request"]
    apply = change["markup_apply"]
    assert change["design_id"] == project["design_id"]
    assert change["design_version"] == 1
    assert apply["endpoint"] == f"/assets/{asset_id}/markup/apply"
    assert apply["body"]["expected_design_version"] == 1
    assert len(apply["body"]["annotations"]) == 1
    assert apply["body"]["annotations"][0]["target_section"] == "band"
    serialized = json.dumps(change)
    assert "/localized-edit" not in serialized
    assert "/designs/" not in serialized


def test_image_run_endpoint_returns_append_only_attempt_evidence(trusted_client):
    client, Session = trusted_client
    run_id = new_id("run")
    with Session() as db:
        db.add(ImageRun(
            id=run_id,
            operation="SPEC_RENDER",
            normalized_intent={"expected_output": "ring render"},
            prompt_version="spec-render.v1",
            input_hash="1" * 64,
            mask_hash="2" * 64,
            variant=0,
            status="pass",
            created_by="usr_gia",
        ))
        db.add(ImageAttempt(
            id=new_id("iat"), run_id=run_id, attempt_number=1,
            provider="grok", model="infrastructure-model",
            cached=False, qa_verdict="pass",
            qa_checks=[{"code": "jewelry_type", "passed": True}],
            prompt_hash="3" * 64,
            cache_key="4" * 64,
            usage={"images": 1},
        ))
        db.commit()

    response = client.get(f"/image-runs/{run_id}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["operation"] == "SPEC_RENDER"
    assert body["input_hash"] == "1" * 64
    assert body["mask_hash"] == "2" * 64
    assert body["attempts"][0]["qa_verdict"] == "pass"
    assert body["attempts"][0]["qa_checks"][0]["passed"] is True
    assert body["attempts"][0]["prompt_hash"] == "3" * 64
    assert body["attempts"][0]["cache_key"] == "4" * 64

    feedback = client.post(f"/image-runs/{run_id}/feedback", json={
        "action": "regenerated",
        "note": "Designer requested a cleaner setting",
        "created_by": "usr_gia",
    })
    assert feedback.status_code == 201, feedback.text
    with Session() as db:
        event = db.get(FeedbackEvent, feedback.json()["feedback_id"])
        assert event.image_run_id == run_id
        assert event.subject_kind == "image_run"
        assert event.action == "regenerated"

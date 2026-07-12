"""Acceptance journey for Studio work before any specification exists."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from conftest import EXAMPLE_SPEC

from facetta.api.studio import get_studio_visual_preview_generator
from facetta.creative_workflow import get_creative_prompt_generator
from facetta.db import (
    ApprovalChecklist,
    Base,
    Design,
    DesignVersion,
    ImageAsset,
    Project,
    ProjectRevisionRecord,
    get_db,
)
from facetta.image_agent import (
    ImageOperation,
    ImageQualityReport,
    JewelryImageAgent,
    ProviderImage,
    QualityVerdict,
    build_image_plan,
)
from facetta.main import app
from facetta.studio_visual_candidates import (
    clear_studio_visual_candidates_for_tests,
)


def _png(color: tuple[int, int, int]) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (56, 56), color).save(output, format="PNG")
    return output.getvalue()


def _accepted_result(plan, image: bytes, *, source: bytes | None = None):
    class Provider:
        def execute(self, *_args, **_kwargs):
            return ProviderImage(image_bytes=image)

    class Evaluator:
        def evaluate(self, *_args, **_kwargs):
            return ImageQualityReport(
                verdict=QualityVerdict.PASS,
                checks=(),
                score=97,
            )

    return JewelryImageAgent(Provider(), Evaluator()).run(
        plan,
        source_image=source,
    )


def _stored_image(Session, asset_id: str) -> bytes:
    with Session() as db:
        asset = db.get(ImageAsset, asset_id)
        assert asset is not None
        return bytes(asset.image)


@pytest.fixture
def prespec_journey_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)

    def override_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    clear_studio_visual_candidates_for_tests()
    app.dependency_overrides[get_db] = override_db
    try:
        yield TestClient(app), Session
    finally:
        app.dependency_overrides.clear()
        clear_studio_visual_candidates_for_tests()


def test_complete_prespec_studio_journey_preserves_every_direction(
    prespec_journey_client,
):
    client, Session = prespec_journey_client
    prompt_outputs: dict[int, bytes] = {}
    preview_sources: list[bytes] = []
    refined_bytes = _png((194, 143, 112))

    def generate_prompt(prompt: str, variant: int):
        assert "botanical signet" in prompt
        image = _png((70 + variant, 105 + variant, 135 + variant))
        prompt_outputs[variant] = image
        plan = build_image_plan(
            ImageOperation.CREATIVE_GENERATE,
            prompt,
            variant=variant,
        )
        return _accepted_result(plan, image)

    def generate_preview(source, instruction, scope, mask, variant):
        assert instruction == "Give the metal a warmer rose-gold appearance"
        assert scope == "appearance"
        assert mask is None
        assert variant == 4
        preview_sources.append(source)
        plan = build_image_plan(
            ImageOperation.REFERENCE_RENDER,
            instruction,
            source_image=source,
            variant=variant,
        )
        return _accepted_result(plan, refined_bytes, source=source)

    app.dependency_overrides[get_creative_prompt_generator] = (
        lambda: generate_prompt
    )
    app.dependency_overrides[get_studio_visual_preview_generator] = (
        lambda: generate_preview
    )

    created_response = client.post("/projects/from-prompt", json={
        "prompt": "A sculptural botanical signet ring with a quiet leaf rhythm",
        "variation_count": 3,
        "starting_variant": 11,
        "owner": "usr_journey",
        "title": "Botanical signet directions",
        "collection": "Studio acceptance",
    })
    assert created_response.status_code == 201, created_response.text
    created = created_response.json()
    root_id = created["root_id"]
    assert len(created["revisions"]) == 3
    assert set(prompt_outputs) == {11, 12, 13}
    assert created["factory_ready"] is False
    assert "design_id" not in created
    assert "spec" not in created

    # Choose the middle displayed direction, proving downstream work does not
    # silently snap to the last generated sibling.
    selected_id = created["revisions"][1]["asset_id"]
    last_id = created["revisions"][-1]["asset_id"]
    assert selected_id != last_id
    selected_image = _stored_image(Session, selected_id)
    last_image = _stored_image(Session, last_id)
    assert selected_image != last_image
    selected_response = client.post(
        f"/projects/{root_id}/creative-candidates/{selected_id}/select",
        json={"created_by": "usr_journey"},
    )
    assert selected_response.status_code == 200, selected_response.text
    selected = selected_response.json()
    assert selected["selected_candidate_asset_id"] == selected_id
    assert selected["active_asset_id"] == selected_id

    preview_response = client.post(
        f"/studio/projects/{root_id}/visual-previews",
        json={
            "created_by": "usr_journey",
            "expected_active_asset_id": selected_id,
            "instruction": "Give the metal a warmer rose-gold appearance",
            "scope": "appearance",
            "variant": 4,
        },
    )
    assert preview_response.status_code == 201, preview_response.text
    preview = preview_response.json()
    assert preview["source_asset_id"] == selected_id
    assert preview_sources == [selected_image]

    applied_response = client.post(
        f"/studio/image-runs/{preview['image_run_id']}/visual-candidates/"
        f"{preview['candidate']['candidate_id']}/accept",
        json={
            "created_by": "usr_journey",
            "expected_active_asset_id": selected_id,
        },
    )
    assert applied_response.status_code == 201, applied_response.text
    applied = applied_response.json()
    applied_id = applied["new_asset_id"]
    assert applied["design_version"] is None
    assert applied["project"]["active_asset_id"] == applied_id
    assert _stored_image(Session, applied_id) == refined_bytes

    reopened_response = client.get(f"/studio/projects/{root_id}/history")
    assert reopened_response.status_code == 200, reopened_response.text
    reopened = reopened_response.json()
    assert reopened["active_asset_id"] == applied_id
    assert len(reopened["revisions"]) == 4
    assert {item["asset_id"] for item in reopened["revisions"]} >= {
        selected_id,
        last_id,
        applied_id,
    }
    applied_history = next(
        item for item in reopened["revisions"]
        if item["asset_id"] == applied_id
    )
    assert applied_history["parent_asset_id"] == selected_id
    assert applied_history["design_version"] is None
    assert applied_history["action"] == "edit"
    assert applied_history["interpretation"]["factory_authority"] is False

    branch_response = client.post(
        f"/studio/projects/{root_id}/variations",
        json={
            "created_by": "usr_journey",
            "expected_active_asset_id": applied_id,
            "expected_design_version": None,
            "label": "Warm metal direction",
        },
    )
    assert branch_response.status_code == 201, branch_response.text
    branch = branch_response.json()
    branch_project = branch["project"]
    branch_root_id = branch_project["root_id"]
    branch_asset_id = branch_project["active_asset_id"]
    assert branch["source_project_id"] == root_id
    assert branch["source_asset_id"] == applied_id
    assert branch_project["factory_ready"] is False
    assert branch_project.get("design_id") is None
    assert branch_project.get("spec") is None
    assert _stored_image(Session, branch_asset_id) == refined_bytes

    restore_response = client.post(
        f"/studio/projects/{root_id}/revisions/{selected_id}/restore",
        json={
            "created_by": "usr_journey",
            "expected_active_asset_id": applied_id,
            "expected_design_version": None,
        },
    )
    assert restore_response.status_code == 201, restore_response.text
    restored = restore_response.json()
    restored_id = restored["new_asset_id"]
    assert restored_id not in {selected_id, applied_id}
    assert restored["restored_from_asset_id"] == selected_id
    assert restored["new_design_version"] is None
    assert restored["project"]["active_asset_id"] == restored_id
    assert _stored_image(Session, restored_id) == selected_image

    final_history = client.get(f"/studio/projects/{root_id}/history").json()
    assert final_history["active_asset_id"] == restored_id
    assert len(final_history["revisions"]) == 5
    restored_history = next(
        item for item in final_history["revisions"]
        if item["asset_id"] == restored_id
    )
    assert restored_history["parent_asset_id"] == applied_id
    assert restored_history["restored_from_asset_id"] == selected_id
    assert restored_history["action"] == "restore"
    # Restore appends; the selected and refined revisions remain immutable.
    assert _stored_image(Session, selected_id) == selected_image
    assert _stored_image(Session, applied_id) == refined_bytes

    for project_id in (root_id, branch_root_id):
        factory = client.get(f"/projects/{project_id}/factory-pack")
        assert factory.status_code == 409
        assert factory.json()["code"] == "creative_candidate_requires_spec_promotion"

    # Neither branching nor restoration may create a side door into the
    # approval/factory control plane, even when a caller supplies a valid spec.
    for asset_id in (branch_asset_id, restored_id):
        pinned = client.post(f"/assets/{asset_id}/pin")
        assert pinned.status_code == 409
        assert pinned.json()["code"] == "creative_candidate_requires_spec_promotion"
        checklist = client.post(f"/assets/{asset_id}/checklist", json={
            "created_by": "usr_journey",
            "mode": "explicit_pin",
            "spec": EXAMPLE_SPEC,
        })
        assert checklist.status_code == 409
        assert checklist.json()["code"] == "creative_candidate_requires_spec_promotion"

    with Session() as db:
        assert db.scalar(select(func.count()).select_from(Design)) == 0
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 0
        assert db.scalar(select(func.count()).select_from(ApprovalChecklist)) == 0
        projects = list(db.scalars(select(Project)))
        assert len(projects) == 2
        assets = list(db.scalars(select(ImageAsset)))
        assert all(asset.design_id is None for asset in assets)
        assert all(asset.design_version is None for asset in assets)
        assert all(asset.pinned_at is None for asset in assets)
        records = list(db.scalars(select(ProjectRevisionRecord)))
        assert {record.action for record in records} == {
            "created", "edit", "restore",
        }

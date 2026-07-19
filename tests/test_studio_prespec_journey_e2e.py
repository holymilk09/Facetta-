"""Acceptance journey for Studio work before any specification exists."""

from __future__ import annotations

import base64
import hashlib
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from conftest import EXAMPLE_SPEC

from facetta.api.studio import get_studio_visual_preview_generator
from facetta.creative_workflow import (
    get_creative_prompt_generator,
    get_creative_render_generator,
)
from facetta.creative_comparability import (
    MainViewComparabilityAudit,
    get_main_view_comparability_inspector,
)
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
    CheckSeverity,
    ImageOperation,
    ImageQualityReport,
    JewelryImageAgent,
    ProviderImage,
    QualityCheck,
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


def _accepted_result(
    plan,
    image: bytes,
    *,
    source: bytes | None = None,
    quality_source: bytes | None = None,
):
    class Provider:
        def execute(self, *_args, **_kwargs):
            return ProviderImage(image_bytes=image)

    class Evaluator:
        def evaluate(self, *_args, **_kwargs):
            return ImageQualityReport(
                verdict=QualityVerdict.PASS,
                checks=(QualityCheck(
                    code="fixture_quality",
                    passed=True,
                    severity=CheckSeverity.HARD,
                    message="fixture candidate passed",
                ),),
                score=97,
            )

    return JewelryImageAgent(Provider(), Evaluator()).run(
        plan,
        source_image=source,
        quality_source_image=quality_source,
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
    app.dependency_overrides[get_main_view_comparability_inspector] = (
        lambda: lambda _first, _second: MainViewComparabilityAudit(
            first_complete_piece_visible=True,
            second_complete_piece_visible=True,
            camera_view_matches=True,
            camera_elevation_matches=True,
            image_plane_rotation_matches=True,
            crop_and_frame_fill_match=True,
            review_scale_matches=True,
            background_family_matches=True,
            comparable=True,
            score=98,
        )
    )
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
        canonical_instruction = (
            "OVERALL DESIGNER REQUEST: "
            "Give the metal a warmer rose-gold appearance"
        )
        assert instruction == canonical_instruction
        assert scope == "appearance"
        assert mask is None
        assert variant == 4
        preview_sources.append(source)
        plan = build_image_plan(
            ImageOperation.REFERENCE_RENDER,
            canonical_instruction,
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
    assert created["revisions"] == []
    assert len(created["creative_candidates"]) == 3
    assert set(prompt_outputs) == {11, 12, 13}
    assert created["factory_ready"] is False
    assert "design_id" not in created
    assert "spec" not in created

    # Choose the middle displayed direction, proving downstream work does not
    # silently snap to the last generated sibling.
    first_id = created["creative_candidates"][0]["asset_id"]
    selected_id = created["creative_candidates"][1]["asset_id"]
    last_id = created["creative_candidates"][-1]["asset_id"]
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
    assert [item["asset_id"] for item in selected["revisions"]] == [selected_id]

    kept_response = client.post(
        f"/studio/projects/{root_id}/creative-candidates/{last_id}/variations",
        json={
            "created_by": "usr_journey",
            "expected_active_asset_id": selected_id,
            "expected_design_version": None,
            "label": "Third generated direction",
        },
    )
    assert kept_response.status_code == 201, kept_response.text
    kept = kept_response.json()
    assert kept["source_asset_id"] == last_id
    assert _stored_image(Session, kept["project"]["active_asset_id"]) == last_image

    reselection = client.post(
        f"/projects/{root_id}/creative-candidates/{first_id}/select",
        json={"created_by": "usr_journey"},
    )
    assert reselection.status_code == 409, reselection.text
    assert "Original direction is locked" in reselection.json()["detail"]
    assert client.get(f"/projects/{root_id}").json()[
        "selected_candidate_asset_id"
    ] == selected_id

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
    assert len(reopened["revisions"]) == 2
    assert {item["asset_id"] for item in reopened["revisions"]} == {
        selected_id, applied_id,
    }
    assert last_id not in {item["asset_id"] for item in reopened["revisions"]}
    applied_history = next(
        item for item in reopened["revisions"]
        if item["asset_id"] == applied_id
    )
    assert applied_history["parent_asset_id"] == selected_id
    assert applied_history["design_version"] is None
    assert applied_history["action"] == "edit"
    assert applied_history["interpretation"]["factory_authority"] is False

    branch_request = {
        "created_by": "usr_journey",
        "expected_active_asset_id": applied_id,
        "expected_design_version": None,
        "label": "Warm metal direction",
        "operation_id": "vary:journey-warm-metal-0001",
    }
    branch_response = client.post(
        f"/studio/projects/{root_id}/variations",
        json=branch_request,
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

    # A transport retry after the first response is lost returns the exact
    # committed sibling instead of charging for or creating another branch.
    replay_response = client.post(
        f"/studio/projects/{root_id}/variations",
        json=branch_request,
    )
    assert replay_response.status_code == 201, replay_response.text
    assert replay_response.json() == branch

    mismatched_retry = client.post(
        f"/studio/projects/{root_id}/variations",
        json={**branch_request, "label": "Different direction"},
    )
    assert mismatched_retry.status_code == 409, mismatched_retry.text
    assert mismatched_retry.json()["code"] == "variation_operation_conflict"

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
    assert len(final_history["revisions"]) == 3
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
        assert len(projects) == 3
        assets = list(db.scalars(select(ImageAsset)))
        assert all(asset.design_id is None for asset in assets)
        assert all(asset.design_version is None for asset in assets)
        assert all(asset.pinned_at is None for asset in assets)
        records = list(db.scalars(select(ProjectRevisionRecord)))
        assert {record.action for record in records} == {
            "created", "edit", "restore",
        }


def test_ten_mixed_source_projects_reopen_branch_compare_and_restore(
    prespec_journey_client,
):
    """Founder corpus stays useful without entering the Factory control plane."""

    client, Session = prespec_journey_client
    owner = "usr_mixed_journey"

    def prompt_provider(prompt: str, variant: int):
        image = _png((45 + variant, 75 + variant, 105 + variant))
        plan = build_image_plan(
            ImageOperation.CREATIVE_GENERATE,
            prompt,
            variant=variant,
        )
        return _accepted_result(plan, image)

    def reference_provider(
        source: bytes,
        instruction: str,
        variant: int,
        *,
        quality_source_image: bytes | None = None,
    ):
        image = _png((65 + variant, 95 + variant, 125 + variant))
        plan = build_image_plan(
            ImageOperation.REFERENCE_RENDER,
            instruction,
            source_image=source,
            quality_source_image=quality_source_image,
            variant=variant,
        )
        return _accepted_result(
            plan,
            image,
            source=source,
            quality_source=quality_source_image,
        )

    app.dependency_overrides[get_creative_prompt_generator] = (
        lambda: prompt_provider
    )
    app.dependency_overrides[get_creative_render_generator] = (
        lambda: reference_provider
    )

    def visual_preview_provider(
        source: bytes,
        instruction: str,
        scope: str,
        mask: bytes | None,
        variant: int,
    ):
        canonical_instruction = (
            "OVERALL DESIGNER REQUEST: "
            "Warm the metal while preserving every contour"
        )
        assert instruction == canonical_instruction
        assert scope == "appearance"
        assert mask is None
        image = _png((105 + variant, 125 + variant, 145 + variant))
        plan = build_image_plan(
            ImageOperation.REFERENCE_RENDER,
            canonical_instruction,
            source_image=source,
            variant=variant,
        )
        return _accepted_result(plan, image, source=source)

    app.dependency_overrides[get_studio_visual_preview_generator] = (
        lambda: visual_preview_provider
    )

    def role_reference(role: str, color: tuple[int, int, int]):
        return {
            "role": role,
            "image_base64": base64.b64encode(_png(color)).decode(),
            "media_type": "image/png",
        }

    corpus: list[dict[str, object]] = [
        {
            "kind": "brief",
            "text": "A quiet oval signet ring with a softened knife-edge band",
        },
        {
            "kind": "brief",
            "text": "A slim pearl pendant inspired by one falling raindrop",
        },
        {
            "kind": "brief",
            "text": "A sculptural bypass ring with two asymmetric leaves",
        },
        {
            "kind": "prompt",
            "text": (
                "An Art Deco platinum cocktail ring, emerald-cut blue "
                "sapphire, stepped diamond shoulders, restrained symmetry"
            ),
        },
        {
            "kind": "prompt",
            "text": (
                "A contemporary yellow-gold pendant using negative space, "
                "one cabochon moonstone, architectural gallery"
            ),
        },
        {
            "kind": "drawing",
            "source_kind": "drawing",
            "source": _png((32, 42, 52)),
            "instruction": "Render this pencil ring sketch faithfully.",
        },
        {
            "kind": "photograph",
            "source_kind": "photograph",
            "source": _png((62, 72, 82)),
            "instruction": "Preserve this photographed pendant silhouette.",
        },
        {
            "kind": "finished_render",
            "source_kind": "finished_render",
            "source": _png((92, 102, 112)),
            "instruction": "Preserve this finished brooch render as the master direction.",
        },
        {
            "kind": "role_labeled",
            "source_kind": "photograph",
            "source": _png((122, 132, 142)),
            "instruction": "Keep the master geometry; use references by role.",
            "references": [
                role_reference("material_style", (172, 132, 82)),
                role_reference("brand_direction", (192, 182, 212)),
            ],
        },
        {
            "kind": "role_labeled",
            "source_kind": "finished_render",
            "source": _png((152, 162, 172)),
            "instruction": "Keep the exact master; apply only advisory roles.",
            "references": [
                role_reference("material_style", (202, 162, 102)),
                role_reference("construction_detail", (72, 92, 122)),
                role_reference("brand_direction", (212, 202, 222)),
            ],
        },
    ]

    original_project_ids: set[str] = set()
    branch_project_ids: set[str] = set()
    immutable_images: dict[str, bytes] = {}

    for index, case in enumerate(corpus):
        starting_variant = 20 + (index * 2)
        common = {
            "variation_count": 2,
            "starting_variant": starting_variant,
            "owner": owner,
            "title": f"Mixed source study {index + 1}",
            "collection": "Ten-project acceptance",
            "tags": [str(case["kind"]), "no-factory"],
        }
        if case["kind"] in {"brief", "prompt"}:
            response = client.post("/projects/from-prompt", json={
                **common,
                "prompt": case["text"],
            })
        else:
            source = case["source"]
            assert isinstance(source, bytes)
            response = client.post("/projects/from-drawing", json={
                **common,
                "image_base64": base64.b64encode(source).decode(),
                "media_type": "image/png",
                "source_kind": case["source_kind"],
                "instruction": case["instruction"],
                "references": case.get("references", []),
            })
        assert response.status_code == 201, response.text
        created = response.json()
        project_id = created["root_id"]
        original_project_ids.add(project_id)
        assert created["factory_ready"] is False
        assert created.get("design_id") is None
        assert created.get("spec") is None
        assert created["revisions"] == []
        assert len(created["creative_candidates"]) == 2
        capabilities = {asset["capability"] for asset in created["assets"]}
        if "source_kind" in case:
            assert "CREATIVE_SOURCE" in capabilities
            source_asset = next(
                asset for asset in created["assets"]
                if asset["capability"] == "CREATIVE_SOURCE"
            )
            assert source_asset["source_kind"] == case["source_kind"]
            assert source_asset["provenance"] == (
                f"designer_supplied_{case['source_kind']}"
            )
            assert {
                candidate["source_kind"]
                for candidate in created["creative_candidates"]
            } == {case["source_kind"]}
        if case["kind"] == "role_labeled":
            assert "CREATIVE_REFERENCE_BOARD" in capabilities
            assert "CREATIVE_REFERENCE_MATERIAL_STYLE" in capabilities
            assert "CREATIVE_REFERENCE_BRAND_DIRECTION" in capabilities
            if len(case["references"]) == 3:
                assert "CREATIVE_REFERENCE_CONSTRUCTION_DETAIL" in capabilities

        first_id = created["creative_candidates"][0]["asset_id"]
        selected_id = created["creative_candidates"][1]["asset_id"]
        first_image = _stored_image(Session, first_id)
        selected_image = _stored_image(Session, selected_id)
        immutable_images[first_id] = first_image
        immutable_images[selected_id] = selected_image
        assert first_image != selected_image
        assert created["creative_candidates"][0]["sha256"] != (
            created["creative_candidates"][1]["sha256"]
        )

        selected = client.post(
            f"/projects/{project_id}/creative-candidates/{selected_id}/select",
            json={"created_by": owner},
        )
        assert selected.status_code == 200, selected.text
        assert selected.json()["active_asset_id"] == selected_id

        preview_response = client.post(
            f"/studio/projects/{project_id}/visual-previews",
            json={
                "created_by": owner,
                "expected_active_asset_id": selected_id,
                "instruction": "Warm the metal while preserving every contour",
                "scope": "appearance",
                "variant": index + 1,
            },
        )
        assert preview_response.status_code == 201, preview_response.text
        preview = preview_response.json()
        candidate_id = preview["candidate"]["candidate_id"]
        applied_response = client.post(
            f"/studio/image-runs/{preview['image_run_id']}/visual-candidates/"
            f"{candidate_id}/accept",
            json={
                "created_by": owner,
                "expected_active_asset_id": selected_id,
            },
        )
        assert applied_response.status_code == 201, applied_response.text
        applied = applied_response.json()
        applied_id = applied["new_asset_id"]
        applied_image = _stored_image(Session, applied_id)
        immutable_images[applied_id] = applied_image
        assert applied_id != selected_id

        # Save/reopen and history comparison use persisted API reads, not the
        # creation response retained by this test.
        reopened = client.get(f"/projects/{project_id}")
        assert reopened.status_code == 200, reopened.text
        reopened_project = reopened.json()
        assert reopened_project["active_asset_id"] == applied_id
        if "source_kind" in case:
            reopened_source = next(
                asset for asset in reopened_project["assets"]
                if asset["capability"] == "CREATIVE_SOURCE"
            )
            assert reopened_source["source_kind"] == case["source_kind"]
            assert reopened_source["provenance"] == (
                f"designer_supplied_{case['source_kind']}"
            )
        before = client.get(f"/studio/projects/{project_id}/history")
        assert before.status_code == 200, before.text
        before_history = before.json()
        assert before_history["active_asset_id"] == applied_id
        assert [item["asset_id"] for item in before_history["revisions"]] == [
            selected_id, applied_id,
        ]
        source_revision, applied_revision = before_history["revisions"]
        assert applied_revision["parent_asset_id"] == source_revision["asset_id"]
        assert applied_revision["action"] == "edit"
        assert applied_revision["raw_intent"]["image_run_id"] == (
            preview["image_run_id"]
        )
        assert applied_revision["interpretation"]["source_sha256"] == (
            hashlib.sha256(selected_image).hexdigest()
        )
        assert applied_revision["interpretation"]["output_sha256"] == (
            hashlib.sha256(applied_image).hexdigest()
        )

        branch_response = client.post(
            f"/studio/projects/{project_id}/variations",
            json={
                "created_by": owner,
                "expected_active_asset_id": applied_id,
                "expected_design_version": None,
                "label": f"Direction {index + 1}B",
                "operation_id": f"vary:journey-direction-{index + 1:04d}",
            },
        )
        assert branch_response.status_code == 201, branch_response.text
        branch = branch_response.json()
        branch_project = branch["project"]
        branch_project_ids.add(branch_project["root_id"])
        assert branch["source_project_id"] == project_id
        assert branch["source_asset_id"] == applied_id
        assert branch_project["factory_ready"] is False
        assert _stored_image(
            Session, branch_project["active_asset_id"],
        ) == applied_image

        # An unselected sibling is a candidate direction, not a historical
        # revision of this Variation, so Restore must fail closed.
        candidate_restore = client.post(
            f"/studio/projects/{project_id}/revisions/{first_id}/restore",
            json={
                "created_by": owner,
                "expected_active_asset_id": applied_id,
                "expected_design_version": None,
            },
        )
        assert candidate_restore.status_code == 422, candidate_restore.text
        assert candidate_restore.json()["code"] == "restore_source_not_revision"

        restore_response = client.post(
            f"/studio/projects/{project_id}/revisions/{selected_id}/restore",
            json={
                "created_by": owner,
                "expected_active_asset_id": applied_id,
                "expected_design_version": None,
            },
        )
        assert restore_response.status_code == 201, restore_response.text
        restored = restore_response.json()
        restored_id = restored["new_asset_id"]
        restored_image = _stored_image(Session, restored_id)
        immutable_images[restored_id] = restored_image
        assert restored_id not in {selected_id, applied_id}
        assert restored["restored_from_asset_id"] == selected_id
        assert restored_image == selected_image

        after = client.get(f"/studio/projects/{project_id}/history").json()
        assert after["active_asset_id"] == restored_id
        assert [item["asset_id"] for item in after["revisions"]] == [
            selected_id, applied_id, restored_id,
        ]
        restored_revision = after["revisions"][-1]
        assert restored_revision["action"] == "restore"
        assert restored_revision["parent_asset_id"] == applied_id
        assert restored_revision["restored_from_asset_id"] == selected_id
        assert _stored_image(Session, first_id) == first_image
        assert _stored_image(Session, selected_id) == selected_image
        assert _stored_image(Session, applied_id) == applied_image

    assert len(original_project_ids) == 10
    assert len(branch_project_ids) == 10
    assert original_project_ids.isdisjoint(branch_project_ids)

    with Session() as db:
        projects = list(db.scalars(select(Project)))
        assert len(projects) == 20
        assert db.scalar(select(func.count()).select_from(Design)) == 0
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 0
        assert db.scalar(select(func.count()).select_from(ApprovalChecklist)) == 0
        assets = list(db.scalars(select(ImageAsset)))
        assert all(asset.design_id is None for asset in assets)
        assert all(asset.design_version is None for asset in assets)
        assert all(asset.pinned_at is None for asset in assets)
        for asset_id, expected in immutable_images.items():
            stored = db.get(ImageAsset, asset_id)
            assert stored is not None
            assert bytes(stored.image) == expected

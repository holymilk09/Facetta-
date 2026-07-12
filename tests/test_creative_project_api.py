"""Input-agnostic creative projects stay useful without becoming factory truth."""

from __future__ import annotations

import base64
import copy
import hashlib
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from conftest import EXAMPLE_SPEC, audited_import_spec

from facetta.creative_workflow import (
    get_creative_prompt_generator,
    get_creative_render_generator,
)
from facetta.db import (
    Base,
    Design,
    DesignFamily,
    DesignVersion,
    ImageAsset,
    ImageRun,
    Project,
    get_db,
)
from facetta.image_agent import (
    CheckSeverity,
    CreativeRenderInspection,
    ImageOperation,
    ImageQualityFailure,
    ImageQualityReport,
    JewelryImageAgent,
    ProviderImage,
    QualityCheck,
    QualityVerdict,
    RingQualityEvaluator,
    build_image_plan,
)
from facetta.image_agent.planning import route_for_attempt
from facetta.image_agent.prompts import (
    compile_correction_prompt,
    compile_initial_prompt,
)
from facetta.image_region import crop_normalized_region
from facetta.main import app
from facetta.spec import Spec


def _png(color: tuple[int, int, int]) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (96, 96), color).save(out, format="PNG")
    return out.getvalue()


SOURCE = _png((245, 245, 245))


class _CreativeInspector:
    def __init__(self, inspection: CreativeRenderInspection):
        self.inspection = inspection

    def inspect_render(self, plan, reference, candidate):
        assert plan.operation is ImageOperation.REFERENCE_RENDER
        assert reference == SOURCE
        assert candidate != reference
        return self.inspection


class _PromptCreativeInspector:
    def __init__(self, inspection: CreativeRenderInspection):
        self.inspection = inspection

    def inspect_render(self, plan, candidate):
        assert plan.operation is ImageOperation.CREATIVE_GENERATE
        assert candidate
        return self.inspection


def _creative_result(variant: int):
    plan = build_image_plan(
        ImageOperation.REFERENCE_RENDER,
        "Render this exact jewelry design in polished yellow gold",
        source_image=SOURCE,
        variant=variant,
    )

    class Provider:
        def execute(self, *_args, **_kwargs):
            return ProviderImage(image_bytes=_png((80 + variant, 60, 30)))

    class Evaluator:
        def evaluate(self, *_args, **_kwargs):
            return ImageQualityReport(
                verdict=QualityVerdict.WARN,
                checks=(QualityCheck(
                    code="factory_authority",
                    passed=False,
                    severity=CheckSeverity.WARNING,
                    message="designer review required before specification",
                ),),
                score=92,
            )

    return JewelryImageAgent(Provider(), Evaluator()).run(
        plan, source_image=SOURCE)


def _prompt_creative_result(variant: int):
    plan = build_image_plan(
        ImageOperation.CREATIVE_GENERATE,
        "A platinum floral lariat necklace with emerald leaves",
        variant=variant,
    )

    class Provider:
        def execute(self, *_args, **_kwargs):
            return ProviderImage(image_bytes=_png((40, 90 + variant, 55)))

    class Evaluator:
        def evaluate(self, *_args, **_kwargs):
            return ImageQualityReport(
                verdict=QualityVerdict.WARN,
                checks=(QualityCheck(
                    code="factory_authority",
                    passed=False,
                    severity=CheckSeverity.WARNING,
                    message="designer review required before specification",
                ),),
                score=94,
            )

    return JewelryImageAgent(Provider(), Evaluator()).run(plan)


def test_prompt_creative_plan_is_category_neutral_and_review_only():
    plan = build_image_plan(
        ImageOperation.CREATIVE_GENERATE,
        "A platinum floral lariat necklace with emerald leaves",
        variant=2,
    )
    prompt = compile_initial_prompt(plan)
    assert plan.jewelry_type == "jewelry"
    assert plan.spec_facts == {"jewelry_type": "jewelry"}
    assert plan.prompt_version == "creative-generate.v3"
    assert route_for_attempt(plan, 1).value == "grok_generate"
    assert route_for_attempt(plan, 3).value == "flux_generate"
    assert "do not silently convert it into a ring" in prompt
    assert "not a specification, measured drawing, CAD" in prompt


def test_prompt_creative_qa_checks_direction_without_source_preservation():
    plan = build_image_plan(
        ImageOperation.CREATIVE_GENERATE,
        "A platinum floral lariat necklace with emerald leaves",
    )
    inspection = CreativeRenderInspection(
        coherent_jewelry_render=True,
        complete_piece_visible=True,
        requested_presentation_applied=True,
        explicit_counts_match=True,
        explicit_stone_facts_match=True,
        text_or_branding_detected=False,
        score=95,
    )
    report = RingQualityEvaluator(
        prompt_creative_inspector=_PromptCreativeInspector(inspection),
        require_cross_inspection=False,
        require_render_cross_inspection=False,
    ).evaluate(
        plan,
        _png((40, 100, 55)),
        source_image=None,
        mask_bytes=None,
    )
    assert report.verdict is QualityVerdict.WARN
    codes = {check.code for check in report.checks}
    assert "source_design_preserved" not in codes
    assert "visible_components_preserved" not in codes
    assert "factory_authority" in codes


def test_prompt_creative_qa_hard_fails_an_explicit_count_mismatch():
    plan = build_image_plan(
        ImageOperation.CREATIVE_GENERATE,
        "A necklace with exactly five marquise emerald leaves",
    )
    inspection = CreativeRenderInspection(
        coherent_jewelry_render=True,
        complete_piece_visible=True,
        requested_presentation_applied=True,
        explicit_counts_match=False,
        explicit_stone_facts_match=True,
        text_or_branding_detected=False,
        major_unintended_changes=("nine emerald leaves are visible",),
        score=78,
    )
    report = RingQualityEvaluator(
        prompt_creative_inspector=_PromptCreativeInspector(inspection),
        require_cross_inspection=False,
        require_render_cross_inspection=False,
    ).evaluate(
        plan,
        _png((40, 100, 55)),
        source_image=None,
        mask_bytes=None,
    )
    assert report.verdict is QualityVerdict.FAIL
    failed = {check.code for check in report.failed_checks}
    assert "explicit_counts_match" in failed
    _prompt, correction = compile_correction_prompt(
        plan, compile_initial_prompt(plan), report)
    assert "explicit_counts_match" in correction
    assert "factory_authority" not in correction


def test_prompt_creative_qa_rejects_cropping_and_wrong_named_stone_shapes():
    plan = build_image_plan(
        ImageOperation.CREATIVE_GENERATE,
        "Show the complete necklace with small round diamond dew drops",
    )
    inspection = CreativeRenderInspection(
        coherent_jewelry_render=True,
        complete_piece_visible=False,
        requested_presentation_applied=True,
        explicit_counts_match=True,
        explicit_stone_facts_match=False,
        text_or_branding_detected=False,
        major_unintended_changes=(
            "chain endpoints are cropped",
            "leaf-shaped diamonds replace part of the round diamond group",
        ),
        score=72,
    )
    report = RingQualityEvaluator(
        prompt_creative_inspector=_PromptCreativeInspector(inspection),
        require_cross_inspection=False,
        require_render_cross_inspection=False,
    ).evaluate(
        plan,
        _png((40, 100, 55)),
        source_image=None,
        mask_bytes=None,
    )
    assert report.verdict is QualityVerdict.FAIL
    assert {check.code for check in report.failed_checks} >= {
        "complete_piece_visible",
        "explicit_stone_facts_match",
    }


def test_reference_render_plan_uses_neutral_source_contract_and_edit_routes():
    plan = build_image_plan(
        ImageOperation.REFERENCE_RENDER,
        "Use platinum and a clean studio background",
        source_image=SOURCE,
        variant=3,
    )
    prompt = compile_initial_prompt(plan)
    assert plan.jewelry_type == "jewelry"
    assert plan.spec_facts == {"jewelry_type": "jewelry"}
    assert plan.prompt_version == "reference-render.v1"
    assert route_for_attempt(plan, 1).value == "grok_edit"
    assert route_for_attempt(plan, 2).value == "grok_edit"
    assert route_for_attempt(plan, 3).value == "flux_kontext_edit"
    assert "FAITHFUL BEST EFFORT" in prompt
    assert "Do not classify or grade the source" in prompt
    assert "not a specification, measurement, CAD model, or factory drawing" in prompt


def test_reference_render_default_qa_requires_review_but_accepts_no_major_drift():
    plan = build_image_plan(
        ImageOperation.REFERENCE_RENDER,
        "polished product render",
        source_image=SOURCE,
    )
    inspection = CreativeRenderInspection(
        coherent_jewelry_render=True,
        source_design_preserved=True,
        visible_components_preserved=True,
        local_geometry_preserved=True,
        repeated_element_pattern_preserved=True,
        stone_shape_and_cut_family_preserved=True,
        requested_presentation_applied=True,
        text_or_branding_detected=False,
        score=95,
    )
    report = RingQualityEvaluator(
        creative_inspector=_CreativeInspector(inspection),
        require_cross_inspection=False,
        require_render_cross_inspection=False,
    ).evaluate(
        plan,
        _png((80, 60, 40)),
        source_image=SOURCE,
        mask_bytes=None,
    )
    assert report.verdict is QualityVerdict.WARN
    assert all(check.passed for check in report.checks
               if check.severity is CheckSeverity.HARD)
    authority = next(check for check in report.checks
                     if check.code == "factory_authority")
    assert authority.severity is CheckSeverity.WARNING
    assert authority.passed is False


def test_reference_render_qa_hard_fails_silent_redesign():
    plan = build_image_plan(
        ImageOperation.REFERENCE_RENDER,
        "polished product render",
        source_image=SOURCE,
    )
    inspection = CreativeRenderInspection(
        coherent_jewelry_render=True,
        source_design_preserved=False,
        visible_components_preserved=False,
        local_geometry_preserved=False,
        repeated_element_pattern_preserved=False,
        stone_shape_and_cut_family_preserved=False,
        requested_presentation_applied=True,
        text_or_branding_detected=False,
        major_unintended_changes=("a second halo was invented",),
        score=45,
    )
    report = RingQualityEvaluator(
        creative_inspector=_CreativeInspector(inspection),
        require_cross_inspection=False,
        require_render_cross_inspection=False,
    ).evaluate(
        plan,
        _png((80, 60, 40)),
        source_image=SOURCE,
        mask_bytes=None,
    )
    assert report.verdict is QualityVerdict.FAIL
    assert {check.code for check in report.failed_checks} >= {
        "source_design_preserved",
        "visible_components_preserved",
        "local_geometry_preserved",
        "repeated_element_pattern_preserved",
        "stone_shape_and_cut_family_preserved",
    }


def test_reference_render_qa_rejects_attractive_local_pattern_drift():
    plan = build_image_plan(
        ImageOperation.REFERENCE_RENDER,
        "polished product render",
        source_image=SOURCE,
    )
    inspection = CreativeRenderInspection(
        coherent_jewelry_render=True,
        complete_piece_visible=True,
        source_design_preserved=True,
        visible_components_preserved=True,
        local_geometry_preserved=False,
        repeated_element_pattern_preserved=False,
        stone_shape_and_cut_family_preserved=True,
        requested_presentation_applied=True,
        text_or_branding_detected=False,
        major_unintended_changes=(
            "rectangular shoulder ladder became round pavé",
        ),
        score=78,
    )
    report = RingQualityEvaluator(
        creative_inspector=_CreativeInspector(inspection),
        require_cross_inspection=False,
        require_render_cross_inspection=False,
    ).evaluate(
        plan,
        _png((80, 60, 40)),
        source_image=SOURCE,
        mask_bytes=None,
    )

    assert report.verdict is QualityVerdict.FAIL
    assert {
        check.code for check in report.failed_checks
        if check.severity is CheckSeverity.HARD
    } == {
        "local_geometry_preserved",
        "repeated_element_pattern_preserved",
    }


def test_reference_render_skeptical_cross_audit_vetoes_primary_pass():
    plan = build_image_plan(
        ImageOperation.REFERENCE_RENDER,
        "polished product render",
        source_image=SOURCE,
    )
    primary = CreativeRenderInspection(
        coherent_jewelry_render=True,
        complete_piece_visible=True,
        source_design_preserved=True,
        visible_components_preserved=True,
        local_geometry_preserved=True,
        repeated_element_pattern_preserved=True,
        stone_shape_and_cut_family_preserved=True,
        requested_presentation_applied=True,
        text_or_branding_detected=False,
        score=94,
    )
    skeptical = primary.model_copy(update={
        "source_design_preserved": False,
        "local_geometry_preserved": False,
        "repeated_element_pattern_preserved": False,
        "score": 42,
        "major_unintended_changes": (
            "rectangular shank ladder became round pavé",
        ),
    })
    report = RingQualityEvaluator(
        creative_inspector=_CreativeInspector(primary),
        creative_cross_inspector=_CreativeInspector(skeptical),
        require_cross_inspection=False,
        require_render_cross_inspection=False,
    ).evaluate(
        plan,
        _png((80, 60, 40)),
        source_image=SOURCE,
        mask_bytes=None,
    )

    assert report.verdict is QualityVerdict.FAIL
    assert report.score == 42
    assert {
        check.code for check in report.failed_checks
        if check.severity is CheckSeverity.HARD
    } >= {
        "source_design_preserved",
        "local_geometry_preserved",
        "repeated_element_pattern_preserved",
    }
    assert "rectangular shank ladder became round pavé" in report.notes


@pytest.fixture
def creative_client():
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
    client = TestClient(app)
    try:
        yield client, Session
    finally:
        app.dependency_overrides.clear()


def _request(*, variation_count: int = 2) -> dict[str, object]:
    return {
        "image_base64": base64.b64encode(SOURCE).decode(),
        "media_type": "image/png",
        "instruction": "Render this exact jewelry design in polished yellow gold",
        "variation_count": variation_count,
        "starting_variant": 7,
        "owner": "usr_designer",
        "title": "Unspecified jewelry study",
        "collection": "Exploration",
        "tags": ["source-led"],
    }


def _role_reference(
    role: str,
    color: tuple[int, int, int],
    *,
    media_type: str = "image/png",
) -> dict[str, str]:
    return {
        "role": role,
        "image_base64": base64.b64encode(_png(color)).decode(),
        "media_type": media_type,
    }


def _prompt_request(*, variation_count: int = 3) -> dict[str, object]:
    return {
        "prompt": "A platinum floral lariat necklace with emerald leaves",
        "variation_count": variation_count,
        "starting_variant": 4,
        "owner": "usr_designer",
        "title": "Emerald lariat exploration",
        "collection": "Exploration",
        "tags": ["prompt-led", "necklace"],
    }


def _visual_form_spec(*, instance_count: int = 1) -> dict:
    raw = copy.deepcopy(EXAMPLE_SPEC)
    raw["design_form"] = {"elements": [{
        "element_id": "assembly.full",
        "role": "full_assembly",
        "label": "Custom complete assembly",
        "confirmed_form_description": "Complete custom front assembly.",
        "symmetry": "asymmetric",
        "instance_count": instance_count,
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
            "kind": "visual_reference_only",
            "asset_id": "ast_candidate_placeholder",
            "asset_sha256": "1" * 64,
        },
    }]}
    return audited_import_spec(raw)


def _profile_confirmation_payload(spec: dict) -> dict:
    return {
        "spec": spec,
        "element_id": "assembly.full",
        "profile": {
            "view": "front",
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
            "manufacturing_notes": (
                "Designer-confirmed prototype profile; verify at bench."
            ),
        },
        "created_by": "usr_designer",
    }


def test_from_prompt_persists_independent_candidates_without_source_or_spec(
    creative_client,
):
    client, Session = creative_client
    variants: list[int] = []

    def generate(instruction: str, variant: int):
        assert "lariat necklace" in instruction
        variants.append(variant)
        return _prompt_creative_result(variant)

    app.dependency_overrides[get_creative_prompt_generator] = lambda: generate
    response = client.post("/projects/from-prompt", json=_prompt_request())
    assert response.status_code == 201, response.text
    body = response.json()
    assert variants == [4, 5, 6]
    assert body["state"] == "refining"
    assert "design_id" not in body
    assert "spec" not in body
    assert body["factory_ready"] is False
    assert len(body["revisions"]) == 3
    assert all(item["capability"] == "CREATIVE_RENDER"
               for item in body["revisions"])
    assert all(item["provenance"] == "pre_spec_creative_candidate"
               for item in body["revisions"])
    assert not any(item["capability"] == "CREATIVE_SOURCE"
                   for item in body["assets"])
    assert body["root_id"] == body["revisions"][0]["asset_id"]
    selected_id = body["revisions"][1]["asset_id"]
    selected = client.post(
        f"/projects/{body['root_id']}/creative-candidates/{selected_id}/select",
        json={"created_by": "usr_designer"},
    )
    assert selected.status_code == 200, selected.text
    selected_body = selected.json()
    assert selected_body["selected_candidate_asset_id"] == selected_id
    assert selected_body["active_asset_id"] == selected_id
    assert selected_body["cover_asset_id"] == selected_id
    assert "spec" not in selected_body

    with Session() as db:
        saved_project = db.get(Project, body["root_id"])
        assert saved_project is not None
        assert saved_project.family_id is not None
        assert saved_project.variation_index == 1
        assert saved_project.variation_label == "Original"
        assert db.get(DesignFamily, saved_project.family_id) is not None
        assert db.scalar(select(func.count()).select_from(Project)) == 1
        assert db.scalar(select(func.count()).select_from(Design)) == 0
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 0
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 3
        runs = list(db.scalars(select(ImageRun).order_by(ImageRun.variant)))
        assert [run.operation for run in runs] == [
            "CREATIVE_GENERATE", "CREATIVE_GENERATE", "CREATIVE_GENERATE"]
        assert [run.variant for run in runs] == [4, 5, 6]
        assert all(run.source_asset_id is None for run in runs)


def test_from_prompt_validates_variation_bounds(creative_client):
    client, _Session = creative_client
    assert client.post(
        "/projects/from-prompt", json=_prompt_request(variation_count=0)
    ).status_code == 422
    assert client.post(
        "/projects/from-prompt", json=_prompt_request(variation_count=5)
    ).status_code == 422


def test_from_drawing_persists_variations_without_inventing_a_spec(
    creative_client,
):
    client, Session = creative_client
    variants: list[int] = []

    def generate(source: bytes, instruction: str, variant: int):
        assert source == SOURCE
        assert "exact jewelry design" in instruction
        variants.append(variant)
        return _creative_result(variant)

    app.dependency_overrides[get_creative_render_generator] = lambda: generate
    response = client.post("/projects/from-drawing", json=_request())
    assert response.status_code == 201, response.text
    body = response.json()
    assert variants == [7, 8]
    assert body["state"] == "refining"
    assert "design_id" not in body
    assert "latest_design_version" not in body
    assert "spec" not in body
    assert body["factory_ready"] is False
    assert [item["capability"] for item in body["revisions"]] == [
        "CREATIVE_RENDER", "CREATIVE_RENDER"]
    assert all("design_version" not in item for item in body["revisions"])
    assert body["assets"][0]["capability"] == "CREATIVE_SOURCE"
    assert len(body["image_run_ids"]) == 2

    with Session() as db:
        saved_project = db.get(Project, body["root_id"])
        assert saved_project is not None
        assert saved_project.family_id is not None
        assert saved_project.variation_index == 1
        assert saved_project.variation_label == "Original"
        assert db.scalar(select(func.count()).select_from(Project)) == 1
        assert db.scalar(select(func.count()).select_from(Design)) == 0
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 0
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 3
        runs = list(db.scalars(select(ImageRun).order_by(ImageRun.variant)))
        assert [run.operation for run in runs] == [
            "REFERENCE_RENDER", "REFERENCE_RENDER"]
        assert [run.variant for run in runs] == [7, 8]
        assert all(run.status == "review_required" for run in runs)


def test_from_drawing_role_board_is_canonical_persisted_and_reopenable(
    creative_client,
):
    client, Session = creative_client
    material = _role_reference("material_style", (186, 138, 72))
    construction = _role_reference("construction_detail", (84, 102, 128))
    brand = _role_reference("brand_direction", (204, 184, 216))
    calls: list[tuple[bytes, str, int]] = []

    def generate(source: bytes, instruction: str, variant: int):
        calls.append((source, instruction, variant))
        plan = build_image_plan(
            ImageOperation.REFERENCE_RENDER,
            instruction,
            source_image=source,
            variant=variant,
        )

        class Provider:
            def execute(self, *_args, **_kwargs):
                return ProviderImage(image_bytes=_png((70 + variant, 61, 51)))

        class Evaluator:
            def evaluate(self, *_args, **_kwargs):
                return ImageQualityReport(
                    verdict=QualityVerdict.WARN,
                    checks=(),
                    score=94,
                )

        return JewelryImageAgent(Provider(), Evaluator()).run(
            plan, source_image=source,
        )

    app.dependency_overrides[get_creative_render_generator] = lambda: generate
    response = client.post("/projects/from-drawing", json={
        **_request(variation_count=4),
        # Caller order cannot alter image numbering or cache identity.
        "references": [brand, material, construction],
    })
    assert response.status_code == 201, response.text
    body = response.json()
    assert len(calls) == 4
    assert [call[2] for call in calls] == [7, 8, 9, 10]
    assert all(call[0] == calls[0][0] for call in calls)
    assert all(call[1] == calls[0][1] for call in calls)
    instruction = calls[0][1]
    assert instruction.index("IMAGE 1 — MASTER GEOMETRY") < instruction.index(
        "IMAGE 2 — MATERIAL & STYLE"
    ) < instruction.index("IMAGE 3 — CONSTRUCTION DETAIL") < instruction.index(
        "IMAGE 4 — BRAND DIRECTION"
    )
    assert "sole authority for the jewelry's identity" in instruction
    assert "surface-only guidance" in instruction
    assert "not a confirmed construction fact" in instruction
    assert "visual-language guidance" in instruction
    assert "proof of manufacturability" in instruction
    assert hashlib.sha256(SOURCE).hexdigest() in instruction
    for reference in (material, construction, brand):
        assert hashlib.sha256(base64.b64decode(
            reference["image_base64"]
        )).hexdigest() in instruction

    assert len(body["revisions"]) == 4
    assets = {asset["capability"]: asset for asset in body["assets"]}
    assert assets["CREATIVE_SOURCE"]["provenance"] == (
        "designer_supplied_source"
    )
    assert assets["CREATIVE_REFERENCE_BOARD"]["provenance"] == (
        "role_labeled_reference_board"
    )
    role_assets = {
        "material_style": assets["CREATIVE_REFERENCE_MATERIAL_STYLE"],
        "construction_detail": assets["CREATIVE_REFERENCE_CONSTRUCTION_DETAIL"],
        "brand_direction": assets["CREATIVE_REFERENCE_BRAND_DIRECTION"],
    }
    assert role_assets["material_style"]["provenance"] == "material_style_reference"
    assert role_assets["construction_detail"]["provenance"] == "construction_detail_reference"
    assert role_assets["brand_direction"]["provenance"] == "brand_direction_reference"
    reopened = client.get(f"/projects/{body['root_id']}")
    assert reopened.status_code == 200, reopened.text
    reopened_assets = {
        asset["capability"]: asset for asset in reopened.json()["assets"]
    }
    assert reopened_assets["CREATIVE_REFERENCE_BOARD"]["instruction"] == (
        assets["CREATIVE_REFERENCE_BOARD"]["instruction"]
    )

    with Session() as db:
        root = db.get(ImageAsset, body["root_id"])
        assert root is not None
        assert bytes(root.image) == SOURCE
        board_asset = db.get(
            ImageAsset, assets["CREATIVE_REFERENCE_BOARD"]["asset_id"]
        )
        assert board_asset is not None
        assert bytes(board_asset.image) == calls[0][0]
        assert board_asset.parent_asset_id == root.id
        for role, reference in {
            "material_style": material,
            "construction_detail": construction,
            "brand_direction": brand,
        }.items():
            stored = db.get(ImageAsset, role_assets[role]["asset_id"])
            assert stored is not None
            assert bytes(stored.image) == base64.b64decode(reference["image_base64"])
            assert stored.parent_asset_id == root.id
        runs = list(db.scalars(select(ImageRun).order_by(ImageRun.variant)))
        assert len(runs) == 4
        assert all(run.source_asset_id == board_asset.id for run in runs)
        assert all(
            run.source_hash == hashlib.sha256(bytes(board_asset.image)).hexdigest()
            for run in runs
        )


@pytest.mark.parametrize("variation_count", [1, 4])
def test_role_labeled_references_preserve_candidate_count_boundaries(
    creative_client,
    variation_count,
):
    client, _Session = creative_client
    variants: list[int] = []

    def generate(source: bytes, instruction: str, variant: int):
        variants.append(variant)
        plan = build_image_plan(
            ImageOperation.REFERENCE_RENDER,
            instruction,
            source_image=source,
            variant=variant,
        )

        class Provider:
            def execute(self, *_args, **_kwargs):
                return ProviderImage(image_bytes=_png((50 + variant, 80, 90)))

        class Evaluator:
            def evaluate(self, *_args, **_kwargs):
                return ImageQualityReport(
                    verdict=QualityVerdict.WARN, checks=(), score=91,
                )

        return JewelryImageAgent(Provider(), Evaluator()).run(
            plan, source_image=source,
        )

    app.dependency_overrides[get_creative_render_generator] = lambda: generate
    response = client.post("/projects/from-drawing", json={
        **_request(variation_count=variation_count),
        "references": [_role_reference(
            "material_style", (160, 120, 60)
        )],
    })
    assert response.status_code == 201, response.text
    assert len(response.json()["revisions"]) == variation_count
    assert variants == list(range(7, 7 + variation_count))


def test_from_drawing_isolates_and_persists_exact_multi_view_source_region(
    creative_client,
):
    client, Session = creative_client
    expected_crop = crop_normalized_region(
        SOURCE, x=0.10, y=0.10, width=0.80, height=0.80,
    )
    calls: list[tuple[bytes, str, int]] = []

    def generate(source: bytes, instruction: str, variant: int):
        calls.append((source, instruction, variant))
        plan = build_image_plan(
            ImageOperation.REFERENCE_RENDER,
            instruction,
            source_image=source,
            variant=variant,
        )

        class Provider:
            def execute(self, *_args, **_kwargs):
                return ProviderImage(image_bytes=_png((91, 72, 51)))

        class Evaluator:
            def evaluate(self, *_args, **_kwargs):
                return ImageQualityReport(
                    verdict=QualityVerdict.WARN,
                    checks=(QualityCheck(
                        code="designer_review",
                        passed=False,
                        severity=CheckSeverity.WARNING,
                        message="Review exact selected-view interpretation.",
                    ),),
                    score=93,
                )

        return JewelryImageAgent(Provider(), Evaluator()).run(
            plan, source_image=source,
        )

    app.dependency_overrides[get_creative_render_generator] = lambda: generate
    response = client.post("/projects/from-drawing", json={
        **_request(variation_count=1),
        "source_region_description": "Front necklace elevation",
        "source_region": {
            "x": 0.10,
            "y": 0.10,
            "width": 0.80,
            "height": 0.80,
        },
    })

    assert response.status_code == 201, response.text
    assert len(calls) == 1
    assert calls[0][0] == expected_crop
    assert "Front necklace elevation" in calls[0][1]
    assert "one view of one finished piece" in calls[0][1]
    body = response.json()
    assets = {asset["capability"]: asset for asset in body["assets"]}
    assert assets["CREATIVE_SOURCE"]["provenance"] == "designer_supplied_source"
    assert assets["CREATIVE_SOURCE_REGION"]["provenance"] == (
        "designer_selected_source_region"
    )

    with Session() as db:
        rows = list(db.scalars(select(ImageAsset)))
        full_source = next(row for row in rows if row.capability == "CREATIVE_SOURCE")
        crop_source = next(
            row for row in rows if row.capability == "CREATIVE_SOURCE_REGION"
        )
        candidate = next(row for row in rows if row.capability == "CREATIVE_RENDER")
        run = db.scalar(select(ImageRun))
        assert run is not None
        assert full_source.image == SOURCE
        assert crop_source.image == expected_crop
        assert crop_source.parent_asset_id == full_source.id
        assert "normalized crop x=0.1000" in crop_source.instruction
        assert candidate.parent_asset_id == crop_source.id
        assert run.source_asset_id == crop_source.id
        assert run.source_hash == hashlib.sha256(expected_crop).hexdigest()


def test_from_drawing_rejects_region_description_without_coordinates(
    creative_client,
):
    client, Session = creative_client
    response = client.post("/projects/from-drawing", json={
        **_request(variation_count=1),
        "source_region_description": "Front necklace elevation",
    })

    assert response.status_code == 422
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(Project)) == 0
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 0


@pytest.mark.parametrize("references", [
    [
        _role_reference("material_style", (1, 2, 3)),
        _role_reference("material_style", (4, 5, 6)),
    ],
    [
        _role_reference("material_style", (1, 2, 3)),
        _role_reference("construction_detail", (4, 5, 6)),
        _role_reference("brand_direction", (7, 8, 9)),
        _role_reference("material_style", (10, 11, 12)),
    ],
    [{
        "role": "master_geometry",
        "image_base64": base64.b64encode(_png((1, 2, 3))).decode(),
        "media_type": "image/png",
    }],
])
def test_from_drawing_rejects_duplicate_excess_or_unknown_secondary_roles(
    creative_client,
    references,
):
    client, Session = creative_client
    response = client.post("/projects/from-drawing", json={
        **_request(variation_count=1),
        "references": references,
    })
    assert response.status_code == 422
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(Project)) == 0
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 0


@pytest.mark.parametrize(("reference", "code"), [
    ({
        "role": "material_style",
        "image_base64": "not-valid-base64!",
        "media_type": "image/png",
    }, "creative_reference_invalid_base64"),
    ({
        "role": "construction_detail",
        "image_base64": base64.b64encode(b"plain text").decode(),
        "media_type": "image/png",
    }, "creative_reference_unsupported_media"),
    ({
        "role": "brand_direction",
        "image_base64": base64.b64encode(_png((1, 2, 3))).decode(),
        "media_type": "image/jpeg",
    }, "creative_reference_media_mismatch"),
])
def test_from_drawing_validates_each_secondary_reference_exactly(
    creative_client,
    reference,
    code,
):
    client, Session = creative_client
    response = client.post("/projects/from-drawing", json={
        **_request(variation_count=1),
        "references": [reference],
    })
    assert response.status_code == 422
    assert response.json()["code"] == code
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(Project)) == 0
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 0


def test_role_reference_generation_failure_leaves_no_project_or_assets(
    creative_client,
):
    client, Session = creative_client

    def fail(source: bytes, instruction: str, variant: int):
        assert b"PNG" in source[:16]
        assert "ROLE-LABELED REFERENCE BOARD" in instruction
        plan = build_image_plan(
            ImageOperation.REFERENCE_RENDER,
            instruction,
            source_image=source,
            variant=variant,
        )
        raise ImageQualityFailure(
            "candidate failed source fidelity",
            report=ImageQualityReport(
                verdict=QualityVerdict.FAIL,
                checks=(QualityCheck(
                    code="source_design_preserved",
                    passed=False,
                    severity=CheckSeverity.HARD,
                    message="major source drift",
                ),),
                score=30,
            ),
            attempts=[],
            plan=plan,
        )

    app.dependency_overrides[get_creative_render_generator] = lambda: fail
    response = client.post("/projects/from-drawing", json={
        **_request(variation_count=1),
        "references": [_role_reference(
            "material_style", (120, 90, 50)
        )],
    })
    assert response.status_code == 422
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(Project)) == 0
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 0
        assert db.scalar(select(func.count()).select_from(Design)) == 0
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 0
        assert db.scalar(select(func.count()).select_from(ImageRun)) == 1


def test_selected_creative_candidate_can_be_read_without_persisting_spec(
    creative_client, monkeypatch,
):
    client, Session = creative_client
    variant = 7
    candidate_bytes = _png((80 + variant, 60, 30))
    app.dependency_overrides[get_creative_render_generator] = (
        lambda: (lambda _source, _instruction, selected: _creative_result(selected)))
    created = client.post(
        "/projects/from-drawing", json=_request(variation_count=1)).json()
    candidate_id = created["revisions"][0]["asset_id"]
    expected = Spec.model_validate(audited_import_spec(EXAMPLE_SPEC))

    def read_candidate(request):
        assert base64.b64decode(request.image_base64) == candidate_bytes
        assert request.created_by == "usr_designer"
        assert request.run_independent_audit is True
        assert request.notes == "Keep the exact shoulder geometry."
        return expected

    monkeypatch.setattr("facetta.api.projects.from_photo", read_candidate)
    response = client.post(
        f"/projects/{created['id']}/creative-candidates/{candidate_id}/draft",
        json={
            "notes": "Keep the exact shoulder geometry.",
            "created_by": "usr_designer",
            "run_independent_audit": True,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["design_id"] == EXAMPLE_SPEC["design_id"]
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(Design)) == 0
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 0


def test_designer_confirms_profile_against_exact_server_candidate_bytes(
    creative_client,
):
    client, Session = creative_client
    app.dependency_overrides[get_creative_render_generator] = (
        lambda: (lambda _source, _instruction, selected: _creative_result(selected))
    )
    created = client.post(
        "/projects/from-drawing",
        json=_request(variation_count=1),
    ).json()
    candidate_id = created["revisions"][0]["asset_id"]
    candidate_bytes = _png((87, 60, 30))

    response = client.post(
        f"/projects/{created['id']}/creative-candidates/{candidate_id}/"
        "dimensioned-profile/confirm",
        json=_profile_confirmation_payload(_visual_form_spec()),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    definition = body["definition"]
    assert body["candidate_asset_id"] == candidate_id
    assert body["candidate_sha256"] == hashlib.sha256(candidate_bytes).hexdigest()
    assert body["previous_definition_kind"] == "visual_reference_only"
    assert definition["kind"] == "dimensioned_profile"
    assert definition["source_asset_id"] == candidate_id
    assert definition["source_asset_sha256"] == body["candidate_sha256"]
    assert definition["confirmed_by"] == "usr_designer"
    assert body["spec"]["design_form"]["elements"][0]["definition"] == definition
    assert body["source_reaudit_required"] is True
    assert body["factory_ready"] is False
    assert body["sheet_authority"] == "preliminary_not_for_production"
    blocker_codes = {item["code"] for item in body["blockers"]}
    assert "visual_reference_not_dimensioned" not in blocker_codes
    assert "source_component_spec_audit_stale" in blocker_codes
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(Design)) == 0
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 0


def test_profile_confirmation_rejects_repeated_partial_target(
    creative_client,
):
    client, _Session = creative_client
    app.dependency_overrides[get_creative_render_generator] = (
        lambda: (lambda _source, _instruction, selected: _creative_result(selected))
    )
    created = client.post(
        "/projects/from-drawing",
        json=_request(variation_count=1),
    ).json()
    candidate_id = created["revisions"][0]["asset_id"]

    response = client.post(
        f"/projects/{created['id']}/creative-candidates/{candidate_id}/"
        "dimensioned-profile/confirm",
        json=_profile_confirmation_payload(_visual_form_spec(instance_count=2)),
    )

    assert response.status_code == 422, response.text
    assert response.json()["code"] == (
        "full_assembly_profile_requires_single_instance"
    )


def test_creative_candidate_confirmation_uses_exact_server_held_bytes(
    creative_client,
):
    client, _Session = creative_client
    app.dependency_overrides[get_creative_render_generator] = (
        lambda: (lambda _source, _instruction, selected: _creative_result(selected)))
    created = client.post(
        "/projects/from-drawing", json=_request(variation_count=1)).json()
    candidate_id = created["revisions"][0]["asset_id"]
    raw = audited_import_spec(EXAMPLE_SPEC)
    raw["source_component_coverage"]["components"][0][
        "independent_audit"
    ]["verdict"] = "inconclusive"
    spec = Spec.model_validate(raw)

    response = client.post(
        f"/projects/{created['id']}/creative-candidates/{candidate_id}/"
        "source-coverage/confirm",
        json={
            "spec": spec.model_dump(mode="json"),
            "confirmations": [{
                "component_id": "assembly.primary",
                "basis": "visible_source",
                "confirmed_description": "The complete ring assembly is visible.",
            }],
            "created_by": "usr_designer",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    confirmation = body["spec"]["source_component_coverage"]["components"][0][
        "designer_confirmation"
    ]
    assert confirmation["evidence_sha256"] == hashlib.sha256(
        _png((87, 60, 30))).hexdigest()
    assert body["factory_ready"] is True


def test_creative_candidate_mapping_reaudit_receives_stored_candidate_image(
    creative_client, monkeypatch,
):
    client, _Session = creative_client
    app.dependency_overrides[get_creative_render_generator] = (
        lambda: (lambda _source, _instruction, selected: _creative_result(selected)))
    created = client.post(
        "/projects/from-drawing", json=_request(variation_count=1)).json()
    candidate_id = created["revisions"][0]["asset_id"]
    spec = Spec.model_validate(audited_import_spec(EXAMPLE_SPEC))

    def resolve(request):
        assert base64.b64decode(request.source_image_base64) == _png((87, 60, 30))
        assert request.run_independent_audit is True
        return {"spec": request.spec.model_dump(mode="json"), "checked": True}

    monkeypatch.setattr("facetta.api.projects.resolve_source_coverage", resolve)
    response = client.post(
        f"/projects/{created['id']}/creative-candidates/{candidate_id}/"
        "source-coverage/resolve",
        json={
            "spec": spec.model_dump(mode="json"),
            "resolutions": [],
            "created_by": "usr_designer",
            "run_independent_audit": True,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["checked"] is True


def test_creative_candidate_cannot_be_approved_pinned_or_factory_exported(
    creative_client,
):
    client, _Session = creative_client
    app.dependency_overrides[get_creative_render_generator] = (
        lambda: (lambda _source, _instruction, variant: _creative_result(variant)))
    created = client.post(
        "/projects/from-drawing", json=_request(variation_count=1))
    assert created.status_code == 201
    body = created.json()
    candidate_id = body["active_asset_id"]
    project_id = body["root_id"]

    checklist = client.post(
        f"/assets/{candidate_id}/checklist",
        json={"created_by": "usr_designer"},
    )
    assert checklist.status_code == 409
    assert checklist.json()["code"] == "creative_candidate_requires_spec_promotion"

    pin = client.post(f"/assets/{candidate_id}/pin")
    assert pin.status_code == 409
    assert pin.json()["code"] == "creative_candidate_requires_spec_promotion"

    manifest = client.get(f"/projects/{project_id}/factory-pack")
    assert manifest.status_code == 409
    assert manifest.json()["code"] == (
        "creative_candidate_requires_spec_promotion")


def test_designer_can_promote_exactly_one_candidate_to_immutable_spec_v1(
    creative_client,
):
    client, Session = creative_client
    app.dependency_overrides[get_creative_render_generator] = (
        lambda: (lambda _source, _instruction, variant: _creative_result(variant)))
    created = client.post("/projects/from-drawing", json=_request())
    body = created.json()
    project_id = body["root_id"]
    selected_id = body["revisions"][0]["asset_id"]

    promoted = client.post(
        f"/projects/{project_id}/creative-candidates/{selected_id}/promote",
        json={
            "created_by": "usr_designer",
            "spec": audited_import_spec(EXAMPLE_SPEC),
        },
    )
    assert promoted.status_code == 200, promoted.text
    result = promoted.json()
    assert result["design_id"].startswith("dsn_")
    assert result["latest_design_version"] == 1
    assert result["active_design_version"] == 1
    assert result["active_revision"]["capability"] == "IMPORTED_REFERENCE"
    assert result["active_revision"]["parent_asset_id"] == selected_id
    creative = [item for item in result["revisions"]
                if item["capability"] == "CREATIVE_RENDER"]
    assert len(creative) == 2
    assert all(item["provenance"] == "pre_spec_creative_candidate"
               for item in creative)
    assert all(item["legacy_provenance"] is False for item in creative)

    checklist = client.post(
        f"/assets/{result['active_asset_id']}/checklist",
        json={"created_by": "usr_designer"},
    )
    assert checklist.status_code == 201, checklist.text

    second = client.post(
        f"/projects/{project_id}/creative-candidates/{body['revisions'][1]['asset_id']}/promote",
        json={
            "created_by": "usr_designer",
            "spec": audited_import_spec(EXAMPLE_SPEC),
        },
    )
    assert second.status_code == 409
    assert second.json()["code"] == "creative_candidate_promotion_conflict"

    with Session() as db:
        assert db.scalar(select(func.count()).select_from(Design)) == 1
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 1


def test_prompt_root_candidate_promotes_into_the_same_trusted_spec_path(
    creative_client,
):
    client, Session = creative_client
    app.dependency_overrides[get_creative_prompt_generator] = (
        lambda: (lambda _instruction, variant: _prompt_creative_result(variant)))
    created = client.post(
        "/projects/from-prompt", json=_prompt_request(variation_count=2))
    assert created.status_code == 201, created.text
    body = created.json()
    selected_id = body["root_id"]
    assert selected_id == body["revisions"][0]["asset_id"]

    promoted = client.post(
        f"/projects/{body['root_id']}/creative-candidates/{selected_id}/promote",
        json={
            "created_by": "usr_designer",
            "spec": audited_import_spec(EXAMPLE_SPEC),
        },
    )
    assert promoted.status_code == 200, promoted.text
    result = promoted.json()
    assert result["latest_design_version"] == 1
    assert result["active_revision"]["capability"] == "IMPORTED_REFERENCE"
    assert result["active_revision"]["parent_asset_id"] == selected_id
    assert result["factory_ready"] is False

    with Session() as db:
        assert db.scalar(select(func.count()).select_from(Design)) == 1
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 1


def test_hard_quality_failure_leaves_no_product_records(creative_client):
    client, Session = creative_client
    plan = build_image_plan(
        ImageOperation.REFERENCE_RENDER,
        "render faithfully",
        source_image=SOURCE,
        variant=7,
    )
    report = ImageQualityReport(
        verdict=QualityVerdict.FAIL,
        checks=(QualityCheck(
            code="source_design_preserved",
            passed=False,
            severity=CheckSeverity.HARD,
            message="major source drift",
        ),),
        score=30,
    )

    def fail(*_args):
        raise ImageQualityFailure(
            "candidate failed source fidelity",
            report=report,
            attempts=[],
            plan=plan,
        )

    app.dependency_overrides[get_creative_render_generator] = lambda: fail
    response = client.post("/projects/from-drawing", json=_request())
    assert response.status_code == 422
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(Project)) == 0
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 0
        assert db.scalar(select(func.count()).select_from(Design)) == 0
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 0
        assert db.scalar(select(func.count()).select_from(ImageRun)) == 1


def test_variation_count_is_explicitly_bounded(creative_client):
    client, _Session = creative_client
    assert client.post(
        "/projects/from-drawing", json=_request(variation_count=0)
    ).status_code == 422
    assert client.post(
        "/projects/from-drawing", json=_request(variation_count=5)
    ).status_code == 422

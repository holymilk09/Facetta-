"""Input-agnostic creative projects stay useful without becoming factory truth."""

from __future__ import annotations

import base64
import copy
import hashlib
import io
from datetime import timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, func, select, update
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
    DesignVersion,
    ImageAsset,
    ImageAttempt,
    ImageRun,
    Project,
    ProjectRevisionRecord,
    RevisionComponentMapRecord,
    StudioCreateDecisionRecord,
    StudioConfirmationDraft,
    StudioJobRecord,
    get_db,
    utcnow,
)
from facetta.design_form import NormalizedPoint, NormalizedPolygon
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
from facetta.image_identity import spec_visual_hash
from facetta.main import app
from facetta.project_backbone import (
    CreativeCandidateInput,
    claim_creative_project_design,
    persist_prompt_creative_project,
)
from facetta.revision_component_map import (
    RevisionComponent,
    RevisionComponentMap,
    polygon_hash,
)
from facetta.revision_component_map_store import add_revision_component_map
from facetta.spec import Spec


def _png(color: tuple[int, int, int]) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (96, 96), color).save(out, format="PNG")
    return out.getvalue()


SOURCE = _png((245, 245, 245))


_RING_COMPONENTS = (
    ("center", "center_stone"),
    ("prongs", "prongs"),
    ("setting", "setting"),
    ("shank", "shank"),
    ("shoulders", "shoulders"),
    ("gallery", "gallery"),
    ("metal", "metal_zone"),
    ("background", "background"),
)


def _exact_component_map(asset_id: str, image: bytes) -> RevisionComponentMap:
    components = []
    for index, (component_id, kind) in enumerate(_RING_COMPONENTS):
        offset = min(index, 5) * 0.02
        polygons = (NormalizedPolygon(points=(
            NormalizedPoint(x=0.1 + offset, y=0.1 + offset),
            NormalizedPoint(x=0.4 + offset, y=0.1 + offset),
            NormalizedPoint(x=0.4 + offset, y=0.4 + offset),
            NormalizedPoint(x=0.1 + offset, y=0.4 + offset),
        )),)
        components.append(RevisionComponent(
            component_id=component_id,
            kind=kind,
            label=component_id.title(),
            resolution="resolved",
            polygons=polygons,
            polygon_sha256=polygon_hash(polygons),
        ))
    with Image.open(io.BytesIO(image)) as raster:
        width, height = raster.size
    return RevisionComponentMap(
        asset_id=asset_id,
        asset_sha256=hashlib.sha256(image).hexdigest(),
        raster_width=width,
        raster_height=height,
        jewelry_type="ring",
        mapper_contract="test.calibrated-candidate-map.v1",
        components=tuple(components),
    )


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


def _reviewing_create_job(
    client: TestClient,
    *,
    project_id: str,
    requested_outputs: int,
    owner: str = "usr_designer",
) -> str:
    created = client.post("/studio/jobs", json={
        "owner": owner,
        "action_id": "create",
        "lane": "fast_visual",
        "requested_outputs": requested_outputs,
        "credits_per_output": 15,
    })
    assert created.status_code == 201, created.text
    job_id = created.json()["job_id"]
    running = client.patch(f"/studio/jobs/{job_id}", json={
        "owner": owner,
        "status": "running",
        "progress": 0.05,
    })
    assert running.status_code == 200, running.text
    reviewing = client.patch(f"/studio/jobs/{job_id}", json={
        "owner": owner,
        "status": "reviewing",
        "progress": 0.9,
        "active_design_id": project_id,
    })
    assert reviewing.status_code == 200, reviewing.text
    return job_id


def _running_create_job(
    client: TestClient,
    *,
    requested_outputs: int,
    owner: str = "usr_designer",
) -> str:
    created = client.post("/studio/jobs", json={
        "owner": owner,
        "action_id": "create",
        "lane": "fast_visual",
        "requested_outputs": requested_outputs,
        "credits_per_output": 15,
    })
    assert created.status_code == 201, created.text
    job_id = created.json()["job_id"]
    running = client.patch(f"/studio/jobs/{job_id}", json={
        "owner": owner,
        "status": "running",
        "progress": 0.05,
    })
    assert running.status_code == 200, running.text
    return job_id


def _promotion_payload(
    client: TestClient,
    project_id: str,
    candidate_id: str,
    spec: dict,
) -> dict[str, object]:
    with patch(
        "facetta.api.projects.from_photo",
        return_value=Spec.model_validate(spec),
    ):
        confirmation = client.post(
            f"/projects/{project_id}/creative-candidates/{candidate_id}/"
            "confirm-design",
            json={"created_by": "usr_designer"},
        )
    assert confirmation.status_code == 200, confirmation.text
    body = confirmation.json()
    assert "continuation_spec" not in body
    return {
        "created_by": "usr_designer",
        "confirmation_token": body["confirmation_token"],
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


def test_production_create_requires_valid_job_before_provider_cost(
    creative_client,
    monkeypatch,
):
    client, Session = creative_client
    prompt_calls: list[int] = []
    drawing_calls: list[int] = []

    def prompt_generate(_instruction: str, variant: int):
        prompt_calls.append(variant)
        return _prompt_creative_result(variant)

    def drawing_generate(_source: bytes, _instruction: str, variant: int):
        drawing_calls.append(variant)
        return _creative_result(variant)

    app.dependency_overrides[get_creative_prompt_generator] = (
        lambda: prompt_generate
    )
    app.dependency_overrides[get_creative_render_generator] = (
        lambda: drawing_generate
    )
    monkeypatch.setenv("FACETTA_ENV", "production")

    missing_prompt = client.post(
        "/projects/from-prompt", json=_prompt_request(variation_count=1),
    )
    missing_drawing = client.post(
        "/projects/from-drawing", json=_request(variation_count=1),
    )
    assert missing_prompt.status_code == 422
    assert missing_prompt.json()["code"] == "studio_job_required"
    assert missing_drawing.status_code == 422
    assert missing_drawing.json()["code"] == "studio_job_required"
    assert prompt_calls == []
    assert drawing_calls == []

    wrong_count_job = _running_create_job(client, requested_outputs=2)
    wrong_count = client.post("/projects/from-prompt", json={
        **_prompt_request(variation_count=1),
        "studio_job_id": wrong_count_job,
    })
    assert wrong_count.status_code == 422
    assert wrong_count.json()["code"] == "studio_job_invalid"
    assert prompt_calls == []

    valid_job = _running_create_job(client, requested_outputs=1)
    created = client.post("/projects/from-prompt", json={
        **_prompt_request(variation_count=1),
        "studio_job_id": valid_job,
    })
    assert created.status_code == 201, created.text
    assert prompt_calls == [4]
    project_id = created.json()["root_id"]
    with Session() as db:
        durable_job = db.get(StudioJobRecord, valid_job)
        durable_project = db.get(Project, project_id)
        assert durable_job is not None
        assert durable_project is not None
        # The provider authorization and project become durable together. The
        # client may later report reviewing, but replay prevention does not
        # depend on that second request.
        assert durable_job.active_design_id == durable_project.root_id
        assert durable_job.status == "running"

    replay = client.post("/projects/from-prompt", json={
        **_prompt_request(variation_count=1),
        "studio_job_id": valid_job,
    })
    assert replay.status_code == 409
    assert replay.json()["code"] == "studio_job_terminal"
    assert prompt_calls == [4]

    drawing_job = _running_create_job(client, requested_outputs=1)
    drawing = client.post("/projects/from-drawing", json={
        **_request(variation_count=1),
        "studio_job_id": drawing_job,
    })
    assert drawing.status_code == 201, drawing.text
    assert len(drawing_calls) == 1
    with Session() as db:
        durable_drawing_job = db.get(StudioJobRecord, drawing_job)
        assert durable_drawing_job is not None
        assert durable_drawing_job.active_design_id == drawing.json()["root_id"]

    drawing_replay = client.post("/projects/from-drawing", json={
        **_request(variation_count=1),
        "studio_job_id": drawing_job,
    })
    assert drawing_replay.status_code == 409
    assert drawing_replay.json()["code"] == "studio_job_terminal"
    assert len(drawing_calls) == 1


def test_create_job_binding_rolls_back_with_project_persistence(
    creative_client,
    monkeypatch,
):
    client, Session = creative_client
    job_id = _running_create_job(client, requested_outputs=1)
    generated = _prompt_creative_result(4)

    def fail_run_persistence(*_args, **_kwargs):
        raise RuntimeError("simulated image-run persistence failure")

    monkeypatch.setattr(
        "facetta.image_run_store.persist_image_agent_result",
        fail_run_persistence,
    )
    with Session() as db:
        job = db.get(StudioJobRecord, job_id)
        assert job is not None and job.active_design_id is None
        with pytest.raises(RuntimeError, match="simulated image-run"):
            persist_prompt_creative_project(
                db,
                candidates=(CreativeCandidateInput(
                    image=generated.image_bytes,
                    instruction="Sapphire orbit",
                    image_run=generated,
                ),),
                owner="usr_designer",
                title="Atomic Create",
                studio_job=job,
            )

    with Session() as db:
        durable_job = db.get(StudioJobRecord, job_id)
        assert durable_job is not None
        assert durable_job.active_design_id is None
        assert db.scalar(select(func.count()).select_from(Project)) == 0


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
    assert body["confirmable_pre_spec"] is False
    assert body["revisions"] == []
    assert len(body["creative_candidates"]) == 3
    assert all(item["capability"] == "CREATIVE_RENDER"
               for item in body["creative_candidates"])
    assert all(item["provenance"] == "pre_spec_creative_candidate"
               for item in body["creative_candidates"])
    assert not any(item["capability"] == "CREATIVE_SOURCE"
                   for item in body["assets"])
    assert body["root_id"] == body["creative_candidates"][0]["asset_id"]
    selected_id = body["creative_candidates"][1]["asset_id"]
    selected = client.post(
        f"/projects/{body['root_id']}/creative-candidates/{selected_id}/select",
        json={"created_by": "usr_designer"},
    )
    assert selected.status_code == 200, selected.text
    selected_body = selected.json()
    assert selected_body["selected_candidate_asset_id"] == selected_id
    assert selected_body["active_asset_id"] == selected_id
    assert selected_body["confirmable_pre_spec"] is True
    assert selected_body["cover_asset_id"] == selected_id
    assert "spec" not in selected_body

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
            "CREATIVE_GENERATE", "CREATIVE_GENERATE", "CREATIVE_GENERATE"]
        assert [run.variant for run in runs] == [4, 5, 6]
        assert all(run.source_asset_id is None for run in runs)


def test_creative_selection_atomically_settles_reviewing_create_job_after_restart(
    creative_client,
):
    client, Session = creative_client
    app.dependency_overrides[get_creative_prompt_generator] = (
        lambda: (lambda _instruction, variant: _prompt_creative_result(variant))
    )
    created = client.post(
        "/projects/from-prompt", json=_prompt_request(variation_count=3)
    )
    assert created.status_code == 201, created.text
    project = created.json()
    selected_id = project["creative_candidates"][1]["asset_id"]
    job_id = _reviewing_create_job(
        client,
        project_id=project["root_id"],
        requested_outputs=4,
    )

    # A new HTTP client has no gateway-local Create map. Settlement depends
    # only on durable project, candidate, and StudioJob rows.
    with TestClient(app) as restarted_client:
        selected = restarted_client.post(
            f"/projects/{project['root_id']}/creative-candidates/"
            f"{selected_id}/select",
            json={"created_by": "usr_designer", "studio_job_id": job_id},
        )
        assert selected.status_code == 200, selected.text
        assert selected.json()["selected_candidate_asset_id"] == selected_id

        # Identical retries are idempotent and cannot double-charge.
        retried = restarted_client.post(
            f"/projects/{project['root_id']}/creative-candidates/"
            f"{selected_id}/select",
            json={"created_by": "usr_designer", "studio_job_id": job_id},
        )
        assert retried.status_code == 200, retried.text

    with Session() as db:
        saved = db.get(Project, project["root_id"])
        job = db.get(StudioJobRecord, job_id)
        assert saved is not None
        assert saved.selected_candidate_asset_id == selected_id
        assert job is not None
        assert job.status == "succeeded"
        assert job.active_design_id == project["root_id"]
        assert job.source_revision_id == selected_id
        # Only three persisted usable directions exist, despite four requested.
        assert job.completed_outputs == 3
        assert job.charged_outputs == 3


def test_creative_selection_job_cas_rejects_stale_project_and_prior_selection(
    creative_client,
):
    client, Session = creative_client
    app.dependency_overrides[get_creative_prompt_generator] = (
        lambda: (lambda _instruction, variant: _prompt_creative_result(variant))
    )
    first = client.post(
        "/projects/from-prompt", json=_prompt_request(variation_count=2)
    ).json()
    second_request = _prompt_request(variation_count=2)
    second_request["title"] = "Second exploration"
    second_request["starting_variant"] = 20
    second = client.post("/projects/from-prompt", json=second_request).json()
    first_job_id = _reviewing_create_job(
        client, project_id=first["root_id"], requested_outputs=2,
    )
    second_candidate = second["creative_candidates"][1]["asset_id"]

    wrong_project = client.post(
        f"/projects/{second['root_id']}/creative-candidates/"
        f"{second_candidate}/select",
        json={"created_by": "usr_designer", "studio_job_id": first_job_id},
    )
    assert wrong_project.status_code == 409
    assert "not bound to the selected project" in wrong_project.json()["detail"]

    first_candidates = [item["asset_id"] for item in first["creative_candidates"]]
    legacy_selection = client.post(
        f"/projects/{first['root_id']}/creative-candidates/"
        f"{first_candidates[0]}/select",
        json={"created_by": "usr_designer"},
    )
    assert legacy_selection.status_code == 200, legacy_selection.text
    stale_selection = client.post(
        f"/projects/{first['root_id']}/creative-candidates/"
        f"{first_candidates[1]}/select",
        json={"created_by": "usr_designer", "studio_job_id": first_job_id},
    )
    assert stale_selection.status_code == 409
    assert "already selected another" in stale_selection.json()["detail"]

    with Session() as db:
        first_project = db.get(Project, first["root_id"])
        second_project = db.get(Project, second["root_id"])
        job = db.get(StudioJobRecord, first_job_id)
        assert first_project is not None
        assert first_project.selected_candidate_asset_id == first_candidates[0]
        assert second_project is not None
        assert second_project.selected_candidate_asset_id is None
        assert job is not None
        assert job.status == "reviewing"
        assert job.source_revision_id is None
        assert job.completed_outputs == 0
        assert job.charged_outputs == 0


def test_creative_selection_rejects_wrong_job_source_without_partial_writes(
    creative_client,
):
    client, Session = creative_client
    app.dependency_overrides[get_creative_prompt_generator] = (
        lambda: (lambda _instruction, variant: _prompt_creative_result(variant))
    )
    created = client.post(
        "/projects/from-prompt", json=_prompt_request(variation_count=2)
    ).json()
    candidate_ids = [item["asset_id"] for item in created["creative_candidates"]]
    job_id = _reviewing_create_job(
        client, project_id=created["root_id"], requested_outputs=2,
    )
    bound = client.patch(f"/studio/jobs/{job_id}", json={
        "owner": "usr_designer",
        "status": "succeeded",
        "progress": 1,
        "completed_outputs": 2,
        "source_revision_id": candidate_ids[0],
    })
    assert bound.status_code == 200, bound.text

    response = client.post(
        f"/projects/{created['root_id']}/creative-candidates/"
        f"{candidate_ids[1]}/select",
        json={"created_by": "usr_designer", "studio_job_id": job_id},
    )
    assert response.status_code == 409
    assert "another selected direction" in response.json()["detail"]

    with Session() as db:
        project = db.get(Project, created["root_id"])
        job = db.get(StudioJobRecord, job_id)
        assert project is not None
        assert project.selected_candidate_asset_id is None
        assert job is not None
        assert job.source_revision_id == candidate_ids[0]
        # Public lifecycle transitions never create a charge.
        assert job.charged_outputs == 0


def test_creative_selection_rejects_foreign_create_job_without_partial_writes(
    creative_client,
):
    client, Session = creative_client
    app.dependency_overrides[get_creative_prompt_generator] = (
        lambda: (lambda _instruction, variant: _prompt_creative_result(variant))
    )
    created = client.post(
        "/projects/from-prompt", json=_prompt_request(variation_count=1)
    ).json()
    candidate_id = created["creative_candidates"][0]["asset_id"]
    foreign_job_id = _reviewing_create_job(
        client,
        project_id=created["root_id"],
        requested_outputs=1,
        owner="usr_other",
    )

    response = client.post(
        f"/projects/{created['root_id']}/creative-candidates/"
        f"{candidate_id}/select",
        json={
            "created_by": "usr_designer",
            "studio_job_id": foreign_job_id,
        },
    )
    assert response.status_code == 409
    assert "unknown Studio job" in response.json()["detail"]

    with Session() as db:
        project = db.get(Project, created["root_id"])
        job = db.get(StudioJobRecord, foreign_job_id)
        assert project is not None
        assert project.selected_candidate_asset_id is None
        assert job is not None
        assert job.owner == "usr_other"
        assert job.status == "reviewing"
        assert job.completed_outputs == 0
        assert job.charged_outputs == 0


def test_creative_direction_commit_is_atomic_billed_once_and_retry_safe(
    creative_client,
):
    client, Session = creative_client
    # Match the production get_db session. Without autoflush, the second
    # ensure_project_family call must still reuse the pending family created by
    # the atomic command rather than treating it as missing.
    Session.configure(autoflush=False)
    app.dependency_overrides[get_creative_prompt_generator] = (
        lambda: (lambda _instruction, variant: _prompt_creative_result(variant))
    )
    created = client.post(
        "/projects/from-prompt", json=_prompt_request(variation_count=4)
    )
    assert created.status_code == 201, created.text
    project = created.json()
    candidates = [
        item["asset_id"] for item in project["creative_candidates"]
    ]
    job_id = _reviewing_create_job(
        client, project_id=project["root_id"], requested_outputs=4,
    )
    payload = {
        "selected_candidate_id": candidates[1],
        "retained": [
            {"candidate_id": candidates[0], "label": "Botanical frame"},
            {"candidate_id": candidates[3], "label": "Open silhouette"},
        ],
        "created_by": "usr_designer",
        "studio_job_id": job_id,
    }

    committed = client.post(
        f"/projects/{project['root_id']}/creative-directions/commit",
        json=payload,
    )
    assert committed.status_code == 200, committed.text
    body = committed.json()
    assert body["project"]["selected_candidate_asset_id"] == candidates[1]
    assert [item["source_asset_id"] for item in body["retained_variations"]] == [
        candidates[0], candidates[3]
    ]
    assert [
        item["variation_index"] for item in body["retained_variations"]
    ] == [2, 3]
    branch_ids = [
        item["project"]["root_id"] for item in body["retained_variations"]
    ]
    assert len(set(branch_ids)) == 2

    # An exact retry returns the same durable branch identities and cannot
    # create or charge anything twice.
    retried = client.post(
        f"/projects/{project['root_id']}/creative-directions/commit",
        json=payload,
    )
    assert retried.status_code == 200, retried.text
    assert [
        item["project"]["root_id"]
        for item in retried.json()["retained_variations"]
    ] == branch_ids

    # Once one complete decision wins, a competing payload cannot fill in an
    # extra branch or rename evidence after a timeout/race.
    mismatched = copy.deepcopy(payload)
    mismatched["retained"][0]["label"] = "Changed after commit"
    rejected = client.post(
        f"/projects/{project['root_id']}/creative-directions/commit",
        json=mismatched,
    )
    assert rejected.status_code == 409
    assert "already committed" in rejected.json()["detail"]

    with Session() as db:
        original = db.get(Project, project["root_id"])
        decision = db.get(StudioCreateDecisionRecord, project["root_id"])
        job = db.get(StudioJobRecord, job_id)
        branches = list(db.scalars(select(Project).where(
            Project.branched_from_project_root_id == project["root_id"]
        ).order_by(Project.variation_index)))
        assert original is not None
        assert original.selected_candidate_asset_id == candidates[1]
        assert original.variation_index == 1
        assert decision is not None
        assert decision.selected_candidate_asset_id == candidates[1]
        assert [
            item["project_root_id"] for item in decision.retained_directions
        ] == branch_ids
        assert [branch.root_id for branch in branches] == branch_ids
        assert [branch.branched_from_asset_id for branch in branches] == [
            candidates[0], candidates[3]
        ]
        assert job is not None
        assert job.status == "succeeded"
        assert job.completed_outputs == 4
        assert job.charged_outputs == 4
        assert db.scalar(select(func.count()).select_from(Project)) == 3
        assert db.scalar(
            select(func.count()).select_from(ProjectRevisionRecord)
        ) == 3
        revision_records = list(db.scalars(
            select(ProjectRevisionRecord).order_by(ProjectRevisionRecord.id)
        ))
        original_revision = next(
            record for record in revision_records
            if record.asset_id == candidates[1]
        )
        selected_asset = db.get(ImageAsset, candidates[1])
        selected_run = db.get(
            ImageRun, original_revision.raw_intent["image_run_id"]
        )
        assert selected_asset is not None
        assert selected_run is not None
        selected_sha256 = hashlib.sha256(
            bytes(selected_asset.image)
        ).hexdigest()
        assert original_revision.action == "created"
        assert original_revision.raw_intent == {
            "kind": "create_direction_commit",
            "create_decision_project_root_id": project["root_id"],
            "selected_candidate_asset_id": candidates[1],
            "source_asset_id": candidates[1],
            "image_run_id": selected_run.id,
            "studio_job_id": job_id,
        }
        assert original_revision.interpretation == {
            "operation": "select_original_direction",
            "source_sha256": selected_sha256,
            "output_sha256": selected_sha256,
            "generation_operation": "CREATIVE_GENERATE",
            "generation_input_sha256": selected_run.input_hash,
            "generation_prompt_version": selected_run.prompt_version,
            "generation_status": "review_required",
            "specification_created": False,
            "factory_authority": False,
            "source_asset_id": candidates[1],
        }
        matching_attempt = db.scalar(select(ImageAttempt).where(
            ImageAttempt.run_id == selected_run.id,
            ImageAttempt.output_hash == selected_sha256,
        ))
        assert matching_attempt is not None
        original_revision_id = original_revision.id

    history = client.get(f"/studio/projects/{project['root_id']}/history")
    assert history.status_code == 200, history.text
    stored_original = next(
        revision for revision in history.json()["revisions"]
        if revision["asset_id"] == candidates[1]
    )
    assert stored_original["raw_intent"]["kind"] == "create_direction_commit"
    assert stored_original["raw_intent"]["image_run_id"] == selected_run.id
    assert stored_original["interpretation"]["source_sha256"] == selected_sha256
    assert stored_original["interpretation"]["output_sha256"] == selected_sha256
    assert all(
        revision["raw_intent"].get("kind") != "legacy_or_pre_studio"
        for revision in history.json()["revisions"]
        if revision["asset_id"] == candidates[1]
    )

    with Session() as db:
        persisted = db.get(ProjectRevisionRecord, original_revision_id)
        assert persisted is not None
        assert db.scalar(
            select(func.count()).select_from(ProjectRevisionRecord)
        ) == 3


@pytest.mark.parametrize("evidence_state", ["missing", "ambiguous"])
def test_creative_direction_commit_fails_closed_without_exact_generation_evidence(
    creative_client,
    evidence_state: str,
):
    client, Session = creative_client
    app.dependency_overrides[get_creative_prompt_generator] = (
        lambda: (lambda _instruction, variant: _prompt_creative_result(variant))
    )
    created = client.post(
        "/projects/from-prompt", json=_prompt_request(variation_count=2)
    )
    assert created.status_code == 201, created.text
    project = created.json()
    candidates = [
        item["asset_id"] for item in project["creative_candidates"]
    ]
    selected_id = candidates[1]

    with Session() as db:
        selected_asset = db.get(ImageAsset, selected_id)
        assert selected_asset is not None
        selected_sha256 = hashlib.sha256(
            bytes(selected_asset.image)
        ).hexdigest()
        selected_run = db.scalar(
            select(ImageRun)
            .join(ImageAttempt, ImageAttempt.run_id == ImageRun.id)
            .where(
                ImageRun.project_root_id == project["root_id"],
                ImageAttempt.output_hash == selected_sha256,
            )
        )
        assert selected_run is not None
        if evidence_state == "missing":
            db.execute(
                update(ImageAttempt)
                .where(
                    ImageAttempt.run_id == selected_run.id,
                    ImageAttempt.output_hash == selected_sha256,
                )
                .values(output_hash="0" * 64)
            )
        else:
            duplicate_run = ImageRun(
                id="run_ambiguous_candidate",
                project_root_id=selected_run.project_root_id,
                source_asset_id=selected_run.source_asset_id,
                operation=selected_run.operation,
                normalized_intent=dict(selected_run.normalized_intent),
                prompt_version=selected_run.prompt_version,
                input_hash=selected_run.input_hash,
                source_hash=selected_run.source_hash,
                mask_hash=selected_run.mask_hash,
                spec_visual_hash=selected_run.spec_visual_hash,
                source_spec_visual_hash=selected_run.source_spec_visual_hash,
                variant=selected_run.variant,
                status=selected_run.status,
                accepted_asset_id=None,
                error_category=selected_run.error_category,
                created_by=selected_run.created_by,
                created_at=utcnow(),
            )
            db.add_all([
                duplicate_run,
                ImageAttempt(
                    id="iat_ambiguous_candidate",
                    run_id=duplicate_run.id,
                    attempt_number=1,
                    provider="fixture",
                    model="fixture",
                    cached=False,
                    qa_verdict="warn",
                    qa_checks=[],
                    output_hash=selected_sha256,
                    usage={},
                    created_at=utcnow(),
                ),
            ])
        db.commit()

    job_id = _reviewing_create_job(
        client, project_id=project["root_id"], requested_outputs=2,
    )
    response = client.post(
        f"/projects/{project['root_id']}/creative-directions/commit",
        json={
            "selected_candidate_id": selected_id,
            "retained": [{
                "candidate_id": candidates[0],
                "label": "Sibling direction",
            }],
            "created_by": "usr_designer",
            "studio_job_id": job_id,
        },
    )
    assert response.status_code == 409
    assert "missing or ambiguous generation provenance" in response.json()[
        "detail"
    ]

    with Session() as db:
        stored_project = db.get(Project, project["root_id"])
        job = db.get(StudioJobRecord, job_id)
        assert stored_project is not None
        assert stored_project.selected_candidate_asset_id is None
        assert stored_project.family_id is None
        assert db.get(
            StudioCreateDecisionRecord, project["root_id"]
        ) is None
        assert db.scalar(select(func.count()).select_from(Project).where(
            Project.branched_from_project_root_id == project["root_id"]
        )) == 0
        assert db.scalar(
            select(func.count()).select_from(ProjectRevisionRecord)
        ) == 0
        assert job is not None
        assert job.status == "reviewing"
        assert job.source_revision_id is None
        assert job.completed_outputs == 0
        assert job.charged_outputs == 0


def test_creative_direction_commit_binds_original_to_uploaded_source_lineage(
    creative_client,
):
    client, Session = creative_client
    app.dependency_overrides[get_creative_render_generator] = lambda: (
        lambda _source, _instruction, variant: _creative_result(variant)
    )
    created = client.post(
        "/projects/from-drawing", json=_request(variation_count=1)
    )
    assert created.status_code == 201, created.text
    project = created.json()
    candidate_id = project["creative_candidates"][0]["asset_id"]
    job_id = _reviewing_create_job(
        client, project_id=project["root_id"], requested_outputs=1,
    )

    committed = client.post(
        f"/projects/{project['root_id']}/creative-directions/commit",
        json={
            "selected_candidate_id": candidate_id,
            "retained": [],
            "created_by": "usr_designer",
            "studio_job_id": job_id,
        },
    )
    assert committed.status_code == 200, committed.text

    with Session() as db:
        record = db.scalar(select(ProjectRevisionRecord).where(
            ProjectRevisionRecord.asset_id == candidate_id
        ))
        assert record is not None
        run = db.get(ImageRun, record.raw_intent["image_run_id"])
        assert run is not None
        assert run.source_asset_id == project["root_id"]
        assert record.raw_intent["source_asset_id"] == project["root_id"]
        assert record.interpretation["source_asset_id"] == project["root_id"]
        assert record.interpretation["source_sha256"] == hashlib.sha256(
            SOURCE
        ).hexdigest()
        assert record.interpretation["generation_operation"] == (
            "REFERENCE_RENDER"
        )
        assert record.interpretation["generation_input_sha256"] == (
            run.input_hash
        )


def test_creative_direction_commit_rolls_back_invalid_retained_candidate(
    creative_client,
):
    client, Session = creative_client
    app.dependency_overrides[get_creative_prompt_generator] = (
        lambda: (lambda _instruction, variant: _prompt_creative_result(variant))
    )
    first = client.post(
        "/projects/from-prompt", json=_prompt_request(variation_count=3)
    ).json()
    other_request = _prompt_request(variation_count=1)
    other_request["title"] = "Foreign exploration"
    other_request["starting_variant"] = 30
    other = client.post("/projects/from-prompt", json=other_request).json()
    first_candidates = [
        item["asset_id"] for item in first["creative_candidates"]
    ]
    foreign_candidate = other["creative_candidates"][0]["asset_id"]
    job_id = _reviewing_create_job(
        client, project_id=first["root_id"], requested_outputs=3,
    )

    response = client.post(
        f"/projects/{first['root_id']}/creative-directions/commit",
        json={
            "selected_candidate_id": first_candidates[1],
            "retained": [
                {"candidate_id": first_candidates[0], "label": "Valid first"},
                {"candidate_id": foreign_candidate, "label": "Wrong project"},
            ],
            "created_by": "usr_designer",
            "studio_job_id": job_id,
        },
    )
    assert response.status_code == 409
    assert "from this project" in response.json()["detail"]

    with Session() as db:
        project = db.get(Project, first["root_id"])
        job = db.get(StudioJobRecord, job_id)
        assert project is not None
        assert project.selected_candidate_asset_id is None
        assert project.family_id is None
        assert db.get(StudioCreateDecisionRecord, first["root_id"]) is None
        assert db.scalar(select(func.count()).select_from(Project).where(
            Project.branched_from_project_root_id == first["root_id"]
        )) == 0
        assert db.scalar(
            select(func.count()).select_from(ProjectRevisionRecord)
        ) == 0
        assert job is not None
        assert job.status == "reviewing"
        assert job.source_revision_id is None
        assert job.completed_outputs == 0
        assert job.charged_outputs == 0


def test_creative_direction_commit_rejects_partial_legacy_state(
    creative_client,
):
    client, Session = creative_client
    app.dependency_overrides[get_creative_prompt_generator] = (
        lambda: (lambda _instruction, variant: _prompt_creative_result(variant))
    )
    created = client.post(
        "/projects/from-prompt", json=_prompt_request(variation_count=2)
    ).json()
    candidates = [
        item["asset_id"] for item in created["creative_candidates"]
    ]
    legacy = client.post(
        f"/projects/{created['root_id']}/creative-candidates/"
        f"{candidates[0]}/select",
        json={"created_by": "usr_designer"},
    )
    assert legacy.status_code == 200, legacy.text

    response = client.post(
        f"/projects/{created['root_id']}/creative-directions/commit",
        json={
            "selected_candidate_id": candidates[0],
            "retained": [
                {"candidate_id": candidates[1], "label": "Late sibling"},
            ],
            "created_by": "usr_designer",
        },
    )
    assert response.status_code == 409
    assert "partial legacy Create selection" in response.json()["detail"]
    with Session() as db:
        assert db.get(StudioCreateDecisionRecord, created["root_id"]) is None
        assert db.scalar(select(func.count()).select_from(Project)) == 1


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
    assert [item["capability"] for item in body["creative_candidates"]] == [
        "CREATIVE_RENDER", "CREATIVE_RENDER"]
    assert all("design_version" not in item for item in body["creative_candidates"])
    assert body["assets"][0]["capability"] == "CREATIVE_SOURCE"
    # Compatibility payload omitted source_kind; the drawing-named route uses
    # its documented legacy fallback without pixel inference.
    assert body["assets"][0]["source_kind"] == "drawing"
    assert body["assets"][0]["provenance"] == "designer_supplied_drawing"
    assert all(
        item["source_kind"] == "drawing"
        for item in body["creative_candidates"]
    )
    assert len(body["image_run_ids"]) == 2

    with Session() as db:
        saved_project = db.get(Project, body["root_id"])
        assert saved_project is not None
        assert saved_project.family_id is None
        assert saved_project.variation_index is None
        assert saved_project.variation_label is None
        assert db.scalar(select(func.count()).select_from(Project)) == 1
        assert db.scalar(select(func.count()).select_from(Design)) == 0
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 0
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 3
        runs = list(db.scalars(select(ImageRun).order_by(ImageRun.variant)))
        assert [run.operation for run in runs] == [
            "REFERENCE_RENDER", "REFERENCE_RENDER"]
        assert [run.variant for run in runs] == [7, 8]
        assert all(run.status == "review_required" for run in runs)


@pytest.mark.parametrize(
    ("source_kind", "expected_provenance"),
    [
        ("photograph", "designer_supplied_photograph"),
        ("finished_render", "designer_supplied_finished_render"),
    ],
)
def test_from_drawing_preserves_explicit_source_semantics_in_reopened_history(
    creative_client, source_kind: str, expected_provenance: str,
):
    client, _Session = creative_client
    app.dependency_overrides[get_creative_render_generator] = lambda: (
        lambda _source, _instruction, variant: _creative_result(variant)
    )

    created = client.post("/projects/from-drawing", json={
        **_request(variation_count=1),
        "source_kind": source_kind,
    })
    assert created.status_code == 201, created.text
    root_id = created.json()["root_id"]
    reopened = client.get(f"/projects/{root_id}")
    assert reopened.status_code == 200, reopened.text
    body = reopened.json()
    source = next(
        item for item in body["assets"]
        if item["capability"] == "CREATIVE_SOURCE"
    )
    assert source["source_kind"] == source_kind
    assert source["provenance"] == expected_provenance
    assert body["creative_candidates"][0]["source_kind"] == source_kind


def test_from_drawing_role_board_is_canonical_persisted_and_reopenable(
    creative_client,
):
    client, Session = creative_client
    material = _role_reference("material_style", (186, 138, 72))
    construction = _role_reference("construction_detail", (84, 102, 128))
    brand = _role_reference("brand_direction", (204, 184, 216))
    calls: list[tuple[bytes, bytes | None, str, int]] = []

    def generate(
        source: bytes,
        instruction: str,
        variant: int,
        *,
        quality_source_image: bytes | None = None,
    ):
        calls.append((source, quality_source_image, instruction, variant))
        plan = build_image_plan(
            ImageOperation.REFERENCE_RENDER,
            instruction,
            source_image=source,
            quality_source_image=quality_source_image,
            variant=variant,
        )

        class Provider:
            def execute(self, *_args, **_kwargs):
                return ProviderImage(image_bytes=_png((70 + variant, 61, 51)))

        class Evaluator:
            def evaluate(
                self, _plan, _candidate, *, source_image, mask_bytes,
            ):
                assert source_image == SOURCE
                assert mask_bytes is None
                return ImageQualityReport(
                    verdict=QualityVerdict.WARN,
                    checks=(),
                    score=94,
                )

        return JewelryImageAgent(Provider(), Evaluator()).run(
            plan,
            source_image=source,
            quality_source_image=quality_source_image,
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
    assert [call[3] for call in calls] == [7, 8, 9, 10]
    assert all(call[0] == calls[0][0] for call in calls)
    assert all(call[1] == SOURCE for call in calls)
    assert all(call[2] == calls[0][2] for call in calls)
    instruction = calls[0][2]
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

    assert body["revisions"] == []
    assert len(body["creative_candidates"]) == 4
    assets = {asset["capability"]: asset for asset in body["assets"]}
    assert assets["CREATIVE_SOURCE"]["provenance"] == (
        "designer_supplied_drawing"
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
        assert all(
            run.normalized_intent["quality_source"]["sha256"]
            == hashlib.sha256(SOURCE).hexdigest()
            for run in runs
        )


@pytest.mark.parametrize("variation_count", [1, 4])
def test_role_labeled_references_preserve_candidate_count_boundaries(
    creative_client,
    variation_count,
):
    client, _Session = creative_client
    variants: list[int] = []

    def generate(
        source: bytes,
        instruction: str,
        variant: int,
        *,
        quality_source_image: bytes | None = None,
    ):
        variants.append(variant)
        plan = build_image_plan(
            ImageOperation.REFERENCE_RENDER,
            instruction,
            source_image=source,
            quality_source_image=quality_source_image,
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
            plan,
            source_image=source,
            quality_source_image=quality_source_image,
        )

    app.dependency_overrides[get_creative_render_generator] = lambda: generate
    response = client.post("/projects/from-drawing", json={
        **_request(variation_count=variation_count),
        "references": [_role_reference(
            "material_style", (160, 120, 60)
        )],
    })
    assert response.status_code == 201, response.text
    assert len(response.json()["creative_candidates"]) == variation_count
    assert variants == list(range(7, 7 + variation_count))


def test_role_board_keeps_legacy_three_argument_generator_override_compatible(
    creative_client,
):
    client, _Session = creative_client
    calls: list[tuple[bytes, str, int]] = []

    def legacy_generate(source: bytes, instruction: str, variant: int):
        calls.append((source, instruction, variant))
        plan = build_image_plan(
            ImageOperation.REFERENCE_RENDER,
            instruction,
            source_image=source,
            variant=variant,
        )

        class Provider:
            def execute(self, *_args, **_kwargs):
                return ProviderImage(image_bytes=_png((81, 62, 43)))

        class Evaluator:
            def evaluate(self, *_args, **_kwargs):
                return ImageQualityReport(
                    verdict=QualityVerdict.WARN,
                    checks=(),
                    score=91,
                )

        return JewelryImageAgent(Provider(), Evaluator()).run(
            plan,
            source_image=source,
        )

    app.dependency_overrides[get_creative_render_generator] = (
        lambda: legacy_generate
    )
    response = client.post("/projects/from-drawing", json={
        **_request(variation_count=1),
        "references": [_role_reference(
            "material_style", (160, 120, 60)
        )],
    })

    assert response.status_code == 201, response.text
    assert len(calls) == 1
    assert calls[0][2] == 7
    assert "ROLE-LABELED REFERENCE BOARD" in calls[0][1]


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
    assert assets["CREATIVE_SOURCE"]["provenance"] == "designer_supplied_drawing"
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


def test_role_board_qa_uses_selected_master_crop_not_composite_board(
    creative_client,
):
    client, Session = creative_client
    expected_crop = crop_normalized_region(
        SOURCE, x=0.10, y=0.10, width=0.80, height=0.80,
    )
    observed: dict[str, bytes] = {}

    def generate(
        source: bytes,
        instruction: str,
        variant: int,
        *,
        quality_source_image: bytes | None = None,
    ):
        assert quality_source_image is not None
        observed["provider"] = source
        observed["quality"] = quality_source_image
        plan = build_image_plan(
            ImageOperation.REFERENCE_RENDER,
            instruction,
            source_image=source,
            quality_source_image=quality_source_image,
            variant=variant,
        )

        class Provider:
            def execute(self, *_args, source_image, **_kwargs):
                assert source_image == source
                return ProviderImage(image_bytes=_png((91, 72, 51)))

        class Evaluator:
            def evaluate(
                self, _plan, _candidate, *, source_image, mask_bytes,
            ):
                assert source_image == expected_crop
                assert mask_bytes is None
                return ImageQualityReport(
                    verdict=QualityVerdict.WARN,
                    checks=(),
                    score=93,
                )

        return JewelryImageAgent(Provider(), Evaluator()).run(
            plan,
            source_image=source,
            quality_source_image=quality_source_image,
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
        "references": [_role_reference(
            "material_style", (160, 120, 60)
        )],
    })

    assert response.status_code == 201, response.text
    assert observed["quality"] == expected_crop
    assert observed["provider"] != expected_crop
    with Session() as db:
        run = db.scalar(select(ImageRun))
        board = db.scalar(select(ImageAsset).where(
            ImageAsset.capability == "CREATIVE_REFERENCE_BOARD"
        ))
        assert run is not None
        assert board is not None
        assert run.source_hash == hashlib.sha256(bytes(board.image)).hexdigest()
        assert run.normalized_intent["quality_source"]["sha256"] == (
            hashlib.sha256(expected_crop).hexdigest()
        )


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

    def fail(
        source: bytes,
        instruction: str,
        variant: int,
        *,
        quality_source_image: bytes | None = None,
    ):
        assert b"PNG" in source[:16]
        assert quality_source_image == SOURCE
        assert "ROLE-LABELED REFERENCE BOARD" in instruction
        plan = build_image_plan(
            ImageOperation.REFERENCE_RENDER,
            instruction,
            source_image=source,
            quality_source_image=quality_source_image,
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
    candidate_id = created["creative_candidates"][0]["asset_id"]
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


def test_confirm_design_projects_typed_designer_facts_and_exact_hashes(
    creative_client, monkeypatch,
):
    client, Session = creative_client
    candidate_bytes = _png((87, 60, 30))
    app.dependency_overrides[get_creative_render_generator] = (
        lambda: (lambda _source, _instruction, selected: _creative_result(selected))
    )
    created = client.post(
        "/projects/from-drawing", json=_request(variation_count=1)
    ).json()
    candidate_id = created["creative_candidates"][0]["asset_id"]
    selected = client.post(
        f"/projects/{created['id']}/creative-candidates/{candidate_id}/select",
        json={"created_by": "usr_designer"},
    )
    assert selected.status_code == 200, selected.text
    raw = audited_import_spec(EXAMPLE_SPEC)
    raw["dimension_provenance"] = {
        "stone.dimensions_mm.length": {
            "status": "estimated_from_reference",
            "method": "reference_vision",
            "source": "selected visual",
            "confidence": 0.8,
        },
        "band.width_mm": {
            "status": "designer_confirmed",
            "method": "designer_input",
            "source": "designer confirmation",
        },
    }
    expected = Spec.model_validate(raw)
    monkeypatch.setattr("facetta.api.projects.from_photo", lambda _request: expected)

    response = client.post(
        f"/projects/{created['id']}/creative-candidates/{candidate_id}/"
        "confirm-design",
        json={
            "notes": "Keep the exact shoulder geometry.",
            "created_by": "usr_designer",
            "run_independent_audit": True,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["candidate_id"] == candidate_id
    assert body["candidate_sha256"] == hashlib.sha256(candidate_bytes).hexdigest()
    assert len(body["spec_visual_hash"]) == 16
    facts = {
        fact["key"]: fact
        for group in body["fact_groups"]
        for fact in group["facts"]
    }
    assert facts["length"]["authority"] == "estimated"
    assert facts["band_width"]["authority"] == "designer_supplied"
    assert facts["species"]["authority"] == "suggested"
    assert body["audit_eligibility"] == {
        "eligible": True,
        "state": "complete",
        "reason": (
            "The selected visual and confirmed facts have current evidence."
        ),
    }
    assert body["unresolved_source_questions"] == []
    assert "continuation_spec" not in body
    assert len(body["confirmation_token"]) >= 32
    assert body["expires_at"]
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(Design)) == 0
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 0
        assert db.scalar(select(func.count()).select_from(
            StudioConfirmationDraft)) == 1


def test_confirm_design_exposes_source_questions_without_internal_control_copy(
    creative_client, monkeypatch,
):
    client, Session = creative_client
    app.dependency_overrides[get_creative_render_generator] = (
        lambda: (lambda _source, _instruction, selected: _creative_result(selected))
    )
    created = client.post(
        "/projects/from-drawing", json=_request(variation_count=1)
    ).json()
    candidate_id = created["creative_candidates"][0]["asset_id"]
    assert client.post(
        f"/projects/{created['id']}/creative-candidates/{candidate_id}/select",
        json={"created_by": "usr_designer"},
    ).status_code == 200
    raw = audited_import_spec(EXAMPLE_SPEC)
    component = raw["source_component_coverage"]["components"][0]
    component["canonical_spec_paths"] = []
    component["unresolved_reason"] = "The lower gallery is hidden."
    component["independent_audit"] = None
    expected = Spec.model_validate(raw)
    monkeypatch.setattr("facetta.api.projects.from_photo", lambda _request: expected)

    response = client.post(
        f"/projects/{created['id']}/creative-candidates/{candidate_id}/"
        "confirm-design",
        json={"created_by": "usr_designer"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["audit_eligibility"]["eligible"] is False
    assert body["audit_eligibility"]["state"] == "not_ready"
    assert body["unresolved_source_questions"] == [
        "Confirm Complete synthetic jewelry assembly: "
        "The lower gallery is hidden."
    ]
    public_projection = {
        "fact_groups": body["fact_groups"],
        "unresolved_source_questions": body["unresolved_source_questions"],
        "audit_eligibility": body["audit_eligibility"],
    }
    projection_text = str(public_projection).lower()
    assert "provider" not in projection_text
    assert "factory" not in projection_text
    promotion = client.post(
        f"/projects/{created['id']}/creative-candidates/{candidate_id}/promote",
        json={
            "created_by": "usr_designer",
            "confirmation_token": body["confirmation_token"],
        },
    )
    assert promotion.status_code == 200, promotion.text
    promoted = promotion.json()
    blocker_codes = {
        blocker["code"] for blocker in promoted["factory_blockers"]
    }
    assert "source_component_unresolved" in blocker_codes
    assert promoted["factory_ready"] is False
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(Design)) == 1
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 1
    assert "qa" not in projection_text


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
    candidate_id = created["creative_candidates"][0]["asset_id"]
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
    candidate_id = created["creative_candidates"][0]["asset_id"]

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
    candidate_id = created["creative_candidates"][0]["asset_id"]
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


def test_alternate_drawing_candidate_confirmation_stays_current_after_promotion(
    creative_client,
):
    """Promotion must not re-anchor evidence to the unrelated drawing root."""
    client, Session = creative_client
    app.dependency_overrides[get_creative_render_generator] = (
        lambda: (lambda _source, _instruction, selected: _creative_result(selected)))
    created = client.post(
        "/projects/from-drawing", json=_request(variation_count=2))
    assert created.status_code == 201, created.text
    created_body = created.json()
    project_id = created_body["root_id"]
    selected_bytes = _png((88, 60, 30))
    with Session() as db:
        candidate_assets = list(db.scalars(select(ImageAsset).where(
            ImageAsset.root_id == project_id,
            ImageAsset.capability == "CREATIVE_RENDER",
        )))
        selected = next(
            asset for asset in candidate_assets
            if bytes(asset.image) == selected_bytes
        )
        selected_id = selected.id
        assert any(
            bytes(asset.image) == _png((87, 60, 30))
            for asset in candidate_assets
        )
    assert selected_id in {
        candidate["asset_id"] for candidate in created_body["creative_candidates"]
    }
    selected_response = client.post(
        f"/projects/{project_id}/creative-candidates/{selected_id}/select",
        json={"created_by": "usr_designer"},
    )
    assert selected_response.status_code == 200, selected_response.text

    raw = audited_import_spec(EXAMPLE_SPEC)
    raw["source_component_coverage"]["components"][0][
        "independent_audit"
    ]["verdict"] = "inconclusive"
    confirmation = client.post(
        f"/projects/{project_id}/creative-candidates/{selected_id}/"
        "source-coverage/confirm",
        json={
            "spec": raw,
            "confirmations": [{
                "component_id": "assembly.primary",
                "basis": "visible_source",
                "confirmed_description": (
                    "The complete alternate ring assembly is visible."
                ),
            }],
            "created_by": "usr_designer",
        },
    )
    assert confirmation.status_code == 200, confirmation.text
    confirmed_spec = confirmation.json()["spec"]
    confirmed_component = confirmed_spec["source_component_coverage"][
        "components"
    ][0]
    assert confirmed_component["designer_confirmation"][
        "evidence_sha256"
    ] == hashlib.sha256(selected_bytes).hexdigest()

    promotion_payload = _promotion_payload(
        client, project_id, selected_id, confirmed_spec)
    promoted = client.post(
        f"/projects/{project_id}/creative-candidates/{selected_id}/promote",
        json=promotion_payload,
    )
    assert promoted.status_code == 200, promoted.text
    promoted_body = promoted.json()
    assert not any(
        blocker["code"] == "source_component_confirmation_stale"
        for blocker in promoted_body["factory_blockers"]
    )
    active_id = promoted_body["active_asset_id"]

    with Session() as db:
        selected = db.get(ImageAsset, selected_id)
        active = db.get(ImageAsset, active_id)
        root = db.get(ImageAsset, project_id)
        assert selected is not None and active is not None and root is not None
        assert active.parent_asset_id == selected.id
        assert active.capability == "IMPORTED_REFERENCE"
        assert bytes(active.image) == bytes(selected.image) == selected_bytes
        assert bytes(root.image) != selected_bytes

    checklist = client.post(f"/assets/{active_id}/checklist", json={
        "created_by": "usr_designer",
        "mode": "auto_pin",
    })
    assert checklist.status_code == 201, checklist.text
    for item in checklist.json()["items"]:
        response = client.post(f"/assets/{active_id}/checklist/respond", json={
            "item_key": item["key"],
            "approved": True,
            "created_by": "usr_designer",
        })
        assert response.status_code == 201, response.text

    factory_pack = client.get(f"/projects/{project_id}/factory-pack")
    assert factory_pack.status_code == 200, factory_pack.text
    assert factory_pack.json()["asset_id"] == active_id

    # The promoted copy is the evidence anchor, not merely its parent pointer.
    # Any later byte mismatch must restore the freshness blocker and close the
    # factory gate rather than inheriting authority from the candidate.
    with Session() as db:
        active = db.get(ImageAsset, active_id)
        root = db.get(ImageAsset, project_id)
        assert active is not None and root is not None
        # Simulate storage corruption outside the normal ORM path. Canonical
        # ImageAsset assignment is guarded and cannot be used for this fixture.
        db.execute(
            update(ImageAsset)
            .where(ImageAsset.id == active.id)
            .values(image=bytes(root.image))
        )
        db.commit()
    reopened = client.get(f"/projects/{project_id}")
    assert reopened.status_code == 200, reopened.text
    assert any(
        blocker["code"] == "source_component_confirmation_stale"
        for blocker in reopened.json()["factory_blockers"]
    )
    blocked_pack = client.get(f"/projects/{project_id}/factory-pack")
    assert blocked_pack.status_code == 409, blocked_pack.text
    assert blocked_pack.json()["code"] == "source_component_coverage_incomplete"


def test_creative_candidate_mapping_reaudit_receives_stored_candidate_image(
    creative_client, monkeypatch,
):
    client, _Session = creative_client
    app.dependency_overrides[get_creative_render_generator] = (
        lambda: (lambda _source, _instruction, selected: _creative_result(selected)))
    created = client.post(
        "/projects/from-drawing", json=_request(variation_count=1)).json()
    candidate_id = created["creative_candidates"][0]["asset_id"]
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
    candidate_id = body["creative_candidates"][0]["asset_id"]
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
    # Confirming a direction must follow the persisted selection, including
    # when the designer chose a non-first candidate.
    selected_id = body["creative_candidates"][1]["asset_id"]
    selected = client.post(
        f"/projects/{project_id}/creative-candidates/{selected_id}/select",
        json={"created_by": "usr_designer"},
    )
    assert selected.status_code == 200, selected.text
    confirmed_spec = audited_import_spec(EXAMPLE_SPEC)

    promotion_payload = _promotion_payload(
        client, project_id, selected_id, confirmed_spec)
    promoted = client.post(
        f"/projects/{project_id}/creative-candidates/{selected_id}/promote",
        json=promotion_payload,
    )
    assert promoted.status_code == 200, promoted.text
    result = promoted.json()
    assert result["design_id"].startswith("dsn_")
    assert result["latest_design_version"] == 1
    assert result["active_design_version"] == 1
    assert result["factory_ready"] is False
    assert result["active_revision"]["capability"] == "IMPORTED_REFERENCE"
    assert result["active_revision"]["parent_asset_id"] == selected_id
    creative = [item for item in result["revisions"]
                if item["capability"] == "CREATIVE_RENDER"]
    assert len(creative) == 1
    assert all(item["provenance"] == "pre_spec_creative_candidate"
               for item in creative)
    assert all(item["legacy_provenance"] is False for item in creative)
    second_id = body["creative_candidates"][0]["asset_id"]

    replay = client.post(
        f"/projects/{project_id}/creative-candidates/{selected_id}/promote",
        json=promotion_payload,
    )
    assert replay.status_code == 409
    assert "already been used" in replay.json()["detail"]
    post_promotion_select = client.post(
        f"/projects/{project_id}/creative-candidates/{second_id}/select",
        json={"created_by": "usr_designer"},
    )
    assert post_promotion_select.status_code == 409

    checklist = client.post(
        f"/assets/{result['active_asset_id']}/checklist",
        json={"created_by": "usr_designer"},
    )
    assert checklist.status_code == 201, checklist.text

    with patch(
        "facetta.api.projects.from_photo",
        return_value=Spec.model_validate(confirmed_spec),
    ):
        second_confirmation = client.post(
            f"/projects/{project_id}/creative-candidates/{second_id}/"
            "confirm-design",
            json={"created_by": "usr_designer"},
        )
    assert second_confirmation.status_code == 409
    assert "current confirmable pre-spec revision" in (
        second_confirmation.json()["detail"]
    )

    with Session() as db:
        assert db.scalar(select(func.count()).select_from(Design)) == 1
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 1
        assert db.scalar(select(func.count()).select_from(
            ProjectRevisionRecord)) == 1
        assert db.scalar(select(func.count()).select_from(ImageAsset).where(
            ImageAsset.capability == "IMPORTED_REFERENCE")) == 1
        record = db.scalar(select(ProjectRevisionRecord))
        assert record is not None
        assert record.asset_id == result["active_asset_id"]
        assert record.action == "edit"
        assert record.raw_intent["kind"] == "confirm_design"
        assert record.raw_intent["selected_candidate_asset_id"] == selected_id
        assert record.interpretation["factory_authority"] is False


def test_confirm_design_v1_preserves_exact_candidate_component_map(
    creative_client,
):
    client, Session = creative_client
    app.dependency_overrides[get_creative_render_generator] = (
        lambda: (lambda _source, _instruction, variant: _creative_result(variant))
    )
    created = client.post(
        "/projects/from-drawing", json=_request(variation_count=1)
    )
    assert created.status_code == 201, created.text
    body = created.json()
    project_id = body["root_id"]
    with Session() as db:
        candidate_id = db.scalar(select(ImageAsset.id).where(
            ImageAsset.root_id == project_id,
            ImageAsset.capability == "CREATIVE_RENDER",
        ))
        assert candidate_id is not None
    assert client.post(
        f"/projects/{project_id}/creative-candidates/{candidate_id}/select",
        json={"created_by": "usr_designer"},
    ).status_code == 200
    with Session() as db:
        candidate = db.get(ImageAsset, candidate_id)
        assert candidate is not None
        image = bytes(candidate.image)
        add_revision_component_map(
            db,
            _exact_component_map(candidate.id, image),
            image_bytes=image,
            parent_asset_id=candidate.parent_asset_id,
        )
        db.commit()

    promoted = client.post(
        f"/projects/{project_id}/creative-candidates/{candidate_id}/promote",
        json=_promotion_payload(
            client,
            project_id,
            candidate_id,
            audited_import_spec(EXAMPLE_SPEC),
        ),
    )

    assert promoted.status_code == 200, promoted.text
    active_id = promoted.json()["active_asset_id"]
    targeting = client.get(f"/assets/{active_id}/studio-component-targeting")
    assert targeting.status_code == 200, targeting.text
    targeting_body = targeting.json()
    assert targeting_body["component_map"]["state"] == "ready"
    assert targeting_body["component_map"]["mapper_contract"] == (
        "facetta.byte-identical-map-copy.v1"
    )
    assert {
        path["component_path"]
        for path in targeting_body["catalog_paths"]
        if path["status"] == "ready"
    } == {"stone.color", "metal.material", "metal.color"}
    with Session() as db:
        child_record = db.get(RevisionComponentMapRecord, active_id)
        assert child_record is not None
        assert child_record.parent_asset_id == candidate_id
        assert {
            component["parent_component_id"]
            for component in child_record.map_json["components"]
        } == {component_id for component_id, _kind in _RING_COMPONENTS}


def test_confirm_design_v1_without_calibrated_map_stays_fail_closed(
    creative_client,
):
    client, Session = creative_client
    app.dependency_overrides[get_creative_render_generator] = (
        lambda: (lambda _source, _instruction, variant: _creative_result(variant))
    )
    created = client.post(
        "/projects/from-drawing", json=_request(variation_count=1)
    )
    assert created.status_code == 201, created.text
    body = created.json()
    project_id = body["root_id"]
    with Session() as db:
        candidate_id = db.scalar(select(ImageAsset.id).where(
            ImageAsset.root_id == project_id,
            ImageAsset.capability == "CREATIVE_RENDER",
        ))
        assert candidate_id is not None
    assert client.post(
        f"/projects/{project_id}/creative-candidates/{candidate_id}/select",
        json={"created_by": "usr_designer"},
    ).status_code == 200

    promoted = client.post(
        f"/projects/{project_id}/creative-candidates/{candidate_id}/promote",
        json=_promotion_payload(
            client,
            project_id,
            candidate_id,
            audited_import_spec(EXAMPLE_SPEC),
        ),
    )

    assert promoted.status_code == 200, promoted.text
    active_id = promoted.json()["active_asset_id"]
    targeting = client.get(f"/assets/{active_id}/studio-component-targeting")
    assert targeting.status_code == 200, targeting.text
    assert targeting.json()["component_map"] == {
        "state": "unmapped",
        "scope": "ring_v1",
        "map_sha256": None,
        "mapper_contract": None,
        "raster_width": None,
        "raster_height": None,
    }
    assert {
        path["reason_code"] for path in targeting.json()["catalog_paths"]
    } == {"component_map_not_found"}
    with Session() as db:
        assert db.get(RevisionComponentMapRecord, active_id) is None


def test_two_sessions_observe_exactly_one_atomic_root_claim(creative_client):
    client, Session = creative_client
    app.dependency_overrides[get_creative_render_generator] = (
        lambda: (lambda _source, _instruction, variant: _creative_result(variant)))
    body = client.post("/projects/from-drawing", json=_request()).json()
    root_id = body["root_id"]
    first_id = "dsn_atomic_first"
    second_id = "dsn_atomic_second"
    now = utcnow()

    with Session() as first, Session() as second:
        # The losing session observes the old row before the winner commits.
        assert second.get(ImageAsset, root_id).design_id is None
        first.add(Design(
            id=first_id, created_by="usr_designer", created_at=now,
            collection="Exploration",
        ))
        first.flush()
        assert claim_creative_project_design(
            first, root_id=root_id, design_id=first_id)
        first.commit()

        second.add(Design(
            id=second_id, created_by="usr_designer", created_at=now,
            collection="Exploration",
        ))
        second.flush()
        assert not claim_creative_project_design(
            second, root_id=root_id, design_id=second_id)
        second.rollback()

    with Session() as db:
        assert db.get(ImageAsset, root_id).design_id == first_id
        assert db.get(Design, second_id) is None


def test_creative_candidate_confirmation_cas_drift_has_no_partial_writes(
    creative_client,
):
    client, Session = creative_client
    app.dependency_overrides[get_creative_render_generator] = (
        lambda: (lambda _source, _instruction, variant: _creative_result(variant)))
    created = client.post("/projects/from-drawing", json=_request())
    assert created.status_code == 201, created.text
    body = created.json()
    project_id = body["root_id"]
    selected_id = body["creative_candidates"][1]["asset_id"]
    other_id = body["creative_candidates"][0]["asset_id"]
    selected = client.post(
        f"/projects/{project_id}/creative-candidates/{selected_id}/select",
        json={"created_by": "usr_designer"},
    )
    assert selected.status_code == 200, selected.text
    confirmed_spec = audited_import_spec(EXAMPLE_SPEC)
    payload = _promotion_payload(client, project_id, selected_id, confirmed_spec)
    changed = client.post(
        f"/projects/{project_id}/creative-candidates/{other_id}/select",
        json={"created_by": "usr_designer"},
    )
    assert changed.status_code == 200, changed.text

    response = client.post(
        f"/projects/{project_id}/creative-candidates/{selected_id}/promote",
        json=payload,
    )
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "creative_candidate_promotion_conflict"

    with Session() as db:
        project = db.get(Project, project_id)
        root = db.get(ImageAsset, project_id)
        assert project is not None and root is not None
        assert root.design_id is None
        assert db.scalar(select(func.count()).select_from(Design)) == 0
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 0
        assert db.scalar(select(func.count()).select_from(
            ProjectRevisionRecord)) == 0
        assert db.scalar(select(func.count()).select_from(ImageAsset).where(
            ImageAsset.capability == "IMPORTED_REFERENCE")) == 0


@pytest.mark.parametrize(
    "attack", [
        "expired", "tampered", "wrong_owner", "wrong_project", "wrong_candidate"
    ])
def test_opaque_confirmation_token_rejects_invalid_binding_without_writes(
    creative_client,
    attack: str,
):
    client, Session = creative_client
    app.dependency_overrides[get_creative_render_generator] = (
        lambda: (lambda _source, _instruction, variant: _creative_result(variant)))
    body = client.post("/projects/from-drawing", json=_request()).json()
    project_id = body["root_id"]
    selected_id = body["creative_candidates"][1]["asset_id"]
    other_id = body["creative_candidates"][0]["asset_id"]
    assert client.post(
        f"/projects/{project_id}/creative-candidates/{selected_id}/select",
        json={"created_by": "usr_designer"},
    ).status_code == 200
    payload = _promotion_payload(
        client, project_id, selected_id, audited_import_spec(EXAMPLE_SPEC))
    path_project = project_id
    path_candidate = selected_id
    if attack == "expired":
        token_hash = hashlib.sha256(
            payload["confirmation_token"].encode("utf-8")
        ).hexdigest()
        with Session() as db:
            draft = db.scalar(select(StudioConfirmationDraft).where(
                StudioConfirmationDraft.token_sha256 == token_hash))
            assert draft is not None
            draft.expires_at = draft.created_at + timedelta(microseconds=1)
            db.commit()
    elif attack == "tampered":
        payload["confirmation_token"] = "invalid-" + payload["confirmation_token"]
    elif attack == "wrong_owner":
        payload["created_by"] = "usr_intruder"
    elif attack == "wrong_project":
        other = client.post("/projects/from-drawing", json={
            **_request(),
            "title": "Other project",
        }).json()
        path_project = other["root_id"]
        path_candidate = other["creative_candidates"][0]["asset_id"]
        assert client.post(
            f"/projects/{path_project}/creative-candidates/"
            f"{path_candidate}/select",
            json={"created_by": "usr_designer"},
        ).status_code == 200
    else:
        path_candidate = other_id

    response = client.post(
        f"/projects/{path_project}/creative-candidates/{path_candidate}/promote",
        json=payload,
    )
    assert response.status_code in {403, 409}, response.text
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(Design)) == 0
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 0
        assert db.scalar(select(func.count()).select_from(
            ProjectRevisionRecord)) == 0


def test_promote_rejects_client_spec_even_with_recomputed_hash(
    creative_client,
):
    client, Session = creative_client
    app.dependency_overrides[get_creative_render_generator] = (
        lambda: (lambda _source, _instruction, variant: _creative_result(variant)))
    body = client.post("/projects/from-drawing", json=_request()).json()
    project_id = body["root_id"]
    selected_id = body["creative_candidates"][0]["asset_id"]
    assert client.post(
        f"/projects/{project_id}/creative-candidates/{selected_id}/select",
        json={"created_by": "usr_designer"},
    ).status_code == 200
    spec = audited_import_spec(EXAMPLE_SPEC)
    payload = _promotion_payload(client, project_id, selected_id, spec)
    modified = copy.deepcopy(spec)
    modified["band"]["width_mm"] = modified["band"]["width_mm"] + 0.5
    payload["spec"] = modified
    payload["expected_spec_visual_hash"] = spec_visual_hash(
        Spec.model_validate(modified))

    response = client.post(
        f"/projects/{project_id}/creative-candidates/{selected_id}/promote",
        json=payload,
    )
    assert response.status_code == 422
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(Design)) == 0
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 0


def test_confirm_design_cleans_expired_unused_drafts_but_keeps_consumed(
    creative_client,
):
    client, Session = creative_client
    app.dependency_overrides[get_creative_render_generator] = (
        lambda: (lambda _source, _instruction, variant: _creative_result(variant)))
    body = client.post("/projects/from-drawing", json=_request()).json()
    project_id = body["root_id"]
    selected_id = body["creative_candidates"][0]["asset_id"]
    assert client.post(
        f"/projects/{project_id}/creative-candidates/{selected_id}/select",
        json={"created_by": "usr_designer"},
    ).status_code == 200
    spec = audited_import_spec(EXAMPLE_SPEC)
    expired_payload = _promotion_payload(client, project_id, selected_id, spec)
    expired_hash = hashlib.sha256(
        expired_payload["confirmation_token"].encode("utf-8")
    ).hexdigest()
    with Session() as db:
        expired = db.scalar(select(StudioConfirmationDraft).where(
            StudioConfirmationDraft.token_sha256 == expired_hash))
        assert expired is not None
        expired.expires_at = expired.created_at + timedelta(microseconds=1)
        db.commit()

    live_payload = _promotion_payload(client, project_id, selected_id, spec)
    live_hash = hashlib.sha256(
        live_payload["confirmation_token"].encode("utf-8")
    ).hexdigest()
    with Session() as db:
        assert db.scalar(select(StudioConfirmationDraft).where(
            StudioConfirmationDraft.token_sha256 == expired_hash)) is None

    promoted = client.post(
        f"/projects/{project_id}/creative-candidates/{selected_id}/promote",
        json=live_payload,
    )
    assert promoted.status_code == 200, promoted.text
    with Session() as db:
        consumed = db.scalar(select(StudioConfirmationDraft).where(
            StudioConfirmationDraft.token_sha256 == live_hash))
        assert consumed is not None and consumed.consumed_at is not None
        consumed.expires_at = consumed.created_at + timedelta(microseconds=1)
        db.commit()

    other = client.post("/projects/from-drawing", json={
        **_request(), "title": "Cleanup trigger",
    }).json()
    other_id = other["creative_candidates"][0]["asset_id"]
    assert client.post(
        f"/projects/{other['root_id']}/creative-candidates/{other_id}/select",
        json={"created_by": "usr_designer"},
    ).status_code == 200
    _promotion_payload(client, other["root_id"], other_id, spec)
    with Session() as db:
        preserved = db.scalar(select(StudioConfirmationDraft).where(
            StudioConfirmationDraft.token_sha256 == live_hash))
        assert preserved is not None
        assert preserved.consumed_at is not None


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
    assert selected_id == body["creative_candidates"][0]["asset_id"]
    selected = client.post(
        f"/projects/{body['root_id']}/creative-candidates/{selected_id}/select",
        json={"created_by": "usr_designer"},
    )
    assert selected.status_code == 200, selected.text
    confirmed_spec = audited_import_spec(EXAMPLE_SPEC)

    promoted = client.post(
        f"/projects/{body['root_id']}/creative-candidates/{selected_id}/promote",
        json=_promotion_payload(
            client, body["root_id"], selected_id, confirmed_spec),
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

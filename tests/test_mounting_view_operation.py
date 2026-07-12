from __future__ import annotations

import pytest

from conftest import HALO_SPEC
from facetta.image_agent import (
    ImageOperation,
    ImagePlanValidationError,
    ImageRoute,
    build_image_plan,
    openai_route_for_plan,
)
from facetta.image_agent.planning import route_for_attempt
from facetta.image_agent.prompts import compile_initial_prompt
from facetta.spec import Spec


SPEC = Spec.model_validate(HALO_SPEC)
SOURCE = b"approved-ring-source"


def test_mounting_view_plan_is_source_backed_spec_bound_and_review_only():
    plan = build_image_plan(
        ImageOperation.MOUNTING_VIEW_GENERATE,
        "Show the actual design-specific side mounting",
        spec=SPEC,
        source_image=SOURCE,
        mounting_view="side",
    )

    assert plan.prompt_version == "mounting-view.v1"
    assert plan.mounting_view == "side"
    assert plan.normalized_intent["requested_projections"] == ["side"]
    assert plan.normalized_intent["mounting_hardware"] == {
        "required_views": ["side"],
        "authority": "factory_discussion_only",
        "designer_confirmation_required": True,
        "production_authority": False,
    }
    assert route_for_attempt(plan, 1) is ImageRoute.GROK_EDIT
    assert route_for_attempt(plan, 2) is ImageRoute.GROK_EDIT
    assert route_for_attempt(plan, 3) is ImageRoute.FLUX_KONTEXT_EDIT
    assert openai_route_for_plan(plan) is ImageRoute.OPENAI_EDIT


def test_mounting_view_requires_source_spec_and_supported_projection():
    with pytest.raises(ImagePlanValidationError, match="requires a source image"):
        build_image_plan(
            ImageOperation.MOUNTING_VIEW_GENERATE,
            "side mounting",
            spec=SPEC,
            mounting_view="side",
        )
    with pytest.raises(ImagePlanValidationError, match="validated ring spec"):
        build_image_plan(
            ImageOperation.MOUNTING_VIEW_GENERATE,
            "side mounting",
            source_image=SOURCE,
            mounting_view="side",
        )
    with pytest.raises(ImagePlanValidationError, match="plan, front, side, or section"):
        build_image_plan(
            ImageOperation.MOUNTING_VIEW_GENERATE,
            "three-quarter mounting",
            spec=SPEC,
            source_image=SOURCE,
            mounting_view="three_quarter",
        )


def test_mounting_view_field_cannot_leak_into_another_operation():
    with pytest.raises(ImagePlanValidationError, match="only valid"):
        build_image_plan(
            ImageOperation.SPEC_RENDER,
            "render ring",
            spec=SPEC,
            mounting_view="side",
        )


def test_mounting_prompt_generates_one_view_and_assigns_geometry_to_ai():
    plan = build_image_plan(
        ImageOperation.MOUNTING_VIEW_GENERATE,
        "Show the actual design-specific side mounting",
        spec=SPEC,
        source_image=SOURCE,
        mounting_view="side",
    )
    prompt = compile_initial_prompt(plan)

    assert "exactly ONE isolated orthographic SIDE" in prompt
    assert "IMAGE MODEL OWNS" not in prompt  # provider prompt stays concise
    assert "no stock or generic basket" in prompt
    assert "designer confirmation" in prompt
    assert "DESIGNER DIRECTION" in prompt
    assert "Show the actual design-specific side mounting" in prompt
    assert len(prompt) < 8_000

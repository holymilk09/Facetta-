from __future__ import annotations

from facetta.mounting_hardware import (
    compile_mounting_hardware_prompt,
    compile_mounting_view_prompt,
    mounting_hardware_contract,
)
from facetta.ring_evals import RING_GOLDEN_CASES, build_ring_golden_spec


def test_engagement_ring_requires_design_specific_side_mounting():
    contract = mounting_hardware_contract("RING_ENGAGEMENT")
    assert contract is not None
    side = next(view for view in contract.views if view.view == "side")
    assert side.default_authority == "unknown"
    assert "stone seat or bearing relationship" in side.required_hardware
    assert "undergallery or bridge" in side.required_hardware
    assert "head-to-shoulder and head-to-shank connection" in side.required_hardware


def test_mounting_prompt_assigns_geometry_to_image_model_without_false_authority():
    prompt = compile_mounting_hardware_prompt("RING_ENGAGEMENT")
    assert "IMAGE MODEL OWNS THE DRAWN JEWELRY GEOMETRY" in prompt
    assert "generic circles, rectangles, baskets, or stock profiles" in prompt
    assert "proposal for designer confirmation" in prompt
    assert "never treat that hidden construction as observed" in prompt
    assert "stone seat or bearing relationship" in prompt
    assert "floating stones" in prompt
    assert "same gallery-rail count" in prompt


def test_non_ring_mode_does_not_receive_ring_mounting_assumptions():
    assert mounting_hardware_contract("PENDANT") is None
    assert compile_mounting_hardware_prompt("PENDANT") == ""


def test_mounting_evidence_marks_synthesized_profiles_as_proposals():
    contract = mounting_hardware_contract("RING_ENGAGEMENT")
    assert contract is not None
    summary = contract.evidence_summary()
    assert summary["deterministic_geometry_allowed"] is False
    assert summary["production_authority"] is False
    side = next(
        view for view in summary["views"]
        if view["view"] == "side"
    )
    assert side["authority"] == "unknown_until_source_and_candidate_audit"
    assert side["authority_policy"] == (
        "hidden_geometry_is_proposed_until_designer_confirmation"
    )


def test_single_side_view_prompt_uses_validated_ring_facts():
    case = next(item for item in RING_GOLDEN_CASES if item.id == "cushion-halo-white-6-wide")
    prompt = compile_mounting_view_prompt(build_ring_golden_spec(case), "side")
    assert "exactly ONE isolated orthographic SIDE" in prompt
    assert "cushion" in prompt
    assert "center holding-prong count 6" in prompt
    assert "total side/halo stone count 19" in prompt
    assert "stone seat or bearing relationship" in prompt
    assert "no stock or generic basket" in prompt
    assert "No color, shading, shadows, dimensions" in prompt


def test_single_section_prompt_forbids_metal_through_stone():
    case = next(item for item in RING_GOLDEN_CASES if item.id == "cushion-halo-white-6-wide")
    prompt = compile_mounting_view_prompt(
        build_ring_golden_spec(case),
        "section",
        correction="remove the center bar",
    )
    assert "TRUE CUT SECTION" in prompt
    assert "section hatching only on cut metal" in prompt
    assert "No solid member or prong may pass through the gemstone" in prompt
    assert "Targeted correction" in prompt
    assert "remove the center bar" in prompt

"""Custom factory geometry must replace, not decorate, a generic template."""

from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from facetta.dxf import svg_to_dxf
from facetta.dimension_provenance import estimated_dimension_summary
from facetta.factory_sheet_plan import build_factory_sheet_fact_plan
from facetta.checklist import build_checklist_items
from facetta.preliminary_sheet import render_sheet_for_review
from facetta.spec import Spec
from facetta.svg_sheet import render_sheet


def _profile_element(*, element_id: str = "assembly.full") -> dict:
    return {
        "element_id": element_id,
        "role": "full_assembly",
        "label": "Designer vine assembly",
        "confirmed_form_description": (
            "Complete designer-confirmed front assembly profile."
        ),
        "symmetry": "asymmetric",
        "instance_count": 1,
        "regions": [{
            "view": "front",
            "polygons": [{
                "points": [
                    {"x": 0.1, "y": 0.1},
                    {"x": 0.9, "y": 0.1},
                    {"x": 0.9, "y": 0.9},
                    {"x": 0.1, "y": 0.9},
                ],
            }],
        }],
        "definition": {
            "kind": "dimensioned_profile",
            "scope": "full_assembly",
            "view": "front",
            "coordinate_system": "x_right_y_up",
            "paths": [
                {
                    "path_id": "vine.outline",
                    "purpose": "outline",
                    "closed": True,
                    "points": [
                        {"x_mm": -12.0, "y_mm": -25.0},
                        {"x_mm": 12.0, "y_mm": -25.0},
                        {"x_mm": 8.0, "y_mm": 25.0},
                        {"x_mm": -8.0, "y_mm": 25.0},
                    ],
                    "nominal_width_mm": None,
                },
                {
                    "path_id": "vine.branch",
                    "purpose": "centerline",
                    "closed": False,
                    "points": [
                        {"x_mm": 0.0, "y_mm": -18.0},
                        {"x_mm": -6.0, "y_mm": 0.0},
                        {"x_mm": 7.0, "y_mm": 17.0},
                    ],
                    "nominal_width_mm": 1.4,
                },
            ],
            "profile_thickness_mm": 1.6,
            "dimension_status": "designer_confirmed_estimate",
            "source_asset_id": "ast_dimensioned_drawing",
            "source_asset_sha256": "d" * 64,
            "confirmed_by": "usr_designer",
            "confirmed_at": "2026-07-12T10:30:00Z",
            "manufacturing_notes": (
                "Prototype profile; factory must verify stone seats and joints."
            ),
        },
    }


def _spec(example_spec: dict) -> Spec:
    raw = copy.deepcopy(example_spec)
    raw["design_form"] = {"elements": [_profile_element()]}
    return Spec.model_validate(raw)


def test_dimensioned_profile_replaces_generic_sheet_geometry(example_spec):
    spec = _spec(example_spec)

    svg, blockers = render_sheet_for_review(spec)

    assert blockers == ()
    assert 'data-facetta-form-authority="dimensioned_profile"' in svg
    assert "DESIGNER-CONFIRMED DIMENSIONED PROFILE" in svg
    assert "DESIGNER-CONFIRMED ESTIMATES — VERIFY BEFORE PRODUCTION" in svg
    assert 'data-profile-path="vine.outline"' in svg
    assert 'data-profile-path="vine.branch"' in svg
    assert "Overall extents: 24 × 50 mm" in svg
    assert "profile thickness 1.6 mm" in svg
    assert "EST. 24 mm OVERALL W" in svg
    assert "EST. 50 mm H" in svg
    assert "SCALE 1:1" in svg
    assert "SCALE 3:1" not in svg
    assert "PRELIMINARY SPEC REVIEW" not in svg


def test_dimensioned_profile_is_deterministic_and_reaches_exchange_dxf(
    example_spec,
):
    spec = _spec(example_spec)

    first = render_sheet(spec)
    second = render_sheet(spec)
    dxf = svg_to_dxf(first)

    assert first == second
    assert "POLYLINE" in dxf
    assert "CIRCLE" not in dxf
    assert "DESIGNER-CONFIRMED DIMENSIONED PROFILE" in dxf


def test_confirmed_profile_estimates_are_disclosed_in_manifest_fact_models(
    example_spec,
):
    spec = _spec(example_spec)

    summary = estimated_dimension_summary(spec)
    plan = build_factory_sheet_fact_plan(spec, confirmed_sections={
        "design_form",
    })

    assert summary["has_estimates"] is True
    assert any(
        item["field_path"].endswith("profile_thickness_mm")
        and item["status"] == "estimated_from_reference"
        and item["source"] == "ast_dimensioned_drawing"
        for item in summary["estimated_fields"]
    )
    profile_facts = [
        item for item in plan.dimensions
        if item.field_path.startswith("design_form.elements[0].definition")
    ]
    assert profile_facts
    assert all(item.status == "estimated_from_reference" for item in profile_facts)
    assert plan.has_estimates is True
    recorded = {
        item.field_path: item for item in plan.recorded_facts
        if item.section == "design_form"
    }
    assert recorded["design_form.elements[0].role"].fact_status == (
        "estimated_from_reference"
    )
    checklist_item = next(
        item for item in build_checklist_items(spec)
        if item.key == "design_form:assembly.full"
    )
    assert "designer-confirmed estimate" in checklist_item.fact
    assert "visual reference only" not in checklist_item.fact


def test_more_than_one_full_assembly_profile_is_rejected(example_spec):
    raw = copy.deepcopy(example_spec)
    raw["design_form"] = {
        "elements": [
            _profile_element(element_id="assembly.first"),
            _profile_element(element_id="assembly.second"),
        ],
    }

    with pytest.raises(ValidationError, match="only one dimensioned"):
        Spec.model_validate(raw)

"""Incomplete visual geometry must never look like a factory-ready sheet."""

from __future__ import annotations

import copy

from fastapi.testclient import TestClient

from facetta.main import app
from facetta.preliminary_sheet import (
    render_sheet_for_review,
    sheet_readiness_blockers,
)
from facetta.spec import Spec
from facetta.validation import validate_spec
from facetta.vocabulary import get_vocabulary


def _reference_defined_necklace(raw: dict) -> Spec:
    value = copy.deepcopy(raw)
    value["design_form"] = {
        "elements": [{
            "element_id": "vine_assembly",
            "role": "pendant_structure",
            "label": "Asymmetric vine assembly",
            "confirmed_form_description": (
                "Asymmetric two-branch vine carrying five emerald leaves."
            ),
            "symmetry": "asymmetric",
            "instance_count": 1,
            "regions": [{
                "view": "front",
                "polygons": [{
                    "points": [
                        {"x": 0.1, "y": 0.2},
                        {"x": 0.9, "y": 0.2},
                        {"x": 0.9, "y": 0.9},
                        {"x": 0.1, "y": 0.9},
                    ],
                }],
            }],
            "definition": {
                "kind": "visual_reference_only",
                "asset_id": "ast_reference",
                "asset_sha256": "a" * 64,
            },
        }],
    }
    return Spec.model_validate(value)


def test_incomplete_reference_form_covers_generic_geometry(necklace_spec):
    spec = _reference_defined_necklace(necklace_spec)

    svg, blockers = render_sheet_for_review(spec)

    codes = {item.code for item in blockers}
    assert "visual_reference_not_dimensioned" in codes
    assert "chain_geometry_missing" in codes
    assert 'data-facetta-authority="preliminary_not_for_production"' in svg
    assert "PRELIMINARY SPEC REVIEW — NOT FOR PRODUCTION" in svg
    assert "REFERENCE-DEFINED GEOMETRY WITHHELD" in svg
    assert "Custom form needs dimensioned geometry" in svg
    assert "Chain construction dimensions are incomplete" in svg
    assert 'x="8.5" y="8.5" width="280" height="17.5"' in svg
    assert "NO DXF OR FACTORY PACK MAY BE GENERATED" in svg
    assert "CONFIDENTIAL — FACTORY PRODUCTION ONLY" not in svg


def test_complete_ring_preview_remains_unmodified_factory_geometry(halo_spec):
    validated = validate_spec(Spec.model_validate(halo_spec), get_vocabulary())
    assert validated.ok
    spec = validated.spec
    svg, blockers = render_sheet_for_review(spec)
    assert blockers == ()
    assert "PRELIMINARY SPEC REVIEW" not in svg
    assert "CONFIDENTIAL — FACTORY REVIEW REFERENCE" in svg
    assert "SCHEMATIC DIMENSIONAL DIAGRAM — NOT PRODUCTION GEOMETRY" in svg


def test_stateless_preview_marks_authority_and_blocks_unsafe_dxf(
    necklace_spec,
):
    spec = _reference_defined_necklace(necklace_spec)
    client = TestClient(app)

    preview = client.post("/specs/sheet.svg", json=spec.model_dump(mode="json"))
    assert preview.status_code == 200, preview.text
    assert preview.headers["X-Facetta-Sheet-Authority"] == (
        "preliminary_not_for_production"
    )
    assert "REFERENCE-DEFINED GEOMETRY WITHHELD" in preview.text

    dxf = client.post("/specs/sheet.dxf", json=spec.model_dump(mode="json"))
    assert dxf.status_code == 409, dxf.text
    assert dxf.json()["code"] == "factory_geometry_incomplete"
    assert {item["code"] for item in dxf.json()["blockers"]} >= {
        "visual_reference_not_dimensioned",
        "chain_geometry_missing",
        "chain_production_reference_missing",
        "chain_pendant_connection_missing",
    }


def test_blocker_helper_is_deterministic(necklace_spec):
    spec = _reference_defined_necklace(necklace_spec)
    assert sheet_readiness_blockers(spec) == sheet_readiness_blockers(spec)

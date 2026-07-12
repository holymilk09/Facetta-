"""Necklace chain geometry is factory data, not an image-model guess."""

from __future__ import annotations

import copy

import pytest

from facetta.chain_geometry import chain_factory_blockers
from facetta.checklist import build_checklist_items
from facetta.component_catalog import CatalogSelectionError, apply_catalog_selection
from facetta.dimension_provenance import (
    estimated_dimension_summary,
    with_reference_dimension_estimates,
)
from facetta.dxf import svg_to_dxf
from facetta.spec import Spec
from facetta.svg_sheet import render_sheet
from facetta.validation import validate_spec
from facetta.vocabulary import get_vocabulary


def _open_link_chain(*, style: str = "cable") -> dict:
    links = [{
        "role": "standard",
        "length_mm": 3.8,
        "inside_length_mm": 3.1,
        "inside_width_mm": 1.3,
    }]
    if style == "figaro":
        links.append({
            "role": "long",
            "length_mm": 7.0,
            "inside_length_mm": 6.3,
            "inside_width_mm": 1.3,
        })
    return {
        "style": style,
        "length_mm": 450.0,
        "clasp": "lobster",
        "pendant_connection": "slides_through_bail",
        "geometry": {
            "construction": "open_link",
            "chain_width_mm": 2.0,
            "profile_thickness_mm": 0.6,
            # Valid supplier combinations may have an end ring narrower than
            # the widest link; no false OD >= chain-width invariant is used.
            "end_ring_outer_diameter_mm": 1.8,
            "link_thickness_mm": 0.35,
            "links_soldered": True,
            "links": links,
        },
        "production": {
            "mode": "stock",
            "reference_kind": "supplier_sku",
            "reference": "RG-CABLE-2MM-18Y",
        },
    }


def _spec(necklace_spec: dict, chain: dict) -> Spec:
    raw = copy.deepcopy(necklace_spec)
    raw["chain"] = chain
    return Spec.model_validate(raw)


def _issues(spec: Spec) -> list:
    return validate_spec(spec, get_vocabulary()).issues


def test_legacy_chain_remains_readable_and_valid_but_not_factory_ready(
    necklace_spec,
):
    legacy = Spec.model_validate(necklace_spec)

    assert legacy.chain is not None
    assert legacy.chain.geometry is None
    assert legacy.chain.production is None
    assert legacy.chain.pendant_connection is None
    assert validate_spec(legacy, get_vocabulary()).ok
    assert {blocker.code for blocker in chain_factory_blockers(legacy)} == {
        "chain_geometry_missing",
        "chain_production_reference_missing",
        "chain_pendant_connection_missing",
    }

    # The additive schema must not perturb historical deterministic sheets.
    assert "end-ring OD" not in render_sheet(legacy)
    assert "pendant connection:" not in render_sheet(legacy)


def test_open_link_chain_serializes_exact_factory_and_provenance_fields(
    necklace_spec,
):
    chain = _open_link_chain()
    current = _spec(necklace_spec, chain)
    validated = validate_spec(current, get_vocabulary())

    assert validated.ok, [issue.as_detail() for issue in validated.issues]
    assert chain_factory_blockers(validated.spec) == ()
    serialized = validated.spec.model_dump(mode="json")["chain"]
    assert serialized["geometry"]["construction"] == "open_link"
    assert serialized["geometry"]["links"][0]["inside_width_mm"] == 1.3
    assert serialized["production"]["reference"] == "RG-CABLE-2MM-18Y"

    estimated = with_reference_dimension_estimates(
        validated.spec,
        source="uploaded necklace reference",
        confidence=0.58,
    )
    summary = estimated_dimension_summary(estimated)
    estimated_paths = {
        item["field_path"] for item in summary["estimated_fields"]
    }
    assert {
        "chain.geometry.chain_width_mm",
        "chain.geometry.profile_thickness_mm",
        "chain.geometry.end_ring_outer_diameter_mm",
        "chain.geometry.link_thickness_mm",
        "chain.geometry.links[0].length_mm",
        "chain.geometry.links[0].inside_length_mm",
        "chain.geometry.links[0].inside_width_mm",
    } <= estimated_paths

    sheet = render_sheet(estimated)
    assert "width 2 · profile 0.6 · end-ring OD 1.8 mm EST." in sheet
    assert "standard L 3.8, ID 3.1 × 1.3 mm" in sheet
    assert "link thickness 0.35 mm · soldered EST." in sheet
    assert "pendant connection: slides through bail" in sheet
    assert "stock · supplier sku: RG-CABLE-2MM-18Y" in sheet
    dxf = svg_to_dxf(sheet)
    assert "end-ring OD 1.8 mm EST." in dxf
    assert "supplier sku: RG-CABLE-2MM-18Y" in dxf

    chain_item = next(
        item for item in build_checklist_items(estimated)
        if item.key == "chain"
    )
    assert "width 2 × profile 0.6 mm EST." in chain_item.fact
    assert "slides through bail" in chain_item.fact
    assert "RG-CABLE-2MM-18Y" in chain_item.fact


def test_compatible_style_selection_preserves_exact_chain_factory_record(
    necklace_spec,
):
    source = _spec(necklace_spec, _open_link_chain())

    selected = apply_catalog_selection(
        source,
        component_path="chain.style",
        option_id="curb",
    ).spec

    assert selected.chain is not None and source.chain is not None
    assert selected.chain.style == "curb"
    assert selected.chain.geometry == source.chain.geometry
    assert selected.chain.production == source.chain.production
    assert selected.chain.pendant_connection == source.chain.pendant_connection


def test_style_selection_cannot_relabel_open_links_as_rope_without_new_geometry(
    necklace_spec,
):
    source = _spec(necklace_spec, _open_link_chain())

    with pytest.raises(
        CatalogSelectionError,
        match="requires stranded geometry",
    ):
        apply_catalog_selection(
            source,
            component_path="chain.style",
            option_id="rope",
        )


def test_open_link_dimensions_cannot_describe_impossible_link_openings(
    necklace_spec,
):
    chain = _open_link_chain()
    chain["geometry"]["chain_width_mm"] = 1.5
    chain["geometry"]["links"][0]["length_mm"] = 3.2
    issues = _issues(_spec(necklace_spec, chain))

    locations = {issue.loc for issue in issues}
    assert ("chain", "geometry", "chain_width_mm") in locations
    assert ("chain", "geometry", "links", 0, "length_mm") in locations


def test_figaro_requires_standard_and_long_repeat_records(necklace_spec):
    chain = _open_link_chain(style="figaro")
    chain["geometry"]["links"] = chain["geometry"]["links"][:1]

    issue = next(
        item for item in _issues(_spec(necklace_spec, chain))
        if item.loc == ("chain", "geometry", "links")
    )
    assert issue.expected == {"roles": ["standard", "long"]}


def test_rope_and_snake_are_not_coerced_into_open_link_geometry(necklace_spec):
    rope = _open_link_chain(style="rope")
    rope_issue = next(
        item for item in _issues(_spec(necklace_spec, rope))
        if item.loc == ("chain", "geometry", "construction")
    )
    assert rope_issue.expected == {"construction": "stranded"}

    rope["geometry"] = {
        "construction": "stranded",
        "chain_width_mm": 2.4,
        "profile_thickness_mm": 2.3,
        "end_ring_outer_diameter_mm": 4.0,
        "strand_wire_diameter_mm": 0.28,
        "strand_count": 8,
    }
    assert validate_spec(_spec(necklace_spec, rope), get_vocabulary()).ok

    snake = copy.deepcopy(rope)
    snake["style"] = "snake"
    snake["geometry"] = {
        "construction": "smooth_plate",
        "chain_width_mm": 2.2,
        "profile_thickness_mm": 1.4,
        "end_ring_outer_diameter_mm": 3.5,
        "plate_thickness_mm": 0.18,
    }
    assert validate_spec(_spec(necklace_spec, snake), get_vocabulary()).ok


def test_bail_clearance_applies_only_when_chain_slides_through(necklace_spec):
    chain = _open_link_chain()
    chain["geometry"]["chain_width_mm"] = 4.0
    chain["geometry"]["links"][0]["inside_width_mm"] = 3.3
    # Fixture bail ID is 3.5 mm; a 4.0 mm chain cannot slide through it.
    sliding = _issues(_spec(necklace_spec, chain))
    assert any(
        issue.loc == ("pendant", "bail_inner_diameter_mm")
        for issue in sliding
    )

    chain["pendant_connection"] = "fixed_to_bail"
    fixed = _issues(_spec(necklace_spec, chain))
    assert not any(
        issue.loc == ("pendant", "bail_inner_diameter_mm")
        for issue in fixed
    )

    chain["pendant_connection"] = "split_chain"
    split = _issues(_spec(necklace_spec, chain))
    assert not any(
        issue.loc == ("pendant", "bail_inner_diameter_mm")
        for issue in split
    )


def test_production_reference_kind_must_match_stock_or_custom(necklace_spec):
    stock = _open_link_chain()
    stock["production"]["reference_kind"] = "cad_asset"
    stock_issue = next(
        item for item in _issues(_spec(necklace_spec, stock))
        if item.loc == ("chain", "production", "reference_kind")
    )
    assert stock_issue.valid_options == ["approved_sample", "supplier_sku"]

    custom = _open_link_chain()
    custom["production"] = {
        "mode": "custom",
        "reference_kind": "supplier_sku",
        "reference": "not-a-custom-construction-record",
    }
    custom_issue = next(
        item for item in _issues(_spec(necklace_spec, custom))
        if item.loc == ("chain", "production", "reference_kind")
    )
    assert custom_issue.valid_options == ["cad_asset", "dimensioned_drawing"]

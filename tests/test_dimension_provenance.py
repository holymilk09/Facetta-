from __future__ import annotations

import copy

from facetta.agent import Annotation, resolve_target, scope_guard
from facetta.checklist import build_checklist_items
from facetta.dimension_provenance import (
    ESTIMATE_DISCLAIMER,
    confirm_designer_dimension_subtree,
    estimated_dimension_summary,
    with_reference_dimension_estimates,
)
from facetta.spec import DimensionProvenance, Spec
from facetta.svg_sheet import render_sheet
from facetta.validation import validate_spec
from facetta.vocabulary import get_vocabulary


def test_reference_completion_marks_dimensions_without_downgrading_confirmation(
    example_spec,
):
    original = Spec.model_validate(example_spec).model_copy(update={
        "dimension_provenance": {
            "band.width_mm": DimensionProvenance(
                status="designer_confirmed",
                method="designer_input",
                source="designer caliper measurement",
                confidence=1.0,
            ),
        },
    })

    result = with_reference_dimension_estimates(
        original, source="uploaded reference", confidence=0.4)

    assert result.dimension_provenance["band.width_mm"].status == (
        "designer_confirmed")
    assert result.dimension_provenance["stone.dimensions_mm.depth"].status == (
        "estimated_from_reference")
    assert result.dimension_provenance["ring_size.value"].status == (
        "estimated_from_reference")
    summary = estimated_dimension_summary(result)
    assert summary["has_estimates"] is True
    assert summary["disclaimer"] == ESTIMATE_DISCLAIMER


def test_scoped_manual_adjustment_promotes_only_the_changed_dimension(
    example_spec,
):
    current = with_reference_dimension_estimates(
        Spec.model_validate(example_spec), source="uploaded reference")
    data = current.model_dump(mode="json")
    data["band"]["width_mm"] = 2.2
    proposed = Spec.model_validate(data)
    target = resolve_target(current, Annotation(
        instruction="set the band width to 2.2 mm", section="band"))

    guarded, changed, _ = scope_guard(current, target, proposed)

    assert guarded.band.width_mm == 2.2
    assert changed == ["band.width_mm 1.8 → 2.2"]
    confirmed = guarded.dimension_provenance["band.width_mm"]
    assert confirmed.status == "designer_confirmed"
    assert confirmed.method == "designer_input"
    assert guarded.dimension_provenance["band.thickness_mm"].status == (
        "estimated_from_reference")


def test_new_side_stone_inventory_dimensions_remain_explicit_estimates(
    halo_spec,
):
    current = with_reference_dimension_estimates(
        Spec.model_validate(halo_spec), source="uploaded reference")
    data = current.model_dump(mode="json")
    added = copy.deepcopy(data["side_stones"][0])
    added.update({
        "cut": "pear",
        "position": "shoulder_accent",
        "count": 2,
    })
    data["side_stones"].append(added)
    proposed = Spec.model_validate(data)

    guarded, _, _ = scope_guard(
        current, ("side_stones", None), proposed)

    existing = guarded.dimension_provenance[
        "side_stones[0].dimensions_mm.length"]
    added_dimension = guarded.dimension_provenance[
        "side_stones[1].dimensions_mm.length"]
    assert existing.source == "uploaded reference"
    assert added_dimension.status == "estimated_from_reference"
    assert added_dimension.method == "nominal_reference"
    assert added_dimension.source == "AI-planned side-stone inventory"


def test_inventory_removal_reindexes_matching_dimension_provenance(
    halo_spec,
):
    raw = copy.deepcopy(halo_spec)
    second = copy.deepcopy(raw["side_stones"][0])
    second.update({
        "cut": "pear",
        "position": "shoulder_accent",
        "count": 2,
    })
    raw["side_stones"].append(second)
    raw["dimension_provenance"] = {
        "side_stones[0].dimensions_mm.length": {
            "status": "estimated_from_reference",
            "method": "reference_vision",
            "source": "uploaded reference",
        },
        "side_stones[1].dimensions_mm.length": {
            "status": "designer_confirmed",
            "method": "designer_input",
            "source": "designer caliper measurement",
        },
    }
    current = Spec.model_validate(raw)
    changed = current.model_dump(mode="json")
    changed["side_stones"] = [changed["side_stones"][1]]
    proposed = Spec.model_validate(changed)

    guarded, _, _ = scope_guard(
        current, ("side_stones", None), proposed)

    moved = guarded.dimension_provenance[
        "side_stones[0].dimensions_mm.length"]
    assert moved.status == "designer_confirmed"
    assert moved.source == "designer caliper measurement"
    assert not any(path.startswith("side_stones[1]")
                   for path in guarded.dimension_provenance)


def test_validator_carries_estimated_ring_size_into_derived_diameter(
    halo_spec,
):
    draft = with_reference_dimension_estimates(
        Spec.model_validate(halo_spec), source="design plate")

    result = validate_spec(draft, get_vocabulary())

    assert result.ok
    assert result.spec.ring_size.inner_diameter_mm is not None
    diameter = result.spec.dimension_provenance["ring_size.inner_diameter_mm"]
    assert diameter.status == "estimated_from_reference"
    assert "Derived from an estimated ring size" in diameter.note


def test_factory_sheet_marks_estimated_values_but_not_confirmed_values(
    example_spec,
):
    raw = dict(example_spec)
    raw["dimension_provenance"] = {
        "band.width_mm": {
            "status": "estimated_from_reference",
            "method": "reference_vision",
            "source": "uploaded reference",
            "confidence": 0.4,
        },
        "stone.dimensions_mm.length": {
            "status": "designer_confirmed",
            "method": "designer_input",
            "source": "designer caliper measurement",
            "confidence": 1.0,
        },
    }
    spec = validate_spec(Spec.model_validate(raw), get_vocabulary()).spec

    sheet = render_sheet(spec)

    assert "ESTIMATED DIMENSIONS" in sheet
    assert "1.8 mm EST." in sheet
    assert "8.6 mm EST." not in sheet


def test_approval_checklist_identifies_estimated_dimensions(example_spec):
    raw = dict(example_spec)
    raw["dimension_provenance"] = {
        "band.width_mm": {
            "status": "estimated_from_reference",
            "method": "reference_vision",
            "source": "uploaded reference",
        },
    }
    items = {item.key: item for item in build_checklist_items(
        Spec.model_validate(raw))}

    assert items["band"].fact.endswith("mm EST.")
    assert "EST." not in items["stone"].fact


def test_chain_target_confirmation_promotes_equal_values_and_drops_old_branch(
    necklace_spec,
):
    raw = copy.deepcopy(necklace_spec)
    raw["chain"].update({
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
            "reference": "CABLE-SOURCE",
        },
        "pendant_connection": "slides_through_bail",
    })
    raw["dimension_provenance"] = {
        "chain.geometry.chain_width_mm": {
            "status": "estimated_from_reference",
            "method": "reference_vision",
            "source": "uploaded necklace",
        },
        "chain.geometry.links[1].length_mm": {
            "status": "estimated_from_reference",
            "method": "reference_vision",
            "source": "removed old long-link branch",
        },
        "chain.length_mm": {
            "status": "estimated_from_reference",
            "method": "reference_vision",
            "source": "uploaded necklace",
        },
    }

    confirmed = confirm_designer_dimension_subtree(
        Spec.model_validate(raw),
        prefix="chain.geometry",
        source="designer-confirmed target",
    )

    assert confirmed.dimension_provenance[
        "chain.geometry.chain_width_mm"].status == "designer_confirmed"
    assert not any(
        path.startswith("chain.geometry.links[1]")
        for path in confirmed.dimension_provenance
    )
    assert confirmed.dimension_provenance["chain.length_mm"].status == (
        "estimated_from_reference")

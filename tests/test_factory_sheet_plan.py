"""Factory fact schedules distinguish measurements from estimates and review."""

from __future__ import annotations

from copy import deepcopy

from conftest import HALO_SPEC

from facetta.checklist import build_checklist_items
from facetta.factory_schedule_pages import render_factory_schedule_pages
from facetta.factory_sheet_plan import (
    build_factory_sheet_fact_plan,
    pending_factory_fact_paths,
)
from facetta.spec import Spec
from facetta.svg_sheet import render_sheet


def test_unapproved_plan_marks_recorded_facts_pending_not_confirmed():
    plan = build_factory_sheet_fact_plan(Spec.model_validate(HALO_SPEC))
    assert plan.materials[0].fact_status == "pending_confirmation"
    assert plan.stones[0].fact_status == "pending_confirmation"
    assert plan.settings[0].fact_status == "pending_confirmation"
    assert plan.pending_confirmation_count > 0
    assert plan.confirmed_fact_count == 0
    assert "notes_to_factory" in pending_factory_fact_paths(plan)


def test_completed_section_approval_confirms_unprovenanced_recorded_facts():
    spec = Spec.model_validate(HALO_SPEC)
    plan = build_factory_sheet_fact_plan(
        spec,
        confirmed_sections={
            "stone", "side_stones", "setting", "metal", "band", "ring_size",
            "notes_to_factory",
        },
    )
    assert plan.pending_confirmation_count == 0
    assert plan.estimated_fact_count == 0
    assert plan.confirmed_fact_count > 0
    assert all(item.status == "designer_confirmed" for item in plan.dimensions)
    assert pending_factory_fact_paths(plan) == ()


def test_reference_estimate_remains_estimated_after_section_approval():
    raw = {**HALO_SPEC, "dimension_provenance": {
        "band.width_mm": {
            "status": "estimated_from_reference",
            "method": "reference_vision",
            "source": "uploaded designer reference",
            "confidence": 0.55,
            "note": "Verify at the bench.",
        },
    }}
    plan = build_factory_sheet_fact_plan(
        Spec.model_validate(raw),
        confirmed_sections={"band"},
    )
    width = next(item for item in plan.dimensions
                 if item.field_path == "band.width_mm")
    thickness = next(item for item in plan.dimensions
                     if item.field_path == "band.thickness_mm")
    assert width.status == "estimated_from_reference"
    assert width.source == "uploaded designer reference"
    assert width.confidence == 0.55
    assert thickness.status == "designer_confirmed"
    assert plan.has_estimates is True
    assert plan.estimated_fact_count == 1
    assert "not measurements" in (plan.estimate_disclaimer or "")


def test_stone_schedule_preserves_group_counts_roles_and_dimension_paths():
    plan = build_factory_sheet_fact_plan(
        Spec.model_validate(HALO_SPEC),
        confirmed_sections={"stone", "side_stones"},
    )
    assert [(row.ref, row.role, row.count) for row in plan.stones] == [
        ("A", "center", 1),
        ("B", "halo", 8),
    ]
    assert plan.stones[1].carat_total == 2.0
    assert plan.stones[1].dimension_paths == (
        "side_stones[0].dimensions_mm.length",
        "side_stones[0].dimensions_mm.width",
        "side_stones[0].dimensions_mm.depth",
    )


def test_non_numeric_stone_and_factory_instructions_reach_the_schedule():
    raw = deepcopy(HALO_SPEC)
    raw["stone"].update({
        "mount": "bezel",
        "origin": "Sri Lanka",
        "treatment": "heat_only",
        "phenomena": ["asterism"],
        "girdle": "medium",
        "culet": "none",
        "lab": "GIA",
        "inscription": "GIA123456",
    })
    raw["notes_to_factory"] = (
        "Keep the inside shank fully polished and confirm the center-stone "
        "seat against the supplied lab report before casting."
    )
    spec = Spec.model_validate(raw)

    plan = build_factory_sheet_fact_plan(
        spec,
        confirmed_sections={"stone", "notes_to_factory"},
    )
    facts = {item.field_path: item for item in plan.recorded_facts}

    assert facts["stone.mount"].value == "bezel"
    assert facts["stone.origin"].value == "Sri Lanka"
    assert facts["stone.treatment"].value == "heat only"
    assert facts["stone.phenomena"].value == "asterism"
    assert facts["stone.inscription"].value == "GIA123456"
    assert facts["notes_to_factory"].fact_status == "designer_confirmed"
    checklist = build_checklist_items(spec)
    instructions = next(item for item in checklist
                        if item.key == "notes_to_factory")
    assert instructions.question == (
        "Are the factory instructions complete and correct?"
    )

    schedule = "".join(render_factory_schedule_pages(plan, rows_per_page=8))
    assert "stone.mount" in schedule
    assert "notes_to_factory" in schedule
    assert "US 6.5" in schedule
    for token in raw["notes_to_factory"].split():
        assert token.strip(".") in schedule
    assert "…" not in schedule


def test_chain_construction_and_production_reference_are_factory_facts(
    necklace_spec,
):
    raw = deepcopy(necklace_spec)
    raw["chain"] = {
        "style": "figaro",
        "length_mm": 450.0,
        "clasp": "lobster",
        "pendant_connection": "slides_through_bail",
        "geometry": {
            "construction": "open_link",
            "chain_width_mm": 2.2,
            "profile_thickness_mm": 0.7,
            "end_ring_outer_diameter_mm": 2.0,
            "link_thickness_mm": 0.4,
            "links_soldered": True,
            "links": [{
                "role": "standard", "length_mm": 3.8,
                "inside_length_mm": 3.0, "inside_width_mm": 1.2,
            }, {
                "role": "long", "length_mm": 7.0,
                "inside_length_mm": 6.2, "inside_width_mm": 1.2,
            }],
        },
        "production": {
            "mode": "stock",
            "reference_kind": "supplier_sku",
            "reference": "FACETTA-FIGARO-2.2MM-18WG-APPROVED-SAMPLE-0042",
        },
    }
    plan = build_factory_sheet_fact_plan(
        Spec.model_validate(raw),
        confirmed_sections={"chain"},
    )
    facts = {item.field_path: item for item in plan.recorded_facts}

    assert facts["chain.style"].value == "figaro"
    assert facts["chain.clasp"].value == "lobster"
    assert facts["chain.geometry.construction"].value == "open link"
    assert facts["chain.geometry.links_soldered"].value == "yes"
    assert facts["chain.geometry.links[1].role"].value == "long"
    assert facts["chain.production.reference"].value.endswith("0042")
    assert all(item.fact_status == "designer_confirmed"
               for item in facts.values() if item.section == "chain")

    schedule = "".join(render_factory_schedule_pages(plan, rows_per_page=9))
    assert "FACETTA-FIGARO-2.2MM-18WG-APPROVED-SAMPLE-0042" in schedule
    assert "Links soldered: yes" in schedule


def test_trusted_fact_editor_dimension_basis_drives_dynamic_sheet_authority(
    example_spec,
):
    measured_raw = deepcopy(example_spec)
    measured_raw["band"]["width_mm"] = 2.8
    measured_raw["dimension_provenance"] = {
        "band.width_mm": {
            "status": "designer_confirmed",
            "method": "designer_input",
            "source": "trusted factory-fact editor",
            "confidence": 1.0,
            "note": "Designer supplied or measured this value.",
        },
    }
    measured = Spec.model_validate(measured_raw)
    measured_plan = build_factory_sheet_fact_plan(
        measured, confirmed_sections={"band"},
    )
    measured_width = next(
        item for item in measured_plan.dimensions
        if item.field_path == "band.width_mm"
    )
    measured_svg = render_sheet(measured)
    assert measured_width.status == "designer_confirmed"
    assert ">2.8 mm<" in measured_svg
    assert ">2.8 mm EST.<" not in measured_svg

    estimated_raw = deepcopy(measured_raw)
    estimated_raw["dimension_provenance"]["band.width_mm"] = {
        "status": "estimated_from_reference",
        "method": "nominal_reference",
        "source": "designer-confirmed reference estimate",
        "confidence": None,
        "note": "Prototype estimate; verify before manufacturing.",
    }
    estimated = Spec.model_validate(estimated_raw)
    estimated_plan = build_factory_sheet_fact_plan(
        estimated, confirmed_sections={"band"},
    )
    estimated_width = next(
        item for item in estimated_plan.dimensions
        if item.field_path == "band.width_mm"
    )
    estimated_svg = render_sheet(estimated)
    assert estimated_width.status == "estimated_from_reference"
    assert ">2.8 mm EST.<" in estimated_svg

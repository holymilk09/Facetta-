"""Image-space provenance helpers for masked design-form revisions."""

import copy
import io

import pytest
from PIL import Image, ImageDraw

from conftest import HALO_SPEC
from facetta.agent import Annotation, resolve_target, scope_guard
from facetta.checklist import build_checklist_items
from facetta.design_form_revision import (
    DesignFormRevisionError,
    confirm_dimensioned_form_element,
    region_from_markup_mask,
)
from facetta.design_form import DimensionedProfileDefinition
from facetta.image_identity import spec_visual_hash
from facetta.spec import Spec


def _png(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def test_bilateral_mask_keeps_two_isolation_polygons():
    source = _png(Image.new("RGB", (100, 80), "white"))
    mask = Image.new("L", (100, 80), 0)
    draw = ImageDraw.Draw(mask)
    draw.rectangle((10, 25, 25, 55), fill=255)
    draw.rectangle((74, 25, 89, 55), fill=255)

    region = region_from_markup_mask(
        _png(mask), source, view="three_quarter")

    assert len(region.polygons) == 2
    x_ranges = [
        (min(point.x for point in polygon.points),
         max(point.x for point in polygon.points))
        for polygon in region.polygons
    ]
    assert x_ranges[0][1] < 0.5 < x_ranges[1][0]


def test_form_mask_must_match_source_raster():
    source = _png(Image.new("RGB", (100, 80), "white"))
    wrong_size = _png(Image.new("L", (99, 80), 255))

    with pytest.raises(
        DesignFormRevisionError,
        match="exact raster size",
    ) as error:
        region_from_markup_mask(
            wrong_size, source, view="three_quarter")

    assert error.value.code == "form_mask_raster_mismatch"


def _element(element_id: str, description: str) -> dict:
    return {
        "element_id": element_id,
        "role": "shoulder_architecture",
        "label": element_id.replace("_", " ").title(),
        "confirmed_form_description": description,
        "symmetry": "bilateral",
        "instance_count": 2,
        "regions": [{
            "view": "three_quarter",
            "polygons": [{"points": [
                {"x": 0.1, "y": 0.2},
                {"x": 0.3, "y": 0.2},
                {"x": 0.2, "y": 0.4},
            ]}],
        }],
        "definition": {
            "kind": "visual_reference_only",
            "asset_id": "ast_reference",
            "asset_sha256": "1" * 64,
        },
    }


def test_agent_scope_guard_targets_one_stable_form_element():
    raw = copy.deepcopy(HALO_SPEC)
    raw["design_form"] = {"elements": [
        _element("shoulder_architecture", "Stepped Art Deco shoulders."),
        _element("gallery_outline", "Open gallery outline."),
    ]}
    current = Spec.model_validate(raw)
    edited_raw = current.model_dump(mode="json")
    edited_raw["design_form"]["elements"][0][
        "confirmed_form_description"] = "Smooth continuous shoulders."
    edited_raw["design_form"]["elements"][1]["label"] = "UNAUTHORIZED"
    edited_raw["band"]["width_mm"] = 7.0
    edited = Spec.model_validate(edited_raw)
    annotation = Annotation(
        section="design_form",
        target_element_id="shoulder_architecture",
        instruction="smooth the shoulders",
    )

    target = resolve_target(current, annotation)
    guarded, changed, ignored = scope_guard(current, target, edited)

    assert target == ("design_form", "shoulder_architecture")
    assert guarded.design_form.elements[0].confirmed_form_description == (
        "Smooth continuous shoulders.")
    assert guarded.design_form.elements[1] == current.design_form.elements[1]
    assert guarded.band == current.band
    assert any("confirmed_form_description" in path for path in changed)
    assert any("band.width_mm" in path for path in ignored)

    form_items = [
        item for item in build_checklist_items(current)
        if item.section == "design_form"
    ]
    assert [item.target_element_id for item in form_items] == [
        "shoulder_architecture", "gallery_outline"]
    for item in form_items:
        assert resolve_target(current, Annotation(
            section=item.section,
            target_element_id=item.target_element_id,
            instruction="revise this confirmed form",
        )) == ("design_form", item.target_element_id)


def test_visual_hash_uses_form_semantics_not_storage_identity():
    raw = copy.deepcopy(HALO_SPEC)
    raw["design_form"] = {"elements": [
        _element("shoulder_architecture", "Smooth continuous shoulders."),
    ]}
    first = Spec.model_validate(raw)
    rebound = first.model_dump(mode="json")
    rebound["design_form"]["elements"][0]["definition"].update({
        "asset_id": "ast_rebound_candidate",
        "asset_sha256": "f" * 64,
    })
    second = Spec.model_validate(rebound)

    assert spec_visual_hash(first) == spec_visual_hash(second)


def _dimensioned_definition() -> dict:
    return {
        "kind": "dimensioned_profile",
        "scope": "full_assembly",
        "view": "front",
        "coordinate_system": "x_right_y_up",
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
        "source_asset_id": "ast_profile_source",
        "source_asset_sha256": "2" * 64,
        "confirmed_by": "usr_designer",
        "confirmed_at": "2026-07-12T10:30:00Z",
        "manufacturing_notes": "Prototype profile; verify at bench.",
    }


def test_visual_hash_tracks_profile_geometry_but_not_confirmation_metadata():
    raw = copy.deepcopy(HALO_SPEC)
    element = _element("assembly_full", "Complete custom assembly.")
    element["role"] = "full_assembly"
    element["instance_count"] = 1
    element["definition"] = _dimensioned_definition()
    raw["design_form"] = {"elements": [element]}
    original = Spec.model_validate(raw)

    metadata_changed = original.model_dump(mode="json")
    metadata_changed["design_form"]["elements"][0]["definition"].update({
        "source_asset_id": "ast_reconfirmed_profile",
        "source_asset_sha256": "3" * 64,
        "confirmed_by": "usr_second_designer",
        "confirmed_at": "2026-07-12T11:30:00Z",
        "manufacturing_notes": "Same geometry, later bench note.",
    })
    geometry_changed = original.model_dump(mode="json")
    geometry_changed["design_form"]["elements"][0]["definition"][
        "paths"
    ][0]["points"][1]["x_mm"] = 11.0

    assert spec_visual_hash(original) == spec_visual_hash(
        Spec.model_validate(metadata_changed)
    )
    assert spec_visual_hash(original) != spec_visual_hash(
        Spec.model_validate(geometry_changed)
    )


def test_dimensioned_confirmation_replaces_only_one_known_single_element():
    raw = copy.deepcopy(HALO_SPEC)
    target = _element("assembly_full", "Complete custom assembly.")
    target["role"] = "full_assembly"
    target["instance_count"] = 1
    frozen = _element("gallery_outline", "Frozen gallery outline.")
    raw["design_form"] = {"elements": [target, frozen]}
    current = Spec.model_validate(raw)

    revised = confirm_dimensioned_form_element(
        current,
        element_id="assembly_full",
        definition=DimensionedProfileDefinition.model_validate(
            _dimensioned_definition()
        ),
    )

    assert current.design_form.elements[0].definition.kind == (
        "visual_reference_only"
    )
    assert revised.design_form.elements[0].definition.kind == (
        "dimensioned_profile"
    )
    assert revised.design_form.elements[1] == current.design_form.elements[1]
    before = current.model_dump(mode="json")
    after = revised.model_dump(mode="json")
    before["design_form"]["elements"][0]["definition"] = after[
        "design_form"
    ]["elements"][0]["definition"]
    assert before == after


def test_dimensioned_confirmation_rejects_unknown_and_repeated_targets():
    raw = copy.deepcopy(HALO_SPEC)
    raw["design_form"] = {"elements": [
        _element("shoulder_pair", "Paired shoulders."),
    ]}
    current = Spec.model_validate(raw)
    definition = DimensionedProfileDefinition.model_validate(
        _dimensioned_definition()
    )

    with pytest.raises(DesignFormRevisionError) as missing:
        confirm_dimensioned_form_element(
            current,
            element_id="not_present",
            definition=definition,
        )
    assert missing.value.code == "form_element_not_found"

    with pytest.raises(DesignFormRevisionError) as repeated:
        confirm_dimensioned_form_element(
            current,
            element_id="shoulder_pair",
            definition=definition,
        )
    assert repeated.value.code == (
        "full_assembly_profile_requires_single_instance"
    )

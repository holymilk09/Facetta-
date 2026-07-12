from __future__ import annotations

from copy import deepcopy

from facetta.drawing_workflow import (
    compile_color_brief,
    compile_line_art_brief,
)
from facetta.spec import Spec


def test_line_art_brief_locks_geometry_before_color():
    brief = compile_line_art_brief("three_quarter")
    assert "exact approved ring" in brief.intent
    assert "no color fill" in " ".join(brief.style_constraints)
    assert "explicit designer confirmation" in brief.expected_output


def test_line_art_brief_uses_only_designer_selected_plate_view():
    brief = compile_line_art_brief(
        "front",
        "the face-up ring drawing in the upper-left of the plate",
    )
    assert "upper-left" in brief.intent
    assert "Do not combine" in brief.intent
    assert "do not complete" in brief.intent
    assert "do not synthesize a new camera angle" in " ".join(
        brief.style_constraints
    )
    assert "only the selected visible jewelry" in brief.expected_output


def test_color_brief_uses_spec_materials_not_visual_guess(example_spec):
    spec = Spec.model_validate(example_spec)
    brief = compile_color_brief(spec)
    assert "sapphire oval brilliant" in brief.intent
    assert "18k yellow gold" in brief.intent
    assert "add no, remove no" in " ".join(brief.style_constraints)


def test_color_brief_maps_leaf_stones_to_diamond_not_metal(example_spec):
    leaf = deepcopy(example_spec["stone"])
    leaf.update({
        "species": "diamond",
        "cut": "marquise",
        "carat": 0.015,
        "dimensions_mm": {"length": 2.5, "width": 1.3, "depth": 0.8},
        "color": {"trade": "colorless", "gia": "F"},
        "count": 12,
        "position": "pave_leaves",
    })
    example_spec["side_stones"] = [leaf]
    spec = Spec.model_validate(example_spec)
    brief = compile_color_brief(spec)
    constraints = " ".join(brief.style_constraints)
    assert "diamond-set leaf shoulders" in brief.intent
    assert "never yellow, gold, or plain metal" in constraints
    assert "never flood-fill a diamond-bearing leaf motif" in constraints

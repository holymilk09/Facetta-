"""DXF conversion preserves transformed and curved sheet geometry."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

from facetta.dxf import DxfUnsupported, svg_to_dxf
from facetta.spec import Spec
from facetta.svg_sheet import render_sheet
from facetta.validation import validate_spec
from facetta.vocabulary import get_vocabulary


def _vertices(dxf: str) -> list[tuple[float, float]]:
    return [
        (float(x), float(y))
        for x, y in re.findall(
            r"0\nVERTEX\n8\n[^\n]+\n10\n([-\d.]+)\n20\n([-\d.]+)",
            dxf,
        )
    ]


def _entity_count(dxf: str) -> int:
    return len(re.findall(r"(?:^|\n)0\n(?:LINE|CIRCLE|POLYLINE|TEXT)\n", dxf))


def test_nested_rotation_moves_ellipse_axes_in_dxf_space():
    svg = """<svg xmlns="http://www.w3.org/2000/svg">
      <g transform="translate(5 0)">
        <g transform="rotate(90 20 20)">
          <ellipse cx="20" cy="20" rx="4" ry="1"/>
        </g>
      </g>
    </svg>"""

    points = _vertices(svg_to_dxf(svg))
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]

    # Rotation swaps the 4:1 ellipse axes; the parent translation then moves
    # its center from x=20 to x=25. DXF y is the sheet-height flip of SVG y.
    assert min(xs) == 24.0
    assert max(xs) == 26.0
    assert min(ys) == 186.0
    assert max(ys) == 194.0


def test_quadratic_cubic_and_arc_segments_are_sampled_not_dropped():
    svg = """<svg xmlns="http://www.w3.org/2000/svg">
      <path d="M 10 30 Q 20 10 30 30 C 35 45 45 45 50 30
               A 8 4 25 0 1 66 30 Z"/>
    </svg>"""

    dxf = svg_to_dxf(svg)
    points = _vertices(dxf)

    assert "POLYLINE" in dxf
    assert len(points) >= 120
    # The quadratic control must bow above its endpoints in SVG space, which
    # appears at a larger y after the DXF sheet flip.
    assert max(y for _x, y in points) == 190.0
    assert min(x for x, _y in points) == 10.0
    assert max(x for x, _y in points) > 65.0


def test_unknown_transform_fails_instead_of_exporting_wrong_coordinates():
    with pytest.raises(DxfUnsupported, match="unsupported SVG transform"):
        svg_to_dxf(
            '<svg xmlns="http://www.w3.org/2000/svg">'
            '<g transform="skewX(20)"><line x1="0" y1="0" x2="1" y2="1"/>'
            '</g></svg>'
        )
    with pytest.raises(DxfUnsupported, match="unsupported SVG element <use>"):
        svg_to_dxf(
            '<svg xmlns="http://www.w3.org/2000/svg">'
            '<use href="#unexpanded-geometry"/>'
            '</svg>'
        )


def test_rotated_rounded_rect_keeps_curved_corners():
    svg = """<svg xmlns="http://www.w3.org/2000/svg">
      <rect x="10" y="10" width="20" height="8" rx="2"
            transform="rotate(30 20 14)"/>
    </svg>"""

    points = _vertices(svg_to_dxf(svg))

    assert len(points) == 36
    assert len({round(x, 2) for x, _y in points}) > 10
    assert len({round(y, 2) for _x, y in points}) > 10


def test_current_factory_templates_convert_without_silent_geometry_loss(
    example_spec,
    halo_spec,
    bangle_spec,
    cuff_spec,
    link_spec,
    pendant_spec,
    loose_spec,
    spray_spec,
):
    leaf = copy.deepcopy(example_spec)
    leaf["template"] = "leaf_shoulder_prong"
    leaf["side_stones"] = [{
        "species": "diamond",
        "cut": "marquise",
        "carat": 0.015,
        "dimensions_mm": {"length": 2.5, "width": 1.3, "depth": 0.8},
        "color": {"trade": "F Colorless", "gia": "colorless"},
        "count": 12,
        "position": "pave_leaves",
    }, {
        "species": "diamond",
        "cut": "round_brilliant",
        "carat": 0.007,
        "dimensions_mm": {"length": 1.2, "width": 1.2, "depth": 0.73},
        "color": {"trade": "F Colorless", "gia": "colorless"},
        "count": 24,
        "position": "pave_leaves",
    }]
    earring = json.loads(
        (Path(__file__).parent.parent / "docs" / "examples"
         / "marquise_drop_earring.json").read_text()
    )
    cases = (
        example_spec,
        halo_spec,
        leaf,
        bangle_spec,
        cuff_spec,
        link_spec,
        pendant_spec,
        loose_spec,
        spray_spec,
        earring,
    )

    evidence: dict[str, tuple[int, int]] = {}
    for raw in cases:
        validated = validate_spec(Spec.model_validate(raw), get_vocabulary())
        assert validated.ok, [issue.as_detail() for issue in validated.issues]
        spec = validated.spec
        svg = render_sheet(spec)
        dxf = svg_to_dxf(svg)
        vertices = _vertices(dxf)
        assert dxf.rstrip().endswith("EOF")
        assert _entity_count(dxf) > 20
        assert vertices, spec.template
        evidence[spec.template] = (_entity_count(dxf), len(vertices))

    assert set(evidence) == {
        "solitaire_prong", "halo_prong", "leaf_shoulder_prong",
        "love_bangle", "cuff", "link_bracelet", "cluster_pendant",
        "loose_stone", "leaf_spray_brooch", "deco_drop_earring",
    }
    # These two templates specifically require the commands the legacy parser
    # dropped: rotated quadratic leaves and cubic/arc drop outlines.
    assert evidence["leaf_shoulder_prong"][1] > 1_000
    assert evidence["deco_drop_earring"][1] > 400
    assert evidence["link_bracelet"][1] > 600

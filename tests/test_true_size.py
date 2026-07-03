"""The 1:1 overlay sheet: printed geometry must equal spec millimeters exactly.

The SVG root declares 1 user unit = 1 mm of paper, so these tests assert the
physical contract directly — the circle a designer lays their ring on has a
radius equal to the spec's inner diameter over two, to the hundredth of a
millimeter the renderer emits.
"""

import re

from fastapi.testclient import TestClient

from facetta.main import app
from facetta.spec import Spec
from facetta.svg_sheet import render_true_size_sheet
from facetta.validation import validate_spec
from facetta.vocabulary import get_vocabulary

client = TestClient(app)


def _render(raw: dict) -> str:
    result = validate_spec(Spec.model_validate(raw), get_vocabulary())
    assert result.ok, [i.msg for i in result.issues]
    return render_true_size_sheet(result.spec)


def _attr_values(svg: str, element: str, attr: str) -> list[float]:
    return [float(m) for m in re.findall(
        rf'<{element}[^>]* {attr}="([-\d.]+)"', svg)]


def test_paper_units_are_millimeters(example_spec):
    svg = _render(example_spec)
    root = svg.splitlines()[0]
    assert 'width="297mm"' in root and 'height="210mm"' in root
    assert 'viewBox="0 0 297 210"' in root  # 1 unit = 1 mm when printed at 100%


def test_ring_hoop_prints_at_actual_size(example_spec):
    svg = _render(example_spec)
    inner_d = example_spec["ring_size"]["inner_diameter_mm"]
    thickness = example_spec["band"]["thickness_mm"]
    radii = _attr_values(svg, "circle", "r")
    assert round(inner_d / 2, 2) in radii            # inside of the hoop
    assert round(inner_d / 2 + thickness, 2) in radii  # outside of the hoop


def test_bangle_opening_prints_at_actual_size(bangle_spec):
    svg = _render(bangle_spec)
    br = bangle_spec["bracelet"]
    rxs = _attr_values(svg, "ellipse", "rx")
    rys = _attr_values(svg, "ellipse", "ry")
    assert round(br["inner_length_mm"] / 2, 2) in rxs
    assert round(br["inner_width_mm"] / 2, 2) in rys
    # every station stone at its exact spec width
    side = bangle_spec["stone"]["dimensions_mm"]["width"]
    stations = re.findall(rf'<rect[^>]* width="{side:.2f}"', svg)
    assert len(stations) == bangle_spec["stone"]["count"]


def test_pendant_drop_prints_at_actual_size(pendant_spec):
    from facetta.validation import pendant_drop_mm

    result = validate_spec(Spec.model_validate(pendant_spec), get_vocabulary())
    assert result.ok
    svg = render_true_size_sheet(result.spec)
    drop = pendant_drop_mm(result.spec)
    # the drop dimension line spans exactly the drop, in paper mm
    ys = [(float(y1), float(y2)) for y1, y2 in re.findall(
        r'<line [^>]*y1="([-\d.]+)" x2="[-\d.]+" y2="([-\d.]+)" stroke="#8a8a8a" '
        r'stroke-width="0.15"/>', svg)]
    spans = [abs(y2 - y1) for y1, y2 in ys]
    assert any(abs(s - drop) < 0.02 for s in spans), (drop, spans)


def test_loose_stone_outline_matches_spec(loose_spec):
    svg = _render(loose_spec)
    d = loose_spec["stone"]["dimensions_mm"]
    # the face-up outline's vertical extent equals the stone's length: the
    # outline polygon's ys span exactly length mm around the baseline
    ys = []
    for pts in re.findall(r'<polygon points="([^"]+)"', svg):
        ys += [float(p.split(",")[1]) for p in pts.split()]
    assert max(ys) - min(ys) >= d["length"] - 0.05


def test_print_check_rule_is_100mm(example_spec):
    svg = _render(example_spec)
    xs = [(float(x1), float(x2)) for x1, x2 in re.findall(
        r'<line x1="([-\d.]+)" y1="[-\d.]+" x2="([-\d.]+)" y2="[-\d.]+" '
        r'stroke="#3f3f3f" stroke-width="0.3"/>', svg)]
    assert any(abs(abs(x2 - x1) - 100.0) < 1e-9 for x1, x2 in xs)
    assert "PRINT CHECK" in svg and "1:1" in svg


def test_true_size_covers_every_template(example_spec, halo_spec, bangle_spec,
                                         cuff_spec, link_spec, pendant_spec,
                                         necklace_spec, loose_spec):
    for raw in (example_spec, halo_spec, bangle_spec, cuff_spec, link_spec,
                pendant_spec, necklace_spec, loose_spec):
        svg = _render(raw)
        assert "TRUE SIZE" in svg


def test_instructions_live_in_the_corner_not_on_the_piece(example_spec):
    result = validate_spec(Spec.model_validate(example_spec), get_vocabulary())
    svg = render_true_size_sheet(result.spec)
    assert "OVERLAY GUIDE" in svg
    # every guide line is anchored at the left margin, x=14 — the outlines sit
    # at the sheet's center and right, so photos of the overlay carry no words
    guide_xs = [float(x) for x in re.findall(
        r'<text x="([\d.]+)"[^>]*>(?:OVERLAY GUIDE|[123]\.\s)', svg)]
    assert guide_xs and all(x == 14.0 for x in guide_xs)


def test_clean_sheet_for_photos(example_spec):
    result = validate_spec(Spec.model_validate(example_spec), get_vocabulary())
    clean = render_true_size_sheet(result.spec, instructions=False)
    assert "OVERLAY GUIDE" not in clean
    assert "lay the finished" not in clean
    assert "PRINT CHECK" in clean  # the calibration rule always stays


def test_true_size_endpoint(example_spec):
    response = client.post("/specs/true-size.svg", json=example_spec)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert "PRINT CHECK" in response.text and "OVERLAY GUIDE" in response.text

    clean = client.post("/specs/true-size.svg?instructions=false", json=example_spec)
    assert clean.status_code == 200
    assert "OVERLAY GUIDE" not in clean.text and "PRINT CHECK" in clean.text

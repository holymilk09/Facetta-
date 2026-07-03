"""GemCad .ASC parser and face-up reconstruction engine."""

import math

import pytest

from facetta import gemcad


def test_parse_round_brilliant_tiers():
    diagram = gemcad.parse_asc(
        (gemcad.DIAGRAM_DIR / "round_brilliant.asc").read_text())
    assert diagram.gear == 96
    sides = [t.side for t in diagram.tiers]
    assert sides == ["pavilion", "pavilion", "girdle", "crown", "crown",
                     "crown", "table"]
    mains = diagram.tiers[0]
    assert len(mains.indices) == 8
    assert mains.indices[0] == 96  # azimuth 0 sits at 12 o'clock


def test_round_brilliant_is_the_57_facet_standard():
    diagram = gemcad.parse_asc(
        (gemcad.DIAGRAM_DIR / "round_brilliant.asc").read_text())
    faces = gemcad.build_faces(diagram)
    by_side = {}
    for _, (tier_i, _) in faces:
        by_side.setdefault(diagram.tiers[tier_i].side, []).append(1)
    assert len(by_side["pavilion"]) == 24   # 8 mains + 16 lower halves
    assert len(by_side["girdle"]) == 16
    assert len(by_side["crown"]) == 32      # 8 mains + 16 halves + 8 stars
    assert len(by_side["table"]) == 1       # = 57 facets plus the girdle


@pytest.mark.parametrize("cut", ["round_brilliant", "oval_brilliant", "cushion",
                                 "princess", "emerald_cut", "asscher",
                                 "pear", "marquise", "trillion", "radiant"])
def test_bundled_diagrams_reconstruct_and_normalize(cut):
    layout = gemcad.layout_for_cut(cut)
    assert layout is not None
    xs = [x for f in layout.facets for x, _ in f.points]
    ys = [y for f in layout.facets for _, y in f.points]
    # outline spans exactly one unit in each axis, centered
    assert math.isclose(max(xs) - min(xs), 1.0, abs_tol=1e-6)
    assert math.isclose(max(ys) - min(ys), 1.0, abs_tol=1e-6)
    assert len([f for f in layout.facets if f.kind == "table"]) == 1
    assert len(layout.facets) >= 9
    for facet in layout.facets:  # crown normals all face the viewer
        assert facet.normal[2] > 0


def test_layout_is_deterministic():
    diagram = gemcad.parse_asc(
        (gemcad.DIAGRAM_DIR / "oval_brilliant.asc").read_text())
    assert gemcad.face_up_layout(diagram) == gemcad.face_up_layout(diagram)


def test_table_remap_hits_spec_percentage():
    layout = gemcad.layout_for_cut("round_brilliant")
    remapped = gemcad.remap_table(layout, 0.62)
    assert math.isclose(remapped.table_fraction, 0.62, abs_tol=1e-6)
    table = next(f for f in remapped.facets if f.kind == "table")
    assert math.isclose(2 * max(abs(x) for x, _ in table.points), 0.62,
                        abs_tol=0.005)
    assert remapped.outline == layout.outline  # girdle outline never moves


def test_unknown_cut_falls_back():
    assert gemcad.layout_for_cut("cabochon") is None  # non-faceted, no diagram


def test_asc_without_distances_fails_loudly():
    with pytest.raises(gemcad.AscUnsupported, match="re-export"):
        gemcad.parse_asc("g 96 0.\na 41.00 96 12 24\n")


def test_asc_without_girdle_fails_loudly():
    with pytest.raises(gemcad.AscUnsupported, match="girdle"):
        gemcad.parse_asc("g 96 0.\na 41.00 0.65195 96 12 24\n")


def test_sheet_uses_diagram_geometry(round_spec):
    from facetta.spec import Spec
    from facetta.svg_sheet import render_sheet

    svg = render_sheet(Spec.model_validate(round_spec))
    # the real SRB face-up carries far more facet polygons than the old
    # procedural pattern (32 crown facets + table + outline)
    assert svg.count("<polygon") >= 34


def test_real_gemcad_export_conventions():
    """oval_brilliant.asc is a genuine Robert H. Long design (Datavue2 1991):
    signed angles (negative = pavilion, even after crown lines), facet names
    interleaved between indices as `n <name>`, and index 0 meaning the gear
    top. The meetpoint proof: crown main A crosses the girdle plane exactly
    at its girdle facet's distance."""
    import math

    diagram = gemcad.parse_asc(
        (gemcad.DIAGRAM_DIR / "oval_brilliant.asc").read_text())
    assert "Long, Robert H" in diagram.header
    assert diagram.tiers[-1].side == "pavilion"      # trailing negative line
    a_tier = next(t for t in diagram.tiers if t.name == "A")
    assert a_tier.indices == (2, 46, 50, 94)          # names between indices
    girdle_a = next(t for t in diagram.tiers
                    if t.side == "girdle" and 2 in t.indices)
    crossing = a_tier.distance / math.sin(math.radians(a_tier.angle_deg))
    assert math.isclose(crossing, girdle_a.distance, abs_tol=2e-5)
    faces = gemcad.build_faces(diagram)
    crown = [1 for _, (t, _) in faces if diagram.tiers[t].side == "crown"]
    assert len(crown) == 32

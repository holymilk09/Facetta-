"""Dimensional-truth audit: ring measurements, sheet geometry, stone density.

Every number a factory reads off a Facetta output must trace back to exact mm
values in the spec. These tests check the measurement chain end to end.
"""

import re

import pytest

from facetta.density import check_density
from facetta.spec import Spec
from facetta.svg_sheet import SCALE, render_sheet
from facetta.validation import expected_inner_diameter_mm
from facetta.spec import RingSize

# Published US ring size -> inner diameter (mm) reference points
US_SIZE_REFERENCE = {
    3: 14.1,
    5: 15.7,
    6.5: 16.9,
    7: 17.3,
    9: 19.0,
    11: 20.6,
    13: 22.2,
}


class TestRingSizes:
    @pytest.mark.parametrize("size,reference_mm", sorted(US_SIZE_REFERENCE.items()))
    def test_us_size_matches_published_reference(self, size, reference_mm):
        derived = expected_inner_diameter_mm(RingSize(system="US", value=size))
        assert derived == pytest.approx(reference_mm, abs=0.1), (
            f"US {size}: derived {derived} mm vs published {reference_mm} mm"
        )

    def test_size_steps_are_uniform(self):
        # one full US size = 0.8128 mm of inner diameter (values round to 0.01)
        d3 = expected_inner_diameter_mm(RingSize(system="US", value=3))
        d13 = expected_inner_diameter_mm(RingSize(system="US", value=13))
        assert d13 - d3 == pytest.approx(10 * 0.8128, abs=0.02)


class TestSheetGeometryIsSpecTrue:
    """Parse the rendered SVG and check drawn geometry == spec mm x SCALE."""

    @pytest.fixture
    def svg(self, example_spec):
        return render_sheet(Spec.model_validate(example_spec))

    def test_stone_outline_scales_exactly(self, svg, example_spec):
        stone = example_spec["stone"]["dimensions_mm"]
        # top view stone outline (facet-diagram girdle polygon): its extents
        # must equal width x length, in mm x SCALE, exactly
        target_w = stone["width"] * SCALE
        target_l = stone["length"] * SCALE
        for match in re.finditer(r'<polygon points="([^"]+)"', svg):
            nums = [float(n) for n in re.findall(r"[-\d.]+", match.group(1))]
            xs, ys = nums[::2], nums[1::2]
            if (max(xs) - min(xs) == pytest.approx(target_w, abs=0.02)
                    and max(ys) - min(ys) == pytest.approx(target_l, abs=0.02)):
                break
        else:
            raise AssertionError("no stone outline polygon with spec extents")

    def test_hoop_inner_circle_scales_exactly(self, svg, example_spec):
        inner = example_spec["ring_size"]["inner_diameter_mm"]
        radii = [float(r) for r in re.findall(r'<circle[^>]*? r="([\d.]+)"', svg)]
        assert any(r == pytest.approx(inner / 2 * SCALE, abs=0.01) for r in radii), (
            f"no circle with r == {inner / 2 * SCALE}"
        )

    def test_band_thickness_ring_scales_exactly(self, svg, example_spec):
        inner = example_spec["ring_size"]["inner_diameter_mm"]
        thickness = example_spec["band"]["thickness_mm"]
        outer_r = (inner / 2 + thickness) * SCALE
        radii = [float(r) for r in re.findall(r'<circle[^>]*? r="([\d.]+)"', svg)]
        assert any(r == pytest.approx(outer_r, abs=0.01) for r in radii)

    def test_shank_strip_is_band_width_wide(self, svg, example_spec):
        band_w = example_spec["band"]["width_mm"] * SCALE
        match = re.search(r'<rect x="[\d.]+" y="[\d.]+" width="([\d.]+)"[^>]*url\(#hatch\)', svg)
        assert match, "hatched shank strip missing"
        assert float(match.group(1)) == pytest.approx(band_w, abs=0.01)

    def test_width_dimension_line_spans_the_stone(self, svg, example_spec):
        stone = example_spec["stone"]["dimensions_mm"]
        label = f'>{stone["width"]} mm<'
        assert label in svg
        # the dim line for width must span exactly width * SCALE
        span = stone["width"] * SCALE
        for x1, x2 in re.findall(r'<line x1="([\d.]+)" y1="[\d.]+" x2="([\d.]+)"', svg):
            if abs((float(x2) - float(x1)) - span) < 0.01:
                break
        else:
            pytest.fail(f"no horizontal line spanning {span} (= {stone['width']} mm x {SCALE})")

    def test_same_spec_same_bytes(self, example_spec):
        spec = Spec.model_validate(example_spec)
        assert render_sheet(spec) == render_sheet(spec)


class TestBlueprintAlignment:
    """Witness lines snap to vector edges; views share one horizontal baseline."""

    def _sheet(self, raw):
        from facetta.validation import validate_spec
        from facetta.vocabulary import get_vocabulary

        result = validate_spec(Spec.model_validate(raw), get_vocabulary())
        assert result.ok, [i.msg for i in result.issues]
        return render_sheet(result.spec)

    def test_witness_lines_snap_on_every_template(
        self, example_spec, halo_spec, bangle_spec, pendant_spec,
        cuff_spec, link_spec, necklace_spec, loose_spec, spray_spec,
    ):
        from support import assert_witness_lines_snap

        for name, raw in [("solitaire", example_spec), ("halo", halo_spec),
                          ("bangle", bangle_spec), ("pendant", pendant_spec),
                          ("cuff", cuff_spec), ("link_bracelet", link_spec),
                          ("necklace", necklace_spec), ("loose_stone", loose_spec),
                          ("leaf_spray", spray_spec)]:
            count = assert_witness_lines_snap(self._sheet(raw), name)
            assert count >= 6, f"{name}: expected a fully dimensioned sheet"

    def test_witness_lines_snap_on_stack_sheets(self, bangle_spec, outer_bangle_spec):
        from facetta.svg_sheet import render_stack_sheet
        from facetta.validation import nesting_clearance
        from support import assert_witness_lines_snap

        a = Spec.model_validate(outer_bangle_spec)
        b = Spec.model_validate(bangle_spec)
        svg = render_stack_sheet(a, b, nesting_clearance(a, b))
        assert_witness_lines_snap(svg, "stack_bangles")

    def test_ring_views_share_the_baseline(self, example_spec):
        from facetta.svg_sheet import BASELINE

        svg = self._sheet(example_spec)
        inner = example_spec["ring_size"]["inner_diameter_mm"] / 2 * SCALE
        # the side-profile hoop center must sit exactly on the baseline
        hoop = re.search(rf'<circle cx="[\d.]+" cy="([\d.]+)" r="{inner:.2f}"', svg)
        assert hoop and float(hoop.group(1)) == BASELINE
        # and the top view's stone outline is centered on the same baseline
        stone_w = example_spec["stone"]["dimensions_mm"]["width"] * SCALE
        for match in re.finditer(r'<polygon points="([^"]+)"', svg):
            nums = [float(n) for n in re.findall(r"[-\d.]+", match.group(1))]
            xs, ys = nums[::2], nums[1::2]
            if max(xs) - min(xs) == pytest.approx(stone_w, abs=0.02):
                assert (min(ys) + max(ys)) / 2 == pytest.approx(BASELINE, abs=0.01)
                break
        else:
            raise AssertionError("stone outline polygon not found")

    def test_datum_line_is_drawn(self, example_spec):
        assert 'stroke-dasharray="6 1.5 1 1.5"' in self._sheet(example_spec)


class TestDensityBenchmarks:
    """The stones used in the halo ring, Love-style bangle, and cluster pendant."""

    def test_quarter_carat_round_melee(self):
        # 0.25 ct round diamond ~ 4.1 mm
        result = check_density(sg=3.52, shape_factor=0.36,
                               length_mm=4.1, width_mm=4.1, depth_mm=2.5, carat=0.25)
        assert result.ok, result.message

    def test_one_carat_princess(self):
        # 1 ct princess ~ 5.5 mm square
        result = check_density(sg=3.52, shape_factor=0.46,
                               length_mm=5.5, width_mm=5.5, depth_mm=3.85, carat=1.0)
        assert result.ok, result.message

    def test_bangle_station_princess(self):
        result = check_density(sg=3.52, shape_factor=0.46,
                               length_mm=2.9, width_mm=2.9, depth_mm=2.0, carat=0.14)
        assert result.ok, result.message

    def test_emerald_cut_emerald_center(self):
        result = check_density(sg=2.72, shape_factor=0.50,
                               length_mm=9.0, width_mm=7.0, depth_mm=4.5, carat=1.9)
        assert result.ok, result.message

    def test_pendant_melee(self):
        result = check_density(sg=3.52, shape_factor=0.36,
                               length_mm=2.3, width_mm=2.3, depth_mm=1.5, carat=0.05)
        assert result.ok, result.message

    def test_round_sapphire_drop(self):
        result = check_density(sg=4.00, shape_factor=0.36,
                               length_mm=5.5, width_mm=5.5, depth_mm=3.4, carat=0.8)
        assert result.ok, result.message

    def test_oval_halo_center(self):
        # 1.5 ct oval diamond, 8.6 x 6.4 x 4.0
        result = check_density(sg=3.52, shape_factor=0.40,
                               length_mm=8.6, width_mm=6.4, depth_mm=4.0, carat=1.5)
        assert result.ok, result.message

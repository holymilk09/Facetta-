"""Leaf-spray brooch: cluster arithmetic, spray fit, and exact sheet geometry.

The fixture is the checked-in example extracted from the designer's artwork:
a terminal emerald quatrefoil, a diamond quatrefoil beside it, three emerald
quatrefoils up the branch, 110 pavé diamonds across the leaves.
"""

from pathlib import Path

import pytest

from facetta.spec import Spec
from facetta.svg_sheet import (
    SPRAY_SCALE, SheetUnsupported, _spray_layout, render_sheet,
)
from facetta.validation import CLUSTER_HUB_MM, spray_cluster_row, validate_spec
from facetta.vocabulary import get_vocabulary

GOLDEN_DIR = Path(__file__).parent / "golden"


def _validated(raw) -> Spec:
    result = validate_spec(Spec.model_validate(raw), get_vocabulary())
    assert result.ok, [i.msg for i in result.issues]
    return result.spec


def _issues(raw) -> list:
    return validate_spec(Spec.model_validate(raw), get_vocabulary()).issues


class TestSprayValidation:
    def test_example_spec_validates(self, spray_spec):
        _validated(spray_spec)

    def test_brooch_section_required(self, spray_spec):
        del spray_spec["brooch"]
        assert any(i.loc == ("brooch",) for i in _issues(spray_spec))

    def test_terminal_must_be_four_petals(self, spray_spec):
        spray_spec["stone"]["count"] = 5
        assert any("four petals" in i.msg for i in _issues(spray_spec))

    def test_stations_come_in_fours(self, spray_spec):
        spray_spec["side_stones"][1]["count"] = 13
        assert any("partial cluster" in i.msg for i in _issues(spray_spec))

    def test_center_count_matches_clusters(self, spray_spec):
        spray_spec["side_stones"][3]["count"] = 3  # 4 centers for 5 clusters
        bad = [i for i in _issues(spray_spec) if "center stones" in i.msg]
        assert bad and bad[0].expected == {"center_count": 5}

    def test_cluster_row_must_fit_the_spray(self, spray_spec):
        spray_spec["brooch"]["length_mm"] = 50.0
        bad = [i for i in _issues(spray_spec) if i.loc == ("brooch", "length_mm")]
        assert bad and bad[0].expected["min_length_mm"] > 50

    def test_terminal_needs_leaf_room(self, spray_spec):
        spray_spec["brooch"]["width_mm"] = 18.0  # terminal alone is 15.6
        assert any(i.loc == ("brooch", "width_mm") for i in _issues(spray_spec))


class TestSprayGeometry:
    def test_cluster_row_from_spec(self, spray_spec):
        spec = _validated(spray_spec)
        row = spray_cluster_row(spec)
        assert len(row) == 5  # terminal + diamond + three emerald
        assert row[0][1] == 2 * 7.0 + CLUSTER_HUB_MM  # 15.6 mm terminal
        assert row[1][0].species == "diamond"  # spec order: diamond at the tip side
        assert all(d == 2 * 5.0 + CLUSTER_HUB_MM for _, d in row[1:])

    def test_layout_extents_are_the_spec_extents(self, spray_spec):
        spec = _validated(spray_spec)
        lay = _spray_layout(spec)
        terminal_x, _, terminal_d, _ = lay["clusters"][0]
        assert terminal_x - terminal_d / 2 == 0.0  # tip at x = 0
        assert lay["catch"][0] + 2.0 == lay["length"]  # catch closes the reach
        assert round(lay["bottom"] - lay["y_top"], 6) == lay["width"]

    def test_every_pave_stone_is_drawn(self, spray_spec):
        spec = _validated(spray_spec)
        lay = _spray_layout(spec)
        stones = [s for leaf in lay["leaves"] for s in leaf["stones"]]
        assert len(stones) == 110
        assert all(r == 0.65 for _, _, r in stones)  # 1.3 mm melee

    def test_clusters_hang_from_the_stem(self, spray_spec):
        from facetta.svg_sheet import _bezier_t_at_x, _bezier_xy

        spec = _validated(spray_spec)
        lay = _spray_layout(spec)
        for x, y, d, _ in lay["clusters"]:
            stem_y = _bezier_xy(*lay["stem"], _bezier_t_at_x(*lay["stem"], x))[1]
            assert y - d / 2 <= stem_y + 1.0  # top edge kisses the branch

    def test_sheet_matches_golden(self, spray_spec):
        svg = render_sheet(_validated(spray_spec))
        golden = GOLDEN_DIR / "leaf_spray_sheet.svg"
        assert golden.exists(), f"golden file missing: {golden}"
        assert svg == golden.read_text(), (
            "sheet no longer matches leaf_spray_sheet.svg — if the change is "
            "intentional, regenerate the golden file and review the visual diff"
        )

    def test_exact_dimension_callouts_present(self, spray_spec):
        svg = render_sheet(_validated(spray_spec))
        for text in (">85 mm<",      # overall reach
                     ">32 mm<",      # overall width
                     ">15.6 mm<",    # terminal cluster diameter
                     ">3.5 mm<",     # terminal petal depth (end section)
                     ">7 mm<"):      # terminal petal length (end section)
            assert text in svg, f"missing callout {text}"

    def test_length_dimension_spans_true_scale(self, spray_spec):
        spec = _validated(spray_spec)
        lay = _spray_layout(spec)
        assert lay["length"] * SPRAY_SCALE == 170.0  # 85 mm at 2:1

    def test_sheet_is_byte_stable(self, spray_spec):
        spec = _validated(spray_spec)
        assert render_sheet(spec) == render_sheet(spec)

    def test_overlong_spray_fails_loudly(self, spray_spec):
        spray_spec["brooch"]["length_mm"] = 120.0
        with pytest.raises(SheetUnsupported, match="105 mm"):
            render_sheet(Spec.model_validate(spray_spec))


class TestSprayPipeline:
    def test_control_image_covers_the_template(self, spray_spec):
        from facetta.plate import render_control_image

        svg = render_control_image(_validated(spray_spec))
        assert "<text" not in svg  # control images never letter

    def test_presentation_plate_covers_the_template(self, spray_spec):
        from facetta.plate import render_presentation_plate

        svg = render_presentation_plate(_validated(spray_spec))
        assert "Leaf Spray Brooch" in svg and "85 mm across" in svg

    def test_fidelity_checklist_pins_the_cluster_count(self, spray_spec):
        from facetta.mockup import fidelity_checklist

        checks = fidelity_checklist(_validated(spray_spec))
        assert any("EXACTLY 5 quatrefoil clusters" in c for c in checks)

    def test_fingerprint_tracks_the_spray_footprint(self, spray_spec):
        from facetta.mockup import geometry_fingerprint

        spec = _validated(spray_spec)
        resized = spec.model_copy(update={
            "brooch": spec.brooch.model_copy(update={"length_mm": 90.0})})
        assert geometry_fingerprint(spec) != geometry_fingerprint(resized)

    def test_sheet_endpoint_serves_the_template(self, spray_spec):
        from fastapi.testclient import TestClient

        from facetta.main import app

        response = TestClient(app).post("/specs/sheet.svg", json=spray_spec)
        assert response.status_code == 200
        assert "LEAF SPRAY BROOCH" in response.text

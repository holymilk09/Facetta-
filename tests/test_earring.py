"""The articulated drop earring: the first vertical archetype, built from a
description and drawn as a native dimensioned sheet.

Covers origination (a sparse earring read becomes a valid deco_drop_earring),
the drawn sheet (every part lettered from the spec), the golden byte-stability,
and the validator's drop-specific rules.
"""

import json
import os
from pathlib import Path

import pytest

from facetta.concept import DesignRead, complete_design
from facetta.spec import Drop, Spec
from facetta.svg_sheet import SheetUnsupported, render_sheet
from facetta.validation import validate_spec
from facetta.vocabulary import get_vocabulary

VOCAB = get_vocabulary()
GOLDEN_DIR = Path(__file__).parent / "golden"
EXAMPLE = Path(__file__).parent.parent / "docs" / "examples" / "marquise_drop_earring.json"


def _example_spec() -> Spec:
    return Spec.model_validate(json.loads(EXAMPLE.read_text()))


class TestOrigination:
    def test_earring_read_becomes_a_drop_archetype(self):
        read = DesignRead(jewelry_type="earring", halo=True, species="diamond",
                          cut="marquise", center_length_mm=14, center_width_mm=9,
                          metal_material="gold", metal_color="yellow")
        spec, corrections = complete_design(read, "marquise drop earring")
        assert validate_spec(spec, VOCAB).ok
        assert spec.template == "deco_drop_earring"
        assert spec.drop is not None and spec.drop.overall_length_mm > 0
        # frame + pavé halo + pear drop + bezel accent all present
        cuts = {s.cut for s in [spec.stone, *spec.side_stones]}
        assert spec.stone.cut == "marquise" and "pear" in cuts
        positions = {s.position for s in spec.side_stones}
        assert {"halo", "drop", "stations"} <= positions
        assert any("halo sized" in c for c in corrections)

    def test_non_earring_still_builds_a_ring(self):
        read = DesignRead(jewelry_type="ring", species="diamond", cut="round",
                          center_length_mm=6.5, center_width_mm=6.5,
                          metal_material="platinum")
        spec, _ = complete_design(read, "solitaire")
        assert spec.jewelry_type == "ring" and spec.drop is None


class TestSheet:
    def test_sheet_draws_and_letters_the_earring(self):
        svg = render_sheet(_example_spec())
        assert "DROP EARRING" in svg
        assert "mm overall" in svg          # the overall reach is dimensioned
        assert "mm frame" in svg            # the frame L×W is dimensioned
        assert "pavé halo" in svg           # the pavé count is lettered
        assert "FRONT VIEW" in svg

    def test_sheet_matches_golden(self):
        svg = render_sheet(_example_spec())
        golden = GOLDEN_DIR / "marquise_drop_earring_sheet.svg"
        if os.environ.get("FACETTA_REGEN_GOLDEN"):
            golden.write_text(svg)
            return
        assert golden.exists(), f"golden file missing: {golden}"
        assert svg == golden.read_text(), (
            "drop-earring sheet changed — if intentional, regenerate the golden")


class TestRenderAsSheet:
    """The render IS the sheet: the actual image is the drawing, code letters
    the validated drop dimensions beside it — so it matches the render."""

    def _png(self) -> bytes:
        import io

        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (600, 900), (210, 205, 198)).save(buf, format="PNG")
        return buf.getvalue()

    def test_overlay_letters_the_drop_dimensions(self):
        from facetta.overlay import render_annotated_artwork

        svg = render_annotated_artwork(_example_spec(), self._png())
        assert "overall length" in svg          # the drop's real reach
        assert "hook" in svg and "pavé halo" in svg
        assert "wall" in svg and "wire" in svg
        # a drop's dims live in the column, so no "could not be traced" note
        assert "could not be traced" not in svg
        assert "pending designer" not in svg


class TestValidation:
    def test_drop_section_is_required(self):
        raw = json.loads(EXAMPLE.read_text())
        raw.pop("drop")
        result = validate_spec(Spec.model_validate(raw), VOCAB)
        assert not result.ok
        assert any("drop section" in i.msg for i in result.issues)

    def test_overall_length_must_contain_hook_and_frame(self):
        spec = _example_spec()
        # a 14 mm frame under a 10 mm hook cannot live in 18 mm of reach
        spec.drop = Drop(hook_height_mm=10, overall_length_mm=18,
                         link_count=3, link_pitch_mm=2.4)
        result = validate_spec(spec, VOCAB)
        assert not result.ok
        assert any(i.expected and "min_overall_length_mm" in i.expected
                   for i in result.issues)

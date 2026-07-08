"""The official Facetta frame: code letters identity from the record.

No network anywhere — frame_technical_drawing is pure code over bytes. The
points under test: orientation follows the drawing, the masthead and subtitle
speak for the platform (or the designer's house), the footer letters only
what the record states, and an unsaved drawing gets honest placeholders —
never an invented name, reference, or date.
"""

import io
import json
from pathlib import Path

import pytest
from PIL import Image

from facetta.drawing_frame import DISCLAIMER, frame_technical_drawing
from facetta.spec import Spec
from facetta.svg_sheet import Branding


def _png(w: int, h: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (255, 255, 255)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def drop_spec() -> Spec:
    path = (Path(__file__).parent.parent / "docs" / "examples"
            / "marquise_drop_earring.json")
    return Spec.model_validate(json.loads(path.read_text()))


class TestFrameTechnicalDrawing:
    def test_portrait_drawing_gets_a_portrait_page(self):
        svg = frame_technical_drawing(_png(600, 900))
        assert 'viewBox="0 0 210 297"' in svg

    def test_landscape_drawing_gets_a_landscape_page(self):
        svg = frame_technical_drawing(_png(900, 600))
        assert 'viewBox="0 0 297 210"' in svg

    def test_default_frame_speaks_for_facetta_with_placeholders(self):
        svg = frame_technical_drawing(_png(600, 900))
        assert "FACETTA" in svg
        assert "MANUFACTURING TECHNICAL DRAWING — dsn_pending · v1" in svg
        assert DISCLAIMER in svg
        assert "CONFIDENTIAL — FACTORY PRODUCTION ONLY" in svg
        assert 'preserveAspectRatio="xMidYMid meet"' in svg
        assert "data:image/png;base64," in svg           # the drawing rides in
        assert "SIGNED" not in svg                       # no mark supplied

    def test_spec_letters_identity_and_description(self, drop_spec):
        svg = frame_technical_drawing(_png(600, 900), spec=drop_spec)
        assert (f"MANUFACTURING TECHNICAL DRAWING — {drop_spec.design_id} "
                f"· v{drop_spec.version}") in svg
        assert "3.83 ct Diamond" in svg                  # description line
        assert "marquise" in svg
        assert "18k Yellow Gold" in svg
        assert f"designer {drop_spec.created_by}" in svg
        assert drop_spec.created_at.date().isoformat() in svg

    def test_branding_letters_the_house_and_signature(self, drop_spec):
        svg = frame_technical_drawing(
            _png(600, 900), spec=drop_spec,
            branding=Branding(house="Maison Vérité", signature="Ana Vérité"))
        assert "Maison Vérité" in svg                    # the masthead
        assert "made with FACETTA" in svg                # the maker's mark stays
        assert "Ana Vérité" in svg
        assert "SIGNED" in svg

    def test_specification_panel_letters_the_stone_schedule(self, drop_spec):
        # each stone's count, size, and type + the total set weight, plus the
        # materials & dimensions block — the factory's "what is this made of"
        svg = frame_technical_drawing(_png(1000, 560), spec=drop_spec)
        assert "STONE SCHEDULE" in svg
        assert "TOTAL SET WEIGHT" in svg
        assert "MATERIALS &amp; DIMENSIONS" in svg
        # the qty column carries each stone's count (the melee group > 1)
        assert max(s.count for s in [drop_spec.stone] + drop_spec.side_stones) > 1
        assert "TOLERANCE" in svg and "UNITS" in svg
        assert "DROP LENGTH" in svg              # the earring's own measurement

    def test_panel_is_well_formed_xml(self, drop_spec):
        import xml.etree.ElementTree as ET
        ET.fromstring(frame_technical_drawing(_png(1000, 560), spec=drop_spec))

    def test_unsaved_frame_has_no_specification_panel(self):
        # nothing to letter without a record — no invented schedule
        svg = frame_technical_drawing(_png(1000, 560))
        assert "STONE SCHEDULE" not in svg
        assert "unsaved drawing — pending record" in svg

    def test_optional_piece_name_letters_the_masthead(self, drop_spec):
        svg = frame_technical_drawing(_png(1000, 560), spec=drop_spec,
                                      piece_name="The Vérité Drop")
        assert "The Vérité Drop" in svg
        # still shows the id subtitle underneath as the unambiguous reference
        assert f"— {drop_spec.design_id} · v{drop_spec.version}" in svg

    def test_piece_name_is_escaped(self, drop_spec):
        import xml.etree.ElementTree as ET
        svg = frame_technical_drawing(_png(1000, 560), spec=drop_spec,
                                      piece_name="Ana & Co <Signature>")
        ET.fromstring(svg)
        assert "Ana &amp; Co" in svg

    def test_xml_special_characters_are_escaped_not_broken(self, drop_spec):
        # 'Smith & Co' must letter the masthead, not break the XML: every
        # record- or branding-derived string is escaped before it reaches
        # a <text> element, so the frame always parses.
        import xml.etree.ElementTree as ET

        svg = frame_technical_drawing(
            _png(600, 900), spec=drop_spec,
            branding=Branding(house="Smith & Co",
                              signature="A. <Smith> & Co"))
        ET.fromstring(svg)                               # well-formed XML
        assert "Smith &amp; Co" in svg
        assert "Smith & Co</text>" not in svg            # never raw

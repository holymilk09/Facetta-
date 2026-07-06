"""Blueprint sheet: the engine paints the views, code letters the numbers.

The master line-art sheet stays the dimensional source of truth; this proves
the presentation twin keeps the geometry/annotation split honest — geometry
carries zero lettering, the composite carries every number from the record.
"""

import base64
import json
from pathlib import Path

import pytest

from facetta.spec import Spec
from facetta.svg_sheet import (
    SheetUnsupported, render_blueprint_frame, render_sheet,
    render_sheet_geometry,
)
from facetta.validation import validate_spec
from facetta.vocabulary import get_vocabulary

EXAMPLES = Path(__file__).parent.parent / "docs" / "examples"


def _ruby() -> Spec:
    raw = json.loads((EXAMPLES / "ruby_sunburst_ring.json").read_text())
    result = validate_spec(Spec.model_validate(raw), get_vocabulary())
    assert result.ok, [i.msg for i in result.issues]
    return result.spec


class TestLayerSplit:
    def test_geometry_carries_no_lettering(self):
        svg = render_sheet_geometry(_ruby())
        assert "<text" not in svg              # no lettering at all
        assert " mm<" not in svg               # no dimension labels leaked
        assert "<polygon" in svg or "<circle" in svg  # but the piece is drawn

    def test_master_unchanged_is_the_contract(self):
        # the goldens enforce byte-stability; here we assert the master still
        # letters while geometry does not — the split didn't blur the two
        spec = _ruby()
        assert "TOTAL SET WEIGHT" in render_sheet(spec)
        assert "TOTAL SET WEIGHT" not in render_sheet_geometry(spec)

    def test_blueprint_frame_letters_over_the_painting(self):
        img = '<image x="0" y="0" width="297" height="210" href="data:image/png;base64,AAAA"/>'
        svg = render_blueprint_frame(_ruby(), img)
        assert img in svg                       # the painted views sit behind
        assert 'fill="url(#grid)"' not in svg   # the painting IS the paper
        assert ">4.03<" in svg and ">⌀ 16.9 mm<" in svg  # our numbers on top
        assert "GEMSTONE KEY &amp; PRODUCTION NOTES" in svg
        assert ">5.33<" in svg                  # true total set weight

    def test_blueprint_refuses_non_ring_templates(self):
        raw = json.loads((EXAMPLES / "leaf_spray_brooch.json").read_text())
        spec = validate_spec(Spec.model_validate(raw), get_vocabulary()).spec
        with pytest.raises(SheetUnsupported, match="blueprint covers"):
            render_sheet_geometry(spec)


class TestBlueprintStyle:
    def test_blueprint_is_a_controlled_style(self):
        from facetta.mockup import ARTWORK_STYLES, compile_artwork_restyle_request

        assert "blueprint" in ARTWORK_STYLES
        body = compile_artwork_restyle_request("blueprint")
        assert "graphite" in body["instruction"]
        assert "engineering projection" in body["instruction"]
        assert "add NO text" in body["instruction"]  # inherits the no-lettering guard


class TestBlueprintPipeline:
    def test_paints_geometry_then_letters(self, monkeypatch):
        import facetta.blueprint as bp

        captured = {}

        def fake_restyle(image_bytes, media_type="image/jpeg",
                         style="rendered_color", model="grok_imagine"):
            captured["style"] = style
            captured["bytes"] = image_bytes
            return b"\x89PNG\r\n\x1a\npainted", False

        monkeypatch.setattr(bp, "restyle_artwork", fake_restyle)
        svg, cached = bp.render_blueprint_sheet(_ruby())
        assert captured["style"] == "blueprint"
        assert captured["bytes"][:8] == b"\x89PNG\r\n\x1a\n"  # our geometry raster
        assert base64.b64encode(b"\x89PNG\r\n\x1a\npainted").decode() in svg
        assert ">4.03<" in svg and not cached

    def test_endpoint_no_key_is_503(self, monkeypatch, tmp_path):
        from fastapi.testclient import TestClient

        import facetta.render as render_mod
        from facetta.main import app

        monkeypatch.setattr(render_mod, "CACHE_DIR", tmp_path)
        monkeypatch.setattr(render_mod, "_provider_key", lambda env: None)
        raw = json.loads((EXAMPLES / "ruby_sunburst_ring.json").read_text())
        response = TestClient(app).post("/specs/blueprint-sheet.svg", json=raw)
        assert response.status_code == 503

    def test_endpoint_non_ring_is_422(self):
        from fastapi.testclient import TestClient

        from facetta.main import app

        raw = json.loads((EXAMPLES / "leaf_spray_brooch.json").read_text())
        response = TestClient(app).post("/specs/blueprint-sheet.svg", json=raw)
        assert response.status_code == 422
        assert "blueprint covers" in response.json()["detail"]

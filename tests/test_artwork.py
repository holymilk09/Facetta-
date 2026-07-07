"""Artwork-first rendering: restyle-in-place instructions, caching, the
pixel-anchor trace, and the code-lettered overlay.

The design under test splits the work the constitution demands: the engine
restyles pixels in place (never recomposing, never lettering), and code
draws every number on the page from the validated spec.
"""

import base64
import io

import pytest
from PIL import Image, ImageDraw

from facetta.mockup import ARTWORK_STYLES, SceneUnsupported, \
    compile_artwork_restyle_request
from facetta.render import _sniff_media_type, artwork_cache_key
from facetta.spec import Spec
from facetta.trace import trace_spray, trace_spray_detailed
from facetta.validation import validate_spec
from facetta.vocabulary import get_vocabulary


def _synthetic_page(size=(700, 500)) -> Image.Image:
    """The TestTrace drawing: a graduated green quatrefoil chain with a
    double gap for the white cluster and a gold foliage tail."""
    im = Image.new("RGB", size, (242, 235, 216))
    d = ImageDraw.Draw(im)
    sx, sy = size[0] / 700, size[1] / 500
    chain = [(100, 400, 34), (225, 345, 28), (290, 313, 26), (355, 288, 24)]
    for cx, cy, r in chain:
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            d.ellipse((sx * (cx + dx * r * 0.55 - r * 0.6),
                       sy * (cy + dy * r * 0.55 - r * 0.6),
                       sx * (cx + dx * r * 0.55 + r * 0.6),
                       sy * (cy + dy * r * 0.55 + r * 0.6)),
                      fill=(0, 150, 60))
    d.line((sx * 355, sy * 288, sx * 640, sy * 175),
           fill=(180, 140, 40), width=max(4, round(18 * sx)))
    return im


def _png_bytes(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


class TestRestyleInstruction:
    def test_instruction_locks_composition(self):
        body = compile_artwork_restyle_request("rendered_color")
        for clause in ("IN PLACE", "Do NOT add, remove, move",
                       "do NOT render the piece only once"):
            assert clause in body["instruction"]

    def test_instruction_bans_lettering(self):
        body = compile_artwork_restyle_request("ink_lineart")
        assert "add NO text" in body["instruction"]
        for banned in ("text", "numbers", "handwriting", "dimensions", "callouts"):
            assert banned in body["negative_prompt"]

    def test_styles_are_a_controlled_vocabulary(self):
        color = compile_artwork_restyle_request("rendered_color")["instruction"]
        ink = compile_artwork_restyle_request("ink_lineart")["instruction"]
        assert color != ink
        with pytest.raises(SceneUnsupported) as err:
            compile_artwork_restyle_request("watercolor")
        assert err.value.valid == sorted(ARTWORK_STYLES)


class TestArtworkCache:
    def test_key_tracks_bytes_style_and_model(self):
        a = artwork_cache_key(b"page-one", "rendered_color", "grok_imagine")
        assert a == artwork_cache_key(b"page-one", "rendered_color", "grok_imagine")
        assert a != artwork_cache_key(b"page-two", "rendered_color", "grok_imagine")
        assert a != artwork_cache_key(b"page-one", "ink_lineart", "grok_imagine")
        assert a != artwork_cache_key(b"page-one", "rendered_color", "grok_direct")


class TestRestylePipeline:
    def test_provider_gets_the_artwork_then_cache(self, tmp_path, monkeypatch):
        import facetta.render as render_mod

        monkeypatch.setattr(render_mod, "CACHE_DIR", tmp_path)
        monkeypatch.setattr(render_mod, "_provider_key", lambda env: "k")
        calls = []

        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"images": [{"url": "data:image/png;base64,"
                                    + base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode()}]}

        def fake_post(url, json=None, timeout=None, headers=None):
            calls.append(json)
            return FakeResponse()

        import httpx
        monkeypatch.setattr(httpx, "post", fake_post)

        img, cached = render_mod.restyle_artwork(b"artwork-bytes", "image/jpeg",
                                                 "rendered_color", "grok_imagine")
        assert not cached and img.startswith(b"\x89PNG")
        sent = calls[0]["image_urls"][0]
        assert sent == ("data:image/jpeg;base64,"
                        + base64.b64encode(b"artwork-bytes").decode())
        assert "IN PLACE" in calls[0]["prompt"]

        img2, cached2 = render_mod.restyle_artwork(b"artwork-bytes", "image/jpeg",
                                                   "rendered_color", "grok_imagine")
        assert cached2 and img2 == img and len(calls) == 1

    def test_no_key_is_503(self, tmp_path, monkeypatch):
        from fastapi.testclient import TestClient

        import facetta.render as render_mod
        from facetta.main import app

        monkeypatch.setattr(render_mod, "CACHE_DIR", tmp_path)
        monkeypatch.setattr(render_mod, "_provider_key", lambda env: None)
        response = TestClient(app).post(
            "/specs/artwork-restyle.png",
            json={"image_base64": base64.b64encode(b"x").decode()})
        assert response.status_code == 503

    def test_unknown_style_is_422_with_options(self):
        from fastapi.testclient import TestClient

        from facetta.main import app

        response = TestClient(app).post(
            "/specs/artwork-restyle.png",
            json={"image_base64": base64.b64encode(b"x").decode(),
                  "style": "gouache"})
        assert response.status_code == 422
        assert response.json()["valid_options"] == sorted(ARTWORK_STYLES)

    def test_sniff_media_type(self):
        assert _sniff_media_type(b"\xff\xd8\xff\xe0rest") == "image/jpeg"
        assert _sniff_media_type(b"\x89PNG\r\n\x1a\nrest") == "image/png"
        assert _sniff_media_type(b"RIFF1234WEBPrest") == "image/webp"


class TestTraceDetailed:
    def test_detailed_matches_normalized(self, tmp_path):
        path = tmp_path / "page.png"
        _synthetic_page().save(path)
        detailed = trace_spray_detailed(str(path))
        assert detailed.clusters == trace_spray(str(path))["clusters"]
        assert detailed.image_size == (700, 500)

    def test_px_anchors_are_original_scale(self, tmp_path):
        path = tmp_path / "big.png"
        _synthetic_page((1400, 1000)).save(path)  # forces the 720px downscale
        detailed = trace_spray_detailed(str(path))
        assert detailed.image_size == (1400, 1000)
        tip = detailed.clusters_px[0]
        assert abs(tip[0] - 200) < 8 and abs(tip[1] - 800) < 8

    def test_accepts_file_like(self):
        detailed = trace_spray_detailed(io.BytesIO(_png_bytes(_synthetic_page())))
        assert len(detailed.clusters_px) == 5  # incl. the inferred white slot


class TestAnnotatedOverlay:
    def _spec_with_five_clusters(self, spray_spec) -> Spec:
        """The synthetic page traces 5 clusters; trim the example spec (6)
        to match: one fewer emerald station, one fewer center."""
        stations = [s for s in spray_spec["side_stones"]
                    if s["position"] == "quatrefoil_stations"]
        spray_spec["side_stones"].remove(stations[-1])
        for s in spray_spec["side_stones"]:
            if s["position"] == "quatrefoil_centers" and s["count"] > 1:
                s["count"] -= 1
        comp = spray_spec["composition"]
        comp["clusters"] = comp["clusters"][:5]
        comp["vein"] = comp["vein"][:5]
        result = validate_spec(Spec.model_validate(spray_spec), get_vocabulary())
        assert result.ok, [i.msg for i in result.issues]
        return result.spec

    def test_overlay_embeds_raster_and_real_numbers(self, spray_spec):
        from facetta.overlay import render_annotated_artwork

        spec = self._spec_with_five_clusters(spray_spec)
        svg = render_annotated_artwork(spec, _png_bytes(_synthetic_page()))
        assert "data:image/png;base64," in svg
        assert "A — ⌀ 13.8" in svg          # terminal callout, spec truth
        assert "overall 85 × 62" in svg      # brooch dims, spec truth
        assert "±0.1" in svg                 # vocabulary tolerance, not code
        assert "STONE SCHEDULE" in svg

    def test_cluster_count_mismatch_strict_refuses(self, spray_spec):
        from facetta.overlay import OverlayUnsupported, render_annotated_artwork

        spec = validate_spec(Spec.model_validate(spray_spec),
                             get_vocabulary()).spec  # 6 clusters vs 5 traced
        page = _png_bytes(_synthetic_page())
        # an explicit anchor image asserts traceability: mismatch refuses
        with pytest.raises(OverlayUnsupported, match="lettered honestly"):
            render_annotated_artwork(spec, page, anchor_image_bytes=page)

    def test_cluster_count_mismatch_degrades_without_anchor(self, spray_spec):
        from facetta.overlay import render_annotated_artwork

        spec = validate_spec(Spec.model_validate(spray_spec),
                             get_vocabulary()).spec
        svg = render_annotated_artwork(spec, _png_bytes(_synthetic_page()))
        assert "callouts omitted" in svg
        assert "STONE SCHEDULE" in svg  # the numbers always letter

    def test_endpoint_round_trip(self, spray_spec):
        from fastapi.testclient import TestClient

        from facetta.main import app

        spec = self._spec_with_five_clusters(spray_spec)
        client = TestClient(app)
        good = client.post("/specs/annotated-artwork.svg", json={
            "spec": spec.model_dump(mode="json"),
            "image_base64": base64.b64encode(_png_bytes(_synthetic_page())).decode(),
        })
        assert good.status_code == 200
        assert good.headers["content-type"].startswith("image/svg+xml")
        bad = client.post("/specs/annotated-artwork.svg", json={
            "spec": spec.model_dump(mode="json"),
            "image_base64": "not-base64!!",
        })
        assert bad.status_code == 422


class TestGenericOverlay:
    def _drop_image(self) -> bytes:
        """A deco-drop-like render: a blue rectangle center, green rounds
        above (graduated line) and below (crescent)."""
        im = Image.new("RGB", (500, 900), (120, 120, 120))
        d = ImageDraw.Draw(im)
        for cy, r in ((120, 30), (200, 16), (250, 16)):  # line, graduated
            d.ellipse((250 - r, cy - r, 250 + r, cy + r), fill=(0, 150, 60))
        d.rectangle((175, 320, 325, 560), fill=(185, 220, 235))  # aquamarine
        for cx in (200, 300):  # crescent pair
            d.ellipse((cx - 18, 610, cx + 18, 646), fill=(0, 150, 60))
        return _png_bytes(im)

    def _drop_spec(self) -> Spec:
        import json
        from pathlib import Path

        path = Path(__file__).parent.parent / "docs" / "examples" / "deco_drop_earring.json"
        raw = json.loads(path.read_text())
        # match the synthetic image: 1 + 2 line stones, 2 crescent stones
        raw["side_stones"][1]["count"] = 2
        raw["side_stones"][3]["count"] = 2
        del raw["side_stones"][2]  # no crescent center in the synthetic
        result = validate_spec(Spec.model_validate(raw), get_vocabulary())
        assert result.ok, [i.msg for i in result.issues]
        return result.spec

    def test_masthead_brands_the_sheet(self):
        from facetta.overlay import render_annotated_artwork

        svg = render_annotated_artwork(self._drop_spec(), self._drop_image())
        assert "FACETTA" in svg and "FACTORY SHEET" in svg

    def test_trace_stones_classes_and_order(self, tmp_path):
        from facetta.trace import trace_stones

        anchors = trace_stones(io.BytesIO(self._drop_image()))
        assert [a.color_class for a in anchors] == \
            ["green", "green", "green", "blue", "green", "green"]
        assert [a.y for a in anchors] == sorted(a.y for a in anchors)

    def test_generic_callouts_letter_real_numbers(self):
        from facetta.overlay import render_annotated_artwork

        svg = render_annotated_artwork(self._drop_spec(), self._drop_image())
        assert "A — 16 × 12" in svg      # the aquamarine, spec truth
        assert "B — ⌀ 4.7" in svg        # the big line stone
        assert "center stone 16 × 12 × 8" in svg
        assert "overall length" in svg   # the drop's reach, lettered from the spec
        assert "±0.1" in svg

    def test_untraceable_drop_degrades_silently(self):
        # a drop's dimensions live in the column, so an untraceable render just
        # loses its leader lines — no error note, the record still carries it
        from facetta.overlay import render_annotated_artwork

        blank = Image.new("RGB", (400, 400), (128, 128, 128))
        svg = render_annotated_artwork(self._drop_spec(), _png_bytes(blank))
        assert "callouts omitted" not in svg
        assert "STONE SCHEDULE" in svg and "overall length" in svg

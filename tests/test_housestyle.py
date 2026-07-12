"""House-style anchoring: a curated reference image rides as a SECOND input
on the multi-image edit route with a strict style-only rule. Under test: the
payload carries both images, the rule reaches the instruction, the style
bytes move the cache key (the stale-cache lesson), single-image engines fail
LOUDLY instead of silently pretending, and the endpoints route a house-style
request to the multi-image engine."""

import base64
import io

import pytest
from PIL import Image

import facetta.render as render_mod
from facetta.housestyle import default_style_ref, list_style_refs
from facetta.render import (
    MASK_GUIDE_RULE, RenderUnavailable, STYLE_REF_RULE, edit_image,
    supports_style_ref,
)


def _png(color) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buf, format="PNG")
    return buf.getvalue()


SOURCE = _png((10, 10, 10))
STYLE = _png((200, 180, 40))
MASK = _png((255, 255, 255))


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(render_mod, "CACHE_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def engine_spy(monkeypatch):
    """Capture the exact payload the fal route would send."""
    calls = []

    class FakeResponse:
        status_code = 200
        def raise_for_status(self):
            pass
        def json(self):
            return {"images": [{"url": "data:image/png;base64,"
                                + base64.b64encode(b"edited").decode()}]}

    def fake_post(url, json=None, timeout=None, headers=None):
        calls.append({"url": url, "payload": json})
        return FakeResponse()

    import httpx
    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setenv("FAL_KEY", "test-key")
    return calls


class TestSupport:
    def test_only_the_multi_image_route_carries_style(self):
        assert supports_style_ref("grok_imagine") is True
        assert supports_style_ref("grok_direct") is True
        assert supports_style_ref("flux_kontext") is False


class TestEditImageWithStyle:
    def test_style_rides_as_the_second_image_with_the_rule(self, cache,
                                                           engine_spy):
        edit_image(SOURCE, "widen the band", "grok_imagine", style_ref=STYLE)
        payload = engine_spy[0]["payload"]
        assert len(payload["image_urls"]) == 2         # design + style ref
        assert payload["image_urls"][0] != payload["image_urls"][1]
        assert STYLE_REF_RULE in payload["prompt"]
        assert "never copy stones" in payload["prompt"]

    def test_no_style_means_one_image_and_no_rule(self, cache, engine_spy):
        edit_image(SOURCE, "widen the band", "grok_imagine")
        payload = engine_spy[0]["payload"]
        assert len(payload["image_urls"]) == 1
        assert STYLE_REF_RULE not in payload["prompt"]

    def test_style_bytes_move_the_cache_key(self, cache, engine_spy):
        edit_image(SOURCE, "x", "grok_imagine", style_ref=STYLE)
        edit_image(SOURCE, "x", "grok_imagine", style_ref=_png((5, 99, 5)))
        edit_image(SOURCE, "x", "grok_imagine")
        assert len(engine_spy) == 3                    # three distinct keys
        # and the same style is served from cache, once paid
        _, cached = edit_image(SOURCE, "x", "grok_imagine", style_ref=STYLE)
        assert cached is True and len(engine_spy) == 3

    def test_single_image_engine_fails_loudly(self, cache):
        with pytest.raises(RenderUnavailable, match="grok_direct"):
            edit_image(SOURCE, "x", "flux_kontext", style_ref=STYLE)

    def test_empty_style_ref_is_refused(self, cache):
        with pytest.raises(RenderUnavailable, match="empty"):
            edit_image(SOURCE, "x", "grok_imagine", style_ref=b"")


class TestMaskGuide:
    def test_direct_grok_receives_source_then_guide(self, cache, monkeypatch):
        calls = []

        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"data": [{"b64_json": base64.b64encode(
                    b"edited").decode()}]}

        def fake_post(url, json=None, timeout=None, headers=None):
            calls.append(json)
            return FakeResponse()

        import httpx
        monkeypatch.setattr(httpx, "post", fake_post)
        monkeypatch.setenv("XAI_KEY", "test-key")

        edit_image(SOURCE, "widen only the band", "grok_direct",
                   mask_bytes=MASK)
        payload = calls[0]
        assert "image" not in payload
        assert len(payload["images"]) == 2
        assert payload["images"][0]["url"] != payload["images"][1]["url"]
        assert MASK_GUIDE_RULE in payload["prompt"]

    def test_mask_and_style_fit_three_reference_limit(self, cache,
                                                       monkeypatch):
        calls = []

        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"data": [{"b64_json": base64.b64encode(
                    b"edited").decode()}]}

        def fake_post(url, json=None, timeout=None, headers=None):
            calls.append(json)
            return FakeResponse()

        import httpx
        monkeypatch.setattr(httpx, "post", fake_post)
        monkeypatch.setenv("XAI_KEY", "test-key")

        edit_image(SOURCE, "widen only the band", "grok_direct",
                   mask_bytes=MASK, style_ref=STYLE)
        assert len(calls[0]["images"]) == 3


class TestHouseStyleSet:
    def test_the_starter_set_exists_and_loads(self):
        refs = list_style_refs()
        assert refs, "data/style_refs must carry the starter set"
        anchor = default_style_ref()
        assert anchor and anchor[:8] == b"\x89PNG\r\n\x1a\n"

    def test_empty_dir_returns_none_never_a_guess(self, tmp_path, monkeypatch):
        import facetta.housestyle as hs
        monkeypatch.setattr(hs, "STYLE_DIR", tmp_path)
        assert hs.list_style_refs() == []
        assert hs.default_style_ref() is None


class TestEndpointWiring:
    def test_house_style_routes_to_the_multi_image_engine(self, monkeypatch):
        from fastapi.testclient import TestClient

        import facetta.api.specs as specs_mod
        from facetta.main import app

        seen = {}

        def fake_edit(image_bytes, **kwargs):
            seen.update(kwargs)
            return {"image": SOURCE, "changed": "c", "frozen": "f",
                    "retried": False, "drift": None, "cached": False}

        monkeypatch.setattr(specs_mod, "localized_edit", fake_edit)
        r = TestClient(app).post("/specs/localized-edit", json={
            "image_base64": base64.b64encode(SOURCE).decode(),
            "region_description": "the band",
            "change_instruction": "widen it",
            "use_house_style": True})
        assert r.status_code == 200, r.text
        assert seen["model"] == "grok_imagine"         # auto-routed
        assert seen["style_ref"]                       # the house anchor rode
        assert r.json()["style_anchored"] is True

    def test_without_house_style_nothing_changes(self, monkeypatch):
        from fastapi.testclient import TestClient

        import facetta.api.specs as specs_mod
        from facetta.main import app

        seen = {}

        def fake_edit(image_bytes, **kwargs):
            seen.update(kwargs)
            return {"image": SOURCE, "changed": "c", "frozen": "f",
                    "retried": False, "drift": None, "cached": False}

        monkeypatch.setattr(specs_mod, "localized_edit", fake_edit)
        r = TestClient(app).post("/specs/localized-edit", json={
            "image_base64": base64.b64encode(SOURCE).decode(),
            "region_description": "the band",
            "change_instruction": "widen it"})
        assert r.status_code == 200
        assert seen["model"] == "grok_direct"
        assert seen["style_ref"] is None
        assert r.json()["style_anchored"] is False

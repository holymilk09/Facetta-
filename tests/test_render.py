"""The photoreal render pipeline: cached by content, graceful without a key,
and never inventing geometry — the provider only ever paints over the
control image the engine drew."""

import base64

import pytest
from fastapi.testclient import TestClient

import facetta.render as render_mod
from facetta.main import app
from facetta.render import render_cache_key, render_finished_image
from facetta.spec import Spec
from facetta.validation import validate_spec
from facetta.vocabulary import get_vocabulary

client = TestClient(app)

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBgAAAABQAB"
    "h6FO1AAAAABJRU5ErkJggg==")


def _validated(raw):
    result = validate_spec(Spec.model_validate(raw), get_vocabulary())
    assert result.ok, [i.msg for i in result.issues]
    return result.spec


def test_cache_key_tracks_content(example_spec):
    spec = _validated(example_spec)
    base = render_cache_key(spec, "photo", "studio")
    assert base == render_cache_key(spec, "photo", "studio")  # stable
    assert base != render_cache_key(spec, "atelier_sketch", "studio")

    example_spec["metal"]["color"] = "white"
    recolored = _validated(example_spec)
    assert base != render_cache_key(recolored, "photo", "studio")  # new look

    example_spec["stone"]["carat"] = 1.8
    example_spec["stone"]["dimensions_mm"] = {"length": 8.2, "width": 6.2,
                                              "depth": 4.0}
    resized = _validated(example_spec)
    assert render_cache_key(recolored, "photo", "studio") != \
        render_cache_key(resized, "photo", "studio")  # new geometry


def test_no_key_means_503_not_crash(example_spec, monkeypatch):
    monkeypatch.setattr(render_mod, "_provider_key", lambda env: None)
    response = client.post("/specs/render.png",
                           json={"spec": example_spec, "style": "photo"})
    assert response.status_code == 503
    assert "FAL_KEY" in response.json()["detail"]  # names the missing key


def test_render_calls_provider_once_then_serves_cache(example_spec,
                                                      monkeypatch, tmp_path):
    monkeypatch.setattr(render_mod, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(render_mod, "_provider_key", lambda env: "test:key")
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"images": [{"url": "data:image/png;base64,"
                                + base64.b64encode(PNG_1PX).decode()}]}

    import httpx

    def fake_post(url, **kwargs):
        calls.append(url)
        # the provider must receive our control image and instruction
        assert kwargs["json"]["image_url"].startswith("data:image/png;base64,")
        assert "control drawing" in kwargs["json"]["prompt"]
        return FakeResponse()

    monkeypatch.setattr(httpx, "post", fake_post)

    spec = _validated(example_spec)
    png1, cached1 = render_finished_image(spec, "photo", "studio")
    png2, cached2 = render_finished_image(spec, "photo", "studio")
    assert png1 == png2 == PNG_1PX
    assert (cached1, cached2) == (False, True)
    assert len(calls) == 1  # paid once, served forever


def test_provider_failure_is_502(example_spec, monkeypatch, tmp_path):
    monkeypatch.setattr(render_mod, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(render_mod, "_provider_key", lambda env: "test:key")
    import httpx

    def explode(url, **kwargs):
        raise httpx.ConnectError("blocked")

    monkeypatch.setattr(httpx, "post", explode)
    with pytest.raises(render_mod.RenderUnavailable):
        render_finished_image(_validated(example_spec), "photo", "studio")


def test_model_choice_is_part_of_the_cache_key(example_spec):
    spec = _validated(example_spec)
    assert render_cache_key(spec, "photo", "studio", "flux_kontext") != \
        render_cache_key(spec, "photo", "studio", "grok_imagine")


def test_unknown_model_fails_loudly(example_spec):
    with pytest.raises(render_mod.RenderUnavailable) as err:
        render_finished_image(_validated(example_spec), model="dalle_1999")
    assert "flux_kontext" in str(err.value)

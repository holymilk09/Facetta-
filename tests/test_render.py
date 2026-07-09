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


def test_generation_variant_makes_a_fresh_image(monkeypatch, tmp_path):
    """The founder's stale-concept bug: the same brief must be able to
    regenerate instead of serving the first-ever image forever."""
    from facetta.render import generate_image

    monkeypatch.setattr(render_mod, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(render_mod, "_provider_key", lambda env: "test:key")
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            # a distinct 1px payload per call so we can see cache vs fresh
            return {"data": [{"b64_json": base64.b64encode(
                b"png-" + str(len(calls)).encode()).decode()}]}

    import httpx

    def fake_post(url, **kwargs):
        calls.append(url)
        return FakeResponse()

    monkeypatch.setattr(httpx, "post", fake_post)

    a, cached_a = generate_image("art deco emerald ring")
    a2, cached_a2 = generate_image("art deco emerald ring")   # same brief, cached
    b, cached_b = generate_image("art deco emerald ring", variant=1)  # regenerate

    assert (cached_a, cached_a2, cached_b) == (False, True, False)
    assert a == a2 and a != b            # variant busts the cache, same brief
    assert len(calls) == 2               # only the two live generations paid


def test_setting_change_moves_the_cache_key_and_variant_busts_it():
    """The stale-drawing bug: a design change that the (lossy) prompt drops —
    the setting's prong count — must still change the render cache key, and a
    variant must force a genuinely fresh render."""
    import json
    from pathlib import Path

    from facetta.render import spec_visual_hash
    raw = json.loads((Path(__file__).parent.parent / "docs" / "examples"
                      / "concept_emerald_halo.json").read_text())
    a = validate_spec(Spec.model_validate(raw), get_vocabulary()).spec
    # change ONLY the setting prong count — the exact field prompt_core drops
    raw2 = json.loads(json.dumps(raw))
    raw2["setting"]["prong_count"] = (a.setting.prong_count or 4) + 2
    b = validate_spec(Spec.model_validate(raw2), get_vocabulary()).spec

    assert spec_visual_hash(a) != spec_visual_hash(b)     # design change -> new key
    # metadata (version/date) must NOT move the key (no needless re-render)
    c = a.model_copy(update={"version": a.version + 9})
    assert spec_visual_hash(a) == spec_visual_hash(c)
    # the finished-render key also reflects it
    assert (render_cache_key(a, "photo", "studio")
            != render_cache_key(b, "photo", "studio"))


def test_metal_finish_change_moves_the_render_key():
    """The parallel bug: metal.finish was in neither the fingerprint nor the
    instruction, so changing polish served the old render."""
    import json
    from pathlib import Path

    raw = json.loads((Path(__file__).parent.parent / "docs" / "examples"
                      / "concept_emerald_halo.json").read_text())
    a = validate_spec(Spec.model_validate(raw), get_vocabulary()).spec
    raw2 = json.loads(json.dumps(raw))
    raw2["metal"]["finish"] = "matte"
    b = validate_spec(Spec.model_validate(raw2), get_vocabulary()).spec
    assert (render_cache_key(a, "photo", "studio")
            != render_cache_key(b, "photo", "studio"))


def test_edit_image_refuses_empty_source():
    from facetta.render import RenderUnavailable, edit_image
    import pytest as _pytest
    with _pytest.raises(RenderUnavailable):
        edit_image(b"", "draw it", "grok_direct")

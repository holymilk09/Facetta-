"""Colored prototype and photoreal-prompt compiler."""

from fastapi.testclient import TestClient

from facetta.main import app
from facetta.prototype import render_color_preview, stone_hex
from facetta.spec import Spec
from facetta.validation import validate_spec
from facetta.vocabulary import get_vocabulary

client = TestClient(app)


def _validated(raw):
    result = validate_spec(Spec.model_validate(raw), get_vocabulary())
    assert result.ok, [i.msg for i in result.issues]
    return result.spec


def test_stone_hex_uses_vocabulary_hue(example_spec):
    spec = _validated(example_spec)
    # hue_code vB -> the vocabulary's Violetish Blue hex
    assert stone_hex(spec.stone, get_vocabulary()) == "#0808A0"


def test_prototype_is_deterministic_and_colored(pendant_spec):
    spec = _validated(pendant_spec)
    svg = render_color_preview(spec)
    assert svg == render_color_preview(spec)
    assert "COLOR PROTOTYPE" in svg
    assert 'url(#stone)' in svg and 'url(#metal)' in svg
    assert "Muzo Green" in svg


def test_prototype_endpoint(halo_spec):
    response = client.post("/specs/prototype.svg", json=halo_spec)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")


def test_render_prompt_carries_dimensional_truth(halo_spec):
    response = client.post("/specs/render-prompt", json=halo_spec)
    assert response.status_code == 200
    body = response.json()
    prompt = body["prompt"]
    assert "1.50 carat" in prompt
    assert "8.6 x 6.4 x 4 mm" in prompt
    assert "8 x 4.1 mm" in prompt and "halo" in prompt
    assert "18 karat white gold" in prompt
    assert "physically accurate proportions" in prompt
    assert body["negative_prompt"]
    assert "ControlNet" in body["control_hint"]


def test_render_prompt_includes_chain_and_drop(necklace_spec):
    body = client.post("/specs/render-prompt", json=necklace_spec).json()
    assert "cable chain" in body["prompt"]
    assert "lobster clasp" in body["prompt"]
    assert "hanging below the center" in body["prompt"]
    assert "drop" in body["prompt"]

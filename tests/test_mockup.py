"""Scene-controlled mockup requests: the geometry locks the composition."""

import pytest
from fastapi.testclient import TestClient

from facetta.main import app
from facetta.mockup import SceneUnsupported, compile_render_request, geometry_fingerprint
from facetta.spec import Spec
from facetta.validation import validate_spec
from facetta.vocabulary import get_vocabulary

client = TestClient(app)


def _validated(raw):
    result = validate_spec(Spec.model_validate(raw), get_vocabulary())
    assert result.ok, [i.msg for i in result.issues]
    return result.spec


def test_same_design_same_seed(example_spec):
    a = compile_render_request(_validated(example_spec))
    b = compile_render_request(_validated(example_spec))
    assert a["seed"] == b["seed"]
    assert a["prompt"] == b["prompt"]


def test_color_and_metal_swaps_keep_the_composition(example_spec):
    base = compile_render_request(_validated(example_spec))

    example_spec["stone"]["color"] = {
        "trade": "Cornflower Blue", "gia": "violetish blue, tone 4, saturation 4",
        "hue_code": "vB", "tone": 4, "saturation": 4,
    }
    recolored = compile_render_request(_validated(example_spec))
    assert recolored["seed"] == base["seed"]          # same composition
    assert recolored["prompt"] != base["prompt"]      # new stone color

    example_spec["metal"]["color"] = "white"
    remetaled = compile_render_request(_validated(example_spec))
    assert remetaled["seed"] == base["seed"]
    assert "white gold" in remetaled["prompt"]


def test_dimension_change_reseeds(example_spec):
    base = geometry_fingerprint(_validated(example_spec))
    example_spec["stone"]["carat"] = 1.8
    example_spec["stone"]["dimensions_mm"] = {"length": 8.2, "width": 6.2, "depth": 4.0}
    assert geometry_fingerprint(_validated(example_spec)) != base


def test_scene_vocabulary_shapes_the_prompt(example_spec):
    spec = _validated(example_spec)
    worn = compile_render_request(spec, lighting="natural", worn_on="finger")
    assert "natural window light" in worn["prompt"]
    assert "ring finger" in worn["prompt"]
    worn_negatives = worn["negative_prompt"].split(", ")
    assert "hands" not in worn_negatives              # a hand is the point
    assert "deformed hands" in worn_negatives

    product = compile_render_request(spec, lighting="studio", worn_on="product")
    assert "hands" in product["negative_prompt"].split(", ")


def test_impossible_scene_fails_loudly(example_spec):
    with pytest.raises(SceneUnsupported) as err:
        compile_render_request(_validated(example_spec), worn_on="neck")
    assert err.value.valid == ["product", "finger"]


def test_render_request_endpoint(example_spec):
    response = client.post("/specs/render-request",
                           json={"spec": example_spec, "lighting": "outdoor",
                                 "worn_on": "finger"})
    assert response.status_code == 200
    body = response.json()
    assert body["seed"] == int(body["geometry_fingerprint"][:8], 16)
    assert body["provider_payload"]["seed"] == body["seed"]
    assert "golden-hour" in body["prompt"]

    bad = client.post("/specs/render-request",
                      json={"spec": example_spec, "worn_on": "wrist"})
    assert bad.status_code == 422
    assert bad.json()["valid_options"] == ["product", "finger"]

from fastapi.testclient import TestClient

from facetta.main import app

client = TestClient(app)


def test_stones_lists_species_and_organics():
    body = client.get("/vocabulary/stones").json()
    by_id = {s["id"]: s for s in body["stones"]}
    assert by_id["ruby"]["parameter_set"] == "gemstone"
    assert by_id["pearl"]["parameter_set"] == "pearl"
    assert by_id["opal"]["parameter_set"] == "opal"
    assert "jadeite" not in by_id  # open item: not in vocabulary yet


def test_ruby_options_return_pigeons_blood_set():
    body = client.get("/vocabulary/stones/ruby/options").json()
    terms = {c["term"] for c in body["colors"]}
    assert "Pigeon's Blood" in terms
    assert "Royal Red (Rabbit's Blood)" in terms
    pigeons = next(c for c in body["colors"] if c["term"] == "Pigeon's Blood")
    assert pigeons["gia"]  # trade + GIA translation both served
    assert body["clarity"]["systems"] == ["gia_type_ii"]
    grades = {g["grade"] for g in body["clarity"]["grades"]["gia_type_ii"]}
    assert "VS" in grades
    assert body["phenomena"] == ["asterism_star"]
    assert {c["id"] for c in body["cuts"]} >= {"round_brilliant", "oval_brilliant", "cabochon"}


def test_cascade_swaps_vocabulary_between_stones():
    ruby = client.get("/vocabulary/stones/ruby/options").json()
    tanzanite = client.get("/vocabulary/stones/tanzanite/options").json()
    assert {c["term"] for c in ruby["colors"]}.isdisjoint({c["term"] for c in tanzanite["colors"]})
    assert tanzanite["clarity"]["systems"] == ["gia_type_i"]


def test_pearl_returns_its_own_parameter_set():
    body = client.get("/vocabulary/stones/pearl/options").json()
    assert body["parameter_set"] == "pearl"
    assert "gia_value_factors" in body
    assert "types" in body
    assert "colors" not in body  # no hue/tone/saturation model for organics


def test_opal_returns_its_own_parameter_set():
    body = client.get("/vocabulary/stones/opal/options").json()
    assert body["parameter_set"] == "opal"
    assert "body_tone_scale" in body
    assert "patterns" in body


def test_unknown_stone_404s_with_valid_options():
    response = client.get("/vocabulary/stones/jadeite/options")
    assert response.status_code == 404
    body = response.json()
    assert "ruby" in body["valid_options"] and "pearl" in body["valid_options"]

import pytest
from fastapi.testclient import TestClient

from facetta.main import app

client = TestClient(app)


def issue_for(body: dict, loc: list):
    return next((d for d in body["detail"] if d["loc"] == loc), None)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_valid_spec_is_echoed_back(example_spec):
    response = client.post("/specs/validate", json=example_spec)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["design_id"] == "dsn_8Kx2"
    assert body["stone"]["color"]["trade"] == "Royal Blue"


def test_unknown_trade_color_lists_valid_options(example_spec):
    example_spec["stone"]["color"]["trade"] = "Ocean Whisper"
    response = client.post("/specs/validate", json=example_spec)
    assert response.status_code == 422
    issue = issue_for(response.json(), ["stone", "color", "trade"])
    assert issue is not None
    assert "Royal Blue" in issue["valid_options"]
    assert "Padparadscha" in issue["valid_options"]


def test_unknown_species_lists_valid_options(example_spec):
    example_spec["stone"]["species"] = "unobtainium"
    response = client.post("/specs/validate", json=example_spec)
    assert response.status_code == 422
    issue = issue_for(response.json(), ["stone", "species"])
    assert "sapphire" in issue["valid_options"]


def test_impossible_carat_gets_corrective_suggestion(example_spec):
    example_spec["stone"]["carat"] = 5.0
    response = client.post("/specs/validate", json=example_spec)
    assert response.status_code == 422
    issue = issue_for(response.json(), ["stone", "carat"])
    assert issue["type"] == "density"
    assert issue["expected"]["expected_carat"] == pytest.approx(1.81, abs=0.01)
    assert issue["expected"]["expected_depth_mm"] > 4.1


def test_clarity_system_must_match_species(example_spec):
    example_spec["stone"]["clarity"]["system"] = "gia_type_i"
    response = client.post("/specs/validate", json=example_spec)
    assert response.status_code == 422
    issue = issue_for(response.json(), ["stone", "clarity", "system"])
    assert issue["valid_options"] == ["gia_type_ii"]


def test_phenomena_must_be_allowed_for_species(example_spec):
    example_spec["stone"]["phenomena"] = ["chatoyancy_cats_eye"]
    response = client.post("/specs/validate", json=example_spec)
    assert response.status_code == 422
    issue = issue_for(response.json(), ["stone", "phenomena", 0])
    assert set(issue["valid_options"]) == {"asterism_star", "color_change"}


def test_missing_inner_diameter_is_auto_derived(example_spec):
    del example_spec["ring_size"]["inner_diameter_mm"]
    response = client.post("/specs/validate", json=example_spec)
    assert response.status_code == 200, response.text
    assert response.json()["ring_size"]["inner_diameter_mm"] == pytest.approx(16.91, abs=0.01)


def test_contradictory_inner_diameter_rejected(example_spec):
    example_spec["ring_size"]["inner_diameter_mm"] = 19.8
    response = client.post("/specs/validate", json=example_spec)
    assert response.status_code == 422
    issue = issue_for(response.json(), ["ring_size", "inner_diameter_mm"])
    assert issue["expected"]["inner_diameter_mm"] == pytest.approx(16.91, abs=0.01)


def test_malformed_spec_still_gets_structured_422(example_spec):
    example_spec["stone"]["dimensions_mm"]["length"] = "8.6"
    response = client.post("/specs/validate", json=example_spec)
    assert response.status_code == 422
    assert any("length" in str(d["loc"]) for d in response.json()["detail"])


def test_silver_cannot_carry_a_color_or_karat(example_spec):
    example_spec["metal"] = {"material": "silver", "karat": 18, "color": "yellow",
                             "finish": "high_polish"}
    response = client.post("/specs/validate", json=example_spec)
    assert response.status_code == 422
    details = response.json()["detail"]
    messages = " · ".join(d["msg"] for d in details)
    assert "single natural color" in messages
    assert "not karated" in messages


def test_gold_requires_karat_and_color_with_options(example_spec):
    example_spec["metal"] = {"material": "gold", "finish": "high_polish"}
    response = client.post("/specs/validate", json=example_spec)
    assert response.status_code == 422
    by_loc = {tuple(d["loc"]): d for d in response.json()["detail"]}
    assert by_loc[("metal", "karat")]["valid_options"] == ["9", "14", "18", "22", "24"]
    assert by_loc[("metal", "color")]["valid_options"] == ["yellow", "white", "rose"]


def test_plain_silver_and_platinum_validate(example_spec):
    for material in ("silver", "platinum"):
        example_spec["metal"] = {"material": material, "finish": "high_polish"}
        response = client.post("/specs/validate", json=example_spec)
        assert response.status_code == 200, response.text


def test_findings_include_metal_rules():
    body = client.get("/vocabulary/findings").json()
    gold = next(m for m in body["metals"] if m["id"] == "gold")
    silver = next(m for m in body["metals"] if m["id"] == "silver")
    assert gold["colors"] == ["yellow", "white", "rose"]
    assert silver["colors"] == [] and silver["karats"] == []

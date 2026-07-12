from __future__ import annotations

from fastapi.testclient import TestClient

from facetta.main import app


def test_draft_stone_selection_cascades_identity_color_and_modeled_carat(
    example_spec,
):
    before = example_spec["stone"]
    response = TestClient(app).post("/specs/stone/select", json={
        "spec": example_spec,
        "species": "emerald",
        "trade_color": "Muzo Green",
    })

    assert response.status_code == 200, response.text
    body = response.json()
    stone = body["spec"]["stone"]
    assert stone["species"] == "emerald"
    assert stone["color"]["trade"] == "Muzo Green"
    assert stone["color"]["gia"]
    assert stone["cut"] == before["cut"]
    assert stone["dimensions_mm"] == before["dimensions_mm"]
    assert stone["count"] == before.get("count", 1)
    assert stone["clarity"] is None
    assert stone["origin"] is None
    assert stone["treatment"] is None
    assert stone["phenomena"] == []
    assert stone["carat"] != before["carat"]
    paths = {change["path"] for change in body["spec_change"]}
    assert {"stone.species", "stone.color", "stone.carat"} <= paths
    assert "stone.dimensions_mm" in body["frozen_facts"]

    noop = TestClient(app).post("/specs/stone/select", json={
        "spec": body["spec"],
        "species": "emerald",
        "trade_color": "Muzo Green",
    })
    assert noop.status_code == 409
    assert noop.json()["code"] == "stone_selection_no_change"


def test_draft_stone_selection_rejects_unknown_species_and_cross_species_color(
    example_spec,
):
    client = TestClient(app)
    species = client.post("/specs/stone/select", json={
        "spec": example_spec,
        "species": "jadeite",
        "trade_color": "Imperial Green",
    })
    assert species.status_code == 422
    assert species.json()["code"] == "stone_species_invalid"
    assert "jadeite" not in species.json()["valid_options"]

    color = client.post("/specs/stone/select", json={
        "spec": example_spec,
        "species": "emerald",
        "trade_color": "Pigeon's Blood",
    })
    assert color.status_code == 422
    assert color.json()["code"] == "stone_color_invalid"
    assert "Muzo Green" in color.json()["valid_options"]

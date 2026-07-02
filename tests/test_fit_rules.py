"""Physical-fit validation for multi-stone assemblies: a spec that describes
stones that cannot coexist in metal fails loudly with the feasible maximum."""

from fastapi.testclient import TestClient

from facetta.main import app

client = TestClient(app)


def issue_for(body, loc):
    return next((d for d in body["detail"] if d["loc"] == loc), None)


def test_halo_that_fits_passes(halo_spec):
    response = client.post("/specs/validate", json=halo_spec)
    assert response.status_code == 200, response.text


def test_too_many_melee_rejected_with_max_count(halo_spec):
    halo_spec["side_stones"][0]["count"] = 20
    response = client.post("/specs/validate", json=halo_spec)
    assert response.status_code == 422
    issue = issue_for(response.json(), ["side_stones", 0, "count"])
    assert issue["type"] == "fit"
    assert issue["expected"]["max_count"] == 8
    assert "at most 8 fit" in issue["msg"]


def test_bangle_station_overflow_rejected(bangle_spec):
    bangle_spec["stone"]["count"] = 60
    response = client.post("/specs/validate", json=bangle_spec)
    assert response.status_code == 422
    issue = issue_for(response.json(), ["stone", "count"])
    assert issue["type"] == "fit"
    assert issue["expected"]["max_count"] < 60


def test_station_wider_than_band_rejected(bangle_spec):
    bangle_spec["stone"]["dimensions_mm"] = {"length": 5.8, "width": 5.8, "depth": 4.0}
    bangle_spec["stone"]["carat"] = 1.1  # keep density consistent: 5.8^2*4*3.52*.46/200
    response = client.post("/specs/validate", json=bangle_spec)
    assert response.status_code == 422
    issue = issue_for(response.json(), ["stone", "dimensions_mm", "width"])
    assert issue is not None
    assert issue["expected"]["max_stone_width_mm"] == 5.1


def test_ring_template_requires_band_and_size(halo_spec):
    del halo_spec["band"]
    del halo_spec["ring_size"]
    response = client.post("/specs/validate", json=halo_spec)
    assert response.status_code == 422
    body = response.json()
    assert issue_for(body, ["band"]) is not None
    assert issue_for(body, ["ring_size"]) is not None


def test_bangle_template_requires_bracelet_section(bangle_spec):
    del bangle_spec["bracelet"]
    response = client.post("/specs/validate", json=bangle_spec)
    assert response.status_code == 422
    assert issue_for(response.json(), ["bracelet"]) is not None


def test_pendant_template_requires_pendant_section(pendant_spec):
    del pendant_spec["pendant"]
    response = client.post("/specs/validate", json=pendant_spec)
    assert response.status_code == 422
    assert issue_for(response.json(), ["pendant"]) is not None


def test_pendant_drop_is_derived(pendant_spec):
    response = client.post("/specs/validate", json=pendant_spec)
    assert response.status_code == 200
    # bail 5.5 + link 1.0 + cluster (9 + 2x(0.3+2.3)) + link 1.0 + sapphire 5.5
    assert response.json()["pendant"]["drop_mm"] == 27.2


def test_side_stones_still_density_checked(pendant_spec):
    pendant_spec["side_stones"][1]["carat"] = 3.0  # impossible for a 5.5 mm round sapphire
    response = client.post("/specs/validate", json=pendant_spec)
    assert response.status_code == 422
    issue = issue_for(response.json(), ["side_stones", 1, "carat"])
    assert issue["type"] == "density"

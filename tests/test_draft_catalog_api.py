from __future__ import annotations

from copy import deepcopy

from fastapi.testclient import TestClient

from facetta.main import app


def test_draft_catalog_compiles_coupled_metal_choice_without_persistence(
    halo_spec,
):
    response = TestClient(app).post("/specs/catalog/select", json={
        "spec": halo_spec,
        "component_path": "metal.material",
        "option_id": "platinum",
    })

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["spec"]["metal"] == {
        "material": "platinum",
        "karat": None,
        "color": None,
        "finish": "high_polish",
    }
    assert [change["path"] for change in body["spec_change"]] == [
        "metal.material", "metal.karat", "metal.color",
    ]
    assert "metal" in body["isolation_target"]
    assert "stone" in body["frozen_facts"]


def test_draft_catalog_rejects_invalid_noop_and_wrong_category(
    halo_spec,
    necklace_spec,
):
    client = TestClient(app)
    invalid = client.post("/specs/catalog/select", json={
        "spec": halo_spec,
        "component_path": "metal.material",
        "option_id": "unobtainium",
    })
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "catalog_selection_invalid"
    assert "platinum" in invalid.json()["valid_options"]

    noop = client.post("/specs/catalog/select", json={
        "spec": halo_spec,
        "component_path": "metal.material",
        "option_id": "gold_18_white",
    })
    assert noop.status_code == 409
    assert noop.json()["code"] == "catalog_selection_no_change"

    wrong_category = client.post("/specs/catalog/select", json={
        "spec": necklace_spec,
        "component_path": "stone.cut",
        "option_id": "oval_brilliant",
    })
    assert wrong_category.status_code == 422
    assert wrong_category.json()["code"] == "catalog_not_applicable"


def test_bezel_draft_selection_removes_obsolete_prong_dimension_provenance(
    halo_spec,
):
    source = deepcopy(halo_spec)
    source["dimension_provenance"] = {
        "setting.prong_tip_mm": {
            "status": "estimated_from_reference",
            "method": "reference_vision",
            "source": "designer drawing",
            "confidence": 0.4,
        },
    }
    response = TestClient(app).post("/specs/catalog/select", json={
        "spec": source,
        "component_path": "setting.style",
        "option_id": "bezel",
    })

    assert response.status_code == 200, response.text
    spec = response.json()["spec"]
    assert spec["setting"]["prong_count"] is None
    assert spec["setting"]["prong_tip_mm"] is None
    assert "setting.prong_tip_mm" not in spec["dimension_provenance"]

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


def test_findings_endpoint_serves_metalwork_vocabulary():
    body = client.get("/vocabulary/findings").json()
    assert {c["id"] for c in body["chain_styles"]} >= {"cable", "curb", "rope", "box"}
    assert {c["id"] for c in body["clasp_types"]} >= {"lobster", "toggle", "spring_ring"}
    assert "medium" in body["girdle_thickness_scale"]
    assert body["girdle_thickness_scale"][0] == "extremely_thin"  # ordered scale


def test_chain_component_catalog_exposes_typed_agent_control_metadata():
    response = client.get("/vocabulary/components/chain.style")
    assert response.status_code == 200
    body = response.json()
    assert body["component_path"] == "chain.style"
    assert body["applicable_jewelry_types"] == ["necklace"]
    assert body["image_agent_status"] == "catalog_ready"
    assert body["preview_execution_modes"] == ["provider"]
    options = {option["id"]: option for option in body["options"]}
    assert {"cable", "curb", "figaro", "rope", "box", "snake"} <= options.keys()
    assert options["curb"]["factory_fields"] == {"chain.style": "curb"}
    assert "chain" in options["curb"]["isolation_target"].lower()
    assert options["curb"]["visual_geometry"]
    assert "pendant" in options["curb"]["frozen_facts"]


def test_ring_component_catalogs_expose_exact_coupled_controls():
    cuts = client.get("/vocabulary/components/stone.cut")
    assert cuts.status_code == 200
    cut_body = cuts.json()
    assert cut_body["display"] == "Center stone cut / shape"
    assert cut_body["applicable_jewelry_types"] == ["ring"]
    assert cut_body["image_agent_status"] == "catalog_ready"
    cut_options = {option["id"]: option for option in cut_body["options"]}
    assert set(cut_options) == {
        "round_brilliant", "oval_brilliant", "emerald_cut", "cushion",
    }
    assert cut_options["emerald_cut"]["factory_fields"] == {
        "stone.cut": "emerald_cut",
    }
    assert cut_options["emerald_cut"]["derived_factory_fields"] == [
        "stone.carat",
    ]

    materials = client.get("/vocabulary/components/metal.material")
    assert materials.status_code == 200
    material_options = {
        option["id"]: option for option in materials.json()["options"]
    }
    assert material_options["gold_18_rose"]["factory_fields"] == {
        "metal.material": "gold",
        "metal.karat": 18,
        "metal.color": "rose",
    }
    assert material_options["platinum"]["factory_fields"] == {
        "metal.material": "platinum",
        "metal.karat": None,
        "metal.color": None,
    }

    colors = client.get("/vocabulary/components/metal.color")
    assert colors.status_code == 200
    assert colors.json()["preview_execution_modes"] == ["instant", "provider"]
    assert {option["id"] for option in colors.json()["options"]} == {
        "yellow", "white", "rose",
    }

    settings = client.get("/vocabulary/components/setting.style")
    assert settings.status_code == 200
    assert settings.json()["preview_execution_modes"] == ["provider"]
    setting_options = {
        option["id"]: option for option in settings.json()["options"]
    }
    assert setting_options["6_prong_basket"]["factory_fields"] == {
        "setting.style": "6_prong_basket",
        "setting.prong_count": 6,
    }
    assert setting_options["bezel"]["factory_fields"] == {
        "setting.style": "bezel",
        "setting.prong_count": None,
        "setting.prong_tip_mm": None,
    }


def test_center_stone_quick_palette_requires_species_and_is_contextual():
    missing = client.get("/vocabulary/components/stone.color")
    assert missing.status_code == 422
    assert missing.json()["code"] == "stone_species_required"

    sapphire = client.get(
        "/vocabulary/components/stone.color",
        params={"stone_species": "sapphire"},
    )
    assert sapphire.status_code == 200, sapphire.text
    body = sapphire.json()
    assert body["display"] == "Center stone species and color"
    assert 5 <= len(body["options"]) <= 7
    royal_blue = next(option for option in body["options"]
                      if option["id"] == "Royal Blue")
    assert royal_blue["factory_fields"]["stone.species"] == "sapphire"
    assert royal_blue["factory_fields"]["stone.color"]["trade"] == "Royal Blue"
    assert "stone.dimensions_mm" in royal_blue["frozen_facts"]

    unknown = client.get(
        "/vocabulary/components/stone.color",
        params={"stone_species": "jadeite"},
    )
    assert unknown.status_code == 422
    assert unknown.json()["code"] == "stone_species_invalid"
    assert "diamond" in unknown.json()["valid_options"]


def test_unknown_component_catalog_is_a_structured_404():
    response = client.get("/vocabulary/components/chain.magic")
    assert response.status_code == 404
    assert response.json()["valid_catalogs"] == [
        "chain.style",
        "stone.cut",
        "stone.color",
        "metal.material",
        "metal.color",
        "setting.style",
    ]


def test_unknown_stone_404s_with_valid_options():
    response = client.get("/vocabulary/stones/jadeite/options")
    assert response.status_code == 404
    body = response.json()
    assert "ruby" in body["valid_options"] and "pearl" in body["valid_options"]

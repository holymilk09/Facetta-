"""Concept origination: Grok invents, the validator makes it manufacturable.

The image engines are mocked; the point under test is the real-life-logic
engine — a sparse, even sloppy vision read is turned into a spec that PASSES
every density, fit, and clearance rule, with the corrections recorded.
"""

import base64

from facetta.concept import DesignRead, complete_design
from facetta.spec import Spec
from facetta.validation import validate_spec
from facetta.vocabulary import get_vocabulary

VOCAB = get_vocabulary()


def _valid(spec: Spec) -> bool:
    return validate_spec(spec, VOCAB).ok


class TestCompleteDesign:
    def test_halo_read_becomes_a_valid_spec(self):
        read = DesignRead(halo=True, species="emerald", cut="emerald",
                          center_length_mm=13, center_width_mm=10,
                          metal_material="platinum")
        spec, corrections = complete_design(read, "emerald halo ring")
        assert _valid(spec)
        assert spec.template == "halo_prong"
        assert spec.stone.cut == "emerald_cut"          # mapped from "emerald"
        assert spec.metal.material == "platinum" and spec.metal.karat is None
        assert corrections                               # it had to do real work

    def test_carat_is_density_consistent(self):
        read = DesignRead(species="sapphire", cut="oval", center_length_mm=9,
                          center_width_mm=7, metal_material="gold",
                          metal_color="yellow")
        spec, _ = complete_design(read, "sapphire solitaire")
        d = spec.stone.dimensions_mm
        expect = validate_spec(spec, VOCAB)  # density is one of its checks
        assert expect.ok
        assert spec.template == "solitaire_prong"
        assert spec.metal.karat == 18 and spec.metal.color == "yellow"

    def test_halo_count_fits_the_centre(self):
        read = DesignRead(halo=True, species="diamond", cut="round",
                          center_length_mm=6, center_width_mm=6,
                          metal_material="platinum")
        spec, corrections = complete_design(read, "small halo")
        melee = spec.side_stones[0]
        # the count is exactly what physically fits — validation agrees
        assert _valid(spec)
        assert any("halo sized to" in c for c in corrections)

    def test_gallery_clears_the_culet(self):
        read = DesignRead(species="diamond", cut="round", center_length_mm=10,
                          center_width_mm=10, metal_material="platinum")
        spec, _ = complete_design(read, "deep stone")
        min_rail = VOCAB.manufacturing_tolerances()["culet_to_finger_rail_mm"]
        required = 0.71 * spec.stone.dimensions_mm.depth + min_rail
        assert spec.setting.gallery_height_mm >= required

    def test_unknown_cut_falls_back(self):
        read = DesignRead(species="diamond", cut="trilliant-ish",
                          center_length_mm=8, center_width_mm=8,
                          metal_material="platinum")
        spec, corrections = complete_design(read, "odd cut")
        assert spec.stone.cut == "oval_brilliant"
        assert any("oval_brilliant" in c for c in corrections)

    def test_bezel_setting_reaches_the_spec(self):
        # the founder's bug: a bezel design was always flattened to 4 prongs
        read = DesignRead(species="diamond", cut="round", center_length_mm=7,
                          center_width_mm=7, metal_material="platinum",
                          setting_style="bezel")
        spec, corrections = complete_design(read, "bezel-set diamond")
        assert _valid(spec)
        assert spec.setting.style == "bezel"
        assert spec.setting.prong_count is None   # a bezel has no claws
        assert any("bezel" in c for c in corrections)

    def test_default_setting_is_a_prong_basket(self):
        read = DesignRead(species="diamond", cut="round", center_length_mm=6.5,
                          center_width_mm=6.5, metal_material="platinum")
        spec, _ = complete_design(read, "plain solitaire")
        assert spec.setting.style == "4_prong_basket"
        assert spec.setting.prong_count == 4


class TestConceptEndpoint:
    def test_from_concept_returns_image_spec_corrections(self, monkeypatch):
        from fastapi.testclient import TestClient

        import facetta.concept as concept_mod
        from facetta.main import app

        fake_png = b"\x89PNG\r\n\x1a\nconcept"
        monkeypatch.setattr(concept_mod, "generate_concept",
                            lambda brief, model="grok_direct", variant=0: (fake_png, False))
        monkeypatch.setattr(concept_mod, "read_design",
                            lambda image, brief: DesignRead(
                                halo=True, species="emerald", cut="emerald",
                                center_length_mm=12, center_width_mm=9,
                                metal_material="platinum"))

        r = TestClient(app).post("/specs/from-concept",
                                 json={"brief": "art deco emerald halo ring"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert base64.b64decode(body["concept_image_b64"]) == fake_png
        assert body["spec"]["template"] == "halo_prong"
        assert body["corrections"]
        # the returned spec is genuinely valid
        assert _valid(Spec.model_validate(body["spec"]))

    def test_missing_key_is_503(self, monkeypatch):
        from fastapi.testclient import TestClient

        import facetta.concept as concept_mod
        from facetta.main import app
        from facetta.render import RenderUnavailable

        def boom(brief, model="grok_direct", variant=0):
            raise RenderUnavailable("no XAI_KEY configured — set it")

        monkeypatch.setattr(concept_mod, "generate_concept", boom)
        r = TestClient(app).post("/specs/from-concept", json={"brief": "a ring"})
        assert r.status_code == 503

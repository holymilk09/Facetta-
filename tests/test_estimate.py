"""The math assist: deterministic code as the calculator, never the designer.

Pure arithmetic over the vocabulary's SG and shape-factor tables — no LLM,
no cache, no network, and nothing drawn. Under test: carat from dimensions
(with the cut's typical depth ratio filling a missing depth), the inverse
required-depth, the tolerant size-string parser, and the physics check that
corrects Grok's estimates against the same density model the validator trusts.
"""

import pytest
from fastapi.testclient import TestClient

from facetta.density import check_density
from facetta.estimate import (
    EstimateError, estimate_carat, match_stone_words, parse_size_mm,
    physics_check_estimates, required_depth_mm,
)
from facetta.main import app
from facetta.vocabulary import get_vocabulary

VOCAB = get_vocabulary()


class TestEstimateCarat:
    def test_stated_depth_matches_the_density_model_exactly(self):
        out = estimate_carat(VOCAB, "diamond", "oval_brilliant", 8, 6, 3.7)
        assert out["depth_assumed"] is False and out["depth_used_mm"] == 3.7
        # byte-identical to the validator's own model
        expected = 8 * 6 * 3.7 * 3.52 * 0.4 / 200
        assert out["carat"] == round(expected, 3)

    def test_missing_depth_uses_the_cuts_typical_ratio(self):
        out = estimate_carat(VOCAB, "diamond", "oval_brilliant", 8, 6)
        assert out["depth_assumed"] is True
        assert out["depth_used_mm"] == round(6 * 0.62, 2)   # width × ratio

    def test_species_density_matters(self):
        # same dimensions, heavier stone: sapphire (SG 4.0) outweighs diamond
        d = estimate_carat(VOCAB, "diamond", "round_brilliant", 6, 6, 3.7)
        s = estimate_carat(VOCAB, "sapphire", "round_brilliant", 6, 6, 3.7)
        assert s["carat"] > d["carat"]

    def test_unknown_species_or_cut_carries_the_options(self):
        with pytest.raises(EstimateError, match="diamond"):
            estimate_carat(VOCAB, "kryptonite", "oval_brilliant", 8, 6)
        with pytest.raises(EstimateError, match="round_brilliant"):
            estimate_carat(VOCAB, "diamond", "dodecahedron", 8, 6)

    def test_nonpositive_dimensions_are_refused(self):
        with pytest.raises(EstimateError):
            estimate_carat(VOCAB, "diamond", "pear", 0, 6)
        with pytest.raises(EstimateError):
            estimate_carat(VOCAB, "diamond", "pear", 8, 6, -1)


class TestRequiredDepth:
    def test_round_trips_with_the_density_model(self):
        depth = required_depth_mm(VOCAB, "diamond", "oval_brilliant", 1.5, 8, 6)
        back = estimate_carat(VOCAB, "diamond", "oval_brilliant", 8, 6, depth)
        assert back["carat"] == pytest.approx(1.5, abs=0.01)

    def test_agrees_with_check_density_expected_depth(self):
        depth = required_depth_mm(VOCAB, "ruby", "cushion", 2.0, 7, 7)
        sp, c = VOCAB.species("ruby"), VOCAB.cut("cushion")
        model = check_density(sg=sp.sg, shape_factor=c.shape_factor,
                              length_mm=7, width_mm=7, depth_mm=4.0, carat=2.0)
        assert depth == model.expected_depth_mm


class TestParseSizeMm:
    def test_the_messy_forms_grok_writes(self):
        assert parse_size_mm("8 × 6") == (8.0, 6.0, None)
        assert parse_size_mm("~8.5 x 6.5 mm") == (8.5, 6.5, None)
        assert parse_size_mm("7×5×3.2") == (7.0, 5.0, 3.2)
        assert parse_size_mm("1.4 * 1.4") == (1.4, 1.4, None)

    def test_a_lone_number_reads_as_a_round_diameter(self):
        assert parse_size_mm("⌀1.4") == (1.4, 1.4, None)
        assert parse_size_mm("6 mm") == (6.0, 6.0, None)

    def test_junk_is_none_never_a_guess(self):
        assert parse_size_mm("TBD") is None
        assert parse_size_mm("large") is None
        assert parse_size_mm(None) is None
        assert parse_size_mm(8.5) is None


class TestMatchStoneWords:
    def test_species_and_cut_from_free_text(self):
        assert match_stone_words(VOCAB, "diamond oval brilliant") == \
            ("diamond", "oval_brilliant")
        assert match_stone_words(VOCAB, "sapphire pear") == ("sapphire", "pear")

    def test_round_shorthand(self):
        assert match_stone_words(VOCAB, "diamond round") == \
            ("diamond", "round_brilliant")

    def test_no_match_stays_none_never_guessed(self):
        assert match_stone_words(VOCAB, "mystery gem") == (None, None)


class TestPhysicsCheckEstimates:
    def _est(self, stones):
        return {"stones": stones, "metal": "18k gold", "measurements": [],
                "scaled": False, "scale_anchor": None}

    def test_impossible_carat_is_corrected_to_the_model(self):
        est = self._est([{"qty": 1, "type": "diamond oval brilliant",
                          "size_mm": "8 × 6", "carat_each": 5.0,
                          "confidence": 0.6}])
        out = physics_check_estimates(VOCAB, est)
        stone = out["stones"][0]
        assert stone["carat_each"] == pytest.approx(1.257, abs=0.01)
        assert "adjusted from 5.0" in stone["note"]
        assert out["physics_checked"] is True

    def test_missing_carat_is_filled_from_the_model(self):
        est = self._est([{"qty": 8, "type": "diamond round brilliant",
                          "size_mm": "1.4 × 1.4", "carat_each": None,
                          "confidence": 0.4}])
        out = physics_check_estimates(VOCAB, est)
        assert out["stones"][0]["carat_each"] > 0
        assert "modeled from size" in out["stones"][0]["note"]

    def test_consistent_carat_raises_confidence_capped(self):
        modeled = estimate_carat(VOCAB, "diamond", "oval_brilliant", 8, 6)
        est = self._est([{"qty": 1, "type": "diamond oval brilliant",
                          "size_mm": "8 × 6", "carat_each": modeled["carat"],
                          "confidence": 0.9}])
        out = physics_check_estimates(VOCAB, est)
        stone = out["stones"][0]
        assert stone["carat_each"] == modeled["carat"]     # untouched
        assert stone["confidence"] == 0.95                 # bumped, capped
        assert "physics ✓" in stone["note"]

    def test_unresolvable_stone_is_left_exactly_as_read(self):
        est = self._est([{"qty": 1, "type": "mystery gem", "size_mm": "9 × 9",
                          "carat_each": 2.0, "confidence": 0.3}])
        out = physics_check_estimates(VOCAB, est)
        assert out["stones"][0] == {"qty": 1, "type": "mystery gem",
                                    "size_mm": "9 × 9", "carat_each": 2.0,
                                    "confidence": 0.3}
        assert "physics_checked" not in out               # nothing was checked


class TestEstimateStoneEndpoint:
    def test_carat_from_dimensions(self):
        r = TestClient(app).post("/specs/estimate-stone", json={
            "species": "diamond", "cut": "oval_brilliant",
            "length_mm": 8, "width_mm": 6, "depth_mm": 3.7})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["derived"] == "carat" and body["depth_assumed"] is False
        assert body["carat"] == pytest.approx(1.25, abs=0.01)

    def test_depth_from_carat(self):
        r = TestClient(app).post("/specs/estimate-stone", json={
            "species": "diamond", "cut": "oval_brilliant",
            "length_mm": 8, "width_mm": 6, "carat": 2.0})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["derived"] == "depth_mm"
        assert body["required_depth_mm"] == pytest.approx(5.92, abs=0.01)

    def test_unknown_species_is_422_with_options(self):
        r = TestClient(app).post("/specs/estimate-stone", json={
            "species": "kryptonite", "cut": "pear",
            "length_mm": 8, "width_mm": 6})
        assert r.status_code == 422
        assert "diamond" in r.json()["detail"]            # the valid options

    def test_missing_dimensions_is_422(self):
        r = TestClient(app).post("/specs/estimate-stone", json={
            "species": "diamond", "cut": "pear"})
        assert r.status_code == 422

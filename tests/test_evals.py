"""The engine evaluation harness: scoring is pure code over mocked vision
reads — no network, no engines. Under test: the conformance components
compare the read against the actual spec, edit fidelity weights the intended
change and the static hold, and the summary averages per engine."""

import json
from pathlib import Path

import pytest

import facetta.specagent as agent
from facetta.evals import (
    score_edit_fidelity, score_spec_conformance, summarize_engine_scores,
)
from facetta.spec import Spec

RUBY = Spec.model_validate(json.loads(
    (Path(__file__).parent.parent / "docs" / "examples"
     / "ruby_sunburst_ring.json").read_text()))


class TestSpecConformance:
    def _mock_read(self, monkeypatch, stones, metal):
        monkeypatch.setattr(agent, "read_sheet_specs",
                            lambda image, **k: {
                                "stones": stones, "metal": metal,
                                "measurements": [], "scaled": False,
                                "scale_anchor": None})

    def test_a_faithful_read_scores_high(self, monkeypatch):
        total = RUBY.stone.count + sum(s.count for s in RUBY.side_stones)
        self._mock_read(monkeypatch, [
            {"qty": 1, "type": "ruby oval brilliant",
             "size_mm": f"{RUBY.stone.dimensions_mm.length} × "
                        f"{RUBY.stone.dimensions_mm.width}",
             "carat_each": RUBY.stone.carat, "confidence": 0.8},
            {"qty": total - 1, "type": "diamond round brilliant",
             "size_mm": "1.4 × 1.4", "carat_each": 0.01, "confidence": 0.5},
        ], "platinum, high polish")
        result = score_spec_conformance(RUBY, b"img")
        assert result["score"] >= 90
        assert result["components"]["species_named"] == 1.0
        assert result["components"]["metal_matched"] == 1.0
        assert result["components"]["stone_count"] == 1.0

    def test_a_wrong_piece_scores_low(self, monkeypatch):
        self._mock_read(monkeypatch, [
            {"qty": 1, "type": "emerald princess", "size_mm": "20 × 20",
             "carat_each": 30.0, "confidence": 0.8}], "sterling silver")
        result = score_spec_conformance(RUBY, b"img")
        assert result["score"] < 30
        assert result["components"]["species_named"] == 0.0
        assert result["components"]["metal_matched"] == 0.0

    def test_an_empty_read_scores_zero_components(self, monkeypatch):
        self._mock_read(monkeypatch, [], "TBD")
        result = score_spec_conformance(RUBY, b"img")
        assert result["components"]["centre_carat"] == 0.0
        assert result["components"]["centre_size"] == 0.0


class TestEditFidelity:
    def _mock_judge(self, monkeypatch, data):
        monkeypatch.setattr(agent, "_vision_json_2img",
                            lambda system, a, b, ask: data)

    def test_applied_and_static_is_a_full_score(self, monkeypatch):
        self._mock_judge(monkeypatch, {
            "change_applied": True, "unintended_changes": [],
            "severity": "none", "change_note": "sapphire now"})
        result = score_edit_fidelity(b"a", b"b", "ruby becomes sapphire")
        assert result["score"] == 100.0 and result["static_hold"] == 1.0

    def test_major_drift_zeroes_the_static_hold(self, monkeypatch):
        self._mock_judge(monkeypatch, {
            "change_applied": True,
            "unintended_changes": ["halo count changed"],
            "severity": "major"})
        result = score_edit_fidelity(b"a", b"b", "x")
        assert result["score"] == 60.0          # change happened, hold failed
        assert result["static_hold"] == 0.0

    def test_change_not_applied_caps_the_score(self, monkeypatch):
        self._mock_judge(monkeypatch, {
            "change_applied": False, "unintended_changes": [],
            "severity": "none"})
        result = score_edit_fidelity(b"a", b"b", "x")
        assert result["score"] == 40.0          # static only, no change


class TestSummary:
    def test_per_engine_means(self):
        rows = [
            {"engine": "grok_direct", "kind": "render", "score": 90.0},
            {"engine": "grok_direct", "kind": "render", "score": 70.0},
            {"engine": "grok_direct", "kind": "edit", "score": 100.0},
            {"engine": "flux", "kind": "render", "score": 50.0},
        ]
        s = summarize_engine_scores(rows)
        assert s["grok_direct"]["render_avg"] == 80.0
        assert s["grok_direct"]["edit_avg"] == 100.0
        assert s["grok_direct"]["runs"] == 3
        assert s["flux"]["edit_avg"] is None

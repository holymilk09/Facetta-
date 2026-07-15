"""The engine evaluation harness: scoring is pure code over mocked vision
reads — no network, no engines. Under test: the conformance components
compare the read against the actual spec, edit fidelity weights the intended
change and the static hold, and the summary averages per engine."""

import json
from copy import deepcopy
from math import nan
from pathlib import Path

import facetta.specagent as agent
import pytest
from facetta.evals import (
    derive_quality_verdict,
    score_edit_fidelity,
    score_edit_fidelity_from_observation,
    score_spec_conformance,
    score_spec_conformance_from_observation,
    summarize_engine_scores,
)
from facetta.spec import Spec

RUBY = Spec.model_validate(json.loads(
    (Path(__file__).parent.parent / "docs" / "examples"
     / "ruby_sunburst_ring.json").read_text()))


class TestSpecConformance:
    @staticmethod
    def _observation(stones, metal):
        return {
            "stones": stones, "metal": metal,
            "measurements": [], "scaled": False,
            "scale_anchor": None,
        }

    def _mock_read(self, monkeypatch, stones, metal):
        monkeypatch.setattr(agent, "read_sheet_specs",
                            lambda image, **k: self._observation(stones, metal))

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

    def test_pure_observation_score_matches_live_wrapper_without_mutation(
            self, monkeypatch):
        observation = self._observation([{
            "qty": 1, "type": "ruby oval brilliant", "size_mm": "8 x 6",
            "carat_each": 2.0, "confidence": 0.8,
        }], "platinum")
        original = deepcopy(observation)
        monkeypatch.setattr(
            agent, "read_sheet_specs", lambda image, **k: deepcopy(observation))

        pure = score_spec_conformance_from_observation(RUBY, observation)
        live = score_spec_conformance(RUBY, b"img")

        assert pure == live
        assert observation == original

    @pytest.mark.parametrize("bad_value", ["1", True])
    def test_pure_observation_rejects_coerced_quantities(self, bad_value):
        observation = self._observation([{
            "qty": bad_value, "type": "ruby oval brilliant",
            "size_mm": "8 x 6", "carat_each": 2.0, "confidence": 0.8,
        }], "platinum")
        with pytest.raises(ValueError, match="qty must be an integer"):
            score_spec_conformance_from_observation(RUBY, observation)

    def test_pure_observation_rejects_non_finite_numbers(self):
        observation = self._observation([{
            "qty": 1, "type": "ruby oval brilliant", "size_mm": "8 x 6",
            "carat_each": nan, "confidence": 0.8,
        }], "platinum")
        with pytest.raises(ValueError, match="carat_each must be finite"):
            score_spec_conformance_from_observation(RUBY, observation)


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

    def test_pure_observation_matches_live_wrapper(self, monkeypatch):
        observation = {
            "change_applied": True,
            "unintended_changes": ["reflection shifted"],
            "severity": "minor", "change_note": "stone changed",
        }
        self._mock_judge(monkeypatch, observation)
        assert score_edit_fidelity_from_observation(observation) == (
            score_edit_fidelity(b"a", b"b", "x"))

    @pytest.mark.parametrize("observation, error", [
        ({"change_applied": "false", "unintended_changes": [],
          "severity": "none"}, "change_applied must be a boolean"),
        ({"change_applied": True, "unintended_changes": "none",
          "severity": "none"}, "unintended_changes must be a string list"),
        ({"change_applied": True, "unintended_changes": [],
          "severity": "unknown"}, "severity must be none, minor, or major"),
    ])
    def test_pure_observation_rejects_malformed_evidence(
            self, observation, error):
        with pytest.raises(ValueError, match=error):
            score_edit_fidelity_from_observation(observation)


def _quality_report(*, verdict="pass", passed=True, severity="hard",
                    score=100.0):
    return {
        "verdict": verdict,
        "checks": [{
            "code": "source_design_preserved", "passed": passed,
            "severity": severity, "message": "source design compared",
            "evidence": {"outside_drift": 0.0},
        }],
        "score": score,
        "notes": [],
    }


class TestQualityVerdict:
    @pytest.mark.parametrize("report, expected", [
        (_quality_report(), "pass"),
        (_quality_report(verdict="warn", passed=False, severity="warning"),
         "warn"),
        (_quality_report(verdict="fail", passed=False), "fail"),
    ])
    def test_derives_verdict_from_checks(self, report, expected):
        assert derive_quality_verdict(report) == expected

    def test_declared_verdict_cannot_override_checks(self):
        report = _quality_report(verdict="pass", passed=False)
        with pytest.raises(ValueError, match="checks derive 'fail'"):
            derive_quality_verdict(report)

    @pytest.mark.parametrize("mutate, error", [
        (lambda report: report.update(checks=[]), "non-empty list"),
        (lambda report: report["checks"][0].update(passed=1),
         "passed must be a boolean"),
        (lambda report: report.update(score=nan), "score must be finite"),
    ])
    def test_malformed_reports_fail_closed(self, mutate, error):
        report = _quality_report()
        mutate(report)
        with pytest.raises(ValueError, match=error):
            derive_quality_verdict(report)


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

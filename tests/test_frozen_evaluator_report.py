"""Provider-free replay contract for retained frozen evaluator reports."""

import json
from pathlib import Path

import pytest

from facetta.frozen_evaluator_report import (
    EVALUATOR_REPORT_SCHEMA,
    validate_and_replay_evaluator_report,
)
from facetta.spec import Spec


ROOT = Path(__file__).parent.parent
RUBY = Spec.model_validate(json.loads(
    (ROOT / "docs/examples/ruby_sunburst_ring.json").read_text()
)).model_dump(mode="json")
HASH = "a" * 64
EVALUATOR_HASH = "b" * 64


def _planned(kind: str) -> dict:
    return {
        "corpus_run_id": "run-1",
        "kind": kind,
        "evaluation_id": "render-1" if kind == "render" else "edit-1",
        "operation_class": "render_conformance" if kind == "render" else "structural",
        "source_filename": "ring.png",
        "source_sha256": HASH,
        "resolved_inputs_sha256": "c" * 64,
        "resolved_inputs": {
            "frozen_component_bindings": {
                "evaluator_bundle": f"src/facetta/evals.py@sha256:{EVALUATOR_HASH}",
            },
            "scoring": {
                "metric": (
                    "score_spec_conformance.v1"
                    if kind == "render" else "score_edit_fidelity.v1"
                ),
            },
            "evaluation_contract": {"canonical_target_spec": RUBY},
        },
    }


def _attempt(kind: str) -> dict:
    return {
        "attempt": 1,
        "source_image_sha256": HASH,
        "candidate_image_sha256": "d" * 64,
        "mask_image_sha256": "e" * 64 if kind == "edit" else None,
        # Stored projections are deliberately not inputs to replay.
        "render_conformance_score": 1000,
        "edit_fidelity_score": 1000,
    }


def _quality(verdict: str = "pass") -> dict:
    passed = verdict == "pass"
    return {
        "verdict": verdict,
        "checks": [{
            "code": "frozen_visual_gate",
            "passed": passed,
            "severity": "hard",
            "message": "retained visual gate",
            "evidence": {},
        }],
        "score": 100.0 if passed else 0.0,
        "notes": [],
    }


def _report(kind: str) -> dict:
    planned = _planned(kind)
    attempt = _attempt(kind)
    return {
        "schema_version": EVALUATOR_REPORT_SCHEMA,
        "bindings": {
            "corpus_run_id": planned["corpus_run_id"],
            "resolved_inputs_sha256": planned["resolved_inputs_sha256"],
            "kind": kind,
            "evaluation_id": planned["evaluation_id"],
            "operation_class": planned["operation_class"],
            "source_filename": planned["source_filename"],
            "attempt": attempt["attempt"],
            "source_image_sha256": attempt["source_image_sha256"],
            "candidate_image_sha256": attempt["candidate_image_sha256"],
            "mask_image_sha256": attempt["mask_image_sha256"],
            "evaluator_contract_sha256": EVALUATOR_HASH,
        },
        "observer": {
            "provider": "fixture",
            "model": "fixture-vision",
            "model_revision": "1",
            "model_revision_status": "pinned",
            "request_id": "request-1",
        },
        "quality_report": _quality(),
        "metric": planned["resolved_inputs"]["scoring"]["metric"],
        "observation": (
            {
                "stones": [{
                    "qty": 1,
                    "type": "ruby oval brilliant",
                    "size_mm": "8 x 6",
                    "carat_each": 2.0,
                    "confidence": 1.0,
                }],
                "metal": "platinum",
                "measurements": [],
                "scaled": False,
                "scale_anchor": None,
            }
            if kind == "render"
            else {
                "change_applied": True,
                "change_note": "requested edit applied",
                "unintended_changes": [],
                "severity": "none",
            }
        ),
    }


def test_render_report_replays_score_and_hard_gate_without_stored_scalar() -> None:
    derived = validate_and_replay_evaluator_report(
        _report("render"), _planned("render"), _attempt("render"),
    )
    assert 0 <= derived["render_conformance_score"] <= 100
    assert derived["hard_gate_pass"] is True
    assert derived["accepted"] is True
    assert derived["attempt_outcome"] == "accepted"


def test_edit_report_replays_discrete_fidelity_projection() -> None:
    derived = validate_and_replay_evaluator_report(
        _report("edit"), _planned("edit"), _attempt("edit"),
    )
    assert derived["edit_fidelity_score"] == 100.0
    assert derived["change_applied"] is True
    assert derived["severity"] == "none"
    assert derived["static_hold"] == 1.0


@pytest.mark.parametrize("field", [
    "candidate_image_sha256",
    "resolved_inputs_sha256",
    "evaluation_id",
    "attempt",
])
def test_cross_attempt_or_artifact_substitution_fails(field: str) -> None:
    report = _report("render")
    report["bindings"][field] = 2 if field == "attempt" else "x" * 64
    with pytest.raises(ValueError, match="bindings differ"):
        validate_and_replay_evaluator_report(
            report, _planned("render"), _attempt("render"),
        )


def test_quality_verdict_cannot_contradict_checks() -> None:
    report = _report("render")
    report["quality_report"]["checks"][0]["passed"] = False
    with pytest.raises(ValueError, match="checks derive 'fail'"):
        validate_and_replay_evaluator_report(
            report, _planned("render"), _attempt("render"),
        )


def test_unknown_report_fields_fail_closed() -> None:
    report = _report("edit")
    report["claimed_score"] = 100
    with pytest.raises(ValueError, match="fields differ"):
        validate_and_replay_evaluator_report(
            report, _planned("edit"), _attempt("edit"),
        )

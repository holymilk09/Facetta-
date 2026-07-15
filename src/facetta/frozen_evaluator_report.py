"""Strict, provider-free replay for frozen evaluator evidence.

The report is an observation artifact, not an authoritative score.  Capture
production and release replay both call :func:`validate_and_replay_evaluator_report`
and derive every machine projection from the retained observations and QA
checks.  This makes accidental or post-observation scalar inflation fail
closed while keeping replay local and fast.
"""

from __future__ import annotations

import json
import re
from typing import Any

from facetta.evals import (
    derive_quality_verdict,
    score_edit_fidelity_from_observation,
    score_spec_conformance_from_observation,
)
from facetta.spec import Spec


Json = dict[str, Any]
EVALUATOR_REPORT_SCHEMA = "facetta-frozen-evaluator-report.v1"
MAX_EVALUATOR_REPORT_BYTES = 1_000_000

_REPORT_FIELDS = {
    "schema_version",
    "bindings",
    "observer",
    "quality_report",
    "metric",
    "observation",
}
_BINDING_FIELDS = {
    "corpus_run_id",
    "resolved_inputs_sha256",
    "kind",
    "evaluation_id",
    "operation_class",
    "source_filename",
    "attempt",
    "source_image_sha256",
    "candidate_image_sha256",
    "mask_image_sha256",
    "evaluator_contract_sha256",
}
_OBSERVER_FIELDS = {
    "provider",
    "model",
    "model_revision",
    "model_revision_status",
    "request_id",
}
_HEX_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _require_exact_fields(value: object, expected: set[str], label: str) -> Json:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    if set(value) != expected:
        raise ValueError(f"{label} fields differ from the frozen schema")
    return value


def _require_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or _HEX_SHA256.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _evaluator_contract_sha256(planned: Json) -> str:
    resolved = planned.get("resolved_inputs")
    frozen = (
        resolved.get("frozen_component_bindings")
        if isinstance(resolved, dict) else None
    )
    pin = frozen.get("evaluator_bundle") if isinstance(frozen, dict) else None
    if not isinstance(pin, str) or "@sha256:" not in pin:
        raise ValueError("planned evaluator contract is not hash-pinned")
    digest = pin.rsplit("@sha256:", 1)[1]
    return _require_sha256(digest, "planned evaluator contract hash")


def _validate_observer(observer: object) -> None:
    value = _require_exact_fields(observer, _OBSERVER_FIELDS, "evaluator observer")
    for field in ("provider", "model", "model_revision_status"):
        if not isinstance(value[field], str) or not value[field].strip():
            raise ValueError(f"evaluator observer.{field} must be non-empty")
    for field in ("model_revision", "request_id"):
        if value[field] is not None and not isinstance(value[field], str):
            raise ValueError(f"evaluator observer.{field} must be a string or null")


def _validate_bindings(report: Json, planned: Json, attempt: Json) -> None:
    bindings = _require_exact_fields(
        report.get("bindings"), _BINDING_FIELDS, "evaluator report bindings",
    )
    kind = planned.get("kind")
    expected = {
        "corpus_run_id": planned.get("corpus_run_id"),
        "resolved_inputs_sha256": planned.get("resolved_inputs_sha256"),
        "kind": kind,
        "evaluation_id": planned.get("evaluation_id"),
        "operation_class": planned.get("operation_class"),
        "source_filename": planned.get("source_filename"),
        "attempt": attempt.get("attempt"),
        "source_image_sha256": attempt.get("source_image_sha256"),
        "candidate_image_sha256": attempt.get("candidate_image_sha256"),
        "mask_image_sha256": (
            attempt.get("mask_image_sha256") if kind == "edit" else None
        ),
        "evaluator_contract_sha256": _evaluator_contract_sha256(planned),
    }
    if bindings != expected:
        raise ValueError("evaluator report bindings differ from the frozen attempt")
    for field in (
        "resolved_inputs_sha256",
        "source_image_sha256",
        "candidate_image_sha256",
        "evaluator_contract_sha256",
    ):
        _require_sha256(bindings[field], f"evaluator report bindings.{field}")
    if kind == "edit":
        _require_sha256(
            bindings["mask_image_sha256"],
            "evaluator report bindings.mask_image_sha256",
        )


def validate_and_replay_evaluator_report(
    report: Json,
    planned: Json,
    attempt: Json,
) -> Json:
    """Validate one retained report and return canonical machine projections.

    The function performs no provider calls.  ``attempt`` supplies only exact
    artifact identity; stored score/outcome fields are deliberately ignored.
    """

    value = _require_exact_fields(report, _REPORT_FIELDS, "evaluator report")
    encoded = json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")
    if len(encoded) > MAX_EVALUATOR_REPORT_BYTES:
        raise ValueError("evaluator report exceeds the frozen size limit")
    if value.get("schema_version") != EVALUATOR_REPORT_SCHEMA:
        raise ValueError("evaluator report schema_version is unsupported")
    _validate_bindings(value, planned, attempt)
    _validate_observer(value.get("observer"))

    resolved = planned.get("resolved_inputs")
    scoring = resolved.get("scoring") if isinstance(resolved, dict) else None
    if not isinstance(scoring, dict):
        raise ValueError("planned scoring contract is unavailable")
    metric = value.get("metric")
    if metric != scoring.get("metric"):
        raise ValueError("evaluator report metric differs from the frozen plan")
    verdict = derive_quality_verdict(value.get("quality_report"))
    accepted = verdict == "pass"
    common: Json = {
        "accepted": accepted,
        "attempt_outcome": "accepted" if accepted else "qa_failed",
        "provider_error_code": None,
        "qa_outcome": "pass" if accepted else "fail",
        "quality_verdict": verdict,
    }

    if planned.get("kind") == "render":
        evaluation = resolved.get("evaluation_contract")
        target = (
            evaluation.get("canonical_target_spec")
            if isinstance(evaluation, dict) else None
        )
        if not isinstance(target, dict):
            raise ValueError("render evaluator target spec is unavailable")
        scored = score_spec_conformance_from_observation(
            Spec.model_validate(target), value.get("observation"),
        )
        return {
            **common,
            "render_conformance_score": scored["score"],
            "hard_gate_pass": accepted,
            "render_components": scored["components"],
        }

    if planned.get("kind") != "edit":
        raise ValueError("evaluator report kind is unsupported")
    scored = score_edit_fidelity_from_observation(value.get("observation"))
    return {
        **common,
        "edit_fidelity_score": scored["score"],
        "severity": scored["severity"],
        "change_applied": scored["change_applied"],
        "static_hold": scored["static_hold"],
    }


__all__ = [
    "EVALUATOR_REPORT_SCHEMA",
    "MAX_EVALUATOR_REPORT_BYTES",
    "validate_and_replay_evaluator_report",
]

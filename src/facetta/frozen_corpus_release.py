"""Verify the founder's decision against one exact frozen-corpus result."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from facetta.frozen_corpus_gate import (
    file_sha256,
    validate_frozen_component_pins,
)


Json = dict[str, Any]

GATE_RESULT_SCHEMA = "facetta-frozen-corpus-gate-result.v1"
GATE_RUN_KIND = "provider_free_frozen_corpus_gate"
WORKLOAD_SCHEMA = "facetta-frozen-capture-workload.v1"
FROZEN_INTEGRITY_SOURCE_COUNT = 144
FROZEN_QUALITY_SOURCE_COUNT = 58
FROZEN_EVALUATION_SEQUENCE_COUNT = 1_044


def canonical_founder_approval_payload(approval: Json) -> bytes:
    unsigned = {key: value for key, value in approval.items() if key != "signature"}
    return json.dumps(
        unsigned, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")


def _load_object(path: Path) -> Json:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_value(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _pinned_workload(
    config: Json,
    repository_root: Path,
) -> tuple[Json | None, str | None, list[str]]:
    """Load the exact workload pinned by the frozen release configuration."""

    errors: list[str] = []
    frozen = config.get("frozen_components")
    value = frozen.get("capture_workload") if isinstance(frozen, dict) else None
    if not isinstance(value, str) or "@sha256:" not in value:
        return None, None, ["config capture_workload is not hash-pinned"]
    relative, expected_hash = value.rsplit("@sha256:", 1)
    root = repository_root.resolve()
    path = (root / relative).resolve()
    if (
        not relative
        or Path(relative).is_absolute()
        or not path.is_relative_to(root)
        or not path.is_file()
    ):
        return None, None, ["config capture_workload path is unavailable"]
    if not _sha256_value(expected_hash) or file_sha256(path) != expected_hash:
        return None, None, ["config capture_workload implementation drifted"]
    try:
        workload = _load_object(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return None, expected_hash, [f"pinned capture_workload is invalid: {exc}"]

    if workload.get("schema_version") != WORKLOAD_SCHEMA:
        errors.append("unsupported pinned capture_workload schema_version")
    if workload.get("config_id") != config.get("config_id"):
        errors.append("pinned capture_workload config_id differs from config")
    if workload.get("corpus_id") != config.get("corpus_id"):
        errors.append("pinned capture_workload corpus_id differs from config")
    if workload.get("manifest_sha256") != config.get("manifest_sha256"):
        errors.append("pinned capture_workload manifest hash differs from config")
    return workload, expected_hash, errors


def _workload_counts(workload: Json) -> tuple[int, int, int, list[str]]:
    """Derive frozen scope from workload rows instead of result summaries."""

    errors: list[str] = []
    sources = workload.get("sources")
    if not isinstance(sources, list) or not all(
        isinstance(row, dict) for row in sources
    ):
        return 0, 0, 0, ["pinned capture_workload sources are invalid"]
    source_rows: list[Json] = sources
    names = [row.get("filename") for row in source_rows]
    if any(not isinstance(name, str) or not name for name in names):
        errors.append("pinned capture_workload has an invalid source filename")
    if len(set(names)) != len(names):
        errors.append("pinned capture_workload has duplicate sources")
    if any(row.get("integrity_required") is not True for row in source_rows):
        errors.append("pinned capture_workload does not require every source integrity")

    evaluation_set_id = workload.get("ring_quality_evaluation_set_id")
    evaluation_sets = workload.get("evaluation_sets")
    evaluations = (
        evaluation_sets.get(evaluation_set_id)
        if isinstance(evaluation_sets, dict) and isinstance(evaluation_set_id, str)
        else None
    )
    if not isinstance(evaluations, list) or not evaluations or not all(
        isinstance(row, dict) for row in evaluations
    ):
        errors.append("pinned capture_workload quality evaluation set is invalid")
        evaluations = []
    evaluation_keys = [
        (row.get("kind"), row.get("evaluation_id")) for row in evaluations
    ]
    if any(
        kind not in {"render", "edit"}
        or not isinstance(evaluation_id, str)
        or not evaluation_id
        for kind, evaluation_id in evaluation_keys
    ):
        errors.append("pinned capture_workload has an invalid quality evaluation")
    if len(set(evaluation_keys)) != len(evaluation_keys):
        errors.append("pinned capture_workload has duplicate quality evaluations")

    quality_assignment = {
        "slice": "ring", "evaluation_set_id": evaluation_set_id,
    }
    quality_sources = [
        row for row in source_rows if row.get("quality") == quality_assignment
    ]
    if any(
        row.get("quality") not in (None, quality_assignment) for row in source_rows
    ):
        errors.append("pinned capture_workload has an unknown quality assignment")
    integrity_count = len(source_rows)
    quality_count = len(quality_sources)
    assignment_count = quality_count * len(evaluations)
    if workload.get("expected_integrity_source_count") != integrity_count:
        errors.append("pinned capture_workload integrity count is inconsistent")
    if workload.get("expected_quality_source_count") != quality_count:
        errors.append("pinned capture_workload quality count is inconsistent")
    if integrity_count != FROZEN_INTEGRITY_SOURCE_COUNT:
        errors.append("frozen workload must contain exactly 144 integrity sources")
    if quality_count != FROZEN_QUALITY_SOURCE_COUNT:
        errors.append("frozen workload must contain exactly 58 quality sources")
    if assignment_count != FROZEN_EVALUATION_SEQUENCE_COUNT:
        errors.append("frozen workload must contain exactly 1,044 quality assignments")
    return integrity_count, quality_count, assignment_count, errors


def _validate_compiled_result_internals(
    results: Json,
    config: Json,
    workload_hash: str | None,
    integrity_count: int,
    quality_count: int,
    assignment_count: int,
) -> list[str]:
    """Fail closed unless the result contains the compiler's full pass proof."""

    errors: list[str] = []
    if results.get("provider_calls") != 0:
        errors.append("frozen-corpus result provider_calls must be zero")

    reviewer_key = config.get("reviewer_public_key")
    configured_reviewer_key_id = (
        reviewer_key.get("key_id") if isinstance(reviewer_key, dict) else None
    )
    evidence = results.get("evidence")
    if not isinstance(evidence, dict) or not (
        evidence.get("schema_version") == "facetta-frozen-replay.v1"
        and _sha256_value(evidence.get("sha256"))
        and evidence.get("workload_sha256") == workload_hash
        and _sha256_value(evidence.get("capture_sha256"))
        and isinstance(configured_reviewer_key_id, str)
        and bool(configured_reviewer_key_id.strip())
        and evidence.get("reviewer_key_id") == configured_reviewer_key_id
    ):
        errors.append("frozen-corpus signed replay binding is incomplete or mismatched")

    definition = results.get("definition")
    if not isinstance(definition, dict) or not (
        definition.get("status") == "pass" and definition.get("errors") == []
    ):
        errors.append("frozen-corpus definition evidence is not a clean pass")

    workload = results.get("workload")
    expected_evaluations_per_source = (
        assignment_count // quality_count if quality_count else 0
    )
    if not isinstance(workload, dict) or not (
        workload.get("status") == "pass"
        and workload.get("sha256") == workload_hash
        and workload.get("integrity_source_count") == integrity_count
        and workload.get("quality_source_count") == quality_count
        and workload.get("quality_evaluations_per_source")
        == expected_evaluations_per_source
    ):
        errors.append("frozen-corpus workload evidence does not match pinned scope")

    source_integrity = results.get("source_integrity")
    if not isinstance(source_integrity, dict) or not (
        source_integrity.get("status") == "pass"
        and source_integrity.get("expected") == integrity_count
        and source_integrity.get("verified") == integrity_count
        and source_integrity.get("failures") == []
    ):
        errors.append("frozen-corpus source integrity is not a clean full-count pass")

    quality = results.get("quality")
    if not isinstance(quality, dict):
        return errors + ["frozen-corpus quality evidence is missing"]
    if quality.get("status") != "pass" or quality.get("errors") != []:
        errors.append("frozen-corpus quality evidence is not a clean pass")
    signature = quality.get("signature")
    if not isinstance(signature, dict) or not (
        signature.get("status") == "verified"
        and signature.get("key_id") == configured_reviewer_key_id
    ):
        errors.append("frozen-corpus replay signature is not verified")
    coverage = quality.get("source_coverage")
    if not isinstance(coverage, dict) or not (
        coverage.get("status") == "pass"
        and coverage.get("expected_source_count") == quality_count
        and coverage.get("completed_source_count") == quality_count
        and coverage.get("failed_source_count") == 0
        and coverage.get("missing_source_filenames") == []
        and coverage.get("errors") == []
    ):
        errors.append("frozen-corpus quality source coverage is not a clean full-count pass")
    if not (
        quality.get("integrity_source_count") == integrity_count
        and quality.get("quality_source_count") == quality_count
        and quality.get("expected_evaluation_count") == assignment_count
        and quality.get("completed_evaluation_count") == assignment_count
    ):
        errors.append("frozen-corpus quality assignment counts do not match pinned scope")
    if quality.get("reviewer_review_complete") is not True:
        errors.append("frozen-corpus GIA reviewer evidence is incomplete")
    if quality.get("all_reviewer_decisions_accepted") is not True:
        errors.append("frozen-corpus reviewer decisions are not all accepted")
    if quality.get("all_outside_mask_drift_pass") is not True:
        errors.append("frozen-corpus outside-mask replay is not a clean pass")

    release_gates = quality.get("release_gates")
    required_release_gates = (
        "hard_gate_pass", "spec_render_conformance_pass",
        "all_localized_edits_within_three_attempts", "edit_fidelity_pass",
        "zero_major_unintended_drift", "persistence_evidence_verified",
        "zero_rejected_candidates_persisted", "automated_gates_pass",
    )
    if not isinstance(release_gates, dict) or any(
        release_gates.get(gate) is not True for gate in required_release_gates
    ):
        errors.append("frozen-corpus release gates are not all passing")
    classified = quality.get("classified_release_gates")
    if not isinstance(classified, dict) or any(
        not isinstance(classified.get(name), dict)
        or classified[name].get("pass") is not True
        for name in ("quick_appearance", "structural")
    ):
        errors.append("frozen-corpus classified release gates are not all passing")
    return errors


def _public_key(config: Json, repository_root: Path) -> tuple[Ed25519PublicKey | None, str | None, str | None]:
    configured = config.get("founder_public_key")
    if not isinstance(configured, dict):
        return None, None, "founder public key is not configured"
    key_id = configured.get("key_id")
    relative = configured.get("path")
    if not isinstance(key_id, str) or not key_id.strip() or not isinstance(relative, str):
        return None, None, "founder public-key configuration is incomplete"
    root = repository_root.resolve()
    path = (root / relative).resolve()
    if (
        Path(relative).is_absolute()
        or not path.is_relative_to(root)
        or not path.is_file()
        or file_sha256(path) != configured.get("sha256")
    ):
        return None, key_id, "founder public-key file failed its configured hash"
    try:
        content = path.read_bytes()
        if len(content) == 32:
            return Ed25519PublicKey.from_public_bytes(content), key_id, None
        key = load_pem_public_key(content)
        if not isinstance(key, Ed25519PublicKey):
            return None, key_id, "configured founder key is not Ed25519"
        return key, key_id, None
    except (TypeError, ValueError) as exc:
        return None, key_id, f"founder public key is invalid: {exc}"


def verify_frozen_corpus_release(
    results_path: Path,
    config_path: Path,
    approval_path: Path,
    *,
    repository_root: Path | None = None,
) -> Json:
    results = _load_object(results_path)
    config = _load_object(config_path)
    approval = _load_object(approval_path)
    errors: list[str] = []
    results_hash = file_sha256(results_path)
    config_hash = file_sha256(config_path)
    root = repository_root or Path(__file__).resolve().parents[2]

    if results.get("schema_version") != GATE_RESULT_SCHEMA:
        errors.append("unsupported frozen-corpus gate result schema_version")
    if results.get("run_kind") != GATE_RUN_KIND:
        errors.append("unsupported frozen-corpus gate result run_kind")
    if (
        results.get("status") != "pass"
        or results.get("corpus_gate_ready") is not True
    ):
        errors.append("frozen-corpus technical/GIA result is not release-ready")
    if config.get("schema_version") != "facetta-frozen-gate-config.v1":
        errors.append("unsupported frozen-corpus config schema_version")

    pinned_workload, workload_hash, workload_errors = _pinned_workload(config, root)
    errors.extend(workload_errors)
    integrity_count = quality_count = assignment_count = 0
    if pinned_workload is not None:
        (
            integrity_count,
            quality_count,
            assignment_count,
            count_errors,
        ) = _workload_counts(pinned_workload)
        errors.extend(count_errors)
    errors.extend(_validate_compiled_result_internals(
        results,
        config,
        workload_hash,
        integrity_count,
        quality_count,
        assignment_count,
    ))

    result_manifest = results.get("manifest")
    result_config = results.get("config")
    result_implementation = results.get("implementation")
    manifest_hash = (
        result_manifest.get("sha256")
        if isinstance(result_manifest, dict) else None
    )
    result_config_hash = (
        result_config.get("sha256")
        if isinstance(result_config, dict) else None
    )
    result_components = (
        result_implementation.get("frozen_components")
        if isinstance(result_implementation, dict) else None
    )
    configured_components = config.get("frozen_components")
    if not _sha256_value(manifest_hash):
        errors.append("frozen-corpus result lacks a valid manifest SHA-256")
    elif config.get("manifest_sha256") != manifest_hash:
        errors.append("frozen-corpus result manifest hash differs from config")
    if not _sha256_value(result_config_hash):
        errors.append("frozen-corpus result lacks a valid config SHA-256")
    elif result_config_hash != config_hash:
        errors.append("frozen-corpus result does not bind the exact config bytes")
    result_corpus_id = (
        result_manifest.get("corpus_id")
        if isinstance(result_manifest, dict) else None
    )
    if (
        not isinstance(result_corpus_id, str)
        or result_corpus_id != config.get("corpus_id")
    ):
        errors.append("frozen-corpus result corpus_id differs from config")
    if not isinstance(configured_components, dict):
        errors.append("frozen-corpus config lacks frozen implementation pins")
    elif result_components != configured_components:
        errors.append("frozen-corpus result implementation pins differ from config")
    errors.extend(validate_frozen_component_pins(config, root))
    if approval.get("schema_version") != "facetta-founder-approval.v1":
        errors.append("unsupported founder approval schema_version")
    if approval.get("results_sha256") != results_hash:
        errors.append("founder approval does not bind the exact results bytes")
    if approval.get("decision") != "approved":
        errors.append("founder decision is not approved")
    for field in ("founder", "approved_at", "release_ticket"):
        value = approval.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"founder approval {field} is missing")
    approved_at = approval.get("approved_at")
    if isinstance(approved_at, str):
        try:
            parsed = datetime.fromisoformat(approved_at.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError
        except ValueError:
            errors.append("founder approval approved_at must include a timezone")

    public_key, key_id, key_error = _public_key(config, root)
    signature = approval.get("signature")
    signature_status = "not_verified"
    if key_error:
        errors.append(key_error)
    elif not isinstance(signature, dict):
        errors.append("founder approval is unsigned")
    elif (
        signature.get("algorithm") != "Ed25519"
        or signature.get("key_id") != key_id
        or not isinstance(signature.get("value"), str)
    ):
        errors.append("founder approval signature metadata is invalid")
    else:
        try:
            assert public_key is not None
            public_key.verify(
                base64.b64decode(signature["value"], validate=True),
                canonical_founder_approval_payload(approval),
            )
            signature_status = "verified"
        except (InvalidSignature, ValueError, TypeError):
            errors.append("founder approval signature is invalid")

    passed = not errors and signature_status == "verified"
    result_evidence = results.get("evidence")
    return {
        "schema_version": "facetta-frozen-corpus-release-decision.v2",
        "status": "pass" if passed else "incomplete_or_failed",
        "corpus_gate_ready": passed,
        "release_boundary": (
            "This decision satisfies only the signed frozen-corpus gate. "
            "External beta also requires a separately verified live "
            "two-principal staging-isolation result."
        ),
        "provider_calls": 0,
        "gate_bindings": {
            "results_sha256": results_hash,
            "manifest_sha256": manifest_hash,
            "config_sha256": config_hash,
            "workload_sha256": workload_hash,
            "replay_sha256": (
                result_evidence.get("sha256")
                if isinstance(result_evidence, dict) else None
            ),
            "capture_sha256": (
                result_evidence.get("capture_sha256")
                if isinstance(result_evidence, dict) else None
            ),
            "reviewer_key_id": (
                result_evidence.get("reviewer_key_id")
                if isinstance(result_evidence, dict) else None
            ),
            "derived_scope": {
                "integrity_source_count": integrity_count,
                "quality_source_count": quality_count,
                "quality_assignment_count": assignment_count,
            },
            "config_id": config.get("config_id"),
            "corpus_id": result_corpus_id,
            "implementation_pins_sha256": (
                _canonical_sha256(configured_components)
                if isinstance(configured_components, dict) else None
            ),
        },
        "approval_sha256": file_sha256(approval_path),
        "founder_signature": {"status": signature_status, "key_id": key_id},
        "errors": errors,
    }

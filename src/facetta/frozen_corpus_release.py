"""Verify the founder's decision against one exact frozen-corpus result."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from facetta.frozen_corpus_gate import (
    REPLAY_SCHEMA,
    compile_frozen_corpus_gate,
    file_sha256,
    release_authority_key_separation,
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
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    """Serialize JSON deterministically for semantic byte comparison."""

    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")


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
    evidence_corpus_run_id = (
        evidence.get("corpus_run_id") if isinstance(evidence, dict) else None
    )
    if not isinstance(evidence, dict) or not (
        evidence.get("schema_version") == REPLAY_SCHEMA
        and _sha256_value(evidence.get("sha256"))
        and evidence.get("workload_sha256") == workload_hash
        and _sha256_value(evidence.get("capture_sha256"))
        and isinstance(evidence_corpus_run_id, str)
        and bool(evidence_corpus_run_id.strip())
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
    execution_count = quality.get("execution_ready_evaluation_count")
    not_applicable_count = quality.get("not_applicable_evaluation_count")
    if not (
        type(execution_count) is int
        and execution_count >= 0
        and type(not_applicable_count) is int
        and not_applicable_count >= 0
        and execution_count + not_applicable_count == assignment_count
    ):
        errors.append(
            "frozen-corpus execution-ready and not-applicable counts do not "
            "resolve the pinned scope"
        )
        execution_count = -1
        not_applicable_count = -1
    not_applicable_rows = quality.get("not_applicable_assignments")
    expected_not_applicable_fields = {
        "kind", "evaluation_id", "operation_class", "source_filename",
        "source_sha256", "resolved_inputs_sha256", "reason",
        "review_evidence_sha256",
    }
    not_applicable_projection_valid = (
        isinstance(not_applicable_rows, list)
        and len(not_applicable_rows) == not_applicable_count
        and all(
            isinstance(row, dict)
            and set(row) == expected_not_applicable_fields
            and row.get("kind") == "edit"
            and all(
                isinstance(row.get(field), str) and bool(row[field].strip())
                for field in (
                    "evaluation_id", "operation_class", "source_filename",
                    "reason",
                )
            )
            and all(
                _sha256_value(row.get(field))
                for field in (
                    "source_sha256", "resolved_inputs_sha256",
                    "review_evidence_sha256",
                )
            )
            for row in not_applicable_rows
        )
    )
    if not_applicable_projection_valid:
        projection_keys = {
            (row["kind"], row["evaluation_id"], row["source_filename"])
            for row in not_applicable_rows
        }
        not_applicable_projection_valid = (
            len(projection_keys) == len(not_applicable_rows)
        )
    if not not_applicable_projection_valid:
        errors.append(
            "frozen-corpus not-applicable assignment projection is incomplete"
        )
    if quality.get("reviewer_review_complete") is not True:
        errors.append("frozen-corpus GIA reviewer evidence is incomplete")
    if quality.get("all_reviewer_decisions_accepted") is not True:
        errors.append("frozen-corpus reviewer decisions are not all accepted")
    blind_review = quality.get("blind_review")
    blind_binding = results.get("blind_review_evidence")
    reviewer_profile_sha256 = (
        reviewer_key.get("reviewer_profile_sha256")
        if isinstance(reviewer_key, dict) else None
    )
    if not isinstance(blind_review, dict) or not (
        blind_review.get("schema_version")
        == "facetta-blind-jewelry-review-ledger-validation.v2"
        and blind_review.get("status") == "pass"
        and blind_review.get("signature_status") == "verified"
        and blind_review.get("reviewer_profile_sha256")
        == reviewer_profile_sha256
        and blind_review.get("accepted_count") == execution_count
        and blind_review.get("accepted_rate") == 1.0
        and isinstance(blind_review.get("decisions"), list)
        and len(blind_review["decisions"]) == execution_count
        and blind_review.get("errors") == []
    ):
        errors.append("frozen-corpus blind GIA criterion review is not a clean pass")
    if not isinstance(blind_binding, dict) or not (
        _sha256_value(blind_binding.get("packet_file_sha256"))
        and _sha256_value(blind_binding.get("packet_canonical_sha256"))
        and _sha256_value(blind_binding.get("ledger_file_sha256"))
        and blind_review.get("packet_sha256")
        == blind_binding.get("packet_canonical_sha256")
    ):
        errors.append("frozen-corpus blind GIA artifact binding is incomplete")
    if quality.get("all_outside_mask_drift_pass") is not True:
        errors.append("frozen-corpus outside-mask replay is not a clean pass")
    runner_key = config.get("canonical_api_runner_public_key")
    runner_key_id = (
        runner_key.get("key_id") if isinstance(runner_key, dict) else None
    )
    persistence = quality.get("persistence_attestation")
    persistence_signature = (
        persistence.get("signature") if isinstance(persistence, dict) else None
    )
    persistence_bindings = (
        persistence.get("bindings") if isinstance(persistence, dict) else None
    )
    persistence_checks = (
        persistence.get("checks") if isinstance(persistence, dict) else None
    )
    compiled_config = results.get("config")
    compiled_config_hash = (
        compiled_config.get("sha256")
        if isinstance(compiled_config, dict) else None
    )
    if not isinstance(persistence, dict) or not (
        persistence.get("schema_version")
        == "facetta-canonical-persistence-verification.v1"
        and persistence.get("status") == "pass"
        and persistence.get("errors") == []
        and persistence.get("provider_calls") == 0
        and isinstance(persistence_signature, dict)
        and persistence_signature.get("status") == "verified"
        and isinstance(runner_key_id, str)
        and bool(runner_key_id.strip())
        and persistence_signature.get("key_id") == runner_key_id
        and isinstance(persistence_bindings, dict)
        and persistence_bindings.get("config_id") == config.get("config_id")
        and persistence_bindings.get("config_sha256")
        == compiled_config_hash
        and persistence_bindings.get("workload_sha256") == workload_hash
        and persistence_bindings.get("corpus_id") == config.get("corpus_id")
        and persistence_bindings.get("result_count") == execution_count
        and _sha256_value(persistence_bindings.get("result_set_sha256"))
        and isinstance(persistence_bindings.get("corpus_run_id"), str)
        and persistence_bindings.get("corpus_run_id") == evidence_corpus_run_id
        and isinstance(persistence_checks, dict)
        and all(persistence_checks.get(check) is True for check in (
            "atomic_image_spec_persistence", "stale_write_rejection",
            "zero_rejected_candidates_persisted",
        ))
    ):
        errors.append("frozen-corpus signed persistence attestation is not a clean pass")

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


def _reverify_retained_results(
    results: Json,
    config: Json,
    *,
    manifest_path: Path | None,
    config_path: Path,
    source_dir: Path | None,
    evidence_path: Path | None,
    evidence_root: Path | None,
    workload_path: Path | None,
    gia_review_packet_path: Path | None,
    gia_review_ledger_path: Path | None,
    repository_root: Path,
    workload_hash: str | None,
    integrity_count: int,
    quality_count: int,
    assignment_count: int,
) -> Json:
    """Recompile one retained result from its raw, signed evidence.

    A retained result is a cache, not authority.  The compiler reopens the
    confined replay and independently verifies the GIA-reviewer and canonical
    API persistence signatures.  Canonical JSON bytes must then match the
    retained result exactly.  This remains provider-free.
    """

    retained_bytes = _canonical_json_bytes(results)
    summary: Json = {
        "status": "not_run",
        "compiler": "compile_frozen_corpus_gate",
        "provider_calls": 0,
        "matches_retained_results": False,
        "retained_results_canonical_sha256": hashlib.sha256(
            retained_bytes
        ).hexdigest(),
        "recomputed_results_canonical_sha256": None,
        "errors": [],
    }
    required = {
        "manifest_path": manifest_path,
        "source_dir": source_dir,
        "evidence_path": evidence_path,
        "evidence_root": evidence_root,
        "workload_path": workload_path,
        "gia_review_packet_path": gia_review_packet_path,
        "gia_review_ledger_path": gia_review_ledger_path,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        summary["errors"] = [
            "raw frozen-corpus evidence inputs are required: "
            + ", ".join(missing)
        ]
        return summary

    try:
        assert manifest_path is not None
        assert source_dir is not None
        assert evidence_path is not None
        assert evidence_root is not None
        assert workload_path is not None
        recomputed = compile_frozen_corpus_gate(
            manifest_path,
            config_path,
            source_dir,
            evidence_path,
            repository_root=repository_root,
            workload_path=workload_path,
            evidence_root=evidence_root,
            review_packet_path=gia_review_packet_path,
            review_ledger_path=gia_review_ledger_path,
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        summary["status"] = "fail"
        summary["errors"] = [
            f"raw frozen-corpus evidence could not be recomputed: {exc}"
        ]
        return summary

    recomputed_bytes = _canonical_json_bytes(recomputed)
    summary["recomputed_results_canonical_sha256"] = hashlib.sha256(
        recomputed_bytes
    ).hexdigest()
    summary["matches_retained_results"] = hmac.compare_digest(
        retained_bytes, recomputed_bytes
    )
    compiler_provider_calls = recomputed.get("provider_calls")
    summary["provider_calls"] = compiler_provider_calls

    revalidation_errors: list[str] = []
    if compiler_provider_calls != 0:
        revalidation_errors.append(
            "recomputed frozen-corpus gate provider_calls must be zero"
        )
    if (
        recomputed.get("status") != "pass"
        or recomputed.get("corpus_gate_ready") is not True
    ):
        revalidation_errors.append(
            "recomputed frozen-corpus technical/GIA result is not release-ready"
        )
    for section_name in ("definition", "quality"):
        section = recomputed.get(section_name)
        section_errors = (
            section.get("errors") if isinstance(section, dict) else None
        )
        if isinstance(section_errors, list):
            for error in section_errors:
                if isinstance(error, str) and error:
                    revalidation_errors.append(
                        f"recomputed {section_name}: {error}"
                    )
    for error in _validate_compiled_result_internals(
        recomputed,
        config,
        workload_hash,
        integrity_count,
        quality_count,
        assignment_count,
    ):
        revalidation_errors.append(f"recomputed result: {error}")
    if summary["matches_retained_results"] is not True:
        revalidation_errors.append(
            "recomputed frozen-corpus result does not byte-match retained results"
        )

    summary["errors"] = revalidation_errors
    summary["status"] = "pass" if not revalidation_errors else "fail"
    return summary


def verify_frozen_corpus_release(
    results_path: Path,
    config_path: Path,
    approval_path: Path,
    *,
    repository_root: Path | None = None,
    manifest_path: Path | None = None,
    source_dir: Path | None = None,
    evidence_path: Path | None = None,
    evidence_root: Path | None = None,
    workload_path: Path | None = None,
    gia_review_packet_path: Path | None = None,
    gia_review_ledger_path: Path | None = None,
) -> Json:
    results = _load_object(results_path)
    config = _load_object(config_path)
    approval = _load_object(approval_path)
    errors: list[str] = []
    results_hash = file_sha256(results_path)
    config_hash = file_sha256(config_path)
    root = repository_root or Path(__file__).resolve().parents[2]
    authority_key_separation = release_authority_key_separation(config)
    errors.extend(authority_key_separation["errors"])

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

    evidence_reverification = _reverify_retained_results(
        results,
        config,
        manifest_path=manifest_path,
        config_path=config_path,
        source_dir=source_dir,
        evidence_path=evidence_path,
        evidence_root=evidence_root,
        workload_path=workload_path,
        gia_review_packet_path=gia_review_packet_path,
        gia_review_ledger_path=gia_review_ledger_path,
        repository_root=root,
        workload_hash=workload_hash,
        integrity_count=integrity_count,
        quality_count=quality_count,
        assignment_count=assignment_count,
    )
    errors.extend(map(str, evidence_reverification["errors"]))

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
    result_quality = results.get("quality")
    execution_ready_count = (
        result_quality.get("execution_ready_evaluation_count")
        if isinstance(result_quality, dict) else None
    )
    not_applicable_count = (
        result_quality.get("not_applicable_evaluation_count")
        if isinstance(result_quality, dict) else None
    )
    not_applicable_assignments = (
        result_quality.get("not_applicable_assignments")
        if isinstance(result_quality, dict) else None
    )
    result_persistence = (
        result_quality.get("persistence_attestation")
        if isinstance(result_quality, dict) else None
    )
    persistence_bindings = (
        result_persistence.get("bindings")
        if isinstance(result_persistence, dict) else None
    )
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
            "corpus_run_id": (
                result_evidence.get("corpus_run_id")
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
                "execution_ready_quality_assignment_count": (
                    execution_ready_count
                ),
                "not_applicable_quality_assignment_count": (
                    not_applicable_count
                ),
            },
            "not_applicable_projection_sha256": (
                _canonical_sha256(not_applicable_assignments)
                if isinstance(not_applicable_assignments, list) else None
            ),
            "persistence_attestation": (
                persistence_bindings
                if isinstance(persistence_bindings, dict) else None
            ),
            "config_id": config.get("config_id"),
            "corpus_id": result_corpus_id,
            "implementation_pins_sha256": (
                _canonical_sha256(configured_components)
                if isinstance(configured_components, dict) else None
            ),
        },
        "approval_sha256": file_sha256(approval_path),
        "evidence_reverification": evidence_reverification,
        "authority_key_separation": authority_key_separation,
        "founder_signature": {"status": signature_status, "key_id": key_id},
        "errors": errors,
    }

"""Verify signed canonical-API persistence evidence for a frozen corpus run.

The attestation is provider-free.  It proves that an enrolled canonical API
runner exercised persistence behavior against the exact selected result set;
it does not infer persistence safety from image scores or reviewer approval.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key


Json = dict[str, Any]
ATTESTATION_SCHEMA = "facetta-canonical-persistence-attestation.v1"
CANONICAL_API_SCHEMA = "facetta-canonical-project-api.v1"
RESULT_SET_SCHEMA = "facetta-frozen-selected-result-set.v1"


def canonical_attestation_payload(attestation: Json) -> bytes:
    unsigned = {
        key: value for key, value in attestation.items() if key != "signature"
    }
    return json.dumps(
        unsigned, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")


def canonical_result_set(rows: list[Json]) -> list[Json]:
    """Return the strict, deterministic selected-result projection."""

    projected = [
        {
            "kind": row.get("kind"),
            "evaluation_id": row.get("evaluation_id"),
            "source_filename": row.get("source_filename"),
            "selected_attempt": row.get("selected_attempt"),
            "candidate_image_sha256": row.get("candidate_image_sha256"),
        }
        for row in rows
    ]
    return sorted(projected, key=lambda row: (
        str(row["kind"]), str(row["evaluation_id"]),
        str(row["source_filename"]),
    ))


def result_set_sha256(rows: list[Json]) -> str:
    payload = {
        "schema_version": RESULT_SET_SCHEMA,
        "results": canonical_result_set(rows),
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _result_set_errors(rows: list[Json], *, label: str) -> list[str]:
    errors: list[str] = []
    keys: list[tuple[str, str, str]] = []
    for index, row in enumerate(rows):
        kind = row.get("kind")
        evaluation_id = row.get("evaluation_id")
        source_filename = row.get("source_filename")
        attempt = row.get("selected_attempt")
        digest = row.get("candidate_image_sha256")
        if kind not in {"render", "edit"}:
            errors.append(f"{label} result {index} kind is invalid")
        if not isinstance(evaluation_id, str) or not evaluation_id.strip():
            errors.append(f"{label} result {index} evaluation_id is invalid")
        if (
            not isinstance(source_filename, str)
            or not source_filename.strip()
            or Path(source_filename).name != source_filename
        ):
            errors.append(f"{label} result {index} source_filename is invalid")
        if type(attempt) is not int or attempt < 1:
            errors.append(f"{label} result {index} selected_attempt is invalid")
        if not _sha256_value(digest):
            errors.append(
                f"{label} result {index} candidate_image_sha256 is invalid"
            )
        keys.append((str(kind), str(evaluation_id), str(source_filename)))
    if len(set(keys)) != len(keys):
        errors.append(f"{label} result_set contains duplicate assignments")
    return errors


def _sha256_value(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _git_sha(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) in {40, 64}
        and all(character in "0123456789abcdef" for character in value)
    )


def _load_runner_key(
    config: Json,
    repository_root: Path,
) -> tuple[Ed25519PublicKey | None, str | None, str | None]:
    enrolled = config.get("canonical_api_runner_public_key")
    if not isinstance(enrolled, dict):
        return None, None, "canonical API runner public key is not configured"
    key_id = enrolled.get("key_id")
    relative = enrolled.get("path")
    expected_hash = enrolled.get("sha256")
    if not isinstance(key_id, str) or not key_id.strip():
        return None, None, "canonical API runner key_id is missing"
    root = repository_root.resolve()
    path = (root / str(relative)).resolve() if isinstance(relative, str) else None
    if (
        path is None
        or not isinstance(relative, str)
        or Path(relative).is_absolute()
        or not path.is_relative_to(root)
        or not path.is_file()
    ):
        return None, key_id, "canonical API runner public-key file is unavailable"
    if not _sha256_value(expected_hash) or hashlib.sha256(
        path.read_bytes()
    ).hexdigest() != expected_hash:
        return None, key_id, "canonical API runner public-key hash differs from config"
    try:
        content = path.read_bytes()
        if len(content) == 32:
            return Ed25519PublicKey.from_public_bytes(content), key_id, None
        key = load_pem_public_key(content)
        if not isinstance(key, Ed25519PublicKey):
            return None, key_id, "canonical API runner key is not Ed25519"
        return key, key_id, None
    except (TypeError, ValueError) as exc:
        return None, key_id, f"canonical API runner public key is invalid: {exc}"


def verify_persistence_attestation(
    attestation: object,
    *,
    config: Json,
    repository_root: Path,
    config_sha256: str,
    workload_sha256: str,
    workload_id: str,
    corpus_id: str,
    expected_corpus_run_id: str,
    expected_result_set: list[Json],
) -> Json:
    """Verify one signed, run-bound canonical persistence attestation."""

    errors: list[str] = []
    value = attestation if isinstance(attestation, dict) else {}
    if value.get("schema_version") != ATTESTATION_SCHEMA:
        errors.append("unsupported canonical persistence attestation schema_version")
    if value.get("canonical_api_schema_version") != CANONICAL_API_SCHEMA:
        errors.append("canonical API schema version is missing or unsupported")
    if not _git_sha(value.get("commit_sha")):
        errors.append("canonical persistence commit_sha is invalid")
    for field in ("attestation_id",):
        field_value = value.get(field)
        if not isinstance(field_value, str) or not field_value.strip():
            errors.append(f"canonical persistence {field} is missing")
    if (
        not isinstance(expected_corpus_run_id, str)
        or not expected_corpus_run_id.strip()
        or value.get("corpus_run_id") != expected_corpus_run_id
    ):
        errors.append("canonical persistence corpus_run_id differs from signed capture")
    expected_bindings = {
        "config_id": config.get("config_id"),
        "config_sha256": config_sha256,
        "workload_id": workload_id,
        "workload_sha256": workload_sha256,
        "corpus_id": corpus_id,
    }
    for field, expected in expected_bindings.items():
        if value.get(field) != expected:
            errors.append(f"canonical persistence {field} differs from frozen run")

    expected_rows = canonical_result_set(expected_result_set)
    declared_rows = value.get("result_set")
    errors.extend(_result_set_errors(expected_rows, label="replay-selected"))
    if not isinstance(declared_rows, list) or not all(
        isinstance(row, dict) for row in declared_rows
    ):
        errors.append("canonical persistence result_set must be a list of objects")
        declared_rows = []
    else:
        errors.extend(_result_set_errors(declared_rows, label="attested"))
    if canonical_result_set(declared_rows) != expected_rows:
        errors.append("canonical persistence result_set differs from replay selections")
    result_hash = result_set_sha256(expected_rows)
    if value.get("result_set_schema_version") != RESULT_SET_SCHEMA:
        errors.append("canonical persistence result-set schema is unsupported")
    if value.get("result_set_sha256") != result_hash:
        errors.append("canonical persistence result-set hash differs")
    if value.get("result_count") != len(expected_rows) or not expected_rows:
        errors.append("canonical persistence result count is invalid")

    checks = value.get("checks")
    if not isinstance(checks, dict):
        checks = {}
        errors.append("canonical persistence checks are missing")
    atomic = checks.get("atomic_image_spec_persistence")
    if not isinstance(atomic, dict) or not (
        atomic.get("status") == "pass"
        and atomic.get("verified_result_count") == len(expected_rows)
        and atomic.get("image_and_spec_committed_together") is True
        and atomic.get("partial_commit_count") == 0
    ):
        errors.append("atomic image/spec persistence is not proven for the result set")
    stale = checks.get("stale_write_rejection")
    if not isinstance(stale, dict) or not (
        stale.get("status") == "pass"
        and type(stale.get("attempted_count")) is int
        and stale.get("attempted_count") > 0
        and stale.get("rejected_count") == stale.get("attempted_count")
        and stale.get("canonical_mutation_count") == 0
    ):
        errors.append("stale-write rejection is not proven")
    rejected = checks.get("rejected_candidate_persistence")
    if not isinstance(rejected, dict) or not (
        rejected.get("status") == "pass"
        and type(rejected.get("tested_rejected_candidate_count")) is int
        and rejected.get("tested_rejected_candidate_count") > 0
        and rejected.get("active_asset_count") == 0
    ):
        errors.append("zero rejected-candidate persistence is not proven")

    public_key, key_id, key_error = _load_runner_key(config, repository_root)
    signature = value.get("signature")
    signature_status = "not_verified"
    if key_error:
        errors.append(key_error)
    elif not isinstance(signature, dict):
        errors.append("canonical persistence attestation is unsigned")
    elif not (
        signature.get("algorithm") == "Ed25519"
        and signature.get("key_id") == key_id
        and isinstance(signature.get("value"), str)
    ):
        errors.append("canonical persistence signature metadata is invalid")
    else:
        try:
            assert public_key is not None
            public_key.verify(
                base64.b64decode(signature["value"], validate=True),
                canonical_attestation_payload(value),
            )
            signature_status = "verified"
        except (InvalidSignature, ValueError, TypeError):
            errors.append("canonical persistence signature is invalid")

    passed = not errors and signature_status == "verified"
    return {
        "schema_version": "facetta-canonical-persistence-verification.v1",
        "status": "pass" if passed else "fail",
        "errors": errors,
        "signature": {"status": signature_status, "key_id": key_id},
        "bindings": {
            "attestation_id": value.get("attestation_id"),
            "corpus_run_id": value.get("corpus_run_id"),
            "commit_sha": value.get("commit_sha"),
            "canonical_api_schema_version": value.get(
                "canonical_api_schema_version"
            ),
            **expected_bindings,
            "result_set_schema_version": RESULT_SET_SCHEMA,
            "result_set_sha256": result_hash,
            "result_count": len(expected_rows),
        },
        "checks": {
            "atomic_image_spec_persistence": passed and isinstance(atomic, dict),
            "stale_write_rejection": passed and isinstance(stale, dict),
            "zero_rejected_candidates_persisted": (
                passed and isinstance(rejected, dict)
            ),
        },
        "provider_calls": 0,
    }

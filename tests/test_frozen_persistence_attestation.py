from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from facetta.frozen_persistence_attestation import (
    canonical_attestation_payload,
    result_set_sha256,
    verify_persistence_attestation,
)


def _fixture(tmp_path: Path) -> dict[str, Any]:
    private_key = Ed25519PrivateKey.generate()
    public_key = tmp_path / "runner.pub"
    public_key.write_bytes(private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ))
    result_set = [{
        "kind": "edit",
        "evaluation_id": "metal-color",
        "source_filename": "ring-1.png",
        "selected_attempt": 2,
        "candidate_image_sha256": "a" * 64,
    }]
    value: dict[str, Any] = {
        "schema_version": "facetta-canonical-persistence-attestation.v1",
        "canonical_api_schema_version": "facetta-canonical-project-api.v1",
        "attestation_id": "attestation-1",
        "corpus_run_id": "corpus-run-1",
        "commit_sha": "b" * 40,
        "config_id": "config-1",
        "config_sha256": "c" * 64,
        "workload_id": "workload-1",
        "workload_sha256": "d" * 64,
        "corpus_id": "corpus-1",
        "result_set_schema_version": "facetta-frozen-selected-result-set.v1",
        "result_set": [dict(row) for row in result_set],
        "result_set_sha256": result_set_sha256(result_set),
        "result_count": 1,
        "checks": {
            "atomic_image_spec_persistence": {
                "status": "pass", "verified_result_count": 1,
                "image_and_spec_committed_together": True,
                "partial_commit_count": 0,
            },
            "stale_write_rejection": {
                "status": "pass", "attempted_count": 2,
                "rejected_count": 2, "canonical_mutation_count": 0,
            },
            "rejected_candidate_persistence": {
                "status": "pass", "tested_rejected_candidate_count": 3,
                "active_asset_count": 0,
            },
        },
    }
    value["signature"] = {
        "algorithm": "Ed25519",
        "key_id": "runner-v1",
        "value": base64.b64encode(private_key.sign(
            canonical_attestation_payload(value)
        )).decode("ascii"),
    }
    return {
        "attestation": value,
        "result_set": result_set,
        "config": {
            "config_id": "config-1",
            "canonical_api_runner_public_key": {
                "key_id": "runner-v1", "path": public_key.name,
                "sha256": hashlib.sha256(public_key.read_bytes()).hexdigest(),
            },
        },
        "root": tmp_path,
    }


def _verify(paths: dict[str, Any]) -> dict[str, Any]:
    return verify_persistence_attestation(
        paths["attestation"],
        config=paths["config"],
        repository_root=paths["root"],
        config_sha256="c" * 64,
        workload_sha256="d" * 64,
        workload_id="workload-1",
        corpus_id="corpus-1",
        expected_corpus_run_id="corpus-run-1",
        expected_result_set=paths["result_set"],
    )


def test_complete_signed_canonical_api_attestation_passes(tmp_path: Path):
    paths = _fixture(tmp_path)
    result = _verify(paths)
    assert result["status"] == "pass"
    assert result["signature"] == {"status": "verified", "key_id": "runner-v1"}
    assert result["bindings"]["commit_sha"] == "b" * 40
    assert result["bindings"]["corpus_run_id"] == "corpus-run-1"
    assert result["bindings"]["result_count"] == 1
    assert all(result["checks"].values())
    assert result["provider_calls"] == 0


def test_shallow_self_asserted_persistence_json_fails(tmp_path: Path):
    paths = _fixture(tmp_path)
    paths["attestation"] = {
        "verified": True,
        "method": "canonical_project_api_integration",
        "result_set": "test-result",
        "rejected_active_asset_count": 0,
    }
    result = _verify(paths)
    assert result["status"] == "fail"
    joined = " ".join(result["errors"])
    assert "schema_version" in joined
    assert "commit_sha" in joined
    assert "checks are missing" in joined
    assert "unsigned" in joined


@pytest.mark.parametrize(
    ("section", "field", "value", "expected_error"),
    [
        ("root", "config_sha256", "0" * 64, "config_sha256 differs"),
        ("root", "commit_sha", "main", "commit_sha is invalid"),
        (
            "atomic_image_spec_persistence", "partial_commit_count", 1,
            "atomic image/spec persistence",
        ),
        (
            "stale_write_rejection", "canonical_mutation_count", 1,
            "stale-write rejection",
        ),
        (
            "rejected_candidate_persistence", "active_asset_count", 1,
            "zero rejected-candidate persistence",
        ),
    ],
)
def test_tampered_binding_or_safety_check_fails(
    tmp_path: Path,
    section: str,
    field: str,
    value: object,
    expected_error: str,
):
    paths = _fixture(tmp_path)
    if section == "root":
        paths["attestation"][field] = value
    else:
        paths["attestation"]["checks"][section][field] = value
    result = _verify(paths)
    assert result["status"] == "fail"
    assert any(expected_error in error for error in result["errors"])
    assert result["signature"]["status"] == "not_verified"


def test_result_set_must_exactly_match_replay_selection(tmp_path: Path):
    paths = _fixture(tmp_path)
    paths["attestation"]["result_set"][0]["candidate_image_sha256"] = "e" * 64
    result = _verify(paths)
    assert result["status"] == "fail"
    assert any("result_set differs" in error for error in result["errors"])
    assert result["signature"]["status"] == "not_verified"


def test_corpus_run_id_must_match_signed_capture_provenance(tmp_path: Path):
    paths = _fixture(tmp_path)
    paths["attestation"]["corpus_run_id"] = "another-corpus-run"
    result = _verify(paths)
    assert result["status"] == "fail"
    assert any("corpus_run_id differs" in error for error in result["errors"])


def test_malformed_replay_result_digest_fails_closed(tmp_path: Path):
    paths = _fixture(tmp_path)
    paths["result_set"][0]["candidate_image_sha256"] = "not-a-digest"
    result = _verify(paths)
    assert result["status"] == "fail"
    assert any(
        "replay-selected result 0 candidate_image_sha256 is invalid" in error
        for error in result["errors"]
    )

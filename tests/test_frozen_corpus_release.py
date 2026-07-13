from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from facetta.frozen_corpus_release import (
    canonical_founder_approval_payload,
    verify_frozen_corpus_release,
)


def _json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> dict[str, Any]:
    private_key = Ed25519PrivateKey.generate()
    public_key = tmp_path / "founder.pub"
    public_key.write_bytes(private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ))
    components = tmp_path / "components"
    components.mkdir()
    component_files: dict[str, Path] = {}
    for name in (
        "ring_contract", "prompt_bundle", "evaluator_bundle", "live_runner",
        "replay_verifier", "replay_runner", "release_verifier",
        "packet_builder", "packet_runner",
    ):
        path = components / f"{name}.py"
        path.write_text(f"# frozen {name}\n")
        component_files[name] = path
    frozen_components = {
        name: f"components/{path.name}@sha256:{_sha(path)}"
        for name, path in component_files.items()
    } | {"routing": "captured-replay.v1"}
    manifest_hash = "a" * 64
    config = tmp_path / "config.json"
    _json(config, {
        "schema_version": "facetta-frozen-gate-config.v1",
        "config_id": "test-config",
        "corpus_id": "test-corpus",
        "manifest_sha256": manifest_hash,
        "frozen_components": frozen_components,
        "founder_public_key": {
            "key_id": "founder-v1", "path": public_key.name,
            "sha256": _sha(public_key),
        },
    })
    results = tmp_path / "results.json"
    _json(results, {
        "schema_version": "facetta-frozen-corpus-gate-result.v1",
        "run_kind": "provider_free_frozen_corpus_gate",
        "status": "pass",
        "corpus_gate_ready": True,
        "manifest": {"sha256": manifest_hash, "corpus_id": "test-corpus"},
        "config": {"sha256": _sha(config)},
        "implementation": {"frozen_components": frozen_components},
    })
    approval = tmp_path / "approval.json"
    value: dict[str, Any] = {
        "schema_version": "facetta-founder-approval.v1",
        "results_sha256": _sha(results),
        "decision": "approved",
        "founder": "Test Founder",
        "approved_at": "2026-07-13T12:00:00+08:00",
        "release_ticket": "FACETTA-TEST-1",
    }
    value["signature"] = {
        "algorithm": "Ed25519", "key_id": "founder-v1",
        "value": base64.b64encode(private_key.sign(
            canonical_founder_approval_payload(value)
        )).decode("ascii"),
    }
    _json(approval, value)
    return {
        "results": results, "config": config, "approval": approval,
        "root": tmp_path, "components": component_files,
    }


def _run(paths: dict[str, Any]) -> dict[str, Any]:
    return verify_frozen_corpus_release(
        paths["results"], paths["config"], paths["approval"],
        repository_root=paths["root"],
    )


def test_exact_signed_founder_decision_passes_corpus_gate_only(tmp_path: Path):
    paths = _fixture(tmp_path)
    result = _run(paths)
    assert result["schema_version"] == "facetta-frozen-corpus-release-decision.v2"
    assert result["corpus_gate_ready"] is True
    assert "external_beta_ready" not in result
    assert result["founder_signature"]["status"] == "verified"
    assert result["provider_calls"] == 0
    assert "two-principal staging-isolation" in result["release_boundary"]
    assert result["gate_bindings"]["results_sha256"] == _sha(paths["results"])
    assert result["gate_bindings"]["config_sha256"] == _sha(paths["config"])
    assert result["gate_bindings"]["manifest_sha256"] == "a" * 64
    assert len(result["gate_bindings"]["implementation_pins_sha256"]) == 64


def test_approval_for_different_result_fails(tmp_path: Path):
    paths = _fixture(tmp_path)
    results = json.loads(paths["results"].read_text())
    results["changed"] = True
    _json(paths["results"], results)
    result = _run(paths)
    assert result["corpus_gate_ready"] is False
    assert any("exact results bytes" in error for error in result["errors"])


def test_tampered_founder_decision_fails_signature(tmp_path: Path):
    paths = _fixture(tmp_path)
    approval = json.loads(paths["approval"].read_text())
    approval["release_ticket"] = "FACETTA-TAMPERED"
    _json(paths["approval"], approval)
    result = _run(paths)
    assert result["founder_signature"]["status"] == "not_verified"
    assert result["corpus_gate_ready"] is False


def test_non_ready_technical_result_cannot_be_approved(tmp_path: Path):
    paths = _fixture(tmp_path)
    results = json.loads(paths["results"].read_text())
    results.update({"status": "incomplete_or_failed", "corpus_gate_ready": False})
    _json(paths["results"], results)
    result = _run(paths)
    assert result["corpus_gate_ready"] is False
    assert any("technical/GIA" in error for error in result["errors"])


def test_legacy_release_ready_result_is_not_accepted(tmp_path: Path):
    paths = _fixture(tmp_path)
    results = json.loads(paths["results"].read_text())
    results.pop("schema_version")
    results.pop("corpus_gate_ready")
    results["release_ready"] = True
    _json(paths["results"], results)
    result = _run(paths)
    assert result["corpus_gate_ready"] is False
    assert any("schema_version" in error for error in result["errors"])
    assert any("technical/GIA" in error for error in result["errors"])


def test_wrong_run_kind_is_not_accepted(tmp_path: Path):
    paths = _fixture(tmp_path)
    results = json.loads(paths["results"].read_text())
    results["run_kind"] = "different_gate"
    _json(paths["results"], results)
    result = _run(paths)
    assert result["corpus_gate_ready"] is False
    assert any("run_kind" in error for error in result["errors"])


def test_result_must_bind_exact_config_bytes(tmp_path: Path):
    paths = _fixture(tmp_path)
    config = json.loads(paths["config"].read_text())
    config["operator_note"] = "changed after corpus run"
    _json(paths["config"], config)
    result = _run(paths)
    assert result["corpus_gate_ready"] is False
    assert any("exact config bytes" in error for error in result["errors"])


def test_result_implementation_snapshot_must_match_config(tmp_path: Path):
    paths = _fixture(tmp_path)
    results = json.loads(paths["results"].read_text())
    results["implementation"]["frozen_components"]["routing"] = "changed.v2"
    _json(paths["results"], results)
    result = _run(paths)
    assert result["corpus_gate_ready"] is False
    assert any("implementation pins differ" in error for error in result["errors"])


def test_pinned_implementation_drift_after_result_fails(tmp_path: Path):
    paths = _fixture(tmp_path)
    paths["components"]["release_verifier"].write_text("# drifted\n")
    result = _run(paths)
    assert result["corpus_gate_ready"] is False
    assert any("release_verifier implementation drifted" in error
               for error in result["errors"])

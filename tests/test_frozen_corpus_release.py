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
    results = tmp_path / "results.json"
    _json(results, {"status": "pass", "release_ready": True})
    private_key = Ed25519PrivateKey.generate()
    public_key = tmp_path / "founder.pub"
    public_key.write_bytes(private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ))
    config = tmp_path / "config.json"
    _json(config, {
        "founder_public_key": {
            "key_id": "founder-v1", "path": public_key.name,
            "sha256": _sha(public_key),
        },
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
        "root": tmp_path,
    }


def _run(paths: dict[str, Any]) -> dict[str, Any]:
    return verify_frozen_corpus_release(
        paths["results"], paths["config"], paths["approval"],
        repository_root=paths["root"],
    )


def test_exact_signed_founder_decision_passes(tmp_path: Path):
    paths = _fixture(tmp_path)
    result = _run(paths)
    assert result["external_beta_ready"] is True
    assert result["founder_signature"]["status"] == "verified"
    assert result["provider_calls"] == 0


def test_approval_for_different_result_fails(tmp_path: Path):
    paths = _fixture(tmp_path)
    _json(paths["results"], {"status": "pass", "release_ready": True, "changed": True})
    result = _run(paths)
    assert result["external_beta_ready"] is False
    assert any("exact results bytes" in error for error in result["errors"])


def test_tampered_founder_decision_fails_signature(tmp_path: Path):
    paths = _fixture(tmp_path)
    approval = json.loads(paths["approval"].read_text())
    approval["release_ticket"] = "FACETTA-TAMPERED"
    _json(paths["approval"], approval)
    result = _run(paths)
    assert result["founder_signature"]["status"] == "not_verified"
    assert result["external_beta_ready"] is False


def test_non_ready_technical_result_cannot_be_approved(tmp_path: Path):
    paths = _fixture(tmp_path)
    _json(paths["results"], {"status": "incomplete_or_failed", "release_ready": False})
    result = _run(paths)
    assert result["external_beta_ready"] is False
    assert any("technical/GIA" in error for error in result["errors"])

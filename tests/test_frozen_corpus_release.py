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
    reviewer_private_key = Ed25519PrivateKey.generate()
    public_key = tmp_path / "founder.pub"
    public_key.write_bytes(private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ))
    reviewer_public_key = tmp_path / "reviewer.pub"
    reviewer_public_key.write_bytes(
        reviewer_private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    )
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
    evaluation_rows = [
        {
            "kind": "render" if index < 7 else "edit",
            "evaluation_id": f"evaluation-{index + 1}",
            "operation_class": (
                "render_conformance" if index < 7
                else "quick_appearance" if index < 10 else "structural"
            ),
        }
        for index in range(18)
    ]
    quality_assignment = {
        "slice": "ring", "evaluation_set_id": "ring-full-matrix-v1",
    }
    workload = tmp_path / "workload.json"
    _json(workload, {
        "schema_version": "facetta-frozen-capture-workload.v1",
        "config_id": "test-config",
        "corpus_id": "test-corpus",
        "manifest_sha256": "a" * 64,
        "expected_integrity_source_count": 144,
        "expected_quality_source_count": 58,
        "ring_quality_evaluation_set_id": "ring-full-matrix-v1",
        "evaluation_sets": {"ring-full-matrix-v1": evaluation_rows},
        "sources": [
            {
                "filename": f"source-{index + 1}.png",
                "sha256": f"{index + 1:064x}",
                "integrity_required": True,
                "quality": quality_assignment if index < 58 else None,
            }
            for index in range(144)
        ],
    })
    frozen_components = {
        name: f"components/{path.name}@sha256:{_sha(path)}"
        for name, path in component_files.items()
    } | {
        "routing": "captured-replay.v1",
        "capture_workload": f"{workload.name}@sha256:{_sha(workload)}",
    }
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
        "reviewer_public_key": {
            "key_id": "reviewer-v1", "path": reviewer_public_key.name,
            "sha256": _sha(reviewer_public_key),
        },
    })
    results = tmp_path / "results.json"
    _json(results, {
        "schema_version": "facetta-frozen-corpus-gate-result.v1",
        "run_kind": "provider_free_frozen_corpus_gate",
        "status": "pass",
        "corpus_gate_ready": True,
        "provider_calls": 0,
        "manifest": {"sha256": manifest_hash, "corpus_id": "test-corpus"},
        "config": {"sha256": _sha(config)},
        "workload": {
            "sha256": _sha(workload),
            "status": "pass",
            "integrity_source_count": 144,
            "quality_source_count": 58,
            "quality_evaluations_per_source": 18,
        },
        "evidence": {
            "path": "/secure/replay.json",
            "sha256": "b" * 64,
            "schema_version": "facetta-frozen-replay.v1",
            "workload_sha256": _sha(workload),
            "capture_sha256": "c" * 64,
            "reviewer_key_id": "reviewer-v1",
        },
        "implementation": {"frozen_components": frozen_components},
        "definition": {"status": "pass", "errors": []},
        "source_integrity": {
            "status": "pass", "expected": 144, "verified": 144,
            "failures": [],
        },
        "quality": {
            "status": "pass",
            "errors": [],
            "signature": {"status": "verified", "key_id": "reviewer-v1"},
            "source_coverage": {
                "status": "pass",
                "expected_source_count": 58,
                "completed_source_count": 58,
                "failed_source_count": 0,
                "missing_source_filenames": [],
                "errors": [],
            },
            "captured_attempt_count": 1_044,
            "expected_evaluation_count": 1_044,
            "completed_evaluation_count": 1_044,
            "integrity_source_count": 144,
            "quality_source_count": 58,
            "all_outside_mask_drift_pass": True,
            "release_gates": {
                "hard_gate_pass": True,
                "spec_render_conformance_pass": True,
                "all_localized_edits_within_three_attempts": True,
                "edit_fidelity_pass": True,
                "zero_major_unintended_drift": True,
                "persistence_evidence_verified": True,
                "zero_rejected_candidates_persisted": True,
                "automated_gates_pass": True,
            },
            "classified_release_gates": {
                "quick_appearance": {"pass": True},
                "structural": {"pass": True},
            },
            "reviewer_review_complete": True,
            "all_reviewer_decisions_accepted": True,
            "reviewer_confusion_counts": {
                "false_positives": 0, "false_negatives": 0,
            },
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
        "root": tmp_path, "components": component_files,
        "workload": workload,
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
    assert result["gate_bindings"]["workload_sha256"] == _sha(paths["workload"])
    assert result["gate_bindings"]["replay_sha256"] == "b" * 64
    assert result["gate_bindings"]["capture_sha256"] == "c" * 64
    assert result["gate_bindings"]["reviewer_key_id"] == "reviewer-v1"
    assert result["gate_bindings"]["derived_scope"] == {
        "integrity_source_count": 144,
        "quality_source_count": 58,
        "quality_assignment_count": 1_044,
    }
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


def test_synthetic_minimal_top_level_pass_fails_closed(tmp_path: Path):
    paths = _fixture(tmp_path)
    results = json.loads(paths["results"].read_text())
    for field in ("definition", "source_integrity", "quality"):
        results.pop(field)
    _json(paths["results"], results)
    result = _run(paths)
    assert result["corpus_gate_ready"] is False
    assert any("definition evidence" in error for error in result["errors"])
    assert any("source integrity" in error for error in result["errors"])
    assert any("quality evidence is missing" in error for error in result["errors"])


def test_workload_result_counts_cannot_replace_pinned_scope(tmp_path: Path):
    paths = _fixture(tmp_path)
    results = json.loads(paths["results"].read_text())
    results["workload"]["quality_source_count"] = 1
    results["quality"]["expected_evaluation_count"] = 18
    results["quality"]["completed_evaluation_count"] = 18
    _json(paths["results"], results)
    result = _run(paths)
    assert result["corpus_gate_ready"] is False
    assert any("workload evidence" in error for error in result["errors"])
    assert any("assignment counts" in error for error in result["errors"])


def test_missing_or_tampered_nested_quality_proof_fails_closed(tmp_path: Path):
    paths = _fixture(tmp_path)
    results = json.loads(paths["results"].read_text())
    results["quality"]["signature"]["status"] = "not_verified"
    results["quality"]["source_coverage"]["completed_source_count"] = 57
    results["quality"]["reviewer_review_complete"] = False
    results["quality"]["release_gates"]["persistence_evidence_verified"] = False
    results["quality"]["classified_release_gates"]["structural"]["pass"] = False
    _json(paths["results"], results)
    result = _run(paths)
    assert result["corpus_gate_ready"] is False
    joined = " ".join(result["errors"])
    assert "replay signature" in joined
    assert "source coverage" in joined
    assert "GIA reviewer" in joined
    assert "release gates" in joined
    assert "classified release gates" in joined


def test_signed_replay_binding_is_required_and_key_bound(tmp_path: Path):
    paths = _fixture(tmp_path)
    results = json.loads(paths["results"].read_text())
    results["evidence"] = {
        "sha256": "not-a-digest",
        "schema_version": "facetta-frozen-replay.v0",
        "workload_sha256": "0" * 64,
        "capture_sha256": None,
        "reviewer_key_id": "different-reviewer",
    }
    _json(paths["results"], results)
    result = _run(paths)
    assert result["corpus_gate_ready"] is False
    assert any("signed replay binding" in error for error in result["errors"])


def test_quality_signature_key_must_match_enrolled_reviewer(tmp_path: Path):
    paths = _fixture(tmp_path)
    results = json.loads(paths["results"].read_text())
    results["quality"]["signature"]["key_id"] = "different-reviewer"
    _json(paths["results"], results)
    result = _run(paths)
    assert result["corpus_gate_ready"] is False
    assert any("replay signature" in error for error in result["errors"])


def test_pinned_workload_must_preserve_144_by_58_by_18_scope(tmp_path: Path):
    paths = _fixture(tmp_path)
    workload = json.loads(paths["workload"].read_text())
    workload["sources"] = workload["sources"][:1]
    workload["expected_integrity_source_count"] = 1
    workload["expected_quality_source_count"] = 1
    _json(paths["workload"], workload)
    config = json.loads(paths["config"].read_text())
    config["frozen_components"]["capture_workload"] = (
        f"{paths['workload'].name}@sha256:{_sha(paths['workload'])}"
    )
    _json(paths["config"], config)
    result = _run(paths)
    assert result["corpus_gate_ready"] is False
    joined = " ".join(result["errors"])
    assert "exactly 144" in joined
    assert "exactly 58" in joined
    assert "exactly 1,044" in joined

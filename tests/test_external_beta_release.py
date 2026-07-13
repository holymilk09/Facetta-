from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from facetta.external_beta_release import (
    canonical_designer_approval_payload,
    canonical_staging_approval_payload,
    required_staging_checks,
    verify_external_beta_release,
)


def _json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> dict[str, Any]:
    reviewer_private = Ed25519PrivateKey.generate()
    designer_private = Ed25519PrivateKey.generate()
    reviewer_public = tmp_path / "staging-reviewer.pub"
    reviewer_public.write_bytes(reviewer_private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ))
    designer_public = tmp_path / "designer-reviewer.pub"
    designer_public.write_bytes(designer_private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ))
    components = tmp_path / "components"
    components.mkdir()
    verifier = components / "external_beta_release.py"
    verifier.write_text("# frozen external beta verifier\n")
    staging_probe = components / "run_staging_two_user_isolation.py"
    staging_probe.write_text("# frozen staging probe\n")
    verifier_cli = components / "verify_external_beta_release.py"
    verifier_cli.write_text("# frozen external beta verifier CLI\n")
    workload = tmp_path / "workload.json"
    _json(workload, {
        "schema_version": "facetta-frozen-capture-workload.v1",
        "ring_quality_evaluation_set_id": "ring-v1",
        "evaluation_sets": {
            "ring-v1": [
                {
                    "kind": "edit",
                    "evaluation_id": "metal-color",
                    "operation_class": "quick_appearance",
                },
            ],
        },
        "sources": [
            {
                "filename": filename,
                "quality": {"slice": "ring", "evaluation_set_id": "ring-v1"},
            }
            for filename in ("ring-a.png", "ring-b.png")
        ],
    })

    config = tmp_path / "config.json"
    _json(config, {
        "schema_version": "facetta-frozen-gate-config.v1",
        "config_id": "fixture-config",
        "frozen_components": {
            "external_beta_release_verifier": (
                f"components/{verifier.name}@sha256:{_sha(verifier)}"
            ),
            "staging_isolation_probe": (
                f"components/{staging_probe.name}@sha256:{_sha(staging_probe)}"
            ),
            "external_beta_release_cli": (
                f"components/{verifier_cli.name}@sha256:{_sha(verifier_cli)}"
            ),
            "capture_workload": f"{workload.name}@sha256:{_sha(workload)}",
        },
        "staging_reviewer_public_key": {
            "key_id": "staging-reviewer-v1",
            "path": reviewer_public.name,
            "sha256": _sha(reviewer_public),
        },
        "designer_reviewer_public_key": {
            "key_id": "designer-reviewer-v1",
            "path": designer_public.name,
            "sha256": _sha(designer_public),
        },
    })

    corpus_results = tmp_path / "corpus-results.json"
    corpus_approval = tmp_path / "corpus-approval.json"
    _json(corpus_results, {
        "fixture": "signed result input",
        "quality": {
            "classified_release_gates": {
                "quick_appearance": {
                    "evaluation_count": 2,
                    "designer_accepted_count": 2,
                    "designer_acceptance_rate": 1.0,
                    "threshold": 0.9,
                    "pass": True,
                },
            },
            "release_gates": {
                "all_localized_edits_within_three_attempts": True,
            },
        },
    })
    _json(corpus_approval, {"fixture": "signed founder input"})
    corpus_exit = tmp_path / "corpus-exit-code.txt"
    corpus_exit.write_text("0\n")
    corpus_decision_value = {
        "schema_version": "facetta-frozen-corpus-release-decision.v2",
        "status": "pass",
        "corpus_gate_ready": True,
        "provider_calls": 0,
        "gate_bindings": {
            "config_sha256": _sha(config),
            "corpus_run_id": "fixture-corpus-run-v1",
        },
        "founder_signature": {"status": "verified", "key_id": "founder-v1"},
        "errors": [],
    }
    corpus_decision = tmp_path / "corpus-final-decision.json"
    _json(corpus_decision, corpus_decision_value)

    checks = [
        {"name": name, "expected": expected, "observed": expected, "passed": True}
        for name, expected in required_staging_checks().items()
    ]
    staging_results = tmp_path / "staging-results.json"
    _json(staging_results, {
        "schema_version": "facetta-staging-isolation.v3",
        "run_kind": "read_only_two_principal_staging_probe",
        "target": {
            "origin_sha256": "a" * 64,
            "deployment_revision": "0123456789abcdef",
            "fixture_set_sha256": "b" * 64,
            "probed_at": "2026-07-13T12:00:00+08:00",
            "transport": "live_https",
        },
        "checks": checks,
        "passed": True,
        "secrets_logged": False,
        "provider_calls": 0,
        "mutations": 0,
    })
    staging_exit = tmp_path / "staging-exit-code.txt"
    staging_exit.write_text("0\n")
    designer_approval = tmp_path / "designer-approval.json"
    designer_decisions = tmp_path / "designer-decisions.json"
    _json(designer_decisions, {
        "schema_version": "facetta-designer-acceptance-decisions.v1",
        "corpus_results_sha256": _sha(corpus_results),
        "corpus_run_id": "fixture-corpus-run-v1",
        "completed": True,
        "designer": "Test Jewelry Designer",
        "qualification": "jewelry_designer",
        "reviewed_at": "2026-07-13T12:10:00+08:00",
        "decisions": [
            {
                "source_filename": filename,
                "evaluation_id": "metal-color",
                "accepted": True,
            }
            for filename in ("ring-a.png", "ring-b.png")
        ],
    })
    staging_approval = tmp_path / "staging-approval.json"

    paths: dict[str, Any] = {
        "root": tmp_path,
        "private": reviewer_private,
        "designer_private": designer_private,
        "verifier": verifier,
        "staging_probe": staging_probe,
        "verifier_cli": verifier_cli,
        "config": config,
        "corpus_results": corpus_results,
        "corpus_approval": corpus_approval,
        "corpus_exit": corpus_exit,
        "corpus_decision": corpus_decision,
        "corpus_decision_value": corpus_decision_value,
        "staging_results": staging_results,
        "staging_exit": staging_exit,
        "designer_approval": designer_approval,
        "designer_decisions": designer_decisions,
        "staging_approval": staging_approval,
    }
    _sign_designer_approval(paths)
    _sign_staging_approval(paths)
    return paths


def _sign_staging_approval(paths: dict[str, Any]) -> None:
    staging = json.loads(paths["staging_results"].read_text())
    value: dict[str, Any] = {
        "schema_version": "facetta-staging-isolation-approval.v1",
        "staging_results_sha256": _sha(paths["staging_results"]),
        "staging_exit_code_sha256": _sha(paths["staging_exit"]),
        "decision": "approved",
        "reviewer": "Test Release Reviewer",
        "approved_at": "2026-07-13T12:30:00+08:00",
        "release_ticket": "FACETTA-STAGING-1",
        "origin_sha256": staging["target"]["origin_sha256"],
        "deployment_revision": staging["target"]["deployment_revision"],
    }
    value["signature"] = {
        "algorithm": "Ed25519",
        "key_id": "staging-reviewer-v1",
        "value": base64.b64encode(paths["private"].sign(
            canonical_staging_approval_payload(value)
        )).decode("ascii"),
    }
    _json(paths["staging_approval"], value)


def _sign_designer_approval(paths: dict[str, Any]) -> None:
    quick = json.loads(paths["corpus_results"].read_text())["quality"][
        "classified_release_gates"
    ]["quick_appearance"]
    value: dict[str, Any] = {
        "schema_version": "facetta-designer-acceptance-approval.v1",
        "corpus_results_sha256": _sha(paths["corpus_results"]),
        "corpus_run_id": "fixture-corpus-run-v1",
        "designer_decisions_sha256": _sha(paths["designer_decisions"]),
        "decision": "approved",
        "designer": "Test Jewelry Designer",
        "qualification": "jewelry_designer",
        "approved_at": "2026-07-13T12:15:00+08:00",
        "release_ticket": "FACETTA-DESIGNER-1",
        "quick_appearance": {
            "evaluation_count": quick["evaluation_count"],
            "accepted_count": 2,
            "acceptance_rate": 1.0,
            "threshold": quick["threshold"],
            "within_three_attempts": True,
        },
    }
    value["signature"] = {
        "algorithm": "Ed25519",
        "key_id": "designer-reviewer-v1",
        "value": base64.b64encode(paths["designer_private"].sign(
            canonical_designer_approval_payload(value)
        )).decode("ascii"),
    }
    _json(paths["designer_approval"], value)


def _verify(paths: dict[str, Any], corpus_verifier=None) -> dict[str, Any]:
    if corpus_verifier is None:
        expected = paths["corpus_decision_value"]

        def corpus_verifier(*args, **kwargs):
            return expected

    return verify_external_beta_release(
        paths["corpus_decision"],
        paths["corpus_results"],
        paths["corpus_approval"],
        paths["corpus_exit"],
        paths["config"],
        paths["designer_decisions"],
        paths["designer_approval"],
        paths["staging_results"],
        paths["staging_approval"],
        paths["staging_exit"],
        repository_root=paths["root"],
        corpus_verifier=corpus_verifier,
    )


def test_exact_reverified_corpus_and_signed_staging_pass_together(tmp_path: Path):
    paths = _fixture(tmp_path)
    result = _verify(paths)
    assert result["schema_version"] == "facetta-external-beta-release-decision.v1"
    assert result["external_beta_ready"] is True
    assert result["status"] == "pass"
    assert result["provider_calls"] == 0
    assert result["mutations"] == 0
    assert result["signatures"]["founder"]["status"] == "verified"
    assert result["signatures"]["designer"]["status"] == "verified"
    assert result["signatures"]["staging_reviewer"]["status"] == "verified"
    assert result["gate_bindings"]["deployment_revision"] == "0123456789abcdef"


def test_staging_result_tamper_breaks_exact_approval_binding(tmp_path: Path):
    paths = _fixture(tmp_path)
    value = json.loads(paths["staging_results"].read_text())
    value["operator_note"] = "changed after approval"
    _json(paths["staging_results"], value)
    result = _verify(paths)
    assert result["external_beta_ready"] is False
    assert any("exact result bytes" in error for error in result["errors"])


def test_shallow_staging_pass_cannot_omit_required_check(tmp_path: Path):
    paths = _fixture(tmp_path)
    value = json.loads(paths["staging_results"].read_text())
    value["checks"] = value["checks"][1:]
    _json(paths["staging_results"], value)
    _sign_staging_approval(paths)
    result = _verify(paths)
    assert result["external_beta_ready"] is False
    assert any("exactly cover" in error for error in result["errors"])


def test_malformed_staging_check_name_fails_closed_without_crashing(tmp_path: Path):
    paths = _fixture(tmp_path)
    value = json.loads(paths["staging_results"].read_text())
    value["checks"][0]["name"] = {"not": "a string"}
    _json(paths["staging_results"], value)
    _sign_staging_approval(paths)
    result = _verify(paths)
    assert result["external_beta_ready"] is False
    assert any("invalid names" in error for error in result["errors"])


def test_corpus_decision_must_equal_fresh_signature_verification(tmp_path: Path):
    paths = _fixture(tmp_path)

    def different_corpus(*args, **kwargs):
        return {**paths["corpus_decision_value"], "corpus_gate_ready": False}

    result = _verify(paths, different_corpus)
    assert result["external_beta_ready"] is False
    assert any("differs from fresh verification" in error for error in result["errors"])


def test_nonzero_retained_exit_code_fails_closed(tmp_path: Path):
    paths = _fixture(tmp_path)
    paths["staging_exit"].write_text("1\n")
    _sign_staging_approval(paths)
    result = _verify(paths)
    assert result["external_beta_ready"] is False
    assert any("did not retain exit code 0" in error for error in result["errors"])


def test_staging_reviewer_signature_must_verify(tmp_path: Path):
    paths = _fixture(tmp_path)
    approval = json.loads(paths["staging_approval"].read_text())
    approval["release_ticket"] = "FACETTA-TAMPERED"
    _json(paths["staging_approval"], approval)
    result = _verify(paths)
    assert result["external_beta_ready"] is False
    assert result["signatures"]["staging_reviewer"]["status"] == "not_verified"


def test_designer_approval_is_separate_and_must_verify(tmp_path: Path):
    paths = _fixture(tmp_path)
    approval = json.loads(paths["designer_approval"].read_text())
    approval["quick_appearance"]["accepted_count"] = 1
    _json(paths["designer_approval"], approval)
    result = _verify(paths)
    assert result["external_beta_ready"] is False
    assert result["signatures"]["designer"]["status"] == "not_verified"
    assert any("summary differs" in error for error in result["errors"])


def test_designer_and_staging_reviewer_cannot_share_public_key(tmp_path: Path):
    paths = _fixture(tmp_path)
    config = json.loads(paths["config"].read_text())
    designer = config["designer_reviewer_public_key"]
    config["staging_reviewer_public_key"] = {
        "key_id": "staging-distinct-label",
        "path": designer["path"],
        "sha256": designer["sha256"],
    }
    _json(paths["config"], config)

    result = _verify(paths)

    separation = result["authority_key_separation"]
    assert separation["status"] == "fail"
    assert any(
        "jewelry_designer, staging_reviewer" in error
        and "public-key bytes" in error
        for error in separation["errors"]
    )
    assert result["external_beta_ready"] is False


def test_frozen_combined_verifier_pin_must_not_drift(tmp_path: Path):
    paths = _fixture(tmp_path)
    paths["verifier"].write_text("# drifted verifier\n")
    result = _verify(paths)
    assert result["external_beta_ready"] is False
    assert any(
        "external_beta_release_verifier implementation drifted" in error
        for error in result["errors"]
    )

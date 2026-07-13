from __future__ import annotations

import hashlib
import json
import base64
from pathlib import Path
from typing import Any

from PIL import Image
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from facetta.frozen_corpus_gate import (
    canonical_evidence_payload,
    compile_frozen_corpus_gate,
)


def _json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _image(path: Path, color: str) -> None:
    Image.new("RGB", (4, 4), color).save(path)


def _sign(paths: dict[str, Any], evidence: dict[str, Any]) -> None:
    evidence.pop("signature", None)
    signature = paths["private_key"].sign(canonical_evidence_payload(evidence))
    evidence["signature"] = {
        "algorithm": "Ed25519",
        "key_id": "test-reviewer-v1",
        "value": base64.b64encode(signature).decode("ascii"),
    }


def _write_signed(paths: dict[str, Any], evidence: dict[str, Any]) -> None:
    _sign(paths, evidence)
    _json(paths["evidence"], evidence)


def _fixture(tmp_path: Path) -> dict[str, Any]:
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    first = source_dir / "image-1.png"
    second = source_dir / "image-2.png"
    _image(first, "white")
    _image(second, "gray")
    manifest = tmp_path / "manifest.json"
    _json(manifest, {
        "schema_version": "facetta-frozen-corpus.v1",
        "corpus_id": "test-corpus",
        "expected_source_count": 2,
        "source_policy": "test-only",
        "sources": [
            {"filename": first.name, "sha256": _sha(first)},
            {"filename": second.name, "sha256": _sha(second)},
        ],
        "evaluation_slice": {
            "category": "ring",
            "ring_source_filenames": [first.name],
            "render_case_ids": ["render-one"],
            "operation_ids": ["edit-one", "edit-structural"],
            "operation_classes": {
                "quick_appearance": ["edit-one"],
                "structural": ["edit-structural"],
            },
        },
    })
    config = tmp_path / "config.json"
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
    private_key = Ed25519PrivateKey.generate()
    reviewer_key = tmp_path / "reviewer-v1.pub"
    reviewer_key.write_bytes(private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ))
    _json(config, {
        "schema_version": "facetta-frozen-gate-config.v1",
        "config_id": "test-config",
        "corpus_id": "test-corpus",
        "manifest_sha256": _sha(manifest),
        "frozen_components": {
            name: f"components/{path.name}@sha256:{_sha(path)}"
            for name, path in component_files.items()
        } | {
            "routing": "captured-replay.v1",
        },
        "thresholds": {
            "render_hard_gate_pass_rate": 0.90,
            "mean_render_conformance": 85,
            "mean_edit_fidelity": 90,
            "max_attempts": 3,
            "max_outside_mask_drift": 0.18,
            "quick_appearance_designer_acceptance_rate": 0.90,
        },
        "reviewer_public_key": {
            "key_id": "test-reviewer-v1",
            "path": reviewer_key.name,
            "sha256": _sha(reviewer_key),
        },
    })
    render_candidate = tmp_path / "render-candidate.png"
    edit_candidate = tmp_path / "edit-candidate.png"
    mask = tmp_path / "mask.png"
    _image(render_candidate, "white")
    _image(edit_candidate, "gray")
    _image(mask, "black")
    evidence = tmp_path / "evidence.json"
    evidence_value: dict[str, Any] = {
        "schema_version": "facetta-frozen-replay.v1",
        "manifest_sha256": _sha(manifest),
        "config_sha256": _sha(config),
        "source_coverage": [
            {
                "filename": first.name, "source_sha256": _sha(first),
                "evaluation_ids": ["render-one"], "quality_status": "pass",
            },
            {
                "filename": second.name, "source_sha256": _sha(second),
                "evaluation_ids": ["edit-one", "edit-structural"],
                "quality_status": "pass",
            },
        ],
        "attempts": [
            {
                "kind": "render", "evaluation_id": "render-one",
                "attempt": 1, "accepted": True,
                "source_filename": first.name, "source_sha256": _sha(first),
                "source_image": str(first),
                "source_image_sha256": _sha(first),
                "candidate_image": str(render_candidate),
                "candidate_image_sha256": _sha(render_candidate),
                "render_conformance_score": 90, "hard_gate_pass": True,
            },
            {
                "kind": "edit", "evaluation_id": "edit-one",
                "attempt": 1, "accepted": True,
                "source_filename": second.name, "source_sha256": _sha(second),
                "edit_fidelity_score": 95, "severity": "none",
                "change_applied": True, "source_image": str(second),
                "source_image_sha256": _sha(second),
                "candidate_image": str(edit_candidate),
                "candidate_image_sha256": _sha(edit_candidate),
                "mask_image": str(mask), "mask_image_sha256": _sha(mask),
            },
            {
                "kind": "edit", "evaluation_id": "edit-structural",
                "attempt": 1, "accepted": True,
                "source_filename": second.name, "source_sha256": _sha(second),
                "edit_fidelity_score": 95, "severity": "none",
                "change_applied": True, "source_image": str(second),
                "source_image_sha256": _sha(second),
                "candidate_image": str(edit_candidate),
                "candidate_image_sha256": _sha(edit_candidate),
                "mask_image": str(mask), "mask_image_sha256": _sha(mask),
            },
        ],
        "persistence_evidence": {
            "verified": True,
            "method": "canonical_project_api_integration",
            "result_set": "test-result",
            "rejected_active_asset_count": 0,
        },
        "reviewer_review": {
            "completed": True, "reviewer": "test reviewer",
            "qualification": "GIA-trained",
            "false_positives": 0, "false_negatives": 0,
            "decisions": [
                {
                    "kind": "render", "evaluation_id": "render-one",
                    "source_filename": first.name, "accepted": True,
                },
                {
                    "kind": "edit", "evaluation_id": "edit-one",
                    "source_filename": second.name, "accepted": True,
                },
                {
                    "kind": "edit", "evaluation_id": "edit-structural",
                    "source_filename": second.name, "accepted": True,
                },
            ],
        },
    }
    paths: dict[str, Any] = {
        "root": tmp_path,
        "source_dir": source_dir, "manifest": manifest, "config": config,
        "evidence": evidence, "first": first, "second": second,
        "prompt_bundle": component_files["prompt_bundle"],
        "private_key": private_key, "reviewer_key": reviewer_key,
        "render_candidate": render_candidate, "edit_candidate": edit_candidate,
    }
    _write_signed(paths, evidence_value)
    return paths


def _run(paths: dict[str, Any], *, evidence: bool = True) -> dict:
    return compile_frozen_corpus_gate(
        paths["manifest"], paths["config"], paths["source_dir"],
        paths["evidence"] if evidence else None,
        repository_root=paths["root"],
    )


def _refresh_config_manifest_hash(paths: dict[str, Any]) -> None:
    config = json.loads(paths["config"].read_text())
    config["manifest_sha256"] = _sha(paths["manifest"])
    _json(paths["config"], config)


def _refresh_evidence_hashes(paths: dict[str, Any]) -> dict[str, Any]:
    evidence = json.loads(paths["evidence"].read_text())
    evidence["manifest_sha256"] = _sha(paths["manifest"])
    evidence["config_sha256"] = _sha(paths["config"])
    return evidence


def test_complete_offline_replay_can_pass(tmp_path: Path):
    paths = _fixture(tmp_path)
    result = _run(paths)
    assert result["release_ready"] is True
    assert result["source_integrity"]["status"] == "pass"
    assert result["quality"]["status"] == "pass"
    assert result["quality"]["signature"]["status"] == "verified"
    assert result["quality"]["source_coverage"] == {
        "status": "pass",
        "expected_source_count": 2,
        "completed_source_count": 2,
        "failed_source_count": 0,
        "missing_source_filenames": [],
        "errors": [],
    }
    assert result["quality"]["outside_mask_replay"][0][
        "outside_mask_drift"
    ] == 0


def test_missing_source_fails_integrity(tmp_path: Path):
    paths = _fixture(tmp_path)
    paths["second"].unlink()
    result = _run(paths)
    assert result["release_ready"] is False
    assert result["source_integrity"]["failures"][0]["code"] == "missing"


def test_changed_source_hash_fails_integrity(tmp_path: Path):
    paths = _fixture(tmp_path)
    _image(paths["second"], "black")
    result = _run(paths)
    assert result["source_integrity"]["failures"][0]["code"] == "sha256_mismatch"


def test_duplicate_manifest_hash_fails_definition(tmp_path: Path):
    paths = _fixture(tmp_path)
    manifest = json.loads(paths["manifest"].read_text())
    manifest["sources"][1]["sha256"] = manifest["sources"][0]["sha256"]
    _json(paths["manifest"], manifest)
    _refresh_config_manifest_hash(paths)
    result = _run(paths, evidence=False)
    assert result["definition"]["status"] == "fail"
    assert any("duplicate source hashes" in error
               for error in result["definition"]["errors"])


def test_config_drift_is_rejected_by_replay_hash(tmp_path: Path):
    paths = _fixture(tmp_path)
    config = json.loads(paths["config"].read_text())
    config["frozen_components"]["prompt_bundle"] = "changed.v2"
    _json(paths["config"], config)
    result = _run(paths)
    assert result["quality"]["status"] == "fail"
    assert "replay config hash differs" in " ".join(result["quality"]["errors"])


def test_pinned_implementation_drift_fails_definition(tmp_path: Path):
    paths = _fixture(tmp_path)
    paths["prompt_bundle"].write_text("# changed implementation\n")
    result = _run(paths, evidence=False)
    assert result["definition"]["status"] == "fail"
    assert any("prompt_bundle implementation drifted" in error
               for error in result["definition"]["errors"])


def test_absent_replay_is_not_run_and_fails_closed(tmp_path: Path):
    paths = _fixture(tmp_path)
    result = _run(paths, evidence=False)
    assert result["source_integrity"]["status"] == "pass"
    assert result["quality"]["status"] == "not_run"
    assert result["release_ready"] is False


def test_missing_reviewer_fails_quality(tmp_path: Path):
    paths = _fixture(tmp_path)
    evidence = _refresh_evidence_hashes(paths)
    evidence.pop("reviewer_review")
    _write_signed(paths, evidence)
    result = _run(paths)
    assert result["quality"]["reviewer_review_complete"] is False
    assert any("reviewer" in error for error in result["quality"]["errors"])


def test_more_than_three_attempts_fails_quality(tmp_path: Path):
    paths = _fixture(tmp_path)
    evidence = _refresh_evidence_hashes(paths)
    edit = next(row for row in evidence["attempts"] if row["kind"] == "edit")
    edit["accepted"] = False
    for attempt in (2, 3, 4):
        row = dict(edit)
        row["attempt"] = attempt
        row["accepted"] = attempt == 4
        evidence["attempts"].append(row)
    _write_signed(paths, evidence)
    result = _run(paths)
    assert any("exceeded 3 attempts" in error
               for error in result["quality"]["errors"])
    assert result["quality"]["release_gates"][
        "all_localized_edits_within_three_attempts"
    ] is False


def test_metric_failure_fails_release_gate(tmp_path: Path):
    paths = _fixture(tmp_path)
    evidence = _refresh_evidence_hashes(paths)
    edit = next(row for row in evidence["attempts"] if row["kind"] == "edit")
    edit["edit_fidelity_score"] = 70
    _write_signed(paths, evidence)
    result = _run(paths)
    assert result["quality"]["release_gates"]["edit_fidelity_pass"] is False
    assert result["quality"]["status"] == "fail"


def test_rejected_candidate_persisted_fails_release_gate(tmp_path: Path):
    paths = _fixture(tmp_path)
    evidence = _refresh_evidence_hashes(paths)
    evidence["persistence_evidence"]["rejected_active_asset_count"] = 1
    _write_signed(paths, evidence)
    result = _run(paths)
    assert result["quality"]["release_gates"][
        "zero_rejected_candidates_persisted"
    ] is False
    assert result["release_ready"] is False


def test_quick_appearance_reviewer_acceptance_is_a_release_gate(tmp_path: Path):
    paths = _fixture(tmp_path)
    evidence = _refresh_evidence_hashes(paths)
    decision = next(
        row for row in evidence["reviewer_review"]["decisions"]
        if row["evaluation_id"] == "edit-one"
    )
    decision["accepted"] = False
    evidence["reviewer_review"]["false_positives"] = 1
    _write_signed(paths, evidence)
    result = _run(paths)
    gate = result["quality"]["classified_release_gates"]["quick_appearance"]
    assert gate["designer_acceptance_rate"] == 0
    assert gate["threshold"] == 0.9
    assert gate["pass"] is False
    assert result["release_ready"] is False


def test_structural_fidelity_is_classified_independently(tmp_path: Path):
    paths = _fixture(tmp_path)
    evidence = _refresh_evidence_hashes(paths)
    structural = next(
        row for row in evidence["attempts"]
        if row["evaluation_id"] == "edit-structural"
    )
    structural["edit_fidelity_score"] = 89
    _write_signed(paths, evidence)
    result = _run(paths)
    gate = result["quality"]["classified_release_gates"]["structural"]
    assert gate["mean_edit_fidelity"] == 89
    assert gate["pass"] is False
    assert result["release_ready"] is False


def test_reviewer_confusion_summary_must_match_decisions(tmp_path: Path):
    paths = _fixture(tmp_path)
    evidence = _refresh_evidence_hashes(paths)
    evidence["reviewer_review"]["false_negatives"] = 9
    _write_signed(paths, evidence)
    result = _run(paths)
    assert result["quality"]["reviewer_confusion_counts"] == {
        "false_positives": 0, "false_negatives": 0,
    }
    assert result["quality"]["reviewer_review_complete"] is False
    assert result["release_ready"] is False


def test_unsigned_evidence_fails_signature_gate(tmp_path: Path):
    paths = _fixture(tmp_path)
    evidence = json.loads(paths["evidence"].read_text())
    evidence.pop("signature")
    _json(paths["evidence"], evidence)
    result = _run(paths)
    assert result["quality"]["signature"]["status"] == "not_verified"
    assert any("unsigned" in error for error in result["quality"]["errors"])
    assert result["release_ready"] is False


def test_tampered_signed_assertion_fails_signature_gate(tmp_path: Path):
    paths = _fixture(tmp_path)
    evidence = json.loads(paths["evidence"].read_text())
    evidence["reviewer_review"]["false_negatives"] = 7
    _json(paths["evidence"], evidence)
    result = _run(paths)
    assert result["quality"]["signature"]["status"] == "not_verified"
    assert any("signature is invalid" in error
               for error in result["quality"]["errors"])


def test_missing_manifest_source_coverage_claim_fails(tmp_path: Path):
    paths = _fixture(tmp_path)
    evidence = _refresh_evidence_hashes(paths)
    evidence["source_coverage"].pop()
    _write_signed(paths, evidence)
    result = _run(paths)
    coverage = result["quality"]["source_coverage"]
    assert coverage["expected_source_count"] == 2
    assert coverage["completed_source_count"] == 2
    assert coverage["missing_source_filenames"] == []
    assert any("lack matching coverage rows" in error
               for error in coverage["errors"])
    assert result["release_ready"] is False


def test_signed_coverage_claim_without_source_attempt_fails(tmp_path: Path):
    paths = _fixture(tmp_path)
    evidence = _refresh_evidence_hashes(paths)
    for edit in (row for row in evidence["attempts"] if row["kind"] == "edit"):
        edit.update({
            "source_filename": paths["first"].name,
            "source_sha256": _sha(paths["first"]),
            "source_image": str(paths["first"]),
            "source_image_sha256": _sha(paths["first"]),
            "candidate_image": str(paths["render_candidate"]),
            "candidate_image_sha256": _sha(paths["render_candidate"]),
        })
    _write_signed(paths, evidence)
    result = _run(paths)
    coverage = result["quality"]["source_coverage"]
    assert coverage["expected_source_count"] == 2
    assert coverage["completed_source_count"] == 1
    assert coverage["missing_source_filenames"] == ["image-2.png"]
    assert any("do not match verified attempts" in error
               for error in coverage["errors"])
    assert result["release_ready"] is False


def test_attempt_artifact_hash_mismatch_fails(tmp_path: Path):
    paths = _fixture(tmp_path)
    _image(paths["edit_candidate"], "black")
    result = _run(paths)
    assert any("candidate_image artifact hash mismatch" in error
               for error in result["quality"]["errors"])
    assert result["release_ready"] is False

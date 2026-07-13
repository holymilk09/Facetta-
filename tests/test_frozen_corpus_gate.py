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
    release_authority_key_separation,
)
from facetta.frozen_evidence_paths import build_artifact_index
from facetta.frozen_persistence_attestation import (
    canonical_attestation_payload,
    result_set_sha256,
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
    persistence_path = paths["persistence_artifact"]
    _json(persistence_path, evidence["persistence_evidence"])
    evidence["persistence_evidence_binding"] = {
        "artifact": persistence_path.relative_to(paths["root"]).as_posix(),
        "sha256": _sha(persistence_path),
    }
    artifact_rows: list[tuple[str, str, str]] = [
        (
            evidence["capture_provenance"]["capture_artifact"],
            evidence["capture_provenance"]["capture_sha256"],
            "signed_capture",
        ),
        (
            evidence["capture_provenance"]["executor_public_key_artifact"],
            evidence["capture_provenance"]["executor_public_key_sha256"],
            "executor_public_key",
        ),
        (
            evidence["persistence_evidence_binding"]["artifact"],
            evidence["persistence_evidence_binding"]["sha256"],
            "persistence_evidence",
        ),
    ]
    for row in evidence["attempts"]:
        identity = (
            f"{row['kind']}:{row['evaluation_id']}:"
            f"{row['source_filename']}:attempt-{row['attempt']}"
        )
        artifact_rows.extend([
            (row["source_image"], row["source_image_sha256"], f"source:{identity}"),
            (
                row["candidate_image"],
                row["candidate_image_sha256"],
                f"candidate:{identity}",
            ),
        ])
        if row["kind"] == "edit":
            artifact_rows.append((
                row["mask_image"], row["mask_image_sha256"], f"mask:{identity}",
            ))
    evidence["artifact_index"] = build_artifact_index(artifact_rows)
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
    workload = tmp_path / "workload.json"
    _json(workload, {
        "schema_version": "facetta-frozen-capture-workload.v1",
        "workload_id": "test-workload-v1",
        "corpus_id": "test-corpus",
        "config_id": "test-config",
        "manifest_sha256": _sha(manifest),
        "expected_integrity_source_count": 2,
        "expected_quality_source_count": 1,
        "ring_quality_evaluation_set_id": "ring-full-matrix-v1",
        "evaluation_sets": {
            "ring-full-matrix-v1": [
                {
                    "kind": "render",
                    "evaluation_id": "render-one",
                    "operation_class": "render_conformance",
                },
                {
                    "kind": "edit",
                    "evaluation_id": "edit-one",
                    "operation_class": "quick_appearance",
                },
                {
                    "kind": "edit",
                    "evaluation_id": "edit-structural",
                    "operation_class": "structural",
                },
            ],
        },
        "sources": [
            {
                "filename": first.name,
                "sha256": _sha(first),
                "integrity_required": True,
                "quality": {
                    "slice": "ring",
                    "evaluation_set_id": "ring-full-matrix-v1",
                },
            },
            {
                "filename": second.name,
                "sha256": _sha(second),
                "integrity_required": True,
                "quality": None,
            },
        ],
    })
    config = tmp_path / "config.json"
    components = tmp_path / "components"
    components.mkdir()
    component_files: dict[str, Path] = {}
    for name in (
        "ring_contract", "prompt_bundle", "evaluator_bundle", "live_runner",
        "replay_verifier", "replay_runner", "release_verifier",
        "packet_builder", "packet_runner", "capture_producer",
        "capture_producer_cli",
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
    runner_private_key = Ed25519PrivateKey.generate()
    runner_key = tmp_path / "canonical-api-runner-v1.pub"
    runner_key.write_bytes(runner_private_key.public_key().public_bytes(
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
            "capture_workload": f"workload.json@sha256:{_sha(workload)}",
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
        "canonical_api_runner_public_key": {
            "key_id": "canonical-api-runner-v1",
            "path": runner_key.name,
            "sha256": _sha(runner_key),
        },
    })
    render_candidate = tmp_path / "render-candidate.png"
    edit_candidate = tmp_path / "edit-candidate.png"
    mask = tmp_path / "mask.png"
    _image(render_candidate, "white")
    _image(edit_candidate, "white")
    edit_mask = Image.new("L", (4, 4), 0)
    edit_mask.putpixel((0, 0), 255)
    edit_mask.save(mask)
    evidence = tmp_path / "evidence.json"
    capture_artifact = tmp_path / "capture.json"
    capture_artifact.write_text('{"signed":true}\n')
    persistence_artifact = tmp_path / "persistence.json"
    evidence_value: dict[str, Any] = {
        "schema_version": "facetta-frozen-replay.v1",
        "manifest_sha256": _sha(manifest),
        "config_sha256": _sha(config),
        "workload_sha256": _sha(workload),
        "capture_sha256": _sha(capture_artifact),
        "capture_provenance": {
            "corpus_run_id": "corpus-run-test-1",
            "capture_artifact": capture_artifact.name,
            "capture_sha256": _sha(capture_artifact),
            "executor_public_key_artifact": reviewer_key.name,
            "executor_public_key_sha256": _sha(reviewer_key),
            "executor_signature_status": "verified",
            "capture_validation": {"status": "pass"},
        },
        "source_coverage": [
            {
                "filename": first.name, "source_sha256": _sha(first),
                "evaluation_ids": [
                    "render-one", "edit-one", "edit-structural",
                ],
                "quality_status": "pass",
            },
        ],
        "attempts": [
            {
                "kind": "render", "evaluation_id": "render-one",
                "operation_class": "render_conformance",
                "attempt": 1, "accepted": True,
                "source_filename": first.name, "source_sha256": _sha(first),
                "source_image": first.relative_to(tmp_path).as_posix(),
                "source_image_sha256": _sha(first),
                "candidate_image": render_candidate.name,
                "candidate_image_sha256": _sha(render_candidate),
                "render_conformance_score": 90, "hard_gate_pass": True,
            },
            {
                "kind": "edit", "evaluation_id": "edit-one",
                "operation_class": "quick_appearance",
                "attempt": 1, "accepted": True,
                "source_filename": first.name, "source_sha256": _sha(first),
                "edit_fidelity_score": 95, "severity": "none",
                "change_applied": True,
                "source_image": first.relative_to(tmp_path).as_posix(),
                "source_image_sha256": _sha(first),
                "candidate_image": edit_candidate.name,
                "candidate_image_sha256": _sha(edit_candidate),
                "mask_image": mask.name, "mask_image_sha256": _sha(mask),
            },
            {
                "kind": "edit", "evaluation_id": "edit-structural",
                "operation_class": "structural",
                "attempt": 1, "accepted": True,
                "source_filename": first.name, "source_sha256": _sha(first),
                "edit_fidelity_score": 95, "severity": "none",
                "change_applied": True,
                "source_image": first.relative_to(tmp_path).as_posix(),
                "source_image_sha256": _sha(first),
                "candidate_image": edit_candidate.name,
                "candidate_image_sha256": _sha(edit_candidate),
                "mask_image": mask.name, "mask_image_sha256": _sha(mask),
            },
        ],
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
                    "source_filename": first.name, "accepted": True,
                },
                {
                    "kind": "edit", "evaluation_id": "edit-structural",
                    "source_filename": first.name, "accepted": True,
                },
            ],
        },
    }
    paths: dict[str, Any] = {
        "root": tmp_path,
        "source_dir": source_dir, "manifest": manifest, "config": config,
        "workload": workload,
        "evidence": evidence, "first": first, "second": second,
        "prompt_bundle": component_files["prompt_bundle"],
        "capture_producer": component_files["capture_producer"],
        "private_key": private_key, "reviewer_key": reviewer_key,
        "runner_private_key": runner_private_key, "runner_key": runner_key,
        "render_candidate": render_candidate, "edit_candidate": edit_candidate,
        "capture_artifact": capture_artifact,
        "persistence_artifact": persistence_artifact,
    }
    selected_result_set = [
        {
            "kind": row["kind"],
            "evaluation_id": row["evaluation_id"],
            "source_filename": row["source_filename"],
            "selected_attempt": row["attempt"],
            "candidate_image_sha256": row["candidate_image_sha256"],
        }
        for row in evidence_value["attempts"]
    ]
    attestation: dict[str, Any] = {
        "schema_version": "facetta-canonical-persistence-attestation.v1",
        "canonical_api_schema_version": "facetta-canonical-project-api.v1",
        "attestation_id": "persistence-test-1",
        "corpus_run_id": "corpus-run-test-1",
        "commit_sha": "d" * 40,
        "config_id": "test-config",
        "config_sha256": _sha(config),
        "workload_id": "test-workload-v1",
        "workload_sha256": _sha(workload),
        "corpus_id": "test-corpus",
        "result_set_schema_version": "facetta-frozen-selected-result-set.v1",
        "result_set": selected_result_set,
        "result_set_sha256": result_set_sha256(selected_result_set),
        "result_count": len(selected_result_set),
        "checks": {
            "atomic_image_spec_persistence": {
                "status": "pass",
                "verified_result_count": len(selected_result_set),
                "image_and_spec_committed_together": True,
                "partial_commit_count": 0,
            },
            "stale_write_rejection": {
                "status": "pass", "attempted_count": 2,
                "rejected_count": 2, "canonical_mutation_count": 0,
            },
            "rejected_candidate_persistence": {
                "status": "pass", "tested_rejected_candidate_count": 2,
                "active_asset_count": 0,
            },
        },
    }
    attestation["signature"] = {
        "algorithm": "Ed25519",
        "key_id": "canonical-api-runner-v1",
        "value": base64.b64encode(runner_private_key.sign(
            canonical_attestation_payload(attestation)
        )).decode("ascii"),
    }
    evidence_value["persistence_evidence"] = attestation
    _write_signed(paths, evidence_value)
    return paths


def _run(paths: dict[str, Any], *, evidence: bool = True) -> dict:
    return compile_frozen_corpus_gate(
        paths["manifest"], paths["config"], paths["source_dir"],
        paths["evidence"] if evidence else None,
        repository_root=paths["root"],
        workload_path=paths["workload"],
        evidence_root=paths["root"],
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
    assert result["schema_version"] == "facetta-frozen-corpus-gate-result.v1"
    assert result["run_kind"] == "provider_free_frozen_corpus_gate"
    assert result["corpus_gate_ready"] is True
    assert "release_ready" not in result
    assert result["source_integrity"]["status"] == "pass"
    assert result["quality"]["status"] == "pass"
    assert result["quality"]["signature"]["status"] == "verified"
    assert result["evidence"] == {
        "path": paths["evidence"].name,
        "sha256": _sha(paths["evidence"]),
        "schema_version": "facetta-frozen-replay.v1",
        "workload_sha256": _sha(paths["workload"]),
        "capture_sha256": _sha(paths["capture_artifact"]),
        "corpus_run_id": "corpus-run-test-1",
        "reviewer_key_id": "test-reviewer-v1",
    }
    assert result["quality"]["source_coverage"] == {
        "status": "pass",
        "expected_source_count": 1,
        "completed_source_count": 1,
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
    assert result["corpus_gate_ready"] is False
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


def test_release_authorities_cannot_reuse_public_key_bytes(tmp_path: Path):
    paths = _fixture(tmp_path)
    config = json.loads(paths["config"].read_text())
    config["canonical_api_runner_public_key"] = {
        "key_id": "canonical-api-runner-distinct-label",
        "path": paths["reviewer_key"].name,
        "sha256": _sha(paths["reviewer_key"]),
    }
    _json(paths["config"], config)

    result = _run(paths, evidence=False)

    separation = result["implementation"]["authority_key_separation"]
    assert separation["status"] == "fail"
    assert any(
        "canonical_api_runner, gia_reviewer" in error
        and "public-key bytes" in error
        for error in separation["errors"]
    )
    assert result["definition"]["status"] == "fail"
    assert result["corpus_gate_ready"] is False


def test_release_authorities_cannot_reuse_key_ids(tmp_path: Path):
    paths = _fixture(tmp_path)
    config = json.loads(paths["config"].read_text())
    config["canonical_api_runner_public_key"]["key_id"] = "test-reviewer-v1"
    _json(paths["config"], config)

    result = _run(paths, evidence=False)

    separation = result["implementation"]["authority_key_separation"]
    assert separation["status"] == "fail"
    assert any(
        "canonical_api_runner, gia_reviewer" in error
        and "key_id" in error
        for error in separation["errors"]
    )
    assert result["definition"]["status"] == "fail"
    assert result["corpus_gate_ready"] is False


def test_separation_audit_covers_all_six_release_authorities():
    config = {
        "executor_trust": {
            "status": "enrolled",
            "key_id": "executor-v1",
            "public_key": f"keys/executor.pub@sha256:{'1' * 64}",
        },
        "canonical_api_runner_public_key": {
            "key_id": "runner-v1", "sha256": "2" * 64,
        },
        "reviewer_public_key": {
            "key_id": "gia-v1", "sha256": "3" * 64,
        },
        "founder_public_key": {
            "key_id": "founder-v1", "sha256": "4" * 64,
        },
        "designer_reviewer_public_key": {
            "key_id": "designer-v1", "sha256": "5" * 64,
        },
        "staging_reviewer_public_key": {
            "key_id": "staging-v1", "sha256": "6" * 64,
        },
    }

    audit = release_authority_key_separation(config)
    assert audit["status"] == "pass"
    assert audit["configured_roles"] == [
        "canonical_api_runner",
        "executor",
        "founder",
        "gia_reviewer",
        "jewelry_designer",
        "staging_reviewer",
    ]
    assert audit["missing_roles"] == []

    config["executor_trust"]["public_key"] = (
        f"keys/executor.pub@sha256:{'4' * 64}"
    )
    duplicate = release_authority_key_separation(config)
    assert duplicate["status"] == "fail"
    assert any(
        "executor, founder" in error and "public-key bytes" in error
        for error in duplicate["errors"]
    )


def test_pinned_capture_producer_drift_fails_definition(tmp_path: Path):
    paths = _fixture(tmp_path)
    paths["capture_producer"].write_text("# changed capture producer\n")
    result = _run(paths, evidence=False)
    assert result["definition"]["status"] == "fail"
    assert any("capture_producer implementation drifted" in error
               for error in result["definition"]["errors"])


def test_absent_replay_is_not_run_and_fails_closed(tmp_path: Path):
    paths = _fixture(tmp_path)
    result = _run(paths, evidence=False)
    assert result["source_integrity"]["status"] == "pass"
    assert result["quality"]["status"] == "not_run"
    assert result["corpus_gate_ready"] is False


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


def test_attempt_indexes_must_be_contiguous_per_source_assignment(tmp_path: Path):
    paths = _fixture(tmp_path)
    evidence = _refresh_evidence_hashes(paths)
    evidence["attempts"][0]["attempt"] = 2
    _write_signed(paths, evidence)
    result = _run(paths)
    assert any(
        "attempt indexes are not contiguous" in error
        for error in result["quality"]["errors"]
    )
    assert result["corpus_gate_ready"] is False


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
    evidence["persistence_evidence"]["checks"][
        "rejected_candidate_persistence"
    ]["active_asset_count"] = 1
    _write_signed(paths, evidence)
    result = _run(paths)
    assert result["quality"]["release_gates"][
        "zero_rejected_candidates_persisted"
    ] is False
    assert result["corpus_gate_ready"] is False


def test_shallow_persistence_self_assertion_fails_gate(tmp_path: Path):
    paths = _fixture(tmp_path)
    evidence = _refresh_evidence_hashes(paths)
    evidence["persistence_evidence"] = {
        "verified": True,
        "method": "canonical_project_api_integration",
        "result_set": "test-result",
        "rejected_active_asset_count": 0,
    }
    _write_signed(paths, evidence)
    result = _run(paths)
    assert result["quality"]["persistence_attestation"]["status"] == "fail"
    assert result["quality"]["release_gates"][
        "persistence_evidence_verified"
    ] is False
    assert any(
        "persistence attestation schema_version" in error
        for error in result["quality"]["errors"]
    )


def test_persistence_attestation_cannot_replay_across_capture_runs(tmp_path: Path):
    paths = _fixture(tmp_path)
    evidence = _refresh_evidence_hashes(paths)
    evidence["capture_provenance"]["corpus_run_id"] = "another-run"
    _write_signed(paths, evidence)
    result = _run(paths)
    assert result["corpus_gate_ready"] is False
    assert any(
        "corpus_run_id differs from signed capture" in error
        for error in result["quality"]["errors"]
    )


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
    assert result["corpus_gate_ready"] is False


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
    assert result["corpus_gate_ready"] is False


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
    assert result["corpus_gate_ready"] is False


def test_unsigned_evidence_fails_signature_gate(tmp_path: Path):
    paths = _fixture(tmp_path)
    evidence = json.loads(paths["evidence"].read_text())
    evidence.pop("signature")
    _json(paths["evidence"], evidence)
    result = _run(paths)
    assert result["quality"]["signature"]["status"] == "not_verified"
    assert any("unsigned" in error for error in result["quality"]["errors"])
    assert result["corpus_gate_ready"] is False


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
    assert coverage["expected_source_count"] == 1
    assert coverage["completed_source_count"] == 1
    assert coverage["missing_source_filenames"] == []
    assert any("lack matching coverage rows" in error
               for error in coverage["errors"])
    assert result["corpus_gate_ready"] is False


def test_signed_coverage_claim_without_source_attempt_fails(tmp_path: Path):
    paths = _fixture(tmp_path)
    evidence = _refresh_evidence_hashes(paths)
    evidence["attempts"] = [
        row for row in evidence["attempts"]
        if row["evaluation_id"] != "edit-structural"
    ]
    _write_signed(paths, evidence)
    result = _run(paths)
    coverage = result["quality"]["source_coverage"]
    assert coverage["expected_source_count"] == 1
    assert coverage["completed_source_count"] == 0
    assert coverage["missing_source_filenames"] == ["image-1.png"]
    assert any("do not match verified attempts" in error
               for error in coverage["errors"])
    assert result["corpus_gate_ready"] is False


def test_attempt_artifact_hash_mismatch_fails(tmp_path: Path):
    paths = _fixture(tmp_path)
    _image(paths["edit_candidate"], "black")
    result = _run(paths)
    assert any("candidate_image artifact hash mismatch" in error
               for error in result["quality"]["errors"])
    assert result["corpus_gate_ready"] is False


def test_replay_rejects_absolute_artifact_reference(tmp_path: Path):
    paths = _fixture(tmp_path)
    evidence = _refresh_evidence_hashes(paths)
    evidence["attempts"][0]["candidate_image"] = str(paths["render_candidate"])
    _write_signed(paths, evidence)

    result = _run(paths)
    assert result["corpus_gate_ready"] is False
    assert any(
        "must be evidence-root-relative" in error
        or "lacks candidate_image artifact" in error
        for error in result["quality"]["errors"]
    )


def test_replay_rejects_traversal_artifact_reference(tmp_path: Path):
    paths = _fixture(tmp_path)
    outside = tmp_path.parent / "outside-candidate.png"
    _image(outside, "white")
    evidence = _refresh_evidence_hashes(paths)
    evidence["attempts"][0]["candidate_image"] = "../outside-candidate.png"
    evidence["attempts"][0]["candidate_image_sha256"] = _sha(outside)
    _write_signed(paths, evidence)

    result = _run(paths)
    assert result["corpus_gate_ready"] is False
    assert any(
        "escapes the evidence root" in error
        for error in result["quality"]["errors"]
    )


def test_replay_rejects_symlink_artifact_escape(tmp_path: Path):
    paths = _fixture(tmp_path)
    outside = tmp_path.parent / "symlink-candidate.png"
    _image(outside, "white")
    link = paths["root"] / "escaped-candidate.png"
    link.symlink_to(outside)
    evidence = _refresh_evidence_hashes(paths)
    evidence["attempts"][0]["candidate_image"] = link.name
    evidence["attempts"][0]["candidate_image_sha256"] = _sha(outside)
    _write_signed(paths, evidence)

    result = _run(paths)
    assert result["corpus_gate_ready"] is False
    assert any(
        "escapes the evidence root" in error
        for error in result["quality"]["errors"]
    )


def test_replay_artifact_must_be_in_canonical_index(tmp_path: Path):
    paths = _fixture(tmp_path)
    evidence = _refresh_evidence_hashes(paths)
    indexed = evidence["artifact_index"]["artifacts"]
    evidence["artifact_index"]["artifacts"] = [
        row for row in indexed if row["path"] != paths["render_candidate"].name
    ]
    _sign(paths, evidence)
    _json(paths["evidence"], evidence)

    result = _run(paths)
    assert result["corpus_gate_ready"] is False
    assert any(
        "artifact_index canonical hash differs" in error
        or "absent from the artifact index" in error
        for error in result["quality"]["errors"]
    )


def test_replay_file_must_resolve_beneath_explicit_evidence_root(tmp_path: Path):
    paths = _fixture(tmp_path)
    outside = tmp_path.parent / "outside-replay.json"
    outside.write_bytes(paths["evidence"].read_bytes())
    result = compile_frozen_corpus_gate(
        paths["manifest"],
        paths["config"],
        paths["source_dir"],
        outside,
        repository_root=paths["root"],
        workload_path=paths["workload"],
        evidence_root=paths["root"],
    )
    assert result["corpus_gate_ready"] is False
    assert "replay evidence escapes the evidence root" in result["quality"]["errors"]


def test_non_ring_quality_attempt_is_an_unexpected_assignment(tmp_path: Path):
    paths = _fixture(tmp_path)
    evidence = _refresh_evidence_hashes(paths)
    extra = dict(evidence["attempts"][0])
    extra.update({
        "source_filename": paths["second"].name,
        "source_sha256": _sha(paths["second"]),
        "source_image": paths["second"].relative_to(paths["root"]).as_posix(),
        "source_image_sha256": _sha(paths["second"]),
    })
    evidence["attempts"].append(extra)
    _write_signed(paths, evidence)
    result = _run(paths)
    assert any(
        "unexpected workload assignments" in error
        for error in result["quality"]["errors"]
    )
    assert result["corpus_gate_ready"] is False


def test_attempt_operation_class_must_match_workload(tmp_path: Path):
    paths = _fixture(tmp_path)
    evidence = _refresh_evidence_hashes(paths)
    evidence["attempts"][0]["operation_class"] = "structural"
    _write_signed(paths, evidence)
    result = _run(paths)
    assert any(
        "operation_class differs from frozen workload" in error
        for error in result["quality"]["errors"]
    )
    assert result["corpus_gate_ready"] is False


def test_gia_rejection_of_render_fails_quality(tmp_path: Path):
    paths = _fixture(tmp_path)
    evidence = _refresh_evidence_hashes(paths)
    decision = next(
        row for row in evidence["reviewer_review"]["decisions"]
        if row["kind"] == "render"
    )
    decision["accepted"] = False
    evidence["reviewer_review"]["false_positives"] = 1
    _write_signed(paths, evidence)
    result = _run(paths)
    assert result["quality"]["all_reviewer_decisions_accepted"] is False
    assert result["quality"]["status"] == "fail"


def test_gia_rejection_of_structural_edit_fails_quality(tmp_path: Path):
    paths = _fixture(tmp_path)
    evidence = _refresh_evidence_hashes(paths)
    decision = next(
        row for row in evidence["reviewer_review"]["decisions"]
        if row["evaluation_id"] == "edit-structural"
    )
    decision["accepted"] = False
    evidence["reviewer_review"]["false_positives"] = 1
    _write_signed(paths, evidence)
    result = _run(paths)
    assert result["quality"]["all_reviewer_decisions_accepted"] is False
    assert result["quality"]["status"] == "fail"


def test_rejected_render_attempt_cannot_hard_pass(tmp_path: Path):
    paths = _fixture(tmp_path)
    evidence = _refresh_evidence_hashes(paths)
    render = next(row for row in evidence["attempts"] if row["kind"] == "render")
    render["accepted"] = False
    evidence["reviewer_review"]["false_negatives"] = 1
    _write_signed(paths, evidence)
    result = _run(paths)
    assert result["quality"]["release_gates"]["hard_gate_pass"] is False
    assert result["quality"]["status"] == "fail"


def test_non_finite_score_fails_closed(tmp_path: Path):
    paths = _fixture(tmp_path)
    evidence = _refresh_evidence_hashes(paths)
    evidence["attempts"][0]["render_conformance_score"] = float("nan")
    _write_signed(paths, evidence)
    result = _run(paths)
    assert any(
        "lacks scored capture evidence" in error
        for error in result["quality"]["errors"]
    )
    assert result["quality"]["status"] == "fail"


def test_uniform_edit_mask_cannot_claim_zero_drift(tmp_path: Path):
    paths = _fixture(tmp_path)
    Image.new("L", (4, 4), 255).save(paths["root"] / "mask.png")
    evidence = _refresh_evidence_hashes(paths)
    for row in evidence["attempts"]:
        if row["kind"] == "edit":
            row["mask_image_sha256"] = _sha(paths["root"] / "mask.png")
    _write_signed(paths, evidence)
    result = _run(paths)
    assert any(
        "mask lacks selected/protected regions" in error
        for error in result["quality"]["errors"]
    )
    assert result["quality"]["status"] == "fail"


def test_replay_must_bind_exact_workload_hash(tmp_path: Path):
    paths = _fixture(tmp_path)
    evidence = _refresh_evidence_hashes(paths)
    evidence["workload_sha256"] = "0" * 64
    _write_signed(paths, evidence)
    result = _run(paths)
    assert "replay workload hash differs" in " ".join(
        result["quality"]["errors"]
    )
    assert result["corpus_gate_ready"] is False

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from facetta.frozen_capture_workload import (
    build_provider_call_plan,
    canonical_capture_payload,
    validate_capture_envelope,
    validate_workload_definition,
)


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    root = tmp_path / "repo"
    manifest = root / "manifest.json"
    config = root / "config.json"
    workload = root / "workload.json"
    source_hashes = {"ring.png": "a" * 64, "necklace.png": "b" * 64}
    _write(manifest, {
        "corpus_id": "fixture-v1",
        "expected_source_count": 2,
        "sources": [
            {"filename": filename, "sha256": digest}
            for filename, digest in source_hashes.items()
        ],
        "evaluation_slice": {
            "ring_source_filenames": ["ring.png"],
            "render_case_ids": ["render-one"],
            "operation_ids": ["metal-color"],
            "operation_classes": {
                "quick_appearance": ["metal-color"],
                "structural": [],
            },
        },
    })
    _write(workload, {
        "schema_version": "facetta-frozen-capture-workload.v1",
        "workload_id": "fixture-workload-v1",
        "corpus_id": "fixture-v1",
        "config_id": "fixture-config-v1",
        "manifest_sha256": _sha(manifest),
        "expected_integrity_source_count": 2,
        "expected_quality_source_count": 1,
        "ring_quality_evaluation_set_id": "ring-full-v1",
        "evaluation_sets": {"ring-full-v1": [
            {
                "kind": "render",
                "evaluation_id": "render-one",
                "operation_class": "render_conformance",
            },
            {
                "kind": "edit",
                "evaluation_id": "metal-color",
                "operation_class": "quick_appearance",
            },
        ]},
        "sources": [
            {
                "filename": "ring.png",
                "sha256": source_hashes["ring.png"],
                "integrity_required": True,
                "quality": {
                    "slice": "ring",
                    "evaluation_set_id": "ring-full-v1",
                },
            },
            {
                "filename": "necklace.png",
                "sha256": source_hashes["necklace.png"],
                "integrity_required": True,
                "quality": None,
            },
        ],
    })
    _write(config, {
        "config_id": "fixture-config-v1",
        "manifest_sha256": _sha(manifest),
        "thresholds": {"max_attempts": 3},
        "frozen_components": {
            "capture_workload": f"workload.json@sha256:{_sha(workload)}",
        },
    })
    return root, manifest, config, workload


def test_definition_separates_integrity_from_ring_quality(tmp_path: Path):
    root, manifest, config, workload = _fixture(tmp_path)
    result = validate_workload_definition(
        manifest, config, workload, repository_root=root,
    )
    assert result["status"] == "pass"
    assert result["provider_calls"] == 0
    assert result["integrity_source_count"] == 2
    assert result["quality_source_count"] == 1
    assert result["planned_evaluation_sequence_count"] == 2
    assert result["corpus_gate_ready"] is False


def test_definition_rejects_quality_assignment_outside_ring_slice(tmp_path: Path):
    root, manifest, config, workload = _fixture(tmp_path)
    raw = json.loads(workload.read_text())
    raw["sources"][1]["quality"] = {
        "slice": "ring", "evaluation_set_id": "ring-full-v1",
    }
    _write(workload, raw)
    config_raw = json.loads(config.read_text())
    config_raw["frozen_components"]["capture_workload"] = (
        f"workload.json@sha256:{_sha(workload)}"
    )
    _write(config, config_raw)
    result = validate_workload_definition(
        manifest, config, workload, repository_root=root,
    )
    assert result["status"] == "fail"
    assert "non-ring source has a quality assignment: necklace.png" in result["errors"]


def test_plan_is_deterministic_and_executes_no_provider_calls(tmp_path: Path):
    root, manifest, config, workload = _fixture(tmp_path)
    first = build_provider_call_plan(
        manifest, config, workload, repository_root=root,
    )
    second = build_provider_call_plan(
        manifest, config, workload, repository_root=root,
    )
    assert first == second
    assert first["provider_calls_executed"] == 0
    assert first["planned_evaluation_sequence_count"] == 2
    assert first["maximum_provider_attempt_count"] == 6
    assert {row["source_filename"] for row in first["items"]} == {"ring.png"}


def test_signed_capture_binds_plan_artifacts_and_persistence(tmp_path: Path):
    root, manifest, config, workload = _fixture(tmp_path)
    plan = build_provider_call_plan(
        manifest, config, workload, repository_root=root,
    )
    capture_dir = root / "capture"
    capture_dir.mkdir()
    (capture_dir / "render.png").write_bytes(b"render")
    (capture_dir / "edit.png").write_bytes(b"edit")
    (capture_dir / "mask.png").write_bytes(b"mask")
    (capture_dir / "persistence.json").write_text('{"verified":true}\n')
    attempts = []
    artifact_names = {
        "render": ("render.png", None),
        "edit": ("edit.png", "mask.png"),
    }
    for planned in plan["items"]:
        candidate, mask = artifact_names[planned["kind"]]
        row = {
            "kind": planned["kind"],
            "evaluation_id": planned["evaluation_id"],
            "source_filename": planned["source_filename"],
            "source_sha256": planned["source_sha256"],
            "attempt": 1,
            "accepted": True,
            "candidate_image": candidate,
            "candidate_image_sha256": _sha(capture_dir / candidate),
        }
        if planned["kind"] == "render":
            row.update(render_conformance_score=95, hard_gate_pass=True)
        else:
            row.update(
                edit_fidelity_score=95,
                severity="none",
                change_applied=True,
            )
        if mask:
            row["mask_image"] = mask
            row["mask_image_sha256"] = _sha(capture_dir / mask)
        attempts.append(row)
    capture = {
        "schema_version": "facetta-frozen-capture.v1",
        "manifest_sha256": plan["manifest_sha256"],
        "config_sha256": plan["config_sha256"],
        "workload_sha256": plan["workload_sha256"],
        "attempts": attempts,
        "persistence_evidence_ref": {
            "relative_path": "persistence.json",
            "sha256": _sha(capture_dir / "persistence.json"),
        },
        "signature": None,
    }
    private_key = Ed25519PrivateKey.generate()
    public_key_path = root / "executor.pub"
    public_key_path.write_bytes(private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ))
    signature = private_key.sign(canonical_capture_payload(capture))
    capture["signature"] = {
        "algorithm": "Ed25519",
        "key_id": "executor-test-v1",
        "public_key_sha256": _sha(public_key_path),
        "value": base64.b64encode(signature).decode("ascii"),
    }
    capture_path = capture_dir / "capture.json"
    _write(capture_path, capture)

    result = validate_capture_envelope(
        capture_path,
        manifest,
        config,
        workload,
        capture_public_key_path=public_key_path,
        capture_key_id="executor-test-v1",
        repository_root=root,
    )
    assert result["status"] == "pass"
    assert result["signature_status"] == "verified"
    assert result["captured_evaluation_sequence_count"] == 2
    assert result["corpus_gate_ready"] is False


def test_signed_capture_rejects_artifact_tampering(tmp_path: Path):
    root, manifest, config, workload = _fixture(tmp_path)
    plan = build_provider_call_plan(
        manifest, config, workload, repository_root=root,
    )
    capture_dir = root / "capture"
    capture_dir.mkdir()
    candidate = capture_dir / "candidate.png"
    mask = capture_dir / "mask.png"
    persistence = capture_dir / "persistence.json"
    candidate.write_bytes(b"candidate")
    mask.write_bytes(b"mask")
    persistence.write_text("{}\n")
    attempts = []
    for planned in plan["items"]:
        row = {
            "kind": planned["kind"],
            "evaluation_id": planned["evaluation_id"],
            "source_filename": planned["source_filename"],
            "source_sha256": planned["source_sha256"],
            "attempt": 1,
            "accepted": True,
            "candidate_image": candidate.name,
            "candidate_image_sha256": _sha(candidate),
        }
        if planned["kind"] == "render":
            row.update(render_conformance_score=95, hard_gate_pass=True)
        else:
            row.update(
                edit_fidelity_score=95,
                severity="none",
                change_applied=True,
            )
        if planned["kind"] == "edit":
            row.update(mask_image=mask.name, mask_image_sha256=_sha(mask))
        attempts.append(row)
    capture = {
        "schema_version": "facetta-frozen-capture.v1",
        "manifest_sha256": plan["manifest_sha256"],
        "config_sha256": plan["config_sha256"],
        "workload_sha256": plan["workload_sha256"],
        "attempts": attempts,
        "persistence_evidence_ref": {
            "relative_path": persistence.name, "sha256": _sha(persistence),
        },
        "signature": None,
    }
    key = Ed25519PrivateKey.generate()
    public_key_path = root / "executor.pub"
    public_key_path.write_bytes(key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ))
    capture["signature"] = {
        "algorithm": "Ed25519",
        "key_id": "executor-test-v1",
        "public_key_sha256": _sha(public_key_path),
        "value": base64.b64encode(
            key.sign(canonical_capture_payload(capture))
        ).decode("ascii"),
    }
    capture_path = capture_dir / "capture.json"
    _write(capture_path, capture)
    candidate.write_bytes(b"tampered")

    result = validate_capture_envelope(
        capture_path,
        manifest,
        config,
        workload,
        capture_public_key_path=public_key_path,
        capture_key_id="executor-test-v1",
        repository_root=root,
    )
    assert result["status"] == "fail"
    assert any("candidate_image hash differs" in error for error in result["errors"])

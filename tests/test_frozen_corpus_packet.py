from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from PIL import Image

from facetta.frozen_capture_workload import (
    build_provider_call_plan,
    canonical_capture_payload,
)
from facetta.frozen_corpus_packet import prepare_frozen_corpus_review_packet


def _json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> dict[str, Path | str]:
    root = tmp_path / "repo"
    sources = root / "sources"
    sources.mkdir(parents=True)
    ring = sources / "ring.png"
    necklace = sources / "necklace.png"
    Image.new("RGB", (4, 4), "white").save(ring)
    Image.new("RGB", (4, 4), "blue").save(necklace)

    manifest = root / "manifest.json"
    _json(manifest, {
        "corpus_id": "fixture-v1",
        "expected_source_count": 2,
        "sources": [
            {"filename": ring.name, "sha256": _sha(ring)},
            {"filename": necklace.name, "sha256": _sha(necklace)},
        ],
        "evaluation_slice": {
            "ring_source_filenames": [ring.name],
            "render_case_ids": ["render-one"],
            "operation_ids": ["metal-color"],
            "operation_classes": {
                "quick_appearance": ["metal-color"],
                "structural": [],
            },
        },
    })
    workload = root / "workload.json"
    _json(workload, {
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
                "filename": ring.name,
                "sha256": _sha(ring),
                "integrity_required": True,
                "quality": {
                    "slice": "ring",
                    "evaluation_set_id": "ring-full-v1",
                },
            },
            {
                "filename": necklace.name,
                "sha256": _sha(necklace),
                "integrity_required": True,
                "quality": None,
            },
        ],
    })
    config = root / "config.json"
    _json(config, {
        "config_id": "fixture-config-v1",
        "manifest_sha256": _sha(manifest),
        "thresholds": {"max_attempts": 3},
        "frozen_components": {
            "capture_workload": f"workload.json@sha256:{_sha(workload)}",
        },
    })
    plan = build_provider_call_plan(
        manifest, config, workload, repository_root=root,
    )
    capture_dir = root / "capture"
    capture_dir.mkdir()
    attempts = []
    for index, planned in enumerate(plan["items"], 1):
        candidate = capture_dir / f"candidate-{index}.png"
        Image.new("RGB", (4, 4), "gray").save(candidate)
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
            mask = capture_dir / f"mask-{index}.png"
            Image.new("RGB", (4, 4), "black").save(mask)
            row.update(
                mask_image=mask.name,
                mask_image_sha256=_sha(mask),
                edit_fidelity_score=95,
                severity="none",
                change_applied=True,
            )
        attempts.append(row)
    persistence = capture_dir / "persistence.json"
    _json(persistence, {
        "verified": True,
        "canonical_api": "POST /projects/{project_id}/preview-candidates/{id}/apply",
        "rejected_candidates_became_active_assets": 0,
    })
    capture = {
        "schema_version": "facetta-frozen-capture.v1",
        "manifest_sha256": plan["manifest_sha256"],
        "config_sha256": plan["config_sha256"],
        "workload_sha256": plan["workload_sha256"],
        "attempts": attempts,
        "persistence_evidence_ref": {
            "relative_path": persistence.name,
            "sha256": _sha(persistence),
        },
        "signature": None,
    }
    private_key = Ed25519PrivateKey.generate()
    public_key = root / "executor.pub"
    public_key.write_bytes(private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ))
    capture["signature"] = {
        "algorithm": "Ed25519",
        "key_id": "executor-test-v1",
        "public_key_sha256": _sha(public_key),
        "value": base64.b64encode(
            private_key.sign(canonical_capture_payload(capture))
        ).decode("ascii"),
    }
    capture_path = capture_dir / "capture.json"
    _json(capture_path, capture)
    return {
        "root": root,
        "manifest": manifest,
        "config": config,
        "workload": workload,
        "sources": sources,
        "capture": capture_path,
        "public_key": public_key,
        "persistence": persistence,
        "key_id": "executor-test-v1",
    }


def _prepare(fixture: dict[str, Path | str]) -> dict[str, object]:
    return prepare_frozen_corpus_review_packet(
        fixture["manifest"],  # type: ignore[arg-type]
        fixture["config"],  # type: ignore[arg-type]
        fixture["workload"],  # type: ignore[arg-type]
        fixture["sources"],  # type: ignore[arg-type]
        fixture["capture"],  # type: ignore[arg-type]
        capture_public_key_path=fixture["public_key"],  # type: ignore[arg-type]
        capture_key_id=str(fixture["key_id"]),
        repository_root=fixture["root"],  # type: ignore[arg-type]
    )


def test_packet_uses_only_workload_quality_assignments(tmp_path: Path):
    fixture = _fixture(tmp_path)
    packet = _prepare(fixture)

    assert packet["quality_scope"] == {
        "slice": "ring",
        "source_count": 1,
        "evaluation_sequence_count": 2,
        "status": "pending_review",
    }
    assert packet["integrity_prerequisite"] == {
        "manifest_sha256": _sha(fixture["manifest"]),  # type: ignore[arg-type]
        "expected_source_count": 2,
        "status": "required_separately",
        "verified_source_count": None,
        "quality_inference_allowed": False,
    }
    assert [row["filename"] for row in packet["source_coverage"]] == ["ring.png"]
    assert len(packet["reviewer_review"]["decisions"]) == 2
    assert all(
        row["source_filename"] == "ring.png"
        for row in packet["reviewer_review"]["decisions"]
    )
    assert all(
        row["accepted"] is None
        for row in packet["reviewer_review"]["decisions"]
    )
    assert packet["signature"] is None
    assert packet["corpus_gate_ready"] is False


def test_packet_embeds_exact_hash_bound_persistence_object(tmp_path: Path):
    fixture = _fixture(tmp_path)
    packet = _prepare(fixture)

    signed_capture_sha256 = _sha(fixture["capture"])  # type: ignore[arg-type]
    assert packet["capture_sha256"] == signed_capture_sha256
    assert (
        packet["capture_provenance"]["capture_sha256"]
        == packet["capture_sha256"]
    )
    assert packet["persistence_evidence"]["verified"] is True
    assert packet["persistence_evidence_binding"]["sha256"] == _sha(
        fixture["persistence"],  # type: ignore[arg-type]
    )
    assert packet["capture_provenance"]["executor_signature_status"] == "verified"


def test_packet_rejects_unsigned_capture(tmp_path: Path):
    fixture = _fixture(tmp_path)
    capture = json.loads(fixture["capture"].read_text())  # type: ignore[union-attr]
    capture["signature"] = None
    _json(fixture["capture"], capture)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="capture validation failed: capture is unsigned"):
        _prepare(fixture)


def test_packet_rejects_tampered_persistence_bytes(tmp_path: Path):
    fixture = _fixture(tmp_path)
    fixture["persistence"].write_text('{"verified": false}\n')  # type: ignore[union-attr]

    with pytest.raises(ValueError, match="persistence evidence hash differs"):
        _prepare(fixture)


def test_packet_rejects_non_object_persistence_contents(tmp_path: Path):
    fixture = _fixture(tmp_path)
    persistence = fixture["persistence"]
    persistence.write_text("[]\n")  # type: ignore[union-attr]
    capture_path = fixture["capture"]
    capture = json.loads(capture_path.read_text())  # type: ignore[union-attr]
    capture["persistence_evidence_ref"]["sha256"] = _sha(persistence)  # type: ignore[arg-type]

    # Re-sign after changing the binding so capture provenance is valid; packet
    # conversion must still reject contents that replay cannot consume.
    key = Ed25519PrivateKey.generate()
    public_key = fixture["public_key"]
    public_key.write_bytes(key.public_key().public_bytes(  # type: ignore[union-attr]
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ))
    capture["signature"] = {
        "algorithm": "Ed25519",
        "key_id": fixture["key_id"],
        "public_key_sha256": _sha(public_key),  # type: ignore[arg-type]
        "value": base64.b64encode(
            key.sign(canonical_capture_payload(capture))
        ).decode("ascii"),
    }
    _json(capture_path, capture)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="persistence evidence must be a JSON object"):
        _prepare(fixture)


def test_packet_rejects_changed_quality_source(tmp_path: Path):
    fixture = _fixture(tmp_path)
    Image.new("RGB", (4, 4), "red").save(fixture["sources"] / "ring.png")  # type: ignore[operator]

    with pytest.raises(ValueError, match="quality source hash differs"):
        _prepare(fixture)

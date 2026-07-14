from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from PIL import Image

from facetta.blind_jewelry_review import (
    BLIND_REVIEW_PACKET_SCHEMA,
    GIA_VISUAL_FIDELITY_ROLE,
    validate_blind_review_packet,
)
from facetta.frozen_capture_workload import (
    FROZEN_ROUTING_LABEL,
    build_provider_call_plan,
    canonical_capture_payload,
    expected_attempt_routing,
    not_applicable_assignment_rows,
)
from facetta.frozen_corpus_packet import (
    prepare_blind_frozen_corpus_review_packet_v2,
    prepare_frozen_corpus_review_packet,
)
from facetta.frozen_evidence_paths import confined_output_path
from facetta.ring_evals import (
    CANONICAL_RING_EDITS,
    RING_GOLDEN_CASES,
    apply_canonical_ring_edit,
    build_ring_golden_spec,
)


def _json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _install_routing_contract(root: Path) -> Path:
    source = (
        Path(__file__).resolve().parents[1]
        / "docs/evals/frozen-founder-corpus-v1/routing-contract.v1.json"
    )
    destination = root / "routing-contract.v1.json"
    destination.write_bytes(source.read_bytes())
    return destination


def _binding(evaluation_id: str, kind: str) -> dict[str, object]:
    cases = {case.id: case for case in RING_GOLDEN_CASES}
    if kind == "render":
        source = build_ring_golden_spec(cases[evaluation_id])
        target = source
        instruction = f"frozen founder corpus render: {evaluation_id}"
        region = None
        frozen = ["reviewed synthetic source geometry"]
    else:
        edit = next(item for item in CANONICAL_RING_EDITS if item.id == evaluation_id)
        source = build_ring_golden_spec(cases[edit.golden_case_id])
        target, issues = apply_canonical_ring_edit(source, edit)
        assert target is not None and not issues
        instruction = edit.instruction
        region = None if edit.visual_only else edit.region
        frozen = list(edit.frozen_facts)
    return {
        "schema_version": "facetta-frozen-source-assignment.v1",
        "review_status": "approved",
        "applicability": "execute",
        "review_evidence_sha256": "4" * 64,
        "source_spec_evidence_sha256": "5" * 64,
        "component_map_sha256": "6" * 64,
        "region_evidence_sha256": "7" * 64,
        "source_spec": source.model_dump(mode="json"),
        "target_spec": target.model_dump(mode="json"),
        "instruction": instruction,
        "region_description": region,
        "frozen_facts": frozen,
    }


def _fixture(
    tmp_path: Path,
    *,
    not_applicable_edit: bool = False,
) -> dict[str, Any]:
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
            "render_case_ids": ["round-solitaire-yellow-4-narrow"],
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
                "evaluation_id": "round-solitaire-yellow-4-narrow",
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
    assignment_bundle = root / "assignments.json"
    _json(assignment_bundle, {
        "schema_version": "facetta-frozen-assignment-bundle.v1",
        "workload_sha256": _sha(workload),
        "corpus_run_id": "packet-fixture-run-v1",
        "assignments": [
            {
                "source_filename": ring.name,
                "kind": kind,
                "evaluation_id": evaluation_id,
                "binding": _binding(evaluation_id, kind),
            }
            for kind, evaluation_id in (
                ("render", "round-solitaire-yellow-4-narrow"),
                ("edit", "metal-color"),
            )
        ],
    })
    if not_applicable_edit:
        assignment_raw = json.loads(assignment_bundle.read_text())
        edit = next(
            row for row in assignment_raw["assignments"]
            if row["kind"] == "edit"
        )
        edit["binding"] = {
            "schema_version": "facetta-frozen-source-assignment.v1",
            "review_status": "approved",
            "applicability": "not_applicable",
            "not_applicable_reason": "source contains no eligible metal surface",
            "review_evidence_sha256": "4" * 64,
            "source_spec_evidence_sha256": "5" * 64,
            "component_map_sha256": "6" * 64,
            "region_evidence_sha256": "7" * 64,
        }
        _json(assignment_bundle, assignment_raw)
    private_key = Ed25519PrivateKey.generate()
    public_key = root / "executor.pub"
    public_key.write_bytes(private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ))
    config = root / "config.json"
    routing_contract = _install_routing_contract(root)
    _json(config, {
        "config_id": "fixture-config-v1",
        "manifest_sha256": _sha(manifest),
        "thresholds": {
            "max_attempts": 3,
            "mean_render_conformance": 85,
            "render_hard_gate_pass_rate": 0.9,
            "mean_edit_fidelity": 90,
            "max_outside_mask_drift": 0.18,
        },
        "frozen_components": {
            "capture_workload": f"workload.json@sha256:{_sha(workload)}",
            "resolved_assignment_bundle": (
                f"assignments.json@sha256:{_sha(assignment_bundle)}"
            ),
            "ring_contract": "fixture-ring-contract@sha256:" + "1" * 64,
            "prompt_bundle": "fixture-prompt-bundle@sha256:" + "2" * 64,
            "evaluator_bundle": "fixture-evaluator-bundle@sha256:" + "3" * 64,
            "routing": FROZEN_ROUTING_LABEL,
            "routing_contract": (
                f"{routing_contract.name}@sha256:{_sha(routing_contract)}"
            ),
        },
        "executor_trust": {
            "schema_version": "facetta-frozen-executor-trust.v1",
            "status": "enrolled",
            "key_id": "executor-test-v1",
            "public_key": f"executor.pub@sha256:{_sha(public_key)}",
        },
    })
    plan = build_provider_call_plan(
        manifest, config, workload, repository_root=root,
    )
    capture_dir = root / "capture"
    capture_dir.mkdir()
    attempts = []
    execution_items = [
        row for row in plan["items"]
        if row["resolved_inputs"].get("execution_ready") is True
    ]
    for index, planned in enumerate(execution_items, 1):
        candidate = capture_dir / f"candidate-{index}.png"
        Image.new("RGB", (4, 4), "gray").save(candidate)
        row = {
            "kind": planned["kind"],
            "evaluation_id": planned["evaluation_id"],
            "source_filename": planned["source_filename"],
            "source_sha256": planned["source_sha256"],
            "resolved_inputs_sha256": planned["resolved_inputs_sha256"],
            "attempt": 1,
            **expected_attempt_routing(planned, 1),
            "accepted": True,
            "attempt_outcome": "accepted",
            "provider_error_code": None,
            "qa_outcome": "pass",
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
        "schema_version": "facetta-frozen-capture.v2",
        "corpus_run_id": plan["corpus_run_id"],
        "manifest_sha256": plan["manifest_sha256"],
        "config_sha256": plan["config_sha256"],
        "workload_sha256": plan["workload_sha256"],
        "assignment_bundle_sha256": plan["assignment_bundle"]["bundle_sha256"],
        "not_applicable_assignments": not_applicable_assignment_rows(plan),
        "attempts": attempts,
        "persistence_evidence_ref": {
            "relative_path": persistence.name,
            "sha256": _sha(persistence),
        },
        "signature": None,
    }
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
        "private_key": private_key,
        "persistence": persistence,
        "key_id": "executor-test-v1",
    }


def _prepare(fixture: dict[str, Any]) -> dict[str, object]:
    return prepare_frozen_corpus_review_packet(
        fixture["manifest"],  # type: ignore[arg-type]
        fixture["config"],  # type: ignore[arg-type]
        fixture["workload"],  # type: ignore[arg-type]
        fixture["sources"],  # type: ignore[arg-type]
        fixture["capture"],  # type: ignore[arg-type]
        evidence_root=fixture["root"],  # type: ignore[arg-type]
        capture_public_key_path=fixture["public_key"],  # type: ignore[arg-type]
        capture_key_id=str(fixture["key_id"]),
        repository_root=fixture["root"],  # type: ignore[arg-type]
    )


def _prepare_blind_v2(fixture: dict[str, Any]) -> dict[str, object]:
    return prepare_blind_frozen_corpus_review_packet_v2(
        fixture["manifest"],  # type: ignore[arg-type]
        fixture["config"],  # type: ignore[arg-type]
        fixture["workload"],  # type: ignore[arg-type]
        fixture["sources"],  # type: ignore[arg-type]
        fixture["capture"],  # type: ignore[arg-type]
        evidence_root=fixture["root"],  # type: ignore[arg-type]
        capture_public_key_path=fixture["public_key"],  # type: ignore[arg-type]
        capture_key_id=str(fixture["key_id"]),
        review_seed="a" * 64,
        reviewer_role=GIA_VISUAL_FIDELITY_ROLE,
        repository_root=fixture["root"],  # type: ignore[arg-type]
    )


def test_packet_uses_only_workload_quality_assignments(tmp_path: Path):
    fixture = _fixture(tmp_path)
    packet = _prepare(fixture)

    assert packet["quality_scope"] == {
        "slice": "ring",
        "source_count": 1,
        "evaluation_sequence_count": 2,
        "executed_evaluation_sequence_count": 2,
        "not_applicable_evaluation_sequence_count": 0,
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


def test_reviewed_not_applicable_row_is_replayed_but_not_blind_reviewed(
    tmp_path: Path,
):
    fixture = _fixture(tmp_path, not_applicable_edit=True)
    packet = _prepare(fixture)
    blind = _prepare_blind_v2(fixture)

    assert packet["quality_scope"] == {
        "slice": "ring",
        "source_count": 1,
        "evaluation_sequence_count": 2,
        "executed_evaluation_sequence_count": 1,
        "not_applicable_evaluation_sequence_count": 1,
        "status": "pending_review",
    }
    assert len(packet["attempts"]) == 1
    assert len(packet["not_applicable_assignments"]) == 1
    assert packet["source_coverage"][0]["filename"] == "ring.png"
    assert packet["source_coverage"][0]["evaluation_ids"] == [
        "metal-color", "round-solitaire-yellow-4-narrow",
    ]
    assert len(packet["reviewer_review"]["decisions"]) == 1
    assert len(blind["items"]) == 1
    assert blind["items"][0]["operation_class"] == "render_conformance"

    capture_path: Path = fixture["capture"]
    capture = json.loads(capture_path.read_text())
    capture["not_applicable_assignments"][0]["reason"] = "tampered"
    capture["signature"] = None
    private_key: Ed25519PrivateKey = fixture["private_key"]
    capture["signature"] = {
        "algorithm": "Ed25519",
        "key_id": fixture["key_id"],
        "public_key_sha256": _sha(fixture["public_key"]),
        "value": base64.b64encode(
            private_key.sign(canonical_capture_payload(capture))
        ).decode("ascii"),
    }
    _json(capture_path, capture)
    with pytest.raises(
        ValueError,
        match="capture not-applicable assignments differ from the frozen plan",
    ):
        _prepare(fixture)


def test_blind_v2_projects_only_selected_artifacts_and_review_intent(tmp_path: Path):
    fixture = _fixture(tmp_path)
    packet = _prepare_blind_v2(fixture)

    assert packet["schema_version"] == BLIND_REVIEW_PACKET_SCHEMA
    assert packet["evidence_binding"] == {
        "manifest_sha256": _sha(fixture["manifest"]),  # type: ignore[arg-type]
        "config_sha256": _sha(fixture["config"]),  # type: ignore[arg-type]
        "workload_sha256": _sha(fixture["workload"]),  # type: ignore[arg-type]
        "capture_sha256": _sha(fixture["capture"]),  # type: ignore[arg-type]
    }
    assert validate_blind_review_packet(packet)["status"] == "pass"
    assert len(packet["items"]) == 2
    assert {item["operation_class"] for item in packet["items"]} == {
        "render_conformance", "quick_appearance",
    }
    metal = next(
        item for item in packet["items"]
        if item["operation_class"] == "quick_appearance"
    )
    assert metal["intent"] == {
        "intended_change": next(
            edit.instruction for edit in CANONICAL_RING_EDITS
            if edit.id == "metal-color"
        ),
        "target_region": next(
            edit.region for edit in CANONICAL_RING_EDITS
            if edit.id == "metal-color"
        ),
        "frozen_facts": list(next(
            edit.frozen_facts for edit in CANONICAL_RING_EDITS
            if edit.id == "metal-color"
        )),
    }
    assert metal["artifacts"]["source"]["sha256"] == _sha(
        fixture["sources"] / "ring.png",  # type: ignore[operator]
    )
    assert metal["artifacts"]["candidate"]["sha256"]
    assert metal["artifacts"]["mask"]["sha256"]
    serialized = json.dumps(packet, sort_keys=True).lower()
    for forbidden in (
        "accepted",
        "attempt",
        "hard_gate",
        "score",
        "severity",
        "change_applied",
        "provider",
        "model",
        "retry",
    ):
        assert forbidden not in serialized


def test_blind_v2_is_deterministic_for_the_same_capture_and_seed(tmp_path: Path):
    fixture = _fixture(tmp_path)

    assert _prepare_blind_v2(fixture) == _prepare_blind_v2(fixture)


def test_blind_v2_rejects_ambiguous_or_missing_machine_selection(tmp_path: Path):
    fixture = _fixture(tmp_path)
    capture_path = fixture["capture"]
    capture = json.loads(capture_path.read_text())  # type: ignore[union-attr]
    capture["attempts"][0]["accepted"] = False
    capture["attempts"][0]["attempt_outcome"] = "qa_failed"
    capture["attempts"][0]["qa_outcome"] = "fail"
    capture["signature"] = {
        "algorithm": "Ed25519",
        "key_id": fixture["key_id"],
        "public_key_sha256": _sha(fixture["public_key"]),  # type: ignore[arg-type]
        "value": base64.b64encode(
            fixture["private_key"].sign(canonical_capture_payload(capture))
        ).decode("ascii"),
    }
    _json(capture_path, capture)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="exactly one machine-selected candidate"):
        _prepare_blind_v2(fixture)


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
    assert packet["capture_provenance"]["corpus_run_id"] == "packet-fixture-run-v1"
    referenced_paths = {
        packet["capture_provenance"]["capture_artifact"],
        packet["capture_provenance"]["executor_public_key_artifact"],
        packet["persistence_evidence_binding"]["artifact"],
    }
    for attempt in packet["attempts"]:
        referenced_paths.update({
            attempt["source_image"], attempt["candidate_image"],
        })
        if attempt["kind"] == "edit":
            referenced_paths.add(attempt["mask_image"])
    assert all(not Path(path).is_absolute() for path in referenced_paths)
    indexed_paths = {
        row["path"] for row in packet["artifact_index"]["artifacts"]
    }
    assert referenced_paths <= indexed_paths


def test_packet_rejects_capture_outside_evidence_root(tmp_path: Path):
    fixture = _fixture(tmp_path)
    outside = tmp_path / "outside-capture.json"
    outside.write_bytes(fixture["capture"].read_bytes())  # type: ignore[union-attr]

    with pytest.raises(ValueError, match="capture artifact escapes the evidence root"):
        prepare_frozen_corpus_review_packet(
            fixture["manifest"],  # type: ignore[arg-type]
            fixture["config"],  # type: ignore[arg-type]
            fixture["workload"],  # type: ignore[arg-type]
            fixture["sources"],  # type: ignore[arg-type]
            outside,
            evidence_root=fixture["root"],  # type: ignore[arg-type]
            capture_public_key_path=fixture["public_key"],  # type: ignore[arg-type]
            capture_key_id=str(fixture["key_id"]),
            repository_root=fixture["root"],  # type: ignore[arg-type]
        )


def test_packet_rejects_executor_key_outside_evidence_root(tmp_path: Path):
    fixture = _fixture(tmp_path)
    outside_key = tmp_path / "outside-executor.pub"
    outside_key.write_bytes(fixture["public_key"].read_bytes())

    with pytest.raises(ValueError, match="executor public key escapes the evidence root"):
        prepare_frozen_corpus_review_packet(
            fixture["manifest"],
            fixture["config"],
            fixture["workload"],
            fixture["sources"],
            fixture["capture"],
            evidence_root=fixture["root"],
            capture_public_key_path=outside_key,
            capture_key_id=str(fixture["key_id"]),
            repository_root=fixture["root"],
        )


def test_review_packet_output_must_stay_beneath_evidence_root(tmp_path: Path):
    root = tmp_path / "evidence"
    root.mkdir()
    with pytest.raises(ValueError, match="review packet output escapes"):
        confined_output_path(
            root.resolve(),
            tmp_path / "outside-review.json",
            label="review packet output",
        )


def test_packet_rejects_source_symlink_escape(tmp_path: Path):
    fixture = _fixture(tmp_path)
    source = fixture["sources"] / "ring.png"  # type: ignore[operator]
    outside = tmp_path / "outside-ring.png"
    outside.write_bytes(source.read_bytes())
    source.unlink()
    source.symlink_to(outside)

    with pytest.raises(ValueError, match="quality source ring.png escapes the evidence root"):
        _prepare(fixture)


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
    key = fixture["private_key"]
    public_key = fixture["public_key"]
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

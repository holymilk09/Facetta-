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
    canonical_object_sha256,
    not_applicable_assignment_rows,
    validate_capture_envelope,
    validate_workload_definition,
)
from facetta.ring_evals import (
    CANONICAL_RING_EDITS,
    RING_GOLDEN_CASES,
    apply_canonical_ring_edit,
    build_ring_golden_spec,
)


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _executor_key(root: Path, config: Path) -> tuple[Ed25519PrivateKey, Path]:
    private_key = Ed25519PrivateKey.generate()
    public_key_path = root / "executor.pub"
    public_key_path.write_bytes(private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ))
    raw = json.loads(config.read_text())
    raw["executor_trust"] = {
        "schema_version": "facetta-frozen-executor-trust.v1",
        "status": "enrolled",
        "key_id": "executor-test-v1",
        "public_key": f"executor.pub@sha256:{_sha(public_key_path)}",
    }
    _write(config, raw)
    return private_key, public_key_path


def _binding(evaluation_id: str, kind: str) -> dict[str, object]:
    cases = {case.id: case for case in RING_GOLDEN_CASES}
    if kind == "render":
        spec = build_ring_golden_spec(cases[evaluation_id]).model_dump(mode="json")
        instruction = f"frozen founder corpus render: {evaluation_id}"
        region = None
        frozen = ["reviewed synthetic source geometry"]
        target = spec
    else:
        edit = next(item for item in CANONICAL_RING_EDITS if item.id == evaluation_id)
        source_model = build_ring_golden_spec(cases[edit.golden_case_id])
        target_model, issues = apply_canonical_ring_edit(source_model, edit)
        assert target_model is not None and not issues
        spec = source_model.model_dump(mode="json")
        target = target_model.model_dump(mode="json")
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
        "source_spec": spec,
        "target_spec": target,
        "instruction": instruction,
        "region_description": region,
        "frozen_facts": frozen,
    }


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
            "render_case_ids": ["round-solitaire-yellow-4-narrow"],
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
    assignment_bundle = root / "assignments.json"
    _write(assignment_bundle, {
        "schema_version": "facetta-frozen-assignment-bundle.v1",
        "workload_sha256": _sha(workload),
        "corpus_run_id": "fixture-corpus-run-v1",
        "assignments": [
            {
                "source_filename": "ring.png",
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
    _write(config, {
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
            "routing": "fixture-provider-free-routing.v1",
        },
    })
    return root, manifest, config, workload


def _mark_edit_not_applicable(root: Path, config: Path, *, reason: str) -> None:
    assignments = root / "assignments.json"
    raw = json.loads(assignments.read_text())
    edit = next(row for row in raw["assignments"] if row["kind"] == "edit")
    edit["binding"] = {
        "schema_version": "facetta-frozen-source-assignment.v1",
        "review_status": "approved",
        "applicability": "not_applicable",
        "not_applicable_reason": reason,
        "review_evidence_sha256": "4" * 64,
        "source_spec_evidence_sha256": "5" * 64,
        "component_map_sha256": "6" * 64,
        "region_evidence_sha256": "7" * 64,
    }
    _write(assignments, raw)
    config_raw = json.loads(config.read_text())
    config_raw["frozen_components"]["resolved_assignment_bundle"] = (
        f"assignments.json@sha256:{_sha(assignments)}"
    )
    _write(config, config_raw)


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
    assert first["logical_scope_maximum_attempt_count"] == 6
    assert first["corpus_run_id"] == "fixture-corpus-run-v1"
    assert {row["source_filename"] for row in first["items"]} == {"ring.png"}
    for row in first["items"]:
        assert row["resolved_inputs"]["schema_version"] == (
            "facetta-frozen-resolved-assignment.v1"
        )
        assert row["resolved_inputs_sha256"] == canonical_object_sha256(
            row["resolved_inputs"]
        )


def test_reviewed_not_applicable_rows_remain_signed_without_provider_calls(
    tmp_path: Path,
):
    root, manifest, config, workload = _fixture(tmp_path)
    _mark_edit_not_applicable(
        root, config, reason="source has no plated metal surface to recolor",
    )
    private_key, public_key_path = _executor_key(root, config)
    plan = build_provider_call_plan(
        manifest, config, workload, repository_root=root,
    )
    assert plan["provider_calls_executed"] == 0
    assert plan["planned_evaluation_sequence_count"] == 2
    assert plan["resolved_sequence_count"] == 2
    assert plan["execution_ready_sequence_count"] == 1
    assert plan["not_applicable_sequence_count"] == 1
    assert plan["maximum_provider_attempt_count"] == 3
    assert plan["logical_scope_maximum_attempt_count"] == 6
    assert plan["capture_status"] == "not_run"

    capture_dir = root / "capture-na"
    capture_dir.mkdir()
    candidate = capture_dir / "render.png"
    candidate.write_bytes(b"render")
    persistence = capture_dir / "persistence.json"
    persistence.write_text('{"verified":true}\n')
    planned = next(
        row for row in plan["items"]
        if row["resolved_inputs"]["execution_ready"] is True
    )
    capture = {
        "schema_version": "facetta-frozen-capture.v2",
        "corpus_run_id": plan["corpus_run_id"],
        "manifest_sha256": plan["manifest_sha256"],
        "config_sha256": plan["config_sha256"],
        "workload_sha256": plan["workload_sha256"],
        "assignment_bundle_sha256": plan["assignment_bundle"]["bundle_sha256"],
        "not_applicable_assignments": not_applicable_assignment_rows(plan),
        "attempts": [{
            "kind": planned["kind"],
            "evaluation_id": planned["evaluation_id"],
            "source_filename": planned["source_filename"],
            "source_sha256": planned["source_sha256"],
            "resolved_inputs_sha256": planned["resolved_inputs_sha256"],
            "attempt": 1,
            "accepted": True,
            "candidate_image": candidate.name,
            "candidate_image_sha256": _sha(candidate),
            "render_conformance_score": 95,
            "hard_gate_pass": True,
        }],
        "persistence_evidence_ref": {
            "relative_path": persistence.name,
            "sha256": _sha(persistence),
        },
        "signature": None,
    }

    def sign() -> None:
        capture["signature"] = {
            "algorithm": "Ed25519",
            "key_id": "executor-test-v1",
            "public_key_sha256": _sha(public_key_path),
            "value": base64.b64encode(
                private_key.sign(canonical_capture_payload(capture))
            ).decode("ascii"),
        }

    capture_path = capture_dir / "capture.json"
    sign()
    _write(capture_path, capture)
    valid = validate_capture_envelope(
        capture_path, manifest, config, workload,
        capture_public_key_path=public_key_path,
        capture_key_id="executor-test-v1",
        repository_root=root,
    )
    assert valid["status"] == "pass"
    assert valid["logical_evaluation_sequence_count"] == 2
    assert valid["captured_evaluation_sequence_count"] == 1
    assert valid["not_applicable_evaluation_sequence_count"] == 1

    capture["not_applicable_assignments"][0]["reason"] = "tampered reason"
    sign()
    _write(capture_path, capture)
    tampered = validate_capture_envelope(
        capture_path, manifest, config, workload,
        capture_public_key_path=public_key_path,
        capture_key_id="executor-test-v1",
        repository_root=root,
    )
    assert tampered["status"] == "fail"
    assert "capture not-applicable assignments differ from the frozen plan" in (
        tampered["errors"]
    )

    capture["not_applicable_assignments"] = not_applicable_assignment_rows(plan)
    reviewed_na = next(
        row for row in plan["items"]
        if row["resolved_inputs"]["resolution_status"] == "not_applicable"
    )
    edit_candidate = capture_dir / "edit.png"
    edit_mask = capture_dir / "mask.png"
    edit_candidate.write_bytes(b"edit")
    edit_mask.write_bytes(b"mask")
    capture["attempts"].append({
        "kind": reviewed_na["kind"],
        "evaluation_id": reviewed_na["evaluation_id"],
        "source_filename": reviewed_na["source_filename"],
        "source_sha256": reviewed_na["source_sha256"],
        "resolved_inputs_sha256": reviewed_na["resolved_inputs_sha256"],
        "attempt": 1,
        "accepted": True,
        "candidate_image": edit_candidate.name,
        "candidate_image_sha256": _sha(edit_candidate),
        "mask_image": edit_mask.name,
        "mask_image_sha256": _sha(edit_mask),
        "edit_fidelity_score": 95,
        "severity": "none",
        "change_applied": True,
    })
    sign()
    _write(capture_path, capture)
    attempted = validate_capture_envelope(
        capture_path, manifest, config, workload,
        capture_public_key_path=public_key_path,
        capture_key_id="executor-test-v1",
        repository_root=root,
    )
    assert attempted["status"] == "fail"
    assert any(
        "attempted a reviewed non-applicable assignment" in error
        for error in attempted["errors"]
    )


def test_malformed_not_applicable_assignment_blocks_without_provider_calls(
    tmp_path: Path,
):
    root, manifest, config, workload = _fixture(tmp_path)
    _mark_edit_not_applicable(root, config, reason="")
    plan = build_provider_call_plan(
        manifest, config, workload, repository_root=root,
    )
    assert plan["provider_calls_executed"] == 0
    assert plan["unresolved_sequence_count"] == 1
    assert plan["not_applicable_sequence_count"] == 0
    assert plan["capture_status"] == "blocked_unresolved_assignments"


def test_production_matrix_is_scope_only_until_reviewed_bindings_are_pinned():
    root = Path(__file__).resolve().parents[1]
    frozen = root / "docs" / "evals" / "frozen-founder-corpus-v1"
    plan = build_provider_call_plan(
        frozen / "manifest.json",
        frozen / "config.json",
        frozen / "workload.json",
        repository_root=root,
    )
    assert plan["planned_evaluation_sequence_count"] == 1_044
    assert plan["execution_ready_sequence_count"] == 0
    assert plan["maximum_provider_attempt_count"] == 0
    assert plan["logical_scope_maximum_attempt_count"] == 3_132
    assert plan["unresolved_sequence_count"] == 1_044
    assert plan["capture_status"] == "blocked_unresolved_assignments"
    assert plan["executor_trust"]["status"] == "not_enrolled"
    assert plan["assignment_bundle"]["status"] == "not_enrolled"
    assert plan["corpus_gate_ready"] is False
    assert all(item["resolved_inputs"]["execution"] is None for item in plan["items"])


def test_provider_free_fake_executor_covers_all_1044_synthetic_assignments(
    tmp_path: Path,
):
    repository = Path(__file__).resolve().parents[1]
    frozen = repository / "docs" / "evals" / "frozen-founder-corpus-v1"
    root = tmp_path / "synthetic-repo"
    manifest = root / "manifest.json"
    workload = root / "workload.json"
    config = root / "config.json"
    _write(manifest, json.loads((frozen / "manifest.json").read_text()))
    workload_raw = json.loads((frozen / "workload.json").read_text())
    workload_raw["manifest_sha256"] = _sha(manifest)
    _write(workload, workload_raw)
    evaluation_set = workload_raw["evaluation_sets"][
        workload_raw["ring_quality_evaluation_set_id"]
    ]
    quality_sources = [
        row for row in workload_raw["sources"] if row.get("quality") is not None
    ]
    assignments = [
        {
            "source_filename": source["filename"],
            "kind": evaluation["kind"],
            "evaluation_id": evaluation["evaluation_id"],
            "binding": _binding(evaluation["evaluation_id"], evaluation["kind"]),
        }
        for source in quality_sources
        for evaluation in evaluation_set
    ]
    assignment_bundle = root / "assignments.json"
    _write(assignment_bundle, {
        "schema_version": "facetta-frozen-assignment-bundle.v1",
        "workload_sha256": _sha(workload),
        "corpus_run_id": "synthetic-complete-1044-v1",
        "assignments": assignments,
    })
    _write(config, {
        "config_id": workload_raw["config_id"],
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
            "ring_contract": "synthetic-ring-contract@sha256:" + "1" * 64,
            "prompt_bundle": "synthetic-prompt-bundle@sha256:" + "2" * 64,
            "evaluator_bundle": "synthetic-evaluator-bundle@sha256:" + "3" * 64,
            "routing": "provider-free-fake.v1",
        },
    })
    plan = build_provider_call_plan(
        manifest, config, workload, repository_root=root,
    )

    class ProviderFreeFakeExecutor:
        provider_calls_executed = 0

        def execute(self, item: dict[str, object]) -> dict[str, object]:
            resolved = item["resolved_inputs"]
            assert isinstance(resolved, dict)
            assert resolved["execution_ready"] is True
            assert isinstance(resolved["execution"], dict)
            assert isinstance(resolved["scoring"], dict)
            assert item["resolved_inputs_sha256"] == canonical_object_sha256(resolved)
            return {
                "assignment_sha256": item["resolved_inputs_sha256"],
                "terminal_status": "contract_validated_without_provider",
            }

    executor = ProviderFreeFakeExecutor()
    outcomes = [executor.execute(item) for item in plan["items"]]
    assert len(outcomes) == 1_044
    assert len({row["assignment_sha256"] for row in outcomes}) == 1_044
    assert plan["execution_ready_sequence_count"] == 1_044
    assert plan["unresolved_sequence_count"] == 0
    assert executor.provider_calls_executed == 0
    assert plan["corpus_gate_ready"] is False


def test_signed_capture_binds_plan_artifacts_and_persistence(tmp_path: Path):
    root, manifest, config, workload = _fixture(tmp_path)
    private_key, public_key_path = _executor_key(root, config)
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
            "resolved_inputs_sha256": planned["resolved_inputs_sha256"],
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
        "schema_version": "facetta-frozen-capture.v2",
        "corpus_run_id": plan["corpus_run_id"],
        "manifest_sha256": plan["manifest_sha256"],
        "config_sha256": plan["config_sha256"],
        "workload_sha256": plan["workload_sha256"],
        "assignment_bundle_sha256": plan["assignment_bundle"]["bundle_sha256"],
        "not_applicable_assignments": not_applicable_assignment_rows(plan),
        "attempts": attempts,
        "persistence_evidence_ref": {
            "relative_path": "persistence.json",
            "sha256": _sha(capture_dir / "persistence.json"),
        },
        "signature": None,
    }
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
    assert result["corpus_run_id"] == "fixture-corpus-run-v1"
    assert result["captured_evaluation_sequence_count"] == 2
    assert result["corpus_gate_ready"] is False

    capture["corpus_run_id"] = "operator-invented-run"
    capture["signature"] = {
        "algorithm": "Ed25519",
        "key_id": "executor-test-v1",
        "public_key_sha256": _sha(public_key_path),
        "value": base64.b64encode(
            private_key.sign(canonical_capture_payload(capture))
        ).decode("ascii"),
    }
    _write(capture_path, capture)
    wrong_run = validate_capture_envelope(
        capture_path,
        manifest,
        config,
        workload,
        capture_public_key_path=public_key_path,
        capture_key_id="executor-test-v1",
        repository_root=root,
    )
    assert wrong_run["status"] == "fail"
    assert "capture corpus_run_id differs from the preassigned plan run" in (
        wrong_run["errors"]
    )

    untrusted_key = Ed25519PrivateKey.generate()
    untrusted_public_key = root / "operator-generated.pub"
    untrusted_public_key.write_bytes(untrusted_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ))
    capture["corpus_run_id"] = plan["corpus_run_id"]
    capture["signature"] = {
        "algorithm": "Ed25519",
        "key_id": "operator-generated-v1",
        "public_key_sha256": _sha(untrusted_public_key),
        "value": base64.b64encode(
            untrusted_key.sign(canonical_capture_payload(capture))
        ).decode("ascii"),
    }
    _write(capture_path, capture)
    rejected = validate_capture_envelope(
        capture_path,
        manifest,
        config,
        workload,
        capture_public_key_path=untrusted_public_key,
        capture_key_id="operator-generated-v1",
        repository_root=root,
    )
    assert rejected["status"] == "fail"
    assert any("config-enrolled executor" in error for error in rejected["errors"])


def test_signed_capture_rejects_artifact_tampering(tmp_path: Path):
    root, manifest, config, workload = _fixture(tmp_path)
    key, public_key_path = _executor_key(root, config)
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
            "resolved_inputs_sha256": planned["resolved_inputs_sha256"],
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
        "schema_version": "facetta-frozen-capture.v2",
        "corpus_run_id": plan["corpus_run_id"],
        "manifest_sha256": plan["manifest_sha256"],
        "config_sha256": plan["config_sha256"],
        "workload_sha256": plan["workload_sha256"],
        "assignment_bundle_sha256": plan["assignment_bundle"]["bundle_sha256"],
        "not_applicable_assignments": not_applicable_assignment_rows(plan),
        "attempts": attempts,
        "persistence_evidence_ref": {
            "relative_path": persistence.name, "sha256": _sha(persistence),
        },
        "signature": None,
    }
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

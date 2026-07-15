from __future__ import annotations

import hashlib
import json
import base64
from pathlib import Path
from typing import Any

from PIL import Image
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from facetta.blind_jewelry_review import (
    GIA_VISUAL_FIDELITY_ROLE,
    blind_review_packet_sha256,
    build_blind_review_packet,
    canonical_review_ledger_payload,
)
from facetta.frozen_assignment_contract import (
    SIGNED_ASSIGNMENT_BUNDLE_SCHEMA,
    canonical_assignment_bundle_payload,
)
from facetta.frozen_corpus_gate import (
    REPLAY_SCHEMA,
    _replay_quality,
    canonical_evidence_payload,
    compile_frozen_corpus_gate,
    release_authority_key_separation,
)
from facetta.frozen_capture_workload import (
    CAPTURE_SCHEMA,
    FROZEN_ROUTING_LABEL,
    build_provider_call_plan,
    canonical_capture_payload,
    canonical_object_sha256,
    expected_attempt_routing,
    not_applicable_assignment_rows,
)
from facetta.frozen_corpus_packet import prepare_frozen_corpus_review_packet
from facetta.frozen_evidence_paths import build_artifact_index
from facetta.frozen_evaluator_report import (
    EVALUATOR_REPORT_SCHEMA,
    validate_and_replay_evaluator_report,
)
from facetta.frozen_persistence_attestation import (
    canonical_attestation_payload,
    result_set_sha256,
)
from facetta.ring_evals import (
    CANONICAL_RING_EDITS,
    RING_GOLDEN_CASES,
    apply_canonical_ring_edit,
    build_ring_golden_spec,
)
from facetta.spec import Spec


def _json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _evaluator_report(
    planned: dict[str, Any],
    *,
    attempt: int,
    candidate_sha256: str,
    mask_sha256: str | None,
    passed: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    resolved = planned["resolved_inputs"]
    frozen = resolved["frozen_component_bindings"]
    evaluator_hash = frozen["evaluator_bundle"].rsplit("@sha256:", 1)[1]
    kind = planned["kind"]
    evaluation_contract = resolved["evaluation_contract"]
    spec = (
        Spec.model_validate(evaluation_contract["canonical_target_spec"])
        if kind == "render"
        else None
    )
    report = {
        "schema_version": EVALUATOR_REPORT_SCHEMA,
        "bindings": {
            "corpus_run_id": planned["corpus_run_id"],
            "resolved_inputs_sha256": planned["resolved_inputs_sha256"],
            "kind": kind,
            "evaluation_id": planned["evaluation_id"],
            "operation_class": planned["operation_class"],
            "source_filename": planned["source_filename"],
            "attempt": attempt,
            "source_image_sha256": planned["source_sha256"],
            "candidate_image_sha256": candidate_sha256,
            "mask_image_sha256": mask_sha256 if kind == "edit" else None,
            "evaluator_contract_sha256": evaluator_hash,
        },
        "observer": {
            "provider": "fixture",
            "model": "fixture-vision",
            "model_revision": "1",
            "model_revision_status": "pinned",
            "request_id": f"{kind}:{planned['evaluation_id']}:{attempt}",
        },
        "quality_report": {
            "verdict": "pass" if passed else "fail",
            "checks": [{
                "code": "frozen_visual_gate",
                "passed": passed,
                "severity": "hard",
                "message": "retained visual gate",
                "evidence": {},
            }],
            "score": 100.0 if passed else 0.0,
            "notes": [],
        },
        "metric": resolved["scoring"]["metric"],
        "observation": (
            {
                "stones": [{
                    "qty": 1,
                    "type": spec.stone.species,
                    "size_mm": (
                        f"{spec.stone.dimensions_mm.length} x "
                        f"{spec.stone.dimensions_mm.width}"
                    ),
                    "carat_each": spec.stone.carat,
                    "confidence": 1.0,
                }],
                "metal": spec.metal.material.replace("_", " "),
                "measurements": [],
                "scaled": False,
                "scale_anchor": None,
            }
            if kind == "render"
            else {
                "change_applied": passed,
                "change_note": "requested edit applied" if passed else "not applied",
                "unintended_changes": [] if passed else ["design drift"],
                "severity": "none" if passed else "major",
            }
        ),
    }
    identity = {
        "attempt": attempt,
        "source_image_sha256": planned["source_sha256"],
        "candidate_image_sha256": candidate_sha256,
        "mask_image_sha256": mask_sha256 if kind == "edit" else None,
    }
    return report, validate_and_replay_evaluator_report(
        report, planned, identity,
    )


_ASSIGNMENT_REVIEWER_KEY_ID = "assignment-reviewer-test-v1"
_ASSIGNMENT_REVIEWER_PROFILE_SHA256 = "a" * 64


def _assignment_reviewer_private_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(bytes(range(32)))


def _install_assignment_reviewer(root: Path) -> dict[str, str]:
    public_key = root / "assignment-reviewer-v1.pub"
    public_key.write_bytes(
        _assignment_reviewer_private_key().public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    )
    return {
        "key_id": _ASSIGNMENT_REVIEWER_KEY_ID,
        "path": public_key.name,
        "sha256": _sha(public_key),
        "reviewer_profile_sha256": _ASSIGNMENT_REVIEWER_PROFILE_SHA256,
    }


def _signed_assignment_bundle(
    workload: Path,
    assignments: list[dict[str, object]],
) -> dict[str, object]:
    bundle: dict[str, object] = {
        "schema_version": SIGNED_ASSIGNMENT_BUNDLE_SCHEMA,
        "workload_sha256": _sha(workload),
        "corpus_run_id": "corpus-run-test-1",
        "reviewer_key_id": _ASSIGNMENT_REVIEWER_KEY_ID,
        "reviewer_profile_sha256": _ASSIGNMENT_REVIEWER_PROFILE_SHA256,
        "reviewed_template_sha256": "9" * 64,
        "release_authority_decision": None,
        "assignments": assignments,
        "signature": None,
    }
    bundle["signature"] = {
        "algorithm": "Ed25519",
        "key_id": _ASSIGNMENT_REVIEWER_KEY_ID,
        "value": base64.b64encode(
            _assignment_reviewer_private_key().sign(
                canonical_assignment_bundle_payload(bundle)
            )
        ).decode("ascii"),
    }
    return bundle


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


def _not_applicable_binding(source_sha256: str) -> dict[str, object]:
    edit = next(
        candidate for candidate in CANONICAL_RING_EDITS
        if candidate.id == "impossible-band-width"
    )
    case = next(
        candidate for candidate in RING_GOLDEN_CASES
        if candidate.id == edit.golden_case_id
    )
    source_spec = build_ring_golden_spec(case)
    target_spec, issues = apply_canonical_ring_edit(source_spec, edit)
    assert target_spec is None and issues
    return {
        "schema_version": "facetta-frozen-source-assignment.v1",
        "review_status": "approved",
        "applicability": "not_applicable",
        "not_applicable_reason": (
            "canonical_delta_inapplicable/canonical-edit-apply-failed.v1"
        ),
        "review_evidence_sha256": "4" * 64,
        "source_spec_evidence_sha256": "5" * 64,
        "component_map_sha256": "6" * 64,
        "region_evidence_sha256": "7" * 64,
        "source_sha256": source_sha256,
        "source_spec": source_spec.model_dump(mode="json"),
        "canonical_edit_issues": issues,
    }


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
        "capture_relative_path": persistence_path.relative_to(
            paths["capture_artifact"].parent
        ).as_posix(),
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
        artifact_rows.append((
            row["source_image"], row["source_image_sha256"], f"source:{identity}",
        ))
        if row.get("candidate_image") is not None:
            artifact_rows.append((
                row["candidate_image"],
                row["candidate_image_sha256"],
                f"candidate:{identity}",
            ))
        if row["kind"] == "edit" and row.get("mask_image") is not None:
            artifact_rows.append((
                row["mask_image"], row["mask_image_sha256"], f"mask:{identity}",
            ))
        if row.get("evaluator_report") is not None:
            artifact_rows.append((
                row["evaluator_report"],
                row["evaluator_report_sha256"],
                f"evaluator-report:{identity}",
            ))
    evidence["artifact_index"] = build_artifact_index(artifact_rows)
    _sign(paths, evidence)
    _json(paths["evidence"], evidence)


def _write_review_ledger(paths: dict[str, Any], ledger: dict[str, Any]) -> None:
    ledger.pop("signature", None)
    ledger["signature"] = {
        "algorithm": "Ed25519",
        "key_id": "test-reviewer-v1",
        "value": base64.b64encode(paths["private_key"].sign(
            canonical_review_ledger_payload(ledger)
        )).decode("ascii"),
    }
    _json(paths["review_ledger"], ledger)


def _reject_blind_review_item(
    paths: dict[str, Any], *, kind: str | None = None,
    operation_class: str | None = None,
) -> None:
    packet = json.loads(paths["review_packet"].read_text())
    ledger = json.loads(paths["review_ledger"].read_text())
    item = next(
        row for row in packet["items"]
        if (kind is None or row["kind"] == kind)
        and (operation_class is None or row["operation_class"] == operation_class)
    )
    decision = next(
        row for row in ledger["decisions"] if row["item_id"] == item["item_id"]
    )
    decision["criteria"][0] = {
        **decision["criteria"][0],
        "rating": "fail",
        "rationale": "Visible fidelity does not meet the declared criterion.",
    }
    _write_review_ledger(paths, ledger)


def _fixture(
    tmp_path: Path, *, not_applicable_edit: bool = False,
) -> dict[str, Any]:
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    first = source_dir / "image-1.png"
    second = source_dir / "image-2.png"
    _image(first, "white")
    _image(second, "gray")
    quick_edit_ids = ["metal-color"]
    structural_edit_ids = [
        "band-width",
        *(["impossible-band-width"] if not_applicable_edit else []),
    ]
    evaluation_keys = [
        ("render", "round-solitaire-yellow-4-narrow"),
        *(("edit", evaluation_id) for evaluation_id in quick_edit_ids),
        *(("edit", evaluation_id) for evaluation_id in structural_edit_ids),
    ]
    evaluation_rows = [
        {
            "kind": kind,
            "evaluation_id": evaluation_id,
            "operation_class": (
                "render_conformance" if kind == "render"
                else "quick_appearance" if evaluation_id in quick_edit_ids
                else "structural"
            ),
        }
        for kind, evaluation_id in evaluation_keys
    ]
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
            "render_case_ids": ["round-solitaire-yellow-4-narrow"],
            "operation_ids": [*quick_edit_ids, *structural_edit_ids],
            "operation_classes": {
                "quick_appearance": quick_edit_ids,
                "structural": structural_edit_ids,
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
            "ring-full-matrix-v1": evaluation_rows,
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
    assignment_bundle = tmp_path / "assignments.json"
    _json(assignment_bundle, _signed_assignment_bundle(
        workload,
        assignments=[
            {
                "source_filename": first.name,
                "kind": kind,
                "evaluation_id": evaluation_id,
                "binding": (
                    _not_applicable_binding(_sha(first))
                    if (
                        not_applicable_edit
                        and evaluation_id == "impossible-band-width"
                    )
                    else _binding(evaluation_id, kind)
                ),
            }
            for kind, evaluation_id in evaluation_keys
        ],
    ))
    config = tmp_path / "config.json"
    components = tmp_path / "components"
    components.mkdir()
    component_files: dict[str, Path] = {}
    for name in (
        "ring_contract", "prompt_bundle", "evaluator_bundle", "live_runner",
        "replay_verifier", "replay_runner", "release_verifier",
        "packet_builder", "packet_runner", "capture_producer",
        "capture_producer_cli",
        "blind_review_contract", "release_authority_enrollment",
        "release_authority_bundle",
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
    executor_private_key = Ed25519PrivateKey.generate()
    executor_key = tmp_path / "executor-v1.pub"
    executor_key.write_bytes(executor_private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ))
    routing_contract = _install_routing_contract(tmp_path)
    _json(config, {
        "schema_version": "facetta-frozen-gate-config.v1",
        "config_id": "test-config",
        "corpus_id": "test-corpus",
        "manifest_sha256": _sha(manifest),
        "frozen_components": {
            name: f"components/{path.name}@sha256:{_sha(path)}"
            for name, path in component_files.items()
        } | {
            "routing": FROZEN_ROUTING_LABEL,
            "routing_contract": (
                f"{routing_contract.name}@sha256:{_sha(routing_contract)}"
            ),
            "capture_workload": f"workload.json@sha256:{_sha(workload)}",
            "resolved_assignment_bundle": (
                f"assignments.json@sha256:{_sha(assignment_bundle)}"
            ),
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
            "reviewer_profile_sha256": "b" * 64,
        },
        "assignment_reviewer_public_key": _install_assignment_reviewer(tmp_path),
        "canonical_api_runner_public_key": {
            "key_id": "canonical-api-runner-v1",
            "path": runner_key.name,
            "sha256": _sha(runner_key),
        },
        "executor_trust": {
            "schema_version": "facetta-frozen-executor-trust.v1",
            "status": "enrolled",
            "key_id": "executor-test-v1",
            "public_key": f"{executor_key.name}@sha256:{_sha(executor_key)}",
        },
    })
    plan = build_provider_call_plan(
        manifest, config, workload, repository_root=tmp_path,
    )
    capture_dir = tmp_path / "capture"
    capture_dir.mkdir()
    captured_sources = capture_dir / "sources"
    captured_sources.mkdir()
    captured_source = captured_sources / first.name
    captured_source.write_bytes(first.read_bytes())
    attempts: list[dict[str, Any]] = []
    render_candidate: Path | None = None
    edit_candidate: Path | None = None
    mask: Path | None = None
    execution_items = [
        row for row in plan["items"]
        if row["resolved_inputs"].get("execution_ready") is True
    ]
    for index, planned in enumerate(execution_items, 1):
        candidate = capture_dir / f"candidate-{index}.png"
        _image(candidate, "white")
        selected_pixel = ((index - 1) % 4, 0)
        if planned["kind"] == "edit":
            candidate_image = Image.open(candidate).convert("RGB")
            candidate_image.putpixel(
                selected_pixel, (255 - index, 255 - index, 255 - index),
            )
            candidate_image.save(candidate)
        row: dict[str, Any] = {
            "kind": planned["kind"],
            "evaluation_id": planned["evaluation_id"],
            "operation_class": planned["operation_class"],
            "source_filename": planned["source_filename"],
            "source_sha256": planned["source_sha256"],
            "source_image": captured_source.relative_to(capture_dir).as_posix(),
            "source_image_sha256": planned["source_sha256"],
            "resolved_inputs_sha256": planned["resolved_inputs_sha256"],
            "attempt": 1,
            **expected_attempt_routing(planned, 1),
            "accepted": True,
            "attempt_outcome": "accepted",
            "provider_error_code": None,
            "qa_outcome": "pass",
            "candidate_image": candidate.name,
            "candidate_image_sha256": _sha(candidate),
            "mask_image": None,
            "mask_image_sha256": None,
        }
        if planned["kind"] == "render":
            render_candidate = candidate
        else:
            edit_mask_path = capture_dir / f"mask-{index}.png"
            edit_mask = Image.new("L", (4, 4), 0)
            edit_mask.putpixel(selected_pixel, 255)
            edit_mask.save(edit_mask_path)
            row.update(
                mask_image=edit_mask_path.name,
                mask_image_sha256=_sha(edit_mask_path),
            )
            if edit_candidate is None:
                edit_candidate = candidate
                mask = edit_mask_path
        report, derived = _evaluator_report(
            planned,
            attempt=1,
            candidate_sha256=row["candidate_image_sha256"],
            mask_sha256=row["mask_image_sha256"],
        )
        report_path = capture_dir / f"evaluator-report-{index}.json"
        _json(report_path, report)
        row.update({
            "evaluator_report": report_path.name,
            "evaluator_report_sha256": _sha(report_path),
        })
        projection_fields = (
            (
                "accepted", "attempt_outcome", "provider_error_code",
                "qa_outcome", "render_conformance_score", "hard_gate_pass",
            )
            if planned["kind"] == "render"
            else (
                "accepted", "attempt_outcome", "provider_error_code",
                "qa_outcome", "edit_fidelity_score", "severity",
                "change_applied",
            )
        )
        row.update({field: derived[field] for field in projection_fields})
        attempts.append(row)
    assert render_candidate is not None
    assert edit_candidate is not None
    assert mask is not None
    persistence_artifact = capture_dir / "persistence.json"
    selected_result_set = [
        {
            "kind": row["kind"],
            "evaluation_id": row["evaluation_id"],
            "source_filename": row["source_filename"],
            "selected_attempt": row["attempt"],
            "candidate_image_sha256": row["candidate_image_sha256"],
        }
        for row in attempts
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
    _json(persistence_artifact, attestation)
    capture_value: dict[str, Any] = {
        "schema_version": CAPTURE_SCHEMA,
        "corpus_run_id": plan["corpus_run_id"],
        "manifest_sha256": plan["manifest_sha256"],
        "config_sha256": plan["config_sha256"],
        "workload_sha256": plan["workload_sha256"],
        "assignment_bundle_sha256": plan["assignment_bundle"]["bundle_sha256"],
        "not_applicable_assignments": not_applicable_assignment_rows(plan),
        "provider_calls_executed": len(execution_items),
        "attempts": attempts,
        "persistence_evidence_ref": {
            "relative_path": persistence_artifact.name,
            "sha256": _sha(persistence_artifact),
        },
    }
    capture_value["signature"] = {
        "algorithm": "Ed25519",
        "key_id": "executor-test-v1",
        "public_key_sha256": _sha(executor_key),
        "value": base64.b64encode(executor_private_key.sign(
            canonical_capture_payload(capture_value)
        )).decode("ascii"),
    }
    capture_artifact = capture_dir / "capture.json"
    _json(capture_artifact, capture_value)
    evidence_value = prepare_frozen_corpus_review_packet(
        manifest,
        config,
        workload,
        source_dir,
        capture_artifact,
        evidence_root=tmp_path,
        capture_public_key_path=executor_key,
        capture_key_id="executor-test-v1",
        repository_root=tmp_path,
    )
    evidence_value["source_coverage"][0]["quality_status"] = "pass"
    evidence_value["quality_scope"]["status"] = "reviewed"
    evidence_value["reviewer_review"] = {
        "completed": True,
        "reviewer": "test reviewer",
        "qualification": "GIA-trained",
        "false_positives": 0,
        "false_negatives": 0,
        "decisions": [
            {
                "kind": row["kind"],
                "evaluation_id": row["evaluation_id"],
                "source_filename": row["source_filename"],
                "accepted": True,
            }
            for row in evidence_value["attempts"]
            if row["accepted"] is True
        ],
    }
    evidence = tmp_path / "evidence.json"
    paths: dict[str, Any] = {
        "root": tmp_path,
        "source_dir": source_dir, "manifest": manifest, "config": config,
        "workload": workload,
        "evidence": evidence, "first": first, "second": second,
        "prompt_bundle": component_files["prompt_bundle"],
        "capture_producer": component_files["capture_producer"],
        "release_authority_bundle": component_files["release_authority_bundle"],
        "private_key": private_key, "reviewer_key": reviewer_key,
        "runner_private_key": runner_private_key, "runner_key": runner_key,
        "executor_private_key": executor_private_key, "executor_key": executor_key,
        "render_candidate": render_candidate, "edit_candidate": edit_candidate,
        "mask": mask,
        "capture_artifact": capture_artifact,
        "persistence_artifact": persistence_artifact,
        "plan": plan,
    }
    _write_signed(paths, evidence_value)
    selected_items = []
    for row in evidence_value["attempts"]:
        kind = str(row["kind"])
        selected_items.append({
            "kind": kind,
            "operation_class": row["operation_class"],
            "intent": {
                "intended_change": f"Review {row['evaluation_id']} visual fidelity",
                "target_region": None if kind == "render" else "declared edit region",
                "frozen_facts": ["design identity", "unrelated geometry"],
            },
            "source": {
                "path": row["source_image"],
                "sha256": row["source_image_sha256"],
            },
            "candidate": {
                "path": row["candidate_image"],
                "sha256": row["candidate_image_sha256"],
            },
            "mask": (
                {
                    "path": row["mask_image"],
                    "sha256": row["mask_image_sha256"],
                }
                if kind == "edit" else None
            ),
        })
    review_packet_value = build_blind_review_packet(
        corpus_run_id="corpus-run-test-1",
        manifest_sha256=_sha(manifest),
        config_sha256=_sha(config),
        workload_sha256=_sha(workload),
        capture_sha256=_sha(capture_artifact),
        reviewer_role=GIA_VISUAL_FIDELITY_ROLE,
        review_seed="a" * 64,
        selected_items=selected_items,
    )
    review_packet = tmp_path / "gia-blind-review-packet.json"
    _json(review_packet, review_packet_value)
    review_ledger = tmp_path / "gia-blind-review-ledger.json"
    review_ledger_value = {
        "schema_version": "facetta-blind-jewelry-review-ledger.v2",
        "blind_packet_sha256": blind_review_packet_sha256(review_packet_value),
        "reviewer_id": "opaque-gia-reviewer-test",
        "reviewer_role": GIA_VISUAL_FIDELITY_ROLE,
        "reviewer_profile_sha256": "b" * 64,
        "review_timezone": "UTC",
        "reviewed_at": "2026-07-13T00:00:00+00:00",
        "decisions": [
            {
                "item_id": item["item_id"],
                "selected_source_sha256": item["artifacts"]["source"]["sha256"],
                "selected_candidate_sha256": item["artifacts"]["candidate"]["sha256"],
                "selected_mask_sha256": (
                    item["artifacts"]["mask"]["sha256"]
                    if item["artifacts"]["mask"] is not None else None
                ),
                "criteria": [
                    {
                        "criterion_id": criterion["criterion_id"],
                        "rating": "pass",
                        "rationale": "",
                    }
                    for criterion in item["criteria"]
                ],
            }
            for item in review_packet_value["items"]
        ],
    }
    paths["review_packet"] = review_packet
    paths["review_ledger"] = review_ledger
    _write_review_ledger(paths, review_ledger_value)
    return paths


def _run(
    paths: dict[str, Any], *, evidence: bool = True, review: bool = True,
) -> dict:
    return compile_frozen_corpus_gate(
        paths["manifest"], paths["config"], paths["source_dir"],
        paths["evidence"] if evidence else None,
        repository_root=paths["root"],
        workload_path=paths["workload"],
        evidence_root=paths["root"],
        review_packet_path=paths["review_packet"] if review else None,
        review_ledger_path=paths["review_ledger"] if review else None,
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
        "schema_version": REPLAY_SCHEMA,
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


def test_complete_offline_replay_retains_reviewed_not_applicable_assignment(
    tmp_path: Path,
):
    paths = _fixture(tmp_path, not_applicable_edit=True)

    result = _run(paths)

    assert result["corpus_gate_ready"] is True
    quality = result["quality"]
    assert quality["expected_evaluation_count"] == 4
    assert quality["execution_ready_evaluation_count"] == 3
    assert quality["not_applicable_evaluation_count"] == 1
    assert quality["completed_evaluation_count"] == 4
    assert quality["blind_review"]["accepted_count"] == 3
    assert quality["persistence_attestation"]["bindings"]["result_count"] == 3
    actual = quality["not_applicable_assignments"]
    assert len(actual) == 1
    assert set(actual[0]) == {
        "kind",
        "evaluation_id",
        "operation_class",
        "source_filename",
        "source_sha256",
        "resolved_inputs_sha256",
        "reason",
        "review_evidence_sha256",
    }
    expected = [{
        "kind": "edit",
        "evaluation_id": "impossible-band-width",
        "operation_class": "structural",
        "source_filename": "image-1.png",
        "source_sha256": _sha(paths["first"]),
        "resolved_inputs_sha256": next(
            row["resolved_inputs_sha256"]
            for row in paths["plan"]["items"]
            if row["resolved_inputs"]["resolution_status"] == "not_applicable"
        ),
        "reason": (
            "canonical_delta_inapplicable/canonical-edit-apply-failed.v1"
        ),
        "review_evidence_sha256": "4" * 64,
    }]
    assert actual == expected
    planned_not_applicable = next(
        row for row in paths["plan"]["items"]
        if row["resolved_inputs"]["resolution_status"] == "not_applicable"
    )
    assert actual[0]["resolved_inputs_sha256"] == canonical_object_sha256(
        planned_not_applicable["resolved_inputs"]
    )


def test_release_replay_rejects_xai_adapter_key_as_provider_model(
    tmp_path: Path,
):
    paths = _fixture(tmp_path)
    config = json.loads(paths["config"].read_text())
    contract_pin = config["frozen_components"]["routing_contract"]
    _, contract_sha256 = contract_pin.rsplit("@sha256:", 1)
    entry = json.loads((tmp_path / "routing-contract.v1.json").read_text())[
        "route_entries"
    ][0]
    items = []
    evidence = json.loads(paths["evidence"].read_text())
    for index, captured in enumerate(evidence["attempts"], 1):
        resolved_sha256 = str(index) * 64
        planned = {
            "kind": captured["kind"],
            "evaluation_id": captured["evaluation_id"],
            "operation_class": captured["operation_class"],
            "source_filename": captured["source_filename"],
            "source_sha256": captured["source_sha256"],
            "resolved_inputs_sha256": resolved_sha256,
            "resolved_inputs": {
                "execution_ready": True,
                "execution": {
                    "routing": {
                        "attempts": [{
                            "attempt": 1,
                            "routing_contract_sha256": contract_sha256,
                            "routing_label": FROZEN_ROUTING_LABEL,
                            "route_role": entry["role"],
                            "route": entry["route"],
                            "adapter_key": entry["adapter_key"],
                            "provider": entry["provider"],
                            "model": entry["model"],
                            "model_revision": entry["model_revision"],
                            "model_revision_status": entry[
                                "model_revision_status"
                            ],
                            "endpoint": entry["endpoint"],
                            "provider_operation": entry["provider_operation"],
                            "allowed_fallback_reasons": [],
                        }],
                    },
                },
            },
        }
        captured["resolved_inputs_sha256"] = resolved_sha256
        captured.update(expected_attempt_routing(planned, 1))
        items.append(planned)
    assignment_plan = {"items": items}
    evidence["attempts"][0]["model"] = "grok_direct"
    _write_signed(paths, evidence)

    result = _replay_quality(
        json.loads(paths["evidence"].read_text()),
        paths["evidence"],
        paths["manifest"],
        paths["config"],
        paths["workload"],
        paths["source_dir"],
        json.loads(paths["manifest"].read_text()),
        config,
        json.loads(paths["workload"].read_text()),
        _sha(paths["manifest"]),
        _sha(paths["config"]),
        _sha(paths["workload"]),
        paths["root"],
        paths["root"],
        json.loads(paths["review_packet"].read_text()),
        json.loads(paths["review_ledger"].read_text()),
        assignment_plan,
    )

    assert result["status"] == "fail"
    assert any(
        "route/provider/model differs from frozen plan" in error
        for error in result["errors"]
    )


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


def test_pinned_release_authority_contract_drift_fails_definition(
    tmp_path: Path,
):
    paths = _fixture(tmp_path)
    paths["release_authority_bundle"].write_text(
        "# changed release-authority contract\n"
    )

    result = _run(paths, evidence=False)

    assert result["definition"]["status"] == "fail"
    assert any(
        "release_authority_bundle implementation drifted" in error
        for error in result["definition"]["errors"]
    )


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


def test_configured_component_mapper_requires_a_distinct_valid_ed25519_key(
    tmp_path: Path,
):
    paths = _fixture(tmp_path)
    config = json.loads(paths["config"].read_text())
    invalid_key = tmp_path / "component-mapper.pub"
    invalid_key.write_bytes(b"not-an-ed25519-public-key")
    config["component_mapper_public_key"] = {
        "key_id": "component-mapper-v1",
        "path": invalid_key.name,
        "sha256": _sha(invalid_key),
    }
    _json(paths["config"], config)

    result = _run(paths, evidence=False)

    assert result["definition"]["status"] == "fail"
    assert "component mapper public key is not Ed25519" in result[
        "definition"
    ]["errors"]
    assert result["corpus_gate_ready"] is False


def test_separation_audit_covers_all_seven_release_authorities():
    config = {
        "executor_trust": {
            "status": "enrolled",
            "key_id": "executor-v1",
            "public_key": f"keys/executor.pub@sha256:{'1' * 64}",
        },
        "canonical_api_runner_public_key": {
            "key_id": "runner-v1", "sha256": "2" * 64,
        },
        "assignment_reviewer_public_key": {
            "key_id": "assignment-v1", "sha256": "7" * 64,
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
        "assignment_reviewer",
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


def test_reviewer_signature_cannot_turn_fake_capture_into_executor_evidence(
    tmp_path: Path,
):
    paths = _fixture(tmp_path)
    paths["capture_artifact"].write_text('{"signed": true}\n')
    evidence = _refresh_evidence_hashes(paths)
    evidence["capture_sha256"] = _sha(paths["capture_artifact"])
    evidence["capture_provenance"]["capture_sha256"] = _sha(
        paths["capture_artifact"]
    )
    evidence["capture_provenance"]["executor_signature_status"] = "verified"
    evidence["capture_provenance"]["capture_validation"] = {"status": "pass"}
    _write_signed(paths, evidence)

    result = _run(paths)

    assert result["corpus_gate_ready"] is False
    assert any(
        "signed capture" in error or "capture is unsigned" in error
        for error in result["quality"]["errors"]
    )


def test_reviewer_cannot_forge_executor_verification_claim(tmp_path: Path):
    paths = _fixture(tmp_path)
    evidence = _refresh_evidence_hashes(paths)
    evidence["capture_provenance"][
        "executor_signature_status"
    ] = "verified-by-reviewer"
    evidence["capture_provenance"]["capture_validation"] = {
        "status": "pass",
        "signature_status": "verified",
    }
    _write_signed(paths, evidence)

    result = _run(paths)

    assert result["corpus_gate_ready"] is False
    assert any(
        "reviewer executor-signature status differs from revalidation" in error
        for error in result["quality"]["errors"]
    )
    assert any(
        "reviewer capture-validation claim differs from revalidation" in error
        for error in result["quality"]["errors"]
    )


def test_reviewer_cannot_substitute_signed_attempt_or_applicability_rows(
    tmp_path: Path,
):
    paths = _fixture(tmp_path)
    evidence = _refresh_evidence_hashes(paths)
    render = next(row for row in evidence["attempts"] if row["kind"] == "render")
    render["render_conformance_score"] = 1
    evidence["not_applicable_assignments"] = [{
        "kind": "edit",
        "evaluation_id": "invented-omission",
        "operation_class": "structural",
        "source_filename": "image-1.png",
        "source_sha256": _sha(paths["first"]),
        "resolved_inputs_sha256": "1" * 64,
        "reason": "reviewer substitution",
        "review_evidence_sha256": "2" * 64,
    }]
    _write_signed(paths, evidence)

    result = _run(paths)

    assert result["corpus_gate_ready"] is False
    assert any(
        "signed evaluator projection differs from replay" in error
        for error in result["quality"]["errors"]
    )
    assert any(
        "reviewed applicability rows differ from signed capture" in error
        for error in result["quality"]["errors"]
    )


def test_reviewer_cannot_substitute_signed_persistence_observations(
    tmp_path: Path,
):
    paths = _fixture(tmp_path)
    evidence = _refresh_evidence_hashes(paths)
    evidence["persistence_evidence"]["commit_sha"] = "e" * 40
    _sign(paths, evidence)
    _json(paths["evidence"], evidence)

    result = _run(paths)

    assert result["corpus_gate_ready"] is False
    assert any(
        "reviewed persistence evidence differs from signed capture" in error
        for error in result["quality"]["errors"]
    )


def test_absent_replay_is_not_run_and_fails_closed(tmp_path: Path):
    paths = _fixture(tmp_path)
    result = _run(paths, evidence=False)
    assert result["source_integrity"]["status"] == "pass"
    assert result["quality"]["status"] == "not_run"
    assert result["corpus_gate_ready"] is False


def test_missing_reviewer_fails_quality(tmp_path: Path):
    paths = _fixture(tmp_path)
    result = _run(paths, review=False)
    assert result["quality"]["reviewer_review_complete"] is False
    assert any("blind v2" in error for error in result["quality"]["errors"])


def test_v1_boolean_review_cannot_make_corpus_ready_without_blind_v2(
    tmp_path: Path,
):
    paths = _fixture(tmp_path)
    legacy = json.loads(paths["evidence"].read_text())["reviewer_review"]
    assert legacy["completed"] is True
    assert all(row["accepted"] is True for row in legacy["decisions"])

    result = _run(paths, review=False)

    assert result["corpus_gate_ready"] is False
    assert result["quality"]["blind_review"]["status"] == "not_run"


def test_blind_packet_must_exactly_cover_selected_replay_artifacts(tmp_path: Path):
    paths = _fixture(tmp_path)
    packet = json.loads(paths["review_packet"].read_text())
    packet["items"][0]["artifacts"]["candidate"]["sha256"] = "f" * 64
    _json(paths["review_packet"], packet)

    result = _run(paths)

    assert result["corpus_gate_ready"] is False
    assert any(
        "does not exactly cover selected replay artifacts" in error
        for error in result["quality"]["errors"]
    )


def test_blind_ledger_profile_must_match_configured_gia_profile(tmp_path: Path):
    paths = _fixture(tmp_path)
    ledger = json.loads(paths["review_ledger"].read_text())
    ledger["reviewer_profile_sha256"] = "c" * 64
    _write_review_ledger(paths, ledger)

    result = _run(paths)

    assert result["corpus_gate_ready"] is False
    assert any(
        "reviewer_profile_sha256 differs" in error
        for error in result["quality"]["errors"]
    )


def test_gia_reviewer_profile_must_be_config_enrolled(tmp_path: Path):
    paths = _fixture(tmp_path)
    config = json.loads(paths["config"].read_text())
    config["reviewer_public_key"].pop("reviewer_profile_sha256")
    _json(paths["config"], config)

    result = _run(paths)

    assert result["corpus_gate_ready"] is False
    assert any(
        "GIA reviewer profile sha256 is invalid" in error
        for error in result["definition"]["errors"]
    )


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


def test_scalar_metric_tampering_cannot_change_replayed_release_metric(
    tmp_path: Path,
):
    paths = _fixture(tmp_path)
    evidence = _refresh_evidence_hashes(paths)
    edit = next(row for row in evidence["attempts"] if row["kind"] == "edit")
    edit["edit_fidelity_score"] = 70
    _write_signed(paths, evidence)
    result = _run(paths)
    assert result["quality"]["release_gates"]["edit_fidelity_pass"] is True
    assert any(
        "signed evaluator projection differs from replay" in error
        for error in result["quality"]["errors"]
    )
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
    _reject_blind_review_item(paths, operation_class="quick_appearance")
    result = _run(paths)
    gate = result["quality"]["classified_release_gates"]["quick_appearance"]
    assert gate["gia_acceptance_rate"] == 0
    assert gate["independent_designer_acceptance_threshold"] == 0.9
    assert gate["pass"] is False
    assert result["corpus_gate_ready"] is False


def test_structural_scalar_cannot_override_replayed_fidelity(tmp_path: Path):
    paths = _fixture(tmp_path)
    evidence = _refresh_evidence_hashes(paths)
    structural = next(
        row for row in evidence["attempts"]
        if row["evaluation_id"] == "band-width"
    )
    structural["edit_fidelity_score"] = 89
    _write_signed(paths, evidence)
    result = _run(paths)
    gate = result["quality"]["classified_release_gates"]["structural"]
    assert gate["mean_edit_fidelity"] == 100
    assert gate["pass"] is True
    assert any(
        "signed evaluator projection differs from replay" in error
        for error in result["quality"]["errors"]
    )
    assert result["corpus_gate_ready"] is False


def test_legacy_boolean_summary_cannot_override_blind_v2_ledger(tmp_path: Path):
    paths = _fixture(tmp_path)
    evidence = _refresh_evidence_hashes(paths)
    evidence["reviewer_review"]["false_negatives"] = 9
    _write_signed(paths, evidence)
    result = _run(paths)
    assert result["quality"]["reviewer_confusion_counts"] == {
        "false_positives": 0, "false_negatives": 0,
    }
    assert result["quality"]["reviewer_review_complete"] is True
    assert result["corpus_gate_ready"] is True


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
        if row["evaluation_id"] != "band-width"
    ]
    _write_signed(paths, evidence)
    result = _run(paths)
    coverage = result["quality"]["source_coverage"]
    assert coverage["expected_source_count"] == 1
    assert coverage["completed_source_count"] == 0
    assert coverage["missing_source_filenames"] == ["image-1.png"]
    assert any("do not match verified attempts" in error
               for error in coverage["errors"])
    assert any(
        "reviewed attempts differ from the executor-signed capture" in error
        for error in result["quality"]["errors"]
    )
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
    candidate_path = evidence["attempts"][0]["candidate_image"]
    evidence["artifact_index"]["artifacts"] = [
        row for row in indexed if row["path"] != candidate_path
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
    render = next(row for row in evidence["attempts"] if row["kind"] == "render")
    render["operation_class"] = "structural"
    _write_signed(paths, evidence)
    result = _run(paths)
    assert any(
        "operation_class differs from frozen workload" in error
        for error in result["quality"]["errors"]
    )
    assert result["corpus_gate_ready"] is False


def test_gia_rejection_of_render_fails_quality(tmp_path: Path):
    paths = _fixture(tmp_path)
    _reject_blind_review_item(paths, kind="render")
    result = _run(paths)
    assert result["quality"]["all_reviewer_decisions_accepted"] is False
    assert result["quality"]["status"] == "fail"


def test_gia_rejection_of_structural_edit_fails_quality(tmp_path: Path):
    paths = _fixture(tmp_path)
    _reject_blind_review_item(paths, operation_class="structural")
    result = _run(paths)
    assert result["quality"]["all_reviewer_decisions_accepted"] is False
    assert result["quality"]["status"] == "fail"


def test_scalar_acceptance_tampering_cannot_change_replayed_hard_pass(
    tmp_path: Path,
):
    paths = _fixture(tmp_path)
    evidence = _refresh_evidence_hashes(paths)
    render = next(row for row in evidence["attempts"] if row["kind"] == "render")
    render["accepted"] = False
    evidence["reviewer_review"]["false_negatives"] = 1
    _write_signed(paths, evidence)
    result = _run(paths)
    assert result["quality"]["release_gates"]["hard_gate_pass"] is True
    assert any(
        "signed evaluator projection differs from replay" in error
        for error in result["quality"]["errors"]
    )
    assert result["quality"]["status"] == "fail"


def test_non_finite_stored_score_fails_closed_against_replay(tmp_path: Path):
    paths = _fixture(tmp_path)
    evidence = _refresh_evidence_hashes(paths)
    render = next(row for row in evidence["attempts"] if row["kind"] == "render")
    render["render_conformance_score"] = float("nan")
    _write_signed(paths, evidence)
    result = _run(paths)
    assert any(
        "signed evaluator projection differs from replay" in error
        for error in result["quality"]["errors"]
    )
    assert result["quality"]["status"] == "fail"


def test_uniform_edit_mask_cannot_claim_zero_drift(tmp_path: Path):
    paths = _fixture(tmp_path)
    evidence = _refresh_evidence_hashes(paths)
    for row in evidence["attempts"]:
        if row["kind"] == "edit":
            mask_path = paths["root"] / row["mask_image"]
            Image.new("L", (4, 4), 255).save(mask_path)
            row["mask_image_sha256"] = _sha(mask_path)
    _write_signed(paths, evidence)
    result = _run(paths)
    assert any(
        "evaluator report replay failed: evaluator report bindings differ"
        in error
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

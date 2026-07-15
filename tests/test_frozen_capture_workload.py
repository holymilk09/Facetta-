from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from facetta.frozen_assignment_contract import (
    SIGNED_ASSIGNMENT_BUNDLE_SCHEMA,
    canonical_assignment_bundle_payload,
)
from facetta.frozen_capture_workload import (
    FROZEN_ROUTING_LABEL,
    _resolved_assignment,
    _routing_attempt_assignments,
    attempt_sequence_errors,
    build_provider_call_plan,
    canonical_capture_payload,
    canonical_object_sha256,
    expected_attempt_routing,
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


_ASSIGNMENT_REVIEWER_KEY_ID = "assignment-reviewer-test-v1"
_ASSIGNMENT_REVIEWER_PROFILE_SHA256 = "8" * 64


def _assignment_reviewer_private_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(bytes(range(32)))


def _install_assignment_reviewer(root: Path) -> dict[str, str]:
    public_key = root / "assignment-reviewer.pub"
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


def _sign_assignment_bundle(bundle: dict[str, object]) -> None:
    bundle["signature"] = {
        "algorithm": "Ed25519",
        "key_id": _ASSIGNMENT_REVIEWER_KEY_ID,
        "value": base64.b64encode(
            _assignment_reviewer_private_key().sign(
                canonical_assignment_bundle_payload(bundle)
            )
        ).decode("ascii"),
    }


def test_component_absence_binding_cannot_replay_across_workload_sources():
    result = _resolved_assignment(
        {"filename": "ring.png", "sha256": "1" * 64},
        {
            "kind": "edit",
            "evaluation_id": "metal-color",
            "operation_class": "quick_appearance",
        },
        {
            "thresholds": {
                "max_attempts": 3,
                "mean_edit_fidelity": 0.9,
                "max_outside_mask_drift": 0.05,
            },
            "frozen_components": {
                "ring_contract": "ring",
                "prompt_bundle": "prompts",
                "evaluator_bundle": "evals",
                "routing": "routing",
                "routing_contract": "contract",
            },
        },
        {
            "schema_version": "facetta-frozen-source-assignment.v1",
            "review_status": "approved",
            "applicability": "not_applicable",
            "not_applicable_reason": (
                "source_component_absent/"
                "component-map-all-required-kinds-absent.v1"
            ),
            "review_evidence_sha256": "2" * 64,
            "source_spec_evidence_sha256": "3" * 64,
            "component_map_sha256": "4" * 64,
            "region_evidence_sha256": "5" * 64,
            "source_sha256": "9" * 64,
        },
        {},
        "6" * 64,
    )

    assert result["assignment_resolved"] is False
    assert (
        "not-applicable assignment source hash differs from workload"
        in result["resolution_errors"]
    )


def _signed_assignment_bundle(
    workload: Path,
    *,
    corpus_run_id: str,
    assignments: list[dict[str, object]],
) -> dict[str, object]:
    bundle: dict[str, object] = {
        "schema_version": SIGNED_ASSIGNMENT_BUNDLE_SCHEMA,
        "workload_sha256": _sha(workload),
        "corpus_run_id": corpus_run_id,
        "reviewer_key_id": _ASSIGNMENT_REVIEWER_KEY_ID,
        "reviewer_profile_sha256": _ASSIGNMENT_REVIEWER_PROFILE_SHA256,
        "reviewed_template_sha256": "9" * 64,
        "release_authority_decision": None,
        "assignments": assignments,
        "signature": None,
    }
    _sign_assignment_bundle(bundle)
    return bundle


def _install_routing_contract(root: Path) -> Path:
    source = (
        Path(__file__).resolve().parents[1]
        / "docs/evals/frozen-founder-corpus-v1/routing-contract.v1.json"
    )
    destination = root / "routing-contract.v1.json"
    destination.write_bytes(source.read_bytes())
    return destination


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


def _evaluator_projection(attempt: dict[str, object]) -> dict[str, object]:
    common = {
        field: attempt.get(field)
        for field in (
            "accepted",
            "attempt_outcome",
            "provider_error_code",
            "qa_outcome",
        )
    }
    if attempt["kind"] == "render":
        common.update(
            render_conformance_score=attempt.get("render_conformance_score"),
            hard_gate_pass=attempt.get("hard_gate_pass"),
        )
    else:
        common.update(
            edit_fidelity_score=attempt.get("edit_fidelity_score"),
            severity=attempt.get("severity"),
            change_applied=attempt.get("change_applied"),
        )
    return common


def _attach_fixture_evaluator_report(
    capture_dir: Path,
    planned: dict[str, object],
    attempt: dict[str, object],
) -> Path:
    report_path = capture_dir / (
        f"{planned['evaluator_report_artifact_stem']}--attempt-"
        f"{attempt['attempt']}.json"
    )
    _write(report_path, {
        "schema_version": "facetta-test-evaluator-report.v1",
        "identity": {
            "kind": planned["kind"],
            "evaluation_id": planned["evaluation_id"],
            "source_filename": planned["source_filename"],
            "resolved_inputs_sha256": planned["resolved_inputs_sha256"],
            "attempt": attempt["attempt"],
        },
        "projection": _evaluator_projection(attempt),
    })
    attempt["evaluator_report"] = report_path.name
    attempt["evaluator_report_sha256"] = _sha(report_path)
    return report_path


def _replay_fixture_evaluator_report(
    report: dict[str, object],
    planned: dict[str, object],
    attempt: dict[str, object],
) -> dict[str, object]:
    if report.get("schema_version") != "facetta-test-evaluator-report.v1":
        raise ValueError("fixture evaluator report schema is invalid")
    identity = report.get("identity")
    expected_identity = {
        "kind": planned["kind"],
        "evaluation_id": planned["evaluation_id"],
        "source_filename": planned["source_filename"],
        "resolved_inputs_sha256": planned["resolved_inputs_sha256"],
        "attempt": attempt["attempt"],
    }
    if identity != expected_identity:
        raise ValueError("fixture evaluator report identity differs")
    projection = report.get("projection")
    if not isinstance(projection, dict):
        raise ValueError("fixture evaluator report projection is invalid")
    return projection


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
    _write(assignment_bundle, _signed_assignment_bundle(
        workload,
        corpus_run_id="fixture-corpus-run-v1",
        assignments=[
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
    ))
    routing_contract = _install_routing_contract(root)
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
        "assignment_reviewer_public_key": _install_assignment_reviewer(root),
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
    })
    return root, manifest, config, workload


def _mark_edit_not_applicable(root: Path, config: Path, *, reason: str) -> None:
    canonical_reason = (
        "canonical_delta_inapplicable/canonical-edit-apply-failed.v1"
    )
    if reason == canonical_reason:
        manifest = root / "manifest.json"
        manifest_raw = json.loads(manifest.read_text())
        manifest_raw["evaluation_slice"]["operation_ids"] = [
            "impossible-band-width"
        ]
        manifest_raw["evaluation_slice"]["operation_classes"] = {
            "quick_appearance": [],
            "structural": ["impossible-band-width"],
        }
        _write(manifest, manifest_raw)

        workload = root / "workload.json"
        workload_raw = json.loads(workload.read_text())
        workload_raw["manifest_sha256"] = _sha(manifest)
        edit_evaluation = workload_raw["evaluation_sets"]["ring-full-v1"][1]
        edit_evaluation["evaluation_id"] = "impossible-band-width"
        edit_evaluation["operation_class"] = "structural"
        _write(workload, workload_raw)

    assignments = root / "assignments.json"
    raw = json.loads(assignments.read_text())
    edit = next(row for row in raw["assignments"] if row["kind"] == "edit")
    binding: dict[str, object] = {
        "schema_version": "facetta-frozen-source-assignment.v1",
        "review_status": "approved",
        "applicability": "not_applicable",
        "not_applicable_reason": reason,
        "review_evidence_sha256": "4" * 64,
        "source_spec_evidence_sha256": "5" * 64,
        "component_map_sha256": "6" * 64,
        "region_evidence_sha256": "7" * 64,
    }
    if reason == canonical_reason:
        impossible_edit = next(
            candidate for candidate in CANONICAL_RING_EDITS
            if candidate.id == "impossible-band-width"
        )
        source_spec = build_ring_golden_spec(
            next(
                case for case in RING_GOLDEN_CASES
                if case.id == impossible_edit.golden_case_id
            )
        )
        target_spec, issues = apply_canonical_ring_edit(
            source_spec,
            impossible_edit,
        )
        assert target_spec is None and issues
        edit["evaluation_id"] = impossible_edit.id
        binding.update({
            "source_sha256": "a" * 64,
            "source_spec": source_spec.model_dump(mode="json"),
            "canonical_edit_issues": issues,
        })
        raw["workload_sha256"] = _sha(root / "workload.json")
    edit["binding"] = binding
    _sign_assignment_bundle(raw)
    _write(assignments, raw)
    config_raw = json.loads(config.read_text())
    if reason == canonical_reason:
        config_raw["manifest_sha256"] = _sha(root / "manifest.json")
        config_raw["frozen_components"]["capture_workload"] = (
            f"workload.json@sha256:{_sha(root / 'workload.json')}"
        )
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


@pytest.mark.parametrize("second_filename", ("ring.png", "Ring.png"))
def test_definition_rejects_candidate_and_mask_stem_collisions_provider_free(
    tmp_path: Path,
    second_filename: str,
):
    root, manifest, config, workload = _fixture(tmp_path)
    manifest_raw = json.loads(manifest.read_text())
    manifest_raw["evaluation_slice"]["ring_source_filenames"] = [
        "ring.jpg",
        second_filename,
    ]
    manifest_raw["sources"][0] = {
        "filename": "ring.jpg",
        "sha256": "c" * 64,
    }
    manifest_raw["sources"][1] = {
        "filename": second_filename,
        "sha256": "a" * 64,
    }
    _write(manifest, manifest_raw)

    workload_raw = json.loads(workload.read_text())
    workload_raw["manifest_sha256"] = _sha(manifest)
    workload_raw["expected_quality_source_count"] = 2
    workload_raw["sources"] = [
        {
            "filename": "ring.jpg",
            "sha256": "c" * 64,
            "integrity_required": True,
            "quality": {
                "slice": "ring",
                "evaluation_set_id": "ring-full-v1",
            },
        },
        {
            "filename": second_filename,
            "sha256": "a" * 64,
            "integrity_required": True,
            "quality": {
                "slice": "ring",
                "evaluation_set_id": "ring-full-v1",
            },
        },
    ]
    _write(workload, workload_raw)

    config_raw = json.loads(config.read_text())
    config_raw["manifest_sha256"] = _sha(manifest)
    config_raw["frozen_components"]["capture_workload"] = (
        f"workload.json@sha256:{_sha(workload)}"
    )
    _write(config, config_raw)

    result = validate_workload_definition(
        manifest,
        config,
        workload,
        repository_root=root,
    )

    assert result["status"] == "fail"
    assert result["provider_calls"] == 0
    collision_error = next(
        error for error in result["errors"]
        if error.startswith("provider artifact output stem collisions:")
    )
    assert "ring--render--round-solitaire-yellow-4-narrow" in collision_error
    assert "candidate:ring.jpg:render:round-solitaire-yellow-4-narrow" in (
        collision_error
    )
    assert f"candidate:{second_filename}:render:round-solitaire-yellow-4-narrow" in (
        collision_error
    )
    assert "ring--edit--metal-color--mask" in collision_error
    assert "mask:ring.jpg:edit:metal-color" in collision_error
    assert f"mask:{second_filename}:edit:metal-color" in collision_error
    with pytest.raises(
        ValueError,
        match="invalid workload definition:.*output stem collisions",
    ):
        build_provider_call_plan(
            manifest,
            config,
            workload,
            repository_root=root,
        )


def test_definition_rejects_non_ascii_or_non_nfc_source_names(tmp_path: Path):
    root, manifest, config, workload = _fixture(tmp_path)
    unsafe = "e\u0301.png"
    manifest_raw = json.loads(manifest.read_text())
    manifest_raw["sources"][0]["filename"] = unsafe
    manifest_raw["evaluation_slice"]["ring_source_filenames"] = [unsafe]
    _write(manifest, manifest_raw)
    workload_raw = json.loads(workload.read_text())
    workload_raw["manifest_sha256"] = _sha(manifest)
    workload_raw["sources"][0]["filename"] = unsafe
    _write(workload, workload_raw)
    config_raw = json.loads(config.read_text())
    config_raw["manifest_sha256"] = _sha(manifest)
    config_raw["frozen_components"]["capture_workload"] = (
        f"workload.json@sha256:{_sha(workload)}"
    )
    _write(config, config_raw)

    result = validate_workload_definition(
        manifest, config, workload, repository_root=root,
    )

    assert result["status"] == "fail"
    assert any(
        "source filenames are not portable artifact identifiers" in error
        for error in result["errors"]
    )


@pytest.mark.parametrize(
    "unsafe",
    ["CON.png", "aux.jpg", "LPT9.webp", "nul.reference.avif", "ring..v1.png"],
)
def test_definition_rejects_windows_reserved_or_ambiguous_source_names(
    tmp_path: Path,
    unsafe: str,
):
    root, manifest, config, workload = _fixture(tmp_path)
    manifest_raw = json.loads(manifest.read_text())
    manifest_raw["sources"][0]["filename"] = unsafe
    manifest_raw["evaluation_slice"]["ring_source_filenames"] = [unsafe]
    _write(manifest, manifest_raw)
    workload_raw = json.loads(workload.read_text())
    workload_raw["manifest_sha256"] = _sha(manifest)
    workload_raw["sources"][0]["filename"] = unsafe
    _write(workload, workload_raw)
    config_raw = json.loads(config.read_text())
    config_raw["manifest_sha256"] = _sha(manifest)
    config_raw["frozen_components"]["capture_workload"] = (
        f"workload.json@sha256:{_sha(workload)}"
    )
    _write(config, config_raw)

    result = validate_workload_definition(
        manifest, config, workload, repository_root=root,
    )

    assert result["status"] == "fail"
    assert any(
        "source filenames are not portable artifact identifiers" in error
        for error in result["errors"]
    )


def test_definition_rejects_traversal_like_evaluation_ids(tmp_path: Path):
    root, manifest, config, workload = _fixture(tmp_path)
    unsafe = "foo/../bar"
    manifest_raw = json.loads(manifest.read_text())
    manifest_raw["evaluation_slice"]["operation_ids"] = [unsafe]
    manifest_raw["evaluation_slice"]["operation_classes"] = {
        "quick_appearance": [],
        "structural": [unsafe],
    }
    _write(manifest, manifest_raw)
    workload_raw = json.loads(workload.read_text())
    workload_raw["manifest_sha256"] = _sha(manifest)
    workload_raw["evaluation_sets"]["ring-full-v1"][1]["evaluation_id"] = unsafe
    workload_raw["evaluation_sets"]["ring-full-v1"][1]["operation_class"] = (
        "structural"
    )
    _write(workload, workload_raw)
    config_raw = json.loads(config.read_text())
    config_raw["manifest_sha256"] = _sha(manifest)
    config_raw["frozen_components"]["capture_workload"] = (
        f"workload.json@sha256:{_sha(workload)}"
    )
    _write(config, config_raw)

    result = validate_workload_definition(
        manifest, config, workload, repository_root=root,
    )

    assert result["status"] == "fail"
    assert any(
        "non-portable evaluation_id" in error for error in result["errors"]
    )


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    (
        ("missing", "config frozen component routing_contract is not hash-pinned"),
        ("drifted", "config frozen component routing_contract implementation drifted"),
        ("reordered", "routing contract route entry 1 differs"),
        ("provider_substitution", "routing contract route entry 2 differs"),
    ),
)
def test_definition_rejects_unfrozen_routing_contract(
    tmp_path: Path,
    mutation: str,
    expected_error: str,
):
    root, manifest, config, workload = _fixture(tmp_path)
    config_raw = json.loads(config.read_text())
    contract = root / "routing-contract.v1.json"
    contract_raw = json.loads(contract.read_text())
    if mutation == "missing":
        del config_raw["frozen_components"]["routing_contract"]
    elif mutation == "drifted":
        contract_raw["selection_policy"]["stop_after_acceptance"] = False
        _write(contract, contract_raw)
    elif mutation == "reordered":
        contract_raw["route_entries"].reverse()
        _write(contract, contract_raw)
        config_raw["frozen_components"]["routing_contract"] = (
            f"{contract.name}@sha256:{_sha(contract)}"
        )
    else:
        contract_raw["route_entries"][1]["provider"] = "fal"
        _write(contract, contract_raw)
        config_raw["frozen_components"]["routing_contract"] = (
            f"{contract.name}@sha256:{_sha(contract)}"
        )
    _write(config, config_raw)

    result = validate_workload_definition(
        manifest,
        config,
        workload,
        repository_root=root,
    )

    assert result["status"] == "fail"
    assert any(expected_error in error for error in result["errors"])


def test_route_assignment_enforces_task_and_image_operation_applicability(
    tmp_path: Path,
):
    root, _, config, _ = _fixture(tmp_path)
    config_raw = json.loads(config.read_text())
    _, contract_sha256 = config_raw["frozen_components"][
        "routing_contract"
    ].rsplit("@sha256:", 1)
    contract = json.loads((root / "routing-contract.v1.json").read_text())
    contract["route_entries"][0]["applicable_task_classes"].remove(
        "structural"
    )

    with pytest.raises(
        ValueError,
        match="does not allow operation class structural",
    ):
        _routing_attempt_assignments(
            contract,
            contract_sha256,
            operation_class="structural",
            image_operation="LOCAL_EDIT",
        )

    contract = json.loads((root / "routing-contract.v1.json").read_text())
    contract["route_entries"][0]["applicable_image_operations"].remove(
        "LOCAL_EDIT"
    )
    with pytest.raises(
        ValueError,
        match="does not allow image operation LOCAL_EDIT",
    ):
        _routing_attempt_assignments(
            contract,
            contract_sha256,
            operation_class="structural",
            image_operation="LOCAL_EDIT",
        )


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
    assert first["assignment_bundle"]["reviewer_key_id"] == (
        _ASSIGNMENT_REVIEWER_KEY_ID
    )
    assert first["assignment_bundle"]["reviewed_template_sha256"] == "9" * 64
    assert {row["source_filename"] for row in first["items"]} == {"ring.png"}
    for row in first["items"]:
        assert row["resolved_inputs"]["schema_version"] == (
            "facetta-frozen-resolved-assignment.v1"
        )
        assert row["resolved_inputs_sha256"] == canonical_object_sha256(
            row["resolved_inputs"]
        )
        if row["resolved_inputs"]["execution_ready"]:
            assert expected_attempt_routing(row, 1) == {
                "routing_contract_sha256": first["routing_contract_sha256"],
                "routing_label": FROZEN_ROUTING_LABEL,
                "route_role": "primary",
                "route": "grok_edit",
                "adapter_key": "grok_direct",
                "provider": "xai",
                "model": "grok-imagine-image-quality",
                "model_revision": None,
                "model_revision_status": "provider_alias_unversioned",
                "endpoint": "https://api.x.ai/v1/images/edits",
                "provider_operation": "images.edits",
                "fallback_reason": None,
            }


def test_plan_rejects_unsigned_v1_assignment_bundle_provider_free(tmp_path: Path):
    root, manifest, config, workload = _fixture(tmp_path)
    assignment_bundle = root / "assignments.json"
    signed = json.loads(assignment_bundle.read_text())
    legacy = {
        "schema_version": "facetta-frozen-assignment-bundle.v1",
        "workload_sha256": signed["workload_sha256"],
        "corpus_run_id": signed["corpus_run_id"],
        "assignments": signed["assignments"],
    }
    _write(assignment_bundle, legacy)
    config_raw = json.loads(config.read_text())
    config_raw["frozen_components"]["resolved_assignment_bundle"] = (
        f"assignments.json@sha256:{_sha(assignment_bundle)}"
    )
    _write(config, config_raw)

    with pytest.raises(ValueError, match="assignment bundle schema is unsupported"):
        build_provider_call_plan(
            manifest,
            config,
            workload,
            repository_root=root,
        )


def test_plan_verifies_signature_before_resolving_assignment_rows(
    tmp_path: Path,
):
    root, manifest, config, workload = _fixture(tmp_path)
    assignment_bundle = root / "assignments.json"
    raw = json.loads(assignment_bundle.read_text())
    raw["assignments"][0]["binding"] = {
        "schema_version": "operator-invented-assignment.v1",
    }
    _write(assignment_bundle, raw)
    config_raw = json.loads(config.read_text())
    config_raw["frozen_components"]["resolved_assignment_bundle"] = (
        f"assignments.json@sha256:{_sha(assignment_bundle)}"
    )
    _write(config, config_raw)

    with pytest.raises(ValueError, match="assignment bundle signature is invalid"):
        build_provider_call_plan(
            manifest,
            config,
            workload,
            repository_root=root,
        )


def test_plan_rejects_signed_shadow_binding_fields_provider_free(tmp_path: Path):
    root, manifest, config, workload = _fixture(tmp_path)
    assignment_bundle = root / "assignments.json"
    raw = json.loads(assignment_bundle.read_text())
    raw["assignments"][0]["binding"]["provider_override"] = "operator-choice"
    _sign_assignment_bundle(raw)
    _write(assignment_bundle, raw)
    config_raw = json.loads(config.read_text())
    config_raw["frozen_components"]["resolved_assignment_bundle"] = (
        f"assignments.json@sha256:{_sha(assignment_bundle)}"
    )
    _write(config, config_raw)

    with pytest.raises(
        ValueError,
        match="assignment bundle binding has unexpected or missing fields",
    ):
        build_provider_call_plan(
            manifest,
            config,
            workload,
            repository_root=root,
        )


def test_plan_blocks_signed_not_applicable_render_provider_free(tmp_path: Path):
    root, manifest, config, workload = _fixture(tmp_path)
    assignment_bundle = root / "assignments.json"
    raw = json.loads(assignment_bundle.read_text())
    render = next(row for row in raw["assignments"] if row["kind"] == "render")
    render["binding"] = {
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
    }
    _sign_assignment_bundle(raw)
    _write(assignment_bundle, raw)
    config_raw = json.loads(config.read_text())
    config_raw["frozen_components"]["resolved_assignment_bundle"] = (
        f"assignments.json@sha256:{_sha(assignment_bundle)}"
    )
    _write(config, config_raw)

    with pytest.raises(ValueError, match="render cannot be not_applicable"):
        build_provider_call_plan(
            manifest,
            config,
            workload,
            repository_root=root,
        )


def test_reviewed_not_applicable_rows_remain_signed_without_provider_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "facetta.frozen_capture_workload.validate_and_replay_evaluator_report",
        _replay_fixture_evaluator_report,
    )
    root, manifest, config, workload = _fixture(tmp_path)
    _mark_edit_not_applicable(
        root,
        config,
        reason=(
            "canonical_delta_inapplicable/canonical-edit-apply-failed.v1"
        ),
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
    render_attempt = {
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
        "render_conformance_score": 95,
        "hard_gate_pass": True,
    }
    _attach_fixture_evaluator_report(capture_dir, planned, render_attempt)
    capture = {
        "schema_version": "facetta-frozen-capture.v3",
        "corpus_run_id": plan["corpus_run_id"],
        "manifest_sha256": plan["manifest_sha256"],
        "config_sha256": plan["config_sha256"],
        "workload_sha256": plan["workload_sha256"],
        "assignment_bundle_sha256": plan["assignment_bundle"]["bundle_sha256"],
        "not_applicable_assignments": not_applicable_assignment_rows(plan),
        "attempts": [render_attempt],
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

    capture["attempts"][0]["model"] = "grok_direct"
    sign()
    _write(capture_path, capture)
    substituted = validate_capture_envelope(
        capture_path, manifest, config, workload,
        capture_public_key_path=public_key_path,
        capture_key_id="executor-test-v1",
        repository_root=root,
    )
    assert substituted["status"] == "fail"
    assert any(
        "route/provider/model differs" in error
        for error in substituted["errors"]
    )
    capture["attempts"][0].update(expected_attempt_routing(planned, 1))

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
        "attempt_outcome": "accepted",
        "provider_error_code": None,
        "qa_outcome": "pass",
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
    with pytest.raises(ValueError, match="not-applicable reason is unsupported"):
        build_provider_call_plan(
            manifest, config, workload, repository_root=root,
        )


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
    workload_raw["config_id"] = "synthetic-complete-1044-v1"
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
    _write(assignment_bundle, _signed_assignment_bundle(
        workload,
        corpus_run_id="synthetic-complete-1044-v1",
        assignments=assignments,
    ))
    routing_contract = _install_routing_contract(root)
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
        "assignment_reviewer_public_key": _install_assignment_reviewer(root),
        "frozen_components": {
            "capture_workload": f"workload.json@sha256:{_sha(workload)}",
            "resolved_assignment_bundle": (
                f"assignments.json@sha256:{_sha(assignment_bundle)}"
            ),
            "ring_contract": "synthetic-ring-contract@sha256:" + "1" * 64,
            "prompt_bundle": "synthetic-prompt-bundle@sha256:" + "2" * 64,
            "evaluator_bundle": "synthetic-evaluator-bundle@sha256:" + "3" * 64,
            "routing": FROZEN_ROUTING_LABEL,
            "routing_contract": (
                f"{routing_contract.name}@sha256:{_sha(routing_contract)}"
            ),
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


def test_signed_capture_binds_plan_artifacts_and_persistence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "facetta.frozen_capture_workload.validate_and_replay_evaluator_report",
        _replay_fixture_evaluator_report,
    )
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
            **expected_attempt_routing(planned, 1),
            "accepted": True,
            "attempt_outcome": "accepted",
            "provider_error_code": None,
            "qa_outcome": "pass",
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
        _attach_fixture_evaluator_report(capture_dir, planned, row)
        attempts.append(row)
    capture = {
        "schema_version": "facetta-frozen-capture.v3",
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

    def sign() -> None:
        capture["signature"] = {
            "algorithm": "Ed25519",
            "key_id": "executor-test-v1",
            "public_key_sha256": _sha(public_key_path),
            "value": base64.b64encode(
                private_key.sign(canonical_capture_payload(capture))
            ).decode("ascii"),
        }

    sign()
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
    assert result["verified_artifact_count"] == 5
    assert result["corpus_gate_ready"] is False
    assert plan["schema_version"] == "facetta-frozen-provider-call-plan.v3"
    assert all(
        item["evaluator_report_artifact_stem"].endswith("--evaluator-report")
        for item in plan["items"]
    )

    report_attempt = next(row for row in attempts if row["kind"] == "render")
    original_report_path = report_attempt.pop("evaluator_report")
    original_report_hash = report_attempt.pop("evaluator_report_sha256")
    sign()
    _write(capture_path, capture)
    missing_report = validate_capture_envelope(
        capture_path,
        manifest,
        config,
        workload,
        capture_public_key_path=public_key_path,
        capture_key_id="executor-test-v1",
        repository_root=root,
    )
    assert missing_report["status"] == "fail"
    assert any(
        "lacks an evaluator report path" in error
        for error in missing_report["errors"]
    )
    report_attempt["evaluator_report"] = original_report_path
    report_attempt["evaluator_report_sha256"] = original_report_hash

    report_attempt["render_conformance_score"] = 94
    sign()
    _write(capture_path, capture)
    altered_projection = validate_capture_envelope(
        capture_path,
        manifest,
        config,
        workload,
        capture_public_key_path=public_key_path,
        capture_key_id="executor-test-v1",
        repository_root=root,
    )
    assert altered_projection["status"] == "fail"
    assert any(
        "signed evaluator projection differs from replay" in error
        for error in altered_projection["errors"]
    )
    report_attempt["render_conformance_score"] = 95

    evaluator_report = capture_dir / str(original_report_path)
    original_report_bytes = evaluator_report.read_bytes()
    _write(evaluator_report, {"schema_version": "tampered"})
    report_attempt["evaluator_report_sha256"] = _sha(evaluator_report)
    sign()
    _write(capture_path, capture)
    invalid_replay = validate_capture_envelope(
        capture_path,
        manifest,
        config,
        workload,
        capture_public_key_path=public_key_path,
        capture_key_id="executor-test-v1",
        repository_root=root,
    )
    assert invalid_replay["status"] == "fail"
    assert any(
        "evaluator report is invalid" in error
        for error in invalid_replay["errors"]
    )
    evaluator_report.write_bytes(original_report_bytes)
    report_attempt["evaluator_report_sha256"] = original_report_hash

    outside_report = root / "outside-report.json"
    outside_report.write_bytes(original_report_bytes)
    report_attempt["evaluator_report"] = "../outside-report.json"
    report_attempt["evaluator_report_sha256"] = _sha(outside_report)
    sign()
    _write(capture_path, capture)
    escaped_report = validate_capture_envelope(
        capture_path,
        manifest,
        config,
        workload,
        capture_public_key_path=public_key_path,
        capture_key_id="executor-test-v1",
        repository_root=root,
    )
    assert escaped_report["status"] == "fail"
    assert any(
        "invalid evaluator_report path" in error
        for error in escaped_report["errors"]
    )
    report_attempt["evaluator_report"] = original_report_path
    report_attempt["evaluator_report_sha256"] = original_report_hash

    capture["schema_version"] = "facetta-frozen-capture.v2"
    sign()
    _write(capture_path, capture)
    legacy_capture = validate_capture_envelope(
        capture_path,
        manifest,
        config,
        workload,
        capture_public_key_path=public_key_path,
        capture_key_id="executor-test-v1",
        repository_root=root,
    )
    assert legacy_capture["status"] == "fail"
    assert "unsupported capture schema_version" in legacy_capture["errors"]
    capture["schema_version"] = "facetta-frozen-capture.v3"

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


def test_signed_capture_rejects_artifact_tampering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "facetta.frozen_capture_workload.validate_and_replay_evaluator_report",
        _replay_fixture_evaluator_report,
    )
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
            row.update(
                edit_fidelity_score=95,
                severity="none",
                change_applied=True,
            )
        if planned["kind"] == "edit":
            row.update(mask_image=mask.name, mask_image_sha256=_sha(mask))
        _attach_fixture_evaluator_report(capture_dir, planned, row)
        attempts.append(row)
    capture = {
        "schema_version": "facetta-frozen-capture.v3",
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


def test_provider_failure_forbids_evaluator_report_references(tmp_path: Path):
    root, manifest, config, workload = _fixture(tmp_path)
    plan = build_provider_call_plan(
        manifest, config, workload, repository_root=root,
    )
    planned = plan["items"][0]
    failed_attempt = {
        "kind": planned["kind"],
        "evaluation_id": planned["evaluation_id"],
        "source_filename": planned["source_filename"],
        "source_sha256": planned["source_sha256"],
        "resolved_inputs_sha256": planned["resolved_inputs_sha256"],
        "attempt": 1,
        **expected_attempt_routing(planned, 1),
        "accepted": False,
        "attempt_outcome": "provider_failed",
        "provider_error_code": "provider_timeout",
        "qa_outcome": None,
        "evaluator_report": "provider-failure-report.json",
        "evaluator_report_sha256": "f" * 64,
    }

    errors = attempt_sequence_errors(
        [failed_attempt], planned, label="fixture",
    )

    assert any(
        "provider failure declares an evaluator report" in error
        for error in errors
    )

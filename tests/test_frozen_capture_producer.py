from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from facetta.frozen_capture_producer import (
    BundleCaptureExecutor,
    Ed25519PrivateKeySigner,
    FilePersistenceObservationRunner,
    FrozenCaptureProducer,
)
from facetta.frozen_capture_workload import (
    build_provider_call_plan,
    canonical_object_sha256,
    validate_capture_envelope,
)
from facetta.frozen_persistence_attestation import (
    RESULT_SET_SCHEMA,
    result_set_sha256,
    verify_persistence_attestation,
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


def _public_bytes(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def _binding(evaluation_id: str, kind: str) -> dict[str, object]:
    cases = {case.id: case for case in RING_GOLDEN_CASES}
    if kind == "render":
        source = build_ring_golden_spec(cases[evaluation_id]).model_dump(mode="json")
        target = source
        instruction = f"frozen founder corpus render: {evaluation_id}"
        region = None
        frozen = ["reviewed source geometry"]
    else:
        edit = next(item for item in CANONICAL_RING_EDITS if item.id == evaluation_id)
        source_model = build_ring_golden_spec(cases[edit.golden_case_id])
        target_model, issues = apply_canonical_ring_edit(source_model, edit)
        assert target_model is not None and not issues
        source = source_model.model_dump(mode="json")
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
        "source_spec": source,
        "target_spec": target,
        "instruction": instruction,
        "region_description": region,
        "frozen_facts": frozen,
    }


def _fixture(
    tmp_path: Path,
    *,
    resolved: bool = True,
    enrolled: bool = True,
) -> dict[str, object]:
    repository = tmp_path / "repo"
    evidence = tmp_path / "evidence"
    source_dir = evidence / "sources"
    source_dir.mkdir(parents=True)
    source = source_dir / "ring.png"
    source.write_bytes(b"frozen-ring-source")
    manifest = repository / "manifest.json"
    config = repository / "config.json"
    workload = repository / "workload.json"
    _write(manifest, {
        "corpus_id": "capture-producer-fixture-v1",
        "expected_source_count": 1,
        "sources": [{"filename": "ring.png", "sha256": _sha(source)}],
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
        "workload_id": "capture-producer-workload-v1",
        "corpus_id": "capture-producer-fixture-v1",
        "config_id": "capture-producer-config-v1",
        "manifest_sha256": _sha(manifest),
        "expected_integrity_source_count": 1,
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
        "sources": [{
            "filename": "ring.png",
            "sha256": _sha(source),
            "integrity_required": True,
            "quality": {"slice": "ring", "evaluation_set_id": "ring-full-v1"},
        }],
    })
    assignments = repository / "assignments.json"
    if resolved:
        _write(assignments, {
            "schema_version": "facetta-frozen-assignment-bundle.v1",
            "workload_sha256": _sha(workload),
            "corpus_run_id": "capture-producer-run-v1",
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
    executor_private = Ed25519PrivateKey.generate()
    api_private = Ed25519PrivateKey.generate()
    executor_public = repository / "executor.pub"
    api_public = repository / "canonical-api-runner.pub"
    executor_public.parent.mkdir(parents=True, exist_ok=True)
    executor_public.write_bytes(_public_bytes(executor_private))
    api_public.write_bytes(_public_bytes(api_private))
    component_dir = repository / "components"
    component_dir.mkdir()
    component_files: dict[str, Path] = {}
    for name in (
        "ring_contract",
        "prompt_bundle",
        "evaluator_bundle",
        "live_runner",
        "replay_verifier",
        "replay_runner",
        "release_verifier",
        "packet_builder",
        "packet_runner",
        "capture_producer",
        "capture_producer_cli",
    ):
        component = component_dir / f"{name}.py"
        component.write_text(f"# frozen {name} fixture\n")
        component_files[name] = component
    frozen_components: dict[str, str] = {
        "capture_workload": f"workload.json@sha256:{_sha(workload)}",
        **{
            name: f"components/{path.name}@sha256:{_sha(path)}"
            for name, path in component_files.items()
        },
        "routing": "provider-free-fixture.v1",
    }
    if resolved:
        frozen_components["resolved_assignment_bundle"] = (
            f"assignments.json@sha256:{_sha(assignments)}"
        )
    config_value: dict[str, object] = {
        "config_id": "capture-producer-config-v1",
        "manifest_sha256": _sha(manifest),
        "thresholds": {
            "max_attempts": 3,
            "mean_render_conformance": 85,
            "render_hard_gate_pass_rate": 0.9,
            "mean_edit_fidelity": 90,
            "max_outside_mask_drift": 0.18,
        },
        "frozen_components": frozen_components,
        "canonical_api_runner_public_key": {
            "key_id": "api-runner-test-v1",
            "path": "canonical-api-runner.pub",
            "sha256": _sha(api_public),
        },
    }
    if enrolled:
        config_value["executor_trust"] = {
            "schema_version": "facetta-frozen-executor-trust.v1",
            "status": "enrolled",
            "key_id": "executor-test-v1",
            "public_key": f"executor.pub@sha256:{_sha(executor_public)}",
        }
    _write(config, config_value)
    return {
        "repository": repository,
        "evidence": evidence,
        "source_dir": source_dir,
        "manifest": manifest,
        "config": config,
        "workload": workload,
        "executor_private": executor_private,
        "api_private": api_private,
        "executor_public": executor_public,
        "capture_producer_component": component_files["capture_producer"],
    }


class _FakeExecutor:
    provider_calls_executed = 0

    def __init__(self, evidence: Path, *, attempt_count: int = 1):
        self.evidence = evidence
        self.attempt_count = attempt_count
        self.preflight_calls = 0
        self.execute_calls = 0
        inbox = evidence / "executor"
        inbox.mkdir(parents=True, exist_ok=True)
        self.render = inbox / "render.png"
        self.edit = inbox / "edit.png"
        self.mask = inbox / "mask.png"
        self.render.write_bytes(b"render-candidate")
        self.edit.write_bytes(b"edit-candidate")
        self.mask.write_bytes(b"edit-mask")

    def preflight(self, *, plan: dict[str, object], evidence_root: Path) -> None:
        self.preflight_calls += 1
        assert plan["execution_ready_sequence_count"] == 2
        assert evidence_root == self.evidence.resolve()

    def execute(self, item: dict[str, object]) -> list[dict[str, object]]:
        self.execute_calls += 1
        rows = []
        for index in range(1, self.attempt_count + 1):
            accepted = index == self.attempt_count
            if item["kind"] == "render":
                rows.append({
                    "accepted": accepted,
                    "candidate_image": self.render,
                    "candidate_image_sha256": _sha(self.render),
                    "render_conformance_score": 96,
                    "hard_gate_pass": True,
                })
            else:
                rows.append({
                    "accepted": accepted,
                    "candidate_image": self.edit,
                    "candidate_image_sha256": _sha(self.edit),
                    "mask_image": self.mask,
                    "mask_image_sha256": _sha(self.mask),
                    "edit_fidelity_score": 97,
                    "severity": "none",
                    "change_applied": True,
                })
        return rows


def test_preflight_rejects_frozen_capture_producer_drift_before_execution(
    tmp_path: Path,
):
    fixture = _fixture(tmp_path)
    executor = _FakeExecutor(fixture["evidence"])  # type: ignore[arg-type]
    producer = _producer(
        fixture,
        executor=executor,
        persistence_runner=_FakePersistenceRunner(),
    )
    component: Path = fixture["capture_producer_component"]  # type: ignore[assignment]
    component.write_text("# drifted capture producer fixture\n")

    with pytest.raises(
        ValueError,
        match="capture_producer implementation drifted",
    ):
        producer.produce()

    assert executor.preflight_calls == 0
    assert executor.execute_calls == 0
    assert not (fixture["evidence"] / "capture").exists()  # type: ignore[operator]


class _FakePersistenceRunner:
    def __init__(self):
        self.preflight_calls = 0
        self.observe_calls = 0

    def preflight(self, *, plan: dict[str, object]) -> None:
        self.preflight_calls += 1
        assert plan["corpus_run_id"] == "capture-producer-run-v1"

    def observe(self, *, selected_result_set: list[dict[str, object]]) -> dict[str, object]:
        self.observe_calls += 1
        return {"checks": _checks(len(selected_result_set))}


def _checks(count: int) -> dict[str, object]:
    return {
        "atomic_image_spec_persistence": {
            "status": "pass",
            "verified_result_count": count,
            "image_and_spec_committed_together": True,
            "partial_commit_count": 0,
        },
        "stale_write_rejection": {
            "status": "pass",
            "attempted_count": 2,
            "rejected_count": 2,
            "canonical_mutation_count": 0,
        },
        "rejected_candidate_persistence": {
            "status": "pass",
            "tested_rejected_candidate_count": 1,
            "active_asset_count": 0,
        },
    }


def _producer(
    fixture: dict[str, object],
    *,
    executor: object,
    persistence_runner: object,
    output_name: str = "capture",
) -> FrozenCaptureProducer:
    return FrozenCaptureProducer(
        repository_root=fixture["repository"],  # type: ignore[arg-type]
        evidence_root=fixture["evidence"],  # type: ignore[arg-type]
        manifest_path=fixture["manifest"],  # type: ignore[arg-type]
        config_path=fixture["config"],  # type: ignore[arg-type]
        workload_path=fixture["workload"],  # type: ignore[arg-type]
        source_dir=fixture["source_dir"],  # type: ignore[arg-type]
        output_dir=Path(output_name),
        executor=executor,  # type: ignore[arg-type]
        persistence_runner=persistence_runner,  # type: ignore[arg-type]
        executor_signer=Ed25519PrivateKeySigner(
            "executor-test-v1",
            fixture["executor_private"],  # type: ignore[arg-type]
        ),
        api_signer=Ed25519PrivateKeySigner(
            "api-runner-test-v1",
            fixture["api_private"],  # type: ignore[arg-type]
        ),
        commit_sha="a" * 40,
        attestation_id="capture-producer-attestation-v1",
    )


@pytest.mark.parametrize(
    ("resolved", "enrolled", "message"),
    [
        (False, True, "unresolved assignments"),
        (True, False, "no enrolled executor"),
    ],
)
def test_preflight_refuses_unresolved_or_unenrolled_without_execution(
    tmp_path: Path,
    resolved: bool,
    enrolled: bool,
    message: str,
):
    fixture = _fixture(tmp_path, resolved=resolved, enrolled=enrolled)
    executor = _FakeExecutor(fixture["evidence"])  # type: ignore[arg-type]
    persistence = _FakePersistenceRunner()
    producer = _producer(
        fixture, executor=executor, persistence_runner=persistence,
    )
    with pytest.raises(ValueError, match=message):
        producer.produce()
    assert executor.preflight_calls == 0
    assert executor.execute_calls == 0
    assert persistence.preflight_calls == 0
    assert not (fixture["evidence"] / "capture").exists()  # type: ignore[operator]


def test_attempt_ceiling_fails_without_partial_capture(tmp_path: Path):
    fixture = _fixture(tmp_path)
    executor = _FakeExecutor(fixture["evidence"], attempt_count=4)  # type: ignore[arg-type]
    producer = _producer(
        fixture,
        executor=executor,
        persistence_runner=_FakePersistenceRunner(),
    )
    with pytest.raises(ValueError, match="attempt count is out of bounds"):
        producer.produce()
    assert executor.execute_calls == 1
    assert not (fixture["evidence"] / "capture").exists()  # type: ignore[operator]


def test_terminal_unaccepted_render_and_edit_capture_final_attempt(
    tmp_path: Path,
):
    fixture = _fixture(tmp_path)

    class ExhaustedExecutor(_FakeExecutor):
        def execute(self, item: dict[str, object]) -> list[dict[str, object]]:
            rows = super().execute(item)
            for row in rows:
                row["accepted"] = False
                if item["kind"] == "render":
                    row["hard_gate_pass"] = False
                else:
                    row["severity"] = "major"
                    row["change_applied"] = False
            return rows

    class RecordingPersistenceRunner(_FakePersistenceRunner):
        selected: list[dict[str, object]] | None = None

        def observe(
            self,
            *,
            selected_result_set: list[dict[str, object]],
        ) -> dict[str, object]:
            self.selected = selected_result_set
            return super().observe(selected_result_set=selected_result_set)

    executor = ExhaustedExecutor(
        fixture["evidence"],  # type: ignore[arg-type]
        attempt_count=3,
    )
    persistence = RecordingPersistenceRunner()
    producer = _producer(
        fixture,
        executor=executor,
        persistence_runner=persistence,
    )

    producer.produce()

    assert persistence.selected is not None
    assert {
        row["kind"]: row["selected_attempt"] for row in persistence.selected
    } == {"edit": 3, "render": 3}

    evidence: Path = fixture["evidence"]  # type: ignore[assignment]
    capture_path = evidence / "capture" / "capture.json"
    capture = json.loads(capture_path.read_text())
    assert len(capture["attempts"]) == 6
    assert all(row["accepted"] is False for row in capture["attempts"])
    final_by_kind = {
        row["kind"]: row
        for row in capture["attempts"]
        if row["attempt"] == 3
    }
    assert final_by_kind["render"]["hard_gate_pass"] is False
    assert final_by_kind["edit"]["change_applied"] is False
    assert final_by_kind["edit"]["severity"] == "major"

    validation = validate_capture_envelope(
        capture_path,
        fixture["manifest"],  # type: ignore[arg-type]
        fixture["config"],  # type: ignore[arg-type]
        fixture["workload"],  # type: ignore[arg-type]
        capture_public_key_path=fixture["executor_public"],  # type: ignore[arg-type]
        capture_key_id="executor-test-v1",
        repository_root=fixture["repository"],  # type: ignore[arg-type]
    )
    assert validation["status"] == "pass"
    assert validation["signature_status"] == "verified"


@pytest.mark.parametrize(
    ("accepted_pattern", "message"),
    [
        ([True, False], "accepted attempt must be final"),
        ([True, True], "multiple accepted attempts"),
    ],
)
def test_invalid_early_or_multiple_acceptance_fails_without_partial_capture(
    tmp_path: Path,
    accepted_pattern: list[bool],
    message: str,
):
    fixture = _fixture(tmp_path)

    class InvalidAcceptanceExecutor(_FakeExecutor):
        def execute(self, item: dict[str, object]) -> list[dict[str, object]]:
            rows = super().execute(item)
            for row, accepted in zip(rows, accepted_pattern, strict=True):
                row["accepted"] = accepted
            return rows

    executor = InvalidAcceptanceExecutor(
        fixture["evidence"],  # type: ignore[arg-type]
        attempt_count=len(accepted_pattern),
    )
    persistence = _FakePersistenceRunner()
    producer = _producer(
        fixture,
        executor=executor,
        persistence_runner=persistence,
    )

    with pytest.raises(ValueError, match=message):
        producer.produce()

    assert executor.execute_calls == 1
    assert persistence.observe_calls == 0
    assert not (fixture["evidence"] / "capture").exists()  # type: ignore[operator]


def test_pluggable_executor_artifacts_cannot_escape_evidence_root(tmp_path: Path):
    fixture = _fixture(tmp_path)
    outside = tmp_path / "outside-candidate.png"
    outside.write_bytes(b"outside")

    class EscapingExecutor(_FakeExecutor):
        def execute(self, item: dict[str, object]) -> list[dict[str, object]]:
            rows = super().execute(item)
            rows[0]["candidate_image"] = outside
            rows[0]["candidate_image_sha256"] = _sha(outside)
            return rows

    escaping = EscapingExecutor(fixture["evidence"])  # type: ignore[arg-type]
    producer = _producer(
        fixture,
        executor=escaping,
        persistence_runner=_FakePersistenceRunner(),
    )
    with pytest.raises(ValueError, match="escapes the evidence root"):
        producer.produce()
    assert escaping.execute_calls == 1
    assert not (fixture["evidence"] / "capture").exists()  # type: ignore[operator]


def test_post_execution_provider_call_ceiling_fails_before_persistence(
    tmp_path: Path,
):
    fixture = _fixture(tmp_path)

    class OverBudgetExecutor(_FakeExecutor):
        def execute(self, item: dict[str, object]) -> list[dict[str, object]]:
            rows = super().execute(item)
            self.provider_calls_executed = 7
            return rows

    executor = OverBudgetExecutor(fixture["evidence"])  # type: ignore[arg-type]
    persistence = _FakePersistenceRunner()
    producer = _producer(
        fixture,
        executor=executor,
        persistence_runner=persistence,
    )

    with pytest.raises(ValueError, match="provider-call ceiling during execution"):
        producer.produce()

    assert persistence.observe_calls == 0
    assert not (fixture["evidence"] / "capture").exists()  # type: ignore[operator]


@pytest.mark.parametrize("unsafe", ["escape", "hash"])
def test_bundle_preflight_rejects_path_escape_and_hash_drift(
    tmp_path: Path,
    unsafe: str,
):
    fixture = _fixture(tmp_path)
    plan = build_provider_call_plan(
        fixture["manifest"],  # type: ignore[arg-type]
        fixture["config"],  # type: ignore[arg-type]
        fixture["workload"],  # type: ignore[arg-type]
        repository_root=fixture["repository"],  # type: ignore[arg-type]
    )
    evidence: Path = fixture["evidence"]  # type: ignore[assignment]
    inbox = evidence / "bundle-inputs"
    inbox.mkdir()
    candidate = inbox / "candidate.png"
    mask = inbox / "mask.png"
    candidate.write_bytes(b"candidate")
    mask.write_bytes(b"mask")
    sequences = []
    for item in plan["items"]:
        candidate_ref = "../outside.png" if unsafe == "escape" else (
            candidate.relative_to(evidence).as_posix()
        )
        candidate_hash = "0" * 64 if unsafe == "hash" else _sha(candidate)
        attempt: dict[str, object] = {
            "accepted": True,
            "candidate_image": candidate_ref,
            "candidate_image_sha256": candidate_hash,
        }
        if item["kind"] == "render":
            attempt.update(render_conformance_score=95, hard_gate_pass=True)
        else:
            attempt.update(
                mask_image=mask.relative_to(evidence).as_posix(),
                mask_image_sha256=_sha(mask),
                edit_fidelity_score=95,
                severity="none",
                change_applied=True,
            )
        sequences.append({
            "kind": item["kind"],
            "evaluation_id": item["evaluation_id"],
            "source_filename": item["source_filename"],
            "resolved_inputs_sha256": item["resolved_inputs_sha256"],
            "attempts": [attempt],
        })
    bundle = evidence / "execution-bundle.json"
    _write(bundle, {
        "schema_version": "facetta-frozen-execution-bundle.v1",
        "corpus_run_id": plan["corpus_run_id"],
        "plan_sha256": canonical_object_sha256(plan),
        "provider_calls_executed": 0,
        "sequences": sequences,
    })
    producer = _producer(
        fixture,
        executor=BundleCaptureExecutor(bundle),
        persistence_runner=_FakePersistenceRunner(),
    )
    expected = "escapes the evidence root" if unsafe == "escape" else "hash differs"
    with pytest.raises(ValueError, match=expected):
        producer.produce()
    assert not (evidence / "capture").exists()


def _bundle_inputs(
    fixture: dict[str, object],
) -> tuple[Path, Path, list[dict[str, object]]]:
    plan = build_provider_call_plan(
        fixture["manifest"],  # type: ignore[arg-type]
        fixture["config"],  # type: ignore[arg-type]
        fixture["workload"],  # type: ignore[arg-type]
        repository_root=fixture["repository"],  # type: ignore[arg-type]
    )
    evidence: Path = fixture["evidence"]  # type: ignore[assignment]
    inbox = evidence / "bundle-inputs"
    inbox.mkdir(exist_ok=True)
    candidate = inbox / "candidate.png"
    mask = inbox / "mask.png"
    candidate.write_bytes(b"candidate")
    mask.write_bytes(b"mask")
    sequences = []
    selected = []
    for item in plan["items"]:
        attempt: dict[str, object] = {
            "accepted": True,
            "candidate_image": candidate.relative_to(evidence).as_posix(),
            "candidate_image_sha256": _sha(candidate),
        }
        if item["kind"] == "render":
            attempt.update(render_conformance_score=96, hard_gate_pass=True)
        else:
            attempt.update(
                mask_image=mask.relative_to(evidence).as_posix(),
                mask_image_sha256=_sha(mask),
                edit_fidelity_score=97,
                severity="none",
                change_applied=True,
            )
        sequences.append({
            "kind": item["kind"],
            "evaluation_id": item["evaluation_id"],
            "source_filename": item["source_filename"],
            "resolved_inputs_sha256": item["resolved_inputs_sha256"],
            "attempts": [attempt],
        })
        selected.append({
            "kind": item["kind"],
            "evaluation_id": item["evaluation_id"],
            "source_filename": item["source_filename"],
            "selected_attempt": 1,
            "candidate_image_sha256": _sha(candidate),
        })
    bundle = evidence / "execution-bundle.json"
    _write(bundle, {
        "schema_version": "facetta-frozen-execution-bundle.v1",
        "corpus_run_id": plan["corpus_run_id"],
        "plan_sha256": canonical_object_sha256(plan),
        "provider_calls_executed": 0,
        "sequences": sequences,
    })
    observations = evidence / "persistence-observations.json"
    _write(observations, {
        "schema_version": "facetta-canonical-persistence-observations.v1",
        "corpus_run_id": plan["corpus_run_id"],
        "result_set_schema_version": RESULT_SET_SCHEMA,
        "result_set_sha256": result_set_sha256(selected),
        "result_count": len(selected),
        "checks": _checks(len(selected)),
    })
    return bundle, observations, selected


def test_persistence_observations_must_bind_exact_selected_results(tmp_path: Path):
    fixture = _fixture(tmp_path)
    bundle, observations, _ = _bundle_inputs(fixture)
    value = json.loads(observations.read_text())
    value["result_set_sha256"] = "0" * 64
    _write(observations, value)
    producer = _producer(
        fixture,
        executor=BundleCaptureExecutor(bundle),
        persistence_runner=FilePersistenceObservationRunner(
            observations,
            evidence_root=fixture["evidence"],  # type: ignore[arg-type]
        ),
    )
    with pytest.raises(ValueError, match="result-set hash differs"):
        producer.produce()
    assert not (fixture["evidence"] / "capture").exists()  # type: ignore[operator]


def test_selected_result_is_scoped_to_each_planned_sequence(tmp_path: Path):
    fixture = _fixture(tmp_path)

    class VariableAttemptExecutor(_FakeExecutor):
        def execute(self, item: dict[str, object]) -> list[dict[str, object]]:
            previous = self.attempt_count
            self.attempt_count = 2 if item["kind"] == "edit" else 1
            try:
                return super().execute(item)
            finally:
                self.attempt_count = previous

    class RecordingPersistenceRunner(_FakePersistenceRunner):
        selected: list[dict[str, object]] | None = None

        def observe(
            self,
            *,
            selected_result_set: list[dict[str, object]],
        ) -> dict[str, object]:
            self.selected = selected_result_set
            return super().observe(selected_result_set=selected_result_set)

    executor = VariableAttemptExecutor(fixture["evidence"])  # type: ignore[arg-type]
    persistence = RecordingPersistenceRunner()
    producer = _producer(
        fixture,
        executor=executor,
        persistence_runner=persistence,
    )
    producer.produce()
    assert persistence.selected is not None
    attempts_by_kind = {
        row["kind"]: row["selected_attempt"] for row in persistence.selected
    }
    assert attempts_by_kind == {"edit": 2, "render": 1}


def test_provider_free_bundle_round_trip_is_deterministic_and_verified(
    tmp_path: Path,
):
    fixture = _fixture(tmp_path)
    bundle, observations, selected = _bundle_inputs(fixture)
    summaries = []
    for output_name in ("capture-a", "capture-b"):
        producer = _producer(
            fixture,
            executor=BundleCaptureExecutor(bundle),
            persistence_runner=FilePersistenceObservationRunner(
                observations,
                evidence_root=fixture["evidence"],  # type: ignore[arg-type]
            ),
            output_name=output_name,
        )
        summaries.append(producer.produce())

    evidence: Path = fixture["evidence"]  # type: ignore[assignment]
    first_capture = evidence / "capture-a" / "capture.json"
    second_capture = evidence / "capture-b" / "capture.json"
    assert first_capture.read_bytes() == second_capture.read_bytes()
    assert summaries[0]["provider_calls_executed"] == 0
    assert summaries[0]["signature_status"] == "verified"

    capture = json.loads(first_capture.read_text())
    indexed_roles = {
        role
        for row in capture["artifact_index"]["artifacts"]
        for role in row["roles"]
    }
    assert {
        "source-image",
        "candidate-image",
        "edit-mask",
        "canonical-persistence-attestation",
    } <= indexed_roles
    capture_validation = validate_capture_envelope(
        first_capture,
        fixture["manifest"],  # type: ignore[arg-type]
        fixture["config"],  # type: ignore[arg-type]
        fixture["workload"],  # type: ignore[arg-type]
        capture_public_key_path=fixture["executor_public"],  # type: ignore[arg-type]
        capture_key_id="executor-test-v1",
        repository_root=fixture["repository"],  # type: ignore[arg-type]
    )
    assert capture_validation["status"] == "pass"
    assert capture_validation["signature_status"] == "verified"

    attestation = json.loads(
        (evidence / "capture-a" / "persistence-attestation.json").read_text()
    )
    plan = build_provider_call_plan(
        fixture["manifest"],  # type: ignore[arg-type]
        fixture["config"],  # type: ignore[arg-type]
        fixture["workload"],  # type: ignore[arg-type]
        repository_root=fixture["repository"],  # type: ignore[arg-type]
    )
    persistence_validation = verify_persistence_attestation(
        attestation,
        config=json.loads(Path(fixture["config"]).read_text()),
        repository_root=fixture["repository"],  # type: ignore[arg-type]
        config_sha256=plan["config_sha256"],
        workload_sha256=plan["workload_sha256"],
        workload_id="capture-producer-workload-v1",
        corpus_id="capture-producer-fixture-v1",
        expected_corpus_run_id="capture-producer-run-v1",
        expected_result_set=selected,
    )
    assert persistence_validation["status"] == "pass"
    assert persistence_validation["signature"]["status"] == "verified"


def test_cli_summary_output_cannot_escape_evidence_root(tmp_path: Path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    outside_summary = tmp_path / "outside-summary.json"
    command = [
        sys.executable,
        "scripts/run_frozen_corpus_capture.py",
        "--evidence-root",
        str(evidence),
        "--source-dir",
        str(evidence / "sources"),
        "--execution-bundle",
        str(evidence / "bundle.json"),
        "--persistence-observations",
        str(evidence / "persistence.json"),
        "--output-dir",
        str(evidence / "capture"),
        "--executor-private-key",
        str(tmp_path / "executor.key"),
        "--canonical-api-private-key",
        str(tmp_path / "api.key"),
        "--commit-sha",
        "a" * 40,
        "--attestation-id",
        "test-attestation",
        "--summary-out",
        str(outside_summary),
    ]
    result = subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[1],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "escapes the evidence root" in result.stdout
    assert not outside_summary.exists()

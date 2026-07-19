from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from scripts import plan_frozen_corpus_capture
from scripts import prepare_frozen_corpus_review
from scripts import run_frozen_corpus_gate
from scripts import verify_external_beta_release
from scripts import verify_frozen_corpus_release


ROOT = Path(__file__).resolve().parents[1]


def _set_argv(
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
    arguments: list[str],
) -> None:
    monkeypatch.setattr(sys, "argv", [module.__file__ or module.__name__, *arguments])


def test_capture_plan_output_is_retained_without_recomputation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    output = tmp_path / "capture-plan.json"
    calls = 0

    def fake_validate(*_args: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {"status": "pass", "provider_calls": 0}

    monkeypatch.setattr(
        plan_frozen_corpus_capture,
        "validate_workload_definition",
        fake_validate,
    )
    _set_argv(
        monkeypatch,
        plan_frozen_corpus_capture,
        ["--out", str(output), "validate-definition"],
    )

    assert plan_frozen_corpus_capture.main() == 0
    retained = output.read_bytes()
    assert json.loads(retained) == {"provider_calls": 0, "status": "pass"}

    with pytest.raises(ValueError, match="retained artifact already exists"):
        plan_frozen_corpus_capture.main()

    assert calls == 1
    assert output.read_bytes() == retained


def test_capture_plan_subprocess_returns_stable_collision_json(tmp_path: Path):
    output = tmp_path / "capture-plan.json"
    output.write_bytes(b"signed-existing-plan")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/plan_frozen_corpus_capture.py",
            "--out",
            str(output),
            "validate-definition",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    result = json.loads(completed.stdout)
    assert result["schema_version"] == "facetta-retained-evidence-error.v1"
    assert result["provider_calls"] == 0
    assert "retained artifact already exists" in result["error"]
    assert output.read_bytes() == b"signed-existing-plan"


def test_review_packet_output_is_retained_without_recomputation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    output = evidence_root / "packets" / "review.json"
    output.parent.mkdir()
    calls = 0

    def fake_prepare(*_args: object, **_kwargs: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {
            "packet_status": "ready",
            "attempts": [],
            "quality_scope": {
                "source_count": 58,
                "evaluation_sequence_count": 1102,
            },
            "integrity_prerequisite": {"status": "pass"},
        }

    monkeypatch.setattr(
        prepare_frozen_corpus_review,
        "prepare_frozen_corpus_review_packet",
        fake_prepare,
    )
    _set_argv(
        monkeypatch,
        prepare_frozen_corpus_review,
        [
            "--source-dir", str(evidence_root / "sources"),
            "--capture", str(evidence_root / "capture.json"),
            "--capture-public-key", str(evidence_root / "capture.pub"),
            "--capture-key-id", "capture-key-v1",
            "--evidence-root", str(evidence_root),
            "--out", "packets/review.json",
        ],
    )

    assert prepare_frozen_corpus_review.main() == 0
    retained = output.read_bytes()
    assert json.loads(retained)["packet_status"] == "ready"

    with pytest.raises(ValueError, match="retained artifact already exists"):
        prepare_frozen_corpus_review.main()

    assert calls == 1
    assert output.read_bytes() == retained


def _passing_gate_result() -> dict[str, object]:
    return {
        "status": "pass",
        "corpus_gate_ready": True,
        "definition": {"status": "pass"},
        "workload": {
            "status": "pass",
            "quality_source_count": 58,
            "integrity_source_count": 144,
        },
        "source_integrity": {"status": "pass", "verified": 144, "expected": 144},
        "quality": {
            "status": "pass",
            "source_coverage": {
                "completed_source_count": 58,
                "expected_source_count": 58,
            },
            "classified_release_gates": {
                "quick_appearance": {
                    "gia_acceptance_rate": 0.95,
                    "pass": True,
                },
                "structural": {"pass": True},
            },
        },
    }


def test_corpus_gate_writes_one_retained_batch_and_preflights_both_outputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    (evidence_root / "gate-complete").mkdir()
    calls = 0

    def fake_compile(*_args: object, **_kwargs: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return _passing_gate_result()

    monkeypatch.setattr(
        run_frozen_corpus_gate, "compile_frozen_corpus_gate", fake_compile,
    )
    _set_argv(
        monkeypatch,
        run_frozen_corpus_gate,
        [
            "--evidence-root", str(evidence_root),
            "--source-dir", str(evidence_root / "sources"),
            "--outdir", "gate-complete",
        ],
    )

    assert run_frozen_corpus_gate.main() == 0
    results = evidence_root / "gate-complete" / "results.json"
    report = evidence_root / "gate-complete" / "report.md"
    retained_results = results.read_bytes()
    retained_report = report.read_bytes()
    assert json.loads(retained_results)["corpus_gate_ready"] is True
    assert b"# Frozen founder corpus gate" in retained_report

    partial = evidence_root / "gate-partial"
    partial.mkdir()
    existing_report = partial / "report.md"
    existing_report.write_bytes(b"signed-existing-report")
    _set_argv(
        monkeypatch,
        run_frozen_corpus_gate,
        [
            "--evidence-root", str(evidence_root),
            "--source-dir", str(evidence_root / "sources"),
            "--outdir", "gate-partial",
        ],
    )

    with pytest.raises(ValueError, match="retained artifact already exists"):
        run_frozen_corpus_gate.main()

    assert calls == 1
    assert not (partial / "results.json").exists()
    assert existing_report.read_bytes() == b"signed-existing-report"
    assert results.read_bytes() == retained_results
    assert report.read_bytes() == retained_report


def test_failed_corpus_release_decision_is_retained_without_recomputation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    output = evidence_root / "corpus-release" / "final-decision.json"
    output.parent.mkdir()
    calls = 0

    def fake_verify(*_args: object, **_kwargs: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {
            "status": "blocked",
            "corpus_gate_ready": False,
            "reasons": ["founder approval is absent"],
        }

    monkeypatch.setattr(
        verify_frozen_corpus_release, "verify_frozen_corpus_release", fake_verify,
    )
    _set_argv(
        monkeypatch,
        verify_frozen_corpus_release,
        [
            "--results", str(evidence_root / "results.json"),
            "--approval", str(evidence_root / "approval.json"),
            "--manifest", str(evidence_root / "manifest.json"),
            "--source-dir", str(evidence_root / "sources"),
            "--evidence", str(evidence_root / "evidence.json"),
            "--evidence-root", str(evidence_root),
            "--workload", str(evidence_root / "workload.json"),
            "--gia-review-packet", str(evidence_root / "gia-packet.json"),
            "--gia-review-ledger", str(evidence_root / "gia-ledger.json"),
            "--outdir", "corpus-release",
        ],
    )

    assert verify_frozen_corpus_release.main() == 1
    retained = output.read_bytes()
    assert json.loads(retained)["corpus_gate_ready"] is False

    with pytest.raises(ValueError, match="retained artifact already exists"):
        verify_frozen_corpus_release.main()

    assert calls == 1
    assert output.read_bytes() == retained


def test_failed_external_beta_decision_is_retained_without_recomputation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    output = evidence_root / "external-release" / "external-beta-decision.json"
    output.parent.mkdir()
    calls = 0
    observed_kwargs: dict[str, object] = {}

    def fake_verify(*_args: object, **kwargs: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        observed_kwargs.update(kwargs)
        return {
            "status": "blocked",
            "external_beta_ready": False,
            "reasons": ["staging approval is absent"],
        }

    monkeypatch.setattr(
        verify_external_beta_release, "verify_external_beta_release", fake_verify,
    )
    _set_argv(
        monkeypatch,
        verify_external_beta_release,
        [
            "--corpus-decision", str(evidence_root / "corpus-decision.json"),
            "--corpus-results", str(evidence_root / "corpus-results.json"),
            "--corpus-approval", str(evidence_root / "corpus-approval.json"),
            "--corpus-exit-code", str(evidence_root / "corpus-exit.txt"),
            "--corpus-manifest", str(evidence_root / "manifest.json"),
            "--corpus-source-dir", str(evidence_root / "sources"),
            "--corpus-evidence", str(evidence_root / "evidence.json"),
            "--corpus-evidence-root", str(evidence_root),
            "--corpus-workload", str(evidence_root / "workload.json"),
            "--gia-review-packet", str(evidence_root / "gia-packet.json"),
            "--gia-review-ledger", str(evidence_root / "gia-ledger.json"),
            "--designer-review-packet", str(evidence_root / "designer-packet.json"),
            "--designer-review-ledger", str(evidence_root / "designer-ledger.json"),
            "--staging-results", str(evidence_root / "staging-results.json"),
            "--staging-approval", str(evidence_root / "staging-approval.json"),
            "--staging-exit-code", str(evidence_root / "staging-exit.txt"),
            "--staging-run-id", "staging-run-fixture-v1",
            "--external-release-run-id", "external-release-fixture-v1",
            "--outdir", "external-release",
        ],
    )

    assert verify_external_beta_release.main() == 1
    retained = output.read_bytes()
    assert json.loads(retained)["external_beta_ready"] is False

    with pytest.raises(ValueError, match="retained artifact already exists"):
        verify_external_beta_release.main()

    assert calls == 1
    assert observed_kwargs["staging_run_id"] == "staging-run-fixture-v1"
    assert (
        observed_kwargs["external_release_run_id"]
        == "external-release-fixture-v1"
    )
    assert output.read_bytes() == retained

from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from facetta.blind_jewelry_review import (
    BLIND_REVIEW_LEDGER_SCHEMA,
    INDEPENDENT_DESIGNER_ROLE,
    blind_review_packet_sha256,
    build_blind_review_packet,
    canonical_review_ledger_payload,
)
from facetta.external_beta_release import (
    _selected_quick_appearance_scope,
    canonical_staging_approval_payload,
    required_staging_checks,
    verify_external_beta_release,
)


def test_designer_scope_counts_reviewed_not_applicable_rows_as_resolved(
    tmp_path: Path,
):
    replay = tmp_path / "replay.json"
    _json(replay, {
        "attempts": [{
            "kind": "edit",
            "operation_class": "quick_appearance",
            "source_filename": "ring-a.png",
            "evaluation_id": "metal-color",
            "accepted": True,
            "source_image_sha256": "1" * 64,
            "candidate_image_sha256": "2" * 64,
            "mask_image_sha256": "3" * 64,
        }],
        "not_applicable_assignments": [{
            "kind": "edit",
            "operation_class": "quick_appearance",
            "source_filename": "ring-b.png",
            "evaluation_id": "metal-color",
        }],
    })
    expected = {("ring-a.png", "metal-color"), ("ring-b.png", "metal-color")}
    errors: list[str] = []
    scope = _selected_quick_appearance_scope(
        replay, tmp_path, expected, errors,
    )
    assert errors == []
    assert scope == [("1" * 64, "2" * 64, "3" * 64)]

    raw = json.loads(replay.read_text())
    raw["not_applicable_assignments"] = []
    _json(replay, raw)
    errors = []
    _selected_quick_appearance_scope(replay, tmp_path, expected, errors)
    assert "signed replay resolved scope does not exactly cover quick appearance" in (
        errors
    )


def _json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> dict[str, Any]:
    reviewer_private = Ed25519PrivateKey.generate()
    designer_private = Ed25519PrivateKey.generate()
    reviewer_public = tmp_path / "staging-reviewer.pub"
    reviewer_public.write_bytes(reviewer_private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ))
    designer_public = tmp_path / "designer-reviewer.pub"
    designer_public.write_bytes(designer_private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ))
    components = tmp_path / "components"
    components.mkdir()
    verifier = components / "external_beta_release.py"
    verifier.write_text("# frozen external beta verifier\n")
    staging_probe = components / "run_staging_two_user_isolation.py"
    staging_probe.write_text("# frozen staging probe\n")
    verifier_cli = components / "verify_external_beta_release.py"
    verifier_cli.write_text("# frozen external beta verifier CLI\n")
    workload = tmp_path / "workload.json"
    _json(workload, {
        "schema_version": "facetta-frozen-capture-workload.v1",
        "ring_quality_evaluation_set_id": "ring-v1",
        "evaluation_sets": {
            "ring-v1": [
                {
                    "kind": "edit",
                    "evaluation_id": "metal-color",
                    "operation_class": "quick_appearance",
                },
            ],
        },
        "sources": [
            {
                "filename": filename,
                "quality": {"slice": "ring", "evaluation_set_id": "ring-v1"},
            }
            for filename in ("ring-a.png", "ring-b.png")
        ],
    })

    config = tmp_path / "config.json"
    _json(config, {
        "schema_version": "facetta-frozen-gate-config.v1",
        "config_id": "fixture-config",
        "thresholds": {
            "quick_appearance_designer_acceptance_rate": 0.9,
            "max_staging_evidence_age_hours": 24,
        },
        "frozen_components": {
            "external_beta_release_verifier": (
                f"components/{verifier.name}@sha256:{_sha(verifier)}"
            ),
            "staging_isolation_probe": (
                f"components/{staging_probe.name}@sha256:{_sha(staging_probe)}"
            ),
            "external_beta_release_cli": (
                f"components/{verifier_cli.name}@sha256:{_sha(verifier_cli)}"
            ),
            "capture_workload": f"{workload.name}@sha256:{_sha(workload)}",
        },
        "staging_reviewer_public_key": {
            "key_id": "staging-reviewer-v1",
            "path": reviewer_public.name,
            "sha256": _sha(reviewer_public),
        },
        "designer_reviewer_public_key": {
            "key_id": "designer-reviewer-v1",
            "path": designer_public.name,
            "sha256": _sha(designer_public),
            "reviewer_profile_sha256": "f" * 64,
        },
    })

    corpus_results = tmp_path / "corpus-results.json"
    corpus_approval = tmp_path / "corpus-approval.json"
    _json(corpus_results, {
        "fixture": "signed result input",
        "quality": {
            "classified_release_gates": {
                "quick_appearance": {
                    "evaluation_count": 2,
                    "designer_accepted_count": 2,
                    "designer_acceptance_rate": 1.0,
                    "threshold": 0.9,
                    "pass": True,
                },
            },
            "release_gates": {
                "all_localized_edits_within_three_attempts": True,
            },
        },
    })
    _json(corpus_approval, {"fixture": "signed founder input"})
    corpus_exit = tmp_path / "corpus-exit-code.txt"
    corpus_exit.write_text("0\n")
    corpus_manifest = tmp_path / "manifest.json"
    _json(corpus_manifest, {"fixture": "manifest"})
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    corpus_source_dir = evidence_root / "sources"
    corpus_source_dir.mkdir()
    corpus_evidence = evidence_root / "signed-replay.json"
    gia_review_packet = evidence_root / "gia-blind-packet.json"
    gia_review_ledger = evidence_root / "gia-criterion-ledger.json"
    _json(gia_review_packet, {"fixture": "GIA packet is verified downstream"})
    _json(gia_review_ledger, {"fixture": "GIA ledger is verified downstream"})
    selected_hashes = [
        ("1" * 64, "3" * 64, "5" * 64),
        ("2" * 64, "4" * 64, "6" * 64),
    ]
    _json(corpus_evidence, {
        "attempts": [
            {
                "kind": "edit",
                "operation_class": "quick_appearance",
                "evaluation_id": "metal-color",
                "source_filename": filename,
                "accepted": True,
                "source_image_sha256": hashes[0],
                "candidate_image_sha256": hashes[1],
                "mask_image_sha256": hashes[2],
            }
            for filename, hashes in zip(
                ("ring-a.png", "ring-b.png"), selected_hashes, strict=True,
            )
        ],
    })
    corpus_decision_value = {
        "schema_version": "facetta-frozen-corpus-release-decision.v2",
        "status": "pass",
        "corpus_gate_ready": True,
        "provider_calls": 0,
        "gate_bindings": {
            "config_sha256": _sha(config),
            "corpus_run_id": "fixture-corpus-run-v1",
            "manifest_sha256": "a" * 64,
            "workload_sha256": _sha(workload),
            "capture_sha256": "b" * 64,
        },
        "founder_signature": {"status": "verified", "key_id": "founder-v1"},
        "errors": [],
    }
    corpus_decision = tmp_path / "corpus-final-decision.json"
    _json(corpus_decision, corpus_decision_value)

    checks = [
        {"name": name, "expected": expected, "observed": expected, "passed": True}
        for name, expected in required_staging_checks().items()
    ]
    staging_results = tmp_path / "staging-results.json"
    now = datetime.now(UTC)
    probed_at = (now - timedelta(minutes=30)).isoformat()
    approved_at = (now - timedelta(minutes=15)).isoformat()
    _json(staging_results, {
        "schema_version": "facetta-staging-isolation.v6",
        "run_kind": "read_only_two_principal_staging_probe",
        "target": {
            "staging_run_id": "staging-run-fixture-v1",
            "external_release_run_id": "external-release-fixture-v1",
            "origin_sha256": "a" * 64,
            "deployment_revision": "0123456789abcdef",
            "fixture_set_sha256": "b" * 64,
            "probed_at": probed_at,
            "transport": "live_https",
        },
        "checks": checks,
        "passed": True,
        "secrets_logged": False,
        "provider_calls": 0,
        "mutations": 0,
    })
    staging_exit = tmp_path / "staging-exit-code.txt"
    staging_exit.write_text("0\n")
    designer_packet = tmp_path / "designer-blind-packet.json"
    packet_value = build_blind_review_packet(
        corpus_run_id="fixture-corpus-run-v1",
        manifest_sha256="a" * 64,
        config_sha256=_sha(config),
        workload_sha256=_sha(workload),
        capture_sha256="b" * 64,
        reviewer_role=INDEPENDENT_DESIGNER_ROLE,
        review_seed="c" * 64,
        selected_items=[
            {
                "kind": "edit",
                "operation_class": "quick_appearance",
                "intent": {
                    "intended_change": "Change yellow gold to white gold.",
                    "target_region": "all visible metal",
                    "frozen_facts": ["stone count", "setting geometry"],
                },
                "source": {
                    "path": f"sources/{filename}", "sha256": hashes[0],
                },
                "candidate": {
                    "path": f"review/{filename}", "sha256": hashes[1],
                },
                "mask": {
                    "path": f"review/{filename}.mask.png", "sha256": hashes[2],
                },
            }
            for filename, hashes in zip(
                ("ring-a.png", "ring-b.png"), selected_hashes, strict=True,
            )
        ],
    )
    _json(designer_packet, packet_value)
    designer_ledger = tmp_path / "designer-criterion-ledger.json"
    staging_approval = tmp_path / "staging-approval.json"

    paths: dict[str, Any] = {
        "root": tmp_path,
        "private": reviewer_private,
        "designer_private": designer_private,
        "verifier": verifier,
        "staging_probe": staging_probe,
        "verifier_cli": verifier_cli,
        "config": config,
        "corpus_results": corpus_results,
        "corpus_approval": corpus_approval,
        "corpus_exit": corpus_exit,
        "corpus_manifest": corpus_manifest,
        "corpus_source_dir": corpus_source_dir,
        "corpus_evidence": corpus_evidence,
        "gia_review_packet": gia_review_packet,
        "gia_review_ledger": gia_review_ledger,
        "evidence_root": evidence_root,
        "workload": workload,
        "corpus_decision": corpus_decision,
        "corpus_decision_value": corpus_decision_value,
        "staging_results": staging_results,
        "staging_exit": staging_exit,
        "designer_packet": designer_packet,
        "designer_ledger": designer_ledger,
        "staging_approval": staging_approval,
        "approved_at": approved_at,
    }
    _sign_designer_ledger(paths)
    _sign_staging_approval(paths)
    return paths


def _sign_staging_approval(paths: dict[str, Any]) -> None:
    staging = json.loads(paths["staging_results"].read_text())
    value: dict[str, Any] = {
        "schema_version": "facetta-staging-isolation-approval.v2",
        "staging_results_sha256": _sha(paths["staging_results"]),
        "staging_exit_code_sha256": _sha(paths["staging_exit"]),
        "decision": "approved",
        "reviewer": "Test Release Reviewer",
        "approved_at": paths["approved_at"],
        "release_ticket": "FACETTA-STAGING-1",
        "staging_run_id": staging["target"]["staging_run_id"],
        "external_release_run_id": staging["target"]["external_release_run_id"],
        "origin_sha256": staging["target"]["origin_sha256"],
        "deployment_revision": staging["target"]["deployment_revision"],
        "fixture_set_sha256": staging["target"]["fixture_set_sha256"],
    }
    value["signature"] = {
        "algorithm": "Ed25519",
        "key_id": "staging-reviewer-v1",
        "value": base64.b64encode(
            paths["private"].sign(canonical_staging_approval_payload(value))
        ).decode("ascii"),
    }
    _json(paths["staging_approval"], value)


def _sign_designer_ledger(
    paths: dict[str, Any],
    *,
    failed_item_indexes: set[int] | None = None,
) -> None:
    packet = json.loads(paths["designer_packet"].read_text())
    failed = failed_item_indexes or set()
    decisions = []
    for index, item in enumerate(packet["items"]):
        artifacts = item["artifacts"]
        criteria = []
        for criterion_index, criterion in enumerate(item["criteria"]):
            rating = (
                "fail" if index in failed and criterion_index == 0 else "pass"
            )
            criteria.append({
                "criterion_id": criterion["criterion_id"],
                "rating": rating,
                "rationale": (
                    "Requested appearance was not achieved."
                    if rating == "fail" else None
                ),
            })
        decisions.append({
            "item_id": item["item_id"],
            "selected_source_sha256": artifacts["source"]["sha256"],
            "selected_candidate_sha256": artifacts["candidate"]["sha256"],
            "selected_mask_sha256": (
                artifacts["mask"]["sha256"]
                if artifacts["mask"] is not None else None
            ),
            "criteria": criteria,
        })
    value: dict[str, Any] = {
        "schema_version": BLIND_REVIEW_LEDGER_SCHEMA,
        "blind_packet_sha256": blind_review_packet_sha256(packet),
        "reviewer_id": "independent-designer-fixture-1",
        "reviewer_role": INDEPENDENT_DESIGNER_ROLE,
        "reviewer_profile_sha256": "f" * 64,
        "review_timezone": "Asia/Shanghai",
        "reviewed_at": "2026-07-13T12:15:00+08:00",
        "decisions": decisions,
        "signature": None,
    }
    value["signature"] = {
        "algorithm": "Ed25519",
        "key_id": "designer-reviewer-v1",
        "value": base64.b64encode(paths["designer_private"].sign(
            canonical_review_ledger_payload(value)
        )).decode("ascii"),
    }
    _json(paths["designer_ledger"], value)


def _verify(
    paths: dict[str, Any],
    corpus_verifier=None,
    authority_verifier=None,
    *,
    staging_run_id: str = "staging-run-fixture-v1",
    external_release_run_id: str = "external-release-fixture-v1",
) -> dict[str, Any]:
    if corpus_verifier is None:
        expected = paths["corpus_decision_value"]

        def corpus_verifier(*args, **kwargs):
            return expected

    if authority_verifier is None:
        def authority_verifier(config, repository_root, decision_time):
            return {
                "schema_version": (
                    "facetta-release-authority-bundle-decision.v1"
                ),
                "status": "pass",
                "decision_time": decision_time.isoformat(),
                "verification_policy": "facetta-release-authority-policy-v1",
                "status_list": {"artifact_sha256": "e" * 64},
                "authorities": [
                    {"role": role, "enrollment_artifact_sha256": "d" * 64}
                    for role in (
                        "executor", "canonical_api_runner", "gia_reviewer",
                        "founder", "jewelry_designer", "staging_reviewer",
                    )
                ],
                "errors": [],
            }

    return verify_external_beta_release(
        paths["corpus_decision"],
        paths["corpus_results"],
        paths["corpus_approval"],
        paths["corpus_exit"],
        paths["config"],
        paths["designer_packet"],
        paths["designer_ledger"],
        paths["staging_results"],
        paths["staging_approval"],
        paths["staging_exit"],
        staging_run_id=staging_run_id,
        external_release_run_id=external_release_run_id,
        repository_root=paths["root"],
        corpus_manifest_path=paths["corpus_manifest"],
        corpus_source_dir=paths["corpus_source_dir"],
        corpus_evidence_path=paths["corpus_evidence"],
        corpus_evidence_root=paths["evidence_root"],
        corpus_workload_path=paths["workload"],
        gia_review_packet_path=paths["gia_review_packet"],
        gia_review_ledger_path=paths["gia_review_ledger"],
        corpus_verifier=corpus_verifier,
        authority_verifier=authority_verifier,
    )


def test_exact_reverified_corpus_and_signed_staging_pass_together(tmp_path: Path):
    paths = _fixture(tmp_path)
    result = _verify(paths)
    assert result["schema_version"] == "facetta-external-beta-release-decision.v2"
    assert result["external_beta_ready"] is True
    assert result["status"] == "pass"
    json.dumps(result)
    assert result["provider_calls"] == 0
    assert result["mutations"] == 0
    assert result["signatures"]["founder"]["status"] == "verified"
    assert result["signatures"]["designer"]["status"] == "verified"
    assert result["signatures"]["staging_reviewer"]["status"] == "verified"
    assert result["gate_bindings"]["deployment_revision"] == "0123456789abcdef"
    assert result["gate_bindings"]["staging_run_id"] == "staging-run-fixture-v1"
    assert (
        result["gate_bindings"]["external_release_run_id"]
        == "external-release-fixture-v1"
    )
    assert result["release_authority_bundle"]["status"] == "pass"
    assert (
        result["release_authority_bundle"]["status_list"]["artifact_sha256"]
        == "e" * 64
    )
    assert len(result["release_authority_bundle"]["authorities"]) == 6
    assert result["independent_designer_review"] == {
        "status": "pass",
        "evaluation_count": 2,
        "accepted_count": 2,
        "acceptance_rate": 1.0,
        "threshold": 0.9,
        "within_three_attempts": True,
    }


def test_external_verifier_passes_exact_raw_inputs_to_corpus_reverification(
    tmp_path: Path,
):
    paths = _fixture(tmp_path)
    called: dict[str, Any] = {}

    def corpus_spy(*args, **kwargs):
        called.update(kwargs)
        return paths["corpus_decision_value"]

    result = _verify(paths, corpus_spy)

    assert result["external_beta_ready"] is True
    assert called == {
        "repository_root": paths["root"],
        "manifest_path": paths["corpus_manifest"],
        "source_dir": paths["corpus_source_dir"],
        "evidence_path": paths["corpus_evidence"],
        "evidence_root": paths["evidence_root"],
        "workload_path": paths["workload"],
        "review_packet_path": paths["gia_review_packet"],
        "review_ledger_path": paths["gia_review_ledger"],
    }


def test_legacy_v1_designer_booleans_are_parseable_but_never_authoritative(
    tmp_path: Path,
):
    paths = _fixture(tmp_path)
    _json(paths["designer_packet"], {
        "schema_version": "facetta-designer-acceptance-decisions.v1",
        "completed": True,
        "decisions": [{"accepted": True}],
    })
    _json(paths["designer_ledger"], {
        "schema_version": "facetta-designer-acceptance-approval.v1",
        "decision": "approved",
    })

    result = _verify(paths)

    assert result["external_beta_ready"] is False
    assert any(
        "unsupported blind-review packet schema_version" in error
        for error in result["errors"]
    )


def test_acceptance_is_derived_from_signed_criterion_outcomes(tmp_path: Path):
    paths = _fixture(tmp_path)
    _sign_designer_ledger(paths, failed_item_indexes={0})

    result = _verify(paths)

    assert result["signatures"]["designer"]["status"] == "verified"
    assert result["independent_designer_review"]["accepted_count"] == 1
    assert result["independent_designer_review"]["acceptance_rate"] == 0.5
    assert result["external_beta_ready"] is False
    assert any("criterion acceptance" in error for error in result["errors"])


def test_quick_appearance_rate_ignores_other_valid_designer_packet_items(
    tmp_path: Path,
):
    paths = _fixture(tmp_path)
    original = json.loads(paths["designer_packet"].read_text())
    selected_items = [
        {
            "kind": item["kind"],
            "operation_class": item["operation_class"],
            "intent": item["intent"],
            "source": item["artifacts"]["source"],
            "candidate": item["artifacts"]["candidate"],
            "mask": item["artifacts"]["mask"],
        }
        for item in original["items"]
    ]
    selected_items.append({
        "kind": "render",
        "operation_class": "render_conformance",
        "intent": {
            "intended_change": "Review the complete ring presentation.",
            "target_region": None,
            "frozen_facts": ["stone count", "setting geometry"],
        },
        "source": {"path": "sources/render.png", "sha256": "7" * 64},
        "candidate": {"path": "review/render.png", "sha256": "8" * 64},
        "mask": None,
    })
    packet = build_blind_review_packet(
        corpus_run_id=original["corpus_run_id"],
        manifest_sha256=original["evidence_binding"]["manifest_sha256"],
        config_sha256=original["evidence_binding"]["config_sha256"],
        workload_sha256=original["evidence_binding"]["workload_sha256"],
        capture_sha256=original["evidence_binding"]["capture_sha256"],
        reviewer_role=INDEPENDENT_DESIGNER_ROLE,
        review_seed=original["review_protocol"]["review_seed"],
        selected_items=selected_items,
    )
    _json(paths["designer_packet"], packet)
    failed_render_index = next(
        index
        for index, item in enumerate(packet["items"])
        if item["kind"] == "render"
    )
    _sign_designer_ledger(paths, failed_item_indexes={failed_render_index})

    result = _verify(paths)

    assert result["external_beta_ready"] is True
    assert result["independent_designer_review"] == {
        "status": "pass",
        "evaluation_count": 2,
        "accepted_count": 2,
        "acceptance_rate": 1.0,
        "threshold": 0.9,
        "within_three_attempts": True,
    }


def test_reviewer_supplied_accepted_boolean_is_rejected_even_when_resigned(
    tmp_path: Path,
):
    paths = _fixture(tmp_path)
    ledger = json.loads(paths["designer_ledger"].read_text())
    ledger["decisions"][0]["accepted"] = True
    ledger["signature"] = {
        "algorithm": "Ed25519",
        "key_id": "designer-reviewer-v1",
        "value": base64.b64encode(paths["designer_private"].sign(
            canonical_review_ledger_payload(ledger)
        )).decode("ascii"),
    }
    _json(paths["designer_ledger"], ledger)

    result = _verify(paths)

    assert result["external_beta_ready"] is False
    assert any(
        "decision has unexpected or missing fields" in error
        for error in result["errors"]
    )


def test_packet_must_match_exact_selected_source_candidate_and_mask_hashes(
    tmp_path: Path,
):
    paths = _fixture(tmp_path)
    replay = json.loads(paths["corpus_evidence"].read_text())
    replay["attempts"][0]["candidate_image_sha256"] = "9" * 64
    _json(paths["corpus_evidence"], replay)

    result = _verify(paths)

    assert result["external_beta_ready"] is False
    assert any("artifact hashes do not exactly match" in error for error in result["errors"])


def test_designer_packet_must_bind_exact_corpus_evidence(tmp_path: Path):
    paths = _fixture(tmp_path)
    packet = json.loads(paths["designer_packet"].read_text())
    packet["evidence_binding"]["capture_sha256"] = "9" * 64
    _json(paths["designer_packet"], packet)

    result = _verify(paths)

    assert result["external_beta_ready"] is False
    assert any("exact frozen-corpus evidence" in error for error in result["errors"])


def test_designer_profile_must_be_hash_enrolled_outside_the_ledger(
    tmp_path: Path,
):
    paths = _fixture(tmp_path)
    config = json.loads(paths["config"].read_text())
    config["designer_reviewer_public_key"].pop("reviewer_profile_sha256")
    _json(paths["config"], config)

    result = _verify(paths)

    assert result["external_beta_ready"] is False
    assert any("profile is not hash-enrolled" in error for error in result["errors"])


def test_complete_six_role_authority_bundle_is_mandatory(tmp_path: Path):
    paths = _fixture(tmp_path)
    observed_time = None

    def failed_authorities(config, repository_root, decision_time):
        nonlocal observed_time
        observed_time = decision_time
        return {
            "status": "fail",
            "authorities": [{"role": "founder"}],
            "errors": ["qualification expired"],
        }

    result = _verify(paths, authority_verifier=failed_authorities)

    assert observed_time is not None
    assert observed_time.tzinfo is not None
    assert observed_time.utcoffset().total_seconds() == 0
    assert result["external_beta_ready"] is False
    assert any("six-role" in error for error in result["errors"])


def test_staging_result_tamper_breaks_exact_approval_binding(tmp_path: Path):
    paths = _fixture(tmp_path)
    value = json.loads(paths["staging_results"].read_text())
    value["operator_note"] = "changed after approval"
    _json(paths["staging_results"], value)
    result = _verify(paths)
    assert result["external_beta_ready"] is False
    assert any("exact result bytes" in error for error in result["errors"])


def test_staging_evidence_cannot_be_replayed_under_different_run_ids(
    tmp_path: Path,
):
    paths = _fixture(tmp_path)

    result = _verify(
        paths,
        staging_run_id="staging-run-replay-v2",
        external_release_run_id="external-release-replay-v2",
    )

    assert result["external_beta_ready"] is False
    assert any("result staging_run_id differs" in error for error in result["errors"])
    assert any(
        "result external_release_run_id differs" in error
        for error in result["errors"]
    )
    assert any("approval staging_run_id differs" in error for error in result["errors"])
    assert any(
        "approval external_release_run_id differs" in error
        for error in result["errors"]
    )


def test_signed_staging_approval_cannot_target_a_different_release_run(
    tmp_path: Path,
):
    paths = _fixture(tmp_path)
    approval = json.loads(paths["staging_approval"].read_text())
    approval["external_release_run_id"] = "external-release-other-v2"
    approval["signature"] = {
        "algorithm": "Ed25519",
        "key_id": "staging-reviewer-v1",
        "value": base64.b64encode(
            paths["private"].sign(canonical_staging_approval_payload(approval))
        ).decode("ascii"),
    }
    _json(paths["staging_approval"], approval)

    result = _verify(paths)

    assert result["signatures"]["staging_reviewer"]["status"] == "verified"
    assert result["external_beta_ready"] is False
    assert any(
        "external_release_run_id differs from the tested target" in error
        for error in result["errors"]
    )


def test_staging_evidence_older_than_frozen_limit_fails_closed(tmp_path: Path):
    paths = _fixture(tmp_path)
    staging = json.loads(paths["staging_results"].read_text())
    staging["target"]["probed_at"] = (
        datetime.now(UTC) - timedelta(hours=25)
    ).isoformat()
    _json(paths["staging_results"], staging)
    paths["approved_at"] = (
        datetime.now(UTC) - timedelta(hours=24, minutes=30)
    ).isoformat()
    _sign_staging_approval(paths)

    result = _verify(paths)

    assert result["external_beta_ready"] is False
    assert any("exceeds the frozen maximum age" in error for error in result["errors"])


def test_staging_probe_and_approval_timestamps_must_be_ordered_and_not_future(
    tmp_path: Path,
):
    paths = _fixture(tmp_path)
    staging = json.loads(paths["staging_results"].read_text())
    staging["target"]["probed_at"] = (
        datetime.now(UTC) + timedelta(minutes=30)
    ).isoformat()
    _json(paths["staging_results"], staging)
    paths["approved_at"] = (
        datetime.now(UTC) + timedelta(minutes=15)
    ).isoformat()
    _sign_staging_approval(paths)

    result = _verify(paths)

    assert result["external_beta_ready"] is False
    assert any("probed_at is in the future" in error for error in result["errors"])
    assert any("approved_at is in the future" in error for error in result["errors"])
    assert any("approval predates the staging probe" in error for error in result["errors"])


def test_frozen_staging_age_policy_cannot_exceed_24_hours(tmp_path: Path):
    paths = _fixture(tmp_path)
    config = json.loads(paths["config"].read_text())
    config["thresholds"]["max_staging_evidence_age_hours"] = 48
    _json(paths["config"], config)

    result = _verify(paths)

    assert result["external_beta_ready"] is False
    assert any("frozen between 0 and 24 hours" in error for error in result["errors"])


def test_shallow_staging_pass_cannot_omit_required_check(tmp_path: Path):
    paths = _fixture(tmp_path)
    value = json.loads(paths["staging_results"].read_text())
    value["checks"] = value["checks"][1:]
    _json(paths["staging_results"], value)
    _sign_staging_approval(paths)
    result = _verify(paths)
    assert result["external_beta_ready"] is False
    assert any("exactly cover" in error for error in result["errors"])


def test_malformed_staging_check_name_fails_closed_without_crashing(tmp_path: Path):
    paths = _fixture(tmp_path)
    value = json.loads(paths["staging_results"].read_text())
    value["checks"][0]["name"] = {"not": "a string"}
    _json(paths["staging_results"], value)
    _sign_staging_approval(paths)
    result = _verify(paths)
    assert result["external_beta_ready"] is False
    assert any("invalid names" in error for error in result["errors"])


def test_corpus_decision_must_equal_fresh_signature_verification(tmp_path: Path):
    paths = _fixture(tmp_path)

    def different_corpus(*args, **kwargs):
        return {**paths["corpus_decision_value"], "corpus_gate_ready": False}

    result = _verify(paths, different_corpus)
    assert result["external_beta_ready"] is False
    assert any("differs from fresh verification" in error for error in result["errors"])


def test_nonzero_retained_exit_code_fails_closed(tmp_path: Path):
    paths = _fixture(tmp_path)
    paths["staging_exit"].write_text("1\n")
    _sign_staging_approval(paths)
    result = _verify(paths)
    assert result["external_beta_ready"] is False
    assert any("did not retain exit code 0" in error for error in result["errors"])


def test_staging_reviewer_signature_must_verify(tmp_path: Path):
    paths = _fixture(tmp_path)
    approval = json.loads(paths["staging_approval"].read_text())
    approval["release_ticket"] = "FACETTA-TAMPERED"
    _json(paths["staging_approval"], approval)
    result = _verify(paths)
    assert result["external_beta_ready"] is False
    assert result["signatures"]["staging_reviewer"]["status"] == "not_verified"


def test_staging_approval_must_bind_exact_fixture_set_even_when_resigned(
    tmp_path: Path,
):
    paths = _fixture(tmp_path)
    approval = json.loads(paths["staging_approval"].read_text())
    approval["fixture_set_sha256"] = "9" * 64
    approval["signature"] = {
        "algorithm": "Ed25519",
        "key_id": "staging-reviewer-v1",
        "value": base64.b64encode(
            paths["private"].sign(canonical_staging_approval_payload(approval))
        ).decode("ascii"),
    }
    _json(paths["staging_approval"], approval)

    result = _verify(paths)

    assert result["signatures"]["staging_reviewer"]["status"] == "verified"
    assert result["external_beta_ready"] is False
    assert any("fixture_set_sha256 differs" in error for error in result["errors"])


def test_designer_criterion_ledger_signature_must_verify(tmp_path: Path):
    paths = _fixture(tmp_path)
    ledger = json.loads(paths["designer_ledger"].read_text())
    ledger["reviewed_at"] = "2026-07-13T12:16:00+08:00"
    _json(paths["designer_ledger"], ledger)
    result = _verify(paths)
    assert result["external_beta_ready"] is False
    assert result["signatures"]["designer"]["status"] == "not_verified"
    assert any("ledger signature is invalid" in error for error in result["errors"])


def test_designer_and_staging_reviewer_cannot_share_public_key(tmp_path: Path):
    paths = _fixture(tmp_path)
    config = json.loads(paths["config"].read_text())
    designer = config["designer_reviewer_public_key"]
    config["staging_reviewer_public_key"] = {
        "key_id": "staging-distinct-label",
        "path": designer["path"],
        "sha256": designer["sha256"],
    }
    _json(paths["config"], config)

    result = _verify(paths)

    separation = result["authority_key_separation"]
    assert separation["status"] == "fail"
    assert any(
        "jewelry_designer, staging_reviewer" in error
        and "public-key bytes" in error
        for error in separation["errors"]
    )
    assert result["external_beta_ready"] is False


def test_frozen_combined_verifier_pin_must_not_drift(tmp_path: Path):
    paths = _fixture(tmp_path)
    paths["verifier"].write_text("# drifted verifier\n")
    result = _verify(paths)
    assert result["external_beta_ready"] is False
    assert any(
        "external_beta_release_verifier implementation drifted" in error
        for error in result["errors"]
    )

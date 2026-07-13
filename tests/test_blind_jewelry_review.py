from __future__ import annotations

import base64
from copy import deepcopy

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from facetta.blind_jewelry_review import (
    BLIND_REVIEW_LEDGER_SCHEMA,
    GIA_VISUAL_FIDELITY_ROLE,
    INDEPENDENT_DESIGNER_ROLE,
    blind_review_packet_sha256,
    build_blind_review_packet,
    canonical_review_ledger_payload,
    criterion_template,
    validate_blind_review_packet,
    validate_signed_review_ledger,
)


def _selected_items() -> list[dict[str, object]]:
    return [
        {
            "kind": "render",
            "operation_class": "render_conformance",
            "intent": {
                "intended_change": "Render the reviewed round solitaire.",
                "target_region": None,
                "frozen_facts": ["round center stone", "four prongs"],
            },
            "source": {"path": "sources/ring.png", "sha256": "1" * 64},
            "candidate": {"path": "review/render.png", "sha256": "2" * 64},
            "mask": None,
        },
        {
            "kind": "edit",
            "operation_class": "quick_appearance",
            "intent": {
                "intended_change": "Change yellow gold to white gold.",
                "target_region": "all visible metal",
                "frozen_facts": ["stone count", "setting geometry"],
            },
            "source": {"path": "sources/ring.png", "sha256": "1" * 64},
            "candidate": {"path": "review/edit.png", "sha256": "3" * 64},
            "mask": {"path": "review/edit-mask.png", "sha256": "4" * 64},
        },
        {
            "kind": "edit",
            "operation_class": "structural",
            "intent": {
                "intended_change": "Widen both shoulders.",
                "target_region": "left and right shoulders",
                "frozen_facts": ["center stone", "prong count"],
            },
            "source": {"path": "sources/ring.png", "sha256": "1" * 64},
            "candidate": {"path": "review/structure.png", "sha256": "5" * 64},
            "mask": {"path": "review/structure-mask.png", "sha256": "6" * 64},
        },
    ]


def _packet(
    *,
    role: str = GIA_VISUAL_FIDELITY_ROLE,
    seed: str = "a" * 64,
) -> dict[str, object]:
    return build_blind_review_packet(
        corpus_run_id="blind-review-fixture-v2",
        manifest_sha256="7" * 64,
        config_sha256="8" * 64,
        workload_sha256="9" * 64,
        capture_sha256="b" * 64,
        reviewer_role=role,
        review_seed=seed,
        selected_items=_selected_items(),
    )


def _ledger(
    packet: dict[str, object],
    private_key: Ed25519PrivateKey,
    *,
    profile_sha256: str = "c" * 64,
) -> dict[str, object]:
    decisions = []
    for item in packet["items"]:  # type: ignore[index]
        artifacts = item["artifacts"]
        decisions.append({
            "item_id": item["item_id"],
            "selected_source_sha256": artifacts["source"]["sha256"],
            "selected_candidate_sha256": artifacts["candidate"]["sha256"],
            "selected_mask_sha256": (
                artifacts["mask"]["sha256"]
                if artifacts["mask"] is not None else None
            ),
            "criteria": [
                {
                    "criterion_id": criterion["criterion_id"],
                    "rating": "pass",
                    "rationale": None,
                }
                for criterion in item["criteria"]
            ],
        })
    ledger: dict[str, object] = {
        "schema_version": BLIND_REVIEW_LEDGER_SCHEMA,
        "blind_packet_sha256": blind_review_packet_sha256(packet),
        "reviewer_id": "reviewer-fixture-17",
        "reviewer_role": packet["review_protocol"]["reviewer_role"],  # type: ignore[index]
        "reviewer_profile_sha256": profile_sha256,
        "review_timezone": "Asia/Shanghai",
        "reviewed_at": "2026-07-13T14:30:00+08:00",
        "decisions": decisions,
        "signature": None,
    }
    ledger["signature"] = {
        "algorithm": "Ed25519",
        "key_id": "reviewer-key-v2",
        "value": base64.b64encode(
            private_key.sign(canonical_review_ledger_payload(ledger))
        ).decode("ascii"),
    }
    return ledger


def _resign(ledger: dict[str, object], private_key: Ed25519PrivateKey) -> None:
    ledger["signature"] = {
        "algorithm": "Ed25519",
        "key_id": "reviewer-key-v2",
        "value": base64.b64encode(
            private_key.sign(canonical_review_ledger_payload(ledger))
        ).decode("ascii"),
    }


def _validate(
    packet: dict[str, object],
    ledger: dict[str, object],
    private_key: Ed25519PrivateKey,
) -> dict[str, object]:
    return validate_signed_review_ledger(
        packet,
        ledger,
        reviewer_public_key=private_key.public_key(),
        reviewer_key_id="reviewer-key-v2",
        expected_reviewer_profile_sha256="c" * 64,
    )


def test_packet_is_opaque_reproducible_and_contains_no_machine_evidence():
    packet = _packet()
    repeated = _packet()

    assert packet == repeated
    assert validate_blind_review_packet(packet)["status"] == "pass"
    assert all(
        item["item_id"].startswith("item_")
        and len(item["item_id"]) == 37
        for item in packet["items"]  # type: ignore[index]
    )
    serialized = str(packet).lower()
    for forbidden in (
        "evaluation_id",
        "source_filename",
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


def test_seed_changes_order_but_not_opaque_item_identity():
    first = _packet(seed="0" * 64)
    first_ids = [item["item_id"] for item in first["items"]]  # type: ignore[index]
    different = None
    for number in range(1, 100):
        candidate = _packet(seed=f"{number:064x}")
        candidate_ids = [
            item["item_id"] for item in candidate["items"]  # type: ignore[index]
        ]
        if candidate_ids != first_ids:
            different = candidate
            break

    assert different is not None
    assert {
        item["item_id"] for item in different["items"]  # type: ignore[index]
    } == set(first_ids)
    assert validate_blind_review_packet(different)["status"] == "pass"


def test_role_and_operation_templates_are_distinct_and_exact():
    gia_quick = criterion_template(
        GIA_VISUAL_FIDELITY_ROLE, "edit", "quick_appearance",
    )
    gia_structural = criterion_template(
        GIA_VISUAL_FIDELITY_ROLE, "edit", "structural",
    )
    designer_quick = criterion_template(
        INDEPENDENT_DESIGNER_ROLE, "edit", "quick_appearance",
    )

    assert gia_quick != gia_structural
    assert gia_quick != designer_quick
    assert {row["criterion_id"] for row in gia_quick} == {
        "intended_change_observable",
        "target_region_control",
        "frozen_facts_preserved",
        "stone_and_setting_integrity",
        "unrelated_drift_and_artifacts_absent",
    }


def test_valid_signed_ledger_derives_acceptance_for_every_item():
    packet = _packet()
    private_key = Ed25519PrivateKey.generate()
    result = _validate(packet, _ledger(packet, private_key), private_key)

    assert result["status"] == "pass"
    assert result["signature_status"] == "verified"
    assert result["accepted_count"] == 3
    assert result["accepted_rate"] == 1.0
    assert all(row["derived_accepted"] for row in result["decisions"])


def test_signed_non_pass_with_rationale_is_valid_but_not_accepted():
    packet = _packet()
    private_key = Ed25519PrivateKey.generate()
    ledger = _ledger(packet, private_key)
    first = ledger["decisions"][0]["criteria"][0]  # type: ignore[index]
    first["rating"] = "not_observable"
    first["rationale"] = "Candidate crop hides the lower setting support."
    _resign(ledger, private_key)

    result = _validate(packet, ledger, private_key)

    assert result["status"] == "pass"
    assert result["accepted_count"] == 2
    assert result["decisions"][0]["derived_accepted"] is False


def test_non_pass_requires_rationale_and_reviewer_cannot_submit_acceptance():
    packet = _packet()
    private_key = Ed25519PrivateKey.generate()
    ledger = _ledger(packet, private_key)
    first_decision = ledger["decisions"][0]  # type: ignore[index]
    first_decision["criteria"][0]["rating"] = "fail"
    first_decision["criteria"][0]["rationale"] = None
    first_decision["accepted"] = True
    _resign(ledger, private_key)

    result = _validate(packet, ledger, private_key)

    assert result["status"] == "fail"
    assert any("unexpected or missing fields" in error for error in result["errors"])
    assert any("requires a rationale" in error for error in result["errors"])
    assert result["decisions"][0]["derived_accepted"] is False


def test_ledger_binds_selected_hashes_profile_timezone_and_signature():
    packet = _packet()
    private_key = Ed25519PrivateKey.generate()
    ledger = _ledger(packet, private_key)
    ledger["decisions"][0]["selected_candidate_sha256"] = "d" * 64  # type: ignore[index]
    ledger["review_timezone"] = "America/New_York"
    _resign(ledger, private_key)

    result = _validate(packet, ledger, private_key)

    assert result["status"] == "fail"
    assert any("selected_candidate_sha256 differs" in error for error in result["errors"])
    assert "reviewed_at offset differs from review_timezone" in result["errors"]

    wrong_profile = _ledger(packet, private_key, profile_sha256="d" * 64)
    profile_result = _validate(packet, wrong_profile, private_key)
    assert "reviewer_profile_sha256 differs" in profile_result["errors"]

    tampered = deepcopy(_ledger(packet, private_key))
    tampered["reviewer_id"] = "reviewer-tampered"
    signature_result = _validate(packet, tampered, private_key)
    assert signature_result["signature_status"] == "not_verified"
    assert signature_result["accepted_count"] == 0


def test_packet_validator_rejects_machine_fields_even_if_nested():
    packet = _packet()
    packet["items"][0]["score"] = 99  # type: ignore[index]

    result = validate_blind_review_packet(packet)

    assert result["status"] == "fail"
    assert any("forbidden machine fields" in error for error in result["errors"])

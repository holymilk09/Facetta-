from __future__ import annotations

import base64
import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from facetta.release_authority_bundle import (
    BUNDLE_CONFIG_SCHEMA,
    BUNDLE_DECISION_SCHEMA,
    REQUIRED_ROLES,
    REQUIRED_VERIFICATION_POLICY,
    ROLE_QUALIFICATION_REQUIREMENTS,
    verify_release_authority_bundle,
)
from facetta.release_authority_enrollment import (
    ENROLLMENT_SCHEMA,
    QUALIFICATION_SCHEMA,
    STATUS_LIST_SCHEMA,
    canonical_enrollment_proof_payload,
    canonical_qualification_payload,
    canonical_status_list_payload,
    derive_opaque_token,
    enrollment_artifact_sha256,
    public_key_sha256,
)


NOW = datetime(2026, 7, 13, 12, 0, 0, tzinfo=UTC)
SECRET = b"bundle-test-secret-material-32bytes!"


@dataclass(frozen=True)
class BundleFixture:
    root: Path
    config: dict[str, Any]
    paths: dict[str, Path]


def _token(kind: str, label: str) -> str:
    return derive_opaque_token(SECRET, kind, label)  # type: ignore[arg-type]


def _raw_public(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def _signature(
    private_key: Ed25519PrivateKey,
    key_id: str,
    payload: bytes,
) -> dict[str, str]:
    return {
        "algorithm": "Ed25519",
        "key_id": key_id,
        "value": base64.b64encode(private_key.sign(payload)).decode("ascii"),
    }


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
    )


def _pin(root: Path, path: Path) -> dict[str, str]:
    return {
        "path": str(path.relative_to(root)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _build_fixture(
    tmp_path: Path,
    *,
    expired: bool = False,
    status_state: str | None = None,
    duplicate_enrollment_subject: bool = False,
    wrong_qualification_field: tuple[str, str, str] | None = None,
    status_signer_collision: bool = False,
    minimum_sequence: int = 7,
) -> BundleFixture:
    root = tmp_path / "repository"
    artifact_root = root / "authority-bundle"
    key_root = artifact_root / "keys"
    key_root.mkdir(parents=True)
    paths: dict[str, Path] = {}

    authority_private = {
        role: Ed25519PrivateKey.generate() for role in REQUIRED_ROLES
    }
    qualification_private = Ed25519PrivateKey.generate()
    status_private = (
        authority_private["executor"]
        if status_signer_collision
        else Ed25519PrivateKey.generate()
    )
    qualification_key_id = "qualification-verifier-v1"
    status_key_id = "status-signer-v1"

    qualification_key_path = key_root / "qualification-verifier.pub"
    qualification_key_path.write_bytes(_raw_public(qualification_private))
    status_key_path = key_root / "status-signer.pub"
    status_key_path.write_bytes(_raw_public(status_private))
    paths["qualification_key"] = qualification_key_path
    paths["status_key"] = status_key_path

    authority_config: dict[str, Any] = {}
    enrollments: dict[str, dict[str, Any]] = {}
    qualifications: dict[str, dict[str, Any]] = {}
    status_subjects: dict[str, str] = {}
    status_organizations: dict[str, str] = {}
    executor_subject = _token("subject", "executor")

    for role in REQUIRED_ROLES:
        private_key = authority_private[role]
        key_id = f"{role}-key-v1"
        subject = (
            executor_subject
            if duplicate_enrollment_subject and role == "founder"
            else _token("subject", role)
        )
        organization = _token("organization", f"{role}-organization")
        status_subjects[role] = _token("subject", role)
        status_organizations[role] = organization
        valid_until = (
            "2026-07-10T00:00:00Z"
            if expired
            else "2026-08-01T00:00:00Z"
        )
        enrollment: dict[str, Any] = {
            "schema_version": ENROLLMENT_SCHEMA,
            "role": role,
            "subject_token": subject,
            "organization_token": organization,
            "key_id": key_id,
            "public_key_sha256": public_key_sha256(private_key.public_key()),
            "valid_from": "2026-07-01T00:00:00Z",
            "valid_until": valid_until,
        }
        enrollment["proof_of_possession"] = _signature(
            private_key,
            key_id,
            canonical_enrollment_proof_payload(enrollment),
        )
        enrollments[role] = enrollment

        required_code, methods = ROLE_QUALIFICATION_REQUIREMENTS[role]
        method = sorted(methods)[0]
        if role == "gia_reviewer":
            method = "issuer_registry"
        qualification: dict[str, Any] = {
            "schema_version": QUALIFICATION_SCHEMA,
            "role": role,
            "subject_token": subject,
            "organization_token": organization,
            "authority_key_id": key_id,
            "authority_public_key_sha256": enrollment["public_key_sha256"],
            "enrollment_sha256": enrollment_artifact_sha256(enrollment),
            "qualification_code": required_code,
            "issuer_token": _token("issuer", "qualification-issuer"),
            "credential_reference_sha256": hashlib.sha256(
                f"credential:{role}".encode(),
            ).hexdigest(),
            "restricted_evidence_sha256": hashlib.sha256(
                f"evidence:{role}".encode(),
            ).hexdigest(),
            "verification_method": method,
            "verification_policy": REQUIRED_VERIFICATION_POLICY,
            "verified_at": "2026-07-02T00:00:00Z",
            "valid_from": "2026-07-01T00:00:00Z",
            "valid_until": (
                "2026-07-09T00:00:00Z"
                if expired
                else "2026-07-31T00:00:00Z"
            ),
            "verifier_key_id": qualification_key_id,
            "verifier_public_key_sha256": public_key_sha256(
                qualification_private.public_key(),
            ),
        }
        if wrong_qualification_field and wrong_qualification_field[0] == role:
            qualification[wrong_qualification_field[1]] = wrong_qualification_field[2]
        qualification["verifier_signature"] = _signature(
            qualification_private,
            qualification_key_id,
            canonical_qualification_payload(qualification),
        )
        qualifications[role] = qualification

        enrollment_path = artifact_root / role / "enrollment.json"
        qualification_path = artifact_root / role / "qualification.json"
        public_key_path = key_root / f"{role}.pub"
        _write_json(enrollment_path, enrollment)
        _write_json(qualification_path, qualification)
        public_key_path.write_bytes(_raw_public(private_key))
        paths[f"{role}_enrollment"] = enrollment_path
        paths[f"{role}_qualification"] = qualification_path
        paths[f"{role}_key"] = public_key_path
        authority_config[role] = {
            "enrollment": _pin(root, enrollment_path),
            "qualification": _pin(root, qualification_path),
            "public_key": {
                **_pin(root, public_key_path),
                "key_id": key_id,
            },
        }

    entries: list[dict[str, Any]] = []
    for role in REQUIRED_ROLES:
        enrollment = enrollments[role]
        state = status_state if role == "founder" and status_state else "active"
        entry: dict[str, Any] = {
            "role": role,
            "subject_token": status_subjects[role],
            "organization_token": status_organizations[role],
            "authority_key_id": enrollment["key_id"],
            "authority_public_key_sha256": enrollment["public_key_sha256"],
            "state": state,
            "effective_at": "2026-07-13T10:00:00Z",
            "replacement_key_id": None,
            "replacement_public_key_sha256": None,
        }
        if state == "rotation":
            replacement = Ed25519PrivateKey.generate()
            entry["replacement_key_id"] = "founder-key-v2"
            entry["replacement_public_key_sha256"] = public_key_sha256(
                replacement.public_key(),
            )
        entries.append(entry)

    status: dict[str, Any] = {
        "schema_version": STATUS_LIST_SCHEMA,
        "list_id": "facetta-authorities-2026-07",
        "sequence": 7,
        "issuer_token": _token("issuer", "status-issuer"),
        "issued_at": "2026-07-13T11:00:00Z",
        "next_update": "2026-07-14T11:00:00Z",
        "entries": entries,
        "signer_key_id": status_key_id,
        "signer_public_key_sha256": public_key_sha256(status_private.public_key()),
    }
    status["signer_signature"] = _signature(
        status_private,
        status_key_id,
        canonical_status_list_payload(status),
    )
    status_path = artifact_root / "status-list.json"
    _write_json(status_path, status)
    paths["status"] = status_path

    config = {
        "schema_version": "legacy-corpus-config-remains-separate",
        "release_authority_bundle": {
            "schema_version": BUNDLE_CONFIG_SCHEMA,
            "verification_policy": REQUIRED_VERIFICATION_POLICY,
            "authorities": authority_config,
            "qualification_verifier_public_key": {
                **_pin(root, qualification_key_path),
                "key_id": qualification_key_id,
            },
            "status": {
                "artifact": _pin(root, status_path),
                "issuer_token": status["issuer_token"],
                "list_id": status["list_id"],
                "minimum_sequence": minimum_sequence,
                "signer_public_key": {
                    **_pin(root, status_key_path),
                    "key_id": status_key_id,
                },
            },
        },
    }
    operational_fields = {
        "canonical_api_runner": "canonical_api_runner_public_key",
        "gia_reviewer": "reviewer_public_key",
        "founder": "founder_public_key",
        "jewelry_designer": "designer_reviewer_public_key",
        "staging_reviewer": "staging_reviewer_public_key",
    }
    executor_key = paths["executor_key"]
    executor_pin = _pin(root, executor_key)
    config["executor_trust"] = {
        "schema_version": "facetta-frozen-executor-trust.v1",
        "status": "enrolled",
        "key_id": enrollments["executor"]["key_id"],
        "public_key": f"{executor_pin['path']}@sha256:{executor_pin['sha256']}",
    }
    for role, field in operational_fields.items():
        config[field] = {
            **_pin(root, paths[f"{role}_key"]),
            "key_id": enrollments[role]["key_id"],
        }
    return BundleFixture(root=root, config=config, paths=paths)


def test_verifies_all_six_roles_and_returns_only_opaque_facts_and_digests(
    tmp_path: Path,
) -> None:
    fixture = _build_fixture(tmp_path)

    result = verify_release_authority_bundle(fixture.config, fixture.root, NOW)

    assert result["schema_version"] == BUNDLE_DECISION_SCHEMA
    assert result["status"] == "pass"
    assert result["errors"] == []
    assert result["status_list"]["sequence"] == 7
    assert [row["role"] for row in result["authorities"]] == list(REQUIRED_ROLES)
    assert all(row["subject_token"].startswith("sub_hmac_sha256_") for row in result["authorities"])
    assert all(row["organization_token"].startswith("org_hmac_sha256_") for row in result["authorities"])
    serialized = json.dumps(result, sort_keys=True)
    for forbidden in (
        "authority-bundle/",
        "email",
        "full_name",
        "credential_number",
        "BEGIN PUBLIC KEY",
    ):
        assert forbidden not in serialized


@pytest.mark.parametrize("config", [{}, {"executor_trust": {"status": "enrolled"}}])
def test_absent_or_legacy_config_fails_without_exception(config: dict[str, Any]) -> None:
    result = verify_release_authority_bundle(config, Path.cwd(), NOW)
    assert result["status"] == "fail"
    assert result["authorities"] == []
    assert result["errors"] == ["release authority bundle config is absent"]


def test_rejects_repository_traversal_even_when_outside_hash_matches(
    tmp_path: Path,
) -> None:
    fixture = _build_fixture(tmp_path)
    outside = tmp_path / "outside-enrollment.json"
    outside.write_bytes(fixture.paths["executor_enrollment"].read_bytes())
    config = deepcopy(fixture.config)
    config["release_authority_bundle"]["authorities"]["executor"]["enrollment"] = {
        "path": "../outside-enrollment.json",
        "sha256": hashlib.sha256(outside.read_bytes()).hexdigest(),
    }

    result = verify_release_authority_bundle(config, fixture.root, NOW)
    assert result["status"] == "fail"
    assert any("escapes repository root" in error for error in result["errors"])


def test_rejects_hash_drift_before_parsing_artifact(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path)
    fixture.paths["gia_reviewer_qualification"].write_text("{}")

    result = verify_release_authority_bundle(fixture.config, fixture.root, NOW)
    assert result["status"] == "fail"
    assert result["errors"] == ["gia_reviewer qualification hash mismatch"]


def test_expired_authority_bundle_fails_closed(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path, expired=True)
    result = verify_release_authority_bundle(fixture.config, fixture.root, NOW)
    assert result["status"] == "fail"
    assert any("enrollment is not currently valid" in error for error in result["errors"])


@pytest.mark.parametrize("state", ["revoked", "rotation"])
def test_revocation_and_rotation_do_not_authorize_founder(
    tmp_path: Path,
    state: str,
) -> None:
    fixture = _build_fixture(tmp_path, status_state=state)
    result = verify_release_authority_bundle(fixture.config, fixture.root, NOW)
    assert result["status"] == "fail"
    assert any(f"status is {state}" in error for error in result["errors"])


def test_duplicate_opaque_subject_across_roles_fails_independence(
    tmp_path: Path,
) -> None:
    fixture = _build_fixture(tmp_path, duplicate_enrollment_subject=True)
    result = verify_release_authority_bundle(fixture.config, fixture.root, NOW)
    assert result["status"] == "fail"
    assert any("subject_token" in error for error in result["errors"])


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("qualification_code", "self_asserted_reviewer"),
        ("verification_method", "manual_document_review"),
        ("verification_policy", "weaker-policy-v1"),
    ],
)
def test_wrong_gia_qualification_code_method_or_policy_is_rejected(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    fixture = _build_fixture(
        tmp_path,
        wrong_qualification_field=("gia_reviewer", field, value),
    )
    result = verify_release_authority_bundle(fixture.config, fixture.root, NOW)
    assert result["status"] == "fail"
    assert any("qualification" in error for error in result["errors"])


def test_status_signer_cannot_reuse_release_authority_key(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path, status_signer_collision=True)
    result = verify_release_authority_bundle(fixture.config, fixture.root, NOW)
    assert result["status"] == "fail"
    assert result["errors"] == ["signer public key collides with a release authority"]


def test_operational_signer_must_be_the_exact_enrolled_role_key(
    tmp_path: Path,
) -> None:
    fixture = _build_fixture(tmp_path)
    config = deepcopy(fixture.config)
    founder_pin = _pin(fixture.root, fixture.paths["founder_key"])
    config["staging_reviewer_public_key"] = {
        **founder_pin,
        "key_id": "staging_reviewer-key-v1",
    }

    result = verify_release_authority_bundle(config, fixture.root, NOW)

    assert result["status"] == "fail"
    assert result["errors"] == [
        "staging_reviewer operational signer public key differs from enrollment",
    ]


def test_missing_operational_signer_fails_closed(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path)
    config = deepcopy(fixture.config)
    config["founder_public_key"] = None

    result = verify_release_authority_bundle(config, fixture.root, NOW)

    assert result["status"] == "fail"
    assert result["errors"] == ["founder operational signer config is absent"]


def test_status_sequence_below_configured_minimum_is_rollback(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path, minimum_sequence=8)
    result = verify_release_authority_bundle(fixture.config, fixture.root, NOW)
    assert result["status"] == "fail"
    assert result["errors"] == ["status sequence is below configured minimum"]


def test_qualification_verifier_and_status_signer_must_be_distinct(
    tmp_path: Path,
) -> None:
    fixture = _build_fixture(tmp_path)
    config = deepcopy(fixture.config)
    qualification_key = config["release_authority_bundle"][
        "qualification_verifier_public_key"
    ]
    config["release_authority_bundle"]["status"]["signer_public_key"] = {
        **qualification_key,
        "key_id": "status-signer-v1",
    }

    result = verify_release_authority_bundle(config, fixture.root, NOW)
    assert result["status"] == "fail"
    assert result["errors"] == [
        "qualification verifier and status signer keys must be distinct",
    ]


def test_naive_decision_time_is_a_failed_json_safe_decision(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path)
    result = verify_release_authority_bundle(
        fixture.config,
        fixture.root,
        datetime(2026, 7, 13, 12, 0, 0),
    )
    assert result["status"] == "fail"
    assert result["decision_time"] is None
    assert result["errors"] == ["decision_time must be timezone-aware"]

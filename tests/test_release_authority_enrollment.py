from __future__ import annotations

import base64
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from pydantic import ValidationError

from facetta.release_authority_enrollment import (
    ENROLLMENT_PROOF_DOMAIN,
    ENROLLMENT_SCHEMA,
    QUALIFICATION_DOMAIN,
    QUALIFICATION_SCHEMA,
    STATUS_LIST_DOMAIN,
    STATUS_LIST_SCHEMA,
    QualificationVerification,
    ReleaseAuthorityEnrollment,
    ReleaseAuthorityVerificationError,
    SignedReleaseAuthorityStatusList,
    canonical_enrollment_proof_payload,
    canonical_qualification_payload,
    canonical_status_list_payload,
    derive_opaque_token,
    enrollment_artifact_sha256,
    public_key_sha256,
    verify_authority_enrollment,
    verify_enrollment_independence,
    verify_qualification_verification,
    verify_release_authority,
    verify_signed_status_list,
)


NOW = datetime(2026, 7, 13, 12, 0, 0, tzinfo=UTC)
SECRET = b"facetta-test-opaque-token-key!" + b"x" * 8


def _public_bytes(private_key: Ed25519PrivateKey) -> bytes:
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


def _subject(label: str = "authority-1") -> str:
    return derive_opaque_token(SECRET, "subject", label)


def _organization(label: str = "organization-1") -> str:
    return derive_opaque_token(SECRET, "organization", label)


def _issuer(label: str = "issuer-1") -> str:
    return derive_opaque_token(SECRET, "issuer", label)


def _enrollment(
    private_key: Ed25519PrivateKey,
    *,
    role: str = "gia_reviewer",
    subject_token: str | None = None,
    organization_token: str | None = None,
    key_id: str = "authority-key-v1",
    valid_from: str = "2026-07-01T00:00:00Z",
    valid_until: str = "2026-08-01T00:00:00Z",
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_version": ENROLLMENT_SCHEMA,
        "role": role,
        "subject_token": subject_token or _subject(),
        "organization_token": organization_token or _organization(),
        "key_id": key_id,
        "public_key_sha256": public_key_sha256(private_key.public_key()),
        "valid_from": valid_from,
        "valid_until": valid_until,
    }
    value["proof_of_possession"] = _signature(
        private_key,
        key_id,
        canonical_enrollment_proof_payload(value),
    )
    return value


def _qualification(
    enrollment: dict[str, Any] | ReleaseAuthorityEnrollment,
    verifier_private_key: Ed25519PrivateKey,
    **overrides: Any,
) -> dict[str, Any]:
    enrolled = (
        enrollment
        if isinstance(enrollment, ReleaseAuthorityEnrollment)
        else ReleaseAuthorityEnrollment.model_validate(enrollment)
    )
    value: dict[str, Any] = {
        "schema_version": QUALIFICATION_SCHEMA,
        "role": enrolled.role,
        "subject_token": enrolled.subject_token,
        "organization_token": enrolled.organization_token,
        "authority_key_id": enrolled.key_id,
        "authority_public_key_sha256": enrolled.public_key_sha256,
        "enrollment_sha256": enrollment_artifact_sha256(enrolled),
        "qualification_code": "GIA-GG",
        "issuer_token": _issuer(),
        "credential_reference_sha256": "1" * 64,
        "restricted_evidence_sha256": "2" * 64,
        "verification_method": "issuer_registry",
        "verification_policy": "release-authority-policy-v1",
        "verified_at": "2026-07-02T00:00:00Z",
        "valid_from": "2026-07-01T00:00:00Z",
        "valid_until": "2026-07-31T00:00:00Z",
        "verifier_key_id": "qualification-verifier-v1",
        "verifier_public_key_sha256": public_key_sha256(
            verifier_private_key.public_key(),
        ),
    }
    value.update(overrides)
    value["verifier_signature"] = _signature(
        verifier_private_key,
        str(value["verifier_key_id"]),
        canonical_qualification_payload(value),
    )
    return value


def _status_list(
    enrollment: dict[str, Any] | ReleaseAuthorityEnrollment,
    signer_private_key: Ed25519PrivateKey,
    *,
    state: str = "active",
    issued_at: str = "2026-07-13T11:00:00Z",
    next_update: str = "2026-07-14T11:00:00Z",
    effective_at: str = "2026-07-13T10:00:00Z",
    replacement_key_id: str | None = None,
    replacement_public_key_sha256: str | None = None,
) -> dict[str, Any]:
    enrolled = (
        enrollment
        if isinstance(enrollment, ReleaseAuthorityEnrollment)
        else ReleaseAuthorityEnrollment.model_validate(enrollment)
    )
    entry: dict[str, Any] = {
        "role": enrolled.role,
        "subject_token": enrolled.subject_token,
        "organization_token": enrolled.organization_token,
        "authority_key_id": enrolled.key_id,
        "authority_public_key_sha256": enrolled.public_key_sha256,
        "state": state,
        "effective_at": effective_at,
        "replacement_key_id": replacement_key_id,
        "replacement_public_key_sha256": replacement_public_key_sha256,
    }
    value: dict[str, Any] = {
        "schema_version": STATUS_LIST_SCHEMA,
        "list_id": "release-authorities-2026-07-13",
        "sequence": 7,
        "issuer_token": _issuer("status-issuer"),
        "issued_at": issued_at,
        "next_update": next_update,
        "entries": [entry],
        "signer_key_id": "status-signer-v1",
        "signer_public_key_sha256": public_key_sha256(
            signer_private_key.public_key(),
        ),
    }
    value["signer_signature"] = _signature(
        signer_private_key,
        str(value["signer_key_id"]),
        canonical_status_list_payload(value),
    )
    return value


def _complete_fixture() -> tuple[
    Ed25519PrivateKey,
    Ed25519PrivateKey,
    Ed25519PrivateKey,
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    authority = Ed25519PrivateKey.generate()
    verifier = Ed25519PrivateKey.generate()
    status_signer = Ed25519PrivateKey.generate()
    enrollment = _enrollment(authority)
    qualification = _qualification(enrollment, verifier)
    status = _status_list(enrollment, status_signer)
    return authority, verifier, status_signer, enrollment, qualification, status


def test_complete_authority_verification_returns_only_opaque_release_facts() -> None:
    authority, verifier, status_signer, enrollment, qualification, status = (
        _complete_fixture()
    )

    verified = verify_release_authority(
        enrollment,
        qualification,
        status,
        authority_public_key=_public_bytes(authority),
        verifier_public_key=verifier.public_key(),
        status_signer_public_key=status_signer.public_key(),
        now=NOW,
        required_qualification_code="GIA-GG",
        required_verification_policy="release-authority-policy-v1",
        allowed_verification_methods={"issuer_registry"},
    )

    assert verified.role == "gia_reviewer"
    assert verified.authority_key_id == "authority-key-v1"
    assert verified.status_list_sequence == 7
    assert verified.verified_at == "2026-07-13T12:00:00Z"
    assert set(verified.model_dump()) == {
        "role",
        "subject_token",
        "organization_token",
        "authority_key_id",
        "authority_public_key_sha256",
        "qualification_code",
        "verification_method",
        "verification_policy",
        "status_list_id",
        "status_list_sequence",
        "verified_at",
    }


def test_opaque_tokens_are_stable_namespaced_and_domain_separated() -> None:
    subject = derive_opaque_token(SECRET, "subject", "stable-id")
    assert subject == derive_opaque_token(SECRET, "subject", "stable-id")
    assert subject.startswith("sub_hmac_sha256_")
    assert derive_opaque_token(SECRET, "organization", "stable-id").startswith(
        "org_hmac_sha256_",
    )
    assert derive_opaque_token(SECRET, "issuer", "stable-id").startswith(
        "iss_hmac_sha256_",
    )
    assert len(
        {
            derive_opaque_token(SECRET, kind, "stable-id")
            for kind in ("subject", "organization", "issuer")
        },
    ) == 3
    with pytest.raises(ValueError, match="at least 32 bytes"):
        derive_opaque_token(b"short", "subject", "stable-id")
    with pytest.raises(ValueError, match="non-empty"):
        derive_opaque_token(SECRET, "subject", "   ")


def test_signing_payloads_are_canonical_domain_separated_and_reject_pii() -> None:
    authority, verifier, status_signer, enrollment, qualification, status = (
        _complete_fixture()
    )
    del authority, verifier, status_signer

    enrollment_payload = canonical_enrollment_proof_payload(enrollment)
    qualification_payload = canonical_qualification_payload(qualification)
    status_payload = canonical_status_list_payload(status)
    assert enrollment_payload.startswith(ENROLLMENT_PROOF_DOMAIN + b"\x00")
    assert qualification_payload.startswith(QUALIFICATION_DOMAIN + b"\x00")
    assert status_payload.startswith(STATUS_LIST_DOMAIN + b"\x00")
    assert len({enrollment_payload, qualification_payload, status_payload}) == 3
    assert b"proof_of_possession" not in enrollment_payload
    assert b"verifier_signature" not in qualification_payload
    assert b"signer_signature" not in status_payload

    with pytest.raises(ValueError, match="raw PII key is forbidden"):
        canonical_enrollment_proof_payload({**enrollment, "email": "hidden@example"})
    nested = deepcopy(status)
    nested["entries"][0]["organization_name"] = "Do Not Persist"
    with pytest.raises(ValueError, match="raw PII key is forbidden"):
        canonical_status_list_payload(nested)


def test_enrollment_rejects_wrong_key_tampering_invalid_time_and_raw_pii() -> None:
    authority = Ed25519PrivateKey.generate()
    enrollment = _enrollment(authority)
    enrolled = verify_authority_enrollment(
        enrollment,
        authority.public_key(),
        now=NOW,
    )
    assert enrolled.public_key_sha256 == public_key_sha256(_public_bytes(authority))

    with pytest.raises(ReleaseAuthorityVerificationError, match="digest mismatch"):
        verify_authority_enrollment(
            enrollment,
            Ed25519PrivateKey.generate().public_key(),
            now=NOW,
        )
    tampered = deepcopy(enrollment)
    tampered["role"] = "founder"
    with pytest.raises(ReleaseAuthorityVerificationError, match="proof of possession"):
        verify_authority_enrollment(tampered, authority.public_key(), now=NOW)
    with pytest.raises(ReleaseAuthorityVerificationError, match="not currently valid"):
        verify_authority_enrollment(
            enrollment,
            authority.public_key(),
            now=datetime(2026, 8, 1, tzinfo=UTC),
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        verify_authority_enrollment(
            enrollment,
            authority.public_key(),
            now=datetime(2026, 7, 13),
        )

    invalid_window = _enrollment(
        authority,
        valid_from="2026-08-01T00:00:00Z",
        valid_until="2026-08-01T00:00:00Z",
    )
    with pytest.raises(ValidationError, match="valid_from must precede"):
        ReleaseAuthorityEnrollment.model_validate(invalid_window)
    noncanonical = deepcopy(enrollment)
    noncanonical["valid_from"] = "2026-07-01T00:00:00+00:00"
    with pytest.raises(ValidationError):
        ReleaseAuthorityEnrollment.model_validate(noncanonical)
    with pytest.raises(ValueError, match="raw PII key is forbidden"):
        verify_authority_enrollment(
            {**enrollment, "full_name": "Private Person"},
            authority.public_key(),
            now=NOW,
        )


def test_qualification_requires_exact_credential_coverage_and_verifier() -> None:
    authority = Ed25519PrivateKey.generate()
    verifier = Ed25519PrivateKey.generate()
    enrollment = ReleaseAuthorityEnrollment.model_validate(_enrollment(authority))
    qualification = _qualification(enrollment, verifier)

    accepted = verify_qualification_verification(
        qualification,
        enrollment,
        verifier.public_key(),
        now=NOW,
        required_qualification_code="GIA-GG",
        required_verification_policy="release-authority-policy-v1",
        allowed_verification_methods={"issuer_registry"},
    )
    assert accepted.enrollment_sha256 == enrollment_artifact_sha256(enrollment)

    wrong_subject = _qualification(
        enrollment,
        verifier,
        subject_token=_subject("different-person"),
    )
    with pytest.raises(ReleaseAuthorityVerificationError, match="subject_token"):
        verify_qualification_verification(
            wrong_subject,
            enrollment,
            verifier.public_key(),
            now=NOW,
        )
    overbroad = _qualification(
        enrollment,
        verifier,
        valid_until="2026-08-02T00:00:00Z",
    )
    with pytest.raises(ReleaseAuthorityVerificationError, match="not contained"):
        verify_qualification_verification(
            overbroad,
            enrollment,
            verifier.public_key(),
            now=NOW,
        )
    with pytest.raises(ReleaseAuthorityVerificationError, match="digest mismatch"):
        verify_qualification_verification(
            qualification,
            enrollment,
            Ed25519PrivateKey.generate().public_key(),
            now=NOW,
        )
    with pytest.raises(ReleaseAuthorityVerificationError, match="code is not authorized"):
        verify_qualification_verification(
            qualification,
            enrollment,
            verifier.public_key(),
            now=NOW,
            required_qualification_code="FOUNDER-OWNER",
        )
    with pytest.raises(ReleaseAuthorityVerificationError, match="method is not authorized"):
        verify_qualification_verification(
            qualification,
            enrollment,
            verifier.public_key(),
            now=NOW,
            allowed_verification_methods={"manual_document_review"},
        )


def test_qualification_signature_and_exact_enrollment_digest_are_tamper_evident() -> None:
    authority = Ed25519PrivateKey.generate()
    verifier = Ed25519PrivateKey.generate()
    enrollment = ReleaseAuthorityEnrollment.model_validate(_enrollment(authority))
    qualification = _qualification(enrollment, verifier)

    tampered = deepcopy(qualification)
    tampered["restricted_evidence_sha256"] = "9" * 64
    with pytest.raises(ReleaseAuthorityVerificationError, match="verifier signature"):
        verify_qualification_verification(
            tampered,
            enrollment,
            verifier.public_key(),
            now=NOW,
        )

    rebound = _qualification(enrollment, verifier, enrollment_sha256="8" * 64)
    with pytest.raises(ReleaseAuthorityVerificationError, match="enrollment_sha256"):
        verify_qualification_verification(
            rebound,
            enrollment,
            verifier.public_key(),
            now=NOW,
        )


def test_status_list_requires_fresh_bounded_signed_independent_state() -> None:
    authority = Ed25519PrivateKey.generate()
    status_signer = Ed25519PrivateKey.generate()
    enrollment = ReleaseAuthorityEnrollment.model_validate(_enrollment(authority))
    status = _status_list(enrollment, status_signer)
    accepted = verify_signed_status_list(
        status,
        status_signer.public_key(),
        now=NOW,
    )
    assert accepted.sequence == 7

    stale = _status_list(
        enrollment,
        status_signer,
        issued_at="2026-07-12T10:00:00Z",
        next_update="2026-07-13T11:59:59Z",
        effective_at="2026-07-12T09:00:00Z",
    )
    with pytest.raises(ReleaseAuthorityVerificationError, match="stale"):
        verify_signed_status_list(stale, status_signer.public_key(), now=NOW)
    future = _status_list(
        enrollment,
        status_signer,
        issued_at="2026-07-13T12:00:01Z",
        next_update="2026-07-14T12:00:00Z",
    )
    with pytest.raises(ReleaseAuthorityVerificationError, match="future-dated"):
        verify_signed_status_list(future, status_signer.public_key(), now=NOW)
    broad = _status_list(
        enrollment,
        status_signer,
        issued_at="2026-07-13T11:00:00Z",
        next_update="2026-07-15T11:00:00Z",
    )
    with pytest.raises(ReleaseAuthorityVerificationError, match="too broad"):
        verify_signed_status_list(broad, status_signer.public_key(), now=NOW)
    tampered = deepcopy(status)
    tampered["sequence"] = 8
    with pytest.raises(ReleaseAuthorityVerificationError, match="signer signature"):
        verify_signed_status_list(tampered, status_signer.public_key(), now=NOW)


@pytest.mark.parametrize("state", ["revoked", "rotation"])
def test_non_active_status_never_authorizes_release(state: str) -> None:
    authority, verifier, status_signer, enrollment, qualification, _ = (
        _complete_fixture()
    )
    replacement = Ed25519PrivateKey.generate()
    status = _status_list(
        enrollment,
        status_signer,
        state=state,
        replacement_key_id="authority-key-v2" if state == "rotation" else None,
        replacement_public_key_sha256=(
            public_key_sha256(replacement.public_key())
            if state == "rotation"
            else None
        ),
    )

    with pytest.raises(ReleaseAuthorityVerificationError, match=f"status is {state}"):
        verify_release_authority(
            enrollment,
            qualification,
            status,
            authority_public_key=authority.public_key(),
            verifier_public_key=verifier.public_key(),
            status_signer_public_key=status_signer.public_key(),
            now=NOW,
        )


def test_rotation_shape_and_status_coverage_fail_closed() -> None:
    authority, verifier, status_signer, enrollment, qualification, status = (
        _complete_fixture()
    )
    malformed_rotation = _status_list(
        enrollment,
        status_signer,
        state="rotation",
    )
    with pytest.raises(ValidationError, match="rotation status requires"):
        SignedReleaseAuthorityStatusList.model_validate(malformed_rotation)

    missing = deepcopy(status)
    missing["entries"][0]["authority_key_id"] = "another-authority-key"
    missing["signer_signature"] = _signature(
        status_signer,
        "status-signer-v1",
        canonical_status_list_payload(missing),
    )
    with pytest.raises(ReleaseAuthorityVerificationError, match="exactly one"):
        verify_release_authority(
            enrollment,
            qualification,
            missing,
            authority_public_key=authority.public_key(),
            verifier_public_key=verifier.public_key(),
            status_signer_public_key=status_signer.public_key(),
            now=NOW,
        )


def test_subject_organization_and_key_material_must_be_independent() -> None:
    first_key = Ed25519PrivateKey.generate()
    second_key = Ed25519PrivateKey.generate()
    first = ReleaseAuthorityEnrollment.model_validate(
        _enrollment(first_key, role="founder", key_id="founder-key-v1"),
    )
    second = ReleaseAuthorityEnrollment.model_validate(
        _enrollment(
            second_key,
            role="gia_reviewer",
            subject_token=_subject("reviewer"),
            organization_token=_organization("reviewer-org"),
            key_id="gia-key-v1",
        ),
    )
    assert verify_enrollment_independence(
        [first, second],
        required_roles={"founder", "gia_reviewer"},
    ) == (first, second)

    duplicate_subject = second.model_copy(
        update={"subject_token": first.subject_token},
    )
    with pytest.raises(ReleaseAuthorityVerificationError, match="subject_token"):
        verify_enrollment_independence([first, duplicate_subject])
    duplicate_org = second.model_copy(
        update={"organization_token": first.organization_token},
    )
    with pytest.raises(ReleaseAuthorityVerificationError, match="organization_token"):
        verify_enrollment_independence([first, duplicate_org])
    duplicate_key_id = ReleaseAuthorityEnrollment.model_validate(
        _enrollment(
            second_key,
            role="gia_reviewer",
            subject_token=_subject("reviewer"),
            organization_token=_organization("reviewer-org"),
            key_id=first.key_id,
        ),
    )
    with pytest.raises(ReleaseAuthorityVerificationError, match="authority_key_id"):
        verify_enrollment_independence([first, duplicate_key_id])
    duplicate_key = second.model_copy(
        update={"public_key_sha256": first.public_key_sha256},
    )
    with pytest.raises(
        ReleaseAuthorityVerificationError,
        match="authority_public_key_sha256",
    ):
        verify_enrollment_independence([first, duplicate_key])
    with pytest.raises(ReleaseAuthorityVerificationError, match="exactly cover"):
        verify_enrollment_independence(
            [first, second],
            required_roles={"founder", "gia_reviewer", "executor"},
        )


def test_schema_is_strict_about_unknown_fields_digests_and_signatures() -> None:
    authority = Ed25519PrivateKey.generate()
    enrollment = _enrollment(authority)
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ReleaseAuthorityEnrollment.model_validate({**enrollment, "legacy": True})

    invalid_digest = deepcopy(enrollment)
    invalid_digest["public_key_sha256"] = "A" * 64
    with pytest.raises(ValidationError):
        ReleaseAuthorityEnrollment.model_validate(invalid_digest)

    invalid_signature = deepcopy(enrollment)
    invalid_signature["proof_of_possession"]["value"] = base64.b64encode(
        b"short",
    ).decode("ascii").ljust(88, "=")
    with pytest.raises(ValidationError, match="canonical base64|64 bytes"):
        ReleaseAuthorityEnrollment.model_validate(invalid_signature)

    verifier = Ed25519PrivateKey.generate()
    qualification = _qualification(enrollment, verifier)
    qualification["verification_method"] = "self_asserted"
    with pytest.raises(ValidationError):
        QualificationVerification.model_validate(qualification)


def test_status_list_rejects_duplicate_subject_or_organization_entries() -> None:
    authority = Ed25519PrivateKey.generate()
    signer = Ed25519PrivateKey.generate()
    enrollment = _enrollment(authority)
    status = _status_list(enrollment, signer)
    duplicate = deepcopy(status["entries"][0])
    duplicate["role"] = "founder"
    duplicate["authority_key_id"] = "founder-key-v1"
    duplicate["authority_public_key_sha256"] = "a" * 64
    status["entries"].append(duplicate)
    status["signer_signature"] = _signature(
        signer,
        "status-signer-v1",
        canonical_status_list_payload(status),
    )
    with pytest.raises(ValidationError, match="subject_token"):
        SignedReleaseAuthorityStatusList.model_validate(status)


def test_status_age_limit_is_independent_from_signed_next_update() -> None:
    authority = Ed25519PrivateKey.generate()
    signer = Ed25519PrivateKey.generate()
    enrollment = _enrollment(authority)
    status = _status_list(
        enrollment,
        signer,
        issued_at="2026-07-13T09:00:00Z",
        next_update="2026-07-13T13:00:00Z",
        effective_at="2026-07-13T08:00:00Z",
    )
    with pytest.raises(ReleaseAuthorityVerificationError, match="maximum age"):
        verify_signed_status_list(
            status,
            signer.public_key(),
            now=NOW,
            max_status_age=timedelta(hours=2),
        )

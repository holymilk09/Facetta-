"""Privacy-safe enrollment and qualification checks for release authorities.

This module is deliberately independent from Facetta's release gates.  The
integration surface is four verifier functions plus canonical signing helpers:

* :func:`verify_authority_enrollment` proves possession of an enrolled key.
* :func:`verify_qualification_verification` binds a qualification to that exact
  enrollment artifact and to a separately enrolled verifier key.
* :func:`verify_signed_status_list` validates a fresh, signed authority list.
* :func:`verify_release_authority` composes the three checks and requires the
  enrolled key to be active.  Rotation is fail-closed and requires a new
  enrollment; it never silently promotes the replacement key.

Only HMAC-derived opaque subject, organization, and issuer tokens are retained.
Callers derive them before persistence with :func:`derive_opaque_token`; stable
identifiers and other raw PII must never enter these records.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from collections.abc import Collection, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal, Self, TypeVar

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    load_pem_public_key,
)
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


ENROLLMENT_SCHEMA = "facetta-release-authority-enrollment.v1"
QUALIFICATION_SCHEMA = "facetta-release-authority-qualification-verification.v1"
STATUS_LIST_SCHEMA = "facetta-release-authority-status-list.v1"

ENROLLMENT_PROOF_DOMAIN = b"facetta.release-authority.enrollment-pop.v1"
ENROLLMENT_ARTIFACT_DOMAIN = b"facetta.release-authority.enrollment-artifact.v1"
QUALIFICATION_DOMAIN = b"facetta.release-authority.qualification-verification.v1"
STATUS_LIST_DOMAIN = b"facetta.release-authority.status-list.v1"

DEFAULT_MAX_STATUS_AGE = timedelta(hours=24)
DEFAULT_MAX_STATUS_VALIDITY = timedelta(hours=24)

ReleaseAuthorityRole = Literal[
    "executor",
    "canonical_api_runner",
    "assignment_reviewer",
    "gia_reviewer",
    "founder",
    "jewelry_designer",
    "staging_reviewer",
]
VerificationMethod = Literal[
    "issuer_registry",
    "signed_attestation",
    "manual_document_review",
]
AuthorityState = Literal["active", "revoked", "rotation"]
OpaqueTokenKind = Literal["subject", "organization", "issuer"]

SafeIdentifier = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=3,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]
Sha256Digest = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$"),
]
SubjectToken = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^sub_hmac_sha256_[0-9a-f]{64}$"),
]
OrganizationToken = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^org_hmac_sha256_[0-9a-f]{64}$"),
]
IssuerToken = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^iss_hmac_sha256_[0-9a-f]{64}$"),
]
UtcTimestamp = Annotated[
    str,
    StringConstraints(
        strict=True,
        pattern=(
            r"^[0-9]{4}-(?:0[1-9]|1[0-2])-"
            r"(?:0[1-9]|[12][0-9]|3[01])T"
            r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]Z$"
        ),
    ),
]


class ReleaseAuthorityVerificationError(ValueError):
    """Raised when a cryptographic or semantic authority check fails."""


class _StrictRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class Ed25519Signature(_StrictRecord):
    algorithm: Literal["Ed25519"]
    key_id: SafeIdentifier
    value: str = Field(strict=True, min_length=88, max_length=88)

    @field_validator("value")
    @classmethod
    def _valid_signature(cls, value: str) -> str:
        try:
            decoded = base64.b64decode(value, validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError("signature value must be canonical base64") from exc
        if len(decoded) != 64 or base64.b64encode(decoded).decode("ascii") != value:
            raise ValueError("signature value must encode exactly 64 bytes")
        return value


class ReleaseAuthorityEnrollment(_StrictRecord):
    schema_version: Literal[ENROLLMENT_SCHEMA]
    role: ReleaseAuthorityRole
    subject_token: SubjectToken
    organization_token: OrganizationToken
    key_id: SafeIdentifier
    public_key_sha256: Sha256Digest
    valid_from: UtcTimestamp
    valid_until: UtcTimestamp
    proof_of_possession: Ed25519Signature

    @model_validator(mode="after")
    def _ordered_and_bound(self) -> Self:
        if _parse_timestamp(self.valid_from) >= _parse_timestamp(self.valid_until):
            raise ValueError("enrollment valid_from must precede valid_until")
        if self.proof_of_possession.key_id != self.key_id:
            raise ValueError("proof-of-possession key_id does not match enrollment")
        return self


class QualificationVerification(_StrictRecord):
    schema_version: Literal[QUALIFICATION_SCHEMA]
    role: ReleaseAuthorityRole
    subject_token: SubjectToken
    organization_token: OrganizationToken
    authority_key_id: SafeIdentifier
    authority_public_key_sha256: Sha256Digest
    enrollment_sha256: Sha256Digest
    qualification_code: SafeIdentifier
    issuer_token: IssuerToken
    credential_reference_sha256: Sha256Digest
    restricted_evidence_sha256: Sha256Digest
    verification_method: VerificationMethod
    verification_policy: SafeIdentifier
    verified_at: UtcTimestamp
    valid_from: UtcTimestamp
    valid_until: UtcTimestamp
    verifier_key_id: SafeIdentifier
    verifier_public_key_sha256: Sha256Digest
    verifier_signature: Ed25519Signature

    @model_validator(mode="after")
    def _ordered_and_bound(self) -> Self:
        start = _parse_timestamp(self.valid_from)
        end = _parse_timestamp(self.valid_until)
        verified = _parse_timestamp(self.verified_at)
        if start >= end:
            raise ValueError("qualification valid_from must precede valid_until")
        if not start <= verified < end:
            raise ValueError("verified_at must fall inside the qualification window")
        if self.verifier_signature.key_id != self.verifier_key_id:
            raise ValueError("verifier signature key_id does not match qualification")
        return self


class ReleaseAuthorityStatusEntry(_StrictRecord):
    role: ReleaseAuthorityRole
    subject_token: SubjectToken
    organization_token: OrganizationToken
    authority_key_id: SafeIdentifier
    authority_public_key_sha256: Sha256Digest
    state: AuthorityState
    effective_at: UtcTimestamp
    replacement_key_id: SafeIdentifier | None = None
    replacement_public_key_sha256: Sha256Digest | None = None

    @model_validator(mode="after")
    def _rotation_shape(self) -> Self:
        replacement_values = (
            self.replacement_key_id,
            self.replacement_public_key_sha256,
        )
        if self.state == "rotation":
            if any(value is None for value in replacement_values):
                raise ValueError("rotation status requires replacement key id and digest")
            if self.replacement_key_id == self.authority_key_id:
                raise ValueError("rotation replacement key_id must be different")
            if self.replacement_public_key_sha256 == self.authority_public_key_sha256:
                raise ValueError("rotation replacement public key must be different")
        elif any(value is not None for value in replacement_values):
            raise ValueError("only rotation status may name a replacement key")
        return self


class SignedReleaseAuthorityStatusList(_StrictRecord):
    schema_version: Literal[STATUS_LIST_SCHEMA]
    list_id: SafeIdentifier
    sequence: int = Field(strict=True, ge=1)
    issuer_token: IssuerToken
    issued_at: UtcTimestamp
    next_update: UtcTimestamp
    entries: tuple[ReleaseAuthorityStatusEntry, ...] = Field(min_length=1)
    signer_key_id: SafeIdentifier
    signer_public_key_sha256: Sha256Digest
    signer_signature: Ed25519Signature

    @field_validator("entries", mode="before")
    @classmethod
    def _freeze_json_entries(cls, value: Any) -> Any:
        # JSON represents tuples as arrays.  Normalize that one container at
        # the trust boundary, while strict nested models still reject coercion.
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def _ordered_unique_and_bound(self) -> Self:
        issued = _parse_timestamp(self.issued_at)
        if issued >= _parse_timestamp(self.next_update):
            raise ValueError("status-list issued_at must precede next_update")
        if self.signer_signature.key_id != self.signer_key_id:
            raise ValueError("status-list signature key_id does not match signer")
        for entry in self.entries:
            if _parse_timestamp(entry.effective_at) > issued:
                raise ValueError("status entry cannot become effective after issued_at")
        _ensure_independent(self.entries, label="status list")
        return self


class VerifiedReleaseAuthority(_StrictRecord):
    """Minimal privacy-safe result that a release gate may retain."""

    role: ReleaseAuthorityRole
    subject_token: SubjectToken
    organization_token: OrganizationToken
    authority_key_id: SafeIdentifier
    authority_public_key_sha256: Sha256Digest
    qualification_code: SafeIdentifier
    verification_method: VerificationMethod
    verification_policy: SafeIdentifier
    status_list_id: SafeIdentifier
    status_list_sequence: int = Field(strict=True, ge=1)
    verified_at: UtcTimestamp


_TOKEN_PREFIX = {
    "subject": "sub_hmac_sha256_",
    "organization": "org_hmac_sha256_",
    "issuer": "iss_hmac_sha256_",
}
_TOKEN_DOMAIN = {
    "subject": b"facetta.release-authority.subject-token.v1",
    "organization": b"facetta.release-authority.organization-token.v1",
    "issuer": b"facetta.release-authority.issuer-token.v1",
}
_RAW_PII_KEYS = {
    "address",
    "city",
    "company_name",
    "credential_number",
    "date_of_birth",
    "display_name",
    "dob",
    "email",
    "email_address",
    "employer_name",
    "full_name",
    "government_id",
    "legal_name",
    "license_number",
    "name",
    "national_id",
    "organization_name",
    "org_name",
    "passport",
    "person_name",
    "phone",
    "phone_number",
    "postal_code",
    "street",
    "user_id",
    "username",
}

PublicKeyMaterial = bytes | Ed25519PublicKey
RecordT = TypeVar("RecordT", bound=BaseModel)


def derive_opaque_token(
    secret: bytes,
    kind: OpaqueTokenKind,
    stable_identifier: str,
) -> str:
    """Return a domain-separated HMAC token without retaining raw identity.

    The secret must be an independently managed, tenant-appropriate secret of
    at least 256 bits.  The returned token is deterministic for deduplication;
    rotating the secret intentionally breaks linkage to earlier records.
    """

    if not isinstance(secret, bytes) or len(secret) < 32:
        raise ValueError("opaque-token HMAC secret must contain at least 32 bytes")
    if not isinstance(stable_identifier, str) or not stable_identifier.strip():
        raise ValueError("stable_identifier must be a non-empty string")
    normalized = stable_identifier.strip().encode("utf-8")
    digest = hmac.new(
        secret,
        _TOKEN_DOMAIN[kind] + b"\x00" + normalized,
        hashlib.sha256,
    ).hexdigest()
    return _TOKEN_PREFIX[kind] + digest


def public_key_sha256(public_key: PublicKeyMaterial) -> str:
    """Fingerprint normalized raw Ed25519 public-key bytes."""

    key = _load_public_key(public_key)
    raw = key.public_bytes(Encoding.Raw, PublicFormat.Raw)
    return hashlib.sha256(raw).hexdigest()


def canonical_enrollment_proof_payload(
    enrollment: ReleaseAuthorityEnrollment | Mapping[str, Any],
) -> bytes:
    """Return domain-separated bytes signed for proof of possession."""

    return _canonical_payload(
        ENROLLMENT_PROOF_DOMAIN,
        enrollment,
        omit={"proof_of_possession"},
    )


def canonical_qualification_payload(
    qualification: QualificationVerification | Mapping[str, Any],
) -> bytes:
    """Return domain-separated bytes signed by the qualification verifier."""

    return _canonical_payload(
        QUALIFICATION_DOMAIN,
        qualification,
        omit={"verifier_signature"},
    )


def canonical_status_list_payload(
    status_list: SignedReleaseAuthorityStatusList | Mapping[str, Any],
) -> bytes:
    """Return domain-separated bytes signed by the status-list authority."""

    return _canonical_payload(
        STATUS_LIST_DOMAIN,
        status_list,
        omit={"signer_signature"},
    )


def enrollment_artifact_sha256(
    enrollment: ReleaseAuthorityEnrollment | Mapping[str, Any],
) -> str:
    """Digest the complete enrollment, including its proof of possession."""

    return hashlib.sha256(
        _canonical_payload(ENROLLMENT_ARTIFACT_DOMAIN, enrollment),
    ).hexdigest()


def verify_authority_enrollment(
    enrollment: ReleaseAuthorityEnrollment | Mapping[str, Any],
    public_key: PublicKeyMaterial,
    *,
    now: datetime,
) -> ReleaseAuthorityEnrollment:
    """Validate schema, key binding, validity, and proof of possession."""

    record = _record(ReleaseAuthorityEnrollment, enrollment)
    instant = _aware_utc(now)
    start = _parse_timestamp(record.valid_from)
    end = _parse_timestamp(record.valid_until)
    if not start <= instant < end:
        raise ReleaseAuthorityVerificationError("enrollment is not currently valid")
    if public_key_sha256(public_key) != record.public_key_sha256:
        raise ReleaseAuthorityVerificationError("enrollment public-key digest mismatch")
    _verify_signature(
        public_key,
        record.proof_of_possession.value,
        canonical_enrollment_proof_payload(record),
        label="enrollment proof of possession",
    )
    return record


def verify_qualification_verification(
    qualification: QualificationVerification | Mapping[str, Any],
    enrollment: ReleaseAuthorityEnrollment,
    verifier_public_key: PublicKeyMaterial,
    *,
    now: datetime,
    required_qualification_code: str | None = None,
    required_verification_policy: str | None = None,
    allowed_verification_methods: Collection[VerificationMethod] | None = None,
) -> QualificationVerification:
    """Validate a qualification and its exact enrollment/key coverage."""

    enrollment = _record(ReleaseAuthorityEnrollment, enrollment)
    record = _record(QualificationVerification, qualification)
    instant = _aware_utc(now)
    bindings = {
        "role": enrollment.role,
        "subject_token": enrollment.subject_token,
        "organization_token": enrollment.organization_token,
        "authority_key_id": enrollment.key_id,
        "authority_public_key_sha256": enrollment.public_key_sha256,
        "enrollment_sha256": enrollment_artifact_sha256(enrollment),
    }
    for field_name, expected in bindings.items():
        if getattr(record, field_name) != expected:
            raise ReleaseAuthorityVerificationError(
                f"qualification does not cover enrollment {field_name}",
            )

    qualification_start = _parse_timestamp(record.valid_from)
    qualification_end = _parse_timestamp(record.valid_until)
    enrollment_start = _parse_timestamp(enrollment.valid_from)
    enrollment_end = _parse_timestamp(enrollment.valid_until)
    if qualification_start < enrollment_start or qualification_end > enrollment_end:
        raise ReleaseAuthorityVerificationError(
            "qualification validity is not contained by enrollment validity",
        )
    if not qualification_start <= instant < qualification_end:
        raise ReleaseAuthorityVerificationError("qualification is not currently valid")
    if _parse_timestamp(record.verified_at) > instant:
        raise ReleaseAuthorityVerificationError("qualification verification is future-dated")
    if (
        required_qualification_code is not None
        and record.qualification_code != required_qualification_code
    ):
        raise ReleaseAuthorityVerificationError("qualification code is not authorized")
    if (
        required_verification_policy is not None
        and record.verification_policy != required_verification_policy
    ):
        raise ReleaseAuthorityVerificationError("qualification policy is not authorized")
    if (
        allowed_verification_methods is not None
        and record.verification_method not in allowed_verification_methods
    ):
        raise ReleaseAuthorityVerificationError("qualification method is not authorized")
    if public_key_sha256(verifier_public_key) != record.verifier_public_key_sha256:
        raise ReleaseAuthorityVerificationError("verifier public-key digest mismatch")
    _verify_signature(
        verifier_public_key,
        record.verifier_signature.value,
        canonical_qualification_payload(record),
        label="qualification verifier signature",
    )
    return record


def verify_signed_status_list(
    status_list: SignedReleaseAuthorityStatusList | Mapping[str, Any],
    signer_public_key: PublicKeyMaterial,
    *,
    now: datetime,
    max_status_age: timedelta = DEFAULT_MAX_STATUS_AGE,
    max_status_validity: timedelta = DEFAULT_MAX_STATUS_VALIDITY,
) -> SignedReleaseAuthorityStatusList:
    """Validate signature, freshness, bounded lifetime, and entry independence."""

    record = _record(SignedReleaseAuthorityStatusList, status_list)
    instant = _aware_utc(now)
    issued = _parse_timestamp(record.issued_at)
    next_update = _parse_timestamp(record.next_update)
    if max_status_age <= timedelta(0) or max_status_validity <= timedelta(0):
        raise ValueError("status freshness limits must be positive")
    if issued > instant:
        raise ReleaseAuthorityVerificationError("status list is future-dated")
    if instant >= next_update:
        raise ReleaseAuthorityVerificationError("status list is stale")
    if instant - issued > max_status_age:
        raise ReleaseAuthorityVerificationError("status list exceeds maximum age")
    if next_update - issued > max_status_validity:
        raise ReleaseAuthorityVerificationError("status list validity is too broad")
    if public_key_sha256(signer_public_key) != record.signer_public_key_sha256:
        raise ReleaseAuthorityVerificationError("status signer public-key digest mismatch")
    _verify_signature(
        signer_public_key,
        record.signer_signature.value,
        canonical_status_list_payload(record),
        label="status-list signer signature",
    )
    return record


def verify_enrollment_independence(
    enrollments: Sequence[ReleaseAuthorityEnrollment],
    *,
    required_roles: Collection[ReleaseAuthorityRole] | None = None,
) -> tuple[ReleaseAuthorityEnrollment, ...]:
    """Reject cross-role reuse of identity, organization, or key material."""

    records = tuple(
        _record(ReleaseAuthorityEnrollment, enrollment)
        for enrollment in enrollments
    )
    if not records:
        raise ReleaseAuthorityVerificationError("at least one enrollment is required")
    _ensure_independent(records, label="enrollments")
    if required_roles is not None:
        required = set(required_roles)
        observed = {record.role for record in records}
        if observed != required:
            raise ReleaseAuthorityVerificationError(
                "enrollment roles do not exactly cover required roles",
            )
    return records


def verify_release_authority(
    enrollment: ReleaseAuthorityEnrollment | Mapping[str, Any],
    qualification: QualificationVerification | Mapping[str, Any],
    status_list: SignedReleaseAuthorityStatusList | Mapping[str, Any],
    *,
    authority_public_key: PublicKeyMaterial,
    verifier_public_key: PublicKeyMaterial,
    status_signer_public_key: PublicKeyMaterial,
    now: datetime,
    required_qualification_code: str | None = None,
    required_verification_policy: str | None = None,
    allowed_verification_methods: Collection[VerificationMethod] | None = None,
    max_status_age: timedelta = DEFAULT_MAX_STATUS_AGE,
    max_status_validity: timedelta = DEFAULT_MAX_STATUS_VALIDITY,
) -> VerifiedReleaseAuthority:
    """Compose all checks and return a minimal active-authority decision."""

    instant = _aware_utc(now)
    enrolled = verify_authority_enrollment(
        enrollment,
        authority_public_key,
        now=instant,
    )
    qualified = verify_qualification_verification(
        qualification,
        enrolled,
        verifier_public_key,
        now=instant,
        required_qualification_code=required_qualification_code,
        required_verification_policy=required_verification_policy,
        allowed_verification_methods=allowed_verification_methods,
    )
    statuses = verify_signed_status_list(
        status_list,
        status_signer_public_key,
        now=instant,
        max_status_age=max_status_age,
        max_status_validity=max_status_validity,
    )
    matching = [
        entry
        for entry in statuses.entries
        if (
            entry.role == enrolled.role
            and entry.subject_token == enrolled.subject_token
            and entry.organization_token == enrolled.organization_token
            and entry.authority_key_id == enrolled.key_id
            and entry.authority_public_key_sha256 == enrolled.public_key_sha256
        )
    ]
    if len(matching) != 1:
        raise ReleaseAuthorityVerificationError(
            "status list does not contain exactly one enrollment entry",
        )
    status = matching[0]
    if _parse_timestamp(status.effective_at) > instant:
        raise ReleaseAuthorityVerificationError("authority status is not yet effective")
    if status.state != "active":
        raise ReleaseAuthorityVerificationError(
            f"authority status is {status.state}; a fresh enrollment is required",
        )
    return VerifiedReleaseAuthority(
        role=enrolled.role,
        subject_token=enrolled.subject_token,
        organization_token=enrolled.organization_token,
        authority_key_id=enrolled.key_id,
        authority_public_key_sha256=enrolled.public_key_sha256,
        qualification_code=qualified.qualification_code,
        verification_method=qualified.verification_method,
        verification_policy=qualified.verification_policy,
        status_list_id=statuses.list_id,
        status_list_sequence=statuses.sequence,
        verified_at=_format_timestamp(instant),
    )


def _record(
    record_type: type[RecordT],
    value: RecordT | Mapping[str, Any],
) -> RecordT:
    raw = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    if not isinstance(raw, Mapping):
        raise TypeError("release-authority record must be a JSON object")
    _assert_no_raw_pii_keys(raw)
    # Re-validate model instances too: Pydantic's model_copy(update=...) is an
    # intentionally unvalidated API and must not bypass this trust boundary.
    return record_type.model_validate(raw)


def _canonical_payload(
    domain: bytes,
    value: BaseModel | Mapping[str, Any],
    *,
    omit: set[str] | None = None,
) -> bytes:
    raw = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    if not isinstance(raw, Mapping):
        raise TypeError("signed payload must be a JSON object")
    _assert_no_raw_pii_keys(raw)
    unsigned = {
        key: item
        for key, item in raw.items()
        if omit is None or key not in omit
    }
    try:
        serialized = json.dumps(
            unsigned,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("signed payload must contain only finite JSON values") from exc
    return domain + b"\x00" + serialized


def _assert_no_raw_pii_keys(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"record key at {path} must be a string")
            normalized = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
            if normalized in _RAW_PII_KEYS:
                raise ValueError(f"raw PII key is forbidden: {path}.{key}")
            _assert_no_raw_pii_keys(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_no_raw_pii_keys(item, f"{path}[{index}]")


def _load_public_key(public_key: PublicKeyMaterial) -> Ed25519PublicKey:
    if isinstance(public_key, Ed25519PublicKey):
        return public_key
    if not isinstance(public_key, bytes):
        raise TypeError("public key must be Ed25519PublicKey or bytes")
    try:
        if len(public_key) == 32:
            return Ed25519PublicKey.from_public_bytes(public_key)
        loaded = load_pem_public_key(public_key)
    except (TypeError, ValueError) as exc:
        raise ReleaseAuthorityVerificationError("invalid Ed25519 public key") from exc
    if not isinstance(loaded, Ed25519PublicKey):
        raise ReleaseAuthorityVerificationError("public key is not Ed25519")
    return loaded


def _verify_signature(
    public_key: PublicKeyMaterial,
    signature: str,
    payload: bytes,
    *,
    label: str,
) -> None:
    try:
        decoded = base64.b64decode(signature, validate=True)
        _load_public_key(public_key).verify(decoded, payload)
    except (InvalidSignature, ValueError, TypeError) as exc:
        raise ReleaseAuthorityVerificationError(f"invalid {label}") from exc


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError) as exc:
        raise ValueError("timestamp must be exact UTC second precision") from exc
    return parsed.replace(tzinfo=UTC)


def _format_timestamp(value: datetime) -> str:
    return _aware_utc(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def _aware_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("now must be a timezone-aware datetime")
    return value.astimezone(UTC).replace(microsecond=0)


def _ensure_independent(
    records: Sequence[ReleaseAuthorityEnrollment | ReleaseAuthorityStatusEntry],
    *,
    label: str,
) -> None:
    fields = (
        "role",
        "subject_token",
        "organization_token",
        "authority_key_id",
        "authority_public_key_sha256",
    )
    aliases = {
        "authority_key_id": "key_id",
        "authority_public_key_sha256": "public_key_sha256",
    }
    for field_name in fields:
        seen: set[str] = set()
        for record in records:
            if hasattr(record, field_name):
                value = str(getattr(record, field_name))
            else:
                value = str(getattr(record, aliases[field_name]))
            if value in seen:
                raise ReleaseAuthorityVerificationError(
                    f"{label} reuse {field_name}; release authorities must be independent",
                )
            seen.add(value)


__all__ = [
    "AuthorityState",
    "DEFAULT_MAX_STATUS_AGE",
    "DEFAULT_MAX_STATUS_VALIDITY",
    "ENROLLMENT_SCHEMA",
    "Ed25519Signature",
    "IssuerToken",
    "OrganizationToken",
    "QUALIFICATION_SCHEMA",
    "QualificationVerification",
    "ReleaseAuthorityEnrollment",
    "ReleaseAuthorityRole",
    "ReleaseAuthorityStatusEntry",
    "ReleaseAuthorityVerificationError",
    "STATUS_LIST_SCHEMA",
    "SignedReleaseAuthorityStatusList",
    "SubjectToken",
    "VerificationMethod",
    "VerifiedReleaseAuthority",
    "canonical_enrollment_proof_payload",
    "canonical_qualification_payload",
    "canonical_status_list_payload",
    "derive_opaque_token",
    "enrollment_artifact_sha256",
    "public_key_sha256",
    "verify_authority_enrollment",
    "verify_enrollment_independence",
    "verify_qualification_verification",
    "verify_release_authority",
    "verify_signed_status_list",
]

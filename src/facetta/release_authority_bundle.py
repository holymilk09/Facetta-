"""Fail-closed loading and verification of a complete release-authority set.

The legacy corpus configuration remains valid for its existing gates, but it
is not sufficient for this verifier.  A caller must provide a strict
``release_authority_bundle`` config that hash-pins every enrollment,
qualification, status list, and public key.  Nothing is fetched from the
network and every path is resolved beneath ``repository_root`` before it is
read.

The only public integration function is
:func:`verify_release_authority_bundle`.  It never raises for absent or
malformed bundle input; it returns a JSON-safe failed decision instead.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from facetta.release_authority_enrollment import (
    IssuerToken,
    QualificationVerification,
    ReleaseAuthorityEnrollment,
    ReleaseAuthorityRole,
    ReleaseAuthorityVerificationError,
    SignedReleaseAuthorityStatusList,
    VerificationMethod,
    enrollment_artifact_sha256,
    public_key_sha256,
    verify_enrollment_independence,
    verify_release_authority,
)


BUNDLE_CONFIG_SCHEMA = "facetta-release-authority-bundle-config.v1"
BUNDLE_DECISION_SCHEMA = "facetta-release-authority-bundle-decision.v1"
REQUIRED_VERIFICATION_POLICY = "facetta-release-authority-policy-v1"

REQUIRED_ROLES: tuple[ReleaseAuthorityRole, ...] = (
    "executor",
    "canonical_api_runner",
    "gia_reviewer",
    "founder",
    "jewelry_designer",
    "staging_reviewer",
)

ROLE_QUALIFICATION_REQUIREMENTS: dict[
    ReleaseAuthorityRole,
    tuple[str, frozenset[VerificationMethod]],
] = {
    "executor": (
        "secured_executor",
        frozenset({"signed_attestation", "manual_document_review"}),
    ),
    "canonical_api_runner": (
        "canonical_api_runner",
        frozenset({"signed_attestation", "manual_document_review"}),
    ),
    "gia_reviewer": (
        "GIA-trained",
        frozenset({"issuer_registry", "signed_attestation"}),
    ),
    "founder": (
        "founder_release_approver",
        frozenset({"signed_attestation", "manual_document_review"}),
    ),
    "jewelry_designer": (
        "jewelry_designer",
        frozenset({"signed_attestation", "manual_document_review"}),
    ),
    "staging_reviewer": (
        "staging_isolation_reviewer",
        frozenset({"signed_attestation", "manual_document_review"}),
    ),
}

_MAX_JSON_BYTES = 2 * 1024 * 1024
_MAX_PUBLIC_KEY_BYTES = 16 * 1024

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
RelativePath = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, max_length=1024),
]


class _StrictConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class _PinnedArtifact(_StrictConfig):
    path: RelativePath
    sha256: Sha256Digest


class _PinnedPublicKey(_PinnedArtifact):
    key_id: SafeIdentifier


class _AuthorityConfig(_StrictConfig):
    enrollment: _PinnedArtifact
    qualification: _PinnedArtifact
    public_key: _PinnedPublicKey


class _StatusConfig(_StrictConfig):
    artifact: _PinnedArtifact
    issuer_token: IssuerToken
    list_id: SafeIdentifier
    minimum_sequence: int = Field(strict=True, ge=1)
    signer_public_key: _PinnedPublicKey


class _BundleConfig(_StrictConfig):
    schema_version: Literal[BUNDLE_CONFIG_SCHEMA]
    verification_policy: Literal[REQUIRED_VERIFICATION_POLICY]
    authorities: dict[ReleaseAuthorityRole, _AuthorityConfig]
    qualification_verifier_public_key: _PinnedPublicKey
    status: _StatusConfig

    @model_validator(mode="after")
    def _exact_role_coverage(self) -> Self:
        if set(self.authorities) != set(REQUIRED_ROLES):
            raise ValueError("authority config must exactly cover all six roles")
        return self


class _BundleError(ValueError):
    """Internal error whose message is safe to return in a decision."""


def verify_release_authority_bundle(
    config: Mapping[str, Any],
    repository_root: Path,
    decision_time: datetime,
) -> dict[str, Any]:
    """Verify the complete six-role authority bundle without raising.

    The successful result contains only opaque tokens, public identifiers, and
    digests.  It intentionally excludes paths, raw key bytes, credential data,
    and signed artifact bodies.
    """

    result: dict[str, Any] = {
        "schema_version": BUNDLE_DECISION_SCHEMA,
        "status": "fail",
        "decision_time": _safe_decision_time(decision_time),
        "verification_policy": REQUIRED_VERIFICATION_POLICY,
        "status_list": None,
        "authorities": [],
        "errors": [],
    }
    try:
        instant = _decision_time(decision_time)
        root = repository_root.resolve(strict=True)
        if not root.is_dir():
            raise _BundleError("repository root is not a directory")
        raw_bundle = config.get("release_authority_bundle")
        if not isinstance(raw_bundle, Mapping):
            raise _BundleError("release authority bundle config is absent")
        bundle = _BundleConfig.model_validate(raw_bundle)

        qualification_key_bytes, qualification_key_digest = _load_pinned_key(
            root,
            bundle.qualification_verifier_public_key,
            label="qualification verifier public key",
        )
        status_key_bytes, status_key_digest = _load_pinned_key(
            root,
            bundle.status.signer_public_key,
            label="status signer public key",
        )
        if (
            bundle.qualification_verifier_public_key.key_id
            == bundle.status.signer_public_key.key_id
            or qualification_key_digest == status_key_digest
        ):
            raise _BundleError(
                "qualification verifier and status signer keys must be distinct",
            )

        status_bytes = _read_pinned(
            root,
            bundle.status.artifact,
            label="signed status list",
            maximum_bytes=_MAX_JSON_BYTES,
        )
        status_value = _json_object(status_bytes, label="signed status list")
        status_list = SignedReleaseAuthorityStatusList.model_validate(status_value)
        if status_list.signer_key_id != bundle.status.signer_public_key.key_id:
            raise _BundleError("status signer key_id differs from config")
        if status_list.signer_public_key_sha256 != status_key_digest:
            raise _BundleError("status signer normalized key digest differs from config")
        if status_list.issuer_token != bundle.status.issuer_token:
            raise _BundleError("status issuer token differs from config")
        if status_list.list_id != bundle.status.list_id:
            raise _BundleError("status list_id differs from config")
        if status_list.sequence < bundle.status.minimum_sequence:
            raise _BundleError("status sequence is below configured minimum")

        enrollments: dict[ReleaseAuthorityRole, ReleaseAuthorityEnrollment] = {}
        qualifications: dict[ReleaseAuthorityRole, QualificationVerification] = {}
        authority_keys: dict[ReleaseAuthorityRole, bytes] = {}
        enrollment_file_hashes: dict[ReleaseAuthorityRole, str] = {}
        qualification_file_hashes: dict[ReleaseAuthorityRole, str] = {}

        for role in REQUIRED_ROLES:
            authority = bundle.authorities[role]
            enrollment_bytes = _read_pinned(
                root,
                authority.enrollment,
                label=f"{role} enrollment",
                maximum_bytes=_MAX_JSON_BYTES,
            )
            qualification_bytes = _read_pinned(
                root,
                authority.qualification,
                label=f"{role} qualification",
                maximum_bytes=_MAX_JSON_BYTES,
            )
            enrollment = ReleaseAuthorityEnrollment.model_validate(
                _json_object(enrollment_bytes, label=f"{role} enrollment"),
            )
            qualification = QualificationVerification.model_validate(
                _json_object(qualification_bytes, label=f"{role} qualification"),
            )
            key_bytes, key_digest = _load_pinned_key(
                root,
                authority.public_key,
                label=f"{role} public key",
            )
            if enrollment.role != role or qualification.role != role:
                raise _BundleError(f"{role} artifacts declare a different role")
            if enrollment.key_id != authority.public_key.key_id:
                raise _BundleError(f"{role} enrollment key_id differs from config")
            if enrollment.public_key_sha256 != key_digest:
                raise _BundleError(
                    f"{role} enrollment normalized key digest differs from config",
                )
            if (
                qualification.verifier_key_id
                != bundle.qualification_verifier_public_key.key_id
            ):
                raise _BundleError(
                    f"{role} qualification verifier key_id differs from config",
                )
            if qualification.verifier_public_key_sha256 != qualification_key_digest:
                raise _BundleError(
                    f"{role} qualification verifier digest differs from config",
                )
            enrollments[role] = enrollment
            qualifications[role] = qualification
            authority_keys[role] = key_bytes
            enrollment_file_hashes[role] = hashlib.sha256(
                enrollment_bytes,
            ).hexdigest()
            qualification_file_hashes[role] = hashlib.sha256(
                qualification_bytes,
            ).hexdigest()

        verify_enrollment_independence(
            tuple(enrollments[role] for role in REQUIRED_ROLES),
            required_roles=set(REQUIRED_ROLES),
        )
        authority_key_ids = {enrollment.key_id for enrollment in enrollments.values()}
        authority_key_digests = {
            enrollment.public_key_sha256 for enrollment in enrollments.values()
        }
        privileged_key_ids = {
            bundle.qualification_verifier_public_key.key_id,
            bundle.status.signer_public_key.key_id,
        }
        privileged_key_digests = {qualification_key_digest, status_key_digest}
        if authority_key_ids & privileged_key_ids:
            raise _BundleError("signer key_id collides with a release authority")
        if authority_key_digests & privileged_key_digests:
            raise _BundleError("signer public key collides with a release authority")

        verified_rows: list[dict[str, Any]] = []
        for role in REQUIRED_ROLES:
            qualification_code, methods = ROLE_QUALIFICATION_REQUIREMENTS[role]
            verified = verify_release_authority(
                enrollments[role],
                qualifications[role],
                status_list,
                authority_public_key=authority_keys[role],
                verifier_public_key=qualification_key_bytes,
                status_signer_public_key=status_key_bytes,
                now=instant,
                required_qualification_code=qualification_code,
                required_verification_policy=REQUIRED_VERIFICATION_POLICY,
                allowed_verification_methods=methods,
                max_status_age=timedelta(hours=24),
                max_status_validity=timedelta(hours=24),
            )
            verified_rows.append({
                "role": verified.role,
                "subject_token": verified.subject_token,
                "organization_token": verified.organization_token,
                "authority_key_id": verified.authority_key_id,
                "authority_public_key_sha256": (
                    verified.authority_public_key_sha256
                ),
                "qualification_code": verified.qualification_code,
                "verification_method": verified.verification_method,
                "verification_policy": verified.verification_policy,
                "enrollment_artifact_sha256": enrollment_artifact_sha256(
                    enrollments[role],
                ),
                "enrollment_file_sha256": enrollment_file_hashes[role],
                "qualification_file_sha256": qualification_file_hashes[role],
                "credential_reference_sha256": (
                    qualifications[role].credential_reference_sha256
                ),
                "restricted_evidence_sha256": (
                    qualifications[role].restricted_evidence_sha256
                ),
            })

        result.update({
            "status": "pass",
            "status_list": {
                "issuer_token": status_list.issuer_token,
                "list_id": status_list.list_id,
                "sequence": status_list.sequence,
                "artifact_sha256": hashlib.sha256(status_bytes).hexdigest(),
                "signer_key_id": status_list.signer_key_id,
                "signer_public_key_sha256": status_key_digest,
            },
            "authorities": verified_rows,
            "errors": [],
        })
        return result
    except _BundleError as exc:
        result["errors"] = [str(exc)]
    except ReleaseAuthorityVerificationError as exc:
        result["errors"] = [str(exc)]
    except ValidationError:
        result["errors"] = ["release authority bundle artifact schema is invalid"]
    except json.JSONDecodeError:
        result["errors"] = ["release authority bundle artifact is not valid JSON"]
    except (OSError, TypeError, ValueError):
        result["errors"] = ["release authority bundle value is invalid"]
    except Exception:
        # The public boundary is deliberately fail-closed.  Do not leak
        # exception detail because validation errors can echo artifact values.
        result["errors"] = ["release authority bundle verification failed"]
    return result


def _read_pinned(
    root: Path,
    artifact: _PinnedArtifact,
    *,
    label: str,
    maximum_bytes: int,
) -> bytes:
    relative = Path(artifact.path)
    if relative.is_absolute() or "\x00" in artifact.path:
        raise _BundleError(f"{label} path is not repository-relative")
    try:
        candidate = (root / relative).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise _BundleError(f"{label} is unavailable") from exc
    if not candidate.is_relative_to(root) or not candidate.is_file():
        raise _BundleError(f"{label} path escapes repository root")
    try:
        content = candidate.read_bytes()
    except OSError as exc:
        raise _BundleError(f"{label} is unreadable") from exc
    if len(content) > maximum_bytes:
        raise _BundleError(f"{label} exceeds the size limit")
    if hashlib.sha256(content).hexdigest() != artifact.sha256:
        raise _BundleError(f"{label} hash mismatch")
    return content


def _load_pinned_key(
    root: Path,
    pinned_key: _PinnedPublicKey,
    *,
    label: str,
) -> tuple[bytes, str]:
    content = _read_pinned(
        root,
        pinned_key,
        label=label,
        maximum_bytes=_MAX_PUBLIC_KEY_BYTES,
    )
    try:
        normalized_digest = public_key_sha256(content)
    except (ReleaseAuthorityVerificationError, TypeError, ValueError) as exc:
        raise _BundleError(f"{label} is not a valid Ed25519 public key") from exc
    return content, normalized_digest


def _json_object(content: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _BundleError(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise _BundleError(f"{label} must contain a JSON object")
    return value


def _decision_time(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _BundleError("decision_time must be timezone-aware")
    return value.astimezone(UTC).replace(microsecond=0)


def _safe_decision_time(value: datetime) -> str | None:
    try:
        return _decision_time(value).strftime("%Y-%m-%dT%H:%M:%SZ")
    except _BundleError:
        return None


__all__ = [
    "BUNDLE_CONFIG_SCHEMA",
    "BUNDLE_DECISION_SCHEMA",
    "REQUIRED_ROLES",
    "REQUIRED_VERIFICATION_POLICY",
    "ROLE_QUALIFICATION_REQUIREMENTS",
    "verify_release_authority_bundle",
]

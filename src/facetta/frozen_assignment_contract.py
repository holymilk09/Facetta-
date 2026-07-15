"""Signed reviewer authority for frozen source-specific assignments.

The capture planner must not trust a bundle merely because it is hash-pinned in
the same config that points at it.  A usable production bundle is therefore
signed by a separately enrolled assignment reviewer.  The private key stays
outside both the repository and retained-evidence root; this module only loads
the hash-pinned public enrollment and verifies canonical bundle bytes.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from facetta.release_authority_bundle import verify_release_authority_bundle
from facetta.revision_component_map import RevisionComponentMap, component_map_hash
from facetta.ring_evals import CANONICAL_RING_EDITS, apply_canonical_ring_edit
from facetta.spec import Spec


Json = dict[str, Any]

SIGNED_ASSIGNMENT_BUNDLE_SCHEMA = "facetta-frozen-assignment-bundle.v2"
ASSIGNMENT_REVIEWER_CONFIG_KEY = "assignment_reviewer_public_key"
COMPONENT_MAPPER_CONFIG_KEY = "component_mapper_public_key"
COMPONENT_MAP_ATTESTATION_SCHEMA = "facetta-frozen-component-map-attestation.v1"
ASSIGNMENT_BUNDLE_SIGNATURE_DOMAIN = (
    b"facetta:frozen-assignment-bundle:v2\x00"
)
COMPONENT_MAP_ATTESTATION_SIGNATURE_DOMAIN = (
    b"facetta:frozen-component-map-attestation:v1\x00"
)
ASSIGNMENT_BUNDLE_ROW_FIELDS = frozenset({
    "source_filename",
    "kind",
    "evaluation_id",
    "binding",
})
_ASSIGNMENT_EVIDENCE_FIELDS = {
    "review_evidence_sha256",
    "source_spec_evidence_sha256",
    "component_map_sha256",
    "region_evidence_sha256",
}
EXECUTE_ASSIGNMENT_BINDING_FIELDS = frozenset({
    "schema_version",
    "review_status",
    "applicability",
    *_ASSIGNMENT_EVIDENCE_FIELDS,
    "source_spec",
    "target_spec",
    "instruction",
    "region_description",
    "frozen_facts",
})
NOT_APPLICABLE_ASSIGNMENT_BINDING_FIELDS = frozenset({
    "schema_version",
    "review_status",
    "applicability",
    "not_applicable_reason",
    *_ASSIGNMENT_EVIDENCE_FIELDS,
})
CANONICAL_DELTA_INAPPLICABLE_BINDING_FIELDS = frozenset({
    *NOT_APPLICABLE_ASSIGNMENT_BINDING_FIELDS,
    "source_sha256",
    "source_spec",
    "canonical_edit_issues",
})
SOURCE_COMPONENT_ABSENT_BINDING_FIELDS = frozenset({
    *NOT_APPLICABLE_ASSIGNMENT_BINDING_FIELDS,
    "source_sha256",
    "component_map",
    "component_map_attestation",
    "component_map_attestation_sha256",
})
RELEASE_AUTHORITY_DECISION_FIELDS = frozenset({
    "reviewed_at",
    "decision_time",
    "authority_decision_sha256",
    "release_authority_bundle_sha256",
})

_PRODUCTION_FROZEN_CONFIG_ID = "founder-ring-90-85-90-v1"
_PRODUCTION_FROZEN_CORPUS_ID = "founder-reference-144-v1"
_OPAQUE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{6,127}\Z")
_OPAQUE_COMPONENT_MAP_RUN_ID = re.compile(r"maprun_[0-9a-f]{64}\Z")
_FROZEN_COMPONENT_PIN = re.compile(
    r"(?P<path>[^@]+)@sha256:(?P<sha256>[0-9a-f]{64})\Z"
)
SOURCE_COMPONENT_ABSENT_REASON = (
    "source_component_absent/component-map-all-required-kinds-absent.v1"
)
CANONICAL_DELTA_INAPPLICABLE_REASON = (
    "canonical_delta_inapplicable/canonical-edit-apply-failed.v1"
)
SUPPORTED_NOT_APPLICABLE_REASONS = frozenset({
    SOURCE_COMPONENT_ABSENT_REASON,
    CANONICAL_DELTA_INAPPLICABLE_REASON,
})
_RING_REQUIRED_COMPONENT_KINDS = frozenset({
    "background",
    "center_stone",
    "gallery",
    "metal_zone",
    "prongs",
    "setting",
    "shank",
    "shoulders",
})
EDIT_REQUIRED_COMPONENT_KINDS = MappingProxyType({
    "center-cut-shape": frozenset({"center_stone", "prongs", "setting"}),
    "center-species-color": frozenset({"center_stone"}),
    "band-width": frozenset({"shank"}),
    "metal-color": frozenset({
        "prongs",
        "setting",
        "shank",
        "shoulders",
        "gallery",
        "metal_zone",
    }),
    "metal-material": frozenset({
        "prongs",
        "setting",
        "shank",
        "shoulders",
        "gallery",
        "metal_zone",
    }),
    "prong-setting": frozenset({"prongs", "setting"}),
    "halo-add": frozenset({"center_stone", "setting", "stone_group"}),
    "halo-remove": frozenset({"center_stone", "setting", "stone_group"}),
    "halo-count": frozenset({"center_stone", "setting", "stone_group"}),
    "leaf-motif-shape": frozenset({"shoulders", "stone_group"}),
    "background-only": frozenset({"background"}),
    "impossible-band-width": frozenset({"shank"}),
})


@dataclass(frozen=True)
class EnrolledAssignmentReviewer:
    key_id: str
    reviewer_profile_sha256: str
    public_key_sha256: str
    public_key: Ed25519PublicKey


@dataclass(frozen=True)
class EnrolledComponentMapper:
    key_id: str
    public_key_sha256: str
    public_key: Ed25519PublicKey


def _sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def _canonical_object_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _canonical_utc_timestamp(value: object, *, label: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"signed {label} is invalid")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise ValueError(f"signed {label} is not canonical UTC") from exc
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise ValueError(f"signed {label} is not canonical UTC")
    return parsed


def _requires_release_authority_decision(config: Json) -> bool:
    return (
        config.get("config_id") == _PRODUCTION_FROZEN_CONFIG_ID
        or config.get("corpus_id") == _PRODUCTION_FROZEN_CORPUS_ID
        or config.get("release_authority_bundle") is not None
    )


def build_release_authority_decision_binding(
    config: Json,
    authority_decision: Json,
    *,
    reviewed_at: str,
) -> Json:
    """Build the exact signed bridge from assignment review to authority state."""

    release_authority_config = config.get("release_authority_bundle")
    if release_authority_config is None:
        raise ValueError("release authority bundle config is absent")
    decision_time_value = authority_decision.get("decision_time")
    decision_time = _canonical_utc_timestamp(
        decision_time_value,
        label="authority decision time",
    )
    review_time = _canonical_utc_timestamp(
        reviewed_at,
        label="assignment review time",
    )
    if review_time > decision_time:
        raise ValueError("assignment review time follows authority decision time")
    roles = {
        row.get("role")
        for row in authority_decision.get("authorities", [])
        if isinstance(row, dict)
    }
    if (
        authority_decision.get("status") != "pass"
        or "assignment_reviewer" not in roles
    ):
        raise ValueError("assignment reviewer release authority is not active")
    return {
        "reviewed_at": reviewed_at,
        "decision_time": decision_time_value,
        "authority_decision_sha256": _canonical_object_sha256(
            authority_decision
        ),
        "release_authority_bundle_sha256": _canonical_object_sha256(
            release_authority_config
        ),
    }


def _load_public_key(content: bytes) -> Ed25519PublicKey:
    try:
        if len(content) == 32:
            return Ed25519PublicKey.from_public_bytes(content)
        loaded = load_pem_public_key(content)
    except (TypeError, ValueError) as exc:
        raise ValueError("configured assignment reviewer public key is invalid") from exc
    if not isinstance(loaded, Ed25519PublicKey):
        raise ValueError("configured assignment reviewer public key is not Ed25519")
    return loaded


def load_enrolled_component_mapper(
    config: Json,
    *,
    repository_root: Path,
    reviewer: EnrolledAssignmentReviewer | None = None,
) -> EnrolledComponentMapper:
    """Load an independent, repository-confined component-mapper key."""

    configured = config.get(COMPONENT_MAPPER_CONFIG_KEY)
    if not isinstance(configured, dict) or set(configured) != {
        "key_id",
        "path",
        "sha256",
    }:
        raise ValueError("component mapper public key is not completely configured")
    key_id = configured.get("key_id")
    relative = configured.get("path")
    expected_sha256 = configured.get("sha256")
    if not isinstance(key_id, str) or _OPAQUE_ID.fullmatch(key_id) is None:
        raise ValueError("component mapper key_id must be opaque")
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("component mapper public-key path is invalid")
    if not _sha256(expected_sha256):
        raise ValueError("component mapper public-key sha256 is invalid")
    root = repository_root.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("component mapper public-key file is unavailable")
    content = path.read_bytes()
    actual_sha256 = hashlib.sha256(content).hexdigest()
    if actual_sha256 != expected_sha256:
        raise ValueError("component mapper public-key sha256 differs")
    if reviewer is not None and (
        key_id == reviewer.key_id
        or actual_sha256 == reviewer.public_key_sha256
    ):
        raise ValueError(
            "component mapper enrollment must be distinct from assignment reviewer"
        )
    return EnrolledComponentMapper(
        key_id=key_id,
        public_key_sha256=actual_sha256,
        public_key=_load_public_key(content),
    )


def canonical_component_map_attestation_payload(attestation: Json) -> bytes:
    """Return the domain-separated bytes signed by the enrolled mapper."""

    unsigned = {
        key: value for key, value in attestation.items() if key != "signature"
    }
    return COMPONENT_MAP_ATTESTATION_SIGNATURE_DOMAIN + json.dumps(
        unsigned,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def verify_component_map_attestation(
    attestation: Json,
    *,
    mapper: EnrolledComponentMapper,
    source_sha256: str,
    component_map_sha256: str,
    mapper_contract: str,
    calibration_evidence_sha256: str,
    corpus_run_id: str,
) -> None:
    """Verify one exact map result, not only a mapper calibration claim."""

    if set(attestation) != {
        "schema_version",
        "source_sha256",
        "component_map_sha256",
        "mapper_contract",
        "calibration_evidence_sha256",
        "corpus_run_id",
        "run_id",
        "mapper_key_id",
        "signature",
    }:
        raise ValueError("component-map attestation has unexpected or missing fields")
    if attestation.get("schema_version") != COMPONENT_MAP_ATTESTATION_SCHEMA:
        raise ValueError("component-map attestation schema is unsupported")
    for field_name in (
        "source_sha256",
        "component_map_sha256",
        "calibration_evidence_sha256",
    ):
        if not _sha256(attestation.get(field_name)):
            raise ValueError(f"component-map attestation {field_name} is invalid")
    run_id = attestation.get("run_id")
    if not isinstance(run_id, str) or _OPAQUE_COMPONENT_MAP_RUN_ID.fullmatch(run_id) is None:
        raise ValueError("component-map attestation run_id must be opaque")
    if attestation.get("mapper_key_id") != mapper.key_id:
        raise ValueError("component-map attestation key differs from enrollment")
    signature = attestation.get("signature")
    if not isinstance(signature, dict) or set(signature) != {
        "algorithm",
        "key_id",
        "value",
    }:
        raise ValueError("component-map attestation signature is malformed")
    if (
        signature.get("algorithm") != "Ed25519"
        or signature.get("key_id") != mapper.key_id
    ):
        raise ValueError("component-map attestation signature enrollment differs")
    encoded = signature.get("value")
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "component-map attestation signature is not canonical base64"
        ) from exc
    if (
        not isinstance(encoded, str)
        or len(decoded) != 64
        or base64.b64encode(decoded).decode("ascii") != encoded
    ):
        raise ValueError("component-map attestation signature must encode 64 bytes")
    try:
        mapper.public_key.verify(
            decoded,
            canonical_component_map_attestation_payload(attestation),
        )
    except InvalidSignature as exc:
        raise ValueError("component-map attestation signature is invalid") from exc
    expected = {
        "source_sha256": source_sha256,
        "component_map_sha256": component_map_sha256,
        "mapper_contract": mapper_contract,
        "calibration_evidence_sha256": calibration_evidence_sha256,
        "corpus_run_id": corpus_run_id,
    }
    for field_name, expected_value in expected.items():
        if attestation.get(field_name) != expected_value:
            raise ValueError(
                f"component-map attestation {field_name} binding differs"
            )


def _component_mapper_contract_binding(
    config: Json,
    *,
    repository_root: Path,
) -> tuple[str, str]:
    """Return the current hash-pinned mapper contract identity and calibration."""

    frozen = config.get("frozen_components")
    raw_pin = (
        frozen.get("assignment_component_mapper_contract")
        if isinstance(frozen, dict)
        else None
    )
    match = _FROZEN_COMPONENT_PIN.fullmatch(raw_pin) if isinstance(raw_pin, str) else None
    if match is None:
        raise ValueError("frozen component-map mapper contract pin is unavailable")
    root = repository_root.resolve()
    relative = match.group("path")
    if Path(relative).is_absolute():
        raise ValueError("frozen component-map mapper contract path is not relative")
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("frozen component-map mapper contract is unavailable")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != match.group("sha256"):
        raise ValueError("frozen component-map mapper contract hash differs")
    try:
        contract = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError("frozen component-map mapper contract is invalid JSON") from exc
    if not isinstance(contract, dict) or set(contract) != {
        "schema_version",
        "mapper_contract",
        "calibration_evidence_sha256",
        "minimum_tested_source_count",
        "required_component_kinds",
        "coverage_policy",
    }:
        raise ValueError("frozen component-map mapper contract is malformed")
    mapper_contract = contract.get("mapper_contract")
    calibration_sha256 = contract.get("calibration_evidence_sha256")
    minimum_source_count = contract.get("minimum_tested_source_count")
    if (
        contract.get("schema_version")
        != "facetta-frozen-component-mapper-contract.v1"
        or not isinstance(mapper_contract, str)
        or not mapper_contract
        or not _sha256(calibration_sha256)
        or not isinstance(minimum_source_count, int)
        or isinstance(minimum_source_count, bool)
        or minimum_source_count < 144
        or contract.get("required_component_kinds")
        != sorted(_RING_REQUIRED_COMPONENT_KINDS)
        or contract.get("coverage_policy")
        != "all-required-kinds-unresolved.v1"
    ):
        raise ValueError("frozen component-map mapper contract is unsupported")
    return mapper_contract, calibration_sha256


def load_enrolled_assignment_reviewer(
    config: Json,
    *,
    repository_root: Path,
) -> EnrolledAssignmentReviewer:
    """Load one strict, repository-confined assignment-review enrollment."""

    configured = config.get(ASSIGNMENT_REVIEWER_CONFIG_KEY)
    if not isinstance(configured, dict) or set(configured) != {
        "key_id",
        "path",
        "sha256",
        "reviewer_profile_sha256",
    }:
        raise ValueError("assignment reviewer public key is not completely configured")
    key_id = configured.get("key_id")
    relative = configured.get("path")
    expected_sha256 = configured.get("sha256")
    profile_sha256 = configured.get("reviewer_profile_sha256")
    if not isinstance(key_id, str) or not key_id.strip():
        raise ValueError("assignment reviewer key_id is empty")
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("assignment reviewer public-key path is invalid")
    if not _sha256(expected_sha256):
        raise ValueError("assignment reviewer public-key sha256 is invalid")
    if not _sha256(profile_sha256):
        raise ValueError("assignment reviewer profile sha256 is invalid")
    root = repository_root.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("assignment reviewer public-key file is unavailable")
    content = path.read_bytes()
    actual_sha256 = hashlib.sha256(content).hexdigest()
    if actual_sha256 != expected_sha256:
        raise ValueError("assignment reviewer public-key sha256 differs")
    return EnrolledAssignmentReviewer(
        key_id=key_id,
        reviewer_profile_sha256=profile_sha256,
        public_key_sha256=actual_sha256,
        public_key=_load_public_key(content),
    )


def canonical_assignment_bundle_payload(bundle: Json) -> bytes:
    """Canonical bytes signed by the assignment reviewer."""

    unsigned = {key: value for key, value in bundle.items() if key != "signature"}
    canonical_json = json.dumps(
        unsigned,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return ASSIGNMENT_BUNDLE_SIGNATURE_DOMAIN + canonical_json


def verify_signed_assignment_bundle(
    bundle: Json,
    config: Json,
    *,
    repository_root: Path,
) -> EnrolledAssignmentReviewer:
    """Fail closed unless a v2 bundle has a valid enrolled Ed25519 signature."""

    if bundle.get("schema_version") != SIGNED_ASSIGNMENT_BUNDLE_SCHEMA:
        raise ValueError("signed assignment bundle schema is unsupported")
    if set(bundle) != {
        "schema_version",
        "workload_sha256",
        "corpus_run_id",
        "reviewer_key_id",
        "reviewer_profile_sha256",
        "reviewed_template_sha256",
        "release_authority_decision",
        "assignments",
        "signature",
    }:
        raise ValueError("signed assignment bundle has unexpected or missing fields")
    if not _sha256(bundle.get("workload_sha256")):
        raise ValueError("signed assignment bundle workload sha256 is invalid")
    if not _sha256(bundle.get("reviewed_template_sha256")):
        raise ValueError("signed assignment bundle template sha256 is invalid")
    corpus_run_id = bundle.get("corpus_run_id")
    if not isinstance(corpus_run_id, str) or not corpus_run_id.strip():
        raise ValueError("signed assignment bundle corpus_run_id is empty")
    if not isinstance(bundle.get("assignments"), list):
        raise ValueError("signed assignment bundle assignments must be a list")
    authority_binding = bundle.get("release_authority_decision")
    if authority_binding is not None:
        if (
            not isinstance(authority_binding, dict)
            or set(authority_binding) != RELEASE_AUTHORITY_DECISION_FIELDS
        ):
            raise ValueError(
                "signed assignment bundle authority decision is malformed"
            )
        decision_time = _canonical_utc_timestamp(
            authority_binding.get("decision_time"),
            label="authority decision time",
        )
        review_time = _canonical_utc_timestamp(
            authority_binding.get("reviewed_at"),
            label="assignment review time",
        )
        if review_time > decision_time:
            raise ValueError("assignment review time follows authority decision time")
        if not _sha256(authority_binding.get("authority_decision_sha256")):
            raise ValueError(
                "signed assignment bundle authority decision sha256 is invalid"
            )
        if not _sha256(authority_binding.get("release_authority_bundle_sha256")):
            raise ValueError(
                "signed assignment bundle release authority config sha256 is invalid"
            )
    reviewer = load_enrolled_assignment_reviewer(
        config,
        repository_root=repository_root,
    )
    if bundle.get("reviewer_key_id") != reviewer.key_id:
        raise ValueError("signed assignment bundle reviewer key differs from enrollment")
    if bundle.get("reviewer_profile_sha256") != reviewer.reviewer_profile_sha256:
        raise ValueError("signed assignment bundle reviewer profile differs from enrollment")
    signature = bundle.get("signature")
    if not isinstance(signature, dict) or set(signature) != {
        "algorithm",
        "key_id",
        "value",
    }:
        raise ValueError("signed assignment bundle signature is malformed")
    if signature.get("algorithm") != "Ed25519" or signature.get("key_id") != reviewer.key_id:
        raise ValueError("signed assignment bundle signature enrollment differs")
    encoded = signature.get("value")
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (TypeError, ValueError) as exc:
        raise ValueError("signed assignment bundle signature is not canonical base64") from exc
    if (
        not isinstance(encoded, str)
        or len(decoded) != 64
        or base64.b64encode(decoded).decode("ascii") != encoded
    ):
        raise ValueError("signed assignment bundle signature must encode 64 bytes")
    try:
        reviewer.public_key.verify(decoded, canonical_assignment_bundle_payload(bundle))
    except InvalidSignature as exc:
        raise ValueError("signed assignment bundle signature is invalid") from exc
    for row in bundle["assignments"]:
        if not isinstance(row, dict) or set(row) != ASSIGNMENT_BUNDLE_ROW_FIELDS:
            raise ValueError(
                "signed assignment bundle row has unexpected or missing fields"
            )
        binding = row["binding"]
        if not isinstance(binding, dict):
            raise ValueError("signed assignment bundle binding must be an object")
        applicability = binding.get("applicability")
        if applicability == "execute":
            expected_binding_fields = EXECUTE_ASSIGNMENT_BINDING_FIELDS
        elif applicability == "not_applicable":
            reason = binding.get("not_applicable_reason")
            if reason not in SUPPORTED_NOT_APPLICABLE_REASONS:
                raise ValueError(
                    "signed assignment bundle not-applicable reason is unsupported"
                )
            if row.get("kind") != "edit":
                raise ValueError(
                    "signed assignment bundle render cannot be not_applicable"
                )
            expected_binding_fields = (
                SOURCE_COMPONENT_ABSENT_BINDING_FIELDS
                if reason == SOURCE_COMPONENT_ABSENT_REASON
                else CANONICAL_DELTA_INAPPLICABLE_BINDING_FIELDS
            )
        else:
            raise ValueError(
                "signed assignment bundle binding applicability is not terminal"
            )
        if set(binding) != expected_binding_fields:
            raise ValueError(
                "signed assignment bundle binding has unexpected or missing fields"
            )
        component_map_attestation_sha256 = binding.get(
            "component_map_attestation_sha256"
        )
        if (
            expected_binding_fields == SOURCE_COMPONENT_ABSENT_BINDING_FIELDS
            and not _sha256(component_map_attestation_sha256)
        ):
            raise ValueError(
                "signed assignment bundle component-map attestation sha256 is invalid"
            )
        if expected_binding_fields == SOURCE_COMPONENT_ABSENT_BINDING_FIELDS:
            source_sha256 = binding.get("source_sha256")
            component_map_sha256 = binding.get("component_map_sha256")
            component_map_payload = binding.get("component_map")
            attestation = binding.get("component_map_attestation")
            if not _sha256(source_sha256):
                raise ValueError(
                    "signed assignment bundle source sha256 is invalid"
                )
            if not isinstance(attestation, dict):
                raise ValueError(
                    "signed assignment bundle component-map attestation is missing"
                )
            if not isinstance(component_map_payload, dict):
                raise ValueError(
                    "signed assignment bundle component map is missing"
                )
            try:
                component_map = RevisionComponentMap.model_validate(
                    component_map_payload
                )
            except ValueError as exc:
                raise ValueError(
                    "signed assignment bundle component map is invalid"
                ) from exc
            if component_map_hash(component_map) != component_map_sha256:
                raise ValueError(
                    "signed assignment bundle component map hash differs"
                )
            if component_map.asset_sha256 != source_sha256:
                raise ValueError(
                    "signed assignment bundle component map source differs"
                )
            if (
                _canonical_object_sha256(attestation)
                != component_map_attestation_sha256
            ):
                raise ValueError(
                    "signed assignment bundle component-map attestation hash differs"
                )
            mapper = load_enrolled_component_mapper(
                config,
                repository_root=repository_root,
                reviewer=reviewer,
            )
            mapper_contract, calibration_sha256 = (
                _component_mapper_contract_binding(
                    config,
                    repository_root=repository_root,
                )
            )
            if (
                component_map.mapper_contract != mapper_contract
                or component_map.calibration_evidence_sha256
                != calibration_sha256
            ):
                raise ValueError(
                    "signed assignment bundle component map provenance differs"
                )
            verify_component_map_attestation(
                attestation,
                mapper=mapper,
                source_sha256=source_sha256,
                component_map_sha256=component_map_sha256,
                mapper_contract=mapper_contract,
                calibration_evidence_sha256=calibration_sha256,
                corpus_run_id=corpus_run_id,
            )
            required_kinds = EDIT_REQUIRED_COMPONENT_KINDS.get(
                str(row.get("evaluation_id") or "")
            )
            if row.get("kind") != "edit" or required_kinds is None:
                raise ValueError(
                    "source-component absence is not defined for this evaluation"
                )
            resolved_required_kinds = sorted({
                component.kind
                for component in component_map.components
                if component.kind in required_kinds
                and component.resolution == "resolved"
            })
            if resolved_required_kinds:
                raise ValueError(
                    "source-component absence contradicts resolved component kinds: "
                    + ", ".join(resolved_required_kinds)
                )
        elif (
            expected_binding_fields
            == CANONICAL_DELTA_INAPPLICABLE_BINDING_FIELDS
        ):
            source_sha256 = binding.get("source_sha256")
            if not _sha256(source_sha256):
                raise ValueError(
                    "signed assignment bundle source sha256 is invalid"
                )
            source_spec_payload = binding.get("source_spec")
            canonical_edit_issues = binding.get("canonical_edit_issues")
            if not isinstance(source_spec_payload, dict):
                raise ValueError(
                    "signed assignment bundle canonical source spec is missing"
                )
            try:
                source_spec = Spec.model_validate(source_spec_payload)
            except ValueError as exc:
                raise ValueError(
                    "signed assignment bundle canonical source spec is invalid"
                ) from exc
            edit = next(
                (
                    candidate
                    for candidate in CANONICAL_RING_EDITS
                    if candidate.id == row.get("evaluation_id")
                ),
                None,
            )
            if edit is None:
                raise ValueError(
                    "canonical-delta absence is not defined for this evaluation"
                )
            target_spec, issues = apply_canonical_ring_edit(source_spec, edit)
            if target_spec is not None or not issues:
                raise ValueError(
                    "canonical-delta absence contradicts a valid canonical edit"
                )
            if canonical_edit_issues != issues:
                raise ValueError(
                    "canonical-delta absence issues differ from deterministic result"
                )
    if authority_binding is None:
        if _requires_release_authority_decision(config):
            raise ValueError(
                "signed assignment bundle release authority decision is required"
            )
        return reviewer

    decision_time = _canonical_utc_timestamp(
        authority_binding["decision_time"],
        label="authority decision time",
    )
    authority_decision = verify_release_authority_bundle(
        config,
        repository_root,
        decision_time,
    )
    roles = {
        row.get("role")
        for row in authority_decision.get("authorities", [])
        if isinstance(row, dict)
    }
    if (
        authority_decision.get("status") != "pass"
        or authority_decision.get("decision_time")
        != authority_binding["decision_time"]
        or "assignment_reviewer" not in roles
    ):
        raise ValueError(
            "signed assignment bundle release authority decision is not active"
        )
    expected_authority_binding = build_release_authority_decision_binding(
        config,
        authority_decision,
        reviewed_at=authority_binding["reviewed_at"],
    )
    if (
        expected_authority_binding["authority_decision_sha256"]
        != authority_binding["authority_decision_sha256"]
    ):
        raise ValueError(
            "signed assignment bundle release authority decision differs"
        )
    if (
        expected_authority_binding["release_authority_bundle_sha256"]
        != authority_binding["release_authority_bundle_sha256"]
    ):
        raise ValueError(
            "signed assignment bundle release authority config differs"
        )
    return reviewer


__all__ = [
    "ASSIGNMENT_REVIEWER_CONFIG_KEY",
    "ASSIGNMENT_BUNDLE_ROW_FIELDS",
    "ASSIGNMENT_BUNDLE_SIGNATURE_DOMAIN",
    "CANONICAL_DELTA_INAPPLICABLE_REASON",
    "CANONICAL_DELTA_INAPPLICABLE_BINDING_FIELDS",
    "COMPONENT_MAP_ATTESTATION_SCHEMA",
    "COMPONENT_MAP_ATTESTATION_SIGNATURE_DOMAIN",
    "COMPONENT_MAPPER_CONFIG_KEY",
    "EnrolledComponentMapper",
    "EDIT_REQUIRED_COMPONENT_KINDS",
    "EnrolledAssignmentReviewer",
    "EXECUTE_ASSIGNMENT_BINDING_FIELDS",
    "NOT_APPLICABLE_ASSIGNMENT_BINDING_FIELDS",
    "RELEASE_AUTHORITY_DECISION_FIELDS",
    "SIGNED_ASSIGNMENT_BUNDLE_SCHEMA",
    "SOURCE_COMPONENT_ABSENT_REASON",
    "SOURCE_COMPONENT_ABSENT_BINDING_FIELDS",
    "SUPPORTED_NOT_APPLICABLE_REASONS",
    "build_release_authority_decision_binding",
    "canonical_assignment_bundle_payload",
    "canonical_component_map_attestation_payload",
    "load_enrolled_assignment_reviewer",
    "load_enrolled_component_mapper",
    "verify_component_map_attestation",
    "verify_signed_assignment_bundle",
]

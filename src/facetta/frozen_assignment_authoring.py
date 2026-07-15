"""Provider-free authoring for signed frozen source assignments.

The human-facing workbook is deliberately not an executable bundle.  It locks
the workload identities and exposes only evidence references, an applicability
decision, and a versioned non-applicable detail code.  Validation reopens all
evidence beneath one retained-evidence root, derives specifications and edit
targets, and compiles strict assignment rows.  Finalization additionally
requires the active seven-role release-authority decision and signs the v2
bundle with the dedicated assignment-reviewer key.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    load_pem_private_key,
)

from facetta.frozen_assignment_contract import (
    COMPONENT_MAP_ATTESTATION_SCHEMA,
    COMPONENT_MAP_ATTESTATION_SIGNATURE_DOMAIN,
    COMPONENT_MAPPER_CONFIG_KEY,
    EDIT_REQUIRED_COMPONENT_KINDS,
    EnrolledAssignmentReviewer,
    EnrolledComponentMapper,
    SIGNED_ASSIGNMENT_BUNDLE_SCHEMA,
    build_release_authority_decision_binding,
    canonical_assignment_bundle_payload,
    canonical_component_map_attestation_payload,
    load_enrolled_component_mapper,
    verify_component_map_attestation,
    verify_signed_assignment_bundle,
)
from facetta.frozen_capture_workload import (
    canonical_object_sha256,
    file_sha256,
    validate_workload_definition,
)
from facetta.frozen_evidence_paths import confined_path, relative_artifact_path
from facetta.release_authority_bundle import verify_release_authority_bundle
from facetta.revision_component_map import (
    RING_REQUIRED_KINDS,
    RevisionComponentMap,
    bind_map_to_raster,
    component_map_hash,
)
from facetta.ring_evals import (
    CANONICAL_RING_EDITS,
    RING_GOLDEN_CASES,
    apply_canonical_ring_edit,
    build_ring_golden_spec,
)
from facetta.spec import Spec


Json = dict[str, Any]

ASSIGNMENT_AUTHORING_TEMPLATE_SCHEMA = (
    "facetta-frozen-assignment-authoring-template.v2"
)
ASSIGNMENT_VALIDATION_SCHEMA = "facetta-frozen-assignment-validation.v1"
SOURCE_SPEC_EVIDENCE_SCHEMA = "facetta-frozen-source-spec-evidence.v1"
ASSIGNMENT_REVIEW_EVIDENCE_SCHEMA = "facetta-frozen-assignment-review-evidence.v2"
ASSIGNMENT_REGION_EVIDENCE_SCHEMA = "facetta-frozen-assignment-region-evidence.v1"
COMPONENT_MAPPER_CONTRACT_SCHEMA = (
    "facetta-frozen-component-mapper-contract.v1"
)
COMPONENT_MAP_CALIBRATION_EVIDENCE_SCHEMA = (
    "facetta-frozen-component-map-calibration-evidence.v1"
)
_OPAQUE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{6,127}\Z")
_OPAQUE_REVIEWER_ID = re.compile(r"rvr_[0-9a-f]{64}\Z")
_IANA_TIMEZONE = re.compile(
    r"[A-Za-z][A-Za-z0-9._+-]*(?:/[A-Za-z0-9._+-]+)+\Z"
)
_REASON_CODES = {
    "canonical_delta_inapplicable",
    "source_component_absent",
}
_REASON_DETAIL_CODES = MappingProxyType({
    "source_component_absent": "component-map-all-required-kinds-absent.v1",
    "canonical_delta_inapplicable": "canonical-edit-apply-failed.v1",
})
_EVIDENCE_ROLES = {
    "assignment_region_evidence",
    "assignment_review_evidence",
    "component_map_evidence",
    "component_map_calibration_evidence",
    "component_map_attestation_evidence",
    "source_raster",
    "source_spec_evidence",
}
_FROZEN_COMPONENT_PIN = re.compile(
    r"(?P<path>[^@]+)@sha256:(?P<sha256>[0-9a-f]{64})\Z"
)
_COMPILATION_INTEGRITY_DOMAIN = "facetta:frozen-assignment-compilation:v1"

_EDIT_REQUIRED_COMPONENT_KINDS = EDIT_REQUIRED_COMPONENT_KINDS


@dataclass(frozen=True)
class AssignmentCompilation:
    unsigned_bundle: Json
    validation: Json
    integrity_sha256: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "integrity_sha256",
            _compilation_integrity_sha256(self.unsigned_bundle, self.validation),
        )


def _compilation_integrity_sha256(
    unsigned_bundle: Json,
    validation: Json,
) -> str:
    return canonical_object_sha256({
        "domain": _COMPILATION_INTEGRITY_DOMAIN,
        "unsigned_bundle": unsigned_bundle,
        "validation": validation,
    })


def _verify_compilation_integrity(
    unsigned_bundle: Json,
    validation: Json,
    expected_integrity_sha256: str,
) -> None:
    actual_integrity_sha256 = _compilation_integrity_sha256(
        unsigned_bundle,
        validation,
    )
    if not hmac.compare_digest(
        expected_integrity_sha256,
        actual_integrity_sha256,
    ):
        raise ValueError(
            "assignment compilation integrity differs from validated state"
        )
    if unsigned_bundle.get("signature") is not None:
        raise ValueError("assignment compilation unsigned bundle is already signed")
    if validation.get("unsigned_bundle_sha256") != canonical_object_sha256(
        unsigned_bundle
    ):
        raise ValueError(
            "assignment compilation validation differs from the unsigned bundle"
        )
    for field_name in (
        "workload_sha256",
        "corpus_run_id",
        "reviewer_key_id",
        "reviewer_profile_sha256",
        "reviewed_template_sha256",
    ):
        if validation.get(field_name) != unsigned_bundle.get(field_name):
            raise ValueError(
                f"assignment compilation {field_name} differs between validation "
                "and unsigned bundle"
            )
    assignments = unsigned_bundle.get("assignments")
    source_summaries = validation.get("source_summaries")
    if not isinstance(assignments, list) or not isinstance(source_summaries, list):
        raise ValueError("assignment compilation validation counts are invalid")
    applicability = [
        row.get("binding", {}).get("applicability")
        for row in assignments
        if isinstance(row, dict) and isinstance(row.get("binding"), dict)
    ]
    expected_counts = {
        "source_count": len(source_summaries),
        "assignment_count": len(assignments),
        "execute_count": applicability.count("execute"),
        "not_applicable_count": applicability.count("not_applicable"),
        "unresolved_count": 0,
    }
    if any(validation.get(name) != value for name, value in expected_counts.items()):
        raise ValueError("assignment compilation validation counts are incoherent")
    if len(applicability) != len(assignments):
        raise ValueError("assignment compilation contains an invalid assignment binding")


def _object(path: Path, *, label: str) -> Json:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _exact(value: object, keys: set[str], *, label: str) -> Json:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{label} has unexpected or missing fields")
    return value


def _sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and re.fullmatch(r"[0-9a-f]{64}", value) is not None
    )


def _utc_timestamp(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a timezone offset")
    return value


def _canonical_utc_timestamp(value: object, *, label: str) -> str:
    parsed_value = _utc_timestamp(value, label=label)
    parsed = datetime.fromisoformat(parsed_value.replace("Z", "+00:00"))
    return parsed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonical_iana_timezone(value: object) -> str:
    if (
        not isinstance(value, str)
        or not _IANA_TIMEZONE.fullmatch(value)
        or len(value) > 80
    ):
        raise ValueError("assignment review timezone must be a canonical IANA name")
    try:
        timezone = ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(
            "assignment review timezone must be a canonical IANA name"
        ) from exc
    if timezone.key != value:
        raise ValueError("assignment review timezone must be a canonical IANA name")
    return value


def _required_component_kinds(kind: str, evaluation_id: str) -> frozenset[str]:
    if kind == "render":
        return frozenset()
    required = _EDIT_REQUIRED_COMPONENT_KINDS.get(evaluation_id)
    if required is None:
        raise ValueError(f"unknown edit assignment: {evaluation_id}")
    return required


def _resolved_component_ids_for_kinds(
    component_map: RevisionComponentMap,
    required_kinds: frozenset[str],
) -> tuple[list[str], list[str]]:
    resolved_by_kind = {
        kind: sorted(
            component.component_id
            for component in component_map.components
            if component.kind == kind and component.resolution == "resolved"
        )
        for kind in required_kinds
    }
    missing_kinds = sorted(
        kind for kind, component_ids in resolved_by_kind.items() if not component_ids
    )
    resolved_ids = sorted(
        component_id
        for component_ids in resolved_by_kind.values()
        for component_id in component_ids
    )
    return resolved_ids, missing_kinds


def _relative_evidence(
    root: Path,
    value: object,
    *,
    label: str,
) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} reference is required")
    return confined_path(
        root,
        value,
        label=label,
        kind="file",
        require_relative=True,
    )


def _quality_scope(workload: Json) -> tuple[list[Json], list[Json]]:
    ring_set_id = workload.get("ring_quality_evaluation_set_id")
    sets = workload.get("evaluation_sets")
    evaluations = sets.get(ring_set_id) if isinstance(sets, dict) else None
    sources = workload.get("sources")
    if not isinstance(evaluations, list) or not all(
        isinstance(row, dict) for row in evaluations
    ):
        raise ValueError("frozen assignment evaluation set is unavailable")
    if not isinstance(sources, list) or not all(isinstance(row, dict) for row in sources):
        raise ValueError("frozen assignment sources are unavailable")
    quality_sources = [row for row in sources if isinstance(row.get("quality"), dict)]
    return (
        sorted(quality_sources, key=lambda row: str(row["filename"])),
        sorted(
            evaluations,
            key=lambda row: (str(row["kind"]), str(row["evaluation_id"])),
        ),
    )


def _locked_evaluation(evaluation: Json) -> Json:
    return {
        "kind": evaluation["kind"],
        "evaluation_id": evaluation["evaluation_id"],
        "operation_class": evaluation["operation_class"],
    }


def build_assignment_authoring_template(
    manifest_path: Path,
    config_path: Path,
    workload_path: Path,
    *,
    corpus_run_id: str,
    reviewer: EnrolledAssignmentReviewer,
    repository_root: Path,
) -> Json:
    """Create a deterministic, non-executable workbook for one frozen run."""

    if not _OPAQUE_ID.fullmatch(corpus_run_id):
        raise ValueError("corpus_run_id must be an opaque 7-128 character identifier")
    definition = validate_workload_definition(
        manifest_path,
        config_path,
        workload_path,
        repository_root=repository_root,
    )
    if definition["status"] != "pass":
        raise ValueError(
            "invalid frozen assignment definition: "
            + "; ".join(definition["errors"])
        )
    workload = _object(workload_path, label="frozen workload")
    sources, evaluations = _quality_scope(workload)
    bindings = {
        "manifest_sha256": file_sha256(manifest_path),
        "config_sha256": file_sha256(config_path),
        "workload_sha256": file_sha256(workload_path),
        "workload_id": workload["workload_id"],
        "corpus_run_id": corpus_run_id,
        "reviewer_key_id": reviewer.key_id,
        "reviewer_profile_sha256": reviewer.reviewer_profile_sha256,
        "sources": [
            {
                "source_filename": source["filename"],
                "source_sha256": source["sha256"],
                "evaluations": [_locked_evaluation(row) for row in evaluations],
            }
            for source in sources
        ],
    }
    return {
        "schema_version": ASSIGNMENT_AUTHORING_TEMPLATE_SCHEMA,
        "bindings": bindings,
        "review": {
            "reviewer_id": None,
            "review_timezone": None,
            "reviewed_at": None,
            "sources": [
                {
                    "source_filename": source["filename"],
                    "source_spec_evidence_ref": None,
                    "component_map_evidence_ref": None,
                    "component_map_calibration_evidence_ref": None,
                    "component_map_attestation_ref": None,
                    "evaluations": [
                        {
                            "kind": evaluation["kind"],
                            "evaluation_id": evaluation["evaluation_id"],
                            "applicability": None,
                            "review_evidence_ref": None,
                            "region_evidence_ref": None,
                            "not_applicable_reason_code": None,
                            "not_applicable_detail_code": None,
                        }
                        for evaluation in evaluations
                    ],
                }
                for source in sources
            ],
        },
    }


def _source_spec_evidence(
    path: Path,
    *,
    source_filename: str,
    source_sha256: str,
) -> Spec:
    evidence = _exact(
        _object(path, label="source-spec evidence"),
        {"schema_version", "source_filename", "source_sha256", "spec"},
        label="source-spec evidence",
    )
    if evidence.get("schema_version") != SOURCE_SPEC_EVIDENCE_SCHEMA:
        raise ValueError("source-spec evidence schema is unsupported")
    if (
        evidence.get("source_filename") != source_filename
        or evidence.get("source_sha256") != source_sha256
    ):
        raise ValueError("source-spec evidence source binding differs")
    spec = Spec.model_validate(evidence.get("spec"))
    if not _OPAQUE_ID.fullmatch(spec.design_id) or not _OPAQUE_ID.fullmatch(
        spec.created_by
    ):
        raise ValueError("source spec must use opaque design and creator identifiers")
    if spec.jewelry_type != "ring":
        raise ValueError("frozen assignment source spec must describe a ring")
    return spec


def _component_map_evidence(
    path: Path,
    *,
    image_bytes: bytes,
) -> RevisionComponentMap:
    component_map = RevisionComponentMap.model_validate(
        _object(path, label="component-map evidence")
    )
    bind_map_to_raster(component_map, image_bytes)
    return component_map


def _component_map_absence_provenance(
    config: Json,
    *,
    repository_root: Path,
    evidence_root: Path,
    calibration_evidence_ref: object,
    attestation_ref: object,
    source_sha256: str,
    corpus_run_id: str,
    reviewer: EnrolledAssignmentReviewer,
    component_map: RevisionComponentMap,
) -> tuple[Path, Path, Json]:
    frozen_components = config.get("frozen_components")
    if not isinstance(frozen_components, dict):
        raise ValueError("frozen component-map mapper contract is unavailable")
    raw_pin = frozen_components.get("assignment_component_mapper_contract")
    match = _FROZEN_COMPONENT_PIN.fullmatch(raw_pin) if isinstance(raw_pin, str) else None
    if match is None:
        raise ValueError("frozen component-map mapper contract pin is unavailable")
    contract_path = confined_path(
        repository_root.resolve(),
        match.group("path"),
        label="component-map mapper contract",
        kind="file",
        require_relative=True,
    )
    if file_sha256(contract_path) != match.group("sha256"):
        raise ValueError("frozen component-map mapper contract hash differs")
    contract = _exact(
        _object(contract_path, label="component-map mapper contract"),
        {
            "schema_version",
            "mapper_contract",
            "calibration_evidence_sha256",
            "minimum_tested_source_count",
            "required_component_kinds",
            "coverage_policy",
        },
        label="component-map mapper contract",
    )
    if contract.get("schema_version") != COMPONENT_MAPPER_CONTRACT_SCHEMA:
        raise ValueError("component-map mapper contract schema is unsupported")
    if contract.get("mapper_contract") != component_map.mapper_contract:
        raise ValueError("component-map mapper contract identity differs")
    required_kinds = contract.get("required_component_kinds")
    if required_kinds != sorted(RING_REQUIRED_KINDS):
        raise ValueError("component-map mapper contract coverage is incomplete")
    if contract.get("coverage_policy") != "all-required-kinds-unresolved.v1":
        raise ValueError("component-map mapper contract coverage policy is unsupported")
    minimum_source_count = contract.get("minimum_tested_source_count")
    if (
        not isinstance(minimum_source_count, int)
        or isinstance(minimum_source_count, bool)
        or minimum_source_count < 144
    ):
        raise ValueError("component-map mapper contract calibration scope is insufficient")
    calibration_sha256 = contract.get("calibration_evidence_sha256")
    if (
        not isinstance(calibration_sha256, str)
        or not re.fullmatch(r"[0-9a-f]{64}", calibration_sha256)
        or component_map.calibration_evidence_sha256 != calibration_sha256
    ):
        raise ValueError("component-map calibration provenance differs")
    calibration_path = _relative_evidence(
        evidence_root.resolve(),
        calibration_evidence_ref,
        label="component-map calibration evidence",
    )
    if file_sha256(calibration_path) != calibration_sha256:
        raise ValueError("component-map calibration evidence hash differs")
    calibration = _exact(
        _object(calibration_path, label="component-map calibration evidence"),
        {
            "schema_version",
            "mapper_contract",
            "calibration_run_id",
            "status",
            "tested_source_count",
            "required_component_kinds",
            "unresolved_false_absence_count",
        },
        label="component-map calibration evidence",
    )
    tested_source_count = calibration.get("tested_source_count")
    if (
        calibration.get("schema_version")
        != COMPONENT_MAP_CALIBRATION_EVIDENCE_SCHEMA
        or calibration.get("mapper_contract") != component_map.mapper_contract
        or not isinstance(calibration.get("calibration_run_id"), str)
        or not _OPAQUE_ID.fullmatch(calibration["calibration_run_id"])
        or calibration.get("status") != "pass"
        or not isinstance(tested_source_count, int)
        or isinstance(tested_source_count, bool)
        or tested_source_count < minimum_source_count
        or calibration.get("required_component_kinds")
        != sorted(RING_REQUIRED_KINDS)
        or calibration.get("unresolved_false_absence_count") != 0
    ):
        raise ValueError("component-map calibration evidence is not release-qualified")
    mapper = load_enrolled_component_mapper(
        config,
        repository_root=repository_root,
        reviewer=reviewer,
    )
    attestation_path = _relative_evidence(
        evidence_root.resolve(),
        attestation_ref,
        label="component-map attestation evidence",
    )
    attestation = _object(
        attestation_path,
        label="component-map attestation evidence",
    )
    verify_component_map_attestation(
        attestation,
        mapper=mapper,
        source_sha256=source_sha256,
        component_map_sha256=component_map_hash(component_map),
        mapper_contract=component_map.mapper_contract,
        calibration_evidence_sha256=calibration_sha256,
        corpus_run_id=corpus_run_id,
    )
    return calibration_path, attestation_path, attestation


def _review_evidence(
    path: Path,
    *,
    source_filename: str,
    source_sha256: str,
    evaluation: Json,
    applicability: str,
    reason_code: str | None,
    detail_code: str | None,
    reviewer: EnrolledAssignmentReviewer,
) -> None:
    evidence = _exact(
        _object(path, label="assignment-review evidence"),
        {
            "schema_version",
            "source_filename",
            "source_sha256",
            "kind",
            "evaluation_id",
            "applicability",
            "not_applicable_reason_code",
            "not_applicable_detail_code",
            "reviewer_key_id",
            "reviewer_profile_sha256",
        },
        label="assignment-review evidence",
    )
    expected = {
        "schema_version": ASSIGNMENT_REVIEW_EVIDENCE_SCHEMA,
        "source_filename": source_filename,
        "source_sha256": source_sha256,
        "kind": evaluation["kind"],
        "evaluation_id": evaluation["evaluation_id"],
        "applicability": applicability,
        "not_applicable_reason_code": reason_code,
        "not_applicable_detail_code": detail_code,
        "reviewer_key_id": reviewer.key_id,
        "reviewer_profile_sha256": reviewer.reviewer_profile_sha256,
    }
    if evidence != expected:
        raise ValueError("assignment-review evidence differs from the signed workbook")


def _region_evidence(
    path: Path,
    *,
    source_filename: str,
    source_sha256: str,
    evaluation: Json,
    expected_region: str | None,
    component_map: RevisionComponentMap,
    required_kinds: frozenset[str],
) -> None:
    evidence = _exact(
        _object(path, label="assignment-region evidence"),
        {
            "schema_version",
            "source_filename",
            "source_sha256",
            "kind",
            "evaluation_id",
            "region_description",
            "component_ids",
        },
        label="assignment-region evidence",
    )
    if evidence.get("schema_version") != ASSIGNMENT_REGION_EVIDENCE_SCHEMA:
        raise ValueError("assignment-region evidence schema is unsupported")
    expected_identity = {
        "source_filename": source_filename,
        "source_sha256": source_sha256,
        "kind": evaluation["kind"],
        "evaluation_id": evaluation["evaluation_id"],
        "region_description": expected_region,
    }
    if any(evidence.get(key) != value for key, value in expected_identity.items()):
        raise ValueError("assignment-region evidence binding differs")
    component_ids = evidence.get("component_ids")
    if not isinstance(component_ids, list) or component_ids != sorted(set(component_ids)):
        raise ValueError("assignment-region component IDs must be unique and sorted")
    components_by_id = {
        component.component_id: component for component in component_map.components
    }
    if any(
        not isinstance(value, str) or value not in components_by_id
        for value in component_ids
    ):
        raise ValueError("assignment-region evidence names an unknown component")
    if any(
        components_by_id[component_id].resolution != "resolved"
        for component_id in component_ids
    ):
        raise ValueError("assignment-region evidence names an unresolved component")
    required_ids, missing_kinds = _resolved_component_ids_for_kinds(
        component_map,
        required_kinds,
    )
    if missing_kinds:
        raise ValueError(
            "assignment-region evidence lacks resolved component kinds: "
            + ", ".join(missing_kinds)
        )
    if component_ids != required_ids:
        raise ValueError(
            "assignment-region component IDs differ from the required semantic scope"
        )


def _private_key(
    path: Path,
    *,
    repository_root: Path,
    evidence_root: Path,
) -> Ed25519PrivateKey:
    resolved = path.resolve()
    if not resolved.is_file():
        raise ValueError("assignment reviewer private key is unavailable")
    if resolved.is_relative_to(repository_root.resolve()) or resolved.is_relative_to(
        evidence_root.resolve()
    ):
        raise ValueError(
            "assignment reviewer private key must remain outside the repository "
            "and evidence root"
        )
    if resolved.stat().st_mode & 0o077:
        raise ValueError(
            "assignment reviewer private key must not be group- or world-accessible"
        )
    content = resolved.read_bytes()
    try:
        if len(content) == 32:
            return Ed25519PrivateKey.from_private_bytes(content)
        loaded = load_pem_private_key(content, password=None)
    except (TypeError, ValueError) as exc:
        raise ValueError("assignment reviewer private key is invalid") from exc
    if not isinstance(loaded, Ed25519PrivateKey):
        raise ValueError("assignment reviewer private key is not Ed25519")
    return loaded


def _verify_compilation_evidence(validation: Json, evidence_root: Path) -> None:
    """Reopen every retained input immediately before signing.

    Validation and signing are intentionally separate operator steps.  A
    retained file can therefore disappear, be replaced, or be redirected by a
    symlink after compilation.  The signature must never bless the stale
    in-memory hashes in that situation.
    """

    root = evidence_root.resolve()
    if not root.is_dir():
        raise ValueError("assignment evidence root is unavailable")
    artifacts = validation.get("evidence_artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError("assignment validation evidence artifacts are unavailable")
    seen: set[str] = set()
    for index, raw in enumerate(artifacts, 1):
        artifact = _exact(
            raw,
            {"path", "sha256", "roles"},
            label=f"assignment evidence artifact {index}",
        )
        relative = artifact.get("path")
        expected_sha256 = artifact.get("sha256")
        roles = artifact.get("roles")
        if (
            not isinstance(relative, str)
            or not relative
            or Path(relative).is_absolute()
        ):
            raise ValueError(
                f"assignment evidence artifact {index} path must be relative"
            )
        if (
            not isinstance(expected_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)
        ):
            raise ValueError(
                f"assignment evidence artifact {index} sha256 is invalid"
            )
        if (
            not isinstance(roles, list)
            or not roles
            or roles != sorted(set(roles))
            or any(role not in _EVIDENCE_ROLES for role in roles)
        ):
            raise ValueError(
                f"assignment evidence artifact {index} roles are invalid"
            )
        path = confined_path(
            root,
            relative,
            label=f"assignment evidence artifact {index}",
            kind="file",
            require_relative=True,
        )
        normalized = path.relative_to(root).as_posix()
        if relative != normalized:
            raise ValueError(
                f"assignment evidence artifact {index} path is not canonical"
            )
        if normalized in seen:
            raise ValueError("assignment evidence artifact paths must be unique")
        seen.add(normalized)
        if file_sha256(path) != expected_sha256:
            raise ValueError(
                f"assignment evidence artifact hash drifted: {normalized}"
            )


def validate_completed_assignment_template(
    manifest_path: Path,
    config_path: Path,
    workload_path: Path,
    completed_template: Json,
    *,
    reviewer: EnrolledAssignmentReviewer,
    evidence_root: Path,
    source_dir: Path,
    repository_root: Path,
) -> AssignmentCompilation:
    """Compile exact evidence-backed rows without signing or provider calls."""

    config = _object(config_path, label="frozen config")
    template = _exact(
        completed_template,
        {"schema_version", "bindings", "review"},
        label="assignment authoring template",
    )
    if template.get("schema_version") != ASSIGNMENT_AUTHORING_TEMPLATE_SCHEMA:
        raise ValueError("assignment authoring template schema is unsupported")
    bindings = _exact(
        template.get("bindings"),
        {
            "manifest_sha256",
            "config_sha256",
            "workload_sha256",
            "workload_id",
            "corpus_run_id",
            "reviewer_key_id",
            "reviewer_profile_sha256",
            "sources",
        },
        label="assignment template bindings",
    )
    corpus_run_id = bindings.get("corpus_run_id")
    if not isinstance(corpus_run_id, str):
        raise ValueError("assignment template corpus_run_id is invalid")
    expected_bindings = build_assignment_authoring_template(
        manifest_path,
        config_path,
        workload_path,
        corpus_run_id=corpus_run_id,
        reviewer=reviewer,
        repository_root=repository_root,
    )["bindings"]
    if bindings != expected_bindings:
        raise ValueError("assignment template bindings differ from frozen inputs")
    review = _exact(
        template.get("review"),
        {"reviewer_id", "review_timezone", "reviewed_at", "sources"},
        label="assignment review",
    )
    reviewer_id = review.get("reviewer_id")
    if (
        not isinstance(reviewer_id, str)
        or not _OPAQUE_REVIEWER_ID.fullmatch(reviewer_id)
    ):
        raise ValueError("assignment reviewer_id must be an opaque rvr_ token")
    _canonical_iana_timezone(review.get("review_timezone"))
    reviewed_at_utc = _canonical_utc_timestamp(
        review.get("reviewed_at"),
        label="assignment reviewed_at",
    )
    source_reviews = review.get("sources")
    locked_sources = bindings["sources"]
    if not isinstance(source_reviews, list) or len(source_reviews) != len(locked_sources):
        raise ValueError("assignment review source count differs from frozen scope")

    root = evidence_root.resolve()
    resolved_source_dir = confined_path(
        root,
        source_dir,
        label="assignment source directory",
        kind="directory",
    )
    cases = {case.id: case for case in RING_GOLDEN_CASES}
    edits = {edit.id: edit for edit in CANONICAL_RING_EDITS}
    assignments: list[Json] = []
    artifacts: list[Json] = []
    source_summaries: list[Json] = []
    execute_count = 0
    not_applicable_count = 0
    for source_index, (locked_source, source_review) in enumerate(
        zip(locked_sources, source_reviews, strict=True),
        1,
    ):
        source_review = _exact(
            source_review,
            {
                "source_filename",
                "source_spec_evidence_ref",
                "component_map_evidence_ref",
                "component_map_calibration_evidence_ref",
                "component_map_attestation_ref",
                "evaluations",
            },
            label=f"assignment source review {source_index}",
        )
        filename = str(locked_source["source_filename"])
        source_sha256 = str(locked_source["source_sha256"])
        if source_review.get("source_filename") != filename:
            raise ValueError(f"assignment source review {source_index} identity differs")
        if Path(filename).is_absolute() or len(Path(filename).parts) != 1:
            raise ValueError(f"assignment source filename is not portable: {filename}")
        source_path = confined_path(
            root,
            resolved_source_dir / filename,
            label=f"assignment source {filename}",
            kind="file",
        )
        if not source_path.is_relative_to(resolved_source_dir):
            raise ValueError(f"assignment source escapes source directory: {filename}")
        image_bytes = source_path.read_bytes()
        if hashlib.sha256(image_bytes).hexdigest() != source_sha256:
            raise ValueError(f"assignment source hash differs: {filename}")
        spec_path = _relative_evidence(
            root,
            source_review.get("source_spec_evidence_ref"),
            label=f"source-spec evidence {filename}",
        )
        map_path = _relative_evidence(
            root,
            source_review.get("component_map_evidence_ref"),
            label=f"component-map evidence {filename}",
        )
        source_spec = _source_spec_evidence(
            spec_path,
            source_filename=filename,
            source_sha256=source_sha256,
        )
        component_map = _component_map_evidence(map_path, image_bytes=image_bytes)
        artifacts.extend([
            {
                "path": relative_artifact_path(root, source_path, label=filename),
                "sha256": source_sha256,
                "role": "source_raster",
            },
            {
                "path": relative_artifact_path(root, spec_path, label="source spec"),
                "sha256": file_sha256(spec_path),
                "role": "source_spec_evidence",
            },
            {
                "path": relative_artifact_path(root, map_path, label="component map"),
                "sha256": file_sha256(map_path),
                "role": "component_map_evidence",
            },
        ])
        evaluation_reviews = source_review.get("evaluations")
        locked_evaluations = locked_source["evaluations"]
        if not isinstance(evaluation_reviews, list) or len(evaluation_reviews) != len(
            locked_evaluations
        ):
            raise ValueError(f"assignment evaluations differ for {filename}")
        source_execute = 0
        source_na = 0
        for evaluation_index, (evaluation, response) in enumerate(
            zip(locked_evaluations, evaluation_reviews, strict=True),
            1,
        ):
            response = _exact(
                response,
                {
                    "kind",
                    "evaluation_id",
                    "applicability",
                    "review_evidence_ref",
                    "region_evidence_ref",
                    "not_applicable_reason_code",
                    "not_applicable_detail_code",
                },
                label=f"assignment response {filename}:{evaluation_index}",
            )
            if (
                response.get("kind") != evaluation["kind"]
                or response.get("evaluation_id") != evaluation["evaluation_id"]
            ):
                raise ValueError(f"assignment response identity differs for {filename}")
            kind = str(evaluation["kind"])
            evaluation_id = str(evaluation["evaluation_id"])
            required_kinds = _required_component_kinds(kind, evaluation_id)
            edit = edits.get(evaluation_id) if kind == "edit" else None
            if kind == "edit" and edit is None:
                raise ValueError(f"unknown edit assignment: {evaluation_id}")
            applicability = response.get("applicability")
            if applicability not in {"execute", "not_applicable"}:
                raise ValueError(f"assignment response is not terminal for {filename}")
            reason_code = response.get("not_applicable_reason_code")
            detail_code = response.get("not_applicable_detail_code")
            component_map_attestation: Json | None = None
            component_map_attestation_sha256: str | None = None
            canonical_edit_issues: list[Json] | None = None
            if applicability == "execute":
                if reason_code is not None or detail_code is not None:
                    raise ValueError("executable assignment cannot declare an N/A reason")
            else:
                if response.get("region_evidence_ref") is not None:
                    raise ValueError(
                        "not-applicable assignment cannot declare region evidence"
                    )
                if evaluation["kind"] != "edit":
                    raise ValueError("render assignments cannot be marked not_applicable")
                if reason_code not in _REASON_CODES:
                    raise ValueError("not-applicable reason code is unsupported")
                if detail_code != _REASON_DETAIL_CODES[reason_code]:
                    raise ValueError("not-applicable detail code is unsupported")
                assert edit is not None
                if reason_code == "source_component_absent":
                    resolved_ids, missing_kinds = _resolved_component_ids_for_kinds(
                        component_map,
                        required_kinds,
                    )
                    if resolved_ids or set(missing_kinds) != set(required_kinds):
                        raise ValueError(
                            "source_component_absent requires every required component "
                            "kind to be unresolved"
                        )
                    calibration_path, attestation_path, component_map_attestation = (
                        _component_map_absence_provenance(
                            config,
                            repository_root=repository_root,
                            evidence_root=root,
                            calibration_evidence_ref=source_review.get(
                                "component_map_calibration_evidence_ref"
                            ),
                            attestation_ref=source_review.get(
                                "component_map_attestation_ref"
                            ),
                            source_sha256=source_sha256,
                            corpus_run_id=corpus_run_id,
                            reviewer=reviewer,
                            component_map=component_map,
                        )
                    )
                    artifacts.append({
                        "path": relative_artifact_path(
                            root,
                            calibration_path,
                            label="component map calibration",
                        ),
                        "sha256": file_sha256(calibration_path),
                        "role": "component_map_calibration_evidence",
                    })
                    component_map_attestation_sha256 = canonical_object_sha256(
                        component_map_attestation
                    )
                    artifacts.append({
                        "path": relative_artifact_path(
                            root,
                            attestation_path,
                            label="component map attestation",
                        ),
                        "sha256": file_sha256(attestation_path),
                        "role": "component_map_attestation_evidence",
                    })
                else:
                    target_spec, issues = apply_canonical_ring_edit(source_spec, edit)
                    if target_spec is not None or not issues:
                        raise ValueError(
                            "canonical_delta_inapplicable contradicts a deterministic "
                            "valid canonical edit"
                        )
                    canonical_edit_issues = issues
            review_path = _relative_evidence(
                root,
                response.get("review_evidence_ref"),
                label=f"assignment-review evidence {filename}:{evaluation_index}",
            )
            _review_evidence(
                review_path,
                source_filename=filename,
                source_sha256=source_sha256,
                evaluation=evaluation,
                applicability=applicability,
                reason_code=reason_code,
                detail_code=detail_code,
                reviewer=reviewer,
            )
            review_hash = file_sha256(review_path)
            artifacts.append({
                "path": relative_artifact_path(root, review_path, label="review evidence"),
                "sha256": review_hash,
                "role": "assignment_review_evidence",
            })
            binding: Json = {
                "schema_version": "facetta-frozen-source-assignment.v1",
                "review_status": "approved",
                "applicability": applicability,
                "review_evidence_sha256": review_hash,
                "source_spec_evidence_sha256": file_sha256(spec_path),
                "component_map_sha256": component_map_hash(component_map),
                "region_evidence_sha256": review_hash,
            }
            if applicability == "not_applicable":
                binding["not_applicable_reason"] = f"{reason_code}/{detail_code}"
                if component_map_attestation_sha256 is not None:
                    assert component_map_attestation is not None
                    binding["source_sha256"] = source_sha256
                    binding["component_map"] = component_map.model_dump(
                        mode="json"
                    )
                    binding["component_map_attestation"] = deepcopy(
                        component_map_attestation
                    )
                    binding["component_map_attestation_sha256"] = (
                        component_map_attestation_sha256
                    )
                elif canonical_edit_issues is not None:
                    binding["source_sha256"] = source_sha256
                    binding["source_spec"] = source_spec.model_dump(mode="json")
                    binding["canonical_edit_issues"] = deepcopy(
                        canonical_edit_issues
                    )
                not_applicable_count += 1
                source_na += 1
            else:
                if kind == "render":
                    case = cases.get(evaluation_id)
                    if case is None:
                        raise ValueError(f"unknown render assignment: {evaluation_id}")
                    target_spec = build_ring_golden_spec(case)
                    instruction = f"frozen founder corpus render: {evaluation_id}"
                    region = None
                    frozen_facts = ["reviewed source geometry and component inventory"]
                else:
                    if edit is None or not edit.expected_valid:
                        raise ValueError(f"unknown edit assignment: {evaluation_id}")
                    target_spec, issues = apply_canonical_ring_edit(source_spec, edit)
                    if target_spec is None or issues:
                        raise ValueError(
                            f"canonical edit cannot be executed for {filename}:{evaluation_id}"
                        )
                    instruction = edit.instruction
                    region = None if edit.visual_only else edit.region
                    frozen_facts = list(edit.frozen_facts)
                region_path = _relative_evidence(
                    root,
                    response.get("region_evidence_ref"),
                    label=f"assignment-region evidence {filename}:{evaluation_index}",
                )
                _region_evidence(
                    region_path,
                    source_filename=filename,
                    source_sha256=source_sha256,
                    evaluation=evaluation,
                    expected_region=region,
                    component_map=component_map,
                    required_kinds=required_kinds,
                )
                region_hash = file_sha256(region_path)
                artifacts.append({
                    "path": relative_artifact_path(root, region_path, label="region evidence"),
                    "sha256": region_hash,
                    "role": "assignment_region_evidence",
                })
                binding.update({
                    "source_spec": source_spec.model_dump(mode="json"),
                    "target_spec": target_spec.model_dump(mode="json"),
                    "instruction": instruction,
                    "region_description": region,
                    "frozen_facts": frozen_facts,
                    "region_evidence_sha256": region_hash,
                })
                execute_count += 1
                source_execute += 1
            assignments.append({
                "source_filename": filename,
                "kind": evaluation["kind"],
                "evaluation_id": evaluation["evaluation_id"],
                "binding": binding,
            })
        source_summaries.append({
            "source_filename": filename,
            "execute_count": source_execute,
            "not_applicable_count": source_na,
            "resolved_count": source_execute + source_na,
        })

    assignments.sort(
        key=lambda row: (
            str(row["source_filename"]),
            str(row["kind"]),
            str(row["evaluation_id"]),
        )
    )
    unsigned_bundle = {
        "schema_version": SIGNED_ASSIGNMENT_BUNDLE_SCHEMA,
        "workload_sha256": file_sha256(workload_path),
        "corpus_run_id": corpus_run_id,
        "reviewer_key_id": reviewer.key_id,
        "reviewer_profile_sha256": reviewer.reviewer_profile_sha256,
        "reviewed_template_sha256": canonical_object_sha256(template),
        "release_authority_decision": None,
        "assignments": assignments,
        "signature": None,
    }
    merged_artifacts: dict[str, Json] = {}
    for artifact in artifacts:
        current = merged_artifacts.setdefault(
            artifact["path"],
            {"path": artifact["path"], "sha256": artifact["sha256"], "roles": []},
        )
        if current["sha256"] != artifact["sha256"]:
            raise ValueError(f"assignment evidence hash conflicts for {artifact['path']}")
        if artifact["role"] not in current["roles"]:
            current["roles"].append(artifact["role"])
    artifact_rows = sorted(merged_artifacts.values(), key=lambda row: row["path"])
    for artifact in artifact_rows:
        artifact["roles"].sort()
    validation = {
        "schema_version": ASSIGNMENT_VALIDATION_SCHEMA,
        "status": "pass",
        "provider_calls": 0,
        "workload_sha256": file_sha256(workload_path),
        "corpus_run_id": corpus_run_id,
        "reviewer_key_id": reviewer.key_id,
        "reviewer_profile_sha256": reviewer.reviewer_profile_sha256,
        "reviewed_template_sha256": canonical_object_sha256(template),
        "reviewed_at_utc": reviewed_at_utc,
        "source_count": len(source_summaries),
        "assignment_count": len(assignments),
        "execute_count": execute_count,
        "not_applicable_count": not_applicable_count,
        "unresolved_count": 0,
        "source_summaries": source_summaries,
        "evidence_artifacts": artifact_rows,
        "unsigned_bundle_sha256": canonical_object_sha256(unsigned_bundle),
        "corpus_gate_ready": False,
    }
    return AssignmentCompilation(unsigned_bundle=unsigned_bundle, validation=validation)


def finalize_signed_assignment_bundle(
    compilation: AssignmentCompilation,
    config: Json,
    *,
    reviewer: EnrolledAssignmentReviewer,
    private_key_path: Path,
    decision_time: datetime,
    repository_root: Path,
    evidence_root: Path,
) -> tuple[Json, Json, Json]:
    """Require active authority, sign, self-verify, and return a pin proposal."""

    unsigned_bundle = deepcopy(compilation.unsigned_bundle)
    validation_snapshot = deepcopy(compilation.validation)
    _verify_compilation_evidence(validation_snapshot, evidence_root)
    _verify_compilation_integrity(
        unsigned_bundle,
        validation_snapshot,
        compilation.integrity_sha256,
    )
    authority = verify_release_authority_bundle(
        config,
        repository_root,
        decision_time,
    )
    roles = {
        row.get("role")
        for row in authority.get("authorities", [])
        if isinstance(row, dict)
    }
    if authority.get("status") != "pass" or "assignment_reviewer" not in roles:
        raise ValueError("active assignment reviewer release authority is unavailable")
    private_key = _private_key(
        private_key_path,
        repository_root=repository_root,
        evidence_root=evidence_root,
    )
    signer_bytes = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    reviewer_bytes = reviewer.public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
    if signer_bytes != reviewer_bytes:
        raise ValueError("assignment reviewer private key differs from enrollment")
    bundle = unsigned_bundle
    if config.get("release_authority_bundle") is not None:
        bundle["release_authority_decision"] = (
            build_release_authority_decision_binding(
                config,
                authority,
                reviewed_at=str(validation_snapshot["reviewed_at_utc"]),
            )
        )
    bundle["signature"] = {
        "algorithm": "Ed25519",
        "key_id": reviewer.key_id,
        "value": base64.b64encode(
            private_key.sign(canonical_assignment_bundle_payload(bundle))
        ).decode("ascii"),
    }
    verify_signed_assignment_bundle(bundle, config, repository_root=repository_root)
    validation = validation_snapshot
    validation["release_authority_decision"] = deepcopy(
        bundle["release_authority_decision"]
    )
    validation["signed_bundle_sha256"] = canonical_object_sha256(bundle)
    validation["signature_status"] = "verified"
    pin = {
        "schema_version": "facetta-frozen-assignment-pin-proposal.v1",
        "workload_sha256": bundle["workload_sha256"],
        "corpus_run_id": bundle["corpus_run_id"],
        "reviewed_template_sha256": bundle["reviewed_template_sha256"],
        "release_authority_decision": deepcopy(
            bundle["release_authority_decision"]
        ),
        "bundle_canonical_sha256": canonical_object_sha256(bundle),
        "reviewer_key_id": reviewer.key_id,
        "installation_status": "review_required",
    }
    return bundle, validation, pin


__all__ = [
    "ASSIGNMENT_AUTHORING_TEMPLATE_SCHEMA",
    "ASSIGNMENT_REGION_EVIDENCE_SCHEMA",
    "ASSIGNMENT_REVIEW_EVIDENCE_SCHEMA",
    "ASSIGNMENT_VALIDATION_SCHEMA",
    "AssignmentCompilation",
    "COMPONENT_MAP_ATTESTATION_SCHEMA",
    "COMPONENT_MAP_ATTESTATION_SIGNATURE_DOMAIN",
    "COMPONENT_MAPPER_CONFIG_KEY",
    "EnrolledComponentMapper",
    "SOURCE_SPEC_EVIDENCE_SCHEMA",
    "build_assignment_authoring_template",
    "canonical_component_map_attestation_payload",
    "finalize_signed_assignment_bundle",
    "load_enrolled_component_mapper",
    "validate_completed_assignment_template",
]

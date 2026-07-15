"""Provider-free validation and replay for a frozen image corpus gate.

The compiler deliberately separates source integrity from image quality.  It
can prove that a versioned corpus and configuration are unchanged without any
provider credentials.  Quality is only evaluated when a complete captured
replay is supplied; missing evidence is ``not_run`` and the release gate fails
closed.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections import defaultdict
from math import isfinite
from pathlib import Path
from statistics import mean
from typing import Any

from PIL import Image
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from facetta.blind_jewelry_review import (
    GIA_VISUAL_FIDELITY_ROLE,
    validate_blind_review_packet,
    validate_signed_review_ledger,
)
from facetta.image_agent.drift import outside_mask_drift
from facetta.frozen_capture_workload import (
    ATTEMPT_ROUTING_FIELDS,
    CAPTURE_SCHEMA,
    build_provider_call_plan,
    expected_attempt_routing,
    not_applicable_assignment_rows,
    validate_capture_envelope,
    validate_workload_definition,
)
from facetta.frozen_evidence_paths import (
    confined_path,
    evidence_root as resolve_evidence_root,
    relative_artifact_path,
    validate_artifact_index,
)
from facetta.frozen_persistence_attestation import (
    verify_persistence_attestation,
)
from facetta.ring_evals import evaluate_release_gates


Json = dict[str, Any]

_PRODUCTION_FROZEN_CONFIG_ID = "founder-ring-90-85-90-v1"
_PRODUCTION_FROZEN_CORPUS_ID = "founder-reference-144-v1"
_PRODUCTION_AUTHORING_PINS = (
    "blind_review_ledger_authoring",
    "blind_review_ledger_authoring_cli",
    "assignment_bundle_contract",
    "assignment_bundle_authoring",
    "assignment_bundle_authoring_cli",
)


def _requires_production_authoring_pins(config: Json) -> bool:
    return (
        config.get("schema_version") == "facetta-frozen-gate-config.v1"
        and config.get("config_id") == _PRODUCTION_FROZEN_CONFIG_ID
        and config.get("corpus_id") == _PRODUCTION_FROZEN_CORPUS_ID
    )


_RELEASE_AUTHORITY_KEY_FIELDS = (
    ("canonical_api_runner", "canonical_api_runner_public_key"),
    ("assignment_reviewer", "assignment_reviewer_public_key"),
    ("gia_reviewer", "reviewer_public_key"),
    ("founder", "founder_public_key"),
    ("jewelry_designer", "designer_reviewer_public_key"),
    ("staging_reviewer", "staging_reviewer_public_key"),
)


def release_authority_key_separation(config: Json) -> Json:
    """Audit cryptographic separation across every enrolled release role.

    A signature proves control of a key, not independence between people.  The
    frozen release claims nevertheless require different signing authorities
    for execution, canonical persistence, frozen-assignment review, GIA review,
    founder approval, jewelry-designer acceptance, and staging review. Reusing
    either a key id or the exact public-key bytes across roles therefore fails
    closed.

    Missing roles are deliberately reported but are not errors here: each gate
    already requires the authorities it consumes.  This helper owns only the
    cross-role uniqueness invariant and is shared by all release verifiers.
    """

    identities: list[Json] = []
    trust = config.get("executor_trust")
    if isinstance(trust, dict) and trust.get("status") == "enrolled":
        key_id = trust.get("key_id")
        public_key = trust.get("public_key")
        public_key_sha256 = (
            public_key.rsplit("@sha256:", 1)[1]
            if isinstance(public_key, str) and "@sha256:" in public_key
            else None
        )
        if (
            isinstance(key_id, str)
            and key_id.strip()
            and isinstance(public_key_sha256, str)
            and len(public_key_sha256) == 64
        ):
            identities.append({
                "role": "executor",
                "key_id": key_id,
                "public_key_sha256": public_key_sha256,
            })

    for role, field in _RELEASE_AUTHORITY_KEY_FIELDS:
        configured = config.get(field)
        if not isinstance(configured, dict):
            continue
        key_id = configured.get("key_id")
        public_key_sha256 = configured.get("sha256")
        if (
            isinstance(key_id, str)
            and key_id.strip()
            and isinstance(public_key_sha256, str)
            and len(public_key_sha256) == 64
        ):
            identities.append({
                "role": role,
                "key_id": key_id,
                "public_key_sha256": public_key_sha256,
            })

    errors: list[str] = []
    for field, label in (
        ("key_id", "key_id"),
        ("public_key_sha256", "public-key bytes"),
    ):
        roles_by_identity: dict[str, list[str]] = defaultdict(list)
        for identity in identities:
            roles_by_identity[str(identity[field])].append(str(identity["role"]))
        for roles in roles_by_identity.values():
            if len(roles) > 1:
                errors.append(
                    "release authority roles must use distinct "
                    f"{label}: {', '.join(sorted(roles))}"
                )

    configured_roles = {str(row["role"]) for row in identities}
    all_roles = {"executor"} | {
        role for role, _ in _RELEASE_AUTHORITY_KEY_FIELDS
    }
    return {
        "status": "pass" if not errors else "fail",
        "configured_roles": sorted(configured_roles),
        "missing_roles": sorted(all_roles - configured_roles),
        "identities": sorted(identities, key=lambda row: str(row["role"])),
        "errors": errors,
    }


def _valid_score(value: object) -> bool:
    return (
        type(value) in {int, float}
        and isfinite(float(value))
        and 0 <= float(value) <= 100
    )


def _mask_has_selected_and_protected_pixels(path: Path) -> bool:
    """A drift replay needs both an edit region and an outside control region."""

    with Image.open(path) as image:
        low, high = image.convert("L").getextrema()
    return low < 128 <= high


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_evidence_payload(evidence: Json) -> bytes:
    """Return the exact bytes covered by the reviewer signature."""

    unsigned = {key: value for key, value in evidence.items() if key != "signature"}
    return json.dumps(
        unsigned,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _load_object(path: Path) -> Json:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _duplicate_values(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def _validate_manifest(manifest: Json) -> tuple[list[Json], list[str]]:
    errors: list[str] = []
    if manifest.get("schema_version") != "facetta-frozen-corpus.v1":
        errors.append("unsupported manifest schema_version")
    sources = manifest.get("sources")
    if not isinstance(sources, list):
        return [], errors + ["manifest sources must be a list"]
    rows = [row for row in sources if isinstance(row, dict)]
    if len(rows) != len(sources):
        errors.append("every manifest source must be an object")
    expected_count = manifest.get("expected_source_count")
    if type(expected_count) is not int or expected_count < 1:
        errors.append("expected_source_count must be a positive integer")
    elif len(rows) != expected_count:
        errors.append(
            f"manifest source count {len(rows)} does not equal {expected_count}"
        )
    names = [str(row.get("filename") or "") for row in rows]
    hashes = [str(row.get("sha256") or "") for row in rows]
    if any(not name or Path(name).name != name for name in names):
        errors.append("source filenames must be non-empty basenames")
    duplicate_names = _duplicate_values(names)
    if duplicate_names:
        errors.append("duplicate source filenames: " + ", ".join(duplicate_names))
    duplicate_hashes = _duplicate_values(hashes)
    if duplicate_hashes:
        errors.append("duplicate source hashes: " + ", ".join(duplicate_hashes))
    if any(len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest)
           for digest in hashes):
        errors.append("every source sha256 must be 64 lowercase hex characters")

    evaluation = manifest.get("evaluation_slice")
    if not isinstance(evaluation, dict):
        errors.append("evaluation_slice must be an object")
        return rows, errors
    ring_names = evaluation.get("ring_source_filenames")
    if not isinstance(ring_names, list) or not ring_names:
        errors.append("ring_source_filenames must be a non-empty list")
    else:
        unknown = sorted(set(map(str, ring_names)) - set(names))
        if unknown:
            errors.append("ring slice references unknown sources: " + ", ".join(unknown))
        duplicate_ring = _duplicate_values(list(map(str, ring_names)))
        if duplicate_ring:
            errors.append("duplicate ring slice sources: " + ", ".join(duplicate_ring))
    for field in ("render_case_ids", "operation_ids"):
        values = evaluation.get(field)
        if not isinstance(values, list) or not values:
            errors.append(f"{field} must be a non-empty list")
        elif _duplicate_values(list(map(str, values))):
            errors.append(f"{field} contains duplicates")
    operation_classes = evaluation.get("operation_classes")
    if not isinstance(operation_classes, dict):
        errors.append("operation_classes must be an object")
    else:
        quick = operation_classes.get("quick_appearance")
        structural = operation_classes.get("structural")
        if not isinstance(quick, list) or not isinstance(structural, list):
            errors.append(
                "operation_classes must declare quick_appearance and structural lists"
            )
        else:
            classified = list(map(str, quick)) + list(map(str, structural))
            if _duplicate_values(classified):
                errors.append("operation classes contain duplicate assignments")
            operation_ids = set(map(str, evaluation.get("operation_ids", [])))
            if set(classified) != operation_ids:
                errors.append("operation classes must partition operation_ids exactly")
    return rows, errors


def _validate_config(
    config: Json,
    manifest: Json,
    manifest_hash: str,
    repository_root: Path,
) -> list[str]:
    errors: list[str] = []
    if config.get("schema_version") != "facetta-frozen-gate-config.v1":
        errors.append("unsupported config schema_version")
    if config.get("corpus_id") != manifest.get("corpus_id"):
        errors.append("config corpus_id does not match manifest")
    if config.get("manifest_sha256") != manifest_hash:
        errors.append("config manifest_sha256 does not match manifest bytes")
    thresholds = config.get("thresholds")
    required = {
        "render_hard_gate_pass_rate": 0.90,
        "mean_render_conformance": 85,
        "mean_edit_fidelity": 90,
        "max_attempts": 3,
        "max_outside_mask_drift": 0.18,
        "quick_appearance_designer_acceptance_rate": 0.90,
    }
    if not isinstance(thresholds, dict):
        errors.append("config thresholds must be an object")
    else:
        for key, expected in required.items():
            if thresholds.get(key) != expected:
                errors.append(
                    f"config threshold {key} must remain pinned to {expected}"
                )
    frozen = config.get("frozen_components")
    required_frozen_components = (
        "ring_contract", "prompt_bundle", "evaluator_bundle", "routing",
        "routing_contract",
        "live_runner", "replay_verifier", "replay_runner",
        "release_verifier", "packet_builder", "packet_runner",
        "blind_review_contract", "release_authority_enrollment",
        "release_authority_bundle",
    )
    if _requires_production_authoring_pins(config):
        required_frozen_components += _PRODUCTION_AUTHORING_PINS
    if not isinstance(frozen, dict) or any(
        not isinstance(frozen.get(key), str) or not frozen.get(key)
        for key in required_frozen_components
    ):
        errors.append("config frozen_components are incomplete")
    elif isinstance(frozen, dict):
        errors.extend(validate_frozen_component_pins(config, repository_root))
    reviewer_key = config.get("reviewer_public_key")
    if reviewer_key is not None:
        if not isinstance(reviewer_key, dict):
            errors.append("reviewer_public_key must be null or an object")
        else:
            key_id = reviewer_key.get("key_id")
            relative = reviewer_key.get("path")
            expected_hash = reviewer_key.get("sha256")
            reviewer_profile_sha256 = reviewer_key.get(
                "reviewer_profile_sha256",
            )
            root = repository_root.resolve()
            candidate = (
                (root / str(relative)).resolve()
                if isinstance(relative, str) else None
            )
            if not isinstance(key_id, str) or not key_id.strip():
                errors.append("reviewer public key_id is missing")
            if not (
                isinstance(reviewer_profile_sha256, str)
                and len(reviewer_profile_sha256) == 64
                and all(
                    character in "0123456789abcdef"
                    for character in reviewer_profile_sha256
                )
            ):
                errors.append("GIA reviewer profile sha256 is invalid")
            if (
                candidate is None or not isinstance(relative, str)
                or Path(relative).is_absolute()
                or not candidate.is_relative_to(root)
                or not candidate.is_file()
            ):
                errors.append("reviewer public-key file is unavailable")
            elif file_sha256(candidate) != expected_hash:
                errors.append("reviewer public-key file hash differs from config")
    runner_key = config.get("canonical_api_runner_public_key")
    if runner_key is not None:
        if not isinstance(runner_key, dict):
            errors.append("canonical_api_runner_public_key must be null or an object")
        else:
            key_id = runner_key.get("key_id")
            relative = runner_key.get("path")
            expected_hash = runner_key.get("sha256")
            root = repository_root.resolve()
            candidate = (
                (root / str(relative)).resolve()
                if isinstance(relative, str) else None
            )
            if not isinstance(key_id, str) or not key_id.strip():
                errors.append("canonical API runner public key_id is missing")
            if (
                candidate is None or not isinstance(relative, str)
                or Path(relative).is_absolute()
                or not candidate.is_relative_to(root)
                or not candidate.is_file()
            ):
                errors.append("canonical API runner public-key file is unavailable")
            elif file_sha256(candidate) != expected_hash:
                errors.append(
                    "canonical API runner public-key file hash differs from config"
                )
    mapper_key = config.get("component_mapper_public_key")
    if mapper_key is not None:
        if not isinstance(mapper_key, dict) or set(mapper_key) != {
            "key_id",
            "path",
            "sha256",
        }:
            errors.append(
                "component_mapper_public_key must be null or a complete object"
            )
        else:
            key_id = mapper_key.get("key_id")
            relative = mapper_key.get("path")
            expected_hash = mapper_key.get("sha256")
            root = repository_root.resolve()
            candidate = (
                (root / str(relative)).resolve()
                if isinstance(relative, str)
                else None
            )
            if not isinstance(key_id, str) or not key_id.strip():
                errors.append("component mapper public key_id is missing")
            if (
                candidate is None
                or not isinstance(relative, str)
                or Path(relative).is_absolute()
                or not candidate.is_relative_to(root)
                or not candidate.is_file()
            ):
                errors.append("component mapper public-key file is unavailable")
            elif file_sha256(candidate) != expected_hash:
                errors.append(
                    "component mapper public-key file hash differs from config"
                )
            else:
                content = candidate.read_bytes()
                try:
                    mapper_public_key = (
                        Ed25519PublicKey.from_public_bytes(content)
                        if len(content) == 32
                        else load_pem_public_key(content)
                    )
                except (TypeError, ValueError):
                    mapper_public_key = None
                if not isinstance(mapper_public_key, Ed25519PublicKey):
                    errors.append("component mapper public key is not Ed25519")
            assignment_key = config.get("assignment_reviewer_public_key")
            if isinstance(assignment_key, dict) and (
                assignment_key.get("key_id") == key_id
                or assignment_key.get("sha256") == expected_hash
            ):
                errors.append(
                    "component mapper enrollment must be distinct from "
                    "assignment reviewer"
                )
    errors.extend(release_authority_key_separation(config)["errors"])
    return errors


def validate_frozen_component_pins(
    config: Json,
    repository_root: Path,
) -> list[str]:
    """Re-verify the executable implementation pins in one gate config.

    The corpus compiler and founder decision verifier both call this helper so
    a result cannot be approved after any pinned implementation has drifted.
    The routing label is backed by a separately hash-pinned executable contract.
    """

    frozen = config.get("frozen_components")
    if not isinstance(frozen, dict):
        return ["config frozen_components are incomplete"]
    errors: list[str] = []
    root = repository_root.resolve()
    for key in (
        "ring_contract", "prompt_bundle", "evaluator_bundle", "routing_contract",
        "live_runner",
        "replay_verifier", "replay_runner", "release_verifier",
        "packet_builder", "packet_runner",
    ):
        value = frozen.get(key)
        if not isinstance(value, str) or "@sha256:" not in value:
            errors.append(f"config frozen component {key} is not hash-pinned")
            continue
        relative, expected_hash = value.rsplit("@sha256:", 1)
        candidate = (root / relative).resolve()
        if (
            not relative or Path(relative).is_absolute()
            or not candidate.is_relative_to(root)
            or not candidate.is_file()
        ):
            errors.append(f"config frozen component {key} path is unavailable")
            continue
        if file_sha256(candidate) != expected_hash:
            errors.append(f"config frozen component {key} implementation drifted")
    # The capture spine was added after the replay schema.  Existing synthetic
    # fixtures remain valid, while any production config that declares these
    # components gets the same path and byte-level pin verification.
    production_authoring_pins = (
        frozenset(_PRODUCTION_AUTHORING_PINS)
        if _requires_production_authoring_pins(config)
        else frozenset()
    )
    for key in (
        "capture_workload", "capture_planner", "capture_planner_cli",
        "capture_producer", "capture_producer_cli", "persistence_verifier",
        "evidence_path_contract", "release_verifier_cli",
        "blind_review_ledger_authoring", "blind_review_ledger_authoring_cli",
        "assignment_bundle_contract", "assignment_bundle_authoring",
        "assignment_bundle_authoring_cli",
        "blind_review_contract", "release_authority_enrollment",
        "release_authority_bundle",
    ):
        if key not in frozen:
            if key in production_authoring_pins:
                errors.append(f"config frozen component {key} is not hash-pinned")
            continue
        value = frozen.get(key)
        if not isinstance(value, str) or "@sha256:" not in value:
            errors.append(f"config frozen component {key} is not hash-pinned")
            continue
        relative, expected_hash = value.rsplit("@sha256:", 1)
        candidate = (root / relative).resolve()
        if (
            not relative or Path(relative).is_absolute()
            or not candidate.is_relative_to(root)
            or not candidate.is_file()
        ):
            errors.append(f"config frozen component {key} path is unavailable")
            continue
        if file_sha256(candidate) != expected_hash:
            errors.append(f"config frozen component {key} implementation drifted")
    return errors


def _verify_sources(
    rows: list[Json], source_dir: Path, evidence_root: Path,
) -> Json:
    failures: list[Json] = []
    verified = 0
    for row in rows:
        filename = str(row.get("filename") or "")
        try:
            path = confined_path(
                evidence_root,
                source_dir / filename,
                label=f"frozen source {filename}",
                kind="file",
            )
            if not path.is_relative_to(source_dir):
                raise ValueError(f"frozen source {filename} escapes source directory")
        except ValueError as exc:
            failures.append({"filename": filename, "code": "missing"})
            failures[-1]["detail"] = str(exc)
            continue
        digest = file_sha256(path)
        if digest != row.get("sha256"):
            failures.append({
                "filename": filename,
                "code": "sha256_mismatch",
                "expected": row.get("sha256"),
                "observed": digest,
            })
            continue
        try:
            with Image.open(path) as image:
                image.verify()
        except Exception as exc:
            failures.append({
                "filename": filename,
                "code": "not_decodable",
                "detail": str(exc),
            })
            continue
        verified += 1
    return {
        "status": "pass" if not failures and verified == len(rows) else "fail",
        "expected": len(rows),
        "verified": verified,
        "failures": failures,
    }


def _reviewer_public_key(
    config: Json,
    repository_root: Path,
) -> tuple[Ed25519PublicKey | None, str | None, str | None]:
    configured = config.get("reviewer_public_key")
    if not isinstance(configured, dict):
        return None, None, "reviewer public key is not configured"
    key_id = configured.get("key_id")
    relative = configured.get("path")
    if not isinstance(key_id, str) or not isinstance(relative, str):
        return None, None, "reviewer public-key configuration is incomplete"
    path = (repository_root / relative).resolve()
    if not path.is_file() or file_sha256(path) != configured.get("sha256"):
        return None, key_id, "reviewer public-key file failed its configured hash"
    content = path.read_bytes()
    try:
        if len(content) == 32:
            return Ed25519PublicKey.from_public_bytes(content), key_id, None
        key = load_pem_public_key(content)
        if not isinstance(key, Ed25519PublicKey):
            return None, key_id, "configured reviewer key is not Ed25519"
        return key, key_id, None
    except (TypeError, ValueError) as exc:
        return None, key_id, f"reviewer public key is invalid: {exc}"


def _verify_signature(
    evidence: Json,
    config: Json,
    repository_root: Path,
) -> Json:
    public_key, configured_key_id, key_error = _reviewer_public_key(
        config, repository_root,
    )
    signature = evidence.get("signature")
    if key_error:
        return {"status": "not_verified", "error": key_error}
    if not isinstance(signature, dict):
        return {"status": "not_verified", "error": "replay is unsigned"}
    if signature.get("algorithm") != "Ed25519":
        return {"status": "not_verified", "error": "signature algorithm is not Ed25519"}
    if signature.get("key_id") != configured_key_id:
        return {"status": "not_verified", "error": "signature key_id differs from config"}
    encoded = signature.get("value")
    if not isinstance(encoded, str):
        return {"status": "not_verified", "error": "signature value is missing"}
    try:
        decoded = base64.b64decode(encoded, validate=True)
        assert public_key is not None
        public_key.verify(decoded, canonical_evidence_payload(evidence))
    except (InvalidSignature, ValueError, TypeError):
        return {"status": "not_verified", "error": "replay signature is invalid"}
    return {"status": "verified", "key_id": configured_key_id}


def _verify_declared_artifact(
    row: Json,
    evidence_root: Path,
    artifact_bindings: dict[str, str],
    field: str,
    errors: list[str],
    label: str,
) -> Path | None:
    value = row.get(field)
    try:
        path = confined_path(
            evidence_root,
            str(value or ""),
            label=f"{label} {field}",
            kind="file",
            require_relative=True,
        )
    except ValueError:
        path = None
    expected_hash = row.get(f"{field}_sha256")
    if path is None or not path.is_file():
        errors.append(f"{label} lacks {field} artifact")
        return None
    if not isinstance(expected_hash, str) or file_sha256(path) != expected_hash:
        errors.append(f"{label} {field} artifact hash mismatch")
        return None
    if artifact_bindings.get(str(value)) != expected_hash:
        errors.append(f"{label} {field} is absent from the artifact index")
        return None
    return path


def _artifact_bindings(evidence: Json, evidence_root: Path, errors: list[str]) -> dict[str, str]:
    index = evidence.get("artifact_index")
    errors.extend(validate_artifact_index(index, evidence_root))
    if not isinstance(index, dict) or not isinstance(index.get("artifacts"), list):
        return {}
    return {
        str(row.get("path")): str(row.get("sha256"))
        for row in index["artifacts"]
        if isinstance(row, dict)
    }


def _capture_relative_artifact(
    capture_path: Path,
    evidence_root: Path,
    value: object,
    *,
    label: str,
) -> Path:
    """Resolve one executor-signed capture artifact without widening its root."""

    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError(f"{label} must be capture-relative")
    artifact = confined_path(
        evidence_root,
        capture_path.parent / value,
        label=label,
        kind="file",
    )
    if not artifact.is_relative_to(capture_path.parent.resolve()):
        raise ValueError(f"{label} escapes the signed capture directory")
    return artifact


def _revalidate_signed_capture_projection(
    evidence: Json,
    *,
    manifest_path: Path,
    config_path: Path,
    workload_path: Path,
    repository_root: Path,
    evidence_root: Path,
    source_dir: Path,
    assignment_plan: Json | None,
) -> Json:
    """Reopen executor authority and compare its exact reviewer projection.

    Reviewer evidence is not allowed to assert that capture validation happened.
    The replay compiler independently verifies the enrolled executor signature,
    then deterministically projects those signed attempts and persistence bytes
    into the evidence-root paths used by offline replay.  A reviewer may add
    decisions, but may not substitute any machine or applicability evidence.
    """

    errors: list[str] = []
    provenance = evidence.get("capture_provenance")
    expected_provenance_fields = {
        "schema_version",
        "corpus_run_id",
        "capture_artifact",
        "capture_sha256",
        "executor_key_id",
        "executor_public_key_artifact",
        "executor_public_key_sha256",
        "executor_signature",
        "executor_signature_status",
        "capture_validation",
    }
    if not isinstance(provenance, dict):
        return {
            "status": "fail",
            "errors": ["signed capture provenance is missing"],
            "validation": None,
        }
    if set(provenance) != expected_provenance_fields:
        errors.append("signed capture provenance fields differ")

    try:
        capture_path = confined_path(
            evidence_root,
            str(provenance.get("capture_artifact") or ""),
            label="signed capture artifact",
            kind="file",
            require_relative=True,
        )
        executor_key_path = confined_path(
            evidence_root,
            str(provenance.get("executor_public_key_artifact") or ""),
            label="executor public key artifact",
            kind="file",
            require_relative=True,
        )
    except ValueError as exc:
        return {
            "status": "fail",
            "errors": errors + [str(exc)],
            "validation": None,
        }

    capture_sha256 = file_sha256(capture_path)
    executor_key_sha256 = file_sha256(executor_key_path)
    if provenance.get("capture_sha256") != capture_sha256:
        errors.append("signed capture provenance hash differs")
    if evidence.get("capture_sha256") != capture_sha256:
        errors.append("replay capture hash differs from signed capture")
    if provenance.get("executor_public_key_sha256") != executor_key_sha256:
        errors.append("executor public key provenance hash differs")

    capture_key_id = provenance.get("executor_key_id")
    validation: Json | None = None
    if not isinstance(capture_key_id, str) or not capture_key_id.strip():
        errors.append("signed capture executor key_id is empty")
    else:
        try:
            validation = validate_capture_envelope(
                capture_path,
                manifest_path,
                config_path,
                workload_path,
                capture_public_key_path=executor_key_path,
                capture_key_id=capture_key_id,
                repository_root=repository_root,
            )
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"signed capture validation could not run: {exc}")
        else:
            if validation.get("status") != "pass":
                errors.extend(
                    "signed capture: " + str(error)
                    for error in validation.get("errors", [])
                )
            if validation.get("signature_status") != "verified":
                errors.append("signed capture executor signature is not verified")
            if provenance.get("executor_signature_status") != validation.get(
                "signature_status"
            ):
                errors.append("reviewer executor-signature status differs from revalidation")
            if provenance.get("capture_validation") != validation:
                errors.append("reviewer capture-validation claim differs from revalidation")

    try:
        capture = _load_object(capture_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "status": "fail",
            "errors": errors + [f"signed capture is invalid: {exc}"],
            "validation": validation,
        }

    if capture.get("schema_version") != CAPTURE_SCHEMA:
        errors.append("signed capture schema_version is unsupported")
    if provenance.get("schema_version") != capture.get("schema_version"):
        errors.append("capture provenance schema differs from signed capture")
    if provenance.get("corpus_run_id") != capture.get("corpus_run_id"):
        errors.append("capture provenance corpus_run_id differs from signed capture")
    if provenance.get("executor_signature") != capture.get("signature"):
        errors.append("capture provenance signature differs from signed capture")

    if assignment_plan is None:
        errors.append("signed capture replay requires a frozen assignment plan")
        planned_execution: dict[tuple[str, str, str], Json] = {}
        expected_not_applicable: list[Json] = []
    else:
        planned_execution = {
            (row["kind"], row["evaluation_id"], row["source_filename"]): row
            for row in assignment_plan.get("items", [])
            if (
                isinstance(row, dict)
                and isinstance(row.get("resolved_inputs"), dict)
                and row["resolved_inputs"].get("execution_ready") is True
            )
        }
        expected_not_applicable = not_applicable_assignment_rows(assignment_plan)
        if capture.get("assignment_bundle_sha256") != assignment_plan.get(
            "assignment_bundle", {}
        ).get("bundle_sha256"):
            errors.append("signed capture assignment identity differs from frozen plan")
        for field in ("manifest_sha256", "config_sha256", "workload_sha256"):
            if capture.get(field) != assignment_plan.get(field):
                errors.append(f"signed capture {field} differs from frozen plan")
        if capture.get("corpus_run_id") != assignment_plan.get("corpus_run_id"):
            errors.append("signed capture corpus_run_id differs from frozen plan")

    if capture.get("not_applicable_assignments") != expected_not_applicable:
        errors.append("signed capture applicability rows differ from frozen plan")
    if evidence.get("not_applicable_assignments") != capture.get(
        "not_applicable_assignments"
    ):
        errors.append("reviewed applicability rows differ from signed capture")

    raw_attempts = capture.get("attempts")
    projected_attempts: list[Json] = []
    if not isinstance(raw_attempts, list) or any(
        not isinstance(row, dict) for row in raw_attempts
    ):
        errors.append("signed capture attempts are invalid")
    else:
        for index, raw in enumerate(raw_attempts, 1):
            key = (
                str(raw.get("kind") or ""),
                str(raw.get("evaluation_id") or ""),
                str(raw.get("source_filename") or ""),
            )
            planned = planned_execution.get(key)
            if planned is None:
                errors.append(
                    f"signed capture attempt {index} has no frozen execution assignment"
                )
                continue
            if raw.get("operation_class") != planned.get("operation_class"):
                errors.append(
                    f"signed capture attempt {index} operation_class differs from plan"
                )
            projected = dict(raw)
            projected["operation_class"] = planned.get("operation_class")
            try:
                signed_source = _capture_relative_artifact(
                    capture_path,
                    evidence_root,
                    raw.get("source_image"),
                    label=f"signed capture attempt {index} source image",
                )
                if file_sha256(signed_source) != planned.get("source_sha256"):
                    errors.append(
                        f"signed capture attempt {index} source image hash differs"
                    )
                if raw.get("source_image_sha256") != planned.get("source_sha256"):
                    errors.append(
                        f"signed capture attempt {index} source image claim differs"
                    )
                replay_source = confined_path(
                    evidence_root,
                    source_dir / key[2],
                    label=f"frozen source {key[2]}",
                    kind="file",
                )
                if not replay_source.is_relative_to(source_dir.resolve()):
                    raise ValueError(f"frozen source {key[2]} escapes source directory")
                projected["source_image"] = relative_artifact_path(
                    evidence_root,
                    replay_source,
                    label=f"frozen source {key[2]}",
                )
                projected["source_image_sha256"] = planned.get("source_sha256")
            except ValueError as exc:
                errors.append(str(exc))

            for field in ("candidate_image", "mask_image"):
                value = raw.get(field)
                if value is None:
                    projected[field] = None
                    continue
                try:
                    artifact = _capture_relative_artifact(
                        capture_path,
                        evidence_root,
                        value,
                        label=f"signed capture attempt {index} {field}",
                    )
                except ValueError as exc:
                    errors.append(str(exc))
                    continue
                projected[field] = relative_artifact_path(
                    evidence_root,
                    artifact,
                    label=f"signed capture attempt {index} {field}",
                )
            projected_attempts.append(projected)

    if evidence.get("attempts") != projected_attempts:
        errors.append("reviewed attempts differ from the executor-signed capture")

    persistence_ref = capture.get("persistence_evidence_ref")
    if not isinstance(persistence_ref, dict) or set(persistence_ref) != {
        "relative_path",
        "sha256",
    }:
        errors.append("signed capture persistence reference is invalid")
    else:
        try:
            persistence_path = _capture_relative_artifact(
                capture_path,
                evidence_root,
                persistence_ref.get("relative_path"),
                label="signed capture persistence evidence",
            )
        except ValueError as exc:
            errors.append(str(exc))
        else:
            expected_persistence_binding = {
                "artifact": relative_artifact_path(
                    evidence_root,
                    persistence_path,
                    label="signed capture persistence evidence",
                ),
                "sha256": persistence_ref.get("sha256"),
                "capture_relative_path": persistence_ref.get("relative_path"),
            }
            if file_sha256(persistence_path) != persistence_ref.get("sha256"):
                errors.append("signed capture persistence evidence hash differs")
            if evidence.get("persistence_evidence_binding") != (
                expected_persistence_binding
            ):
                errors.append(
                    "reviewed persistence binding differs from signed capture"
                )
            try:
                signed_persistence = _load_object(persistence_path)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"signed persistence evidence is invalid: {exc}")
            else:
                if evidence.get("persistence_evidence") != signed_persistence:
                    errors.append(
                        "reviewed persistence evidence differs from signed capture"
                    )

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "validation": validation,
    }


def _source_coverage(
    evidence: Json,
    quality_sources: dict[str, str],
    expected_assignments: set[tuple[str, str, str]],
    verified_source_evaluations: dict[str, set[tuple[str, str]]],
) -> Json:
    expected_by_source: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for kind, evaluation_id, filename in expected_assignments:
        expected_by_source[filename].add((kind, evaluation_id))
    rows = evidence.get("source_coverage")
    errors: list[str] = []
    if not isinstance(rows, list):
        rows = []
        errors.append("source_coverage must be a list")
    objects = [row for row in rows if isinstance(row, dict)]
    if len(objects) != len(rows):
        errors.append("every source_coverage row must be an object")
    names = [str(row.get("filename") or "") for row in objects]
    duplicates = _duplicate_values(names)
    if duplicates:
        errors.append("duplicate source coverage: " + ", ".join(duplicates))
    claimed: set[str] = set()
    failed: set[str] = set()
    for row in objects:
        filename = str(row.get("filename") or "")
        if filename not in quality_sources:
            errors.append(
                f"source coverage references non-quality or unknown source: {filename}"
            )
            continue
        if row.get("source_sha256") != quality_sources[filename]:
            errors.append(f"source coverage hash differs for {filename}")
            continue
        evaluation_ids = row.get("evaluation_ids")
        expected_ids = {
            evaluation_id for _, evaluation_id in expected_by_source[filename]
        }
        if not isinstance(evaluation_ids, list) or set(map(str, evaluation_ids)) != expected_ids:
            errors.append(f"source coverage evaluations are invalid for {filename}")
            continue
        actual_ids = verified_source_evaluations.get(filename, set())
        if actual_ids != expected_by_source[filename]:
            errors.append(
                f"source coverage evaluations do not match verified attempts for {filename}"
            )
            continue
        status = row.get("quality_status")
        if status not in {"pass", "fail"}:
            errors.append(f"source coverage quality_status is invalid for {filename}")
            continue
        claimed.add(filename)
        if status == "fail":
            failed.add(filename)
    completed = {
        filename
        for filename, expected in expected_by_source.items()
        if verified_source_evaluations.get(filename, set()) == expected
    }
    missing = sorted(set(quality_sources) - completed)
    if missing:
        errors.append("missing artifact-verified source coverage: " + ", ".join(missing))
    unclaimed = sorted(completed - claimed)
    if unclaimed:
        errors.append("verified source attempts lack matching coverage rows: " + ", ".join(unclaimed))
    return {
        "status": "pass" if not errors and not failed else "fail",
        "expected_source_count": len(quality_sources),
        "completed_source_count": len(completed),
        "failed_source_count": len(failed),
        "missing_source_filenames": missing,
        "errors": errors,
    }


def _quality_workload(
    workload: Json,
) -> tuple[
    dict[str, str],
    dict[tuple[str, str], str],
    set[tuple[str, str, str]],
]:
    """Compile the already-validated quality matrix into exact assignments."""

    set_id = str(workload["ring_quality_evaluation_set_id"])
    evaluation_rows = workload["evaluation_sets"][set_id]
    evaluation_classes = {
        (str(row["kind"]), str(row["evaluation_id"])):
        str(row["operation_class"])
        for row in evaluation_rows
    }
    quality_sources = {
        str(row["filename"]): str(row["sha256"])
        for row in workload["sources"]
        if row.get("quality") is not None
    }
    assignments = {
        (kind, evaluation_id, filename)
        for filename in quality_sources
        for kind, evaluation_id in evaluation_classes
    }
    return quality_sources, evaluation_classes, assignments


def _replay_quality(
    evidence: Json,
    evidence_path: Path,
    manifest_path: Path,
    config_path: Path,
    workload_path: Path,
    source_dir: Path,
    manifest: Json,
    config: Json,
    workload: Json,
    manifest_hash: str,
    config_hash: str,
    workload_hash: str,
    repository_root: Path,
    evidence_root: Path,
    review_packet: Json | None,
    review_ledger: Json | None,
    assignment_plan: Json | None,
) -> Json:
    errors: list[str] = []
    if evidence.get("schema_version") != "facetta-frozen-replay.v1":
        errors.append("unsupported replay schema_version")
    if evidence.get("manifest_sha256") != manifest_hash:
        errors.append("replay manifest hash differs from frozen manifest")
    if evidence.get("config_sha256") != config_hash:
        errors.append("replay config hash differs from frozen config")
    if evidence.get("workload_sha256") != workload_hash:
        errors.append("replay workload hash differs from frozen workload")
    artifact_bindings = _artifact_bindings(evidence, evidence_root, errors)
    capture_revalidation = _revalidate_signed_capture_projection(
        evidence,
        manifest_path=manifest_path,
        config_path=config_path,
        workload_path=workload_path,
        repository_root=repository_root,
        evidence_root=evidence_root,
        source_dir=source_dir,
        assignment_plan=assignment_plan,
    )
    errors.extend(capture_revalidation["errors"])
    capture_provenance = evidence.get("capture_provenance")
    persistence_binding_raw = evidence.get("persistence_evidence_binding")
    indexed_bindings = [
        (
            capture_provenance.get("capture_artifact"),
            capture_provenance.get("capture_sha256"),
            "capture artifact",
        ),
        (
            capture_provenance.get("executor_public_key_artifact"),
            capture_provenance.get("executor_public_key_sha256"),
            "executor public key",
        ),
        (
            persistence_binding_raw.get("artifact"),
            persistence_binding_raw.get("sha256"),
            "persistence evidence",
        ),
    ] if isinstance(capture_provenance, dict) and isinstance(
        persistence_binding_raw, dict
    ) else []
    if not indexed_bindings:
        errors.append("capture and persistence artifact bindings are incomplete")
    for artifact, digest, label in indexed_bindings:
        if not isinstance(artifact, str) or artifact_bindings.get(artifact) != digest:
            errors.append(f"{label} is absent from the artifact index")
    signature = _verify_signature(evidence, config, repository_root)
    if signature["status"] != "verified":
        errors.append(str(signature.get("error") or "replay signature is not verified"))
    attempts = evidence.get("attempts")
    if not isinstance(attempts, list) or not attempts:
        return {
            "status": "not_run",
            "errors": errors + ["no captured attempts were supplied"],
            "signature": signature,
            "source_coverage": {
                "status": "not_run",
                "expected_source_count": workload.get(
                    "expected_quality_source_count", 0,
                ),
                "completed_source_count": 0,
            },
            "release_gates": {"status": "not_evaluated"},
        }
    if any(not isinstance(row, dict) for row in attempts):
        errors.append("every captured attempt must be an object")
        attempts = [row for row in attempts if isinstance(row, dict)]

    quality_sources, evaluation_classes, expected = _quality_workload(workload)
    expected_not_applicable_rows = (
        not_applicable_assignment_rows(assignment_plan)
        if assignment_plan is not None
        else []
    )
    actual_not_applicable_rows = evidence.get("not_applicable_assignments", [])
    if actual_not_applicable_rows != expected_not_applicable_rows:
        errors.append(
            "replay not-applicable assignments differ from the frozen plan"
        )
    expected_not_applicable = {
        (
            str(row["kind"]),
            str(row["evaluation_id"]),
            str(row["source_filename"]),
        )
        for row in expected_not_applicable_rows
    }
    expected_execution = expected - expected_not_applicable
    planned_execution = {
        (row["kind"], row["evaluation_id"], row["source_filename"]): row
        for row in assignment_plan.get("items", [])
        if (
            isinstance(row, dict)
            and isinstance(row.get("resolved_inputs"), dict)
            and row["resolved_inputs"].get("execution_ready") is True
        )
    } if isinstance(assignment_plan, dict) else {}
    grouped: dict[tuple[str, str, str], list[Json]] = defaultdict(list)
    for row in attempts:
        key = (
            str(row.get("kind") or ""),
            str(row.get("evaluation_id") or ""),
            str(row.get("source_filename") or ""),
        )
        grouped[key].append(row)
    observed_execution = set(grouped)
    observed_assignments = observed_execution | expected_not_applicable
    missing = sorted(expected - observed_assignments)
    unexpected = sorted(observed_execution - expected_execution)
    if missing:
        errors.append(
            "missing workload assignments: "
            + ", ".join(":".join(value) for value in missing)
        )
    if unexpected:
        errors.append(
            "unexpected workload assignments: "
            + ", ".join(":".join(value) for value in unexpected)
        )

    thresholds = config["thresholds"]
    max_attempts = int(thresholds["max_attempts"])
    rows: list[Json] = []
    selected_result_set: list[Json] = []
    selected_review_scope: list[Json] = []
    replayed_drift: list[Json] = []
    artifact_paths: dict[int, dict[str, Path]] = {}
    verified_source_evaluations: dict[str, set[tuple[str, str]]] = defaultdict(set)
    manifest_sources = {
        str(row["filename"]): str(row["sha256"])
        for row in manifest["sources"]
    }
    for captured in attempts:
        label = (
            f"{captured.get('kind')}:{captured.get('evaluation_id')}:"
            f"attempt-{captured.get('attempt')}"
        )
        source_filename = str(captured.get("source_filename") or "")
        sequence_key = (
            str(captured.get("kind") or ""),
            str(captured.get("evaluation_id") or ""),
            source_filename,
        )
        planned = planned_execution.get(sequence_key)
        if assignment_plan is not None:
            if planned is None:
                errors.append(f"{label} has no frozen execution assignment")
            else:
                if captured.get("resolved_inputs_sha256") != planned.get(
                    "resolved_inputs_sha256"
                ):
                    errors.append(f"{label} resolved inputs differ from frozen plan")
                attempt_number = captured.get("attempt")
                if type(attempt_number) is not int:
                    errors.append(f"{label} cannot resolve frozen routing identity")
                else:
                    try:
                        expected_routing = expected_attempt_routing(
                            planned,
                            attempt_number,
                            fallback_reason=captured.get("fallback_reason"),
                        )
                    except ValueError as exc:
                        errors.append(f"{label} {exc}")
                    else:
                        actual_routing = {
                            field: captured.get(field)
                            for field in ATTEMPT_ROUTING_FIELDS
                        }
                        if actual_routing != expected_routing:
                            errors.append(
                                f"{label} route/provider/model differs from frozen plan"
                            )
        source_hash = captured.get("source_sha256")
        binding_valid = manifest_sources.get(source_filename) == source_hash
        if not binding_valid:
            errors.append(f"{label} is not bound to a frozen source filename/hash")
        paths: dict[str, Path] = {}
        provider_failed = captured.get("attempt_outcome") == "provider_failed"
        artifact_fields = (
            ("source_image",)
            if provider_failed
            else ("source_image", "candidate_image")
        )
        for field in artifact_fields:
            artifact = _verify_declared_artifact(
                captured, evidence_root, artifact_bindings, field, errors, label,
            )
            if artifact is not None:
                paths[field] = artifact
        if "source_image" in paths and file_sha256(paths["source_image"]) != source_hash:
            errors.append(f"{label} source artifact differs from frozen source hash")
            binding_valid = False
        if captured.get("kind") == "edit" and not provider_failed:
            mask = _verify_declared_artifact(
                captured,
                evidence_root,
                artifact_bindings,
                "mask_image",
                errors,
                label,
            )
            if mask is not None:
                paths["mask_image"] = mask
        artifact_paths[id(captured)] = paths
        required_artifacts = (
            {"source_image"}
            if provider_failed
            else {"source_image", "candidate_image"}
        )
        if captured.get("kind") == "edit" and not provider_failed:
            required_artifacts.add("mask_image")
        evaluation_pair = (
            str(captured.get("kind") or ""),
            str(captured.get("evaluation_id") or ""),
        )
        expected_class = evaluation_classes.get(evaluation_pair)
        if captured.get("operation_class") != expected_class:
            errors.append(f"{label} operation_class differs from frozen workload")
        if (
            binding_valid
            and required_artifacts <= set(paths)
            and (*evaluation_pair, source_filename) in expected_execution
            and captured.get("operation_class") == expected_class
            and not provider_failed
        ):
            verified_source_evaluations[source_filename].add(evaluation_pair)
    for kind, evaluation_id, source_filename in expected_not_applicable:
        verified_source_evaluations[source_filename].add((kind, evaluation_id))
    coverage = _source_coverage(
        evidence,
        quality_sources,
        expected,
        verified_source_evaluations,
    )
    errors.extend(coverage["errors"])
    for sequence_key in sorted(grouped):
        key = sequence_key[:2]
        source_filename = sequence_key[2]
        if sequence_key not in expected_execution:
            continue
        captured = sorted(grouped[sequence_key], key=lambda row: (
            row.get("attempt") if type(row.get("attempt")) is int else 10**9
        ))
        indexes = [row.get("attempt") for row in captured]
        if any(type(index) is not int or index < 1 for index in indexes):
            errors.append(
                f"{key[0]}:{key[1]}:{source_filename} has invalid attempt indexes"
            )
            continue
        if len(set(indexes)) != len(indexes):
            errors.append(
                f"{key[0]}:{key[1]}:{source_filename} has duplicate attempt indexes"
            )
        elif sorted(indexes) != list(range(1, len(captured) + 1)):
            errors.append(
                f"{key[0]}:{key[1]}:{source_filename} attempt indexes are not contiguous"
            )
        attempts_used = max(indexes, default=0)
        if attempts_used > max_attempts:
            errors.append(
                f"{key[0]}:{key[1]}:{source_filename} exceeded "
                f"{max_attempts} attempts"
            )
        accepted = [row for row in captured if row.get("accepted") is True]
        if len(accepted) > 1:
            errors.append(
                f"{key[0]}:{key[1]}:{source_filename} has multiple accepted attempts"
            )
        selected = accepted[-1] if accepted else (captured[-1] if captured else {})
        if accepted and selected.get("attempt") != attempts_used:
            errors.append(
                f"{key[0]}:{key[1]}:{source_filename} continued after acceptance"
            )
        if key[0] == "render":
            score = selected.get("render_conformance_score")
            hard_pass = selected.get("hard_gate_pass")
            if not _valid_score(score) or type(hard_pass) is not bool:
                errors.append(f"render:{key[1]} lacks scored capture evidence")
                continue
            selected_result_set.append({
                "kind": "render",
                "evaluation_id": key[1],
                "source_filename": source_filename,
                "selected_attempt": selected.get("attempt"),
                "candidate_image_sha256": selected.get(
                    "candidate_image_sha256"
                ),
            })
            selected_review_scope.append({
                "kind": "render",
                "operation_class": "render_conformance",
                "source_sha256": selected.get("source_image_sha256"),
                "candidate_sha256": selected.get("candidate_image_sha256"),
                "mask_sha256": None,
                "machine_pass": bool(selected.get("accepted")) and hard_pass,
            })
            rows.append({
                "kind": "render", "case": f"{key[1]}@{source_filename}",
                "evaluation_id": key[1], "source_filename": source_filename,
                "score": score,
                "hard_gate_pass": (
                    bool(selected.get("accepted")) and hard_pass
                ),
                "attempts": attempts_used,
            })
            continue

        score = selected.get("edit_fidelity_score")
        severity = selected.get("severity")
        applied = selected.get("change_applied")
        if (not _valid_score(score)
                or severity not in {"none", "minor", "major"}
                or type(applied) is not bool):
            errors.append(f"edit:{key[1]} lacks scored capture evidence")
            continue
        selected_paths = artifact_paths.get(id(selected), {})
        parent = selected_paths.get("source_image")
        child = selected_paths.get("candidate_image")
        mask = selected_paths.get("mask_image")
        if not all(path is not None for path in (parent, child, mask)):
            errors.append(f"edit:{key[1]} lacks replayable source/candidate/mask files")
            continue
        assert parent is not None and child is not None and mask is not None
        if not _mask_has_selected_and_protected_pixels(mask):
            errors.append(
                f"edit:{key[1]}:{source_filename} mask lacks selected/protected regions"
            )
            continue
        drift = outside_mask_drift(parent.read_bytes(), child.read_bytes(), mask.read_bytes())
        drift_pass = drift <= float(thresholds["max_outside_mask_drift"])
        selected_result_set.append({
            "kind": "edit",
            "evaluation_id": key[1],
            "source_filename": source_filename,
            "selected_attempt": selected.get("attempt"),
            "candidate_image_sha256": selected.get("candidate_image_sha256"),
        })
        selected_review_scope.append({
            "kind": "edit",
            "operation_class": evaluation_classes.get(key),
            "source_sha256": selected.get("source_image_sha256"),
            "candidate_sha256": selected.get("candidate_image_sha256"),
            "mask_sha256": selected.get("mask_image_sha256"),
            "machine_pass": bool(selected.get("accepted")) and applied and drift_pass,
        })
        replayed_drift.append({
            "evaluation_id": key[1], "source_filename": source_filename,
            "attempt": selected.get("attempt"),
            "outside_mask_drift": round(drift, 6), "pass": drift_pass,
        })
        rows.append({
            "kind": "edit", "case": f"{key[1]}@{source_filename}", "score": score,
            "evaluation_id": key[1], "source_filename": source_filename,
            "applied": bool(selected.get("accepted")) and applied and drift_pass,
            "attempts": attempts_used, "severity": severity,
            "expected_valid": True,
        })

    capture_provenance = evidence.get("capture_provenance")
    capture_run_id = (
        capture_provenance.get("corpus_run_id")
        if isinstance(capture_provenance, dict) else None
    )
    if not isinstance(capture_provenance, dict) or not (
        isinstance(capture_run_id, str)
        and bool(capture_run_id.strip())
        and capture_provenance.get("capture_sha256")
        == evidence.get("capture_sha256")
        and capture_provenance.get("executor_signature_status") == "verified"
        and isinstance(capture_provenance.get("capture_validation"), dict)
        and capture_provenance["capture_validation"].get("status") == "pass"
    ):
        errors.append("signed capture provenance lacks a verified corpus_run_id")
        capture_run_id = ""
    persistence_verification = verify_persistence_attestation(
        evidence.get("persistence_evidence"),
        config=config,
        repository_root=repository_root,
        config_sha256=config_hash,
        workload_sha256=workload_hash,
        workload_id=str(workload.get("workload_id") or ""),
        corpus_id=str(workload.get("corpus_id") or ""),
        expected_corpus_run_id=capture_run_id,
        expected_result_set=selected_result_set,
    )
    if persistence_verification["status"] != "pass":
        errors.extend(
            "canonical persistence: " + str(error)
            for error in persistence_verification["errors"]
        )
    persistence_binding = persistence_verification["bindings"]
    release = evaluate_release_gates(rows, persistence_evidence={
        "verified": persistence_verification["status"] == "pass",
        "method": "signed_canonical_api_runner_attestation",
        "result_set": persistence_binding["result_set_sha256"],
        "rejected_active_asset_count": (
            0 if persistence_verification["checks"][
                "zero_rejected_candidates_persisted"
            ] else None
        ),
    })
    blind_review: Json = {
        "status": "not_run",
        "signature_status": "not_verified",
        "errors": ["blind v2 GIA review packet and ledger are required"],
        "decisions": [],
        "accepted_count": 0,
        "accepted_rate": 0.0,
    }
    packet_scope: dict[tuple[str, str, object, object, object], str] = {}
    machine_scope = {
        (
            str(row["kind"]),
            str(row["operation_class"]),
            row["source_sha256"],
            row["candidate_sha256"],
            row["mask_sha256"],
        ): row
        for row in selected_review_scope
    }
    if review_packet is not None and review_ledger is not None:
        packet_validation = validate_blind_review_packet(review_packet)
        protocol = review_packet.get("review_protocol")
        binding = review_packet.get("evidence_binding")
        capture_provenance = evidence.get("capture_provenance")
        blind_errors: list[str] = []
        if packet_validation["status"] != "pass":
            blind_errors.extend(map(str, packet_validation["errors"]))
        if not isinstance(protocol, dict) or (
            protocol.get("reviewer_role") != GIA_VISUAL_FIDELITY_ROLE
        ):
            blind_errors.append("blind review packet is not the GIA visual-fidelity role")
        expected_binding = {
            "manifest_sha256": manifest_hash,
            "config_sha256": config_hash,
            "workload_sha256": workload_hash,
            "capture_sha256": evidence.get("capture_sha256"),
        }
        if binding != expected_binding:
            blind_errors.append("blind review packet evidence binding differs from replay")
        if not isinstance(capture_provenance, dict) or (
            review_packet.get("corpus_run_id")
            != capture_provenance.get("corpus_run_id")
        ):
            blind_errors.append("blind review packet corpus_run_id differs from replay")
        for item in review_packet.get("items", []):
            if not isinstance(item, dict):
                continue
            artifacts = item.get("artifacts")
            if not isinstance(artifacts, dict):
                continue
            source = artifacts.get("source")
            candidate = artifacts.get("candidate")
            mask = artifacts.get("mask")
            scope_key = (
                str(item.get("kind")),
                str(item.get("operation_class")),
                source.get("sha256") if isinstance(source, dict) else None,
                candidate.get("sha256") if isinstance(candidate, dict) else None,
                mask.get("sha256") if isinstance(mask, dict) else None,
            )
            item_id = item.get("item_id")
            if scope_key in packet_scope:
                blind_errors.append("blind review packet contains duplicate artifact scope")
            elif isinstance(item_id, str):
                packet_scope[scope_key] = item_id
        if set(packet_scope) != set(machine_scope):
            blind_errors.append(
                "blind review packet does not exactly cover selected replay artifacts"
            )
        reviewer_key, reviewer_key_id, key_error = _reviewer_public_key(
            config, repository_root,
        )
        reviewer_config = config.get("reviewer_public_key")
        profile_sha256 = (
            reviewer_config.get("reviewer_profile_sha256")
            if isinstance(reviewer_config, dict) else None
        )
        if key_error:
            blind_errors.append(key_error)
        elif not isinstance(profile_sha256, str):
            blind_errors.append("GIA reviewer profile sha256 is not configured")
        else:
            assert reviewer_key is not None and reviewer_key_id is not None
            blind_review = validate_signed_review_ledger(
                review_packet,
                review_ledger,
                reviewer_public_key=reviewer_key,
                reviewer_key_id=reviewer_key_id,
                expected_reviewer_profile_sha256=profile_sha256,
            )
            blind_errors.extend(map(str, blind_review["errors"]))
        if blind_errors:
            blind_review = {**blind_review, "status": "fail", "errors": blind_errors}
    errors.extend("GIA blind review: " + str(error) for error in blind_review["errors"])
    decision_by_item = {
        str(row.get("item_id")): row
        for row in blind_review.get("decisions", [])
        if isinstance(row, dict)
    }
    review_complete = (
        blind_review.get("status") == "pass"
        and blind_review.get("signature_status") == "verified"
        and len(decision_by_item) == len(machine_scope)
    )
    all_reviewer_accepted = (
        review_complete
        and bool(decision_by_item)
        and all(row.get("derived_accepted") is True for row in decision_by_item.values())
    )
    if not all_reviewer_accepted:
        errors.append("one or more GIA reviewer decisions rejected a selected result")

    false_positives = 0
    false_negatives = 0
    for scope_key, machine_row in machine_scope.items():
        item_id = packet_scope.get(scope_key)
        human_accepted = decision_by_item.get(str(item_id), {}).get(
            "derived_accepted",
        )
        false_positives += (
            machine_row["machine_pass"] is True and human_accepted is False
        )
        false_negatives += (
            machine_row["machine_pass"] is False and human_accepted is True
        )

    structural_ids = {
        evaluation_id
        for (kind, evaluation_id), operation_class in evaluation_classes.items()
        if kind == "edit" and operation_class == "structural"
    }
    quick_scope = {
        scope_key: row for scope_key, row in machine_scope.items()
        if row["kind"] == "edit" and row["operation_class"] == "quick_appearance"
    }
    quick_accepted = sum(
        decision_by_item.get(packet_scope.get(scope_key, ""), {}).get(
            "derived_accepted",
        ) is True
        for scope_key in quick_scope
    )
    quick_rate = quick_accepted / len(quick_scope) if quick_scope else 0.0
    quick_pass = bool(quick_scope) and quick_accepted == len(quick_scope)
    structural_rows = [
        row for row in rows
        if row["kind"] == "edit" and row["evaluation_id"] in structural_ids
    ]
    structural_scores = [float(row["score"]) for row in structural_rows]
    structural_mean = mean(structural_scores) if structural_scores else 0.0
    structural_drift = [
        row for row in replayed_drift if row["evaluation_id"] in structural_ids
    ]
    structural_pass = (
        bool(structural_rows)
        and structural_mean >= float(thresholds["mean_edit_fidelity"])
        and len(structural_drift) == len(structural_rows)
        and all(row["pass"] for row in structural_drift)
        and all(row.get("severity") != "major" for row in structural_rows)
    )
    classified_gates = {
        "quick_appearance": {
            "evaluation_count": len(quick_scope),
            "gia_accepted_count": quick_accepted,
            "gia_acceptance_rate": round(quick_rate, 4),
            "independent_designer_acceptance_threshold": thresholds[
                "quick_appearance_designer_acceptance_rate"
            ],
            "pass": quick_pass,
        },
        "structural": {
            "evaluation_count": len(structural_rows),
            "mean_edit_fidelity": round(structural_mean, 2),
            "minimum_mean_edit_fidelity": thresholds["mean_edit_fidelity"],
            "outside_mask_drift_threshold": thresholds["max_outside_mask_drift"],
            "pass": structural_pass,
        },
    }
    all_drift_pass = bool(replayed_drift) and all(row["pass"] for row in replayed_drift)
    base_machine_gates_pass = all((
        release.get("hard_gate_pass") is True,
        release.get("spec_render_conformance_pass") is True,
        release.get("all_localized_edits_within_three_attempts") is True,
        release.get("edit_fidelity_pass") is True,
        release.get("zero_major_unintended_drift") is True,
        release.get("persistence_evidence_verified") is True,
        release.get("zero_rejected_candidates_persisted") is True,
    ))
    passed = (
        not errors
        and observed_assignments == expected
        and signature["status"] == "verified"
        and coverage["status"] == "pass"
        and base_machine_gates_pass
        and all_drift_pass
        and review_complete
        and all_reviewer_accepted
        and quick_pass
        and structural_pass
    )
    return {
        "status": "pass" if passed else "fail",
        "errors": errors,
        "signature": signature,
        "source_coverage": coverage,
        "captured_attempt_count": len(attempts),
        "expected_evaluation_count": len(expected),
        "execution_ready_evaluation_count": len(expected_execution),
        "not_applicable_evaluation_count": len(expected_not_applicable),
        "not_applicable_assignments": expected_not_applicable_rows,
        "completed_evaluation_count": len(observed_assignments & expected),
        "integrity_source_count": len(manifest.get("sources", [])),
        "quality_source_count": len(quality_sources),
        "outside_mask_replay": replayed_drift,
        "all_outside_mask_drift_pass": all_drift_pass,
        "release_gates": release,
        "persistence_attestation": persistence_verification,
        "classified_release_gates": classified_gates,
        "reviewer_review_complete": review_complete,
        "all_reviewer_decisions_accepted": all_reviewer_accepted,
        "blind_review": blind_review,
        "reviewer_confusion_counts": {
            "false_positives": false_positives,
            "false_negatives": false_negatives,
        },
    }


def compile_frozen_corpus_gate(
    manifest_path: Path,
    config_path: Path,
    source_dir: Path,
    evidence_path: Path | None = None,
    repository_root: Path | None = None,
    workload_path: Path | None = None,
    evidence_root: Path | None = None,
    review_packet_path: Path | None = None,
    review_ledger_path: Path | None = None,
) -> Json:
    manifest = _load_object(manifest_path)
    config = _load_object(config_path)
    manifest_hash = file_sha256(manifest_path)
    config_hash = file_sha256(config_path)
    rows, manifest_errors = _validate_manifest(manifest)
    resolved_repository_root = (
        repository_root or Path(__file__).resolve().parents[2]
    )
    resolved_workload_path = workload_path or manifest_path.parent / "workload.json"
    workload: Json = {}
    workload_errors: list[str] = []
    workload_validation: Json
    assignment_plan: Json | None = None
    try:
        workload = _load_object(resolved_workload_path)
        workload_validation = validate_workload_definition(
            manifest_path,
            config_path,
            resolved_workload_path,
            repository_root=resolved_repository_root,
        )
        workload_errors.extend(map(str, workload_validation.get("errors", [])))
        frozen_components = config.get("frozen_components")
        if (
            not workload_errors
            and isinstance(frozen_components, dict)
            and "resolved_assignment_bundle" in frozen_components
        ):
            assignment_plan = build_provider_call_plan(
                manifest_path,
                config_path,
                resolved_workload_path,
                repository_root=resolved_repository_root,
            )
            if assignment_plan.get("unresolved_sequence_count") != 0:
                workload_errors.append(
                    "frozen assignment plan contains unresolved logical rows"
                )
                assignment_plan = None
            elif assignment_plan.get("resolved_sequence_count") != (
                assignment_plan.get("planned_evaluation_sequence_count")
            ):
                workload_errors.append(
                    "frozen assignment plan does not resolve its complete logical scope"
                )
                assignment_plan = None
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        workload_validation = {
            "status": "fail",
            "provider_calls": 0,
            "errors": [f"workload definition is unavailable: {exc}"],
            "corpus_gate_ready": False,
        }
        workload_errors.extend(workload_validation["errors"])
    config_errors = _validate_config(
        config,
        manifest,
        manifest_hash,
        resolved_repository_root,
    )
    authority_key_separation = release_authority_key_separation(config)
    path_errors: list[str] = []
    resolved_evidence_root: Path | None = None
    resolved_source_dir: Path | None = None
    resolved_evidence_path: Path | None = None
    resolved_review_packet_path: Path | None = None
    resolved_review_ledger_path: Path | None = None
    try:
        if evidence_root is None:
            raise ValueError("an explicit evidence root is required")
        resolved_evidence_root = resolve_evidence_root(evidence_root)
        resolved_source_dir = confined_path(
            resolved_evidence_root,
            source_dir,
            label="source directory",
            kind="directory",
        )
        if evidence_path is not None:
            resolved_evidence_path = confined_path(
                resolved_evidence_root,
                evidence_path,
                label="replay evidence",
                kind="file",
            )
        if review_packet_path is not None:
            resolved_review_packet_path = confined_path(
                resolved_evidence_root,
                review_packet_path,
                label="GIA blind review packet",
                kind="file",
            )
        if review_ledger_path is not None:
            resolved_review_ledger_path = confined_path(
                resolved_evidence_root,
                review_ledger_path,
                label="GIA blind review ledger",
                kind="file",
            )
    except ValueError as exc:
        path_errors.append(str(exc))
    source_integrity = (
        _verify_sources(rows, resolved_source_dir, resolved_evidence_root)
        if rows and resolved_source_dir is not None and resolved_evidence_root is not None
        else {
        "status": "fail", "expected": 0, "verified": 0,
        "failures": [{"code": "path_or_manifest_invalid", "details": path_errors}],
    })
    evidence: Json | None = None
    review_packet: Json | None = None
    review_ledger: Json | None = None
    evidence_binding: Json | None = None
    if resolved_evidence_path is not None and resolved_evidence_root is not None:
        evidence = _load_object(resolved_evidence_path)
        if resolved_review_packet_path is not None:
            review_packet = _load_object(resolved_review_packet_path)
        if resolved_review_ledger_path is not None:
            review_ledger = _load_object(resolved_review_ledger_path)
        signature = evidence.get("signature")
        capture_provenance = evidence.get("capture_provenance")
        evidence_binding = {
            "path": resolved_evidence_path.relative_to(
                resolved_evidence_root
            ).as_posix(),
            "sha256": file_sha256(resolved_evidence_path),
            "schema_version": evidence.get("schema_version"),
            "workload_sha256": evidence.get("workload_sha256"),
            "capture_sha256": evidence.get("capture_sha256"),
            "corpus_run_id": (
                capture_provenance.get("corpus_run_id")
                if isinstance(capture_provenance, dict) else None
            ),
            "reviewer_key_id": (
                signature.get("key_id") if isinstance(signature, dict) else None
            ),
        }
    if evidence_path is None:
        quality: Json = {
            "status": "not_run",
            "errors": ["no captured replay evidence was supplied"],
            "signature": {"status": "not_run"},
            "source_coverage": {
                "status": "not_run",
                "expected_source_count": workload_validation.get(
                    "quality_source_count", 0,
                ),
                "completed_source_count": 0,
            },
            "release_gates": {"status": "not_evaluated"},
        }
    elif path_errors:
        quality = {
            "status": "not_run",
            "errors": path_errors,
            "signature": {"status": "not_run"},
            "source_coverage": {
                "status": "not_run",
                "expected_source_count": workload_validation.get(
                    "quality_source_count", 0,
                ),
                "completed_source_count": 0,
            },
            "release_gates": {"status": "not_evaluated"},
        }
    elif workload_errors:
        quality = {
            "status": "not_run",
            "errors": ["quality replay requires a valid frozen workload"],
            "signature": {"status": "not_run"},
            "source_coverage": {
                "status": "not_run",
                "expected_source_count": 0,
                "completed_source_count": 0,
            },
            "release_gates": {"status": "not_evaluated"},
        }
    else:
        assert evidence is not None
        assert resolved_evidence_path is not None
        assert resolved_evidence_root is not None
        assert resolved_source_dir is not None
        quality = _replay_quality(
            evidence,
            resolved_evidence_path,
            manifest_path,
            config_path,
            resolved_workload_path,
            resolved_source_dir,
            manifest,
            config,
            workload,
            manifest_hash, config_hash, file_sha256(resolved_workload_path),
            resolved_repository_root, resolved_evidence_root,
            review_packet, review_ledger, assignment_plan,
        )
    definition_errors = manifest_errors + config_errors + workload_errors + path_errors
    passed = (
        not definition_errors
        and source_integrity["status"] == "pass"
        and quality["status"] == "pass"
    )
    return {
        "schema_version": "facetta-frozen-corpus-gate-result.v1",
        "run_kind": "provider_free_frozen_corpus_gate",
        "provider_calls": 0,
        "manifest": {
            "path": str(manifest_path), "sha256": manifest_hash,
            "corpus_id": manifest.get("corpus_id"),
        },
        "config": {"path": str(config_path), "sha256": config_hash},
        "workload": {
            "path": str(resolved_workload_path),
            "sha256": (
                file_sha256(resolved_workload_path)
                if resolved_workload_path.is_file()
                else None
            ),
            "status": workload_validation.get("status", "fail"),
            "integrity_source_count": workload_validation.get(
                "integrity_source_count", 0,
            ),
            "quality_source_count": workload_validation.get(
                "quality_source_count", 0,
            ),
            "quality_evaluations_per_source": workload_validation.get(
                "quality_evaluations_per_source", 0,
            ),
        },
        "implementation": {
            "frozen_components": config.get("frozen_components"),
            "authority_key_separation": authority_key_separation,
        },
        "evidence": evidence_binding,
        "blind_review_evidence": {
            "packet_file_sha256": (
                file_sha256(resolved_review_packet_path)
                if resolved_review_packet_path is not None else None
            ),
            "packet_canonical_sha256": (
                quality.get("blind_review", {}).get("packet_sha256")
                if isinstance(quality.get("blind_review"), dict) else None
            ),
            "ledger_file_sha256": (
                file_sha256(resolved_review_ledger_path)
                if resolved_review_ledger_path is not None else None
            ),
        },
        "definition": {
            "status": "pass" if not definition_errors else "fail",
            "errors": definition_errors,
        },
        "source_integrity": source_integrity,
        "quality": quality,
        "status": "pass" if passed else "incomplete_or_failed",
        "corpus_gate_ready": passed,
        "release_boundary": (
            "Source integrity is not image quality. Missing captures, canonical "
            "persistence proof, or GIA-trained review fail closed and must never "
            "be reported as a quality pass."
        ),
    }

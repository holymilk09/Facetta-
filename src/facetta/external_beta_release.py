"""Fail-closed composition of the corpus and staging external-beta gates.

Neither input gate is trusted from a shallow top-level boolean.  The corpus
decision is recomputed from the signed founder approval, while the staging
result must have exact check coverage and a separately enrolled reviewer
signature over the retained result and exit-code bytes.
"""

from __future__ import annotations

import base64
import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from facetta.blind_jewelry_review import (
    INDEPENDENT_DESIGNER_ROLE,
    validate_signed_review_ledger,
)
from facetta.frozen_corpus_gate import (
    file_sha256,
    release_authority_key_separation,
)
from facetta.frozen_evidence_paths import (
    confined_path,
    evidence_root as resolve_evidence_root,
)
from facetta.frozen_corpus_release import verify_frozen_corpus_release
from facetta.release_authority_bundle import (
    REQUIRED_ROLES,
    verify_release_authority_bundle,
)


Json = dict[str, Any]
CorpusVerifier = Callable[..., Json]
AuthorityVerifier = Callable[[dict[str, Any], Path, datetime], Json]

CORPUS_DECISION_SCHEMA = "facetta-frozen-corpus-release-decision.v2"
STAGING_RESULT_SCHEMA = "facetta-staging-isolation.v3"
STAGING_RUN_KIND = "read_only_two_principal_staging_probe"
STAGING_APPROVAL_SCHEMA = "facetta-staging-isolation-approval.v1"
EXTERNAL_BETA_DECISION_SCHEMA = "facetta-external-beta-release-decision.v1"


def required_staging_checks() -> dict[str, object]:
    """Return the exact production-isolation observations required to pass."""

    checks: dict[str, object] = {
        "live_health_is_facetta": True,
        "live_deployment_revision_matches": True,
        "live_persistence_is_postgresql": True,
    }
    for label in ("A", "B"):
        checks.update({
            f"user_{label}_reads_own_project": 200,
            f"user_{label}_project_owner_is_token_subject": True,
            f"user_{label}_project_requires_auth": 401,
            f"user_{label}_cannot_read_other_project": 403,
            f"user_{label}_reads_own_history": 200,
            f"user_{label}_cannot_read_other_history": 403,
            f"user_{label}_reads_own_asset": 200,
            f"user_{label}_own_asset_is_image": True,
            f"user_{label}_cannot_read_other_asset": 403,
            f"user_{label}_asset_requires_auth": 401,
            f"user_{label}_lists_own_families": 200,
            f"user_{label}_family_results_are_tenant_scoped": True,
            f"user_{label}_cannot_spoof_family_owner": 403,
            f"user_{label}_reads_own_family": 200,
            f"user_{label}_cannot_enumerate_other_family": 404,
        })
    checks["studio_families_require_auth"] = 401
    for name in (
        "designs", "library", "library_collections", "users", "stones",
        "share_e2e-hidden", "asset_metadata", "asset_history",
        "asset_component_map", "openapi.json", "docs",
    ):
        checks[f"production_hides_{name}"] = 404
    return checks


def canonical_staging_approval_payload(approval: Json) -> bytes:
    """Canonical bytes signed by the enrolled staging reviewer."""

    unsigned = {key: value for key, value in approval.items() if key != "signature"}
    return json.dumps(
        unsigned, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")


def _load_object(path: Path) -> Json:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _sha256_value(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _timezone_value(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _zero_exit_code(path: Path, label: str, errors: list[str]) -> str:
    digest = file_sha256(path)
    try:
        value = path.read_text().strip()
    except (OSError, UnicodeDecodeError):
        errors.append(f"{label} exit-code artifact is unreadable")
        return digest
    if value != "0":
        errors.append(f"{label} command did not retain exit code 0")
    return digest


def _pinned_file(
    config: Json,
    key: str,
    repository_root: Path,
    errors: list[str],
) -> str | None:
    frozen = config.get("frozen_components")
    value = frozen.get(key) if isinstance(frozen, dict) else None
    if not isinstance(value, str) or "@sha256:" not in value:
        errors.append(f"config frozen component {key} is not hash-pinned")
        return None
    relative, expected_hash = value.rsplit("@sha256:", 1)
    root = repository_root.resolve()
    candidate = (root / relative).resolve()
    if (
        not relative
        or Path(relative).is_absolute()
        or not candidate.is_relative_to(root)
        or not candidate.is_file()
    ):
        errors.append(f"config frozen component {key} path is unavailable")
        return expected_hash
    if not _sha256_value(expected_hash) or file_sha256(candidate) != expected_hash:
        errors.append(f"config frozen component {key} implementation drifted")
    return expected_hash


def _expected_quick_appearance_keys(
    config: Json,
    repository_root: Path,
    errors: list[str],
) -> set[tuple[str, str]]:
    """Derive the exact designer-review scope from the pinned workload."""

    frozen = config.get("frozen_components")
    value = frozen.get("capture_workload") if isinstance(frozen, dict) else None
    if not isinstance(value, str) or "@sha256:" not in value:
        errors.append("config capture_workload is not hash-pinned")
        return set()
    relative, expected_hash = value.rsplit("@sha256:", 1)
    root = repository_root.resolve()
    path = (root / relative).resolve()
    if (
        not relative
        or Path(relative).is_absolute()
        or not path.is_relative_to(root)
        or not path.is_file()
        or not _sha256_value(expected_hash)
        or file_sha256(path) != expected_hash
    ):
        errors.append("config capture_workload implementation drifted")
        return set()
    try:
        workload = _load_object(path)
    except (OSError, ValueError, json.JSONDecodeError):
        errors.append("pinned capture_workload is invalid")
        return set()
    evaluation_set_id = workload.get("ring_quality_evaluation_set_id")
    sets = workload.get("evaluation_sets")
    evaluations = (
        sets.get(evaluation_set_id)
        if isinstance(sets, dict) and isinstance(evaluation_set_id, str)
        else None
    )
    sources = workload.get("sources")
    if not isinstance(evaluations, list) or not isinstance(sources, list):
        errors.append("pinned capture_workload lacks designer-review scope")
        return set()
    quick_ids = {
        row.get("evaluation_id")
        for row in evaluations
        if isinstance(row, dict)
        and row.get("kind") == "edit"
        and row.get("operation_class") == "quick_appearance"
        and isinstance(row.get("evaluation_id"), str)
    }
    quality = {"slice": "ring", "evaluation_set_id": evaluation_set_id}
    filenames = {
        row.get("filename")
        for row in sources
        if isinstance(row, dict)
        and row.get("quality") == quality
        and isinstance(row.get("filename"), str)
    }
    keys = {(filename, evaluation_id) for filename in filenames for evaluation_id in quick_ids}
    if not keys:
        errors.append("pinned capture_workload has no quick-appearance designer scope")
    return keys


def _selected_quick_appearance_scope(
    evidence_path: Path | None,
    evidence_root: Path | None,
    expected_keys: set[tuple[str, str]],
    errors: list[str],
) -> list[tuple[str, str, str]]:
    """Derive the exact signed-replay artifact scope for designer review."""

    if evidence_path is None or evidence_root is None:
        errors.append("raw replay and evidence root are required for designer scope")
        return []
    try:
        root = resolve_evidence_root(evidence_root)
        replay_path = confined_path(
            root, evidence_path, label="replay evidence", kind="file",
        )
        replay = _load_object(replay_path)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        errors.append(f"designer scope replay is unavailable: {exc}")
        return []

    attempts = replay.get("attempts")
    if not isinstance(attempts, list) or not all(
        isinstance(row, dict) for row in attempts
    ):
        errors.append("designer scope replay attempts are invalid")
        return []
    selected_by_key: dict[tuple[str, str], list[tuple[str, str, str]]] = {}
    for row in attempts:
        if not (
            row.get("kind") == "edit"
            and row.get("operation_class") == "quick_appearance"
            and row.get("accepted") is True
        ):
            continue
        source_filename = row.get("source_filename")
        evaluation_id = row.get("evaluation_id")
        key = (source_filename, evaluation_id)
        if not all(isinstance(value, str) and value for value in key):
            errors.append("selected quick-appearance replay row has an invalid key")
            continue
        hashes = (
            row.get("source_image_sha256"),
            row.get("candidate_image_sha256"),
            row.get("mask_image_sha256"),
        )
        if not all(_sha256_value(value) for value in hashes):
            errors.append(
                "selected quick-appearance replay row has invalid artifact hashes"
            )
            continue
        typed_key = (str(source_filename), str(evaluation_id))
        selected_by_key.setdefault(typed_key, []).append(
            (str(hashes[0]), str(hashes[1]), str(hashes[2]))
        )
    if set(selected_by_key) != expected_keys:
        errors.append(
            "signed replay selected scope does not exactly cover quick appearance"
        )
    if any(len(rows) != 1 for rows in selected_by_key.values()):
        errors.append(
            "signed replay must select exactly one quick-appearance candidate per item"
        )
    return sorted(
        rows[0]
        for key, rows in selected_by_key.items()
        if key in expected_keys and len(rows) == 1
    )


def _designer_packet_scope(
    packet: Json,
    errors: list[str],
) -> tuple[list[tuple[str, str, str]], set[str]]:
    """Return only the source/candidate/mask hashes visible to the designer."""

    protocol = packet.get("review_protocol")
    if not isinstance(protocol, dict) or (
        protocol.get("reviewer_role") != INDEPENDENT_DESIGNER_ROLE
    ):
        errors.append("blind review packet is not for an independent designer")
    items = packet.get("items")
    if not isinstance(items, list) or not all(isinstance(row, dict) for row in items):
        errors.append("blind review packet items are invalid")
        return [], set()
    scope: list[tuple[str, str, str]] = []
    item_ids: set[str] = set()
    for row in items:
        if not (
            row.get("kind") == "edit"
            and row.get("operation_class") == "quick_appearance"
        ):
            continue
        item_id = row.get("item_id")
        if isinstance(item_id, str):
            item_ids.add(item_id)
        artifacts = row.get("artifacts")
        source = artifacts.get("source") if isinstance(artifacts, dict) else None
        candidate = (
            artifacts.get("candidate") if isinstance(artifacts, dict) else None
        )
        mask = artifacts.get("mask") if isinstance(artifacts, dict) else None
        hashes = (
            source.get("sha256") if isinstance(source, dict) else None,
            candidate.get("sha256") if isinstance(candidate, dict) else None,
            mask.get("sha256") if isinstance(mask, dict) else None,
        )
        if all(_sha256_value(value) for value in hashes):
            scope.append((str(hashes[0]), str(hashes[1]), str(hashes[2])))
        else:
            errors.append("blind review packet item has invalid artifact hashes")
    if not scope:
        errors.append("independent designer packet has no quick-appearance items")
    return sorted(scope), item_ids


def _staging_public_key(
    config: Json,
    repository_root: Path,
) -> tuple[Ed25519PublicKey | None, str | None, str | None]:
    configured = config.get("staging_reviewer_public_key")
    if not isinstance(configured, dict):
        return None, None, "staging reviewer public key is not configured"
    key_id = configured.get("key_id")
    relative = configured.get("path")
    expected_hash = configured.get("sha256")
    if (
        not isinstance(key_id, str)
        or not key_id.strip()
        or not isinstance(relative, str)
        or not _sha256_value(expected_hash)
    ):
        return None, key_id if isinstance(key_id, str) else None, (
            "staging reviewer public-key configuration is incomplete"
        )
    root = repository_root.resolve()
    path = (root / relative).resolve()
    if (
        Path(relative).is_absolute()
        or not path.is_relative_to(root)
        or not path.is_file()
        or file_sha256(path) != expected_hash
    ):
        return None, key_id, "staging reviewer public-key file failed its configured hash"
    try:
        content = path.read_bytes()
        if len(content) == 32:
            return Ed25519PublicKey.from_public_bytes(content), key_id, None
        key = load_pem_public_key(content)
        if not isinstance(key, Ed25519PublicKey):
            return None, key_id, "configured staging reviewer key is not Ed25519"
        return key, key_id, None
    except (TypeError, ValueError) as exc:
        return None, key_id, f"staging reviewer public key is invalid: {exc}"


def _designer_public_key(
    config: Json,
    repository_root: Path,
) -> tuple[
    Ed25519PublicKey | None,
    str | None,
    str | None,
    str | None,
]:
    configured = config.get("designer_reviewer_public_key")
    if not isinstance(configured, dict):
        return None, None, None, "designer reviewer public key is not configured"
    key_id = configured.get("key_id")
    relative = configured.get("path")
    expected_hash = configured.get("sha256")
    profile_hash = configured.get("reviewer_profile_sha256")
    if (
        not isinstance(key_id, str)
        or not key_id.strip()
        or not isinstance(relative, str)
        or not _sha256_value(expected_hash)
    ):
        return None, key_id if isinstance(key_id, str) else None, None, (
            "designer reviewer public-key configuration is incomplete"
        )
    if not _sha256_value(profile_hash):
        return None, key_id, None, (
            "designer reviewer profile is not hash-enrolled"
        )
    root = repository_root.resolve()
    path = (root / relative).resolve()
    if (
        Path(relative).is_absolute()
        or not path.is_relative_to(root)
        or not path.is_file()
        or file_sha256(path) != expected_hash
    ):
        return None, key_id, str(profile_hash), (
            "designer reviewer public-key file failed its configured hash"
        )
    try:
        content = path.read_bytes()
        if len(content) == 32:
            return (
                Ed25519PublicKey.from_public_bytes(content),
                key_id,
                str(profile_hash),
                None,
            )
        key = load_pem_public_key(content)
        if not isinstance(key, Ed25519PublicKey):
            return None, key_id, str(profile_hash), (
                "configured designer reviewer key is not Ed25519"
            )
        return key, key_id, str(profile_hash), None
    except (TypeError, ValueError) as exc:
        return None, key_id, str(profile_hash), (
            f"designer reviewer public key is invalid: {exc}"
        )


def _validate_staging_result(staging: Json) -> list[str]:
    errors: list[str] = []
    if staging.get("schema_version") != STAGING_RESULT_SCHEMA:
        errors.append("unsupported staging-isolation result schema_version")
    if staging.get("run_kind") != STAGING_RUN_KIND:
        errors.append("unsupported staging-isolation result run_kind")
    if staging.get("passed") is not True:
        errors.append("staging-isolation result is not passing")
    if staging.get("secrets_logged") is not False:
        errors.append("staging-isolation result does not prove secrets stayed hidden")
    if staging.get("provider_calls") != 0:
        errors.append("staging-isolation result provider_calls must be zero")
    if staging.get("mutations") != 0:
        errors.append("staging-isolation result mutations must be zero")

    target = staging.get("target")
    if not isinstance(target, dict) or not (
        _sha256_value(target.get("origin_sha256"))
        and _sha256_value(target.get("fixture_set_sha256"))
        and isinstance(target.get("deployment_revision"), str)
        and re.fullmatch(r"[A-Za-z0-9._-]{7,128}", target["deployment_revision"])
        and _timezone_value(target.get("probed_at"))
        and target.get("transport") == "live_https"
    ):
        errors.append("staging-isolation target binding is incomplete or invalid")

    rows = staging.get("checks")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        return errors + ["staging-isolation checks are invalid"]
    names = [row.get("name") for row in rows]
    if not all(isinstance(name, str) for name in names):
        errors.append("staging-isolation checks contain invalid names")
    string_names = [name for name in names if isinstance(name, str)]
    if len(set(string_names)) != len(string_names):
        errors.append("staging-isolation checks contain duplicate names")
    expected = required_staging_checks()
    if set(string_names) != set(expected):
        errors.append("staging-isolation checks do not exactly cover the release contract")
    for row in rows:
        name = row.get("name")
        if not isinstance(name, str):
            continue
        if name not in expected:
            continue
        if not (
            row.get("expected") == expected[name]
            and row.get("observed") == expected[name]
            and row.get("passed") is True
        ):
            errors.append(f"staging-isolation check is not a clean pass: {name}")
    return errors


def verify_external_beta_release(
    corpus_decision_path: Path,
    corpus_results_path: Path,
    corpus_approval_path: Path,
    corpus_exit_code_path: Path,
    config_path: Path,
    designer_packet_path: Path,
    designer_ledger_path: Path,
    staging_results_path: Path,
    staging_approval_path: Path,
    staging_exit_code_path: Path,
    *,
    repository_root: Path | None = None,
    corpus_manifest_path: Path | None = None,
    corpus_source_dir: Path | None = None,
    corpus_evidence_path: Path | None = None,
    corpus_evidence_root: Path | None = None,
    corpus_workload_path: Path | None = None,
    gia_review_packet_path: Path | None = None,
    gia_review_ledger_path: Path | None = None,
    corpus_verifier: CorpusVerifier = verify_frozen_corpus_release,
    authority_verifier: AuthorityVerifier = verify_release_authority_bundle,
) -> Json:
    """Re-verify and compose both signed external-beta authorities."""

    root = repository_root or Path(__file__).resolve().parents[2]
    corpus_decision = _load_object(corpus_decision_path)
    corpus_results = _load_object(corpus_results_path)
    config = _load_object(config_path)
    designer_packet = _load_object(designer_packet_path)
    designer_ledger = _load_object(designer_ledger_path)
    staging = _load_object(staging_results_path)
    staging_approval = _load_object(staging_approval_path)
    errors: list[str] = []
    authority_key_separation = release_authority_key_separation(config)
    errors.extend(authority_key_separation["errors"])
    decision_time = datetime.now(UTC)
    authority_bundle = authority_verifier(config, root, decision_time)
    authority_rows = authority_bundle.get("authorities")
    authority_roles = {
        row.get("role")
        for row in authority_rows
        if isinstance(row, dict) and isinstance(row.get("role"), str)
    } if isinstance(authority_rows, list) else set()
    if not (
        authority_bundle.get("status") == "pass"
        and authority_bundle.get("errors") == []
        and authority_roles == set(REQUIRED_ROLES)
        and isinstance(authority_rows, list)
        and len(authority_rows) == len(REQUIRED_ROLES)
    ):
        errors.append("complete six-role release authority bundle is not verified")
        errors.extend(
            f"release authority bundle: {error}"
            for error in authority_bundle.get("errors", [])
        )

    corpus_exit_hash = _zero_exit_code(
        corpus_exit_code_path, "frozen-corpus finalizer", errors,
    )
    staging_exit_hash = _zero_exit_code(
        staging_exit_code_path, "staging-isolation probe", errors,
    )
    recomputed_corpus = corpus_verifier(
        corpus_results_path,
        config_path,
        corpus_approval_path,
        repository_root=root,
        manifest_path=corpus_manifest_path,
        source_dir=corpus_source_dir,
        evidence_path=corpus_evidence_path,
        evidence_root=corpus_evidence_root,
        workload_path=corpus_workload_path,
        review_packet_path=gia_review_packet_path,
        review_ledger_path=gia_review_ledger_path,
    )
    if corpus_decision != recomputed_corpus:
        errors.append("retained corpus final-decision differs from fresh verification")
    founder_signature = corpus_decision.get("founder_signature")
    if not (
        corpus_decision.get("schema_version") == CORPUS_DECISION_SCHEMA
        and corpus_decision.get("status") == "pass"
        and corpus_decision.get("corpus_gate_ready") is True
        and corpus_decision.get("errors") == []
        and corpus_decision.get("provider_calls") == 0
        and isinstance(founder_signature, dict)
        and founder_signature.get("status") == "verified"
    ):
        errors.append("frozen-corpus final-decision is not a clean signed pass")
    bindings = corpus_decision.get("gate_bindings")
    if not isinstance(bindings, dict) or bindings.get("config_sha256") != file_sha256(config_path):
        errors.append("frozen-corpus final-decision does not bind the exact release config")

    corpus_results_hash = file_sha256(corpus_results_path)
    expected_designer_keys = _expected_quick_appearance_keys(config, root, errors)
    selected_scope = _selected_quick_appearance_scope(
        corpus_evidence_path,
        corpus_evidence_root,
        expected_designer_keys,
        errors,
    )
    packet_scope, quick_packet_item_ids = _designer_packet_scope(
        designer_packet, errors,
    )
    if Counter(packet_scope) != Counter(selected_scope):
        errors.append(
            "blind review packet artifact hashes do not exactly match the "
            "signed replay selections"
        )

    expected_packet_binding = {
        "manifest_sha256": (
            bindings.get("manifest_sha256") if isinstance(bindings, dict) else None
        ),
        "config_sha256": (
            bindings.get("config_sha256") if isinstance(bindings, dict) else None
        ),
        "workload_sha256": (
            bindings.get("workload_sha256") if isinstance(bindings, dict) else None
        ),
        "capture_sha256": (
            bindings.get("capture_sha256") if isinstance(bindings, dict) else None
        ),
    }
    if designer_packet.get("evidence_binding") != expected_packet_binding:
        errors.append(
            "blind review packet does not bind the exact frozen-corpus evidence"
        )
    expected_corpus_run_id = (
        bindings.get("corpus_run_id") if isinstance(bindings, dict) else None
    )
    if designer_packet.get("corpus_run_id") != expected_corpus_run_id:
        errors.append("blind review packet corpus_run_id differs from corpus decision")

    thresholds = config.get("thresholds")
    configured_threshold = (
        thresholds.get("quick_appearance_designer_acceptance_rate")
        if isinstance(thresholds, dict) else None
    )
    if (
        isinstance(configured_threshold, bool)
        or not isinstance(configured_threshold, (int, float))
        or not 0.90 <= float(configured_threshold) <= 1.0
    ):
        errors.append(
            "independent designer acceptance threshold must be configured at "
            "90 percent or higher"
        )
        designer_threshold = 1.0
    else:
        designer_threshold = float(configured_threshold)

    quality = corpus_results.get("quality")
    release_gates = quality.get("release_gates") if isinstance(quality, dict) else None
    within_three_attempts = (
        isinstance(release_gates, dict)
        and release_gates.get("all_localized_edits_within_three_attempts") is True
    )
    if not within_three_attempts:
        errors.append("quick-appearance selections did not complete within three attempts")

    (
        designer_key,
        designer_key_id,
        designer_profile_hash,
        designer_key_error,
    ) = _designer_public_key(config, root)
    if designer_key_error:
        errors.append(designer_key_error)
        designer_validation: Json = {
            "status": "fail",
            "errors": [designer_key_error],
            "signature_status": "not_verified",
            "decisions": [],
            "accepted_count": 0,
            "accepted_rate": 0.0,
        }
    else:
        assert designer_key is not None
        assert designer_key_id is not None
        assert designer_profile_hash is not None
        designer_validation = validate_signed_review_ledger(
            designer_packet,
            designer_ledger,
            reviewer_public_key=designer_key,
            reviewer_key_id=designer_key_id,
            expected_reviewer_profile_sha256=designer_profile_hash,
        )
        errors.extend(
            f"independent designer review: {error}"
            for error in designer_validation.get("errors", [])
        )
    designer_signature_status = designer_validation.get(
        "signature_status", "not_verified",
    )
    validation_decisions = designer_validation.get("decisions")
    quick_decisions = [
        row
        for row in validation_decisions
        if isinstance(row, dict)
        and row.get("item_id") in quick_packet_item_ids
    ] if isinstance(validation_decisions, list) else []
    quick_decision_ids = {
        row.get("item_id")
        for row in quick_decisions
        if isinstance(row.get("item_id"), str)
    }
    designer_evaluation_count = len(selected_scope)
    designer_accepted_count = sum(
        row.get("derived_accepted") is True for row in quick_decisions
    )
    designer_rate = (
        designer_accepted_count / designer_evaluation_count
        if designer_evaluation_count
        else 0.0
    )
    if not (
        designer_validation.get("status") == "pass"
        and designer_signature_status == "verified"
        and len(packet_scope) == designer_evaluation_count
        and len(quick_packet_item_ids) == designer_evaluation_count
        and len(quick_decisions) == designer_evaluation_count
        and quick_decision_ids == quick_packet_item_ids
        and float(designer_rate) >= designer_threshold
    ):
        errors.append(
            "independent designer criterion acceptance does not meet the "
            "frozen threshold"
        )

    verifier_pin = _pinned_file(
        config, "external_beta_release_verifier", root, errors,
    )
    verifier_cli_pin = _pinned_file(
        config, "external_beta_release_cli", root, errors,
    )
    staging_probe_pin = _pinned_file(
        config, "staging_isolation_probe", root, errors,
    )
    errors.extend(_validate_staging_result(staging))

    staging_results_hash = file_sha256(staging_results_path)
    if staging_approval.get("schema_version") != STAGING_APPROVAL_SCHEMA:
        errors.append("unsupported staging-isolation approval schema_version")
    if staging_approval.get("staging_results_sha256") != staging_results_hash:
        errors.append("staging approval does not bind the exact result bytes")
    if staging_approval.get("staging_exit_code_sha256") != staging_exit_hash:
        errors.append("staging approval does not bind the exact exit-code bytes")
    if staging_approval.get("decision") != "approved":
        errors.append("staging reviewer decision is not approved")
    for field in ("reviewer", "approved_at", "release_ticket"):
        value = staging_approval.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"staging approval {field} is missing")
    if not _timezone_value(staging_approval.get("approved_at")):
        errors.append("staging approval approved_at must include a timezone")
    target = staging.get("target") if isinstance(staging.get("target"), dict) else {}
    for field in (
        "origin_sha256",
        "deployment_revision",
        "fixture_set_sha256",
    ):
        if staging_approval.get(field) != target.get(field):
            errors.append(f"staging approval {field} differs from the tested target")

    public_key, key_id, key_error = _staging_public_key(config, root)
    signature = staging_approval.get("signature")
    staging_signature_status = "not_verified"
    if key_error:
        errors.append(key_error)
    elif not isinstance(signature, dict):
        errors.append("staging approval is unsigned")
    elif (
        signature.get("algorithm") != "Ed25519"
        or signature.get("key_id") != key_id
        or not isinstance(signature.get("value"), str)
    ):
        errors.append("staging approval signature metadata is invalid")
    else:
        try:
            assert public_key is not None
            public_key.verify(
                base64.b64decode(signature["value"], validate=True),
                canonical_staging_approval_payload(staging_approval),
            )
            staging_signature_status = "verified"
        except (InvalidSignature, ValueError, TypeError):
            errors.append("staging approval signature is invalid")

    passed = (
        not errors
        and designer_signature_status == "verified"
        and staging_signature_status == "verified"
    )
    return {
        "schema_version": EXTERNAL_BETA_DECISION_SCHEMA,
        "status": "pass" if passed else "incomplete_or_failed",
        "external_beta_ready": passed,
        "provider_calls": 0,
        "mutations": 0,
        "independent_designer_review": {
            "status": designer_validation.get("status"),
            "evaluation_count": designer_evaluation_count,
            "accepted_count": designer_accepted_count,
            "acceptance_rate": designer_rate,
            "threshold": designer_threshold,
            "within_three_attempts": within_three_attempts,
        },
        "gate_bindings": {
            "corpus_final_decision_sha256": file_sha256(corpus_decision_path),
            "corpus_results_sha256": corpus_results_hash,
            "corpus_approval_sha256": file_sha256(corpus_approval_path),
            "corpus_exit_code_sha256": corpus_exit_hash,
            "designer_review_packet_sha256": file_sha256(
                designer_packet_path
            ),
            "designer_review_ledger_sha256": file_sha256(
                designer_ledger_path
            ),
            "staging_results_sha256": staging_results_hash,
            "staging_approval_sha256": file_sha256(staging_approval_path),
            "staging_exit_code_sha256": staging_exit_hash,
            "config_sha256": file_sha256(config_path),
            "origin_sha256": target.get("origin_sha256"),
            "deployment_revision": target.get("deployment_revision"),
            "fixture_set_sha256": target.get("fixture_set_sha256"),
            "external_beta_release_verifier_sha256": verifier_pin,
            "external_beta_release_cli_sha256": verifier_cli_pin,
            "staging_isolation_probe_sha256": staging_probe_pin,
        },
        "signatures": {
            "founder": corpus_decision.get("founder_signature"),
            "designer": {
                "status": designer_signature_status,
                "key_id": designer_key_id,
            },
            "staging_reviewer": {
                "status": staging_signature_status,
                "key_id": key_id,
            },
        },
        "authority_key_separation": authority_key_separation,
        "release_authority_bundle": authority_bundle,
        "errors": errors,
    }

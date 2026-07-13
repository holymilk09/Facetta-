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
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from facetta.frozen_corpus_gate import file_sha256
from facetta.frozen_corpus_release import verify_frozen_corpus_release


Json = dict[str, Any]
CorpusVerifier = Callable[..., Json]

CORPUS_DECISION_SCHEMA = "facetta-frozen-corpus-release-decision.v2"
STAGING_RESULT_SCHEMA = "facetta-staging-isolation.v2"
STAGING_RUN_KIND = "read_only_two_principal_staging_probe"
STAGING_APPROVAL_SCHEMA = "facetta-staging-isolation-approval.v1"
DESIGNER_APPROVAL_SCHEMA = "facetta-designer-acceptance-approval.v1"
EXTERNAL_BETA_DECISION_SCHEMA = "facetta-external-beta-release-decision.v1"


def required_staging_checks() -> dict[str, object]:
    """Return the exact production-isolation observations required to pass."""

    checks: dict[str, object] = {}
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


def canonical_designer_approval_payload(approval: Json) -> bytes:
    """Canonical bytes signed by the enrolled jewelry designer."""

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


def _validate_designer_decisions(
    decisions: Json,
    *,
    corpus_results_hash: str,
    corpus_run_id: object,
    expected_keys: set[tuple[str, str]],
) -> tuple[int, list[str]]:
    errors: list[str] = []
    if decisions.get("schema_version") != "facetta-designer-acceptance-decisions.v1":
        errors.append("unsupported designer acceptance decisions schema_version")
    if decisions.get("corpus_results_sha256") != corpus_results_hash:
        errors.append("designer decisions do not bind the exact corpus result bytes")
    if decisions.get("corpus_run_id") != corpus_run_id:
        errors.append("designer decisions corpus_run_id differs from the corpus decision")
    if decisions.get("completed") is not True:
        errors.append("designer decisions are not complete")
    if decisions.get("qualification") != "jewelry_designer":
        errors.append("designer decisions qualification must be jewelry_designer")
    if not isinstance(decisions.get("designer"), str) or not decisions["designer"].strip():
        errors.append("designer decisions designer is missing")
    if not _timezone_value(decisions.get("reviewed_at")):
        errors.append("designer decisions reviewed_at must include a timezone")
    rows = decisions.get("decisions")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        return 0, errors + ["designer acceptance decisions are invalid"]
    observed: dict[tuple[str, str], bool] = {}
    for row in rows:
        key = (row.get("source_filename"), row.get("evaluation_id"))
        if not all(isinstance(value, str) and value for value in key):
            errors.append("designer acceptance decision has an invalid key")
            continue
        typed_key = (str(key[0]), str(key[1]))
        if typed_key in observed:
            errors.append("designer acceptance decisions contain duplicate keys")
        if type(row.get("accepted")) is not bool:
            errors.append("designer acceptance decision lacks boolean accepted")
            continue
        observed[typed_key] = row["accepted"]
    if set(observed) != expected_keys:
        errors.append("designer acceptance decisions do not exactly cover quick appearance")
    return sum(observed.get(key) is True for key in expected_keys), errors


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
) -> tuple[Ed25519PublicKey | None, str | None, str | None]:
    configured = config.get("designer_reviewer_public_key")
    if not isinstance(configured, dict):
        return None, None, "designer reviewer public key is not configured"
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
            "designer reviewer public-key configuration is incomplete"
        )
    root = repository_root.resolve()
    path = (root / relative).resolve()
    if (
        Path(relative).is_absolute()
        or not path.is_relative_to(root)
        or not path.is_file()
        or file_sha256(path) != expected_hash
    ):
        return None, key_id, "designer reviewer public-key file failed its configured hash"
    try:
        content = path.read_bytes()
        if len(content) == 32:
            return Ed25519PublicKey.from_public_bytes(content), key_id, None
        key = load_pem_public_key(content)
        if not isinstance(key, Ed25519PublicKey):
            return None, key_id, "configured designer reviewer key is not Ed25519"
        return key, key_id, None
    except (TypeError, ValueError) as exc:
        return None, key_id, f"designer reviewer public key is invalid: {exc}"


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
    designer_decisions_path: Path,
    designer_approval_path: Path,
    staging_results_path: Path,
    staging_approval_path: Path,
    staging_exit_code_path: Path,
    *,
    repository_root: Path | None = None,
    corpus_verifier: CorpusVerifier = verify_frozen_corpus_release,
) -> Json:
    """Re-verify and compose both signed external-beta authorities."""

    root = repository_root or Path(__file__).resolve().parents[2]
    corpus_decision = _load_object(corpus_decision_path)
    corpus_results = _load_object(corpus_results_path)
    config = _load_object(config_path)
    designer_decisions = _load_object(designer_decisions_path)
    designer_approval = _load_object(designer_approval_path)
    staging = _load_object(staging_results_path)
    staging_approval = _load_object(staging_approval_path)
    errors: list[str] = []

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

    quality = corpus_results.get("quality")
    classified = (
        quality.get("classified_release_gates")
        if isinstance(quality, dict) else None
    )
    quick_gate = (
        classified.get("quick_appearance")
        if isinstance(classified, dict) else None
    )
    if not isinstance(quick_gate, dict) or not (
        type(quick_gate.get("evaluation_count")) is int
        and quick_gate["evaluation_count"] > 0
        and type(quick_gate.get("designer_accepted_count")) is int
        and 0 <= quick_gate["designer_accepted_count"] <= quick_gate["evaluation_count"]
        and isinstance(quick_gate.get("designer_acceptance_rate"), (int, float))
        and isinstance(quick_gate.get("threshold"), (int, float))
        and quick_gate["designer_acceptance_rate"] >= quick_gate["threshold"]
        and quick_gate.get("pass") is True
    ):
        errors.append("corpus quick-appearance acceptance evidence is not a clean pass")
        quick_gate = {}

    corpus_results_hash = file_sha256(corpus_results_path)
    expected_designer_keys = _expected_quick_appearance_keys(config, root, errors)
    designer_accepted_count, designer_decision_errors = _validate_designer_decisions(
        designer_decisions,
        corpus_results_hash=corpus_results_hash,
        corpus_run_id=(
            bindings.get("corpus_run_id") if isinstance(bindings, dict) else None
        ),
        expected_keys=expected_designer_keys,
    )
    errors.extend(designer_decision_errors)
    if designer_approval.get("schema_version") != DESIGNER_APPROVAL_SCHEMA:
        errors.append("unsupported designer acceptance approval schema_version")
    if designer_approval.get("corpus_results_sha256") != corpus_results_hash:
        errors.append("designer approval does not bind the exact corpus result bytes")
    if designer_approval.get("corpus_run_id") != (
        bindings.get("corpus_run_id") if isinstance(bindings, dict) else None
    ):
        errors.append("designer approval corpus_run_id differs from the corpus decision")
    designer_decisions_hash = file_sha256(designer_decisions_path)
    if designer_approval.get("designer_decisions_sha256") != designer_decisions_hash:
        errors.append("designer approval does not bind the exact decision ledger bytes")
    if designer_approval.get("decision") != "approved":
        errors.append("designer decision is not approved")
    if designer_approval.get("qualification") != "jewelry_designer":
        errors.append("designer approval qualification must be jewelry_designer")
    if designer_approval.get("designer") != designer_decisions.get("designer"):
        errors.append("designer approval identity differs from the decision ledger")
    for field in ("designer", "approved_at", "release_ticket"):
        value = designer_approval.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"designer approval {field} is missing")
    if not _timezone_value(designer_approval.get("approved_at")):
        errors.append("designer approval approved_at must include a timezone")
    designer_summary = designer_approval.get("quick_appearance")
    designer_evaluation_count = len(expected_designer_keys)
    designer_rate = (
        round(designer_accepted_count / designer_evaluation_count, 4)
        if designer_evaluation_count else 0.0
    )
    release_gates = quality.get("release_gates") if isinstance(quality, dict) else None
    within_three_attempts = (
        isinstance(release_gates, dict)
        and release_gates.get("all_localized_edits_within_three_attempts") is True
    )
    expected_designer_summary = {
        "evaluation_count": designer_evaluation_count,
        "accepted_count": designer_accepted_count,
        "acceptance_rate": designer_rate,
        "threshold": quick_gate.get("threshold"),
        "within_three_attempts": within_three_attempts,
    }
    if designer_summary != expected_designer_summary:
        errors.append("designer approval quick-appearance summary differs from corpus evidence")
    if not (
        designer_evaluation_count == quick_gate.get("evaluation_count")
        and within_three_attempts
        and isinstance(quick_gate.get("threshold"), (int, float))
        and designer_rate >= quick_gate["threshold"]
    ):
        errors.append("independent designer acceptance does not meet the frozen threshold")

    designer_key, designer_key_id, designer_key_error = _designer_public_key(config, root)
    designer_signature = designer_approval.get("signature")
    designer_signature_status = "not_verified"
    if designer_key_error:
        errors.append(designer_key_error)
    elif not isinstance(designer_signature, dict):
        errors.append("designer approval is unsigned")
    elif (
        designer_signature.get("algorithm") != "Ed25519"
        or designer_signature.get("key_id") != designer_key_id
        or not isinstance(designer_signature.get("value"), str)
    ):
        errors.append("designer approval signature metadata is invalid")
    else:
        try:
            assert designer_key is not None
            designer_key.verify(
                base64.b64decode(designer_signature["value"], validate=True),
                canonical_designer_approval_payload(designer_approval),
            )
            designer_signature_status = "verified"
        except (InvalidSignature, ValueError, TypeError):
            errors.append("designer approval signature is invalid")

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
    for field in ("origin_sha256", "deployment_revision"):
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
        "gate_bindings": {
            "corpus_final_decision_sha256": file_sha256(corpus_decision_path),
            "corpus_results_sha256": corpus_results_hash,
            "corpus_approval_sha256": file_sha256(corpus_approval_path),
            "corpus_exit_code_sha256": corpus_exit_hash,
            "designer_approval_sha256": file_sha256(designer_approval_path),
            "designer_decisions_sha256": designer_decisions_hash,
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
        "errors": errors,
    }

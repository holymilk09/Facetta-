"""Provider-free planning and validation for the frozen corpus capture workload.

The 144-file corpus is an integrity boundary.  Only the advisory 58-file ring
slice is a quality workload.  This module makes that distinction executable
without calling an image provider or manufacturing evidence.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import unicodedata
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from facetta.frozen_assignment_contract import (
    CANONICAL_DELTA_INAPPLICABLE_REASON,
    SIGNED_ASSIGNMENT_BUNDLE_SCHEMA,
    SUPPORTED_NOT_APPLICABLE_REASONS,
    verify_signed_assignment_bundle,
)
from facetta.frozen_evaluator_report import validate_and_replay_evaluator_report
from facetta.image_agent.contracts import ImageOperation, ImageRoute
from facetta.image_agent.prompts import PROMPT_VERSIONS
from facetta.ring_evals import (
    CANONICAL_RING_EDITS,
    RING_GOLDEN_CASES,
    apply_canonical_ring_edit,
    build_ring_golden_spec,
)


Json = dict[str, Any]
_PORTABLE_SOURCE_FILENAME = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.(?:jpe?g|png|webp|avif)\Z",
    re.IGNORECASE,
)
_PORTABLE_EVALUATION_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,79}\Z")
_WINDOWS_RESERVED_BASENAME = re.compile(
    r"(?:con|prn|aux|nul|com[1-9]|lpt[1-9])\Z",
    re.IGNORECASE,
)
WORKLOAD_SCHEMA = "facetta-frozen-capture-workload.v1"
PLAN_SCHEMA = "facetta-frozen-provider-call-plan.v3"
CAPTURE_SCHEMA = "facetta-frozen-capture.v3"
RESOLVED_ASSIGNMENT_SCHEMA = "facetta-frozen-resolved-assignment.v1"
ASSIGNMENT_BUNDLE_SCHEMA = SIGNED_ASSIGNMENT_BUNDLE_SCHEMA
EXECUTOR_TRUST_SCHEMA = "facetta-frozen-executor-trust.v1"
ROUTING_CONTRACT_SCHEMA = "facetta-frozen-routing-contract.v1"
FROZEN_ROUTING_LABEL = "grok-primary-openai-fallback.v1"

_ROUTING_CONTRACT_KEYS = {
    "schema_version",
    "routing_label",
    "route_entries",
    "selection_policy",
}
_ROUTE_ENTRY_KEYS = {
    "adapter_key",
    "order",
    "role",
    "route",
    "provider",
    "model",
    "model_revision",
    "model_revision_status",
    "applicable_task_classes",
    "applicable_image_operations",
    "attempt_numbers",
    "fallback_conditions",
    "endpoint",
    "provider_operation",
}
_APPLICABLE_TASK_CLASSES = [
    "quick_appearance",
    "render_conformance",
    "structural",
]
_APPLICABLE_IMAGE_OPERATIONS = [
    ImageOperation.LOCAL_EDIT.value,
    ImageOperation.SPEC_RENDER.value,
    ImageOperation.VISUAL_ONLY_EDIT.value,
]
_FALLBACK_CONDITIONS = [
    "grok_provider_failed",
    "grok_provider_failed_after_qa_failure",
    "grok_qa_failed",
]
_SELECTION_POLICY = {
    "credential_based_substitution_allowed": False,
    "source_image_required": True,
    "stop_after_acceptance": True,
    "undeclared_route_allowed": False,
}
_EXPECTED_ROUTE_ENTRIES = (
    {
        "adapter_key": "grok_direct",
        "order": 1,
        "role": "primary",
        "route": ImageRoute.GROK_EDIT.value,
        "provider": "xai",
        "model": "grok-imagine-image-quality",
        "model_revision": None,
        "model_revision_status": "provider_alias_unversioned",
        "endpoint": "https://api.x.ai/v1/images/edits",
        "provider_operation": "images.edits",
        "applicable_task_classes": _APPLICABLE_TASK_CLASSES,
        "applicable_image_operations": _APPLICABLE_IMAGE_OPERATIONS,
        "attempt_numbers": [1, 2],
        "fallback_conditions": [],
    },
    {
        "adapter_key": "openai_image_provider",
        "order": 2,
        "role": "fallback",
        "route": ImageRoute.OPENAI_EDIT.value,
        "provider": "openai",
        "model": "gpt-image-2",
        "model_revision": None,
        "model_revision_status": "provider_alias_unversioned",
        "endpoint": "https://api.openai.com/v1/images/edits",
        "provider_operation": "images.edits",
        "applicable_task_classes": _APPLICABLE_TASK_CLASSES,
        "applicable_image_operations": _APPLICABLE_IMAGE_OPERATIONS,
        "attempt_numbers": [3],
        "fallback_conditions": _FALLBACK_CONDITIONS,
    },
)
ATTEMPT_ROUTING_FIELDS = (
    "routing_contract_sha256",
    "routing_label",
    "route_role",
    "route",
    "adapter_key",
    "provider",
    "model",
    "model_revision",
    "model_revision_status",
    "endpoint",
    "provider_operation",
    "fallback_reason",
)
_ATTEMPT_ROUTE_IDENTITY_FIELDS = ATTEMPT_ROUTING_FIELDS[:-1]
ATTEMPT_OUTCOME_FIELDS = (
    "attempt_outcome",
    "provider_error_code",
    "qa_outcome",
)
_EVALUATOR_REPORT_PROJECTION_FIELDS = {
    "render": (
        "accepted",
        "attempt_outcome",
        "provider_error_code",
        "qa_outcome",
        "render_conformance_score",
        "hard_gate_pass",
    ),
    "edit": (
        "accepted",
        "attempt_outcome",
        "provider_error_code",
        "qa_outcome",
        "edit_fidelity_score",
        "severity",
        "change_applied",
    ),
}


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_object(path: Path) -> Json:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _hex_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def canonical_object_sha256(value: object) -> str:
    """Hash one JSON-compatible contract without filesystem ambiguity."""

    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def valid_machine_score(value: object) -> bool:
    """Return whether a machine score is a finite numeric value in 0..100."""

    return (
        type(value) in {int, float}
        and math.isfinite(float(value))
        and 0 <= float(value) <= 100
    )


def _duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def _artifact_stem_collisions(
    source_filenames: set[str],
    evaluations: set[tuple[str, str]],
) -> list[str]:
    """Return deterministic provider-output stem collisions for a workload.

    The capture producer deliberately removes the source suffix when it names
    candidate and mask artifacts.  Two distinct sources such as ``ring.jpg``
    and ``ring.png`` would therefore target the same output after paid provider
    work.  Validate the complete candidate/mask namespace while planning is
    still provider-free so execution cannot begin with ambiguous destinations.
    """

    owners: defaultdict[str, list[str]] = defaultdict(list)
    for source_filename in sorted(source_filenames):
        source_stem = unicodedata.normalize(
            "NFC", Path(source_filename).stem,
        ).casefold()
        for kind, evaluation_id in sorted(evaluations):
            candidate_stem = f"{source_stem}--{kind}--{evaluation_id}"
            identity = f"{source_filename}:{kind}:{evaluation_id}"
            owners[candidate_stem].append(f"candidate:{identity}")
            if kind == "edit":
                owners[f"{candidate_stem}--mask"].append(f"mask:{identity}")
    return [
        f"{stem} ({', '.join(sorted(stem_owners))})"
        for stem, stem_owners in sorted(owners.items())
        if len(stem_owners) > 1
    ]


def _portable_source_filename(value: str) -> bool:
    """Keep provider artifacts addressable across supported filesystems."""

    if (
        not value.isascii()
        or unicodedata.normalize("NFC", value) != value
        or _PORTABLE_SOURCE_FILENAME.fullmatch(value) is None
    ):
        return False
    stem = value.rsplit(".", 1)[0]
    device_token = stem.split(".", 1)[0]
    return (
        ".." not in stem
        and not stem.endswith(".")
        and _WINDOWS_RESERVED_BASENAME.fullmatch(device_token) is None
    )


def _pinned_path(config: Json, key: str, root: Path) -> tuple[Path, str]:
    frozen = config.get("frozen_components")
    value = frozen.get(key) if isinstance(frozen, dict) else None
    if not isinstance(value, str) or "@sha256:" not in value:
        raise ValueError(f"config frozen component {key} is not hash-pinned")
    relative, expected_hash = value.rsplit("@sha256:", 1)
    candidate = (root.resolve() / relative).resolve()
    if (
        not relative
        or Path(relative).is_absolute()
        or not candidate.is_relative_to(root.resolve())
        or not candidate.is_file()
    ):
        raise ValueError(f"config frozen component {key} path is unavailable")
    if not _hex_digest(expected_hash) or file_sha256(candidate) != expected_hash:
        raise ValueError(f"config frozen component {key} implementation drifted")
    return candidate, expected_hash


def _load_routing_contract(config: Json, root: Path) -> tuple[Json, str]:
    """Load and strictly validate the only route schedule allowed for capture.

    The frozen corpus is intentionally provider-free until secured execution,
    but its route semantics cannot be.  This contract prevents a live executor
    from treating a human-readable routing label as permission to select a
    credential-dependent provider or model.
    """

    contract_path, contract_sha256 = _pinned_path(
        config,
        "routing_contract",
        root,
    )
    contract = _load_object(contract_path)
    errors: list[str] = []
    if set(contract) != _ROUTING_CONTRACT_KEYS:
        errors.append("routing contract top-level fields differ")
    if contract.get("schema_version") != ROUTING_CONTRACT_SCHEMA:
        errors.append("routing contract schema_version is unsupported")
    components = config.get("frozen_components")
    routing_label = components.get("routing") if isinstance(components, dict) else None
    if routing_label != FROZEN_ROUTING_LABEL:
        errors.append("config frozen routing label is unsupported")
    if contract.get("routing_label") != routing_label:
        errors.append("routing contract label differs from config")
    if contract.get("selection_policy") != _SELECTION_POLICY:
        errors.append("routing contract selection policy differs")
    entries = contract.get("route_entries")
    if not isinstance(entries, list) or len(entries) != len(_EXPECTED_ROUTE_ENTRIES):
        errors.append("routing contract route entries are incomplete")
        entries = []
    for index, expected in enumerate(_EXPECTED_ROUTE_ENTRIES, 1):
        if index > len(entries):
            break
        entry = entries[index - 1]
        if not isinstance(entry, dict):
            errors.append(f"routing contract route entry {index} is not an object")
            continue
        if set(entry) != _ROUTE_ENTRY_KEYS:
            errors.append(f"routing contract route entry {index} fields differ")
            continue
        if entry != expected:
            errors.append(f"routing contract route entry {index} differs")
    thresholds = config.get("thresholds")
    max_attempts = (
        thresholds.get("max_attempts")
        if isinstance(thresholds, dict)
        else None
    )
    assigned_attempts = [
        attempt
        for entry in entries
        if isinstance(entry, dict)
        for attempt in (
            entry.get("attempt_numbers", [])
            if isinstance(entry.get("attempt_numbers"), list)
            else []
        )
        if type(attempt) is int
    ]
    if type(max_attempts) is not int or sorted(assigned_attempts) != list(
        range(1, max_attempts + 1)
    ):
        errors.append("routing contract attempt schedule differs from config")
    if errors:
        raise ValueError("invalid frozen routing contract: " + "; ".join(errors))
    return contract, contract_sha256


def _routing_attempt_assignments(
    contract: Json,
    contract_sha256: str,
    *,
    operation_class: str,
    image_operation: str,
) -> list[Json]:
    assignments: list[Json] = []
    for entry in contract["route_entries"]:
        if operation_class not in entry["applicable_task_classes"]:
            raise ValueError(
                "routing contract does not allow operation class "
                f"{operation_class}"
            )
        if image_operation not in entry["applicable_image_operations"]:
            raise ValueError(
                "routing contract does not allow image operation "
                f"{image_operation}"
            )
        for attempt in entry["attempt_numbers"]:
            assignments.append({
                "attempt": attempt,
                "routing_contract_sha256": contract_sha256,
                "routing_label": contract["routing_label"],
                "route_role": entry["role"],
                "route": entry["route"],
                "adapter_key": entry["adapter_key"],
                "provider": entry["provider"],
                "model": entry["model"],
                "model_revision": entry["model_revision"],
                "model_revision_status": entry["model_revision_status"],
                "endpoint": entry["endpoint"],
                "provider_operation": entry["provider_operation"],
                "allowed_fallback_reasons": entry["fallback_conditions"],
            })
    return sorted(assignments, key=lambda row: int(row["attempt"]))


def expected_attempt_routing(
    planned: Json,
    attempt: int,
    *,
    fallback_reason: str | None = None,
) -> Json:
    """Return the exact signed route identity assigned to one attempt."""

    resolved = planned.get("resolved_inputs")
    execution = resolved.get("execution") if isinstance(resolved, dict) else None
    routing = execution.get("routing") if isinstance(execution, dict) else None
    assignments = routing.get("attempts") if isinstance(routing, dict) else None
    if not isinstance(assignments, list):
        raise ValueError("planned execution routing assignments are unavailable")
    matches = [
        row
        for row in assignments
        if isinstance(row, dict) and row.get("attempt") == attempt
    ]
    if len(matches) != 1:
        raise ValueError(f"planned execution attempt {attempt} routing is unavailable")
    assignment = matches[0]
    allowed_reasons = assignment.get("allowed_fallback_reasons")
    if assignment.get("route_role") == "primary":
        if fallback_reason is not None:
            raise ValueError(
                f"primary attempt {attempt} cannot declare a fallback reason"
            )
    elif (
        not isinstance(allowed_reasons, list)
        or fallback_reason not in allowed_reasons
    ):
        raise ValueError(
            f"fallback attempt {attempt} requires a declared fallback reason"
        )
    expected = {
        field: matches[0].get(field)
        for field in _ATTEMPT_ROUTE_IDENTITY_FIELDS
    }
    expected["fallback_reason"] = fallback_reason
    return expected


def attempt_sequence_errors(
    attempts: list[Json],
    planned: Json,
    *,
    label: str,
) -> list[str]:
    """Validate signed attempt routing, outcomes, and fallback causality."""

    errors: list[str] = []
    maximum = planned.get("maximum_attempts")
    if type(maximum) is not int or not attempts or len(attempts) > maximum:
        return [f"{label} attempt count is out of bounds"]
    accepted: list[int] = []
    prior_outcomes: list[str] = []
    for index, attempt in enumerate(attempts, 1):
        fallback_reason = attempt.get("fallback_reason")
        try:
            expected_routing = expected_attempt_routing(
                planned,
                index,
                fallback_reason=fallback_reason,
            )
        except ValueError as exc:
            errors.append(f"{label} {exc}")
        else:
            actual_routing = {
                field: attempt.get(field)
                for field in ATTEMPT_ROUTING_FIELDS
            }
            if actual_routing != expected_routing:
                errors.append(
                    f"{label} attempt {index} route/provider/model differs"
                )

        accepted_value = attempt.get("accepted")
        outcome = attempt.get("attempt_outcome")
        provider_error = attempt.get("provider_error_code")
        qa_outcome = attempt.get("qa_outcome")
        if type(accepted_value) is not bool:
            errors.append(f"{label} attempt {index} accepted must be boolean")
        elif accepted_value:
            accepted.append(index)
        if outcome == "accepted":
            if accepted_value is not True or qa_outcome != "pass":
                errors.append(
                    f"{label} attempt {index} accepted outcome is inconsistent"
                )
            if provider_error is not None:
                errors.append(
                    f"{label} attempt {index} accepted outcome has provider error"
                )
        elif outcome == "qa_failed":
            if accepted_value is not False or qa_outcome != "fail":
                errors.append(
                    f"{label} attempt {index} QA-failed outcome is inconsistent"
                )
            if provider_error is not None:
                errors.append(
                    f"{label} attempt {index} QA-failed outcome has provider error"
                )
        elif outcome == "provider_failed":
            if accepted_value is not False or qa_outcome is not None:
                errors.append(
                    f"{label} attempt {index} provider-failed outcome is inconsistent"
                )
            if not isinstance(provider_error, str) or not provider_error.strip():
                errors.append(
                    f"{label} attempt {index} provider failure lacks an error code"
                )
        else:
            errors.append(f"{label} attempt {index} outcome is unsupported")

        if index == 3:
            expected_reason = (
                "grok_provider_failed_after_qa_failure"
                if prior_outcomes[-1:] == ["provider_failed"]
                and "qa_failed" in prior_outcomes[:-1]
                else "grok_provider_failed"
                if prior_outcomes[-1:] == ["provider_failed"]
                else "grok_qa_failed"
                if prior_outcomes[-1:] == ["qa_failed"]
                else None
            )
            if fallback_reason != expected_reason:
                errors.append(
                    f"{label} attempt 3 fallback reason does not match prior "
                    "signed outcomes"
                )
        prior_outcomes.append(str(outcome or ""))

        provider_failed = outcome == "provider_failed"
        candidate_fields = (
            attempt.get("candidate_image"),
            attempt.get("candidate_image_sha256"),
        )
        evaluator_report_fields = (
            attempt.get("evaluator_report"),
            attempt.get("evaluator_report_sha256"),
        )
        if provider_failed:
            if any(value is not None for value in candidate_fields):
                errors.append(
                    f"{label} attempt {index} provider failure declares a candidate"
                )
            if any(
                field in attempt
                for field in ("evaluator_report", "evaluator_report_sha256")
            ):
                errors.append(
                    f"{label} attempt {index} provider failure declares an "
                    "evaluator report"
                )
            if any(attempt.get(field) is not None for field in (
                "mask_image",
                "mask_image_sha256",
                "render_conformance_score",
                "hard_gate_pass",
                "edit_fidelity_score",
                "severity",
                "change_applied",
            )):
                errors.append(
                    f"{label} attempt {index} provider failure declares QA evidence"
                )
        else:
            report_path, report_hash = evaluator_report_fields
            if not isinstance(report_path, str) or not report_path.strip():
                errors.append(
                    f"{label} attempt {index} lacks an evaluator report path"
                )
            if not _hex_digest(report_hash):
                errors.append(
                    f"{label} attempt {index} lacks an evaluator report hash"
                )

        if provider_failed:
            continue
        if planned.get("kind") == "render":
            if (
                not valid_machine_score(attempt.get("render_conformance_score"))
                or type(attempt.get("hard_gate_pass")) is not bool
            ):
                errors.append(f"{label} render attempt {index} lacks machine scores")
            if attempt.get("mask_image") is not None:
                errors.append(f"{label} render attempt {index} declares a mask")
        elif (
            not valid_machine_score(attempt.get("edit_fidelity_score"))
            or attempt.get("severity") not in {"none", "minor", "major"}
            or type(attempt.get("change_applied")) is not bool
        ):
            errors.append(f"{label} edit attempt {index} lacks machine scores")

    if len(accepted) > 1:
        errors.append(f"{label} sequence has multiple accepted attempts")
    elif accepted and accepted[0] != len(attempts):
        errors.append(f"{label} accepted attempt must be final")
    if attempts[-1].get("attempt_outcome") == "provider_failed":
        errors.append(f"{label} final attempt cannot be a provider failure")
    return errors


def _executor_trust(config: Json, root: Path) -> tuple[Path, str, str]:
    """Resolve the only executor identity allowed to sign this config.

    Capture validation deliberately does not trust a key supplied only on the
    command line. The key id, path and exact public-key bytes must already be
    enrolled in the hash-bound frozen config.
    """

    trust = config.get("executor_trust")
    if not isinstance(trust, dict):
        raise ValueError("config executor trust is not enrolled")
    if trust.get("schema_version") != EXECUTOR_TRUST_SCHEMA:
        raise ValueError("config executor trust schema is unsupported")
    if trust.get("status") != "enrolled":
        raise ValueError("config executor trust is not enrolled")
    key_id = trust.get("key_id")
    if not isinstance(key_id, str) or not key_id.strip():
        raise ValueError("config executor key_id is empty")
    value = trust.get("public_key")
    if not isinstance(value, str) or "@sha256:" not in value:
        raise ValueError("config executor public key is not hash-pinned")
    relative, expected_hash = value.rsplit("@sha256:", 1)
    candidate = (root.resolve() / relative).resolve()
    if (
        not relative
        or Path(relative).is_absolute()
        or not candidate.is_relative_to(root.resolve())
        or not candidate.is_file()
    ):
        raise ValueError("config executor public key path is unavailable")
    if not _hex_digest(expected_hash) or file_sha256(candidate) != expected_hash:
        raise ValueError("config executor public key drifted")
    try:
        _load_capture_public_key(candidate)
    except (OSError, TypeError, ValueError) as exc:
        raise ValueError("config executor public key is invalid") from exc
    return candidate, key_id, expected_hash


def _resolved_assignment(
    source: Json,
    evaluation: Json,
    config: Json,
    binding: Json | None,
    routing_contract: Json,
    routing_contract_sha256: str,
) -> Json:
    """Resolve one provider-free execution and scoring contract.

    The returned object contains no provider output and performs no provider
    call. It freezes every semantic input an executor needs so the signed
    capture cannot substitute a different prompt, spec, edit or score target.
    """

    evaluation_id = str(evaluation["evaluation_id"])
    kind = str(evaluation["kind"])
    operation_class = str(evaluation["operation_class"])
    thresholds = config.get("thresholds")
    if not isinstance(thresholds, dict):
        raise ValueError("frozen config thresholds are unavailable")
    components = config.get("frozen_components")
    if not isinstance(components, dict):
        raise ValueError("frozen config components are unavailable")
    component_binding = {
        key: components.get(key)
        for key in (
            "ring_contract",
            "prompt_bundle",
            "evaluator_bundle",
            "routing",
            "routing_contract",
        )
    }
    if components.get("evaluator_report_contract") is not None:
        component_binding["evaluator_report_contract"] = components.get(
            "evaluator_report_contract"
        )
    if any(not isinstance(value, str) or not value for value in component_binding.values()):
        raise ValueError("resolved assignment requires frozen execution components")

    source_input: Json = {
        "filename": str(source["filename"]),
        "sha256": str(source["sha256"]),
        "role": "provider_source_and_fidelity_reference",
    }
    cases = {case.id: case for case in RING_GOLDEN_CASES}
    edits = {edit.id: edit for edit in CANONICAL_RING_EDITS}
    if kind == "render":
        case = cases.get(evaluation_id)
        if case is None:
            raise ValueError(f"unknown frozen render evaluation: {evaluation_id}")
        canonical_target_spec = build_ring_golden_spec(case).model_dump(mode="json")
        operation = ImageOperation.SPEC_RENDER
        evaluation_contract: Json = {
            "case": asdict(case),
            "canonical_target_spec": canonical_target_spec,
            "canonical_target_spec_sha256": canonical_object_sha256(
                canonical_target_spec
            ),
        }
        scoring: Json = {
            "metric": "score_spec_conformance.v1",
            "candidate_input": "candidate_image_sha256",
            "minimum_mean_score": thresholds.get("mean_render_conformance"),
            "hard_gate_pass_rate": thresholds.get("render_hard_gate_pass_rate"),
            "accepted_candidate_required": True,
        }
    elif kind == "edit":
        edit = edits.get(evaluation_id)
        canonical_na = (
            isinstance(binding, dict)
            and binding.get("applicability") == "not_applicable"
            and binding.get("not_applicable_reason")
            == CANONICAL_DELTA_INAPPLICABLE_REASON
        )
        if edit is None or (not edit.expected_valid and not canonical_na):
            raise ValueError(f"unknown or invalid frozen edit evaluation: {evaluation_id}")
        operation = (
            ImageOperation.VISUAL_ONLY_EDIT
            if edit.visual_only
            else ImageOperation.LOCAL_EDIT
        )
        evaluation_contract = {
            "edit": {
                **asdict(edit),
                "allowed_delta_prefixes": list(edit.allowed_delta_prefixes),
                "frozen_facts": list(edit.frozen_facts),
            },
        }
        scoring = {
            "metric": "score_edit_fidelity.v1",
            "reference_input": "source_input.sha256",
            "candidate_input": "candidate_image_sha256",
            "mask_input": "mask_image_sha256",
            "intended_change": edit.instruction,
            "minimum_mean_score": thresholds.get("mean_edit_fidelity"),
            "maximum_outside_mask_drift": thresholds.get("max_outside_mask_drift"),
            "mask_requires_selected_and_protected_pixels": True,
        }
    else:
        raise ValueError(f"unsupported frozen evaluation kind: {kind}")

    binding_errors: list[str] = []
    if not isinstance(binding, dict):
        binding_errors.append("reviewed source-specific assignment binding is missing")
        binding = {}
    elif binding.get("schema_version") != "facetta-frozen-source-assignment.v1":
        binding_errors.append("source-specific assignment schema is unsupported")
    for field in (
        "review_evidence_sha256",
        "source_spec_evidence_sha256",
        "component_map_sha256",
        "region_evidence_sha256",
    ):
        if not _hex_digest(binding.get(field)):
            binding_errors.append(f"source-specific {field} is not hash-bound")
    if binding.get("review_status") != "approved":
        binding_errors.append("source-specific assignment is not approved")
    applicability = binding.get("applicability")
    if applicability not in {"execute", "not_applicable"}:
        binding_errors.append("source-specific applicability is not terminal")
    if applicability == "not_applicable":
        if kind == "render":
            binding_errors.append("render assignment cannot be not_applicable")
        reason = binding.get("not_applicable_reason")
        if reason not in SUPPORTED_NOT_APPLICABLE_REASONS:
            binding_errors.append("not-applicable assignment reason is unsupported")
        if binding.get("source_sha256") != source_input["sha256"]:
            binding_errors.append(
                "not-applicable assignment source hash differs from workload"
            )
        if not binding_errors:
            return {
                "schema_version": RESOLVED_ASSIGNMENT_SCHEMA,
                "kind": kind,
                "evaluation_id": evaluation_id,
                "operation_class": operation_class,
                "source_input": source_input,
                "assignment_resolved": True,
                "resolution_status": "not_applicable",
                "execution_ready": False,
                "resolution_errors": [],
                "evaluation_contract": evaluation_contract,
                "applicability": {
                    "status": "not_applicable",
                    "reason": reason,
                    "review_evidence_sha256": binding["review_evidence_sha256"],
                },
                "execution": None,
                "scoring": scoring,
                "routing_contract_sha256": routing_contract_sha256,
                "frozen_component_bindings": component_binding,
            }

    source_spec = binding.get("source_spec")
    target_spec = binding.get("target_spec")
    if not isinstance(source_spec, dict) or not isinstance(target_spec, dict):
        binding_errors.append("reviewed source and target specifications are required")
    else:
        try:
            from facetta.spec import Spec

            source_spec = Spec.model_validate(source_spec).model_dump(mode="json")
            target_spec = Spec.model_validate(target_spec).model_dump(mode="json")
        except Exception:
            binding_errors.append("reviewed source or target specification is invalid")
    intent = binding.get("instruction")
    region = binding.get("region_description")
    frozen_facts = binding.get("frozen_facts")
    if not isinstance(intent, str) or not intent.strip():
        binding_errors.append("source-specific instruction is missing")
    if kind == "render":
        expected_intent = f"frozen founder corpus render: {evaluation_id}"
        if intent != expected_intent:
            binding_errors.append("source-specific render instruction differs")
        if target_spec != evaluation_contract["canonical_target_spec"]:
            binding_errors.append("source-specific render target differs from canonical case")
        if region is not None:
            binding_errors.append("render assignment cannot declare a local region")
    else:
        edit = edits[evaluation_id]
        if intent != edit.instruction:
            binding_errors.append("source-specific edit instruction differs")
        expected_region = None if edit.visual_only else edit.region
        if region != expected_region:
            binding_errors.append("source-specific edit region differs")
        if frozen_facts != list(edit.frozen_facts):
            binding_errors.append("source-specific frozen facts differ")
        if isinstance(source_spec, dict) and isinstance(target_spec, dict):
            try:
                expected_target, issues = apply_canonical_ring_edit(
                    Spec.model_validate(source_spec), edit
                )
                expected_target_raw = (
                    expected_target.model_dump(mode="json")
                    if expected_target is not None else None
                )
                if issues or expected_target_raw != target_spec:
                    binding_errors.append(
                        "source-specific edit target does not match the canonical delta"
                    )
            except Exception:
                binding_errors.append("source-specific canonical edit cannot be applied")
    if not isinstance(frozen_facts, list) or not all(
        isinstance(value, str) and value.strip() for value in frozen_facts
    ):
        binding_errors.append("source-specific frozen facts are missing")

    execution_ready = not binding_errors
    execution: Json | None = None
    if execution_ready:
        execution = {
            "image_operation": operation.value,
            "prompt_version": PROMPT_VERSIONS[operation],
            "intent": intent,
            "source_image_required": True,
            "source_spec": source_spec,
            "target_spec": target_spec,
            "region_description": region,
            "frozen_facts": frozen_facts,
            "expected_output": (
                "one photorealistic image faithful to the validated target spec "
                "and the source design identity"
                if kind == "render"
                else "only the requested presentation change"
                if operation is ImageOperation.VISUAL_ONLY_EDIT
                else "the requested local change and no unrelated redesign"
            ),
            "variant": 0,
            "fallback_allowed": True,
            "maximum_attempts": int(thresholds["max_attempts"]),
            "routing": {
                "routing_contract_sha256": routing_contract_sha256,
                "routing_label": routing_contract["routing_label"],
                "attempts": _routing_attempt_assignments(
                    routing_contract,
                    routing_contract_sha256,
                    operation_class=operation_class,
                    image_operation=operation.value,
                ),
            },
            "review_evidence_sha256": binding["review_evidence_sha256"],
            "source_spec_evidence_sha256": binding["source_spec_evidence_sha256"],
            "component_map_sha256": binding["component_map_sha256"],
            "region_evidence_sha256": binding["region_evidence_sha256"],
        }

    return {
        "schema_version": RESOLVED_ASSIGNMENT_SCHEMA,
        "kind": kind,
        "evaluation_id": evaluation_id,
        "operation_class": operation_class,
        "source_input": source_input,
        "assignment_resolved": execution_ready,
        "resolution_status": "execute" if execution_ready else "unresolved",
        "execution_ready": execution_ready,
        "resolution_errors": binding_errors,
        "evaluation_contract": evaluation_contract,
        "execution": execution,
        "scoring": scoring,
        "routing_contract_sha256": routing_contract_sha256,
        "frozen_component_bindings": component_binding,
    }


def _assignment_bindings(
    config: Json,
    workload_path: Path,
    root: Path,
) -> tuple[dict[tuple[str, str, str], Json], Json]:
    """Load an optional, separately reviewed and hash-pinned input bundle."""

    components = config.get("frozen_components")
    pin = components.get("resolved_assignment_bundle") if isinstance(components, dict) else None
    if pin is None:
        return {}, {
            "status": "not_enrolled",
            "bundle_sha256": None,
            "assignment_count": 0,
        }
    bundle_path, bundle_hash = _pinned_path(config, "resolved_assignment_bundle", root)
    bundle = _load_object(bundle_path)
    reviewer = verify_signed_assignment_bundle(
        bundle,
        config,
        repository_root=root,
    )
    if bundle.get("workload_sha256") != file_sha256(workload_path):
        raise ValueError("resolved assignment bundle workload hash differs")
    corpus_run_id = bundle.get("corpus_run_id")
    if not isinstance(corpus_run_id, str) or not corpus_run_id.strip():
        raise ValueError("resolved assignment bundle corpus_run_id is empty")
    rows = bundle.get("assignments")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("resolved assignment bundle assignments must be objects")
    resolved: dict[tuple[str, str, str], Json] = {}
    for row in rows:
        key = (
            str(row.get("source_filename") or ""),
            str(row.get("kind") or ""),
            str(row.get("evaluation_id") or ""),
        )
        if key in resolved:
            raise ValueError("resolved assignment bundle contains duplicate assignments")
        binding = row.get("binding")
        if not all(key) or not isinstance(binding, dict):
            raise ValueError("resolved assignment bundle row is incomplete")
        resolved[key] = binding
    return resolved, {
        "status": "enrolled",
        "bundle_sha256": bundle_hash,
        "corpus_run_id": corpus_run_id,
        "assignment_count": len(resolved),
        "reviewer_key_id": reviewer.key_id,
        "reviewer_profile_sha256": reviewer.reviewer_profile_sha256,
        "reviewed_template_sha256": bundle["reviewed_template_sha256"],
    }


def validate_workload_definition(
    manifest_path: Path,
    config_path: Path,
    workload_path: Path,
    *,
    repository_root: Path | None = None,
) -> Json:
    """Validate one explicit source-to-evaluation workload matrix.

    The returned object is a deterministic summary only.  A passing definition
    is not a capture, a quality result, or a release decision.
    """

    root = (repository_root or Path(__file__).resolve().parents[2]).resolve()
    manifest = _load_object(manifest_path)
    config = _load_object(config_path)
    workload = _load_object(workload_path)
    errors: list[str] = []
    routing_contract: Json | None = None
    routing_contract_sha256: str | None = None

    if workload.get("schema_version") != WORKLOAD_SCHEMA:
        errors.append("unsupported workload schema_version")
    if workload.get("corpus_id") != manifest.get("corpus_id"):
        errors.append("workload corpus_id differs from manifest")
    if workload.get("manifest_sha256") != file_sha256(manifest_path):
        errors.append("workload manifest hash differs")
    if workload.get("config_id") != config.get("config_id"):
        errors.append("workload config_id differs from config")
    if config.get("manifest_sha256") != file_sha256(manifest_path):
        errors.append("config manifest hash differs")
    try:
        pinned_workload, _ = _pinned_path(config, "capture_workload", root)
        if pinned_workload != workload_path.resolve():
            errors.append("validated workload path differs from config pin")
    except ValueError as exc:
        errors.append(str(exc))
    try:
        routing_contract, routing_contract_sha256 = _load_routing_contract(
            config,
            root,
        )
    except ValueError as exc:
        errors.append(str(exc))

    manifest_rows = manifest.get("sources")
    if not isinstance(manifest_rows, list):
        manifest_rows = []
        errors.append("manifest sources must be a list")
    manifest_sources = {
        str(row.get("filename") or ""): str(row.get("sha256") or "")
        for row in manifest_rows
        if isinstance(row, dict)
    }
    expected_count = manifest.get("expected_source_count")
    if expected_count != len(manifest_sources):
        errors.append("manifest source count is inconsistent")
    unsafe_source_names = sorted(
        filename for filename in manifest_sources
        if not _portable_source_filename(filename)
    )
    if unsafe_source_names:
        errors.append(
            "manifest source filenames are not portable artifact identifiers: "
            + ", ".join(unsafe_source_names)
        )

    matrix = workload.get("sources")
    if not isinstance(matrix, list):
        matrix = []
        errors.append("workload sources must be a list")
    source_rows = [row for row in matrix if isinstance(row, dict)]
    if len(source_rows) != len(matrix):
        errors.append("every workload source must be an object")
    names = [str(row.get("filename") or "") for row in source_rows]
    duplicates = _duplicates(names)
    if duplicates:
        errors.append("duplicate workload sources: " + ", ".join(duplicates))
    if set(names) != set(manifest_sources):
        missing = sorted(set(manifest_sources) - set(names))
        extra = sorted(set(names) - set(manifest_sources))
        if missing:
            errors.append("workload omits manifest sources: " + ", ".join(missing))
        if extra:
            errors.append("workload has unknown sources: " + ", ".join(extra))

    evaluation = manifest.get("evaluation_slice")
    if not isinstance(evaluation, dict):
        evaluation = {}
        errors.append("manifest evaluation_slice must be an object")
    ring_sources = set(map(str, evaluation.get("ring_source_filenames", [])))
    render_ids = list(map(str, evaluation.get("render_case_ids", [])))
    operation_ids = list(map(str, evaluation.get("operation_ids", [])))
    operation_classes = evaluation.get("operation_classes")
    quick_ids = set(map(
        str,
        operation_classes.get("quick_appearance", [])
        if isinstance(operation_classes, dict) else [],
    ))
    structural_ids = set(map(
        str,
        operation_classes.get("structural", [])
        if isinstance(operation_classes, dict) else [],
    ))
    expected_evaluations = {
        ("render", evaluation_id) for evaluation_id in render_ids
    } | {("edit", evaluation_id) for evaluation_id in operation_ids}

    evaluation_sets = workload.get("evaluation_sets")
    if not isinstance(evaluation_sets, dict):
        evaluation_sets = {}
        errors.append("workload evaluation_sets must be an object")
    ring_set_id = workload.get("ring_quality_evaluation_set_id")
    ring_set = evaluation_sets.get(ring_set_id) if isinstance(ring_set_id, str) else None
    if not isinstance(ring_set, list):
        ring_set = []
        errors.append("ring quality evaluation set is unavailable")
    declared_evaluations: set[tuple[str, str]] = set()
    for index, raw in enumerate(ring_set, 1):
        if not isinstance(raw, dict):
            errors.append(f"ring evaluation {index} must be an object")
            continue
        key = (str(raw.get("kind") or ""), str(raw.get("evaluation_id") or ""))
        if _PORTABLE_EVALUATION_ID.fullmatch(key[1]) is None:
            errors.append(
                f"ring evaluation {index} has a non-portable evaluation_id"
            )
        if key in declared_evaluations:
            errors.append("duplicate ring evaluation: " + ":".join(key))
        declared_evaluations.add(key)
        expected_class = (
            "render_conformance"
            if key[0] == "render"
            else "quick_appearance"
            if key[1] in quick_ids
            else "structural"
            if key[1] in structural_ids
            else None
        )
        if raw.get("operation_class") != expected_class:
            errors.append("ring evaluation class differs: " + ":".join(key))
    if declared_evaluations != expected_evaluations:
        errors.append("ring evaluation set must match the manifest workload exactly")

    quality_names: set[str] = set()
    for row in source_rows:
        filename = str(row.get("filename") or "")
        if row.get("sha256") != manifest_sources.get(filename):
            errors.append(f"workload source hash differs for {filename}")
        if row.get("integrity_required") is not True:
            errors.append(f"source integrity is not required for {filename}")
        quality = row.get("quality")
        if filename in ring_sources:
            if quality != {"slice": "ring", "evaluation_set_id": ring_set_id}:
                errors.append(f"ring source has invalid quality assignment: {filename}")
            else:
                quality_names.add(filename)
        elif quality is not None:
            errors.append(f"non-ring source has a quality assignment: {filename}")

    if quality_names != ring_sources:
        errors.append("quality matrix does not exactly cover the declared ring slice")
    artifact_stem_collisions = _artifact_stem_collisions(
        quality_names,
        declared_evaluations,
    )
    if artifact_stem_collisions:
        errors.append(
            "provider artifact output stem collisions: "
            + "; ".join(artifact_stem_collisions)
        )
    declared_integrity_count = workload.get("expected_integrity_source_count")
    declared_quality_count = workload.get("expected_quality_source_count")
    if declared_integrity_count != len(manifest_sources):
        errors.append("expected_integrity_source_count is inconsistent")
    if declared_quality_count != len(ring_sources):
        errors.append("expected_quality_source_count is inconsistent")

    summary: Json = {
        "schema_version": "facetta-frozen-capture-workload-validation.v1",
        "status": "pass" if not errors else "fail",
        "provider_calls": 0,
        "errors": errors,
        "manifest_sha256": file_sha256(manifest_path),
        "config_sha256": file_sha256(config_path),
        "workload_sha256": file_sha256(workload_path),
        "routing_contract_sha256": routing_contract_sha256,
        "routing_label": (
            routing_contract.get("routing_label")
            if isinstance(routing_contract, dict)
            else None
        ),
        "integrity_source_count": len(manifest_sources),
        "quality_source_count": len(quality_names),
        "quality_evaluations_per_source": len(declared_evaluations),
        "planned_evaluation_sequence_count": (
            len(quality_names) * len(declared_evaluations)
        ),
        "corpus_gate_ready": False,
        "release_boundary": (
            "A workload definition validates scope only. It contains no provider "
            "output, quality score, reviewer decision, or founder approval."
        ),
    }
    return summary


def build_provider_call_plan(
    manifest_path: Path,
    config_path: Path,
    workload_path: Path,
    *,
    repository_root: Path | None = None,
) -> Json:
    validation = validate_workload_definition(
        manifest_path,
        config_path,
        workload_path,
        repository_root=repository_root,
    )
    if validation["status"] != "pass":
        raise ValueError("invalid workload definition: " + "; ".join(validation["errors"]))
    workload = _load_object(workload_path)
    config = _load_object(config_path)
    root = (repository_root or Path(__file__).resolve().parents[2]).resolve()
    routing_contract, routing_contract_sha256 = _load_routing_contract(config, root)
    assignment_bindings, assignment_bundle = _assignment_bindings(
        config, workload_path, root,
    )
    ring_set_id = str(workload["ring_quality_evaluation_set_id"])
    evaluations = workload["evaluation_sets"][ring_set_id]
    max_attempts = int(config["thresholds"]["max_attempts"])
    try:
        _, executor_key_id, executor_public_key_sha256 = _executor_trust(
            config,
            root,
        )
        executor_trust = {
            "status": "enrolled",
            "key_id": executor_key_id,
            "public_key_sha256": executor_public_key_sha256,
        }
    except ValueError:
        # Planning remains provider-free and useful before enrollment. Capture
        # validation below is the authority and fails closed without this key.
        executor_trust = {
            "status": "not_enrolled",
            "key_id": None,
            "public_key_sha256": None,
        }
    items: list[Json] = []
    for source in sorted(workload["sources"], key=lambda row: row["filename"]):
        quality = source.get("quality")
        if not isinstance(quality, dict):
            continue
        for evaluation in sorted(
            evaluations,
            key=lambda row: (row["kind"], row["evaluation_id"]),
        ):
            kind = str(evaluation["kind"])
            evaluation_id = str(evaluation["evaluation_id"])
            stem = f"{Path(source['filename']).stem}--{kind}--{evaluation_id}"
            binding = assignment_bindings.get((
                str(source["filename"]), kind, evaluation_id,
            ))
            resolved_inputs = _resolved_assignment(
                source,
                evaluation,
                config,
                binding,
                routing_contract,
                routing_contract_sha256,
            )
            items.append({
                "source_filename": source["filename"],
                "source_sha256": source["sha256"],
                "corpus_run_id": assignment_bundle.get("corpus_run_id"),
                "quality_slice": "ring",
                "kind": kind,
                "evaluation_id": evaluation_id,
                "operation_class": evaluation.get("operation_class"),
                "resolved_inputs": resolved_inputs,
                "resolved_inputs_sha256": canonical_object_sha256(resolved_inputs),
                "maximum_attempts": max_attempts,
                "candidate_artifact_stem": stem,
                "mask_artifact_stem": stem + "--mask" if kind == "edit" else None,
                "evaluator_report_artifact_stem": stem + "--evaluator-report",
            })
    execution_ready_count = sum(
        bool(item["resolved_inputs"]["execution_ready"]) for item in items
    )
    assignment_resolved_count = sum(
        bool(item["resolved_inputs"]["assignment_resolved"]) for item in items
    )
    not_applicable_count = sum(
        item["resolved_inputs"]["resolution_status"] == "not_applicable"
        for item in items
    )
    extra_bindings = len(set(assignment_bindings) - {
        (item["source_filename"], item["kind"], item["evaluation_id"])
        for item in items
    })
    if extra_bindings:
        raise ValueError("resolved assignment bundle contains unplanned assignments")
    return {
        "schema_version": PLAN_SCHEMA,
        "status": "plan_ready",
        "corpus_id": workload["corpus_id"],
        "manifest_sha256": validation["manifest_sha256"],
        "config_sha256": validation["config_sha256"],
        "workload_sha256": validation["workload_sha256"],
        "routing_contract_sha256": routing_contract_sha256,
        "routing_label": routing_contract["routing_label"],
        "provider_calls_executed": 0,
        "integrity_source_count": validation["integrity_source_count"],
        "quality_source_count": validation["quality_source_count"],
        "planned_evaluation_sequence_count": len(items),
        "maximum_provider_attempt_count": execution_ready_count * max_attempts,
        "logical_scope_maximum_attempt_count": len(items) * max_attempts,
        "executor_trust": executor_trust,
        "assignment_bundle": assignment_bundle,
        "corpus_run_id": assignment_bundle.get("corpus_run_id"),
        "resolved_sequence_count": assignment_resolved_count,
        "execution_ready_sequence_count": execution_ready_count,
        "not_applicable_sequence_count": not_applicable_count,
        "unresolved_sequence_count": len(items) - assignment_resolved_count,
        "items": items,
        "capture_status": (
            "blocked_unresolved_assignments"
            if assignment_resolved_count != len(items)
            else "not_run"
        ),
        "corpus_gate_ready": False,
    }


def canonical_capture_payload(capture: Json) -> bytes:
    unsigned = {key: value for key, value in capture.items() if key != "signature"}
    return json.dumps(
        unsigned,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def not_applicable_assignment_rows(plan: Json) -> list[Json]:
    """Project reviewed non-applicable rows into a signed, deterministic list.

    A non-applicable logical row is still part of the frozen 1,044-row scope,
    but it must never become a provider request or a synthetic failed attempt.
    The projection retains the exact reviewed reason and plan binding so the
    capture and replay verifiers can prove that no row was silently dropped.
    """

    rows: list[Json] = []
    items = plan.get("items")
    if not isinstance(items, list):
        raise ValueError("frozen plan items are invalid")
    for planned in items:
        if not isinstance(planned, dict):
            raise ValueError("frozen plan item is invalid")
        resolved = planned.get("resolved_inputs")
        if not isinstance(resolved, dict):
            raise ValueError("frozen plan resolved inputs are invalid")
        if resolved.get("resolution_status") != "not_applicable":
            continue
        applicability = resolved.get("applicability")
        if not isinstance(applicability, dict):
            raise ValueError("not-applicable assignment lacks reviewed evidence")
        rows.append({
            "kind": planned.get("kind"),
            "evaluation_id": planned.get("evaluation_id"),
            "operation_class": planned.get("operation_class"),
            "source_filename": planned.get("source_filename"),
            "source_sha256": planned.get("source_sha256"),
            "resolved_inputs_sha256": planned.get("resolved_inputs_sha256"),
            "reason": applicability.get("reason"),
            "review_evidence_sha256": applicability.get(
                "review_evidence_sha256"
            ),
        })
    return sorted(
        rows,
        key=lambda row: (
            str(row["kind"]),
            str(row["evaluation_id"]),
            str(row["source_filename"]),
        ),
    )


def _artifact_path(capture_path: Path, value: object) -> Path | None:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        return None
    root = capture_path.parent.resolve()
    candidate = (root / value).resolve()
    if not candidate.is_relative_to(root):
        return None
    return candidate


def _load_capture_public_key(path: Path) -> Ed25519PublicKey:
    content = path.read_bytes()
    if len(content) == 32:
        return Ed25519PublicKey.from_public_bytes(content)
    key = load_pem_public_key(content)
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("capture public key is not Ed25519")
    return key


def validate_capture_envelope(
    capture_path: Path,
    manifest_path: Path,
    config_path: Path,
    workload_path: Path,
    *,
    capture_public_key_path: Path,
    capture_key_id: str,
    repository_root: Path | None = None,
) -> Json:
    """Validate a secured executor's signed capture without replaying quality."""

    plan = build_provider_call_plan(
        manifest_path,
        config_path,
        workload_path,
        repository_root=repository_root,
    )
    capture = _load_object(capture_path)
    config = _load_object(config_path)
    root = (repository_root or Path(__file__).resolve().parents[2]).resolve()
    errors: list[str] = []
    if plan["unresolved_sequence_count"]:
        errors.append(
            "frozen plan contains unresolved source-specific assignments; "
            "capture is forbidden"
        )
    if plan["executor_trust"]["status"] != "enrolled":
        errors.append("frozen plan has no enrolled executor")
    if capture.get("schema_version") != CAPTURE_SCHEMA:
        errors.append("unsupported capture schema_version")
    corpus_run_id = capture.get("corpus_run_id")
    if not isinstance(corpus_run_id, str) or not corpus_run_id.strip():
        errors.append("capture corpus_run_id is empty")
    elif corpus_run_id != plan.get("corpus_run_id"):
        errors.append("capture corpus_run_id differs from the preassigned plan run")
    for field in ("manifest_sha256", "config_sha256", "workload_sha256"):
        if capture.get(field) != plan[field]:
            errors.append(f"capture {field} differs from the frozen plan")

    expected_logical = {
        (row["kind"], row["evaluation_id"], row["source_filename"]): row
        for row in plan["items"]
    }
    expected = {
        key: row
        for key, row in expected_logical.items()
        if row["resolved_inputs"].get("execution_ready") is True
    }
    expected_not_applicable = not_applicable_assignment_rows(plan)
    if capture.get("assignment_bundle_sha256") != plan["assignment_bundle"].get(
        "bundle_sha256"
    ):
        errors.append("capture assignment bundle hash differs from the frozen plan")
    if capture.get("not_applicable_assignments") != expected_not_applicable:
        errors.append(
            "capture not-applicable assignments differ from the frozen plan"
        )
    attempts = capture.get("attempts")
    if not isinstance(attempts, list):
        attempts = []
        errors.append("capture attempts must be a list")
    grouped: dict[tuple[str, str, str], list[Json]] = defaultdict(list)
    artifact_count = 0
    artifact_paths_seen: set[str] = set()
    for index, row in enumerate(attempts, 1):
        if not isinstance(row, dict):
            errors.append(f"capture attempt {index} must be an object")
            continue
        key = (
            str(row.get("kind") or ""),
            str(row.get("evaluation_id") or ""),
            str(row.get("source_filename") or ""),
        )
        planned = expected.get(key)
        if planned is None:
            if key in expected_logical:
                errors.append(
                    "capture attempted a reviewed non-applicable assignment: "
                    + ":".join(key)
                )
            else:
                errors.append(
                    "capture contains an unplanned assignment: " + ":".join(key)
                )
            continue
        if row.get("source_sha256") != planned["source_sha256"]:
            errors.append(f"capture source hash differs for attempt {index}")
        if row.get("resolved_inputs_sha256") != planned["resolved_inputs_sha256"]:
            errors.append(f"capture resolved inputs hash differs for attempt {index}")
        grouped[key].append(row)
        if row.get("attempt_outcome") == "provider_failed":
            continue
        for field in ("candidate_image", "mask_image"):
            if field == "mask_image" and key[0] != "edit":
                if row.get(field) is not None:
                    errors.append(f"render attempt {index} declares a mask")
                continue
            artifact = _artifact_path(capture_path, row.get(field))
            expected_hash = row.get(f"{field}_sha256")
            relative_path = row.get(field)
            if isinstance(relative_path, str) and relative_path in artifact_paths_seen:
                errors.append(f"capture artifact path is reused: {relative_path}")
            elif isinstance(relative_path, str):
                artifact_paths_seen.add(relative_path)
            if artifact is None or not artifact.is_file():
                errors.append(f"capture attempt {index} has invalid {field} path")
            elif not _hex_digest(expected_hash) or file_sha256(artifact) != expected_hash:
                errors.append(f"capture attempt {index} {field} hash differs")
            else:
                artifact_count += 1

        report_path = row.get("evaluator_report")
        evaluator_report = _artifact_path(capture_path, report_path)
        expected_report_hash = row.get("evaluator_report_sha256")
        if isinstance(report_path, str) and report_path in artifact_paths_seen:
            errors.append(f"capture artifact path is reused: {report_path}")
        elif isinstance(report_path, str):
            artifact_paths_seen.add(report_path)
        if evaluator_report is None or not evaluator_report.is_file():
            errors.append(
                f"capture attempt {index} has invalid evaluator_report path"
            )
            continue
        if (
            not _hex_digest(expected_report_hash)
            or file_sha256(evaluator_report) != expected_report_hash
        ):
            errors.append(
                f"capture attempt {index} evaluator_report hash differs"
            )
            continue
        artifact_count += 1
        try:
            report = _load_object(evaluator_report)
            replay_attempt = {
                **row,
                "source_image_sha256": row.get("source_sha256"),
            }
            derived = validate_and_replay_evaluator_report(
                report, planned, replay_attempt,
            )
        except (OSError, TypeError, ValueError) as exc:
            errors.append(
                f"capture attempt {index} evaluator report is invalid: {exc}"
            )
            continue
        if not isinstance(derived, dict):
            errors.append(
                f"capture attempt {index} evaluator replay returned no projection"
            )
            continue
        projection_fields = _EVALUATOR_REPORT_PROJECTION_FIELDS[key[0]]
        missing_projection_fields = [
            field for field in projection_fields if field not in derived
        ]
        if missing_projection_fields:
            errors.append(
                f"capture attempt {index} evaluator replay projection is incomplete"
            )
            continue
        signed_projection = {field: row.get(field) for field in projection_fields}
        replayed_projection = {field: derived[field] for field in projection_fields}
        if canonical_object_sha256(signed_projection) != canonical_object_sha256(
            replayed_projection
        ):
            errors.append(
                f"capture attempt {index} signed evaluator projection differs "
                "from replay"
            )

    missing = sorted(set(expected) - set(grouped))
    if missing:
        errors.append(f"capture is missing {len(missing)} planned evaluation sequences")
    max_attempts = max((int(row["maximum_attempts"]) for row in expected.values()), default=0)
    for key, rows in grouped.items():
        indexes = [row.get("attempt") for row in rows]
        if (
            any(type(index) is not int for index in indexes)
            or sorted(indexes) != list(range(1, len(rows) + 1))
            or len(rows) > max_attempts
        ):
            errors.append("capture attempts are not contiguous/in-bounds: " + ":".join(key))
        planned = expected.get(key)
        if planned is not None:
            ordered_rows = sorted(
                rows,
                key=lambda row: (
                    row.get("attempt")
                    if type(row.get("attempt")) is int
                    else max_attempts + 1
                ),
            )
            errors.extend(attempt_sequence_errors(
                ordered_rows,
                planned,
                label="capture " + ":".join(key),
            ))

    persistence = capture.get("persistence_evidence_ref")
    if not isinstance(persistence, dict):
        errors.append("capture persistence_evidence_ref is missing")
    else:
        artifact = _artifact_path(capture_path, persistence.get("relative_path"))
        expected_hash = persistence.get("sha256")
        if artifact is None or not artifact.is_file():
            errors.append("capture persistence evidence path is invalid")
        elif not _hex_digest(expected_hash) or file_sha256(artifact) != expected_hash:
            errors.append("capture persistence evidence hash differs")

    signature = capture.get("signature")
    signature_status = "not_verified"
    trusted_public_key_path: Path | None = None
    trusted_key_id: str | None = None
    trusted_public_key_hash: str | None = None
    try:
        trusted_public_key_path, trusted_key_id, trusted_public_key_hash = (
            _executor_trust(config, root)
        )
    except ValueError as exc:
        errors.append(str(exc))
    try:
        supplied_public_key_hash = file_sha256(capture_public_key_path)
    except OSError:
        supplied_public_key_hash = None
        errors.append("capture public key is unavailable")
    if trusted_public_key_path is not None and (
        capture_public_key_path.resolve() != trusted_public_key_path
        or supplied_public_key_hash != trusted_public_key_hash
    ):
        errors.append("capture public key is not the config-enrolled executor key")
    if not capture_key_id.strip() or (
        trusted_key_id is not None and capture_key_id != trusted_key_id
    ):
        errors.append("capture key_id is not the config-enrolled executor key_id")
    if not isinstance(signature, dict):
        errors.append("capture is unsigned")
    elif (
        signature.get("algorithm") != "Ed25519"
        or signature.get("key_id") != capture_key_id
        or signature.get("public_key_sha256") != supplied_public_key_hash
        or (
            trusted_public_key_hash is not None
            and signature.get("public_key_sha256") != trusted_public_key_hash
        )
        or not isinstance(signature.get("value"), str)
    ):
        errors.append("capture signature metadata is invalid")
    elif trusted_public_key_path is not None:
        try:
            decoded = base64.b64decode(signature["value"], validate=True)
            _load_capture_public_key(trusted_public_key_path).verify(
                decoded,
                canonical_capture_payload(capture),
            )
            signature_status = "verified"
        except (InvalidSignature, OSError, TypeError, ValueError):
            errors.append("capture signature is invalid")

    return {
        "schema_version": "facetta-frozen-capture-validation.v1",
        "status": "pass" if not errors else "fail",
        "provider_calls": 0,
        "errors": errors,
        "signature_status": signature_status,
        "corpus_run_id": (
            corpus_run_id
            if isinstance(corpus_run_id, str) and corpus_run_id.strip()
            else None
        ),
        "planned_evaluation_sequence_count": len(expected_logical),
        "execution_ready_evaluation_sequence_count": len(expected),
        "logical_evaluation_sequence_count": len(expected_logical),
        "not_applicable_evaluation_sequence_count": len(
            expected_not_applicable
        ),
        "captured_evaluation_sequence_count": len(set(expected) & set(grouped)),
        "captured_attempt_count": len(attempts),
        "verified_artifact_count": artifact_count,
        "corpus_gate_ready": False,
        "release_boundary": (
            "A signed capture proves executor provenance and artifact binding only. "
            "It is not the signed GIA review or founder release decision."
        ),
    }


__all__ = [
    "ASSIGNMENT_BUNDLE_SCHEMA",
    "ATTEMPT_OUTCOME_FIELDS",
    "ATTEMPT_ROUTING_FIELDS",
    "CAPTURE_SCHEMA",
    "EXECUTOR_TRUST_SCHEMA",
    "FROZEN_ROUTING_LABEL",
    "PLAN_SCHEMA",
    "RESOLVED_ASSIGNMENT_SCHEMA",
    "ROUTING_CONTRACT_SCHEMA",
    "WORKLOAD_SCHEMA",
    "build_provider_call_plan",
    "attempt_sequence_errors",
    "canonical_capture_payload",
    "canonical_object_sha256",
    "expected_attempt_routing",
    "file_sha256",
    "not_applicable_assignment_rows",
    "validate_capture_envelope",
    "valid_machine_score",
    "validate_workload_definition",
]

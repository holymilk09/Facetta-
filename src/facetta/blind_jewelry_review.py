"""Blind, criterion-level jewelry review contracts.

This module deliberately separates the reviewer-visible packet from executor
and evaluator evidence.  A packet contains only the selected images, their
hashes, the reviewed intent, and the rubric.  Machine attempts, scores,
provider routing, retries, and machine verdicts are not part of this schema.

The review ledger is a second artifact.  It binds the exact packet, reviewer
profile, local timezone, selected image hashes, and criterion-level decisions
under an Ed25519 signature.  Acceptance is derived only after validation; a
reviewer cannot submit an ``accepted`` Boolean.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from copy import deepcopy
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


Json = dict[str, Any]

BLIND_REVIEW_PACKET_SCHEMA = "facetta-blind-jewelry-review-packet.v2"
BLIND_REVIEW_LEDGER_SCHEMA = "facetta-blind-jewelry-review-ledger.v2"
BLIND_REVIEW_CRITERIA_SCHEMA = "facetta-blind-jewelry-review-criteria.v2"

GIA_VISUAL_FIDELITY_ROLE = "gia_visual_fidelity_reviewer"
INDEPENDENT_DESIGNER_ROLE = "independent_jewelry_designer"

PASS_RATING = "pass"
FAIL_RATING = "fail"
NOT_OBSERVABLE_RATING = "not_observable"
NOT_APPLICABLE_RATING = "not_applicable"
REVIEW_RATINGS = frozenset({
    PASS_RATING,
    FAIL_RATING,
    NOT_OBSERVABLE_RATING,
    NOT_APPLICABLE_RATING,
})

_HEX_LENGTH = 64
_FORBIDDEN_REVIEWER_KEYS = frozenset({
    "accepted",
    "attempt",
    "change_applied",
    "hard_gate_pass",
    "model",
    "provider",
    "retry",
    "score",
    "severity",
})


def _criterion(
    criterion_id: str,
    prompt: str,
    *,
    required_for_acceptance: bool = True,
    not_applicable_allowed: bool = False,
) -> Json:
    return {
        "criterion_id": criterion_id,
        "prompt": prompt,
        "required_for_acceptance": required_for_acceptance,
        "not_applicable_allowed": not_applicable_allowed,
    }


_CRITERION_TEMPLATES: dict[tuple[str, str, str], tuple[Json, ...]] = {
    (GIA_VISUAL_FIDELITY_ROLE, "render", "render_conformance"): (
        _criterion(
            "source_and_candidate_reviewable",
            "Both images permit a clear, like-for-like visual comparison.",
        ),
        _criterion(
            "gemstone_identity_fidelity",
            "Visible gemstone count, cut, orientation, color appearance, and placement match the intended design.",
        ),
        _criterion(
            "setting_geometry_fidelity",
            "Visible prongs, bezels, supports, shoulders, halo, and shank geometry match the intended design.",
        ),
        _criterion(
            "jewelry_construction_coherence",
            "Visible jewelry construction is continuous, symmetric where intended, and physically coherent at image-review level.",
        ),
        _criterion(
            "frozen_facts_preserved",
            "Every declared frozen fact that is visually observable remains unchanged.",
        ),
        _criterion(
            "unrelated_drift_and_artifacts_absent",
            "No unrelated redesign, duplicated or missing parts, broken geometry, or distracting generation artifact is visible.",
        ),
    ),
    (GIA_VISUAL_FIDELITY_ROLE, "edit", "quick_appearance"): (
        _criterion(
            "intended_change_observable",
            "The requested appearance change is clearly present and confined to its intended meaning.",
        ),
        _criterion(
            "target_region_control",
            "The declared target region changed without visible spill into protected regions.",
        ),
        _criterion(
            "frozen_facts_preserved",
            "Every declared frozen fact that is visually observable remains unchanged.",
        ),
        _criterion(
            "stone_and_setting_integrity",
            "Gemstone inventory, placement, setting geometry, and support relationships remain intact.",
        ),
        _criterion(
            "unrelated_drift_and_artifacts_absent",
            "No unrelated redesign, duplicated or missing parts, broken geometry, or distracting generation artifact is visible.",
        ),
    ),
    (GIA_VISUAL_FIDELITY_ROLE, "edit", "structural"): (
        _criterion(
            "intended_structure_observable",
            "The requested structural change is clearly present and visually decidable.",
        ),
        _criterion(
            "target_region_geometry",
            "The declared target region has the intended geometry and joins cleanly to unchanged structure.",
        ),
        _criterion(
            "gemstone_setting_integrity",
            "Gemstones, seats, prongs or bezels, supports, and clearances remain visually coherent.",
        ),
        _criterion(
            "frozen_facts_preserved",
            "Every declared frozen fact that is visually observable remains unchanged.",
        ),
        _criterion(
            "outside_region_drift_absent",
            "No unrelated geometry, material, stone, silhouette, or motif changed outside the target region.",
        ),
        _criterion(
            "jewelry_construction_coherence",
            "Visible construction remains continuous, wearable, symmetric where intended, and free of broken geometry.",
        ),
    ),
    (INDEPENDENT_DESIGNER_ROLE, "render", "render_conformance"): (
        _criterion(
            "brief_and_design_direction_match",
            "The candidate communicates the intended brief and design direction.",
        ),
        _criterion(
            "design_identity_preserved",
            "The defining silhouette, motif, proportions, materials, and focal hierarchy remain recognizable.",
        ),
        _criterion(
            "design_is_visually_coherent",
            "The result reads as one intentional jewelry design rather than assembled or contradictory parts.",
        ),
        _criterion(
            "presentation_is_decision_ready",
            "The image is clear and artifact-free enough to support a design decision.",
        ),
    ),
    (INDEPENDENT_DESIGNER_ROLE, "edit", "quick_appearance"): (
        _criterion(
            "requested_appearance_achieved",
            "The requested appearance change is achieved at a useful design-review quality.",
        ),
        _criterion(
            "design_identity_preserved",
            "The original design identity and all unrelated visual decisions remain intact.",
        ),
        _criterion(
            "comparison_is_decidable",
            "The source and candidate make the requested difference easy to judge.",
        ),
        _criterion(
            "presentation_is_usable",
            "The result is coherent and artifact-free enough for continued design work.",
        ),
    ),
    (INDEPENDENT_DESIGNER_ROLE, "edit", "structural"): (
        _criterion(
            "requested_structure_achieved",
            "The requested structural change is achieved and visually unambiguous.",
        ),
        _criterion(
            "design_identity_preserved",
            "The defining design language remains intact outside the requested structural change.",
        ),
        _criterion(
            "wearable_design_coherence",
            "The changed form still reads as intentional, balanced, and plausibly wearable jewelry.",
        ),
        _criterion(
            "presentation_is_usable",
            "The result is coherent and artifact-free enough for continued design work.",
        ),
    ),
}


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_object_sha256(value: object) -> str:
    """Return the SHA-256 of Facetta's canonical JSON representation."""

    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def canonical_review_ledger_payload(ledger: Json) -> bytes:
    """Return the bytes covered by a v2 review-ledger signature."""

    unsigned = {key: value for key, value in ledger.items() if key != "signature"}
    return _canonical_bytes(unsigned)


def blind_review_packet_sha256(packet: Json) -> str:
    """Hash the complete reviewer-visible packet for ledger binding."""

    return canonical_object_sha256(packet)


def criterion_template(reviewer_role: str, kind: str, operation_class: str) -> list[Json]:
    """Return a defensive copy of the rubric for one role and operation."""

    key = (reviewer_role, kind, operation_class)
    template = _CRITERION_TEMPLATES.get(key)
    if template is None:
        raise ValueError(
            "unsupported blind-review rubric: " + ":".join(key)
        )
    return deepcopy(list(template))


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _HEX_LENGTH
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def _artifact(value: object, *, label: str, required: bool = True) -> Json | None:
    if value is None and not required:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an artifact object")
    if set(value) != {"path", "sha256"}:
        raise ValueError(f"{label} must contain only path and sha256")
    path = value.get("path")
    if (
        not isinstance(path, str)
        or not path
        or path.startswith("/")
        or ".." in path.split("/")
    ):
        raise ValueError(f"{label} path must be evidence-root relative")
    if not _is_sha256(value.get("sha256")):
        raise ValueError(f"{label} sha256 is invalid")
    return {"path": path, "sha256": value["sha256"]}


def _canonical_intent(value: object, *, kind: str) -> Json:
    if not isinstance(value, dict):
        raise ValueError("review intent must be an object")
    if set(value) != {"intended_change", "target_region", "frozen_facts"}:
        raise ValueError(
            "review intent must contain intended_change, target_region, and frozen_facts"
        )
    intended_change = value.get("intended_change")
    target_region = value.get("target_region")
    frozen_facts = value.get("frozen_facts")
    if not isinstance(intended_change, str) or not intended_change.strip():
        raise ValueError("review intended_change is empty")
    if target_region is not None and (
        not isinstance(target_region, str) or not target_region.strip()
    ):
        raise ValueError("review target_region must be null or non-empty text")
    if kind == "render" and target_region is not None:
        raise ValueError("render review cannot declare a target region")
    if not isinstance(frozen_facts, list) or not frozen_facts or not all(
        isinstance(fact, str) and fact.strip() for fact in frozen_facts
    ):
        raise ValueError("review frozen_facts must be non-empty text values")
    if len(set(frozen_facts)) != len(frozen_facts):
        raise ValueError("review frozen_facts contain duplicates")
    return {
        "intended_change": intended_change.strip(),
        "target_region": target_region.strip() if isinstance(target_region, str) else None,
        "frozen_facts": [fact.strip() for fact in frozen_facts],
    }


def _opaque_item_id(
    reviewer_role: str,
    kind: str,
    operation_class: str,
    intent: Json,
    source: Json,
    candidate: Json,
    mask: Json | None,
) -> str:
    binding = {
        "domain": "facetta-blind-jewelry-review-item.v2",
        "reviewer_role": reviewer_role,
        "kind": kind,
        "operation_class": operation_class,
        "intent": intent,
        "source_sha256": source["sha256"],
        "candidate_sha256": candidate["sha256"],
        "mask_sha256": mask["sha256"] if mask is not None else None,
    }
    return "item_" + canonical_object_sha256(binding)[:32]


def _forbidden_key_paths(value: object, prefix: str = "$") -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).lower()
            if normalized in _FORBIDDEN_REVIEWER_KEYS or any(
                normalized.startswith(term + "_") or normalized.endswith("_" + term)
                for term in _FORBIDDEN_REVIEWER_KEYS
            ):
                paths.append(f"{prefix}.{key}")
            paths.extend(_forbidden_key_paths(nested, f"{prefix}.{key}"))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            paths.extend(_forbidden_key_paths(nested, f"{prefix}[{index}]"))
    return paths


def build_blind_review_packet(
    *,
    corpus_run_id: str,
    manifest_sha256: str,
    config_sha256: str,
    workload_sha256: str,
    capture_sha256: str,
    reviewer_role: str,
    review_seed: str,
    selected_items: list[Json],
) -> Json:
    """Build a reviewer-visible v2 packet from already selected artifacts.

    ``selected_items`` is an internal integration input, not the packet schema.
    Each row must contain ``kind``, ``operation_class``, ``intent``, ``source``,
    ``candidate``, and ``mask``.  Machine evidence must select the candidate
    before invoking this function.
    """

    if not isinstance(corpus_run_id, str) or not corpus_run_id.strip():
        raise ValueError("corpus_run_id is empty")
    bindings = {
        "manifest_sha256": manifest_sha256,
        "config_sha256": config_sha256,
        "workload_sha256": workload_sha256,
        "capture_sha256": capture_sha256,
    }
    for label, digest in bindings.items():
        if not _is_sha256(digest):
            raise ValueError(f"{label} is invalid")
    if reviewer_role not in {GIA_VISUAL_FIDELITY_ROLE, INDEPENDENT_DESIGNER_ROLE}:
        raise ValueError("reviewer_role is unsupported")
    if not _is_sha256(review_seed):
        raise ValueError("review_seed must be 64 lowercase hexadecimal characters")
    if not isinstance(selected_items, list) or not selected_items:
        raise ValueError("selected_items must be a non-empty list")

    items: list[Json] = []
    for index, raw in enumerate(selected_items, 1):
        if not isinstance(raw, dict):
            raise ValueError(f"selected item {index} must be an object")
        if set(raw) != {
            "kind", "operation_class", "intent", "source", "candidate", "mask",
        }:
            raise ValueError(f"selected item {index} has unexpected fields")
        kind = raw.get("kind")
        operation_class = raw.get("operation_class")
        if kind not in {"render", "edit"}:
            raise ValueError(f"selected item {index} kind is unsupported")
        if not isinstance(operation_class, str) or not operation_class:
            raise ValueError(f"selected item {index} operation_class is empty")
        if kind == "render" and operation_class != "render_conformance":
            raise ValueError("render item must use render_conformance")
        if kind == "edit" and operation_class not in {"quick_appearance", "structural"}:
            raise ValueError("edit item operation_class is unsupported")
        intent = _canonical_intent(raw.get("intent"), kind=kind)
        source = _artifact(raw.get("source"), label=f"selected item {index} source")
        candidate = _artifact(
            raw.get("candidate"), label=f"selected item {index} candidate",
        )
        mask = _artifact(
            raw.get("mask"),
            label=f"selected item {index} mask",
            required=kind == "edit",
        )
        if kind == "render" and mask is not None:
            raise ValueError("render review item cannot contain a mask")
        assert source is not None and candidate is not None
        criteria = criterion_template(reviewer_role, kind, operation_class)
        item_id = _opaque_item_id(
            reviewer_role, kind, operation_class, intent, source, candidate, mask,
        )
        items.append({
            "item_id": item_id,
            "kind": kind,
            "operation_class": operation_class,
            "intent": intent,
            "artifacts": {
                "source": source,
                "candidate": candidate,
                "mask": mask,
            },
            "criteria": criteria,
        })

    item_ids = [item["item_id"] for item in items]
    if len(set(item_ids)) != len(item_ids):
        raise ValueError("selected_items contain duplicate blind-review identities")
    seed_bytes = bytes.fromhex(review_seed)
    items.sort(key=lambda item: (
        hmac.new(seed_bytes, item["item_id"].encode("utf-8"), hashlib.sha256).digest(),
        item["item_id"],
    ))
    ordered_ids = [item["item_id"] for item in items]
    packet = {
        "schema_version": BLIND_REVIEW_PACKET_SCHEMA,
        "corpus_run_id": corpus_run_id.strip(),
        "evidence_binding": bindings,
        "review_protocol": {
            "criteria_schema_version": BLIND_REVIEW_CRITERIA_SCHEMA,
            "reviewer_role": reviewer_role,
            "order_algorithm": "HMAC-SHA256(review_seed,item_id)",
            "review_seed": review_seed,
            "review_seed_sha256": hashlib.sha256(seed_bytes).hexdigest(),
            "ordered_item_ids_sha256": canonical_object_sha256(ordered_ids),
        },
        "items": items,
        "review_status": "awaiting_signed_criterion_review",
    }
    errors = validate_blind_review_packet(packet)["errors"]
    if errors:
        raise ValueError("invalid blind-review packet: " + "; ".join(errors))
    return packet


def validate_blind_review_packet(packet: object) -> Json:
    """Validate v2 packet structure, opacity, rubric, hashes, and order."""

    errors: list[str] = []
    if not isinstance(packet, dict):
        return {"status": "fail", "errors": ["packet must be an object"]}
    expected_top = {
        "schema_version",
        "corpus_run_id",
        "evidence_binding",
        "review_protocol",
        "items",
        "review_status",
    }
    if set(packet) != expected_top:
        errors.append("packet has unexpected or missing top-level fields")
    if packet.get("schema_version") != BLIND_REVIEW_PACKET_SCHEMA:
        errors.append("unsupported blind-review packet schema_version")
    forbidden = _forbidden_key_paths(packet)
    if forbidden:
        errors.append("reviewer packet contains forbidden machine fields: " + ", ".join(forbidden))
    corpus_run_id = packet.get("corpus_run_id")
    if not isinstance(corpus_run_id, str) or not corpus_run_id.strip():
        errors.append("corpus_run_id is empty")
    binding = packet.get("evidence_binding")
    if not isinstance(binding, dict) or set(binding) != {
        "manifest_sha256", "config_sha256", "workload_sha256", "capture_sha256",
    }:
        errors.append("evidence_binding is incomplete")
    elif not all(_is_sha256(value) for value in binding.values()):
        errors.append("evidence_binding contains an invalid sha256")
    protocol = packet.get("review_protocol")
    if not isinstance(protocol, dict) or set(protocol) != {
        "criteria_schema_version",
        "reviewer_role",
        "order_algorithm",
        "review_seed",
        "review_seed_sha256",
        "ordered_item_ids_sha256",
    }:
        errors.append("review_protocol is incomplete")
        protocol = {}
    if protocol.get("criteria_schema_version") != BLIND_REVIEW_CRITERIA_SCHEMA:
        errors.append("review criteria schema_version is unsupported")
    role = protocol.get("reviewer_role")
    if role not in {GIA_VISUAL_FIDELITY_ROLE, INDEPENDENT_DESIGNER_ROLE}:
        errors.append("reviewer_role is unsupported")
    if protocol.get("order_algorithm") != "HMAC-SHA256(review_seed,item_id)":
        errors.append("review order algorithm is unsupported")
    seed = protocol.get("review_seed")
    if not _is_sha256(seed):
        errors.append("review_seed is invalid")
        seed_bytes = None
    else:
        seed_bytes = bytes.fromhex(seed)
        if protocol.get("review_seed_sha256") != hashlib.sha256(seed_bytes).hexdigest():
            errors.append("review_seed_sha256 differs")
    items = packet.get("items")
    if not isinstance(items, list) or not items:
        errors.append("review packet items must be a non-empty list")
        items = []
    item_ids: list[str] = []
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict) or set(item) != {
            "item_id", "kind", "operation_class", "intent", "artifacts", "criteria",
        }:
            errors.append(f"review item {index} has unexpected or missing fields")
            continue
        item_id = item.get("item_id")
        if (
            not isinstance(item_id, str)
            or not item_id.startswith("item_")
            or len(item_id) != 37
            or not all(char in "0123456789abcdef" for char in item_id[5:])
        ):
            errors.append(f"review item {index} item_id is not opaque v2 form")
            continue
        item_ids.append(item_id)
        kind = item.get("kind")
        operation_class = item.get("operation_class")
        try:
            intent = _canonical_intent(item.get("intent"), kind=str(kind))
            artifacts = item.get("artifacts")
            if not isinstance(artifacts, dict) or set(artifacts) != {
                "source", "candidate", "mask",
            }:
                raise ValueError("artifacts must contain source, candidate, and mask")
            source = _artifact(artifacts.get("source"), label="source")
            candidate = _artifact(artifacts.get("candidate"), label="candidate")
            mask = _artifact(
                artifacts.get("mask"), label="mask", required=kind == "edit",
            )
            if kind == "render" and mask is not None:
                raise ValueError("render review item cannot contain a mask")
            assert source is not None and candidate is not None
            if role in {GIA_VISUAL_FIDELITY_ROLE, INDEPENDENT_DESIGNER_ROLE}:
                template = criterion_template(str(role), str(kind), str(operation_class))
                if item.get("criteria") != template:
                    errors.append(f"review item {index} criteria differ from the role rubric")
                expected_id = _opaque_item_id(
                    str(role), str(kind), str(operation_class), intent,
                    source, candidate, mask,
                )
                if item_id != expected_id:
                    errors.append(f"review item {index} opaque item_id binding differs")
        except ValueError as exc:
            errors.append(f"review item {index}: {exc}")
    if len(set(item_ids)) != len(item_ids):
        errors.append("review packet contains duplicate item IDs")
    if protocol.get("ordered_item_ids_sha256") != canonical_object_sha256(item_ids):
        errors.append("ordered_item_ids_sha256 differs")
    if seed_bytes is not None and item_ids:
        expected_order = sorted(
            item_ids,
            key=lambda item_id: (
                hmac.new(seed_bytes, item_id.encode("utf-8"), hashlib.sha256).digest(),
                item_id,
            ),
        )
        if item_ids != expected_order:
            errors.append("review item order differs from the bound seed")
    if packet.get("review_status") != "awaiting_signed_criterion_review":
        errors.append("review_status is not awaiting signed criterion review")
    return {
        "schema_version": "facetta-blind-jewelry-review-packet-validation.v2",
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "item_count": len(items),
        "packet_sha256": blind_review_packet_sha256(packet),
    }


def _timezone_binding_error(reviewed_at: object, review_timezone: object) -> str | None:
    if not isinstance(reviewed_at, str) or not reviewed_at:
        return "reviewed_at is empty"
    if not isinstance(review_timezone, str) or not review_timezone:
        return "review_timezone is empty"
    try:
        instant = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
    except ValueError:
        return "reviewed_at is not ISO-8601"
    if instant.tzinfo is None or instant.utcoffset() is None:
        return "reviewed_at must include a UTC offset"
    try:
        zone = ZoneInfo(review_timezone)
    except ZoneInfoNotFoundError:
        return "review_timezone is not an IANA timezone"
    if instant.utcoffset() != instant.astimezone(zone).utcoffset():
        return "reviewed_at offset differs from review_timezone"
    return None


def validate_signed_review_ledger(
    packet: Json,
    ledger: object,
    *,
    reviewer_public_key: Ed25519PublicKey,
    reviewer_key_id: str,
    expected_reviewer_profile_sha256: str,
) -> Json:
    """Verify a signed ledger and derive criterion-level item acceptance."""

    errors: list[str] = []
    packet_validation = validate_blind_review_packet(packet)
    if packet_validation["status"] != "pass":
        errors.extend("packet: " + error for error in packet_validation["errors"])
    if not isinstance(ledger, dict):
        return {
            "schema_version": "facetta-blind-jewelry-review-ledger-validation.v2",
            "status": "fail",
            "errors": errors + ["ledger must be an object"],
            "signature_status": "not_verified",
            "decisions": [],
            "accepted_count": 0,
            "accepted_rate": 0.0,
        }
    expected_top = {
        "schema_version",
        "blind_packet_sha256",
        "reviewer_id",
        "reviewer_role",
        "reviewer_profile_sha256",
        "review_timezone",
        "reviewed_at",
        "decisions",
        "signature",
    }
    if set(ledger) != expected_top:
        errors.append("ledger has unexpected or missing top-level fields")
    if ledger.get("schema_version") != BLIND_REVIEW_LEDGER_SCHEMA:
        errors.append("unsupported blind-review ledger schema_version")
    if ledger.get("blind_packet_sha256") != blind_review_packet_sha256(packet):
        errors.append("blind_packet_sha256 differs")
    reviewer_id = ledger.get("reviewer_id")
    if not isinstance(reviewer_id, str) or not reviewer_id.strip():
        errors.append("reviewer_id is empty")
    role = packet.get("review_protocol", {}).get("reviewer_role")
    if ledger.get("reviewer_role") != role:
        errors.append("reviewer_role differs from the packet")
    if not _is_sha256(expected_reviewer_profile_sha256):
        errors.append("expected reviewer profile sha256 is invalid")
    if ledger.get("reviewer_profile_sha256") != expected_reviewer_profile_sha256:
        errors.append("reviewer_profile_sha256 differs")
    timezone_error = _timezone_binding_error(
        ledger.get("reviewed_at"), ledger.get("review_timezone"),
    )
    if timezone_error:
        errors.append(timezone_error)

    signature_status = "not_verified"
    signature = ledger.get("signature")
    if not isinstance(signature, dict):
        errors.append("ledger is unsigned")
    elif set(signature) != {"algorithm", "key_id", "value"}:
        errors.append("ledger signature is incomplete")
    elif signature.get("algorithm") != "Ed25519":
        errors.append("ledger signature algorithm is unsupported")
    elif signature.get("key_id") != reviewer_key_id:
        errors.append("ledger signature key_id differs")
    else:
        try:
            encoded = signature.get("value")
            if not isinstance(encoded, str):
                raise ValueError("signature value is not text")
            reviewer_public_key.verify(
                base64.b64decode(encoded, validate=True),
                canonical_review_ledger_payload(ledger),
            )
            signature_status = "verified"
        except (InvalidSignature, ValueError, TypeError):
            errors.append("ledger signature is invalid")

    packet_items = {
        item["item_id"]: item
        for item in packet.get("items", [])
        if isinstance(item, dict) and isinstance(item.get("item_id"), str)
    }
    decisions = ledger.get("decisions")
    if not isinstance(decisions, list):
        errors.append("ledger decisions must be a list")
        decisions = []
    seen: set[str] = set()
    derived: list[Json] = []
    for index, decision in enumerate(decisions, 1):
        decision_errors: list[str] = []
        if not isinstance(decision, dict) or set(decision) != {
            "item_id",
            "selected_source_sha256",
            "selected_candidate_sha256",
            "selected_mask_sha256",
            "criteria",
        }:
            decision_errors.append("decision has unexpected or missing fields")
            decision = decision if isinstance(decision, dict) else {}
        item_id = decision.get("item_id")
        item = packet_items.get(item_id) if isinstance(item_id, str) else None
        if item is None:
            decision_errors.append("item_id is not in the packet")
        elif item_id in seen:
            decision_errors.append("item_id is duplicated")
        else:
            seen.add(item_id)
        if item is not None:
            artifacts = item["artifacts"]
            expected_hashes = {
                "selected_source_sha256": artifacts["source"]["sha256"],
                "selected_candidate_sha256": artifacts["candidate"]["sha256"],
                "selected_mask_sha256": (
                    artifacts["mask"]["sha256"]
                    if artifacts["mask"] is not None else None
                ),
            }
            for field, expected in expected_hashes.items():
                if decision.get(field) != expected:
                    decision_errors.append(f"{field} differs from the packet")

            submitted = decision.get("criteria")
            if not isinstance(submitted, list):
                decision_errors.append("criteria must be a list")
                submitted = []
            submitted_by_id: dict[str, Json] = {}
            for criterion_index, response in enumerate(submitted, 1):
                if not isinstance(response, dict) or set(response) != {
                    "criterion_id", "rating", "rationale",
                }:
                    decision_errors.append(
                        f"criterion {criterion_index} has unexpected or missing fields"
                    )
                    continue
                criterion_id = response.get("criterion_id")
                if not isinstance(criterion_id, str) or criterion_id in submitted_by_id:
                    decision_errors.append(
                        f"criterion {criterion_index} ID is empty or duplicated"
                    )
                    continue
                submitted_by_id[criterion_id] = response
            expected_criteria = {
                criterion["criterion_id"]: criterion for criterion in item["criteria"]
            }
            if set(submitted_by_id) != set(expected_criteria):
                decision_errors.append("criterion IDs differ from the packet rubric")
            criterion_outcomes: list[Json] = []
            for criterion_id, rubric in expected_criteria.items():
                response = submitted_by_id.get(criterion_id, {})
                rating = response.get("rating")
                rationale = response.get("rationale")
                if rating not in REVIEW_RATINGS:
                    decision_errors.append(f"{criterion_id} rating is unsupported")
                if rating != PASS_RATING and (
                    not isinstance(rationale, str) or len(rationale.strip()) < 8
                ):
                    decision_errors.append(
                        f"{criterion_id} requires a rationale for a non-pass rating"
                    )
                if rating == NOT_APPLICABLE_RATING and not rubric[
                    "not_applicable_allowed"
                ]:
                    decision_errors.append(f"{criterion_id} cannot be not_applicable")
                criterion_outcomes.append({
                    "criterion_id": criterion_id,
                    "rating": rating,
                    "required_for_acceptance": rubric["required_for_acceptance"],
                })
        else:
            criterion_outcomes = []
        derived_accepted = not decision_errors and all(
            outcome["rating"] == PASS_RATING
            for outcome in criterion_outcomes
            if outcome["required_for_acceptance"]
        )
        errors.extend(
            f"decision {index}: {error}" for error in decision_errors
        )
        derived.append({
            "item_id": item_id,
            "derived_accepted": derived_accepted,
            "criterion_outcomes": criterion_outcomes,
            "errors": decision_errors,
        })
    missing = set(packet_items) - seen
    if missing:
        errors.append("ledger is missing packet items: " + ", ".join(sorted(missing)))
    if len(decisions) != len(packet_items):
        errors.append("ledger decision count differs from packet item count")
    if errors:
        # No criterion result is authoritative when packet binding, reviewer
        # identity, timezone, signature, coverage, or ledger shape is invalid.
        # A legitimate signed ``fail``/``not_observable`` rating is not itself
        # an error and therefore still permits valid per-item derivation.
        for row in derived:
            row["derived_accepted"] = False
    accepted_count = sum(bool(row["derived_accepted"]) for row in derived)
    return {
        "schema_version": "facetta-blind-jewelry-review-ledger-validation.v2",
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "signature_status": signature_status,
        "packet_sha256": blind_review_packet_sha256(packet),
        "reviewer_profile_sha256": ledger.get("reviewer_profile_sha256"),
        "review_timezone": ledger.get("review_timezone"),
        "decisions": derived,
        "accepted_count": accepted_count,
        "accepted_rate": accepted_count / len(packet_items) if packet_items else 0.0,
    }


__all__ = [
    "BLIND_REVIEW_CRITERIA_SCHEMA",
    "BLIND_REVIEW_LEDGER_SCHEMA",
    "BLIND_REVIEW_PACKET_SCHEMA",
    "FAIL_RATING",
    "GIA_VISUAL_FIDELITY_ROLE",
    "INDEPENDENT_DESIGNER_ROLE",
    "NOT_APPLICABLE_RATING",
    "NOT_OBSERVABLE_RATING",
    "PASS_RATING",
    "blind_review_packet_sha256",
    "build_blind_review_packet",
    "canonical_object_sha256",
    "canonical_review_ledger_payload",
    "criterion_template",
    "validate_blind_review_packet",
    "validate_signed_review_ledger",
]

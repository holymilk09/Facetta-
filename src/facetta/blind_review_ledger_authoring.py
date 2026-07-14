"""Provider-free authoring for reviewer-safe blind-review ledgers.

The packet and enrolled reviewer configuration are authoritative.  This module
creates a form whose packet, artifact, criterion, role, profile, and key
bindings are immutable; a human reviewer may supply only an opaque reviewer
identifier, local review time, criterion ratings, and rationales.  The result
is signed with an Ed25519 key kept outside both the repository and evidence
root, then verified through the canonical ledger validator before callers may
retain it.
"""

from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    load_pem_private_key,
    load_pem_public_key,
)

from facetta.blind_jewelry_review import (
    BLIND_REVIEW_LEDGER_SCHEMA,
    GIA_VISUAL_FIDELITY_ROLE,
    INDEPENDENT_DESIGNER_ROLE,
    blind_review_packet_sha256,
    canonical_review_ledger_payload,
    validate_blind_review_packet,
    validate_signed_review_ledger,
)


Json = dict[str, Any]

BLIND_REVIEW_AUTHORING_TEMPLATE_SCHEMA = (
    "facetta-blind-jewelry-review-authoring-template.v1"
)

_ROLE_CONFIG_KEYS = {
    GIA_VISUAL_FIDELITY_ROLE: "reviewer_public_key",
    INDEPENDENT_DESIGNER_ROLE: "designer_reviewer_public_key",
}
_OPAQUE_REVIEWER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{6,127}\Z")


@dataclass(frozen=True)
class EnrolledBlindReviewer:
    """Exact public reviewer identity used to bind and verify one ledger."""

    reviewer_role: str
    key_id: str
    reviewer_profile_sha256: str
    public_key: Ed25519PublicKey


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_public_key(path: Path) -> Ed25519PublicKey:
    content = path.read_bytes()
    try:
        if len(content) == 32:
            return Ed25519PublicKey.from_public_bytes(content)
        loaded = load_pem_public_key(content)
    except (TypeError, ValueError) as exc:
        raise ValueError("configured reviewer public key is invalid") from exc
    if not isinstance(loaded, Ed25519PublicKey):
        raise ValueError("configured reviewer public key is not Ed25519")
    return loaded


def load_enrolled_blind_reviewer(
    config: Json,
    *,
    reviewer_role: str,
    repository_root: Path,
) -> EnrolledBlindReviewer:
    """Load one role-specific reviewer enrollment from frozen configuration."""

    config_key = _ROLE_CONFIG_KEYS.get(reviewer_role)
    if config_key is None:
        raise ValueError("reviewer_role is unsupported")
    configured = config.get(config_key)
    if not isinstance(configured, dict) or set(configured) != {
        "key_id", "path", "sha256", "reviewer_profile_sha256",
    }:
        raise ValueError(f"{config_key} is not completely configured")
    key_id = configured.get("key_id")
    relative = configured.get("path")
    expected_sha256 = configured.get("sha256")
    profile_sha256 = configured.get("reviewer_profile_sha256")
    if not isinstance(key_id, str) or not key_id.strip():
        raise ValueError("configured reviewer key_id is empty")
    if not _is_sha256(expected_sha256):
        raise ValueError("configured reviewer public-key sha256 is invalid")
    if not _is_sha256(profile_sha256):
        raise ValueError("configured reviewer profile sha256 is invalid")
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("configured reviewer public-key path is invalid")
    root = repository_root.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("configured reviewer public-key file is unavailable")
    if _file_sha256(path) != expected_sha256:
        raise ValueError("configured reviewer public-key sha256 differs")
    return EnrolledBlindReviewer(
        reviewer_role=reviewer_role,
        key_id=key_id,
        reviewer_profile_sha256=profile_sha256,
        public_key=_load_public_key(path),
    )


def _packet_items(packet: Json) -> list[Json]:
    validation = validate_blind_review_packet(packet)
    if validation["status"] != "pass":
        raise ValueError(
            "invalid blind-review packet: " + "; ".join(validation["errors"])
        )
    items = packet["items"]
    assert isinstance(items, list)
    return items


def _item_binding(item: Json) -> Json:
    artifacts = item["artifacts"]
    return {
        "item_id": item["item_id"],
        "selected_source_sha256": artifacts["source"]["sha256"],
        "selected_candidate_sha256": artifacts["candidate"]["sha256"],
        "selected_mask_sha256": (
            artifacts["mask"]["sha256"]
            if artifacts["mask"] is not None else None
        ),
        "criterion_ids": [criterion["criterion_id"] for criterion in item["criteria"]],
    }


def build_blind_review_authoring_template(
    packet: Json,
    *,
    reviewer: EnrolledBlindReviewer,
) -> Json:
    """Create a human-fillable form with immutable packet-derived bindings."""

    items = _packet_items(packet)
    packet_role = packet["review_protocol"]["reviewer_role"]
    if reviewer.reviewer_role != packet_role:
        raise ValueError("reviewer_role differs from the packet")
    return {
        "schema_version": BLIND_REVIEW_AUTHORING_TEMPLATE_SCHEMA,
        "bindings": {
            "blind_packet_sha256": blind_review_packet_sha256(packet),
            "reviewer_role": reviewer.reviewer_role,
            "reviewer_key_id": reviewer.key_id,
            "reviewer_profile_sha256": reviewer.reviewer_profile_sha256,
            "items": [_item_binding(item) for item in items],
        },
        "review": {
            "reviewer_id": None,
            "review_timezone": None,
            "reviewed_at": None,
            "decisions": [
                {
                    "item_id": item["item_id"],
                    "criteria": [
                        {
                            "criterion_id": criterion["criterion_id"],
                            "rating": None,
                            "rationale": None,
                        }
                        for criterion in item["criteria"]
                    ],
                }
                for item in items
            ],
        },
    }


def _forbidden_accepted_paths(value: object, prefix: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            path = f"{prefix}.{key}"
            if str(key).lower() == "accepted":
                found.append(path)
            found.extend(_forbidden_accepted_paths(nested, path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            found.extend(_forbidden_accepted_paths(nested, f"{prefix}[{index}]"))
    return found


def _require_exact_template_bindings(
    packet: Json,
    template: Json,
    reviewer: EnrolledBlindReviewer,
) -> tuple[list[Json], Json]:
    items = _packet_items(packet)
    if set(template) != {"schema_version", "bindings", "review"}:
        raise ValueError("authoring template has unexpected or missing fields")
    if template.get("schema_version") != BLIND_REVIEW_AUTHORING_TEMPLATE_SCHEMA:
        raise ValueError("authoring template schema_version is unsupported")
    expected_bindings = build_blind_review_authoring_template(
        packet, reviewer=reviewer,
    )["bindings"]
    if template.get("bindings") != expected_bindings:
        raise ValueError("authoring template bindings differ from packet or enrollment")
    review = template.get("review")
    if not isinstance(review, dict) or set(review) != {
        "reviewer_id", "review_timezone", "reviewed_at", "decisions",
    }:
        raise ValueError("review input has unexpected or missing fields")
    forbidden = _forbidden_accepted_paths(review)
    if forbidden:
        raise ValueError(
            "reviewer cannot assert accepted booleans: " + ", ".join(forbidden)
        )
    return items, review


def _human_decisions(items: list[Json], review: Json) -> list[Json]:
    decisions = review.get("decisions")
    if not isinstance(decisions, list) or len(decisions) != len(items):
        raise ValueError("review decision count differs from packet item count")
    ledger_decisions: list[Json] = []
    for index, (item, decision) in enumerate(zip(items, decisions, strict=True), 1):
        if not isinstance(decision, dict) or set(decision) != {"item_id", "criteria"}:
            raise ValueError(f"review decision {index} has unexpected or missing fields")
        if decision.get("item_id") != item["item_id"]:
            raise ValueError(f"review decision {index} item_id differs from the packet")
        responses = decision.get("criteria")
        criteria = item["criteria"]
        if not isinstance(responses, list) or len(responses) != len(criteria):
            raise ValueError(f"review decision {index} criterion count differs")
        human_criteria: list[Json] = []
        for criterion_index, (rubric, response) in enumerate(
            zip(criteria, responses, strict=True), 1
        ):
            if not isinstance(response, dict) or set(response) != {
                "criterion_id", "rating", "rationale",
            }:
                raise ValueError(
                    f"review decision {index} criterion {criterion_index} "
                    "has unexpected or missing fields"
                )
            if response.get("criterion_id") != rubric["criterion_id"]:
                raise ValueError(
                    f"review decision {index} criterion IDs differ from packet rubric"
                )
            human_criteria.append({
                "criterion_id": rubric["criterion_id"],
                "rating": response.get("rating"),
                "rationale": response.get("rationale"),
            })
        artifacts = item["artifacts"]
        ledger_decisions.append({
            "item_id": item["item_id"],
            "selected_source_sha256": artifacts["source"]["sha256"],
            "selected_candidate_sha256": artifacts["candidate"]["sha256"],
            "selected_mask_sha256": (
                artifacts["mask"]["sha256"]
                if artifacts["mask"] is not None else None
            ),
            "criteria": human_criteria,
        })
    return ledger_decisions


def _load_private_key(
    path: Path,
    *,
    repository_root: Path,
    evidence_root: Path,
) -> Ed25519PrivateKey:
    resolved = path.resolve()
    if not resolved.is_file():
        raise ValueError("private reviewer signing key is unavailable")
    if resolved.is_relative_to(repository_root.resolve()) or resolved.is_relative_to(
        evidence_root.resolve()
    ):
        raise ValueError(
            "private reviewer signing key must remain outside the repository and evidence root"
        )
    if resolved.stat().st_mode & 0o077:
        raise ValueError(
            "private reviewer signing key must not be group- or world-accessible"
        )
    content = resolved.read_bytes()
    try:
        if len(content) == 32:
            return Ed25519PrivateKey.from_private_bytes(content)
        loaded = load_pem_private_key(content, password=None)
    except (TypeError, ValueError) as exc:
        raise ValueError("private reviewer signing key is invalid") from exc
    if not isinstance(loaded, Ed25519PrivateKey):
        raise ValueError("private reviewer signing key is not Ed25519")
    return loaded


def author_signed_blind_review_ledger(
    packet: Json,
    completed_template: Json,
    *,
    reviewer: EnrolledBlindReviewer,
    private_key_path: Path,
    repository_root: Path,
    evidence_root: Path,
) -> tuple[Json, Json]:
    """Build, sign, and immediately self-verify an exact blind-review ledger."""

    items, review = _require_exact_template_bindings(
        packet, completed_template, reviewer,
    )
    reviewer_id = review.get("reviewer_id")
    if not isinstance(reviewer_id, str) or not _OPAQUE_REVIEWER_ID.fullmatch(
        reviewer_id
    ):
        raise ValueError("reviewer_id must be an opaque 7-128 character identifier")
    ledger: Json = {
        "schema_version": BLIND_REVIEW_LEDGER_SCHEMA,
        "blind_packet_sha256": blind_review_packet_sha256(packet),
        "reviewer_id": reviewer_id,
        "reviewer_role": reviewer.reviewer_role,
        "reviewer_profile_sha256": reviewer.reviewer_profile_sha256,
        "review_timezone": review.get("review_timezone"),
        "reviewed_at": review.get("reviewed_at"),
        "decisions": _human_decisions(items, review),
        "signature": None,
    }
    private_key = _load_private_key(
        private_key_path,
        repository_root=repository_root,
        evidence_root=evidence_root,
    )
    enrolled_bytes = reviewer.public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
    signer_bytes = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    if signer_bytes != enrolled_bytes:
        raise ValueError("private reviewer signing key differs from configured enrollment")
    ledger["signature"] = {
        "algorithm": "Ed25519",
        "key_id": reviewer.key_id,
        "value": base64.b64encode(
            private_key.sign(canonical_review_ledger_payload(ledger))
        ).decode("ascii"),
    }
    validation = validate_signed_review_ledger(
        packet,
        ledger,
        reviewer_public_key=reviewer.public_key,
        reviewer_key_id=reviewer.key_id,
        expected_reviewer_profile_sha256=reviewer.reviewer_profile_sha256,
    )
    if validation["status"] != "pass" or validation["signature_status"] != "verified":
        raise ValueError(
            "signed blind-review ledger failed self-verification: "
            + "; ".join(validation["errors"])
        )
    return ledger, validation


__all__ = [
    "BLIND_REVIEW_AUTHORING_TEMPLATE_SCHEMA",
    "EnrolledBlindReviewer",
    "author_signed_blind_review_ledger",
    "build_blind_review_authoring_template",
    "load_enrolled_blind_reviewer",
]

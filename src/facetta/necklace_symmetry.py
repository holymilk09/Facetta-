"""Deterministic review of structured necklace-symmetry evidence.

Pixels still require a vision inspector.  This module does not pretend to
measure symmetry from an image.  It verifies that the inspector actually
inventoried every corresponding element from the centerline outward and that
its structured evidence is internally consistent with the designer's stated
symmetry intent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from facetta.creative_symmetry import (
    JEWELRY_SYMMETRY_CONTRACT,
    JEWELRY_SYMMETRY_REPAIR_CONTRACT,
)
if TYPE_CHECKING:
    from facetta.image_agent.contracts import (
        NecklaceSymmetryAudit,
        NecklaceSymmetryPairAudit,
    )


ObservedJewelryType = Literal[
    "ring", "necklace", "earrings", "bracelet", "brooch", "other", "unclear"
]


_NECKLACE_CUE = re.compile(
    r"\b(?:necklace|pendant|choker|collar|lariat|torque|neckpiece)\b",
    flags=re.IGNORECASE,
)
_EXPLICIT_ASYMMETRY_CUE = re.compile(
    r"\b(?:intentional(?:ly)?|deliberate(?:ly)?|purposeful(?:ly)?|"
    r"designer[- ]requested|preserve|retain|keep|asymmetric|asymmetrical)"
    r"(?:\s+\w+){0,5}\s+asymmetr(?:y|ic|ical|ically)\b|"
    r"\basymmetr(?:ic|ical)\b",
    flags=re.IGNORECASE,
)
_NEGATED_ASYMMETRY_CUE = re.compile(
    r"\b(?:not|non|no|avoid|without)\s+(?:an?\s+)?"
    r"asymmetr(?:y|ic|ical|ically)\b",
    flags=re.IGNORECASE,
)

_PAIR_FIELDS: tuple[tuple[str, str], ...] = (
    ("motif_order", "motif_order_matches"),
    ("orientation", "orientation_matches"),
    ("spacing", "spacing_matches"),
    ("scale", "scale_matches"),
    ("metal_treatment", "metal_treatment_matches"),
    ("pave_coverage", "pave_coverage_matches"),
    ("gemstone_treatment", "gemstone_treatment_matches"),
    ("connection_type", "connection_type_matches"),
)


@dataclass(frozen=True)
class NecklaceSymmetryGateResult:
    applicable: bool
    passed: bool
    reasons: tuple[str, ...]
    audit_count: int


def _designer_instruction(intent: str) -> str:
    return (
        intent.replace(JEWELRY_SYMMETRY_REPAIR_CONTRACT, "")
        .replace(JEWELRY_SYMMETRY_CONTRACT, "")
        .strip()
    )


def requires_necklace_symmetry_audit(
    intent: str,
    *,
    observed_jewelry_type: ObservedJewelryType | None = None,
) -> bool:
    """Whether text or visual inspection identifies a necklace-family piece."""

    return (
        observed_jewelry_type == "necklace"
        or _NECKLACE_CUE.search(_designer_instruction(intent)) is not None
    )


def explicitly_requests_necklace_asymmetry(intent: str) -> bool:
    """Recognize only asymmetry stated outside Facetta's appended contract."""

    designer_instruction = _designer_instruction(intent)
    if _NEGATED_ASYMMETRY_CUE.search(designer_instruction) is not None:
        return False
    return _EXPLICIT_ASYMMETRY_CUE.search(designer_instruction) is not None


def _validate_pair(
    pair: NecklaceSymmetryPairAudit,
    *,
    expectation: str,
) -> tuple[list[str], bool]:
    reasons: list[str] = []
    designed_difference = False
    authorized = set(pair.authorized_differences)
    for dimension, field in _PAIR_FIELDS:
        matches = getattr(pair, field)
        if matches is None:
            reasons.append(
                f"pair {pair.position_from_center} did not assess {dimension}"
            )
            continue
        if matches:
            if dimension in authorized:
                reasons.append(
                    f"pair {pair.position_from_center} marks matching "
                    f"{dimension} as an authorized difference"
                )
            continue
        designed_difference = True
        if expectation == "bilateral":
            reasons.append(
                f"pair {pair.position_from_center} has mismatched {dimension}"
            )
        elif dimension not in authorized:
            reasons.append(
                f"pair {pair.position_from_center} has unauthorized "
                f"{dimension} mismatch"
            )
    return reasons, designed_difference


def _validate_audit(
    audit: NecklaceSymmetryAudit,
    *,
    explicit_asymmetry: bool,
    source_present: bool,
) -> list[str]:
    reasons: list[str] = []
    if audit.complete_piece_assessable is not True:
        reasons.append("complete necklace was not assessable")
    if audit.unrequested_differences_absent is not True:
        reasons.append("absence of unrequested differences was not established")

    expected_positions = tuple(range(1, len(audit.pair_audits) + 1))
    observed_positions = tuple(
        pair.position_from_center for pair in audit.pair_audits
    )
    if observed_positions != expected_positions:
        reasons.append("pair audits are not a complete center-outward sequence")

    if audit.expectation == "bilateral":
        if explicit_asymmetry:
            reasons.append("bilateral output erased explicit designer asymmetry")
        if audit.left_count != audit.right_count:
            reasons.append("left and right necklace counts differ")
        if len(audit.pair_audits) != audit.left_count:
            reasons.append("pair-audit count does not cover both strand inventories")
        if audit.unpaired_left or audit.unpaired_right:
            reasons.append("bilateral necklace contains unpaired strand elements")
        if audit.unpaired_elements_authorized is True:
            reasons.append("bilateral audit cannot authorize unpaired elements")
    elif audit.expectation == "explicit_asymmetry":
        if not explicit_asymmetry:
            reasons.append("audit claims asymmetry not requested by the designer")
        if audit.requested_asymmetry_preserved is not True:
            reasons.append("requested asymmetry was not visibly preserved")
    elif audit.expectation == "source_asymmetry":
        if not source_present:
            reasons.append("source-authoritative asymmetry has no identity source")
        if audit.requested_asymmetry_preserved is not True:
            reasons.append("source asymmetry was not visibly preserved")

    designed_difference = bool(
        audit.left_count != audit.right_count
        or audit.unpaired_left
        or audit.unpaired_right
    )
    for pair in audit.pair_audits:
        pair_reasons, pair_difference = _validate_pair(
            pair,
            expectation=audit.expectation,
        )
        reasons.extend(pair_reasons)
        designed_difference = designed_difference or pair_difference

    has_unpaired = bool(audit.unpaired_left or audit.unpaired_right)
    if has_unpaired and audit.expectation != "bilateral":
        if audit.unpaired_elements_authorized is not True:
            reasons.append("unpaired asymmetric elements were not authorized")
    if audit.expectation != "bilateral" and not designed_difference:
        reasons.append("claimed asymmetry contains no documented difference")
    return reasons


def evaluate_necklace_symmetry_audits(
    intent: str,
    audits: tuple[NecklaceSymmetryAudit, ...],
    *,
    source_present: bool,
    observed_jewelry_type: ObservedJewelryType | None = None,
) -> NecklaceSymmetryGateResult:
    """Fail closed when a necklace audit is missing or internally incomplete."""

    if not requires_necklace_symmetry_audit(
        intent,
        observed_jewelry_type=observed_jewelry_type,
    ):
        return NecklaceSymmetryGateResult(False, True, (), len(audits))
    if not audits:
        return NecklaceSymmetryGateResult(
            True,
            False,
            ("structured center-outward necklace audit is missing",),
            0,
        )
    explicit_asymmetry = explicitly_requests_necklace_asymmetry(intent)
    reasons: list[str] = []
    for index, audit in enumerate(audits, start=1):
        reasons.extend(
            f"audit {index}: {reason}"
            for reason in _validate_audit(
                audit,
                explicit_asymmetry=explicit_asymmetry,
                source_present=source_present,
            )
        )
    return NecklaceSymmetryGateResult(
        True,
        not reasons,
        tuple(reasons),
        len(audits),
    )

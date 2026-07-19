"""Deterministic validation for the six-leaf ruby material pattern."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from facetta.creative_symmetry import SIX_LEAF_RUBY_PATTERN_CONTRACT

if TYPE_CHECKING:
    from facetta.image_agent.contracts import (
        NecklaceSymmetryAudit,
        SixLeafRubyPatternAudit,
    )


@dataclass(frozen=True)
class SixLeafRubyPatternGateResult:
    applicable: bool
    passed: bool
    reasons: tuple[str, ...]
    audit_count: int


def _names_leaf_ruby_motif(component: str) -> bool:
    lowered = component.casefold()
    return "ruby" in lowered and any(
        cue in lowered for cue in ("leaf", "leaves", "floral", "flower")
    )


def _audit_key(audit: SixLeafRubyPatternAudit) -> str:
    return f"{audit.side} motif {audit.position_from_center}"


def _validate_motif(audit: SixLeafRubyPatternAudit) -> list[str]:
    key = _audit_key(audit)
    reasons: list[str] = []
    if audit.complete_motif_assessable is not True:
        reasons.append(f"{key} was not completely assessable")
    if audit.leaf_count != 6:
        reasons.append(f"{key} has {audit.leaf_count} leaves instead of 6")
    if audit.diamond_leaf_count != 3:
        reasons.append(
            f"{key} has {audit.diamond_leaf_count} diamond leaves instead of 3"
        )
    if audit.tsavorite_leaf_count != 3:
        reasons.append(
            f"{key} has {audit.tsavorite_leaf_count} tsavorite leaves instead of 3"
        )
    if audit.whole_leaf_treatments is not True:
        reasons.append(f"{key} does not establish one material per whole leaf")
    sequence = audit.material_sequence
    if len(sequence) != 6:
        reasons.append(f"{key} material sequence does not inventory all 6 leaves")
    elif "other" in sequence:
        reasons.append(f"{key} contains a leaf outside diamond and tsavorite")
    elif any(
        sequence[index] == sequence[(index + 1) % len(sequence)]
        for index in range(len(sequence))
    ):
        reasons.append(f"{key} material sequence is not cyclically alternating")
    return reasons


def evaluate_six_leaf_ruby_pattern_audits(
    intent: str,
    audits: tuple[SixLeafRubyPatternAudit, ...],
    *,
    necklace_audits: tuple[NecklaceSymmetryAudit, ...] = (),
) -> SixLeafRubyPatternGateResult:
    """Fail closed on incomplete motifs, bad alternation, or phase mismatch."""

    if SIX_LEAF_RUBY_PATTERN_CONTRACT not in intent:
        return SixLeafRubyPatternGateResult(False, True, (), len(audits))
    if not audits:
        return SixLeafRubyPatternGateResult(
            True,
            False,
            ("structured six-leaf ruby motif audit is missing",),
            0,
        )

    reasons: list[str] = []
    by_location: dict[tuple[str, int], SixLeafRubyPatternAudit] = {}
    for audit in audits:
        location = (audit.side, audit.position_from_center)
        if location in by_location:
            reasons.append(f"duplicate {_audit_key(audit)} audit")
            continue
        by_location[location] = audit
        reasons.extend(_validate_motif(audit))

    required_pair_positions = {
        pair.position_from_center
        for necklace in necklace_audits
        for pair in necklace.pair_audits
        if (
            _names_leaf_ruby_motif(pair.left_component)
            or _names_leaf_ruby_motif(pair.right_component)
        )
    }
    observed_pair_positions = {
        position
        for side, position in by_location
        if side in {"left", "right"}
    }
    for position in sorted(required_pair_positions | observed_pair_positions):
        left = by_location.get(("left", position))
        right = by_location.get(("right", position))
        if left is None or right is None:
            reasons.append(
                f"ruby motif pair {position} is missing a left or right audit"
            )
            continue
        if left.material_sequence != right.material_sequence:
            reasons.append(
                f"ruby motif pair {position} does not share the same mirrored material phase"
            )

    return SixLeafRubyPatternGateResult(
        True,
        not reasons,
        tuple(reasons),
        len(audits),
    )

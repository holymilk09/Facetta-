"""Default symmetry contract for designer-facing jewelry concepts.

This contract is intentionally visual and pre-spec. It prevents a provider
from treating a left/right mismatch as harmless creative variation while still
allowing a designer's words or identity source to authorize asymmetry.
"""

from __future__ import annotations

import re


JEWELRY_SYMMETRY_CONTRACT = (
    "JEWELRY SYMMETRY CONTRACT: Unless the designer's words or identity "
    "source explicitly request or visibly establish asymmetry, treat "
    "intentional jewelry symmetry as a design invariant. For necklaces and "
    "pendants, mirror the left and right strand sequence from the centerline "
    "outward: component count, motif order, orientation, spacing, scale, "
    "metal treatment, pave coverage, gemstone treatment, and connection type "
    "must correspond link by link. For rings, mirror the two shoulders and "
    "any bilateral halo or side-stone pattern. For earring pairs, preserve "
    "matching construction unless a mirrored handed pair is requested. For "
    "bracelets, bands, and radial designs, keep the repeated sequence and "
    "spacing regular around the piece. Never make one side fully metal and "
    "the corresponding side partly pave, change a stone or motif on only one "
    "side, or alter a repeated element on one side alone unless that "
    "difference is explicitly requested. A supplied identity source remains "
    "authoritative, including any asymmetry visibly present in that source, "
    "unless the designer explicitly asks to repair or replace that asymmetry."
)


JEWELRY_SYMMETRY_REPAIR_CONTRACT = (
    "EXPLICIT SYMMETRY REPAIR: The designer has asked to correct bilateral "
    "imbalance in the selected source. Treat unmatched left/right treatment "
    "in the source as the defect to repair, not as identity to preserve. "
    "Mirror corresponding elements from the centerline outward, including "
    "component order, spacing, orientation, scale, metal treatment, pave "
    "coverage, gemstone treatment, and connections. Keep the center element, "
    "camera, background, and every unrelated or unmentioned detail fixed."
)


SIX_LEAF_RUBY_PATTERN_CONTRACT = (
    "SIX-LEAF RUBY PATTERN INTERPRETATION: The requested six leaves are six "
    "discrete leaves total around the ruby motif in the edit scope: three "
    "leaves use "
    "white-diamond treatment and three leaves use tsavorite treatment, in "
    "the requested green tone when the designer names green. "
    "Alternate the treatments one whole leaf at a time around the ruby; do "
    "not split one leaf between both materials unless the designer asks. "
    "Keep leaf size, setting style, spacing, orientation, and connections "
    "regular. Choose a reflection axis through two opposite leaves so the "
    "six-leaf alternating surround remains bilaterally symmetric. Repeat "
    "the same material phase and order at corresponding left/right ruby "
    "positions; never swap the diamond and tsavorite sequence on one side. "
    "If only one repeated ruby motif is marked, include its mirrored "
    "counterpart but keep unrelated ruby motifs and unmarked details fixed."
)


_SYMMETRY_REPAIR_REQUEST = re.compile(
    r"(?:\bsymmetr(?:y|ical|ically|ize|ise|ized|ised)\b|"
    r"\bmatch(?:ing)?\s+(?:the\s+)?(?:left\s+and\s+right|both\s+sides)\b|"
    r"\b(?:mirror|balance)\s+(?:the\s+)?(?:left\s+and\s+right|both\s+sides|"
    r"corresponding\s+(?:jewelry\s+)?elements?|side\s+patterns?)\b|"
    r"\bsame\s+(?:design|pattern|treatment)\s+on\s+both\s+sides\b)",
    flags=re.IGNORECASE,
)

_SIX_LEAF_COUNT_CUE = re.compile(
    r"\b(?:6|six)\s+(?:discrete\s+)?leaves?\b",
    flags=re.IGNORECASE,
)
_THREE_LEAVES_PER_SIDE_CUE = re.compile(
    r"\b(?:3|three)\s+leaves?\s+(?:on\s+)?(?:each|per)\s+side\b",
    flags=re.IGNORECASE,
)


def requests_six_leaf_ruby_pattern(instruction: str) -> bool:
    """Recognize the designer's six-leaf ruby material-pattern request."""

    lowered = instruction.lower()
    return (
        (
            _SIX_LEAF_COUNT_CUE.search(instruction) is not None
            or _THREE_LEAVES_PER_SIDE_CUE.search(instruction) is not None
        )
        and "ruby" in lowered
        and "diamond" in lowered
        and "tsavorite" in lowered
        and any(cue in lowered for cue in ("half", "three", "3", "pattern"))
    )


def with_jewelry_symmetry_contract(instruction: str) -> str:
    """Append the canonical symmetry rule exactly once."""

    normalized = instruction.strip()
    contracted = normalized
    if JEWELRY_SYMMETRY_CONTRACT not in contracted:
        contracted = f"{contracted}\n\n{JEWELRY_SYMMETRY_CONTRACT}"
    if (
        requests_six_leaf_ruby_pattern(normalized)
        and SIX_LEAF_RUBY_PATTERN_CONTRACT not in contracted
    ):
        contracted = f"{contracted}\n\n{SIX_LEAF_RUBY_PATTERN_CONTRACT}"
    return contracted


def requests_jewelry_symmetry_repair(instruction: str) -> bool:
    """Return true only for an explicit bilateral symmetry request."""

    return (
        JEWELRY_SYMMETRY_REPAIR_CONTRACT in instruction
        or _SYMMETRY_REPAIR_REQUEST.search(instruction) is not None
    )


def with_requested_jewelry_symmetry_repair(instruction: str) -> str:
    """Bind the default symmetry gate only to an explicit repair request."""

    normalized = instruction.strip()
    if not requests_jewelry_symmetry_repair(normalized):
        return normalized
    contracted = with_jewelry_symmetry_contract(normalized)
    if JEWELRY_SYMMETRY_REPAIR_CONTRACT in contracted:
        return contracted
    return f"{contracted}\n\n{JEWELRY_SYMMETRY_REPAIR_CONTRACT}"

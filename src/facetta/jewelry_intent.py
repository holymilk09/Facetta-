"""Conservative interpretation of sequential designer jewelry edits.

The selected source image is the accepted design state.  A continuation is a
delta against that state, never permission to redraw unrelated details or to
turn visual language into factory facts.
"""

from __future__ import annotations

import re
from collections.abc import Sequence


SEQUENTIAL_JEWELRY_EDIT_CONTRACT = (
    "SEQUENTIAL JEWELRY EDIT CONTRACT: Treat the selected source image as "
    "the complete accepted design state and this instruction only as a named "
    "delta. Change only the component and attributes explicitly named now. "
    "Preserve every prior accepted visible detail, including center stones, "
    "motif counts, bilateral placement, material sequence, settings, scale, "
    "spacing, connections, and presentation, unless this instruction names "
    "that exact detail for change. An adjective modifies only its named "
    "component; never infer a new stone species, pave, melee, component, or "
    "factory specification from an adjective such as 'small' alone."
)

SMALL_DIAMOND_VISUAL_CONTRACT = (
    "SMALL DIAMOND VISUAL INTERPRETATION: 'small white diamonds' authorizes "
    "small, melee-scale white-diamond visual accents only where the designer "
    "named them. This is appearance guidance, not a confirmed melee size, "
    "calibrated diameter, count, grade, carat weight, setting specification, "
    "or factory authority. Preserve their requested pattern and mirrored "
    "placement without inventing precision."
)

BRAIDED_WHITE_GOLD_CHAIN_CONTRACT = (
    "BRAIDED WHITE-GOLD CHAIN DELTA: Change only the necklace chain to a "
    "white-gold visual appearance and an intertwined or braided link/weave. "
    "Do not recolor or redesign ruby settings, leaf motifs, stone treatments, "
    "motif counts, their three-per-side bilateral arrangement, or any other "
    "accepted detail. White-gold appearance here is pre-spec visual intent, "
    "not confirmed alloy, purity, dimensions, or factory authority."
)

_SMALL_DIAMOND_CUE = re.compile(
    r"\bsmall(?:\s+(?:white|colourless|colorless|round|bright|accent|"
    r"pav[eé]|brilliant(?:-cut)?)){0,3}\s+diamonds?\b",
    flags=re.IGNORECASE,
)
_WHITE_GOLD_CUE = re.compile(r"\bwhite[- ]gold\b", flags=re.IGNORECASE)
_BRAIDED_CHAIN_CUE = re.compile(
    r"\b(?:intertwined|braided|woven|interlaced)\b",
    flags=re.IGNORECASE,
)
_CHAIN_CUE = re.compile(r"\bchain\b", flags=re.IGNORECASE)


def requests_small_diamond_visual_accents(instruction: str) -> bool:
    """Require the stone noun; ``small`` by itself never implies diamonds."""

    return _SMALL_DIAMOND_CUE.search(instruction) is not None


def requests_braided_white_gold_chain(instruction: str) -> bool:
    """Recognize the named chain material-and-weave continuation delta."""

    return (
        _CHAIN_CUE.search(instruction) is not None
        and _WHITE_GOLD_CUE.search(instruction) is not None
        and _BRAIDED_CHAIN_CUE.search(instruction) is not None
    )


def _accepted_context(instructions: Sequence[str]) -> str:
    accepted = tuple(
        instruction.strip()
        for instruction in instructions
        if instruction and instruction.strip()
    )
    if not accepted:
        return ""
    rows = " ".join(
        f"{index}. {instruction}"
        for index, instruction in enumerate(accepted, start=1)
    )
    return (
        "ACCEPTED SOURCE CONTEXT (history, not new commands): The selected "
        "source image is current truth. These accepted instructions explain "
        "its visible lineage; later entries supersede earlier entries. Do not "
        "reapply, undo, or newly expand them. Preserve the details that remain "
        f"visible unless the current request names them. {rows}"
    )


def with_sequential_jewelry_edit_contract(
    instruction: str,
    *,
    accepted_instructions: Sequence[str] = (),
) -> str:
    """Append named-delta, visual-scale, and chain-specific contracts once."""

    normalized = instruction.strip()
    compiled = normalized
    context = _accepted_context(accepted_instructions)
    if context and "ACCEPTED SOURCE CONTEXT (history, not new commands):" not in compiled:
        compiled = f"{compiled}\n\n{context}"
    if SEQUENTIAL_JEWELRY_EDIT_CONTRACT not in compiled:
        compiled = f"{compiled}\n\n{SEQUENTIAL_JEWELRY_EDIT_CONTRACT}"
    if (
        requests_small_diamond_visual_accents(normalized)
        and SMALL_DIAMOND_VISUAL_CONTRACT not in compiled
    ):
        compiled = f"{compiled}\n\n{SMALL_DIAMOND_VISUAL_CONTRACT}"
    if (
        requests_braided_white_gold_chain(normalized)
        and BRAIDED_WHITE_GOLD_CHAIN_CONTRACT not in compiled
    ):
        compiled = f"{compiled}\n\n{BRAIDED_WHITE_GOLD_CHAIN_CONTRACT}"
    return compiled

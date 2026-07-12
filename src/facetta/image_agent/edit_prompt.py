"""Provider-neutral prompt contract for one localized jewelry edit."""

from __future__ import annotations


EDIT_OPENERS = {
    "render": "Jewelry render edit.",
    "technical": "Jewelry technical drawing edit.",
}

_STRENGTHEN_LINE = (
    "CRITICAL: the previous attempt drifted outside the highlighted region. "
    "Preserve every pixel outside the region below with exact fidelity — "
    "this preservation contract is absolute."
)


def compile_localized_edit_instruction(
    region_description: str,
    change_instruction: str,
    kind: str = "render",
    strengthen: bool = False,
    jewelry_type: str = "ring",
) -> str:
    """Compile the preservation contract for a scoped image edit."""
    if kind not in EDIT_OPENERS:
        raise ValueError(
            f"unknown edit kind '{kind}'; options: {list(EDIT_OPENERS)}")
    if jewelry_type == "necklace":
        preserve = (
            f"PRESERVE: All design elements outside '{region_description}' must "
            "remain exactly as in the reference — same camera angle, lighting, "
            "metal tone, pendant count and geometry, bail, every stone and "
            "setting, clasp, chain endpoints and drape, all non-chain geometry, "
            "and background unchanged."
        )
    else:
        preserve = (
            f"PRESERVE: All design elements outside '{region_description}' must "
            "remain exactly as in the reference — same camera angle, lighting, "
            "metal tone, every stone and prong outside the region, shank shape "
            "outside the region, background unchanged."
        )
    edit_scope = (
        f"EDIT SCOPE: Inside '{region_description}' only: "
        f"{change_instruction}."
    )
    forbidden = (
        "FORBIDDEN: Any change outside the highlighted region; no crop; no "
        "zoom; no global redesign; no new stones outside region unless "
        "explicitly inside highlight."
    )
    if kind == "technical":
        forbidden += (
            " Do not move other view boxes or unrelated dimension strings.")
        closing = (
            "Black line art on white preserved. Match reference style "
            "exactly outside edit zone."
        )
    else:
        closing = (
            "Photorealistic jewelry product quality. Match reference style "
            "exactly outside edit zone."
        )
    lines = [EDIT_OPENERS[kind], preserve, edit_scope, forbidden, closing]
    if strengthen:
        lines = [_STRENGTHEN_LINE, *lines, preserve]
    return "\n".join(lines)

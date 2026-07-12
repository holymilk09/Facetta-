"""Design-specific mounting-hardware contracts for AI-drawn jewelry views.

The image model owns the visual proposal because a generic parametric basket
cannot represent the many valid ways a jeweler may connect stones, settings,
shoulders, galleries, and bridges.  Code owns the facts surrounding that
proposal: required observations, evidence status, cross-view checks, and the
designer-confirmation boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from facetta.spec import Spec


MountingView = Literal["plan", "front", "side", "section"]
HardwareAuthority = Literal[
    "source_observed",
    "spec_confirmed",
    "proposed_designer_confirmation_required",
    "unknown",
]


@dataclass(frozen=True)
class MountingViewContract:
    view: MountingView
    purpose: str
    required_hardware: tuple[str, ...]
    default_authority: HardwareAuthority


@dataclass(frozen=True)
class MountingHardwareContract:
    piece_mode: str
    views: tuple[MountingViewContract, ...]
    topology_locks: tuple[str, ...]
    forbidden_failures: tuple[str, ...]
    designer_confirmation_required: bool

    def evidence_summary(self) -> dict[str, object]:
        """Return JSON-safe authority metadata for the illustration."""

        return {
            "piece_mode": self.piece_mode,
            "geometry_source": "ai_design_specific_visual_proposal",
            "deterministic_geometry_allowed": False,
            "designer_confirmation_required": self.designer_confirmation_required,
            "production_authority": False,
            "views": [
                {
                    "view": view.view,
                    "authority": "unknown_until_source_and_candidate_audit",
                    "authority_policy": (
                        "hidden_geometry_is_proposed_until_designer_confirmation"
                        if view.view in {"side", "section"}
                        else "source_support_must_be_proven_per_input"
                    ),
                    "required_hardware": list(view.required_hardware),
                }
                for view in self.views
            ],
        }

    def prompt_block(self) -> str:
        view_lines = []
        for view in self.views:
            structures = ", ".join(view.required_hardware)
            view_lines.append(
                f"{view.view.upper()}: {view.purpose}; show {structures}."
            )
        return " ".join((
            "MOUNTING-HARDWARE CONTRACT — IMAGE MODEL OWNS THE DRAWN "
            "JEWELRY GEOMETRY; deterministic code must not replace it with "
            "generic circles, rectangles, baskets, or stock profiles.",
            "First inspect every supplied view and determine the actual "
            "design-specific setting family and how metal physically holds "
            "each stone and connects the head to the body. Preserve every "
            "source-visible hardware fact exactly. When a requested view "
            "reveals hardware not visible in any source, draw the most "
            "plausible coherent construction as a proposal for designer "
            "confirmation; never treat that hidden construction as observed "
            "or factory-confirmed.",
            *view_lines,
            "CROSS-VIEW TOPOLOGY LOCK: " + "; ".join(self.topology_locks) + ".",
            "HARD FAILURES: " + "; ".join(self.forbidden_failures) + ".",
            "The proposed hardware must remain editable and must be approved "
            "by the designer before it can support factory review. Production "
            "still requires tolerance-bearing CAD or a verified master.",
        ))


_RING_ENGAGEMENT = MountingHardwareContract(
    piece_mode="RING_ENGAGEMENT",
    views=(
        MountingViewContract(
            view="plan",
            purpose="establish the head footprint and holding-point topology",
            required_hardware=(
                "all actual prong or bezel holding points",
                "halo or side-stone setting boundaries when present",
                "head-to-shoulder junctions",
            ),
            default_authority="unknown",
        ),
        MountingViewContract(
            view="front",
            purpose="establish head elevation and structural symmetry or intentional asymmetry",
            required_hardware=(
                "prong stems and roots",
                "basket or setting wall",
                "gallery rails",
                "shoulder transitions",
            ),
            default_authority="unknown",
        ),
        MountingViewContract(
            view="side",
            purpose="show the real mounting construction rather than a generic stone-on-band silhouette",
            required_hardware=(
                "stone seat or bearing relationship",
                "prong roots or bezel wall",
                "basket and gallery rails appropriate to this design",
                "undergallery or bridge",
                "head-to-shoulder and head-to-shank connection",
                "pavilion and finger-clearance relationship",
            ),
            default_authority="unknown",
        ),
        MountingViewContract(
            view="section",
            purpose="explain the proposed holding and connection logic through the center-stone axis",
            required_hardware=(
                "seat contact beneath the stone girdle",
                "pavilion clearance",
                "prong or bezel structural continuity",
                "gallery and undergallery continuity",
                "head connection into shoulders or shank",
            ),
            default_authority="unknown",
        ),
    ),
    topology_locks=(
        "the same center stone, setting family, prong count, and holding-point positions in every view",
        "the same gallery-rail count and undergallery or bridge construction in front, side, and section",
        "every prong begins in metal, reaches a valid stone-holding point, and remains continuous across views",
        "shoulders connect to the same head locations in plan, front, side, and section",
        "halo and side-stone counts and setting method do not change between views",
    ),
    forbidden_failures=(
        "floating stones or stones supported only by empty space",
        "prongs disconnected from the basket, gallery, shoulder, or shank",
        "generic basket hardware that contradicts the approved design",
        "different mounting families or prong topology between views",
        "metal passing impossibly through a stone or two components occupying the same space",
        "invented hidden hardware represented as a confirmed source fact",
    ),
    designer_confirmation_required=True,
)


def mounting_hardware_contract(piece_mode: str) -> MountingHardwareContract | None:
    """Return the first-slice mounting contract for the requested piece mode."""

    if piece_mode == _RING_ENGAGEMENT.piece_mode:
        return _RING_ENGAGEMENT
    return None


def compile_mounting_hardware_prompt(piece_mode: str) -> str:
    """Compile the image-agent prompt block, or an empty block when unsupported."""

    contract = mounting_hardware_contract(piece_mode)
    return contract.prompt_block() if contract is not None else ""


def compile_mounting_view_prompt(
    spec: Spec,
    view: MountingView,
    *,
    correction: str = "",
) -> str:
    """Compile one accuracy-first AI drawing call for one mounting view.

    Multi-view composites are deliberately excluded.  Each view is generated,
    evaluated, and confirmed independently before deterministic page layout.
    """

    contract = mounting_hardware_contract("RING_ENGAGEMENT")
    if contract is None or spec.jewelry_type != "ring":
        raise ValueError("mounting-view generation currently supports rings only")
    selected = next(item for item in contract.views if item.view == view)
    center = spec.stone
    side_count = sum(group.count for group in spec.side_stones)
    setting = spec.setting
    setting_style = setting.style if setting is not None else "setting TBD"
    prong_count = setting.prong_count if setting is not None else None
    facts = (
        f"Validated visual facts: center stone {center.species}, "
        f"{center.cut.replace('_', ' ')}, {center.dimensions_mm.length:g} × "
        f"{center.dimensions_mm.width:g} mm face-up; setting {setting_style}; "
        f"center holding-prong count {prong_count if prong_count is not None else 'TBD'}; "
        f"total side/halo stone count {side_count}; metal "
        f"{spec.metal.color if spec.metal and spec.metal.color else ''} "
        f"{spec.metal.material if spec.metal else 'TBD'}."
    )
    section_rule = (
        "This must be a TRUE CUT SECTION through the center-stone axis: use "
        "section hatching only on cut metal; show the gemstone uninterrupted, "
        "its seat contacting only beneath the girdle, and open pavilion "
        "clearance. No solid member or prong may pass through the gemstone."
        if view == "section" else
        "This is an exterior orthographic view, not a perspective beauty view "
        "and not a section."
    )
    required = ", ".join(selected.required_hardware)
    correction_text = (
        f" Targeted correction from the previous failed candidate: {correction.strip()}"
        if correction.strip() else ""
    )
    return " ".join((
        f"Create exactly ONE isolated orthographic {view.upper()} technical "
        "line-art view of the SAME approved ring in the source image.",
        facts,
        "Use the source for design identity and the validated facts for exact "
        "component identity and counts. Do not simplify, beautify, substitute, "
        "or drift the center-stone outline, halo layout, prong topology, shank, "
        "or shoulder style.",
        f"The purpose of this view is to {selected.purpose}. Required visible "
        f"mounting evidence: {required}.",
        section_rule,
        "Infer only hardware hidden by the supplied view. It is a coherent "
        "design proposal requiring designer confirmation, not an observed fact. "
        "Use the actual design language of this ring; no stock or generic basket.",
        "Hard failures: floating stone; disconnected prong root; metal through "
        "a gemstone; impossible intersections; changed setting family; changed "
        "prong or halo count; generic mounting unrelated to the source.",
        "Output only the complete ring view, centered and uncropped, as crisp "
        "thin black jewelry line art on pure white. No color, shading, shadows, "
        "dimensions, arrows, labels, text, title block, logo, or watermark.",
        correction_text,
    ))

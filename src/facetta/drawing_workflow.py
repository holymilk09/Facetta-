"""Prompt contracts for the confirmed line-art then color workflow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from facetta.spec import Spec


LineArtView = Literal["front", "three_quarter", "side"]


@dataclass(frozen=True)
class DrawingBrief:
    intent: str
    style_constraints: tuple[str, ...]
    expected_output: str


def compile_line_art_brief(
    view: LineArtView,
    source_region_description: str | None = None,
) -> DrawingBrief:
    label = view.replace("_", "-")
    source_lock = (
        " Use only the designer-selected source region as geometry authority: "
        f"{source_region_description.strip()}. Do not combine, average, or "
        "invent geometry from another view on the plate. Trace only jewelry "
        "geometry actually visible inside the selected region; do not complete "
        "a hidden shank, band, shoulder, gallery, or other absent component."
        if source_region_description and source_region_description.strip()
        else ""
    )
    return DrawingBrief(
        intent=(
            f"Convert this exact approved ring into one clean black technical line-art {label} view. "
            "Remove photography, paint, paper texture, shadows, annotations, and background only."
            + source_lock
        ),
        style_constraints=(
            "pure black precise jewelry outlines on a plain white background",
            "preserve every stone, leaf, shoulder, prong, setting, band contour, count, and spatial relationship",
            (
                "one selected-view jewelry drawing only; no hidden-component "
                "completion, exploded parts, title block, labels, numbers, "
                "text, or watermark"
                if source_region_description else
                "one assembled ring view only; no exploded parts, title block, "
                "labels, numbers, text, or watermark"
            ),
            (
                "preserve the selected source view exactly; do not synthesize a "
                "new camera angle or merge geometry across plate views"
                if source_region_description else
                "preserve the source view without inventing hidden geometry"
            ),
            "consistent thin technical strokes with faceted stone outlines and no color fill",
        ),
        expected_output=(
            f"one geometry-faithful {label} line drawing of only the selected "
            "visible jewelry for explicit designer confirmation before rendering"
            if source_region_description else
            f"one geometry-faithful {label} line drawing for explicit designer "
            "confirmation before rendering"
        ),
    )


def _stone_text(spec: Spec) -> str:
    center = spec.stone
    color = center.color.trade or center.color.gia
    position_labels = {
        "pave_leaves": "diamond-set leaf shoulders",
        "halo": "the halo",
        "surround": "the center-stone surround",
        "shoulder": "the shoulders",
    }
    side = "; ".join(
        f"{group.count} {group.species} {group.cut.replace('_', ' ')} at "
        f"{position_labels.get(group.position or '', group.position or 'side')}"
        for group in spec.side_stones
    ) or "no additional confirmed side-stone groups"
    return (
        f"center: {center.species} {center.cut.replace('_', ' ')} in {color}; "
        f"side groups: {side}"
    )


def compile_color_brief(spec: Spec) -> DrawingBrief:
    metal = spec.metal
    metal_text = (
        " ".join(part for part in (
            f"{metal.karat}k" if metal and metal.karat else None,
            metal.color if metal else None,
            metal.material if metal else None,
        ) if part)
        if metal else "metal TBD"
    )
    return DrawingBrief(
        intent=(
            "Apply controlled jeweler's color to this designer-confirmed line drawing using only the validated specification. "
            f"{_stone_text(spec)}. Metal: {metal_text}."
        ),
        style_constraints=(
            "the confirmed black outline geometry is locked pixel-for-structure: add no, remove no, move no, or reshape no element",
            "fill color within the existing jewelry outlines with restrained realistic facet shading",
            "every marquise leaf outline and tiny round pave point named as diamond in the specification must remain a bright colorless faceted diamond, never yellow, gold, or plain metal",
            "apply yellow gold only to structural metal between and around gemstone outlines; never flood-fill a diamond-bearing leaf motif as solid gold",
            "keep each stone distinct and preserve the plain white background",
            "no labels, numbers, text, logo, watermark, title block, or new line work",
        ),
        expected_output=(
            "one spec-colored technical illustration with the confirmed line geometry unchanged"
        ),
    )

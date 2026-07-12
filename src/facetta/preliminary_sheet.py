"""Safe presentation boundary for incomplete deterministic sheet previews.

The underlying renderer supports generic category templates. A distinctive
reference-defined form or an incomplete chain record must never let that
generic geometry masquerade as the approved piece. Factory packs fail closed;
standalone review sheets instead cover the drawing area and state exactly why
the specification is preliminary.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

from facetta.chain_geometry import chain_factory_blockers
from facetta.design_form import unresolved_form_factory_blockers
from facetta.image_identity import spec_visual_hash
from facetta.source_component_coverage import source_component_factory_blockers
from facetta.source_component_resolution import valid_source_component_spec_paths
from facetta.spec import Spec
from facetta.svg_sheet import Branding, render_sheet


@dataclass(frozen=True)
class SheetReadinessBlocker:
    code: str
    detail: str


_BLOCKER_LABELS = {
    "visual_reference_not_dimensioned": "Custom form needs dimensioned geometry",
    "chain_production_reference_missing": "Chain needs an approved production reference",
    "chain_geometry_missing": "Chain construction dimensions are incomplete",
    "chain_pendant_connection_missing": "Pendant-to-chain connection is unresolved",
    "source_component_spec_audit_missing": "Source-to-spec audit must be repeated",
    "source_component_not_independently_audited": "Visible component needs independent audit",
    "source_component_audit_failed": "Visible component conflicts with the specification",
    "source_component_audit_inconclusive": "Visible component needs designer confirmation",
}


def sheet_readiness_blockers(spec: Spec) -> tuple[SheetReadinessBlocker, ...]:
    blockers = [
        SheetReadinessBlocker(item.code, item.message)
        for item in unresolved_form_factory_blockers(spec.design_form)
    ]
    blockers.extend(
        SheetReadinessBlocker(item.code, item.message)
        for item in chain_factory_blockers(spec)
    )
    if spec.source_component_coverage is not None:
        blockers.extend(
            SheetReadinessBlocker(item.code, item.message)
            for item in source_component_factory_blockers(
                spec.source_component_coverage,
                valid_spec_paths=valid_source_component_spec_paths(spec),
                current_spec_visual_hash=spec_visual_hash(spec),
            )
        )
    return tuple(blockers)


def _clip(value: str, limit: int = 128) -> str:
    compact = " ".join(value.split())
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"


def _blocker_text(blocker: SheetReadinessBlocker) -> str:
    label = _BLOCKER_LABELS.get(
        blocker.code,
        blocker.code.replace("_", " ").capitalize(),
    )
    return _clip(f"{label} — {blocker.detail}", 150)


def _preliminary_overlay(
    svg: str,
    blockers: tuple[SheetReadinessBlocker, ...],
) -> str:
    lines = [
        '<g id="facetta-preliminary-authority" data-authority="not-for-production">',
        # The taller solid header also covers the base renderer's estimated-
        # dimension banner.  Leaving that line partially visible made the
        # preliminary authority notice look like an accidental overlay.
        '<rect x="8.5" y="8.5" width="280" height="17.5" fill="#fdfdfa" '
        'stroke="#b3261e" stroke-width="0.8"/>',
        '<text x="148.5" y="19" text-anchor="middle" '
        'font-family="Arial, sans-serif" font-size="5.2" font-weight="bold" '
        'letter-spacing="0.8" fill="#b3261e">PRELIMINARY SPEC REVIEW — NOT FOR PRODUCTION</text>',
        '<rect x="11" y="28" width="275" height="134" rx="2" '
        'fill="#fdfdfa" fill-opacity="0.985" stroke="#b3261e" '
        'stroke-width="0.7" stroke-dasharray="3 1.5"/>',
        '<text x="148.5" y="56" text-anchor="middle" '
        'font-family="Arial, sans-serif" font-size="7" font-weight="bold" '
        'fill="#b3261e">REFERENCE-DEFINED GEOMETRY WITHHELD</text>',
        '<text x="148.5" y="67" text-anchor="middle" '
        'font-family="Arial, sans-serif" font-size="3.5" fill="#3f3f3f">'
        'The generic template drawing is hidden because it does not represent the approved design.</text>',
        '<text x="148.5" y="74" text-anchor="middle" '
        'font-family="Arial, sans-serif" font-size="3.5" fill="#3f3f3f">'
        'Use the pinned visual only for appearance. Supply dimensioned drawing or CAD geometry before manufacture.</text>',
    ]
    y = 88
    for blocker in blockers[:5]:
        label = escape(_blocker_text(blocker))
        lines.append(
            f'<text x="22" y="{y}" font-family="Arial, sans-serif" '
            f'font-size="3.2" fill="#3f3f3f">• {label}</text>'
        )
        y += 8
    if len(blockers) > 5:
        lines.append(
            f'<text x="22" y="{y}" font-family="Arial, sans-serif" '
            f'font-size="3.2" fill="#3f3f3f">• +{len(blockers) - 5} additional blockers</text>'
        )
    lines.extend([
        '<text x="148.5" y="142" text-anchor="middle" '
        'font-family="Arial, sans-serif" font-size="3.8" font-weight="bold" '
        'fill="#b3261e">NO DXF OR FACTORY PACK MAY BE GENERATED FROM THIS RECORD</text>',
        '</g>',
    ])
    marked = svg.replace(
        "CONFIDENTIAL — FACTORY PRODUCTION ONLY",
        "PRELIMINARY — NOT FOR PRODUCTION",
    )
    marked = marked.replace(
        "<svg ",
        '<svg data-facetta-authority="preliminary_not_for_production" ',
        1,
    )
    return marked.replace("</svg>", "\n".join(lines) + "\n</svg>")


def render_sheet_for_review(
    spec: Spec,
    *,
    highlight_ref: str | None = None,
    branding: Branding | None = None,
) -> tuple[str, tuple[SheetReadinessBlocker, ...]]:
    blockers = sheet_readiness_blockers(spec)
    svg = render_sheet(
        spec,
        highlight_ref=highlight_ref,
        branding=branding,
    )
    return (_preliminary_overlay(svg, blockers) if blockers else svg), blockers

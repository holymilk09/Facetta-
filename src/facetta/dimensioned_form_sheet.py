"""Render explicit designer-confirmed millimeter form geometry onto a sheet.

The legacy template renderer remains useful for supported catalog forms.  A
custom full assembly, however, must show its own confirmed profile rather than
the nearest generic pendant/ring drawing.  This module replaces only the main
drawing field while preserving the deterministic title block and schedules.
"""

from __future__ import annotations

import re
from html import escape

from facetta.design_form import (
    DesignFormElement,
    DimensionedProfileDefinition,
    DimensionedProfilePath,
)
from facetta.spec import Spec


def _fmt(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _clip(value: str, limit: int) -> str:
    compact = " ".join(value.split())
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"


def _profile_element(
    spec: Spec,
) -> tuple[DesignFormElement, DimensionedProfileDefinition] | None:
    found = [
        (element, element.definition)
        for element in spec.design_form.elements
        if element.definition.kind == "dimensioned_profile"
    ]
    if not found:
        return None
    # DesignForm rejects more than one full-assembly profile. Keep this guard
    # local as well because this renderer is a factory-truth boundary.
    if len(found) != 1:  # pragma: no cover - protected by domain validation
        raise ValueError("exactly one dimensioned full-assembly profile is required")
    element, definition = found[0]
    return element, definition


def _bounds(paths: tuple[DimensionedProfilePath, ...]) -> tuple[float, ...]:
    points = [point for path in paths for point in path.points]
    min_x = min(point.x_mm for point in points)
    max_x = max(point.x_mm for point in points)
    min_y = min(point.y_mm for point in points)
    max_y = max(point.y_mm for point in points)
    for path in paths:
        if path.nominal_width_mm is None:
            continue
        radius = path.nominal_width_mm / 2
        min_x = min(min_x, min(point.x_mm for point in path.points) - radius)
        max_x = max(max_x, max(point.x_mm for point in path.points) + radius)
        min_y = min(min_y, min(point.y_mm for point in path.points) - radius)
        max_y = max(max_y, max(point.y_mm for point in path.points) + radius)
    return min_x, min_y, max_x, max_y


def _path_svg(
    path: DimensionedProfilePath,
    *,
    origin_x: float,
    origin_y: float,
    scale: float,
) -> str:
    points = " ".join(
        f"{origin_x + point.x_mm * scale:.3f},"
        f"{origin_y - point.y_mm * scale:.3f}"
        for point in path.points
    )
    stroke_width = 0.35
    dash = ""
    if path.purpose == "centerline":
        stroke_width = max(0.35, (path.nominal_width_mm or 0.35) * scale)
    elif path.purpose in {"stone_seat", "attachment"}:
        dash = ' stroke-dasharray="1.4 0.8"'
    tag = "polygon" if path.closed else "polyline"
    return (
        f'<{tag} data-profile-path="{escape(path.path_id)}" '
        f'data-purpose="{path.purpose}" points="{points}" fill="none" '
        f'stroke="#222222" stroke-width="{stroke_width:.3f}" '
        f'stroke-linejoin="round" stroke-linecap="round"{dash}/>'
    )


def render_dimensioned_form_overlay(svg: str, spec: Spec) -> str:
    """Replace generic drawing geometry with exact embedded profile geometry."""

    selected = _profile_element(spec)
    if selected is None:
        return svg
    element, profile = selected
    min_x, min_y, max_x, max_y = _bounds(profile.paths)
    width_mm = max_x - min_x
    height_mm = max_y - min_y
    if width_mm <= 0 or height_mm <= 0:  # pragma: no cover - model guards area
        raise ValueError("dimensioned profile must have non-zero extents")

    plot_x, plot_y, plot_w, plot_h = 22.0, 43.0, 178.0, 98.0
    scale = min(1.0, plot_w / width_mm, plot_h / height_mm)
    center_x = plot_x + plot_w / 2
    center_y = plot_y + plot_h / 2
    datum_x = center_x - ((min_x + max_x) / 2) * scale
    datum_y = center_y + ((min_y + max_y) / 2) * scale
    left = datum_x + min_x * scale
    right = datum_x + max_x * scale
    top = datum_y - max_y * scale
    bottom = datum_y - min_y * scale
    status = (
        "CONFIRMED MEASUREMENTS"
        if profile.dimension_status == "designer_supplied"
        else "DESIGNER-CONFIRMED ESTIMATES — VERIFY BEFORE PRODUCTION"
    )
    scale_label = "1:1" if scale == 1.0 else f"{scale:.3f}:1"
    dimension_prefix = (
        "" if profile.dimension_status == "designer_supplied" else "EST. "
    )

    geometry = [
        '<rect x="11" y="24" width="275" height="138" fill="#ffffff"/>',
        '<g id="facetta-dimensioned-form" '
        'data-facetta-geometry="designer-confirmed-dimensioned-profile">',
        '<text x="148.5" y="31.5" text-anchor="middle" '
        'font-family="Arial, sans-serif" font-size="4.7" font-weight="bold" '
        'letter-spacing="0.5" fill="#222222">DESIGNER-CONFIRMED DIMENSIONED PROFILE</text>',
        f'<text x="148.5" y="37" text-anchor="middle" '
        f'font-family="Arial, sans-serif" font-size="2.8" fill="#8a5a00">'
        f'{escape(status)}</text>',
        f'<line x1="{plot_x:.3f}" y1="{datum_y:.3f}" '
        f'x2="{plot_x + plot_w:.3f}" y2="{datum_y:.3f}" '
        'stroke="#b5b5b5" stroke-width="0.18" stroke-dasharray="1.5 1"/>',
        f'<line x1="{datum_x:.3f}" y1="{plot_y:.3f}" '
        f'x2="{datum_x:.3f}" y2="{plot_y + plot_h:.3f}" '
        'stroke="#b5b5b5" stroke-width="0.18" stroke-dasharray="1.5 1"/>',
        *(
            _path_svg(
                path,
                origin_x=datum_x,
                origin_y=datum_y,
                scale=scale,
            )
            for path in profile.paths
        ),
        f'<line x1="{left:.3f}" y1="{top - 5:.3f}" '
        f'x2="{right:.3f}" y2="{top - 5:.3f}" '
        'stroke="#666666" stroke-width="0.22"/>',
        f'<line x1="{left:.3f}" y1="{top - 6.5:.3f}" '
        f'x2="{left:.3f}" y2="{top + 1:.3f}" '
        'stroke="#888888" stroke-width="0.18"/>',
        f'<line x1="{right:.3f}" y1="{top - 6.5:.3f}" '
        f'x2="{right:.3f}" y2="{top + 1:.3f}" '
        'stroke="#888888" stroke-width="0.18"/>',
        f'<text x="{(left + right) / 2:.3f}" y="{top - 7:.3f}" '
        f'text-anchor="middle" font-family="Arial, sans-serif" '
        f'font-size="2.7" fill="#3f3f3f">{dimension_prefix}'
        f'{_fmt(width_mm)} mm OVERALL W</text>',
        f'<line x1="{left - 7:.3f}" y1="{top:.3f}" '
        f'x2="{left - 7:.3f}" y2="{bottom:.3f}" '
        'stroke="#666666" stroke-width="0.22"/>',
        f'<line x1="{left - 8.5:.3f}" y1="{top:.3f}" '
        f'x2="{left + 1:.3f}" y2="{top:.3f}" '
        'stroke="#888888" stroke-width="0.18"/>',
        f'<line x1="{left - 8.5:.3f}" y1="{bottom:.3f}" '
        f'x2="{left + 1:.3f}" y2="{bottom:.3f}" '
        'stroke="#888888" stroke-width="0.18"/>',
        f'<text x="{left - 9:.3f}" y="{(top + bottom) / 2:.3f}" '
        f'text-anchor="end" font-family="Arial, sans-serif" '
        f'font-size="2.7" fill="#3f3f3f">{dimension_prefix}'
        f'{_fmt(height_mm)} mm H</text>',
        f'<text x="22" y="148" font-family="Arial, sans-serif" '
        f'font-size="3" fill="#3f3f3f">Overall extents: '
        f'{_fmt(width_mm)} × {_fmt(height_mm)} mm · profile thickness '
        f'{_fmt(profile.profile_thickness_mm)} mm · scale {scale_label}</text>',
        f'<text x="22" y="154" font-family="Arial, sans-serif" '
        f'font-size="2.7" fill="#666666">Datum: x right / y up · '
        f'view {escape(profile.view)} · {escape(_clip(element.label, 60))}</text>',
        '<text x="208" y="51" font-family="Arial, sans-serif" '
        'font-size="3.1" font-weight="bold" fill="#222222">PROFILE RECORD</text>',
        f'<text x="208" y="59" font-family="Arial, sans-serif" '
        f'font-size="2.7" fill="#3f3f3f">Confirmed by: '
        f'{escape(_clip(profile.confirmed_by, 34))}</text>',
        f'<text x="208" y="65" font-family="Arial, sans-serif" '
        f'font-size="2.7" fill="#3f3f3f">Confirmed: '
        f'{profile.confirmed_at.date().isoformat()}</text>',
        f'<text x="208" y="71" font-family="Arial, sans-serif" '
        f'font-size="2.7" fill="#3f3f3f">Source: '
        f'{escape(_clip(profile.source_asset_id, 32))}</text>',
        f'<text x="208" y="81" font-family="Arial, sans-serif" '
        f'font-size="2.7" fill="#3f3f3f">{escape(_clip(profile.manufacturing_notes, 46))}</text>',
        '</g>',
    ]
    marked = re.sub(
        r"SCALE\s+[0-9.]+:1",
        f"SCALE {scale_label}",
        svg,
    ).replace(
        "<svg ",
        '<svg data-facetta-form-authority="dimensioned_profile" ',
        1,
    )
    return marked.replace("</svg>", "\n".join(geometry) + "\n</svg>")

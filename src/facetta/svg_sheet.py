"""Annotated technical sheet renderer: spec object -> SVG.

Deterministic by construction — every coordinate derives from the spec's mm
values; the only date on the sheet is the version's created_at. Same spec in,
byte-identical SVG out. The AI never draws geometry; this code does, from
numbers.

Sheet layout: A4 landscape, 1 SVG user unit = 1 mm of paper, drawings at a
fixed 3:1 scale. Two orthographic views of the solitaire ring:

- TOP VIEW: looking down at the worn ring — shank strip (band width), stone
  outline (length x width) with prong tips.
- SIDE PROFILE: looking along the palm — band hoop cross-section (inner
  diameter, thickness), stone profile (crown/girdle/pavilion), basket and
  prongs, gallery height.

Pencil-style rendering: thin gray strokes, light diagonal hatching on metal
cross-sections, architectural tick dimension lines, and a title block.
"""

from __future__ import annotations

import math

from facetta.spec import Spec

SHEET_W, SHEET_H = 297.0, 210.0
MARGIN = 8.0
SCALE = 3.0

INK = "#3f3f3f"
FAINT = "#8a8a8a"
STROKE_MAIN = 0.3
STROKE_DIM = 0.15
FONT = "Georgia, 'Times New Roman', serif"

SUPPORTED_TEMPLATES = ("solitaire_prong",)
SUPPORTED_CUTS = ("round_brilliant", "oval_brilliant")


class SheetUnsupported(Exception):
    """The sheet renderer does not cover this template/cut yet."""


def _fmt(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _text(x: float, y: float, s: str, *, size: float = 3.2, anchor: str = "middle",
          color: str = INK, style: str = "") -> str:
    return (
        f'<text x="{x:.2f}" y="{y:.2f}" font-family="{FONT}" font-size="{size}" '
        f'fill="{color}" text-anchor="{anchor}"{style}>{s}</text>'
    )


def _line(x1: float, y1: float, x2: float, y2: float, *, w: float = STROKE_MAIN,
          color: str = INK, dash: str = "") -> str:
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" '
        f'stroke="{color}" stroke-width="{w}"{d}/>'
    )


def _tick(x: float, y: float) -> str:
    # 45-degree architectural tick centered on the dimension line endpoint
    return _line(x - 0.9, y + 0.9, x + 0.9, y - 0.9, w=STROKE_DIM * 1.6)


def _dim_h(x1: float, x2: float, y: float, label: str) -> list[str]:
    """Horizontal dimension line with ticks and a centered label above."""
    return [
        _line(x1, y, x2, y, w=STROKE_DIM, color=FAINT),
        _tick(x1, y), _tick(x2, y),
        _text((x1 + x2) / 2, y - 1.4, label),
    ]


def _dim_v(x: float, y1: float, y2: float, label: str) -> list[str]:
    """Vertical dimension line with ticks and a label to its right."""
    return [
        _line(x, y1, x, y2, w=STROKE_DIM, color=FAINT),
        _tick(x, y1), _tick(x, y2),
        _text(x + 1.8, (y1 + y2) / 2 + 1.1, label, anchor="start"),
    ]


def _ext(x1: float, y1: float, x2: float, y2: float) -> str:
    """Faint extension line from geometry out to a dimension line."""
    return _line(x1, y1, x2, y2, w=STROKE_DIM, color=FAINT, dash="0.8 0.8")


def _top_view(spec: Spec, cx: float, cy: float) -> list[str]:
    stone = spec.stone
    length = stone.dimensions_mm.length * SCALE
    width = stone.dimensions_mm.width * SCALE
    rx, ry = width / 2, length / 2

    band_w = spec.band.width_mm * SCALE
    inner = spec.ring_size.inner_diameter_mm * SCALE
    thickness = spec.band.thickness_mm * SCALE
    strip_len = inner + 2 * thickness  # the hoop seen from above spans its outer diameter

    top, bottom = cy - strip_len / 2, cy + strip_len / 2
    left_x, right_x = cx - band_w / 2, cx + band_w / 2

    parts = [
        # shank strip, hatched metal
        f'<rect x="{left_x:.2f}" y="{top:.2f}" width="{band_w:.2f}" height="{strip_len:.2f}" '
        f'fill="url(#hatch)" stroke="none"/>',
        _line(left_x, top, left_x, bottom),
        _line(right_x, top, right_x, bottom),
        _line(left_x, top, right_x, top),
        _line(left_x, bottom, right_x, bottom),
        # stone outline over the shank
        f'<ellipse cx="{cx:.2f}" cy="{cy:.2f}" rx="{rx:.2f}" ry="{ry:.2f}" '
        f'fill="#ffffff" stroke="{INK}" stroke-width="{STROKE_MAIN}"/>',
        # centerlines
        _line(cx, cy - ry - 3, cx, cy + ry + 3, w=STROKE_DIM, color=FAINT, dash="3 1 0.5 1"),
        _line(cx - rx - 3, cy, cx + rx + 3, cy, w=STROKE_DIM, color=FAINT, dash="3 1 0.5 1"),
    ]

    prong_r = (spec.setting.prong_tip_mm or 0.9) * SCALE / 2
    count = spec.setting.prong_count or 4
    for i in range(count):
        angle = math.pi / count + i * 2 * math.pi / count  # start between the axes
        px = cx + rx * math.cos(angle)
        py = cy + ry * math.sin(angle)
        parts.append(
            f'<circle cx="{px:.2f}" cy="{py:.2f}" r="{prong_r:.2f}" '
            f'fill="#ffffff" stroke="{INK}" stroke-width="{STROKE_MAIN}"/>'
        )

    dim_w = _fmt(stone.dimensions_mm.width)
    dim_l = _fmt(stone.dimensions_mm.length)
    dim_b = _fmt(spec.band.width_mm)

    y_dim = cy - max(ry, 0) - 7
    x_dim = cx + max(rx, band_w / 2) + 8
    parts += [
        _ext(cx - rx, cy, cx - rx, y_dim - 1), _ext(cx + rx, cy, cx + rx, y_dim - 1),
        *_dim_h(cx - rx, cx + rx, y_dim, f"{dim_w} mm"),
        _ext(cx, cy - ry, x_dim + 1, cy - ry), _ext(cx, cy + ry, x_dim + 1, cy + ry),
        *_dim_v(x_dim, cy - ry, cy + ry, f"{dim_l} mm"),
        _ext(left_x, bottom, left_x, bottom + 6), _ext(right_x, bottom, right_x, bottom + 6),
        *_dim_h(left_x, right_x, bottom + 5, f"{dim_b} mm"),
        _text(cx, bottom + 14, "TOP VIEW", size=3.6, style=' letter-spacing="1.2"'),
    ]
    return parts


def _side_view(spec: Spec, cx: float, cy: float) -> list[str]:
    stone = spec.stone
    inner_r = spec.ring_size.inner_diameter_mm * SCALE / 2
    outer_r = inner_r + spec.band.thickness_mm * SCALE
    gallery = (spec.setting.gallery_height_mm or 0.0) * SCALE
    depth = stone.dimensions_mm.depth * SCALE
    span = stone.dimensions_mm.length * SCALE  # profile seen across the finger

    crown_h = depth / 3
    pavilion_h = depth - crown_h
    table_w = span * 0.55

    # center the composition: hoop lower, stone above
    ring_cy = cy + (gallery + depth) / 2 - depth / 3
    ring_top = ring_cy - outer_r
    y_girdle = ring_top - gallery
    y_table = y_girdle - crown_h
    y_culet = y_girdle + pavilion_h

    xl, xr = cx - span / 2, cx + span / 2
    txl, txr = cx - table_w / 2, cx + table_w / 2

    parts = [
        # band hoop cross-section, hatched metal between the circles
        f'<circle cx="{cx:.2f}" cy="{ring_cy:.2f}" r="{outer_r:.2f}" '
        f'fill="url(#hatch)" stroke="{INK}" stroke-width="{STROKE_MAIN}"/>',
        f'<circle cx="{cx:.2f}" cy="{ring_cy:.2f}" r="{inner_r:.2f}" '
        f'fill="#ffffff" stroke="{INK}" stroke-width="{STROKE_MAIN}"/>',
        # basket: slanted gallery lines from hoop shoulders up to the girdle
        _line(cx - outer_r * 0.28, ring_top + 1.2, xl, y_girdle),
        _line(cx + outer_r * 0.28, ring_top + 1.2, xr, y_girdle),
        # stone profile: table, crown, girdle, pavilion to culet
        f'<polygon points="{txl:.2f},{y_table:.2f} {txr:.2f},{y_table:.2f} '
        f'{xr:.2f},{y_girdle:.2f} {cx:.2f},{y_culet:.2f} {xl:.2f},{y_girdle:.2f}" '
        f'fill="#ffffff" stroke="{INK}" stroke-width="{STROKE_MAIN}"/>',
        _line(xl, y_girdle, xr, y_girdle),
        # centerline through the hoop
        _line(cx, ring_top - gallery - crown_h - 3, cx, ring_cy + outer_r + 3,
              w=STROKE_DIM, color=FAINT, dash="3 1 0.5 1"),
    ]

    prong_r = (spec.setting.prong_tip_mm or 0.9) * SCALE / 2
    for x in (xl - prong_r / 2, xr + prong_r / 2):
        parts += [
            _line(x, y_girdle + 2.0, x, y_table + 1.0),
            f'<circle cx="{x:.2f}" cy="{y_table + 1.0:.2f}" r="{prong_r:.2f}" '
            f'fill="#ffffff" stroke="{INK}" stroke-width="{STROKE_MAIN}"/>',
        ]

    dim_id = _fmt(spec.ring_size.inner_diameter_mm)
    dim_g = _fmt(spec.setting.gallery_height_mm or 0.0)
    dim_d = _fmt(stone.dimensions_mm.depth)

    x_dim = cx + outer_r + 9
    x_dim2 = x_dim + 26
    parts += [
        # inner diameter across the hoop
        *_dim_h(cx - inner_r, cx + inner_r, ring_cy, f"⌀ {dim_id} mm"),
        # gallery height on the near right, stone depth further out
        _ext(xr, y_girdle, x_dim + 1, y_girdle),
        _ext(cx + outer_r * 0.28, ring_top, x_dim + 1, ring_top),
        *_dim_v(x_dim, y_girdle, ring_top, f"{dim_g} mm gallery"),
        _ext(txr, y_table, x_dim2 + 1, y_table),
        _ext(cx, y_culet, x_dim2 + 1, y_culet),
        *_dim_v(x_dim2, y_table, y_culet, f"{dim_d} mm"),
        _text(cx, ring_cy + outer_r + 12, "SIDE PROFILE", size=3.6, style=' letter-spacing="1.2"'),
    ]
    return parts


def _title_block(spec: Spec) -> list[str]:
    x = SHEET_W - MARGIN - 100
    y = SHEET_H - MARGIN - 40
    stone = spec.stone
    metal = spec.metal
    karat = f"{metal.karat}k " if metal.karat else ""
    finish = f", {metal.finish.replace('_', ' ')}" if metal.finish else ""
    lines = [
        (f"{spec.design_id}  ·  v{spec.version}", 4.2, True),
        (f"{stone.carat:.2f} ct {stone.species}, {stone.cut.replace('_', ' ')}", 3.2, False),
        (f"{karat}{metal.color} {metal.material}{finish}", 3.2, False),
        (f"{stone.color.trade}  ·  {stone.clarity.grade}", 3.2, False),
        (f"designer {spec.created_by}  ·  {spec.created_at.date().isoformat()}", 3.0, False),
        ("UNITS mm  ·  SCALE 3:1", 3.0, False),
    ]
    parts = [
        f'<rect x="{x:.2f}" y="{y:.2f}" width="100" height="40" fill="none" '
        f'stroke="{INK}" stroke-width="{STROKE_MAIN}"/>',
        _line(x, y + 8, x + 100, y + 8, w=STROKE_DIM),
        _text(x + 3, y + 5.8, "FACETTA", size=4.0, anchor="start", style=' letter-spacing="2.0"'),
    ]
    ty = y + 8
    for s, size, bold in lines:
        ty += 4.6 if not bold else 5.6
        weight = ' font-weight="bold"' if bold else ""
        parts.append(_text(x + 3, ty, s, size=size, anchor="start", style=weight))
    return parts


def render_sheet(spec: Spec) -> str:
    """Render the annotated technical sheet for a validated spec."""
    if spec.template not in SUPPORTED_TEMPLATES:
        raise SheetUnsupported(
            f"template '{spec.template}' not supported yet; supported: {list(SUPPORTED_TEMPLATES)}"
        )
    if spec.stone.cut not in SUPPORTED_CUTS:
        raise SheetUnsupported(
            f"cut '{spec.stone.cut}' not supported on sheets yet; supported: {list(SUPPORTED_CUTS)}"
        )
    if spec.band is None or spec.ring_size is None or spec.ring_size.inner_diameter_mm is None:
        raise SheetUnsupported("a solitaire sheet needs band and ring_size (with inner diameter)")

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SHEET_W:g} {SHEET_H:g}" '
        f'width="{SHEET_W:g}mm" height="{SHEET_H:g}mm" font-family="{FONT}">',
        "<defs>"
        '<pattern id="hatch" width="1.4" height="1.4" patternTransform="rotate(45)" patternUnits="userSpaceOnUse">'
        f'<line x1="0" y1="0" x2="0" y2="1.4" stroke="{FAINT}" stroke-width="0.12"/>'
        "</pattern>"
        "</defs>",
        f'<rect x="0" y="0" width="{SHEET_W:g}" height="{SHEET_H:g}" fill="#fdfdfa"/>',
        f'<rect x="{MARGIN:g}" y="{MARGIN:g}" width="{SHEET_W - 2 * MARGIN:g}" '
        f'height="{SHEET_H - 2 * MARGIN:g}" fill="none" stroke="{INK}" stroke-width="{STROKE_MAIN}"/>',
        _text(SHEET_W / 2, MARGIN + 8, "TECHNICAL SHEET — SOLITAIRE RING",
              size=4.6, style=' letter-spacing="1.6"'),
    ]
    parts += _top_view(spec, 82, 105)
    parts += _side_view(spec, 200, 100)
    parts += _title_block(spec)
    if spec.notes_to_factory:
        parts.append(_text(MARGIN + 4, SHEET_H - MARGIN - 4,
                           f"NOTES: {spec.notes_to_factory}", size=3.0, anchor="start"))
    parts.append("</svg>")
    return "\n".join(parts) + "\n"

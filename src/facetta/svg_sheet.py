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

from facetta import gemcad
from facetta.spec import Spec
from facetta.validation import (
    NestingClearance, ellipse_perimeter_mm, estimate_metal_g, pendant_drop_mm,
)

SHEET_W, SHEET_H = 297.0, 210.0
MARGIN = 8.0
SCALE = 3.0
BASELINE = 105.0  # shared horizontal datum: every view's centerline sits here

INK = "#3f3f3f"
FAINT = "#8a8a8a"
PAPER = "#fdfdfa"
ACCENT = "#7a5c2e"  # second piece on stacking sheets
STROKE_MAIN = 0.3
STROKE_DIM = 0.15
FONT = "Georgia, 'Times New Roman', serif"

SUPPORTED_CUTS = ("round_brilliant", "oval_brilliant")  # solitaire / halo center cuts
BANGLE_STATION_CUTS = ("princess", "asscher")
PENDANT_CENTER_CUTS = ("emerald_cut", "asscher", "radiant")


class SheetUnsupported(Exception):
    """The sheet renderer does not cover this template/cut yet."""


def _fmt(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _text(x: float, y: float, s: str, *, size: float = 3.2, anchor: str = "middle",
          color: str = INK, style: str = "", halo: bool = False) -> str:
    # halo paints the paper color behind the glyphs so a label crossing
    # linework stays readable without hiding the geometry beneath it
    h = (f' stroke="{PAPER}" stroke-width="1.0" stroke-linejoin="round" '
         'paint-order="stroke"') if halo else ""
    return (
        f'<text x="{x:.2f}" y="{y:.2f}" font-family="{FONT}" font-size="{size}" '
        f'fill="{color}" text-anchor="{anchor}"{h}{style}>{s}</text>'
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
        _text((x1 + x2) / 2, y - 1.4, label, halo=True),
    ]


def _dim_v(x: float, y1: float, y2: float, label: str) -> list[str]:
    """Vertical dimension line with ticks and a label to its right."""
    return [
        _line(x, y1, x, y2, w=STROKE_DIM, color=FAINT),
        _tick(x, y1), _tick(x, y2),
        _text(x + 1.8, (y1 + y2) / 2 + 1.1, label, anchor="start", halo=True),
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
        # shank strip, hatched metal — rounded ends, the hoop curving away
        f'<rect x="{left_x:.2f}" y="{top:.2f}" width="{band_w:.2f}" height="{strip_len:.2f}" '
        f'rx="{band_w / 2:.2f}" fill="url(#hatch)" stroke="{INK}" '
        f'stroke-width="{STROKE_MAIN}"/>',
        # stone with its standard face-up facet pattern
        *_facet_face_up(cx, cy, stone.cut, 2 * rx, 2 * ry),
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
        _ext(left_x, bottom - band_w / 2, left_x, bottom + 6),
        _ext(right_x, bottom - band_w / 2, right_x, bottom + 6),
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

    # cy IS the hoop center — the view's datum, shared with the top view
    ring_cy = cy
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
        _ext(cx, ring_top, x_dim + 1, ring_top),  # anchored on the hoop's top point
        *_dim_v(x_dim, y_girdle, ring_top, f"{dim_g} mm gallery"),
        _ext(txr, y_table, x_dim2 + 1, y_table),
        _ext(cx, y_culet, x_dim2 + 1, y_culet),
        *_dim_v(x_dim2, y_table, y_culet, f"{dim_d} mm"),
        _text(cx, ring_cy + outer_r + 12, "SIDE PROFILE", size=3.6, style=' letter-spacing="1.2"'),
    ]
    return parts


def _title_block(spec: Spec, scale_label: str = "3:1") -> list[str]:
    x = SHEET_W - MARGIN - 100
    y = SHEET_H - MARGIN - 40
    stone = spec.stone
    metal = spec.metal
    if metal is not None:
        karat = f"{metal.karat}k " if metal.karat else ""
        finish = f", {metal.finish.replace('_', ' ')}" if metal.finish else ""
        metal_line = f"{karat}{metal.color} {metal.material}{finish}"
    else:
        metal_line = "loose stone — unmounted"
    lines = [
        (f"{spec.design_id}  ·  v{spec.version}", 4.2, True),
        (f"{stone.carat:.2f} ct {stone.species}, {stone.cut.replace('_', ' ')}", 3.2, False),
        (metal_line, 3.2, False),
        (f"{stone.color.trade}  ·  {stone.clarity.grade}" if stone.clarity
         else f"{stone.color.trade}  ·  finest available", 3.2, False),
        (f"designer {spec.created_by}  ·  {spec.created_at.date().isoformat()}", 3.0, False),
        (f"UNITS mm  ·  SCALE {scale_label}"
         + (f"  ·  EST. {weight} g" if (weight := estimate_metal_g(spec)) else ""), 3.0, False),
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


def _footer_key() -> list[str]:
    """Footer legend strip: what each line style on the sheet means."""
    top = SHEET_H - MARGIN - 8
    y = top + 4  # sample-line y inside the strip
    ty = y + 1.0  # label baseline

    def sample(x: float, label: str, dash: str = "") -> list[str]:
        return [
            _line(x, y, x + 8, y, w=STROKE_DIM if dash else STROKE_MAIN,
                  color=FAINT if dash else INK, dash=dash),
            _text(x + 10, ty, label, size=2.6, anchor="start", color=FAINT),
        ]

    parts = [
        _line(MARGIN, top, SHEET_W - MARGIN - 100, top, w=STROKE_DIM, color=FAINT),
        _text(MARGIN + 4, ty, "KEY", size=2.8, anchor="start",
              style=' letter-spacing="1.4"'),
        *sample(MARGIN + 18, "edge"),
        # 0.9 0.9 dashing: reads identically but is a depiction, not a live
        # witness line, so the snap audit doesn't try to anchor it
        *sample(MARGIN + 52, "witness", dash="0.9 0.9"),
        *sample(MARGIN + 84, "centerline", dash="6 1.5 1 1.5"),
        f'<rect x="{MARGIN + 114:.2f}" y="{y - 1.5:.2f}" width="8" height="3" '
        f'fill="url(#hatch)" stroke="{INK}" stroke-width="{STROKE_DIM}"/>',
        _text(MARGIN + 124, ty, "metal section", size=2.6, anchor="start", color=FAINT),
        _text(SHEET_W - MARGIN - 104, ty, "all dimensions in mm", size=2.6,
              anchor="end", color=FAINT),
    ]
    return parts


def _frame(spec: Spec, title: str, scale_label: str, body: list[str],
           datum_y: float | None = BASELINE) -> str:
    """The shared sheet envelope: page, border, title, body views, title block.

    datum_y draws the shared horizontal baseline every view is centered on.
    """
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SHEET_W:g} {SHEET_H:g}" '
        f'width="{SHEET_W:g}mm" height="{SHEET_H:g}mm" font-family="{FONT}">',
        "<defs>"
        '<pattern id="hatch" width="1.4" height="1.4" patternTransform="rotate(45)" patternUnits="userSpaceOnUse">'
        f'<line x1="0" y1="0" x2="0" y2="1.4" stroke="{FAINT}" stroke-width="0.12"/>'
        "</pattern>"
        "</defs>",
        f'<rect x="0" y="0" width="{SHEET_W:g}" height="{SHEET_H:g}" fill="{PAPER}"/>',
        f'<rect x="{MARGIN:g}" y="{MARGIN:g}" width="{SHEET_W - 2 * MARGIN:g}" '
        f'height="{SHEET_H - 2 * MARGIN:g}" fill="none" stroke="{INK}" stroke-width="{STROKE_MAIN}"/>',
        _text(SHEET_W / 2, MARGIN + 8, title, size=4.6, style=' letter-spacing="1.6"'),
        _line(MARGIN + 3, MARGIN + 11.5, SHEET_W - MARGIN - 3, MARGIN + 11.5,
              w=STROKE_DIM, color=FAINT),  # header rule under the sheet title
    ]
    if datum_y is not None:
        parts.append(_line(MARGIN + 3, datum_y, SHEET_W - MARGIN - 3, datum_y,
                           w=STROKE_DIM, color=FAINT, dash="6 1.5 1 1.5"))
    parts += body
    parts += _title_block(spec, scale_label)
    parts += _footer_key()
    if spec.notes_to_factory:
        parts.append(_text(MARGIN + 4, SHEET_H - MARGIN - 10.5,
                           f"NOTES: {spec.notes_to_factory}", size=3.0, anchor="start"))
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def _front_view(spec: Spec, cx: float, cy: float, melee=None) -> list[str]:
    """Third orthographic view for rings: the band edge-on with the setting's
    rise above the shank — the view factories use to judge sit height."""
    stone = spec.stone
    inner_r = spec.ring_size.inner_diameter_mm * SCALE / 2
    outer_r = inner_r + spec.band.thickness_mm * SCALE
    band_w = spec.band.width_mm * SCALE
    gallery = (spec.setting.gallery_height_mm or 0.0) * SCALE
    depth = stone.dimensions_mm.depth * SCALE
    span = stone.dimensions_mm.width * SCALE  # seen across the finger

    crown_h = depth / 3
    ring_cy = cy
    ring_top = ring_cy - outer_r
    y_girdle = ring_top - gallery
    y_table = y_girdle - crown_h
    y_culet = y_girdle + (depth - crown_h)
    xl, xr = cx - span / 2, cx + span / 2
    txl, txr = cx - span * 0.55 / 2, cx + span * 0.55 / 2

    parts = [
        # band edge-on: a capsule as tall as the hoop — the bottom of a ring
        # reads rounded from the front, never squared off
        f'<rect x="{cx - band_w / 2:.2f}" y="{ring_top:.2f}" width="{band_w:.2f}" '
        f'height="{2 * outer_r:.2f}" rx="{band_w / 2:.2f}" fill="url(#hatch)" stroke="{INK}" '
        f'stroke-width="{STROKE_MAIN}"/>',
        # basket flare from the shank up to the girdle
        _line(cx - band_w / 2, ring_top + band_w / 2, xl, y_girdle),
        _line(cx + band_w / 2, ring_top + band_w / 2, xr, y_girdle),
        # stone from the front
        f'<polygon points="{txl:.2f},{y_table:.2f} {txr:.2f},{y_table:.2f} '
        f'{xr:.2f},{y_girdle:.2f} {cx:.2f},{y_culet:.2f} {xl:.2f},{y_girdle:.2f}" '
        f'fill="#ffffff" stroke="{INK}" stroke-width="{STROKE_MAIN}"/>',
        _line(xl, y_girdle, xr, y_girdle),
        _line(cx, y_table - 3, cx, ring_cy + outer_r + 3, w=STROKE_DIM, color=FAINT,
              dash="3 1 0.5 1"),
    ]
    prong_r = (spec.setting.prong_tip_mm or 0.9) * SCALE / 2
    for x in (xl - prong_r / 2, xr + prong_r / 2):
        parts += [
            _line(x, y_girdle + 2.0, x, y_table + 1.0),
            _circle(x, y_table + 1.0, prong_r),
        ]
    if melee is not None:
        mr = melee.dimensions_mm.width / 2 * SCALE
        for sign in (-1, 1):
            parts.append(_circle(cx + sign * (span / 2 + prong_r + 0.6 + mr), y_girdle, mr))

    rise_mm = (spec.setting.gallery_height_mm or 0.0) + stone.dimensions_mm.depth / 3
    x_dim = cx + max(span / 2, band_w / 2) + 9
    parts += [
        _ext(txr, y_table, x_dim + 1, y_table),
        _ext(cx, ring_top, x_dim + 1, ring_top),  # capsule apex
        *_dim_v(x_dim, y_table, ring_top, f"{_fmt(rise_mm)} mm rise"),
        _ext(cx - band_w / 2, ring_cy + outer_r - band_w / 2, cx - band_w / 2, ring_cy + outer_r + 7),
        _ext(cx + band_w / 2, ring_cy + outer_r - band_w / 2, cx + band_w / 2, ring_cy + outer_r + 7),
        *_dim_h(cx - band_w / 2, cx + band_w / 2, ring_cy + outer_r + 6,
                f"{_fmt(spec.band.width_mm)} mm"),
        _text(cx, ring_cy + outer_r + 14, "FRONT VIEW", size=3.6, style=' letter-spacing="1.2"'),
    ]
    return parts


def _require_ring_sections(spec: Spec, what: str) -> None:
    if spec.band is None or spec.ring_size is None or spec.ring_size.inner_diameter_mm is None:
        raise SheetUnsupported(f"a {what} sheet needs band and ring_size (with inner diameter)")


def _render_solitaire(spec: Spec) -> str:
    if spec.stone.cut not in SUPPORTED_CUTS:
        raise SheetUnsupported(
            f"cut '{spec.stone.cut}' not supported on sheets yet; supported: {list(SUPPORTED_CUTS)}"
        )
    _require_ring_sections(spec, "solitaire")
    body = (
        _top_view(spec, 58, BASELINE)
        + _front_view(spec, 138, BASELINE)
        + _side_view(spec, 208, BASELINE)
    )
    return _frame(spec, "TECHNICAL SHEET — SOLITAIRE RING", "3:1", body)


def _find_stone(spec: Spec, *positions: str):
    return next((s for s in spec.side_stones if s.position in positions), None)


def _circle(cx: float, cy: float, r: float, fill: str = "#ffffff") -> str:
    return (
        f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}" '
        f'fill="{fill}" stroke="{INK}" stroke-width="{STROKE_MAIN}"/>'
    )


def _ellipse(cx: float, cy: float, rx: float, ry: float, fill: str = "#ffffff") -> str:
    return (
        f'<ellipse cx="{cx:.2f}" cy="{cy:.2f}" rx="{rx:.2f}" ry="{ry:.2f}" '
        f'fill="{fill}" stroke="{INK}" stroke-width="{STROKE_MAIN}"/>'
    )


# --- face-up facet patterns ----------------------------------------------------
#
# Standard facet diagrams per cut family, GIA-diagram style: brilliant cuts get
# the 8-main / 8-star / 16-upper-girdle pattern, princess gets chevrons, step
# cuts get concentric rows. Everything is parameterized on the stone's actual
# outline so patterns stay true on ovals, pears, and marquises.

BRILLIANT_CUTS = ("round_brilliant", "oval_brilliant", "pear", "marquise", "cushion", "trillion")
STEP_CUTS = ("emerald_cut", "asscher", "radiant")


def _pt(cx: float, cy: float, rx: float, ry: float, deg: float) -> tuple[float, float]:
    return cx + rx * math.cos(math.radians(deg)), cy + ry * math.sin(math.radians(deg))


def _poly(points: list[tuple[float, float]], fill: str, stroke: str, w: float) -> str:
    pts = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
    return f'<polygon points="{pts}" fill="{fill}" stroke="{stroke}" stroke-width="{w}"/>'


def _lit_poly(points: list[tuple[float, float]], fill: str, opacity: float) -> str:
    pts = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
    return f'<polygon points="{pts}" fill="{fill}" opacity="{opacity}" stroke="none"/>'


_LIGHT = (-0.445, -0.544, 0.712)  # unit vector, studio light from the upper left


def _diagram_face_up(cx: float, cy: float, layout, w_pp: float, l_pp: float,
                     stroke: str, fill: str, fc: str, facet_w: float,
                     lit: bool, shade_scale: float = 1.0) -> list[str]:
    """Draw a GemCad facet diagram's exact face-up projection at w_pp × l_pp.

    shade_scale tempers the dark facet shading: near-white stones carry their
    structure in crisp facet lines, not gray washes — full-strength black
    overlays on a D-color diamond read as mush, not brilliance.
    """
    def pp(pt):
        return (cx + pt[0] * w_pp, cy + pt[1] * l_pp)

    parts = [_poly([pp(p) for p in layout.outline], fill, stroke, STROKE_MAIN)]
    if lit:  # true per-facet shading: brightness from the real facet normal
        for fct in layout.facets:
            b = sum(n * l for n, l in zip(fct.normal, _LIGHT))
            if b > 0.60:
                parts.append(_lit_poly([pp(p) for p in fct.points], "#ffffff",
                                       round(min((b - 0.60) * 0.55, 0.30), 3)))
            elif b < 0.55:
                opacity = min((0.55 - b) * 0.45, 0.22) * shade_scale
                if opacity >= 0.01:
                    parts.append(_lit_poly([pp(p) for p in fct.points],
                                           "#000000", round(opacity, 3)))
    for fct in layout.facets:
        parts.append(_poly([pp(p) for p in fct.points], "none", fc, facet_w))
    return parts


def _facet_face_up(cx: float, cy: float, cut_id: str, w_pp: float, l_pp: float,
                   table_ratio: float | None = None, stroke: str = INK,
                   fill: str = "#ffffff", facet_color: str | None = None,
                   facet_w: float = STROKE_DIM, lit: bool = False,
                   shade_scale: float = 1.0) -> list[str]:
    """Face-up outline + facet pattern; w_pp/l_pp are full paper-space extents.

    Cuts with a cached GemCad diagram (data/facet_diagrams/) draw the
    diagram's exact projected geometry — remapped so the drawn table matches
    the spec's table % when one is given. Other cuts use the procedural
    pattern. lit=True adds per-facet light-and-shade polygons (for color
    prototypes) — the technical sheets stay pure linework.
    """
    rx, ry = w_pp / 2, l_pp / 2
    fc = facet_color or stroke
    layout = gemcad.remapped_layout(cut_id, table_ratio)
    if layout is not None:
        return _diagram_face_up(cx, cy, layout, w_pp, l_pp, stroke, fill, fc,
                                facet_w, lit, shade_scale)
    t = 0.55 if table_ratio is None else table_ratio
    fline = lambda a, b: _line(a[0], a[1], b[0], b[1], w=facet_w, color=fc)  # noqa: E731

    if cut_id in BRILLIANT_CUTS:
        parts = [f'<ellipse cx="{cx:.2f}" cy="{cy:.2f}" rx="{rx:.2f}" ry="{ry:.2f}" '
                 f'fill="{fill}" stroke="{stroke}" stroke-width="{STROKE_MAIN}"/>']
        corners = [45 * k for k in range(8)]  # mains on the axes, GIA-diagram style
        table_pts = [_pt(cx, cy, rx * t, ry * t, a) for a in corners]
        r_star = t + 0.38 * (1 - t)
        stars = [_pt(cx, cy, rx * r_star, ry * r_star, a + 22.5) for a in corners]
        girdle = lambda a: _pt(cx, cy, rx, ry, a)  # noqa: E731

        if lit:  # light from the upper left: alternating facets catch and shade
            for k in range(8):
                a, mid = corners[k], corners[k] + 22.5
                parts += [
                    _lit_poly([table_pts[k], table_pts[(k + 1) % 8], stars[k]],
                              "#ffffff", 0.30),
                    _lit_poly([table_pts[k], stars[k - 1], girdle(a), stars[k]],
                              "#ffffff" if k % 2 == 0 else "#000000",
                              0.14 if k % 2 == 0 else 0.08),
                    _lit_poly([stars[k], girdle(a), girdle(mid)], "#ffffff", 0.08),
                    _lit_poly([stars[k], girdle(mid), girdle(corners[(k + 1) % 8])],
                              "#000000", 0.05),
                ]
            parts.append(_lit_poly([table_pts[4], table_pts[5], table_pts[6], (cx, cy)],
                                   "#ffffff", 0.18))  # table sheen toward the light

        parts.append(_poly(table_pts, "none", fc, facet_w))
        for k in range(8):
            a, mid = corners[k], corners[k] + 22.5
            c_a, c_b = table_pts[k], table_pts[(k + 1) % 8]
            parts += [
                fline(c_a, girdle(a)),                        # bezel main
                fline(c_a, stars[k]), fline(c_b, stars[k]),   # star facet
                fline(stars[k], girdle(mid)),                 # upper girdle junction
            ]
        return parts

    if cut_id == "princess":
        outline = [(cx - rx, cy - ry), (cx + rx, cy - ry), (cx + rx, cy + ry), (cx - rx, cy + ry)]
        table = [(cx - rx * t, cy - ry * t), (cx + rx * t, cy - ry * t),
                 (cx + rx * t, cy + ry * t), (cx - rx * t, cy + ry * t)]
        parts = [_poly(outline, fill, stroke, STROKE_MAIN)]
        mids = [(cx, cy - ry), (cx + rx, cy), (cx, cy + ry), (cx - rx, cy)]
        if lit:  # opposing chevron quadrants trade light and shade
            for i in range(4):
                shade = "#ffffff" if i in (0, 3) else "#000000"  # light upper-left
                parts.append(_lit_poly([outline[i], outline[(i + 1) % 4], (cx, cy)],
                                       shade, 0.12 if shade == "#ffffff" else 0.07))
            parts.append(_lit_poly([table[3], table[0], (cx, cy)], "#ffffff", 0.18))
        parts.append(_poly(table, "none", fc, facet_w))
        for i in range(4):
            parts.append(fline(outline[i], table[i]))  # corner mains
        for i, m in enumerate(mids):  # chevrons from edge midpoints to table corners
            parts += [fline(m, table[i - 1]), fline(m, table[i])]
        return parts

    if cut_id in STEP_CUTS or cut_id == "baguette":
        cut_c = 0.18 * w_pp if cut_id != "baguette" else 0.0
        rows = [1.0, t + 0.6 * (1 - t), t + 0.28 * (1 - t), t]

        def octagon_pts(f: float) -> list[tuple[float, float]]:
            hw, hl, c = rx * f, ry * f, cut_c * f
            if c <= 0:
                return [(cx - hw, cy - hl), (cx + hw, cy - hl), (cx + hw, cy + hl), (cx - hw, cy + hl)]
            return [
                (cx - hw + c, cy - hl), (cx + hw - c, cy - hl), (cx + hw, cy - hl + c),
                (cx + hw, cy + hl - c), (cx + hw - c, cy + hl), (cx - hw + c, cy + hl),
                (cx - hw, cy + hl - c), (cx - hw, cy - hl + c),
            ]

        rings = [octagon_pts(f) for f in rows]
        parts = [_poly(rings[0], fill, stroke, STROKE_MAIN)]
        if lit:  # step rows read as alternating bands under the light
            parts += [
                _lit_poly(rings[1], "#000000", 0.06),
                _lit_poly(rings[2], "#ffffff", 0.10),
                _lit_poly(rings[3], "#ffffff", 0.08),
            ]
        parts += [_poly(r, "none", fc, facet_w) for r in rings[1:]]
        for i in range(len(rings[0])):  # corner rays across the step rows
            parts.append(fline(rings[0][i], rings[-1][i]))
        return parts

    # cabochon / rose cut / unknown: smooth dome with a highlight arc
    parts = [f'<ellipse cx="{cx:.2f}" cy="{cy:.2f}" rx="{rx:.2f}" ry="{ry:.2f}" '
             f'fill="{fill}" stroke="{stroke}" stroke-width="{STROKE_MAIN}"/>',
             f'<path d="M {cx - rx * 0.55:.2f} {cy - ry * 0.25:.2f} '
             f'A {rx * 0.6:.2f} {ry * 0.6:.2f} 0 0 1 {cx + rx * 0.25:.2f} {cy - ry * 0.55:.2f}" '
             f'fill="none" stroke="{fc}" stroke-width="{facet_w}"/>']
    return parts


# --- halo ring ---------------------------------------------------------------


def _halo_top_view(spec: Spec, melee, cx: float, cy: float) -> list[str]:
    stone = spec.stone.dimensions_mm
    rx, ry = stone.width / 2 * SCALE, stone.length / 2 * SCALE
    mw = melee.dimensions_mm.width
    mr = mw / 2 * SCALE
    # halo centerline and outer edge (mm -> paper)
    ring_ax = rx + 0.3 * SCALE + mr
    ring_by = ry + 0.3 * SCALE + mr
    oax, oby = ring_ax + mr, ring_by + mr
    halo_w_mm = stone.width + 2 * (0.3 + mw)
    halo_l_mm = stone.length + 2 * (0.3 + mw)

    band_w = spec.band.width_mm * SCALE
    inner = spec.ring_size.inner_diameter_mm * SCALE
    thickness = spec.band.thickness_mm * SCALE
    strip_len = inner + 2 * thickness
    top, bottom = cy - strip_len / 2, cy + strip_len / 2
    left_x, right_x = cx - band_w / 2, cx + band_w / 2

    parts = [
        f'<rect x="{left_x:.2f}" y="{top:.2f}" width="{band_w:.2f}" height="{strip_len:.2f}" '
        f'rx="{band_w / 2:.2f}" fill="url(#hatch)" stroke="{INK}" '
        f'stroke-width="{STROKE_MAIN}"/>',
        _ellipse(cx, cy, oax, oby),  # halo outer edge
    ]
    for i in range(melee.count):
        t = -math.pi / 2 + i * 2 * math.pi / melee.count
        parts.append(_circle(cx + ring_ax * math.cos(t), cy + ring_by * math.sin(t), mr))
    parts += [
        *_facet_face_up(cx, cy, spec.stone.cut, 2 * rx, 2 * ry),  # center stone
        _line(cx, cy - oby - 3, cx, cy + oby + 3, w=STROKE_DIM, color=FAINT, dash="3 1 0.5 1"),
        _line(cx - oax - 3, cy, cx + oax + 3, cy, w=STROKE_DIM, color=FAINT, dash="3 1 0.5 1"),
    ]

    y_dim = cy - oby - 7
    y_dim2 = y_dim - 6
    x_dim = cx + max(oax, band_w / 2) + 8
    x_dim2 = x_dim + 18
    parts += [
        # center stone dims (near), halo outer dims (stacked outside)
        _ext(cx - rx, cy, cx - rx, y_dim - 1), _ext(cx + rx, cy, cx + rx, y_dim - 1),
        *_dim_h(cx - rx, cx + rx, y_dim, f"{_fmt(stone.width)} mm"),
        _ext(cx - oax, cy, cx - oax, y_dim2 - 1), _ext(cx + oax, cy, cx + oax, y_dim2 - 1),
        *_dim_h(cx - oax, cx + oax, y_dim2, f"{_fmt(halo_w_mm)} mm halo"),
        _ext(cx, cy - ry, x_dim + 1, cy - ry), _ext(cx, cy + ry, x_dim + 1, cy + ry),
        *_dim_v(x_dim, cy - ry, cy + ry, f"{_fmt(stone.length)} mm"),
        _ext(cx, cy - oby, x_dim2 + 1, cy - oby), _ext(cx, cy + oby, x_dim2 + 1, cy + oby),
        *_dim_v(x_dim2, cy - oby, cy + oby, f"{_fmt(halo_l_mm)} mm halo"),
        _ext(left_x, bottom - band_w / 2, left_x, bottom + 6),
        _ext(right_x, bottom - band_w / 2, right_x, bottom + 6),
        *_dim_h(left_x, right_x, bottom + 5, f"{_fmt(spec.band.width_mm)} mm"),
        _text(cx, bottom + 14, "TOP VIEW", size=3.6, style=' letter-spacing="1.2"'),
        _text(cx, bottom + 19, f"{melee.count} × ⌀{_fmt(mw)} mm melee, 0.3 mm off center girdle",
              size=2.8, color=FAINT),
    ]
    return parts


def _halo_side_view(spec: Spec, melee, cx: float, cy: float) -> list[str]:
    parts = _side_view(spec, cx, cy)
    # halo melee flank the center stone at girdle height (same construction as _side_view)
    stone = spec.stone.dimensions_mm
    inner_r = spec.ring_size.inner_diameter_mm * SCALE / 2
    outer_r = inner_r + spec.band.thickness_mm * SCALE
    gallery = (spec.setting.gallery_height_mm or 0.0) * SCALE
    span = stone.length * SCALE
    ring_cy = cy  # datum: hoop center, matching _side_view
    y_girdle = ring_cy - outer_r - gallery
    prong_r = (spec.setting.prong_tip_mm or 0.9) * SCALE / 2
    mr = melee.dimensions_mm.width / 2 * SCALE
    for sign in (-1, 1):
        mx = cx + sign * (span / 2 + prong_r + 0.6 + mr)
        parts.append(_circle(mx, y_girdle, mr))
    return parts


def _render_halo(spec: Spec) -> str:
    if spec.stone.cut not in SUPPORTED_CUTS:
        raise SheetUnsupported(
            f"halo center cut '{spec.stone.cut}' not supported; supported: {list(SUPPORTED_CUTS)}"
        )
    _require_ring_sections(spec, "halo ring")
    melee = _find_stone(spec, "halo", "surround")
    if melee is None:
        raise SheetUnsupported("halo_prong needs a side_stones entry with position 'halo'")
    body = (
        _halo_top_view(spec, melee, 56, BASELINE)
        + _front_view(spec, 140, BASELINE, melee=melee)
        + _halo_side_view(spec, melee, 208, BASELINE)
    )
    return _frame(spec, "TECHNICAL SHEET — HALO RING", "3:1", body)


# --- oval station bangle ------------------------------------------------------

BANGLE_SCALE = 2.0
SECTION_SCALE = 6.0


def _bangle_face_view(spec: Spec, cx: float, cy: float) -> list[str]:
    br = spec.bracelet
    s = BANGLE_SCALE
    a_in, b_in = br.inner_length_mm / 2 * s, br.inner_width_mm / 2 * s
    a_out, b_out = a_in + br.thickness_mm * s, b_in + br.thickness_mm * s
    parts = [
        _ellipse(cx, cy, a_out, b_out, fill="url(#hatch)"),
        _ellipse(cx, cy, a_in, b_in),
    ]
    stone = spec.stone
    side = stone.dimensions_mm.width * s
    a_c = (br.inner_length_mm + br.thickness_mm) / 2 * s
    b_c = (br.inner_width_mm + br.thickness_mm) / 2 * s
    for i in range(stone.count):
        t = -math.pi / 2 + i * 2 * math.pi / stone.count
        px, py = cx + a_c * math.cos(t), cy + b_c * math.sin(t)
        angle = math.degrees(math.atan2(b_c * math.cos(t), -a_c * math.sin(t)))
        parts.append(
            f'<rect x="{px - side / 2:.2f}" y="{py - side / 2:.2f}" '
            f'width="{side:.2f}" height="{side:.2f}" fill="#ffffff" stroke="{INK}" '
            f'stroke-width="{STROKE_MAIN}" transform="rotate({angle:.1f} {px:.2f} {py:.2f})"/>'
        )
    parts += [
        _ext(cx - a_in, cy, cx - a_in, cy + 15),
        _ext(cx + a_in, cy, cx + a_in, cy + 15),
        *_dim_h(cx - a_in, cx + a_in, cy + 14, f"{_fmt(br.inner_length_mm)} mm"),
        *_dim_v(cx, cy - b_in, cy + b_in, f"{_fmt(br.inner_width_mm)} mm"),
        _text(cx, cy + b_out + 12, "FACE VIEW", size=3.6, style=' letter-spacing="1.2"'),
        _text(cx, cy + b_out + 17,
              f"{stone.count} × {_fmt(stone.dimensions_mm.width)} mm "
              f"{stone.cut.replace('_', ' ')}, evenly spaced on the band centerline",
              size=2.8, color=FAINT),
    ]
    return parts


def _bangle_section_view(spec: Spec, cx: float, cy: float) -> list[str]:
    br = spec.bracelet
    s = SECTION_SCALE
    w, t = br.width_mm * s, br.thickness_mm * s
    y_face = cy - t / 2
    stone = spec.stone.dimensions_mm
    sw, sd = stone.width * s, stone.depth * s
    parts = [
        f'<rect x="{cx - w / 2:.2f}" y="{y_face:.2f}" width="{w:.2f}" height="{t:.2f}" '
        f'fill="url(#hatch)" stroke="{INK}" stroke-width="{STROKE_MAIN}"/>',
        # station stone in section: crown proud of the face, pavilion recessed
        f'<polygon points="{cx - 0.35 * sw:.2f},{y_face - 0.3 * sd:.2f} '
        f'{cx + 0.35 * sw:.2f},{y_face - 0.3 * sd:.2f} '
        f'{cx + sw / 2:.2f},{y_face:.2f} {cx:.2f},{y_face + 0.7 * sd:.2f} '
        f'{cx - sw / 2:.2f},{y_face:.2f}" '
        f'fill="#ffffff" stroke="{INK}" stroke-width="{STROKE_MAIN}"/>',
        _line(cx - sw / 2, y_face, cx + sw / 2, y_face),
        _ext(cx - sw / 2, y_face, cx - sw / 2, y_face - 0.3 * sd - 6),
        _ext(cx + sw / 2, y_face, cx + sw / 2, y_face - 0.3 * sd - 6),
        *_dim_h(cx - sw / 2, cx + sw / 2, y_face - 0.3 * sd - 5, f"{_fmt(stone.width)} mm"),
        _ext(cx - w / 2, cy + t / 2, cx - w / 2, cy + t / 2 + 7),
        _ext(cx + w / 2, cy + t / 2, cx + w / 2, cy + t / 2 + 7),
        *_dim_h(cx - w / 2, cx + w / 2, cy + t / 2 + 6, f"{_fmt(br.width_mm)} mm"),
        _ext(cx + w / 2, y_face, cx + w / 2 + 7, y_face),
        _ext(cx + w / 2, y_face + t, cx + w / 2 + 7, y_face + t),
        *_dim_v(cx + w / 2 + 6, y_face, y_face + t, f"{_fmt(br.thickness_mm)} mm"),
        _text(cx, cy + t / 2 + 15, "SECTION — 6:1", size=3.6, style=' letter-spacing="1.2"'),
    ]
    return parts


def _render_bangle(spec: Spec) -> str:
    if spec.bracelet is None:
        raise SheetUnsupported("a bangle sheet needs a bracelet section")
    if spec.stone.cut not in BANGLE_STATION_CUTS:
        raise SheetUnsupported(
            f"bangle stations must be a square cut; supported: {list(BANGLE_STATION_CUTS)}"
        )
    body = _bangle_face_view(spec, 95, BASELINE) + _bangle_section_view(spec, 232, BASELINE)
    return _frame(spec, "TECHNICAL SHEET — OVAL STATION BANGLE", "2:1", body)


# --- cluster pendant ----------------------------------------------------------

LINK_GAP_MM = 1.0  # jump-ring gap between bail, cluster, and drop stone


def _pendant_front_view(spec: Spec, melee, drop_stone, cx: float, ty: float) -> list[str]:
    p = spec.pendant
    stone = spec.stone.dimensions_mm
    mw = melee.dimensions_mm.width if melee else 0.0
    surround = (0.3 + mw) if melee else 0.0
    cluster_ax = (stone.width / 2 + surround) * SCALE
    cluster_by = (stone.length / 2 + surround) * SCALE

    bail_r = p.bail_height_mm / 2 * SCALE
    bail_cy = ty + bail_r
    cluster_cy = ty + (p.bail_height_mm + LINK_GAP_MM) * SCALE + cluster_by
    cluster_bottom = cluster_cy + cluster_by
    parts = [
        _circle(cx, bail_cy, bail_r),
        _circle(cx, bail_cy, p.bail_inner_diameter_mm / 2 * SCALE),
        _circle(cx, ty + (p.bail_height_mm + LINK_GAP_MM / 2) * SCALE, LINK_GAP_MM / 2 * SCALE),
    ]
    hw, hl = stone.width / 2 * SCALE, stone.length / 2 * SCALE
    if melee:
        ring_ax = hw + 0.3 * SCALE + mw / 2 * SCALE
        ring_by = hl + 0.3 * SCALE + mw / 2 * SCALE
        for i in range(melee.count):
            t = -math.pi / 2 + i * 2 * math.pi / melee.count
            parts.append(_circle(cx + ring_ax * math.cos(t), cluster_cy + ring_by * math.sin(t),
                                 mw / 2 * SCALE))
    parts += _facet_face_up(cx, cluster_cy, spec.stone.cut, 2 * hw, 2 * hl, table_ratio=0.62)

    bottom = cluster_bottom
    if drop_stone:
        sw = drop_stone.dimensions_mm.width * SCALE
        sap_cy = cluster_bottom + LINK_GAP_MM * SCALE + sw / 2
        parts += [
            _circle(cx, cluster_bottom + LINK_GAP_MM / 2 * SCALE, LINK_GAP_MM / 2 * SCALE),
            _circle(cx, sap_cy, sw / 2),
            f'<circle cx="{cx:.2f}" cy="{sap_cy:.2f}" r="{sw / 2 * 0.55:.2f}" fill="none" '
            f'stroke="{FAINT}" stroke-width="{STROKE_DIM}" stroke-dasharray="1 0.8"/>',
        ]
        bottom = sap_cy + sw / 2

    drop_mm = p.drop_mm if p.drop_mm is not None else (bottom - ty) / SCALE
    x_dim = cx + max(cluster_ax, bail_r) + 10
    x_dim2 = x_dim + 18
    y_dim = ty - 5  # center-width dim sits above the bail, clear of the drawing
    parts += [
        _line(cx, ty - 3, cx, bottom + 3, w=STROKE_DIM, color=FAINT, dash="3 1 0.5 1"),
        # center stone dims
        _ext(cx - hw, cluster_cy, cx - hw, y_dim - 1), _ext(cx + hw, cluster_cy, cx + hw, y_dim - 1),
        *_dim_h(cx - hw, cx + hw, y_dim, f"{_fmt(stone.width)} mm"),
        _ext(cx, cluster_cy - hl, x_dim + 1, cluster_cy - hl),
        _ext(cx, cluster_cy + hl, x_dim + 1, cluster_cy + hl),
        *_dim_v(x_dim, cluster_cy - hl, cluster_cy + hl, f"{_fmt(stone.length)} mm"),
        # overall drop
        _ext(cx, ty, x_dim2 + 1, ty), _ext(cx, bottom, x_dim2 + 1, bottom),
        *_dim_v(x_dim2, ty, bottom, f"{_fmt(drop_mm)} mm drop"),
        _text(cx + bail_r + 3, bail_cy + 1,
              f"bail ⌀{_fmt(p.bail_inner_diameter_mm)} mm inside", size=2.8, anchor="start",
              color=FAINT),
        _text(cx, bottom + 12, "FRONT VIEW", size=3.6, style=' letter-spacing="1.2"'),
    ]
    if melee:
        parts.append(_text(cx, bottom + 17,
                           f"{melee.count} × ⌀{_fmt(mw)} mm melee around center",
                           size=2.8, color=FAINT))
    if drop_stone:
        sw_mm = drop_stone.dimensions_mm.width
        sap_cy = cluster_bottom + LINK_GAP_MM * SCALE + sw_mm * SCALE / 2
        parts += [
            _ext(cx - sw_mm / 2 * SCALE, sap_cy, cx - sw_mm / 2 * SCALE, bottom + 6),
            _ext(cx + sw_mm / 2 * SCALE, sap_cy, cx + sw_mm / 2 * SCALE, bottom + 6),
            *_dim_h(cx - sw_mm / 2 * SCALE, cx + sw_mm / 2 * SCALE, bottom + 5,
                    f"⌀ {_fmt(sw_mm)} mm"),
        ]
    return parts


def _pendant_side_view(spec: Spec, melee, drop_stone, cx: float, ty: float) -> list[str]:
    """Side silhouettes at the same heights as the front view, with depth dims."""
    p = spec.pendant
    stone = spec.stone.dimensions_mm
    mw = melee.dimensions_mm.width if melee else 0.0
    surround = (0.3 + mw) if melee else 0.0
    cluster_by = (stone.length / 2 + surround) * SCALE
    bail_w = 1.2 * SCALE
    parts = [
        f'<rect x="{cx - bail_w / 2:.2f}" y="{ty:.2f}" width="{bail_w:.2f}" '
        f'height="{p.bail_height_mm * SCALE:.2f}" fill="#ffffff" stroke="{INK}" '
        f'stroke-width="{STROKE_MAIN}"/>',
    ]
    cluster_cy = ty + (p.bail_height_mm + LINK_GAP_MM) * SCALE + cluster_by
    d = stone.depth * SCALE
    hl = stone.length / 2 * SCALE
    girdle_x = cx - d / 2 + 0.3 * d  # table faces front (left)
    parts += [
        f'<rect x="{cx - d / 2:.2f}" y="{cluster_cy - hl:.2f}" width="{d:.2f}" '
        f'height="{2 * hl:.2f}" fill="#ffffff" stroke="{INK}" stroke-width="{STROKE_MAIN}"/>',
        _line(girdle_x, cluster_cy - hl, girdle_x, cluster_cy + hl, w=STROKE_DIM, color=FAINT),
        _ext(cx - d / 2, cluster_cy + hl, cx - d / 2, cluster_cy + hl + 6),
        _ext(cx + d / 2, cluster_cy + hl, cx + d / 2, cluster_cy + hl + 6),
        *_dim_h(cx - d / 2, cx + d / 2, cluster_cy + hl + 5, f"{_fmt(stone.depth)} mm"),
    ]
    bottom = cluster_cy + cluster_by
    if drop_stone:
        sd = drop_stone.dimensions_mm.depth * SCALE
        sw = drop_stone.dimensions_mm.width * SCALE
        sap_cy = bottom + LINK_GAP_MM * SCALE + sw / 2
        sap_girdle_x = cx - sd / 2 + 0.35 * sd
        parts += [
            f'<rect x="{cx - sd / 2:.2f}" y="{sap_cy - sw / 2:.2f}" width="{sd:.2f}" '
            f'height="{sw:.2f}" fill="#ffffff" stroke="{INK}" stroke-width="{STROKE_MAIN}"/>',
            _line(sap_girdle_x, sap_cy - sw / 2, sap_girdle_x, sap_cy + sw / 2,
                  w=STROKE_DIM, color=FAINT),
            _ext(cx - sd / 2, sap_cy + sw / 2, cx - sd / 2, sap_cy + sw / 2 + 6),
            _ext(cx + sd / 2, sap_cy + sw / 2, cx + sd / 2, sap_cy + sw / 2 + 6),
            *_dim_h(cx - sd / 2, cx + sd / 2, sap_cy + sw / 2 + 5,
                    f"{_fmt(drop_stone.dimensions_mm.depth)} mm"),
        ]
        bottom = sap_cy + sw / 2
    parts += [
        _line(cx, ty - 3, cx, bottom + 3, w=STROKE_DIM, color=FAINT, dash="3 1 0.5 1"),
        _text(cx, bottom + 12, "SIDE PROFILE", size=3.6, style=' letter-spacing="1.2"'),
    ]
    return parts


def _render_pendant(spec: Spec) -> str:
    if spec.pendant is None:
        raise SheetUnsupported("a pendant sheet needs a pendant section")
    if spec.stone.cut not in PENDANT_CENTER_CUTS:
        raise SheetUnsupported(
            f"pendant center cut '{spec.stone.cut}' not supported; "
            f"supported: {list(PENDANT_CENTER_CUTS)}"
        )
    melee = _find_stone(spec, "halo", "surround")
    drop_stone = _find_stone(spec, "under_center", "drop")
    # center the whole drop on the shared baseline
    ty = BASELINE - pendant_drop_mm(spec) * SCALE / 2
    body = (
        _pendant_front_view(spec, melee, drop_stone, 100, ty)
        + _pendant_side_view(spec, melee, drop_stone, 225, ty)
    )
    title = "TECHNICAL SHEET — CLUSTER PENDANT"
    if spec.chain is not None:
        title = "TECHNICAL SHEET — PENDANT NECKLACE"
        body += _chain_callout(spec, 100, ty)
    return _frame(spec, title, "3:1", body)


def _chain_callout(spec: Spec, cx: float, bail_top_y: float) -> list[str]:
    """Chain stubs leaving the bail plus the chain/clasp data block (the chain
    itself is data, not drawn to scale)."""
    chain = spec.chain
    parts = []
    for sign in (-1, 1):
        for i in range(1, 4):  # three fading links up each side
            r = 1.4 - i * 0.25
            parts.append(_circle(cx + sign * i * 2.6, bail_top_y - 1.4 - i * 2.2, r))
    parts += [
        _text(MARGIN + 6, 26, "CHAIN", size=3.4, anchor="start", style=' letter-spacing="1.2"'),
        _text(MARGIN + 6, 31,
              f"{chain.style.replace('_', ' ')} · {_fmt(chain.length_mm)} mm · "
              f"{chain.clasp.replace('_', ' ')} clasp",
              size=3.0, anchor="start", color=FAINT),
    ]
    return parts


# --- open cuff ----------------------------------------------------------------


def _cuff_face_view(spec: Spec, cx: float, cy: float) -> list[str]:
    br = spec.bracelet
    s = BANGLE_SCALE
    a_in, b_in = br.inner_length_mm / 2 * s, br.inner_width_mm / 2 * s
    a_out, b_out = a_in + br.thickness_mm * s, b_in + br.thickness_mm * s
    a_c = (br.inner_length_mm + br.thickness_mm) / 2 * s
    b_c = (br.inner_width_mm + br.thickness_mm) / 2 * s

    # gap centered at the bottom: tips at parameter pi/2 +/- delta
    delta = math.asin(min(1.0, br.gap_width_mm * s / (2 * a_c)))
    t1, t2 = math.pi / 2 + delta, math.pi / 2 - delta

    def pt(a: float, b: float, t: float) -> tuple[float, float]:
        return cx + a * math.cos(t), cy + b * math.sin(t)

    o1, o2 = pt(a_out, b_out, t1), pt(a_out, b_out, t2)
    i1, i2 = pt(a_in, b_in, t1), pt(a_in, b_in, t2)
    c1, c2 = pt(a_c, b_c, t1), pt(a_c, b_c, t2)
    path = (
        f'<path d="M {o1[0]:.2f} {o1[1]:.2f} '
        f'A {a_out:.2f} {b_out:.2f} 0 1 1 {o2[0]:.2f} {o2[1]:.2f} '
        f'L {i2[0]:.2f} {i2[1]:.2f} '
        f'A {a_in:.2f} {b_in:.2f} 0 1 0 {i1[0]:.2f} {i1[1]:.2f} Z" '
        f'fill="url(#hatch)" stroke="{INK}" stroke-width="{STROKE_MAIN}"/>'
    )
    parts = [path]

    stone = spec.stone
    if stone.position == "stations":
        side = stone.dimensions_mm.width * s
        pad = delta + 0.35
        t0, t_end = math.pi / 2 + pad, math.pi / 2 - pad + 2 * math.pi
        for i in range(stone.count):
            t = t0 + (t_end - t0) * i / max(1, stone.count - 1)
            px, py = pt(a_c, b_c, t)
            angle = math.degrees(math.atan2(b_c * math.cos(t), -a_c * math.sin(t)))
            parts.append(
                f'<rect x="{px - side / 2:.2f}" y="{py - side / 2:.2f}" '
                f'width="{side:.2f}" height="{side:.2f}" fill="#ffffff" stroke="{INK}" '
                f'stroke-width="{STROKE_MAIN}" transform="rotate({angle:.1f} {px:.2f} {py:.2f})"/>'
            )

    gap_y = max(o1[1], o2[1]) + 6
    parts += [
        _ext(cx - a_in, cy, cx - a_in, cy + 15),
        _ext(cx + a_in, cy, cx + a_in, cy + 15),
        *_dim_h(cx - a_in, cx + a_in, cy + 14, f"{_fmt(br.inner_length_mm)} mm"),
        *_dim_v(cx, cy - b_in, cy + b_in, f"{_fmt(br.inner_width_mm)} mm"),
        _ext(c1[0], c1[1], c1[0], gap_y + 1), _ext(c2[0], c2[1], c2[0], gap_y + 1),
        *_dim_h(c1[0], c2[0], gap_y, f"{_fmt(br.gap_width_mm)} mm gap"),
        _text(cx, cy + b_out + 16, "FACE VIEW", size=3.6, style=' letter-spacing="1.2"'),
    ]
    if stone.position == "stations":
        parts.append(_text(cx, cy + b_out + 21,
                           f"{stone.count} × {_fmt(stone.dimensions_mm.width)} mm "
                           f"{stone.cut.replace('_', ' ')} on the arc",
                           size=2.8, color=FAINT))
    return parts


def _render_cuff(spec: Spec) -> str:
    if spec.bracelet is None or spec.bracelet.gap_width_mm is None:
        raise SheetUnsupported("a cuff sheet needs a bracelet section with gap_width_mm")
    if spec.stone.cut not in BANGLE_STATION_CUTS:
        raise SheetUnsupported(
            f"cuff stations must be a square cut; supported: {list(BANGLE_STATION_CUTS)}"
        )
    body = _cuff_face_view(spec, 95, BASELINE) + _bangle_section_view(spec, 232, BASELINE)
    return _frame(spec, "TECHNICAL SHEET — OPEN CUFF", "2:1", body)


# --- articulated link bracelet --------------------------------------------------


def _link_face_view(spec: Spec, cx: float, cy: float) -> list[str]:
    br = spec.bracelet
    s = BANGLE_SCALE
    a_in, b_in = br.inner_length_mm / 2 * s, br.inner_width_mm / 2 * s
    a_c = (br.inner_length_mm + br.thickness_mm) / 2 * s
    b_c = (br.inner_width_mm + br.thickness_mm) / 2 * s
    n = br.link_count
    pitch_mm = ellipse_perimeter_mm(a_c / s, b_c / s) / n
    link_l, link_w = pitch_mm * 0.82 * s, br.width_mm * s

    # the wrist opening the links articulate around — the boundary the
    # inner-diameter dimensions anchor on
    parts = [
        f'<ellipse cx="{cx:.2f}" cy="{cy:.2f}" rx="{a_in:.2f}" ry="{b_in:.2f}" '
        f'fill="none" stroke="{FAINT}" stroke-width="{STROKE_DIM}"/>',
    ]
    stone = spec.stone
    stone_side = stone.dimensions_mm.width * s
    stone_every = max(1, round(n / stone.count)) if stone.position == "stations" else 0
    stones_drawn = 0
    for i in range(n):
        t = -math.pi / 2 + i * 2 * math.pi / n
        px, py = cx + a_c * math.cos(t), cy + b_c * math.sin(t)
        angle = math.degrees(math.atan2(b_c * math.cos(t), -a_c * math.sin(t)))
        parts.append(
            f'<rect x="{px - link_l / 2:.2f}" y="{py - link_w / 2:.2f}" '
            f'width="{link_l:.2f}" height="{link_w:.2f}" rx="1.6" fill="#ffffff" '
            f'stroke="{INK}" stroke-width="{STROKE_MAIN}" '
            f'transform="rotate({angle:.1f} {px:.2f} {py:.2f})"/>'
        )
        if stone_every and i % stone_every == 0 and stones_drawn < stone.count:
            stones_drawn += 1
            parts.append(
                f'<rect x="{px - stone_side / 2:.2f}" y="{py - stone_side / 2:.2f}" '
                f'width="{stone_side:.2f}" height="{stone_side:.2f}" fill="#ffffff" '
                f'stroke="{INK}" stroke-width="{STROKE_MAIN}" '
                f'transform="rotate({angle + 45:.1f} {px:.2f} {py:.2f})"/>'
            )
    parts += [
        _ext(cx - a_in, cy, cx - a_in, cy + 15),
        _ext(cx + a_in, cy, cx + a_in, cy + 15),
        *_dim_h(cx - a_in, cx + a_in, cy + 14, f"{_fmt(br.inner_length_mm)} mm"),
        *_dim_v(cx, cy - b_in, cy + b_in, f"{_fmt(br.inner_width_mm)} mm"),
        _text(cx, cy + b_c + link_w / 2 + 12, "FACE VIEW", size=3.6, style=' letter-spacing="1.2"'),
        _text(cx, cy + b_c + link_w / 2 + 17,
              f"{n} articulated links · pitch {pitch_mm:.1f} mm on the centerline",
              size=2.8, color=FAINT),
    ]
    return parts


def _link_detail_view(spec: Spec, cx: float, cy: float) -> list[str]:
    """One link at 6:1 with its pitch, width, and stone seat."""
    br = spec.bracelet
    s = SECTION_SCALE
    a_c = (br.inner_length_mm + br.thickness_mm) / 2
    b_c = (br.inner_width_mm + br.thickness_mm) / 2
    pitch_mm = ellipse_perimeter_mm(a_c, b_c) / br.link_count
    link_l, link_w = pitch_mm * 0.82 * s, br.width_mm * s
    x0 = cx - pitch_mm * s / 2
    next_x0 = x0 + pitch_mm * s

    parts = [
        f'<rect x="{x0:.2f}" y="{cy - link_w / 2:.2f}" width="{link_l:.2f}" '
        f'height="{link_w:.2f}" rx="3" fill="#ffffff" stroke="{INK}" '
        f'stroke-width="{STROKE_MAIN}"/>',
        # phantom start of the next link marks the pitch
        f'<rect x="{next_x0:.2f}" y="{cy - link_w / 2:.2f}" width="{link_l * 0.25:.2f}" '
        f'height="{link_w:.2f}" rx="3" fill="none" stroke="{FAINT}" '
        f'stroke-width="{STROKE_DIM}" stroke-dasharray="1.2 1"/>',
        _ext(x0, cy - link_w / 2, x0, cy - link_w / 2 - 7),
        _ext(next_x0, cy - link_w / 2, next_x0, cy - link_w / 2 - 7),
        *_dim_h(x0, next_x0, cy - link_w / 2 - 6, f"pitch {pitch_mm:.1f} mm"),
        _ext(x0, cy - link_w / 2, x0 - 7, cy - link_w / 2),
        _ext(x0, cy + link_w / 2, x0 - 7, cy + link_w / 2),
        *_dim_v(x0 - 6, cy - link_w / 2, cy + link_w / 2, f"{_fmt(br.width_mm)} mm"),
    ]
    stone = spec.stone
    if stone.position == "stations":
        side = stone.dimensions_mm.width * s
        sx, sy = x0 + link_l / 2, cy
        parts += [
            f'<rect x="{sx - side / 2:.2f}" y="{sy - side / 2:.2f}" width="{side:.2f}" '
            f'height="{side:.2f}" fill="#ffffff" stroke="{INK}" '
            f'stroke-width="{STROKE_MAIN}" transform="rotate(45 {sx:.2f} {sy:.2f})"/>',
            _text(cx, cy + link_w / 2 + 20,
                  f"{_fmt(stone.dimensions_mm.width)} mm {stone.cut.replace('_', ' ')} seat, "
                  f"every {max(1, round(br.link_count / stone.count))} links",
                  size=2.8, color=FAINT),
        ]
    parts.append(_text(cx, cy + link_w / 2 + 15, "LINK DETAIL — 6:1",
                       size=3.6, style=' letter-spacing="1.2"'))
    if spec.chain is not None:
        parts.append(_text(cx, cy + link_w / 2 + 25,
                           f"closure: {spec.chain.clasp.replace('_', ' ')} clasp",
                           size=2.8, color=FAINT))
    return parts


def _render_link_bracelet(spec: Spec) -> str:
    if spec.bracelet is None or spec.bracelet.link_count is None:
        raise SheetUnsupported("a link-bracelet sheet needs a bracelet section with link_count")
    body = _link_face_view(spec, 95, BASELINE) + _link_detail_view(spec, 232, BASELINE)
    return _frame(spec, "TECHNICAL SHEET — LINK BRACELET", "2:1", body)


# --- loose stone / gem ID -------------------------------------------------------

GEM_SCALES = (10.0, 8.0, 6.0, 4.0, 3.0)


def _gem_scale(spec: Spec) -> float:
    d = spec.stone.dimensions_mm
    for s in GEM_SCALES:
        if max(d.length, d.width) * s <= 70 and d.depth * s <= 55:
            return s
    return GEM_SCALES[-1]


def _gem_face_view(spec: Spec, cx: float, cy: float, s: float) -> list[str]:
    stone = spec.stone
    d = stone.dimensions_mm
    hw, hl = d.width / 2 * s, d.length / 2 * s
    table_ratio = (stone.table_pct or 57) / 100
    parts = _facet_face_up(cx, cy, stone.cut, 2 * hw, 2 * hl, table_ratio=table_ratio)
    table_w_mm = d.width * table_ratio
    y_dim = cy - hl - 7
    parts += [
        _line(cx, cy - hl - 3, cx, cy + hl + 3, w=STROKE_DIM, color=FAINT, dash="3 1 0.5 1"),
        _line(cx - hw - 3, cy, cx + hw + 3, cy, w=STROKE_DIM, color=FAINT, dash="3 1 0.5 1"),
        _ext(cx - hw * table_ratio, cy, cx - hw * table_ratio, y_dim - 1),
        _ext(cx + hw * table_ratio, cy, cx + hw * table_ratio, y_dim - 1),
        *_dim_h(cx - hw * table_ratio, cx + hw * table_ratio, y_dim,
                f"table {_fmt(stone.table_pct or 57)}% = {table_w_mm:.2f} mm"),
        _ext(cx - hw, cy, cx - hw, cy + hl + 7), _ext(cx + hw, cy, cx + hw, cy + hl + 7),
        *_dim_h(cx - hw, cx + hw, cy + hl + 6, f"{_fmt(d.width)} mm"),
        _ext(cx, cy - hl, cx + hw + 8, cy - hl), _ext(cx, cy + hl, cx + hw + 8, cy + hl),
        *_dim_v(cx + hw + 7, cy - hl, cy + hl, f"{_fmt(d.length)} mm"),
        _text(cx, cy + hl + 16, "FACE UP", size=3.6, style=' letter-spacing="1.2"'),
    ]
    return parts


def _profile_facets(cut_id: str, cx: float, span: float, y_top: float,
                    y_g1: float, y_g2: float, y_culet: float) -> list[str]:
    """Faint facet-junction lines inside the profile outline (Gem ID sheets).

    The diagram's crown heights map onto the drawn crown band and pavilion
    heights onto the drawn pavilion band, so the junctions stay honest to the
    spec's proportions even when the design's native split differs."""
    prof = gemcad.profile_layout(cut_id)
    if prof is None:
        return []
    parts = []
    crown_span = prof.z_table - prof.z_crown_base or 1.0
    pav_span = prof.z_pav_top - prof.z_culet or 1.0
    for polys, y_base, y_far, z_base, z_span in (
        (prof.crown, y_g1, y_top, prof.z_crown_base, crown_span),
        (prof.pavilion, y_g2, y_culet, prof.z_pav_top, -pav_span),
    ):
        for poly in polys:
            pts = [(cx + xn * span,
                    y_base + (z - z_base) / z_span * (y_far - y_base))
                   for xn, z in poly]
            parts.append(_poly(pts, "none", FAINT, STROKE_DIM))
    return parts


def _gem_profile_view(spec: Spec, cx: float, cy: float, s: float) -> list[str]:
    stone = spec.stone
    d = stone.dimensions_mm
    span = d.width * s
    depth = d.depth * s
    girdle_t = max(0.6, 0.02 * d.width * s)  # drawn girdle band
    # GIA-typical split: crown ~26% of total depth, pavilion the rest
    crown_h = 0.26 * depth - girdle_t / 2
    pavilion_h = depth - 0.26 * depth - girdle_t / 2
    table_w = span * ((stone.table_pct or 57) / 100)

    y_top = cy - depth / 2
    y_g1 = y_top + crown_h
    y_g2 = y_g1 + girdle_t
    y_culet = y_g2 + pavilion_h
    xl, xr = cx - span / 2, cx + span / 2
    txl, txr = cx - table_w / 2, cx + table_w / 2
    parts = [
        f'<polygon points="{txl:.2f},{y_top:.2f} {txr:.2f},{y_top:.2f} '
        f'{xr:.2f},{y_g1:.2f} {xl:.2f},{y_g1:.2f}" '
        f'fill="#ffffff" stroke="{INK}" stroke-width="{STROKE_MAIN}"/>',
        f'<rect x="{xl:.2f}" y="{y_g1:.2f}" width="{span:.2f}" height="{girdle_t:.2f}" '
        f'fill="#ffffff" stroke="{INK}" stroke-width="{STROKE_MAIN}"/>',
        f'<polygon points="{xl:.2f},{y_g2:.2f} {xr:.2f},{y_g2:.2f} {cx:.2f},{y_culet:.2f}" '
        f'fill="#ffffff" stroke="{INK}" stroke-width="{STROKE_MAIN}"/>',
        # true facet junctions from the cut's diagram, seen in side elevation —
        # remapped so they land inside the spec-true crown and pavilion bands
        *_profile_facets(stone.cut, cx, span, y_top, y_g1, y_g2, y_culet),
        _line(cx, y_top - 3, cx, y_culet + 3, w=STROKE_DIM, color=FAINT, dash="3 1 0.5 1"),
        _ext(txr, y_top, cx + span / 2 + 8, y_top),
        _ext(cx, y_culet, cx + span / 2 + 8, y_culet),
        *_dim_v(cx + span / 2 + 7, y_top, y_culet,
                f"{_fmt(d.depth)} mm ({_fmt(stone.depth_pct or round(d.depth / d.width * 100, 1))}%)"),
    ]
    # GIA proportion callouts: crown and pavilion angles from the drawn geometry
    crown_angle = math.degrees(math.atan2(crown_h, (span - table_w) / 2))
    pavilion_angle = math.degrees(math.atan2(pavilion_h, span / 2))
    parts += [
        _ext((txr + xr) / 2, (y_top + y_g1) / 2, xr + 5, y_top - 4),
        _text(xr + 5.6, y_top - 3, f"crown {crown_angle:.1f}°", size=2.8, anchor="start",
              color=FAINT),
        _ext((xr + cx) / 2, (y_g2 + y_culet) / 2, xl - 5, y_culet + 2),
        _text(xl - 5.6, y_culet + 3, f"pavilion {pavilion_angle:.1f}°", size=2.8, anchor="end",
              color=FAINT),
    ]
    if stone.girdle:
        parts += [
            _ext(xl, (y_g1 + y_g2) / 2, xl - 6, (y_g1 + y_g2) / 2),
            _text(xl - 7, (y_g1 + y_g2) / 2 + 1, f"girdle: {stone.girdle.replace('_', ' ')}",
                  size=2.8, anchor="end", color=FAINT),
        ]
    if stone.inscription:
        lab = f"{stone.lab} " if stone.lab else ""
        parts += [
            _ext(xr, (y_g1 + y_g2) / 2, cx + span * 0.3, y_culet + 15.5),
            _text(cx, y_culet + 17,
                  f'laser inscription on girdle: {lab}"{stone.inscription}"',
                  size=2.8),
        ]
    parts.append(_text(cx, y_culet + 12, "PROFILE", size=3.6, style=' letter-spacing="1.2"'))
    return parts


def _render_loose_stone(spec: Spec) -> str:
    s = _gem_scale(spec)
    stone = spec.stone
    d = stone.dimensions_mm
    data_lines = [
        f"{_fmt(d.length)} × {_fmt(d.width)} × {_fmt(d.depth)} mm",
        f"{stone.carat:.2f} ct {stone.species}, {stone.cut.replace('_', ' ')}",
        f"table {_fmt(stone.table_pct)}%" if stone.table_pct else None,
        f"depth {_fmt(stone.depth_pct)}%" if stone.depth_pct else None,
        f"girdle {stone.girdle.replace('_', ' ')}" if stone.girdle else None,
        f"culet {(stone.culet or 'pointed').replace('_', ' ')}",
        f"clarity {stone.clarity.grade} ({stone.clarity.system})" if stone.clarity else None,
        f"origin {stone.origin}" if stone.origin else None,
    ]
    parts = [_text(MARGIN + 6, 26, "GEM DATA", size=3.4, anchor="start",
                   style=' letter-spacing="1.2"')]
    y = 31
    for line in data_lines:
        if line:
            parts.append(_text(MARGIN + 6, y, line, size=3.0, anchor="start", color=FAINT))
            y += 4.6
    body = parts + _gem_face_view(spec, 110, BASELINE, s) + _gem_profile_view(spec, 208, BASELINE, s)
    return _frame(spec, "GEM IDENTIFICATION — LOOSE STONE", f"{s:g}:1", body)


TEMPLATES = {
    "solitaire_prong": _render_solitaire,
    "halo_prong": _render_halo,
    "love_bangle": _render_bangle,
    "cluster_pendant": _render_pendant,
    "cuff": _render_cuff,
    "link_bracelet": _render_link_bracelet,
    "loose_stone": _render_loose_stone,
}


def render_sheet(spec: Spec) -> str:
    """Render the annotated technical sheet for a validated spec."""
    render = TEMPLATES.get(spec.template)
    if render is None:
        raise SheetUnsupported(
            f"template '{spec.template}' not supported yet; supported: {list(TEMPLATES)}"
        )
    return render(spec)


# --- stacking overlay -----------------------------------------------------------


def _stack_bangles(spec_a: Spec, spec_b: Spec, clearance: NestingClearance,
                   cx: float, cy: float) -> list[str]:
    s = BANGLE_SCALE
    # draw the larger piece in ink, the nested piece in accent
    outer, inner = sorted(
        (spec_a, spec_b),
        key=lambda sp: sp.bracelet.inner_length_mm + 2 * sp.bracelet.thickness_mm,
        reverse=True,
    )
    parts = []
    for sp, color in ((outer, INK), (inner, ACCENT)):
        br = sp.bracelet
        a_in, b_in = br.inner_length_mm / 2 * s, br.inner_width_mm / 2 * s
        a_out, b_out = a_in + br.thickness_mm * s, b_in + br.thickness_mm * s
        for a, b in ((a_out, b_out), (a_in, b_in)):
            parts.append(
                f'<ellipse cx="{cx:.2f}" cy="{cy:.2f}" rx="{a:.2f}" ry="{b:.2f}" '
                f'fill="none" stroke="{color}" stroke-width="{STROKE_MAIN}"/>'
            )
    a_in_outer = outer.bracelet.inner_length_mm / 2 * s
    b_in_outer = outer.bracelet.inner_width_mm / 2 * s
    a_env_inner = (inner.bracelet.inner_length_mm / 2 + inner.bracelet.thickness_mm) * s
    b_env_inner = (inner.bracelet.inner_width_mm / 2 + inner.bracelet.thickness_mm) * s
    parts += [
        # per-axis clearance between the outer piece's opening and the inner piece's envelope
        _ext(cx + a_env_inner, cy, cx + a_env_inner, cy - 8),
        _ext(cx + a_in_outer, cy, cx + a_in_outer, cy - 8),
        *_dim_h(cx + a_env_inner, cx + a_in_outer, cy - 7,
                f"{_fmt(clearance.clearance_x_mm)} mm"),
        _ext(cx, cy - b_env_inner, cx + 8, cy - b_env_inner),
        _ext(cx, cy - b_in_outer, cx + 8, cy - b_in_outer),
        *_dim_v(cx + 7, cy - b_in_outer, cy - b_env_inner,
                f"{_fmt(clearance.clearance_y_mm)} mm"),
        _text(cx, cy + (outer.bracelet.inner_width_mm / 2 + outer.bracelet.thickness_mm) * s + 12,
              "NESTED FACE VIEW", size=3.6, style=' letter-spacing="1.2"'),
    ]
    return parts


def _stack_rings(spec_a: Spec, spec_b: Spec, clearance: NestingClearance,
                 cx: float, cy: float) -> list[str]:
    parts = []
    radii = []
    for sp, color in ((spec_a, INK), (spec_b, ACCENT)):
        inner_r = sp.ring_size.inner_diameter_mm * SCALE / 2
        outer_r = inner_r + sp.band.thickness_mm * SCALE
        radii.append(outer_r)
        for r in (inner_r, outer_r):
            parts.append(
                f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}" '
                f'fill="none" stroke="{color}" stroke-width="{STROKE_MAIN}"/>'
            )
    r_max = max(radii)
    # stack section: the two band profiles side by side, as worn along the finger
    sx = cx + r_max + 40
    w_a, w_b = spec_a.band.width_mm * SECTION_SCALE, spec_b.band.width_mm * SECTION_SCALE
    t_a, t_b = spec_a.band.thickness_mm * SECTION_SCALE, spec_b.band.thickness_mm * SECTION_SCALE
    x_a = sx - (w_a + w_b) / 2
    parts += [
        f'<rect x="{x_a:.2f}" y="{cy - t_a / 2:.2f}" width="{w_a:.2f}" height="{t_a:.2f}" '
        f'fill="url(#hatch)" stroke="{INK}" stroke-width="{STROKE_MAIN}"/>',
        f'<rect x="{x_a + w_a:.2f}" y="{cy - t_b / 2:.2f}" width="{w_b:.2f}" height="{t_b:.2f}" '
        f'fill="url(#hatch)" stroke="{ACCENT}" stroke-width="{STROKE_MAIN}"/>',
        _ext(x_a, cy - max(t_a, t_b) / 2, x_a, cy - max(t_a, t_b) / 2 - 7),
        _ext(x_a + w_a + w_b, cy - max(t_a, t_b) / 2, x_a + w_a + w_b, cy - max(t_a, t_b) / 2 - 7),
        *_dim_h(x_a, x_a + w_a + w_b, cy - max(t_a, t_b) / 2 - 6,
                f"stack {_fmt(clearance.stack_height_mm)} mm"),
        _text(sx, cy + max(t_a, t_b) / 2 + 12, "STACK SECTION — 6:1",
              size=3.6, style=' letter-spacing="1.2"'),
        _text(cx, cy + r_max + 12, "ON-FINGER PROFILE", size=3.6, style=' letter-spacing="1.2"'),
        _text(cx, cy + r_max + 17,
              f"inner ⌀ {_fmt(spec_a.ring_size.inner_diameter_mm)} / "
              f"{_fmt(spec_b.ring_size.inner_diameter_mm)} mm — "
              f"Δ {_fmt(clearance.diameter_delta_mm)} mm", size=2.8, color=FAINT),
    ]
    return parts


def render_stack_sheet(spec_a: Spec, spec_b: Spec, clearance: NestingClearance) -> str:
    """Overlay two pieces on a shared axis with their nesting clearance."""
    if clearance.kind == "bangle_in_bangle":
        body = _stack_bangles(spec_a, spec_b, clearance, 118, BASELINE)
        scale_label = "2:1"
    else:
        body = _stack_rings(spec_a, spec_b, clearance, 100, BASELINE)
        scale_label = "3:1"
    body += [
        _text(MARGIN + 6, 26, "PIECES", size=3.4, anchor="start", style=' letter-spacing="1.2"'),
        _text(MARGIN + 6, 31, f"A — {spec_a.design_id} v{spec_a.version}",
              size=3.0, anchor="start"),
        _text(MARGIN + 6, 35.6, f"B — {spec_b.design_id} v{spec_b.version}",
              size=3.0, anchor="start", color=ACCENT),
    ]
    return _frame(spec_a, "STACKING SHEET — NESTING CLEARANCE", scale_label, body)

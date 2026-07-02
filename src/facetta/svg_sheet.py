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

SUPPORTED_CUTS = ("round_brilliant", "oval_brilliant")  # solitaire / halo center cuts
BANGLE_STATION_CUTS = ("princess", "asscher")
PENDANT_CENTER_CUTS = ("emerald_cut", "asscher", "radiant")


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


def _title_block(spec: Spec, scale_label: str = "3:1") -> list[str]:
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
        (f"UNITS mm  ·  SCALE {scale_label}", 3.0, False),
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


def _frame(spec: Spec, title: str, scale_label: str, body: list[str]) -> str:
    """The shared sheet envelope: page, border, title, body views, title block."""
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
        _text(SHEET_W / 2, MARGIN + 8, title, size=4.6, style=' letter-spacing="1.6"'),
    ]
    parts += body
    parts += _title_block(spec, scale_label)
    if spec.notes_to_factory:
        parts.append(_text(MARGIN + 4, SHEET_H - MARGIN - 4,
                           f"NOTES: {spec.notes_to_factory}", size=3.0, anchor="start"))
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def _require_ring_sections(spec: Spec, what: str) -> None:
    if spec.band is None or spec.ring_size is None or spec.ring_size.inner_diameter_mm is None:
        raise SheetUnsupported(f"a {what} sheet needs band and ring_size (with inner diameter)")


def _render_solitaire(spec: Spec) -> str:
    if spec.stone.cut not in SUPPORTED_CUTS:
        raise SheetUnsupported(
            f"cut '{spec.stone.cut}' not supported on sheets yet; supported: {list(SUPPORTED_CUTS)}"
        )
    _require_ring_sections(spec, "solitaire")
    body = _top_view(spec, 82, 105) + _side_view(spec, 200, 100)
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
        f'fill="url(#hatch)" stroke="none"/>',
        _line(left_x, top, left_x, bottom),
        _line(right_x, top, right_x, bottom),
        _line(left_x, top, right_x, top),
        _line(left_x, bottom, right_x, bottom),
        _ellipse(cx, cy, oax, oby),  # halo outer edge
    ]
    for i in range(melee.count):
        t = -math.pi / 2 + i * 2 * math.pi / melee.count
        parts.append(_circle(cx + ring_ax * math.cos(t), cy + ring_by * math.sin(t), mr))
    parts += [
        _ellipse(cx, cy, rx, ry),  # center stone
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
        _ext(left_x, bottom, left_x, bottom + 6), _ext(right_x, bottom, right_x, bottom + 6),
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
    depth = stone.depth * SCALE
    span = stone.length * SCALE
    ring_cy = cy + (gallery + depth) / 2 - depth / 3
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
    body = _halo_top_view(spec, melee, 82, 105) + _halo_side_view(spec, melee, 205, 100)
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
    body = _bangle_face_view(spec, 95, 103) + _bangle_section_view(spec, 232, 100)
    return _frame(spec, "TECHNICAL SHEET — OVAL STATION BANGLE", "2:1", body)


# --- cluster pendant ----------------------------------------------------------

LINK_GAP_MM = 1.0  # jump-ring gap between bail, cluster, and drop stone


def _octagon(cx: float, cy: float, hw: float, hl: float, cut: float) -> str:
    points = (
        f"{cx - hw + cut:.2f},{cy - hl:.2f} {cx + hw - cut:.2f},{cy - hl:.2f} "
        f"{cx + hw:.2f},{cy - hl + cut:.2f} {cx + hw:.2f},{cy + hl - cut:.2f} "
        f"{cx + hw - cut:.2f},{cy + hl:.2f} {cx - hw + cut:.2f},{cy + hl:.2f} "
        f"{cx - hw:.2f},{cy + hl - cut:.2f} {cx - hw:.2f},{cy - hl + cut:.2f}"
    )
    return (
        f'<polygon points="{points}" fill="#ffffff" stroke="{INK}" '
        f'stroke-width="{STROKE_MAIN}"/>'
    )


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
    cut = 0.18 * stone.width * SCALE
    parts += [
        _octagon(cx, cluster_cy, hw, hl, cut),
        _octagon(cx, cluster_cy, hw * 0.62, hl * 0.62, cut * 0.62),  # step-cut table
    ]

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
    body = (
        _pendant_front_view(spec, melee, drop_stone, 100, 48)
        + _pendant_side_view(spec, melee, drop_stone, 225, 48)
    )
    return _frame(spec, "TECHNICAL SHEET — CLUSTER PENDANT", "3:1", body)


TEMPLATES = {
    "solitaire_prong": _render_solitaire,
    "halo_prong": _render_halo,
    "love_bangle": _render_bangle,
    "cluster_pendant": _render_pendant,
}


def render_sheet(spec: Spec) -> str:
    """Render the annotated technical sheet for a validated spec."""
    render = TEMPLATES.get(spec.template)
    if render is None:
        raise SheetUnsupported(
            f"template '{spec.template}' not supported yet; supported: {list(TEMPLATES)}"
        )
    return render(spec)

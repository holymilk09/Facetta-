"""Presentation plate: the atelier-sketch look with the engine's exact truth.

The AI-sketch experiment proved the aesthetic and disproved the method — the
image model drew a beautiful plate with the wrong number of stations and
lettered its own measurements. This module draws that same plate style
deterministically: geometry and station counts come from the spec renderers
(always exact), dimensions are written by code (always true), and the
hand-drawn feel — ivory paper, pencil wobble, paper grain, hatched shadow,
italic plate typography — is styling applied on top. Same spec in, same
plate out, every time.
"""

from __future__ import annotations

import re

from facetta.prototype import (
    _bracelet_proto, _center_default_mount, _defs, _loose_proto, _metal_stops,
    _mix, _pendant_proto, _ring_proto, stone_hex, stone_manifest,
)
from facetta.spec import Spec
from facetta.svg_sheet import BASELINE, MARGIN, SHEET_H, SHEET_W
from facetta.validation import pendant_drop_mm
from facetta.vocabulary import get_vocabulary

IVORY = "#f2ebd8"
INK = "#4a4238"     # warm graphite-sepia, the pencil's own color
FAINT = "#8d8272"
PLATE_FONT = "Georgia, 'Times New Roman', serif"

# Plate papers — what jewelry renderers actually paint on. Mid-grey is the
# haute-joaillerie gouache standard; black/midnight carry diamond and white
# metal renders; ivory is the classic sketchbook; blush suits bridal work.
PAPERS = {
    "ivory":    {"paper": "#f2ebd8", "ink": "#4a4238", "faint": "#8d8272"},
    "white":    {"paper": "#fbfaf7", "ink": "#3f3f3f", "faint": "#8a8a8a"},
    "grey":     {"paper": "#b7b3ab", "ink": "#2b2723", "faint": "#524d46"},
    "midnight": {"paper": "#242a38", "ink": "#e7e3d8", "faint": "#a5a196"},
    "black":    {"paper": "#1c1b18", "ink": "#eae6db", "faint": "#a5a196"},
    "blush":    {"paper": "#f4e3dd", "ink": "#4a3a38", "faint": "#93807c"},
}

TITLES = {
    "solitaire_prong": "Solitaire Ring",
    "halo_prong": "Halo Ring",
    "love_bangle": "Station Bangle",
    "cuff": "Open Cuff",
    "link_bracelet": "Link Bracelet",
    "cluster_pendant": "Cluster Pendant",
    "loose_stone": "Loose Stone",
}


def _fmt(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _t(x: float, y: float, s: str, *, size: float = 4.0, anchor: str = "middle",
       color: str = INK, italic: bool = True, ls: str = "") -> str:
    style = ' font-style="italic"' if italic else ""
    if ls:
        style += f' letter-spacing="{ls}"'
    return (f'<text x="{x:.2f}" y="{y:.2f}" font-family="{PLATE_FONT}" '
            f'font-size="{size}" fill="{color}" text-anchor="{anchor}"{style}>{s}</text>')


def _tick(x: float, y: float) -> str:
    return (f'<line x1="{x - 1:.2f}" y1="{y + 1:.2f}" x2="{x + 1:.2f}" y2="{y - 1:.2f}" '
            f'stroke="{INK}" stroke-width="0.35"/>')


def _dim_h(x1: float, x2: float, y: float, label: str) -> list[str]:
    return [
        f'<line x1="{x1:.2f}" y1="{y:.2f}" x2="{x2:.2f}" y2="{y:.2f}" '
        f'stroke="{INK}" stroke-width="0.3"/>',
        _tick(x1, y), _tick(x2, y),
        _t((x1 + x2) / 2, y - 2.2, label, size=4.4),
    ]


def _dim_v(x: float, y1: float, y2: float, label: str) -> list[str]:
    return [
        f'<line x1="{x:.2f}" y1="{y1:.2f}" x2="{x:.2f}" y2="{y2:.2f}" '
        f'stroke="{INK}" stroke-width="0.3"/>',
        _tick(x, y1), _tick(x, y2),
        _t(x + 2.4, (y1 + y2) / 2 + 1.4, label, size=4.4, anchor="start"),
    ]


def _leader(x1: float, y1: float, x2: float, y2: float, label: str,
            anchor: str = "start") -> list[str]:
    dx = 2 if anchor == "start" else -2
    return [
        f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" '
        f'stroke="{INK}" stroke-width="0.3"/>',
        _t(x2 + dx, y2 + 1.2, label, size=4.0, anchor=anchor),
    ]


def _plate_defs(ink: str) -> str:
    """Sketch styling: fixed seeds keep the plate byte-identical per spec.
    The grain speckles in the paper's own ink so every paper keeps tooth."""
    r, g, b = (int(ink[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return (
        "<defs>"
        # hand wobble: linework drifts like a confident pencil stroke
        '<filter id="wobble" x="-8%" y="-8%" width="116%" height="116%">'
        '<feTurbulence type="fractalNoise" baseFrequency="0.012 0.022" '
        'numOctaves="2" seed="7" result="n"/>'
        '<feDisplacementMap in="SourceGraphic" in2="n" scale="2.4" '
        'xChannelSelector="R" yChannelSelector="G"/>'
        "</filter>"
        # paper grain: fine tooth over the whole sheet
        '<filter id="grain">'
        '<feTurbulence type="fractalNoise" baseFrequency="0.55" numOctaves="2" seed="11"/>'
        f'<feColorMatrix values="0 0 0 0 {r:.2f}  0 0 0 0 {g:.2f}  '
        f'0 0 0 0 {b:.2f}  0 0 0 0.055 0"/>'
        "</filter>"
        # diagonal pencil hatching for the drop shadows
        '<pattern id="hatchsh" width="2.2" height="2.2" patternTransform="rotate(45)" '
        'patternUnits="userSpaceOnUse">'
        f'<line x1="0" y1="0" x2="0" y2="2.2" stroke="{ink}" stroke-width="0.45"/>'
        "</pattern>"
        "</defs>"
    )


_GROUND = re.compile(r'<ellipse ([^>]*)fill="url\(#ground\)"/>')


def _sketchify(parts: list[str]) -> list[str]:
    """Give each soft ground shadow a pencil-hatched twin underneath."""
    out = []
    for p in parts:
        m = _GROUND.search(p)
        if m:
            out.append(f'<ellipse {m.group(1)}fill="url(#hatchsh)" opacity="0.30"/>')
        out.append(p)
    return out


def _bracelet_dims(spec: Spec) -> list[str]:
    s = 2.6
    cx, cy = SHEET_W / 2, BASELINE
    br = spec.bracelet
    a_in, b_in = br.inner_length_mm / 2 * s, br.inner_width_mm / 2 * s
    a_out = a_in + br.thickness_mm * s * 1.6
    b_out = b_in + br.thickness_mm * s * 1.6
    parts = _dim_h(cx - a_in, cx + a_in, cy,
                   f"{_fmt(br.inner_length_mm)} mm inside")
    parts += _dim_v(cx + a_out + 9, cy - b_in, cy + b_in,
                    f"{_fmt(br.inner_width_mm)} mm")
    # band width leader off the upper-left shoulder of the band
    px = cx - (a_in + a_out) / 2 * 0.7071
    py = cy - (b_in + b_out) / 2 * 0.7071
    parts += _leader(px, py, px - 22, py - 12,
                     f"band {_fmt(br.width_mm)} mm wide", anchor="end")
    if spec.stone.position == "stations":
        st = spec.stone
        parts += _leader(cx, cy - b_out + 1.5, cx + a_out * 0.55, cy - b_out - 9,
                         f"{st.count} × {_fmt(st.dimensions_mm.width)} mm "
                         f"{st.cut.replace('_', ' ')}, evenly spaced")
    return parts


def _ring_dims(spec: Spec) -> list[str]:
    import math
    s = 5.0
    cx, cy = SHEET_W / 2, BASELINE
    stone = spec.stone.dimensions_mm
    rx = stone.width / 2 * s
    strip = (spec.ring_size.inner_diameter_mm + 2 * spec.band.thickness_mm) * s
    band_w = spec.band.width_mm * s
    melee = next((m for m in spec.side_stones if m.position in ("halo", "surround")), None)
    head_ax = rx + (0.3 + melee.dimensions_mm.width) * s if melee else rx
    head_by = (stone.length / 2 + (0.3 + melee.dimensions_mm.width)) * s if melee \
        else stone.length / 2 * s
    parts = _dim_h(cx - rx, cx + rx, cy - head_by - 5,
                   f"{_fmt(stone.width)} mm")
    parts += _dim_v(cx + max(head_ax, band_w / 2) + 9, cy - strip / 2, cy + strip / 2,
                    f"{_fmt(spec.ring_size.inner_diameter_mm)} mm inside "
                    f"+ {_fmt(spec.band.thickness_mm)} mm band")
    if melee:
        parts += _leader(cx + head_ax * 0.7071, cy + head_by * 0.7071,
                         cx + head_ax + 16, cy + head_by + 12,
                         f"{melee.count} × ⌀{_fmt(melee.dimensions_mm.width)} mm halo")
    return parts


PENDANT_FRONT_CX = 102.0
PENDANT_SIDE_CX = 226.0


def _pendant_dims(spec: Spec) -> list[str]:
    s = 5.0
    cx = PENDANT_FRONT_CX
    stone = spec.stone.dimensions_mm
    total = pendant_drop_mm(spec) * s
    ty = BASELINE - total / 2
    melee = next((m for m in spec.side_stones if m.position in ("halo", "surround")), None)
    mw = melee.dimensions_mm.width if melee else 0.0
    # the piece's true widest extent: melee outer edge to melee outer edge
    overall = stone.width + 2 * (0.3 + mw) if melee else stone.width
    x = cx + max(overall / 2 * s, spec.pendant.bail_height_mm / 2 * s) + 10
    parts = _dim_v(x, ty, ty + total,
                   f"{_fmt(pendant_drop_mm(spec))} mm drop")
    # overall width below the piece, label under the line so it never
    # touches a drop stone hanging above it
    y = min(ty + total + 10, SHEET_H - MARGIN - 16)
    x1, x2 = cx - overall / 2 * s, cx + overall / 2 * s
    parts += [
        f'<line x1="{x1:.2f}" y1="{y:.2f}" x2="{x2:.2f}" y2="{y:.2f}" '
        f'stroke="{INK}" stroke-width="0.3"/>',
        _tick(x1, y), _tick(x2, y),
        _t((x1 + x2) / 2, y + 5.2, f"{_fmt(overall)} mm across", size=4.4),
        _t(cx, ty - 4, "face on", size=3.6, color=FAINT),
    ]
    # center stone called out by leader, not a line under someone else's stone
    parts += _leader(cx + stone.width / 2 * s * 0.7071,
                     BASELINE - total / 2 + spec.pendant.bail_height_mm * s
                     + 5.0 + (stone.length / 2 + (0.3 + mw)) * s
                     - stone.length / 2 * s * 0.7071,
                     x1 - 4, BASELINE - total * 0.32,
                     f"center {_fmt(stone.width)} × {_fmt(stone.length)} mm",
                     anchor="end")
    return parts


def _stone_profile_color(cx, cy, depth_pp, length_pp, hexval,
                         table_frac=0.57) -> list[str]:
    """A stone edge-on in its own color: table left, crown, girdle band,
    pavilion to the culet — the same construction the ink sheets use."""
    g = max(0.6, 0.03 * depth_pp)
    crown_w = 0.26 * depth_pp - g / 2
    x_t = cx - depth_pp / 2
    x_g1 = x_t + crown_w
    x_g2 = x_g1 + g
    x_culet = cx + depth_pp / 2
    hl = length_pp / 2
    t_hl = hl * table_frac
    edge = _mix(hexval, "#20242c", 0.5)
    return [
        f'<polygon points="{x_t:.2f},{cy - t_hl:.2f} {x_g1:.2f},{cy - hl:.2f} '
        f'{x_g1:.2f},{cy + hl:.2f} {x_t:.2f},{cy + t_hl:.2f}" '
        f'fill="{_mix(hexval, "#FFFFFF", 0.38)}" stroke="{edge}" stroke-width="0.3"/>',
        f'<rect x="{x_g1:.2f}" y="{cy - hl:.2f}" width="{g:.2f}" '
        f'height="{length_pp:.2f}" fill="{_mix(hexval, "#FFFFFF", 0.16)}" '
        f'stroke="{edge}" stroke-width="0.3"/>',
        f'<polygon points="{x_g2:.2f},{cy - hl:.2f} {x_culet:.2f},{cy:.2f} '
        f'{x_g2:.2f},{cy + hl:.2f}" fill="{_mix(hexval, "#000000", 0.18)}" '
        f'stroke="{edge}" stroke-width="0.3"/>',
    ]


def _profile_mount_marks(mount, x_t, x_g1, x_g2, x_culet, cy, hl,
                         m1, m2) -> list[str]:
    """The same mount the face-on view wears, seen from the side — claws
    grip the girdle corners, a bezel walls the girdle, a cap sits the tip."""
    dark = _mix(m2, "#000000", 0.35)
    if mount in ("prong_4", "prong_6", "v_prong", "shared_prong"):
        r = max(1.0, hl * 0.11)
        return [
            f'<ellipse cx="{x_g1:.2f}" cy="{cy + sgn * hl:.2f}" rx="{r * 1.4:.2f}" '
            f'ry="{r:.2f}" fill="{m1}" stroke="{dark}" stroke-width="0.3"/>'
            for sgn in (-1, 1)
        ]
    if mount in ("bezel", "semi_bezel", "flush"):
        wall = (x_g2 - x_g1) * 2.4
        return [
            f'<rect x="{x_g1 - wall * 0.3:.2f}" y="{cy - hl - 1.0:.2f}" '
            f'width="{wall:.2f}" height="{2 * hl + 2.0:.2f}" rx="{wall * 0.3:.2f}" '
            f'fill="{m1}" stroke="{dark}" stroke-width="0.3" opacity="0.95"/>'
        ]
    return []


def _pendant_profile_plate(spec: Spec, vocab) -> list[str]:
    """Side elevation at the same scale and heights as the face-on view, so
    the two correlate stone for stone AND mount for mount."""
    import math  # noqa: F401  (kept parallel with the proto helpers)

    s = 5.0
    cx = PENDANT_SIDE_CX
    stone = spec.stone.dimensions_mm
    total = pendant_drop_mm(spec) * s
    ty = BASELINE - total / 2
    p = spec.pendant
    m1, m2 = _metal_stops(spec)
    melee = next((m for m in spec.side_stones
                  if m.position in ("halo", "surround")), None)
    drop = next((m for m in spec.side_stones
                 if m.position in ("under_center", "drop")), None)
    mw = melee.dimensions_mm.width if melee else 0.0
    surround = (0.3 + mw) if melee else 0.0
    cluster_by = (stone.length / 2 + surround) * s
    cluster_cy = ty + (p.bail_height_mm + 1.0) * s + cluster_by

    bail_w = 1.2 * s
    parts = [
        # the bail edge-on: a narrow gold capsule
        f'<rect x="{cx - bail_w / 2:.2f}" y="{ty:.2f}" width="{bail_w:.2f}" '
        f'height="{p.bail_height_mm * s:.2f}" rx="{bail_w / 2:.2f}" fill="{m1}" '
        f'stroke="{_mix(m2, "#000000", 0.3)}" stroke-width="0.3"/>',
        f'<circle cx="{cx:.2f}" cy="{ty + (p.bail_height_mm + 0.5) * s:.2f}" '
        f'r="{0.45 * s:.2f}" fill="none" stroke="{m1}" '
        f'stroke-width="{0.25 * s:.2f}"/>',
    ]
    d_pp = stone.depth * s
    hl = stone.length / 2 * s
    table_frac = (spec.stone.table_pct or 57) / 100
    hexval = stone_hex(spec.stone, vocab)
    parts += _stone_profile_color(cx, cluster_cy, d_pp, 2 * hl, hexval,
                                  table_frac)
    g = max(0.6, 0.03 * d_pp)
    x_t = cx - d_pp / 2
    x_g1 = x_t + (0.26 * d_pp - g / 2)
    parts += _profile_mount_marks(
        spec.stone.mount or _center_default_mount(spec),
        x_t, x_g1, x_g1 + g, cx + d_pp / 2, cluster_cy, hl, m1, m2)
    if melee:
        md = melee.dimensions_mm.depth * s
        ml = melee.dimensions_mm.width * s
        mhex = stone_hex(melee, vocab)
        for m_cy in (cluster_cy - hl - 0.3 * s - ml / 2,
                     cluster_cy + hl + 0.3 * s + ml / 2):
            parts += _stone_profile_color(cx, m_cy, md, ml, mhex)
    bottom = cluster_cy + cluster_by
    if drop:
        dd = drop.dimensions_mm.depth * s
        dl = drop.dimensions_mm.length * s
        sap_cy = bottom + 1.0 * s + dl / 2
        dhex = stone_hex(drop, vocab)
        parts += [
            f'<circle cx="{cx:.2f}" cy="{bottom + 0.5 * s:.2f}" r="{0.45 * s:.2f}" '
            f'fill="none" stroke="{m1}" stroke-width="{0.25 * s:.2f}"/>',
        ]
        parts += _stone_profile_color(cx, sap_cy, dd, dl, dhex)
        d_mount = drop.mount or "drop_cap"
        if d_mount == "drop_cap":
            cap_w = max(2.0, dd * 0.40)
            # in profile the stone's widest line is the girdle, not the depth
            # center — the cap sits over the girdle, where the tip really is
            gx = cx - dd / 2 + 0.26 * dd
            parts.append(
                f'<path d="M {gx - cap_w / 2:.2f} {sap_cy - dl / 2 + cap_w * 0.35:.2f} '
                f'Q {gx - cap_w / 2:.2f} {sap_cy - dl / 2 - cap_w * 0.4:.2f} '
                f'{gx:.2f} {sap_cy - dl / 2 - cap_w * 0.4:.2f} '
                f'Q {gx + cap_w / 2:.2f} {sap_cy - dl / 2 - cap_w * 0.4:.2f} '
                f'{gx + cap_w / 2:.2f} {sap_cy - dl / 2 + cap_w * 0.35:.2f} Z" '
                f'fill="{m1}" stroke="{_mix(m2, "#000000", 0.3)}" stroke-width="0.3"/>')
        else:
            dg = max(0.6, 0.03 * dd)
            dx_t = cx - dd / 2
            dx_g1 = dx_t + (0.26 * dd - dg / 2)
            parts += _profile_mount_marks(d_mount, dx_t, dx_g1, dx_g1 + dg,
                                          cx + dd / 2, sap_cy, dl / 2, m1, m2)
        bottom = sap_cy + dl / 2
    # the depth dimension the face-on view cannot carry
    y = min(bottom + 10, SHEET_H - MARGIN - 16)
    x1, x2 = cx - d_pp / 2, cx + d_pp / 2
    parts += [
        f'<line x1="{x1:.2f}" y1="{y:.2f}" x2="{x2:.2f}" y2="{y:.2f}" '
        f'stroke="{INK}" stroke-width="0.3"/>',
        _tick(x1, y), _tick(x2, y),
        _t((x1 + x2) / 2, y + 5.2, f"{_fmt(stone.depth)} mm deep", size=4.4),
        _t(cx, ty - 4, "profile", size=3.6, color=FAINT),
    ]
    return parts


def _loose_dims(spec: Spec) -> list[str]:
    d = spec.stone.dimensions_mm
    s = min(9.0, 60 / max(d.length, d.width))
    cx, cy = SHEET_W / 2, BASELINE
    hw, hl = d.width / 2 * s, d.length / 2 * s
    parts = _dim_h(cx - hw, cx + hw, cy - hl - 6, f"{_fmt(d.width)} mm")
    parts += _dim_v(cx + hw + 8, cy - hl, cy + hl, f"{_fmt(d.length)} mm")
    parts += _leader(cx + hw * 0.5, cy + hl * 0.87, cx + hw + 18, cy + hl + 10,
                     f"depth {_fmt(d.depth)} mm")
    return parts


def render_presentation_plate(spec: Spec, paper: str = "ivory") -> str:
    """The client-facing designer plate: sketch warmth, engineering truth.

    paper picks the rendering ground — ivory sketchbook, bright white,
    atelier grey (the gouache tradition), midnight, black, or blush."""
    if paper not in PAPERS:
        raise ValueError(
            f"unknown plate paper '{paper}'; options: {list(PAPERS)}")
    p = PAPERS[paper]
    vocab = get_vocabulary()
    if spec.template in ("solitaire_prong", "halo_prong"):
        body, dims = _ring_proto(spec, vocab, paper=IVORY), _ring_dims(spec)
    elif spec.template in ("love_bangle", "cuff", "link_bracelet"):
        body, dims = _bracelet_proto(spec, vocab, paper=IVORY), _bracelet_dims(spec)
    elif spec.template == "cluster_pendant":
        body = (_pendant_proto(spec, vocab, cx=PENDANT_FRONT_CX)
                + _pendant_profile_plate(spec, vocab))
        dims = _pendant_dims(spec)
    elif spec.template == "loose_stone":
        body, dims = _loose_proto(spec, vocab), _loose_dims(spec)
    else:
        raise ValueError(f"no presentation plate for template '{spec.template}'")

    title = TITLES.get(spec.template, "Jewel")
    stone = spec.stone
    metal_line = ""
    if spec.metal:
        karat = f"{spec.metal.karat}k " if spec.metal.karat else ""
        color = f"{spec.metal.color.replace('_', ' ')} " if spec.metal.color else ""
        metal_line = f"{karat}{color}{spec.metal.material}".title() + " — "
    species = ("" if stone.species.lower() in stone.color.trade.lower()
               else f" {stone.species.title()}")
    subtitle = f"{metal_line}{stone.color.trade}{species}"

    manifest = stone_manifest(spec)
    my = SHEET_H - MARGIN - 6 - 4.6 * (len(manifest) - 1)
    manifest_block = [
        _t(MARGIN + 6, my - 5.4, "STONES &amp; METAL", size=3.0, italic=False,
           color=FAINT, anchor="start", ls="1.6"),
    ] + [
        _t(MARGIN + 6, my + i * 4.6, line, size=3.6, anchor="start", color=FAINT)
        for i, line in enumerate(manifest)
    ]

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SHEET_W:g} {SHEET_H:g}" '
        f'width="{SHEET_W:g}mm" height="{SHEET_H:g}mm" font-family="{PLATE_FONT}">',
        _defs(spec, vocab),
        _plate_defs(p["ink"]),
        f'<rect x="0" y="0" width="{SHEET_W:g}" height="{SHEET_H:g}" fill="{IVORY}"/>',
        f'<rect x="0" y="0" width="{SHEET_W:g}" height="{SHEET_H:g}" filter="url(#grain)"/>',
        f'<rect x="{MARGIN:g}" y="{MARGIN:g}" width="{SHEET_W - 2 * MARGIN:g}" '
        f'height="{SHEET_H - 2 * MARGIN:g}" fill="none" stroke="{INK}" '
        f'stroke-width="0.35" opacity="0.55"/>',
        # cartouche: top-left so tall pieces never collide with the lettering
        _t(MARGIN + 6, MARGIN + 14, title, size=9.5, anchor="start"),
        _t(MARGIN + 6, MARGIN + 21, subtitle, size=4.6, anchor="start", color=FAINT),
        f'<line x1="{MARGIN + 6:.2f}" y1="{MARGIN + 24.5:.2f}" '
        f'x2="{MARGIN + 92:.2f}" y2="{MARGIN + 24.5:.2f}" stroke="{INK}" '
        f'stroke-width="0.3" opacity="0.5"/>',
        # the piece, hand-wobbled; the numbers, dead straight
        '<g filter="url(#wobble)">',
        *_sketchify(body),
        "</g>",
        *dims,
        *manifest_block,
        _t(SHEET_W - MARGIN - 4, SHEET_H - MARGIN - 6,
           "drawn to specification — every measurement from the design record",
           size=3.2, anchor="end", color=FAINT),
        _t(SHEET_W - MARGIN - 4, MARGIN + 12, "FACETTA", size=3.6, anchor="end",
           italic=False, ls="2.4", color=FAINT),
        "</svg>",
    ]
    svg = "\n".join(parts) + "\n"
    if paper != "ivory":
        # the plate is authored in the ivory palette; other papers re-ink it —
        # a pure substitution, so geometry and lettering stay byte-stable
        svg = (svg.replace(IVORY, p["paper"])
                  .replace(INK, p["ink"])
                  .replace(FAINT, p["faint"]))
    return svg

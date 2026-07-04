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
    _bracelet_proto, _defs, _loose_proto, _pendant_proto, _ring_proto,
    stone_manifest,
)
from facetta.spec import Spec
from facetta.svg_sheet import BASELINE, MARGIN, SHEET_H, SHEET_W
from facetta.validation import pendant_drop_mm
from facetta.vocabulary import get_vocabulary

IVORY = "#f2ebd8"
INK = "#4a4238"     # warm graphite-sepia, the pencil's own color
FAINT = "#8d8272"
PLATE_FONT = "Georgia, 'Times New Roman', serif"

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


def _plate_defs() -> str:
    """Sketch styling: fixed seeds keep the plate byte-identical per spec."""
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
        '<feColorMatrix values="0 0 0 0 0.28  0 0 0 0 0.24  0 0 0 0 0.18  0 0 0 0.055 0"/>'
        "</filter>"
        # diagonal pencil hatching for the drop shadows
        '<pattern id="hatchsh" width="2.2" height="2.2" patternTransform="rotate(45)" '
        'patternUnits="userSpaceOnUse">'
        f'<line x1="0" y1="0" x2="0" y2="2.2" stroke="{INK}" stroke-width="0.45"/>'
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


def _pendant_dims(spec: Spec) -> list[str]:
    s = 5.0
    cx = SHEET_W / 2
    stone = spec.stone.dimensions_mm
    total = pendant_drop_mm(spec) * s
    ty = BASELINE - total / 2
    melee = next((m for m in spec.side_stones if m.position in ("halo", "surround")), None)
    cluster_ax = (stone.width / 2 + (0.3 + melee.dimensions_mm.width if melee else 0.0)) * s
    x = cx + max(cluster_ax, spec.pendant.bail_height_mm / 2 * s) + 12
    parts = _dim_v(x, ty, ty + total,
                   f"{_fmt(pendant_drop_mm(spec))} mm drop")
    # center-width dim below the piece, label under the line so it never
    # touches a drop stone hanging above it
    y = min(ty + total + 10, SHEET_H - MARGIN - 16)
    x1, x2 = cx - stone.width / 2 * s, cx + stone.width / 2 * s
    parts += [
        f'<line x1="{x1:.2f}" y1="{y:.2f}" x2="{x2:.2f}" y2="{y:.2f}" '
        f'stroke="{INK}" stroke-width="0.3"/>',
        _tick(x1, y), _tick(x2, y),
        _t((x1 + x2) / 2, y + 5.2, f"{_fmt(stone.width)} mm center", size=4.4),
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


def render_presentation_plate(spec: Spec) -> str:
    """The client-facing designer plate: sketch warmth, engineering truth."""
    vocab = get_vocabulary()
    if spec.template in ("solitaire_prong", "halo_prong"):
        body, dims = _ring_proto(spec, vocab, paper=IVORY), _ring_dims(spec)
    elif spec.template in ("love_bangle", "cuff", "link_bracelet"):
        body, dims = _bracelet_proto(spec, vocab, paper=IVORY), _bracelet_dims(spec)
    elif spec.template == "cluster_pendant":
        body, dims = _pendant_proto(spec, vocab), _pendant_dims(spec)
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
        _plate_defs(),
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
    return "\n".join(parts) + "\n"

"""Colored prototype rendering and the photoreal render-prompt compiler.

The colored prototype is the deterministic, spec-true colored view (vocabulary
hue hexes + metal tones) that sits between the pencil technical sheet and the
photoreal AI render of PRD phase 2.5. The prompt compiler produces the text an
external image model consumes — the AI never draws geometry, it only receives
the numbers and controlled vocabulary we compiled.
"""

from __future__ import annotations

from facetta.spec import Spec, Stone
from facetta.svg_sheet import (
    BASELINE, FONT, MARGIN, SHEET_H, SHEET_W, _facet_face_up, _find_stone, _fmt, _text,
)
from facetta.validation import estimate_metal_g, pendant_drop_mm
from facetta.vocabulary import Vocabulary, get_vocabulary

INK = "#3f3f3f"

METAL_GRADIENTS = {
    ("gold", "yellow"): ("#F3DFA0", "#C9992E"),
    ("gold", "rose"): ("#F0BFAC", "#B06A55"),
    ("gold", "white"): ("#F2F4F6", "#A9AFB5"),
    ("platinum", None): ("#F4F6F8", "#AEB4BA"),
    ("silver", None): ("#F7F8F9", "#B9BEC3"),
}

# fallback stone colors when the spec carries no GIA hue code
SPECIES_HEX = {
    "diamond": "#F2F5F8",
    "ruby": "#F80E5C",
    "sapphire": "#0916A5",
    "emerald": "#00A550",
    "aquamarine": "#7FD4E4",
    "spinel": "#E4002B",
    "tanzanite": "#4B3A9E",
    "garnet": "#8A0F2C",
    "topaz": "#F6A400",
    "tourmaline": "#00B893",
}


def _mix(hex_color: str, toward: str, t: float) -> str:
    a = [int(hex_color[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(toward[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


def stone_hex(stone: Stone, vocab: Vocabulary) -> str:
    if stone.color.hue_code:
        for entry in vocab.raw["gia_hue_scale"]:
            if entry["code"] == stone.color.hue_code:
                return entry["hex"]
    return SPECIES_HEX.get(stone.species, "#9aa0c0")


def _metal_stops(spec: Spec) -> tuple[str, str]:
    if spec.metal is None:
        return METAL_GRADIENTS[("platinum", None)]
    key = (spec.metal.material, spec.metal.color if spec.metal.material == "gold" else None)
    return METAL_GRADIENTS.get(key, METAL_GRADIENTS[("gold", "yellow")])


def _defs(spec: Spec, vocab: Vocabulary) -> str:
    m1, m2 = _metal_stops(spec)
    s = stone_hex(spec.stone, vocab)
    s_light = _mix(s, "#FFFFFF", 0.55)
    return (
        "<defs>"
        f'<linearGradient id="metal" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{m1}"/><stop offset="1" stop-color="{m2}"/>'
        "</linearGradient>"
        f'<radialGradient id="stone" cx="0.38" cy="0.32" r="0.85">'
        f'<stop offset="0" stop-color="{s_light}"/><stop offset="1" stop-color="{s}"/>'
        "</radialGradient>"
        f'<radialGradient id="melee" cx="0.4" cy="0.35" r="0.9">'
        '<stop offset="0" stop-color="#ffffff"/><stop offset="1" stop-color="#ccd4dc"/>'
        "</radialGradient>"
        # lighting: metal sheen sweeping from the upper left, soft blur, lift shadow
        '<linearGradient id="sheen" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" stop-color="#ffffff" stop-opacity="0.5"/>'
        '<stop offset="0.45" stop-color="#ffffff" stop-opacity="0.06"/>'
        '<stop offset="0.75" stop-color="#000000" stop-opacity="0.07"/>'
        '<stop offset="1" stop-color="#000000" stop-opacity="0.12"/>'
        "</linearGradient>"
        # ground shadow: dense core melting to nothing at the rim
        '<radialGradient id="ground" cx="0.5" cy="0.5" r="0.5">'
        '<stop offset="0" stop-color="#3f3f3f" stop-opacity="0.22"/>'
        '<stop offset="0.45" stop-color="#3f3f3f" stop-opacity="0.13"/>'
        '<stop offset="0.75" stop-color="#3f3f3f" stop-opacity="0.05"/>'
        '<stop offset="1" stop-color="#3f3f3f" stop-opacity="0"/>'
        "</radialGradient>"
        '<filter id="blur1"><feGaussianBlur stdDeviation="1.1"/></filter>'
        '<filter id="lift" x="-20%" y="-20%" width="140%" height="140%">'
        '<feDropShadow dx="0" dy="1.6" stdDeviation="1.8" flood-color="#3f3f3f" '
        'flood-opacity="0.22"/></filter>'
        "</defs>"
    )


def _shadow(cx: float, cy: float, rx: float) -> str:
    # widened so the gradient's penumbra has room to fade out
    return (
        f'<ellipse cx="{cx:.2f}" cy="{cy:.2f}" rx="{rx * 1.35:.2f}" '
        f'ry="{rx * 0.24:.2f}" fill="url(#ground)"/>'
    )


def _stone_faceted(cx, cy, cut, w_pp, l_pp, table_ratio=0.57, fill="url(#stone)",
                   edge=None) -> list[str]:
    parts = [
        # ambient occlusion where the stone meets the metal
        f'<ellipse cx="{cx + 0.6:.2f}" cy="{cy + 1.0:.2f}" rx="{w_pp / 2 + 0.6:.2f}" '
        f'ry="{l_pp / 2 + 0.6:.2f}" fill="#000000" opacity="0.18" filter="url(#blur1)"/>',
    ]
    parts += _facet_face_up(cx, cy, cut, w_pp, l_pp, table_ratio=table_ratio,
                            stroke=edge or "#00000055", fill=fill,
                            facet_color="#ffffffaa", facet_w=0.35, lit=True)
    # specular catch-light toward the source
    parts.append(
        f'<ellipse cx="{cx - w_pp * 0.16:.2f}" cy="{cy - l_pp * 0.20:.2f}" '
        f'rx="{w_pp * 0.13:.2f}" ry="{l_pp * 0.08:.2f}" fill="#ffffff" opacity="0.55" '
        f'filter="url(#blur1)" transform="rotate(-30 {cx:.2f} {cy:.2f})"/>'
    )
    return parts


def _melee_circle(cx, cy, r) -> str:
    return (
        # seat shadow, stone, and a pinpoint catch-light
        f'<circle cx="{cx + 0.4:.2f}" cy="{cy + 0.7:.2f}" r="{r:.2f}" fill="#000000" '
        f'opacity="0.16" filter="url(#blur1)"/>'
        f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}" fill="url(#melee)" '
        f'stroke="#00000033" stroke-width="0.25"/>'
        f'<circle cx="{cx - r * 0.3:.2f}" cy="{cy - r * 0.35:.2f}" r="{r * 0.18:.2f}" '
        f'fill="#ffffff" opacity="0.85"/>'
    )


def _ring_proto(spec: Spec, vocab: Vocabulary) -> list[str]:
    import math

    s = 5.0
    cx, cy = SHEET_W / 2, BASELINE
    stone = spec.stone.dimensions_mm
    rx, ry = stone.width / 2 * s, stone.length / 2 * s
    band_w = spec.band.width_mm * s
    strip = (spec.ring_size.inner_diameter_mm + 2 * spec.band.thickness_mm) * s
    melee = _find_stone(spec, "halo", "surround")

    parts = [_shadow(cx, cy + strip / 2 + 8, strip / 3)]
    band_rect = (
        f'x="{cx - band_w / 2:.2f}" y="{cy - strip / 2:.2f}" width="{band_w:.2f}" '
        f'height="{strip:.2f}" rx="{band_w / 2:.2f}"'
    )
    parts += [
        f'<rect {band_rect} fill="url(#metal)" stroke="#00000022" stroke-width="0.3"/>',
        f'<rect {band_rect} fill="url(#sheen)"/>',
    ]
    if melee is not None:
        mw = melee.dimensions_mm.width
        mr = mw / 2 * s
        ring_ax = rx + 0.3 * s + mr
        ring_by = ry + 0.3 * s + mr
        halo = f'cx="{cx:.2f}" cy="{cy:.2f}" rx="{ring_ax + mr:.2f}" ry="{ring_by + mr:.2f}"'
        parts += [
            f'<ellipse {halo} fill="url(#metal)" stroke="#00000022" stroke-width="0.3"/>',
            f'<ellipse {halo} fill="url(#sheen)"/>',
        ]
        for i in range(melee.count):
            t = -math.pi / 2 + i * 2 * math.pi / melee.count
            parts.append(_melee_circle(cx + ring_ax * math.cos(t), cy + ring_by * math.sin(t), mr))
    parts += _stone_faceted(cx, cy, spec.stone.cut, 2 * rx, 2 * ry)
    return parts


def _bracelet_proto(spec: Spec, vocab: Vocabulary) -> list[str]:
    import math

    s = 2.6
    cx, cy = SHEET_W / 2, BASELINE
    br = spec.bracelet
    a_in, b_in = br.inner_length_mm / 2 * s, br.inner_width_mm / 2 * s
    a_out, b_out = a_in + br.thickness_mm * s * 1.6, b_in + br.thickness_mm * s * 1.6
    parts = [
        _shadow(cx, cy + b_out + 8, a_out * 0.8),
        f'<ellipse cx="{cx:.2f}" cy="{cy:.2f}" rx="{a_out:.2f}" ry="{b_out:.2f}" '
        f'fill="url(#metal)" stroke="#00000022" stroke-width="0.3"/>',
        f'<ellipse cx="{cx:.2f}" cy="{cy:.2f}" rx="{a_out:.2f}" ry="{b_out:.2f}" '
        f'fill="url(#sheen)"/>',
        f'<ellipse cx="{cx:.2f}" cy="{cy:.2f}" rx="{a_in:.2f}" ry="{b_in:.2f}" '
        f'fill="#fdfdfa"/>',
    ]
    stone = spec.stone
    if stone.position == "stations":
        side = stone.dimensions_mm.width * s * 1.4
        a_c, b_c = (a_in + a_out) / 2, (b_in + b_out) / 2
        for i in range(stone.count):
            t = -math.pi / 2 + i * 2 * math.pi / stone.count
            px, py = cx + a_c * math.cos(t), cy + b_c * math.sin(t)
            angle = math.degrees(math.atan2(b_c * math.cos(t), -a_c * math.sin(t)))
            parts.append(
                f'<rect x="{px - side / 2:.2f}" y="{py - side / 2:.2f}" width="{side:.2f}" '
                f'height="{side:.2f}" fill="url(#melee)" stroke="#00000033" stroke-width="0.25" '
                f'transform="rotate({angle:.1f} {px:.2f} {py:.2f})"/>'
            )
    return parts


def _pendant_proto(spec: Spec, vocab: Vocabulary) -> list[str]:
    import math

    s = 5.0
    cx = SHEET_W / 2
    stone = spec.stone.dimensions_mm
    hw, hl = stone.width / 2 * s, stone.length / 2 * s
    melee = _find_stone(spec, "halo", "surround")
    drop = _find_stone(spec, "under_center", "drop")
    total = pendant_drop_mm(spec) * s
    ty = BASELINE - total / 2
    p = spec.pendant

    bail_r = p.bail_height_mm / 2 * s
    bail_w = (p.bail_height_mm - p.bail_inner_diameter_mm) / 2 * s
    parts = [
        _shadow(cx, ty + total + 10, total / 4),
        f'<circle cx="{cx:.2f}" cy="{ty + bail_r:.2f}" r="{bail_r:.2f}" fill="none" '
        f'stroke="url(#metal)" stroke-width="{bail_w:.2f}"/>',
        f'<circle cx="{cx:.2f}" cy="{ty + bail_r:.2f}" r="{bail_r:.2f}" fill="none" '
        f'stroke="url(#sheen)" stroke-width="{bail_w:.2f}"/>',
    ]
    surround = (0.3 + (melee.dimensions_mm.width if melee else 0.0)) if melee else 0.0
    cluster_by = (stone.length / 2 + surround) * s
    cluster_cy = ty + (p.bail_height_mm + 1.0) * s + cluster_by
    if melee:
        mw = melee.dimensions_mm.width
        mr = mw / 2 * s
        ring_ax = hw + 0.3 * s + mr
        ring_by = hl + 0.3 * s + mr
        for i in range(melee.count):
            t = -math.pi / 2 + i * 2 * math.pi / melee.count
            parts.append(_melee_circle(cx + ring_ax * math.cos(t),
                                       cluster_cy + ring_by * math.sin(t), mr))
    parts += _stone_faceted(cx, cluster_cy, spec.stone.cut, 2 * hw, 2 * hl, table_ratio=0.62)
    if drop:
        dw = drop.dimensions_mm.width * s
        sap_cy = cluster_cy + cluster_by + 1.0 * s + dw / 2
        sap_hex = stone_hex(drop, vocab)
        parts.append(
            f'<circle cx="{cx:.2f}" cy="{sap_cy:.2f}" r="{dw / 2:.2f}" fill="{sap_hex}" '
            f'stroke="#00000033" stroke-width="0.3"/>'
        )
        parts.append(
            f'<circle cx="{cx - dw * 0.12:.2f}" cy="{sap_cy - dw * 0.14:.2f}" r="{dw * 0.16:.2f}" '
            f'fill="#ffffff" opacity="0.5"/>'
        )
    return parts


def _loose_proto(spec: Spec, vocab: Vocabulary) -> list[str]:
    d = spec.stone.dimensions_mm
    s = min(9.0, 60 / max(d.length, d.width))
    cx, cy = SHEET_W / 2, BASELINE
    hw, hl = d.width / 2 * s, d.length / 2 * s
    table = (spec.stone.table_pct or 57) / 100
    return [
        _shadow(cx, cy + hl + 8, hw * 1.1),
        *_stone_faceted(cx, cy, spec.stone.cut, 2 * hw, 2 * hl, table_ratio=table),
    ]


def render_color_preview(spec: Spec) -> str:
    """Deterministic colored prototype: vocabulary hues + metal tones, same
    geometry as the technical sheet."""
    vocab = get_vocabulary()
    if spec.template in ("solitaire_prong", "halo_prong"):
        body = _ring_proto(spec, vocab)
    elif spec.template in ("love_bangle", "cuff", "link_bracelet"):
        body = _bracelet_proto(spec, vocab)
    elif spec.template == "cluster_pendant":
        body = _pendant_proto(spec, vocab)
    elif spec.template == "loose_stone":
        body = _loose_proto(spec, vocab)
    else:
        raise ValueError(f"no prototype view for template '{spec.template}'")

    stone = spec.stone
    metal_text = ""
    if spec.metal:
        karat = f"{spec.metal.karat}k " if spec.metal.karat else ""
        metal_text = f" · {karat}{spec.metal.color} {spec.metal.material}"
    caption = (
        f"{stone.carat:.2f} ct {stone.color.trade} {stone.species}, "
        f"{stone.cut.replace('_', ' ')}{metal_text}"
    )
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SHEET_W:g} {SHEET_H:g}" '
        f'width="{SHEET_W:g}mm" height="{SHEET_H:g}mm" font-family="{FONT}">',
        _defs(spec, vocab),
        f'<rect x="0" y="0" width="{SHEET_W:g}" height="{SHEET_H:g}" fill="#fdfdfa"/>',
        _text(SHEET_W / 2, MARGIN + 10, "COLOR PROTOTYPE", size=4.6,
              style=' letter-spacing="2.4"'),
        _text(SHEET_W / 2, MARGIN + 15.4,
              f"{spec.design_id} · v{spec.version} — colors from the controlled vocabulary",
              size=2.8, color="#8a8a8a"),
        '<g filter="url(#lift)">',
        *body,
        "</g>",
        _text(SHEET_W / 2, SHEET_H - MARGIN - 6, caption, size=3.4),
        "</svg>",
    ]
    return "\n".join(parts) + "\n"


def compile_render_prompt(spec: Spec) -> dict:
    """Spec -> photoreal prompt for an external image model. Dimensional truth
    travels with the prompt; the control image carries the geometry."""
    stone = spec.stone
    d = stone.dimensions_mm
    piece = {
        "solitaire_prong": "solitaire ring",
        "halo_prong": "halo ring",
        "love_bangle": "oval station bangle bracelet",
        "cuff": "open cuff bracelet",
        "link_bracelet": "articulated link bracelet",
        "cluster_pendant": "cluster pendant necklace" if spec.chain else "cluster pendant",
        "loose_stone": "loose gemstone, unmounted",
    }.get(spec.template, spec.template)

    details = [
        f"a {stone.carat:.2f} carat {stone.color.trade} {stone.species} "
        f"({stone.color.gia}), {stone.cut.replace('_', ' ')} cut, "
        f"{_fmt(d.length)} x {_fmt(d.width)} x {_fmt(d.depth)} mm",
    ]
    if spec.metal:
        karat = f"{spec.metal.karat} karat " if spec.metal.karat else ""
        finish = (spec.metal.finish or "high_polish").replace("_", " ")
        details.append(f"set in {karat}{spec.metal.color} {spec.metal.material}, {finish} finish")
    for side in spec.side_stones:
        where = {"halo": "in a halo around the center", "surround": "surrounding the center",
                 "stations": "evenly spaced stations", "under_center": "hanging below the center",
                 "drop": "hanging below the center"}.get(side.position or "", "as accents")
        details.append(
            f"{side.count} x {_fmt(side.dimensions_mm.width)} mm "
            f"{side.cut.replace('_', ' ')} {side.color.trade} {side.species} {where}"
        )
    if spec.bracelet:
        details.append(
            f"oval opening {_fmt(spec.bracelet.inner_length_mm)} x "
            f"{_fmt(spec.bracelet.inner_width_mm)} mm, band {_fmt(spec.bracelet.width_mm)} mm wide"
        )
    if spec.pendant:
        details.append(f"overall drop {_fmt(pendant_drop_mm(spec))} mm from the bail")
    if spec.chain:
        details.append(
            f"on a {spec.chain.style.replace('_', ' ')} chain, "
            f"{_fmt(spec.chain.length_mm)} mm, {spec.chain.clasp.replace('_', ' ')} clasp"
        )
    weight = estimate_metal_g(spec)
    if weight:
        details.append(f"approximately {weight} g of metal")

    prompt = (
        f"Ultra-realistic studio product photograph of a {piece}: "
        + "; ".join(details)
        + ". Macro jewelry photography, softbox lighting, neutral seamless background, "
        "sharp focus on the center stone, physically accurate proportions exactly as "
        "specified, no exaggeration of stone size."
    )
    return {
        "prompt": prompt,
        "negative_prompt": (
            "wrong number of stones, extra prongs, deformed metal, text, watermark, "
            "hands, blurry, cartoon, painting, exaggerated sparkle"
        ),
        "control_hint": (
            "For geometry-locked renders, rasterize this version's sheet.svg (or the "
            "prototype.svg) and feed it as a lineart/Canny ControlNet input, or use the "
            "future GLB export as a depth map. The prompt alone will not hold dimensions."
        ),
    }

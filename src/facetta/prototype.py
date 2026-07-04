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
        '<filter id="blur1" x="-60%" y="-60%" width="220%" height="220%">'
        '<feGaussianBlur stdDeviation="1.1"/></filter>'
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


def _luminance(hex_color: str) -> float:
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _stone_faceted(cx, cy, cut, w_pp, l_pp, table_ratio=0.57, fill="url(#stone)",
                   edge=None, tone=None) -> list[str]:
    # light stones (D-color diamond) show structure through crisp facet lines
    # in a darker tone of their own color; dark stones through light-and-shade
    lum = _luminance(tone) if tone else 0.5
    facet_line = _mix(tone, "#343a44", 0.42) if tone else "#ffffffaa"
    shade = max(0.15, 1.0 - lum)
    parts = [
        # ambient occlusion where the stone meets the metal
        f'<ellipse cx="{cx + 0.6:.2f}" cy="{cy + 1.0:.2f}" rx="{w_pp / 2 + 0.6:.2f}" '
        f'ry="{l_pp / 2 + 0.6:.2f}" fill="#000000" opacity="0.18" filter="url(#blur1)"/>',
    ]
    parts += _facet_face_up(cx, cy, cut, w_pp, l_pp, table_ratio=table_ratio,
                            stroke=edge or (_mix(tone, "#20242c", 0.5) if tone
                                            else "#00000055"),
                            fill=fill, facet_color=facet_line, facet_w=0.3,
                            lit=True, shade_scale=shade)
    # specular catch-light toward the source
    parts.append(
        f'<ellipse cx="{cx - w_pp * 0.16:.2f}" cy="{cy - l_pp * 0.20:.2f}" '
        f'rx="{w_pp * 0.13:.2f}" ry="{l_pp * 0.08:.2f}" fill="#ffffff" opacity="0.55" '
        f'filter="url(#blur1)" transform="rotate(-30 {cx:.2f} {cy:.2f})"/>'
    )
    return parts


def _pearl_dome(cx, cy, r, body_hex) -> str:
    """Pearls ARE smooth spheres — nacre luster, not facets."""
    light = _mix(body_hex, "#FFFFFF", 0.75)
    return (
        f'<circle cx="{cx + 0.4:.2f}" cy="{cy + 0.7:.2f}" r="{r:.2f}" fill="#000000" '
        f'opacity="0.16" filter="url(#blur1)"/>'
        f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}" fill="{body_hex}" '
        f'stroke="#00000033" stroke-width="0.25"/>'
        f'<circle cx="{cx - r * 0.28:.2f}" cy="{cy - r * 0.32:.2f}" r="{r * 0.55:.2f}" '
        f'fill="{light}" opacity="0.6" filter="url(#blur1)"/>'
        f'<circle cx="{cx - r * 0.3:.2f}" cy="{cy - r * 0.35:.2f}" r="{r * 0.16:.2f}" '
        f'fill="#ffffff" opacity="0.9"/>'
    )


def _stone_visual(cx, cy, stone, w_pp, l_pp, vocab, table_ratio=0.57,
                  fill=None) -> list[str]:
    """A stone drawn as what it IS: pearls as lustrous spheres, everything
    faceted with its real cut and ITS OWN color — a diamond melee must never
    read as a pearl, and a sapphire drop must never borrow the center's hue."""
    hexval = stone_hex(stone, vocab)
    if stone.species == "pearl":
        return [_pearl_dome(cx, cy, max(w_pp, l_pp) / 2, hexval)]
    return _stone_faceted(cx, cy, stone.cut, w_pp, l_pp, table_ratio=table_ratio,
                          tone=hexval, fill=fill or _mix(hexval, "#FFFFFF", 0.22))


def _arc_points(cx, cy, rx, ry, deg0, deg1, n=48) -> str:
    """Sampled elliptical arc as a polyline points string (screen angles)."""
    import math
    pts = []
    for k in range(n + 1):
        a = math.radians(deg0 + (deg1 - deg0) * k / n)
        pts.append(f"{cx + rx * math.cos(a):.2f},{cy + ry * math.sin(a):.2f}")
    return " ".join(pts)


def _annulus_lighting(cx, cy, a_in, b_in, a_out, b_out, m1, m2) -> list[str]:
    """Light that follows the ring's own geometry, not the page.

    A metal annulus under a single upper-left source: a broad rim highlight
    sweeping the upper-left arc of the band centerline, a shade arc opposite,
    ambient occlusion hugging the inner edge, and a crisp rim light on the
    outer edge — every stroke traced along the actual ellipses, so any
    bangle dimensions shade correctly."""
    a_c, b_c = (a_in + a_out) / 2, (b_in + b_out) / 2
    band = max(1.0, min(a_out - a_in, b_out - b_in))
    cid = f"ann{cx:.0f}x{cy:.0f}x{a_out:.0f}"  # deterministic per ring
    return [
        f'<clipPath id="{cid}"><ellipse cx="{cx:.2f}" cy="{cy:.2f}" '
        f'rx="{a_out:.2f}" ry="{b_out:.2f}"/></clipPath>',
        f'<g clip-path="url(#{cid})">',
        # broad highlight along the upper-left of the band
        f'<polyline points="{_arc_points(cx, cy, a_c, b_c, 155, 275)}" fill="none" '
        f'stroke="{_mix(m1, "#FFFFFF", 0.65)}" stroke-width="{band * 0.72:.2f}" '
        f'stroke-linecap="round" opacity="0.65" filter="url(#blur1)"/>',
        f'<polyline points="{_arc_points(cx, cy, a_c, b_c, 185, 245)}" fill="none" '
        f'stroke="#ffffff" stroke-width="{band * 0.3:.2f}" '
        f'stroke-linecap="round" opacity="0.5" filter="url(#blur1)"/>',
        # deep tone along the lower-right
        f'<polyline points="{_arc_points(cx, cy, a_c, b_c, -15, 105)}" fill="none" '
        f'stroke="{_mix(m2, "#000000", 0.35)}" stroke-width="{band * 0.6:.2f}" '
        f'stroke-linecap="round" opacity="0.45" filter="url(#blur1)"/>',
        # ambient occlusion hugging the inner opening
        f'<ellipse cx="{cx:.2f}" cy="{cy:.2f}" rx="{a_in + band * 0.12:.2f}" '
        f'ry="{b_in + band * 0.12:.2f}" fill="none" stroke="#000000" '
        f'stroke-width="{band * 0.22:.2f}" opacity="0.18" filter="url(#blur1)"/>',
        # crisp rim light where the outer edge turns away from the source
        f'<polyline points="{_arc_points(cx, cy, a_out - 0.25, b_out - 0.25, 165, 265)}" '
        f'fill="none" stroke="#ffffff" stroke-width="0.6" opacity="0.7"/>',
        "</g>",
    ]


def _link_ring(cx, cy, r) -> list[str]:
    """A small metal jump ring — components must visibly connect."""
    return [
        f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}" fill="none" '
        f'stroke="url(#metal)" stroke-width="{r * 0.55:.2f}"/>',
        f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}" fill="none" '
        f'stroke="url(#sheen)" stroke-width="{r * 0.55:.2f}"/>',
    ]


def _ring_proto(spec: Spec, vocab: Vocabulary, paper: str = "#fdfdfa") -> list[str]:
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
        m1, m2 = _metal_stops(spec)
        halo = f'cx="{cx:.2f}" cy="{cy:.2f}" rx="{ring_ax + mr:.2f}" ry="{ring_by + mr:.2f}"'
        parts += [
            f'<ellipse {halo} fill="{_mix(m1, m2, 0.45)}" stroke="#00000022" stroke-width="0.3"/>',
            *_annulus_lighting(cx, cy, ring_ax - mr, ring_by - mr,
                               ring_ax + mr, ring_by + mr, m1, m2),
            f'<ellipse cx="{cx:.2f}" cy="{cy:.2f}" rx="{ring_ax - mr:.2f}" '
            f'ry="{ring_by - mr:.2f}" fill="{paper}"/>',
        ]
        for i in range(melee.count):
            t = -math.pi / 2 + i * 2 * math.pi / melee.count
            parts += _stone_visual(cx + ring_ax * math.cos(t),
                                   cy + ring_by * math.sin(t), melee,
                                   2 * mr, 2 * mr, vocab)
    parts += _stone_visual(cx, cy, spec.stone, 2 * rx, 2 * ry, vocab,
                           fill="url(#stone)")
    return parts


def _bracelet_proto(spec: Spec, vocab: Vocabulary, paper: str = "#fdfdfa") -> list[str]:
    import math

    s = 2.6
    cx, cy = SHEET_W / 2, BASELINE
    br = spec.bracelet
    a_in, b_in = br.inner_length_mm / 2 * s, br.inner_width_mm / 2 * s
    a_out, b_out = a_in + br.thickness_mm * s * 1.6, b_in + br.thickness_mm * s * 1.6
    m1, m2 = _metal_stops(spec)
    parts = [
        _shadow(cx, cy + b_out + 8, a_out * 0.8),
        f'<ellipse cx="{cx:.2f}" cy="{cy:.2f}" rx="{a_out:.2f}" ry="{b_out:.2f}" '
        f'fill="{_mix(m1, m2, 0.45)}" stroke="#00000022" stroke-width="0.3"/>',
        f'<ellipse cx="{cx:.2f}" cy="{cy:.2f}" rx="{a_in:.2f}" ry="{b_in:.2f}" '
        f'fill="{paper}"/>',
        # light traced along the ring's own curvature, not the page
        *_annulus_lighting(cx, cy, a_in, b_in, a_out, b_out, m1, m2),
        f'<ellipse cx="{cx:.2f}" cy="{cy:.2f}" rx="{a_in:.2f}" ry="{b_in:.2f}" '
        f'fill="{paper}"/>',
    ]
    stone = spec.stone
    if stone.position == "stations":
        side = stone.dimensions_mm.width * s * 1.4
        a_c, b_c = (a_in + a_out) / 2, (b_in + b_out) / 2
        hexval = stone_hex(stone, vocab)  # stations wear their own color
        fill = _mix(hexval, "#FFFFFF", 0.22)
        edge = _mix(hexval, "#20242c", 0.5)
        seat = side * 1.22  # the flush bezel frame holding each station
        for i in range(stone.count):
            t = -math.pi / 2 + i * 2 * math.pi / stone.count
            px, py = cx + a_c * math.cos(t), cy + b_c * math.sin(t)
            angle = math.degrees(math.atan2(b_c * math.cos(t), -a_c * math.sin(t)))
            inset = side * 0.32
            parts.append(
                f'<g transform="rotate({angle:.1f} {px:.2f} {py:.2f})">'
                f'<rect x="{px - seat / 2:.2f}" y="{py - seat / 2:.2f}" width="{seat:.2f}" '
                f'height="{seat:.2f}" rx="{seat * 0.12:.2f}" fill="{_mix(m2, "#000000", 0.12)}"/>'
                f'<rect x="{px - seat / 2:.2f}" y="{py - seat / 2:.2f}" width="{seat:.2f}" '
                f'height="{seat:.2f}" rx="{seat * 0.12:.2f}" fill="none" '
                f'stroke="{_mix(m1, "#FFFFFF", 0.4)}" stroke-width="0.35"/>'
                f'<rect x="{px - side / 2:.2f}" y="{py - side / 2:.2f}" width="{side:.2f}" '
                f'height="{side:.2f}" fill="{fill}" stroke="{edge}" stroke-width="0.3"/>'
                f'<rect x="{px - side / 2 + inset:.2f}" y="{py - side / 2 + inset:.2f}" '
                f'width="{side - 2 * inset:.2f}" height="{side - 2 * inset:.2f}" '
                f'fill="none" stroke="{edge}" stroke-width="0.25"/>'
                f'<circle cx="{px - side * 0.18:.2f}" cy="{py - side * 0.18:.2f}" '
                f'r="{side * 0.1:.2f}" fill="#ffffff" opacity="0.8"/></g>'
            )
    return parts


def _pendant_proto(spec: Spec, vocab: Vocabulary) -> list[str]:
    import math

    s = 5.0
    cx = SHEET_W / 2
    stone = spec.stone.dimensions_mm
    hw, hl = stone.width / 2 * s, stone.length / 2 * s
    surround_groups = [s for s in spec.side_stones if s.position in ("halo", "surround")]
    melee = (max(surround_groups, key=lambda s: s.dimensions_mm.width)
             if surround_groups else None)
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
    # the bail hangs the cluster on the 1 mm jump ring the spec's drop math uses
    parts += _link_ring(cx, ty + p.bail_height_mm * s + 0.5 * s, 0.45 * s)
    if melee:
        from facetta.svg_sheet import _surround_sequence
        mw = melee.dimensions_mm.width
        mr = mw / 2 * s
        ring_ax = hw + 0.3 * s + mr
        ring_by = hl + 0.3 * s + mr
        sequence = _surround_sequence(spec)
        for i, side in enumerate(sequence):
            t = -math.pi / 2 + i * 2 * math.pi / len(sequence)
            r_i = side.dimensions_mm.width / 2 * s
            parts += _stone_visual(cx + ring_ax * math.cos(t),
                                   cluster_cy + ring_by * math.sin(t), side,
                                   2 * r_i, 2 * r_i, vocab)
    parts += _stone_visual(cx, cluster_cy, spec.stone, 2 * hw, 2 * hl, vocab,
                           table_ratio=0.62, fill="url(#stone)")
    if drop:
        dw = drop.dimensions_mm.width * s
        dl = drop.dimensions_mm.length * s  # hangs point-down
        sap_cy = cluster_cy + cluster_by + 1.0 * s + dl / 2
        # articulated drop: its jump ring bridges the cluster and the stone
        parts += _link_ring(cx, cluster_cy + cluster_by + 0.5 * s, 0.45 * s)
        parts += _stone_visual(cx, sap_cy, drop, dw, dl, vocab)
    return parts


def _loose_proto(spec: Spec, vocab: Vocabulary) -> list[str]:
    d = spec.stone.dimensions_mm
    s = min(9.0, 60 / max(d.length, d.width))
    cx, cy = SHEET_W / 2, BASELINE
    hw, hl = d.width / 2 * s, d.length / 2 * s
    table = (spec.stone.table_pct or 57) / 100
    return [
        _shadow(cx, cy + hl + 8, hw * 1.1),
        *_stone_visual(cx, cy, spec.stone, 2 * hw, 2 * hl, vocab,
                       table_ratio=table, fill="url(#stone)"),
    ]


def stone_manifest(spec: Spec) -> list[str]:
    """Every stone group on the piece, then the metal — a client must be able
    to read exactly what they are looking at."""
    def name(s) -> str:
        # "Cobalt Spinel" already says spinel — never "Cobalt Spinel spinel"
        if s.species.lower() in s.color.trade.lower():
            return s.color.trade
        return f"{s.color.trade} {s.species}"

    stone = spec.stone
    lead = f"{stone.count} × " if stone.count > 1 else ""
    manifest = [f"{lead}{stone.carat:.2f} ct {name(stone)}, "
                f"{stone.cut.replace('_', ' ')}"]
    position_word = {"halo": "halo", "surround": "surround",
                     "stations": "stations", "under_center": "drop",
                     "drop": "drop"}
    for side in spec.side_stones:
        where = position_word.get(side.position or "", "accent")
        manifest.append(
            f"{side.count} × {side.carat:.2f} ct {name(side)} {where}"
            if side.count > 1 else
            f"{side.carat:.2f} ct {name(side)} {where}")
    if spec.metal:
        karat = f"{spec.metal.karat}k " if spec.metal.karat else ""
        color = f"{spec.metal.color} " if spec.metal.color else ""
        manifest.append(f"{karat}{color}{spec.metal.material}")
    return manifest


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

    caption = "  ·  ".join(stone_manifest(spec))
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
        _text(SHEET_W / 2, SHEET_H - MARGIN - 6, caption,
              size=3.4 if len(caption) <= 105 else 2.8),
        "</svg>",
    ]
    return "\n".join(parts) + "\n"


def prompt_core(spec: Spec) -> tuple[str, list[str]]:
    """The piece name and its spec-true detail phrases — shared by the plain
    render prompt and the scene-controlled mockup requests."""
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

    cut_name = stone.cut.replace("_", " ")
    cut_phrase = cut_name if cut_name.endswith("cut") else f"{cut_name} cut"
    if stone.count > 1:  # station pieces: the count is the design
        details = [
            f"EXACTLY {stone.count} evenly spaced {stone.color.trade} "
            f"{stone.species} stations ({stone.color.gia}), {cut_phrase}, "
            f"each {_fmt(d.length)} x {_fmt(d.width)} mm and {stone.carat:.2f} carat",
        ]
    else:
        details = [
            f"a {stone.carat:.2f} carat {stone.color.trade} {stone.species} "
            f"({stone.color.gia}), {cut_phrase}, "
            f"{_fmt(d.length)} x {_fmt(d.width)} x {_fmt(d.depth)} mm",
        ]
    if spec.metal:
        karat = f"{spec.metal.karat} karat " if spec.metal.karat else ""
        color = f"{spec.metal.color} " if spec.metal.color else ""
        finish = (spec.metal.finish or "high_polish").replace("_", " ")
        details.append(f"set in {karat}{color}{spec.metal.material}, {finish} finish")
    for side in spec.side_stones:
        where = {"halo": "in a halo around the center", "surround": "surrounding the center",
                 "stations": "evenly spaced stations", "under_center": "hanging below the center",
                 "drop": "hanging below the center"}.get(side.position or "", "as accents")
        # phrasing proven against live image models: EXACTLY + relative scale
        # holds counts and stops accents inflating into feature stones
        w = side.dimensions_mm.width
        rel = w / d.width if d.width else 0
        faceted = "" if side.cut == "cabochon" else "faceted "
        scale_note = (f", small accent points at {rel:.0%} of the center's width, "
                      "not feature stones" if 0 < rel < 0.45 else "")
        details.append(
            f"EXACTLY {side.count} x {_fmt(w)} mm "
            f"{faceted}{side.cut.replace('_', ' ')} {side.color.trade} "
            f"{side.species} {where}{scale_note}"
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
    return piece, details


def compile_render_prompt(spec: Spec) -> dict:
    """Spec -> photoreal prompt for an external image model. Dimensional truth
    travels with the prompt; the control image carries the geometry."""
    piece, details = prompt_core(spec)
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

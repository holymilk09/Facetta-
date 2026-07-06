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


def _center_default_mount(spec: Spec) -> str:
    """The center stone's mount when unspecified, read from the setting style."""
    style = (spec.setting.style if spec.setting else "") or ""
    if "bezel" in style:
        return "bezel"
    if "6" in style or (spec.setting and spec.setting.prong_count == 6):
        return "prong_6"
    return "prong_4"


DEFAULT_MOUNTS = {"halo": "shared_prong", "surround": "shared_prong",
                  "stations": "flush", "under_center": "drop_cap",
                  "drop": "drop_cap"}


def _prong_marks(cx, cy, w_pp, l_pp, n, m1, m2, start_deg=45.0) -> list[str]:
    """n claws gripping the stone's rim — radial talons, not dots: each is an
    oval aligned to its radius, half over the girdle, so the grip reads."""
    import math
    claw_l = max(1.7, w_pp * 0.105)   # along the radius
    claw_w = max(1.0, w_pp * 0.062)   # across it
    parts = []
    for i in range(n):
        a = math.radians(start_deg + i * 360 / n)
        px = cx + w_pp / 2 * math.cos(a)
        py = cy + l_pp / 2 * math.sin(a)
        deg = math.degrees(a) + 90  # oval's long axis points at the center
        parts.append(
            f'<g transform="rotate({deg:.1f} {px:.2f} {py:.2f})">'
            f'<ellipse cx="{px:.2f}" cy="{py:.2f}" rx="{claw_w:.2f}" '
            f'ry="{claw_l:.2f}" fill="{m1}" '
            f'stroke="{_mix(m2, "#000000", 0.4)}" stroke-width="0.3"/>'
            f'<ellipse cx="{px - claw_w * 0.22:.2f}" cy="{py - claw_l * 0.28:.2f}" '
            f'rx="{claw_w * 0.34:.2f}" ry="{claw_l * 0.34:.2f}" '
            f'fill="#ffffff" opacity="0.75"/>'
            f'</g>'
        )
    return parts


def _ellipse_arc_angles(a: float, b: float, n: int,
                        start: float = -1.5707963267948966) -> list[float]:
    """n parameter angles spaced by EQUAL ARC LENGTH around an ellipse.

    Equal-angle steps crowd stones near an ellipse's flat ends (that is where
    a degree covers the least distance), which is exactly where surrounds
    pancake. Sampling the perimeter and inverting the cumulative arc length
    gives uniform physical spacing — deterministic, no eyeballing."""
    import math
    m = 1440
    ts = [start + k * 2 * math.pi / m for k in range(m + 1)]
    pts = [(a * math.cos(t), b * math.sin(t)) for t in ts]
    cum = [0.0]
    for i in range(1, m + 1):
        cum.append(cum[-1] + math.hypot(pts[i][0] - pts[i - 1][0],
                                        pts[i][1] - pts[i - 1][1]))
    total = cum[-1]
    angles, j = [], 0
    for k in range(n):
        target = k * total / n
        while cum[j] < target:
            j += 1
        angles.append(ts[j])
    return angles


def _shared_claws(x1, y1, r1, x2, y2, r2, ocx, ocy, m1, m2) -> list[str]:
    """The claw pair at the junction of two neighbouring stones — placed on
    the STATIC no-overlap solution, not by eye.

    A claw center sits at the junction midpoint, pushed radially in/out of
    the ring (real shared prongs grip the girdles from both sides). Its
    radius is then clamped to the actual clearance to the nearer stone:
    r_claw = min(desired, distance_to_stone_center − r_stone − margin).
    Equal-angle spacing crowds an ellipse near its flat ends, so this is
    computed per junction from true coordinates — a claw can shrink to the
    real gap or vanish entirely, but it can never sit on a stone."""
    import math
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    ux, uy = mx - ocx, my - ocy
    norm = math.hypot(ux, uy) or 1.0
    ux, uy = ux / norm, uy / norm
    r_avg = (r1 + r2) / 2
    parts = []
    for sgn in (1, -1):  # a claw outside the ring line, and one inside
        px, py = mx + ux * sgn * r_avg * 0.62, my + uy * sgn * r_avg * 0.62
        clearance = min(math.hypot(px - x1, py - y1) - r1,
                        math.hypot(px - x2, py - y2) - r2)
        br = min(r_avg * 0.36, clearance - 0.15)
        if br < 0.3:
            continue  # girdles truly touch here: no metal fits, none is drawn
        parts.append(
            f'<circle cx="{px:.2f}" cy="{py:.2f}" r="{br:.2f}" fill="{m1}" '
            f'stroke="{_mix(m2, "#000000", 0.35)}" stroke-width="0.25"/>'
            f'<circle cx="{px - br * 0.3:.2f}" cy="{py - br * 0.3:.2f}" '
            f'r="{br * 0.35:.2f}" fill="#ffffff" opacity="0.75"/>'
        )
    return parts


def _v_prong_marks(cx, cy, w_pp, l_pp, m1, m2) -> list[str]:
    """Folded claws cradling the stone's points (length-axis tips)."""
    s = max(1.2, w_pp * 0.11)
    parts = []
    for sign in (-1, 1):
        ty = cy + sign * l_pp / 2
        parts.append(
            f'<path d="M {cx - s:.2f} {ty - sign * s * 0.9:.2f} '
            f'L {cx:.2f} {ty + sign * s * 0.55:.2f} '
            f'L {cx + s:.2f} {ty - sign * s * 0.9:.2f}" fill="none" '
            f'stroke="{m1}" stroke-width="{s * 0.55:.2f}" stroke-linecap="round" '
            f'stroke-linejoin="round"/>'
        )
    return parts


def _bezel_rim(cx, cy, w_pp, l_pp, m1, m2, semi=False) -> list[str]:
    """A metal rim over the girdle; semi leaves two windows open."""
    rim = max(0.7, w_pp * 0.09)
    rx, ry = w_pp / 2 + rim / 2, l_pp / 2 + rim / 2
    if semi:
        return [
            f'<polyline points="{_arc_points(cx, cy, rx, ry, 120, 240)}" fill="none" '
            f'stroke="{m1}" stroke-width="{rim:.2f}" stroke-linecap="round"/>',
            f'<polyline points="{_arc_points(cx, cy, rx, ry, -60, 60)}" fill="none" '
            f'stroke="{m1}" stroke-width="{rim:.2f}" stroke-linecap="round"/>',
        ]
    return [
        f'<ellipse cx="{cx:.2f}" cy="{cy:.2f}" rx="{rx:.2f}" ry="{ry:.2f}" '
        f'fill="none" stroke="{m1}" stroke-width="{rim:.2f}"/>',
        f'<polyline points="{_arc_points(cx, cy, rx, ry, 160, 260)}" fill="none" '
        f'stroke="#ffffff" stroke-width="{rim * 0.35:.2f}" opacity="0.7"/>',
    ]


def _drop_cap(cx, stone_top, w_pp, m1, m2) -> list[str]:
    """The cap-and-pin a drop actually hangs from — over the stone's tip."""
    cap_w = max(2.0, w_pp * 0.40)
    cap_h = cap_w * 0.75
    y0 = stone_top - cap_h * 0.55
    return [
        f'<path d="M {cx - cap_w / 2:.2f} {y0 + cap_h:.2f} '
        f'Q {cx - cap_w / 2:.2f} {y0:.2f} {cx:.2f} {y0:.2f} '
        f'Q {cx + cap_w / 2:.2f} {y0:.2f} {cx + cap_w / 2:.2f} {y0 + cap_h:.2f} Z" '
        f'fill="{m1}" stroke="{_mix(m2, "#000000", 0.3)}" stroke-width="0.3"/>',
        f'<circle cx="{cx - cap_w * 0.18:.2f}" cy="{y0 + cap_h * 0.3:.2f}" '
        f'r="{cap_w * 0.14:.2f}" fill="#ffffff" opacity="0.7"/>',
    ]


def _mount_visual(cx, cy, mount_id, w_pp, l_pp, m1, m2) -> list[str]:
    """Draw a vocabulary setting technique on a placed stone. Tension and
    invisible settings show no metal by definition — that IS their look."""
    if mount_id == "prong_4":
        return _prong_marks(cx, cy, w_pp, l_pp, 4, m1, m2)
    if mount_id == "prong_6":
        return _prong_marks(cx, cy, w_pp, l_pp, 6, m1, m2, start_deg=30)
    if mount_id == "v_prong":
        return _v_prong_marks(cx, cy, w_pp, l_pp, m1, m2)
    if mount_id == "bezel":
        return _bezel_rim(cx, cy, w_pp, l_pp, m1, m2)
    if mount_id == "semi_bezel":
        return _bezel_rim(cx, cy, w_pp, l_pp, m1, m2, semi=True)
    if mount_id in ("pave", "micro_pave"):
        return _prong_marks(cx, cy, w_pp, l_pp, 4, m1, m2, start_deg=0)
    if mount_id == "drop_cap":
        return _drop_cap(cx, cy - l_pp / 2, w_pp, m1, m2)
    return []


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
    m1, m2 = _metal_stops(spec)
    if melee is not None:
        mw = melee.dimensions_mm.width
        mr = mw / 2 * s
        ring_ax = rx + 0.3 * s + mr
        ring_by = ry + 0.3 * s + mr
        halo = f'cx="{cx:.2f}" cy="{cy:.2f}" rx="{ring_ax + mr:.2f}" ry="{ring_by + mr:.2f}"'
        parts += [
            f'<ellipse {halo} fill="{_mix(m1, m2, 0.45)}" stroke="#00000022" stroke-width="0.3"/>',
            *_annulus_lighting(cx, cy, ring_ax - mr, ring_by - mr,
                               ring_ax + mr, ring_by + mr, m1, m2),
            f'<ellipse cx="{cx:.2f}" cy="{cy:.2f}" rx="{ring_ax - mr:.2f}" '
            f'ry="{ring_by - mr:.2f}" fill="{paper}"/>',
        ]
        mount = melee.mount or "shared_prong"
        placed = [(cx + ring_ax * math.cos(t), cy + ring_by * math.sin(t), mr)
                  for t in _ellipse_arc_angles(ring_ax, ring_by, melee.count)]
        claws, stones, mounts = [], [], []
        for i, (sx, sy, r_i) in enumerate(placed):
            stones += _stone_visual(sx, sy, melee, 2 * mr, 2 * mr, vocab)
            if mount == "shared_prong":
                nx, ny, r_n = placed[(i + 1) % melee.count]
                claws += _shared_claws(sx, sy, r_i, nx, ny, r_n, cx, cy, m1, m2)
            else:
                mounts += _mount_visual(sx, sy, mount, 2 * mr, 2 * mr, m1, m2)
        parts += claws + stones + mounts
    parts += _stone_visual(cx, cy, spec.stone, 2 * rx, 2 * ry, vocab,
                           fill="url(#stone)")
    parts += _mount_visual(cx, cy,
                           spec.stone.mount or _center_default_mount(spec),
                           2 * rx, 2 * ry, m1, m2)
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
        mount = stone.mount or DEFAULT_MOUNTS.get("stations", "flush")
        if mount == "channel":
            # two rails the stones sit between, girdle to girdle
            for off in (side / 2 + 0.8, -(side / 2 + 0.8)):
                parts.append(
                    f'<ellipse cx="{cx:.2f}" cy="{cy:.2f}" rx="{a_c + off:.2f}" '
                    f'ry="{b_c + off:.2f}" fill="none" stroke="{m1}" '
                    f'stroke-width="0.9" opacity="0.9"/>'
                )
        for i in range(stone.count):
            t = -math.pi / 2 + i * 2 * math.pi / stone.count
            px, py = cx + a_c * math.cos(t), cy + b_c * math.sin(t)
            angle = math.degrees(math.atan2(b_c * math.cos(t), -a_c * math.sin(t)))
            inset = side * 0.32
            group = f'<g transform="rotate({angle:.1f} {px:.2f} {py:.2f})">'
            if mount in ("flush", "bezel"):
                group += (
                    f'<rect x="{px - seat / 2:.2f}" y="{py - seat / 2:.2f}" width="{seat:.2f}" '
                    f'height="{seat:.2f}" rx="{seat * 0.12:.2f}" fill="{_mix(m2, "#000000", 0.12)}"/>'
                    f'<rect x="{px - seat / 2:.2f}" y="{py - seat / 2:.2f}" width="{seat:.2f}" '
                    f'height="{seat:.2f}" rx="{seat * 0.12:.2f}" fill="none" '
                    f'stroke="{_mix(m1, "#FFFFFF", 0.4)}" stroke-width="0.35"/>'
                )
            elif mount == "bar":
                bar_w = side * 0.34
                group += (
                    f'<rect x="{px - side / 2 - bar_w - 0.5:.2f}" y="{py - seat / 2:.2f}" '
                    f'width="{bar_w:.2f}" height="{seat:.2f}" fill="{m1}" '
                    f'stroke="{_mix(m2, "#000000", 0.3)}" stroke-width="0.25"/>'
                    f'<rect x="{px + side / 2 + 0.5:.2f}" y="{py - seat / 2:.2f}" '
                    f'width="{bar_w:.2f}" height="{seat:.2f}" fill="{m1}" '
                    f'stroke="{_mix(m2, "#000000", 0.3)}" stroke-width="0.25"/>'
                )
            group += (
                f'<rect x="{px - side / 2:.2f}" y="{py - side / 2:.2f}" width="{side:.2f}" '
                f'height="{side:.2f}" fill="{fill}" stroke="{edge}" stroke-width="0.3"/>'
                f'<rect x="{px - side / 2 + inset:.2f}" y="{py - side / 2 + inset:.2f}" '
                f'width="{side - 2 * inset:.2f}" height="{side - 2 * inset:.2f}" '
                f'fill="none" stroke="{edge}" stroke-width="0.25"/>'
                f'<circle cx="{px - side * 0.18:.2f}" cy="{py - side * 0.18:.2f}" '
                f'r="{side * 0.1:.2f}" fill="#ffffff" opacity="0.8"/>'
            )
            if mount == "prong_4":
                group += "".join(_prong_marks(px, py, side, side, 4, m1, m2))
            group += "</g>"
            parts.append(group)
    return parts


def _pendant_proto(spec: Spec, vocab: Vocabulary,
                   cx: float = SHEET_W / 2) -> list[str]:
    import math

    s = 5.0
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
    m1, m2 = _metal_stops(spec)
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
        n = len(sequence)
        placed = []
        for t, side in zip(_ellipse_arc_angles(ring_ax, ring_by, n), sequence):
            r_i = side.dimensions_mm.width / 2 * s
            placed.append((cx + ring_ax * math.cos(t),
                           cluster_cy + ring_by * math.sin(t), r_i, side))
        # claws first (they grip from behind), stones on top, other mounts last
        claws, stones, mounts = [], [], []
        for i, (sx, sy, r_i, side) in enumerate(placed):
            stones += _stone_visual(sx, sy, side, 2 * r_i, 2 * r_i, vocab)
            mount = side.mount or DEFAULT_MOUNTS.get(side.position or "",
                                                     "shared_prong")
            if mount == "shared_prong":
                nx, ny, r_n, _ = placed[(i + 1) % n]
                claws += _shared_claws(sx, sy, r_i, nx, ny, r_n,
                                       cx, cluster_cy, m1, m2)
            else:
                mounts += _mount_visual(sx, sy, mount, 2 * r_i, 2 * r_i, m1, m2)
        parts += claws + stones + mounts
    parts += _stone_visual(cx, cluster_cy, spec.stone, 2 * hw, 2 * hl, vocab,
                           table_ratio=0.62, fill="url(#stone)")
    parts += _mount_visual(cx, cluster_cy,
                           spec.stone.mount or _center_default_mount(spec),
                           2 * hw, 2 * hl, m1, m2)
    if drop:
        dw = drop.dimensions_mm.width * s
        dl = drop.dimensions_mm.length * s  # hangs point-down
        sap_cy = cluster_cy + cluster_by + 1.0 * s + dl / 2
        # articulated drop: its jump ring bridges the cluster and the stone
        parts += _link_ring(cx, cluster_cy + cluster_by + 0.5 * s, 0.45 * s)
        parts += _stone_visual(cx, sap_cy, drop, dw, dl, vocab)
        parts += _mount_visual(cx, sap_cy, drop.mount or "drop_cap",
                               dw, dl, m1, m2)
    return parts


SPRAY_PROTO_SCALE = 2.6


def _melee_dot(cx: float, cy: float, r: float) -> str:
    """A pavé stone too small for a facet pattern: bright dome, one sparkle."""
    return (
        f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}" fill="url(#melee)" '
        f'stroke="#00000033" stroke-width="0.2"/>'
        f'<circle cx="{cx - r * 0.3:.2f}" cy="{cy - r * 0.3:.2f}" '
        f'r="{r * 0.3:.2f}" fill="#ffffff" opacity="0.85"/>'
    )


def _spray_origin(lay: dict, s: float) -> tuple[float, float]:
    """Page origin that centers the spray's true extents on the sheet."""
    ox = SHEET_W / 2 - lay["length"] * s / 2
    oy = BASELINE - (lay["y_top"] + lay["bottom"]) / 2 * s
    return ox, oy


def _spray_proto(spec: Spec, vocab: Vocabulary,
                 s: float = SPRAY_PROTO_SCALE) -> list[str]:
    """The leaf spray in color: gold branch and leaves, pavé, quatrefoil
    clusters with claws — every position from the same layout the ink
    sheet draws, so the two can never disagree."""
    import math

    from facetta.svg_sheet import _bezier_tangent, _bezier_xy, _spray_layout

    lay = _spray_layout(spec)
    ox, oy = _spray_origin(lay, s)

    def pp(pt):
        return ox + pt[0] * s, oy + pt[1] * s

    m1, m2 = _metal_stops(spec)
    edge = _mix(m2, "#000000", 0.3)
    q0, q1, q2 = lay["stem"]
    upper, lower = [], []
    for i in range(25):
        t = i / 24
        bx, by = _bezier_xy(q0, q1, q2, t)
        ux, uy = _bezier_tangent(q0, q1, q2, t)
        w = (0.7 + 1.5 * t) / 2
        upper.append(pp((bx + uy * w, by - ux * w)))
        lower.append(pp((bx - uy * w, by + ux * w)))
    vein_pts = " ".join(f"{x:.2f},{y:.2f}" for x, y in upper + lower[::-1])
    parts = [
        _shadow(SHEET_W / 2, oy + lay["bottom"] * s + 10, lay["length"] * s / 3),
        f'<polygon points="{vein_pts}" fill="url(#metal)" stroke="{edge}" '
        f'stroke-width="0.3"/>',
        f'<polygon points="{vein_pts}" fill="url(#sheen)"/>',
    ]
    for leaf in lay["leaves"]:
        cxl, cyl = pp(leaf["center"])
        parts.append(
            f'<g transform="rotate({leaf["deg"]:.1f} {cxl:.2f} {cyl:.2f})">'
            f'<ellipse cx="{cxl:.2f}" cy="{cyl:.2f}" rx="{leaf["rx"] * s:.2f}" '
            f'ry="{leaf["ry"] * s:.2f}" fill="url(#metal)" stroke="{edge}" '
            f'stroke-width="0.3"/>'
            f'<ellipse cx="{cxl:.2f}" cy="{cyl:.2f}" rx="{leaf["rx"] * s:.2f}" '
            f'ry="{leaf["ry"] * s:.2f}" fill="url(#sheen)"/></g>')
        for mx, my, mr in leaf["stones"]:
            parts.append(_melee_dot(*pp((mx, my)), mr * s))
    parts += _link_ring(*pp(lay["catch"]), 2.0 * s)
    for (x, y, d, petal), center in zip(lay["clusters"], lay["center_of"]):
        cx, cy = pp((x, y))
        r_pp = d / 2 * s
        parts.append(
            f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r_pp:.2f}" fill="none" '
            f'stroke="{m1}" stroke-width="{0.30 * s:.2f}"/>')
        n_beads = max(8, round(math.pi * d / 1.1))
        for i in range(n_beads):  # fine beaded frame, as the artwork draws it
            a = 2 * math.pi * i / n_beads
            bx = cx + r_pp * math.cos(a)
            by = cy + r_pp * math.sin(a)
            parts.append(
                f'<circle cx="{bx:.2f}" cy="{by:.2f}" r="{0.35 * s:.2f}" '
                f'fill="{m1}" stroke="{edge}" stroke-width="0.15"/>')
        pw = petal.dimensions_mm.width * s
        pl = petal.dimensions_mm.length * s
        hub = r_pp - 0.8 * s - pl
        for k in range(4):
            theta = 45 + 90 * k  # petals on the diagonals, as drawn
            r_mid = hub + pl / 2
            px = cx + r_mid * math.cos(math.radians(theta))
            py = cy + r_mid * math.sin(math.radians(theta))
            parts.append(
                f'<g transform="rotate({(theta + 270) % 360} {px:.2f} {py:.2f})">')
            parts += _stone_visual(px, py, petal, pw, pl, vocab)
            parts.append("</g>")
        if center is not None:
            cw = center.dimensions_mm.width * s
            parts += _stone_visual(cx, cy, center, cw, cw, vocab)
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
                     "drop": "drop", "quatrefoil_stations": "cluster petals",
                     "quatrefoil_centers": "cluster centers",
                     "pave_leaves": "pavé leaves"}
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
    elif spec.template == "leaf_spray_brooch":
        body = _spray_proto(spec, vocab)
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
        "leaf_spray_brooch": "leaf-spray brooch — a single curved branch",
    }.get(spec.template, spec.template)

    cut_name = stone.cut.replace("_", " ")
    cut_phrase = cut_name if cut_name.endswith("cut") else f"{cut_name} cut"
    if stone.position == "terminal_quatrefoil":
        details = [
            f"EXACTLY {stone.count} {stone.color.trade} {stone.species} petals "
            f"({stone.color.gia}), {cut_phrase}, each "
            f"{_fmt(d.length)} x {_fmt(d.width)} mm, points meeting at a "
            "small hub — the large terminal quatrefoil cluster at the tip",
        ]
    elif stone.count > 1:  # station pieces: the count is the design
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
                 "drop": "hanging below the center",
                 "quatrefoil_stations": "as quatrefoil clusters of four along the branch, "
                                        "graduated toward the terminal",
                 "quatrefoil_centers": "one at the heart of each quatrefoil cluster",
                 "pave_leaves": "pavé set across the branch's leaves",
                 }.get(side.position or "", "as accents")
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

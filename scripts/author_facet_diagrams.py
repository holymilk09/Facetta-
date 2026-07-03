"""Author the bundled GemCad .ASC facet diagrams in data/facet_diagrams/.

Each design is computed the way a faceter cuts: girdle first, then every
tier's plane distance is solved so facets pass exactly through their
meetpoints (culet, girdle corners, table-edge meets). The output is genuine
GemCad .ASC — the same format FacetDiagrams.org, the USFG directory and The
Gemology Project distribute — so downloaded designs and bundled ones flow
through the identical parser in facetta.gemcad.

Angles follow published standard proportions: the Tolkowsky-derived standard
round brilliant, and conventional oval/princess/step-cut layouts.

Run:  uv run python scripts/author_facet_diagrams.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "facet_diagrams"
GEAR = 96


def u_vec(az_deg: float) -> tuple[float, float]:
    """Azimuth 0 = 12 o'clock, clockwise — matches facetta.gemcad."""
    a = math.radians(az_deg)
    return math.sin(a), -math.cos(a)


def idx(az_deg: float) -> int:
    i = round(az_deg / 360 * GEAR) % GEAR
    return GEAR if i == 0 else i


def normal(side: str, angle_deg: float, az_deg: float):
    a = math.radians(angle_deg)
    ux, uy = u_vec(az_deg)
    if side == "girdle":
        return (ux, uy, 0.0)
    nz = math.cos(a) if side == "crown" else -math.cos(a)
    return (math.sin(a) * ux, math.sin(a) * uy, nz)


def dot(n, p):
    return n[0] * p[0] + n[1] * p[1] + n[2] * p[2]


def solve3(p1, p2, p3):
    """Intersection point of three planes (normal, distance)."""
    rows = [p1, p2, p3]
    a = [[r[0][0], r[0][1], r[0][2], r[1]] for r in rows]
    for c in range(3):  # gaussian elimination with partial pivot
        piv = max(range(c, 3), key=lambda r: abs(a[r][c]))
        a[c], a[piv] = a[piv], a[c]
        for r in range(3):
            if r != c and abs(a[c][c]) > 1e-12:
                f = a[r][c] / a[c][c]
                a[r] = [x - f * y for x, y in zip(a[r], a[c])]
    return tuple(a[i][3] / a[i][i] for i in range(3))


def line_intersect_2d(u1, d1, u2, d2):
    """Point where lines u1·p = d1 and u2·p = d2 meet."""
    det = u1[0] * u2[1] - u1[1] * u2[0]
    x = (d1 * u2[1] - d2 * u1[1]) / det
    y = (u1[0] * d2 - u2[0] * d1) / det
    return x, y


class Asc:
    def __init__(self, title: str, note: str):
        self.lines = [f"g {GEAR} 0.", "I 1.54", f"H {title}", f"F {note}"]

    def tier(self, side, angle, distance, azimuths, name):
        indices = " ".join(str(idx(a)) for a in azimuths)
        a = 0.0 if side == "table" else (90.0 if side == "girdle" else angle)
        # GemCad names are single tokens after an ``n`` marker — bare integers
        # anywhere else on the line are gear indices, so never leave them loose
        slug = name.replace(" ", "-")
        self.lines.append(f"a {a:.2f} {distance:.5f} {indices} n {slug}")

    def write(self, path: Path):
        path.write_text("\n".join(self.lines) + "\n")
        print(f"wrote {path.name}: {len(self.lines) - 4} tiers")


# --- round brilliant: the 57-facet standard -----------------------------------


def round_brilliant():
    g = 0.06                       # girdle band height (3% of the 2.0 diameter)
    zp = 0.86                      # pavilion depth, 43% of diameter
    d_g = math.cos(math.pi / 16)   # 16-gon girdle, corners at radius 1
    mains_az = [k * 45.0 for k in range(8)]
    halves_az = [11.25 + k * 22.5 for k in range(16)]
    stars_az = [22.5 + k * 45.0 for k in range(8)]

    asc = Asc("Facetta standard round brilliant - 57 facets",
              "authored from published Tolkowsky-derived proportions")

    a_pm = math.degrees(math.atan(zp / 1.0))       # mains: culet to girdle corner
    asc.tier("pavilion", a_pm, zp * math.cos(math.radians(a_pm)),
             mains_az, "n1 pavilion mains")
    a_lh = 42.2                                     # lower halves through corners
    asc.tier("pavilion", a_lh, math.sin(math.radians(a_lh)) * math.cos(math.radians(11.25)),
             halves_az, "n2 lower girdle halves")
    asc.tier("girdle", 90.0, d_g, halves_az, "girdle")

    a_cm, a_uh, a_st, t = 34.5, 41.0, 15.0, 0.56
    d_cm = math.sin(math.radians(a_cm)) + math.cos(math.radians(a_cm)) * g
    asc.tier("crown", a_cm, d_cm, mains_az, "n3 crown mains")
    d_uh = (math.sin(math.radians(a_uh)) * math.cos(math.radians(11.25))
            + math.cos(math.radians(a_uh)) * g)
    asc.tier("crown", a_uh, d_uh, halves_az, "n4 upper girdle halves")
    z_t = (d_cm - t * math.sin(math.radians(a_cm))) / math.cos(math.radians(a_cm))
    # stars pass through both adjacent mains' table-edge points, so the table
    # closes as the classic octagon with its corners at the main azimuths
    a_pt = (*(x * t for x in u_vec(0.0)), z_t)
    asc.tier("crown", a_st, dot(normal("crown", a_st, 22.5), a_pt), stars_az,
             "n5 stars")
    asc.tier("table", 0.0, z_t, [0.0], "T table")
    asc.write(OUT_DIR / "round_brilliant.asc")


# --- brilliant on a curved outline: oval / cushion ----------------------------


def curved_brilliant(name: str, filename: str, support, note: str,
                     zp_frac: float = 0.86, table: float = 0.58):
    """Oval-family brilliant: 16-gon girdle tangent to the outline curve.

    `support(u)` is the outline's support distance in direction u — the exact
    girdle plane distance. Mains change angle per azimuth (as real oval
    cutting does) so each passes through the culet AND its girdle corner.
    """
    g = 0.05
    halves_az = [11.25 + k * 22.5 for k in range(16)]
    mains_az = [k * 45.0 for k in range(8)]
    stars_az = [22.5 + k * 45.0 for k in range(8)]
    d_g = {az: support(u_vec(az)) for az in halves_az}
    # girdle corners: adjacent tangent planes intersected in 2D
    corner = {}
    for k in range(16):
        az1, az2 = halves_az[k - 1], halves_az[k]
        corner[(k * 22.5) % 360] = line_intersect_2d(
            u_vec(az1), d_g[az1], u_vec(az2), d_g[az2])
    a_x = max(abs(c[0]) for c in corner.values())
    zp = zp_frac * a_x  # pavilion depth measured off the narrow (width) axis

    asc = Asc(name, note)

    def reach(az):  # how far the girdle corner lies along the facet direction
        return dot((*u_vec(az), 0.0), (*corner[az % 360], 0.0))

    # pavilion mains: per-azimuth angle, through culet and their corner
    for az in mains_az:
        a = math.degrees(math.atan(zp / reach(az)))
        asc.tier("pavilion", a, zp * math.cos(math.radians(a)), [az],
                 f"n1 pavilion main {int(az)}")
    # lower halves: through their girdle facet's bottom edge, slightly steeper
    for az in halves_az:
        a = math.degrees(math.atan(zp / d_g[az])) + 2.0
        asc.tier("pavilion", a, math.sin(math.radians(a)) * d_g[az], [az],
                 f"n2 lower half {int(az * 10)}")
    for az in halves_az:
        asc.tier("girdle", 90.0, d_g[az], [az], "girdle")

    # crown: one table plane; narrow-axis main fixed at 34.5deg sets its height
    r90 = reach(90.0)
    z_t = g + math.tan(math.radians(34.5)) * r90 * (1 - table)
    d_cm = {}
    a_cm = {}
    for az in mains_az:
        r = reach(az)
        a = math.degrees(math.atan((z_t - g) / (r * (1 - table))))
        a_cm[az], d_cm[az] = a, (math.sin(math.radians(a)) * r
                                 + math.cos(math.radians(a)) * g)
        asc.tier("crown", a, d_cm[az], [az], f"n3 crown main {int(az)}")
    for az in halves_az:
        base = math.degrees(math.atan((z_t - g) / (d_g[az] * (1 - table))))
        a = base + 6.5
        asc.tier("crown", a, (math.sin(math.radians(a)) * d_g[az]
                              + math.cos(math.radians(a)) * g), [az],
                 f"n4 upper half {int(az * 10)}")
    # stars: through both adjacent mains' table-edge points (deepest wins)
    for az in stars_az:
        m1, m2 = (az - 22.5) % 360, (az + 22.5) % 360
        a = max(10.0, min(a_cm[m1], a_cm[m2]) - 19.0)
        n = normal("crown", a, az)
        d = min(dot(n, (*(x * table * reach(m)
                          for x in u_vec(m)), z_t)) for m in (m1, m2))
        asc.tier("crown", a, d, [az], f"n5 star {int(az * 10)}")
    asc.tier("table", 0.0, z_t, [0.0], "T table")
    asc.write(OUT_DIR / filename)


def ellipse_support(a: float, b: float):
    def support(u):
        return math.sqrt(a * a * u[0] * u[0] + b * b * u[1] * u[1])
    return support


def superellipse_support(a: float, b: float, n: float):
    pts = []
    for k in range(1440):
        th = math.pi * k / 720
        c, s = math.cos(th), math.sin(th)
        pts.append((a * math.copysign(abs(c) ** (2 / n), c),
                    b * math.copysign(abs(s) ** (2 / n), s)))

    def support(u):
        return max(u[0] * x + u[1] * y for x, y in pts)
    return support


# --- step cuts: emerald / asscher ----------------------------------------------


def step_cut(name: str, filename: str, a: float, b: float, cut_frac: float,
             note: str, rows=(46.0, 37.0, 27.0)):
    """Octagonal step cut: concentric crown rows, each meeting the last."""
    g = 0.05
    cc = cut_frac * a  # corner cut, measured along each side
    sides = {0.0: b, 180.0: b, 90.0: a, 270.0: a}
    d_c = math.cos(math.radians(45)) * (a + b - cc)
    az8 = [0.0, 45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0]
    d_g = {az: (d_c if az % 90 else sides[az]) for az in az8}

    asc = Asc(name, note)

    # pavilion: two step tiers closing to a keel (depth measured positive down)
    z_step = 0.35 * 2 * a
    r_at = dict(d_g)
    for i, a_p in enumerate((50.0, 42.0)):
        s, c = math.sin(math.radians(a_p)), math.cos(math.radians(a_p))
        z0 = i * z_step
        for az in az8:
            asc.tier("pavilion", a_p, s * r_at[az] + c * z0, [az],
                     f"pav step {i + 1} az{int(az)}")
        r_at = {az: r_at[az] - z_step / math.tan(math.radians(a_p))
                for az in az8}
    for az in az8:
        asc.tier("girdle", 90.0, d_g[az], [az], "girdle")

    # crown: three rows, each tier's plane through the previous row's rim
    ch = 0.32 * a
    heights = [g, g + 0.40 * ch, g + 0.72 * ch, g + ch]  # last = table height
    r_at = dict(d_g)
    for i, a_c in enumerate(rows):
        s, c = math.sin(math.radians(a_c)), math.cos(math.radians(a_c))
        z0, z1 = heights[i], heights[i + 1]
        for az in az8:
            asc.tier("crown", a_c, s * r_at[az] + c * z0, [az],
                     f"crown step {i + 1} az{int(az)}")
        r_at = {az: r_at[az] - (z1 - z0) / math.tan(math.radians(a_c))
                for az in az8}
    asc.tier("table", 0.0, heights[-1], [0.0], "T table")
    asc.write(OUT_DIR / filename)


# --- princess -------------------------------------------------------------------


def princess():
    g = 0.05
    zp = 1.4
    asc = Asc("Facetta princess - chevron crown, square girdle",
              "authored from conventional princess-cut proportions")
    sides_az = [0.0, 90.0, 180.0, 270.0]
    corners_az = [45.0, 135.0, 225.0, 315.0]

    a_pm = math.degrees(math.atan(zp / 1.0))
    asc.tier("pavilion", a_pm, zp * math.cos(math.radians(a_pm)), sides_az,
             "n1 pavilion mains")
    a_pc = 58.0
    asc.tier("pavilion", a_pc, math.sin(math.radians(a_pc)) * math.sqrt(2.0),
             corners_az, "n2 pavilion corners")
    asc.tier("girdle", 90.0, 1.0, sides_az, "girdle")
    asc.tier("girdle", 90.0, math.cos(math.radians(45)) * 2 * 0.985, corners_az,
             "girdle corners")  # tiny corner chamfer, keeps corners crisp

    t = 0.66
    a_cm, a_cb, a_ch = 34.0, 40.0, 27.0
    d_cm = math.sin(math.radians(a_cm)) + math.cos(math.radians(a_cm)) * g
    asc.tier("crown", a_cm, d_cm, sides_az, "n3 side mains")
    z_t = (d_cm - t * math.sin(math.radians(a_cm))) / math.cos(math.radians(a_cm))
    # corner bezels through the chamfer's top edge
    d_chamfer = math.cos(math.radians(45)) * 2 * 0.985
    d_cb = (math.sin(math.radians(a_cb)) * d_chamfer
            + math.cos(math.radians(a_cb)) * g)
    asc.tier("crown", a_cb, d_cb, corners_az, "n4 corner bezels")
    # fan chevrons: each anchors where its corner bezel meets the side girdle
    # top edge, rising inward shallower than the mains so it cuts a fan from
    # near the corner up to the table edge — corners stay protected
    for az in sides_az:
        for daz in (-11.25, 11.25):
            e = solve3((normal("crown", a_cb, az + math.copysign(45, daz)), d_cb),
                       (normal("girdle", 90.0, az), 1.0),
                       ((0.0, 0.0, 1.0), g))
            asc.tier("crown", a_ch, dot(normal("crown", a_ch, az + daz), e),
                     [az + daz], f"n5 chevron {int((az + daz) * 10) % 3600}")
    asc.tier("table", 0.0, z_t, [0.0], "T table")
    asc.write(OUT_DIR / "princess.asc")


# --- freeform brilliants: pear / marquise / trillion --------------------------
# Tier angles come from data/reference/facet_blueprints.csv (research-sourced
# 96-index layouts); the published index lists are partial, so the outline is
# completed with a support curve and every filled azimuth borrows the nearest
# published angle. Distances are meetpoint-solved as everywhere else.


def nearest_angle(table: dict[float, float]):
    def angle(az: float) -> float:
        az %= 360
        return table[min(table, key=lambda a: min(abs(a - az), 360 - abs(a - az)))]
    return angle


def freeform_brilliant(name: str, filename: str, support, girdle_az, pav_planes,
                       crown_angle, star_az, star_angle, table: float,
                       ref_az: float, note: str):
    """Brilliant on an arbitrary convex outline.

    girdle_az: tangent-plane azimuths; pav_planes: (az, angle) pavilion tiers
    through the outline tangent at z=0; crown_angle(az): break angle per
    azimuth, anchored on the girdle top edge; stars anchor where their two
    nearest breaks cross the table plane. ref_az fixes the table height.
    """
    g = 0.05
    asc = Asc(name, note)
    d_g = {az: support(u_vec(az)) for az in girdle_az}

    for az, a in pav_planes:
        asc.tier("pavilion", a, math.sin(math.radians(a)) * support(u_vec(az)),
                 [az], f"n1 pav {int(az * 100)}")
    for az in girdle_az:
        asc.tier("girdle", 90.0, d_g[az], [az], "girdle")

    a_ref = crown_angle(ref_az) if crown_angle else 36.0
    z_t = g + math.tan(math.radians(a_ref)) * d_g[ref_az] * (1 - table)
    breaks: dict[float, tuple[float, float]] = {}
    for az in girdle_az:
        if crown_angle:
            a = crown_angle(az)
        else:
            # table-coherent break: its table trace lands at table*support
            # along its own azimuth, so the table closes as one clean polygon
            a = math.degrees(math.atan((z_t - g) / (d_g[az] * (1 - table))))
        d = math.sin(math.radians(a)) * d_g[az] + math.cos(math.radians(a)) * g
        breaks[az] = (a, d)
        asc.tier("crown", a, d, [az], f"n2 break {int(az * 100)}")
    for az_s in star_az:
        near = sorted(girdle_az, key=lambda a: min(abs(a - az_s), 360 - abs(a - az_s)))[:2]
        a_s = star_angle if star_angle else max(12.0, min(breaks[m][0] for m in near) - 19.0)
        d_s = None
        for m in near:
            a_m, d_m = breaks[m]
            r_m = (d_m - math.cos(math.radians(a_m)) * z_t) / math.sin(math.radians(a_m))
            p = (*(x * r_m for x in u_vec(m)), z_t)
            d_here = dot(normal("crown", a_s, az_s), p)
            d_s = d_here if d_s is None else min(d_s, d_here)
        asc.tier("crown", a_s, d_s, [az_s], f"n3 star {int(az_s * 100)}")
    asc.tier("table", 0.0, z_t, [0.0], "T table")
    asc.write(OUT_DIR / filename)


def sampled_support(points):
    def support(u):
        return max(u[0] * x + u[1] * y for x, y in points)
    return support


def pear_outline(a: float = 0.62, sharpen: float = 0.28):
    """Egg curve, round head, pointed tip at azimuth 0 (12 o'clock)."""
    pts = []
    for k in range(1, 1440):
        y = math.cos(math.pi * k / 720)  # -1 head .. +1 tip (screen y is down)
        w = a * math.sqrt(max(0.0, 1 - y * y)) * ((1 - y) / 2) ** sharpen
        pts.append((w, y))
        pts.append((-w, y))
    pts.append((0.0, -1.0))
    pts.append((0.0, 1.0))
    # tip points up on screen: flip so the sharp end faces azimuth 0
    return [(x, -y) for x, y in pts]


def marquise_outline(a: float = 0.48):
    """Lens of two circular arcs, points at azimuths 0 and 180."""
    c = (1 - a * a) / (2 * a)  # arc center offset so the arcs meet at (0, ±1)
    r = a + c
    half = math.asin(1 / r)
    pts = []
    for k in range(-720, 721):
        t = half * k / 720  # arc centered at (-c, 0) bulging toward +x
        pts.append((r * math.cos(t) - c, r * math.sin(t)))
    pts += [(-x, y) for x, y in pts]
    return pts


def trillion_outline(bulge: float = 0.16):
    """Rounded triangle, one point at azimuth 0, convex sides."""
    pts = []
    for k in range(1440):
        th = 2 * math.pi * k / 1440
        r = 1 + bulge * math.cos(3 * th)
        pts.append((r * math.sin(th), -r * math.cos(th)))
    return pts


def pear():
    girdle_az = [0.0, 22.5, 45.0, 67.5, 90.0, 105.0, 127.5, 150.0, 180.0,
                 210.0, 232.5, 255.0, 270.0, 292.5, 315.0, 337.5]
    pav = nearest_angle({0.0: 42.18, 90.0: 42.18, 270.0: 42.18,
                         105.0: 41.68, 255.0: 41.68, 180.0: 41.68})
    stars = [11.25, 33.75, 78.75, 116.25, 165.0, 195.0, 243.75, 281.25,
             326.25, 348.75]
    freeform_brilliant(
        "Facetta pear brilliant - egg girdle, pointed tip", "pear.asc",
        sampled_support(pear_outline()), girdle_az,
        [(az, pav(az)) for az in girdle_az], None, stars, None,
        table=0.58, ref_az=90.0,
        note="pavilion angles from data/reference/facet_blueprints.csv "
             "(pear rows); crown solved table-coherent on a flat girdle plane")


def marquise():
    girdle_az = [0.0, 7.5, 22.5, 30.0, 45.0, 90.0, 135.0, 150.0, 157.5,
                 172.5, 180.0, 187.5, 202.5, 210.0, 225.0, 270.0, 315.0,
                 330.0, 337.5, 352.5]
    pav_table = {7.5: 52.0, 352.5: 52.0, 172.5: 52.0, 187.5: 52.0,
                 15.0: 49.25, 345.0: 49.25, 165.0: 49.25, 195.0: 49.25,
                 37.5: 43.0, 322.5: 43.0, 142.5: 43.0, 217.5: 43.0,
                 22.5: 49.0, 337.5: 49.0, 157.5: 49.0, 202.5: 49.0,
                 30.0: 46.82, 330.0: 46.82, 150.0: 46.82, 210.0: 46.82,
                 45.0: 42.0, 315.0: 42.0, 135.0: 42.0, 225.0: 42.0,
                 90.0: 42.0, 270.0: 42.0, 0.0: 52.0, 180.0: 52.0}
    stars = [45.0, 135.0, 225.0, 315.0, 67.5, 112.5, 247.5, 292.5]
    freeform_brilliant(
        "Facetta marquise brilliant - lens girdle, pointed ends", "marquise.asc",
        sampled_support(marquise_outline()), girdle_az,
        sorted(pav_table.items()), None, stars, 24.76,
        table=0.55, ref_az=90.0,
        note="pavilion angles from data/reference/facet_blueprints.csv "
             "(marquise rows); crown solved table-coherent on a flat girdle plane")


def trillion():
    girdle_az = [0.0, 30.0, 90.0, 120.0, 150.0, 210.0, 240.0, 270.0, 330.0]
    pav_planes = ([(az, 41.0) for az in (0.0, 120.0, 240.0)]
                  + [(az, 36.3) for az in (48.75, 131.25, 228.75, 311.25)]
                  + [(az, 34.2) for az in (75.0, 105.0, 255.0, 285.0)]
                  + [(az, 38.0) for az in (30.0, 90.0, 150.0, 210.0, 270.0, 330.0)])
    crown = nearest_angle({0.0: 37.0})  # dataset: 37 deg on every break index
    stars = [60.0, 180.0, 300.0]
    freeform_brilliant(
        "Facetta trillion brilliant - rounded triangle", "trillion.asc",
        sampled_support(trillion_outline()), girdle_az,
        pav_planes, crown, stars, 17.35,
        table=0.55, ref_az=30.0,
        note="tier angles from data/reference/facet_blueprints.csv (trillion rows)")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    round_brilliant()
    # oval_brilliant.asc is NOT authored here: it carries a genuine published
    # design (Robert H. Long, PC 02.113A "Milli", Datavue2 1991) — never
    # overwrite real diagram data with a synthetic one.
    curved_brilliant("Facetta cushion brilliant - pillow girdle",
                     "cushion.asc", superellipse_support(0.85, 1.0, 2.6),
                     "authored from conventional cushion brilliant layouts")
    princess()
    step_cut("Facetta emerald cut - three step rows", "emerald_cut.asc",
             a=0.778, b=1.0, cut_frac=0.40,
             note="authored from conventional emerald-cut proportions")
    step_cut("Facetta asscher - square step cut", "asscher.asc",
             a=1.0, b=1.0, cut_frac=0.42,
             note="authored from conventional asscher proportions")
    step_cut("Facetta radiant - cropped corners, stepped crown", "radiant.asc",
             a=0.82, b=1.0, cut_frac=0.35, rows=(42.0, 35.0, 24.0),
             note="crown step angles from data/reference/facet_blueprints.csv "
                  "(radiant rows)")
    pear()
    marquise()
    trillion()
    return 0


if __name__ == "__main__":
    sys.exit(main())

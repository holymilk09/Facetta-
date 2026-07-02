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
        self.lines.append(f"a {a:.2f} {distance:.5f} {indices} {name}")

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


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    round_brilliant()
    curved_brilliant("Facetta oval brilliant - 8 mains, stars, halves",
                     "oval_brilliant.asc", ellipse_support(0.744, 1.0),
                     "authored from conventional oval brilliant layouts")
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
    return 0


if __name__ == "__main__":
    sys.exit(main())

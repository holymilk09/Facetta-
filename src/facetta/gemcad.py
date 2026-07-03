"""GemCad .ASC facet-diagram engine.

Parses GemCad ASCII faceting blueprints — the open interchange format used by
FacetDiagrams.org, the USFG design directory and The Gemology Project — and
reconstructs the cut stone deterministically: every ``a`` line defines a plane
(cutting angle from the girdle plane, perpendicular distance, index-gear
azimuths); the stone is the intersection of those half-spaces; the face-up
layout is the crown projected straight down. No drawing is invented — the
facet polygons ARE the diagram's math.

Diagrams are cached as plain ``.asc`` files in ``data/facet_diagrams/`` keyed
by cut id. Drop any downloaded design there (same filename) to replace the
bundled one; cuts without a diagram fall back to the procedural pattern in
``svg_sheet``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DIAGRAM_DIR = Path(__file__).resolve().parents[2] / "data" / "facet_diagrams"

_EPS = 1e-9
_MERGE = 1e-7


class AscUnsupported(ValueError):
    """The .ASC variant cannot be reconstructed (loud failure, never a guess)."""


# --- parsing ------------------------------------------------------------------


@dataclass(frozen=True)
class Tier:
    side: str  # 'pavilion' | 'girdle' | 'crown' | 'table'
    angle_deg: float
    distance: float
    indices: tuple[int, ...]
    name: str = ""


@dataclass(frozen=True)
class Diagram:
    gear: int
    header: str
    tiers: tuple[Tier, ...]


def _is_int(token: str) -> bool:
    try:
        int(token)
    except ValueError:
        return False
    return True


def _is_float(token: str) -> bool:
    try:
        float(token)
    except ValueError:
        return False
    return True


def parse_asc(text: str) -> Diagram:
    """Parse a GemCad .ASC file into tiers of facet planes.

    Two crown/pavilion conventions are supported: GemCad exports carry signed
    angles (negative = pavilion, positive = crown, the sign wins regardless of
    line order); sign-free files split at the first 90-degree girdle tier —
    the file order is the cutting order. A 0-degree tier is the table. Each
    tier must carry its plane distance after the angle; index positions are
    integers on the stated gear (0 means the gear's top index), and facet
    names may be interleaved between indices as ``n <name>`` pairs.
    """
    gear = 96
    header_lines: list[str] = []
    raw_tiers: list[tuple[float, float, tuple[int, ...], str]] = []

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        tokens = line.split()
        key = tokens[0]
        if key == "g" and len(tokens) >= 2:
            gear = int(float(tokens[1]))
        elif key in ("H", "h", "F") and len(tokens) > 1:
            header_lines.append(" ".join(tokens[1:]))
        elif key == "a":
            if len(tokens) < 3:
                raise AscUnsupported(f"malformed facet line: {line!r}")
            angle = float(tokens[1])
            rest = tokens[2:]
            if not (_is_float(rest[0]) and not _is_int(rest[0])):
                raise AscUnsupported(
                    "this .ASC has no plane distances — re-export the design "
                    "from GemCad (File > Save As .ASC) so each facet line "
                    "carries angle, distance, then indices"
                )
            distance = float(rest[0])
            indices: list[int] = []
            names: list[str] = []
            i = 1
            while i < len(rest):
                token = rest[i]
                if _is_int(token):
                    indices.append(int(token))
                    i += 1
                elif token == "n":  # per-facet name follows, indices continue
                    if i + 1 < len(rest):
                        names.append(rest[i + 1])
                    i += 2
                elif token.startswith("G"):  # GemCad UI metadata
                    i += 1
                else:
                    names.append(token)
                    i += 1
            if not indices:
                raise AscUnsupported(f"facet line has no gear indices: {line!r}")
            raw_tiers.append((angle, distance, tuple(indices), " ".join(names)))
        # I (refractive index), y, e, x, U/V/W print blocks: metadata — ignored.

    if not raw_tiers:
        raise AscUnsupported("no facet lines found")

    signed = any(angle < 0 for angle, *_ in raw_tiers)
    tiers: list[Tier] = []
    girdle_seen = False
    for angle, distance, indices, name in raw_tiers:
        if abs(abs(angle) - 90.0) < 1e-6:
            side = "girdle"
            girdle_seen = True
        elif abs(angle) < 1e-6:
            side = "table"
        elif signed:
            side = "pavilion" if angle < 0 else "crown"
        else:
            side = "crown" if girdle_seen else "pavilion"
        tiers.append(Tier(side, abs(angle), distance, indices, name))

    if not girdle_seen:
        raise AscUnsupported("no 90-degree girdle tier — cannot split crown/pavilion")
    return Diagram(gear=gear, header=" · ".join(header_lines), tiers=tuple(tiers))


# --- convex polyhedron by half-space clipping ---------------------------------


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def tier_planes(diagram: Diagram) -> list[tuple[tuple[float, float, float], float, int]]:
    """Expand tiers to (normal, distance, tier_index) planes.

    Azimuth 0 (gear index == gear) points at 12 o'clock in the face-up view;
    indices advance clockwise, matching printed faceting diagrams.
    """
    planes = []
    for t_i, tier in enumerate(diagram.tiers):
        a = math.radians(tier.angle_deg)
        for idx in tier.indices:
            az = 2 * math.pi * (idx % diagram.gear) / diagram.gear
            ux, uy = math.sin(az), -math.cos(az)  # 12 o'clock, clockwise
            if tier.side == "table":
                n = (0.0, 0.0, 1.0)
            elif tier.side == "girdle":
                n = (ux, uy, 0.0)
            else:
                nz = math.cos(a) if tier.side == "crown" else -math.cos(a)
                n = (math.sin(a) * ux, math.sin(a) * uy, nz)
            planes.append((n, tier.distance, t_i))
    return planes


def _plane_basis(n):
    ax = (1.0, 0.0, 0.0) if abs(n[0]) < 0.9 else (0.0, 1.0, 0.0)
    u = (n[1] * ax[2] - n[2] * ax[1], n[2] * ax[0] - n[0] * ax[2],
         n[0] * ax[1] - n[1] * ax[0])
    lu = math.sqrt(_dot(u, u))
    u = (u[0] / lu, u[1] / lu, u[2] / lu)
    v = (n[1] * u[2] - n[2] * u[1], n[2] * u[0] - n[0] * u[2],
         n[0] * u[1] - n[1] * u[0])
    return u, v


def _clip_faces(faces, n, d, tag):
    """Clip the convex polyhedron's face list by half-space n·x <= d."""
    kept = []
    cap: list[tuple[float, float, float]] = []
    for points, face_tag in faces:
        out = []
        m = len(points)
        for i in range(m):
            a, b = points[i], points[(i + 1) % m]
            da, db = _dot(n, a) - d, _dot(n, b) - d
            if da <= _EPS:
                out.append(a)
            if (da > _EPS) != (db > _EPS) and abs(da - db) > _EPS:
                t = da / (da - db)
                p = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]),
                     a[2] + t * (b[2] - a[2]))
                out.append(p)
                cap.append(p)
        if len(out) >= 3:
            kept.append((out, face_tag))
    # the cut cross-section becomes the new facet on this plane
    uniq: list[tuple[float, float, float]] = []
    for p in cap:
        if all(max(abs(p[k] - q[k]) for k in range(3)) > _MERGE for q in uniq):
            uniq.append(p)
    if len(uniq) >= 3:
        u, v = _plane_basis(n)
        cx = sum(p[0] for p in uniq) / len(uniq)
        cy = sum(p[1] for p in uniq) / len(uniq)
        cz = sum(p[2] for p in uniq) / len(uniq)
        c = (cx, cy, cz)
        uniq.sort(key=lambda p: math.atan2(
            _dot((p[0] - c[0], p[1] - c[1], p[2] - c[2]), v),
            _dot((p[0] - c[0], p[1] - c[1], p[2] - c[2]), u)))
        kept.append((uniq, tag))
    return kept


def build_faces(diagram: Diagram):
    """Intersect all facet half-spaces; return [(3D points, (tier_i, normal))]."""
    s = 8.0  # starting block, comfortably larger than any unit-girdle design
    corners = [(x, y, z) for x in (-s, s) for y in (-s, s) for z in (-s, s)]
    quads = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1),
             (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    faces = [([corners[i] for i in q], None) for q in quads]
    for n, d, t_i in tier_planes(diagram):
        faces = _clip_faces(faces, n, d, (t_i, n))
        if not faces:
            raise AscUnsupported("facet planes leave no stone — bad distances")
    if any(tag is None for _, tag in faces):
        raise AscUnsupported("diagram does not close into a stone "
                             "(some raw block surface survives)")
    return faces


# --- face-up projection -------------------------------------------------------


@dataclass(frozen=True)
class FaceUpFacet:
    points: tuple[tuple[float, float], ...]  # normalized: extents == 1, centered
    normal: tuple[float, float, float]       # unit, screen coords (y down)
    kind: str                                # 'table' | 'crown'
    tier: int


@dataclass(frozen=True)
class FaceUpLayout:
    outline: tuple[tuple[float, float], ...]
    facets: tuple[FaceUpFacet, ...]
    table_fraction: float  # table extent as a fraction of the outline extent
    header: str


def _hull_2d(points):
    pts = sorted(set((round(x, 7), round(y, 7)) for x, y in points))
    if len(pts) < 3:
        return pts

    def half(seq):
        out = []
        for p in seq:
            while len(out) >= 2 and (
                (out[-1][0] - out[-2][0]) * (p[1] - out[-2][1])
                - (out[-1][1] - out[-2][1]) * (p[0] - out[-2][0])
            ) <= 0:
                out.pop()
            out.append(p)
        return out[:-1]

    return half(pts) + half(pts[::-1])


def face_up_layout(diagram: Diagram) -> FaceUpLayout:
    """Project the crown straight down to the exact face-up drawing.

    Design y (12 o'clock) maps to screen -y is already handled in
    ``tier_planes`` (screen coordinates, y down), so the projection is a
    plain drop of z. Coordinates are normalized so the outline spans exactly
    1.0 in x and in y, centered on the origin — the renderer multiplies by
    the stone's real mm extents. Deterministic: same file, same layout.
    """
    faces = build_faces(diagram)
    all_pts = [p for points, _ in faces for p in points]
    xmin, xmax = min(p[0] for p in all_pts), max(p[0] for p in all_pts)
    ymin, ymax = min(p[1] for p in all_pts), max(p[1] for p in all_pts)
    cx, cy = (xmin + xmax) / 2, (ymin + ymax) / 2
    sx, sy = xmax - xmin, ymax - ymin

    def norm(p):
        return ((p[0] - cx) / sx, (p[1] - cy) / sy)

    outline = tuple(norm(p) for p in _hull_2d((p[0], p[1]) for p in all_pts))

    facets: list[FaceUpFacet] = []
    table_extent = 0.0
    for points, (t_i, n) in faces:
        tier = diagram.tiers[t_i]
        if tier.side not in ("crown", "table"):
            continue
        pts2 = tuple(norm(p) for p in points)
        if tier.side == "table":
            table_extent = max(table_extent,
                               *(max(abs(x), abs(y)) for x, y in pts2))
        facets.append(FaceUpFacet(points=pts2, normal=n, kind=tier.side, tier=t_i))

    facets.sort(key=lambda f: (f.tier, round(sum(x for x, _ in f.points), 6),
                               round(sum(y for _, y in f.points), 6)))
    return FaceUpLayout(outline=outline, facets=tuple(facets),
                        table_fraction=2 * table_extent, header=diagram.header)


# --- side elevation (profile) -------------------------------------------------


@dataclass(frozen=True)
class ProfileLayout:
    """Front-facing facet polygons seen from the side, as (x_norm, z) pairs.

    x_norm is centered and normalized by the stone's width; z is the raw
    design height. The renderer remaps crown z to its drawn crown band and
    pavilion z to its drawn pavilion band, so the facet junctions land inside
    the spec-true profile outline whatever the spec's depth split is."""

    crown: tuple[tuple[tuple[float, float], ...], ...]
    pavilion: tuple[tuple[tuple[float, float], ...], ...]
    z_table: float
    z_crown_base: float
    z_pav_top: float
    z_culet: float


@lru_cache(maxsize=None)
def profile_layout(cut_id: str, axis: str = "length") -> ProfileLayout | None:
    """The cut's true side elevation.

    axis="length": viewed along the length axis (span = width) — the Gem ID
    profile. axis="width": viewed along the width axis (span = length) — a
    stone seen edge-on in an assembly side view.
    """
    path = DIAGRAM_DIR / f"{cut_id}.asc"
    if not path.exists():
        return None
    diagram = parse_asc(path.read_text())
    faces = build_faces(diagram)
    keep, cull = (0, 1) if axis == "length" else (1, 0)
    all_pts = [p for pts, _ in faces for p in pts]
    lo = min(p[keep] for p in all_pts)
    hi = max(p[keep] for p in all_pts)
    center, span = (lo + hi) / 2, hi - lo

    crown: list[tuple] = []
    pavilion: list[tuple] = []
    for pts, (t_i, n) in faces:
        side = diagram.tiers[t_i].side
        if side not in ("crown", "pavilion") or n[cull] > -1e-6:
            continue  # back-facing or girdle/table — not visible from the front
        poly = tuple(((p[keep] - center) / span, p[2]) for p in pts)
        (crown if side == "crown" else pavilion).append(poly)
    if not crown or not pavilion:
        return None
    return ProfileLayout(
        crown=tuple(crown), pavilion=tuple(pavilion),
        z_table=max(z for f in crown for _, z in f),
        z_crown_base=min(z for f in crown for _, z in f),
        z_pav_top=max(z for f in pavilion for _, z in f),
        z_culet=min(z for f in pavilion for _, z in f),
    )


# --- spec-true table remap ----------------------------------------------------


def _outline_radius(outline, angle):
    """Distance from the origin to the outline polygon along a direction."""
    dx, dy = math.cos(angle), math.sin(angle)
    best = None
    m = len(outline)
    for i in range(m):
        (x1, y1), (x2, y2) = outline[i], outline[(i + 1) % m]
        ex, ey = x2 - x1, y2 - y1
        den = ex * dy - ey * dx  # solve t*d = p1 + s*e
        if abs(den) < 1e-12:
            continue
        t = (ex * y1 - ey * x1) / den
        s = (dx * y1 - dy * x1) / den
        if t > 1e-9 and -1e-9 <= s <= 1 + 1e-9:
            best = t if best is None else min(best, t)
    return best or 0.5


def remap_table(layout: FaceUpLayout, table_ratio: float) -> FaceUpLayout:
    """Radially rescale the crown so the drawn table matches the spec's table %.

    The diagram keeps its exact topology; every vertex moves along its ray
    from the center so the table edge lands at ``table_ratio`` of the outline
    while the outline itself stays fixed. Dimensional truth: the spec's
    numbers win over the design's native proportions.
    """
    f = layout.table_fraction
    if f <= 0 or abs(f - table_ratio) < 0.002 or not 0.2 <= table_ratio <= 0.9:
        return layout

    def remap_pt(x, y):
        r = math.hypot(x, y)
        if r < 1e-9:
            return (x, y)
        ang = math.atan2(y, x)
        r_out = _outline_radius(layout.outline, ang)
        m = min(r / r_out, 1.0)
        if m <= f:
            m2 = m * table_ratio / f
        else:
            m2 = table_ratio + (m - f) * (1 - table_ratio) / (1 - f)
        s = m2 / m
        return (x * s, y * s)

    facets = tuple(
        FaceUpFacet(points=tuple(remap_pt(x, y) for x, y in fct.points),
                    normal=fct.normal, kind=fct.kind, tier=fct.tier)
        for fct in layout.facets)
    return FaceUpLayout(outline=layout.outline, facets=facets,
                        table_fraction=table_ratio, header=layout.header)


# --- cached diagram library ---------------------------------------------------


@lru_cache(maxsize=None)
def layout_for_cut(cut_id: str) -> FaceUpLayout | None:
    """The cached face-up layout for a cut id, or None to use the fallback."""
    path = DIAGRAM_DIR / f"{cut_id}.asc"
    if not path.exists():
        return None
    return face_up_layout(parse_asc(path.read_text()))


@lru_cache(maxsize=None)
def remapped_layout(cut_id: str, table_ratio: float | None) -> FaceUpLayout | None:
    layout = layout_for_cut(cut_id)
    if layout is None or table_ratio is None:
        return layout
    return remap_table(layout, table_ratio)

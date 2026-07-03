"""Sheet SVG -> DXF R12 converter for CAD handoff.

Factories import the technical sheet as a 2D reference underlay in their CAD
package (Rhino, MatrixGold, RhinoJewel all read R12 DXF natively). This is a
drawing exchange, not solid modeling: the same deterministic vectors the SVG
carries, re-encoded entity for entity. Coordinates stay in sheet millimeters
(the title block states each view's scale, standard drafting practice);
DXF's y axis points up, so everything is flipped about the sheet height.

Layers: EDGES (solid geometry), ANNOTATION (dimension/witness/center lines),
TEXT (labels). Hatch fills are presentation-only and are not exported.
"""

from __future__ import annotations

import math
import re

from facetta.svg_sheet import SHEET_H

_CIRCLE = re.compile(r'<circle cx="([-\d.]+)" cy="([-\d.]+)" r="([-\d.]+)"')
_ELLIPSE = re.compile(r'<ellipse cx="([-\d.]+)" cy="([-\d.]+)" rx="([-\d.]+)" ry="([-\d.]+)"')
_RECT = re.compile(r'<rect x="([-\d.]+)" y="([-\d.]+)" width="([-\d.]+)" height="([-\d.]+)"[^>]*?/?>')
_POLYGON = re.compile(r'<polygon points="([^"]+)"')
_LINE = re.compile(r'<line x1="([-\d.]+)" y1="([-\d.]+)" x2="([-\d.]+)" y2="([-\d.]+)"([^>]*?)/>')
_TEXT = re.compile(r'<text x="([-\d.]+)" y="([-\d.]+)"[^>]*?font-size="([\d.]+)"[^>]*?>([^<]+)</text>')
_PATH = re.compile(r'<path d="([^"]+)"')
_NUM = re.compile(r"[-\d.]+")


def _y(v: float) -> float:
    return SHEET_H - v


def _entity(pairs: list[tuple[int, object]]) -> str:
    return "\n".join(f"{code}\n{value}" for code, value in pairs)


def _line(x1, y1, x2, y2, layer):
    return _entity([(0, "LINE"), (8, layer),
                    (10, f"{x1:.3f}"), (20, f"{_y(y1):.3f}"), (30, "0.0"),
                    (11, f"{x2:.3f}"), (21, f"{_y(y2):.3f}"), (31, "0.0")])


def _circle(cx, cy, r, layer):
    return _entity([(0, "CIRCLE"), (8, layer),
                    (10, f"{cx:.3f}"), (20, f"{_y(cy):.3f}"), (30, "0.0"),
                    (40, f"{r:.3f}")])


def _polyline(points, layer, closed=True):
    parts = [_entity([(0, "POLYLINE"), (8, layer), (66, 1),
                      (70, 1 if closed else 0)])]
    for x, y in points:
        parts.append(_entity([(0, "VERTEX"), (8, layer),
                              (10, f"{x:.3f}"), (20, f"{_y(y):.3f}"), (30, "0.0")]))
    parts.append(_entity([(0, "SEQEND"), (8, layer)]))
    return "\n".join(parts)


def _ellipse_polyline(cx, cy, rx, ry, layer, segments=64):
    pts = [(cx + rx * math.cos(2 * math.pi * k / segments),
            cy + ry * math.sin(2 * math.pi * k / segments))
           for k in range(segments)]
    return _polyline(pts, layer)


def _text(x, y, height, value, layer="TEXT"):
    clean = (value.replace("&amp;", "&").replace("&lt;", "<")
             .replace("&gt;", ">").replace("⌀", "%%c").replace("×", "x")
             .replace("·", "-").replace("—", "-").replace("°", "%%d"))
    return _entity([(0, "TEXT"), (8, layer),
                    (10, f"{x:.3f}"), (20, f"{_y(y):.3f}"), (30, "0.0"),
                    (40, f"{height:.2f}"), (1, clean)])


def _path_entities(d: str, layer: str) -> list[str]:
    """Absolute M/L/A/Z paths: lines pass through; arcs sample to polylines."""
    tokens = re.findall(r"[MALZ]|[-\d.]+", d)
    out: list[str] = []
    pos = start = None
    i = 0
    while i < len(tokens):
        cmd = tokens[i]
        if cmd == "M":
            pos = start = (float(tokens[i + 1]), float(tokens[i + 2]))
            i += 3
        elif cmd == "L":
            new = (float(tokens[i + 1]), float(tokens[i + 2]))
            out.append(_line(*pos, *new, layer))
            pos = new
            i += 3
        elif cmd == "A":
            rx, ry = float(tokens[i + 1]), float(tokens[i + 2])
            large, sweep = int(float(tokens[i + 4])), int(float(tokens[i + 5]))
            new = (float(tokens[i + 6]), float(tokens[i + 7]))
            out.append(_polyline(_sample_arc(pos, new, rx, ry, large, sweep),
                                 layer, closed=False))
            pos = new
            i += 8
        elif cmd == "Z":
            if pos != start:
                out.append(_line(*pos, *start, layer))
            pos = start
            i += 1
        else:
            i += 1
    return out


def _sample_arc(p1, p2, rx, ry, large_arc, sweep, segments=24):
    """SVG endpoint parameterization -> sampled points (spec F.6.5, rotation 0)."""
    (x1, y1), (x2, y2) = p1, p2
    x1p, y1p = (x1 - x2) / 2, (y1 - y2) / 2
    lam = x1p**2 / rx**2 + y1p**2 / ry**2
    if lam > 1:
        rx, ry = rx * math.sqrt(lam), ry * math.sqrt(lam)
    num = rx**2 * ry**2 - rx**2 * y1p**2 - ry**2 * x1p**2
    den = rx**2 * y1p**2 + ry**2 * x1p**2
    c = math.sqrt(max(0.0, num / den))
    if large_arc == sweep:
        c = -c
    cxp, cyp = c * rx * y1p / ry, -c * ry * x1p / rx
    cx, cy = cxp + (x1 + x2) / 2, cyp + (y1 + y2) / 2

    def angle(ux, uy):
        return math.atan2(uy, ux)

    th1 = angle((x1p - cxp) / rx, (y1p - cyp) / ry)
    dth = angle((-x1p - cxp) / rx, (-y1p - cyp) / ry) - th1
    if not sweep and dth > 0:
        dth -= 2 * math.pi
    elif sweep and dth < 0:
        dth += 2 * math.pi
    return [(cx + rx * math.cos(th1 + dth * k / segments),
             cy + ry * math.sin(th1 + dth * k / segments))
            for k in range(segments + 1)]


def svg_to_dxf(svg: str) -> str:
    entities: list[str] = []
    for m in _CIRCLE.finditer(svg):
        cx, cy, r = map(float, m.groups())
        entities.append(_circle(cx, cy, r, "EDGES"))
    for m in _ELLIPSE.finditer(svg):
        cx, cy, rx, ry = map(float, m.groups())
        entities.append(_ellipse_polyline(cx, cy, rx, ry, "EDGES"))
    for m in _RECT.finditer(svg):
        x, y, w, h = map(float, m.groups())
        entities.append(_polyline([(x, y), (x + w, y), (x + w, y + h), (x, y + h)],
                                  "EDGES"))
    for m in _POLYGON.finditer(svg):
        nums = [float(n) for n in _NUM.findall(m.group(1))]
        entities.append(_polyline(list(zip(nums[::2], nums[1::2])), "EDGES"))
    for m in _LINE.finditer(svg):
        x1, y1, x2, y2 = map(float, m.groups()[:4])
        layer = "ANNOTATION" if "stroke-dasharray" in m.group(5) else "EDGES"
        entities.append(_line(x1, y1, x2, y2, layer))
    for m in _PATH.finditer(svg):
        entities += _path_entities(m.group(1), "EDGES")
    for m in _TEXT.finditer(svg):
        x, y, size, value = m.groups()
        entities.append(_text(float(x), float(y), float(size) * 0.8, value.strip()))

    return "\n".join([
        "0", "SECTION", "2", "HEADER",
        "9", "$INSUNITS", "70", "4",  # millimeters
        "0", "ENDSEC",
        "0", "SECTION", "2", "ENTITIES",
        *entities,
        "0", "ENDSEC",
        "0", "EOF",
    ]) + "\n"

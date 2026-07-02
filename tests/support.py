"""Blueprint-quality assertions for rendered sheets.

Witness (extension) lines are the faint dashed lines that carry a dimension
out from the geometry. Drafting rule: they must start exactly on the vector
they measure — never floating near it. `assert_witness_lines_snap` parses a
sheet and proves every witness line touches a real shape edge.
"""

import math
import re

TOL = 0.02

_CIRCLE = re.compile(r'<circle cx="([-\d.]+)" cy="([-\d.]+)" r="([-\d.]+)"')
_ELLIPSE = re.compile(r'<ellipse cx="([-\d.]+)" cy="([-\d.]+)" rx="([-\d.]+)" ry="([-\d.]+)"')
_RECT = re.compile(r'<rect x="([-\d.]+)" y="([-\d.]+)" width="([-\d.]+)" height="([-\d.]+)"')
_POLYGON = re.compile(r'<polygon points="([^"]+)"')
_LINE = re.compile(r'<line x1="([-\d.]+)" y1="([-\d.]+)" x2="([-\d.]+)" y2="([-\d.]+)"[^>]*?/>')
_PATH = re.compile(r'<path d="([^"]+)"')
_PATH_NUMS = re.compile(r"[-\d.]+")


def _arc_center(p1, p2, rx, ry, large_arc, sweep):
    """SVG endpoint parameterization -> arc center (rotation 0), per spec F.6.5."""
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
    return (cxp + (x1 + x2) / 2, cyp + (y1 + y2) / 2, rx, ry)


def _parse_path(d: str):
    """Ellipses (from arcs) and segments (from L/Z) of an absolute-command path."""
    tokens = re.findall(r"[MALZ]|[-\d.]+", d)
    ellipses, segments = [], []
    pos = start = None
    i = 0
    while i < len(tokens):
        cmd = tokens[i]
        if cmd == "M":
            pos = start = (float(tokens[i + 1]), float(tokens[i + 2]))
            i += 3
        elif cmd == "L":
            new = (float(tokens[i + 1]), float(tokens[i + 2]))
            segments.append((pos, new))
            pos = new
            i += 3
        elif cmd == "A":
            rx, ry = float(tokens[i + 1]), float(tokens[i + 2])
            large_arc, sweep = int(float(tokens[i + 4])), int(float(tokens[i + 5]))
            new = (float(tokens[i + 6]), float(tokens[i + 7]))
            ellipses.append(_arc_center(pos, new, rx, ry, large_arc, sweep))
            pos = new
            i += 8
        elif cmd == "Z":
            segments.append((pos, start))
            pos = start
            i += 1
        else:  # stray number — malformed for our purposes
            i += 1
    return ellipses, segments


def _on_segment(p, a, b) -> bool:
    (px, py), (ax, ay), (bx, by) = p, a, b
    if not (min(ax, bx) - TOL <= px <= max(ax, bx) + TOL
            and min(ay, by) - TOL <= py <= max(ay, by) + TOL):
        return False
    cross = (bx - ax) * (py - ay) - (by - ay) * (px - ax)
    length = math.hypot(bx - ax, by - ay) or 1.0
    return abs(cross) / length <= TOL


def _on_ellipse(p, cx, cy, rx, ry) -> bool:
    if rx <= 0 or ry <= 0:
        return False
    v = ((p[0] - cx) / rx) ** 2 + ((p[1] - cy) / ry) ** 2
    return abs(v - 1) <= 0.01


def collect_edges(svg: str):
    """All shape edges a witness line may legally anchor on."""
    ellipses, segments = [], []
    for m in _CIRCLE.finditer(svg):
        cx, cy, r = map(float, m.groups())
        ellipses.append((cx, cy, r, r))
    for m in _ELLIPSE.finditer(svg):
        ellipses.append(tuple(map(float, m.groups())))
    for m in _RECT.finditer(svg):
        x, y, w, h = map(float, m.groups())
        corners = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
        segments += list(zip(corners, corners[1:] + corners[:1]))
    for m in _POLYGON.finditer(svg):
        nums = [float(n) for n in _PATH_NUMS.findall(m.group(1))]
        pts = list(zip(nums[::2], nums[1::2]))
        segments += list(zip(pts, pts[1:] + pts[:1]))
    for m in _LINE.finditer(svg):
        whole = m.group(0)
        if "stroke-dasharray" in whole:
            continue  # dashed lines are annotations, not geometry
        x1, y1, x2, y2 = map(float, m.groups())
        segments.append(((x1, y1), (x2, y2)))
    for m in _PATH.finditer(svg):
        e, s = _parse_path(m.group(1))
        ellipses += e
        segments += s
    return ellipses, segments


def witness_lines(svg: str):
    """The dashed extension lines (dasharray 0.8 0.8 is used only by _ext)."""
    out = []
    for m in _LINE.finditer(svg):
        if 'stroke-dasharray="0.8 0.8"' in m.group(0):
            x1, y1, x2, y2 = map(float, m.groups())
            out.append(((x1, y1), (x2, y2)))
    return out


def _snaps(p, ellipses, segments) -> bool:
    return any(_on_ellipse(p, *e) for e in ellipses) or any(
        _on_segment(p, a, b) for a, b in segments
    )


def assert_witness_lines_snap(svg: str, context: str = "sheet") -> int:
    ellipses, segments = collect_edges(svg)
    lines = witness_lines(svg)
    assert lines, f"{context}: no witness lines found"
    loose = [line for line in lines if not (_snaps(line[0], ellipses, segments)
                                            or _snaps(line[1], ellipses, segments))]
    assert not loose, (
        f"{context}: {len(loose)} witness line(s) do not touch any shape edge: {loose}"
    )
    return len(lines)

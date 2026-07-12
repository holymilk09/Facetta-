"""Deterministic SVG sheet -> DXF R12 drawing-exchange conversion.

The converter walks the SVG tree so nested transforms cannot be silently lost.
Curved paths are sampled into stable polylines because R12 has no portable
Bezier entity. The DXF remains a drawing-exchange reference, not fabrication
geometry; authority is decided by the factory-pack manifest, not this module.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from xml.etree import ElementTree as ET

from facetta.svg_sheet import SHEET_H


Point = tuple[float, float]
Matrix = tuple[float, float, float, float, float, float]
IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

_NUMBER = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")
_PATH_TOKEN = re.compile(
    r"[AaCcHhLlMmQqSsTtVvZz]|"
    r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
)
_TRANSFORM = re.compile(r"([A-Za-z]+)\s*\(([^)]*)\)")
_SKIP_TREES = {"defs", "pattern", "clipPath", "mask", "metadata", "title"}


class DxfUnsupported(ValueError):
    """The source uses SVG geometry that cannot be exported without loss."""


def _tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _float(element: ET.Element, key: str, default: float | None = None) -> float:
    value = element.get(key)
    if value is None:
        if default is None:
            raise DxfUnsupported(f"SVG {_tag(element)} is missing {key}")
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise DxfUnsupported(
            f"SVG {_tag(element)} has a non-numeric {key}: {value!r}"
        ) from exc


def _multiply(left: Matrix, right: Matrix) -> Matrix:
    la, lb, lc, ld, le, lf = left
    ra, rb, rc, rd, re, rf = right
    return (
        la * ra + lc * rb,
        lb * ra + ld * rb,
        la * rc + lc * rd,
        lb * rc + ld * rd,
        la * re + lc * rf + le,
        lb * re + ld * rf + lf,
    )


def _apply(matrix: Matrix, point: Point) -> Point:
    a, b, c, d, e, f = matrix
    x, y = point
    return a * x + c * y + e, b * x + d * y + f


def _parse_transform(value: str | None) -> Matrix:
    if not value:
        return IDENTITY
    matrix = IDENTITY
    matched = ""
    for match in _TRANSFORM.finditer(value):
        matched += match.group(0)
        name = match.group(1).lower()
        values = [float(item) for item in _NUMBER.findall(match.group(2))]
        if name == "matrix" and len(values) == 6:
            local: Matrix = tuple(values)  # type: ignore[assignment]
        elif name == "translate" and len(values) in {1, 2}:
            local = (1, 0, 0, 1, values[0], values[1] if len(values) == 2 else 0)
        elif name == "scale" and len(values) in {1, 2}:
            local = (values[0], 0, 0, values[-1], 0, 0)
        elif name == "rotate" and len(values) in {1, 3}:
            angle = math.radians(values[0])
            cosine, sine = math.cos(angle), math.sin(angle)
            rotation: Matrix = (cosine, sine, -sine, cosine, 0, 0)
            if len(values) == 3:
                cx, cy = values[1:]
                local = _multiply(
                    _multiply((1, 0, 0, 1, cx, cy), rotation),
                    (1, 0, 0, 1, -cx, -cy),
                )
            else:
                local = rotation
        else:
            raise DxfUnsupported(
                f"unsupported SVG transform {match.group(0)!r}"
            )
        matrix = _multiply(matrix, local)
    if re.sub(r"[\s,]+", "", matched) != re.sub(r"[\s,]+", "", value):
        raise DxfUnsupported(f"invalid SVG transform list {value!r}")
    return matrix


def _y(value: float) -> float:
    return SHEET_H - value


def _entity(pairs: list[tuple[int, object]]) -> str:
    return "\n".join(f"{code}\n{value}" for code, value in pairs)


def _line(x1: float, y1: float, x2: float, y2: float, layer: str) -> str:
    return _entity([
        (0, "LINE"), (8, layer),
        (10, f"{x1:.3f}"), (20, f"{_y(y1):.3f}"), (30, "0.0"),
        (11, f"{x2:.3f}"), (21, f"{_y(y2):.3f}"), (31, "0.0"),
    ])


def _circle(cx: float, cy: float, radius: float, layer: str) -> str:
    return _entity([
        (0, "CIRCLE"), (8, layer),
        (10, f"{cx:.3f}"), (20, f"{_y(cy):.3f}"), (30, "0.0"),
        (40, f"{radius:.3f}"),
    ])


def _polyline(points: Iterable[Point], layer: str, *, closed: bool = True) -> str:
    vertices = tuple(points)
    if len(vertices) < 2:
        return ""
    parts = [_entity([
        (0, "POLYLINE"), (8, layer), (66, 1), (70, 1 if closed else 0),
    ])]
    for x, y in vertices:
        parts.append(_entity([
            (0, "VERTEX"), (8, layer),
            (10, f"{x:.3f}"), (20, f"{_y(y):.3f}"), (30, "0.0"),
        ]))
    parts.append(_entity([(0, "SEQEND"), (8, layer)]))
    return "\n".join(parts)


def _text(
    x: float,
    y: float,
    height: float,
    value: str,
    *,
    rotation: float = 0.0,
) -> str:
    clean = (
        value.replace("⌀", "%%c").replace("×", "x")
        .replace("·", "-").replace("—", "-").replace("°", "%%d")
    )
    pairs: list[tuple[int, object]] = [
        (0, "TEXT"), (8, "TEXT"),
        (10, f"{x:.3f}"), (20, f"{_y(y):.3f}"), (30, "0.0"),
        (40, f"{height:.2f}"), (1, clean),
    ]
    if abs(rotation) > 1e-9:
        pairs.append((50, f"{-rotation:.3f}"))
    return _entity(pairs)


def _sample_ellipse(
    cx: float,
    cy: float,
    rx: float,
    ry: float,
    *,
    segments: int = 64,
) -> tuple[Point, ...]:
    return tuple(
        (
            cx + rx * math.cos(2 * math.pi * index / segments),
            cy + ry * math.sin(2 * math.pi * index / segments),
        )
        for index in range(segments)
    )


def _rounded_rect_points(
    x: float,
    y: float,
    width: float,
    height: float,
    rx: float,
    ry: float,
    *,
    corner_segments: int = 8,
) -> tuple[Point, ...]:
    rx, ry = min(abs(rx), width / 2), min(abs(ry), height / 2)
    if rx == 0 or ry == 0:
        return (
            (x, y), (x + width, y),
            (x + width, y + height), (x, y + height),
        )
    corners = (
        (x + width - rx, y + ry, -math.pi / 2, 0.0),
        (x + width - rx, y + height - ry, 0.0, math.pi / 2),
        (x + rx, y + height - ry, math.pi / 2, math.pi),
        (x + rx, y + ry, math.pi, 3 * math.pi / 2),
    )
    points: list[Point] = []
    for cx, cy, start, end in corners:
        for index in range(corner_segments + 1):
            angle = start + (end - start) * index / corner_segments
            points.append((cx + rx * math.cos(angle), cy + ry * math.sin(angle)))
    return tuple(points)


def _sample_quadratic(
    start: Point,
    control: Point,
    end: Point,
    *,
    segments: int = 32,
) -> tuple[Point, ...]:
    return tuple(
        (
            (1 - t) ** 2 * start[0]
            + 2 * (1 - t) * t * control[0]
            + t**2 * end[0],
            (1 - t) ** 2 * start[1]
            + 2 * (1 - t) * t * control[1]
            + t**2 * end[1],
        )
        for t in (index / segments for index in range(segments + 1))
    )


def _sample_cubic(
    start: Point,
    first: Point,
    second: Point,
    end: Point,
    *,
    segments: int = 48,
) -> tuple[Point, ...]:
    return tuple(
        (
            (1 - t) ** 3 * start[0]
            + 3 * (1 - t) ** 2 * t * first[0]
            + 3 * (1 - t) * t**2 * second[0]
            + t**3 * end[0],
            (1 - t) ** 3 * start[1]
            + 3 * (1 - t) ** 2 * t * first[1]
            + 3 * (1 - t) * t**2 * second[1]
            + t**3 * end[1],
        )
        for t in (index / segments for index in range(segments + 1))
    )


def _sample_arc(
    start: Point,
    end: Point,
    rx: float,
    ry: float,
    rotation_deg: float,
    large_arc: int,
    sweep: int,
    *,
    segments: int = 48,
) -> tuple[Point, ...]:
    if start == end:
        return (start,)
    rx, ry = abs(rx), abs(ry)
    if rx == 0 or ry == 0:
        return start, end
    phi = math.radians(rotation_deg % 360)
    cosine, sine = math.cos(phi), math.sin(phi)
    dx, dy = (start[0] - end[0]) / 2, (start[1] - end[1]) / 2
    x_prime = cosine * dx + sine * dy
    y_prime = -sine * dx + cosine * dy
    scale = x_prime**2 / rx**2 + y_prime**2 / ry**2
    if scale > 1:
        scale = math.sqrt(scale)
        rx *= scale
        ry *= scale
    numerator = max(
        0.0,
        rx**2 * ry**2 - rx**2 * y_prime**2 - ry**2 * x_prime**2,
    )
    denominator = rx**2 * y_prime**2 + ry**2 * x_prime**2
    coefficient = 0.0 if denominator == 0 else math.sqrt(numerator / denominator)
    if large_arc == sweep:
        coefficient *= -1
    cx_prime = coefficient * rx * y_prime / ry
    cy_prime = -coefficient * ry * x_prime / rx
    center = (
        cosine * cx_prime - sine * cy_prime + (start[0] + end[0]) / 2,
        sine * cx_prime + cosine * cy_prime + (start[1] + end[1]) / 2,
    )

    def vector_angle(vector: Point) -> float:
        return math.atan2(vector[1], vector[0])

    theta = vector_angle(((x_prime - cx_prime) / rx, (y_prime - cy_prime) / ry))
    delta = (
        vector_angle(((-x_prime - cx_prime) / rx, (-y_prime - cy_prime) / ry))
        - theta
    )
    if not sweep and delta > 0:
        delta -= 2 * math.pi
    elif sweep and delta < 0:
        delta += 2 * math.pi
    return tuple(
        (
            center[0] + cosine * rx * math.cos(angle)
            - sine * ry * math.sin(angle),
            center[1] + sine * rx * math.cos(angle)
            + cosine * ry * math.sin(angle),
        )
        for angle in (
            theta + delta * index / segments
            for index in range(segments + 1)
        )
    )


def _path_subpaths(data: str) -> tuple[tuple[tuple[Point, ...], bool], ...]:
    tokens = _PATH_TOKEN.findall(data)
    if not tokens:
        return ()
    consumed = "".join(tokens)
    source = re.sub(r"[\s,]+", "", data)
    if consumed != source:
        raise DxfUnsupported(f"unsupported SVG path syntax in {data!r}")
    index = 0
    command: str | None = None
    current: Point = (0.0, 0.0)
    start: Point | None = None
    points: list[Point] = []
    closed = False
    result: list[tuple[tuple[Point, ...], bool]] = []
    last_quadratic: Point | None = None
    last_cubic: Point | None = None

    def number() -> float:
        nonlocal index
        if index >= len(tokens) or tokens[index].isalpha():
            raise DxfUnsupported(f"incomplete SVG path command in {data!r}")
        value = float(tokens[index])
        index += 1
        return value

    def point(relative: bool) -> Point:
        value = number(), number()
        return (
            (current[0] + value[0], current[1] + value[1])
            if relative else value
        )

    def flush() -> None:
        nonlocal points, closed
        if len(points) >= 2:
            result.append((tuple(points), closed))
        points = []
        closed = False

    while index < len(tokens):
        if tokens[index].isalpha():
            command = tokens[index]
            index += 1
        if command is None:
            raise DxfUnsupported(f"SVG path starts without a command: {data!r}")
        upper = command.upper()
        relative = command.islower()
        if upper == "Z":
            if start is not None:
                current = start
            closed = True
            flush()
            start = None
            last_quadratic = last_cubic = None
            command = None
            continue
        if upper == "M":
            destination = point(relative)
            if points:
                flush()
            current = destination
            start = destination
            points = [destination]
            command = "l" if relative else "L"
            last_quadratic = last_cubic = None
            continue
        if start is None:
            raise DxfUnsupported(f"SVG path draws before move command: {data!r}")
        if upper == "L":
            current = point(relative)
            points.append(current)
            last_quadratic = last_cubic = None
        elif upper == "H":
            x = number() + (current[0] if relative else 0)
            current = x, current[1]
            points.append(current)
            last_quadratic = last_cubic = None
        elif upper == "V":
            y = number() + (current[1] if relative else 0)
            current = current[0], y
            points.append(current)
            last_quadratic = last_cubic = None
        elif upper == "Q":
            control = point(relative)
            destination = point(relative)
            points.extend(_sample_quadratic(current, control, destination)[1:])
            current, last_quadratic = destination, control
            last_cubic = None
        elif upper == "T":
            control = (
                (2 * current[0] - last_quadratic[0],
                 2 * current[1] - last_quadratic[1])
                if last_quadratic is not None else current
            )
            destination = point(relative)
            points.extend(_sample_quadratic(current, control, destination)[1:])
            current, last_quadratic = destination, control
            last_cubic = None
        elif upper == "C":
            first = point(relative)
            second = point(relative)
            destination = point(relative)
            points.extend(_sample_cubic(current, first, second, destination)[1:])
            current, last_cubic = destination, second
            last_quadratic = None
        elif upper == "S":
            first = (
                (2 * current[0] - last_cubic[0],
                 2 * current[1] - last_cubic[1])
                if last_cubic is not None else current
            )
            second = point(relative)
            destination = point(relative)
            points.extend(_sample_cubic(current, first, second, destination)[1:])
            current, last_cubic = destination, second
            last_quadratic = None
        elif upper == "A":
            rx, ry, rotation = number(), number(), number()
            large_arc, sweep = int(number()), int(number())
            if large_arc not in {0, 1} or sweep not in {0, 1}:
                raise DxfUnsupported("SVG arc flags must be zero or one")
            destination = point(relative)
            points.extend(_sample_arc(
                current, destination, rx, ry, rotation, large_arc, sweep,
            )[1:])
            current = destination
            last_quadratic = last_cubic = None
        else:  # pragma: no cover - tokenizer and explicit command set agree
            raise DxfUnsupported(f"unsupported SVG path command {command!r}")
    flush()
    return tuple(result)


def _points_attribute(value: str) -> tuple[Point, ...]:
    values = [float(item) for item in _NUMBER.findall(value)]
    if len(values) % 2:
        raise DxfUnsupported(f"SVG points attribute has an odd value count: {value!r}")
    return tuple(zip(values[::2], values[1::2], strict=True))


def _uniform_scale(matrix: Matrix) -> float | None:
    a, b, c, d, _e, _f = matrix
    first, second = math.hypot(a, b), math.hypot(c, d)
    if abs(first - second) > 1e-9 or abs(a * c + b * d) > 1e-9:
        return None
    return first


def _element_entities(element: ET.Element, matrix: Matrix) -> list[str]:
    tag = _tag(element)
    layer = "ANNOTATION" if element.get("stroke-dasharray") else "EDGES"
    if tag == "line":
        start = _apply(matrix, (_float(element, "x1"), _float(element, "y1")))
        end = _apply(matrix, (_float(element, "x2"), _float(element, "y2")))
        return [_line(*start, *end, layer)]
    if tag == "circle":
        center = _apply(matrix, (_float(element, "cx"), _float(element, "cy")))
        radius = _float(element, "r")
        scale = _uniform_scale(matrix)
        if scale is not None:
            return [_circle(*center, radius * scale, layer)]
        points = (_apply(matrix, item) for item in _sample_ellipse(
            _float(element, "cx"), _float(element, "cy"), radius, radius,
        ))
        return [_polyline(points, layer)]
    if tag == "ellipse":
        points = (_apply(matrix, item) for item in _sample_ellipse(
            _float(element, "cx"), _float(element, "cy"),
            _float(element, "rx"), _float(element, "ry"),
        ))
        return [_polyline(points, layer)]
    if tag == "rect":
        x, y = _float(element, "x", 0), _float(element, "y", 0)
        width, height = _float(element, "width"), _float(element, "height")
        rx = _float(element, "rx", 0)
        ry = _float(element, "ry", rx)
        points = _rounded_rect_points(
            x, y, width, height, rx, ry,
        )
        return [_polyline((_apply(matrix, item) for item in points), layer)]
    if tag in {"polygon", "polyline"}:
        points = (
            _apply(matrix, item)
            for item in _points_attribute(element.get("points", ""))
        )
        return [_polyline(points, layer, closed=tag == "polygon")]
    if tag == "path":
        return [
            _polyline(
                (_apply(matrix, item) for item in points),
                layer,
                closed=closed,
            )
            for points, closed in _path_subpaths(element.get("d", ""))
        ]
    if tag == "text":
        x, y = _float(element, "x", 0), _float(element, "y", 0)
        tx, ty = _apply(matrix, (x, y))
        size = _float(element, "font-size", 3.0) * 0.8
        rotation = math.degrees(math.atan2(matrix[1], matrix[0]))
        value = "".join(element.itertext()).strip()
        return [_text(tx, ty, size, value, rotation=rotation)] if value else []
    if tag in {"svg", "g", "tspan", "desc", "style"}:
        return []
    raise DxfUnsupported(f"unsupported SVG element <{tag}>")


def _walk(element: ET.Element, parent_matrix: Matrix) -> list[str]:
    if _tag(element) in _SKIP_TREES:
        return []
    matrix = _multiply(parent_matrix, _parse_transform(element.get("transform")))
    entities = _element_entities(element, matrix)
    for child in element:
        entities.extend(_walk(child, matrix))
    return [entity for entity in entities if entity]


def svg_to_dxf(svg: str) -> str:
    """Convert one deterministic sheet, failing rather than dropping geometry."""
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as exc:
        raise DxfUnsupported(f"invalid SVG: {exc}") from exc
    dimensioned_forms = [
        element for element in root.iter()
        if element.get("id") == "facetta-dimensioned-form"
    ]
    if len(dimensioned_forms) > 1:
        raise DxfUnsupported("more than one dimensioned-form SVG group")
    source = dimensioned_forms[0] if dimensioned_forms else root
    entities = _walk(source, IDENTITY)
    return "\n".join([
        "0", "SECTION", "2", "HEADER",
        "9", "$INSUNITS", "70", "4",
        "0", "ENDSEC",
        "0", "SECTION", "2", "ENTITIES",
        *entities,
        "0", "ENDSEC",
        "0", "EOF",
    ]) + "\n"

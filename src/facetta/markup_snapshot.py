"""Validated normalized markup snapshots and deterministic raster composition.

The mobile canvas keeps geometry in image-relative 0–1 coordinates.  This
module is the only backend bridge from that untrusted interchange format to a
raster supplied to the existing two-image markup reader.  It never fetches
``source_uri``: immutable asset bytes supplied by the caller are the sole
visual source of truth.
"""

from __future__ import annotations

import io
import math
import re
import warnings
from typing import Annotated, Literal

from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

MARKUP_SNAPSHOT_SCHEMA_VERSION = 1
MAX_MARKUP_ANNOTATIONS = 32
MAX_FREEHAND_POINTS = 1_024
MAX_TOTAL_MARKUP_POINTS = 4_096
MAX_TOTAL_MARKUP_TEXT = 2_000
MAX_SOURCE_IMAGE_BYTES = 50_000_000
MAX_SOURCE_IMAGE_DIMENSION = 8_192
MAX_SOURCE_IMAGE_PIXELS = 20_000_000
MAX_COMPOSITED_IMAGE_BYTES = 64_000_000

_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")


class _FrozenStrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        strict=True,
    )


class NormalizedMarkupPoint(_FrozenStrictModel):
    x: Annotated[float, Field(ge=0.0, le=1.0)]
    y: Annotated[float, Field(ge=0.0, le=1.0)]


class _MarkupAnnotationBase(_FrozenStrictModel):
    id: Annotated[
        str,
        Field(
            strict=True,
            min_length=1,
            max_length=64,
            pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
        ),
    ]
    color: Annotated[
        str,
        Field(strict=True, pattern=r"^#[0-9A-Fa-f]{6}$"),
    ]
    stroke_width: Annotated[float, Field(ge=0.001, le=0.1)]


class RectangleMarkupAnnotation(_MarkupAnnotationBase):
    type: Literal["rectangle"]
    start: NormalizedMarkupPoint
    end: NormalizedMarkupPoint

    @model_validator(mode="after")
    def require_area(self) -> RectangleMarkupAnnotation:
        if self.start.x == self.end.x or self.start.y == self.end.y:
            raise ValueError("rectangle annotation must have non-zero area")
        return self


class CircleMarkupAnnotation(_MarkupAnnotationBase):
    type: Literal["circle"]
    start: NormalizedMarkupPoint
    end: NormalizedMarkupPoint

    @model_validator(mode="after")
    def require_area(self) -> CircleMarkupAnnotation:
        if self.start.x == self.end.x or self.start.y == self.end.y:
            raise ValueError("circle annotation must have non-zero area")
        return self


class ArrowMarkupAnnotation(_MarkupAnnotationBase):
    type: Literal["arrow"]
    start: NormalizedMarkupPoint
    end: NormalizedMarkupPoint

    @model_validator(mode="after")
    def require_length(self) -> ArrowMarkupAnnotation:
        if self.start == self.end:
            raise ValueError("arrow annotation must have non-zero length")
        return self


class FreehandMarkupAnnotation(_MarkupAnnotationBase):
    type: Literal["freehand"]
    points: Annotated[
        list[NormalizedMarkupPoint],
        Field(min_length=2, max_length=MAX_FREEHAND_POINTS),
    ]

    @model_validator(mode="after")
    def require_visible_stroke(self) -> FreehandMarkupAnnotation:
        if all(point == self.points[0] for point in self.points[1:]):
            raise ValueError("freehand annotation must contain a visible stroke")
        return self


class TextMarkupAnnotation(_MarkupAnnotationBase):
    type: Literal["text"]
    anchor: NormalizedMarkupPoint
    text: Annotated[str, Field(strict=True, min_length=1, max_length=500)]
    font_size: Annotated[float, Field(ge=0.01, le=0.2)]

    @field_validator("text")
    @classmethod
    def require_safe_trimmed_text(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("annotation text must be trimmed")
        if _CONTROL_CHARACTERS.search(value):
            raise ValueError("annotation text cannot contain control characters")
        return value


MarkupSnapshotAnnotation = Annotated[
    RectangleMarkupAnnotation
    | CircleMarkupAnnotation
    | ArrowMarkupAnnotation
    | FreehandMarkupAnnotation
    | TextMarkupAnnotation,
    Field(discriminator="type"),
]


class MarkupSnapshot(_FrozenStrictModel):
    """Schema-v1 contract emitted by ``mobile/src/trusted/AnnotationCanvas``."""

    schema_version: Literal[1]
    coordinate_space: Literal["normalized_image"]
    source_uri: Annotated[
        str,
        Field(strict=True, min_length=1, max_length=4_096),
    ]
    annotations: Annotated[
        list[MarkupSnapshotAnnotation],
        Field(min_length=1, max_length=MAX_MARKUP_ANNOTATIONS),
    ]

    @field_validator("schema_version", mode="before")
    @classmethod
    def require_integer_schema_version(cls, value: object) -> object:
        # ``bool`` is an ``int`` subclass in Python and compares equal to 1;
        # reject it explicitly so the wire schema remains genuinely typed.
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("schema_version must be the integer 1")
        return value

    @model_validator(mode="after")
    def require_bounded_unique_content(self) -> MarkupSnapshot:
        ids = tuple(annotation.id for annotation in self.annotations)
        if len(ids) != len(set(ids)):
            raise ValueError("annotation IDs must be unique")

        point_count = 0
        text_count = 0
        for annotation in self.annotations:
            if isinstance(annotation, FreehandMarkupAnnotation):
                point_count += len(annotation.points)
            elif isinstance(annotation, TextMarkupAnnotation):
                point_count += 1
                text_count += len(annotation.text)
            else:
                point_count += 2
        if point_count > MAX_TOTAL_MARKUP_POINTS:
            raise ValueError(
                f"markup snapshot exceeds {MAX_TOTAL_MARKUP_POINTS} total points"
            )
        if text_count > MAX_TOTAL_MARKUP_TEXT:
            raise ValueError(
                f"markup snapshot exceeds {MAX_TOTAL_MARKUP_TEXT} text characters"
            )
        return self


class MarkupSnapshotImageError(ValueError):
    """The immutable source could not be safely composited."""


def _pixel_point(
    point: NormalizedMarkupPoint,
    width: int,
    height: int,
) -> tuple[int, int]:
    return (
        round(point.x * max(0, width - 1)),
        round(point.y * max(0, height - 1)),
    )


def _rgba(hex_color: str) -> tuple[int, int, int, int]:
    return (
        int(hex_color[1:3], 16),
        int(hex_color[3:5], 16),
        int(hex_color[5:7], 16),
        255,
    )


def _stroke_width(value: float, width: int, height: int) -> int:
    return max(1, round(value * min(width, height)))


def _ellipse_box(
    start: tuple[int, int],
    end: tuple[int, int],
) -> tuple[int, int, int, int]:
    return (
        min(start[0], end[0]),
        min(start[1], end[1]),
        max(start[0], end[0]),
        max(start[1], end[1]),
    )


def _draw_arrow(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    fill: tuple[int, int, int, int],
    width: int,
    min_dimension: int,
) -> None:
    draw.line((start, end), fill=fill, width=width)
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    line_length = math.hypot(end[0] - start[0], end[1] - start[1])
    head_length = min(
        max(10.0, min_dimension * 0.035),
        max(2.0, line_length * 0.5),
    )
    for offset in (-math.pi / 6, math.pi / 6):
        head = (
            round(end[0] - head_length * math.cos(angle + offset)),
            round(end[1] - head_length * math.sin(angle + offset)),
        )
        draw.line((end, head), fill=fill, width=width)


def _draw_freehand(
    draw: ImageDraw.ImageDraw,
    points: list[tuple[int, int]],
    *,
    fill: tuple[int, int, int, int],
    width: int,
) -> None:
    draw.line(points, fill=fill, width=width, joint="curve")
    radius = max(1, width // 2)
    for x, y in (points[0], points[-1]):
        draw.ellipse(
            (x - radius, y - radius, x + radius, y + radius),
            fill=fill,
        )


def _default_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # pragma: no cover - compatibility with old Pillow
        return ImageFont.load_default()


def _safe_source_image(source_bytes: bytes) -> Image.Image:
    if not source_bytes:
        raise MarkupSnapshotImageError("source asset image is empty")
    if len(source_bytes) > MAX_SOURCE_IMAGE_BYTES:
        raise MarkupSnapshotImageError(
            f"source asset exceeds {MAX_SOURCE_IMAGE_BYTES} encoded bytes"
        )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            source = Image.open(io.BytesIO(source_bytes))
            width, height = source.size
            if width <= 0 or height <= 0:
                raise MarkupSnapshotImageError(
                    "source asset has invalid image dimensions"
                )
            if width > MAX_SOURCE_IMAGE_DIMENSION or height > MAX_SOURCE_IMAGE_DIMENSION:
                raise MarkupSnapshotImageError(
                    "source asset dimensions exceed the markup canvas limit"
                )
            if width * height > MAX_SOURCE_IMAGE_PIXELS:
                raise MarkupSnapshotImageError(
                    "source asset pixel count exceeds the markup canvas limit"
                )
            source.load()
            return ImageOps.exif_transpose(source).convert("RGBA")
    except MarkupSnapshotImageError:
        raise
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        UnidentifiedImageError,
    ) as exc:
        raise MarkupSnapshotImageError(
            "source asset is not a safely decodable raster image"
        ) from exc


def composite_markup_snapshot(
    source_bytes: bytes,
    snapshot: MarkupSnapshot,
) -> bytes:
    """Composite a validated schema-v1 snapshot over immutable source bytes.

    The output is always a single-frame PNG.  Unmarked source pixels remain
    identical after decode, which keeps the existing pixel-difference mask
    trustworthy when the marked audit leaf is later applied.
    """

    canvas = _safe_source_image(source_bytes)
    width, height = canvas.size
    min_dimension = min(width, height)
    draw = ImageDraw.Draw(canvas)

    for annotation in snapshot.annotations:
        color = _rgba(annotation.color)
        stroke_width = _stroke_width(annotation.stroke_width, width, height)
        if isinstance(annotation, (RectangleMarkupAnnotation, CircleMarkupAnnotation)):
            start = _pixel_point(annotation.start, width, height)
            end = _pixel_point(annotation.end, width, height)
            box = _ellipse_box(start, end)
            if isinstance(annotation, RectangleMarkupAnnotation):
                draw.rectangle(box, outline=color, width=stroke_width)
            else:
                draw.ellipse(box, outline=color, width=stroke_width)
        elif isinstance(annotation, ArrowMarkupAnnotation):
            _draw_arrow(
                draw,
                _pixel_point(annotation.start, width, height),
                _pixel_point(annotation.end, width, height),
                fill=color,
                width=stroke_width,
                min_dimension=min_dimension,
            )
        elif isinstance(annotation, FreehandMarkupAnnotation):
            _draw_freehand(
                draw,
                [_pixel_point(point, width, height) for point in annotation.points],
                fill=color,
                width=stroke_width,
            )
        else:
            anchor = _pixel_point(annotation.anchor, width, height)
            font_size = max(8, round(annotation.font_size * min_dimension))
            draw.text(
                anchor,
                annotation.text,
                fill=color,
                font=_default_font(font_size),
                stroke_width=max(1, font_size // 16),
                stroke_fill=(255, 255, 255, 255),
            )

    output = io.BytesIO()
    canvas.save(output, format="PNG", compress_level=6, optimize=False)
    marked = output.getvalue()
    if len(marked) > MAX_COMPOSITED_IMAGE_BYTES:
        raise MarkupSnapshotImageError(
            "composited markup image exceeds the safe output limit"
        )
    return marked

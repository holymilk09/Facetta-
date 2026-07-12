"""Deterministic evidence for visible ring-band width changes."""

from __future__ import annotations

import io
import math
import statistics

from PIL import Image


def _background(image: Image.Image) -> tuple[float, float, float]:
    width, height = image.size
    edge = max(2, round(min(width, height) * 0.045))
    pixels: list[tuple[int, int, int]] = []
    for y in range(height):
        for x in range(width):
            if x < edge or x >= width - edge or y < edge or y >= height - edge:
                pixels.append(image.getpixel((x, y)))
    return tuple(float(statistics.median(channel))
                 for channel in zip(*pixels, strict=True))


def _foreground(image: Image.Image) -> list[list[bool]]:
    background = _background(image)
    threshold_sq = 28 * 28
    rows: list[list[bool]] = []
    for y in range(image.height):
        row: list[bool] = []
        for x in range(image.width):
            pixel = image.getpixel((x, y))
            distance_sq = sum(
                (float(value) - background[index]) ** 2
                for index, value in enumerate(pixel)
            )
            row.append(distance_sq > threshold_sq)
        rows.append(row)
    return rows


def _bbox(mask: list[list[bool]]) -> tuple[int, int, int, int] | None:
    xs: list[int] = []
    ys: list[int] = []
    for y, row in enumerate(mask):
        for x, value in enumerate(row):
            if value:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def _roi_metrics(
    mask: list[list[bool]],
    bbox: tuple[int, int, int, int],
) -> tuple[int, float]:
    left, top, right, bottom = bbox
    height = bottom - top + 1
    start = top + round(height * 0.45)
    end = top + round(height * 0.80)
    row_counts = [
        sum(mask[y][left:right + 1])
        for y in range(start, min(end, len(mask)))
    ]
    useful = [count for count in row_counts if count >= 4]
    return sum(useful), float(statistics.median(useful)) if useful else 0.0


def band_width_change_evidence(
    source_bytes: bytes,
    candidate_bytes: bytes,
    *,
    before_mm: float,
    after_mm: float,
    sample_size: int = 256,
) -> dict[str, int | float | bool | str]:
    """Measure lower-shank silhouette growth/shrinkage in aligned imagery.

    This is evidence that a width edit is *visible*, not proof of millimeters.
    Exact dimensions remain the validated spec plus designer/factory review.
    """
    try:
        source = Image.open(io.BytesIO(source_bytes)).convert("RGB").resize(
            (sample_size, sample_size), Image.Resampling.LANCZOS)
        candidate = Image.open(io.BytesIO(candidate_bytes)).convert("RGB").resize(
            (sample_size, sample_size), Image.Resampling.LANCZOS)
    except Exception:
        return {"checked": False, "change_visible": False}
    if before_mm <= 0 or after_mm <= 0 or before_mm == after_mm:
        return {"checked": False, "change_visible": False}
    source_mask = _foreground(source)
    candidate_mask = _foreground(candidate)
    source_bbox = _bbox(source_mask)
    candidate_bbox = _bbox(candidate_mask)
    if source_bbox is None or candidate_bbox is None:
        return {"checked": False, "change_visible": False}
    source_area, source_median = _roi_metrics(source_mask, source_bbox)
    candidate_area, candidate_median = _roi_metrics(candidate_mask, source_bbox)
    if source_area <= 0 or source_median <= 0:
        return {"checked": False, "change_visible": False}

    source_center = ((source_bbox[0] + source_bbox[2]) / 2,
                     (source_bbox[1] + source_bbox[3]) / 2)
    candidate_center = ((candidate_bbox[0] + candidate_bbox[2]) / 2,
                        (candidate_bbox[1] + candidate_bbox[3]) / 2)
    center_shift = math.dist(source_center, candidate_center) / sample_size
    source_height = source_bbox[3] - source_bbox[1] + 1
    candidate_height = candidate_bbox[3] - candidate_bbox[1] + 1
    height_ratio = candidate_height / source_height
    framing_stable = center_shift <= 0.035 and 0.96 <= height_ratio <= 1.04
    area_ratio = candidate_area / source_area
    median_ratio = candidate_median / source_median
    widening = after_mm > before_mm
    change_visible = framing_stable and (
        (area_ratio >= 1.035 and median_ratio >= 1.08)
        if widening else
        (area_ratio <= 0.965 and median_ratio <= 0.92)
    )
    return {
        "checked": True,
        "change_visible": change_visible,
        "direction": "widen" if widening else "narrow",
        "target_relative_change": round(abs(after_mm - before_mm) / before_mm, 6),
        "foreground_area_ratio": round(area_ratio, 6),
        "foreground_median_width_ratio": round(median_ratio, 6),
        "framing_stable": framing_stable,
        "center_shift": round(center_shift, 6),
        "height_ratio": round(height_ratio, 6),
    }

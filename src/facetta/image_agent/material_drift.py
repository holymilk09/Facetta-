"""Deterministic material-assignment drift checks for aligned jewelry views."""

from __future__ import annotations

import io

from PIL import Image, ImageFilter


def _pixels(image: Image.Image):
    flattened = getattr(image, "get_flattened_data", None)
    return flattened() if callable(flattened) else image.getdata()


def _foreground_bbox(image: Image.Image) -> tuple[int, int, int, int]:
    rgb = image.convert("RGB")
    width, height = rgb.size
    xs: list[int] = []
    ys: list[int] = []
    for y in range(height):
        for x in range(width):
            r, g, b = rgb.getpixel((x, y))
            saturation = max(r, g, b) - min(r, g, b)
            if min(r, g, b) < 235 or saturation > 28:
                xs.append(x)
                ys.append(y)
    if not xs:
        return 0, 0, width, height
    pad_x = max(2, round((max(xs) - min(xs) + 1) * 0.04))
    pad_y = max(2, round((max(ys) - min(ys) + 1) * 0.04))
    return (
        max(0, min(xs) - pad_x),
        max(0, min(ys) - pad_y),
        min(width, max(xs) + pad_x + 1),
        min(height, max(ys) + pad_y + 1),
    )


def white_stone_to_gold_drift(
    approved_source: bytes,
    colored_candidate: bytes,
    *,
    sample_size: int = 320,
) -> dict[str, int | float | bool]:
    """Measure faceted white regions in the source becoming gold in output.

    Both jewelry foregrounds are cropped and normalized before comparison, so
    modest framing changes do not hide a material reassignment.  The check is
    deliberately conservative: it only fails when hundreds of high-edge,
    low-saturation source pixels become strongly yellow/gold at corresponding
    jewelry positions.
    """
    try:
        source = Image.open(io.BytesIO(approved_source)).convert("RGB")
        candidate = Image.open(io.BytesIO(colored_candidate)).convert("RGB")
    except Exception:
        return {
            "checked": False,
            "source_white_feature_pixels": 0,
            "white_to_gold_pixels": 0,
            "white_to_gold_ratio": 0.0,
            "failed": False,
        }
    source = source.crop(_foreground_bbox(source)).resize(
        (sample_size, sample_size), Image.Resampling.LANCZOS)
    candidate = candidate.crop(_foreground_bbox(candidate)).resize(
        (sample_size, sample_size), Image.Resampling.LANCZOS)
    edges = source.convert("L").filter(ImageFilter.FIND_EDGES)

    source_white = 0
    changed = 0
    for src, dst, edge in zip(_pixels(source), _pixels(candidate), _pixels(edges)):
        sr, sg, sb = src
        dr, dg, db = dst
        src_brightness = (sr + sg + sb) / 3
        src_saturation = max(src) - min(src)
        white_feature = (
            145 <= src_brightness <= 248
            and src_saturation <= 72
            and edge >= 18
        )
        if not white_feature:
            continue
        source_white += 1
        dst_saturation = max(dst) - min(dst)
        gold = (
            dr >= 135 and dg >= 85 and db <= 175
            and dr - db >= 42 and dg - db >= 22
            and dst_saturation >= 55
        )
        if gold:
            changed += 1
    ratio = changed / source_white if source_white else 0.0
    failed = source_white >= 350 and changed >= 160 and ratio >= 0.18
    return {
        "checked": True,
        "source_white_feature_pixels": source_white,
        "white_to_gold_pixels": changed,
        "white_to_gold_ratio": round(ratio, 6),
        "failed": failed,
    }

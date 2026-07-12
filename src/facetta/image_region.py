"""Safe normalized source-region isolation for trusted image workflows."""

from __future__ import annotations

import io
import math

from PIL import Image, ImageOps


class ImageRegionError(ValueError):
    """The requested normalized crop cannot produce a reviewable image."""


def crop_normalized_region(
    image_bytes: bytes,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
) -> bytes:
    """Crop one normalized rectangle without changing its depicted geometry."""
    values = (x, y, width, height)
    if not all(math.isfinite(value) for value in values):
        raise ImageRegionError("source-region coordinates must be finite")
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise ImageRegionError("source region must have positive in-bounds area")
    if x + width > 1 or y + height > 1:
        raise ImageRegionError("source region exceeds normalized image bounds")
    try:
        image = Image.open(io.BytesIO(image_bytes))
        source_format = image.format or "PNG"
        image = ImageOps.exif_transpose(image)
        image.load()
    except Exception as exc:
        raise ImageRegionError("source image is not a decodable raster") from exc
    left = max(0, round(x * image.width))
    top = max(0, round(y * image.height))
    right = min(image.width, round((x + width) * image.width))
    bottom = min(image.height, round((y + height) * image.height))
    if right - left < 64 or bottom - top < 64:
        raise ImageRegionError(
            "source region is too small for reliable jewelry review"
        )
    cropped = image.crop((left, top, right, bottom))
    output = io.BytesIO()
    if source_format.upper() in {"JPEG", "JPG"}:
        if cropped.mode not in {"RGB", "L"}:
            cropped = cropped.convert("RGB")
        cropped.save(output, format="JPEG", quality=95, optimize=True)
    elif source_format.upper() == "WEBP":
        cropped.save(output, format="WEBP", quality=95, method=6)
    else:
        cropped.save(output, format="PNG", optimize=True)
    return output.getvalue()

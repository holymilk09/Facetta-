from __future__ import annotations

import io

import pytest
from PIL import Image

from facetta.image_region import ImageRegionError, crop_normalized_region


def _png(width: int = 200, height: int = 120) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (width, height), (230, 225, 218)).save(
        output, format="PNG"
    )
    return output.getvalue()


def test_normalized_crop_preserves_selected_pixel_dimensions():
    cropped = crop_normalized_region(
        _png(), x=0.1, y=0.0, width=0.5, height=1.0
    )
    with Image.open(io.BytesIO(cropped)) as image:
        assert image.size == (100, 120)
        assert image.format == "PNG"


@pytest.mark.parametrize(
    ("x", "y", "width", "height", "message"),
    [
        (0.8, 0.0, 0.3, 1.0, "exceeds"),
        (0.0, 0.0, 0.1, 0.1, "too small"),
        (float("nan"), 0.0, 1.0, 1.0, "finite"),
    ],
)
def test_normalized_crop_rejects_unsafe_regions(
    x: float,
    y: float,
    width: float,
    height: float,
    message: str,
):
    with pytest.raises(ImageRegionError, match=message):
        crop_normalized_region(
            _png(), x=x, y=y, width=width, height=height
        )

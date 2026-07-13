from __future__ import annotations

import io
import struct
import zlib

import pytest
from PIL import Image

from facetta.instant_metal_color import (
    InstantMetalColorError,
    transform_ring_gold_color,
)


def _encoded(image: Image.Image, format: str = "PNG", **kwargs) -> bytes:
    output = io.BytesIO()
    image.save(output, format=format, **kwargs)
    return output.getvalue()


def _mask(size: tuple[int, int]) -> bytes:
    image = Image.new("L", size, 0)
    for y in range(1, size[1] - 1):
        for x in range(1, size[0] - 1):
            image.putpixel((x, y), 255)
    return _encoded(image)


@pytest.mark.parametrize("controlled_color", ("yellow", "white", "rose"))
def test_supported_gold_colors_preserve_alpha_and_outside_pixels(
    controlled_color: str,
):
    source = Image.new("RGBA", (6, 6), (148, 104, 62, 173))
    source_bytes = _encoded(source)
    result = transform_ring_gold_color(
        source_bytes,
        _mask(source.size),
        controlled_color=controlled_color,
    )

    with Image.open(io.BytesIO(result.image_bytes)) as preview:
        output = preview.convert("RGBA")
    assert output.getpixel((0, 0)) == source.getpixel((0, 0))
    assert output.getpixel((2, 2)) != source.getpixel((2, 2))
    assert all(
        output.getpixel((x, y))[3] == source.getpixel((x, y))[3]
        for y in range(source.height)
        for x in range(source.width)
    )


@pytest.mark.parametrize(
    ("mode", "format", "kwargs"),
    (
        ("RGB", "JPEG", {"quality": 95}),
        ("RGB", "WEBP", {"lossless": True}),
        ("P", "PNG", {"transparency": 0}),
    ),
)
def test_released_raster_inputs_preserve_exact_decoded_outside_region(
    mode: str,
    format: str,
    kwargs: dict,
):
    if mode == "P":
        source = Image.new("P", (6, 6), 1)
        palette = [0, 0, 0, 148, 104, 62] + [0, 0, 0] * 254
        source.putpalette(palette)
        source.putpixel((0, 0), 0)
    else:
        source = Image.new(mode, (6, 6), (148, 104, 62))
    source_bytes = _encoded(source, format, **kwargs)
    with Image.open(io.BytesIO(source_bytes)) as decoded:
        decoded_rgba = decoded.convert("RGBA")
    result = transform_ring_gold_color(
        source_bytes,
        _mask(source.size),
        controlled_color="rose",
    )
    with Image.open(io.BytesIO(result.image_bytes)) as preview:
        preview_rgba = preview.convert("RGBA")
    assert preview_rgba.getpixel((0, 0)) == decoded_rgba.getpixel((0, 0))


def test_oriented_source_fails_closed_before_transform():
    source = Image.new("RGB", (8, 4), (148, 104, 62))
    exif = Image.Exif()
    exif[274] = 6
    source_bytes = _encoded(source, "JPEG", exif=exif)

    with pytest.raises(InstantMetalColorError) as caught:
        transform_ring_gold_color(
            source_bytes,
            _mask(source.size),
            controlled_color="rose",
        )
    assert caught.value.code == "instant_gold_color_orientation_unsupported"


def test_oversized_compressed_header_fails_before_pixel_materialization():
    source = bytearray(_encoded(Image.new("RGB", (1, 1), (148, 104, 62))))
    source[16:24] = struct.pack(">II", 5000, 5000)
    source[29:33] = struct.pack(">I", zlib.crc32(source[12:29]) & 0xFFFFFFFF)

    with pytest.raises(InstantMetalColorError) as caught:
        transform_ring_gold_color(
            bytes(source),
            _mask((1, 1)),
            controlled_color="rose",
        )
    assert caught.value.code == "instant_gold_color_raster_too_large"

"""Small, provider-independent media helpers shared across workflows."""

from __future__ import annotations

import io

from PIL import Image, ImageFilter


def sniff_media_type(content: bytes) -> str:
    """Return the raster media type from magic bytes.

    Provider responses and imported files are frequently mislabeled, so
    canonical persistence trusts the bytes rather than a filename. Unknown
    raster content keeps the historical PNG default for compatibility.
    """
    if content[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if content[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


def build_mask_guide(source_bytes: bytes, mask_bytes: bytes) -> bytes:
    """Build a non-product localization reference for masked image edits.

    White mask pixels are tinted magenta and outlined over the untouched
    source; black pixels remain unchanged. The original source stays the first
    provider input and this guide becomes the second, so models without a
    native mask parameter can see the selected region precisely.
    """
    try:
        source = Image.open(io.BytesIO(source_bytes)).convert("RGB")
        mask = Image.open(io.BytesIO(mask_bytes)).convert("L")
    except Exception as exc:
        raise ValueError("source and mask must be decodable raster images") from exc
    if mask.size != source.size:
        mask = mask.resize(source.size, Image.Resampling.NEAREST)
    binary = mask.point(lambda value: 255 if value >= 128 else 0)
    selected = Image.blend(
        source,
        Image.new("RGB", source.size, (255, 0, 180)),
        0.52,
    )
    guide = Image.composite(selected, source, binary)
    expanded = binary.filter(ImageFilter.MaxFilter(7))
    boundary_bytes = bytes(
        max(0, outer - inner)
        for outer, inner in zip(
            expanded.tobytes(), binary.tobytes(), strict=True)
    )
    boundary = Image.frombytes("L", binary.size, boundary_bytes)
    guide.paste((255, 255, 255), mask=boundary)
    output = io.BytesIO()
    guide.save(output, format="PNG")
    return output.getvalue()

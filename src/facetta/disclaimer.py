"""A gentle accuracy disclaimer stamped on every delivered image.

A Grok render is a faithful preview, not a photograph of the finished piece —
the client must know the crafted result may differ slightly, without being
alarmed. So every raster image the client actually sees carries a small,
tasteful caption. It is applied at the DELIVERY boundary only: stored and
derived bytes stay clean, so image-to-image (angles, worn shots) never bakes
the text into a source and the caption is never doubled.
"""

from __future__ import annotations

import base64
import glob
import io

from PIL import Image, ImageDraw, ImageFont

# Reassuring, not scary: it is a preview for design reference, and the real
# piece — handmade by the factory — may vary a touch.
DISCLAIMER_TEXT = ("Design preview — for reference; the finished handcrafted "
                   "piece may vary slightly.")

_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
)

# raster formats we stamp; SVG/technical sheets carry their own disclaimer copy
_STAMPABLE = {"image/png", "image/jpeg", "image/webp"}


def is_stampable(media_type: str | None) -> bool:
    return (media_type or "").lower() in _STAMPABLE


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _FONT_CANDIDATES:
        if glob.glob(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                pass
    try:                       # Pillow >= 10.1 scales the built-in font
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def stamp_image(image_bytes: bytes, text: str = DISCLAIMER_TEXT) -> bytes:
    """Return `image_bytes` with a subtle disclaimer caption along the bottom.
    Format-preserving (PNG stays PNG, JPEG stays JPEG). Any image that cannot
    be opened or stamped is returned unchanged — a caption must never cost the
    client their render."""
    try:
        src = Image.open(io.BytesIO(image_bytes))
        fmt = src.format or "PNG"
        base = src.convert("RGBA")
    except Exception:
        return image_bytes

    w, h = base.size
    # a slim translucent strip, sized to the image so it reads on any format
    font_size = max(11, int(w * 0.024))
    pad = max(6, int(font_size * 0.5))
    strip_h = font_size + pad * 2

    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rectangle([0, h - strip_h, w, h], fill=(15, 15, 20, 140))

    font = _font(font_size)
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        tw, th = len(text) * font_size // 2, font_size
    tx = max(pad, (w - tw) // 2)
    ty = h - strip_h + (strip_h - th) // 2 - 2
    draw.text((tx, ty), text, font=font, fill=(240, 240, 245, 235))

    out = Image.alpha_composite(base, overlay)
    buf = io.BytesIO()
    if fmt.upper() in ("JPEG", "JPG"):
        out.convert("RGB").save(buf, format="JPEG", quality=92)
    else:
        out.save(buf, format=fmt if fmt.upper() != "GIF" else "PNG")
    return buf.getvalue()


def stamp_b64(image_bytes: bytes, text: str = DISCLAIMER_TEXT) -> str:
    """Stamp then base64-encode — the convenience used by the JSON endpoints."""
    return base64.b64encode(stamp_image(image_bytes, text)).decode()

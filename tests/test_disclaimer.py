"""The accuracy disclaimer stamped on every client-facing render.

A Grok render is a faithful preview, not a photo of the finished piece — the
client must be gently told it may vary, without being scared. The stamp is
format-preserving, deterministic (so cache/identity checks still hold), and
never destroys the image on a bad input.
"""

import io

from PIL import Image

from facetta.disclaimer import (
    DISCLAIMER_TEXT, is_stampable, stamp_b64, stamp_image,
)


def _png(size=(400, 300), color=(200, 200, 200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _jpeg(size=(400, 300), color=(180, 160, 140)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG")
    return buf.getvalue()


def test_wording_is_gentle_not_scary():
    # reassuring language: a preview that may vary, not a warning
    assert "preview" in DISCLAIMER_TEXT.lower()
    assert "may vary" in DISCLAIMER_TEXT.lower()
    for scary in ("inaccurate", "warning", "not accurate", "do not rely"):
        assert scary not in DISCLAIMER_TEXT.lower()


def test_stamp_changes_the_pixels_but_keeps_size_and_format():
    src = _png()
    out = stamp_image(src)
    assert out != src                       # the caption was drawn
    a, b = Image.open(io.BytesIO(src)), Image.open(io.BytesIO(out))
    assert b.size == a.size                 # same dimensions
    assert b.format == "PNG"                # format preserved


def test_stamp_is_along_the_bottom_only():
    # the top of the image is untouched; only the bottom strip changes
    src = _png(color=(200, 200, 200))
    out = stamp_image(src)
    a = Image.open(io.BytesIO(src)).convert("RGB")
    b = Image.open(io.BytesIO(out)).convert("RGB")
    w, h = a.size
    assert a.getpixel((w // 2, 5)) == b.getpixel((w // 2, 5))       # top intact
    assert a.getpixel((w // 2, h - 4)) != b.getpixel((w // 2, h - 4))  # bottom changed


def test_jpeg_stays_jpeg():
    out = stamp_image(_jpeg())
    assert Image.open(io.BytesIO(out)).format == "JPEG"


def test_deterministic():
    src = _png()
    assert stamp_image(src) == stamp_image(src)      # identity/cache-safe
    assert stamp_b64(src) == stamp_b64(src)


def test_bad_input_is_returned_unchanged():
    junk = b"not an image at all"
    assert stamp_image(junk) == junk                 # never destroys the payload


def test_is_stampable_gate():
    assert is_stampable("image/png")
    assert is_stampable("image/jpeg")
    assert not is_stampable("image/svg+xml")         # technical sheets excluded
    assert not is_stampable("video/mp4")             # videos excluded
    assert not is_stampable(None)

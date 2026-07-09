"""The blueprint sheet: Grok paints the views, code letters the truth.

The founder's benchmark stung for a real reason — our technical sheet was the
one output the image engine never touched, so it stayed flat while a chat
restyle looked finished. This closes that gap with the same fusion the rest of
the product runs on: deterministic code draws the geometry EXACTLY (every
stone, prong, and proportion), an image model shades it into a master
jeweler's graphite illustration, and then code letters every dimension, the
gemstone key, and the title block on top — pixel-aligned, always from the
record. The engine paints; it never numbers.

The crisp line-art master (`svg_sheet.render_sheet`) stays the source of
dimensional truth — instant, offline, DXF-exact. This is its presentation
twin.
"""

from __future__ import annotations

import base64

from facetta.mockup import compile_artwork_restyle_request  # noqa: F401 (style guard)
from facetta.render import _sniff_media_type, restyle_artwork
from facetta.spec import Spec
from facetta.svg_sheet import (
    SHEET_H, SHEET_W, Branding, render_blueprint_frame, render_sheet_geometry,
)

BLUEPRINT_RASTER_WIDTH = 1485  # matches the control-image rasterization


def render_blueprint_sheet(spec: Spec, model: str = "grok_imagine",
                           branding: Branding | None = None) -> tuple[str, bool]:
    """Return (svg, was_cached). Raises RenderUnavailable without a key or
    when the provider fails — callers translate to 503/502, exactly like the
    photoreal render."""
    import cairosvg  # deferred: rasterizer needs system cairo

    geometry_png = cairosvg.svg2png(
        bytestring=render_sheet_geometry(spec).encode(),
        output_width=BLUEPRINT_RASTER_WIDTH)
    painted, cached = restyle_artwork(
        geometry_png, media_type="image/png", style="blueprint", model=model)
    media_type = _sniff_media_type(painted)
    # full-bleed, stretched to the sheet's exact frame so the painted stones
    # land where our geometry put them — the code-drawn dims then align
    image_tag = (
        f'<image x="0" y="0" width="{SHEET_W:g}" height="{SHEET_H:g}" '
        f'preserveAspectRatio="none" '
        f'href="data:{media_type};base64,{base64.b64encode(painted).decode()}"/>')
    return render_blueprint_frame(spec, image_tag, branding=branding), cached

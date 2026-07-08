"""Rasterize an SVG to PNG bytes — the one seam every control-image path needs.

The blueprint and control-image pipelines rasterize a code-drawn SVG so an
image model can paint over it. The preferred rasterizer is cairosvg, but it
needs the native cairo library, which isn't present in every environment
(including this one). So this module tries cairosvg first, then falls back to
headless Chromium (already available for the app's browser automation), and
raises a clear error only if neither works — the pipeline never dies on a
silent ImportError again.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

from facetta.render import RenderUnavailable

# Chromium bundled for Playwright; PLAYWRIGHT_BROWSERS_PATH points at it
_CHROMIUM = os.environ.get("FACETTA_CHROMIUM", "/opt/pw-browsers/chromium")


def _rasterize_cairosvg(svg: str, width: int) -> bytes | None:
    try:
        import cairosvg  # noqa: PLC0415 — deferred; native cairo may be absent
    except Exception:
        return None
    try:
        return cairosvg.svg2png(bytestring=svg.encode(), output_width=width)
    except Exception:
        return None


def _rasterize_chromium(svg: str, width: int) -> bytes | None:
    """Headless-Chromium fallback: load the SVG in a data page sized to the
    target width and screenshot it. Uses the browser the app already ships."""
    chromium = _CHROMIUM if os.path.exists(_CHROMIUM) else shutil.which("chromium")
    if not chromium:
        return None
    work = tempfile.mkdtemp(prefix="facetta-raster-")
    svg_path = os.path.join(work, "in.svg")
    png_path = os.path.join(work, "out.png")
    with open(svg_path, "w") as fh:
        fh.write(svg)
    # deterministic scale: force the SVG to render at `width` device px
    scale = max(1, round(width / _svg_px_width(svg)))
    cmd = [
        chromium, "--headless", "--no-sandbox", "--disable-gpu",
        "--hide-scrollbars", "--default-background-color=00000000",
        f"--force-device-scale-factor={scale}",
        f"--screenshot={png_path}",
        f"--window-size={_svg_px_width(svg)},{_svg_px_height(svg)}",
        "file://" + svg_path,
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=90, check=True)
        with open(png_path, "rb") as fh:
            return fh.read()
    except Exception:
        return None


def _svg_dim(svg: str, attr: str) -> float:
    import re

    m = re.search(rf'{attr}="([\d.]+)', svg)
    if m:
        return float(m.group(1))
    # fall back to the viewBox
    vb = re.search(r'viewBox="[\d.]+ [\d.]+ ([\d.]+) ([\d.]+)"', svg)
    if vb:
        return float(vb.group(1) if attr == "width" else vb.group(2))
    return 297.0 if attr == "width" else 210.0


def _svg_px_width(svg: str) -> int:
    return max(1, round(_svg_dim(svg, "width")))


def _svg_px_height(svg: str) -> int:
    return max(1, round(_svg_dim(svg, "height")))


def rasterize_svg(svg: str, width: int = 1485) -> bytes:
    """SVG string → PNG bytes at `width` px. Tries cairosvg, then Chromium.
    Raises RenderUnavailable if neither rasterizer is usable — the caller
    maps it to 503/502 like any other engine outage."""
    png = _rasterize_cairosvg(svg, width) or _rasterize_chromium(svg, width)
    if png is None:
        raise RenderUnavailable(
            "no SVG rasterizer available — install cairosvg (with system "
            "cairo) or make Chromium reachable for the control-image path")
    return png

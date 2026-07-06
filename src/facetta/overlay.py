"""Deterministic annotations over the designer's artwork (or its restyle).

The division of labor the Grok-chat experiment settled: an image engine can
restyle a drawn page with near-perfect compositional fidelity — and letters
pure fiction the moment it is allowed to annotate (garbled words, invented
millimeters, wrong gemology). So the raster — the designer's hand or the
engine's paint — carries the look, and every letter and number on the page
is drawn here, by code, from the validated spec. This module exists because
engines letter fiction.

Anchoring: cluster positions come from facetta.trace in FRACTIONS of the
image, traced from the original artwork. Because a restyle is
composition-preserving, the same fractions land on a restyled raster at any
resolution — pass the original as anchor_image_bytes when the display image
cannot be traced (ink line art has no green ink).
"""

from __future__ import annotations

import base64
import io

from facetta.render import _sniff_media_type
from facetta.spec import Spec
from facetta.svg_sheet import FAINT, FONT, INK, MARGIN, PAPER, STROKE_DIM, \
    STROKE_MAIN, _line, _stone_schedule, _text
from facetta.trace import trace_spray_detailed
from facetta.validation import spray_cluster_row
from facetta.vocabulary import get_vocabulary

SHEET_W, SHEET_H = 297.0, 210.0  # landscape A4, like every Facetta sheet
ART_W = 180.0                    # the artwork's drawn width on the sheet


class OverlayUnsupported(ValueError):
    """The spec and the artwork disagree — the sheet cannot be lettered
    honestly, so it is not lettered at all."""


def _fmt(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def render_annotated_artwork(spec: Spec, image_bytes: bytes,
                             anchor_image_bytes: bytes | None = None) -> str:
    """The artwork as the drawing, the spec as every number on the page.

    image_bytes is the raster shown (original artwork or an in-place
    restyle); anchor_image_bytes, when given, is the image the anchors are
    traced from (default: the display image itself)."""
    if spec.template != "leaf_spray_brooch" or spec.brooch is None:
        raise OverlayUnsupported(
            "annotated artwork currently covers template 'leaf_spray_brooch' "
            "with a brooch section")
    trace = trace_spray_detailed(io.BytesIO(anchor_image_bytes or image_bytes))
    row = spray_cluster_row(spec)
    if len(trace.clusters_px) != len(row):
        raise OverlayUnsupported(
            f"the spec defines {len(row)} clusters but the artwork traces "
            f"{len(trace.clusters_px)} — the sheet cannot be lettered honestly")

    img_w, img_h = trace.image_size
    aw = ART_W
    ah = aw * img_h / img_w
    if ah > SHEET_H - 2 * MARGIN - 24:  # leave the title strip clear
        ah = SHEET_H - 2 * MARGIN - 24
        aw = ah * img_w / img_h
    ax, ay = MARGIN + 2, MARGIN + 3
    media_type = _sniff_media_type(image_bytes)

    def at(px: float, py: float) -> tuple[float, float]:
        return ax + px / img_w * aw, ay + py / img_h * ah

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SHEET_W:g} {SHEET_H:g}" '
        f'width="{SHEET_W:g}mm" height="{SHEET_H:g}mm" font-family="{FONT}">',
        f'<rect x="0" y="0" width="{SHEET_W:g}" height="{SHEET_H:g}" fill="{PAPER}"/>',
        f'<rect x="{MARGIN:g}" y="{MARGIN:g}" width="{SHEET_W - 2 * MARGIN:g}" '
        f'height="{SHEET_H - 2 * MARGIN:g}" fill="none" stroke="{INK}" '
        f'stroke-width="{STROKE_MAIN}"/>',
        f'<image x="{ax:.2f}" y="{ay:.2f}" width="{aw:.2f}" height="{ah:.2f}" '
        f'preserveAspectRatio="xMidYMid meet" '
        f'href="data:{media_type};base64,{base64.b64encode(image_bytes).decode()}"/>',
    ]

    # callouts: the traced clusters lettered with the SCHEDULE's own refs —
    # petal stones by identity, so a repeated definition keeps one letter
    stones = [spec.stone] + spec.side_stones
    for i, ((px, py, pr), (petal, d_mm)) in enumerate(zip(trace.clusters_px, row)):
        ref = chr(65 + stones.index(petal))
        cx, cy = at(px, py)
        r_pp = pr / img_w * aw
        up = i % 2 == 0
        lx = cx + r_pp * 0.8
        ly = cy + (-1 if up else 1) * (r_pp + 6)
        parts += [
            _line(cx + r_pp * 0.55, cy + (-1 if up else 1) * r_pp * 0.55,
                  lx, ly, w=STROKE_DIM, color=INK),
            _text(lx + 1.2, ly + (0 if up else 2.6),
                  f"{ref} — ⌀ {_fmt(d_mm)}", size=3.0, anchor="start", halo=True),
        ]

    # right column: schedule (shared with the technical sheet — the letters
    # can never disagree), then dimensions, all from the validated spec
    col_x = MARGIN + 2 + max(aw, ART_W) + 6
    col_x = min(col_x, SHEET_W - MARGIN - 96)
    parts += _stone_schedule(spec, col_x, MARGIN + 8)
    dims_y = MARGIN + 8 + 5.0 + 3.9 * len(stones) + 10
    tol = get_vocabulary().manufacturing_tolerances()["general_linear_tolerance_mm"]
    dim_lines = [
        ("DIMENSIONS (mm)", True),
        (f"overall {_fmt(spec.brooch.length_mm)} × {_fmt(spec.brooch.width_mm)}", False),
        (f"terminal cluster ⌀ {_fmt(row[0][1])}", False),
        (f"stations ⌀ {' / '.join(_fmt(d) for _, d in row[1:])}", False),
        (f"linear dims ±{_fmt(tol)} unless noted", False),
    ]
    parts.append(_line(col_x, dims_y - 4, col_x + 92, dims_y - 4,
                       w=STROKE_DIM, color=FAINT))
    for k, (line, header) in enumerate(dim_lines):
        parts.append(_text(col_x, dims_y + k * 4.2, line,
                           size=3.0 if header else 2.8, anchor="start",
                           color=INK if header else FAINT,
                           style=' letter-spacing="1.4"' if header else ""))

    # title block: the spec speaks, the model never letters
    metal = spec.metal
    metal_line = (f"{metal.karat}k {metal.color} {metal.material}, "
                  f"{(metal.finish or 'polished').replace('_', ' ')}"
                  if metal else "metal TBD")
    ty = SHEET_H - MARGIN - 14
    parts += [
        _line(MARGIN + 2, ty - 5, SHEET_W - MARGIN - 2, ty - 5,
              w=STROKE_DIM, color=FAINT),
        _text(MARGIN + 4, ty, f"{spec.design_id}  ·  v{spec.version}  ·  "
              "LEAF SPRAY BROOCH", size=4.0, anchor="start",
              style=' letter-spacing="1.2"'),
        _text(MARGIN + 4, ty + 5, metal_line, size=3.0, anchor="start",
              color=FAINT),
        _text(SHEET_W - MARGIN - 4, ty,
              "artwork by the designer · every number from the design record",
              size=2.8, anchor="end", color=FAINT),
        _text(SHEET_W - MARGIN - 4, ty + 5,
              f"designer {spec.created_by} · {spec.created_at.date().isoformat()}"
              "  ·  FACETTA", size=2.8, anchor="end", color=FAINT),
        "</svg>",
    ]
    return "\n".join(parts) + "\n"

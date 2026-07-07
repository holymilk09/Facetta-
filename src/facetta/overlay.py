"""Deterministic annotations over the designer's artwork (or a render of it).

The division of labor the Grok-chat experiment settled: an image engine can
restyle a drawn page with near-perfect compositional fidelity — and letters
pure fiction the moment it is allowed to annotate (garbled words, invented
millimeters, wrong gemology). So the raster — the designer's hand or the
engine's paint — carries the look, and every letter and number on the page
is drawn here, by code, from the validated spec. This module exists because
engines letter fiction.

Anchoring strategies:
- leaf-spray specs use the archetype tracer (quatrefoil chain, one callout
  per cluster);
- everything else uses the generic stone tracer: per schedule entry, the
  anchor whose traced size best matches the entry's spec size, scaled by
  the center stone;
- when the image cannot be traced against the spec, the sheet degrades
  honestly — callouts are omitted (and say so), the schedule, dimensions,
  and title always letter.
"""

from __future__ import annotations

import base64
import io
import math

from facetta.render import _sniff_media_type
from facetta.spec import Spec, Stone
from facetta.svg_sheet import FAINT, FONT, INK, MARGIN, PAPER, STROKE_DIM, \
    STROKE_MAIN, _line, _stone_schedule, _text
from facetta.trace import trace_spray_detailed, trace_stones
from facetta.validation import spray_cluster_row
from facetta.vocabulary import get_vocabulary

SHEET_W, SHEET_H = 297.0, 210.0  # landscape A4, like every Facetta sheet
ART_W = 180.0                    # the artwork's drawn width on the sheet
MASTHEAD_H = 17.0                # the brand strip across the top

# species → traceable body-color class; species outside this map anchor by
# size ranking only
COLOR_CLASS = {
    "emerald": "green", "garnet": "green", "peridot": "green",
    "tourmaline": "green", "tsavorite": "green",
    "aquamarine": "blue", "sapphire": "blue", "topaz": "blue",
    "tanzanite": "blue", "iolite": "blue", "zircon": "blue",
    "ruby": "red", "spinel": "red", "red_beryl": "red",
}


class OverlayUnsupported(ValueError):
    """The spec and the artwork disagree — the sheet cannot be lettered
    honestly, so it is not lettered at all."""


def _fmt(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _stone_diag_mm(stone: Stone) -> float:
    """The traced anchor radius in mm: a round's circumscribed circle is its
    own girdle; an elongated cut circumscribes on its half-diagonal."""
    d = stone.dimensions_mm
    if d.length == d.width:
        return d.width / 2
    return math.hypot(d.length, d.width) / 2


def _spray_callouts(spec: Spec, anchor_bytes: bytes) -> list[tuple]:
    """(x_px, y_px, r_px, label) per quatrefoil cluster — leaf-spray path."""
    trace = trace_spray_detailed(io.BytesIO(anchor_bytes))
    row = spray_cluster_row(spec)
    if len(trace.clusters_px) != len(row):
        raise OverlayUnsupported(
            f"the spec defines {len(row)} clusters but the artwork traces "
            f"{len(trace.clusters_px)} — the sheet cannot be lettered honestly")
    stones = [spec.stone] + spec.side_stones
    out = []
    for (px, py, pr), (petal, d_mm) in zip(trace.clusters_px, row):
        ref = chr(65 + stones.index(petal))
        out.append((px, py, pr, f"{ref} — ⌀ {_fmt(d_mm)}"))
    return out, trace.image_size


def _generic_callouts(spec: Spec, anchor_bytes: bytes) -> list[tuple]:
    """One callout per schedule entry: the traced anchor whose size best
    matches the entry, scaled through the center stone. Honest by
    construction — an entry with no matching anchor gets no callout."""
    anchors = trace_stones(io.BytesIO(anchor_bytes))
    if not anchors:
        raise OverlayUnsupported("no stones traced in the image")
    from PIL import Image
    image_size = Image.open(io.BytesIO(anchor_bytes)).size

    stones = [spec.stone] + spec.side_stones
    center_class = COLOR_CLASS.get(spec.stone.species)
    scale = None
    if center_class:
        own = [a for a in anchors if a.color_class == center_class]
        if own:
            biggest = max(own, key=lambda a: a.radius)
            scale = biggest.radius / _stone_diag_mm(spec.stone)
    if scale is None:  # no classed center: rank the largest against the largest
        biggest = max(anchors, key=lambda a: a.radius)
        scale = biggest.radius / max(_stone_diag_mm(s) for s in stones)

    unused = list(anchors)
    out = []
    for i, stone in enumerate(stones):
        cls = COLOR_CLASS.get(stone.species)
        if cls is None:
            continue  # colorless stones aren't traceable: no anchor is claimed
        pool = [a for a in unused if a.color_class == cls]
        if not pool:
            continue
        expected = _stone_diag_mm(stone) * scale
        take = sorted(pool, key=lambda a: abs(a.radius - expected))
        take = take[:min(stone.count, len(take))]
        for a in take:
            unused.remove(a)
        first = min(take, key=lambda a: a.y)
        d = stone.dimensions_mm
        size = (f"⌀ {_fmt(d.width)}" if d.length == d.width
                else f"{_fmt(d.length)} × {_fmt(d.width)}")
        out.append((first.x, first.y, first.radius, f"{chr(65 + i)} — {size}"))
    return out, image_size


def render_annotated_artwork(spec: Spec, image_bytes: bytes,
                             anchor_image_bytes: bytes | None = None) -> str:
    """The artwork (or its render) as the drawing, the spec as every number.

    image_bytes is the raster shown; anchor_image_bytes, when given, is the
    image the anchors are traced from (an in-place restyle keeps the
    original's composition, so the original can anchor a line-art render)."""
    anchor_bytes = anchor_image_bytes or image_bytes
    strict = anchor_image_bytes is not None
    callouts, image_size, degrade_note = [], None, None
    try:
        if spec.template == "leaf_spray_brooch" and spec.brooch is not None:
            callouts, image_size = _spray_callouts(spec, anchor_bytes)
        else:
            callouts, image_size = _generic_callouts(spec, anchor_bytes)
    except (OverlayUnsupported, ValueError) as exc:
        if strict:
            raise OverlayUnsupported(str(exc)) from exc
        # a drop earring carries every number in its dimensions column, so an
        # untraceable render (e.g. diamonds on gold) degrades silently — the
        # render stays the drawing, the record still speaks. Other pieces say so.
        if spec.template != "deco_drop_earring":
            degrade_note = ("cluster callouts omitted — the image could not be "
                            "traced against the spec")
    if image_size is None:
        from PIL import Image
        image_size = Image.open(io.BytesIO(image_bytes)).size

    img_w, img_h = image_size
    aw = ART_W
    ah = aw * img_h / img_w
    if ah > SHEET_H - 2 * MARGIN - MASTHEAD_H - 22:  # masthead + title strip
        ah = SHEET_H - 2 * MARGIN - MASTHEAD_H - 22
        aw = ah * img_w / img_h
    ax, ay = MARGIN + 2, MARGIN + MASTHEAD_H + 2
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
        # the brand masthead: FACETTA speaks for the sheet, the model never does
        _text(SHEET_W / 2, MARGIN + 8.5, "FACETTA", size=7.0,
              style=' letter-spacing="6"'),
        _text(SHEET_W / 2, MARGIN + 13.5,
              f"FACTORY SHEET — {spec.design_id} · v{spec.version}",
              size=3.0, color=FAINT, style=' letter-spacing="1.6"'),
        _line(MARGIN + 3, MARGIN + MASTHEAD_H - 1,
              SHEET_W - MARGIN - 3, MARGIN + MASTHEAD_H - 1,
              w=STROKE_DIM, color=FAINT),
        f'<image x="{ax:.2f}" y="{ay:.2f}" width="{aw:.2f}" height="{ah:.2f}" '
        f'preserveAspectRatio="xMidYMid meet" '
        f'href="data:{media_type};base64,{base64.b64encode(image_bytes).decode()}"/>',
    ]

    for i, (px, py, pr, label) in enumerate(callouts):
        cx, cy = at(px, py)
        r_pp = pr / img_w * aw
        # labels leave sideways so a vertical piece never reads ambiguously
        side = 1 if i % 2 == 0 else -1
        lx = cx + side * (r_pp + 9)
        parts += [
            _line(cx + side * r_pp * 0.9, cy, lx, cy, w=STROKE_DIM, color=INK),
            _text(lx + side * 1.2, cy + 1.0, label, size=3.0,
                  anchor="start" if side > 0 else "end", halo=True),
        ]
    if degrade_note:
        parts.append(_text(ax + aw / 2, ay + ah + 4, degrade_note,
                           size=2.6, color=FAINT))

    # right column: schedule (shared with the technical sheet — the letters
    # can never disagree), then dimensions, all from the validated spec
    stones = [spec.stone] + spec.side_stones
    col_x = min(MARGIN + 2 + aw + 6, SHEET_W - MARGIN - 96)
    parts += _stone_schedule(spec, col_x, MARGIN + MASTHEAD_H + 4)
    dims_y = MARGIN + MASTHEAD_H + 4 + 5.0 + 3.9 * len(stones) + 10
    tol = get_vocabulary().manufacturing_tolerances()["general_linear_tolerance_mm"]
    d = spec.stone.dimensions_mm
    dim_lines = [("DIMENSIONS (mm)", True)]
    if spec.brooch is not None:
        dim_lines.append((f"overall {_fmt(spec.brooch.length_mm)} × "
                          f"{_fmt(spec.brooch.width_mm)}", False))
    elif spec.ring_size is not None:
        rs = spec.ring_size
        inner = (f", inner ⌀ {_fmt(rs.inner_diameter_mm)}"
                 if rs.inner_diameter_mm else "")
        dim_lines.append((f"ring size {rs.system} {rs.value}{inner}", False))
        if spec.band is not None:
            dim_lines.append((f"band {_fmt(spec.band.width_mm)} wide × "
                              f"{_fmt(spec.band.thickness_mm)} thick", False))
        if spec.setting is not None and spec.setting.gallery_height_mm:
            dim_lines.append((f"gallery {_fmt(spec.setting.gallery_height_mm)} "
                              "under center", False))
    elif spec.drop is not None:
        dr = spec.drop
        dim_lines.append((f"overall length {_fmt(dr.overall_length_mm)}", False))
        run = (f"  ·  {dr.link_count} links @ {_fmt(dr.link_pitch_mm)}"
               if dr.link_count and dr.link_pitch_mm else "")
        dim_lines.append((f"hook {_fmt(dr.hook_height_mm)}{run}", False))
        halo = next((s for s in spec.side_stones
                     if s.position in ("halo", "surround")), None)
        if halo is not None:
            dim_lines.append((f"pavé halo {halo.count} × ⌀"
                              f"{_fmt(halo.dimensions_mm.width)}", False))
        gauge = "  ·  ".join(filter(None, [
            f"wall {_fmt(dr.wall_mm)}" if dr.wall_mm else "",
            f"wire {_fmt(dr.wire_mm)}" if dr.wire_mm else ""]))
        if gauge:
            dim_lines.append((gauge, False))
    else:
        dim_lines.append(("overall extent — pending designer", False))
    if spec.template == "leaf_spray_brooch":
        row = spray_cluster_row(spec)
        dim_lines += [
            (f"terminal cluster ⌀ {_fmt(row[0][1])}", False),
            (f"stations ⌀ {' / '.join(_fmt(dd) for _, dd in row[1:])}", False),
        ]
    else:
        dim_lines.append((f"center stone {_fmt(d.length)} × {_fmt(d.width)} "
                          f"× {_fmt(d.depth)}", False))
    dim_lines.append((f"linear dims ±{_fmt(tol)} unless noted", False))
    parts.append(_line(col_x, dims_y - 4, col_x + 92, dims_y - 4,
                       w=STROKE_DIM, color=FAINT))
    for k, (line, header) in enumerate(dim_lines):
        parts.append(_text(col_x, dims_y + k * 4.2, line,
                           size=3.0 if header else 2.8, anchor="start",
                           color=INK if header else FAINT,
                           style=' letter-spacing="1.4"' if header else ""))

    # title block: the spec speaks, the model never letters
    metal = spec.metal
    if metal:
        bits = [f"{metal.karat}k" if metal.karat else "",
                metal.color or "", metal.material]
        metal_line = (" ".join(b for b in bits if b)
                      + f", {(metal.finish or 'polished').replace('_', ' ')}")
    else:
        metal_line = "metal TBD"
    piece = spec.template.replace("_", " ").upper()
    ty = SHEET_H - MARGIN - 14
    parts += [
        _line(MARGIN + 2, ty - 5, SHEET_W - MARGIN - 2, ty - 5,
              w=STROKE_DIM, color=FAINT),
        _text(MARGIN + 4, ty, f"{spec.design_id}  ·  v{spec.version}  ·  {piece}",
              size=4.0, anchor="start", style=' letter-spacing="1.2"'),
        _text(MARGIN + 4, ty + 5, metal_line, size=3.0, anchor="start",
              color=FAINT),
        _text(SHEET_W - MARGIN - 4, ty,
              "every number from the design record — never from the image",
              size=2.8, anchor="end", color=FAINT),
        _text(SHEET_W - MARGIN - 4, ty + 5,
              f"designer {spec.created_by} · {spec.created_at.date().isoformat()}",
              size=2.8, anchor="end", color=FAINT),
        "</svg>",
    ]
    return "\n".join(parts) + "\n"

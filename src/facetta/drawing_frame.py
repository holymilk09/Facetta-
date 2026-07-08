"""The official Facetta frame for the agent-drawn manufacturing technical
drawing — applied by CODE, from the record, never by the model.

The live test caught Grok signing a sheet 'ATELIER PRECIEUX | JOB REF
2024-E01 | DATE 2024-10-26' — pure fiction. So the division of labor is the
same one every Facetta artifact obeys: the model draws geometry (with the
templated instruction telling it to leave clean margins), and this module
letters the masthead, the piece name, the full stone schedule, the materials
and construction, the designer, the date, and the signature from the validated
spec and the designer's branding. A letter the record cannot vouch for never
reaches the page.
"""

from __future__ import annotations

import base64
import io
from xml.sax.saxutils import escape

from facetta.render import _sniff_media_type
from facetta.spec import Spec
from facetta.svg_sheet import (
    FAINT, FONT, INK, PAPER, STROKE_DIM, STROKE_MAIN, Branding, _fmt, _line,
    _metal_line, _stone_schedule, _text, _wrap,
)
from facetta.validation import estimate_metal_g

MARGIN = 8.0
FOOTER_H = 22.0     # identity + signature + disclaimer band (below the panel)

# NB: keep this XML-safe (no raw &/<>) — it letters a <text> element. The
# wording matches specagent.DISCLAIMER.
DISCLAIMER = ("Manufacturing illustration — final dimensions after master "
              "model and sign-off.")


def _dimension_lines(spec: Spec) -> list[tuple[str, str]]:
    """The materials + construction facts a factory needs that aren't stones:
    metal, mount, the piece's own key measurements, tolerance, and units —
    each straight from the record, TBD-free (only what's present is lettered)."""
    lines: list[tuple[str, str]] = [("METAL", _metal_line(spec.metal))]

    weight = estimate_metal_g(spec)
    if weight:
        lines.append(("EST. METAL", f"{weight} g"))

    if spec.setting is not None:
        style = spec.setting.style.replace("_", " ").title()
        # only append the prong count when the style name doesn't already
        # carry it — 'Prong 4 · 4-prong' read as a stutter on the live sheet
        if (spec.setting.prong_count
                and str(spec.setting.prong_count) not in style):
            style += f"  ·  {spec.setting.prong_count}-prong"
        lines.append(("SETTING", style))

    if spec.band is not None:
        b = spec.band
        lines.append(("BAND", f"{b.profile.replace('_', ' ')}  ·  "
                              f"{_fmt(b.width_mm)} × {_fmt(b.thickness_mm)} mm"))

    if spec.ring_size is not None:
        rs = spec.ring_size
        val = f"{rs.system} {rs.value}"
        if rs.inner_diameter_mm:
            val += f"  ·  ⌀ {_fmt(rs.inner_diameter_mm)} mm"
        lines.append(("RING SIZE", val))

    if spec.drop is not None:
        lines.append(("DROP LENGTH", f"{_fmt(spec.drop.overall_length_mm)} mm"))
        if spec.drop.link_count:
            lines.append(("LINKS", str(spec.drop.link_count)))

    if spec.pendant is not None and spec.pendant.drop_mm:
        lines.append(("DROP", f"{_fmt(spec.pendant.drop_mm)} mm"))

    if spec.bracelet is not None:
        br = spec.bracelet
        lines.append(("INNER", f"{_fmt(br.inner_length_mm)} × "
                               f"{_fmt(br.inner_width_mm)} mm"))

    if spec.chain is not None:
        lines.append(("CHAIN", f"{spec.chain.style.replace('_', ' ')}  ·  "
                               f"{_fmt(spec.chain.length_mm)} mm"))

    if spec.brooch is not None:
        lines.append(("FOOTPRINT", f"{_fmt(spec.brooch.length_mm)} × "
                                   f"{_fmt(spec.brooch.width_mm)} mm"))

    # one compact line: the tolerance and the unit convention travel together
    lines.append(("TOLERANCE", "± 0.10 mm general  ·  all dims in mm"))
    return lines


_NOTE_LINES = 2      # factory notes wrap to a short paragraph, never one long cut


def _panel_height(spec: Spec) -> float:
    """The panel grows with the record instead of clipping it: a piece with
    eight stone groups gets a taller schedule, the drawing area gives up the
    difference. Mirrors the row math of _stone_schedule / _spec_panel."""
    rows = 1 + len(spec.side_stones)
    left = 9.4 + rows * 3.9                       # header + rows + total line
    right = 5.0 + len(_dimension_lines(spec)) * 4.0
    if spec.notes_to_factory:
        right += 4.6 + 3.6 * _NOTE_LINES
    return max(40.0, max(left, right) + 8.0)


def _spec_panel(spec: Spec, x0: float, y0: float, x1: float,
                height: float) -> list[str]:
    """The specification panel: the full stone schedule on the left (every
    stone's count, size, and type, with total set weight) and the
    non-stone build — metal, mount, band, overall measurement, tolerance —
    on the right. Common-sense factory title-block content, all lettered by
    code from the validated record. The two halves never overlap: stone sizes
    live in the schedule, the metalwork lives in construction."""
    parts = _stone_schedule(spec, x0, y0, circled=False, totals=True)

    rx = x0 + 108
    parts.append(_line(rx - 6, y0 - 1.0, rx - 6, y0 + height - 8.0,
                       w=STROKE_DIM, color=FAINT))
    parts.append(_text(rx, y0, "MATERIALS &amp; CONSTRUCTION", size=3.0,
                       anchor="start", style=' letter-spacing="1.2"'))
    parts.append(_line(rx, y0 + 1.4, x1, y0 + 1.4, w=STROKE_DIM, color=FAINT))

    y = y0 + 5.0
    for label, value in _dimension_lines(spec):
        y += 4.0
        parts.append(_text(rx, y, label, size=2.4, anchor="start", color=FAINT))
        parts.append(_text(rx + 24, y, escape(value), size=2.8, anchor="start"))

    if spec.notes_to_factory:
        y += 4.6
        parts.append(_text(rx, y, "FACTORY NOTES", size=2.4, anchor="start",
                           color=FAINT))
        width_chars = max(24, int((x1 - rx) / 1.55))
        for row in _wrap(spec.notes_to_factory, width_chars, _NOTE_LINES):
            y += 3.6
            parts.append(_text(rx, y, escape(row), size=2.6, anchor="start"))
    return parts


def _estimate_panel_height(est: dict) -> float:
    rows = max(len(est.get("stones") or []), 1)
    left = 9.4 + rows * 3.9
    right = 5.0 + (1 + len(est.get("measurements") or [])) * 4.0
    return max(40.0, max(left, right) + 12.0)   # extra row: the confirm banner


def _estimate_panel(est: dict, x0: float, y0: float, x1: float) -> list[str]:
    """The ASSIST panel: Grok's vision-estimated read of the render, lettered
    by CODE and unmistakably marked as estimates. Same two-column layout as
    the record panel, so the sheet reads the same — but every value carries
    the confirm-before-production banner instead of the record's authority."""
    parts = [
        _text(x0, y0, "ESTIMATED SPECIFICATIONS", size=3.0, anchor="start",
              style=' letter-spacing="1.2"'),
        _line(x0, y0 + 1.4, x0 + 100, y0 + 1.4, w=STROKE_DIM, color=FAINT),
        _text(x0, y0 + 5.0, "QTY", size=2.4, anchor="start", color=FAINT),
        _text(x0 + 9, y0 + 5.0, "STONE (estimated)", size=2.4, anchor="start",
              color=FAINT),
        _text(x0 + 55, y0 + 5.0, "~SIZE mm", size=2.4, anchor="start",
              color=FAINT),
        _text(x0 + 78, y0 + 5.0, "~CT EA.", size=2.4, anchor="start",
              color=FAINT),
    ]
    y = y0 + 5.0
    for s in (est.get("stones") or [])[:8]:
        y += 3.9
        ct = s.get("carat_each")
        parts += [
            _text(x0, y, str(s.get("qty", 1)), size=2.6, anchor="start"),
            _text(x0 + 9, y, escape(str(s.get("type", ""))[:34]), size=2.6,
                  anchor="start"),
            _text(x0 + 55, y, escape(str(s.get("size_mm", "TBD"))), size=2.6,
                  anchor="start"),
            _text(x0 + 78, y, f"{ct:.2f}" if isinstance(ct, (int, float))
                  else "TBD", size=2.6, anchor="start"),
        ]

    rx = x0 + 108
    parts.append(_line(rx - 6, y0 - 1.0, rx - 6,
                       y0 + _estimate_panel_height(est) - 12.0,
                       w=STROKE_DIM, color=FAINT))
    parts.append(_text(rx, y0, "MATERIALS (ESTIMATED)",
                       size=3.0, anchor="start", style=' letter-spacing="1.2"'))
    parts.append(_line(rx, y0 + 1.4, x1, y0 + 1.4, w=STROKE_DIM, color=FAINT))
    ry = y0 + 5.0
    rows = [("METAL", str(est.get("metal") or "TBD"))]
    rows += [(str(label).upper()[:20], str(value))
             for label, value in (est.get("measurements") or [])[:6]]
    for label, value in rows:
        ry += 4.0
        parts.append(_text(rx, ry, escape(label), size=2.4, anchor="start",
                           color=FAINT))
        parts.append(_text(rx + 34, ry, escape(value)[:60], size=2.8,
                           anchor="start"))

    banner_y = y0 + _estimate_panel_height(est) - 9.0
    parts.append(_text(x0, banner_y,
                       "ALL VALUES ESTIMATED FROM THE RENDER — designer must "
                       "confirm every value before production.",
                       size=2.6, anchor="start", color=FAINT,
                       style=' font-style="italic"'))
    return parts


def frame_technical_drawing(drawing_bytes: bytes, spec: Spec | None = None,
                            branding: Branding | None = None,
                            piece_name: str | None = None,
                            estimates: dict | None = None,
                            approval: str | None = None) -> str:
    """Wrap the agent's drawing in the official Facetta template: A4 page
    (orientation follows the drawing), a masthead (with an optional piece
    name), the drawing centered, a specification panel (stone schedule +
    materials & dimensions), and an identity footer — everything but the
    drawing lettered from the record.

    spec=None frames an unsaved drawing — identity shows the pending
    placeholders instead of inventing anything. piece_name is the optional
    friendly title of the piece ('The Vérité Solitaire'); blank falls back to
    the design id in the subtitle.

    estimates (only honored when spec is None) is the assist path for the
    ballpark designer: Grok's vision read of the render
    (specagent.read_sheet_specs), lettered by code into an ESTIMATED panel —
    the model never paints spec text on the sheet. A validated spec always
    wins over estimates.

    approval, when given, is the checklist sign-off line
    ('approved 7/7 · usr_ana · 2026-07-08') lettered on the identity row —
    built by the caller from the approval record, never invented here."""
    from PIL import Image

    img_w, img_h = Image.open(io.BytesIO(drawing_bytes)).size
    portrait = img_h > img_w
    sheet_w, sheet_h = (210.0, 297.0) if portrait else (297.0, 210.0)

    house = branding.house_line if branding else None
    signature = branding.signature_line if branding else None
    masthead = house or "FACETTA"
    design_id = spec.design_id if spec is not None else "dsn_pending"
    version = spec.version if spec is not None else 1
    name = " ".join(piece_name.split())[:48] if piece_name else None
    masthead_h = 21.0 if name else 17.0

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {sheet_w:g} {sheet_h:g}" '
        f'width="{sheet_w:g}mm" height="{sheet_h:g}mm" font-family="{FONT}">',
        f'<rect x="0" y="0" width="{sheet_w:g}" height="{sheet_h:g}" '
        f'fill="{PAPER}"/>',
        f'<rect x="{MARGIN:g}" y="{MARGIN:g}" '
        f'width="{sheet_w - 2 * MARGIN:g}" height="{sheet_h - 2 * MARGIN:g}" '
        f'fill="none" stroke="{INK}" stroke-width="{STROKE_MAIN}"/>',
        # the masthead: the house (or Facetta) speaks for the sheet — the
        # model never letters identity. Every record- or branding-derived
        # string is XML-escaped: 'Smith & Co' must letter, not break, the SVG.
        _text(sheet_w / 2, MARGIN + 8.5, escape(masthead), size=7.0,
              style=' letter-spacing="6"'),
    ]
    if name:
        parts.append(_text(sheet_w / 2, MARGIN + 13.8, escape(name), size=4.2,
                           style=' font-style="italic"'))
    parts += [
        _text(sheet_w / 2, MARGIN + (masthead_h - 3.5),
              escape(f"MANUFACTURING TECHNICAL DRAWING — {design_id} "
                     f"· v{version}"),
              size=3.0, color=FAINT, style=' letter-spacing="1.6"'),
        _line(MARGIN + 3, MARGIN + masthead_h - 1,
              sheet_w - MARGIN - 3, MARGIN + masthead_h - 1,
              w=STROKE_DIM, color=FAINT),
    ]
    # Facetta keeps its maker's mark even under a designer's house name
    if house:
        parts.append(_text(sheet_w - MARGIN - 3, MARGIN + 5.0,
                           "made with FACETTA", size=2.2, anchor="end",
                           color=FAINT, style=' letter-spacing="0.6"'))

    # the specification panel sits just above the identity footer; the drawing
    # fills everything between the masthead and the panel. The panel is sized
    # to the record — more stone groups, taller schedule — so it never clips.
    # A validated spec letters the record panel; with no spec, Grok's assist
    # estimates (when supplied) letter the ESTIMATED panel instead.
    assist = estimates if (spec is None and estimates) else None
    if spec is not None:
        panel_h = _panel_height(spec)
    elif assist:
        panel_h = _estimate_panel_height(assist)
    else:
        panel_h = 0.0
    ident_top = sheet_h - MARGIN - FOOTER_H
    panel_top = ident_top - panel_h
    if spec is not None:
        parts += _spec_panel(spec, MARGIN + 4, panel_top + 2,
                             sheet_w - MARGIN - 4, panel_h)
    elif assist:
        parts += _estimate_panel(assist, MARGIN + 4, panel_top + 2,
                                 sheet_w - MARGIN - 4)

    # the drawing itself, centered between masthead and the panel
    ax, ay = MARGIN + 2, MARGIN + masthead_h + 2
    aw = sheet_w - 2 * (MARGIN + 2)
    ah = panel_top - ay - 2
    media_type = _sniff_media_type(drawing_bytes)
    parts.append(
        f'<image x="{ax:.2f}" y="{ay:.2f}" width="{aw:.2f}" '
        f'height="{ah:.2f}" preserveAspectRatio="xMidYMid meet" '
        f'href="data:{media_type};base64,'
        f'{base64.b64encode(drawing_bytes).decode()}"/>')

    # footer band: identity left, signature right, disclaimer — every letter
    # from the record
    ty = sheet_h - MARGIN - 14
    parts.append(_line(MARGIN + 2, ty - 5, sheet_w - MARGIN - 2, ty - 5,
                       w=STROKE_DIM, color=FAINT))
    if spec is not None:
        stone = spec.stone
        stones = [stone] + spec.side_stones
        total_ct = sum(s.count * s.carat for s in stones)
        total_n = sum(s.count for s in stones)
        # the at-a-glance line: centre stone + the set totals. The metal is
        # NOT repeated here — it lives in Materials & Construction above.
        description = (f"{stone.carat:.2f} ct {stone.species.title()}  ·  "
                       f"{stone.cut.replace('_', ' ')} — "
                       f"{total_n} stones set  ·  {total_ct:.2f} ct total")
        # the description must stop short of the signature block — a long
        # metal line ran straight into the signed name on the live test
        avail = ((sheet_w - MARGIN - 46) if signature
                 else (sheet_w - MARGIN - 2)) - (MARGIN + 4) - 3
        max_chars = max(20, int(avail / 2.1))
        if len(description) > max_chars:
            description = description[: max_chars - 1].rstrip() + "…"
        parts += [
            _text(MARGIN + 4, ty, escape(description), size=3.0,
                  anchor="start", style=' letter-spacing="0.4"'),
            _text(MARGIN + 4, ty + 5,
                  escape(f"designer {spec.created_by} · "
                         f"{spec.created_at.date().isoformat()}"
                         + (f"   ·   {approval}" if approval else "")),
                  size=2.8, anchor="start", color=FAINT),
        ]
    elif assist:
        parts.append(_text(MARGIN + 4, ty,
                           "estimated from render — confirm before production",
                           size=3.0, anchor="start", color=FAINT))
    else:
        parts.append(_text(MARGIN + 4, ty, "unsaved drawing — pending record",
                           size=3.0, anchor="start", color=FAINT))

    # signature: a designer's hand, only when they've supplied a mark — the
    # same ruled-line gesture as the title block's sign-off
    if signature:
        sx = sheet_w - MARGIN - 46
        parts += [
            _line(sx, ty + 1.4, sx + 39, ty + 1.4, w=STROKE_DIM, color=FAINT),
            _text(sx, ty + 0.3, escape(signature), size=3.6, anchor="start",
                  style=' font-style="italic"'),
            _text(sx, ty + 4.3, "SIGNED", size=2.1, anchor="start",
                  color=FAINT, style=' letter-spacing="1.0"'),
        ]

    parts += [
        _text(sheet_w / 2, sheet_h - MARGIN - 3.4, escape(DISCLAIMER),
              size=2.6, color=FAINT),
        # outside the border, as on every Facetta sheet
        _text(sheet_w - MARGIN, sheet_h - 3.2,
              "CONFIDENTIAL — FACTORY PRODUCTION ONLY", size=2.8,
              anchor="end", color=FAINT, style=' letter-spacing="1.2"'),
        "</svg>",
    ]
    return "\n".join(parts) + "\n"

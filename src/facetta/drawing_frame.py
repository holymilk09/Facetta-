"""The official Facetta frame for the agent-drawn manufacturing technical
drawing — applied by CODE, from the record, never by the model.

The live test caught Grok signing a sheet 'ATELIER PRECIEUX | JOB REF
2024-E01 | DATE 2024-10-26' — pure fiction. So the division of labor is the
same one every Facetta artifact obeys: the model draws geometry (with the
templated instruction telling it to leave clean margins), and this module
letters the masthead, identity, description, designer, date, and signature
from the validated spec and the designer's branding. A letter the record
cannot vouch for never reaches the page.
"""

from __future__ import annotations

import base64
import io
from xml.sax.saxutils import escape

from facetta.render import _sniff_media_type
from facetta.spec import Spec
from facetta.svg_sheet import (
    FAINT, FONT, INK, PAPER, STROKE_DIM, STROKE_MAIN, Branding, _line,
    _metal_line, _text,
)

MARGIN = 8.0
MASTHEAD_H = 17.0   # the brand strip across the top, as on the overlay sheet
FOOTER_H = 22.0     # identity + signature + disclaimer band

# NB: keep this XML-safe (no raw &/<>) — it letters a <text> element. The
# wording matches specagent.DISCLAIMER.
DISCLAIMER = ("Manufacturing illustration — final dimensions after master "
              "model and sign-off.")


def frame_technical_drawing(drawing_bytes: bytes, spec: Spec | None = None,
                            branding: Branding | None = None) -> str:
    """Wrap the agent's drawing in the official Facetta template: A4 page
    (orientation follows the drawing), masthead, the drawing centered, and a
    footer band lettered entirely from the record.

    spec=None frames an unsaved drawing — identity shows the pending
    placeholders instead of inventing anything."""
    from PIL import Image

    img_w, img_h = Image.open(io.BytesIO(drawing_bytes)).size
    portrait = img_h > img_w
    sheet_w, sheet_h = (210.0, 297.0) if portrait else (297.0, 210.0)

    house = branding.house_line if branding else None
    signature = branding.signature_line if branding else None
    masthead = house or "FACETTA"
    design_id = spec.design_id if spec is not None else "dsn_pending"
    version = spec.version if spec is not None else 1

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
        _text(sheet_w / 2, MARGIN + 13.5,
              escape(f"MANUFACTURING TECHNICAL DRAWING — {design_id} "
                     f"· v{version}"),
              size=3.0, color=FAINT, style=' letter-spacing="1.6"'),
        _line(MARGIN + 3, MARGIN + MASTHEAD_H - 1,
              sheet_w - MARGIN - 3, MARGIN + MASTHEAD_H - 1,
              w=STROKE_DIM, color=FAINT),
    ]
    # Facetta keeps its maker's mark even under a designer's house name
    if house:
        parts.append(_text(sheet_w - MARGIN - 3, MARGIN + 5.0,
                           "made with FACETTA", size=2.2, anchor="end",
                           color=FAINT, style=' letter-spacing="0.6"'))

    # the drawing itself, centered in everything between masthead and footer
    ax, ay = MARGIN + 2, MARGIN + MASTHEAD_H + 2
    aw = sheet_w - 2 * (MARGIN + 2)
    ah = sheet_h - ay - MARGIN - FOOTER_H
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
        description = (f"{stone.carat:.2f} ct {stone.species.title()}  ·  "
                       f"{stone.cut.replace('_', ' ')} — "
                       f"{_metal_line(spec.metal)}")
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
                         f"{spec.created_at.date().isoformat()}"),
                  size=2.8, anchor="start", color=FAINT),
        ]
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

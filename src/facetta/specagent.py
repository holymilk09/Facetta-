"""Jewelry Manufacturing Spec Agent: render in, factory sheet out — agent only.

The founder's rule for the user-facing spec sheet: the AGENT draws it. Grok
vision inspects the designer's render, a mode/region router picks the right
instruction block, and a controlled image-to-image edit turns the render into
black-line orthographic documentation. Our deterministic geometry code never
touches this artifact — the parametric CAD/DXF sheet is a separate, explicit
handoff, and this module imports nothing that draws.

Math is assistance, not authorship: when a VALIDATED spec exists, its numbers
are lifted out as plain text and injected into the prompt as
designer-authoritative dimensions. Everything the record does not state is
marked TBD on the sheet — the agent never invents a millimetre as final.

The prompt pack (docs/spec_agent_prompt_pack.md) is encoded here as DATA —
modes, regions, glossary, suffixes — so extending a mode means adding an
entry, not another f-string.
"""

from __future__ import annotations

import base64
import json
import os

from pydantic import BaseModel, ConfigDict, ValidationError

from facetta.render import (
    RenderUnavailable, _provider_key, _sniff_media_type, edit_image,
    generate_image,
)
from facetta.spec import Spec

DISCLAIMER = ("Manufacturing illustration—final dimensions after master "
              "model and sign-off.")

# The founder's terminology directive: image models read "spec sheet" as a
# form/table — the phrase that reliably lands is the primary one below. It
# opens every image instruction; the synonyms line teaches system prompts
# what the artifact is (and is not).
TASK_LINE = (
    "Task: Convert the render into a jewelry manufacturing technical drawing "
    "(line art, orthographic plan/front/side, mm dimensions, material and "
    "stone callouts) for factory handoff.")

SYNONYMS_LINE = (
    "Also called: factory drawing, technical file, production drawing — not "
    "a photoreal render, not a spreadsheet-only spec.")

# Product naming — the app's single source for how this capability is labeled.
TASK_MODE = "MANUFACTURING_TECHNICAL_DRAWING"
UI_LABELS = {
    "button": "Create manufacturing drawing",
    "subtitle": ("True-scale views, dimensions, materials & stones for "
                 "production"),
    "synonyms": SYNONYMS_LINE,
}

MASTER_SYSTEM = """\
You are the Jewelry Manufacturing Technical Drawing Agent for a
designer-facing app. You convert photorealistic jewelry renders into
factory-ready jewelry manufacturing technical drawings (line art,
orthographic views, dimensions, component labels) using vision-first
analysis and controlled image generation — not parametric guesswork.

""" + TASK_LINE + "\n" + SYNONYMS_LINE + """

Mission: maximize manufacturing usefulness and visual fidelity to the
designer's render (~90%+ layout accuracy). Minimize invented dimensions. Use
professional fine-jewelry terminology.

Workflow (non-negotiable): 1) inspect every reference — piece type, views
shown, settings, stone shapes, symmetry, occluded areas; 2) classify mode and
region from image + designer notes; 3) load the mode-specific instruction
block; 4) generate the sheet via image edit from the render; 5) one
legibility repair pass if text or dimensions are blurry; 6) deliver the sheet
plus a structured manufacturing summary with an explicit TBD/confirm list.

Never: fall back to code-only geometry for this user-facing step unless the
user explicitly requests CAD export; output photorealistic re-renders when a
manufacturing technical drawing was asked for; present guessed stone weights or finger sizes as
final; "improve" or simplify the designer's proportions.

Sheet layout (default composite): title block (job/style ref — TBD ok,
description, metal/alloy/color, finish codes, stone summary table, scale/size
basis, revision/date/"Designer sign-off required"); views as applicable —
PLAN | FRONT | SIDE | SECTION A–A, detail callouts at 2x ("DETAIL B"), L/R
pair notation for earrings. Drawing style: black line on white, uniform
stroke, dashed = hidden, centerlines for stones, stones as faceted outlines
(no color fill), mm-primary dimension leaders (region adds secondary units).

Dimension policy: designer-supplied dimensions are authoritative on the
sheet. Proportional-from-render gets the footnote "nominal from render —
verify on master model". Unknown gets TBD with a leader line. Tolerances when
the mode requires: casting shrink "per alloy + caster"; stone seat
+0.00/−0.02 mm typical round; comfort-fit note euro vs flat inner.

Edge cases: occluded gallery → section view + "confirm undergallery";
multiple metals → label zones or "two-tone TBD"; engraving → "artwork vector
TBD", blank shank; rough render → ask for a cleaner render, never hallucinate
prongs; house styles → generic labels, no third-party logos. CAD handoff is a
separate explicit action — the sheet is an illustration."""

# ---------------------------------------------------------------------------
# Section 1 — the three-capability agent contract
# (docs/jewelry_agent_system_prompt.md). AGENT_SYSTEM is the app's TOP-LEVEL
# system message; MASTER_SYSTEM above remains the MODE B drawing pipeline's.
# ---------------------------------------------------------------------------

CAPABILITIES = ("JEWELRY_RENDER", "MANUFACTURING_TECHNICAL_DRAWING",
                "LOCALIZED_EDIT", "GLOBAL_RESTYLE")

AGENT_SYSTEM = """\
You are the Jewelry Design & Manufacturing Agent embedded in a professional
jewelry design application. You work only in jewelry and fine jewelry (rings,
bands, engagement and wedding jewelry, pendants, necklaces, earrings,
bracelets, brooches, cuffs, high jewelry, jewelry watches). You are not a
general image editor, fashion tech-pack tool, or mechanical CAD system.

You operate in three distinct capabilities. Identify which one the user (or
the application mode field) is requesting and never mix behaviors — no
photoreal marketing renders when a factory technical drawing was asked for,
no dimensioned line art when only a beauty render was asked for.

MODE A — JEWELRY_RENDER: photorealistic product visualization for
presentation and design approval, not factory line art. Photoreal jewelry
image on a neutral studio background unless the user requests context. Use
correct jewelry vocabulary (shank, gallery, prong, bezel, pavé, melee,
bail); no invented trademarks or copies of protected house designs unless
the user owns them; no factory dimension strings on the image unless
explicitly requested; when sizes are not given, visualize plausible
proportions but never present them as confirmed manufacturing specs.

MODE B — MANUFACTURING_TECHNICAL_DRAWING: convert an approved reference
(usually a photoreal render or uploaded sketch) into a jewelry manufacturing
technical drawing for factory handoff — black line art on white,
orthographic views per piece type, dimension lines in millimeters, labels,
a stone schedule table, and a short manufacturing summary in chat. Always
inspect the reference first — never generate blind. Dimension honesty:
final numbers only when designer-supplied or labeled "nominal from
reference—verify on master model", else TBD with leader lines. Preserve the
proportions of the reference silhouette — never "improve" the design. No
photorealism on the sheet.

MODE C — LOCALIZED_EDIT: the designer highlights a region on an existing
image (render or, with care, technical drawing) and gives an instruction.
Apply only the requested change inside that region; freeze everything
outside the highlight. Required: region_description and change_instruction
(mask strongly recommended — white = edit, black = preserve). If no
highlight or mask was provided, ask the user to select the area — do not
perform a full-image redesign unless they explicitly ask for a global
restyle. Every edit prompt carries the preservation contract: PRESERVE /
EDIT SCOPE / FORBIDDEN. Obvious drift outside the region gets ONE retry
with stronger preserve language; still failing, ask the user to tighten
the mask or split the edit.

DEFAULT JOURNEY: 1) designer describes a piece → JEWELRY_RENDER (optional);
2) designer refines → LOCALIZED_EDIT on the latest render (repeat);
3) designer approves → MANUFACTURING_TECHNICAL_DRAWING from the latest
render asset; 4) minor fixes → LOCALIZED_EDIT on the render or one drawing
legibility pass — never the legacy math spec backend.

ITERATION IS THE PRIMARY LOOP: designers always adjust. The journey is
JEWELRY_RENDER → many LOCALIZED_EDIT → pin → MANUFACTURING_TECHNICAL_DRAWING
on demand. A technical drawing is NOT the natural next step after every edit;
regenerate it only on an explicit "approve for factory" action, from the
PINNED version, not the latest.

MODE INFERENCE when the mode is ambiguous: "render / realistic / show me /
visualization" → JEWELRY_RENDER; "technical drawing / factory /
manufacturing / dimensions / orthographic / production" →
MANUFACTURING_TECHNICAL_DRAWING; "only this part / highlight / selected
area / don't change the rest" → LOCALIZED_EDIT; a whole-piece change —
"everywhere / the whole shank / overall style / make it more X" →
GLOBAL_RESTYLE, a reference-locked restyle with no region freeze (warn the
designer and lean on parent/child compare and revert), NOT a localized edit
forced without a mask.

DOMAIN GUARDRAILS: 1) jewelry-only — politely decline non-jewelry requests
and ask for a jewelry-focused one; 2) standard manufacturing terminology on
drawings and in prompts — no vague words when a standard term exists;
3) no false precision — never present guessed carat weights, exact melee
counts, or finger sizes as final factory data; 4) compliance — no
non-consensual sexualized content, no minors; respect moderation and never
evade filters by paraphrasing; 5) real people and branded characters follow
the platform's reference workflows — this agent does not bypass them;
6) every manufacturing summary carries the disclaimer: "Manufacturing
illustration for discussion; final dimensions and tolerances require
designer sign-off and verification on master model / gauge."

ERROR HANDLING: moderated, rate-limited, or provider unavailable — stop,
don't evade, inform briefly. Other errors: at most one retry for generation
or legibility. LOCALIZED_EDIT drift: one preserve-retry, then ask for a
tighter mask or a smaller scope.

CHAT RESPONSE FORMAT: after JEWELRY_RENDER — a brief design read; invite
localized edits or a technical drawing. After
MANUFACTURING_TECHNICAL_DRAWING — the sheet plus Confirmed from reference /
Designer must confirm / Factory notes bullets and the disclaimer. After
LOCALIZED_EDIT — confirm what changed and what was frozen; suggest comparing
to the parent; offer revert via the app.

YOU MUST NOT: use the legacy parametric/math spec backend for modes B or C;
replace a technical-drawing request with a photoreal render; replace a
render request with line art unless asked; guess the highlight region when
none was provided — ask; invent exact factory numbers without designer
input or nominal labeling."""

# Section 1's mode-inference rules as keyword heuristics — checked in
# priority order. GLOBAL_RESTYLE outranks LOCALIZED_EDIT: "widen the whole
# shank" or "make it more deco everywhere" is a scoped-to-everything change,
# and forcing it through the localized path without a mask would either block
# the designer or silently guess a region. Edit signals still win over
# drawing signals, drawing over render (a message that says "highlight" and
# "render" is an edit OF a render, not a new render).
_CAPABILITY_SIGNALS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("GLOBAL_RESTYLE",
     ("everywhere", "whole piece", "whole shank", "entire", "overall style",
      "all over", "restyle", "globally", "the whole")),
    ("LOCALIZED_EDIT",
     ("only this part", "highlight", "selected area", "don't change the rest",
      "this area", "just the")),
    ("MANUFACTURING_TECHNICAL_DRAWING",
     ("technical drawing", "factory", "manufacturing", "dimension",
      "orthographic", "production", "spec sheet")),
    ("JEWELRY_RENDER",
     ("render", "realistic", "show me", "visualization", "photo")),
)


def infer_capability(text: str) -> str:
    """Section 1's mode-inference rules for the app's router: global-restyle
    signals first (a whole-piece change must not be forced through the
    localized path), then localized-edit, then technical-drawing, then
    render; the default journey starts at JEWELRY_RENDER. Case-insensitive."""
    lowered = text.lower()
    for capability, signals in _CAPABILITY_SIGNALS:
        if any(signal in lowered for signal in signals):
            return capability
    return "JEWELRY_RENDER"


# G0 — the universal suffix, the tail of every image-edit instruction.
G0_SUFFIX = (
    "Single composite jewelry manufacturing technical drawing. Black "
    "technical line art on pure white. Orthographic views with view labels "
    "PLAN, FRONT, SIDE. Dimension lines with arrowheads. CAD/jewelry atelier "
    "documentation style. Gemstones as faceted outlines only, no color. No "
    "photorealism, no shadows, no jewelry box, no model. Preserve exact "
    "design proportions and silhouette from reference. Legible sans-serif "
    "labels. Title block with METAL, JOB REF, REV A.")

# The CLEAN factory-drawing directive (templated mode, the app's factory-sheet
# path): Grok draws ONLY the actual piece — clean views and thin dimension
# INDICATOR lines it renders accurately — and writes NO text at all. Every
# number, label, and identity is lettered by the platform's code panel beside
# the drawing (facetta.drawing_frame). Grok can't reliably letter precise text
# (it produced 'Pullish', 'G6.91'), and inventing labels gave phantom 'PLAN'
# and 'SECTION A-A' with no cut line — so it letters nothing, ever.
CLEAN_DRAW_DIRECTIVE = (
    "Redraw the SAME piece from the reference as a clean jewelry manufacturing "
    "technical illustration — precise graphite/line technical style on pure "
    "white paper. Orthographic views: {views}. Keep the design, proportions, "
    "stones, setting, metal and silhouette EXACTLY as the reference — this is "
    "the designer's actual piece, do not restyle it. You MAY draw clean, thin "
    "dimension indicator lines between features (heights between levels, widths) "
    "as visual guides.")

CLEAN_G0 = (
    "CRITICAL — write NO text of ANY kind on the drawing: no numbers, no "
    "dimension values or measurements, no view-name labels (no 'PLAN', 'TOP', "
    "'FRONT', 'SIDE', 'SECTION', 'A-A'), no 'TBD', no title block, no brand, "
    "designer, or date, no callout words, no legend, no letters. The platform's "
    "template letters every number and label from the record beside the "
    "drawing. Draw ONLY the clean views and thin indicator lines. Gemstones as "
    "clean faceted outlines. No photorealism, no shadows, no jewelry box, no "
    "model, no background, no watermark.")

# --- colored, multi-angle clean redraw of a hand plate -----------------------
#
# The domain expert's requirement for the redraw: it must carry COLOUR matching
# the piece's real materials (a factory has to see blue enamel vs lapis,
# tsavorite vs emerald), and come in MULTIPLE ANGLES — factories build from
# more than one view. Grok DRAWS every view (image-to-image, design-locked);
# code still letters all text on the sheet, so nothing garbles like 'penalr'.

PLATE_VIEWS = ("front", "three-quarter", "side")

_PLATE_VIEW_PHRASE = {
    "front": "a straight-on orthographic FRONT view",
    "three-quarter": "a three-quarter view, rotated about 35° to show depth",
    "side": "a side profile view",
    "back": "a back view",
    "top": "a top-down plan view",
}


def _material_summary(read: dict) -> str:
    """A short colour/materials phrase for the redraw prompt, from the plate
    read — the stone types (which carry the colour words) and the metal."""
    parts = []
    for s in read.get("stones") or []:
        t = str(s.get("type", "")).strip()
        if not t:
            continue
        qty = int(s.get("qty") or 1)
        parts.append(f"{qty}× {t}" if qty > 1 else t)
    metal = str(read.get("metal") or "").strip()
    if metal and metal.upper() != "TBD":
        parts.append(f"{metal} metal")
    return "; ".join(parts) if parts else "as coloured in the reference"


# two stones cannot occupy the same space — a merged/overlapping stone is a
# physically impossible piece a factory cannot make. This clause rides in both
# the line-art and the colorize prompts.
_PHYSICAL_SEPARATION = (
    "PHYSICAL SEPARATION (a real factory piece): every stone is a SEPARATE "
    "solid part — stones must NOT overlap, merge, fuse, or cross into each "
    "other. Each stone keeps its own complete outline with metal or clear "
    "space between it and its neighbours. Wings and side stones sit BESIDE the "
    "centre stone and attach to the metal frame; they never cross over, sink "
    "into, or blend with the centre stone. No stone floats inside another.")


def _assembly_lock(read: dict) -> str:
    """The spatial-assembly clause: without it Grok flattens a complex piece
    into a row of loose stones, or merges overlapping stones into one. Built
    from the plate read's jewelry_type and the extracted assembly sentence, so
    the redraw keeps what connects to what and keeps every stone separate."""
    jtype = (read.get("jewelry_type") or "piece").replace("_", " ")
    assembly = read.get("assembly")
    clause = (f"This is ONE assembled {jtype}"
              + (f": {assembly}." if assembly else "."))
    return (clause + " Keep this EXACT assembly and spatial arrangement — what "
            "connects to what, top to bottom. Do NOT lay the stones out in a "
            "row or separate them into loose components; draw the assembled "
            "piece as designed. COUNT LOCK: reproduce the EXACT number of every "
            "element in the reference — the same number of wings, petals, "
            "stones, discs and prongs. Do NOT add, duplicate, multiply, or "
            "invent any element; if the reference has two wings, draw exactly "
            "two. " + _PHYSICAL_SEPARATION)


def compile_plate_redraw(read: dict, view: str, *, from_hero: bool,
                         colored: bool = True) -> str:
    """A clean-technical redraw instruction for one view. colored=True fills
    the piece with colour matching the materials; colored=False draws pure
    BLACK LINE ART (the high-fidelity first stage — the designer confirms the
    geometry before any colour). from_hero locks to an already-redrawn hero
    (viewpoint change only). Grok draws; CLEAN_G0 forbids all text."""
    phrase = _PLATE_VIEW_PHRASE.get(view, view)
    if from_hero:
        lead = ("New camera angle of the SAME redrawn piece: show it from "
                f"{phrase}.")
    else:
        lead = ("Redraw the SAME jewelry piece from the reference as a clean "
                f"jewelry manufacturing technical illustration — {phrase}.")
    if colored:
        style = ("Crisp clean line work with FLAT COLOUR matching the piece's "
                 f"real materials: {_material_summary(read)}. Colour it like a "
                 "jeweller's coloured technical rendering — accurate hues, "
                 "subtle shading only, on a plain white background.")
    else:
        style = ("Draw as clean BLACK LINE ART only — crisp outlines on a pure "
                 "white background, NO colour and NO shaded fills, like a "
                 "jeweller's technical line drawing. Accurate proportions and "
                 "silhouette.")
    return "\n".join([
        lead,
        _assembly_lock(read),
        style,
        "IDENTITY LOCK: keep the exact design, stones, setting, metal and "
        "proportions of the reference — this is the designer's actual piece; "
        "do NOT restyle, redesign, or add or remove any element. Only the "
        "viewpoint differs.",
        CLEAN_G0,
    ])


def compile_colorize(materials: str) -> str:
    """Colour a CONFIRMED line drawing from the designer's specs. The geometry
    is locked — Grok may only fill colour inside the existing outlines, so it
    cannot add wings or multiply elements. Colours come from the designer's
    confirmed materials, not a visual guess."""
    return "\n".join([
        "Add FLAT COLOUR to this jewelry technical LINE DRAWING.",
        "CRITICAL — the line drawing's geometry is FINAL and LOCKED: do NOT "
        "change, move, add, remove, or duplicate ANY line, outline, shape, "
        "stone, wing, disc, or element. Keep every element exactly where it is "
        "and exactly how many there are. Only FILL colour inside the existing "
        "outlines. Keep each stone's outline distinct — do NOT let colour bleed "
        "across two stones so they read as merged; every stone stays a separate "
        "shape.",
        f"Colour the elements to match these confirmed materials: {materials}. "
        "Flat jeweller's colour, accurate hues, subtle shading only; keep the "
        "plain white background. Write NO text of any kind.",
    ])


def colorize_lineart(lineart_bytes: bytes, materials: str, *,
                     model: str = "grok_direct",
                     variant: int = 0) -> tuple[bytes, bool]:
    """Stage 2: colour a designer-CONFIRMED line drawing from the confirmed
    materials. Colouring locked geometry, so the piece cannot drift. Runs on
    Grok (grok_direct). Returns (image_bytes, was_cached)."""
    return edit_image(lineart_bytes, compile_colorize(materials), model,
                      variant=variant)


_NO_MULTIPLY_RETRY = (
    "The previous attempt DRIFTED the design — it added, duplicated, or "
    "multiplied elements (extra wings, petals, or stones) that are NOT in the "
    "reference. Redraw with the EXACT SAME elements and the EXACT SAME COUNT of "
    "every part as the reference — do not add or invent anything.")


def redraw_plate_views(plate_bytes: bytes, read: dict, *, colored: bool,
                       views=PLATE_VIEWS, model: str = "grok_direct",
                       variant: int = 0, max_attempts: int = 3) -> list[dict]:
    """Clean-technical redraw of a hand plate in MULTIPLE ANGLES, each softly
    checked for design drift. colored toggles colour vs pure line art. The
    first view is redrawn from the designer's plate (the hero); every other
    angle is derived from the hero, so all views are the same piece. A view
    the vision check flags as MAJOR drift (added/changed elements) is re-rolled
    with stronger no-multiply language; the flag rides back as `ok`.

    The vision check is ADVISORY — it misses count errors (line-art vs line-art
    reads as 'same design'), so the reliable gate is the DESIGNER confirming
    the line art. Returns [{"view", "image", "cached", "ok", "differences"}]."""
    out: list[dict] = []
    hero = None
    for view in views:
        reference = plate_bytes if hero is None else hero
        from_hero = hero is not None
        best = None
        for attempt in range(max_attempts):
            instr = compile_plate_redraw(read, view, from_hero=from_hero,
                                         colored=colored)
            if attempt > 0:
                instr += "\n" + _NO_MULTIPLY_RETRY + f" (attempt {attempt + 1})"
            img, cached = edit_image(reference, instr, model,
                                     variant=variant + attempt)
            cons = check_design_consistency(reference, img)
            ok = cons.get("severity") != "major"
            cand = {"view": view, "image": img, "cached": cached, "ok": ok,
                    "differences": list(cons.get("differences", []))}
            best = cand if ok else (best or cand)
            if ok:
                break
        out.append(best)
        if hero is None:
            hero = best["image"]
    return out


def redraw_plate_lineart(plate_bytes: bytes, read: dict, **kwargs) -> list[dict]:
    """Stage 1 (high fidelity): pure BLACK LINE ART in multiple angles for the
    designer to CONFIRM before any colour. Same shape as redraw_plate_views."""
    return redraw_plate_views(plate_bytes, read, colored=False, **kwargs)


def redraw_plate_colored(plate_bytes: bytes, read: dict, **kwargs) -> list[dict]:
    """One-shot COLOURED redraw in multiple angles (the quick path). The
    higher-fidelity route is redraw_plate_lineart → confirm → colorize_lineart."""
    return redraw_plate_views(plate_bytes, read, colored=True, **kwargs)


def compose_views_strip(images: list[bytes], *, gap: int = 48,
                        bg=(255, 255, 255)) -> bytes:
    """Lay the redraw views side by side on one white canvas — the multi-angle
    row a factory reads (front · three-quarter · side). Each view is scaled to
    a common height. Returns PNG bytes; the frame letters the panel beneath."""
    import io

    from PIL import Image

    ims = [Image.open(io.BytesIO(b)).convert("RGB") for b in images]
    if not ims:
        raise ValueError("no views to compose")
    h = max(i.height for i in ims)
    scaled = [i.resize((max(1, round(i.width * h / i.height)), h)) for i in ims]
    w = sum(i.width for i in scaled) + gap * (len(scaled) + 1)
    canvas = Image.new("RGB", (w, h + 2 * gap), bg)
    x = gap
    for i in scaled:
        canvas.paste(i, (x, gap))
        x += i.width + gap
    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    return buf.getvalue()


# G6 — the one-shot legibility repair pass. The body only: the tail (G0,
# templated or not, plus the honesty rule) is appended at call time by
# _legibility_instruction, so the repair pass obeys the same title-block and
# honesty rules as the first edit. G6_LEGIBILITY (the untemplated compiled
# form) is defined below, after the rules it depends on.
_G6_BODY = (
    "Identical layout and proportions. Redraw all text, numbers, dimension "
    "arrows, and view labels in sharp black sans-serif. Increase text "
    "legibility for print at A4. No design changes. ")

# Section C + G — one entry per mode: the mandatory views, the callouts the
# factory needs, and the image-edit prompt body (G0 is appended at compile
# time, never stored). G1–G5 are the pack's wording; the rest are composed
# from their Section C views and callouts in the same voice.
MODES: dict[str, dict] = {
    "RING_ENGAGEMENT": {
        "label": "Engagement ring",
        "views": ["plan (head+shank)", "front", "side",
                  "section A–A through center-stone axis"],
        "callouts": ["center Ø mm", "halo OD", "prong count & style",
                     "gallery height", "shank width (narrow point)",
                     "shank thickness", "rise",
                     "finger bore → US size + inner Ø mm",
                     "stone table: CENTER / HALO / SHANK ACCENTS"],
        "prompt": (
            "Transform the engagement ring from the reference into a jewelry "
            "manufacturing technical drawing. Views: plan showing head and shank top, front "
            "elevation, side profile, section A–A through center stone. "
            "Dimension callouts in mm: center stone diameter TBD unless "
            "known, halo outer diameter if present, prong count visible, "
            "gallery height, shank width at narrowest, shank thickness, head "
            "height above shank. Label cathedral, prongs, gallery, shank. "
            "Ring size line: US ___ / inner Ø ___ mm."),
    },
    "RING_BAND_PAVE": {
        "label": "Pavé band",
        "views": ["plan (unrolled strip + round plan)", "front", "side"],
        "callouts": ["shank width/thickness", "pavé row count", "melee size",
                     "min metal between stones", "edge type",
                     "stone count TBD unless countable"],
        "prompt": (
            "Pavé band manufacturing technical drawing from reference. Views: plan with stone row "
            "schematic, front, side. Callouts: band width, thickness, "
            "estimated melee size mm TBD, number of pave rows, edge profile. "
            "Note on sheet: melee spacing nominal—confirm at setting."),
    },
    "RING_SIGNET": {
        "label": "Signet ring",
        "views": ["plan (face)", "front", "side"],
        "callouts": ["face L×W/Ø", "face thickness", "shoulder width",
                     "shank taper", "engraving depth TBD post-artwork"],
        "prompt": (
            "Signet ring manufacturing technical drawing from reference. Views: plan of the face, "
            "front elevation, side profile. Dimension callouts in mm: face "
            "length and width or diameter, face thickness, shoulder width, "
            "shank taper. Engraving depth: TBD post-artwork."),
    },
    "RING_STACKABLE": {
        "label": "Stackable bands",
        "views": ["plan per band", "side per band"],
        "callouts": ["band width", "band thickness", "profile",
                     "stacked gap TBD", "qty in set TBD from single render"],
        "prompt": (
            "Stackable band set manufacturing technical drawing from reference. Views: plan and "
            "side per band. Dimension callouts in mm: band width, band "
            "thickness, profile shape. Stacked gap TBD. Note on sheet: qty "
            "in set TBD."),
    },
    "PENDANT": {
        "label": "Pendant",
        "views": ["plan", "front", "side", "bail detail (section)"],
        "callouts": ["overall H×W", "bail wire OD", "bail ID (chain pass)",
                     "thickness", "stone positions", "bail type"],
        "prompt": (
            "Pendant manufacturing technical drawing. Views: plan, front, side, bail detail "
            "inset. Dimensions: overall height and width mm, metal "
            "thickness, bail inner diameter for chain. Label bail and main "
            "stone locations."),
    },
    "NECKLACE": {
        "label": "Necklace",
        "views": ["compressed full-length elevation", "motif front detail",
                  "clasp detail", "link section"],
        "callouts": ["finished length cm/in", "link L×W×wire gauge",
                     "clasp type", "safety chain Y/N"],
        "prompt": (
            "Necklace manufacturing technical drawing from reference. Views: compressed "
            "full-length elevation, motif front detail, clasp detail, link "
            "section. Dimension callouts: finished length in cm and inches, "
            "link length, width and wire gauge, clasp type, safety chain "
            "yes/no. If only a pendant is rendered, note: chain schematic "
            "not shown—TBD."),
    },
    "EARRINGS_STUD": {
        "label": "Stud earrings",
        "views": ["front", "side (post)", "optional back"],
        "callouts": ["motif W×H", "projection", "post Ø & length",
                     "pair L/R mirror"],
        "prompt": (
            "Pair of stud earrings manufacturing technical drawing L/R. Views: front, side "
            "showing the post, optional back detail. Dimension callouts in "
            "mm: motif width and height, projection from the ear, post "
            "diameter and length. Note: pair mirrored left/right."),
    },
    "EARRINGS_DROP": {
        "label": "Drop earrings",
        "views": ["front pair", "side profile (drop length)",
                  "wire/hook detail"],
        "callouts": ["overall drop length", "hinge/jump-ring Ø",
                     "component stack heights",
                     "articulation TBD when unclear"],
        "prompt": (
            "Pair of drop earrings manufacturing technical drawing L/R. Views: front pair, side "
            "profile showing drop length. Dimension total drop length mm, "
            "width at widest, hinge and finding details."),
    },
    "BRACELET": {
        "label": "Bracelet",
        "views": ["plan (flattened)", "front", "side link profile",
                  "clasp open/closed"],
        "callouts": ["interior length cm", "link dims", "clasp width",
                     "safety latch"],
        "prompt": (
            "Bracelet manufacturing technical drawing from reference. Views: flattened plan, "
            "front elevation, side link profile, clasp shown open and "
            "closed. Dimension callouts: interior length in cm, link "
            "dimensions, clasp width, safety latch."),
    },
    "BROOCH": {
        "label": "Brooch",
        "views": ["plan", "front", "side (pin hinge)",
                  "pin mechanism detail"],
        "callouts": ["W×H", "thickness", "hinge/catch position",
                     "pin length"],
        "prompt": (
            "Brooch manufacturing technical drawing from reference. Views: plan, front, side "
            "showing the pin hinge, pin mechanism detail. Dimension callouts "
            "in mm: overall width and height, thickness, hinge and catch "
            "positions, pin length."),
    },
    "HIGH_JEWELRY": {
        "label": "High jewelry",
        "views": ["plan", "front", "side", "≥1 section",
                  "2 detail callouts"],
        "callouts": ["stone schedule table (TBD unless specified)",
                     "complex undergallery — rubber mold / CNC path TBD "
                     "with master jeweler",
                     "never collapse asymmetry; label L/R asym"],
        "prompt": (
            "High jewelry manufacturing technical drawing with large stone schedule table "
            "(columns: ITEM, QTY, SHAPE, SIZE mm, SETTING, MATERIAL, TBD). "
            "Views: plan, front, side, section, two detail callouts for "
            "gallery and cluster. Preserve asymmetry."),
    },
    "WATCH_JEWELRY": {
        "label": "Jewelry watch",
        "views": ["dial plan", "front", "side (case)", "lug width"],
        "callouts": ["case Ø/L×W", "lug width", "crown position",
                     "bezel height", "bezel stone count"],
        "prompt": (
            "Jewelry watch manufacturing technical drawing from reference. Views: dial plan, "
            "front, side of the case, lug width detail. Dimension callouts "
            "in mm: case diameter or length and width, lug width, crown "
            "position, bezel height, bezel stone count."),
    },
    "GENERIC": {
        "label": "Generic piece",
        "views": ["plan", "front", "side"],
        "callouts": ["label visible settings", "TBD elsewhere"],
        "prompt": (
            "Jewelry manufacturing technical drawing from reference. Views: plan, front, side "
            "minimum. Label every visible setting; mark all other "
            "dimensions TBD."),
    },
}

# Section D — region unit rules, as prompt lines.
REGIONS: dict[str, str] = {
    "US": ("Units: mm mandatory for stones; inches optional on shank lines; "
           "ring size as US half-size with inner Ø mm secondary; footnote "
           "'Dimensions in mm; inches in parentheses where shown'; dwt "
           "optional."),
    "EU": ("Units: mm only; ring size as ISO inner Ø mm (optional EU "
           "circumference); grams in the title block; assay stamps (750, "
           "585) on the metal line."),
    "DUAL": ("Units: mm primary everywhere; US ring size + inner Ø mm in "
             "the title block; bracelet/necklace lengths in cm and in."),
}

# Section E — the on-sheet label vocabulary, exposed for the app/UI.
GLOSSARY: dict[str, str] = {
    "shank": "the band of a ring (also: band, hoop)",
    "head": "the top structure that holds the center stone (also: crown)",
    "gallery": "the open framework under the head (also: undergallery, basket)",
    "prong": "a claw of metal holding a stone (also: claw, shared prong)",
    "bezel": "a continuous metal rim around a stone (also: semi-bezel, tube)",
    "pave": "a field of small stones set close together (also: micro-pavé, melee)",
    "bright cut": "polished engraved borders around bead-set stones (also: azured)",
    "cathedral": "shoulders that rise to meet the head like arches",
    "milgrain": "a beaded decorative edge",
    "knife edge": "a band profile that peaks to a fine ridge",
    "comfort fit": "a rounded inner band profile (also: euro shank)",
    "bail": "the loop a pendant hangs from (also: enhancer)",
    "friction back": "a push-on earring back (alternative: screw back)",
    "rhodium flash": "a thin rhodium plating over white gold",
    "HP": "finish code: high polish",
    "SAT": "finish code: satin",
    "BR": "finish code: brushed",
    "HG": "finish code: hand engraved",
    "MG": "finish code: milgrain",
    "RH": "finish code: rhodium",
}

MODE_FOR_TEMPLATE: dict[str, str] = {
    "solitaire_prong": "RING_ENGAGEMENT",
    "halo_prong": "RING_ENGAGEMENT",
    "deco_drop_earring": "EARRINGS_DROP",
    "cluster_pendant": "PENDANT",
    "leaf_spray_brooch": "BROOCH",
    "love_bangle": "BRACELET",
    "cuff": "BRACELET",
    "link_bracelet": "BRACELET",
    "loose_stone": "GENERIC",
}

_TBD_POLICY = ("Any dimension not listed above: mark TBD with a leader "
               "line, or 'nominal from render—verify on master model'.")

# The live test caught Grok signing sheets as 'ATELIER PRECIEUX | JOB REF
# 2024-E01 | DATE 2024-10-26' — pure fiction. Both instruction modes close
# with this rule.
HONESTY_RULE = ("Never invent designer names, job references, or dates — "
                "write TBD where unknown.")

def _legibility_instruction(*, templated: bool = False) -> str:
    """The G6 repair pass. In templated mode the drawing carries NO text (the
    code panel letters everything), so the pass only reinforces a clean,
    text-free illustration — never redraw or add labels. Legacy mode keeps the
    text-legibility repair."""
    if templated:
        return ("Identical layout, proportions, and design — no changes. Keep "
                "the drawing perfectly clean. " + CLEAN_G0 + " " + HONESTY_RULE)
    return _G6_BODY + G0_SUFFIX + " " + HONESTY_RULE


# The untemplated compiled form, kept as the public constant.
G6_LEGIBILITY = _legibility_instruction()

# Section B — the router.
_ROUTER_SYSTEM = (
    "You classify one jewelry render for the Jewelry Manufacturing "
    "Technical Drawing Agent. Given the designer's notes and the image, "
    "output JSON only:\n"
    '{"mode": "...", "region": "US|EU|DUAL", "confidence": 0-1, '
    '"occlusion": "low|med|high"}\n'
    "Valid modes: " + ", ".join(MODES) + ".\n"
    "Valid regions: US, EU, DUAL (DUAL unless the notes say otherwise).\n"
    "Rules: halo + center stone → RING_ENGAGEMENT; continuous melee band → "
    "RING_BAND_PAVE; drop with movement → EARRINGS_DROP; 3+ distinct stone "
    "zones + complex gallery → HIGH_JEWELRY. Anything else you cannot place "
    "→ GENERIC.")

# Section I / Section 5 — the manufacturing summary the app shows next to
# the sheet. `mode` is the CAPABILITY (always MANUFACTURING_TECHNICAL_DRAWING
# here); `piece_type` is the MODES table key the drawing was compiled from.
_INSPECT_SYSTEM = (
    MASTER_SYSTEM + "\n\n"
    "Inspect this render and return the manufacturing summary as JSON only, "
    "exactly this shape:\n"
    f'{{"mode": "{TASK_MODE}", "piece_type": "...", "region": "...",\n'
    ' "confirmed_from_reference": ["what the reference establishes"],\n'
    ' "designer_must_confirm": ["every guessed or occluded value"],\n'
    ' "factory_notes": ["setter/caster instructions"],\n'
    ' "dimension_status": "nominal_from_reference",\n'
    f' "disclaimer": "{DISCLAIMER}"}}')


class Route(BaseModel):
    """The router's verdict: which instruction block and unit rules apply."""

    model_config = ConfigDict(extra="ignore")

    mode: str = "GENERIC"
    region: str = "DUAL"
    confidence: float = 0.0
    occlusion: str = "low"


def _vision_json(system: str, image_bytes: bytes, user_text: str) -> dict:
    """One xAI vision call, JSON out — the same pattern as concept.read_design.
    Every failure (no key, network, schema) is one story upstream."""
    key = _provider_key("XAI_KEY")
    if not key:
        raise RenderUnavailable(
            "no XAI_KEY configured — the spec agent needs a vision key")

    media = _sniff_media_type(image_bytes)
    b64 = base64.b64encode(image_bytes).decode()

    import httpx

    try:
        response = httpx.post(
            "https://api.x.ai/v1/chat/completions", timeout=120.0,
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": os.environ.get("FACETTA_XAI_VISION", "grok-4.3"),
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": [
                        {"type": "image_url",
                         "image_url": {"url": f"data:{media};base64,{b64}"}},
                        {"type": "text", "text": user_text},
                    ]},
                ],
                "response_format": {"type": "json_object"},
            })
        response.raise_for_status()
        data = json.loads(response.json()["choices"][0]["message"]["content"])
        if not isinstance(data, dict):
            raise ValueError(f"provider returned non-object JSON: {data!r}")
        return data
    except Exception as exc:
        raise RenderUnavailable(f"vision inspect failed: {exc}") from exc


def route_design(image_bytes: bytes, notes: str = "") -> Route:
    """Section B: classify the render into a mode + region. A mode the router
    invents is coerced to GENERIC — the sheet must always have a real
    instruction block. Raises RenderUnavailable on missing key or provider
    failure."""
    data = _vision_json(_ROUTER_SYSTEM, image_bytes,
                        f"Designer notes: {notes or 'none'}")
    if data.get("mode") not in MODES:
        data["mode"] = "GENERIC"
    if data.get("region") not in REGIONS:
        data["region"] = "DUAL"
    try:
        return Route.model_validate(data)
    except ValidationError:
        # confidence/occlusion are advisory — junk scalars from the model are
        # a provider quirk, not a reason to fail (or to blame the client)
        return Route(mode=data["mode"], region=data["region"])


def _stub_summary(piece_type: str, region: str, note: str) -> dict:
    """The Section 5 summary shape: `mode` is the capability, `piece_type`
    the MODES table key, `dimension_status` one of nominal_from_reference /
    TBD / designer_supplied."""
    return {
        "mode": TASK_MODE, "piece_type": piece_type, "region": region,
        "confirmed_from_reference": [], "designer_must_confirm": [],
        "factory_notes": [note],
        "dimension_status": "nominal_from_reference",
        "disclaimer": DISCLAIMER,
    }


def inspect_render(image_bytes: bytes, notes: str, mode: str,
                   region: str) -> dict:
    """Section I / Section 5: the structured manufacturing summary — what the
    reference establishes, what the designer must confirm, what the factory
    should know. mode (the piece type) and region are ours (the router's or
    the caller's), so they are stamped over whatever the model echoed back."""
    data = _vision_json(
        _INSPECT_SYSTEM, image_bytes,
        f"Piece type: {mode}. Region: {region}. "
        f"Designer notes: {notes or 'none'}")
    summary = _stub_summary(mode, region, "")
    summary["factory_notes"] = []
    for field in ("confirmed_from_reference", "designer_must_confirm",
                  "factory_notes", "dimension_status", "disclaimer"):
        if data.get(field):
            summary[field] = data[field]
    return summary


# The assist reader: when a designer has NO saved record (the ballpark
# workflow), the official template's panel has nothing to letter. Grok
# assists by READING the render into estimated values that CODE letters into
# the panel, clearly marked estimated — the model never paints spec text on
# the sheet (see CLEAN_G0), so a 'Pullish' can never ship.
_ESTIMATE_SYSTEM = (
    MASTER_SYSTEM + "\n\n"
    "Read this jewelry image and estimate its dimensions as a REFERENCE for a "
    "designer prototyping — a helpful starting point, not production truth. "
    "Output JSON only, exactly this shape:\n"
    '{"stones": [{"qty": 1, "type": "species + cut, e.g. diamond oval '
    'brilliant", "size_mm": "L × W", "carat_each": 1.5, "confidence": 0.0}],\n'
    ' "metal": "karat/colour/material + finish",\n'
    ' "measurements": [{"label": "band width", "value": "~2 mm", '
    '"confidence": 0.0}, ...]}\n'
    "stones: one entry per distinct stone group (center first), qty counted "
    "from the image, sizes your best estimate in mm. carat_each may be null. "
    "measurements: the piece's own key numbers you can estimate (band width, "
    "overall length, drop, heights between levels...). "
    "confidence (0-1) is how sure you are of EACH value: an image alone has no "
    "true scale, so keep confidence modest unless a known measurement anchors "
    "it. Estimate honestly; omit what you cannot see. Output ONLY the JSON.")


def _conf(value) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.5   # a middling default when the model omits confidence


def read_sheet_specs(image_bytes: bytes, *,
                     scale_anchor: str | None = None) -> dict:
    """Grok's ESTIMATED read of a render — a designer's quick-draft
    REFERENCE, never production truth. Returns
    {"stones": [{qty,type,size_mm,carat_each,confidence}], "metal": str,
     "measurements": [{label,value,confidence}], "scaled": bool,
     "scale_anchor": str|None}.

    scale_anchor is ONE known measurement the designer supplies (e.g. "centre
    stone 2 ct" or "overall height 40 mm"); an image has no inherent scale, so
    with an anchor Grok scales every other estimate relative to it and the
    numbers get far more useful. Missing keys are normalized. Raises
    RenderUnavailable on provider failure — an explicit assist fails loudly."""
    ask = "Estimate the dimensions of this piece as a reference."
    if scale_anchor:
        ask += (f" KNOWN measurement to scale everything else against: "
                f"{scale_anchor}. Scale all other estimates to be consistent "
                f"with it and raise your confidence accordingly.")
    data = _vision_json(_ESTIMATE_SYSTEM, image_bytes, ask)
    return _normalize_stone_read(data, scale_anchor)


def _normalize_stone_read(data: dict, scale_anchor: str | None) -> dict:
    """Coerce a vision read into the shared estimate shape:
    {"stones": [{qty,type,size_mm,carat_each,confidence}], "metal": str,
     "measurements": [{label,value,confidence}], "scaled", "scale_anchor"}.
    Used by both the render reader (read_sheet_specs) and the hand-plate
    reader (read_design_plate) so downstream (physics check, panel) is one
    path. Junk entries are dropped; missing keys are filled honestly."""
    stones = []
    for s in data.get("stones") or []:
        if isinstance(s, dict) and s.get("type"):
            stones.append({
                "qty": int(s.get("qty") or 1),
                "type": str(s["type"]),
                "size_mm": str(s.get("size_mm") or "TBD"),
                "carat_each": s.get("carat_each"),
                "confidence": _conf(s.get("confidence")),
            })
    measurements = []
    for m in data.get("measurements") or []:
        if isinstance(m, dict) and m.get("label"):
            measurements.append({"label": str(m["label"]),
                                 "value": str(m.get("value") or "TBD"),
                                 "confidence": _conf(m.get("confidence"))})
        elif isinstance(m, (list, tuple)) and len(m) >= 2:  # tolerate old shape
            measurements.append({"label": str(m[0]), "value": str(m[1]),
                                 "confidence": 0.5})
    return {"stones": stones, "metal": str(data.get("metal") or "TBD"),
            "measurements": measurements,
            "scaled": bool(scale_anchor), "scale_anchor": scale_anchor}


# The hand-plate reader: the founder's wife hand-renders dimensioned design
# plates for factories (gouache + pencil on toned paper, often with the piece
# drawn over a figure croquis and dimensions written by hand). This reads ONE
# such plate into the same estimate shape so the factory-sheet panel can letter
# it — the app extracting what she used to letter by hand. Numbers she WROTE on
# the plate are authoritative (high confidence); shapes/colours read from the
# rendering are estimates; the croquis figure and background are ignored.
_PLATE_SYSTEM = (
    MASTER_SYSTEM + "\n\n"
    "This is a jewelry designer's HAND-RENDERED design plate (gouache/"
    "watercolour and pencil on toned paper) — often the piece drawn beside or "
    "over a faint pencil figure sketch, and possibly rotated. Read ONLY the "
    "rendered jewelry piece; IGNORE the figure/croquis, the background paper, "
    "and any body outline. Report the piece as JSON only, exactly this shape:\n"
    '{"jewelry_type": "ring|pendant|earrings|brooch|bracelet|necklace",\n'
    ' "stones": [{"qty": 1, "type": "species + cut, e.g. sapphire emerald cut '
    'or lapis cabochon or diamond marquise", "size_mm": "L × W", '
    '"carat_each": null, "confidence": 0.0}],\n'
    ' "metal": "karat/colour/material, e.g. 18k yellow gold or platinum",\n'
    ' "assembly": "one sentence describing the SPATIAL arrangement: what is at '
    'top/bottom/centre and what connects to what, e.g. \'vertical drop earring: '
    'ear wire at top, graduated discs descending, emerald-cut stone in a round '
    'frame at the bottom\'",\n'
    ' "measurements": [{"label": "overall length", "value": "38 mm", '
    '"confidence": 0.0}],\n'
    ' "hand_written": ["transcribe VERBATIM every number, dimension, or note '
    'the designer wrote on the plate"]}\n'
    "stones: one entry per distinct stone group (centre first); include "
    "cabochons, enamel domes, briolettes, pavé — name the cut/shape and the "
    "colour you see. ANY dimension the designer WROTE on the plate is "
    "authoritative: report it in measurements at HIGH confidence (>=0.85) and "
    "echo it verbatim in hand_written. Shapes and colours you infer from the "
    "rendering are estimates — keep confidence modest. Use controlled trade "
    "terms where you are sure; never invent a stone. Output ONLY the JSON.")


def read_design_plate(image_bytes: bytes, *,
                      scale_anchor: str | None = None) -> dict:
    """Read a hand-rendered design plate into the shared estimate shape plus a
    `hand_written` list (every number/note the designer lettered, verbatim —
    those are authoritative, not guesses). The factory-sheet panel letters the
    result; her drawing itself is the sheet's image. Raises RenderUnavailable
    on provider failure. This is the reverse of the app's usual flow: her hand
    drawing IN, a structured factory sheet OUT."""
    ask = ("Read this hand-rendered jewelry design plate. Transcribe every "
           "dimension or note the designer wrote by hand.")
    if scale_anchor:
        ask += (f" KNOWN measurement to scale the rest against: {scale_anchor}.")
    data = _vision_json(_PLATE_SYSTEM, image_bytes, ask)
    read = _normalize_stone_read(data, scale_anchor)
    read["source"] = "plate"             # the panel banner adapts its wording
    read["jewelry_type"] = str(data.get("jewelry_type") or "").strip() or None
    # the spatial arrangement — feeds the redraw's assembly lock so Grok keeps
    # the piece assembled instead of flattening it into a row of loose stones
    read["assembly"] = str(data.get("assembly") or "").strip() or None
    hand = data.get("hand_written") or []
    read["hand_written"] = [str(h) for h in hand if str(h).strip()]
    return read


def authoritative_dims(spec: Spec) -> list[str]:
    """Math as ASSISTANCE: lift the validated record's own numbers out as
    plain text for the prompt. Nothing is computed or drawn here — only what
    the spec already states, so every line is designer-authoritative."""
    def num(value: float) -> str:
        return f"{value:g}"

    dims: list[str] = []
    stone, mm = spec.stone, spec.stone.dimensions_mm
    dims.append(
        f"center stone: {stone.cut.replace('_', ' ')} {stone.species} "
        f"{num(mm.length)} × {num(mm.width)} × {num(mm.depth)} mm, "
        f"{num(stone.carat)} ct")

    for group in spec.side_stones:
        gmm = group.dimensions_mm
        where = (group.position or "side").replace("_", " ")
        dims.append(
            f"{where} stones: {group.count} × {group.cut.replace('_', ' ')} "
            f"{group.species} {num(gmm.length)} × {num(gmm.width)} mm")

    if spec.metal:
        metal = spec.metal
        alloy = " ".join(
            part for part in (
                f"{metal.karat}k" if metal.karat else None,
                metal.color, metal.material) if part)
        line = f"metal: {alloy}"
        if metal.finish:
            line += f", {metal.finish.replace('_', ' ')} finish"
        dims.append(line)

    if spec.setting:
        line = f"setting: {spec.setting.style.replace('_', ' ')}"
        if spec.setting.prong_count:
            line += f", {spec.setting.prong_count} prongs"
        if spec.setting.gallery_height_mm:
            line += f", gallery height {num(spec.setting.gallery_height_mm)} mm"
        dims.append(line)

    if spec.ring_size:
        line = f"ring size: {spec.ring_size.system} {spec.ring_size.value}"
        if spec.ring_size.inner_diameter_mm:
            line += f", inner Ø {num(spec.ring_size.inner_diameter_mm)} mm"
        dims.append(line)

    if spec.drop:
        drop = spec.drop
        dims.append(f"overall drop length: {num(drop.overall_length_mm)} mm")
        dims.append(f"ear hook height: {num(drop.hook_height_mm)} mm")
        if drop.link_count:
            line = f"link run: {drop.link_count} links"
            if drop.link_pitch_mm:
                line += f" at {num(drop.link_pitch_mm)} mm pitch"
            dims.append(line)
        if drop.wall_mm:
            dims.append(f"frame wall: {num(drop.wall_mm)} mm")
        if drop.wire_mm:
            dims.append(f"wire gauge: {num(drop.wire_mm)} mm")

    if spec.bracelet:
        br = spec.bracelet
        dims.append(
            f"bracelet opening: {num(br.inner_length_mm)} × "
            f"{num(br.inner_width_mm)} mm inner, band {num(br.width_mm)} × "
            f"{num(br.thickness_mm)} mm")
        if br.gap_width_mm:
            dims.append(f"cuff gap: {num(br.gap_width_mm)} mm")
        if br.link_count:
            dims.append(f"bracelet links: {br.link_count}")

    if spec.pendant:
        pend = spec.pendant
        dims.append(
            f"bail: inner Ø {num(pend.bail_inner_diameter_mm)} mm, height "
            f"{num(pend.bail_height_mm)} mm")
        if pend.drop_mm:
            dims.append(f"pendant drop: {num(pend.drop_mm)} mm")

    if spec.chain:
        chain = spec.chain
        dims.append(
            f"chain: {chain.style.replace('_', ' ')}, "
            f"{num(chain.length_mm)} mm, "
            f"{chain.clasp.replace('_', ' ')} clasp")

    return dims


def compile_sheet_instruction(mode: str, region: str = "DUAL",
                              dims: list[str] | None = None,
                              notes: str = "", *,
                              templated: bool = False) -> str:
    """Assemble the one image-edit instruction: the founder's Task line
    first, then mode block + region units + the designer-authoritative
    dimensions (when a validated spec supplied them) + the TBD policy + the
    G0 tail + the honesty rule.

    templated=True is the official-template mode: the platform's code frames
    the drawing afterwards (facetta.drawing_frame), so the G0 tail's
    title-block sentence is replaced with the no-title-block rule — the model
    leaves clean margins and letters no identity at all."""
    if mode not in MODES:
        raise ValueError(f"unknown mode '{mode}'; options: {list(MODES)}")
    if region not in REGIONS:
        raise ValueError(f"unknown region '{region}'; options: {list(REGIONS)}")
    if templated:
        # the app's factory-sheet path: Grok draws the actual piece clean, the
        # code panel letters every number — so the model writes NO text at all.
        views = ", ".join(MODES[mode]["views"])
        parts = [TASK_LINE, CLEAN_DRAW_DIRECTIVE.format(views=views)]
        if notes:
            parts.append(f"Designer notes (honor in the drawing, do NOT letter "
                         f"them as text): {notes}")
        parts.append(CLEAN_G0)
        parts.append(HONESTY_RULE)
        return " ".join(parts)
    # legacy standalone sheet: the model letters its own numbers/title block
    parts = [TASK_LINE, MODES[mode]["prompt"], REGIONS[region]]
    if dims:
        parts.append(
            "Designer-authoritative dimensions — place these EXACTLY on the "
            "sheet, they are final:\n"
            + "\n".join(f"- {line}" for line in dims))
    if notes:
        parts.append(f"Designer notes: {notes}")
    parts.append(_TBD_POLICY)
    parts.append(G0_SUFFIX)
    parts.append(HONESTY_RULE)
    return " ".join(parts)


def generate_spec_sheet(image_bytes: bytes, *, notes: str = "",
                        mode: str | None = None, region: str = "DUAL",
                        spec: Spec | None = None, legibility: bool = False,
                        templated: bool = False, variant: int = 0,
                        model: str = "grok_direct") -> tuple[bytes, dict, bool]:
    """The Section H pipeline, one call: classify (unless the caller or the
    spec already knows the mode) → inspect → controlled image edit →
    optional legibility pass. Returns (sheet_bytes, summary, was_cached).

    templated=True passes through to compile_sheet_instruction: the model
    leaves clean margins and the caller applies the official Facetta frame
    (facetta.drawing_frame) from the record afterwards.

    A hiccup on the INSPECT call degrades to a stub summary — the sheet
    itself must not die because the summary call failed. The edit call's
    failures propagate: no sheet is the one thing this cannot paper over."""
    if mode is None:
        if spec is not None:
            mode = MODE_FOR_TEMPLATE.get(spec.template, "GENERIC")
        else:
            route = route_design(image_bytes, notes)
            mode = route.mode
            if region == "DUAL":       # caller left the default → router's call
                region = route.region

    dims = authoritative_dims(spec) if spec is not None else None
    instruction = compile_sheet_instruction(mode, region, dims, notes,
                                            templated=templated)

    try:
        summary = inspect_render(image_bytes, notes, mode, region)
    except RenderUnavailable as exc:
        summary = _stub_summary(
            mode, region, f"manufacturing summary unavailable: {exc}")
    # ours, not the model's: capability, piece type, region — and when a
    # validated spec injected authoritative numbers, the dimension status
    summary["mode"] = TASK_MODE
    summary["piece_type"] = mode
    summary["region"] = region
    if dims:
        summary["dimension_status"] = "designer_supplied"

    # variant lets the designer force a genuinely fresh drawing (the
    # regenerate button) instead of the content-addressed cached one
    sheet, cached = edit_image(image_bytes, instruction, model, variant=variant)
    if legibility:
        sheet, _ = edit_image(
            sheet, _legibility_instruction(templated=templated), model,
            variant=variant)
    return sheet, summary, cached


# ---------------------------------------------------------------------------
# MODE A — JEWELRY_RENDER (Section 4A): photoreal product visualization.
# ---------------------------------------------------------------------------

_RENDER_SPINE = (
    "Studio lighting, soft gradient neutral background, sharp focus, no "
    "watermark, no text overlay, no factory dimensions.")


def compile_render_instruction(piece_description: str, metal: str = "",
                               stones: str = "", setting_details: str = "",
                               view_angle: str = "three-quarter product view"
                               ) -> str:
    """The Section 4A prompt body, near-verbatim: the Metal:/Stones:/setting
    clauses appear only when supplied — an empty field is omitted cleanly,
    never printed as 'Metal: .'."""
    parts = ["Photorealistic fine jewelry product photograph, "
             f"{piece_description.strip()}."]
    if metal.strip():
        parts.append(f"Metal: {metal.strip()}.")
    if stones.strip():
        parts.append(f"Stones: {stones.strip()}.")
    if setting_details.strip():
        parts.append(setting_details.strip().rstrip(".") + ".")
    parts.append(_RENDER_SPINE)
    parts.append("Professional jewelry campaign quality, accurate "
                 f"proportions, {view_angle.strip()}.")
    return " ".join(parts)


def jewelry_render(piece_description: str, *, metal: str = "",
                   stones: str = "", setting_details: str = "",
                   view_angle: str = "three-quarter product view",
                   variant: int = 0,
                   model: str = "grok_direct") -> tuple[bytes, bool]:
    """MODE A, one call: compile the Section 4A prompt and generate. Returns
    (image_bytes, was_cached); variant>0 asks for a genuinely fresh take."""
    prompt = compile_render_instruction(
        piece_description, metal=metal, stones=stones,
        setting_details=setting_details, view_angle=view_angle)
    return generate_image(prompt, model=model, variant=variant)


# Extra camera angles of the SAME piece. Consistency is why these are derived
# from the hero render by image-to-image (design-locked), never re-generated
# from text — a fresh text render would invent a different ring every time.
# The named presets are the standard product-photography turntable; a designer
# may also pass free-text ("from below, looking up at the gallery").
VIEW_ANGLES: dict[str, str] = {
    "three_quarter": "a three-quarter product angle, camera slightly above and "
                     "to the side, the piece filling the frame the same as the "
                     "reference",
    "top": "a strict top-down bird's-eye plan view — camera pointing straight "
           "DOWN at the face from directly overhead (90° above), the face flat "
           "to the camera",
    "front": "a straight-on front elevation — camera at the SAME HEIGHT as the "
             "piece, looking horizontally at the front (NOT from above, NOT "
             "top-down); the WHOLE ring including the complete band is visible "
             "and centred, nothing cropped at the bottom",
    "side": "a true side profile facing the LENGTH of the finger — camera level, "
            "the band forming a vertical circle (an O), showing the full height "
            "the setting rises above the band and the shoulder taper; the ENTIRE "
            "ring in frame, nothing cropped",
    "profile_width": "the OTHER side profile, facing the WIDTH of the piece — "
                     "rotate the piece 90° from the standard side view so the "
                     "camera looks across the width of the head; you see how "
                     "wide the setting sits and both shoulders symmetrically; "
                     "the ENTIRE ring in frame, nothing cropped",
    "back": "the back three-quarter, showing the underside gallery and the "
            "underneath of the shank",
    "detail": "a tight close-up macro of the centre setting and gallery, the "
              "rest of the piece softly out of frame",
    "hand": "worn on an elegant manicured hand in a relaxed, graceful editorial "
            "jewelry pose — the hand softly draped or resting, all fingers "
            "gently together or lightly separated and naturally curved, the "
            "ring resting on the ring finger and clearly visible. A tasteful, "
            "classic hand pose, never a rude or pointing gesture",
}
STANDARD_VIEW_SET = ("three_quarter", "top", "front", "side", "profile_width")

# hand/worn angles need explicit anatomy guardrails — a live test repeatedly
# produced a ring spanning two fingers, so the prompt is emphatic AND the
# result is vision-validated below (a prompt alone is not reliable enough).
_WORN_SAFETY = (
    "CRITICAL — how the ring is worn: an elegant, relaxed hand in a tasteful "
    "editorial jewelry pose. The fingers are gently, evenly separated and "
    "softly curved so each finger is distinct, and the ring sits on the ring "
    "finger alone. The ring encircles exactly ONE finger and its head/halo "
    "sits centred on that finger, with clear space on BOTH sides of the head — "
    "the head must NOT touch, overlap, bridge to, or crowd a neighbouring "
    "finger, and the band must NOT rest across the gap between two fingers. "
    "Keep it graceful and professional: a natural resting or softly draped "
    "hand. Realistic human hand anatomy: one hand, five fingers, correct "
    "proportions. STRICTLY FORBIDDEN: any rude, offensive, or pointing "
    "gesture; a single finger raised or thrust forward on its own (never an "
    "isolated middle or index finger); a ring on or across two fingers; a "
    "head touching an adjacent finger; extra/missing/deformed fingers; two "
    "hands.")

# The ring's PHYSICAL size must never change between shots. If a 2 ct centre
# reads huge in the render and arrives smaller from the factory the client is
# betrayed — so lock the true scale across every angle and skin tone.
_SCALE_LOCK = (
    "SCALE LOCK — the ring's real size is fixed: the centre stone, halo, and "
    "band keep the EXACT same physical dimensions and the same proportion "
    "relative to the finger as the reference. Do NOT enlarge the stone to look "
    "more impressive or shrink it to fit — a 2 ct stone must read as 2 ct. The "
    "ring must look the SAME size in every view and on every skin tone; the "
    "stone-to-finger ratio is identical across all versions.")

_WORN_RETRY = (
    "The previous attempt was wrong — it either placed the ring across TWO "
    "fingers or used a rude/isolated-finger gesture. Redo it with a graceful, "
    "relaxed hand, fingers gently separated, the ring encircling only ONE "
    "finger with its head sitting on that single finger alone, and no "
    "offensive or pointing gesture.")

# Optional skin-tone choice for worn (hand) shots — a respectful, neutral
# spread; a designer may also pass a free-text description.
SKIN_TONES: dict[str, str] = {
    "fair": "fair, light skin", "light": "light skin",
    "medium": "medium skin tone", "olive": "olive skin tone",
    "tan": "tan skin", "brown": "brown skin", "deep": "deep brown skin",
    "dark": "dark skin",
}


def is_worn_angle(angle: str) -> bool:
    return any(w in angle.lower() for w in ("hand", "worn", "finger"))


def compile_view_instruction(angle: str, skin_tone: str | None = None,
                             retry: bool = False) -> str:
    """A camera-only change: the hero render is the reference, and the design
    is locked — only the viewpoint moves. `angle` is a preset key from
    VIEW_ANGLES or a free-text camera description. `skin_tone` (a SKIN_TONES
    key or free text) applies only to worn/hand shots. retry adds the
    single-finger correction after a validation failure."""
    described = VIEW_ANGLES.get(angle, angle)
    worn = is_worn_angle(angle)
    lines = [
        "Jewelry render — new camera angle of the SAME piece.",
        f"Show the EXACT SAME piece from the reference from {described}.",
        "IDENTITY LOCK: identical design — same centre stone (cut, colour, "
        "size), same halo and side stones, same setting and prong style, "
        "same metal and finish, same proportions and silhouette. Only the "
        "camera viewpoint changes; do NOT redesign, restyle, or add or "
        "remove any element.",
        _SCALE_LOCK,
        "The ENTIRE piece is fully visible and centred in frame — nothing "
        "cropped or cut off at any edge.",
        "Photorealistic studio product photograph, same soft neutral "
        "background and lighting as the reference, sharp focus, no text.",
    ]
    if worn:
        if skin_tone:
            described_tone = SKIN_TONES.get(skin_tone, skin_tone)
            lines.append(f"The hand has {described_tone}.")
        lines.append(_WORN_SAFETY)
        if retry:
            lines.insert(1, _WORN_RETRY)
    return "\n".join(lines)


# A prompt alone cannot guarantee the ring lands on one finger — a factory
# lookbook can NEVER show a ring bridging two fingers, so the worn render is
# vision-validated and re-rolled until it passes (or is refused).
_WORN_CHECK_SYSTEM = """\
You are a STRICT quality inspector for jewelry model photography. Look at the
image of a ring worn on a hand and judge ONLY how it is worn. Reason about the
ring's head/halo relative to the finger next to it.

Return a JSON object exactly:
{"single_finger": true|false, "head_touches_neighbor": true|false,
 "one_hand": true|false, "anatomy_ok": true|false, "gesture_ok": true|false,
 "issue": "short reason"}

single_finger is TRUE only if ALL hold: the band encircles exactly ONE finger,
the head/halo does NOT touch, overlap, bridge to, or crowd the neighbouring
finger, and there is clear empty background space on BOTH sides of the head.
Set head_touches_neighbor TRUE if the head reaches over or contacts an adjacent
finger. one_hand is FALSE if more than one hand appears; anatomy_ok is FALSE for
extra/missing/deformed fingers. gesture_ok is FALSE if the hand makes any rude,
offensive, or pointing gesture, or a single finger is raised/extended on its own
(e.g. an isolated middle or index finger) — a jewelry lookbook must be tasteful.
Be strict — when unsure, answer single_finger false. Output ONLY the JSON."""


def check_worn_render(image_bytes: bytes) -> dict:
    """Vision QA of a worn shot. Returns the inspector JSON; on a provider
    failure returns a permissive pass so a hiccup never blocks the pipeline
    (the strict gate is best-effort, not a hard dependency)."""
    try:
        data = _vision_json(_WORN_CHECK_SYSTEM, image_bytes,
                            "Judge how the ring is worn.")
    except RenderUnavailable:
        return {"single_finger": True, "one_hand": True, "anatomy_ok": True,
                "gesture_ok": True, "issue": "", "checked": False}
    data.setdefault("issue", "")
    data["checked"] = True
    return data


def _worn_ok(check: dict) -> bool:
    return bool(check.get("single_finger") and check.get("one_hand", True)
                and check.get("anatomy_ok", True)
                and check.get("gesture_ok", True))


# The design-consistency validator: a derived view (a new angle, a worn shot)
# must be the SAME piece as the hero. This compares the two images by vision
# and re-rolls if the jewelry drifted — the same gate the worn check applies to
# the hand, applied to the design itself.
_CONSISTENCY_SYSTEM = """\
You compare TWO photos of fine jewelry for a manufacturer. The FIRST image is
the approved reference design. The SECOND is a new photo that must show the
EXACT SAME piece from a different angle or setting — not a redesign.

Judge ONLY the jewelry (ignore camera angle, background, hands, lighting).
Return JSON exactly:
{"consistent": true|false, "differences": ["..."], "severity": "none|minor|major"}

consistent is FALSE if the second piece differs in any of: centre stone shape/
cut, centre stone colour, number or arrangement of side/halo stones, setting or
prong style, metal colour, overall proportions, or the SIZE/SCALE of the stone
and ring. Scale matters: if the ring is worn on a hand, the centre stone must
keep the same size relative to the finger — a stone that looks noticeably bigger
or smaller than the reference (so a 2 ct would read as a different carat) is a
MAJOR difference, because the client must not be misled about how large the
finished piece is. List each real difference briefly in differences. Minor
lighting/reflection changes are NOT differences. Set severity to "major" for any
change to the design, stones, metal, or size; "minor" for trivial framing. Be
fair but honest. Output ONLY the JSON."""


def _vision_json_2img(system: str, image_a: bytes, image_b: bytes,
                      text: str) -> dict:
    """A vision call over TWO images (reference, candidate), JSON out."""
    key = _provider_key("XAI_KEY")
    if not key:
        raise RenderUnavailable("no XAI_KEY configured — validation needs a key")

    import httpx

    def uri(b: bytes) -> str:
        return f"data:{_sniff_media_type(b)};base64," + base64.b64encode(b).decode()

    try:
        response = httpx.post(
            "https://api.x.ai/v1/chat/completions", timeout=120.0,
            headers={"Authorization": f"Bearer {key}"},
            json={"model": os.environ.get("FACETTA_XAI_VISION", "grok-4.3"),
                  "messages": [
                      {"role": "system", "content": system},
                      {"role": "user", "content": [
                          {"type": "image_url", "image_url": {"url": uri(image_a)}},
                          {"type": "image_url", "image_url": {"url": uri(image_b)}},
                          {"type": "text", "text": text}]}],
                  "response_format": {"type": "json_object"}})
        response.raise_for_status()
        data = json.loads(response.json()["choices"][0]["message"]["content"])
        if not isinstance(data, dict):
            raise ValueError("non-object JSON")
        return data
    except Exception as exc:
        raise RenderUnavailable(f"consistency check failed: {exc}") from exc


def check_design_consistency(reference_bytes: bytes,
                             candidate_bytes: bytes) -> dict:
    """Does the candidate show the SAME jewelry design as the reference?
    Returns {"consistent", "differences", "severity", "checked"}. A provider
    failure returns a permissive pass (checked=False) — the gate is best-effort,
    never a hard dependency that blocks a render."""
    try:
        data = _vision_json_2img(
            _CONSISTENCY_SYSTEM, reference_bytes, candidate_bytes,
            "Is the second the same piece as the first?")
    except RenderUnavailable:
        return {"consistent": True, "differences": [], "severity": "none",
                "checked": False}
    data.setdefault("differences", [])
    data.setdefault("severity", "none")
    data["checked"] = True
    return data


# The markup reader: the designer draws/writes ON the piece — in-app canvas
# circles and arrows with typed notes, or freehand pen and handwriting (even a
# photographed printout). Grok reads the marks into structured change requests
# the localized-edit contract executes; the marks themselves never become an
# edit base, and an unclear mark asks instead of guessing.
_MARKUP_SYSTEM = """\
You read a designer's markup on a jewelry image for a manufacturing platform.
The FIRST image is the clean approved render. The SECOND is the SAME image
carrying the designer's marks: canvas circles, arrows, highlights, or freehand
pen strokes and HANDWRITING (possibly photographed).

For EVERY distinct mark: transcribe any handwriting VERBATIM first, then
interpret it. Describe the marked region in jewelry terms ("the prongs on the
center setting", "the halo, lower arc", "the shank, left shoulder"). One
annotation per mark. Do not invent marks; do not merge separate marks.

Return JSON exactly:
{"annotations": [{"region_description": "...", "change_instruction": "...",
  "target_section": "stone|side_stones|setting|metal|band|ring_size|drop|pendant|chain|bracelet|brooch" or null,
  "handwriting": "verbatim transcription or empty",
  "confidence": 0.0-1.0}],
 "understood_as": "Understood as: (1) ...; (2) ... — nothing else changes.",
 "needs_clarification": true|false, "clarification": "the ONE question to ask"}

Set needs_clarification true (with a concrete question) if any handwriting is
illegible, a mark's intent is ambiguous, or you cannot tell WHICH element a
mark points at. NEVER guess a region or an intent. Output ONLY the JSON."""


def read_markup(clean_bytes: bytes, marked_bytes: bytes) -> dict:
    """Read the designer's marks: clean render vs marked copy, structured
    change requests out. Post-rule: any annotation under 0.6 confidence flips
    needs_clarification — a half-read mark is asked about, never executed.
    Raises RenderUnavailable on provider failure (explicit request, fails
    loudly)."""
    data = _vision_json_2img(_MARKUP_SYSTEM, clean_bytes, marked_bytes,
                             "Read the designer's marks on the second image.")
    annotations = []
    for a in data.get("annotations") or []:
        if not isinstance(a, dict):
            continue
        region = str(a.get("region_description") or "").strip()
        change = str(a.get("change_instruction") or "").strip()
        if not region or not change:
            continue
        annotations.append({
            "region_description": region,
            "change_instruction": change,
            "target_section": a.get("target_section"),
            "handwriting": str(a.get("handwriting") or ""),
            "confidence": float(a.get("confidence") or 0.0),
        })
    needs = bool(data.get("needs_clarification"))
    clarification = str(data.get("clarification") or "")
    low = [a for a in annotations if a["confidence"] < 0.6]
    if low and not needs:
        needs = True
        clarification = clarification or (
            "some marks were hard to read with confidence — restate: "
            + "; ".join(a["region_description"] for a in low))
    return {"annotations": annotations,
            "understood_as": str(data.get("understood_as") or ""),
            "needs_clarification": needs,
            "clarification": clarification}


def mask_from_markup(clean_bytes: bytes, marked_bytes: bytes,
                     dilate_px: int = 24) -> bytes | None:
    """Where did the designer draw? Pixel-diff the clean and marked images
    (same raster only — in-app canvas marks) into a dilated white-on-black
    mask PNG, so the markup edit gets the SAME measured-drift gate as a
    canvas-masked localized edit. Returns None when the two images differ in
    size (e.g. a photographed printout) — no mask beats a wrong mask."""
    import io

    from PIL import Image, ImageChops, ImageFilter

    clean = Image.open(io.BytesIO(clean_bytes)).convert("RGB")
    marked = Image.open(io.BytesIO(marked_bytes)).convert("RGB")
    if clean.size != marked.size:
        return None
    diff = ImageChops.difference(clean, marked).convert("L")
    mask = diff.point(lambda p: 255 if p > 24 else 0)
    if mask.getbbox() is None:
        return None                      # no marks at all
    # dilate so the edit region breathes around the stroke itself
    grown = mask.filter(ImageFilter.MaxFilter(
        max(3, (dilate_px // 2) * 2 + 1)))
    buf = io.BytesIO()
    grown.save(buf, format="PNG")
    return buf.getvalue()


def render_worn_view(image_bytes: bytes, angle: str, *,
                     skin_tone: str | None = None, model: str = "grok_direct",
                     max_attempts: int = 3) -> dict:
    """A worn/hand shot that is vision-validated: generate, inspect, and
    re-roll (with the single-finger correction) until the ring is on exactly
    one finger — or refuse. Returns {"image", "ok", "attempts", "issue"};
    ok=False means every attempt failed the check and the image must NOT be
    shown as final (the caller drops or flags it)."""
    last_image, last_issue = None, ""
    for attempt in range(1, max_attempts + 1):
        instruction = compile_view_instruction(angle, skin_tone,
                                                retry=attempt > 1)
        image, _ = edit_image(image_bytes, instruction, model)
        check = check_worn_render(image)
        last_image, last_issue = image, check.get("issue", "")
        if _worn_ok(check):
            return {"image": image, "ok": True, "attempts": attempt, "issue": ""}
    return {"image": last_image, "ok": False, "attempts": max_attempts,
            "issue": last_issue or "ring not clearly on a single finger"}


def render_view(image_bytes: bytes, angle: str, *, skin_tone: str | None = None,
                model: str = "grok_direct") -> tuple[bytes, bool]:
    """One additional camera angle of the piece in `image_bytes`, design-
    locked. skin_tone applies only to worn/hand shots. Returns
    (image_bytes, was_cached). For worn angles prefer render_worn_view, which
    validates that the ring is on one finger."""
    return edit_image(
        image_bytes, compile_view_instruction(angle, skin_tone), model)


# When a derived view DRIFTS the design (a new angle that is subtly a different
# piece), this note re-anchors the re-roll to the reference. It also varies the
# instruction text (attempt suffix) so the content-addressed cache is busted and
# the re-roll actually generates a fresh image rather than returning the drifted
# one again.
_DRIFT_RETRY = (
    "The previous attempt DRIFTED from the reference design — it changed the "
    "piece instead of only moving the camera. Regenerate strictly locked to "
    "the reference: same centre stone (cut, colour, size), same halo and side "
    "stones, same setting and prong style, same metal and proportions. Only "
    "the viewpoint differs.")


def render_checked_view(image_bytes: bytes, angle: str, *,
                        skin_tone: str | None = None, model: str = "grok_direct",
                        max_attempts: int = 3,
                        check_consistency: bool = True) -> dict:
    """One derived view, gated on BOTH validators: a worn/hand shot must have
    the ring on a single finger (see render_worn_view), and every view must be
    the SAME design as the hero (check_design_consistency). Generate, inspect,
    and re-roll on a worn failure or a MAJOR design drift until it passes — or
    return the best attempt flagged so the caller need not file it.

    Returns {"angle", "image", "cached", "ok", "consistent", "differences",
    "severity", "issue", "attempts"}. ok=False → worn check failed;
    consistent=False → the piece drifted from the hero."""
    worn = is_worn_angle(angle)
    last = None
    for attempt in range(1, max_attempts + 1):
        retry = attempt > 1
        if worn:
            instruction = compile_view_instruction(angle, skin_tone, retry=retry)
        else:
            instruction = compile_view_instruction(angle, skin_tone)
            if retry:
                instruction += f"\n{_DRIFT_RETRY} (attempt {attempt})"
        image, cached = edit_image(image_bytes, instruction, model)

        worn_ok, issue = True, ""
        if worn:
            check = check_worn_render(image)
            worn_ok = _worn_ok(check)
            issue = check.get("issue", "")

        cons = {"consistent": True, "differences": [], "severity": "none",
                "checked": False}
        if check_consistency:
            cons = check_design_consistency(image_bytes, image)
        # only a CHECKED, MAJOR drift forces a re-roll; minor lighting/reflection
        # noise the vision model may flag is tolerated so we don't loop forever
        drift_major = bool(cons.get("checked") and cons.get("severity") == "major")

        last = {"angle": angle, "image": image, "cached": cached,
                "ok": worn_ok, "consistent": bool(cons.get("consistent", True)),
                "differences": list(cons.get("differences", [])),
                "severity": cons.get("severity", "none"),
                "issue": issue, "attempts": attempt}
        if worn_ok and not drift_major:
            return last
    return last


def render_view_set(image_bytes: bytes, angles, *, skin_tone: str | None = None,
                    model: str = "grok_direct",
                    check_consistency: bool = True) -> list[dict]:
    """A turntable set: each requested angle derived from the ONE hero render,
    so every view is the same design. Every view is design-consistency checked
    against the hero (re-rolled on major drift); worn/hand angles are also
    single-finger validated. Views carry ok/consistent/issue so the caller can
    drop or flag a bad one. Returns a list of {"angle", "image", "cached",
    "ok", "consistent", "differences", "severity", "issue"} in request order."""
    views = []
    for angle in angles:
        result = render_checked_view(image_bytes, angle, skin_tone=skin_tone,
                                     model=model,
                                     check_consistency=check_consistency)
        views.append({"angle": angle, "image": result["image"],
                      "cached": result["cached"], "ok": result["ok"],
                      "consistent": result["consistent"],
                      "differences": result["differences"],
                      "severity": result["severity"], "issue": result["issue"]})
    return views


# A short showcase clip of the piece. Motions the designer can pick; each keeps
# the piece centred and the design locked, and spins/moves GENTLY — a jewelry
# showcase reads as elegant, never a fast whirl.
SPIN_MOTIONS: dict[str, str] = {
    "turntable": "a slow, smooth 360-degree turntable rotation, the piece "
                 "spinning gently and evenly on its stand, seamless loop",
    "sway": "a gentle slow sway, the piece rocking softly side to side so the "
            "facets catch the light",
    "orbit": "the camera slowly orbiting around the piece a little more than "
             "half a turn, smooth and unhurried",
    "sparkle": "the piece nearly still with a slow subtle drift, light moving "
               "across the stones so they sparkle",
}
DEFAULT_SPIN_MOTION = "turntable"


def compile_spin_prompt(motion: str = DEFAULT_SPIN_MOTION) -> str:
    """The showcase-video prompt: design-locked, slow and elegant."""
    described = SPIN_MOTIONS.get(motion, motion)
    return (
        f"Fine jewelry showcase video: {described}. Photorealistic studio "
        "product footage of the EXACT piece in the reference image — same "
        "design, same stones, setting, metal and proportions; do not redesign "
        "it. Soft neutral studio background and lighting, sharp focus on the "
        "piece, smooth slow motion, no text or watermark. Keep the piece "
        "centred in frame the whole time.")


def render_spin_video(image_bytes: bytes, *, motion: str = DEFAULT_SPIN_MOTION,
                      model: str = "grok_video"):
    """A short spinning showcase clip from a still render, design-locked.
    Returns a render.VideoResult (mp4 bytes when the media host is reachable,
    otherwise just the url)."""
    from facetta.render import generate_video

    return generate_video(image_bytes, compile_spin_prompt(motion), model=model)


# ---------------------------------------------------------------------------
# MODE C — LOCALIZED_EDIT (Section 4C): change inside the highlight, freeze
# everything outside it. The preservation contract rides in EVERY edit
# prompt; a mask enables the drift QA and the one stronger-preserve retry.
# ---------------------------------------------------------------------------

_EDIT_OPENERS = {"render": "Jewelry render edit.",
                 "technical": "Jewelry technical drawing edit."}

_STRENGTHEN_LINE = (
    "CRITICAL: the previous attempt drifted outside the highlighted region. "
    "Preserve every pixel outside the region below with exact fidelity — "
    "this preservation contract is absolute.")


def compile_localized_edit_instruction(region_description: str,
                                       change_instruction: str,
                                       kind: str = "render",
                                       strengthen: bool = False) -> str:
    """The Section 4C preservation contract, verbatim blocks: PRESERVE /
    EDIT SCOPE / FORBIDDEN with the region and change filled in. kind
    'technical' opens as a drawing edit and forbids moving other view boxes
    or unrelated dimension strings; strengthen=True is the one-retry
    stronger-preserve language — a CRITICAL opener plus the preserve clause
    repeated at the tail."""
    if kind not in _EDIT_OPENERS:
        raise ValueError(
            f"unknown edit kind '{kind}'; options: {list(_EDIT_OPENERS)}")
    preserve = (
        f"PRESERVE: All design elements outside '{region_description}' must "
        "remain exactly as in the reference — same camera angle, lighting, "
        "metal tone, every stone and prong outside the region, shank shape "
        "outside the region, background unchanged.")
    edit_scope = (f"EDIT SCOPE: Inside '{region_description}' only: "
                  f"{change_instruction}.")
    forbidden = (
        "FORBIDDEN: Any change outside the highlighted region; no crop; no "
        "zoom; no global redesign; no new stones outside region unless "
        "explicitly inside highlight.")
    if kind == "technical":
        forbidden += (" Do not move other view boxes or unrelated dimension "
                      "strings.")
        closing = ("Black line art on white preserved. Match reference "
                   "style exactly outside edit zone.")
    else:
        closing = ("Photorealistic jewelry product quality. Match reference "
                   "style exactly outside edit zone.")
    lines = [_EDIT_OPENERS[kind], preserve, edit_scope, forbidden, closing]
    if strengthen:
        lines = [_STRENGTHEN_LINE] + lines + [preserve]
    return "\n".join(lines)


def _outside_drift(parent_bytes: bytes, child_bytes: bytes,
                   mask_bytes: bytes) -> float:
    """How much the edit moved OUTSIDE the mask (white = edit, black =
    preserve): mean absolute grayscale pixel delta over the preserve pixels,
    normalized to 0..1. Child and mask are resized to the parent so provider
    resolution changes never break the compare. Pure function — no provider,
    no cache."""
    import io

    from PIL import Image

    parent = Image.open(io.BytesIO(parent_bytes)).convert("L")
    child = Image.open(io.BytesIO(child_bytes)).convert("L")
    mask = Image.open(io.BytesIO(mask_bytes)).convert("L")
    if child.size != parent.size:
        child = child.resize(parent.size)
    if mask.size != parent.size:
        mask = mask.resize(parent.size)

    total = 0
    count = 0
    # "L" mode → tobytes() is one byte per pixel, row-major
    for p, c, m in zip(parent.tobytes(), child.tobytes(), mask.tobytes()):
        if m < 128:                      # black = preserve — measure here
            total += abs(p - c)
            count += 1
    if count == 0:                       # all-white mask: nothing to preserve
        return 0.0
    return total / count / 255.0


def localized_edit(image_bytes: bytes, *, region_description: str,
                   change_instruction: str, mask_bytes: bytes | None = None,
                   kind: str = "render", model: str = "grok_direct",
                   drift_threshold: float = 0.18, variant: int = 0,
                   style_ref: bytes | None = None) -> dict:
    """MODE C, one call: compile the preservation contract, edit, and (with a
    mask) QA the result — drift outside the mask beyond the threshold gets
    exactly ONE retry with the stronger preserve language, and the
    lower-drift child wins. The strengthened instruction is a different
    cache key, so the retry is a fresh render, never the same cached result.

    variant>0 is the designer's regenerate: re-asking for the SAME edit on the
    SAME image must be able to produce a fresh result — without it the
    content-addressed cache would replay the first (possibly bad) edit forever.

    Returns {"image", "changed", "frozen", "retried", "drift", "cached"}.
    Raises ValueError when the region or change is missing — per the MODE C
    rule, ask the user to select the area instead of guessing."""
    if not region_description.strip() or not change_instruction.strip():
        raise ValueError(
            "localized edit needs a highlighted region and a change "
            "instruction — ask the user to select the area to edit; a "
            "full-image redesign must be requested explicitly")

    instruction = compile_localized_edit_instruction(
        region_description, change_instruction, kind=kind)
    child, cached = edit_image(image_bytes, instruction, model,
                               variant=variant, style_ref=style_ref)

    retried = False
    drift: float | None = None
    if mask_bytes is not None:
        drift = _outside_drift(image_bytes, child, mask_bytes)
        if drift > drift_threshold:
            retried = True
            stronger = compile_localized_edit_instruction(
                region_description, change_instruction, kind=kind,
                strengthen=True)
            retry_child, retry_cached = edit_image(image_bytes, stronger,
                                                   model, variant=variant,
                                                   style_ref=style_ref)
            retry_drift = _outside_drift(image_bytes, retry_child, mask_bytes)
            if retry_drift < drift:      # keep the better (lower-drift) child
                child, cached, drift = retry_child, retry_cached, retry_drift

    return {
        "image": child,
        "changed": f"inside '{region_description}': {change_instruction}",
        "frozen": "everything outside: " + region_description,
        "retried": retried,
        "drift": drift,
        "cached": cached,
    }


GLOBAL_RESTYLE_WARNING = (
    "global restyle — the whole piece may change; compare with the parent "
    "version and revert if the direction is wrong")


def compile_global_restyle_instruction(instruction: str,
                                       kind: str = "render") -> str:
    """A scoped-to-everything change: reference-locked so it restyles THIS
    piece rather than inventing a new one, but with no region freeze — that
    is the point. The identity locks (same piece, composition, camera,
    background) are the guardrail; drift is expected and tolerated."""
    if kind not in _EDIT_OPENERS:
        raise ValueError(
            f"unknown edit kind '{kind}'; options: {list(_EDIT_OPENERS)}")
    opener = ("Jewelry render restyle." if kind == "render"
              else "Jewelry technical drawing restyle.")
    return "\n".join([
        opener,
        f"Apply this change across the whole piece: {instruction.strip()}.",
        "IDENTITY LOCK: This is a restyle of the SAME design in the "
        "reference — keep the same piece, the same composition and stone "
        "arrangement unless the change says otherwise, the same camera "
        "angle, and the same background. Do not replace the design with a "
        "different piece.",
        ("Photorealistic jewelry product quality." if kind == "render"
         else "Black line art on white preserved."),
    ])


def global_restyle(image_bytes: bytes, *, instruction: str,
                   kind: str = "render",
                   model: str = "grok_direct", variant: int = 0,
                   style_ref: bytes | None = None) -> dict:
    """The whole-piece change path: when the designer says "more X
    everywhere" or "widen the whole shank", forcing LOCALIZED_EDIT without a
    mask would either block them or guess a region. This edits reference-
    locked with NO freeze contract and returns a warning instead of a drift
    gate — the UI's parent/child compare and revert are the safety net.
    variant>0 regenerates: a fresh take instead of the cached first result."""
    if not instruction.strip():
        raise ValueError("global restyle needs a change instruction")
    child, cached = edit_image(
        image_bytes, compile_global_restyle_instruction(instruction, kind),
        model, variant=variant, style_ref=style_ref)
    return {
        "image": child,
        "changed": f"across the whole piece: {instruction.strip()}",
        "frozen": "piece identity, composition, camera, background",
        "warning": GLOBAL_RESTYLE_WARNING,
        "cached": cached,
    }

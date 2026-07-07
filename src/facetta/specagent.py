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

# G0 — the universal suffix, the tail of every image-edit instruction.
G0_SUFFIX = (
    "Single composite jewelry manufacturing technical drawing. Black "
    "technical line art on pure white. Orthographic views with view labels "
    "PLAN, FRONT, SIDE. Dimension lines with arrowheads. CAD/jewelry atelier "
    "documentation style. Gemstones as faceted outlines only, no color. No "
    "photorealism, no shadows, no jewelry box, no model. Preserve exact "
    "design proportions and silhouette from reference. Legible sans-serif "
    "labels. Title block with METAL, JOB REF, REV A.")

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

# The G0 sentence the official-template mode swaps out: when the platform's
# code applies the Facetta frame from the record, the model must draw NO
# identity block at all — code letters identity, the model never does.
_TITLE_BLOCK_SENTENCE = "Title block with METAL, JOB REF, REV A."
NO_TITLE_BLOCK_RULE = (
    "Do not draw any title block, brand name, designer name, job reference, "
    "or date — leave clean margins; the platform's official template adds "
    "the title block.")


def _templated_tail(templated: bool) -> str:
    """The G0 tail as the mode demands: templated mode swaps the model-drawn
    title-block sentence for the clean-margins rule."""
    if templated:
        return G0_SUFFIX.replace(_TITLE_BLOCK_SENTENCE, NO_TITLE_BLOCK_RULE)
    return G0_SUFFIX


def _legibility_instruction(*, templated: bool = False) -> str:
    """The G6 repair instruction, compiled at call time so it carries the
    same tail as the first edit: templated mode must not reintroduce a
    model-drawn title block, and the honesty rule closes both modes."""
    return _G6_BODY + _templated_tail(templated) + " " + HONESTY_RULE


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

# Section I — the manufacturing summary the app shows next to the sheet.
_INSPECT_SYSTEM = (
    MASTER_SYSTEM + "\n\n"
    "Inspect this render and return the manufacturing summary as JSON only, "
    "exactly this shape:\n"
    '{"mode": "...", "region": "...",\n'
    ' "confirmed_from_render": ["what the render establishes"],\n'
    ' "designer_must_confirm": ["every guessed or occluded value"],\n'
    ' "factory_notes": ["setter/caster instructions"],\n'
    ' "dimensions_on_sheet": "nominal_from_render",\n'
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


def _stub_summary(mode: str, region: str, note: str) -> dict:
    return {
        "mode": mode, "region": region,
        "confirmed_from_render": [], "designer_must_confirm": [],
        "factory_notes": [note],
        "dimensions_on_sheet": "nominal_from_render",
        "disclaimer": DISCLAIMER,
    }


def inspect_render(image_bytes: bytes, notes: str, mode: str,
                   region: str) -> dict:
    """Section I: the structured manufacturing summary — what the render
    establishes, what the designer must confirm, what the factory should
    know. mode/region are ours (the router's or the caller's), so they are
    stamped over whatever the model echoed back."""
    data = _vision_json(
        _INSPECT_SYSTEM, image_bytes,
        f"Mode: {mode}. Region: {region}. Designer notes: {notes or 'none'}")
    summary = _stub_summary(mode, region, "")
    summary["factory_notes"] = []
    for field in ("confirmed_from_render", "designer_must_confirm",
                  "factory_notes", "dimensions_on_sheet", "disclaimer"):
        if data.get(field):
            summary[field] = data[field]
    return summary


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
    parts = [TASK_LINE, MODES[mode]["prompt"], REGIONS[region]]
    if dims:
        parts.append(
            "Designer-authoritative dimensions — place these EXACTLY on the "
            "sheet, they are final:\n"
            + "\n".join(f"- {line}" for line in dims))
    if notes:
        parts.append(f"Designer notes: {notes}")
    parts.append(_TBD_POLICY)
    parts.append(_templated_tail(templated))
    parts.append(HONESTY_RULE)
    return " ".join(parts)


def generate_spec_sheet(image_bytes: bytes, *, notes: str = "",
                        mode: str | None = None, region: str = "DUAL",
                        spec: Spec | None = None, legibility: bool = False,
                        templated: bool = False,
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

    sheet, cached = edit_image(image_bytes, instruction, model)
    if legibility:
        sheet, _ = edit_image(
            sheet, _legibility_instruction(templated=templated), model)
    return sheet, summary, cached

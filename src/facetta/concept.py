"""Concept origination: Grok invents a design, Facetta makes it manufacturable.

The founder's test: let the image engine dream up an entirely new piece, then
have the platform do what a chat cannot — put REAL millimeters in the right
places, specify the metal, keep every profile consistent, and prove the whole
thing is physically buildable before it reaches a factory.

The division of labor is the same one the rest of the product runs on:
  invent the look        · Grok text-to-image (a brand-new design)
  read it into numbers   · a vision model (sparse, controlled-vocabulary read)
  make it physically real · the validator + density model (this module)
  draw every profile      · deterministic code, all from the one spec

The vision read is only an estimate — a photo (or a dream) never carries exact
millimeters. complete_design() turns that estimate into a spec that PASSES the
same density, fit, and clearance rules as a hand-built one, recording every
correction it had to make. The engine imagines; the validator is the jeweler.
"""

from __future__ import annotations

import json
import math
import os

from pydantic import BaseModel, ConfigDict, Field

from facetta.density import check_density
from facetta.render import RenderUnavailable, generate_image
from facetta.spec import (
    Band, Metal, RingSize, Setting, Spec, Stone, StoneColor, StoneDimensions,
)
from facetta.validation import (
    HALO_MARGIN_MM, STONE_GAP_MM, _surround_fit, validate_spec,
)
from facetta.vocabulary import Vocabulary, get_vocabulary

# vision cut → the nearest cut the ring sheet can draw
_CUT_MAP = {
    "emerald": "emerald_cut", "step": "emerald_cut", "rectangular": "emerald_cut",
    "square": "cushion", "cushion": "cushion", "radiant": "cushion",
    "round": "round_brilliant", "brilliant": "round_brilliant",
    "oval": "oval_brilliant", "marquise": "oval_brilliant", "pear": "oval_brilliant",
}
# depth as a fraction of width, by cut family — conventional cutting proportions
_DEPTH_FRAC = {"round_brilliant": 0.61, "oval_brilliant": 0.64,
               "emerald_cut": 0.65, "cushion": 0.66}

# how a vision-read mount maps to a spec setting the sheet can DRAW. The value
# is (spec style, prong_count) — prong_count is None for continuous-metal
# mounts (bezels), which the sheet renders as a collar, not claws. Keeping this
# a lookup means "this ring had a diamond bezel" actually reaches the drawing
# instead of being flattened to a default 4-prong basket.
_SETTING_MAP = {
    "bezel": ("bezel", None),
    "semi_bezel": ("semi_bezel", None),
    "half_bezel": ("semi_bezel", None),
    "tension": ("bezel", None),          # nearest drawable continuous mount
    "prong": ("4_prong_basket", 4),
    "prong_4": ("4_prong_basket", 4),
    "4_prong": ("4_prong_basket", 4),
    "4_prong_basket": ("4_prong_basket", 4),
    "prong_6": ("6_prong_basket", 6),
    "6_prong": ("6_prong_basket", 6),
    "6_prong_basket": ("6_prong_basket", 6),
    "v_prong": ("4_prong_basket", 4),
}


class DesignRead(BaseModel):
    """What a vision model can honestly report from a concept image — sparse,
    all inside the controlled vocabulary. Dimensions are ESTIMATES."""

    model_config = ConfigDict(extra="ignore")

    jewelry_type: str = "ring"
    halo: bool = False
    species: str = "diamond"
    cut: str = "round_brilliant"
    center_length_mm: float = 8.0
    center_width_mm: float = 6.0
    metal_material: str = "platinum"
    metal_color: str | None = None
    setting_style: str = "prong"     # how the centre is held (see _SETTING_MAP)


class ConceptInvalid(Exception):
    """A generated concept could not be made physically real — carries the
    corrections tried and the validator issues, so a caller can report both."""

    def __init__(self, corrections: list[str], issues):
        self.corrections = corrections
        self.issues = issues
        super().__init__("generated concept could not be made physically real")


def originate_concept(brief: str, model: str = "grok_direct",
                      variant: int = 0) -> tuple[bytes, DesignRead, Spec, list[str]]:
    """The whole origination flow, once: Grok invents → vision reads → the
    validator makes it real. Returns (concept_image, read, validated_spec,
    corrections). Raises RenderUnavailable (no key / provider) or ConceptInvalid
    (the concept could not be made buildable). Shared by /from-concept and the
    one-call /build so both stay in lockstep."""
    image, _ = generate_concept(brief, model, variant)
    read = read_design(image, brief)
    spec, corrections = complete_design(read, brief)
    result = validate_spec(spec, get_vocabulary())
    if not result.ok:
        raise ConceptInvalid(corrections, result.issues)
    return image, read, result.spec, corrections


def concept_prompt(brief: str) -> str:
    """A clean product-photo brief so the read is unambiguous."""
    return (
        f"{brief}. A single piece of fine jewelry, professional studio product "
        "photograph on a plain neutral background, sharp focus, true gemstone "
        "colors, realistic metal, no text or watermark."
    )


def generate_concept(brief: str, model: str = "grok_direct",
                     variant: int = 0) -> tuple[bytes, bool]:
    """Grok invents a brand-new design from the brief. Returns (bytes, cached).
    variant>0 asks for a fresh take when the designer wants to regenerate rather
    than re-see the first concept for this brief."""
    return generate_image(concept_prompt(brief), model=model, variant=variant)


_READ_SYSTEM = """\
You identify one piece of fine jewelry from an image for a manufacturing platform.
Report ONLY what you can see, using these controlled-vocabulary ids:

species (pick one): {species}
cut (pick one): {cuts}
metal_material (pick one): {metals}
setting_style (pick one): bezel, semi_bezel, prong_4, prong_6, v_prong, tension

Return a JSON object exactly matching:
{{"jewelry_type": "ring"|"pendant"|"earring", "halo": true|false,
  "species": id, "cut": id, "center_length_mm": number, "center_width_mm": number,
  "metal_material": id, "metal_color": "yellow"|"white"|"rose"|null,
  "setting_style": id}}

center_length_mm/center_width_mm are your best estimate of the main stone in
millimetres (a typical cocktail-ring centre is 8-13 mm). halo=true only if a
ring of small stones encircles the centre. setting_style is how the centre
stone is held: 'bezel' if a continuous metal rim wraps the whole girdle,
'semi_bezel' if metal wraps only two sides, otherwise the claw count you see
(prong_4 / prong_6). metal_color is null for platinum or silver. Output ONLY
the JSON."""


def read_design(image_bytes: bytes, brief: str = "",
                vocab: Vocabulary | None = None) -> DesignRead:
    """Vision reads the concept into a sparse, controlled-vocabulary spec.
    Uses xAI (Grok) vision by default; falls back to Claude if configured."""
    import base64

    vocab = vocab or get_vocabulary()
    system = _READ_SYSTEM.format(
        species=", ".join(vocab.species_ids()),
        cuts=", ".join(vocab.cut_ids()),
        metals=", ".join(m["id"] for m in vocab.metals()))
    b64 = base64.b64encode(image_bytes).decode()
    media = "image/jpeg" if image_bytes[:3] == b"\xff\xd8\xff" else "image/png"

    key = _provider_key("XAI_KEY")
    if not key:
        raise RenderUnavailable(
            "no XAI_KEY configured — concept reading needs a vision key")

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
                        {"type": "text", "text": f"Brief: {brief or 'fine jewelry'}"},
                    ]},
                ],
                "response_format": {"type": "json_object"},
            })
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
    except Exception as exc:
        raise RenderUnavailable(f"vision read failed: {exc}") from exc
    return DesignRead.model_validate(json.loads(content))


def _provider_key(env: str) -> str | None:
    from facetta.render import _provider_key as pk
    return pk(env)


def _round_stone(vocab: Vocabulary, species: str, cut: str, w: float, length: float,
                 depth: float) -> tuple[float, float]:
    """(carat, expected_carat) for a stone at these mm — carat is set to the
    density model's own answer, so it is physically consistent by construction."""
    sg = vocab.species(species).sg
    sf = vocab.cut(cut).shape_factor
    ct = round(length * w * depth * sg * sf / 200, 3)
    return ct, ct


def complete_design(read: DesignRead, brief: str = "",
                    vocab: Vocabulary | None = None) -> tuple[Spec, list[str]]:
    """Turn a sparse vision read into a spec that PASSES every real-jewelry
    rule, recording each correction. This is the validator acting as the
    jeweler: measurements land in the right places and nothing impossible ships.
    """
    vocab = vocab or get_vocabulary()
    corrections: list[str] = []

    cut = _CUT_MAP.get(read.cut, read.cut)
    if cut not in ("round_brilliant", "oval_brilliant", "emerald_cut", "cushion"):
        corrections.append(f"centre cut '{read.cut}' mapped to oval_brilliant for the sheet")
        cut = "oval_brilliant"
    elif cut != read.cut:
        corrections.append(f"centre cut '{read.cut}' read as {cut}")

    species = read.species if vocab.species(read.species) else "diamond"
    L = max(read.center_length_mm, read.center_width_mm)
    W = min(read.center_length_mm, read.center_width_mm)
    if cut in ("round_brilliant",):
        L = W = round((L + W) / 2, 1)  # a round is one diameter
    depth = round(W * _DEPTH_FRAC.get(cut, 0.63), 1)
    ct, _ = _round_stone(vocab, species, cut, W, L, depth)
    corrections.append(
        f"centre depth set to {depth} mm and {ct} ct to match {L}×{W} mm "
        f"at {species}'s density")

    # colour: the vocabulary's benchmark trade term for the species
    terms = vocab.trade_color_terms(species)
    color = (StoneColor(trade=terms[0].term, gia=terms[0].gia) if terms
             else StoneColor(trade=species.title(), gia="natural colour"))

    center = Stone(species=species, cut=cut, carat=ct,
                   dimensions_mm=StoneDimensions(length=L, width=W, depth=depth),
                   color=color, position="center")

    side_stones: list[Stone] = []
    template = "solitaire_prong"
    if read.halo:
        template = "halo_prong"
        mw = round(max(1.3, W * 0.22), 1)          # melee ~22% of the centre width
        md = round(mw * 0.61, 2)
        mct, _ = _round_stone(vocab, "diamond", "round_brilliant", mw, mw, md)
        dw = vocab.trade_color_terms("diamond")
        dcolor = StoneColor(trade="F", gia="colorless")
        melee = Stone(species="diamond", cut="round_brilliant", carat=max(mct, 0.001),
                      dimensions_mm=StoneDimensions(length=mw, width=mw, depth=md),
                      color=dcolor, count=8, position="halo")
        max_count, _ = _surround_fit(W / 2, L / 2, melee, STONE_GAP_MM, HALO_MARGIN_MM)
        melee.count = max(6, min(max_count, 24))
        corrections.append(
            f"halo sized to {melee.count} × ⌀{mw} mm diamonds — the most that "
            f"fit the {L}×{W} mm centre with real seats")
        side_stones.append(melee)

    material = read.metal_material if any(
        m["id"] == read.metal_material for m in vocab.metals()) else "platinum"
    if material == "gold":
        metal = Metal(material="gold", karat=18, color=read.metal_color or "yellow",
                      finish="high_polish")
    else:
        metal = Metal(material=material, finish="high_polish")

    # how the centre is held — read from the design, not assumed. A bezel stays
    # a bezel all the way to the sheet; only an unrecognised mount falls back to
    # a 4-prong basket, and that fallback is recorded like any other correction.
    style, prong_count = _SETTING_MAP.get(read.setting_style, (None, None))
    if style is None:
        style, prong_count = "4_prong_basket", 4
        corrections.append(
            f"setting '{read.setting_style}' not drawable yet — shown as a "
            "4-prong basket; confirm the mount with the designer")
    elif style != "4_prong_basket":
        corrections.append(f"centre held in a {style.replace('_', ' ')} setting")

    # gallery must clear the culet from the finger — the factory rule, up front
    min_rail = vocab.manufacturing_tolerances()["culet_to_finger_rail_mm"]
    gallery = round(0.71 * depth + min_rail + 0.05, 1)
    setting = Setting(style=style, prong_count=prong_count,
                      prong_tip_mm=0.9 if prong_count else None,
                      gallery_height_mm=gallery)
    band = Band(profile="comfort_fit", width_mm=2.2, thickness_mm=1.6)
    ring_size = RingSize(system="US", value=6.5, inner_diameter_mm=16.91)

    spec = Spec(
        schema_version=1, design_id="dsn_concept", version=1,
        created_by="usr_pending", created_at="1970-01-01T00:00:00Z",
        jewelry_type="ring", template=template, mode="pro",
        stone=center, side_stones=side_stones, metal=metal, setting=setting,
        band=band, ring_size=ring_size,
        notes_to_factory=(
            f"Concept originated by image generation from the brief: “{brief}”. "
            "All dimensions are density-consistent DRAFT proposals scaled from a "
            "vision estimate of the centre stone — the designer confirms exact "
            "millimetres before production."),
    )

    # safety net: apply any correction the validator still reports
    for _ in range(4):
        result = validate_spec(spec, vocab)
        if result.ok:
            break
        applied = _apply_corrections(spec, result.issues, corrections)
        if not applied:
            break
    return spec, corrections


def _apply_corrections(spec: Spec, issues, corrections: list[str]) -> bool:
    """Push the validator's `expected` values back into the spec. Returns
    True if anything changed."""
    changed = False
    for issue in issues:
        exp = issue.expected or {}
        if "min_gallery_height_mm" in exp and spec.setting:
            spec.setting.gallery_height_mm = exp["min_gallery_height_mm"]
            corrections.append(f"gallery raised to {exp['min_gallery_height_mm']} mm "
                               "to clear the culet")
            changed = True
        elif "expected_depth_mm" in exp:
            spec.stone.dimensions_mm.depth = exp["expected_depth_mm"]
            corrections.append(f"centre depth corrected to {exp['expected_depth_mm']} mm")
            changed = True
        elif "max_count" in exp and issue.loc and issue.loc[0] == "side_stones":
            i = issue.loc[1] if len(issue.loc) > 1 and isinstance(issue.loc[1], int) else 0
            spec.side_stones[i].count = exp["max_count"]
            corrections.append(f"halo count reduced to {exp['max_count']} to fit")
            changed = True
    return changed

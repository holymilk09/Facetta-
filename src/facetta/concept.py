"""Concept origination: Grok invents a design, Facetta makes it manufacturable.

The founder's test: let the image engine dream up an entirely new piece, then
have the platform do what a chat cannot — put REAL millimeters in the right
places, specify the metal, keep every profile consistent, and prove the whole
thing is physically buildable before it reaches a factory.

The division of labor is the same one the rest of the product runs on:
  invent the look        · Grok text-to-image (a brand-new design)
  read it into numbers   · configured vision (sparse controlled-vocabulary read)
  make it physically real · the validator + density model (this module)
  draw every profile      · deterministic code, all from the one spec

The vision read is only an estimate — a photo (or a dream) never carries exact
millimeters. complete_design() turns that estimate into a spec that PASSES the
same density, fit, and clearance rules as a hand-built one, recording every
correction it had to make. The engine imagines; the validator is the jeweler.
"""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict, model_validator

from facetta.image_agent.vision import configured_vision_json
from facetta.render import RenderUnavailable, generate_image
from facetta.spec import (
    Band, Chain, Drop, Metal, Pendant, RingSize, Setting, Spec, Stone, StoneColor,
    StoneDimensions,
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
    main_stone_count: int = 1
    main_stone_position: str = "center"
    accent_species: str | None = None
    accent_cut: str | None = None
    accent_count: int = 0
    chain_style: str | None = None


class _ProviderDesignRead(DesignRead):
    """Strict transport boundary for a model-produced visual read.

    ``DesignRead`` remains the sparse internal contract used by deterministic
    completion and tests. Provider JSON must additionally match the declared
    schema exactly; unknown fields are rejected rather than silently becoming
    specification authority.
    """

    model_config = ConfigDict(extra="forbid")

    # Provider Structured Outputs must emit the complete transport contract.
    # Optional visual facts are required keys whose value may be null; no
    # Pydantic defaults are exposed as unsupported JSON Schema defaults.
    jewelry_type: str
    halo: bool
    species: str
    cut: str
    center_length_mm: float
    center_width_mm: float
    metal_material: str
    metal_color: str | None
    setting_style: str
    main_stone_count: int
    main_stone_position: str
    accent_species: str | None
    accent_cut: str | None
    accent_count: int
    chain_style: str | None

    @model_validator(mode="after")
    def require_coherent_visible_inventory(self):
        if not (
            math.isfinite(self.center_length_mm)
            and math.isfinite(self.center_width_mm)
            and self.center_length_mm > 0
            and self.center_width_mm > 0
        ):
            raise ValueError("visible stone dimensions must be positive and finite")
        if not 1 <= self.main_stone_count <= 64:
            raise ValueError("visible main-stone count must be between 1 and 64")
        if not 0 <= self.accent_count <= 64:
            raise ValueError("visible accent count must be between 0 and 64")
        if self.accent_count and not (self.accent_species and self.accent_cut):
            raise ValueError(
                "a visible accent count requires accent species and cut"
            )
        return self


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
{{"jewelry_type": "ring"|"pendant"|"necklace"|"earring", "halo": true|false,
  "species": id, "cut": id, "center_length_mm": number, "center_width_mm": number,
  "metal_material": id, "metal_color": "yellow"|"white"|"rose"|null,
  "setting_style": id, "main_stone_count": integer,
  "main_stone_position": "center"|"halo"|"vine_leaves"|"stations"|"drop",
  "accent_species": id|null, "accent_cut": id|null,
  "accent_count": integer, "chain_style": "cable"|"curb"|"figaro"|"rope"|"snake"|null}}

First identify the jewelry category from the whole silhouette and honor an
explicit category in the designer brief when the image agrees. Never turn a
necklace, pendant chain, bracelet, or earring into a ring merely because it has
gemstones. center_length_mm/center_width_mm are your best estimate of ONE
representative main stone in millimetres. main_stone_count is the exact visible
count of that repeated main-stone group, not the total of all gems. Accent fields
describe one visually distinct secondary gemstone group; use null/0 when none
is visible. chain_style is only for a visible necklace/pendant carrier. halo=true only if a
ring of small stones encircles the centre. setting_style is how the centre
stone is held: 'bezel' if a continuous metal rim wraps the whole girdle,
'semi_bezel' if metal wraps only two sides, otherwise the claw count you see
(prong_4 / prong_6). metal_color is null for platinum or silver. Output ONLY
the JSON."""


def read_design(image_bytes: bytes, brief: str = "",
                vocab: Vocabulary | None = None) -> DesignRead:
    """Vision reads the concept into a sparse, controlled-vocabulary spec.
    Uses the configured vision reader; deterministic completion owns physical
    values. XAI remains primary when configured and OpenAI is the fallback only
    when XAI is absent."""

    vocab = vocab or get_vocabulary()
    system = _READ_SYSTEM.format(
        species=", ".join(vocab.species_ids()),
        cuts=", ".join(vocab.cut_ids()),
        metals=", ".join(m["id"] for m in vocab.metals()))
    try:
        payload = configured_vision_json(
            system,
            image_bytes,
            f"Brief: {brief or 'fine jewelry'}",
            _ProviderDesignRead.model_json_schema(),
        )
        read = _ProviderDesignRead.model_validate(payload)
    except RenderUnavailable:
        raise
    except Exception as exc:
        raise RenderUnavailable(
            f"vision read returned an invalid design contract: {exc}"
        ) from exc
    return DesignRead.model_validate(read.model_dump(mode="python"))


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
    if read.jewelry_type == "earring":
        return _complete_earring(read, brief, vocab)
    if read.jewelry_type == "necklace":
        return _complete_necklace(read, brief, vocab)
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
    else:
        # A ring reader reports one representative main stone plus the exact
        # visible count of that repeated group. Keep the representative as the
        # canonical center and preserve the remaining visible stones as one
        # side group instead of flattening a three-stone ring to a solitaire.
        main_count = max(1, min(int(read.main_stone_count), 64))
        if main_count > 1:
            repeated_side_count = main_count - 1
            side_stones.append(center.model_copy(update={
                "count": repeated_side_count,
                # Count is visible; exact shoulder construction is not. Keep a
                # generic side position until a designer confirms topology.
                "position": "side",
            }))
            corrections.append(
                f"visible main-stone inventory preserved as 1 center plus "
                f"{repeated_side_count} matching side stone"
                f"{'s' if repeated_side_count != 1 else ''}; dimensions remain "
                "reference estimates"
            )

        if read.accent_count > 0 and read.accent_species:
            accent_species = (
                read.accent_species
                if vocab.species(read.accent_species)
                else "diamond"
            )
            requested_accent_cut = read.accent_cut or "round_brilliant"
            accent_cut = _CUT_MAP.get(
                requested_accent_cut, requested_accent_cut,
            )
            if not vocab.cut(accent_cut):
                accent_cut = "round_brilliant"
            accent_count = max(1, min(int(read.accent_count), 64))
            # One image can establish the accent group's visible count, species,
            # cut family, and placement, but not production millimeters. Use a
            # conservative proportional draft solely so deterministic density
            # validation can run; photo_spec marks every resulting dimension as
            # estimated_from_reference before Starting Facts is returned.
            accent_length = max(1.0, round(L * 0.55, 1))
            accent_width = max(1.0, round(W * 0.55, 1))
            if accent_cut == "round_brilliant":
                accent_length = accent_width = round(
                    (accent_length + accent_width) / 2,
                    1,
                )
            accent_depth = round(
                accent_width * _DEPTH_FRAC.get(accent_cut, 0.63),
                1,
            )
            accent_carat, _ = _round_stone(
                vocab,
                accent_species,
                accent_cut,
                accent_width,
                accent_length,
                accent_depth,
            )
            side_stones.append(Stone(
                species=accent_species,
                cut=accent_cut,
                carat=max(accent_carat, 0.001),
                dimensions_mm=StoneDimensions(
                    length=accent_length,
                    width=accent_width,
                    depth=accent_depth,
                ),
                color=_species_color(vocab, accent_species),
                count=accent_count,
                position="side",
            ))
            corrections.append(
                f"visible accent inventory preserved as {accent_count} "
                f"{accent_cut} {accent_species} stone"
                f"{'s' if accent_count != 1 else ''}; proportional dimensions "
                "are draft estimates for designer review"
            )

        visible_stone_count = 1 + sum(stone.count for stone in side_stones)
        if visible_stone_count == 3:
            template = "three_stone_prong"
        elif visible_stone_count > 1:
            template = "multi_stone_prong"

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


def _complete_necklace(
    read: DesignRead,
    brief: str,
    vocab: Vocabulary,
) -> tuple[Spec, list[str]]:
    """Complete a visible pendant-necklace read without coercing it to a ring.

    Dimensions remain reviewable estimates. Chain manufacturing geometry and
    production references are deliberately absent until the designer supplies
    them, so this draft cannot become factory-ready by convention alone.
    """
    corrections: list[str] = []
    species = read.species if vocab.species(read.species) else "diamond"
    cut = read.cut if vocab.cut(read.cut) else _CUT_MAP.get(read.cut, "oval_brilliant")
    count = max(1, min(int(read.main_stone_count), 512))
    length = max(float(read.center_length_mm), float(read.center_width_mm))
    width = min(float(read.center_length_mm), float(read.center_width_mm))
    depth = round(width * _DEPTH_FRAC.get(cut, 0.60), 1)
    carat, _ = _round_stone(vocab, species, cut, width, length, depth)
    main = Stone(
        species=species,
        cut=cut,
        carat=max(carat, 0.001),
        dimensions_mm=StoneDimensions(
            length=length, width=width, depth=depth),
        color=_species_color(vocab, species),
        count=count,
        position=(read.main_stone_position or "pendant"),
    )
    corrections.append(
        f"main necklace group recorded as {count} {cut} {species} stones; "
        "all dimensions remain reference estimates"
    )

    side_stones: list[Stone] = []
    if read.accent_species and read.accent_count > 0:
        accent_species = (
            read.accent_species
            if vocab.species(read.accent_species) else "diamond"
        )
        accent_cut = (
            read.accent_cut
            if read.accent_cut and vocab.cut(read.accent_cut)
            else "round_brilliant"
        )
        accent_width = max(1.0, round(width * 0.28, 1))
        accent_depth = round(
            accent_width * _DEPTH_FRAC.get(accent_cut, 0.61), 2)
        accent_carat, _ = _round_stone(
            vocab,
            accent_species,
            accent_cut,
            accent_width,
            accent_width,
            accent_depth,
        )
        side_stones.append(Stone(
            species=accent_species,
            cut=accent_cut,
            carat=max(accent_carat, 0.001),
            dimensions_mm=StoneDimensions(
                length=accent_width,
                width=accent_width,
                depth=accent_depth,
            ),
            color=_species_color(vocab, accent_species),
            count=max(1, min(int(read.accent_count), 512)),
            position="vine_accents",
        ))

    material = read.metal_material if any(
        metal["id"] == read.metal_material for metal in vocab.metals()
    ) else "platinum"
    metal = (
        Metal(
            material="gold",
            karat=18,
            color=read.metal_color or "yellow",
            finish="high_polish",
        )
        if material == "gold"
        else Metal(material=material, finish="high_polish")
    )
    chain_styles = {str(item["id"]) for item in vocab.chain_styles()}
    chain_style = read.chain_style if read.chain_style in chain_styles else "cable"
    if chain_style != read.chain_style:
        corrections.append(
            "carrier chain style was not visually reliable and defaults to "
            "cable for designer correction"
        )
    spec = Spec(
        schema_version=1,
        design_id="dsn_concept",
        version=1,
        created_by="usr_pending",
        created_at="1970-01-01T00:00:00Z",
        jewelry_type="necklace",
        template="cluster_pendant",
        mode="pro",
        stone=main,
        side_stones=side_stones,
        setting=Setting(style="prong_cluster", prong_count=4, prong_tip_mm=0.8),
        metal=metal,
        pendant=Pendant(
            bail_inner_diameter_mm=3.0,
            bail_height_mm=5.0,
        ),
        chain=Chain(
            style=chain_style,
            length_mm=450.0,
            clasp="lobster",
        ),
        notes_to_factory=(
            f"Necklace draft read from visual reference: “{brief}”. Stone, "
            "pendant, chain length, clasp, setting, and all dimensions require "
            "designer review. Exact chain geometry, pendant connection, and a "
            "production reference remain intentionally unset."
        ),
    )
    return spec, corrections


def _species_color(vocab: Vocabulary, species: str) -> StoneColor:
    terms = vocab.trade_color_terms(species)
    if terms:
        return StoneColor(trade=terms[0].term, gia=terms[0].gia)
    return StoneColor(trade=species.title(), gia="natural colour")


def _complete_earring(read: DesignRead, brief: str,
                      vocab: Vocabulary) -> tuple[Spec, list[str]]:
    """Build an articulated drop earring from a sparse read — the vertical
    archetype. The read's centre becomes the marquise (or read) frame; a pavé
    halo, a nested pear drop, and a bezel accent are added on conventional
    proportions, every carat set by the density model so the whole piece is
    physically real. The designer confirms exact millimetres before production.
    """
    corrections: list[str] = []
    species = read.species if vocab.species(read.species) else "diamond"
    fcut = read.cut if vocab.cut(read.cut) else "marquise"
    if fcut != read.cut:
        corrections.append(f"frame cut '{read.cut}' read as {fcut}")

    L = max(read.center_length_mm, read.center_width_mm)
    W = min(read.center_length_mm, read.center_width_mm)
    fdepth = round(W * 0.60, 1)
    fct, _ = _round_stone(vocab, species, fcut, W, L, fdepth)
    frame = Stone(species=species, cut=fcut, carat=max(fct, 0.001),
                  dimensions_mm=StoneDimensions(length=L, width=W, depth=fdepth),
                  color=_species_color(vocab, species), count=1,
                  position="center", mount="prong_4")
    corrections.append(f"marquise frame set to {L}×{W}×{fdepth} mm, {fct} ct "
                       f"at {species}'s density")

    side: list[Stone] = []
    if read.halo:
        mw = round(max(1.2, W * 0.16), 1)
        md = round(mw * 0.61, 2)
        mct, _ = _round_stone(vocab, "diamond", "round_brilliant", mw, mw, md)
        per = math.pi * (3 * (L / 2 + W / 2)
                         - math.sqrt(max(0.0, (3 * L / 2 + W / 2) * (L / 2 + 3 * W / 2))))
        count = max(12, min(int(per / (mw + 0.4)), 40))
        side.append(Stone(species="diamond", cut="round_brilliant",
                          carat=max(mct, 0.001),
                          dimensions_mm=StoneDimensions(length=mw, width=mw, depth=md),
                          color=StoneColor(trade="F", gia="colorless"),
                          count=count, position="halo", mount="pave"))
        corrections.append(f"pavé halo sized to {count} × ⌀{mw} mm diamonds "
                           "around the frame")

    dl, dw = round(L * 0.5, 1), round(W * 0.55, 1)
    dd = round(dw * 0.60, 1)
    dcut = "pear" if vocab.cut("pear") else "oval_brilliant"
    dct, _ = _round_stone(vocab, species, dcut, dw, dl, dd)
    side.append(Stone(species=species, cut=dcut, carat=max(dct, 0.001),
                      dimensions_mm=StoneDimensions(length=dl, width=dw, depth=dd),
                      color=_species_color(vocab, species), count=1,
                      position="drop", mount="v_prong"))

    aw = round(max(1.6, W * 0.22), 1)
    ad = round(aw * 0.60, 2)
    act, _ = _round_stone(vocab, "diamond", "round_brilliant", aw, aw, ad)
    side.append(Stone(species="diamond", cut="round_brilliant", carat=max(act, 0.001),
                      dimensions_mm=StoneDimensions(length=aw, width=aw, depth=ad),
                      color=StoneColor(trade="F", gia="colorless"), count=1,
                      position="stations", mount="bezel"))

    material = read.metal_material if any(
        m["id"] == read.metal_material for m in vocab.metals()) else "gold"
    if material == "gold":
        metal = Metal(material="gold", karat=18, color=read.metal_color or "yellow",
                      finish="high_polish")
    else:
        metal = Metal(material=material, finish="high_polish")

    hook = 10.0
    link_count, link_pitch = 3, 2.4
    halo_extra = (side[0].dimensions_mm.width if read.halo else 0.0)
    overall = round(hook + link_count * link_pitch + 3 + L + 2 * halo_extra, 1)
    drop_section = Drop(hook_height_mm=hook, overall_length_mm=overall,
                        link_count=link_count, link_pitch_mm=link_pitch,
                        wall_mm=0.9, wire_mm=0.8)
    corrections.append(f"overall reach set to {overall} mm — hook, {link_count}-link "
                       "run, frame and halo stacked; designer confirms final length")

    spec = Spec(
        schema_version=1, design_id="dsn_concept", version=1,
        created_by="usr_pending", created_at="1970-01-01T00:00:00Z",
        jewelry_type="earring", template="deco_drop_earring", mode="pro",
        stone=frame, side_stones=side, metal=metal,
        setting=Setting(style="prong_4", prong_count=4, prong_tip_mm=0.9),
        drop=drop_section,
        notes_to_factory=(
            f"Concept originated by image generation from the brief: “{brief}”. "
            "Modular articulated drop — cast frame, hand-set pavé. All dimensions "
            "are density-consistent DRAFT proposals scaled from a vision estimate; "
            "the designer confirms exact millimetres before production."),
    )
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

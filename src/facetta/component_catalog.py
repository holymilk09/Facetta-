"""Deterministic component choices that compile to exact spec deltas.

A catalog option is more than display copy: it tells a category-aware image
plan which visual geometry to request, which component to isolate, which
factory fields it owns, and which facts must remain frozen.  Applying an
option is pure and never persists a version or calls an image provider.

Some designer choices are necessarily coupled.  For example, platinum clears
gold-only karat/color fields, a bezel clears prong fields, and changing a cut
factor changes the modeled carat for unchanged L x W x D.  Those coupled
assignments live here instead of being guessed by an image model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from facetta.estimate import estimate_carat
from facetta.dimension_provenance import is_dimension_path
from facetta.json_types import JsonObject, JsonValue
from facetta.spec import DimensionProvenance, Spec
from facetta.validation import RING_TEMPLATES, validate_spec
from facetta.vocabulary import TradeColorTerm, Vocabulary, get_vocabulary


ImageAgentCatalogStatus = Literal[
    "catalog_ready",
    "catalog_ready_category_pending",
]


class ComponentCatalogOption(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    display: str = Field(min_length=1)
    visual_geometry: tuple[str, ...] = Field(min_length=1)
    isolation_target: str = Field(min_length=1)
    frozen_facts: tuple[str, ...] = Field(min_length=1)
    factory_fields: dict[str, JsonValue]
    # Dynamic fields are still deterministic, but depend on existing exact
    # facts.  The result returns their concrete before/after values.
    derived_factory_fields: tuple[str, ...] = ()
    selection_requirements: tuple[str, ...] = ()


class CatalogSelectionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec: Spec
    spec_change: tuple[JsonObject, ...]
    isolation_target: str
    frozen_facts: tuple[str, ...]


@dataclass(frozen=True)
class ComponentCatalogDescriptor:
    display: str
    applicable_jewelry_types: tuple[str, ...]
    image_agent_status: ImageAgentCatalogStatus


class CatalogSelectionError(ValueError):
    def __init__(
        self,
        component_path: str,
        option_id: str,
        valid_options: tuple[str, ...],
        message: str | None = None,
    ) -> None:
        self.component_path = component_path
        self.option_id = option_id
        self.valid_options = valid_options
        super().__init__(message or (
            f"unknown option '{option_id}' for {component_path}; valid options: "
            + ", ".join(valid_options)
        ))


_CHAIN_ISOLATION = (
    "the complete visible chain-link run only, excluding the pendant, bail, "
    "stones, setting, and clasp"
)
_CHAIN_FROZEN = (
    "stone",
    "side_stones",
    "setting",
    "metal",
    "pendant",
    "chain.length_mm",
    "chain.clasp",
    "chain.pendant_connection",
)

_CENTER_CUT_ISOLATION = (
    "the center-stone body and its immediately touching seat or prong tips "
    "only; exclude side stones, halo, shoulders, shank, and all other metal"
)
_CENTER_CUT_FROZEN = (
    "stone.species",
    "stone.dimensions_mm",
    "stone.color",
    "stone.clarity",
    "stone.origin",
    "stone.treatment",
    "stone.orientation",
    # A new outline may require the existing claws/seat to move to valid
    # bearing points. Freeze the factory setting facts, not impossible pixel
    # coordinates from the old cut.
    "setting.style",
    "setting.prong_count",
    "setting.prong_tip_mm",
    "setting.gallery_height_mm",
    "side_stones",
    "metal",
    "band",
    "ring_size",
    "design_form",
)

# A quick gemstone selection is still a structural specification change.  The
# image agent may change the center gem's material and color appearance, but it
# must not redraw the cut outline, move the seat, or use a broad pixel color
# replacement that destroys facets and reflections.
_CENTER_STONE_COLOR_ISOLATION = (
    "the center-stone body only, preserving its dimensions, outline, cut, "
    "count, seat, and every surrounding component"
)
_CENTER_STONE_COLOR_FROZEN = (
    "stone.cut",
    "stone.dimensions_mm",
    "stone.count",
    "stone.position",
    "setting",
    "side_stones",
    "metal",
    "band",
    "ring_size",
    "design_form",
)

_METAL_ISOLATION = (
    "all visible metal surfaces of the ring, including shank, shoulders, "
    "gallery, and setting metal; exclude every gemstone"
)
_METAL_FROZEN = (
    "stone",
    "side_stones",
    "setting",
    "band.profile",
    "band.width_mm",
    "band.thickness_mm",
    "ring_size",
    "design_form",
)

_SETTING_ISOLATION = (
    "the center-stone holding structure only: claws or bezel rim, seats, and "
    "immediate basket; exclude the center stone body, side stones, shoulders, "
    "and lower shank"
)
_SETTING_FROZEN = (
    "stone",
    "side_stones",
    "metal",
    "band",
    "ring_size",
    "setting.gallery_height_mm",
    "design_form",
)
_PRONG_SETTING_FROZEN = _SETTING_FROZEN + ("setting.prong_tip_mm",)

_SUPPORTED_CENTER_CUTS = (
    "round_brilliant",
    "oval_brilliant",
    "emerald_cut",
    "cushion",
)
_CUT_GEOMETRY: dict[str, tuple[str, ...]] = {
    "round_brilliant": (
        "circular face-up outline with equal length and width",
        "radially symmetric brilliant faceting and a centered culet",
        "no clipped, pointed, or elongated corners",
    ),
    "oval_brilliant": (
        "elongated elliptical face-up outline with continuously curved ends",
        "bilaterally symmetric brilliant faceting along the long axis",
        "no corners, straight step-cut sides, or pointed tips",
    ),
    "emerald_cut": (
        "elongated rectangular outline with four clipped corners",
        "parallel concentric step facets and a broad open table",
        "straight sides; do not round into an oval or cushion",
    ),
    "cushion": (
        "soft square or rectangular pillow outline with rounded corners",
        "broad brilliant-style facets inside the unchanged bounding dimensions",
        "no sharp princess corners or straight emerald-cut steps",
    ),
}

# A six-claw basket is deliberately restricted to round/oval within this
# catalog.  Emerald/cushion six-prong layouts require a designer to specify
# exact corner/side placement.  Pear, marquise, princess, and other pointed
# shapes are omitted entirely until the spec represents V-prong/tip structure.
_SETTING_CUT_COMPATIBILITY: dict[str, tuple[str, ...]] = {
    "4_prong_basket": _SUPPORTED_CENTER_CUTS,
    "6_prong_basket": ("round_brilliant", "oval_brilliant"),
    "bezel": _SUPPORTED_CENTER_CUTS,
    "semi_bezel": _SUPPORTED_CENTER_CUTS,
}

_SETTING_OPTIONS: tuple[ComponentCatalogOption, ...] = (
    ComponentCatalogOption(
        id="4_prong_basket",
        display="4-prong basket",
        visual_geometry=(
            "exactly four distinct center-stone claws",
            "balanced opposing pairs at the stone's secure bearing points",
            "open basket with no continuous bezel rim",
        ),
        isolation_target=_SETTING_ISOLATION,
        frozen_facts=_PRONG_SETTING_FROZEN,
        factory_fields={
            "setting.style": "4_prong_basket",
            "setting.prong_count": 4,
        },
        selection_requirements=(
            "center cut is round_brilliant, oval_brilliant, emerald_cut, or cushion",
            "existing designer-confirmed setting.prong_tip_mm is preserved",
        ),
    ),
    ComponentCatalogOption(
        id="6_prong_basket",
        display="6-prong basket",
        visual_geometry=(
            "exactly six distinct center-stone claws",
            "evenly distributed secure bearing points around a round or oval girdle",
            "open basket with no continuous bezel rim",
        ),
        isolation_target=_SETTING_ISOLATION,
        frozen_facts=_PRONG_SETTING_FROZEN,
        factory_fields={
            "setting.style": "6_prong_basket",
            "setting.prong_count": 6,
        },
        selection_requirements=(
            "center cut is round_brilliant or oval_brilliant",
            "existing designer-confirmed setting.prong_tip_mm is preserved",
        ),
    ),
    ComponentCatalogOption(
        id="bezel",
        display="Full bezel",
        visual_geometry=(
            "one continuous metal rim around the complete center-stone girdle",
            "no center-stone claws or isolated prong tips",
            "even collar height following the exact stone outline",
        ),
        isolation_target=_SETTING_ISOLATION,
        frozen_facts=_SETTING_FROZEN,
        factory_fields={
            "setting.style": "bezel",
            "setting.prong_count": None,
            "setting.prong_tip_mm": None,
        },
        selection_requirements=(
            "center cut is supported by the current ring sheet",
        ),
    ),
    ComponentCatalogOption(
        id="semi_bezel",
        display="Semi-bezel",
        visual_geometry=(
            "two opposing metal arcs secure the center-stone girdle",
            "two open sides expose the girdle",
            "no isolated center-stone claws or full continuous rim",
        ),
        isolation_target=_SETTING_ISOLATION,
        frozen_facts=_SETTING_FROZEN,
        factory_fields={
            "setting.style": "semi_bezel",
            "setting.prong_count": None,
            "setting.prong_tip_mm": None,
        },
        selection_requirements=(
            "center cut is supported by the current ring sheet",
        ),
    ),
)

_CATALOG_DESCRIPTORS: dict[str, ComponentCatalogDescriptor] = {
    "chain.style": ComponentCatalogDescriptor(
        display="Chain type",
        applicable_jewelry_types=("necklace",),
        image_agent_status="catalog_ready",
    ),
    "stone.cut": ComponentCatalogDescriptor(
        display="Center stone cut / shape",
        applicable_jewelry_types=("ring",),
        image_agent_status="catalog_ready",
    ),
    "stone.color": ComponentCatalogDescriptor(
        display="Center stone species and color",
        applicable_jewelry_types=("ring",),
        image_agent_status="catalog_ready",
    ),
    "metal.material": ComponentCatalogDescriptor(
        display="Metal alloy",
        applicable_jewelry_types=("ring",),
        image_agent_status="catalog_ready",
    ),
    "metal.color": ComponentCatalogDescriptor(
        display="Gold color",
        applicable_jewelry_types=("ring",),
        image_agent_status="catalog_ready",
    ),
    "setting.style": ComponentCatalogDescriptor(
        display="Center setting",
        applicable_jewelry_types=("ring",),
        image_agent_status="catalog_ready",
    ),
}


def component_catalog_paths() -> tuple[str, ...]:
    return tuple(_CATALOG_DESCRIPTORS)


def get_component_catalog_descriptor(
    component_path: str,
) -> ComponentCatalogDescriptor:
    descriptor = _CATALOG_DESCRIPTORS.get(component_path)
    if descriptor is None:
        raise CatalogSelectionError(
            component_path,
            option_id="",
            valid_options=component_catalog_paths(),
            message=f"unknown component catalog '{component_path}'",
        )
    return descriptor


def _chain_style_catalog(vocab: Vocabulary) -> tuple[ComponentCatalogOption, ...]:
    return tuple(
        ComponentCatalogOption(
            id=str(entry["id"]),
            display=str(entry["display"]),
            visual_geometry=tuple(str(item) for item in entry["visual_geometry"]),
            isolation_target=_CHAIN_ISOLATION,
            frozen_facts=_CHAIN_FROZEN,
            factory_fields={"chain.style": str(entry["id"])},
            selection_requirements=(
                "designer-confirmed target geometry matching the selected "
                "open-link, stranded, or smooth-plate construction family",
                "exact target supplier SKU, approved sample, dimensioned "
                "drawing, or CAD record; never reuse a source-style stock item",
            ),
        )
        for entry in vocab.chain_styles()
    )


def _center_cut_catalog(vocab: Vocabulary) -> tuple[ComponentCatalogOption, ...]:
    options: list[ComponentCatalogOption] = []
    for cut_id in _SUPPORTED_CENTER_CUTS:
        cut = vocab.cut(cut_id)
        if cut is None:
            continue
        compatible = tuple(
            setting for setting, cuts in _SETTING_CUT_COMPATIBILITY.items()
            if cut_id in cuts
        )
        options.append(ComponentCatalogOption(
            id=cut.id,
            display=cut.name,
            visual_geometry=_CUT_GEOMETRY[cut.id] + (
                "retain setting style, prong count, gauge, and gallery height; "
                "move only the existing contact points required to secure the new outline",
            ),
            isolation_target=_CENTER_CUT_ISOLATION,
            frozen_facts=_CENTER_CUT_FROZEN,
            factory_fields={"stone.cut": cut.id},
            derived_factory_fields=("stone.carat",),
            selection_requirements=(
                "existing face-up length and width already describe this outline",
                "compatible center setting: " + ", ".join(compatible),
            ),
        ))
    return tuple(options)


def _stone_color_payload(term: TradeColorTerm) -> JsonObject:
    """Serialize the controlled color record owned by a catalog option."""
    # ``TradeColorTerm`` intentionally retains source-specific extras.  Only
    # fields represented by StoneColor belong in a DesignVersion.
    return {
        "trade": term.term,
        "gia": term.gia,
        "hue_code": term.extras.get("hue_code"),
        "tone": term.extras.get("tone"),
        "saturation": term.extras.get("saturation"),
    }


def _stone_color_catalog(
    vocab: Vocabulary,
    stone_species: str | None,
) -> tuple[ComponentCatalogOption, ...]:
    """Return the compact, species-scoped color palette for a center stone.

    The UI may let a designer browse species first, but a persisted revision
    always records the exact species *and* a controlled appearance direction
    together.  A bare species click would otherwise leave a false color claim
    in the immutable spec.
    """
    if stone_species is None or vocab.species(stone_species) is None:
        raise CatalogSelectionError(
            "stone.color",
            option_id="",
            valid_options=tuple(vocab.species_ids()),
            message=(
                "stone.color catalog selection requires a known center-stone "
                "species so Facetta can show its contextual color palette"
            ),
        )
    terms = vocab.trade_color_terms(stone_species)
    # Product palettes deliberately stay compact. The vocabulary entries are
    # ordered by the gemologist-curated quick choices; View All can be added
    # later without changing stored option semantics.
    if not terms:
        raise CatalogSelectionError(
            "stone.color",
            option_id="",
            valid_options=(),
            message=(
                f"stone.color palette for {stone_species} has no controlled "
                "color choices yet"
            ),
        )
    return tuple(
        ComponentCatalogOption(
            # The trade term is the stable data vocabulary id within the
            # species-scoped request, not an image-model instruction.
            id=term.term,
            display=term.term,
            visual_geometry=(
                f"center stone reads as {term.term}: {term.gia}",
                "retain photoreal facet structure, internal reflections, "
                "polish, and lighting rather than flat-filling the gemstone",
                "do not alter the stone outline, cut pattern, count, seat, "
                "or any surrounding jewelry component",
            ),
            isolation_target=_CENTER_STONE_COLOR_ISOLATION,
            frozen_facts=_CENTER_STONE_COLOR_FROZEN,
            factory_fields={
                "stone.species": stone_species,
                "stone.color": _stone_color_payload(term),
            },
            derived_factory_fields=("stone.carat",),
            selection_requirements=(
                "species and color are selected together from the controlled "
                "gem vocabulary",
                "this is a design appearance direction, not a certification, "
                "origin, or treatment claim",
            ),
        )
        for term in terms[:7]
    )


def _metal_material_catalog(vocab: Vocabulary) -> tuple[ComponentCatalogOption, ...]:
    """Common complete alloy presets; never an under-specified bare 'gold'."""
    options: list[ComponentCatalogOption] = []
    gold = vocab.metal("gold")
    if gold is not None:
        # 14k and 18k are the common fine-jewelry ring alloys in the first
        # slice.  24k white/rose combinations are intentionally not generated
        # merely because the broad vocabulary lists gold colors.
        for karat in (14, 18):
            if karat not in gold["karats"]:
                continue
            for color in ("yellow", "white", "rose"):
                if color not in gold["colors"]:
                    continue
                options.append(ComponentCatalogOption(
                    id=f"gold_{karat}_{color}",
                    display=f"{karat}k {color.title()} Gold",
                    visual_geometry=(
                        f"all visible metal reads as {color} gold",
                        "uniform alloy appearance across shank, shoulders, gallery, and setting",
                        "highlights may vary with lighting but must not change ring geometry",
                    ),
                    isolation_target=_METAL_ISOLATION,
                    frozen_facts=_METAL_FROZEN,
                    factory_fields={
                        "metal.material": "gold",
                        "metal.karat": karat,
                        "metal.color": color,
                    },
                ))
    for material, display, appearance in (
        ("platinum", "Platinum", "cool neutral white platinum"),
        ("silver", "Silver", "bright cool white silver"),
    ):
        if vocab.metal(material) is None:
            continue
        options.append(ComponentCatalogOption(
            id=material,
            display=display,
            visual_geometry=(
                f"all visible metal reads as {appearance}",
                "uniform material appearance across shank, shoulders, gallery, and setting",
                "material identity remains a factory fact when pixels cannot distinguish white alloys",
            ),
            isolation_target=_METAL_ISOLATION,
            frozen_facts=_METAL_FROZEN,
            factory_fields={
                "metal.material": material,
                "metal.karat": None,
                "metal.color": None,
            },
        ))
    return tuple(options)


def _metal_color_catalog(vocab: Vocabulary) -> tuple[ComponentCatalogOption, ...]:
    gold = vocab.metal("gold")
    if gold is None:
        return ()
    geometry = {
        "yellow": "warm yellow-gold hue on every visible metal surface",
        "white": "cool white-gold appearance on every visible metal surface",
        "rose": "warm pink rose-gold hue on every visible metal surface",
    }
    return tuple(
        ComponentCatalogOption(
            id=color,
            display=f"{color.title()} Gold",
            visual_geometry=(
                geometry[color],
                "uniform color across shank, shoulders, gallery, and setting",
                "no change to polish, texture, dimensions, or component geometry",
            ),
            isolation_target=_METAL_ISOLATION,
            frozen_facts=_METAL_FROZEN + ("metal.material", "metal.karat", "metal.finish"),
            factory_fields={"metal.color": color},
            selection_requirements=("metal.material == gold",),
        )
        for color in ("yellow", "white", "rose")
        if color in gold["colors"]
    )


def get_component_catalog(
    component_path: str,
    *,
    vocabulary: Vocabulary | None = None,
    stone_species: str | None = None,
) -> tuple[ComponentCatalogOption, ...]:
    """Return typed options for one stable spec path."""
    vocab = vocabulary or get_vocabulary()
    get_component_catalog_descriptor(component_path)
    if component_path == "chain.style":
        return _chain_style_catalog(vocab)
    if component_path == "stone.cut":
        return _center_cut_catalog(vocab)
    if component_path == "stone.color":
        return _stone_color_catalog(vocab, stone_species)
    if component_path == "metal.material":
        return _metal_material_catalog(vocab)
    if component_path == "metal.color":
        return _metal_color_catalog(vocab)
    if component_path == "setting.style":
        return _SETTING_OPTIONS
    raise AssertionError(f"catalog descriptor has no compiler: {component_path}")


def _selection_error(
    component_path: str,
    option_id: str,
    options: tuple[ComponentCatalogOption, ...],
    message: str,
) -> CatalogSelectionError:
    return CatalogSelectionError(
        component_path,
        option_id,
        tuple(option.id for option in options),
        message=message,
    )


def _change(path: str, before: JsonValue, after: JsonValue, label: str) -> JsonObject:
    return {"path": path, "before": before, "after": after, "label": label}


def _setting_key(spec: Spec) -> str | None:
    setting = spec.setting
    if setting is None:
        return None
    if setting.style in {"bezel", "semi_bezel"} and setting.prong_count is None:
        return setting.style
    if setting.style == "4_prong_basket" and setting.prong_count == 4:
        return setting.style
    if setting.style == "6_prong_basket" and setting.prong_count == 6:
        return setting.style
    return None


def _require_ring_sections(
    spec: Spec,
    *,
    component_path: str,
    option_id: str,
    options: tuple[ComponentCatalogOption, ...],
) -> None:
    if (spec.jewelry_type != "ring" or spec.template not in RING_TEMPLATES
            or spec.metal is None or spec.setting is None):
        raise _selection_error(
            component_path,
            option_id,
            options,
            f"{component_path} catalog selection requires a mounted ring specification",
        )


def _validate_candidate(
    candidate: Spec,
    *,
    component_path: str,
    option_id: str,
    options: tuple[ComponentCatalogOption, ...],
    vocabulary: Vocabulary,
) -> None:
    result = validate_spec(candidate, vocabulary)
    if result.ok:
        return
    details = "; ".join(issue.msg for issue in result.issues)
    raise _selection_error(
        component_path,
        option_id,
        options,
        f"catalog selection does not compile to a valid specification: {details}",
    )


def _apply_chain_style(
    spec: Spec,
    option: ComponentCatalogOption,
    options: tuple[ComponentCatalogOption, ...],
    vocab: Vocabulary,
) -> tuple[Spec, tuple[JsonObject, ...]]:
    if spec.chain is None or spec.jewelry_type != "necklace":
        raise _selection_error(
            "chain.style",
            option.id,
            options,
            "chain.style catalog selection requires a necklace specification "
            "with a carrier-chain section",
        )
    before = spec.chain.style
    raw = spec.model_dump(mode="json")
    raw["chain"]["style"] = option.id
    selected = Spec.model_validate(raw)
    _validate_candidate(
        selected,
        component_path="chain.style",
        option_id=option.id,
        options=options,
        vocabulary=vocab,
    )
    changes = () if before == option.id else (
        _change("chain.style", before, option.id, "chain style"),
    )
    return selected, changes


def _apply_center_cut(
    spec: Spec,
    option: ComponentCatalogOption,
    options: tuple[ComponentCatalogOption, ...],
    vocab: Vocabulary,
) -> tuple[Spec, tuple[JsonObject, ...]]:
    _require_ring_sections(
        spec,
        component_path="stone.cut",
        option_id=option.id,
        options=options,
    )
    before_cut = spec.stone.cut
    if before_cut == option.id:
        return spec, ()
    setting = _setting_key(spec)
    compatible = tuple(
        setting_id
        for setting_id, cut_ids in _SETTING_CUT_COMPATIBILITY.items()
        if option.id in cut_ids
    )
    if setting not in compatible:
        raise _selection_error(
            "stone.cut",
            option.id,
            options,
            f"{option.id} requires one of these exact center settings before "
            f"the cut change: {', '.join(compatible)}",
        )

    dimensions = spec.stone.dimensions_mm
    ratio = max(dimensions.length, dimensions.width) / min(
        dimensions.length, dimensions.width)
    if option.id == "round_brilliant" and ratio > 1.05:
        raise _selection_error(
            "stone.cut",
            option.id,
            options,
            "round_brilliant needs equal face-up length and width; confirm a "
            "new diameter instead of letting the catalog guess it",
        )
    if option.id == "oval_brilliant" and ratio < 1.08:
        raise _selection_error(
            "stone.cut",
            option.id,
            options,
            "oval_brilliant needs an elongated face-up length/width pair; "
            "confirm those dimensions instead of letting the catalog guess them",
        )
    if option.id == "emerald_cut" and ratio < 1.08:
        raise _selection_error(
            "stone.cut",
            option.id,
            options,
            "emerald_cut needs a rectangular face-up length/width pair; "
            "choose asscher for a square step cut or confirm new dimensions",
        )

    before_carat = spec.stone.carat
    raw = spec.model_dump(mode="json")
    raw["stone"]["cut"] = option.id
    modeled = estimate_carat(
        vocab,
        spec.stone.species,
        option.id,
        dimensions.length,
        dimensions.width,
        dimensions.depth,
    )
    raw["stone"]["carat"] = modeled["carat"]
    selected = Spec.model_validate(raw)
    _validate_candidate(
        selected,
        component_path="stone.cut",
        option_id=option.id,
        options=options,
        vocabulary=vocab,
    )

    changes: list[JsonObject] = []
    if before_cut != option.id:
        changes.append(_change("stone.cut", before_cut, option.id, "center stone cut"))
    if before_carat != selected.stone.carat:
        changes.append(_change(
            "stone.carat",
            before_carat,
            selected.stone.carat,
            "modeled carat at unchanged dimensions",
        ))
    return selected, tuple(changes)


def _apply_center_stone_color(
    spec: Spec,
    option: ComponentCatalogOption,
    options: tuple[ComponentCatalogOption, ...],
    vocab: Vocabulary,
) -> tuple[Spec, tuple[JsonObject, ...]]:
    """Compile one species-scoped color choice into a complete spec delta."""
    _require_ring_sections(
        spec,
        component_path="stone.color",
        option_id=option.id,
        options=options,
    )
    target_species = option.factory_fields["stone.species"]
    target_color = option.factory_fields["stone.color"]
    assert isinstance(target_species, str)
    assert isinstance(target_color, dict)

    before = spec.stone
    raw = spec.model_dump(mode="json")
    stone = raw["stone"]
    assert isinstance(stone, dict)
    stone["species"] = target_species
    stone["color"] = target_color
    if before.species != target_species:
        # Species-specific grading, geographic, treatment, and phenomenon
        # records cannot survive a material swap. The designer can add them
        # back explicitly; the catalog never carries them over by appearance.
        stone["clarity"] = None
        stone["origin"] = None
        stone["treatment"] = None
        stone["phenomena"] = []
    dimensions = before.dimensions_mm
    modeled = estimate_carat(
        vocab,
        target_species,
        before.cut,
        dimensions.length,
        dimensions.width,
        dimensions.depth,
    )
    stone["carat"] = modeled["carat"]
    selected = Spec.model_validate(raw)
    _validate_candidate(
        selected,
        component_path="stone.color",
        option_id=option.id,
        options=options,
        vocabulary=vocab,
    )

    before_color = before.color.model_dump(mode="json")
    after_color = selected.stone.color.model_dump(mode="json")
    changes: list[JsonObject] = []
    for path, old, new, label in (
        ("stone.species", before.species, selected.stone.species,
         "center stone species"),
        ("stone.color", before_color, after_color, "center stone color"),
        ("stone.carat", before.carat, selected.stone.carat,
         "modeled carat at unchanged dimensions"),
        ("stone.clarity", (
            before.clarity.model_dump(mode="json") if before.clarity else None
        ), (
            selected.stone.clarity.model_dump(mode="json")
            if selected.stone.clarity else None
        ), "center stone clarity"),
        ("stone.origin", before.origin, selected.stone.origin,
         "center stone origin"),
        ("stone.treatment", before.treatment, selected.stone.treatment,
         "center stone treatment"),
        ("stone.phenomena", list(before.phenomena),
         list(selected.stone.phenomena), "center stone phenomena"),
    ):
        if old != new:
            changes.append(_change(path, old, new, label))
    return selected, tuple(changes)


def _apply_metal_material(
    spec: Spec,
    option: ComponentCatalogOption,
    options: tuple[ComponentCatalogOption, ...],
    vocab: Vocabulary,
) -> tuple[Spec, tuple[JsonObject, ...]]:
    _require_ring_sections(
        spec,
        component_path="metal.material",
        option_id=option.id,
        options=options,
    )
    assert spec.metal is not None
    raw = spec.model_dump(mode="json")
    before = {
        "metal.material": spec.metal.material,
        "metal.karat": spec.metal.karat,
        "metal.color": spec.metal.color,
    }
    for path, value in option.factory_fields.items():
        raw["metal"][path.removeprefix("metal.")] = value
    selected = Spec.model_validate(raw)
    _validate_candidate(
        selected,
        component_path="metal.material",
        option_id=option.id,
        options=options,
        vocabulary=vocab,
    )
    labels = {
        "metal.material": "metal material",
        "metal.karat": "metal karat",
        "metal.color": "metal color",
    }
    changes = tuple(
        _change(path, before[path], value, labels[path])
        for path, value in option.factory_fields.items()
        if before[path] != value
    )
    return selected, changes


def _apply_metal_color(
    spec: Spec,
    option: ComponentCatalogOption,
    options: tuple[ComponentCatalogOption, ...],
    vocab: Vocabulary,
) -> tuple[Spec, tuple[JsonObject, ...]]:
    _require_ring_sections(
        spec,
        component_path="metal.color",
        option_id=option.id,
        options=options,
    )
    assert spec.metal is not None
    if spec.metal.material != "gold":
        raise _selection_error(
            "metal.color",
            option.id,
            options,
            "metal.color selection applies only to gold; choose a complete "
            "metal.material alloy preset to change material",
        )
    before = spec.metal.color
    raw = spec.model_dump(mode="json")
    raw["metal"]["color"] = option.id
    selected = Spec.model_validate(raw)
    _validate_candidate(
        selected,
        component_path="metal.color",
        option_id=option.id,
        options=options,
        vocabulary=vocab,
    )
    changes = () if before == option.id else (
        _change("metal.color", before, option.id, "gold color"),
    )
    return selected, changes


def _apply_setting_style(
    spec: Spec,
    option: ComponentCatalogOption,
    options: tuple[ComponentCatalogOption, ...],
    vocab: Vocabulary,
) -> tuple[Spec, tuple[JsonObject, ...]]:
    _require_ring_sections(
        spec,
        component_path="setting.style",
        option_id=option.id,
        options=options,
    )
    assert spec.setting is not None
    compatible = _SETTING_CUT_COMPATIBILITY[option.id]
    if spec.stone.cut not in compatible:
        raise _selection_error(
            "setting.style",
            option.id,
            options,
            f"{option.id} is not an exact catalog setting for "
            f"{spec.stone.cut}; compatible cuts: {', '.join(compatible)}",
        )
    if (option.id in {"4_prong_basket", "6_prong_basket"}
            and spec.setting.prong_tip_mm is None):
        raise _selection_error(
            "setting.style",
            option.id,
            options,
            f"{option.id} requires a designer-confirmed prong-tip gauge; "
            "the catalog will not invent setting.prong_tip_mm",
        )

    raw = spec.model_dump(mode="json")
    before: dict[str, JsonValue] = {
        "setting.style": spec.setting.style,
        "setting.prong_count": spec.setting.prong_count,
        "setting.prong_tip_mm": spec.setting.prong_tip_mm,
    }
    for path, value in option.factory_fields.items():
        raw["setting"][path.removeprefix("setting.")] = value
    selected = Spec.model_validate(raw)
    _validate_candidate(
        selected,
        component_path="setting.style",
        option_id=option.id,
        options=options,
        vocabulary=vocab,
    )
    labels = {
        "setting.style": "center setting",
        "setting.prong_count": "center prong count",
        "setting.prong_tip_mm": "center prong tip",
    }
    changes = tuple(
        _change(path, before[path], value, labels[path])
        for path, value in option.factory_fields.items()
        if before[path] != value
    )
    return selected, changes


def apply_catalog_selection(
    spec: Spec,
    *,
    component_path: str,
    option_id: str,
    vocabulary: Vocabulary | None = None,
    stone_species: str | None = None,
) -> CatalogSelectionResult:
    """Apply one catalog choice and return its exact, validated spec delta."""
    vocab = vocabulary or get_vocabulary()
    # A species is a browsing context, not a loose image edit.  Falling back
    # to the active species supports same-species color swaps while a supplied
    # species atomically changes identity and color in one revision.
    palette_species = (
        stone_species or spec.stone.species
        if component_path == "stone.color" else None
    )
    options = get_component_catalog(
        component_path,
        vocabulary=vocab,
        stone_species=palette_species,
    )
    by_id = {option.id: option for option in options}
    option = by_id.get(option_id)
    if option is None:
        raise CatalogSelectionError(
            component_path,
            option_id,
            tuple(by_id),
        )

    if component_path == "chain.style":
        selected, changes = _apply_chain_style(spec, option, options, vocab)
    elif component_path == "stone.cut":
        selected, changes = _apply_center_cut(spec, option, options, vocab)
    elif component_path == "stone.color":
        selected, changes = _apply_center_stone_color(spec, option, options, vocab)
    elif component_path == "metal.material":
        selected, changes = _apply_metal_material(spec, option, options, vocab)
    elif component_path == "metal.color":
        selected, changes = _apply_metal_color(spec, option, options, vocab)
    elif component_path == "setting.style":
        selected, changes = _apply_setting_style(spec, option, options, vocab)
    else:
        raise AssertionError(f"catalog descriptor has no selector: {component_path}")

    # A catalog may clear a dimension-bearing field (for example a bezel has
    # no prong-tip gauge). Remove stale provenance with it. Numeric dimensions
    # explicitly owned by a selected catalog option are designer-confirmed
    # deterministic facts, never reference estimates.
    provenance = dict(selected.dimension_provenance)
    for path, value in option.factory_fields.items():
        if not is_dimension_path(path):
            continue
        if value is None:
            provenance.pop(path, None)
            continue
        provenance[path] = DimensionProvenance(
            status="designer_confirmed",
            method="designer_input",
            source=f"component catalog {component_path}:{option_id}",
            confidence=1.0,
            note="Designer selected this deterministic component option.",
        )
    selected = selected.model_copy(update={"dimension_provenance": provenance})

    return CatalogSelectionResult(
        spec=selected,
        spec_change=changes,
        isolation_target=option.isolation_target,
        frozen_facts=option.frozen_facts,
    )

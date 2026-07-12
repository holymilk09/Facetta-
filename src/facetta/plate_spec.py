"""Turn a Grok hand-plate read into a designer-reviewable draft ``Spec``.

The plate reader is deliberately descriptive: it can see several stone groups
and spatial relationships that the sparse photo reader cannot, but it cannot
prove a species, scale, or exact count from a drawing.  This module therefore
uses conservative, valid placeholders where the schema requires a value and
records every such placeholder in ``notes_to_factory``.  Nothing returned here
is factory truth until the designer confirms it.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from facetta.concept import _DEPTH_FRAC, _round_stone
from facetta.design_form import (
    DesignForm,
    DesignFormElement,
    DesignFormRegion,
    NormalizedPoint,
    NormalizedPolygon,
    VisualReferenceOnlyDefinition,
)
from facetta.dimension_provenance import with_reference_dimension_estimates
from facetta.spec import (
    Band, Chain, DimensionProvenance,
    Metal,
    Pendant,
    RingSize,
    Setting,
    Spec,
    Stone,
    StoneColor,
    StoneDimensions,
)
from facetta.source_component_coverage import (
    IndependentComponentAudit,
    SourceComponentCoverage,
    SourceVisibleComponent,
)
from facetta.vocabulary import Vocabulary, get_vocabulary


_CUT_WORDS = (
    ("emerald cut", "emerald_cut"),
    ("step cut", "emerald_cut"),
    ("square", "cushion"),
    ("cushion", "cushion"),
    ("round", "round_brilliant"),
    ("brilliant", "round_brilliant"),
    ("marquise", "marquise"),
    ("baguette", "baguette"),
    ("pear", "pear"),
    ("oval", "oval_brilliant"),
    ("cabochon", "cabochon"),
)

_DEFAULT_COLOR = StoneColor(trade="TBD", gia="TBD")

_SOURCE_VIEWS = {
    "plate_composite", "front", "top", "side", "three_quarter", "detail",
    "unspecified",
}
_GENERIC_COMPONENT_DESCRIPTIONS = {
    "", "tbd", "unknown", "unclear", "ambiguous", "stone", "stones",
    "component", "unreadable",
}
_UNREPRESENTED_ASSEMBLY_TERMS = (
    "art deco", "braid", "engraved", "filigree", "leaf", "motif",
    "organic", "sculpted", "scroll", "twist",
)


def _number_pair(value: str) -> tuple[float, float] | None:
    nums = re.findall(r"(?<![A-Za-z])\d+(?:[.,]\d+)?", value or "")
    if len(nums) < 2:
        return None
    try:
        return float(nums[0].replace(",", ".")), float(nums[1].replace(",", "."))
    except ValueError:
        return None


def _number(value: str) -> float | None:
    match = re.search(r"(?<![A-Za-z])\d+(?:[.,]\d+)?", value or "")
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", "."))
    except ValueError:
        return None


def _species(text: str, vocab: Vocabulary) -> str | None:
    lowered = text.lower()
    # longest names first, so smoky_quartz is not reduced to quartz/TBD
    for candidate in sorted(vocab.species_ids(), key=len, reverse=True):
        if candidate.replace("_", " ") in lowered or candidate in lowered:
            return candidate
    return None


def _cut(text: str) -> str:
    lowered = re.sub(r"[-_]+", " ", text.lower())
    for word, cut in _CUT_WORDS:
        if word in lowered:
            return cut
    return "round_brilliant"


def _explicit_prong_count(text: str) -> int | None:
    lowered = text.lower()
    numeric = re.search(r"\b([2-8])\s*[- ]?prong\b", lowered)
    if numeric:
        return int(numeric.group(1))
    for word, count in (("four", 4), ("six", 6)):
        if re.search(rf"\b{word}\s*[- ]?prong\b", lowered):
            return count
    return None


def _source_confidence(value: object) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _source_view(value: object) -> str:
    normalized = str(value or "plate_composite").strip().lower()
    normalized = normalized.replace("-", "_").replace(" ", "_")
    return normalized if normalized in _SOURCE_VIEWS else "unspecified"


def _independent_audit(
    read: dict,
    component_id: str,
) -> IndependentComponentAudit | None:
    audits = read.get("component_audits")
    if not isinstance(audits, dict):
        return None
    evidence = audits.get(component_id)
    if evidence is None:
        return None
    if not isinstance(evidence, dict):
        raise ValueError(
            f"component audit for {component_id!r} must be an object")
    return IndependentComponentAudit.model_validate(evidence)


def _component(
    read: dict,
    *,
    component_id: str,
    description: str,
    confidence: object,
    source_view: object = "plate_composite",
    paths: tuple[str, ...] = (),
    unresolved_reason: str | None = None,
) -> SourceVisibleComponent:
    return SourceVisibleComponent(
        component_id=component_id,
        source_view=_source_view(source_view),
        source_description=description.strip(),
        source_confidence=_source_confidence(confidence),
        canonical_spec_paths=paths,
        unresolved_reason=unresolved_reason,
        independent_audit=_independent_audit(read, component_id),
    )


def _stone_position(text: str) -> str:
    lowered = text.lower()
    if "leaf" in lowered and (
        "pav" in lowered or "diamond" in lowered or "stone" in lowered
    ):
        return "pave_leaves"
    if "halo" in lowered or "surround" in lowered:
        return "halo"
    if any(word in lowered for word in (
        "shoulder", "shank", "band", "pav",
    )):
        return "shoulder"
    if "under" in lowered or "gallery" in lowered:
        return "under_center"
    return "side"


def _stone_group_is_unresolved(group: dict, description: str) -> bool:
    status = str(group.get("status") or "").strip().lower()
    normalized = re.sub(r"[^a-z]+", " ", description.lower()).strip()
    return (
        status in {"ambiguous", "unresolved", "unreadable"}
        or normalized in _GENERIC_COMPONENT_DESCRIPTIONS
    )


def _assembly_stone_hints(
    assembly: str,
    represented_positions: set[str],
) -> tuple[tuple[str, str], ...]:
    """Find source-described stone groups omitted from the plate group list.

    This is intentionally conservative and only fires for a location plus a
    gem-bearing word.  It does not invent a species, count, or dimension.
    """

    lowered = assembly.lower()
    gem_word = any(word in lowered for word in (
        "diamond", "gem", "pavé", "pave", "stone", "ruby", "sapphire",
        "emerald",
    ))
    if not gem_word:
        return ()

    hints: list[tuple[str, str]] = []
    if any(word in lowered for word in ("halo", "surround")):
        if "halo" not in represented_positions:
            hints.append(("halo", "halo/surround stone group"))
    shoulder_stones_named = (
        any(word in lowered for word in ("leaf", "shoulder"))
        or bool(re.search(
            r"\b(?:pav[eé]|stone|diamond|gem)[- ](?:set )?(?:shank|band)\b",
            lowered,
        ))
        or bool(re.search(
            r"\b(?:shank|band)\b.{0,24}\b(?:pav[eé]|stone|diamond|gem)s?\b",
            lowered,
        ))
    )
    if shoulder_stones_named:
        if not represented_positions.intersection({"pave_leaves", "shoulder"}):
            hints.append(("shoulder", "gem-bearing shoulder/leaf stone group"))
    if any(word in lowered for word in ("under", "gallery")):
        if "under_center" not in represented_positions:
            hints.append(("under_center", "under-center/gallery stone group"))
    if any(word in lowered for word in ("side stone", "accent stone")):
        if not represented_positions.intersection({
            "side", "pave_leaves", "shoulder", "halo", "under_center",
        }):
            hints.append(("side", "side/accent stone group"))
    return tuple(hints)


def _compile_source_component_coverage(
    read: dict,
    *,
    groups: list[dict],
    invalid_groups: list[tuple[int, object]],
    positions: list[str],
) -> SourceComponentCoverage:
    components: list[SourceVisibleComponent] = []
    source_view = read.get("source_view") or "plate_composite"

    if groups:
        for index, group in enumerate(groups):
            component_id = "stone.center" if index == 0 else f"stone.group.{index:03d}"
            description = str(group.get("type") or "unresolved stone group").strip()
            if _stone_group_is_unresolved(group, description):
                components.append(_component(
                    read,
                    component_id=component_id,
                    description=description,
                    confidence=group.get("confidence"),
                    source_view=group.get("source_view") or source_view,
                    unresolved_reason=(
                        "The source reader did not identify this visible stone "
                        "group clearly enough to bind it to the compiled spec."
                    ),
                ))
            else:
                path = "stone" if index == 0 else f"side_stones[{index - 1}]"
                components.append(_component(
                    read,
                    component_id=component_id,
                    description=description,
                    confidence=group.get("confidence"),
                    source_view=group.get("source_view") or source_view,
                    paths=(path,),
                ))
    else:
        components.append(_component(
            read,
            component_id="stone.center",
            description="Center stone group was not returned by the plate reader.",
            confidence=0.0,
            source_view=source_view,
            unresolved_reason=(
                "No visible stone group was confidently read; the compiler's "
                "required center stone is only a placeholder."
            ),
        ))

    for sequence, (source_index, raw_group) in enumerate(invalid_groups, start=1):
        components.append(_component(
            read,
            component_id=f"stone.unparsed.{sequence:03d}",
            description=(
                f"Unparsed stone-group entry at source index {source_index}: "
                f"{str(raw_group)[:300]}"
            ),
            confidence=0.0,
            source_view=source_view,
            unresolved_reason=(
                "The source stone-group entry was not structured and was not "
                "silently discarded."
            ),
        ))

    assembly = str(read.get("assembly") or "").strip()
    if not assembly:
        components.append(_component(
            read,
            component_id="assembly.primary",
            description="Primary spatial assembly was not returned by the plate reader.",
            confidence=0.0,
            source_view=source_view,
            unresolved_reason=(
                "The spatial relationship among visible components is unknown."
            ),
        ))
    elif any(term in assembly.lower() for term in _UNREPRESENTED_ASSEMBLY_TERMS):
        components.append(_component(
            read,
            component_id="assembly.primary",
            description=assembly,
            confidence=read.get("assembly_confidence"),
            source_view=source_view,
            unresolved_reason=(
                "The assembly describes a visual form or motif that the sparse "
                "template path cannot fully define."
            ),
        ))
    else:
        components.append(_component(
            read,
            component_id="assembly.primary",
            description=assembly,
            confidence=read.get("assembly_confidence"),
            source_view=source_view,
            paths=("template",),
        ))

    represented_positions = set(positions[1:])
    for hint_id, hint_description in _assembly_stone_hints(
        assembly, represented_positions,
    ):
        components.append(_component(
            read,
            component_id=f"stone.assembly_hint.{hint_id}",
            description=f"Assembly source says: {assembly}",
            confidence=read.get("assembly_confidence"),
            source_view=source_view,
            unresolved_reason=(
                f"The assembly describes a {hint_description}, but the plate "
                "reader returned no distinct stone group for it."
            ),
        ))

    setting_is_explicit = bool(
        _explicit_prong_count(assembly) is not None
        or re.search(
            r"\b(?:bezel|basket|center setting|prong(?:ed)? setting)\b",
            assembly.lower(),
        )
    )
    components.append(_component(
        read,
        component_id="setting.primary",
        description=(assembly if assembly else
                     "Center setting structure was not returned by the plate reader."),
        confidence=read.get("assembly_confidence"),
        source_view=source_view,
        paths=("setting",) if setting_is_explicit else (),
        unresolved_reason=None if setting_is_explicit else (
            "The source does not explicitly establish the center setting; the "
            "compiled setting is a placeholder."
        ),
    ))

    raw_metal = str(read.get("metal") or "").strip()
    metal_known = raw_metal.lower() not in {
        "", "tbd", "unknown", "unclear", "ambiguous",
    }
    components.append(_component(
        read,
        component_id="metal.body",
        description=(raw_metal or "Metal was not returned by the plate reader."),
        confidence=read.get("metal_confidence"),
        source_view=source_view,
        paths=("metal",) if metal_known else (),
        unresolved_reason=None if metal_known else (
            "The visible body metal is missing or ambiguous; the compiled alloy "
            "is only a placeholder."
        ),
    ))

    confirmed_band_measurements = [
        measurement for measurement in (read.get("measurements") or [])
        if isinstance(measurement, dict)
        and measurement.get("status") == "designer_confirmed"
        and any(word in str(measurement.get("label") or "").lower()
                for word in ("band", "shank"))
    ]
    band_is_visible = bool(
        confirmed_band_measurements
        or any(word in assembly.lower() for word in (
            "ring", "band", "shank", "shoulder",
        ))
    )
    band_confidence = max(
        (_source_confidence(item.get("confidence"))
         for item in confirmed_band_measurements),
        default=_source_confidence(read.get("assembly_confidence")),
    )
    components.append(_component(
        read,
        component_id="band.shank",
        description=(
            str(confirmed_band_measurements[0].get("raw")
                or confirmed_band_measurements[0].get("value")
                or confirmed_band_measurements[0].get("label"))
            if confirmed_band_measurements else
            assembly if assembly else
            "Ring band/shank was not described by the plate reader."
        ),
        confidence=band_confidence,
        source_view=source_view,
        paths=("band",) if band_is_visible else (),
        unresolved_reason=None if band_is_visible else (
            "The source read does not explicitly account for the visible band "
            "or shank; compiled dimensions are placeholders."
        ),
    ))

    return SourceComponentCoverage(
        source_kind="designer_plate",
        components=tuple(components),
    )


def _metal(read: dict, notes: list[str]) -> Metal:
    raw = str(read.get("metal") or "").strip()
    lowered = raw.lower()
    material = "platinum" if "platinum" in lowered else "gold" if "gold" in lowered else "gold"
    if material == "gold":
        # Restrict the match to valid karats.  A handwritten "120 gold" is a
        # length/weight note, not a 120k alloy.
        match = re.search(r"\b(9|14|18|22|24)\s*k\b", lowered)
        karat = int(match.group(1)) if match else 18
        if not match:
            notes.append(f"metal karat is not explicit in '{raw or 'TBD'}'; using 18k placeholder")
        color = next((c for c in ("yellow", "white", "rose") if c in lowered), "yellow")
        if color == "yellow" and "white" not in lowered and "rose" not in lowered:
            notes.append("metal colour is a visual estimate; confirm yellow/white/rose")
        return Metal(material="gold", karat=karat, color=color, finish="high_polish")
    if material == "platinum":
        return Metal(material="platinum", finish="high_polish")
    return Metal(material="gold", karat=18, color="yellow", finish="high_polish")


def _metal_is_factory_specific(raw: str) -> bool:
    """Whether a plate names enough metal facts to bind the canonical spec.

    A visible "white metal" is a useful appearance read but it does not prove
    white gold, platinum, silver, or an alloy/purity. Gold additionally needs
    both a supported karat and colour before the compiler-created value stops
    being a placeholder.
    """

    lowered = raw.strip().lower()
    if not lowered or any(
        token in lowered for token in (" or ", "/", "unknown", "tbd")
    ):
        return False
    if "platinum" in lowered:
        return True
    if "gold" not in lowered:
        return False
    has_karat = re.search(r"\b(?:9|14|18|22|24)\s*k\b", lowered) is not None
    has_colour = any(colour in lowered for colour in ("yellow", "white", "rose"))
    return has_karat and has_colour


def _stone(
    text: str,
    *,
    count: int,
    position: str,
    vocab: Vocabulary,
    notes: list[str],
    center: bool = False,
) -> Stone:
    species = _species(text, vocab)
    if species is None:
        # The schema needs a vocabulary id, but this is explicitly marked as a
        # placeholder.  The designer must confirm species before approval.
        species = "diamond"
        notes.append(f"{position} stone species is not named; diamond is a placeholder")
    cut = _cut(text)
    pair = _number_pair(str(text))
    if pair is None:
        L = W = 8.0 if center else 2.0
        notes.append(f"{position} stone dimensions are not confirmed; using nominal {L:g} mm placeholder")
    else:
        L, W = max(pair), min(pair)
    if cut == "round_brilliant":
        L = W = round((L + W) / 2, 2)
    depth = round(W * _DEPTH_FRAC.get(cut, 0.63), 2)
    carat, _ = _round_stone(vocab, species, cut, W, L, depth)
    # Very small placeholder stones are valid but must remain positive.
    carat = max(carat, 0.001)
    terms = vocab.trade_color_terms(species)
    color = (StoneColor(trade=terms[0].term, gia=terms[0].gia)
             if terms else _DEFAULT_COLOR)
    if terms:
        notes.append(f"{position} stone colour is a visual estimate; confirm the trade colour")
    return Stone(
        species=species,
        cut=cut,
        carat=carat,
        dimensions_mm=StoneDimensions(length=L, width=W, depth=depth),
        color=color,
        count=max(1, min(64, count)),
        position=position,
    )


def _necklace_position(text: str) -> str:
    lowered = text.lower()
    if "pear" in lowered or "drop" in lowered or "pendant" in lowered:
        return "drop"
    if any(word in lowered for word in ("station", "link", "buff top")):
        return "stations"
    return "necklace_accents"


def _explicit_group_position(group: dict, fallback_description: str) -> str:
    """Keep a reader's physical role without allowing arbitrary noisy text.

    The value remains a descriptive spec position, not a manufacturing fact;
    it is especially useful for separating same-species necklace groups such
    as centre, inner-flanking, and outer-flanking pear drops.
    """

    raw = str(group.get("position") or "").strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
    if normalized:
        return normalized[:80]
    return _necklace_position(fallback_description)


def _source_group_description(group: dict, fallback: str) -> str:
    description = str(group.get("type") or fallback).strip()
    position = str(group.get("position") or "").strip()
    labels = group.get("written_labels")
    label_text = ""
    if isinstance(labels, list):
        clean = [str(label).strip() for label in labels if str(label).strip()]
        if clean:
            label_text = f"; nearby labels: {', '.join(clean)}"
    return f"{position}: {description}{label_text}" if position else (
        f"{description}{label_text}"
    )


def _necklace_visual_form(
    assembly: str,
    *,
    source_asset_id: str | None,
    source_asset_sha256: str | None,
) -> DesignForm:
    if source_asset_id is None or source_asset_sha256 is None:
        return DesignForm()
    return DesignForm(elements=(DesignFormElement(
        element_id="necklace_assembly",
        role="full_assembly",
        label="Complete necklace assembly",
        confirmed_form_description=(
            assembly
            or "Complete custom necklace silhouette from the designer plate."
        ),
        symmetry="asymmetric",
        instance_count=1,
        regions=(DesignFormRegion(
            view="plate_composite",
            polygons=(NormalizedPolygon(points=(
                NormalizedPoint(x=0.01, y=0.01),
                NormalizedPoint(x=0.99, y=0.01),
                NormalizedPoint(x=0.99, y=0.99),
                NormalizedPoint(x=0.01, y=0.99),
            )),),
        ),),
        definition=VisualReferenceOnlyDefinition(
            kind="visual_reference_only",
            asset_id=source_asset_id,
            asset_sha256=source_asset_sha256,
        ),
    ),))


def _compile_necklace_coverage(
    read: dict,
    *,
    groups: list[dict],
    invalid_groups: list[tuple[int, object]],
    has_visual_form: bool,
) -> SourceComponentCoverage:
    components: list[SourceVisibleComponent] = []
    source_view = read.get("source_view") or "plate_composite"
    for index, group in enumerate(groups):
        component_id = "stone.center" if index == 0 else f"stone.group.{index:03d}"
        description = _source_group_description(
            group, "unresolved stone group",
        )
        if _stone_group_is_unresolved(group, description):
            components.append(_component(
                read,
                component_id=component_id,
                description=description,
                confidence=group.get("confidence"),
                source_view=group.get("source_view") or source_view,
                unresolved_reason=(
                    "The source reader did not identify this necklace stone "
                    "group clearly enough to bind it to the compiled draft."
                ),
            ))
        else:
            components.append(_component(
                read,
                component_id=component_id,
                description=description,
                confidence=group.get("confidence"),
                source_view=group.get("source_view") or source_view,
                paths=("stone" if index == 0 else f"side_stones[{index - 1}]",),
            ))
    if not groups:
        components.append(_component(
            read,
            component_id="stone.center",
            description="No necklace stone group was confidently returned.",
            confidence=0.0,
            source_view=source_view,
            unresolved_reason="The required primary stone is only a placeholder.",
        ))
    for sequence, (source_index, raw_group) in enumerate(invalid_groups, start=1):
        components.append(_component(
            read,
            component_id=f"stone.unparsed.{sequence:03d}",
            description=(
                f"Unparsed necklace stone group at source index {source_index}: "
                f"{str(raw_group)[:300]}"
            ),
            confidence=0.0,
            source_view=source_view,
            unresolved_reason="The unstructured source group was not discarded.",
        ))

    assembly = str(read.get("assembly") or "").strip()
    group_text = " ".join(
        str(group.get("type") or "").lower() for group in groups
    )
    # The reader's assembly sentence is a second source channel. If it names a
    # major gem material that the structured groups omitted, retain that fact
    # as a blocker instead of silently producing an incomplete stone schedule.
    for species in ("diamond", "emerald", "ruby", "sapphire"):
        if species in assembly.lower() and species not in group_text:
            components.append(_component(
                read,
                component_id=f"stone.assembly_hint.{species}",
                description=(
                    f"Assembly names visible {species} stones: {assembly}"
                ),
                confidence=read.get("assembly_confidence"),
                source_view=source_view,
                unresolved_reason=(
                    f"The assembly describes visible {species} stones, but "
                    "the plate reader returned no distinct structured stone "
                    "group for the factory schedule."
                ),
            ))
    assembly_paths = (
        ("template", "design_form.elements[necklace_assembly]")
        if has_visual_form else ()
    )
    components.append(_component(
        read,
        component_id="assembly.primary",
        description=assembly or "Necklace assembly was not returned.",
        confidence=read.get("assembly_confidence"),
        source_view=source_view,
        paths=assembly_paths,
        unresolved_reason=None if assembly_paths else (
            "The custom necklace silhouette needs an exact pinned source "
            "before it can map to a stable design-form element."
        ),
    ))
    components.append(_component(
        read,
        component_id="assembly.pendant",
        description=assembly or "Front necklace drop assembly was not returned.",
        confidence=read.get("assembly_confidence"),
        source_view=source_view,
        paths=("pendant",) if assembly else (),
        unresolved_reason=None if assembly else (
            "The front drop/pendant relationship is unknown."
        ),
    ))

    setting_is_explicit = bool(re.search(
        r"\b(?:bezel|basket|prong|claw|channel|pav[eé])\b",
        assembly.lower(),
    ))
    components.append(_component(
        read,
        component_id="setting.primary",
        description=assembly or "Stone setting construction was not returned.",
        confidence=read.get("assembly_confidence"),
        source_view=source_view,
        paths=("setting",) if setting_is_explicit else (),
        unresolved_reason=None if setting_is_explicit else (
            "The plate does not explicitly establish the stone-setting "
            "construction; the compiled setting remains a placeholder."
        ),
    ))

    raw_metal = str(read.get("metal") or "").strip()
    metal_is_unambiguous = _metal_is_factory_specific(raw_metal)
    components.append(_component(
        read,
        component_id="metal.body",
        description=raw_metal or "Necklace metal was not returned.",
        confidence=read.get("metal_confidence"),
        source_view=source_view,
        paths=("metal",) if metal_is_unambiguous else (),
        unresolved_reason=None if metal_is_unambiguous else (
            "The plate does not establish one exact metal/alloy target."
        ),
    ))
    components.append(_component(
        read,
        component_id="assembly.chain",
        description=assembly or "Carrier construction was not returned.",
        confidence=read.get("assembly_confidence"),
        source_view=source_view,
        unresolved_reason=(
            "The visible collar/link construction is not a confirmed cable "
            "chain record; choose exact chain geometry and a production reference."
        ),
    ))
    return SourceComponentCoverage(
        source_kind="designer_plate",
        components=tuple(components),
    )


def _compile_necklace_plate_spec(
    read: dict,
    *,
    created_by: str,
    design_id: str,
    vocab: Vocabulary,
    source_asset_id: str | None,
    source_asset_sha256: str | None,
) -> tuple[Spec, list[str]]:
    notes: list[str] = [
        "DRAFT FROM NECKLACE DESIGN PLATE — written values without explicit "
        "units remain ambiguous; all estimates and placeholders require "
        "designer confirmation before factory release."
    ]
    raw_groups = list(read.get("stones") or [])
    source_groups = [group for group in raw_groups if isinstance(group, dict)]
    invalid_groups = [
        (index, group)
        for index, group in enumerate(raw_groups)
        if not isinstance(group, dict)
    ]
    groups = list(source_groups)
    if not groups:
        groups = [{"type": "necklace primary stone (species TBD)", "qty": 1}]
        notes.append("no necklace stone groups were confidently read")

    main_group = groups[0]
    try:
        main_count = max(1, int(main_group.get("qty") or 1))
    except (TypeError, ValueError):
        main_count = 1
        notes.append("primary necklace stone count is not confirmed")
    main = _stone(
        str(main_group.get("type") or "necklace primary stone"),
        count=main_count,
        position=_explicit_group_position(main_group, "drop"),
        vocab=vocab,
        notes=notes,
        center=True,
    )
    side_stones: list[Stone] = []
    for index, group in enumerate(groups[1:], start=1):
        description = str(group.get("type") or f"necklace stone group {index}")
        try:
            count = max(1, int(group.get("qty") or 1))
        except (TypeError, ValueError):
            count = 1
            notes.append(f"necklace stone group {index} count is not confirmed")
        side_stones.append(_stone(
            description,
            count=count,
            position=_explicit_group_position(group, description),
            vocab=vocab,
            notes=notes,
        ))
        qty_status = str(group.get("qty_status") or "").strip()
        if qty_status == "ambiguous":
            notes.append(
                f"necklace stone group {index} quantity is a conservative "
                "placeholder pending designer confirmation"
            )

    assembly = str(read.get("assembly") or "").strip()
    visual_form = _necklace_visual_form(
        assembly,
        source_asset_id=source_asset_id,
        source_asset_sha256=source_asset_sha256,
    )
    coverage = _compile_necklace_coverage(
        read,
        groups=source_groups,
        invalid_groups=invalid_groups,
        has_visual_form=bool(visual_form.elements),
    )
    for component in coverage.components:
        if component.unresolved_reason is not None:
            notes.append(
                f"SOURCE COMPONENT UNRESOLVED {component.component_id}: "
                + component.unresolved_reason
            )
    notes.append(
        "Exact collar/link geometry, chain production reference, attachment "
        "construction, stone seats, and all unlabelled dimensions remain open."
    )
    raw_measurements = [
        str(item.get("raw") or item.get("value") or item.get("label"))
        for item in (read.get("measurements") or [])
        if isinstance(item, dict)
    ]
    ambiguous = [value for value in raw_measurements if value and value != "None"]
    if ambiguous:
        notes.append(
            "Unassigned written values preserved for designer review: "
            + ", ".join(ambiguous)
        )

    spec = Spec(
        schema_version=1,
        design_id=design_id,
        version=1,
        created_by=created_by,
        created_at=datetime.now(timezone.utc),
        jewelry_type="necklace",
        template="cluster_pendant",
        mode="pro",
        stone=main,
        side_stones=side_stones,
        setting=Setting(
            style="prong_cluster",
            prong_count=4,
            prong_tip_mm=0.8,
        ),
        metal=_metal(read, notes),
        pendant=Pendant(
            bail_inner_diameter_mm=3.0,
            bail_height_mm=5.0,
        ),
        chain=Chain(
            style="cable",
            length_mm=450.0,
            clasp="lobster",
        ),
        design_form=visual_form,
        notes_to_factory=" ".join(notes),
        source_component_coverage=coverage,
    )
    spec = with_reference_dimension_estimates(
        spec,
        source="designer necklace drawing / design plate",
        method="scaled_reference" if read.get("scaled") else "reference_vision",
        confidence=0.55 if read.get("scaled") else 0.35,
    )
    return spec, notes


def compile_plate_spec(
    read: dict,
    *,
    created_by: str = "designer",
    design_id: str = "draft_plate",
    vocab: Vocabulary | None = None,
    source_asset_id: str | None = None,
    source_asset_sha256: str | None = None,
) -> tuple[Spec, list[str]]:
    """Compile a plate read into a valid ring/necklace review draft.

    Rings remain the first complete trusted category. Necklace plates preserve
    their custom full assembly as visual-only source truth and deliberately
    retain chain/setting/material ambiguities as factory blockers.
    """
    vocab = vocab or get_vocabulary()
    jewelry_type = str(read.get("jewelry_type") or "ring").lower()
    if jewelry_type in {"necklace", "necklaces"}:
        return _compile_necklace_plate_spec(
            read,
            created_by=created_by,
            design_id=design_id,
            vocab=vocab,
            source_asset_id=source_asset_id,
            source_asset_sha256=source_asset_sha256,
        )
    if jewelry_type not in {"ring", "rings"}:
        raise ValueError(
            "plate compiler currently supports rings and necklaces only "
            f"(got {jewelry_type})"
        )

    notes: list[str] = [
        "DRAFT FROM DESIGN PLATE — visual estimates and placeholders require designer confirmation before factory release."
    ]
    raw_groups = list(read.get("stones") or [])
    groups = [g for g in raw_groups if isinstance(g, dict)]
    invalid_groups = [
        (index, group) for index, group in enumerate(raw_groups)
        if not isinstance(group, dict)
    ]
    source_groups = list(groups)
    if not groups:
        groups = [{"type": "center stone (species TBD)", "qty": 1}]
        notes.append("no stone groups were confidently read from the plate")

    center_text = str(groups[0].get("type") or "center stone")
    center = _stone(center_text, count=1, position="center", vocab=vocab, notes=notes, center=True)
    side_stones: list[Stone] = []
    positions = ["center"]
    assembly_text = str(read.get("assembly") or "")
    assembly_lower = assembly_text.lower()
    for idx, group in enumerate(groups[1:], start=1):
        text = str(group.get("type") or f"side stone group {idx}")
        position = _stone_position(text)
        # Vision may put the location in the assembly sentence rather than in
        # the repeated stone-group label.  A single generic side group is safe
        # to bind to the one explicitly named surround/shoulder location; with
        # multiple generic groups we keep them unresolved as generic sides.
        if position == "side" and len(groups) == 2:
            if any(word in assembly_lower for word in ("halo", "surround")):
                position = "halo"
            elif any(word in assembly_lower for word in ("leaf", "shoulder")):
                position = "shoulder"
        positions.append(position)
        count = group.get("qty")
        try:
            count = int(count)
        except (TypeError, ValueError):
            count = 1
        if count <= 1:
            notes.append(f"{position} stone count is not confirmed; showing one representative stone")
        side_stones.append(_stone(text, count=count, position=position,
                                  vocab=vocab, notes=notes))

    assembly = assembly_lower
    explicit_prongs = _explicit_prong_count(assembly)
    prongs = explicit_prongs or 4
    if prongs not in {4, 6}:
        prongs = 4
    setting_style = "bezel" if "bezel" in assembly else f"{prongs}_prong_basket"
    if explicit_prongs is None and "bezel" not in assembly:
        notes.append("setting/prong count is not confirmed; using four-prong placeholder")

    metal = _metal(read, notes)
    confirmed_measurements = [
        m for m in (read.get("measurements") or [])
        if isinstance(m, dict) and m.get("status") == "designer_confirmed"
    ]
    band_width = 2.0
    band_width_confirmed = False
    for measurement in confirmed_measurements:
        label = str(measurement.get("label") or "").lower()
        value = _number(str(measurement.get("value") or ""))
        if value is not None and ("shank" in label or "band" in label):
            band_width = max(1.2, min(8.0, value))
            band_width_confirmed = True
            break
    else:
        notes.append("band width is not designer-confirmed; using 2.0 mm placeholder")

    # A plate rarely carries a ring size.  This is intentionally explicit and
    # easy to replace during confirmation, rather than pretending the drawing
    # establishes a finger size.
    notes.append("ring size is not established by the plate; using US 6.5 placeholder")
    source_component_coverage = _compile_source_component_coverage(
        read,
        groups=source_groups,
        invalid_groups=invalid_groups,
        positions=positions,
    )
    unresolved_components = [
        component for component in source_component_coverage.components
        if component.unresolved_reason is not None
    ]
    notes.extend(
        "SOURCE COMPONENT UNRESOLVED " + component.component_id + ": "
        + component.unresolved_reason
        for component in unresolved_components
    )
    unaudited_ids = [
        component.component_id
        for component in source_component_coverage.components
        if component.independent_audit is None
    ]
    if unaudited_ids:
        notes.append(
            "INDEPENDENT SOURCE-COVERAGE AUDIT REQUIRED before factory "
            "release: " + ", ".join(unaudited_ids)
        )
    spec = Spec(
        schema_version=1,
        design_id=design_id,
        version=1,
        created_by=created_by,
        created_at=datetime.now(timezone.utc),
        jewelry_type="ring",
        template=(
            "halo_prong" if any(s.position == "halo" for s in side_stones)
            else "leaf_shoulder_prong"
            if any(s.position == "pave_leaves" for s in side_stones)
            else "solitaire_prong"
        ),
        mode="pro",
        stone=center,
        setting=Setting(style=setting_style, prong_count=None if setting_style == "bezel" else prongs,
                         prong_tip_mm=0.9 if setting_style != "bezel" else None),
        metal=metal,
        band=Band(profile="half_round", width_mm=band_width, thickness_mm=1.6),
        ring_size=RingSize(system="US", value=6.5),
        side_stones=side_stones,
        notes_to_factory=" ".join(notes),
        source_component_coverage=source_component_coverage,
    )
    method = "scaled_reference" if read.get("scaled") else "reference_vision"
    spec = with_reference_dimension_estimates(
        spec,
        source="designer hand drawing / design plate",
        method=method,
        confidence=0.55 if read.get("scaled") else 0.4,
    )
    if band_width_confirmed:
        provenance = dict(spec.dimension_provenance)
        provenance["band.width_mm"] = DimensionProvenance(
            status="designer_confirmed",
            method="designer_input",
            source="designer-confirmed plate annotation",
            confidence=1.0,
            note="Preserved from the designer's written band/shank width.",
        )
        spec = spec.model_copy(update={"dimension_provenance": provenance})
    return spec, notes

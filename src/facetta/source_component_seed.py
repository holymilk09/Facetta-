"""Seed auditable component coverage for an imported jewelry photograph.

The primary photo reader produces a structured draft but can omit a visible
component. This module accounts for every component that *is* represented by
that draft using stable IDs and exact canonical paths. A later blind-first
audit is responsible for finding anything visible that the primary read
missed; seeding is not itself evidence that the mapping is correct.
"""

from __future__ import annotations

from facetta.source_component_coverage import (
    SourceComponentCoverage,
    SourceVisibleComponent,
)
from facetta.spec import Spec


def _stone_description(stone, *, label: str) -> str:
    count = stone.count
    position = stone.position or label
    return (
        f"{count} {stone.species} {stone.cut} stone"
        f"{'s' if count != 1 else ''} at {position}"
    )


def seed_imported_reference_coverage(
    spec: Spec,
    *,
    source_confidence: float = 0.45,
) -> SourceComponentCoverage:
    """Map represented draft components without claiming independent proof.

    Only existing canonical spec objects are named. No dimensions, CAD
    contours, or extra source components are invented here. Every returned
    component deliberately has ``independent_audit=None`` until the separate
    blind-first audit inspects the source bytes.
    """

    components: list[SourceVisibleComponent] = [
        SourceVisibleComponent(
            component_id="stone.center",
            source_view="unspecified",
            source_description=_stone_description(spec.stone, label="center"),
            source_confidence=source_confidence,
            canonical_spec_paths=("stone",),
        ),
    ]
    components.extend(
        SourceVisibleComponent(
            component_id=f"stone.group.{index + 1:03d}",
            source_view="unspecified",
            source_description=_stone_description(
                stone,
                label=f"side group {index + 1}",
            ),
            source_confidence=source_confidence,
            canonical_spec_paths=(f"side_stones[{index}]",),
        )
        for index, stone in enumerate(spec.side_stones)
    )

    if spec.setting is not None:
        setting_description = f"{spec.setting.style} setting"
        if spec.setting.prong_count is not None:
            setting_description += f" with {spec.setting.prong_count} prongs"
        components.append(SourceVisibleComponent(
            component_id="setting.primary",
            source_view="unspecified",
            source_description=setting_description,
            source_confidence=source_confidence,
            canonical_spec_paths=("setting",),
        ))

    if spec.metal is not None:
        metal_parts = [
            str(value)
            for value in (
                spec.metal.karat,
                spec.metal.color,
                spec.metal.material,
            )
            if value is not None and str(value).strip()
        ]
        components.append(SourceVisibleComponent(
            component_id="metal.body",
            source_view="unspecified",
            source_description=" ".join(metal_parts) + " metal body",
            source_confidence=source_confidence,
            canonical_spec_paths=("metal",),
        ))

    if spec.band is not None:
        components.append(SourceVisibleComponent(
            component_id="band.shank",
            source_view="unspecified",
            source_description=f"{spec.band.profile} ring shank",
            source_confidence=source_confidence,
            canonical_spec_paths=("band",),
        ))

    for section in (
        "bracelet",
        "pendant",
        "chain",
        "brooch",
        "drop",
        "composition",
    ):
        if getattr(spec, section) is None:
            continue
        components.append(SourceVisibleComponent(
            component_id=f"assembly.{section}",
            source_view="unspecified",
            source_description=f"structured {section} assembly",
            source_confidence=source_confidence,
            canonical_spec_paths=(section,),
        ))

    components.append(SourceVisibleComponent(
        component_id="assembly.primary",
        source_view="unspecified",
        source_description=f"{spec.template} primary assembly topology",
        source_confidence=source_confidence,
        canonical_spec_paths=("template",),
    ))

    components.extend(
        SourceVisibleComponent(
            component_id=f"form.{element.element_id}",
            source_view="unspecified",
            source_description=element.confirmed_form_description,
            source_confidence=source_confidence,
            canonical_spec_paths=(
                f"design_form.elements[{element.element_id}]",
            ),
        )
        for element in spec.design_form.elements
    )
    return SourceComponentCoverage(
        source_kind="imported_reference",
        components=tuple(components),
    )

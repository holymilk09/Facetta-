"""Structured, deterministic fact plan behind the factory sheet.

The existing SVG renderer remains the drawing engine.  This module makes the
facts feeding that drawing auditable: every material, stone group, setting,
and physical dimension is separated from presentation and carries a status.
Reference estimates never become measurements merely because a checklist was
completed.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

from facetta.dimension_provenance import (
    ESTIMATE_DISCLAIMER,
    is_dimension_path,
)
from facetta.spec import Spec, Stone


FactStatus = Literal[
    "designer_confirmed",
    "estimated_from_reference",
    "pending_confirmation",
]


class _PlanModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FactoryDimensionFact(_PlanModel):
    field_path: str
    section: str
    value: float
    unit: str
    status: FactStatus
    method: str | None = None
    source: str | None = None
    confidence: float | None = None
    note: str | None = None


class FactoryStoneScheduleRow(_PlanModel):
    ref: str
    section: str
    role: str
    species: str
    cut: str
    visible_color: str | None
    count: int
    carat_each: float
    carat_total: float
    fact_status: FactStatus
    dimension_paths: tuple[str, ...]


class FactoryMaterialScheduleRow(_PlanModel):
    section: Literal["metal"] = "metal"
    material: str
    karat: int | None
    color: str | None
    finish: str | None
    fact_status: FactStatus


class FactorySettingScheduleRow(_PlanModel):
    section: Literal["setting"] = "setting"
    style: str
    prong_count: int | None
    fact_status: FactStatus
    dimension_paths: tuple[str, ...]


class FactoryRecordedFact(_PlanModel):
    """Non-dimensional manufacturing fact that must survive sheet export."""

    field_path: str
    section: str
    label: str
    value: str
    fact_status: FactStatus


class FactorySheetFactPlan(_PlanModel):
    schema_version: Literal["facetta.factory-sheet-plan.v1"] = (
        "facetta.factory-sheet-plan.v1")
    jewelry_type: str
    template: str
    materials: tuple[FactoryMaterialScheduleRow, ...]
    stones: tuple[FactoryStoneScheduleRow, ...]
    settings: tuple[FactorySettingScheduleRow, ...]
    recorded_facts: tuple[FactoryRecordedFact, ...]
    dimensions: tuple[FactoryDimensionFact, ...]
    confirmed_fact_count: int
    estimated_fact_count: int
    pending_confirmation_count: int
    has_estimates: bool
    estimate_disclaimer: str | None


def pending_factory_fact_paths(plan: FactorySheetFactPlan) -> tuple[str, ...]:
    """Stable identifiers for every fact still lacking designer confirmation."""
    pending = [
        *(f"material:{index}" for index, item in enumerate(plan.materials)
          if item.fact_status == "pending_confirmation"),
        *(f"stone:{item.ref}" for item in plan.stones
          if item.fact_status == "pending_confirmation"),
        *(f"setting:{index}" for index, item in enumerate(plan.settings)
          if item.fact_status == "pending_confirmation"),
        *(item.field_path for item in plan.recorded_facts
          if item.fact_status == "pending_confirmation"),
        *(item.field_path for item in plan.dimensions
          if item.status == "pending_confirmation"),
    ]
    return tuple(dict.fromkeys(pending))


def _section(path: str) -> str:
    return "side_stones" if path.startswith("side_stones[") else path.split(".", 1)[0]


_PROFILE_PATH = re.compile(r"^design_form\.elements\[(\d+)\]\.definition\.")


def _profile_dimension_metadata(
    spec: Spec,
    path: str,
) -> tuple[FactStatus, str, str, str] | None:
    match = _PROFILE_PATH.match(path)
    if match is None:
        return None
    index = int(match.group(1))
    if index >= len(spec.design_form.elements):
        return None
    definition = spec.design_form.elements[index].definition
    if definition.kind != "dimensioned_profile":
        return None
    status: FactStatus = (
        "estimated_from_reference"
        if definition.dimension_status == "designer_confirmed_estimate"
        else "designer_confirmed"
    )
    return (
        status,
        "designer_confirmation",
        definition.source_asset_id,
        definition.manufacturing_notes,
    )


def _dimension_values(value: object, prefix: str = "") -> list[tuple[str, float]]:
    if isinstance(value, dict):
        out: list[tuple[str, float]] = []
        for key, child in value.items():
            if not prefix and key in {
                "dimension_provenance", "source_component_coverage",
            }:
                continue
            path = f"{prefix}.{key}" if prefix else key
            out.extend(_dimension_values(child, path))
        return out
    if isinstance(value, list):
        out = []
        for index, child in enumerate(value):
            out.extend(_dimension_values(child, f"{prefix}[{index}]"))
        return out
    if (isinstance(value, (int, float)) and not isinstance(value, bool)
            and is_dimension_path(prefix)):
        return [(prefix, float(value))]
    return []


def _status(
    spec: Spec,
    path_or_section: str,
    confirmed_sections: set[str],
) -> FactStatus:
    provenance = spec.dimension_provenance.get(path_or_section)
    if provenance is not None:
        return provenance.status
    profile = _profile_dimension_metadata(spec, path_or_section)
    if profile is not None:
        return profile[0]
    return (
        "designer_confirmed"
        if _section(path_or_section) in confirmed_sections
        else "pending_confirmation"
    )


def _stone_row(
    spec: Spec,
    stone: Stone,
    *,
    index: int | None,
    confirmed_sections: set[str],
) -> FactoryStoneScheduleRow:
    section = "stone" if index is None else "side_stones"
    prefix = "stone" if index is None else f"side_stones[{index}]"
    trade = stone.color.trade if stone.color is not None else None
    return FactoryStoneScheduleRow(
        ref="A" if index is None else chr(ord("B") + index),
        section=section,
        role="center" if index is None else (stone.position or f"group_{index + 1}"),
        species=stone.species,
        cut=stone.cut,
        visible_color=trade,
        count=stone.count,
        carat_each=stone.carat,
        carat_total=round(stone.carat * stone.count, 4),
        fact_status=(
            "designer_confirmed"
            if section in confirmed_sections else "pending_confirmation"
        ),
        dimension_paths=(
            f"{prefix}.dimensions_mm.length",
            f"{prefix}.dimensions_mm.width",
            f"{prefix}.dimensions_mm.depth",
        ),
    )


def _display(value: object) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:g}"
    if isinstance(value, list):
        return ", ".join(_display(item) for item in value)
    return str(value).replace("_", " ")


def _recorded_fact(
    spec: Spec,
    confirmed_sections: set[str],
    *,
    field_path: str,
    label: str,
    value: object | None,
    section: str | None = None,
    status: FactStatus | None = None,
) -> FactoryRecordedFact | None:
    if value is None or value == "" or value == []:
        return None
    resolved_section = section or _section(field_path)
    return FactoryRecordedFact(
        field_path=field_path,
        section=resolved_section,
        label=label,
        value=_display(value),
        fact_status=status or _status(spec, resolved_section, confirmed_sections),
    )


def _stone_recorded_facts(
    spec: Spec,
    stone: Stone,
    *,
    index: int | None,
    confirmed_sections: set[str],
) -> list[FactoryRecordedFact]:
    prefix = "stone" if index is None else f"side_stones[{index}]"
    section = "stone" if index is None else "side_stones"
    label_prefix = "Center" if index is None else f"Group {index + 1}"
    values: tuple[tuple[str, str, object | None], ...] = (
        ("mount", f"{label_prefix} mount", stone.mount),
        ("clarity.system", f"{label_prefix} clarity system",
         stone.clarity.system if stone.clarity else None),
        ("clarity.grade", f"{label_prefix} clarity grade",
         stone.clarity.grade if stone.clarity else None),
        ("clarity.eye_clean", f"{label_prefix} eye clean",
         stone.clarity.eye_clean if stone.clarity else None),
        ("origin", f"{label_prefix} origin", stone.origin),
        ("treatment", f"{label_prefix} treatment", stone.treatment),
        ("phenomena", f"{label_prefix} phenomena", stone.phenomena),
        ("table_pct", f"{label_prefix} table", (
            f"{stone.table_pct:g}%" if stone.table_pct is not None else None
        )),
        ("depth_pct", f"{label_prefix} depth", (
            f"{stone.depth_pct:g}%" if stone.depth_pct is not None else None
        )),
        ("girdle", f"{label_prefix} girdle", stone.girdle),
        ("culet", f"{label_prefix} culet", stone.culet),
        ("lab", f"{label_prefix} grading lab", stone.lab),
        ("inscription", f"{label_prefix} inscription", stone.inscription),
    )
    return [
        fact
        for suffix, label, value in values
        if (fact := _recorded_fact(
            spec,
            confirmed_sections,
            field_path=f"{prefix}.{suffix}",
            section=section,
            label=label,
            value=value,
        )) is not None
    ]


def _recorded_facts(
    spec: Spec,
    confirmed_sections: set[str],
) -> tuple[FactoryRecordedFact, ...]:
    candidates: list[FactoryRecordedFact | None] = [
        *_stone_recorded_facts(
            spec, spec.stone, index=None,
            confirmed_sections=confirmed_sections,
        ),
        *(
            fact
            for index, stone in enumerate(spec.side_stones)
            for fact in _stone_recorded_facts(
                spec, stone, index=index,
                confirmed_sections=confirmed_sections,
            )
        ),
        _recorded_fact(
            spec, confirmed_sections,
            field_path="band.profile", label="Band profile",
            value=spec.band.profile if spec.band else None,
        ),
        _recorded_fact(
            spec, confirmed_sections,
            field_path="ring_size.system", label="Ring-size system",
            value=spec.ring_size.system if spec.ring_size else None,
        ),
        _recorded_fact(
            spec, confirmed_sections,
            field_path="ring_size.value", label="Ring size",
            value=(spec.ring_size.value
                   if spec.ring_size and isinstance(spec.ring_size.value, str)
                   else None),
        ),
        _recorded_fact(
            spec, confirmed_sections,
            field_path="bracelet.link_count", label="Bracelet link count",
            value=spec.bracelet.link_count if spec.bracelet else None,
        ),
        _recorded_fact(
            spec, confirmed_sections,
            field_path="brooch.sweep_deg", label="Brooch sweep",
            value=(f"{spec.brooch.sweep_deg:g} degrees"
                   if spec.brooch and spec.brooch.sweep_deg is not None else None),
        ),
        _recorded_fact(
            spec, confirmed_sections,
            field_path="drop.link_count", label="Drop link count",
            value=spec.drop.link_count if spec.drop else None,
        ),
        _recorded_fact(
            spec, confirmed_sections,
            field_path="chain.style", label="Chain style",
            value=spec.chain.style if spec.chain else None,
        ),
        _recorded_fact(
            spec, confirmed_sections,
            field_path="chain.clasp", label="Clasp",
            value=spec.chain.clasp if spec.chain else None,
        ),
        _recorded_fact(
            spec, confirmed_sections,
            field_path="chain.pendant_connection", label="Pendant connection",
            value=spec.chain.pendant_connection if spec.chain else None,
        ),
        _recorded_fact(
            spec, confirmed_sections,
            field_path="chain.geometry.construction", label="Chain construction",
            value=(spec.chain.geometry.construction
                   if spec.chain and spec.chain.geometry else None),
        ),
        _recorded_fact(
            spec, confirmed_sections,
            field_path="chain.geometry.links_soldered", label="Links soldered",
            value=(spec.chain.geometry.links_soldered
                   if spec.chain and spec.chain.geometry
                   and spec.chain.geometry.construction == "open_link" else None),
        ),
        _recorded_fact(
            spec, confirmed_sections,
            field_path="chain.geometry.strand_count", label="Strand count",
            value=(spec.chain.geometry.strand_count
                   if spec.chain and spec.chain.geometry
                   and spec.chain.geometry.construction == "stranded" else None),
        ),
        _recorded_fact(
            spec, confirmed_sections,
            field_path="chain.production.mode", label="Chain production mode",
            value=(spec.chain.production.mode
                   if spec.chain and spec.chain.production else None),
        ),
        _recorded_fact(
            spec, confirmed_sections,
            field_path="chain.production.reference_kind",
            label="Chain production reference type",
            value=(spec.chain.production.reference_kind
                   if spec.chain and spec.chain.production else None),
        ),
        _recorded_fact(
            spec, confirmed_sections,
            field_path="chain.production.reference",
            label="Chain production reference",
            value=(spec.chain.production.reference
                   if spec.chain and spec.chain.production else None),
        ),
        _recorded_fact(
            spec, confirmed_sections,
            field_path="notes_to_factory", label="Factory instructions",
            value=spec.notes_to_factory,
            section="notes_to_factory",
        ),
    ]
    if spec.chain and spec.chain.geometry and spec.chain.geometry.construction == "open_link":
        candidates.extend(
            _recorded_fact(
                spec, confirmed_sections,
                field_path=f"chain.geometry.links[{index}].role",
                label=f"Chain link {index + 1} role",
                value=link.role,
            )
            for index, link in enumerate(spec.chain.geometry.links)
        )
    for index, element in enumerate(spec.design_form.elements):
        definition = element.definition
        element_status: FactStatus | None = None
        if (
            definition.kind == "dimensioned_profile"
            and definition.dimension_status == "designer_confirmed_estimate"
        ):
            element_status = "estimated_from_reference"
        candidates.extend((
            _recorded_fact(
                spec, confirmed_sections,
                field_path=f"design_form.elements[{index}].role",
                section="design_form", label=element.label,
                value=f"{element.role} · {definition.kind}",
                status=element_status,
            ),
            _recorded_fact(
                spec, confirmed_sections,
                field_path=f"design_form.elements[{index}].confirmed_form_description",
                section="design_form", label=f"{element.label} form",
                value=element.confirmed_form_description,
                status=element_status,
            ),
            _recorded_fact(
                spec, confirmed_sections,
                field_path=f"design_form.elements[{index}].definition.manufacturing_notes",
                section="design_form", label=f"{element.label} manufacturing notes",
                value=(definition.manufacturing_notes
                       if definition.kind == "dimensioned_profile" else None),
                status=element_status,
            ),
        ))
    return tuple(fact for fact in candidates if fact is not None)


def build_factory_sheet_fact_plan(
    spec: Spec,
    *,
    confirmed_sections: set[str] | None = None,
) -> FactorySheetFactPlan:
    """Compile the exact schedule used to explain one deterministic sheet."""
    confirmed = set(confirmed_sections or set())
    dimensions: list[FactoryDimensionFact] = []
    for path, value in sorted(_dimension_values(spec.model_dump(mode="json"))):
        provenance = spec.dimension_provenance.get(path)
        profile = _profile_dimension_metadata(spec, path)
        dimensions.append(FactoryDimensionFact(
            field_path=path,
            section=_section(path),
            value=value,
            unit=(spec.ring_size.system
                  if path == "ring_size.value" and spec.ring_size else "mm"),
            status=_status(spec, path, confirmed),
            method=(provenance.method if provenance else (
                profile[1] if profile else None
            )),
            source=(provenance.source if provenance else (
                profile[2] if profile else None
            )),
            confidence=provenance.confidence if provenance else None,
            note=(provenance.note if provenance else (
                profile[3] if profile else None
            )),
        ))

    stones = [
        _stone_row(spec, spec.stone, index=None, confirmed_sections=confirmed),
        *[
            _stone_row(spec, stone, index=index, confirmed_sections=confirmed)
            for index, stone in enumerate(spec.side_stones)
        ],
    ]
    materials = (() if spec.metal is None else (
        FactoryMaterialScheduleRow(
            material=spec.metal.material,
            karat=spec.metal.karat,
            color=spec.metal.color,
            finish=spec.metal.finish,
            fact_status=("designer_confirmed" if "metal" in confirmed
                         else "pending_confirmation"),
        ),
    ))
    settings = (() if spec.setting is None else (
        FactorySettingScheduleRow(
            style=spec.setting.style,
            prong_count=spec.setting.prong_count,
            fact_status=("designer_confirmed" if "setting" in confirmed
                         else "pending_confirmation"),
            dimension_paths=tuple(
                path for path in (
                    "setting.prong_tip_mm",
                    "setting.gallery_height_mm",
                )
                if any(item.field_path == path for item in dimensions)
            ),
        ),
    ))
    recorded_facts = _recorded_facts(spec, confirmed)
    statuses = [
        *(item.status for item in dimensions),
        *(item.fact_status for item in stones),
        *(item.fact_status for item in materials),
        *(item.fact_status for item in settings),
        *(item.fact_status for item in recorded_facts),
    ]
    estimated = statuses.count("estimated_from_reference")
    return FactorySheetFactPlan(
        jewelry_type=spec.jewelry_type,
        template=spec.template,
        materials=materials,
        stones=tuple(stones),
        settings=settings,
        recorded_facts=recorded_facts,
        dimensions=tuple(dimensions),
        confirmed_fact_count=statuses.count("designer_confirmed"),
        estimated_fact_count=estimated,
        pending_confirmation_count=statuses.count("pending_confirmation"),
        has_estimates=estimated > 0,
        estimate_disclaimer=ESTIMATE_DISCLAIMER if estimated else None,
    )

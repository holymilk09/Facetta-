"""Pydantic models for Design Spec Object — Schema v1 (docs/SPEC_SCHEMA.md).

All linear dimensions are mm, all weights are ct, stored as numbers, never
strings (strict types reject string-typed values). Vocabulary membership and
cross-field physical rules are enforced by facetta.validation, not here, so
the models stay vocabulary-agnostic and errors can carry valid-option lists.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Mm = Annotated[float, Field(strict=True, gt=0, description="Linear dimension in mm")]
Carat = Annotated[float, Field(strict=True, gt=0, description="Weight in ct")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StoneDimensions(StrictModel):
    length: Mm
    width: Mm
    depth: Mm


class StoneColor(StrictModel):
    trade: str
    gia: str
    hue_code: str | None = None
    tone: Annotated[int, Field(ge=0, le=10)] | None = None
    saturation: Annotated[int, Field(ge=1, le=6)] | None = None


class StoneClarity(StrictModel):
    system: str
    grade: str
    eye_clean: bool | None = None


class Stone(StrictModel):
    species: str
    cut: str
    carat: Carat  # per stone, when count > 1
    dimensions_mm: StoneDimensions
    color: StoneColor
    # design-first workflow: pieces are designed before stones are sourced, so
    # clarity is optional — absent means "best available, sourced on approval"
    clarity: StoneClarity | None = None
    origin: str | None = None
    treatment: str | None = None
    phenomena: list[str] = Field(default_factory=list)
    count: Annotated[int, Field(ge=1, le=64)] = 1
    position: str | None = None  # e.g. "halo", "stations", "under_center"
    # gem-ID proportions (loose stones / lab-report data)
    table_pct: Annotated[float, Field(ge=40, le=80)] | None = None
    depth_pct: Annotated[float, Field(ge=30, le=90)] | None = None
    girdle: str | None = None  # vocabulary girdle_thickness_scale word
    culet: str | None = None   # vocabulary culet_size_scale grade
    lab: str | None = None     # grading lab for the inscription (GIA, IGI, ...)
    inscription: Annotated[str, Field(min_length=1, max_length=24)] | None = None


class Setting(StrictModel):
    style: str
    prong_count: Annotated[int, Field(ge=2, le=8)] | None = None
    prong_tip_mm: Annotated[float, Field(strict=True, ge=0.6, le=1.5)] | None = None
    gallery_height_mm: Mm | None = None


class Metal(StrictModel):
    material: str
    karat: Annotated[int, Field(ge=1, le=24)] | None = None
    color: str | None = None
    finish: str | None = None


class Band(StrictModel):
    profile: str
    width_mm: Annotated[float, Field(strict=True, ge=1.2, le=8.0)]
    thickness_mm: Mm


class RingSize(StrictModel):
    system: Literal["US", "UK", "EU", "JP", "HK"]
    # UK sizes are letters ("M 1/2"); the other systems are numeric
    value: Annotated[float, Field(gt=0)] | Annotated[str, Field(min_length=1, max_length=8)]
    inner_diameter_mm: Mm | None = None


class Bracelet(StrictModel):
    """Oval bangle/cuff opening plus band cross-section."""

    inner_length_mm: Annotated[float, Field(strict=True, ge=40, le=75)]
    inner_width_mm: Annotated[float, Field(strict=True, ge=35, le=65)]
    width_mm: Annotated[float, Field(strict=True, ge=3.0, le=12.0)]
    thickness_mm: Annotated[float, Field(strict=True, ge=1.5, le=4.0)]
    gap_width_mm: Annotated[float, Field(strict=True, ge=15, le=40)] | None = None  # open cuff
    link_count: Annotated[int, Field(ge=4, le=60)] | None = None  # articulated bracelet


class Chain(StrictModel):
    style: str  # vocabulary findings.chain_styles id
    length_mm: Annotated[float, Field(strict=True, ge=300, le=900)]
    clasp: str  # vocabulary findings.clasp_types id


class Pendant(StrictModel):
    bail_inner_diameter_mm: Annotated[float, Field(strict=True, ge=1.5, le=10.0)]
    bail_height_mm: Mm
    drop_mm: Mm | None = None  # overall bail-top to lowest point; derived if absent


class Spec(StrictModel):
    schema_version: Literal[1]
    design_id: str
    version: Annotated[int, Field(ge=1)]
    created_by: str
    created_at: datetime
    jewelry_type: str
    template: str
    mode: Literal["basic", "pro"]
    stone: Stone
    setting: Setting | None = None  # loose stones carry no mount; required per-template
    metal: Metal | None = None
    band: Band | None = None
    ring_size: RingSize | None = None
    bracelet: Bracelet | None = None
    pendant: Pendant | None = None
    chain: Chain | None = None
    side_stones: list[Stone] = Field(default_factory=list)
    notes_to_factory: str | None = None

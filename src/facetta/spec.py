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
    carat: Carat
    dimensions_mm: StoneDimensions
    color: StoneColor
    clarity: StoneClarity
    origin: str | None = None
    treatment: str | None = None
    phenomena: list[str] = Field(default_factory=list)


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
    system: Literal["US"]
    value: Annotated[float, Field(gt=0)]
    inner_diameter_mm: Mm | None = None


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
    setting: Setting
    metal: Metal
    band: Band | None = None
    ring_size: RingSize | None = None
    side_stones: list[Stone] = Field(default_factory=list)
    notes_to_factory: str | None = None

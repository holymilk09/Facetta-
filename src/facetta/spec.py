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

from .design_form import DesignForm
from .source_component_coverage import SourceComponentCoverage

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
    # vocabulary setting_techniques id; absent = the position's default mount
    # (center → prongs, surround → shared prong, stations → flush, drop → cap)
    mount: str | None = None


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


class ChainLinkDimensions(StrictModel):
    """One repeat in an open-link chain, measured as a finished link.

    ``length_mm`` is the outside link length.  The inside dimensions describe
    the usable opening rather than asking a factory to reverse-engineer it
    from a generated image.  Figaro chains carry both a standard and a long
    repeat; the other first-slice open-link families carry one standard repeat.
    """

    role: Literal["standard", "long"] = "standard"
    length_mm: Annotated[float, Field(strict=True, ge=0.8, le=40.0)]
    inside_length_mm: Annotated[float, Field(strict=True, ge=0.2, le=35.0)]
    inside_width_mm: Annotated[float, Field(strict=True, ge=0.2, le=20.0)]


class OpenLinkChainGeometry(StrictModel):
    construction: Literal["open_link"]
    chain_width_mm: Annotated[float, Field(strict=True, ge=0.5, le=20.0)]
    profile_thickness_mm: Annotated[
        float, Field(strict=True, ge=0.2, le=12.0)
    ]
    end_ring_outer_diameter_mm: Annotated[
        float, Field(strict=True, ge=1.0, le=20.0)
    ]
    link_thickness_mm: Annotated[
        float, Field(strict=True, ge=0.15, le=6.0)
    ]
    links_soldered: bool
    links: Annotated[
        list[ChainLinkDimensions], Field(min_length=1, max_length=2)
    ]


class StrandedChainGeometry(StrictModel):
    """Overall and constituent dimensions for rope-like chain families.

    These values control the visual envelope but are not presented as a full
    fabrication recipe.  A stock/sample or CAD/dimensioned-drawing production
    reference remains mandatory at factory release.
    """

    construction: Literal["stranded"]
    chain_width_mm: Annotated[float, Field(strict=True, ge=0.5, le=20.0)]
    profile_thickness_mm: Annotated[
        float, Field(strict=True, ge=0.2, le=12.0)
    ]
    end_ring_outer_diameter_mm: Annotated[
        float, Field(strict=True, ge=1.0, le=20.0)
    ]
    strand_wire_diameter_mm: Annotated[
        float, Field(strict=True, ge=0.1, le=4.0)
    ]
    strand_count: Annotated[int, Field(ge=2, le=32)]


class SmoothChainGeometry(StrictModel):
    """Finished profile for plate-built smooth chains such as snake chain."""

    construction: Literal["smooth_plate"]
    chain_width_mm: Annotated[float, Field(strict=True, ge=0.5, le=20.0)]
    profile_thickness_mm: Annotated[
        float, Field(strict=True, ge=0.2, le=12.0)
    ]
    end_ring_outer_diameter_mm: Annotated[
        float, Field(strict=True, ge=1.0, le=20.0)
    ]
    plate_thickness_mm: Annotated[
        float, Field(strict=True, ge=0.05, le=3.0)
    ]


ChainGeometry = Annotated[
    OpenLinkChainGeometry | StrandedChainGeometry | SmoothChainGeometry,
    Field(discriminator="construction"),
]


class ChainProduction(StrictModel):
    """How the factory obtains the exact chain represented by the spec.

    A style name plus a few dimensions is not a complete rope/snake recipe.
    Stock chains therefore name a supplier/sample; custom chains name the
    dimensioned drawing or CAD record that is authoritative for construction.
    """

    mode: Literal["stock", "custom"]
    reference_kind: Literal[
        "supplier_sku", "approved_sample", "dimensioned_drawing", "cad_asset"
    ]
    reference: Annotated[str, Field(min_length=1, max_length=200)]


class Chain(StrictModel):
    style: str  # vocabulary findings.chain_styles id
    length_mm: Annotated[float, Field(strict=True, ge=300, le=900)]
    clasp: str  # vocabulary findings.clasp_types id
    # Additive and nullable so historical JSON remains readable.  New trusted
    # factory release requires both records through chain_factory_blockers().
    geometry: ChainGeometry | None = None
    production: ChainProduction | None = None
    # Whether the carrier must physically pass through the bail or is joined
    # at fixed points.  Bail-clearance validation is valid only for the first.
    pendant_connection: Literal[
        "slides_through_bail", "fixed_to_bail", "split_chain"
    ] | None = None


class Pendant(StrictModel):
    bail_inner_diameter_mm: Annotated[float, Field(strict=True, ge=1.5, le=10.0)]
    bail_height_mm: Mm
    drop_mm: Mm | None = None  # overall bail-top to lowest point; derived if absent


class Brooch(StrictModel):
    """Spray footprint: tip-to-catch reach, widest cross measure, and how far
    the plume sweeps — the composition is design data, not renderer taste."""

    length_mm: Annotated[float, Field(strict=True, ge=20, le=150)]
    width_mm: Annotated[float, Field(strict=True, ge=8, le=80)]
    sweep_deg: Annotated[float, Field(strict=True, ge=20, le=110)] | None = None


class Drop(StrictModel):
    """Articulated drop-earring construction: the ear hook, the link run that
    gives the piece movement, the overall reach, and the wall/wire gauges the
    design lives on. The frame, halo, drop, and accent STONES live in
    stone/side_stones; this section carries the metal architecture — everything
    a factory needs that isn't a gem. overall_length_mm is bail-top to the
    lowest point; the renderer stacks the parts to it and letters it."""

    hook_height_mm: Annotated[float, Field(strict=True, ge=5, le=20)]
    overall_length_mm: Annotated[float, Field(strict=True, ge=15, le=90)]
    link_count: Annotated[int, Field(ge=0, le=20)] = 0
    link_pitch_mm: Annotated[float, Field(strict=True, ge=0.8, le=6.0)] | None = None
    wall_mm: Annotated[float, Field(strict=True, ge=0.5, le=3.0)] | None = None
    wire_mm: Annotated[float, Field(strict=True, ge=0.5, le=2.0)] | None = None


class Composition(StrictModel):
    """Anchor geometry traced from the designer's own artwork (facetta.trace).

    Coordinates are normalized: the tip-most cluster center is (0, 0) and the
    piece's full drawn reach is 1.0, so the drawing's proportions scale to any
    length the designer sets. clusters carry [x, y, r] per cluster, tip first;
    vein carries [x, y] control points of the branch line. When present, the
    renderers anchor to these points instead of synthesizing a layout — the
    drawing's geometry, not the renderer's taste, decides the composition."""

    source: str | None = None  # e.g. "traced:IMG_5523.jpeg"
    clusters: list[Annotated[list[float], Field(min_length=3, max_length=3)]]
    vein: list[Annotated[list[float], Field(min_length=2, max_length=2)]] = Field(
        default_factory=list)


class DimensionProvenance(StrictModel):
    """How one numeric factory dimension entered the immutable record.

    The dictionary key on :class:`Spec` is the canonical dotted field path,
    for example ``stone.dimensions_mm.length`` or ``band.width_mm``.  An
    estimate is useful as a prototyping starting point, but is never silently
    promoted to a measured value.  A designer adjustment creates a new spec
    version with ``designer_confirmed`` provenance.
    """

    status: Literal["designer_confirmed", "estimated_from_reference"]
    method: Literal[
        "designer_input",
        "reference_vision",
        "scaled_reference",
        "nominal_reference",
    ]
    source: Annotated[str, Field(min_length=1, max_length=160)]
    confidence: Annotated[float, Field(ge=0, le=1)] | None = None
    note: Annotated[str, Field(max_length=500)] | None = None


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
    brooch: Brooch | None = None
    drop: Drop | None = None
    composition: Composition | None = None
    side_stones: list[Stone] = Field(default_factory=list)
    notes_to_factory: str | None = None
    dimension_provenance: dict[str, DimensionProvenance] = Field(
        default_factory=dict)
    design_form: DesignForm = Field(default_factory=DesignForm)
    # ``None`` means the immutable record predates explicit source-component
    # accounting.  New imported-source compilers attach a non-empty contract;
    # legacy database history remains readable without guessed backfills.
    source_component_coverage: SourceComponentCoverage | None = None

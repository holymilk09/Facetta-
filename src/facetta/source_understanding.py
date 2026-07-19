"""Typed, visible-only source understanding for pre-spec Studio Create.

This module deliberately stops at what one submitted image can establish.  It
does not create a specification, infer hidden construction, or turn model prose
into factory authority.  Its only purpose is to give the image generator and
its retry/QA loop the same deterministic preservation inventory.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from facetta.config import env_value
from facetta.image_agent.vision import openai_vision_json
from facetta.provider_errors import RenderUnavailable


SOURCE_UNDERSTANDING_VERSION = "source-visible-facts.v1"

CreativeSourceKind: TypeAlias = Literal[
    "drawing", "photograph", "finished_render"
]
VisibleJewelryCategory: TypeAlias = Literal[
    "ring",
    "necklace",
    "pendant",
    "bracelet",
    "earring",
    "brooch",
    "loose_stone",
    "other_jewelry",
    "unknown",
]


class _FrozenStrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class VisibleCenterStoneFacts(_FrozenStrictModel):
    """Only center-stone attributes assessable in the submitted view."""

    shape_or_cut_family: Annotated[
        str, Field(strict=True, min_length=1, max_length=80)
    ] | None = None
    visible_color: Annotated[
        str, Field(strict=True, min_length=1, max_length=80)
    ] | None = None

    @field_validator("shape_or_cut_family", "visible_color")
    @classmethod
    def require_trimmed_center_text(cls, value: str | None) -> str | None:
        if value is not None and value != value.strip():
            raise ValueError("visible center-stone text must be trimmed")
        return value


class VisibleSideStoneFacts(_FrozenStrictModel):
    """Counts are null unless the relevant side is actually assessable."""

    left_count: Annotated[int, Field(strict=True, ge=0, le=100)] | None = None
    right_count: Annotated[int, Field(strict=True, ge=0, le=100)] | None = None
    other_visible_count: Annotated[
        int, Field(strict=True, ge=0, le=200)
    ] | None = None
    shape_or_cut_family: Annotated[
        str, Field(strict=True, min_length=1, max_length=80)
    ] | None = None

    @field_validator("shape_or_cut_family")
    @classmethod
    def require_trimmed_side_text(cls, value: str | None) -> str | None:
        if value is not None and value != value.strip():
            raise ValueError("visible side-stone text must be trimmed")
        return value


class SourceVisibleFactsBrief(_FrozenStrictModel):
    """A deterministic preservation brief, never a product specification."""

    version: Literal["source-visible-facts.v1"] = SOURCE_UNDERSTANDING_VERSION
    source_kind: CreativeSourceKind
    category: VisibleJewelryCategory = "unknown"
    center_stone: VisibleCenterStoneFacts = Field(
        default_factory=VisibleCenterStoneFacts
    )
    visible_center_claw_or_prong_count: Annotated[
        int, Field(strict=True, ge=0, le=24)
    ] | None = None
    side_stones: VisibleSideStoneFacts = Field(
        default_factory=VisibleSideStoneFacts
    )
    repeated_motifs: tuple[
        Annotated[str, Field(strict=True, min_length=1, max_length=160)], ...
    ] = ()
    band_or_silhouette: Annotated[
        str, Field(strict=True, min_length=1, max_length=240)
    ] | None = None
    ambiguous_visible_details: tuple[
        Annotated[str, Field(strict=True, min_length=1, max_length=200)], ...
    ] = ()
    hidden_construction: Literal[
        "unknown_from_visible_source"
    ] = "unknown_from_visible_source"

    @field_validator(
        "band_or_silhouette",
        mode="after",
    )
    @classmethod
    def require_trimmed_optional_text(cls, value: str | None) -> str | None:
        if value is not None and value != value.strip():
            raise ValueError("visible-facts text must be trimmed")
        return value

    @field_validator("repeated_motifs", "ambiguous_visible_details")
    @classmethod
    def require_trimmed_unique_items(
        cls, value: tuple[str, ...]
    ) -> tuple[str, ...]:
        if any(item != item.strip() for item in value):
            raise ValueError("visible-facts list items must be trimmed")
        if len(set(value)) != len(value):
            raise ValueError("visible-facts list items must be unique")
        return value

    @model_validator(mode="after")
    def cap_advisory_lists(self) -> SourceVisibleFactsBrief:
        if len(self.repeated_motifs) > 12:
            raise ValueError("at most 12 repeated motifs may be recorded")
        if len(self.ambiguous_visible_details) > 12:
            raise ValueError("at most 12 ambiguous details may be recorded")
        return self


SourceUnderstandingInspector: TypeAlias = Callable[
    [bytes, CreativeSourceKind], SourceVisibleFactsBrief
]


_SOURCE_UNDERSTANDING_SYSTEM = """\
You inspect one designer-supplied jewelry source for preservation planning.
Return JSON only, with exactly this schema:
{
  "version": "source-visible-facts.v1",
  "source_kind": "drawing|photograph|finished_render",
  "category": "ring|necklace|pendant|bracelet|earring|brooch|loose_stone|other_jewelry|unknown",
  "center_stone": {
    "shape_or_cut_family": "short visible description"|null,
    "visible_color": "short visible color"|null
  },
  "visible_center_claw_or_prong_count": 0|null,
  "side_stones": {
    "left_count": 0|null,
    "right_count": 0|null,
    "other_visible_count": 0|null,
    "shape_or_cut_family": "short visible description"|null
  },
  "repeated_motifs": ["short visible motif with exact assessable count"],
  "band_or_silhouette": "short factual visible description"|null,
  "ambiguous_visible_details": ["specific visible ambiguity"],
  "hidden_construction": "unknown_from_visible_source"
}

Record only facts visible in this one image. Count only center-stone holding
claws/prongs that are separately visible and assessable; do not count side
stone claws, beads, reflections, gallery supports, labels, or decorative balls.
For side stones, count left and right independently and use null when an
occlusion prevents a reliable count. Do not identify a gemstone species from
color alone. Do not infer dimensions, carat, metal purity, hidden gallery,
underside, setting mechanics, manufacturability, or any off-frame component.
Keep hidden_construction exactly "unknown_from_visible_source". Source labels,
arrows, handwriting, captions, and dimension text are annotations, not jewelry
components. Do not judge source quality, skill, completeness, or attractiveness.
"""


_SOURCE_KIND_INSPECTION_GUIDANCE: dict[CreativeSourceKind, str] = {
    "drawing": (
        "The source is designer-declared DRAWING evidence. Treat drawn contours, "
        "color blocks, repeated marks, and explicit annotations as visual intent, "
        "but do not convert implied depth or unseen construction into facts."
    ),
    "photograph": (
        "The source is a designer-declared PHOTOGRAPH. Separate physical jewelry "
        "components from reflections, glare, shadows, perspective, fingers, props, "
        "and occlusion. Record only the jewelry form actually visible."
    ),
    "finished_render": (
        "The source is a designer-declared FINISHED RENDER. Preserve its visible "
        "design identity while treating idealized lighting, depth, and unseen "
        "construction as non-authoritative."
    ),
}


def conservative_source_visible_facts(
    _image_bytes: bytes,
    source_kind: CreativeSourceKind,
) -> SourceVisibleFactsBrief:
    """Return an honest all-unknown brief when no vision provider is available."""

    return SourceVisibleFactsBrief(source_kind=source_kind)


def requires_rough_drawing_interpretation(
    brief: SourceVisibleFactsBrief,
) -> bool:
    """Use best-effort interpretation for designer-declared drawings.

    Even a crude sketch can expose several coarse signals, while still being
    incapable of establishing literal prongs, motif topology, or faceting. A
    count-based confidence heuristic would therefore turn the most legible
    rough sketches back into strict pixel-fidelity edits. Photographs and
    finished renders remain strict. Exact technical-drawing fidelity, if added,
    must be an explicit future workflow rather than inferred from this upload.
    """

    return brief.source_kind == "drawing"


def compile_rough_drawing_intent_brief() -> str:
    """Keep a low-fidelity drawing usable without turning ambiguity into facts.

    Source understanding is an advisory preservation pass for Studio Create,
    not an authorization gate.  When that pass cannot produce a typed visible
    inventory, the exact drawing and the designer's sentence still carry valid
    creative intent.  This contract tells the image model how to use that
    intent while keeping every production claim explicitly out of scope.
    """

    return "\n".join((
        "ROUGH DRAWING INTENT FALLBACK (DESIGN INTENT ONLY; NOT A SPECIFICATION):",
        "- Treat the submitted drawing as the designer's visual intent even "
        "when its lines are loose, incomplete, faint, or not reliably countable.",
        "- Use the designer's written instruction to resolve ambiguous marks "
        "into one coherent fine-jewelry design direction.",
        "- Preserve the observable overall silhouette, center-element placement, "
        "side-element rhythm, and balance. Use professional jewelry judgment for "
        "loose or missing local geometry; do not demand literal pixel matching.",
        "- Do not require exact local contours, repeated-motif topology, prong "
        "counts, or stone cut identity unless the drawing or written direction "
        "actually establishes them.",
        "- Default to a balanced symmetric jewelry design unless the designer "
        "explicitly requests asymmetry or the drawing clearly establishes it.",
        "- Do not reject the source merely because it is an early sketch.",
        "- Do not infer dimensions, carat weights, metal purity, hidden construction, "
        "setting mechanics, manufacturability, or production readiness.",
        "- Produce a designer-review visualization, never a factory drawing or "
        "manufacturing specification.",
    ))


def inspect_source_visible_facts(
    image_bytes: bytes,
    source_kind: CreativeSourceKind,
) -> SourceVisibleFactsBrief:
    """Inspect one exact source once and validate its visible-only inventory."""

    try:
        payload = openai_vision_json(
            _SOURCE_UNDERSTANDING_SYSTEM,
            image_bytes,
            _SOURCE_KIND_INSPECTION_GUIDANCE[source_kind],
        )
        # The designer declaration controls source semantics. A model cannot
        # silently relabel the upload even if it returns a different value.
        payload = {**payload, "source_kind": source_kind}
        return SourceVisibleFactsBrief.model_validate(payload)
    except RenderUnavailable:
        raise
    except Exception as exc:
        raise RenderUnavailable(
            f"source visible-facts inspection was invalid: {exc}"
        ) from exc


def get_source_understanding_inspector() -> SourceUnderstandingInspector:
    """Use OpenAI when configured, otherwise preserve only explicit unknowns.

    Unit tests never make ambient provider calls; focused route tests override
    this dependency with a deterministic inspector. Local development without
    a vision key remains usable but gains no invented pixel claims.
    """

    if os.environ.get("FACETTA_ENV") == "test":
        return conservative_source_visible_facts
    if env_value("OPENAI_API_KEY"):
        return inspect_source_visible_facts
    return conservative_source_visible_facts


_SOURCE_KIND_RENDER_HANDLING: dict[CreativeSourceKind, str] = {
    "drawing": (
        "Translate the drawing into believable fine-jewelry material response "
        "while preserving every assessable drawn contour, count, placement, "
        "proportion, and repeated mark. Do not invent hidden construction."
    ),
    "photograph": (
        "Preserve the photographed jewelry's assessable physical design while "
        "treating reflections, glare, shadow, perspective, props, and occlusion "
        "as presentation evidence rather than components. Do not reconstruct "
        "unseen construction as fact."
    ),
    "finished_render": (
        "Preserve the finished render's visible design identity exactly. Improve "
        "presentation only as requested; do not reinterpret idealized pixels as "
        "dimensions, hidden construction, or permission to redesign."
    ),
}


def compile_source_preservation_brief(brief: SourceVisibleFactsBrief) -> str:
    """Compile typed facts in a fixed order for first and corrective prompts."""

    center_shape = brief.center_stone.shape_or_cut_family or "not assessable"
    center_color = brief.center_stone.visible_color or "not assessable"
    prongs = (
        f"exactly {brief.visible_center_claw_or_prong_count} separately visible"
        if brief.visible_center_claw_or_prong_count is not None
        else "not assessable from this view"
    )
    left = (
        str(brief.side_stones.left_count)
        if brief.side_stones.left_count is not None else "not assessable"
    )
    right = (
        str(brief.side_stones.right_count)
        if brief.side_stones.right_count is not None else "not assessable"
    )
    other = (
        str(brief.side_stones.other_visible_count)
        if brief.side_stones.other_visible_count is not None
        else "not assessable"
    )
    side_shape = brief.side_stones.shape_or_cut_family or "not assessable"
    motifs = "; ".join(brief.repeated_motifs) or "none assessable"
    silhouette = brief.band_or_silhouette or "not assessable"
    ambiguities = (
        "; ".join(brief.ambiguous_visible_details)
        or "none specifically recorded"
    )
    return "\n".join((
        "SOURCE PRESERVATION BRIEF source-visible-facts.v1 ",
        "(VISIBLE EVIDENCE ONLY; NOT A SPECIFICATION):",
        f"- Designer-declared source kind: {brief.source_kind}.",
        f"- Source-kind handling: {_SOURCE_KIND_RENDER_HANDLING[brief.source_kind]}",
        f"- Visible jewelry category: {brief.category}.",
        f"- Visible center outline/cut family: {center_shape}.",
        f"- Visible center color: {center_color}.",
        f"- Visible center holding claws/prongs: {prongs}.",
        f"- Visible side stones: left={left}; right={right}; other={other}; "
        f"shape/cut family={side_shape}.",
        f"- Visible repeated motifs: {motifs}.",
        f"- Visible band or overall silhouette: {silhouette}.",
        f"- Visible ambiguities: {ambiguities}.",
        "- Hidden, underside, off-frame, and internal construction: UNKNOWN. "
        "Never invent it or present it as observed.",
        "PRESERVATION REQUIREMENT: Keep every assessable fact above exact in "
        "every variation. A variation may change only what the separate designer "
        "instruction explicitly requests; unknown facts are not redesign space.",
    ))

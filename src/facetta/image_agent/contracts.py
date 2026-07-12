"""Typed contracts for Facetta's closed-loop jewelry image agent.

The image agent is deliberately persistence-agnostic.  It returns enough
structured evidence for an API layer to create ``ImageRun``/``ImageAttempt``
records, but it never promotes a candidate to a project asset itself.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from facetta.json_types import JsonObject, JsonValue  # noqa: F401


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", ser_json_bytes="base64")


class ImageOperation(str, Enum):
    CREATIVE_GENERATE = "CREATIVE_GENERATE"
    CONCEPT_GENERATE = "CONCEPT_GENERATE"
    REFERENCE_RENDER = "REFERENCE_RENDER"
    SPEC_RENDER = "SPEC_RENDER"
    LOCAL_EDIT = "LOCAL_EDIT"
    VISUAL_ONLY_EDIT = "VISUAL_ONLY_EDIT"
    MOUNTING_VIEW_GENERATE = "MOUNTING_VIEW_GENERATE"


class DesignerEditDomain(str, Enum):
    """Factory-relevant edit families tracked across planning, prompts, and QA."""

    CENTER_STONE_SHAPE = "center_stone_shape"
    CENTER_STONE_IDENTITY = "center_stone_identity"
    CENTER_STONE_COLOR = "center_stone_color"
    SIDE_STONE_INVENTORY = "side_stone_inventory"
    SIDE_STONE_SHAPE = "side_stone_shape"
    SIDE_STONE_IDENTITY = "side_stone_identity"
    SETTING = "setting"
    METAL_IDENTITY = "metal_identity"
    METAL_FINISH = "metal_finish"
    BAND_GEOMETRY = "band_geometry"
    RING_SIZE = "ring_size"
    CHAIN_STYLE = "chain_style"
    DESIGN_FORM = "design_form"


class QualityVerdict(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class CheckSeverity(str, Enum):
    HARD = "hard"
    WARNING = "warning"


class ImageRoute(str, Enum):
    GROK_GENERATE = "grok_generate"
    GROK_EDIT = "grok_edit"
    FLUX_GENERATE = "flux_generate"
    FLUX_KONTEXT_EDIT = "flux_kontext_edit"
    OPENAI_GENERATE = "openai_generate"
    OPENAI_EDIT = "openai_edit"


class ImageRunStatus(str, Enum):
    ACCEPTED = "accepted"
    REVIEW_REQUIRED = "review_required"
    FAILED = "failed"


class FailureCategory(str, Enum):
    VALIDATION = "validation"
    PROVIDER = "provider"
    EVALUATION = "evaluation"
    QUALITY = "quality"


class QualityCheck(_Contract):
    code: str
    passed: bool
    severity: CheckSeverity
    message: str
    evidence: JsonObject = Field(default_factory=dict)


class ImageQualityReport(_Contract):
    verdict: QualityVerdict
    checks: tuple[QualityCheck, ...]
    score: float | None = Field(default=None, ge=0, le=100)
    notes: tuple[str, ...] = ()

    @property
    def failed_checks(self) -> tuple[QualityCheck, ...]:
        return tuple(check for check in self.checks if not check.passed)


class ImageAgentPlan(_Contract):
    operation: ImageOperation
    jewelry_type: Literal["jewelry", "ring", "necklace"] = "ring"
    intent: str = Field(min_length=1)
    normalized_intent: JsonObject
    edit_domains: tuple[DesignerEditDomain, ...] = ()
    prompt_version: str
    spec_facts: JsonObject
    source_spec_facts: JsonObject | None = None
    source_spec_visual_hash: str | None = None
    source_hash: str | None = None
    mask_hash: str | None = None
    spec_visual_hash: str
    region_description: str | None = None
    mounting_view: Literal["plan", "front", "side", "section"] | None = None
    frozen: tuple[str, ...] = ()
    style_constraints: tuple[str, ...] = ()
    expected_output: str
    variant: int = Field(default=0, ge=0)
    fallback_allowed: bool = True
    drift_threshold: float = Field(default=0.18, ge=0, le=1)
    input_hash: str

    @property
    def is_necklace_chain_style_edit(self) -> bool:
        """Whether this is the deliberately narrow necklace image-agent slice."""

        return (
            self.jewelry_type == "necklace"
            and self.operation is ImageOperation.LOCAL_EDIT
            and self.edit_domains == (DesignerEditDomain.CHAIN_STYLE,)
        )


class ProviderImage(_Contract):
    image_bytes: bytes
    cached: bool = False
    provider_request_id: str | None = None
    usage: JsonObject | None = None
    cost: float | None = Field(default=None, ge=0)


class AttemptError(_Contract):
    category: FailureCategory
    code: str
    message: str
    retryable: bool = True


class ImageAttemptSummary(_Contract):
    attempt_number: int = Field(ge=1, le=3)
    route: ImageRoute
    provider: str
    model: str
    latency_ms: int = Field(ge=0)
    cached: bool = False
    provider_request_id: str | None = None
    qa_verdict: QualityVerdict | None = None
    qa_checks: tuple[QualityCheck, ...] = ()
    quality_score: float | None = Field(default=None, ge=0, le=100)
    corrective_instruction: str | None = None
    fallback_reason: str | None = None
    output_hash: str | None = None
    prompt_hash: str
    cache_key: str
    usage: JsonObject | None = None
    cost: float | None = Field(default=None, ge=0)
    error_category: FailureCategory | None = None
    error: AttemptError | None = None

    @property
    def number(self) -> int:
        return self.attempt_number

    @property
    def verdict(self) -> QualityVerdict | None:
        return self.qa_verdict

    @property
    def checks(self) -> tuple[QualityCheck, ...]:
        return self.qa_checks

    @property
    def fallback(self) -> bool:
        return self.fallback_reason is not None


class ImageRunSummary(_Contract):
    status: ImageRunStatus
    operation: ImageOperation
    normalized_intent: JsonObject
    prompt_version: str
    source_hash: str | None = None
    spec_visual_hash: str
    variant: int
    verdict: QualityVerdict | None = None
    attempts: tuple[ImageAttemptSummary, ...]
    selected_attempt: int | None = None
    output_hash: str | None = None
    error_category: FailureCategory | None = None


class ImageAgentResult(_Contract):
    plan: ImageAgentPlan
    run: ImageRunSummary
    image_bytes: bytes
    quality: ImageQualityReport
    accepted: bool
    review_required: bool


class RenderInspection(_Contract):
    """Normalized one-image QA observations.

    ``None`` means the vision judge could not assess that fact.  Unknown hard
    facts become warnings; an observed mismatch is a hard failure.
    """

    model_config = ConfigDict(extra="ignore")

    jewelry_type_matches: bool | None = None
    center_species_matches: bool | None = None
    cut_family_matches: bool | None = None
    center_color_matches: bool | None = None
    metal_matches: bool | None = None
    major_components_match: bool | None = None
    setting_matches: bool | None = None
    stone_count_matches: bool | None = None
    text_or_branding_detected: bool | None = None
    reference_consistent: bool | None = None
    exact_dimensions_credible: bool | None = None
    exact_carat_credible: bool | None = None
    score: float | None = Field(default=None, ge=0, le=100)
    notes: tuple[str, ...] = ()


class CreativeRenderInspection(_Contract):
    """Comparative evidence for a pre-spec drawing/image beauty render.

    This deliberately avoids judging whether the designer's source is rough,
    professional, complete, or attractive.  It only asks whether the candidate
    is coherent, follows the stated intent, and preserves visible design
    identity closely enough to be offered for explicit designer review.
    """

    model_config = ConfigDict(extra="ignore")

    coherent_jewelry_render: bool | None = None
    complete_piece_visible: bool | None = None
    source_design_preserved: bool | None = None
    visible_components_preserved: bool | None = None
    local_geometry_preserved: bool | None = None
    repeated_element_pattern_preserved: bool | None = None
    stone_shape_and_cut_family_preserved: bool | None = None
    requested_presentation_applied: bool | None = None
    explicit_counts_match: bool | None = None
    explicit_stone_facts_match: bool | None = None
    text_or_branding_detected: bool | None = None
    major_unintended_changes: tuple[str, ...] = ()
    score: float | None = Field(default=None, ge=0, le=100)
    notes: tuple[str, ...] = ()


class RenderCrossInspection(_Contract):
    """Independent count/identity audit for a validated spec render."""

    model_config = ConfigDict(extra="ignore")

    checked: bool = True
    jewelry_type_matches: bool | None = None
    center_identity_matches: bool | None = None
    center_cut_matches: bool | None = None
    metal_matches: bool | None = None
    setting_style_matches: bool | None = None
    prong_count_matches: bool | None = None
    observed_prong_count: int | None = Field(default=None, ge=0, le=16)
    observed_prong_count_complete: bool | None = None
    side_stone_inventory_matches: bool | None = None
    observed_side_stone_count: int | None = Field(default=None, ge=0, le=512)
    observed_side_stone_count_complete: bool | None = None
    major_components_match: bool | None = None
    differences: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


class BlindCountInspection(_Contract):
    """Expectation-free visible component count to reduce confirmation bias."""

    model_config = ConfigDict(extra="ignore")

    center_prongs_visible: int | None = Field(default=None, ge=0, le=16)
    center_prong_count_complete: bool | None = None
    side_stones_visible: int | None = Field(default=None, ge=0, le=512)
    side_stone_count_complete: bool | None = None
    notes: tuple[str, ...] = ()


class ChainStyleEditInspection(_Contract):
    """Category-specific visual evidence for one necklace chain-style edit.

    Every field is comparative image evidence, never dimensional proof.
    ``None`` therefore holds the candidate for designer review rather than
    silently converting visual uncertainty into approval.
    """

    model_config = ConfigDict(extra="ignore")

    target_style_matches: bool | None = None
    complete_visible_run_matches: bool | None = None
    chain_connections_preserved: bool | None = None
    pendant_count_preserved: bool | None = None
    pendant_geometry_preserved: bool | None = None
    bail_preserved: bool | None = None
    stones_preserved: bool | None = None
    setting_preserved: bool | None = None
    clasp_preserved: bool | None = None
    source_clasp_visible: bool | None = None
    candidate_clasp_visible: bool | None = None
    chain_length_and_drape_preserved: bool | None = None
    non_chain_geometry_preserved: bool | None = None
    candidate_contains_non_jewelry_text_or_branding: bool | None = None


class EditInspection(_Contract):
    """Normalized two-image QA observations for a scoped edit."""

    model_config = ConfigDict(extra="ignore")

    change_applied: bool | None = None
    unintended_severity: Literal["none", "minor", "major", "unknown"] = "unknown"
    unintended_changes: tuple[str, ...] = ()
    protected_regions_preserved: bool | None = None
    geometry_preserved: bool | None = None
    spec_change_matches: bool | None = None
    domain_matches: dict[str, bool | None] = Field(default_factory=dict)
    side_stone_inventory: "EditSideStoneInventoryInspection | None" = None
    chain_style: ChainStyleEditInspection | None = None
    text_or_branding_detected: bool | None = None
    score: float | None = Field(default=None, ge=0, le=100)
    notes: tuple[str, ...] = ()


class EditSideStoneInventoryInspection(_Contract):
    """Comparative visible-count evidence for one scoped inventory edit."""

    model_config = ConfigDict(extra="ignore")

    source_visible_count: int | None = Field(default=None, ge=0, le=512)
    source_count_complete: bool | None = None
    candidate_visible_count: int | None = Field(default=None, ge=0, le=512)
    candidate_count_complete: bool | None = None
    source_role_counts: dict[str, int] = Field(default_factory=dict)
    candidate_role_counts: dict[str, int] = Field(default_factory=dict)
    notes: tuple[str, ...] = ()


class EditCrossInspection(_Contract):
    """Independent skeptical audit of a primary localized-edit judgment."""

    model_config = ConfigDict(extra="ignore")

    checked: bool = True
    change_applied: bool | None = None
    frozen_facts_preserved: bool | None = None
    unintended_severity: Literal["none", "minor", "major", "unknown"] = "unknown"
    unintended_changes: tuple[str, ...] = ()
    domain_mismatches: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

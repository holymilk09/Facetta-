"""Trusted project workspace: creation, revision provenance, and state.

This router owns one Studio variation workspace and its optional trusted
factory-promotion lane. Library search and collection organization remain in
``api.library``.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import secrets
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from facetta.chain_geometry import chain_factory_blockers
from facetta.checklist import checklist_status
from facetta.confirmed_import import (
    ConfirmedImportCommand,
    ConfirmedImportRejected,
    ConfirmedImportSourceAuditPolicy,
    import_confirmed_project,
)
from facetta.concept import ConceptInvalid
from facetta.creative_workflow import (
    CreativePromptGenerator,
    CreativeRenderGenerator,
    get_creative_prompt_generator,
    get_creative_render_generator,
    invoke_creative_render_generator,
)
from facetta.creative_reference_board import (
    CreativeReferenceImage,
    build_creative_reference_board,
)
from facetta.api.error_mapping import (
    image_agent_error_response, provider_studio_job_error_response,
    render_unavailable_response,
)
from facetta.auth import (
    AuthenticatedPrincipal,
    principal_actor,
    require_principal_boundary,
)
from facetta.api.specs import (
    PhotoRequest,
    SourceCoverageAuditSummary,
    SourceCoverageConfirmRequest,
    SourceCoverageConfirmResponse,
    SourceCoverageResolveRequest,
    SourceCoverageResolveResponse,
    confirm_source_coverage,
    from_photo,
    resolve_source_coverage,
)
from facetta.db import (
    ApprovalChecklist,
    ApprovalResponse,
    DesignVersion,
    ImageAsset,
    ImageRun,
    Project,
    StudioCreateDecisionRecord,
    StudioConfirmationDraft,
    get_db,
    new_id,
    utcnow,
)
from facetta.disclaimer import is_stampable, stamp_b64
from facetta.design_form import (
    DimensionedProfileDefinition,
    DimensionedProfilePath,
    FormElementId,
    FormView,
    PositiveMillimeter,
    unresolved_form_factory_blockers,
)
from facetta.design_form_revision import (
    DesignFormRevisionError,
    confirm_dimensioned_form_element,
)
from facetta.drawing_workflow import (
    compile_color_brief,
    compile_line_art_brief,
)
from facetta.image_agent import (
    ImageAgentError,
    ImageAgentResult,
    ImageOperation,
    JewelryImageAgent,
    MountingViewQualityEvaluator,
    build_image_plan,
)
from facetta.image_identity import spec_visual_hash
from facetta.json_types import JsonObject
from facetta.project_backbone import (
    BriefProjectGeneration,
    BriefProjectGenerator,
    BriefProjectGeneratorUnavailable,
    CreativeCandidateInput,
    PersistedProjectInput,
    PROVENANCE_BY_CAPABILITY,
    SourceAssetInput,
    accepted_creative_candidate,
    confirmable_pre_spec_asset,
    get_brief_project_generator,
    is_primary_revision,
    is_canonical_revision,
    persist_project_v1,
    persist_creative_project,
    persist_prompt_creative_project,
    promote_creative_candidate,
    persist_project_derived_asset,
    persist_project_primary_revision,
)
from facetta.image_run_store import (
    persist_image_agent_failure, persist_image_agent_result,
)
from facetta.image_region import ImageRegionError, crop_normalized_region
from facetta.media import sniff_media_type
from facetta.presentation import (
    MarketingImageGenerator,
    PresentationScopeError,
    compile_product_photo_brief,
    get_marketing_image_generator,
)
from facetta.provider_job_gate import (
    ProviderStudioJobError,
    require_provider_studio_job,
)
from facetta.preliminary_sheet import sheet_readiness_blockers
from facetta.render import RenderUnavailable
from facetta.spec import Spec
from facetta.studio_history import (
    StudioHistoryError,
    ensure_project_family,
    fork_project_variation,
)
from facetta.studio_jobs import (
    StudioJobAccountingError,
    settle_create_studio_job_selection,
)
from facetta.studio_presentation_candidates import (
    StudioPresentationError,
    fail_exact_studio_presentation_job,
    reserve_exact_studio_presentation_job,
    store_studio_presentation_candidate,
)
from facetta.studio_view_candidates import (
    StudioViewError,
    fail_studio_view_job,
    reserve_studio_view_job,
    store_studio_view_candidate,
)
from facetta.studio_confirm import (
    StudioConfirmDesignResponse,
    build_studio_confirm_design_response,
)
from facetta.source_component_coverage import (
    source_component_factory_blockers,
)
from facetta.source_component_confirmation import SourceComponentConfirmationInput
from facetta.source_component_resolution import (
    SourceComponentResolution,
    valid_source_component_spec_paths,
)
from facetta.source_evidence_lineage import (
    apply_trusted_lineage_to_blockers,
    has_trusted_visual_spec_lineage,
    source_confirmation_evidence_matches,
    source_evidence_anchor_asset,
)
from facetta.validation import validate_spec
from facetta.vocabulary import get_vocabulary
from facetta.warning_candidates import (
    BriefWarningCandidate,
    MountingViewArtifactMetadata,
    WarningCandidateUnavailable,
    get_brief_warning_candidate,
    store_brief_warning_candidate,
    store_markup_warning_candidate,
)

_UNSTAMPED_CAPS = {
    "MANUFACTURING_TECHNICAL_DRAWING",
    "PRODUCT_PHOTO",
    "MARKETING_IMAGE",
    "LINE_ART",
    "COLORED_LINE_ART",
}

router = APIRouter(
    prefix="/projects",
    tags=["projects"],
    dependencies=[Depends(require_principal_boundary)],
)

DbSession = Annotated[Session, Depends(get_db)]
PrincipalDep = Annotated[AuthenticatedPrincipal, Depends(require_principal_boundary)]
BriefGeneratorDep = Annotated[
    BriefProjectGenerator, Depends(get_brief_project_generator)]
CreativeGeneratorDep = Annotated[
    CreativeRenderGenerator, Depends(get_creative_render_generator)]
CreativePromptGeneratorDep = Annotated[
    CreativePromptGenerator, Depends(get_creative_prompt_generator)]
MarketingGeneratorDep = Annotated[
    MarketingImageGenerator, Depends(get_marketing_image_generator)]

MountingViewGenerator = Callable[[Spec, bytes, str, int], ImageAgentResult]


def get_mounting_view_generator() -> MountingViewGenerator:
    def generate(
        spec: Spec,
        source_image: bytes,
        view: str,
        variant: int,
    ) -> ImageAgentResult:
        plan = build_image_plan(
            ImageOperation.MOUNTING_VIEW_GENERATE,
            f"Create the design-specific {view} mounting view.",
            spec=spec,
            source_image=source_image,
            mounting_view=view,
            variant=variant,
        )
        return JewelryImageAgent(
            evaluator=MountingViewQualityEvaluator(),
        ).run(plan, source_image=source_image)

    return generate


MountingViewGeneratorDep = Annotated[
    MountingViewGenerator, Depends(get_mounting_view_generator)]

ProjectState = Literal[
    "refining", "approval_required", "approved", "factory_ready"]


class AssetSummary(BaseModel):
    asset_id: str
    root_id: str
    parent_asset_id: str | None
    capability: str
    source_kind: Literal["drawing", "photograph", "finished_render"] | None
    provenance: str
    revision: int | None
    design_version: int | None
    region: str | None
    instruction: str | None
    drift: float | None
    pinned: bool
    media_type: str
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    image_url: str
    created_by: str
    created_at: datetime
    legacy_provenance: bool = False
    image_b64: str | None = None


class ApprovalSummary(BaseModel):
    checklist_id: str
    asset_id: str
    design_id: str | None
    design_version: int | None
    mode: str
    items: list[dict[str, object]]
    answers: dict[str, dict[str, object]]
    outstanding: list[str]
    approved_count: int
    total: int
    completed: bool
    all_approved: bool
    pinned: bool


class FactoryReadinessBlocker(BaseModel):
    code: str
    subject_kind: Literal["design_form", "source_component", "chain"]
    subject_id: str
    element_id: str | None = None
    component_id: str | None = None
    role: str
    label: str
    detail: str
    required_resolution: str


class ProjectDetail(BaseModel):
    id: str
    root_id: str
    title: str
    collection: str
    tags: list[str]
    owner: str
    counts: dict[str, int]
    item_count: int
    primary_revision_count: int
    has_factory_drawing: bool
    cover_asset_id: str | None
    created_at: datetime
    updated_at: datetime
    state: ProjectState
    design_id: str | None
    latest_design_version: int | None
    spec: dict[str, object] | None
    active_asset_id: str | None
    confirmable_pre_spec: bool
    selected_candidate_asset_id: str | None
    active_design_version: int | None
    active_revision: AssetSummary | None
    pinned_revision: AssetSummary | None
    revisions: list[AssetSummary]
    creative_candidates: list[AssetSummary]
    derived_assets: list[AssetSummary]
    assets: list[AssetSummary]
    items: list[AssetSummary]
    approval: ApprovalSummary | None
    factory_ready: bool
    factory_blockers: list[FactoryReadinessBlocker]
    image_run_ids: list[str]


class ProjectFromImageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_base64: Annotated[str, Field(min_length=1, max_length=14_000_000)]
    media_type: Literal["image/png", "image/jpeg", "image/webp"] | None = None
    spec: Spec
    owner: Annotated[str, Field(min_length=1, max_length=32)]
    title: Annotated[str, Field(min_length=1, max_length=200)]
    collection: Annotated[str, Field(min_length=1, max_length=80)] | None = None
    tags: Annotated[list[str], Field(max_length=24)] = Field(default_factory=list)


class ProjectFromBriefRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brief: Annotated[str, Field(min_length=3, max_length=600)]
    owner: Annotated[str, Field(min_length=1, max_length=32)]
    title: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    collection: Annotated[str, Field(min_length=1, max_length=80)] | None = None
    tags: Annotated[list[str], Field(max_length=24)] = Field(default_factory=list)
    variant: Annotated[int, Field(ge=0, le=100)] = 0


class NormalizedSourceRegion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    x: Annotated[float, Field(ge=0, le=1)]
    y: Annotated[float, Field(ge=0, le=1)]
    width: Annotated[float, Field(gt=0, le=1)]
    height: Annotated[float, Field(gt=0, le=1)]

    @model_validator(mode="after")
    def remain_inside_image(self) -> NormalizedSourceRegion:
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("source region must remain inside normalized bounds")
        return self


class CreativeRoleReferenceRequest(BaseModel):
    """One advisory image with a single, non-authoritative creative role."""

    model_config = ConfigDict(extra="forbid")

    role: Literal[
        "material_style", "construction_detail", "brand_direction"
    ]
    image_base64: Annotated[str, Field(min_length=1, max_length=14_000_000)]
    media_type: Literal["image/png", "image/jpeg", "image/webp"]


class ProjectFromDrawingRequest(BaseModel):
    """One media intake with explicit, designer-declared source semantics."""

    model_config = ConfigDict(extra="forbid")

    image_base64: Annotated[str, Field(min_length=1, max_length=14_000_000)]
    # Compatibility: historical `/from-drawing` clients had no source label.
    # The legacy route name is the only honest fallback; current Studio always
    # sends the designer's explicit choice.
    source_kind: Literal["drawing", "photograph", "finished_render"] = "drawing"
    media_type: Literal["image/png", "image/jpeg", "image/webp"] | None = None
    instruction: Annotated[str, Field(min_length=3, max_length=1000)] = (
        "Create a polished fine-jewelry beauty render faithful to every visible "
        "design element in this source."
    )
    variation_count: Annotated[int, Field(ge=1, le=4)] = 1
    starting_variant: Annotated[int, Field(ge=0, le=100)] = 0
    owner: Annotated[str, Field(min_length=1, max_length=32)]
    title: Annotated[str, Field(min_length=1, max_length=200)]
    collection: Annotated[str, Field(min_length=1, max_length=80)] | None = None
    tags: Annotated[list[str], Field(max_length=24)] = Field(default_factory=list)
    studio_job_id: Annotated[str, Field(min_length=1, max_length=32)] | None = None

    # A professional plate often repeats one finished piece as front, side,
    # and enlarged construction views. The designer may isolate the exact view
    # to render; the original plate and the cropped source are both persisted.
    source_region_description: Annotated[
        str, Field(min_length=3, max_length=500)
    ] | None = None
    source_region: NormalizedSourceRegion | None = None
    references: Annotated[
        list[CreativeRoleReferenceRequest], Field(max_length=3)
    ] = Field(default_factory=list)

    @model_validator(mode="after")
    def description_requires_region(self) -> ProjectFromDrawingRequest:
        if self.source_region_description is not None and self.source_region is None:
            raise ValueError(
                "source_region_description requires source_region coordinates"
            )
        return self

    @model_validator(mode="after")
    def reference_roles_are_unique(self) -> ProjectFromDrawingRequest:
        roles = [reference.role for reference in self.references]
        if len(set(roles)) != len(roles):
            raise ValueError("secondary creative reference roles must be unique")
        return self


class ProjectFromPromptRequest(BaseModel):
    """Category-neutral prompt intake with no inferred factory authority."""

    model_config = ConfigDict(extra="forbid")

    prompt: Annotated[str, Field(min_length=3, max_length=2000)]
    variation_count: Annotated[int, Field(ge=1, le=4)] = 1
    starting_variant: Annotated[int, Field(ge=0, le=100)] = 0
    owner: Annotated[str, Field(min_length=1, max_length=32)]
    title: Annotated[str, Field(min_length=1, max_length=200)]
    collection: Annotated[str, Field(min_length=1, max_length=80)] | None = None
    tags: Annotated[list[str], Field(max_length=24)] = Field(default_factory=list)
    studio_job_id: Annotated[str, Field(min_length=1, max_length=32)] | None = None


class CreativeCandidatePromoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created_by: Annotated[str, Field(min_length=1, max_length=32)]
    confirmation_token: Annotated[str, Field(min_length=32, max_length=256)]


class CreativeCandidateSelectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created_by: Annotated[str, Field(min_length=1, max_length=32)]
    studio_job_id: Annotated[str, Field(min_length=1, max_length=32)] | None = None


class RetainedCreativeDirectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: Annotated[str, Field(min_length=1, max_length=32)]
    label: Annotated[str, Field(min_length=1, max_length=120)]


class CreativeDirectionCommitRequest(BaseModel):
    """One complete designer decision for a generated Create review."""

    model_config = ConfigDict(extra="forbid")

    selected_candidate_id: Annotated[str, Field(min_length=1, max_length=32)]
    retained: Annotated[
        list[RetainedCreativeDirectionRequest], Field(max_length=3)
    ] = Field(default_factory=list)
    created_by: Annotated[str, Field(min_length=1, max_length=32)]
    studio_job_id: Annotated[str, Field(min_length=1, max_length=32)] | None = None

    @model_validator(mode="after")
    def validate_candidate_set(self):
        retained_ids = [item.candidate_id for item in self.retained]
        if len(set(retained_ids)) != len(retained_ids):
            raise ValueError("each retained creative direction must be unique")
        if self.selected_candidate_id in retained_ids:
            raise ValueError(
                "the selected Original cannot also be retained as a sibling"
            )
        normalized_labels = [item.label.strip() for item in self.retained]
        if any(not label for label in normalized_labels):
            raise ValueError("each retained creative direction requires a label")
        return self


class CreativeDirectionVariationResponse(BaseModel):
    status: Literal["variation_created"]
    family_id: str
    variation_index: int
    source_project_id: str
    source_asset_id: str
    project: ProjectDetail


class CreativeDirectionCommitResponse(BaseModel):
    project: ProjectDetail
    retained_variations: list[CreativeDirectionVariationResponse]


class CreativeCandidateDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notes: Annotated[str, Field(max_length=2000)] = ""
    created_by: Annotated[str, Field(min_length=1, max_length=32)]
    run_independent_audit: bool = True


class CreativeCandidateCoverageResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec: Spec
    resolutions: Annotated[
        tuple[SourceComponentResolution, ...],
        Field(max_length=999),
    ] = ()
    created_by: Annotated[str, Field(min_length=1, max_length=32)]
    run_independent_audit: bool = False


class CreativeCandidateCoverageConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec: Spec
    confirmations: Annotated[
        tuple[SourceComponentConfirmationInput, ...],
        Field(min_length=1, max_length=999),
    ]
    created_by: Annotated[str, Field(min_length=1, max_length=32)]


class DimensionedProfileGeometryInput(BaseModel):
    """Designer-entered geometry; source bytes and actor bind server-side."""

    model_config = ConfigDict(extra="forbid")

    view: FormView
    paths: Annotated[
        tuple[DimensionedProfilePath, ...],
        Field(min_length=1, max_length=128),
    ]
    profile_thickness_mm: PositiveMillimeter
    dimension_status: Literal[
        "designer_supplied",
        "designer_confirmed_estimate",
    ]
    manufacturing_notes: Annotated[
        str,
        Field(min_length=1, max_length=1000),
    ]

    @model_validator(mode="after")
    def reject_ambiguous_notes(self) -> DimensionedProfileGeometryInput:
        if self.manufacturing_notes != self.manufacturing_notes.strip():
            raise ValueError("manufacturing notes must be trimmed")
        return self


class CreativeCandidateProfileConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec: Spec
    element_id: FormElementId
    profile: DimensionedProfileGeometryInput
    created_by: Annotated[str, Field(min_length=1, max_length=32)]


class DimensionedProfileBlockerSummary(BaseModel):
    code: str
    detail: str


class CreativeCandidateProfileConfirmResponse(BaseModel):
    spec: Spec
    element_id: FormElementId
    candidate_asset_id: str
    candidate_sha256: str
    previous_definition_kind: str
    definition: DimensionedProfileDefinition
    source_reaudit_required: bool
    factory_ready: bool
    sheet_authority: Literal[
        "factory_profile",
        "preliminary_not_for_production",
    ]
    blockers: tuple[DimensionedProfileBlockerSummary, ...]


class ProjectRenderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created_by: Annotated[str, Field(min_length=1, max_length=32)]
    # Optional for compatibility with callers that render directly from the
    # active primary revision.  The trusted drawing flow sends both IDs: the
    # current primary is the optimistic-concurrency guard, while the selected
    # source may be its exact-version, designer-confirmed COLORED_LINE_ART.
    expected_asset_id: Annotated[str, Field(min_length=1, max_length=32)] | None = None
    source_asset_id: Annotated[str, Field(min_length=1, max_length=32)] | None = None
    expected_design_version: Annotated[int, Field(ge=1)]
    instruction: Annotated[str, Field(min_length=3, max_length=1000)] = (
        "Create a beauty render faithful to the current designer-confirmed "
        "specification and preserve the imported design identity."
    )
    variant: Annotated[int, Field(ge=0, le=100)] = 0
    presentation_only: bool = False
    studio_job_id: Annotated[str, Field(min_length=1, max_length=32)] | None = None


class ProductPhotoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created_by: Annotated[str, Field(min_length=1, max_length=32)]
    expected_asset_id: Annotated[str, Field(min_length=1, max_length=32)]
    expected_design_version: Annotated[int, Field(ge=1)]
    preset: Literal[
        "catalog_white", "luxury_studio", "dark_editorial", "macro_detail",
    ] = "catalog_white"
    framing: Literal["source", "square", "portrait"] = "portrait"
    custom_instruction: Annotated[str, Field(max_length=600)] = ""
    variant: Annotated[int, Field(ge=0, le=100)] = 0
    presentation_only: bool = False
    studio_job_id: Annotated[str, Field(min_length=1, max_length=32)] | None = None


class MarketingPackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created_by: Annotated[str, Field(min_length=1, max_length=32)]
    expected_asset_id: Annotated[str, Field(min_length=1, max_length=32)]
    expected_design_version: Annotated[int, Field(ge=1)]
    presets: Annotated[list[Literal[
        "catalog_white", "luxury_studio", "dark_editorial", "macro_detail",
    ]], Field(min_length=1, max_length=4)]
    framing: Literal["source", "square", "portrait"] = "portrait"
    custom_instruction: Annotated[str, Field(max_length=600)] = ""
    starting_variant: Annotated[int, Field(ge=0, le=100)] = 0
    studio_job_id: Annotated[str, Field(min_length=1, max_length=32)] | None = None

    @model_validator(mode="after")
    def unique_presets(self) -> MarketingPackRequest:
        if len(set(self.presets)) != len(self.presets):
            raise ValueError("marketing pack presets must be unique")
        return self


class MarketingPackCandidate(BaseModel):
    preset: str
    framing: str
    image_run_id: str
    candidate_id: str
    preview_url: str
    qa: JsonObject
    routing: JsonObject
    studio_job_id: str | None = None


class MarketingPackFailure(BaseModel):
    preset: str
    image_run_id: str | None
    error_category: str
    code: str
    detail: str


class MarketingPackResponse(BaseModel):
    status: Literal["review_required", "failed"]
    project_id: str
    source_asset_id: str
    design_version: int
    requested_count: int
    candidate_count: int
    failed_count: int
    maximum_provider_attempts: int
    actual_attempts: int
    candidates: list[MarketingPackCandidate]
    failures: list[MarketingPackFailure]


MountingViewName = Literal["plan", "front", "side", "section"]


class VisualTwinViewsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created_by: Annotated[str, Field(min_length=1, max_length=32)]
    expected_asset_id: Annotated[str, Field(min_length=1, max_length=32)]
    expected_design_version: Annotated[int, Field(ge=1)]
    views: Annotated[list[MountingViewName], Field(min_length=1, max_length=4)]
    starting_variant: Annotated[int, Field(ge=0, le=100)] = 0

    @model_validator(mode="after")
    def unique_views(self) -> VisualTwinViewsRequest:
        if len(set(self.views)) != len(self.views):
            raise ValueError("visual twin views must be unique")
        return self


class VisualTwinViewCandidate(BaseModel):
    view: MountingViewName
    image_run_id: str
    candidate_id: str
    preview_url: str
    promotion_kind: Literal["derived_only"]
    authority: Literal["factory_discussion_only"]
    qa: JsonObject
    routing: JsonObject


class VisualTwinViewFailure(BaseModel):
    view: MountingViewName
    image_run_id: str | None
    error_category: str
    code: str
    detail: str


class VisualTwinViewsResponse(BaseModel):
    status: Literal["review_required", "failed"]
    project_id: str
    source_asset_id: str
    design_version: int
    requested_count: int
    candidate_count: int
    failed_count: int
    maximum_provider_attempts: int
    actual_attempts: int
    candidates: list[VisualTwinViewCandidate]
    failures: list[VisualTwinViewFailure]


class ProjectLineArtRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created_by: Annotated[str, Field(min_length=1, max_length=32)]
    expected_asset_id: Annotated[str, Field(min_length=1, max_length=32)]
    expected_design_version: Annotated[int, Field(ge=1)]
    view: Literal["front", "three_quarter", "side"] = "three_quarter"
    source_region_description: Annotated[
        str, Field(min_length=3, max_length=500)
    ] | None = None
    source_region: NormalizedSourceRegion | None = None
    variant: Annotated[int, Field(ge=0, le=100)] = 0
    studio_job_id: Annotated[str, Field(min_length=1, max_length=32)] | None = None


class ProjectColorizeLineArtRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created_by: Annotated[str, Field(min_length=1, max_length=32)]
    expected_asset_id: Annotated[str, Field(min_length=1, max_length=32)]
    expected_design_version: Annotated[int, Field(ge=1)]
    variant: Annotated[int, Field(ge=0, le=100)] = 0


class BriefWarningAcceptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created_by: Annotated[str, Field(min_length=1, max_length=32)]


class ProjectWarningCandidate(BaseModel):
    run_id: str
    candidate_id: str
    preview_url: str
    qa: JsonObject
    operation: Literal["CONCEPT_GENERATE", "SPEC_RENDER"]
    requested_change: str
    creation_stage: Literal["concept", "spec_render"]


class ProjectCreationWarning(BaseModel):
    status: Literal["review_required"] = "review_required"
    project: None = None
    image_run_id: str
    quality_report: JsonObject
    warning_candidate: ProjectWarningCandidate


def project_chain(db: Session, root_id: str) -> list[ImageAsset]:
    chain = list(db.scalars(
        select(ImageAsset).where(ImageAsset.root_id == root_id)
        .order_by(ImageAsset.created_at, ImageAsset.id)))
    # Atomic project creation gives root and source artifacts one timestamp.
    # The chain root is revision 1, never whichever opaque id sorts first.
    chain.sort(key=lambda asset: (
        asset.id != root_id, asset.created_at, asset.id))
    return chain


def _same_direct_asset_branch(
    chain: list[ImageAsset],
    first: ImageAsset,
    second: ImageAsset,
) -> bool:
    """Whether either asset is an ancestor of the other.

    A shared root is insufficient: two children of that root can represent
    abandoned alternative visual branches.  Explicit beauty-render sources
    must remain on the active primary's own parent chain in either direction.
    """
    if first.id == second.id:
        return True
    by_id = {asset.id: asset for asset in chain}

    def is_ancestor(ancestor_id: str, descendant: ImageAsset) -> bool:
        seen: set[str] = set()
        cursor = descendant
        while cursor.parent_asset_id is not None:
            parent_id = cursor.parent_asset_id
            if parent_id == ancestor_id:
                return True
            if parent_id in seen:
                return False
            seen.add(parent_id)
            parent = by_id.get(parent_id)
            if parent is None:
                return False
            cursor = parent
        return False

    return is_ancestor(first.id, second) or is_ancestor(second.id, first)


def _cover_asset(chain: list[ImageAsset]) -> ImageAsset | None:
    pinned = [a for a in chain
              if is_primary_revision(a) and a.pinned_at is not None]
    if pinned:
        return max(pinned, key=lambda a: a.pinned_at)
    primary = [a for a in chain if is_primary_revision(a)]
    if primary:
        return primary[-1]
    images = [a for a in chain if a.media_type.startswith("image/")]
    return images[-1] if images else (chain[-1] if chain else None)


def project_card(db: Session, project: Project) -> dict:
    chain = project_chain(db, project.root_id)
    primary = [a for a in chain if is_canonical_revision(a)]
    selected_candidate = accepted_creative_candidate(
        chain, project.selected_candidate_asset_id,
    )
    if selected_candidate is not None:
        primary.insert(0, selected_candidate)
    kinds = Counter(a.capability for a in chain)
    selected = (
        next((asset for asset in chain
              if asset.id == project.selected_candidate_asset_id), None)
        if project.selected_candidate_asset_id is not None
        and not any(asset.design_version is not None for asset in primary)
        else None
    )
    cover = selected or _cover_asset(chain)
    return {
        "root_id": project.root_id,
        "title": project.title,
        "collection": project.collection or "Unfiled",
        "tags": project.tags or [],
        "owner": project.owner,
        "counts": dict(kinds),
        "item_count": len(chain),
        "primary_revision_count": len(primary),
        "has_factory_drawing": any(
            a.capability == "MANUFACTURING_TECHNICAL_DRAWING" for a in chain),
        "cover_asset_id": cover.id if cover else None,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }


def _linked_design_id(db: Session, project: Project,
                      chain: list[ImageAsset]) -> str | None:
    root = db.get(ImageAsset, project.root_id)
    if root is not None and root.design_id:
        return root.design_id
    candidates = {a.design_id for a in chain if a.design_id}
    return next(iter(candidates)) if len(candidates) == 1 else None


def _latest_spec(db: Session, design_id: str | None) -> DesignVersion | None:
    if design_id is None:
        return None
    return db.execute(
        select(DesignVersion)
        .where(DesignVersion.design_id == design_id)
        .order_by(DesignVersion.version.desc())
    ).scalars().first()


def _revision_numbers(
    chain: list[ImageAsset], selected_candidate_asset_id: str | None = None,
) -> dict[str, int]:
    canonical = [a for a in chain if is_canonical_revision(a)]
    selected = accepted_creative_candidate(chain, selected_candidate_asset_id)
    if selected is not None:
        canonical.insert(0, selected)
    return {asset.id: revision for revision, asset in enumerate(
        canonical, start=1)}


def _asset_summary(
    asset: ImageAsset,
    *,
    revisions: dict[str, int],
    chain_design_id: str | None,
    include_image: bool,
) -> dict:
    legacy = bool(
        is_primary_revision(asset)
        and chain_design_id
        and asset.design_version is None
        and asset.capability != "CREATIVE_RENDER"
    )
    provenance = (
        "legacy_unversioned" if legacy
        else (
            f"designer_supplied_{asset.source_kind}"
            if asset.capability == "CREATIVE_SOURCE" and asset.source_kind
            else PROVENANCE_BY_CAPABILITY.get(
                asset.capability, "derived_artifact")
        )
    )
    item = {
        "asset_id": asset.id,
        "root_id": asset.root_id,
        "parent_asset_id": asset.parent_asset_id,
        "capability": asset.capability,
        "source_kind": asset.source_kind,
        "provenance": provenance,
        "revision": revisions.get(asset.id),
        "design_version": asset.design_version,
        "region": asset.region,
        "instruction": asset.instruction,
        "drift": asset.drift,
        "pinned": asset.pinned_at is not None,
        "media_type": asset.media_type,
        "sha256": hashlib.sha256(bytes(asset.image)).hexdigest(),
        "image_url": f"/assets/{asset.id}/image",
        "created_by": asset.created_by,
        "created_at": asset.created_at,
        "legacy_provenance": legacy,
    }
    if include_image:
        raw = bytes(asset.image)
        item["image_b64"] = (
            stamp_b64(raw) if (asset.capability not in _UNSTAMPED_CAPS
                               and is_stampable(asset.media_type))
            else base64.b64encode(raw).decode())
    return item


def _approval_for_active(
    db: Session, active: ImageAsset | None, design_id: str | None,
    *,
    factory_blocked: bool = False,
) -> tuple[dict | None, ProjectState]:
    if active is None:
        return None, "refining"
    candidates = list(db.execute(
        select(ApprovalChecklist)
        .where(ApprovalChecklist.asset_id == active.id)
        .order_by(ApprovalChecklist.created_at.desc(),
                  ApprovalChecklist.id.desc())
    ).scalars())
    # Versioned assets require an exact asset + design + version binding.
    checklist = next((candidate for candidate in candidates if (
        active.design_version is None
        or (candidate.design_id == design_id
            and candidate.design_version == active.design_version)
    )), None)
    if checklist is None:
        return None, "refining"
    responses = list(db.scalars(
        select(ApprovalResponse)
        .where(ApprovalResponse.checklist_id == checklist.id)
        .order_by(ApprovalResponse.id)
    ))
    status = checklist_status(checklist.items, responses)
    answers: dict[str, dict[str, object]] = {}
    for response in responses:
        answers[response.item_key] = {
            "approved": bool(response.approved),
            "note": response.note,
            "understood_as": response.understood_as,
            "created_by": response.created_by,
            "created_at": response.created_at.isoformat(),
        }
    summary = {
        "checklist_id": checklist.id,
        "asset_id": active.id,
        "design_id": checklist.design_id,
        "design_version": checklist.design_version,
        "mode": checklist.mode,
        "items": checklist.items,
        "answers": answers,
        "outstanding": status["outstanding"],
        "approved_count": status["approved"],
        "total": status["total"],
        "completed": status["all_approved"],
        "all_approved": status["all_approved"],
        "pinned": active.pinned_at is not None,
    }
    if status["all_approved"]:
        state: ProjectState = (
            "factory_ready"
            if active.pinned_at is not None and not factory_blocked
            else "approved"
        )
    else:
        state = "approval_required"
    return summary, state


def project_detail(db: Session, project: Project,
                   include_images: bool = False) -> dict:
    chain = project_chain(db, project.root_id)
    revision_numbers = _revision_numbers(
        chain, project.selected_candidate_asset_id,
    )
    primary = [a for a in chain if a.id in revision_numbers]
    creative_candidates = [
        asset for asset in chain
        if asset.capability == "CREATIVE_RENDER" and asset.design_version is None
    ]
    active = primary[-1] if primary else None
    if (project.selected_candidate_asset_id is not None
            and not primary):
        selected = next((asset for asset in creative_candidates
                         if asset.id == project.selected_candidate_asset_id), None)
        if selected is not None:
            active = selected
    pinned_candidates = [a for a in primary if a.pinned_at is not None]
    pinned = (max(pinned_candidates, key=lambda a: a.pinned_at)
              if pinned_candidates else None)
    design_id = _linked_design_id(db, project, chain)
    confirmable = confirmable_pre_spec_asset(
        chain,
        project.selected_candidate_asset_id,
    )
    latest = _latest_spec(db, design_id)
    summaries = [
        _asset_summary(
            a, revisions=revision_numbers, chain_design_id=design_id,
            include_image=include_images)
        for a in chain
    ]
    by_id = {item["asset_id"]: item for item in summaries}
    factory_blockers: list[dict[str, object]] = []
    if (active is not None and design_id is not None
            and active.design_version is not None):
        exact = db.get(DesignVersion, (design_id, active.design_version))
        if exact is not None:
            active_spec = Spec.model_validate(exact.spec)
            factory_blockers = [{
                "code": blocker.code,
                "subject_kind": "design_form",
                "subject_id": blocker.element_id,
                "element_id": blocker.element_id,
                "component_id": None,
                "role": blocker.role,
                "label": blocker.label,
                "detail": blocker.message,
                "required_resolution": blocker.required_resolution,
            } for blocker in unresolved_form_factory_blockers(
                active_spec.design_form)]
            target_visual_hash = spec_visual_hash(active_spec)
            source_evidence_hash = hashlib.sha256(
                bytes(source_evidence_anchor_asset(
                    db,
                    active_asset=active,
                ).image)
            ).hexdigest()
            source_blockers = source_component_factory_blockers(
                active_spec.source_component_coverage,
                valid_spec_paths=valid_source_component_spec_paths(active_spec),
                current_spec_visual_hash=target_visual_hash,
                current_source_hash=source_evidence_hash,
            )
            coverage = active_spec.source_component_coverage
            source_blockers = apply_trusted_lineage_to_blockers(
                source_blockers,
                lineage_verified=has_trusted_visual_spec_lineage(
                    db,
                    active_asset=active,
                    source_spec_visual_hash=(
                        coverage.audited_spec_visual_hash
                        if coverage is not None else None
                    ),
                    target_spec_visual_hash=target_visual_hash,
                ),
                source_confirmation_evidence_verified=(
                    source_confirmation_evidence_matches(
                        coverage,
                        source_hash=source_evidence_hash,
                    )
                ),
            )
            factory_blockers.extend({
                "code": blocker.code,
                "subject_kind": "source_component",
                "subject_id": blocker.component_id,
                "element_id": None,
                "component_id": blocker.component_id,
                "role": "source_component",
                "label": blocker.component_id.replace(".", " "),
                "detail": blocker.message,
                "required_resolution": blocker.required_resolution,
            } for blocker in source_blockers)
            factory_blockers.extend({
                "code": blocker.code,
                "subject_kind": "chain",
                "subject_id": blocker.field_path,
                "element_id": None,
                "component_id": None,
                "role": "chain_manufacturing",
                "label": blocker.field_path.replace("_", " "),
                "detail": blocker.message,
                "required_resolution": blocker.required_resolution,
            } for blocker in chain_factory_blockers(active_spec))
    approval, state = _approval_for_active(
        db,
        active,
        design_id,
        factory_blocked=bool(factory_blockers),
    )
    return {
        **project_card(db, project),
        "id": project.root_id,
        "state": state,
        "design_id": design_id,
        "latest_design_version": latest.version if latest else None,
        "spec": latest.spec if latest else None,
        "active_asset_id": active.id if active else None,
        "confirmable_pre_spec": (
            confirmable is not None
            and active is not None
            and confirmable.id == active.id
        ),
        "selected_candidate_asset_id": project.selected_candidate_asset_id,
        "active_design_version": (active.design_version if active else None),
        "active_revision": by_id.get(active.id) if active else None,
        "pinned_revision": by_id.get(pinned.id) if pinned else None,
        "revisions": [by_id[a.id] for a in primary],
        "creative_candidates": [by_id[a.id] for a in creative_candidates],
        "derived_assets": [
            item for item in summaries
            if item["revision"] is None
            and item["asset_id"] not in {
                candidate.id for candidate in creative_candidates
            }
        ],
        "assets": summaries,
        "items": summaries,
        "approval": approval,
        "factory_ready": state == "factory_ready",
        "factory_blockers": factory_blockers,
        "image_run_ids": list(db.scalars(
            select(ImageRun.id)
            .where(ImageRun.project_root_id == project.root_id)
            .order_by(ImageRun.created_at, ImageRun.id))),
    }


def _uploaded_media_type(image: bytes) -> str | None:
    if image[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if image[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if image[:4] == b"RIFF" and image[8:12] == b"WEBP":
        return "image/webp"
    return None


def _validate_ring_spec(spec: Spec):
    if spec.jewelry_type != "ring":
        return None, JSONResponse(status_code=422, content={
            "error_category": "validation_failure",
            "detail": "the trusted workflow first slice supports rings only",
        })
    result = validate_spec(spec, get_vocabulary())
    if not result.ok:
        return None, JSONResponse(status_code=422, content={
            "error_category": "validation_failure",
            "detail": [issue.as_detail() for issue in result.issues],
        })
    return result.spec, None


def _owned_creative_candidate(
    db: Session,
    *,
    project_id: str,
    candidate_id: str,
    actor: str,
) -> tuple[Project, ImageAsset]:
    project = db.get(Project, project_id)
    candidate = db.get(ImageAsset, candidate_id)
    if project is None or candidate is None:
        raise HTTPException(status_code=404, detail="creative candidate not found")
    if project.owner != actor:
        raise HTTPException(
            status_code=403,
            detail="only the project owner may review a creative candidate",
        )
    if (candidate.root_id != project.root_id
            or candidate.capability != "CREATIVE_RENDER"
            or candidate.design_version is not None):
        raise HTTPException(
            status_code=409,
            detail="the selected asset is not a pre-spec creative candidate",
        )
    return project, candidate


def _owned_current_confirmable_pre_spec_asset(
    db: Session,
    *,
    project_id: str,
    candidate_id: str,
    actor: str,
) -> tuple[Project, ImageAsset]:
    """Resolve the exact current pre-spec pixels eligible for confirmation."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="creative candidate not found")
    if project.owner != actor:
        raise HTTPException(
            status_code=403,
            detail="only the project owner may review a creative candidate",
        )
    current = confirmable_pre_spec_asset(
        project_chain(db, project.root_id),
        project.selected_candidate_asset_id,
    )
    if current is None or current.id != candidate_id:
        raise HTTPException(
            status_code=409,
            detail=(
                "the selected asset is not the current confirmable pre-spec "
                "revision"
            ),
        )
    return project, current


def _normalized_retained_directions(
    request: CreativeDirectionCommitRequest,
) -> list[dict[str, str]]:
    return [
        {"candidate_id": item.candidate_id, "label": item.label.strip()}
        for item in request.retained
    ]


def _creative_direction_commit_response(
    db: Session,
    *,
    project: Project,
    decision: StudioCreateDecisionRecord,
    request: CreativeDirectionCommitRequest,
) -> CreativeDirectionCommitResponse:
    """Return one durable decision only when the retry payload is exact."""

    requested = _normalized_retained_directions(request)
    stored = list(decision.retained_directions or [])
    stored_request = [
        {
            "candidate_id": str(item.get("candidate_id", "")),
            "label": str(item.get("label", "")),
        }
        for item in stored
    ]
    if (
        decision.owner != request.created_by
        or decision.selected_candidate_asset_id != request.selected_candidate_id
        or decision.studio_job_id != request.studio_job_id
        or stored_request != requested
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "the Create review was already committed with a different "
                "selection or retained-direction set"
            ),
        )
    if project.selected_candidate_asset_id != decision.selected_candidate_asset_id:
        raise HTTPException(
            status_code=409,
            detail="the committed Create decision no longer matches the project",
        )

    retained: list[CreativeDirectionVariationResponse] = []
    for item in stored:
        child_root_id = str(item.get("project_root_id", ""))
        child = db.get(Project, child_root_id) if child_root_id else None
        if (
            child is None
            or child.owner != decision.owner
            or child.branched_from_project_root_id != project.root_id
            or child.branched_from_asset_id != item.get("candidate_id")
            or child.variation_label != item.get("label")
            or child.family_id != item.get("family_id")
            or child.variation_index != item.get("variation_index")
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "the committed Create decision has incomplete sibling "
                    "variation evidence"
                ),
            )
        retained.append(CreativeDirectionVariationResponse(
            status="variation_created",
            family_id=str(item["family_id"]),
            variation_index=int(item["variation_index"]),
            source_project_id=project.root_id,
            source_asset_id=str(item["candidate_id"]),
            project=project_detail(db, child),
        ))
    return CreativeDirectionCommitResponse(
        project=project_detail(db, project),
        retained_variations=retained,
    )


def _existing_creative_direction_commit(
    db: Session,
    *,
    project_id: str,
    request: CreativeDirectionCommitRequest,
) -> CreativeDirectionCommitResponse | None:
    project = db.get(Project, project_id)
    decision = db.get(StudioCreateDecisionRecord, project_id)
    if project is None or decision is None:
        return None
    return _creative_direction_commit_response(
        db, project=project, decision=decision, request=request,
    )


@router.post(
    "/{project_id}/creative-directions/commit",
    response_model=CreativeDirectionCommitResponse,
    response_model_exclude_none=True,
)
def commit_project_creative_directions(
    project_id: str,
    request: CreativeDirectionCommitRequest,
    db: DbSession,
    principal: PrincipalDep,
):
    """Atomically choose Original and retain up to three sibling directions.

    Candidate selection, family creation, sibling projects, immutable branch
    evidence, and Create-job settlement share one transaction.  The durable
    decision row makes an exact retry safe after a timeout or concurrent
    request; a different or partial prior decision fails closed.
    """

    principal_actor(principal, request.created_by)
    project = db.scalar(select(Project).where(
        Project.root_id == project_id,
    ).with_for_update())
    if project is None:
        raise HTTPException(status_code=404, detail="creative project not found")
    if project.owner != request.created_by:
        raise HTTPException(
            status_code=403,
            detail="only the project owner may commit a Create review",
        )

    existing = db.scalar(select(StudioCreateDecisionRecord).where(
        StudioCreateDecisionRecord.project_root_id == project_id,
    ).with_for_update())
    if existing is not None:
        return _creative_direction_commit_response(
            db, project=project, decision=existing, request=request,
        )

    root = db.scalar(select(ImageAsset).where(
        ImageAsset.id == project.root_id,
    ).with_for_update())
    if root is None:
        raise HTTPException(status_code=404, detail="creative project not found")
    if root.design_id is not None:
        raise HTTPException(
            status_code=409,
            detail="Create directions can be committed only before design confirmation",
        )
    if project.selected_candidate_asset_id is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "the project has a partial legacy Create selection; reload "
                "without committing another direction set"
            ),
        )
    prior_branch = db.scalar(select(Project.root_id).where(
        Project.branched_from_project_root_id == project.root_id,
    ).limit(1))
    if prior_branch is not None:
        raise HTTPException(
            status_code=409,
            detail="the project already has sibling variations outside this decision",
        )

    retained_request = _normalized_retained_directions(request)
    requested_ids = {
        request.selected_candidate_id,
        *(item["candidate_id"] for item in retained_request),
    }
    locked_candidates = list(db.scalars(
        select(ImageAsset)
        .where(ImageAsset.id.in_(requested_ids))
        .order_by(ImageAsset.id)
        .with_for_update()
    ))
    by_id = {candidate.id: candidate for candidate in locked_candidates}
    if set(by_id) != requested_ids:
        raise HTTPException(status_code=404, detail="creative candidate not found")
    for candidate in locked_candidates:
        if (
            candidate.root_id != project.root_id
            or candidate.capability != "CREATIVE_RENDER"
            or candidate.design_version is not None
            or candidate.design_id is not None
            or not is_primary_revision(candidate)
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "every committed direction must be a pre-spec creative "
                    "candidate from this project"
                ),
            )

    selected = by_id[request.selected_candidate_id]
    try:
        available_outputs = len(list(db.scalars(select(ImageAsset.id).where(
            ImageAsset.root_id == project.root_id,
            ImageAsset.capability == "CREATIVE_RENDER",
            ImageAsset.design_version.is_(None),
        ))))
        if request.studio_job_id is not None:
            settle_create_studio_job_selection(
                db,
                job_id=request.studio_job_id,
                owner=request.created_by,
                project_root_id=project.root_id,
                source_revision_id=selected.id,
                available_outputs=available_outputs,
            )

        project.selected_candidate_asset_id = selected.id
        project.updated_at = utcnow()
        ensure_project_family(db, project)

        retained_records: list[dict[str, object]] = []
        for retained in retained_request:
            result = fork_project_variation(
                db,
                project_root_id=project.root_id,
                source_asset_id=retained["candidate_id"],
                expected_active_asset_id=selected.id,
                expected_design_version=None,
                variation_label=retained["label"],
                created_by=request.created_by,
                allow_unselected_creative_candidate=True,
                commit=False,
            )
            retained_records.append({
                "candidate_id": retained["candidate_id"],
                "label": retained["label"],
                "family_id": result.family_id,
                "variation_index": result.variation_index,
                "project_root_id": result.project_root_id,
                "asset_id": result.asset_id,
            })

        decision = StudioCreateDecisionRecord(
            project_root_id=project.root_id,
            owner=project.owner,
            selected_candidate_asset_id=selected.id,
            retained_directions=retained_records,
            studio_job_id=request.studio_job_id,
            created_by=request.created_by,
            committed_at=utcnow(),
        )
        db.add(decision)
        db.flush()
        db.commit()
    except (StudioHistoryError, StudioJobAccountingError, IntegrityError) as exc:
        db.rollback()
        retry = _existing_creative_direction_commit(
            db, project_id=project_id, request=request,
        )
        if retry is not None:
            return retry
        if isinstance(exc, StudioHistoryError):
            raise HTTPException(
                status_code=exc.status_code, detail=exc.detail,
            ) from exc
        if isinstance(exc, StudioJobAccountingError):
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise HTTPException(
            status_code=409,
            detail="another Create decision committed first; reload and retry",
        ) from exc
    except Exception:
        db.rollback()
        raise

    db.refresh(project)
    return _creative_direction_commit_response(
        db, project=project, decision=decision, request=request,
    )


@router.post(
    "/{project_id}/creative-candidates/{candidate_id}/select",
    response_model=ProjectDetail,
    response_model_exclude_none=True,
)
def select_project_creative_candidate(
    project_id: str,
    candidate_id: str,
    request: CreativeCandidateSelectRequest,
    db: DbSession,
    principal: PrincipalDep,
):
    """Persist the designer's chosen visual without inventing a specification."""
    principal_actor(principal, request.created_by)
    project = db.scalar(
        select(Project).where(Project.root_id == project_id).with_for_update()
    )
    candidate = db.scalar(
        select(ImageAsset).where(ImageAsset.id == candidate_id).with_for_update()
    )
    if project is None or candidate is None:
        raise HTTPException(status_code=404, detail="creative candidate not found")
    if project.owner != request.created_by:
        raise HTTPException(
            status_code=403,
            detail="only the project owner may review a creative candidate",
        )
    root = candidate if candidate.id == project_id else db.get(ImageAsset, project_id)
    if root is None or root.design_id is not None:
        raise HTTPException(
            status_code=409,
            detail="candidate selection is available only before design confirmation",
        )
    if (candidate.root_id != project.root_id
            or candidate.capability != "CREATIVE_RENDER"
            or candidate.design_version is not None):
        raise HTTPException(
            status_code=409,
            detail="the selected asset is not a pre-spec creative candidate",
        )
    if (
        project.selected_candidate_asset_id not in (None, candidate.id)
        and db.scalar(
            select(Project.root_id).where(
                Project.branched_from_project_root_id == project.root_id
            ).limit(1)
        ) is not None
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "the Original direction is locked after a sibling variation "
                "has been saved"
            ),
        )
    if (
        request.studio_job_id is not None
        and project.selected_candidate_asset_id not in (None, candidate.id)
    ):
        raise HTTPException(
            status_code=409,
            detail="the project already selected another creative candidate",
        )
    if request.studio_job_id is not None:
        available_outputs = len(list(db.scalars(select(ImageAsset.id).where(
            ImageAsset.root_id == project.root_id,
            ImageAsset.capability == "CREATIVE_RENDER",
            ImageAsset.design_version.is_(None),
        ))))
        try:
            settle_create_studio_job_selection(
                db,
                job_id=request.studio_job_id,
                owner=request.created_by,
                project_root_id=project.root_id,
                source_revision_id=candidate.id,
                available_outputs=available_outputs,
            )
        except StudioJobAccountingError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    if project.selected_candidate_asset_id != candidate.id:
        project.selected_candidate_asset_id = candidate.id
        project.updated_at = utcnow()
    ensure_project_family(db, project)
    db.commit()
    db.refresh(project)
    return project_detail(db, project)


@router.post(
    "/from-prompt", status_code=201, response_model=ProjectDetail,
    response_model_exclude_none=True,
)
def create_project_from_prompt(
    request: ProjectFromPromptRequest,
    db: DbSession,
    generate: CreativePromptGeneratorDep,
    principal: PrincipalDep,
):
    """Create several category-neutral visual concepts before specification.

    Every provider/QA run finishes before the project transaction. The outputs
    remain designer-review candidates and cannot enter approval or factory
    export until one is selected and bound to a confirmed exact specification.
    """
    actor = principal_actor(principal, request.owner)
    try:
        studio_job = require_provider_studio_job(
            db,
            job_id=request.studio_job_id,
            owner=actor,
            action_id="create",
            requested_outputs=request.variation_count,
        )
    except ProviderStudioJobError as exc:
        return provider_studio_job_error_response(exc)
    generated = []
    for offset in range(request.variation_count):
        variant = request.starting_variant + offset
        try:
            result = generate(request.prompt, variant)
        except ImageAgentError as exc:
            observed_run_ids = [
                persist_image_agent_result(
                    db, prior, created_by=request.owner)
                for prior in generated
            ]
            failed_run_id = (
                persist_image_agent_failure(
                    db, exc.plan, exc, created_by=request.owner)
                if exc.plan is not None else None
            )
            response = image_agent_error_response(
                exc, image_run_id=failed_run_id)
            if observed_run_ids:
                response.headers["X-Facetta-Completed-Run-Count"] = str(
                    len(observed_run_ids))
            return response
        if result.plan.operation.value != "CREATIVE_GENERATE":
            return JSONResponse(status_code=500, content={
                "error_category": "validation_failure",
                "detail": "creative prompt generator returned the wrong operation",
            })
        if _uploaded_media_type(result.image_bytes) is None:
            persist_image_agent_result(db, result, created_by=request.owner)
            return JSONResponse(status_code=422, content={
                "error_category": "quality_failure",
                "detail": "image agent returned an unsupported render format",
            })
        generated.append(result)

    persisted = persist_prompt_creative_project(
        db,
        candidates=tuple(CreativeCandidateInput(
            image=result.image_bytes,
            instruction=request.prompt,
            image_run=result,
        ) for result in generated),
        owner=request.owner,
        title=request.title,
        collection=request.collection,
        tags=request.tags,
        studio_job=studio_job,
    )
    project = db.get(Project, persisted.root_id)
    if project is None:  # pragma: no cover - transaction invariant
        raise RuntimeError("persisted prompt project is unavailable")
    db.commit()
    db.refresh(project)
    return project_detail(db, project)


@router.post(
    "/from-drawing", status_code=201, response_model=ProjectDetail,
    response_model_exclude_none=True,
)
def create_project_from_drawing(
    request: ProjectFromDrawingRequest,
    db: DbSession,
    generate: CreativeGeneratorDep,
    principal: PrincipalDep,
):
    """Create reviewable beauty renders without inventing a factory spec.

    Provider and QA work completes before the one product transaction. A hard
    QA/provider failure leaves no Project, ImageAsset, Design, or DesignVersion.
    Completed attempt evidence is still retained as append-only observability.
    """
    actor = principal_actor(principal, request.owner)
    try:
        studio_job = require_provider_studio_job(
            db,
            job_id=request.studio_job_id,
            owner=actor,
            action_id="create",
            requested_outputs=request.variation_count,
        )
    except ProviderStudioJobError as exc:
        return provider_studio_job_error_response(exc)
    try:
        image = base64.b64decode(request.image_base64, validate=True)
    except (binascii.Error, ValueError):
        return JSONResponse(status_code=422, content={
            "error_category": "validation_failure",
            "detail": "image_base64 is not valid base64",
        })
    detected = _uploaded_media_type(image)
    if detected is None:
        return JSONResponse(status_code=422, content={
            "error_category": "validation_failure",
            "detail": "upload must be a PNG, JPEG, or WebP image",
        })
    if request.media_type is not None and request.media_type != detected:
        return JSONResponse(status_code=422, content={
            "error_category": "validation_failure",
            "detail": (f"media_type says {request.media_type}, but the upload "
                       f"is {detected}"),
        })

    decoded_references: list[CreativeReferenceImage] = []
    for reference in request.references:
        try:
            reference_image = base64.b64decode(
                reference.image_base64, validate=True)
        except (binascii.Error, ValueError):
            return JSONResponse(status_code=422, content={
                "error_category": "validation_failure",
                "code": "creative_reference_invalid_base64",
                "detail": (
                    f"{reference.role} image_base64 is not valid base64"
                ),
            })
        reference_media_type = _uploaded_media_type(reference_image)
        if reference_media_type is None:
            return JSONResponse(status_code=422, content={
                "error_category": "validation_failure",
                "code": "creative_reference_unsupported_media",
                "detail": (
                    f"{reference.role} must be a PNG, JPEG, or WebP image"
                ),
            })
        if reference.media_type != reference_media_type:
            return JSONResponse(status_code=422, content={
                "error_category": "validation_failure",
                "code": "creative_reference_media_mismatch",
                "detail": (
                    f"{reference.role} media_type says {reference.media_type}, "
                    f"but the upload is {reference_media_type}"
                ),
            })
        decoded_references.append(CreativeReferenceImage(
            role=reference.role,
            image=reference_image,
            media_type=reference_media_type,
        ))

    render_source = image
    render_source_media_type: str | None = None
    render_source_instruction: str | None = None
    effective_instruction = request.instruction.strip()
    if request.source_region is not None:
        region = request.source_region
        try:
            render_source = crop_normalized_region(
                image,
                x=region.x,
                y=region.y,
                width=region.width,
                height=region.height,
            )
        except ImageRegionError as exc:
            return JSONResponse(status_code=422, content={
                "error_category": "validation_failure",
                "code": "source_region_invalid",
                "detail": str(exc),
            })
        render_source_media_type = sniff_media_type(render_source)
        coordinates = (
            f"normalized crop x={region.x:.4f}, y={region.y:.4f}, "
            f"width={region.width:.4f}, height={region.height:.4f}"
        )
        description = (
            request.source_region_description.strip()
            if request.source_region_description else
            "Designer-selected jewelry view"
        )
        render_source_instruction = f"{description}; {coordinates}"
        effective_instruction = (
            f"{effective_instruction}\n\n"
            "SOURCE ISOLATION: Render only the designer-selected source crop "
            f"({description}). Treat it as one view of one finished piece. "
            "Do not reconstruct, combine, or count components from surrounding "
            "views outside this exact crop."
        )

    quality_source = render_source
    render_source_capability: Literal[
        "CREATIVE_SOURCE_REGION", "CREATIVE_REFERENCE_BOARD"
    ] = "CREATIVE_SOURCE_REGION"
    if decoded_references:
        isolated_source_instruction = render_source_instruction
        try:
            board = build_creative_reference_board(
                render_source,
                tuple(decoded_references),
            )
        except (OSError, ValueError) as exc:
            return JSONResponse(status_code=422, content={
                "error_category": "validation_failure",
                "code": "creative_reference_invalid_image",
                "detail": f"a role-labeled reference could not be decoded: {exc}",
            })
        render_source = board.image
        render_source_media_type = "image/png"
        render_source_instruction = (
            f"{isolated_source_instruction}\n\n{board.instruction}"
            if isolated_source_instruction is not None
            else board.instruction
        )
        render_source_capability = "CREATIVE_REFERENCE_BOARD"
        effective_instruction = (
            f"{effective_instruction}\n\nREFERENCE ROLE CONTRACT:\n"
            f"{board.instruction}"
        )

    generated = []
    for offset in range(request.variation_count):
        variant = request.starting_variant + offset
        try:
            if decoded_references:
                result = invoke_creative_render_generator(
                    generate,
                    render_source,
                    effective_instruction,
                    variant,
                    quality_source_image=quality_source,
                )
            else:
                result = generate(render_source, effective_instruction, variant)
        except ImageAgentError as exc:
            observed_run_ids = [
                persist_image_agent_result(
                    db, prior, created_by=request.owner)
                for prior in generated
            ]
            failed_run_id = (
                persist_image_agent_failure(
                    db, exc.plan, exc, created_by=request.owner)
                if exc.plan is not None else None
            )
            response = image_agent_error_response(
                exc, image_run_id=failed_run_id)
            if observed_run_ids:
                response.headers["X-Facetta-Completed-Run-Count"] = str(
                    len(observed_run_ids))
            return response
        if result.plan.operation.value != "REFERENCE_RENDER":
            return JSONResponse(status_code=500, content={
                "error_category": "validation_failure",
                "detail": "creative generator returned the wrong operation",
            })
        if _uploaded_media_type(result.image_bytes) is None:
            persist_image_agent_result(db, result, created_by=request.owner)
            return JSONResponse(status_code=422, content={
                "error_category": "quality_failure",
                "detail": "image agent returned an unsupported render format",
            })
        generated.append(result)

    persisted = persist_creative_project(
        db,
        source_image=image,
        source_media_type=detected,
        source_kind=request.source_kind,
        render_source_image=(
            render_source
            if request.source_region is not None or decoded_references
            else None
        ),
        render_source_media_type=render_source_media_type,
        render_source_instruction=render_source_instruction,
        render_source_capability=render_source_capability,
        reference_sources=tuple(SourceAssetInput(
            image=reference.image,
            media_type=reference.media_type,
            capability={
                "material_style": "CREATIVE_REFERENCE_MATERIAL_STYLE",
                "construction_detail": "CREATIVE_REFERENCE_CONSTRUCTION_DETAIL",
                "brand_direction": "CREATIVE_REFERENCE_BRAND_DIRECTION",
            }[reference.role],
            instruction=(
                f"Role-labeled {reference.role} reference; SHA-256 "
                f"{hashlib.sha256(reference.image).hexdigest()}"
            ),
        ) for reference in decoded_references),
        candidates=tuple(CreativeCandidateInput(
            image=result.image_bytes,
            instruction=effective_instruction,
            image_run=result,
        ) for result in generated),
        owner=request.owner,
        title=request.title,
        collection=request.collection,
        tags=request.tags,
        studio_job=studio_job,
    )
    project = db.get(Project, persisted.root_id)
    if project is None:  # pragma: no cover - transaction invariant
        raise RuntimeError("persisted creative project is unavailable")
    db.commit()
    db.refresh(project)
    return project_detail(db, project)


@router.post(
    "/{project_id}/creative-candidates/{candidate_id}/draft",
    response_model=Spec,
    response_model_exclude_none=True,
)
def draft_project_creative_candidate(
    project_id: str,
    candidate_id: str,
    request: CreativeCandidateDraftRequest,
    db: DbSession,
):
    """Read one selected creative candidate into an unpersisted draft spec."""
    _project, candidate = _owned_creative_candidate(
        db,
        project_id=project_id,
        candidate_id=candidate_id,
        actor=request.created_by,
    )
    result = from_photo(PhotoRequest(
        image_base64=base64.b64encode(bytes(candidate.image)).decode("ascii"),
        media_type=candidate.media_type,
        notes=request.notes,
        created_by=request.created_by,
        run_independent_audit=request.run_independent_audit,
    ))
    return result


@router.post(
    "/{project_id}/creative-candidates/{candidate_id}/confirm-design",
    response_model=StudioConfirmDesignResponse,
    response_model_exclude_none=True,
)
def confirm_project_creative_candidate_design(
    project_id: str,
    candidate_id: str,
    request: CreativeCandidateDraftRequest,
    db: DbSession,
    principal: PrincipalDep,
):
    """Read one candidate into designer facts without persisting a design."""
    principal_actor(principal, request.created_by)
    _project, candidate = _owned_current_confirmable_pre_spec_asset(
        db,
        project_id=project_id,
        candidate_id=candidate_id,
        actor=request.created_by,
    )
    candidate_bytes = bytes(candidate.image)
    draft = from_photo(PhotoRequest(
        image_base64=base64.b64encode(candidate_bytes).decode("ascii"),
        media_type=candidate.media_type,
        notes=request.notes,
        created_by=request.created_by,
        run_independent_audit=request.run_independent_audit,
    ))
    if isinstance(draft, JSONResponse):
        return draft
    if not isinstance(draft, Spec):
        raise RuntimeError("candidate design reader returned an invalid contract")
    token = secrets.token_urlsafe(32)
    now = utcnow()
    expires_at = now + timedelta(minutes=30)
    candidate_sha256 = hashlib.sha256(candidate_bytes).hexdigest()
    visual_hash = spec_visual_hash(draft)
    # Expired unused drafts have no provenance value. Consumed drafts remain
    # durable evidence and are never removed by this opportunistic cleanup.
    db.execute(delete(StudioConfirmationDraft).where(
        StudioConfirmationDraft.expires_at <= now,
        StudioConfirmationDraft.consumed_at.is_(None),
    ))
    db.add(StudioConfirmationDraft(
        id=new_id("scd"),
        token_sha256=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        owner=_project.owner,
        project_root_id=_project.root_id,
        candidate_asset_id=candidate.id,
        candidate_sha256=candidate_sha256,
        spec_visual_hash=visual_hash,
        spec=draft.model_dump(mode="json"),
        created_at=now,
        expires_at=expires_at,
    ))
    db.commit()
    return build_studio_confirm_design_response(
        confirmation_token=token,
        expires_at=expires_at,
        candidate_id=candidate.id,
        candidate_sha256=candidate_sha256,
        spec=draft,
    )


@router.post(
    "/{project_id}/creative-candidates/{candidate_id}/"
    "dimensioned-profile/confirm",
    response_model=CreativeCandidateProfileConfirmResponse,
)
def confirm_project_creative_candidate_profile(
    project_id: str,
    candidate_id: str,
    request: CreativeCandidateProfileConfirmRequest,
    db: DbSession,
):
    """Bind designer-entered millimeter geometry to exact candidate bytes.

    This is a pure pre-promotion draft step. It writes no DesignVersion or
    asset, never estimates points itself, and cannot mutate an approved
    project. The returned spec must still pass source re-audit and normal
    candidate promotion before it can become factory truth.
    """

    _project, candidate = _owned_creative_candidate(
        db,
        project_id=project_id,
        candidate_id=candidate_id,
        actor=request.created_by,
    )
    existing = next((
        element
        for element in request.spec.design_form.elements
        if element.element_id == request.element_id
    ), None)
    if existing is None:
        return JSONResponse(status_code=422, content={
            "error_category": "validation_failure",
            "code": "form_element_not_found",
            "detail": (
                "the candidate draft has no stable design-form element "
                f"{request.element_id!r}"
            ),
        })
    candidate_bytes = bytes(candidate.image)
    candidate_sha256 = hashlib.sha256(candidate_bytes).hexdigest()
    profile = request.profile
    definition = DimensionedProfileDefinition(
        kind="dimensioned_profile",
        scope="full_assembly",
        view=profile.view,
        coordinate_system="x_right_y_up",
        paths=profile.paths,
        profile_thickness_mm=profile.profile_thickness_mm,
        dimension_status=profile.dimension_status,
        source_asset_id=candidate.id,
        source_asset_sha256=candidate_sha256,
        confirmed_by=request.created_by,
        confirmed_at=utcnow(),
        manufacturing_notes=profile.manufacturing_notes,
    )
    try:
        updated = confirm_dimensioned_form_element(
            request.spec,
            element_id=request.element_id,
            definition=definition,
        )
    except DesignFormRevisionError as exc:
        return JSONResponse(status_code=422, content={
            "error_category": "validation_failure",
            "code": exc.code,
            "detail": exc.detail,
        })
    validated = validate_spec(updated, get_vocabulary())
    if not validated.ok:
        return JSONResponse(status_code=422, content={
            "error_category": "validation_failure",
            "code": "dimensioned_profile_spec_invalid",
            "detail": [issue.as_detail() for issue in validated.issues],
        })
    blockers = sheet_readiness_blockers(updated)
    coverage = updated.source_component_coverage
    source_reaudit_required = bool(
        coverage is not None
        and coverage.audited_spec_visual_hash != spec_visual_hash(updated)
    )
    return CreativeCandidateProfileConfirmResponse(
        spec=updated,
        element_id=request.element_id,
        candidate_asset_id=candidate.id,
        candidate_sha256=candidate_sha256,
        previous_definition_kind=existing.definition.kind,
        definition=definition,
        source_reaudit_required=source_reaudit_required,
        factory_ready=not blockers,
        sheet_authority=(
            "factory_profile"
            if not blockers else "preliminary_not_for_production"
        ),
        blockers=tuple(
            DimensionedProfileBlockerSummary(
                code=blocker.code,
                detail=blocker.detail,
            )
            for blocker in blockers
        ),
    )


@router.post(
    "/{project_id}/creative-candidates/{candidate_id}/source-coverage/resolve",
)
def resolve_project_creative_candidate_coverage(
    project_id: str,
    candidate_id: str,
    request: CreativeCandidateCoverageResolveRequest,
    db: DbSession,
):
    """Correct candidate mappings and optionally re-audit exact stored bytes."""
    _project, candidate = _owned_creative_candidate(
        db,
        project_id=project_id,
        candidate_id=candidate_id,
        actor=request.created_by,
    )
    return resolve_source_coverage(SourceCoverageResolveRequest(
        spec=request.spec,
        source_image_base64=(
            base64.b64encode(bytes(candidate.image)).decode("ascii")
            if request.run_independent_audit else None
        ),
        resolutions=request.resolutions,
        created_by=request.created_by,
        run_independent_audit=request.run_independent_audit,
    ))


@router.post(
    "/{project_id}/creative-candidates/{candidate_id}/source-coverage/confirm",
)
def confirm_project_creative_candidate_coverage(
    project_id: str,
    candidate_id: str,
    request: CreativeCandidateCoverageConfirmRequest,
    db: DbSession,
):
    """Bind explicit designer decisions to exact stored candidate bytes."""
    _project, candidate = _owned_creative_candidate(
        db,
        project_id=project_id,
        candidate_id=candidate_id,
        actor=request.created_by,
    )
    confirmed = confirm_source_coverage(SourceCoverageConfirmRequest(
        spec=request.spec,
        source_image_base64=base64.b64encode(bytes(candidate.image)).decode("ascii"),
        confirmations=request.confirmations,
        created_by=request.created_by,
    ))
    if isinstance(confirmed, JSONResponse):
        return confirmed
    if not isinstance(confirmed, SourceCoverageConfirmResponse):
        raise RuntimeError("candidate confirmation returned an invalid contract")
    coverage = confirmed.spec.source_component_coverage
    if coverage is None:  # pragma: no cover - confirmation invariant
        raise RuntimeError("candidate confirmation lost source coverage")
    valid_paths = valid_source_component_spec_paths(confirmed.spec)
    return SourceCoverageResolveResponse(
        spec=confirmed.spec,
        source_kind=coverage.source_kind,
        components=coverage.components,
        valid_spec_paths=valid_paths,
        changed_component_ids=confirmed.confirmed_component_ids,
        invalidated_audit_component_ids=(),
        blockers=confirmed.blockers,
        factory_ready=confirmed.factory_ready,
        legacy_provenance=False,
        resolved_by=confirmed.confirmed_by,
        audit=SourceCoverageAuditSummary(
            requested=False,
            status=("pass" if confirmed.factory_ready else "review_required"),
            audited_component_ids=tuple(
                component.component_id
                for component in coverage.components
                if component.independent_audit is not None
            ),
            blocker_count=len(confirmed.blockers),
        ),
    )


@router.post(
    "/{project_id}/creative-candidates/{candidate_id}/promote",
    response_model=ProjectDetail,
    response_model_exclude_none=True,
)
def promote_project_creative_candidate(
    project_id: str,
    candidate_id: str,
    request: CreativeCandidatePromoteRequest,
    db: DbSession,
    principal: PrincipalDep,
):
    """Bind one chosen candidate to designer-confirmed immutable spec v1."""
    principal_actor(principal, request.created_by)
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="creative project not found")
    if project.owner != request.created_by:
        return JSONResponse(status_code=403, content={
            "code": "creative_project_owner_mismatch",
            "error_category": "authorization_failure",
            "detail": "only the project owner may promote a creative candidate",
        })
    try:
        promote_creative_candidate(
            db,
            root_id=project_id,
            candidate_asset_id=candidate_id,
            created_by=request.created_by,
            confirmation_token=request.confirmation_token,
        )
    except ValueError as exc:
        return JSONResponse(status_code=409, content={
            "code": "creative_candidate_promotion_conflict",
            "error_category": "conflict",
            "detail": str(exc),
        })
    return project_detail(db, project)


@router.post(
    "/from-image", status_code=201, response_model=ProjectDetail,
    response_model_exclude_none=True, deprecated=True,
)
def create_project_from_image(
    request: ProjectFromImageRequest,
    db: DbSession,
    principal: PrincipalDep,
):
    """Deprecated development compatibility for confirmed image import."""
    return confirmed_import_response(
        request,
        db,
        principal,
        source_audit_policy="legacy_compatible",
    )


def confirmed_import_response(
    request: ProjectFromImageRequest,
    db: Session,
    principal: AuthenticatedPrincipal,
    *,
    source_audit_policy: ConfirmedImportSourceAuditPolicy = "exact",
):
    """Shared authenticated HTTP adapter for canonical and legacy routes."""
    actor = principal_actor(principal, request.owner)
    try:
        result = import_confirmed_project(
            db,
            ConfirmedImportCommand(
                image_base64=request.image_base64,
                media_type=request.media_type,
                spec=request.spec,
                actor=actor,
                title=request.title,
                collection=request.collection,
                tags=tuple(request.tags),
                source_audit_policy=source_audit_policy,
            ),
        )
    except ConfirmedImportRejected as exc:
        return JSONResponse(status_code=exc.status_code, content=exc.content)
    project = db.get(Project, result.root_id)
    if project is None:  # pragma: no cover - committed service invariant
        raise RuntimeError("confirmed import committed without its project")
    return project_detail(db, project)


def _brief_warning_response(
    candidate: BriefWarningCandidate,
) -> JSONResponse:
    operation = (
        "CONCEPT_GENERATE" if candidate.stage == "concept"
        else "SPEC_RENDER"
    )
    preview_url = (
        f"/projects/from-brief/candidates/{candidate.candidate_id}/image"
    )
    return JSONResponse(status_code=202, content={
        "status": "review_required",
        "project": None,
        "image_run_id": candidate.run_id,
        "quality_report": candidate.generation.quality_report,
        "warning_candidate": {
            "run_id": candidate.run_id,
            "candidate_id": candidate.candidate_id,
            "preview_url": preview_url,
            "qa": candidate.generation.quality_report,
            "operation": operation,
            "requested_change": candidate.brief,
            "creation_stage": candidate.stage,
        },
    })


def _store_brief_warning(
    db: Session,
    generated: BriefProjectGeneration,
    request: ProjectFromBriefRequest,
    *,
    concept_warning_run_id: str | None = None,
) -> BriefWarningCandidate:
    stage = str(generated.quality_report.get("stage", "spec_render"))
    if stage == "concept":
        warning_result = generated.concept_run
        normalized_stage: Literal["concept", "spec_render"] = "concept"
    else:
        warning_result = generated.spec_render_run
        normalized_stage = "spec_render"
    if warning_result is None:
        raise ValueError("warning generation did not include its image run")
    run_id = persist_image_agent_result(
        db, warning_result, created_by=request.owner)
    return store_brief_warning_candidate(
        run_id=run_id,
        stage=normalized_stage,
        generation=generated,
        brief=request.brief,
        variant=request.variant,
        owner=request.owner,
        title=request.title,
        collection=request.collection,
        tags=tuple(request.tags),
        concept_warning_run_id=concept_warning_run_id,
    )


def _persist_brief_generation(
    db: Session,
    generated: BriefProjectGeneration,
    request: ProjectFromBriefRequest,
    *,
    concept_warning_run_id: str | None = None,
    spec_warning_run_id: str | None = None,
) -> dict | JSONResponse:
    if generated.spec is None:
        return JSONResponse(status_code=422, content={
            "error_category": "validation_failure",
            "detail": "the image agent did not produce a validated ring spec",
        })
    spec, error = _validate_ring_spec(generated.spec)
    if error:
        return error
    if _uploaded_media_type(generated.spec_render) is None:
        return JSONResponse(status_code=422, content={
            "error_category": "quality_failure",
            "detail": "the image agent returned an unsupported spec render",
            "quality_report": generated.quality_report,
        })
    if _uploaded_media_type(generated.concept_image) is None:
        return JSONResponse(status_code=422, content={
            "error_category": "quality_failure",
            "detail": "the image agent returned an unsupported source concept",
            "quality_report": generated.quality_report,
        })
    result = persist_project_v1(
        db,
        PersistedProjectInput(
            spec=spec,
            primary_image=generated.spec_render,
            primary_capability="SPEC_RENDER",
            primary_instruction=request.brief,
            primary_image_run=(generated.spec_render_run
                               if spec_warning_run_id is None else None),
            reviewed_primary_run_id=spec_warning_run_id,
            sources=(SourceAssetInput(
                image=generated.concept_image,
                capability="SOURCE_CONCEPT",
                instruction=request.brief,
                image_run=(generated.concept_run
                           if concept_warning_run_id is None else None),
                reviewed_image_run_id=concept_warning_run_id,
            ),),
        ),
        owner=request.owner,
        title=request.title or request.brief,
        collection=request.collection,
        tags=request.tags,
    )
    project = db.get(Project, result.root_id)
    if project is None:  # pragma: no cover - transaction invariant
        raise RuntimeError("persisted project is unavailable")
    return project_detail(db, project)


@router.post(
    "/from-brief", status_code=201, response_model=ProjectDetail,
    response_model_exclude_none=True,
    responses={202: {"model": ProjectCreationWarning}},
    deprecated=True,
)
def create_project_from_brief(
    request: ProjectFromBriefRequest,
    db: DbSession,
    generate: BriefGeneratorDep,
    principal: PrincipalDep,
):
    """Create a ring through the injected, QA-gated jewelry image agent."""
    principal_actor(principal, request.owner)
    try:
        generated: BriefProjectGeneration = generate(
            request.brief, request.variant)
    except BriefProjectGeneratorUnavailable as exc:
        return JSONResponse(status_code=503, content={
            "error_category": "provider_unavailable", "detail": str(exc)})
    except RenderUnavailable as exc:
        return render_unavailable_response(exc)
    except ConceptInvalid as exc:
        return JSONResponse(status_code=422, content={
            "error_category": "validation_failure",
            "detail": [issue.as_detail() for issue in exc.issues],
            "corrections": exc.corrections,
        })
    except ImageAgentError as exc:
        run_id = (persist_image_agent_failure(
            db, exc.plan, exc, created_by=request.owner)
            if exc.plan is not None else None)
        return image_agent_error_response(exc, image_run_id=run_id)

    if generated.quality_verdict == "warn":
        return _brief_warning_response(
            _store_brief_warning(db, generated, request))
    if generated.quality_verdict != "pass":
        return JSONResponse(status_code=422, content={
            "error_category": "quality_failure",
            "detail": "candidate failed image quality gates",
            "quality_report": generated.quality_report,
        })
    return _persist_brief_generation(db, generated, request)


@router.get(
    "/from-brief/candidates/{candidate_id}/image",
    deprecated=True,
)
def get_brief_warning_image(candidate_id: str, principal: PrincipalDep):
    try:
        candidate = get_brief_warning_candidate(candidate_id)
    except WarningCandidateUnavailable as exc:
        return JSONResponse(status_code=410, content={
            "code": "warning_candidate_unavailable",
            "category": "conflict",
            "detail": str(exc),
        })
    if not principal.local_unbound and candidate.owner != principal.subject:
        raise HTTPException(status_code=404, detail="warning candidate unavailable")
    return Response(
        content=candidate.image_bytes,
        media_type=candidate.media_type,
        headers={"Cache-Control": "private, no-store"},
    )


@router.post(
    "/from-brief/candidates/{candidate_id}/accept",
    response_model=ProjectDetail,
    response_model_exclude_none=True,
    responses={202: {"model": ProjectCreationWarning}},
    deprecated=True,
)
def accept_brief_warning(
    candidate_id: str,
    request: BriefWarningAcceptRequest,
    db: DbSession,
    principal: PrincipalDep,
):
    principal_actor(principal, request.created_by)
    try:
        candidate = get_brief_warning_candidate(candidate_id)
    except WarningCandidateUnavailable as exc:
        return JSONResponse(status_code=410, content={
            "code": "warning_candidate_unavailable",
            "category": "conflict",
            "detail": str(exc),
        })
    if request.created_by != candidate.owner:
        return JSONResponse(status_code=403, content={
            "code": "warning_candidate_owner_mismatch",
            "category": "authorization",
            "detail": "only the designer who created this candidate may accept it",
        })

    project_request = ProjectFromBriefRequest(
        brief=candidate.brief,
        owner=candidate.owner,
        title=candidate.title,
        collection=candidate.collection,
        tags=list(candidate.tags),
        variant=candidate.variant,
    )
    concept_warning_run_id = candidate.concept_warning_run_id
    spec_warning_run_id: str | None = None
    generated = candidate.generation
    if candidate.stage == "concept":
        concept_warning_run_id = candidate.run_id
        if generated.concept_run is None:
            return JSONResponse(status_code=409, content={
                "code": "warning_candidate_incomplete",
                "category": "conflict",
                "detail": "the reviewed concept no longer has its image-agent evidence",
            })
        from facetta.trusted_brief import continue_trusted_brief_project

        try:
            generated = continue_trusted_brief_project(
                candidate.brief,
                candidate.variant,
                generated.concept_run,
            )
        except RenderUnavailable as exc:
            return render_unavailable_response(exc)
        except ConceptInvalid as exc:
            return JSONResponse(status_code=422, content={
                "error_category": "validation_failure",
                "detail": [issue.as_detail() for issue in exc.issues],
                "corrections": exc.corrections,
            })
        except ImageAgentError as exc:
            run_id = (persist_image_agent_failure(
                db, exc.plan, exc, created_by=candidate.owner)
                if exc.plan is not None else None)
            return image_agent_error_response(exc, image_run_id=run_id)
        if generated.quality_verdict == "warn":
            next_candidate = _store_brief_warning(
                db,
                generated,
                project_request,
                concept_warning_run_id=concept_warning_run_id,
            )
            return _brief_warning_response(next_candidate)
    else:
        spec_warning_run_id = candidate.run_id

    if generated.quality_verdict != "pass" and spec_warning_run_id is None:
        return JSONResponse(status_code=422, content={
            "error_category": "quality_failure",
            "detail": "candidate failed image quality gates",
            "quality_report": generated.quality_report,
        })
    return _persist_brief_generation(
        db,
        generated,
        project_request,
        concept_warning_run_id=concept_warning_run_id,
        spec_warning_run_id=spec_warning_run_id,
    )


@router.get(
    "/{root_id}", response_model=ProjectDetail,
    response_model_exclude_none=True,
)
def get_project(root_id: str, db: DbSession, include_images: bool = False):
    project = db.get(Project, root_id)
    if project is None:
        raise HTTPException(status_code=404,
                            detail=f"no project for chain '{root_id}'")
    return project_detail(db, project, include_images=include_images)


@router.post("/{root_id}/render", status_code=201, deprecated=True)
def render_project_revision(
    root_id: str,
    request: ProjectRenderRequest,
    db: DbSession,
):
    """Create a QA-gated beauty render from the exact current project spec."""
    project = db.get(Project, root_id)
    if project is None:
        raise HTTPException(status_code=404,
                            detail=f"no project for chain '{root_id}'")
    if request.studio_job_id is not None and not request.presentation_only:
        return JSONResponse(status_code=422, content={
            "code": "presentation_job_requires_presentation_only",
            "detail": "a Present job cannot create a primary beauty revision",
        })
    chain = project_chain(db, root_id)
    primary = [asset for asset in chain if is_primary_revision(asset)]
    active = primary[-1] if primary else None
    design_id = _linked_design_id(db, project, chain)
    latest = _latest_spec(db, design_id)
    if active is None or latest is None or design_id is None:
        return JSONResponse(status_code=409, content={
            "error_category": "validation_failure",
            "detail": "project has no linked validated specification and source",
        })
    if request.expected_design_version != latest.version:
        return JSONResponse(status_code=409, content={
            "error_category": "stale_version",
            "code": "stale_design_version",
            "expected_design_version": request.expected_design_version,
            "current_design_version": latest.version,
        })
    if active.design_version != latest.version:
        return JSONResponse(status_code=409, content={
            "error_category": "stale_version",
            "code": "stale_asset_revision",
            "detail": (
                "the active image does not represent the current design "
                "version; reload before creating a beauty render"
            ),
            "current_asset_id": active.id,
            "current_design_version": latest.version,
            "active_asset_design_version": active.design_version,
        })
    if (request.expected_asset_id is not None
            and request.expected_asset_id != active.id):
        return JSONResponse(status_code=409, content={
            "error_category": "stale_version",
            "code": "stale_asset_revision",
            "detail": (
                "the active visual changed while this beauty render was open; "
                "reload before rendering"
            ),
            "expected_asset_id": request.expected_asset_id,
            "current_asset_id": active.id,
        })

    source = active
    if request.source_asset_id is not None:
        selected = db.get(ImageAsset, request.source_asset_id)
        if selected is None or selected.root_id != root_id:
            return JSONResponse(status_code=422, content={
                "error_category": "validation_failure",
                "code": "beauty_source_invalid",
                "detail": (
                    "the selected beauty-render source is not an asset in "
                    "this project"
                ),
                "source_asset_id": request.source_asset_id,
            })
        if selected.design_version != latest.version:
            return JSONResponse(status_code=409, content={
                "error_category": "stale_version",
                "code": "stale_beauty_source",
                "detail": (
                    "the selected beauty-render source represents a stale "
                    "specification version"
                ),
                "source_asset_id": selected.id,
                "source_design_version": selected.design_version,
                "current_design_version": latest.version,
            })
        if (selected.id != active.id
                and selected.capability not in {"LINE_ART", "COLORED_LINE_ART"}):
            return JSONResponse(status_code=422, content={
                "error_category": "validation_failure",
                "code": "beauty_source_capability_invalid",
                "detail": (
                    "beauty rendering may use only the current primary visual "
                    "or designer-confirmed LINE_ART/COLORED_LINE_ART"
                ),
                "source_asset_id": selected.id,
                "source_capability": selected.capability,
            })
        if not _same_direct_asset_branch(chain, active, selected):
            return JSONResponse(status_code=409, content={
                "error_category": "stale_version",
                "code": "beauty_source_branch_mismatch",
                "detail": (
                    "the selected colored source belongs to an abandoned "
                    "sibling branch; choose a source on the active visual's "
                    "direct parent chain"
                ),
                "current_asset_id": active.id,
                "source_asset_id": selected.id,
            })
        source = selected
    from facetta.image_agent import ImageOperation, JewelryImageAgent, build_image_plan

    spec = validate_spec(Spec.model_validate(latest.spec), get_vocabulary())
    if not spec.ok:
        return JSONResponse(status_code=422, content={
            "error_category": "validation_failure",
            "detail": [issue.as_detail() for issue in spec.issues],
        })
    coverage_blockers = source_component_factory_blockers(
        spec.spec.source_component_coverage,
        valid_spec_paths=valid_source_component_spec_paths(spec.spec),
        current_spec_visual_hash=spec_visual_hash(spec.spec),
    )
    if coverage_blockers:
        return JSONResponse(status_code=409, content={
            "code": "source_component_coverage_incomplete",
            "category": "validation",
            "detail": (
                "Resolve and independently audit every visible source "
                "component before creating a spec-aligned beauty render."
            ),
            "factory_blockers": [
                blocker.model_dump(mode="json")
                for blocker in coverage_blockers
            ],
        })
    if request.studio_job_id is None:
        try:
            require_provider_studio_job(
                db,
                job_id=None,
                owner=request.created_by,
                action_id="present",
                requested_outputs=1,
                active_design_id=root_id,
                source_revision_id=source.id,
            )
        except ProviderStudioJobError as exc:
            return provider_studio_job_error_response(exc)
    if request.studio_job_id is not None:
        try:
            reserve_exact_studio_presentation_job(
                db,
                job_id=request.studio_job_id,
                owner=request.created_by,
                project_root_id=root_id,
                source_asset_id=source.id,
                requested_outputs=1,
            )
        except StudioPresentationError as exc:
            return JSONResponse(status_code=exc.status_code, content={
                "code": exc.code, "detail": exc.detail,
            })
    plan = build_image_plan(
        ImageOperation.SPEC_RENDER,
        request.instruction,
        spec=spec.spec,
        source_image=bytes(source.image),
        variant=request.variant,
    )
    try:
        result = JewelryImageAgent().run(
            plan, source_image=bytes(source.image))
    except ImageAgentError as exc:
        run_id = persist_image_agent_failure(
            db, plan, exc, project_root_id=root_id,
            source_asset_id=source.id, created_by=request.created_by)
        if request.studio_job_id is not None:
            fail_exact_studio_presentation_job(
                db,
                job_id=request.studio_job_id,
                owner=request.created_by,
                error_code="presentation_provider_failed",
            )
        return image_agent_error_response(exc, image_run_id=run_id)
    if request.studio_job_id is not None and _failed_hard_quality(result):
        run_id = persist_image_agent_result(
            db, result, project_root_id=root_id,
            source_asset_id=source.id, created_by=request.created_by)
        fail_exact_studio_presentation_job(
            db, job_id=request.studio_job_id, owner=request.created_by,
            error_code="presentation_failed_quality",
        )
        return JSONResponse(status_code=422, content={
            "code": "presentation_failed_quality",
            "detail": "the presentation failed automated quality checks",
            "image_run_id": run_id,
        })
    review_result = (
        _designer_review_result(result)
        if request.studio_job_id is not None else result
    )
    if not review_result.accepted:
        run_id = persist_image_agent_result(
            db, review_result, project_root_id=root_id, source_asset_id=source.id,
            created_by=request.created_by)
        qa = _quality_payload(review_result)
        routing = _routing_payload(review_result, run_id)
        if request.studio_job_id is not None:
            try:
                candidate = store_studio_presentation_candidate(
                    db,
                    run_id=run_id,
                    project_root_id=root_id,
                    source_asset_id=source.id,
                    source_hash=hashlib.sha256(bytes(source.image)).hexdigest(),
                    image_bytes=review_result.image_bytes,
                    media_type=sniff_media_type(review_result.image_bytes),
                    destination="client",
                    capability="CLIENT_BEAUTY_RENDER",
                    requested_change=request.instruction,
                    preset="beauty",
                    framing="source",
                    qa=qa,
                    created_by=request.created_by,
                    studio_job_id=request.studio_job_id,
                    design_version=latest.version,
                    output_ordinal=0,
                    expected_active_asset_id=active.id,
                )
            except StudioPresentationError as exc:
                fail_exact_studio_presentation_job(
                    db,
                    job_id=request.studio_job_id,
                    owner=request.created_by,
                    error_code="presentation_candidate_store_failed",
                )
                return JSONResponse(status_code=exc.status_code, content={
                    "code": exc.code,
                    "detail": exc.detail,
                })
            preview_url = (
                f"/studio/image-runs/{run_id}/presentation-candidates/"
                f"{candidate.candidate_id}/image?owner={request.created_by}"
            )
        else:
            candidate = store_markup_warning_candidate(
                run_id=run_id,
                project_root_id=root_id,
                source_asset_id=source.id,
                expected_active_asset_id=active.id,
                expected_design_version=latest.version,
                image_bytes=review_result.image_bytes,
                media_type=sniff_media_type(review_result.image_bytes),
                operation=ImageOperation.SPEC_RENDER.value,
                asset_capability=(
                    "CLIENT_BEAUTY_RENDER"
                    if request.presentation_only else "SPEC_RENDER"
                ),
                requested_change=request.instruction,
                region_description="entire designer-confirmed ring",
                drift=None,
                next_spec=None,
                ignored_fields=(),
                qa=qa,
                routing=routing,
                created_by=request.created_by,
                promotion_kind=(
                    "presentation_only"
                    if request.presentation_only else "standard"
                ),
            )
            preview_url = (
                f"/image-runs/{run_id}/candidates/{candidate.candidate_id}/image"
            )
        return JSONResponse(status_code=202, content={
            "status": "review_required",
            "project_id": root_id,
            "source_asset_id": source.id,
            "image_run_id": run_id,
            "quality_report": qa,
            "routing": routing,
            "warning_candidate": {
                "run_id": run_id,
                "candidate_id": candidate.candidate_id,
                "preview_url": preview_url,
                "operation": ImageOperation.SPEC_RENDER.value,
                "asset_capability": (
                    "CLIENT_BEAUTY_RENDER"
                    if request.presentation_only else "SPEC_RENDER"
                ),
                "qa": qa,
                "requested_change": request.instruction,
                "studio_job_id": request.studio_job_id,
            },
        })
    persisted = (
        persist_project_derived_asset(
            db,
            root_id=root_id,
            parent_asset_id=source.id,
            image=result.image_bytes,
            capability="CLIENT_BEAUTY_RENDER",
            instruction=request.instruction,
            design_version=latest.version,
            created_by=request.created_by,
            image_run=result,
        )
        if request.presentation_only else
        persist_project_primary_revision(
            db,
            root_id=root_id,
            image=result.image_bytes,
            capability="SPEC_RENDER",
            instruction=request.instruction,
            design_version=latest.version,
            created_by=request.created_by,
            image_run=result,
            source_asset_id=source.id,
        )
    )
    return {
        "status": "accepted",
        "project": project_detail(db, project),
        "source_asset_id": source.id,
        "asset_id": persisted.asset_id,
        "image_run_id": persisted.image_run_id,
        "qa": result.quality.model_dump(mode="json"),
    }


def _quality_payload(result) -> dict[str, object]:
    failed = list(result.quality.failed_checks)
    return {
        **result.quality.model_dump(mode="json"),
        "accepted": result.accepted,
        "review_required": result.review_required,
        "summary": ("Image checks passed." if result.accepted
                    else "Image needs explicit designer review."),
        "failed_checks": [check.code for check in failed],
        "warnings": [
            check.message for check in failed
            if check.severity.value == "warning"
        ],
    }


def _failed_hard_quality(result: ImageAgentResult) -> bool:
    return (
        result.quality.verdict.value == "fail"
        or any(
            not check.passed and check.severity.value == "hard"
            for check in result.quality.checks
        )
    )


def _routing_payload(result, run_id: str | None = None) -> dict[str, object]:
    attempts = result.run.attempts
    return {
        "attempt_count": len(attempts),
        "used_retry": len(attempts) > 1,
        "used_fallback": any(attempt.fallback for attempt in attempts),
        "cache_hit": any(attempt.cached for attempt in attempts),
        "run_id": run_id,
    }


def _designer_review_result(result):
    """Force a QA-pass drawing to await human geometry confirmation."""
    from facetta.image_agent import ImageRunStatus

    return result.model_copy(update={
        "accepted": False,
        "review_required": True,
        "run": result.run.model_copy(update={
            "status": ImageRunStatus.REVIEW_REQUIRED,
        }),
    })


@router.post("/{root_id}/product-photo", status_code=201, deprecated=True)
def create_product_photo(
    root_id: str,
    request: ProductPhotoRequest,
    db: DbSession,
):
    """Create a persisted ecommerce presentation while freezing the ring.

    This is a visual-only revision: it inherits the current specification
    version, never creates a new ``DesignVersion``, and invalidates any older
    visual approval by becoming the active primary revision. Provider work and
    QA finish before the short atomic persistence step.
    """
    project = db.get(Project, root_id)
    if project is None:
        raise HTTPException(status_code=404,
                            detail=f"no project for chain '{root_id}'")
    if request.studio_job_id is not None and not request.presentation_only:
        return JSONResponse(status_code=422, content={
            "code": "presentation_job_requires_presentation_only",
            "detail": "a Present job cannot create a primary photo revision",
        })
    chain = project_chain(db, root_id)
    primary = [asset for asset in chain if is_primary_revision(asset)]
    source = primary[-1] if primary else None
    design_id = _linked_design_id(db, project, chain)
    latest = _latest_spec(db, design_id)
    if source is None or latest is None or design_id is None:
        return JSONResponse(status_code=409, content={
            "error_category": "validation_failure",
            "detail": "project has no linked validated specification and active image",
        })
    if request.expected_asset_id != source.id:
        return JSONResponse(status_code=409, content={
            "error_category": "stale_version",
            "code": "stale_asset_revision",
            "expected_asset_id": request.expected_asset_id,
            "current_asset_id": source.id,
        })
    if (request.expected_design_version != latest.version
            or source.design_version != latest.version):
        return JSONResponse(status_code=409, content={
            "error_category": "stale_version",
            "code": "stale_design_version",
            "expected_design_version": request.expected_design_version,
            "current_design_version": latest.version,
            "active_asset_design_version": source.design_version,
        })
    try:
        brief = compile_product_photo_brief(
            request.preset,
            request.framing,
            request.custom_instruction,
        )
    except PresentationScopeError as exc:
        return JSONResponse(status_code=422, content={
            "error_category": "validation_failure",
            "code": "presentation_scope_violation",
            "detail": str(exc),
        })

    if request.studio_job_id is None:
        try:
            require_provider_studio_job(
                db,
                job_id=None,
                owner=request.created_by,
                action_id="present",
                requested_outputs=1,
                active_design_id=root_id,
                source_revision_id=source.id,
            )
        except ProviderStudioJobError as exc:
            return provider_studio_job_error_response(exc)

    if request.studio_job_id is not None:
        try:
            reserve_exact_studio_presentation_job(
                db,
                job_id=request.studio_job_id,
                owner=request.created_by,
                project_root_id=root_id,
                source_asset_id=source.id,
                requested_outputs=1,
            )
        except StudioPresentationError as exc:
            return JSONResponse(status_code=exc.status_code, content={
                "code": exc.code, "detail": exc.detail,
            })

    from facetta.image_agent import ImageOperation, JewelryImageAgent, build_image_plan

    validated = validate_spec(Spec.model_validate(latest.spec), get_vocabulary())
    if not validated.ok:
        return JSONResponse(status_code=422, content={
            "error_category": "validation_failure",
            "detail": [issue.as_detail() for issue in validated.issues],
        })
    plan = build_image_plan(
        ImageOperation.VISUAL_ONLY_EDIT,
        brief.intent,
        spec=validated.spec,
        source_spec=validated.spec,
        source_image=bytes(source.image),
        frozen=(
            "the exact approved ring silhouette and jewelry-to-jewelry proportions",
            "every center and side stone identity, cut, color, count, and placement",
            "the complete setting, prong, gallery, band, and metal construction",
        ),
        style_constraints=brief.style_constraints,
        expected_output=brief.expected_output,
        variant=request.variant,
    )
    try:
        result = JewelryImageAgent().run(
            plan, source_image=bytes(source.image))
    except ImageAgentError as exc:
        run_id = persist_image_agent_failure(
            db, plan, exc, project_root_id=root_id,
            source_asset_id=source.id, created_by=request.created_by)
        if request.studio_job_id is not None:
            fail_exact_studio_presentation_job(
                db,
                job_id=request.studio_job_id,
                owner=request.created_by,
                error_code="presentation_provider_failed",
            )
        return image_agent_error_response(exc, image_run_id=run_id)

    if request.studio_job_id is not None and _failed_hard_quality(result):
        run_id = persist_image_agent_result(
            db, result, project_root_id=root_id,
            source_asset_id=source.id, created_by=request.created_by)
        fail_exact_studio_presentation_job(
            db, job_id=request.studio_job_id, owner=request.created_by,
            error_code="presentation_failed_quality",
        )
        return JSONResponse(status_code=422, content={
            "code": "presentation_failed_quality",
            "detail": "the presentation failed automated quality checks",
            "image_run_id": run_id,
        })
    review_result = (
        _designer_review_result(result)
        if request.studio_job_id is not None else result
    )
    qa = _quality_payload(review_result)
    if review_result.review_required:
        run_id = persist_image_agent_result(
            db, review_result, project_root_id=root_id,
            source_asset_id=source.id, created_by=request.created_by)
        routing = _routing_payload(review_result, run_id)
        if request.studio_job_id is not None:
            try:
                candidate = store_studio_presentation_candidate(
                    db,
                    run_id=run_id,
                    project_root_id=root_id,
                    source_asset_id=source.id,
                    source_hash=hashlib.sha256(bytes(source.image)).hexdigest(),
                    image_bytes=review_result.image_bytes,
                    media_type=sniff_media_type(review_result.image_bytes),
                    destination="client",
                    capability="CLIENT_PRODUCT_PHOTO",
                    requested_change=brief.intent,
                    preset=request.preset,
                    framing=request.framing,
                    qa=qa,
                    created_by=request.created_by,
                    studio_job_id=request.studio_job_id,
                    design_version=latest.version,
                    output_ordinal=0,
                    expected_active_asset_id=source.id,
                )
            except StudioPresentationError as exc:
                fail_exact_studio_presentation_job(
                    db,
                    job_id=request.studio_job_id,
                    owner=request.created_by,
                    error_code="presentation_candidate_store_failed",
                )
                return JSONResponse(status_code=exc.status_code, content={
                    "code": exc.code,
                    "detail": exc.detail,
                })
            preview_url = (
                f"/studio/image-runs/{run_id}/presentation-candidates/"
                f"{candidate.candidate_id}/image?owner={request.created_by}"
            )
        else:
            candidate = store_markup_warning_candidate(
                run_id=run_id,
                project_root_id=root_id,
                source_asset_id=source.id,
                expected_active_asset_id=source.id,
                expected_design_version=latest.version,
                image_bytes=review_result.image_bytes,
                media_type=sniff_media_type(review_result.image_bytes),
                operation=ImageOperation.VISUAL_ONLY_EDIT.value,
                asset_capability=(
                    "CLIENT_PRODUCT_PHOTO"
                    if request.presentation_only else "PRODUCT_PHOTO"
                ),
                requested_change=brief.intent,
                region_description=(
                    "entire product presentation; jewelry design frozen"),
                drift=None,
                next_spec=None,
                ignored_fields=(),
                qa=qa,
                routing=routing,
                created_by=request.created_by,
                promotion_kind=(
                    "presentation_only" if request.presentation_only else "standard"
                ),
            )
            preview_url = (
                f"/image-runs/{run_id}/candidates/{candidate.candidate_id}/image"
            )
        return JSONResponse(status_code=202, content={
            "status": "review_required",
            "project_id": root_id,
            "image_run_id": run_id,
            "quality_report": qa,
            "routing": routing,
            "presentation": {
                "preset": request.preset,
                "framing": request.framing,
                "source_asset_id": source.id,
                "design_version": latest.version,
            },
            "warning_candidate": {
                "run_id": run_id,
                "candidate_id": candidate.candidate_id,
                "preview_url": preview_url,
                "qa": qa,
                "operation": ImageOperation.VISUAL_ONLY_EDIT.value,
                "requested_change": brief.intent,
                "studio_job_id": request.studio_job_id,
            },
        })

    persisted = (
        persist_project_derived_asset(
            db,
            root_id=root_id,
            parent_asset_id=source.id,
            image=result.image_bytes,
            capability="CLIENT_PRODUCT_PHOTO",
            instruction=brief.intent,
            design_version=latest.version,
            created_by=request.created_by,
            image_run=result,
        )
        if request.presentation_only else
        persist_project_primary_revision(
            db,
            root_id=root_id,
            image=result.image_bytes,
            capability="PRODUCT_PHOTO",
            instruction=brief.intent,
            design_version=latest.version,
            created_by=request.created_by,
            image_run=result,
        )
    )
    return {
        "status": "accepted",
        "project": project_detail(db, project),
        "asset_id": persisted.asset_id,
        "image_run_id": persisted.image_run_id,
        "qa": qa,
        "routing": _routing_payload(result, persisted.image_run_id),
        "presentation": {
            "preset": request.preset,
            "framing": request.framing,
            "source_asset_id": source.id,
            "design_version": latest.version,
        },
    }


@router.post(
    "/{root_id}/marketing-pack",
    status_code=202,
    response_model=MarketingPackResponse,
)
def create_marketing_pack(
    root_id: str,
    request: MarketingPackRequest,
    db: DbSession,
    generate: MarketingGeneratorDep,
):
    """Generate a review queue of ecommerce scenes without changing design state.

    Every candidate is temporary until explicitly accepted. Accepted outputs
    become derived ``MARKETING_IMAGE`` assets tied to the exact source/spec;
    they never become the active design revision or invalidate factory approval.
    """
    project = db.get(Project, root_id)
    if project is None:
        raise HTTPException(status_code=404,
                            detail=f"no project for chain '{root_id}'")
    chain = project_chain(db, root_id)
    primary = [asset for asset in chain if is_primary_revision(asset)]
    source = primary[-1] if primary else None
    design_id = _linked_design_id(db, project, chain)
    latest = _latest_spec(db, design_id)
    if source is None or latest is None or design_id is None:
        return JSONResponse(status_code=409, content={
            "error_category": "validation_failure",
            "detail": "project has no linked validated specification and active image",
        })
    if request.expected_asset_id != source.id:
        return JSONResponse(status_code=409, content={
            "error_category": "stale_version",
            "code": "stale_asset_revision",
            "expected_asset_id": request.expected_asset_id,
            "current_asset_id": source.id,
        })
    if (request.expected_design_version != latest.version
            or source.design_version != latest.version):
        return JSONResponse(status_code=409, content={
            "error_category": "stale_version",
            "code": "stale_design_version",
            "expected_design_version": request.expected_design_version,
            "current_design_version": latest.version,
            "active_asset_design_version": source.design_version,
        })

    validated = validate_spec(Spec.model_validate(latest.spec), get_vocabulary())
    if not validated.ok:
        return JSONResponse(status_code=422, content={
            "error_category": "validation_failure",
            "detail": [issue.as_detail() for issue in validated.issues],
        })
    try:
        briefs = [
            compile_product_photo_brief(
                preset, request.framing, request.custom_instruction)
            for preset in request.presets
        ]
    except PresentationScopeError as exc:
        return JSONResponse(status_code=422, content={
            "error_category": "validation_failure",
            "code": "presentation_scope_violation",
            "detail": str(exc),
        })

    if request.studio_job_id is None:
        try:
            require_provider_studio_job(
                db,
                job_id=None,
                owner=request.created_by,
                action_id="present",
                requested_outputs=len(request.presets),
                active_design_id=root_id,
                source_revision_id=source.id,
            )
        except ProviderStudioJobError as exc:
            return provider_studio_job_error_response(exc)

    if request.studio_job_id is not None:
        try:
            reserve_exact_studio_presentation_job(
                db,
                job_id=request.studio_job_id,
                owner=request.created_by,
                project_root_id=root_id,
                source_asset_id=source.id,
                requested_outputs=len(request.presets),
            )
        except StudioPresentationError as exc:
            return JSONResponse(status_code=exc.status_code, content={
                "code": exc.code, "detail": exc.detail,
            })

    candidates: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    actual_attempts = 0
    for offset, (preset, brief) in enumerate(zip(request.presets, briefs)):
        variant = request.starting_variant + offset
        try:
            result = generate(
                validated.spec,
                bytes(source.image),
                brief,
                variant,
            )
        except ImageAgentError as exc:
            actual_attempts += len(exc.attempts)
            run_id = (
                persist_image_agent_failure(
                    db,
                    exc.plan,
                    exc,
                    project_root_id=root_id,
                    source_asset_id=source.id,
                    created_by=request.created_by,
                ) if exc.plan is not None else None
            )
            failures.append({
                "preset": preset,
                "image_run_id": run_id,
                "error_category": exc.category.value,
                "code": exc.code,
                "detail": exc.message,
            })
            continue

        if request.studio_job_id is not None and _failed_hard_quality(result):
            run_id = persist_image_agent_result(
                db, result, project_root_id=root_id,
                source_asset_id=source.id, created_by=request.created_by)
            failures.append({
                "preset": preset,
                "image_run_id": run_id,
                "error_category": "quality_failure",
                "code": "presentation_failed_quality",
                "detail": "the presentation failed automated quality checks",
            })
            continue

        # Marketing output is never promoted merely because automated QA
        # passed. The designer explicitly selects each deliverable.
        review_result = _designer_review_result(result)
        actual_attempts += len(review_result.run.attempts)
        qa = _quality_payload(review_result)
        run_id = persist_image_agent_result(
            db,
            review_result,
            project_root_id=root_id,
            source_asset_id=source.id,
            created_by=request.created_by,
        )
        routing = _routing_payload(review_result, run_id)
        if request.studio_job_id is not None:
            try:
                candidate = store_studio_presentation_candidate(
                    db,
                    run_id=run_id,
                    project_root_id=root_id,
                    source_asset_id=source.id,
                    source_hash=hashlib.sha256(bytes(source.image)).hexdigest(),
                    image_bytes=review_result.image_bytes,
                    media_type=sniff_media_type(review_result.image_bytes),
                    destination="marketing",
                    capability="MARKETING_IMAGE",
                    requested_change=brief.intent,
                    preset=preset,
                    framing=request.framing,
                    qa=qa,
                    created_by=request.created_by,
                    studio_job_id=request.studio_job_id,
                    design_version=latest.version,
                    output_ordinal=offset,
                    expected_active_asset_id=source.id,
                )
            except StudioPresentationError as exc:
                failures.append({
                    "preset": preset,
                    "image_run_id": run_id,
                    "error_category": "validation_failure",
                    "code": exc.code,
                    "detail": exc.detail,
                })
                continue
            preview_url = (
                f"/studio/image-runs/{run_id}/presentation-candidates/"
                f"{candidate.candidate_id}/image?owner={request.created_by}"
            )
        else:
            candidate = store_markup_warning_candidate(
                run_id=run_id,
                project_root_id=root_id,
                source_asset_id=source.id,
                expected_active_asset_id=source.id,
                expected_design_version=latest.version,
                image_bytes=review_result.image_bytes,
                media_type=sniff_media_type(review_result.image_bytes),
                operation="VISUAL_ONLY_EDIT",
                asset_capability="MARKETING_IMAGE",
                requested_change=brief.intent,
                region_description=(
                    "entire ecommerce presentation; approved jewelry frozen"),
                drift=None,
                next_spec=None,
                ignored_fields=(),
                qa=qa,
                routing=routing,
                created_by=request.created_by,
                promotion_kind="presentation_only",
            )
            preview_url = (
                f"/image-runs/{run_id}/candidates/{candidate.candidate_id}/image"
            )
        candidates.append({
            "preset": preset,
            "framing": request.framing,
            "image_run_id": run_id,
            "candidate_id": candidate.candidate_id,
            "preview_url": preview_url,
            "qa": qa,
            "routing": routing,
            "studio_job_id": request.studio_job_id,
        })

    if request.studio_job_id is not None and not candidates:
        fail_exact_studio_presentation_job(
            db,
            job_id=request.studio_job_id,
            owner=request.created_by,
            error_code="presentation_outputs_failed",
        )
    return {
        "status": "review_required" if candidates else "failed",
        "project_id": root_id,
        "source_asset_id": source.id,
        "design_version": latest.version,
        "requested_count": len(request.presets),
        "candidate_count": len(candidates),
        "failed_count": len(failures),
        "maximum_provider_attempts": len(request.presets) * 3,
        "actual_attempts": actual_attempts,
        "candidates": candidates,
        "failures": failures,
    }


@router.post(
    "/{root_id}/visual-twin/views",
    status_code=202,
    response_model=VisualTwinViewsResponse,
)
def create_visual_twin_views(
    root_id: str,
    request: VisualTwinViewsRequest,
    db: DbSession,
    generate: MountingViewGeneratorDep,
):
    """Generate independent, review-only mounting views for one variation.

    Each view receives its own closed-loop image run. A visual QA pass still
    remains temporary until the designer accepts it; acceptance creates a
    derived discussion artifact and never changes the active revision/spec.
    """

    project = db.get(Project, root_id)
    if project is None:
        raise HTTPException(status_code=404,
                            detail=f"no project for chain '{root_id}'")
    chain = project_chain(db, root_id)
    primary = [asset for asset in chain if is_primary_revision(asset)]
    source = primary[-1] if primary else None
    design_id = _linked_design_id(db, project, chain)
    latest = _latest_spec(db, design_id)
    if source is None or latest is None or design_id is None:
        return JSONResponse(status_code=409, content={
            "error_category": "validation_failure",
            "detail": "visual twin generation requires an active validated design",
        })
    if request.expected_asset_id != source.id:
        return JSONResponse(status_code=409, content={
            "error_category": "stale_version",
            "code": "stale_asset_revision",
            "expected_asset_id": request.expected_asset_id,
            "current_asset_id": source.id,
        })
    if (request.expected_design_version != latest.version
            or source.design_version != latest.version):
        return JSONResponse(status_code=409, content={
            "error_category": "stale_version",
            "code": "stale_design_version",
            "expected_design_version": request.expected_design_version,
            "current_design_version": latest.version,
            "active_asset_design_version": source.design_version,
        })
    validated = validate_spec(Spec.model_validate(latest.spec), get_vocabulary())
    if not validated.ok or validated.spec.jewelry_type != "ring":
        return JSONResponse(status_code=422, content={
            "error_category": "validation_failure",
            "detail": (
                [issue.as_detail() for issue in validated.issues]
                if not validated.ok else
                "the first visual-twin mounting slice supports rings only"
            ),
        })

    source_bytes = bytes(source.image)
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    visual_hash = spec_visual_hash(validated.spec)
    candidates: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    actual_attempts = 0
    for offset, view in enumerate(request.views):
        variant = request.starting_variant + offset
        try:
            generated = generate(validated.spec, source_bytes, view, variant)
        except ImageAgentError as exc:
            actual_attempts += len(exc.attempts)
            run_id = (
                persist_image_agent_failure(
                    db,
                    exc.plan,
                    exc,
                    project_root_id=root_id,
                    source_asset_id=source.id,
                    created_by=request.created_by,
                ) if exc.plan is not None else None
            )
            failures.append({
                "view": view,
                "image_run_id": run_id,
                "error_category": exc.category.value,
                "code": exc.code,
                "detail": exc.message,
            })
            continue

        result = _designer_review_result(generated)
        actual_attempts += len(result.run.attempts)
        qa = _quality_payload(result)
        run_id = persist_image_agent_result(
            db,
            result,
            project_root_id=root_id,
            source_asset_id=source.id,
            created_by=request.created_by,
        )
        routing = _routing_payload(result, run_id)
        candidate = store_markup_warning_candidate(
            run_id=run_id,
            project_root_id=root_id,
            source_asset_id=source.id,
            expected_active_asset_id=source.id,
            expected_design_version=latest.version,
            image_bytes=result.image_bytes,
            media_type=sniff_media_type(result.image_bytes),
            operation=ImageOperation.MOUNTING_VIEW_GENERATE.value,
            asset_capability="FACTORY_REVIEW_MOUNTING_VIEW",
            requested_change=(
                f"Create the design-specific {view} mounting view."
            ),
            region_description=f"isolated {view} mounting view",
            drift=None,
            next_spec=None,
            ignored_fields=(),
            qa=qa,
            routing=routing,
            created_by=request.created_by,
            promotion_kind="derived_only",
            artifact_metadata=MountingViewArtifactMetadata(
                view=view,
                source_hash=source_hash,
                spec_visual_hash=visual_hash,
            ),
        )
        candidates.append({
            "view": view,
            "image_run_id": run_id,
            "candidate_id": candidate.candidate_id,
            "preview_url": (
                f"/image-runs/{run_id}/candidates/"
                f"{candidate.candidate_id}/image"
            ),
            "promotion_kind": "derived_only",
            "authority": "factory_discussion_only",
            "qa": qa,
            "routing": routing,
        })

    return {
        "status": "review_required" if candidates else "failed",
        "project_id": root_id,
        "source_asset_id": source.id,
        "design_version": latest.version,
        "requested_count": len(request.views),
        "candidate_count": len(candidates),
        "failed_count": len(failures),
        "maximum_provider_attempts": len(request.views) * 3,
        "actual_attempts": actual_attempts,
        "candidates": candidates,
        "failures": failures,
    }


@router.post("/{root_id}/line-art", status_code=202)
def create_project_line_art(
    root_id: str,
    request: ProjectLineArtRequest,
    db: DbSession,
):
    """Create a temporary line drawing that a designer must confirm."""
    project = db.get(Project, root_id)
    if project is None:
        raise HTTPException(status_code=404,
                            detail=f"no project for chain '{root_id}'")
    chain = project_chain(db, root_id)
    primary = [asset for asset in chain if is_primary_revision(asset)]
    source = primary[-1] if primary else None
    design_id = _linked_design_id(db, project, chain)
    latest = _latest_spec(db, design_id)
    if source is None or latest is None or design_id is None:
        return JSONResponse(status_code=409, content={
            "error_category": "validation_failure",
            "detail": "project has no linked validated specification and active image",
        })
    if request.expected_asset_id != source.id:
        return JSONResponse(status_code=409, content={
            "error_category": "stale_version",
            "code": "stale_asset_revision",
            "expected_asset_id": request.expected_asset_id,
            "current_asset_id": source.id,
        })
    if (request.expected_design_version != latest.version
            or source.design_version != latest.version):
        return JSONResponse(status_code=409, content={
            "error_category": "stale_version",
            "code": "stale_design_version",
            "current_design_version": latest.version,
        })
    validated = validate_spec(Spec.model_validate(latest.spec), get_vocabulary())
    if not validated.ok:
        return JSONResponse(status_code=422, content={
            "error_category": "validation_failure",
            "detail": [issue.as_detail() for issue in validated.issues],
        })
    if request.studio_job_id is None:
        try:
            require_provider_studio_job(
                db,
                job_id=None,
                owner=request.created_by,
                action_id="views",
                requested_outputs=1,
                active_design_id=root_id,
                source_revision_id=source.id,
            )
        except ProviderStudioJobError as exc:
            return provider_studio_job_error_response(exc)
    source_control = bytes(source.image)
    selection_payload = None
    region_description = request.source_region_description
    if request.source_region is not None:
        region = request.source_region
        try:
            source_control = crop_normalized_region(
                source_control,
                x=region.x,
                y=region.y,
                width=region.width,
                height=region.height,
            )
        except ImageRegionError as exc:
            return JSONResponse(status_code=422, content={
                "error_category": "validation_failure",
                "code": "source_region_invalid",
                "detail": str(exc),
            })
        selection_payload = region.model_dump(mode="json")
        coordinates = (
            f"normalized crop x={region.x:.4f}, y={region.y:.4f}, "
            f"width={region.width:.4f}, height={region.height:.4f}"
        )
        region_description = (
            f"{region_description.strip()}; {coordinates}"
            if region_description else coordinates
        )
    brief = compile_line_art_brief(
        request.view,
        region_description,
    )
    from facetta.image_agent import (
        ConfirmedLineArtQualityEvaluator,
        ImageOperation,
        JewelryImageAgent,
        build_image_plan,
    )

    frozen = (
        (
            "every jewelry outline and spatial relationship visible inside the "
            "designer-selected source crop",
            "do not add any band, shank, shoulder, gallery, stone, setting, or "
            "other jewelry geometry absent from the selected crop",
            "the exact validated identities and counts for components visible "
            "inside the selected crop",
        )
        if selection_payload else
        (
            "the complete assembled ring silhouette and proportions",
            "every visible stone, setting, prong, shoulder motif, and band contour",
            "the exact validated specification, including center-prong and side-stone counts",
        )
    )
    plan = build_image_plan(
        ImageOperation.VISUAL_ONLY_EDIT,
        brief.intent,
        spec=validated.spec,
        source_spec=validated.spec,
        source_image=source_control,
        frozen=frozen,
        style_constraints=brief.style_constraints,
        expected_output=brief.expected_output,
        variant=request.variant,
    )
    if request.studio_job_id is not None:
        try:
            reserve_studio_view_job(
                db,
                job_id=request.studio_job_id,
                owner=request.created_by,
                project_root_id=root_id,
                source_asset_id=source.id,
            )
        except StudioViewError as exc:
            return JSONResponse(status_code=exc.status_code, content={
                "code": exc.code, "detail": exc.detail,
            })
    try:
        result = JewelryImageAgent(
            evaluator=ConfirmedLineArtQualityEvaluator(),
        ).run(plan, source_image=source_control)
    except ImageAgentError as exc:
        run_id = persist_image_agent_failure(
            db, plan, exc, project_root_id=root_id,
            source_asset_id=source.id, created_by=request.created_by)
        if request.studio_job_id is not None:
            fail_studio_view_job(
                db, job_id=request.studio_job_id, owner=request.created_by,
                error_code="view_provider_failed",
            )
        return image_agent_error_response(exc, image_run_id=run_id)

    if request.studio_job_id is not None and _failed_hard_quality(result):
        run_id = persist_image_agent_result(
            db, result, project_root_id=root_id,
            source_asset_id=source.id, created_by=request.created_by)
        fail_studio_view_job(
            db, job_id=request.studio_job_id, owner=request.created_by,
            error_code="view_failed_quality",
        )
        return JSONResponse(status_code=422, content={
            "code": "view_failed_quality",
            "detail": "the generated View failed automated quality checks",
            "image_run_id": run_id,
        })
    result = _designer_review_result(result)
    run_id = persist_image_agent_result(
        db, result, project_root_id=root_id,
        source_asset_id=source.id, created_by=request.created_by)
    qa = _quality_payload(result)
    routing = _routing_payload(result, run_id)
    if request.studio_job_id is not None:
        try:
            candidate = store_studio_view_candidate(
                db,
                run_id=run_id,
                project_root_id=root_id,
                source_asset_id=source.id,
                source_hash=hashlib.sha256(bytes(source.image)).hexdigest(),
                output_bytes=result.image_bytes,
                media_type=sniff_media_type(result.image_bytes),
                design_version=latest.version,
                spec_hash=spec_visual_hash(validated.spec),
                view=request.view,
                requested_change=brief.intent,
                qa=qa,
                routing=routing,
                created_by=request.created_by,
                studio_job_id=request.studio_job_id,
            )
        except StudioViewError as exc:
            fail_studio_view_job(
                db,
                job_id=request.studio_job_id,
                owner=request.created_by,
                error_code="view_candidate_store_failed",
            )
            return JSONResponse(status_code=exc.status_code, content={
                "code": exc.code,
                "category": (
                    "validation" if exc.status_code == 422 else "conflict"
                ),
                "detail": exc.detail,
            })
        preview_url = (
            f"/studio/view-candidates/{run_id}/"
            f"{candidate.candidate_id}/image?owner={request.created_by}"
        )
    else:
        candidate = store_markup_warning_candidate(
            run_id=run_id,
            project_root_id=root_id,
            source_asset_id=source.id,
            expected_active_asset_id=source.id,
            expected_design_version=latest.version,
            image_bytes=result.image_bytes,
            media_type=sniff_media_type(result.image_bytes),
            operation=ImageOperation.VISUAL_ONLY_EDIT.value,
            asset_capability="LINE_ART",
            requested_change=brief.intent,
            region_description=(
                f"designer-selected source region to confirmed {request.view} "
                "line-art view" if selection_payload else
                f"entire confirmed {request.view} line-art view"
            ),
            drift=None,
            next_spec=None,
            ignored_fields=(),
            qa=qa,
            routing=routing,
            created_by=request.created_by,
        )
        preview_url = (
            f"/image-runs/{run_id}/candidates/{candidate.candidate_id}/image"
        )
    return {
        "status": "confirmation_required",
        "project_id": root_id,
        "image_run_id": run_id,
        "quality_report": qa,
        "routing": routing,
        "view": request.view,
        "source_selection": selection_payload,
        "candidate": {
            "run_id": run_id,
            "candidate_id": candidate.candidate_id,
            "preview_url": preview_url,
            "operation": ImageOperation.VISUAL_ONLY_EDIT.value,
            "asset_capability": "LINE_ART",
            "qa": qa,
            "requested_change": brief.intent,
            "studio_job_id": request.studio_job_id,
        },
        "next": (
            "designer confirms geometry, then render directly from the "
            "persisted LINE_ART asset; a colored technical illustration is optional"
        ),
    }


@router.post("/{root_id}/line-art/{line_art_asset_id}/colorize", status_code=201)
def colorize_project_line_art(
    root_id: str,
    line_art_asset_id: str,
    request: ProjectColorizeLineArtRequest,
    db: DbSession,
):
    """Color a designer-confirmed LINE_ART asset from the exact spec."""
    project = db.get(Project, root_id)
    line_art = db.get(ImageAsset, line_art_asset_id)
    if project is None:
        raise HTTPException(status_code=404,
                            detail=f"no project for chain '{root_id}'")
    if (line_art is None or line_art.root_id != root_id
            or line_art.capability != "LINE_ART"):
        return JSONResponse(status_code=422, content={
            "error_category": "validation_failure",
            "code": "confirmed_line_art_required",
            "detail": "colorization requires a designer-confirmed LINE_ART asset",
        })
    chain = project_chain(db, root_id)
    primary = [asset for asset in chain if is_primary_revision(asset)]
    active = primary[-1] if primary else None
    design_id = _linked_design_id(db, project, chain)
    latest = _latest_spec(db, design_id)
    if active is None or latest is None or design_id is None:
        return JSONResponse(status_code=409, content={
            "error_category": "validation_failure",
            "detail": "project has no linked validated specification and active image",
        })
    if request.expected_asset_id != active.id or line_art.parent_asset_id != active.id:
        return JSONResponse(status_code=409, content={
            "error_category": "stale_version",
            "code": "stale_asset_revision",
            "current_asset_id": active.id,
        })
    if (request.expected_design_version != latest.version
            or line_art.design_version != latest.version):
        return JSONResponse(status_code=409, content={
            "error_category": "stale_version",
            "code": "stale_design_version",
            "current_design_version": latest.version,
        })
    validated = validate_spec(Spec.model_validate(latest.spec), get_vocabulary())
    if not validated.ok:
        return JSONResponse(status_code=422, content={
            "error_category": "validation_failure",
            "detail": [issue.as_detail() for issue in validated.issues],
        })
    brief = compile_color_brief(validated.spec)
    from facetta.image_agent import (
        ColoredLineArtQualityEvaluator,
        ImageOperation,
        ImageQualityFailure,
        JewelryImageAgent,
        build_image_plan,
    )

    plan = build_image_plan(
        ImageOperation.VISUAL_ONLY_EDIT,
        brief.intent,
        spec=validated.spec,
        source_spec=validated.spec,
        source_image=bytes(line_art.image),
        frozen=(
            "every confirmed line, outline, stone count, component, and spatial relationship",
            "the exact validated specification",
        ),
        style_constraints=brief.style_constraints,
        expected_output=brief.expected_output,
        variant=request.variant,
    )
    try:
        result = JewelryImageAgent(
            evaluator=ColoredLineArtQualityEvaluator(bytes(active.image)),
        ).run(
            plan, source_image=bytes(line_art.image))
    except ImageAgentError as exc:
        run_id = persist_image_agent_failure(
            db, plan, exc, project_root_id=root_id,
            source_asset_id=line_art.id, created_by=request.created_by)
        extra = None
        if isinstance(exc, ImageQualityFailure) and any(
            check.code == "approved_source_material_identity"
            and not check.passed
            for check in exc.report.checks
        ):
            extra = {
                "code": "approved_source_material_identity_failed",
                "detail": (
                    "colorization changed stone or metal identity from the "
                    "approved source after targeted correction; no asset was created"
                ),
                "quality_report": exc.report.model_dump(mode="json"),
            }
        return image_agent_error_response(
            exc, image_run_id=run_id, extra=extra)

    qa = _quality_payload(result)
    if result.review_required:
        run_id = persist_image_agent_result(
            db, result, project_root_id=root_id,
            source_asset_id=line_art.id, created_by=request.created_by)
        routing = _routing_payload(result, run_id)
        candidate = store_markup_warning_candidate(
            run_id=run_id,
            project_root_id=root_id,
            source_asset_id=line_art.id,
            expected_active_asset_id=active.id,
            expected_design_version=latest.version,
            image_bytes=result.image_bytes,
            media_type=sniff_media_type(result.image_bytes),
            operation=ImageOperation.VISUAL_ONLY_EDIT.value,
            asset_capability="COLORED_LINE_ART",
            requested_change=brief.intent,
            region_description="inside the confirmed line-art geometry only",
            drift=None,
            next_spec=None,
            ignored_fields=(),
            qa=qa,
            routing=routing,
            created_by=request.created_by,
        )
        return JSONResponse(status_code=202, content={
            "status": "review_required",
            "project_id": root_id,
            "image_run_id": run_id,
            "quality_report": qa,
            "routing": routing,
            "candidate": {
                "run_id": run_id,
                "candidate_id": candidate.candidate_id,
                "preview_url": (
                    f"/image-runs/{run_id}/candidates/"
                    f"{candidate.candidate_id}/image"
                ),
                "operation": ImageOperation.VISUAL_ONLY_EDIT.value,
                "asset_capability": "COLORED_LINE_ART",
                "qa": qa,
                "requested_change": brief.intent,
            },
        })

    persisted = persist_project_derived_asset(
        db,
        root_id=root_id,
        parent_asset_id=line_art.id,
        image=result.image_bytes,
        capability="COLORED_LINE_ART",
        instruction=brief.intent,
        design_version=latest.version,
        created_by=request.created_by,
        image_run=result,
    )
    return {
        "status": "accepted",
        "project": project_detail(db, project),
        "asset_id": persisted.asset_id,
        "image_run_id": persisted.image_run_id,
        "qa": qa,
        "routing": _routing_payload(result, persisted.image_run_id),
    }

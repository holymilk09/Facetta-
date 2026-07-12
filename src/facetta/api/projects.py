"""Trusted project workspace: creation, revision provenance, and state.

This router owns one Studio variation workspace and its optional trusted
factory-promotion lane. Library search and collection organization remain in
``api.library``.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from facetta.chain_geometry import chain_factory_blockers
from facetta.checklist import checklist_status
from facetta.concept import ConceptInvalid
from facetta.creative_workflow import (
    CreativePromptGenerator,
    CreativeRenderGenerator,
    get_creative_prompt_generator,
    get_creative_render_generator,
)
from facetta.api.error_mapping import (
    image_agent_error_response, render_unavailable_response,
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
    get_db,
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
    DesignAlreadyLinked,
    PersistedProjectInput,
    PROVENANCE_BY_CAPABILITY,
    SourceAssetInput,
    get_brief_project_generator,
    is_primary_revision,
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
from facetta.preliminary_sheet import sheet_readiness_blockers
from facetta.render import RenderUnavailable
from facetta.spec import Spec
from facetta.studio_history import ensure_project_family
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

router = APIRouter(prefix="/projects", tags=["projects"])

DbSession = Annotated[Session, Depends(get_db)]
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
    provenance: str
    revision: int | None
    design_version: int | None
    region: str | None
    instruction: str | None
    drift: float | None
    pinned: bool
    media_type: str
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
    selected_candidate_asset_id: str | None
    active_design_version: int | None
    active_revision: AssetSummary | None
    pinned_revision: AssetSummary | None
    revisions: list[AssetSummary]
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


class ProjectFromDrawingRequest(BaseModel):
    """Neutral image/drawing intake; no quality or source-maturity labels."""

    model_config = ConfigDict(extra="forbid")

    image_base64: Annotated[str, Field(min_length=1, max_length=14_000_000)]
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

    # A professional plate often repeats one finished piece as front, side,
    # and enlarged construction views. The designer may isolate the exact view
    # to render; the original plate and the cropped source are both persisted.
    source_region_description: Annotated[
        str, Field(min_length=3, max_length=500)
    ] | None = None
    source_region: NormalizedSourceRegion | None = None

    @model_validator(mode="after")
    def description_requires_region(self) -> ProjectFromDrawingRequest:
        if self.source_region_description is not None and self.source_region is None:
            raise ValueError(
                "source_region_description requires source_region coordinates"
            )
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


class CreativeCandidatePromoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec: Spec
    created_by: Annotated[str, Field(min_length=1, max_length=32)]


class CreativeCandidateSelectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created_by: Annotated[str, Field(min_length=1, max_length=32)]


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
    primary = [a for a in chain if is_primary_revision(a)]
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


def _revision_numbers(chain: list[ImageAsset]) -> dict[str, int]:
    return {asset.id: revision for revision, asset in enumerate(
        (a for a in chain if is_primary_revision(a)), start=1)}


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
        else PROVENANCE_BY_CAPABILITY.get(
            asset.capability, "derived_artifact"))
    item = {
        "asset_id": asset.id,
        "root_id": asset.root_id,
        "parent_asset_id": asset.parent_asset_id,
        "capability": asset.capability,
        "provenance": provenance,
        "revision": revisions.get(asset.id),
        "design_version": asset.design_version,
        "region": asset.region,
        "instruction": asset.instruction,
        "drift": asset.drift,
        "pinned": asset.pinned_at is not None,
        "media_type": asset.media_type,
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
    revision_numbers = _revision_numbers(chain)
    primary = [a for a in chain if a.id in revision_numbers]
    active = primary[-1] if primary else None
    if (project.selected_candidate_asset_id is not None
            and not any(asset.design_version is not None for asset in primary)):
        selected = next((asset for asset in primary
                         if asset.id == project.selected_candidate_asset_id), None)
        if selected is not None and selected.design_version is None:
            active = selected
    pinned_candidates = [a for a in primary if a.pinned_at is not None]
    pinned = (max(pinned_candidates, key=lambda a: a.pinned_at)
              if pinned_candidates else None)
    design_id = _linked_design_id(db, project, chain)
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
            source_blockers = source_component_factory_blockers(
                active_spec.source_component_coverage,
                valid_spec_paths=valid_source_component_spec_paths(active_spec),
                current_spec_visual_hash=target_visual_hash,
                current_source_hash=hashlib.sha256(
                    bytes((db.get(ImageAsset, project.root_id) or active).image)
                ).hexdigest(),
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
        "selected_candidate_asset_id": project.selected_candidate_asset_id,
        "active_design_version": (active.design_version if active else None),
        "active_revision": by_id.get(active.id) if active else None,
        "pinned_revision": by_id.get(pinned.id) if pinned else None,
        "revisions": [by_id[a.id] for a in primary],
        "derived_assets": [item for item in summaries
                           if item["revision"] is None],
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


def _validate_confirmed_import_spec(spec: Spec):
    """Validate the categories accepted by designer-confirmed image import.

    Brief generation remains ring-only. Necklace import is deliberately
    limited to the existing pendant-necklace template and must name a carrier
    chain; missing manufacturing facts remain visible factory blockers and
    cannot be used by the catalog route until explicitly supplied.
    """
    if spec.jewelry_type == "ring":
        return _validate_ring_spec(spec)
    if spec.jewelry_type != "necklace":
        return None, JSONResponse(status_code=422, content={
            "error_category": "validation_failure",
            "detail": (
                "designer-confirmed project import currently supports rings "
                "and pendant necklaces only"
            ),
        })
    if spec.template != "cluster_pendant" or spec.chain is None:
        return None, JSONResponse(status_code=422, content={
            "error_category": "validation_failure",
            "detail": (
                "a trusted necklace import requires template "
                "'cluster_pendant' and an explicit carrier-chain section"
            ),
        })
    result = validate_spec(spec, get_vocabulary())
    if not result.ok:
        return None, JSONResponse(status_code=422, content={
            "error_category": "validation_failure",
            "detail": [issue.as_detail() for issue in result.issues],
        })
    return result.spec, None


def _confirmed_import_coverage_error(
    spec: Spec,
    source_image: bytes | None = None,
) -> JSONResponse | None:
    """Fail closed for new imports without exact audited source accounting."""
    coverage = spec.source_component_coverage
    if coverage is None:
        return JSONResponse(status_code=422, content={
            "error_category": "validation_failure",
            "code": "source_component_coverage_required",
            "detail": (
                "a new image import requires server-reviewed source-component "
                "coverage; extract the source, resolve every visible component, "
                "and complete the independent audit before project creation"
            ),
        })
    blockers = source_component_factory_blockers(
        coverage,
        valid_spec_paths=valid_source_component_spec_paths(spec),
        current_spec_visual_hash=spec_visual_hash(spec),
        current_source_hash=(
            hashlib.sha256(source_image).hexdigest()
            if source_image is not None else None
        ),
    )
    if not blockers:
        return None
    return JSONResponse(status_code=409, content={
        "error_category": "validation_failure",
        "code": "source_component_coverage_incomplete",
        "detail": (
            "every visible source component must map to the exact confirmed "
            "specification and pass independent audit before project creation"
        ),
        "factory_blockers": [
            blocker.model_dump(mode="json") for blocker in blockers
        ],
    })


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
):
    """Persist the designer's chosen visual without inventing a specification."""
    project, candidate = _owned_creative_candidate(
        db, project_id=project_id, candidate_id=candidate_id,
        actor=request.created_by,
    )
    project.selected_candidate_asset_id = candidate.id
    project.updated_at = utcnow()
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
):
    """Create several category-neutral visual concepts before specification.

    Every provider/QA run finishes before the project transaction. The outputs
    remain designer-review candidates and cannot enter approval or factory
    export until one is selected and bound to a confirmed exact specification.
    """
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
    )
    project = db.get(Project, persisted.root_id)
    if project is None:  # pragma: no cover - transaction invariant
        raise RuntimeError("persisted prompt project is unavailable")
    ensure_project_family(db, project)
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
):
    """Create reviewable beauty renders without inventing a factory spec.

    Provider and QA work completes before the one product transaction. A hard
    QA/provider failure leaves no Project, ImageAsset, Design, or DesignVersion.
    Completed attempt evidence is still retained as append-only observability.
    """
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

    generated = []
    for offset in range(request.variation_count):
        variant = request.starting_variant + offset
        try:
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
        render_source_image=(
            render_source if request.source_region is not None else None
        ),
        render_source_media_type=render_source_media_type,
        render_source_instruction=render_source_instruction,
        candidates=tuple(CreativeCandidateInput(
            image=result.image_bytes,
            instruction=effective_instruction,
            image_run=result,
        ) for result in generated),
        owner=request.owner,
        title=request.title,
        collection=request.collection,
        tags=request.tags,
    )
    project = db.get(Project, persisted.root_id)
    if project is None:  # pragma: no cover - transaction invariant
        raise RuntimeError("persisted creative project is unavailable")
    ensure_project_family(db, project)
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
):
    """Bind one chosen candidate to designer-confirmed immutable spec v1."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="creative project not found")
    if project.owner != request.created_by:
        return JSONResponse(status_code=403, content={
            "code": "creative_project_owner_mismatch",
            "error_category": "authorization_failure",
            "detail": "only the project owner may promote a creative candidate",
        })
    spec, error = _validate_confirmed_import_spec(request.spec)
    if error:
        return error
    selected_candidate = db.get(ImageAsset, candidate_id)
    coverage_error = _confirmed_import_coverage_error(
        spec,
        bytes(selected_candidate.image) if selected_candidate is not None else None,
    )
    if coverage_error is not None:
        return coverage_error
    try:
        promote_creative_candidate(
            db,
            root_id=project_id,
            candidate_asset_id=candidate_id,
            spec=spec,
            created_by=request.created_by,
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
    response_model_exclude_none=True,
)
def create_project_from_image(request: ProjectFromImageRequest, db: DbSession):
    """Persist a designer-confirmed ring or pendant-necklace reference."""
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
    spec, error = _validate_confirmed_import_spec(request.spec)
    if error:
        return error
    coverage_error = _confirmed_import_coverage_error(spec, image)
    if coverage_error is not None:
        return coverage_error

    try:
        result = persist_project_v1(
            db,
            PersistedProjectInput(
                spec=spec,
                primary_image=image,
                primary_capability="IMPORTED_REFERENCE",
                primary_instruction="Designer-confirmed imported reference",
                primary_media_type=detected,
            ),
            owner=request.owner,
            title=request.title,
            collection=request.collection,
            tags=request.tags,
        )
    except DesignAlreadyLinked as exc:
        return JSONResponse(status_code=409, content={
            "error_category": "design_already_linked",
            "detail": str(exc),
            "existing_root_id": exc.root_id,
        })
    return project_detail(db, db.get(Project, result.root_id))


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
)
def create_project_from_brief(
    request: ProjectFromBriefRequest,
    db: DbSession,
    generate: BriefGeneratorDep,
):
    """Create a ring through the injected, QA-gated jewelry image agent."""
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


@router.get("/from-brief/candidates/{candidate_id}/image")
def get_brief_warning_image(candidate_id: str):
    try:
        candidate = get_brief_warning_candidate(candidate_id)
    except WarningCandidateUnavailable as exc:
        return JSONResponse(status_code=410, content={
            "code": "warning_candidate_unavailable",
            "category": "conflict",
            "detail": str(exc),
        })
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
)
def accept_brief_warning(
    candidate_id: str,
    request: BriefWarningAcceptRequest,
    db: DbSession,
):
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


@router.post("/{root_id}/render", status_code=201)
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
        return image_agent_error_response(exc, image_run_id=run_id)
    if not result.accepted:
        run_id = persist_image_agent_result(
            db, result, project_root_id=root_id, source_asset_id=source.id,
            created_by=request.created_by)
        qa = _quality_payload(result)
        routing = _routing_payload(result, run_id)
        candidate = store_markup_warning_candidate(
            run_id=run_id,
            project_root_id=root_id,
            source_asset_id=source.id,
            expected_active_asset_id=active.id,
            expected_design_version=latest.version,
            image_bytes=result.image_bytes,
            media_type=sniff_media_type(result.image_bytes),
            operation=ImageOperation.SPEC_RENDER.value,
            asset_capability="SPEC_RENDER",
            requested_change=request.instruction,
            region_description="entire designer-confirmed ring",
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
            "source_asset_id": source.id,
            "image_run_id": run_id,
            "quality_report": qa,
            "routing": routing,
            "warning_candidate": {
                "run_id": run_id,
                "candidate_id": candidate.candidate_id,
                "preview_url": (
                    f"/image-runs/{run_id}/candidates/"
                    f"{candidate.candidate_id}/image"
                ),
                "operation": ImageOperation.SPEC_RENDER.value,
                "asset_capability": "SPEC_RENDER",
                "qa": qa,
                "requested_change": request.instruction,
            },
        })
    persisted = persist_project_primary_revision(
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


@router.post("/{root_id}/product-photo", status_code=201)
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
        return image_agent_error_response(exc, image_run_id=run_id)

    qa = _quality_payload(result)
    if result.review_required:
        run_id = persist_image_agent_result(
            db, result, project_root_id=root_id,
            source_asset_id=source.id, created_by=request.created_by)
        routing = _routing_payload(result, run_id)
        candidate = store_markup_warning_candidate(
            run_id=run_id,
            project_root_id=root_id,
            source_asset_id=source.id,
            expected_active_asset_id=source.id,
            expected_design_version=latest.version,
            image_bytes=result.image_bytes,
            media_type=sniff_media_type(result.image_bytes),
            operation=ImageOperation.VISUAL_ONLY_EDIT.value,
            asset_capability="PRODUCT_PHOTO",
            requested_change=brief.intent,
            region_description="entire product presentation; jewelry design frozen",
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
            "presentation": {
                "preset": request.preset,
                "framing": request.framing,
                "source_asset_id": source.id,
                "design_version": latest.version,
            },
            "warning_candidate": {
                "run_id": run_id,
                "candidate_id": candidate.candidate_id,
                "preview_url": (
                    f"/image-runs/{run_id}/candidates/"
                    f"{candidate.candidate_id}/image"
                ),
                "qa": qa,
                "operation": ImageOperation.VISUAL_ONLY_EDIT.value,
                "requested_change": brief.intent,
            },
        })

    persisted = persist_project_primary_revision(
        db,
        root_id=root_id,
        image=result.image_bytes,
        capability="PRODUCT_PHOTO",
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
        )
        candidates.append({
            "preset": preset,
            "framing": request.framing,
            "image_run_id": run_id,
            "candidate_id": candidate.candidate_id,
            "preview_url": (
                f"/image-runs/{run_id}/candidates/"
                f"{candidate.candidate_id}/image"
            ),
            "qa": qa,
            "routing": routing,
        })

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
    try:
        result = JewelryImageAgent(
            evaluator=ConfirmedLineArtQualityEvaluator(),
        ).run(plan, source_image=source_control)
    except ImageAgentError as exc:
        run_id = persist_image_agent_failure(
            db, plan, exc, project_root_id=root_id,
            source_asset_id=source.id, created_by=request.created_by)
        return image_agent_error_response(exc, image_run_id=run_id)

    result = _designer_review_result(result)
    run_id = persist_image_agent_result(
        db, result, project_root_id=root_id,
        source_asset_id=source.id, created_by=request.created_by)
    qa = _quality_payload(result)
    routing = _routing_payload(result, run_id)
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
            "preview_url": (
                f"/image-runs/{run_id}/candidates/"
                f"{candidate.candidate_id}/image"
            ),
            "operation": ImageOperation.VISUAL_ONLY_EDIT.value,
            "asset_capability": "LINE_ART",
            "qa": qa,
            "requested_change": brief.intent,
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

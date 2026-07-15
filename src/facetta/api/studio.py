"""AI-first Studio branching, immutable history, and restoration APIs."""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from facetta.api.error_mapping import (
    image_agent_error_response,
    provider_studio_job_error_response,
)
from facetta.api.projects import (
    ProductPhotoRequest,
    ProjectDetail,
    ProjectFromImageRequest,
    ProjectRenderRequest,
    confirmed_import_response,
    create_product_photo,
    project_card,
    project_detail,
    render_project_revision,
)
from facetta.auth import (
    AuthenticatedPrincipal,
    principal_actor,
    require_principal_boundary,
)
from facetta.db import (
    DesignFamily,
    DesignVersion,
    ImageAsset,
    ImageRun,
    Project,
    ProjectRevisionRecord,
    StudioJobRecord,
    get_db,
    new_id,
    utcnow,
)
from facetta.image_agent import (
    ImageAgentError,
    ImageAgentResult,
    ImageOperation,
    JewelryImageAgent,
    build_image_plan,
)
from facetta.image_run_store import (
    persist_image_agent_failure,
    persist_image_agent_result,
)
from facetta.media import sniff_media_type
from facetta.markup_interpretations import (
    MarkupInterpretationError,
    confirmed_annotation,
    require_confirmed_markup_interpretation,
)
from facetta.project_backbone import (
    accepted_creative_candidate,
    is_canonical_revision,
    is_primary_revision,
)
from facetta.presentation import (
    PresentationScopeError,
    ProductPhotoFraming,
    ProductPhotoPreset,
    compile_product_photo_brief,
)
from facetta.provider_job_gate import (
    ProviderStudioJobError,
    require_provider_studio_job,
)
from facetta.spec import Spec
from facetta.specagent import mask_from_markup
from facetta.studio_history import (
    StudioHistoryError,
    apply_pre_spec_visual_candidate,
    discard_pre_spec_visual_candidate,
    fork_preview_candidate_variation,
    fork_project_revision_variation,
    fork_project_variation,
    restore_project_revision,
)
from facetta.studio_candidate_reconciliation import (
    reconcile_studio_review_jobs,
)
from facetta.studio_jobs import (
    FactoryJobContextError,
    STUDIO_JOB_ACTIONS,
    lock_factory_job_context,
    studio_job_action_definition,
)
from facetta.studio_visual_candidates import (
    StudioVisualCandidateUnavailable,
    StudioVisualJobError,
    fail_reserved_studio_visual_job,
    get_studio_visual_candidate,
    invalidate_studio_visual_candidate,
    list_studio_visual_candidates,
    remove_studio_visual_candidate,
    reserve_studio_visual_job,
    store_studio_visual_candidate,
)
from facetta.studio_markup_candidates import (
    StudioMarkupCandidateUnavailable,
    StudioMarkupError,
    accept_studio_markup_candidate,
    discard_studio_markup_candidate,
    get_studio_markup_candidate,
    list_studio_markup_candidates,
)
from facetta.studio_preview_candidates import (
    StudioPreviewCandidate,
    StudioPreviewCandidateError,
    decide_studio_preview_candidate,
    get_studio_preview_candidate,
    get_studio_preview_image,
    list_studio_preview_candidates,
)
from facetta.studio_presentation_candidates import (
    StudioPresentationCandidateUnavailable,
    StudioPresentationError,
    accept_studio_presentation_candidate,
    discard_studio_presentation_candidate,
    fail_reserved_studio_presentation_job,
    get_studio_presentation_candidate,
    list_studio_presentation_candidates,
    reserve_studio_presentation_job,
    store_studio_presentation_candidate,
)
from facetta.studio_view_candidates import (
    StudioViewCandidateUnavailable,
    StudioViewError,
    accept_studio_view_candidate,
    discard_studio_view_candidate,
    get_studio_view_candidate,
    list_studio_view_candidates,
)
from facetta.trusted_revision import (
    WarningRevisionError,
    accept_warning_revision,
    discard_warning_revision,
)
from facetta.entitlements import has_factory_entitlement, require_factory_entitlement
from facetta.warning_candidates import (
    MarkupWarningCandidate,
    WarningCandidateUnavailable,
    discard_markup_warning_candidate,
    get_markup_warning_candidate,
)


router = APIRouter(
    prefix="/studio",
    tags=["studio"],
    dependencies=[Depends(require_principal_boundary)],
)
DbSession = Annotated[Session, Depends(get_db)]
PrincipalDep = Annotated[AuthenticatedPrincipal, Depends(require_principal_boundary)]


class StudioFactoryCapability(BaseModel):
    enabled: bool
    scope: Literal["principal"] = "principal"


class StudioCapabilities(BaseModel):
    factory_review: StudioFactoryCapability
    workspace_entitlements_available: Literal[False] = False


class StudioBeautyRenderRequest(ProjectRenderRequest):
    """Exact-revision Client preview bound to one accounted Studio job."""

    presentation_only: Literal[True]
    studio_job_id: Annotated[str, Field(min_length=1, max_length=32)]


class StudioProductPhotoRequest(ProductPhotoRequest):
    """Exact-revision product preview bound to one accounted Studio job."""

    presentation_only: Literal[True]
    studio_job_id: Annotated[str, Field(min_length=1, max_length=32)]


@router.post(
    "/projects/import-confirmed",
    status_code=201,
    response_model=ProjectDetail,
    response_model_exclude_none=True,
)
def import_confirmed_studio_project(
    request: ProjectFromImageRequest,
    db: DbSession,
    principal: PrincipalDep,
):
    """Create Design v1 only from an exact source-bound confirmed audit."""
    return confirmed_import_response(request, db, principal)


@router.get("/capabilities", response_model=StudioCapabilities)
def get_studio_capabilities(principal: PrincipalDep) -> StudioCapabilities:
    """Return server-owned capabilities for the authenticated Studio actor.

    There is no workspace membership model yet, so this response says so and
    exposes only an exact principal-scoped Factory capability.
    """
    return StudioCapabilities(
        factory_review=StudioFactoryCapability(
            enabled=has_factory_entitlement(principal),
        ),
    )


@router.post("/projects/{root_id}/beauty-render", status_code=201)
def create_studio_beauty_render(
    root_id: str,
    request: StudioBeautyRenderRequest,
    db: DbSession,
    principal: PrincipalDep,
):
    """Delegate an exact, review-only Client render to trusted persistence."""
    principal_actor(principal, request.created_by)
    return render_project_revision(root_id, request, db)


@router.post("/projects/{root_id}/product-photo", status_code=201)
def create_studio_product_photo(
    root_id: str,
    request: StudioProductPhotoRequest,
    db: DbSession,
    principal: PrincipalDep,
):
    """Delegate exact product photography without exposing legacy mutation."""
    principal_actor(principal, request.created_by)
    return create_product_photo(root_id, request, db)


class SaveVariationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created_by: Annotated[str, Field(min_length=1, max_length=32)]
    expected_active_asset_id: Annotated[str, Field(min_length=1, max_length=32)]
    expected_design_version: Annotated[int, Field(ge=1)] | None = None
    label: Annotated[str, Field(min_length=1, max_length=120)]


class SaveCurrentVariationRequest(SaveVariationRequest):
    operation_id: Annotated[
        str,
        Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"),
    ]


class SaveCreativeVariationRequest(SaveVariationRequest):
    """Retry-safe request for preserving one generated Create direction."""

    operation_id: Annotated[
        str,
        Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"),
    ]


class SaveRevisionVariationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created_by: Annotated[str, Field(min_length=1, max_length=32)]
    expected_active_asset_id: Annotated[str, Field(min_length=1, max_length=32)]
    expected_active_design_version: Annotated[int, Field(ge=1)] | None
    expected_source_design_version: Annotated[int, Field(ge=1)] | None
    expected_source_sha256: Annotated[
        str,
        Field(pattern=r"^[0-9a-f]{64}$"),
    ]
    label: Annotated[str, Field(min_length=1, max_length=120)]
    operation_id: Annotated[
        str,
        Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"),
    ]


class RevisionVariationMember(BaseModel):
    project_root_id: str
    asset_id: str
    design_id: str | None
    design_version: int | None
    family_id: str
    variation_index: int
    branched_from_project_root_id: str
    branched_from_asset_id: str
    component_map_status: Literal["mapped", "unmapped"]
    component_map_sha256: str | None


class RevisionVariationResponse(BaseModel):
    status: Literal["variation_created"]
    family_id: str
    variation_index: int
    source_project_id: str
    source_asset_id: str
    source_design_version: int | None
    source_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    guarded_active_asset_id: str
    guarded_active_design_version: int | None
    child_project_root_id: str
    child_asset_id: str
    child_design_id: str | None
    child_design_version: int | None
    child_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    child_family_id: str
    child_variation_index: int
    child_branched_from_project_root_id: str
    child_branched_from_asset_id: str
    component_map_status: Literal["mapped", "unmapped"]
    component_map_sha256: str | None
    variation: RevisionVariationMember
    project: ProjectDetail


class SavePreviewVariationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created_by: Annotated[str, Field(min_length=1, max_length=32)]
    label: Annotated[str, Field(min_length=1, max_length=120)]


class RestoreRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created_by: Annotated[str, Field(min_length=1, max_length=32)]
    expected_active_asset_id: Annotated[str, Field(min_length=1, max_length=32)]
    expected_design_version: Annotated[int, Field(ge=1)] | None = None


StudioJobStatus = Literal[
    "queued", "running", "reviewing", "succeeded", "failed", "canceled",
]
StudioJobAction = Literal[
    "create", "vary", "refine", "views", "present", "factory",
]
StudioJobLane = Literal["instant", "fast_visual", "trusted_structural"]


class CreateStudioJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner: Annotated[str, Field(min_length=1, max_length=32)]
    action_id: StudioJobAction
    lane: StudioJobLane
    active_design_id: Annotated[str, Field(min_length=1, max_length=32)] | None = None
    source_revision_id: Annotated[str, Field(min_length=1, max_length=32)] | None = None
    requested_outputs: Annotated[int, Field(ge=1, le=4)]
    credits_per_output: Annotated[int, Field(ge=0, le=100000)]


class TransitionStudioJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner: Annotated[str, Field(min_length=1, max_length=32)]
    status: StudioJobStatus
    progress: Annotated[float, Field(ge=0, le=1)]
    completed_outputs: Annotated[int, Field(ge=0, le=4)] | None = None
    error_code: Annotated[str, Field(min_length=1, max_length=64)] | None = None
    active_design_id: Annotated[str, Field(min_length=1, max_length=32)] | None = None
    source_revision_id: Annotated[str, Field(min_length=1, max_length=32)] | None = None


class CancelStudioJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner: Annotated[str, Field(min_length=1, max_length=32)]


class ResolvePresentationCandidateRequest(BaseModel):
    """Exact lineage required for a terminal presentation decision."""

    model_config = ConfigDict(extra="forbid")

    created_by: Annotated[str, Field(min_length=1, max_length=32)]
    expected_project_id: Annotated[str, Field(min_length=1, max_length=32)]
    expected_source_asset_id: Annotated[str, Field(min_length=1, max_length=32)]
    expected_design_version: Annotated[int, Field(ge=1)]


class ResolveViewCandidateRequest(BaseModel):
    """Exact project, source, and specification guards for a View decision."""

    model_config = ConfigDict(extra="forbid")

    created_by: Annotated[str, Field(min_length=1, max_length=32)]
    expected_project_id: Annotated[str, Field(min_length=1, max_length=32)]
    expected_source_asset_id: Annotated[str, Field(min_length=1, max_length=32)]
    expected_design_version: Annotated[int, Field(ge=1)]


class CreateVisualPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created_by: Annotated[str, Field(min_length=1, max_length=32)]
    expected_active_asset_id: Annotated[str, Field(min_length=1, max_length=32)]
    instruction: Annotated[str, Field(min_length=3, max_length=1000)]
    scope: Literal["appearance", "marked_region"]
    mask_base64: Annotated[str, Field(min_length=1, max_length=14_000_000)] | None = None
    markup_asset_id: Annotated[str, Field(min_length=1, max_length=32)] | None = None
    confirmed_interpretation_id: Annotated[
        str, Field(min_length=1, max_length=32)
    ] | None = None
    variant: Annotated[int, Field(ge=0, le=100)] = 0
    studio_job_id: Annotated[str, Field(min_length=1, max_length=32)] | None = None


class ReviewVisualPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created_by: Annotated[str, Field(min_length=1, max_length=32)]
    expected_active_asset_id: Annotated[str, Field(min_length=1, max_length=32)]


class ReviewMarkupCandidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created_by: Annotated[str, Field(min_length=1, max_length=32)]
    expected_active_asset_id: Annotated[str, Field(min_length=1, max_length=32)]
    expected_design_version: Annotated[int, Field(ge=1)]


StudioPreviewKind = Literal["visual", "catalog_revision", "markup"]
StudioPreviewStatus = Literal[
    "reviewing", "applied", "saved_as_variation", "discarded", "expired",
]
StudioPreviewDecision = Literal["apply", "save_as_variation", "discard"]


class StudioPreviewCandidateBase(BaseModel):
    """Fields shared by every temporary Refine output."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    status: StudioPreviewStatus
    image_run_id: str
    project_root_id: str
    source_asset_id: str
    expected_active_asset_id: str
    expected_design_version: int | None
    source_sha256: str
    output_sha256: str
    requested_change: str
    verdict: Literal["pass", "warn"] | None
    qa: dict
    studio_job_id: str | None
    terminal_asset_id: str | None
    created_at: datetime
    expires_at: datetime
    resolved_at: datetime | None
    available_decisions: tuple[StudioPreviewDecision, ...]
    preview_url: str
    decision_url: str


class StudioVisualPreviewCandidateResponse(StudioPreviewCandidateBase):
    kind: Literal["visual"] = "visual"
    scope: Literal["appearance", "marked_region"]


class StudioCatalogPreviewCandidateResponse(StudioPreviewCandidateBase):
    kind: Literal["catalog_revision"] = "catalog_revision"
    component_path: str
    option_id: str
    spec_change: tuple[dict, ...]
    next_spec: Spec


class StudioMarkupPreviewCandidateResponse(StudioPreviewCandidateBase):
    kind: Literal["markup"] = "markup"
    operation: str
    region_description: str


StudioPreviewCandidateResponse = Annotated[
    StudioVisualPreviewCandidateResponse
    | StudioCatalogPreviewCandidateResponse
    | StudioMarkupPreviewCandidateResponse,
    Field(discriminator="kind"),
]


class StudioPreviewCandidateListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidates: list[StudioPreviewCandidateResponse]


class DecideStudioPreviewCandidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created_by: Annotated[str, Field(min_length=1, max_length=32)]
    decision: StudioPreviewDecision
    expected_active_asset_id: Annotated[str, Field(min_length=1, max_length=32)]
    expected_design_version: Annotated[int, Field(ge=1)] | None = None
    variation_label: Annotated[str, Field(min_length=1, max_length=120)] | None = None


class StudioPreviewCandidateDecisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["applied", "saved_as_variation", "discarded"]
    candidate_id: str
    kind: StudioPreviewKind
    source_project_id: str
    result_project_id: str
    terminal_asset_id: str | None
    studio_job_id: str | None
    family_id: str | None
    variation_index: int | None


class CreatePreSpecPresentationRequest(BaseModel):
    """One explicitly review-only Client or Marketing presentation preview."""

    model_config = ConfigDict(extra="forbid")

    created_by: Annotated[str, Field(min_length=1, max_length=32)]
    expected_active_asset_id: Annotated[str, Field(min_length=1, max_length=32)]
    destination: Literal["client", "marketing"]
    client_format: Literal["beauty", "product"] = "product"
    preset: ProductPhotoPreset = "catalog_white"
    framing: ProductPhotoFraming = "square"
    custom_instruction: Annotated[str, Field(max_length=600)] = ""
    variant: Annotated[int, Field(ge=0, le=100)] = 0
    studio_job_id: Annotated[str, Field(min_length=1, max_length=32)]


class ReviewPreSpecPresentationRequest(BaseModel):
    """Client-supplied optimistic guards for one terminal decision."""

    model_config = ConfigDict(extra="forbid")

    created_by: Annotated[str, Field(min_length=1, max_length=32)]
    expected_active_asset_id: Annotated[str, Field(min_length=1, max_length=32)]
    expected_source_sha256: Annotated[
        str, Field(pattern=r"^[0-9a-f]{64}$")
    ]


VisualPreviewGenerator = Callable[
    [bytes, str, Literal["appearance", "marked_region"], bytes | None, int],
    ImageAgentResult,
]


def generate_studio_visual_preview(
    source_image: bytes,
    instruction: str,
    scope: Literal["appearance", "marked_region"],
    mask_bytes: bytes | None,
    variant: int,
) -> ImageAgentResult:
    """Run a source-faithful, explicitly non-structural pre-spec edit."""

    scope_instruction = (
        "PRE-SPEC APPEARANCE REFINEMENT ONLY. Change presentation, color, "
        "surface finish, or material appearance as requested. Preserve exact "
        "jewelry geometry, silhouette, topology, component count, proportions, "
        "stone shapes, stone placement, setting, and construction. "
        if scope == "appearance" else
        "PRE-SPEC MARKED-REGION APPEARANCE REFINEMENT ONLY. Change only the "
        "designer-marked pixels as requested. Preserve every pixel outside "
        "the mask and preserve all jewelry geometry, topology, component count, "
        "proportions, stone shapes, stone placement, setting, and construction. "
    )
    plan = build_image_plan(
        ImageOperation.REFERENCE_RENDER,
        scope_instruction + instruction.strip(),
        source_image=source_image,
        mask_bytes=mask_bytes,
        mask_provenance=(
            "designer_marked_pre_spec_region" if mask_bytes is not None else None
        ),
        region_description=(
            "designer-marked appearance region"
            if scope == "marked_region" else None
        ),
        frozen=(
            "exact jewelry geometry and silhouette",
            "exact topology, component count, proportions, and placement",
            "all construction and setting details",
            "all pixels outside the designer mask" if mask_bytes is not None
            else "camera and composition unless explicitly requested",
        ),
        expected_output=(
            "one source-faithful pre-spec visual preview with only the requested "
            "appearance change and no structural authority"
        ),
        variant=variant,
    )
    return JewelryImageAgent().run(
        plan,
        source_image=source_image,
        mask_bytes=mask_bytes,
    )


def get_studio_visual_preview_generator() -> VisualPreviewGenerator:
    return generate_studio_visual_preview


VisualPreviewGeneratorDep = Annotated[
    VisualPreviewGenerator, Depends(get_studio_visual_preview_generator)]


PreSpecPresentationGenerator = Callable[
    [bytes, str, tuple[str, ...], str, int], ImageAgentResult,
]


def generate_pre_spec_presentation_preview(
    source_image: bytes,
    intent: str,
    style_constraints: tuple[str, ...],
    expected_output: str,
    variant: int,
) -> ImageAgentResult:
    """Create a source-faithful presentation without claiming spec authority."""

    plan = build_image_plan(
        ImageOperation.REFERENCE_RENDER,
        (
            "PRE-SPEC PRESENTATION ONLY. Restage this exact visible jewelry "
            "direction without redesigning it. Preserve the exact silhouette, "
            "topology, component count, proportions, stone shapes, stone "
            "placement, setting, and visible construction. " + intent
        ),
        source_image=source_image,
        frozen=(
            "exact visible jewelry geometry and silhouette",
            "exact visible topology, component count, proportions, and placement",
            "every visible stone shape, setting, and construction detail",
        ),
        style_constraints=style_constraints,
        expected_output=expected_output,
        variant=variant,
    )
    return JewelryImageAgent().run(plan, source_image=source_image)


def get_pre_spec_presentation_generator() -> PreSpecPresentationGenerator:
    return generate_pre_spec_presentation_preview


PreSpecPresentationGeneratorDep = Annotated[
    PreSpecPresentationGenerator,
    Depends(get_pre_spec_presentation_generator),
]


_JOB_TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"running", "canceled", "failed"}),
    "running": frozenset({"reviewing", "canceled", "failed"}),
    # Once an output is in review, its candidate-specific Accept/Discard
    # endpoint owns the atomic candidate + job decision. Generic cancellation
    # would otherwise strand a reviewable candidate behind a canceled job.
    "reviewing": frozenset({"succeeded", "failed"}),
    "succeeded": frozenset(),
    "failed": frozenset(),
    "canceled": frozenset(),
}

# Candidate generation owns the transition into reviewing, and the
# candidate-specific Apply/Save/Discard transaction owns successful settlement.
# A public lifecycle report may start work or report a pre-review failure, but it
# must not fabricate either candidate existence or canonical acceptance.
_CANDIDATE_OWNED_REVIEW_ACTIONS = frozenset(
    action_id
    for action_id, definition in STUDIO_JOB_ACTIONS.items()
    if definition.review_authority == "candidate_decision"
)

_BILLING_POLICY = (
    "Only requested outputs accepted by a backend decision are charged. "
    "Client completion reports, internal retries, and failed review attempts "
    "are not charged."
)


def _factory_job_pre_insert_hook() -> None:
    """Deterministic test seam between optimistic and locked validation."""


def _studio_job(job: StudioJobRecord) -> dict:
    def timestamp(value):
        # SQLite does not retain timezone metadata; API timestamps remain UTC
        # and stable before and after a persistence round-trip.
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()

    return {
        "job_id": job.id,
        "owner": job.owner,
        "action_id": job.action_id,
        "lane": job.lane,
        "status": job.status,
        "progress": job.progress,
        "active_design_id": job.active_design_id,
        "source_revision_id": job.source_revision_id,
        "accepted_output_sha256": job.accepted_output_sha256,
        "error_code": job.error_code,
        "created_at": timestamp(job.created_at),
        "updated_at": timestamp(job.updated_at),
        "billing": {
            "requested_outputs": job.requested_outputs,
            "credits_per_output": job.credits_per_output,
            "estimated_credits": (
                job.requested_outputs * job.credits_per_output
            ),
            "completed_outputs": job.completed_outputs,
            "charged_outputs": job.charged_outputs,
            "charged_credits": job.charged_outputs * job.credits_per_output,
            "policy": _BILLING_POLICY,
        },
    }


def _owned_job(
    db: Session,
    job_id: str,
    owner: str,
    *,
    for_update: bool = False,
) -> StudioJobRecord:
    query = select(StudioJobRecord).where(
        StudioJobRecord.id == job_id,
        StudioJobRecord.owner == owner,
    )
    if for_update:
        query = query.with_for_update()
    job = db.scalar(query)
    if job is None:
        # Do not disclose another owner's job identity.
        raise HTTPException(status_code=404, detail=f"unknown Studio job '{job_id}'")
    return job


def _require_studio_job_context(
    db: Session,
    request: CreateStudioJobRequest,
) -> None:
    """Validate server-owned action context before reserving any work."""

    action = studio_job_action_definition(request.action_id)
    if action.execution_mode == "instant_transaction":
        raise HTTPException(
            status_code=422,
            detail=(
                f"{request.action_id} is an atomic Studio transaction and does "
                "not create a Studio job"
            ),
        )
    requirements = frozenset(action.context_requirements)
    if "active_project" not in requirements:
        return
    if request.active_design_id is None or request.source_revision_id is None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"{request.action_id} requires an active project and revision"
            ),
        )
    project = db.get(Project, request.active_design_id)
    if project is None or project.owner != request.owner:
        raise HTTPException(
            status_code=404,
            detail=f"unknown Studio project '{request.active_design_id}'",
        )
    detail = project_detail(db, project)
    if detail["active_asset_id"] != request.source_revision_id:
        raise HTTPException(
            status_code=409,
            detail="source_revision_id is not the project's active revision",
        )
    if "exact_specification" not in requirements:
        return
    design_id = detail["design_id"]
    design_version = detail["active_design_version"]
    if (
        design_id is None
        or design_version is None
        or db.get(DesignVersion, (design_id, design_version)) is None
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                f"{request.action_id} requires the active revision's exact "
                "validated specification"
            ),
        )
    if "factory_eligible" in requirements and not detail["factory_ready"]:
        raise HTTPException(
            status_code=409,
            detail="the active revision is not eligible for Factory review",
        )


@router.post("/jobs", status_code=201)
def create_studio_job(
    request: CreateStudioJobRequest,
    db: DbSession,
    principal: PrincipalDep,
):
    principal_actor(principal, request.owner)
    action = studio_job_action_definition(request.action_id)
    if request.action_id == "factory":
        require_factory_entitlement(principal)
    if request.lane != action.lane:
        raise HTTPException(
            status_code=422,
            detail=f"lane does not match server definition for {request.action_id}",
        )
    if request.credits_per_output != action.credits_per_output:
        raise HTTPException(
            status_code=422,
            detail=(
                "credits_per_output does not match server definition for "
                f"{request.action_id}"
            ),
        )
    _require_studio_job_context(db, request)
    if not (
        action.min_requested_outputs
        <= request.requested_outputs
        <= action.max_requested_outputs
    ):
        expected = (
            str(action.min_requested_outputs)
            if action.min_requested_outputs == action.max_requested_outputs
            else (
                f"{action.min_requested_outputs} to "
                f"{action.max_requested_outputs}"
            )
        )
        raise HTTPException(
            status_code=422,
            detail=(
                f"{request.action_id} requires {expected} requested "
                f"output{'s' if action.max_requested_outputs != 1 else ''}"
            ),
        )
    if request.action_id == "factory":
        _factory_job_pre_insert_hook()
        try:
            lock_factory_job_context(
                db,
                owner=request.owner,
                project_root_id=request.active_design_id or "",
                source_revision_id=request.source_revision_id or "",
            )
        except FactoryJobContextError as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    now = utcnow()
    job = StudioJobRecord(
        id=new_id("job"),
        owner=request.owner,
        action_id=request.action_id,
        lane=action.lane,
        status="queued",
        progress=0,
        active_design_id=request.active_design_id,
        source_revision_id=request.source_revision_id,
        requested_outputs=request.requested_outputs,
        credits_per_output=action.credits_per_output,
        completed_outputs=0,
        charged_outputs=0,
        created_at=now,
        updated_at=now,
    )
    db.add(job)
    db.commit()
    return _studio_job(job)


@router.get("/jobs")
def list_studio_jobs(
    db: DbSession,
    owner: Annotated[str, Query(min_length=1, max_length=32)],
    principal: PrincipalDep,
    status: StudioJobStatus | None = None,
):
    principal_actor(principal, owner)
    reconcile_studio_review_jobs(db, owner=owner)
    query = select(StudioJobRecord).where(StudioJobRecord.owner == owner)
    if status is not None:
        query = query.where(StudioJobRecord.status == status)
    jobs = list(db.scalars(
        query.order_by(StudioJobRecord.created_at.desc(), StudioJobRecord.id)
    ))
    return {"jobs": [_studio_job(job) for job in jobs]}


@router.get("/jobs/{job_id}")
def get_studio_job(
    job_id: str,
    db: DbSession,
    owner: Annotated[str, Query(min_length=1, max_length=32)],
    principal: PrincipalDep,
):
    principal_actor(principal, owner)
    reconcile_studio_review_jobs(db, owner=owner, job_id=job_id)
    return _studio_job(_owned_job(db, job_id, owner))


@router.patch("/jobs/{job_id}")
def transition_studio_job(
    job_id: str,
    request: TransitionStudioJobRequest,
    db: DbSession,
    principal: PrincipalDep,
):
    principal_actor(principal, request.owner)
    job = _owned_job(db, job_id, request.owner, for_update=True)
    action = studio_job_action_definition(job.action_id)
    if action.review_authority == "backend_transaction":
        raise HTTPException(
            status_code=409,
            detail=(
                f"this {job.action_id} job is owned by its backend transaction; "
                "use its dedicated preparation action"
            ),
        )
    if (
        job.action_id in _CANDIDATE_OWNED_REVIEW_ACTIONS
        and request.status not in {"running", "failed"}
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                f"public lifecycle reports for this {job.action_id} job may "
                "only set running or failed; use its dedicated candidate or "
                "cancellation action"
            ),
        )
    if request.status not in _JOB_TRANSITIONS[job.status]:
        raise HTTPException(
            status_code=409,
            detail=f"invalid Studio job transition: {job.status} -> {request.status}",
        )
    if (
        job.status == "reviewing"
        and job.action_id in _CANDIDATE_OWNED_REVIEW_ACTIONS
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                f"this {job.action_id} job is owned by its candidate decision; "
                "use its Apply, Save, or Discard action"
            ),
        )
    if request.progress < job.progress:
        raise HTTPException(status_code=409, detail="Studio job progress cannot move backward")
    for field in ("active_design_id", "source_revision_id"):
        incoming = getattr(request, field)
        current = getattr(job, field)
        if incoming is not None and current is not None and incoming != current:
            raise HTTPException(
                status_code=409,
                detail=f"Studio job {field} is already bound and cannot change",
            )

    completed = request.completed_outputs
    if request.status == "succeeded":
        if completed is None or completed < 1:
            raise HTTPException(
                status_code=422,
                detail="successful Studio jobs require completed_outputs",
            )
        if completed > job.requested_outputs:
            raise HTTPException(
                status_code=422,
                detail="completed outputs cannot exceed requested outputs",
            )
        job.progress = 1
        job.completed_outputs = completed
        # A public lifecycle report is not an acceptance or billing authority.
        # Only record_accepted_studio_job_outputs may create a charge.
        job.charged_outputs = 0
        job.error_code = None
    else:
        if completed not in (None, 0):
            raise HTTPException(
                status_code=422,
                detail="only successful Studio jobs can report completed outputs",
            )
        job.progress = request.progress
        job.completed_outputs = 0
        job.charged_outputs = 0
        job.error_code = (
            request.error_code if request.status == "failed" else None
        )
    job.status = request.status
    if request.active_design_id is not None:
        job.active_design_id = request.active_design_id
    if request.source_revision_id is not None:
        job.source_revision_id = request.source_revision_id
    job.updated_at = utcnow()
    db.commit()
    return _studio_job(job)


@router.post("/jobs/{job_id}/cancel")
def cancel_studio_job(
    job_id: str,
    request: CancelStudioJobRequest,
    db: DbSession,
    principal: PrincipalDep,
):
    principal_actor(principal, request.owner)
    job = _owned_job(db, job_id, request.owner, for_update=True)
    if "canceled" not in _JOB_TRANSITIONS[job.status]:
        raise HTTPException(
            status_code=409,
            detail=f"Studio job cannot be canceled from {job.status}",
        )
    job.status = "canceled"
    job.completed_outputs = 0
    job.charged_outputs = 0
    job.error_code = None
    job.updated_at = utcnow()
    db.commit()
    return _studio_job(job)


def _selected_pre_spec_visual(
    db: Session,
    *,
    project_root_id: str,
    expected_active_asset_id: str,
    created_by: str,
) -> tuple[Project, ImageAsset]:
    project = db.get(Project, project_root_id)
    source = db.get(ImageAsset, expected_active_asset_id)
    root = db.get(ImageAsset, project_root_id)
    if project is None or source is None or root is None:
        raise StudioHistoryError(
            "visual_preview_source_unavailable",
            "the selected pre-spec visual is unavailable",
            status_code=404,
        )
    if project.owner != created_by:
        raise StudioHistoryError(
            "visual_preview_source_unavailable",
            "the selected pre-spec visual is unavailable",
            status_code=404,
        )
    if root.design_id is not None or source.design_version is not None:
        raise StudioHistoryError(
            "visual_preview_requires_pre_spec_project",
            "this route refines visuals only and cannot change specification-linked work",
            status_code=422,
        )
    if source.root_id != project.root_id or not is_primary_revision(source):
        raise StudioHistoryError(
            "visual_preview_source_invalid",
            "select a canonical pre-spec visual before continuing",
            status_code=422,
        )
    if project.selected_candidate_asset_id != source.id:
        raise StudioHistoryError(
            "stale_asset_revision",
            "the selected visual changed; reload before creating a preview",
        )
    return project, source


def _decode_visual_mask(
    db: Session,
    encoded: str | None,
    *,
    created_by: str,
    markup_asset_id: str | None,
    scope: Literal["appearance", "marked_region"],
    source_asset: ImageAsset,
    source: bytes,
) -> bytes | None:
    if scope == "appearance":
        if encoded is not None or markup_asset_id is not None:
            raise StudioHistoryError(
                "visual_preview_mask_unexpected",
                "an appearance preview cannot include a marked-region mask",
                status_code=422,
            )
        return None
    if encoded is not None and markup_asset_id is not None:
        raise StudioHistoryError(
            "visual_preview_mask_ambiguous",
            "provide either markup_asset_id or mask_base64, not both",
            status_code=422,
        )
    if markup_asset_id is not None:
        notes = db.get(ImageAsset, markup_asset_id)
        if (notes is None
                or notes.capability != "MARKUP_NOTES"
                or notes.root_id != source_asset.root_id
                or notes.parent_asset_id != source_asset.id
                or notes.created_by != created_by):
            raise StudioHistoryError(
                "visual_preview_markup_invalid",
                "the markup must be saved from this exact selected visual",
                status_code=422,
            )
        derived = mask_from_markup(source, bytes(notes.image))
        if derived is None:
            raise StudioHistoryError(
                "visual_preview_markup_mask_unavailable",
                "the saved markup has no usable same-raster marked region",
                status_code=422,
            )
        return derived
    if encoded is None:
        raise StudioHistoryError(
            "visual_preview_mask_required",
            "a marked-region preview requires a same-size raster mask",
            status_code=422,
        )
    try:
        mask = base64.b64decode(encoded, validate=True)
        with Image.open(io.BytesIO(source)) as source_image:
            source_size = source_image.size
        with Image.open(io.BytesIO(mask)) as mask_image:
            mask_size = mask_image.size
            mask_image.verify()
    except (binascii.Error, ValueError, OSError) as exc:
        raise StudioHistoryError(
            "visual_preview_mask_invalid",
            "mask_base64 must contain a decodable PNG, JPEG, or WebP raster",
            status_code=422,
        ) from exc
    if source_size != mask_size:
        raise StudioHistoryError(
            "visual_preview_mask_size_mismatch",
            "the marked-region mask must match the selected visual dimensions",
            status_code=422,
        )
    return mask


def _visual_preview_qa(result: ImageAgentResult) -> dict:
    failed = list(result.quality.failed_checks)
    return {
        **result.quality.model_dump(mode="json"),
        "accepted": result.accepted,
        "review_required": result.review_required,
        "summary": (
            "Image checks passed."
            if result.accepted else "Image needs explicit designer review."
        ),
        "failed_checks": [check.code for check in failed],
        "warnings": [
            check.message for check in failed
            if check.severity.value == "warning"
        ],
    }


@router.post("/projects/{project_id}/visual-previews", status_code=201)
def create_visual_preview(
    project_id: str,
    request: CreateVisualPreviewRequest,
    db: DbSession,
    generate: VisualPreviewGeneratorDep,
):
    """Generate a temporary pre-spec appearance preview without mutation."""

    if request.studio_job_id is None:
        try:
            require_provider_studio_job(
                db,
                job_id=None,
                owner=request.created_by,
                action_id="refine",
                requested_outputs=1,
                active_design_id=project_id,
                source_revision_id=request.expected_active_asset_id,
            )
        except ProviderStudioJobError as exc:
            return provider_studio_job_error_response(exc)
    if request.studio_job_id is not None:
        try:
            reserve_studio_visual_job(
                db,
                job_id=request.studio_job_id,
                owner=request.created_by,
                project_root_id=project_id,
                source_asset_id=request.expected_active_asset_id,
            )
        except StudioVisualJobError as exc:
            return JSONResponse(status_code=exc.status_code, content={
                "code": exc.code,
                "category": (
                    "not_found" if exc.status_code == 404 else "validation"
                    if exc.status_code == 422 else "conflict"
                ),
                "detail": exc.detail,
            })
    try:
        project, source = _selected_pre_spec_visual(
            db,
            project_root_id=project_id,
            expected_active_asset_id=request.expected_active_asset_id,
            created_by=request.created_by,
        )
        markup_asset_id = request.markup_asset_id
        if request.scope == "marked_region":
            if request.mask_base64 is not None:
                raise StudioHistoryError(
                    "markup_interpretation_substitution",
                    "a confirmed marked preview must use its saved markup evidence",
                    status_code=422,
                )
            try:
                interpretation_record = (
                    require_confirmed_markup_interpretation(
                        db,
                        request.confirmed_interpretation_id,
                        owner=request.created_by,
                        project_root_id=project.root_id,
                        source_asset_id=source.id,
                        current_design_version=None,
                        current_spec_visual_hash=None,
                        supplied_markup_asset_id=request.markup_asset_id,
                        supplied_instruction=request.instruction,
                    )
                )
                # Validate the canonical provider evidence before using its
                # exact saved markup parent. Pre-spec visual previews cannot
                # execute an interpretation classified as specification work;
                # those facts must go through Starting Facts first.
                annotation = confirmed_annotation(interpretation_record)
                if annotation.get("impact") != "visual_only":
                    raise MarkupInterpretationError(
                        "markup_interpretation_impact_invalid",
                        "pre-spec marked previews require a visual-only interpretation",
                        422,
                    )
                markup_asset_id = interpretation_record.markup_asset_id
            except MarkupInterpretationError as exc:
                raise StudioHistoryError(
                    exc.code, exc.detail, status_code=exc.status_code,
                ) from exc
        elif request.confirmed_interpretation_id is not None:
            raise StudioHistoryError(
                "visual_preview_confirmation_unexpected",
                "an appearance preview does not use markup confirmation",
                status_code=422,
            )
        mask = _decode_visual_mask(
            db,
            request.mask_base64,
            created_by=request.created_by,
            markup_asset_id=markup_asset_id,
            scope=request.scope,
            source_asset=source,
            source=bytes(source.image),
        )
    except StudioHistoryError as exc:
        if request.studio_job_id is not None:
            fail_reserved_studio_visual_job(
                db,
                job_id=request.studio_job_id,
                owner=request.created_by,
                error_code=exc.code,
            )
        return _error(exc)

    try:
        result = generate(
            bytes(source.image),
            request.instruction,
            request.scope,
            mask,
            request.variant,
        )
    except ImageAgentError as exc:
        run_id = (
            persist_image_agent_failure(
                db,
                exc.plan,
                exc,
                project_root_id=project.root_id,
                source_asset_id=source.id,
                created_by=request.created_by,
                commit=request.studio_job_id is None,
            )
            if exc.plan is not None else None
        )
        if request.studio_job_id is not None:
            fail_reserved_studio_visual_job(
                db,
                job_id=request.studio_job_id,
                owner=request.created_by,
                error_code=exc.code,
            )
        return image_agent_error_response(exc, image_run_id=run_id)
    except Exception:
        if request.studio_job_id is not None:
            fail_reserved_studio_visual_job(
                db,
                job_id=request.studio_job_id,
                owner=request.created_by,
                error_code="unexpected_generation_failure",
            )
        raise

    expected_hash = hashlib.sha256(bytes(source.image)).hexdigest()
    if (result.plan.operation is not ImageOperation.REFERENCE_RENDER
            or result.plan.source_hash != expected_hash):
        run_id = persist_image_agent_result(
            db,
            result,
            project_root_id=project.root_id,
            source_asset_id=source.id,
            created_by=request.created_by,
            status_override="failed",
            commit=request.studio_job_id is None,
        )
        if request.studio_job_id is not None:
            fail_reserved_studio_visual_job(
                db,
                job_id=request.studio_job_id,
                owner=request.created_by,
                error_code="visual_preview_lineage_incomplete",
            )
        return JSONResponse(status_code=500, content={
            "code": "visual_preview_lineage_incomplete",
            "category": "internal",
            "detail": "the generated preview is not bound to the exact selected source",
            "image_run_id": run_id,
        })
    if not result.accepted and not result.review_required:
        run_id = persist_image_agent_result(
            db,
            result,
            project_root_id=project.root_id,
            source_asset_id=source.id,
            created_by=request.created_by,
            status_override="failed",
            commit=request.studio_job_id is None,
        )
        if request.studio_job_id is not None:
            fail_reserved_studio_visual_job(
                db,
                job_id=request.studio_job_id,
                owner=request.created_by,
                error_code="visual_preview_failed_quality",
            )
        return JSONResponse(status_code=422, content={
            "code": "visual_preview_failed_quality",
            "category": "quality",
            "detail": "the visual candidate failed quality checks and cannot be reviewed",
            "image_run_id": run_id,
            "qa": _visual_preview_qa(result),
        })

    run_id = persist_image_agent_result(
        db,
        result,
        project_root_id=project.root_id,
        source_asset_id=source.id,
        created_by=request.created_by,
        status_override=(
            "preview_ready" if result.accepted else "review_required"
        ),
        commit=False,
    )
    verdict: Literal["pass", "warn"] = (
        "pass" if result.accepted else "warn"
    )
    qa = _visual_preview_qa(result)
    try:
        candidate = store_studio_visual_candidate(
            db,
            run_id=run_id,
            verdict=verdict,
            project_root_id=project.root_id,
            source_asset_id=source.id,
            expected_selected_candidate_asset_id=source.id,
            source_hash=expected_hash,
            image_bytes=result.image_bytes,
            media_type=sniff_media_type(result.image_bytes),
            requested_change=request.instruction.strip(),
            scope=request.scope,
            qa=qa,
            created_by=request.created_by,
            studio_job_id=request.studio_job_id,
        )
    except StudioVisualCandidateUnavailable as exc:
        # Candidate binding/persistence failed after generation. Roll back the
        # unreviewable output, then preserve one failed run and settle the exact
        # reserved job in the same zero-charge transaction.
        db.rollback()
        failed_run_id = persist_image_agent_result(
            db,
            result,
            project_root_id=project.root_id,
            source_asset_id=source.id,
            created_by=request.created_by,
            status_override="failed",
            commit=request.studio_job_id is None,
        )
        if request.studio_job_id is not None:
            fail_reserved_studio_visual_job(
                db,
                job_id=request.studio_job_id,
                owner=request.created_by,
                error_code="visual_preview_candidate_unavailable",
            )
        return JSONResponse(status_code=409, content={
            "code": "visual_preview_candidate_unavailable",
            "category": "conflict",
            "detail": str(exc),
            "image_run_id": failed_run_id,
        })
    payload = {
        "project_id": project.root_id,
        "source_asset_id": source.id,
        "image_run_id": run_id,
        "candidate": {
            "candidate_id": candidate.candidate_id,
            "preview_url": (
                f"/studio/image-runs/{run_id}/visual-candidates/"
                f"{candidate.candidate_id}/image"
            ),
            "save_as_variation_url": (
                f"/studio/image-runs/{run_id}/visual-candidates/"
                f"{candidate.candidate_id}/save-as-variation"
            ),
            "verdict": verdict,
            "qa": qa,
        },
    }
    if verdict == "warn":
        return JSONResponse(status_code=202, content=payload)
    return payload


@router.get(
    "/image-runs/{run_id}/visual-candidates/{candidate_id}/image"
)
def get_visual_preview_image(
    run_id: str,
    candidate_id: str,
    db: DbSession,
    principal: PrincipalDep,
):
    run = db.get(ImageRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="visual preview unavailable")
    if not principal.local_unbound and run.created_by != principal.subject:
        raise HTTPException(status_code=404, detail="visual preview unavailable")
    try:
        candidate = get_studio_visual_candidate(
            db, run_id, candidate_id, owner=run.created_by,
        )
    except StudioVisualCandidateUnavailable as exc:
        return JSONResponse(status_code=410, content={
            "code": "visual_preview_unavailable",
            "category": "conflict",
            "detail": str(exc),
        })
    return Response(
        content=candidate.image_bytes,
        media_type=candidate.media_type,
        headers={"Cache-Control": "private, no-store"},
    )


@router.post(
    "/image-runs/{run_id}/visual-candidates/{candidate_id}/accept",
    status_code=201,
)
def accept_visual_preview(
    run_id: str,
    candidate_id: str,
    request: ReviewVisualPreviewRequest,
    db: DbSession,
    principal: PrincipalDep,
):
    principal_actor(principal, request.created_by)
    try:
        candidate = get_studio_visual_candidate(
            db, run_id, candidate_id, owner=request.created_by,
        )
        accepted = apply_pre_spec_visual_candidate(
            db,
            candidate=candidate,
            expected_active_asset_id=request.expected_active_asset_id,
            created_by=request.created_by,
            commit=False,
        )
        remove_studio_visual_candidate(
            db, run_id, candidate_id,
            owner=request.created_by,
            review_id=accepted.review_id,
            terminal_asset_id=accepted.asset_id,
            commit=False,
        )
        db.commit()
    except StudioVisualCandidateUnavailable as exc:
        invalidate_studio_visual_candidate(
            db,
            run_id,
            candidate_id,
            owner=request.created_by,
        )
        return JSONResponse(status_code=410, content={
            "code": "visual_preview_unavailable",
            "category": "conflict",
            "detail": str(exc),
        })
    except StudioHistoryError as exc:
        if exc.code in {
            "stale_asset_revision",
            "visual_preview_already_reviewed",
            "visual_preview_run_mismatch",
            "visual_preview_source_hash_mismatch",
            "visual_preview_unavailable",
        }:
            invalidate_studio_visual_candidate(
                db,
                run_id,
                candidate_id,
                owner=request.created_by,
                error_code=exc.code,
            )
        return _error(exc)
    project = db.get(Project, accepted.project_root_id)
    if project is None:  # pragma: no cover - transaction invariant
        raise HTTPException(status_code=500, detail="applied project unavailable")
    return {
        "status": "applied",
        "project_id": accepted.project_root_id,
        "source_asset_id": accepted.source_asset_id,
        "new_asset_id": accepted.asset_id,
        "design_version": None,
        "project": project_detail(db, project),
    }


@router.post(
    "/image-runs/{run_id}/visual-candidates/{candidate_id}/discard"
)
def discard_visual_preview(
    run_id: str,
    candidate_id: str,
    request: ReviewVisualPreviewRequest,
    db: DbSession,
    principal: PrincipalDep,
):
    principal_actor(principal, request.created_by)
    try:
        candidate = get_studio_visual_candidate(
            db, run_id, candidate_id, owner=request.created_by,
            require_active=False,
        )
        discarded = discard_pre_spec_visual_candidate(
            db,
            candidate=candidate,
            expected_active_asset_id=request.expected_active_asset_id,
            created_by=request.created_by,
            commit=False,
        )
        remove_studio_visual_candidate(
            db, run_id, candidate_id,
            owner=request.created_by,
            review_id=discarded.review_id,
            commit=False,
        )
        db.commit()
    except StudioVisualCandidateUnavailable as exc:
        return JSONResponse(status_code=410, content={
            "code": "visual_preview_unavailable",
            "category": "conflict",
            "detail": str(exc),
        })
    except StudioHistoryError as exc:
        return _error(exc)
    return {
        "status": "discarded",
        "project_id": discarded.project_root_id,
        "source_asset_id": discarded.source_asset_id,
        "candidate_id": candidate_id,
    }


@router.post(
    "/image-runs/{run_id}/visual-candidates/{candidate_id}/save-as-variation",
    status_code=201,
)
def save_visual_preview_as_variation(
    run_id: str,
    candidate_id: str,
    request: SavePreviewVariationRequest,
    db: DbSession,
    principal: PrincipalDep,
):
    principal_actor(principal, request.created_by)
    try:
        result = fork_preview_candidate_variation(
            db,
            kind="studio_visual",
            run_id=run_id,
            candidate_id=candidate_id,
            variation_label=request.label,
            created_by=request.created_by,
        )
    except StudioHistoryError as exc:
        return _error(exc)
    project = db.get(Project, result.project_root_id)
    if project is None:  # pragma: no cover
        raise HTTPException(status_code=500, detail="variation unavailable")
    return {
        "status": "saved_as_variation",
        "family_id": result.family_id,
        "variation_index": result.variation_index,
        "source_project_id": result.source_project_id,
        "source_asset_id": result.source_asset_id,
        "project": project_detail(db, project),
    }


@router.get("/projects/{project_root_id}/visual-candidates")
def reopen_visual_previews(
    project_root_id: str,
    db: DbSession,
    principal: PrincipalDep,
):
    project = db.get(Project, project_root_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project unavailable")
    if not principal.local_unbound and project.owner != principal.subject:
        raise HTTPException(status_code=404, detail="project unavailable")
    candidates = list_studio_visual_candidates(
        db, project_root_id=project_root_id, owner=project.owner,
    )
    return {"candidates": [{
        "candidate_id": candidate.candidate_id,
        "image_run_id": candidate.run_id,
        "source_asset_id": candidate.source_asset_id,
        "preview_url": (
            f"/studio/image-runs/{candidate.run_id}/visual-candidates/"
            f"{candidate.candidate_id}/image"
        ),
        "save_as_variation_url": (
            f"/studio/image-runs/{candidate.run_id}/visual-candidates/"
            f"{candidate.candidate_id}/save-as-variation"
        ),
        "verdict": candidate.verdict,
        "requested_change": candidate.requested_change,
        "scope": candidate.scope,
        "qa": candidate.qa,
        "expires_at": candidate.expires_at.isoformat(),
        "studio_job_id": candidate.studio_job_id,
    } for candidate in candidates]}


def _markup_candidate_error(
    exc: StudioMarkupError | StudioMarkupCandidateUnavailable,
) -> JSONResponse:
    status_code = getattr(exc, "status_code", 410)
    code = getattr(exc, "code", "markup_candidate_unavailable")
    detail = getattr(exc, "detail", str(exc))
    return JSONResponse(status_code=status_code, content={
        "code": code,
        "category": (
            "validation" if status_code == 422
            else "authorization" if status_code == 403
            else "conflict"
        ),
        "detail": detail,
    })


def _markup_candidate_payload(candidate) -> dict:
    base = (
        f"/studio/markup-candidates/{candidate.run_id}/"
        f"{candidate.candidate_id}"
    )
    return {
        "candidate_id": candidate.candidate_id,
        "image_run_id": candidate.run_id,
        "project_root_id": candidate.project_root_id,
        "source_asset_id": candidate.source_asset_id,
        "expected_active_asset_id": candidate.expected_active_asset_id,
        "design_version": candidate.design_version,
        "source_sha256": candidate.source_hash,
        "output_sha256": candidate.output_hash,
        "operation": candidate.operation,
        "requested_change": candidate.requested_change,
        "region_description": candidate.region_description,
        "qa": candidate.qa,
        "routing": candidate.routing,
        "status": candidate.status,
        "studio_job_id": candidate.studio_job_id,
        "expires_at": candidate.expires_at.isoformat(),
        "preview_url": f"{base}/image",
        "accept_url": f"{base}/accept",
        "discard_url": f"{base}/discard",
        "save_as_variation_url": f"{base}/save-as-variation",
    }


@router.get("/projects/{project_root_id}/markup-candidates")
def list_exact_markup_candidates(
    project_root_id: str,
    db: DbSession,
    principal: PrincipalDep,
):
    project = db.get(Project, project_root_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project unavailable")
    if not principal.local_unbound and project.owner != principal.subject:
        raise HTTPException(status_code=404, detail="project unavailable")
    candidates = list_studio_markup_candidates(
        db, owner=project.owner, project_root_id=project_root_id,
    )
    return {"candidates": [
        _markup_candidate_payload(candidate) for candidate in candidates
    ]}


@router.get("/markup-candidates/{run_id}/{candidate_id}/image")
def get_exact_markup_candidate_image(
    run_id: str,
    candidate_id: str,
    db: DbSession,
    principal: PrincipalDep,
):
    run = db.get(ImageRun, run_id)
    owner = (
        run.created_by if principal.local_unbound and run is not None
        else principal.subject
    )
    if owner is None:
        raise HTTPException(status_code=404, detail="markup candidate unavailable")
    try:
        candidate = get_studio_markup_candidate(
            db, run_id, candidate_id, owner=owner)
    except StudioMarkupCandidateUnavailable as exc:
        return _markup_candidate_error(exc)
    if candidate.status != "reviewing":
        return _markup_candidate_error(StudioMarkupCandidateUnavailable(
            f"the Studio markup candidate was already {candidate.status}"))
    return Response(
        content=candidate.image_bytes,
        media_type=candidate.media_type,
        headers={"Cache-Control": "private, no-store"},
    )


@router.post(
    "/markup-candidates/{run_id}/{candidate_id}/accept", status_code=201,
)
def accept_exact_markup_candidate(
    run_id: str,
    candidate_id: str,
    request: ReviewMarkupCandidateRequest,
    db: DbSession,
    principal: PrincipalDep,
):
    principal_actor(principal, request.created_by)
    try:
        candidate = get_studio_markup_candidate(
            db, run_id, candidate_id, owner=request.created_by)
        asset_id = accept_studio_markup_candidate(
            db,
            candidate,
            expected_active_asset_id=request.expected_active_asset_id,
            expected_design_version=request.expected_design_version,
            created_by=request.created_by,
        )
    except (StudioMarkupCandidateUnavailable, StudioMarkupError) as exc:
        return _markup_candidate_error(exc)
    except WarningRevisionError as exc:
        return _presentation_candidate_error(exc)
    project = db.get(Project, candidate.project_root_id)
    if project is None:  # pragma: no cover
        raise HTTPException(status_code=500, detail="accepted project unavailable")
    return {
        "status": "applied",
        "candidate_id": candidate_id,
        "asset_id": asset_id,
        "project": project_detail(db, project),
    }


@router.post("/markup-candidates/{run_id}/{candidate_id}/discard")
def discard_exact_markup_candidate(
    run_id: str,
    candidate_id: str,
    request: ReviewMarkupCandidateRequest,
    db: DbSession,
    principal: PrincipalDep,
):
    principal_actor(principal, request.created_by)
    try:
        candidate = get_studio_markup_candidate(
            db, run_id, candidate_id, owner=request.created_by)
        discard_studio_markup_candidate(
            db,
            candidate,
            expected_active_asset_id=request.expected_active_asset_id,
            expected_design_version=request.expected_design_version,
            created_by=request.created_by,
        )
    except (StudioMarkupCandidateUnavailable, StudioMarkupError) as exc:
        return _markup_candidate_error(exc)
    except WarningRevisionError as exc:
        return _presentation_candidate_error(exc)
    return {"status": "discarded", "candidate_id": candidate_id}


@router.post(
    "/markup-candidates/{run_id}/{candidate_id}/save-as-variation",
    status_code=201,
)
def save_exact_markup_candidate_as_variation(
    run_id: str,
    candidate_id: str,
    request: SavePreviewVariationRequest,
    db: DbSession,
    principal: PrincipalDep,
):
    principal_actor(principal, request.created_by)
    try:
        result = fork_preview_candidate_variation(
            db,
            kind="studio_markup",
            run_id=run_id,
            candidate_id=candidate_id,
            variation_label=request.label,
            created_by=request.created_by,
        )
    except StudioHistoryError as exc:
        return _error(exc)
    project = db.get(Project, result.project_root_id)
    if project is None:  # pragma: no cover
        raise HTTPException(status_code=500, detail="variation unavailable")
    return {
        "status": "saved_as_variation",
        "candidate_id": candidate_id,
        "family_id": result.family_id,
        "variation_index": result.variation_index,
        "source_project_id": result.source_project_id,
        "source_asset_id": result.source_asset_id,
        "project": project_detail(db, project),
    }


def _studio_preview_error(exc: StudioPreviewCandidateError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={
        "code": exc.code,
        "category": (
            "authorization" if exc.status_code == 403
            else "validation" if exc.status_code == 422
            else "conflict"
        ),
        "detail": exc.detail,
    })


def _studio_preview_owner(
    principal: AuthenticatedPrincipal,
    supplied_owner: str | None,
) -> str:
    """Resolve GET ownership without allowing query-label impersonation."""

    if principal.local_unbound:
        if supplied_owner is None:
            raise HTTPException(
                status_code=422,
                detail="owner is required when local authentication is unbound",
            )
        return supplied_owner
    assert principal.subject is not None
    if supplied_owner is not None:
        principal_actor(principal, supplied_owner)
    return principal.subject


def _studio_preview_payload(candidate: StudioPreviewCandidate) -> dict:
    base = f"/studio/preview-candidates/{candidate.candidate_id}"
    payload = {
        "candidate_id": candidate.candidate_id,
        "kind": candidate.kind,
        "status": candidate.status,
        "image_run_id": candidate.image_run_id,
        "project_root_id": candidate.project_root_id,
        "source_asset_id": candidate.source_asset_id,
        "expected_active_asset_id": candidate.expected_active_asset_id,
        "expected_design_version": candidate.expected_design_version,
        "source_sha256": candidate.source_sha256,
        "output_sha256": candidate.output_sha256,
        "requested_change": candidate.requested_change,
        "verdict": candidate.verdict,
        "qa": candidate.qa,
        "studio_job_id": candidate.studio_job_id,
        "terminal_asset_id": candidate.terminal_asset_id,
        "created_at": candidate.created_at,
        "expires_at": candidate.expires_at,
        "resolved_at": candidate.resolved_at,
        "available_decisions": candidate.available_decisions,
        "preview_url": (
            f"{base}/image?owner={quote(candidate.owner, safe='')}"
        ),
        "decision_url": f"{base}/decision",
        **candidate.detail,
    }
    return payload


@router.get(
    "/projects/{project_root_id}/preview-candidates",
    response_model=StudioPreviewCandidateListResponse,
)
def list_normalized_studio_preview_candidates(
    project_root_id: str,
    db: DbSession,
    principal: PrincipalDep,
    include_resolved: bool = Query(False),
):
    """List one project's temporary Refine outputs through one typed seam."""

    project = db.get(Project, project_root_id)
    if project is None or (
        not principal.local_unbound and project.owner != principal.subject
    ):
        raise HTTPException(status_code=404, detail="project unavailable")
    candidates = list_studio_preview_candidates(
        db,
        owner=project.owner,
        project_root_id=project_root_id,
        include_resolved=include_resolved,
    )
    return {"candidates": [
        _studio_preview_payload(candidate) for candidate in candidates
    ]}


@router.get(
    "/preview-candidates/{candidate_id}",
    response_model=StudioPreviewCandidateResponse,
)
def get_normalized_studio_preview_candidate(
    candidate_id: str,
    db: DbSession,
    principal: PrincipalDep,
    owner: Annotated[
        str | None, Query(min_length=1, max_length=32)
    ] = None,
):
    effective_owner = _studio_preview_owner(principal, owner)
    try:
        candidate = get_studio_preview_candidate(
            db, candidate_id, owner=effective_owner,
        )
    except StudioPreviewCandidateError as exc:
        return _studio_preview_error(exc)
    return _studio_preview_payload(candidate)


@router.get("/preview-candidates/{candidate_id}/image")
def get_normalized_studio_preview_candidate_image(
    candidate_id: str,
    db: DbSession,
    principal: PrincipalDep,
    owner: Annotated[
        str | None, Query(min_length=1, max_length=32)
    ] = None,
):
    effective_owner = _studio_preview_owner(principal, owner)
    try:
        image = get_studio_preview_image(
            db, candidate_id, owner=effective_owner,
        )
    except StudioPreviewCandidateError as exc:
        return _studio_preview_error(exc)
    return Response(
        content=image.image_bytes,
        media_type=image.media_type,
        headers={"Cache-Control": "private, no-store"},
    )


@router.post(
    "/preview-candidates/{candidate_id}/decision",
    response_model=StudioPreviewCandidateDecisionResponse,
)
def decide_normalized_studio_preview_candidate(
    candidate_id: str,
    request: DecideStudioPreviewCandidateRequest,
    db: DbSession,
    principal: PrincipalDep,
):
    actor = principal_actor(principal, request.created_by)
    try:
        result = decide_studio_preview_candidate(
            db,
            candidate_id,
            owner=actor,
            decision=request.decision,
            expected_active_asset_id=request.expected_active_asset_id,
            expected_design_version=request.expected_design_version,
            variation_label=request.variation_label,
        )
    except StudioPreviewCandidateError as exc:
        return _studio_preview_error(exc)
    return {
        "status": result.status,
        "candidate_id": result.candidate_id,
        "kind": result.kind,
        "source_project_id": result.source_project_id,
        "result_project_id": result.result_project_id,
        "terminal_asset_id": result.terminal_asset_id,
        "studio_job_id": result.studio_job_id,
        "family_id": result.family_id,
        "variation_index": result.variation_index,
    }


def _pre_spec_presentation_error(
    exc: StudioPresentationError,
) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={
        "code": exc.code,
        "category": (
            "stale_version" if exc.code.startswith("stale_")
            else "validation" if exc.status_code == 422
            else "conflict"
        ),
        "detail": exc.detail,
    })


@router.post(
    "/projects/{project_id}/presentation-previews",
    status_code=201,
)
def create_pre_spec_presentation_preview(
    project_id: str,
    request: CreatePreSpecPresentationRequest,
    db: DbSession,
    generate: PreSpecPresentationGeneratorDep,
):
    """Create a temporary Client or Marketing image from one exact visual.

    This route is intentionally separate from spec-aligned product photography.
    Even a QA-passing output remains temporary until the designer saves it.
    """

    try:
        project, source = _selected_pre_spec_visual(
            db,
            project_root_id=project_id,
            expected_active_asset_id=request.expected_active_asset_id,
            created_by=request.created_by,
        )
        brief = compile_product_photo_brief(
            request.preset,
            request.framing,
            request.custom_instruction,
        )
    except StudioHistoryError as exc:
        return _error(exc)
    except PresentationScopeError as exc:
        return JSONResponse(status_code=422, content={
            "code": "presentation_scope_violation",
            "category": "validation",
            "detail": str(exc),
        })

    client_beauty = (
        request.destination == "client" and request.client_format == "beauty"
    )
    intent = brief.intent
    if client_beauty:
        intent = (
            "Create one polished client-review beauty image with restrained, "
            "high-jewelry art direction. " + intent
        )
    expected_output = (
        "one polished client-review image of the exact selected visual; "
        "presentation changed, jewelry unchanged, no manufacturing authority"
        if request.destination == "client" else
        "one polished marketing image of the exact selected visual; "
        "presentation changed, jewelry unchanged, no manufacturing authority"
    )
    try:
        reserve_studio_presentation_job(
            db,
            job_id=request.studio_job_id,
            owner=request.created_by,
            project_root_id=project.root_id,
            source_asset_id=source.id,
        )
    except StudioPresentationError as exc:
        return _pre_spec_presentation_error(exc)
    try:
        result = generate(
            bytes(source.image),
            intent,
            brief.style_constraints,
            expected_output,
            request.variant,
        )
    except ImageAgentError as exc:
        run_id = (
            persist_image_agent_failure(
                db, exc.plan, exc,
                project_root_id=project.root_id,
                source_asset_id=source.id,
                created_by=request.created_by,
            ) if exc.plan is not None else None
        )
        fail_reserved_studio_presentation_job(
            db,
            job_id=request.studio_job_id,
            owner=request.created_by,
            error_code=exc.code,
        )
        return image_agent_error_response(exc, image_run_id=run_id)
    except Exception:
        fail_reserved_studio_presentation_job(
            db,
            job_id=request.studio_job_id,
            owner=request.created_by,
            error_code="unexpected_generation_failure",
        )
        raise

    source_hash = hashlib.sha256(bytes(source.image)).hexdigest()
    if (result.plan.operation is not ImageOperation.REFERENCE_RENDER
            or result.plan.source_hash != source_hash
            or result.plan.source_spec_visual_hash is not None):
        run_id = persist_image_agent_result(
            db,
            result,
            project_root_id=project.root_id,
            source_asset_id=source.id,
            created_by=request.created_by,
            status_override="failed",
        )
        fail_reserved_studio_presentation_job(
            db,
            job_id=request.studio_job_id,
            owner=request.created_by,
            error_code="presentation_lineage_incomplete",
        )
        return JSONResponse(status_code=500, content={
            "code": "presentation_lineage_incomplete",
            "category": "internal",
            "detail": "the preview is not bound to the exact pre-spec source",
            "image_run_id": run_id,
        })
    if not result.accepted and not result.review_required:
        run_id = persist_image_agent_result(
            db, result,
            project_root_id=project.root_id,
            source_asset_id=source.id,
            created_by=request.created_by,
        )
        fail_reserved_studio_presentation_job(
            db,
            job_id=request.studio_job_id,
            owner=request.created_by,
            error_code="presentation_failed_quality",
        )
        return JSONResponse(status_code=422, content={
            "code": "presentation_failed_quality",
            "category": "quality",
            "detail": "the result did not preserve the selected design closely enough",
            "image_run_id": run_id,
            "qa": _visual_preview_qa(result),
        })

    run_id = persist_image_agent_result(
        db, result,
        project_root_id=project.root_id,
        source_asset_id=source.id,
        created_by=request.created_by,
        status_override=(
            "preview_ready" if result.accepted else "review_required"
        ),
    )
    capability = (
        "CLIENT_BEAUTY_RENDER" if client_beauty else
        "CLIENT_PRODUCT_PHOTO" if request.destination == "client" else
        "MARKETING_IMAGE"
    )
    qa = _visual_preview_qa(result)
    try:
        candidate = store_studio_presentation_candidate(
            db,
            run_id=run_id,
            project_root_id=project.root_id,
            source_asset_id=source.id,
            source_hash=source_hash,
            image_bytes=result.image_bytes,
            media_type=sniff_media_type(result.image_bytes),
            destination=request.destination,
            capability=capability,
            requested_change=intent,
            preset=request.preset,
            framing=request.framing,
            qa=qa,
            created_by=request.created_by,
            studio_job_id=request.studio_job_id,
        )
    except StudioPresentationError as exc:
        fail_reserved_studio_presentation_job(
            db,
            job_id=request.studio_job_id,
            owner=request.created_by,
            error_code=exc.code,
        )
        return _pre_spec_presentation_error(exc)
    return {
        "status": "review_required",
        "project_id": project.root_id,
        "source_asset_id": source.id,
        "source_sha256": source_hash,
        "design_version": None,
        "destination": request.destination,
        "client_format": request.client_format,
        "candidate": {
            "candidate_id": candidate.candidate_id,
            "image_run_id": run_id,
            "preview_url": (
                f"/studio/image-runs/{run_id}/presentation-candidates/"
                f"{candidate.candidate_id}/image?owner={request.created_by}"
            ),
            "studio_job_id": candidate.studio_job_id,
            "capability": capability,
            "preset": request.preset,
            "framing": request.framing,
            "qa": qa,
        },
    }


def _view_candidate_error(exc: StudioViewError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={
        "code": exc.code,
        "category": (
            "stale_version" if exc.code.startswith("stale_")
            else "validation" if exc.status_code == 422
            else "authorization" if exc.status_code == 403
            else "conflict"
        ),
        "detail": exc.detail,
    })


@router.get("/view-candidates")
def list_exact_view_candidates(
    db: DbSession,
    owner: Annotated[str, Query(min_length=1, max_length=32)],
    principal: PrincipalDep,
    project_id: Annotated[str, Query(min_length=1, max_length=32)] | None = None,
    status: Literal[
        "reviewing", "accepted", "discarded", "expired",
    ] | None = "reviewing",
):
    principal_actor(principal, owner)
    candidates = list_studio_view_candidates(
        db, owner=owner, project_root_id=project_id, status=status)
    return {"candidates": [{
        "candidate_id": item.candidate_id,
        "image_run_id": item.run_id,
        "studio_job_id": item.studio_job_id,
        "project_id": item.project_root_id,
        "source_asset_id": item.source_asset_id,
        "source_sha256": item.source_hash,
        "design_version": item.design_version,
        "view": item.view,
        "qa": item.qa,
        "status": item.status,
        "accepted_asset_id": item.accepted_asset_id,
        "expires_at": item.expires_at.isoformat(),
        "preview_url": (
            f"/studio/view-candidates/{item.run_id}/"
            f"{item.candidate_id}/image?owner={owner}"
        ),
    } for item in candidates]}


@router.get("/view-candidates/{run_id}/{candidate_id}/image")
def get_exact_view_candidate_image(
    run_id: str,
    candidate_id: str,
    db: DbSession,
    owner: Annotated[str, Query(min_length=1, max_length=32)],
    principal: PrincipalDep,
):
    principal_actor(principal, owner)
    try:
        candidate = get_studio_view_candidate(
            db, run_id, candidate_id, owner=owner)
    except StudioViewCandidateUnavailable as exc:
        return JSONResponse(status_code=exc.status_code, content={
            "code": "view_candidate_unavailable",
            "category": "conflict",
            "detail": str(exc),
        })
    if candidate.status != "reviewing":
        return JSONResponse(status_code=410, content={
            "code": "view_candidate_unavailable",
            "category": "conflict",
            "detail": f"the Studio View was already {candidate.status}",
        })
    return Response(
        content=candidate.image_bytes,
        media_type=candidate.media_type,
        headers={"Cache-Control": "private, no-store"},
    )


@router.post(
    "/view-candidates/{run_id}/{candidate_id}/accept", status_code=201,
)
def accept_exact_view_candidate(
    run_id: str,
    candidate_id: str,
    request: ResolveViewCandidateRequest,
    db: DbSession,
    principal: PrincipalDep,
):
    principal_actor(principal, request.created_by)
    try:
        candidate = get_studio_view_candidate(
            db, run_id, candidate_id, owner=request.created_by)
        asset_id = accept_studio_view_candidate(
            db,
            candidate,
            expected_project_id=request.expected_project_id,
            expected_source_asset_id=request.expected_source_asset_id,
            expected_design_version=request.expected_design_version,
            created_by=request.created_by,
        )
    except StudioViewCandidateUnavailable as exc:
        return JSONResponse(status_code=exc.status_code, content={
            "code": "view_candidate_unavailable",
            "category": "conflict",
            "detail": str(exc),
        })
    except StudioViewError as exc:
        return _view_candidate_error(exc)
    project = db.get(Project, candidate.project_root_id)
    if project is None:  # pragma: no cover - transaction invariant
        raise HTTPException(status_code=500, detail="saved Studio View unavailable")
    return {
        "status": "accepted",
        "project_id": candidate.project_root_id,
        "source_asset_id": candidate.source_asset_id,
        "design_version": candidate.design_version,
        "asset_id": asset_id,
        "project": project_detail(db, project),
    }


@router.post("/view-candidates/{run_id}/{candidate_id}/discard")
def discard_exact_view_candidate(
    run_id: str,
    candidate_id: str,
    request: ResolveViewCandidateRequest,
    db: DbSession,
    principal: PrincipalDep,
):
    principal_actor(principal, request.created_by)
    try:
        candidate = get_studio_view_candidate(
            db, run_id, candidate_id, owner=request.created_by)
        discard_studio_view_candidate(
            db,
            candidate,
            expected_project_id=request.expected_project_id,
            expected_source_asset_id=request.expected_source_asset_id,
            expected_design_version=request.expected_design_version,
            created_by=request.created_by,
        )
    except StudioViewCandidateUnavailable as exc:
        return JSONResponse(status_code=exc.status_code, content={
            "code": "view_candidate_unavailable",
            "category": "conflict",
            "detail": str(exc),
        })
    except StudioViewError as exc:
        return _view_candidate_error(exc)
    return {
        "status": "discarded",
        "project_id": candidate.project_root_id,
        "source_asset_id": candidate.source_asset_id,
        "design_version": candidate.design_version,
        "candidate_id": candidate_id,
    }


@router.get("/presentation-candidates")
def list_pre_spec_presentation_candidates(
    db: DbSession,
    owner: Annotated[str, Query(min_length=1, max_length=32)],
    principal: PrincipalDep,
    project_id: Annotated[str, Query(min_length=1, max_length=32)] | None = None,
    status: Literal[
        "reviewing", "accepted", "discarded", "expired",
    ] | None = "reviewing",
):
    """Resume durable presentation reviews after refresh or process restart."""

    principal_actor(principal, owner)
    candidates = list_studio_presentation_candidates(
        db,
        owner=owner,
        project_root_id=project_id,
        status=status,
    )
    return {"candidates": [{
        "candidate_id": item.candidate_id,
        "image_run_id": item.run_id,
        "project_id": item.project_root_id,
        "source_asset_id": item.source_asset_id,
        "source_sha256": item.source_hash,
        "design_version": item.design_version,
        "destination": item.destination,
        "capability": item.capability,
        "preset": item.preset,
        "framing": item.framing,
        "qa": item.qa,
        "status": item.status,
        "studio_job_id": item.studio_job_id,
        "accepted_asset_id": item.accepted_asset_id,
        "expires_at": item.expires_at.isoformat(),
        "preview_url": (
            f"/studio/image-runs/{item.run_id}/presentation-candidates/"
            f"{item.candidate_id}/image?owner={owner}"
        ),
    } for item in candidates]}


@router.get(
    "/image-runs/{run_id}/presentation-candidates/{candidate_id}/image"
)
def get_pre_spec_presentation_image(
    run_id: str,
    candidate_id: str,
    db: DbSession,
    owner: Annotated[str, Query(min_length=1, max_length=32)],
    principal: PrincipalDep,
):
    principal_actor(principal, owner)
    try:
        candidate = get_studio_presentation_candidate(
            db, run_id, candidate_id, owner=owner)
    except StudioPresentationCandidateUnavailable as exc:
        return JSONResponse(status_code=exc.status_code, content={
            "code": "presentation_candidate_unavailable",
            "category": "conflict",
            "detail": str(exc),
        })
    if candidate.status != "reviewing":
        return JSONResponse(status_code=410, content={
            "code": "presentation_candidate_unavailable",
            "category": "conflict",
            "detail": f"the presentation preview was already {candidate.status}",
        })
    return Response(
        content=candidate.image_bytes,
        media_type=candidate.media_type,
        headers={"Cache-Control": "private, no-store"},
    )


@router.post(
    "/image-runs/{run_id}/presentation-candidates/{candidate_id}/accept",
    status_code=201,
)
def accept_pre_spec_presentation(
    run_id: str,
    candidate_id: str,
    request: ReviewPreSpecPresentationRequest,
    db: DbSession,
    principal: PrincipalDep,
):
    principal_actor(principal, request.created_by)
    try:
        candidate = get_studio_presentation_candidate(
            db, run_id, candidate_id, owner=request.created_by)
        accepted = accept_studio_presentation_candidate(
            db, candidate,
            expected_active_asset_id=request.expected_active_asset_id,
            expected_source_sha256=request.expected_source_sha256,
            created_by=request.created_by,
        )
    except StudioPresentationCandidateUnavailable as exc:
        return JSONResponse(status_code=exc.status_code, content={
            "code": "presentation_candidate_unavailable",
            "category": "conflict",
            "detail": str(exc),
        })
    except StudioPresentationError as exc:
        return _pre_spec_presentation_error(exc)
    project = db.get(Project, accepted.project_root_id)
    if project is None:  # pragma: no cover - transaction invariant
        raise HTTPException(status_code=500, detail="saved presentation unavailable")
    return {
        "status": "accepted",
        "project_id": accepted.project_root_id,
        "source_asset_id": accepted.source_asset_id,
        "source_sha256": accepted.source_hash,
        "design_version": None,
        "asset_id": accepted.asset_id,
        "capability": accepted.capability,
        "project": project_detail(db, project),
    }


@router.post(
    "/image-runs/{run_id}/presentation-candidates/{candidate_id}/discard"
)
def discard_pre_spec_presentation(
    run_id: str,
    candidate_id: str,
    request: ReviewPreSpecPresentationRequest,
    db: DbSession,
    principal: PrincipalDep,
):
    principal_actor(principal, request.created_by)
    try:
        candidate = get_studio_presentation_candidate(
            db, run_id, candidate_id, owner=request.created_by)
        discard_studio_presentation_candidate(
            db, candidate,
            expected_active_asset_id=request.expected_active_asset_id,
            expected_source_sha256=request.expected_source_sha256,
            created_by=request.created_by,
        )
    except StudioPresentationCandidateUnavailable as exc:
        return JSONResponse(status_code=exc.status_code, content={
            "code": "presentation_candidate_unavailable",
            "category": "conflict",
            "detail": str(exc),
        })
    except StudioPresentationError as exc:
        return _pre_spec_presentation_error(exc)
    return {
        "status": "discarded",
        "project_id": candidate.project_root_id,
        "source_asset_id": candidate.source_asset_id,
        "source_sha256": candidate.source_hash,
        "design_version": None,
        "candidate_id": candidate_id,
    }


def _presentation_candidate_error(exc: WarningRevisionError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={
        "code": exc.code,
        "category": (
            "stale_version" if exc.code.startswith("stale_")
            else "validation" if exc.status_code == 422
            else "authorization" if exc.status_code == 403
            else "conflict"
        ),
        "detail": exc.detail,
    })


def _require_presentation_candidate_lineage(
    candidate: MarkupWarningCandidate,
    request: ResolvePresentationCandidateRequest,
) -> None:
    if candidate.promotion_kind != "presentation_only":
        raise WarningRevisionError(
            "presentation_candidate_invalid",
            "this candidate is not a presentation-only output",
            status_code=422,
        )
    if candidate.created_by != request.created_by:
        raise WarningRevisionError(
            "presentation_candidate_owner_mismatch",
            "only the candidate creator may resolve this presentation",
            status_code=403,
        )
    if candidate.project_root_id != request.expected_project_id:
        raise WarningRevisionError(
            "presentation_project_mismatch",
            "the candidate does not belong to the expected project",
        )
    if candidate.source_asset_id != request.expected_source_asset_id:
        raise WarningRevisionError(
            "presentation_source_mismatch",
            "the candidate does not belong to the expected source revision",
        )
    if candidate.expected_design_version != request.expected_design_version:
        raise WarningRevisionError(
            "stale_design_version",
            "the candidate belongs to a different design version",
        )


@router.post(
    "/presentation-candidates/{run_id}/{candidate_id}/accept",
    status_code=201,
)
def accept_presentation_candidate(
    run_id: str,
    candidate_id: str,
    request: ResolvePresentationCandidateRequest,
    db: DbSession,
    principal: PrincipalDep,
):
    """Save a reviewed deliverable without changing canonical design state."""

    principal_actor(principal, request.created_by)
    durable = None
    try:
        durable = get_studio_presentation_candidate(
            db, run_id, candidate_id, owner=request.created_by)
    except StudioPresentationCandidateUnavailable:
        pass
    if durable is not None:
        if (
            durable.design_version != request.expected_design_version
            or durable.project_root_id != request.expected_project_id
            or durable.source_asset_id != request.expected_source_asset_id
        ):
            return _presentation_candidate_error(WarningRevisionError(
                "stale_design_version",
                "the durable presentation belongs to a different exact revision",
            ))
        try:
            accepted = accept_studio_presentation_candidate(
                db,
                durable,
                expected_active_asset_id=(
                    durable.expected_active_asset_id
                    or request.expected_source_asset_id
                ),
                expected_source_sha256=durable.source_hash,
                created_by=request.created_by,
            )
        except StudioPresentationError as exc:
            return _pre_spec_presentation_error(exc)
        asset = db.get(ImageAsset, accepted.asset_id)
        project = db.get(Project, durable.project_root_id)
        if asset is None or project is None:  # pragma: no cover
            raise HTTPException(
                status_code=500, detail="saved presentation unavailable")
        return {
            "status": "accepted",
            "project_id": project.root_id,
            "source_asset_id": durable.source_asset_id,
            "source_design_version": durable.design_version,
            "asset_id": asset.id,
            "capability": asset.capability,
            "project": project_detail(db, project),
        }

    try:
        candidate = get_markup_warning_candidate(run_id, candidate_id)
        _require_presentation_candidate_lineage(candidate, request)
        accepted = accept_warning_revision(
            db,
            candidate,
            expected_design_version=request.expected_design_version,
            created_by=request.created_by,
        )
    except WarningCandidateUnavailable as exc:
        return JSONResponse(status_code=410, content={
            "code": "presentation_candidate_unavailable",
            "category": "conflict",
            "detail": str(exc),
        })
    except WarningRevisionError as exc:
        return _presentation_candidate_error(exc)
    asset = db.get(ImageAsset, accepted.asset_id)
    project = db.get(Project, candidate.project_root_id)
    if asset is None or project is None:  # pragma: no cover - transaction invariant
        raise HTTPException(status_code=500, detail="saved presentation unavailable")
    return {
        "status": "accepted",
        "project_id": project.root_id,
        "source_asset_id": candidate.source_asset_id,
        "source_design_version": candidate.expected_design_version,
        "asset_id": asset.id,
        "capability": asset.capability,
        "project": project_detail(db, project),
    }


@router.post(
    "/presentation-candidates/{run_id}/{candidate_id}/discard",
)
def discard_presentation_candidate(
    run_id: str,
    candidate_id: str,
    request: ResolvePresentationCandidateRequest,
    db: DbSession,
    principal: PrincipalDep,
):
    """Persist a terminal rejection without creating a presentation asset."""

    principal_actor(principal, request.created_by)
    durable = None
    try:
        durable = get_studio_presentation_candidate(
            db, run_id, candidate_id, owner=request.created_by)
    except StudioPresentationCandidateUnavailable:
        pass
    if durable is not None:
        if (
            durable.design_version != request.expected_design_version
            or durable.project_root_id != request.expected_project_id
            or durable.source_asset_id != request.expected_source_asset_id
        ):
            return _presentation_candidate_error(WarningRevisionError(
                "stale_design_version",
                "the durable presentation belongs to a different exact revision",
            ))
        try:
            discard_studio_presentation_candidate(
                db,
                durable,
                expected_active_asset_id=(
                    durable.expected_active_asset_id
                    or request.expected_source_asset_id
                ),
                expected_source_sha256=durable.source_hash,
                created_by=request.created_by,
            )
        except StudioPresentationError as exc:
            return _pre_spec_presentation_error(exc)
        return {
            "status": "discarded",
            "project_id": durable.project_root_id,
            "source_asset_id": durable.source_asset_id,
            "source_design_version": durable.design_version,
            "candidate_id": candidate_id,
        }

    try:
        candidate = get_markup_warning_candidate(run_id, candidate_id)
        _require_presentation_candidate_lineage(candidate, request)
        discarded = discard_warning_revision(
            db,
            candidate,
            expected_design_version=request.expected_design_version,
            created_by=request.created_by,
        )
        discard_markup_warning_candidate(
            run_id, candidate_id, created_by=request.created_by,
        )
    except WarningCandidateUnavailable as exc:
        return JSONResponse(status_code=410, content={
            "code": "presentation_candidate_unavailable",
            "category": "conflict",
            "detail": str(exc),
        })
    except WarningRevisionError as exc:
        return _presentation_candidate_error(exc)
    return {
        "status": "discarded",
        "project_id": discarded.project_root_id,
        "source_asset_id": discarded.source_asset_id,
        "source_design_version": discarded.design_version,
        "candidate_id": candidate_id,
    }


def _error(exc: StudioHistoryError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={
        "code": exc.code,
        "category": (
            "stale_version" if exc.code.startswith("stale_")
            else "validation" if exc.status_code == 422
            else "conflict"
        ),
        "detail": exc.detail,
    })


@router.post("/projects/{project_root_id}/variations", status_code=201)
def save_as_variation(
    project_root_id: str,
    request: SaveCurrentVariationRequest,
    db: DbSession,
    principal: PrincipalDep,
):
    actor = principal_actor(principal, request.created_by)
    try:
        result = fork_project_variation(
            db,
            project_root_id=project_root_id,
            source_asset_id=request.expected_active_asset_id,
            expected_active_asset_id=request.expected_active_asset_id,
            expected_design_version=request.expected_design_version,
            variation_label=request.label,
            created_by=actor,
            operation_id=request.operation_id,
        )
    except StudioHistoryError as exc:
        return _error(exc)
    project = db.get(Project, result.project_root_id)
    if project is None:  # pragma: no cover - transaction invariant
        raise HTTPException(status_code=500, detail="variation project not found")
    return {
        "status": "variation_created",
        "family_id": result.family_id,
        "variation_index": result.variation_index,
        "source_project_id": project.branched_from_project_root_id,
        "source_asset_id": project.branched_from_asset_id,
        "project": project_detail(db, project),
    }


@router.post(
    "/projects/{project_root_id}/creative-candidates/{candidate_id}/variations",
    status_code=201,
)
def save_creative_candidate_as_variation(
    project_root_id: str,
    candidate_id: str,
    request: SaveCreativeVariationRequest,
    db: DbSession,
    principal: PrincipalDep,
):
    """Keep an unselected Create direction as a named sibling Variation."""

    actor = principal_actor(principal, request.created_by)
    try:
        result = fork_project_variation(
            db,
            project_root_id=project_root_id,
            source_asset_id=candidate_id,
            expected_active_asset_id=request.expected_active_asset_id,
            expected_design_version=request.expected_design_version,
            variation_label=request.label,
            created_by=actor,
            operation_id=request.operation_id,
            allow_unselected_creative_candidate=True,
        )
    except StudioHistoryError as exc:
        return _error(exc)
    project = db.get(Project, result.project_root_id)
    if project is None:  # pragma: no cover - transaction invariant
        raise HTTPException(status_code=500, detail="variation project not found")
    return {
        "status": "variation_created",
        "family_id": result.family_id,
        "variation_index": result.variation_index,
        "source_project_id": project.branched_from_project_root_id,
        "source_asset_id": project.branched_from_asset_id,
        "project": project_detail(db, project),
    }


@router.post(
    "/projects/{project_root_id}/revisions/{asset_id}/variations",
    status_code=201,
    response_model=RevisionVariationResponse,
)
def save_revision_as_variation(
    project_root_id: str,
    asset_id: str,
    request: SaveRevisionVariationRequest,
    db: DbSession,
    principal: PrincipalDep,
):
    """Branch any exact saved Revision without restoring or mutating it."""

    actor = principal_actor(principal, request.created_by)
    try:
        result = fork_project_revision_variation(
            db,
            project_root_id=project_root_id,
            source_asset_id=asset_id,
            expected_source_design_version=request.expected_source_design_version,
            expected_source_sha256=request.expected_source_sha256,
            expected_active_asset_id=request.expected_active_asset_id,
            expected_active_design_version=(
                request.expected_active_design_version
            ),
            variation_label=request.label,
            created_by=actor,
            operation_id=request.operation_id,
        )
    except StudioHistoryError as exc:
        return _error(exc)
    project = db.get(Project, result.project_root_id)
    if (
        project is None
        or result.source_sha256 is None
        or result.guarded_active_asset_id is None
        or result.output_sha256 is None
    ):  # pragma: no cover - transaction invariant
        raise HTTPException(status_code=500, detail="variation project not found")
    member = {
        "project_root_id": result.project_root_id,
        "asset_id": result.asset_id,
        "design_id": result.design_id,
        "design_version": result.design_version,
        "family_id": result.family_id,
        "variation_index": result.variation_index,
        "branched_from_project_root_id": result.source_project_id,
        "branched_from_asset_id": result.source_asset_id,
        "component_map_status": result.component_map_status,
        "component_map_sha256": result.component_map_sha256,
    }
    return {
        "status": "variation_created",
        "family_id": result.family_id,
        "variation_index": result.variation_index,
        "source_project_id": result.source_project_id,
        "source_asset_id": result.source_asset_id,
        "source_design_version": result.source_design_version,
        "source_sha256": result.source_sha256,
        "guarded_active_asset_id": result.guarded_active_asset_id,
        "guarded_active_design_version": (
            result.guarded_active_design_version
        ),
        "child_project_root_id": result.project_root_id,
        "child_asset_id": result.asset_id,
        "child_design_id": result.design_id,
        "child_design_version": result.design_version,
        "child_sha256": result.output_sha256,
        "child_family_id": result.family_id,
        "child_variation_index": result.variation_index,
        "child_branched_from_project_root_id": result.source_project_id,
        "child_branched_from_asset_id": result.source_asset_id,
        "component_map_status": result.component_map_status,
        "component_map_sha256": result.component_map_sha256,
        "variation": member,
        "project": project_detail(db, project),
    }


@router.post(
    "/projects/{project_root_id}/revisions/{asset_id}/restore",
    status_code=201,
)
def restore_revision(
    project_root_id: str,
    asset_id: str,
    request: RestoreRevisionRequest,
    db: DbSession,
):
    try:
        result = restore_project_revision(
            db,
            project_root_id=project_root_id,
            restore_asset_id=asset_id,
            expected_active_asset_id=request.expected_active_asset_id,
            expected_design_version=request.expected_design_version,
            created_by=request.created_by,
        )
    except StudioHistoryError as exc:
        return _error(exc)
    project = db.get(Project, project_root_id)
    if project is None:  # pragma: no cover - transaction invariant
        raise HTTPException(status_code=500, detail="restored project not found")
    return {
        "status": "restored_as_new_revision",
        "restored_from_asset_id": result.restored_from_asset_id,
        "new_asset_id": result.asset_id,
        "new_design_version": result.design_version,
        "spec_change": list(result.spec_change),
        "project": project_detail(db, project),
    }


@router.get("/projects/{project_root_id}/history")
def studio_history(project_root_id: str, db: DbSession):
    project = db.get(Project, project_root_id)
    if project is None:
        raise HTTPException(status_code=404,
                            detail=f"unknown project '{project_root_id}'")
    chain = list(db.scalars(
        select(ImageAsset)
        .where(ImageAsset.root_id == project_root_id)
        .order_by(ImageAsset.created_at, ImageAsset.id)
    ))
    chain.sort(key=lambda asset: (
        asset.id != project_root_id, asset.created_at, asset.id,
    ))
    primary = [asset for asset in chain if is_canonical_revision(asset)]
    selected_candidate = accepted_creative_candidate(
        chain, project.selected_candidate_asset_id,
    )
    if selected_candidate is not None:
        primary.insert(0, selected_candidate)
    active = primary[-1] if primary else None
    if (project.selected_candidate_asset_id is not None
            and not any(asset.design_version is not None for asset in primary)):
        selected = next((
            asset for asset in primary
            if asset.id == project.selected_candidate_asset_id
            and asset.design_version is None
        ), None)
        if selected is not None:
            active = selected
    records = {
        record.asset_id: record for record in db.scalars(
            select(ProjectRevisionRecord)
            .where(ProjectRevisionRecord.asset_id.in_(
                [asset.id for asset in primary]
            ))
        )
    } if primary else {}
    return {
        "project_id": project_root_id,
        "family_id": project.family_id,
        # Imported and pre-family projects predate Studio's variation
        # metadata. Keep those historical records readable without mutating
        # them from a GET; their root is the compatibility "Original".
        "variation_index": project.variation_index or 1,
        "variation_label": project.variation_label,
        "active_asset_id": active.id if active is not None else None,
        "revisions": [{
            "revision": index,
            "asset_id": asset.id,
            "parent_asset_id": asset.parent_asset_id,
            "design_version": asset.design_version,
            "capability": asset.capability,
            "sha256": hashlib.sha256(bytes(asset.image)).hexdigest(),
            "image_url": f"/assets/{asset.id}/image",
            "pinned": asset.pinned_at is not None,
            "action": (
                records[asset.id].action if asset.id in records
                else "created" if index == 1 else "edit"
            ),
            "raw_intent": (
                records[asset.id].raw_intent if asset.id in records else {
                    "kind": "legacy_or_pre_studio",
                    "instruction": asset.instruction,
                }
            ),
            "interpretation": (
                records[asset.id].interpretation if asset.id in records else {}
            ),
            "change_summary": (
                records[asset.id].change_summary if asset.id in records
                else asset.instruction or (
                    "Initial variation" if index == 1 else "Applied design edit"
                )
            ),
            "restored_from_asset_id": (
                records[asset.id].restored_from_asset_id
                if asset.id in records else None
            ),
            "created_by": asset.created_by,
            "created_at": asset.created_at.isoformat(),
        } for index, asset in enumerate(primary, start=1)],
    }


def _design_family_detail(db: Session, family: DesignFamily) -> dict:
    projects = list(db.scalars(
        select(Project)
        .where(Project.family_id == family.id)
        .order_by(Project.variation_index, Project.created_at)
    ))
    return {
        "family_id": family.id,
        "owner": family.owner,
        "title": family.title,
        "created_at": family.created_at.isoformat(),
        "updated_at": family.updated_at.isoformat(),
        "variations": [{
            **project_card(db, project),
            "variation_index": project.variation_index,
            "variation_label": project.variation_label,
            "branched_from_project_root_id": (
                project.branched_from_project_root_id
            ),
            "branched_from_asset_id": project.branched_from_asset_id,
        } for project in projects],
    }


@router.get("/families")
def list_design_families(
    db: DbSession,
    principal: PrincipalDep,
    owner: str | None = None,
):
    """List Studio families without flattening their variation boundaries."""

    if owner is not None:
        principal_actor(principal, owner)
    effective_owner = owner if principal.local_unbound else principal.subject
    query = select(DesignFamily)
    if effective_owner is not None:
        query = query.where(DesignFamily.owner == effective_owner)
    families = list(db.scalars(
        query.order_by(DesignFamily.updated_at.desc(), DesignFamily.id)
    ))
    return {
        "families": [_design_family_detail(db, family) for family in families],
    }


@router.get("/families/{family_id}")
def get_design_family(
    family_id: str,
    db: DbSession,
    principal: PrincipalDep,
):
    family = db.get(DesignFamily, family_id)
    if (
        family is None
        or (
            not principal.local_unbound
            and family.owner != principal.subject
        )
    ):
        raise HTTPException(status_code=404,
                            detail=f"unknown design family '{family_id}'")
    return _design_family_detail(db, family)

"""AI-first Studio branching, immutable history, and restoration APIs."""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import re
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from PIL import Image
from sqlalchemy import func, select
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
    PreviewCandidateRecord,
    Project,
    ProjectRevisionRecord,
    StudioCreateDecisionRecord,
    StudioJobRecord,
    get_db,
    new_id,
    utcnow,
)
from facetta.image_agent import (
    ImageAgentError,
    ImageAgentResult,
    ImagePlanValidationError,
    ImageOperation,
    JewelryImageAgent,
    build_image_plan,
)
from facetta.creative_symmetry import (
    requests_jewelry_symmetry_repair,
    with_jewelry_symmetry_contract,
    with_requested_jewelry_symmetry_repair,
)
from facetta.image_run_store import (
    persist_image_agent_failure,
    persist_image_agent_result,
)
from facetta.jewelry_intent import with_sequential_jewelry_edit_contract
from facetta.image_agent.providers import RoutedImageProvider
from facetta.media import sniff_media_type
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
from facetta.specagent import mask_from_markup
from facetta.studio_history import (
    StudioHistoryError,
    apply_pre_spec_visual_candidate,
    discard_pre_spec_visual_candidate,
    fork_preview_candidate_variation,
    fork_project_variation,
    restore_project_revision,
)
from facetta.studio_continuation_prompts import (
    StudioContinuationPrompt,
    StudioContinuationPromptError,
    append_studio_continuation_prompt,
    list_studio_continuation_prompts,
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


class VisualPreviewAnnotation(BaseModel):
    """One designer-described change inside the combined marked raster."""

    model_config = ConfigDict(extra="forbid")

    region_description: Annotated[str, Field(min_length=1, max_length=500)]
    change_instruction: Annotated[str, Field(min_length=1, max_length=1000)]


class CreateVisualPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created_by: Annotated[str, Field(min_length=1, max_length=32)]
    expected_active_asset_id: Annotated[str, Field(min_length=1, max_length=32)]
    instruction: Annotated[str, Field(max_length=2000)] = ""
    # Display/audit copy of the designer's own words before the client or
    # backend adds preservation contracts for the image provider.
    raw_user_instruction: Annotated[
        str, Field(min_length=1, max_length=2000)
    ] | None = None
    input_mode: Literal[
        "describe", "markup", "point", "background", "angle", "symmetry",
    ] = "describe"
    annotations: Annotated[
        list[VisualPreviewAnnotation], Field(max_length=8)
    ] = Field(default_factory=list)
    scope: Literal["appearance", "marked_region"]
    mask_base64: Annotated[str, Field(min_length=1, max_length=14_000_000)] | None = None
    markup_asset_id: Annotated[str, Field(min_length=1, max_length=32)] | None = None
    variant: Annotated[int, Field(ge=0, le=100)] = 0
    studio_job_id: Annotated[str, Field(min_length=1, max_length=32)] | None = None

    @model_validator(mode="after")
    def validate_change_intent(self):
        if not self.instruction.strip() and not self.annotations:
            raise ValueError(
                "describe at least one change before creating a preview"
            )
        if any(
            not annotation.region_description.strip()
            or not annotation.change_instruction.strip()
            for annotation in self.annotations
        ):
            raise ValueError(
                "each annotation needs a marked region and requested change"
            )
        if self.annotations and self.scope != "marked_region":
            raise ValueError(
                "region-specific annotations require marked_region scope"
            )
        if self.raw_user_instruction is not None and not self.annotations:
            # The visible/audit copy may omit preservation text added by the
            # client, but it must still be the designer-authored portion of
            # the exact instruction that drives provider work.  Otherwise a
            # stale or malformed client could render change X while recording
            # change Y in immutable revision history.
            normalized_raw = " ".join(
                self.raw_user_instruction.casefold().split()
            )
            normalized_instruction = " ".join(
                self.instruction.casefold().split()
            )
            if normalized_raw not in normalized_instruction:
                raise ValueError(
                    "raw_user_instruction must be preserved in instruction"
                )
        marked_instructions = " ".join(
            (
                self.instruction,
                *(annotation.change_instruction for annotation in self.annotations),
            )
        )
        if (
            self.scope == "marked_region"
            and requests_jewelry_symmetry_repair(marked_instructions)
        ):
            raise ValueError(
                "bilateral symmetry repair cannot use a marked-region boundary; "
                "use the Symmetry tool so both corresponding sides are authorized"
            )
        return self


def _visual_preview_instruction(request: CreateVisualPreviewRequest) -> str:
    """Compile global prose plus per-region edits into one provider contract."""

    parts: list[str] = []
    overall = request.instruction.strip()
    if overall:
        parts.append(f"OVERALL DESIGNER REQUEST: {overall}")
    if request.annotations:
        numbered = " ".join(
            f"{index}. Inside '{item.region_description.strip()}': "
            f"{item.change_instruction.strip()}"
            for index, item in enumerate(request.annotations, start=1)
        )
        parts.append(
            "APPLY ALL MARKED CHANGES IN ONE PREVIEW. Each numbered change is "
            "required and applies only to its named marked region. " + numbered
        )
    return " ".join(parts)


def _user_continuation_prompt(request: CreateVisualPreviewRequest) -> str:
    """Return only designer-authored words for the visible Studio timeline."""

    overall = (
        request.raw_user_instruction.strip()
        if request.raw_user_instruction is not None
        else request.instruction.strip()
    )
    parts = [overall] if overall else []
    parts.extend(
        f"{item.region_description.strip()}: "
        f"{item.change_instruction.strip()}"
        for item in request.annotations
    )
    return "\n".join(parts)


def _continuation_prompt_payload(
    prompt: StudioContinuationPrompt,
    *,
    state: Literal[
        "requested", "preview_ready", "applied", "saved_as_variation",
        "discarded", "failed",
    ],
    candidate_id: str | None = None,
    image_run_id: str | None = None,
    applied_asset_id: str | None = None,
) -> dict:
    return {
        "prompt_id": prompt.prompt_id,
        "sequence": prompt.sequence,
        "prompt": prompt.prompt,
        "annotations": prompt.intent.get("annotations", []),
        "input_mode": prompt.intent.get("input_mode", "describe"),
        "scope": prompt.intent.get("scope"),
        "variant": prompt.intent.get("variant"),
        "source_asset_id": prompt.source_asset_id,
        "source_sha256": prompt.source_sha256,
        "studio_job_id": prompt.studio_job_id,
        "state": state,
        "candidate_id": candidate_id,
        "image_run_id": image_run_id,
        "applied_asset_id": applied_asset_id,
        "created_at": prompt.created_at.isoformat(),
    }


def _accepted_visual_instruction_history(
    db: Session,
    source: ImageAsset,
    *,
    limit: int = 8,
) -> tuple[str, ...]:
    """Read accepted source ancestry without treating history as new edits."""

    instructions: list[str] = []
    visited: set[str] = set()
    current: ImageAsset | None = source
    while current is not None and current.id not in visited:
        visited.add(current.id)
        if current.root_id != source.root_id:
            break
        if current.instruction and current.instruction.strip():
            instructions.append(current.instruction.strip()[:1000])
        if current.parent_asset_id is None:
            break
        current = db.get(ImageAsset, current.parent_asset_id)
    instructions.reverse()
    return tuple(instructions[-limit:])


_NUMBERED_MARKED_CHANGE = re.compile(
    r"\b\d+\. Inside '[^']+':\s*(.*?)(?=\s+\d+\. Inside '|$)",
    flags=re.IGNORECASE,
)
_LOCAL_GEOMETRY_TARGET = re.compile(
    r"\b(prongs?|claws?|bezel|setting|gallery|supports?|contours?|profile|"
    r"shank|band|shoulders?|edges?|openings?|frame)\b",
    flags=re.IGNORECASE,
)
_LOCAL_GEOMETRY_ACTION = re.compile(
    r"\b(finer|thinner|thicker|wider|narrower|delicate|reshape|round|sharpen|"
    r"extend|shorten|lower|raise|taper|remove|add)\b",
    flags=re.IGNORECASE,
)
_PRESERVATION_ONLY_CHANGE = re.compile(
    r"\b(keep|preserve|do not change|don't change|unchanged)\b",
    flags=re.IGNORECASE,
)


def _marked_region_contract(instruction: str) -> tuple[tuple[str, ...], int | None]:
    """Compile conservative QA authority from numbered designer changes."""

    changes = _NUMBERED_MARKED_CHANGE.findall(instruction)
    if not changes:
        return (), None
    domains = ["appearance"]
    if any(
        _LOCAL_GEOMETRY_TARGET.search(change)
        and _LOCAL_GEOMETRY_ACTION.search(change)
        and not _PRESERVATION_ONLY_CHANGE.search(change)
        for change in changes
    ):
        domains.append("local_geometry")
    return tuple(domains), len(changes)


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


class StudioMarkupPreviewCandidateResponse(StudioPreviewCandidateBase):
    kind: Literal["markup"] = "markup"
    operation: str
    region_description: str
    annotations: tuple[dict, ...]


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
    """Run a source-faithful, review-only pre-spec visual edit."""

    symmetry_repair = requests_jewelry_symmetry_repair(instruction)
    if scope == "marked_region" and symmetry_repair:
        raise ImagePlanValidationError(
            "bilateral symmetry repair cannot use a marked-region boundary; "
            "use the Symmetry tool so both corresponding sides are authorized",
            code="marked_symmetry_scope_conflict",
        )
    scope_instruction = (
        "PRE-SPEC SYMMETRY REPAIR. Correct only the bilateral mismatch the "
        "designer identified. The selected source remains authoritative for "
        "the center element and every unmentioned detail, but its unmatched "
        "left/right pattern is explicitly authorized to change. "
        if symmetry_repair else
        "PRE-SPEC DESCRIBED VISUAL REFINEMENT. Apply every explicitly "
        "requested visible change together in one temporary candidate. The "
        "designer's words authorize only the named differences, including "
        "named changes to color, material, surface, finish, stones, repeated "
        "motifs, visible contours, settings, or construction details. Preserve "
        "every unmentioned region and jewelry attribute. When a request names "
        "a bilateral or repeated class without limiting it to one side, apply "
        "the change consistently to corresponding elements. "
        if scope == "appearance" else
        "PRE-SPEC MARKED-REGION REFINEMENT. Apply every explicitly numbered "
        "change inside its named designer-marked region. A named change may "
        "alter local color, surface, finish, or visible contour, setting, or "
        "construction detail only when the designer explicitly requests it. "
        "Multiple marked changes may be completed together, but their combined "
        "mask is the absolute edit boundary. Preserve every pixel outside the "
        "mask. Inside the mask, preserve every unrequested jewelry attribute, "
        "including identity, topology, component count, proportions, stone "
        "shapes, stone placement, setting, and construction. "
        "Make each requested local difference visibly discernible at normal "
        "review scale inside the mask; an imperceptible near-copy does not "
        "complete the edit. "
    )
    marked_change_domains, marked_region_count = _marked_region_contract(
        instruction
    ) if scope == "marked_region" else ((), None)
    effective_instruction = with_sequential_jewelry_edit_contract(
        scope_instruction + instruction.strip()
    )
    if symmetry_repair:
        effective_instruction = with_requested_jewelry_symmetry_repair(
            effective_instruction
        )
    elif scope == "appearance":
        effective_instruction = with_jewelry_symmetry_contract(
            effective_instruction
        )
    plan = build_image_plan(
        ImageOperation.REFERENCE_RENDER,
        effective_instruction,
        source_image=source_image,
        mask_bytes=mask_bytes,
        mask_provenance=(
            "designer_marked_pre_spec_region" if mask_bytes is not None else None
        ),
        authorized_masked_change_domains=marked_change_domains,
        marked_region_count=marked_region_count,
        region_description=(
            "designer-marked edit regions"
            if scope == "marked_region" else None
        ),
        frozen=(
            (
                "exact center element, centerline anchor, and all unrelated "
                "jewelry identity outside the requested bilateral repair"
            ) if symmetry_repair else
            (
                "exact jewelry geometry and silhouette outside the designer "
                "mask; inside it, only explicitly requested local contour "
                "changes are authorized"
            ) if mask_bytes is not None else
            (
                "all unmentioned jewelry geometry and silhouette"
                if scope == "appearance" else
                "exact jewelry geometry and silhouette"
            ),
            (
                "all unmentioned stones, settings, metal and pave treatments, "
                "connections, and construction details"
            ) if symmetry_repair else
            (
                "all unrequested topology, component count, proportions, and "
                "placement"
            ) if mask_bytes is not None else
            (
                "all unmentioned topology, component count, proportions, and "
                "placement"
                if scope == "appearance" else
                "exact topology, component count, proportions, and placement"
            ),
            (
                "camera, crop, scale, lighting, background, and presentation"
            ) if symmetry_repair else (
                "all unrequested construction and setting details"
            ) if mask_bytes is not None else
            (
                "all unmentioned stones, settings, metal and pave treatments, "
                "connections, and construction details"
                if scope == "appearance" else
                "all construction and setting details"
            ),
            (
                "all details outside the corresponding left/right pattern"
            ) if symmetry_repair else
            "all pixels outside the designer mask" if mask_bytes is not None
            else "camera and composition unless explicitly requested",
        ),
        expected_output=(
            (
                "one source-faithful pre-spec visual preview with matching "
                "corresponding left/right jewelry elements, the center and "
                "all unmentioned details fixed, no unrelated drift, and no "
                "structural or production authority"
            ) if symmetry_repair else
            "one source-faithful pre-spec visual preview with only the explicitly "
            "requested change or marked changes, no unrelated drift, and no "
            "structural or production authority"
        ),
        variant=variant,
    )
    # Studio changes are interactive previews. Low-quality GPT Image output is
    # still a full 1024-class raster, but returns materially faster and has
    # proven more reliable than medium for source-image edits. QA and explicit
    # Apply remain mandatory before the preview can enter revision history.
    return JewelryImageAgent(
        provider=RoutedImageProvider(openai_quality="low"),
        use_available_fallback=True,
    ).run(
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
    return JewelryImageAgent(
        provider=RoutedImageProvider(openai_quality="low"),
        use_available_fallback=True,
    ).run(plan, source_image=source_image)


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
    """Generate a temporary review-only pre-spec preview without mutation."""

    compiled_instruction = _visual_preview_instruction(request)

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
        mask = _decode_visual_mask(
            db,
            request.mask_base64,
            created_by=request.created_by,
            markup_asset_id=request.markup_asset_id,
            scope=request.scope,
            source_asset=source,
            source=bytes(source.image),
        )
        provider_instruction = with_sequential_jewelry_edit_contract(
            compiled_instruction,
            accepted_instructions=_accepted_visual_instruction_history(
                db, source,
            ),
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

    expected_hash = hashlib.sha256(bytes(source.image)).hexdigest()
    try:
        continuation_prompt = append_studio_continuation_prompt(
            db,
            owner=request.created_by,
            project_root_id=project.root_id,
            source_asset_id=source.id,
            source_sha256=expected_hash,
            prompt=_user_continuation_prompt(request),
            intent={
                "raw_user_instruction": (
                    request.raw_user_instruction.strip()
                    if request.raw_user_instruction is not None else None
                ),
                "input_mode": request.input_mode,
                "annotations": [
                    annotation.model_dump(mode="json")
                    for annotation in request.annotations
                ],
                "scope": request.scope,
                "variant": request.variant,
                "markup_asset_id": request.markup_asset_id,
                "mask_sha256": (
                    hashlib.sha256(mask).hexdigest()
                    if mask is not None else None
                ),
                "compiled_instruction": compiled_instruction,
                "compiled_instruction_sha256": hashlib.sha256(
                    compiled_instruction.encode("utf-8")
                ).hexdigest(),
            },
            studio_job_id=request.studio_job_id,
        )
    except StudioContinuationPromptError as exc:
        if request.studio_job_id is not None:
            fail_reserved_studio_visual_job(
                db,
                job_id=request.studio_job_id,
                owner=request.created_by,
                error_code="continuation_prompt_conflict",
            )
        return JSONResponse(status_code=409, content={
            "code": "continuation_prompt_conflict",
            "category": "conflict",
            "detail": str(exc),
        })

    try:
        result = generate(
            bytes(source.image),
            provider_instruction,
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
            requested_change=compiled_instruction,
            scope=request.scope,
            qa=qa,
            created_by=request.created_by,
            studio_job_id=request.studio_job_id,
            continuation_prompt_id=continuation_prompt.prompt_id,
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
        "continuation_prompt": _continuation_prompt_payload(
            continuation_prompt,
            state="preview_ready",
            candidate_id=candidate.candidate_id,
            image_run_id=run_id,
        ),
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
        "continuation_prompt_id": candidate.continuation_prompt_id,
    } for candidate in candidates]}


@router.get("/projects/{project_root_id}/continuation-prompts")
def studio_continuation_prompt_history(
    project_root_id: str,
    db: DbSession,
    principal: PrincipalDep,
):
    """Return raw user-authored Refine prompts with their derived outcome."""

    project = db.get(Project, project_root_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project unavailable")
    if not principal.local_unbound and project.owner != principal.subject:
        raise HTTPException(status_code=404, detail="project unavailable")
    prompts = list_studio_continuation_prompts(
        db, owner=project.owner, project_root_id=project_root_id,
    )
    candidate_by_prompt_id: dict[str, PreviewCandidateRecord] = {}
    for candidate in db.scalars(select(PreviewCandidateRecord).where(
        PreviewCandidateRecord.owner == project.owner,
        PreviewCandidateRecord.project_root_id == project_root_id,
        PreviewCandidateRecord.kind == "studio_visual",
    ).order_by(PreviewCandidateRecord.created_at)):
        prompt_id = candidate.continuation_prompt_id
        if isinstance(prompt_id, str):
            candidate_by_prompt_id[prompt_id] = candidate
    job_ids = {
        prompt.studio_job_id for prompt in prompts
        if prompt.studio_job_id is not None
    }
    jobs = {
        job.id: job for job in db.scalars(select(StudioJobRecord).where(
            StudioJobRecord.id.in_(job_ids)
        ))
    } if job_ids else {}
    payloads: list[dict] = []
    for prompt in prompts:
        candidate = candidate_by_prompt_id.get(prompt.prompt_id)
        state: Literal[
            "requested", "preview_ready", "applied", "saved_as_variation",
            "discarded", "failed",
        ] = "requested"
        if candidate is not None:
            state = {
                "reviewing": "preview_ready",
                "applied": "applied",
                "saved_as_variation": "saved_as_variation",
                "discarded": "discarded",
                "expired": "failed",
            }[candidate.status]
        elif (
            prompt.studio_job_id is not None
            and jobs.get(prompt.studio_job_id) is not None
            and jobs[prompt.studio_job_id].status in {"failed", "canceled"}
        ):
            state = "failed"
        payloads.append(_continuation_prompt_payload(
            prompt,
            state=state,
            candidate_id=(candidate.id if candidate is not None else None),
            image_run_id=(
                candidate.image_run_id if candidate is not None else None
            ),
            applied_asset_id=(
                candidate.terminal_asset_id if candidate is not None else None
            ),
        ))
    return {"prompts": payloads}


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
        "annotations": list(candidate.annotations),
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
):
    try:
        result = fork_project_variation(
            db,
            project_root_id=project_root_id,
            source_asset_id=request.expected_active_asset_id,
            expected_active_asset_id=request.expected_active_asset_id,
            expected_design_version=request.expected_design_version,
            variation_label=request.label,
            created_by=request.created_by,
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
    request: SaveVariationRequest,
    db: DbSession,
):
    """Keep an unselected Create direction as a named sibling Variation."""

    try:
        result = fork_project_variation(
            db,
            project_root_id=project_root_id,
            source_asset_id=candidate_id,
            expected_active_asset_id=request.expected_active_asset_id,
            expected_design_version=request.expected_design_version,
            variation_label=request.label,
            created_by=request.created_by,
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


def _design_family_detail(
    db: Session,
    family: DesignFamily,
    *,
    effective_updated_at: datetime | None = None,
) -> dict:
    projects = list(db.scalars(
        select(Project)
        .where(Project.family_id == family.id)
        .order_by(Project.variation_index, Project.created_at)
    ))
    project_activity = _family_project_activity(db, family, projects)
    if effective_updated_at is None:
        effective_updated_at = max(
            project_activity.values(),
            default=family.updated_at,
        )
    elif project_activity:
        effective_updated_at = max(
            effective_updated_at,
            *project_activity.values(),
        )
    return {
        "family_id": family.id,
        "owner": family.owner,
        "title": family.title,
        "tags": list(family.tags or []),
        "is_favorite": family.favorited_at is not None,
        "favorited_at": (
            family.favorited_at.isoformat()
            if family.favorited_at is not None else None
        ),
        "created_at": family.created_at.isoformat(),
        "updated_at": effective_updated_at.isoformat(),
        "variations": [{
            **project_card(db, project),
            "updated_at": project_activity[project.root_id],
            "variation_index": project.variation_index,
            "variation_label": project.variation_label,
            "branched_from_project_root_id": (
                project.branched_from_project_root_id
            ),
            "branched_from_asset_id": project.branched_from_asset_id,
        } for project in projects],
    }


def _family_project_activity(
    db: Session,
    family: DesignFamily,
    projects: list[Project],
) -> dict[str, datetime]:
    """Return read-compatible variation activity for atomic Create families.

    Older atomic Create commits gave the selected Original and retained
    sibling branches the same final activity timestamp. Collections then used
    its deterministic variation-index tie break and reopened a retained
    sibling even though branch creation was only a persistence side effect of
    selecting Original.

    The durable Create decision is a safe compatibility boundary: its commit
    timestamp is later than every row created inside that transaction. We
    promote Original to that timestamp only when the complete recorded sibling
    set still predates the decision. Any project activity at or after commit is
    ambiguous or genuinely later and therefore disables the compatibility
    promotion. This is a response-only repair; canonical history is unchanged.
    """

    activity = {project.root_id: project.updated_at for project in projects}
    if not projects:
        return activity
    by_id = {project.root_id: project for project in projects}
    decisions = list(db.scalars(select(StudioCreateDecisionRecord).where(
        StudioCreateDecisionRecord.project_root_id.in_(tuple(by_id)),
        StudioCreateDecisionRecord.owner == family.owner,
    )))
    for decision in decisions:
        original = by_id.get(decision.project_root_id)
        retained_evidence = list(decision.retained_directions or [])
        selected = db.get(ImageAsset, decision.selected_candidate_asset_id)
        if (
            original is None
            or decision.created_by != decision.owner
            or original.owner != family.owner
            or original.family_id != family.id
            or original.selected_candidate_asset_id
            != decision.selected_candidate_asset_id
            or selected is None
            or selected.root_id != original.root_id
            or selected.created_by != family.owner
            or selected.created_at >= decision.committed_at
            or not retained_evidence
            or original.updated_at >= decision.committed_at
            or not _has_exact_atomic_create_revision(db, decision)
        ):
            continue

        retained_projects: list[Project] = []
        retained_project_ids: set[str] = set()
        retained_candidate_ids: set[str] = set()
        retained_asset_ids: set[str] = set()
        retained_indices: set[int] = set()
        for item in retained_evidence:
            if not isinstance(item, dict):
                retained_projects = []
                break
            project_root_id = item.get("project_root_id")
            candidate_id = item.get("candidate_id")
            asset_id = item.get("asset_id")
            variation_index = item.get("variation_index")
            if (
                not isinstance(project_root_id, str)
                or not isinstance(candidate_id, str)
                or not isinstance(asset_id, str)
                or not isinstance(variation_index, int)
                or project_root_id in retained_project_ids
                or candidate_id in retained_candidate_ids
                or asset_id in retained_asset_ids
                or variation_index in retained_indices
            ):
                retained_projects = []
                break
            retained_project_ids.add(project_root_id)
            retained_candidate_ids.add(candidate_id)
            retained_asset_ids.add(asset_id)
            retained_indices.add(variation_index)
            child = by_id.get(project_root_id)
            child_asset = db.get(ImageAsset, asset_id)
            if (
                child is None
                or child.owner != family.owner
                or child.family_id != family.id
                or child.root_id != asset_id
                or child.selected_candidate_asset_id != asset_id
                or child.branched_from_project_root_id != original.root_id
                or child.branched_from_asset_id != candidate_id
                or child.variation_label != item.get("label")
                or child.variation_index != variation_index
                or child.created_at >= decision.committed_at
                or child.updated_at >= decision.committed_at
                or child_asset is None
                or child_asset.root_id != child.root_id
                or child_asset.created_by != family.owner
                or child_asset.created_at >= decision.committed_at
                or not _has_exact_atomic_branch_revision(
                    db,
                    decision=decision,
                    child=child,
                    source_asset_id=candidate_id,
                    label=item.get("label"),
                )
            ):
                retained_projects = []
                break
            retained_projects.append(child)
        if len(retained_projects) != len(retained_evidence):
            continue

        precommit_children = set(db.scalars(select(Project.root_id).where(
            Project.branched_from_project_root_id == original.root_id,
            Project.created_at < decision.committed_at,
        )))
        if precommit_children != retained_project_ids:
            continue
        activity[original.root_id] = decision.committed_at
    return activity


def _has_exact_atomic_create_revision(
    db: Session,
    decision: StudioCreateDecisionRecord,
) -> bool:
    records = list(db.scalars(select(ProjectRevisionRecord).where(
        ProjectRevisionRecord.asset_id
        == decision.selected_candidate_asset_id,
    )))
    matching = [record for record in records if (
        record.action == "created"
        and record.created_by == decision.owner
        and record.created_at < decision.committed_at
        and record.raw_intent.get("kind") == "create_direction_commit"
        and record.raw_intent.get("create_decision_project_root_id")
        == decision.project_root_id
        and record.raw_intent.get("selected_candidate_asset_id")
        == decision.selected_candidate_asset_id
    )]
    return len(matching) == 1


def _has_exact_atomic_branch_revision(
    db: Session,
    *,
    decision: StudioCreateDecisionRecord,
    child: Project,
    source_asset_id: str,
    label: object,
) -> bool:
    records = list(db.scalars(select(ProjectRevisionRecord).where(
        ProjectRevisionRecord.asset_id == child.root_id,
    )))
    matching = [record for record in records if (
        record.action == "created"
        and record.created_by == decision.owner
        and record.created_at < decision.committed_at
        and record.raw_intent.get("kind") == "save_as_variation"
        and record.raw_intent.get("source_project_id")
        == decision.project_root_id
        and record.raw_intent.get("source_asset_id") == source_asset_id
        and record.raw_intent.get("label") == label
    )]
    return len(matching) == 1


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
    project_activity = (
        select(
            Project.family_id.label("family_id"),
            func.max(Project.updated_at).label("updated_at"),
        )
        .where(Project.family_id.is_not(None))
        .group_by(Project.family_id)
        .subquery()
    )
    effective_updated_at = func.coalesce(
        project_activity.c.updated_at,
        DesignFamily.updated_at,
    ).label("effective_updated_at")
    query = (
        select(DesignFamily, effective_updated_at)
        .outerjoin(
            project_activity,
            project_activity.c.family_id == DesignFamily.id,
        )
    )
    if effective_owner is not None:
        query = query.where(DesignFamily.owner == effective_owner)
    families = list(db.execute(
        query.order_by(effective_updated_at.desc(), DesignFamily.id)
    ))
    details = [
        _design_family_detail(
            db,
            family,
            effective_updated_at=activity_at,
        )
        for family, activity_at in families
    ]
    # SQL orders by stored activity before the compatibility projection is
    # known. Re-sort the small family page by the returned effective timestamp
    # so Recent and the representative variation use one consistent clock.
    details.sort(key=lambda detail: detail["family_id"])
    details.sort(key=lambda detail: detail["updated_at"], reverse=True)
    return {"families": details}


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

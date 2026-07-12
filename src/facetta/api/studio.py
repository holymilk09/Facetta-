"""AI-first Studio branching, immutable history, and restoration APIs."""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
from collections.abc import Callable
from datetime import timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from facetta.api.projects import project_card, project_detail
from facetta.api.error_mapping import image_agent_error_response
from facetta.db import (
    DesignFamily,
    ImageAsset,
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
from facetta.project_backbone import is_primary_revision
from facetta.specagent import mask_from_markup
from facetta.studio_history import (
    StudioHistoryError,
    apply_pre_spec_visual_candidate,
    discard_pre_spec_visual_candidate,
    fork_project_variation,
    restore_project_revision,
)
from facetta.studio_visual_candidates import (
    StudioVisualCandidateUnavailable,
    get_studio_visual_candidate,
    remove_studio_visual_candidate,
    store_studio_visual_candidate,
)


router = APIRouter(prefix="/studio", tags=["studio"])
DbSession = Annotated[Session, Depends(get_db)]


class SaveVariationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created_by: Annotated[str, Field(min_length=1, max_length=32)]
    expected_active_asset_id: Annotated[str, Field(min_length=1, max_length=32)]
    expected_design_version: Annotated[int, Field(ge=1)] | None = None
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


class CreateVisualPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created_by: Annotated[str, Field(min_length=1, max_length=32)]
    expected_active_asset_id: Annotated[str, Field(min_length=1, max_length=32)]
    instruction: Annotated[str, Field(min_length=3, max_length=1000)]
    scope: Literal["appearance", "marked_region"]
    mask_base64: Annotated[str, Field(min_length=1, max_length=14_000_000)] | None = None
    markup_asset_id: Annotated[str, Field(min_length=1, max_length=32)] | None = None
    variant: Annotated[int, Field(ge=0, le=100)] = 0


class ReviewVisualPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created_by: Annotated[str, Field(min_length=1, max_length=32)]
    expected_active_asset_id: Annotated[str, Field(min_length=1, max_length=32)]


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


_JOB_TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"running", "canceled", "failed"}),
    "running": frozenset({"reviewing", "canceled", "failed"}),
    "reviewing": frozenset({"succeeded", "failed", "canceled"}),
    "succeeded": frozenset(),
    "failed": frozenset(),
    "canceled": frozenset(),
}

_BILLING_POLICY = (
    "Only requested outputs that complete successfully are charged. "
    "Internal retries and failed review attempts are included."
)


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


def _owned_job(db: Session, job_id: str, owner: str) -> StudioJobRecord:
    job = db.get(StudioJobRecord, job_id)
    if job is None or job.owner != owner:
        # Do not disclose another owner's job identity.
        raise HTTPException(status_code=404, detail=f"unknown Studio job '{job_id}'")
    return job


@router.post("/jobs", status_code=201)
def create_studio_job(request: CreateStudioJobRequest, db: DbSession):
    now = utcnow()
    job = StudioJobRecord(
        id=new_id("job"),
        owner=request.owner,
        action_id=request.action_id,
        lane=request.lane,
        status="queued",
        progress=0,
        active_design_id=request.active_design_id,
        source_revision_id=request.source_revision_id,
        requested_outputs=request.requested_outputs,
        credits_per_output=request.credits_per_output,
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
    status: StudioJobStatus | None = None,
):
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
):
    return _studio_job(_owned_job(db, job_id, owner))


@router.patch("/jobs/{job_id}")
def transition_studio_job(
    job_id: str,
    request: TransitionStudioJobRequest,
    db: DbSession,
):
    job = _owned_job(db, job_id, request.owner)
    if request.status not in _JOB_TRANSITIONS[job.status]:
        raise HTTPException(
            status_code=409,
            detail=f"invalid Studio job transition: {job.status} -> {request.status}",
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
        job.charged_outputs = completed
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
):
    job = _owned_job(db, job_id, request.owner)
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
    if (source.root_id != project.root_id
            or source.capability != "CREATIVE_RENDER"):
        raise StudioHistoryError(
            "visual_preview_source_invalid",
            "select a pre-spec creative visual before refining it",
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
    except StudioHistoryError as exc:
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
            )
            if exc.plan is not None else None
        )
        return image_agent_error_response(exc, image_run_id=run_id)

    expected_hash = hashlib.sha256(bytes(source.image)).hexdigest()
    if (result.plan.operation is not ImageOperation.REFERENCE_RENDER
            or result.plan.source_hash != expected_hash):
        return JSONResponse(status_code=500, content={
            "code": "visual_preview_lineage_incomplete",
            "category": "internal",
            "detail": "the generated preview is not bound to the exact selected source",
        })
    if not result.accepted and not result.review_required:
        run_id = persist_image_agent_result(
            db,
            result,
            project_root_id=project.root_id,
            source_asset_id=source.id,
            created_by=request.created_by,
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
    )
    verdict: Literal["pass", "warn"] = (
        "pass" if result.accepted else "warn"
    )
    qa = _visual_preview_qa(result)
    candidate = store_studio_visual_candidate(
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
    )
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
def get_visual_preview_image(run_id: str, candidate_id: str):
    try:
        candidate = get_studio_visual_candidate(run_id, candidate_id)
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
):
    try:
        candidate = get_studio_visual_candidate(run_id, candidate_id)
        accepted = apply_pre_spec_visual_candidate(
            db,
            candidate=candidate,
            expected_active_asset_id=request.expected_active_asset_id,
            created_by=request.created_by,
        )
        remove_studio_visual_candidate(run_id, candidate_id)
    except StudioVisualCandidateUnavailable as exc:
        return JSONResponse(status_code=410, content={
            "code": "visual_preview_unavailable",
            "category": "conflict",
            "detail": str(exc),
        })
    except StudioHistoryError as exc:
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
):
    try:
        candidate = get_studio_visual_candidate(run_id, candidate_id)
        discarded = discard_pre_spec_visual_candidate(
            db,
            candidate=candidate,
            expected_active_asset_id=request.expected_active_asset_id,
            created_by=request.created_by,
        )
        remove_studio_visual_candidate(run_id, candidate_id)
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
    request: SaveVariationRequest,
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
    primary = [asset for asset in chain if is_primary_revision(asset)]
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
        "variation_index": project.variation_index,
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
def list_design_families(db: DbSession, owner: str | None = None):
    """List Studio families without flattening their variation boundaries."""

    query = select(DesignFamily)
    if owner is not None:
        query = query.where(DesignFamily.owner == owner)
    families = list(db.scalars(
        query.order_by(DesignFamily.updated_at.desc(), DesignFamily.id)
    ))
    return {
        "families": [_design_family_detail(db, family) for family in families],
    }


@router.get("/families/{family_id}")
def get_design_family(family_id: str, db: DbSession):
    family = db.get(DesignFamily, family_id)
    if family is None:
        raise HTTPException(status_code=404,
                            detail=f"unknown design family '{family_id}'")
    return _design_family_detail(db, family)

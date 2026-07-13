"""Read-only observability and authoritative factory handoff APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from facetta.api.projects import ProjectDetail, project_detail
from facetta.auth import (
    AuthenticatedPrincipal,
    principal_actor,
    require_image_run_boundary,
    require_principal_boundary,
)
from facetta.db import (
    FeedbackEvent, ImageAttempt, ImageRun, ImageRunReview, Project, get_db,
    utcnow,
)
from facetta.factory_pack import (
    FactoryPackUnavailable,
    build_factory_pack,
    factory_pack_zip,
)
from facetta.factory_sheet_plan import FactorySheetFactPlan
from facetta.trusted_revision import (
    WarningRevisionError, accept_warning_revision, discard_warning_revision,
)
from facetta.studio_markup_candidates import (
    StudioMarkupCandidateUnavailable,
    StudioMarkupError,
    accept_studio_markup_candidate,
    discard_studio_markup_candidate,
    get_studio_markup_candidate,
)
from facetta.studio_jobs import (
    FactoryJobContextError,
    StudioJobAccountingError,
    record_accepted_studio_job_outputs,
    revalidate_factory_job_for_execution,
)
from facetta.warning_candidates import (
    discard_markup_warning_candidate,
    WarningCandidateUnavailable, get_markup_warning_candidate,
)

router = APIRouter(
    tags=["trusted-workflow"],
    dependencies=[
        Depends(require_principal_boundary),
        Depends(require_image_run_boundary),
    ],
)
DbSession = Annotated[Session, Depends(get_db)]
PrincipalDep = Annotated[AuthenticatedPrincipal, Depends(require_principal_boundary)]


class ImageAttemptSummary(BaseModel):
    attempt_id: str
    attempt_number: int
    provider: str
    model: str
    latency_ms: int | None
    cached: bool
    provider_request_id: str | None
    qa_verdict: str | None
    qa_checks: list[dict[str, object]]
    corrective_instruction: str | None
    fallback_reason: str | None
    output_hash: str | None
    prompt_hash: str | None
    cache_key: str | None
    usage: dict[str, object]
    cost: float | None
    error_category: str | None
    created_at: datetime
    attempt: int
    engine_role: str
    cache_hit: bool
    verdict: str
    failed_checks: list[str]
    correction: str | None


class ImageRunSummary(BaseModel):
    run_id: str
    project_id: str | None
    source_asset_id: str | None
    operation: str
    normalized_intent: dict[str, object]
    prompt_version: str
    input_hash: str | None
    source_hash: str | None
    mask_hash: str | None
    spec_visual_hash: str | None
    source_spec_visual_hash: str | None
    variant: int
    status: str
    stored_status: str
    accepted_asset_id: str | None
    review_decision: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    error_category: str | None
    created_by: str
    created_at: datetime
    attempts: list[ImageAttemptSummary]
    prompt_contract_version: str
    verdict: str | None
    accepted: bool
    review_required: bool
    output_hash: str | None
    completed_at: datetime | None


class WarningCandidateAcceptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_design_version: Annotated[int, Field(ge=1)]
    created_by: Annotated[str, Field(min_length=1, max_length=32)]


class WarningCandidateDiscardRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created_by: Annotated[str, Field(min_length=1, max_length=32)]


class ImageRunFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["accepted", "regenerated", "rejected"]
    note: Annotated[str, Field(max_length=1000)] | None = None
    created_by: Annotated[str, Field(min_length=1, max_length=32)]


class FactoryPackFile(BaseModel):
    name: str
    sha256: str
    bytes: int
    authoritative: bool


class FactoryPackAuthority(BaseModel):
    factory_truth: list[str]
    authoritative_fact_records: list[str] = Field(default_factory=list)
    dimensional_diagram_only: list[str] = Field(default_factory=list)
    exchange_reference_only: list[str] = Field(default_factory=list)
    visual_reference_only: list[str]
    discussion_only: list[str] = Field(default_factory=list)
    production_authority: list[str] = Field(default_factory=list)
    release_status: Literal["factory_review_only"] = "factory_review_only"
    note: str


class FactoryDimensionEstimate(BaseModel):
    field_path: str
    value: object | None
    unit: str
    status: Literal["estimated_from_reference"]
    method: str
    source: str
    confidence: float | None
    note: str | None


class FactoryDimensionSummary(BaseModel):
    has_estimates: bool
    estimated_fields: list[FactoryDimensionEstimate]
    disclaimer: str | None


class FactoryChecklistResult(BaseModel):
    item_key: str
    label: str | None
    fact: str | None
    approved: bool
    note: str | None
    approved_by: str | None
    approved_at: str | None


class FactoryChecklistManifest(BaseModel):
    id: str
    mode: str
    status: dict[str, object]
    results: list[FactoryChecklistResult]


class FactoryPackManifest(BaseModel):
    schema_version: str
    project_id: str
    design_id: str
    design_version: int
    asset_id: str
    visual_revision: int
    approver: str
    approved_at: str
    pinned_at: str
    checklist: FactoryChecklistManifest
    qa_summary: dict[str, object]
    dimensions: FactoryDimensionSummary
    factory_sheet_fact_plan: FactorySheetFactPlan
    authority: FactoryPackAuthority
    files: list[FactoryPackFile]


@router.get("/image-runs/{run_id}", response_model=ImageRunSummary)
def get_image_run(run_id: str, db: DbSession):
    run = db.get(ImageRun, run_id)
    if run is None:
        raise HTTPException(status_code=404,
                            detail=f"unknown image run '{run_id}'")
    attempts = list(db.scalars(
        select(ImageAttempt)
        .where(ImageAttempt.run_id == run.id)
        .order_by(ImageAttempt.attempt_number, ImageAttempt.id)
    ))
    last_qa = next(
        (attempt for attempt in reversed(attempts) if attempt.qa_verdict),
        None,
    )
    last_output = next(
        (attempt for attempt in reversed(attempts) if attempt.output_hash),
        None,
    )
    review = db.scalar(select(ImageRunReview).where(
        ImageRunReview.run_id == run.id))
    accepted_asset_id = (
        review.accepted_asset_id if review is not None
        and review.decision == "accepted"
        else run.accepted_asset_id
    )
    effective_status = (
        "accepted" if accepted_asset_id is not None else run.status
    )
    return {
        "run_id": run.id,
        "project_id": run.project_root_id,
        "source_asset_id": run.source_asset_id,
        "operation": run.operation,
        "normalized_intent": run.normalized_intent,
        "prompt_version": run.prompt_version,
        "prompt_contract_version": run.prompt_version,
        "input_hash": run.input_hash,
        "source_hash": run.source_hash,
        "mask_hash": run.mask_hash,
        "spec_visual_hash": run.spec_visual_hash,
        "source_spec_visual_hash": run.source_spec_visual_hash,
        "variant": run.variant,
        "status": effective_status,
        "stored_status": run.status,
        "accepted_asset_id": accepted_asset_id,
        "review_decision": review.decision if review else None,
        "reviewed_by": review.created_by if review else None,
        "reviewed_at": review.created_at if review else None,
        "error_category": run.error_category,
        "created_by": run.created_by,
        "created_at": run.created_at,
        "verdict": last_qa.qa_verdict if last_qa else None,
        "accepted": effective_status == "accepted",
        "review_required": effective_status == "review_required",
        "output_hash": last_output.output_hash if last_output else None,
        "completed_at": attempts[-1].created_at if attempts else run.created_at,
        "attempts": [{
            "attempt_id": attempt.id,
            "attempt_number": attempt.attempt_number,
            "provider": attempt.provider,
            "model": attempt.model,
            "latency_ms": attempt.latency_ms,
            "cached": attempt.cached,
            "provider_request_id": attempt.provider_request_id,
            "qa_verdict": attempt.qa_verdict,
            "qa_checks": attempt.qa_checks or [],
            "corrective_instruction": attempt.corrective_instruction,
            "fallback_reason": attempt.fallback_reason,
            "output_hash": attempt.output_hash,
            "prompt_hash": attempt.prompt_hash,
            "cache_key": attempt.cache_key,
            "usage": attempt.usage or {},
            "cost": attempt.cost,
            "error_category": attempt.error_category,
            "created_at": attempt.created_at,
            "attempt": attempt.attempt_number,
            "engine_role": ("fallback" if attempt.fallback_reason else
                            "primary" if attempt.attempt_number == 1 else
                            "primary_retry"),
            "cache_hit": attempt.cached,
            "verdict": attempt.qa_verdict or "fail",
            "failed_checks": [
                str(check.get("code")) for check in (attempt.qa_checks or [])
                if not bool(check.get("passed", False))
            ],
            "correction": attempt.corrective_instruction,
        } for attempt in attempts],
    }


@router.get("/image-runs/{run_id}/candidates/{candidate_id}/image")
def get_warning_candidate_image(
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
    durable = None
    if owner is not None:
        try:
            durable = get_studio_markup_candidate(
                db, run_id, candidate_id, owner=owner)
        except StudioMarkupCandidateUnavailable:
            pass
    if durable is not None:
        if durable.status != "reviewing":
            return JSONResponse(status_code=410, content={
                "code": "warning_candidate_unavailable",
                "category": "conflict",
                "detail": f"the warning candidate was already {durable.status}",
            })
        return Response(
            content=durable.image_bytes,
            media_type=durable.media_type,
            headers={"Cache-Control": "private, no-store"},
        )
    try:
        candidate = get_markup_warning_candidate(run_id, candidate_id)
    except WarningCandidateUnavailable as exc:
        return JSONResponse(status_code=410, content={
            "code": "warning_candidate_unavailable",
            "category": "conflict",
            "detail": str(exc),
        })
    if not principal.local_unbound and candidate.created_by != principal.subject:
        raise HTTPException(status_code=404, detail="warning candidate unavailable")
    return Response(
        content=candidate.image_bytes,
        media_type=candidate.media_type,
        headers={"Cache-Control": "private, no-store"},
    )


@router.post("/image-runs/{run_id}/feedback", status_code=201)
def create_image_run_feedback(
    run_id: str,
    request: ImageRunFeedbackRequest,
    db: DbSession,
    principal: PrincipalDep,
):
    principal_actor(principal, request.created_by)
    run = db.get(ImageRun, run_id)
    if run is None:
        raise HTTPException(status_code=404,
                            detail=f"unknown image run '{run_id}'")
    review = db.scalar(select(ImageRunReview).where(
        ImageRunReview.run_id == run.id))
    subject_id = (
        review.accepted_asset_id if review is not None
        and review.accepted_asset_id is not None
        else run.accepted_asset_id or run.source_asset_id
        or run.project_root_id or run.id
    )
    event = FeedbackEvent(
        asset_id=subject_id,
        image_run_id=run.id,
        subject_kind="image_run",
        action=request.action,
        note=request.note,
        created_by=request.created_by,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return {
        "feedback_id": event.id,
        "image_run_id": run.id,
        "action": event.action,
        "created_by": event.created_by,
        "created_at": event.created_at,
    }


@router.post(
    "/image-runs/{run_id}/candidates/{candidate_id}/accept",
    status_code=201,
    response_model=ProjectDetail,
    response_model_exclude_none=True,
)
def accept_warning_candidate(
    run_id: str,
    candidate_id: str,
    request: WarningCandidateAcceptRequest,
    db: DbSession,
    principal: PrincipalDep,
):
    principal_actor(principal, request.created_by)
    durable = None
    try:
        durable = get_studio_markup_candidate(
            db, run_id, candidate_id, owner=request.created_by)
    except StudioMarkupCandidateUnavailable:
        pass
    if durable is not None:
        try:
            accept_studio_markup_candidate(
                db,
                durable,
                expected_active_asset_id=durable.source_asset_id,
                expected_design_version=request.expected_design_version,
                created_by=request.created_by,
            )
        except (StudioMarkupError, WarningRevisionError) as exc:
            return JSONResponse(status_code=exc.status_code, content={
                "code": exc.code,
                "category": (
                    "stale_version" if exc.code.startswith("stale_")
                    else "validation" if exc.status_code == 422
                    else "conflict"
                ),
                "detail": exc.detail,
            })
        project = db.get(Project, durable.project_root_id)
        if project is None:  # pragma: no cover
            raise HTTPException(status_code=500, detail="accepted project unavailable")
        return project_detail(db, project)
    try:
        candidate = get_markup_warning_candidate(run_id, candidate_id)
        if candidate.promotion_kind == "presentation_only":
            raise WarningRevisionError(
                "presentation_resolution_requires_exact_lineage",
                "resolve presentation candidates through the Studio lineage endpoint",
                status_code=422,
            )
        accept_warning_revision(
            db,
            candidate,
            expected_design_version=request.expected_design_version,
            created_by=request.created_by,
        )
    except WarningCandidateUnavailable as exc:
        return JSONResponse(status_code=410, content={
            "code": "warning_candidate_unavailable",
            "category": "conflict",
            "detail": str(exc),
        })
    except WarningRevisionError as exc:
        return JSONResponse(status_code=exc.status_code, content={
            "code": exc.code,
            "category": ("stale_version" if exc.code.startswith("stale_")
                         else "validation" if exc.status_code == 422
                         else "conflict"),
            "detail": exc.detail,
        })
    project = db.get(Project, candidate.project_root_id)
    if project is None:
        raise HTTPException(status_code=404, detail="accepted project not found")
    return project_detail(db, project)


@router.post(
    "/image-runs/{run_id}/candidates/{candidate_id}/discard",
)
def discard_warning_candidate(
    run_id: str,
    candidate_id: str,
    request: WarningCandidateDiscardRequest,
    db: DbSession,
    principal: PrincipalDep,
):
    principal_actor(principal, request.created_by)
    durable = None
    try:
        durable = get_studio_markup_candidate(
            db, run_id, candidate_id, owner=request.created_by)
    except StudioMarkupCandidateUnavailable:
        pass
    if durable is not None:
        try:
            discard_studio_markup_candidate(
                db,
                durable,
                expected_active_asset_id=durable.source_asset_id,
                expected_design_version=durable.design_version,
                created_by=request.created_by,
            )
        except (StudioMarkupError, WarningRevisionError) as exc:
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
        return {
            "status": "discarded",
            "run_id": durable.run_id,
            "candidate_id": durable.candidate_id,
        }
    try:
        candidate = get_markup_warning_candidate(run_id, candidate_id)
        if candidate.promotion_kind == "presentation_only":
            raise WarningRevisionError(
                "presentation_resolution_requires_exact_lineage",
                "resolve presentation candidates through the Studio lineage endpoint",
                status_code=422,
            )
        if candidate.created_by != request.created_by:
            raise WarningCandidateUnavailable(
                "only the candidate creator may discard it")
        discard_warning_revision(
            db,
            candidate,
            expected_design_version=candidate.expected_design_version,
            created_by=request.created_by,
        )
        discard_markup_warning_candidate(
            run_id, candidate_id, created_by=request.created_by,
        )
    except WarningCandidateUnavailable as exc:
        return JSONResponse(status_code=410, content={
            "code": "warning_candidate_unavailable",
            "category": "conflict",
            "detail": str(exc),
        })
    except WarningRevisionError as exc:
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
    return {
        "status": "discarded",
        "run_id": candidate.run_id,
        "candidate_id": candidate.candidate_id,
    }


def _pack_or_error(db: Session, project_id: str):
    try:
        return build_factory_pack(db, project_id)
    except FactoryPackUnavailable as exc:
        return JSONResponse(status_code=exc.status_code, content={
            "code": exc.code,
            "category": ("validation" if exc.status_code == 422
                         else "approval"),
            "detail": exc.detail,
        })


@router.get(
    "/projects/{project_id}/factory-pack",
    response_model=FactoryPackManifest,
)
def get_factory_pack_manifest(project_id: str, db: DbSession):
    pack = _pack_or_error(db, project_id)
    if isinstance(pack, JSONResponse):
        return pack
    return pack.manifest


class PrepareFactoryPackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    studio_job_id: Annotated[str, Field(min_length=1, max_length=32)]
    owner: Annotated[str, Field(min_length=1, max_length=32)]


@router.post(
    "/projects/{project_id}/factory-pack",
    response_model=FactoryPackManifest,
)
def prepare_factory_pack(
    project_id: str,
    request: PrepareFactoryPackRequest,
    db: DbSession,
    principal: PrincipalDep,
):
    """Build and bill one exact Factory output in one backend transaction.

    The queued job is the server-held CAS token for the active revision and
    approval generation. A successful response means the deterministic pack
    exists and exactly one accepted output was charged. Failed or stale work
    is terminal with zero charge.
    """
    principal_actor(principal, request.owner)
    try:
        job = revalidate_factory_job_for_execution(
            db, job_id=request.studio_job_id, owner=request.owner,
        )
    except FactoryJobContextError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if job.active_design_id != project_id:
        job.status = "failed"
        job.progress = 1
        job.completed_outputs = 0
        job.charged_outputs = 0
        job.error_code = "factory_project_mismatch"
        job.updated_at = utcnow()
        db.commit()
        raise HTTPException(
            status_code=409,
            detail="the Factory job is not bound to this project",
        )
    job.status = "running"
    job.progress = 0.5
    job.updated_at = utcnow()
    db.flush()
    try:
        pack = build_factory_pack(db, project_id)
    except FactoryPackUnavailable as exc:
        job.status = "failed"
        job.progress = 1
        job.completed_outputs = 0
        job.charged_outputs = 0
        job.error_code = exc.code
        job.updated_at = utcnow()
        db.commit()
        return JSONResponse(status_code=exc.status_code, content={
            "code": exc.code,
            "category": ("validation" if exc.status_code == 422 else "approval"),
            "detail": exc.detail,
        })
    try:
        record_accepted_studio_job_outputs(
            db,
            job_id=job.id,
            owner=request.owner,
            completed_outputs=1,
            active_design_id=project_id,
            source_revision_id=job.source_revision_id,
        )
    except StudioJobAccountingError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return pack.manifest


@router.get("/projects/{project_id}/factory-pack.zip")
def download_factory_pack(project_id: str, db: DbSession):
    pack = _pack_or_error(db, project_id)
    if isinstance(pack, JSONResponse):
        return pack
    return Response(
        content=factory_pack_zip(pack),
        media_type="application/zip",
        headers={
            "Content-Disposition":
                f'attachment; filename="facetta-{project_id}-factory-pack.zip"'
        },
    )

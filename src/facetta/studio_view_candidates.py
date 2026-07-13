"""Durable exact Studio View candidates and atomic review decisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from facetta.candidate_qa import forced_review_candidate_qa
from facetta.db import (
    DesignVersion,
    ImageAsset,
    ImageRun,
    ImageRunReview,
    Project,
    StudioJobRecord,
    StudioViewCandidateRecord,
    new_id,
    utcnow,
)
from facetta.image_identity import spec_visual_hash
from facetta.project_backbone import is_primary_revision
from facetta.spec import Spec
from facetta.studio_jobs import (
    StudioJobAccountingError,
    record_accepted_studio_job_outputs,
    studio_job_action_definition,
)


_TTL = timedelta(hours=2)
StudioViewName = Literal["front", "three_quarter", "side"]
StudioViewStatus = Literal["reviewing", "accepted", "discarded", "expired"]


class StudioViewCandidateUnavailable(LookupError):
    def __init__(self, detail: str, *, status_code: int = 410):
        self.status_code = status_code
        super().__init__(detail)


class StudioViewError(ValueError):
    def __init__(self, code: str, detail: str, *, status_code: int = 409):
        self.code = code
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


@dataclass(frozen=True)
class StudioViewCandidate:
    candidate_id: str
    run_id: str
    project_root_id: str
    source_asset_id: str
    source_hash: str
    output_hash: str
    spec_hash: str
    design_version: int
    view: StudioViewName
    image_bytes: bytes
    media_type: str
    requested_change: str
    qa: dict
    routing: dict
    created_by: str
    status: StudioViewStatus
    expires_at: datetime
    studio_job_id: str | None
    accepted_asset_id: str | None
    review_id: str | None


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _candidate(record: StudioViewCandidateRecord) -> StudioViewCandidate:
    return StudioViewCandidate(
        candidate_id=record.id,
        run_id=record.image_run_id,
        project_root_id=record.project_root_id,
        source_asset_id=record.source_asset_id,
        source_hash=record.source_sha256,
        output_hash=record.output_sha256,
        spec_hash=record.spec_visual_hash,
        design_version=record.design_version,
        view=record.view,  # type: ignore[arg-type]
        image_bytes=bytes(record.image),
        media_type=record.media_type,
        requested_change=record.requested_change,
        qa=record.qa,
        routing=record.routing,
        created_by=record.owner,
        status=record.status,  # type: ignore[arg-type]
        expires_at=_utc(record.expires_at),
        studio_job_id=record.studio_job_id,
        accepted_asset_id=record.accepted_asset_id,
        review_id=record.review_id,
    )


def _view_job(
    db: Session,
    *,
    job_id: str,
    owner: str,
    project_root_id: str,
    source_asset_id: str,
) -> StudioJobRecord:
    job = db.get(StudioJobRecord, job_id)
    canonical = studio_job_action_definition("views")
    if job is None or job.owner != owner:
        raise StudioViewError(
            "view_job_unavailable", "the Studio View job is unavailable",
            status_code=404,
        )
    if (
        job.action_id != "views"
        or job.lane != canonical.lane
        or job.credits_per_output != canonical.credits_per_output
        or job.requested_outputs != 1
    ):
        raise StudioViewError(
            "view_job_invalid",
            "this endpoint requires a canonical one-output Studio View job",
            status_code=422,
        )
    if job.status not in {"running", "reviewing"}:
        raise StudioViewError(
            "view_job_terminal", f"the Studio View job is already {job.status}",
        )
    for field, expected in (
        ("active_design_id", project_root_id),
        ("source_revision_id", source_asset_id),
    ):
        current = getattr(job, field)
        if current is not None and current != expected:
            raise StudioViewError(
                "view_job_lineage_mismatch",
                "the Studio View job belongs to a different exact revision",
                status_code=422,
            )
        setattr(job, field, expected)
    job.status = "reviewing"
    job.progress = max(job.progress, 0.9)
    job.updated_at = utcnow()
    return job


def reserve_studio_view_job(
    db: Session,
    *,
    job_id: str,
    owner: str,
    project_root_id: str,
    source_asset_id: str,
) -> None:
    job = db.scalar(select(StudioJobRecord).where(
        StudioJobRecord.id == job_id).with_for_update())
    canonical = studio_job_action_definition("views")
    if job is None or job.owner != owner:
        raise StudioViewError(
            "view_job_unavailable", "the Studio View job is unavailable",
            status_code=404,
        )
    if (
        job.action_id != "views"
        or job.lane != canonical.lane
        or job.credits_per_output != canonical.credits_per_output
        or job.requested_outputs != 1
    ):
        raise StudioViewError(
            "view_job_invalid",
            "this endpoint requires a canonical one-output Studio View job",
            status_code=422,
        )
    if job.status != "running":
        raise StudioViewError(
            "view_job_terminal", f"the Studio View job cannot run from {job.status}",
        )
    for field, expected in (
        ("active_design_id", project_root_id),
        ("source_revision_id", source_asset_id),
    ):
        current = getattr(job, field)
        if current is not None and current != expected:
            raise StudioViewError(
                "view_job_lineage_mismatch",
                "the Studio View job belongs to a different exact revision",
                status_code=422,
            )
        setattr(job, field, expected)
    job.updated_at = utcnow()
    db.commit()


def fail_studio_view_job(
    db: Session, *, job_id: str, owner: str, error_code: str,
) -> None:
    job = db.scalar(select(StudioJobRecord).where(
        StudioJobRecord.id == job_id).with_for_update())
    if job is None or job.owner != owner or job.status not in {"running", "reviewing"}:
        return
    if db.scalar(select(StudioViewCandidateRecord.id).where(
        StudioViewCandidateRecord.studio_job_id == job_id)) is not None:
        return
    job.status = "failed"
    job.progress = 1
    job.completed_outputs = 0
    job.charged_outputs = 0
    job.error_code = error_code[:64]
    job.updated_at = utcnow()
    db.commit()


def _exact_view_job(
    db: Session,
    record: StudioViewCandidateRecord,
) -> StudioJobRecord | None:
    if record.studio_job_id is None:
        return None
    job = db.get(StudioJobRecord, record.studio_job_id)
    canonical = studio_job_action_definition("views")
    if (
        job is None
        or job.owner != record.owner
        or job.action_id != "views"
        or job.lane != canonical.lane
        or job.credits_per_output != canonical.credits_per_output
        or job.requested_outputs != 1
        or job.active_design_id != record.project_root_id
        or job.source_revision_id != record.source_asset_id
    ):
        return None
    return job


def store_studio_view_candidate(
    db: Session,
    *,
    run_id: str,
    project_root_id: str,
    source_asset_id: str,
    source_hash: str,
    output_bytes: bytes,
    media_type: str,
    design_version: int,
    spec_hash: str,
    view: StudioViewName,
    requested_change: str,
    qa: dict,
    routing: dict,
    created_by: str,
    studio_job_id: str | None = None,
) -> StudioViewCandidate:
    bound_job = None
    if studio_job_id is not None:
        bound_job = _view_job(
            db,
            job_id=studio_job_id,
            owner=created_by,
            project_root_id=project_root_id,
            source_asset_id=source_asset_id,
        )
    if not forced_review_candidate_qa(qa):
        if bound_job is not None:
            bound_job.status = "failed"
            bound_job.progress = 1
            bound_job.completed_outputs = 0
            bound_job.charged_outputs = 0
            bound_job.error_code = "view_candidate_qa_invalid"
            bound_job.updated_at = utcnow()
            db.commit()
        raise StudioViewError(
            "view_candidate_qa_invalid",
            "the View QA evidence is incomplete or not reviewable",
            status_code=422,
        )
    now = utcnow()
    record = StudioViewCandidateRecord(
        id=new_id("cand"),
        image_run_id=run_id,
        owner=created_by,
        project_root_id=project_root_id,
        source_asset_id=source_asset_id,
        source_sha256=source_hash,
        output_sha256=hashlib.sha256(output_bytes).hexdigest(),
        spec_visual_hash=spec_hash,
        design_version=design_version,
        view=view,
        image=output_bytes,
        media_type=media_type,
        requested_change=requested_change,
        qa=qa,
        routing=routing,
        status="reviewing",
        studio_job_id=studio_job_id,
        created_at=now,
        expires_at=now + _TTL,
    )
    db.add(record)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise StudioViewError(
            "view_candidate_conflict",
            "a durable View candidate already exists for this generation",
        ) from exc
    return _candidate(record)


def _owned_record(
    db: Session,
    run_id: str,
    candidate_id: str,
    *,
    owner: str,
    for_update: bool = False,
) -> StudioViewCandidateRecord:
    query = select(StudioViewCandidateRecord).where(
        StudioViewCandidateRecord.id == candidate_id,
        StudioViewCandidateRecord.image_run_id == run_id,
        StudioViewCandidateRecord.owner == owner,
    )
    if for_update:
        query = query.with_for_update()
    record = db.scalar(query)
    if record is None:
        raise StudioViewCandidateUnavailable(
            "the Studio View candidate is unavailable", status_code=404)
    if record.status == "reviewing" and _utc(record.expires_at) <= utcnow():
        record.status = "expired"
        record.image = b""
        record.resolved_at = utcnow()
        job = _exact_view_job(db, record)
        if job is not None:
            if job.status in {"running", "reviewing"}:
                job.status = "canceled"
                job.progress = 1
                job.completed_outputs = 0
                job.charged_outputs = 0
                job.error_code = None
                job.updated_at = utcnow()
        db.commit()
        raise StudioViewCandidateUnavailable(
            "the Studio View candidate expired before a decision")
    if record.status == "reviewing" and not forced_review_candidate_qa(record.qa):
        record.status = "expired"
        record.image = b""
        record.resolved_at = utcnow()
        job = _exact_view_job(db, record)
        if job is not None:
            if job.status in {"running", "reviewing"}:
                job.status = "failed"
                job.progress = 1
                job.completed_outputs = 0
                job.charged_outputs = 0
                job.error_code = "view_candidate_qa_invalid"
                job.updated_at = utcnow()
        db.commit()
        raise StudioViewCandidateUnavailable(
            "the Studio View candidate QA evidence is invalid")
    if record.status == "reviewing" and _exact_view_job(db, record) is None:
        record.status = "expired"
        record.image = b""
        record.resolved_at = utcnow()
        db.commit()
        raise StudioViewCandidateUnavailable(
            "the Studio View candidate job binding is invalid")
    return record


def get_studio_view_candidate(
    db: Session, run_id: str, candidate_id: str, *, owner: str,
) -> StudioViewCandidate:
    return _candidate(_owned_record(db, run_id, candidate_id, owner=owner))


def list_studio_view_candidates(
    db: Session,
    *,
    owner: str,
    project_root_id: str | None = None,
    status: StudioViewStatus | None = "reviewing",
) -> list[StudioViewCandidate]:
    query = select(StudioViewCandidateRecord).where(
        StudioViewCandidateRecord.owner == owner)
    if project_root_id is not None:
        query = query.where(
            StudioViewCandidateRecord.project_root_id == project_root_id)
    if status is not None:
        query = query.where(StudioViewCandidateRecord.status == status)
    records = list(db.scalars(query.order_by(
        StudioViewCandidateRecord.created_at.desc(),
        StudioViewCandidateRecord.id,
    )))
    result: list[StudioViewCandidate] = []
    for record in records:
        try:
            result.append(_candidate(_owned_record(
                db, record.image_run_id, record.id, owner=owner)))
        except StudioViewCandidateUnavailable:
            continue
    return result


def _active_primary(db: Session, project_root_id: str) -> ImageAsset | None:
    chain = list(db.scalars(select(ImageAsset).where(
        ImageAsset.root_id == project_root_id,
    ).order_by(ImageAsset.created_at, ImageAsset.id)))
    chain.sort(key=lambda asset: (
        asset.id != project_root_id, asset.created_at, asset.id))
    primary = [asset for asset in chain if is_primary_revision(asset)]
    return primary[-1] if primary else None


def _require_exact_lineage(
    db: Session,
    candidate: StudioViewCandidate,
    *,
    expected_project_id: str,
    expected_source_asset_id: str,
    expected_design_version: int,
    created_by: str,
    require_active: bool = True,
) -> tuple[Project, ImageAsset, ImageAsset, ImageRun]:
    project = db.scalar(select(Project).where(
        Project.root_id == candidate.project_root_id).with_for_update())
    record = db.scalar(select(StudioViewCandidateRecord).where(
        StudioViewCandidateRecord.id == candidate.candidate_id).with_for_update())
    source = db.get(ImageAsset, candidate.source_asset_id)
    root = db.get(ImageAsset, candidate.project_root_id)
    run = db.get(ImageRun, candidate.run_id)
    if project is None or record is None or source is None or root is None or run is None:
        raise StudioViewError(
            "view_source_unavailable",
            "the exact Studio View lineage is unavailable",
            status_code=404,
        )
    if project.owner != created_by or record.owner != created_by:
        raise StudioViewError(
            "view_candidate_owner_mismatch",
            "only the candidate creator may resolve this View",
            status_code=403,
        )
    if (
        expected_project_id != project.root_id
        or expected_source_asset_id != source.id
        or candidate.project_root_id != project.root_id
        or candidate.source_asset_id != source.id
    ):
        raise StudioViewError(
            "view_candidate_lineage_mismatch",
            "the decision does not identify this candidate's exact project and source",
        )
    active = _active_primary(db, project.root_id)
    current_hash = hashlib.sha256(bytes(source.image)).hexdigest()
    latest_version = db.scalar(select(func.max(DesignVersion.version)).where(
        DesignVersion.design_id == root.design_id)) if root.design_id else None
    version = (
        db.get(DesignVersion, (root.design_id, candidate.design_version))
        if root.design_id else None
    )
    if ((require_active and (active is None or active.id != source.id))
            or current_hash != candidate.source_hash):
        raise StudioViewError(
            "stale_asset_revision",
            "the active visual changed while this View was under review",
        )
    if (
        expected_design_version != candidate.design_version
        or source.design_version != candidate.design_version
        or (require_active and latest_version != candidate.design_version)
        or version is None
    ):
        raise StudioViewError(
            "stale_design_version",
            "the exact specification changed while this View was under review",
        )
    exact_spec_hash = spec_visual_hash(Spec.model_validate(version.spec))
    if (
        run.project_root_id != project.root_id
        or run.source_asset_id != source.id
        or run.source_hash != current_hash
        or run.operation != "VISUAL_ONLY_EDIT"
        or run.status not in {"preview_ready", "review_required"}
        or run.created_by != created_by
        or run.spec_visual_hash != exact_spec_hash
        or run.source_spec_visual_hash != exact_spec_hash
        or candidate.spec_hash != exact_spec_hash
        or hashlib.sha256(candidate.image_bytes).hexdigest() != candidate.output_hash
        or not forced_review_candidate_qa(candidate.qa)
    ):
        raise StudioViewError(
            "view_candidate_lineage_mismatch",
            "the View is not bound to the exact source, specification, and QA evidence",
            status_code=422,
        )
    return project, root, source, run


def accept_studio_view_candidate(
    db: Session,
    candidate: StudioViewCandidate,
    *,
    expected_project_id: str,
    expected_source_asset_id: str,
    expected_design_version: int,
    created_by: str,
) -> str:
    db.scalar(select(Project).where(
        Project.root_id == candidate.project_root_id).with_for_update())
    record = _owned_record(
        db, candidate.run_id, candidate.candidate_id,
        owner=created_by, for_update=True,
    )
    if record.status == "accepted" and record.accepted_asset_id is not None:
        return record.accepted_asset_id
    if record.status != "reviewing":
        raise StudioViewError(
            "view_candidate_already_resolved",
            f"this Studio View was already {record.status}",
        )
    candidate = _candidate(record)
    project, _root, source, run = _require_exact_lineage(
        db,
        candidate,
        expected_project_id=expected_project_id,
        expected_source_asset_id=expected_source_asset_id,
        expected_design_version=expected_design_version,
        created_by=created_by,
    )
    if db.scalar(select(ImageRunReview).where(
        ImageRunReview.run_id == run.id)) is not None:
        raise StudioViewError(
            "view_candidate_resolution_conflict",
            "another decision was already saved for this Studio View",
        )
    asset = ImageAsset(
        id=new_id("ast"),
        root_id=project.root_id,
        parent_asset_id=source.id,
        design_id=None,
        design_version=candidate.design_version,
        capability="LINE_ART",
        instruction=candidate.requested_change,
        region=f"confirmed {candidate.view} Studio View",
        drift=None,
        image=candidate.image_bytes,
        media_type=candidate.media_type,
        created_by=created_by,
    )
    review = ImageRunReview(
        id=new_id("irr"), run_id=run.id, decision="accepted",
        accepted_asset_id=asset.id, created_by=created_by,
    )
    now = utcnow()
    record.status = "accepted"
    record.image = b""
    record.accepted_asset_id = asset.id
    record.review_id = review.id
    record.resolved_at = now
    project.updated_at = now
    db.add_all([asset, review])
    if candidate.studio_job_id is not None:
        try:
            record_accepted_studio_job_outputs(
                db,
                job_id=candidate.studio_job_id,
                owner=created_by,
                completed_outputs=1,
                active_design_id=project.root_id,
                source_revision_id=source.id,
            )
        except StudioJobAccountingError as exc:
            db.rollback()
            raise StudioViewError("view_job_resolution_conflict", str(exc)) from exc
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise StudioViewError(
            "view_candidate_resolution_conflict",
            "another decision was already saved for this Studio View",
        ) from exc
    return asset.id


def discard_studio_view_candidate(
    db: Session,
    candidate: StudioViewCandidate,
    *,
    expected_project_id: str,
    expected_source_asset_id: str,
    expected_design_version: int,
    created_by: str,
) -> None:
    db.scalar(select(Project).where(
        Project.root_id == candidate.project_root_id).with_for_update())
    record = _owned_record(
        db, candidate.run_id, candidate.candidate_id,
        owner=created_by, for_update=True,
    )
    if record.status == "discarded":
        return
    if record.status != "reviewing":
        raise StudioViewError(
            "view_candidate_already_resolved",
            f"this Studio View was already {record.status}",
        )
    candidate = _candidate(record)
    _project, _root, _source, run = _require_exact_lineage(
        db,
        candidate,
        expected_project_id=expected_project_id,
        expected_source_asset_id=expected_source_asset_id,
        expected_design_version=expected_design_version,
        created_by=created_by,
        require_active=False,
    )
    if db.scalar(select(ImageRunReview).where(
        ImageRunReview.run_id == run.id)) is not None:
        raise StudioViewError(
            "view_candidate_resolution_conflict",
            "another decision was already saved for this Studio View",
        )
    review = ImageRunReview(
        id=new_id("irr"), run_id=run.id, decision="rejected",
        accepted_asset_id=None, created_by=created_by,
    )
    now = utcnow()
    record.status = "discarded"
    record.image = b""
    record.review_id = review.id
    record.resolved_at = now
    db.add(review)
    if candidate.studio_job_id is not None:
        job = db.get(StudioJobRecord, candidate.studio_job_id)
        if job is None or job.owner != created_by:
            db.rollback()
            raise StudioViewError(
                "view_job_unavailable", "the Studio View job is unavailable",
                status_code=404,
            )
        job.status = "canceled"
        job.progress = 1
        job.completed_outputs = 0
        job.charged_outputs = 0
        job.error_code = None
        job.updated_at = now
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise StudioViewError(
            "view_candidate_resolution_conflict",
            "another decision was already saved for this Studio View",
        ) from exc

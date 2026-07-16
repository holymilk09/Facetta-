"""Durable, review-only visual angle sets for selected pre-spec directions.

This workflow is deliberately separate from exact specification Views.  It
turns one selected creative visual into three temporary camera studies, then
accepts or discards the whole set in one transaction.  Accepted images are
derived ``ANGLE_VIEW`` assets; they never advance the primary revision chain.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
from typing import Literal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from facetta.candidate_qa import forced_review_candidate_qa
from facetta.db import (
    ImageAsset,
    ImageRun,
    ImageRunReview,
    Project,
    StudioJobRecord,
    StudioPresentationCandidateJobLink,
    StudioPresentationCandidateRecord,
    StudioVisualAngleCandidateRecord,
    StudioVisualAngleSetRecord,
    new_id,
    utcnow,
)
from facetta.project_backbone import is_primary_revision
from facetta.studio_jobs import (
    StudioJobAccountingError,
    record_accepted_studio_job_outputs,
    studio_job_action_definition,
)


_TTL = timedelta(hours=2)
_RESERVATION_TTL = timedelta(minutes=15)
_RESERVATION_KIND = "studio_visual"
ANGLE_VIEWS = ("front", "three_quarter", "side")

VisualAngleName = Literal["front", "three_quarter", "side"]
VisualAngleSetStatus = Literal[
    "reviewing", "accepted", "discarded", "expired",
]


class StudioVisualAngleSetUnavailable(LookupError):
    def __init__(self, detail: str, *, status_code: int = 410):
        self.status_code = status_code
        super().__init__(detail)


class StudioVisualAngleSetError(ValueError):
    def __init__(self, code: str, detail: str, *, status_code: int = 409):
        self.code = code
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


@dataclass(frozen=True, slots=True)
class PendingVisualAngle:
    run_id: str
    view: VisualAngleName
    image_bytes: bytes
    media_type: str
    requested_change: str
    qa: dict
    routing: dict


@dataclass(frozen=True, slots=True)
class StudioVisualAngleCandidate:
    candidate_id: str
    run_id: str
    view: VisualAngleName
    output_hash: str
    image_bytes: bytes
    media_type: str
    requested_change: str
    qa: dict
    routing: dict
    status: VisualAngleSetStatus
    accepted_asset_id: str | None
    review_id: str | None


@dataclass(frozen=True, slots=True)
class StudioVisualAngleSet:
    angle_set_id: str
    studio_job_id: str
    project_root_id: str
    source_asset_id: str
    source_hash: str
    created_by: str
    status: VisualAngleSetStatus
    expires_at: datetime
    candidates: tuple[StudioVisualAngleCandidate, ...]


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _candidate(record: StudioVisualAngleCandidateRecord) -> StudioVisualAngleCandidate:
    return StudioVisualAngleCandidate(
        candidate_id=record.id,
        run_id=record.image_run_id,
        view=record.view,  # type: ignore[arg-type]
        output_hash=record.output_sha256,
        image_bytes=bytes(record.image),
        media_type=record.media_type,
        requested_change=record.requested_change,
        qa=record.qa,
        routing=record.routing,
        status=record.status,  # type: ignore[arg-type]
        accepted_asset_id=record.accepted_asset_id,
        review_id=record.review_id,
    )


def _set(
    db: Session,
    record: StudioVisualAngleSetRecord,
) -> StudioVisualAngleSet:
    rows = list(db.scalars(select(StudioVisualAngleCandidateRecord).where(
        StudioVisualAngleCandidateRecord.angle_set_id == record.id,
    ).order_by(StudioVisualAngleCandidateRecord.view)))
    order = {view: index for index, view in enumerate(ANGLE_VIEWS)}
    rows.sort(key=lambda item: order.get(item.view, 99))
    return StudioVisualAngleSet(
        angle_set_id=record.id,
        studio_job_id=record.studio_job_id,
        project_root_id=record.project_root_id,
        source_asset_id=record.source_asset_id,
        source_hash=record.source_sha256,
        created_by=record.owner,
        status=record.status,  # type: ignore[arg-type]
        expires_at=_utc(record.expires_at),
        candidates=tuple(_candidate(item) for item in rows),
    )


def _angle_job(
    db: Session,
    *,
    job_id: str,
    owner: str,
    project_root_id: str,
    source_asset_id: str,
) -> StudioJobRecord:
    job = db.get(StudioJobRecord, job_id)
    canonical = studio_job_action_definition("angles")
    if job is None or job.owner != owner:
        raise StudioVisualAngleSetError(
            "visual_angle_job_unavailable",
            "the visual angle job is unavailable",
            status_code=404,
        )
    if (
        job.action_id != "angles"
        or job.lane != canonical.lane
        or job.credits_per_output != canonical.credits_per_output
        or job.requested_outputs != len(ANGLE_VIEWS)
    ):
        raise StudioVisualAngleSetError(
            "visual_angle_job_invalid",
            "visual angles require one canonical three-output Angles job",
            status_code=422,
        )
    if (
        job.active_design_id != project_root_id
        or job.source_revision_id != source_asset_id
    ):
        raise StudioVisualAngleSetError(
            "visual_angle_job_lineage_mismatch",
            "the visual angle job belongs to another selected direction",
            status_code=422,
        )
    return job


def reserve_studio_visual_angle_job(
    db: Session,
    *,
    job_id: str,
    owner: str,
    project_root_id: str,
    source_asset_id: str,
) -> None:
    """Reserve provider work without creating any canonical output."""

    job = db.scalar(select(StudioJobRecord).where(
        StudioJobRecord.id == job_id,
    ).with_for_update())
    if job is None or job.owner != owner:
        raise StudioVisualAngleSetError(
            "visual_angle_job_unavailable",
            "the visual angle job is unavailable",
            status_code=404,
        )
    _angle_job(
        db,
        job_id=job_id,
        owner=owner,
        project_root_id=project_root_id,
        source_asset_id=source_asset_id,
    )
    already_used = (
        db.scalar(select(StudioVisualAngleSetRecord.id).where(
            StudioVisualAngleSetRecord.studio_job_id == job_id,
        )) is not None
        or db.scalar(select(StudioPresentationCandidateRecord.id).where(
            StudioPresentationCandidateRecord.studio_job_id == job_id,
        )) is not None
        or db.scalar(select(StudioPresentationCandidateJobLink.candidate_id).where(
            StudioPresentationCandidateJobLink.studio_job_id == job_id,
        )) is not None
    )
    if job.status != "running" or job.reservation_kind is not None or already_used:
        raise StudioVisualAngleSetError(
            "visual_angle_job_terminal",
            f"the visual angle job cannot start from {job.status}",
        )
    job.status = "reviewing"
    job.progress = max(job.progress, 0.25)
    job.completed_outputs = 0
    job.charged_outputs = 0
    job.error_code = None
    job.reservation_kind = _RESERVATION_KIND
    job.updated_at = utcnow()
    db.commit()


def fail_reserved_studio_visual_angle_job(
    db: Session,
    *,
    job_id: str,
    owner: str,
    error_code: str,
) -> None:
    """Fail unfinished angle generation with zero completed/charged outputs."""

    job = db.scalar(select(StudioJobRecord).where(
        StudioJobRecord.id == job_id,
    ).with_for_update())
    if (
        job is None
        or job.owner != owner
        or job.status != "reviewing"
        or job.reservation_kind != _RESERVATION_KIND
    ):
        return
    if db.scalar(select(StudioVisualAngleSetRecord.id).where(
        StudioVisualAngleSetRecord.studio_job_id == job_id,
    )) is not None:
        return
    job.status = "failed"
    job.progress = 1
    job.completed_outputs = 0
    job.charged_outputs = 0
    job.error_code = error_code[:64]
    job.reservation_kind = None
    job.updated_at = utcnow()
    db.commit()


def expire_stale_studio_visual_angle_reservations(
    db: Session,
    *,
    owner: str,
    job_id: str | None = None,
) -> int:
    """Fail crash-orphaned provider reservations without charging them."""

    query = select(StudioJobRecord).where(
        StudioJobRecord.owner == owner,
        StudioJobRecord.action_id == "angles",
        StudioJobRecord.status == "reviewing",
        StudioJobRecord.reservation_kind == _RESERVATION_KIND,
        StudioJobRecord.updated_at <= utcnow() - _RESERVATION_TTL,
    )
    if job_id is not None:
        query = query.where(StudioJobRecord.id == job_id)
    jobs = list(db.scalars(query.order_by(
        StudioJobRecord.id).with_for_update()))
    expired = 0
    for job in jobs:
        if db.scalar(select(StudioVisualAngleSetRecord.id).where(
            StudioVisualAngleSetRecord.studio_job_id == job.id,
        )) is not None:
            continue
        job.status = "failed"
        job.progress = 1
        job.completed_outputs = 0
        job.charged_outputs = 0
        job.error_code = "visual_angle_reservation_expired"
        job.reservation_kind = None
        job.updated_at = utcnow()
        expired += 1
    if expired:
        db.commit()
    return expired


def store_studio_visual_angle_set(
    db: Session,
    *,
    studio_job_id: str,
    project_root_id: str,
    source_asset_id: str,
    source_hash: str,
    candidates: tuple[PendingVisualAngle, ...],
    created_by: str,
) -> StudioVisualAngleSet:
    """Persist exactly three QA-reviewable outputs as one decision group."""

    if tuple(item.view for item in candidates) != ANGLE_VIEWS:
        raise StudioVisualAngleSetError(
            "visual_angle_set_incomplete",
            "a visual angle set requires front, three-quarter, and side outputs",
            status_code=422,
        )
    if len({item.run_id for item in candidates}) != len(ANGLE_VIEWS):
        raise StudioVisualAngleSetError(
            "visual_angle_set_run_ambiguity",
            "every visual angle requires its own image-run evidence",
            status_code=422,
        )
    job = _angle_job(
        db,
        job_id=studio_job_id,
        owner=created_by,
        project_root_id=project_root_id,
        source_asset_id=source_asset_id,
    )
    if job.status != "reviewing" or job.reservation_kind != _RESERVATION_KIND:
        raise StudioVisualAngleSetError(
            "visual_angle_job_terminal",
            "the visual angle job is not holding generation authority",
        )
    for item in candidates:
        run = db.get(ImageRun, item.run_id)
        if (
            run is None
            or run.project_root_id != project_root_id
            or run.source_asset_id != source_asset_id
            or run.source_hash != source_hash
            or run.created_by != created_by
            or run.operation != "REFERENCE_RENDER"
            or run.status not in {"preview_ready", "review_required"}
            or run.source_spec_visual_hash is not None
            or not forced_review_candidate_qa(item.qa)
            or item.routing.get("run_id") != item.run_id
            or not isinstance(item.routing.get("attempt_count"), int)
            or item.routing.get("attempt_count", 0) < 1
        ):
            raise StudioVisualAngleSetError(
                "visual_angle_candidate_evidence_invalid",
                "one visual angle lacks exact source, routing, or QA evidence",
                status_code=422,
            )

    now = utcnow()
    set_record = StudioVisualAngleSetRecord(
        id=new_id("aset"),
        studio_job_id=studio_job_id,
        owner=created_by,
        project_root_id=project_root_id,
        source_asset_id=source_asset_id,
        source_sha256=source_hash,
        status="reviewing",
        created_at=now,
        expires_at=now + _TTL,
    )
    rows = [
        StudioVisualAngleCandidateRecord(
            id=new_id("cand"),
            angle_set_id=set_record.id,
            image_run_id=item.run_id,
            owner=created_by,
            project_root_id=project_root_id,
            source_asset_id=source_asset_id,
            source_sha256=source_hash,
            output_sha256=hashlib.sha256(item.image_bytes).hexdigest(),
            view=item.view,
            image=item.image_bytes,
            media_type=item.media_type,
            requested_change=item.requested_change,
            qa=item.qa,
            routing=item.routing,
            status="reviewing",
            created_at=now,
        )
        for item in candidates
    ]
    job.progress = max(job.progress, 0.9)
    job.reservation_kind = None
    job.updated_at = now
    db.add_all([set_record, *rows])
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise StudioVisualAngleSetError(
            "visual_angle_set_conflict",
            "this visual angle job already owns a review set",
        ) from exc
    return _set(db, set_record)


def _expire(db: Session, record: StudioVisualAngleSetRecord) -> None:
    now = utcnow()
    record.status = "expired"
    record.resolved_at = now
    rows = list(db.scalars(select(StudioVisualAngleCandidateRecord).where(
        StudioVisualAngleCandidateRecord.angle_set_id == record.id,
    ).with_for_update()))
    for row in rows:
        row.status = "expired"
        row.image = b""
        row.resolved_at = now
    job = db.get(StudioJobRecord, record.studio_job_id)
    if job is not None and job.status in {"running", "reviewing"}:
        job.status = "canceled"
        job.progress = 1
        job.completed_outputs = 0
        job.charged_outputs = 0
        job.error_code = None
        job.reservation_kind = None
        job.updated_at = now


def expire_stale_studio_visual_angle_sets(
    db: Session,
    *,
    owner: str,
    job_id: str | None = None,
) -> int:
    """Expire due angle decisions before Activity reports their job state."""

    query = select(StudioVisualAngleSetRecord).where(
        StudioVisualAngleSetRecord.owner == owner,
        StudioVisualAngleSetRecord.status == "reviewing",
        StudioVisualAngleSetRecord.expires_at <= utcnow(),
    )
    if job_id is not None:
        query = query.where(StudioVisualAngleSetRecord.studio_job_id == job_id)
    records = list(db.scalars(query.order_by(
        StudioVisualAngleSetRecord.id).with_for_update()))
    for record in records:
        _expire(db, record)
    if records:
        db.commit()
    return len(records)


def _owned_record(
    db: Session,
    angle_set_id: str,
    *,
    owner: str,
    for_update: bool = False,
) -> StudioVisualAngleSetRecord:
    query = select(StudioVisualAngleSetRecord).where(
        StudioVisualAngleSetRecord.id == angle_set_id,
        StudioVisualAngleSetRecord.owner == owner,
    )
    if for_update:
        query = query.with_for_update()
    record = db.scalar(query)
    if record is None:
        raise StudioVisualAngleSetUnavailable(
            "the visual angle set is unavailable", status_code=404)
    if record.status == "reviewing" and _utc(record.expires_at) <= utcnow():
        _expire(db, record)
        db.commit()
        raise StudioVisualAngleSetUnavailable(
            "the visual angle set expired before a decision")
    return record


def get_studio_visual_angle_set(
    db: Session,
    angle_set_id: str,
    *,
    owner: str,
) -> StudioVisualAngleSet:
    record = _owned_record(db, angle_set_id, owner=owner)
    if record.status == "reviewing":
        try:
            _require_exact_lineage(
                db,
                record,
                expected_project_id=record.project_root_id,
                expected_source_asset_id=record.source_asset_id,
                expected_source_sha256=record.source_sha256,
                created_by=owner,
                require_active=True,
            )
        except StudioVisualAngleSetError as exc:
            _expire(db, record)
            job = db.get(StudioJobRecord, record.studio_job_id)
            if job is not None and job.status == "canceled":
                job.status = "failed"
                job.error_code = exc.code[:64]
            db.commit()
            raise StudioVisualAngleSetUnavailable(
                "the visual angle set evidence is no longer reviewable"
            ) from exc
    return _set(db, record)


def get_studio_visual_angle_set_by_job(
    db: Session,
    studio_job_id: str,
    *,
    owner: str,
) -> StudioVisualAngleSet:
    """Resume one owned angle decision from durable Activity identity."""

    record_id = db.scalar(select(StudioVisualAngleSetRecord.id).where(
        StudioVisualAngleSetRecord.studio_job_id == studio_job_id,
        StudioVisualAngleSetRecord.owner == owner,
    ))
    if record_id is None:
        raise StudioVisualAngleSetUnavailable(
            "the visual angle set is unavailable", status_code=404)
    return get_studio_visual_angle_set(db, record_id, owner=owner)


def _require_exact_lineage(
    db: Session,
    record: StudioVisualAngleSetRecord,
    *,
    expected_project_id: str,
    expected_source_asset_id: str,
    expected_source_sha256: str,
    created_by: str,
    require_active: bool,
) -> tuple[Project, ImageAsset, list[StudioVisualAngleCandidateRecord]]:
    project = db.scalar(select(Project).where(
        Project.root_id == record.project_root_id,
    ).with_for_update())
    source = db.get(ImageAsset, record.source_asset_id)
    root = db.get(ImageAsset, record.project_root_id)
    rows = list(db.scalars(select(StudioVisualAngleCandidateRecord).where(
        StudioVisualAngleCandidateRecord.angle_set_id == record.id,
    ).order_by(StudioVisualAngleCandidateRecord.view).with_for_update()))
    if project is None or source is None or root is None:
        raise StudioVisualAngleSetError(
            "visual_angle_source_unavailable",
            "the selected direction is unavailable",
            status_code=404,
        )
    if project.owner != created_by or record.owner != created_by:
        raise StudioVisualAngleSetError(
            "visual_angle_owner_mismatch",
            "only the angle-set creator may resolve it",
            status_code=403,
        )
    current_hash = hashlib.sha256(bytes(source.image)).hexdigest()
    if (
        expected_project_id != project.root_id
        or expected_source_asset_id != source.id
        or expected_source_sha256 != record.source_sha256
        or source.root_id != project.root_id
        or source.id != record.source_asset_id
        or current_hash != record.source_sha256
        or root.design_id is not None
        or source.design_version is not None
        or not is_primary_revision(source)
        or (require_active and project.selected_candidate_asset_id != source.id)
    ):
        raise StudioVisualAngleSetError(
            "stale_asset_revision",
            "the selected direction changed while its angles were under review",
        )
    if len(rows) != len(ANGLE_VIEWS) or {row.view for row in rows} != set(ANGLE_VIEWS):
        raise StudioVisualAngleSetError(
            "visual_angle_set_incomplete",
            "the angle set no longer contains exactly three review outputs",
            status_code=422,
        )
    job = _angle_job(
        db,
        job_id=record.studio_job_id,
        owner=created_by,
        project_root_id=project.root_id,
        source_asset_id=source.id,
    )
    if job.status not in {"reviewing", "succeeded"}:
        raise StudioVisualAngleSetError(
            "visual_angle_job_terminal",
            "the visual angle job no longer owns this decision",
        )
    for row in rows:
        run = db.get(ImageRun, row.image_run_id)
        existing_review = db.scalar(select(ImageRunReview.id).where(
            ImageRunReview.run_id == row.image_run_id,
        ))
        if (
            row.status != "reviewing"
            or run is None
            or run.project_root_id != project.root_id
            or run.source_asset_id != source.id
            or run.source_hash != current_hash
            or run.operation != "REFERENCE_RENDER"
            or run.status not in {"preview_ready", "review_required"}
            or run.created_by != created_by
            or run.source_spec_visual_hash is not None
            or hashlib.sha256(bytes(row.image)).hexdigest() != row.output_sha256
            or not forced_review_candidate_qa(row.qa)
            or row.routing.get("run_id") != row.image_run_id
            or existing_review is not None
        ):
            raise StudioVisualAngleSetError(
                "visual_angle_candidate_evidence_invalid",
                "one visual angle is not bound to exact image-run and QA evidence",
                status_code=422,
            )
    return project, source, rows


def accept_studio_visual_angle_set(
    db: Session,
    angle_set_id: str,
    *,
    expected_project_id: str,
    expected_source_asset_id: str,
    expected_source_sha256: str,
    created_by: str,
) -> tuple[str, ...]:
    """Atomically file three derived angles and charge three accepted outputs."""

    record = _owned_record(
        db, angle_set_id, owner=created_by, for_update=True)
    if record.status == "accepted":
        rows = list(db.scalars(select(StudioVisualAngleCandidateRecord).where(
            StudioVisualAngleCandidateRecord.angle_set_id == record.id,
        ).order_by(StudioVisualAngleCandidateRecord.view)))
        if len(rows) == 3 and all(row.accepted_asset_id for row in rows):
            order = {view: index for index, view in enumerate(ANGLE_VIEWS)}
            rows.sort(key=lambda item: order.get(item.view, 99))
            return tuple(row.accepted_asset_id for row in rows if row.accepted_asset_id)
        raise StudioVisualAngleSetError(
            "visual_angle_resolution_conflict",
            "the accepted angle set has incomplete asset evidence",
        )
    if record.status != "reviewing":
        raise StudioVisualAngleSetError(
            "visual_angle_set_already_resolved",
            f"the visual angle set was already {record.status}",
        )
    project, source, rows = _require_exact_lineage(
        db,
        record,
        expected_project_id=expected_project_id,
        expected_source_asset_id=expected_source_asset_id,
        expected_source_sha256=expected_source_sha256,
        created_by=created_by,
        require_active=True,
    )
    order = {view: index for index, view in enumerate(ANGLE_VIEWS)}
    rows.sort(key=lambda item: order[item.view])
    now = utcnow()
    assets: list[ImageAsset] = []
    reviews: list[ImageRunReview] = []
    for row in rows:
        asset = ImageAsset(
            id=new_id("ast"),
            root_id=project.root_id,
            parent_asset_id=source.id,
            design_id=None,
            design_version=None,
            capability="ANGLE_VIEW",
            instruction=row.requested_change,
            region=(
                f"reviewed {row.view} visual angle; "
                "presentation only, no manufacturing authority"
            ),
            drift=None,
            image=bytes(row.image),
            media_type=row.media_type,
            created_by=created_by,
            created_at=now,
        )
        review = ImageRunReview(
            id=new_id("irr"),
            run_id=row.image_run_id,
            decision="accepted",
            accepted_asset_id=asset.id,
            created_by=created_by,
        )
        row.status = "accepted"
        row.image = b""
        row.accepted_asset_id = asset.id
        row.review_id = review.id
        row.resolved_at = now
        assets.append(asset)
        reviews.append(review)
    record.status = "accepted"
    record.resolved_at = now
    project.updated_at = now
    db.add_all([*assets, *reviews])
    try:
        record_accepted_studio_job_outputs(
            db,
            job_id=record.studio_job_id,
            owner=created_by,
            completed_outputs=len(assets),
            active_design_id=project.root_id,
            source_revision_id=source.id,
        )
        db.commit()
    except (IntegrityError, StudioJobAccountingError) as exc:
        db.rollback()
        raise StudioVisualAngleSetError(
            "visual_angle_resolution_conflict",
            "the visual angle set could not be accepted atomically",
        ) from exc
    return tuple(asset.id for asset in assets)


def discard_studio_visual_angle_set(
    db: Session,
    angle_set_id: str,
    *,
    expected_project_id: str,
    expected_source_asset_id: str,
    expected_source_sha256: str,
    created_by: str,
) -> None:
    """Atomically reject all three candidates and cancel the uncharged job."""

    record = _owned_record(
        db, angle_set_id, owner=created_by, for_update=True)
    if record.status == "discarded":
        return
    if record.status != "reviewing":
        raise StudioVisualAngleSetError(
            "visual_angle_set_already_resolved",
            f"the visual angle set was already {record.status}",
        )
    _project, _source, rows = _require_exact_lineage(
        db,
        record,
        expected_project_id=expected_project_id,
        expected_source_asset_id=expected_source_asset_id,
        expected_source_sha256=expected_source_sha256,
        created_by=created_by,
        require_active=False,
    )
    now = utcnow()
    reviews: list[ImageRunReview] = []
    for row in rows:
        review = ImageRunReview(
            id=new_id("irr"),
            run_id=row.image_run_id,
            decision="rejected",
            accepted_asset_id=None,
            created_by=created_by,
        )
        row.status = "discarded"
        row.image = b""
        row.review_id = review.id
        row.resolved_at = now
        reviews.append(review)
    job = _angle_job(
        db,
        job_id=record.studio_job_id,
        owner=created_by,
        project_root_id=record.project_root_id,
        source_asset_id=record.source_asset_id,
    )
    job.status = "canceled"
    job.progress = 1
    job.completed_outputs = 0
    job.charged_outputs = 0
    job.error_code = None
    job.reservation_kind = None
    job.updated_at = now
    record.status = "discarded"
    record.resolved_at = now
    db.add_all(reviews)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise StudioVisualAngleSetError(
            "visual_angle_resolution_conflict",
            "the visual angle set could not be discarded atomically",
        ) from exc

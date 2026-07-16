"""Durable review storage for Studio pre-spec visual previews.

Candidate bytes remain outside the canonical project asset chain until the
owner explicitly applies one against the exact selected visual it started from.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
from typing import Literal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from facetta.db import (
    ImageAsset,
    ImageRun,
    PreviewCandidateRecord,
    Project,
    StudioJobRecord,
    new_id,
    utcnow,
)
from facetta.candidate_qa import reviewable_candidate_qa
from facetta.json_types import JsonObject
from facetta.studio_jobs import studio_job_action_definition


_TTL_SECONDS = 2 * 60 * 60
_JOB_RESERVATION_TTL_SECONDS = 15 * 60
_JOB_RESERVATION_KIND = "studio_visual"
_VISUAL_JOB_ACTIONS = ("refine", "vary")


def _visual_job_canonical(job: StudioJobRecord | None):
    if job is None or job.action_id not in _VISUAL_JOB_ACTIONS:
        return None
    return studio_job_action_definition(job.action_id)


class StudioVisualCandidateUnavailable(LookupError):
    """The candidate is foreign, expired, terminal, or has stale lineage."""


class StudioVisualJobError(ValueError):
    """A visual request is not bound to one canonical Activity job."""

    def __init__(self, code: str, detail: str, *, status_code: int = 409):
        self.code = code
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


@dataclass(frozen=True)
class StudioVisualCandidate:
    candidate_id: str
    run_id: str
    verdict: Literal["pass", "warn"]
    project_root_id: str
    source_asset_id: str
    expected_selected_candidate_asset_id: str
    source_hash: str
    output_hash: str
    image_bytes: bytes
    media_type: str
    requested_change: str
    scope: Literal["appearance", "marked_region"]
    qa: JsonObject
    created_by: str
    expires_at: datetime
    studio_job_id: str | None = None


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _candidate(record: PreviewCandidateRecord) -> StudioVisualCandidate:
    payload = record.payload
    return StudioVisualCandidate(
        candidate_id=record.id,
        run_id=record.image_run_id,
        verdict=payload["verdict"],
        project_root_id=record.project_root_id,
        source_asset_id=record.source_asset_id,
        expected_selected_candidate_asset_id=record.expected_active_asset_id,
        source_hash=record.source_sha256,
        output_hash=record.output_sha256,
        image_bytes=bytes(record.image),
        media_type=record.media_type,
        requested_change=payload["requested_change"],
        scope=payload["scope"],
        qa=payload["qa"],
        created_by=record.owner,
        expires_at=_utc(record.expires_at),
        studio_job_id=record.studio_job_id,
    )


def _settle_zero_output_job(
    db: Session,
    record: PreviewCandidateRecord,
    *,
    status: Literal["failed", "canceled"],
    error_code: str | None,
) -> None:
    """Settle the candidate's exact visual job without charging an output."""

    if record.studio_job_id is None:
        return
    job = db.scalar(select(StudioJobRecord).where(
        StudioJobRecord.id == record.studio_job_id,
    ).with_for_update())
    canonical = _visual_job_canonical(job)
    if (
        job is None
        or canonical is None
        or job.owner != record.owner
        or job.lane != canonical.lane
        or job.credits_per_output != canonical.credits_per_output
        or job.requested_outputs != 1
        or job.active_design_id != record.project_root_id
        or job.source_revision_id != record.source_asset_id
    ):
        raise StudioVisualCandidateUnavailable(
            "the visual preview Studio job is unavailable"
        )
    if job.completed_outputs != 0 or job.charged_outputs != 0:
        raise StudioVisualCandidateUnavailable(
            "a completed or charged Studio job cannot reject this preview"
        )
    if job.status in {"running", "reviewing"}:
        job.status = status
        job.progress = 1
        job.error_code = error_code
        job.reservation_kind = None
        job.updated_at = utcnow()
        return
    if job.status == status and job.error_code == error_code:
        return
    raise StudioVisualCandidateUnavailable(
        f"the visual preview Studio job is already {job.status}"
    )


def expire_stale_studio_visual_reservations(
    db: Session,
    *,
    owner: str | None = None,
    job_id: str | None = None,
) -> int:
    """Fail crash-orphaned visual reservations without charging an output.

    Provider work intentionally runs outside a database transaction. A process
    can therefore disappear after reserving Activity but before it stores an
    ImageRun or candidate. Activity reads and retries lazily recover only the
    exact reservation marker, only after its lease has elapsed, and only when
    no candidate was persisted.
    """

    cutoff = utcnow() - timedelta(seconds=_JOB_RESERVATION_TTL_SECONDS)
    query = select(StudioJobRecord).where(
        StudioJobRecord.action_id.in_(_VISUAL_JOB_ACTIONS),
        StudioJobRecord.status == "reviewing",
        StudioJobRecord.reservation_kind == _JOB_RESERVATION_KIND,
        StudioJobRecord.updated_at <= cutoff,
    )
    if owner is not None:
        query = query.where(StudioJobRecord.owner == owner)
    if job_id is not None:
        query = query.where(StudioJobRecord.id == job_id)
    jobs = list(db.scalars(query.order_by(StudioJobRecord.id).with_for_update()))
    expired = 0
    for job in jobs:
        candidate_id = db.scalar(select(PreviewCandidateRecord.id).where(
            PreviewCandidateRecord.studio_job_id == job.id,
        ))
        if candidate_id is not None:
            continue
        job.status = "failed"
        job.progress = 1
        job.completed_outputs = 0
        job.charged_outputs = 0
        job.error_code = "visual_preview_reservation_expired"
        job.reservation_kind = None
        job.updated_at = utcnow()
        expired += 1
    if expired:
        db.commit()
    return expired


def reserve_studio_visual_job(
    db: Session,
    *,
    job_id: str,
    owner: str,
    project_root_id: str,
    source_asset_id: str,
) -> None:
    """Claim one exact visual job before validation or provider work begins."""

    expired = expire_stale_studio_visual_reservations(
        db, owner=owner, job_id=job_id,
    )
    if expired:
        raise StudioVisualJobError(
            "visual_preview_job_reservation_expired",
            "the previous visual generation stopped before producing a reviewable output; "
            "start a new visual request",
        )

    job = db.scalar(select(StudioJobRecord).where(
        StudioJobRecord.id == job_id,
    ).with_for_update())
    canonical = _visual_job_canonical(job)
    if job is None or job.owner != owner:
        raise StudioVisualJobError(
            "visual_preview_job_unavailable",
            "the Studio visual job is unavailable",
            status_code=404,
        )
    if (
        canonical is None
        or job.lane != canonical.lane
        or job.credits_per_output != canonical.credits_per_output
        or job.requested_outputs != 1
    ):
        raise StudioVisualJobError(
            "visual_preview_job_invalid",
            "this endpoint requires a canonical one-output Studio visual job",
            status_code=422,
        )
    if job.status != "running":
        raise StudioVisualJobError(
            "visual_preview_job_terminal",
            f"the Studio visual job cannot generate from {job.status}",
        )
    if db.scalar(select(PreviewCandidateRecord.id).where(
        PreviewCandidateRecord.studio_job_id == job_id,
    )) is not None:
        raise StudioVisualJobError(
            "visual_preview_job_terminal",
            "the Studio visual job already has an output",
        )
    for field, expected in (
        ("active_design_id", project_root_id),
        ("source_revision_id", source_asset_id),
    ):
        current = getattr(job, field)
        if current is not None and current != expected:
            raise StudioVisualJobError(
                "visual_preview_job_lineage_mismatch",
                "the Studio visual job belongs to a different exact revision",
                status_code=422,
            )
        setattr(job, field, expected)
    # Reviewing is the durable server-side reservation. The candidate decision
    # endpoint now owns every later terminal transition and its billing effect.
    job.status = "reviewing"
    job.progress = max(job.progress, 0.5)
    job.error_code = None
    job.reservation_kind = _JOB_RESERVATION_KIND
    job.updated_at = utcnow()
    db.commit()


def fail_reserved_studio_visual_job(
    db: Session,
    *,
    job_id: str,
    owner: str,
    error_code: str,
) -> None:
    """Atomically preserve pending evidence and close a reserved job uncharged."""

    job = db.scalar(select(StudioJobRecord).where(
        StudioJobRecord.id == job_id,
    ).with_for_update())
    if job is None or job.owner != owner:
        db.rollback()
        raise StudioVisualJobError(
            "visual_preview_job_resolution_conflict",
            "the reserved Studio visual job cannot be failed",
        )
    if db.scalar(select(PreviewCandidateRecord.id).where(
        PreviewCandidateRecord.studio_job_id == job_id,
    )) is not None:
        db.rollback()
        raise StudioVisualJobError(
            "visual_preview_job_resolution_conflict",
            "a reviewable output already belongs to this Studio visual job",
        )
    canonical = _visual_job_canonical(job)
    if (
        canonical is None
        or job.lane != canonical.lane
        or job.credits_per_output != canonical.credits_per_output
        or job.requested_outputs != 1
        or job.completed_outputs != 0
        or job.charged_outputs != 0
    ):
        db.rollback()
        raise StudioVisualJobError(
            "visual_preview_job_resolution_conflict",
            "the reserved Studio visual job cannot be failed",
        )
    if job.status == "reviewing" and job.reservation_kind == _JOB_RESERVATION_KIND:
        job.status = "failed"
        job.progress = 1
        job.error_code = error_code[:64]
        job.reservation_kind = None
        job.updated_at = utcnow()
    elif job.status == "failed":
        # A concurrent trusted failure may have won the job CAS. Keep that
        # terminal reason, but commit any pending ImageRun/attempt evidence from
        # this request instead of rolling it back or returning a secondary 500.
        job.progress = 1
        job.reservation_kind = None
        job.updated_at = utcnow()
    else:
        db.rollback()
        raise StudioVisualJobError(
            "visual_preview_job_resolution_conflict",
            "the reserved Studio visual job cannot be failed",
        )
    db.commit()


def _expire_record(db: Session, record: PreviewCandidateRecord) -> None:
    _settle_zero_output_job(
        db, record, status="canceled", error_code=None,
    )
    record.status = "expired"
    record.image = b""
    record.resolved_at = utcnow()


def _expire(db: Session, record: PreviewCandidateRecord) -> None:
    _expire_record(db, record)
    db.commit()


def expire_stale_studio_visual_candidates(
    db: Session,
    *,
    owner: str,
    job_id: str | None = None,
) -> int:
    """Expire due, job-backed visual previews before Activity serialization."""

    query = select(PreviewCandidateRecord).where(
        PreviewCandidateRecord.owner == owner,
        PreviewCandidateRecord.kind == "studio_visual",
        PreviewCandidateRecord.status == "reviewing",
        PreviewCandidateRecord.studio_job_id.is_not(None),
        PreviewCandidateRecord.expires_at <= utcnow(),
    )
    if job_id is not None:
        query = query.where(PreviewCandidateRecord.studio_job_id == job_id)
    records = list(db.scalars(
        query.order_by(PreviewCandidateRecord.id).with_for_update()
    ))
    for record in records:
        _expire_record(db, record)
    if records:
        db.commit()
    return len(records)


def invalidate_studio_visual_candidate(
    db: Session,
    run_id: str,
    candidate_id: str,
    *,
    owner: str,
    error_code: str = "visual_preview_unavailable",
) -> bool:
    """Atomically close a stale preview and its uncharged Activity job.

    A missing, foreign, or already-terminal candidate is intentionally a
    no-op. Only the exact owned reviewing row may settle its linked visual job.
    """

    record = db.scalar(select(PreviewCandidateRecord).where(
        PreviewCandidateRecord.id == candidate_id,
        PreviewCandidateRecord.image_run_id == run_id,
        PreviewCandidateRecord.kind == "studio_visual",
        PreviewCandidateRecord.owner == owner,
    ).with_for_update())
    if record is None or record.status != "reviewing":
        return False
    _settle_zero_output_job(
        db, record, status="failed", error_code=error_code[:64],
    )
    record.status = "expired"
    record.image = b""
    record.resolved_at = utcnow()
    db.commit()
    return True


def _owned_reviewing_record(
    db: Session,
    run_id: str,
    candidate_id: str,
    *,
    owner: str,
    for_update: bool = False,
    require_active: bool = True,
) -> PreviewCandidateRecord:
    query = select(PreviewCandidateRecord).where(
        PreviewCandidateRecord.id == candidate_id,
    )
    if for_update:
        query = query.with_for_update()
    record = db.scalar(query)
    if (
        record is None
        or record.kind != "studio_visual"
        or record.image_run_id != run_id
        or record.owner != owner
    ):
        raise StudioVisualCandidateUnavailable("the visual preview is unavailable")
    if record.status != "reviewing":
        raise StudioVisualCandidateUnavailable(
            "the visual preview expired, was discarded, or was already applied"
        )
    if _utc(record.expires_at) <= utcnow():
        _expire(db, record)
        raise StudioVisualCandidateUnavailable(
            "the visual preview expired before a decision"
        )
    try:
        candidate = _candidate(record)
    except (KeyError, TypeError, ValueError) as exc:
        raise StudioVisualCandidateUnavailable(
            "the visual preview QA evidence is unavailable"
        ) from exc
    if not reviewable_candidate_qa(candidate.verdict, candidate.qa):
        raise StudioVisualCandidateUnavailable(
            "the visual preview failed or has incomplete QA evidence"
        )

    project = db.get(Project, record.project_root_id)
    source = db.get(ImageAsset, record.source_asset_id)
    run = db.get(ImageRun, record.image_run_id)
    source_hash = (
        hashlib.sha256(bytes(source.image)).hexdigest()
        if source is not None else None
    )
    output_hash = hashlib.sha256(bytes(record.image)).hexdigest()
    if (
        project is None
        or project.owner != owner
        or source is None
        or source.root_id != record.project_root_id
        or (require_active
            and project.selected_candidate_asset_id != record.expected_active_asset_id)
        or source.id != record.expected_active_asset_id
        or source_hash != record.source_sha256
        or output_hash != record.output_sha256
        or run is None
        or run.created_by != owner
        or run.project_root_id != record.project_root_id
        or run.source_asset_id != record.source_asset_id
        or run.source_hash != record.source_sha256
    ):
        raise StudioVisualCandidateUnavailable(
            "the visual preview no longer matches the exact selected source"
        )
    return record


def store_studio_visual_candidate(
    db: Session,
    *,
    run_id: str,
    verdict: Literal["pass", "warn"],
    project_root_id: str,
    source_asset_id: str,
    expected_selected_candidate_asset_id: str,
    source_hash: str,
    image_bytes: bytes,
    media_type: str,
    requested_change: str,
    scope: Literal["appearance", "marked_region"],
    qa: JsonObject,
    created_by: str,
    studio_job_id: str | None = None,
) -> StudioVisualCandidate:
    if not reviewable_candidate_qa(verdict, qa):
        raise StudioVisualCandidateUnavailable(
            "the visual preview failed or has incomplete QA evidence"
        )
    if studio_job_id is not None:
        job = db.scalar(select(StudioJobRecord).where(
            StudioJobRecord.id == studio_job_id,
        ).with_for_update())
        canonical = _visual_job_canonical(job)
        if (job is None or canonical is None or job.owner != created_by
                or job.lane != canonical.lane
                or job.credits_per_output != canonical.credits_per_output
                or job.requested_outputs != 1 or job.status != "reviewing"
                or job.reservation_kind != _JOB_RESERVATION_KIND):
            raise StudioVisualCandidateUnavailable(
                "the Studio visual job is unavailable or invalid")
        for field, expected in (("active_design_id", project_root_id),
                                ("source_revision_id", source_asset_id)):
            current = getattr(job, field)
            if current is not None and current != expected:
                raise StudioVisualCandidateUnavailable(
                    "the Studio visual job belongs to another source revision")
            setattr(job, field, expected)
    now = utcnow()
    record = PreviewCandidateRecord(
        id=new_id("cand"),
        image_run_id=run_id,
        owner=created_by,
        project_root_id=project_root_id,
        source_asset_id=source_asset_id,
        expected_active_asset_id=expected_selected_candidate_asset_id,
        expected_design_version=None,
        source_sha256=source_hash,
        output_sha256=hashlib.sha256(image_bytes).hexdigest(),
        image=image_bytes,
        media_type=media_type,
        kind="studio_visual",
        status="reviewing",
        studio_job_id=studio_job_id,
        payload={
            "verdict": verdict,
            "requested_change": requested_change,
            "scope": scope,
            "qa": qa,
        },
        created_at=now,
        expires_at=now + timedelta(seconds=_TTL_SECONDS),
    )
    db.add(record)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise StudioVisualCandidateUnavailable(
            "a visual preview already exists for this generation"
        ) from exc
    return _candidate(record)


def get_studio_visual_candidate(
    db: Session,
    run_id: str,
    candidate_id: str,
    *,
    owner: str,
    require_active: bool = True,
) -> StudioVisualCandidate:
    return _candidate(_owned_reviewing_record(
        db, run_id, candidate_id, owner=owner, require_active=require_active,
    ))


def lock_studio_visual_candidate_for_decision(
    db: Session,
    run_id: str,
    candidate_id: str,
    *,
    owner: str,
    require_active: bool = True,
) -> tuple[StudioVisualCandidate, PreviewCandidateRecord]:
    """Lock one exact candidate, optionally allowing a historical source.

    Apply callers keep the default active-source requirement.  Save as
    Variation may explicitly set ``require_active=False`` because it creates
    an independent sibling from the candidate's immutable source instead of
    advancing the active project.  Every ownership, source/candidate hash,
    run-lineage, expiry, terminal-state, and QA check remains mandatory.
    """

    record = _owned_reviewing_record(
        db, run_id, candidate_id, owner=owner, for_update=True,
        require_active=require_active,
    )
    return _candidate(record), record


def list_studio_visual_candidates(
    db: Session,
    *,
    project_root_id: str,
    owner: str,
) -> tuple[StudioVisualCandidate, ...]:
    records = list(db.scalars(
        select(PreviewCandidateRecord)
        .where(
            PreviewCandidateRecord.kind == "studio_visual",
            PreviewCandidateRecord.project_root_id == project_root_id,
            PreviewCandidateRecord.owner == owner,
            PreviewCandidateRecord.status == "reviewing",
        )
        .order_by(PreviewCandidateRecord.created_at, PreviewCandidateRecord.id)
    ))
    candidates: list[StudioVisualCandidate] = []
    for record in records:
        try:
            current = _owned_reviewing_record(
                db, record.image_run_id, record.id, owner=owner,
                require_active=False,
            )
        except StudioVisualCandidateUnavailable:
            continue
        candidates.append(_candidate(current))
    return tuple(candidates)


def resolve_studio_visual_candidate(
    db: Session,
    run_id: str,
    candidate_id: str,
    *,
    owner: str,
    status: Literal["applied", "saved_as_variation", "discarded"],
    review_id: str,
    terminal_asset_id: str | None,
    commit: bool = True,
) -> None:
    record = db.scalar(select(PreviewCandidateRecord).where(
        PreviewCandidateRecord.id == candidate_id,
        PreviewCandidateRecord.image_run_id == run_id,
        PreviewCandidateRecord.kind == "studio_visual",
        PreviewCandidateRecord.owner == owner,
        PreviewCandidateRecord.status == "reviewing",
    ).with_for_update())
    if record is None:
        raise StudioVisualCandidateUnavailable("the visual preview is unavailable")
    if status in {"applied", "saved_as_variation"} and terminal_asset_id is None:
        raise ValueError("accepted previews require a terminal asset")
    if status == "discarded":
        _settle_zero_output_job(
            db, record, status="canceled", error_code=None,
        )
    elif record.studio_job_id is not None:
        job = db.scalar(select(StudioJobRecord).where(
            StudioJobRecord.id == record.studio_job_id,
        ).with_for_update())
        if (
            job is None
            or job.owner != owner
            or job.status != "succeeded"
            or job.completed_outputs != 1
            or job.charged_outputs != 1
        ):
            raise StudioVisualCandidateUnavailable(
                "the accepted visual preview Studio job is unavailable"
            )
        job.reservation_kind = None
    record.status = status
    record.terminal_asset_id = terminal_asset_id
    record.review_id = review_id
    record.decided_by = owner
    record.resolved_at = utcnow()
    record.image = b""
    if commit:
        db.commit()
    else:
        db.flush()


def remove_studio_visual_candidate(
    db: Session,
    run_id: str,
    candidate_id: str,
    *,
    owner: str,
    review_id: str,
    terminal_asset_id: str | None = None,
    commit: bool = True,
) -> None:
    """Compatibility wrapper for callers resolving a terminal decision."""

    resolve_studio_visual_candidate(
        db,
        run_id,
        candidate_id,
        owner=owner,
        status=("applied" if terminal_asset_id is not None else "discarded"),
        review_id=review_id,
        terminal_asset_id=terminal_asset_id,
        commit=commit,
    )


def clear_studio_visual_candidates_for_tests() -> None:
    """Compatibility no-op: isolated test databases own candidate cleanup."""

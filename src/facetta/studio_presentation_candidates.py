"""Durable pre-spec presentation candidates and exact-lineage decisions.

These records deliberately live outside both the primary revision chain and
the trusted specification workflow. A saved candidate is a derived image of
one exact Studio visual; it can never create a Design, DesignVersion, project
revision, approval, or factory authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
from typing import Literal

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from facetta.candidate_qa import (
    forced_review_candidate_qa,
    reviewable_candidate_qa_payload,
)
from facetta.db import (
    DesignVersion,
    ImageAsset,
    ImageRun,
    ImageRunReview,
    Project,
    StudioJobRecord,
    StudioPresentationCandidateRecord,
    StudioPresentationCandidateJobLink,
    new_id,
    utcnow,
)
from facetta.image_identity import spec_visual_hash
from facetta.project_backbone import is_primary_revision
from facetta.spec import Spec
from facetta.json_types import JsonObject
from facetta.studio_jobs import (
    StudioJobAccountingError,
    record_accepted_studio_job_outputs,
    studio_job_action_definition,
)


_TTL = timedelta(hours=2)

PreSpecPresentationDestination = Literal["client", "marketing"]
PreSpecPresentationCapability = Literal[
    "CLIENT_BEAUTY_RENDER", "CLIENT_PRODUCT_PHOTO", "MARKETING_IMAGE",
]
PreSpecPresentationStatus = Literal[
    "reviewing", "accepted", "discarded", "expired",
]


class StudioPresentationCandidateUnavailable(LookupError):
    """The preview does not exist, is foreign, or has expired."""

    def __init__(self, detail: str, *, status_code: int = 410):
        self.status_code = status_code
        super().__init__(detail)


class StudioPresentationError(ValueError):
    def __init__(self, code: str, detail: str, *, status_code: int = 409):
        self.code = code
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


@dataclass(frozen=True)
class StudioPresentationCandidate:
    candidate_id: str
    run_id: str
    project_root_id: str
    source_asset_id: str
    expected_active_asset_id: str | None
    source_hash: str
    output_hash: str
    image_bytes: bytes
    media_type: str
    destination: PreSpecPresentationDestination
    capability: PreSpecPresentationCapability
    requested_change: str
    preset: str
    framing: str
    qa: JsonObject
    created_by: str
    status: PreSpecPresentationStatus
    design_version: int | None
    expires_at: datetime
    studio_job_id: str | None
    accepted_asset_id: str | None
    review_id: str | None


@dataclass(frozen=True)
class SavedStudioPresentation:
    project_root_id: str
    source_asset_id: str
    source_hash: str
    asset_id: str
    capability: PreSpecPresentationCapability


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _candidate(
    record: StudioPresentationCandidateRecord,
    *,
    linked_job_id: str | None = None,
) -> StudioPresentationCandidate:
    return StudioPresentationCandidate(
        candidate_id=record.id,
        run_id=record.image_run_id,
        project_root_id=record.project_root_id,
        source_asset_id=record.source_asset_id,
        expected_active_asset_id=record.expected_active_asset_id,
        source_hash=record.source_sha256,
        output_hash=record.output_sha256,
        image_bytes=bytes(record.image),
        media_type=record.media_type,
        destination=record.destination,  # type: ignore[arg-type]
        capability=record.capability,  # type: ignore[arg-type]
        requested_change=record.requested_change,
        preset=record.preset,
        framing=record.framing,
        qa=record.qa,
        created_by=record.owner,
        status=record.status,  # type: ignore[arg-type]
        design_version=record.design_version,
        expires_at=_utc(record.expires_at),
        studio_job_id=record.studio_job_id or linked_job_id,
        accepted_asset_id=record.accepted_asset_id,
        review_id=record.review_id,
    )


def _linked_job_id(
    db: Session, record: StudioPresentationCandidateRecord,
) -> str | None:
    if record.studio_job_id is not None:
        return record.studio_job_id
    return db.scalar(select(StudioPresentationCandidateJobLink.studio_job_id).where(
        StudioPresentationCandidateJobLink.candidate_id == record.id
    ))


def _exact_present_job(
    db: Session,
    record: StudioPresentationCandidateRecord,
) -> StudioJobRecord | None:
    linked_job_id = _linked_job_id(db, record)
    if linked_job_id is None:
        return None
    job = db.get(StudioJobRecord, linked_job_id)
    canonical = studio_job_action_definition("present")
    if (
        job is None
        or job.owner != record.owner
        or job.action_id != "present"
        or job.lane != canonical.lane
        or job.credits_per_output != canonical.credits_per_output
        or job.active_design_id != record.project_root_id
        or job.source_revision_id != record.source_asset_id
    ):
        return None
    if record.design_version is None:
        return job if (
            record.studio_job_id == job.id and job.requested_outputs == 1
        ) else None
    link = db.scalar(select(StudioPresentationCandidateJobLink).where(
        StudioPresentationCandidateJobLink.candidate_id == record.id,
        StudioPresentationCandidateJobLink.studio_job_id == job.id,
    ))
    if (
        link is None
        or record.studio_job_id is not None
        or not 0 <= link.output_ordinal < job.requested_outputs
    ):
        return None
    return job


def _owned_record(
    db: Session,
    run_id: str,
    candidate_id: str,
    *,
    owner: str,
    for_update: bool = False,
) -> StudioPresentationCandidateRecord:
    query = select(StudioPresentationCandidateRecord).where(
        StudioPresentationCandidateRecord.id == candidate_id
    )
    if for_update:
        query = query.with_for_update()
    record = db.scalar(query)
    if (
        record is None
        or record.image_run_id != run_id
        or record.owner != owner
    ):
        # Deliberately do not disclose another owner's candidate identity.
        raise StudioPresentationCandidateUnavailable(
            "the presentation preview is unavailable", status_code=404
        )
    if record.status == "reviewing" and _utc(record.expires_at) <= utcnow():
        _expire_record(db, record)
        db.commit()
        raise StudioPresentationCandidateUnavailable(
            "the presentation preview expired before a decision"
        )
    if record.status == "reviewing" and not _reviewable_qa(record):
        _invalidate_candidate_qa(db, record)
        db.commit()
        raise StudioPresentationCandidateUnavailable(
            "the presentation preview QA evidence is invalid"
        )
    if record.status == "reviewing" and _exact_present_job(db, record) is None:
        record.status = "expired"
        record.image = b""
        record.resolved_at = utcnow()
        db.commit()
        raise StudioPresentationCandidateUnavailable(
            "the presentation preview job binding is invalid"
        )
    return record


def _reviewable_qa(record: StudioPresentationCandidateRecord) -> bool:
    if record.design_version is None:
        return reviewable_candidate_qa_payload(record.qa)
    return forced_review_candidate_qa(record.qa)


def _invalidate_candidate_qa(
    db: Session,
    record: StudioPresentationCandidateRecord,
) -> None:
    record.status = "expired"
    record.image = b""
    record.resolved_at = utcnow()
    job = _exact_present_job(db, record)
    if job is None:
        return
    if record.design_version is not None:
        if job.status in {"running", "reviewing"}:
            job.error_code = "presentation_candidate_qa_invalid"
            job.updated_at = utcnow()
            _settle_exact_present_job(
                db, job_id=job.id, owner=record.owner)
        return
    if job.status in {"running", "reviewing"}:
        job.status = "failed"
        job.progress = 1
        job.completed_outputs = 0
        job.charged_outputs = 0
        job.error_code = "presentation_candidate_qa_invalid"
        job.updated_at = utcnow()


def _settle_exact_present_job(
    db: Session,
    *,
    job_id: str,
    owner: str,
) -> None:
    """Finalize one multi-output Present job only after every output resolves."""

    job = db.get(StudioJobRecord, job_id)
    if job is None or job.owner != owner:
        raise StudioPresentationError(
            "presentation_job_unavailable",
            "the presentation job is unavailable",
            status_code=404,
        )
    rows = list(db.execute(select(
        StudioPresentationCandidateRecord.status,
        StudioPresentationCandidateRecord.project_root_id,
        StudioPresentationCandidateRecord.source_asset_id,
    ).join(
        StudioPresentationCandidateJobLink,
        StudioPresentationCandidateJobLink.candidate_id
        == StudioPresentationCandidateRecord.id,
    ).where(
        StudioPresentationCandidateJobLink.studio_job_id == job_id,
    )).all())
    if not rows or any(row.status == "reviewing" for row in rows):
        return
    accepted = sum(row.status == "accepted" for row in rows)
    if accepted:
        try:
            record_accepted_studio_job_outputs(
                db,
                job_id=job_id,
                owner=owner,
                completed_outputs=accepted,
                active_design_id=rows[0].project_root_id,
                source_revision_id=rows[0].source_asset_id,
            )
        except StudioJobAccountingError as exc:
            raise StudioPresentationError(
                "presentation_job_resolution_conflict", str(exc)
            ) from exc
    else:
        if job.status == "succeeded":
            raise StudioPresentationError(
                "presentation_job_resolution_conflict",
                "the presentation job already has accepted output",
            )
        qa_invalid = job.error_code == "presentation_candidate_qa_invalid"
        job.status = "failed" if qa_invalid else "canceled"
        job.progress = 1
        job.completed_outputs = 0
        job.charged_outputs = 0
        job.error_code = (
            "presentation_candidate_qa_invalid" if qa_invalid else None
        )
        job.updated_at = utcnow()


def _expire_record(
    db: Session,
    record: StudioPresentationCandidateRecord,
) -> None:
    now = utcnow()
    record.status = "expired"
    record.image = b""
    record.resolved_at = now
    job = _exact_present_job(db, record)
    if record.design_version is not None and job is not None:
        _settle_exact_present_job(db, job_id=job.id, owner=record.owner)
    elif job is not None and job.status not in {
        "succeeded", "failed", "canceled",
    }:
        job.status = "canceled"
        job.progress = 1
        job.completed_outputs = 0
        job.charged_outputs = 0
        job.error_code = None
        job.updated_at = now


def expire_stale_studio_presentation_candidates(
    db: Session,
    *,
    owner: str,
    job_id: str | None = None,
) -> int:
    """Expire due, job-backed Present previews before Activity serialization."""

    query = select(StudioPresentationCandidateRecord).where(
        StudioPresentationCandidateRecord.owner == owner,
        StudioPresentationCandidateRecord.status == "reviewing",
        StudioPresentationCandidateRecord.expires_at <= utcnow(),
    )
    if job_id is None:
        query = query.where(or_(
            StudioPresentationCandidateRecord.studio_job_id.is_not(None),
            StudioPresentationCandidateRecord.id.in_(select(
                StudioPresentationCandidateJobLink.candidate_id
            )),
        ))
    else:
        query = query.where(or_(
            StudioPresentationCandidateRecord.studio_job_id == job_id,
            StudioPresentationCandidateRecord.id.in_(select(
                StudioPresentationCandidateJobLink.candidate_id
            ).where(
                StudioPresentationCandidateJobLink.studio_job_id == job_id
            )),
        ))
    records = list(db.scalars(
        query.order_by(StudioPresentationCandidateRecord.id).with_for_update()
    ))
    for record in records:
        _expire_record(db, record)
    if records:
        db.commit()
    return len(records)


def _fail_invalid_store_job(
    db: Session,
    *,
    job: StudioJobRecord | None,
) -> None:
    if job is None:
        return
    if job.status not in {"queued", "running", "reviewing"}:
        return
    linked_records = list(db.scalars(select(
        StudioPresentationCandidateRecord,
    ).join(
        StudioPresentationCandidateJobLink,
        StudioPresentationCandidateJobLink.candidate_id
        == StudioPresentationCandidateRecord.id,
    ).where(
        StudioPresentationCandidateJobLink.studio_job_id == job.id,
        StudioPresentationCandidateRecord.status == "reviewing",
    )))
    now = utcnow()
    for linked in linked_records:
        linked.status = "expired"
        linked.image = b""
        linked.resolved_at = now
    job.status = "failed"
    job.progress = 1
    job.completed_outputs = 0
    job.charged_outputs = 0
    job.error_code = "presentation_candidate_qa_invalid"
    job.updated_at = now
    db.commit()


def _require_present_job(
    db: Session,
    *,
    job_id: str,
    owner: str,
    project_root_id: str,
    source_asset_id: str,
    output_ordinal: int | None = None,
) -> StudioJobRecord:
    job = db.get(StudioJobRecord, job_id)
    if job is None or job.owner != owner:
        raise StudioPresentationError(
            "presentation_job_unavailable",
            "the presentation job is unavailable",
            status_code=404,
        )
    canonical = studio_job_action_definition("present")
    if (
        job.action_id != "present"
        or job.lane != canonical.lane
        or job.credits_per_output != canonical.credits_per_output
        or (
            output_ordinal is None and job.requested_outputs != 1
        )
        or (
            output_ordinal is not None
            and not 0 <= output_ordinal < job.requested_outputs
        )
    ):
        raise StudioPresentationError(
            "presentation_job_invalid",
            "the Studio job is not a canonical presentation job",
            status_code=422,
        )
    if job.status not in {"queued", "running", "reviewing"}:
        raise StudioPresentationError(
            "presentation_job_terminal",
            f"the Studio job is already {job.status}",
        )
    for field, expected in (
        ("active_design_id", project_root_id),
        ("source_revision_id", source_asset_id),
    ):
        current = getattr(job, field)
        if current is not None and current != expected:
            raise StudioPresentationError(
                "presentation_job_lineage_mismatch",
                "the Studio job belongs to a different source visual",
                status_code=422,
            )
        setattr(job, field, expected)
    job.status = "reviewing"
    job.progress = max(job.progress, 0.9)
    job.updated_at = utcnow()
    return job


def reserve_studio_presentation_job(
    db: Session,
    *,
    job_id: str,
    owner: str,
    project_root_id: str,
    source_asset_id: str,
) -> None:
    """Claim one canonical Present job before any provider work begins."""
    job = db.scalar(select(StudioJobRecord).where(
        StudioJobRecord.id == job_id
    ).with_for_update())
    if job is None or job.owner != owner:
        raise StudioPresentationError(
            "presentation_job_unavailable",
            "the presentation job is unavailable",
            status_code=404,
        )
    canonical = studio_job_action_definition("present")
    if (job.action_id != "present" or job.lane != canonical.lane
            or job.credits_per_output != canonical.credits_per_output
            or job.requested_outputs != 1):
        raise StudioPresentationError(
            "presentation_job_invalid",
            "the Studio job is not a canonical one-output presentation job",
            status_code=422,
        )
    if job.status != "running":
        raise StudioPresentationError(
            "presentation_job_terminal",
            "the presentation job was already reserved or resolved",
        )
    if db.scalar(select(StudioPresentationCandidateRecord.id).where(
        StudioPresentationCandidateRecord.studio_job_id == job_id
    )) is not None:
        raise StudioPresentationError(
            "presentation_job_terminal",
            "the presentation job already has an output",
        )
    for field, expected in (
        ("active_design_id", project_root_id),
        ("source_revision_id", source_asset_id),
    ):
        current = getattr(job, field)
        if current is not None and current != expected:
            raise StudioPresentationError(
                "presentation_job_lineage_mismatch",
                "the Studio job belongs to a different source visual",
                status_code=422,
            )
        setattr(job, field, expected)
    job.status = "reviewing"
    job.progress = max(job.progress, 0.5)
    job.updated_at = utcnow()
    db.commit()


def reserve_exact_studio_presentation_job(
    db: Session,
    *,
    job_id: str,
    owner: str,
    project_root_id: str,
    source_asset_id: str,
    requested_outputs: int,
) -> None:
    """Bind an exact multi-output Present job before provider work."""

    job = db.scalar(select(StudioJobRecord).where(
        StudioJobRecord.id == job_id).with_for_update())
    canonical = studio_job_action_definition("present")
    if job is None or job.owner != owner:
        raise StudioPresentationError(
            "presentation_job_unavailable",
            "the presentation job is unavailable",
            status_code=404,
        )
    if (
        job.action_id != "present"
        or job.lane != canonical.lane
        or job.credits_per_output != canonical.credits_per_output
        or job.requested_outputs != requested_outputs
    ):
        raise StudioPresentationError(
            "presentation_job_invalid",
            "the Present job output count or pricing is not canonical",
            status_code=422,
        )
    if job.status != "running":
        raise StudioPresentationError(
            "presentation_job_terminal",
            f"the Present job cannot generate from {job.status}",
        )
    for field, expected in (
        ("active_design_id", project_root_id),
        ("source_revision_id", source_asset_id),
    ):
        current = getattr(job, field)
        if current is not None and current != expected:
            raise StudioPresentationError(
                "presentation_job_lineage_mismatch",
                "the Present job belongs to a different exact revision",
                status_code=422,
            )
        setattr(job, field, expected)
    job.updated_at = utcnow()
    db.commit()


def fail_exact_studio_presentation_job(
    db: Session, *, job_id: str, owner: str, error_code: str,
) -> None:
    job = db.scalar(select(StudioJobRecord).where(
        StudioJobRecord.id == job_id).with_for_update())
    if job is None or job.owner != owner or job.status not in {"running", "reviewing"}:
        return
    linked = db.scalar(select(func.count()).select_from(
        StudioPresentationCandidateJobLink).where(
            StudioPresentationCandidateJobLink.studio_job_id == job_id))
    if linked:
        return
    job.status = "failed"
    job.progress = 1
    job.completed_outputs = 0
    job.charged_outputs = 0
    job.error_code = error_code[:64]
    job.updated_at = utcnow()
    db.commit()


def fail_reserved_studio_presentation_job(
    db: Session,
    *,
    job_id: str,
    owner: str,
    error_code: str,
) -> None:
    """Close a provider/quality failure without creating any charge."""
    job = db.scalar(select(StudioJobRecord).where(
        StudioJobRecord.id == job_id
    ).with_for_update())
    if job is None or job.owner != owner or job.status != "reviewing":
        return
    job.status = "failed"
    job.progress = 1
    job.completed_outputs = 0
    job.charged_outputs = 0
    job.error_code = error_code[:64]
    job.updated_at = utcnow()
    db.commit()


def store_studio_presentation_candidate(
    db: Session,
    *,
    run_id: str,
    project_root_id: str,
    source_asset_id: str,
    source_hash: str,
    image_bytes: bytes,
    media_type: str,
    destination: PreSpecPresentationDestination,
    capability: PreSpecPresentationCapability,
    requested_change: str,
    preset: str,
    framing: str,
    qa: JsonObject,
    created_by: str,
    studio_job_id: str | None = None,
    design_version: int | None = None,
    output_ordinal: int | None = None,
    expected_active_asset_id: str | None = None,
) -> StudioPresentationCandidate:
    if destination == "client" and capability not in {
        "CLIENT_BEAUTY_RENDER", "CLIENT_PRODUCT_PHOTO",
    }:
        raise ValueError("client presentation capability is invalid")
    if destination == "marketing" and capability != "MARKETING_IMAGE":
        raise ValueError("marketing presentation capability is invalid")
    bound_job = None
    if studio_job_id is not None:
        bound_job = _require_present_job(
            db,
            job_id=studio_job_id,
            owner=created_by,
            project_root_id=project_root_id,
            source_asset_id=source_asset_id,
            output_ordinal=output_ordinal,
        )
    qa_is_reviewable = (
        reviewable_candidate_qa_payload(qa)
        if design_version is None
        else forced_review_candidate_qa(qa)
    )
    if not qa_is_reviewable:
        _fail_invalid_store_job(
            db,
            job=bound_job,
        )
        raise StudioPresentationError(
            "presentation_candidate_qa_invalid",
            "the presentation QA evidence is incomplete or not reviewable",
            status_code=422,
        )
    now = utcnow()
    record = StudioPresentationCandidateRecord(
        id=new_id("cand"),
        image_run_id=run_id,
        owner=created_by,
        project_root_id=project_root_id,
        source_asset_id=source_asset_id,
        expected_active_asset_id=expected_active_asset_id,
        source_sha256=source_hash,
        output_sha256=hashlib.sha256(image_bytes).hexdigest(),
        image=image_bytes,
        media_type=media_type,
        destination=destination,
        capability=capability,
        requested_change=requested_change,
        preset=preset,
        framing=framing,
        qa=qa,
        status="reviewing",
        studio_job_id=(studio_job_id if design_version is None else None),
        design_version=design_version,
        created_at=now,
        expires_at=now + _TTL,
    )
    db.add(record)
    if studio_job_id is not None and design_version is not None:
        if output_ordinal is None:
            raise StudioPresentationError(
                "presentation_job_invalid",
                "exact Present job outputs require a deterministic ordinal",
                status_code=422,
            )
        db.add(StudioPresentationCandidateJobLink(
            candidate_id=record.id,
            studio_job_id=studio_job_id,
            output_ordinal=output_ordinal,
        ))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise StudioPresentationError(
            "presentation_candidate_conflict",
            "a presentation preview already exists for this generation",
        ) from exc
    return _candidate(record, linked_job_id=studio_job_id)


def get_studio_presentation_candidate(
    db: Session,
    run_id: str,
    candidate_id: str,
    *,
    owner: str,
) -> StudioPresentationCandidate:
    record = _owned_record(db, run_id, candidate_id, owner=owner)
    return _candidate(record, linked_job_id=_linked_job_id(db, record))


def list_studio_presentation_candidates(
    db: Session,
    *,
    owner: str,
    project_root_id: str | None = None,
    status: PreSpecPresentationStatus | None = "reviewing",
) -> list[StudioPresentationCandidate]:
    query = select(StudioPresentationCandidateRecord).where(
        StudioPresentationCandidateRecord.owner == owner
    )
    if project_root_id is not None:
        query = query.where(
            StudioPresentationCandidateRecord.project_root_id == project_root_id
        )
    if status is not None:
        query = query.where(StudioPresentationCandidateRecord.status == status)
    records = list(db.scalars(query.order_by(
        StudioPresentationCandidateRecord.created_at.desc(),
        StudioPresentationCandidateRecord.id,
    )))
    candidates: list[StudioPresentationCandidate] = []
    for record in records:
        try:
            fresh = _owned_record(
                db, record.image_run_id, record.id, owner=owner)
        except StudioPresentationCandidateUnavailable:
            continue
        candidates.append(_candidate(
            fresh, linked_job_id=_linked_job_id(db, fresh)))
    return candidates


def remove_studio_presentation_candidate(
    db: Session,
    run_id: str,
    candidate_id: str,
    *,
    owner: str,
) -> None:
    """Compatibility guard: durable candidates are never removed on decision."""
    _owned_record(db, run_id, candidate_id, owner=owner)


def _require_exact_source(
    db: Session,
    candidate: StudioPresentationCandidate,
    *,
    expected_active_asset_id: str,
    expected_source_sha256: str,
    created_by: str,
    require_active: bool = True,
) -> tuple[Project, ImageAsset, ImageRun]:
    project = db.scalar(select(Project).where(
        Project.root_id == candidate.project_root_id
    ).with_for_update())
    root = db.get(ImageAsset, candidate.project_root_id)
    source = db.scalar(select(ImageAsset).where(
        ImageAsset.id == candidate.source_asset_id
    ).with_for_update())
    run = db.get(ImageRun, candidate.run_id)
    if project is None or root is None or source is None or run is None:
        raise StudioPresentationError(
            "presentation_source_unavailable",
            "the exact source visual or generation evidence is unavailable",
            status_code=404,
        )
    if project.owner != created_by or candidate.created_by != created_by:
        raise StudioPresentationError(
            "presentation_source_unavailable",
            "the exact source visual or generation evidence is unavailable",
            status_code=404,
        )
    current_hash = hashlib.sha256(bytes(source.image)).hexdigest()
    if candidate.design_version is None:
        if (
            root.design_id is not None
            or source.design_id is not None
            or source.design_version is not None
        ):
            raise StudioPresentationError(
                "presentation_requires_pre_spec_project",
                "this pre-spec route cannot resolve specification-linked work",
                status_code=422,
            )
        if (
            source.root_id != project.root_id
            or not is_primary_revision(source)
            or (require_active and project.selected_candidate_asset_id != source.id)
            or expected_active_asset_id != source.id
            or expected_source_sha256 != current_hash
            or candidate.source_hash != current_hash
        ):
            raise StudioPresentationError(
                "stale_asset_revision",
                "the selected visual changed while this presentation was under review",
            )
    else:
        chain = list(db.scalars(select(ImageAsset).where(
            ImageAsset.root_id == project.root_id,
        ).order_by(ImageAsset.created_at, ImageAsset.id)))
        chain.sort(key=lambda asset: (
            asset.id != project.root_id, asset.created_at, asset.id))
        primary = [asset for asset in chain if is_primary_revision(asset)]
        active = primary[-1] if primary else None
        latest = (
            db.scalar(select(func.max(DesignVersion.version)).where(
                DesignVersion.design_id == root.design_id))
            if root.design_id else None
        )
        version = (
            db.get(DesignVersion, (root.design_id, candidate.design_version))
            if root.design_id else None
        )
        if (
            (require_active and active is None)
            or (require_active and active is not None
                and active.id != (candidate.expected_active_asset_id or source.id))
            or expected_active_asset_id
            != (candidate.expected_active_asset_id or source.id)
            or expected_source_sha256 != current_hash
            or candidate.source_hash != current_hash
        ):
            raise StudioPresentationError(
                "stale_asset_revision",
                "the active visual changed while this presentation was under review",
            )
        if (
            source.design_version != candidate.design_version
            or (require_active and latest != candidate.design_version)
            or version is None
        ):
            raise StudioPresentationError(
                "stale_design_version",
                "the exact specification changed while this presentation was under review",
            )
        expected_spec_hash = spec_visual_hash(Spec.model_validate(version.spec))
        expected_operation = (
            "SPEC_RENDER" if candidate.capability == "CLIENT_BEAUTY_RENDER"
            else "VISUAL_ONLY_EDIT"
        )
        source_spec_ok = (
            run.source_spec_visual_hash in {None, expected_spec_hash}
            if expected_operation == "SPEC_RENDER"
            else run.source_spec_visual_hash == expected_spec_hash
        )
        if (
            run.spec_visual_hash != expected_spec_hash
            or not source_spec_ok
            or run.operation != expected_operation
        ):
            raise StudioPresentationError(
                "presentation_candidate_lineage_mismatch",
                "the presentation is not bound to the exact specification",
                status_code=422,
            )
    if (
        run.project_root_id != project.root_id
        or run.source_asset_id != source.id
        or run.source_hash != current_hash
        or (
            candidate.design_version is None
            and run.operation != "REFERENCE_RENDER"
        )
        or run.created_by != created_by
        or run.status not in {"preview_ready", "review_required"}
        or hashlib.sha256(candidate.image_bytes).hexdigest() != candidate.output_hash
        or not (
            reviewable_candidate_qa_payload(candidate.qa)
            if candidate.design_version is None
            else forced_review_candidate_qa(candidate.qa)
        )
    ):
        raise StudioPresentationError(
            "presentation_candidate_lineage_mismatch",
            "the presentation is not bound to the exact selected source visual",
            status_code=422,
        )
    return project, source, run


def _resolved_acceptance(
    db: Session,
    candidate: StudioPresentationCandidate,
) -> SavedStudioPresentation:
    if candidate.accepted_asset_id is None:
        raise StudioPresentationError(
            "presentation_candidate_resolution_conflict",
            "this presentation received a different final decision",
        )
    asset = db.get(ImageAsset, candidate.accepted_asset_id)
    if asset is None:
        raise StudioPresentationError(
            "presentation_source_unavailable",
            "the saved presentation is unavailable",
            status_code=404,
        )
    return SavedStudioPresentation(
        project_root_id=candidate.project_root_id,
        source_asset_id=candidate.source_asset_id,
        source_hash=candidate.source_hash,
        asset_id=asset.id,
        capability=candidate.capability,
    )


def accept_studio_presentation_candidate(
    db: Session,
    candidate: StudioPresentationCandidate,
    *,
    expected_active_asset_id: str,
    expected_source_sha256: str,
    created_by: str,
) -> SavedStudioPresentation:
    """Atomically persist the derived image, decision, and accepted charge."""
    if (
        expected_active_asset_id
        != (candidate.expected_active_asset_id or candidate.source_asset_id)
        or expected_source_sha256 != candidate.source_hash
    ):
        raise StudioPresentationError(
            "stale_asset_revision",
            "the decision does not identify this candidate's exact source visual",
        )
    db.scalar(select(Project).where(
        Project.root_id == candidate.project_root_id).with_for_update())
    record = _owned_record(
        db, candidate.run_id, candidate.candidate_id,
        owner=created_by, for_update=True,
    )
    candidate = _candidate(
        record, linked_job_id=_linked_job_id(db, record))
    if candidate.status == "accepted":
        return _resolved_acceptance(db, candidate)
    if candidate.status != "reviewing":
        raise StudioPresentationError(
            "presentation_candidate_already_resolved",
            f"this presentation was already {candidate.status}",
        )
    project, source, _run = _require_exact_source(
        db,
        candidate,
        expected_active_asset_id=expected_active_asset_id,
        expected_source_sha256=expected_source_sha256,
        created_by=created_by,
    )
    existing = db.scalar(select(ImageRunReview).where(
        ImageRunReview.run_id == candidate.run_id,
    ))
    if existing is not None:
        raise StudioPresentationError(
            "presentation_candidate_resolution_conflict",
            "another decision was saved for this presentation",
        )
    asset = ImageAsset(
        id=new_id("ast"),
        root_id=project.root_id,
        parent_asset_id=source.id,
        design_id=None,
        design_version=candidate.design_version,
        capability=candidate.capability,
        instruction=candidate.requested_change,
        region=f"{candidate.destination} presentation; jewelry design frozen",
        drift=None,
        image=candidate.image_bytes,
        media_type=candidate.media_type,
        created_by=created_by,
        created_at=utcnow(),
    )
    review = ImageRunReview(
        id=new_id("irr"),
        run_id=candidate.run_id,
        decision="accepted",
        accepted_asset_id=asset.id,
        created_by=created_by,
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
            if candidate.design_version is None:
                record_accepted_studio_job_outputs(
                    db,
                    job_id=candidate.studio_job_id,
                    owner=created_by,
                    completed_outputs=1,
                    active_design_id=project.root_id,
                    source_revision_id=source.id,
                )
            else:
                _settle_exact_present_job(
                    db, job_id=candidate.studio_job_id, owner=created_by)
        except (StudioJobAccountingError, StudioPresentationError) as exc:
            db.rollback()
            if isinstance(exc, StudioPresentationError):
                raise
            raise StudioPresentationError(
                "presentation_job_resolution_conflict", str(exc)
            ) from exc
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise StudioPresentationError(
            "presentation_candidate_resolution_conflict",
            "another decision was saved for this presentation",
        ) from exc
    return SavedStudioPresentation(
        project_root_id=project.root_id,
        source_asset_id=source.id,
        source_hash=candidate.source_hash,
        asset_id=asset.id,
        capability=candidate.capability,
    )


def discard_studio_presentation_candidate(
    db: Session,
    candidate: StudioPresentationCandidate,
    *,
    expected_active_asset_id: str,
    expected_source_sha256: str,
    created_by: str,
) -> None:
    """Atomically persist rejection and cancel any bound uncharged job."""
    if (
        expected_active_asset_id
        != (candidate.expected_active_asset_id or candidate.source_asset_id)
        or expected_source_sha256 != candidate.source_hash
    ):
        raise StudioPresentationError(
            "stale_asset_revision",
            "the decision does not identify this candidate's exact source visual",
        )
    db.scalar(select(Project).where(
        Project.root_id == candidate.project_root_id).with_for_update())
    record = _owned_record(
        db, candidate.run_id, candidate.candidate_id,
        owner=created_by, for_update=True,
    )
    candidate = _candidate(
        record, linked_job_id=_linked_job_id(db, record))
    if candidate.status == "discarded":
        return
    if candidate.status != "reviewing":
        raise StudioPresentationError(
            "presentation_candidate_already_resolved",
            f"this presentation was already {candidate.status}",
        )
    _require_exact_source(
        db,
        candidate,
        expected_active_asset_id=expected_active_asset_id,
        expected_source_sha256=expected_source_sha256,
        created_by=created_by,
        require_active=False,
    )
    existing = db.scalar(select(ImageRunReview).where(
        ImageRunReview.run_id == candidate.run_id,
    ))
    if existing is not None:
        raise StudioPresentationError(
            "presentation_candidate_resolution_conflict",
            "another decision was saved for this presentation",
        )
    review = ImageRunReview(
        id=new_id("irr"),
        run_id=candidate.run_id,
        decision="rejected",
        accepted_asset_id=None,
        created_by=created_by,
    )
    now = utcnow()
    record.status = "discarded"
    record.image = b""
    record.review_id = review.id
    record.resolved_at = now
    db.add(review)
    if candidate.studio_job_id is not None and candidate.design_version is not None:
        _settle_exact_present_job(
            db, job_id=candidate.studio_job_id, owner=created_by)
    elif candidate.studio_job_id is not None:
        job = db.get(StudioJobRecord, candidate.studio_job_id)
        if job is None or job.owner != created_by:
            db.rollback()
            raise StudioPresentationError(
                "presentation_job_unavailable",
                "the presentation job is unavailable",
                status_code=404,
            )
        if job.status == "succeeded":
            db.rollback()
            raise StudioPresentationError(
                "presentation_job_resolution_conflict",
                "the presentation job already has an accepted output",
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
        raise StudioPresentationError(
            "presentation_candidate_resolution_conflict",
            "another decision was saved for this presentation",
        ) from exc


def clear_studio_presentation_candidates_for_tests() -> None:
    """Retained as a no-op for old tests; durable state belongs to the test DB."""

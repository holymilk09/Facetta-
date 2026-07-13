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
from facetta.json_types import JsonObject
from facetta.studio_jobs import studio_job_action_definition


_TTL_SECONDS = 2 * 60 * 60


class StudioVisualCandidateUnavailable(LookupError):
    """The candidate is foreign, expired, terminal, or has stale lineage."""


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


def _expire(db: Session, record: PreviewCandidateRecord) -> None:
    record.status = "expired"
    record.image = b""
    record.resolved_at = utcnow()
    db.commit()


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
    if studio_job_id is not None:
        job = db.get(StudioJobRecord, studio_job_id)
        canonical = studio_job_action_definition("refine")
        if (job is None or job.owner != created_by or job.action_id != "refine"
                or job.lane != canonical.lane
                or job.credits_per_output != canonical.credits_per_output
                or job.requested_outputs != 1 or job.status != "running"):
            raise StudioVisualCandidateUnavailable(
                "the Studio Refine job is unavailable or invalid")
        for field, expected in (("active_design_id", project_root_id),
                                ("source_revision_id", source_asset_id)):
            current = getattr(job, field)
            if current is not None and current != expected:
                raise StudioVisualCandidateUnavailable(
                    "the Studio Refine job belongs to another source revision")
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
) -> tuple[StudioVisualCandidate, PreviewCandidateRecord]:
    record = _owned_reviewing_record(
        db, run_id, candidate_id, owner=owner, for_update=True,
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

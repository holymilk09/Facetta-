"""Restart-safe exact Refine candidates and atomic terminal decisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
from time import monotonic

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from facetta.db import (
    DesignVersion,
    ImageAsset,
    ImageRun,
    Project,
    ProjectRevisionRecord,
    StudioJobRecord,
    StudioMarkupCandidateRecord,
    new_id,
    utcnow,
)
from facetta.image_identity import spec_visual_hash
from facetta.project_backbone import is_primary_revision
from facetta.spec import Spec
from facetta.specdiff import summarize_changes
from facetta.studio_jobs import (
    StudioJobAccountingError,
    record_accepted_studio_job_outputs,
    studio_job_action_definition,
)
from facetta.trusted_revision import (
    WarningRevisionError,
    accept_warning_revision,
    discard_warning_revision,
)
from facetta.warning_candidates import MarkupWarningCandidate


_TTL = timedelta(hours=2)


class StudioMarkupCandidateUnavailable(LookupError):
    def __init__(self, detail: str, *, status_code: int = 410):
        self.status_code = status_code
        super().__init__(detail)


class StudioMarkupError(ValueError):
    def __init__(self, code: str, detail: str, *, status_code: int = 409):
        self.code = code
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


@dataclass(frozen=True)
class StudioMarkupCandidate:
    candidate_id: str
    run_id: str
    project_root_id: str
    source_asset_id: str
    expected_active_asset_id: str
    design_version: int
    source_hash: str
    output_hash: str
    source_spec_hash: str
    target_spec_hash: str
    image_bytes: bytes
    media_type: str
    operation: str
    asset_capability: str
    requested_change: str
    region_description: str
    drift: float | None
    next_spec: Spec | None
    ignored_fields: tuple[str, ...]
    qa: dict
    routing: dict
    created_by: str
    reserved_asset_id: str | None
    status: str
    expires_at: datetime
    studio_job_id: str | None
    terminal_asset_id: str | None
    review_id: str | None

    def as_warning_candidate(self) -> MarkupWarningCandidate:
        return MarkupWarningCandidate(
            candidate_id=self.candidate_id,
            run_id=self.run_id,
            project_root_id=self.project_root_id,
            source_asset_id=self.source_asset_id,
            expected_active_asset_id=self.expected_active_asset_id,
            reserved_asset_id=self.reserved_asset_id,
            expected_design_version=self.design_version,
            image_bytes=self.image_bytes,
            media_type=self.media_type,
            operation=self.operation,
            asset_capability=self.asset_capability,
            requested_change=self.requested_change,
            region_description=self.region_description,
            drift=self.drift,
            next_spec=self.next_spec,
            ignored_fields=self.ignored_fields,
            qa=self.qa,
            routing=self.routing,
            created_by=self.created_by,
            # The durable UTC expiry is authoritative. The compatibility
            # object is consumed synchronously and never enters the old cache.
            expires_at=monotonic() + 60,
        )


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _candidate(record: StudioMarkupCandidateRecord) -> StudioMarkupCandidate:
    payload = record.payload
    raw_spec = payload.get("next_spec")
    return StudioMarkupCandidate(
        candidate_id=record.id,
        run_id=record.image_run_id,
        project_root_id=record.project_root_id,
        source_asset_id=record.source_asset_id,
        expected_active_asset_id=record.expected_active_asset_id,
        design_version=record.design_version,
        source_hash=record.source_sha256,
        output_hash=record.output_sha256,
        source_spec_hash=record.source_spec_visual_hash,
        target_spec_hash=record.target_spec_visual_hash,
        image_bytes=bytes(record.image),
        media_type=record.media_type,
        operation=record.operation,
        asset_capability=record.asset_capability,
        requested_change=record.requested_change,
        region_description=record.region_description,
        drift=payload.get("drift"),
        next_spec=Spec.model_validate(raw_spec) if raw_spec is not None else None,
        ignored_fields=tuple(payload.get("ignored_fields", ())),
        qa=payload.get("qa", {}),
        routing=payload.get("routing", {}),
        created_by=record.owner,
        reserved_asset_id=payload.get("reserved_asset_id"),
        status=record.status,
        expires_at=_utc(record.expires_at),
        studio_job_id=record.studio_job_id,
        terminal_asset_id=record.terminal_asset_id,
        review_id=record.review_id,
    )


def _active_primary(db: Session, root_id: str) -> ImageAsset | None:
    rows = list(db.scalars(select(ImageAsset).where(
        ImageAsset.root_id == root_id,
    ).order_by(ImageAsset.created_at, ImageAsset.id)))
    rows.sort(key=lambda asset: (asset.id != root_id, asset.created_at, asset.id))
    primary = [asset for asset in rows if is_primary_revision(asset)]
    return primary[-1] if primary else None


def _reviewable(qa: dict) -> bool:
    if qa.get("verdict") == "fail":
        return False
    checks = qa.get("checks")
    return not (isinstance(checks, list) and any(
        isinstance(check, dict)
        and check.get("passed") is False
        and check.get("severity") == "hard"
        for check in checks
    ))


def _bind_refine_job(
    db: Session,
    *,
    job_id: str,
    owner: str,
    project_root_id: str,
    source_asset_id: str,
) -> None:
    job = db.scalar(select(StudioJobRecord).where(
        StudioJobRecord.id == job_id).with_for_update())
    canonical = studio_job_action_definition("refine")
    if job is None or job.owner != owner:
        raise StudioMarkupError(
            "markup_job_unavailable", "the Studio Refine job is unavailable",
            status_code=404,
        )
    if (
        job.action_id != "refine"
        or job.lane != canonical.lane
        or job.credits_per_output != canonical.credits_per_output
        or job.requested_outputs != 1
    ):
        raise StudioMarkupError(
            "markup_job_invalid",
            "this candidate requires a canonical one-output Studio Refine job",
            status_code=422,
        )
    if job.status not in {"running", "reviewing"}:
        raise StudioMarkupError(
            "markup_job_terminal", f"the Studio Refine job is already {job.status}",
        )
    for field, expected in (
        ("active_design_id", project_root_id),
        ("source_revision_id", source_asset_id),
    ):
        current = getattr(job, field)
        if current is not None and current != expected:
            raise StudioMarkupError(
                "markup_job_lineage_mismatch",
                "the Studio Refine job belongs to another exact revision",
                status_code=422,
            )
        setattr(job, field, expected)
    job.status = "reviewing"
    job.progress = max(job.progress, 0.9)
    job.updated_at = utcnow()


def store_studio_markup_candidate(
    db: Session,
    candidate: MarkupWarningCandidate,
    *,
    studio_job_id: str | None = None,
) -> StudioMarkupCandidate:
    source = db.get(ImageAsset, candidate.source_asset_id)
    root = db.get(ImageAsset, candidate.project_root_id)
    run = db.get(ImageRun, candidate.run_id)
    project = db.get(Project, candidate.project_root_id)
    version = (
        db.get(DesignVersion, (root.design_id, candidate.expected_design_version))
        if root is not None and root.design_id is not None else None
    )
    if source is None or root is None or run is None or project is None or version is None:
        raise StudioMarkupError(
            "markup_candidate_lineage_unavailable",
            "the exact project, source, run, or specification is unavailable",
            status_code=404,
        )
    source_hash = hashlib.sha256(bytes(source.image)).hexdigest()
    source_spec_hash = spec_visual_hash(Spec.model_validate(version.spec))
    target_spec_hash = spec_visual_hash(candidate.next_spec or Spec.model_validate(version.spec))
    if (
        candidate.promotion_kind != "standard"
        or project.owner != candidate.created_by
        or source.root_id != project.root_id
        or candidate.expected_active_asset_id != source.id
        or source.design_version != candidate.expected_design_version
        or run.project_root_id != project.root_id
        or run.source_asset_id != source.id
        or run.source_hash != source_hash
        or run.created_by != candidate.created_by
        or run.status != "review_required"
        or run.spec_visual_hash != target_spec_hash
        or run.source_spec_visual_hash not in {None, source_spec_hash}
        or not _reviewable(candidate.qa)
    ):
        raise StudioMarkupError(
            "markup_candidate_lineage_invalid",
            "the candidate is not bound to the exact source, spec, run, and QA evidence",
            status_code=422,
        )
    if studio_job_id is not None:
        _bind_refine_job(
            db,
            job_id=studio_job_id,
            owner=candidate.created_by,
            project_root_id=project.root_id,
            source_asset_id=source.id,
        )
    now = utcnow()
    record = StudioMarkupCandidateRecord(
        id=candidate.candidate_id,
        image_run_id=candidate.run_id,
        owner=candidate.created_by,
        project_root_id=project.root_id,
        source_asset_id=source.id,
        expected_active_asset_id=candidate.expected_active_asset_id,
        design_version=candidate.expected_design_version,
        source_sha256=source_hash,
        output_sha256=hashlib.sha256(candidate.image_bytes).hexdigest(),
        source_spec_visual_hash=source_spec_hash,
        target_spec_visual_hash=target_spec_hash,
        image=candidate.image_bytes,
        media_type=candidate.media_type,
        operation=candidate.operation,
        asset_capability=candidate.asset_capability,
        requested_change=candidate.requested_change,
        region_description=candidate.region_description,
        payload={
            "drift": candidate.drift,
            "next_spec": (
                candidate.next_spec.model_dump(mode="json")
                if candidate.next_spec is not None else None
            ),
            "ignored_fields": list(candidate.ignored_fields),
            "qa": candidate.qa,
            "routing": candidate.routing,
            "reserved_asset_id": candidate.reserved_asset_id,
        },
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
        raise StudioMarkupError(
            "markup_candidate_conflict",
            "a durable markup candidate already exists for this generation",
        ) from exc
    return _candidate(record)


def _owned_record(
    db: Session,
    run_id: str,
    candidate_id: str,
    *,
    owner: str,
    for_update: bool = False,
) -> StudioMarkupCandidateRecord:
    query = select(StudioMarkupCandidateRecord).where(
        StudioMarkupCandidateRecord.id == candidate_id,
        StudioMarkupCandidateRecord.image_run_id == run_id,
        StudioMarkupCandidateRecord.owner == owner,
    )
    if for_update:
        query = query.with_for_update()
    record = db.scalar(query)
    if record is None:
        raise StudioMarkupCandidateUnavailable(
            "the Studio markup candidate is unavailable", status_code=404)
    if record.status == "reviewing" and _utc(record.expires_at) <= utcnow():
        record.status = "expired"
        record.image = b""
        record.resolved_at = utcnow()
        if record.studio_job_id is not None:
            job = db.get(StudioJobRecord, record.studio_job_id)
            if job is not None and job.status in {"running", "reviewing"}:
                job.status = "canceled"
                job.progress = 1
                job.completed_outputs = 0
                job.charged_outputs = 0
                job.error_code = None
                job.updated_at = utcnow()
        db.commit()
        raise StudioMarkupCandidateUnavailable(
            "the Studio markup candidate expired before a decision")
    return record


def get_studio_markup_candidate(
    db: Session, run_id: str, candidate_id: str, *, owner: str,
) -> StudioMarkupCandidate:
    return _candidate(_owned_record(db, run_id, candidate_id, owner=owner))


def lock_studio_markup_candidate_for_decision(
    db: Session, run_id: str, candidate_id: str, *, owner: str,
) -> tuple[StudioMarkupCandidate, StudioMarkupCandidateRecord]:
    record = _owned_record(
        db, run_id, candidate_id, owner=owner, for_update=True)
    if record.status != "reviewing":
        raise StudioMarkupCandidateUnavailable(
            f"the Studio markup candidate was already {record.status}")
    candidate = _candidate(record)
    _validate_exact_lineage(db, candidate)
    return candidate, record


def list_studio_markup_candidates(
    db: Session,
    *,
    owner: str,
    project_root_id: str | None = None,
    status: str | None = "reviewing",
) -> list[StudioMarkupCandidate]:
    query = select(StudioMarkupCandidateRecord).where(
        StudioMarkupCandidateRecord.owner == owner)
    if project_root_id is not None:
        query = query.where(
            StudioMarkupCandidateRecord.project_root_id == project_root_id)
    if status is not None:
        query = query.where(StudioMarkupCandidateRecord.status == status)
    records = list(db.scalars(query.order_by(
        StudioMarkupCandidateRecord.created_at.desc(),
        StudioMarkupCandidateRecord.id,
    )))
    result: list[StudioMarkupCandidate] = []
    for record in records:
        try:
            current = _owned_record(
                db, record.image_run_id, record.id, owner=owner)
        except StudioMarkupCandidateUnavailable:
            continue
        if status is None or current.status == status:
            result.append(_candidate(current))
    return result


def _validate_exact_lineage(
    db: Session, candidate: StudioMarkupCandidate,
) -> tuple[Project, ImageAsset, ImageRun]:
    project = db.get(Project, candidate.project_root_id)
    source = db.get(ImageAsset, candidate.source_asset_id)
    root = db.get(ImageAsset, candidate.project_root_id)
    run = db.get(ImageRun, candidate.run_id)
    active = _active_primary(db, candidate.project_root_id)
    latest = (
        db.scalar(select(func.max(DesignVersion.version)).where(
            DesignVersion.design_id == root.design_id))
        if root is not None and root.design_id is not None else None
    )
    version = (
        db.get(DesignVersion, (root.design_id, candidate.design_version))
        if root is not None and root.design_id is not None else None
    )
    source_hash = (
        hashlib.sha256(bytes(source.image)).hexdigest()
        if source is not None else None
    )
    source_spec_hash = (
        spec_visual_hash(Spec.model_validate(version.spec))
        if version is not None else None
    )
    target_spec_hash = spec_visual_hash(candidate.next_spec or Spec.model_validate(
        version.spec)) if version is not None else None
    if (
        project is None or source is None or run is None or active is None
        or project.owner != candidate.created_by
        or source.id != candidate.expected_active_asset_id
        or active.id != source.id
        or source.design_version != candidate.design_version
        or latest != candidate.design_version
        or source_hash != candidate.source_hash
        or hashlib.sha256(candidate.image_bytes).hexdigest() != candidate.output_hash
        or source_spec_hash != candidate.source_spec_hash
        or target_spec_hash != candidate.target_spec_hash
        or run.project_root_id != project.root_id
        or run.source_asset_id != source.id
        or run.source_hash != source_hash
        or run.created_by != candidate.created_by
        or run.status != "review_required"
        or run.spec_visual_hash != candidate.target_spec_hash
        or run.source_spec_visual_hash not in {None, candidate.source_spec_hash}
        or not _reviewable(candidate.qa)
    ):
        raise StudioMarkupError(
            "markup_candidate_lineage_mismatch",
            "the markup preview no longer matches the exact active image/spec source",
            status_code=422,
        )
    return project, source, run


def accept_studio_markup_candidate(
    db: Session,
    candidate: StudioMarkupCandidate,
    *,
    expected_active_asset_id: str,
    expected_design_version: int,
    created_by: str,
) -> str:
    db.scalar(select(Project).where(
        Project.root_id == candidate.project_root_id).with_for_update())
    record = _owned_record(
        db, candidate.run_id, candidate.candidate_id,
        owner=created_by, for_update=True,
    )
    if record.status == "applied" and record.terminal_asset_id is not None:
        return record.terminal_asset_id
    if record.status != "reviewing":
        raise StudioMarkupError(
            "markup_candidate_already_resolved",
            f"this Studio refinement was already {record.status}",
        )
    candidate = _candidate(record)
    if (
        expected_active_asset_id != candidate.source_asset_id
        or expected_design_version != candidate.design_version
    ):
        raise StudioMarkupError(
            "markup_candidate_lineage_mismatch",
            "the decision identifies another image/spec revision",
        )
    project, source, _run = _validate_exact_lineage(db, candidate)
    try:
        accepted = accept_warning_revision(
            db,
            candidate.as_warning_candidate(),
            expected_design_version=expected_design_version,
            created_by=created_by,
            commit=False,
        )
        now = utcnow()
        child = db.get(ImageAsset, accepted.asset_id)
        if child is None:
            raise StudioMarkupError(
                "markup_candidate_apply_failed",
                "the accepted refinement asset is unavailable",
                status_code=500,
            )
        revision = ProjectRevisionRecord(
            id=new_id("prr"),
            asset_id=child.id,
            action="edit",
            raw_intent={
                "kind": "studio_markup_refinement",
                "source_asset_id": source.id,
                "image_run_id": candidate.run_id,
                "instruction": candidate.requested_change,
            },
            interpretation={
                "operation": candidate.operation,
                "source_sha256": candidate.source_hash,
                "output_sha256": candidate.output_hash,
                "source_spec_visual_hash": candidate.source_spec_hash,
                "target_spec_visual_hash": candidate.target_spec_hash,
                "factory_authority": False,
            },
            change_summary=(
                summarize_changes(list(accepted.spec_change))
                or "Applied a reviewed Studio refinement."
            ),
            created_by=created_by,
            created_at=now,
        )
        project.selected_candidate_asset_id = child.id
        project.updated_at = now
        record.status = "applied"
        record.terminal_asset_id = child.id
        record.review_id = accepted.review_id
        record.decided_by = created_by
        record.resolved_at = now
        record.image = b""
        db.add(revision)
        if candidate.studio_job_id is not None:
            record_accepted_studio_job_outputs(
                db,
                job_id=candidate.studio_job_id,
                owner=created_by,
                completed_outputs=1,
                active_design_id=project.root_id,
                source_revision_id=source.id,
            )
        db.commit()
    except (IntegrityError, StudioJobAccountingError) as exc:
        db.rollback()
        raise StudioMarkupError(
            "markup_candidate_resolution_conflict",
            "another refinement decision was saved first",
        ) from exc
    except (WarningRevisionError, StudioMarkupError):
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    return accepted.asset_id


def discard_studio_markup_candidate(
    db: Session,
    candidate: StudioMarkupCandidate,
    *,
    expected_active_asset_id: str,
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
        raise StudioMarkupError(
            "markup_candidate_already_resolved",
            f"this Studio refinement was already {record.status}",
        )
    candidate = _candidate(record)
    if (
        expected_active_asset_id != candidate.source_asset_id
        or expected_design_version != candidate.design_version
    ):
        raise StudioMarkupError(
            "markup_candidate_lineage_mismatch",
            "the decision identifies another image/spec revision",
        )
    _validate_exact_lineage(db, candidate)
    try:
        discarded = discard_warning_revision(
            db,
            candidate.as_warning_candidate(),
            expected_design_version=expected_design_version,
            created_by=created_by,
            commit=False,
        )
        now = utcnow()
        record.status = "discarded"
        record.review_id = discarded.review_id
        record.decided_by = created_by
        record.resolved_at = now
        record.image = b""
        if candidate.studio_job_id is not None:
            job = db.get(StudioJobRecord, candidate.studio_job_id)
            if job is None or job.owner != created_by:
                raise StudioMarkupError(
                    "markup_job_unavailable", "the Studio Refine job is unavailable",
                    status_code=404,
                )
            job.status = "canceled"
            job.progress = 1
            job.completed_outputs = 0
            job.charged_outputs = 0
            job.error_code = None
            job.updated_at = now
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise StudioMarkupError(
            "markup_candidate_resolution_conflict",
            "another refinement decision was saved first",
        ) from exc
    except (WarningRevisionError, StudioMarkupError):
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise

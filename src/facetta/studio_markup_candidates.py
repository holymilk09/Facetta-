"""Restart-safe exact Refine candidates and atomic terminal decisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
from time import monotonic

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from facetta.candidate_qa import reviewable_candidate_qa_payload
from facetta.db import (
    DesignVersion,
    ImageAsset,
    ImageRun,
    PreviewCandidateRecord,
    Project,
    ProjectRevisionRecord,
    StudioJobRecord,
    StudioMarkupCandidateRecord,
    new_id,
    utcnow,
)
from facetta.image_identity import spec_visual_hash
from facetta.project_backbone import is_primary_revision
from facetta.revision_component_map import ComponentMapError, component_map_hash
from facetta.revision_component_map_store import load_revision_component_map
from facetta.spec import Spec
from facetta.specdiff import summarize_changes
from facetta.studio_jobs import (
    StudioJobAccountingError,
    record_accepted_studio_job_outputs,
    studio_job_action_definition,
)
from facetta.studio_preview_job_binding import (
    StudioPreviewJobBindingConflict,
    require_single_preview_job_output,
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
    source_component_map_state: str | None
    source_component_map_hash: str | None
    target_mask_hash: str | None
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
        source_component_map_state=payload.get("source_component_map_state"),
        source_component_map_hash=payload.get("source_component_map_sha256"),
        target_mask_hash=payload.get("target_mask_sha256"),
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


def _reviewable(qa: object) -> bool:
    return reviewable_candidate_qa_payload(qa)


def _source_component_map_binding(
    db: Session,
    source_asset_id: str,
) -> tuple[str, str | None]:
    """Bind review authority to the exact source's map state.

    Markup refinement may start from a revision that is explicitly unmapped,
    so absence is represented rather than invented.  If a map exists, its
    validated content hash becomes part of the durable candidate lineage.
    """

    component_map = load_revision_component_map(db, source_asset_id)
    if component_map is None:
        return "unmapped", None
    return "mapped", component_map_hash(component_map)


def _run_mask_binding_valid(run: ImageRun, expected_mask_hash: str | None) -> bool:
    intent = run.normalized_intent
    localization = intent.get("localization") if isinstance(intent, dict) else None
    intent_mask_hash = (
        localization.get("mask_hash")
        if isinstance(localization, dict) else None
    )
    if expected_mask_hash is None:
        return run.mask_hash is None and intent_mask_hash is None
    return (
        isinstance(expected_mask_hash, str)
        and len(expected_mask_hash) == 64
        and run.mask_hash == expected_mask_hash
        and intent_mask_hash == expected_mask_hash
    )


def _exact_refine_job(
    db: Session,
    record: StudioMarkupCandidateRecord,
) -> StudioJobRecord | None:
    if record.studio_job_id is None:
        return None
    job = db.get(StudioJobRecord, record.studio_job_id)
    canonical = studio_job_action_definition("refine")
    if (
        job is None
        or job.owner != record.owner
        or job.action_id != "refine"
        or job.lane != canonical.lane
        or job.credits_per_output != canonical.credits_per_output
        or job.requested_outputs != 1
        or job.active_design_id != record.project_root_id
        or job.source_revision_id != record.source_asset_id
    ):
        return None
    return job


def _fail_invalid_candidate_job(
    db: Session,
    record: StudioMarkupCandidateRecord,
) -> None:
    record.status = "expired"
    record.image = b""
    record.resolved_at = utcnow()
    job = _exact_refine_job(db, record)
    if (
        job is not None
        and job.owner == record.owner
        and job.status in {"running", "reviewing"}
    ):
        job.status = "failed"
        job.progress = 1
        job.completed_outputs = 0
        job.charged_outputs = 0
        job.error_code = "markup_candidate_qa_invalid"
        job.updated_at = utcnow()


def _fail_invalid_store_job(
    db: Session,
    *,
    job: StudioJobRecord | None,
) -> None:
    if job is None:
        return
    if job.status in {"running", "reviewing"}:
        job.status = "failed"
        job.progress = 1
        job.completed_outputs = 0
        job.charged_outputs = 0
        job.error_code = "markup_candidate_qa_invalid"
        job.updated_at = utcnow()
        db.commit()


def _bind_refine_job(
    db: Session,
    *,
    job_id: str,
    owner: str,
    project_root_id: str,
    source_asset_id: str,
    candidate_id: str,
    image_run_id: str,
) -> tuple[StudioJobRecord, StudioMarkupCandidateRecord | None]:
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
    sibling = db.scalar(select(PreviewCandidateRecord.id).where(
        PreviewCandidateRecord.studio_job_id == job_id,
    ))
    if sibling is not None or job.reservation_kind is not None:
        raise StudioMarkupError(
            "markup_job_output_conflict",
            "the Studio Refine job already owns another preview output",
        )
    existing = db.scalar(select(StudioMarkupCandidateRecord).where(
        StudioMarkupCandidateRecord.studio_job_id == job_id,
    ))
    if job.status == "reviewing":
        if (
            existing is None
            or existing.id != candidate_id
            or existing.image_run_id != image_run_id
            or existing.owner != owner
            or existing.project_root_id != project_root_id
            or existing.source_asset_id != source_asset_id
        ):
            raise StudioMarkupError(
                "markup_job_output_conflict",
                "the Studio Refine job already owns another preview output",
            )
    elif job.status != "running":
        raise StudioMarkupError(
            "markup_job_terminal", f"the Studio Refine job is already {job.status}",
        )
    elif existing is not None:
        raise StudioMarkupError(
            "markup_job_output_conflict",
            "the Studio Refine job already owns another preview output",
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
    return job, existing


def _is_exact_store_replay(
    record: StudioMarkupCandidateRecord,
    *,
    candidate: MarkupWarningCandidate,
    studio_job_id: str,
    source_hash: str,
    output_hash: str,
    source_spec_hash: str,
    target_spec_hash: str,
    payload: dict,
) -> bool:
    """Allow only a byte- and evidence-identical retry of one durable output."""

    return (
        record.status == "reviewing"
        and record.id == candidate.candidate_id
        and record.image_run_id == candidate.run_id
        and record.owner == candidate.created_by
        and record.project_root_id == candidate.project_root_id
        and record.source_asset_id == candidate.source_asset_id
        and record.expected_active_asset_id == candidate.expected_active_asset_id
        and record.design_version == candidate.expected_design_version
        and record.source_sha256 == source_hash
        and record.output_sha256 == output_hash
        and record.source_spec_visual_hash == source_spec_hash
        and record.target_spec_visual_hash == target_spec_hash
        and bytes(record.image) == candidate.image_bytes
        and record.media_type == candidate.media_type
        and record.operation == candidate.operation
        and record.asset_capability == candidate.asset_capability
        and record.requested_change == candidate.requested_change
        and record.region_description == candidate.region_description
        and record.studio_job_id == studio_job_id
        and record.payload == payload
    )


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
    try:
        source_map_state, source_map_hash = _source_component_map_binding(
            db, source.id)
    except ComponentMapError as exc:
        raise StudioMarkupError(
            "markup_candidate_lineage_invalid",
            "the exact source component-map evidence is invalid",
            status_code=422,
        ) from exc
    target_mask_hash = run.mask_hash
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
        or run.operation != candidate.operation
        or run.status != "review_required"
        or run.spec_visual_hash != target_spec_hash
        or run.source_spec_visual_hash not in {None, source_spec_hash}
        or not _run_mask_binding_valid(run, target_mask_hash)
    ):
        raise StudioMarkupError(
            "markup_candidate_lineage_invalid",
            "the candidate is not bound to the exact source, spec, run, and QA evidence",
            status_code=422,
        )
    payload = {
        "drift": candidate.drift,
        "next_spec": (
            candidate.next_spec.model_dump(mode="json")
            if candidate.next_spec is not None else None
        ),
        "ignored_fields": list(candidate.ignored_fields),
        "qa": candidate.qa,
        "routing": candidate.routing,
        "reserved_asset_id": candidate.reserved_asset_id,
        "source_component_map_state": source_map_state,
        "source_component_map_sha256": source_map_hash,
        "target_mask_sha256": target_mask_hash,
    }
    output_hash = hashlib.sha256(candidate.image_bytes).hexdigest()
    bound_job = None
    existing = None
    if studio_job_id is not None:
        bound_job, existing = _bind_refine_job(
            db,
            job_id=studio_job_id,
            owner=candidate.created_by,
            project_root_id=project.root_id,
            source_asset_id=source.id,
            candidate_id=candidate.candidate_id,
            image_run_id=candidate.run_id,
        )
    if not _reviewable(candidate.qa):
        if existing is None:
            _fail_invalid_store_job(db, job=bound_job)
        raise StudioMarkupError(
            "markup_candidate_qa_invalid",
            "the candidate QA evidence is incomplete or not reviewable",
            status_code=422,
        )
    if existing is not None:
        if _is_exact_store_replay(
            existing,
            candidate=candidate,
            studio_job_id=studio_job_id,
            source_hash=source_hash,
            output_hash=output_hash,
            source_spec_hash=source_spec_hash,
            target_spec_hash=target_spec_hash,
            payload=payload,
        ):
            return _candidate(existing)
        raise StudioMarkupError(
            "markup_candidate_conflict",
            "the existing Studio markup candidate does not match this replay",
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
        output_sha256=output_hash,
        source_spec_visual_hash=source_spec_hash,
        target_spec_visual_hash=target_spec_hash,
        image=candidate.image_bytes,
        media_type=candidate.media_type,
        operation=candidate.operation,
        asset_capability=candidate.asset_capability,
        requested_change=candidate.requested_change,
        region_description=candidate.region_description,
        payload=payload,
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
        _expire_record(db, record)
        db.commit()
        raise StudioMarkupCandidateUnavailable(
            "the Studio markup candidate expired before a decision")
    if record.status == "reviewing":
        if _exact_refine_job(db, record) is None:
            record.status = "expired"
            record.image = b""
            record.resolved_at = utcnow()
            db.commit()
            raise StudioMarkupCandidateUnavailable(
                "the Studio markup candidate job binding is invalid"
            )
        payload = record.payload
        qa = payload.get("qa") if isinstance(payload, dict) else None
        if not _reviewable(qa):
            _fail_invalid_candidate_job(db, record)
            db.commit()
            raise StudioMarkupCandidateUnavailable(
                "the Studio markup candidate QA evidence is invalid"
            )
    return record


def _expire_record(db: Session, record: StudioMarkupCandidateRecord) -> None:
    now = utcnow()
    record.status = "expired"
    record.image = b""
    record.resolved_at = now
    job = _exact_refine_job(db, record)
    if job is not None and job.status in {"running", "reviewing"}:
        job.status = "canceled"
        job.progress = 1
        job.completed_outputs = 0
        job.charged_outputs = 0
        job.error_code = None
        job.updated_at = now


def expire_stale_studio_markup_candidates(
    db: Session,
    *,
    owner: str,
    job_id: str | None = None,
) -> int:
    """Expire due, job-backed markup previews before Activity serialization."""

    query = select(StudioMarkupCandidateRecord).where(
        StudioMarkupCandidateRecord.owner == owner,
        StudioMarkupCandidateRecord.status == "reviewing",
        StudioMarkupCandidateRecord.studio_job_id.is_not(None),
        StudioMarkupCandidateRecord.expires_at <= utcnow(),
    )
    if job_id is not None:
        query = query.where(StudioMarkupCandidateRecord.studio_job_id == job_id)
    records = list(db.scalars(
        query.order_by(StudioMarkupCandidateRecord.id).with_for_update()
    ))
    for record in records:
        _expire_record(db, record)
    if records:
        db.commit()
    return len(records)


def get_studio_markup_candidate(
    db: Session, run_id: str, candidate_id: str, *, owner: str,
) -> StudioMarkupCandidate:
    return _candidate(_owned_record(db, run_id, candidate_id, owner=owner))


def lock_studio_markup_candidate_for_decision(
    db: Session, run_id: str, candidate_id: str, *, owner: str,
    require_active: bool = True,
) -> tuple[StudioMarkupCandidate, StudioMarkupCandidateRecord]:
    """Lock an exact candidate for one terminal decision.

    Apply callers retain the active-source requirement by default. Save as
    Variation may explicitly allow a historical immutable source because it
    creates an independent sibling and never advances the active project.
    Every other source, spec, map, mask, run, candidate, job, and QA binding
    remains mandatory.
    """

    record = _owned_record(
        db, run_id, candidate_id, owner=owner, for_update=True)
    if record.status != "reviewing":
        raise StudioMarkupCandidateUnavailable(
            f"the Studio markup candidate was already {record.status}")
    candidate = _candidate(record)
    _validate_exact_lineage(db, candidate, require_active=require_active)
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
    db: Session, candidate: StudioMarkupCandidate, *, require_active: bool = True,
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
    try:
        current_map_state, current_map_hash = _source_component_map_binding(
            db, candidate.source_asset_id)
    except ComponentMapError:
        current_map_state, current_map_hash = "invalid", None
    if (
        project is None or source is None or run is None
        or (require_active and active is None)
        or project.owner != candidate.created_by
        or source.root_id != candidate.project_root_id
        or source.id != candidate.expected_active_asset_id
        or (require_active and active is not None and active.id != source.id)
        or source.design_version != candidate.design_version
        or (require_active and latest != candidate.design_version)
        or source_hash != candidate.source_hash
        or hashlib.sha256(candidate.image_bytes).hexdigest() != candidate.output_hash
        or source_spec_hash != candidate.source_spec_hash
        or target_spec_hash != candidate.target_spec_hash
        or current_map_state != candidate.source_component_map_state
        or current_map_hash != candidate.source_component_map_hash
        or run.project_root_id != project.root_id
        or run.source_asset_id != source.id
        or run.source_hash != source_hash
        or run.created_by != candidate.created_by
        or run.operation != candidate.operation
        or run.status != "review_required"
        or run.spec_visual_hash != candidate.target_spec_hash
        or run.source_spec_visual_hash not in {None, candidate.source_spec_hash}
        or not _run_mask_binding_valid(run, candidate.target_mask_hash)
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
    try:
        require_single_preview_job_output(
            db,
            studio_job_id=record.studio_job_id,
            expected_candidate_id=record.id,
        )
    except StudioPreviewJobBindingConflict as exc:
        raise StudioMarkupError(
            "markup_job_output_conflict", str(exc),
        ) from exc
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
    try:
        require_single_preview_job_output(
            db,
            studio_job_id=record.studio_job_id,
            expected_candidate_id=record.id,
        )
    except StudioPreviewJobBindingConflict as exc:
        raise StudioMarkupError(
            "markup_job_output_conflict", str(exc),
        ) from exc
    candidate = _candidate(record)
    if (
        expected_active_asset_id != candidate.source_asset_id
        or expected_design_version != candidate.design_version
    ):
        raise StudioMarkupError(
            "markup_candidate_lineage_mismatch",
            "the decision identifies another image/spec revision",
        )
    _validate_exact_lineage(db, candidate, require_active=False)
    try:
        discarded = discard_warning_revision(
            db,
            candidate.as_warning_candidate(),
            expected_design_version=expected_design_version,
            created_by=created_by,
            commit=False,
            require_active=False,
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

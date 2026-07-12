"""Durable catalog previews awaiting explicit Apply or Discard."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
from typing import Literal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from facetta.db import (
    DesignVersion,
    ImageAsset,
    ImageRun,
    PreviewCandidateRecord,
    Project,
    new_id,
    utcnow,
)
from facetta.image_identity import spec_visual_hash
from facetta.json_types import JsonObject
from facetta.project_backbone import is_primary_revision
from facetta.spec import Spec


_TTL_SECONDS = 2 * 60 * 60


class CatalogPreviewUnavailable(LookupError):
    """The temporary preview is foreign, terminal, expired, or stale."""


@dataclass(frozen=True)
class CatalogPreviewCandidate:
    candidate_id: str
    run_id: str
    verdict: Literal["pass", "warn"]
    project_root_id: str
    source_asset_id: str
    expected_active_asset_id: str
    expected_design_version: int
    source_hash: str
    output_hash: str
    source_spec_visual_hash: str
    target_spec_visual_hash: str
    image_bytes: bytes
    media_type: str
    requested_change: str
    region_description: str
    drift: float | None
    next_spec: Spec
    component_path: str
    option_id: str
    spec_change: tuple[JsonObject, ...]
    qa: JsonObject
    routing: JsonObject
    created_by: str
    expires_at: datetime


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _candidate(record: PreviewCandidateRecord) -> CatalogPreviewCandidate:
    payload = record.payload
    return CatalogPreviewCandidate(
        candidate_id=record.id,
        run_id=record.image_run_id,
        verdict=payload["verdict"],
        project_root_id=record.project_root_id,
        source_asset_id=record.source_asset_id,
        expected_active_asset_id=record.expected_active_asset_id,
        expected_design_version=record.expected_design_version or 0,
        source_hash=record.source_sha256,
        output_hash=record.output_sha256,
        source_spec_visual_hash=payload["source_spec_visual_hash"],
        target_spec_visual_hash=payload["target_spec_visual_hash"],
        image_bytes=bytes(record.image),
        media_type=record.media_type,
        requested_change=payload["requested_change"],
        region_description=payload["region_description"],
        drift=payload.get("drift"),
        next_spec=Spec.model_validate(payload["next_spec"]),
        component_path=payload["component_path"],
        option_id=payload["option_id"],
        spec_change=tuple(payload["spec_change"]),
        qa=payload["qa"],
        routing=payload["routing"],
        created_by=record.owner,
        expires_at=_utc(record.expires_at),
    )


def _active_primary(db: Session, root_id: str) -> ImageAsset | None:
    rows = list(db.scalars(
        select(ImageAsset)
        .where(ImageAsset.root_id == root_id)
        .order_by(ImageAsset.created_at, ImageAsset.id)
    ))
    primary = [asset for asset in rows if is_primary_revision(asset)]
    return primary[-1] if primary else None


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
) -> PreviewCandidateRecord:
    query = select(PreviewCandidateRecord).where(
        PreviewCandidateRecord.id == candidate_id,
    )
    if for_update:
        query = query.with_for_update()
    record = db.scalar(query)
    if (
        record is None
        or record.kind != "catalog_revision"
        or record.image_run_id != run_id
        or record.owner != owner
    ):
        raise CatalogPreviewUnavailable("the catalog preview is unavailable")
    if record.status != "reviewing":
        raise CatalogPreviewUnavailable(
            "the catalog preview expired, was discarded, or was already applied"
        )
    if _utc(record.expires_at) <= utcnow():
        _expire(db, record)
        raise CatalogPreviewUnavailable(
            "the catalog preview expired before a decision"
        )

    project = db.get(Project, record.project_root_id)
    source = db.get(ImageAsset, record.source_asset_id)
    root = db.get(ImageAsset, record.project_root_id)
    run = db.get(ImageRun, record.image_run_id)
    active = _active_primary(db, record.project_root_id)
    source_hash = (
        hashlib.sha256(bytes(source.image)).hexdigest()
        if source is not None else None
    )
    output_hash = hashlib.sha256(bytes(record.image)).hexdigest()
    payload = record.payload
    version = (
        db.get(DesignVersion, (root.design_id, record.expected_design_version))
        if root is not None
        and root.design_id is not None
        and record.expected_design_version is not None
        else None
    )
    source_spec_hash = (
        spec_visual_hash(Spec.model_validate(version.spec))
        if version is not None else None
    )
    target_spec_hash = spec_visual_hash(
        Spec.model_validate(payload["next_spec"])
    )
    if (
        project is None
        or project.owner != owner
        or source is None
        or source.root_id != record.project_root_id
        or active is None
        or active.id != record.expected_active_asset_id
        or source.id != record.expected_active_asset_id
        or source.design_version != record.expected_design_version
        or source_hash != record.source_sha256
        or output_hash != record.output_sha256
        or source_spec_hash != payload["source_spec_visual_hash"]
        or target_spec_hash != payload["target_spec_visual_hash"]
        or run is None
        or run.created_by != owner
        or run.project_root_id != record.project_root_id
        or run.source_asset_id != record.source_asset_id
        or run.source_hash != record.source_sha256
        or run.source_spec_visual_hash != payload["source_spec_visual_hash"]
        or run.spec_visual_hash != payload["target_spec_visual_hash"]
    ):
        raise CatalogPreviewUnavailable(
            "the catalog preview no longer matches the exact image/spec source"
        )
    return record


def store_catalog_preview_candidate(
    db: Session,
    *,
    run_id: str,
    verdict: Literal["pass", "warn"],
    project_root_id: str,
    source_asset_id: str,
    expected_active_asset_id: str,
    expected_design_version: int,
    source_hash: str,
    source_spec_visual_hash: str,
    target_spec_visual_hash: str,
    image_bytes: bytes,
    media_type: str,
    requested_change: str,
    region_description: str,
    drift: float | None,
    next_spec: Spec,
    component_path: str,
    option_id: str,
    spec_change: tuple[JsonObject, ...],
    qa: JsonObject,
    routing: JsonObject,
    created_by: str,
) -> CatalogPreviewCandidate:
    now = utcnow()
    record = PreviewCandidateRecord(
        id=new_id("cand"),
        image_run_id=run_id,
        owner=created_by,
        project_root_id=project_root_id,
        source_asset_id=source_asset_id,
        expected_active_asset_id=expected_active_asset_id,
        expected_design_version=expected_design_version,
        source_sha256=source_hash,
        output_sha256=hashlib.sha256(image_bytes).hexdigest(),
        image=image_bytes,
        media_type=media_type,
        kind="catalog_revision",
        status="reviewing",
        payload={
            "verdict": verdict,
            "source_spec_visual_hash": source_spec_visual_hash,
            "target_spec_visual_hash": target_spec_visual_hash,
            "requested_change": requested_change,
            "region_description": region_description,
            "drift": drift,
            "next_spec": next_spec.model_dump(mode="json"),
            "component_path": component_path,
            "option_id": option_id,
            "spec_change": list(spec_change),
            "qa": qa,
            "routing": routing,
        },
        created_at=now,
        expires_at=now + timedelta(seconds=_TTL_SECONDS),
    )
    db.add(record)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise CatalogPreviewUnavailable(
            "a catalog preview already exists for this generation"
        ) from exc
    return _candidate(record)


def get_catalog_preview_candidate(
    db: Session,
    run_id: str,
    candidate_id: str,
    *,
    owner: str,
) -> CatalogPreviewCandidate:
    return _candidate(_owned_reviewing_record(
        db, run_id, candidate_id, owner=owner,
    ))


def lock_catalog_preview_candidate_for_decision(
    db: Session,
    run_id: str,
    candidate_id: str,
    *,
    owner: str,
) -> tuple[CatalogPreviewCandidate, PreviewCandidateRecord]:
    record = _owned_reviewing_record(
        db, run_id, candidate_id, owner=owner, for_update=True,
    )
    return _candidate(record), record


def list_catalog_preview_candidates(
    db: Session,
    *,
    project_root_id: str,
    owner: str,
) -> tuple[CatalogPreviewCandidate, ...]:
    records = list(db.scalars(
        select(PreviewCandidateRecord)
        .where(
            PreviewCandidateRecord.kind == "catalog_revision",
            PreviewCandidateRecord.project_root_id == project_root_id,
            PreviewCandidateRecord.owner == owner,
            PreviewCandidateRecord.status == "reviewing",
        )
        .order_by(PreviewCandidateRecord.created_at, PreviewCandidateRecord.id)
    ))
    candidates: list[CatalogPreviewCandidate] = []
    for record in records:
        try:
            current = _owned_reviewing_record(
                db, record.image_run_id, record.id, owner=owner,
            )
        except CatalogPreviewUnavailable:
            continue
        candidates.append(_candidate(current))
    return tuple(candidates)


def resolve_catalog_preview_candidate(
    db: Session,
    run_id: str,
    candidate_id: str,
    *,
    owner: str,
    status: Literal["applied", "saved_as_variation", "discarded"],
    review_id: str | None = None,
    terminal_asset_id: str | None = None,
    commit: bool = True,
) -> None:
    record = db.scalar(select(PreviewCandidateRecord).where(
        PreviewCandidateRecord.id == candidate_id,
        PreviewCandidateRecord.image_run_id == run_id,
        PreviewCandidateRecord.kind == "catalog_revision",
        PreviewCandidateRecord.owner == owner,
        PreviewCandidateRecord.status == "reviewing",
    ).with_for_update())
    if record is None:
        raise CatalogPreviewUnavailable("the catalog preview is unavailable")
    if status in {"applied", "saved_as_variation"} and (
        terminal_asset_id is None or review_id is None
    ):
        raise ValueError("accepted previews require asset and review identities")
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


def discard_catalog_preview_candidate(
    db: Session,
    run_id: str,
    candidate_id: str,
    *,
    owner: str,
) -> None:
    resolve_catalog_preview_candidate(
        db, run_id, candidate_id, owner=owner, status="discarded",
    )


def clear_catalog_preview_candidates_for_tests() -> None:
    """Compatibility no-op: isolated test databases own candidate cleanup."""

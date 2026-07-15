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
    ImageAttempt,
    ImageRun,
    PreviewCandidateRecord,
    Project,
    StudioJobRecord,
    new_id,
    utcnow,
)
from facetta.image_identity import spec_visual_hash
from facetta.instant_metal_color import (
    TRANSFORM_VERSION as INSTANT_METAL_COLOR_VERSION,
    instant_input_sha256,
    transform_contract_sha256,
)
from facetta.json_types import JsonObject
from facetta.project_backbone import is_primary_revision
from facetta.revision_component_map import (
    ComponentMapError,
    RevisionComponentMap,
    bind_map_to_raster,
    component_map_hash,
    rasterize_component_masks,
)
from facetta.catalog_component_targeting import (
    STRUCTURAL_CATALOG_PATHS,
    catalog_structural_component_mapper_status,
)
from facetta.candidate_qa import reviewable_candidate_qa
from facetta.revision_component_map_store import load_revision_component_map
from facetta.spec import Spec
from facetta.studio_jobs import (
    StudioJobAccountingError,
    record_accepted_studio_job_outputs,
    studio_job_action_definition,
)
from facetta.studio_preview_job_binding import (
    StudioPreviewJobBindingConflict,
    require_single_preview_job_output,
)


_TTL_SECONDS = 2 * 60 * 60


class CatalogPreviewUnavailable(LookupError):
    """The temporary preview is foreign, terminal, expired, or stale."""


class CatalogPreviewQaInvalid(CatalogPreviewUnavailable):
    """A generated catalog output lacks self-consistent reviewable QA."""


class CatalogPreviewJobError(ValueError):
    """A temporary catalog candidate cannot bind or settle its Refine job."""


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
    component_map_sha256: str | None
    target_component_ids: tuple[str, ...]
    target_mask_sha256: str | None
    proposed_child_component_map: RevisionComponentMap | None
    studio_job_id: str | None
    transform_contract_sha256: str | None


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _validated_candidate_payload(
    record: PreviewCandidateRecord,
) -> tuple[
    JsonObject,
    Spec,
    str,
    str,
    tuple[str, ...],
    RevisionComponentMap | None,
]:
    """Parse every field a review read can expose before returning bytes.

    Candidate payloads are durable but deliberately non-canonical. A corrupt
    or partially migrated JSON document must therefore behave like failed QA:
    fail closed so the caller can expire the row and settle its linked job,
    rather than leaking a Pydantic/KeyError 500 from list, image, or Apply.
    """

    payload = record.payload
    try:
        if not isinstance(payload, dict):
            raise TypeError("candidate payload is not an object")
        verdict = payload["verdict"]
        if verdict not in {"pass", "warn"}:
            raise ValueError("candidate verdict is invalid")
        source_spec_hash = payload["source_spec_visual_hash"]
        target_spec_hash = payload["target_spec_visual_hash"]
        if not (
            isinstance(source_spec_hash, str)
            and len(source_spec_hash) == 16
            and isinstance(target_spec_hash, str)
            and len(target_spec_hash) == 16
        ):
            raise ValueError("candidate specification lineage is incomplete")
        for key in (
            "requested_change",
            "region_description",
            "component_path",
            "option_id",
        ):
            if not isinstance(payload[key], str) or not payload[key].strip():
                raise ValueError(f"candidate {key} is invalid")
        raw_changes = payload["spec_change"]
        if not isinstance(raw_changes, list) or not all(
            isinstance(change, dict) for change in raw_changes
        ):
            raise TypeError("candidate specification changes are invalid")
        if not isinstance(payload["qa"], dict) or not isinstance(
            payload["routing"], dict
        ):
            raise TypeError("candidate execution evidence is invalid")
        if not reviewable_candidate_qa(verdict, payload["qa"]):
            raise ValueError("candidate QA evidence is not reviewable")
        drift = payload.get("drift")
        if drift is not None and (
            not isinstance(drift, (int, float)) or isinstance(drift, bool)
        ):
            raise TypeError("candidate drift evidence is invalid")
        next_spec = Spec.model_validate(payload["next_spec"])
        raw_target_ids = payload.get("target_component_ids", ())
        if not isinstance(raw_target_ids, (list, tuple)) or not all(
            isinstance(component_id, str) and component_id.strip()
            for component_id in raw_target_ids
        ):
            raise TypeError("candidate component lineage is invalid")
        target_component_ids = tuple(raw_target_ids)
        raw_child_map = payload.get("proposed_child_component_map")
        proposed_child_map = (
            RevisionComponentMap.model_validate(raw_child_map)
            if raw_child_map is not None
            else None
        )
        transform_hash = payload.get("transform_contract_sha256")
        if transform_hash is not None and (
            not isinstance(transform_hash, str) or len(transform_hash) != 64
        ):
            raise ValueError("candidate transform lineage is invalid")
    except (KeyError, TypeError, ValueError) as exc:
        raise CatalogPreviewUnavailable(
            "the catalog preview payload is incomplete or invalid"
        ) from exc
    return (
        payload,
        next_spec,
        source_spec_hash,
        target_spec_hash,
        target_component_ids,
        proposed_child_map,
    )


def _candidate(record: PreviewCandidateRecord) -> CatalogPreviewCandidate:
    (
        payload,
        next_spec,
        source_spec_hash,
        target_spec_hash,
        target_component_ids,
        proposed_child_map,
    ) = _validated_candidate_payload(record)
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
        source_spec_visual_hash=source_spec_hash,
        target_spec_visual_hash=target_spec_hash,
        image_bytes=bytes(record.image),
        media_type=record.media_type,
        requested_change=payload["requested_change"],
        region_description=payload["region_description"],
        drift=payload.get("drift"),
        next_spec=next_spec,
        component_path=payload["component_path"],
        option_id=payload["option_id"],
        spec_change=tuple(payload["spec_change"]),
        qa=payload["qa"],
        routing=payload["routing"],
        created_by=record.owner,
        expires_at=_utc(record.expires_at),
        component_map_sha256=payload.get("component_map_sha256"),
        target_component_ids=target_component_ids,
        target_mask_sha256=payload.get("target_mask_sha256"),
        proposed_child_component_map=proposed_child_map,
        studio_job_id=record.studio_job_id,
        transform_contract_sha256=payload.get("transform_contract_sha256"),
    )


def _active_primary(db: Session, root_id: str) -> ImageAsset | None:
    rows = list(db.scalars(
        select(ImageAsset)
        .where(ImageAsset.root_id == root_id)
        .order_by(ImageAsset.created_at, ImageAsset.id)
    ))
    primary = [asset for asset in rows if is_primary_revision(asset)]
    return primary[-1] if primary else None


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
        raise CatalogPreviewJobError("the Studio Refine job is unavailable")
    if (
        job.action_id != "refine"
        or job.lane != canonical.lane
        or job.credits_per_output != canonical.credits_per_output
        or job.requested_outputs != 1
    ):
        raise CatalogPreviewJobError(
            "this candidate requires a canonical one-output Studio Refine job")
    if job.status != "running":
        raise CatalogPreviewJobError(
            f"the Studio Refine job is already {job.status}")
    if (
        job.active_design_id != project_root_id
        or job.source_revision_id != source_asset_id
    ):
        raise CatalogPreviewJobError(
            "the Studio Refine job belongs to another exact revision")
    job.status = "reviewing"
    job.progress = max(job.progress, 0.9)
    job.updated_at = utcnow()


def validate_catalog_preview_refine_job(
    db: Session,
    *,
    job_id: str,
    owner: str,
    project_root_id: str,
    source_asset_id: str,
) -> None:
    """Fail before provider work; store revalidates under lock before binding."""
    job = db.scalar(select(StudioJobRecord).where(
        StudioJobRecord.id == job_id).with_for_update())
    canonical = studio_job_action_definition("refine")
    if job is None or job.owner != owner:
        raise CatalogPreviewJobError("the Studio Refine job is unavailable")
    if (
        job.action_id != "refine"
        or job.lane != canonical.lane
        or job.credits_per_output != canonical.credits_per_output
        or job.requested_outputs != 1
    ):
        raise CatalogPreviewJobError(
            "this candidate requires a canonical one-output Studio Refine job")
    if job.status != "running":
        raise CatalogPreviewJobError(
            f"the Studio Refine job is already {job.status}")
    if (
        job.active_design_id != project_root_id
        or job.source_revision_id != source_asset_id
    ):
        raise CatalogPreviewJobError(
            "the Studio Refine job belongs to another exact revision")


def _settle_zero_job(
    db: Session,
    record: PreviewCandidateRecord,
    *,
    status: Literal["failed", "canceled"] = "canceled",
    error_code: str | None = None,
) -> None:
    if record.studio_job_id is None:
        return
    job = db.scalar(select(StudioJobRecord).where(
        StudioJobRecord.id == record.studio_job_id).with_for_update())
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
        raise CatalogPreviewJobError(
            "the catalog preview Studio Refine job is unavailable")
    if job.completed_outputs != 0 or job.charged_outputs != 0:
        raise CatalogPreviewJobError(
            "a completed or charged Studio Refine job cannot settle as zero output")
    if job.status in {"failed", "canceled"}:
        if job.completed_outputs != 0:
            raise CatalogPreviewJobError(
                "the terminal Studio Refine job has inconsistent output evidence")
        if job.status == status and job.error_code == error_code:
            return
        if job.status == "canceled" and job.error_code is None:
            return
        raise CatalogPreviewJobError(
            f"the Studio Refine job is already {job.status}")
    if job.status not in {"running", "reviewing"}:
        raise CatalogPreviewJobError(
            f"the Studio Refine job cannot settle from {job.status}")
    job.status = status
    job.progress = 1
    job.completed_outputs = 0
    job.charged_outputs = 0
    job.error_code = error_code
    job.updated_at = utcnow()


def settle_catalog_preview_refine_job_failure(
    db: Session,
    *,
    job_id: str,
    owner: str,
    project_root_id: str,
    source_asset_id: str,
    error_code: str,
    commit: bool = True,
) -> None:
    """Fail one exact Refine job after provider or jewelry-QA rejection.

    Execution can fail before a temporary candidate exists, so this settlement
    validates the same immutable job binding used by candidate storage. Failed
    attempts are evidence, never billable outputs.
    """

    job = db.scalar(select(StudioJobRecord).where(
        StudioJobRecord.id == job_id,
    ).with_for_update())
    canonical = studio_job_action_definition("refine")
    if (
        job is None
        or job.owner != owner
        or job.action_id != "refine"
        or job.lane != canonical.lane
        or job.credits_per_output != canonical.credits_per_output
        or job.requested_outputs != 1
        or job.active_design_id != project_root_id
        or job.source_revision_id != source_asset_id
    ):
        raise CatalogPreviewJobError(
            "the catalog preview Studio Refine job is unavailable")
    if job.completed_outputs != 0 or job.charged_outputs != 0:
        raise CatalogPreviewJobError(
            "a completed or charged Studio Refine job cannot fail this preview")
    normalized_error = error_code[:64]
    if job.status in {"running", "reviewing"}:
        job.status = "failed"
        job.progress = 1
        job.completed_outputs = 0
        job.charged_outputs = 0
        job.error_code = normalized_error
        job.updated_at = utcnow()
        if commit:
            db.commit()
        else:
            db.flush()
        return
    if job.status == "failed" and job.error_code == normalized_error:
        return
    if job.status == "canceled" and job.error_code is None:
        return
    raise CatalogPreviewJobError(
        f"the Studio Refine job is already {job.status}")


def _expire_record(db: Session, record: PreviewCandidateRecord) -> None:
    _settle_zero_job(db, record)
    record.status = "expired"
    record.image = b""
    record.resolved_at = utcnow()


def _expire(db: Session, record: PreviewCandidateRecord) -> None:
    _expire_record(db, record)
    db.commit()


def expire_stale_catalog_preview_candidates(
    db: Session,
    *,
    owner: str,
    job_id: str | None = None,
) -> int:
    """Expire due, job-backed catalog previews before Activity serialization."""

    query = select(PreviewCandidateRecord).where(
        PreviewCandidateRecord.owner == owner,
        PreviewCandidateRecord.kind == "catalog_revision",
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


def invalidate_catalog_preview_candidate(
    db: Session,
    run_id: str,
    candidate_id: str,
    *,
    owner: str,
    error_code: str = "catalog_preview_unavailable",
) -> bool:
    """Atomically close a stale preview and its uncharged Refine job.

    The lineage validator intentionally raises before returning candidate
    bytes. This exact-row cleanup turns that rejected review into terminal
    evidence without ever promoting pixels or specification state.
    """

    record = db.scalar(select(PreviewCandidateRecord).where(
        PreviewCandidateRecord.id == candidate_id,
        PreviewCandidateRecord.image_run_id == run_id,
        PreviewCandidateRecord.kind == "catalog_revision",
        PreviewCandidateRecord.owner == owner,
    ).with_for_update())
    if record is None or record.status != "reviewing":
        return False
    _settle_zero_job(
        db,
        record,
        status="failed",
        error_code=error_code[:64],
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
    (
        payload,
        next_spec,
        expected_source_spec_hash,
        expected_target_spec_hash,
        target_component_ids,
        proposed_child,
    ) = _validated_candidate_payload(record)
    version = (
        db.get(DesignVersion, (root.design_id, record.expected_design_version))
        if root is not None
        and root.design_id is not None
        and record.expected_design_version is not None
        else None
    )
    source_spec = (
        Spec.model_validate(version.spec) if version is not None else None
    )
    source_spec_hash = (
        spec_visual_hash(source_spec) if source_spec is not None else None
    )
    target_spec_hash = spec_visual_hash(next_spec)
    component_lineage_valid = True
    expected_map_hash = payload.get("component_map_sha256")
    expected_mask_hash = payload.get("target_mask_sha256")
    has_component_lineage = any((
        expected_map_hash is not None,
        expected_mask_hash is not None,
        bool(target_component_ids),
    ))
    # Ring catalog previews created before component targeting became
    # authoritative cannot be grandfathered into Apply: they have no proof of
    # the region shown to the provider. Necklace mapping remains out of v1.
    component_lineage_required = (
        source_spec is not None and source_spec.jewelry_type == "ring"
    )
    if component_lineage_required and not has_component_lineage:
        component_lineage_valid = False
    elif has_component_lineage and not (
        isinstance(expected_map_hash, str)
        and isinstance(expected_mask_hash, str)
        and bool(target_component_ids)
    ):
        component_lineage_valid = False
    elif has_component_lineage:
        try:
            component_map = load_revision_component_map(
                db, record.source_asset_id)
            if component_map is None or not target_component_ids:
                component_lineage_valid = False
            else:
                current_mask = rasterize_component_masks(
                    component_map, target_component_ids)
                current_mask_hash = hashlib.sha256(current_mask).hexdigest()
                component_lineage_valid = (
                    component_map_hash(component_map) == expected_map_hash
                    and current_mask_hash == expected_mask_hash
                    and run is not None
                    and run.mask_hash == expected_mask_hash
                )
        except (ComponentMapError, TypeError, ValueError):
            component_lineage_valid = False
    proposed_child_map_valid = True
    if payload.get("component_path") in STRUCTURAL_CATALOG_PATHS:
        try:
            if proposed_child is None:
                raise ComponentMapError(
                    "the structural child component map is unavailable",
                    code="component_mapping_unresolved",
                )
            bind_map_to_raster(proposed_child, bytes(record.image))
            mapper_status = catalog_structural_component_mapper_status()
            proposed_child_map_valid = (
                proposed_child.asset_id == record.id
                and proposed_child.mapper_contract == mapper_status.mapper_contract
                and proposed_child.calibration_evidence_sha256
                == mapper_status.calibration_evidence_sha256
                and mapper_status.state == "ready"
                and payload["component_path"] in mapper_status.supported_paths
            )
        except (ComponentMapError, TypeError, ValueError):
            proposed_child_map_valid = False
    routing = payload.get("routing")
    intent = run.normalized_intent if run is not None else None
    transform_hash = payload.get("transform_contract_sha256")
    instant_markers = (
        transform_hash is not None,
        isinstance(routing, dict)
        and routing.get("execution_mode") == "instant_masked_transform",
        isinstance(intent, dict)
        and intent.get("execution_mode") == "instant_masked_transform",
        run is not None and run.prompt_version == INSTANT_METAL_COLOR_VERSION,
    )
    instant_lineage_valid = True
    if any(instant_markers):
        provider_attempt = db.scalar(
            select(ImageAttempt.id).where(ImageAttempt.run_id == record.image_run_id)
        )
        recomputed_input_hash = (
            instant_input_sha256(
                record.source_sha256,
                expected_mask_hash,
                transform_hash,
            )
            if isinstance(expected_mask_hash, str)
            and isinstance(transform_hash, str)
            else None
        )
        instant_lineage_valid = (
            payload.get("component_path") == "metal.color"
            and record.studio_job_id is None
            and isinstance(transform_hash, str)
            and len(transform_hash) == 64
            and isinstance(intent, dict)
            and isinstance(intent.get("transform_contract"), dict)
            and transform_contract_sha256(intent["transform_contract"])
            == transform_hash
            and intent["transform_contract"].get("controlled_color")
            == payload.get("option_id")
            and intent.get("execution_mode") == "instant_masked_transform"
            and intent.get("component_path") == "metal.color"
            and intent.get("option_id") == payload.get("option_id")
            and intent.get("source_sha256") == record.source_sha256
            and intent.get("mask_sha256") == expected_mask_hash
            and intent.get("output_sha256") == record.output_sha256
            and intent.get("transform_contract_sha256") == transform_hash
            and intent.get("authority") == "temporary_preview_only"
            and routing.get("transform_contract_sha256") == transform_hash
            and routing.get("execution_mode") == "instant_masked_transform"
            and routing.get("provider_calls") == 0
            and routing.get("attempt_count") == 0
            and routing.get("source_sha256") == record.source_sha256
            and routing.get("mask_sha256") == expected_mask_hash
            and routing.get("output_sha256") == record.output_sha256
            and routing.get("input_sha256") == recomputed_input_hash
            and run is not None
            and run.operation == "LOCAL_EDIT"
            and run.prompt_version == INSTANT_METAL_COLOR_VERSION
            and run.status == "preview_ready"
            and run.accepted_asset_id is None
            and run.input_hash == recomputed_input_hash
            and next_spec.metal is not None
            and next_spec.metal.color == payload.get("option_id")
            and provider_attempt is None
        )
    if (
        project is None
        or project.owner != owner
        or source is None
        or root is None
        or source.root_id != record.project_root_id
        or not is_primary_revision(source)
        or active is None
        or (
            require_active
            and active.id != record.expected_active_asset_id
        )
        or source.id != record.expected_active_asset_id
        or source.design_version != record.expected_design_version
        or source_hash != record.source_sha256
        or output_hash != record.output_sha256
        or source_spec_hash != expected_source_spec_hash
        or target_spec_hash != expected_target_spec_hash
        or run is None
        or run.created_by != owner
        or run.project_root_id != record.project_root_id
        or run.source_asset_id != record.source_asset_id
        or run.source_hash != record.source_sha256
        or run.source_spec_visual_hash != expected_source_spec_hash
        or run.spec_visual_hash != expected_target_spec_hash
        or not component_lineage_valid
        or not proposed_child_map_valid
        or not instant_lineage_valid
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
    component_map_sha256: str | None = None,
    target_component_ids: tuple[str, ...] = (),
    target_mask_sha256: str | None = None,
    proposed_child_component_map: RevisionComponentMap | None = None,
    studio_job_id: str | None = None,
    transform_contract_sha256: str | None = None,
) -> CatalogPreviewCandidate:
    if not reviewable_candidate_qa(verdict, qa):
        raise CatalogPreviewQaInvalid(
            "the catalog preview failed or has incomplete QA evidence"
        )
    if studio_job_id is not None:
        _bind_refine_job(
            db,
            job_id=studio_job_id,
            owner=created_by,
            project_root_id=project_root_id,
            source_asset_id=source_asset_id,
        )
    now = utcnow()
    candidate_id = new_id("cand")
    if proposed_child_component_map is not None:
        bind_map_to_raster(proposed_child_component_map, image_bytes)
        payload = proposed_child_component_map.model_dump(mode="json")
        payload["asset_id"] = candidate_id
        proposed_child_component_map = RevisionComponentMap.model_validate(payload)
        bind_map_to_raster(proposed_child_component_map, image_bytes)
    record = PreviewCandidateRecord(
        id=candidate_id,
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
        studio_job_id=studio_job_id,
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
            "component_map_sha256": component_map_sha256,
            "target_component_ids": list(target_component_ids),
            "target_mask_sha256": target_mask_sha256,
            "transform_contract_sha256": transform_contract_sha256,
            "proposed_child_component_map": (
                proposed_child_component_map.model_dump(mode="json")
                if proposed_child_component_map is not None
                else None
            ),
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
    require_active: bool = True,
) -> tuple[CatalogPreviewCandidate, PreviewCandidateRecord]:
    record = _owned_reviewing_record(
        db,
        run_id,
        candidate_id,
        owner=owner,
        for_update=True,
        require_active=require_active,
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
                require_active=False,
            )
        except CatalogPreviewUnavailable:
            # A resume read is a real lifecycle observation. Do not silently
            # hide invalid bytes while their exact Activity job remains stuck
            # in review.
            invalidate_catalog_preview_candidate(
                db,
                record.image_run_id,
                record.id,
                owner=owner,
            )
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
    try:
        require_single_preview_job_output(
            db,
            studio_job_id=record.studio_job_id,
            expected_candidate_id=record.id,
        )
    except StudioPreviewJobBindingConflict as exc:
        raise CatalogPreviewJobError(str(exc)) from exc
    if status in {"applied", "saved_as_variation"} and (
        terminal_asset_id is None or review_id is None
    ):
        raise ValueError("accepted previews require asset and review identities")
    if status == "discarded":
        _settle_zero_job(db, record)
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


def settle_catalog_preview_acceptance(
    db: Session,
    candidate: CatalogPreviewCandidate,
    *,
    owner: str,
) -> None:
    """Settle one accepted output inside the caller's canonical transaction."""
    if candidate.studio_job_id is None:
        return
    try:
        record_accepted_studio_job_outputs(
            db,
            job_id=candidate.studio_job_id,
            owner=owner,
            completed_outputs=1,
            active_design_id=candidate.project_root_id,
            source_revision_id=candidate.source_asset_id,
        )
    except StudioJobAccountingError as exc:
        raise CatalogPreviewJobError(str(exc)) from exc


def clear_catalog_preview_candidates_for_tests() -> None:
    """Compatibility no-op: isolated test databases own candidate cleanup."""

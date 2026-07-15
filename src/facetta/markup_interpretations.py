"""Durable confirmation authority for designer markup interpretations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from facetta.db import (
    ImageAsset,
    Project,
    StudioMarkupInterpretationRecord,
    new_id,
    utcnow,
)
from facetta.revision_component_map import ComponentMapError, component_map_hash
from facetta.revision_component_map_store import load_revision_component_map


INTERPRETATION_TTL = timedelta(minutes=30)


@dataclass(frozen=True)
class MarkupInterpretationError(Exception):
    code: str
    detail: str
    status_code: int

    def __str__(self) -> str:
        return self.detail


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _payload_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _asset_hash(asset: ImageAsset) -> str:
    return hashlib.sha256(bytes(asset.image)).hexdigest()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(
        tzinfo=timezone.utc)


def _project_owner(
    db: Session,
    *,
    project_root_id: str,
    owner: str,
) -> Project:
    project = db.get(Project, project_root_id)
    if project is None or project.owner != owner:
        raise MarkupInterpretationError(
            "markup_interpretation_project_unavailable",
            "the markup interpretation project is unavailable",
            404,
        )
    return project


def require_markup_interpretation_source(
    db: Session,
    source: ImageAsset,
    *,
    owner: str,
) -> None:
    """Authorize the exact source before any markup provider can see it."""

    _project_owner(db, project_root_id=source.root_id, owner=owner)


def _source_component_map_binding(
    db: Session,
    source_asset_id: str,
) -> tuple[str, str | None]:
    try:
        component_map = load_revision_component_map(db, source_asset_id)
    except ComponentMapError as exc:
        raise MarkupInterpretationError(
            "markup_interpretation_component_map_invalid",
            "the source component map failed its integrity check",
            409,
        ) from exc
    if component_map is None:
        return "unmapped", None
    return "mapped", component_map_hash(component_map)


def create_markup_interpretation(
    db: Session,
    *,
    source: ImageAsset,
    markup: ImageAsset,
    owner: str,
    annotation: dict,
    interpretation: dict,
    provider_evidence: dict,
    source_design_version: int | None,
    source_spec_visual_hash: str | None,
) -> StudioMarkupInterpretationRecord:
    """Persist one exact provider reading without authorizing generation."""

    _project_owner(db, project_root_id=source.root_id, owner=owner)
    if (
        markup.capability != "MARKUP_NOTES"
        or markup.root_id != source.root_id
        or markup.parent_asset_id != source.id
        or markup.created_by != owner
    ):
        raise MarkupInterpretationError(
            "markup_interpretation_markup_invalid",
            "the saved markup is not bound to this exact source revision",
            422,
        )
    if (source_design_version is None) != (source_spec_visual_hash is None):
        raise MarkupInterpretationError(
            "markup_interpretation_spec_binding_invalid",
            "design version and specification hash must be bound together",
            500,
        )
    component_map_state, component_map_sha256 = _source_component_map_binding(
        db, source.id,
    )

    authority = {
        "annotation": annotation,
        "interpretation": interpretation,
    }
    now = utcnow()
    record = StudioMarkupInterpretationRecord(
        id=new_id("mki"),
        owner=owner,
        project_root_id=source.root_id,
        source_asset_id=source.id,
        source_sha256=_asset_hash(source),
        source_design_version=source_design_version,
        source_spec_visual_hash=source_spec_visual_hash,
        source_component_map_state=component_map_state,
        source_component_map_sha256=component_map_sha256,
        markup_asset_id=markup.id,
        markup_sha256=_asset_hash(markup),
        interpretation=authority,
        interpretation_sha256=_payload_hash(authority),
        provider_evidence=provider_evidence,
        provider_evidence_sha256=_payload_hash(provider_evidence),
        status="awaiting_confirmation",
        created_at=now,
        expires_at=now + INTERPRETATION_TTL,
        confirmed_at=None,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def _load_for_owner(
    db: Session,
    interpretation_id: str,
    *,
    owner: str,
) -> StudioMarkupInterpretationRecord:
    record = db.execute(
        select(StudioMarkupInterpretationRecord)
        .where(
            StudioMarkupInterpretationRecord.id == interpretation_id,
            StudioMarkupInterpretationRecord.owner == owner,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if record is None:
        raise MarkupInterpretationError(
            "markup_interpretation_unavailable",
            "the markup interpretation is unavailable",
            404,
        )
    return record


def _validate_exact_binding(
    db: Session,
    record: StudioMarkupInterpretationRecord,
    *,
    owner: str,
    project_root_id: str,
    source_asset_id: str,
    current_design_version: int | None,
    current_spec_visual_hash: str | None,
) -> tuple[ImageAsset, ImageAsset]:
    if record.project_root_id != project_root_id:
        raise MarkupInterpretationError(
            "markup_interpretation_project_mismatch",
            "the confirmed interpretation belongs to a different project",
            409,
        )
    if record.source_asset_id != source_asset_id:
        raise MarkupInterpretationError(
            "markup_interpretation_source_mismatch",
            "the confirmed interpretation belongs to a different source revision",
            409,
        )
    _project_owner(db, project_root_id=project_root_id, owner=owner)
    source = db.get(ImageAsset, source_asset_id)
    markup = db.get(ImageAsset, record.markup_asset_id)
    if source is None or markup is None:
        raise MarkupInterpretationError(
            "markup_interpretation_lineage_unavailable",
            "the confirmed interpretation lineage is unavailable",
            410,
        )
    if _asset_hash(source) != record.source_sha256:
        raise MarkupInterpretationError(
            "stale_markup_interpretation_source",
            "the source image changed after its marks were interpreted",
            409,
        )
    if (
        markup.capability != "MARKUP_NOTES"
        or markup.root_id != project_root_id
        or markup.parent_asset_id != source_asset_id
        or markup.created_by != owner
        or _asset_hash(markup) != record.markup_sha256
    ):
        raise MarkupInterpretationError(
            "markup_interpretation_markup_tampered",
            "the saved markup no longer matches the interpreted evidence",
            409,
        )
    if (
        _payload_hash(record.interpretation)
        != record.interpretation_sha256
        or _payload_hash(record.provider_evidence)
        != record.provider_evidence_sha256
    ):
        raise MarkupInterpretationError(
            "markup_interpretation_evidence_tampered",
            "the persisted interpretation evidence failed its integrity check",
            409,
        )
    if (
        record.source_design_version != current_design_version
        or record.source_spec_visual_hash != current_spec_visual_hash
    ):
        raise MarkupInterpretationError(
            "stale_markup_interpretation_spec",
            "the design facts changed after the marks were interpreted",
            409,
        )
    component_map_state, component_map_sha256 = _source_component_map_binding(
        db, source_asset_id,
    )
    if (
        record.source_component_map_state != component_map_state
        or record.source_component_map_sha256 != component_map_sha256
    ):
        raise MarkupInterpretationError(
            "stale_markup_interpretation_component_map",
            "the source component map changed after the marks were interpreted",
            409,
        )
    return source, markup


def _expire_if_needed(
    db: Session,
    record: StudioMarkupInterpretationRecord,
) -> None:
    if _aware(record.expires_at) > utcnow():
        return
    if record.status != "expired":
        record.status = "expired"
        db.commit()
    raise MarkupInterpretationError(
        "markup_interpretation_expired",
        "the markup interpretation expired; review the current marks again",
        410,
    )


def confirm_markup_interpretation(
    db: Session,
    interpretation_id: str,
    *,
    owner: str,
    project_root_id: str,
    source_asset_id: str,
    current_design_version: int | None,
    current_spec_visual_hash: str | None,
) -> StudioMarkupInterpretationRecord:
    """Confirm the exact server-held reading; replay is idempotent."""

    record = _load_for_owner(db, interpretation_id, owner=owner)
    _expire_if_needed(db, record)
    _validate_exact_binding(
        db,
        record,
        owner=owner,
        project_root_id=project_root_id,
        source_asset_id=source_asset_id,
        current_design_version=current_design_version,
        current_spec_visual_hash=current_spec_visual_hash,
    )
    if record.status == "confirmed":
        return record
    if record.status != "awaiting_confirmation":
        raise MarkupInterpretationError(
            "markup_interpretation_not_confirmable",
            "the markup interpretation cannot be confirmed",
            409,
        )
    record.status = "confirmed"
    record.confirmed_at = utcnow()
    db.commit()
    db.refresh(record)
    return record


def require_confirmed_markup_interpretation(
    db: Session,
    interpretation_id: str | None,
    *,
    owner: str,
    project_root_id: str,
    source_asset_id: str,
    current_design_version: int | None,
    current_spec_visual_hash: str | None,
    supplied_annotation: dict | None = None,
    supplied_markup_asset_id: str | None = None,
    supplied_instruction: str | None = None,
) -> StudioMarkupInterpretationRecord:
    """Authorize generation from one confirmed immutable interpretation."""

    if interpretation_id is None:
        raise MarkupInterpretationError(
            "confirmed_markup_interpretation_required",
            "confirm Facetta's interpretation before creating a preview",
            422,
        )
    record = _load_for_owner(db, interpretation_id, owner=owner)
    _expire_if_needed(db, record)
    _validate_exact_binding(
        db,
        record,
        owner=owner,
        project_root_id=project_root_id,
        source_asset_id=source_asset_id,
        current_design_version=current_design_version,
        current_spec_visual_hash=current_spec_visual_hash,
    )
    if record.status != "confirmed":
        raise MarkupInterpretationError(
            "markup_interpretation_unconfirmed",
            "confirm Facetta's interpretation before creating a preview",
            409,
        )
    annotation = record.interpretation.get("annotation")
    if not isinstance(annotation, dict):
        raise MarkupInterpretationError(
            "markup_interpretation_evidence_tampered",
            "the persisted interpretation evidence is incomplete",
            409,
        )
    if supplied_annotation is not None and supplied_annotation != annotation:
        raise MarkupInterpretationError(
            "markup_interpretation_substitution",
            "the preview request does not exactly replay the confirmed interpretation",
            422,
        )
    if (
        supplied_markup_asset_id is not None
        and supplied_markup_asset_id != record.markup_asset_id
    ):
        raise MarkupInterpretationError(
            "markup_interpretation_substitution",
            "the preview request substituted different markup evidence",
            422,
        )
    if (
        supplied_instruction is not None
        and supplied_instruction.strip() != str(
            annotation.get("change_instruction", "")
        ).strip()
    ):
        raise MarkupInterpretationError(
            "markup_interpretation_substitution",
            "the preview request substituted a different instruction",
            422,
        )
    return record


def confirmed_annotation(
    record: StudioMarkupInterpretationRecord,
) -> dict:
    annotation = record.interpretation.get("annotation")
    if not isinstance(annotation, dict):  # validated before public use
        raise MarkupInterpretationError(
            "markup_interpretation_evidence_tampered",
            "the persisted interpretation evidence is incomplete",
            409,
        )
    return dict(annotation)

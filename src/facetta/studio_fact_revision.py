"""Atomic designer-entered fact revisions for an exact Studio design state."""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from facetta.db import (
    DesignVersion,
    ImageAsset,
    Project,
    ProjectRevisionRecord,
    new_id,
    utcnow,
)
from facetta.dimension_provenance import mark_designer_adjusted_dimensions
from facetta.project_backbone import is_primary_revision
from facetta.spec import Spec
from facetta.specdiff import diff_specs, summarize_changes
from facetta.validation import validate_spec
from facetta.vocabulary import get_vocabulary


DESIGNER_SAFE_FACT_PATHS = frozenset({
    "stone.species",
    "stone.cut",
    "stone.color",
    "stone.color.trade",
    "stone.color.gia",
    "stone.color.hue_code",
    "stone.color.tone",
    "stone.color.saturation",
    "stone.carat",
    "stone.dimensions_mm",
    "stone.dimensions_mm.length",
    "stone.dimensions_mm.width",
    "stone.dimensions_mm.depth",
    "metal.material",
    "metal.karat",
    "metal.color",
    "metal.finish",
    "setting.style",
    "setting.prong_count",
    "band.profile",
    "band.width_mm",
    "band.thickness_mm",
    "ring_size.system",
    "ring_size.value",
})


class StudioFactRevisionError(ValueError):
    """The requested fact revision cannot safely extend canonical history."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class StudioFactRevisionResult:
    status: Literal["applied", "no_change"]
    project_root_id: str
    source_asset_id: str
    asset_id: str
    design_id: str
    previous_design_version: int
    design_version: int
    spec_change: tuple[dict[str, object], ...]


def _project_chain_for_update(
    db: Session,
    project_root_id: str,
) -> list[ImageAsset]:
    chain = list(db.scalars(
        select(ImageAsset)
        .where(ImageAsset.root_id == project_root_id)
        .order_by(ImageAsset.created_at, ImageAsset.id)
        .with_for_update()
    ))
    chain.sort(key=lambda asset: (
        asset.id != project_root_id, asset.created_at, asset.id,
    ))
    return chain


def _set_fact(raw: dict, path: str, value: object) -> None:
    keys = path.split(".")
    current: object = raw
    for key in keys[:-1]:
        if not isinstance(current, dict) or key not in current:
            raise StudioFactRevisionError(
                "fact_path_unavailable",
                f"the active specification has no editable fact path '{path}'",
            )
        current = current[key]
    if not isinstance(current, dict) or keys[-1] not in current:
        raise StudioFactRevisionError(
            "fact_path_unavailable",
            f"the active specification has no editable fact path '{path}'",
        )
    current[keys[-1]] = copy.deepcopy(value)


def _fact_value(raw: dict, path: str) -> object:
    current: object = raw
    for key in path.split("."):
        if not isinstance(current, dict) or key not in current:
            raise StudioFactRevisionError(
                "fact_path_unavailable",
                f"the active specification has no editable fact path '{path}'",
            )
        current = current[key]
    return copy.deepcopy(current)


def _apply_studio_fact_revision(
    db: Session,
    *,
    project_root_id: str,
    expected_active_asset_id: str,
    expected_design_version: int,
    changes: Mapping[str, object],
    created_by: str,
) -> StudioFactRevisionResult:
    """Append one byte-identical revision containing only designer-safe facts."""

    if not changes:
        raise StudioFactRevisionError(
            "fact_changes_required", "submit at least one fact to review",
        )
    unsafe = sorted(set(changes) - DESIGNER_SAFE_FACT_PATHS)
    if unsafe:
        raise StudioFactRevisionError(
            "fact_path_not_allowed",
            "these fact paths are not designer-editable: " + ", ".join(unsafe),
        )

    project = db.scalar(
        select(Project)
        .where(Project.root_id == project_root_id)
        .with_for_update()
    )
    if project is None or project.owner != created_by:
        raise StudioFactRevisionError(
            "fact_revision_unavailable",
            "the active Studio project is unavailable",
        )
    chain = _project_chain_for_update(db, project_root_id)
    primary = [asset for asset in chain if is_primary_revision(asset)]
    active = primary[-1] if primary else None
    root = next((asset for asset in chain if asset.id == project_root_id), None)
    if (
        active is None
        or root is None
        or active.id != expected_active_asset_id
        or active.design_version != expected_design_version
    ):
        raise StudioFactRevisionError(
            "stale_fact_revision",
            "the active image or specification changed before this fact edit",
        )
    if root.design_id is None:
        raise StudioFactRevisionError(
            "exact_specification_required",
            "confirm an exact specification before editing design facts",
        )
    latest = db.scalar(select(func.max(DesignVersion.version)).where(
        DesignVersion.design_id == root.design_id
    ))
    source_version = db.scalar(
        select(DesignVersion)
        .where(
            DesignVersion.design_id == root.design_id,
            DesignVersion.version == expected_design_version,
        )
        .with_for_update()
    )
    if source_version is None or latest != expected_design_version:
        raise StudioFactRevisionError(
            "stale_fact_revision",
            "the active specification is not the latest immutable version",
        )

    try:
        before = Spec.model_validate(source_version.spec)
        edited_raw = before.model_dump(mode="json")
        for path, value in changes.items():
            _set_fact(edited_raw, path, value)
        if {"ring_size.system", "ring_size.value"} & set(changes):
            ring_size = edited_raw.get("ring_size")
            if isinstance(ring_size, dict):
                # This value is deterministic vocabulary output, not a second
                # designer input. Re-derive it from the submitted size.
                ring_size["inner_diameter_mm"] = None
            provenance = edited_raw.get("dimension_provenance")
            if isinstance(provenance, dict):
                provenance.pop("ring_size.inner_diameter_mm", None)
        edited = Spec.model_validate(edited_raw)
    except ValidationError as exc:
        raise StudioFactRevisionError(
            "fact_value_invalid", "a submitted fact has an invalid typed value",
        ) from exc

    requested_values = {
        path: _fact_value(edited.model_dump(mode="json"), path)
        for path in changes
    }
    before_values = {
        path: _fact_value(before.model_dump(mode="json"), path)
        for path in changes
    }
    if requested_values == before_values:
        result = StudioFactRevisionResult(
            status="no_change",
            project_root_id=project.root_id,
            source_asset_id=active.id,
            asset_id=active.id,
            design_id=root.design_id,
            previous_design_version=expected_design_version,
            design_version=expected_design_version,
            spec_change=(),
        )
        db.rollback()
        return result

    edited = mark_designer_adjusted_dimensions(before, edited)
    validated = validate_spec(edited, get_vocabulary())
    if not validated.ok:
        raise StudioFactRevisionError(
            "fact_revision_invalid",
            "the submitted facts do not form a valid jewelry specification",
        )

    now = utcnow()
    next_version = expected_design_version + 1
    stored = validated.spec.model_dump(mode="json")
    stored.update({
        "design_id": root.design_id,
        "version": next_version,
        "created_by": created_by,
        "created_at": now.isoformat().replace("+00:00", "Z"),
    })
    spec_change = tuple(diff_specs(source_version.spec, stored))
    if not spec_change:
        result = StudioFactRevisionResult(
            status="no_change",
            project_root_id=project.root_id,
            source_asset_id=active.id,
            asset_id=active.id,
            design_id=root.design_id,
            previous_design_version=expected_design_version,
            design_version=expected_design_version,
            spec_change=(),
        )
        db.rollback()
        return result

    source_hash = hashlib.sha256(bytes(active.image)).hexdigest()
    child = ImageAsset(
        id=new_id("ast"),
        root_id=project.root_id,
        parent_asset_id=active.id,
        design_id=None,
        design_version=next_version,
        capability="LOCALIZED_EDIT",
        instruction="Designer-entered Studio fact revision",
        region=None,
        drift=None,
        image=bytes(active.image),
        media_type=active.media_type,
        created_by=created_by,
        created_at=now,
    )
    version = DesignVersion(
        design_id=root.design_id,
        version=next_version,
        spec=stored,
        created_by=created_by,
        created_at=now,
    )
    record = ProjectRevisionRecord(
        id=new_id("prr"),
        asset_id=child.id,
        action="edit",
        raw_intent={
            "kind": "studio_fact_revision",
            "source_asset_id": active.id,
            "expected_design_version": expected_design_version,
            "facts": requested_values,
        },
        interpretation={
            "operation": "append_designer_fact_revision",
            "image_generation": False,
            "provider_used": False,
            "factory_authority": False,
            "credits_charged": 0,
            "source_asset_id": active.id,
            "source_sha256": source_hash,
            "output_sha256": source_hash,
        },
        change_summary=(
            summarize_changes(list(spec_change))
            or "Updated designer-confirmed Studio facts."
        ),
        created_by=created_by,
        created_at=now,
    )
    project.selected_candidate_asset_id = child.id
    project.updated_at = now
    db.add_all([version, child, record])
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise StudioFactRevisionError(
            "stale_fact_revision",
            "another revision was saved before these facts could be applied",
        ) from exc
    except Exception:
        db.rollback()
        raise

    return StudioFactRevisionResult(
        status="applied",
        project_root_id=project.root_id,
        source_asset_id=active.id,
        asset_id=child.id,
        design_id=root.design_id,
        previous_design_version=expected_design_version,
        design_version=next_version,
        spec_change=spec_change,
    )


def apply_studio_fact_revision(
    db: Session,
    *,
    project_root_id: str,
    expected_active_asset_id: str,
    expected_design_version: int,
    changes: Mapping[str, object],
    created_by: str,
) -> StudioFactRevisionResult:
    """Append one safe fact revision or leave the database unchanged."""

    try:
        return _apply_studio_fact_revision(
            db,
            project_root_id=project_root_id,
            expected_active_asset_id=expected_active_asset_id,
            expected_design_version=expected_design_version,
            changes=changes,
            created_by=created_by,
        )
    except Exception:
        db.rollback()
        raise

"""Atomic designer-entered fact revisions for an exact Studio design state."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

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
from facetta.project_backbone import is_primary_revision
from facetta.revision_component_map import ComponentMapError
from facetta.revision_component_map_store import (
    copy_revision_component_map_for_identical_raster,
)
from facetta.spec import Spec
from facetta.specdiff import diff_specs, summarize_changes
from facetta.studio_fact_changes import (
    StudioFactChangeError,
    prepare_studio_fact_changes,
)
from facetta.validation import validate_spec
from facetta.vocabulary import get_vocabulary


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

    before = Spec.model_validate(source_version.spec)
    try:
        prepared = prepare_studio_fact_changes(before, changes)
    except StudioFactChangeError as exc:
        raise StudioFactRevisionError(exc.code, exc.detail) from exc
    edited = prepared.spec
    requested_values = dict(prepared.corrected_values)
    if not prepared.changed:
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
    project.selected_candidate_asset_id = child.id
    project.updated_at = now
    db.add_all([version, child])
    try:
        # A fact-only revision deliberately preserves the exact source raster.
        # Carry any calibrated component-isolation evidence forward instead of
        # making a previously targetable design silently unmapped. Validation,
        # copy, immutable history, the active pointer, and the new spec version
        # all share this transaction, so corrupt source evidence fails closed
        # without leaving a partial canonical revision.
        db.flush()
        copied_component_map = copy_revision_component_map_for_identical_raster(
            db,
            source_asset_id=active.id,
            child_asset_id=child.id,
            child_image_bytes=bytes(child.image),
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
                "derived_fact_adjustments": {
                    path: {
                        "before": prepared.derived_original_values[path],
                        "after": value,
                        "authority": "deterministic_component_rule",
                    }
                    for path, value in prepared.derived_values.items()
                },
                "source_asset_id": active.id,
                "source_sha256": source_hash,
                "output_sha256": source_hash,
                "component_map_status": (
                    "copied_exact_raster"
                    if copied_component_map is not None
                    else "unmapped"
                ),
                "component_map_source_asset_id": (
                    active.id if copied_component_map is not None else None
                ),
                "component_map_sha256": (
                    copied_component_map.map_sha256
                    if copied_component_map is not None
                    else None
                ),
            },
            change_summary=(
                summarize_changes(list(spec_change))
                or "Updated designer-confirmed Studio facts."
            ),
            created_by=created_by,
            created_at=now,
        )
        db.add(record)
        db.commit()
    except ComponentMapError as exc:
        db.rollback()
        raise StudioFactRevisionError(exc.code, exc.detail) from exc
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

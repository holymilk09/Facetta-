"""Persistence boundary for immutable revision component maps."""

from __future__ import annotations

import hashlib

from sqlalchemy.orm import Session

from facetta.db import ImageAsset, RevisionComponentMapRecord
from facetta.revision_component_map import (
    ComponentMapError,
    RevisionComponentMap,
    bind_map_to_raster,
    component_map_hash,
)


def load_revision_component_map(
    db: Session,
    asset_id: str,
) -> RevisionComponentMap | None:
    record = db.get(RevisionComponentMapRecord, asset_id)
    if record is None:
        return None
    try:
        component_map = RevisionComponentMap.model_validate(record.map_json)
    except Exception as exc:
        raise ComponentMapError(
            "persisted component map does not match the revision-map contract",
            code="component_map_record_invalid",
        ) from exc
    if component_map_hash(component_map) != record.map_sha256:
        raise ComponentMapError(
            "persisted component map content hash is invalid",
            code="component_map_record_hash_mismatch",
        )
    asset = db.get(ImageAsset, asset_id)
    if asset is None:
        raise ComponentMapError(
            "component map references a missing asset",
            code="component_map_asset_missing",
        )
    bind_map_to_raster(component_map, bytes(asset.image))
    return component_map


def add_revision_component_map(
    db: Session,
    component_map: RevisionComponentMap,
    *,
    image_bytes: bytes,
    parent_asset_id: str | None,
) -> RevisionComponentMapRecord:
    """Stage a validated map in the caller's image-revision transaction."""
    if db.get(RevisionComponentMapRecord, component_map.asset_id) is not None:
        raise ComponentMapError(
            "this asset already has an immutable component map",
            code="component_map_already_exists",
        )
    bind_map_to_raster(component_map, image_bytes)
    record = RevisionComponentMapRecord(
        asset_id=component_map.asset_id,
        parent_asset_id=parent_asset_id,
        map_json=component_map.model_dump(mode="json"),
        map_sha256=component_map_hash(component_map),
    )
    db.add(record)
    db.flush()
    return record


def copy_revision_component_map_for_identical_raster(
    db: Session,
    *,
    source_asset_id: str,
    child_asset_id: str,
    child_image_bytes: bytes,
) -> RevisionComponentMapRecord | None:
    """Carry exact image-isolation evidence onto a byte-identical child.

    Confirmation promotes a selected creative candidate by appending a new,
    immutable Design v1 asset whose raster bytes are identical to the reviewed
    candidate.  Re-running vision for that transition would be slower and
    could introduce different polygons; dropping an existing map would make a
    previously targetable direction inexplicably unmapped.  Exact byte
    identity is sufficient evidence to rebind the same normalized regions and
    stable component IDs to the child asset.

    Absence is intentionally preserved as absence.  This function never
    derives geometry, and callers therefore keep Component Refine fail-closed
    when the source candidate has not been mapped by a calibrated mapper.
    """
    source = load_revision_component_map(db, source_asset_id)
    if source is None:
        return None
    child_sha256 = hashlib.sha256(child_image_bytes).hexdigest()
    if child_sha256 != source.asset_sha256:
        raise ComponentMapError(
            "component-map evidence can only cross a byte-identical revision",
            code="component_map_identical_raster_required",
        )
    payload = source.model_dump(mode="json")
    payload.update({
        "asset_id": child_asset_id,
        "asset_sha256": child_sha256,
        "mapper_contract": "facetta.byte-identical-map-copy.v1",
        "components": [
            {
                **component,
                # Exact raster identity proves that every stable component on
                # the child is the same observed component as on its parent.
                "parent_component_id": component["component_id"],
            }
            for component in payload["components"]
        ],
    })
    child = RevisionComponentMap.model_validate(payload)
    return add_revision_component_map(
        db,
        child,
        image_bytes=child_image_bytes,
        parent_asset_id=source_asset_id,
    )

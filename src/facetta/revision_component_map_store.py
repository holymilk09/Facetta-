"""Persistence boundary for immutable revision component maps."""

from __future__ import annotations

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
    component_map = RevisionComponentMap.model_validate(record.map_json)
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

"""Truthful component-target lineage for catalog revision children.

The v1 contract is deliberately ring-only.  A material-only catalog edit may
carry the source revision's normalized regions forward only when the child is
the same raster size.  Structural edits never copy or infer geometry: a
calibrated mapper must observe the child raster and return a map whose parent
identities reconcile exactly.
"""

from __future__ import annotations

import hashlib
import io
from typing import Protocol

from PIL import Image, ImageOps
from sqlalchemy.orm import Session

from facetta.revision_component_map import (
    ComponentMapError,
    ComponentMappingUnresolved,
    RevisionComponentMap,
    bind_map_to_raster,
    reconcile_parent_component_ids,
)
from facetta.revision_component_map_store import load_revision_component_map


RING_CATALOG_TARGET_KINDS: dict[str, tuple[str, ...]] = {
    "stone.cut": ("center_stone",),
    "stone.color": ("center_stone",),
    "setting.style": ("prongs", "setting"),
    "metal.material": (
        "prongs",
        "setting",
        "shank",
        "shoulders",
        "gallery",
        "metal_zone",
    ),
    "metal.color": (
        "prongs",
        "setting",
        "shank",
        "shoulders",
        "gallery",
        "metal_zone",
    ),
}

# These paths alter appearance/material truth while explicitly freezing every
# target component's geometry in the catalog contract.  No other path may use
# a copied map.
MATERIAL_ONLY_CATALOG_PATHS = frozenset(
    {
        "stone.color",
        "metal.material",
        "metal.color",
    }
)

_MATERIAL_ONLY_SPEC_PATHS: dict[str, frozenset[str]] = {
    "stone.color": frozenset(
        {
            "stone.species",
            "stone.color",
            "stone.carat",
            "stone.clarity",
            "stone.origin",
            "stone.treatment",
            "stone.phenomena",
        }
    ),
    "metal.material": frozenset(
        {"metal.material", "metal.karat", "metal.color"}
    ),
    "metal.color": frozenset({"metal.color"}),
}


class CatalogStructuralComponentMapper(Protocol):
    def __call__(
        self,
        *,
        parent_map: RevisionComponentMap,
        parent_image: bytes,
        child_asset_id: str,
        child_image: bytes,
        target_component_ids: tuple[str, ...],
        component_path: str,
        instruction: str,
    ) -> RevisionComponentMap: ...


_configured_structural_mapper: CatalogStructuralComponentMapper | None = None


def configure_catalog_structural_component_mapper(
    mapper: CatalogStructuralComponentMapper | None,
) -> None:
    """Install a calibrated mapper; ``None`` restores fail-closed behavior."""
    global _configured_structural_mapper
    _configured_structural_mapper = mapper


def catalog_structural_component_mapper_available() -> bool:
    """Report whether structural candidates can preserve map continuity."""
    return _configured_structural_mapper is not None


def _raster_size(image_bytes: bytes) -> tuple[int, int]:
    try:
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(image_bytes)))
        image.load()
    except Exception as exc:
        raise ComponentMapError(
            "the catalog child is not a decodable raster",
            code="catalog_child_raster_invalid",
        ) from exc
    return image.size


def _copy_material_map(
    parent_map: RevisionComponentMap,
    *,
    child_asset_id: str,
    child_image: bytes,
) -> RevisionComponentMap:
    """Rebind unchanged normalized regions to an appearance-only child."""
    if _raster_size(child_image) != (
        parent_map.raster_width,
        parent_map.raster_height,
    ):
        raise ComponentMapError(
            "material-only component regions cannot be copied across raster sizes",
            code="material_component_map_copy_unsafe",
        )
    payload = parent_map.model_dump(mode="json")
    payload.update(
        {
            "asset_id": child_asset_id,
            "asset_sha256": hashlib.sha256(child_image).hexdigest(),
            "mapper_contract": "facetta.material-only-map-copy.v1",
        }
    )
    child_map = RevisionComponentMap.model_validate(payload)
    bind_map_to_raster(child_map, child_image)
    return child_map


def prepare_catalog_child_component_map(
    db: Session,
    *,
    source_asset_id: str,
    source_image: bytes,
    child_asset_id: str,
    child_image: bytes,
    jewelry_type: str,
    component_path: str,
    target_component_ids: tuple[str, ...],
    changed_spec_paths: tuple[str, ...],
    instruction: str,
) -> RevisionComponentMap | None:
    """Return a validated child map or fail before canonical persistence.

    Non-ring component maps are outside v1 and therefore return ``None``.
    Ring callers must already have a source map; accepting a generated child
    without one would sever exact component targeting lineage.
    """
    if jewelry_type != "ring":
        return None
    parent_map = load_revision_component_map(db, source_asset_id)
    if parent_map is None:
        raise ComponentMapError(
            "the source ring revision is explicitly unmapped",
            code="component_map_not_found",
        )
    if component_path in MATERIAL_ONLY_CATALOG_PATHS:
        allowed = _MATERIAL_ONLY_SPEC_PATHS[component_path]
        if not changed_spec_paths or not set(changed_spec_paths).issubset(allowed):
            raise ComponentMapError(
                "the catalog delta is not evidence-safe for a material map copy",
                code="material_component_map_copy_unsafe",
            )
        return _copy_material_map(
            parent_map,
            child_asset_id=child_asset_id,
            child_image=child_image,
        )
    if component_path not in RING_CATALOG_TARGET_KINDS:
        raise ComponentMapError(
            "this ring catalog path has no released component-target policy",
            code="catalog_target_mapping_unavailable",
        )
    if not target_component_ids:
        raise ComponentMapError(
            "the structural catalog candidate has no exact mapped targets",
            code="catalog_target_unmapped",
        )
    mapper = _configured_structural_mapper
    if mapper is None:
        raise ComponentMappingUnresolved(
            "a calibrated catalog child mapper is required for structural edits"
        )
    proposed = mapper(
        parent_map=parent_map,
        parent_image=source_image,
        child_asset_id=child_asset_id,
        child_image=child_image,
        target_component_ids=target_component_ids,
        component_path=component_path,
        instruction=instruction,
    )
    if proposed.asset_id != child_asset_id:
        raise ComponentMappingUnresolved(
            "the catalog child mapper bound its map to the wrong asset"
        )
    reconciled = reconcile_parent_component_ids(parent_map, proposed)
    bind_map_to_raster(reconciled, child_image)
    return reconciled

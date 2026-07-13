"""Immutable, raster-bound semantic component maps for visual revisions.

The map is image-editing evidence, not a specification, DesignForm, CAD
surface, or source-coverage assertion.  Its normalized polygons authorize an
image-agent mask for one exact immutable asset raster.  Geometry is never
inferred by this module: a vision mapper must supply it, and unresolved maps
fail closed.
"""

from __future__ import annotations

import hashlib
import io
import json
from typing import Annotated, Literal, Protocol

from PIL import Image, ImageDraw, ImageOps
from pydantic import BaseModel, ConfigDict, Field, model_validator

from facetta.design_form import NormalizedPolygon


class _FrozenStrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


ComponentId = Annotated[
    str,
    Field(
        strict=True,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$",
    ),
]
ComponentKind = Literal[
    "center_stone",
    "stone_group",
    "prongs",
    "setting",
    "shank",
    "shoulders",
    "gallery",
    "metal_zone",
    "background",
]
ResolutionStatus = Literal["resolved", "unresolved"]


class ComponentMapError(ValueError):
    """A component map cannot safely authorize a localized edit."""

    def __init__(self, detail: str, *, code: str = "component_map_invalid"):
        super().__init__(detail)
        self.detail = detail
        self.code = code


class ComponentMappingUnresolved(ComponentMapError):
    """Vision did not produce a safe child-revision map."""

    def __init__(self, detail: str = "component mapping is unresolved"):
        super().__init__(detail, code="component_mapping_unresolved")


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def polygon_hash(polygons: tuple[NormalizedPolygon, ...]) -> str:
    payload = [
        [[point.x, point.y] for point in polygon.points]
        for polygon in polygons
    ]
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


class RevisionComponent(_FrozenStrictModel):
    component_id: ComponentId
    kind: ComponentKind
    label: Annotated[str, Field(strict=True, min_length=1, max_length=120)]
    resolution: ResolutionStatus
    polygons: tuple[NormalizedPolygon, ...] = ()
    polygon_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")] | None = None
    # On a child revision the mapper states which parent identity it observed.
    # Reconciliation replaces an unstable proposed ID with this stable ID.
    parent_component_id: ComponentId | None = None

    @model_validator(mode="after")
    def bind_resolution_to_geometry(self) -> "RevisionComponent":
        if self.resolution == "resolved":
            if not self.polygons:
                raise ValueError("resolved components require polygons")
            expected = polygon_hash(self.polygons)
            if self.polygon_sha256 != expected:
                raise ValueError(
                    "polygon_sha256 must bind the canonical normalized polygons"
                )
        elif self.polygons or self.polygon_sha256 is not None:
            raise ValueError("unresolved components cannot carry guessed polygons")
        return self


RING_REQUIRED_KINDS = frozenset({
    "center_stone",
    "prongs",
    "setting",
    "shank",
    "shoulders",
    "gallery",
    "metal_zone",
    "background",
})
RING_SINGLETON_KINDS = frozenset({
    "center_stone",
    "setting",
    "shank",
    "gallery",
    "background",
})


class RevisionComponentMap(_FrozenStrictModel):
    schema_version: Literal["facetta.revision-component-map.v1"] = (
        "facetta.revision-component-map.v1"
    )
    asset_id: Annotated[
        str,
        Field(strict=True, min_length=1, max_length=128,
              pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"),
    ]
    asset_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    raster_width: Annotated[int, Field(strict=True, ge=1, le=32768)]
    raster_height: Annotated[int, Field(strict=True, ge=1, le=32768)]
    jewelry_type: Literal["ring"]
    mapper_contract: Annotated[
        str,
        Field(strict=True, min_length=1, max_length=80),
    ]
    # Present only when an automatic mapper was activated against an external,
    # approved frozen evaluation artifact. The digest is provenance, not a
    # claim that these image polygons are factory geometry.
    calibration_evidence_sha256: Annotated[
        str,
        Field(pattern=r"^[0-9a-f]{64}$"),
    ] | None = None
    components: Annotated[tuple[RevisionComponent, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_inventory(self) -> "RevisionComponentMap":
        ids = [component.component_id for component in self.components]
        if len(ids) != len(set(ids)):
            raise ValueError("component IDs must be unique within one revision")
        kinds = {component.kind for component in self.components}
        missing = sorted(RING_REQUIRED_KINDS - kinds)
        if missing:
            raise ValueError(
                "ring component inventory is missing required kinds: "
                + ", ".join(missing)
            )
        for singleton in RING_SINGLETON_KINDS:
            if sum(c.kind == singleton for c in self.components) != 1:
                raise ValueError(
                    f"ring component inventory requires exactly one {singleton}"
                )
        return self

    def component(self, component_id: str) -> RevisionComponent:
        found = next(
            (component for component in self.components
             if component.component_id == component_id),
            None,
        )
        if found is None:
            raise ComponentMapError(
                f"component {component_id!r} is not in revision {self.asset_id!r}",
                code="target_component_not_found",
            )
        if found.resolution != "resolved":
            raise ComponentMapError(
                f"component {component_id!r} is unresolved on this revision",
                code="target_component_unresolved",
            )
        return found


def component_map_hash(component_map: RevisionComponentMap) -> str:
    return hashlib.sha256(_canonical_json(
        component_map.model_dump(mode="json")
    )).hexdigest()


def bind_map_to_raster(
    component_map: RevisionComponentMap,
    image_bytes: bytes,
) -> None:
    """Prove the domain record names the exact decoded asset raster."""
    if hashlib.sha256(image_bytes).hexdigest() != component_map.asset_sha256:
        raise ComponentMapError(
            "component map asset hash does not match the raster bytes",
            code="component_map_raster_hash_mismatch",
        )
    try:
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(image_bytes)))
        image.load()
    except Exception as exc:
        raise ComponentMapError(
            "component map asset is not a decodable raster",
            code="component_map_raster_invalid",
        ) from exc
    if image.size != (component_map.raster_width, component_map.raster_height):
        raise ComponentMapError(
            "component map raster dimensions do not match the asset",
            code="component_map_raster_size_mismatch",
        )


def reconcile_parent_component_ids(
    parent: RevisionComponentMap,
    proposed_child: RevisionComponentMap,
) -> RevisionComponentMap:
    """Preserve stable parent IDs and reject ambiguous mapper identities."""
    parent_by_id = {item.component_id: item for item in parent.components}
    reconciled: list[RevisionComponent] = []
    claimed: set[str] = set()
    for component in proposed_child.components:
        parent_id = component.parent_component_id
        if parent_id is None:
            if component.component_id in parent_by_id:
                raise ComponentMappingUnresolved(
                    f"component {component.component_id!r} reused a parent ID "
                    "without explicit reconciliation evidence"
                )
            reconciled.append(component)
            continue
        parent_component = parent_by_id.get(parent_id)
        if parent_component is None:
            raise ComponentMappingUnresolved(
                f"mapper referenced unknown parent component {parent_id!r}"
            )
        if parent_id in claimed:
            raise ComponentMappingUnresolved(
                f"multiple child components claim parent {parent_id!r}"
            )
        if parent_component.kind != component.kind:
            raise ComponentMappingUnresolved(
                f"component kind changed while reconciling {parent_id!r}"
            )
        claimed.add(parent_id)
        reconciled.append(component.model_copy(update={
            "component_id": parent_id,
        }))

    # Required semantic identities may not silently disappear. Structural
    # edits that truly remove a group keep the stable component unresolved;
    # they do not allow the mapper to pretend it never existed.
    parent_ids = {item.component_id for item in parent.components}
    if not parent_ids.issubset(claimed):
        missing = sorted(parent_ids - claimed)
        raise ComponentMappingUnresolved(
            "mapper did not reconcile parent components: "
            + ", ".join(missing)
        )
    payload = proposed_child.model_dump(mode="json")
    payload["components"] = [
        component.model_dump(mode="json") for component in reconciled
    ]
    return RevisionComponentMap.model_validate(payload)


def rasterize_component_mask(
    component_map: RevisionComponentMap,
    component_id: str,
) -> bytes:
    """Rasterize white-edit/black-preserve polygons at the bound dimensions."""
    return rasterize_component_masks(component_map, (component_id,))


def rasterize_component_masks(
    component_map: RevisionComponentMap,
    component_ids: tuple[str, ...],
) -> bytes:
    """Rasterize the exact union of resolved semantic component regions.

    Catalog edits can legitimately target a semantic aggregate (for example,
    all visible ring metal).  The aggregate must still be made exclusively
    from resolved identities in one immutable, raster-bound component map.
    Missing, unresolved, or empty target sets fail before any image provider
    can receive the request.
    """
    if not component_ids:
        raise ComponentMapError(
            "a component edit requires at least one mapped target",
            code="target_component_required",
        )
    if len(component_ids) != len(set(component_ids)):
        raise ComponentMapError(
            "component edit targets must be unique",
            code="target_component_duplicate",
        )
    components = tuple(
        component_map.component(component_id)
        for component_id in component_ids
    )
    mask = Image.new(
        "L", (component_map.raster_width, component_map.raster_height), 0
    )
    draw = ImageDraw.Draw(mask)
    max_x = component_map.raster_width - 1
    max_y = component_map.raster_height - 1
    for component in components:
        for polygon in component.polygons:
            draw.polygon(
                [(round(point.x * max_x), round(point.y * max_y))
                 for point in polygon.points],
                fill=255,
            )
    if mask.getbbox() is None:
        raise ComponentMapError(
            "mapped target regions rasterized to an empty mask",
            code="target_component_mask_empty",
        )
    output = io.BytesIO()
    mask.save(output, format="PNG", optimize=True)
    return output.getvalue()


class RevisionComponentMapper(Protocol):
    def __call__(
        self,
        *,
        parent_map: RevisionComponentMap,
        parent_image: bytes,
        child_asset_id: str,
        child_image: bytes,
        target_component_id: str,
        instruction: str,
    ) -> RevisionComponentMap: ...


def unresolved_revision_component_mapper(**_kwargs) -> RevisionComponentMap:
    """Production-safe seam until a calibrated vision mapper is configured."""
    raise ComponentMappingUnresolved(
        "the revision component vision mapper is not configured"
    )

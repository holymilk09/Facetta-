"""Attestable ring component mapping for exact-revision image edits.

The mapper observes image-space semantic regions only.  Its polygons authorize
localized raster editing; they are never CAD, measurements, setting-engineering
evidence, or manufacturing authority.  Production activation is handled by a
separate composition boundary and remains fail-closed without externally
approved calibration evidence.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
from collections.abc import Callable
from typing import Literal

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from facetta.design_form import NormalizedPoint, NormalizedPolygon
from facetta.image_agent.vision import PairInspector, vision_json, vision_json_pair
from facetta.revision_component_map import (
    ComponentKind,
    ComponentMappingUnresolved,
    RevisionComponent,
    RevisionComponentMap,
    bind_map_to_raster,
    polygon_hash,
)


GROK_RING_COMPONENT_MAPPER_CONTRACT = "facetta.grok-ring-component-map.v1"
GROK_RING_COMPONENT_MAPPER_PATHS = frozenset({"stone.cut"})
_MIN_NON_TARGET_IOU = 0.85
_MIN_CHANGED_PIXEL_COVERAGE = 0.90
_MIN_CHANGED_PIXELS = 12
_PIXEL_CHANGE_THRESHOLD = 12

# These thresholds are part of ``GROK_RING_COMPONENT_MAPPER_CONTRACT``.  They
# are deliberately conservative for the released white-background/product-view
# ring slice.  Changing one requires a new mapper contract and frozen-corpus
# evidence; an extreme crop falls back to Describe/Mark up rather than silently
# widening image-edit authority.
_SOURCE_KIND_FRAME_AREA = {
    "center_stone": (0.0025, 0.25),
    "prongs": (0.0005, 0.15),
    "setting": (0.001, 0.30),
}
_MIN_SOURCE_TARGET_FRAME_AREA = 0.005
_MAX_SOURCE_TARGET_FRAME_AREA = 0.40
_MAX_TARGET_FOREGROUND_SHARE = 0.85
_MAX_BACKGROUND_FOREGROUND_OVERLAP = 0.01
_MAX_TARGET_UNRELATED_OVERLAP = 0.05
_MAX_CENTER_HOLDER_OVERLAP = 0.20
_MAX_CHILD_TARGET_UNRELATED_OVERLAP = 0.10
_MAX_CHILD_UNRELATED_OVERLAP_GROWTH = 0.05
_CHILD_KIND_AREA_RATIO = {
    "center_stone": (0.65, 1.45),
    "prongs": (0.60, 1.60),
    "setting": (0.60, 1.60),
}
_MIN_CHILD_TARGET_AREA_RATIO = 0.65
_MAX_CHILD_TARGET_AREA_RATIO = 1.45
_MIN_TARGET_IOU = 0.55
_MAX_TARGET_CENTER_SHIFT = 0.04
_MAX_CENTER_STONE_SHIFT = 0.03
_MIN_CENTER_BBOX_RATIO = 0.75
_MAX_CENTER_BBOX_RATIO = 1.33
_MIN_CHILD_TARGET_IN_SOURCE_ENVELOPE = 0.85
_SOURCE_AUTHORIZATION_DILATION = 0.025
_TARGET_ADJACENCY_DILATION = 0.02
_SETTING_ENVELOPE_DILATION = 0.04

_TARGET_KINDS = ("center_stone", "prongs", "setting")
_UNRELATED_KINDS = (
    "stone_group",
    "shank",
    "shoulders",
    "gallery",
)
_LEAF_FOREGROUND_KINDS = (
    "center_stone",
    "stone_group",
    "prongs",
    "setting",
    "shank",
    "shoulders",
    "gallery",
)


SingleInspector = Callable[[str, bytes, str], dict]


class _ObservedPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)


class _ObservedPolygon(BaseModel):
    model_config = ConfigDict(extra="forbid")

    points: tuple[_ObservedPoint, ...] = Field(min_length=3)


class _ObservedComponent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent_component_id: str
    kind: ComponentKind
    resolution: Literal["resolved", "unresolved"]
    polygons: tuple[_ObservedPolygon, ...] = ()


class _ObservedMap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    components: tuple[_ObservedComponent, ...] = Field(min_length=1)


_MAPPER_SYSTEM = """\
You are an exact-revision jewelry IMAGE segmentation system. You receive one
or two images and a required semantic component inventory. Return normalized
image-space polygons for every inventory item. These polygons authorize only
localized raster editing. They are not dimensions, CAD, construction proof,
manufacturing guidance, or evidence that a design is physically producible.

Use the stable component IDs and kinds exactly as supplied. Do not add, remove,
merge, split, rename, or reinterpret components. A polygon must be a simple,
non-self-intersecting boundary with coordinates from 0.0 to 1.0. Use
"resolution":"unresolved" and an empty polygons array when a component cannot
be observed confidently; never guess hidden geometry.

Polygons are visible semantic pixel masks, not loose bounding boxes or hidden
part envelopes. Leaf components must not broadly overlap. ``background`` means
only visible empty/background pixels and must never cover the jewelry.
``metal_zone`` is the sole aggregate region and may overlap visible metal leaf
components; it does not relax any leaf-component safety rule.

Return JSON only:
{"components":[{"parent_component_id":"...","kind":"center_stone|stone_group|prongs|setting|shank|shoulders|gallery|metal_zone|background","resolution":"resolved|unresolved","polygons":[{"points":[{"x":0.1,"y":0.2},{"x":0.2,"y":0.2},{"x":0.2,"y":0.3}]}]}]}"""


def _decode_size(image_bytes: bytes) -> tuple[int, int]:
    try:
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(image_bytes)))
        image.load()
    except Exception as exc:
        raise ComponentMappingUnresolved(
            "the component mapper received an invalid raster"
        ) from exc
    return image.size


def _inventory_payload(component_map: RevisionComponentMap) -> list[dict[str, str]]:
    return [
        {
            "component_id": component.component_id,
            "kind": component.kind,
            "label": component.label,
            "required_resolution": component.resolution,
        }
        for component in component_map.components
    ]


def _observations_to_map(
    observed: _ObservedMap,
    *,
    inventory: tuple[RevisionComponent, ...],
    asset_id: str,
    image_bytes: bytes,
    source_inventory: bool = False,
) -> RevisionComponentMap:
    expected = {component.component_id: component for component in inventory}
    received: dict[str, _ObservedComponent] = {}
    for component in observed.components:
        if component.parent_component_id in received:
            raise ComponentMappingUnresolved(
                "the component mapper returned a duplicate stable identity"
            )
        received[component.parent_component_id] = component
    if set(received) != set(expected):
        missing = sorted(set(expected) - set(received))
        extra = sorted(set(received) - set(expected))
        raise ComponentMappingUnresolved(
            "the component mapper changed the required inventory"
            f" (missing={missing}, extra={extra})"
        )

    components: list[RevisionComponent] = []
    for index, parent in enumerate(inventory, start=1):
        item = received[parent.component_id]
        if item.kind != parent.kind:
            raise ComponentMappingUnresolved(
                f"the component mapper changed the kind of {parent.component_id!r}"
            )
        # An exact-revision mapping may not silently degrade or invent a
        # component's observability. Camera/framing are frozen for this slice.
        if not source_inventory and item.resolution != parent.resolution:
            raise ComponentMappingUnresolved(
                f"component {parent.component_id!r} changed resolution state"
            )
        polygons: tuple[NormalizedPolygon, ...] = ()
        digest: str | None = None
        if item.resolution == "resolved":
            if not item.polygons:
                raise ComponentMappingUnresolved(
                    f"component {parent.component_id!r} has no mapped polygons"
                )
            try:
                polygons = tuple(
                    NormalizedPolygon(
                        points=tuple(
                            NormalizedPoint(x=float(point.x), y=float(point.y))
                            for point in polygon.points
                        )
                    )
                    for polygon in item.polygons
                )
            except ValidationError as exc:
                raise ComponentMappingUnresolved(
                    f"component {parent.component_id!r} has unsafe polygons"
                ) from exc
            digest = polygon_hash(polygons)
        elif item.polygons:
            raise ComponentMappingUnresolved(
                f"unresolved component {parent.component_id!r} carried polygons"
            )
        components.append(
            RevisionComponent(
                component_id=(
                    parent.component_id
                    if source_inventory
                    else f"mapped_{index:02d}"
                ),
                kind=parent.kind,
                label=parent.label,
                resolution=item.resolution,
                polygons=polygons,
                polygon_sha256=digest,
                parent_component_id=(
                    None if source_inventory else parent.component_id
                ),
            )
        )

    width, height = _decode_size(image_bytes)
    result = RevisionComponentMap(
        asset_id=asset_id,
        asset_sha256=hashlib.sha256(image_bytes).hexdigest(),
        raster_width=width,
        raster_height=height,
        jewelry_type="ring",
        mapper_contract=GROK_RING_COMPONENT_MAPPER_CONTRACT,
        components=tuple(components),
    )
    bind_map_to_raster(result, image_bytes)
    return result


def _component_mask(
    component: RevisionComponent,
    *,
    width: int,
    height: int,
) -> Image.Image:
    mask = Image.new("1", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    max_x = width - 1
    max_y = height - 1
    for polygon in component.polygons:
        draw.polygon(
            [
                (round(point.x * max_x), round(point.y * max_y))
                for point in polygon.points
            ],
            fill=1,
        )
    return mask


def _mask_union(
    component_map: RevisionComponentMap,
    component_ids: tuple[str, ...],
) -> Image.Image:
    union = Image.new(
        "1", (component_map.raster_width, component_map.raster_height), 0
    )
    for component_id in component_ids:
        component = component_map.component(component_id)
        union = ImageChops.logical_or(
            union,
            _component_mask(
                component,
                width=component_map.raster_width,
                height=component_map.raster_height,
            ),
        )
    return union


def _kind_mask(
    component_map: RevisionComponentMap,
    kind: str,
) -> Image.Image:
    """Return the union of every resolved visible component of one kind."""
    union = Image.new(
        "1", (component_map.raster_width, component_map.raster_height), 0
    )
    for component in component_map.components:
        if component.kind != kind or component.resolution != "resolved":
            continue
        union = ImageChops.logical_or(
            union,
            _component_mask(
                component,
                width=component_map.raster_width,
                height=component_map.raster_height,
            ),
        )
    return union


def _kind_union(
    component_map: RevisionComponentMap,
    kinds: tuple[str, ...],
) -> Image.Image:
    union = Image.new(
        "1", (component_map.raster_width, component_map.raster_height), 0
    )
    for kind in kinds:
        union = ImageChops.logical_or(union, _kind_mask(component_map, kind))
    return union


def _mask_count(mask: Image.Image) -> int:
    return mask.convert("L").histogram()[255]


def _intersection_count(first: Image.Image, second: Image.Image) -> int:
    return _mask_count(ImageChops.logical_and(first, second))


def _overlap_of_smaller(first: Image.Image, second: Image.Image) -> float:
    smaller = min(_mask_count(first), _mask_count(second))
    if smaller == 0:
        return 0.0
    return _intersection_count(first, second) / smaller


def _dilate(mask: Image.Image, radius: int) -> Image.Image:
    """Dilate in bounded C-backed steps instead of one unbounded rank kernel."""
    expanded = mask
    remaining = max(0, radius)
    while remaining:
        step = min(15, remaining)
        expanded = expanded.filter(ImageFilter.MaxFilter(2 * step + 1))
        remaining -= step
    return expanded


def _diagonal(component_map: RevisionComponentMap) -> float:
    return math.hypot(component_map.raster_width, component_map.raster_height)


def _normalized_bbox_center(mask: Image.Image) -> tuple[float, float]:
    bounds = mask.getbbox()
    if bounds is None:
        raise ComponentMappingUnresolved("a required semantic mask is empty")
    left, top, right, bottom = bounds
    return (
        ((left + right) / 2) / mask.width,
        ((top + bottom) / 2) / mask.height,
    )


def _normalized_bbox_size(mask: Image.Image) -> tuple[float, float]:
    bounds = mask.getbbox()
    if bounds is None:
        raise ComponentMappingUnresolved("a required semantic mask is empty")
    left, top, right, bottom = bounds
    return ((right - left) / mask.width, (bottom - top) / mask.height)


def _normalized_center_distance(
    first: Image.Image,
    second: Image.Image,
) -> float:
    first_bounds = first.getbbox()
    second_bounds = second.getbbox()
    if first_bounds is None or second_bounds is None:
        raise ComponentMappingUnresolved("a required semantic mask is empty")
    first_x = (first_bounds[0] + first_bounds[2]) / 2
    first_y = (first_bounds[1] + first_bounds[3]) / 2
    second_x = (second_bounds[0] + second_bounds[2]) / 2
    second_y = (second_bounds[1] + second_bounds[3]) / 2
    return math.hypot(first_x - second_x, first_y - second_y) / math.hypot(
        first.width,
        first.height,
    )


def _expanded_bbox_mask(mask: Image.Image, radius: int) -> Image.Image:
    bounds = mask.getbbox()
    if bounds is None:
        raise ComponentMappingUnresolved("a required semantic mask is empty")
    left, top, right, bottom = bounds
    output = Image.new("1", mask.size, 0)
    ImageDraw.Draw(output).rectangle(
        (
            max(0, left - radius),
            max(0, top - radius),
            min(mask.width - 1, right - 1 + radius),
            min(mask.height - 1, bottom - 1 + radius),
        ),
        fill=1,
    )
    return output


def _absolute_semantic_masks(
    component_map: RevisionComponentMap,
    *,
    stage: Literal["source", "child"],
) -> dict[str, Image.Image]:
    """Reject masks that cannot safely authorize a localized ring cut edit."""
    masks = {
        kind: _kind_mask(component_map, kind)
        for kind in (
            *_TARGET_KINDS,
            *_UNRELATED_KINDS,
            "background",
        )
    }
    target = _kind_union(component_map, _TARGET_KINDS)
    foreground = _kind_union(component_map, _LEAF_FOREGROUND_KINDS)
    frame_area = component_map.raster_width * component_map.raster_height

    for kind, (minimum, maximum) in _SOURCE_KIND_FRAME_AREA.items():
        fraction = _mask_count(masks[kind]) / frame_area
        if not minimum <= fraction <= maximum:
            raise ComponentMappingUnresolved(
                f"{stage} {kind} semantic area is outside the released range"
            )
    target_fraction = _mask_count(target) / frame_area
    if not _MIN_SOURCE_TARGET_FRAME_AREA <= target_fraction <= (
        _MAX_SOURCE_TARGET_FRAME_AREA
    ):
        raise ComponentMappingUnresolved(
            f"{stage} cut target area exceeds the released localization range"
        )
    foreground_count = _mask_count(foreground)
    if foreground_count == 0 or (
        _mask_count(target) / foreground_count > _MAX_TARGET_FOREGROUND_SHARE
    ):
        raise ComponentMappingUnresolved(
            f"{stage} cut target consumes too much of the visible jewelry"
        )
    if _overlap_of_smaller(masks["background"], foreground) > (
        _MAX_BACKGROUND_FOREGROUND_OVERLAP
    ):
        raise ComponentMappingUnresolved(
            f"{stage} background semantic mask covers visible jewelry"
        )
    for kind in _UNRELATED_KINDS:
        if _overlap_of_smaller(target, masks[kind]) > (
            _MAX_TARGET_UNRELATED_OVERLAP
        ):
            raise ComponentMappingUnresolved(
                f"{stage} cut target overlaps unrelated {kind} pixels"
            )
    for holder in ("prongs", "setting"):
        if _overlap_of_smaller(masks["center_stone"], masks[holder]) > (
            _MAX_CENTER_HOLDER_OVERLAP
        ):
            raise ComponentMappingUnresolved(
                f"{stage} center stone broadly overlaps {holder} pixels"
            )

    adjacency_radius = max(1, math.ceil(_TARGET_ADJACENCY_DILATION * _diagonal(
        component_map
    )))
    if _intersection_count(
        _dilate(masks["center_stone"], adjacency_radius), masks["prongs"]
    ) == 0:
        raise ComponentMappingUnresolved(
            f"{stage} prongs are disconnected from the center stone"
        )
    setting_radius = max(1, math.ceil(_SETTING_ENVELOPE_DILATION * _diagonal(
        component_map
    )))
    setting_envelope = _expanded_bbox_mask(masks["setting"], setting_radius)
    prong_count = _mask_count(masks["prongs"])
    if (
        prong_count == 0
        or _intersection_count(masks["prongs"], setting_envelope) / prong_count < 0.90
    ):
        raise ComponentMappingUnresolved(
            f"{stage} prongs fall outside the setting envelope"
        )
    center_x, center_y = _normalized_bbox_center(masks["center_stone"])
    setting_bounds = setting_envelope.getbbox()
    assert setting_bounds is not None
    if not (
        setting_bounds[0] / component_map.raster_width
        <= center_x
        <= setting_bounds[2] / component_map.raster_width
        and setting_bounds[1] / component_map.raster_height
        <= center_y
        <= setting_bounds[3] / component_map.raster_height
    ):
        raise ComponentMappingUnresolved(
            f"{stage} center stone is disconnected from the setting"
        )
    masks["target"] = target
    masks["foreground"] = foreground
    return masks


def _iou(first: Image.Image, second: Image.Image) -> float:
    intersection = ImageChops.logical_and(first, second)
    union = ImageChops.logical_or(first, second)
    union_count = union.convert("L").histogram()[255]
    if union_count == 0:
        return 1.0
    return intersection.convert("L").histogram()[255] / union_count


def _changed_pixel_mask(parent_image: bytes, child_image: bytes) -> Image.Image:
    parent = ImageOps.exif_transpose(
        Image.open(io.BytesIO(parent_image))
    ).convert("RGB")
    child = ImageOps.exif_transpose(
        Image.open(io.BytesIO(child_image))
    ).convert("RGB")
    difference = ImageChops.difference(parent, child)
    return difference.convert("L").point(
        lambda value: 255 if value >= _PIXEL_CHANGE_THRESHOLD else 0,
        mode="1",
    )


def _validate_structural_continuity(
    parent: RevisionComponentMap,
    child: RevisionComponentMap,
    *,
    parent_image: bytes,
    child_image: bytes,
    target_component_ids: tuple[str, ...],
) -> None:
    if (parent.raster_width, parent.raster_height) != (
        child.raster_width,
        child.raster_height,
    ):
        raise ComponentMappingUnresolved(
            "ring structural mapping requires an unchanged raster size"
        )
    source_masks = _absolute_semantic_masks(parent, stage="source")
    child_masks = _absolute_semantic_masks(child, stage="child")
    child_by_parent = {
        component.parent_component_id: component
        for component in child.components
    }
    target_ids = set(target_component_ids)
    for parent_component in parent.components:
        child_component = child_by_parent.get(parent_component.component_id)
        if child_component is None:
            raise ComponentMappingUnresolved(
                "the child map lost a stable component identity"
            )
        if (
            parent_component.component_id not in target_ids
            and parent_component.resolution == "resolved"
        ):
            overlap = _iou(
                _component_mask(
                    parent_component,
                    width=parent.raster_width,
                    height=parent.raster_height,
                ),
                _component_mask(
                    child_component,
                    width=child.raster_width,
                    height=child.raster_height,
                ),
            )
            if overlap < _MIN_NON_TARGET_IOU:
                raise ComponentMappingUnresolved(
                    f"non-target component {parent_component.component_id!r} "
                    "drifted beyond the released mapping threshold"
                )

    for kind, (minimum, maximum) in _CHILD_KIND_AREA_RATIO.items():
        source_area = _mask_count(source_masks[kind])
        child_area = _mask_count(child_masks[kind])
        if source_area == 0 or not minimum <= child_area / source_area <= maximum:
            raise ComponentMappingUnresolved(
                f"child {kind} semantic area drifted beyond the source range"
            )

    source_target_area = _mask_count(source_masks["target"])
    child_target_area = _mask_count(child_masks["target"])
    target_area_ratio = child_target_area / source_target_area
    if not _MIN_CHILD_TARGET_AREA_RATIO <= target_area_ratio <= (
        _MAX_CHILD_TARGET_AREA_RATIO
    ):
        raise ComponentMappingUnresolved(
            "child cut target area drifted beyond the source range"
        )
    if _iou(source_masks["target"], child_masks["target"]) < _MIN_TARGET_IOU:
        raise ComponentMappingUnresolved(
            "child cut target moved beyond the released source region"
        )
    if _normalized_center_distance(
        source_masks["target"], child_masks["target"]
    ) > _MAX_TARGET_CENTER_SHIFT:
        raise ComponentMappingUnresolved(
            "child cut target center moved beyond the released threshold"
        )
    if _normalized_center_distance(
        source_masks["center_stone"], child_masks["center_stone"]
    ) > _MAX_CENTER_STONE_SHIFT:
        raise ComponentMappingUnresolved(
            "child center stone moved beyond the released threshold"
        )
    source_center_size = _normalized_bbox_size(source_masks["center_stone"])
    child_center_size = _normalized_bbox_size(child_masks["center_stone"])
    for axis, source_size, child_size in zip(
        ("width", "height"), source_center_size, child_center_size, strict=True
    ):
        ratio = child_size / source_size
        if not _MIN_CENTER_BBOX_RATIO <= ratio <= _MAX_CENTER_BBOX_RATIO:
            raise ComponentMappingUnresolved(
                f"child center stone {axis} drifted beyond the source range"
            )

    authorization_radius = max(
        1, math.ceil(_SOURCE_AUTHORIZATION_DILATION * _diagonal(parent))
    )
    source_envelope = _dilate(source_masks["target"], authorization_radius)
    child_inside_source = _intersection_count(
        child_masks["target"], source_envelope
    ) / child_target_area
    if child_inside_source < _MIN_CHILD_TARGET_IN_SOURCE_ENVELOPE:
        raise ComponentMappingUnresolved(
            "child cut target escaped the source authorization envelope"
        )
    for kind in _UNRELATED_KINDS:
        source_overlap = _overlap_of_smaller(
            source_masks["target"], source_masks[kind]
        )
        child_overlap = _overlap_of_smaller(
            child_masks["target"], child_masks[kind]
        )
        if (
            child_overlap > _MAX_CHILD_TARGET_UNRELATED_OVERLAP
            and child_overlap
            > source_overlap + _MAX_CHILD_UNRELATED_OVERLAP_GROWTH
        ):
            raise ComponentMappingUnresolved(
                f"child cut target expanded over unrelated {kind} pixels"
            )

    changed = _changed_pixel_mask(parent_image, child_image)
    changed_count = _mask_count(changed)
    if changed_count < _MIN_CHANGED_PIXELS:
        raise ComponentMappingUnresolved(
            "the structural candidate did not make a visible target change"
        )
    # Only the approved source revision may authorize edited pixels.  A model-
    # supplied child polygon is evidence to validate, never authority that can
    # expand the edit region around its own drift.
    covered = ImageChops.logical_and(changed, source_envelope)
    covered_count = _mask_count(covered)
    if covered_count / changed_count < _MIN_CHANGED_PIXEL_COVERAGE:
        raise ComponentMappingUnresolved(
            "the structural pixel change escapes the source authorization envelope"
        )


class GrokRingComponentMapper:
    """Strict Grok adapter for externally calibrated ring cut mapping."""

    mapper_contract = GROK_RING_COMPONENT_MAPPER_CONTRACT
    supported_paths = GROK_RING_COMPONENT_MAPPER_PATHS

    def __init__(
        self,
        *,
        inspect_pair: PairInspector | None = None,
        inspect_single: SingleInspector | None = None,
    ) -> None:
        self._inspect_pair = inspect_pair or vision_json_pair
        self._inspect_single = inspect_single or vision_json

    def map_source(
        self,
        *,
        asset_id: str,
        image: bytes,
    ) -> RevisionComponentMap:
        """Map one ring raster using the stable v1 semantic inventory."""
        inventory = tuple(
            RevisionComponent(
                component_id=component_id,
                kind=kind,
                label=label,
                resolution="unresolved",
            )
            for component_id, kind, label in (
                ("center_stone.main", "center_stone", "Center stone"),
                ("stone_group.side", "stone_group", "Side stones"),
                ("prongs.center", "prongs", "Center prongs"),
                ("setting.center", "setting", "Center setting"),
                ("shank.main", "shank", "Shank"),
                ("shoulders.main", "shoulders", "Shoulders"),
                ("gallery.main", "gallery", "Gallery"),
                ("metal_zone.main", "metal_zone", "Visible metal"),
                ("background.main", "background", "Background"),
            )
        )
        # Source mapping expects the model to resolve every visible inventory
        # item. Build an observation-only inventory rather than pretending the
        # unresolved placeholders are already evidence.
        request_inventory = [
            {
                "component_id": component.component_id,
                "kind": component.kind,
                "label": component.label,
            }
            for component in inventory
        ]
        try:
            raw = self._inspect_single(
                _MAPPER_SYSTEM,
                image,
                "Map this exact ring raster. Required inventory: "
                + json.dumps(request_inventory, separators=(",", ":")),
            )
            observed = _ObservedMap.model_validate(raw)
        except ComponentMappingUnresolved:
            raise
        except Exception as exc:
            raise ComponentMappingUnresolved(
                "the source ring component mapper failed closed"
            ) from exc

        mapped = _observations_to_map(
            observed,
            inventory=inventory,
            asset_id=asset_id,
            image_bytes=image,
            source_inventory=True,
        )
        required_kinds = {"center_stone", "prongs", "setting"}
        if any(
            component.resolution != "resolved"
            for component in mapped.components
            if component.kind in required_kinds
        ):
            raise ComponentMappingUnresolved(
                "the source ring is not mapped for the coupled cut region"
            )
        _absolute_semantic_masks(mapped, stage="source")
        return mapped

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
    ) -> RevisionComponentMap:
        if component_path not in self.supported_paths:
            raise ComponentMappingUnresolved(
                f"{component_path} is not released by this mapper contract"
            )
        bind_map_to_raster(parent_map, parent_image)
        if not target_component_ids:
            raise ComponentMappingUnresolved(
                "a structural child map requires exact target identities"
            )
        for component_id in target_component_ids:
            parent_map.component(component_id)
        prompt = {
            "operation": component_path,
            "instruction": instruction,
            "target_component_ids": list(target_component_ids),
            "required_inventory": _inventory_payload(parent_map),
            "images": {
                "first": "approved exact parent revision",
                "second": "generated temporary child candidate",
            },
        }
        try:
            raw = self._inspect_pair(
                _MAPPER_SYSTEM,
                parent_image,
                child_image,
                "Map the SECOND image and reconcile every item to the FIRST. "
                + json.dumps(prompt, separators=(",", ":")),
            )
            observed = _ObservedMap.model_validate(raw)
            child = _observations_to_map(
                observed,
                inventory=parent_map.components,
                asset_id=child_asset_id,
                image_bytes=child_image,
            )
            _validate_structural_continuity(
                parent_map,
                child,
                parent_image=parent_image,
                child_image=child_image,
                target_component_ids=target_component_ids,
            )
            return child
        except ComponentMappingUnresolved:
            raise
        except Exception as exc:
            raise ComponentMappingUnresolved(
                "the ring structural component mapper failed closed"
            ) from exc

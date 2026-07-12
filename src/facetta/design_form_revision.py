"""Compile one confirmed markup mask into a scoped visual-form spec revision.

This module deliberately performs no provider calls and no persistence.  It
turns the designer's confirmed target element plus the actual edit mask into
image-space provenance, then pins the resulting form to the exact immutable
asset bytes.  The result is useful visual truth, not inferred CAD geometry.
"""

from __future__ import annotations

import hashlib
import io
from collections.abc import Iterable

from PIL import Image, UnidentifiedImageError

from facetta.design_form import (
    DesignForm,
    DesignFormElement,
    DesignFormRegion,
    DimensionedProfileDefinition,
    NormalizedPoint,
    NormalizedPolygon,
    VisualReferenceOnlyDefinition,
    apply_scoped_form_element,
)
from facetta.spec import Spec


class DesignFormRevisionError(ValueError):
    """A confirmed form revision cannot be represented without guessing."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail)


def confirm_dimensioned_form_element(
    spec: Spec,
    *,
    element_id: str,
    definition: DimensionedProfileDefinition,
) -> Spec:
    """Replace one known visual form with explicit confirmed millimeter data.

    The function is pure and never derives points from a raster. Callers own
    actor/source binding and must pass a fully validated definition. Every
    unrelated spec field and design-form element remains byte-for-structure
    unchanged.
    """

    existing = next((
        element
        for element in spec.design_form.elements
        if element.element_id == element_id
    ), None)
    if existing is None:
        raise DesignFormRevisionError(
            "form_element_not_found",
            f"the current spec has no design-form element {element_id!r}",
        )
    if existing.instance_count != 1:
        raise DesignFormRevisionError(
            "full_assembly_profile_requires_single_instance",
            "a full-assembly profile must target one complete stable element; "
            "repeated/paired elements need a shared placement contract first",
        )
    replacement = existing.model_copy(update={"definition": definition})
    try:
        revised_form = apply_scoped_form_element(
            spec.design_form,
            DesignForm(elements=(replacement,)),
            element_id=element_id,
        )
    except ValueError as exc:
        raise DesignFormRevisionError(
            "form_revision_no_change",
            str(exc),
        ) from exc
    raw = spec.model_dump(mode="json")
    raw["design_form"] = revised_form.model_dump(mode="json")
    return Spec.model_validate(raw)


def _cross(
    origin: tuple[int, int],
    first: tuple[int, int],
    second: tuple[int, int],
) -> int:
    return ((first[0] - origin[0]) * (second[1] - origin[1])
            - (first[1] - origin[1]) * (second[0] - origin[0]))


def _convex_hull(points: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    """Return a stable convex isolation contour around non-zero mask pixels."""
    ordered = sorted(set(points))
    if len(ordered) <= 1:
        return ordered
    lower: list[tuple[int, int]] = []
    for point in ordered:
        while len(lower) >= 2 and _cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    upper: list[tuple[int, int]] = []
    for point in reversed(ordered):
        while len(upper) >= 2 and _cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    return lower[:-1] + upper[:-1]


def _sample_contour(
    points: list[tuple[int, int]],
    *,
    limit: int = 32,
) -> list[tuple[int, int]]:
    if len(points) <= limit:
        return points
    indices = sorted({index * len(points) // limit for index in range(limit)})
    return [points[index] for index in indices]


def _connected_components(
    points: set[tuple[int, int]],
) -> list[list[tuple[int, int]]]:
    """Split bilateral/repeated marks so frozen space between them stays out."""
    remaining = set(points)
    components: list[list[tuple[int, int]]] = []
    while remaining:
        seed = min(remaining)
        remaining.remove(seed)
        stack = [seed]
        component = [seed]
        while stack:
            x, y = stack.pop()
            for dx, dy in (
                (-1, -1), (0, -1), (1, -1),
                (-1, 0), (1, 0),
                (-1, 1), (0, 1), (1, 1),
            ):
                neighbor = (x + dx, y + dy)
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    stack.append(neighbor)
                    component.append(neighbor)
        components.append(component)
    components.sort(key=lambda component: min(component))
    return components


def region_from_markup_mask(
    mask_bytes: bytes,
    source_image: bytes,
    *,
    view: str,
) -> DesignFormRegion:
    """Derive normalized provenance from the real same-raster markup mask."""
    try:
        with Image.open(io.BytesIO(source_image)) as source:
            source_size = source.size
        with Image.open(io.BytesIO(mask_bytes)) as mask_image:
            mask = mask_image.convert("L")
    except (UnidentifiedImageError, OSError) as exc:
        raise DesignFormRevisionError(
            "form_mask_invalid",
            "the design-form edit mask is not a readable image",
        ) from exc
    if mask.size != source_size:
        raise DesignFormRevisionError(
            "form_mask_raster_mismatch",
            "the design-form mask must use the source image's exact raster size",
        )
    width, height = mask.size
    if width < 2 or height < 2:
        raise DesignFormRevisionError(
            "form_mask_invalid",
            "the design-form mask raster is too small to define a region",
        )
    pixels = mask.load()
    marked = {
        (x, y)
        for y in range(height)
        for x in range(width)
        if pixels[x, y] > 0
    }
    contours = [
        _sample_contour(_convex_hull(component))
        for component in _connected_components(marked)
    ]
    contours = [contour for contour in contours if len(contour) >= 3]
    if not contours:
        raise DesignFormRevisionError(
            "form_mask_empty",
            "the saved markup does not enclose a usable design-form region",
        )
    try:
        polygons = tuple(
            NormalizedPolygon(points=tuple(
                NormalizedPoint(
                    x=float(x / (width - 1)),
                    y=float(y / (height - 1)),
                )
                for x, y in contour
            ))
            for contour in contours
        )
        return DesignFormRegion(view=view, polygons=polygons)
    except ValueError as exc:
        raise DesignFormRevisionError(
            "form_mask_invalid",
            "the saved markup does not define a valid design-form region",
        ) from exc


def revise_visual_form_element(
    spec: Spec,
    *,
    element_id: str,
    confirmed_form_description: str,
    region: DesignFormRegion,
    asset_id: str,
    asset_bytes: bytes | None = None,
    asset_sha256: str | None = None,
) -> Spec:
    """Replace exactly one existing form element and pin its visual bytes.

    Project creation may initialize elements through the pure design-form
    contract.  An edit must target a known stable ID; Facetta never guesses a
    component identity from free text during mutation.
    """
    existing = next((
        element for element in spec.design_form.elements
        if element.element_id == element_id
    ), None)
    if existing is None:
        raise DesignFormRevisionError(
            "form_element_not_found",
            f"the current spec has no design-form element {element_id!r}",
        )
    description = confirmed_form_description.strip()
    if not description:
        raise DesignFormRevisionError(
            "form_description_required",
            "a design-form edit needs the designer-confirmed target form",
        )
    if asset_sha256 is None:
        if asset_bytes is None:
            raise DesignFormRevisionError(
                "form_reference_hash_required",
                "the exact visual-reference bytes are required",
            )
        asset_sha256 = hashlib.sha256(asset_bytes).hexdigest()
    regions = tuple(
        region if current.view == region.view else current
        for current in existing.regions
    )
    if all(current.view != region.view for current in existing.regions):
        regions = (*regions, region)
    replacement = DesignFormElement(
        element_id=existing.element_id,
        role=existing.role,
        label=existing.label,
        confirmed_form_description=description,
        symmetry=existing.symmetry,
        instance_count=existing.instance_count,
        regions=regions,
        definition=VisualReferenceOnlyDefinition(
            kind="visual_reference_only",
            asset_id=asset_id,
            asset_sha256=asset_sha256,
        ),
    )
    proposed = DesignForm(elements=(replacement,))
    try:
        revised_form = apply_scoped_form_element(
            spec.design_form,
            proposed,
            element_id=element_id,
        )
    except ValueError as exc:
        raise DesignFormRevisionError("form_revision_no_change", str(exc)) from exc
    raw = spec.model_dump(mode="json")
    raw["design_form"] = revised_form.model_dump(mode="json")
    return Spec.model_validate(raw)

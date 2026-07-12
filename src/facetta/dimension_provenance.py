"""Typed provenance and safe promotion rules for factory dimensions.

Reference-derived values are allowed to fill a draft specification so a
designer can start prototyping without measuring every feature.  They remain
explicit estimates until a designer changes/adopts the value in the immutable
version workflow.  No helper in this module changes a physical value.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from facetta.json_types import JsonObject
from facetta.spec import DimensionProvenance, Spec


ESTIMATE_DISCLAIMER = (
    "ESTIMATED dimensions are reference-derived prototyping values, not "
    "measurements. Verify or adjust them before manufacturing; factory and "
    "designer sign-off remain required."
)

_INDEX = re.compile(r"([^[.]+)|\[(\d+)\]")


def is_dimension_path(path: str) -> bool:
    """True only for numeric linear-dimension leaves in the spec schema."""
    leaf = path.rsplit(".", 1)[-1]
    return ("dimensions_mm." in path or leaf.endswith("_mm")
            or path == "ring_size.value")


def value_at_path(spec: Spec, path: str) -> object | None:
    value: Any = spec.model_dump(mode="json")
    try:
        for match in _INDEX.finditer(path):
            key, index = match.groups()
            value = value[int(index)] if index is not None else value[key]
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    return value


def estimated_dimension_summary(spec: Spec) -> JsonObject:
    fields: list[JsonObject] = []
    recorded_paths: set[str] = set()
    for path, provenance in sorted(spec.dimension_provenance.items()):
        if provenance.status != "estimated_from_reference":
            continue
        recorded_paths.add(path)
        fields.append({
            "field_path": path,
            "value": value_at_path(spec, path),
            "unit": (spec.ring_size.system
                     if path == "ring_size.value" and spec.ring_size else "mm"),
            "status": provenance.status,
            "method": provenance.method,
            "source": provenance.source,
            "confidence": provenance.confidence,
            "note": provenance.note,
        })
    # A dimensioned profile carries its own whole-record status because its
    # coordinates are one confirmed geometry, not unrelated AI guesses. Keep
    # every millimeter leaf visible in the manifest without requiring callers
    # to duplicate hundreds of point-level provenance entries.
    for element_index, element in enumerate(spec.design_form.elements):
        definition = element.definition
        if (
            definition.kind != "dimensioned_profile"
            or definition.dimension_status != "designer_confirmed_estimate"
        ):
            continue
        prefix = f"design_form.elements[{element_index}].definition"
        profile_paths = {
            f"{prefix}.profile_thickness_mm",
            *(
                f"{prefix}.paths[{path_index}].nominal_width_mm"
                for path_index, path in enumerate(definition.paths)
                if path.nominal_width_mm is not None
            ),
            *(
                f"{prefix}.paths[{path_index}].points[{point_index}].{axis}_mm"
                for path_index, path in enumerate(definition.paths)
                for point_index, _point in enumerate(path.points)
                for axis in ("x", "y")
            ),
        }
        for path in sorted(profile_paths - recorded_paths):
            fields.append({
                "field_path": path,
                "value": value_at_path(spec, path),
                "unit": "mm",
                "status": "estimated_from_reference",
                "method": "designer_confirmation",
                "source": definition.source_asset_id,
                "confidence": None,
                "note": definition.manufacturing_notes,
            })
    return {
        "has_estimates": bool(fields),
        "estimated_fields": fields,
        "disclaimer": ESTIMATE_DISCLAIMER if fields else None,
    }


def estimate_marker(spec: Spec, *paths: str) -> str:
    """A compact label suffix when any contributing dimension is estimated."""
    if any(
        (item := spec.dimension_provenance.get(path)) is not None
        and item.status == "estimated_from_reference"
        for path in paths
    ):
        return " EST."
    return ""


def _changed_dimension_paths(before: Any, after: Any, prefix: str = "") -> set[str]:
    if isinstance(before, dict) or isinstance(after, dict):
        b = before if isinstance(before, dict) else {}
        a = after if isinstance(after, dict) else {}
        out: set[str] = set()
        for key in set(b) | set(a):
            if not prefix and key == "dimension_provenance":
                continue
            path = f"{prefix}.{key}" if prefix else key
            out |= _changed_dimension_paths(b.get(key), a.get(key), path)
        return out
    if isinstance(before, list) or isinstance(after, list):
        b = before if isinstance(before, list) else []
        a = after if isinstance(after, list) else []
        out = set()
        for index in range(max(len(b), len(a))):
            bv = b[index] if index < len(b) else None
            av = a[index] if index < len(a) else None
            out |= _changed_dimension_paths(bv, av, f"{prefix}[{index}]")
        return out
    return {prefix} if before != after and is_dimension_path(prefix) else set()


def _dimension_paths(value: Any, prefix: str = "") -> set[str]:
    if isinstance(value, dict):
        out: set[str] = set()
        for key, child in value.items():
            if not prefix and key == "dimension_provenance":
                continue
            path = f"{prefix}.{key}" if prefix else key
            out |= _dimension_paths(child, path)
        return out
    if isinstance(value, list):
        out = set()
        for index, child in enumerate(value):
            out |= _dimension_paths(child, f"{prefix}[{index}]")
        return out
    return {prefix} if value is not None and is_dimension_path(prefix) else set()


def with_reference_dimension_estimates(
    spec: Spec,
    *,
    source: str,
    method: Literal[
        "reference_vision", "scaled_reference", "nominal_reference"
    ] = "reference_vision",
    confidence: float | None = None,
) -> Spec:
    """Mark every unprovenanced mm value as a reference estimate.

    Existing provenance always wins, so designer-confirmed fields are never
    downgraded when a draft is recompiled or completed.
    """
    provenance = dict(spec.dimension_provenance)
    for path in _dimension_paths(spec.model_dump(mode="json")):
        provenance.setdefault(path, DimensionProvenance(
            status="estimated_from_reference",
            method=method,
            source=source,
            confidence=confidence,
            note="Reference-derived starting value; verify before production.",
        ))
    return spec.model_copy(update={"dimension_provenance": provenance})


def mark_designer_adjusted_dimensions(before: Spec, after: Spec) -> Spec:
    """Promote only dimensions the designer actually changed/adopted.

    This is called by the existing scoped/versioned edit boundary.  Physical
    values still come from that boundary and still pass normal validation; the
    helper only updates their audit metadata in the new immutable version.
    """
    changed = _changed_dimension_paths(
        before.model_dump(mode="json"), after.model_dump(mode="json"))
    if not changed:
        return after
    provenance = dict(after.dimension_provenance)
    for path in changed:
        previous = provenance.get(path) or before.dimension_provenance.get(path)
        provenance[path] = DimensionProvenance(
            status="designer_confirmed",
            method="designer_input",
            source="designer-adjusted immutable spec version",
            confidence=1.0,
            note=("Replaces a reference estimate."
                  if previous is not None
                  and previous.status == "estimated_from_reference"
                  else "Entered or adjusted by the designer."),
        )
    return after.model_copy(update={"dimension_provenance": provenance})


def confirm_designer_dimension_subtree(
    spec: Spec,
    *,
    prefix: str,
    source: str,
    note: str | None = None,
) -> Spec:
    """Confirm every current dimension below one explicitly submitted subtree.

    Catalog target records can repeat a numeric value while changing its
    construction meaning (for example cable to curb). A before/after numeric
    diff would miss that confirmation. This helper first removes stale paths
    from the prior discriminated-union branch, then records every current
    dimension under ``prefix`` as designer-confirmed.
    """
    if not prefix or prefix.endswith("."):
        raise ValueError("dimension subtree prefix must be a canonical path")
    provenance = {
        path: item
        for path, item in spec.dimension_provenance.items()
        if path != prefix and not path.startswith(prefix + ".")
    }
    current_paths = _dimension_paths(spec.model_dump(mode="json"))
    for path in sorted(current_paths):
        if path == prefix or path.startswith(prefix + "."):
            provenance[path] = DimensionProvenance(
                status="designer_confirmed",
                method="designer_input",
                source=source,
                confidence=1.0,
                note=note or "Confirmed with the submitted manufacturing record.",
            )
    return spec.model_copy(update={"dimension_provenance": provenance})


def reconcile_side_stone_inventory_provenance(
    before: Spec,
    after: Spec,
) -> Spec:
    """Carry unchanged group dimensions and estimate every new group safely.

    A whole-inventory edit may add, remove, or reorder groups. Index-based
    provenance cannot simply be copied because ``side_stones[0]`` may now name
    a different stone. Groups with an identical physical identity keep their
    existing per-field provenance at the new index; every unmatched group's
    dimensions are marked as nominal estimates pending designer measurement.
    """

    def signature(stone) -> tuple[object, ...]:
        dims = stone.dimensions_mm
        return (
            stone.species,
            stone.cut,
            stone.position,
            dims.length,
            dims.width,
            dims.depth,
        )

    available: dict[tuple[object, ...], list[int]] = {}
    for index, stone in enumerate(before.side_stones):
        available.setdefault(signature(stone), []).append(index)

    provenance = {
        path: item for path, item in after.dimension_provenance.items()
        if not path.startswith("side_stones[")
    }
    suffixes = (
        "dimensions_mm.length",
        "dimensions_mm.width",
        "dimensions_mm.depth",
    )
    for new_index, stone in enumerate(after.side_stones):
        matches = available.get(signature(stone), [])
        old_index = matches.pop(0) if matches else None
        for suffix in suffixes:
            new_path = f"side_stones[{new_index}].{suffix}"
            old_path = (f"side_stones[{old_index}].{suffix}"
                        if old_index is not None else None)
            previous = (before.dimension_provenance.get(old_path)
                        if old_path is not None else None)
            if previous is not None:
                provenance[new_path] = previous
            elif old_index is None:
                provenance[new_path] = DimensionProvenance(
                    status="estimated_from_reference",
                    method="nominal_reference",
                    source="AI-planned side-stone inventory",
                    confidence=None,
                    note=(
                        "Nominal starting dimension for a new stone group; "
                        "verify or adjust before production."
                    ),
                )
    return after.model_copy(update={"dimension_provenance": provenance})

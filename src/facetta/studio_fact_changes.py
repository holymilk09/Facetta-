"""Typed, provenance-safe edits for designer-reviewable Studio facts.

Both Starting Facts promotion and later Advanced Specifications use this
module.  Keeping the path allowlist and typed mutation in one place prevents
the two interfaces from accepting subtly different design truth.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import ValidationError

from facetta.component_catalog import (
    CatalogSelectionError,
    apply_catalog_selection,
)
from facetta.dimension_provenance import mark_designer_adjusted_dimensions
from facetta.spec import Spec


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
    "setting.prong_tip_mm",
    "band.profile",
    "band.width_mm",
    "band.thickness_mm",
    "ring_size.system",
    "ring_size.value",
})


class StudioFactChangeError(ValueError):
    """A requested fact correction cannot safely update a specification."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class PreparedStudioFactChanges:
    spec: Spec
    original_values: Mapping[str, object]
    corrected_values: Mapping[str, object]
    derived_original_values: Mapping[str, object]
    derived_values: Mapping[str, object]

    @property
    def changed(self) -> bool:
        return bool(self.corrected_values or self.derived_values)


_COUPLED_CATALOG_PATHS = ("metal.material", "setting.style")
_COUPLED_DEPENDENT_PATHS = {
    "metal.material": ("metal.karat", "metal.color"),
    "setting.style": ("setting.prong_count", "setting.prong_tip_mm"),
}
_NO_PRONG_RULE = object()


def _reject_overlapping_paths(changes: Mapping[str, object]) -> None:
    paths = sorted(changes)
    for index, path in enumerate(paths):
        for other in paths[index + 1:]:
            if other.startswith(f"{path}."):
                raise StudioFactChangeError(
                    "fact_path_conflict",
                    f"submit either '{path}' or '{other}', not both",
                )


def _set_fact(raw: dict, path: str, value: object) -> None:
    keys = path.split(".")
    current: object = raw
    for key in keys[:-1]:
        if not isinstance(current, dict) or key not in current:
            raise StudioFactChangeError(
                "fact_path_unavailable",
                f"the active specification has no editable fact path '{path}'",
            )
        current = current[key]
    if not isinstance(current, dict) or keys[-1] not in current:
        raise StudioFactChangeError(
            "fact_path_unavailable",
            f"the active specification has no editable fact path '{path}'",
        )
    current[keys[-1]] = copy.deepcopy(value)


def _fact_value(raw: dict, path: str) -> object:
    current: object = raw
    for key in path.split("."):
        if not isinstance(current, dict) or key not in current:
            raise StudioFactChangeError(
                "fact_path_unavailable",
                f"the active specification has no editable fact path '{path}'",
            )
        current = current[key]
    return copy.deepcopy(current)


def prepare_studio_fact_changes(
    before: Spec,
    changes: Mapping[str, object],
) -> PreparedStudioFactChanges:
    """Apply typed corrections while preserving every untouched fact.

    Only values that actually differ are returned as corrected provenance.
    Reference-derived dimensions that were not edited retain their estimate
    metadata; changed dimensions become designer-confirmed through the shared
    immutable-spec provenance helper.
    """

    unsafe = sorted(set(changes) - DESIGNER_SAFE_FACT_PATHS)
    if unsafe:
        raise StudioFactChangeError(
            "fact_path_not_allowed",
            "these fact paths are not designer-editable: " + ", ".join(unsafe),
        )
    _reject_overlapping_paths(changes)

    before_raw = before.model_dump(mode="json")
    edited = before
    derived_original_values: dict[str, object] = {}
    derived_values: dict[str, object] = {}
    coupled_expected: dict[str, object] = {}
    for path in _COUPLED_CATALOG_PATHS:
        if path not in changes:
            continue
        value = changes[path]
        if _fact_value(before_raw, path) == value:
            continue
        if not isinstance(value, str):
            raise StudioFactChangeError(
                "fact_value_invalid",
                f"'{path}' requires a controlled component option",
            )
        option_id = value
        if path == "metal.material" and value == "gold":
            karat = changes.get("metal.karat", edited.metal.karat if edited.metal else None)
            color = changes.get("metal.color", edited.metal.color if edited.metal else None)
            if not isinstance(karat, int) or not isinstance(color, str):
                raise StudioFactChangeError(
                    "fact_dependency_required",
                    "gold requires both a karat and alloy color",
                )
            option_id = f"gold_{karat}_{color}"
        catalog_input = edited
        if (
            path == "setting.style"
            and option_id in {"4_prong_basket", "6_prong_basket"}
            and "setting.prong_tip_mm" in changes
        ):
            # A bezel truthfully has no active prong-tip gauge. Advanced
            # Specifications can restore a prong construction by submitting
            # the exact catalog style and an explicit gauge in one atomic
            # revision. Seed only that designer-supplied dependency before
            # catalog validation; it is still recorded as an explicit fact,
            # never as an inferred component adjustment.
            catalog_raw = edited.model_dump(mode="json")
            _set_fact(
                catalog_raw,
                "setting.prong_tip_mm",
                changes["setting.prong_tip_mm"],
            )
            try:
                catalog_input = Spec.model_validate(catalog_raw)
            except ValidationError as exc:
                raise StudioFactChangeError(
                    "fact_value_invalid",
                    "setting.prong_tip_mm requires a valid designer-supplied gauge",
                ) from exc
        try:
            selected = apply_catalog_selection(
                catalog_input,
                component_path=path,
                option_id=option_id,
            )
        except CatalogSelectionError as exc:
            raise StudioFactChangeError(
                "fact_value_invalid",
                f"the submitted {path} option is not valid for this design",
            ) from exc
        for change in selected.spec_change:
            changed_path = change.get("path")
            if not isinstance(changed_path, str) or changed_path in changes:
                continue
            derived_original_values.setdefault(changed_path, change.get("before"))
            derived_values[changed_path] = copy.deepcopy(change.get("after"))
        edited = selected.spec
        selected_raw = edited.model_dump(mode="json")
        for dependent_path in _COUPLED_DEPENDENT_PATHS[path]:
            coupled_expected[dependent_path] = _fact_value(
                selected_raw, dependent_path,
            )

    edited_raw = edited.model_dump(mode="json")
    for path in sorted(changes):
        if path in _COUPLED_CATALOG_PATHS:
            continue
        value = changes[path]
        if path in coupled_expected and value != coupled_expected[path]:
            raise StudioFactChangeError(
                "fact_dependency_conflict",
                f"'{path}' conflicts with the selected coupled component",
            )
        _set_fact(edited_raw, path, value)

    if {"ring_size.system", "ring_size.value"} & set(changes):
        ring_size = edited_raw.get("ring_size")
        if isinstance(ring_size, dict):
            # Diameter is deterministic vocabulary output, not a second
            # designer correction. Re-derive it from the submitted size.
            ring_size["inner_diameter_mm"] = None
        provenance = edited_raw.get("dimension_provenance")
        if isinstance(provenance, dict):
            provenance.pop("ring_size.inner_diameter_mm", None)

    try:
        edited = Spec.model_validate(edited_raw)
    except ValidationError as exc:
        raise StudioFactChangeError(
            "fact_value_invalid", "a submitted fact has an invalid typed value",
        ) from exc

    if edited.setting is not None:
        expected_prongs = {
            "4_prong_basket": 4,
            "6_prong_basket": 6,
            "bezel": None,
            "semi_bezel": None,
        }.get(edited.setting.style, _NO_PRONG_RULE)
        if (
            expected_prongs is not _NO_PRONG_RULE
            and edited.setting.prong_count != expected_prongs
        ):
            raise StudioFactChangeError(
                "fact_dependency_conflict",
                "setting.prong_count conflicts with the selected setting style",
            )
        if (
            edited.setting.style in {"bezel", "semi_bezel"}
            and edited.setting.prong_tip_mm is not None
        ):
            raise StudioFactChangeError(
                "fact_dependency_conflict",
                "bezel settings cannot retain a prong-tip dimension",
            )

    normalized = edited.model_dump(mode="json")
    original_values: dict[str, object] = {}
    corrected_values: dict[str, object] = {}
    for path in changes:
        original = _fact_value(before_raw, path)
        corrected = _fact_value(normalized, path)
        if corrected != original:
            original_values[path] = original
            corrected_values[path] = corrected

    if not corrected_values:
        return PreparedStudioFactChanges(
            spec=before,
            original_values={},
            corrected_values={},
            derived_original_values={},
            derived_values={},
        )

    edited = mark_designer_adjusted_dimensions(before, edited)
    return PreparedStudioFactChanges(
        spec=edited,
        original_values=original_values,
        corrected_values=corrected_values,
        derived_original_values=derived_original_values,
        derived_values=derived_values,
    )

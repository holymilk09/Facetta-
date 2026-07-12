"""Pure draft resolution for imported-source component coverage.

The resolver changes only how an already-inventoried, stable source component
maps into an existing draft specification.  It cannot add or delete source
components, mutate specification values, estimate dimensions, or create CAD.
Any changed mapping clears its prior independent audit because that evidence
described the old semantics.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)

from facetta.source_component_coverage import (
    CanonicalSpecPath,
    SourceComponentCoverage,
    SourceCoverageFactoryBlocker,
    SourceVisibleComponent,
    VisibleComponentId,
    source_component_factory_blockers,
)
from facetta.spec import Spec


class _FrozenStrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceCoverageResolutionInvalid(ValueError):
    """A batch attempted to invent, delete, duplicate, or mis-map a component."""


class SourceComponentResolution(_FrozenStrictModel):
    """One designer decision for one existing stable source component."""

    component_id: VisibleComponentId
    canonical_spec_paths: tuple[CanonicalSpecPath, ...] = ()
    unresolved_reason: Annotated[
        str,
        Field(strict=True, min_length=1, max_length=1000),
    ] | None = None

    @field_validator("unresolved_reason")
    @classmethod
    def require_trimmed_reason(cls, value: str | None) -> str | None:
        if value is not None and (value != value.strip() or not value.strip()):
            raise ValueError("unresolved reason must be non-blank and trimmed")
        return value

    @model_validator(mode="after")
    def require_mapping_xor_reason(self) -> SourceComponentResolution:
        has_paths = bool(self.canonical_spec_paths)
        has_reason = self.unresolved_reason is not None
        if has_paths == has_reason:
            raise ValueError(
                "resolution must provide canonical spec paths or an "
                "unresolved reason, but not both"
            )
        if len(set(self.canonical_spec_paths)) != len(self.canonical_spec_paths):
            raise ValueError("canonical spec paths must be unique")
        return self


class SourceCoverageResolutionResult(_FrozenStrictModel):
    """Immutable outcome and source-coverage-only factory readiness."""

    coverage: SourceComponentCoverage | None
    changed_component_ids: tuple[VisibleComponentId, ...] = ()
    invalidated_audit_component_ids: tuple[VisibleComponentId, ...] = ()
    blockers: tuple[SourceCoverageFactoryBlocker, ...] = ()
    factory_ready: bool
    legacy_provenance: bool = False


_CANONICAL_OBJECT_ROOTS = (
    "stone",
    "setting",
    "metal",
    "band",
    "ring_size",
    "bracelet",
    "pendant",
    "chain",
    "brooch",
    "drop",
    "composition",
)
_CANONICAL_PATHS_ADAPTER = TypeAdapter(tuple[CanonicalSpecPath, ...])


def _present_model_paths(prefix: str, value: BaseModel) -> list[str]:
    paths = [prefix]
    for field_name in type(value).model_fields:
        child = getattr(value, field_name)
        if child is None or child == [] or child == () or child == {}:
            continue
        child_path = f"{prefix}.{field_name}"
        if isinstance(child, BaseModel):
            paths.extend(_present_model_paths(child_path, child))
        else:
            paths.append(child_path)
    return paths


def valid_source_component_spec_paths(spec: Spec) -> tuple[CanonicalSpecPath, ...]:
    """Return exact canonical mapping targets present in this draft.

    Paths describe existing structured fields only.  They do not expose notes,
    provenance, image regions, inferred measurements, or manufacturing/CAD
    geometry as source-component mapping targets.
    """

    raw_paths: list[str] = ["jewelry_type", "template"]
    for root in _CANONICAL_OBJECT_ROOTS:
        value = getattr(spec, root)
        if isinstance(value, BaseModel):
            raw_paths.extend(_present_model_paths(root, value))

    for index, stone in enumerate(spec.side_stones):
        raw_paths.extend(_present_model_paths(f"side_stones[{index}]", stone))

    raw_paths.extend(
        f"design_form.elements[{element.element_id}]"
        for element in spec.design_form.elements
    )

    # Every generated value is validated by the public path contract before it
    # can be advertised to a client or accepted by the resolver.
    return _CANONICAL_PATHS_ADAPTER.validate_python(tuple(raw_paths))


def _semantic_resolution(component: SourceVisibleComponent) -> tuple:
    return (
        frozenset(component.canonical_spec_paths),
        component.unresolved_reason,
    )


def resolve_source_component_coverage(
    coverage: SourceComponentCoverage | None,
    resolutions: tuple[SourceComponentResolution, ...],
    *,
    valid_spec_paths: tuple[CanonicalSpecPath, ...],
) -> SourceCoverageResolutionResult:
    """Apply a batch atomically while retaining every stable component.

    All component identities and requested paths are checked before a result is
    constructed.  A validation failure therefore returns no partial draft.
    Unmentioned components retain their exact prior state and position.
    """

    requested_ids = tuple(item.component_id for item in resolutions)
    if len(set(requested_ids)) != len(requested_ids):
        raise SourceCoverageResolutionInvalid(
            "source-component resolution IDs must be unique within a batch"
        )

    if coverage is None:
        if resolutions:
            raise SourceCoverageResolutionInvalid(
                "legacy spec has no source coverage; resolution cannot invent "
                "stable source components"
            )
        return SourceCoverageResolutionResult(
            coverage=None,
            blockers=(),
            factory_ready=True,
            legacy_provenance=True,
        )

    existing_ids = {item.component_id for item in coverage.components}
    unknown_ids = sorted(set(requested_ids) - existing_ids)
    if unknown_ids:
        raise SourceCoverageResolutionInvalid(
            "resolution references unknown stable source component IDs: "
            + ", ".join(unknown_ids)
        )

    valid_paths = set(valid_spec_paths)
    invalid_paths = sorted({
        path
        for item in resolutions
        for path in item.canonical_spec_paths
        if path not in valid_paths
    })
    if invalid_paths:
        raise SourceCoverageResolutionInvalid(
            "resolution references canonical paths absent from this draft: "
            + ", ".join(invalid_paths)
        )

    resolutions_by_id = {item.component_id: item for item in resolutions}
    updated: list[SourceVisibleComponent] = []
    changed_ids: list[str] = []
    invalidated_ids: list[str] = []
    for component in coverage.components:
        resolution = resolutions_by_id.get(component.component_id)
        if resolution is None:
            updated.append(component)
            continue

        proposed_semantics = (
            frozenset(resolution.canonical_spec_paths),
            resolution.unresolved_reason,
        )
        if proposed_semantics == _semantic_resolution(component):
            updated.append(component)
            continue

        payload = component.model_dump(mode="python")
        payload["canonical_spec_paths"] = resolution.canonical_spec_paths
        payload["unresolved_reason"] = resolution.unresolved_reason
        payload["independent_audit"] = None
        updated.append(SourceVisibleComponent.model_validate(payload))
        changed_ids.append(component.component_id)
        if component.independent_audit is not None:
            invalidated_ids.append(component.component_id)

    result_coverage = SourceComponentCoverage(
        source_kind=coverage.source_kind,
        components=tuple(updated),
        audited_spec_visual_hash=(
            None if changed_ids else coverage.audited_spec_visual_hash
        ),
    )
    blockers = source_component_factory_blockers(
        result_coverage,
        valid_spec_paths=valid_spec_paths,
    )
    return SourceCoverageResolutionResult(
        coverage=result_coverage,
        changed_component_ids=tuple(changed_ids),
        invalidated_audit_component_ids=tuple(invalidated_ids),
        blockers=blockers,
        factory_ready=not blockers,
        legacy_provenance=False,
    )

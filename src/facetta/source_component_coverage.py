"""Pure coverage contract for components visible in an imported source.

The sparse :class:`facetta.spec.Spec` cannot safely imply that every visible
part of a designer drawing was captured.  This module makes that accounting
explicit without inventing dimensions, contours, or CAD.  Each source
component is either mapped to one or more canonical spec paths or marked
unresolved.  An independent audit may then confirm that the mapping preserves
the component seen in the source.

``None`` at the ``Spec`` boundary means the record predates this contract.
That legacy state is intentionally readable and non-blocking; new source
imports create a non-empty ``SourceComponentCoverage`` record.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _FrozenStrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


VisibleComponentId: TypeAlias = Annotated[
    str,
    Field(
        strict=True,
        min_length=1,
        max_length=96,
        pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$",
    ),
]

CanonicalSpecPath: TypeAlias = Annotated[
    str,
    Field(
        strict=True,
        pattern=(
            r"^(?:(?:jewelry_type|template|stone|setting|metal|band|ring_size|"
            r"bracelet|pendant|chain|brooch|drop|composition|"
            r"side_stones\[(?:0|[1-9][0-9]*)\])"
            r"(?:\.[a-z][a-z0-9_]*)*|"
            r"design_form\.elements\["
            r"[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*\])$"
        ),
    ),
]

SourceView: TypeAlias = Literal[
    "plate_composite",
    "front",
    "top",
    "side",
    "three_quarter",
    "detail",
    "unspecified",
]

Sha256Hex: TypeAlias = Annotated[
    str,
    Field(strict=True, pattern=r"^[0-9a-f]{64}$"),
]

SpecVisualHash: TypeAlias = Annotated[
    str,
    Field(strict=True, pattern=r"^[0-9a-f]{16}$"),
]


class IndependentComponentAudit(_FrozenStrictModel):
    """Optional evidence from a reviewer independent of the primary read.

    The evidence describes component coverage only.  It cannot introduce a
    dimension or manufacturing contour, and the strict model rejects such
    fields.
    """

    kind: Literal["independent_component_audit"]
    verdict: Literal["pass", "fail", "inconclusive"]
    auditor: Annotated[str, Field(strict=True, min_length=1, max_length=120)]
    source_view: SourceView
    observed_description: Annotated[
        str,
        Field(strict=True, min_length=1, max_length=1000),
    ]
    evidence_sha256: Sha256Hex | None = None

    @field_validator("auditor", "observed_description")
    @classmethod
    def require_trimmed_text(cls, value: str) -> str:
        if value != value.strip() or not value.strip():
            raise ValueError("audit text must be non-blank and trimmed")
        return value


class DesignerComponentConfirmation(_FrozenStrictModel):
    """Human resolution of an inconclusive independent component audit.

    A confirmation cannot overwrite a failed audit and cannot change the spec.
    It binds one explicit reviewer decision to the exact source bytes and exact
    visual specification. ``designer_defined_target`` is used when the source
    never showed a physical detail (for example band cross-section) but the
    designer deliberately defines it for the manufacturing record.
    """

    kind: Literal["designer_component_confirmation"]
    basis: Literal["visible_source", "designer_defined_target"]
    reviewer: Annotated[str, Field(strict=True, min_length=1, max_length=120)]
    source_view: SourceView
    confirmed_description: Annotated[
        str,
        Field(strict=True, min_length=1, max_length=1000),
    ]
    evidence_sha256: Sha256Hex
    spec_visual_hash: SpecVisualHash

    @field_validator("reviewer", "confirmed_description")
    @classmethod
    def require_trimmed_confirmation_text(cls, value: str) -> str:
        if value != value.strip() or not value.strip():
            raise ValueError("confirmation text must be non-blank and trimmed")
        return value


class SourceVisibleComponent(_FrozenStrictModel):
    """One stable major component observed (or expected) in the source.

    ``canonical_spec_paths`` and ``unresolved_reason`` are mutually exclusive.
    This makes silent loss impossible: a reader cannot claim a component was
    accounted for without naming its exact destination in the immutable spec.
    """

    component_id: VisibleComponentId
    source_view: SourceView
    source_description: Annotated[
        str,
        Field(strict=True, min_length=1, max_length=1200),
    ]
    source_confidence: Annotated[float, Field(strict=True, ge=0.0, le=1.0)]
    canonical_spec_paths: tuple[CanonicalSpecPath, ...] = ()
    unresolved_reason: Annotated[
        str,
        Field(strict=True, min_length=1, max_length=1000),
    ] | None = None
    independent_audit: IndependentComponentAudit | None = None
    designer_confirmation: DesignerComponentConfirmation | None = None

    @field_validator("source_description", "unresolved_reason")
    @classmethod
    def require_trimmed_component_text(cls, value: str | None) -> str | None:
        if value is not None and (value != value.strip() or not value.strip()):
            raise ValueError("component text must be non-blank and trimmed")
        return value

    @model_validator(mode="after")
    def require_exactly_one_resolution(self) -> SourceVisibleComponent:
        has_paths = bool(self.canonical_spec_paths)
        has_unresolved_reason = self.unresolved_reason is not None
        if has_paths == has_unresolved_reason:
            raise ValueError(
                "component must have canonical spec paths or an unresolved "
                "reason, but not both"
            )
        if len(set(self.canonical_spec_paths)) != len(self.canonical_spec_paths):
            raise ValueError("canonical spec paths must be unique")
        return self


class SourceComponentCoverage(_FrozenStrictModel):
    """Non-empty component accounting for one newly imported source."""

    source_kind: Literal["designer_plate", "imported_reference"]
    components: Annotated[tuple[SourceVisibleComponent, ...], Field(min_length=1)]
    audited_spec_visual_hash: SpecVisualHash | None = None

    @model_validator(mode="after")
    def require_unique_component_ids(self) -> SourceComponentCoverage:
        component_ids = tuple(component.component_id for component in self.components)
        if len(set(component_ids)) != len(component_ids):
            raise ValueError("visible component IDs must be unique")
        return self


class SourceCoverageFactoryBlocker(_FrozenStrictModel):
    """One source component that is not ready to be manufacturing truth."""

    code: Literal[
        "source_component_unresolved",
        "source_component_not_independently_audited",
        "source_component_audit_failed",
        "source_component_audit_inconclusive",
        "source_component_path_missing",
        "source_component_spec_audit_missing",
        "source_component_spec_audit_stale",
        "source_component_confirmation_stale",
    ]
    component_id: VisibleComponentId
    message: str
    required_resolution: str


def source_component_factory_blockers(
    coverage: SourceComponentCoverage | None,
    *,
    valid_spec_paths: Collection[CanonicalSpecPath] | None = None,
    current_spec_visual_hash: SpecVisualHash | None = None,
    current_source_hash: Sha256Hex | None = None,
) -> tuple[SourceCoverageFactoryBlocker, ...]:
    """Return every unresolved, stale, or unaudited source-component state.

    A missing coverage record is a legacy provenance state.  It deliberately
    returns no blockers so existing database history stays readable and its
    old approval semantics are not rewritten.  New import paths must attach a
    non-empty coverage record.  When ``valid_spec_paths`` is supplied, every
    mapped path must also exist in that exact spec version; a historical audit
    cannot bless a path removed by a later designer revision.
    """

    if coverage is None:
        return ()

    blockers: list[SourceCoverageFactoryBlocker] = []
    if current_spec_visual_hash is not None:
        if coverage.audited_spec_visual_hash is None:
            blockers.append(SourceCoverageFactoryBlocker(
                code="source_component_spec_audit_missing",
                component_id="audit.spec",
                message=(
                    "source-component evidence was not audited against the "
                    "exact visible facts in this specification"
                ),
                required_resolution=(
                    "Repeat the independent source audit with the current "
                    "validated specification before rendering or release."
                ),
            ))
        elif coverage.audited_spec_visual_hash != current_spec_visual_hash:
            blockers.append(SourceCoverageFactoryBlocker(
                code="source_component_spec_audit_stale",
                component_id="audit.spec",
                message=(
                    "source-component evidence belongs to a different visual "
                    "specification version"
                ),
                required_resolution=(
                    "Repeat the independent source audit against the current "
                    "validated specification."
                ),
            ))
    valid_paths = set(valid_spec_paths) if valid_spec_paths is not None else None
    for component in coverage.components:
        if valid_paths is not None:
            missing_paths = tuple(
                path
                for path in component.canonical_spec_paths
                if path not in valid_paths
            )
            if missing_paths:
                blockers.append(SourceCoverageFactoryBlocker(
                    code="source_component_path_missing",
                    component_id=component.component_id,
                    message=(
                        f"{component.component_id} maps to paths absent from "
                        "the current specification: " + ", ".join(missing_paths)
                    ),
                    required_resolution=(
                        "Map the component to paths that exist in the current "
                        "specification, then repeat the independent audit."
                    ),
                ))
        if component.unresolved_reason is not None:
            blockers.append(SourceCoverageFactoryBlocker(
                code="source_component_unresolved",
                component_id=component.component_id,
                message=(
                    f"{component.component_id} is visible in the source but "
                    f"unresolved: {component.unresolved_reason}"
                ),
                required_resolution=(
                    "Designer must map the component to canonical spec paths "
                    "or define it through an explicit supported form contract."
                ),
            ))

        audit = component.independent_audit
        if audit is None:
            blockers.append(SourceCoverageFactoryBlocker(
                code="source_component_not_independently_audited",
                component_id=component.component_id,
                message=(
                    f"{component.component_id} has not been independently "
                    "audited against the imported source."
                ),
                required_resolution=(
                    "Run and retain an independent component-coverage audit."
                ),
            ))
        elif audit.verdict == "fail":
            blockers.append(SourceCoverageFactoryBlocker(
                code="source_component_audit_failed",
                component_id=component.component_id,
                message=(
                    f"Independent coverage audit failed for "
                    f"{component.component_id}: {audit.observed_description}"
                ),
                required_resolution=(
                    "Correct the spec mapping and repeat the independent audit."
                ),
            ))
        elif audit.verdict == "inconclusive":
            confirmation = component.designer_confirmation
            expected_spec_hash = (
                current_spec_visual_hash or coverage.audited_spec_visual_hash)
            confirmation_current = (
                confirmation is not None
                and confirmation.spec_visual_hash == expected_spec_hash
                and (current_source_hash is None
                     or confirmation.evidence_sha256 == current_source_hash)
            )
            if confirmation is None:
                blockers.append(SourceCoverageFactoryBlocker(
                    code="source_component_audit_inconclusive",
                    component_id=component.component_id,
                    message=(
                        f"Independent coverage audit was inconclusive for "
                        f"{component.component_id}: {audit.observed_description}"
                    ),
                    required_resolution=(
                        "Obtain a clearer source and repeat the audit, or have "
                        "the designer explicitly confirm the visible fact / "
                        "define the missing target against this exact source."
                    ),
                ))
            elif not confirmation_current:
                blockers.append(SourceCoverageFactoryBlocker(
                    code="source_component_confirmation_stale",
                    component_id=component.component_id,
                    message=(
                        f"Designer confirmation for {component.component_id} "
                        "does not match the exact source/spec evidence"
                    ),
                    required_resolution=(
                        "Repeat designer confirmation against the current source "
                        "bytes and visual specification."
                    ),
                ))
    return tuple(blockers)

"""Designer resolution for inconclusive imported-source component evidence."""

from __future__ import annotations

import hashlib
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from facetta.image_identity import spec_visual_hash
from facetta.source_component_coverage import (
    DesignerComponentConfirmation,
    SourceComponentCoverage,
    SourceVisibleComponent,
    VisibleComponentId,
)
from facetta.spec import Spec


class SourceComponentConfirmationInvalid(ValueError):
    pass


class SourceComponentConfirmationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    component_id: VisibleComponentId
    basis: Literal["visible_source", "designer_defined_target"]
    confirmed_description: Annotated[
        str,
        Field(strict=True, min_length=1, max_length=1000),
    ]


def confirm_source_components(
    spec: Spec,
    source_image: bytes,
    confirmations: tuple[SourceComponentConfirmationInput, ...],
    *,
    reviewer: str,
) -> Spec:
    """Bind explicit human decisions without changing any specification fact."""
    if not reviewer.strip() or reviewer != reviewer.strip():
        raise SourceComponentConfirmationInvalid(
            "reviewer must be non-blank and trimmed")
    if not source_image:
        raise SourceComponentConfirmationInvalid("source image must not be empty")
    coverage = spec.source_component_coverage
    if coverage is None:
        raise SourceComponentConfirmationInvalid(
            "current imported-source coverage is required")
    identities = [item.component_id for item in confirmations]
    if len(set(identities)) != len(identities):
        raise SourceComponentConfirmationInvalid(
            "component confirmations must be unique")

    requested = {item.component_id: item for item in confirmations}
    known = {item.component_id for item in coverage.components}
    unknown = sorted(set(requested) - known)
    if unknown:
        raise SourceComponentConfirmationInvalid(
            "unknown source components: " + ", ".join(unknown))
    evidence_hash = hashlib.sha256(source_image).hexdigest()
    visual_hash = spec_visual_hash(spec)
    updated: list[SourceVisibleComponent] = []
    for component in coverage.components:
        decision = requested.get(component.component_id)
        if decision is None:
            updated.append(component)
            continue
        audit = component.independent_audit
        if audit is None or audit.verdict != "inconclusive":
            verdict = audit.verdict if audit is not None else "missing"
            raise SourceComponentConfirmationInvalid(
                f"{component.component_id} audit is {verdict}; designer "
                "confirmation is allowed only after an inconclusive audit")
        confirmation = DesignerComponentConfirmation(
            kind="designer_component_confirmation",
            basis=decision.basis,
            reviewer=reviewer,
            source_view=audit.source_view,
            confirmed_description=decision.confirmed_description,
            evidence_sha256=evidence_hash,
            spec_visual_hash=visual_hash,
        )
        updated.append(component.model_copy(update={
            "designer_confirmation": confirmation,
        }))
    updated_coverage = SourceComponentCoverage(
        source_kind=coverage.source_kind,
        components=tuple(updated),
        audited_spec_visual_hash=coverage.audited_spec_visual_hash,
    )
    return spec.model_copy(update={
        "source_component_coverage": updated_coverage,
    })

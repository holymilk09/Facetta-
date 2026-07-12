"""Designer-safe adapter for confirming facts read from a Studio visual.

The canonical :class:`Spec` remains the continuation contract used by the
trusted services.  This module deliberately projects that dense record into
small, plain-language fact groups for Studio.  It does not persist a design,
grant release authority, or reinterpret the source reader's evidence.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from facetta.image_identity import spec_visual_hash
from facetta.spec import Spec
from facetta.source_component_coverage import source_component_factory_blockers
from facetta.source_component_resolution import valid_source_component_spec_paths


FactAuthority = Literal["suggested", "estimated", "designer_supplied"]


class _StudioConfirmModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StudioDesignerFact(_StudioConfirmModel):
    key: Annotated[str, Field(min_length=1, max_length=80)]
    label: Annotated[str, Field(min_length=1, max_length=120)]
    value: Annotated[str, Field(min_length=1, max_length=240)]
    authority: FactAuthority


class StudioDesignerFactGroup(_StudioConfirmModel):
    key: Literal[
        "design", "center_stone", "setting", "metal", "ring_fit", "accents"
    ]
    label: Annotated[str, Field(min_length=1, max_length=80)]
    facts: Annotated[tuple[StudioDesignerFact, ...], Field(min_length=1)]


class StudioSourceReviewEligibility(_StudioConfirmModel):
    eligible: bool
    state: Literal["not_ready", "ready", "complete"]
    reason: Annotated[str, Field(min_length=1, max_length=240)]


class StudioConfirmDesignResponse(_StudioConfirmModel):
    confirmation_token: Annotated[str, Field(min_length=32, max_length=256)]
    expires_at: datetime
    candidate_id: Annotated[str, Field(min_length=1, max_length=32)]
    candidate_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    spec_visual_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{16}$")]
    fact_groups: tuple[StudioDesignerFactGroup, ...]
    unresolved_source_questions: tuple[
        Annotated[str, Field(min_length=1, max_length=1200)], ...
    ]
    audit_eligibility: StudioSourceReviewEligibility


def _authority(spec: Spec, path: str) -> FactAuthority:
    provenance = spec.dimension_provenance.get(path)
    if provenance is None:
        return "suggested"
    if provenance.status == "designer_confirmed":
        return "designer_supplied"
    return "estimated"


def _fact(
    spec: Spec,
    *,
    key: str,
    label: str,
    value: object,
    path: str,
    suffix: str = "",
) -> StudioDesignerFact:
    return StudioDesignerFact(
        key=key,
        label=label,
        value=f"{value}{suffix}",
        authority=_authority(spec, path),
    )


def _designer_fact_groups(spec: Spec) -> tuple[StudioDesignerFactGroup, ...]:
    groups: list[StudioDesignerFactGroup] = []
    groups.append(StudioDesignerFactGroup(
        key="design",
        label="Design",
        facts=(
            _fact(
                spec, key="jewelry_type", label="Jewelry type",
                value=spec.jewelry_type, path="jewelry_type",
            ),
            _fact(
                spec, key="template", label="Design type",
                value=spec.template, path="template",
            ),
        ),
    ))

    stone = spec.stone
    stone_facts = [
        _fact(
            spec, key="species", label="Stone", value=stone.species,
            path="stone.species",
        ),
        _fact(
            spec, key="cut", label="Cut", value=stone.cut,
            path="stone.cut",
        ),
        _fact(
            spec, key="color", label="Color", value=stone.color.trade,
            path="stone.color",
        ),
        _fact(
            spec, key="carat", label="Carat", value=stone.carat,
            path="stone.carat", suffix=" ct",
        ),
        _fact(
            spec, key="length", label="Length",
            value=stone.dimensions_mm.length,
            path="stone.dimensions_mm.length", suffix=" mm",
        ),
        _fact(
            spec, key="width", label="Width",
            value=stone.dimensions_mm.width,
            path="stone.dimensions_mm.width", suffix=" mm",
        ),
        _fact(
            spec, key="depth", label="Depth",
            value=stone.dimensions_mm.depth,
            path="stone.dimensions_mm.depth", suffix=" mm",
        ),
    ]
    groups.append(StudioDesignerFactGroup(
        key="center_stone", label="Center stone", facts=tuple(stone_facts),
    ))

    if spec.setting is not None:
        setting_facts = [
            _fact(
                spec, key="style", label="Setting",
                value=spec.setting.style, path="setting.style",
            )
        ]
        if spec.setting.prong_count is not None:
            setting_facts.append(_fact(
                spec, key="prong_count", label="Prongs",
                value=spec.setting.prong_count, path="setting.prong_count",
            ))
        groups.append(StudioDesignerFactGroup(
            key="setting", label="Setting", facts=tuple(setting_facts),
        ))

    if spec.metal is not None:
        metal_facts = [
            _fact(
                spec, key="material", label="Metal",
                value=spec.metal.material, path="metal.material",
            )
        ]
        for key, label, value in (
            ("karat", "Karat", spec.metal.karat),
            ("color", "Metal color", spec.metal.color),
            ("finish", "Finish", spec.metal.finish),
        ):
            if value is not None:
                metal_facts.append(_fact(
                    spec, key=key, label=label, value=value,
                    path=f"metal.{key}",
                ))
        groups.append(StudioDesignerFactGroup(
            key="metal", label="Metal", facts=tuple(metal_facts),
        ))

    fit_facts: list[StudioDesignerFact] = []
    if spec.band is not None:
        fit_facts.extend((
            _fact(
                spec, key="band_profile", label="Band profile",
                value=spec.band.profile, path="band.profile",
            ),
            _fact(
                spec, key="band_width", label="Band width",
                value=spec.band.width_mm, path="band.width_mm", suffix=" mm",
            ),
            _fact(
                spec, key="band_thickness", label="Band thickness",
                value=spec.band.thickness_mm,
                path="band.thickness_mm", suffix=" mm",
            ),
        ))
    if spec.ring_size is not None:
        fit_facts.append(_fact(
            spec, key="ring_size", label="Ring size",
            value=f"{spec.ring_size.system} {spec.ring_size.value}",
            path="ring_size.value",
        ))
    if fit_facts:
        groups.append(StudioDesignerFactGroup(
            key="ring_fit", label="Ring and fit", facts=tuple(fit_facts),
        ))

    if spec.side_stones:
        groups.append(StudioDesignerFactGroup(
            key="accents",
            label="Accent stones",
            facts=tuple(
                _fact(
                    spec,
                    key=f"group_{index + 1}",
                    label=f"Accent group {index + 1}",
                    value=f"{stone.count} x {stone.species}, {stone.cut}",
                    path=f"side_stones[{index}]",
                )
                for index, stone in enumerate(spec.side_stones)
            ),
        ))
    return tuple(groups)


def _source_questions(spec: Spec) -> tuple[str, ...]:
    coverage = spec.source_component_coverage
    if coverage is None:
        return (
            "Confirm which visible parts of the selected visual must be kept.",
        )
    questions: list[str] = []
    for component in coverage.components:
        description = component.source_description.rstrip(".!?")
        if component.unresolved_reason is not None:
            questions.append(
                f"Confirm {description}: "
                f"{component.unresolved_reason}"
            )
            continue
        evidence = component.independent_audit
        if component.designer_confirmation is not None:
            continue
        if evidence is None:
            questions.append(
                f"Review {description} against the selected visual."
            )
        elif evidence.verdict != "pass":
            questions.append(
                f"Review {description}; the visual evidence "
                "is not conclusive."
            )
    return tuple(questions)


def build_studio_confirm_design_response(
    *,
    confirmation_token: str,
    expires_at: datetime,
    candidate_id: str,
    candidate_sha256: str,
    spec: Spec,
) -> StudioConfirmDesignResponse:
    questions = _source_questions(spec)
    coverage = spec.source_component_coverage
    current_hash = spec_visual_hash(spec)
    blockers = (
        source_component_factory_blockers(
            coverage,
            valid_spec_paths=valid_source_component_spec_paths(spec),
            current_spec_visual_hash=current_hash,
            current_source_hash=candidate_sha256,
        )
        if coverage is not None
        else (object(),)
    )
    if not blockers:
        eligibility = StudioSourceReviewEligibility(
            eligible=True,
            state="complete",
            reason="The selected visual and confirmed facts have current evidence.",
        )
    else:
        eligibility = StudioSourceReviewEligibility(
            eligible=False,
            state="not_ready",
            reason="Complete the source review against this exact visual first.",
        )
    return StudioConfirmDesignResponse(
        confirmation_token=confirmation_token,
        expires_at=expires_at,
        candidate_id=candidate_id,
        candidate_sha256=candidate_sha256,
        spec_visual_hash=current_hash,
        fact_groups=_designer_fact_groups(spec),
        unresolved_source_questions=questions,
        audit_eligibility=eligibility,
    )

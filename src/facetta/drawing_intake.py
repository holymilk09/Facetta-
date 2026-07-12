"""Input-agnostic, best-effort processing contract for designer drawings.

Facetta does not score, label, or persist a judgment about drawing quality.
Every valid drawing receives the same faithful visual attempt.  Concrete
uncertainties are ephemeral workflow evidence: they guide conservative image
behavior and become questions only when a draft is promoted toward a factory
specification.

This module is pure.  It performs no provider, persistence, or UI work.
"""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


DRAWING_PROCESSING_CONTRACT_VERSION = "drawing-processing.v1"


class _FrozenStrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


DimensionEvidence: TypeAlias = Literal[
    "absent",
    "reference_estimate",
    "designer_supplied",
    "unresolved",
]
InternalEvidenceCode: TypeAlias = Literal[
    "geometry_not_visible",
    "geometry_ambiguous",
    "views_disagree",
    "dimension_illegible",
    "annotation_ambiguous",
]
DimensionHandling: TypeAlias = Literal[
    "estimate_missing_separately",
    "preserve_estimate_label",
    "preserve_exactly",
    "defer_until_factory_clarification",
]


class InternalDrawingEvidenceSignal(_FrozenStrictModel):
    """Ephemeral factual evidence; never a designer-facing source label."""

    code: InternalEvidenceCode
    subject: Annotated[str, Field(strict=True, min_length=1, max_length=160)]
    detail: Annotated[str, Field(strict=True, min_length=1, max_length=800)]
    visibility: Literal["internal_only"] = "internal_only"

    @field_validator("subject", "detail")
    @classmethod
    def require_trimmed_text(cls, value: str) -> str:
        if value != value.strip() or not value.strip():
            raise ValueError("drawing evidence text must be trimmed")
        return value


class DrawingIntakeFacts(_FrozenStrictModel):
    """Facts known at intake, with no drawing-quality or designer taxonomy."""

    dimension_evidence: DimensionEvidence = "absent"
    internal_signals: tuple[InternalDrawingEvidenceSignal, ...] = ()

    @model_validator(mode="after")
    def require_unique_internal_signals(self) -> DrawingIntakeFacts:
        identities = tuple(
            (signal.code, signal.subject)
            for signal in self.internal_signals
        )
        if len(set(identities)) != len(identities):
            raise ValueError(
                "internal drawing evidence must be unique by code and subject"
            )
        return self


class DrawingFactoryQuestion(_FrozenStrictModel):
    """A concrete question surfaced only at factory-specification review."""

    stage: Literal["factory_spec"] = "factory_spec"
    code: Literal[
        "define_unseen_geometry",
        "resolve_geometry",
        "choose_controlling_view",
        "provide_exact_dimension",
        "explain_annotation",
        "classify_dimension_evidence",
    ]
    subject: Annotated[str, Field(strict=True, min_length=1, max_length=160)]
    question: Annotated[str, Field(strict=True, min_length=1, max_length=500)]
    required_before_factory_promotion: Literal[True] = True


class DrawingProcessingPolicy(_FrozenStrictModel):
    """Invariant visual attempt plus separate factory-promotion controls."""

    render_strategy: Literal["faithful_best_effort"] = "faithful_best_effort"
    visual_render_allowed: Literal[True] = True
    draft_spec_allowed: Literal[True] = True
    factory_spec_blocked_by_drawing_evidence: bool
    geometry_handling: Literal[
        "preserve_supplied_design_evidence"
    ] = "preserve_supplied_design_evidence"
    unseen_geometry_handling: Literal[
        "minimal_review_proposal_not_factory_truth"
    ] = "minimal_review_proposal_not_factory_truth"
    presentation_cleanup_allowed: Literal[True] = True
    pre_render_clarification_required: Literal[False] = False
    designer_review_required: Literal[True] = True
    dimension_handling: DimensionHandling
    provider_output_authoritative: Literal[False] = False
    factory_truth_source: Literal[
        "validated_record_plus_original_source"
    ] = "validated_record_plus_original_source"


class DrawingProcessingContract(_FrozenStrictModel):
    """Prompt facts and factory-stage questions for one drawing attempt."""

    contract_version: Literal[
        "drawing-processing.v1"
    ] = DRAWING_PROCESSING_CONTRACT_VERSION
    policy: DrawingProcessingPolicy
    factory_questions: tuple[DrawingFactoryQuestion, ...]
    prompt_facts: tuple[Annotated[str, Field(strict=True, min_length=1)], ...]


def _question_for_signal(
    signal: InternalDrawingEvidenceSignal,
) -> DrawingFactoryQuestion:
    if signal.code == "geometry_not_visible":
        return DrawingFactoryQuestion(
            code="define_unseen_geometry",
            subject=signal.subject,
            question=(
                f"For the factory specification, what exact geometry defines "
                f"{signal.subject}?"
            ),
        )
    if signal.code == "geometry_ambiguous":
        return DrawingFactoryQuestion(
            code="resolve_geometry",
            subject=signal.subject,
            question=(
                f"For the factory specification, which exact outline or "
                f"construction should define {signal.subject}?"
            ),
        )
    if signal.code == "views_disagree":
        return DrawingFactoryQuestion(
            code="choose_controlling_view",
            subject=signal.subject,
            question=(
                f"For the factory specification, which source view controls "
                f"{signal.subject}?"
            ),
        )
    if signal.code == "dimension_illegible":
        return DrawingFactoryQuestion(
            code="provide_exact_dimension",
            subject=signal.subject,
            question=(
                f"What exact value and unit should the factory specification "
                f"record for {signal.subject}?"
            ),
        )
    return DrawingFactoryQuestion(
        code="explain_annotation",
        subject=signal.subject,
        question=(
            f"For the factory specification, what does the annotation for "
            f"{signal.subject} require?"
        ),
    )


def _prompt_handling_for_signal(
    signal: InternalDrawingEvidenceSignal,
) -> str:
    handling = {
        "geometry_not_visible": (
            "Do not claim hidden geometry was observed. If the visual output "
            "requires continuity, use the minimum conservative proposal and keep "
            "it review-only."
        ),
        "geometry_ambiguous": (
            "Preserve the clear surrounding geometry and use the least "
            "transformative interpretation for the review candidate."
        ),
        "views_disagree": (
            "Do not average or merge the views. Keep the requested or selected "
            "view internally coherent and defer the conflict to factory review."
        ),
        "dimension_illegible": (
            "Do not guess the numeric value or unit. Continue the visual render "
            "from visible geometry and defer the number to factory review."
        ),
        "annotation_ambiguous": (
            "Do not execute the unclear annotation as a design change. Preserve "
            "the supplied base geometry and defer its meaning to factory review."
        ),
    }[signal.code]
    return (
        f"INTERNAL SOURCE EVIDENCE [{signal.code}] {signal.subject}: "
        f"{signal.detail} {handling} Do not expose this internal label in output."
    )


def _dimension_policy(
    evidence: DimensionEvidence,
) -> tuple[DimensionHandling, str]:
    return {
        "absent": (
            "estimate_missing_separately",
            (
                "No supplied dimensions are available. Reference-derived values "
                "may be offered separately as EST. suggestions, never measurements."
            ),
        ),
        "reference_estimate": (
            "preserve_estimate_label",
            (
                "Supplied dimension values are estimates. Preserve their EST. "
                "status and never promote them to measured values."
            ),
        ),
        "designer_supplied": (
            "preserve_exactly",
            (
                "Designer-supplied dimensions must be transcribed exactly with "
                "their units and must never be replaced by visual estimates."
            ),
        ),
        "unresolved": (
            "defer_until_factory_clarification",
            (
                "The status of supplied dimensions is unresolved. Do not transcribe "
                "them into factory truth before factory-specification review."
            ),
        ),
    }[evidence]


def build_drawing_processing_contract(
    facts: DrawingIntakeFacts,
) -> DrawingProcessingContract:
    """Build the same faithful visual policy for every valid drawing input."""

    questions = [
        _question_for_signal(signal)
        for signal in facts.internal_signals
    ]
    if facts.dimension_evidence == "unresolved":
        questions.append(DrawingFactoryQuestion(
            code="classify_dimension_evidence",
            subject="supplied dimensions",
            question=(
                "For the factory specification, are the supplied dimension labels "
                "exact designer values or reference estimates that must remain EST.?"
            ),
        ))

    dimension_handling, dimension_fact = _dimension_policy(
        facts.dimension_evidence
    )
    prompt_facts = [
        "DRAWING RENDER POLICY: FAITHFUL BEST EFFORT.",
        (
            "Preserve every supplied visible line, shape, component count, "
            "proportion, topology, and spatial relationship as design evidence."
        ),
        (
            "Improve presentation quality only: remove capture noise and apply the "
            "requested finish, material, color, or lighting without regularizing, "
            "symmetrizing, substituting, or silently redesigning geometry."
        ),
        (
            "When a visual output requires geometry that is not supplied, use only "
            "the minimum conservative review proposal and never call it observed, "
            "approved, measured, or factory-ready."
        ),
        (
            "Do not stop the visual attempt for an intake-quality judgment. Defer "
            "only concrete unresolved physical facts to factory-specification review."
        ),
        dimension_fact,
    ]
    prompt_facts.extend(
        _prompt_handling_for_signal(signal)
        for signal in facts.internal_signals
    )
    prompt_facts.append(
        "AI output is never factory authority; only the validated immutable record "
        "plus the original source can support factory truth."
    )

    return DrawingProcessingContract(
        policy=DrawingProcessingPolicy(
            factory_spec_blocked_by_drawing_evidence=bool(questions),
            dimension_handling=dimension_handling,
        ),
        factory_questions=tuple(questions),
        prompt_facts=tuple(prompt_facts),
    )

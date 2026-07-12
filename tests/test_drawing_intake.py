"""Best-effort drawing processing without designer-facing source labels."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from facetta.drawing_intake import (
    DrawingIntakeFacts,
    InternalDrawingEvidenceSignal,
    build_drawing_processing_contract,
)


def test_default_contract_always_attempts_a_faithful_visual_render() -> None:
    contract = build_drawing_processing_contract(DrawingIntakeFacts())

    policy = contract.policy
    assert contract.contract_version == "drawing-processing.v1"
    assert policy.render_strategy == "faithful_best_effort"
    assert policy.visual_render_allowed is True
    assert policy.draft_spec_allowed is True
    assert policy.pre_render_clarification_required is False
    assert policy.geometry_handling == "preserve_supplied_design_evidence"
    assert policy.presentation_cleanup_allowed is True
    assert policy.designer_review_required is True
    assert policy.provider_output_authoritative is False
    assert policy.factory_spec_blocked_by_drawing_evidence is False
    assert policy.dimension_handling == "estimate_missing_separately"
    assert contract.factory_questions == ()


def test_prompt_facts_preserve_design_without_judging_the_source() -> None:
    contract = build_drawing_processing_contract(DrawingIntakeFacts())
    facts = " ".join(contract.prompt_facts)

    assert "FAITHFUL BEST EFFORT" in facts
    assert "Preserve every supplied visible line" in facts
    assert "without regularizing, symmetrizing, substituting" in facts
    assert "minimum conservative review proposal" in facts
    assert "AI output is never factory authority" in facts
    assert "rough" not in facts.lower()
    assert "professional" not in facts.lower()
    serialized = contract.model_dump_json().lower()
    assert "maturity" not in serialized
    assert "drawing_class" not in serialized


@pytest.mark.parametrize(
    "code, expected_question",
    [
        ("geometry_not_visible", "define_unseen_geometry"),
        ("geometry_ambiguous", "resolve_geometry"),
        ("views_disagree", "choose_controlling_view"),
        ("dimension_illegible", "provide_exact_dimension"),
        ("annotation_ambiguous", "explain_annotation"),
    ],
)
def test_internal_evidence_never_stops_visual_attempt_and_only_questions_factory(
    code: str,
    expected_question: str,
) -> None:
    signal = InternalDrawingEvidenceSignal.model_validate({
        "code": code,
        "subject": "center assembly",
        "detail": "The supplied source does not establish one physical fact.",
    })
    contract = build_drawing_processing_contract(DrawingIntakeFacts(
        internal_signals=(signal,),
    ))

    assert contract.policy.visual_render_allowed is True
    assert contract.policy.draft_spec_allowed is True
    assert contract.policy.pre_render_clarification_required is False
    assert contract.policy.factory_spec_blocked_by_drawing_evidence is True
    assert len(contract.factory_questions) == 1
    question = contract.factory_questions[0]
    assert question.stage == "factory_spec"
    assert question.code == expected_question
    assert question.required_before_factory_promotion is True
    assert "For the factory specification" in question.question or (
        "factory specification" in question.question
    )
    facts = " ".join(contract.prompt_facts)
    assert f"INTERNAL SOURCE EVIDENCE [{code}]" in facts
    assert "Do not expose this internal label" in facts


def test_unseen_geometry_is_a_review_proposal_not_factory_truth() -> None:
    signal = InternalDrawingEvidenceSignal(
        code="geometry_not_visible",
        subject="rear clasp connection",
        detail="Only the front connection is visible.",
    )
    contract = build_drawing_processing_contract(DrawingIntakeFacts(
        internal_signals=(signal,),
    ))

    assert contract.policy.unseen_geometry_handling == (
        "minimal_review_proposal_not_factory_truth"
    )
    facts = " ".join(contract.prompt_facts)
    assert "Do not claim hidden geometry was observed" in facts
    assert "keep it review-only" in facts


@pytest.mark.parametrize(
    "evidence, expected",
    [
        ("absent", "estimate_missing_separately"),
        ("reference_estimate", "preserve_estimate_label"),
        ("designer_supplied", "preserve_exactly"),
        ("unresolved", "defer_until_factory_clarification"),
    ],
)
def test_dimension_evidence_has_explicit_non_promoting_handling(
    evidence: str,
    expected: str,
) -> None:
    facts = DrawingIntakeFacts.model_validate({"dimension_evidence": evidence})
    contract = build_drawing_processing_contract(facts)

    assert contract.policy.dimension_handling == expected
    assert contract.policy.visual_render_allowed is True
    if evidence == "unresolved":
        assert contract.policy.factory_spec_blocked_by_drawing_evidence is True
        assert contract.factory_questions[0].stage == "factory_spec"
        assert contract.factory_questions[0].code == "classify_dimension_evidence"
    else:
        assert contract.policy.factory_spec_blocked_by_drawing_evidence is False


def test_supplied_dimensions_remain_exact_and_estimates_remain_estimates() -> None:
    exact = build_drawing_processing_contract(DrawingIntakeFacts(
        dimension_evidence="designer_supplied",
    ))
    estimated = build_drawing_processing_contract(DrawingIntakeFacts(
        dimension_evidence="reference_estimate",
    ))

    assert "transcribed exactly" in " ".join(exact.prompt_facts)
    estimate_facts = " ".join(estimated.prompt_facts)
    assert "Preserve their EST. status" in estimate_facts
    assert "never promote them to measured values" in estimate_facts


def test_internal_signals_are_strict_trimmed_and_unique() -> None:
    with pytest.raises(ValidationError, match="must be trimmed"):
        InternalDrawingEvidenceSignal(
            code="geometry_ambiguous",
            subject=" gallery ",
            detail="Two outlines overlap.",
        )

    signal = InternalDrawingEvidenceSignal(
        code="geometry_ambiguous",
        subject="gallery",
        detail="Two outlines overlap.",
    )
    assert signal.visibility == "internal_only"
    with pytest.raises(ValidationError, match="must be unique"):
        DrawingIntakeFacts(internal_signals=(signal, signal))

"""Prompt-to-project preparation through the closed-loop image agent."""

from __future__ import annotations

from facetta.concept import ConceptInvalid, complete_design, read_design
from facetta.image_agent import (
    ImageAgentResult,
    ImageOperation,
    ImagePlanValidationError,
    JewelryImageAgent,
    QualityVerdict,
    build_image_plan,
)
from facetta.project_backbone import BriefProjectGeneration
from facetta.validation import validate_spec
from facetta.vocabulary import get_vocabulary


def generate_trusted_brief_project(
    brief: str, variant: int,
) -> BriefProjectGeneration:
    """Generate, inspect, physicalize, re-render, and QA a ring brief."""
    agent = JewelryImageAgent()
    concept_plan = build_image_plan(
        ImageOperation.CONCEPT_GENERATE,
        brief,
        expected_output=("one unbranded, client-reviewable ring concept on a "
                         "neutral studio background"),
        variant=variant,
    )
    concept = agent.run(concept_plan)
    concept_report = concept.quality.model_dump(mode="json")
    if concept.quality.verdict is QualityVerdict.WARN:
        return BriefProjectGeneration(
            concept_image=concept.image_bytes,
            spec_render=b"",
            spec=None,
            quality_verdict="warn",
            quality_report={
                "verdict": "warn",
                "stage": "concept",
                "concept": concept_report,
            },
            concept_run=concept,
        )

    return continue_trusted_brief_project(brief, variant, concept, agent=agent)


def continue_trusted_brief_project(
    brief: str,
    variant: int,
    concept: ImageAgentResult,
    *,
    agent: JewelryImageAgent | None = None,
) -> BriefProjectGeneration:
    """Continue an explicitly reviewed concept through spec and render QA."""
    agent = agent or JewelryImageAgent()
    concept_report = concept.quality.model_dump(mode="json")

    read = read_design(concept.image_bytes, brief)
    draft, corrections = complete_design(read, brief)
    validated = validate_spec(draft, get_vocabulary())
    if not validated.ok:
        raise ConceptInvalid(corrections, validated.issues)
    if validated.spec.jewelry_type != "ring":
        raise ImagePlanValidationError(
            "the concept reader did not identify a ring; no project was saved")

    spec_plan = build_image_plan(
        ImageOperation.SPEC_RENDER,
        "Create the spec-aligned hero render for the approved concept",
        spec=validated.spec,
        source_image=concept.image_bytes,
        expected_output=("one photorealistic ring render that preserves the "
                         "concept identity and matches every visible validated "
                         "specification fact"),
        variant=variant,
    )
    spec_render = agent.run(spec_plan, source_image=concept.image_bytes)
    verdict = spec_render.quality.verdict.value
    return BriefProjectGeneration(
        concept_image=concept.image_bytes,
        spec_render=spec_render.image_bytes,
        spec=validated.spec,
        quality_verdict=verdict,
        quality_report={
            "verdict": verdict,
            "stage": "spec_render",
            "concept": concept_report,
            "spec_render": spec_render.quality.model_dump(mode="json"),
        },
        corrections=tuple(corrections),
        read=read.model_dump(mode="json"),
        concept_run=concept,
        spec_render_run=spec_render,
    )

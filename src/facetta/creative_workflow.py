"""Provider-facing pre-spec creative rendering service.

This is the canonical bridge from an arbitrary designer image/drawing to the
closed-loop image agent.  It intentionally does not extract or invent a
factory specification; that happens only after a designer chooses a candidate.
"""

from __future__ import annotations

from collections.abc import Callable

from facetta.image_agent import (
    ImageAgentResult,
    ImageOperation,
    JewelryImageAgent,
    build_image_plan,
)


CreativeRenderGenerator = Callable[[bytes, str, int], ImageAgentResult]
CreativePromptGenerator = Callable[[str, int], ImageAgentResult]


def generate_creative_prompt(
    instruction: str,
    variant: int,
) -> ImageAgentResult:
    """Generate a category-neutral, explicitly pre-spec jewelry candidate."""
    plan = build_image_plan(
        ImageOperation.CREATIVE_GENERATE,
        instruction,
        variant=variant,
        style_constraints=(
            "fine-jewelry product rendering with believable material response",
            "clean presentation with the complete jewelry piece reviewable",
            "designer-facing concept quality rather than generic clip art",
        ),
    )
    return JewelryImageAgent().run(plan)


def get_creative_prompt_generator() -> CreativePromptGenerator:
    return generate_creative_prompt


def generate_creative_render(
    source_image: bytes,
    instruction: str,
    variant: int,
) -> ImageAgentResult:
    plan = build_image_plan(
        ImageOperation.REFERENCE_RENDER,
        instruction,
        source_image=source_image,
        variant=variant,
        style_constraints=(
            "fine-jewelry product rendering with believable material response",
            "clean presentation that keeps the entire visible piece reviewable",
        ),
    )
    return JewelryImageAgent().run(plan, source_image=source_image)


def get_creative_render_generator() -> CreativeRenderGenerator:
    return generate_creative_render

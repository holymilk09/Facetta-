"""Provider-facing pre-spec creative rendering service.

This is the canonical bridge from an arbitrary designer image/drawing to the
closed-loop image agent.  It intentionally does not extract or invent a
factory specification; that happens only after a designer chooses a candidate.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Protocol, TypeAlias, cast

from facetta.image_agent import (
    ImageAgentResult,
    ImageOperation,
    ImageRoute,
    JewelryImageAgent,
    build_image_plan,
)


CAMERA_REFERENCE_EDIT_CONTRACT = (
    "ORDERED CAMERA REFERENCE CONTRACT: Image 1 is the identity source and "
    "the only authority for jewelry design, silhouette, geometry, component "
    "and stone count, placement, proportions, materials, and motifs. Image 2 "
    "is camera-only guidance. From Image 2 copy only camera elevation, azimuth, "
    "upright image-plane rotation, crop, frame fill, apparent review scale, and "
    "neutral background family. Never copy, merge, replace, or infer any "
    "jewelry feature from Image 2. Return Image 1's exact design presented with "
    "Image 2's review camera."
)


class QualitySourceCreativeRenderGenerator(Protocol):
    def __call__(
        self,
        source_image: bytes,
        instruction: str,
        variant: int,
        *,
        quality_source_image: bytes | None = None,
        camera_reference_image: bytes | None = None,
    ) -> ImageAgentResult: ...


LegacyCreativeRenderGenerator: TypeAlias = Callable[
    [bytes, str, int], ImageAgentResult
]
CreativeRenderGenerator: TypeAlias = (
    QualitySourceCreativeRenderGenerator | LegacyCreativeRenderGenerator
)
class CreativePromptGenerator(Protocol):
    def __call__(
        self,
        instruction: str,
        variant: int,
        *,
        reference_board: bytes | None = None,
        reference_instruction: str | None = None,
    ) -> ImageAgentResult: ...


def invoke_creative_render_generator(
    generate: CreativeRenderGenerator,
    source_image: bytes,
    instruction: str,
    variant: int,
    *,
    quality_source_image: bytes | None = None,
    camera_reference_image: bytes | None = None,
) -> ImageAgentResult:
    """Invoke v2 generators without breaking legacy dependency overrides.

    The canonical production generator exposes typed quality-source and
    camera-reference keywords. Older injected callables remain valid when no
    camera reference is required. Signature inspection happens before
    execution so a ``TypeError`` raised *inside* a generator can never trigger
    a second call.
    """
    if quality_source_image is None and camera_reference_image is None:
        return generate(source_image, instruction, variant)
    try:
        parameters = inspect.signature(generate).parameters.values()
    except (TypeError, ValueError):
        # An opaque callable must honor the current typed contract. Failing
        # closed is safer than silently dropping fidelity authority.
        return cast(QualitySourceCreativeRenderGenerator, generate)(
            source_image,
            instruction,
            variant,
            quality_source_image=quality_source_image,
            camera_reference_image=camera_reference_image,
        )
    supports_quality_source = any(
        parameter.name == "quality_source_image"
        or parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters
    )
    supports_camera_reference = any(
        parameter.name == "camera_reference_image"
        or parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters
    )
    if camera_reference_image is not None and not supports_camera_reference:
        raise TypeError(
            "creative render generator cannot accept camera_reference_image"
        )
    kwargs: dict[str, bytes | None] = {}
    if quality_source_image is not None and supports_quality_source:
        kwargs["quality_source_image"] = quality_source_image
    if camera_reference_image is not None:
        kwargs["camera_reference_image"] = camera_reference_image
    if kwargs:
        return cast(QualitySourceCreativeRenderGenerator, generate)(
            source_image,
            instruction,
            variant,
            **kwargs,
        )
    return generate(source_image, instruction, variant)


def generate_creative_prompt(
    instruction: str,
    variant: int,
    *,
    reference_board: bytes | None = None,
    reference_instruction: str | None = None,
) -> ImageAgentResult:
    """Generate a category-neutral, explicitly pre-spec jewelry candidate."""
    if (reference_board is None) != (reference_instruction is None):
        raise ValueError(
            "an advisory reference board and its role contract must be supplied together"
        )
    style_constraints = (
        "fine-jewelry product rendering with believable material response",
        "clean presentation with the complete jewelry piece reviewable",
        "designer-facing concept quality rather than generic clip art",
    )
    if reference_instruction is not None:
        style_constraints = (*style_constraints, reference_instruction)
    plan = build_image_plan(
        ImageOperation.CREATIVE_GENERATE,
        instruction,
        source_image=reference_board,
        variant=variant,
        style_constraints=style_constraints,
    )
    return JewelryImageAgent().run(plan, source_image=reference_board)


def get_creative_prompt_generator() -> CreativePromptGenerator:
    return generate_creative_prompt


def generate_creative_render(
    source_image: bytes,
    instruction: str,
    variant: int,
    *,
    quality_source_image: bytes | None = None,
    camera_reference_image: bytes | None = None,
) -> ImageAgentResult:
    style_constraints = (
        "fine-jewelry product rendering with believable material response",
        "clean presentation that keeps the entire visible piece reviewable",
    )
    if camera_reference_image is not None:
        style_constraints = (*style_constraints, CAMERA_REFERENCE_EDIT_CONTRACT)
    plan = build_image_plan(
        ImageOperation.REFERENCE_RENDER,
        instruction,
        source_image=source_image,
        quality_source_image=quality_source_image,
        camera_reference_image=camera_reference_image,
        variant=variant,
        style_constraints=style_constraints,
    )
    agent = JewelryImageAgent(
        # A camera-only repair has no provider-safe fallback: only the ordered
        # OpenAI edit route accepts both the identity source and camera
        # reference.  Still give transient transport failures the same bounded
        # retry budget as every other image operation.  These are internal
        # attempts; Studio persists and charges only after the complete
        # direction set passes review.
        attempt_routes=(
            ImageRoute.OPENAI_EDIT,
            ImageRoute.OPENAI_EDIT,
            ImageRoute.OPENAI_EDIT,
        ),
    ) if camera_reference_image is not None else JewelryImageAgent()
    return agent.run(
        plan,
        source_image=source_image,
        quality_source_image=quality_source_image,
        camera_reference_image=camera_reference_image,
    )


def get_creative_render_generator() -> CreativeRenderGenerator:
    return generate_creative_render

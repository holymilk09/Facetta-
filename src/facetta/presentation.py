"""Designer-facing product-photography briefs for trusted visual-only edits.

These presets describe presentation, never jewelry design.  The image-agent
plan and QA layer still freeze every validated stone, setting, component, and
metal fact; this module makes that contract concrete for ecommerce workflows.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from collections.abc import Callable
from typing import Literal

from facetta.image_agent.contracts import ImageAgentResult
from facetta.spec import Spec


ProductPhotoPreset = Literal[
    "catalog_white",
    "luxury_studio",
    "dark_editorial",
    "macro_detail",
]
ProductPhotoFraming = Literal["source", "square", "portrait"]


class PresentationScopeError(ValueError):
    """The request asks to redesign jewelry rather than present it."""


@dataclass(frozen=True)
class ProductPhotoBrief:
    intent: str
    style_constraints: tuple[str, ...]
    expected_output: str


_PRESETS: dict[str, tuple[str, tuple[str, ...]]] = {
    "catalog_white": (
        "Restage this exact jewelry piece as a clean ecommerce catalog photograph on a seamless pure-white background.",
        (
            "soft even studio light with controlled gemstone and metal reflections",
            "centered product-only composition with no props, hands, text, or logos",
            "commercially clean edges and a natural contact shadow",
        ),
    ),
    "luxury_studio": (
        "Restage this exact jewelry piece as a refined high-jewelry studio product photograph on a warm neutral surface.",
        (
            "soft directional atelier lighting with realistic gemstone fire",
            "restrained ivory or pale stone background with no distracting props",
            "premium ecommerce campaign finish without text or branding",
        ),
    ),
    "dark_editorial": (
        "Restage this exact jewelry piece as a dark editorial product photograph while keeping every jewelry fact unchanged.",
        (
            "charcoal-to-black seamless background with precise rim lighting",
            "retain readable metal color and true gemstone color in the shadows",
            "single product, no props, text, logos, smoke, or invented branding",
        ),
    ),
    "macro_detail": (
        "Create a close product-detail photograph of this exact jewelry piece, emphasizing its setting and craftsmanship.",
        (
            "macro studio optics with the complete setting and prong structure legible",
            "neutral uncluttered background and realistic fine-jewelry reflections",
            "crop may change, but no component, proportion, stone, or setting may change",
        ),
    ),
}

_MUTATION_VERBS = re.compile(
    r"\b(change|replace|swap|remove|add|widen|narrow|enlarge|shrink|reshape|"
    r"redesign|smooth|convert|turn)\w*\b",
    re.IGNORECASE,
)
_DESIGN_COMPONENTS = re.compile(
    r"\b(stone|gem|diamond|emerald|ruby|sapphire|band|shank|prong|setting|"
    r"halo|metal|gold|platinum|gallery|bezel|carat|millimeter|mm)\w*\b",
    re.IGNORECASE,
)


def compile_product_photo_brief(
    preset: ProductPhotoPreset,
    framing: ProductPhotoFraming = "portrait",
    custom_instruction: str = "",
) -> ProductPhotoBrief:
    """Compile a presentation-only brief and reject physical redesign asks."""
    if preset not in _PRESETS:
        raise PresentationScopeError(f"unknown product photo preset '{preset}'")
    if framing not in {"source", "square", "portrait"}:
        raise PresentationScopeError(f"unknown product photo framing '{framing}'")
    custom = custom_instruction.strip()
    if custom and _MUTATION_VERBS.search(custom) and _DESIGN_COMPONENTS.search(custom):
        raise PresentationScopeError(
            "product photography may change only scene, lighting, crop, and background; use a confirmed design revision for jewelry changes"
        )

    base, constraints = _PRESETS[preset]
    framing_constraint = {
        "source": "preserve the source framing and camera orientation",
        "square": "compose for a centered square ecommerce crop without resizing the jewelry relative to the frame deceptively",
        "portrait": "compose for a 4:5 portrait ecommerce crop with comfortable product margins",
    }[framing]
    intent = base
    if custom:
        intent += f" Designer presentation direction: {custom}"
    return ProductPhotoBrief(
        intent=intent,
        style_constraints=(*constraints, framing_constraint),
        expected_output=(
            "one production-ready ecommerce product photograph of the exact approved jewelry piece; presentation changed, jewelry unchanged"
        ),
    )


def generate_marketing_image_candidate(
    spec: Spec,
    source_image: bytes,
    brief: ProductPhotoBrief,
    variant: int,
) -> ImageAgentResult:
    """Execute one observed presentation-only candidate through the image agent."""
    from facetta.image_agent import ImageOperation, JewelryImageAgent, build_image_plan

    plan = build_image_plan(
        ImageOperation.VISUAL_ONLY_EDIT,
        brief.intent,
        spec=spec,
        source_spec=spec,
        source_image=source_image,
        frozen=(
            "the exact approved jewelry silhouette and component proportions",
            "every gemstone identity, cut, color, count, scale, and placement",
            "every setting, prong, connection, chain, clasp, band, and metal fact",
        ),
        style_constraints=brief.style_constraints,
        expected_output=brief.expected_output,
        variant=variant,
    )
    return JewelryImageAgent().run(plan, source_image=source_image)


MarketingImageGenerator = Callable[
    [Spec, bytes, ProductPhotoBrief, int], ImageAgentResult]


def get_marketing_image_generator() -> MarketingImageGenerator:
    return generate_marketing_image_candidate

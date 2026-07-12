"""Injectable image-provider seam and adapter for existing render primitives."""

from __future__ import annotations

from typing import Protocol

from facetta.image_agent.contracts import (
    ImageAgentPlan,
    ImageOperation,
    ImageRoute,
    ProviderImage,
)
from facetta.image_agent.errors import ProviderCallError
from facetta.provider_errors import RenderUnavailable
from facetta.config import env_value


ROUTE_METADATA = {
    ImageRoute.GROK_GENERATE: ("xai", "grok_direct"),
    ImageRoute.GROK_EDIT: ("xai", "grok_direct"),
    ImageRoute.FLUX_GENERATE: ("fal", "flux"),
    ImageRoute.FLUX_KONTEXT_EDIT: ("fal", "flux_kontext"),
    ImageRoute.OPENAI_GENERATE: ("openai", "gpt-image-2"),
    ImageRoute.OPENAI_EDIT: ("openai", "gpt-image-2"),
}


def configured_fallback_provider() -> str | None:
    """Return the currently usable task-safe fallback, in routing priority.

    FLUX remains the first configured fallback.  OpenAI is the supported
    replacement when FAL is unavailable.  Keeping this decision in one place
    prevents the runtime and live-evaluation harness from claiming different
    routing policies.
    """

    if env_value("FAL_KEY"):
        return "fal"
    if env_value("OPENAI_API_KEY"):
        return "openai"
    return None


def available_fallback_route(route: ImageRoute) -> ImageRoute:
    """Resolve a nominal FLUX fallback to the provider available locally."""

    if route not in {
        ImageRoute.FLUX_GENERATE,
        ImageRoute.FLUX_KONTEXT_EDIT,
    }:
        return route
    if configured_fallback_provider() != "openai":
        return route
    return (
        ImageRoute.OPENAI_EDIT
        if route is ImageRoute.FLUX_KONTEXT_EDIT
        else ImageRoute.OPENAI_GENERATE
    )


class ImageProvider(Protocol):
    def execute(
        self,
        plan: ImageAgentPlan,
        route: ImageRoute,
        prompt: str,
        *,
        source_image: bytes | None,
        mask_bytes: bytes | None,
    ) -> ProviderImage: ...


class RenderPrimitiveProvider:
    """Production adapter over ``facetta.render``.

    Importing this adapter never calls a provider. Network work happens only
    when ``execute`` is explicitly invoked, which keeps orchestration tests
    fully deterministic.
    """

    def execute(
        self,
        plan: ImageAgentPlan,
        route: ImageRoute,
        prompt: str,
        *,
        source_image: bytes | None,
        mask_bytes: bytes | None,
    ) -> ProviderImage:
        if route in {ImageRoute.OPENAI_GENERATE, ImageRoute.OPENAI_EDIT}:
            raise ProviderCallError(
                "OpenAI comparison routes require OpenAIImageProvider",
                code="invalid_provider_adapter",
                retryable=False,
            )
        from facetta.render import edit_image, generate_image

        provider, model = ROUTE_METADATA[route]
        del provider  # provider is captured in attempt metadata by the caller
        generation_route = route in {
            ImageRoute.GROK_GENERATE,
            ImageRoute.FLUX_GENERATE,
        }
        reference_backed_spec_render = (
            plan.operation is ImageOperation.SPEC_RENDER
            and plan.source_hash is not None)
        operation_needs_generation = (
            plan.operation in {
                ImageOperation.CREATIVE_GENERATE,
                ImageOperation.CONCEPT_GENERATE,
            }
            or (plan.operation is ImageOperation.SPEC_RENDER
                and not reference_backed_spec_render))
        if operation_needs_generation != generation_route:
            raise ProviderCallError(
                f"route {route.value} does not support {plan.operation.value}",
                code="invalid_provider_route",
                retryable=False,
            )
        try:
            if generation_route:
                image, cached = generate_image(
                    prompt,
                    model=model,
                    variant=plan.variant,
                    discriminator=(f"{plan.prompt_version}:"
                                   f"{plan.spec_visual_hash}:"
                                   f"{plan.input_hash}"),
                )
            else:
                if not source_image:
                    raise ProviderCallError(
                        "edit provider received no source image",
                        code="missing_source_image",
                        retryable=False,
                    )
                image, cached = edit_image(
                    source_image,
                    prompt,
                    model=model,
                    variant=plan.variant,
                    mask_bytes=(mask_bytes
                                if route is ImageRoute.GROK_EDIT else None),
                )
        except ProviderCallError:
            raise
        except RenderUnavailable as exc:
            raise ProviderCallError(str(exc)) from exc
        if not image:
            raise ProviderCallError("image provider returned an empty candidate")
        return ProviderImage(image_bytes=image, cached=cached)


class RoutedImageProvider:
    """Dispatch canonical routes without exposing providers to product code."""

    def __init__(self) -> None:
        self._render = RenderPrimitiveProvider()
        self._openai: ImageProvider | None = None

    def execute(
        self,
        plan: ImageAgentPlan,
        route: ImageRoute,
        prompt: str,
        *,
        source_image: bytes | None,
        mask_bytes: bytes | None,
    ) -> ProviderImage:
        if route in {ImageRoute.OPENAI_GENERATE, ImageRoute.OPENAI_EDIT}:
            if self._openai is None:
                from facetta.image_agent.openai_provider import OpenAIImageProvider

                self._openai = OpenAIImageProvider()
            return self._openai.execute(
                plan,
                route,
                prompt,
                source_image=source_image,
                mask_bytes=mask_bytes,
            )
        return self._render.execute(
            plan,
            route,
            prompt,
            source_image=source_image,
            mask_bytes=mask_bytes,
        )

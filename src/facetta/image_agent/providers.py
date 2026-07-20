"""Injectable image-provider seam and adapter for existing render primitives."""

from __future__ import annotations

import threading
import time
from typing import Protocol

import httpx

from facetta.config import env_value
from facetta.image_agent.contracts import (
    ImageAgentPlan,
    ImageOperation,
    ImageRoute,
    ProviderImage,
)
from facetta.image_agent.errors import ProviderCallError
from facetta.provider_errors import RenderUnavailable


ROUTE_METADATA = {
    ImageRoute.GROK_GENERATE: ("xai", "grok_direct"),
    ImageRoute.GROK_EDIT: ("xai", "grok_direct"),
    ImageRoute.FLUX_GENERATE: ("fal", "flux"),
    ImageRoute.FLUX_KONTEXT_EDIT: ("fal", "flux_kontext"),
    ImageRoute.OPENAI_GENERATE: ("openai", "gpt-image-2"),
    ImageRoute.OPENAI_EDIT: ("openai", "gpt-image-2"),
}


_XAI_QUOTA_EXHAUSTION_MARKERS = (
    "all available credits",
    "used all available credits",
    "insufficient credits",
    "spending limit",
    "monthly spending limit",
    "reached its spending limit",
    "insufficient_quota",
    "quota exhausted",
)

# Quota exhaustion is durable enough that probing xAI again for every Studio
# request only adds latency before the same task-safe fallback. Keep this
# process-local and time bounded: a restart or the first request after expiry
# probes xAI again, so replenished credits recover without operator action.
_XAI_QUOTA_COOLDOWN_SECONDS = 15 * 60
_xai_quota_cooldown_until = 0.0
_xai_quota_cooldown_lock = threading.Lock()


def is_xai_quota_exhaustion(exc: BaseException) -> bool:
    cause: BaseException | None = exc
    while cause is not None:
        if isinstance(cause, httpx.HTTPStatusError):
            return (
                cause.response.status_code == 403
                and any(
                    marker in cause.response.text.casefold()
                    for marker in _XAI_QUOTA_EXHAUSTION_MARKERS
                )
            )
        cause = cause.__cause__
    return False


def note_xai_quota_exhausted() -> None:
    global _xai_quota_cooldown_until
    with _xai_quota_cooldown_lock:
        _xai_quota_cooldown_until = max(
            _xai_quota_cooldown_until,
            time.monotonic() + _XAI_QUOTA_COOLDOWN_SECONDS,
        )


def xai_quota_cooldown_active() -> bool:
    with _xai_quota_cooldown_lock:
        return time.monotonic() < _xai_quota_cooldown_until


def _reset_xai_quota_cooldown() -> None:
    """Reset process-local provider state for deterministic tests."""

    global _xai_quota_cooldown_until
    with _xai_quota_cooldown_lock:
        _xai_quota_cooldown_until = 0.0


def _provider_call_error(
    route: ImageRoute,
    exc: RenderUnavailable,
) -> ProviderCallError:
    """Classify only deterministic xAI quota 403s as fast-fallback errors."""

    if route not in {ImageRoute.GROK_GENERATE, ImageRoute.GROK_EDIT}:
        return ProviderCallError(str(exc))

    if is_xai_quota_exhaustion(exc):
        return ProviderCallError(
            str(exc),
            code="xai_quota_exhausted",
            retryable=False,
            fallback_eligible=True,
        )
    return ProviderCallError(str(exc))


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


def available_configured_route(route: ImageRoute) -> ImageRoute:
    """Use an actually configured provider without spending dead attempts.

    The route remains task-compatible (generate vs edit). When xAI is
    configured it stays primary. If it is absent, the configured fallback is
    promoted for the whole bounded retry budget instead of being tried only
    after two guaranteed credential failures.
    """

    editing = route in {
        ImageRoute.GROK_EDIT,
        ImageRoute.FLUX_KONTEXT_EDIT,
        ImageRoute.OPENAI_EDIT,
    }
    if route in {ImageRoute.GROK_GENERATE, ImageRoute.GROK_EDIT}:
        if env_value("XAI_KEY") and not xai_quota_cooldown_active():
            return route
        provider = configured_fallback_provider()
        if provider == "openai":
            return ImageRoute.OPENAI_EDIT if editing else ImageRoute.OPENAI_GENERATE
        if provider == "fal":
            return ImageRoute.FLUX_KONTEXT_EDIT if editing else ImageRoute.FLUX_GENERATE
        return route
    return available_fallback_route(route)


class ImageProvider(Protocol):
    def execute(
        self,
        plan: ImageAgentPlan,
        route: ImageRoute,
        prompt: str,
        *,
        source_image: bytes | None,
        mask_bytes: bytes | None,
        camera_reference_image: bytes | None = None,
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
        camera_reference_image: bytes | None = None,
    ) -> ProviderImage:
        if camera_reference_image is not None:
            raise ProviderCallError(
                "ordered camera-reference edits require the OpenAI image route",
                code="camera_reference_route_unsupported",
                retryable=False,
            )
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
            (
                plan.operation in {
                    ImageOperation.CREATIVE_GENERATE,
                    ImageOperation.CONCEPT_GENERATE,
                }
                and plan.source_hash is None
            )
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
            provider_error = _provider_call_error(route, exc)
            if provider_error.code == "xai_quota_exhausted":
                note_xai_quota_exhausted()
            raise provider_error from exc
        if not image:
            raise ProviderCallError("image provider returned an empty candidate")
        return ProviderImage(image_bytes=image, cached=cached)


class RoutedImageProvider:
    """Dispatch canonical routes without exposing providers to product code."""

    def __init__(self, *, openai_quality: str = "high") -> None:
        self._render = RenderPrimitiveProvider()
        self._openai: ImageProvider | None = None
        self._openai_quality = openai_quality

    def execute(
        self,
        plan: ImageAgentPlan,
        route: ImageRoute,
        prompt: str,
        *,
        source_image: bytes | None,
        mask_bytes: bytes | None,
        camera_reference_image: bytes | None = None,
    ) -> ProviderImage:
        if route in {ImageRoute.OPENAI_GENERATE, ImageRoute.OPENAI_EDIT}:
            if self._openai is None:
                from facetta.image_agent.openai_provider import OpenAIImageProvider

                self._openai = OpenAIImageProvider(quality=self._openai_quality)
            return self._openai.execute(
                plan,
                route,
                prompt,
                source_image=source_image,
                mask_bytes=mask_bytes,
                camera_reference_image=camera_reference_image,
            )
        return self._render.execute(
            plan,
            route,
            prompt,
            source_image=source_image,
            mask_bytes=mask_bytes,
            camera_reference_image=camera_reference_image,
        )

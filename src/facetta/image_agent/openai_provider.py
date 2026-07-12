"""Direct GPT Image provider used for QA-gated fallback and comparisons.

Grok remains primary. FLUX is preferred when configured; GPT Image is the
task-safe third-attempt replacement when FAL is unavailable. The same adapter
also lets evaluation tools compare a normalized plan, prompt contract, source,
mask, and QA gates directly against GPT Image 2.

For masked edits, Facetta does not trust a generative model to reproduce frozen
pixels.  It sends an alpha mask to the Image Edit API and then composites the
returned patch over the untouched source using the original internal
white-edit/black-preserve mask.  Pixels outside the approved mask therefore
come from the source raster by construction.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import os
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from PIL import Image, ImageChops, ImageFilter, ImageOps

from facetta.config import env_value
from facetta.image_agent.contracts import (
    ImageAgentPlan,
    ImageOperation,
    ImageRoute,
    ProviderImage,
)
from facetta.image_agent.errors import ProviderCallError
from facetta.json_types import JsonObject

OPENAI_IMAGE_MODEL = "gpt-image-2"
OPENAI_GENERATION_URL = "https://api.openai.com/v1/images/generations"
OPENAI_EDIT_URL = "https://api.openai.com/v1/images/edits"
OPENAI_PROVIDER_CONTRACT = "openai-image-provider.v2-inward-mask-feather"


class _Response(Protocol):
    status_code: int
    headers: object

    def json(self) -> object: ...


PostCall = Callable[..., _Response]


def _default_post(url: str, **kwargs) -> _Response:
    import httpx

    return httpx.post(url, **kwargs)


def _png_bytes(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _source_image(source_bytes: bytes) -> Image.Image:
    try:
        source = ImageOps.exif_transpose(
            Image.open(io.BytesIO(source_bytes))
        ).convert("RGBA")
    except Exception as exc:
        raise ProviderCallError(
            "OpenAI image edit source must be a decodable raster",
            code="invalid_openai_source_image",
            retryable=False,
        ) from exc
    return source


def _internal_mask(mask_bytes: bytes, size: tuple[int, int]) -> Image.Image:
    try:
        internal = Image.open(io.BytesIO(mask_bytes)).convert("L")
    except Exception as exc:
        raise ProviderCallError(
            "OpenAI image edit mask must be a decodable raster",
            code="invalid_openai_edit_mask",
            retryable=False,
        ) from exc
    if internal.size != size:
        raise ProviderCallError(
            "OpenAI image edit mask must match the source dimensions",
            code="openai_mask_size_mismatch",
            retryable=False,
        )
    return internal


def _openai_alpha_mask(internal: Image.Image) -> bytes:
    """Translate white-edit/black-preserve into transparent-edit alpha."""

    alpha = ImageOps.invert(internal)
    size = internal.size
    provider_mask = Image.new("RGBA", size, (255, 255, 255, 255))
    provider_mask.putalpha(alpha)
    return _png_bytes(provider_mask)


def _source_output_size(size: tuple[int, int]) -> tuple[int, int]:
    """Fit a source aspect ratio to GPT Image 2's documented size bounds."""

    width, height = size
    ratio = max(width, height) / min(width, height)
    if ratio > 3:
        raise ProviderCallError(
            "OpenAI source aspect ratio exceeds 3:1",
            code="openai_source_aspect_unsupported",
            retryable=False,
        )
    min_pixels = 655_360
    max_pixels = 8_294_400
    max_edge = 3_840
    scale = max(1.0, math.sqrt(min_pixels / (width * height)))
    if max(width, height) * scale > max_edge:
        scale = max_edge / max(width, height)
    if width * height * scale * scale > max_pixels:
        scale = math.sqrt(max_pixels / (width * height))
    target_width = max(16, math.floor(width * scale / 16) * 16)
    target_height = max(16, math.floor(height * scale / 16) * 16)
    while target_width * target_height < min_pixels:
        if target_width / width <= target_height / height:
            target_width += 16
        else:
            target_height += 16
    if (
        target_width > max_edge
        or target_height > max_edge
        or target_width * target_height > max_pixels
    ):
        raise ProviderCallError(
            "OpenAI source cannot be fit within image-size constraints",
            code="openai_source_size_unsupported",
            retryable=False,
        )
    return target_width, target_height


def _composite_masked_patch(
    source: Image.Image,
    candidate_bytes: bytes,
    internal_mask: Image.Image,
    provider_size: tuple[int, int],
) -> bytes:
    try:
        candidate = ImageOps.exif_transpose(
            Image.open(io.BytesIO(candidate_bytes))
        ).convert("RGBA")
    except Exception as exc:
        raise ProviderCallError(
            "OpenAI returned an undecodable image",
            code="invalid_openai_image_response",
            retryable=True,
        ) from exc
    if candidate.size != provider_size:
        raise ProviderCallError(
            "OpenAI masked edit output dimensions differ from the request",
            code="openai_output_size_mismatch",
            retryable=True,
        )
    if candidate.size != source.size:
        candidate = candidate.resize(source.size, Image.Resampling.LANCZOS)
    # Hard mask edges create visible rectangular seams when the provider's
    # local lighting differs slightly from the source. Feather only inward:
    # multiplying by the original mask guarantees every originally protected
    # pixel remains exactly source-authored.
    radius = max(2.0, min(source.size) / 128)
    feathered = internal_mask.filter(ImageFilter.GaussianBlur(radius=radius))
    inward_mask = ImageChops.multiply(feathered, internal_mask)
    composited = Image.composite(candidate, source, inward_mask)
    return _png_bytes(composited)


def openai_route_for_plan(plan: ImageAgentPlan) -> ImageRoute:
    editing = plan.operation in {
        ImageOperation.REFERENCE_RENDER,
        ImageOperation.LOCAL_EDIT,
        ImageOperation.VISUAL_ONLY_EDIT,
        ImageOperation.MOUNTING_VIEW_GENERATE,
    } or (
        plan.operation is ImageOperation.SPEC_RENDER
        and plan.source_hash is not None
    )
    return ImageRoute.OPENAI_EDIT if editing else ImageRoute.OPENAI_GENERATE


class OpenAIImageProvider:
    """ImageProvider adapter for direct GPT Image 2 generation and edits.

    Medium output quality is deliberate: this provider normally appears only
    after two failed Grok attempts, where avoiding another unusable candidate
    matters more than preview-level latency. Callers running cheap comparison
    sweeps can still opt into ``quality="low"`` explicitly.
    """

    def __init__(
        self,
        *,
        model: str = OPENAI_IMAGE_MODEL,
        quality: str = "medium",
        size: str = "source",
        post: PostCall | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        if quality not in {"low", "medium", "high", "auto"}:
            raise ValueError("OpenAI image quality must be low, medium, high, or auto")
        self.model = model
        self.quality = quality
        self.size = size
        self.post = post or _default_post
        root = Path(os.environ.get("FACETTA_RENDER_CACHE", "data/render_cache"))
        self.cache_dir = cache_dir or root / "openai"

    def execute(
        self,
        plan: ImageAgentPlan,
        route: ImageRoute,
        prompt: str,
        *,
        source_image: bytes | None,
        mask_bytes: bytes | None,
    ) -> ProviderImage:
        expected_route = openai_route_for_plan(plan)
        if route is not expected_route:
            raise ProviderCallError(
                f"route {route.value} does not support {plan.operation.value}",
                code="invalid_openai_provider_route",
                retryable=False,
            )
        key = env_value("OPENAI_API_KEY")
        if not key:
            raise ProviderCallError(
                "no OPENAI_API_KEY configured",
                code="openai_provider_not_configured",
                retryable=False,
            )
        if len(prompt) > 32_000:
            raise ProviderCallError(
                "OpenAI image prompt exceeds 32000 characters",
                code="openai_prompt_too_long",
                retryable=False,
            )
        if route is ImageRoute.OPENAI_GENERATE and (source_image or mask_bytes):
            raise ProviderCallError(
                "OpenAI generation route cannot receive source or mask bytes",
                code="invalid_openai_generation_input",
                retryable=False,
            )
        if route is ImageRoute.OPENAI_EDIT and not source_image:
            raise ProviderCallError(
                "OpenAI edit route requires a source image",
                code="missing_openai_source_image",
                retryable=False,
            )

        cache_key = hashlib.sha256(json.dumps({
            "provider_contract": OPENAI_PROVIDER_CONTRACT,
            "model": self.model,
            "quality": self.quality,
            "size": self.size,
            "route": route.value,
            "input_hash": plan.input_hash,
            "prompt": prompt,
            "source_hash": (
                hashlib.sha256(source_image).hexdigest()
                if source_image else None
            ),
            "mask_hash": (
                hashlib.sha256(mask_bytes).hexdigest()
                if mask_bytes else None
            ),
            "variant": plan.variant,
        }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cached = self.cache_dir / f"{cache_key}.png"
        if cached.exists():
            return ProviderImage(image_bytes=cached.read_bytes(), cached=True)

        headers = {"Authorization": f"Bearer {key}"}
        source_raster: Image.Image | None = None
        internal_mask: Image.Image | None = None
        provider_size: tuple[int, int] | None = None
        try:
            if route is ImageRoute.OPENAI_GENERATE:
                request_size = (
                    "1024x1024" if self.size == "source" else self.size
                )
                response = self.post(
                    OPENAI_GENERATION_URL,
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "n": 1,
                        "size": request_size,
                        "quality": self.quality,
                        "output_format": "png",
                        "background": "opaque",
                    },
                    headers={**headers, "Content-Type": "application/json"},
                    timeout=180.0,
                )
            else:
                source_raster = _source_image(source_image or b"")
                provider_size = (
                    _source_output_size(source_raster.size)
                    if self.size == "source"
                    else tuple(int(item) for item in self.size.split("x", 1))
                )
                provider_source = (
                    source_raster
                    if source_raster.size == provider_size
                    else source_raster.resize(
                        provider_size, Image.Resampling.LANCZOS
                    )
                )
                source_png = _png_bytes(provider_source)
                request_size = (
                    f"{provider_size[0]}x{provider_size[1]}"
                )
                files: list[tuple[str, tuple[str, bytes, str]]] = [
                    ("image[]", ("source.png", source_png, "image/png")),
                ]
                if mask_bytes is not None:
                    internal_mask = _internal_mask(
                        mask_bytes, source_raster.size
                    )
                    provider_internal_mask = (
                        internal_mask
                        if internal_mask.size == provider_size
                        else internal_mask.resize(
                            provider_size, Image.Resampling.LANCZOS
                        )
                    )
                    provider_mask = _openai_alpha_mask(provider_internal_mask)
                    files.append(
                        ("mask", ("mask.png", provider_mask, "image/png"))
                    )
                response = self.post(
                    OPENAI_EDIT_URL,
                    data={
                        "model": self.model,
                        "prompt": prompt,
                        "n": "1",
                        "size": request_size,
                        "quality": self.quality,
                        "output_format": "png",
                        "background": "opaque",
                    },
                    files=files,
                    headers=headers,
                    timeout=180.0,
                )
        except ProviderCallError:
            raise
        except Exception as exc:
            raise ProviderCallError(
                f"OpenAI image transport failed: {exc}",
                code="openai_image_transport_failed",
                retryable=True,
            ) from exc

        if response.status_code >= 400:
            detail = self._safe_error_detail(response)
            retryable = response.status_code == 429 or response.status_code >= 500
            raise ProviderCallError(
                f"OpenAI image API returned HTTP {response.status_code}"
                + (f": {detail}" if detail else ""),
                code=f"openai_image_http_{response.status_code}",
                retryable=retryable,
            )
        body = response.json()
        if not isinstance(body, dict):
            raise ProviderCallError(
                "OpenAI image API returned a non-object response",
                code="invalid_openai_image_response",
            )
        data = body.get("data")
        encoded = (
            data[0].get("b64_json")
            if isinstance(data, list) and data and isinstance(data[0], dict)
            else None
        )
        if not isinstance(encoded, str) or not encoded:
            raise ProviderCallError(
                "OpenAI image API returned no base64 image",
                code="invalid_openai_image_response",
            )
        try:
            image = base64.b64decode(encoded, validate=True)
        except Exception as exc:
            raise ProviderCallError(
                "OpenAI image API returned invalid base64 image data",
                code="invalid_openai_image_response",
            ) from exc
        if (
            internal_mask is not None
            and source_raster is not None
            and provider_size is not None
        ):
            image = _composite_masked_patch(
                source_raster, image, internal_mask, provider_size
            )
        else:
            try:
                Image.open(io.BytesIO(image)).verify()
            except Exception as exc:
                raise ProviderCallError(
                    "OpenAI image API returned an undecodable image",
                    code="invalid_openai_image_response",
                ) from exc

        cached.write_bytes(image)
        request_id = None
        response_headers = getattr(response, "headers", None)
        if response_headers is not None and hasattr(response_headers, "get"):
            request_id = response_headers.get("x-request-id")
        usage = body.get("usage")
        return ProviderImage(
            image_bytes=image,
            cached=False,
            provider_request_id=(
                request_id if isinstance(request_id, str) else None
            ),
            usage=usage if isinstance(usage, dict) else None,
        )

    @staticmethod
    def _safe_error_detail(response: _Response) -> str:
        try:
            body = response.json()
        except Exception:
            return ""
        if not isinstance(body, dict):
            return ""
        error = body.get("error", body)
        if not isinstance(error, dict):
            return str(error)[:800]
        safe: JsonObject = {
            key: error[key]
            for key in ("code", "type", "message", "param")
            if key in error and isinstance(error[key], (str, int, float, bool))
        }
        return str(safe)[:800]

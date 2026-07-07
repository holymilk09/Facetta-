"""Photoreal finishing via fal.ai: one button from spec to client image.

The pipeline the whole product funnels into: deterministic code renders the
control image (exact geometry, no lettering), compile_finish_request writes
the trace-don't-redesign instruction, and FLUX Kontext paints realism over
the scaffold. Results are cached by content: the same design in the same
style and lighting is rendered once and served from disk forever — edits
that change geometry or materials change the key and re-render.

The FAL_KEY is read from the environment (or a local .env, which is
gitignored); it must never appear in code, specs, or sheets.
"""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path

from facetta.mockup import compile_finish_request, geometry_fingerprint
from facetta.spec import Spec

CACHE_DIR = Path(os.environ.get("FACETTA_RENDER_CACHE", "data/render_cache"))
PIPELINE_VERSION = "2"  # bump to invalidate every cached render
# v2: pendant profile gained real construction (gallery frame, basket,
# built depth) — control images changed, so cached v1 renders retired

# Three routes to two engines. Each entry knows its key, auth scheme, how
# to wrap our (instruction, control image) pair, and how to find the image
# in the response — the pipeline around them never changes.
MODELS = {
    "flux_kontext": {  # FLUX Kontext via fal
        "endpoint": "https://fal.run/fal-ai/flux-pro/kontext",
        "key_env": "FAL_KEY", "auth": "Key",
        # sync_mode returns the image inline as a data URI, so the result
        # never depends on network access to fal's media hosts
        "payload": lambda prompt, image, extra: {
            "prompt": prompt, "image_url": image, "sync_mode": True,
            "num_images": 1, "output_format": "png", **extra,
        },
        "parse": lambda data: data["images"][0]["url"],
    },
    "grok_imagine": {  # Grok Imagine edit via fal's marketplace
        "endpoint": "https://fal.run/xai/grok-imagine-image/edit",
        "key_env": "FAL_KEY", "auth": "Key",
        "payload": lambda prompt, image, extra: {
            "prompt": prompt, "image_urls": [image], "sync_mode": True,
        },
        "parse": lambda data: data["images"][0]["url"],
    },
    "grok_direct": {  # Grok Imagine edit straight from xAI
        "endpoint": "https://api.x.ai/v1/images/edits",
        "key_env": "XAI_KEY", "auth": "Bearer",
        # b64_json keeps the result inline — no dependency on imgen.x.ai
        "payload": lambda prompt, image, extra: {
            "model": "grok-imagine-image-quality",
            "prompt": prompt,
            "image": {"url": image, "type": "image_url"},
            "response_format": "b64_json",
        },
        "parse": lambda data: (
            "data:image/png;base64," + data["data"][0]["b64_json"]
            if data["data"][0].get("b64_json") else data["data"][0]["url"]),
    },
}


# Text-to-image generation — Grok invents a NEW design from a brief. Separate
# from MODELS (edit endpoints): these take a prompt and no input image.
GENERATION_MODELS = {
    "grok_direct": {
        "endpoint": "https://api.x.ai/v1/images/generations",
        "key_env": "XAI_KEY", "auth": "Bearer",
        "payload": lambda prompt: {
            "model": "grok-imagine-image-quality", "prompt": prompt,
            "n": 1, "response_format": "b64_json"},
        "parse": lambda data: (
            "data:image/png;base64," + data["data"][0]["b64_json"]
            if data["data"][0].get("b64_json") else data["data"][0]["url"]),
    },
    "flux": {
        "endpoint": "https://fal.run/fal-ai/flux-pro/v1.1",
        "key_env": "FAL_KEY", "auth": "Key",
        "payload": lambda prompt: {
            "prompt": prompt, "num_images": 1, "output_format": "png",
            "sync_mode": True},
        "parse": lambda data: data["images"][0]["url"],
    },
}


class RenderUnavailable(Exception):
    """No key, or the provider cannot be reached."""


def _sniff_media_type(image: bytes) -> str:
    """Engines answer JPEG under .png names — trust magic bytes, not names."""
    if image[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if image[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if image[:4] == b"RIFF" and image[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


def _call_engine(model: str, instruction: str, image_data_uri: str,
                 extra: dict) -> bytes:
    """One instruction + one edit-input image through a configured engine."""
    engine_cfg = MODELS[model]
    provider_key = _provider_key(engine_cfg["key_env"])
    if not provider_key:
        raise RenderUnavailable(
            f"no {engine_cfg['key_env']} configured — set it in the "
            "environment or .env")

    import httpx

    payload = engine_cfg["payload"](instruction, image_data_uri, extra)
    try:
        response = httpx.post(
            engine_cfg["endpoint"], json=payload, timeout=180.0,
            headers={"Authorization": f"{engine_cfg['auth']} {provider_key}"})
        response.raise_for_status()
        image_url = engine_cfg["parse"](response.json())
        if image_url.startswith("data:"):
            return base64.b64decode(image_url.split(",", 1)[1])
        image = httpx.get(image_url, timeout=120.0)
        image.raise_for_status()
        return image.content
    except Exception as exc:  # network, auth, schema — all one story upstream
        raise RenderUnavailable(f"render provider failed: {exc}") from exc


def generate_image(prompt: str, model: str = "grok_direct",
                   variant: int = 0) -> tuple[bytes, bool]:
    """Grok invents a NEW design image from a text brief. Content-addressed by
    (prompt, model, variant). Returns (bytes, was_cached).

    Generation is CREATIVE, not deterministic — the same brief can yield a
    different piece each call. Caching by prompt alone froze that: once a brief
    was rendered, every later 'generate again' served the first image forever,
    so a design the designer had since moved past kept coming back. `variant`
    bumps the key, so the app can ask for a genuinely fresh take (variant=1, 2,
    …) without ever colliding with a stale concept from an earlier session."""
    if model not in GENERATION_MODELS:
        raise RenderUnavailable(
            f"unknown generation model '{model}'; options: {list(GENERATION_MODELS)}")
    suffix = f":v{variant}" if variant else ""
    key = hashlib.sha256(
        (PIPELINE_VERSION + ":generate:" + model + ":" + prompt + suffix).encode()
    ).hexdigest()[:32]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = CACHE_DIR / f"{key}.png"
    if cached.exists():
        return cached.read_bytes(), True

    engine = GENERATION_MODELS[model]
    provider_key = _provider_key(engine["key_env"])
    if not provider_key:
        raise RenderUnavailable(
            f"no {engine['key_env']} configured — set it in the environment or .env")

    import httpx

    try:
        response = httpx.post(
            engine["endpoint"], json=engine["payload"](prompt), timeout=180.0,
            headers={"Authorization": f"{engine['auth']} {provider_key}"})
        response.raise_for_status()
        url = engine["parse"](response.json())
        if url.startswith("data:"):
            image = base64.b64decode(url.split(",", 1)[1])
        else:
            got = httpx.get(url, timeout=120.0)
            got.raise_for_status()
            image = got.content
    except Exception as exc:
        raise RenderUnavailable(f"generation provider failed: {exc}") from exc

    cached.write_bytes(image)
    return image, False


def artwork_cache_key(image_bytes: bytes, style: str,
                      model: str = "grok_imagine") -> str:
    """Content-addressed like spec renders: the artwork's bytes pin the
    composition, the instruction carries the style — either changing means
    a genuinely new image. ':artwork:' namespaces these away from spec keys."""
    from facetta.mockup import compile_artwork_restyle_request

    body = compile_artwork_restyle_request(style)
    return hashlib.sha256(
        (PIPELINE_VERSION + ":artwork:" + model + ":"
         + hashlib.sha256(image_bytes).hexdigest()
         + ":" + body["instruction"]).encode()
    ).hexdigest()[:32]


def restyle_artwork(image_bytes: bytes, media_type: str = "image/jpeg",
                    style: str = "rendered_color",
                    model: str = "grok_imagine") -> tuple[bytes, bool]:
    """Restyle the designer's artwork page IN PLACE — the page IS the
    composition, so there is no control image and no spec: the engine only
    changes the rendering style, never the layout. Returns (bytes, cached)."""
    from facetta.mockup import compile_artwork_restyle_request

    if model not in MODELS:
        raise RenderUnavailable(
            f"unknown render model '{model}'; options: {list(MODELS)}")
    body = compile_artwork_restyle_request(style)  # validates the style first
    key = artwork_cache_key(image_bytes, style, model)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = CACHE_DIR / f"{key}.png"
    if cached.exists():
        return cached.read_bytes(), True
    data_uri = (f"data:{media_type};base64,"
                + base64.b64encode(image_bytes).decode())
    image = _call_engine(model, body["instruction"], data_uri,
                         body["provider_payload"])
    cached.write_bytes(image)
    return image, False


def render_from_spec(spec: Spec, model: str = "grok_direct") -> tuple[bytes, bool]:
    """Render the piece straight from the VALIDATED spec — the accurate path.

    The founder's finding: our deterministic drawing stays schematic, but feeding
    the structured spec to Grok renders faithfully because the spec's controlled
    vocabulary keeps it in the design's lane (exact species, cut, mm, metal,
    counts, arrangement). This compiles that spec into a spec-true text-to-image
    prompt and generates from it — no loose brief, no re-reading. Cached by the
    prompt (which is a pure function of the spec), so the same design renders
    once. Returns (bytes, was_cached)."""
    from facetta.prototype import compile_render_prompt

    return generate_image(compile_render_prompt(spec)["prompt"], model=model)


def _provider_key(key_env: str) -> str | None:
    if os.environ.get(key_env):
        return os.environ[key_env]
    env_file = Path(".env")
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith(f"{key_env}="):
                return line.split("=", 1)[1].strip()
    return None


def render_cache_key(spec: Spec, style: str, lighting: str,
                     model: str = "flux_kontext") -> str:
    """Content-addressed: geometry pins the composition, the instruction
    carries colors/metal/style — either changing means a genuinely new image."""
    body = compile_finish_request(spec, style, lighting)
    return hashlib.sha256(
        (PIPELINE_VERSION + model + geometry_fingerprint(spec)
         + body["instruction"]).encode()
    ).hexdigest()[:32]


def render_finished_image(spec: Spec, style: str = "photo",
                          lighting: str = "studio",
                          model: str = "flux_kontext") -> tuple[bytes, bool]:
    """Returns (png_bytes, was_cached). Raises RenderUnavailable without a
    key or when the provider fails — callers translate to 503/502."""
    if model not in MODELS:
        raise RenderUnavailable(
            f"unknown render model '{model}'; options: {list(MODELS)}")
    key = render_cache_key(spec, style, lighting, model)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = CACHE_DIR / f"{key}.png"
    if cached.exists():
        return cached.read_bytes(), True

    import cairosvg  # deferred: rasterizer needs system cairo

    from facetta.plate import render_control_image

    control_png = cairosvg.svg2png(
        bytestring=render_control_image(spec).encode(), output_width=1485)
    body = compile_finish_request(spec, style, lighting)
    png = _call_engine(
        model, body["instruction"],
        "data:image/png;base64," + base64.b64encode(control_png).decode(),
        body["provider_payload"])
    cached.write_bytes(png)
    return png, False

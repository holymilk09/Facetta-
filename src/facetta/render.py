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
PIPELINE_VERSION = "1"  # bump to invalidate every cached render

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
    # NOTE: xAI's edits endpoint accepts public image URLs but rejects our
    # inline data-URI control image (403). Until Facetta hosts control
    # images publicly, use grok_imagine (same engine, via fal, inline OK).
    "grok_direct": {  # Grok Imagine edit straight from xAI
        "endpoint": "https://api.x.ai/v1/images/edits",
        "key_env": "XAI_KEY", "auth": "Bearer",
        "payload": lambda prompt, image, extra: {
            "model": "grok-imagine-image-quality",
            "prompt": prompt,
            "image": {"url": image, "type": "image_url"},
        },
        "parse": lambda data: (
            data["data"][0]["url"] if data["data"][0].get("url")
            else "data:image/png;base64," + data["data"][0]["b64_json"]),
    },
}


class RenderUnavailable(Exception):
    """No key, or the provider cannot be reached."""


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

    engine_cfg = MODELS[model]
    provider_key = _provider_key(engine_cfg["key_env"])
    if not provider_key:
        raise RenderUnavailable(
            f"no {engine_cfg['key_env']} configured — set it in the "
            "environment or .env")

    import cairosvg  # deferred: rasterizer needs system cairo
    import httpx

    from facetta.plate import render_control_image

    control_png = cairosvg.svg2png(
        bytestring=render_control_image(spec).encode(), output_width=1485)
    body = compile_finish_request(spec, style, lighting)
    payload = engine_cfg["payload"](
        body["instruction"],
        "data:image/png;base64," + base64.b64encode(control_png).decode(),
        body["provider_payload"])
    try:
        response = httpx.post(
            engine_cfg["endpoint"], json=payload, timeout=180.0,
            headers={"Authorization": f"{engine_cfg['auth']} {provider_key}"})
        response.raise_for_status()
        image_url = engine_cfg["parse"](response.json())
        if image_url.startswith("data:"):
            png = base64.b64decode(image_url.split(",", 1)[1])
        else:
            image = httpx.get(image_url, timeout=120.0)
            image.raise_for_status()
            png = image.content
    except Exception as exc:  # network, auth, schema — all one story upstream
        raise RenderUnavailable(f"render provider failed: {exc}") from exc

    cached.write_bytes(png)
    return png, False

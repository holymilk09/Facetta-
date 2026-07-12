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

from facetta.cairo_support import load_cairosvg
from facetta.image_identity import spec_visual_hash
from facetta.media import build_mask_guide, sniff_media_type
from facetta.mockup import compile_finish_request, geometry_fingerprint
from facetta.provider_errors import RenderUnavailable
from facetta.spec import Spec

CACHE_DIR = Path(os.environ.get("FACETTA_RENDER_CACHE", "data/render_cache"))
PIPELINE_VERSION = "2"  # bump to invalidate every cached render
# v2: pendant profile gained real construction (gallery frame, basket,
# built depth) — control images changed, so cached v1 renders retired

# Three routes to two engines. Each entry knows its key, auth scheme, how
# to wrap our (instruction, control image) pair, and how to find the image
# in the response — the pipeline around them never changes.


def _grok_direct_edit_payload(
    prompt: str, image: str, extra: dict,
) -> dict:
    references = [image, *list(extra.get("extra_images", []))]
    payload = {
        "model": "grok-imagine-image-quality",
        "prompt": prompt,
    }
    if len(references) == 1:
        payload["image"] = {"url": references[0], "type": "image_url"}
    else:
        payload["images"] = [
            {"url": reference, "type": "image_url"}
            for reference in references
        ]
    return payload


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
        # image_urls is an ARRAY: extra_images (e.g. a house-style reference)
        # ride after the design image — the only edit route that can
        "multi_image": True,
        "payload": lambda prompt, image, extra: {
            "prompt": prompt,
            "image_urls": [image] + list(extra.get("extra_images", [])),
            "sync_mode": True,
        },
        "parse": lambda data: data["images"][0]["url"],
    },
    "grok_direct": {  # Grok Imagine edit straight from xAI
        "endpoint": "https://api.x.ai/v1/images/edits",
        "key_env": "XAI_KEY", "auth": "Bearer",
        "multi_image": True,
        # b64_json keeps the result inline — no dependency on imgen.x.ai
        "payload": _grok_direct_edit_payload,
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
            "n": 1},
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
    "flux_lora": {  # FLUX with the house-style LoRA (facetta.tuning)
        "endpoint": "https://fal.run/fal-ai/flux-lora",
        "key_env": "FAL_KEY", "auth": "Key",
        "payload": lambda prompt: _house_lora_payload(prompt),
        "parse": lambda data: data["images"][0]["url"],
        # a retrained LoRA is a DIFFERENT engine: its URL moves the cache key
        "key_extra": lambda: _house_lora_url(),
    },
}


def _house_lora_record() -> dict:
    from facetta.tuning import house_lora

    record = house_lora()
    if record is None:
        raise RenderUnavailable(
            "no house-style LoRA trained yet — run "
            "facetta.tuning.train_style_lora on the curated set first")
    return record


def _house_lora_url() -> str:
    return _house_lora_record()["url"]


def _house_lora_payload(prompt: str) -> dict:
    record = _house_lora_record()
    return {
        "prompt": f"{record['trigger_word']} style. {prompt}",
        "loras": [{"path": record["url"], "scale": 1.0}],
        "num_images": 1, "output_format": "png", "sync_mode": True,
        "image_size": "square_hd",
    }


# Image-to-video (Grok Imagine): a short showcase clip from a still render.
# Async — POST returns a request_id, then poll GET /v1/videos/{id} until
# status == "done", which returns {"video": {"url", "duration"}}. The mp4
# lives on a separate media host.
VIDEO_MODELS = {
    "grok_video": {
        "endpoint": "https://api.x.ai/v1/videos/generations",
        "poll": "https://api.x.ai/v1/videos/",
        "key_env": "XAI_KEY", "auth": "Bearer",
        "model": "grok-imagine-video",
    },
    "grok_video_hd": {
        "endpoint": "https://api.x.ai/v1/videos/generations",
        "poll": "https://api.x.ai/v1/videos/",
        "key_env": "XAI_KEY", "auth": "Bearer",
        "model": "grok-imagine-video-1.5",
    },
}


# Legacy imports keep working while canonical code uses the public helper.
_sniff_media_type = sniff_media_type


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
    except httpx.HTTPStatusError as exc:
        # Keep enough provider evidence to repair a drifting API contract, but
        # never include request headers, credentials, or the base64 source.
        safe_detail = ""
        try:
            body = exc.response.json()
            error = body.get("error", body) if isinstance(body, dict) else body
            if isinstance(error, dict):
                safe = {
                    key: error[key]
                    for key in ("code", "type", "message", "param")
                    if key in error
                }
                safe_detail = str(safe)[:800]
            else:
                safe_detail = str(error)[:800]
        except Exception:
            safe_detail = exc.response.text[:800]
        suffix = f": {safe_detail}" if safe_detail else ""
        raise RenderUnavailable(
            f"render provider returned HTTP {exc.response.status_code}{suffix}"
        ) from exc
    except Exception as exc:  # network, auth, response schema
        raise RenderUnavailable(f"render provider failed: {exc}") from exc


def generate_image(prompt: str, model: str = "grok_direct",
                   variant: int = 0, discriminator: str = "") -> tuple[bytes, bool]:
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
    engine = GENERATION_MODELS[model]
    provider_key = _provider_key(engine["key_env"])
    if not provider_key:
        raise RenderUnavailable(
            f"no {engine['key_env']} configured — set it in the environment or .env")
    suffix = f":v{variant}" if variant else ""
    if discriminator:  # e.g. the full-spec visual hash, so a design change
        suffix += ":" + discriminator  # never collides with the old render
    key_extra = GENERATION_MODELS[model].get("key_extra")
    if key_extra:      # e.g. the LoRA URL: a retrained style is a new engine
        suffix += ":" + key_extra()
    key = hashlib.sha256(
        (PIPELINE_VERSION + ":generate:" + model + ":" + prompt + suffix).encode()
    ).hexdigest()[:32]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = CACHE_DIR / f"{key}.png"
    if cached.exists():
        return cached.read_bytes(), True

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


STYLE_REF_RULE = (
    "STYLE REFERENCE: the LAST image is a style reference ONLY — match its "
    "rendering style, lighting, finish and overall presentation. The FIRST "
    "image is the design: never copy stones, shapes, settings, or any design "
    "element from the style reference.")

MASK_GUIDE_RULE = (
    "MASK GUIDE: IMAGE 1 is the untouched source and remains the design truth. "
    "IMAGE 2 is only a localization guide: the magenta-tinted, white-outlined "
    "area is editable. Apply the requested change inside that area only and "
    "preserve IMAGE 1 everywhere else. The magenta tint and white outline are "
    "guide marks, not output content; remove them completely from the result."
)


def supports_style_ref(model: str) -> bool:
    """Only engines whose edit route accepts multiple input images can carry
    a house-style reference alongside the design."""
    return bool(MODELS.get(model, {}).get("multi_image"))


def edit_image(image_bytes: bytes, instruction: str,
               model: str = "grok_direct", variant: int = 0,
               style_ref: bytes | None = None,
               mask_bytes: bytes | None = None) -> tuple[bytes, bool]:
    """Instruction-driven edit of a caller-supplied image — the primitive the
    spec agent's image-to-image passes ride on. Content-addressed like
    restyle_artwork: the input bytes pin the source, the instruction carries
    the transformation — either changing means a genuinely new image.
    ':edit:' namespaces these keys away from artwork and spec renders.

    A white-edit/black-preserve ``mask_bytes`` raster becomes a second
    localization-guide image. ``style_ref`` becomes the last image. This fits
    xAI's three-reference limit exactly: untouched source, mask guide, style.
    Engines without multi-image support fail loudly instead of pretending.

    Returns (bytes, was_cached)."""
    if model not in MODELS:
        raise RenderUnavailable(
            f"unknown render model '{model}'; options: {list(MODELS)}")
    if not image_bytes:  # a failed upstream render must not collide on the
        raise RenderUnavailable(  # empty-bytes hash and serve a stale drawing
            "edit_image received an empty source image — the upstream render "
            "produced nothing to edit")
    extra: dict = {}
    extra_images: list[str] = []
    if mask_bytes is not None:
        if not supports_style_ref(model):
            supported = [m for m in MODELS if supports_style_ref(m)]
            raise RenderUnavailable(
                f"model '{model}' cannot carry a mask guide; masked editing "
                f"needs one of {supported}")
        if not mask_bytes:
            raise RenderUnavailable("edit mask is empty")
        try:
            guide = build_mask_guide(image_bytes, mask_bytes)
        except ValueError as exc:
            raise RenderUnavailable(str(exc)) from exc
        instruction = instruction + "\n" + MASK_GUIDE_RULE
        extra_images.append(
            "data:image/png;base64," + base64.b64encode(guide).decode())
    if style_ref is not None:
        if not supports_style_ref(model):
            supported = [m for m in MODELS if supports_style_ref(m)]
            raise RenderUnavailable(
                f"model '{model}' cannot carry a style reference (single-image "
                f"edit route); style anchoring needs one of {supported}")
        if not style_ref:
            raise RenderUnavailable("style reference image is empty")
        instruction = instruction + "\n" + STYLE_REF_RULE
        extra_images.append(
            f"data:{_sniff_media_type(style_ref)};base64,"
            + base64.b64encode(style_ref).decode())
    # Validate all request semantics before checking credentials so callers get
    # a useful contract error (unsupported mask/style/empty input) even when a
    # fallback provider is not configured.  Credential validation still occurs
    # before the cache lookup, so a missing key can never serve stale bytes.
    provider_key = _provider_key(MODELS[model]["key_env"])
    if not provider_key:
        raise RenderUnavailable(
            f"no {MODELS[model]['key_env']} configured — set it in the "
            "environment or .env")
    if extra_images:
        extra["extra_images"] = extra_images
    suffix = f":v{variant}" if variant else ""
    if mask_bytes is not None:
        suffix += ":mask:" + hashlib.sha256(mask_bytes).hexdigest()[:16]
    if style_ref is not None:
        suffix += ":style:" + hashlib.sha256(style_ref).hexdigest()[:16]
    key = hashlib.sha256(
        (PIPELINE_VERSION + ":edit:" + model + ":"
         + hashlib.sha256(image_bytes).hexdigest()
         + ":" + hashlib.sha256(instruction.encode()).hexdigest()
         + suffix).encode()
    ).hexdigest()[:32]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = CACHE_DIR / f"{key}.png"
    if cached.exists():
        return cached.read_bytes(), True
    data_uri = (f"data:{_sniff_media_type(image_bytes)};base64,"
                + base64.b64encode(image_bytes).decode())
    image = _call_engine(model, instruction, data_uri, extra)
    cached.write_bytes(image)
    return image, False


def artwork_cache_key(image_bytes: bytes, style: str,
                      model: str = "grok_direct") -> str:
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
                    model: str = "grok_direct") -> tuple[bytes, bool]:
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


class VideoResult:
    """A finished showcase clip. `data` is the mp4 bytes when the media host is
    reachable; otherwise it is None and only `url` is available (the mp4 lives
    on a media host that a network policy may gate). `duration` is seconds."""

    __slots__ = ("url", "data", "duration", "cached")

    def __init__(self, url: str, data: bytes | None, duration: int | None,
                 cached: bool):
        self.url, self.data, self.duration, self.cached = url, data, duration, cached


def _video_cache_key(image_bytes: bytes, prompt: str, model: str) -> str:
    return hashlib.sha256(
        (PIPELINE_VERSION + ":video:" + model + ":"
         + hashlib.sha256(image_bytes).hexdigest() + ":"
         + hashlib.sha256(prompt.encode()).hexdigest()).encode()
    ).hexdigest()[:32]


def generate_video(image_bytes: bytes, prompt: str, *, model: str = "grok_video",
                   poll_seconds: float = 6.0, max_polls: int = 40,
                   sleep=None) -> VideoResult:
    """Turn a still render into a short showcase clip (image-to-video). Async:
    submit, poll until done, then fetch the mp4. Returns a VideoResult — the
    bytes are cached on disk by (image, prompt, model) so a clip renders once.
    When the media host is unreachable the bytes are None but the url is still
    returned. Raises RenderUnavailable on missing key or provider failure."""
    if model not in VIDEO_MODELS:
        raise RenderUnavailable(
            f"unknown video model '{model}'; options: {list(VIDEO_MODELS)}")
    cfg = VIDEO_MODELS[model]
    key = _video_cache_key(image_bytes, prompt, model)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached_mp4 = CACHE_DIR / f"{key}.mp4"
    cached_url = CACHE_DIR / f"{key}.url"
    if cached_mp4.exists():
        url = cached_url.read_text() if cached_url.exists() else ""
        return VideoResult(url, cached_mp4.read_bytes(), None, True)

    provider_key = _provider_key(cfg["key_env"])
    if not provider_key:
        raise RenderUnavailable(
            f"no {cfg['key_env']} configured — set it in the environment or .env")

    import time as _time

    import httpx

    sleep = sleep or _time.sleep
    headers = {"Authorization": f"{cfg['auth']} {provider_key}"}
    data_uri = (f"data:{_sniff_media_type(image_bytes)};base64,"
                + base64.b64encode(image_bytes).decode())
    try:
        submit = httpx.post(
            cfg["endpoint"], headers=headers, timeout=60.0,
            json={"model": cfg["model"], "prompt": prompt,
                  "image": {"url": data_uri, "type": "image_url"}})
        submit.raise_for_status()
        request_id = submit.json()["request_id"]
        video = None
        for _ in range(max_polls):
            sleep(poll_seconds)
            poll = httpx.get(cfg["poll"] + request_id, headers=headers, timeout=30.0)
            body = poll.json()
            if poll.status_code == 200 or body.get("status") == "done":
                video = body.get("video", {})
                break
            if body.get("status") in ("failed", "error", "moderated"):
                raise RenderUnavailable(f"video generation {body.get('status')}")
        if not video:
            raise RenderUnavailable("video generation timed out")
    except RenderUnavailable:
        raise
    except Exception as exc:
        raise RenderUnavailable(f"video provider failed: {exc}") from exc

    url = video.get("url", "")
    duration = video.get("duration")
    cached_url.write_text(url)
    # fetch the mp4 from the media host; a gated host leaves bytes None but the
    # url is still usable by a client whose network can reach it
    mp4 = None
    try:
        got = httpx.get(url, timeout=120.0)
        got.raise_for_status()
        mp4 = got.content
        cached_mp4.write_bytes(mp4)
    except Exception:
        mp4 = None
    return VideoResult(url, mp4, duration, False)


def render_from_spec(spec: Spec, model: str = "grok_direct",
                     variant: int = 0) -> tuple[bytes, bool]:
    """Render the piece straight from the VALIDATED spec — the accurate path.

    The founder's finding: our deterministic drawing stays schematic, but feeding
    the structured spec to Grok renders faithfully because the spec's controlled
    vocabulary keeps it in the design's lane (exact species, cut, mm, metal,
    counts, arrangement). This compiles that spec into a spec-true text-to-image
    prompt and generates from it — no loose brief, no re-reading. Cached by the
    prompt (which is a pure function of the spec), so the same design renders
    once. Returns (bytes, was_cached)."""
    from facetta.prototype import compile_render_prompt

    # key on the FULL spec, not just the (lossy) prompt: prompt_core drops
    # sections like spec.setting, so a prompt-only key served a stale render
    # when only the setting changed. variant lets the designer force a fresh one.
    return generate_image(compile_render_prompt(spec)["prompt"], model=model,
                          variant=variant, discriminator=spec_visual_hash(spec))


def _provider_key(key_env: str) -> str | None:
    from facetta.config import env_value

    return env_value(key_env)


def render_cache_key(spec: Spec, style: str, lighting: str,
                     model: str = "grok_direct") -> str:
    """Content-addressed: geometry pins the composition, the instruction
    carries colors/metal/style — either changing means a genuinely new image."""
    body = compile_finish_request(spec, style, lighting)
    return hashlib.sha256(
        (PIPELINE_VERSION + model + geometry_fingerprint(spec)
         + body["instruction"] + spec_visual_hash(spec)).encode()
    ).hexdigest()[:32]


def render_finished_image(spec: Spec, style: str = "photo",
                          lighting: str = "studio",
                          model: str = "grok_direct") -> tuple[bytes, bool]:
    """Returns (png_bytes, was_cached). Raises RenderUnavailable without a
    key or when the provider fails — callers translate to 503/502."""
    if model not in MODELS:
        raise RenderUnavailable(
            f"unknown render model '{model}'; options: {list(MODELS)}")
    provider_key = _provider_key(MODELS[model]["key_env"])
    if not provider_key:
        raise RenderUnavailable(
            f"no {MODELS[model]['key_env']} configured — set it in the "
            "environment or .env")
    key = render_cache_key(spec, style, lighting, model)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = CACHE_DIR / f"{key}.png"
    if cached.exists():
        return cached.read_bytes(), True

    cairosvg = load_cairosvg()

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

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
import json
import os
from pathlib import Path

from facetta.mockup import compile_finish_request, geometry_fingerprint
from facetta.spec import Spec

# Fields that do NOT change what the rendered image looks like -- excluded from
# the visual hash so a new version (bumped id/date/notes) doesn't needlessly
# re-render, while every APPEARANCE field (stone, setting, metal, band, ...) IS
# in the key. The old bug was the reverse: appearance fields (setting, metal
# finish, clarity) were in NEITHER the prompt nor the fingerprint, so a changed
# design kept the old key and served a stale image "from ages ago".
_NONVISUAL_SPEC_FIELDS = {
    "design_id", "version", "created_by", "created_at", "schema_version",
    "mode", "notes_to_factory",
}


def spec_visual_hash(spec: Spec) -> str:
    """A stable fingerprint of everything about a spec that affects how the
    rendered piece LOOKS -- the whole spec minus pure metadata. Any appearance
    change (setting, finish, clarity, counts, arrangement) moves this hash, so
    it can never serve a stale render for a design that actually changed."""
    data = {k: v for k, v in spec.model_dump(mode="json").items()
            if k not in _NONVISUAL_SPEC_FIELDS}
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()[:16]

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


STYLE_REF_RULE = (
    "STYLE REFERENCE: the LAST image is a style reference ONLY — match its "
    "rendering style, lighting, finish and overall presentation. The FIRST "
    "image is the design: never copy stones, shapes, settings, or any design "
    "element from the style reference.")


def supports_style_ref(model: str) -> bool:
    """Only engines whose edit route accepts multiple input images can carry
    a house-style reference alongside the design."""
    return bool(MODELS.get(model, {}).get("multi_image"))


def edit_image(image_bytes: bytes, instruction: str,
               model: str = "grok_direct", variant: int = 0,
               style_ref: bytes | None = None) -> tuple[bytes, bool]:
    """Instruction-driven edit of a caller-supplied image — the primitive the
    spec agent's image-to-image passes ride on. Content-addressed like
    restyle_artwork: the input bytes pin the source, the instruction carries
    the transformation — either changing means a genuinely new image.
    ':edit:' namespaces these keys away from artwork and spec renders.

    style_ref is an optional house-style anchor image: it rides as a SECOND
    input with a strict style-only rule, so the output converges on the
    house's rendering style without borrowing design elements. Only engines
    with a multi-image edit route accept it — anywhere else this fails
    LOUDLY rather than silently pretending the style was applied. The style
    bytes are part of the cache key: a changed style set is a different image.

    Returns (bytes, was_cached)."""
    if model not in MODELS:
        raise RenderUnavailable(
            f"unknown render model '{model}'; options: {list(MODELS)}")
    if not image_bytes:  # a failed upstream render must not collide on the
        raise RenderUnavailable(  # empty-bytes hash and serve a stale drawing
            "edit_image received an empty source image — the upstream render "
            "produced nothing to edit")
    extra: dict = {}
    if style_ref is not None:
        if not supports_style_ref(model):
            supported = [m for m in MODELS if supports_style_ref(m)]
            raise RenderUnavailable(
                f"model '{model}' cannot carry a style reference (single-image "
                f"edit route); style anchoring needs one of {supported}")
        if not style_ref:
            raise RenderUnavailable("style reference image is empty")
        instruction = instruction + "\n" + STYLE_REF_RULE
        extra["extra_images"] = [
            f"data:{_sniff_media_type(style_ref)};base64,"
            + base64.b64encode(style_ref).decode()]
    suffix = f":v{variant}" if variant else ""
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
    if os.environ.get(key_env):
        return os.environ[key_env]
    env_file = Path(".env")
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith(f"{key_env}="):
                return line.split("=", 1)[1].strip()
    return None


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

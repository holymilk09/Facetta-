"""LoRA fine-tuning through fal: teach FLUX the house's rendering style from
the designer's approved images.

The whole pipeline is API-driven — zip the curated images, submit a training
job to fal's queue, poll to completion, persist the LoRA weights URL — so a
retrain is one function call whenever the curated set grows. The trained LoRA
registers as the `flux_lora` engine (render.py) whose cache keys carry the
LoRA URL: a retrained style is a DIFFERENT engine, never a stale cache hit.

Code never draws; a LoRA only teaches an engine the house's look.
"""

from __future__ import annotations

import base64
import io
import json
import zipfile
from pathlib import Path

from facetta.render import RenderUnavailable, _provider_key

LORAS_PATH = Path(__file__).resolve().parents[2] / "data" / "loras.json"
TRAIN_ENDPOINT = "https://fal.run/fal-ai/flux-lora-fast-training"
STORAGE_INITIATE = "https://rest.alpha.fal.ai/storage/upload/initiate"
HOUSE_TRIGGER = "FACETTASTYLE"


def load_loras() -> dict:
    if LORAS_PATH.exists():
        return json.loads(LORAS_PATH.read_text())
    return {}


def house_lora() -> dict | None:
    """The registered house-style LoRA, or None when never trained."""
    return load_loras().get("house_style")


def _zip_bytes(image_paths: list[Path]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for p in image_paths:
            z.write(p, p.name)
    return buf.getvalue()


def _upload_archive(key: str, zip_bytes: bytes) -> str:
    """Upload the training archive to fal storage and return its URL. The
    trainer REQUIRES a fetchable URL (a data URI is rejected as 'URL too
    long'), so storage is the only route. NOTE: a restricted network policy
    that blocks rest.alpha.fal.ai blocks training entirely — allow that host
    (and queue.fal.run) or run the training from an unrestricted machine."""
    import httpx

    initiate = httpx.post(
        STORAGE_INITIATE,
        json={"file_name": "facetta_style_train.zip",
              "content_type": "application/zip"},
        headers={"Authorization": f"Key {key}"}, timeout=60.0)
    initiate.raise_for_status()
    body = initiate.json()
    upload = httpx.put(body["upload_url"], content=zip_bytes,
                       headers={"Content-Type": "application/zip"},
                       timeout=300.0)
    upload.raise_for_status()
    return body["file_url"]


def train_style_lora(image_paths: list[Path], *,
                     trigger_word: str = HOUSE_TRIGGER,
                     steps: int = 1000,
                     timeout: float = 1500.0) -> dict:
    """Train a FLUX style LoRA on the curated images (fal, synchronous) and
    persist it as the house style. Returns the stored record
    {"url", "trigger_word", "steps", "images"}. Raises RenderUnavailable on a
    missing key or provider failure — a training run never fails silently."""
    key = _provider_key("FAL_KEY")
    if not key:
        raise RenderUnavailable("no FAL_KEY configured — set it in the "
                                "environment or .env")
    if len(image_paths) < 4:
        raise RenderUnavailable(
            f"a style LoRA needs at least 4 curated images (got "
            f"{len(image_paths)}) — add approved renders first")

    import httpx

    try:
        archive_url = _upload_archive(key, _zip_bytes(image_paths))
        payload = {
            "images_data_url": archive_url,
            "trigger_word": trigger_word,
            "steps": steps,
            "is_style": True,      # style LoRA: learn the look, not a subject
        }
        submit = httpx.post(TRAIN_ENDPOINT, json=payload, timeout=timeout,
                            headers={"Authorization": f"Key {key}"})
        submit.raise_for_status()
        result = submit.json()
        url = (result.get("diffusers_lora_file") or {}).get("url")
        if not url:
            raise RenderUnavailable(
                f"training completed but returned no LoRA file: "
                f"{json.dumps(result)[:300]}")
    except RenderUnavailable:
        raise
    except Exception as exc:
        raise RenderUnavailable(f"LoRA training failed: {exc}") from exc

    record = {"url": url, "trigger_word": trigger_word, "steps": steps,
              "images": len(image_paths)}
    loras = load_loras()
    loras["house_style"] = record
    LORAS_PATH.write_text(json.dumps(loras, indent=1) + "\n")
    return record

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
# the SYNC route: this environment's network policy allows fal.run but not
# queue.fal.run, so the training call holds the connection until done
TRAIN_ENDPOINT = "https://fal.run/fal-ai/flux-lora-fast-training"
HOUSE_TRIGGER = "FACETTASTYLE"


def load_loras() -> dict:
    if LORAS_PATH.exists():
        return json.loads(LORAS_PATH.read_text())
    return {}


def house_lora() -> dict | None:
    """The registered house-style LoRA, or None when never trained."""
    return load_loras().get("house_style")


def _zip_data_uri(image_paths: list[Path]) -> str:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for p in image_paths:
            z.write(p, p.name)
    return ("data:application/zip;base64,"
            + base64.b64encode(buf.getvalue()).decode())


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

    payload = {
        "images_data_url": _zip_data_uri(image_paths),
        "trigger_word": trigger_word,
        "steps": steps,
        "is_style": True,          # style LoRA: learn the look, not a subject
    }
    try:
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

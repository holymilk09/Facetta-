"""LoRA fine-tuning through fal: teach FLUX the house's rendering style from
the designer's approved images.

Two halves:

- `export_approved_training_set` turns the designer's REAL approvals (pinned
  or accepted assets) into a curated style set — the moat. This is the source
  worth training on; it accrues as the app is used.
- `train_style_lora` uploads that set to fal storage, trains a FLUX style
  LoRA, and persists the weights URL. The trained LoRA registers as the
  `flux_lora` engine (render.py) whose cache keys carry the LoRA URL: a
  retrained style is a DIFFERENT engine, never a stale cache hit.

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


# --- curation: which images belong in a STYLE training set -------------------
#
# A style LoRA should learn the house's PRODUCT look, not the artifacts around
# it. Two things never belong: technical drawings (near-white, colourless —
# they would teach line-art, not style) and, for a product-style LoRA, worn/
# hand shots (skin dominates the frame and biases the model toward hands).
# The thresholds are heuristic; approval is always the primary signal, so this
# only filters the obvious wrong shapes and REPORTS every drop — never silent.

def is_style_worthy(image_bytes: bytes, *, product_only: bool = True,
                    min_side: int = 512) -> tuple[bool, str]:
    """(ok, reason) — is this image a good STYLE training example? Rejects
    technical drawings and (when product_only) likely worn/hand shots and
    anything too small. reason is empty when ok."""
    from PIL import Image, ImageStat

    try:
        im = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception as exc:
        return False, f"unreadable image ({exc})"
    if min(im.size) < min_side:
        return False, f"too small ({im.size[0]}x{im.size[1]})"
    brightness = sum(ImageStat.Stat(im).mean) / 3
    saturation = ImageStat.Stat(im.convert("HSV")).mean[1]
    # a technical drawing: very bright and nearly colourless
    if brightness >= 235 and saturation <= 20:
        return False, "looks like a technical drawing (near-white, desaturated)"
    if product_only and saturation > 55 and brightness < 140:
        return False, "looks like a worn/hand shot (skin-dominated)"
    return True, ""


# capabilities that are NOT photoreal product renders — never style examples
_NON_STYLE_CAPABILITIES = {"MANUFACTURING_TECHNICAL_DRAWING"}


def export_approved_training_set(db, out_dir: Path, *,
                                 product_only: bool = True,
                                 min_side: int = 512) -> dict:
    """Turn the designer's REAL approvals into a style training set — the moat.

    An asset counts as approved when it is pinned (`pinned_at`) OR carries an
    `accepted` FeedbackEvent. Only image renders qualify (technical drawings
    excluded by capability); each is run through `is_style_worthy` and the
    survivors are written as downscaled JPEGs to out_dir. Returns a manifest
    {"kept": int, "dropped": [{"id", "reason"}], "out_dir": str} — every
    rejected candidate is reported, so a thin set never masquerades as a full
    one. When `kept` is large enough (~30+), feed out_dir to train_style_lora."""
    from sqlalchemy import select

    from facetta.db import FeedbackEvent, ImageAsset

    accepted_ids = set(db.scalars(
        select(FeedbackEvent.asset_id).where(
            FeedbackEvent.action == "accepted")).all())
    assets = db.scalars(select(ImageAsset)).all()

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    kept: list[str] = []
    dropped: list[dict] = []
    seen: set[str] = set()
    for asset in assets:
        approved = asset.pinned_at is not None or asset.id in accepted_ids
        if not approved or asset.id in seen:
            continue
        seen.add(asset.id)
        if not (asset.media_type or "").startswith("image/"):
            dropped.append({"id": asset.id, "reason": "not an image"})
            continue
        if asset.capability in _NON_STYLE_CAPABILITIES:
            dropped.append({"id": asset.id, "reason": "technical drawing"})
            continue
        ok, reason = is_style_worthy(bytes(asset.image),
                                     product_only=product_only,
                                     min_side=min_side)
        if not ok:
            dropped.append({"id": asset.id, "reason": reason})
            continue
        _write_jpeg(bytes(asset.image), out_dir / f"{asset.id}.jpg")
        kept.append(asset.id)
    return {"kept": len(kept), "dropped": dropped, "out_dir": str(out_dir)}


def _write_jpeg(image_bytes: bytes, path: Path, *, max_side: int = 1024) -> None:
    from PIL import Image

    im = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    im.thumbnail((max_side, max_side))
    im.save(path, "JPEG", quality=88)


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

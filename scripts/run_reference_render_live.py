"""Run one bounded live drawing/image -> beauty-render evaluation.

The script writes evidence only: source hash, plan/prompt version, attempts,
QA, and the review candidate when one is returned. It never persists a product
project or promotes output to factory truth.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from facetta.config import load_env_file
from facetta.image_agent import (
    ImageAgentError,
    ImageOperation,
    JewelryImageAgent,
    build_image_plan,
)
from facetta.image_region import ImageRegionError, crop_normalized_region
from facetta.media import sniff_media_type


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _extension(media_type: str) -> str:
    return {
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/webp": "webp",
    }.get(media_type, "bin")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--instruction", required=True)
    parser.add_argument("--variant", type=int, default=0)
    parser.add_argument(
        "--source-region",
        type=float,
        nargs=4,
        metavar=("X", "Y", "WIDTH", "HEIGHT"),
        help="normalized designer-selected source rectangle",
    )
    parser.add_argument("--source-region-description")
    args = parser.parse_args()

    load_env_file()
    source = args.source.read_bytes()
    render_source = source
    source_region = None
    region_description = None
    if args.source_region_description and args.source_region is None:
        parser.error("--source-region-description requires --source-region")
    if args.source_region is not None:
        x, y, width, height = args.source_region
        try:
            render_source = crop_normalized_region(
                source, x=x, y=y, width=width, height=height,
            )
        except ImageRegionError as exc:
            parser.error(str(exc))
        source_region = {
            "x": x,
            "y": y,
            "width": width,
            "height": height,
        }
        label = args.source_region_description or "Designer-selected jewelry view"
        region_description = (
            f"{label}; normalized crop x={x:.4f}, y={y:.4f}, "
            f"width={width:.4f}, height={height:.4f}"
        )
    plan = build_image_plan(
        ImageOperation.REFERENCE_RENDER,
        args.instruction,
        source_image=render_source,
        variant=args.variant,
        region_description=region_description,
        style_constraints=(
            "luxury fine-jewelry product render",
            "clean neutral studio presentation",
            "keep the complete visible source design reviewable",
        ),
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    common = {
        "result_set": args.output_dir.name,
        "executed_at": datetime.now(UTC).isoformat(),
        "source": str(args.source),
        "source_sha256": _sha256(source),
        "render_source_sha256": _sha256(render_source),
        "source_region": source_region,
        "source_region_description": region_description,
        "instruction": args.instruction,
        "operation": plan.operation.value,
        "prompt_version": plan.prompt_version,
        "input_hash": plan.input_hash,
        "variant": plan.variant,
        "maximum_attempts": 3,
        "product_asset_persisted": False,
        "factory_authoritative": False,
    }
    if source_region is not None:
        crop_media_type = sniff_media_type(render_source)
        crop_name = f"source-region.{_extension(crop_media_type)}"
        (args.output_dir / crop_name).write_bytes(render_source)
        common["source_region_file"] = crop_name
    try:
        result = JewelryImageAgent().run(plan, source_image=render_source)
    except ImageAgentError as exc:
        summary = {
            **common,
            "status": "failed",
            "error": exc.as_dict(),
            "candidate_file": None,
        }
        (args.output_dir / "summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n")
        return 2

    media_type = sniff_media_type(result.image_bytes)
    candidate_name = f"candidate.{_extension(media_type)}"
    (args.output_dir / candidate_name).write_bytes(result.image_bytes)
    summary = {
        **common,
        "status": result.run.status.value,
        "accepted": result.accepted,
        "review_required": result.review_required,
        "verdict": result.quality.verdict.value,
        "candidate_file": candidate_name,
        "candidate_media_type": media_type,
        "candidate_sha256": _sha256(result.image_bytes),
        "quality": result.quality.model_dump(mode="json"),
        "attempts": [
            attempt.model_dump(mode="json")
            for attempt in result.run.attempts
        ],
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Run one bounded live prompt -> pre-spec jewelry concept evaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from facetta.config import load_env_file
from facetta.image_agent import ImageAgentError
from facetta.creative_workflow import generate_creative_prompt
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
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--variant", type=int, default=0)
    args = parser.parse_args()

    load_env_file()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    common = {
        "result_set": args.output_dir.name,
        "executed_at": datetime.now(UTC).isoformat(),
        "designer_prompt": args.prompt,
        "variant": args.variant,
        "maximum_attempts": 3,
        "product_asset_persisted": False,
        "specification_created": False,
        "factory_authoritative": False,
    }
    try:
        result = generate_creative_prompt(args.prompt, args.variant)
    except ImageAgentError as exc:
        summary = {
            **common,
            "operation": exc.plan.operation.value if exc.plan else None,
            "prompt_version": exc.plan.prompt_version if exc.plan else None,
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
        "operation": result.plan.operation.value,
        "prompt_version": result.plan.prompt_version,
        "input_hash": result.plan.input_hash,
        "jewelry_type": result.plan.jewelry_type,
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

"""Generate one accuracy-first Grok mounting view for manual evaluation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from facetta.config import load_env_file
from facetta.mounting_hardware import compile_mounting_view_prompt
from facetta.render import edit_image
from facetta.ring_evals import RING_GOLDEN_CASES, build_ring_golden_spec


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--view", choices=("plan", "front", "side", "section"), required=True)
    parser.add_argument("--golden-case", required=True)
    parser.add_argument("--variant", type=int, default=0)
    parser.add_argument("--correction", default="")
    args = parser.parse_args()

    load_env_file()
    case = next(
        (item for item in RING_GOLDEN_CASES if item.id == args.golden_case),
        None,
    )
    if case is None:
        raise SystemExit(f"unknown ring golden case: {args.golden_case}")
    spec = build_ring_golden_spec(case)
    prompt = compile_mounting_view_prompt(
        spec, args.view, correction=args.correction)
    output, cached = edit_image(
        args.source.read_bytes(), prompt, "grok_direct", variant=args.variant)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    suffix = ".png" if output.startswith(b"\x89PNG") else ".jpg"
    output_path = args.output_dir / f"grok-{args.view}{suffix}"
    output_path.write_bytes(output)
    (args.output_dir / "prompt.txt").write_text(prompt + "\n")
    result = {
        "live": True,
        "provider": "xai",
        "model_role": "grok_primary",
        "view": args.view,
        "source": str(args.source.resolve()),
        "output": str(output_path.resolve()),
        "cached": cached,
        "validated_spec": spec.model_dump(mode="json"),
        "authority": "proposed_designer_confirmation_required",
        "production_authority": False,
        "manual_review": {"status": "pending", "verdict": None},
    }
    (args.output_dir / "results.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(output_path),
        "cached": cached,
        "review_status": "pending",
    }))


if __name__ == "__main__":
    main()

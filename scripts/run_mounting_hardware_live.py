"""Run one live Grok mounting-hardware technical-illustration probe.

This is intentionally separate from unit tests: it spends provider credits and
stores the exact prompt, output, and authority metadata for visual review.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from facetta.config import load_env_file
from facetta.mounting_hardware import compile_mounting_hardware_prompt
from facetta.ring_evals import RING_GOLDEN_CASES, build_ring_golden_spec
from facetta.specagent import generate_spec_sheet


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--variant", type=int, default=0)
    parser.add_argument("--golden-case")
    parser.add_argument("--correction", default="")
    args = parser.parse_args()

    load_env_file()
    source = args.source.read_bytes()
    spec = None
    if args.golden_case:
        case = next(
            (item for item in RING_GOLDEN_CASES if item.id == args.golden_case),
            None,
        )
        if case is None:
            raise SystemExit(f"unknown ring golden case: {args.golden_case}")
        spec = build_ring_golden_spec(case)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    drawing, summary, cached = generate_spec_sheet(
        source,
        mode="RING_ENGAGEMENT",
        region="DUAL",
        templated=True,
        variant=args.variant,
        spec=spec,
        notes=(
            "Preserve this exact approved cushion halo ring and six-prong "
            "topology. Make the SIDE mounting construction especially clear. "
            "Include one TRUE CUT SECTION through the center-stone axis that "
            "visibly cuts the stone, seat, gallery, undergallery, and head "
            "connection; do not substitute another exterior elevation. "
            + args.correction.strip()
        ),
    )
    suffix = ".png" if drawing.startswith(b"\x89PNG") else ".jpg"
    output_path = args.output_dir / f"grok-mounting-composite{suffix}"
    output_path.write_bytes(drawing)
    (args.output_dir / "prompt.txt").write_text(
        compile_mounting_hardware_prompt("RING_ENGAGEMENT") + "\n"
    )
    result = {
        "live": True,
        "provider": "xai",
        "model_role": "grok_primary",
        "source": str(args.source.resolve()),
        "output": str(output_path.resolve()),
        "cached": cached,
        "validated_spec_used": spec is not None,
        "summary": summary,
        "manual_review": {
            "status": "pending",
            "checks": [
                "side view contains a design-specific stone seat or bearing",
                "prong roots connect continuously into metal",
                "basket and gallery match the approved design",
                "undergallery or bridge is structurally coherent",
                "head connects coherently to shoulders and shank",
                "plan/front/side/section use one consistent hardware topology",
                "no hidden proposal is mistaken for production-confirmed geometry",
            ],
        },
    }
    (args.output_dir / "results.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps({
        "output": str(output_path),
        "cached": cached,
        "review_status": "pending",
    }))


if __name__ == "__main__":
    main()

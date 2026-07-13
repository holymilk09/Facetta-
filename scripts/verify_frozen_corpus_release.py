"""Compile the founder-approved frozen-corpus gate decision."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from facetta.frozen_corpus_release import verify_frozen_corpus_release  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--approval", type=Path, required=True)
    parser.add_argument(
        "--config", type=Path,
        default=ROOT / "docs/evals/frozen-founder-corpus-v1/config.json",
    )
    parser.add_argument("--outdir", type=Path, required=True)
    args = parser.parse_args()
    decision = verify_frozen_corpus_release(
        args.results, args.config, args.approval,
    )
    args.outdir.mkdir(parents=True, exist_ok=True)
    (args.outdir / "final-decision.json").write_text(
        json.dumps(decision, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps({
        "status": decision["status"],
        "corpus_gate_ready": decision["corpus_gate_ready"],
        "artifact": str(args.outdir / "final-decision.json"),
    }, indent=2))
    return 0 if decision["corpus_gate_ready"] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())

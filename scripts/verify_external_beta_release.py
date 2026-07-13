#!/usr/bin/env python3
"""Compose signed corpus and staging evidence into one beta decision."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from facetta.external_beta_release import verify_external_beta_release  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus-decision", type=Path, required=True)
    parser.add_argument("--corpus-results", type=Path, required=True)
    parser.add_argument("--corpus-approval", type=Path, required=True)
    parser.add_argument("--corpus-exit-code", type=Path, required=True)
    parser.add_argument("--designer-approval", type=Path, required=True)
    parser.add_argument("--designer-decisions", type=Path, required=True)
    parser.add_argument("--staging-results", type=Path, required=True)
    parser.add_argument("--staging-approval", type=Path, required=True)
    parser.add_argument("--staging-exit-code", type=Path, required=True)
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "docs/evals/frozen-founder-corpus-v1/config.json",
    )
    parser.add_argument("--outdir", type=Path, required=True)
    args = parser.parse_args()

    decision = verify_external_beta_release(
        args.corpus_decision,
        args.corpus_results,
        args.corpus_approval,
        args.corpus_exit_code,
        args.config,
        args.designer_decisions,
        args.designer_approval,
        args.staging_results,
        args.staging_approval,
        args.staging_exit_code,
    )
    args.outdir.mkdir(parents=True, exist_ok=True)
    artifact = args.outdir / "external-beta-decision.json"
    artifact.write_text(json.dumps(decision, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "status": decision["status"],
        "external_beta_ready": decision["external_beta_ready"],
        "artifact": str(artifact),
    }, indent=2))
    return 0 if decision["external_beta_ready"] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())

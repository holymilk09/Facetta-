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
    parser.add_argument("--corpus-manifest", type=Path, required=True)
    parser.add_argument("--corpus-source-dir", type=Path, required=True)
    parser.add_argument("--corpus-evidence", type=Path, required=True)
    parser.add_argument("--corpus-evidence-root", type=Path, required=True)
    parser.add_argument("--corpus-workload", type=Path, required=True)
    parser.add_argument("--gia-review-packet", type=Path, required=True)
    parser.add_argument("--gia-review-ledger", type=Path, required=True)
    parser.add_argument("--designer-review-packet", type=Path, required=True)
    parser.add_argument("--designer-review-ledger", type=Path, required=True)
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
        args.designer_review_packet,
        args.designer_review_ledger,
        args.staging_results,
        args.staging_approval,
        args.staging_exit_code,
        corpus_manifest_path=args.corpus_manifest,
        corpus_source_dir=args.corpus_source_dir,
        corpus_evidence_path=args.corpus_evidence,
        corpus_evidence_root=args.corpus_evidence_root,
        corpus_workload_path=args.corpus_workload,
        gia_review_packet_path=args.gia_review_packet,
        gia_review_ledger_path=args.gia_review_ledger,
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

"""Compile the founder-approved frozen-corpus gate decision."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from facetta.frozen_corpus_release import verify_frozen_corpus_release  # noqa: E402
from facetta.frozen_evidence_paths import (  # noqa: E402
    confined_output_path,
    evidence_root,
    require_new_artifact_paths,
    retained_cli_entrypoint,
    write_new_text_artifact,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--approval", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--workload", type=Path, required=True)
    parser.add_argument("--gia-review-packet", type=Path, required=True)
    parser.add_argument("--gia-review-ledger", type=Path, required=True)
    parser.add_argument(
        "--config", type=Path,
        default=ROOT / "docs/evals/frozen-founder-corpus-v1/config.json",
    )
    parser.add_argument("--outdir", type=Path, required=True)
    args = parser.parse_args()
    resolved_evidence_root = evidence_root(args.evidence_root)
    output_dir = confined_output_path(
        resolved_evidence_root, args.outdir, label="final decision output directory",
    )
    artifact = output_dir / "final-decision.json"
    require_new_artifact_paths([artifact], root=resolved_evidence_root)
    decision = verify_frozen_corpus_release(
        args.results, args.config, args.approval,
        manifest_path=args.manifest,
        source_dir=args.source_dir,
        evidence_path=args.evidence,
        evidence_root=args.evidence_root,
        workload_path=args.workload,
        gia_review_packet_path=args.gia_review_packet,
        gia_review_ledger_path=args.gia_review_ledger,
    )
    write_new_text_artifact(
        artifact,
        json.dumps(decision, indent=2, sort_keys=True) + "\n",
        root=resolved_evidence_root,
    )
    print(json.dumps({
        "status": decision["status"],
        "corpus_gate_ready": decision["corpus_gate_ready"],
        "artifact": str(artifact),
    }, indent=2))
    return 0 if decision["corpus_gate_ready"] is True else 1


if __name__ == "__main__":
    raise SystemExit(retained_cli_entrypoint(main))

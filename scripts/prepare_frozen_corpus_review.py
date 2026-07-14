"""Prepare an unsigned frozen-corpus review packet without provider calls."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from facetta.blind_jewelry_review import (  # noqa: E402
    GIA_VISUAL_FIDELITY_ROLE,
    INDEPENDENT_DESIGNER_ROLE,
)
from facetta.frozen_corpus_packet import (  # noqa: E402
    prepare_blind_frozen_corpus_review_packet_v2,
    prepare_frozen_corpus_review_packet,
)
from facetta.frozen_evidence_paths import (  # noqa: E402
    confined_output_path,
    evidence_root,
    require_new_artifact_paths,
    retained_cli_entrypoint,
    write_new_text_artifact,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    frozen = ROOT / "docs/evals/frozen-founder-corpus-v1"
    parser.add_argument("--manifest", type=Path, default=frozen / "manifest.json")
    parser.add_argument("--config", type=Path, default=frozen / "config.json")
    parser.add_argument("--workload", type=Path, default=frozen / "workload.json")
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--capture-public-key", type=Path, required=True)
    parser.add_argument("--capture-key-id", required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--packet-format",
        choices=("replay-v1", "blind-v2"),
        default="replay-v1",
        help="Keep replay-v1 for compatibility or emit the reviewer-safe blind-v2 artifact.",
    )
    parser.add_argument(
        "--review-seed",
        help="Required for blind-v2: 64 lowercase hex characters used for reproducible review order.",
    )
    parser.add_argument(
        "--reviewer-role",
        choices=(GIA_VISUAL_FIDELITY_ROLE, INDEPENDENT_DESIGNER_ROLE),
        default=GIA_VISUAL_FIDELITY_ROLE,
        help="Role-specific blind-v2 rubric.",
    )
    args = parser.parse_args()
    resolved_evidence_root = evidence_root(args.evidence_root)
    output_path = confined_output_path(
        resolved_evidence_root, args.out, label="review packet output",
    )
    common = {
        "evidence_root": resolved_evidence_root,
        "capture_public_key_path": args.capture_public_key,
        "capture_key_id": args.capture_key_id,
        "repository_root": ROOT,
    }
    require_new_artifact_paths([output_path], root=resolved_evidence_root)
    if args.packet_format == "blind-v2":
        if args.review_seed is None:
            parser.error("--review-seed is required with --packet-format blind-v2")
        packet = prepare_blind_frozen_corpus_review_packet_v2(
            args.manifest,
            args.config,
            args.workload,
            args.source_dir,
            args.capture,
            review_seed=args.review_seed,
            reviewer_role=args.reviewer_role,
            **common,
        )
    else:
        if args.review_seed is not None:
            parser.error("--review-seed is only valid with --packet-format blind-v2")
        packet = prepare_frozen_corpus_review_packet(
            args.manifest,
            args.config,
            args.workload,
            args.source_dir,
            args.capture,
            **common,
        )
    write_new_text_artifact(
        output_path,
        json.dumps(packet, indent=2, sort_keys=True) + "\n",
        root=resolved_evidence_root,
    )
    if args.packet_format == "blind-v2":
        summary = {
            "status": packet["review_status"],
            "packet_format": args.packet_format,
            "provider_calls": 0,
            "reviewer_role": packet["review_protocol"]["reviewer_role"],
            "review_item_count": len(packet["items"]),
            "corpus_gate_ready": False,
            "artifact": output_path.relative_to(resolved_evidence_root).as_posix(),
        }
    else:
        summary = {
            "status": packet["packet_status"],
            "packet_format": args.packet_format,
            "provider_calls": 0,
            "attempt_count": len(packet["attempts"]),
            "quality_source_count": packet["quality_scope"]["source_count"],
            "evaluation_sequence_count": packet["quality_scope"][
                "evaluation_sequence_count"
            ],
            "integrity_status": packet["integrity_prerequisite"]["status"],
            "corpus_gate_ready": False,
            "artifact": output_path.relative_to(resolved_evidence_root).as_posix(),
        }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(retained_cli_entrypoint(main))

"""Prepare an unsigned frozen-corpus review packet without provider calls."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from facetta.frozen_corpus_packet import prepare_frozen_corpus_review_packet  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    frozen = ROOT / "docs/evals/frozen-founder-corpus-v1"
    parser.add_argument("--manifest", type=Path, default=frozen / "manifest.json")
    parser.add_argument("--config", type=Path, default=frozen / "config.json")
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    packet = prepare_frozen_corpus_review_packet(
        args.manifest, args.config, args.source_dir, args.capture,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "status": packet["packet_status"], "provider_calls": 0,
        "attempt_count": len(packet["attempts"]), "artifact": str(args.out),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

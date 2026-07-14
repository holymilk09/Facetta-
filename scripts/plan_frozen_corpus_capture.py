"""Validate or expand the frozen capture workload without provider calls."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from facetta.frozen_capture_workload import (  # noqa: E402
    build_provider_call_plan,
    validate_capture_envelope,
    validate_workload_definition,
)
from facetta.frozen_evidence_paths import (  # noqa: E402
    require_new_artifact_paths,
    retained_cli_entrypoint,
    write_new_text_artifact,
)


DEFAULT_DIR = ROOT / "docs" / "evals" / "frozen-founder-corpus-v1"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_DIR / "manifest.json")
    parser.add_argument("--config", type=Path, default=DEFAULT_DIR / "config.json")
    parser.add_argument("--workload", type=Path, default=DEFAULT_DIR / "workload.json")
    parser.add_argument("--out", type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate-definition")
    subparsers.add_parser("plan")
    capture = subparsers.add_parser("validate-capture")
    capture.add_argument("--capture", type=Path, required=True)
    capture.add_argument("--capture-public-key", type=Path, required=True)
    capture.add_argument("--capture-key-id", required=True)
    args = parser.parse_args()
    if args.out:
        require_new_artifact_paths([args.out])

    if args.command == "validate-definition":
        result = validate_workload_definition(args.manifest, args.config, args.workload)
    elif args.command == "plan":
        result = build_provider_call_plan(args.manifest, args.config, args.workload)
    else:
        result = validate_capture_envelope(
            args.capture,
            args.manifest,
            args.config,
            args.workload,
            capture_public_key_path=args.capture_public_key,
            capture_key_id=args.capture_key_id,
        )
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.out:
        write_new_text_artifact(args.out, rendered)
    print(rendered, end="")
    return 0 if result["status"] in {"pass", "plan_ready"} else 1


if __name__ == "__main__":
    raise SystemExit(retained_cli_entrypoint(main))

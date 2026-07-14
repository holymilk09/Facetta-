#!/usr/bin/env python3
"""Create and sign provider-free blind-review ledger forms."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from facetta.blind_review_ledger_authoring import (  # noqa: E402
    author_signed_blind_review_ledger,
    build_blind_review_authoring_template,
    load_enrolled_blind_reviewer,
)
from facetta.blind_jewelry_review import (  # noqa: E402
    GIA_VISUAL_FIDELITY_ROLE,
    INDEPENDENT_DESIGNER_ROLE,
)
from facetta.frozen_evidence_paths import (  # noqa: E402
    confined_output_path,
    confined_path,
    evidence_root,
    require_new_artifact_paths,
    retained_cli_entrypoint,
    write_new_text_artifact,
)


Json = dict[str, Any]
CANONICAL_CONFIG_RELATIVE = Path("docs/evals/frozen-founder-corpus-v1/config.json")


def _object(path: Path, *, label: str) -> Json:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _canonical_config(packet: Json) -> Json:
    repository_root = ROOT.resolve()
    config_path = (repository_root / CANONICAL_CONFIG_RELATIVE).resolve()
    if not config_path.is_relative_to(repository_root) or not config_path.is_file():
        raise ValueError("canonical frozen reviewer config is unavailable")
    content = config_path.read_bytes()
    binding = packet.get("evidence_binding")
    expected_sha256 = (
        binding.get("config_sha256") if isinstance(binding, dict) else None
    )
    actual_sha256 = hashlib.sha256(content).hexdigest()
    if expected_sha256 != actual_sha256:
        raise ValueError(
            "blind-review packet is not bound to the canonical frozen reviewer config"
        )
    value = json.loads(content)
    if not isinstance(value, dict):
        raise ValueError("canonical frozen reviewer config must be a JSON object")
    return value


def _common(subparser: argparse.ArgumentParser) -> None:
    subparser.add_argument("--evidence-root", type=Path, required=True)
    subparser.add_argument("--packet", type=Path, required=True)
    subparser.add_argument("--out", type=Path, required=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Author an exact signed criterion ledger without image-provider calls."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    template = subparsers.add_parser(
        "template",
        help="Create a fresh human-fillable form with locked packet bindings.",
    )
    _common(template)
    template.add_argument(
        "--reviewer-role",
        choices=(GIA_VISUAL_FIDELITY_ROLE, INDEPENDENT_DESIGNER_ROLE),
        required=True,
    )
    sign = subparsers.add_parser(
        "sign",
        help="Sign a completed form and self-verify it before retention.",
    )
    _common(sign)
    sign.add_argument("--template", type=Path, required=True)
    sign.add_argument("--private-key", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    resolved_evidence_root = evidence_root(args.evidence_root)
    packet_path = confined_path(
        resolved_evidence_root,
        args.packet,
        label="blind-review packet",
        kind="file",
    )
    output_path = confined_output_path(
        resolved_evidence_root,
        args.out,
        label="blind-review authoring output",
    )
    require_new_artifact_paths([output_path], root=resolved_evidence_root)
    packet = _object(packet_path, label="blind-review packet")
    config = _canonical_config(packet)
    if args.command == "template":
        reviewer = load_enrolled_blind_reviewer(
            config,
            reviewer_role=args.reviewer_role,
            repository_root=ROOT,
        )
        result = build_blind_review_authoring_template(packet, reviewer=reviewer)
        summary = {
            "status": "awaiting_human_review",
            "provider_calls": 0,
            "reviewer_role": reviewer.reviewer_role,
            "review_item_count": len(result["review"]["decisions"]),
            "artifact": output_path.relative_to(resolved_evidence_root).as_posix(),
            "corpus_gate_ready": False,
        }
    else:
        template_path = confined_path(
            resolved_evidence_root,
            args.template,
            label="completed blind-review template",
            kind="file",
        )
        completed_template = _object(
            template_path, label="completed blind-review template",
        )
        protocol = packet.get("review_protocol")
        reviewer_role = (
            protocol.get("reviewer_role") if isinstance(protocol, dict) else None
        )
        if not isinstance(reviewer_role, str):
            raise ValueError("blind-review packet reviewer_role is unavailable")
        reviewer = load_enrolled_blind_reviewer(
            config,
            reviewer_role=reviewer_role,
            repository_root=ROOT,
        )
        result, validation = author_signed_blind_review_ledger(
            packet,
            completed_template,
            reviewer=reviewer,
            private_key_path=args.private_key,
            repository_root=ROOT,
            evidence_root=resolved_evidence_root,
        )
        summary = {
            "status": "signed_and_verified",
            "provider_calls": 0,
            "reviewer_role": reviewer.reviewer_role,
            "review_item_count": len(result["decisions"]),
            "accepted_count": validation["accepted_count"],
            "artifact": output_path.relative_to(resolved_evidence_root).as_posix(),
            "corpus_gate_ready": False,
        }
    write_new_text_artifact(
        output_path,
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        root=resolved_evidence_root,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(retained_cli_entrypoint(main))

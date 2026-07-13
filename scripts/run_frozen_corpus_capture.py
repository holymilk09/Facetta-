#!/usr/bin/env python3
"""Produce a signed frozen-corpus capture from provider-free input bundles."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from facetta.frozen_capture_producer import (  # noqa: E402
    BundleCaptureExecutor,
    Ed25519PrivateKeySigner,
    FilePersistenceObservationRunner,
    FrozenCaptureProducer,
)
from facetta.frozen_evidence_paths import (  # noqa: E402
    confined_output_path,
    evidence_root as resolve_evidence_root,
)


DEFAULT_DIR = ROOT / "docs" / "evals" / "frozen-founder-corpus-v1"


def _configured_key_ids(config_path: Path) -> tuple[str, str]:
    config = json.loads(config_path.read_text())
    executor = config.get("executor_trust")
    api_runner = config.get("canonical_api_runner_public_key")
    executor_id = executor.get("key_id") if isinstance(executor, dict) else None
    api_id = api_runner.get("key_id") if isinstance(api_runner, dict) else None
    if not isinstance(executor_id, str) or not executor_id.strip():
        raise ValueError("config executor key is not enrolled")
    if not isinstance(api_id, str) or not api_id.strip():
        raise ValueError("config canonical API runner key is not enrolled")
    return executor_id, api_id


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create a locally revalidated signed capture. This CLI consumes "
            "existing bundles and never calls an image provider."
        ),
    )
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_DIR / "manifest.json")
    parser.add_argument("--config", type=Path, default=DEFAULT_DIR / "config.json")
    parser.add_argument("--workload", type=Path, default=DEFAULT_DIR / "workload.json")
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--execution-bundle", type=Path, required=True)
    parser.add_argument("--persistence-observations", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--executor-private-key", type=Path, required=True)
    parser.add_argument("--canonical-api-private-key", type=Path, required=True)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--attestation-id", required=True)
    parser.add_argument("--summary-out", type=Path)
    args = parser.parse_args()

    summary_path: Path | None = None
    try:
        resolved_evidence_root = resolve_evidence_root(args.evidence_root)
        if args.summary_out:
            requested_output_dir = confined_output_path(
                resolved_evidence_root,
                args.output_dir,
                label="capture output directory",
            )
            summary_path = confined_output_path(
                resolved_evidence_root,
                args.summary_out,
                label="capture summary output",
            )
            if summary_path == requested_output_dir or summary_path.is_relative_to(
                requested_output_dir
            ):
                raise ValueError(
                    "capture summary output must remain outside the atomic capture directory"
                )
            if summary_path.exists():
                raise ValueError("capture summary output already exists")
            if not summary_path.parent.is_dir():
                raise ValueError("capture summary output parent is unavailable")
        executor_id, api_id = _configured_key_ids(args.config)
        forbidden = (args.repository_root.resolve(), args.evidence_root.resolve())
        executor_signer = Ed25519PrivateKeySigner.from_file(
            args.executor_private_key,
            key_id=executor_id,
            forbidden_roots=forbidden,
        )
        api_signer = Ed25519PrivateKeySigner.from_file(
            args.canonical_api_private_key,
            key_id=api_id,
            forbidden_roots=forbidden,
        )
        runner = FrozenCaptureProducer(
            repository_root=args.repository_root,
            evidence_root=args.evidence_root,
            manifest_path=args.manifest,
            config_path=args.config,
            workload_path=args.workload,
            source_dir=args.source_dir,
            output_dir=args.output_dir,
            executor=BundleCaptureExecutor(args.execution_bundle),
            persistence_runner=FilePersistenceObservationRunner(
                args.persistence_observations,
                evidence_root=args.evidence_root.resolve(),
            ),
            executor_signer=executor_signer,
            api_signer=api_signer,
            commit_sha=args.commit_sha,
            attestation_id=args.attestation_id,
        )
        result = runner.produce()
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        result = {
            "schema_version": "facetta-frozen-capture-production.v1",
            "status": "fail",
            "provider_calls_executed": 0,
            "error": str(exc),
            "corpus_gate_ready": False,
        }
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if summary_path is not None:
        summary_path.write_text(rendered)
    print(rendered, end="")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())

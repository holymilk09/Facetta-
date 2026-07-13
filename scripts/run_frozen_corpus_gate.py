"""Compile or replay the provider-free frozen corpus release gate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from facetta.frozen_corpus_gate import compile_frozen_corpus_gate  # noqa: E402
from facetta.frozen_evidence_paths import (  # noqa: E402
    confined_output_path,
    evidence_root,
)


DEFAULT_MANIFEST = (
    ROOT / "docs" / "evals" / "frozen-founder-corpus-v1" / "manifest.json"
)
DEFAULT_CONFIG = (
    ROOT / "docs" / "evals" / "frozen-founder-corpus-v1" / "config.json"
)
DEFAULT_WORKLOAD = (
    ROOT / "docs" / "evals" / "frozen-founder-corpus-v1" / "workload.json"
)


def _report(result: dict[str, object]) -> str:
    definition = result["definition"]
    sources = result["source_integrity"]
    quality = result["quality"]
    assert isinstance(definition, dict)
    assert isinstance(sources, dict)
    assert isinstance(quality, dict)
    coverage = quality.get("source_coverage", {})
    classified = quality.get("classified_release_gates", {})
    assert isinstance(coverage, dict)
    assert isinstance(classified, dict)
    quick = classified.get("quick_appearance", {})
    structural = classified.get("structural", {})
    assert isinstance(quick, dict)
    assert isinstance(structural, dict)
    return "\n".join([
        "# Frozen founder corpus gate",
        "",
        f"- Overall: `{result['status']}`",
        f"- Corpus gate ready: `{result['corpus_gate_ready']}`",
        f"- Definition: `{definition['status']}`",
        f"- Workload: `{result['workload']['status']}` "
        f"(quality: `{result['workload']['quality_source_count']}`, "
        f"integrity: `{result['workload']['integrity_source_count']}`)",
        f"- Source integrity: `{sources['status']}` "
        f"({sources['verified']}/{sources['expected']})",
        f"- Image quality replay: `{quality['status']}`",
        "- Signed quality source coverage: "
        f"`{coverage.get('completed_source_count', 0)}/"
        f"{coverage.get('expected_source_count', sources['expected'])}`",
        "- Quick-appearance GIA visual-fidelity acceptance: "
        f"`{quick.get('gia_acceptance_rate', 'not_run')}` "
        f"(pass: `{quick.get('pass', False)}`)",
        "- Structural fidelity/drift class: "
        f"`{structural.get('pass', False)}`",
        "- Provider calls: `0`",
        "",
        "Source integrity is not image quality. An absent or incomplete replay, "
        "canonical persistence proof, or GIA-trained review fails closed. "
        "Founder approval is verified separately against these exact result bytes.",
        "",
    ])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--workload", type=Path, default=DEFAULT_WORKLOAD)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--gia-review-packet", type=Path)
    parser.add_argument("--gia-review-ledger", type=Path)
    parser.add_argument("--outdir", type=Path, required=True)
    args = parser.parse_args()
    resolved_evidence_root = evidence_root(args.evidence_root)
    output_dir = confined_output_path(
        resolved_evidence_root, args.outdir, label="gate output directory",
    )
    result = compile_frozen_corpus_gate(
        args.manifest, args.config, args.source_dir, args.evidence,
        workload_path=args.workload,
        evidence_root=resolved_evidence_root,
        review_packet_path=args.gia_review_packet,
        review_ledger_path=args.gia_review_ledger,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "results.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    (output_dir / "report.md").write_text(_report(result))
    print(json.dumps({
        "status": result["status"],
        "corpus_gate_ready": result["corpus_gate_ready"],
        "artifacts": output_dir.relative_to(resolved_evidence_root).as_posix(),
    }, indent=2))
    return 0 if result["corpus_gate_ready"] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())

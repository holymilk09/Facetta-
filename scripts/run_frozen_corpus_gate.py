"""Compile or replay the provider-free frozen corpus release gate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from facetta.frozen_corpus_gate import compile_frozen_corpus_gate  # noqa: E402


DEFAULT_MANIFEST = (
    ROOT / "docs" / "evals" / "frozen-founder-corpus-v1" / "manifest.json"
)
DEFAULT_CONFIG = (
    ROOT / "docs" / "evals" / "frozen-founder-corpus-v1" / "config.json"
)


def _report(result: dict[str, object]) -> str:
    definition = result["definition"]
    sources = result["source_integrity"]
    quality = result["quality"]
    assert isinstance(definition, dict)
    assert isinstance(sources, dict)
    assert isinstance(quality, dict)
    coverage = quality.get("source_coverage", {})
    assert isinstance(coverage, dict)
    return "\n".join([
        "# Frozen founder corpus gate",
        "",
        f"- Overall: `{result['status']}`",
        f"- Release ready: `{result['release_ready']}`",
        f"- Definition: `{definition['status']}`",
        f"- Source integrity: `{sources['status']}` "
        f"({sources['verified']}/{sources['expected']})",
        f"- Image quality replay: `{quality['status']}`",
        "- Signed quality source coverage: "
        f"`{coverage.get('completed_source_count', 0)}/"
        f"{coverage.get('expected_source_count', sources['expected'])}`",
        "- Provider calls: `0`",
        "",
        "Source integrity is not image quality. An absent or incomplete replay, "
        "canonical persistence proof, or GIA-trained review fails closed.",
        "",
    ])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--outdir", type=Path, required=True)
    args = parser.parse_args()
    result = compile_frozen_corpus_gate(
        args.manifest, args.config, args.source_dir, args.evidence,
    )
    args.outdir.mkdir(parents=True, exist_ok=True)
    (args.outdir / "results.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    (args.outdir / "report.md").write_text(_report(result))
    print(json.dumps({
        "status": result["status"],
        "release_ready": result["release_ready"],
        "artifacts": str(args.outdir),
    }, indent=2))
    return 0 if result["release_ready"] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())

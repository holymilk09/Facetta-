"""Run six provider-free probes against the canonical drawing contract."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from facetta.drawing_quality_matrix import (  # noqa: E402
    load_inventory_evidence,
    run_contract_matrix,
)


DEFAULT_PREFLIGHT = (
    ROOT / "docs" / "evals" /
    "designer-reference-all-144-preflight-2026-07-11" / "results.json"
)
DEFAULT_INVENTORY = (
    ROOT / "docs" / "evals" /
    "designer-reference-inventory-live-2026-07-11" / "results.json"
)
DEFAULT_OUTDIR = (
    ROOT / "docs" / "evals" / "drawing-quality-contract-matrix-v1"
)


def _report(result: dict[str, object]) -> str:
    summary = result["summary"]
    assert isinstance(summary, dict)
    fixtures = result["fixtures"]
    assert isinstance(fixtures, list)
    lines = [
        "# Canonical Drawing Contract Matrix v1",
        "",
        "This internal, provider-free contract test made **0 provider calls**, "
        "generated **0 images**, live-evaluated **0 images**, and classified "
        "**0 user sources**.",
        "",
        "All fixture policy comes from "
        "`facetta.drawing_intake.build_drawing_processing_contract`. Fixture "
        "IDs and evidence signals are internal test data and never product "
        "labels or provider judgments.",
        "",
        "## Result",
        "",
        f"- Fixtures: {summary['fixture_count']}",
        f"- Passing contracts: {summary['contract_pass_count']}",
        f"- All contracts pass: {summary['all_contracts_pass']}",
        f"- Distinct render strategies: "
        f"{summary['distinct_render_strategy_count']}",
        "- Uniform render strategy: `faithful_best_effort`",
        "- Factory truth from provider output: prohibited",
        "",
        "## Internal matrix",
        "",
        "| Fixture | Render strategy | Dimension evidence | Signals | Visual attempt |",
        "|---|---|---|---:|---|",
    ]
    for row in fixtures:
        assert isinstance(row, dict)
        facts = row["intake_facts"]
        contract = row["processing_contract"]
        assert isinstance(facts, dict) and isinstance(contract, dict)
        policy = contract["policy"]
        assert isinstance(policy, dict)
        signals = facts["internal_signals"]
        assert isinstance(signals, list)
        lines.append(
            f"| `{row['fixture_id']}` | `{policy['render_strategy']}` | "
            f"`{facts['dimension_evidence']}` | {len(signals)} | required |"
        )
    lines.extend([
        "",
        "Every fixture passes the same four contract dimensions: fidelity, "
        "best-result usefulness, uncertainty capture, and factory-truth "
        "non-promotion. Evidence changes factory questions or dimension handling; "
        "it never changes or pre-blocks the visual attempt.",
        "",
        "## Evidence boundary",
        "",
        "The founder corpus contains 144 decodable inventoried files. One "
        "existing inventory entry anchors each fixture to an advisory taxonomy "
        "and hash. Neither the 144 files nor the six linked files were "
        "pixel-inspected or live-tested by this harness.",
        "",
        "A pass proves canonical contract consistency only. It does not prove "
        "provider image quality, geometry fidelity, or factory readiness. Those "
        "remain separate live, designer-reviewed release gates.",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight", type=Path, default=DEFAULT_PREFLIGHT)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR)
    args = parser.parse_args()

    evidence = load_inventory_evidence(args.preflight, args.inventory)
    result = run_contract_matrix(evidence)
    args.outdir.mkdir(parents=True, exist_ok=True)
    (args.outdir / "results.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    (args.outdir / "report.md").write_text(_report(result))
    print(json.dumps(result["summary"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

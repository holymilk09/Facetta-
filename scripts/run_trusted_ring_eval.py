"""Run the Grok-primary trusted-ring release evaluation.

Usage:
    PYTHONPATH=src uv run python scripts/run_trusted_ring_eval.py RUN_NAME
    PYTHONPATH=src uv run python scripts/run_trusted_ring_eval.py RUN_NAME --preflight
    PYTHONPATH=src uv run python scripts/run_trusted_ring_eval.py RUN_NAME \
        --persistence-evidence path/to/canonical-api-result.json

Preflight validates and records the complete matrix without provider calls.
Live mode requires XAI_KEY plus either FAL_KEY or OPENAI_API_KEY and writes
images plus scored evidence to ``docs/evals/RUN_NAME``. ``--grok-only`` is an explicit diagnostic
mode for measuring Grok without claiming fallback reliability was tested.
Results do not become blocking until the GIA-trained
cofounder records the evaluator false-positive/false-negative review.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from facetta.config import load_env_file  # noqa: E402
from facetta.evals import score_edit_fidelity, score_spec_conformance  # noqa: E402
from facetta.image_agent import (  # noqa: E402
    ImageAgentError,
    ImageOperation,
    JewelryImageAgent,
    build_image_plan,
)
from facetta.image_agent.providers import (  # noqa: E402
    configured_fallback_provider,
)
from facetta.ring_evals import (  # noqa: E402
    CANONICAL_RING_EDITS,
    RING_GOLDEN_CASES,
    apply_canonical_ring_edit,
    build_ring_golden_spec,
    evaluate_release_gates,
)


UNVERIFIED_PERSISTENCE_EVIDENCE = {
    "verified": False,
    "method": "not_run",
    "result_set": None,
    "rejected_active_asset_count": None,
    "note": (
        "This image-engine run did not exercise canonical project persistence. "
        "Attach a named canonical-API integration result before the persistence "
        "release gate can pass."
    ),
}


def _json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _load_persistence_evidence(path: Path | None) -> dict[str, object]:
    """Load explicit API evidence; absence must never masquerade as success."""
    if path is None:
        return dict(UNVERIFIED_PERSISTENCE_EVIDENCE)
    try:
        value: object = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"could not read persistence evidence: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit("persistence evidence must be a JSON object")
    required = {
        "verified", "method", "result_set", "rejected_active_asset_count"}
    missing = sorted(required - value.keys())
    if missing:
        raise SystemExit(
            "persistence evidence is missing: " + ", ".join(missing))
    rejected_count = value["rejected_active_asset_count"]
    if (value["verified"] is not True
            or not isinstance(value["method"], str)
            or not value["method"].strip()
            or not isinstance(value["result_set"], str)
            or not value["result_set"].strip()
            or type(rejected_count) is not int
            or rejected_count < 0):
        raise SystemExit(
            "verified persistence evidence requires a method, named result_set, "
            "and a non-negative rejected_active_asset_count")
    return value


def _preflight(outdir: Path, run_name: str) -> None:
    cases = []
    for case in RING_GOLDEN_CASES:
        spec = build_ring_golden_spec(case)
        cases.append({
            **asdict(case),
            "reference_required": case.requires_reference,
            "live_reference_strategy": (
                "generated_spec_aligned_fixture"
                if case.requires_reference else None),
            "spec": spec.model_dump(mode="json"),
            "halo_count": spec.side_stones[0].count if spec.side_stones else 0,
        })
    edit_checks = []
    cases_by_id = {case.id: case for case in RING_GOLDEN_CASES}
    for edit in CANONICAL_RING_EDITS:
        case = cases_by_id[edit.golden_case_id]
        base_spec = build_ring_golden_spec(case)
        updated, issues = apply_canonical_ring_edit(base_spec, edit)
        edit_checks.append({
            **asdict(edit),
            "starting_point": case.starting_point,
            "validation_passed": updated is not None,
            "issues": issues,
        })
    result = {
        "run": run_name,
        "mode": "preflight",
        "live": False,
        "cases": cases,
        "canonical_edits": edit_checks,
        "provider_readiness": {
            "xai_configured": bool(os.getenv("XAI_KEY")),
            "fallback_configured": configured_fallback_provider() is not None,
            "fallback_provider": configured_fallback_provider(),
        },
        "persistence_evidence": dict(UNVERIFIED_PERSISTENCE_EVIDENCE),
        "release_gates": {
            "status": "not_evaluated",
            "blocking_enabled": False,
            "blocking_note": (
                "Run live with both providers, then complete GIA-trained "
                "cofounder evaluator review."),
        },
    }
    _json(outdir / "results.json", result)
    (outdir / "report.md").write_text(
        f"# Trusted ring evaluation — {run_name}\n\n"
        "Preflight completed: the ring matrix and canonical edits validate. "
        "No provider calls were made, so reliability gates are not evaluated.\n"
    )


def _live(
    outdir: Path,
    run_name: str,
    persistence_evidence: dict[str, object],
    *,
    grok_only: bool = False,
    only_edit: str | None = None,
    edit_source: Path | None = None,
) -> None:
    missing = ["XAI_KEY"] if not os.getenv("XAI_KEY") else []
    fallback_provider = configured_fallback_provider()
    if not grok_only and fallback_provider is None:
        missing.append("FAL_KEY or OPENAI_API_KEY")
    if missing:
        raise SystemExit(
            "live trusted-ring evaluation requires configured provider keys: "
            + ", ".join(missing))
    agent = JewelryImageAgent()
    rows: list[dict] = []
    sources: dict[str, bytes] = {}
    specs = {case.id: build_ring_golden_spec(case)
             for case in RING_GOLDEN_CASES}
    selected_edits = [
        edit for edit in CANONICAL_RING_EDITS
        if only_edit is None or edit.id == only_edit
    ]
    cases_by_id = {case.id: case for case in RING_GOLDEN_CASES}
    source_override: dict[str, object] | None = None
    if edit_source is not None:
        if only_edit is None or len(selected_edits) != 1:
            raise SystemExit("--edit-source requires exactly one --only-edit case")
        try:
            source_bytes = edit_source.read_bytes()
            Image.open(io.BytesIO(source_bytes)).verify()
        except (OSError, ValueError) as exc:
            raise SystemExit(f"could not read edit source image: {exc}") from exc
        edit = selected_edits[0]
        sources[edit.golden_case_id] = source_bytes
        source_override = {
            "path": str(edit_source.resolve()),
            "sha256": hashlib.sha256(source_bytes).hexdigest(),
            "golden_case": edit.golden_case_id,
            "scope": "single_edit_diagnostic_only",
            "provenance": (
                "operator-selected, previously reviewed spec-aligned source; "
                "not re-generated or re-audited by this result set"
            ),
        }
        rows.append({
            "kind": "source",
            "case": edit.golden_case_id,
            "starting_point": cases_by_id[edit.golden_case_id].starting_point,
            "source_override": source_override,
        })
    required_case_ids = (
        {edit.golden_case_id for edit in selected_edits}
        if only_edit is not None else
        {case.id for case in RING_GOLDEN_CASES}
    )

    for case in RING_GOLDEN_CASES:
        if case.id not in required_case_ids:
            continue
        if case.id in sources:
            continue
        spec = specs[case.id]
        reference: bytes | None = None
        reference_attempts = 0
        if case.requires_reference:
            # Build a known spec-aligned fixture, then exercise the actual
            # reference-backed SPEC_RENDER route with those bytes. The evidence
            # names the fixture honestly; it is not presented as a user upload.
            reference_plan = build_image_plan(
                ImageOperation.SPEC_RENDER,
                f"spec-aligned source fixture for reference-backed case {case.id}",
                spec=spec,
                allow_fallback=not grok_only,
            )
            try:
                reference_result = agent.run(reference_plan)
            except ImageAgentError as exc:
                rows.append({
                    "kind": "render", "case": case.id,
                    "starting_point": case.starting_point,
                    "reference_required": True,
                    "reference_supplied": False,
                    "reference_stage_error": exc.category.value,
                    "reference_attempts": len(exc.attempts),
                    "score": 0, "hard_gate_pass": False, "attempts": 0,
                    "agent_error": exc.as_dict(),
                })
                continue
            reference_attempts = len(reference_result.run.attempts)
            if not reference_result.accepted:
                reference_name = f"{case.id}--reference-warning.png"
                (outdir / reference_name).write_bytes(
                    reference_result.image_bytes)
                rows.append({
                    "kind": "render", "case": case.id,
                    "starting_point": case.starting_point,
                    "reference_required": True,
                    "reference_supplied": False,
                    "reference_stage_error": "reference_requires_review",
                    "reference_attempts": reference_attempts,
                    "score": 0, "hard_gate_pass": False, "attempts": 0,
                    "reference_warning_image": reference_name,
                    "quality": reference_result.quality.model_dump(mode="json"),
                    "agent_run": reference_result.run.model_dump(mode="json"),
                })
                continue
            reference = reference_result.image_bytes
            (outdir / f"{case.id}--reference.png").write_bytes(reference)
            # An imported-reference project starts revision 1 from the
            # designer-confirmed reference itself. Keep that valid source
            # available for edit diagnostics even if a separate, optional
            # reference-backed spec render fails QA.
            sources[case.id] = reference

        if case.requires_reference and reference is None:
            raise RuntimeError(
                f"reference-backed case '{case.id}' has no source image")
        plan = build_image_plan(
            ImageOperation.SPEC_RENDER,
            f"trusted golden render: {case.id}",
            spec=spec,
            source_image=reference,
            allow_fallback=not grok_only,
        )
        try:
            result = agent.run(plan, source_image=reference)
            scored = score_spec_conformance(spec, result.image_bytes)
            candidate_name = (f"{case.id}.png" if result.accepted
                              else f"{case.id}--warning.png")
            (outdir / candidate_name).write_bytes(result.image_bytes)
            if result.accepted:
                sources[case.id] = result.image_bytes
            rows.append({
                "kind": "render", "case": case.id,
                "starting_point": case.starting_point,
                "reference_required": case.requires_reference,
                "reference_supplied": reference is not None,
                "reference_origin": (
                    "generated_spec_aligned_fixture"
                    if reference is not None else None),
                "reference_attempts": reference_attempts,
                "score": scored["score"],
                "hard_gate_pass": result.accepted,
                "attempts": len(result.run.attempts),
                "verdict": result.quality.verdict.value,
                "failed_checks": [check.code
                                  for check in result.quality.failed_checks],
                "quality": result.quality.model_dump(mode="json"),
                "agent_run": result.run.model_dump(mode="json"),
            })
        except ImageAgentError as exc:
            rows.append({
                "kind": "render", "case": case.id, "score": 0,
                "starting_point": case.starting_point,
                "reference_required": case.requires_reference,
                "reference_supplied": reference is not None,
                "reference_origin": (
                    "generated_spec_aligned_fixture"
                    if reference is not None else None),
                "reference_attempts": reference_attempts,
                "hard_gate_pass": False, "attempts": len(exc.attempts),
                "error_category": exc.category.value,
                "agent_error": exc.as_dict(),
            })

    for edit in selected_edits:
        golden_case = cases_by_id[edit.golden_case_id]
        base_spec = specs[golden_case.id]
        updated, issues = apply_canonical_ring_edit(base_spec, edit)
        if not edit.expected_valid:
            rows.append({
                "kind": "validation", "case": edit.id,
                "golden_case": golden_case.id,
                "starting_point": golden_case.starting_point,
                "rejected_before_provider": updated is None,
                "issues": issues,
            })
            continue
        source = sources.get(golden_case.id)
        if updated is None or source is None:
            rows.append({
                "kind": "edit", "case": edit.id,
                "golden_case": golden_case.id,
                "starting_point": golden_case.starting_point,
                "score": 0, "applied": False, "attempts": 0,
                "severity": "major", "expected_valid": True,
                "precondition_error": (
                    "spec_edit_invalid" if updated is None
                    else "no_accepted_case_render"),
                "issues": issues,
            })
            continue
        operation = (ImageOperation.VISUAL_ONLY_EDIT if edit.visual_only
                     else ImageOperation.LOCAL_EDIT)
        plan = build_image_plan(
            operation,
            edit.instruction,
            spec=updated,
            source_spec=(None if edit.visual_only else base_spec),
            source_image=source,
            region_description=(None if edit.visual_only else edit.region),
            frozen=edit.frozen_facts,
            allow_fallback=not grok_only,
        )
        try:
            result = agent.run(plan, source_image=source)
            score = score_edit_fidelity(
                source, result.image_bytes, edit.instruction)
            candidate_name = (f"edit-{edit.id}.png" if result.accepted
                              else f"edit-{edit.id}--warning.png")
            (outdir / candidate_name).write_bytes(result.image_bytes)
            rows.append({
                "kind": "edit", "case": edit.id,
                "golden_case": golden_case.id,
                "starting_point": golden_case.starting_point,
                "score": score["score"],
                "applied": result.accepted and score["change_applied"],
                "change_visible": bool(score["change_applied"]),
                "review_required": result.review_required,
                "eligible_after_designer_review": (
                    result.review_required
                    and bool(score["change_applied"])
                    and score["severity"] != "major"
                ),
                "attempts": len(result.run.attempts),
                "severity": score["severity"],
                "expected_valid": True,
                "verdict": result.quality.verdict.value,
                "quality": result.quality.model_dump(mode="json"),
                "agent_run": result.run.model_dump(mode="json"),
                "fidelity_evidence": score,
            })
        except ImageAgentError as exc:
            rows.append({
                "kind": "edit", "case": edit.id,
                "golden_case": golden_case.id,
                "starting_point": golden_case.starting_point,
                "score": 0, "applied": False,
                "attempts": len(exc.attempts),
                "severity": "major", "expected_valid": True,
                "error_category": exc.category.value,
                "agent_error": exc.as_dict(),
            })

    result = {
        "run": run_name,
        "mode": "live",
        "live": True,
        "rows": rows,
        "persistence_evidence": persistence_evidence,
        "routing_mode": (
            "grok_only" if grok_only
            else f"grok_then_{fallback_provider}"
        ),
        "fallback_provider": None if grok_only else fallback_provider,
        "source_override": source_override,
        "fallback_tested": not grok_only,
        "release_gates": (
            evaluate_release_gates(
                rows, persistence_evidence=persistence_evidence)
            if only_edit is None else {
                "status": "diagnostic_subset_not_evaluated",
                "blocking_enabled": False,
                "note": f"Only canonical edit '{only_edit}' was executed.",
            }
        ),
        "gia_evaluator_review": {
            "completed": False,
            "reviewer": None,
            "false_positives": None,
            "false_negatives": None,
        },
    }
    _json(outdir / "results.json", result)
    (outdir / "report.md").write_text(
        f"# Trusted ring evaluation — {run_name}\n\n"
        f"Rows: {len(rows)}\n\n"
        "See `results.json` for attempt evidence and release-gate status. "
        "Gates remain non-blocking until GIA evaluator review is complete.\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_name")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument(
        "--persistence-evidence",
        type=Path,
        help=("JSON evidence from a named canonical project-API integration run; "
              "without it, persistence safety fails closed"),
    )
    parser.add_argument(
        "--edit-source",
        type=Path,
        help=(
            "reuse one existing, operator-reviewed source image for a focused "
            "--only-edit diagnostic; the source hash is recorded and full "
            "release gates remain unevaluated"
        ),
    )
    parser.add_argument(
        "--grok-only", action="store_true",
        help=("run two Grok attempts without requiring FAL_KEY; fallback "
              "reliability gates remain failed because fallback was not tested"),
    )
    parser.add_argument(
        "--only-edit",
        choices=[edit.id for edit in CANONICAL_RING_EDITS],
        help=(
            "run one canonical edit and only its required source case; this is "
            "diagnostic evidence and never evaluates the full release gates"
        ),
    )
    args = parser.parse_args()
    load_env_file()
    outdir = ROOT / "docs" / "evals" / args.run_name
    outdir.mkdir(parents=True, exist_ok=False)
    if args.preflight:
        _preflight(outdir, args.run_name)
    else:
        _live(
            outdir,
            args.run_name,
            _load_persistence_evidence(args.persistence_evidence),
            grok_only=args.grok_only,
            only_edit=args.only_edit,
            edit_source=args.edit_source,
        )
    print(outdir)


if __name__ == "__main__":
    main()

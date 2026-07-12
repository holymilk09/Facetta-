"""Preflight and live-read the founder-supplied designer reference corpus."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from facetta.config import load_env_file  # noqa: E402
from facetta.designer_evals import (  # noqa: E402
    DesignerReferenceCase,
    inspect_source,
    load_corpus,
    score_paired_reads,
    score_plate_read,
    summarize_source_coverage,
)
from facetta.estimate import physics_check_estimates  # noqa: E402
from facetta.image_identity import spec_visual_hash  # noqa: E402
from facetta.plate_spec import compile_plate_spec  # noqa: E402
from facetta.source_component_audit import (  # noqa: E402
    SourceComponentAuditError,
    SourceComponentAuditInvalid,
    audit_source_component_coverage,
)
from facetta.source_component_coverage import (  # noqa: E402
    source_component_factory_blockers,
)
from facetta.specagent import read_design_plate  # noqa: E402
from facetta.vocabulary import get_vocabulary  # noqa: E402


DEFAULT_MANIFEST = (
    ROOT / "docs" / "evals" / "designer-reference-corpus-v1" /
    "manifest.json"
)
DEFAULT_SOURCE_DIR = Path(
    "/Users/mattfb/.codex/attachments/"
    "c2fd41d0-b236-43ef-ada9-e9479718c771"
)


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _selected(
    cases: tuple[DesignerReferenceCase, ...], ids: list[str],
) -> list[DesignerReferenceCase]:
    if not ids:
        return list(cases)
    wanted = set(ids)
    selected = [case for case in cases if case.id in wanted]
    missing = sorted(wanted - {case.id for case in selected})
    if missing:
        raise SystemExit("unknown case ids: " + ", ".join(missing))
    return selected


def _audit_with_product_contract_retry(
    source: bytes,
    coverage,
    *,
    spec,
):
    """Mirror the trusted API's one retry for malformed audit JSON only."""

    try:
        return audit_source_component_coverage(
            source,
            coverage,
            spec=spec,
        )
    except SourceComponentAuditInvalid:
        return audit_source_component_coverage(
            source,
            coverage,
            spec=spec,
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_name")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--stage", choices=("preflight", "read", "coverage"),
                        default="preflight")
    args = parser.parse_args()

    load_env_file()
    corpus = load_corpus(args.manifest)
    cases = _selected(corpus.cases, args.case)
    outdir = ROOT / "docs" / "evals" / args.run_name
    outdir.mkdir(parents=True, exist_ok=True)
    rows = []

    if args.stage in {"read", "coverage"} and not os.getenv("XAI_KEY"):
        raise SystemExit("live plate reads/audits require XAI_KEY")

    for case in cases:
        source_info = inspect_source(case, args.source_dir)
        row = {
            "case": case.id,
            "category": case.category,
            "input_kind": case.input_kind,
            "workflows": list(case.workflows),
            "source": source_info,
        }
        if args.stage in {"read", "coverage"}:
            if not source_info.get("hash_matches"):
                row["read_error"] = "source unavailable or hash mismatch"
            elif "plate_read" not in case.workflows:
                row["read_status"] = "not_applicable"
            else:
                started = time.perf_counter()
                try:
                    raw_read = read_design_plate(
                        (args.source_dir / case.source_filename).read_bytes())
                    read = physics_check_estimates(
                        get_vocabulary(), raw_read)
                    row["read"] = read
                    row["read_score"] = score_plate_read(case, read)
                    if args.stage == "coverage":
                        if case.category not in {"ring", "necklace"}:
                            row["coverage_status"] = (
                                "not_applicable_supported_categories")
                        else:
                            spec, uncertainties = compile_plate_spec(
                                raw_read,
                                created_by="eval_designer",
                                design_id=f"eval_{case.id}",
                                source_asset_id=f"eval:{case.id}",
                                source_asset_sha256=case.sha256,
                            )
                            coverage = spec.source_component_coverage
                            if coverage is None:
                                raise ValueError(
                                    "plate compiler returned no coverage")
                            row["draft_spec"] = spec.model_dump(mode="json")
                            row["uncertainties"] = uncertainties
                            try:
                                audited = _audit_with_product_contract_retry(
                                    (args.source_dir / case.source_filename)
                                    .read_bytes(),
                                    coverage,
                                    spec=spec,
                                )
                            except SourceComponentAuditError as exc:
                                # The source read is still valid evidence. An
                                # invalid or unavailable independent pass must
                                # stay a distinct, factory-blocking outcome so
                                # aggregate read metrics cannot hide it.
                                audited = coverage
                                row["coverage_status"] = (
                                    "invalid" if isinstance(
                                        exc, SourceComponentAuditInvalid)
                                    else "unavailable"
                                )
                                row["coverage_error"] = str(exc)
                                if (
                                    isinstance(exc, SourceComponentAuditInvalid)
                                    and exc.debug_evidence is not None
                                ):
                                    # Local evaluation evidence only: source
                                    # bytes are never retained, while both raw
                                    # audit mappings survive validator failure.
                                    row["coverage_audit_debug"] = (
                                        exc.debug_evidence
                                    )
                            blockers = source_component_factory_blockers(
                                audited,
                                current_spec_visual_hash=spec_visual_hash(spec),
                            )
                            if "coverage_status" not in row:
                                row["coverage_status"] = (
                                    "pass" if not blockers
                                    else "review_required")
                            row["source_component_coverage"] = (
                                audited.model_dump(mode="json"))
                            row["coverage_blockers"] = [
                                blocker.model_dump(mode="json")
                                for blocker in blockers
                            ]
                except Exception as exc:
                    row["read_error"] = str(exc)
                row["latency_ms"] = round(
                    (time.perf_counter() - started) * 1000)
        rows.append(row)

    read_rows = {
        row["case"]: row["read"]
        for row in rows if isinstance(row.get("read"), dict)
    }
    pair_checks = []
    for case in cases:
        if (case.paired_case_id and case.id in read_rows
                and case.paired_case_id in read_rows):
            pair_checks.append({
                "base_case": case.paired_case_id,
                "variant_case": case.id,
                "expected_change": "material/species only; geometry frozen",
                "result": score_paired_reads(
                    read_rows[case.paired_case_id], read_rows[case.id]),
            })

    result = {
        "run": args.run_name,
        "stage": args.stage,
        "corpus": corpus.name,
        "source_policy": corpus.source_policy,
        "provider_readiness": {
            "xai_configured": bool(os.getenv("XAI_KEY")),
            "fallback_configured": bool(os.getenv("FAL_KEY")),
        },
        "rows": rows,
        "pair_checks": pair_checks,
    }
    if args.stage == "coverage":
        result["coverage_summary"] = summarize_source_coverage(rows)
    _write_json(outdir / "results.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

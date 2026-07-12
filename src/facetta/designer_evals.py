"""Typed corpus and scoring helpers for designer-reference evaluations."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from facetta.json_types import JsonObject


class DesignerReferenceCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    source_filename: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    category: str
    input_kind: str
    workflows: tuple[str, ...]
    expected_jewelry_type: str
    expected_terms_any: tuple[str, ...] = ()
    expected_min_stone_groups: int = Field(default=0, ge=0)
    authoritative_text_any: tuple[str, ...] = ()
    paired_case_id: str | None = None
    multi_design: bool = False
    notes: str = ""


class DesignerReferenceCorpus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    source_policy: str
    cases: tuple[DesignerReferenceCase, ...]


def load_corpus(path: Path) -> DesignerReferenceCorpus:
    return DesignerReferenceCorpus.model_validate_json(path.read_text())


def inspect_source(case: DesignerReferenceCase, source_dir: Path) -> JsonObject:
    source = source_dir / case.source_filename
    if not source.is_file():
        return {"available": False, "path": str(source)}
    content = source.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    try:
        with Image.open(source) as image:
            size = [image.width, image.height]
            media_format = image.format
    except Exception as exc:
        return {
            "available": True,
            "sha256": digest,
            "hash_matches": digest == case.sha256,
            "decodable": False,
            "error": str(exc),
        }
    return {
        "available": True,
        "path": str(source),
        "sha256": digest,
        "hash_matches": digest == case.sha256,
        "decodable": True,
        "size": size,
        "format": media_format,
    }


def score_plate_read(
    case: DesignerReferenceCase,
    read: JsonObject,
) -> JsonObject:
    """Score identity/OCR coverage without pretending estimates are truth."""
    serialized = json.dumps(read, sort_keys=True).lower()
    observed_type = str(read.get("jewelry_type") or "").lower()
    type_ok = observed_type == case.expected_jewelry_type.lower()
    term_hits = [
        term for term in case.expected_terms_any
        if term.lower() in serialized
    ]
    terms_ok = not case.expected_terms_any or bool(term_hits)
    stones = read.get("stones")
    stone_count = len(stones) if isinstance(stones, list) else 0
    stone_groups_ok = stone_count >= case.expected_min_stone_groups
    hand = read.get("hand_written")
    hand_text = " ".join(str(item) for item in hand).lower() \
        if isinstance(hand, list) else ""
    transcription_hits = [
        token for token in case.authoritative_text_any
        if token.lower() in hand_text
    ]
    transcription_ok = (
        not case.authoritative_text_any or bool(transcription_hits))
    checks = {
        "jewelry_type": type_ok,
        "expected_visual_terms": terms_ok,
        "minimum_stone_groups": stone_groups_ok,
        "authoritative_text": transcription_ok,
    }
    score = round(100 * sum(checks.values()) / len(checks), 1)
    return {
        "score": score,
        "status": "pass" if all(checks.values()) else "review_required",
        "checks": checks,
        "observed_jewelry_type": observed_type or None,
        "term_hits": term_hits,
        "stone_group_count": stone_count,
        "transcription_hits": transcription_hits,
        "multi_design_warning": case.multi_design,
    }


_CUT_TERMS = (
    "round", "oval", "emerald cut", "princess", "cushion", "marquise",
    "pear", "heart", "radiant", "baguette", "cabochon",
)


def _center_cut(read: JsonObject) -> str | None:
    stones = read.get("stones")
    if not isinstance(stones, list) or not stones:
        return None
    first = stones[0]
    text = str(first.get("type") if isinstance(first, dict) else "").lower()
    return next((term for term in _CUT_TERMS if term in text), None)


def score_paired_reads(base: JsonObject, variant: JsonObject) -> JsonObject:
    """Check geometry facts that must survive a material-only variant."""
    base_stones = base.get("stones") if isinstance(base.get("stones"), list) else []
    variant_stones = (variant.get("stones")
                      if isinstance(variant.get("stones"), list) else [])
    base_measurements = {
        str(item.get("value")) for item in base.get("measurements", [])
        if isinstance(item, dict) and item.get("value")
    }
    variant_measurements = {
        str(item.get("value")) for item in variant.get("measurements", [])
        if isinstance(item, dict) and item.get("value")
    }
    union = base_measurements | variant_measurements
    measurement_overlap = (
        len(base_measurements & variant_measurements) / len(union)
        if union else 1.0
    )
    checks = {
        "jewelry_type_stable": base.get("jewelry_type") == variant.get("jewelry_type"),
        "center_cut_stable": _center_cut(base) == _center_cut(variant),
        "stone_group_count_stable": len(base_stones) == len(variant_stones),
        "measurement_overlap": measurement_overlap >= 0.5,
    }
    return {
        "status": "pass" if all(checks.values()) else "fail",
        "checks": checks,
        "base_center_cut": _center_cut(base),
        "variant_center_cut": _center_cut(variant),
        "base_stone_group_count": len(base_stones),
        "variant_stone_group_count": len(variant_stones),
        "measurement_overlap": round(measurement_overlap, 3),
    }


def summarize_source_coverage(rows: list[JsonObject]) -> JsonObject:
    """Aggregate the factory-truth gate separately from semantic read score.

    A plate can score perfectly on broad recognition while still omitting a
    halo, shoulder group, setting detail, or other build-critical component.
    This summary intentionally counts only explicit independent-audit states;
    it never promotes the broad read score into manufacturing readiness.
    """

    applicable: list[JsonObject] = []
    for row in rows:
        status = row.get("coverage_status")
        if not isinstance(status, str) or status.startswith("not_applicable"):
            continue
        applicable.append(row)

    statuses = ("pass", "review_required", "invalid", "unavailable")
    counts = {
        status: sum(row.get("coverage_status") == status for row in applicable)
        for status in statuses
    }
    unexpected = sum(
        row.get("coverage_status") not in statuses for row in applicable
    )
    if unexpected:
        counts["unexpected"] = unexpected

    total = len(applicable)
    passed = counts["pass"]
    blocking_cases: list[JsonObject] = []
    for row in applicable:
        if row.get("coverage_status") == "pass":
            continue
        blockers = row.get("coverage_blockers")
        blocker_count = len(blockers) if isinstance(blockers, list) else 0
        blocking_cases.append({
            "case": str(row.get("case") or "unknown"),
            "status": str(row.get("coverage_status") or "unknown"),
            "blocker_count": blocker_count,
        })

    return {
        "applicable_cases": total,
        "factory_ready_cases": passed,
        "factory_ready_rate": round(100 * passed / total, 1) if total else None,
        "all_factory_ready": bool(total) and passed == total,
        "status_counts": counts,
        "blocking_cases": blocking_cases,
        "gate_definition": (
            "Factory ready only when every visible source component is mapped "
            "and independently audited with no blockers."
        ),
    }

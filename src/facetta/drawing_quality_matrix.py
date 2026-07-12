"""Provider-free fixtures for the canonical drawing-intake contract.

The six fixtures span source conditions that matter to internal evaluation.
They are never product labels, drawing scores, or provider instructions.  Each
fixture delegates policy construction to
``facetta.drawing_intake.build_drawing_processing_contract`` and must produce
the same ``faithful_best_effort`` visual strategy.  Only factual internal
evidence and dimension provenance vary.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from facetta.drawing_intake import (
    DrawingIntakeFacts,
    DrawingProcessingContract,
    InternalDrawingEvidenceSignal,
    build_drawing_processing_contract,
)


@dataclass(frozen=True)
class InventoryExample:
    filename: str
    allowed_input_kinds: tuple[str, ...]
    relevance: str


@dataclass(frozen=True)
class DrawingQualityFixture:
    """An internal condition probe, never a user-facing classification."""

    fixture_id: str
    coverage_intent: str
    intake_facts: DrawingIntakeFacts
    inventory_example: InventoryExample


def _signal(
    code: str,
    subject: str,
    detail: str,
) -> InternalDrawingEvidenceSignal:
    return InternalDrawingEvidenceSignal.model_validate({
        "code": code,
        "subject": subject,
        "detail": detail,
    })


MATRIX_FIXTURES: tuple[DrawingQualityFixture, ...] = (
    DrawingQualityFixture(
        fixture_id="phone-capture-visibility-loss",
        coverage_intent=(
            "Phone capture with perspective, glare, and cropping that obscure "
            "specific supplied marks."
        ),
        intake_facts=DrawingIntakeFacts(
            dimension_evidence="absent",
            internal_signals=(
                _signal(
                    "geometry_ambiguous",
                    "contours behind capture glare",
                    "A capture reflection overlaps two supplied contour segments.",
                ),
                _signal(
                    "geometry_not_visible",
                    "cropped lower design region",
                    "The source frame ends before the lower design region is shown.",
                ),
            ),
        ),
        inventory_example=InventoryExample(
            filename="image-61.jpg",
            allowed_input_kinds=("mixed",),
            relevance=(
                "Inventory note identifies a photographed design card. Capture "
                "artifacts in this fixture remain contract evidence, not a claim "
                "that this inventoried image was live-evaluated."
            ),
        ),
    ),
    DrawingQualityFixture(
        fixture_id="open-ideation-lines",
        coverage_intent=(
            "Early ideation source with open contours and unresolved construction "
            "marks."
        ),
        intake_facts=DrawingIntakeFacts(
            dimension_evidence="absent",
            internal_signals=(
                _signal(
                    "geometry_not_visible",
                    "rear shank continuation",
                    "The supplied shank line stops before the rear continuation is defined.",
                ),
                _signal(
                    "geometry_ambiguous",
                    "shoulder transition",
                    "Two supplied construction strokes overlap at the shoulder transition.",
                ),
            ),
        ),
        inventory_example=InventoryExample(
            filename="image-90.jpg",
            allowed_input_kinds=("hand_drawing",),
            relevance=(
                "Inventory note identifies a hand sketch on a hand plus a "
                "separate ring drawing. The fixture evidence is not a live image "
                "assessment."
            ),
        ),
    ),
    DrawingQualityFixture(
        fixture_id="single-visible-line-design",
        coverage_intent=(
            "Single legible hand-drawn design with no recorded uncertainty "
            "signals at intake."
        ),
        intake_facts=DrawingIntakeFacts(dimension_evidence="absent"),
        inventory_example=InventoryExample(
            filename="image-10.jpg",
            allowed_input_kinds=("line_art",),
            relevance="Inventory identifies one single line-art pendant.",
        ),
    ),
    DrawingQualityFixture(
        fixture_id="dimensioned-multi-view-source",
        coverage_intent=(
            "Multi-view dimensioned source with one recorded disagreement between "
            "views."
        ),
        intake_facts=DrawingIntakeFacts(
            dimension_evidence="designer_supplied",
            internal_signals=(
                _signal(
                    "views_disagree",
                    "side connection geometry",
                    "Two supplied views depict different side connection outlines.",
                ),
            ),
        ),
        inventory_example=InventoryExample(
            filename="image-86.jpg",
            allowed_input_kinds=("technical_sheet",),
            relevance=(
                "Inventory identifies detailed CAD-style drawings with dimensions. "
                "The disagreement signal belongs to the fixture, not the inventory "
                "classification."
            ),
        ),
    ),
    DrawingQualityFixture(
        fixture_id="line-and-color-intent-source",
        coverage_intent=(
            "Designer illustration containing visible line geometry, color intent, "
            "and one annotation whose meaning is not established."
        ),
        intake_facts=DrawingIntakeFacts(
            dimension_evidence="reference_estimate",
            internal_signals=(
                _signal(
                    "annotation_ambiguous",
                    "blue shoulder wash",
                    "The supplied color wash has no explicit material annotation.",
                ),
            ),
        ),
        inventory_example=InventoryExample(
            filename="image-11.jpg",
            allowed_input_kinds=("colored_design_plate",),
            relevance=(
                "Inventory identifies a single floral pendant design plate with "
                "notes."
            ),
        ),
    ),
    DrawingQualityFixture(
        fixture_id="finished-piece-photo-reference",
        coverage_intent=(
            "Finished-piece photograph with hidden construction and unresolved "
            "dimension provenance."
        ),
        intake_facts=DrawingIntakeFacts(
            dimension_evidence="unresolved",
            internal_signals=(
                _signal(
                    "geometry_not_visible",
                    "rear gallery construction",
                    "The photograph shows the front of the piece but not the rear gallery.",
                ),
            ),
        ),
        inventory_example=InventoryExample(
            filename="image-8.jpg",
            allowed_input_kinds=("finished_jewelry_photo",),
            relevance=(
                "Inventory identifies a single butterfly pendant product photo."
            ),
        ),
    ),
)


def compile_fixture_contract(
    fixture: DrawingQualityFixture,
) -> DrawingProcessingContract:
    """Delegate directly to the one canonical drawing-processing policy."""

    return build_drawing_processing_contract(fixture.intake_facts)


_USER_CLASSIFICATION = re.compile(
    r"\b(?:poor|rough|professional)\b",
    flags=re.IGNORECASE,
)


def evaluate_fixture_contract(
    fixture: DrawingQualityFixture,
    contract: DrawingProcessingContract,
) -> dict[str, Any]:
    """Assert invariant rendering and evidence-specific factory safeguards."""

    prompt = " ".join(contract.prompt_facts)
    signals = fixture.intake_facts.internal_signals
    question_subjects = {
        question.subject for question in contract.factory_questions
    }
    signals_captured = all(
        f"[{signal.code}]" in prompt
        and signal.subject in prompt
        and signal.subject in question_subjects
        for signal in signals
    )
    unresolved_captured = (
        fixture.intake_facts.dimension_evidence != "unresolved"
        or any(
            question.code == "classify_dimension_evidence"
            for question in contract.factory_questions
        )
    )
    checks = {
        "canonical_contract_version": (
            contract.contract_version == "drawing-processing.v1"
        ),
        "uniform_render_strategy": (
            contract.policy.render_strategy == "faithful_best_effort"
        ),
        "visual_attempt_never_preblocked": (
            contract.policy.visual_render_allowed is True
            and contract.policy.pre_render_clarification_required is False
        ),
        "supplied_design_evidence_preserved": (
            contract.policy.geometry_handling
            == "preserve_supplied_design_evidence"
            and "Preserve every supplied visible line" in prompt
        ),
        "internal_signals_captured": signals_captured,
        "dimension_provenance_handled": (
            bool(contract.policy.dimension_handling)
            and unresolved_captured
        ),
        "provider_output_not_authoritative": (
            contract.policy.provider_output_authoritative is False
            and "AI output is never factory authority" in prompt
        ),
        "factory_truth_uses_validated_record_and_source": (
            contract.policy.factory_truth_source
            == "validated_record_plus_original_source"
        ),
        "no_user_quality_classification_in_prompt": (
            _USER_CLASSIFICATION.search(prompt) is None
        ),
    }
    dimensions = {
        "fidelity": checks["supplied_design_evidence_preserved"],
        "best_result_usefulness": (
            checks["uniform_render_strategy"]
            and checks["visual_attempt_never_preblocked"]
        ),
        "uncertainty_capture": (
            checks["internal_signals_captured"]
            and checks["dimension_provenance_handled"]
        ),
        "factory_truth_non_promotion": (
            checks["provider_output_not_authoritative"]
            and checks["factory_truth_uses_validated_record_and_source"]
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "status": "pass" if not failed else "fail",
        "checks": checks,
        "evaluation_dimensions": dimensions,
        "failed_checks": failed,
    }


def required_live_outcome(
    fixture: DrawingQualityFixture,
    contract: DrawingProcessingContract,
) -> dict[str, Any]:
    """State future live acceptance without pretending a render occurred."""

    return {
        "render_strategy": contract.policy.render_strategy,
        "visual_attempt": "required",
        "source_design_evidence": "preserved",
        "review_proposal_may_be_factory_truth": False,
        "provider_output_authoritative": False,
        "designer_review_required": contract.policy.designer_review_required,
        "dimension_evidence": fixture.intake_facts.dimension_evidence,
        "dimension_handling": contract.policy.dimension_handling,
        "internal_signal_count": len(fixture.intake_facts.internal_signals),
        "factory_question_count": len(contract.factory_questions),
    }


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def load_inventory_evidence(
    preflight_path: Path,
    inventory_path: Path,
) -> dict[str, Any]:
    """Link neutral fixtures to the 144-item inventory without reading images."""

    preflight = _load_json(preflight_path)
    inventory = _load_json(inventory_path)
    rows = preflight.get("rows")
    items = inventory.get("items")
    if not isinstance(rows, list) or not isinstance(items, list):
        raise ValueError("inventory evidence is missing rows/items")
    if preflight.get("total_files") != 144 or len(rows) != 144:
        raise ValueError("preflight is not the expected 144-file inventory")
    if inventory.get("summary", {}).get("item_count") != 144 or len(items) != 144:
        raise ValueError("semantic inventory is not the expected 144 items")

    rows_by_name = {row.get("filename"): row for row in rows}
    items_by_name = {item.get("filename"): item for item in items}
    if len(rows_by_name) != 144 or len(items_by_name) != 144:
        raise ValueError("the 144-item inventory contains duplicate filenames")
    if set(rows_by_name) != set(items_by_name):
        raise ValueError("preflight and semantic inventory filenames differ")

    examples: dict[str, Any] = {}
    for fixture in MATRIX_FIXTURES:
        pointer = fixture.inventory_example
        row = rows_by_name.get(pointer.filename)
        item = items_by_name.get(pointer.filename)
        if not isinstance(row, dict) or not isinstance(item, dict):
            raise ValueError(f"missing inventory example: {pointer.filename}")
        observed_kind = item.get("input_kind")
        if observed_kind not in pointer.allowed_input_kinds:
            raise ValueError(
                f"unexpected input_kind for {pointer.filename}: {observed_kind}"
            )
        examples[fixture.fixture_id] = {
            "filename": pointer.filename,
            "sha256": row.get("sha256"),
            "decodable": bool(row.get("format")),
            "inventory_input_kind": observed_kind,
            "inventory_category": item.get("primary_category"),
            "inventory_notes": item.get("notes"),
            "relevance": pointer.relevance,
            "evidence_scope": "inventory_taxonomy_only",
            "live_tested_by_this_harness": False,
        }

    return {
        "inventoried_files": len(rows),
        "decodable_files": preflight.get("decodable_files"),
        "semantic_inventory_advisory_only": inventory.get(
            "summary", {}
        ).get("advisory_only"),
        "source_policy": inventory.get("source_policy"),
        "examples": examples,
        "evidence_scope": (
            "The 144-image corpus is reused only to anchor neutral internal "
            "fixtures to advisory inventory records and source hashes. This "
            "harness performs no pixel inspection, model call, or live image "
            "quality claim."
        ),
    }


def run_contract_matrix(inventory_evidence: dict[str, Any]) -> dict[str, Any]:
    """Run six provider-free probes against the one canonical policy."""

    rows: list[dict[str, Any]] = []
    for fixture in MATRIX_FIXTURES:
        contract = compile_fixture_contract(fixture)
        rows.append({
            "fixture_id": fixture.fixture_id,
            "internal_coverage_intent": fixture.coverage_intent,
            "intake_facts": fixture.intake_facts.model_dump(mode="json"),
            "processing_contract": contract.model_dump(mode="json"),
            "contract_evaluation": evaluate_fixture_contract(
                fixture, contract
            ),
            "required_live_outcome": required_live_outcome(
                fixture, contract
            ),
            "inventory_example": inventory_evidence["examples"][
                fixture.fixture_id
            ],
        })

    strategies = {
        row["processing_contract"]["policy"]["render_strategy"]
        for row in rows
    }
    all_pass = all(
        row["contract_evaluation"]["status"] == "pass" for row in rows
    )
    return {
        "run_kind": "provider_free_canonical_drawing_contract_matrix",
        "canonical_policy": (
            "facetta.drawing_intake.build_drawing_processing_contract"
        ),
        "contract_version": "drawing-processing.v1",
        "product_behavior": {
            "fixture_ids_are_internal_only": True,
            "user_source_classification": None,
            "user_drawing_is_scored_or_ranked": False,
            "uniform_render_strategy": "faithful_best_effort",
        },
        "summary": {
            "fixture_count": len(rows),
            "contract_pass_count": sum(
                row["contract_evaluation"]["status"] == "pass"
                for row in rows
            ),
            "all_contracts_pass": all_pass,
            "distinct_render_strategy_count": len(strategies),
            "render_strategies": sorted(strategies),
            "provider_calls": 0,
            "images_generated": 0,
            "images_live_evaluated": 0,
            "user_sources_classified": 0,
            "user_drawings_scored": False,
            "factory_truth_from_provider_output_allowed": False,
        },
        "inventory_evidence": inventory_evidence,
        "fixtures": rows,
        "release_boundary": (
            "Passing this matrix proves canonical contract consistency only. "
            "It does not prove image quality, provider reliability, geometry "
            "fidelity, or factory readiness; those require separate live evals "
            "and designer review."
        ),
    }

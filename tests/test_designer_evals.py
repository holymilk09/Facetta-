import hashlib
import json

from PIL import Image

from facetta.designer_evals import (
    DesignerReferenceCase,
    inspect_source,
    score_paired_reads,
    score_plate_read,
    summarize_source_coverage,
)


def _case(**updates):
    values = {
        "id": "leaf-ring",
        "source_filename": "leaf.jpg",
        "sha256": "0" * 64,
        "category": "ring",
        "input_kind": "plate",
        "workflows": ["plate_read"],
        "expected_jewelry_type": "ring",
        "expected_terms_any": ["emerald", "leaf"],
        "expected_min_stone_groups": 2,
        "authoritative_text_any": ["2 mm"],
    }
    values.update(updates)
    return DesignerReferenceCase.model_validate(values)


def test_source_inventory_checks_hash_and_image(tmp_path):
    path = tmp_path / "leaf.jpg"
    Image.new("RGB", (20, 30), "white").save(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    result = inspect_source(_case(sha256=digest), tmp_path)
    assert result["hash_matches"] is True
    assert result["decodable"] is True
    assert result["size"] == [20, 30]


def test_plate_read_score_keeps_ocr_and_identity_separate():
    case = _case()
    read = {
        "jewelry_type": "ring",
        "stones": [
            {"type": "emerald cushion"},
            {"type": "diamond leaf melee"},
        ],
        "hand_written": ["band width 2 mm"],
    }
    score = score_plate_read(case, read)
    assert score["status"] == "pass"
    assert score["score"] == 100
    assert score["term_hits"] == ["emerald", "leaf"]


def test_plate_read_missing_authoritative_text_requires_review():
    read = {
        "jewelry_type": "ring",
        "stones": [{"type": "emerald"}, {"type": "diamond"}],
        "hand_written": [],
    }
    score = score_plate_read(_case(), read)
    assert score["status"] == "review_required"
    assert score["checks"]["authoritative_text"] is False
    json.dumps(score)


def test_material_variant_pair_catches_geometry_read_instability():
    base = {
        "jewelry_type": "ring",
        "stones": [
            {"type": "green emerald-cut stone"},
            {"type": "diamond marquise"},
        ],
        "measurements": [{"value": "2 mm"}, {"value": "11.5 mm"}],
    }
    variant = {
        "jewelry_type": "ring",
        "stones": [
            {"type": "pink princess-cut stone"},
            {"type": "diamond marquise"},
            {"type": "diamond round"},
        ],
        "measurements": [{"value": "2 mm"}, {"value": "11.5 mm"}],
    }
    score = score_paired_reads(base, variant)
    assert score["status"] == "fail"
    assert score["checks"]["center_cut_stable"] is False
    assert score["checks"]["stone_group_count_stable"] is False


def test_coverage_summary_never_turns_a_perfect_read_into_factory_truth():
    rows = [{
        "case": "architectural-ring",
        "read_score": {"score": 100.0, "status": "pass"},
        "coverage_status": "review_required",
        "coverage_blockers": [
            {"code": "source_component_unresolved"},
            {"code": "source_component_audit_failed"},
        ],
    }, {
        "case": "simple-solitaire",
        "read_score": {"score": 75.0, "status": "review_required"},
        "coverage_status": "pass",
        "coverage_blockers": [],
    }, {
        "case": "necklace-probe",
        "coverage_status": "not_applicable_ring_first",
    }]

    summary = summarize_source_coverage(rows)

    assert summary["applicable_cases"] == 2
    assert summary["factory_ready_cases"] == 1
    assert summary["factory_ready_rate"] == 50.0
    assert summary["all_factory_ready"] is False
    assert summary["status_counts"] == {
        "pass": 1,
        "review_required": 1,
        "invalid": 0,
        "unavailable": 0,
    }
    assert summary["blocking_cases"] == [{
        "case": "architectural-ring",
        "status": "review_required",
        "blocker_count": 2,
    }]


def test_coverage_summary_counts_invalid_audits_as_blocking():
    summary = summarize_source_coverage([{
        "case": "contradictory-audit",
        "coverage_status": "invalid",
        "coverage_error": "contradictory bidirectional mapping",
    }])

    assert summary["status_counts"]["invalid"] == 1
    assert summary["factory_ready_rate"] == 0.0
    assert summary["all_factory_ready"] is False

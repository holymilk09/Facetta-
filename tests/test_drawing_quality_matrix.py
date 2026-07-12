from __future__ import annotations

from pathlib import Path

from facetta.drawing_quality_matrix import (
    MATRIX_FIXTURES,
    compile_fixture_contract,
    evaluate_fixture_contract,
    load_inventory_evidence,
    run_contract_matrix,
)


ROOT = Path(__file__).resolve().parent.parent


def test_six_internal_fixtures_compile_one_uniform_visual_policy():
    assert len(MATRIX_FIXTURES) == 6
    contracts = [
        compile_fixture_contract(fixture) for fixture in MATRIX_FIXTURES
    ]
    assert {
        contract.policy.render_strategy for contract in contracts
    } == {"faithful_best_effort"}
    assert all(contract.policy.visual_render_allowed for contract in contracts)
    assert all(
        contract.policy.pre_render_clarification_required is False
        for contract in contracts
    )
    assert all(
        contract.policy.geometry_handling
        == "preserve_supplied_design_evidence"
        for contract in contracts
    )


def test_provider_prompt_facts_never_receive_fixture_quality_labels():
    banned = ("poor", "rough", "professional")
    for fixture in MATRIX_FIXTURES:
        contract = compile_fixture_contract(fixture)
        prompt = " ".join(contract.prompt_facts).lower()
        assert all(word not in prompt for word in banned)
        assert fixture.fixture_id not in prompt
        assert "FAITHFUL BEST EFFORT" in prompt.upper()


def test_only_factual_signals_and_dimension_provenance_vary():
    dimensions = {
        fixture.intake_facts.dimension_evidence
        for fixture in MATRIX_FIXTURES
    }
    assert dimensions == {
        "absent",
        "reference_estimate",
        "designer_supplied",
        "unresolved",
    }
    allowed_codes = {
        "geometry_not_visible",
        "geometry_ambiguous",
        "views_disagree",
        "dimension_illegible",
        "annotation_ambiguous",
    }
    assert all(
        signal.visibility == "internal_only"
        and signal.code in allowed_codes
        for fixture in MATRIX_FIXTURES
        for signal in fixture.intake_facts.internal_signals
    )


def test_each_fixture_passes_four_required_evaluation_dimensions():
    for fixture in MATRIX_FIXTURES:
        contract = compile_fixture_contract(fixture)
        evaluation = evaluate_fixture_contract(fixture, contract)
        assert evaluation["status"] == "pass"
        assert evaluation["evaluation_dimensions"] == {
            "fidelity": True,
            "best_result_usefulness": True,
            "uncertainty_capture": True,
            "factory_truth_non_promotion": True,
        }


def test_internal_evidence_changes_factory_questions_not_visual_attempt():
    for fixture in MATRIX_FIXTURES:
        contract = compile_fixture_contract(fixture)
        signal_subjects = {
            signal.subject for signal in fixture.intake_facts.internal_signals
        }
        question_subjects = {
            question.subject for question in contract.factory_questions
        }
        assert signal_subjects <= question_subjects
        assert contract.policy.visual_render_allowed is True
        assert contract.policy.render_strategy == "faithful_best_effort"
        assert contract.policy.provider_output_authoritative is False


def test_unresolved_dimensions_add_factory_question_without_render_block():
    fixture = next(
        fixture for fixture in MATRIX_FIXTURES
        if fixture.intake_facts.dimension_evidence == "unresolved"
    )
    contract = compile_fixture_contract(fixture)
    assert any(
        question.code == "classify_dimension_evidence"
        for question in contract.factory_questions
    )
    assert contract.policy.factory_spec_blocked_by_drawing_evidence is True
    assert contract.policy.visual_render_allowed is True
    assert contract.policy.pre_render_clarification_required is False


def test_runner_reuses_144_inventory_without_claiming_live_evaluation():
    evidence = load_inventory_evidence(
        ROOT / "docs" / "evals" /
        "designer-reference-all-144-preflight-2026-07-11" / "results.json",
        ROOT / "docs" / "evals" /
        "designer-reference-inventory-live-2026-07-11" / "results.json",
    )
    result = run_contract_matrix(evidence)
    assert evidence["inventoried_files"] == 144
    assert evidence["decodable_files"] == 144
    assert evidence["semantic_inventory_advisory_only"] is True
    assert all(
        example["evidence_scope"] == "inventory_taxonomy_only"
        and example["live_tested_by_this_harness"] is False
        for example in evidence["examples"].values()
    )
    assert result["summary"] == {
        "fixture_count": 6,
        "contract_pass_count": 6,
        "all_contracts_pass": True,
        "distinct_render_strategy_count": 1,
        "render_strategies": ["faithful_best_effort"],
        "provider_calls": 0,
        "images_generated": 0,
        "images_live_evaluated": 0,
        "user_sources_classified": 0,
        "user_drawings_scored": False,
        "factory_truth_from_provider_output_allowed": False,
    }
    behavior = result["product_behavior"]
    assert behavior["fixture_ids_are_internal_only"] is True
    assert behavior["user_source_classification"] is None
    assert behavior["uniform_render_strategy"] == "faithful_best_effort"

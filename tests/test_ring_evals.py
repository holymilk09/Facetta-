"""Offline guarantees for the live trusted-ring evaluation matrix."""

import pytest

from facetta.creative_symmetry import JEWELRY_SYMMETRY_CONTRACT
from facetta.image_agent import ImageOperation, build_image_plan
from facetta.image_agent.prompts import compile_initial_prompt
from facetta.ring_evals import (
    CANONICAL_RING_EDITS,
    RING_GOLDEN_CASES,
    apply_canonical_ring_edit,
    build_ring_golden_spec,
    evaluate_release_gates,
)
from facetta.specdiff import diff_specs


def test_ring_golden_set_covers_required_visual_families():
    specs = [(case, build_ring_golden_spec(case))
             for case in RING_GOLDEN_CASES]
    assert {case.center_cut for case, _ in specs} >= {
        "round_brilliant", "oval_brilliant", "emerald_cut", "cushion",
        "marquise"}
    assert {case.metal_color for case, _ in specs} == {
        "yellow", "white", "rose"}
    assert {case.prong_count for case, _ in specs} == {4, 6}
    assert {case.starting_point for case, _ in specs} == {
        "spec_render", "imported_reference"}
    assert any(case.halo for case, _ in specs)
    assert any(not case.halo for case, _ in specs)
    assert any(case.template == "leaf_shoulder_prong" for case, _ in specs)
    assert min(case.band_width_mm for case, _ in specs) <= 1.8
    assert max(case.band_width_mm for case, _ in specs) >= 3.2
    for case, spec in specs:
        assert spec.stone.cut == case.center_cut
        assert spec.setting.prong_count == case.prong_count
        assert spec.metal.color == case.metal_color
        assert spec.band.width_mm == case.band_width_mm
        if case.halo:
            assert spec.side_stones[0].count == 19
        if case.template is not None:
            assert spec.template == case.template
        if case.template == "leaf_shoulder_prong":
            assert [(stone.cut, stone.count, stone.position)
                    for stone in spec.side_stones] == [
                ("marquise", 12, "pave_leaves"),
                ("round_brilliant", 24, "pave_leaves"),
            ]


def test_canonical_edits_produce_valid_specs_or_reject_before_provider():
    cases = {case.id: case for case in RING_GOLDEN_CASES}
    by_id = {edit.id: edit for edit in CANONICAL_RING_EDITS}
    assert set(by_id) == {
        "center-cut-shape", "center-species-color", "band-width",
        "metal-color", "metal-material", "prong-setting", "halo-add",
        "halo-remove", "halo-count", "leaf-motif-shape",
        "intentional-shoulder-asymmetry",
        "background-only", "impossible-band-width"}
    assert {edit.category for edit in CANONICAL_RING_EDITS} == {
        "center_shape", "center_identity", "band_geometry", "metal_color",
        "metal_material", "setting", "stone_inventory", "motif_shape",
        "presentation", "invalid_geometry",
    }
    assert {edit.golden_case_id for edit in CANONICAL_RING_EDITS} <= set(cases)
    assert len({edit.golden_case_id for edit in CANONICAL_RING_EDITS}) >= 5
    assert cases[by_id["halo-count"].golden_case_id].halo is True
    assert cases[by_id["halo-remove"].golden_case_id].halo is True
    assert cases[by_id["halo-add"].golden_case_id].halo is False
    assert cases[by_id["leaf-motif-shape"].golden_case_id].template == (
        "leaf_shoulder_prong")
    for edit in CANONICAL_RING_EDITS:
        base = build_ring_golden_spec(cases[edit.golden_case_id])
        updated, issues = apply_canonical_ring_edit(base, edit)
        assert (updated is not None) is edit.expected_valid
        assert bool(issues) is (not edit.expected_valid)
        if edit.expected_valid and edit.requires_spec_delta:
            assert updated != base
            assert edit.allowed_delta_prefixes
            changes = diff_specs(
                base.model_dump(mode="json"),
                updated.model_dump(mode="json"),
            )
            assert changes
            assert all(
                any(change["path"] == prefix
                    or change["path"].startswith(prefix + ".")
                    for prefix in edit.allowed_delta_prefixes)
                for change in changes
            ), (edit.id, changes)
            assert edit.frozen_facts
    background_base = build_ring_golden_spec(
        cases[by_id["background-only"].golden_case_id])
    unchanged, _ = apply_canonical_ring_edit(
        background_base, by_id["background-only"])
    assert unchanged == background_base
    band_base = build_ring_golden_spec(
        cases[by_id["band-width"].golden_case_id])
    widened, _ = apply_canonical_ring_edit(band_base, by_id["band-width"])
    assert widened.band.width_mm == pytest.approx(band_base.band.width_mm + 0.6)

    intentional = by_id["intentional-shoulder-asymmetry"]
    intentional_base = build_ring_golden_spec(
        cases[intentional.golden_case_id]
    )
    intentional_target, issues = apply_canonical_ring_edit(
        intentional_base, intentional
    )
    assert issues == []
    assert intentional_target == intentional_base
    assert intentional.requires_spec_delta is False
    assert JEWELRY_SYMMETRY_CONTRACT in intentional.instruction
    assert "designer-requested asymmetry" in intentional.instruction
    assert JEWELRY_SYMMETRY_CONTRACT in by_id["leaf-motif-shape"].instruction


def test_canonical_edits_mutate_exact_designer_facts_and_freeze_the_rest():
    cases = {case.id: case for case in RING_GOLDEN_CASES}
    edits = {edit.id: edit for edit in CANONICAL_RING_EDITS}

    def apply(edit_id):
        edit = edits[edit_id]
        base = build_ring_golden_spec(cases[edit.golden_case_id])
        target, issues = apply_canonical_ring_edit(base, edit)
        assert target is not None and issues == []
        return base, target

    before, after = apply("center-cut-shape")
    assert before.stone.cut == "oval_brilliant"
    assert after.stone.cut == "emerald_cut"
    assert after.stone.dimensions_mm == before.stone.dimensions_mm
    assert after.stone.species == before.stone.species
    assert after.stone.color == before.stone.color
    assert after.setting == before.setting

    before, after = apply("center-species-color")
    assert after.stone.species == "sapphire"
    assert after.stone.color.trade == "Royal Blue"
    assert after.stone.cut == before.stone.cut
    assert after.stone.dimensions_mm == before.stone.dimensions_mm
    assert after.setting == before.setting

    before, after = apply("metal-color")
    assert after.metal.material == "gold"
    assert after.metal.karat == 18
    assert after.metal.color == "rose"
    assert after.stone == before.stone
    assert after.side_stones == before.side_stones

    before, after = apply("metal-material")
    assert before.metal.material == "gold"
    assert after.metal.material == "platinum"
    assert after.metal.karat is None and after.metal.color is None
    assert after.stone == before.stone
    assert after.setting == before.setting

    before, after = apply("prong-setting")
    assert before.setting.prong_count == 6
    assert after.setting.prong_count == 4
    assert after.setting.style == "4_prong_basket"
    assert after.stone == before.stone
    assert after.side_stones == before.side_stones

    before, after = apply("halo-add")
    assert before.side_stones == []
    assert after.template == "halo_prong"
    assert [(group.position, group.count, group.cut)
            for group in after.side_stones] == [
        ("halo", 12, "round_brilliant")]
    assert after.stone == before.stone
    assert after.setting == before.setting

    before, after = apply("halo-remove")
    assert before.side_stones and after.side_stones == []
    assert after.template == "solitaire_prong"
    assert after.stone == before.stone
    assert after.setting == before.setting

    before, after = apply("halo-count")
    assert after.side_stones[0].count == before.side_stones[0].count - 1
    before_group = before.side_stones[0].model_copy(update={
        "count": after.side_stones[0].count})
    assert after.side_stones[0] == before_group

    before, after = apply("leaf-motif-shape")
    assert before.side_stones[0].cut == "marquise"
    assert after.side_stones[0].cut == "pear"
    assert after.side_stones[0].count == before.side_stones[0].count == 12
    assert after.side_stones[0].dimensions_mm == (
        before.side_stones[0].dimensions_mm)
    assert after.side_stones[1] == before.side_stones[1]
    assert after.stone == before.stone
    assert after.setting == before.setting


def test_canonical_matrix_builds_delta_driven_image_plans_without_pixel_logic():
    cases = {case.id: case for case in RING_GOLDEN_CASES}
    for edit in CANONICAL_RING_EDITS:
        if not edit.expected_valid:
            continue
        source = build_ring_golden_spec(cases[edit.golden_case_id])
        target, issues = apply_canonical_ring_edit(source, edit)
        assert target is not None and issues == []
        operation = (ImageOperation.VISUAL_ONLY_EDIT if edit.visual_only
                     else ImageOperation.LOCAL_EDIT)
        plan = build_image_plan(
            operation,
            edit.instruction,
            spec=target,
            source_spec=source,
            source_image=b"approved-source-image",
            region_description=(None if edit.visual_only else edit.region),
            frozen=edit.frozen_facts,
        )
        assert plan.operation is operation
        assert set(edit.frozen_facts) <= set(plan.frozen)
        delta = plan.normalized_intent["spec_delta"]
        if not edit.requires_spec_delta:
            assert delta == []
        else:
            assert delta
            assert all(
                any(change["path"] == prefix
                    or change["path"].startswith(prefix + ".")
                    for prefix in edit.allowed_delta_prefixes)
                for change in delta
            )


def test_canonical_matrix_compiles_domain_specific_pixel_instructions():
    cases = {case.id: case for case in RING_GOLDEN_CASES}
    expected = {
        "center-cut-shape": (
            {"center_stone_shape"}, {"CENTER-STONE SHAPE EXECUTION"}),
        "center-species-color": (
            {"center_stone_identity", "center_stone_color"},
            {"CENTER-STONE MATERIAL/COLOR EXECUTION"}),
        "band-width": (
            {"band_geometry"}, {"BAND-WIDTH GEOMETRY EXECUTION"}),
        "metal-color": (
            {"metal_identity"}, {"METAL MATERIAL/COLOR EXECUTION"}),
        "metal-material": (
            {"metal_identity"}, {"METAL MATERIAL/COLOR EXECUTION"}),
        "prong-setting": (
            {"setting"}, {"SETTING / PRONG EXECUTION"}),
        "halo-add": (
            {"side_stone_inventory"},
            {"SIDE-STONE INVENTORY EXECUTION"}),
        "halo-remove": (
            {"side_stone_inventory"},
            {"SIDE-STONE INVENTORY EXECUTION"}),
        "halo-count": (
            {"side_stone_inventory"}, {"SIDE-STONE INVENTORY EXECUTION"}),
        "leaf-motif-shape": (
            {"side_stone_shape"}, {"SIDE-STONE / MOTIF SHAPE EXECUTION"}),
    }
    edits = {edit.id: edit for edit in CANONICAL_RING_EDITS}
    assert set(expected) == {
        edit.id for edit in CANONICAL_RING_EDITS
        if edit.expected_valid and edit.requires_spec_delta
    }
    for edit_id, (domains, phrases) in expected.items():
        edit = edits[edit_id]
        source = build_ring_golden_spec(cases[edit.golden_case_id])
        target, issues = apply_canonical_ring_edit(source, edit)
        assert target is not None and issues == []
        plan = build_image_plan(
            ImageOperation.LOCAL_EDIT,
            edit.instruction,
            spec=target,
            source_spec=source,
            source_image=b"approved-source-image",
            region_description=edit.region,
            frozen=edit.frozen_facts,
        )
        prompt = compile_initial_prompt(plan)

        assert {domain.value for domain in plan.edit_domains} == domains
        for phrase in phrases:
            assert phrase in prompt
        assert "SOURCE SPEC FACTS (before edit)" in prompt
        assert "VALIDATED RESULT FACTS (after edit)" in prompt
        assert "EXACT SPEC DELTA" in prompt
        if edit_id in {"halo-add", "halo-remove", "halo-count"}:
            contract = plan.normalized_intent[
                "side_stone_inventory_contract"
            ]
            assert contract["target"]["total_count"] >= 0
            assert "SOURCE-TO-TARGET INVENTORY CONTRACT" in prompt
            assert "Do not fake a removal" in prompt
        if edit_id == "prong-setting":
            assert edit.golden_case_id == "oval-solitaire-white-6-wide"
            contract = plan.normalized_intent["setting_topology_contract"]
            assert contract["source"]["prong_count"] == 6
            assert contract["target"]["prong_count"] == 4
            assert "SOURCE-TO-TARGET SETTING TOPOLOGY" in prompt
            assert "Do not fake removal" in prompt
        for frozen in edit.frozen_facts:
            assert frozen in prompt


def test_spec_render_makes_exact_center_prongs_individually_countable():
    case = next(
        item for item in RING_GOLDEN_CASES
        if item.id == "cushion-halo-white-6-wide"
    )
    plan = build_image_plan(
        ImageOperation.SPEC_RENDER,
        "render the validated ring",
        spec=build_ring_golden_spec(case),
    )
    prompt = compile_initial_prompt(plan)

    assert plan.prompt_version == "spec-render.v3"
    assert "exactly 6 separate metal prongs" in prompt
    assert "Every one of the 6 holding prongs" in prompt
    assert "Do not add unlisted pave or shoulder stones" in prompt

def test_release_gates_match_the_internal_acceptance_thresholds():
    rows = [
        {"kind": "render", "score": score, "hard_gate_pass": True}
        for score in (90, 88, 87, 86, 85, 85, 85, 85, 85, 85)
    ] + [
        {"kind": "edit", "score": score, "applied": True,
         "attempts": 3, "severity": "none", "expected_valid": True}
        for score in (90, 92, 94, 91, 93, 90)
    ]
    gates = evaluate_release_gates(rows, persistence_evidence={
        "verified": True,
        "method": "canonical_project_api_integration",
        "result_set": "trusted-ring-api-acceptance-test",
        "rejected_active_asset_count": 0,
    })
    assert gates["hard_gate_pass_rate"] == 1.0
    assert gates["hard_gate_pass"] is True
    assert gates["spec_render_conformance_pass"] is True
    assert gates["all_localized_edits_within_three_attempts"] is True
    assert gates["edit_fidelity_pass"] is True
    assert gates["zero_major_unintended_drift"] is True
    assert gates["persistence_evidence_verified"] is True
    assert gates["zero_rejected_candidates_persisted"] is True
    assert gates["automated_gates_pass"] is True
    assert gates["blocking_enabled"] is False
    assert "GIA-trained" in gates["blocking_note"]


def test_release_gates_fail_closed_without_persistence_evidence():
    rows = [
        {"kind": "render", "score": 90, "hard_gate_pass": True},
        {"kind": "edit", "score": 95, "applied": True,
         "attempts": 1, "severity": "none", "expected_valid": True},
    ]
    missing = evaluate_release_gates(rows)
    assert missing["persistence_evidence_verified"] is False
    assert missing["zero_rejected_candidates_persisted"] is False
    assert missing["automated_gates_pass"] is False

    self_claimed_but_unnamed = evaluate_release_gates(
        rows,
        persistence_evidence={
            "verified": True,
            "method": "",
            "result_set": "",
            "rejected_active_asset_count": 0,
        },
    )
    assert self_claimed_but_unnamed["persistence_evidence_verified"] is False


def test_imported_reference_cases_are_explicitly_reference_backed():
    imported = [case for case in RING_GOLDEN_CASES
                if case.starting_point == "imported_reference"]
    generated = [case for case in RING_GOLDEN_CASES
                 if case.starting_point == "spec_render"]
    assert imported and generated
    assert all(case.requires_reference for case in imported)
    assert all(not case.requires_reference for case in generated)

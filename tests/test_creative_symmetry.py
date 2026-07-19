"""Prompt concepts fail closed on unrequested jewelry asymmetry."""

from __future__ import annotations

import io

from PIL import Image

from facetta.creative_symmetry import (
    JEWELRY_SYMMETRY_CONTRACT,
    JEWELRY_SYMMETRY_REPAIR_CONTRACT,
    SIX_LEAF_RUBY_PATTERN_CONTRACT,
    requests_jewelry_symmetry_repair,
    requests_six_leaf_ruby_pattern,
    with_jewelry_symmetry_contract,
    with_requested_jewelry_symmetry_repair,
)
from facetta.image_agent import (
    CreativeRenderInspection,
    ImageOperation,
    NecklaceSymmetryAudit,
    NecklaceSymmetryPairAudit,
    QualityVerdict,
    RingQualityEvaluator,
    build_image_plan,
)
from facetta.image_agent.prompts import compile_correction_prompt


def _png() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (64, 64), (248, 245, 238)).save(
        output, format="PNG"
    )
    return output.getvalue()


def test_refine_symmetry_repair_requires_explicit_bilateral_language():
    assert requests_jewelry_symmetry_repair(
        "Make the left and right sides symmetrical around the centerline."
    )
    assert requests_jewelry_symmetry_repair(
        "Use the same pattern on both sides."
    )
    assert not requests_jewelry_symmetry_repair(
        "Make the background warmer and the gold more luminous."
    )
    assert not requests_jewelry_symmetry_repair(
        "Preserve the intentional asymmetry in the source."
    )


def test_requested_refine_repair_overrides_only_the_source_mismatch():
    instruction = with_requested_jewelry_symmetry_repair(
        "Match the left and right sides."
    )

    assert JEWELRY_SYMMETRY_CONTRACT in instruction
    assert JEWELRY_SYMMETRY_REPAIR_CONTRACT in instruction
    assert "center element" in instruction
    assert with_requested_jewelry_symmetry_repair(
        "Keep the intentional asymmetry."
    ) == "Keep the intentional asymmetry."


class _Inspector:
    def __init__(self, inspection: CreativeRenderInspection) -> None:
        self.inspection = inspection

    def inspect_render(self, plan, candidate):
        assert JEWELRY_SYMMETRY_CONTRACT in plan.intent
        assert candidate
        return self.inspection


class _SourceInspector:
    def __init__(self, inspection: CreativeRenderInspection) -> None:
        self.inspection = inspection

    def inspect_render(self, plan, source, candidate):
        assert JEWELRY_SYMMETRY_CONTRACT in plan.intent
        assert source
        assert candidate
        assert source != candidate
        return self.inspection


def _inspection(
    symmetry: bool | None,
    *observations: str,
    necklace_audits: tuple[NecklaceSymmetryAudit, ...] = (),
) -> CreativeRenderInspection:
    return CreativeRenderInspection(
        coherent_jewelry_render=True,
        complete_piece_visible=True,
        source_design_preserved=True,
        visible_components_preserved=True,
        local_geometry_preserved=True,
        repeated_element_pattern_preserved=True,
        stone_shape_and_cut_family_preserved=True,
        requested_presentation_applied=True,
        explicit_counts_match=True,
        explicit_stone_facts_match=True,
        symmetry_expectation_matches=symmetry,
        symmetry_observations=(observations or (
            "compared the gold and pave leaf sequence from the pendant outward",
        )),
        necklace_symmetry_audits=necklace_audits,
        text_or_branding_detected=False,
        score=96,
    )


def _report(
    symmetry: bool | None,
    instruction: str = (
        "A ruby necklace with alternating gold and pave leaf links"
    ),
    *observations: str,
):
    instruction = with_jewelry_symmetry_contract(
        instruction
    )
    plan = build_image_plan(
        ImageOperation.CREATIVE_GENERATE,
        instruction,
    )
    necklace_audits: tuple[NecklaceSymmetryAudit, ...] = ()
    if "necklace" in instruction.lower() and symmetry is not None:
        explicit = "intentionally asymmetric" in instruction.lower()
        pair_matches = not (symmetry is False and not explicit)
        necklace_audits = (NecklaceSymmetryAudit(
            expectation=(
                "explicit_asymmetry"
                if explicit and symmetry is True else
                "bilateral"
            ),
            centerline_anchor="center ruby pendant",
            complete_piece_assessable=True,
            left_count=1,
            right_count=1,
            pair_audits=(NecklaceSymmetryPairAudit(
                position_from_center=1,
                left_component="left ruby leaf link",
                right_component="right ruby leaf link",
                motif_order_matches=(False if explicit and symmetry is True else True),
                orientation_matches=True,
                spacing_matches=True,
                scale_matches=True,
                metal_treatment_matches=pair_matches,
                pave_coverage_matches=pair_matches,
                gemstone_treatment_matches=True,
                connection_type_matches=True,
                authorized_differences=(
                    ("motif_order",) if explicit and symmetry is True else ()
                ),
                observation="compared the first links beside the center pendant",
            ),),
            requested_asymmetry_preserved=(True if explicit and symmetry is True else None),
            unrequested_differences_absent=True,
        ),)
    inspection = _inspection(
        symmetry,
        *observations,
        necklace_audits=necklace_audits,
    )
    report = RingQualityEvaluator(
        prompt_creative_inspector=_Inspector(inspection),
        require_cross_inspection=False,
        require_render_cross_inspection=False,
    ).evaluate(
        plan,
        _png(),
        source_image=None,
        mask_bytes=None,
    )
    return plan, report


def _source_report(symmetry: bool | None):
    source = _png()
    candidate_buffer = io.BytesIO()
    Image.new("RGB", (64, 64), (238, 235, 228)).save(
        candidate_buffer, format="PNG"
    )
    candidate = candidate_buffer.getvalue()
    instruction = with_jewelry_symmetry_contract(
        "Polish this visibly asymmetric heirloom brooch without changing "
        "its unequal left and right motif arrangement"
    )
    plan = build_image_plan(
        ImageOperation.REFERENCE_RENDER,
        instruction,
        source_image=source,
    )
    inspection = _inspection(
        symmetry,
        "the unequal source motifs remain in the same left/right arrangement",
    )
    report = RingQualityEvaluator(
        creative_inspector=_SourceInspector(inspection),
        require_creative_cross_inspection=False,
        require_cross_inspection=False,
        require_render_cross_inspection=False,
    ).evaluate(
        plan,
        candidate,
        source_image=source,
        mask_bytes=None,
    )
    return plan, report


def test_symmetry_contract_is_appended_exactly_once() -> None:
    once = with_jewelry_symmetry_contract("A diamond necklace")
    twice = with_jewelry_symmetry_contract(once)

    assert once == twice
    assert once.count(JEWELRY_SYMMETRY_CONTRACT) == 1
    assert "correspond link by link" in once
    assert "fully metal" in once
    assert "identity source remains authoritative" in once


def test_six_leaf_ruby_pattern_gets_an_exact_jewelry_interpretation() -> None:
    designer_words = (
        "Surrounding the ruby is 6 leaves, half white diamonds and half "
        "tsavorite, so it's a pattern."
    )

    assert requests_six_leaf_ruby_pattern(designer_words) is True
    contracted = with_jewelry_symmetry_contract(designer_words)
    assert contracted.count(SIX_LEAF_RUBY_PATTERN_CONTRACT) == 1
    assert "six discrete leaves total around the ruby motif" in contracted
    assert "three leaves use white-diamond treatment" in contracted
    assert "three leaves use tsavorite treatment" in contracted
    assert "Alternate the treatments one whole leaf at a time" in contracted
    assert "same material phase and order" in contracted
    assert "include its mirrored counterpart" in contracted
    assert "keep unrelated ruby motifs and unmarked details fixed" in contracted


def test_three_leaves_each_side_is_the_same_six_leaf_pattern_contract() -> None:
    designer_words = (
        "Add leaf design surrounding the ruby, 3 leaves each side; small "
        "white diamonds and the other half green tsavorites."
    )

    assert requests_six_leaf_ruby_pattern(designer_words) is True
    contracted = with_jewelry_symmetry_contract(designer_words)
    assert SIX_LEAF_RUBY_PATTERN_CONTRACT in contracted
    assert "six discrete leaves total" in contracted
    assert "same material phase and order" in contracted


def test_unrelated_leaf_prompt_does_not_gain_six_leaf_material_rules() -> None:
    contracted = with_jewelry_symmetry_contract(
        "A ruby necklace with four polished gold leaves"
    )

    assert SIX_LEAF_RUBY_PATTERN_CONTRACT not in contracted


def test_unrequested_left_right_mismatch_is_a_hard_failure() -> None:
    plan, report = _report(False)

    assert report.verdict is QualityVerdict.FAIL
    symmetry = next(
        check for check in report.checks if check.code == "jewelry_symmetry"
    )
    assert symmetry.passed is False
    assert symmetry.severity.value == "hard"
    assert symmetry.evidence["observed"] is False
    assert "gold and pave leaf sequence" in symmetry.evidence["observations"][0]

    _prompt, correction = compile_correction_prompt(plan, plan.intent, report)
    assert "jewelry_symmetry" in correction


def test_necklace_pair_evidence_vetoes_a_coarse_symmetry_pass() -> None:
    instruction = with_jewelry_symmetry_contract(
        "A ruby necklace with alternating gold and pave leaf links"
    )
    plan = build_image_plan(ImageOperation.CREATIVE_GENERATE, instruction)
    inspection = _inspection(
        True,
        "the necklace appears balanced overall",
        necklace_audits=(NecklaceSymmetryAudit(
            expectation="bilateral",
            centerline_anchor="center ruby pendant",
            complete_piece_assessable=True,
            left_count=1,
            right_count=1,
            pair_audits=(NecklaceSymmetryPairAudit(
                position_from_center=1,
                left_component="full-pave gold leaf",
                right_component="half-pave gold leaf",
                motif_order_matches=True,
                orientation_matches=True,
                spacing_matches=True,
                scale_matches=True,
                metal_treatment_matches=True,
                pave_coverage_matches=False,
                gemstone_treatment_matches=True,
                connection_type_matches=True,
                observation="corresponding leaves have different pave coverage",
            ),),
            unrequested_differences_absent=True,
        ),),
    )
    report = RingQualityEvaluator(
        prompt_creative_inspector=_Inspector(inspection),
        require_cross_inspection=False,
        require_render_cross_inspection=False,
    ).evaluate(plan, _png(), source_image=None, mask_bytes=None)

    assert report.verdict is QualityVerdict.FAIL
    by_code = {check.code: check for check in report.checks}
    assert by_code["jewelry_symmetry"].passed is True
    assert by_code["necklace_sequence_symmetry"].passed is False
    assert any(
        "mismatched pave_coverage" in reason
        for reason in by_code["necklace_sequence_symmetry"].evidence["reasons"]
    )


def test_missing_symmetry_evidence_fails_closed() -> None:
    _plan, report = _report(None)

    assert report.verdict is QualityVerdict.FAIL
    symmetry = next(
        check for check in report.checks if check.code == "jewelry_symmetry"
    )
    assert symmetry.passed is False
    assert symmetry.severity.value == "hard"


def test_verified_symmetry_remains_review_only_not_factory_truth() -> None:
    _plan, report = _report(True)

    assert report.verdict is QualityVerdict.WARN
    symmetry = next(
        check for check in report.checks if check.code == "jewelry_symmetry"
    )
    assert symmetry.passed is True
    assert any(check.code == "factory_authority" for check in report.checks)


def test_explicit_asymmetry_is_required_rather_than_silently_mirrored() -> None:
    instruction = (
        "An intentionally asymmetric necklace: three ruby leaves on the left "
        "and one long diamond branch on the right"
    )

    _plan, honored = _report(
        True,
        instruction,
        "the candidate retains three left leaves and one right branch",
    )
    _plan, silently_mirrored = _report(
        False,
        instruction,
        "the candidate duplicated the left leaves onto the right side",
    )

    honored_check = next(
        check for check in honored.checks if check.code == "jewelry_symmetry"
    )
    mirrored_check = next(
        check
        for check in silently_mirrored.checks
        if check.code == "jewelry_symmetry"
    )
    assert honored.verdict is QualityVerdict.WARN
    assert honored_check.passed is True
    assert silently_mirrored.verdict is QualityVerdict.FAIL
    assert mirrored_check.passed is False
    assert "duplicated the left leaves" in mirrored_check.evidence["observations"][0]


def test_visibly_asymmetric_identity_source_remains_authoritative() -> None:
    _plan, preserved = _source_report(True)
    _plan, overwritten = _source_report(False)

    preserved_check = next(
        check for check in preserved.checks if check.code == "jewelry_symmetry"
    )
    overwritten_check = next(
        check for check in overwritten.checks if check.code == "jewelry_symmetry"
    )
    assert preserved.verdict is QualityVerdict.WARN
    assert preserved_check.passed is True
    assert preserved_check.evidence[
        "identity_source_or_explicit_asymmetry_may_override"
    ] is True
    assert overwritten.verdict is QualityVerdict.FAIL
    assert overwritten_check.passed is False


def test_irregular_bracelet_or_band_sequence_fails_the_radial_gate() -> None:
    _plan, report = _report(
        False,
        "A bracelet alternating one emerald bezel with two polished gold links",
        "one interval has three gold links and the radial spacing is uneven",
    )

    symmetry = next(
        check for check in report.checks if check.code == "jewelry_symmetry"
    )
    assert report.verdict is QualityVerdict.FAIL
    assert symmetry.passed is False
    assert "radial spacing is uneven" in symmetry.evidence["observations"][0]
    assert "bracelets, bands, and radial designs" in JEWELRY_SYMMETRY_CONTRACT
    assert "repeated sequence and spacing regular" in JEWELRY_SYMMETRY_CONTRACT


def test_earring_pairs_support_matching_or_requested_handed_construction() -> None:
    matching_instruction = "A matching pair of diamond drop earrings"
    handed_instruction = (
        "A deliberately mirrored handed pair of vine earrings, one curving "
        "toward each cheek"
    )

    _plan, matching = _report(
        True,
        matching_instruction,
        "both earrings use the same stones, settings, and drop construction",
    )
    _plan, handed = _report(
        True,
        handed_instruction,
        "the same construction is mirrored into left- and right-handed curves",
    )
    _plan, handed_lost = _report(
        False,
        handed_instruction,
        "both earrings curve in the same direction instead of toward each cheek",
    )

    assert matching.verdict is QualityVerdict.WARN
    assert handed.verdict is QualityVerdict.WARN
    assert handed_lost.verdict is QualityVerdict.FAIL
    assert "mirrored handed pair is requested" in JEWELRY_SYMMETRY_CONTRACT

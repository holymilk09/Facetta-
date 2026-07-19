"""Provider-free six-leaf ruby motif contract tests."""

from __future__ import annotations

from facetta.creative_symmetry import with_jewelry_symmetry_contract
from facetta.image_agent import (
    NecklaceSymmetryAudit,
    NecklaceSymmetryPairAudit,
    SixLeafRubyPatternAudit,
)
from facetta.ruby_leaf_pattern import (
    canonical_six_leaf_coverage_audits,
    evaluate_six_leaf_ruby_pattern_audits,
)


PATTERN_INTENT = with_jewelry_symmetry_contract(
    "Each ruby motif has 6 leaves, half white diamonds and half tsavorite, "
    "in an alternating pattern."
)
ALTERNATING = (
    "diamond", "tsavorite", "diamond", "tsavorite", "diamond", "tsavorite",
)


def _motif(**updates: object) -> SixLeafRubyPatternAudit:
    values: dict[str, object] = {
        "side": "left",
        "position_from_center": 1,
        "ruby_component": "first ruby floral motif",
        "complete_motif_assessable": True,
        "leaf_count": 6,
        "diamond_leaf_count": 3,
        "tsavorite_leaf_count": 3,
        "material_sequence": ALTERNATING,
        "whole_leaf_treatments": True,
        "observation": "six whole leaves inventoried from the centerline-facing leaf",
    }
    values.update(updates)
    return SixLeafRubyPatternAudit.model_validate(values)


def _pair_audit() -> NecklaceSymmetryAudit:
    return NecklaceSymmetryAudit(
        expectation="bilateral",
        centerline_anchor="center ruby",
        complete_piece_assessable=True,
        left_count=1,
        right_count=1,
        pair_audits=(NecklaceSymmetryPairAudit(
            position_from_center=1,
            left_component="left ruby floral leaf motif",
            right_component="right ruby floral leaf motif",
            motif_order_matches=True,
            orientation_matches=True,
            spacing_matches=True,
            scale_matches=True,
            metal_treatment_matches=True,
            pave_coverage_matches=True,
            gemstone_treatment_matches=True,
            connection_type_matches=True,
            observation="paired ruby leaf motifs",
        ),),
        unrequested_differences_absent=True,
    )


def _evaluate(*audits: SixLeafRubyPatternAudit):
    return evaluate_six_leaf_ruby_pattern_audits(
        PATTERN_INTENT,
        audits,
        necklace_audits=(_pair_audit(),),
    )


def test_six_leaf_pattern_requires_structured_motif_evidence():
    result = _evaluate()

    assert result.applicable is True
    assert result.passed is False
    assert result.reasons == ("structured six-leaf ruby motif audit is missing",)


def test_adjacent_same_material_leaves_fail_even_with_three_of_each():
    non_alternating = (
        "diamond", "diamond", "tsavorite", "diamond", "tsavorite", "tsavorite",
    )
    result = _evaluate(
        _motif(material_sequence=non_alternating),
        _motif(side="right", material_sequence=non_alternating),
    )

    assert result.passed is False
    assert any("not cyclically alternating" in reason for reason in result.reasons)


def test_six_leaf_pattern_requires_exact_leaf_and_material_counts():
    result = _evaluate(
        _motif(leaf_count=5, diamond_leaf_count=2),
        _motif(side="right"),
    )

    assert result.passed is False
    assert any("5 leaves instead of 6" in reason for reason in result.reasons)
    assert any("2 diamond leaves instead of 3" in reason for reason in result.reasons)


def test_corresponding_motifs_require_the_same_mirrored_material_phase():
    shifted = ALTERNATING[1:] + ALTERNATING[:1]
    result = _evaluate(
        _motif(),
        _motif(side="right", material_sequence=shifted),
    )

    assert result.passed is False
    assert any("same mirrored material phase" in reason for reason in result.reasons)


def test_complete_alternating_pair_passes():
    result = _evaluate(_motif(), _motif(side="right"))

    assert result.passed is True
    assert result.reasons == ()


def test_incidental_ruby_accent_beside_leaf_links_is_not_a_six_leaf_motif():
    incidental = _pair_audit().model_copy(update={
        "pair_audits": (_pair_audit().pair_audits[0].model_copy(update={
            "position_from_center": 1,
            "left_component": "small ruby accent followed by two leaf links",
            "right_component": "small ruby accent followed by two leaf links",
        }),),
    })
    result = evaluate_six_leaf_ruby_pattern_audits(
        PATTERN_INTENT,
        (
            _motif(position_from_center=3),
            _motif(side="right", position_from_center=3),
        ),
        necklace_audits=(incidental,),
    )

    assert result.passed is True
    assert result.reasons == ()


def test_invalid_incidental_rows_do_not_override_governed_floral_pairs():
    invalid_incidental = _motif(
        position_from_center=2,
        ruby_component="small ruby accent beside two ordinary leaf links",
        leaf_count=2,
        diamond_leaf_count=1,
        tsavorite_leaf_count=1,
        material_sequence=("diamond", "tsavorite"),
    )
    result = _evaluate(
        _motif(),
        _motif(side="right"),
        invalid_incidental,
        invalid_incidental.model_copy(update={"side": "right"}),
    )

    assert result.passed is True
    assert result.audit_count == 2
    assert result.reasons == ()


def test_independent_necklace_audits_do_not_union_local_motif_positions():
    primary = _pair_audit()
    skeptical_pair = primary.pair_audits[0].model_copy(update={
        "position_from_center": 2,
        "left_component": "second ruby floral motif",
        "right_component": "second ruby floral motif",
    })
    skeptical = primary.model_copy(update={
        "left_count": 2,
        "right_count": 2,
        "pair_audits": (
            primary.pair_audits[0],
            skeptical_pair,
        ),
    })

    selected = canonical_six_leaf_coverage_audits((primary, skeptical))
    result = evaluate_six_leaf_ruby_pattern_audits(
        PATTERN_INTENT,
        (_motif(), _motif(side="right")),
        necklace_audits=(primary, skeptical),
    )

    assert selected == (primary,)
    assert result.passed is True
    assert result.reasons == ()


def test_necklace_inventory_requires_both_motif_sides():
    result = _evaluate(_motif())

    assert result.passed is False
    assert any("missing a left or right audit" in reason for reason in result.reasons)

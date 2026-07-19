"""Provider-free necklace sequence symmetry contract tests."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from facetta.creative_symmetry import with_jewelry_symmetry_contract
from facetta.image_agent import NecklaceSymmetryAudit, NecklaceSymmetryPairAudit
from facetta.image_agent.quality import (
    _normalize_authorized_necklace_differences,
)
from facetta.necklace_symmetry import evaluate_necklace_symmetry_audits


def _pair(**updates: object) -> NecklaceSymmetryPairAudit:
    values: dict[str, object] = {
        "position_from_center": 1,
        "left_component": "yellow-gold leaf with full diamond pave",
        "right_component": "yellow-gold leaf with full diamond pave",
        "motif_order_matches": True,
        "orientation_matches": True,
        "spacing_matches": True,
        "scale_matches": True,
        "metal_treatment_matches": True,
        "pave_coverage_matches": True,
        "gemstone_treatment_matches": True,
        "connection_type_matches": True,
        "authorized_differences": (),
        "observation": "first leaf pair matches beside the center ruby",
    }
    values.update(updates)
    return NecklaceSymmetryPairAudit.model_validate(values)


def _audit(**updates: object) -> NecklaceSymmetryAudit:
    values: dict[str, object] = {
        "expectation": "bilateral",
        "centerline_anchor": "pear ruby pendant and central connector",
        "complete_piece_assessable": True,
        "left_count": 1,
        "right_count": 1,
        "pair_audits": (_pair(),),
        "unpaired_left": (),
        "unpaired_right": (),
        "unpaired_elements_authorized": False,
        "requested_asymmetry_preserved": None,
        "unrequested_differences_absent": True,
    }
    values.update(updates)
    return NecklaceSymmetryAudit.model_validate(values)


def _evaluate(
    instruction: str,
    audit: NecklaceSymmetryAudit | None,
    *,
    source_present: bool = False,
):
    return evaluate_necklace_symmetry_audits(
        with_jewelry_symmetry_contract(instruction),
        (() if audit is None else (audit,)),
        source_present=source_present,
    )


def test_bilateral_necklace_requires_structured_center_outward_evidence():
    result = _evaluate("A ruby and diamond necklace", None)

    assert result.applicable is True
    assert result.passed is False
    assert result.reasons == (
        "structured center-outward necklace audit is missing",
    )


def test_visual_necklace_classification_requires_audit_without_text_cue():
    result = evaluate_necklace_symmetry_audits(
        with_jewelry_symmetry_contract(
            "Make the left and right sides match link by link."
        ),
        (),
        source_present=True,
        observed_jewelry_type="necklace",
    )

    assert result.applicable is True
    assert result.passed is False
    assert result.reasons == (
        "structured center-outward necklace audit is missing",
    )


def test_necklace_symmetry_module_imports_without_image_agent_cycle():
    source_root = Path(__file__).resolve().parents[1] / "src"
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                f"import sys; sys.path.insert(0, {str(source_root)!r}); "
                "import facetta.necklace_symmetry"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_bilateral_necklace_rejects_full_gold_vs_half_pave_mismatch():
    result = _evaluate(
        "A ruby necklace with alternating gold and diamond leaf links",
        _audit(pair_audits=(_pair(
            right_component="yellow-gold leaf with half diamond pave",
            pave_coverage_matches=False,
            observation="left leaf is fully pave but right leaf is half pave",
        ),)),
    )

    assert result.passed is False
    assert any("mismatched pave_coverage" in reason for reason in result.reasons)


def test_bilateral_necklace_requires_complete_ordered_pair_inventory():
    result = _evaluate(
        "A bilaterally balanced sapphire necklace",
        _audit(left_count=2, right_count=2, pair_audits=(_pair(),)),
    )

    assert result.passed is False
    assert any("does not cover" in reason for reason in result.reasons)


def test_six_leaf_ruby_pattern_accepts_matching_left_right_material_phase():
    sequence = (
        "ruby with six leaves clockwise: diamond, tsavorite, diamond, "
        "tsavorite, diamond, tsavorite"
    )
    result = _evaluate(
        "Surrounding each ruby on the necklace is 6 leaves, half white "
        "diamonds and half tsavorite, so it's a pattern",
        _audit(pair_audits=(_pair(
            left_component=sequence,
            right_component=sequence,
            observation=(
                "corresponding ruby motifs have the same alternating "
                "diamond-tsavorite phase"
            ),
        ),)),
    )

    assert result.passed is True


def test_six_leaf_ruby_pattern_rejects_swapped_material_phase_on_one_side():
    result = _evaluate(
        "Surrounding each ruby on the necklace is 6 leaves, half white "
        "diamonds and half tsavorite, so it's a pattern",
        _audit(pair_audits=(_pair(
            left_component=(
                "ruby leaves clockwise: diamond, tsavorite, diamond, "
                "tsavorite, diamond, tsavorite"
            ),
            right_component=(
                "ruby leaves clockwise: tsavorite, diamond, tsavorite, "
                "diamond, tsavorite, diamond"
            ),
            motif_order_matches=False,
            gemstone_treatment_matches=False,
            observation=(
                "right ruby motif starts with tsavorite where its paired "
                "left motif starts with diamond"
            ),
        ),)),
    )

    assert result.passed is False
    assert any("mismatched motif_order" in reason for reason in result.reasons)
    assert any(
        "mismatched gemstone_treatment" in reason
        for reason in result.reasons
    )


def test_intentional_asymmetry_preserves_only_authorized_differences():
    result = _evaluate(
        "An intentionally asymmetric necklace with a ruby leaf on the left "
        "and a diamond branch on the right",
        _audit(
            expectation="explicit_asymmetry",
            pair_audits=(_pair(
                right_component="diamond branch",
                motif_order_matches=False,
                gemstone_treatment_matches=False,
                authorized_differences=(
                    "motif_order",
                    "gemstone_treatment",
                ),
                observation="requested ruby leaf differs from diamond branch",
            ),),
            requested_asymmetry_preserved=True,
        ),
    )

    assert result.passed is True


def test_unrequested_asymmetry_cannot_self_authorize_from_candidate():
    result = _evaluate(
        "A ruby and diamond necklace",
        _audit(
            expectation="explicit_asymmetry",
            pair_audits=(_pair(
                pave_coverage_matches=False,
                authorized_differences=("pave_coverage",),
            ),),
            requested_asymmetry_preserved=True,
        ),
    )

    assert result.passed is False
    assert any("not requested" in reason for reason in result.reasons)


def test_negated_asymmetry_keeps_bilateral_symmetry_as_the_default():
    result = _evaluate(
        "A ruby necklace that is not asymmetric",
        _audit(
            expectation="explicit_asymmetry",
            pair_audits=(_pair(
                pave_coverage_matches=False,
                authorized_differences=("pave_coverage",),
            ),),
            requested_asymmetry_preserved=True,
        ),
    )

    assert result.passed is False
    assert any("not requested" in reason for reason in result.reasons)


def test_source_asymmetry_requires_an_identity_source():
    audit = _audit(
        expectation="source_asymmetry",
        pair_audits=(_pair(
            motif_order_matches=False,
            authorized_differences=("motif_order",),
        ),),
        requested_asymmetry_preserved=True,
    )

    assert _evaluate(
        "Render this necklace faithfully",
        audit,
        source_present=True,
    ).passed is True
    without_source = _evaluate(
        "Render this necklace faithfully",
        audit,
        source_present=False,
    )
    assert without_source.passed is False
    assert any("no identity source" in reason for reason in without_source.reasons)


def test_one_unambiguous_prose_authorization_maps_to_typed_dimension():
    payload = {
        "necklace_symmetry_audits": [{
            "pair_audits": [{
                "authorized_differences": [
                    "upper-right tsavorite leaf changed to deeper emerald green",
                ],
            }],
        }],
    }

    normalized = _normalize_authorized_necklace_differences(payload)

    assert normalized["necklace_symmetry_audits"][0]["pair_audits"][0][
        "authorized_differences"
    ] == ["gemstone_treatment"]


def test_ambiguous_prose_authorization_stays_invalid_and_fail_closed():
    prose = "change the gemstone color and size"
    payload = {
        "necklace_symmetry_audits": [{
            "pair_audits": [{"authorized_differences": [prose]}],
        }],
    }

    normalized = _normalize_authorized_necklace_differences(payload)

    assert normalized["necklace_symmetry_audits"][0]["pair_audits"][0][
        "authorized_differences"
    ] == [prose]


def test_provider_free_fixture_set_is_contract_only_not_external_quality():
    path = (
        Path(__file__).resolve().parents[1]
        / "docs/evals/necklace-symmetry-contract-v1/cases.json"
    )
    fixture = json.loads(path.read_text())

    assert fixture["evidence_status"] == "contract_only"
    assert fixture["external_quality_status"] == "not_run"
    assert fixture["provider_calls"] == 0
    assert {case["expected_pass"] for case in fixture["cases"]} == {True, False}

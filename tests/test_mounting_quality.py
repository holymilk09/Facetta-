from __future__ import annotations

import pytest

from facetta.image_agent import ImageOperation, build_image_plan
from facetta.image_agent.contracts import CheckSeverity, QualityVerdict
from facetta.image_agent.mounting_quality import MountingViewQualityEvaluator


SOURCE = b"approved-source"
CANDIDATE = b"mounting-candidate"


def _plan():
    plan = build_image_plan(
        ImageOperation.REFERENCE_RENDER,
        "Create plan, front, side, and true section mounting views",
        source_image=SOURCE,
    )
    return plan.model_copy(update={
        "normalized_intent": {
            **plan.normalized_intent,
            "mounting_hardware": {
                "required_views": ["plan", "front", "side", "section"],
            },
        },
        "spec_facts": {
            "jewelry_type": "ring",
            "stone": {"cut": "cushion", "species": "ruby"},
            "setting": {"style": "prong_halo", "prong_count": 6},
            "side_stones": [{"position": "halo", "count": 20}],
        },
    })


def _candidate_pass() -> dict:
    return {
        "checked": True,
        "projections": [
            {"projection": name, "present": True}
            for name in ("plan", "front", "side", "section")
        ],
        "hardware_continuity": True,
        "interpenetration_detected": False,
        "text_or_dimensions_detected": False,
        "complete_piece_visible": True,
        "section": {
            "panel_present": True,
            "center_axis_cut": True,
            "stone_cross_section_visible": True,
            "seat_or_bearing_visible": True,
            "pavilion_clearance_visible": True,
            "cut_metal_surfaces_visible": True,
            "exterior_elevation_only": False,
            "evidence": ["cut passes through stone, seat, and gallery"],
        },
        "score": 96,
        "notes": ["all four views are structurally legible"],
    }


def _fidelity_pass() -> dict:
    return {
        "checked": True,
        "center_shape_matches_source": True,
        "center_shape_matches_spec": True,
        "center_visual_identity_matches_spec": True,
        "major_components_match": True,
        "stone_count_matches": True,
        "prong_count_matches": True,
        "score": 94,
        "notes": ["cushion center and six-prong halo remain faithful"],
    }


def _evaluator(candidate: dict | None = None, fidelity: dict | None = None):
    candidate_result = candidate or _candidate_pass()
    fidelity_result = fidelity or _fidelity_pass()
    return MountingViewQualityEvaluator(
        candidate_audit=lambda _plan, _image: candidate_result,
        fidelity_audit=lambda _plan, _source, _image: fidelity_result,
    )


def _evaluate(evaluator: MountingViewQualityEvaluator):
    return evaluator.evaluate(
        _plan(),
        CANDIDATE,
        source_image=SOURCE,
        mask_bytes=None,
    )


def _check(report, code: str):
    return next(item for item in report.checks if item.code == code)


def test_visual_pass_remains_designer_review_only_for_factory_authority():
    report = _evaluate(_evaluator())

    assert report.verdict is QualityVerdict.WARN
    assert report.score == 94
    assert all(
        check.passed
        for check in report.checks
        if check.severity is CheckSeverity.HARD
    )
    authority = _check(report, "factory_authority")
    assert authority.passed is False
    assert authority.severity is CheckSeverity.WARNING
    assert authority.evidence == {
        "factory_authoritative": False,
        "designer_confirmation_required": True,
    }


def test_missing_requested_section_is_a_hard_failure():
    candidate = _candidate_pass()
    candidate["projections"] = [
        row for row in candidate["projections"]
        if row["projection"] != "section"
    ]
    candidate["section"] = {
        "panel_present": False,
        "center_axis_cut": False,
        "stone_cross_section_visible": False,
        "seat_or_bearing_visible": False,
        "pavilion_clearance_visible": False,
        "cut_metal_surfaces_visible": False,
        "exterior_elevation_only": None,
    }

    report = _evaluate(_evaluator(candidate=candidate))

    assert report.verdict is QualityVerdict.FAIL
    assert _check(report, "mounting:requested_projections").passed is False
    section = _check(report, "mounting:true_section")
    assert section.passed is False
    assert section.severity is CheckSeverity.HARD


def test_exterior_elevation_cannot_pass_as_true_section():
    candidate = _candidate_pass()
    candidate["section"] = {
        "panel_present": True,
        "center_axis_cut": False,
        "stone_cross_section_visible": False,
        "seat_or_bearing_visible": True,
        "pavilion_clearance_visible": True,
        "cut_metal_surfaces_visible": False,
        "exterior_elevation_only": True,
        "evidence": ["panel is another exterior side elevation"],
    }

    report = _evaluate(_evaluator(candidate=candidate))

    assert report.verdict is QualityVerdict.FAIL
    section = _check(report, "mounting:true_section")
    assert section.passed is False
    assert section.evidence["exterior_elevation_only"] is True


def test_center_shape_drift_is_a_hard_failure():
    fidelity = _fidelity_pass()
    fidelity.update({
        "center_shape_matches_source": False,
        "center_shape_matches_spec": False,
        "differences": ["source/spec cushion center became oval in plan"],
    })

    report = _evaluate(_evaluator(fidelity=fidelity))

    assert report.verdict is QualityVerdict.FAIL
    center = _check(report, "mounting:center_identity")
    assert center.passed is False
    assert center.severity is CheckSeverity.HARD
    assert center.evidence["center_shape_matches_source"] is False


@pytest.mark.parametrize(
    "candidate_update",
    [
        {"hardware_continuity": False, "interpenetration_detected": False},
        {"hardware_continuity": True, "interpenetration_detected": True},
    ],
)
def test_disconnected_hardware_or_metal_through_stone_is_hard_failure(
    candidate_update: dict,
):
    candidate = _candidate_pass()
    candidate.update(candidate_update)

    report = _evaluate(_evaluator(candidate=candidate))

    assert report.verdict is QualityVerdict.FAIL
    hardware = _check(report, "mounting:hardware_continuity")
    assert hardware.passed is False
    assert hardware.severity is CheckSeverity.HARD


def test_component_or_count_drift_is_a_hard_failure():
    fidelity = _fidelity_pass()
    fidelity.update({
        "stone_count_matches": False,
        "prong_count_matches": False,
        "differences": ["candidate changed halo and center-prong counts"],
    })

    report = _evaluate(_evaluator(fidelity=fidelity))

    assert report.verdict is QualityVerdict.FAIL
    check = _check(report, "mounting:component_count_fidelity")
    assert check.passed is False
    assert check.evidence["stone_count_matches"] is False


def test_model_authored_dimensions_and_crop_are_hard_failures():
    candidate = _candidate_pass()
    candidate.update({
        "text_or_dimensions_detected": True,
        "complete_piece_visible": False,
    })

    report = _evaluate(_evaluator(candidate=candidate))

    assert report.verdict is QualityVerdict.FAIL
    assert _check(report, "mounting:no_text_or_dimensions").passed is False
    assert _check(report, "mounting:complete_uncropped_piece").passed is False


def test_null_observation_is_a_warning_not_a_visual_pass():
    fidelity = _fidelity_pass()
    fidelity["center_shape_matches_source"] = None

    report = _evaluate(_evaluator(fidelity=fidelity))

    assert report.verdict is QualityVerdict.WARN
    center = _check(report, "mounting:center_identity")
    assert center.passed is False
    assert center.severity is CheckSeverity.WARNING


def test_audit_unavailable_holds_candidate_for_review():
    def unavailable(*_args):
        raise RuntimeError("vision transport unavailable")

    evaluator = MountingViewQualityEvaluator(
        candidate_audit=unavailable,
        fidelity_audit=unavailable,
    )

    report = _evaluate(evaluator)

    assert report.verdict is QualityVerdict.WARN
    assert _check(
        report, "mounting:candidate_audit_unavailable"
    ).severity is CheckSeverity.WARNING
    assert _check(
        report, "mounting:fidelity_audit_unavailable"
    ).severity is CheckSeverity.WARNING
    assert all(
        check.severity is CheckSeverity.WARNING
        for check in report.failed_checks
    )

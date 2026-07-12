"""Category-safe image-agent contracts for necklace chain-style edits."""

from __future__ import annotations

import io
from copy import deepcopy

import pytest
from PIL import Image

from conftest import HALO_SPEC, NECKLACE_SPEC
from facetta.image_agent import (
    ChainStyleEditInspection,
    CheckSeverity,
    DesignerEditDomain,
    EditInspection,
    GrokSkepticalEditInspector,
    GrokVisionInspector,
    ImageOperation,
    ImagePlanValidationError,
    QualityVerdict,
    RingQualityEvaluator,
    build_image_plan,
)
from facetta.image_agent.prompts import (
    MAX_PROVIDER_PROMPT_CHARS,
    compile_initial_prompt,
)
from facetta.spec import Spec


def _png(color: tuple[int, int, int]) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (96, 96), color).save(output, format="PNG")
    return output.getvalue()


def _specs() -> tuple[Spec, Spec]:
    source = Spec.model_validate(deepcopy(NECKLACE_SPEC))
    target = source.model_copy(deep=True)
    assert source.chain is not None and target.chain is not None
    target.chain.style = "curb"
    return source, target


def _plan():
    source, target = _specs()
    return build_image_plan(
        ImageOperation.LOCAL_EDIT,
        "change the complete necklace chain from cable to curb",
        spec=target,
        source_spec=source,
        source_image=_png((20, 20, 20)),
        region_description=(
            "the complete visible chain-link run only, excluding pendant, "
            "bail, stones, setting, and clasp"
        ),
    )


def _faithful_chain_inspection(**updates: bool | None) -> ChainStyleEditInspection:
    facts: dict[str, bool | None] = {
        "target_style_matches": True,
        "complete_visible_run_matches": True,
        "chain_connections_preserved": True,
        "pendant_count_preserved": True,
        "pendant_geometry_preserved": True,
        "bail_preserved": True,
        "stones_preserved": True,
        "setting_preserved": True,
        "clasp_preserved": True,
        "source_clasp_visible": False,
        "candidate_clasp_visible": False,
        "chain_length_and_drape_preserved": True,
        "non_chain_geometry_preserved": True,
        "candidate_contains_non_jewelry_text_or_branding": False,
    }
    facts.update(updates)
    return ChainStyleEditInspection(**facts)


def _edit(chain_style: ChainStyleEditInspection | None, **updates) -> EditInspection:
    facts = {
        "change_applied": True,
        "unintended_severity": "none",
        "protected_regions_preserved": True,
        "geometry_preserved": True,
        "spec_change_matches": True,
        "domain_matches": {"chain_style": True},
        "chain_style": chain_style,
        "text_or_branding_detected": False,
        "score": 96,
    }
    facts.update(updates)
    return EditInspection(**facts)


class _StaticInspector:
    def __init__(self, inspection: EditInspection):
        self.inspection = inspection

    def inspect_edit(self, plan, reference, candidate):
        return self.inspection

    def inspect_render(self, plan, candidate, *, reference):
        raise AssertionError("necklace chain LOCAL_EDIT must use edit inspection")


class _ExplodingRingRenderCrossInspector:
    calls = 0

    def inspect_render(self, plan, candidate):
        self.calls += 1
        raise AssertionError("ring target-spec crosscheck must not run for a necklace")


def _evaluate(inspection: EditInspection, *, render_cross=None):
    source = _png((20, 20, 20))
    plan = _plan()
    evaluator = RingQualityEvaluator(
        _StaticInspector(inspection),
        require_cross_inspection=False,
        render_cross_inspector=render_cross,
        require_render_cross_inspection=False,
    )
    return plan, evaluator.evaluate(
        plan,
        _png((40, 40, 40)),
        source_image=source,
        mask_bytes=None,
    )


def test_necklace_chain_plan_is_exactly_scoped_and_prompted_end_to_end():
    plan = _plan()
    prompt = compile_initial_prompt(plan)

    assert plan.jewelry_type == "necklace"
    assert plan.prompt_version == "local-edit.v8"
    assert plan.edit_domains == (DesignerEditDomain.CHAIN_STYLE,)
    assert [change["path"] for change in plan.normalized_intent["spec_delta"]] == [
        "chain.style"
    ]
    frozen = " ".join(plan.frozen).lower()
    for required in (
        "pendant count",
        "bail geometry",
        "gemstone identity",
        "setting",
        "clasp type",
        "chain length",
        "non-chain jewelry geometry",
        "invented branding",
    ):
        assert required in frozen
    assert "COMPLETE VISIBLE CHAIN RUN" in prompt
    assert "every visible segment and every link" in prompt
    assert "Do not leave a cable-chain segment mixed" in prompt
    assert "Add or remove no pendant" in prompt
    assert "cannot prove exact link gauge" in prompt
    assert "same camera angle" in prompt
    assert "do not reveal or invent one" in prompt
    assert "remove it cleanly" in prompt
    assert "shank shape" not in prompt
    assert len(prompt) < MAX_PROVIDER_PROMPT_CHARS
    assert "dimension_provenance" not in prompt
    assert "source_component_coverage" not in prompt


def test_chain_production_reference_persists_outside_visual_plan_and_cache():
    source_raw = deepcopy(NECKLACE_SPEC)
    source_raw["chain"]["production"] = {
        "mode": "stock",
        "reference_kind": "supplier_sku",
        "reference": "SOURCE-CABLE",
    }
    source = Spec.model_validate(source_raw)
    first = source.model_copy(deep=True)
    second = source.model_copy(deep=True)
    assert first.chain is not None and second.chain is not None
    first.chain.style = second.chain.style = "curb"
    first.chain.production.reference = "TARGET-CURB-A"
    second.chain.production.reference = "TARGET-CURB-B"
    image = _png((20, 20, 20))

    plan_a = build_image_plan(
        ImageOperation.LOCAL_EDIT,
        "change the complete necklace chain from cable to curb",
        spec=first,
        source_spec=source,
        source_image=image,
        region_description="complete visible chain run",
    )
    plan_b = build_image_plan(
        ImageOperation.LOCAL_EDIT,
        "change the complete necklace chain from cable to curb",
        spec=second,
        source_spec=source,
        source_image=image,
        region_description="complete visible chain run",
    )

    assert plan_a.spec_visual_hash == plan_b.spec_visual_hash
    assert plan_a.input_hash == plan_b.input_hash
    assert "production" not in plan_a.spec_facts["chain"]
    assert "production" not in plan_a.source_spec_facts["chain"]
    assert not any(
        change["path"].startswith("chain.production")
        for change in plan_a.normalized_intent["spec_delta"]
    )
    assert "TARGET-CURB-A" not in compile_initial_prompt(plan_a)


def test_necklace_support_rejects_every_operation_or_delta_beyond_chain_style():
    source, target = _specs()
    image = _png((20, 20, 20))

    with pytest.raises(ImagePlanValidationError, match="limited to chain.style"):
        build_image_plan(ImageOperation.SPEC_RENDER, "render necklace", spec=target)
    with pytest.raises(ImagePlanValidationError, match="source specification"):
        build_image_plan(
            ImageOperation.LOCAL_EDIT,
            "change the chain",
            spec=target,
            source_image=image,
            region_description="complete chain run",
        )

    assert target.metal is not None
    target.metal.finish = "satin"
    with pytest.raises(
        ImagePlanValidationError,
        match="only chain geometry/production companion deltas",
    ):
        build_image_plan(
            ImageOperation.LOCAL_EDIT,
            "change chain and finish",
            spec=target,
            source_spec=source,
            source_image=image,
            region_description="complete chain run",
        )


def test_existing_ring_local_edit_contract_remains_supported():
    ring = Spec.model_validate(deepcopy(HALO_SPEC))
    plan = build_image_plan(
        ImageOperation.LOCAL_EDIT,
        "refine only the lower shank",
        spec=ring,
        source_image=_png((20, 20, 20)),
        region_description="lower shank",
    )

    assert plan.jewelry_type == "ring"
    assert plan.is_necklace_chain_style_edit is False


def test_faithful_chain_edit_is_reviewed_for_unprovable_link_dimensions():
    ring_cross = _ExplodingRingRenderCrossInspector()
    _, report = _evaluate(
        _edit(_faithful_chain_inspection()),
        render_cross=ring_cross,
    )

    assert ring_cross.calls == 0
    assert report.verdict is QualityVerdict.WARN
    failed = {check.code: check for check in report.failed_checks}
    assert set(failed) == {"exact_chain_dimensions"}
    dimensions = failed["exact_chain_dimensions"]
    assert dimensions.severity is CheckSeverity.WARNING
    assert dimensions.evidence["raster_dimensional_proof"] is False
    assert "designer review" in dimensions.message


@pytest.mark.parametrize(
    ("field", "check_code"),
    (
        ("target_style_matches", "chain_style_target"),
        ("complete_visible_run_matches", "chain_style_complete_run"),
        ("chain_connections_preserved", "chain_connections"),
        ("pendant_count_preserved", "pendant_count"),
        ("pendant_geometry_preserved", "pendant_geometry"),
        ("bail_preserved", "bail"),
        ("stones_preserved", "stones"),
        ("setting_preserved", "setting"),
        ("clasp_preserved", "clasp"),
        ("chain_length_and_drape_preserved", "chain_length_and_drape"),
        ("non_chain_geometry_preserved", "non_chain_geometry"),
    ),
)
def test_observed_chain_or_frozen_component_mismatch_is_a_hard_failure(
    field: str,
    check_code: str,
):
    _, report = _evaluate(_edit(_faithful_chain_inspection(**{field: False})))

    assert report.verdict is QualityVerdict.FAIL
    check = next(item for item in report.failed_checks if item.code == check_code)
    assert check.severity is CheckSeverity.HARD


def test_added_branding_is_a_hard_failure():
    _, report = _evaluate(_edit(
        _faithful_chain_inspection(),
        text_or_branding_detected=True,
    ))

    assert report.verdict is QualityVerdict.FAIL
    check = next(item for item in report.failed_checks
                 if item.code == "text_or_branding")
    assert check.severity is CheckSeverity.HARD


def test_retained_source_branding_is_an_absolute_candidate_hard_failure():
    _, report = _evaluate(_edit(_faithful_chain_inspection(
        candidate_contains_non_jewelry_text_or_branding=True,
    )))

    assert report.verdict is QualityVerdict.FAIL
    check = next(item for item in report.failed_checks
                 if item.code == "candidate_text_or_branding")
    assert check.severity is CheckSeverity.HARD
    assert "signature" in check.message


def test_newly_visible_clasp_is_an_added_component_hard_failure():
    _, report = _evaluate(_edit(_faithful_chain_inspection(
        source_clasp_visible=False,
        candidate_clasp_visible=True,
    )))

    assert report.verdict is QualityVerdict.FAIL
    check = next(item for item in report.failed_checks
                 if item.code == "clasp_visibility")
    assert check.severity is CheckSeverity.HARD
    assert check.evidence == {
        "source_clasp_visible": False,
        "candidate_clasp_visible": True,
    }


def test_uncertain_chain_semantics_remain_designer_reviewed():
    _, report = _evaluate(_edit(
        ChainStyleEditInspection(),
        text_or_branding_detected=None,
    ))

    assert report.verdict is QualityVerdict.WARN
    failed = {check.code: check for check in report.failed_checks}
    assert failed["chain_style_target"].severity is CheckSeverity.WARNING
    assert failed["chain_style_complete_run"].severity is CheckSeverity.WARNING
    assert failed["pendant_count"].severity is CheckSeverity.WARNING
    assert failed["text_or_branding"].severity is CheckSeverity.WARNING


def test_live_vision_contracts_are_category_specific(monkeypatch):
    plan = _plan()
    systems: list[str] = []

    def fake_pair(system, source, candidate, ask):
        systems.append(system)
        if "Return JSON only:\n{\"change_applied\"" in system and (
                "chain_style\"" in system):
            return _edit(_faithful_chain_inspection()).model_dump(mode="json")
        return {
            "checked": True,
            "change_applied": True,
            "frozen_facts_preserved": True,
            "unintended_severity": "none",
            "unintended_changes": [],
            "domain_mismatches": [],
            "notes": [],
        }

    monkeypatch.setattr("facetta.image_agent.quality.vision_json_pair", fake_pair)
    GrokVisionInspector().inspect_edit(
        plan, _png((20, 20, 20)), _png((40, 40, 40)))
    GrokSkepticalEditInspector().inspect_edit(
        plan, _png((20, 20, 20)), _png((40, 40, 40)))

    assert len(systems) == 2
    assert "same fine-jewelry necklace" in systems[0]
    assert "every visible chain segment and link" in systems[0]
    assert "Trace both visible chain" in systems[1]
    assert "runs link by link" in systems[1]
    assert "Any added/removed pendant" in systems[1]

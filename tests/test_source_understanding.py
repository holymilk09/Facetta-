"""Visible-only source understanding and deterministic prompt compilation."""

from __future__ import annotations

import pytest

from facetta.image_agent import (
    CheckSeverity,
    ImageOperation,
    ImageQualityReport,
    QualityCheck,
    QualityVerdict,
    build_image_plan,
)
from facetta.image_agent.prompts import (
    compile_correction_prompt,
    compile_initial_prompt,
)
from facetta.provider_errors import RenderUnavailable
from facetta import source_understanding as understanding
from facetta.source_understanding import (
    SourceVisibleFactsBrief,
    VisibleCenterStoneFacts,
    VisibleSideStoneFacts,
    compile_rough_drawing_intent_brief,
    compile_source_preservation_brief,
    requires_rough_drawing_interpretation,
)


def _brief(source_kind: str = "drawing") -> SourceVisibleFactsBrief:
    return SourceVisibleFactsBrief(
        source_kind=source_kind,
        category="ring",
        center_stone=VisibleCenterStoneFacts(
            shape_or_cut_family="oval",
            visible_color="green",
        ),
        visible_center_claw_or_prong_count=4,
        side_stones=VisibleSideStoneFacts(
            left_count=3,
            right_count=3,
            shape_or_cut_family="round",
        ),
        repeated_motifs=("three round shoulder stones on each side",),
        band_or_silhouette="slender continuous ring band",
        ambiguous_visible_details=("underside of center setting is occluded",),
    )


@pytest.mark.parametrize(
    ("source_kind", "handling_fragment"),
    [
        ("drawing", "Translate the drawing"),
        ("photograph", "photographed jewelry"),
        ("finished_render", "finished render's visible design identity"),
    ],
)
def test_source_kind_compiles_honest_visible_only_preservation_contract(
    source_kind: str,
    handling_fragment: str,
):
    compiled = compile_source_preservation_brief(_brief(source_kind))

    assert f"source kind: {source_kind}" in compiled
    assert handling_fragment in compiled
    assert "exactly 4 separately visible" in compiled
    assert "left=3; right=3" in compiled
    assert "Hidden, underside, off-frame, and internal construction: UNKNOWN" in compiled
    assert "NOT A SPECIFICATION" in compiled


def test_source_brief_is_present_in_first_and_corrective_prompts():
    preservation = compile_source_preservation_brief(_brief())
    instruction = (
        "Render this exact source in polished yellow gold.\n\n" + preservation
    )
    plan = build_image_plan(
        ImageOperation.REFERENCE_RENDER,
        instruction,
        source_image=b"source",
    )
    first = compile_initial_prompt(plan)
    report = ImageQualityReport(
        verdict=QualityVerdict.FAIL,
        checks=(QualityCheck(
            code="visible_components_preserved",
            passed=False,
            severity=CheckSeverity.HARD,
            message="visible shoulder stones changed",
        ),),
    )
    corrective, correction = compile_correction_prompt(plan, first, report)

    assert "Render this exact source in polished yellow gold" in first
    assert "left=3; right=3" in first
    assert "exactly 4 separately visible" in corrective
    assert "Hidden, underside, off-frame" in corrective
    assert "visible_components_preserved" in correction


def test_openai_inspection_is_typed_and_designer_source_kind_wins(monkeypatch):
    captured: dict[str, object] = {}

    def inspect(system: str, image: bytes, user_text: str) -> dict:
        captured.update(system=system, image=image, user_text=user_text)
        return {
            **_brief("drawing").model_dump(mode="json"),
            # The model cannot relabel a designer-declared source.
            "source_kind": "drawing",
        }

    monkeypatch.setattr(understanding, "openai_vision_json", inspect)
    result = understanding.inspect_source_visible_facts(
        b"finished-render", "finished_render"
    )

    assert result.source_kind == "finished_render"
    assert result.visible_center_claw_or_prong_count == 4
    assert captured["image"] == b"finished-render"
    assert "unknown_from_visible_source" in str(captured["system"])
    assert "FINISHED RENDER" in str(captured["user_text"])


def test_malformed_source_inspection_fails_closed(monkeypatch):
    monkeypatch.setattr(
        understanding,
        "openai_vision_json",
        lambda *_args: {
            "source_kind": "drawing",
            "category": "ring",
            "center_stone": {},
            "side_stones": {},
            "hidden_construction": "six-prong basket",
        },
    )

    with pytest.raises(RenderUnavailable, match="inspection was invalid"):
        understanding.inspect_source_visible_facts(b"source", "drawing")


def test_conservative_fallback_records_no_invented_visible_facts():
    result = understanding.conservative_source_visible_facts(
        b"source", "photograph"
    )

    assert result.source_kind == "photograph"
    assert result.category == "unknown"
    assert result.visible_center_claw_or_prong_count is None
    assert result.side_stones.left_count is None
    assert result.hidden_construction == "unknown_from_visible_source"


def test_all_designer_drawings_use_interpretive_qa_but_rendered_sources_do_not():
    unknown_drawing = understanding.conservative_source_visible_facts(
        b"source", "drawing"
    )
    sparse_drawing = SourceVisibleFactsBrief(
        source_kind="drawing",
        category="ring",
        center_stone=VisibleCenterStoneFacts(shape_or_cut_family="oval"),
        band_or_silhouette="one continuous ring outline",
    )

    assert requires_rough_drawing_interpretation(unknown_drawing) is True
    assert requires_rough_drawing_interpretation(sparse_drawing) is True
    assert requires_rough_drawing_interpretation(_brief("drawing")) is True
    assert requires_rough_drawing_interpretation(_brief("photograph")) is False
    assert requires_rough_drawing_interpretation(_brief("finished_render")) is False


def test_rough_drawing_fallback_is_creative_not_factory_authority():
    compiled = compile_rough_drawing_intent_brief()

    assert "designer's visual intent" in compiled
    assert "written instruction" in compiled
    assert "early sketch" in compiled
    assert "professional jewelry judgment" in compiled
    assert "do not demand literal pixel matching" in compiled
    assert "stone cut identity unless" in compiled
    assert "balanced symmetric jewelry design" in compiled
    assert "NOT A SPECIFICATION" in compiled
    assert "never a factory drawing" in compiled
    assert "production readiness" in compiled

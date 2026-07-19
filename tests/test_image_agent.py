"""Closed-loop image-agent tests use fake providers and QA only—never network."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import io
from pathlib import Path

import httpx
import pytest
from PIL import Image, ImageDraw

from conftest import HALO_SPEC
from facetta.image_agent import (
    CheckSeverity,
    ColoredLineArtQualityEvaluator,
    ConfirmedLineArtQualityEvaluator,
    CreativeRenderInspection,
    DesignerEditDomain,
    EditCrossInspection,
    EditInspection,
    EditSideStoneInventoryInspection,
    GrokSkepticalRenderInspector,
    GrokVisionInspector,
    ImageOperation,
    ImagePlanValidationError,
    ImageProviderFailure,
    ImageQualityFailure,
    ImageQualityReport,
    ImageRoute,
    JewelryImageAgent,
    MaterialIdentityQualityEvaluator,
    ProviderCallError,
    ProviderImage,
    QualityCheck,
    QualityVerdict,
    RenderCrossInspection,
    RenderInspection,
    RingQualityEvaluator,
    build_image_plan,
)
from facetta.image_agent import orchestrator as orchestrator_module
from facetta.ring_evals import (
    CANONICAL_RING_EDITS,
    RING_GOLDEN_CASES,
    apply_canonical_ring_edit,
    build_ring_golden_spec,
)
from facetta.spec import Spec
from facetta.image_agent.planning import attempt_cache_key
from facetta.image_agent.providers import (
    _provider_call_error,
    _reset_xai_quota_cooldown,
    available_configured_route,
    available_fallback_route,
    configured_fallback_provider,
    note_xai_quota_exhausted,
    RenderPrimitiveProvider,
    xai_quota_cooldown_active,
)
from facetta.provider_errors import RenderUnavailable


HALO = Spec.model_validate(HALO_SPEC)


@pytest.fixture(autouse=True)
def reset_xai_quota_cooldown():
    _reset_xai_quota_cooldown()
    yield
    _reset_xai_quota_cooldown()


def test_canonical_agent_does_not_depend_on_legacy_specagent_or_private_media():
    package = Path(__file__).parents[1] / "src" / "facetta" / "image_agent"
    sources = "\n".join(
        path.read_text() for path in sorted(package.glob("*.py")))
    assert "facetta.specagent" not in sources
    assert "from facetta.render import _" not in sources

    backbone = (
        Path(__file__).parents[1] / "src" / "facetta" /
        "project_backbone.py"
    ).read_text()
    assert "_sniff_media_type" not in backbone


def test_mask_provenance_without_mask_fails_plan_validation():
    with pytest.raises(ImagePlanValidationError, match="actual mask bytes"):
        build_image_plan(
            ImageOperation.LOCAL_EDIT,
            "widen the lower shank",
            spec=HALO,
            source_image=png(),
            mask_provenance="persisted_designer_markup",
            region_description="lower shank",
        )


def png(color: tuple[int, int, int] = (120, 120, 120)) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (96, 96), color).save(output, format="PNG")
    return output.getvalue()


class FakeProvider:
    def __init__(self, failures: dict[int, ProviderCallError] | None = None):
        self.calls: list[dict] = []
        self.failures = failures or {}

    def execute(self, plan, route, prompt, *, source_image, mask_bytes):
        number = len(self.calls) + 1
        self.calls.append({
            "plan": plan,
            "route": route,
            "prompt": prompt,
            "source": source_image,
            "mask": mask_bytes,
        })
        if number in self.failures:
            raise self.failures[number]
        return ProviderImage(
            image_bytes=f"candidate-{number}".encode(),
            cached=False,
            provider_request_id=f"req-{number}",
            usage={"images": 1},
            cost=0.02,
        )


class SequenceEvaluator:
    def __init__(self, *reports: ImageQualityReport):
        self.reports = list(reports)
        self.calls = []

    def evaluate(self, plan, candidate, *, source_image, mask_bytes):
        self.calls.append((plan, candidate, source_image, mask_bytes))
        return self.reports.pop(0)


def render_failure(
    status: int,
    message: str,
) -> RenderUnavailable:
    request = httpx.Request("POST", "https://api.x.ai/v1/images/generations")
    response = httpx.Response(
        status,
        request=request,
        json={"error": {"message": message}},
    )
    status_error = httpx.HTTPStatusError(
        f"HTTP {status}",
        request=request,
        response=response,
    )
    try:
        raise RenderUnavailable("generation provider failed") from status_error
    except RenderUnavailable as failure:
        return failure


class StaticInspector:
    def __init__(self, *, render: RenderInspection | None = None,
                 edit: EditInspection | None = None):
        self.render = render
        self.edit = edit

    def inspect_render(self, plan, candidate, *, reference):
        assert self.render is not None
        return self.render

    def inspect_edit(self, plan, reference, candidate):
        assert self.edit is not None
        return self.edit


class StaticCrossInspector:
    def __init__(self, result: EditCrossInspection | Exception):
        self.result = result

    def inspect_edit(self, plan, reference, candidate):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class StaticRenderCrossInspector:
    def __init__(self, result: RenderCrossInspection | Exception):
        self.result = result

    def inspect_render(self, plan, candidate):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def report(verdict: QualityVerdict, code: str = "metal",
           message: str = "metal color is wrong") -> ImageQualityReport:
    passed = verdict is QualityVerdict.PASS
    severity = (CheckSeverity.WARNING if verdict is QualityVerdict.WARN
                else CheckSeverity.HARD)
    return ImageQualityReport(
        verdict=verdict,
        checks=(QualityCheck(
            code=code,
            passed=passed,
            severity=severity,
            message=message,
            evidence={"expected": "white gold", "observed": "yellow gold"}
            if not passed else {},
        ),),
        score=100 if passed else 60,
    )


def faithful_render(**updates) -> RenderInspection:
    values = {
        "jewelry_type_matches": True,
        "center_species_matches": True,
        "cut_family_matches": True,
        "center_color_matches": True,
        "metal_matches": True,
        "major_components_match": True,
        "setting_matches": True,
        "stone_count_matches": True,
        "text_or_branding_detected": False,
        "exact_dimensions_credible": True,
        "exact_carat_credible": True,
        "score": 96,
    }
    values.update(updates)
    return RenderInspection(**values)


def faithful_edit(**updates) -> EditInspection:
    values = {
        "change_applied": True,
        "unintended_severity": "none",
        "protected_regions_preserved": True,
        "geometry_preserved": True,
        "spec_change_matches": True,
        "text_or_branding_detected": False,
        "score": 98,
    }
    values.update(updates)
    return EditInspection(**values)


class TestPlanning:
    def test_supported_operations_are_versioned_and_content_addressed(self):
        source = b"source"
        plan = build_image_plan(
            ImageOperation.LOCAL_EDIT,
            "widen the band to 2.4 mm",
            spec=HALO,
            source_image=source,
            region_description="the shank between both shoulders",
        )
        same = build_image_plan(
            ImageOperation.LOCAL_EDIT,
            "widen the band to 2.4 mm",
            spec=HALO,
            source_image=source,
            region_description="the shank between both shoulders",
        )
        changed = build_image_plan(
            ImageOperation.LOCAL_EDIT,
            "widen the band to 2.6 mm",
            spec=HALO,
            source_image=source,
            region_description="the shank between both shoulders",
        )
        assert plan.prompt_version == "local-edit.v8"
        assert plan.input_hash == same.input_hash
        assert plan.input_hash != changed.input_hash
        assert plan.source_hash and plan.spec_visual_hash
        model_a = attempt_cache_key(
            plan, ImageRoute.GROK_EDIT, "compiled prompt", "grok-a")
        model_b = attempt_cache_key(
            plan, ImageRoute.GROK_EDIT, "compiled prompt", "grok-b")
        assert model_a != model_b
        variant = build_image_plan(
            ImageOperation.LOCAL_EDIT,
            "widen the band to 2.4 mm",
            spec=HALO,
            source_image=source,
            region_description="the shank between both shoulders",
            variant=1,
        )
        assert plan.input_hash != variant.input_hash

    def test_local_edit_carries_source_and_target_spec_delta(self):
        source = HALO.model_copy(deep=True)
        target = HALO.model_copy(deep=True)
        source.band.width_mm = 2.0
        target.band.width_mm = 2.6
        plan = build_image_plan(
            ImageOperation.LOCAL_EDIT,
            "increase the band width by 0.6 mm",
            spec=target,
            source_spec=source,
            source_image=b"source",
            region_description="the lower shank",
        )
        assert plan.source_spec_facts is not None
        assert plan.source_spec_facts["band"]["width_mm"] == 2.0
        assert plan.spec_facts["band"]["width_mm"] == 2.6
        assert any(
            change["path"] == "band.width_mm"
            and change["from"] == "2 mm"
            and change["to"] == "2.6 mm"
            for change in plan.normalized_intent["spec_delta"]
        )
        assert plan.edit_domains == (DesignerEditDomain.BAND_GEOMETRY,)
        assert plan.normalized_intent["edit_domains"] == ["band_geometry"]

    @pytest.mark.parametrize(
        ("mutate", "expected_domains", "prompt_phrases"),
        (
            (
                lambda spec: (
                    setattr(spec.stone, "cut", "emerald_cut"),
                    setattr(spec.setting, "style", "4_prong_cathedral"),
                ),
                {
                    DesignerEditDomain.CENTER_STONE_SHAPE,
                    DesignerEditDomain.SETTING,
                },
                ("CENTER-STONE SHAPE EXECUTION", "SETTING / PRONG EXECUTION"),
            ),
            (
                lambda spec: (
                    setattr(spec.stone, "species", "sapphire"),
                    setattr(spec.stone.color, "trade", "Royal Blue"),
                    setattr(spec.stone.color, "gia", "vivid blue"),
                ),
                {
                    DesignerEditDomain.CENTER_STONE_IDENTITY,
                    DesignerEditDomain.CENTER_STONE_COLOR,
                },
                ("CENTER-STONE MATERIAL/COLOR EXECUTION",),
            ),
            (
                lambda spec: (
                    setattr(spec.metal, "material", "platinum"),
                    setattr(spec.metal, "karat", None),
                    setattr(spec.metal, "color", None),
                    setattr(spec.metal, "finish", "satin"),
                ),
                {
                    DesignerEditDomain.METAL_IDENTITY,
                    DesignerEditDomain.METAL_FINISH,
                },
                ("METAL MATERIAL/COLOR EXECUTION", "METAL FINISH EXECUTION"),
            ),
            (
                lambda spec: (
                    setattr(spec.side_stones[0], "count", 12),
                    setattr(spec.side_stones[0], "cut", "pear"),
                ),
                {
                    DesignerEditDomain.SIDE_STONE_INVENTORY,
                    DesignerEditDomain.SIDE_STONE_SHAPE,
                },
                ("SIDE-STONE INVENTORY EXECUTION", "SIDE-STONE / MOTIF SHAPE EXECUTION"),
            ),
        ),
    )
    def test_common_designer_deltas_compile_domain_specific_execution(
            self, mutate, expected_domains, prompt_phrases):
        from facetta.image_agent.prompts import compile_initial_prompt

        source = HALO.model_copy(deep=True)
        target = HALO.model_copy(deep=True)
        mutate(target)
        plan = build_image_plan(
            ImageOperation.LOCAL_EDIT,
            "apply the selected jewelry change",
            spec=target,
            source_spec=source,
            source_image=b"source",
            region_description="the designer-selected region",
        )
        prompt = compile_initial_prompt(plan)

        assert set(plan.edit_domains) == expected_domains
        assert set(plan.normalized_intent["edit_domains"]) == {
            domain.value for domain in expected_domains
        }
        for phrase in prompt_phrases:
            assert phrase in prompt
        assert "SOURCE SPEC FACTS (before edit)" in prompt
        assert "VALIDATED RESULT FACTS (after edit)" in prompt
        assert "EXACT SPEC DELTA" in prompt
        assert "FROZEN — THESE MUST NOT CHANGE" in prompt

    def test_retry_prompt_for_unchanged_edit_requires_visible_delta(self):
        from facetta.image_agent.prompts import (
            compile_correction_prompt, compile_initial_prompt,
        )
        plan = build_image_plan(
            ImageOperation.LOCAL_EDIT,
            "increase the band width from 2 mm to 2.6 mm",
            spec=HALO,
            source_spec=HALO,
            source_image=b"source",
            region_description="the lower shank",
        )
        failed_report = report(QualityVerdict.FAIL, code="requested_change")
        prompt, correction = compile_correction_prompt(
            plan, compile_initial_prompt(plan), failed_report)
        assert "Do not return an unchanged source image" in prompt
        assert "requested_change" in correction

    def test_retry_prompt_for_imperceptible_masked_edit_names_attribute(self):
        from facetta.image_agent.prompts import (
            compile_correction_prompt, compile_initial_prompt,
        )
        plan = build_image_plan(
            ImageOperation.REFERENCE_RENDER,
            "make only the marked leaf visibly more emerald green",
            source_image=b"source",
            mask_bytes=b"mask",
        )
        failed_report = report(
            QualityVerdict.FAIL,
            code="inside_mask_effect",
        )

        prompt, correction = compile_correction_prompt(
            plan,
            compile_initial_prompt(plan),
            failed_report,
        )

        assert "Do not return an unchanged source image" in prompt
        assert "exact requested attribute visibly changed" in prompt
        assert "requested geometry visibly changed" not in prompt
        assert "inside_mask_effect" in correction

    def test_band_delta_compiles_visible_symmetric_geometry(self):
        from facetta.image_agent.prompts import compile_initial_prompt

        source = HALO.model_copy(deep=True)
        target = HALO.model_copy(deep=True)
        source.band.width_mm = 3.2
        target.band.width_mm = 3.8
        plan = build_image_plan(
            ImageOperation.LOCAL_EDIT,
            "increase the lower-shank band width",
            spec=target,
            source_spec=source,
            source_image=b"source",
            region_description="the lower shank",
        )
        prompt = compile_initial_prompt(plan)

        assert "approximately 18.7%" in prompt
        assert "Move both visible outer shank edges outward symmetrically" in prompt
        assert "changing only highlight width" in prompt
        assert "inner diameter/circumference" in prompt

    def test_ring_slice_rejects_non_ring_and_missing_edit_source(self):
        non_ring = deepcopy(HALO_SPEC)
        non_ring["jewelry_type"] = "bracelet"
        with pytest.raises(ImagePlanValidationError, match="rings only"):
            build_image_plan(ImageOperation.SPEC_RENDER, "render", spec=non_ring)
        with pytest.raises(ImagePlanValidationError, match="source image"):
            build_image_plan(
                ImageOperation.LOCAL_EDIT,
                "widen band",
                spec=HALO,
                region_description="band",
            )

    def test_run_rejects_bytes_that_do_not_match_the_plan(self):
        plan = build_image_plan(
            ImageOperation.VISUAL_ONLY_EDIT,
            "make the background ivory",
            spec=HALO,
            source_image=b"source-a",
        )
        with pytest.raises(ImagePlanValidationError, match="content hash"):
            JewelryImageAgent(FakeProvider(), SequenceEvaluator(report(
                QualityVerdict.PASS))).run(plan, source_image=b"source-b")

    def test_provider_board_and_quality_source_are_independently_bound(self):
        board = b"role-labeled-reference-board"
        master = b"exact-master-geometry"
        changed_master = b"different-master-geometry"
        plan = build_image_plan(
            ImageOperation.REFERENCE_RENDER,
            "Use the role-labeled board without changing master geometry",
            source_image=board,
            quality_source_image=master,
        )
        changed = build_image_plan(
            ImageOperation.REFERENCE_RENDER,
            "Use the role-labeled board without changing master geometry",
            source_image=board,
            quality_source_image=changed_master,
        )

        assert plan.source_hash == hashlib.sha256(board).hexdigest()
        assert plan.quality_source_hash == hashlib.sha256(master).hexdigest()
        assert plan.normalized_intent["quality_source"] == {
            "sha256": hashlib.sha256(master).hexdigest(),
            "authority": "source_preflight_and_candidate_fidelity",
            "provider_source_sha256": hashlib.sha256(board).hexdigest(),
        }
        assert plan.input_hash != changed.input_hash
        assert attempt_cache_key(
            plan, ImageRoute.GROK_EDIT, "same prompt", "same model",
        ) != attempt_cache_key(
            changed, ImageRoute.GROK_EDIT, "same prompt", "same model",
        )

        with pytest.raises(ImagePlanValidationError, match="quality source"):
            JewelryImageAgent(
                FakeProvider(),
                SequenceEvaluator(report(QualityVerdict.PASS)),
            ).run(
                plan,
                source_image=board,
                quality_source_image=changed_master,
            )

    def test_provider_uses_board_while_preflight_and_corrected_qa_use_master(self):
        board = b"role-labeled-reference-board"
        master = b"exact-master-geometry"
        plan = build_image_plan(
            ImageOperation.REFERENCE_RENDER,
            "Apply material guidance while preserving master geometry",
            source_image=board,
            quality_source_image=master,
        )
        provider = FakeProvider()

        class FidelityEvaluator(SequenceEvaluator):
            def __init__(self):
                super().__init__(
                    report(QualityVerdict.FAIL, code="source_design_preserved"),
                    report(QualityVerdict.PASS),
                )
                self.preflight_sources: list[bytes] = []

            def evaluate_source_precondition(self, _plan, source):
                self.preflight_sources.append(source)
                return report(QualityVerdict.PASS)

        evaluator = FidelityEvaluator()
        result = JewelryImageAgent(provider, evaluator).run(
            plan,
            source_image=board,
            quality_source_image=master,
        )

        assert result.accepted is True
        assert evaluator.preflight_sources == [master]
        assert [call[2] for call in evaluator.calls] == [master, master]
        assert [call["source"] for call in provider.calls] == [board, board]
        assert "source_design_preserved" in provider.calls[1]["prompt"]

    def test_omitted_quality_source_keeps_existing_source_and_no_source_behavior(self):
        source = b"ordinary-reference"
        reference_plan = build_image_plan(
            ImageOperation.REFERENCE_RENDER,
            "Polish this reference",
            source_image=source,
        )
        reference_evaluator = SequenceEvaluator(report(QualityVerdict.PASS))
        JewelryImageAgent(FakeProvider(), reference_evaluator).run(
            reference_plan,
            source_image=source,
        )
        assert reference_plan.quality_source_hash is None
        assert "quality_source" not in reference_plan.normalized_intent
        assert reference_evaluator.calls[0][2] == source

        prompt_plan = build_image_plan(
            ImageOperation.CREATIVE_GENERATE,
            "A sculptural gold ring",
        )
        prompt_evaluator = SequenceEvaluator(report(QualityVerdict.PASS))
        JewelryImageAgent(FakeProvider(), prompt_evaluator).run(prompt_plan)
        assert prompt_evaluator.calls[0][2] is None

    def test_reference_backed_spec_render_uses_edit_routes(self):
        plan = build_image_plan(
            ImageOperation.SPEC_RENDER,
            "render the validated spec without losing the concept identity",
            spec=HALO,
            source_image=b"approved-concept",
        )
        provider = FakeProvider()
        result = JewelryImageAgent(
            provider,
            SequenceEvaluator(
                report(QualityVerdict.FAIL, code="reference_consistency"),
                report(QualityVerdict.FAIL, code="reference_consistency"),
                report(QualityVerdict.PASS),
            ),
        ).run(plan, source_image=b"approved-concept")
        assert result.accepted is True
        assert [call["route"] for call in provider.calls] == [
            ImageRoute.GROK_EDIT,
            ImageRoute.GROK_EDIT,
            ImageRoute.FLUX_KONTEXT_EDIT,
        ]
        assert all(call["source"] == b"approved-concept"
                   for call in provider.calls)
        assert "source concept's unique design identity" in provider.calls[0][
            "prompt"]

    def test_mask_reaches_provider_and_prompt_contract(self):
        source = b"source"
        mask = b"mask"
        plan = build_image_plan(
            ImageOperation.LOCAL_EDIT,
            "widen the band",
            spec=HALO,
            source_image=source,
            mask_bytes=mask,
            region_description="the lower shank",
        )
        provider = FakeProvider()
        result = JewelryImageAgent(
            provider,
            SequenceEvaluator(report(QualityVerdict.PASS)),
        ).run(plan, source_image=source, mask_bytes=mask)

        assert result.accepted is True
        assert provider.calls[0]["mask"] == mask
        assert "IMAGE 2 is the localization guide" in provider.calls[0]["prompt"]


class TestRingQualityGates:
    def test_blind_prong_count_overrides_expectation_biased_render_pass(
        self, monkeypatch,
    ):
        spec = HALO.model_copy(deep=True)
        spec.setting.prong_count = 6
        spec.setting.style = "6_prong_basket"
        plan = build_image_plan(
            ImageOperation.SPEC_RENDER, "render six prongs", spec=spec)
        calls = []

        def inspect(system, candidate, ask):
            calls.append((system, ask))
            if "expectation-free" in system:
                return {
                    "center_prongs_visible": 4,
                    "center_prong_count_complete": True,
                    "side_stones_visible": 8,
                    "side_stone_count_complete": True,
                    "notes": ["four center-holding claws are visible"],
                }
            return RenderCrossInspection(
                jewelry_type_matches=True,
                center_identity_matches=True,
                center_cut_matches=True,
                metal_matches=True,
                setting_style_matches=True,
                prong_count_matches=True,  # biased broad audit says six
                observed_prong_count=6,
                side_stone_inventory_matches=True,
                observed_side_stone_count=8,
                major_components_match=True,
            ).model_dump(mode="json")

        monkeypatch.setattr(
            "facetta.image_agent.quality.vision_json", inspect)

        result = GrokSkepticalRenderInspector().inspect_render(
            plan, b"candidate")

        assert len(calls) == 2
        assert "6_prong_basket" in calls[0][1]
        assert calls[1][1].startswith(
            "Count only what is visibly present in this image.")
        assert "deterministic crop" in calls[1][1]
        assert result.observed_prong_count == 4
        assert result.prong_count_matches is False
        assert result.side_stone_inventory_matches is True

    def test_conflicting_side_stone_counts_require_designer_review(
        self, monkeypatch,
    ):
        plan = build_image_plan(
            ImageOperation.SPEC_RENDER, "render exact halo", spec=HALO)

        def inspect(system, candidate, ask):
            if "expectation-free" in system:
                return {
                    "center_prongs_visible": 4,
                    "center_prong_count_complete": True,
                    "side_stones_visible": 9,
                    "side_stone_count_complete": True,
                }
            return RenderCrossInspection(
                jewelry_type_matches=True,
                center_identity_matches=True,
                center_cut_matches=True,
                metal_matches=True,
                setting_style_matches=True,
                prong_count_matches=True,
                side_stone_inventory_matches=True,
                major_components_match=True,
            ).model_dump(mode="json")

        monkeypatch.setattr(
            "facetta.image_agent.quality.vision_json", inspect)
        result = GrokSkepticalRenderInspector().inspect_render(
            plan, b"candidate")

        assert result.side_stone_inventory_matches is None
        assert result.observed_side_stone_count == 9
        assert any("designer count review required" in note
                   for note in result.notes)

    def test_grok_edit_audit_receives_before_after_delta_frozen_and_domains(
        self, monkeypatch,
    ):
        source_spec = HALO.model_copy(deep=True)
        target_spec = HALO.model_copy(deep=True)
        target_spec.side_stones[0].count -= 1
        target_spec.metal.color = "rose"
        plan = build_image_plan(
            ImageOperation.LOCAL_EDIT,
            "remove one halo diamond and change all metal to rose gold",
            spec=target_spec,
            source_spec=source_spec,
            source_image=b"source",
            region_description="the ring head and all metal surfaces",
            frozen=("center stone", "camera and lighting"),
        )
        captured = {}

        def inspect(system, source, candidate, ask):
            captured.update({
                "system": system,
                "source": source,
                "candidate": candidate,
                "ask": ask,
            })
            return faithful_edit(domain_matches={
                domain.value: True for domain in plan.edit_domains
            }).model_dump(mode="json")

        monkeypatch.setattr(
            "facetta.image_agent.quality.vision_json_pair", inspect)

        result = GrokVisionInspector().inspect_edit(
            plan, b"source", b"candidate")

        assert result.domain_matches == {
            "side_stone_inventory": True,
            "metal_identity": True,
        }
        assert captured["source"] == b"source"
        assert captured["candidate"] == b"candidate"
        assert '"domain_matches"' in captured["system"]
        assert "exactly those domain ids" in captured["system"]
        assert "Source facts:" in captured["ask"]
        assert '"color": "white"' in captured["ask"]
        assert "Validated result facts:" in captured["ask"]
        assert '"color": "rose"' in captured["ask"]
        assert "Exact spec delta:" in captured["ask"]
        assert '"path": "side_stones.0.count"' in captured["ask"]
        assert '"path": "metal.color"' in captured["ask"]
        assert "Frozen facts:" in captured["ask"]
        assert "camera and lighting" in captured["ask"]
        assert "REQUIRED EDIT DOMAINS:" in captured["ask"]
        assert '"side_stone_inventory", "metal_identity"' in captured["ask"]

    def test_faithful_spec_render_passes_every_hard_gate(self):
        evaluator = RingQualityEvaluator(StaticInspector(render=faithful_render()))
        plan = build_image_plan(ImageOperation.SPEC_RENDER, "studio render", spec=HALO)
        result = evaluator.evaluate(
            plan,
            png(),
            source_image=None,
            mask_bytes=None,
        )
        assert result.verdict is QualityVerdict.PASS
        assert {check.code for check in result.checks} >= {
            "jewelry_type", "center_species", "cut_family", "center_color",
            "metal", "major_components", "setting", "stone_count",
            "text_or_branding",
        }

    def test_raster_dimension_uncertainty_is_a_warning_not_a_failure(self):
        evaluator = RingQualityEvaluator(StaticInspector(
            render=faithful_render(exact_dimensions_credible=False)))
        plan = build_image_plan(ImageOperation.SPEC_RENDER, "studio render", spec=HALO)
        result = evaluator.evaluate(plan, png(), source_image=None,
                                    mask_bytes=None)
        assert result.verdict is QualityVerdict.WARN
        dimension = next(c for c in result.checks if c.code == "exact_dimensions")
        assert dimension.severity is CheckSeverity.WARNING

    def test_wrong_setting_and_branding_are_hard_failures(self):
        evaluator = RingQualityEvaluator(StaticInspector(render=faithful_render(
            setting_matches=False,
            text_or_branding_detected=True,
        )))
        plan = build_image_plan(ImageOperation.SPEC_RENDER, "studio render", spec=HALO)
        result = evaluator.evaluate(plan, png(), source_image=None,
                                    mask_bytes=None)
        assert result.verdict is QualityVerdict.FAIL
        failed = {c.code for c in result.failed_checks}
        assert {"setting", "text_or_branding"} <= failed

    def test_independent_render_audit_catches_wrong_prong_count(self):
        evaluator = RingQualityEvaluator(
            StaticInspector(render=faithful_render()),
            render_cross_inspector=StaticRenderCrossInspector(
                RenderCrossInspection(
                    jewelry_type_matches=True,
                    center_identity_matches=True,
                    center_cut_matches=True,
                    metal_matches=True,
                    setting_style_matches=True,
                    prong_count_matches=False,
                    observed_prong_count=4,
                    side_stone_inventory_matches=True,
                    major_components_match=True,
                    differences=("four center prongs visible; six required",),
                )),
        )
        plan = build_image_plan(
            ImageOperation.SPEC_RENDER, "studio render", spec=HALO)

        result = evaluator.evaluate(
            plan, png(), source_image=None, mask_bytes=None)

        assert result.verdict is QualityVerdict.FAIL
        assert result.score == 40.0
        prongs = next(
            check for check in result.failed_checks
            if check.code == "render_crosscheck:prong_count")
        assert prongs.severity is CheckSeverity.HARD
        assert prongs.evidence["observed_prong_count"] == 4
        assert "six required" in prongs.evidence["differences"][0]

    def test_unassessable_render_crosscheck_requires_review(self):
        evaluator = RingQualityEvaluator(
            StaticInspector(render=faithful_render()),
            render_cross_inspector=StaticRenderCrossInspector(
                RenderCrossInspection(
                    jewelry_type_matches=True,
                    center_identity_matches=True,
                    center_cut_matches=True,
                    metal_matches=True,
                    setting_style_matches=True,
                    prong_count_matches=None,
                    side_stone_inventory_matches=None,
                    major_components_match=True,
                )),
        )
        plan = build_image_plan(
            ImageOperation.SPEC_RENDER, "studio render", spec=HALO)

        result = evaluator.evaluate(
            plan, png(), source_image=None, mask_bytes=None)

        assert result.verdict is QualityVerdict.WARN
        failed = {check.code: check for check in result.failed_checks}
        assert failed["render_crosscheck:prong_count"].severity is (
            CheckSeverity.WARNING)
        assert failed["render_crosscheck:side_stone_inventory"].severity is (
            CheckSeverity.WARNING)

    def test_local_edit_enforces_mask_drift_and_result_spec(self):
        evaluator = RingQualityEvaluator(
            StaticInspector(edit=faithful_edit(spec_change_matches=False)),
            drift_measure=lambda source, candidate, mask: 0.22,
        )
        plan = build_image_plan(
            ImageOperation.LOCAL_EDIT,
            "widen the band to 2.4 mm",
            spec=HALO,
            source_image=png((10, 10, 10)),
            mask_bytes=b"mask",
            region_description="band",
            drift_threshold=0.18,
        )
        result = evaluator.evaluate(plan, png((20, 20, 20)),
                                    source_image=png((10, 10, 10)),
                                    mask_bytes=b"mask")
        assert result.verdict is QualityVerdict.FAIL
        failed = {c.code for c in result.failed_checks}
        assert {"spec_change", "outside_mask_drift"} <= failed

    def test_masked_near_noop_fails_deterministic_effect_gate(self):
        source = png((120, 120, 120))
        candidate_image = Image.open(io.BytesIO(source)).convert("RGB")
        candidate_image.putpixel((48, 48), (130, 120, 120))
        candidate_output = io.BytesIO()
        candidate_image.save(candidate_output, format="PNG")
        mask_image = Image.new("L", (96, 96), 0)
        ImageDraw.Draw(mask_image).rectangle((24, 24, 72, 72), fill=255)
        mask_output = io.BytesIO()
        mask_image.save(mask_output, format="PNG")
        mask = mask_output.getvalue()
        evaluator = RingQualityEvaluator(
            StaticInspector(edit=faithful_edit()),
        )
        plan = build_image_plan(
            ImageOperation.LOCAL_EDIT,
            "make the center setting rose gold",
            spec=HALO,
            source_image=source,
            mask_bytes=mask,
            region_description="the center setting",
        )

        result = evaluator.evaluate(
            plan,
            candidate_output.getvalue(),
            source_image=source,
            mask_bytes=mask,
        )

        assert result.verdict is QualityVerdict.FAIL
        effect = next(
            check for check in result.checks
            if check.code == "inside_mask_effect"
        )
        assert effect.passed is False
        assert effect.severity is CheckSeverity.HARD
        assert effect.evidence["changed_pixels"] == 1

    def test_unmasked_appearance_edit_has_no_local_effect_gate(self):
        source = png((120, 120, 120))
        candidate_image = Image.open(io.BytesIO(source)).convert("RGB")
        candidate_image.putpixel((48, 48), (130, 120, 120))
        candidate_output = io.BytesIO()
        candidate_image.save(candidate_output, format="PNG")
        evaluator = RingQualityEvaluator(
            StaticInspector(edit=faithful_edit()),
        )
        plan = build_image_plan(
            ImageOperation.VISUAL_ONLY_EDIT,
            "warm the overall presentation",
            spec=HALO,
            source_image=source,
        )

        result = evaluator.evaluate(
            plan,
            candidate_output.getvalue(),
            source_image=source,
            mask_bytes=None,
        )

        assert result.verdict is QualityVerdict.PASS
        assert "inside_mask_effect" not in {
            check.code for check in result.checks
        }

    def test_masked_reference_render_rejects_near_noop(self):
        source = png((120, 120, 120))
        candidate_image = Image.open(io.BytesIO(source)).convert("RGB")
        candidate_image.putpixel((48, 48), (130, 120, 120))
        candidate_output = io.BytesIO()
        candidate_image.save(candidate_output, format="PNG")
        mask_image = Image.new("L", (96, 96), 0)
        ImageDraw.Draw(mask_image).ellipse((24, 24, 72, 72), fill=255)
        mask_output = io.BytesIO()
        mask_image.save(mask_output, format="PNG")
        mask = mask_output.getvalue()

        class CreativeInspector:
            def inspect_render(self, _plan, _source, _candidate):
                return CreativeRenderInspection(
                    coherent_jewelry_render=True,
                    complete_piece_visible=True,
                    source_design_preserved=True,
                    visible_components_preserved=True,
                    local_geometry_preserved=True,
                    repeated_element_pattern_preserved=True,
                    stone_shape_and_cut_family_preserved=True,
                    requested_presentation_applied=True,
                    text_or_branding_detected=False,
                    score=98,
                )

        evaluator = RingQualityEvaluator(
            StaticInspector(edit=faithful_edit()),
            creative_inspector=CreativeInspector(),
        )
        plan = build_image_plan(
            ImageOperation.REFERENCE_RENDER,
            "make the marked center stone pale yellow",
            source_image=source,
            mask_bytes=mask,
        )

        result = evaluator.evaluate(
            plan,
            candidate_output.getvalue(),
            source_image=source,
            mask_bytes=mask,
        )

        assert result.verdict is QualityVerdict.FAIL
        failed = {check.code for check in result.failed_checks}
        assert "inside_mask_effect" in failed

    def test_marked_local_geometry_false_negative_is_bounded_by_region_proof(self):
        source_image = Image.new("RGB", (96, 96), (220, 220, 220))
        candidate_image = source_image.copy()
        candidate_draw = ImageDraw.Draw(candidate_image)
        candidate_draw.rectangle((8, 20, 30, 42), fill=(150, 190, 230))
        candidate_draw.rectangle((66, 20, 88, 42), fill=(180, 180, 180))
        mask_image = Image.new("L", source_image.size, 0)
        mask_draw = ImageDraw.Draw(mask_image)
        mask_draw.rectangle((8, 20, 30, 42), fill=255)
        mask_draw.rectangle((66, 20, 88, 42), fill=255)

        def encoded(image: Image.Image) -> bytes:
            output = io.BytesIO()
            image.save(output, format="PNG")
            return output.getvalue()

        class AggregateFalseNegativeInspector:
            def inspect_render(self, _plan, _source, _candidate):
                return CreativeRenderInspection(
                    coherent_jewelry_render=True,
                    complete_piece_visible=True,
                    source_design_preserved=False,
                    visible_components_preserved=True,
                    local_geometry_preserved=False,
                    repeated_element_pattern_preserved=True,
                    stone_shape_and_cut_family_preserved=True,
                    requested_presentation_applied=True,
                    text_or_branding_detected=False,
                    major_unintended_changes=(),
                    score=96,
                )

        source = encoded(source_image)
        candidate = encoded(candidate_image)
        mask = encoded(mask_image)
        plan = build_image_plan(
            ImageOperation.REFERENCE_RENDER,
            (
                "1. Inside 'left stone': Make it pale blue. "
                "2. Inside 'right prongs': Make the prongs finer."
            ),
            source_image=source,
            mask_bytes=mask,
            mask_provenance="designer_marked_pre_spec_region",
            authorized_masked_change_domains=("appearance", "local_geometry"),
            marked_region_count=2,
        )
        evaluator = RingQualityEvaluator(
            StaticInspector(edit=faithful_edit()),
            creative_inspector=AggregateFalseNegativeInspector(),
            require_creative_cross_inspection=False,
        )

        result = evaluator.evaluate(
            plan,
            candidate,
            source_image=source,
            mask_bytes=mask,
        )

        checks = {check.code: check for check in result.checks}
        assert result.verdict in {QualityVerdict.PASS, QualityVerdict.WARN}
        assert checks["inside_each_mask_region_effect"].passed is True
        assert checks["source_design_preserved"].passed is True
        assert checks["local_geometry_preserved"].passed is True
        assert checks["local_geometry_preserved"].evidence["resolved_by"] == (
            "bounded_marked_region_authorization"
        )

    def test_marked_edit_cannot_hide_an_unchanged_requested_region(self):
        source_image = Image.new("RGB", (96, 96), (220, 220, 220))
        candidate_image = source_image.copy()
        ImageDraw.Draw(candidate_image).rectangle(
            (8, 20, 30, 42), fill=(150, 190, 230)
        )
        mask_image = Image.new("L", source_image.size, 0)
        mask_draw = ImageDraw.Draw(mask_image)
        mask_draw.rectangle((8, 20, 30, 42), fill=255)
        mask_draw.rectangle((66, 20, 88, 42), fill=255)

        def encoded(image: Image.Image) -> bytes:
            output = io.BytesIO()
            image.save(output, format="PNG")
            return output.getvalue()

        class Inspector:
            def inspect_render(self, _plan, _source, _candidate):
                return CreativeRenderInspection(
                    coherent_jewelry_render=True,
                    complete_piece_visible=True,
                    source_design_preserved=True,
                    visible_components_preserved=True,
                    local_geometry_preserved=True,
                    repeated_element_pattern_preserved=True,
                    stone_shape_and_cut_family_preserved=True,
                    requested_presentation_applied=True,
                    text_or_branding_detected=False,
                    score=96,
                )

        source = encoded(source_image)
        candidate = encoded(candidate_image)
        mask = encoded(mask_image)
        plan = build_image_plan(
            ImageOperation.REFERENCE_RENDER,
            "apply both marked changes",
            source_image=source,
            mask_bytes=mask,
            mask_provenance="designer_marked_pre_spec_region",
            authorized_masked_change_domains=("appearance",),
            marked_region_count=2,
        )
        evaluator = RingQualityEvaluator(
            StaticInspector(edit=faithful_edit()),
            creative_inspector=Inspector(),
            require_creative_cross_inspection=False,
        )

        result = evaluator.evaluate(
            plan,
            candidate,
            source_image=source,
            mask_bytes=mask,
        )

        failed = {check.code for check in result.failed_checks}
        assert result.verdict is QualityVerdict.FAIL
        assert "inside_each_mask_region_effect" in failed

    def test_unmasked_reference_render_has_no_mask_gates(self):
        source = png((120, 120, 120))

        class CreativeInspector:
            def inspect_render(self, _plan, _source, _candidate):
                return CreativeRenderInspection(
                    coherent_jewelry_render=True,
                    complete_piece_visible=True,
                    source_design_preserved=True,
                    visible_components_preserved=True,
                    local_geometry_preserved=True,
                    repeated_element_pattern_preserved=True,
                    stone_shape_and_cut_family_preserved=True,
                    requested_presentation_applied=True,
                    text_or_branding_detected=False,
                    score=98,
                )

        evaluator = RingQualityEvaluator(
            StaticInspector(edit=faithful_edit()),
            creative_inspector=CreativeInspector(),
        )
        plan = build_image_plan(
            ImageOperation.REFERENCE_RENDER,
            "warm the whole presentation",
            source_image=source,
        )

        result = evaluator.evaluate(
            plan,
            png((125, 120, 120)),
            source_image=source,
            mask_bytes=None,
        )

        assert "inside_mask_effect" not in {
            check.code for check in result.checks
        }
        assert "outside_mask_drift" not in {
            check.code for check in result.checks
        }

    @pytest.mark.parametrize("edit_id", [
        "center-cut-shape",
        "center-species-color",
        "band-width",
        "metal-color",
        "prong-setting",
        "halo-add",
        "halo-remove",
        "halo-count",
        "leaf-motif-shape",
    ])
    def test_each_designer_edit_domain_is_an_independent_hard_gate(
        self, edit_id,
    ):
        cases = {case.id: case for case in RING_GOLDEN_CASES}
        edits = {edit.id: edit for edit in CANONICAL_RING_EDITS}
        edit = edits[edit_id]
        source_spec = build_ring_golden_spec(cases[edit.golden_case_id])
        target_spec, issues = apply_canonical_ring_edit(source_spec, edit)
        assert target_spec is not None and issues == []
        source = png((20, 20, 20))
        candidate = png((40, 40, 40))
        plan = build_image_plan(
            ImageOperation.LOCAL_EDIT,
            edit.instruction,
            spec=target_spec,
            source_spec=source_spec,
            source_image=source,
            region_description=edit.region,
            frozen=edit.frozen_facts,
        )
        assert plan.edit_domains
        failed_domain = plan.edit_domains[-1].value
        domain_matches = {
            domain.value: domain.value != failed_domain
            for domain in plan.edit_domains
        }
        evaluator = RingQualityEvaluator(StaticInspector(edit=faithful_edit(
            domain_matches=domain_matches,
        )))

        result = evaluator.evaluate(
            plan, candidate, source_image=source, mask_bytes=None)

        assert result.verdict is QualityVerdict.FAIL
        failed = {check.code: check for check in result.failed_checks}
        code = f"edit_domain:{failed_domain}"
        assert code in failed
        assert failed[code].severity is CheckSeverity.HARD
        assert failed[code].evidence["domain"] == failed_domain
        assert failed[code].evidence["spec_delta"]

    @pytest.mark.parametrize("edit_id", ("halo-add", "halo-remove"))
    def test_complete_halo_lifecycle_is_one_atomic_inventory_domain(
        self, edit_id,
    ):
        edit = next(item for item in CANONICAL_RING_EDITS if item.id == edit_id)
        case = next(
            item for item in RING_GOLDEN_CASES
            if item.id == edit.golden_case_id
        )
        source_spec = build_ring_golden_spec(case)
        target_spec, issues = apply_canonical_ring_edit(source_spec, edit)
        assert target_spec is not None, issues
        source = png()

        plan = build_image_plan(
            ImageOperation.LOCAL_EDIT,
            edit.instruction,
            spec=target_spec,
            source_spec=source_spec,
            source_image=source,
            region_description=edit.region,
        )

        assert plan.edit_domains == (
            DesignerEditDomain.SIDE_STONE_INVENTORY,
        )

    def test_existing_side_stone_shape_change_keeps_shape_domain(self):
        edit = next(
            item for item in CANONICAL_RING_EDITS
            if item.id == "leaf-motif-shape"
        )
        case = next(
            item for item in RING_GOLDEN_CASES
            if item.id == edit.golden_case_id
        )
        source_spec = build_ring_golden_spec(case)
        target_spec, issues = apply_canonical_ring_edit(source_spec, edit)
        assert target_spec is not None, issues

        plan = build_image_plan(
            ImageOperation.LOCAL_EDIT,
            edit.instruction,
            spec=target_spec,
            source_spec=source_spec,
            source_image=png(),
            region_description=edit.region,
        )

        assert DesignerEditDomain.SIDE_STONE_SHAPE in plan.edit_domains

    def test_complete_candidate_inventory_count_is_an_independent_hard_gate(self):
        edit = next(
            item for item in CANONICAL_RING_EDITS if item.id == "halo-count"
        )
        case = next(
            item for item in RING_GOLDEN_CASES
            if item.id == edit.golden_case_id
        )
        source_spec = build_ring_golden_spec(case)
        target_spec, issues = apply_canonical_ring_edit(source_spec, edit)
        assert target_spec is not None, issues
        source = png((20, 20, 20))
        plan = build_image_plan(
            ImageOperation.LOCAL_EDIT,
            edit.instruction,
            spec=target_spec,
            source_spec=source_spec,
            source_image=source,
            region_description=edit.region,
        )
        target_count = target_spec.side_stones[0].count
        evaluator = RingQualityEvaluator(StaticInspector(edit=faithful_edit(
            domain_matches={"side_stone_inventory": True},
            side_stone_inventory=EditSideStoneInventoryInspection(
                source_visible_count=target_count + 1,
                source_count_complete=True,
                candidate_visible_count=target_count + 1,
                candidate_count_complete=True,
                source_role_counts={"halo": target_count + 1},
                candidate_role_counts={"halo": target_count + 1},
            ),
        )))

        result = evaluator.evaluate(
            plan, png((40, 40, 40)), source_image=source, mask_bytes=None)

        checks = {check.code: check for check in result.checks}
        assert result.verdict is QualityVerdict.FAIL
        assert checks["inventory_source_count"].passed is True
        assert checks["inventory_target_count"].passed is False
        assert checks["inventory_target_count"].evidence == {
            "expected": target_count,
            "observed": target_count + 1,
            "complete": True,
            "role_counts": {"halo": target_count + 1},
        }

    def test_conflicting_blind_inventory_count_cannot_be_a_warning_candidate(self):
        edit = next(
            item for item in CANONICAL_RING_EDITS if item.id == "halo-count"
        )
        case = next(
            item for item in RING_GOLDEN_CASES
            if item.id == edit.golden_case_id
        )
        source_spec = build_ring_golden_spec(case)
        target_spec, issues = apply_canonical_ring_edit(source_spec, edit)
        assert target_spec is not None, issues
        target_count = target_spec.side_stones[0].count
        source = png((20, 20, 20))
        plan = build_image_plan(
            ImageOperation.LOCAL_EDIT,
            edit.instruction,
            spec=target_spec,
            source_spec=source_spec,
            source_image=source,
            region_description=edit.region,
        )
        evaluator = RingQualityEvaluator(
            StaticInspector(edit=faithful_edit(
                domain_matches={"side_stone_inventory": True},
                side_stone_inventory=EditSideStoneInventoryInspection(
                    source_visible_count=target_count + 1,
                    source_count_complete=True,
                    candidate_visible_count=target_count,
                    candidate_count_complete=True,
                ),
            )),
            render_cross_inspector=StaticRenderCrossInspector(
                RenderCrossInspection(
                    jewelry_type_matches=True,
                    center_identity_matches=True,
                    center_cut_matches=True,
                    metal_matches=True,
                    setting_style_matches=True,
                    prong_count_matches=True,
                    side_stone_inventory_matches=None,
                    observed_side_stone_count=target_count + 3,
                    observed_side_stone_count_complete=True,
                    major_components_match=True,
                )),
        )

        result = evaluator.evaluate(
            plan, png((40, 40, 40)), source_image=source, mask_bytes=None)

        failed = {check.code: check for check in result.failed_checks}
        assert result.verdict is QualityVerdict.FAIL
        assert result.score == 40.0
        count = failed["inventory_independent_target_count"]
        assert count.severity is CheckSeverity.HARD
        assert count.evidence == {
            "expected": target_count,
            "observed": target_count + 3,
            "complete": True,
        }

    def test_missing_domain_judgment_requires_review_instead_of_silent_pass(self):
        source_spec = HALO.model_copy(deep=True)
        target_spec = HALO.model_copy(deep=True)
        target_spec.metal.color = "rose"
        source = png((20, 20, 20))
        plan = build_image_plan(
            ImageOperation.LOCAL_EDIT,
            "change all metal to rose gold",
            spec=target_spec,
            source_spec=source_spec,
            source_image=source,
            region_description="all metal surfaces",
        )
        evaluator = RingQualityEvaluator(StaticInspector(
            edit=faithful_edit(domain_matches={})))

        result = evaluator.evaluate(
            plan, png((40, 40, 40)), source_image=source, mask_bytes=None)

        assert result.verdict is QualityVerdict.WARN
        domain = next(check for check in result.failed_checks
                      if check.code == "edit_domain:metal_identity")
        assert domain.severity is CheckSeverity.WARNING

    def test_all_required_domain_judgments_allow_a_faithful_edit_to_pass(self):
        source_spec = HALO.model_copy(deep=True)
        target_spec = HALO.model_copy(deep=True)
        target_spec.metal.color = "rose"
        source = png((20, 20, 20))
        plan = build_image_plan(
            ImageOperation.LOCAL_EDIT,
            "change all metal to rose gold",
            spec=target_spec,
            source_spec=source_spec,
            source_image=source,
            region_description="all metal surfaces",
        )
        evaluator = RingQualityEvaluator(StaticInspector(edit=faithful_edit(
            domain_matches={domain.value: True for domain in plan.edit_domains},
        )))

        result = evaluator.evaluate(
            plan, png((40, 40, 40)), source_image=source, mask_bytes=None)

        assert result.verdict is QualityVerdict.PASS

    def test_skeptical_second_audit_vetoes_a_primary_false_pass(self):
        source_spec = HALO.model_copy(deep=True)
        target_spec = HALO.model_copy(deep=True)
        target_spec.metal.color = "rose"
        source = png((20, 20, 20))
        plan = build_image_plan(
            ImageOperation.LOCAL_EDIT,
            "change all metal to rose gold",
            spec=target_spec,
            source_spec=source_spec,
            source_image=source,
            region_description="all metal surfaces",
            frozen=("every gemstone and all ring geometry",),
        )
        evaluator = RingQualityEvaluator(
            StaticInspector(edit=faithful_edit(
                domain_matches={"metal_identity": True},
            )),
            edit_cross_inspector=StaticCrossInspector(EditCrossInspection(
                change_applied=True,
                frozen_facts_preserved=False,
                unintended_severity="major",
                unintended_changes=("center setting geometry changed",),
            )),
        )

        result = evaluator.evaluate(
            plan, png((40, 40, 40)), source_image=source, mask_bytes=None)

        assert result.verdict is QualityVerdict.FAIL
        failed = {check.code: check for check in result.failed_checks}
        assert failed["crosscheck_frozen_facts"].severity is CheckSeverity.HARD
        assert failed["crosscheck_unintended_drift"].severity is CheckSeverity.HARD
        assert "center setting geometry changed" in (
            failed["crosscheck_unintended_drift"].message)

    def test_local_edit_must_also_match_the_complete_target_spec(self):
        source_spec = HALO.model_copy(deep=True)
        target_spec = HALO.model_copy(deep=True)
        target_spec.stone.cut = "emerald_cut"
        source = png((20, 20, 20))
        plan = build_image_plan(
            ImageOperation.LOCAL_EDIT,
            "change the center stone to emerald cut and keep six prongs",
            spec=target_spec,
            source_spec=source_spec,
            source_image=source,
            region_description="center stone and prong seats",
            frozen=("six-prong count and setting style",),
        )
        evaluator = RingQualityEvaluator(
            StaticInspector(edit=faithful_edit(
                domain_matches={"center_stone_shape": True},
            )),
            edit_cross_inspector=StaticCrossInspector(EditCrossInspection(
                change_applied=True,
                frozen_facts_preserved=True,
                unintended_severity="none",
            )),
            render_cross_inspector=StaticRenderCrossInspector(
                RenderCrossInspection(
                    jewelry_type_matches=True,
                    center_identity_matches=True,
                    center_cut_matches=True,
                    metal_matches=True,
                    setting_style_matches=True,
                    prong_count_matches=False,
                    observed_prong_count=4,
                    side_stone_inventory_matches=True,
                    major_components_match=True,
                    differences=("four center prongs visible; six required",),
                )),
        )

        result = evaluator.evaluate(
            plan, png((40, 40, 40)), source_image=source, mask_bytes=None)

        assert result.verdict is QualityVerdict.FAIL
        assert result.score == 40.0
        failed = {check.code: check for check in result.failed_checks}
        prongs = failed["target_spec_crosscheck:prong_count"]
        assert prongs.severity is CheckSeverity.HARD
        assert prongs.evidence["observed_prong_count"] == 4

    def test_unavailable_second_audit_holds_candidate_for_review(self):
        source_spec = HALO.model_copy(deep=True)
        target_spec = HALO.model_copy(deep=True)
        target_spec.metal.color = "rose"
        source = png((20, 20, 20))
        plan = build_image_plan(
            ImageOperation.LOCAL_EDIT,
            "change all metal to rose gold",
            spec=target_spec,
            source_spec=source_spec,
            source_image=source,
            region_description="all metal surfaces",
        )
        evaluator = RingQualityEvaluator(
            StaticInspector(edit=faithful_edit(
                domain_matches={"metal_identity": True},
            )),
            edit_cross_inspector=StaticCrossInspector(
                RuntimeError("secondary provider unavailable")),
        )

        result = evaluator.evaluate(
            plan, png((40, 40, 40)), source_image=source, mask_bytes=None)

        assert result.verdict is QualityVerdict.WARN
        audit = next(check for check in result.failed_checks
                     if check.code == "independent_edit_audit")
        assert audit.severity is CheckSeverity.WARNING

    def test_white_gold_to_platinum_is_spec_truth_and_review_warning(self):
        source_spec = HALO.model_copy(deep=True)
        target_spec = HALO.model_copy(deep=True)
        target_spec.metal.material = "platinum"
        target_spec.metal.karat = None
        target_spec.metal.color = None
        source = png((20, 20, 20))
        plan = build_image_plan(
            ImageOperation.LOCAL_EDIT,
            "change 18k white gold to platinum",
            spec=target_spec,
            source_spec=source_spec,
            source_image=source,
            region_description="all metal surfaces",
        )
        evaluator = RingQualityEvaluator(
            StaticInspector(edit=faithful_edit(
                domain_matches={"metal_identity": True},
            )),
            edit_cross_inspector=StaticCrossInspector(EditCrossInspection(
                change_applied=True,
                frozen_facts_preserved=True,
                unintended_severity="none",
            )),
            render_cross_inspector=StaticRenderCrossInspector(
                RenderCrossInspection(
                    jewelry_type_matches=True,
                    center_identity_matches=True,
                    center_cut_matches=True,
                    metal_matches=True,
                    setting_style_matches=True,
                    prong_count_matches=True,
                    observed_prong_count=4,
                    side_stone_inventory_matches=True,
                    observed_side_stone_count=8,
                    major_components_match=True,
                )),
        )

        result = evaluator.evaluate(
            plan, png((40, 40, 40)), source_image=source, mask_bytes=None)

        assert result.verdict is QualityVerdict.WARN
        material = next(check for check in result.failed_checks
                        if check.code == "exact_metal_material")
        assert material.severity is CheckSeverity.WARNING
        assert "cannot be proven from pixels" in material.message
        assert material.evidence["source_material"]["material"] == "gold"
        assert material.evidence["target_material"]["material"] == "platinum"

    def test_domain_failure_becomes_a_targeted_retry_with_exact_delta(self):
        from facetta.image_agent.prompts import (
            compile_correction_prompt,
            compile_initial_prompt,
        )

        source_spec = HALO.model_copy(deep=True)
        target_spec = HALO.model_copy(deep=True)
        target_spec.metal.color = "rose"
        source = png((20, 20, 20))
        plan = build_image_plan(
            ImageOperation.LOCAL_EDIT,
            "change all metal to rose gold",
            spec=target_spec,
            source_spec=source_spec,
            source_image=source,
            region_description="all metal surfaces",
        )
        evaluator = RingQualityEvaluator(StaticInspector(edit=faithful_edit(
            domain_matches={"metal_identity": False},
        )))
        report = evaluator.evaluate(
            plan, png((40, 40, 40)), source_image=source, mask_bytes=None)

        retry, correction = compile_correction_prompt(
            plan, compile_initial_prompt(plan), report)

        assert "edit_domain:metal_identity" in correction
        assert '"path": "metal.color"' in correction
        assert "white -> rose" in retry
        assert "Do not compensate by changing another component" in retry

    def test_visible_band_silhouette_becomes_review_warning_when_vision_misses_it(
        self,
    ):
        source_spec = HALO.model_copy(deep=True)
        target_spec = HALO.model_copy(deep=True)
        source_spec.band.width_mm = 3.2
        target_spec.band.width_mm = 3.8
        def ring(stroke: int) -> bytes:
            image = Image.new("RGB", (256, 256), (200, 212, 226))
            draw = ImageDraw.Draw(image)
            draw.ellipse((55, 35, 205, 225), outline=(80, 85, 90),
                         width=stroke)
            draw.ellipse((105, 20, 155, 70), fill=(30, 50, 180))
            output = io.BytesIO()
            image.save(output, format="PNG")
            return output.getvalue()

        source = ring(10)
        candidate = ring(14)
        evaluator = RingQualityEvaluator(StaticInspector(edit=faithful_edit(
            change_applied=False,
            spec_change_matches=False,
        )))
        plan = build_image_plan(
            ImageOperation.LOCAL_EDIT,
            "widen the lower shank",
            spec=target_spec,
            source_spec=source_spec,
            source_image=source,
            region_description="lower shank",
        )

        result = evaluator.evaluate(
            plan, candidate, source_image=source, mask_bytes=None)

        assert result.verdict is QualityVerdict.WARN
        checks = {check.code: check for check in result.checks}
        assert checks["requested_change"].passed is True
        assert checks["spec_change"].passed is True
        assert checks["exact_band_width"].passed is False
        assert checks["exact_band_width"].severity is CheckSeverity.WARNING

    def test_band_width_vision_pass_cannot_waive_deterministic_reframing(self):
        source_spec = HALO.model_copy(deep=True)
        target_spec = HALO.model_copy(deep=True)
        source_spec.band.width_mm = 3.2
        target_spec.band.width_mm = 3.8

        def ring(stroke: int, *, inset: int = 0) -> bytes:
            image = Image.new("RGB", (256, 256), (200, 212, 226))
            draw = ImageDraw.Draw(image)
            draw.ellipse(
                (55 + inset, 35 + inset, 205 - inset, 225 - inset),
                outline=(80, 85, 90),
                width=stroke,
            )
            draw.ellipse((105, 20, 155, 70), fill=(30, 50, 180))
            output = io.BytesIO()
            image.save(output, format="PNG")
            return output.getvalue()

        source = ring(10)
        reframed = ring(16, inset=28)
        evaluator = RingQualityEvaluator(StaticInspector(edit=faithful_edit(
            domain_matches={"band_geometry": True},
        )))
        plan = build_image_plan(
            ImageOperation.LOCAL_EDIT,
            "widen the lower shank",
            spec=target_spec,
            source_spec=source_spec,
            source_image=source,
            region_description="lower shank",
        )

        result = evaluator.evaluate(
            plan, reframed, source_image=source, mask_bytes=None)

        checks = {check.code: check for check in result.checks}
        assert result.verdict is QualityVerdict.FAIL
        assert checks["requested_change"].passed is False
        assert checks["spec_change"].passed is False
        assert checks["edit_domain:band_geometry"].passed is False
        assert checks["band_edit_presentation_lock"].passed is False

    def test_visual_only_edit_cannot_change_geometry(self):
        evaluator = RingQualityEvaluator(StaticInspector(
            edit=faithful_edit(geometry_preserved=False)))
        plan = build_image_plan(
            ImageOperation.VISUAL_ONLY_EDIT,
            "replace the background with ivory",
            spec=HALO,
            source_image=png((10, 10, 10)),
        )
        result = evaluator.evaluate(plan, png((20, 20, 20)),
                                    source_image=png((10, 10, 10)),
                                    mask_bytes=None)
        assert result.verdict is QualityVerdict.FAIL
        assert "geometry_preserved" in {c.code for c in result.failed_checks}

    def test_deterministic_raster_and_unchanged_candidate_gates(self):
        evaluator = RingQualityEvaluator(StaticInspector(edit=faithful_edit()))
        source = png((10, 10, 10))
        plan = build_image_plan(
            ImageOperation.VISUAL_ONLY_EDIT,
            "replace the background with ivory",
            spec=HALO,
            source_image=source,
        )
        unchanged = evaluator.evaluate(
            plan, source, source_image=source, mask_bytes=None)
        assert unchanged.verdict is QualityVerdict.FAIL
        assert "candidate_changed" in {
            check.code for check in unchanged.failed_checks}

        corrupt = evaluator.evaluate(
            plan, b"not-an-image", source_image=source, mask_bytes=None)
        assert corrupt.verdict is QualityVerdict.FAIL
        assert "decodable_image" in {
            check.code for check in corrupt.failed_checks}


class TestClosedLoopRouting:
    def test_bounded_refine_correction_can_exceed_legacy_eight_thousand_chars(
        self,
        monkeypatch,
    ):
        original = "I" * 7_585
        corrected = original + ("C" * 935)
        monkeypatch.setattr(
            orchestrator_module, "compile_initial_prompt", lambda plan: original
        )
        monkeypatch.setattr(
            orchestrator_module,
            "compile_correction_prompt",
            lambda plan, initial, prior: (corrected, "bounded correction"),
        )
        provider = FakeProvider()
        evaluator = SequenceEvaluator(
            report(QualityVerdict.FAIL),
            report(QualityVerdict.PASS),
        )
        plan = build_image_plan(
            ImageOperation.REFERENCE_RENDER,
            "Match corresponding left and right necklace motifs.",
            source_image=b"source",
        )

        result = JewelryImageAgent(provider, evaluator).run(
            plan, source_image=b"source"
        )

        assert result.accepted is True
        assert len(provider.calls) == 2
        assert len(provider.calls[1]["prompt"]) == 8_520

    def test_exact_topology_warning_uses_targeted_retry_before_review(self):
        warning = ImageQualityReport(
            verdict=QualityVerdict.WARN,
            checks=(QualityCheck(
                code="target_spec_crosscheck:prong_count",
                passed=False,
                severity=CheckSeverity.WARNING,
                message="complete target prong count is not assessable",
            ),),
            score=60,
        )
        provider = FakeProvider()
        evaluator = SequenceEvaluator(
            warning,
            report(QualityVerdict.PASS),
        )
        plan = build_image_plan(
            ImageOperation.SPEC_RENDER,
            "render exactly six visible holding prongs",
            spec=HALO,
        )

        result = JewelryImageAgent(provider, evaluator).run(plan)

        assert result.accepted is True
        assert len(provider.calls) == 2
        assert "complete target prong count is not assessable" in (
            provider.calls[1]["prompt"])
        assert result.run.attempts[0].qa_verdict is QualityVerdict.WARN
        assert result.run.attempts[1].qa_verdict is QualityVerdict.PASS

    def test_uncertain_source_topology_runs_but_forces_designer_review(self):
        class ValidProvider(FakeProvider):
            def execute(
                self, plan, route, prompt, *, source_image, mask_bytes,
            ):
                self.calls.append({"route": route, "prompt": prompt})
                return ProviderImage(image_bytes=png((40, 40, 40)))

        source_spec = HALO.model_copy(deep=True)
        source_spec.setting.prong_count = 6
        source_spec.setting.style = "6_prong_basket"
        target_spec = source_spec.model_copy(deep=True)
        target_spec.setting.prong_count = 4
        target_spec.setting.style = "4_prong_basket"
        source = png((20, 20, 20))
        plan = build_image_plan(
            ImageOperation.LOCAL_EDIT,
            "change the center setting from six prongs to four prongs",
            spec=target_spec,
            source_spec=source_spec,
            source_image=source,
            region_description="the center setting",
        )
        provider = ValidProvider()
        evaluator = RingQualityEvaluator(
            StaticInspector(edit=faithful_edit(
                domain_matches={"setting": True},
            )),
            render_cross_inspector=StaticRenderCrossInspector(
                RenderCrossInspection(
                    setting_style_matches=True,
                    prong_count_matches=None,
                    observed_prong_count=5,
                    observed_prong_count_complete=False,
                )),
        )

        result = JewelryImageAgent(provider, evaluator).run(
            plan, source_image=source)

        assert len(provider.calls) == 3
        assert result.accepted is False
        assert result.review_required is True
        assert result.quality.verdict is QualityVerdict.WARN
        assert result.quality.score == 60.0
        source_check = next(
            check for check in result.quality.failed_checks
            if check.code == "source_topology:prong_count"
        )
        assert source_check.severity is CheckSeverity.WARNING

    def test_transient_qa_timeout_retries_same_candidate_not_provider(self):
        class FlakyEvaluator:
            def __init__(self):
                self.calls = []

            def evaluate(self, plan, candidate, *, source_image, mask_bytes):
                self.calls.append(candidate)
                if len(self.calls) == 1:
                    raise TimeoutError("vision SSL handshake timed out")
                return report(QualityVerdict.PASS)

        provider = FakeProvider()
        evaluator = FlakyEvaluator()
        plan = build_image_plan(
            ImageOperation.SPEC_RENDER,
            "render one exact ring",
            spec=HALO,
        )

        result = JewelryImageAgent(provider, evaluator).run(plan)

        assert len(provider.calls) == 1
        assert evaluator.calls == [b"candidate-1", b"candidate-1"]
        recovered = next(
            check for check in result.quality.checks
            if check.code == "evaluation_transport_recovered"
        )
        assert recovered.evidence == {
            "retry_count": 1,
            "image_regenerated": False,
        }

    def test_setting_edit_rejects_wrong_source_topology_before_provider(self):
        source_spec = HALO.model_copy(deep=True)
        source_spec.setting.prong_count = 6
        source_spec.setting.style = "6_prong_basket"
        target_spec = source_spec.model_copy(deep=True)
        target_spec.setting.prong_count = 4
        target_spec.setting.style = "4_prong_basket"
        source = png((20, 20, 20))
        plan = build_image_plan(
            ImageOperation.LOCAL_EDIT,
            "change the center setting from six prongs to four prongs",
            spec=target_spec,
            source_spec=source_spec,
            source_image=source,
            region_description="the center setting",
        )
        provider = FakeProvider()
        evaluator = RingQualityEvaluator(
            StaticInspector(edit=faithful_edit(
                domain_matches={"setting": True},
            )),
            render_cross_inspector=StaticRenderCrossInspector(
                RenderCrossInspection(
                    setting_style_matches=False,
                    prong_count_matches=False,
                    observed_prong_count=4,
                    observed_prong_count_complete=True,
                )),
        )

        with pytest.raises(ImageQualityFailure) as caught:
            JewelryImageAgent(provider, evaluator).run(
                plan, source_image=source)

        assert provider.calls == []
        assert caught.value.attempts == ()
        failed = {check.code: check for check in caught.value.report.failed_checks}
        assert failed["source_topology:prong_count"].evidence == {
            "expected": 6,
            "observed": 4,
            "complete": True,
        }

    def test_pass_stops_after_the_initial_grok_attempt(self):
        provider = FakeProvider()
        agent = JewelryImageAgent(provider, SequenceEvaluator(report(QualityVerdict.PASS)))
        plan = build_image_plan(ImageOperation.SPEC_RENDER, "studio render", spec=HALO)

        result = agent.run(plan)

        assert result.accepted is True and result.review_required is False
        assert result.run.verdict is QualityVerdict.PASS
        assert [call["route"] for call in provider.calls] == [
            ImageRoute.GROK_GENERATE]
        attempt = result.run.attempts[0]
        assert attempt.attempt_number == 1
        assert attempt.provider == "xai" and attempt.model == "grok_direct"
        assert attempt.provider_request_id == "req-1"
        assert attempt.qa_verdict is QualityVerdict.PASS

    def test_warning_returns_review_candidate_without_retry_or_acceptance(self):
        provider = FakeProvider()
        agent = JewelryImageAgent(provider, SequenceEvaluator(report(
            QualityVerdict.WARN,
            code="exact_dimensions",
            message="millimeters cannot be proven from this view",
        )))
        plan = build_image_plan(ImageOperation.SPEC_RENDER, "studio render", spec=HALO)

        result = agent.run(plan)

        assert result.accepted is False and result.review_required is True
        assert result.run.status.value == "review_required"
        assert result.image_bytes == b"candidate-1"
        assert len(provider.calls) == 1

    def test_result_is_json_safe_even_for_binary_image_bytes(self):
        provider = FakeProvider()
        provider.execute = lambda *args, **kwargs: ProviderImage(
            image_bytes=b"\x89PNG\r\n\x1a\n\xff")
        plan = build_image_plan(ImageOperation.SPEC_RENDER, "studio render", spec=HALO)
        result = JewelryImageAgent(
            provider,
            SequenceEvaluator(report(QualityVerdict.PASS)),
        ).run(plan)
        assert '"image_bytes":"iVBORw0KGgr_"' in result.model_dump_json()

    def test_grok_retry_uses_failure_specific_correction(self):
        provider = FakeProvider()
        evaluator = SequenceEvaluator(
            report(QualityVerdict.FAIL, "metal", "metal should be white, not yellow"),
            report(QualityVerdict.PASS),
        )
        plan = build_image_plan(ImageOperation.SPEC_RENDER, "studio render", spec=HALO)

        result = JewelryImageAgent(provider, evaluator).run(plan)

        assert result.accepted and len(provider.calls) == 2
        assert [c["route"] for c in provider.calls] == [
            ImageRoute.GROK_GENERATE,
            ImageRoute.GROK_GENERATE,
        ]
        correction = provider.calls[1]["prompt"]
        assert "metal: metal should be white, not yellow" in correction
        assert '"expected": "white gold"' in correction
        assert "every validated stone, setting, metal" in correction
        assert "not a redesign" in correction
        assert result.run.attempts[1].corrective_instruction

    def test_material_identity_failure_drives_targeted_grok_retry(self):
        provider = FakeProvider()
        base = SequenceEvaluator(
            report(QualityVerdict.PASS),
            report(QualityVerdict.PASS),
        )

        def raster(_approved, candidate):
            failed = candidate == b"candidate-1"
            return {
                "checked": True,
                "source_white_feature_pixels": 900,
                "white_to_gold_pixels": 300 if failed else 20,
                "white_to_gold_ratio": 0.333 if failed else 0.022,
                "failed": failed,
            }

        def material(_approved, candidate):
            failed = candidate == b"candidate-1"
            return {
                "checked": True,
                "consistent": not failed,
                "differences": ["diamonds became gold"] if failed else [],
                "severity": "major" if failed else "none",
            }

        evaluator = MaterialIdentityQualityEvaluator(
            b"approved-color-source",
            base=base,
            raster_audit=raster,
            material_audit=material,
        )
        source = b"confirmed-line-art"
        plan = build_image_plan(
            ImageOperation.VISUAL_ONLY_EDIT,
            "color the confirmed line art from the exact specification",
            spec=HALO,
            source_spec=HALO,
            source_image=source,
        )

        result = JewelryImageAgent(provider, evaluator).run(
            plan, source_image=source)

        assert result.accepted is True
        assert len(provider.calls) == 2
        assert "approved_source_material_identity" in provider.calls[1]["prompt"]
        assert "white-stone regions converted to gold" in provider.calls[1]["prompt"]
        assert result.run.attempts[0].qa_verdict is QualityVerdict.FAIL
        assert result.run.attempts[1].qa_verdict is QualityVerdict.PASS

    def test_cross_modality_raster_disagreement_requires_designer_review(self):
        evaluator = MaterialIdentityQualityEvaluator(
            b"approved-photo",
            base=SequenceEvaluator(report(QualityVerdict.PASS)),
            raster_audit=lambda *_: {
                "checked": True,
                "source_white_feature_pixels": 900,
                "white_to_gold_pixels": 280,
                "white_to_gold_ratio": 0.311,
                "failed": True,
            },
            material_audit=lambda *_: {
                "checked": True,
                "consistent": True,
                "differences": [],
                "severity": "none",
            },
        )
        source = b"line-art"
        plan = build_image_plan(
            ImageOperation.VISUAL_ONLY_EDIT,
            "color the confirmed line art",
            spec=HALO,
            source_image=source,
        )
        result = JewelryImageAgent(FakeProvider(), evaluator).run(
            plan, source_image=source)

        assert result.review_required is True
        assert result.run.verdict is QualityVerdict.WARN
        material = next(
            check for check in result.quality.checks
            if check.code == "approved_source_material_identity"
        )
        assert material.severity is CheckSeverity.WARNING
        assert material.evidence["severity"] == "disagreement"

    def test_colored_line_art_contract_corrects_photorealistic_replacement(self):
        provider = FakeProvider()
        base = SequenceEvaluator(
            report(QualityVerdict.PASS),
            report(QualityVerdict.PASS),
        )

        def line_art_audit(_source, candidate):
            photorealistic = candidate == b"candidate-1"
            return {
                "checked": True,
                "linework_retained": not photorealistic,
                "color_inside_existing_geometry": not photorealistic,
                "technical_illustration_style": not photorealistic,
                "photorealistic_replacement": photorealistic,
                "geometry_consistent": True,
                "differences": (
                    ["technical line drawing was replaced by a beauty render"]
                    if photorealistic else []
                ),
                "severity": "major" if photorealistic else "none",
            }

        evaluator = ColoredLineArtQualityEvaluator(
            b"approved-source",
            base=base,
            line_art_audit=line_art_audit,
        )
        source = b"confirmed-black-line-art"
        plan = build_image_plan(
            ImageOperation.VISUAL_ONLY_EDIT,
            "apply controlled color inside the confirmed line drawing",
            spec=HALO,
            source_spec=HALO,
            source_image=source,
        )

        result = JewelryImageAgent(provider, evaluator).run(
            plan, source_image=source
        )

        assert result.accepted is True
        assert len(provider.calls) == 2
        assert result.run.attempts[0].qa_verdict is QualityVerdict.FAIL
        assert result.run.attempts[1].qa_verdict is QualityVerdict.PASS
        assert "colored_line_art_contract" in provider.calls[1]["prompt"]
        assert "photorealistic" in provider.calls[1]["prompt"]

    def test_unavailable_colored_line_art_audit_requires_review(self):
        evaluator = ColoredLineArtQualityEvaluator(
            b"approved-source",
            base=SequenceEvaluator(report(QualityVerdict.PASS)),
            line_art_audit=lambda *_: {
                "checked": False,
                "linework_retained": None,
                "color_inside_existing_geometry": None,
                "technical_illustration_style": None,
                "photorealistic_replacement": None,
                "geometry_consistent": None,
                "differences": ["audit unavailable"],
                "severity": "unknown",
            },
        )
        source = b"confirmed-black-line-art"
        plan = build_image_plan(
            ImageOperation.VISUAL_ONLY_EDIT,
            "apply controlled color inside the confirmed line drawing",
            spec=HALO,
            source_image=source,
        )

        result = JewelryImageAgent(FakeProvider(), evaluator).run(
            plan, source_image=source
        )

        assert result.review_required is True
        contract = next(
            check for check in result.quality.checks
            if check.code == "colored_line_art_contract"
        )
        assert contract.severity is CheckSeverity.WARNING

    def test_line_art_contract_corrects_branding_and_count_drift(self):
        provider = FakeProvider()
        base = SequenceEvaluator(
            report(QualityVerdict.PASS),
            report(QualityVerdict.PASS),
        )

        def audit(_source, candidate, expected, focus):
            assert expected["setting"]["prong_count"] == 4
            assert "Count" in focus or "watermarks" in focus
            failed = candidate == b"candidate-1"
            return {
                "checked": True,
                "black_line_art_on_white": True,
                "single_assembled_view": True,
                "source_geometry_preserved": not failed,
                "center_prong_count_matches": True,
                "observed_center_prong_count": 4,
                "side_stone_inventory_matches": not failed,
                "observed_side_stone_counts": [10 if failed else 8],
                "candidate_text_or_branding_detected": failed,
                "colored_or_photorealistic": False,
                "differences": (
                    ["social watermark and two extra halo stones"]
                    if failed else []
                ),
                "severity": "major" if failed else "none",
            }

        evaluator = ConfirmedLineArtQualityEvaluator(
            base=base,
            line_art_audit=audit,
        )
        source = b"imported-designer-plate"
        plan = build_image_plan(
            ImageOperation.VISUAL_ONLY_EDIT,
            "convert the exact ring into one black technical line drawing",
            spec=HALO,
            source_spec=HALO,
            source_image=source,
        )

        result = JewelryImageAgent(provider, evaluator).run(
            plan, source_image=source
        )

        assert result.accepted is True
        assert len(provider.calls) == 2
        assert result.run.attempts[0].qa_verdict is QualityVerdict.FAIL
        assert result.run.attempts[1].qa_verdict is QualityVerdict.PASS
        correction = provider.calls[1]["prompt"]
        assert "confirmed_line_art_contract" in correction
        assert "watermark" in correction
        assert "side-stone counts" in correction

    def test_unavailable_line_art_double_audit_requires_review(self):
        evaluator = ConfirmedLineArtQualityEvaluator(
            base=SequenceEvaluator(report(QualityVerdict.PASS)),
            line_art_audit=lambda *_: {
                "checked": False,
                "black_line_art_on_white": None,
                "single_assembled_view": None,
                "source_geometry_preserved": None,
                "center_prong_count_matches": None,
                "observed_center_prong_count": None,
                "side_stone_inventory_matches": None,
                "observed_side_stone_counts": [],
                "candidate_text_or_branding_detected": None,
                "colored_or_photorealistic": None,
                "differences": ["audit unavailable"],
                "severity": "unknown",
            },
        )
        source = b"imported-designer-plate"
        plan = build_image_plan(
            ImageOperation.VISUAL_ONLY_EDIT,
            "convert to black technical line art",
            spec=HALO,
            source_image=source,
        )

        result = JewelryImageAgent(FakeProvider(), evaluator).run(
            plan, source_image=source
        )

        assert result.review_required is True
        contract = next(
            check for check in result.quality.checks
            if check.code == "confirmed_line_art_contract"
        )
        assert contract.severity is CheckSeverity.WARNING

    def test_local_edit_uses_kontext_only_after_two_grok_qa_failures(self):
        provider = FakeProvider()
        evaluator = SequenceEvaluator(
            report(QualityVerdict.FAIL, "requested_change", "band stayed narrow"),
            report(QualityVerdict.FAIL, "protected_regions", "halo drifted"),
            report(QualityVerdict.PASS),
        )
        source = b"source"
        plan = build_image_plan(
            ImageOperation.LOCAL_EDIT,
            "widen the band to 2.4 mm",
            spec=HALO,
            source_image=source,
            region_description="the lower shank",
        )

        result = JewelryImageAgent(provider, evaluator).run(
            plan,
            source_image=source,
        )

        assert [call["route"] for call in provider.calls] == [
            ImageRoute.GROK_EDIT,
            ImageRoute.GROK_EDIT,
            ImageRoute.FLUX_KONTEXT_EDIT,
        ]
        third = result.run.attempts[2]
        assert third.fallback is True
        assert third.fallback_reason == "grok_qa_failed"
        assert third.provider == "fal" and third.model == "flux_kontext"

    def test_generation_fallback_is_flux_not_kontext(self):
        provider = FakeProvider()
        evaluator = SequenceEvaluator(
            report(QualityVerdict.FAIL),
            report(QualityVerdict.FAIL),
            report(QualityVerdict.PASS),
        )
        plan = build_image_plan(ImageOperation.CONCEPT_GENERATE,
                                "an oval sapphire cathedral ring")
        JewelryImageAgent(provider, evaluator).run(plan)
        assert provider.calls[2]["route"] is ImageRoute.FLUX_GENERATE

    def test_default_policy_uses_openai_for_the_full_retry_budget_when_xai_is_unavailable(
        self, monkeypatch,
    ):
        monkeypatch.delenv("XAI_KEY", raising=False)
        monkeypatch.delenv("XAI_API_KEY", raising=False)
        monkeypatch.delenv("FAL_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "test-only")
        monkeypatch.setattr(
            "facetta.image_agent.providers.env_value",
            lambda key, default=None: {
                "XAI_KEY": None,
                "FAL_KEY": None,
                "OPENAI_API_KEY": "test-only",
            }.get(key, default),
        )
        provider = FakeProvider()
        evaluator = SequenceEvaluator(
            report(QualityVerdict.FAIL),
            report(QualityVerdict.FAIL),
            report(QualityVerdict.PASS),
        )
        plan = build_image_plan(
            ImageOperation.CREATIVE_GENERATE,
            "a platinum floral lariat necklace",
        )

        result = JewelryImageAgent(
            provider,
            evaluator,
            use_available_fallback=True,
        ).run(plan)

        assert [call["route"] for call in provider.calls] == [
            ImageRoute.OPENAI_GENERATE,
            ImageRoute.OPENAI_GENERATE,
            ImageRoute.OPENAI_GENERATE,
        ]
        assert result.run.attempts[-1].fallback_reason is None

    def test_openai_fallback_also_runs_after_two_grok_provider_failures(
        self, monkeypatch,
    ):
        monkeypatch.setenv("XAI_KEY", "test-only")
        monkeypatch.delenv("FAL_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "test-only")
        provider = FakeProvider(failures={
            1: ProviderCallError("xai unavailable"),
            2: ProviderCallError("xai unavailable"),
        })
        plan = build_image_plan(
            ImageOperation.SPEC_RENDER,
            "one exact validated ring render",
            spec=HALO,
        )

        result = JewelryImageAgent(
            provider,
            SequenceEvaluator(report(QualityVerdict.PASS)),
            use_available_fallback=True,
        ).run(plan)

        assert [call["route"] for call in provider.calls] == [
            ImageRoute.GROK_GENERATE,
            ImageRoute.GROK_GENERATE,
            ImageRoute.OPENAI_GENERATE,
        ]
        assert result.run.attempts[-1].fallback_reason == "grok_provider_failed"

    def test_xai_quota_403_skips_duplicate_grok_and_uses_openai_fallback(
        self,
        monkeypatch,
    ):
        monkeypatch.setenv("XAI_KEY", "test-only")
        monkeypatch.delenv("FAL_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "test-only")
        quota_failure = _provider_call_error(
            ImageRoute.GROK_GENERATE,
            render_failure(
                403,
                "Your team 7f3959c1 has either used all available credits or "
                "reached its monthly spending limit. To continue making API "
                "requests, please purchase more credits or raise your spending "
                "limit.",
            ),
        )
        provider = FakeProvider(failures={1: quota_failure})
        plan = build_image_plan(
            ImageOperation.CREATIVE_GENERATE,
            "a symmetric ruby necklace",
        )

        result = JewelryImageAgent(
            provider,
            SequenceEvaluator(report(QualityVerdict.PASS)),
            use_available_fallback=True,
        ).run(plan)

        assert [call["route"] for call in provider.calls] == [
            ImageRoute.GROK_GENERATE,
            ImageRoute.OPENAI_GENERATE,
        ]
        assert result.run.attempts[0].error is not None
        assert result.run.attempts[0].error.retryable is False
        assert result.run.attempts[0].error.code == "xai_quota_exhausted"
        assert result.run.attempts[1].fallback_reason == "grok_provider_failed"

    def test_openai_fallback_keeps_one_bounded_quality_correction(
        self,
        monkeypatch,
    ):
        monkeypatch.setenv("XAI_KEY", "test-only")
        monkeypatch.delenv("FAL_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "test-only")
        quota_failure = _provider_call_error(
            ImageRoute.GROK_GENERATE,
            render_failure(403, "monthly spending limit reached"),
        )
        provider = FakeProvider(failures={1: quota_failure})
        evaluator = SequenceEvaluator(
            report(
                QualityVerdict.FAIL,
                "six_leaf_ruby_pattern",
                "ruby motif pair 1 is missing a left or right audit",
            ),
            report(QualityVerdict.PASS),
        )
        plan = build_image_plan(
            ImageOperation.CREATIVE_GENERATE,
            "a symmetric six-leaf ruby necklace",
        )

        result = JewelryImageAgent(
            provider,
            evaluator,
            use_available_fallback=True,
        ).run(plan)

        assert [call["route"] for call in provider.calls] == [
            ImageRoute.GROK_GENERATE,
            ImageRoute.OPENAI_GENERATE,
            ImageRoute.OPENAI_GENERATE,
        ]
        assert result.accepted is True
        assert result.run.attempts[2].corrective_instruction is not None
        assert "six_leaf_ruby_pattern" in (
            result.run.attempts[2].corrective_instruction or ""
        )

    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_transient_xai_failures_keep_same_provider_retry(
        self,
        monkeypatch,
        status,
    ):
        monkeypatch.setenv("XAI_KEY", "test-only")
        monkeypatch.delenv("FAL_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "test-only")
        transient = _provider_call_error(
            ImageRoute.GROK_GENERATE,
            render_failure(status, "temporarily unavailable"),
        )
        provider = FakeProvider(failures={1: transient})
        plan = build_image_plan(
            ImageOperation.CREATIVE_GENERATE,
            "a symmetric ruby necklace",
        )

        result = JewelryImageAgent(
            provider,
            SequenceEvaluator(report(QualityVerdict.PASS)),
            use_available_fallback=True,
        ).run(plan)

        assert transient.retryable is True
        assert transient.fallback_eligible is False
        assert [call["route"] for call in provider.calls] == [
            ImageRoute.GROK_GENERATE,
            ImageRoute.GROK_GENERATE,
        ]
        assert result.accepted is True

    def test_generic_xai_403_does_not_impersonate_quota_exhaustion(self):
        failure = _provider_call_error(
            ImageRoute.GROK_GENERATE,
            render_failure(403, "this key cannot access the requested model"),
        )

        assert failure.retryable is True
        assert failure.fallback_eligible is False
        assert failure.code == "image_provider_call_failed"
        assert xai_quota_cooldown_active() is False

    def test_quota_cooldown_routes_around_xai_then_expires(
        self,
        monkeypatch,
    ):
        now = [100.0]
        monkeypatch.setattr(
            "facetta.image_agent.providers.time.monotonic", lambda: now[0],
        )
        monkeypatch.setenv("XAI_KEY", "xai-key")
        monkeypatch.delenv("FAL_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "openai-key")

        failure = _provider_call_error(
            ImageRoute.GROK_EDIT,
            render_failure(403, "monthly spending limit reached"),
        )
        note_xai_quota_exhausted()

        assert failure.code == "xai_quota_exhausted"
        assert xai_quota_cooldown_active() is True
        assert available_configured_route(
            ImageRoute.GROK_EDIT,
        ) is ImageRoute.OPENAI_EDIT
        assert available_configured_route(
            ImageRoute.GROK_GENERATE,
        ) is ImageRoute.OPENAI_GENERATE

        now[0] += 901
        assert xai_quota_cooldown_active() is False
        assert available_configured_route(
            ImageRoute.GROK_EDIT,
        ) is ImageRoute.GROK_EDIT

    def test_render_adapter_opens_cooldown_on_confirmed_xai_quota(
        self,
        monkeypatch,
    ):
        plan = build_image_plan(
            ImageOperation.CREATIVE_GENERATE,
            "a symmetric ruby necklace",
        )
        monkeypatch.setattr(
            "facetta.render.generate_image",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                render_failure(403, "monthly spending limit reached")
            ),
        )

        with pytest.raises(ProviderCallError) as caught:
            RenderPrimitiveProvider().execute(
                plan,
                ImageRoute.GROK_GENERATE,
                "prompt",
                source_image=None,
                mask_bytes=None,
            )

        assert caught.value.code == "xai_quota_exhausted"
        assert xai_quota_cooldown_active() is True

    def test_quota_cooldown_without_fallback_keeps_honest_xai_route(
        self,
        monkeypatch,
    ):
        monkeypatch.setenv("XAI_KEY", "xai-key")
        monkeypatch.delenv("FAL_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        _provider_call_error(
            ImageRoute.GROK_GENERATE,
            render_failure(403, "quota exhausted"),
        )
        note_xai_quota_exhausted()

        assert xai_quota_cooldown_active() is True
        assert available_configured_route(
            ImageRoute.GROK_GENERATE,
        ) is ImageRoute.GROK_GENERATE

    def test_three_failed_candidates_raise_structured_quality_failure(self):
        provider = FakeProvider()
        evaluator = SequenceEvaluator(
            report(QualityVerdict.FAIL),
            report(QualityVerdict.FAIL),
            report(QualityVerdict.FAIL),
        )
        plan = build_image_plan(ImageOperation.SPEC_RENDER, "studio render", spec=HALO)

        with pytest.raises(ImageQualityFailure) as caught:
            JewelryImageAgent(provider, evaluator).run(plan)

        assert len(caught.value.attempts) == 3
        assert caught.value.category.value == "quality"
        assert caught.value.report.verdict is QualityVerdict.FAIL
        assert caught.value.attempts[-1].fallback

    def test_failed_grok_qa_remains_quality_when_fallback_is_unconfigured(self):
        provider = FakeProvider(failures={
            3: ProviderCallError(
                "no FAL_KEY configured",
                code="provider_not_configured",
                retryable=False,
            ),
        })
        evaluator = SequenceEvaluator(
            report(QualityVerdict.FAIL, "material", "diamonds became gold"),
            report(QualityVerdict.FAIL, "material", "diamonds still gold"),
        )
        plan = build_image_plan(
            ImageOperation.VISUAL_ONLY_EDIT,
            "color confirmed line art",
            spec=HALO,
            source_image=b"line-art",
        )

        with pytest.raises(ImageQualityFailure) as caught:
            JewelryImageAgent(provider, evaluator).run(
                plan, source_image=b"line-art")

        assert caught.value.category.value == "quality"
        assert len(caught.value.attempts) == 3
        assert caught.value.attempts[-1].error_category.value == "provider"
        assert caught.value.attempts[-1].fallback_reason == "grok_qa_failed"

    def test_unsafe_fallback_policy_stops_after_two_grok_attempts(self):
        provider = FakeProvider()
        evaluator = SequenceEvaluator(
            report(QualityVerdict.FAIL),
            report(QualityVerdict.FAIL),
        )
        plan = build_image_plan(
            ImageOperation.SPEC_RENDER,
            "studio render",
            spec=HALO,
            allow_fallback=False,
        )

        with pytest.raises(ImageQualityFailure) as caught:
            JewelryImageAgent(provider, evaluator).run(plan)

        assert len(caught.value.attempts) == 2
        assert all(a.route is ImageRoute.GROK_GENERATE for a in caught.value.attempts)

    def test_provider_failures_remain_distinct_from_quality_failures(self):
        provider = FakeProvider(failures={
            1: ProviderCallError("xai unavailable"),
            2: ProviderCallError("xai unavailable"),
            3: ProviderCallError("fal unavailable"),
        })
        plan = build_image_plan(ImageOperation.SPEC_RENDER, "studio render", spec=HALO)

        with pytest.raises(ImageProviderFailure) as caught:
            JewelryImageAgent(provider, SequenceEvaluator()).run(plan)

        assert len(caught.value.attempts) == 3
        assert all(a.error_category.value == "provider"
                   for a in caught.value.attempts)
        assert caught.value.attempts[-1].fallback_reason == "grok_provider_failed"


def test_configured_fallback_provider_and_route_share_one_priority(
    monkeypatch, tmp_path,
):
    monkeypatch.setattr(
        "facetta.config.DEFAULT_ENV_FILES", (tmp_path / "missing.env",),
    )
    monkeypatch.delenv("XAI_KEY", raising=False)
    monkeypatch.delenv("FAL_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert configured_fallback_provider() is None
    assert available_fallback_route(
        ImageRoute.FLUX_KONTEXT_EDIT
    ) is ImageRoute.FLUX_KONTEXT_EDIT

    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    assert configured_fallback_provider() == "openai"
    assert available_fallback_route(
        ImageRoute.FLUX_KONTEXT_EDIT
    ) is ImageRoute.OPENAI_EDIT
    assert available_fallback_route(
        ImageRoute.FLUX_GENERATE
    ) is ImageRoute.OPENAI_GENERATE
    assert available_configured_route(
        ImageRoute.GROK_GENERATE
    ) is ImageRoute.OPENAI_GENERATE
    assert available_configured_route(
        ImageRoute.GROK_EDIT
    ) is ImageRoute.OPENAI_EDIT

    monkeypatch.setenv("FAL_KEY", "test-only")
    assert configured_fallback_provider() == "fal"
    assert available_fallback_route(
        ImageRoute.FLUX_KONTEXT_EDIT
    ) is ImageRoute.FLUX_KONTEXT_EDIT

    monkeypatch.setenv("XAI_KEY", "test-only")
    assert available_configured_route(
        ImageRoute.GROK_GENERATE
    ) is ImageRoute.GROK_GENERATE


def test_material_identity_guard_reports_lost_pave_as_major():
    from facetta.image_agent.vision import check_material_identity

    def inspect(system, source, candidate, ask):
        assert "MATERIAL ASSIGNMENT" in system
        assert source == b"approved" and candidate == b"colored"
        assert "stone and metal zone" in ask
        return {
            "consistent": False,
            "differences": ["diamond leaf pavé became plain metal"],
            "severity": "major",
        }

    result = check_material_identity(
        b"approved", b"colored", inspect_pair=inspect)
    assert result["checked"] is True
    assert result["consistent"] is False
    assert result["severity"] == "major"

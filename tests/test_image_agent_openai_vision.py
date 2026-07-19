"""OpenAI prompt-concept QA routing and transport tests (never real network)."""

from __future__ import annotations

import json
import io

import pytest
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from facetta.image_agent import (
    GrokPromptCreativeRenderInspector,
    FocusedSixLeafRubyPatternInspector,
    ImageOperation,
    ImageRoute,
    OpenAIPromptCreativeRenderInspector,
    RingQualityEvaluator,
    build_image_plan,
)
from facetta.image_agent import quality as quality_module
from facetta.image_agent import providers as providers_module
from facetta.image_agent import vision as vision_module
from facetta.provider_errors import RenderUnavailable
from facetta.source_understanding import compile_rough_drawing_intent_brief


def _inspection_payload() -> dict:
    return {
        "coherent_jewelry_render": True,
        "complete_piece_visible": True,
        "source_design_preserved": None,
        "visible_components_preserved": None,
        "requested_presentation_applied": True,
        "explicit_counts_match": True,
        "explicit_stone_facts_match": True,
        "text_or_branding_detected": False,
        "major_unintended_changes": [],
        "score": 96,
        "notes": ["one complete coherent ring is visible"],
    }


def _png(color: tuple[int, int, int]) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(output, format="PNG")
    return output.getvalue()


def _comparison_inspection_payload(*, preserved: bool) -> dict:
    return {
        "coherent_jewelry_render": True,
        "complete_piece_visible": True,
        "source_design_preserved": preserved,
        "visible_components_preserved": preserved,
        "local_geometry_preserved": preserved,
        "repeated_element_pattern_preserved": preserved,
        "stone_shape_and_cut_family_preserved": preserved,
        "requested_presentation_applied": True,
        "text_or_branding_detected": False,
        "major_unintended_changes": (
            [] if preserved else [
                "candidate has four shoulder stones where the source has three"
            ]
        ),
        "score": 97 if preserved else 35,
        "notes": [
            (
                "four center claws and three round stones per shoulder match"
                if preserved else
                "the assessable repeated-element count does not match"
            )
        ],
    }


def test_openai_prompt_inspector_sends_direction_and_returns_typed_result(
    monkeypatch,
):
    captured: dict[str, object] = {}

    def inspect(
        system: str,
        candidate: bytes,
        ask: str,
        *,
        response_schema: dict | None = None,
    ) -> dict:
        captured.update(
            system=system,
            candidate=candidate,
            ask=ask,
            response_schema=response_schema,
        )
        return _inspection_payload()

    monkeypatch.setattr(quality_module, "openai_vision_json", inspect)
    plan = build_image_plan(
        ImageOperation.CREATIVE_GENERATE,
        "a polished yellow-gold ring with exactly three round diamonds",
    )

    result = OpenAIPromptCreativeRenderInspector().inspect_render(
        plan, b"candidate-image")

    assert result.coherent_jewelry_render is True
    assert result.complete_piece_visible is True
    assert captured["candidate"] == b"candidate-image"
    assert "exactly three round diamonds" in str(captured["ask"])
    assert '"complete_piece_visible"' in str(captured["system"])
    assert '"left_count":0,"right_count":0' not in str(captured["system"])
    assert '"left_count":1,"right_count":1' in str(captured["system"])
    assert captured["response_schema"] == (
        quality_module.CreativeRenderInspection.model_json_schema()
    )
    assert '"diamond|tsavorite|other"' not in str(captured["system"])


def test_focused_six_leaf_inspector_requests_an_exhaustive_strict_inventory(
    monkeypatch,
):
    captured: dict[str, object] = {}

    def inspect(system, candidate, ask, response_schema):
        captured.update(
            system=system,
            candidate=candidate,
            ask=ask,
            response_schema=response_schema,
        )
        return {"audits": [], "notes": ["no ruby motifs visible"]}

    monkeypatch.setattr(quality_module, "_qa_vision_json", inspect)
    plan = build_image_plan(
        ImageOperation.CREATIVE_GENERATE,
        "Every ruby flower has six alternating diamond and tsavorite leaves.",
    )

    result = FocusedSixLeafRubyPatternInspector().inspect_render(
        plan, b"candidate-image", (),
    )

    assert result.audits == ()
    assert "Inventory EVERY visible ruby motif" in str(captured["system"])
    assert "incidental ruby accent" in str(captured["system"])
    assert "Broad necklace coverage checklist" in str(captured["ask"])
    assert captured["response_schema"] == (
        quality_module.SixLeafRubyPatternInspection.model_json_schema()
    )


@pytest.mark.parametrize(
    ("xai", "openai", "expected"),
    [
        ("xai-key", "openai-key", GrokPromptCreativeRenderInspector),
        (None, "openai-key", OpenAIPromptCreativeRenderInspector),
        (None, None, GrokPromptCreativeRenderInspector),
    ],
)
def test_prompt_qa_provider_selection_is_deterministic(
    monkeypatch, xai, openai, expected,
):
    values = {"XAI_KEY": xai, "OPENAI_API_KEY": openai}
    monkeypatch.setattr(
        quality_module, "env_value", lambda key, default=None: values.get(key, default))

    evaluator = RingQualityEvaluator()

    assert isinstance(evaluator._prompt_creative_inspector, expected)


def test_qa_fallback_does_not_change_grok_primary_image_routes(monkeypatch):
    values = {"XAI_KEY": "xai-key", "OPENAI_API_KEY": "openai-key"}
    monkeypatch.setattr(
        providers_module,
        "env_value",
        lambda key, default=None: values.get(key, default),
    )

    assert providers_module.available_configured_route(
        ImageRoute.GROK_GENERATE,
    ) is ImageRoute.GROK_GENERATE
    assert providers_module.available_configured_route(
        ImageRoute.GROK_EDIT,
    ) is ImageRoute.GROK_EDIT


def test_grok_pair_qa_retries_openai_only_when_provider_is_unavailable(
    monkeypatch,
):
    calls: list[str] = []
    monkeypatch.setattr(
        quality_module,
        "env_value",
        lambda key, default=None: (
            "openai-key" if key == "OPENAI_API_KEY" else default
        ),
    )

    def unavailable(*_args):
        calls.append("grok")
        raise vision_module.VisionProviderUnavailable("xAI returned 403")

    def inspect_openai(*_args):
        calls.append("openai")
        return _comparison_inspection_payload(preserved=True)

    monkeypatch.setattr(quality_module, "vision_json_pair", unavailable)
    monkeypatch.setattr(
        quality_module, "openai_vision_json_pair", inspect_openai,
    )
    plan = build_image_plan(
        ImageOperation.REFERENCE_RENDER,
        "Preserve this exact rough drawing as a polished jewelry render.",
        source_image=b"rough-sketch",
    )

    result = quality_module.GrokCreativeRenderInspector().inspect_render(
        plan, b"rough-sketch", b"candidate",
    )

    assert result.source_design_preserved is True
    assert calls == ["grok", "openai"]


def test_grok_single_qa_retries_openai_only_when_provider_is_unavailable(
    monkeypatch,
):
    calls: list[str] = []
    monkeypatch.setattr(
        quality_module,
        "env_value",
        lambda key, default=None: (
            "openai-key" if key == "OPENAI_API_KEY" else default
        ),
    )

    def unavailable(*_args):
        calls.append("grok")
        raise vision_module.VisionProviderUnavailable("xAI timed out")

    def inspect_openai(*_args, **kwargs):
        calls.append("openai")
        assert kwargs["response_schema"] == (
            quality_module.CreativeRenderInspection.model_json_schema()
        )
        return _inspection_payload()

    monkeypatch.setattr(quality_module, "vision_json", unavailable)
    monkeypatch.setattr(quality_module, "openai_vision_json", inspect_openai)
    plan = build_image_plan(
        ImageOperation.CREATIVE_GENERATE,
        "A balanced three-stone yellow-gold ring.",
    )

    result = quality_module.GrokPromptCreativeRenderInspector().inspect_render(
        plan, b"candidate",
    )

    assert result.coherent_jewelry_render is True
    assert calls == ["grok", "openai"]


@pytest.mark.parametrize(
    "failure",
    [
        RenderUnavailable("xAI returned malformed JSON"),
        RenderUnavailable("xAI response did not match the QA schema"),
    ],
)
def test_grok_qa_does_not_fallback_for_response_or_schema_failures(
    monkeypatch,
    failure,
):
    monkeypatch.setattr(
        quality_module,
        "env_value",
        lambda key, default=None: (
            "openai-key" if key == "OPENAI_API_KEY" else default
        ),
    )
    monkeypatch.setattr(
        quality_module,
        "vision_json_pair",
        lambda *_args: (_ for _ in ()).throw(failure),
    )
    monkeypatch.setattr(
        quality_module,
        "openai_vision_json_pair",
        lambda *_args: pytest.fail("contract failures must not change reviewer"),
    )
    plan = build_image_plan(
        ImageOperation.REFERENCE_RENDER,
        "Preserve the source.",
        source_image=b"source",
    )

    with pytest.raises(RenderUnavailable) as caught:
        quality_module.GrokCreativeRenderInspector().inspect_render(
            plan, b"source", b"candidate",
        )

    assert caught.value is failure


def test_grok_qa_does_not_fallback_after_typed_contract_validation_fails(
    monkeypatch,
):
    monkeypatch.setattr(
        quality_module,
        "env_value",
        lambda key, default=None: (
            "openai-key" if key == "OPENAI_API_KEY" else default
        ),
    )
    monkeypatch.setattr(
        quality_module,
        "vision_json_pair",
        lambda *_args: {"score": "not-a-number"},
    )
    monkeypatch.setattr(
        quality_module,
        "openai_vision_json_pair",
        lambda *_args: pytest.fail("typed validation must fail closed"),
    )
    plan = build_image_plan(
        ImageOperation.REFERENCE_RENDER,
        "Preserve the source.",
        source_image=b"source",
    )

    with pytest.raises(ValidationError):
        quality_module.GrokCreativeRenderInspector().inspect_render(
            plan, b"source", b"candidate",
        )


class _FakeResponse:
    def __init__(self, payload: object, *, status_error: Exception | None = None):
        self._payload = payload
        self._status_error = status_error

    def raise_for_status(self) -> None:
        if self._status_error is not None:
            raise self._status_error

    def json(self) -> object:
        return self._payload


@pytest.mark.parametrize(
    ("status", "is_availability_failure"),
    [
        (403, True),
        (503, True),
        (422, False),
    ],
)
def test_xai_vision_transport_classifies_only_fallback_safe_statuses(
    monkeypatch,
    status,
    is_availability_failure,
):
    import httpx

    request = httpx.Request(
        "POST", "https://api.x.ai/v1/chat/completions",
    )
    response = httpx.Response(status, request=request)
    status_error = httpx.HTTPStatusError(
        f"xAI returned {status}",
        request=request,
        response=response,
    )
    monkeypatch.setattr(vision_module, "env_value", lambda _key: "xai-key")
    monkeypatch.setattr(
        "httpx.post",
        lambda *_args, **_kwargs: _FakeResponse(
            {}, status_error=status_error,
        ),
    )

    with pytest.raises(RenderUnavailable) as caught:
        vision_module.vision_json_pair(
            "Compare source and candidate.",
            b"source",
            b"candidate",
            "Audit.",
        )

    assert isinstance(
        caught.value, vision_module.VisionProviderUnavailable,
    ) is is_availability_failure


def test_openai_vision_transport_uses_image_data_url_and_json_mode(monkeypatch):
    captured: dict[str, object] = {}

    def post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return _FakeResponse({
            "output": [{
                "type": "message",
                "content": [{
                    "type": "output_text",
                    "text": json.dumps(_inspection_payload()),
                }],
            }],
        })

    monkeypatch.setattr(vision_module, "env_value", lambda key: "test-key")
    monkeypatch.setattr("httpx.post", post)

    result = vision_module.openai_vision_json(
        "Return the audit as JSON.", b"not-a-real-image", "Inspect it.")

    request = captured["json"]
    assert result["score"] == 96
    assert captured["url"] == "https://api.openai.com/v1/responses"
    assert request["text"]["format"] == {"type": "json_object"}
    assert request["max_output_tokens"] == 4000
    image = request["input"][1]["content"][0]
    assert image["type"] == "input_image"
    assert image["image_url"].startswith("data:image/png;base64,")
    assert captured["headers"] == {"Authorization": "Bearer test-key"}


def test_openai_vision_transport_uses_strict_pydantic_schema(monkeypatch):
    class VisionContract(BaseModel):
        model_config = ConfigDict(extra="forbid")

        visible_count: int = 1
        optional_note: str | None = Field(
            default=None, min_length=1, max_length=80,
        )

    captured: dict[str, object] = {}

    def post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return _FakeResponse({
            "output_text": json.dumps({
                "visible_count": 3,
                "optional_note": None,
            }),
        })

    monkeypatch.setattr(vision_module, "env_value", lambda key: "test-key")
    monkeypatch.setattr("httpx.post", post)
    pydantic_schema = VisionContract.model_json_schema()

    result = vision_module.openai_vision_json(
        "Return the audit contract.",
        b"not-a-real-image",
        "Inspect it.",
        pydantic_schema,
    )

    assert result == {"visible_count": 3, "optional_note": None}
    text_format = captured["json"]["text"]["format"]
    assert text_format["type"] == "json_schema"
    assert text_format["name"] == "facetta_vision_contract"
    assert text_format["strict"] is True
    schema = text_format["schema"]
    assert schema["required"] == ["visible_count", "optional_note"]
    assert schema["additionalProperties"] is False
    assert "default" not in schema["properties"]["visible_count"]
    assert "default" not in schema["properties"]["optional_note"]
    assert schema["properties"]["optional_note"]["anyOf"] == [
        {"type": "string"},
        {"type": "null"},
    ]
    assert "minLength" not in schema["properties"]["optional_note"]["anyOf"][0]
    assert "maxLength" not in schema["properties"]["optional_note"]["anyOf"][0]
    # Sanitizing a request must not mutate a reusable Pydantic schema.
    assert pydantic_schema["properties"]["visible_count"]["default"] == 1
    assert pydantic_schema["properties"]["optional_note"]["default"] is None
    assert pydantic_schema["properties"]["optional_note"]["anyOf"][0]["minLength"] == 1
    assert pydantic_schema["properties"]["optional_note"]["anyOf"][0]["maxLength"] == 80


def test_openai_vision_transport_fails_closed_on_malformed_output(monkeypatch):
    monkeypatch.setattr(vision_module, "env_value", lambda key: "test-key")
    monkeypatch.setattr(
        "httpx.post", lambda *args, **kwargs: _FakeResponse({"output": []}))

    with pytest.raises(RenderUnavailable, match="did not contain output text"):
        vision_module.openai_vision_json(
            "Return JSON.", b"candidate", "Inspect it.")


def test_configured_single_vision_forwards_schema_only_to_openai(monkeypatch):
    schema = {
        "type": "object",
        "properties": {"visible_count": {"type": "integer"}},
        "required": ["visible_count"],
        "additionalProperties": False,
    }
    values = {"XAI_KEY": None, "OPENAI_API_KEY": "openai-key"}
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        vision_module,
        "env_value",
        lambda key, default=None: values.get(key, default),
    )

    def inspect(system, image, prompt, response_schema):
        captured.update(
            system=system,
            image=image,
            prompt=prompt,
            schema=response_schema,
        )
        return {"visible_count": 3}

    monkeypatch.setattr(vision_module, "openai_vision_json", inspect)
    monkeypatch.setattr(
        vision_module,
        "vision_json",
        lambda *_args: pytest.fail("XAI is not configured"),
    )

    result = vision_module.configured_vision_json(
        "system", b"image", "prompt", schema,
    )

    assert result == {"visible_count": 3}
    assert captured["schema"] is schema


def test_configured_single_vision_keeps_xai_call_shape_with_schema(monkeypatch):
    values = {"XAI_KEY": "xai-key", "OPENAI_API_KEY": "openai-key"}
    calls: list[tuple[str, bytes, str]] = []
    monkeypatch.setattr(
        vision_module,
        "env_value",
        lambda key, default=None: values.get(key, default),
    )

    def inspect(system, image, prompt):
        calls.append((system, image, prompt))
        return {"visible_count": 3}

    monkeypatch.setattr(vision_module, "vision_json", inspect)
    monkeypatch.setattr(
        vision_module,
        "openai_vision_json",
        lambda *_args: pytest.fail("XAI must remain primary"),
    )

    result = vision_module.configured_vision_json(
        "system",
        b"image",
        "prompt",
        {"type": "object"},
    )

    assert result == {"visible_count": 3}
    assert calls == [("system", b"image", "prompt")]


def test_openai_pair_transport_sends_reference_before_candidate(monkeypatch):
    captured: dict[str, object] = {}

    def post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return _FakeResponse({
            "output_text": json.dumps({
                "change_applied": True,
                "protected_regions_preserved": True,
            }),
        })

    monkeypatch.setattr(vision_module, "env_value", lambda key: "test-key")
    monkeypatch.setattr("httpx.post", post)

    result = vision_module.openai_vision_json_pair(
        "Compare source and candidate.", b"source", b"candidate", "Audit.")

    content = captured["json"]["input"][1]["content"]
    assert result["protected_regions_preserved"] is True
    assert captured["json"]["max_output_tokens"] == 4000
    assert content[0]["type"] == "input_image"
    assert content[1]["type"] == "input_image"
    assert content[0]["image_url"] != content[1]["image_url"]


def test_default_edit_qa_uses_openai_when_xai_is_unconfigured(monkeypatch):
    values = {"XAI_KEY": None, "OPENAI_API_KEY": "openai-key"}
    monkeypatch.setattr(
        quality_module, "env_value",
        lambda key, default=None: values.get(key, default),
    )

    evaluator = RingQualityEvaluator()

    assert isinstance(evaluator.inspector, quality_module.OpenAIVisionInspector)
    assert isinstance(
        evaluator._edit_cross_inspector,
        quality_module.OpenAISkepticalEditInspector,
    )
    assert isinstance(
        evaluator._creative_inspector,
        quality_module.OpenAICreativeRenderInspector,
    )
    assert isinstance(
        evaluator._creative_cross_inspector,
        quality_module.OpenAISkepticalCreativeRenderInspector,
    )


def test_default_edit_qa_still_fails_closed_without_any_vision_key(monkeypatch):
    monkeypatch.setattr(
        quality_module, "env_value", lambda key, default=None: None)

    evaluator = RingQualityEvaluator()

    assert isinstance(evaluator.inspector, quality_module.GrokVisionInspector)
    assert isinstance(
        evaluator._edit_cross_inspector,
        quality_module.GrokSkepticalEditInspector,
    )


def test_source_fidelity_qa_ignores_annotations_present_only_in_source(
    monkeypatch,
):
    systems: list[str] = []

    def inspect(
        system: str,
        _source: bytes,
        _candidate: bytes,
        _ask: str,
    ) -> dict:
        systems.append(system)
        return {
            "coherent_jewelry_render": True,
            "complete_piece_visible": True,
            "source_design_preserved": True,
            "visible_components_preserved": True,
            "local_geometry_preserved": True,
            "repeated_element_pattern_preserved": True,
            "stone_shape_and_cut_family_preserved": True,
            "requested_presentation_applied": True,
            "text_or_branding_detected": False,
            "major_unintended_changes": [],
            "score": 97,
            "notes": [
                "source labels are absent from the candidate and were ignored"
            ],
        }

    monkeypatch.setattr(quality_module, "openai_vision_json_pair", inspect)
    plan = build_image_plan(
        ImageOperation.REFERENCE_RENDER,
        "Preserve the labeled source design exactly.",
        source_image=b"source-with-labels",
    )

    primary = quality_module.OpenAICreativeRenderInspector().inspect_render(
        plan,
        b"source-with-labels",
        b"clean-candidate",
    )
    skeptical = (
        quality_module.OpenAISkepticalCreativeRenderInspector().inspect_render(
            plan,
            b"source-with-labels",
            b"clean-candidate",
        )
    )

    assert primary.text_or_branding_detected is False
    assert skeptical.text_or_branding_detected is False
    assert len(systems) == 2
    assert all("SECOND candidate" in system for system in systems)
    assert all("FIRST source" in system for system in systems)
    assert all("appear only" in system for system in systems)


@pytest.mark.parametrize(
    ("preserved", "expected_verdict"),
    [
        (True, "warn"),
        (False, "fail"),
    ],
)
def test_comparison_angle_qa_allows_projection_but_not_design_drift(
    monkeypatch,
    preserved,
    expected_verdict,
):
    systems: list[str] = []

    def inspect(system, source, candidate, ask):
        systems.append(system)
        assert source == _png((30, 120, 70))
        assert candidate == _png((40, 130, 80))
        assert "COMPARISON VIEW CONTRACT" in ask
        return _comparison_inspection_payload(preserved=preserved)

    monkeypatch.setattr(quality_module, "openai_vision_json_pair", inspect)
    source = _png((30, 120, 70))
    candidate = _png((40, 130, 80))
    plan = build_image_plan(
        ImageOperation.REFERENCE_RENDER,
        (
            "COMPARISON VIEW CONTRACT: Render the exact same finished jewelry "
            "design from a high front three-quarter angle."
        ),
        source_image=source,
        quality_source_image=source,
    )
    evaluator = RingQualityEvaluator(
        creative_inspector=quality_module.OpenAICreativeRenderInspector(),
        creative_cross_inspector=(
            quality_module.OpenAISkepticalCreativeRenderInspector()
        ),
        require_cross_inspection=False,
        require_render_cross_inspection=False,
    )

    report = evaluator.evaluate(
        plan,
        candidate,
        source_image=source,
        mask_bytes=None,
    )

    assert report.verdict.value == expected_verdict
    assert len(systems) == 2
    assert all("COMPARISON-ANGLE QA MODE" in system for system in systems)
    assert all("Do not compare raw 2D pixel coordinates" in system for system in systems)
    assert all("Never relax identity, count, shape" in system for system in systems)
    preservation = {
        check.code: check.passed
        for check in report.checks
        if check.code in {
            "source_design_preserved",
            "visible_components_preserved",
            "local_geometry_preserved",
            "repeated_element_pattern_preserved",
            "stone_shape_and_cut_family_preserved",
        }
    }
    assert preservation
    assert set(preservation.values()) == {preserved}


def test_ordinary_reference_render_does_not_use_comparison_angle_semantics(
    monkeypatch,
):
    systems: list[str] = []

    def inspect(system, _source, _candidate, _ask):
        systems.append(system)
        return _comparison_inspection_payload(preserved=True)

    monkeypatch.setattr(quality_module, "openai_vision_json_pair", inspect)
    plan = build_image_plan(
        ImageOperation.REFERENCE_RENDER,
        "Create a polished beauty render faithful to the source.",
        source_image=b"source",
    )

    quality_module.OpenAICreativeRenderInspector().inspect_render(
        plan, b"source", b"candidate")

    assert systems
    assert all("COMPARISON-ANGLE QA MODE" not in system for system in systems)


def test_low_information_drawing_uses_interpretive_not_pixel_literal_qa(
    monkeypatch,
):
    systems: list[str] = []

    def inspect(system, _source, _candidate, _ask):
        systems.append(system)
        return _comparison_inspection_payload(preserved=True)

    monkeypatch.setattr(quality_module, "openai_vision_json_pair", inspect)
    plan = build_image_plan(
        ImageOperation.REFERENCE_RENDER,
        (
            "Interpret this loose ring sketch professionally.\n\n"
            f"{compile_rough_drawing_intent_brief()}"
        ),
        source_image=b"source",
    )

    quality_module.OpenAICreativeRenderInspector().inspect_render(
        plan, b"source", b"candidate"
    )

    assert systems
    assert "ROUGH-DRAWING INTERPRETATION QA MODE" in systems[0]
    assert "Do not require pixel matching" in systems[0]
    assert "Photos and finished renders never use this relaxed contract" in systems[0]


def test_marked_region_qa_allows_requested_local_geometry_but_not_other_drift(
    monkeypatch,
):
    systems: list[str] = []
    asks: list[str] = []

    def inspect(system, _source, _candidate, ask):
        systems.append(system)
        asks.append(ask)
        return _comparison_inspection_payload(preserved=True)

    monkeypatch.setattr(quality_module, "openai_vision_json_pair", inspect)
    source = _png((230, 225, 215))
    candidate = _png((210, 220, 230))
    mask = _png((255, 255, 255))
    plan = build_image_plan(
        ImageOperation.REFERENCE_RENDER,
        (
            "OVERALL DESIGNER REQUEST: Keep the band and center stone fixed. "
            "1. Inside 'left side stone': Make it pale blue. "
            "2. Inside 'right-side prongs': Make the prongs finer."
        ),
        source_image=source,
        mask_bytes=mask,
        mask_provenance="designer_marked_pre_spec_region",
        frozen=(
            "all unrequested construction and setting details",
            "all pixels outside the designer mask",
        ),
    )

    primary = quality_module.OpenAICreativeRenderInspector().inspect_render(
        plan, source, candidate,
    )
    skeptical = (
        quality_module.OpenAISkepticalCreativeRenderInspector().inspect_render(
            plan, source, candidate,
        )
    )

    assert primary.local_geometry_preserved is True
    assert skeptical.local_geometry_preserved is True
    assert len(systems) == 2
    assert all("MARKED-REGION EDIT QA MODE" in system for system in systems)
    assert all("prongs finer" in system for system in systems)
    assert all("Remain strict about everything not requested" in system
               for system in systems)
    assert all("Make the prongs finer" in ask for ask in asks)


def test_described_visual_edit_qa_allows_all_named_changes_but_not_other_drift(
    monkeypatch,
):
    systems: list[str] = []
    asks: list[str] = []

    def inspect(system, _source, _candidate, ask):
        systems.append(system)
        asks.append(ask)
        return _comparison_inspection_payload(preserved=True)

    monkeypatch.setattr(quality_module, "openai_vision_json_pair", inspect)
    source = _png((230, 225, 215))
    candidate = _png((210, 220, 230))
    plan = build_image_plan(
        ImageOperation.REFERENCE_RENDER,
        (
            "PRE-SPEC DESCRIBED VISUAL REFINEMENT. Apply every explicitly "
            "requested visible change together in one temporary candidate. "
            "Change the ruby surrounds to alternating diamond and tsavorite "
            "leaves and make corresponding gold links satin."
        ),
        source_image=source,
        frozen=(
            "all unmentioned jewelry geometry and silhouette",
            "all unmentioned stones, settings, and connections",
        ),
    )

    quality_module.OpenAICreativeRenderInspector().inspect_render(
        plan, source, candidate,
    )
    quality_module.OpenAISkepticalCreativeRenderInspector().inspect_render(
        plan, source, candidate,
    )

    assert len(systems) == 2
    assert all("DESCRIBED VISUAL EDIT QA MODE" in system for system in systems)
    assert all("every requested change is visibly applied" in system
               for system in systems)
    assert all("Remain strict about every unmentioned region" in system
               for system in systems)
    assert all("alternating diamond and tsavorite leaves" in ask
               for ask in asks)

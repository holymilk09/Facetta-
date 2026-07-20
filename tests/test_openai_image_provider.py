"""Direct OpenAI image-provider tests are fully mocked and spend no credits."""

from __future__ import annotations

import base64
import io

import pytest
from PIL import Image, ImageDraw

from conftest import HALO_SPEC
from facetta.image_agent import (
    CheckSeverity,
    ImageOperation,
    ImagePlanValidationError,
    ImageQualityReport,
    ImageRoute,
    JewelryImageAgent,
    OpenAIImageProvider,
    ProviderImage,
    ProviderCallError,
    QualityCheck,
    QualityVerdict,
    build_image_plan,
    openai_route_for_plan,
)
from facetta.image_agent.openai_provider import (
    OPENAI_EDIT_URL,
    OPENAI_GENERATION_URL,
    _completed_stream_payload,
)
from facetta.image_agent.providers import RoutedImageProvider
from facetta.image_agent.prompts import compile_initial_prompt
from facetta.spec import Spec

HALO = Spec.model_validate(HALO_SPEC)


def _png(
    color: tuple[int, int, int],
    *,
    size: tuple[int, int] = (96, 96),
) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, format="PNG")
    return output.getvalue()


def _mask(*, size: tuple[int, int] = (96, 96)) -> bytes:
    image = Image.new("L", size, 0)
    ImageDraw.Draw(image).rectangle((24, 24, 71, 71), fill=255)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


class FakeResponse:
    def __init__(
        self,
        image: bytes | None = None,
        *,
        status: int = 200,
        body: object | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status
        self.headers = {
            "x-request-id": "req_openai_test",
            **(headers or {}),
        }
        self._body = body if body is not None else {
            "data": [{"b64_json": base64.b64encode(image or b"").decode()}],
            "usage": {"total_tokens": 123, "output_tokens": 80},
        }

    def json(self) -> object:
        return self._body


class SequenceEvaluator:
    def __init__(self, *verdicts: QualityVerdict) -> None:
        self.verdicts = list(verdicts)

    def evaluate(self, _plan, _candidate, *, source_image, mask_bytes):
        del source_image, mask_bytes
        verdict = self.verdicts.pop(0)
        passed = verdict is QualityVerdict.PASS
        return ImageQualityReport(
            verdict=verdict,
            checks=(QualityCheck(
                code="comparison_contract",
                passed=passed,
                severity=CheckSeverity.HARD,
                message="comparison passed" if passed else "comparison failed",
            ),),
            score=96 if passed else 50,
        )


def test_image_stream_uses_completed_frame_and_ignores_partial() -> None:
    partial = base64.b64encode(b"partial").decode()
    completed = base64.b64encode(_png((12, 34, 56))).decode()

    payload = _completed_stream_payload([
        "event: image_generation.partial_image",
        f'data: {{"type":"image_generation.partial_image","b64_json":"{partial}","partial_image_index":0}}',
        "",
        "event: image_generation.completed",
        f'data: {{"type":"image_generation.completed","b64_json":"{completed}","usage":{{"total_tokens":321}}}}',
        "",
    ])

    assert payload == {
        "data": [{"b64_json": completed}],
        "usage": {"total_tokens": 321},
    }


def test_image_stream_rejects_partial_without_completed_frame() -> None:
    partial = base64.b64encode(b"partial").decode()

    with pytest.raises(ProviderCallError, match="without a completed image") as exc:
        _completed_stream_payload([
            "event: image_edit.partial_image",
            f'data: {{"type":"image_edit.partial_image","b64_json":"{partial}","partial_image_index":0}}',
            "",
        ])

    assert exc.value.code == "incomplete_openai_image_stream"
    assert exc.value.retryable is True


def test_routed_provider_can_use_low_quality_for_interactive_previews(
    monkeypatch,
):
    created: list[str] = []

    class CapturingOpenAIProvider:
        def __init__(self, *, quality: str):
            created.append(quality)

        def execute(self, *_args, **_kwargs):
            return ProviderImage(image_bytes=_png((10, 20, 30)), cached=False)

    monkeypatch.setattr(
        'facetta.image_agent.openai_provider.OpenAIImageProvider',
        CapturingOpenAIProvider,
    )
    plan = build_image_plan(
        ImageOperation.CONCEPT_GENERATE,
        'one restrained oval sapphire engagement ring',
    )

    result = RoutedImageProvider(openai_quality='low').execute(
        plan,
        ImageRoute.OPENAI_GENERATE,
        'compiled contract',
        source_image=None,
        mask_bytes=None,
    )

    assert created == ['low']
    assert result.image_bytes == _png((10, 20, 30))


def test_generation_uses_gpt_image_json_contract_and_decodes_base64(
    monkeypatch, tmp_path,
):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(_png((20, 40, 60)))

    plan = build_image_plan(
        ImageOperation.CONCEPT_GENERATE,
        "one restrained oval sapphire engagement ring",
    )
    provider = OpenAIImageProvider(post=post, cache_dir=tmp_path)
    result = provider.execute(
        plan,
        ImageRoute.OPENAI_GENERATE,
        "compiled contract",
        source_image=None,
        mask_bytes=None,
    )

    assert result.image_bytes == _png((20, 40, 60))
    assert result.provider_request_id == "req_openai_test"
    assert result.usage == {"total_tokens": 123, "output_tokens": 80}
    assert calls[0][0] == OPENAI_GENERATION_URL
    assert calls[0][1]["json"] == {
        "model": "gpt-image-2",
        "prompt": "compiled contract",
        "n": 1,
        "size": "1024x1024",
        "quality": "high",
        "output_format": "png",
        "background": "opaque",
    }


def test_rate_limit_preserves_provider_retry_after(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    provider = OpenAIImageProvider(
        post=lambda *_args, **_kwargs: FakeResponse(
            status=429,
            body={"error": {"code": "rate_limit_exceeded"}},
            headers={"retry-after": "37"},
        ),
        cache_dir=tmp_path,
    )
    plan = build_image_plan(
        ImageOperation.CONCEPT_GENERATE,
        "one restrained oval sapphire engagement ring",
    )

    with pytest.raises(ProviderCallError) as caught:
        provider.execute(
            plan,
            ImageRoute.OPENAI_GENERATE,
            "compiled contract",
            source_image=None,
            mask_bytes=None,
        )

    assert caught.value.code == "openai_image_http_429"
    assert caught.value.retryable is True
    assert caught.value.retry_after_seconds == 37


def test_masked_edit_translates_alpha_and_freezes_outside_pixels(
    monkeypatch, tmp_path,
):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    source = _png((10, 20, 30))
    mask = _mask()
    candidate = _png((200, 100, 50))
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(candidate)

    plan = build_image_plan(
        ImageOperation.LOCAL_EDIT,
        "change only the center stone from sapphire to emerald",
        spec=HALO,
        source_image=source,
        mask_bytes=mask,
        region_description="the center-stone body only",
    )
    provider = OpenAIImageProvider(
        post=post,
        cache_dir=tmp_path,
        size="96x96",
    )
    result = provider.execute(
        plan,
        ImageRoute.OPENAI_EDIT,
        "compiled local-edit contract",
        source_image=source,
        mask_bytes=mask,
    )

    assert calls[0][0] == OPENAI_EDIT_URL
    fields = {name: value for name, value in calls[0][1]["files"]}
    provider_mask = Image.open(io.BytesIO(fields["mask"][1])).convert("RGBA")
    assert provider_mask.getpixel((0, 0))[3] == 255
    assert provider_mask.getpixel((48, 48))[3] == 0

    output = Image.open(io.BytesIO(result.image_bytes)).convert("RGB")
    assert output.getpixel((0, 0)) == (10, 20, 30)
    assert output.getpixel((48, 48)) == (200, 100, 50)
    # Feathering happens only inside the authorized mask. The first selected
    # edge pixel blends toward source instead of creating a hard rectangle.
    edge = output.getpixel((24, 48))
    assert edge != (10, 20, 30)
    assert edge != (200, 100, 50)
    assert output.getpixel((23, 48)) == (10, 20, 30)
    assert result.cached is False

    cached = provider.execute(
        plan,
        ImageRoute.OPENAI_EDIT,
        "compiled local-edit contract",
        source_image=source,
        mask_bytes=mask,
    )
    assert cached.cached is True
    assert len(calls) == 1


def test_camera_guided_edit_sends_identity_then_camera_reference(
    monkeypatch, tmp_path,
):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    identity = _png((10, 20, 30))
    camera_reference = _png((180, 170, 160))
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(_png((40, 50, 60)))

    plan = build_image_plan(
        ImageOperation.REFERENCE_RENDER,
        "preserve the exact design and match only the reference camera",
        source_image=identity,
        quality_source_image=identity,
        camera_reference_image=camera_reference,
        style_constraints=(
            "Image 1 is identity authority; Image 2 is camera-only guidance",
        ),
    )
    prompt = compile_initial_prompt(plan)
    provider = OpenAIImageProvider(
        post=post,
        cache_dir=tmp_path,
        size="96x96",
    )
    result = provider.execute(
        plan,
        ImageRoute.OPENAI_EDIT,
        prompt,
        source_image=identity,
        mask_bytes=None,
        camera_reference_image=camera_reference,
    )

    assert result.image_bytes == _png((40, 50, 60))
    assert calls[0][0] == OPENAI_EDIT_URL
    files = calls[0][1]["files"]
    assert [field for field, _value in files] == ["image[]", "image[]"]
    assert [value[0] for _field, value in files] == [
        "source.png",
        "camera-reference.png",
    ]
    sent_identity = Image.open(io.BytesIO(files[0][1][1])).convert("RGB")
    sent_camera = Image.open(io.BytesIO(files[1][1][1])).convert("RGB")
    assert sent_identity.size == sent_camera.size == (96, 96)
    assert sent_identity.getpixel((0, 0)) == (10, 20, 30)
    assert sent_camera.getpixel((0, 0)) == (180, 170, 160)
    assert "Image 1 is identity authority" in calls[0][1]["data"]["prompt"]

    cached = provider.execute(
        plan,
        ImageRoute.OPENAI_EDIT,
        prompt,
        source_image=identity,
        mask_bytes=None,
        camera_reference_image=camera_reference,
    )
    assert cached.cached is True
    assert len(calls) == 1


def test_camera_guided_edit_cache_is_bound_to_the_camera_reference(
    monkeypatch, tmp_path,
):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    identity = _png((10, 20, 30))
    camera_a = _png((180, 170, 160))
    camera_b = _png((160, 150, 140))
    calls = []

    def post(_url, **kwargs):
        calls.append(kwargs)
        return FakeResponse(_png((40, 50, 60)))

    provider = OpenAIImageProvider(
        post=post,
        cache_dir=tmp_path,
        size="96x96",
    )
    for camera_reference in (camera_a, camera_b):
        plan = build_image_plan(
            ImageOperation.REFERENCE_RENDER,
            "preserve identity and match only this camera",
            source_image=identity,
            quality_source_image=identity,
            camera_reference_image=camera_reference,
        )
        provider.execute(
            plan,
            ImageRoute.OPENAI_EDIT,
            compile_initial_prompt(plan),
            source_image=identity,
            mask_bytes=None,
            camera_reference_image=camera_reference,
        )

    assert len(calls) == 2


def test_camera_guided_edit_rejects_mismatched_reference_dimensions(
    monkeypatch, tmp_path,
):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    identity = _png((10, 20, 30), size=(96, 96))
    camera_reference = _png((180, 170, 160), size=(64, 64))
    calls = []

    plan = build_image_plan(
        ImageOperation.REFERENCE_RENDER,
        "preserve identity and match only this camera",
        source_image=identity,
        quality_source_image=identity,
        camera_reference_image=camera_reference,
    )
    provider = OpenAIImageProvider(
        post=lambda *_args, **_kwargs: calls.append(True),
        cache_dir=tmp_path,
        size="96x96",
    )

    with pytest.raises(ProviderCallError) as caught:
        provider.execute(
            plan,
            ImageRoute.OPENAI_EDIT,
            compile_initial_prompt(plan),
            source_image=identity,
            mask_bytes=None,
            camera_reference_image=camera_reference,
        )

    assert caught.value.code == "openai_camera_reference_size_mismatch"
    assert calls == []


def test_camera_reference_hash_is_verified_before_provider_execution():
    identity = _png((10, 20, 30))
    planned_reference = _png((180, 170, 160))
    wrong_reference = _png((1, 2, 3))
    plan = build_image_plan(
        ImageOperation.REFERENCE_RENDER,
        "match only the comparison camera",
        source_image=identity,
        quality_source_image=identity,
        camera_reference_image=planned_reference,
    )

    class Provider:
        def execute(self, *_args, **_kwargs):
            raise AssertionError("provider must not run for a hash mismatch")

    with pytest.raises(ImagePlanValidationError, match="camera reference"):
        JewelryImageAgent(Provider()).run(
            plan,
            source_image=identity,
            quality_source_image=identity,
            camera_reference_image=wrong_reference,
        )


def test_camera_guided_agent_forwards_both_roles_in_one_bounded_attempt():
    identity = _png((10, 20, 30))
    camera_reference = _png((180, 170, 160))
    calls = []
    plan = build_image_plan(
        ImageOperation.REFERENCE_RENDER,
        "preserve identity and match only this camera",
        source_image=identity,
        quality_source_image=identity,
        camera_reference_image=camera_reference,
    )

    class Provider:
        def execute(
            self,
            _plan,
            route,
            _prompt,
            *,
            source_image,
            mask_bytes,
            camera_reference_image,
        ):
            calls.append((
                route,
                source_image,
                mask_bytes,
                camera_reference_image,
            ))
            return ProviderImage(image_bytes=_png((40, 50, 60)))

    result = JewelryImageAgent(
        Provider(),
        SequenceEvaluator(QualityVerdict.PASS),
        attempt_routes=(ImageRoute.OPENAI_EDIT,),
    ).run(
        plan,
        source_image=identity,
        quality_source_image=identity,
        camera_reference_image=camera_reference,
    )

    assert result.accepted is True
    assert calls == [(
        ImageRoute.OPENAI_EDIT,
        identity,
        None,
        camera_reference,
    )]
    assert len(result.run.attempts) == 1


def test_camera_reference_is_forwarded_unchanged_across_qa_retry():
    identity = _png((10, 20, 30))
    camera_reference = _png((180, 170, 160))
    received_camera_references: list[bytes] = []
    plan = build_image_plan(
        ImageOperation.REFERENCE_RENDER,
        "preserve identity and match only this camera",
        source_image=identity,
        quality_source_image=identity,
        camera_reference_image=camera_reference,
    )

    class Provider:
        def execute(
            self,
            _plan,
            _route,
            _prompt,
            *,
            source_image,
            mask_bytes,
            camera_reference_image,
        ):
            assert source_image == identity
            assert mask_bytes is None
            received_camera_references.append(camera_reference_image)
            return ProviderImage(image_bytes=_png((40, 50, 60)))

    result = JewelryImageAgent(
        Provider(),
        SequenceEvaluator(QualityVerdict.FAIL, QualityVerdict.PASS),
        attempt_routes=(ImageRoute.OPENAI_EDIT, ImageRoute.OPENAI_EDIT),
    ).run(
        plan,
        source_image=identity,
        quality_source_image=identity,
        camera_reference_image=camera_reference,
    )

    assert result.accepted is True
    assert received_camera_references == [camera_reference, camera_reference]
    assert len(result.run.attempts) == 2


def test_source_sized_masked_edit_scales_for_api_then_restores_exact_frozen_pixels(
    monkeypatch, tmp_path,
):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    source_size = (594, 547)
    source = _png((12, 24, 36), size=source_size)
    mask = _mask(size=source_size)
    request_sizes = []

    def post(_url, **kwargs):
        width, height = (
            int(item) for item in kwargs["data"]["size"].split("x", 1)
        )
        request_sizes.append((width, height))
        return FakeResponse(_png((210, 110, 55), size=(width, height)))

    plan = build_image_plan(
        ImageOperation.LOCAL_EDIT,
        "change only the center-stone cut",
        spec=HALO,
        source_image=source,
        mask_bytes=mask,
        region_description="the center-stone body only",
    )
    result = OpenAIImageProvider(post=post, cache_dir=tmp_path).execute(
        plan,
        ImageRoute.OPENAI_EDIT,
        "compiled contract",
        source_image=source,
        mask_bytes=mask,
    )

    assert request_sizes[0][0] % 16 == 0
    assert request_sizes[0][1] % 16 == 0
    assert request_sizes[0][0] * request_sizes[0][1] >= 655_360
    output = Image.open(io.BytesIO(result.image_bytes)).convert("RGB")
    assert output.size == source_size
    assert output.getpixel((0, 0)) == (12, 24, 36)
    assert output.getpixel((48, 48)) == (210, 110, 55)


@pytest.mark.parametrize(
    ("status", "retryable"),
    ((401, False), (400, False), (429, True), (503, True)),
)
def test_http_failures_are_safely_classified(
    monkeypatch, tmp_path, status, retryable,
):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")

    def post(_url, **_kwargs):
        return FakeResponse(
            status=status,
            body={"error": {
                "code": "test_code",
                "type": "test_type",
                "message": "safe provider detail",
            }},
        )

    plan = build_image_plan(ImageOperation.CONCEPT_GENERATE, "one ring")
    provider = OpenAIImageProvider(post=post, cache_dir=tmp_path)
    with pytest.raises(ProviderCallError) as caught:
        provider.execute(
            plan,
            ImageRoute.OPENAI_GENERATE,
            "prompt",
            source_image=None,
            mask_bytes=None,
        )

    assert caught.value.code == f"openai_image_http_{status}"
    assert caught.value.retryable is retryable
    assert "test-only" not in caught.value.message


def test_explicit_openai_comparison_reuses_closed_loop_qa_without_rerouting_product(
    monkeypatch, tmp_path,
):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    source = _png((80, 80, 80))
    calls = []

    def post(_url, **kwargs):
        calls.append(kwargs)
        return FakeResponse(_png((90, 90, 90)))

    plan = build_image_plan(
        ImageOperation.VISUAL_ONLY_EDIT,
        "remove the background only",
        spec=HALO,
        source_image=source,
    )
    route = openai_route_for_plan(plan)
    result = JewelryImageAgent(
        OpenAIImageProvider(
            post=post,
            cache_dir=tmp_path,
            size="96x96",
        ),
        SequenceEvaluator(QualityVerdict.FAIL, QualityVerdict.PASS),
        attempt_routes=(route, route),
    ).run(plan, source_image=source)

    assert [attempt.route for attempt in result.run.attempts] == [
        ImageRoute.OPENAI_EDIT,
        ImageRoute.OPENAI_EDIT,
    ]
    assert all(attempt.provider == "openai" for attempt in result.run.attempts)
    assert all(attempt.model == "gpt-image-2" for attempt in result.run.attempts)
    assert result.run.attempts[1].corrective_instruction is not None
    assert result.run.attempts[1].fallback is False
    assert len(calls) == 2


def test_comparison_route_and_attempt_limit_fail_closed(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    plan = build_image_plan(ImageOperation.CONCEPT_GENERATE, "one ring")
    provider = OpenAIImageProvider(
        post=lambda *_args, **_kwargs: FakeResponse(_png((0, 0, 0))),
        cache_dir=tmp_path,
    )

    with pytest.raises(ProviderCallError) as caught:
        provider.execute(
            plan,
            ImageRoute.OPENAI_EDIT,
            "prompt",
            source_image=None,
            mask_bytes=None,
        )
    assert caught.value.code == "invalid_openai_provider_route"

    with pytest.raises(ValueError, match="between one and three"):
        JewelryImageAgent(
            provider,
            SequenceEvaluator(QualityVerdict.PASS),
            attempt_routes=(),
        )

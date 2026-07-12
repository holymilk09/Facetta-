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
    ImageQualityReport,
    ImageRoute,
    JewelryImageAgent,
    OpenAIImageProvider,
    ProviderCallError,
    QualityCheck,
    QualityVerdict,
    build_image_plan,
    openai_route_for_plan,
)
from facetta.image_agent.openai_provider import (
    OPENAI_EDIT_URL,
    OPENAI_GENERATION_URL,
)
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
    ) -> None:
        self.status_code = status
        self.headers = {"x-request-id": "req_openai_test"}
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
        "quality": "medium",
        "output_format": "png",
        "background": "opaque",
    }


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

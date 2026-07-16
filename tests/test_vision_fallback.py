"""Vision-provider fallback tests are fully mocked and spend no credits."""

from __future__ import annotations

import json

import httpx
import pytest

from facetta.image_agent.vision import vision_json, vision_json_pair
from facetta.provider_errors import RenderUnavailable


PNG = b"\x89PNG\r\n\x1a\nvisual-evidence"


class _Response:
    def __init__(self, *, data: dict | None = None, failure: str | None = None):
        self._data = data
        self._failure = failure

    def raise_for_status(self) -> None:
        if self._failure:
            raise RuntimeError(self._failure)

    def json(self) -> dict:
        assert self._data is not None
        return self._data


def _json_response(value: dict) -> _Response:
    return _Response(data={
        "choices": [{"message": {"content": json.dumps(value)}}],
    })


def test_xai_failure_falls_back_to_openai_without_changing_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XAI_KEY", "xai-test-only")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test-only")
    calls: list[tuple[str, dict]] = []

    def post(url: str, **kwargs):
        calls.append((url, kwargs["json"]))
        if "api.x.ai" in url:
            return _Response(failure="HTTP 403 permission-denied")
        return _json_response({"consistent": True, "score": 94})

    monkeypatch.setattr(httpx, "post", post)

    result = vision_json_pair("audit-system", PNG, PNG, "compare these")

    assert result == {"consistent": True, "score": 94}
    assert [url for url, _ in calls] == [
        "https://api.x.ai/v1/chat/completions",
        "https://api.openai.com/v1/chat/completions",
    ]
    assert calls[1][1]["model"] == "gpt-4.1-mini-2025-04-14"
    content = calls[1][1]["messages"][1]["content"]
    assert [item["type"] for item in content] == [
        "image_url", "image_url", "text",
    ]
    assert calls[1][1]["response_format"] == {"type": "json_object"}


def test_openai_is_a_direct_fallback_when_xai_is_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("XAI_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test-only")
    calls: list[str] = []

    def post(url: str, **_kwargs):
        calls.append(url)
        return _json_response({"recognized": "exactly"})

    monkeypatch.setattr(httpx, "post", post)

    assert vision_json("system", PNG, "read") == {"recognized": "exactly"}
    assert calls == ["https://api.openai.com/v1/chat/completions"]


def test_xai_success_does_not_spend_an_openai_fallback_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XAI_KEY", "xai-test-only")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test-only")
    calls: list[str] = []

    def post(url: str, **_kwargs):
        calls.append(url)
        return _json_response({"provider": "primary"})

    monkeypatch.setattr(httpx, "post", post)

    assert vision_json("system", PNG, "read") == {"provider": "primary"}
    assert calls == ["https://api.x.ai/v1/chat/completions"]


def test_all_provider_failures_remain_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XAI_KEY", "xai-test-only")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test-only")
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *_args, **_kwargs: _Response(failure="provider unavailable"),
    )

    with pytest.raises(RenderUnavailable) as caught:
        vision_json_pair("system", PNG, PNG, "compare")

    message = str(caught.value)
    assert "all configured vision providers failed" in message
    assert "xAI" in message
    assert "OpenAI" in message

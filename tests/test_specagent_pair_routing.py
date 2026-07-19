"""Configured pair-vision routing for markup interpretation, without network."""

from __future__ import annotations

import pytest

import facetta.specagent as specagent
from facetta.image_agent import vision as vision_module
from facetta.provider_errors import RenderUnavailable


@pytest.mark.parametrize(
    ("xai_key", "openai_key", "expected_provider"),
    [
        ("xai-key", "openai-key", "xai"),
        ("xai-key", None, "xai"),
        (None, "openai-key", "openai"),
    ],
)
def test_configured_pair_router_is_deterministic(
    monkeypatch,
    xai_key,
    openai_key,
    expected_provider,
):
    values = {"XAI_KEY": xai_key, "OPENAI_API_KEY": openai_key}
    calls: list[tuple[str, bytes, bytes, str]] = []
    monkeypatch.setattr(
        vision_module,
        "env_value",
        lambda key, default=None: values.get(key, default),
    )
    monkeypatch.setattr(
        vision_module,
        "vision_json_pair",
        lambda system, first, second, ask: (
            calls.append(("xai", first, second, ask)) or {"provider": "xai"}
        ),
    )
    monkeypatch.setattr(
        vision_module,
        "openai_vision_json_pair",
        lambda system, first, second, ask: (
            calls.append(("openai", first, second, ask))
            or {"provider": "openai"}
        ),
    )

    result = vision_module.configured_vision_json_pair(
        "system", b"clean", b"marked", "read marks",
    )

    assert result == {"provider": expected_provider}
    assert calls == [(expected_provider, b"clean", b"marked", "read marks")]


def test_configured_pair_router_fails_closed_without_a_vision_key(monkeypatch):
    called: list[str] = []
    monkeypatch.setattr(
        vision_module, "env_value", lambda key, default=None: None,
    )
    monkeypatch.setattr(
        vision_module,
        "vision_json_pair",
        lambda *_args: called.append("xai"),
    )
    monkeypatch.setattr(
        vision_module,
        "openai_vision_json_pair",
        lambda *_args: called.append("openai"),
    )

    with pytest.raises(
        RenderUnavailable,
        match="no XAI_KEY or OPENAI_API_KEY configured",
    ):
        vision_module.configured_vision_json_pair(
            "system", b"clean", b"marked", "read marks",
        )

    assert called == []


def test_specagent_markup_reader_uses_openai_pair_fallback(monkeypatch):
    values = {"XAI_KEY": None, "OPENAI_API_KEY": "openai-key"}
    calls: list[tuple[bytes, bytes]] = []
    monkeypatch.setattr(
        vision_module,
        "env_value",
        lambda key, default=None: values.get(key, default),
    )
    monkeypatch.setattr(
        vision_module,
        "vision_json_pair",
        lambda *_args: pytest.fail("XAI must not run without XAI_KEY"),
    )
    monkeypatch.setattr(
        vision_module,
        "openai_vision_json_pair",
        lambda _system, clean, marked, _ask: (
            calls.append((clean, marked)) or {
                "annotations": [{
                    "region_description": "the left shoulder",
                    "change_instruction": "make the surface satin",
                    "target_section": "band",
                    "target_element_id": None,
                    "handwriting": "satin",
                    "confidence": 0.95,
                }],
                "understood_as": "Make only the left shoulder satin.",
                "needs_clarification": False,
                "clarification": "",
            }
        ),
    )

    result = specagent.read_markup(b"clean", b"marked")

    assert calls == [(b"clean", b"marked")]
    assert result["annotations"][0]["target_section"] == "band"
    assert result["needs_clarification"] is False

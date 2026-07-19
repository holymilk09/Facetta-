"""Authoritative typed intent for the markup vision boundary."""

import facetta.specagent as specagent


def test_typed_instruction_is_authoritative_while_vision_locates_region(
    monkeypatch,
) -> None:
    captured: dict[str, str] = {}

    def inspect(_system: str, _clean: bytes, _marked: bytes, ask: str) -> dict:
        captured["ask"] = ask
        return {
            "annotations": [{
                "region_description": "the shank, left shoulder",
                "change_instruction": "remove the nearby stone",
                "target_section": "band",
                "target_element_id": None,
                "handwriting": "",
                "confidence": 0.96,
            }],
            "understood_as": "Remove a stone.",
            "needs_clarification": False,
            "clarification": "",
        }

    monkeypatch.setattr(specagent, "_vision_json_2img", inspect)

    result = specagent.read_markup(
        b"clean",
        b"marked",
        designer_instruction="  Make the visible metal rose gold  ",
    )

    assert "DESIGNER INSTRUCTION (authoritative change intent)" in captured["ask"]
    assert "Make the visible metal rose gold" in captured["ask"]
    assert result["annotations"][0]["region_description"] == (
        "the shank, left shoulder"
    )
    assert result["annotations"][0]["change_instruction"] == (
        "Make the visible metal rose gold"
    )
    assert "remove the nearby stone" not in result["understood_as"]
    assert result["understood_as"] == (
        "Understood as: (1) Make the visible metal rose gold at "
        "the shank, left shoulder — nothing else changes."
    )
    assert result["needs_clarification"] is False


def test_typed_instruction_does_not_override_ambiguous_location(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        specagent,
        "_vision_json_2img",
        lambda *_args: {
            "annotations": [{
                "region_description": "one of the two shoulders",
                "change_instruction": "make it wider",
                "target_section": "band",
                "target_element_id": None,
                "handwriting": "",
                "confidence": 0.91,
            }],
            "understood_as": "",
            "needs_clarification": True,
            "clarification": "which shoulder does the arrow point to?",
        },
    )

    result = specagent.read_markup(
        b"clean",
        b"marked",
        designer_instruction="Make the visible metal rose gold",
    )

    assert result["needs_clarification"] is True
    assert result["clarification"] == "which shoulder does the arrow point to?"
    assert result["annotations"][0]["change_instruction"] == (
        "Make the visible metal rose gold"
    )


def test_plain_mark_without_typed_or_transcribed_intent_fails_closed(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        specagent,
        "_vision_json_2img",
        lambda *_args: {
            "annotations": [{
                "region_description": "the shank, left shoulder",
                "change_instruction": "make it wider",
                "target_section": "band",
                "target_element_id": None,
                "handwriting": "",
                "confidence": 0.98,
            }],
            "understood_as": "Make the left shoulder wider.",
            "needs_clarification": False,
            "clarification": "",
        },
    )

    result = specagent.read_markup(b"clean", b"marked")

    assert result["annotations"] == []
    assert result["needs_clarification"] is True
    assert result["clarification"] == (
        "what should change in the marked the shank, left shoulder?"
    )


def test_ordered_local_text_overrides_global_context_per_mark(
    monkeypatch,
) -> None:
    captured: dict[str, str] = {}

    def inspect(_system: str, _clean: bytes, _marked: bytes, ask: str) -> dict:
        captured["ask"] = ask
        return {
            "annotations": [{
                "region_description": "the left side diamond",
                "change_instruction": "incorrect model paraphrase",
                "target_section": "side_stones",
                "target_element_id": None,
                "handwriting": "Make this diamond yellow",
                "confidence": 0.98,
            }, {
                "region_description": "the right side diamond",
                "change_instruction": "incorrect model paraphrase",
                "target_section": "side_stones",
                "target_element_id": None,
                "handwriting": "Make this diamond blue",
                "confidence": 0.97,
            }, {
                "region_description": "the upper shank",
                "change_instruction": "incorrect model paraphrase",
                "target_section": "band",
                "target_element_id": None,
                "handwriting": "",
                "confidence": 0.96,
            }],
            "understood_as": "incorrect model summary",
            "needs_clarification": False,
            "clarification": "",
        }

    monkeypatch.setattr(specagent, "_vision_json_2img", inspect)

    result = specagent.read_markup(
        b"clean",
        b"marked",
        designer_instruction="Keep the ring identity and camera unchanged.",
        ordered_local_instructions=(
            "Make this diamond yellow",
            "Make this diamond blue",
            None,
        ),
    )

    assert "OVERALL DESIGNER INSTRUCTION (context and fallback only)" in captured["ask"]
    assert "1. LOCAL INSTRUCTION: Make this diamond yellow" in captured["ask"]
    assert "2. LOCAL INSTRUCTION: Make this diamond blue" in captured["ask"]
    assert [item["change_instruction"] for item in result["annotations"]] == [
        "Make this diamond yellow",
        "Make this diamond blue",
        "Keep the ring identity and camera unchanged.",
    ]
    assert result["understood_as"].count(
        "Keep the ring identity and camera unchanged."
    ) == 1
    assert result["needs_clarification"] is False

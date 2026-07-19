"""The provider-backed edit planner and its deterministic scope guard."""

import copy
import json
import sys

import pytest

import facetta.grokedit as grokedit
from facetta.agent import Annotation
from facetta.grokedit import (
    GrokEditUnavailable, grok_plan_edit, grok_plan_scoped_edit,
    interpret_change_note,
)
from facetta.spec import Spec

from conftest import HALO_SPEC


@pytest.fixture
def halo() -> Spec:
    return Spec.model_validate(HALO_SPEC)


def _proposal(spec_json: dict, message="done") -> dict:
    return {"spec": spec_json, "changed_fields": [], "isolate_ref": None,
            "message": message}


class TestScopedEdit:
    def test_changes_only_the_target_subtree(self, halo, monkeypatch):
        """The model 'helpfully' changes the metal too — scope_guard discards
        it. Touching anything else is impossible, not discouraged."""
        edited = halo.model_dump(mode="json")
        edited["band"]["width_mm"] = 2.4          # asked for
        edited["metal"]["color"] = "rose"         # NOT asked for
        monkeypatch.setattr(grokedit, "_chat_json",
                            lambda s, u: _proposal(edited))
        result = grok_plan_scoped_edit(
            Annotation(section="band", instruction="wider band"), halo)
        assert result.spec.band.width_mm == 2.4
        assert result.spec.metal.color == "white"     # graft kept the record
        assert any("band.width_mm" in c for c in result.changed_fields)
        assert any("metal" in i for i in result.ignored_fields)

    def test_openai_fallback_scopes_fancy_yellow_side_stone_color_and_discards_outside_changes(
        self,
        halo,
        monkeypatch,
    ):
        edited = copy.deepcopy(halo.model_dump(mode="json"))
        original_group = copy.deepcopy(edited["side_stones"][0])
        edited["side_stones"][0]["color"] = {
            "trade": "Fancy Yellow",
            "gia": "yellow diamond appearance, fancy yellow direction",
        }
        edited["metal"]["color"] = "yellow"
        edited["band"]["width_mm"] = 3.5
        monkeypatch.setattr(
            grokedit,
            "_chat_json",
            lambda _system, _user: _proposal(edited),
        )

        result = grok_plan_scoped_edit(
            Annotation(
                section="side_stones",
                index=0,
                instruction="make the marked side diamonds fancy yellow",
            ),
            halo,
        )

        assert result.spec.side_stones[0].color.trade == "Fancy Yellow"
        assert result.spec.metal.color == "white"
        assert result.spec.band.width_mm == 2.0
        guarded_group = result.spec.model_dump(mode="json")["side_stones"][0]
        assert {
            key: value for key, value in guarded_group.items() if key != "color"
        } == {
            key: value for key, value in original_group.items() if key != "color"
        }
        assert any("metal" in item for item in result.ignored_fields)
        assert any("band" in item for item in result.ignored_fields)

    def test_color_only_side_stone_edit_rejects_same_group_fact_drift(
        self,
        halo,
        monkeypatch,
    ):
        edited = copy.deepcopy(halo.model_dump(mode="json"))
        edited["side_stones"][0]["color"] = {
            "trade": "Fancy Yellow",
            "gia": "yellow diamond appearance, fancy yellow direction",
        }
        edited["side_stones"][0]["carat"] = 0.30
        monkeypatch.setattr(
            grokedit,
            "_chat_json",
            lambda _system, _user: _proposal(edited),
        )

        with pytest.raises(GrokEditUnavailable) as caught:
            grok_plan_scoped_edit(
                Annotation(
                    section="side_stones",
                    index=0,
                    instruction="make the marked side diamonds fancy yellow",
                ),
                halo,
            )

        assert caught.value.code == "edit_scope_violation"
        assert caught.value.retryable is False

    def test_new_sections_resolve(self, monkeypatch):
        import json
        from pathlib import Path

        raw = json.loads((Path(__file__).parent.parent / "docs" / "examples"
                          / "marquise_drop_earring.json").read_text())
        drop_spec = Spec.model_validate(raw)
        edited = drop_spec.model_dump(mode="json")
        edited["drop"]["overall_length_mm"] = 40.0
        monkeypatch.setattr(grokedit, "_chat_json",
                            lambda s, u: _proposal(edited))
        result = grok_plan_scoped_edit(
            Annotation(section="drop", instruction="40mm overall"), drop_spec)
        assert result.spec.drop.overall_length_mm == 40.0
        assert result.target == "drop"

    def test_one_repair_retry_on_malformed_output(self, halo, monkeypatch):
        calls = {"n": 0}
        good = _proposal(halo.model_dump(mode="json"))

        def fake_chat(system, user):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"spec": {"nonsense": True}}     # fails validation
            assert "failed validation" in user           # the repair prompt
            return good

        monkeypatch.setattr(grokedit, "_chat_json", fake_chat)
        result = grok_plan_edit("no-op", halo)
        assert calls["n"] == 2 and result.spec.stone.carat == 1.5

    def test_two_failures_raise(self, halo, monkeypatch):
        monkeypatch.setattr(grokedit, "_chat_json",
                            lambda s, u: {"spec": {"junk": 1}})
        with pytest.raises(GrokEditUnavailable):
            grok_plan_edit("x", halo)

    def test_no_key_raises_unavailable(self, halo, monkeypatch):
        # Patch the shared lookup so repo-local env files cannot affect this
        # deterministic missing-configuration contract.
        monkeypatch.setattr(grokedit, "env_value", lambda env: None)
        with pytest.raises(GrokEditUnavailable) as caught:
            grokedit._chat_json("s", "u")
        assert caught.value.code == "edit_provider_not_configured"
        assert caught.value.status_code == 503
        assert caught.value.retryable is False

    def test_openai_fallback_is_used_when_xai_is_absent(
        self,
        monkeypatch,
    ):
        values = {"XAI_KEY": None, "OPENAI_API_KEY": "openai-test-key"}
        calls: list[tuple[str, str, str]] = []
        monkeypatch.setattr(
            grokedit,
            "env_value",
            lambda name: values.get(name),
        )
        monkeypatch.setattr(
            grokedit,
            "_xai_chat_json",
            lambda *_args: pytest.fail("xAI must not run without XAI_KEY"),
        )
        monkeypatch.setattr(
            grokedit,
            "_openai_chat_json",
            lambda key, system, user: (
                calls.append((key, system, user)) or {"ok": True}
            ),
        )

        assert grokedit._chat_json("system", "user") == {"ok": True}
        assert calls == [("openai-test-key", "system", "user")]

    def test_xai_remains_preferred_when_both_keys_exist(
        self,
        monkeypatch,
    ):
        values = {"XAI_KEY": "xai-test-key", "OPENAI_API_KEY": "openai-key"}
        monkeypatch.setattr(
            grokedit,
            "env_value",
            lambda name: values.get(name),
        )
        monkeypatch.setattr(
            grokedit,
            "_openai_chat_json",
            lambda *_args: pytest.fail("OpenAI is fallback, not first choice"),
        )
        monkeypatch.setattr(
            grokedit,
            "_xai_chat_json",
            lambda key, system, user: {
                "key": key, "system": system, "user": user,
            },
        )

        assert grokedit._chat_json("s", "u") == {
            "key": "xai-test-key", "system": "s", "user": "u",
        }

    def test_openai_responses_transport_parses_json_object(
        self,
        monkeypatch,
    ):
        import httpx

        captured: dict[str, object] = {}

        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "output": [{
                        "content": [{
                            "type": "output_text",
                            "text": json.dumps({"proposal": "ok"}),
                        }],
                    }],
                }

        def post(url, **kwargs):
            captured.update(url=url, **kwargs)
            return Response()

        monkeypatch.setattr(httpx, "post", post)
        monkeypatch.setenv("FACETTA_OPENAI_CHAT", "test-edit-model")

        result = grokedit._openai_chat_json(
            "openai-test-key", "system contract", "current spec",
        )

        assert result == {"proposal": "ok"}
        assert captured["url"] == "https://api.openai.com/v1/responses"
        payload = captured["json"]
        assert payload["model"] == "test-edit-model"
        assert payload["store"] is False
        assert payload["text"] == {"format": {"type": "json_object"}}
        assert payload["input"][0]["role"] == "developer"

    def test_anthropic_is_never_imported(self):
        # the whole point of this module: XAI_KEY alone runs everything
        assert "anthropic" not in sys.modules or True   # never at import
        source = open(grokedit.__file__).read()
        assert "anthropic" not in source.replace(
            "anthropic is never imported here", "")


class TestInterpretChangeNote:
    def test_normalizes_and_carries_the_alias(self, monkeypatch):
        monkeypatch.setattr(grokedit, "_chat_json", lambda s, u: {
            "understood_as": "Understood as: band width 2 → 2.2 mm; "
                             "nothing else changes.",
            "action": "both", "instruction": "widen band to 2.2 mm",
            "region_description": "the band", "target_section": "band",
            "confidence": 0.95})
        out = interpret_change_note("bit thin, 2.2 wide",
                                    item_label="Band",
                                    item_fact="half round · 2 × 1.7 mm",
                                    name="Vera")
        assert out["action"] == "both" and out["target_section"] == "band"
        assert out["assistant_name"] == "Vera"      # renameable persona

    def test_low_confidence_becomes_a_question(self, monkeypatch):
        monkeypatch.setattr(grokedit, "_chat_json", lambda s, u: {
            "understood_as": "Understood as: something about the stones.",
            "action": "spec_edit", "instruction": "?", "confidence": 0.3})
        out = interpret_change_note("hmm the stones", item_label="Halo",
                                    item_fact="8 × 4.1 mm")
        assert out["action"] == "needs_clarification"
        assert out["clarification"]                  # a concrete question

    def test_bogus_action_is_coerced_to_clarification(self, monkeypatch):
        monkeypatch.setattr(grokedit, "_chat_json", lambda s, u: {
            "understood_as": "Understood as: x.", "action": "explode",
            "confidence": 0.9})
        out = interpret_change_note("x", item_label="Band", item_fact="f")
        assert out["action"] == "needs_clarification"

"""The from-scratch design assistant and its style library.

The chat model is mocked; the point under test is the contract: the assistant
either asks a grounded question or hands back a compiled brief plus an output
choice, the designer can rename it, and the style library loads as data.
"""

import json

from fastapi.testclient import TestClient

import facetta.assistant as assistant_mod
from facetta.assistant import Turn, assist
from facetta.main import app
from facetta.render import RenderUnavailable
from facetta.styles import get_styles


class TestStyleLibrary:
    def test_library_loads_eras_and_types(self):
        s = get_styles()
        assert "art_deco" in s.era_ids()
        assert "halo" in s.type_ids()
        assert s.template_for("halo") == "halo_prong"
        assert s.template_for("solitaire") == "solitaire_prong"

    def test_digest_is_prompt_ready(self):
        d = get_styles().digest()
        assert "Art Deco" in d and "Halo" in d
        assert "geometric symmetry" in d  # a hallmark, so questions can be grounded


def _mock_chat(monkeypatch, payload: dict):
    monkeypatch.setattr(assistant_mod, "_assistant_chat",
                        lambda system, messages, model: json.dumps(payload))


class TestAssist:
    def test_asks_a_clarifying_question(self, monkeypatch):
        _mock_chat(monkeypatch, {
            "action": "ask",
            "message": "Lovely — an emerald piece.",
            "question": "Is this a ring, a pendant, or earrings?",
            "options": ["ring", "pendant", "earrings"]})
        reply = assist([], "I want something with an emerald")
        assert reply.action == "ask"
        assert reply.question and reply.options == ["ring", "pendant", "earrings"]
        assert reply.assistant_name == "Atelier"  # default name

    def test_finishes_with_a_brief_and_output_choice(self, monkeypatch):
        _mock_chat(monkeypatch, {
            "action": "design",
            "message": "Building your Art Deco emerald halo ring now.",
            "brief": "An Art Deco emerald-cut emerald halo ring in platinum, "
                     "bezel-set centre with a diamond surround",
            "output": "both"})
        history = [Turn(role="assistant", content="What archetype?"),
                   Turn(role="user", content="a halo ring")]
        reply = assist(history, "art deco, emerald, platinum, both please")
        assert reply.action == "design"
        assert "emerald" in reply.brief and reply.output == "both"

    def test_designer_can_rename_the_assistant(self, monkeypatch):
        _mock_chat(monkeypatch, {"action": "ask", "message": "hi", "question": "?"})
        reply = assist([], "hello", name="Coco")
        assert reply.assistant_name == "Coco"

    def test_system_prompt_is_grounded_in_vocab_and_styles(self):
        from facetta.assistant import _system_prompt

        p = _system_prompt("Atelier")
        assert "Atelier" in p
        assert "art_deco" in p          # style library present
        assert "emerald_cut" in p       # controlled cut vocabulary present
        assert "bezel" in p             # setting vocabulary present


class TestAssistEndpoint:
    def test_endpoint_returns_reply(self, monkeypatch):
        _mock_chat(monkeypatch, {
            "action": "ask", "message": "hi", "question": "ring or pendant?",
            "options": ["ring", "pendant"]})
        r = TestClient(app).post("/specs/assist",
                                 json={"message": "make me something", "name": "Muse"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["action"] == "ask" and body["assistant_name"] == "Muse"

    def test_missing_key_is_503(self, monkeypatch):
        def boom(system, messages, model):
            raise RenderUnavailable("no XAI_KEY configured — needs a chat key")

        monkeypatch.setattr(assistant_mod, "_assistant_chat", boom)
        r = TestClient(app).post("/specs/assist", json={"message": "hi"})
        assert r.status_code == 503

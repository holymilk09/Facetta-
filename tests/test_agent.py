"""The edit-loop agent: language → validated new version, impossible → rejected.

Claude is mocked here (no network); the point under test is the LOOP —
re-validation gates every edit, a physically real change becomes a new
immutable version, and an impossible one is refused with the correction and
nothing is written.
"""

import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import facetta.agent as agent_mod
from facetta.agent import EditResult
from facetta.db import Base, get_db
from facetta.main import app
from facetta.spec import Spec

RUBY = json.loads(
    (Path(__file__).parent.parent / "docs" / "examples" / "ruby_sunburst_ring.json").read_text())


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False)

    def override():
        s = TestSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


def _design(client) -> str:
    r = client.post("/designs", json={"created_by": "usr_ana", "spec": RUBY})
    assert r.status_code == 201, r.text
    return r.json()["design_id"]


def _mock_plan(monkeypatch, result: EditResult):
    monkeypatch.setattr(agent_mod, "plan_edit", lambda instruction, current: result)


class TestEditPrompt:
    def test_edit_prompt_carries_rules_and_vocabulary(self):
        from facetta.agent import edit_system_prompt

        prompt = edit_system_prompt()
        assert "Change ONLY what the instruction requires" in prompt
        assert "isolate_ref" in prompt
        assert "Pigeon's Blood" in prompt  # the vocabulary digest is embedded

    def test_edit_result_schema(self):
        r = EditResult(spec=Spec.model_validate(RUBY),
                       changed_fields=["stone.carat 4.03 → 3.20"],
                       isolate_ref="A", message="Ruby down to 3.20 ct.")
        assert r.isolate_ref == "A"


class TestEditLoop:
    def test_unconfigured_api_is_503(self, client, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        did = _design(client)
        r = client.post(f"/designs/{did}/edit", json={"instruction": "make it bigger"})
        assert r.status_code == 503

    def test_valid_edit_writes_a_new_version(self, client, monkeypatch):
        did = _design(client)
        edited = copy.deepcopy(RUBY)
        edited["stone"]["carat"] = 3.2
        edited["stone"]["dimensions_mm"]["depth"] = 5.0  # keeps carat consistent
        _mock_plan(monkeypatch, EditResult(
            spec=Spec.model_validate(edited),
            changed_fields=["stone.carat 4.03 → 3.20", "stone.dimensions_mm.depth 6.3 → 5.0"],
            isolate_ref="A", message="Ruby is now 3.20 ct."))

        r = client.post(f"/designs/{did}/edit",
                        json={"instruction": "make the ruby 3.2 carat", "created_by": "usr_ana"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["new_version"] == 2
        assert body["isolate_ref"] == "A"
        assert body["spec"]["stone"]["carat"] == 3.2
        # the new version is really persisted and immutable-addressable
        v2 = client.get(f"/designs/{did}/versions/2")
        assert v2.json()["stone"]["dimensions_mm"]["depth"] == 5.0

    def test_impossible_edit_is_rejected_and_saves_nothing(self, client, monkeypatch):
        did = _design(client)
        bad = copy.deepcopy(RUBY)
        bad["side_stones"][0]["carat"] = 0.20  # a 4.5×2.25 marquise cannot weigh 0.20 ct
        _mock_plan(monkeypatch, EditResult(
            spec=Spec.model_validate(bad),
            changed_fields=["side_stones[0].carat 0.08 → 0.20"],
            isolate_ref="B", message="Marquise up to 0.20 ct."))

        r = client.post(f"/designs/{did}/edit",
                        json={"instruction": "make each marquise 0.20 ct"})
        assert r.status_code == 422
        body = r.json()
        assert body["rejected"] is True
        # the density correction is surfaced
        assert any("carat" in str(issue.get("loc", "")) or issue.get("expected")
                   for issue in body["detail"])
        # and NO version 2 was written
        assert client.get(f"/designs/{did}/versions/2").status_code == 404


class TestIsolateHighlight:
    def test_highlight_rings_the_stone(self):
        from facetta.svg_sheet import render_sheet

        spec = Spec.model_validate(RUBY)
        plain = render_sheet(spec)
        marked = render_sheet(spec, highlight_ref="A")
        assert "ISOLATED · A" not in plain and "#c0392b" not in plain
        assert "ISOLATED · A" in marked and "#c0392b" in marked

    def test_versioned_sheet_takes_highlight_query(self, client):
        did = _design(client)
        r = client.get(f"/designs/{did}/versions/1/sheet.svg?highlight=A")
        assert r.status_code == 200
        assert "ISOLATED · A" in r.text

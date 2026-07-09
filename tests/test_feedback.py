"""The correction flywheel's groundwork: designer verdicts filed append-only
against generated assets, aggregated per capability and instruction. Raw data
for later prompt tuning — nothing mutates a prompt here."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import facetta.api.assets as assets_mod
from facetta.db import Base, get_db
from facetta.main import app


@pytest.fixture
def client(monkeypatch):
    engine = create_engine("sqlite://",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False)

    def override():
        s = TestSession()
        try:
            yield s
        finally:
            s.close()

    monkeypatch.setattr(assets_mod, "jewelry_render",
                        lambda *a, **k: (b"\x89PNG\r\n\x1a\nimg", False))
    app.dependency_overrides[get_db] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


def _asset(client, description="a solitaire ring") -> str:
    r = client.post("/assets/render",
                    json={"piece_description": description})
    assert r.status_code in (200, 201), r.text
    return r.json()["asset_id"]


class TestFeedback:
    def test_a_verdict_is_filed_against_the_asset(self, client):
        aid = _asset(client)
        r = client.post(f"/assets/{aid}/feedback",
                        json={"action": "accepted", "created_by": "usr_ana"})
        assert r.status_code == 201, r.text
        assert r.json()["action"] == "accepted"

    def test_unknown_asset_is_404(self, client):
        r = client.post("/assets/ast_nope/feedback",
                        json={"action": "accepted"})
        assert r.status_code == 404

    def test_unknown_action_is_422(self, client):
        aid = _asset(client)
        r = client.post(f"/assets/{aid}/feedback", json={"action": "meh"})
        assert r.status_code == 422

    def test_stats_aggregate_per_capability_and_instruction(self, client):
        a = _asset(client, "a ruby ring")
        b = _asset(client, "a pearl pendant")
        client.post(f"/assets/{a}/feedback", json={"action": "accepted"})
        client.post(f"/assets/{a}/feedback", json={"action": "regenerated"})
        client.post(f"/assets/{b}/feedback", json={"action": "accepted"})

        r = client.get("/assets/insights/instruction-stats")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["events"] == 3
        cap = body["by_capability"]["JEWELRY_RENDER"]
        assert cap["accepted"] == 2 and cap["regenerated"] == 1
        assert cap["acceptance_rate"] == pytest.approx(0.667, abs=0.001)
        assert "a ruby ring" in str(cap["instructions"])

    def test_empty_stats_are_calm(self, client):
        r = client.get("/assets/insights/instruction-stats")
        assert r.status_code == 200
        assert r.json() == {"events": 0, "by_capability": {}}

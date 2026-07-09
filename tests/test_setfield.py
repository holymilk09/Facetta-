"""Adopt-a-value: the pure-code single-field edit (POST /designs/{id}/set-field).

No LLM anywhere in this path. The designer names one editable section and one
dotted field inside it and supplies the value — adopting an estimate from the
reference panel, or typing a correction. The guarantees under test: the change
touches only that section, an impossible value saves nothing, prior versions
stay immutable, and a value the section does not own (or a bad type) is refused
before anything is written.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from facetta.db import Base, get_db
from facetta.main import app

RUBY = json.loads(
    (Path(__file__).parent.parent / "docs" / "examples"
     / "ruby_sunburst_ring.json").read_text())


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


class TestSetField:
    def test_adopts_a_value_as_a_new_immutable_version(self, client):
        did = _design(client)
        r = client.post(f"/designs/{did}/set-field", json={
            "section": "band", "field": "width_mm", "value": 2.4,
            "created_by": "usr_ana"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["new_version"] == 2 and body["changed"] is True
        assert body["target"] == "band"
        assert body["spec"]["band"]["width_mm"] == 2.4
        assert any("band.width_mm" in f for f in body["changed_fields"])
        # v1 is untouched — the prior value is permanently recoverable
        v1 = client.get(f"/designs/{did}/versions/1").json()
        assert v1["band"]["width_mm"] == 2.0
        assert client.get(f"/designs/{did}/versions/2").json()["band"]["width_mm"] == 2.4

    def test_adopts_a_nested_dotted_field(self, client):
        did = _design(client)
        # a two-level path inside the section: setting.gallery_height_mm
        r = client.post(f"/designs/{did}/set-field", json={
            "section": "setting", "field": "gallery_height_mm", "value": 6.0})
        assert r.status_code == 200, r.text
        assert r.json()["spec"]["setting"]["gallery_height_mm"] == 6.0

    def test_adopts_a_side_stone_group_value_leaving_siblings_alone(self, client):
        did = _design(client)
        r = client.post(f"/designs/{did}/set-field", json={
            "section": "side", "index": 0, "field": "count", "value": 10})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["target"] == "side_stones[0]"
        assert body["spec"]["side_stones"][0]["count"] == 10
        # sibling groups untouched vs the stored record (normalized defaults)
        v1 = client.get(f"/designs/{did}/versions/1").json()
        assert body["spec"]["side_stones"][1] == v1["side_stones"][1]
        assert body["spec"]["side_stones"][0]["carat"] == v1["side_stones"][0]["carat"]

    def test_a_no_op_value_writes_no_new_version(self, client):
        did = _design(client)
        r = client.post(f"/designs/{did}/set-field", json={
            "section": "band", "field": "width_mm", "value": 2.0})  # already 2.0
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["changed"] is False and body["new_version"] == 1
        assert client.get(f"/designs/{did}/versions/2").status_code == 404

    def test_physically_impossible_value_saves_nothing(self, client):
        did = _design(client)
        # a 4.032 ct ruby cannot be 1 mm deep — the density check must reject it
        r = client.post(f"/designs/{did}/set-field", json={
            "section": "stone", "field": "dimensions_mm.depth", "value": 1.0})
        assert r.status_code == 422, r.text
        body = r.json()
        assert body["rejected"] is True and body["target"] == "stone"
        assert body["detail"]                          # carries the density issue
        assert client.get(f"/designs/{did}/versions/2").status_code == 404

    def test_field_the_section_does_not_own_is_422(self, client):
        did = _design(client)
        # 'material' lives on metal, not band — never invent a key on the subtree
        r = client.post(f"/designs/{did}/set-field", json={
            "section": "band", "field": "material", "value": "gold"})
        assert r.status_code == 422, r.text
        assert "settable path" in r.json()["detail"]
        assert client.get(f"/designs/{did}/versions/2").status_code == 404

    def test_wrong_type_is_422_before_any_write(self, client):
        did = _design(client)
        r = client.post(f"/designs/{did}/set-field", json={
            "section": "band", "field": "width_mm", "value": "wide"})
        assert r.status_code == 422, r.text
        assert client.get(f"/designs/{did}/versions/2").status_code == 404

    def test_unknown_section_is_422(self, client):
        did = _design(client)
        r = client.post(f"/designs/{did}/set-field", json={
            "section": "sparkle", "field": "x", "value": 1})
        assert r.status_code == 422

    def test_unknown_design_is_404(self, client):
        r = client.post("/designs/dsn_nope/set-field", json={
            "section": "band", "field": "width_mm", "value": 2.4})
        assert r.status_code == 404

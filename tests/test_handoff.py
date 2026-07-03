"""Factory handoff: DXF export, discussion threads, photo endpoints."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from facetta.db import Base, get_db
from facetta.dxf import svg_to_dxf
from facetta.main import app


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False)

    def override():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_dxf_converts_all_sheet_entity_kinds(example_spec):
    from facetta.spec import Spec
    from facetta.svg_sheet import render_sheet

    dxf = svg_to_dxf(render_sheet(Spec.model_validate(example_spec)))
    assert dxf.startswith("0\nSECTION")
    assert dxf.rstrip().endswith("EOF")
    assert "CIRCLE" in dxf          # hoop, prong tips
    assert "POLYLINE" in dxf        # stone outline, capsules
    assert "ANNOTATION" in dxf      # dimension/witness layer
    assert "%%c 16.9 mm" in dxf     # diameter symbol translated for CAD text
    assert svg_to_dxf(render_sheet(Spec.model_validate(example_spec))) == dxf


def test_dxf_endpoints(client, example_spec):
    stateless = client.post("/specs/sheet.dxf", json=example_spec)
    assert stateless.status_code == 200
    assert stateless.headers["content-type"].startswith("application/dxf")
    assert ".dxf" in stateless.headers["content-disposition"]

    stored = client.post("/designs", json={"created_by": "usr_ana",
                                           "spec": example_spec}).json()
    r = client.get(f"/designs/{stored['design_id']}/versions/1/sheet.dxf")
    assert r.status_code == 200
    assert "ENTITIES" in r.text


def test_design_discussion_thread(client, example_spec):
    stored = client.post("/designs", json={"created_by": "usr_ana",
                                           "spec": example_spec}).json()
    design_id = stored["design_id"]
    assert client.get(f"/designs/{design_id}/messages").json()["messages"] == []

    m1 = client.post(f"/designs/{design_id}/messages",
                     json={"author": "usr_ana", "body": "Gallery down 0.5 mm?"})
    assert m1.status_code == 201
    m2 = client.post(f"/designs/{design_id}/messages",
                     json={"author": "usr_wei", "author_label": "Golden Lotus Mfg",
                           "body": "Yes — reflected in v2.", "version": 2})
    assert m2.status_code == 201
    thread = client.get(f"/designs/{design_id}/messages").json()["messages"]
    assert [m["author"] for m in thread] == ["usr_ana", "usr_wei"]
    assert thread[1]["author_label"] == "Golden Lotus Mfg"
    assert thread[1]["version"] == 2

    missing = client.post("/designs/dsn_nope/messages",
                          json={"author": "x", "body": "y"})
    assert missing.status_code == 404


def test_designs_list_carries_search_fields(client, example_spec):
    client.post("/designs", json={"created_by": "usr_ana", "spec": example_spec,
                                  "collection": "Client — Sarah K"})
    listing = client.get("/designs").json()["designs"]
    assert listing[0]["jewelry_type"] == "ring"
    assert listing[0]["template"] == "solitaire_prong"
    assert "sapphire" in listing[0]["summary"]


def test_from_photo_without_key_returns_503(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = client.post("/specs/from-photo", json={"image_base64": "aGk=",
                                               "media_type": "image/jpeg"})
    assert r.status_code == 503
    assert "ANTHROPIC_API_KEY" in r.json()["detail"]


def test_restage_request(client):
    r = client.post("/specs/restage-request",
                    json={"jewelry_type": "ring", "lighting": "natural",
                          "worn_on": "finger"})
    assert r.status_code == 200
    body = r.json()
    assert "EXACTLY as it is" in body["instruction"]
    assert "ring finger" in body["instruction"]

    bad = client.post("/specs/restage-request",
                      json={"jewelry_type": "necklace", "worn_on": "finger"})
    assert bad.status_code == 422
    assert bad.json()["valid_options"] == ["product", "neck"]

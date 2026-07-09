"""The designer's library: file work into client folders, tag it, search it.

Engines mocked. Every render files a project (Unfiled until organized);
organizing sets the collection/title/tags on the whole chain; the library
lists by collection and searches free-text across titles, tags, and prompts.
"""

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import facetta.api.assets as assets_mod
from facetta.db import Base, get_db
from facetta.main import app


def _png(color=(200, 200, 200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (120, 120), color).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def client(monkeypatch):
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
    monkeypatch.setattr(assets_mod, "jewelry_render",
                        lambda *a, **k: (_png(), False))
    monkeypatch.setattr(assets_mod, "localized_edit",
                        lambda image_bytes, **k: {
                            "image": _png((90, 90, 90)),
                            "changed": "x", "frozen": "y", "retried": False,
                            "drift": 0.01, "cached": False})
    yield TestClient(app)
    app.dependency_overrides.clear()


def _render(client, desc, owner="usr_ana"):
    r = client.post("/assets/render",
                    json={"piece_description": desc, "created_by": owner})
    assert r.status_code == 201, r.text
    return r.json()["asset_id"]


class TestLibrary:
    def test_render_files_an_unfiled_project(self, client):
        aid = _render(client, "art deco sapphire ring")
        r = client.get("/library", params={"owner": "usr_ana"})
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        card = body["projects"][0]
        assert card["root_id"] == aid
        assert card["collection"] == "Unfiled"
        assert card["title"] == "art deco sapphire ring"

    def test_organize_into_a_client_folder(self, client):
        aid = _render(client, "emerald pendant")
        r = client.patch(f"/assets/{aid}/organize",
                         json={"collection": "Sarah K — engagement",
                               "title": "Sarah's emerald", "tags": ["emerald", "gift"]})
        assert r.status_code == 200
        # organizing works from ANY asset in the chain (edit child too)
        e = client.post(f"/assets/{aid}/localized-edit",
                        json={"region_description": "the bail",
                              "change_instruction": "bigger bail"})
        child = e.json()["asset_id"]
        r = client.patch(f"/assets/{child}/organize", json={"tags": ["emerald", "rush"]})
        assert r.status_code == 200 and set(r.json()["tags"]) == {"emerald", "rush"}

        col = client.get("/library/collections", params={"owner": "usr_ana"}).json()
        names = {c["collection"] for c in col["collections"]}
        assert "Sarah K — engagement" in names

    def test_filter_by_collection_and_search_text(self, client):
        a = _render(client, "art deco sapphire ring")
        b = _render(client, "plain gold band")
        client.patch(f"/assets/{a}/organize",
                     json={"collection": "Client A", "tags": ["deco", "sapphire"]})
        client.patch(f"/assets/{b}/organize", json={"collection": "Client B"})

        # by collection
        r = client.get("/library", params={"owner": "usr_ana", "collection": "Client A"})
        assert [c["root_id"] for c in r.json()["projects"]] == [a]
        # free-text over the prompt
        r = client.get("/library", params={"owner": "usr_ana", "q": "sapphire"})
        assert [c["root_id"] for c in r.json()["projects"]] == [a]
        # by tag
        r = client.get("/library", params={"owner": "usr_ana", "tag": "deco"})
        assert [c["root_id"] for c in r.json()["projects"]] == [a]
        # Unfiled bucket after moving B out
        client.patch(f"/assets/{b}/organize", json={"clear_collection": True})
        r = client.get("/library", params={"owner": "usr_ana", "collection": "Unfiled"})
        assert [c["root_id"] for c in r.json()["projects"]] == [b]

    def test_owner_isolation(self, client):
        _render(client, "ana's ring", owner="usr_ana")
        _render(client, "ben's ring", owner="usr_ben")
        assert client.get("/library", params={"owner": "usr_ana"}).json()["total"] == 1
        assert client.get("/library", params={"owner": "usr_ben"}).json()["total"] == 1

    def test_project_groups_the_whole_chain(self, client):
        aid = _render(client, "a ring")
        client.post(f"/assets/{aid}/localized-edit",
                    json={"region_description": "shank", "change_instruction": "wider"})
        r = client.get(f"/projects/{aid}")
        assert r.status_code == 200
        body = r.json()
        assert body["item_count"] == 2
        caps = [i["capability"] for i in body["items"]]
        assert caps == ["JEWELRY_RENDER", "LOCALIZED_EDIT"]
        assert body["cover_asset_id"] is not None

    def test_tags_endpoint(self, client):
        a = _render(client, "one")
        client.patch(f"/assets/{a}/organize", json={"tags": ["sapphire", "deco"]})
        r = client.get("/library/tags", params={"owner": "usr_ana"})
        tags = {t["tag"] for t in r.json()["tags"]}
        assert {"sapphire", "deco"} <= tags

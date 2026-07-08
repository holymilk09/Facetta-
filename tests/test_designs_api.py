import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from facetta.db import Base, get_db
from facetta.main import app


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
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


def _create(client, example_spec, created_by="usr_ana"):
    response = client.post("/designs", json={"created_by": created_by, "spec": example_spec})
    assert response.status_code == 201, response.text
    return response.json()


def test_create_design_assigns_identity(client, example_spec):
    stored = _create(client, example_spec)
    assert stored["design_id"].startswith("dsn_")
    assert stored["version"] == 1
    assert stored["created_by"] == "usr_ana"
    assert stored["stone"]["carat"] == 2.0


def test_edits_create_new_versions_and_never_mutate(client, example_spec):
    v1 = _create(client, example_spec)
    design_id = v1["design_id"]

    example_spec["stone"]["carat"] = 1.8
    example_spec["stone"]["dimensions_mm"] = {"length": 8.2, "width": 6.2, "depth": 4.0}
    v2 = client.post(f"/designs/{design_id}/versions",
                     json={"created_by": "usr_ana", "spec": example_spec}).json()
    assert v2["version"] == 2

    # version 1 is untouched and permanently addressable
    v1_again = client.get(f"/designs/{design_id}/versions/1").json()
    assert v1_again["stone"]["carat"] == 2.0
    assert v1_again == v1

    listing = client.get("/designs").json()["designs"]
    assert listing[0]["latest_version"] == 2


def test_history_and_changes_show_what_moved(client, example_spec):
    """A designer who adjusts a dimension can always see the before → after
    and recover the previous correct value — no LLM, pure structural diff."""
    v1 = _create(client, example_spec)
    design_id = v1["design_id"]
    old_width = example_spec["band"]["width_mm"]

    example_spec["band"]["width_mm"] = old_width - 0.2
    client.post(f"/designs/{design_id}/versions",
                json={"created_by": "usr_ana", "spec": example_spec})

    # the /changes compare defaults to the latest edit (v1 → v2)
    diff = client.get(f"/designs/{design_id}/changes").json()
    assert diff["base_version"] == 1 and diff["target_version"] == 2
    band = [c for c in diff["changes"] if c["path"] == "band.width_mm"][0]
    assert band["label"] == "band width"
    assert band["from"].startswith(str(old_width))
    assert "band width" in diff["changes_summary"]

    # the history trail carries a per-version summary; v1 is the initial one
    hist = client.get(f"/designs/{design_id}").json()["versions"]
    assert hist[0]["changes_summary"] == "initial version"
    assert "band width" in hist[1]["changes_summary"]
    # and the previous exact value is still permanently addressable
    assert client.get(f"/designs/{design_id}/versions/1").json()[
        "band"]["width_mm"] == old_width


def test_versions_are_immutable_no_update_route(client, example_spec):
    design_id = _create(client, example_spec)["design_id"]
    for method in ("PUT", "PATCH", "DELETE"):
        response = client.request(method, f"/designs/{design_id}/versions/1", json={"anything": True})
        assert response.status_code == 405, method


def test_invalid_spec_stores_nothing(client, example_spec):
    example_spec["stone"]["carat"] = 9.5
    response = client.post("/designs", json={"created_by": "usr_ana", "spec": example_spec})
    assert response.status_code == 422
    assert client.get("/designs").json()["designs"] == []


def test_stored_version_renders_stable_sheet(client, example_spec):
    design_id = _create(client, example_spec)["design_id"]
    first = client.get(f"/designs/{design_id}/versions/1/sheet.svg")
    second = client.get(f"/designs/{design_id}/versions/1/sheet.svg")
    assert first.status_code == 200
    assert first.headers["content-type"].startswith("image/svg+xml")
    assert first.text == second.text
    assert ">8.6 mm<" in first.text


def test_share_link_opens_one_unambiguous_version(client, example_spec):
    design_id = _create(client, example_spec)["design_id"]
    example_spec["stone"]["carat"] = 1.8
    example_spec["stone"]["dimensions_mm"]["depth"] = 3.7
    client.post(f"/designs/{design_id}/versions",
                json={"created_by": "usr_ana", "spec": example_spec})

    link = client.post(f"/designs/{design_id}/versions/1/share", json={}).json()
    assert link["scope"] == "comment"

    opened = client.get(link["path"]).json()
    assert opened["version"] == 1
    assert opened["spec"]["stone"]["carat"] == 2.0  # v1, even though v2 exists
    assert opened["comments"] == []

    sheet = client.get(f"{link['path']}/sheet.svg")
    assert sheet.status_code == 200 and sheet.text.startswith("<svg")


def test_factory_pins_comment_to_sheet_region(client, example_spec):
    design_id = _create(client, example_spec)["design_id"]
    link = client.post(f"/designs/{design_id}/versions/1/share", json={"scope": "comment"}).json()

    comment = client.post(f"{link['path']}/comments", json={
        "author": "Mogok Works",
        "view": "side",
        "x_pct": 62.5,
        "y_pct": 21.0,
        "body": "Prong tips 0.9 mm is fine; please confirm gallery clears a 1.5 mm band.",
    })
    assert comment.status_code == 201
    pinned = comment.json()
    assert pinned["view"] == "side" and pinned["x_pct"] == 62.5

    # visible on the share link and on the designer's side
    assert len(client.get(link["path"]).json()["comments"]) == 1
    designer_view = client.get(f"/designs/{design_id}/versions/1/comments").json()
    assert designer_view["comments"][0]["body"].startswith("Prong tips")


def test_view_only_link_cannot_comment(client, example_spec):
    design_id = _create(client, example_spec)["design_id"]
    link = client.post(f"/designs/{design_id}/versions/1/share", json={"scope": "view"}).json()
    response = client.post(f"{link['path']}/comments", json={
        "author": "x", "view": "top", "x_pct": 1, "y_pct": 1, "body": "hi",
    })
    assert response.status_code == 403


def test_comment_anchor_bounds_enforced(client, example_spec):
    design_id = _create(client, example_spec)["design_id"]
    response = client.post(f"/designs/{design_id}/versions/1/comments", json={
        "author": "x", "view": "top", "x_pct": 140, "y_pct": 10, "body": "off-sheet",
    })
    assert response.status_code == 422


def test_unknown_design_and_version_404(client, example_spec):
    assert client.get("/designs/dsn_nope").status_code == 404
    design_id = _create(client, example_spec)["design_id"]
    assert client.get(f"/designs/{design_id}/versions/9").status_code == 404
    assert client.get("/share/not-a-token").status_code == 404


def test_users_roundtrip(client):
    created = client.post("/users", json={"name": "Ana", "role": "designer"})
    assert created.status_code == 201
    assert created.json()["id"].startswith("usr_")
    assert client.get("/users").json()["users"][0]["name"] == "Ana"


def test_collections_group_and_filter(client, example_spec):
    client.post("/designs", json={"created_by": "usr_ana", "spec": example_spec,
                                  "collection": "Client — Sarah K"})
    solo = _create(client, example_spec)  # no collection

    listing = client.get("/designs").json()["designs"]
    assert {d["collection"] for d in listing} == {"Client — Sarah K", None}

    filtered = client.get("/designs", params={"collection": "Client — Sarah K"}).json()["designs"]
    assert len(filtered) == 1 and filtered[0]["collection"] == "Client — Sarah K"

    # a later version may regroup the container; the versions stay immutable
    moved = client.post(f"/designs/{solo['design_id']}/versions",
                        json={"created_by": "usr_ana", "spec": example_spec,
                              "collection": "My sketches"})
    assert moved.status_code == 201
    listing = client.get("/designs", params={"collection": "My sketches"}).json()["designs"]
    assert [d["design_id"] for d in listing] == [solo["design_id"]]

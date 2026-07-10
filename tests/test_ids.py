"""Identity contract: user-visible rows that may one day replicate across
regional databases carry opaque, globally-unique IDs — never auto-increment
integers, which two regions would both mint as 1, 2, 3… and collide on sync.
See docs/hosting-and-data-residency.md."""

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from facetta.db import Base, get_db, new_id
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


def test_new_id_is_prefixed_and_high_entropy():
    ident = new_id("msg")
    assert ident.startswith("msg_")
    hex_part = ident.split("_", 1)[1]
    assert re.fullmatch(r"[0-9a-f]{16}", hex_part)  # 8 bytes / 64-bit
    assert len({new_id("msg") for _ in range(2000)}) == 2000  # no collisions


def test_message_and_comment_ids_are_opaque_and_global(client, example_spec):
    design_id = client.post(
        "/designs", json={"created_by": "usr_ana", "spec": example_spec}
    ).json()["design_id"]

    m1 = client.post(f"/designs/{design_id}/messages",
                     json={"author": "usr_ana", "body": "one"}).json()
    m2 = client.post(f"/designs/{design_id}/messages",
                     json={"author": "usr_wei", "body": "two"}).json()
    assert isinstance(m1["id"], str) and m1["id"].startswith("msg_")
    assert m2["id"].startswith("msg_") and m1["id"] != m2["id"]

    c1 = client.post(f"/designs/{design_id}/versions/1/comments",
                     json={"author": "usr_wei", "view": "top",
                           "x_pct": 10, "y_pct": 20, "body": "a"}).json()
    c2 = client.post(f"/designs/{design_id}/versions/1/comments",
                     json={"author": "usr_wei", "view": "side",
                           "x_pct": 30, "y_pct": 40, "body": "b"}).json()
    assert c1["id"].startswith("cmt_") and c2["id"].startswith("cmt_")
    assert c1["id"] != c2["id"]

    # message and comment id-spaces never overlap (distinct prefixes)
    assert {m1["id"], m2["id"]}.isdisjoint({c1["id"], c2["id"]})

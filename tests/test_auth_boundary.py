"""Studio beta routes authorize from a first-party principal, not body labels."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from facetta.db import (
    Base, Design, DesignFamily, FeedbackEvent, ImageAsset, ImageRun, Project,
    get_db, utcnow,
)
from facetta.main import app
from facetta.studio_visual_candidates import store_studio_visual_candidate


OWNER_TOKEN = "owner-session-token-1234"
OTHER_TOKEN = "other-session-token-1234"


@pytest.fixture
def auth_client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    now = utcnow()
    with Session() as db:
        root = ImageAsset(
            id="ast_auth_root",
            root_id="ast_auth_root",
            parent_asset_id=None,
            design_id=None,
            design_version=None,
            capability="CREATIVE_RENDER",
            instruction="Authenticated concept",
            image=b"auth-image",
            media_type="image/png",
            created_by="usr_owner",
            created_at=now,
        )
        orphan = ImageAsset(
            id="ast_orphan",
            root_id="ast_orphan",
            parent_asset_id=None,
            design_id=None,
            design_version=None,
            capability="CREATIVE_RENDER",
            instruction="Legacy orphan",
            image=b"orphan-image",
            media_type="image/png",
            created_by="usr_owner",
            created_at=now,
        )
        ownerless = ImageAsset(
            id="ast_ownerless",
            root_id="ast_ownerless",
            parent_asset_id=None,
            design_id=None,
            design_version=None,
            capability="CREATIVE_RENDER",
            instruction="Ownerless legacy asset",
            image=b"ownerless-image",
            media_type="image/png",
            created_by="",
            created_at=now,
        )
        other_orphan = ImageAsset(
            id="ast_other_orphan",
            root_id="ast_other_orphan",
            parent_asset_id=None,
            design_id=None,
            design_version=None,
            capability="CREATIVE_RENDER",
            instruction="Other private instruction",
            image=b"other-image",
            media_type="image/png",
            created_by="usr_other",
            created_at=now,
        )
        project = Project(
            root_id=root.id,
            owner="usr_owner",
            title="Private project",
            tags=[],
            selected_candidate_asset_id=root.id,
            created_at=now,
            updated_at=now,
        )
        db.add_all([root, orphan, ownerless, other_orphan, project])
        db.add_all([
            Design(
                id="dsn_owner", created_by="usr_owner", created_at=now,
                collection=None,
            ),
            Design(
                id="dsn_other", created_by="usr_other", created_at=now,
                collection=None,
            ),
            FeedbackEvent(
                asset_id=root.id, action="accepted", created_by="usr_owner",
            ),
            FeedbackEvent(
                asset_id=other_orphan.id, action="rejected",
                created_by="usr_other",
            ),
        ])
        db.add(ImageRun(
            id="run_owner",
            project_root_id=root.id,
            source_asset_id=root.id,
            operation="CREATIVE_GENERATE",
            normalized_intent={},
            prompt_version="auth-test.v1",
            variant=0,
            status="review_required",
            created_by="usr_owner",
            created_at=now,
        ))
        db.add_all([
            DesignFamily(
                id="fam_owner", owner="usr_owner", title="Owner family",
                created_at=now, updated_at=now,
            ),
            DesignFamily(
                id="fam_other", owner="usr_other", title="Other family",
                created_at=now, updated_at=now,
            ),
        ])
        db.commit()

    def override_db():
        with Session() as db:
            yield db

    monkeypatch.setenv("FACETTA_AUTH_MODE", "required")
    monkeypatch.setenv("FACETTA_AUTH_PRINCIPALS_JSON", json.dumps({
        OWNER_TOKEN: "usr_owner",
        OTHER_TOKEN: "usr_other",
    }))
    app.dependency_overrides[get_db] = override_db
    try:
        yield TestClient(app), Session
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize(
    ("header", "code"),
    [
        (None, "authentication_required"),
        ("Bearer invalid-session-token", "invalid_authentication_token"),
    ],
)
def test_project_routes_fail_closed_for_missing_or_invalid_token(
    auth_client,
    header: str | None,
    code: str,
):
    client, _Session = auth_client
    headers = {} if header is None else {"Authorization": header}
    response = client.get("/projects/ast_auth_root", headers=headers)
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == code


def test_cross_owner_project_read_is_denied(auth_client):
    client, _Session = auth_client
    response = client.get(
        "/projects/ast_auth_root",
        headers={"Authorization": f"Bearer {OTHER_TOKEN}"},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "project_access_denied"


def test_studio_routes_share_the_same_required_principal_boundary(auth_client):
    client, _Session = auth_client
    for url in (
        "/studio/jobs?owner=usr_owner",
        "/studio/families",
        "/assets/ast_auth_root/image",
        "/image-runs/run_owner",
    ):
        response = client.get(url)
        assert response.status_code == 401
        assert response.json()["detail"]["code"] == "authentication_required"


def test_owner_and_created_by_fields_cannot_spoof_principal(auth_client):
    client, _Session = auth_client
    response = client.post(
        "/projects/ast_auth_root/creative-candidates/ast_auth_root/select",
        headers={"Authorization": f"Bearer {OWNER_TOKEN}"},
        json={"created_by": "usr_other"},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "principal_actor_mismatch"
    confirm = client.post(
        "/projects/ast_auth_root/creative-candidates/ast_auth_root/confirm-design",
        headers={"Authorization": f"Bearer {OWNER_TOKEN}"},
        json={"created_by": "usr_other"},
    )
    assert confirm.status_code == 403
    assert confirm.json()["detail"]["code"] == "principal_actor_mismatch"


def test_authenticated_owner_can_read_own_project(auth_client):
    client, _Session = auth_client
    response = client.get(
        "/projects/ast_auth_root",
        headers={"Authorization": f"Bearer {OWNER_TOKEN}"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["owner"] == "usr_owner"


def test_family_list_and_detail_are_scoped_to_principal(auth_client):
    client, _Session = auth_client
    headers = {"Authorization": f"Bearer {OWNER_TOKEN}"}
    listed = client.get("/studio/families", headers=headers)
    assert listed.status_code == 200, listed.text
    assert [item["family_id"] for item in listed.json()["families"]] == [
        "fam_owner"
    ]
    denied = client.get("/studio/families/fam_other", headers=headers)
    assert denied.status_code == 404
    spoof = client.get(
        "/studio/families", params={"owner": "usr_other"}, headers=headers)
    assert spoof.status_code == 403
    assert spoof.json()["detail"]["code"] == "principal_actor_mismatch"
    jobs = client.get(
        "/studio/jobs", params={"owner": "usr_other"}, headers=headers)
    assert jobs.status_code == 403
    assert jobs.json()["detail"]["code"] == "principal_actor_mismatch"


def test_history_asset_and_visual_candidate_reads_deny_other_principal(
    auth_client,
):
    client, _Session = auth_client
    headers = {"Authorization": f"Bearer {OTHER_TOKEN}"}
    history = client.get(
        "/studio/projects/ast_auth_root/history", headers=headers)
    assert history.status_code == 403
    assert history.json()["detail"]["code"] == "project_access_denied"
    asset = client.get("/assets/ast_auth_root/image", headers=headers)
    assert asset.status_code == 403
    assert asset.json()["detail"]["code"] == "asset_access_denied"

    candidate = store_studio_visual_candidate(
        run_id="run_auth_visual",
        verdict="pass",
        project_root_id="ast_auth_root",
        source_asset_id="ast_auth_root",
        expected_selected_candidate_asset_id="ast_auth_root",
        source_hash="a" * 64,
        image_bytes=b"private-preview",
        media_type="image/png",
        requested_change="polish",
        scope="appearance",
        qa={},
        created_by="usr_owner",
    )
    preview = client.get(
        f"/studio/image-runs/{candidate.run_id}/visual-candidates/"
        f"{candidate.candidate_id}/image",
        headers=headers,
    )
    assert preview.status_code == 404


def test_orphan_and_ownerless_assets_fail_closed(auth_client):
    client, _Session = auth_client
    other = {"Authorization": f"Bearer {OTHER_TOKEN}"}
    assert client.get("/assets/ast_orphan/image", headers=other).status_code == 403
    owner = {"Authorization": f"Bearer {OWNER_TOKEN}"}
    assert client.get(
        "/assets/ast_ownerless/image", headers=owner).status_code == 403


def test_trusted_image_run_evidence_denies_other_principal(auth_client):
    client, _Session = auth_client
    response = client.get(
        "/image-runs/run_owner",
        headers={"Authorization": f"Bearer {OTHER_TOKEN}"},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "image_run_access_denied"


def test_render_actor_design_link_and_insights_are_tenant_scoped(
    auth_client,
    monkeypatch,
):
    client, _Session = auth_client
    headers = {"Authorization": f"Bearer {OWNER_TOKEN}"}
    render_calls: list[str] = []

    def unexpected_render(*_args, **_kwargs):
        render_calls.append("called")
        raise AssertionError("foreign-design render reached the provider")

    monkeypatch.setattr("facetta.api.assets.jewelry_render", unexpected_render)
    spoofed_render = client.post("/assets/render", headers=headers, json={
        "piece_description": "A private solitaire ring",
        "created_by": "usr_other",
    })
    assert spoofed_render.status_code == 403
    assert spoofed_render.json()["detail"]["code"] == (
        "principal_actor_mismatch"
    )
    foreign_design_render = client.post("/assets/render", headers=headers, json={
        "piece_description": "A private solitaire ring",
        "created_by": "usr_owner",
        "design_id": "dsn_other",
    })
    assert foreign_design_render.status_code == 403
    assert foreign_design_render.json()["detail"]["code"] == (
        "design_access_denied"
    )
    assert render_calls == []

    link = client.patch(
        "/assets/ast_auth_root/link-design",
        headers=headers,
        json={"design_id": "dsn_other"},
    )
    assert link.status_code == 403
    assert link.json()["detail"]["code"] == "design_access_denied"

    stats = client.get("/assets/insights/instruction-stats", headers=headers)
    assert stats.status_code == 200, stats.text
    assert stats.json()["events"] == 1
    assert stats.json()["by_capability"]["CREATIVE_RENDER"]["accepted"] == 1
    assert stats.json()["by_capability"]["CREATIVE_RENDER"]["rejected"] == 0


def test_feedback_actor_spoof_is_rejected_without_append(auth_client):
    client, Session = auth_client
    response = client.post(
        "/assets/ast_auth_root/feedback",
        headers={"Authorization": f"Bearer {OWNER_TOKEN}"},
        json={"action": "accepted", "created_by": "usr_other"},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "principal_actor_mismatch"
    with Session() as db:
        events = list(db.query(FeedbackEvent).filter(
            FeedbackEvent.asset_id == "ast_auth_root"
        ))
        assert len(events) == 1

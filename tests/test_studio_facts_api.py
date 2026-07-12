"""Authenticated API coverage for atomic Studio fact revisions."""

from __future__ import annotations

import copy
import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from conftest import EXAMPLE_SPEC

from facetta.db import (
    Base,
    Design,
    DesignVersion,
    ImageAsset,
    Project,
    ProjectRevisionRecord,
    get_db,
    utcnow,
)
from facetta.main import app


OWNER_TOKEN = "studio-facts-owner-token"
OTHER_TOKEN = "studio-facts-other-token"
OWNER_HEADERS = {"Authorization": f"Bearer {OWNER_TOKEN}"}
OTHER_HEADERS = {"Authorization": f"Bearer {OTHER_TOKEN}"}


def _seed_exact_project(
    sessions: sessionmaker[Session],
    *,
    project_id: str,
    design_id: str,
    owner: str,
) -> None:
    now = utcnow()
    spec = copy.deepcopy(EXAMPLE_SPEC)
    spec.update({
        "design_id": design_id,
        "version": 1,
        "created_by": owner,
    })
    with sessions() as db:
        db.add_all([
            Design(id=design_id, created_by=owner, created_at=now),
            DesignVersion(
                design_id=design_id,
                version=1,
                spec=spec,
                created_by=owner,
                created_at=now,
            ),
            ImageAsset(
                id=project_id,
                root_id=project_id,
                parent_asset_id=None,
                design_id=design_id,
                design_version=1,
                capability="JEWELRY_RENDER",
                image=f"image-{project_id}".encode(),
                media_type="image/png",
                created_by=owner,
                created_at=now,
            ),
            Project(
                root_id=project_id,
                owner=owner,
                title="Studio fact ring",
                tags=[],
                selected_candidate_asset_id=project_id,
                created_at=now,
                updated_at=now,
            ),
        ])
        db.commit()


@pytest.fixture()
def facts_api(monkeypatch) -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    _seed_exact_project(
        sessions,
        project_id="ast_facts_api",
        design_id="dsn_facts_api",
        owner="usr_designer",
    )
    _seed_exact_project(
        sessions,
        project_id="ast_facts_foreign",
        design_id="dsn_facts_foreign",
        owner="usr_other",
    )

    def override_db() -> Iterator[Session]:
        with sessions() as db:
            yield db

    monkeypatch.setenv("FACETTA_AUTH_MODE", "opaque")
    monkeypatch.setenv("FACETTA_AUTH_PRINCIPALS_JSON", json.dumps({
        OWNER_TOKEN: "usr_designer",
        OTHER_TOKEN: "usr_other",
    }))
    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            yield client, sessions
    finally:
        app.dependency_overrides.clear()


def _request(*, created_by: str = "usr_designer") -> dict:
    return {
        "expected_active_asset_id": "ast_facts_api",
        "expected_design_version": 1,
        "created_by": created_by,
        "changes": [
            {"path": "band.width_mm", "value": 2.2},
            {"path": "metal.finish", "value": "satin"},
        ],
    }


def test_fact_revision_requires_authentication_and_canonical_actor(facts_api):
    client, _sessions = facts_api
    missing = client.post(
        "/studio/projects/ast_facts_api/facts/revise",
        json=_request(),
    )
    assert missing.status_code == 401
    assert missing.json()["detail"]["code"] == "authentication_required"

    mismatch = client.post(
        "/studio/projects/ast_facts_api/facts/revise",
        headers=OWNER_HEADERS,
        json=_request(created_by="usr_other"),
    )
    assert mismatch.status_code == 403
    assert mismatch.json()["detail"]["code"] == "principal_actor_mismatch"


def test_fact_revision_rejects_foreign_project_before_mutation(facts_api):
    client, sessions = facts_api
    body = _request()
    body["expected_active_asset_id"] = "ast_facts_foreign"
    response = client.post(
        "/studio/projects/ast_facts_foreign/facts/revise",
        headers=OWNER_HEADERS,
        json=body,
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "project_access_denied"
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 2
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 2


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("expected_active_asset_id", "ast_stale"),
        ("expected_design_version", 2),
    ],
)
def test_fact_revision_maps_stale_guards_to_safe_conflict(
    facts_api,
    field: str,
    value: object,
):
    client, sessions = facts_api
    body = _request()
    body[field] = value
    response = client.post(
        "/studio/projects/ast_facts_api/facts/revise",
        headers=OWNER_HEADERS,
        json=body,
    )
    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "stale_fact_revision",
        "error_category": "conflict",
        "detail": (
            "the active image or specification changed before this fact edit"
        ),
    }
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 2
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 2
        assert db.scalar(
            select(func.count()).select_from(ProjectRevisionRecord)
        ) == 0


def test_fact_revision_no_op_keeps_lineage_unchanged(facts_api):
    client, sessions = facts_api
    body = _request()
    body["changes"] = [{"path": "band.width_mm", "value": 1.8}]
    response = client.post(
        "/studio/projects/ast_facts_api/facts/revise",
        headers=OWNER_HEADERS,
        json=body,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "no_change"
    assert payload["asset_id"] == "ast_facts_api"
    assert payload["design_version"] == 1
    assert payload["spec_change"] == []
    assert payload["project_detail"]["active_asset_id"] == "ast_facts_api"
    assert payload["project_detail"]["active_design_version"] == 1
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 2
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 2
        assert db.scalar(
            select(func.count()).select_from(ProjectRevisionRecord)
        ) == 0


def test_fact_revision_atomically_advances_project_detail(facts_api):
    client, sessions = facts_api
    response = client.post(
        "/studio/projects/ast_facts_api/facts/revise",
        headers=OWNER_HEADERS,
        json=_request(),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "applied"
    assert payload["source_asset_id"] == "ast_facts_api"
    assert payload["asset_id"] != payload["source_asset_id"]
    assert payload["previous_design_version"] == 1
    assert payload["design_version"] == 2
    assert payload["project_detail"]["active_asset_id"] == payload["asset_id"]
    assert payload["project_detail"]["active_design_version"] == 2
    assert payload["project_detail"]["latest_design_version"] == 2
    assert {change["path"] for change in payload["spec_change"]} >= {
        "band.width_mm",
        "metal.finish",
    }
    assert "provider" not in response.text.lower()
    assert "model_name" not in response.text.lower()

    with sessions() as db:
        versions = list(db.scalars(select(DesignVersion).where(
            DesignVersion.design_id == "dsn_facts_api"
        ).order_by(DesignVersion.version)))
        assets = list(db.scalars(select(ImageAsset).where(
            ImageAsset.root_id == "ast_facts_api"
        ).order_by(ImageAsset.created_at, ImageAsset.id)))
        project = db.get(Project, "ast_facts_api")
        record = db.scalar(select(ProjectRevisionRecord).where(
            ProjectRevisionRecord.asset_id == payload["asset_id"]
        ))
        assert [version.version for version in versions] == [1, 2]
        assert versions[1].spec["band"]["width_mm"] == 2.2
        assert versions[1].spec["metal"]["finish"] == "satin"
        assert len(assets) == 2
        assert bytes(assets[0].image) == bytes(assets[1].image)
        assert project is not None
        assert project.selected_candidate_asset_id == payload["asset_id"]
        assert record is not None


def test_fact_revision_request_and_allowlist_fail_closed(facts_api):
    client, _sessions = facts_api
    duplicate = _request()
    duplicate["changes"] = [
        {"path": "band.width_mm", "value": 2.0},
        {"path": "band.width_mm", "value": 2.2},
    ]
    duplicate_response = client.post(
        "/studio/projects/ast_facts_api/facts/revise",
        headers=OWNER_HEADERS,
        json=duplicate,
    )
    assert duplicate_response.status_code == 422

    unsafe = _request()
    unsafe["changes"] = [{
        "path": "notes_to_factory",
        "value": "silently override production instructions",
    }]
    unsafe_response = client.post(
        "/studio/projects/ast_facts_api/facts/revise",
        headers=OWNER_HEADERS,
        json=unsafe,
    )
    assert unsafe_response.status_code == 422
    assert unsafe_response.json()["detail"]["code"] == "fact_path_not_allowed"

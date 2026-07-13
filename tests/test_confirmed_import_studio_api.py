"""Canonical Studio import contracts and legacy compatibility boundaries."""

from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from conftest import audited_import_spec

from facetta.db import Base, Design, DesignVersion, ImageAsset, Project, get_db
from facetta.main import app, create_app


OWNER_TOKEN = "owner-confirmed-import-token"
OTHER_TOKEN = "other-confirmed-import-token"
OWNER_HEADERS = {"Authorization": f"Bearer {OWNER_TOKEN}"}


def _png(color: tuple[int, int, int] = (17, 83, 149)) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (31, 29), color).save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def confirmed_import_client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)

    def override():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setenv("FACETTA_AUTH_MODE", "opaque")
    monkeypatch.setenv("FACETTA_AUTH_PRINCIPALS_JSON", json.dumps({
        OWNER_TOKEN: "usr_ana",
        OTHER_TOKEN: "usr_other",
    }))
    app.dependency_overrides[get_db] = override
    try:
        yield TestClient(app), Session
    finally:
        app.dependency_overrides.clear()


def _request(example_spec: dict, image: bytes | None = None) -> dict:
    exact_image = image or _png()
    spec = audited_import_spec(example_spec)
    spec["source_component_coverage"]["audited_source_sha256"] = (
        hashlib.sha256(exact_image).hexdigest()
    )
    return {
        "image_base64": base64.b64encode(exact_image).decode(),
        "media_type": "image/png",
        "spec": spec,
        "owner": "usr_ana",
        "title": "Confirmed blue solitaire",
        "collection": "Exact references",
        "tags": ["confirmed", " sapphire "],
    }


def _counts(Session) -> dict[str, int]:
    with Session() as db:
        return {
            "designs": db.scalar(select(func.count()).select_from(Design)),
            "versions": db.scalar(
                select(func.count()).select_from(DesignVersion),
            ),
            "assets": db.scalar(select(func.count()).select_from(ImageAsset)),
            "projects": db.scalar(select(func.count()).select_from(Project)),
        }


def test_studio_confirmed_import_requires_owner_authentication(
    confirmed_import_client,
    example_spec,
):
    client, Session = confirmed_import_client
    request = _request(example_spec)

    missing = client.post("/studio/projects/import-confirmed", json=request)
    assert missing.status_code == 401
    assert missing.json()["detail"]["code"] == "authentication_required"

    spoofed = client.post(
        "/studio/projects/import-confirmed",
        json=request,
        headers={"Authorization": f"Bearer {OTHER_TOKEN}"},
    )
    assert spoofed.status_code == 403
    assert spoofed.json()["detail"]["code"] == "principal_actor_mismatch"
    assert _counts(Session) == {
        "designs": 0, "versions": 0, "assets": 0, "projects": 0,
    }


def test_studio_confirmed_import_preserves_exact_bytes_and_spec_provenance(
    confirmed_import_client,
    example_spec,
):
    client, Session = confirmed_import_client
    exact_image = _png((9, 71, 133))
    request = _request(example_spec, exact_image)

    response = client.post(
        "/studio/projects/import-confirmed",
        json=request,
        headers=OWNER_HEADERS,
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["owner"] == "usr_ana"
    assert body["active_revision"]["capability"] == "IMPORTED_REFERENCE"
    assert body["active_revision"]["provenance"] == "imported_reference"
    assert body["spec"]["source_component_coverage"][
        "audited_source_sha256"
    ] == hashlib.sha256(exact_image).hexdigest()
    assert body["spec"]["source_component_coverage"][
        "audited_spec_visual_hash"
    ] == request["spec"]["source_component_coverage"][
        "audited_spec_visual_hash"
    ]

    with Session() as db:
        project = db.get(Project, body["root_id"])
        assert project is not None
        asset = db.get(ImageAsset, body["active_asset_id"])
        assert asset is not None
        assert asset.image == exact_image
        version = db.get(DesignVersion, (body["design_id"], 1))
        assert version is not None
        assert version.spec["source_component_coverage"] == (
            body["spec"]["source_component_coverage"]
        )
        assert version.spec["stone"]["species"] == (
            request["spec"]["stone"]["species"]
        )
        assert version.spec["stone"]["dimensions_mm"] == (
            request["spec"]["stone"]["dimensions_mm"]
        )


def test_studio_confirmed_import_rejects_stale_source_hash_without_writes(
    confirmed_import_client,
    example_spec,
):
    client, Session = confirmed_import_client
    request = _request(example_spec)
    request["spec"]["source_component_coverage"][
        "audited_source_sha256"
    ] = "f" * 64

    response = client.post(
        "/studio/projects/import-confirmed",
        json=request,
        headers=OWNER_HEADERS,
    )

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "source_component_source_audit_stale"
    assert _counts(Session) == {
        "designs": 0, "versions": 0, "assets": 0, "projects": 0,
    }


def test_studio_confirmed_import_requires_source_hash_without_writes(
    confirmed_import_client,
    example_spec,
):
    client, Session = confirmed_import_client
    request = _request(example_spec)
    request["spec"]["source_component_coverage"].pop(
        "audited_source_sha256",
    )

    response = client.post(
        "/studio/projects/import-confirmed",
        json=request,
        headers=OWNER_HEADERS,
    )

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "source_component_source_audit_required"
    assert _counts(Session) == {
        "designs": 0, "versions": 0, "assets": 0, "projects": 0,
    }


def test_legacy_and_studio_confirmed_imports_have_semantic_parity(
    confirmed_import_client,
    example_spec,
):
    client, Session = confirmed_import_client
    exact_image = _png((121, 29, 77))
    request = _request(example_spec, exact_image)

    studio = client.post(
        "/studio/projects/import-confirmed",
        json=request,
        headers=OWNER_HEADERS,
    )
    legacy = client.post(
        "/projects/from-image",
        json=request,
        headers=OWNER_HEADERS,
    )

    assert studio.status_code == legacy.status_code == 201
    studio_body = studio.json()
    legacy_body = legacy.json()
    for field in (
        "title", "collection", "tags", "owner", "state",
        "primary_revision_count", "item_count", "factory_ready",
    ):
        assert studio_body[field] == legacy_body[field]
    for body in (studio_body, legacy_body):
        assert body["active_revision"]["capability"] == "IMPORTED_REFERENCE"
        assert body["active_revision"]["provenance"] == "imported_reference"
    assert studio_body["spec"]["stone"] == legacy_body["spec"]["stone"]
    assert studio_body["spec"]["source_component_coverage"] == (
        legacy_body["spec"]["source_component_coverage"]
    )
    assert _counts(Session) == {
        "designs": 2, "versions": 2, "assets": 2, "projects": 2,
    }


def test_studio_confirmed_import_rolls_back_every_row_when_flush_fails(
    confirmed_import_client,
    example_spec,
    monkeypatch,
):
    client, Session = confirmed_import_client
    original_flush = Session.class_.flush

    def fail_after_persistence_flush(session, *args, **kwargs):
        is_confirmed_import = any(
            isinstance(row, Project) for row in session.new
        )
        result = original_flush(session, *args, **kwargs)
        if is_confirmed_import:
            raise RuntimeError("simulated confirmed-import database failure")
        return result

    monkeypatch.setattr(Session.class_, "flush", fail_after_persistence_flush)
    with pytest.raises(
        RuntimeError,
        match="simulated confirmed-import database failure",
    ):
        client.post(
            "/studio/projects/import-confirmed",
            json=_request(example_spec),
            headers=OWNER_HEADERS,
        )

    assert _counts(Session) == {
        "designs": 0, "versions": 0, "assets": 0, "projects": 0,
    }


def test_production_exposes_only_the_canonical_studio_import(monkeypatch):
    monkeypatch.setenv("FACETTA_ENV", "production")
    monkeypatch.setenv("FACETTA_AUTH_MODE", "supabase")
    monkeypatch.setenv(
        "FACETTA_SUPABASE_URL",
        "https://facetta-test.supabase.co",
    )

    paths = create_app().openapi()["paths"]

    assert "post" in paths["/studio/projects/import-confirmed"]
    assert "/projects/from-image" not in paths


@pytest.mark.parametrize("relative_path", [
    "mobile/src/trusted/client.ts",
    "scripts/run_designer_corrected_e2e.py",
    "scripts/run_standard_halo_full_e2e.py",
    "scripts/run_live_edit_factory_e2e.py",
    "scripts/run_necklace_chain_catalog_eval.py",
])
def test_live_callers_use_the_canonical_studio_import(relative_path: str):
    repository_root = Path(__file__).resolve().parents[1]
    source = (repository_root / relative_path).read_text()

    assert "/studio/projects/import-confirmed" in source
    assert '"/projects/from-image"' not in source
    assert "'/projects/from-image'" not in source

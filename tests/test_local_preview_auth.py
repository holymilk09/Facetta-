"""Fail-closed coverage for the ephemeral localhost preview session."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from facetta.api import local_preview_auth as local_preview_api
from facetta.auth import (
    AuthenticatedPrincipal,
    require_authenticated_principal,
)
from facetta.local_preview_auth import (
    LOCAL_PREVIEW_SESSION_SECONDS,
    LOCAL_PREVIEW_SUBJECT,
)
from facetta.main import create_app


LOOPBACK_ORIGIN = "http://127.0.0.1:8081"


def _enable_preview(monkeypatch, *, environment: str = "development") -> None:
    monkeypatch.setenv("FACETTA_ENV", environment)
    monkeypatch.setenv("FACETTA_AUTH_MODE", "required")
    monkeypatch.setenv("FACETTA_LOCAL_PREVIEW_AUTH", "true")
    monkeypatch.delenv("FACETTA_SUPABASE_URL", raising=False)


def _preview_test_app() -> FastAPI:
    application = FastAPI()
    application.include_router(local_preview_api.router)

    @application.get("/whoami")
    async def whoami(
        principal: AuthenticatedPrincipal = Depends(
            require_authenticated_principal,
        ),
    ) -> dict[str, str | None]:
        return {"subject": principal.subject}

    return application


def test_preview_route_is_absent_without_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("FACETTA_ENV", "development")
    monkeypatch.setenv("FACETTA_AUTH_MODE", "required")
    monkeypatch.delenv("FACETTA_LOCAL_PREVIEW_AUTH", raising=False)
    application = create_app()

    assert "/auth/local-preview-session" not in application.openapi()["paths"]
    response = TestClient(
        application,
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 51001),
    ).post(
        "/auth/local-preview-session",
        headers={"Origin": LOOPBACK_ORIGIN},
    )
    assert response.status_code == 404


def test_preview_route_is_absent_in_production_even_when_flag_is_set(
    monkeypatch,
):
    monkeypatch.setenv("FACETTA_ENV", "production")
    monkeypatch.setenv("FACETTA_AUTH_MODE", "supabase")
    monkeypatch.setenv(
        "FACETTA_SUPABASE_URL", "https://facetta-test.supabase.co",
    )
    monkeypatch.setenv("FACETTA_LOCAL_PREVIEW_AUTH", "true")
    application = create_app()

    assert application.openapi_url is None
    response = TestClient(
        application,
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 51002),
    ).post(
        "/auth/local-preview-session",
        headers={"Origin": LOOPBACK_ORIGIN},
    )
    assert response.status_code == 404


def test_preview_session_is_bounded_non_cacheable_and_authenticates(
    monkeypatch,
):
    _enable_preview(monkeypatch)
    client = TestClient(
        _preview_test_app(),
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 51003),
    )

    issued = client.post(
        "/auth/local-preview-session",
        headers={"Origin": LOOPBACK_ORIGIN},
    )
    assert issued.status_code == 201, issued.text
    assert issued.headers["cache-control"] == "no-store, private"
    assert issued.headers["pragma"] == "no-cache"
    body = issued.json()
    assert body["token_type"] == "bearer"
    assert body["designer_id"] == LOCAL_PREVIEW_SUBJECT
    assert isinstance(body["access_token"], str) and body["access_token"]
    assert body["access_token"] not in repr(dict(issued.headers))
    assert LOCAL_PREVIEW_SESSION_SECONDS == 2 * 60 * 60
    expires_at = datetime.fromisoformat(body["expires_at"])
    remaining = (expires_at - datetime.now(timezone.utc)).total_seconds()
    assert LOCAL_PREVIEW_SESSION_SECONDS - 10 <= remaining <= (
        LOCAL_PREVIEW_SESSION_SECONDS + 1
    )

    authenticated = client.get(
        "/whoami",
        headers={
            "Authorization": f"Bearer {body['access_token']}",
            "Origin": LOOPBACK_ORIGIN,
        },
    )
    assert authenticated.status_code == 200, authenticated.text
    assert authenticated.json() == {"subject": LOCAL_PREVIEW_SUBJECT}


def test_preview_session_rejects_remote_socket_or_remote_browser_origin(
    monkeypatch,
):
    _enable_preview(monkeypatch)
    remote_socket = TestClient(
        _preview_test_app(),
        base_url="http://127.0.0.1",
        client=("203.0.113.9", 51004),
    )
    assert remote_socket.post(
        "/auth/local-preview-session",
        headers={"Origin": LOOPBACK_ORIGIN},
    ).status_code == 404

    loopback_socket = TestClient(
        _preview_test_app(),
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 51005),
    )
    assert loopback_socket.post(
        "/auth/local-preview-session",
        headers={"Origin": "https://attacker.example"},
    ).status_code == 404


def test_issued_token_stops_working_when_opt_in_is_removed(monkeypatch):
    _enable_preview(monkeypatch)
    client = TestClient(
        _preview_test_app(),
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 51006),
    )
    token = client.post(
        "/auth/local-preview-session",
        headers={"Origin": LOOPBACK_ORIGIN},
    ).json()["access_token"]

    monkeypatch.delenv("FACETTA_LOCAL_PREVIEW_AUTH")
    rejected = client.get(
        "/whoami",
        headers={
            "Authorization": f"Bearer {token}",
            "Origin": LOOPBACK_ORIGIN,
        },
    )
    assert rejected.status_code == 401
    assert rejected.json()["detail"]["code"] == (
        "invalid_authentication_token"
    )


def test_opted_in_development_app_mounts_the_preview_route(monkeypatch):
    _enable_preview(monkeypatch)
    application = create_app()
    assert "/auth/local-preview-session" in application.openapi()["paths"]
    response = TestClient(
        application,
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 51007),
    ).post(
        "/auth/local-preview-session",
        headers={"Origin": LOOPBACK_ORIGIN},
    )
    assert response.status_code == 201, response.text

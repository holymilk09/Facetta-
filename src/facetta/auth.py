"""First-party authenticated principal boundary for Studio beta routes."""

from __future__ import annotations

import hmac
import json
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlparse
from uuid import UUID

from fastapi import Depends, HTTPException, Request
import jwt
from jwt import PyJWKClient, PyJWTError
from jwt.exceptions import (
    PyJWKClientConnectionError, PyJWKClientError, PyJWKSetError,
)
from sqlalchemy.orm import Session

from facetta.config import env_value
from facetta.db import ImageAsset, ImageRun, Project, get_db


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    subject: str | None
    local_unbound: bool = False


def validate_auth_configuration() -> None:
    """Reject unsafe or incomplete authentication before serving traffic."""
    mode = (env_value("FACETTA_AUTH_MODE") or "required").strip().lower()
    environment = (env_value("FACETTA_ENV") or "production").strip().lower()
    allowed = {"required", "supabase", "opaque", "local", "test"}
    if environment not in {"development", "test", "production"}:
        raise RuntimeError("FACETTA_ENV is not recognized")
    if mode not in allowed:
        raise RuntimeError("FACETTA_AUTH_MODE is not recognized")
    if mode == "supabase" and _supabase_issuer() is None:
        raise RuntimeError("Supabase authentication requires a valid FACETTA_SUPABASE_URL")
    audience = (env_value("FACETTA_SUPABASE_AUDIENCE") or "authenticated").strip()
    if mode == "supabase" and audience != "authenticated":
        raise RuntimeError("Supabase authentication requires audience=authenticated")
    if environment == "production" and mode != "supabase":
        raise RuntimeError("production requires FACETTA_AUTH_MODE=supabase")


def _error(status: int, code: str, detail: str) -> HTTPException:
    return HTTPException(status_code=status, detail={
        "code": code,
        "error_category": "authentication" if status in {401, 503} else "authorization",
        "detail": detail,
    })


def _configured_principals() -> dict[str, str]:
    raw = env_value("FACETTA_AUTH_PRINCIPALS_JSON")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {
        token: subject for token, subject in parsed.items()
        if isinstance(token, str) and len(token) >= 16
        and isinstance(subject, str) and 0 < len(subject) <= 32
    }


def _supabase_issuer() -> str | None:
    raw = (env_value("FACETTA_SUPABASE_URL") or "").strip().rstrip("/")
    if not raw:
        return None
    parsed = urlparse(raw)
    environment = (env_value("FACETTA_ENV") or "production").strip().lower()
    allow_http = (
        (env_value("FACETTA_SUPABASE_ALLOW_HTTP") or "").lower() == "true"
        and environment in {"development", "test"}
    )
    if parsed.scheme != "https" and not (
        allow_http and parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}
    ):
        return None
    if (
        not parsed.netloc
        or parsed.path not in {"", "/"}
        or parsed.params or parsed.query or parsed.fragment
        or parsed.username is not None or parsed.password is not None
    ):
        return None
    return f"{raw}/auth/v1"


@lru_cache(maxsize=4)
def _jwks_client(issuer: str) -> PyJWKClient:
    # Supabase's edge caches JWKS for ten minutes. Do not extend that trust
    # window in-process or rotations/revocations take longer to reach this API.
    return PyJWKClient(
        f"{issuer}/.well-known/jwks.json",
        cache_keys=False,
        lifespan=600,
        timeout=5,
    )


def _supabase_signing_key(token: str, issuer: str):
    return _jwks_client(issuer).get_signing_key_from_jwt(token).key


def _authenticate_supabase(token: str) -> AuthenticatedPrincipal:
    issuer = _supabase_issuer()
    if issuer is None:
        raise _error(503, "authentication_configuration_error", "authentication is unavailable")
    audience = (env_value("FACETTA_SUPABASE_AUDIENCE") or "authenticated").strip()
    if audience != "authenticated":
        raise _error(503, "authentication_configuration_error", "authentication is unavailable")
    try:
        signing_key = _supabase_signing_key(token, issuer)
    except PyJWKClientConnectionError:
        raise _error(503, "authentication_verifier_unavailable", "authentication is temporarily unavailable")
    except (PyJWKSetError, json.JSONDecodeError):
        raise _error(503, "authentication_verifier_unavailable", "authentication is temporarily unavailable")
    except PyJWKClientError as exc:
        if "Unable to find a signing key that matches" in str(exc):
            raise _error(401, "invalid_authentication_token", "the bearer session token is invalid")
        raise _error(503, "authentication_verifier_unavailable", "authentication is temporarily unavailable")
    except (PyJWTError, OSError, ValueError):
        raise _error(401, "invalid_authentication_token", "the bearer session token is invalid")
    try:
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=["ES256", "RS256"],
            audience=audience,
            issuer=issuer,
            options={
                "require": [
                    "aud", "exp", "iat", "iss", "role", "sub",
                    "session_id", "is_anonymous",
                ],
            },
        )
    except (PyJWTError, OSError, ValueError):
        raise _error(401, "invalid_authentication_token", "the bearer session token is invalid")
    subject = claims.get("sub")
    role = claims.get("role")
    session_id = claims.get("session_id")
    if (
        not isinstance(subject, str) or not subject
        or role != "authenticated"
        or not isinstance(session_id, str) or not session_id
        or claims.get("is_anonymous") is not False
    ):
        raise _error(401, "invalid_authentication_token", "the bearer session token is invalid")
    try:
        canonical_subject = UUID(subject).hex
        UUID(session_id)
    except (ValueError, AttributeError):
        raise _error(401, "invalid_authentication_token", "the bearer session token is invalid")
    return AuthenticatedPrincipal(subject=canonical_subject)


def _authenticate(request: Request) -> AuthenticatedPrincipal:
    mode = (env_value("FACETTA_AUTH_MODE") or "required").strip().lower()
    if mode not in {"required", "supabase", "opaque", "local", "test"}:
        raise _error(503, "authentication_configuration_error", "authentication is unavailable")
    header = request.headers.get("authorization")
    if mode in {"local", "test"} and not header:
        return AuthenticatedPrincipal(subject=None, local_unbound=True)
    if not header or not header.startswith("Bearer "):
        raise _error(401, "authentication_required", "a bearer session token is required")
    supplied = header.removeprefix("Bearer ").strip()
    supabase_configured = bool((env_value("FACETTA_SUPABASE_URL") or "").strip())
    if mode == "supabase" or (mode == "required" and supabase_configured):
        return _authenticate_supabase(supplied)
    for token, subject in _configured_principals().items():
        if hmac.compare_digest(supplied, token):
            return AuthenticatedPrincipal(subject=subject)
    raise _error(401, "invalid_authentication_token", "the bearer session token is invalid")


def principal_actor(
    principal: AuthenticatedPrincipal,
    supplied_actor: str,
) -> str:
    """Return the canonical actor, rejecting request-label impersonation."""
    if principal.local_unbound:
        return supplied_actor
    if supplied_actor != principal.subject:
        raise _error(
            403,
            "principal_actor_mismatch",
            "owner and created_by audit fields must match the authenticated principal",
        )
    assert principal.subject is not None
    return principal.subject


async def require_principal_boundary(
    request: Request,
    db: Session = Depends(get_db),
) -> AuthenticatedPrincipal:
    """Authenticate and reject actor/project spoofing before route execution."""
    principal = _authenticate(request)
    if principal.local_unbound:
        return principal
    assert principal.subject is not None
    project_id = request.path_params.get("project_id") or request.path_params.get("root_id")
    project_id = project_id or request.path_params.get("project_root_id")
    if project_id:
        project = db.get(Project, project_id)
        if project is not None and project.owner != principal.subject:
            raise _error(
                403,
                "project_access_denied",
                "the authenticated principal does not own this project",
            )
    return principal


async def require_asset_project_boundary(
    request: Request,
    db: Session = Depends(get_db),
    principal: AuthenticatedPrincipal = Depends(require_principal_boundary),
) -> None:
    """Authorize an asset path through its canonical project root owner."""
    asset_id = request.path_params.get("asset_id")
    if not asset_id or principal.local_unbound:
        return
    asset = db.get(ImageAsset, asset_id)
    if asset is None:
        return
    project = db.get(Project, asset.root_id)
    owner = project.owner if project is not None else asset.created_by
    if not owner or owner != principal.subject:
        raise _error(403, "asset_access_denied", "the principal does not own this asset")


async def require_image_run_boundary(
    request: Request,
    db: Session = Depends(get_db),
    principal: AuthenticatedPrincipal = Depends(require_principal_boundary),
) -> None:
    """Authorize trusted run evidence through project owner or run creator."""
    run_id = request.path_params.get("run_id")
    if not run_id or principal.local_unbound:
        return
    run = db.get(ImageRun, run_id)
    if run is None:
        return
    project = db.get(Project, run.project_root_id) if run.project_root_id else None
    owner = project.owner if project is not None else run.created_by
    if owner != principal.subject:
        raise _error(
            403,
            "image_run_access_denied",
            "the principal does not own this image-run evidence",
        )

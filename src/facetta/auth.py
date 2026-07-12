"""First-party authenticated principal boundary for Studio beta routes."""

from __future__ import annotations

import hmac
import json
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from facetta.config import env_value
from facetta.db import ImageAsset, ImageRun, Project, get_db


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    subject: str | None
    local_unbound: bool = False


def _error(status: int, code: str, detail: str) -> HTTPException:
    return HTTPException(status_code=status, detail={
        "code": code,
        "error_category": "authentication" if status == 401 else "authorization",
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


def _authenticate(request: Request) -> AuthenticatedPrincipal:
    mode = (env_value("FACETTA_AUTH_MODE") or "required").strip().lower()
    header = request.headers.get("authorization")
    if mode in {"local", "test"} and not header:
        return AuthenticatedPrincipal(subject=None, local_unbound=True)
    if not header or not header.startswith("Bearer "):
        raise _error(401, "authentication_required", "a bearer session token is required")
    supplied = header.removeprefix("Bearer ").strip()
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

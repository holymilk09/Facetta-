"""Server-owned principal capabilities for optional paid Studio destinations.

Facetta does not yet persist organizations or workspaces.  Factory access is
therefore scoped to the authenticated principal, never inferred from client
configuration or project readiness.  The allowlist is deliberately fail-closed
until a durable workspace membership/billing model replaces this seam.
"""

from __future__ import annotations

import json

from fastapi import HTTPException

from facetta.auth import AuthenticatedPrincipal
from facetta.config import env_value


def _factory_principals() -> frozenset[str]:
    raw = env_value("FACETTA_FACTORY_ENTITLED_PRINCIPALS_JSON")
    if not raw:
        return frozenset()
    try:
        values = json.loads(raw)
    except json.JSONDecodeError:
        return frozenset()
    if not isinstance(values, list):
        return frozenset()
    return frozenset(
        value for value in values
        if isinstance(value, str) and 0 < len(value) <= 128
    )


def has_factory_entitlement(principal: AuthenticatedPrincipal) -> bool:
    """Return an exact, server-configured principal capability.

    Local/unbound requests have no trustworthy identity and remain disabled.
    Invalid or missing configuration also disables the capability.
    """
    local_test_enabled = (
        principal.local_unbound
        and (env_value("FACETTA_ENV") or "production").strip().lower() == "test"
        and (env_value("FACETTA_FACTORY_ALLOW_LOCAL_TEST") or "").strip().lower()
        == "true"
    )
    return local_test_enabled or (
        not principal.local_unbound
        and principal.subject is not None
        and principal.subject in _factory_principals()
    )


def require_factory_entitlement(principal: AuthenticatedPrincipal) -> None:
    if not has_factory_entitlement(principal):
        raise HTTPException(status_code=403, detail={
            "code": "factory_entitlement_required",
            "error_category": "authorization",
            "detail": "Factory review is not enabled for this account.",
        })

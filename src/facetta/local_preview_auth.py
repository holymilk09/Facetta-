"""Ephemeral localhost-only authentication for an explicitly opted-in preview.

This module is deliberately separate from Supabase authentication.  It gives a
developer who is running both the API and Expo on one machine a short-lived
Bearer session without introducing a reusable password, checked-in token, or
persistent credential store.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import ipaddress
import re
import secrets
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import Request
import jwt
from jwt import PyJWTError

from facetta.config import env_value


LOCAL_PREVIEW_SUBJECT = "localpreview00000000000000000000"
# Real image-provider QA can span several generation, review, and acceptance
# steps. Keep the credential bounded, but long enough that an interactive local
# verification run does not expire between generation and persistence.
LOCAL_PREVIEW_SESSION_SECONDS = 2 * 60 * 60
_LOCAL_PREVIEW_AUDIENCE = "facetta-local-preview"
_LOCAL_PREVIEW_ISSUER = "facetta-local-preview-process"
_LOCAL_PREVIEW_SCOPE = "studio:preview"
_LOCAL_PREVIEW_SIGNING_KEY = secrets.token_bytes(32)


def local_preview_auth_enabled() -> bool:
    """Return true only for an exact, non-production operator opt-in."""
    environment = (env_value("FACETTA_ENV") or "production").strip().lower()
    enabled = (env_value("FACETTA_LOCAL_PREVIEW_AUTH") or "").strip().lower()
    return environment in {"development", "test"} and enabled == "true"


def _is_loopback_hostname(hostname: str | None) -> bool:
    if hostname is None:
        return False
    candidate = hostname.strip().lower().strip("[]")
    if candidate == "localhost":
        return True
    # A scoped IPv6 loopback may include a zone identifier.  IPv4-mapped IPv6
    # addresses are checked through their mapped address rather than treated as
    # an arbitrary IPv6 peer.
    candidate = candidate.split("%", 1)[0]
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        return address.ipv4_mapped.is_loopback
    return address.is_loopback


def _loopback_origin_allowed(origin: str) -> bool:
    try:
        parsed = urlparse(origin)
        # Browser Origin values contain only scheme and authority.  Rejecting
        # every other component also rejects `null` and crafted credential URLs.
        return (
            parsed.scheme in {"http", "https"}
            and parsed.username is None
            and parsed.password is None
            and parsed.path in {"", "/"}
            and not parsed.params
            and not parsed.query
            and not parsed.fragment
            and _is_loopback_hostname(parsed.hostname)
        )
    except (TypeError, ValueError):
        return False


def local_preview_request_allowed(request: Request) -> bool:
    """Authorize from the socket peer and browser Origin, never proxy headers."""
    if not local_preview_auth_enabled() or request.client is None:
        return False
    if not _is_loopback_hostname(request.client.host):
        return False
    if not _is_loopback_hostname(request.url.hostname):
        return False
    origin = request.headers.get("origin")
    return origin is None or _loopback_origin_allowed(origin)


def issue_local_preview_credential() -> tuple[str, datetime]:
    """Issue one process-local session; the signing key is never persisted."""
    issued_at = datetime.now(timezone.utc).replace(microsecond=0)
    expires_at = issued_at + timedelta(seconds=LOCAL_PREVIEW_SESSION_SECONDS)
    token = jwt.encode(
        {
            "iss": _LOCAL_PREVIEW_ISSUER,
            "aud": _LOCAL_PREVIEW_AUDIENCE,
            "sub": LOCAL_PREVIEW_SUBJECT,
            "scope": _LOCAL_PREVIEW_SCOPE,
            "iat": int(issued_at.timestamp()),
            "nbf": int(issued_at.timestamp()),
            "exp": int(expires_at.timestamp()),
            "jti": uuid4().hex,
        },
        _LOCAL_PREVIEW_SIGNING_KEY,
        algorithm="HS256",
    )
    return token, expires_at


def authenticate_local_preview_token(request: Request, token: str) -> str | None:
    """Verify an ephemeral preview token without weakening other auth modes."""
    if not local_preview_request_allowed(request):
        return None
    try:
        claims = jwt.decode(
            token,
            _LOCAL_PREVIEW_SIGNING_KEY,
            algorithms=["HS256"],
            audience=_LOCAL_PREVIEW_AUDIENCE,
            issuer=_LOCAL_PREVIEW_ISSUER,
            options={
                "require": [
                    "iss", "aud", "sub", "scope", "iat", "nbf", "exp", "jti",
                ],
            },
            leeway=5,
        )
    except (PyJWTError, OSError, TypeError, ValueError):
        return None
    if (
        claims.get("sub") != LOCAL_PREVIEW_SUBJECT
        or claims.get("scope") != _LOCAL_PREVIEW_SCOPE
        or not isinstance(claims.get("jti"), str)
        or re.fullmatch(r"[a-f0-9]{32}", claims["jti"]) is None
    ):
        return None
    return LOCAL_PREVIEW_SUBJECT

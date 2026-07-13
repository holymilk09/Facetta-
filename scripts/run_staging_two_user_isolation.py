#!/usr/bin/env python3
"""Read-only two-principal isolation probe for the deployed Studio API.

The script never prints credentials or response bodies and performs no
generation or persistence calls. It requires two already-seeded principals,
projects, and image assets so ownership can be checked in both directions.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from facetta.external_beta_release import required_staging_checks  # noqa: E402


@dataclass(frozen=True)
class HttpResult:
    status: int
    content_type: str = ""
    json_body: object | None = None


Transport = Callable[[str, str, str], HttpResult]


@dataclass(frozen=True)
class StagingIdentity:
    label: str
    token: str
    actor: str
    project_id: str
    family_id: str
    asset_id: str


@dataclass(frozen=True)
class StagingConfig:
    base_url: str
    deployment_revision: str
    first: StagingIdentity
    second: StagingIdentity


class MissingConfiguration(ValueError):
    def __init__(self, missing: list[str]):
        super().__init__("missing staging configuration")
        self.missing = missing


def _required(name: str, missing: list[str]) -> str:
    value = (os.environ.get(name) or "").strip()
    if not value:
        missing.append(name)
    return value


def _jwt_actor(token: str) -> str:
    """Read the public JWT subject only to form the expected tenant label."""

    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        return UUID(str(claims["sub"])).hex
    except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("staging token is not a Supabase UUID-subject JWT") from exc


def load_config() -> StagingConfig:
    missing: list[str] = []
    base_url = _required("FACETTA_STAGING_BASE_URL", missing).rstrip("/")
    deployment_revision = _required(
        "FACETTA_STAGING_DEPLOYMENT_REVISION", missing,
    )
    identity_values: dict[str, dict[str, str]] = {}
    for label in ("A", "B"):
        prefix = f"FACETTA_STAGING_USER_{label}"
        identity_values[label] = {
            "token": _required(f"{prefix}_ACCESS_TOKEN", missing),
            "project_id": _required(f"{prefix}_PROJECT_ID", missing),
            "family_id": _required(f"{prefix}_FAMILY_ID", missing),
            "asset_id": _required(f"{prefix}_ASSET_ID", missing),
        }
    if missing:
        raise MissingConfiguration(sorted(missing))
    parsed = urlparse(base_url)
    if (
        parsed.scheme != "https" or not parsed.netloc
        or parsed.path or parsed.query or parsed.fragment
        or parsed.username is not None or parsed.password is not None
    ):
        raise ValueError("FACETTA_STAGING_BASE_URL must be an exact HTTPS origin")
    if re.fullmatch(r"[A-Za-z0-9._-]{7,128}", deployment_revision) is None:
        raise ValueError("staging deployment revision is not a safe release identifier")

    def identity(label: str) -> StagingIdentity:
        values = identity_values[label]
        token = values["token"]
        identifier = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
        for field in ("project_id", "family_id", "asset_id"):
            if identifier.fullmatch(values[field]) is None:
                raise ValueError(f"staging {field} is not a safe identifier")
        return StagingIdentity(
            label=label,
            token=token,
            actor=_jwt_actor(token),
            project_id=values["project_id"],
            family_id=values["family_id"],
            asset_id=values["asset_id"],
        )

    first = identity("A")
    second = identity("B")
    if first.token == second.token or first.actor == second.actor:
        raise ValueError("staging identities must be two distinct principals")
    if (
        first.project_id == second.project_id
        or first.family_id == second.family_id
        or first.asset_id == second.asset_id
    ):
        raise ValueError("staging identities must reference distinct seeded records")
    return StagingConfig(
        base_url=base_url,
        deployment_revision=deployment_revision,
        first=first,
        second=second,
    )


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


_OPENER = build_opener(_RejectRedirects)


def http_transport(method: str, url: str, token: str) -> HttpResult:
    request = Request(
        url,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, image/*",
        },
    )
    try:
        with _OPENER.open(request, timeout=15) as response:
            content_type = response.headers.get_content_type()
            content_length = response.headers.get("Content-Length")
            if (
                content_type == "application/json"
                and content_length is not None
                and int(content_length) > 2_000_000
            ):
                raise RuntimeError("staging response exceeded the safe JSON limit")
            raw = response.read(2_000_001) if content_type == "application/json" else b""
            if len(raw) > 2_000_000:
                raise RuntimeError("staging response exceeded the safe JSON limit")
            body = (
                json.loads(raw) if content_type == "application/json" and raw
                else None
            )
            return HttpResult(response.status, content_type, body)
    except HTTPError as exc:
        return HttpResult(exc.code, exc.headers.get_content_type())
    except (URLError, TimeoutError) as exc:
        raise RuntimeError("staging API is unreachable") from exc


def run_probe(config: StagingConfig, transport: Transport = http_transport) -> dict:
    checks: list[dict] = []

    def request(identity: StagingIdentity, path: str) -> HttpResult:
        return transport("GET", f"{config.base_url}{path}", identity.token)

    def record(name: str, expected: object, observed: object) -> None:
        checks.append({
            "name": name,
            "expected": expected,
            "observed": observed,
            "passed": observed == expected,
        })

    for own, other in (
        (config.first, config.second),
        (config.second, config.first),
    ):
        own_project = request(own, f"/projects/{quote(own.project_id, safe='')}")
        record(f"user_{own.label}_reads_own_project", 200, own_project.status)
        owner = (
            own_project.json_body.get("owner")
            if isinstance(own_project.json_body, dict) else None
        )
        record(f"user_{own.label}_project_owner_is_token_subject", True, owner == own.actor)

        no_auth_project = transport(
            "GET", f"{config.base_url}/projects/{quote(own.project_id, safe='')}", "",
        )
        record(f"user_{own.label}_project_requires_auth", 401, no_auth_project.status)

        cross_project = request(own, f"/projects/{quote(other.project_id, safe='')}")
        record(f"user_{own.label}_cannot_read_other_project", 403, cross_project.status)

        own_history = request(
            own, f"/studio/projects/{quote(own.project_id, safe='')}/history",
        )
        record(f"user_{own.label}_reads_own_history", 200, own_history.status)
        cross_history = request(
            own, f"/studio/projects/{quote(other.project_id, safe='')}/history",
        )
        record(f"user_{own.label}_cannot_read_other_history", 403, cross_history.status)

        own_image = request(own, f"/assets/{quote(own.asset_id, safe='')}/image")
        record(f"user_{own.label}_reads_own_asset", 200, own_image.status)
        record(
            f"user_{own.label}_own_asset_is_image",
            True,
            own_image.content_type.startswith("image/"),
        )

        cross_image = request(own, f"/assets/{quote(other.asset_id, safe='')}/image")
        record(f"user_{own.label}_cannot_read_other_asset", 403, cross_image.status)

        no_auth_image = transport(
            "GET", f"{config.base_url}/assets/{quote(own.asset_id, safe='')}/image", "",
        )
        record(f"user_{own.label}_asset_requires_auth", 401, no_auth_image.status)

        own_families = request(
            own, "/studio/families?" + urlencode({"owner": own.actor}),
        )
        record(f"user_{own.label}_lists_own_families", 200, own_families.status)
        families = (
            own_families.json_body.get("families")
            if isinstance(own_families.json_body, dict) else None
        )
        family_ids = {
            str(family.get("family_id"))
            for family in families
            if isinstance(families, list) and isinstance(family, dict)
        } if isinstance(families, list) else set()
        record(
            f"user_{own.label}_family_results_are_tenant_scoped",
            True,
            own.family_id in family_ids and other.family_id not in family_ids,
        )

        spoofed_families = request(
            own, "/studio/families?" + urlencode({"owner": other.actor}),
        )
        record(f"user_{own.label}_cannot_spoof_family_owner", 403, spoofed_families.status)

        own_family = request(
            own, f"/studio/families/{quote(own.family_id, safe='')}",
        )
        record(f"user_{own.label}_reads_own_family", 200, own_family.status)
        cross_family = request(
            own, f"/studio/families/{quote(other.family_id, safe='')}",
        )
        record(f"user_{own.label}_cannot_enumerate_other_family", 404, cross_family.status)

    no_auth_families = transport(
        "GET", f"{config.base_url}/studio/families", "",
    )
    record("studio_families_require_auth", 401, no_auth_families.status)

    for path in (
        "/designs", "/library", "/library/collections", "/users", "/stones",
        "/share/e2e-hidden", f"/assets/{quote(config.first.asset_id, safe='')}",
        f"/assets/{quote(config.first.asset_id, safe='')}/history",
        f"/assets/{quote(config.first.asset_id, safe='')}/component-map",
        "/openapi.json", "/docs",
    ):
        hidden = transport(
            "OPTIONS", f"{config.base_url}{path}", config.first.token,
        )
        hidden_name = (
            "asset_metadata" if path == f"/assets/{config.first.asset_id}"
            else "asset_history" if path.endswith("/history") and path.startswith("/assets/")
            else "asset_component_map" if path.endswith("/component-map")
            else path[1:].replace("/", "_")
        )
        record(f"production_hides_{hidden_name}", 404, hidden.status)

    passed = all(check["passed"] for check in checks)
    expected_checks = required_staging_checks()
    if {row["name"]: row["expected"] for row in checks} != expected_checks:
        raise RuntimeError("staging probe implementation differs from release contract")
    fixture_binding = {
        identity.label: {
            "actor": identity.actor,
            "project_id": identity.project_id,
            "family_id": identity.family_id,
            "asset_id": identity.asset_id,
        }
        for identity in (config.first, config.second)
    }
    fixture_set_sha256 = hashlib.sha256(json.dumps(
        fixture_binding,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")).hexdigest()
    return {
        "schema_version": "facetta-staging-isolation.v2",
        "run_kind": "read_only_two_principal_staging_probe",
        "target": {
            "origin_sha256": hashlib.sha256(
                config.base_url.encode("utf-8")
            ).hexdigest(),
            "deployment_revision": config.deployment_revision,
            "fixture_set_sha256": fixture_set_sha256,
            "probed_at": datetime.now(timezone.utc).isoformat(),
            "transport": "live_https",
        },
        "checks": checks,
        "passed": passed,
        "secrets_logged": False,
        "provider_calls": 0,
        "mutations": 0,
    }


def main() -> int:
    try:
        result = run_probe(load_config())
    except MissingConfiguration as exc:
        print(json.dumps({
            "status": "skipped",
            "reason": "missing_credentials_or_fixtures",
            "missing": exc.missing,
            "secrets_logged": False,
        }, indent=2))
        return 77
    except (ValueError, RuntimeError):
        print(json.dumps({
            "passed": False,
            "configuration_error": "invalid_or_unreachable_staging_configuration",
            "secrets_logged": False,
        }, indent=2))
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())

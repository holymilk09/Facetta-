#!/usr/bin/env python3
"""Read-only two-principal isolation probe for the deployed Studio API.

The script never prints credentials or response bodies and performs no
generation or persistence calls. It requires two already-seeded principals,
projects, image assets, jobs, fresh review candidates, and an already-discarded
normalized decision candidate so ownership can be checked in both directions
without generation or a new canonical mutation. Replaying ``discard`` against
the terminal fixture is deliberately idempotent.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
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

from facetta.external_beta_release import (  # noqa: E402
    STAGING_DISALLOWED_LEGACY_OPERATIONS,
    STAGING_RESULT_SCHEMA,
    required_staging_checks,
)


@dataclass(frozen=True)
class HttpResult:
    status: int
    content_type: str = ""
    json_body: object | None = None
    allowed_methods: frozenset[str] = frozenset()


Transport = Callable[[str, str, str], HttpResult]
DecisionTransport = Callable[[str, str, str, dict[str, object]], HttpResult]


@dataclass(frozen=True)
class CandidateFixture:
    kind: str
    run_id: str
    candidate_id: str
    source_asset_id: str
    studio_job_id: str


@dataclass(frozen=True)
class NormalizedDecisionFixture:
    kind: str
    image_run_id: str
    candidate_id: str
    source_asset_id: str
    studio_job_id: str
    expected_design_version: int | None


@dataclass(frozen=True)
class StagingIdentity:
    label: str
    token: str
    actor: str
    project_id: str
    family_id: str
    asset_id: str
    job_id: str
    candidates: tuple[CandidateFixture, ...]
    normalized_decision: NormalizedDecisionFixture

    def candidate(self, kind: str) -> CandidateFixture:
        return next(candidate for candidate in self.candidates if candidate.kind == kind)


@dataclass(frozen=True)
class StagingConfig:
    base_url: str
    deployment_revision: str
    staging_run_id: str
    external_release_run_id: str
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
    staging_run_id = _required("FACETTA_STAGING_RUN_ID", missing)
    external_release_run_id = _required(
        "FACETTA_EXTERNAL_RELEASE_RUN_ID", missing,
    )
    identity_values: dict[str, dict[str, str]] = {}
    for label in ("A", "B"):
        prefix = f"FACETTA_STAGING_USER_{label}"
        identity_values[label] = {
            "token": _required(f"{prefix}_ACCESS_TOKEN", missing),
            "project_id": _required(f"{prefix}_PROJECT_ID", missing),
            "family_id": _required(f"{prefix}_FAMILY_ID", missing),
            "asset_id": _required(f"{prefix}_ASSET_ID", missing),
            "job_id": _required(f"{prefix}_JOB_ID", missing),
            "candidate_fixtures": _required(
                f"{prefix}_CANDIDATE_FIXTURES_JSON", missing,
            ),
            "normalized_decision_fixture": _required(
                f"{prefix}_NORMALIZED_DECISION_FIXTURE_JSON", missing,
            ),
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
    run_identifier = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{6,127}$")
    if run_identifier.fullmatch(staging_run_id) is None:
        raise ValueError("FACETTA_STAGING_RUN_ID is not a safe release identifier")
    if run_identifier.fullmatch(external_release_run_id) is None:
        raise ValueError(
            "FACETTA_EXTERNAL_RELEASE_RUN_ID is not a safe release identifier"
        )

    def identity(label: str) -> StagingIdentity:
        values = identity_values[label]
        token = values["token"]
        identifier = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
        for field in ("project_id", "family_id", "asset_id", "job_id"):
            if identifier.fullmatch(values[field]) is None:
                raise ValueError(f"staging {field} is not a safe identifier")
        try:
            raw_candidates = json.loads(values["candidate_fixtures"])
        except json.JSONDecodeError as exc:
            raise ValueError("staging candidate fixtures are not valid JSON") from exc
        kinds = {"catalog", "visual", "markup", "view", "presentation"}
        if not isinstance(raw_candidates, dict) or set(raw_candidates) != kinds:
            raise ValueError(
                "staging candidate fixtures must exactly cover catalog, visual, "
                "markup, view, and presentation"
            )
        candidates: list[CandidateFixture] = []
        for kind in sorted(kinds):
            raw = raw_candidates[kind]
            if not isinstance(raw, dict) or set(raw) != {
                "run_id", "candidate_id", "source_asset_id", "studio_job_id",
            }:
                raise ValueError(f"staging {kind} candidate fixture is invalid")
            run_id = raw.get("run_id")
            candidate_id = raw.get("candidate_id")
            source_asset_id = raw.get("source_asset_id")
            studio_job_id = raw.get("studio_job_id")
            if (
                not isinstance(run_id, str)
                or not isinstance(candidate_id, str)
                or not isinstance(source_asset_id, str)
                or not isinstance(studio_job_id, str)
                or identifier.fullmatch(run_id) is None
                or identifier.fullmatch(candidate_id) is None
                or identifier.fullmatch(source_asset_id) is None
                or identifier.fullmatch(studio_job_id) is None
                or source_asset_id != values["asset_id"]
            ):
                raise ValueError(f"staging {kind} candidate identifiers are unsafe")
            candidates.append(CandidateFixture(
                kind,
                run_id,
                candidate_id,
                source_asset_id,
                studio_job_id,
            ))
        try:
            raw_decision = json.loads(values["normalized_decision_fixture"])
        except json.JSONDecodeError as exc:
            raise ValueError(
                "staging normalized decision fixture is not valid JSON"
            ) from exc
        if not isinstance(raw_decision, dict) or set(raw_decision) != {
            "kind", "image_run_id", "candidate_id", "source_asset_id",
            "studio_job_id", "expected_design_version",
        }:
            raise ValueError("staging normalized decision fixture is invalid")
        decision_kind = raw_decision.get("kind")
        image_run_id = raw_decision.get("image_run_id")
        candidate_id = raw_decision.get("candidate_id")
        source_asset_id = raw_decision.get("source_asset_id")
        studio_job_id = raw_decision.get("studio_job_id")
        expected_design_version = raw_decision.get("expected_design_version")
        if (
            decision_kind not in {"visual", "catalog_revision", "markup"}
            or not isinstance(image_run_id, str)
            or not isinstance(candidate_id, str)
            or not isinstance(source_asset_id, str)
            or not isinstance(studio_job_id, str)
            or identifier.fullmatch(image_run_id) is None
            or identifier.fullmatch(candidate_id) is None
            or identifier.fullmatch(source_asset_id) is None
            or identifier.fullmatch(studio_job_id) is None
            or source_asset_id != values["asset_id"]
            or (
                expected_design_version is not None
                and (
                    not isinstance(expected_design_version, int)
                    or isinstance(expected_design_version, bool)
                    or expected_design_version < 1
                )
            )
            or (
                decision_kind == "visual"
                and expected_design_version is not None
            )
            or (
                decision_kind != "visual"
                and expected_design_version is None
            )
        ):
            raise ValueError(
                "staging normalized decision fixture identifiers are unsafe"
            )
        decision_fixture = NormalizedDecisionFixture(
            decision_kind,
            image_run_id,
            candidate_id,
            source_asset_id,
            studio_job_id,
            expected_design_version,
        )
        if candidate_id in {candidate.candidate_id for candidate in candidates}:
            raise ValueError(
                "staging normalized decision fixture must be a separate record"
            )
        return StagingIdentity(
            label=label,
            token=token,
            actor=_jwt_actor(token),
            project_id=values["project_id"],
            family_id=values["family_id"],
            asset_id=values["asset_id"],
            job_id=values["job_id"],
            candidates=tuple(candidates),
            normalized_decision=decision_fixture,
        )

    first = identity("A")
    second = identity("B")
    if first.token == second.token or first.actor == second.actor:
        raise ValueError("staging identities must be two distinct principals")
    if (
        first.project_id == second.project_id
        or first.family_id == second.family_id
        or first.asset_id == second.asset_id
        or first.job_id == second.job_id
    ):
        raise ValueError("staging identities must reference distinct seeded records")
    first_candidates = {
        (candidate.run_id, candidate.candidate_id) for candidate in first.candidates
    }
    second_candidates = {
        (candidate.run_id, candidate.candidate_id) for candidate in second.candidates
    }
    if len(first_candidates) != 5 or len(second_candidates) != 5 or (
        first_candidates & second_candidates
    ):
        raise ValueError("staging candidate fixtures must be distinct seeded records")
    first_candidate_jobs = {
        candidate.studio_job_id for candidate in first.candidates
    }
    second_candidate_jobs = {
        candidate.studio_job_id for candidate in second.candidates
    }
    first_candidate_jobs.add(first.normalized_decision.studio_job_id)
    second_candidate_jobs.add(second.normalized_decision.studio_job_id)
    if (
        len(first_candidate_jobs) != 6
        or len(second_candidate_jobs) != 6
        or ({first.job_id} | first_candidate_jobs)
        & ({second.job_id} | second_candidate_jobs)
        or first.normalized_decision.candidate_id
        == second.normalized_decision.candidate_id
    ):
        raise ValueError("staging candidate fixtures must bind distinct Studio jobs")
    return StagingConfig(
        base_url=base_url,
        deployment_revision=deployment_revision,
        staging_run_id=staging_run_id,
        external_release_run_id=external_release_run_id,
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
            allowed_methods = frozenset(
                item.strip().upper()
                for item in (response.headers.get("Allow") or "").split(",")
                if item.strip()
            )
            return HttpResult(
                response.status, content_type, body, allowed_methods,
            )
    except HTTPError as exc:
        content_type = exc.headers.get_content_type() if exc.headers else ""
        allowed_methods = frozenset(
            item.strip().upper()
            for item in (
                (exc.headers.get("Allow") if exc.headers else None) or ""
            ).split(",")
            if item.strip()
        )
        return HttpResult(
            exc.code, content_type, allowed_methods=allowed_methods,
        )
    except (URLError, TimeoutError) as exc:
        raise RuntimeError("staging API is unreachable") from exc


def http_decision_transport(
    method: str,
    url: str,
    token: str,
    json_body: dict[str, object],
) -> HttpResult:
    """Send one bounded JSON decision without exposing tokens or payloads."""

    if method != "POST":
        raise RuntimeError("decision transport only permits POST")
    encoded = json.dumps(
        json_body, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")
    if len(encoded) > 8_192:
        raise RuntimeError("staging decision request exceeded the safe JSON limit")
    request = Request(
        url,
        method="POST",
        data=encoded,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
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
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise RuntimeError("staging response exceeded the safe JSON limit")
            body = (
                json.loads(raw)
                if content_type == "application/json" and raw else None
            )
            return HttpResult(response.status, content_type, body)
    except HTTPError as exc:
        content_type = exc.headers.get_content_type() if exc.headers else ""
        return HttpResult(exc.code, content_type)
    except (URLError, TimeoutError) as exc:
        raise RuntimeError("staging API is unreachable") from exc


def run_probe(
    config: StagingConfig,
    transport: Transport = http_transport,
    decision_transport: DecisionTransport | None = None,
) -> dict:
    checks: list[dict] = []
    if decision_transport is None:
        if transport is not http_transport:
            raise ValueError(
                "a custom read transport requires an explicit decision transport"
            )
        decision_transport = http_decision_transport

    def request(identity: StagingIdentity, path: str) -> HttpResult:
        return transport("GET", f"{config.base_url}{path}", identity.token)

    def decide(
        identity: StagingIdentity,
        candidate_id: str,
        payload: dict[str, object],
    ) -> HttpResult:
        assert decision_transport is not None
        return decision_transport(
            "POST",
            f"{config.base_url}/studio/preview-candidates/"
            f"{quote(candidate_id, safe='')}/decision",
            identity.token,
            payload,
        )

    def record(name: str, expected: object, observed: object) -> None:
        checks.append({
            "name": name,
            "expected": expected,
            "observed": observed,
            "passed": observed == expected,
        })

    def collection_rows(result: HttpResult, name: str) -> list[dict] | None:
        """Return a canonical JSON list or fail closed for malformed payloads."""

        body = result.json_body
        if (
            result.status != 200
            or result.content_type != "application/json"
            or not isinstance(body, dict)
            or set(body) != {name}
        ):
            return None
        rows = body.get(name)
        if not isinstance(rows, list) or not all(
            isinstance(row, dict) for row in rows
        ):
            return None
        return rows

    def aware_timestamp(value: object, *, future: bool = False) -> bool:
        if not isinstance(value, str):
            return False
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return False
        return not future or parsed > datetime.now(timezone.utc)

    def sha256_or_none(value: object) -> bool:
        return value is None or (
            isinstance(value, str)
            and re.fullmatch(r"[0-9a-f]{64}", value) is not None
        )

    def json_value_is_valid(value: object) -> bool:
        """Mirror the trusted client's finite JSON-value decoder."""

        if value is None or isinstance(value, (str, bool)):
            return True
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return math.isfinite(value)
        if isinstance(value, list):
            return all(json_value_is_valid(item) for item in value)
        if isinstance(value, dict):
            return all(
                isinstance(key, str) and json_value_is_valid(item)
                for key, item in value.items()
            )
        return False

    def preview_qa_matches_verdict(verdict: object, qa: object) -> bool:
        """Match the mobile decoder's explicit QA acceptance semantics."""

        if verdict is None:
            return qa is None
        if verdict not in {"pass", "warn"} or not isinstance(qa, dict):
            return False
        qa_verdict = qa.get("verdict") if "verdict" in qa else qa.get("status")
        accepted = qa.get("accepted")
        review_required = qa.get("review_required")
        return (
            qa_verdict == verdict
            and isinstance(accepted, bool)
            and isinstance(review_required, bool)
            and (
                (verdict == "pass" and accepted and not review_required)
                or (verdict == "warn" and not accepted and review_required)
            )
        )

    def catalog_changes_are_valid(value: object) -> bool:
        """Require the same non-empty, unique, labeled changes as mobile."""

        if not isinstance(value, list) or not value:
            return False
        missing = object()
        paths: list[str] = []
        for change in value:
            if not isinstance(change, dict):
                return False
            path = change.get("path", change.get("field"))
            before = (
                change["before"] if "before" in change
                else change.get("old", missing)
            )
            after = (
                change["after"] if "after" in change
                else change.get("new", missing)
            )
            label = change.get("label")
            if (
                not isinstance(path, str)
                or re.fullmatch(
                    r"[a-z][a-z0-9_]*(?:(?:\.[a-z][a-z0-9_]*)|"
                    r"(?:\[[0-9]+\]))+",
                    path,
                ) is None
                or not isinstance(label, str)
                or not label.strip()
                or before is missing
                or after is missing
                or not json_value_is_valid(before)
                or not json_value_is_valid(after)
            ):
                return False
            paths.append(path)
        return len(set(paths)) == len(paths)

    def catalog_next_spec_is_valid(value: object) -> bool:
        """Mirror the mobile catalog preview's canonical Spec envelope."""

        if (
            not isinstance(value, dict)
            or not value
            or not json_value_is_valid(value)
            or value.get("schema_version") != 1
            or isinstance(value.get("schema_version"), bool)
        ):
            return False

        def nonempty_text(item: object) -> bool:
            return isinstance(item, str) and len(item) > 0

        def positive_number(item: object) -> bool:
            return (
                isinstance(item, (int, float))
                and not isinstance(item, bool)
                and math.isfinite(item)
                and item > 0
            )

        version = value.get("version")
        created_at = value.get("created_at")
        rfc3339 = (
            isinstance(created_at, str)
            and re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
                r"(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})",
                created_at,
            ) is not None
        )
        if (
            not isinstance(version, (int, float))
            or isinstance(version, bool)
            or not math.isfinite(version)
            or int(version) != version
            or version < 1
            or not nonempty_text(value.get("design_id"))
            or not nonempty_text(value.get("created_by"))
            or not nonempty_text(created_at)
            or not rfc3339
            or not nonempty_text(value.get("jewelry_type"))
            or not nonempty_text(value.get("template"))
            or value.get("mode") not in ("basic", "pro")
        ):
            return False
        try:
            datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
        except ValueError:
            return False

        stone = value.get("stone")
        if not isinstance(stone, dict):
            return False
        dimensions = stone.get("dimensions_mm")
        color = stone.get("color")
        return (
            nonempty_text(stone.get("species"))
            and nonempty_text(stone.get("cut"))
            and positive_number(stone.get("carat"))
            and isinstance(dimensions, dict)
            and positive_number(dimensions.get("length"))
            and positive_number(dimensions.get("width"))
            and positive_number(dimensions.get("depth"))
            and isinstance(color, dict)
            and nonempty_text(color.get("trade"))
            and nonempty_text(color.get("gia"))
        )

    def studio_job_shape_is_valid(row: dict) -> bool:
        if set(row) != {
            "job_id", "owner", "action_id", "lane", "status", "progress",
            "active_design_id", "source_revision_id", "accepted_output_sha256",
            "error_code", "created_at", "updated_at", "billing",
        }:
            return False
        billing = row.get("billing")
        if not isinstance(billing, dict) or set(billing) != {
            "requested_outputs", "credits_per_output", "estimated_credits",
            "completed_outputs", "charged_outputs", "charged_credits", "policy",
        }:
            return False
        requested = billing.get("requested_outputs")
        rate = billing.get("credits_per_output")
        completed = billing.get("completed_outputs")
        charged = billing.get("charged_outputs")
        integers = (requested, rate, completed, charged)
        progress = row.get("progress")
        return (
            row.get("action_id")
            in {"create", "vary", "refine", "views", "present", "factory"}
            and row.get("lane")
            in {"instant", "fast_visual", "trusted_structural"}
            and row.get("status")
            in {"queued", "running", "reviewing", "succeeded", "failed", "canceled"}
            and isinstance(progress, (int, float))
            and not isinstance(progress, bool)
            and 0 <= progress <= 1
            and all(isinstance(value, int) and not isinstance(value, bool)
                    for value in integers)
            and 1 <= requested <= 4
            and rate >= 0
            and 0 <= completed <= requested
            and 0 <= charged <= completed
            and billing.get("estimated_credits") == requested * rate
            and billing.get("charged_credits") == charged * rate
            and isinstance(billing.get("policy"), str)
            and bool(billing.get("policy"))
            and sha256_or_none(row.get("accepted_output_sha256"))
            and (
                row.get("error_code") is None
                or isinstance(row.get("error_code"), str)
            )
            and aware_timestamp(row.get("created_at"))
            and aware_timestamp(row.get("updated_at"))
        )

    def own_jobs_are_tenant_scoped(
        result: HttpResult,
        own: StagingIdentity,
        other: StagingIdentity,
    ) -> bool:
        rows = collection_rows(result, "jobs")
        if rows is None:
            return False
        seen: set[str] = set()
        expected_sources = {own.job_id: own.asset_id}
        expected_sources.update({
            candidate.studio_job_id: candidate.source_asset_id
            for candidate in own.candidates
        })
        expected_sources[
            own.normalized_decision.studio_job_id
        ] = own.normalized_decision.source_asset_id
        expected_counts = {job_id: 0 for job_id in expected_sources}
        for row in rows:
            job_id = row.get("job_id")
            owner = row.get("owner")
            active_design_id = row.get("active_design_id")
            source_revision_id = row.get("source_revision_id")
            if (
                not studio_job_shape_is_valid(row)
                or not isinstance(job_id, str)
                or not job_id
                or not isinstance(owner, str)
                or not owner
                or (
                    active_design_id is not None
                    and not isinstance(active_design_id, str)
                )
                or (
                    source_revision_id is not None
                    and not isinstance(source_revision_id, str)
                )
                or job_id in seen
                or owner != own.actor
                or job_id == other.job_id
                or job_id in {
                    candidate.studio_job_id for candidate in other.candidates
                }
                or job_id == other.normalized_decision.studio_job_id
                or active_design_id == other.project_id
                or source_revision_id == other.asset_id
            ):
                return False
            seen.add(job_id)
            if job_id in expected_counts:
                expected_counts[job_id] += 1
                if (
                    active_design_id != own.project_id
                    or source_revision_id != expected_sources[job_id]
                ):
                    return False
        return all(count == 1 for count in expected_counts.values())

    def own_candidates_are_tenant_scoped(
        result: HttpResult,
        kind: str,
        own: StagingIdentity,
        other: StagingIdentity,
        own_job_ids: set[str],
    ) -> bool:
        rows = collection_rows(result, "candidates")
        if rows is None:
            return False
        own_fixture = own.candidate(kind)
        other_fixture = other.candidate(kind)
        project_field = {
            "markup": "project_root_id",
            "view": "project_id",
            "presentation": "project_id",
        }.get(kind)
        seen: set[tuple[str, str]] = set()
        own_fixture_count = 0
        expected_keys = {
            "catalog": {
                "candidate_id", "image_run_id", "source_asset_id",
                "component_path", "option_id", "requested_change", "verdict",
                "preview_url", "save_as_variation_url", "next_spec",
                "spec_change", "qa", "routing", "studio_job_id", "expires_at",
            },
            "visual": {
                "candidate_id", "image_run_id", "source_asset_id", "preview_url",
                "save_as_variation_url", "verdict", "requested_change", "scope",
                "qa", "expires_at", "studio_job_id",
            },
            "markup": {
                "candidate_id", "image_run_id", "project_root_id",
                "source_asset_id", "expected_active_asset_id", "design_version",
                "source_sha256", "output_sha256", "operation", "requested_change",
                "region_description", "qa", "routing", "status", "studio_job_id",
                "expires_at", "preview_url", "accept_url", "discard_url",
                "save_as_variation_url",
            },
            "view": {
                "candidate_id", "image_run_id", "studio_job_id", "project_id",
                "source_asset_id", "source_sha256", "design_version", "view", "qa",
                "status", "accepted_asset_id", "expires_at", "preview_url",
            },
            "presentation": {
                "candidate_id", "image_run_id", "project_id", "source_asset_id",
                "source_sha256", "design_version", "destination", "capability",
                "preset", "framing", "qa", "status", "studio_job_id",
                "accepted_asset_id", "expires_at", "preview_url",
            },
        }[kind]
        for row in rows:
            candidate_id = row.get("candidate_id")
            image_run_id = row.get("image_run_id")
            source_asset_id = row.get("source_asset_id")
            studio_job_id = row.get("studio_job_id")
            pair = (image_run_id, candidate_id)
            if (
                set(row) != expected_keys
                or not isinstance(candidate_id, str)
                or not candidate_id
                or not isinstance(image_run_id, str)
                or not image_run_id
                or not isinstance(source_asset_id, str)
                or not source_asset_id
                or not isinstance(studio_job_id, str)
                or not studio_job_id
                or studio_job_id not in own_job_ids
                or pair in seen
                or pair == (other_fixture.run_id, other_fixture.candidate_id)
                or source_asset_id != own.asset_id
                or studio_job_id == other.job_id
                or studio_job_id in {
                    candidate.studio_job_id for candidate in other.candidates
                }
            ):
                return False
            if project_field is not None:
                project_id = row.get(project_field)
                if not isinstance(project_id, str) or project_id != own.project_id:
                    return False
            if kind == "markup" and row.get("expected_active_asset_id") != own.asset_id:
                return False
            base = {
                "catalog": (
                    f"/image-runs/{image_run_id}/catalog-candidates/{candidate_id}"
                ),
                "visual": (
                    f"/studio/image-runs/{image_run_id}/visual-candidates/"
                    f"{candidate_id}"
                ),
                "markup": (
                    f"/studio/markup-candidates/{image_run_id}/{candidate_id}"
                ),
                "view": (
                    f"/studio/view-candidates/{image_run_id}/{candidate_id}"
                ),
                "presentation": (
                    f"/studio/image-runs/{image_run_id}/presentation-candidates/"
                    f"{candidate_id}"
                ),
            }[kind]
            expected_preview = (
                f"{base}/image?owner={own.actor}"
                if kind in {"view", "presentation"}
                else f"{base}/image"
            )
            if (
                row.get("preview_url") != expected_preview
                or not aware_timestamp(row.get("expires_at"), future=True)
                or not isinstance(row.get("qa"), dict)
            ):
                return False
            if kind == "catalog" and not (
                isinstance(row.get("component_path"), str)
                and isinstance(row.get("option_id"), str)
                and isinstance(row.get("requested_change"), str)
                and isinstance(row.get("verdict"), str)
                and row.get("save_as_variation_url") == f"{base}/save-as-variation"
                and isinstance(row.get("next_spec"), dict)
                and isinstance(row.get("spec_change"), list)
                and isinstance(row.get("routing"), dict)
            ):
                return False
            if kind == "visual" and not (
                isinstance(row.get("verdict"), str)
                and isinstance(row.get("requested_change"), str)
                and isinstance(row.get("scope"), str)
                and row.get("save_as_variation_url") == f"{base}/save-as-variation"
            ):
                return False
            if kind == "markup" and not (
                isinstance(row.get("design_version"), int)
                and row.get("design_version") >= 1
                and sha256_or_none(row.get("source_sha256"))
                and row.get("source_sha256") is not None
                and sha256_or_none(row.get("output_sha256"))
                and row.get("output_sha256") is not None
                and isinstance(row.get("operation"), str)
                and isinstance(row.get("requested_change"), str)
                and (
                    row.get("region_description") is None
                    or isinstance(row.get("region_description"), str)
                )
                and isinstance(row.get("routing"), dict)
                and row.get("status") == "reviewing"
                and row.get("accept_url") == f"{base}/accept"
                and row.get("discard_url") == f"{base}/discard"
                and row.get("save_as_variation_url") == f"{base}/save-as-variation"
            ):
                return False
            if kind == "view" and not (
                isinstance(row.get("design_version"), int)
                and row.get("design_version") >= 1
                and sha256_or_none(row.get("source_sha256"))
                and row.get("source_sha256") is not None
                and isinstance(row.get("view"), str)
                and row.get("status") == "reviewing"
                and row.get("accepted_asset_id") is None
            ):
                return False
            if kind == "presentation" and not (
                isinstance(row.get("design_version"), int)
                and row.get("design_version") >= 1
                and sha256_or_none(row.get("source_sha256"))
                and row.get("source_sha256") is not None
                and all(isinstance(row.get(field), str) for field in (
                    "destination", "capability", "preset", "framing",
                ))
                and row.get("status") == "reviewing"
                and row.get("accepted_asset_id") is None
            ):
                return False
            seen.add(pair)
            if pair == (own_fixture.run_id, own_fixture.candidate_id):
                own_fixture_count += 1
                if (
                    source_asset_id != own_fixture.source_asset_id
                    or studio_job_id != own_fixture.studio_job_id
                ):
                    return False
        return own_fixture_count == 1

    def normalized_kind(fixture_kind: str) -> str:
        return "catalog_revision" if fixture_kind == "catalog" else fixture_kind

    def normalized_candidate_shape_is_valid(
        row: dict,
        *,
        own: StagingIdentity,
        own_single_output_refine_job_ids: set[str],
        expected_status: str = "reviewing",
    ) -> bool:
        kind = row.get("kind")
        detail_keys = {
            "visual": {"scope"},
            "catalog_revision": {
                "component_path", "option_id", "spec_change", "next_spec",
            },
            "markup": {"operation", "region_description"},
        }
        if kind not in detail_keys:
            return False
        common_keys = {
            "candidate_id", "kind", "status", "image_run_id",
            "project_root_id", "source_asset_id", "expected_active_asset_id",
            "expected_design_version", "source_sha256", "output_sha256",
            "requested_change", "verdict", "qa", "studio_job_id",
            "terminal_asset_id", "created_at", "expires_at", "resolved_at",
            "available_decisions", "preview_url", "decision_url",
        }
        if set(row) != common_keys | detail_keys[kind]:
            return False
        candidate_id = row.get("candidate_id")
        image_run_id = row.get("image_run_id")
        studio_job_id = row.get("studio_job_id")
        expected_version = row.get("expected_design_version")
        if not (
            isinstance(candidate_id, str)
            and bool(candidate_id)
            and isinstance(image_run_id, str)
            and bool(image_run_id)
            and row.get("status") == expected_status
            and row.get("project_root_id") == own.project_id
            and row.get("source_asset_id") == own.asset_id
            and row.get("expected_active_asset_id") == own.asset_id
            and sha256_or_none(row.get("source_sha256"))
            and row.get("source_sha256") is not None
            and sha256_or_none(row.get("output_sha256"))
            and row.get("output_sha256") is not None
            and isinstance(row.get("requested_change"), str)
            and preview_qa_matches_verdict(row.get("verdict"), row.get("qa"))
            and isinstance(studio_job_id, str)
            and studio_job_id in own_single_output_refine_job_ids
            and aware_timestamp(row.get("created_at"))
            and aware_timestamp(row.get("expires_at"))
            and row.get("preview_url")
            == (
                f"/studio/preview-candidates/{candidate_id}/image?"
                + urlencode({"owner": own.actor})
            )
            and row.get("decision_url")
            == f"/studio/preview-candidates/{candidate_id}/decision"
        ):
            return False
        if expected_status == "reviewing":
            if not (
                row.get("terminal_asset_id") is None
                and row.get("resolved_at") is None
                and row.get("available_decisions")
                == ["apply", "save_as_variation", "discard"]
                and aware_timestamp(row.get("expires_at"), future=True)
            ):
                return False
        elif expected_status == "discarded":
            if not (
                row.get("terminal_asset_id") is None
                and aware_timestamp(row.get("resolved_at"))
                and row.get("available_decisions") == []
            ):
                return False
        else:  # pragma: no cover - helper contract
            return False
        if kind == "visual":
            return expected_version is None and row.get("scope") in {
                "appearance", "marked_region",
            }
        if not (
            isinstance(expected_version, int)
            and not isinstance(expected_version, bool)
            and expected_version >= 1
        ):
            return False
        if kind == "catalog_revision":
            return (
                row.get("component_path") in {
                    "chain.style", "stone.color", "stone.cut",
                    "metal.material", "metal.color", "setting.style",
                }
                and isinstance(row.get("option_id"), str)
                and bool(row.get("option_id"))
                and catalog_changes_are_valid(row.get("spec_change"))
                and catalog_next_spec_is_valid(row.get("next_spec"))
            )
        return (
            row.get("operation") in {"LOCAL_EDIT", "VISUAL_ONLY_EDIT"}
            and isinstance(row.get("region_description"), str)
            and bool(row.get("region_description"))
        )

    def own_normalized_candidates_are_tenant_scoped(
        result: HttpResult,
        own: StagingIdentity,
        other: StagingIdentity,
        own_single_output_refine_job_ids: set[str],
    ) -> bool:
        rows = collection_rows(result, "candidates")
        if rows is None:
            return False
        expected = {
            fixture.candidate_id: fixture
            for fixture in own.candidates
            if fixture.kind in {"catalog", "visual", "markup"}
        }
        other_ids = {
            fixture.candidate_id for fixture in other.candidates
            if fixture.kind in {"catalog", "visual", "markup"}
        }
        seen: set[str] = set()
        seen_job_ids: set[str] = set()
        counts = {candidate_id: 0 for candidate_id in expected}
        for row in rows:
            candidate_id = row.get("candidate_id")
            studio_job_id = row.get("studio_job_id")
            if (
                not normalized_candidate_shape_is_valid(
                    row,
                    own=own,
                    own_single_output_refine_job_ids=(
                        own_single_output_refine_job_ids
                    ),
                )
                or not isinstance(candidate_id, str)
                or candidate_id in seen
                or candidate_id in other_ids
                or studio_job_id in seen_job_ids
            ):
                return False
            seen.add(candidate_id)
            assert isinstance(studio_job_id, str)
            seen_job_ids.add(studio_job_id)
            fixture = expected.get(candidate_id)
            if fixture is not None:
                counts[candidate_id] += 1
                if not (
                    row.get("kind") == normalized_kind(fixture.kind)
                    and row.get("image_run_id") == fixture.run_id
                    and row.get("studio_job_id") == fixture.studio_job_id
                ):
                    return False
        return all(count == 1 for count in counts.values())

    def normalized_decision_result_is_valid(
        result: HttpResult,
        own: StagingIdentity,
    ) -> bool:
        fixture = own.normalized_decision
        body = result.json_body
        return (
            result.status == 200
            and result.content_type == "application/json"
            and isinstance(body, dict)
            and set(body) == {
                "status", "candidate_id", "kind", "source_project_id",
                "result_project_id", "terminal_asset_id", "studio_job_id",
                "family_id", "variation_index",
            }
            and body.get("status") == "discarded"
            and body.get("candidate_id") == fixture.candidate_id
            and body.get("kind") == fixture.kind
            and body.get("source_project_id") == own.project_id
            and body.get("result_project_id") == own.project_id
            and body.get("terminal_asset_id") is None
            and body.get("studio_job_id") == fixture.studio_job_id
            and body.get("family_id") is None
            and body.get("variation_index") is None
        )

    def candidate_paths(
        kind: str,
        identity: StagingIdentity,
    ) -> tuple[str, str, int, int]:
        actor_query = urlencode({
            "owner": identity.actor,
            "project_id": identity.project_id,
        })
        if kind == "catalog":
            return (
                f"/assets/{quote(identity.asset_id, safe='')}/catalog/previews",
                "/image-runs/{run_id}/catalog-candidates/{candidate_id}/image",
                404,
                404,
            )
        if kind == "visual":
            return (
                f"/studio/projects/{quote(identity.project_id, safe='')}/visual-candidates",
                "/studio/image-runs/{run_id}/visual-candidates/{candidate_id}/image",
                404,
                404,
            )
        if kind == "markup":
            return (
                f"/studio/projects/{quote(identity.project_id, safe='')}/markup-candidates",
                "/studio/markup-candidates/{run_id}/{candidate_id}/image",
                404,
                404,
            )
        if kind == "view":
            return (
                f"/studio/view-candidates?{actor_query}",
                (
                    "/studio/view-candidates/{run_id}/{candidate_id}/image?"
                    + urlencode({"owner": identity.actor})
                ),
                403,
                403,
            )
        if kind == "presentation":
            return (
                f"/studio/presentation-candidates?{actor_query}",
                (
                    "/studio/image-runs/{run_id}/presentation-candidates/"
                    "{candidate_id}/image?"
                    + urlencode({"owner": identity.actor})
                ),
                403,
                403,
            )
        raise RuntimeError(f"unsupported candidate probe kind: {kind}")

    # Bind the operator-selected release identifier to the process reached at
    # the exact HTTPS origin.  Before this check, a caller could label evidence
    # with any syntactically valid revision even when staging ran other code.
    live_health = transport("GET", f"{config.base_url}/health", "")
    health_body = (
        live_health.json_body
        if isinstance(live_health.json_body, dict) else {}
    )
    record(
        "live_health_is_facetta",
        True,
        (
            live_health.status == 200
            and live_health.content_type == "application/json"
            and health_body.get("status") == "ok"
            and health_body.get("service") == "facetta"
        ),
    )
    record(
        "live_deployment_revision_matches",
        True,
        health_body.get("deployment_revision") == config.deployment_revision,
    )
    record(
        "live_persistence_is_postgresql",
        True,
        health_body.get("persistence_backend") == "postgresql",
    )

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

        own_factory_pack = request(
            own, f"/projects/{quote(own.project_id, safe='')}/factory-pack",
        )
        record(
            f"user_{own.label}_factory_pack_route_is_addressable",
            True,
            own_factory_pack.status in {200, 409, 422},
        )
        cross_factory_pack = request(
            own, f"/projects/{quote(other.project_id, safe='')}/factory-pack",
        )
        record(
            f"user_{own.label}_cannot_read_other_factory_pack",
            403,
            cross_factory_pack.status,
        )
        own_factory_zip = request(
            own, f"/projects/{quote(own.project_id, safe='')}/factory-pack.zip",
        )
        record(
            f"user_{own.label}_factory_pack_zip_route_is_addressable",
            True,
            own_factory_zip.status in {200, 409, 422},
        )
        cross_factory_zip = request(
            own, f"/projects/{quote(other.project_id, safe='')}/factory-pack.zip",
        )
        record(
            f"user_{own.label}_cannot_download_other_factory_pack",
            403,
            cross_factory_zip.status,
        )

        own_checklist = request(
            own, f"/assets/{quote(own.asset_id, safe='')}/checklist",
        )
        record(
            f"user_{own.label}_checklist_route_is_addressable",
            True,
            own_checklist.status in {200, 404},
        )
        cross_checklist = request(
            own, f"/assets/{quote(other.asset_id, safe='')}/checklist",
        )
        record(
            f"user_{own.label}_cannot_read_other_checklist",
            403,
            cross_checklist.status,
        )

        own_targeting = request(
            own,
            f"/assets/{quote(own.asset_id, safe='')}/studio-component-targeting",
        )
        record(
            f"user_{own.label}_component_targeting_route_is_addressable",
            True,
            own_targeting.status in {200, 409},
        )
        cross_targeting = request(
            own,
            f"/assets/{quote(other.asset_id, safe='')}/studio-component-targeting",
        )
        record(
            f"user_{own.label}_cannot_read_other_component_targeting",
            403,
            cross_targeting.status,
        )

        cross_catalog_previews = request(
            own, f"/assets/{quote(other.asset_id, safe='')}/catalog/previews",
        )
        record(
            f"user_{own.label}_cannot_list_other_catalog_previews",
            404,
            cross_catalog_previews.status,
        )

        own_job = request(
            own,
            f"/studio/jobs/{quote(own.job_id, safe='')}?"
            + urlencode({"owner": own.actor}),
        )
        record(f"user_{own.label}_reads_own_job", 200, own_job.status)
        own_jobs = request(
            own, "/studio/jobs?" + urlencode({"owner": own.actor}),
        )
        record(f"user_{own.label}_lists_own_jobs", 200, own_jobs.status)
        record(
            f"user_{own.label}_job_results_are_tenant_scoped",
            True,
            own_jobs_are_tenant_scoped(own_jobs, own, other),
        )
        own_job_rows = collection_rows(own_jobs, "jobs")
        own_job_ids = {
            row["job_id"]
            for row in (own_job_rows or [])
            if isinstance(row.get("job_id"), str)
        }
        own_single_output_refine_job_ids = {
            row["job_id"]
            for row in (own_job_rows or [])
            if (
                studio_job_shape_is_valid(row)
                and row.get("action_id") == "refine"
                and isinstance(row.get("billing"), dict)
                and row["billing"].get("requested_outputs") == 1
                and isinstance(row.get("job_id"), str)
            )
        }
        cross_job = request(
            own,
            f"/studio/jobs/{quote(other.job_id, safe='')}?"
            + urlencode({"owner": own.actor}),
        )
        record(f"user_{own.label}_cannot_read_other_job", 404, cross_job.status)
        spoofed_jobs = request(
            own, "/studio/jobs?" + urlencode({"owner": other.actor}),
        )
        record(
            f"user_{own.label}_cannot_spoof_job_owner",
            403,
            spoofed_jobs.status,
        )

        normalized_list_path = (
            f"/studio/projects/{quote(own.project_id, safe='')}/"
            "preview-candidates"
        )
        own_normalized = request(own, normalized_list_path)
        record(
            f"user_{own.label}_lists_own_normalized_preview_candidates",
            200,
            own_normalized.status,
        )
        record(
            f"user_{own.label}_normalized_preview_results_are_tenant_scoped",
            True,
            own_normalized_candidates_are_tenant_scoped(
                own_normalized,
                own,
                other,
                own_single_output_refine_job_ids,
            ),
        )
        cross_normalized = request(
            own,
            f"/studio/projects/{quote(other.project_id, safe='')}/"
            "preview-candidates",
        )
        record(
            f"user_{own.label}_cannot_list_other_normalized_preview_candidates",
            404,
            cross_normalized.status,
        )

        for kind in ("catalog", "visual", "markup"):
            fixture = own.candidate(kind)
            other_fixture = other.candidate(kind)
            candidate_query = urlencode({"owner": own.actor})
            candidate_path = (
                f"/studio/preview-candidates/"
                f"{quote(fixture.candidate_id, safe='')}?{candidate_query}"
            )
            own_candidate = request(own, candidate_path)
            record(
                f"user_{own.label}_reads_own_normalized_{kind}_candidate",
                200,
                own_candidate.status,
            )
            candidate_body = (
                own_candidate.json_body
                if isinstance(own_candidate.json_body, dict) else {}
            )
            record(
                f"user_{own.label}_normalized_{kind}_candidate_lineage_is_exact",
                True,
                (
                    normalized_candidate_shape_is_valid(
                        candidate_body,
                        own=own,
                        own_single_output_refine_job_ids=(
                            own_single_output_refine_job_ids
                        ),
                    )
                    and candidate_body.get("candidate_id")
                    == fixture.candidate_id
                    and candidate_body.get("kind") == normalized_kind(kind)
                    and candidate_body.get("image_run_id") == fixture.run_id
                    and candidate_body.get("studio_job_id")
                    == fixture.studio_job_id
                ),
            )
            spoofed_candidate = request(
                own,
                f"/studio/preview-candidates/"
                f"{quote(fixture.candidate_id, safe='')}?"
                + urlencode({"owner": other.actor}),
            )
            record(
                f"user_{own.label}_cannot_spoof_normalized_{kind}_owner",
                403,
                spoofed_candidate.status,
            )
            cross_candidate = request(
                own,
                f"/studio/preview-candidates/"
                f"{quote(other_fixture.candidate_id, safe='')}?{candidate_query}",
            )
            record(
                f"user_{own.label}_cannot_enumerate_other_normalized_{kind}_candidate",
                404,
                cross_candidate.status,
            )
            image_path = (
                f"/studio/preview-candidates/"
                f"{quote(fixture.candidate_id, safe='')}/image?{candidate_query}"
            )
            own_candidate_image = request(own, image_path)
            record(
                f"user_{own.label}_reads_own_normalized_{kind}_candidate_image",
                200,
                own_candidate_image.status,
            )
            record(
                f"user_{own.label}_own_normalized_{kind}_candidate_is_image",
                True,
                own_candidate_image.content_type.startswith("image/"),
            )
            cross_candidate_image = request(
                own,
                f"/studio/preview-candidates/"
                f"{quote(other_fixture.candidate_id, safe='')}/image?"
                f"{candidate_query}",
            )
            record(
                f"user_{own.label}_cannot_read_other_normalized_{kind}_candidate_image",
                404,
                cross_candidate_image.status,
            )
            spoofed_candidate_image = request(
                own,
                f"/studio/preview-candidates/"
                f"{quote(fixture.candidate_id, safe='')}/image?"
                + urlencode({"owner": other.actor}),
            )
            record(
                f"user_{own.label}_cannot_spoof_normalized_{kind}_image_owner",
                403,
                spoofed_candidate_image.status,
            )

        decision_fixture = own.normalized_decision
        decision_query = urlencode({"owner": own.actor})
        decision_candidate = request(
            own,
            f"/studio/preview-candidates/"
            f"{quote(decision_fixture.candidate_id, safe='')}?{decision_query}",
        )
        decision_body = (
            decision_candidate.json_body
            if isinstance(decision_candidate.json_body, dict) else {}
        )
        record(
            f"user_{own.label}_reads_own_discarded_normalized_decision_fixture",
            200,
            decision_candidate.status,
        )
        record(
            f"user_{own.label}_normalized_decision_fixture_is_terminal_and_exact",
            True,
            (
                normalized_candidate_shape_is_valid(
                    decision_body,
                    own=own,
                    own_single_output_refine_job_ids=(
                        own_single_output_refine_job_ids
                    ),
                    expected_status="discarded",
                )
                and decision_body.get("candidate_id")
                == decision_fixture.candidate_id
                and decision_body.get("kind") == decision_fixture.kind
                and decision_body.get("image_run_id")
                == decision_fixture.image_run_id
                and decision_body.get("studio_job_id")
                == decision_fixture.studio_job_id
                and decision_body.get("expected_design_version")
                == decision_fixture.expected_design_version
            ),
        )
        decision_payload = {
            "created_by": own.actor,
            "decision": "discard",
            "expected_active_asset_id": decision_fixture.source_asset_id,
            "expected_design_version": decision_fixture.expected_design_version,
            "variation_label": None,
        }
        own_decision = decide(
            own, decision_fixture.candidate_id, decision_payload,
        )
        record(
            f"user_{own.label}_replays_own_terminal_normalized_decision",
            True,
            normalized_decision_result_is_valid(own_decision, own),
        )
        other_decision = other.normalized_decision
        cross_decision = decide(
            own,
            other_decision.candidate_id,
            decision_payload,
        )
        record(
            f"user_{own.label}_cannot_resolve_other_normalized_candidate",
            404,
            cross_decision.status,
        )
        spoofed_payload = {**decision_payload, "created_by": other.actor}
        spoofed_decision = decide(
            own,
            decision_fixture.candidate_id,
            spoofed_payload,
        )
        record(
            f"user_{own.label}_cannot_spoof_normalized_decision_actor",
            403,
            spoofed_decision.status,
        )

        for kind in (
            "catalog", "visual", "markup", "view", "presentation",
        ):
            list_path, image_template, cross_list_status, cross_image_status = (
                candidate_paths(kind, own)
            )
            fixture = own.candidate(kind)
            own_candidates = request(own, list_path)
            record(
                f"user_{own.label}_lists_own_{kind}_candidates",
                200,
                own_candidates.status,
            )
            record(
                f"user_{own.label}_{kind}_candidate_results_are_tenant_scoped",
                True,
                own_candidates_are_tenant_scoped(
                    own_candidates, kind, own, other, own_job_ids,
                ),
            )
            image_path = image_template.format(
                run_id=quote(fixture.run_id, safe=""),
                candidate_id=quote(fixture.candidate_id, safe=""),
            )
            other_fixture = other.candidate(kind)
            cross_image_path = image_template.format(
                run_id=quote(other_fixture.run_id, safe=""),
                candidate_id=quote(other_fixture.candidate_id, safe=""),
            )

            if kind == "catalog":
                cross_list_path = (
                    f"/assets/{quote(other.asset_id, safe='')}/catalog/previews"
                )
            elif kind in {"visual", "markup"}:
                cross_list_path = (
                    f"/studio/projects/{quote(other.project_id, safe='')}/"
                    f"{kind}-candidates"
                )
            else:
                cross_list_path = list_path.replace(
                    urlencode({
                        "owner": own.actor,
                        "project_id": own.project_id,
                    }),
                    urlencode({
                        "owner": other.actor,
                        "project_id": other.project_id,
                    }),
                )
            if kind != "catalog":
                cross_candidates = request(own, cross_list_path)
                record(
                    f"user_{own.label}_cannot_list_other_{kind}_candidates",
                    cross_list_status,
                    cross_candidates.status,
                )

            own_candidate_image = request(own, image_path)
            record(
                f"user_{own.label}_reads_own_{kind}_candidate_image",
                200,
                own_candidate_image.status,
            )
            record(
                f"user_{own.label}_own_{kind}_candidate_is_image",
                True,
                own_candidate_image.content_type.startswith("image/"),
            )
            # Keep the authenticated actor and owner query aligned while
            # changing only the bound object identifiers. Otherwise view and
            # presentation endpoints could reject an owner spoof before
            # exercising candidate-object isolation at all.
            cross_candidate_image = request(own, cross_image_path)
            record(
                f"user_{own.label}_cannot_read_other_{kind}_candidate_image",
                cross_image_status,
                cross_candidate_image.status,
            )
            no_auth_candidate_image = transport(
                "GET", f"{config.base_url}{image_path}", "",
            )
            record(
                f"user_{own.label}_{kind}_candidate_image_requires_auth",
                401,
                no_auth_candidate_image.status,
            )

    no_auth_families = transport(
        "GET", f"{config.base_url}/studio/families", "",
    )
    record("studio_families_require_auth", 401, no_auth_families.status)
    no_auth_paths = {
        "factory_packs_require_auth": (
            f"/projects/{quote(config.first.project_id, safe='')}/factory-pack"
        ),
        "factory_pack_downloads_require_auth": (
            f"/projects/{quote(config.first.project_id, safe='')}/factory-pack.zip"
        ),
        "asset_checklists_require_auth": (
            f"/assets/{quote(config.first.asset_id, safe='')}/checklist"
        ),
        "component_targeting_requires_auth": (
            f"/assets/{quote(config.first.asset_id, safe='')}/studio-component-targeting"
        ),
        "catalog_previews_require_auth": (
            f"/assets/{quote(config.first.asset_id, safe='')}/catalog/previews"
        ),
        "studio_jobs_require_auth": (
            "/studio/jobs?" + urlencode({"owner": config.first.actor})
        ),
        "normalized_preview_lists_require_auth": (
            f"/studio/projects/{quote(config.first.project_id, safe='')}/"
            "preview-candidates"
        ),
        "normalized_preview_candidates_require_auth": (
            "/studio/preview-candidates/"
            f"{quote(config.first.candidate('visual').candidate_id, safe='')}"
        ),
        "normalized_preview_images_require_auth": (
            "/studio/preview-candidates/"
            f"{quote(config.first.candidate('visual').candidate_id, safe='')}/image"
        ),
    }
    for name, path in no_auth_paths.items():
        result = transport("GET", f"{config.base_url}{path}", "")
        record(name, 401, result.status)

    unauthenticated_decision = decision_transport(
        "POST",
        f"{config.base_url}/studio/preview-candidates/"
        f"{quote(config.first.normalized_decision.candidate_id, safe='')}/decision",
        "",
        {
            "created_by": config.first.actor,
            "decision": "discard",
            "expected_active_asset_id": config.first.asset_id,
            "expected_design_version": (
                config.first.normalized_decision.expected_design_version
            ),
            "variation_label": None,
        },
    )
    record(
        "normalized_preview_decisions_require_auth",
        401,
        unauthenticated_decision.status,
    )

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

    # A path can collide with an allowed dynamic GET route (for example,
    # /projects/from-image is also shaped like /projects/{root_id}). Therefore
    # an exact 404 check would reject the safe production surface. OPTIONS
    # exposes the mounted methods without invoking them: 404 is unmounted; 405
    # is acceptable only when the retired mutating method is absent from Allow.
    legacy_path_values = {
        "project_id": quote(config.first.project_id, safe=""),
        "root_id": quote(config.first.project_id, safe=""),
        "asset_id": quote(config.first.asset_id, safe=""),
        "active_asset_id": quote(config.first.asset_id, safe=""),
        "design_id": "e2e-hidden",
        "version": "1",
        "token": "e2e-hidden",
        "candidate_id": "e2e-hidden",
        "line_art_asset_id": "e2e-hidden",
        "run_id": "e2e-hidden",
    }
    for name, forbidden_method, path_template in (
        STAGING_DISALLOWED_LEGACY_OPERATIONS
    ):
        path = path_template.format(**legacy_path_values)
        legacy = transport(
            "OPTIONS", f"{config.base_url}{path}", config.first.token,
        )
        record(
            f"production_disallows_{name}",
            True,
            (
                legacy.status == 404
                or (
                    legacy.status == 405
                    and bool(legacy.allowed_methods)
                    and forbidden_method not in legacy.allowed_methods
                )
            ),
        )

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
            "job_id": identity.job_id,
                "candidates": {
                candidate.kind: {
                    "run_id": candidate.run_id,
                    "candidate_id": candidate.candidate_id,
                    "source_asset_id": candidate.source_asset_id,
                    "studio_job_id": candidate.studio_job_id,
                }
                    for candidate in identity.candidates
                },
                "normalized_decision": {
                    "kind": identity.normalized_decision.kind,
                    "image_run_id": identity.normalized_decision.image_run_id,
                    "candidate_id": identity.normalized_decision.candidate_id,
                    "source_asset_id": identity.normalized_decision.source_asset_id,
                    "studio_job_id": identity.normalized_decision.studio_job_id,
                    "expected_design_version": (
                        identity.normalized_decision.expected_design_version
                    ),
                },
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
        "schema_version": STAGING_RESULT_SCHEMA,
        "run_kind": "read_only_two_principal_staging_probe",
        "target": {
            "staging_run_id": config.staging_run_id,
            "external_release_run_id": config.external_release_run_id,
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

"""Production boundary for provider-backed Studio work.

Compatibility callers may still omit a Studio job in development and tests.
The Internet-facing application may not: every requested provider output must
be tied to one canonical, running Studio job before provider work begins.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Literal, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from facetta.config import env_value
from facetta.db import (
    STUDIO_CREATE_INTENT_SCHEMA_VERSION,
    STUDIO_REFINE_INTENT_SCHEMA_VERSION,
    StudioCreateIntentRecord,
    StudioJobRecord,
    StudioRefineIntentRecord,
    studio_create_intent_sha256,
    studio_refine_intent_sha256,
)
from facetta.studio_jobs import studio_job_action_definition


ProviderJobAction = Literal["create", "refine", "views", "present"]


@dataclass(frozen=True, slots=True)
class ProviderStudioJobError(ValueError):
    """A provider request is not backed by the required Studio job."""

    code: str
    detail: str
    status_code: int

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True, slots=True)
class StudioCreateIntentSnapshot:
    """Verified append-only visual guidance bound to one Create job."""

    studio_job_id: str
    owner: str
    schema_version: str
    creative_intent: dict[str, str]
    creative_intent_sha256: str

    def revision_fields(self) -> dict[str, object]:
        return {
            "studio_job_id": self.studio_job_id,
            "creative_intent_schema": self.schema_version,
            "creative_intent": dict(self.creative_intent),
            "creative_intent_sha256": self.creative_intent_sha256,
        }


@dataclass(frozen=True, slots=True)
class StudioRefineIntentSnapshot:
    """Verified append-only edit request bound to one Refine job."""

    studio_job_id: str
    owner: str
    schema_version: str
    refine_intent: dict[str, object]
    refine_intent_sha256: str


_CREATIVE_INTENT_VALUES: dict[str, frozenset[str]] = {
    "metal_color": frozenset({"yellow", "white", "rose", "mixed"}),
    "color_accent": frozenset({
        "colorless", "blue", "green", "pink_red", "warm", "multicolor",
    }),
    "surface_finish": frozenset({
        "polished", "satin_brushed", "hammered", "frosted", "organic", "mixed",
    }),
    "visual_mood": frozenset({
        "minimal", "romantic", "organic", "heritage", "sculptural", "playful",
    }),
}


def _error(code: str, detail: str, status_code: int) -> ProviderStudioJobError:
    return ProviderStudioJobError(
        code=code,
        detail=detail,
        status_code=status_code,
    )


def normalize_studio_create_intent(
    value: Mapping[str, object] | None,
) -> dict[str, str]:
    """Return a canonical typed Create intent; an empty object is explicit."""

    if value is None:
        return {}
    if not isinstance(value, Mapping) or set(value) - set(_CREATIVE_INTENT_VALUES):
        raise _error(
            "studio_create_intent_invalid",
            "the Studio Create visual guidance is not canonical",
            422,
        )
    normalized: dict[str, str] = {}
    for key in _CREATIVE_INTENT_VALUES:
        if key not in value:
            continue
        item = value[key]
        if not isinstance(item, str) or item not in _CREATIVE_INTENT_VALUES[key]:
            raise _error(
                "studio_create_intent_invalid",
                "the Studio Create visual guidance is not canonical",
                422,
            )
        normalized[key] = item
    return normalized


def normalize_studio_refine_intent(
    value: Mapping[str, object],
) -> dict[str, object]:
    """Return a byte-stable JSON snapshot of one exact Refine request."""

    if (
        not isinstance(value, Mapping)
        or set(value) != {"intent_kind", "request"}
        or not isinstance(value.get("intent_kind"), str)
        or not str(value["intent_kind"]).strip()
        or not isinstance(value.get("request"), Mapping)
    ):
        raise _error(
            "studio_refine_intent_invalid",
            "the Studio Refine request is not canonical",
            422,
        )
    try:
        normalized = json.loads(json.dumps(
            dict(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ))
    except (TypeError, ValueError):
        raise _error(
            "studio_refine_intent_invalid",
            "the Studio Refine request is not canonical",
            422,
        ) from None
    if not isinstance(normalized, dict):
        raise _error(
            "studio_refine_intent_invalid",
            "the Studio Refine request is not canonical",
            422,
        )
    return normalized


def studio_create_intent_record(
    *,
    studio_job_id: str,
    owner: str,
    creative_intent: Mapping[str, object] | None,
) -> StudioCreateIntentRecord:
    """Build the immutable intent row inserted with a new Create job."""

    normalized = normalize_studio_create_intent(creative_intent)
    return StudioCreateIntentRecord(
        studio_job_id=studio_job_id,
        owner=owner,
        schema_version=STUDIO_CREATE_INTENT_SCHEMA_VERSION,
        creative_intent=normalized,
        creative_intent_sha256=studio_create_intent_sha256(normalized),
    )


def require_studio_create_intent_snapshot(
    db: Session,
    *,
    studio_job_id: str,
    owner: str,
) -> StudioCreateIntentSnapshot:
    """Fail closed unless the exact append-only Create request is intact."""

    record = db.scalar(select(StudioCreateIntentRecord).where(
        StudioCreateIntentRecord.studio_job_id == studio_job_id,
    ))
    if record is None or record.owner != owner:
        raise _error(
            "studio_create_intent_unbound",
            "the Studio Create job has no bound visual guidance",
            409,
        )
    normalized = normalize_studio_create_intent(record.creative_intent)
    digest = studio_create_intent_sha256(normalized)
    if (
        record.schema_version != STUDIO_CREATE_INTENT_SCHEMA_VERSION
        or record.creative_intent_sha256 != digest
    ):
        raise _error(
            "studio_create_intent_corrupt",
            "the Studio Create visual guidance failed its integrity check",
            409,
        )
    return StudioCreateIntentSnapshot(
        studio_job_id=record.studio_job_id,
        owner=record.owner,
        schema_version=record.schema_version,
        creative_intent=normalized,
        creative_intent_sha256=digest,
    )


def require_provider_studio_job(
    db: Session,
    *,
    job_id: str | None,
    owner: str,
    action_id: ProviderJobAction,
    requested_outputs: int,
    active_design_id: str | None = None,
    source_revision_id: str | None = None,
    creative_intent: Mapping[str, object] | None = None,
) -> StudioJobRecord | None:
    """Validate the exact job authority before any provider call.

    Missing jobs remain a compatibility path only outside production.  When a
    job is supplied in any environment it is validated identically, so tests
    exercise the same owner, pricing, lifecycle, output-count, and lineage
    rules used by the deployed application.  The selected row is locked for
    the surrounding request transaction; candidate-specific services may then
    perform their stronger reservation transition before generation.
    """

    environment = (env_value("FACETTA_ENV") or "production").strip().lower()
    if job_id is None:
        if environment != "production":
            return None
        raise _error(
            "studio_job_required",
            "production generation requires a durable Studio job",
            422,
        )

    job = db.scalar(select(StudioJobRecord).where(
        StudioJobRecord.id == job_id,
    ).with_for_update())
    if job is None or job.owner != owner:
        # Do not disclose whether a foreign job exists.
        raise _error(
            "studio_job_unavailable",
            "the Studio job is unavailable",
            404,
        )

    canonical = studio_job_action_definition(action_id)
    if (
        job.action_id != action_id
        or job.lane != canonical.lane
        or job.credits_per_output != canonical.credits_per_output
        or job.requested_outputs != requested_outputs
    ):
        raise _error(
            "studio_job_invalid",
            "the Studio job action, output count, or pricing is not canonical",
            422,
        )
    if (
        job.status != "running"
        or job.completed_outputs != 0
        or job.charged_outputs != 0
    ):
        raise _error(
            "studio_job_terminal",
            f"the Studio job cannot generate from {job.status}",
            409,
        )
    if action_id == "create" and (
        job.active_design_id is not None
        or job.source_revision_id is not None
    ):
        raise _error(
            "studio_job_terminal",
            "the Studio Create job is already bound to generated work",
            409,
        )
    if action_id == "create":
        bound_intent = require_studio_create_intent_snapshot(
            db,
            studio_job_id=job.id,
            owner=owner,
        )
        if bound_intent.creative_intent != normalize_studio_create_intent(
            creative_intent
        ):
            raise _error(
                "studio_create_intent_mismatch",
                "the generation request changed after its Studio job was created",
                409,
            )
    for field, expected in (
        ("active_design_id", active_design_id),
        ("source_revision_id", source_revision_id),
    ):
        if expected is not None and getattr(job, field) != expected:
            raise _error(
                "studio_job_lineage_mismatch",
                "the Studio job belongs to a different exact revision",
                422,
            )
    return job


def bind_or_require_studio_refine_intent(
    db: Session,
    *,
    studio_job_id: str,
    owner: str,
    active_design_id: str,
    source_revision_id: str,
    refine_intent: Mapping[str, object],
) -> StudioRefineIntentSnapshot:
    """Claim a running Refine job once, then require exact request equality.

    The job row remains locked for the surrounding provider transaction. This
    makes the first request the sole authority and rejects a changed component,
    option, variant, or production detail before provider work begins.
    """

    require_provider_studio_job(
        db,
        job_id=studio_job_id,
        owner=owner,
        action_id="refine",
        requested_outputs=1,
        active_design_id=active_design_id,
        source_revision_id=source_revision_id,
    )
    normalized = normalize_studio_refine_intent(refine_intent)
    digest = studio_refine_intent_sha256(normalized)
    record = db.scalar(select(StudioRefineIntentRecord).where(
        StudioRefineIntentRecord.studio_job_id == studio_job_id,
    ).with_for_update())
    if record is None:
        record = StudioRefineIntentRecord(
            studio_job_id=studio_job_id,
            owner=owner,
            schema_version=STUDIO_REFINE_INTENT_SCHEMA_VERSION,
            refine_intent=normalized,
            refine_intent_sha256=digest,
        )
        db.add(record)
        db.flush()
    else:
        if record.owner != owner:
            raise _error(
                "studio_refine_intent_unavailable",
                "the Studio Refine request is unavailable",
                404,
            )
        try:
            stored = normalize_studio_refine_intent(record.refine_intent)
        except ProviderStudioJobError:
            raise _error(
                "studio_refine_intent_corrupt",
                "the Studio Refine request failed its integrity check",
                409,
            ) from None
        if (
            record.schema_version != STUDIO_REFINE_INTENT_SCHEMA_VERSION
            or record.refine_intent_sha256
            != studio_refine_intent_sha256(stored)
        ):
            raise _error(
                "studio_refine_intent_corrupt",
                "the Studio Refine request failed its integrity check",
                409,
            )
        if stored != normalized or record.refine_intent_sha256 != digest:
            raise _error(
                "studio_refine_intent_mismatch",
                "the edit request changed after its Studio job was claimed",
                409,
            )
    return StudioRefineIntentSnapshot(
        studio_job_id=record.studio_job_id,
        owner=record.owner,
        schema_version=record.schema_version,
        refine_intent=normalized,
        refine_intent_sha256=digest,
    )

"""Production boundary for provider-backed Studio work.

Compatibility callers may still omit a Studio job in development and tests.
The Internet-facing application may not: every requested provider output must
be tied to one canonical, running Studio job before provider work begins.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from facetta.config import env_value
from facetta.db import StudioJobRecord
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


def _error(code: str, detail: str, status_code: int) -> ProviderStudioJobError:
    return ProviderStudioJobError(
        code=code,
        detail=detail,
        status_code=status_code,
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

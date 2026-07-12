"""Server-owned Studio action pricing and trusted outcome accounting."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from facetta.db import StudioJobRecord, utcnow


@dataclass(frozen=True, slots=True)
class StudioJobActionDefinition:
    """Execution lane and public credit rate owned by the server."""

    lane: str
    credits_per_output: int


STUDIO_JOB_ACTIONS: dict[str, StudioJobActionDefinition] = {
    "create": StudioJobActionDefinition("fast_visual", 15),
    "vary": StudioJobActionDefinition("instant", 0),
    "refine": StudioJobActionDefinition("trusted_structural", 20),
    "views": StudioJobActionDefinition("fast_visual", 15),
    "present": StudioJobActionDefinition("fast_visual", 18),
    "factory": StudioJobActionDefinition("trusted_structural", 28),
}


class StudioJobAccountingError(ValueError):
    """A trusted outcome cannot be recorded without breaking job invariants."""


def studio_job_action_definition(action_id: str) -> StudioJobActionDefinition:
    try:
        return STUDIO_JOB_ACTIONS[action_id]
    except KeyError as exc:
        raise StudioJobAccountingError(
            f"unknown Studio job action '{action_id}'"
        ) from exc


def record_accepted_studio_job_outputs(
    db: Session,
    *,
    job_id: str,
    owner: str,
    completed_outputs: int,
    active_design_id: str | None = None,
    source_revision_id: str | None = None,
) -> StudioJobRecord:
    """Record a backend-authorized acceptance without committing.

    The caller owns the surrounding transaction so accepting a canonical asset
    and charging its requested output can be atomic.  This helper is purposely
    not exposed through the public Studio jobs API.
    """

    job = db.get(StudioJobRecord, job_id)
    if job is None:
        raise StudioJobAccountingError(f"unknown Studio job '{job_id}'")
    if job.owner != owner:
        # Internal callers still fail closed rather than disclosing or billing
        # a job from another designer's acceptance transaction.
        raise StudioJobAccountingError(f"unknown Studio job '{job_id}'")
    if job.status not in {"running", "reviewing", "succeeded"}:
        raise StudioJobAccountingError(
            f"Studio job cannot accept outputs from {job.status}"
        )
    if completed_outputs < 1 or completed_outputs > job.requested_outputs:
        raise StudioJobAccountingError(
            "accepted outputs must be between one and requested_outputs"
        )
    canonical = studio_job_action_definition(job.action_id)
    if (
        job.lane != canonical.lane
        or job.credits_per_output != canonical.credits_per_output
    ):
        raise StudioJobAccountingError("Studio job pricing is not canonical")
    for field, incoming in (
        ("active_design_id", active_design_id),
        ("source_revision_id", source_revision_id),
    ):
        current = getattr(job, field)
        if incoming is not None and current is not None and incoming != current:
            raise StudioJobAccountingError(
                f"Studio job {field} is already bound and cannot change"
            )
    if job.charged_outputs:
        if (
            job.status == "succeeded"
            and job.completed_outputs == completed_outputs
            and job.charged_outputs == completed_outputs
        ):
            return job
        raise StudioJobAccountingError("Studio job outputs are already charged")
    for field, incoming in (
        ("active_design_id", active_design_id),
        ("source_revision_id", source_revision_id),
    ):
        if incoming is not None:
            setattr(job, field, incoming)

    job.status = "succeeded"
    job.progress = 1
    job.completed_outputs = completed_outputs
    job.charged_outputs = completed_outputs
    job.error_code = None
    job.updated_at = utcnow()
    db.flush()
    return job

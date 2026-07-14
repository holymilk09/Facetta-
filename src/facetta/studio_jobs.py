"""Server-owned Studio action pricing and trusted outcome accounting."""

from __future__ import annotations

from dataclasses import dataclass
import json
from importlib.resources import files
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from facetta.db import (
    ApprovalChecklist,
    ApprovalResponse,
    DesignVersion,
    ImageAsset,
    Project,
    StudioJobRecord,
    utcnow,
)


StudioExecutionMode = Literal[
    "instant_transaction", "candidate_job", "terminal_job",
]
StudioReviewAuthority = Literal[
    "none", "candidate_decision", "generic_transition",
]

_EXECUTION_MODES = frozenset({
    "instant_transaction", "candidate_job", "terminal_job",
})
_REVIEW_AUTHORITIES = frozenset({
    "none", "candidate_decision", "generic_transition",
})
_REVIEW_AUTHORITY_BY_EXECUTION_MODE = {
    "instant_transaction": "none",
    "candidate_job": "candidate_decision",
    "terminal_job": "generic_transition",
}


@dataclass(frozen=True, slots=True)
class StudioJobUiField:
    """One provider-neutral input rendered by the Studio action UI."""

    id: str
    label: str
    kind: str
    required: bool
    reference_role: str | None = None


@dataclass(frozen=True, slots=True)
class StudioJobActionDefinition:
    """Canonical Studio job contract owned by the server."""

    lane: str
    execution_mode: StudioExecutionMode
    review_authority: StudioReviewAuthority
    credits_per_output: int
    min_requested_outputs: int
    max_requested_outputs: int
    input_requirements: tuple[str, ...]
    context_requirements: tuple[str, ...]
    output_type: str
    authority: str
    ui_schema: tuple[StudioJobUiField, ...]


def _load_studio_job_actions() -> dict[str, StudioJobActionDefinition]:
    raw = json.loads(
        files("facetta").joinpath("studio_action_manifest.json").read_text(
            encoding="utf-8",
        ),
    )
    for action_id, value in raw.items():
        execution_mode = value.get("execution_mode")
        review_authority = value.get("review_authority")
        if execution_mode not in _EXECUTION_MODES:
            raise ValueError(
                f"Studio action {action_id!r} has invalid execution_mode "
                f"{execution_mode!r}"
            )
        if review_authority not in _REVIEW_AUTHORITIES:
            raise ValueError(
                f"Studio action {action_id!r} has invalid review_authority "
                f"{review_authority!r}"
            )
        expected_authority = _REVIEW_AUTHORITY_BY_EXECUTION_MODE[execution_mode]
        if review_authority != expected_authority:
            raise ValueError(
                f"Studio action {action_id!r} execution_mode {execution_mode!r} "
                f"requires review_authority {expected_authority!r}"
            )
        minimum = value.get("min_requested_outputs")
        maximum = value.get("max_requested_outputs")
        if (
            not isinstance(minimum, int)
            or isinstance(minimum, bool)
            or not isinstance(maximum, int)
            or isinstance(maximum, bool)
            or minimum < 0
            or maximum < minimum
            or maximum > 4
        ):
            raise ValueError(
                f"Studio action {action_id!r} has invalid requested-output "
                f"range {minimum!r}..{maximum!r}"
            )
        if (
            execution_mode == "instant_transaction"
            and (minimum, maximum) != (0, 0)
        ):
            raise ValueError(
                f"Studio instant action {action_id!r} must request zero outputs"
            )
        if execution_mode != "instant_transaction" and minimum < 1:
            raise ValueError(
                f"Studio job action {action_id!r} must request at least one output"
            )
    return {
        action_id: StudioJobActionDefinition(
            lane=value["lane"],
            execution_mode=value["execution_mode"],
            review_authority=value["review_authority"],
            credits_per_output=value["credits_per_output"],
            min_requested_outputs=value["min_requested_outputs"],
            max_requested_outputs=value["max_requested_outputs"],
            input_requirements=tuple(value["input_requirements"]),
            context_requirements=tuple(value["context_requirements"]),
            output_type=value["output_type"],
            authority=value["authority"],
            ui_schema=tuple(
                StudioJobUiField(
                    id=field["id"],
                    label=field["label"],
                    kind=field["kind"],
                    required=field["required"],
                    reference_role=field.get("reference_role"),
                )
                for field in value["ui_schema"]
            ),
        )
        for action_id, value in raw.items()
    }


STUDIO_JOB_ACTIONS = _load_studio_job_actions()


class StudioJobAccountingError(ValueError):
    """A trusted outcome cannot be recorded without breaking job invariants."""


class FactoryJobContextError(ValueError):
    """Factory work is no longer bound to the eligible active revision."""


class ApprovalGenerationLockedError(ValueError):
    """Approval truth cannot change while Factory consumes that generation."""


def lock_project_approval_generation(
    db: Session,
    *,
    project_root_id: str,
    owner: str | None = None,
    for_mutation: bool = False,
) -> Project | None:
    """Serialize Factory eligibility and every writer of approval truth.

    All approval/checklist writers and Factory CAS acquire the same Project
    row first. Once Factory work is queued, its approval generation remains
    immutable until the job reaches a terminal state; a writer can then start
    the next generation. Legacy asset chains without a Project cannot create
    Factory jobs, so returning ``None`` preserves their compatibility path
    without weakening Factory authority.
    """

    project_query = select(Project).where(Project.root_id == project_root_id)
    if owner is not None:
        project_query = project_query.where(Project.owner == owner)
    project = db.scalar(project_query.with_for_update())
    if project is None or not for_mutation:
        return project

    active_factory_job = db.scalar(select(StudioJobRecord).where(
        StudioJobRecord.active_design_id == project_root_id,
        StudioJobRecord.action_id == "factory",
        StudioJobRecord.status.in_(("queued", "running", "reviewing")),
    ).order_by(
        StudioJobRecord.created_at,
        StudioJobRecord.id,
    ).with_for_update())
    if active_factory_job is not None:
        raise ApprovalGenerationLockedError(
            "approval is locked while Factory reviews this exact revision"
        )
    return project


def lock_factory_job_context(
    db: Session,
    *,
    owner: str,
    project_root_id: str,
    source_revision_id: str,
) -> Project:
    """Lock and revalidate exact Factory authority in the current transaction."""

    from facetta.api.projects import project_detail

    project = lock_project_approval_generation(
        db,
        project_root_id=project_root_id,
        owner=owner,
    )
    if project is None:
        raise FactoryJobContextError("the Factory project is unavailable")
    source = db.scalar(select(ImageAsset).where(
        ImageAsset.id == source_revision_id,
        ImageAsset.root_id == project_root_id,
    ).with_for_update())
    if source is None:
        raise FactoryJobContextError("the Factory source revision is unavailable")
    root = db.scalar(select(ImageAsset).where(
        ImageAsset.id == project_root_id,
    ).with_for_update())
    if root is None or root.design_id is None or source.design_version is None:
        raise FactoryJobContextError(
            "Factory requires an exact specification-bound revision"
        )
    version = db.scalar(select(DesignVersion).where(
        DesignVersion.design_id == root.design_id,
        DesignVersion.version == source.design_version,
    ).with_for_update())
    if version is None:
        raise FactoryJobContextError(
            "the Factory source specification is unavailable"
        )
    checklists = list(db.scalars(select(ApprovalChecklist).where(
        ApprovalChecklist.asset_id == source_revision_id,
    ).with_for_update()))
    checklist_ids = [checklist.id for checklist in checklists]
    if checklist_ids:
        list(db.scalars(select(ApprovalResponse).where(
            ApprovalResponse.checklist_id.in_(checklist_ids)
        ).with_for_update()))

    detail = project_detail(db, project)
    if detail["active_asset_id"] != source_revision_id:
        raise FactoryJobContextError(
            "the Factory source is no longer the active revision"
        )
    if detail["active_design_version"] != source.design_version:
        raise FactoryJobContextError(
            "the Factory source specification is no longer active"
        )
    if not detail["factory_ready"]:
        raise FactoryJobContextError(
            "the active revision is no longer eligible for Factory review"
        )
    return project


def revalidate_factory_job_for_execution(
    db: Session,
    *,
    job_id: str,
    owner: str,
) -> StudioJobRecord:
    """Fail stale queued Factory work with zero charge before provider work."""

    # Read the immutable binding first, then acquire Project before the job row.
    # Approval writers use Project -> job in that order too, avoiding a lock
    # inversion while still rechecking the job after both locks are held.
    job_snapshot = db.scalar(select(StudioJobRecord).where(
        StudioJobRecord.id == job_id,
        StudioJobRecord.owner == owner,
    ))
    if job_snapshot is None:
        raise FactoryJobContextError("the Factory job is unavailable")
    if job_snapshot.action_id != "factory":
        raise FactoryJobContextError(
            "the supplied Studio job is not a Factory job"
        )
    if job_snapshot.status != "queued":
        raise FactoryJobContextError(
            f"Factory job cannot start from {job_snapshot.status}"
        )
    try:
        if (job_snapshot.active_design_id is None
                or job_snapshot.source_revision_id is None):
            raise FactoryJobContextError("the Factory job context is incomplete")
        lock_factory_job_context(
            db,
            owner=owner,
            project_root_id=job_snapshot.active_design_id,
            source_revision_id=job_snapshot.source_revision_id,
        )
    except FactoryJobContextError:
        failed_job = db.scalar(select(StudioJobRecord).where(
            StudioJobRecord.id == job_id,
            StudioJobRecord.owner == owner,
        ).with_for_update())
        if failed_job is not None and failed_job.status == "queued":
            failed_job.status = "failed"
            failed_job.progress = 1
            failed_job.completed_outputs = 0
            failed_job.charged_outputs = 0
            failed_job.error_code = "stale_factory_context"
            failed_job.updated_at = utcnow()
        db.commit()
        raise
    job = db.scalar(select(StudioJobRecord).where(
        StudioJobRecord.id == job_id,
        StudioJobRecord.owner == owner,
    ).with_for_update())
    if job is None or job.status != "queued":
        state = "unavailable" if job is None else job.status
        raise FactoryJobContextError(f"Factory job cannot start from {state}")
    return job


def studio_job_action_definition(action_id: str) -> StudioJobActionDefinition:
    try:
        return STUDIO_JOB_ACTIONS[action_id]
    except KeyError as exc:
        raise StudioJobAccountingError(
            f"unknown Studio job action '{action_id}'"
        ) from exc


def settle_create_studio_job_selection(
    db: Session,
    *,
    job_id: str,
    owner: str,
    project_root_id: str,
    source_revision_id: str,
    available_outputs: int,
) -> StudioJobRecord:
    """Atomically settle one durable Create review after candidate selection.

    Candidate generation and designer selection can occur in different client
    processes.  The reviewing job is therefore the server-held CAS token: it
    must already be bound to this project, and its selected source may be bound
    only once.  The caller owns the surrounding Project/candidate transaction
    and commits the selection together with this settlement.
    """

    job = db.scalar(select(StudioJobRecord).where(
        StudioJobRecord.id == job_id,
    ).with_for_update())
    if job is None or job.owner != owner:
        raise StudioJobAccountingError(f"unknown Studio job '{job_id}'")
    if job.action_id != "create":
        raise StudioJobAccountingError("Studio job is not a Create review")
    if job.active_design_id != project_root_id:
        raise StudioJobAccountingError(
            "Create job is not bound to the selected project"
        )
    if job.source_revision_id not in (None, source_revision_id):
        raise StudioJobAccountingError(
            "Create job is already bound to another selected direction"
        )
    if available_outputs < 1:
        raise StudioJobAccountingError(
            "Create selection requires at least one persisted output"
        )
    completed_outputs = min(job.requested_outputs, available_outputs)
    if job.status == "succeeded":
        if (
            job.source_revision_id == source_revision_id
            and job.completed_outputs == completed_outputs
            and job.charged_outputs == completed_outputs
        ):
            return job
        raise StudioJobAccountingError(
            "Create job was already settled with different output evidence"
        )
    if job.status != "reviewing":
        raise StudioJobAccountingError(
            f"Create job cannot settle selection from {job.status}"
        )
    return record_accepted_studio_job_outputs(
        db,
        job_id=job.id,
        owner=owner,
        completed_outputs=completed_outputs,
        active_design_id=project_root_id,
        source_revision_id=source_revision_id,
    )


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
    job.reservation_kind = None
    job.updated_at = utcnow()
    db.flush()
    return job

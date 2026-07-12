"""Server-owned Studio action pricing and trusted outcome accounting."""

from __future__ import annotations

from dataclasses import dataclass

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
    credits_per_output: int
    input_requirements: tuple[str, ...]
    context_requirements: tuple[str, ...]
    output_type: str
    authority: str
    ui_schema: tuple[StudioJobUiField, ...]


STUDIO_JOB_ACTIONS: dict[str, StudioJobActionDefinition] = {
    "create": StudioJobActionDefinition(
        lane="fast_visual",
        credits_per_output=15,
        input_requirements=("brief",),
        context_requirements=(),
        output_type="design_revision",
        authority="design_record",
        ui_schema=(
            StudioJobUiField("brief", "Design brief", "text", True),
            StudioJobUiField(
                "master", "Master geometry", "reference", False,
                "master_geometry",
            ),
            StudioJobUiField(
                "style", "Material or style", "reference", False,
                "material_style",
            ),
        ),
    ),
    "vary": StudioJobActionDefinition(
        lane="instant",
        credits_per_output=0,
        input_requirements=("direction",),
        context_requirements=("active_project", "active_revision"),
        output_type="variation_set",
        authority="design_record",
        ui_schema=(
            StudioJobUiField("direction", "Variation name", "text", True),
        ),
    ),
    "refine": StudioJobActionDefinition(
        lane="trusted_structural",
        credits_per_output=20,
        input_requirements=("instruction",),
        context_requirements=("active_project", "active_revision"),
        output_type="design_revision",
        authority="design_record",
        ui_schema=(
            StudioJobUiField(
                "instruction", "Change instruction", "text", True,
            ),
            StudioJobUiField(
                "mask", "Target region", "reference", False, "edit_mask",
            ),
        ),
    ),
    "views": StudioJobActionDefinition(
        lane="fast_visual",
        credits_per_output=15,
        input_requirements=("view_set",),
        context_requirements=(
            "active_project", "active_revision", "exact_specification",
        ),
        output_type="view_set",
        authority="visual_preview",
        ui_schema=(
            StudioJobUiField("view_set", "Views", "select", True),
        ),
    ),
    "present": StudioJobActionDefinition(
        lane="fast_visual",
        credits_per_output=18,
        input_requirements=("destination",),
        context_requirements=("active_project", "active_revision"),
        output_type="presentation_pack",
        authority="visual_preview",
        ui_schema=(
            StudioJobUiField(
                "destination", "Presentation destination", "select", True,
            ),
            StudioJobUiField(
                "brand", "Brand direction", "reference", False,
                "brand_direction",
            ),
        ),
    ),
    "factory": StudioJobActionDefinition(
        lane="trusted_structural",
        credits_per_output=28,
        input_requirements=("confirmed_facts",),
        context_requirements=(
            "active_project",
            "active_revision",
            "exact_specification",
            "factory_eligible",
        ),
        output_type="factory_review_pack",
        authority="production_review",
        ui_schema=(
            StudioJobUiField(
                "confirmed_facts", "Confirmed production facts", "toggle",
                True,
            ),
        ),
    ),
}


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
        return job_snapshot
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

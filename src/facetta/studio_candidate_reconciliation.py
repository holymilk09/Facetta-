"""Reconcile temporary Studio review work before Activity is serialized.

Each candidate domain remains the authority for its own expiration, terminal
job settlement, and billing effect.  Activity calls this narrow coordinator so
its job lifecycle cannot advertise an already-expired review decision.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from facetta.catalog_preview_candidates import (
    expire_stale_catalog_preview_candidates,
)
from facetta.db import StudioJobRecord
from facetta.studio_markup_candidates import (
    expire_stale_studio_markup_candidates,
)
from facetta.studio_presentation_candidates import (
    expire_stale_studio_presentation_candidates,
)
from facetta.studio_view_candidates import (
    expire_stale_studio_view_candidates,
    expire_stale_studio_view_reservations,
)
from facetta.studio_visual_candidates import (
    expire_stale_studio_visual_candidates,
    expire_stale_studio_visual_reservations,
)
from facetta.studio_visual_angle_sets import (
    expire_stale_studio_visual_angle_reservations,
    expire_stale_studio_visual_angle_sets,
)


def reconcile_studio_review_jobs(
    db: Session,
    *,
    owner: str,
    job_id: str | None = None,
) -> int:
    """Return the number of stale reservations or candidates reconciled.

    The owner scope is mandatory.  Candidate-domain functions use their
    existing row locks and exact job bindings, making repeated Activity reads
    idempotent and preventing a foreign owner's read from settling work.
    """

    query = select(StudioJobRecord.action_id).where(
        StudioJobRecord.owner == owner,
        StudioJobRecord.status == "reviewing",
    )
    if job_id is not None:
        query = query.where(StudioJobRecord.id == job_id)
    actions = set(db.scalars(query))
    if not actions:
        return 0

    reconciled = 0
    if "refine" in actions:
        reconciled += expire_stale_studio_visual_reservations(
            db, owner=owner, job_id=job_id,
        )
        reconciled += expire_stale_catalog_preview_candidates(
            db, owner=owner, job_id=job_id,
        )
        reconciled += expire_stale_studio_visual_candidates(
            db, owner=owner, job_id=job_id,
        )
        reconciled += expire_stale_studio_markup_candidates(
            db, owner=owner, job_id=job_id,
        )
    if "views" in actions:
        reconciled += expire_stale_studio_view_reservations(
            db, owner=owner, job_id=job_id,
        )
        reconciled += expire_stale_studio_view_candidates(
            db, owner=owner, job_id=job_id,
        )
    if "angles" in actions:
        reconciled += expire_stale_studio_visual_angle_reservations(
            db, owner=owner, job_id=job_id,
        )
        reconciled += expire_stale_studio_visual_angle_sets(
            db, owner=owner, job_id=job_id,
        )
    if "present" in actions:
        reconciled += expire_stale_studio_presentation_candidates(
            db, owner=owner, job_id=job_id,
        )
    return reconciled

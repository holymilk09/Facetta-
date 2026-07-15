"""Cross-store authority for one-output Studio Refine jobs."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from facetta.db import (
    PreviewCandidateRecord,
    StudioJobRecord,
    StudioMarkupCandidateRecord,
)


class StudioPreviewJobBindingConflict(ValueError):
    """One Studio job is ambiguously bound to multiple preview stores."""


def require_single_preview_job_output(
    db: Session,
    *,
    studio_job_id: str | None,
    expected_candidate_id: str,
) -> None:
    """Lock and verify the only preview output owned by a Refine job.

    Each candidate table has its own unique job constraint, so historical
    data can still bind the same job once in both stores. A terminal decision
    must never settle, bill, or append truth while that ambiguity exists.
    """

    if studio_job_id is None:
        return
    job = db.scalar(
        select(StudioJobRecord)
        .where(StudioJobRecord.id == studio_job_id)
        .with_for_update()
    )
    preview_ids = list(
        db.scalars(
            select(PreviewCandidateRecord.id)
            .where(PreviewCandidateRecord.studio_job_id == studio_job_id)
            .with_for_update()
        )
    )
    markup_ids = list(
        db.scalars(
            select(StudioMarkupCandidateRecord.id)
            .where(StudioMarkupCandidateRecord.studio_job_id == studio_job_id)
            .with_for_update()
        )
    )
    bound_ids = preview_ids + markup_ids
    if (
        job is None
        or len(bound_ids) != 1
        or bound_ids[0] != expected_candidate_id
    ):
        raise StudioPreviewJobBindingConflict(
            "the Studio Refine job is ambiguously bound to preview outputs"
        )

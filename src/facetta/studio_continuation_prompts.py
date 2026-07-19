"""Append-only user prompt history for the existing Studio Refine seam."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from facetta.db import (
    Project,
    StudioContinuationPromptRecord,
    new_id,
    utcnow,
)
from facetta.json_types import JsonObject


class StudioContinuationPromptError(RuntimeError):
    """The prompt cannot be bound to the requested project/revision."""


@dataclass(frozen=True)
class StudioContinuationPrompt:
    prompt_id: str
    sequence: int
    owner: str
    project_root_id: str
    source_asset_id: str
    source_sha256: str
    prompt: str
    intent: JsonObject
    studio_job_id: str | None
    created_at: datetime


def _prompt(record: StudioContinuationPromptRecord) -> StudioContinuationPrompt:
    return StudioContinuationPrompt(
        prompt_id=record.id,
        sequence=record.sequence,
        owner=record.owner,
        project_root_id=record.project_root_id,
        source_asset_id=record.source_asset_id,
        source_sha256=record.source_sha256,
        prompt=record.prompt,
        intent=record.intent,
        studio_job_id=record.studio_job_id,
        created_at=record.created_at,
    )


def append_studio_continuation_prompt(
    db: Session,
    *,
    owner: str,
    project_root_id: str,
    source_asset_id: str,
    source_sha256: str,
    prompt: str,
    intent: JsonObject,
    studio_job_id: str | None,
) -> StudioContinuationPrompt:
    """Append one valid user request before provider work begins.

    Locking the project makes the owner-local sequence deterministic on
    Postgres.  A bounded retry covers SQLite and any database that reports a
    concurrent sequence insert after the lock was acquired.
    """

    visible_prompt = prompt.strip()
    if not visible_prompt:
        raise StudioContinuationPromptError(
            "a continuation prompt must preserve user-authored text"
        )
    for attempt in range(2):
        project = db.scalar(
            select(Project)
            .where(
                Project.root_id == project_root_id,
                Project.owner == owner,
            )
            .with_for_update()
        )
        if project is None:
            raise StudioContinuationPromptError(
                "the Studio project is unavailable"
            )
        latest = db.scalar(select(func.max(
            StudioContinuationPromptRecord.sequence
        )).where(
            StudioContinuationPromptRecord.project_root_id == project_root_id,
            StudioContinuationPromptRecord.owner == owner,
        )) or 0
        record = StudioContinuationPromptRecord(
            id=new_id("scp"),
            owner=owner,
            project_root_id=project_root_id,
            source_asset_id=source_asset_id,
            source_sha256=source_sha256,
            sequence=latest + 1,
            prompt=visible_prompt,
            intent=intent,
            studio_job_id=studio_job_id,
            created_at=utcnow(),
        )
        db.add(record)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            if attempt == 0 and studio_job_id is None:
                continue
            raise StudioContinuationPromptError(
                "the continuation prompt could not be appended in order"
            ) from exc
        return _prompt(record)
    raise StudioContinuationPromptError(
        "the continuation prompt could not be appended in order"
    )


def list_studio_continuation_prompts(
    db: Session,
    *,
    owner: str,
    project_root_id: str,
) -> list[StudioContinuationPrompt]:
    """Return the designer's raw prompts in stable chronological order."""

    records = db.scalars(select(StudioContinuationPromptRecord).where(
        StudioContinuationPromptRecord.owner == owner,
        StudioContinuationPromptRecord.project_root_id == project_root_id,
    ).order_by(
        StudioContinuationPromptRecord.sequence,
        StudioContinuationPromptRecord.created_at,
        StudioContinuationPromptRecord.id,
    ))
    return [_prompt(record) for record in records]

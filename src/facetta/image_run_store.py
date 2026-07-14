"""Append-only persistence adapter for image-agent execution evidence."""

from __future__ import annotations

from sqlalchemy.orm import Session

from facetta.db import ImageAttempt, ImageRun, new_id
from facetta.image_agent import (
    ImageAgentError,
    ImageAgentPlan,
    ImageAgentResult,
    ImageAttemptSummary,
)


def _attempt_row(run_id: str, attempt: ImageAttemptSummary) -> ImageAttempt:
    return ImageAttempt(
        id=new_id("iat"),
        run_id=run_id,
        attempt_number=attempt.attempt_number,
        provider=attempt.provider,
        model=attempt.model,
        latency_ms=attempt.latency_ms,
        cached=attempt.cached,
        provider_request_id=attempt.provider_request_id,
        qa_verdict=(attempt.qa_verdict.value if attempt.qa_verdict else None),
        qa_checks=[
            check.model_dump(mode="json") for check in attempt.qa_checks
        ],
        corrective_instruction=attempt.corrective_instruction,
        fallback_reason=attempt.fallback_reason,
        output_hash=attempt.output_hash,
        prompt_hash=attempt.prompt_hash,
        cache_key=attempt.cache_key,
        usage=attempt.usage or {},
        cost=attempt.cost,
        error_category=(attempt.error_category.value
                        if attempt.error_category else None),
    )


def persist_image_agent_result(
    db: Session,
    result: ImageAgentResult,
    *,
    project_root_id: str | None = None,
    source_asset_id: str | None = None,
    accepted_asset_id: str | None = None,
    created_by: str = "usr_pending",
    status_override: str | None = None,
    error_category_override: str | None = None,
    commit: bool = True,
) -> str:
    """Store one immutable run and every attempt without candidate bytes.

    ``status_override`` is reserved for workflows where QA passed but product
    promotion still requires an explicit designer action (for example a
    temporary catalog preview).  Attempt verdicts remain the evaluator truth.
    ``error_category_override`` lets a product gate record its terminal
    classification in that same initial insert rather than rewriting the run.
    """
    run_id = new_id("run")
    run = ImageRun(
        id=run_id,
        project_root_id=project_root_id,
        source_asset_id=source_asset_id,
        operation=result.plan.operation.value,
        normalized_intent=result.plan.normalized_intent,
        prompt_version=result.plan.prompt_version,
        input_hash=result.plan.input_hash,
        source_hash=result.plan.source_hash,
        mask_hash=result.plan.mask_hash,
        spec_visual_hash=result.plan.spec_visual_hash,
        source_spec_visual_hash=result.plan.source_spec_visual_hash,
        variant=result.plan.variant,
        status=status_override or result.run.status.value,
        accepted_asset_id=(accepted_asset_id if result.accepted else None),
        error_category=(
            error_category_override
            if error_category_override is not None
            else (
                result.run.error_category.value
                if result.run.error_category else None
            )
        ),
        created_by=created_by,
    )
    attempts = [_attempt_row(run_id, attempt)
                for attempt in result.run.attempts]
    db.add_all([run, *attempts])
    if commit:
        db.commit()
    else:
        db.flush()
    return run_id


def persist_image_agent_failure(
    db: Session,
    plan: ImageAgentPlan,
    error: ImageAgentError,
    *,
    project_root_id: str | None = None,
    source_asset_id: str | None = None,
    created_by: str = "usr_pending",
    commit: bool = True,
) -> str:
    """Record a terminal provider/evaluator/quality failure without bytes."""
    run_id = new_id("run")
    db.add(ImageRun(
        id=run_id,
        project_root_id=project_root_id,
        source_asset_id=source_asset_id,
        operation=plan.operation.value,
        normalized_intent=plan.normalized_intent,
        prompt_version=plan.prompt_version,
        input_hash=plan.input_hash,
        source_hash=plan.source_hash,
        mask_hash=plan.mask_hash,
        spec_visual_hash=plan.spec_visual_hash,
        source_spec_visual_hash=plan.source_spec_visual_hash,
        variant=plan.variant,
        status="failed",
        accepted_asset_id=None,
        error_category=error.category.value,
        created_by=created_by,
    ))
    db.add_all([_attempt_row(run_id, attempt) for attempt in error.attempts])
    if commit:
        db.commit()
    else:
        db.flush()
    return run_id

"""Regression coverage for immutable image-agent evidence persistence."""

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from facetta.db import ImageAttempt, ImageRun
from facetta.image_agent import (
    ImageAgentPlan,
    ImageAgentResult,
    ImageAttemptSummary,
    ImageOperation,
    ImageQualityFailure,
    ImageQualityReport,
    ImageRoute,
    ImageRunStatus,
    ImageRunSummary,
    QualityVerdict,
)
from facetta.image_run_store import (
    persist_image_agent_failure,
    persist_image_agent_result,
)


def _multi_attempt_result() -> ImageAgentResult:
    plan = ImageAgentPlan(
        operation=ImageOperation.CREATIVE_GENERATE,
        intent="a sculptural aquamarine ring",
        normalized_intent={"brief": "a sculptural aquamarine ring"},
        prompt_version="creative-v1",
        spec_facts={},
        spec_visual_hash="s" * 64,
        expected_output="jewelry render",
        input_hash="i" * 64,
    )
    attempts = (
        ImageAttemptSummary(
            attempt_number=1,
            route=ImageRoute.GROK_GENERATE,
            provider="xai",
            model="grok-imagine",
            latency_ms=120,
            qa_verdict=QualityVerdict.FAIL,
            prompt_hash="1" * 64,
            cache_key="a" * 64,
        ),
        ImageAttemptSummary(
            attempt_number=2,
            route=ImageRoute.GROK_GENERATE,
            provider="xai",
            model="grok-imagine",
            latency_ms=95,
            qa_verdict=QualityVerdict.PASS,
            prompt_hash="2" * 64,
            cache_key="b" * 64,
        ),
    )
    run = ImageRunSummary(
        status=ImageRunStatus.ACCEPTED,
        operation=plan.operation,
        normalized_intent=plan.normalized_intent,
        prompt_version=plan.prompt_version,
        spec_visual_hash=plan.spec_visual_hash,
        variant=plan.variant,
        verdict=QualityVerdict.PASS,
        attempts=attempts,
        selected_attempt=2,
        output_hash="o" * 64,
    )
    return ImageAgentResult(
        plan=plan,
        run=run,
        image_bytes=b"candidate-image",
        quality=ImageQualityReport(
            verdict=QualityVerdict.PASS,
            checks=(),
        ),
        accepted=True,
        review_required=False,
    )


def test_result_flushes_run_before_multiple_attempts_with_foreign_keys():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    ImageRun.__table__.create(engine)
    ImageAttempt.__table__.create(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)

    with sessions() as db:
        run_id = persist_image_agent_result(
            db,
            _multi_attempt_result(),
            commit=False,
        )
        db.commit()

    with sessions() as db:
        run = db.get(ImageRun, run_id)
        attempts = db.scalars(
            select(ImageAttempt)
            .where(ImageAttempt.run_id == run_id)
            .order_by(ImageAttempt.attempt_number)
        ).all()

        assert run is not None
        assert run.status == "accepted"
        assert [attempt.attempt_number for attempt in attempts] == [1, 2]
        assert [attempt.qa_verdict for attempt in attempts] == ["fail", "pass"]


def test_failure_flushes_run_before_multiple_attempts_with_foreign_keys():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    ImageRun.__table__.create(engine)
    ImageAttempt.__table__.create(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    result = _multi_attempt_result()
    error = ImageQualityFailure(
        "all candidates failed QA",
        report=result.quality,
        attempts=result.run.attempts,
        plan=result.plan,
    )

    with sessions() as db:
        run_id = persist_image_agent_failure(
            db,
            result.plan,
            error,
            commit=False,
        )
        db.commit()

    with sessions() as db:
        run = db.get(ImageRun, run_id)
        attempts = db.scalars(
            select(ImageAttempt)
            .where(ImageAttempt.run_id == run_id)
            .order_by(ImageAttempt.attempt_number)
        ).all()

        assert run is not None
        assert run.status == "failed"
        assert run.error_category == "quality"
        assert [attempt.attempt_number for attempt in attempts] == [1, 2]


def test_commit_false_result_is_removed_by_outer_rollback():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    ImageRun.__table__.create(engine)
    ImageAttempt.__table__.create(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)

    with sessions() as db:
        persist_image_agent_result(
            db,
            _multi_attempt_result(),
            commit=False,
        )
        assert db.scalar(select(func.count()).select_from(ImageRun)) == 1
        assert db.scalar(select(func.count()).select_from(ImageAttempt)) == 2
        db.rollback()

    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(ImageRun)) == 0
        assert db.scalar(select(func.count()).select_from(ImageAttempt)) == 0

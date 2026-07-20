"""Provider failure evidence stays useful after the HTTP response is gone."""

from __future__ import annotations

import json

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from facetta.api.error_mapping import image_agent_error_response
from facetta.db import Base, ImageAttempt
from facetta.image_agent import (
    ImageOperation,
    ImageProviderFailure,
    ImageRoute,
    JewelryImageAgent,
    ProviderCallError,
    build_image_plan,
)
from facetta.image_run_store import persist_image_agent_failure


class FailingProvider:
    def execute(self, *_args, **_kwargs):
        raise ProviderCallError(
            "provider quota is exhausted",
            code="xai_quota_exhausted",
            retryable=False,
            retry_after_seconds=900,
        )


class UnusedEvaluator:
    def evaluate(self, *_args, **_kwargs):
        raise AssertionError("QA must not run after a provider failure")


def test_terminal_provider_cause_is_persisted_and_returned_precisely():
    plan = build_image_plan(
        ImageOperation.CREATIVE_GENERATE,
        "a symmetric ruby necklace",
    )
    try:
        JewelryImageAgent(
            FailingProvider(),
            UnusedEvaluator(),
            attempt_routes=(ImageRoute.GROK_GENERATE,),
            retry_sleep=lambda _seconds: None,
        ).run(plan)
    except ImageProviderFailure as failure:
        error = failure
    else:  # pragma: no cover - protects the test's setup contract
        raise AssertionError("provider failure was expected")

    assert error.code == "xai_quota_exhausted"
    assert error.retryable is False
    response = image_agent_error_response(error)
    body = json.loads(response.body)
    assert body["code"] == "xai_quota_exhausted"
    assert body["retryable"] is False
    assert body["retry_after_seconds"] == 900
    assert response.headers["retry-after"] == "900"

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        persist_image_agent_failure(session, plan, error)
        attempt = session.scalar(select(ImageAttempt))
        assert attempt is not None
        assert attempt.error_code == "xai_quota_exhausted"
        assert attempt.error_message == "provider quota is exhausted"
        assert attempt.error_retryable is False
        assert attempt.retry_after_seconds == 900

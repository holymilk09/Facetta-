"""Structured failures for the image-agent boundary."""

from __future__ import annotations

from collections.abc import Sequence

from facetta.image_agent.contracts import (
    FailureCategory,
    ImageAgentPlan,
    ImageAttemptSummary,
    ImageQualityReport,
)
from facetta.json_types import JsonObject


class ImageAgentError(Exception):
    category: FailureCategory
    default_code = "image_agent_error"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        attempts: Sequence[ImageAttemptSummary] = (),
        plan: ImageAgentPlan | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or self.default_code
        self.attempts = tuple(attempts)
        self.plan = plan

    def as_dict(self) -> JsonObject:
        return {
            "category": self.category.value,
            "code": self.code,
            "message": self.message,
            "attempts": [attempt.model_dump(mode="json") for attempt in self.attempts],
        }


class ImagePlanValidationError(ImageAgentError, ValueError):
    category = FailureCategory.VALIDATION
    default_code = "invalid_image_plan"


class ProviderCallError(ImageAgentError):
    """A single provider call failed. The orchestrator may retry it."""

    category = FailureCategory.PROVIDER
    default_code = "image_provider_call_failed"

    def __init__(self, message: str, *, code: str | None = None,
                 retryable: bool = True) -> None:
        super().__init__(message, code=code)
        self.retryable = retryable


class ImageProviderFailure(ImageAgentError):
    category = FailureCategory.PROVIDER
    default_code = "image_provider_failed"


class ImageEvaluationFailure(ImageAgentError):
    category = FailureCategory.EVALUATION
    default_code = "image_evaluation_failed"


class ImageQualityFailure(ImageAgentError):
    category = FailureCategory.QUALITY
    default_code = "image_quality_failed"

    def __init__(self, message: str, *, report: ImageQualityReport,
                 attempts: Sequence[ImageAttemptSummary] = (),
                 plan: ImageAgentPlan | None = None) -> None:
        super().__init__(message, attempts=attempts, plan=plan)
        self.report = report

    def as_dict(self) -> JsonObject:
        data = super().as_dict()
        data["quality"] = self.report.model_dump(mode="json")
        return data

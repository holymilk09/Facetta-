"""Canonical provider/image-agent error mapping for HTTP boundaries."""

from __future__ import annotations

from fastapi.responses import JSONResponse

from facetta.image_agent import FailureCategory, ImageAgentError
from facetta.json_types import JsonObject
from facetta.render import RenderUnavailable


def render_unavailable_response(error: RenderUnavailable) -> JSONResponse:
    detail = str(error)
    missing_configuration = "_KEY" in detail or "not configured" in detail
    return JSONResponse(
        status_code=503 if missing_configuration else 502,
        content={
            "code": ("provider_not_configured" if missing_configuration
                     else "provider_failure"),
            "category": "provider",
            "error_category": "provider_failure",
            "detail": detail,
            "retryable": not missing_configuration,
        },
    )


def image_agent_error_response(
    error: ImageAgentError,
    *,
    image_run_id: str | None = None,
    extra: JsonObject | None = None,
) -> JSONResponse:
    if error.category in {FailureCategory.VALIDATION, FailureCategory.QUALITY}:
        status = 422
    elif (error.category is FailureCategory.PROVIDER
          and ("_KEY" in error.message or "not configured" in error.message)):
        status = 503
    else:
        status = 502
    content: JsonObject = {
        "code": error.code,
        "category": error.category.value,
        "error_category": f"{error.category.value}_failure",
        "detail": error.message,
        "retryable": status == 502,
        "image_run_id": image_run_id,
        "attempts": [attempt.model_dump(mode="json")
                     for attempt in error.attempts],
    }
    if extra:
        content.update(extra)
    return JSONResponse(status_code=status, content=content)

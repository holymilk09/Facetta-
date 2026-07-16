"""Explicitly opted-in localhost preview-session endpoint."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict

from facetta.local_preview_auth import (
    LOCAL_PREVIEW_SUBJECT,
    issue_local_preview_credential,
    local_preview_request_allowed,
)


router = APIRouter(prefix="/auth", tags=["local-preview-auth"])


class LocalPreviewSessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    access_token: str
    expires_at: datetime
    token_type: Literal["bearer"] = "bearer"
    designer_id: str


@router.post(
    "/local-preview-session",
    response_model=LocalPreviewSessionResponse,
    status_code=201,
)
async def create_local_preview_session(
    request: Request,
    response: Response,
) -> LocalPreviewSessionResponse:
    # The router is conditionally mounted, and this second check ensures an
    # environment change or non-loopback request still fails as an absent route.
    if not local_preview_request_allowed(request):
        raise HTTPException(status_code=404, detail="Not Found")
    token, expires_at = issue_local_preview_credential()
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Pragma"] = "no-cache"
    return LocalPreviewSessionResponse(
        access_token=token,
        expires_at=expires_at,
        designer_id=LOCAL_PREVIEW_SUBJECT,
    )

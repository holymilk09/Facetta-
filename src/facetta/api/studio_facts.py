"""Authenticated Studio transport for atomic designer fact revisions."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from facetta.api.projects import project_detail
from facetta.auth import (
    AuthenticatedPrincipal,
    principal_actor,
    require_principal_boundary,
)
from facetta.db import Project, get_db
from facetta.json_types import JsonValue
from facetta.studio_fact_revision import (
    StudioFactRevisionError,
    apply_studio_fact_revision,
)


router = APIRouter(
    prefix="/studio",
    tags=["studio"],
    dependencies=[Depends(require_principal_boundary)],
)
DbSession = Annotated[Session, Depends(get_db)]
PrincipalDep = Annotated[
    AuthenticatedPrincipal,
    Depends(require_principal_boundary),
]


class StudioFactChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: Annotated[str, Field(min_length=1, max_length=80)]
    value: JsonValue


class ReviseStudioFactsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_active_asset_id: Annotated[
        str, Field(min_length=1, max_length=32)
    ]
    expected_design_version: Annotated[int, Field(ge=1)]
    created_by: Annotated[str, Field(min_length=1, max_length=32)]
    changes: Annotated[
        list[StudioFactChangeRequest], Field(min_length=1, max_length=12)
    ]

    @model_validator(mode="after")
    def require_unique_paths(self) -> "ReviseStudioFactsRequest":
        paths = [change.path for change in self.changes]
        if len(paths) != len(set(paths)):
            raise ValueError("fact change paths must be unique")
        return self


def _fact_revision_http_error(exc: StudioFactRevisionError) -> HTTPException:
    if exc.code == "fact_revision_unavailable":
        status_code = 404
        category = "not_found"
    elif exc.code == "stale_fact_revision":
        status_code = 409
        category = "conflict"
    else:
        status_code = 422
        category = "validation_failure"
    return HTTPException(
        status_code=status_code,
        detail={
            "code": exc.code,
            "error_category": category,
            "detail": exc.detail,
        },
    )


def _designer_project_detail(db: Session, project: Project) -> dict:
    """Return canonical lineage without operational or production internals."""

    detail = project_detail(db, project)
    for key in (
        "approval",
        "factory_ready",
        "factory_blockers",
        "has_factory_drawing",
        "image_run_ids",
    ):
        detail.pop(key, None)
    return detail


@router.post("/projects/{project_root_id}/facts/revise")
def revise_studio_facts(
    project_root_id: str,
    request: ReviseStudioFactsRequest,
    db: DbSession,
    principal: PrincipalDep,
) -> dict:
    """Append safe designer facts to exact immutable Studio lineage."""

    actor = principal_actor(principal, request.created_by)
    try:
        result = apply_studio_fact_revision(
            db,
            project_root_id=project_root_id,
            expected_active_asset_id=request.expected_active_asset_id,
            expected_design_version=request.expected_design_version,
            changes={change.path: change.value for change in request.changes},
            created_by=actor,
        )
    except StudioFactRevisionError as exc:
        raise _fact_revision_http_error(exc) from exc

    project = db.get(Project, result.project_root_id)
    if project is None:
        # The domain transaction owns this invariant. Avoid leaking persistence
        # details if the canonical row disappears after it returns.
        raise HTTPException(
            status_code=404,
            detail={
                "code": "fact_revision_unavailable",
                "error_category": "not_found",
                "detail": "the active Studio project is unavailable",
            },
        )
    return {
        "status": result.status,
        "project_root_id": result.project_root_id,
        "source_asset_id": result.source_asset_id,
        "asset_id": result.asset_id,
        "design_id": result.design_id,
        "previous_design_version": result.previous_design_version,
        "design_version": result.design_version,
        "spec_change": list(result.spec_change),
        "project_detail": _designer_project_detail(db, project),
    }

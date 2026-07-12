"""AI-first Studio branching, immutable history, and restoration APIs."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from facetta.api.projects import project_card, project_detail
from facetta.db import (
    DesignFamily,
    ImageAsset,
    Project,
    ProjectRevisionRecord,
    get_db,
)
from facetta.project_backbone import is_primary_revision
from facetta.studio_history import (
    StudioHistoryError,
    fork_project_variation,
    restore_project_revision,
)


router = APIRouter(prefix="/studio", tags=["studio"])
DbSession = Annotated[Session, Depends(get_db)]


class SaveVariationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created_by: Annotated[str, Field(min_length=1, max_length=32)]
    expected_active_asset_id: Annotated[str, Field(min_length=1, max_length=32)]
    expected_design_version: Annotated[int, Field(ge=1)] | None = None
    label: Annotated[str, Field(min_length=1, max_length=120)]


class RestoreRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created_by: Annotated[str, Field(min_length=1, max_length=32)]
    expected_active_asset_id: Annotated[str, Field(min_length=1, max_length=32)]
    expected_design_version: Annotated[int, Field(ge=1)] | None = None


def _error(exc: StudioHistoryError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={
        "code": exc.code,
        "category": (
            "stale_version" if exc.code.startswith("stale_")
            else "validation" if exc.status_code == 422
            else "conflict"
        ),
        "detail": exc.detail,
    })


@router.post("/projects/{project_root_id}/variations", status_code=201)
def save_as_variation(
    project_root_id: str,
    request: SaveVariationRequest,
    db: DbSession,
):
    try:
        result = fork_project_variation(
            db,
            project_root_id=project_root_id,
            source_asset_id=request.expected_active_asset_id,
            expected_active_asset_id=request.expected_active_asset_id,
            expected_design_version=request.expected_design_version,
            variation_label=request.label,
            created_by=request.created_by,
        )
    except StudioHistoryError as exc:
        return _error(exc)
    project = db.get(Project, result.project_root_id)
    if project is None:  # pragma: no cover - transaction invariant
        raise HTTPException(status_code=500, detail="variation project not found")
    return {
        "status": "variation_created",
        "family_id": result.family_id,
        "variation_index": result.variation_index,
        "source_project_id": project.branched_from_project_root_id,
        "source_asset_id": project.branched_from_asset_id,
        "project": project_detail(db, project),
    }


@router.post(
    "/projects/{project_root_id}/revisions/{asset_id}/restore",
    status_code=201,
)
def restore_revision(
    project_root_id: str,
    asset_id: str,
    request: RestoreRevisionRequest,
    db: DbSession,
):
    try:
        result = restore_project_revision(
            db,
            project_root_id=project_root_id,
            restore_asset_id=asset_id,
            expected_active_asset_id=request.expected_active_asset_id,
            expected_design_version=request.expected_design_version,
            created_by=request.created_by,
        )
    except StudioHistoryError as exc:
        return _error(exc)
    project = db.get(Project, project_root_id)
    if project is None:  # pragma: no cover - transaction invariant
        raise HTTPException(status_code=500, detail="restored project not found")
    return {
        "status": "restored_as_new_revision",
        "restored_from_asset_id": result.restored_from_asset_id,
        "new_asset_id": result.asset_id,
        "new_design_version": result.design_version,
        "spec_change": list(result.spec_change),
        "project": project_detail(db, project),
    }


@router.get("/projects/{project_root_id}/history")
def studio_history(project_root_id: str, db: DbSession):
    project = db.get(Project, project_root_id)
    if project is None:
        raise HTTPException(status_code=404,
                            detail=f"unknown project '{project_root_id}'")
    chain = list(db.scalars(
        select(ImageAsset)
        .where(ImageAsset.root_id == project_root_id)
        .order_by(ImageAsset.created_at, ImageAsset.id)
    ))
    chain.sort(key=lambda asset: (
        asset.id != project_root_id, asset.created_at, asset.id,
    ))
    primary = [asset for asset in chain if is_primary_revision(asset)]
    records = {
        record.asset_id: record for record in db.scalars(
            select(ProjectRevisionRecord)
            .where(ProjectRevisionRecord.asset_id.in_(
                [asset.id for asset in primary]
            ))
        )
    } if primary else {}
    return {
        "project_id": project_root_id,
        "family_id": project.family_id,
        "variation_index": project.variation_index,
        "variation_label": project.variation_label,
        "active_asset_id": primary[-1].id if primary else None,
        "revisions": [{
            "revision": index,
            "asset_id": asset.id,
            "parent_asset_id": asset.parent_asset_id,
            "design_version": asset.design_version,
            "capability": asset.capability,
            "image_url": f"/assets/{asset.id}/image",
            "pinned": asset.pinned_at is not None,
            "action": (
                records[asset.id].action if asset.id in records
                else "created" if index == 1 else "edit"
            ),
            "raw_intent": (
                records[asset.id].raw_intent if asset.id in records else {
                    "kind": "legacy_or_pre_studio",
                    "instruction": asset.instruction,
                }
            ),
            "interpretation": (
                records[asset.id].interpretation if asset.id in records else {}
            ),
            "change_summary": (
                records[asset.id].change_summary if asset.id in records
                else asset.instruction or (
                    "Initial variation" if index == 1 else "Applied design edit"
                )
            ),
            "restored_from_asset_id": (
                records[asset.id].restored_from_asset_id
                if asset.id in records else None
            ),
            "created_by": asset.created_by,
            "created_at": asset.created_at.isoformat(),
        } for index, asset in enumerate(primary, start=1)],
    }


def _design_family_detail(db: Session, family: DesignFamily) -> dict:
    projects = list(db.scalars(
        select(Project)
        .where(Project.family_id == family.id)
        .order_by(Project.variation_index, Project.created_at)
    ))
    return {
        "family_id": family.id,
        "owner": family.owner,
        "title": family.title,
        "created_at": family.created_at.isoformat(),
        "updated_at": family.updated_at.isoformat(),
        "variations": [{
            **project_card(db, project),
            "variation_index": project.variation_index,
            "variation_label": project.variation_label,
            "branched_from_project_root_id": (
                project.branched_from_project_root_id
            ),
            "branched_from_asset_id": project.branched_from_asset_id,
        } for project in projects],
    }


@router.get("/families")
def list_design_families(db: DbSession, owner: str | None = None):
    """List Studio families without flattening their variation boundaries."""

    query = select(DesignFamily)
    if owner is not None:
        query = query.where(DesignFamily.owner == owner)
    families = list(db.scalars(
        query.order_by(DesignFamily.updated_at.desc(), DesignFamily.id)
    ))
    return {
        "families": [_design_family_detail(db, family) for family in families],
    }


@router.get("/families/{family_id}")
def get_design_family(family_id: str, db: DbSession):
    family = db.get(DesignFamily, family_id)
    if family is None:
        raise HTTPException(status_code=404,
                            detail=f"unknown design family '{family_id}'")
    return _design_family_detail(db, family)

"""Versioned design records. Versions are immutable: any edit creates a new
version; prior versions are untouched and permanently addressable. There is
deliberately no update route on a version."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from facetta.db import Comment, Design, DesignVersion, get_db, new_id, utcnow
from facetta.spec import Spec
from facetta.svg_sheet import SheetUnsupported, render_sheet
from facetta.validation import validate_spec
from facetta.vocabulary import get_vocabulary

router = APIRouter(prefix="/designs", tags=["designs"])

DbSession = Annotated[Session, Depends(get_db)]


class DesignSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created_by: str
    spec: Spec


class CommentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    author: str
    view: Literal["top", "side", "sheet"]
    x_pct: Annotated[float, Field(ge=0, le=100)]
    y_pct: Annotated[float, Field(ge=0, le=100)]
    body: Annotated[str, Field(min_length=1, max_length=4000)]


def _validated_or_response(spec: Spec):
    result = validate_spec(spec, get_vocabulary())
    if not result.ok:
        return None, JSONResponse(
            status_code=422,
            content={"detail": [issue.as_detail() for issue in result.issues]},
        )
    return result.spec, None


def _store_version(db: Session, design: Design, spec: Spec, version: int, created_by: str) -> dict:
    now = utcnow()
    stored = spec.model_dump(mode="json")
    stored.update({
        "design_id": design.id,
        "version": version,
        "created_by": created_by,
        "created_at": now.isoformat().replace("+00:00", "Z"),
    })
    db.add(DesignVersion(design_id=design.id, version=version, spec=stored,
                         created_by=created_by, created_at=now))
    db.commit()
    return stored


def _get_version(db: Session, design_id: str, version: int) -> DesignVersion:
    row = db.get(DesignVersion, (design_id, version))
    if row is None:
        raise HTTPException(status_code=404, detail=f"no version {version} of design '{design_id}'")
    return row


@router.post("", status_code=201)
def create_design(submission: DesignSubmission, db: DbSession):
    spec, error = _validated_or_response(submission.spec)
    if error:
        return error
    design = Design(id=new_id("dsn"), created_by=submission.created_by)
    db.add(design)
    return _store_version(db, design, spec, version=1, created_by=submission.created_by)


@router.post("/{design_id}/versions", status_code=201)
def create_version(design_id: str, submission: DesignSubmission, db: DbSession):
    design = db.get(Design, design_id)
    if design is None:
        raise HTTPException(status_code=404, detail=f"unknown design '{design_id}'")
    spec, error = _validated_or_response(submission.spec)
    if error:
        return error
    latest = db.scalar(
        select(func.max(DesignVersion.version)).where(DesignVersion.design_id == design_id)
    ) or 0
    return _store_version(db, design, spec, version=latest + 1, created_by=submission.created_by)


@router.get("")
def list_designs(db: DbSession):
    rows = db.execute(
        select(Design, func.max(DesignVersion.version))
        .join(DesignVersion, DesignVersion.design_id == Design.id)
        .group_by(Design.id)
        .order_by(Design.created_at)
    ).all()
    return {
        "designs": [
            {
                "design_id": design.id,
                "created_by": design.created_by,
                "created_at": design.created_at,
                "latest_version": latest,
            }
            for design, latest in rows
        ]
    }


@router.get("/{design_id}")
def get_design(design_id: str, db: DbSession):
    design = db.get(Design, design_id)
    if design is None:
        raise HTTPException(status_code=404, detail=f"unknown design '{design_id}'")
    versions = db.scalars(
        select(DesignVersion)
        .where(DesignVersion.design_id == design_id)
        .order_by(DesignVersion.version)
    ).all()
    return {
        "design_id": design.id,
        "created_by": design.created_by,
        "created_at": design.created_at,
        "versions": [
            {"version": v.version, "created_by": v.created_by, "created_at": v.created_at}
            for v in versions
        ],
    }


@router.get("/{design_id}/versions/{version}")
def get_version(design_id: str, version: int, db: DbSession):
    return _get_version(db, design_id, version).spec


@router.get("/{design_id}/versions/{version}/sheet.svg")
def get_sheet(design_id: str, version: int, db: DbSession):
    row = _get_version(db, design_id, version)
    try:
        svg = render_sheet(Spec.model_validate(row.spec))
    except SheetUnsupported as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    return Response(content=svg, media_type="image/svg+xml")


@router.get("/{design_id}/versions/{version}/comments")
def list_comments(design_id: str, version: int, db: DbSession):
    _get_version(db, design_id, version)
    return {"comments": [_comment_json(c) for c in _comments(db, design_id, version)]}


@router.post("/{design_id}/versions/{version}/comments", status_code=201)
def create_comment(design_id: str, version: int, comment: CommentCreate, db: DbSession):
    _get_version(db, design_id, version)
    return add_comment(db, design_id, version, comment)


def _comments(db: Session, design_id: str, version: int):
    return db.scalars(
        select(Comment)
        .where(Comment.design_id == design_id, Comment.version == version)
        .order_by(Comment.created_at, Comment.id)
    ).all()


def _comment_json(c: Comment) -> dict:
    return {
        "id": c.id,
        "design_id": c.design_id,
        "version": c.version,
        "view": c.view,
        "x_pct": c.x_pct,
        "y_pct": c.y_pct,
        "body": c.body,
        "author": c.author,
        "created_at": c.created_at,
    }


def add_comment(db: Session, design_id: str, version: int, comment: CommentCreate) -> dict:
    row = Comment(design_id=design_id, version=version, view=comment.view,
                  x_pct=comment.x_pct, y_pct=comment.y_pct,
                  body=comment.body, author=comment.author)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _comment_json(row)

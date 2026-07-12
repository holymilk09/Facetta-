"""Share links. A link always points to (design_id, version) — never to
'latest' implicitly — so factory and client can rely on a permanent state.
Scope 'view' is read-only; 'comment' additionally allows pinning comments
anchored to a region of the sheet."""

import secrets
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from facetta.api.designs import CommentCreate, _comment_json, _comments, _get_version, add_comment
from facetta.db import ShareLink, get_db
from facetta.spec import Spec
from facetta.svg_sheet import SheetUnsupported, render_sheet

router = APIRouter(tags=["share"])

DbSession = Annotated[Session, Depends(get_db)]


class ShareCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: Literal["view", "comment"] = "comment"


@router.post(
    "/designs/{design_id}/versions/{version}/share",
    status_code=201,
    deprecated=True,
)
def create_share_link(design_id: str, version: int, share: ShareCreate, db: DbSession):
    _get_version(db, design_id, version)
    link = ShareLink(token=secrets.token_urlsafe(16), design_id=design_id,
                     version=version, scope=share.scope)
    db.add(link)
    db.commit()
    return {
        "token": link.token,
        "design_id": design_id,
        "version": version,
        "scope": link.scope,
        "path": f"/share/{link.token}",
    }


def _get_link(db: Session, token: str) -> ShareLink:
    link = db.get(ShareLink, token)
    if link is None:
        raise HTTPException(status_code=404, detail="unknown share link")
    return link


@router.get("/share/{token}", deprecated=True)
def open_share_link(token: str, db: DbSession):
    link = _get_link(db, token)
    row = _get_version(db, link.design_id, link.version)
    return {
        "design_id": link.design_id,
        "version": link.version,
        "scope": link.scope,
        "spec": row.spec,
        "comments": [_comment_json(c) for c in _comments(db, link.design_id, link.version)],
    }


@router.get("/share/{token}/sheet.svg", deprecated=True)
def share_sheet(token: str, db: DbSession):
    link = _get_link(db, token)
    row = _get_version(db, link.design_id, link.version)
    try:
        svg = render_sheet(Spec.model_validate(row.spec))
    except SheetUnsupported as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    return Response(content=svg, media_type="image/svg+xml")


@router.post("/share/{token}/comments", status_code=201, deprecated=True)
def share_comment(token: str, comment: CommentCreate, db: DbSession):
    link = _get_link(db, token)
    if link.scope != "comment":
        raise HTTPException(status_code=403, detail="this share link is view-only")
    return add_comment(db, link.design_id, link.version, comment)

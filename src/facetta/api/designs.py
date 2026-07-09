"""Versioned design records. Versions are immutable: any edit creates a new
version; prior versions are untouched and permanently addressable. There is
deliberately no update route on a version."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from facetta.db import (
    Comment, Design, DesignMessage, DesignVersion, get_db, new_id, utcnow,
)
from facetta.dxf import svg_to_dxf
from facetta.spec import Spec
from facetta.svg_sheet import (
    SheetUnsupported, render_sheet, render_stack_sheet, render_true_size_sheet,
)
from facetta.validation import nesting_clearance, validate_spec
from facetta.vocabulary import get_vocabulary

router = APIRouter(prefix="/designs", tags=["designs"])

DbSession = Annotated[Session, Depends(get_db)]


class DesignSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created_by: str
    spec: Spec
    collection: Annotated[str, Field(min_length=1, max_length=80)] | None = None


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
    design = Design(id=new_id("dsn"), created_by=submission.created_by,
                    collection=submission.collection)
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
    if submission.collection is not None:
        design.collection = submission.collection  # regroup the container;
        # versions themselves stay immutable
    latest = db.scalar(
        select(func.max(DesignVersion.version)).where(DesignVersion.design_id == design_id)
    ) or 0
    return _store_version(db, design, spec, version=latest + 1, created_by=submission.created_by)


class EditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instruction: Annotated[str, Field(min_length=1, max_length=2000)]
    created_by: str = "usr_pending"


@router.post("/{design_id}/edit")
def edit_design(design_id: str, body: EditRequest, db: DbSession):
    """The edit loop: a plain-language change on the latest version. Claude
    translates it into an edited spec, the validator gates it, and only a
    physically real edit is written as a new immutable version. An impossible
    ask comes back with the density correction and NO version is saved —
    conversational editing that cannot ship a wrong stone."""
    from facetta.agent import plan_edit
    from facetta.prose import ProseUnavailable

    design = db.get(Design, design_id)
    if design is None:
        raise HTTPException(status_code=404, detail=f"unknown design '{design_id}'")
    latest = db.scalar(
        select(func.max(DesignVersion.version)).where(
            DesignVersion.design_id == design_id))
    if latest is None:
        raise HTTPException(status_code=404, detail=f"design '{design_id}' has no versions")
    current = Spec.model_validate(_get_version(db, design_id, latest).spec)

    try:
        result = plan_edit(body.instruction, current)
    except ProseUnavailable as exc:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    validated = validate_spec(result.spec, get_vocabulary())
    if not validated.ok:
        # the edit is physically impossible — surface the correction, save nothing
        return JSONResponse(status_code=422, content={
            "detail": [issue.as_detail() for issue in validated.issues],
            "message": result.message,
            "changed_fields": result.changed_fields,
            "rejected": True,
        })
    stored = _store_version(db, design, validated.spec, latest + 1, body.created_by)
    return {
        "new_version": latest + 1,
        "changed_fields": result.changed_fields,
        "isolate_ref": result.isolate_ref,
        "message": result.message,
        "spec": stored,
    }


@router.get("")
def list_designs(db: DbSession, collection: str | None = None):
    query = (
        select(Design, func.max(DesignVersion.version))
        .join(DesignVersion, DesignVersion.design_id == Design.id)
        .group_by(Design.id)
        .order_by(Design.created_at)
    )
    if collection is not None:
        query = query.where(Design.collection == collection)
    rows = db.execute(query).all()
    designs = []
    for design, latest in rows:
        row = db.get(DesignVersion, (design.id, latest))
        spec = row.spec if row else {}
        stone = spec.get("stone") or {}
        designs.append({
            "design_id": design.id,
            "created_by": design.created_by,
            "created_at": design.created_at,
            "latest_version": latest,
            "collection": design.collection,
            "jewelry_type": spec.get("jewelry_type"),
            "template": spec.get("template"),
            "summary": (f"{stone.get('carat', '?')} ct {stone.get('species', '')} "
                        f"{(stone.get('cut') or '').replace('_', ' ')}").strip(),
        })
    return {"designs": designs}


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
def get_sheet(design_id: str, version: int, db: DbSession,
              highlight: str | None = None):
    """?highlight=A rings that stone in red — the edit agent's isolate mark."""
    row = _get_version(db, design_id, version)
    try:
        svg = render_sheet(Spec.model_validate(row.spec), highlight_ref=highlight)
    except SheetUnsupported as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    return Response(content=svg, media_type="image/svg+xml")


@router.get("/{design_id}/versions/{version}/blueprint-sheet.svg")
def get_blueprint_sheet(design_id: str, version: int, db: DbSession,
                        model: str = "grok_imagine"):
    """The stored version's presentation blueprint: painted views, code-drawn
    numbers. The crisp master stays at .../sheet.svg."""
    from facetta.blueprint import render_blueprint_sheet
    from facetta.render import RenderUnavailable

    row = _get_version(db, design_id, version)
    try:
        svg, cached = render_blueprint_sheet(Spec.model_validate(row.spec), model)
    except SheetUnsupported as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except RenderUnavailable as exc:
        status = 503 if "_KEY" in str(exc) else 502
        return JSONResponse(status_code=status, content={"detail": str(exc)})
    return Response(content=svg, media_type="image/svg+xml",
                    headers={"X-Render-Cache": "hit" if cached else "miss"})


@router.get("/{design_id}/versions/{version}/true_size.svg")
def get_true_size(design_id: str, version: int, db: DbSession,
                  instructions: bool = True):
    """The stored version's 1:1 overlay page — print at 100% and lay the
    finished piece on the outlines. ?instructions=false for a clean page."""
    row = _get_version(db, design_id, version)
    try:
        svg = render_true_size_sheet(Spec.model_validate(row.spec),
                                     instructions=instructions)
    except SheetUnsupported as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    return Response(content=svg, media_type="image/svg+xml")


@router.get("/{design_id}/versions/{version}/plate.svg")
def get_plate(design_id: str, version: int, db: DbSession, paper: str = "ivory"):
    """The stored version's presentation plate — the client-facing page."""
    from facetta.plate import render_presentation_plate

    row = _get_version(db, design_id, version)
    try:
        svg = render_presentation_plate(Spec.model_validate(row.spec), paper=paper)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    return Response(content=svg, media_type="image/svg+xml")


@router.get("/{design_id}/versions/{version}/render.png")
def get_render(design_id: str, version: int, db: DbSession,
               style: str = "photo", lighting: str = "studio"):
    """The stored version's photoreal render — cached by content, so a
    share link serves the identical image every time."""
    from facetta.render import RenderUnavailable, render_finished_image

    row = _get_version(db, design_id, version)
    try:
        png, cached = render_finished_image(Spec.model_validate(row.spec),
                                            style, lighting)
    except RenderUnavailable as exc:
        status = 503 if "_KEY" in str(exc) else 502
        return JSONResponse(status_code=status, content={"detail": str(exc)})
    return Response(content=png, media_type="image/png",
                    headers={"X-Render-Cache": "hit" if cached else "miss"})


@router.get("/{design_id}/versions/{version}/prototype.svg")
def get_prototype(design_id: str, version: int, db: DbSession):
    from facetta.prototype import render_color_preview

    row = _get_version(db, design_id, version)
    try:
        svg = render_color_preview(Spec.model_validate(row.spec))
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    return Response(content=svg, media_type="image/svg+xml")


@router.get("/{design_id}/versions/{version}/stack/{other_id}/{other_version}/sheet.svg")
def get_stack_sheet(design_id: str, version: int, other_id: str, other_version: int,
                    db: DbSession):
    """Overlay two stored versions with their nesting clearance — shareable
    like any other sheet URL."""
    spec_a = Spec.model_validate(_get_version(db, design_id, version).spec)
    spec_b = Spec.model_validate(_get_version(db, other_id, other_version).spec)
    try:
        clearance = nesting_clearance(spec_a, spec_b)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    if not clearance.nests:
        return JSONResponse(status_code=422, content={
            "detail": "these pieces do not nest — negative clearance",
            "clearance": clearance.as_dict(),
        })
    return Response(content=render_stack_sheet(spec_a, spec_b, clearance),
                    media_type="image/svg+xml")


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
    row = Comment(id=new_id("cmt"), design_id=design_id, version=version,
                  view=comment.view, x_pct=comment.x_pct, y_pct=comment.y_pct,
                  body=comment.body, author=comment.author)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _comment_json(row)


# --- factory handoff and discussion -------------------------------------------


@router.get("/{design_id}/versions/{version}/sheet.dxf")
def get_sheet_dxf(design_id: str, version: int, db: DbSession):
    """The stored version's sheet as a DXF R12 drawing for CAD import."""
    row = _get_version(db, design_id, version)
    try:
        svg = render_sheet(Spec.model_validate(row.spec))
    except SheetUnsupported as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    return Response(
        content=svg_to_dxf(svg), media_type="application/dxf",
        headers={"Content-Disposition":
                 f'attachment; filename="{design_id}_v{version}.dxf"'})


class MessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    author: Annotated[str, Field(min_length=1, max_length=120)]
    body: Annotated[str, Field(min_length=1, max_length=4000)]
    author_label: Annotated[str, Field(min_length=1, max_length=120)] | None = None
    version: int | None = None


def _message_json(m: DesignMessage) -> dict:
    return {
        "id": m.id, "design_id": m.design_id, "version": m.version,
        "author": m.author, "author_label": m.author_label,
        "body": m.body, "created_at": m.created_at,
    }


@router.get("/{design_id}/messages")
def list_messages(design_id: str, db: DbSession):
    """The running designer/factory conversation on a design."""
    if db.get(Design, design_id) is None:
        raise HTTPException(status_code=404, detail=f"unknown design '{design_id}'")
    rows = db.execute(
        select(DesignMessage).where(DesignMessage.design_id == design_id)
        .order_by(DesignMessage.created_at, DesignMessage.id)
    ).scalars().all()
    return {"messages": [_message_json(m) for m in rows]}


@router.post("/{design_id}/messages", status_code=201)
def create_message(design_id: str, message: MessageCreate, db: DbSession):
    if db.get(Design, design_id) is None:
        raise HTTPException(status_code=404, detail=f"unknown design '{design_id}'")
    row = DesignMessage(id=new_id("msg"), design_id=design_id, version=message.version,
                        author=message.author, author_label=message.author_label,
                        body=message.body)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _message_json(row)

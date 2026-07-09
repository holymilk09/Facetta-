"""The iteration chain: render → many localized edits → pin → factory drawing.

Designers will always adjust — MODE C is the primary loop, not an edge case.
Every render and every edit is an immutable ImageAsset with a parent, so
history, compare, and revert are chain reads. "Pin for factory" marks the
approved version; the manufacturing technical drawing is generated from the
PINNED asset by default — never silently from "latest" — and only an explicit
override uses the asset the caller named.
"""

from __future__ import annotations

import base64
import binascii
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from facetta.checklist import (
    DEFAULT_MODE, approval_footer_line, build_checklist_items,
    checklist_status,
)
from facetta.db import (
    ApprovalChecklist, ApprovalResponse, DesignVersion, ImageAsset, Project,
    get_db, new_id, utcnow,
)
from facetta.disclaimer import is_stampable, stamp_b64, stamp_image
from facetta.render import RenderUnavailable, _sniff_media_type
from facetta.spec import Spec
from facetta.specagent import (
    SKIN_TONES, SPIN_MOTIONS, VIEW_ANGLES, check_design_consistency,
    generate_spec_sheet, global_restyle, jewelry_render, localized_edit,
    mask_from_markup, read_markup, render_spin_video, render_view_set,
)
from facetta.specdiff import diff_specs, summarize_changes
from facetta.validation import validate_spec
from facetta.vocabulary import get_vocabulary

router = APIRouter(prefix="/assets", tags=["assets"])

DbSession = Annotated[Session, Depends(get_db)]


def _provider_error(exc: RenderUnavailable) -> JSONResponse:
    status = 503 if "_KEY" in str(exc) else 502
    return JSONResponse(status_code=status, content={"detail": str(exc)})


# The gentle accuracy disclaimer is stamped on client-facing photoreal renders.
# A factory technical drawing carries its own dimension-honesty disclaimer, so a
# "preview may vary" caption would undermine it — those are delivered unstamped.
_UNSTAMPED_CAPS = {"MANUFACTURING_TECHNICAL_DRAWING"}


def _client_b64(image_bytes: bytes, *, capability: str | None = None,
                media_type: str = "image/png") -> str:
    """base64 for a client response, with the accuracy disclaimer stamped on
    photoreal renders (never on a factory technical drawing or a video)."""
    if capability in _UNSTAMPED_CAPS or not is_stampable(media_type):
        return base64.b64encode(image_bytes).decode()
    return stamp_b64(image_bytes)


def _get_asset(db: Session, asset_id: str) -> ImageAsset:
    row = db.get(ImageAsset, asset_id)
    if row is None:
        raise HTTPException(status_code=404,
                            detail=f"unknown asset '{asset_id}'")
    return row


def _store_asset(db: Session, image: bytes, capability: str,
                 parent: ImageAsset | None = None, *,
                 instruction: str | None = None, region: str | None = None,
                 drift: float | None = None,
                 created_by: str = "usr_pending") -> ImageAsset:
    asset = ImageAsset(
        id=new_id("ast"),
        root_id=parent.root_id if parent else "",  # set below for roots
        parent_asset_id=parent.id if parent else None,
        capability=capability, instruction=instruction, region=region,
        drift=drift, image=image, media_type=_sniff_media_type(image),
        created_by=created_by)
    if parent is None:
        asset.root_id = asset.id
    db.add(asset)
    db.commit()
    if parent is not None:                       # a new item in an existing chain
        _touch_project(db, asset.root_id)
    return asset


def _ensure_project(db: Session, root: ImageAsset) -> Project:
    """Every chain root files a project into the owner's library (Unfiled until
    the designer organizes it). Idempotent."""
    project = db.get(Project, root.id)
    if project is None:
        title = (root.instruction or "Untitled piece")[:200]
        project = Project(root_id=root.id, owner=root.created_by,
                          collection=None, title=title, tags=[])
        db.add(project)
        db.commit()
    return project


def _touch_project(db: Session, root_id: str) -> None:
    project = db.get(Project, root_id)
    if project is not None:
        project.updated_at = utcnow()
        db.commit()


def _chain(db: Session, root_id: str) -> list[ImageAsset]:
    return list(db.scalars(
        select(ImageAsset).where(ImageAsset.root_id == root_id)
        .order_by(ImageAsset.created_at, ImageAsset.id)))


def _version_number(chain: list[ImageAsset], asset_id: str) -> int:
    for i, a in enumerate(chain, start=1):
        if a.id == asset_id:
            return i
    return 0


def _pinned(chain: list[ImageAsset]) -> ImageAsset | None:
    pinned = [a for a in chain if a.pinned_at is not None]
    return max(pinned, key=lambda a: a.pinned_at) if pinned else None


def _asset_meta(db: Session, asset: ImageAsset) -> dict:
    chain = _chain(db, asset.root_id)
    return {
        "asset_id": asset.id,
        "parent_asset_id": asset.parent_asset_id,
        "root_id": asset.root_id,
        "version": _version_number(chain, asset.id),
        "capability": asset.capability,
        "region": asset.region,
        "drift": asset.drift,
        "pinned": asset.pinned_at is not None,
        "media_type": asset.media_type,
        "created_by": asset.created_by,
        "created_at": asset.created_at.isoformat(),
    }


class AssetRenderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    piece_description: Annotated[str, Field(min_length=3, max_length=600)]
    metal: str = ""
    stones: str = ""
    setting_details: str = ""
    view_angle: str = "three-quarter product view"
    variant: int = 0
    # extra camera angles of the SAME piece, derived from the hero render so
    # the design is identical across views (preset keys or free-text angles)
    angles: Annotated[list[str], Field(max_length=6)] = []
    skin_tone: str | None = None    # for worn/hand angles only
    check_consistency: bool = True  # re-roll a view that drifts from the hero
    # link the chain to a persisted design: markup edits then also move the
    # design's spec, and the factory sheet letters the latest version
    design_id: str | None = None
    created_by: str = "usr_pending"


def _view_children(db: Session, hero: ImageAsset, angles: list[str],
                   created_by: str, skin_tone: str | None = None,
                   check_consistency: bool = True) -> list[dict]:
    """Derive each requested angle from the hero and store it as an
    ANGLE_VIEW child. A view is filed only if it passes BOTH gates: the worn
    single-finger/tasteful-gesture check (a two-finger or rude-gesture render
    must never reach the library or client) AND the design-consistency check
    (a view that drifted the piece — a different stone size, changed halo — is
    not the approved design). A failed view comes back flagged (rejected) with
    its differences so the UI can offer a retry. Returns per-view summaries."""
    out = []
    for view in render_view_set(bytes(hero.image), angles, skin_tone=skin_tone,
                                check_consistency=check_consistency):
        ok = view.get("ok", True)
        consistent = view.get("consistent", True)
        entry = {"angle": view["angle"], "ok": ok, "consistent": consistent,
                 "differences": view.get("differences", []),
                 "issue": view.get("issue", ""), "cached": view["cached"]}
        if ok and consistent:
            child = _store_asset(db, view["image"], "ANGLE_VIEW", hero,
                                 region=view["angle"], created_by=created_by)
            entry["asset_id"] = child.id
            entry["version"] = _version_number(_chain(db, hero.root_id), child.id)
            entry["image_b64"] = stamp_b64(view["image"])
        else:
            # rejected — not filed; surface a preview + the reason, no asset id
            entry["asset_id"] = None
            entry["image_b64"] = (stamp_b64(view["image"])
                                  if view.get("image") else None)
            entry["rejected"] = True
        out.append(entry)
    return out


@router.post("/render", status_code=201)
def create_render_asset(request: AssetRenderRequest, db: DbSession):
    """MODE A into the chain: a new root asset the iteration loop grows from.
    Pass `angles` to also get extra camera views of the same design in one
    request — each is derived from this hero render (design-locked), so the
    designer gets a consistent turntable without re-generating (which would
    invent a different piece per angle)."""
    if request.design_id is not None:
        from facetta.db import Design
        if db.get(Design, request.design_id) is None:
            raise HTTPException(status_code=404,
                                detail=f"unknown design '{request.design_id}'")
    try:
        image, cached = jewelry_render(
            request.piece_description, metal=request.metal,
            stones=request.stones, setting_details=request.setting_details,
            view_angle=request.view_angle, variant=request.variant)
        hero = _store_asset(db, image, "JEWELRY_RENDER",
                            instruction=request.piece_description,
                            created_by=request.created_by)
        if request.design_id is not None:
            hero.design_id = request.design_id  # the root carries the link
            db.commit()
        _ensure_project(db, hero)             # file it into the owner's library
        views = _view_children(db, hero, request.angles, request.created_by,
                               request.skin_tone,
                               request.check_consistency) if request.angles else []
    except RenderUnavailable as exc:
        return _provider_error(exc)
    return {**_asset_meta(db, hero),
            "image_b64": stamp_b64(image), "cached": cached,
            "views": views}


class AssetViewsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    angles: Annotated[list[str], Field(min_length=1, max_length=6)]
    skin_tone: str | None = None
    check_consistency: bool = True
    created_by: str = "usr_pending"


@router.post("/{asset_id}/views", status_code=201)
def add_views(asset_id: str, request: AssetViewsRequest, db: DbSession):
    """Extra camera angles of an EXISTING asset — the same design from new
    viewpoints, design-locked. Useful on a pinned version: get the approved
    piece from four angles for the client without touching the design.
    skin_tone (SKIN_TONES key or free text) applies to worn/hand angles.
    Each view is design-consistency checked against this asset and re-rolled
    on drift (disable with check_consistency=false)."""
    hero = _get_asset(db, asset_id)
    try:
        views = _view_children(db, hero, request.angles, request.created_by,
                               request.skin_tone, request.check_consistency)
    except RenderUnavailable as exc:
        return _provider_error(exc)
    return {"parent_asset_id": hero.id, "known_presets": list(VIEW_ANGLES),
            "known_skin_tones": list(SKIN_TONES), "views": views}


class AssetEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    region_description: Annotated[str, Field(max_length=500)] = ""
    change_instruction: Annotated[str, Field(min_length=1, max_length=2000)]
    mask_base64: str | None = None
    kind: Literal["render", "technical"] = "render"
    created_by: str = "usr_pending"
    variant: int = 0  # regenerate: a fresh take on the SAME edit, not the cache


@router.post("/{asset_id}/localized-edit", status_code=201)
def create_localized_edit(asset_id: str, request: AssetEditRequest,
                          db: DbSession):
    """MODE C on a chain asset: the child records its parent, region, and
    measured drift. No highlighted region → 422 asking for a canvas
    selection; the region is never guessed."""
    parent = _get_asset(db, asset_id)
    if not request.region_description.strip():
        return JSONResponse(status_code=422, content={
            "detail": "select the area on the canvas — a localized edit "
                      "needs a highlighted region, and it is never guessed"})
    mask_bytes = None
    if request.mask_base64:
        try:
            mask_bytes = base64.b64decode(request.mask_base64, validate=True)
        except (binascii.Error, ValueError):
            return JSONResponse(status_code=422, content={
                "detail": "mask_base64 is not valid base64"})
    try:
        result = localized_edit(
            bytes(parent.image), region_description=request.region_description,
            change_instruction=request.change_instruction,
            mask_bytes=mask_bytes, kind=request.kind, variant=request.variant)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except RenderUnavailable as exc:
        return _provider_error(exc)
    asset = _store_asset(
        db, result["image"], "LOCALIZED_EDIT", parent,
        instruction=request.change_instruction,
        region=request.region_description, drift=result["drift"],
        created_by=request.created_by)
    return {**_asset_meta(db, asset),
            "image_b64": (stamp_b64(result["image"])
                          if request.kind == "render"
                          else base64.b64encode(result["image"]).decode()),
            "changed": result["changed"], "frozen": result["frozen"],
            "retried": result["retried"], "drift": result["drift"],
            "cached": result["cached"]}


class MarkupReadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    marked_image_base64: Annotated[str, Field(min_length=1,
                                              max_length=14_000_000)]
    created_by: str = "usr_pending"
    assistant_name: str | None = None


@router.post("/{asset_id}/markup/read")
def markup_read(asset_id: str, request: MarkupReadRequest, db: DbSession):
    """Phase 1 of a markup edit: the agent READS the designer's marks (canvas
    shapes, arrows, freehand handwriting) against the clean render and echoes
    back what it understood — nothing executes here. The designer confirms or
    corrects the echo, then calls markup/apply with the confirmed list: the
    100%-understanding gate. Unreadable or ambiguous marks come back as a 422
    question — a region or intent is never guessed."""
    from facetta.assistant import DEFAULT_ASSISTANT_NAME

    asset = _get_asset(db, asset_id)
    try:
        marked = base64.b64decode(request.marked_image_base64, validate=True)
    except (binascii.Error, ValueError):
        return JSONResponse(status_code=422, content={
            "detail": "marked_image_base64 is not valid base64"})
    try:
        reading = read_markup(bytes(asset.image), marked)
    except RenderUnavailable as exc:
        return _provider_error(exc)

    name = (request.assistant_name or "").strip() or DEFAULT_ASSISTANT_NAME
    if reading["needs_clarification"] or not reading["annotations"]:
        return JSONResponse(status_code=422, content={
            "detail": reading["clarification"]
                      or "no readable marks found — draw on the piece or "
                         "add a note",
            "understood_as": reading["understood_as"],
            "annotations": reading["annotations"],
            "assistant_name": name})

    # the marked upload is filed as an audit leaf — never an edit base
    notes = _store_asset(db, marked, "MARKUP_NOTES", asset,
                         instruction=reading["understood_as"],
                         created_by=request.created_by)
    linked = _linked_design(db, asset)
    return {"markup_asset_id": notes.id, "assistant_name": name,
            "understood_as": reading["understood_as"],
            "annotations": reading["annotations"],
            "design_linked": linked is not None,
            "design_id": linked[0] if linked else None}


class MarkupAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    region_description: Annotated[str, Field(min_length=1, max_length=500)]
    change_instruction: Annotated[str, Field(min_length=1, max_length=2000)]
    target_section: str | None = None
    target_ref: str | None = None
    index: int | None = None
    mask_base64: str | None = None


class MarkupApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    annotations: Annotated[list[MarkupAnnotation], Field(min_length=1,
                                                         max_length=8)]
    markup_asset_id: str | None = None   # phase-1 upload, for mask derivation
    kind: Literal["render", "technical"] = "render"
    update_spec: bool = True
    created_by: str = "usr_pending"
    variant: int = 0  # regenerate: fresh takes on the SAME marks, not the cache


@router.post("/{asset_id}/markup/apply", status_code=201)
def markup_apply(asset_id: str, request: MarkupApplyRequest, db: DbSession):
    """Phase 2: execute the CONFIRMED annotations, sequentially — each child
    is the parent of the next, so every hop keeps its own freeze contract,
    drift measurement, and revert point. Per annotation: the linked design's
    spec moves FIRST through the Grok scoped edit (scope_guard makes touching
    anything else impossible; a physically impossible change skips the
    annotation entirely — image and spec move in lockstep or not at all),
    then the image through the localized-edit contract. One immutable
    DesignVersion per synced change, with the before → after diff. A final
    consistency check against the starting image is ADVISORY — the intended
    changes are real differences; the hard gate is the per-hop drift."""
    from facetta.agent import Annotation, AnnotationUnresolved
    from facetta.grokedit import GrokEditUnavailable, grok_plan_scoped_edit

    asset = _get_asset(db, asset_id)
    start_bytes = bytes(asset.image)

    # a phase-1 canvas upload yields a drift mask (same raster only)
    derived_mask = None
    if request.markup_asset_id:
        notes = db.get(ImageAsset, request.markup_asset_id)
        if notes is not None and notes.capability == "MARKUP_NOTES":
            derived_mask = mask_from_markup(start_bytes, bytes(notes.image))

    linked = _linked_design(db, asset) if request.update_spec else None
    design_id = linked[0] if linked else None
    current_spec = linked[2] if linked else None

    current = asset
    steps: list[dict] = []
    for note in request.annotations:
        step: dict = {"annotation": note.model_dump(exclude={"mask_base64"})}

        # 1) spec first, when linked and the mark names a section
        scoped = None
        if current_spec is not None and (note.target_section or note.target_ref):
            annotation = Annotation(
                ref=note.target_ref, section=note.target_section,
                index=note.index, instruction=note.change_instruction)
            try:
                scoped = grok_plan_scoped_edit(annotation, current_spec)
            except AnnotationUnresolved as exc:
                step["spec_synced"] = False
                step["spec_note"] = str(exc)
            except GrokEditUnavailable as exc:
                status = 503 if "KEY" in str(exc) else 502
                return JSONResponse(status_code=status, content={
                    "detail": str(exc), "steps": steps})
            if scoped is not None:
                validated = validate_spec(scoped.spec, get_vocabulary())
                if not validated.ok:
                    # lockstep rule: an impossible spec change skips the
                    # image edit too — the two never diverge
                    step["rejected"] = True
                    step["detail"] = [i.as_detail() for i in validated.issues]
                    steps.append(step)
                    continue
                scoped_spec = validated.spec

        # 2) the image, through the localized-edit contract
        mask_bytes = derived_mask
        if note.mask_base64:
            try:
                mask_bytes = base64.b64decode(note.mask_base64, validate=True)
            except (binascii.Error, ValueError):
                return JSONResponse(status_code=422, content={
                    "detail": "mask_base64 is not valid base64",
                    "steps": steps})
        try:
            result = localized_edit(
                bytes(current.image),
                region_description=note.region_description,
                change_instruction=note.change_instruction,
                mask_bytes=mask_bytes, kind=request.kind,
                variant=request.variant)
        except ValueError as exc:
            step["rejected"] = True
            step["detail"] = str(exc)
            steps.append(step)
            continue
        except RenderUnavailable as exc:
            return JSONResponse(status_code=502, content={
                "detail": str(exc), "steps": steps})

        child = _store_asset(
            db, result["image"], "LOCALIZED_EDIT", current,
            instruction=note.change_instruction,
            region=note.region_description, drift=result["drift"],
            created_by=request.created_by)
        step.update({"asset_id": child.id,
                     "version": _version_number(_chain(db, asset.root_id),
                                                child.id),
                     "drift": result["drift"], "retried": result["retried"]})

        # 3) one immutable DesignVersion per synced change
        if scoped is not None and current_spec is not None:
            from facetta.api.designs import _store_version
            from facetta.db import Design

            design = db.get(Design, design_id)
            latest = db.scalar(
                select(func.max(DesignVersion.version)).where(
                    DesignVersion.design_id == design_id)) or 0
            before = current_spec.model_dump(mode="json")
            stored = _store_version(db, design, scoped_spec, latest + 1,
                                    request.created_by)
            changes = diff_specs(before, stored)
            step.update({
                "spec_synced": True, "new_spec_version": latest + 1,
                "changed_fields": scoped.changed_fields,
                "ignored_fields": scoped.ignored_fields,
                "changes_summary": summarize_changes(changes)})
            current_spec = scoped_spec
        elif "spec_synced" not in step:
            step["spec_synced"] = False
            if current_spec is None and request.update_spec:
                step["spec_note"] = ("chain not linked to a design — image "
                                     "only (PATCH /assets/{id}/link-design)")

        current = child
        steps.append(step)

    applied = [s for s in steps if s.get("asset_id")]
    consistency = {"checked": False}
    if applied:
        consistency = check_design_consistency(start_bytes,
                                               bytes(current.image))
    return {
        "final_asset_id": current.id if applied else None,
        "root_id": asset.root_id,
        "design_id": design_id,
        "steps": steps,
        "consistency": consistency,
        "image_b64": (stamp_b64(bytes(current.image)) if applied else None),
    }


class AssetRestyleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instruction: Annotated[str, Field(min_length=1, max_length=2000)]
    kind: Literal["render", "technical"] = "render"
    created_by: str = "usr_pending"
    variant: int = 0  # regenerate: a fresh take on the SAME restyle


@router.post("/{asset_id}/global-restyle", status_code=201)
def create_global_restyle(asset_id: str, request: AssetRestyleRequest,
                          db: DbSession):
    """The whole-piece change path: reference-locked, no freeze contract,
    warning instead of a drift gate — parent/child compare and revert are the
    safety net."""
    parent = _get_asset(db, asset_id)
    try:
        result = global_restyle(bytes(parent.image),
                                instruction=request.instruction,
                                kind=request.kind, variant=request.variant)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except RenderUnavailable as exc:
        return _provider_error(exc)
    asset = _store_asset(db, result["image"], "GLOBAL_RESTYLE", parent,
                         instruction=request.instruction,
                         created_by=request.created_by)
    return {**_asset_meta(db, asset),
            "image_b64": (stamp_b64(result["image"])
                          if request.kind == "render"
                          else base64.b64encode(result["image"]).decode()),
            "changed": result["changed"], "frozen": result["frozen"],
            "warning": result["warning"], "cached": result["cached"]}


class AssetVideoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    motion: str = "turntable"
    model: str = "grok_video"
    created_by: str = "usr_pending"


@router.post("/{asset_id}/video", status_code=201)
def create_spin_video(asset_id: str, request: AssetVideoRequest, db: DbSession):
    """A short showcase clip (slow spin) of the piece, from its render —
    design-locked. Stored as a chain child (SPIN_VIDEO) when the mp4 is
    retrievable; the finished clip also lives at a media url the client can
    stream. Presets: turntable / sway / orbit / sparkle."""
    hero = _get_asset(db, asset_id)
    try:
        result = render_spin_video(bytes(hero.image), motion=request.motion,
                                   model=request.model)
    except RenderUnavailable as exc:
        return _provider_error(exc)
    child = None
    if result.data is not None:
        child = _store_asset(db, result.data, "SPIN_VIDEO", hero,
                             instruction=request.motion,
                             created_by=request.created_by)
        child.media_type = "video/mp4"
        db.commit()
    return {
        "parent_asset_id": hero.id,
        "asset_id": child.id if child else None,
        "video_url": result.url or None,
        "duration_seconds": result.duration,
        "video_b64": (base64.b64encode(result.data).decode()
                      if result.data is not None else None),
        "media_type": "video/mp4",
        "cached": result.cached,
        "known_motions": list(SPIN_MOTIONS),
        "note": (None if result.data is not None else
                 "clip generated; mp4 lives at video_url (this server could "
                 "not fetch the media host — stream it client-side)"),
    }


class LinkDesignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    design_id: Annotated[str, Field(min_length=1, max_length=32)]


@router.patch("/{asset_id}/link-design")
def link_design(asset_id: str, request: LinkDesignRequest, db: DbSession):
    """Join an existing chain to the spec universe: sets design_id on the
    chain ROOT (acting on any asset in the chain). Once linked, markup edits
    also move the design's spec and the factory sheet letters the latest
    version automatically."""
    from facetta.db import Design

    asset = _get_asset(db, asset_id)
    if db.get(Design, request.design_id) is None:
        raise HTTPException(status_code=404,
                            detail=f"unknown design '{request.design_id}'")
    root = db.get(ImageAsset, asset.root_id) or asset
    root.design_id = request.design_id
    db.commit()
    return {"root_id": root.id, "design_id": request.design_id,
            "message": f"chain linked to design {request.design_id} — markup "
                       "edits will keep its spec in sync"}


class OrganizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collection: str | None = None   # client / folder name (None leaves as-is)
    title: str | None = None
    tags: list[str] | None = None
    clear_collection: bool = False  # move back to Unfiled


@router.patch("/{asset_id}/organize")
def organize_asset(asset_id: str, request: OrganizeRequest, db: DbSession):
    """File the asset's whole project (chain) — set its collection (client
    folder), title, and tags. Acts on the chain ROOT, so organizing any
    asset organizes the project it belongs to."""
    asset = _get_asset(db, asset_id)
    root = db.get(ImageAsset, asset.root_id)
    project = _ensure_project(db, root)
    if request.clear_collection:
        project.collection = None
    elif request.collection is not None:
        project.collection = request.collection.strip() or None
    if request.title is not None:
        project.title = request.title.strip()[:200] or project.title
    if request.tags is not None:
        project.tags = sorted({t.strip() for t in request.tags if t.strip()})
    project.updated_at = utcnow()
    db.commit()
    return {"root_id": project.root_id, "collection": project.collection,
            "title": project.title, "tags": project.tags}


@router.get("/{asset_id}")
def get_asset(asset_id: str, db: DbSession):
    asset = _get_asset(db, asset_id)
    return {**_asset_meta(db, asset),
            "image_b64": _client_b64(bytes(asset.image),
                                     capability=asset.capability,
                                     media_type=asset.media_type)}


@router.get("/{asset_id}/image")
def get_asset_image(asset_id: str, db: DbSession):
    asset = _get_asset(db, asset_id)
    content = bytes(asset.image)
    if asset.capability not in _UNSTAMPED_CAPS and is_stampable(asset.media_type):
        content = stamp_image(content)
    return Response(content=content, media_type=asset.media_type)


@router.get("/{asset_id}/history")
def get_history(asset_id: str, db: DbSession):
    """The whole chain this asset belongs to, root first — versions, parents,
    per-hop drift, and which version is pinned for factory."""
    asset = _get_asset(db, asset_id)
    chain = _chain(db, asset.root_id)
    pinned = _pinned(chain)
    return {
        "root_id": asset.root_id,
        "factory_source_asset_id": pinned.id if pinned else None,
        "pinned_version": _version_number(chain, pinned.id) if pinned else None,
        "history": [{
            "asset_id": a.id, "version": i,
            "parent_asset_id": a.parent_asset_id,
            "capability": a.capability, "region": a.region,
            "instruction": a.instruction, "drift": a.drift,
            "pinned": a.pinned_at is not None,
            "created_at": a.created_at.isoformat(),
        } for i, a in enumerate(chain, start=1)],
    }


def _linked_design(db: Session, asset: ImageAsset):
    """The chain's bridge to the spec universe: root.design_id → the design's
    LATEST version spec (validated). Returns (design_id, version, Spec) or
    None when the chain is unlinked or the design has no versions."""
    root = db.get(ImageAsset, asset.root_id) or asset
    if not root.design_id:
        return None
    row = db.execute(
        select(DesignVersion)
        .where(DesignVersion.design_id == root.design_id)
        .order_by(DesignVersion.version.desc())
    ).scalars().first()
    if row is None:
        return None
    result = validate_spec(Spec.model_validate(row.spec), get_vocabulary())
    if not result.ok:
        return None
    return root.design_id, row.version, result.spec


def _newest_checklist(db: Session, asset_id: str) -> ApprovalChecklist | None:
    return db.execute(
        select(ApprovalChecklist)
        .where(ApprovalChecklist.asset_id == asset_id)
        .order_by(ApprovalChecklist.created_at.desc(),
                  ApprovalChecklist.id.desc())
    ).scalars().first()


def _checklist_responses(db: Session, checklist_id: str) -> list[ApprovalResponse]:
    return list(db.execute(
        select(ApprovalResponse)
        .where(ApprovalResponse.checklist_id == checklist_id)
        .order_by(ApprovalResponse.id)
    ).scalars())


def _checklist_state(db: Session, checklist: ApprovalChecklist) -> dict:
    responses = _checklist_responses(db, checklist.id)
    return checklist_status(checklist.items, responses)


@router.post("/{asset_id}/pin")
def pin_asset(asset_id: str, db: DbSession):
    """Pin this version for factory: the manufacturing technical drawing is
    generated from the chain's pinned asset, never silently from 'latest'.
    Pinning a new version supersedes the previous pin (latest pin wins).

    Gated by the approval checklist when one exists for this asset (and its
    mode isn't 'optional'): every item must be approved first — the tap-tap
    ritual IS the road to the factory. No checklist → pin behaves as always."""
    asset = _get_asset(db, asset_id)
    checklist = _newest_checklist(db, asset_id)
    if checklist is not None and checklist.mode != "optional":
        status = _checklist_state(db, checklist)
        if not status["all_approved"]:
            return JSONResponse(status_code=409, content={
                "detail": (f"this version has an approval checklist with "
                           f"{len(status['outstanding'])} item(s) outstanding "
                           "— approve them (or answer NO with a change note) "
                           "before pinning"),
                "outstanding": status["outstanding"],
                "checklist_id": checklist.id})
    asset.pinned_at = utcnow()
    db.commit()
    chain = _chain(db, asset.root_id)
    return {"factory_source_asset_id": asset.id,
            "pinned_version": _version_number(chain, asset.id),
            "message": f"Pinned for factory: version "
                       f"{_version_number(chain, asset.id)} of this chain"}


class ChecklistCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec: Spec | None = None      # else resolved via the chain's design link
    mode: Literal["auto_pin", "explicit_pin", "optional"] = DEFAULT_MODE
    created_by: str = "usr_pending"


@router.post("/{asset_id}/checklist", status_code=201)
def create_checklist(asset_id: str, request: ChecklistCreateRequest,
                     db: DbSession):
    """Start the tap-to-approve ritual for this exact version. Items are
    facts derived from the piece's own spec sections — jewelry-type aware by
    construction (a ring asks about its band; a necklace about its chain).
    The spec comes from the body, else the chain's design link; with neither
    there is nothing to derive facts from → 409."""
    asset = _get_asset(db, asset_id)
    validated = None
    if request.spec is not None:
        result = validate_spec(request.spec, get_vocabulary())
        if not result.ok:
            return JSONResponse(status_code=422, content={
                "detail": [issue.as_detail() for issue in result.issues]})
        validated = result.spec
    else:
        linked = _linked_design(db, asset)
        if linked:
            _, _, validated = linked
    if validated is None:
        return JSONResponse(status_code=409, content={
            "detail": "no spec to derive checklist items from — pass a spec "
                      "or link the chain to a design "
                      "(PATCH /assets/{id}/link-design)"})

    items = [i.model_dump() for i in build_checklist_items(validated)]
    checklist = ApprovalChecklist(
        id=new_id("chk"), asset_id=asset.id, mode=request.mode, items=items,
        created_by=request.created_by)
    db.add(checklist)
    db.commit()
    return {"checklist_id": checklist.id, "asset_id": asset.id,
            "version": _version_number(_chain(db, asset.root_id), asset.id),
            "mode": checklist.mode, "items": items,
            "status": checklist_status(items, [])}


@router.get("/{asset_id}/checklist")
def get_checklist(asset_id: str, db: DbSession):
    """The newest checklist for this exact asset: items, the latest answer
    per item, roll-up status, and where the pin stands."""
    asset = _get_asset(db, asset_id)
    checklist = _newest_checklist(db, asset_id)
    if checklist is None:
        raise HTTPException(status_code=404,
                            detail=f"no checklist for asset '{asset_id}' — "
                                   "POST /assets/{id}/checklist to start one")
    responses = _checklist_responses(db, checklist.id)
    latest: dict[str, dict] = {}
    for r in responses:
        latest[r.item_key] = {
            "approved": bool(r.approved), "note": r.note,
            "understood_as": r.understood_as, "created_by": r.created_by,
            "created_at": r.created_at.isoformat()}
    status = checklist_status(checklist.items, responses)
    return {"checklist_id": checklist.id, "asset_id": asset.id,
            "mode": checklist.mode, "items": checklist.items,
            "answers": latest, "status": status,
            "pin_state": {"pinned": asset.pinned_at is not None,
                          "gated": checklist.mode != "optional"}}


class ChecklistRespondRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_key: Annotated[str, Field(min_length=1, max_length=48)]
    approved: bool
    note: Annotated[str, Field(max_length=2000)] = ""
    interpret: bool = False       # ask the agent for its understood-as echo
    created_by: str = "usr_pending"
    assistant_name: str | None = None


@router.post("/{asset_id}/checklist/respond", status_code=201)
def respond_checklist(asset_id: str, request: ChecklistRespondRequest,
                      db: DbSession):
    """One tap. YES approves the fact. NO requires the change note (the WHOOP
    journal rule) and comes back with an agent-ready change request prefill —
    and, with interpret=true, the agent's understood-as echo the designer
    confirms BEFORE anything executes. In auto_pin mode the last YES pins the
    version for factory. Append-only: every tap is an audit row."""
    asset = _get_asset(db, asset_id)
    checklist = _newest_checklist(db, asset_id)
    if checklist is None:
        raise HTTPException(status_code=404,
                            detail=f"no checklist for asset '{asset_id}'")
    items = {i["key"]: i for i in checklist.items}
    item = items.get(request.item_key)
    if item is None:
        return JSONResponse(status_code=422, content={
            "detail": f"unknown item '{request.item_key}' — valid: "
                      f"{sorted(items)}"})
    note = request.note.strip()
    if not request.approved and not note:
        return JSONResponse(status_code=422, content={
            "detail": "a NO needs the change note — say what should change "
                      "so the agent can execute it"})

    # the tap is never lost to a network hiccup: save first, interpret after
    row = ApprovalResponse(
        checklist_id=checklist.id, item_key=request.item_key,
        approved=request.approved, note=note or None,
        created_by=request.created_by)
    db.add(row)
    db.commit()

    out: dict = {"checklist_id": checklist.id, "item_key": request.item_key,
                 "approved": request.approved}

    linked = _linked_design(db, asset)
    if not request.approved:
        # the code-built prefill: the item's section/ref map 1:1 onto the
        # scoped-edit Annotation and the localized-edit region
        out["change_request"] = {
            "annotate": {"ref": item.get("ref"), "section": item["section"],
                         "index": item.get("index"), "instruction": note},
            "localized_edit": {
                "region_description": f"the {item['label'].lower()}",
                "change_instruction": note},
            "endpoints": ["POST /designs/{design_id}/annotate",
                          f"POST /assets/{asset.id}/localized-edit"],
            "design_id": linked[0] if linked else None,
        }
        if request.interpret:
            from facetta.grokedit import (
                GrokEditUnavailable, interpret_change_note,
            )
            try:
                interpretation = interpret_change_note(
                    note, item_label=item["label"], item_fact=item["fact"],
                    spec_json=(linked[2].model_dump(mode="json")
                               if linked else None),
                    name=request.assistant_name or "")
            except GrokEditUnavailable as exc:
                status = 503 if "KEY" in str(exc) else 502
                out["interpretation_error"] = str(exc)
                return JSONResponse(status_code=status,
                                    content={"detail": str(exc), **out})
            row.understood_as = interpretation["understood_as"]
            db.commit()
            out["interpretation"] = interpretation

    status = _checklist_state(db, checklist)
    out["status"] = status
    if (checklist.mode == "auto_pin" and status["all_approved"]
            and asset.pinned_at is None):
        asset.pinned_at = utcnow()
        db.commit()
        chain = _chain(db, asset.root_id)
        out["pinned"] = True
        out["pinned_version"] = _version_number(chain, asset.id)
        out["message"] = (f"All {status['total']} checks approved — pinned "
                          f"version {out['pinned_version']} for factory")
    else:
        out["pinned"] = asset.pinned_at is not None
    return out


class ChainDrawingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notes: Annotated[str, Field(max_length=2000)] = ""
    mode: str | None = None
    region: str = "DUAL"
    spec: Spec | None = None
    legibility: bool = False
    # the app's factory sheet IS the official one: Grok draws clean, code
    # letters every number. Opting OUT (false) is the raw-drawing escape hatch.
    facetta_template: bool = True
    house: str | None = None
    signature: str | None = None
    piece_name: Annotated[str, Field(max_length=48)] | None = None
    # no spec on the chain? Grok vision-reads the pinned render and code
    # letters the panel as ESTIMATED — the ballpark designer's assist
    assist_specs: bool = False
    # one known measurement so Grok scales the reference estimates (e.g.
    # "centre stone 2 ct" or "overall height 40 mm")
    scale_anchor: str | None = None
    # regenerate: force a genuinely fresh Grok drawing instead of the cached
    # one (bump per press; the app's "regenerate" button)
    variant: int = 0
    # explicit override: draw from THIS asset instead of the chain's pin
    use_this_asset: bool = False


@router.post("/{asset_id}/technical-drawing")
def chain_technical_drawing(asset_id: str, request: ChainDrawingRequest,
                            db: DbSession):
    """MODE B, gated by the pin: generates the manufacturing technical
    drawing from the chain's PINNED asset. No pin and no explicit override →
    409 asking the designer to approve a version first. use_this_asset=true
    is the explicit override ("from this exact version"). The response says
    which version it drew from — the UI copy is 'From pinned version N.'"""
    asset = _get_asset(db, asset_id)
    chain = _chain(db, asset.root_id)

    if request.use_this_asset:
        source = asset
    else:
        source = _pinned(chain)
        if source is None:
            return JSONResponse(status_code=409, content={
                "detail": "no version of this chain is pinned for factory — "
                          "approve one (POST /assets/{id}/pin) or pass "
                          "use_this_asset=true to draw from this exact "
                          "version"})

    # spec resolution: the request body wins → else the chain's linked
    # design's LATEST version (so a synced edit letters automatically) →
    # else the assist estimate (below)
    validated = None
    spec_source = None
    if request.spec is not None:
        result = validate_spec(request.spec, get_vocabulary())
        if not result.ok:
            return JSONResponse(status_code=422, content={
                "detail": [issue.as_detail() for issue in result.issues]})
        validated = result.spec
        spec_source = "request"
    else:
        linked = _linked_design(db, source)
        if linked:
            design_id, design_version, validated = linked
            spec_source = f"design:{design_id} v{design_version}"

    try:
        sheet, summary, cached = generate_spec_sheet(
            bytes(source.image), notes=request.notes, mode=request.mode,
            region=request.region, spec=validated,
            legibility=request.legibility, templated=request.facetta_template,
            variant=request.variant)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except RenderUnavailable as exc:
        return _provider_error(exc)

    # assist: no spec anywhere → Grok vision-reads the SOURCE render
    # (the pinned version) and code letters the panel as ESTIMATED
    estimates = None
    if (request.facetta_template and request.assist_specs
            and validated is None):
        from facetta.estimate import physics_check_estimates
        from facetta.specagent import read_sheet_specs
        try:
            estimates = read_sheet_specs(bytes(source.image),
                                        scale_anchor=request.scale_anchor)
            # pure code: correct any carat that contradicts its own estimated
            # size, fill missing ones — zero API calls, drawing untouched
            estimates = physics_check_estimates(get_vocabulary(), estimates)
            spec_source = "assist_estimate"
        except RenderUnavailable as exc:
            return _provider_error(exc)

    # the checklist sign-off, lettered on the sheet when the SOURCE version
    # completed its ritual — from the approval record, never invented
    approval = None
    checklist = _newest_checklist(db, source.id)
    if checklist is not None:
        responses = _checklist_responses(db, checklist.id)
        status = checklist_status(checklist.items, responses)
        if status["all_approved"] and responses:
            last = responses[-1]
            approval = approval_footer_line(status, last.created_by,
                                            last.created_at)

    framed_svg = None
    if request.facetta_template:
        from facetta.drawing_frame import frame_technical_drawing
        from facetta.svg_sheet import Branding
        branding = (Branding(house=request.house, signature=request.signature)
                    if (request.house or request.signature) else None)
        try:
            framed_svg = frame_technical_drawing(sheet, spec=validated,
                                                 branding=branding,
                                                 piece_name=request.piece_name,
                                                 estimates=estimates,
                                                 approval=approval)
        except OSError as exc:
            framed_svg = None
            summary.setdefault("factory_notes", []).append(
                f"official template unavailable: {exc}")

    return {
        "sheet_b64": base64.b64encode(sheet).decode(),
        "media_type": _sniff_media_type(sheet),
        "framed_svg": framed_svg,
        "summary": summary,
        "cached": cached,
        "estimated_specs": estimates,
        "spec_source": spec_source,
        "approval": approval,
        "source_asset_id": source.id,
        "from_pinned_version": (None if request.use_this_asset
                                else _version_number(chain, source.id)),
        "source_note": (f"From this exact version "
                        f"(v{_version_number(chain, source.id)}, override)"
                        if request.use_this_asset else
                        f"From pinned version "
                        f"{_version_number(chain, source.id)}"),
    }

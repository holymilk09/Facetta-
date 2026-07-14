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
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from facetta.api.error_mapping import (
    image_agent_error_response, provider_studio_job_error_response,
    render_unavailable_response,
)
from facetta.auth import (
    AuthenticatedPrincipal,
    principal_actor,
    require_asset_project_boundary,
    require_principal_boundary,
)
from facetta.checklist import (
    DEFAULT_MODE, approval_footer_line, build_checklist_items,
    checklist_status,
)
from facetta.config import env_value
from facetta.db import (
    ApprovalChecklist, ApprovalResponse, DesignVersion, FeedbackEvent,
    ImageAsset, Project, get_db, new_id, utcnow,
)
from facetta.disclaimer import is_stampable, stamp_b64, stamp_image
from facetta.markup_snapshot import (
    MarkupSnapshot,
    MarkupSnapshotImageError,
    composite_markup_snapshot,
)
from facetta.project_backbone import is_primary_revision
from facetta.provider_job_gate import (
    ProviderStudioJobError,
    require_provider_studio_job,
)
from facetta.render import RenderUnavailable, _sniff_media_type
from facetta.revision_component_map import (
    bind_map_to_raster,
    ComponentMapError,
    ComponentMappingUnresolved,
    rasterize_component_mask,
    reconcile_parent_component_ids,
    unresolved_revision_component_mapper,
)
from facetta.revision_component_map_store import (
    add_revision_component_map,
    load_revision_component_map,
)
from facetta.spec import Spec
from facetta.specagent import (
    SKIN_TONES, SPIN_MOTIONS, VIEW_ANGLES, check_design_consistency,
    generate_spec_sheet, global_restyle, jewelry_render, localized_edit,
    mask_from_markup, read_markup, render_spin_video, render_view_set,
)
from facetta.specdiff import diff_specs, summarize_changes
from facetta.validation import validate_spec
from facetta.vocabulary import get_vocabulary

router = APIRouter(
    prefix="/assets",
    tags=["assets"],
    dependencies=[
        Depends(require_principal_boundary),
        Depends(require_asset_project_boundary),
    ],
)

DbSession = Annotated[Session, Depends(get_db)]
PrincipalDep = Annotated[AuthenticatedPrincipal, Depends(require_principal_boundary)]


def _provider_error(exc: RenderUnavailable) -> JSONResponse:
    return render_unavailable_response(exc)


def _trusted_image_agent():
    """Injection seam for the trusted closed-loop image pipeline."""
    from facetta.image_agent import JewelryImageAgent

    return JewelryImageAgent()


def _revision_component_mapper(**kwargs):
    """Injection seam for calibrated vision mapping of accepted child bytes."""
    return unresolved_revision_component_mapper(**kwargs)


# The gentle accuracy disclaimer is stamped on client-facing photoreal renders.
# A factory technical drawing carries its own dimension-honesty disclaimer, so a
# "preview may vary" caption would undermine it — those are delivered unstamped.
# PRODUCT_PHOTO is also clean by contract because it is an ecommerce export,
# while its immutable provenance and QA remain available in the project record.
_UNSTAMPED_CAPS = {
    "MANUFACTURING_TECHNICAL_DRAWING",
    "PRODUCT_PHOTO",
    "MARKETING_IMAGE",
    "LINE_ART",
    "COLORED_LINE_ART",
}


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


def _lock_approval_generation_for_write(
    db: Session,
    asset: ImageAsset,
) -> None:
    """Acquire the Factory CAS lock before mutating approval truth."""

    from facetta.studio_jobs import (
        ApprovalGenerationLockedError,
        lock_project_approval_generation,
    )

    try:
        lock_project_approval_generation(
            db,
            project_root_id=asset.root_id,
            for_mutation=True,
        )
    except ApprovalGenerationLockedError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "factory_approval_generation_locked",
                "message": str(exc),
            },
        ) from exc


def _approval_actor(
    principal: AuthenticatedPrincipal,
    supplied_actor: str | None,
    asset: ImageAsset,
) -> str:
    """Use authenticated identity for approval evidence in deployed modes."""

    if principal.local_unbound:
        return supplied_actor or asset.created_by or "usr_pending"
    assert principal.subject is not None
    return principal_actor(principal, supplied_actor or principal.subject)


def _approval_spec_payload(spec: Spec) -> dict:
    """Comparable jewelry truth without immutable-record identity metadata."""

    payload = spec.model_dump(mode="json")
    for field in ("design_id", "version", "created_by", "created_at"):
        payload.pop(field, None)
    return payload


def _store_asset(db: Session, image: bytes, capability: str,
                 parent: ImageAsset | None = None, *,
                 asset_id: str | None = None,
                 instruction: str | None = None, region: str | None = None,
                 drift: float | None = None,
                 design_id: str | None = None,
                 design_version: int | None = None,
                 media_type: str | None = None,
                 created_by: str = "usr_pending",
                 commit: bool = True) -> ImageAsset:
    """Store one immutable asset.

    The default preserves the legacy route behavior.  Trusted workflows pass
    ``commit=False`` so a primary image and its immutable ``DesignVersion``
    are flushed and committed as one unit.  Derived assets inherit the exact
    specification provenance of their parent.
    """
    if design_version is None and parent is not None:
        design_version = parent.design_version
    asset = ImageAsset(
        id=asset_id or new_id("ast"),
        root_id=parent.root_id if parent else "",  # set below for roots
        parent_asset_id=parent.id if parent else None,
        design_id=design_id if parent is None else None,
        design_version=design_version,
        capability=capability, instruction=instruction, region=region,
        drift=drift, image=image,
        media_type=media_type or _sniff_media_type(image),
        created_by=created_by)
    if parent is None:
        asset.root_id = asset.id
    db.add(asset)
    if parent is not None:                       # a new item in an existing chain
        _touch_project(db, asset.root_id, commit=False)
    if commit:
        db.commit()
    else:
        db.flush()
    return asset


def _ensure_project(db: Session, root: ImageAsset, *, commit: bool = True) -> Project:
    """Every chain root files a project into the owner's library (Unfiled until
    the designer organizes it). Idempotent."""
    project = db.get(Project, root.id)
    if project is None:
        title = (root.instruction or "Untitled piece")[:200]
        project = Project(root_id=root.id, owner=root.created_by,
                          collection=None, title=title, tags=[])
        db.add(project)
        if commit:
            db.commit()
        else:
            db.flush()
    return project


def _touch_project(db: Session, root_id: str, *, commit: bool = True) -> None:
    project = db.get(Project, root_id)
    if project is not None:
        project.updated_at = utcnow()
        if commit:
            db.commit()


def _chain(db: Session, root_id: str) -> list[ImageAsset]:
    return list(db.scalars(
        select(ImageAsset).where(ImageAsset.root_id == root_id)
        .order_by(ImageAsset.created_at, ImageAsset.id)))


def _is_primary_revision(asset: ImageAsset) -> bool:
    """Compatibility alias for the one canonical revision classification."""
    return is_primary_revision(asset)


def _version_number(chain: list[ImageAsset], asset_id: str) -> int:
    """Return the visual revision, excluding derived evidence and media.

    Markup uploads, source concepts, alternate angles, videos, and drawings
    belong to a revision; they do not silently advance it.  A derived asset
    therefore reports the most recent primary revision at its creation point.
    """
    revision = 0
    for asset in chain:
        if _is_primary_revision(asset):
            revision += 1
        if asset.id == asset_id:
            return revision
    return 0


def _pinned(chain: list[ImageAsset]) -> ImageAsset | None:
    pinned = [a for a in chain
              if a.pinned_at is not None and _is_primary_revision(a)]
    if not pinned:  # legacy databases may contain a derived pin; keep readable
        pinned = [a for a in chain if a.pinned_at is not None]
    return max(pinned, key=lambda a: a.pinned_at) if pinned else None


def _asset_meta(db: Session, asset: ImageAsset) -> dict:
    chain = _chain(db, asset.root_id)
    root = db.get(ImageAsset, asset.root_id) or asset
    return {
        "asset_id": asset.id,
        "parent_asset_id": asset.parent_asset_id,
        "root_id": asset.root_id,
        "version": _version_number(chain, asset.id),
        "revision": (_version_number(chain, asset.id)
                     if _is_primary_revision(asset) else None),
        "derived_from_revision": (None if _is_primary_revision(asset)
                                  else _version_number(chain, asset.id)),
        "capability": asset.capability,
        "image_url": f"/assets/{asset.id}/image",
        "design_id": root.design_id,
        "design_version": asset.design_version,
        "provenance": {
            "kind": ("primary_revision" if _is_primary_revision(asset)
                     else "derived_asset"),
            "capability": asset.capability,
            "source_asset_id": asset.parent_asset_id,
            "design_id": root.design_id,
            "design_version": asset.design_version,
            "legacy": bool(root.design_id and asset.design_version is None),
        },
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


@router.post("/render", status_code=201, deprecated=True)
def create_render_asset(
    request: AssetRenderRequest,
    db: DbSession,
    principal: PrincipalDep,
):
    """MODE A into the chain: a new root asset the iteration loop grows from.
    Pass `angles` to also get extra camera views of the same design in one
    request — each is derived from this hero render (design-locked), so the
    designer gets a consistent turntable without re-generating (which would
    invent a different piece per angle)."""
    actor = principal_actor(principal, request.created_by)
    design_version = None
    if request.design_id is not None:
        from facetta.db import Design
        from facetta.project_backbone import (
            DesignAlreadyLinked, ensure_design_chain_available,
        )
        design = db.get(Design, request.design_id)
        if design is None:
            raise HTTPException(status_code=404,
                                detail=f"unknown design '{request.design_id}'")
        if (
            not principal.local_unbound
            and design.created_by != principal.subject
        ):
            raise HTTPException(status_code=403, detail={
                "code": "design_access_denied",
                "error_category": "authorization",
                "detail": "the principal does not own the target design",
            })
        try:
            ensure_design_chain_available(db, request.design_id)
        except DesignAlreadyLinked as exc:
            return JSONResponse(status_code=409, content={
                "detail": str(exc),
                "code": "design_already_linked",
                "existing_root_id": exc.root_id})
        design_version = db.scalar(
            select(func.max(DesignVersion.version)).where(
                DesignVersion.design_id == request.design_id))
    try:
        image, cached = jewelry_render(
            request.piece_description, metal=request.metal,
            stones=request.stones, setting_details=request.setting_details,
            view_angle=request.view_angle, variant=request.variant)
        hero = _store_asset(
            db, image, "JEWELRY_RENDER",
            instruction=request.piece_description,
            design_id=request.design_id, design_version=design_version,
            created_by=actor, commit=False)
        _ensure_project(db, hero, commit=False)  # same transaction as the root
        db.commit()
        views = _view_children(db, hero, request.angles, actor,
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


@router.post("/{asset_id}/views", status_code=201, deprecated=True)
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
    # anchor to the curated house style set (style only, never design)
    use_house_style: bool = False
    created_by: str = "usr_pending"
    variant: int = 0  # regenerate: a fresh take on the SAME edit, not the cache


@router.post("/{asset_id}/localized-edit", status_code=201, deprecated=True)
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
    style_ref, model = None, "grok_direct"
    if request.use_house_style:
        from facetta.housestyle import default_style_ref
        style_ref = default_style_ref()
        if style_ref is None:
            return JSONResponse(status_code=422, content={
                "detail": "no house style references curated yet — add images "
                          "to data/style_refs/"})
        model = "grok_imagine"
    try:
        result = localized_edit(
            bytes(parent.image), region_description=request.region_description,
            change_instruction=request.change_instruction,
            mask_bytes=mask_bytes, kind=request.kind, variant=request.variant,
            model=model, style_ref=style_ref)
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
            "style_anchored": request.use_house_style,
            "cached": result["cached"]}


class MarkupReadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    marked_image_base64: Annotated[
        str,
        Field(min_length=1, max_length=14_000_000),
    ] | None = None
    markup_snapshot: MarkupSnapshot | None = None
    created_by: str = "usr_pending"
    assistant_name: str | None = None

    @model_validator(mode="after")
    def require_exactly_one_markup_input(self) -> MarkupReadRequest:
        has_raster = self.marked_image_base64 is not None
        has_snapshot = self.markup_snapshot is not None
        if has_raster == has_snapshot:
            raise ValueError(
                "provide exactly one of marked_image_base64 or markup_snapshot"
            )
        return self


@router.post("/{asset_id}/markup/read")
def markup_read(
    asset_id: str,
    request: MarkupReadRequest,
    db: DbSession,
    principal: PrincipalDep,
):
    """Phase 1 of a markup edit: the agent READS the designer's marks (canvas
    shapes, arrows, freehand handwriting) against the clean render and echoes
    back what it understood — nothing executes here. The designer confirms or
    corrects the echo, then calls markup/apply with the confirmed list: the
    100%-understanding gate. Unreadable or ambiguous marks come back as a 422
    question — a region or intent is never guessed."""
    from facetta.assistant import DEFAULT_ASSISTANT_NAME

    actor = principal_actor(principal, request.created_by)
    asset = _get_asset(db, asset_id)
    if request.markup_snapshot is not None:
        try:
            marked = composite_markup_snapshot(
                bytes(asset.image), request.markup_snapshot)
        except MarkupSnapshotImageError as exc:
            return JSONResponse(status_code=422, content={
                "detail": str(exc),
                "code": "markup_snapshot_composite_invalid",
                "category": "validation",
            })
    else:
        try:
            marked = base64.b64decode(
                request.marked_image_base64 or "", validate=True)
        except (binascii.Error, ValueError):
            return JSONResponse(status_code=422, content={
                "detail": "marked_image_base64 is not valid base64"})
    linked = _linked_design(db, asset)
    form_elements = (
        tuple({
            "element_id": element.element_id,
            "role": element.role,
            "label": element.label,
            "confirmed_form_description": element.confirmed_form_description,
        } for element in linked[2].design_form.elements)
        if linked is not None else ()
    )
    try:
        reading = (
            read_markup(bytes(asset.image), marked, form_elements)
            if form_elements else read_markup(bytes(asset.image), marked)
        )
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

    known_form_ids = {
        element["element_id"] for element in form_elements
    }
    for annotation in reading["annotations"]:
        if annotation.get("target_section") != "design_form":
            continue
        target_element_id = annotation.get("target_element_id")
        if target_element_id not in known_form_ids:
            return JSONResponse(status_code=422, content={
                "detail": (
                    "the marked form change does not identify exactly one "
                    "known design element; select or confirm the component"
                ),
                "understood_as": reading["understood_as"],
                "annotations": reading["annotations"],
                "assistant_name": name,
                "valid_target_element_ids": sorted(known_form_ids),
            })

    # the marked upload is filed as an audit leaf — never an edit base
    notes = _store_asset(db, marked, "MARKUP_NOTES", asset,
                         instruction=reading["understood_as"],
                         created_by=actor)
    first = reading["annotations"][0]
    targets_spec = bool(first.get("target_section") or first.get("target_ref"))
    interpretation = {
        "target_region": first["region_description"],
        "requested_change": first["change_instruction"],
        "impact": ("specification" if targets_spec else "visual_only"),
        "target_spec_reference": first.get("target_ref"),
        "target_section": first.get("target_section"),
        "target_index": first.get("index"),
        "target_component_id": first.get("target_component_id"),
        "target_element_id": first.get("target_element_id"),
        "frozen_elements": ([
            "all specification sections outside the named target",
            "all jewelry structure outside the marked region",
        ] if targets_spec else [
            "all jewelry geometry and components",
            "the current specification version",
        ]),
        "confidence": first.get("confidence"),
        "clarification_question": None,
        "understood_as": reading["understood_as"],
    }
    return {"markup_asset_id": notes.id, "assistant_name": name,
            "understood_as": reading["understood_as"],
            "annotations": reading["annotations"],
            "interpretation": interpretation,
            "design_linked": linked is not None,
            "design_id": linked[0] if linked else None,
            "expected_design_version": linked[1] if linked else None}


class MarkupAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    region_description: Annotated[str, Field(min_length=1, max_length=500)]
    change_instruction: Annotated[str, Field(min_length=1, max_length=2000)]
    target_section: str | None = None
    target_ref: str | None = None
    index: int | None = None
    # Stable semantic identity on the exact source revision. When supplied it
    # is authoritative for localization; prose and canvas strokes cannot widen
    # its revision-bound polygon mask.
    target_component_id: str | None = None
    target_element_id: str | None = None
    form_view: Literal["front", "side", "top", "three_quarter"] = (
        "three_quarter")
    mask_base64: str | None = None


class MarkupApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    annotations: Annotated[list[MarkupAnnotation], Field(min_length=1,
                                                         max_length=8)]
    markup_asset_id: str | None = None   # phase-1 upload, for mask derivation
    kind: Literal["render", "technical"] = "render"
    update_spec: bool = True
    # Optimistic concurrency guard for the trusted workspace. Optional only for
    # deprecated non-production compatibility callers; production requires it.
    expected_design_version: Annotated[int, Field(ge=1)] | None = None
    created_by: str = "usr_pending"
    variant: int = 0  # regenerate: fresh takes on the SAME marks, not the cache
    # Studio holds even QA-passed edits outside canonical history until the
    # designer explicitly applies the temporary candidate.
    preview_only: bool = False
    # Optional only for deprecated non-production compatibility callers.
    # Production requires the durable Refine job so Apply/Discard/Variation
    # settles Activity in the same transaction as the terminal decision.
    studio_job_id: Annotated[str, Field(min_length=1, max_length=32)] | None = None


@router.post("/{asset_id}/markup/apply", status_code=201)
def markup_apply(
    asset_id: str,
    request: MarkupApplyRequest,
    db: DbSession,
    principal: PrincipalDep,
):
    """Phase 2: execute confirmed annotations.

    Production requests carry a durable Refine Studio job, an exact expected
    design version, and exactly one confirmed instruction. The older no-version
    or unlinked compatibility path is available only outside production until
    its historical callers are migrated. For each annotation, the linked
    design's spec moves first through the scoped edit; a physically impossible
    change skips the image edit so image and spec remain in lockstep. The
    accepted image and immutable DesignVersion then commit atomically.
    """
    actor = principal_actor(principal, request.created_by)
    request = request.model_copy(update={"created_by": actor})
    environment = (env_value("FACETTA_ENV") or "production").strip().lower()
    production = environment == "production"
    if production and request.preview_only is not True:
        return JSONResponse(status_code=409, content={
            "detail": (
                "production refinements must remain temporary until explicit "
                "Studio acceptance"
            ),
            "code": "studio_preview_required",
            "category": "conflict",
        })
    if production and request.expected_design_version is None:
        return JSONResponse(status_code=422, content={
            "detail": (
                "production refinements require the exact expected design "
                "version"
            ),
            "code": "expected_design_version_required",
            "category": "validation",
        })

    from facetta.agent import Annotation, AnnotationUnresolved
    from facetta.grokedit import GrokEditUnavailable, grok_plan_scoped_edit

    if ((production or request.expected_design_version is not None)
            and len(request.annotations) != 1):
        return JSONResponse(status_code=422, content={
            "detail": ("trusted markup applies exactly one confirmed "
                       "instruction at a time"),
            "code": "single_instruction_required",
            "category": "validation",
            "instruction_count": len(request.annotations),
        })

    asset = _get_asset(db, asset_id)
    start_bytes = bytes(asset.image)

    # a phase-1 canvas upload yields a drift mask (same raster only)
    derived_mask = None
    markup_notes_valid = False
    if request.markup_asset_id:
        notes = db.get(ImageAsset, request.markup_asset_id)
        if (notes is not None
                and notes.capability == "MARKUP_NOTES"
                and notes.root_id == asset.root_id
                and notes.parent_asset_id == asset.id):
            markup_notes_valid = True
            derived_mask = mask_from_markup(start_bytes, bytes(notes.image))

    linked = _linked_design(db, asset)
    design_id = linked[0] if linked else None
    current_design_version = linked[1] if linked else asset.design_version
    current_spec = linked[2] if linked and request.update_spec else None

    if linked is None and (production
                           or request.expected_design_version is not None):
        return JSONResponse(status_code=409, content={
            "detail": "the asset is not linked to a validated design",
            "code": "design_not_linked",
            "category": "validation"})
    if request.expected_design_version is not None:
        assert linked is not None
        if request.expected_design_version != linked[1]:
            return JSONResponse(status_code=409, content={
                "detail": ("the design changed while this revision was open; "
                           "reload before applying the annotation"),
                "code": "stale_design_version",
                "category": "stale_version",
                "expected_design_version": request.expected_design_version,
                "current_design_version": linked[1]})

    try:
        require_provider_studio_job(
            db,
            job_id=request.studio_job_id,
            owner=actor,
            action_id="refine",
            requested_outputs=1,
            active_design_id=asset.root_id,
            source_revision_id=asset.id,
        )
    except ProviderStudioJobError as exc:
        return provider_studio_job_error_response(exc)

    if production:
        # Serialize against every canonical Studio revision writer, then
        # recompute active visual truth while that project lock is held.  A
        # design-version check alone cannot detect an appearance-only revision
        # that advanced after this Refine job was opened.
        from facetta.api.projects import project_detail
        from facetta.studio_jobs import lock_project_approval_generation

        project = lock_project_approval_generation(
            db,
            project_root_id=asset.root_id,
            owner=actor,
        )
        active_asset_id = (
            project_detail(db, project)["active_asset_id"]
            if project is not None else None
        )
        if active_asset_id != asset.id:
            return JSONResponse(status_code=409, content={
                "detail": (
                    "the active visual revision changed while this refinement "
                    "was open; reopen the design before creating a preview"
                ),
                "code": "stale_active_revision",
                "category": "stale_version",
                "expected_active_asset_id": asset.id,
                "current_active_asset_id": active_asset_id,
            })

    current = asset
    steps: list[dict] = []
    for note in request.annotations:
        step: dict = {"annotation": note.model_dump(exclude={"mask_base64"})}
        form_edit = (
            note.target_section == "design_form"
            or note.target_element_id is not None
        )
        targets_spec = bool(
            note.target_section or note.target_ref or note.target_element_id)

        if targets_spec and not request.update_spec:
            return JSONResponse(status_code=422, content={
                "detail": ("a geometry, stone, setting, metal, or dimensional "
                           "change must update the image and specification "
                           "together"),
                "code": "spec_sync_required",
                "category": "validation",
                "steps": steps})
        if targets_spec and linked is None:
            # Compatibility only: the trusted client always supplies
            # expected_design_version and is rejected above when unlinked.
            # Keep the old experience reachable until founder acceptance.
            step["spec_note"] = (
                "deprecated unlinked image-only path; trusted structural "
                "edits require a linked design (PATCH "
                "/assets/{id}/link-design)")

        # Decode the per-annotation mask before compiling any structural spec
        # change. A design-form revision must use the mask derived from the
        # persisted same-raster MARKUP_NOTES asset; an untracked client mask
        # cannot substitute for that provenance.
        mask_bytes = derived_mask
        if note.mask_base64:
            try:
                supplied_mask = base64.b64decode(
                    note.mask_base64, validate=True)
            except (binascii.Error, ValueError):
                return JSONResponse(status_code=422, content={
                    "detail": "mask_base64 is not valid base64",
                    "steps": steps})
            if not form_edit:
                mask_bytes = supplied_mask

        parent_component_map = None
        if (request.expected_design_version is not None
                and note.target_component_id is None):
            try:
                mapped_revision = load_revision_component_map(db, current.id)
            except ComponentMapError as exc:
                return JSONResponse(status_code=409, content={
                    "detail": exc.detail,
                    "code": exc.code,
                    "category": "validation",
                    "steps": steps,
                })
            if mapped_revision is not None:
                return JSONResponse(status_code=422, content={
                    "detail": (
                        "select one resolved component on this mapped revision"
                    ),
                    "code": "target_component_required",
                    "category": "validation",
                    "valid_target_component_ids": [
                        component.component_id
                        for component in mapped_revision.components
                        if component.resolution == "resolved"
                    ],
                    "steps": steps,
                })
        if note.target_component_id is not None:
            try:
                parent_component_map = load_revision_component_map(
                    db, current.id)
                if parent_component_map is None:
                    raise ComponentMapError(
                        "the selected visual revision has no component map",
                        code="component_map_not_found",
                    )
                # Membership and resolution are checked by rasterization. The
                # revision-bound semantic mask is authoritative for the image
                # plan; an arbitrary client mask cannot widen the edit area.
                mask_bytes = rasterize_component_mask(
                    parent_component_map, note.target_component_id)
            except ComponentMapError as exc:
                return JSONResponse(status_code=422, content={
                    "detail": exc.detail,
                    "code": exc.code,
                    "category": "validation",
                    "steps": steps,
                })

        if form_edit:
            if (note.target_section != "design_form"
                    or not note.target_element_id):
                return JSONResponse(status_code=422, content={
                    "detail": (
                        "a design-form edit must name target_section "
                        "'design_form' and exactly one stable target_element_id"
                    ),
                    "code": "form_element_required",
                    "category": "validation",
                    "steps": steps,
                })
            if request.expected_design_version is None:
                return JSONResponse(status_code=422, content={
                    "detail": (
                        "a design-form edit requires expected_design_version"
                    ),
                    "code": "expected_design_version_required",
                    "category": "validation",
                    "steps": steps,
                })
            if (not request.markup_asset_id or not markup_notes_valid
                    or derived_mask is None):
                return JSONResponse(status_code=422, content={
                    "detail": (
                        "a design-form edit requires a saved same-raster markup "
                        "asset with a usable highlighted mask"
                    ),
                    "code": "form_markup_mask_required",
                    "category": "validation",
                    "steps": steps,
                })
            mask_bytes = derived_mask

        # 1) spec first, when linked and the mark names a section
        scoped = None
        scoped_spec = None
        reserved_asset_id = (
            new_id("ast") if note.target_component_id is not None else None
        )
        form_region = None
        confirmed_form_description = None
        if form_edit and current_spec is not None:
            from facetta.agent import ScopedEditResult
            from facetta.design_form_revision import (
                DesignFormRevisionError,
                region_from_markup_mask,
                revise_visual_form_element,
            )

            reserved_asset_id = reserved_asset_id or new_id("ast")
            if all(
                element.element_id != note.target_element_id
                for element in current_spec.design_form.elements
            ):
                return JSONResponse(status_code=422, content={
                    "detail": (
                        "the current specification has no confirmed form "
                        f"element {note.target_element_id!r}"
                    ),
                    "code": "form_element_not_found",
                    "category": "validation",
                    "valid_target_element_ids": [
                        element.element_id
                        for element in current_spec.design_form.elements
                    ],
                    "steps": steps,
                })
            try:
                form_region = region_from_markup_mask(
                    mask_bytes,
                    bytes(current.image),
                    view=note.form_view,
                )
                annotation = Annotation(
                    ref=None,
                    section="design_form",
                    index=None,
                    target_element_id=note.target_element_id,
                    instruction=note.change_instruction,
                )
                planned = grok_plan_scoped_edit(annotation, current_spec)
                planned_element = next(
                    element for element in planned.spec.design_form.elements
                    if element.element_id == note.target_element_id
                )
                confirmed_form_description = (
                    planned_element.confirmed_form_description
                )
                proposed_spec = revise_visual_form_element(
                    current_spec,
                    element_id=note.target_element_id,
                    confirmed_form_description=confirmed_form_description,
                    region=form_region,
                    asset_id=reserved_asset_id,
                    asset_sha256="0" * 64,
                )
            except AnnotationUnresolved as exc:
                return JSONResponse(status_code=422, content={
                    "detail": str(exc),
                    "code": "form_interpretation_unresolved",
                    "category": "validation",
                    "steps": steps,
                })
            except GrokEditUnavailable as exc:
                status = 503 if "KEY" in str(exc) else 502
                return JSONResponse(status_code=status, content={
                    "detail": str(exc),
                    "code": "form_interpretation_unavailable",
                    "category": "provider",
                    "steps": steps,
                })
            except DesignFormRevisionError as exc:
                return JSONResponse(status_code=422, content={
                    "detail": exc.detail,
                    "code": exc.code,
                    "category": "validation",
                    "steps": steps,
                })
            validated = validate_spec(proposed_spec, get_vocabulary())
            if not validated.ok:
                return JSONResponse(status_code=422, content={
                    "detail": [issue.as_detail() for issue in validated.issues],
                    "code": "form_spec_invalid",
                    "category": "validation",
                    "steps": steps,
                })
            # Validation is a gate here, not an opportunity to rewrite an
            # unrelated legacy/derived field. The scoped form contract must
            # preserve every non-target byte of the current specification.
            scoped_spec = proposed_spec
            scoped = ScopedEditResult(
                spec=scoped_spec,
                target=f"design_form.elements[{note.target_element_id}]",
                isolate_ref=note.target_element_id,
                changed_fields=[
                    "design_form element " + note.target_element_id
                    + " confirmed form -> " + confirmed_form_description,
                ],
                ignored_fields=[],
                message=planned.message,
            )
        elif current_spec is not None and (note.target_section or note.target_ref):
            annotation = Annotation(
                ref=note.target_ref, section=note.target_section,
                index=note.index, instruction=note.change_instruction)
            try:
                scoped = grok_plan_scoped_edit(annotation, current_spec)
            except AnnotationUnresolved as exc:
                step["spec_synced"] = False
                step["spec_note"] = str(exc)
                step["rejected"] = True
                steps.append(step)
                continue
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
        image_agent_result = None
        qa_report = None
        routing_summary = None
        if request.expected_design_version is not None:
            from facetta.image_agent import (
                ImageAgentError, ImageOperation, build_image_plan,
            )
            from facetta.image_run_store import (
                persist_image_agent_failure, persist_image_agent_result,
            )

            operation = (ImageOperation.LOCAL_EDIT if scoped is not None
                         else ImageOperation.VISUAL_ONLY_EDIT)
            plan_spec = scoped_spec if scoped is not None else linked[2]
            try:
                plan = build_image_plan(
                    operation,
                    note.change_instruction,
                    spec=plan_spec,
                    source_spec=(current_spec if scoped is not None else None),
                    source_image=bytes(current.image),
                    mask_bytes=mask_bytes,
                    mask_provenance=(
                        "persisted_designer_markup"
                        if derived_mask is not None
                        and mask_bytes is derived_mask
                        else "client_supplied_markup"
                        if mask_bytes is not None
                        else None
                    ),
                    region_description=(note.region_description
                                        if operation is ImageOperation.LOCAL_EDIT
                                        else None),
                    frozen=(
                        "all untargeted specification sections",
                        "camera and composition unless explicitly requested",
                    ),
                    variant=request.variant,
                )
                image_agent_result = _trusted_image_agent().run(
                    plan,
                    source_image=bytes(current.image),
                    mask_bytes=mask_bytes,
                )
            except ImageAgentError as exc:
                run_id = None
                if exc.plan is not None:
                    run_id = persist_image_agent_failure(
                        db,
                        exc.plan,
                        exc,
                        project_root_id=asset.root_id,
                        source_asset_id=current.id,
                        created_by=request.created_by,
                    )
                return image_agent_error_response(
                    exc,
                    image_run_id=run_id,
                    extra={"steps": steps},
                )

            # The plan used a reserved asset identity and a non-persisted hash
            # placeholder. Once provider/QA bytes exist, bind the immutable
            # spec to those exact bytes before either pass persistence or
            # warning review. The visual hash intentionally ignores storage
            # identity, so this does not change what the image agent evaluated.
            if form_edit:
                from facetta.agent import ScopedEditResult
                from facetta.design_form_revision import (
                    DesignFormRevisionError,
                    revise_visual_form_element,
                )

                try:
                    final_form_spec = revise_visual_form_element(
                        current_spec,
                        element_id=note.target_element_id,
                        confirmed_form_description=confirmed_form_description,
                        region=form_region,
                        asset_id=reserved_asset_id,
                        asset_bytes=image_agent_result.image_bytes,
                    )
                except DesignFormRevisionError as exc:
                    return JSONResponse(status_code=422, content={
                        "detail": exc.detail,
                        "code": exc.code,
                        "category": "validation",
                        "steps": steps,
                    })
                validated = validate_spec(final_form_spec, get_vocabulary())
                if not validated.ok:
                    return JSONResponse(status_code=422, content={
                        "detail": [
                            issue.as_detail() for issue in validated.issues
                        ],
                        "code": "form_spec_invalid",
                        "category": "validation",
                        "steps": steps,
                    })
                # As above, validation gates the exact scoped record; it must
                # not opportunistically populate an unrelated derived field.
                scoped_spec = final_form_spec
                scoped = ScopedEditResult(
                    spec=scoped_spec,
                    target=(
                        "design_form.elements["
                        + note.target_element_id + "]"
                    ),
                    isolate_ref=note.target_element_id,
                    changed_fields=[
                        "design_form element " + note.target_element_id
                        + " confirmed form -> " + confirmed_form_description,
                    ],
                    ignored_fields=[],
                    message=(
                        "scoped masked design-form revision for "
                        + note.target_element_id
                    ),
                )

            failed = [check.code for check in image_agent_result.quality.failed_checks]
            warnings = [
                check.message for check in image_agent_result.quality.failed_checks
                if check.severity.value == "warning"
            ]
            qa_report = {
                **image_agent_result.quality.model_dump(mode="json"),
                "accepted": image_agent_result.accepted,
                "review_required": image_agent_result.review_required,
                "summary": ("Image checks passed." if image_agent_result.accepted
                            else "Image needs explicit designer review."),
                "failed_checks": failed,
                "warnings": warnings,
            }
            routing_summary = {
                "attempt_count": len(image_agent_result.run.attempts),
                "used_retry": len(image_agent_result.run.attempts) > 1,
                "used_fallback": any(
                    attempt.fallback for attempt in image_agent_result.run.attempts),
                "cache_hit": any(
                    attempt.cached for attempt in image_agent_result.run.attempts),
                "run_id": None,
            }
            if image_agent_result.review_required or request.preview_only:
                if note.target_component_id is not None:
                    # A warning candidate has not become a revision and its
                    # component identities have not been accepted. Until the
                    # warning-candidate store can carry a mapped child atomically,
                    # fail closed instead of later promoting an unmapped asset.
                    return JSONResponse(status_code=422, content={
                        "detail": (
                            "component-aware edits cannot enter temporary review "
                            "until candidate component maps can be promoted "
                            "atomically; use the component catalog or retry"
                        ),
                        "code": "component_edit_qa_review_required",
                        "category": "quality",
                        "qa": qa_report,
                        "steps": steps,
                    })
                stored_preview_result = image_agent_result
                if request.preview_only and not image_agent_result.review_required:
                    from facetta.image_agent import ImageRunStatus
                    stored_preview_result = image_agent_result.model_copy(update={
                        "accepted": False,
                        "review_required": True,
                        "run": image_agent_result.run.model_copy(update={
                            "status": ImageRunStatus.REVIEW_REQUIRED,
                        }),
                    })
                run_id = persist_image_agent_result(
                    db,
                    stored_preview_result,
                    project_root_id=asset.root_id,
                    source_asset_id=current.id,
                    created_by=request.created_by,
                    # A Studio preview holds the Refine job lock until its
                    # durable candidate moves that same job to reviewing.
                    # Persist run evidence in the candidate transaction so a
                    # failed candidate write cannot release a still-running
                    # job with orphaned, replayable provider output.
                    commit=request.studio_job_id is None,
                )
                routing_summary["run_id"] = run_id
                from time import monotonic

                from facetta.studio_markup_candidates import (
                    store_studio_markup_candidate,
                )
                from facetta.warning_candidates import (
                    MarkupWarningCandidate,
                    store_markup_warning_candidate,
                )

                candidate_drift = next((
                    check.evidence.get("drift")
                    for check in image_agent_result.quality.checks
                    if check.code == "outside_mask_drift"
                ), None)
                compatibility_candidate = MarkupWarningCandidate(
                    candidate_id=new_id("cand"),
                    run_id=run_id,
                    project_root_id=asset.root_id,
                    source_asset_id=current.id,
                    expected_active_asset_id=current.id,
                    reserved_asset_id=reserved_asset_id,
                    expected_design_version=current_design_version,
                    image_bytes=image_agent_result.image_bytes,
                    media_type=_sniff_media_type(image_agent_result.image_bytes),
                    operation=operation.value,
                    asset_capability=(
                        "GLOBAL_RESTYLE"
                        if operation is ImageOperation.VISUAL_ONLY_EDIT
                        else "LOCALIZED_EDIT"
                    ),
                    requested_change=note.change_instruction,
                    region_description=note.region_description,
                    drift=(float(candidate_drift)
                           if isinstance(candidate_drift, (int, float))
                           else None),
                    next_spec=(scoped_spec if scoped is not None else None),
                    ignored_fields=tuple(
                        scoped.ignored_fields if scoped is not None else ()),
                    qa=qa_report,
                    routing=routing_summary,
                    created_by=request.created_by,
                    expires_at=monotonic() + (2 * 60 * 60),
                )
                # Existing trusted-workflow callers use the legacy warning
                # review URLs and do not own a StudioJob. Keep that short-lived
                # compatibility path intact while Studio requests opt into the
                # durable, restart-safe review authority explicitly.
                candidate = (
                    store_studio_markup_candidate(
                        db,
                        compatibility_candidate,
                        studio_job_id=request.studio_job_id,
                    )
                    if request.studio_job_id is not None
                    else store_markup_warning_candidate(
                        run_id=compatibility_candidate.run_id,
                        project_root_id=compatibility_candidate.project_root_id,
                        source_asset_id=compatibility_candidate.source_asset_id,
                        expected_active_asset_id=(
                            compatibility_candidate.expected_active_asset_id
                        ),
                        reserved_asset_id=compatibility_candidate.reserved_asset_id,
                        expected_design_version=(
                            compatibility_candidate.expected_design_version
                        ),
                        image_bytes=compatibility_candidate.image_bytes,
                        media_type=compatibility_candidate.media_type,
                        operation=compatibility_candidate.operation,
                        asset_capability=compatibility_candidate.asset_capability,
                        requested_change=compatibility_candidate.requested_change,
                        region_description=compatibility_candidate.region_description,
                        drift=compatibility_candidate.drift,
                        next_spec=compatibility_candidate.next_spec,
                        ignored_fields=compatibility_candidate.ignored_fields,
                        qa=compatibility_candidate.qa,
                        routing=compatibility_candidate.routing,
                        created_by=compatibility_candidate.created_by,
                    )
                )
                return {
                    "final_asset_id": None,
                    "root_id": asset.root_id,
                    "design_id": design_id,
                    "design_version": current_design_version,
                    "revision": None,
                    "spec_version": current_design_version,
                    "spec_change": [],
                    "ignored_fields": (scoped.ignored_fields
                                       if scoped is not None else []),
                    "qa": qa_report,
                    "routing": routing_summary,
                    "image_run_id": run_id,
                    "warning_candidate": {
                        "run_id": run_id,
                        "candidate_id": candidate.candidate_id,
                        "preview_url": (
                            f"/studio/markup-candidates/{run_id}/"
                            f"{candidate.candidate_id}/image"
                            if request.studio_job_id is not None
                            else f"/image-runs/{run_id}/candidates/"
                            f"{candidate.candidate_id}/image"
                        ),
                        "qa": qa_report,
                        "operation": operation.value,
                        "requested_change": note.change_instruction,
                        "studio_job_id": getattr(candidate, "studio_job_id", None),
                        "save_as_variation_url": (
                            f"/studio/markup-candidates/{run_id}/"
                            f"{candidate.candidate_id}/save-as-variation"
                            if request.studio_job_id is not None else None
                        ),
                    },
                    "steps": steps,
                }
            result = {
                "image": image_agent_result.image_bytes,
                "drift": next((
                    check.evidence.get("drift")
                    for check in image_agent_result.quality.checks
                    if check.code == "outside_mask_drift"
                ), None),
                "retried": len(image_agent_result.run.attempts) > 1,
                "qa_report": qa_report,
                "routing": routing_summary,
            }
        else:
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

        # Component geometry for the accepted child must come from a vision
        # mapper over the actual output bytes. It is resolved and reconciled
        # before the short image/spec/map transaction; no generic geometry or
        # copied polygon is invented when the mapper cannot identify a part.
        child_component_map = None
        if note.target_component_id is not None:
            reserved_asset_id = reserved_asset_id or new_id("ast")
            try:
                proposed_component_map = _revision_component_mapper(
                    parent_map=parent_component_map,
                    parent_image=bytes(current.image),
                    child_asset_id=reserved_asset_id,
                    child_image=result["image"],
                    target_component_id=note.target_component_id,
                    instruction=note.change_instruction,
                )
                if proposed_component_map.asset_id != reserved_asset_id:
                    raise ComponentMappingUnresolved(
                        "vision mapper bound the component map to the wrong "
                        "child asset identity"
                    )
                bind_map_to_raster(
                    proposed_component_map, result["image"])
                child_component_map = reconcile_parent_component_ids(
                    parent_component_map, proposed_component_map)
                bind_map_to_raster(child_component_map, result["image"])
            except ComponentMapError as exc:
                return JSONResponse(status_code=422, content={
                    "detail": exc.detail,
                    "code": exc.code,
                    "category": "validation",
                    "steps": steps,
                })

        # 3) persist the accepted image and immutable spec as one transaction.
        # Provider and validation work above intentionally happen before this
        # short write section.
        next_design_version = current_design_version
        stored = None
        changes: list[dict] = []
        if scoped is not None and current_spec is not None:
            from facetta.api.designs import _store_version
            from facetta.db import Design

            design = db.get(Design, design_id)
            latest = db.scalar(
                select(func.max(DesignVersion.version)).where(
                    DesignVersion.design_id == design_id)) or 0
            if current_design_version is not None and latest != current_design_version:
                db.rollback()
                return JSONResponse(status_code=409, content={
                    "detail": ("the design changed while the image was being "
                               "prepared; no revision was saved"),
                    "code": "stale_design_version",
                    "category": "stale_version",
                    "expected_design_version": current_design_version,
                    "current_design_version": latest,
                    "steps": steps})
            next_design_version = latest + 1
            before = current_spec.model_dump(mode="json")
        try:
            child = _store_asset(
                db, result["image"], "LOCALIZED_EDIT", current,
                asset_id=reserved_asset_id,
                instruction=note.change_instruction,
                region=note.region_description, drift=result["drift"],
                design_version=next_design_version,
                created_by=request.created_by, commit=False)
            if scoped is not None and current_spec is not None:
                stored = _store_version(
                    db, design, scoped_spec, next_design_version,
                    request.created_by, commit=False)
                changes = diff_specs(before, stored)
            if child_component_map is not None:
                add_revision_component_map(
                    db,
                    child_component_map,
                    image_bytes=result["image"],
                    parent_asset_id=current.id,
                )
            if image_agent_result is not None:
                run_id = persist_image_agent_result(
                    db,
                    image_agent_result,
                    project_root_id=asset.root_id,
                    source_asset_id=current.id,
                    accepted_asset_id=child.id,
                    created_by=request.created_by,
                    commit=False,
                )
                routing_summary["run_id"] = run_id
            db.commit()
        except Exception:
            db.rollback()
            raise

        step.update({
            "asset_id": child.id,
            "version": _version_number(_chain(db, asset.root_id), child.id),
            "design_version": next_design_version,
            "drift": result["drift"],
            "retried": result["retried"],
            "qa_report": result.get("qa_report"),
            "model_routing": result.get("routing", {
                "attempts": 2 if result.get("retried") else 1,
                "fallback_used": bool(result.get("fallback_used", False)),
            }),
            "target_component_id": note.target_component_id,
            "component_map_url": (
                f"/assets/{child.id}/component-map"
                if child_component_map is not None else None
            ),
        })

        if stored is not None:
            step.update({
                "spec_synced": True,
                "new_spec_version": next_design_version,
                "changed_fields": scoped.changed_fields,
                "ignored_fields": scoped.ignored_fields,
                "spec_change": changes,
                "changes_summary": summarize_changes(changes)})
            current_spec = scoped_spec
            current_design_version = next_design_version
        else:
            step["spec_synced"] = False
            step.setdefault(
                "spec_note", "visual-only edit; specification inherited")

        current = child
        steps.append(step)

    applied = [s for s in steps if s.get("asset_id")]
    consistency = {"checked": False}
    if applied:
        consistency = check_design_consistency(start_bytes,
                                               bytes(current.image))
    last_step = applied[-1] if applied else None
    raw_changes = last_step.get("spec_change", []) if last_step else []
    canonical_changes = [{
        "path": change["path"],
        "label": change.get("label"),
        "before": change.get("from"),
        "after": change.get("to"),
        "kind": change.get("kind"),
    } for change in raw_changes]
    revision = None
    if applied:
        revision = {
            "revision": _version_number(_chain(db, asset.root_id), current.id),
            "asset": _asset_meta(db, current),
            "spec_version": current.design_version,
            "spec_change": canonical_changes,
            "ignored_fields": last_step.get("ignored_fields", []),
            "qa": last_step.get("qa_report"),
            "routing": last_step.get("model_routing"),
            "created_at": current.created_at.isoformat(),
        }
    return {
        "final_asset_id": current.id if applied else None,
        "root_id": asset.root_id,
        "design_id": design_id,
        "design_version": (current_design_version if applied else None),
        "revision": revision,
        "spec_version": (current_design_version if applied else None),
        "spec_change": canonical_changes,
        "ignored_fields": (last_step.get("ignored_fields", [])
                           if last_step else []),
        "qa": last_step.get("qa_report") if last_step else None,
        "routing": last_step.get("model_routing") if last_step else None,
        "image_run_id": ((last_step.get("model_routing") or {}).get("run_id")
                         if last_step else None),
        "warning_candidate": None,
        "steps": steps,
        "consistency": consistency,
        "image_b64": (stamp_b64(bytes(current.image)) if applied else None),
    }


class AssetRestyleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instruction: Annotated[str, Field(min_length=1, max_length=2000)]
    kind: Literal["render", "technical"] = "render"
    use_house_style: bool = False
    created_by: str = "usr_pending"
    variant: int = 0  # regenerate: a fresh take on the SAME restyle


@router.post("/{asset_id}/global-restyle", status_code=201, deprecated=True)
def create_global_restyle(asset_id: str, request: AssetRestyleRequest,
                          db: DbSession):
    """The whole-piece change path: reference-locked, no freeze contract,
    warning instead of a drift gate — parent/child compare and revert are the
    safety net."""
    parent = _get_asset(db, asset_id)
    style_ref, model = None, "grok_direct"
    if request.use_house_style:
        from facetta.housestyle import default_style_ref
        style_ref = default_style_ref()
        if style_ref is None:
            return JSONResponse(status_code=422, content={
                "detail": "no house style references curated yet — add images "
                          "to data/style_refs/"})
        model = "grok_imagine"
    try:
        result = global_restyle(bytes(parent.image),
                                instruction=request.instruction,
                                kind=request.kind, variant=request.variant,
                                model=model, style_ref=style_ref)
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


@router.post("/{asset_id}/video", status_code=201, deprecated=True)
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
                             media_type="video/mp4",
                             created_by=request.created_by)
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
def link_design(
    asset_id: str,
    request: LinkDesignRequest,
    db: DbSession,
    principal: PrincipalDep,
):
    """Join an existing chain to the spec universe: sets design_id on the
    chain ROOT (acting on any asset in the chain). Once linked, markup edits
    also move the design's spec and the factory sheet letters the latest
    version automatically."""
    from facetta.db import Design
    from facetta.project_backbone import (
        DesignAlreadyLinked, claim_creative_project_design,
        ensure_design_chain_available,
    )

    asset = _get_asset(db, asset_id)
    design = db.get(Design, request.design_id)
    if design is None:
        raise HTTPException(status_code=404,
                            detail=f"unknown design '{request.design_id}'")
    if (
        not principal.local_unbound
        and design.created_by != principal.subject
    ):
        raise HTTPException(status_code=403, detail={
            "code": "design_access_denied",
            "error_category": "authorization",
            "detail": "the principal does not own the target design",
        })
    root = db.get(ImageAsset, asset.root_id) or asset
    try:
        ensure_design_chain_available(db, request.design_id, root.id)
    except DesignAlreadyLinked as exc:
        return JSONResponse(status_code=409, content={
            "detail": str(exc),
            "code": "design_already_linked",
            "existing_root_id": exc.root_id})
    if not claim_creative_project_design(
        db, root_id=root.id, design_id=request.design_id,
    ):
        return JSONResponse(status_code=409, content={
            "detail": "the project was linked by another request",
            "code": "design_link_conflict",
            "existing_root_id": root.id,
        })
    db.commit()
    return {"root_id": root.id, "design_id": request.design_id,
            "design_version": None,
            "provenance": "legacy_unversioned",
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


@router.get("/{asset_id}/component-map")
def get_asset_component_map(asset_id: str, db: DbSession):
    _get_asset(db, asset_id)
    try:
        component_map = load_revision_component_map(db, asset_id)
    except ComponentMapError as exc:
        return JSONResponse(status_code=409, content={
            "detail": exc.detail,
            "code": exc.code,
            "category": "validation",
        })
    if component_map is None:
        return JSONResponse(status_code=404, content={
            "detail": "this visual revision has no component map",
            "code": "component_map_not_found",
            "category": "validation",
        })
    return component_map.model_dump(mode="json")


@router.get("/{asset_id}/components/{component_id}/mask")
def get_asset_component_mask(
    asset_id: str,
    component_id: str,
    db: DbSession,
):
    _get_asset(db, asset_id)
    try:
        component_map = load_revision_component_map(db, asset_id)
        if component_map is None:
            raise ComponentMapError(
                "this visual revision has no component map",
                code="component_map_not_found",
            )
        mask = rasterize_component_mask(component_map, component_id)
    except ComponentMapError as exc:
        status = 404 if exc.code in {
            "component_map_not_found", "target_component_not_found"
        } else 422
        return JSONResponse(status_code=status, content={
            "detail": exc.detail,
            "code": exc.code,
            "category": "validation",
        })
    return Response(
        content=mask,
        media_type="image/png",
        headers={
            "X-Facetta-Asset-Id": asset_id,
            "X-Facetta-Component-Id": component_id,
        },
    )


@router.get("/{asset_id}/image")
def get_asset_image(asset_id: str, db: DbSession, principal: PrincipalDep):
    asset = _get_asset(db, asset_id)
    project = db.get(Project, asset.root_id)
    if (
        project is not None
        and not principal.local_unbound
        and project.owner != principal.subject
    ):
        raise HTTPException(status_code=404, detail="asset image not found")
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
            "asset_id": a.id,
            "version": _version_number(chain, a.id),
            "revision": (_version_number(chain, a.id)
                         if _is_primary_revision(a) else None),
            "derived_from_revision": (None if _is_primary_revision(a)
                                      else _version_number(chain, a.id)),
            "chain_position": i,
            "parent_asset_id": a.parent_asset_id,
            "capability": a.capability, "region": a.region,
            "instruction": a.instruction, "drift": a.drift,
            "design_version": a.design_version,
            "image_url": f"/assets/{a.id}/image",
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


def _exact_linked_design(db: Session, asset: ImageAsset):
    """Resolve the specification explicitly represented by ``asset``.

    Unlike ``_linked_design`` this never substitutes the latest spec for an
    older visual.  A NULL version is returned as unknown legacy provenance.
    """
    root = db.get(ImageAsset, asset.root_id) or asset
    if not root.design_id or asset.design_version is None:
        return None
    row = db.get(DesignVersion, (root.design_id, asset.design_version))
    if row is None:
        return None
    result = validate_spec(Spec.model_validate(row.spec), get_vocabulary())
    if not result.ok:
        return None
    return root.design_id, row.version, result.spec


def _requires_creative_spec_promotion(
    db: Session,
    asset: ImageAsset,
) -> bool:
    """Keep every pre-spec primary outside approval and factory authority."""

    if asset.capability == "CREATIVE_RENDER":
        return True
    if asset.capability in {"VARIATION_BRANCH", "RESTORED_REVISION"}:
        return _exact_linked_design(db, asset) is None
    return False


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


@router.post("/{asset_id}/pin", deprecated=True)
def pin_asset(asset_id: str, db: DbSession, principal: PrincipalDep):
    """Pin this version for factory: the manufacturing technical drawing is
    generated from the chain's pinned asset, never silently from 'latest'.
    Pinning a new version supersedes the previous pin (latest pin wins).

    Gated by the approval checklist when one exists for this asset (and its
    mode isn't 'optional'): every item must be approved first — the tap-tap
    ritual IS the road to the factory. No checklist → pin behaves as always."""
    asset = _get_asset(db, asset_id)
    _approval_actor(principal, None, asset)
    _lock_approval_generation_for_write(db, asset)
    if _requires_creative_spec_promotion(db, asset):
        return JSONResponse(status_code=409, content={
            "detail": (
                "creative candidates must be promoted with a designer-confirmed "
                "specification before approval or factory pinning"
            ),
            "code": "creative_candidate_requires_spec_promotion",
        })
    if not _is_primary_revision(asset):
        return JSONResponse(status_code=409, content={
            "detail": "only a primary render or edit can be pinned; derived "
                      "notes, views, videos, and drawings belong to their "
                      "source revision",
            "code": "derived_asset_not_approvable"})
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
    created_by: Annotated[str, Field(min_length=1, max_length=32)] | None = None


@router.post("/{asset_id}/checklist", status_code=201)
def create_checklist(asset_id: str, request: ChecklistCreateRequest,
                     db: DbSession, principal: PrincipalDep):
    """Start the tap-to-approve ritual for this exact version. Items are
    facts derived from the piece's own spec sections — jewelry-type aware by
    construction (a ring asks about its band; a necklace about its chain).
    The spec comes from the body, else the chain's design link; with neither
    there is nothing to derive facts from → 409."""
    asset = _get_asset(db, asset_id)
    actor = _approval_actor(principal, request.created_by, asset)
    _lock_approval_generation_for_write(db, asset)
    if _requires_creative_spec_promotion(db, asset):
        return JSONResponse(status_code=409, content={
            "detail": (
                "creative candidates are review-only; confirm and persist an "
                "exact specification before creating an approval checklist"
            ),
            "code": "creative_candidate_requires_spec_promotion",
        })
    if not _is_primary_revision(asset):
        return JSONResponse(status_code=409, content={
            "detail": "approval checklists bind to primary visual revisions",
            "code": "derived_asset_not_approvable"})
    linked = _exact_linked_design(db, asset)
    validated = None
    if request.spec is not None:
        result = validate_spec(request.spec, get_vocabulary())
        if not result.ok:
            return JSONResponse(status_code=422, content={
                "detail": [issue.as_detail() for issue in result.issues]})
        validated = result.spec
        if (linked is not None
                and _approval_spec_payload(validated)
                != _approval_spec_payload(linked[2])):
            return JSONResponse(status_code=409, content={
                "detail": (
                    "the submitted checklist specification does not match "
                    "this revision's exact immutable specification"
                ),
                "code": "checklist_spec_mismatch",
            })
        if linked is not None:
            validated = linked[2]
    else:
        if linked:
            _, _, validated = linked
        elif (db.get(ImageAsset, asset.root_id) or asset).design_id:
            return JSONResponse(status_code=409, content={
                "detail": ("this asset has legacy provenance with no exact "
                           "design version; create a new spec-aligned revision "
                           "before approval"),
                "code": "legacy_provenance_not_approvable"})
    if validated is None:
        return JSONResponse(status_code=409, content={
            "detail": "no spec to derive checklist items from — pass a spec "
                      "or link the chain to a design "
                      "(PATCH /assets/{id}/link-design)"})

    items = [i.model_dump() for i in build_checklist_items(validated)]
    checklist = ApprovalChecklist(
        id=new_id("chk"), asset_id=asset.id,
        design_id=(linked[0] if linked else None),
        design_version=(asset.design_version
                        if asset.design_version is not None else
                        (linked[1] if linked else None)),
        mode=request.mode, items=items,
        created_by=actor)
    db.add(checklist)
    db.commit()
    return {"checklist_id": checklist.id, "asset_id": asset.id,
            "version": _version_number(_chain(db, asset.root_id), asset.id),
            "design_id": checklist.design_id,
            "design_version": checklist.design_version,
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
            "design_id": checklist.design_id,
            "design_version": checklist.design_version,
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
    created_by: Annotated[str, Field(min_length=1, max_length=32)] | None = None
    assistant_name: str | None = None


@router.post("/{asset_id}/checklist/respond", status_code=201)
def respond_checklist(asset_id: str, request: ChecklistRespondRequest,
                      db: DbSession, principal: PrincipalDep):
    """One tap. YES approves the fact. NO requires the change note (the WHOOP
    journal rule) and comes back with an agent-ready change request prefill —
    and, with interpret=true, the agent's understood-as echo the designer
    confirms BEFORE anything executes. In auto_pin mode the last YES pins the
    version for factory. Append-only: every tap is an audit row."""
    asset = _get_asset(db, asset_id)
    actor = _approval_actor(principal, request.created_by, asset)
    _lock_approval_generation_for_write(db, asset)
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

    # A negative tap is committed before its optional network interpretation,
    # so it immediately invalidates Factory eligibility. Positive taps have no
    # network step and commit atomically with status calculation and auto-pin.
    row = ApprovalResponse(
        checklist_id=checklist.id, item_key=request.item_key,
        approved=request.approved, note=note or None,
        created_by=actor)
    db.add(row)
    if request.approved:
        db.flush()
    else:
        db.commit()

    out: dict = {"checklist_id": checklist.id, "item_key": request.item_key,
                 "approved": request.approved}

    linked = _exact_linked_design(db, asset)
    if not request.approved:
        # The checklist fact maps 1:1 onto the single canonical markup
        # instruction.  The designer first supplies/reads the marked canvas,
        # confirms the interpretation, then applies this exact-version prefill.
        annotation = {
            "region_description": f"the {item['label'].lower()}",
            "change_instruction": note,
            "target_ref": item.get("ref"),
            "target_section": item["section"],
            "index": item.get("index"),
        }
        if item.get("target_element_id"):
            annotation["target_element_id"] = item["target_element_id"]
        expected_design_version = (
            linked[1] if linked else checklist.design_version)
        apply_body: dict = {
            "annotations": [annotation],
            "created_by": actor,
        }
        if expected_design_version is not None:
            apply_body["expected_design_version"] = expected_design_version
        out["change_request"] = {
            "workflow": "markup_read_then_apply",
            "annotation_prefill": annotation,
            "markup_read": {
                "method": "POST",
                "endpoint": f"/assets/{asset.id}/markup/read",
                "body_requires": ["marked_image_base64"],
                "mutates_project": False,
            },
            "markup_apply": {
                "method": "POST",
                "endpoint": f"/assets/{asset.id}/markup/apply",
                "body": apply_body,
                "requires_designer_confirmation": True,
            },
            "endpoints": [f"POST /assets/{asset.id}/markup/read",
                          f"POST /assets/{asset.id}/markup/apply"],
            "design_id": (linked[0] if linked else checklist.design_id),
            "design_version": expected_design_version,
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
        chain = _chain(db, asset.root_id)
        out["pinned"] = True
        out["pinned_version"] = _version_number(chain, asset.id)
        out["message"] = (f"All {status['total']} checks approved — pinned "
                          f"version {out['pinned_version']} for factory")
    else:
        out["pinned"] = asset.pinned_at is not None
    if request.approved:
        db.commit()
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


@router.post("/{asset_id}/technical-drawing", deprecated=True)
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
        linked = _exact_linked_design(db, source)
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

# --- the correction flywheel: designer verdicts on generated assets ----------
#
# Raw data first, learning later: every accepted / regenerated / rejected tap
# is filed append-only against its asset. The stats endpoint aggregates
# success per capability and instruction so the prompt library can eventually
# be tuned from the house's own usage — no prompt ever mutates automatically.


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["accepted", "regenerated", "rejected"]
    note: Annotated[str, Field(max_length=1000)] | None = None
    created_by: str = "usr_pending"


@router.post("/{asset_id}/feedback", status_code=201)
def record_feedback(
    asset_id: str,
    request: FeedbackRequest,
    db: DbSession,
    principal: PrincipalDep,
):
    """One designer verdict on one generated image — append-only."""
    actor = principal_actor(principal, request.created_by)
    asset = _get_asset(db, asset_id)
    row = FeedbackEvent(asset_id=asset.id, action=request.action,
                        note=request.note, created_by=actor)
    db.add(row)
    db.commit()
    return {"asset_id": asset.id, "action": request.action,
            "capability": asset.capability}


@router.get("/insights/instruction-stats")
def instruction_stats(db: DbSession, principal: PrincipalDep):
    """The flywheel readout: per capability (and per instruction within it),
    how often the designer accepted vs regenerated vs rejected. This is the
    dataset the prompt-tuning step will read — served raw, judged by humans."""
    query = (
        select(FeedbackEvent.action, ImageAsset.capability,
               ImageAsset.instruction)
        .join(ImageAsset, ImageAsset.id == FeedbackEvent.asset_id)
        .outerjoin(Project, Project.root_id == ImageAsset.root_id)
    )
    if not principal.local_unbound:
        query = query.where(
            (Project.owner == principal.subject)
            | (
                Project.root_id.is_(None)
                & (ImageAsset.created_by == principal.subject)
            )
        )
    rows = db.execute(query).all()
    by_capability: dict[str, dict] = {}
    for action, capability, instruction in rows:
        cap = by_capability.setdefault(capability or "UNKNOWN", {
            "accepted": 0, "regenerated": 0, "rejected": 0, "instructions": {}})
        cap[action] += 1
        if instruction:
            ins = cap["instructions"].setdefault(
                instruction[:120],
                {"accepted": 0, "regenerated": 0, "rejected": 0})
            ins[action] += 1
    for cap in by_capability.values():
        total = cap["accepted"] + cap["regenerated"] + cap["rejected"]
        cap["acceptance_rate"] = (round(cap["accepted"] / total, 3)
                                  if total else None)
    return {"events": len(rows), "by_capability": by_capability}

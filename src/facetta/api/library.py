"""The designer's library: everything they've generated, organized and
searchable.

Proven model, three levels: the LIBRARY (all of an owner's work) → COLLECTIONS
(client folders — "Sarah K — engagement" — or personal ones) → PROJECTS (one
design chain: a hero render and all its edits, views, videos, and factory
drawings). Tags and free-text search cut across collections to locate a piece
fast. Metadata lives on projects (facetta.db.Project); the images themselves
stay in the asset chain.
"""

from __future__ import annotations

import base64
from collections import Counter
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from facetta.db import ImageAsset, Project, get_db
from facetta.disclaimer import is_stampable, stamp_b64

# a factory technical drawing carries its own dimension-honesty disclaimer; the
# "preview may vary" caption is for client-facing photoreal renders only
_UNSTAMPED_CAPS = {"MANUFACTURING_TECHNICAL_DRAWING"}

router = APIRouter(tags=["library"])

DbSession = Annotated[Session, Depends(get_db)]


def _chain(db: Session, root_id: str) -> list[ImageAsset]:
    return list(db.scalars(
        select(ImageAsset).where(ImageAsset.root_id == root_id)
        .order_by(ImageAsset.created_at, ImageAsset.id)))


def _cover_asset(chain: list[ImageAsset]) -> ImageAsset | None:
    """The card thumbnail: the pinned version if any, else the most recent
    still image, else the root."""
    pinned = [a for a in chain if a.pinned_at is not None]
    if pinned:
        return max(pinned, key=lambda a: a.pinned_at)
    images = [a for a in chain if a.media_type.startswith("image/")]
    return (images[-1] if images else (chain[-1] if chain else None))


def _project_card(db: Session, project: Project) -> dict:
    chain = _chain(db, project.root_id)
    kinds = Counter(a.capability for a in chain)
    cover = _cover_asset(chain)
    return {
        "root_id": project.root_id,
        "title": project.title,
        "collection": project.collection or "Unfiled",
        "tags": project.tags or [],
        "owner": project.owner,
        "counts": dict(kinds),
        "item_count": len(chain),
        "has_factory_drawing": any(
            a.capability == "MANUFACTURING_TECHNICAL_DRAWING" for a in chain),
        "cover_asset_id": cover.id if cover else None,
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
    }


def _searchable_text(db: Session, project: Project) -> str:
    parts = [project.title, project.collection or "", " ".join(project.tags or [])]
    parts += [a.instruction or "" for a in _chain(db, project.root_id)]
    return " ".join(parts).lower()


@router.get("/library")
def search_library(db: DbSession, owner: str | None = None,
                   collection: str | None = None, q: str | None = None,
                   tag: str | None = None, sort: str = "recent",
                   limit: int = 50, offset: int = 0):
    """Search and list projects. Filters: owner, collection (exact folder),
    tag; q is free-text over title, collection, tags, and the chain's prompts.
    sort: recent (updated desc) | created | title."""
    stmt = select(Project)
    if owner:
        stmt = stmt.where(Project.owner == owner)
    if collection is not None:
        stmt = (stmt.where(Project.collection.is_(None)) if collection == "Unfiled"
                else stmt.where(Project.collection == collection))
    projects = list(db.scalars(stmt))

    if tag:
        projects = [p for p in projects if tag in (p.tags or [])]
    if q:
        needle = q.lower().strip()
        projects = [p for p in projects if needle in _searchable_text(db, p)]

    if sort == "title":
        projects.sort(key=lambda p: p.title.lower())
    elif sort == "created":
        projects.sort(key=lambda p: p.created_at, reverse=True)
    else:
        projects.sort(key=lambda p: p.updated_at, reverse=True)

    total = len(projects)
    page = projects[offset:offset + limit]
    return {"total": total, "limit": limit, "offset": offset,
            "projects": [_project_card(db, p) for p in page]}


@router.get("/library/collections")
def list_collections(db: DbSession, owner: str | None = None):
    """The folder sidebar: every collection with its project count, plus the
    Unfiled bucket. Sorted by size."""
    stmt = select(Project)
    if owner:
        stmt = stmt.where(Project.owner == owner)
    projects = list(db.scalars(stmt))
    counts: Counter = Counter((p.collection or "Unfiled") for p in projects)
    folders = [{"collection": name, "project_count": n}
               for name, n in counts.most_common()]
    return {"owner": owner, "total_projects": len(projects),
            "collections": folders}


@router.get("/library/tags")
def list_tags(db: DbSession, owner: str | None = None):
    """Every tag in use with its frequency — the tag cloud / filter chips."""
    stmt = select(Project)
    if owner:
        stmt = stmt.where(Project.owner == owner)
    counts: Counter = Counter()
    for p in db.scalars(stmt):
        counts.update(p.tags or [])
    return {"tags": [{"tag": t, "count": n} for t, n in counts.most_common()]}


@router.get("/projects/{root_id}")
def get_project(root_id: str, db: DbSession, include_images: bool = False):
    """One project: its metadata plus every asset in the chain grouped by
    kind (renders, edits, views, videos, drawings). ?include_images=true
    inlines the base64 for each asset."""
    project = db.get(Project, root_id)
    if project is None:
        raise HTTPException(status_code=404,
                            detail=f"no project for chain '{root_id}'")
    chain = _chain(db, root_id)

    def item(a: ImageAsset) -> dict:
        d = {"asset_id": a.id, "capability": a.capability,
             "parent_asset_id": a.parent_asset_id, "region": a.region,
             "instruction": a.instruction, "drift": a.drift,
             "pinned": a.pinned_at is not None, "media_type": a.media_type,
             "created_at": a.created_at.isoformat()}
        if include_images:
            raw = bytes(a.image)
            d["image_b64"] = (
                stamp_b64(raw) if (a.capability not in _UNSTAMPED_CAPS
                                   and is_stampable(a.media_type))
                else base64.b64encode(raw).decode())
        return d

    return {**_project_card(db, project),
            "items": [item(a) for a in chain]}

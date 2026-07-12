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

from collections import Counter
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from facetta.api.projects import project_card, project_chain
from facetta.db import Project, get_db

router = APIRouter(tags=["library"])

DbSession = Annotated[Session, Depends(get_db)]


def _searchable_text(db: Session, project: Project) -> str:
    parts = [project.title, project.collection or "", " ".join(project.tags or [])]
    parts += [a.instruction or "" for a in project_chain(db, project.root_id)]
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
            "projects": [project_card(db, p) for p in page]}


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

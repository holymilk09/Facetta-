"""Owner-scoped Collections that organize families without touching lineage."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from facetta.auth import AuthenticatedPrincipal, require_principal_boundary
from facetta.db import (
    COLLECTION_TEMPLATES,
    CollectionFamilyMembership,
    DesignFamily,
    Project,
    WorkspaceCollection,
    get_db,
    new_id,
    normalize_collection_name,
    normalize_family_tags,
    utcnow,
)
from facetta.json_types import JsonObject


router = APIRouter(prefix="/studio", tags=["studio-organization"])
DbSession = Annotated[Session, Depends(get_db)]
PrincipalDep = Annotated[
    AuthenticatedPrincipal, Depends(require_principal_boundary)
]
CollectionTemplate = Literal[
    "generic",
    "client",
    "order",
    "project",
    "campaign",
    "season",
    "jewelry_line",
    "personal_study",
    "custom",
]


class CollectionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=120)]
    template: CollectionTemplate = "generic"
    metadata: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_normalized_values(self) -> CollectionCreateRequest:
        if not normalize_collection_name(self.name)[0]:
            raise ValueError("collection name must contain visible characters")
        if len(json.dumps(self.metadata, separators=(",", ":"))) > 8_000:
            raise ValueError("collection metadata is too large")
        return self


class CollectionUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=120)] | None = None
    template: CollectionTemplate | None = None
    metadata: JsonObject | None = None
    archived: bool | None = None

    @model_validator(mode="after")
    def validate_update(self) -> CollectionUpdateRequest:
        if not self.model_fields_set:
            raise ValueError("at least one collection change is required")
        if self.name is not None and not normalize_collection_name(self.name)[0]:
            raise ValueError("collection name must contain visible characters")
        if (
            self.metadata is not None
            and len(json.dumps(self.metadata, separators=(",", ":"))) > 8_000
        ):
            raise ValueError("collection metadata is too large")
        return self


class FamilyTagsUpdateRequest(BaseModel):
    """Canonical family organization only; never a design edit."""

    model_config = ConfigDict(extra="forbid")

    tags: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=40)]],
        Field(max_length=24),
    ] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_tags(self) -> FamilyTagsUpdateRequest:
        if any(any(ord(character) < 32 for character in tag) for tag in self.tags):
            raise ValueError("tags cannot contain control characters")
        return self


def _requested_owner(
    principal: AuthenticatedPrincipal,
    owner: str | None,
) -> str | None:
    if principal.local_unbound:
        return owner
    if owner is not None and owner != principal.subject:
        # Do not turn an owner query into a cross-tenant existence oracle.
        raise HTTPException(status_code=404, detail="collection not found")
    return principal.subject


def _local_workspace_owners(db: Session) -> set[str]:
    owners = set(db.scalars(select(DesignFamily.owner).distinct()))
    owners.update(db.scalars(select(Project.owner).distinct()))
    owners.update(db.scalars(select(WorkspaceCollection.owner).distinct()))
    return {owner for owner in owners if owner}


def _single_local_owner(db: Session, owner: str | None) -> str:
    if owner is not None:
        return owner
    owners = _local_workspace_owners(db)
    if len(owners) != 1:
        raise HTTPException(
            status_code=422,
            detail="owner is required unless the local workspace has exactly one owner",
        )
    return next(iter(owners))


def _owned_collection(
    db: Session,
    principal: AuthenticatedPrincipal,
    collection_id: str,
) -> WorkspaceCollection:
    collection = db.get(WorkspaceCollection, collection_id)
    if (
        collection is None
        or collection.deleted_at is not None
        or (
            not principal.local_unbound
            and collection.owner != principal.subject
        )
    ):
        raise HTTPException(status_code=404, detail="collection not found")
    return collection


def _owned_family(
    db: Session,
    principal: AuthenticatedPrincipal,
    family_id: str,
) -> DesignFamily:
    family = db.get(DesignFamily, family_id)
    if (
        family is None
        or (
            not principal.local_unbound
            and family.owner != principal.subject
        )
    ):
        raise HTTPException(status_code=404, detail="design family not found")
    return family


def _collection_summary(db: Session, collection: WorkspaceCollection) -> dict:
    family_count = len(list(db.scalars(
        select(CollectionFamilyMembership.family_id)
        .join(
            DesignFamily,
            DesignFamily.id == CollectionFamilyMembership.family_id,
        )
        .where(
            CollectionFamilyMembership.collection_id == collection.id,
            CollectionFamilyMembership.owner == collection.owner,
            CollectionFamilyMembership.removed_at.is_(None),
            DesignFamily.owner == collection.owner,
        )
    )))
    return {
        "id": collection.id,
        "name": collection.name,
        "template": collection.template,
        "metadata": collection.template_metadata,
        "archived_at": (
            collection.archived_at.isoformat()
            if collection.archived_at is not None else None
        ),
        "created_at": collection.created_at.isoformat(),
        "updated_at": collection.updated_at.isoformat(),
        "family_count": family_count,
    }


def _remove_active_memberships(
    db: Session,
    collection: WorkspaceCollection,
    *,
    at: datetime,
) -> None:
    memberships = list(db.scalars(
        select(CollectionFamilyMembership).where(
            CollectionFamilyMembership.collection_id == collection.id,
            CollectionFamilyMembership.owner == collection.owner,
            CollectionFamilyMembership.removed_at.is_(None),
        )
    ))
    for membership in memberships:
        membership.removed_at = at
        membership.updated_at = at


@router.get("/collections")
def list_collections(
    db: DbSession,
    principal: PrincipalDep,
    q: Annotated[str | None, Query(max_length=120)] = None,
    include_archived: bool = False,
    owner: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
):
    """List or search optional Collections in the principal's workspace."""

    effective_owner = _requested_owner(principal, owner)
    if principal.local_unbound:
        effective_owner = _single_local_owner(db, effective_owner)
    query = select(WorkspaceCollection).where(
        WorkspaceCollection.deleted_at.is_(None)
    )
    if effective_owner is not None:
        query = query.where(WorkspaceCollection.owner == effective_owner)
    if not include_archived:
        query = query.where(WorkspaceCollection.archived_at.is_(None))
    collections = list(db.scalars(
        query.order_by(WorkspaceCollection.updated_at.desc(),
                       WorkspaceCollection.id)
    ))
    if q is not None and (needle := q.strip().casefold()):
        collections = [
            collection for collection in collections
            if needle in collection.name.casefold()
        ]
    return {
        "collections": [
            _collection_summary(db, collection) for collection in collections
        ],
    }


@router.get("/collection-memberships")
def list_collection_memberships(
    db: DbSession,
    principal: PrincipalDep,
    owner: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
):
    """Return active visible Collection IDs grouped by Design Family."""

    effective_owner = _requested_owner(principal, owner)
    if principal.local_unbound:
        effective_owner = _single_local_owner(db, effective_owner)
    rows = db.execute(
        select(
            DesignFamily.id,
            WorkspaceCollection.id,
        )
        .outerjoin(
            CollectionFamilyMembership,
            and_(
                CollectionFamilyMembership.family_id == DesignFamily.id,
                CollectionFamilyMembership.owner == effective_owner,
                CollectionFamilyMembership.removed_at.is_(None),
            ),
        )
        .outerjoin(
            WorkspaceCollection,
            and_(
                WorkspaceCollection.id
                == CollectionFamilyMembership.collection_id,
                WorkspaceCollection.owner == effective_owner,
                WorkspaceCollection.archived_at.is_(None),
                WorkspaceCollection.deleted_at.is_(None),
            ),
        )
        .where(DesignFamily.owner == effective_owner)
        .order_by(
            DesignFamily.id,
            WorkspaceCollection.name_key,
            WorkspaceCollection.id,
        )
    )
    grouped: dict[str, list[str]] = {}
    for family_id, collection_id in rows:
        collection_ids = grouped.setdefault(family_id, [])
        if collection_id is not None:
            collection_ids.append(collection_id)
    return {"family_collection_ids": grouped}


def _favorite_family(
    db: Session,
    principal: AuthenticatedPrincipal,
    family_id: str,
    owner: str | None,
) -> DesignFamily:
    family = db.get(DesignFamily, family_id)
    if principal.local_unbound:
        # The path already names one stable family, so its persisted owner is
        # unambiguous even when a local development database contains several
        # workspaces. An explicit owner remains an accidental-cross-workspace
        # guard, but older local clients do not need it merely to favorite the
        # family they just loaded.
        if family is None or (owner is not None and family.owner != owner):
            raise HTTPException(status_code=404, detail="design family not found")
        return family
    effective_owner = _requested_owner(principal, owner)
    if family is None or family.owner != effective_owner:
        raise HTTPException(status_code=404, detail="design family not found")
    return family


@router.put("/design-families/{family_id}/favorite", status_code=204)
def favorite_design_family(
    family_id: str,
    db: DbSession,
    principal: PrincipalDep,
    owner: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
):
    family = _favorite_family(db, principal, family_id, owner)
    if family.favorited_at is None:
        family.favorited_at = utcnow()
        db.commit()
    return Response(status_code=204)


@router.delete("/design-families/{family_id}/favorite", status_code=204)
def unfavorite_design_family(
    family_id: str,
    db: DbSession,
    principal: PrincipalDep,
    owner: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
):
    family = _favorite_family(db, principal, family_id, owner)
    if family.favorited_at is not None:
        family.favorited_at = None
        db.commit()
    return Response(status_code=204)


@router.put("/design-families/{family_id}/tags")
def update_design_family_tags(
    family_id: str,
    request: FamilyTagsUpdateRequest,
    db: DbSession,
    principal: PrincipalDep,
    owner: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
):
    """Replace canonical search tags without touching family design activity."""

    family = _favorite_family(db, principal, family_id, owner)
    normalized = normalize_family_tags(request.tags)
    if family.tags != normalized:
        family.tags = normalized
        db.commit()
    return {"family_id": family.id, "tags": list(family.tags or [])}


@router.post("/collections", status_code=201)
def create_collection(
    request: CollectionCreateRequest,
    db: DbSession,
    principal: PrincipalDep,
    owner: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
):
    effective_owner = _requested_owner(principal, owner)
    if effective_owner is None:
        # Local preview has no bearer subject. Reuse its one existing workspace
        # owner when unambiguous; a brand-new local workspace gets a stable
        # non-production identity. Multiple local tenants must opt in with the
        # explicit owner query rather than being merged accidentally.
        local_owners = set(db.scalars(select(DesignFamily.owner).distinct()))
        local_owners.update(db.scalars(select(Project.owner).distinct()))
        if len(local_owners) > 1:
            raise HTTPException(
                status_code=422,
                detail="owner is required for a multi-owner local workspace",
            )
        effective_owner = next(iter(local_owners), "usr_local")
    display_name, name_key = normalize_collection_name(request.name)
    collection = WorkspaceCollection(
        id=new_id("col"),
        owner=effective_owner,
        name=display_name,
        name_key=name_key,
        template=request.template,
        template_metadata=dict(request.metadata),
    )
    db.add(collection)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="an active collection already uses that name",
        )
    db.refresh(collection)
    return _collection_summary(db, collection)


@router.patch("/collections/{collection_id}")
def update_collection(
    collection_id: str,
    request: CollectionUpdateRequest,
    db: DbSession,
    principal: PrincipalDep,
):
    collection = _owned_collection(db, principal, collection_id)
    now = utcnow()
    if request.archived is False and collection.deleted_at is not None:
        raise HTTPException(status_code=409, detail="deleted collection cannot be restored")
    if request.name is not None:
        collection.name, normalized = normalize_collection_name(request.name)
        if collection.archived_at is None:
            collection.name_key = normalized
    if request.template is not None:
        # Kept explicit even though Pydantic already validates the Literal, so
        # persistence callers share the same model contract.
        if request.template not in COLLECTION_TEMPLATES:  # pragma: no cover
            raise HTTPException(status_code=422, detail="unknown collection template")
        collection.template = request.template
    if request.metadata is not None:
        collection.template_metadata = dict(request.metadata)
    if request.archived is True and collection.archived_at is None:
        collection.archived_at = now
        collection.name_key = None
        _remove_active_memberships(db, collection, at=now)
    elif request.archived is False and collection.archived_at is not None:
        collection.archived_at = None
        collection.name_key = normalize_collection_name(collection.name)[1]
    collection.updated_at = now
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="an active collection already uses that name",
        )
    db.refresh(collection)
    return _collection_summary(db, collection)


@router.delete("/collections/{collection_id}", status_code=204)
def delete_collection(
    collection_id: str,
    db: DbSession,
    principal: PrincipalDep,
) -> Response:
    collection = _owned_collection(db, principal, collection_id)
    now = utcnow()
    _remove_active_memberships(db, collection, at=now)
    collection.archived_at = collection.archived_at or now
    collection.deleted_at = now
    collection.name_key = None
    collection.updated_at = now
    db.commit()
    return Response(status_code=204)


@router.get("/design-families/{family_id}/collections")
def list_family_collections(
    family_id: str,
    db: DbSession,
    principal: PrincipalDep,
):
    family = _owned_family(db, principal, family_id)
    collections = list(db.scalars(
        select(WorkspaceCollection)
        .join(
            CollectionFamilyMembership,
            CollectionFamilyMembership.collection_id
            == WorkspaceCollection.id,
        )
        .where(
            CollectionFamilyMembership.family_id == family.id,
            CollectionFamilyMembership.owner == family.owner,
            CollectionFamilyMembership.removed_at.is_(None),
            WorkspaceCollection.owner == family.owner,
            WorkspaceCollection.archived_at.is_(None),
            WorkspaceCollection.deleted_at.is_(None),
        )
        .order_by(WorkspaceCollection.name_key, WorkspaceCollection.id)
    ))
    return {
        "collections": [
            _collection_summary(db, collection) for collection in collections
        ],
    }


@router.put(
    "/design-families/{family_id}/collections/{collection_id}",
    status_code=204,
)
def add_family_to_collection(
    family_id: str,
    collection_id: str,
    db: DbSession,
    principal: PrincipalDep,
) -> Response:
    family = _owned_family(db, principal, family_id)
    collection = _owned_collection(db, principal, collection_id)
    if family.owner != collection.owner:
        raise HTTPException(status_code=404, detail="collection not found")
    if collection.archived_at is not None:
        raise HTTPException(status_code=409, detail="collection is archived")
    now = utcnow()
    membership = db.get(
        CollectionFamilyMembership, (collection.id, family.id),
    )
    if membership is None:
        db.add(CollectionFamilyMembership(
            collection_id=collection.id,
            family_id=family.id,
            owner=family.owner,
            created_at=now,
            updated_at=now,
        ))
    else:
        if membership.owner != family.owner:
            raise HTTPException(status_code=409, detail="invalid collection membership")
        membership.removed_at = None
        membership.updated_at = now
    db.commit()
    return Response(status_code=204)


@router.delete(
    "/design-families/{family_id}/collections/{collection_id}",
    status_code=204,
)
def remove_family_from_collection(
    family_id: str,
    collection_id: str,
    db: DbSession,
    principal: PrincipalDep,
) -> Response:
    family = _owned_family(db, principal, family_id)
    collection = _owned_collection(db, principal, collection_id)
    if family.owner != collection.owner:
        raise HTTPException(status_code=404, detail="collection not found")
    membership = db.get(
        CollectionFamilyMembership, (collection.id, family.id),
    )
    if membership is not None and membership.removed_at is None:
        now = utcnow()
        membership.removed_at = now
        membership.updated_at = now
        db.commit()
    return Response(status_code=204)

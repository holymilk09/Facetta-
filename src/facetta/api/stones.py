"""The stone library: real stones on file, reusable across designs.

A designer records a stone once (species, cut, exact mm, carat, lab
inscription) and tries it in any design. The swap rule is architectural:
because every drawing derives from the spec, replacing the stone re-derives
only the stone and its mounting (seat, prongs, halo envelope) — the band,
ring size, chain and every other dimension of the piece stay exactly as
designed. Fit validators flag combinations that stop working (a halo whose
melee no longer fit, a station stone wider than the band).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from facetta.db import SavedStone, get_db, new_id
from facetta.spec import Spec, Stone
from facetta.validation import validate_spec
from facetta.vocabulary import get_vocabulary

router = APIRouter(tags=["stones"])

DbSession = Annotated[Session, Depends(get_db)]


class StoneSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created_by: str
    label: Annotated[str, Field(min_length=1, max_length=120)]
    stone: Stone


def _stone_json(row: SavedStone) -> dict:
    return {"stone_id": row.id, "created_by": row.created_by, "label": row.label,
            "stone": row.stone, "created_at": row.created_at}


@router.post("/stones", status_code=201)
def save_stone(submission: StoneSubmission, db: DbSession):
    """File a stone in the library. It is validated standalone (vocabulary +
    density) exactly like a loose-stone spec's stone section."""
    probe = Spec.model_validate({
        "schema_version": 1, "design_id": "dsn_probe", "version": 1,
        "created_by": submission.created_by,
        "created_at": "1970-01-01T00:00:00Z",
        "jewelry_type": "loose_stone", "template": "loose_stone",
        "mode": "pro", "stone": submission.stone.model_dump(),
        "side_stones": [],
    })
    result = validate_spec(probe, get_vocabulary())
    if not result.ok:
        return JSONResponse(
            status_code=422,
            content={"detail": [issue.as_detail() for issue in result.issues]},
        )
    row = SavedStone(id=new_id("stn"), created_by=submission.created_by,
                     label=submission.label,
                     stone=result.spec.stone.model_dump(mode="json"))
    db.add(row)
    db.commit()
    db.refresh(row)
    return _stone_json(row)


@router.get("/stones")
def list_stones(db: DbSession, created_by: str | None = None):
    query = select(SavedStone).order_by(SavedStone.created_at)
    if created_by is not None:
        query = query.where(SavedStone.created_by == created_by)
    return {"stones": [_stone_json(r) for r in db.scalars(query).all()]}


class SwapRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec: Spec
    stone_id: str


@router.post("/specs/swap-stone")
def swap_stone(request: SwapRequest, db: DbSession):
    """Try a library stone in a design: only the stone (and therefore its
    mounting) changes; every other dimension of the piece is untouched. The
    full validator runs, so a stone the design can't hold fails loudly with
    the fit numbers."""
    row = db.get(SavedStone, request.stone_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"unknown stone '{request.stone_id}'")
    swapped = Stone.model_validate(row.stone).model_copy(update={
        # the design decides how the stone is used; the library stone brings
        # only its own identity and measurements
        "count": request.spec.stone.count,
        "position": request.spec.stone.position,
    })
    candidate = request.spec.model_copy(update={"stone": swapped})
    result = validate_spec(candidate, get_vocabulary())
    if not result.ok:
        return JSONResponse(
            status_code=422,
            content={"detail": [issue.as_detail() for issue in result.issues]},
        )
    return result.spec

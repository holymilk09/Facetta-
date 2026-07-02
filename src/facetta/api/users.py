"""Minimal user records. The permission model beyond share-link granularity
is an open item (see CLAUDE.md) — these are labels, not auth."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from facetta.db import User, get_db, new_id

router = APIRouter(prefix="/users", tags=["users"])

DbSession = Annotated[Session, Depends(get_db)]


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    role: Literal["designer", "manufacturer", "client"]


@router.post("", status_code=201)
def create_user(user: UserCreate, db: DbSession):
    row = User(id=new_id("usr"), name=user.name, role=user.role)
    db.add(row)
    db.commit()
    return {"id": row.id, "name": row.name, "role": row.role}


@router.get("")
def list_users(db: DbSession):
    return {
        "users": [
            {"id": u.id, "name": u.name, "role": u.role}
            for u in db.scalars(select(User).order_by(User.created_at)).all()
        ]
    }

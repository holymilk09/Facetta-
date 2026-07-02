"""Database layer.

PostgreSQL with JSONB spec storage in production (set DATABASE_URL); SQLite
fallback for zero-setup local development. Design versions are immutable —
there is no update path, at the API layer or here. Schema changes must be
additive only.
"""

from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone
from functools import lru_cache

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

DEFAULT_DATABASE_URL = "sqlite:///./facetta.db"

SpecJSON = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(4)}"


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(24))  # designer | manufacturer | client
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Design(Base):
    __tablename__ = "designs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    created_by: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DesignVersion(Base):
    __tablename__ = "design_versions"

    design_id: Mapped[str] = mapped_column(ForeignKey("designs.id"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    spec: Mapped[dict] = mapped_column(SpecJSON)
    created_by: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    design_id: Mapped[str] = mapped_column(String(32), index=True)
    version: Mapped[int] = mapped_column(Integer)
    view: Mapped[str] = mapped_column(String(16))  # top | side | sheet
    x_pct: Mapped[float] = mapped_column(Float)
    y_pct: Mapped[float] = mapped_column(Float)
    body: Mapped[str] = mapped_column(Text)
    author: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ShareLink(Base):
    __tablename__ = "share_links"

    token: Mapped[str] = mapped_column(String(48), primary_key=True)
    design_id: Mapped[str] = mapped_column(String(32))
    version: Mapped[int] = mapped_column(Integer)
    scope: Mapped[str] = mapped_column(String(16), default="comment")  # view | comment
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


@lru_cache(maxsize=1)
def get_engine():
    url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=connect_args)
    Base.metadata.create_all(engine)
    return engine


def get_db():
    session = sessionmaker(bind=get_engine(), autoflush=False)()
    try:
        yield session
    finally:
        session.close()

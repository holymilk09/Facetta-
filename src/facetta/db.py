"""Database layer.

PostgreSQL with JSONB spec storage in production (set DATABASE_URL); SQLite
fallback for zero-setup local development. Design versions are immutable —
there is no update path, at the API layer or here. Schema changes must be
additive only.

Supabase is just managed Postgres, so pointing DATABASE_URL at it is the whole
integration — no rewrite. A raw connection string copied from the Supabase
dashboard (``postgres://…`` / ``postgresql://…``) is normalized onto psycopg v3,
the driver this project installs, so it works unchanged. See README → Database.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from functools import lru_cache

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from facetta.config import env_value

DEFAULT_DATABASE_URL = "sqlite:///./facetta.db"

SpecJSON = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    # 8 random bytes (64-bit) so IDs stay collision-safe even when several
    # regional deployments mint them independently and later sync a shared
    # design/thread across the border (see docs/hosting-and-data-residency.md).
    # Opaque + globally unique means a row can replicate between databases
    # without renumbering — the property auto-increment integers break.
    return f"{prefix}_{secrets.token_hex(8)}"


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
    # grouping label ("Client — Sarah K", "My sketches"); container metadata,
    # not part of any version, so renaming a group never touches a spec
    collection: Mapped[str | None] = mapped_column(String(80), nullable=True)


class DesignVersion(Base):
    __tablename__ = "design_versions"

    design_id: Mapped[str] = mapped_column(ForeignKey("designs.id"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    spec: Mapped[dict] = mapped_column(SpecJSON)
    created_by: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SavedStone(Base):
    """The user's curated stone library: real stones on file (often with lab
    reports) that get tried in different designs. Swapping a saved stone into
    a design changes only the stone and its mounting — never the piece."""

    __tablename__ = "saved_stones"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    created_by: Mapped[str] = mapped_column(String(32), index=True)
    label: Mapped[str] = mapped_column(String(120))
    stone: Mapped[dict] = mapped_column(SpecJSON)  # a Spec Stone object
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DesignMessage(Base):
    """Free-form discussion between designer and factory on a design.

    Distinct from Comment (which pins to an x/y region of one version's
    sheet): messages are the running conversation — adjustments, questions,
    approvals — optionally referencing a version number."""

    __tablename__ = "design_messages"

    # opaque global id (msg_…), not an auto-increment int: two regional
    # databases must be able to mint messages and sync them into one shared
    # thread without primary-key collisions. Chronology is carried by
    # created_at (UTC), so cross-region ordering stays correct.
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    design_id: Mapped[str] = mapped_column(String(32), index=True)
    version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    author: Mapped[str] = mapped_column(String(120))
    author_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Comment(Base):
    __tablename__ = "comments"

    # opaque global id (cmt_…) for the same cross-region reason as messages
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
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


def _apply_additive_migrations(engine) -> None:
    """Add columns that newer schema versions introduced (additive only)."""
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    existing = {c["name"] for c in inspector.get_columns("designs")}
    if "collection" not in existing:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE designs ADD COLUMN collection VARCHAR(80)"))


def normalize_database_url(url: str) -> str:
    """Route bare Postgres URLs onto psycopg v3 — the installed driver.

    Supabase (and Heroku-style) dashboards hand out ``postgres://`` /
    ``postgresql://`` strings. SQLAlchemy maps those to psycopg2, which this
    project does not depend on (only ``psycopg[binary]``, i.e. psycopg v3).
    Rewriting the scheme lets a pasted connection string work as-is; a URL that
    already names a driver (``postgresql+psycopg://``, ``postgresql+asyncpg://``)
    is left untouched.
    """
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def engine_config(raw_url: str) -> tuple[str, dict]:
    """Resolve (final url, create_engine kwargs) for a DATABASE_URL.

    SQLite gets the thread guard it needs for FastAPI's threadpool. Hosted
    Postgres gets ``pool_pre_ping`` so connections the server drops while idle
    are recycled instead of erroring mid-request. Supabase's transaction pooler
    (port 6543, host ``…pooler.supabase.com``, or ``?pgbouncer=true``) runs
    pgbouncer in transaction mode, which is incompatible with server-side
    prepared statements — so psycopg's prepare cache is disabled there, and the
    non-libpq ``pgbouncer`` query flag (which psycopg would reject) is stripped.
    """
    url = normalize_database_url(raw_url)
    parsed = make_url(url)
    if parsed.get_backend_name() == "sqlite":
        return url, {"connect_args": {"check_same_thread": False}}

    host = parsed.host or ""
    query = {k.lower(): str(v).lower() for k, v in parsed.query.items()}
    pooled = (
        parsed.port == 6543
        or host.endswith("pooler.supabase.com")
        or query.get("pgbouncer") in {"true", "1"}
    )
    stale_flags = [k for k in parsed.query if k.lower() == "pgbouncer"]
    if stale_flags:
        parsed = parsed.difference_update_query(stale_flags)
        url = parsed.render_as_string(hide_password=False)

    kwargs: dict = {"pool_pre_ping": True}
    if parsed.get_driver_name() == "psycopg" and pooled:
        kwargs["connect_args"] = {"prepare_threshold": None}
    return url, kwargs


@lru_cache(maxsize=1)
def get_engine():
    url, kwargs = engine_config(env_value("DATABASE_URL", DEFAULT_DATABASE_URL))
    engine = create_engine(url, **kwargs)
    Base.metadata.create_all(engine)
    _apply_additive_migrations(engine)
    return engine


def get_db():
    session = sessionmaker(bind=get_engine(), autoflush=False)()
    try:
        yield session
    finally:
        session.close()

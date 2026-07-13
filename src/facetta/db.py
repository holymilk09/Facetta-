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

import hashlib
import secrets
from datetime import datetime, timezone
from functools import lru_cache
from threading import Lock

from sqlalchemy import (
    JSON, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer,
    LargeBinary, String, Text, UniqueConstraint, create_engine, event, inspect,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from facetta.config import env_value

DEFAULT_DATABASE_URL = "sqlite:///./facetta.db"

_engine_initialization_lock = Lock()

SpecJSON = JSON().with_variant(JSONB(), "postgresql")

MOUNTING_ARTIFACT_SCHEMA_VERSION = "facetta.mounting-view.v1"
MOUNTING_ARTIFACT_KIND = "mounting_view"
MOUNTING_ARTIFACT_AUTHORITY_SCOPE = "factory_discussion_only"
MOUNTING_ARTIFACT_VIEWS = ("plan", "front", "side", "section")
MOUNTING_HIDDEN_GEOMETRY_STATUSES = (
    "source_observed",
    "spec_confirmed",
    "proposed_designer_confirmation_required",
    "designer_confirmed_visual_proposal",
    "unknown",
)


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


class ImmutableDesignVersionError(RuntimeError):
    """Raised when code tries to rewrite immutable specification truth."""


@event.listens_for(DesignVersion, "before_update")
def _reject_design_version_update(_mapper, _connection, _target) -> None:
    raise ImmutableDesignVersionError(
        "design versions are immutable; append a new specification version"
    )


@event.listens_for(DesignVersion, "before_delete")
def _reject_design_version_delete(_mapper, _connection, _target) -> None:
    raise ImmutableDesignVersionError(
        "design versions are immutable and cannot be deleted"
    )


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


class ImageAsset(Base):
    """One node in the iteration chain: a render or an edit of a render.

    Iteration is the designer's primary loop (A → many C → pin → B on
    demand), so every generated image is a first-class, immutable asset with
    a parent — history, compare, and revert are chain walks, never
    mutations. `pinned_at` marks the version approved for factory handoff:
    the manufacturing technical drawing defaults to the chain's most recently
    pinned asset, not to "latest"."""

    __tablename__ = "image_assets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    root_id: Mapped[str] = mapped_column(String(32), index=True)  # chain key
    parent_asset_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True, index=True)
    # the bridge to the spec universe: set on the chain ROOT when a render is
    # created from (or linked to) a persisted design, so an image edit can
    # also move the design's spec and the factory sheet letters the latest
    # numbers automatically. Children resolve through their root.
    design_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True, index=True)
    # The exact immutable spec version represented by this visual revision.
    # Legacy assets intentionally remain NULL: guessing a historical binding
    # would turn uncertain provenance into false factory truth.
    design_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    capability: Mapped[str] = mapped_column(String(48))  # which mode made it
    # Explicit designer-declared semantics for uploaded Studio sources.  This
    # stays nullable for generated/legacy assets; the service never guesses a
    # photograph, drawing, or finished render from pixels.
    source_kind: Mapped[str | None] = mapped_column(String(24), nullable=True)
    instruction: Mapped[str | None] = mapped_column(Text, nullable=True)
    region: Mapped[str | None] = mapped_column(Text, nullable=True)
    drift: Mapped[float | None] = mapped_column(Float, nullable=True)
    image: Mapped[bytes] = mapped_column(LargeBinary)
    media_type: Mapped[str] = mapped_column(String(24), default="image/png")
    pinned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(32), default="usr_pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow)

    # A design may own only one primary asset-chain root. NULL remains allowed
    # for unlinked/derived assets; the partial index gives new databases a
    # concurrency-safe guard while the service layer preserves legacy DBs that
    # may already contain duplicate historical links.
    __table_args__ = (
        Index(
            "uq_image_assets_design_primary_chain",
            "design_id",
            unique=True,
            sqlite_where=text(
                "design_id IS NOT NULL AND parent_asset_id IS NULL"),
            postgresql_where=text(
                "design_id IS NOT NULL AND parent_asset_id IS NULL"),
        ),
    )


class ImmutableImageAssetError(RuntimeError):
    """Raised when canonical visual bytes or lineage are rewritten."""


_IMAGE_ASSET_CANONICAL_FIELDS = frozenset({
    "id", "root_id", "parent_asset_id", "design_id", "design_version",
    "capability", "instruction", "region", "drift", "image", "media_type",
    "created_by", "created_at",
})


@event.listens_for(ImageAsset, "before_update")
def _reject_image_asset_canonical_update(_mapper, _connection, target) -> None:
    state = inspect(target)
    changed = sorted(
        field for field in _IMAGE_ASSET_CANONICAL_FIELDS
        if state.attrs[field].history.has_changes()
    )
    if changed:
        raise ImmutableImageAssetError(
            "image assets are immutable; append a new visual revision "
            f"instead of changing {', '.join(changed)}"
        )


@event.listens_for(ImageAsset, "before_delete")
def _reject_image_asset_delete(_mapper, _connection, _target) -> None:
    raise ImmutableImageAssetError(
        "image assets are immutable and cannot be deleted"
    )


class RevisionComponentMapRecord(Base):
    """Immutable semantic isolation evidence for one exact visual revision.

    ``map_json`` is validated by ``RevisionComponentMap`` at the service
    boundary.  The content hash makes accidental serialization drift visible;
    ``asset_id`` as the primary key enforces exactly one map per raster.
    """

    __tablename__ = "revision_component_maps"

    asset_id: Mapped[str] = mapped_column(
        ForeignKey("image_assets.id"), primary_key=True)
    parent_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("image_assets.id"), nullable=True, index=True)
    map_json: Mapped[dict] = mapped_column(SpecJSON)
    map_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        CheckConstraint(
            "length(map_sha256) = 64",
            name="ck_revision_component_map_hash_length",
        ),
    )


class ImmutableRevisionComponentMapError(RuntimeError):
    """Raised when append-only per-revision component evidence is rewritten."""


@event.listens_for(RevisionComponentMapRecord, "before_update")
def _reject_revision_component_map_update(
    _mapper, _connection, _target,
) -> None:
    raise ImmutableRevisionComponentMapError(
        "revision component maps are immutable; map the child revision"
    )


@event.listens_for(RevisionComponentMapRecord, "before_delete")
def _reject_revision_component_map_delete(
    _mapper, _connection, _target,
) -> None:
    raise ImmutableRevisionComponentMapError(
        "revision component maps are immutable and cannot be deleted"
    )


class DesignFamily(Base):
    """One Studio design direction with independently versioned project variants."""

    __tablename__ = "design_families"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        CheckConstraint(
            "length(trim(title)) > 0",
            name="ck_design_family_title",
        ),
    )


class StudioJobRecord(Base):
    """Designer-facing lifecycle for one requested Studio generation.

    Provider attempts and internal QA retries deliberately do not live in this
    table.  Activity is an outcome ledger: billing can only reference completed
    outputs the designer requested, never the machinery used to produce them.
    """

    __tablename__ = "studio_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner: Mapped[str] = mapped_column(String(32), index=True)
    action_id: Mapped[str] = mapped_column(String(24))
    lane: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(16), index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    active_design_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True, index=True)
    source_revision_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True)
    requested_outputs: Mapped[int] = mapped_column(Integer)
    credits_per_output: Mapped[int] = mapped_column(Integer)
    completed_outputs: Mapped[int] = mapped_column(Integer, default=0)
    charged_outputs: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Non-null only while a backend-owned candidate workflow holds the job's
    # reviewing state.  Public lifecycle reports must not race that decision.
    reservation_kind: Mapped[str | None] = mapped_column(
        String(24), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        CheckConstraint(
            "action_id IN ('create', 'vary', 'refine', 'views', "
            "'present', 'factory')",
            name="ck_studio_job_action",
        ),
        CheckConstraint(
            "lane IN ('instant', 'fast_visual', 'trusted_structural')",
            name="ck_studio_job_lane",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'reviewing', 'succeeded', "
            "'failed', 'canceled')",
            name="ck_studio_job_status",
        ),
        CheckConstraint(
            "progress >= 0 AND progress <= 1",
            name="ck_studio_job_progress",
        ),
        CheckConstraint(
            "requested_outputs >= 1 AND requested_outputs <= 4",
            name="ck_studio_job_requested_outputs",
        ),
        CheckConstraint(
            "credits_per_output >= 0",
            name="ck_studio_job_credit_rate",
        ),
        CheckConstraint(
            "completed_outputs >= 0 AND completed_outputs <= requested_outputs",
            name="ck_studio_job_completed_outputs",
        ),
        CheckConstraint(
            "charged_outputs >= 0 AND charged_outputs <= completed_outputs",
            name="ck_studio_job_charge_within_completed",
        ),
        CheckConstraint(
            "reservation_kind IS NULL OR reservation_kind = 'studio_visual'",
            name="ck_studio_job_reservation_kind",
        ),
        CheckConstraint(
            "charged_outputs = 0 OR status = 'succeeded'",
            name="ck_studio_job_charge_requires_success",
        ),
    )


class StudioPresentationCandidateRecord(Base):
    """Durable, review-only Client/Marketing output for one exact visual.

    The raster is intentionally stored before acceptance so a browser refresh
    or API process restart cannot silently lose a designer's review work.  A
    terminal decision records its resulting asset/review identity on this row;
    it never mutates the selected Studio revision.
    """

    __tablename__ = "studio_presentation_candidates"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    image_run_id: Mapped[str] = mapped_column(
        ForeignKey("image_runs.id"), nullable=False, index=True)
    owner: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    project_root_id: Mapped[str] = mapped_column(
        ForeignKey("projects.root_id"), nullable=False, index=True)
    source_asset_id: Mapped[str] = mapped_column(
        ForeignKey("image_assets.id"), nullable=False, index=True)
    expected_active_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("image_assets.id"), nullable=True)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    output_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    image: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    media_type: Mapped[str] = mapped_column(String(24), nullable=False)
    destination: Mapped[str] = mapped_column(String(16), nullable=False)
    capability: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_change: Mapped[str] = mapped_column(Text, nullable=False)
    preset: Mapped[str] = mapped_column(String(32), nullable=False)
    framing: Mapped[str] = mapped_column(String(16), nullable=False)
    qa: Mapped[dict] = mapped_column(SpecJSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    # Null preserves every pre-spec candidate. Exact Studio presentation
    # candidates bind to the immutable specification represented by source.
    design_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    studio_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("studio_jobs.id"), nullable=True, index=True)
    accepted_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("image_assets.id"), nullable=True)
    review_id: Mapped[str | None] = mapped_column(
        ForeignKey("image_run_reviews.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "image_run_id", name="uq_studio_presentation_candidate_run"),
        UniqueConstraint(
            "studio_job_id", name="uq_studio_presentation_candidate_job"),
        CheckConstraint(
            "destination IN ('client', 'marketing')",
            name="ck_studio_presentation_candidate_destination",
        ),
        CheckConstraint(
            "capability IN ('CLIENT_BEAUTY_RENDER', "
            "'CLIENT_PRODUCT_PHOTO', 'MARKETING_IMAGE')",
            name="ck_studio_presentation_candidate_capability",
        ),
        CheckConstraint(
            "status IN ('reviewing', 'accepted', 'discarded', 'expired')",
            name="ck_studio_presentation_candidate_status",
        ),
        CheckConstraint(
            "length(source_sha256) = 64 AND length(output_sha256) = 64",
            name="ck_studio_presentation_candidate_hashes",
        ),
        CheckConstraint(
            "(status = 'accepted' AND accepted_asset_id IS NOT NULL "
            "AND review_id IS NOT NULL AND resolved_at IS NOT NULL) OR "
            "(status IN ('discarded', 'expired') AND accepted_asset_id IS NULL "
            "AND resolved_at IS NOT NULL) OR "
            "(status = 'reviewing' AND accepted_asset_id IS NULL "
            "AND review_id IS NULL AND resolved_at IS NULL)",
            name="ck_studio_presentation_candidate_resolution",
        ),
    )


class StudioPresentationCandidateJobLink(Base):
    """Many-output Present job membership without rewriting legacy rows.

    ``StudioPresentationCandidateRecord.studio_job_id`` remains the compatible
    one-output pre-spec binding. Exact multi-output jobs use this additive link
    so one requested pack can settle and bill all accepted outputs together.
    """

    __tablename__ = "studio_presentation_candidate_job_links"

    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("studio_presentation_candidates.id"), primary_key=True)
    studio_job_id: Mapped[str] = mapped_column(
        ForeignKey("studio_jobs.id"), nullable=False, index=True)
    output_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "studio_job_id", "output_ordinal",
            name="uq_studio_presentation_job_output_ordinal",
        ),
        CheckConstraint(
            "output_ordinal >= 0 AND output_ordinal <= 3",
            name="ck_studio_presentation_output_ordinal",
        ),
    )


class StudioViewCandidateRecord(Base):
    """Durable review candidate for an exact, derived Studio View."""

    __tablename__ = "studio_view_candidates"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    image_run_id: Mapped[str] = mapped_column(
        ForeignKey("image_runs.id"), nullable=False, unique=True, index=True)
    owner: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    project_root_id: Mapped[str] = mapped_column(
        ForeignKey("projects.root_id"), nullable=False, index=True)
    source_asset_id: Mapped[str] = mapped_column(
        ForeignKey("image_assets.id"), nullable=False, index=True)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    output_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    spec_visual_hash: Mapped[str] = mapped_column(String(16), nullable=False)
    design_version: Mapped[int] = mapped_column(Integer, nullable=False)
    view: Mapped[str] = mapped_column(String(24), nullable=False)
    image: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    media_type: Mapped[str] = mapped_column(String(24), nullable=False)
    requested_change: Mapped[str] = mapped_column(Text, nullable=False)
    qa: Mapped[dict] = mapped_column(SpecJSON, nullable=False)
    routing: Mapped[dict] = mapped_column(SpecJSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    studio_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("studio_jobs.id"), nullable=True, index=True)
    accepted_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("image_assets.id"), nullable=True)
    review_id: Mapped[str | None] = mapped_column(
        ForeignKey("image_run_reviews.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "view IN ('front', 'three_quarter', 'side')",
            name="ck_studio_view_candidate_view",
        ),
        CheckConstraint(
            "status IN ('reviewing', 'accepted', 'discarded', 'expired')",
            name="ck_studio_view_candidate_status",
        ),
        CheckConstraint(
            "length(source_sha256) = 64 AND length(output_sha256) = 64 "
            "AND length(spec_visual_hash) = 16",
            name="ck_studio_view_candidate_hashes",
        ),
        CheckConstraint(
            "design_version >= 1",
            name="ck_studio_view_candidate_design_version",
        ),
        CheckConstraint(
            "(status = 'accepted' AND accepted_asset_id IS NOT NULL "
            "AND review_id IS NOT NULL AND resolved_at IS NOT NULL) OR "
            "(status = 'discarded' AND accepted_asset_id IS NULL "
            "AND review_id IS NOT NULL AND resolved_at IS NOT NULL) OR "
            "(status = 'expired' AND accepted_asset_id IS NULL "
            "AND resolved_at IS NOT NULL) OR "
            "(status = 'reviewing' AND accepted_asset_id IS NULL "
            "AND review_id IS NULL AND resolved_at IS NULL)",
            name="ck_studio_view_candidate_resolution",
        ),
    )


class StudioMarkupCandidateRecord(Base):
    """Durable exact-revision Refine candidate awaiting one decision.

    Mark-up and natural-language refinements used to retain their candidate
    bytes only in a process-local cache.  This row is the restart-safe review
    authority; canonical image/spec history is still created only by an
    explicit Apply or Save-as-Variation decision.
    """

    __tablename__ = "studio_markup_candidates"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    image_run_id: Mapped[str] = mapped_column(
        ForeignKey("image_runs.id"), nullable=False, unique=True, index=True)
    owner: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    project_root_id: Mapped[str] = mapped_column(
        ForeignKey("projects.root_id"), nullable=False, index=True)
    source_asset_id: Mapped[str] = mapped_column(
        ForeignKey("image_assets.id"), nullable=False, index=True)
    expected_active_asset_id: Mapped[str] = mapped_column(
        ForeignKey("image_assets.id"), nullable=False)
    design_version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    output_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_spec_visual_hash: Mapped[str] = mapped_column(
        String(64), nullable=False)
    target_spec_visual_hash: Mapped[str] = mapped_column(
        String(64), nullable=False)
    image: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    media_type: Mapped[str] = mapped_column(String(24), nullable=False)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    asset_capability: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_change: Mapped[str] = mapped_column(Text, nullable=False)
    region_description: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(SpecJSON, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    studio_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("studio_jobs.id"), nullable=True, unique=True, index=True)
    terminal_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("image_assets.id"), nullable=True)
    review_id: Mapped[str | None] = mapped_column(
        ForeignKey("image_run_reviews.id"), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "design_version >= 1",
            name="ck_studio_markup_candidate_design_version",
        ),
        CheckConstraint(
            "status IN ('reviewing', 'applied', 'saved_as_variation', "
            "'discarded', 'expired')",
            name="ck_studio_markup_candidate_status",
        ),
        CheckConstraint(
            "length(source_sha256) = 64 AND length(output_sha256) = 64 "
            "AND length(source_spec_visual_hash) = 16 "
            "AND length(target_spec_visual_hash) = 16",
            name="ck_studio_markup_candidate_hashes",
        ),
        CheckConstraint(
            "(status IN ('applied', 'saved_as_variation') "
            "AND terminal_asset_id IS NOT NULL AND review_id IS NOT NULL "
            "AND decided_by IS NOT NULL AND resolved_at IS NOT NULL) OR "
            "(status = 'discarded' AND terminal_asset_id IS NULL "
            "AND review_id IS NOT NULL AND decided_by IS NOT NULL "
            "AND resolved_at IS NOT NULL) OR "
            "(status = 'expired' AND terminal_asset_id IS NULL "
            "AND decided_by IS NULL AND resolved_at IS NOT NULL) OR "
            "(status = 'reviewing' AND terminal_asset_id IS NULL "
            "AND review_id IS NULL AND decided_by IS NULL "
            "AND resolved_at IS NULL)",
            name="ck_studio_markup_candidate_resolution",
        ),
    )


class PreviewCandidateRecord(Base):
    """Durable, non-canonical Studio/catalog output awaiting a decision.

    Candidate bytes and typed payload stay outside ``ImageAsset`` and
    ``DesignVersion`` until Apply succeeds.  Exact hashes bind review work to
    the source revision across process restarts and browser refreshes.
    """

    __tablename__ = "preview_candidates"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    image_run_id: Mapped[str] = mapped_column(
        ForeignKey("image_runs.id"), nullable=False, unique=True, index=True)
    owner: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    project_root_id: Mapped[str] = mapped_column(
        ForeignKey("projects.root_id"), nullable=False, index=True)
    source_asset_id: Mapped[str] = mapped_column(
        ForeignKey("image_assets.id"), nullable=False, index=True)
    expected_active_asset_id: Mapped[str] = mapped_column(
        ForeignKey("image_assets.id"), nullable=False)
    expected_design_version: Mapped[int | None] = mapped_column(
        Integer, nullable=True)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    output_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    image: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    media_type: Mapped[str] = mapped_column(String(24), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    studio_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("studio_jobs.id"), nullable=True)
    payload: Mapped[dict] = mapped_column(SpecJSON, nullable=False)
    terminal_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("image_assets.id"), nullable=True)
    review_id: Mapped[str | None] = mapped_column(
        ForeignKey("image_run_reviews.id"), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index(
            "uq_preview_candidates_studio_job_id",
            "studio_job_id",
            unique=True,
            sqlite_where=text("studio_job_id IS NOT NULL"),
            postgresql_where=text("studio_job_id IS NOT NULL"),
        ),
        CheckConstraint(
            "kind IN ('studio_visual', 'catalog_revision')",
            name="ck_preview_candidate_kind",
        ),
        CheckConstraint(
            "status IN ('reviewing', 'applied', 'saved_as_variation', "
            "'discarded', 'expired')",
            name="ck_preview_candidate_status",
        ),
        CheckConstraint(
            "length(source_sha256) = 64 AND length(output_sha256) = 64",
            name="ck_preview_candidate_hashes",
        ),
        CheckConstraint(
            "(status = 'reviewing' AND terminal_asset_id IS NULL "
            "AND review_id IS NULL AND decided_by IS NULL "
            "AND resolved_at IS NULL) OR "
            "(status = 'applied' AND terminal_asset_id IS NOT NULL "
            "AND review_id IS NOT NULL AND decided_by IS NOT NULL "
            "AND resolved_at IS NOT NULL) OR "
            "(status = 'saved_as_variation' AND terminal_asset_id IS NOT NULL "
            "AND review_id IS NOT NULL AND decided_by IS NOT NULL "
            "AND resolved_at IS NOT NULL) OR "
            "(status = 'discarded' AND terminal_asset_id IS NULL "
            "AND decided_by IS NOT NULL AND resolved_at IS NOT NULL) OR "
            "(status = 'expired' AND terminal_asset_id IS NULL "
            "AND decided_by IS NULL AND resolved_at IS NOT NULL)",
            name="ck_preview_candidate_resolution",
        ),
    )


class Project(Base):
    """A design project = one asset chain (a hero render and all its edits,
    views, videos, and factory drawings), filed for the designer.

    Proven library model: owner → collection (a client folder like "Sarah K —
    engagement", or a personal folder) → project → tags. Everything a client's
    work produces stays under one collection, and tags + free-text search
    locate a piece across the whole library. Metadata lives here, off the asset
    rows, so renaming a folder never touches an image."""

    __tablename__ = "projects"

    root_id: Mapped[str] = mapped_column(String(32), primary_key=True)  # chain root
    owner: Mapped[str] = mapped_column(String(32), index=True)
    collection: Mapped[str | None] = mapped_column(
        String(120), nullable=True, index=True)  # client / folder; None = Unfiled
    title: Mapped[str] = mapped_column(String(200))
    tags: Mapped[list] = mapped_column(SpecJSON, default=list)
    family_id: Mapped[str | None] = mapped_column(
        ForeignKey("design_families.id"), nullable=True, index=True)
    variation_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    variation_label: Mapped[str | None] = mapped_column(
        String(120), nullable=True)
    selected_candidate_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("image_assets.id"), nullable=True)
    # A branch keeps the exact Studio project and visual it started from. The
    # child project owns an independent asset chain and immutable spec history.
    branched_from_project_root_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.root_id"), nullable=True, index=True)
    branched_from_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("image_assets.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        CheckConstraint(
            "variation_index IS NULL OR variation_index >= 1",
            name="ck_project_variation_index",
        ),
        Index(
            "uq_projects_family_variation_index",
            "family_id",
            "variation_index",
            unique=True,
            sqlite_where=text(
                "family_id IS NOT NULL AND variation_index IS NOT NULL"),
            postgresql_where=text(
                "family_id IS NOT NULL AND variation_index IS NOT NULL"),
        ),
    )


class StudioConfirmationDraft(Base):
    """One-time server-held design facts for a selected Studio candidate."""

    __tablename__ = "studio_confirmation_drafts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    token_sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    owner: Mapped[str] = mapped_column(String(32), index=True)
    project_root_id: Mapped[str] = mapped_column(
        ForeignKey("projects.root_id"), index=True)
    candidate_asset_id: Mapped[str] = mapped_column(
        ForeignKey("image_assets.id"), index=True)
    candidate_sha256: Mapped[str] = mapped_column(String(64))
    spec_visual_hash: Mapped[str] = mapped_column(String(16))
    spec: Mapped[dict] = mapped_column(SpecJSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "length(token_sha256) = 64 AND length(candidate_sha256) = 64",
            name="ck_studio_confirmation_draft_sha256",
        ),
        CheckConstraint(
            "length(spec_visual_hash) = 16",
            name="ck_studio_confirmation_draft_spec_hash",
        ),
        CheckConstraint(
            "expires_at > created_at",
            name="ck_studio_confirmation_draft_expiry",
        ),
    )


class ProjectRevisionRecord(Base):
    """Immutable designer-intent evidence for one exact primary visual asset.

    The image and specification remain in their canonical asset/design tables.
    This record preserves what the designer asked, how Facetta interpreted it,
    and the concise outcome for Studio history. One primary asset may have only
    one record, so history cannot fork into contradictory explanations.
    """

    __tablename__ = "project_revision_records"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("image_assets.id"))
    action: Mapped[str] = mapped_column(String(16))
    raw_intent: Mapped[dict] = mapped_column(SpecJSON)
    interpretation: Mapped[dict] = mapped_column(SpecJSON)
    change_summary: Mapped[str] = mapped_column(Text)
    restored_from_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("image_assets.id"), nullable=True)
    created_by: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        CheckConstraint(
            "action IN ('created', 'edit', 'restore')",
            name="ck_project_revision_record_action",
        ),
        CheckConstraint(
            "((action = 'restore' AND restored_from_asset_id IS NOT NULL) OR "
            "(action IN ('created', 'edit') AND "
            "restored_from_asset_id IS NULL))",
            name="ck_project_revision_record_restore_source",
        ),
        CheckConstraint(
            "restored_from_asset_id IS NULL OR "
            "restored_from_asset_id <> asset_id",
            name="ck_project_revision_record_restore_distinct",
        ),
        CheckConstraint(
            "length(trim(change_summary)) > 0",
            name="ck_project_revision_record_summary",
        ),
        Index(
            "uq_project_revision_record_asset",
            "asset_id",
            unique=True,
        ),
    )


class ImmutableProjectRevisionRecordError(RuntimeError):
    """Raised when code tries to rewrite append-only Studio revision evidence."""


class InvalidProjectRevisionAssetError(ValueError):
    """Raised when Studio history is attached to a non-primary visual asset."""


@event.listens_for(ProjectRevisionRecord, "before_insert")
def _validate_project_revision_record_asset(
    _mapper, connection, target,
) -> None:
    # Import lazily to avoid a module-initialization cycle while still sharing
    # the project backbone's one canonical primary-capability set.
    from facetta.project_backbone import PRIMARY_REVISION_CAPABILITIES

    asset = connection.execute(
        text(
            "SELECT capability, parent_asset_id, image FROM image_assets "
            "WHERE id = :asset_id"
        ),
        {"asset_id": target.asset_id},
    ).mappings().one_or_none()
    if asset is None or asset["capability"] not in PRIMARY_REVISION_CAPABILITIES:
        raise InvalidProjectRevisionAssetError(
            "project revision records require an existing primary visual asset"
        )

    raw_intent = dict(target.raw_intent or {})
    interpretation = dict(target.interpretation or {})
    source_asset_id = (
        raw_intent.get("source_asset_id")
        or raw_intent.get("selected_asset_id")
        or interpretation.get("source_asset_id")
        or target.restored_from_asset_id
        or asset["parent_asset_id"]
        or target.asset_id
    )
    # A root ``created`` record may have no upstream asset by definition. Its
    # source hash therefore self-binds to the exact bytes that established the
    # canonical baseline. Historical callers remain compatible, while every
    # later edit/branch/restore resolves an explicit parent or source asset.
    source_image = connection.execute(
        text("SELECT image FROM image_assets WHERE id = :asset_id"),
        {"asset_id": source_asset_id},
    ).scalar_one_or_none()
    if source_image is None:
        raise InvalidProjectRevisionAssetError(
            "project revision records require an existing lineage source asset"
        )
    source_sha256 = hashlib.sha256(bytes(source_image)).hexdigest()
    output_sha256 = hashlib.sha256(bytes(asset["image"])).hexdigest()
    supplied_source = interpretation.get("source_sha256")
    supplied_output = interpretation.get("output_sha256")
    if supplied_source is not None and supplied_source != source_sha256:
        raise InvalidProjectRevisionAssetError(
            "project revision source hash does not match canonical bytes"
        )
    if supplied_output is not None and supplied_output != output_sha256:
        raise InvalidProjectRevisionAssetError(
            "project revision output hash does not match canonical bytes"
        )
    interpretation.update({
        "source_asset_id": source_asset_id,
        "source_sha256": source_sha256,
        "output_sha256": output_sha256,
    })
    target.interpretation = interpretation


@event.listens_for(ProjectRevisionRecord, "before_update")
def _reject_project_revision_record_update(
    _mapper, _connection, _target,
) -> None:
    raise ImmutableProjectRevisionRecordError(
        "project revision records are immutable; append a new primary revision"
    )


@event.listens_for(ProjectRevisionRecord, "before_delete")
def _reject_project_revision_record_delete(
    _mapper, _connection, _target,
) -> None:
    raise ImmutableProjectRevisionRecordError(
        "project revision records are immutable and cannot be deleted"
    )


class ImageRun(Base):
    """One completed invocation of the closed-loop jewelry image agent.

    Runs are append-only audit records. The orchestrator gathers provider and
    QA results first, then inserts the final run and all of its attempts. There
    is deliberately no mutable ``updated_at`` lifecycle on this table.
    """

    __tablename__ = "image_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    project_root_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True, index=True)
    source_asset_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True, index=True)
    operation: Mapped[str] = mapped_column(String(32), index=True)
    normalized_intent: Mapped[dict] = mapped_column(SpecJSON)
    prompt_version: Mapped[str] = mapped_column(String(48))
    # Content identities from the normalized plan. Nullable preserves honest
    # provenance for runs recorded before these observability fields existed.
    input_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mask_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    spec_visual_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True)
    source_spec_visual_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True)
    variant: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16))
    accepted_asset_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True, index=True)
    error_category: Mapped[str | None] = mapped_column(
        String(32), nullable=True)
    created_by: Mapped[str] = mapped_column(String(32), default="usr_pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow)


class ImageAttempt(Base):
    """One immutable provider attempt and its jewelry-specific QA result."""

    __tablename__ = "image_attempts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("image_runs.id"), index=True)
    attempt_number: Mapped[int] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(80))
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cached: Mapped[bool] = mapped_column(Boolean, default=False)
    provider_request_id: Mapped[str | None] = mapped_column(
        String(160), nullable=True)
    qa_verdict: Mapped[str | None] = mapped_column(String(16), nullable=True)
    qa_checks: Mapped[list] = mapped_column(SpecJSON, default=list)
    corrective_instruction: Mapped[str | None] = mapped_column(
        Text, nullable=True)
    fallback_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Prompt and cache identities allow a stored attempt to be reproduced and
    # explain cache behavior without retaining provider prompt text.
    prompt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cache_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    usage: Mapped[dict] = mapped_column(SpecJSON, default=dict)
    cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_category: Mapped[str | None] = mapped_column(
        String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("uq_image_attempt_run_number", "run_id", "attempt_number",
              unique=True),
    )


class ImageRunReview(Base):
    """One append-only designer decision for a QA-warning candidate.

    The original ``ImageRun`` and its attempts remain immutable evidence.  A
    later explicit designer acceptance is recorded separately, so promoting a
    warning never rewrites the evaluator's original ``review_required``
    verdict.
    """

    __tablename__ = "image_run_reviews"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("image_runs.id"), unique=True, index=True)
    decision: Mapped[str] = mapped_column(String(16))
    accepted_asset_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True, index=True)
    created_by: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow)


class DerivedArtifactMetadata(Base):
    """Immutable authority metadata for one accepted derived visual artifact.

    Mounting-view candidates remain outside the product asset chain until a
    designer accepts them. Consequently this row requires both the originating
    image run and the append-only acceptance review. The raster remains an
    ``ImageAsset``; this table records why it may appear in factory-review
    material without ever becoming factory or production authority.

    ``source_hashes`` maps every entry in ``source_asset_ids`` to the SHA-256
    identity used by the image run. Application services validate that mapping
    before the short acceptance transaction; scalar authority invariants are
    also enforced by database checks below.
    """

    __tablename__ = "derived_artifact_metadata"

    asset_id: Mapped[str] = mapped_column(
        ForeignKey("image_assets.id"), primary_key=True)
    schema_version: Mapped[str] = mapped_column(
        String(48), default=MOUNTING_ARTIFACT_SCHEMA_VERSION)
    artifact_kind: Mapped[str] = mapped_column(
        String(32), default=MOUNTING_ARTIFACT_KIND)
    view: Mapped[str] = mapped_column(String(16))
    authority_scope: Mapped[str] = mapped_column(
        String(32), default=MOUNTING_ARTIFACT_AUTHORITY_SCOPE)
    hidden_geometry_status: Mapped[str] = mapped_column(String(48))
    source_asset_ids: Mapped[list] = mapped_column(SpecJSON)
    source_hashes: Mapped[dict] = mapped_column(SpecJSON)
    design_version: Mapped[int] = mapped_column(Integer)
    spec_visual_hash: Mapped[str] = mapped_column(String(16))
    image_run_id: Mapped[str] = mapped_column(
        ForeignKey("image_runs.id"))
    # Product assets are created only after explicit designer acceptance, so a
    # persisted mounting artifact must always carry the corresponding review.
    review_id: Mapped[str] = mapped_column(
        ForeignKey("image_run_reviews.id"))
    production_authority: Mapped[bool] = mapped_column(Boolean, default=False)
    disclaimer: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        CheckConstraint(
            f"schema_version = '{MOUNTING_ARTIFACT_SCHEMA_VERSION}'",
            name="ck_derived_artifact_schema_version",
        ),
        CheckConstraint(
            f"artifact_kind = '{MOUNTING_ARTIFACT_KIND}'",
            name="ck_derived_artifact_kind",
        ),
        CheckConstraint(
            "view IN ('plan', 'front', 'side', 'section')",
            name="ck_derived_artifact_mounting_view",
        ),
        CheckConstraint(
            f"authority_scope = '{MOUNTING_ARTIFACT_AUTHORITY_SCOPE}'",
            name="ck_derived_artifact_authority_scope",
        ),
        CheckConstraint(
            "hidden_geometry_status IN ("
            "'source_observed', 'spec_confirmed', "
            "'proposed_designer_confirmation_required', "
            "'designer_confirmed_visual_proposal', 'unknown')",
            name="ck_derived_artifact_hidden_geometry_status",
        ),
        CheckConstraint(
            "design_version >= 1",
            name="ck_derived_artifact_design_version",
        ),
        CheckConstraint(
            "length(spec_visual_hash) = 16",
            name="ck_derived_artifact_spec_visual_hash",
        ),
        CheckConstraint(
            "production_authority = false",
            name="ck_derived_artifact_no_production_authority",
        ),
        CheckConstraint(
            "length(trim(disclaimer)) > 0",
            name="ck_derived_artifact_disclaimer",
        ),
        Index(
            "uq_derived_artifact_image_run",
            "image_run_id",
            unique=True,
        ),
        Index(
            "uq_derived_artifact_review",
            "review_id",
            unique=True,
        ),
    )


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


class ApprovalChecklist(Base):
    """The tap-to-approve ritual for one exact version: a frozen list of
    fact-items derived from the piece's own spec sections (a ring asks about
    its band; a necklace about its chain). Binding to a specific asset (or
    design version) makes invalidation structural — a new version simply has
    no checklist yet. `mode` picks the pin behavior: auto_pin (all-YES pins
    for factory), explicit_pin (completion unlocks the pin), optional
    (advisory only, never gates)."""

    __tablename__ = "approval_checklists"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    asset_id: Mapped[str | None] = mapped_column(String(32), nullable=True,
                                                 index=True)
    design_id: Mapped[str | None] = mapped_column(String(32), nullable=True,
                                                  index=True)
    design_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mode: Mapped[str] = mapped_column(String(16), default="auto_pin")
    items: Mapped[list] = mapped_column(SpecJSON)   # frozen ChecklistItem dicts
    created_by: Mapped[str] = mapped_column(String(32), default="usr_pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow)


class FeedbackEvent(Base):
    """One designer verdict on one generated asset — the correction flywheel's
    raw data. accepted / regenerated / rejected, append-only. Aggregated per
    capability and instruction, this is what later teaches the prompts which
    phrasings work; no prompt ever mutates from a single event."""

    __tablename__ = "feedback_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True,
                                    autoincrement=True)
    asset_id: Mapped[str] = mapped_column(String(32), index=True)
    image_run_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True, index=True)
    subject_kind: Mapped[str] = mapped_column(String(16), default="asset")
    action: Mapped[str] = mapped_column(String(16))  # accepted|regenerated|rejected
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(32), default="usr_pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow)


class ApprovalResponse(Base):
    """One tap on one checklist item — append-only, latest per item wins.
    The audit trail a factory relationship runs on: who confirmed which fact,
    when, and (on a NO) the change note plus the agent's understood-as echo."""

    __tablename__ = "approval_responses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True,
                                    autoincrement=True)
    checklist_id: Mapped[str] = mapped_column(String(32), index=True)
    item_key: Mapped[str] = mapped_column(String(48))
    approved: Mapped[bool] = mapped_column()
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    understood_as: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(32), default="usr_pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow)


def _apply_additive_migrations(engine) -> None:
    """Add columns that newer schema versions introduced (additive only)."""
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    existing = {c["name"] for c in inspector.get_columns("designs")}
    if "collection" not in existing:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE designs ADD COLUMN collection VARCHAR(80)"))
    existing = {c["name"] for c in inspector.get_columns("image_assets")}
    if "design_id" not in existing:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE image_assets ADD COLUMN design_id VARCHAR(32)"))
    if "design_version" not in existing:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE image_assets ADD COLUMN design_version INTEGER"))
    if "source_kind" not in existing:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE image_assets ADD COLUMN source_kind VARCHAR(24)"))

    # Studio family/variation fields are nullable so every historical project
    # remains readable without a guessed family or branch. New families and
    # revision records are entirely new tables and are created by create_all
    # before this compatibility pass.
    project_columns = {
        c["name"] for c in inspector.get_columns("projects")}
    project_additions = {
        "family_id": (
            "VARCHAR(32) REFERENCES design_families(id)"
        ),
        "variation_index": (
            "INTEGER CHECK (variation_index IS NULL OR variation_index >= 1)"
        ),
        "variation_label": "VARCHAR(120)",
        "selected_candidate_asset_id": (
            "VARCHAR(32) REFERENCES image_assets(id)"
        ),
        "branched_from_project_root_id": (
            "VARCHAR(32) REFERENCES projects(root_id)"
        ),
        "branched_from_asset_id": (
            "VARCHAR(32) REFERENCES image_assets(id)"
        ),
    }
    for column, declaration in project_additions.items():
        if column not in project_columns:
            with engine.begin() as conn:
                conn.execute(text(
                    f"ALTER TABLE projects ADD COLUMN {column} {declaration}"
                ))
    project_indexes = {
        item["name"] for item in inspect(engine).get_indexes("projects")}
    for index_name, column in {
        "ix_projects_family_id": "family_id",
        "ix_projects_branched_from_project_root_id": (
            "branched_from_project_root_id"
        ),
        "ix_projects_branched_from_asset_id": "branched_from_asset_id",
    }.items():
        if index_name not in project_indexes:
            with engine.begin() as conn:
                conn.execute(text(
                    f"CREATE INDEX {index_name} ON projects ({column})"
                ))
    project_indexes = {
        item["name"] for item in inspect(engine).get_indexes("projects")}
    family_variation_index = "uq_projects_family_variation_index"
    if family_variation_index not in project_indexes:
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE UNIQUE INDEX " + family_variation_index + " "
                "ON projects (family_id, variation_index) "
                "WHERE family_id IS NOT NULL AND variation_index IS NOT NULL"
            ))

    # Image-agent evidence is append-only, so historical rows are never
    # backfilled with guessed identities. New executions always populate these
    # nullable columns through ``image_run_store``.
    run_columns = {
        c["name"] for c in inspector.get_columns("image_runs")}
    if "input_hash" not in run_columns:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE image_runs ADD COLUMN input_hash VARCHAR(64)"))
    if "mask_hash" not in run_columns:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE image_runs ADD COLUMN mask_hash VARCHAR(64)"))
    if "source_spec_visual_hash" not in run_columns:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE image_runs ADD COLUMN source_spec_visual_hash VARCHAR(64)"))

    attempt_columns = {
        c["name"] for c in inspector.get_columns("image_attempts")}
    if "prompt_hash" not in attempt_columns:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE image_attempts ADD COLUMN prompt_hash VARCHAR(64)"))
    if "cache_key" not in attempt_columns:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE image_attempts ADD COLUMN cache_key VARCHAR(64)"))

    # ``create_all`` creates this index on fresh databases. Existing databases
    # need an additive bootstrap. Preserve readable legacy data: if it already
    # contains duplicate root links, application-level guards prevent another
    # one but startup does not fail by trying to rewrite history.
    indexes = {i["name"] for i in inspector.get_indexes("image_assets")}
    index_name = "uq_image_assets_design_primary_chain"
    if index_name not in indexes:
        with engine.begin() as conn:
            duplicate = conn.execute(text(
                "SELECT design_id FROM image_assets "
                "WHERE design_id IS NOT NULL AND parent_asset_id IS NULL "
                "GROUP BY design_id HAVING COUNT(*) > 1 LIMIT 1"
            )).first()
            if duplicate is None:
                conn.execute(text(
                    "CREATE UNIQUE INDEX " + index_name + " "
                    "ON image_assets (design_id) "
                    "WHERE design_id IS NOT NULL AND parent_asset_id IS NULL"
                ))

    feedback_columns = {
        c["name"] for c in inspector.get_columns("feedback_events")}
    if "image_run_id" not in feedback_columns:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE feedback_events "
                "ADD COLUMN image_run_id VARCHAR(32)"))
    if "subject_kind" not in feedback_columns:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE feedback_events "
                "ADD COLUMN subject_kind VARCHAR(16) DEFAULT 'asset'"))

    # Exact Present candidates add only an optional immutable-spec binding.
    # Historical pre-spec candidates remain valid with NULL design_version;
    # the many-output job link and View candidate ledger are new tables made
    # by create_all before this compatibility pass.
    if inspector.has_table("studio_presentation_candidates"):
        presentation_columns = {
            c["name"]
            for c in inspector.get_columns("studio_presentation_candidates")
        }
        for column, declaration in {
            "design_version": "INTEGER",
            "expected_active_asset_id": (
                "VARCHAR(32) REFERENCES image_assets(id)"
            ),
        }.items():
            if column not in presentation_columns:
                with engine.begin() as conn:
                    conn.execute(text(
                        "ALTER TABLE studio_presentation_candidates "
                        f"ADD COLUMN {column} {declaration}"))

    # Catalog/visual PreviewCandidate rows predate durable StudioJob binding.
    # Historical candidates remain readable with NULL; new catalog previews
    # bind one canonical Refine job to one temporary candidate.
    if inspector.has_table("preview_candidates"):
        preview_columns = {
            c["name"] for c in inspector.get_columns("preview_candidates")
        }
        if "studio_job_id" not in preview_columns:
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE preview_candidates "
                    "ADD COLUMN studio_job_id VARCHAR(32) "
                    "REFERENCES studio_jobs(id)"
                ))
        preview_indexes = {
            item["name"]
            for item in inspect(engine).get_indexes("preview_candidates")
        }
        if "uq_preview_candidates_studio_job_id" not in preview_indexes:
            with engine.begin() as conn:
                conn.execute(text(
                    "CREATE UNIQUE INDEX uq_preview_candidates_studio_job_id "
                    "ON preview_candidates (studio_job_id) "
                    "WHERE studio_job_id IS NOT NULL"
                ))

    # Visual Refine generation now records a durable backend-owned reservation
    # while provider work is outside the database transaction. Historical jobs
    # remain unreserved and retain their existing lifecycle behavior.
    if inspector.has_table("studio_jobs"):
        studio_job_columns = {
            c["name"] for c in inspector.get_columns("studio_jobs")
        }
        if "reservation_kind" not in studio_job_columns:
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE studio_jobs "
                    "ADD COLUMN reservation_kind VARCHAR(24)"
                ))
        studio_job_indexes = {
            item["name"] for item in inspect(engine).get_indexes("studio_jobs")
        }
        if "ix_studio_jobs_reservation_kind" not in studio_job_indexes:
            with engine.begin() as conn:
                conn.execute(text(
                    "CREATE INDEX ix_studio_jobs_reservation_kind "
                    "ON studio_jobs (reservation_kind)"
                ))


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
    (port 6543, or an explicit ``?pgbouncer=true`` hint) is incompatible with
    prepared statements — so psycopg's prepare cache is disabled there, and the
    non-libpq ``pgbouncer`` query flag (which psycopg would reject) is stripped.
    Session-pooler connections on port 5432 keep prepared statements enabled.
    """
    url = normalize_database_url(raw_url)
    parsed = make_url(url)
    if parsed.get_backend_name() == "sqlite":
        return url, {"connect_args": {"check_same_thread": False}}

    query = {k.lower(): str(v).lower() for k, v in parsed.query.items()}
    pooled = (
        parsed.port == 6543
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
def _initialize_engine():
    url, kwargs = engine_config(env_value("DATABASE_URL", DEFAULT_DATABASE_URL))
    engine = create_engine(url, **kwargs)
    Base.metadata.create_all(engine)
    _apply_additive_migrations(engine)
    return engine


def get_engine():
    """Return the single engine after one thread-safe schema initialization.

    ``lru_cache`` keeps completed calls safe but may execute a cache miss more
    than once when requests arrive concurrently. Locking the cache lookup and
    initialization prevents duplicate SQLite DDL during the first requests.
    """
    with _engine_initialization_lock:
        return _initialize_engine()


def get_db():
    session = sessionmaker(bind=get_engine(), autoflush=False)()
    try:
        yield session
    finally:
        session.close()

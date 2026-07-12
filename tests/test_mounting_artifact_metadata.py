"""Persistence contract for designer-reviewed mounting-view artifacts."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from facetta.db import (
    Base,
    DerivedArtifactMetadata,
    ImageAsset,
    ImageRun,
    ImageRunReview,
    MOUNTING_ARTIFACT_AUTHORITY_SCOPE,
    MOUNTING_ARTIFACT_KIND,
    MOUNTING_ARTIFACT_SCHEMA_VERSION,
    MOUNTING_ARTIFACT_VIEWS,
    MOUNTING_HIDDEN_GEOMETRY_STATUSES,
    _apply_additive_migrations,
)


SOURCE_HASH = "a" * 64
SPEC_VISUAL_HASH = "b" * 16
DISCLAIMER = (
    "AI-generated, designer-reviewed factory discussion context only. "
    "Do not measure or manufacture from this image."
)


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _seed_reviewed_mounting_asset(db: Session) -> None:
    db.add_all([
        ImageAsset(
            id="ast_source",
            root_id="ast_source",
            design_version=3,
            capability="SPEC_RENDER",
            image=b"source",
            media_type="image/png",
            created_by="usr_gia",
        ),
        ImageAsset(
            id="ast_mounting",
            root_id="ast_source",
            parent_asset_id="ast_source",
            design_version=3,
            capability="FACTORY_REVIEW_MOUNTING_VIEW",
            image=b"mounting-view",
            media_type="image/png",
            created_by="usr_gia",
        ),
        ImageRun(
            id="run_mounting",
            project_root_id="ast_source",
            source_asset_id="ast_source",
            operation="MOUNTING_VIEW_GENERATE",
            normalized_intent={"view": "side"},
            prompt_version="mounting-view.v1",
            input_hash="c" * 64,
            source_hash=SOURCE_HASH,
            spec_visual_hash=SPEC_VISUAL_HASH,
            status="review_required",
            created_by="usr_gia",
        ),
        ImageRunReview(
            id="irr_mounting",
            run_id="run_mounting",
            decision="accepted",
            accepted_asset_id="ast_mounting",
            created_by="usr_gia",
        ),
    ])
    db.flush()


def _metadata(**overrides: object) -> DerivedArtifactMetadata:
    values: dict[str, object] = {
        "asset_id": "ast_mounting",
        "view": "side",
        "hidden_geometry_status": (
            "proposed_designer_confirmation_required"
        ),
        "source_asset_ids": ["ast_source"],
        "source_hashes": {"ast_source": SOURCE_HASH},
        "design_version": 3,
        "spec_visual_hash": SPEC_VISUAL_HASH,
        "image_run_id": "run_mounting",
        "review_id": "irr_mounting",
        "disclaimer": DISCLAIMER,
    }
    values.update(overrides)
    return DerivedArtifactMetadata(**values)


def test_reviewed_mounting_metadata_round_trips_with_safe_defaults():
    SessionFactory = _session_factory()
    with SessionFactory() as db:
        _seed_reviewed_mounting_asset(db)
        db.add(_metadata())
        db.commit()

        stored = db.scalar(select(DerivedArtifactMetadata))
        assert stored is not None
        assert stored.asset_id == "ast_mounting"
        assert stored.schema_version == MOUNTING_ARTIFACT_SCHEMA_VERSION
        assert stored.artifact_kind == MOUNTING_ARTIFACT_KIND
        assert stored.view == "side"
        assert stored.authority_scope == MOUNTING_ARTIFACT_AUTHORITY_SCOPE
        assert stored.hidden_geometry_status == (
            "proposed_designer_confirmation_required"
        )
        assert stored.source_asset_ids == ["ast_source"]
        assert stored.source_hashes == {"ast_source": SOURCE_HASH}
        assert stored.design_version == 3
        assert stored.spec_visual_hash == SPEC_VISUAL_HASH
        assert stored.image_run_id == "run_mounting"
        assert stored.review_id == "irr_mounting"
        assert stored.production_authority is False
        assert stored.disclaimer == DISCLAIMER


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param(
            {"schema_version": "facetta.mounting-view.v0"},
            id="schema-version",
        ),
        pytest.param(
            {"artifact_kind": "technical_drawing"},
            id="artifact-kind",
        ),
        pytest.param({"view": "three_quarter"}, id="canonical-view"),
        pytest.param(
            {"authority_scope": "factory_truth"},
            id="authority-scope",
        ),
        pytest.param(
            {"hidden_geometry_status": "factory_confirmed"},
            id="hidden-geometry",
        ),
        pytest.param({"design_version": 0}, id="design-version"),
        pytest.param({"spec_visual_hash": "short"}, id="spec-hash"),
        pytest.param(
            {"production_authority": True},
            id="production-authority",
        ),
        pytest.param({"disclaimer": "   "}, id="disclaimer"),
        pytest.param({"review_id": None}, id="designer-review"),
    ],
)
def test_mounting_metadata_rejects_unsafe_scalar_claims(
    overrides: dict[str, object],
):
    SessionFactory = _session_factory()
    with SessionFactory() as db:
        _seed_reviewed_mounting_asset(db)
        db.add(_metadata(**overrides))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_mounting_metadata_constants_match_database_contract():
    assert MOUNTING_ARTIFACT_VIEWS == ("plan", "front", "side", "section")
    assert MOUNTING_HIDDEN_GEOMETRY_STATUSES == (
        "source_observed",
        "spec_confirmed",
        "proposed_designer_confirmation_required",
        "designer_confirmed_visual_proposal",
        "unknown",
    )


def test_additive_bootstrap_creates_metadata_table_without_rewriting_assets():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE designs (id VARCHAR(32) PRIMARY KEY, "
            "created_by VARCHAR(32), created_at DATETIME)"
        ))
        connection.execute(text(
            "CREATE TABLE image_assets (id VARCHAR(32) PRIMARY KEY, "
            "root_id VARCHAR(32), parent_asset_id VARCHAR(32), "
            "capability VARCHAR(48), image BLOB, media_type VARCHAR(24), "
            "created_by VARCHAR(32), created_at DATETIME)"
        ))
        connection.execute(text(
            "CREATE TABLE image_runs (id VARCHAR(32) PRIMARY KEY)"
        ))
        connection.execute(text(
            "CREATE TABLE image_attempts (id VARCHAR(32) PRIMARY KEY, "
            "run_id VARCHAR(32))"
        ))
        connection.execute(text(
            "INSERT INTO image_assets "
            "(id, root_id, capability, image, media_type, created_by) "
            "VALUES ('ast_legacy', 'ast_legacy', 'JEWELRY_RENDER', X'00', "
            "'image/png', 'usr_legacy')"
        ))

    # Production boot order creates entirely new additive tables first, then
    # adds nullable columns to pre-existing tables without rewriting old rows.
    Base.metadata.create_all(engine)
    _apply_additive_migrations(engine)

    inspector = inspect(engine)
    assert DerivedArtifactMetadata.__tablename__ in inspector.get_table_names()
    columns = {
        column["name"]: column
        for column in inspector.get_columns(
            DerivedArtifactMetadata.__tablename__
        )
    }
    assert {
        "asset_id",
        "schema_version",
        "artifact_kind",
        "view",
        "authority_scope",
        "hidden_geometry_status",
        "source_asset_ids",
        "source_hashes",
        "design_version",
        "spec_visual_hash",
        "image_run_id",
        "review_id",
        "production_authority",
        "disclaimer",
    } <= columns.keys()
    assert columns["review_id"]["nullable"] is False
    assert columns["production_authority"]["nullable"] is False

    with engine.connect() as connection:
        legacy = connection.execute(text(
            "SELECT design_id, design_version FROM image_assets "
            "WHERE id = 'ast_legacy'"
        )).one()
    assert legacy == (None, None)

"""Additive Studio family and immutable project-revision persistence."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from facetta.db import (
    Base,
    DesignFamily,
    ImageAsset,
    ImmutableProjectRevisionRecordError,
    InvalidProjectRevisionAssetError,
    Project,
    ProjectRevisionRecord,
    _apply_additive_migrations,
)
from facetta.api.studio import list_design_families


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _asset(
    asset_id: str,
    *,
    root_id: str | None = None,
    parent_asset_id: str | None = None,
    capability: str = "SPEC_RENDER",
) -> ImageAsset:
    return ImageAsset(
        id=asset_id,
        root_id=root_id or asset_id,
        parent_asset_id=parent_asset_id,
        design_version=1,
        capability=capability,
        image=b"image",
        media_type="image/png",
        created_by="usr_studio",
    )


def _revision(
    revision_id: str,
    asset_id: str,
    *,
    action: str = "created",
    restored_from_asset_id: str | None = None,
    change_summary: str = "Created the first Studio variation.",
) -> ProjectRevisionRecord:
    return ProjectRevisionRecord(
        id=revision_id,
        asset_id=asset_id,
        action=action,
        raw_intent={
            "text": "Keep the center stone and explore a lower gallery.",
            "source": "designer_text",
        },
        interpretation={
            "target": "setting.gallery",
            "factory_specification_impact": True,
            "frozen": ["center stone", "metal", "side-stone inventory"],
        },
        change_summary=change_summary,
        restored_from_asset_id=restored_from_asset_id,
        created_by="usr_studio",
    )


def test_fresh_schema_contains_studio_tables_and_project_metadata():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    inspector = inspect(engine)

    assert {
        DesignFamily.__tablename__,
        ProjectRevisionRecord.__tablename__,
    } <= set(inspector.get_table_names())
    project_columns = {
        column["name"] for column in inspector.get_columns("projects")}
    assert {
        "family_id",
        "variation_index",
        "variation_label",
        "branched_from_project_root_id",
        "branched_from_asset_id",
    } <= project_columns
    project_checks = {
        check["name"] for check in inspector.get_check_constraints("projects")}
    assert "ck_project_variation_index" in project_checks
    revision_indexes = {
        item["name"]: item
        for item in inspector.get_indexes(
            ProjectRevisionRecord.__tablename__
        )
    }
    assert revision_indexes["uq_project_revision_record_asset"]["unique"] == 1


def test_family_groups_sibling_projects_without_sharing_revision_history():
    SessionFactory = _session_factory()
    with SessionFactory() as db:
        family = DesignFamily(
            id="fam_solitaire",
            owner="usr_studio",
            title="Low-profile oval solitaire studies",
        )
        root_asset = _asset("ast_original")
        db.add_all([
            family,
            root_asset,
            Project(
                root_id=root_asset.id,
                owner="usr_studio",
                title="Original direction",
                tags=["oval", "solitaire"],
                family_id=family.id,
                variation_index=1,
                variation_label="Original",
            ),
        ])
        db.commit()

        sibling_asset = _asset("ast_low_gallery")
        db.add_all([
            sibling_asset,
            Project(
                root_id=sibling_asset.id,
                owner="usr_studio",
                title="Lower gallery direction",
                tags=["oval", "solitaire", "low-profile"],
                family_id=family.id,
                variation_index=2,
                variation_label="Low gallery",
                branched_from_project_root_id=root_asset.id,
                branched_from_asset_id=root_asset.id,
            ),
            _revision("prr_original", root_asset.id),
            _revision(
                "prr_low_gallery",
                sibling_asset.id,
                change_summary="Branched a lower-gallery Studio direction.",
            ),
        ])
        db.commit()

        siblings = list(db.scalars(
            select(Project)
            .where(Project.family_id == family.id)
            .order_by(Project.variation_index)
        ))
        assert [project.variation_index for project in siblings] == [1, 2]
        assert siblings[1].branched_from_project_root_id == root_asset.id
        assert siblings[1].branched_from_asset_id == root_asset.id
        assert siblings[0].root_id != siblings[1].root_id

        records = list(db.scalars(
            select(ProjectRevisionRecord)
            .order_by(ProjectRevisionRecord.id)
        ))
        assert {record.asset_id for record in records} == {
            root_asset.id,
            sibling_asset.id,
        }
        assert records[0].raw_intent["source"] == "designer_text"
        assert records[0].interpretation[
            "factory_specification_impact"
        ] is True


def test_family_list_preserves_variations_and_filters_by_owner():
    SessionFactory = _session_factory()
    with SessionFactory() as db:
        first_asset = _asset("ast_family_one")
        second_asset = _asset("ast_family_two")
        db.add_all([
            DesignFamily(
                id="fam_one",
                owner="usr_studio",
                title="Emerald directions",
            ),
            DesignFamily(
                id="fam_two",
                owner="usr_other",
                title="Private directions",
            ),
            first_asset,
            second_asset,
            Project(
                root_id=first_asset.id,
                owner="usr_studio",
                title="Original emerald direction",
                tags=["emerald"],
                family_id="fam_one",
                variation_index=1,
                variation_label="Original",
            ),
            Project(
                root_id=second_asset.id,
                owner="usr_other",
                title="Other owner's direction",
                tags=[],
                family_id="fam_two",
                variation_index=1,
                variation_label="Original",
            ),
        ])
        db.commit()

        result = list_design_families(db=db, owner="usr_studio")

        assert [family["family_id"] for family in result["families"]] == [
            "fam_one",
        ]
        assert result["families"][0]["title"] == "Emerald directions"
        assert [
            variation["root_id"]
            for variation in result["families"][0]["variations"]
        ] == ["ast_family_one"]
        assert result["families"][0]["variations"][0][
            "variation_label"
        ] == "Original"


def test_project_variation_index_must_be_positive_when_present():
    SessionFactory = _session_factory()
    with SessionFactory() as db:
        db.add(Project(
            root_id="ast_bad_variation",
            owner="usr_studio",
            title="Invalid variation",
            tags=[],
            variation_index=0,
        ))
        with pytest.raises(IntegrityError):
            db.commit()


@pytest.mark.parametrize(
    "record",
    [
        pytest.param(
            _revision("prr_bad_action", "ast_target", action="regenerate"),
            id="unsupported-action",
        ),
        pytest.param(
            _revision("prr_restore_without_source", "ast_target", action="restore"),
            id="restore-without-source",
        ),
        pytest.param(
            _revision(
                "prr_edit_with_restore_source",
                "ast_target",
                action="edit",
                restored_from_asset_id="ast_source",
            ),
            id="non-restore-with-source",
        ),
        pytest.param(
            _revision(
                "prr_self_restore",
                "ast_target",
                action="restore",
                restored_from_asset_id="ast_target",
            ),
            id="self-restore",
        ),
        pytest.param(
            _revision(
                "prr_blank_summary",
                "ast_target",
                change_summary="   ",
            ),
            id="blank-summary",
        ),
    ],
)
def test_revision_record_rejects_ambiguous_history(
    record: ProjectRevisionRecord,
):
    SessionFactory = _session_factory()
    with SessionFactory() as db:
        db.add_all([_asset("ast_source"), _asset("ast_target"), record])
        with pytest.raises(IntegrityError):
            db.commit()


def test_primary_asset_has_exactly_one_revision_record():
    SessionFactory = _session_factory()
    with SessionFactory() as db:
        db.add(_asset("ast_primary"))
        db.add_all([
            _revision("prr_first", "ast_primary"),
            _revision(
                "prr_duplicate",
                "ast_primary",
                action="edit",
                change_summary="Contradictory second explanation.",
            ),
        ])
        with pytest.raises(IntegrityError):
            db.commit()


def test_revision_record_cannot_bind_to_a_derived_asset():
    SessionFactory = _session_factory()
    with SessionFactory() as db:
        db.add_all([
            _asset("ast_root"),
            _asset(
                "ast_line_art",
                root_id="ast_root",
                parent_asset_id="ast_root",
                capability="LINE_ART",
            ),
            _revision("prr_derived", "ast_line_art"),
        ])
        with pytest.raises(
            InvalidProjectRevisionAssetError,
            match="primary visual asset",
        ):
            db.commit()


def test_restore_record_binds_the_new_primary_to_its_exact_source():
    SessionFactory = _session_factory()
    with SessionFactory() as db:
        db.add_all([
            _asset("ast_old"),
            _asset(
                "ast_restored",
                root_id="ast_old",
                parent_asset_id="ast_old",
                capability="LOCALIZED_EDIT",
            ),
        ])
        record = _revision(
            "prr_restore",
            "ast_restored",
            action="restore",
            restored_from_asset_id="ast_old",
            change_summary="Restored the approved earlier direction.",
        )
        db.add(record)
        db.commit()

        stored = db.get(ProjectRevisionRecord, record.id)
        assert stored is not None
        assert stored.action == "restore"
        assert stored.restored_from_asset_id == "ast_old"


def test_revision_records_reject_update_and_delete():
    SessionFactory = _session_factory()
    with SessionFactory() as db:
        db.add_all([
            _asset("ast_primary"),
            _revision("prr_immutable", "ast_primary"),
        ])
        db.commit()

    with SessionFactory() as db:
        record = db.get(ProjectRevisionRecord, "prr_immutable")
        assert record is not None
        record.change_summary = "Attempted rewrite"
        with pytest.raises(
            ImmutableProjectRevisionRecordError,
            match="immutable",
        ):
            db.commit()
        db.rollback()

    with SessionFactory() as db:
        record = db.get(ProjectRevisionRecord, "prr_immutable")
        assert record is not None
        db.delete(record)
        with pytest.raises(
            ImmutableProjectRevisionRecordError,
            match="cannot be deleted",
        ):
            db.commit()
        db.rollback()

    with SessionFactory() as db:
        stored = db.get(ProjectRevisionRecord, "prr_immutable")
        assert stored is not None
        assert stored.change_summary == "Created the first Studio variation."


def test_additive_bootstrap_preserves_legacy_projects_with_null_studio_fields():
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
            "CREATE TABLE projects (root_id VARCHAR(32) PRIMARY KEY, "
            "owner VARCHAR(32), collection VARCHAR(120), title VARCHAR(200), "
            "tags JSON, created_at DATETIME, updated_at DATETIME)"
        ))
        connection.execute(text(
            "INSERT INTO projects "
            "(root_id, owner, title, tags) VALUES "
            "('ast_legacy', 'usr_legacy', 'Legacy project', '[]')"
        ))

    Base.metadata.create_all(engine)
    _apply_additive_migrations(engine)

    inspector = inspect(engine)
    columns = {
        column["name"] for column in inspector.get_columns("projects")}
    assert {
        "family_id",
        "variation_index",
        "variation_label",
        "branched_from_project_root_id",
        "branched_from_asset_id",
    } <= columns
    assert {
        DesignFamily.__tablename__,
        ProjectRevisionRecord.__tablename__,
    } <= set(inspector.get_table_names())
    assert {
        "ix_projects_family_id",
        "ix_projects_branched_from_project_root_id",
        "ix_projects_branched_from_asset_id",
    } <= {
        item["name"] for item in inspector.get_indexes("projects")
    }
    with engine.connect() as connection:
        legacy = connection.execute(text(
            "SELECT family_id, variation_index, variation_label, "
            "branched_from_project_root_id, branched_from_asset_id "
            "FROM projects WHERE root_id = 'ast_legacy'"
        )).one()
    assert legacy == (None, None, None, None, None)

    with engine.begin() as connection:
        with pytest.raises(IntegrityError):
            connection.execute(text(
                "INSERT INTO projects "
                "(root_id, owner, title, tags, variation_index) VALUES "
                "('ast_invalid', 'usr_legacy', 'Invalid', '[]', 0)"
            ))

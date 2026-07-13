"""Pre-spec Studio history must follow the designer-selected visual."""

import hashlib

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from facetta.db import Base, ImageAsset, Project, ProjectRevisionRecord
from facetta.api.studio import studio_history
from facetta.studio_history import (
    StudioHistoryError,
    fork_project_variation,
    restore_project_revision,
)


def _record(asset_id: str) -> ProjectRevisionRecord:
    return ProjectRevisionRecord(
        id=f"prr_{asset_id}", asset_id=asset_id, action="created",
        raw_intent={"kind": "test_direction"},
        interpretation={"operation": "create_direction"},
        change_summary="Created a test direction.", created_by="designer",
    )


def test_variation_branches_the_selected_creative_candidate_not_last_generated():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        source = ImageAsset(
            id="ast_source",
            root_id="ast_source",
            parent_asset_id=None,
            design_version=None,
            capability="CREATIVE_SOURCE",
            image=b"source",
            media_type="image/png",
            created_by="designer",
        )
        selected = ImageAsset(
            id="ast_direction_one",
            root_id=source.id,
            parent_asset_id=source.id,
            design_version=None,
            capability="CREATIVE_RENDER",
            image=b"selected",
            media_type="image/png",
            created_by="designer",
        )
        generated_later = ImageAsset(
            id="ast_direction_two",
            root_id=source.id,
            parent_asset_id=source.id,
            design_version=None,
            capability="CREATIVE_RENDER",
            image=b"later",
            media_type="image/png",
            created_by="designer",
        )
        project = Project(
            root_id=source.id,
            owner="designer",
            title="Two directions",
            tags=[],
            selected_candidate_asset_id=selected.id,
        )
        db.add_all([source, selected, generated_later, project])
        db.commit()

        initial_history = studio_history(project.root_id, db)
        assert initial_history["active_asset_id"] == selected.id
        assert initial_history["variation_index"] == 1
        assert initial_history["family_id"] is None
        db.refresh(project)
        assert project.variation_index is None
        assert project.family_id is None

        result = fork_project_variation(
            db,
            project_root_id=project.root_id,
            source_asset_id=selected.id,
            expected_active_asset_id=selected.id,
            expected_design_version=None,
            variation_label="Chosen direction",
            created_by="designer",
        )

        branched = db.get(ImageAsset, result.asset_id)
        assert branched is not None
        assert bytes(branched.image) == b"selected"
        assert branched.design_version is None
        assert branched.capability == "VARIATION_BRANCH"
        branch_project = db.get(Project, result.project_root_id)
        assert branch_project is not None
        assert branch_project.selected_candidate_asset_id == branched.id
        branch_record = db.scalar(select(ProjectRevisionRecord).where(
            ProjectRevisionRecord.asset_id == branched.id
        ))
        selected_hash = hashlib.sha256(b"selected").hexdigest()
        assert branch_record is not None
        assert branch_record.interpretation["source_sha256"] == selected_hash
        assert branch_record.interpretation["output_sha256"] == selected_hash

        with pytest.raises(StudioHistoryError) as error:
            restore_project_revision(
                db,
                project_root_id=project.root_id,
                restore_asset_id=generated_later.id,
                expected_active_asset_id=selected.id,
                expected_design_version=None,
                created_by="designer",
            )
        assert error.value.code == "restore_source_not_revision"


def test_pre_spec_branch_and_restore_require_the_project_owner():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        source = ImageAsset(
            id="ast_owner_source",
            root_id="ast_owner_source",
            parent_asset_id=None,
            design_version=None,
            capability="CREATIVE_RENDER",
            image=b"owner source",
            media_type="image/png",
            created_by="designer",
        )
        earlier = ImageAsset(
            id="ast_owner_earlier",
            root_id=source.id,
            parent_asset_id=source.id,
            design_version=None,
            capability="CREATIVE_RENDER",
            image=b"earlier",
            media_type="image/png",
            created_by="designer",
        )
        project = Project(
            root_id=source.id,
            owner="designer",
            title="Owner-bound direction",
            tags=[],
            selected_candidate_asset_id=source.id,
        )
        db.add_all([source, earlier, project])
        db.commit()

        with pytest.raises(StudioHistoryError) as branch_error:
            fork_project_variation(
                db,
                project_root_id=project.root_id,
                source_asset_id=source.id,
                expected_active_asset_id=source.id,
                expected_design_version=None,
                variation_label="Intruder branch",
                created_by="intruder",
            )
        assert branch_error.value.code == "variation_source_unavailable"
        assert branch_error.value.status_code == 404

        with pytest.raises(StudioHistoryError) as restore_error:
            restore_project_revision(
                db,
                project_root_id=project.root_id,
                restore_asset_id=earlier.id,
                expected_active_asset_id=source.id,
                expected_design_version=None,
                created_by="intruder",
            )
        assert restore_error.value.code == "restore_revision_unavailable"
        assert restore_error.value.status_code == 404
        assert db.query(Project).count() == 1
        assert db.query(ImageAsset).count() == 2


def test_branch_rejects_source_bytes_that_drift_from_recorded_hash():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        source = ImageAsset(
            id="ast_branch_hash", root_id="ast_branch_hash",
            parent_asset_id=None, design_version=None,
            capability="CREATIVE_RENDER", image=b"recorded branch source",
            media_type="image/png", created_by="designer",
        )
        db.add_all([
            source,
            Project(
                root_id=source.id, owner="designer", title="Hash-bound branch",
                tags=[], selected_candidate_asset_id=source.id,
            ),
            _record(source.id),
        ])
        db.commit()
        db.execute(
            text("UPDATE image_assets SET image = :image WHERE id = :id"),
            {"image": b"corrupt", "id": source.id},
        )
        db.commit()
        db.expire_all()

        with pytest.raises(StudioHistoryError) as error:
            fork_project_variation(
                db, project_root_id=source.id, source_asset_id=source.id,
                expected_active_asset_id=source.id,
                expected_design_version=None, variation_label="Must fail",
                created_by="designer",
            )
        assert error.value.code == "variation_source_hash_mismatch"


def test_restore_rejects_source_bytes_that_drift_from_recorded_hash():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        active = ImageAsset(
            id="ast_restore_active", root_id="ast_restore_active",
            parent_asset_id=None, design_version=None,
            capability="CREATIVE_RENDER", image=b"active",
            media_type="image/png", created_by="designer",
        )
        earlier = ImageAsset(
            id="ast_restore_earlier", root_id=active.id,
            parent_asset_id=active.id, design_version=None,
            capability="RESTORED_REVISION", image=b"recorded earlier source",
            media_type="image/png", created_by="designer",
        )
        db.add_all([
            active, earlier,
            Project(
                root_id=active.id, owner="designer", title="Hash-bound restore",
                tags=[], selected_candidate_asset_id=active.id,
            ),
            _record(active.id), _record(earlier.id),
        ])
        db.commit()
        db.execute(
            text("UPDATE image_assets SET image = :image WHERE id = :id"),
            {"image": b"corrupt", "id": earlier.id},
        )
        db.commit()
        db.expire_all()

        with pytest.raises(StudioHistoryError) as error:
            restore_project_revision(
                db, project_root_id=active.id, restore_asset_id=earlier.id,
                expected_active_asset_id=active.id,
                expected_design_version=None, created_by="designer",
            )
        assert error.value.code == "restore_source_hash_mismatch"

"""Pre-spec Studio history must follow the designer-selected visual."""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from facetta.db import Base, ImageAsset, Project
from facetta.api.studio import studio_history
from facetta.studio_history import fork_project_variation, restore_project_revision


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

        assert studio_history(project.root_id, db)["active_asset_id"] == selected.id

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

        restored = restore_project_revision(
            db,
            project_root_id=project.root_id,
            restore_asset_id=generated_later.id,
            expected_active_asset_id=selected.id,
            expected_design_version=None,
            created_by="designer",
        )
        db.refresh(project)
        restored_asset = db.get(ImageAsset, restored.asset_id)
        assert restored_asset is not None
        assert restored_asset.parent_asset_id == selected.id
        assert bytes(restored_asset.image) == b"later"
        assert project.selected_candidate_asset_id == restored_asset.id

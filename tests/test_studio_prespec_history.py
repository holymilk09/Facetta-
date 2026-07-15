"""Pre-spec Studio history must follow the designer-selected visual."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import create_engine, select, text, update
from sqlalchemy.orm import Session

import facetta.studio_history as studio_history_service
from facetta.db import (
    Base,
    ImageAsset,
    Project,
    ProjectRevisionRecord,
    StudioVariationDecisionRecord,
)
from facetta.api.studio import studio_history
from facetta.project_backbone import confirmable_pre_spec_asset
from facetta.studio_history import (
    StudioHistoryError,
    ensure_project_family,
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


def test_variation_operation_replays_exact_result_and_rejects_mismatched_reuse():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        source = ImageAsset(
            id="ast_retry_source", root_id="ast_retry_source",
            parent_asset_id=None, design_version=None,
            capability="CREATIVE_RENDER", image=b"retry source",
            media_type="image/png", created_by="designer",
        )
        db.add_all([
            source,
            Project(
                root_id=source.id, owner="designer", title="Retry-safe Vary",
                tags=[], selected_candidate_asset_id=source.id,
            ),
            _record(source.id),
        ])
        db.commit()

        request = {
            "project_root_id": source.id,
            "source_asset_id": source.id,
            "expected_active_asset_id": source.id,
            "expected_design_version": None,
            "variation_label": "Exact sibling",
            "created_by": "designer",
            "operation_id": "vary:domain-retry-0001",
        }
        first = fork_project_variation(db, **request)
        replay = fork_project_variation(db, **request)

        assert replay == first
        assert db.query(StudioVariationDecisionRecord).count() == 1
        assert db.query(Project).count() == 2
        assert db.query(ImageAsset).count() == 2

        with pytest.raises(StudioHistoryError) as conflict:
            fork_project_variation(
                db,
                **{**request, "variation_label": "Changed sibling"},
            )
        assert conflict.value.code == "variation_operation_conflict"
        assert conflict.value.status_code == 409
        assert db.query(Project).count() == 2


def test_concurrent_variation_retries_converge_on_one_committed_child(
    tmp_path,
    monkeypatch,
):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'vary-concurrency.sqlite'}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        source = ImageAsset(
            id="ast_concurrent_source", root_id="ast_concurrent_source",
            parent_asset_id=None, design_version=None,
            capability="CREATIVE_RENDER", image=b"concurrent source",
            media_type="image/png", created_by="designer",
        )
        project = Project(
            root_id=source.id, owner="designer", title="Concurrent Vary",
            tags=[], selected_candidate_asset_id=source.id,
        )
        db.add_all([source, project, _record(source.id)])
        db.flush()
        ensure_project_family(db, project)
        db.commit()

    branch_barrier = Barrier(2)
    original_new_id = studio_history_service.new_id

    def synchronized_new_id(prefix: str) -> str:
        if prefix == "ast":
            branch_barrier.wait(timeout=5)
        return original_new_id(prefix)

    monkeypatch.setattr(studio_history_service, "new_id", synchronized_new_id)
    request = {
        "project_root_id": "ast_concurrent_source",
        "source_asset_id": "ast_concurrent_source",
        "expected_active_asset_id": "ast_concurrent_source",
        "expected_design_version": None,
        "variation_label": "One sibling",
        "created_by": "designer",
        "operation_id": "vary:concurrent-retry-0001",
    }

    def create_branch():
        with Session(engine) as db:
            return fork_project_variation(db, **request)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: create_branch(), range(2)))

    assert results[0] == results[1]
    with Session(engine) as db:
        assert db.query(StudioVariationDecisionRecord).count() == 1
        assert db.query(Project).count() == 2
        assert db.query(ImageAsset).count() == 2


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
        branch_chain = list(db.scalars(
            select(ImageAsset).where(ImageAsset.root_id == branch_project.root_id)
        ))
        assert confirmable_pre_spec_asset(
            db,
            branch_project,
            branch_chain,
            branch_project.selected_candidate_asset_id,
        ) == branched

        nested_result = fork_project_variation(
            db,
            project_root_id=branch_project.root_id,
            source_asset_id=branched.id,
            expected_active_asset_id=branched.id,
            expected_design_version=None,
            variation_label="Nested direction",
            created_by="designer",
        )
        nested_project = db.get(Project, nested_result.project_root_id)
        nested_asset = db.get(ImageAsset, nested_result.asset_id)
        nested_chain = list(db.scalars(
            select(ImageAsset).where(
                ImageAsset.root_id == nested_result.project_root_id
            )
        ))
        assert nested_project is not None and nested_asset is not None
        assert confirmable_pre_spec_asset(
            db,
            nested_project,
            nested_chain,
            nested_project.selected_candidate_asset_id,
        ) == nested_asset

        refined_branch = ImageAsset(
            id="ast_nested_refinement",
            root_id=nested_project.root_id,
            parent_asset_id=nested_asset.id,
            design_version=None,
            capability="LOCALIZED_EDIT",
            image=b"nested refinement",
            media_type="image/png",
            created_by="designer",
        )
        nested_project.selected_candidate_asset_id = refined_branch.id
        db.add_all([refined_branch, _record(refined_branch.id)])
        db.commit()
        nested_chain.append(refined_branch)
        assert confirmable_pre_spec_asset(
            db,
            nested_project,
            nested_chain,
            nested_project.selected_candidate_asset_id,
        ) == refined_branch

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


def test_unproven_pre_spec_branch_fails_closed():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        branch = ImageAsset(
            id="ast_unproven_branch",
            root_id="ast_unproven_branch",
            parent_asset_id=None,
            design_version=None,
            capability="VARIATION_BRANCH",
            image=b"unproven branch",
            media_type="image/png",
            created_by="designer",
        )
        project = Project(
            root_id=branch.id,
            owner="designer",
            title="Unproven branch",
            tags=[],
            selected_candidate_asset_id=branch.id,
        )
        db.add_all([branch, project])
        db.commit()

        assert confirmable_pre_spec_asset(
            db,
            project,
            [branch],
            project.selected_candidate_asset_id,
        ) is None


def test_derived_product_photo_branch_cannot_gain_confirmation_authority():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        creative = ImageAsset(
            id="ast_derived_branch_origin",
            root_id="ast_derived_branch_origin",
            parent_asset_id=None,
            design_version=None,
            capability="CREATIVE_RENDER",
            image=b"creative origin",
            media_type="image/png",
            created_by="designer",
        )
        product_photo = ImageAsset(
            id="ast_derived_branch_photo",
            root_id=creative.id,
            parent_asset_id=creative.id,
            design_version=None,
            capability="PRODUCT_PHOTO",
            image=b"commerce derivative",
            media_type="image/png",
            created_by="designer",
        )
        project = Project(
            root_id=creative.id,
            owner="designer",
            title="Derived branch",
            tags=[],
            selected_candidate_asset_id=product_photo.id,
        )
        db.add_all([
            creative,
            product_photo,
            project,
            _record(creative.id),
            _record(product_photo.id),
        ])
        db.commit()

        result = fork_project_variation(
            db,
            project_root_id=project.root_id,
            source_asset_id=product_photo.id,
            expected_active_asset_id=product_photo.id,
            expected_design_version=None,
            variation_label="Commerce derivative",
            created_by="designer",
        )
        branch_project = db.get(Project, result.project_root_id)
        branch = db.get(ImageAsset, result.asset_id)
        assert branch_project is not None and branch is not None
        assert confirmable_pre_spec_asset(
            db,
            branch_project,
            [branch],
            branch_project.selected_candidate_asset_id,
        ) is None


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


def test_pre_spec_restore_remains_confirmable_from_its_creative_origin():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        original = ImageAsset(
            id="ast_restore_origin",
            root_id="ast_restore_origin",
            parent_asset_id=None,
            design_version=None,
            capability="CREATIVE_RENDER",
            image=b"original direction",
            media_type="image/png",
            created_by="designer",
        )
        refined = ImageAsset(
            id="ast_restore_refined",
            root_id=original.id,
            parent_asset_id=original.id,
            design_version=None,
            capability="LOCALIZED_EDIT",
            image=b"refined direction",
            media_type="image/png",
            created_by="designer",
        )
        project = Project(
            root_id=original.id,
            owner="designer",
            title="Restorable direction",
            tags=[],
            selected_candidate_asset_id=refined.id,
        )
        db.add_all([
            original,
            refined,
            project,
            _record(original.id),
            _record(refined.id),
        ])
        db.commit()

        result = restore_project_revision(
            db,
            project_root_id=project.root_id,
            restore_asset_id=original.id,
            expected_active_asset_id=refined.id,
            expected_design_version=None,
            created_by="designer",
        )
        db.refresh(project)
        restored = db.get(ImageAsset, result.asset_id)
        chain = list(db.scalars(
            select(ImageAsset).where(ImageAsset.root_id == project.root_id)
        ))

        assert restored is not None
        assert restored.capability == "RESTORED_REVISION"
        assert restored.parent_asset_id == refined.id
        assert bytes(restored.image) == bytes(original.image)
        assert project.selected_candidate_asset_id == restored.id
        assert confirmable_pre_spec_asset(
            db,
            project,
            chain,
            project.selected_candidate_asset_id,
        ) == restored


def test_restore_of_derived_product_photo_cannot_gain_confirmation_authority():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        creative = ImageAsset(
            id="ast_restore_derived_origin",
            root_id="ast_restore_derived_origin",
            parent_asset_id=None,
            design_version=None,
            capability="CREATIVE_RENDER",
            image=b"creative origin",
            media_type="image/png",
            created_by="designer",
        )
        product_photo = ImageAsset(
            id="ast_restore_derived_photo",
            root_id=creative.id,
            parent_asset_id=creative.id,
            design_version=None,
            capability="PRODUCT_PHOTO",
            image=b"commerce derivative",
            media_type="image/png",
            created_by="designer",
        )
        refined = ImageAsset(
            id="ast_restore_derived_refined",
            root_id=creative.id,
            parent_asset_id=product_photo.id,
            design_version=None,
            capability="LOCALIZED_EDIT",
            image=b"later refinement",
            media_type="image/png",
            created_by="designer",
        )
        project = Project(
            root_id=creative.id,
            owner="designer",
            title="Derived restore",
            tags=[],
            selected_candidate_asset_id=refined.id,
        )
        db.add_all([
            creative,
            product_photo,
            refined,
            project,
            _record(creative.id),
            _record(product_photo.id),
            _record(refined.id),
        ])
        db.commit()

        result = restore_project_revision(
            db,
            project_root_id=project.root_id,
            restore_asset_id=product_photo.id,
            expected_active_asset_id=refined.id,
            expected_design_version=None,
            created_by="designer",
        )
        db.refresh(project)
        restored = db.get(ImageAsset, result.asset_id)
        chain = list(db.scalars(
            select(ImageAsset).where(ImageAsset.root_id == project.root_id)
        ))
        assert restored is not None
        assert confirmable_pre_spec_asset(
            db,
            project,
            chain,
            project.selected_candidate_asset_id,
        ) is None


def test_pre_spec_restore_cas_rolls_back_a_late_competing_active_revision(
    monkeypatch: pytest.MonkeyPatch,
):
    """A restore may not win after another accepted visual changes active state.

    The component-map copy hook runs after the proposed child has been flushed,
    which lets this test reproduce the otherwise timing-dependent interval
    between initial validation and the final active-pointer write.
    """

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        earlier = ImageAsset(
            id="ast_restore_cas_earlier",
            root_id="ast_restore_cas_earlier",
            parent_asset_id=None,
            design_version=None,
            capability="CREATIVE_RENDER",
            image=b"earlier",
            media_type="image/png",
            created_by="designer",
        )
        active = ImageAsset(
            id="ast_restore_cas_active",
            root_id=earlier.id,
            parent_asset_id=earlier.id,
            design_version=None,
            capability="LOCALIZED_EDIT",
            image=b"active",
            media_type="image/png",
            created_by="designer",
        )
        competing = ImageAsset(
            id="ast_restore_cas_competing",
            root_id=earlier.id,
            parent_asset_id=active.id,
            design_version=None,
            capability="LOCALIZED_EDIT",
            image=b"competing",
            media_type="image/png",
            created_by="designer",
        )
        project = Project(
            root_id=earlier.id,
            owner="designer",
            title="Restore compare-and-set",
            tags=[],
            selected_candidate_asset_id=active.id,
        )
        db.add_all([
            earlier,
            active,
            competing,
            project,
            _record(earlier.id),
            _record(active.id),
        ])
        db.commit()

        def supersede_active_pointer(session, **_kwargs):
            session.execute(
                update(Project)
                .where(Project.root_id == project.root_id)
                .values(selected_candidate_asset_id=competing.id)
            )
            return None

        monkeypatch.setattr(
            "facetta.studio_history."
            "copy_revision_component_map_for_identical_raster",
            supersede_active_pointer,
        )

        with pytest.raises(StudioHistoryError) as error:
            restore_project_revision(
                db,
                project_root_id=project.root_id,
                restore_asset_id=earlier.id,
                expected_active_asset_id=active.id,
                expected_design_version=None,
                created_by="designer",
            )
        assert error.value.code == "stale_asset_revision"

        db.expire_all()
        stored_project = db.get(Project, project.root_id)
        assert stored_project is not None
        assert stored_project.selected_candidate_asset_id == active.id
        assert db.scalar(
            select(ImageAsset).where(
                ImageAsset.root_id == project.root_id,
                ImageAsset.capability == "RESTORED_REVISION",
            )
        ) is None
        assert db.scalar(
            select(ProjectRevisionRecord).where(
                ProjectRevisionRecord.action == "restore"
            )
        ) is None

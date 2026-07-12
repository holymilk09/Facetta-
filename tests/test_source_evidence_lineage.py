from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from facetta.db import Base, ImageAsset, ImageRun, ImageRunReview
from facetta.source_evidence_lineage import has_trusted_visual_spec_lineage


def _session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


def _asset(asset_id: str, *, parent: str | None, version: int) -> ImageAsset:
    return ImageAsset(
        id=asset_id,
        root_id="ast_root",
        parent_asset_id=parent,
        design_version=version,
        capability="IMPORTED_REFERENCE" if parent is None else "LOCAL_EDIT",
        image=b"image",
        media_type="image/png",
        created_by="usr_test",
    )


def _run(*, accepted_asset_id: str | None = "ast_edit") -> ImageRun:
    return ImageRun(
        id="run_edit",
        project_root_id="ast_root",
        source_asset_id="ast_root",
        operation="LOCAL_EDIT",
        normalized_intent={},
        prompt_version="local-edit-v1",
        source_spec_visual_hash="1111111111111111",
        spec_visual_hash="2222222222222222",
        variant=0,
        status="accepted" if accepted_asset_id else "review_required",
        accepted_asset_id=accepted_asset_id,
        created_by="usr_test",
    )


def test_exact_accepted_run_bridges_source_evidence_to_active_spec():
    with _session() as db:
        root = _asset("ast_root", parent=None, version=1)
        edit = _asset("ast_edit", parent="ast_root", version=2)
        db.add_all([root, edit, _run()])
        db.commit()

        assert has_trusted_visual_spec_lineage(
            db,
            active_asset=edit,
            source_spec_visual_hash="1111111111111111",
            target_spec_visual_hash="2222222222222222",
        )


def test_explicit_warning_review_is_an_accepted_lineage_edge():
    with _session() as db:
        root = _asset("ast_root", parent=None, version=1)
        edit = _asset("ast_edit", parent="ast_root", version=2)
        db.add_all([
            root,
            edit,
            _run(accepted_asset_id=None),
            ImageRunReview(
                id="irr_edit",
                run_id="run_edit",
                decision="accepted",
                accepted_asset_id="ast_edit",
                created_by="usr_test",
            ),
        ])
        db.commit()

        assert has_trusted_visual_spec_lineage(
            db,
            active_asset=edit,
            source_spec_visual_hash="1111111111111111",
            target_spec_visual_hash="2222222222222222",
        )


def test_unaccepted_or_hash_mismatched_run_cannot_carry_source_authority():
    with _session() as db:
        root = _asset("ast_root", parent=None, version=1)
        edit = _asset("ast_edit", parent="ast_root", version=2)
        db.add_all([root, edit, _run(accepted_asset_id=None)])
        db.commit()

        assert not has_trusted_visual_spec_lineage(
            db,
            active_asset=edit,
            source_spec_visual_hash="1111111111111111",
            target_spec_visual_hash="2222222222222222",
        )
        assert not has_trusted_visual_spec_lineage(
            db,
            active_asset=edit,
            source_spec_visual_hash="9999999999999999",
            target_spec_visual_hash="2222222222222222",
        )

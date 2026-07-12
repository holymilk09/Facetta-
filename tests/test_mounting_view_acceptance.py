from __future__ import annotations

import hashlib

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from conftest import HALO_SPEC
from facetta.db import (
    Base,
    DerivedArtifactMetadata,
    Design,
    DesignVersion,
    ImageAsset,
    ImageRun,
    ImageRunReview,
    Project,
)
from facetta.image_identity import spec_visual_hash
from facetta.project_backbone import is_primary_revision
from facetta.spec import Spec
from facetta.trusted_revision import accept_warning_revision
from facetta.warning_candidates import (
    MountingViewArtifactMetadata,
    clear_warning_candidates_for_tests,
    store_markup_warning_candidate,
)


SOURCE = b"\x89PNG\r\n\x1a\napproved-source"
CANDIDATE = b"\x89PNG\r\n\x1a\ndesigner-reviewed-side"
SPEC = Spec.model_validate(HALO_SPEC)


def _session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return factory()


def _seed(db: Session) -> None:
    db.add_all([
        Design(id="dsn_1", created_by="usr_designer"),
        DesignVersion(
            design_id="dsn_1",
            version=1,
            spec=SPEC.model_dump(mode="json"),
            created_by="usr_designer",
        ),
        ImageAsset(
            id="ast_root",
            root_id="ast_root",
            design_id="dsn_1",
            design_version=1,
            capability="SPEC_RENDER",
            image=SOURCE,
            media_type="image/png",
            created_by="usr_designer",
        ),
        Project(
            root_id="ast_root",
            owner="usr_designer",
            title="Six-prong ring",
            tags=[],
        ),
        ImageRun(
            id="run_side",
            project_root_id="ast_root",
            source_asset_id="ast_root",
            operation="MOUNTING_VIEW_GENERATE",
            normalized_intent={"requested_projections": ["side"]},
            prompt_version="mounting-view.v1",
            source_hash=hashlib.sha256(SOURCE).hexdigest(),
            spec_visual_hash=spec_visual_hash(SPEC),
            status="review_required",
            created_by="usr_designer",
        ),
    ])
    db.commit()


def _candidate():
    return store_markup_warning_candidate(
        run_id="run_side",
        project_root_id="ast_root",
        source_asset_id="ast_root",
        expected_active_asset_id="ast_root",
        expected_design_version=1,
        image_bytes=CANDIDATE,
        media_type="image/png",
        operation="MOUNTING_VIEW_GENERATE",
        asset_capability="FACTORY_REVIEW_MOUNTING_VIEW",
        requested_change="Generate one design-specific side mounting view.",
        region_description="isolated side mounting view",
        drift=None,
        next_spec=None,
        ignored_fields=(),
        qa={"verdict": "warn"},
        routing={"attempt_count": 1},
        created_by="usr_designer",
        promotion_kind="derived_only",
        artifact_metadata=MountingViewArtifactMetadata(
            view="side",
            source_hash=hashlib.sha256(SOURCE).hexdigest(),
            spec_visual_hash=spec_visual_hash(SPEC),
        ),
    )


def test_accepting_mounting_view_creates_only_reviewed_derived_artifact():
    clear_warning_candidates_for_tests()
    with _session() as db:
        _seed(db)
        accepted = accept_warning_revision(
            db,
            _candidate(),
            expected_design_version=1,
            created_by="usr_designer",
        )

        asset = db.get(ImageAsset, accepted.asset_id)
        assert asset is not None
        assert asset.parent_asset_id == "ast_root"
        assert asset.design_version == 1
        assert asset.capability == "FACTORY_REVIEW_MOUNTING_VIEW"
        assert is_primary_revision(asset) is False
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 1
        assert len([
            item for item in db.scalars(select(ImageAsset))
            if is_primary_revision(item)
        ]) == 1

        review = db.get(ImageRunReview, accepted.review_id)
        metadata = db.get(DerivedArtifactMetadata, accepted.asset_id)
        assert review is not None and review.accepted_asset_id == asset.id
        assert metadata is not None
        assert metadata.view == "side"
        assert metadata.hidden_geometry_status == (
            "designer_confirmed_visual_proposal"
        )
        assert metadata.authority_scope == "factory_discussion_only"
        assert metadata.production_authority is False
        assert metadata.spec_visual_hash == spec_visual_hash(SPEC)
        assert "Do not measure or manufacture" in metadata.disclaimer

    clear_warning_candidates_for_tests()

"""Read-only compatibility for pre-companion retained Create variations."""

from __future__ import annotations

import hashlib

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from facetta.api.projects import project_detail
from facetta.db import (
    Base,
    DesignFamily,
    ImageAsset,
    ImageAttempt,
    ImageRun,
    Project,
    ProjectRevisionRecord,
    StudioJobRecord,
    utcnow,
)
from facetta.image_agent import ImageOperation


SOURCE_BYTES = b"historical-primary-raster"
COMPARISON_BYTES = b"validated-three-quarter-raster"
REQUIRED_QA_CODES = (
    "requested_presentation_applied",
    "source_design_preserved",
    "visible_components_preserved",
    "local_geometry_preserved",
    "stone_shape_and_cut_family_preserved",
)


@pytest.fixture
def SessionLocal():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False)
    engine.dispose()


def _seed_legacy_branch(
    SessionLocal,
    *,
    branch_bytes: bytes = SOURCE_BYTES,
    branch_owner: str = "usr_designer",
) -> None:
    now = utcnow()
    source_sha256 = hashlib.sha256(SOURCE_BYTES).hexdigest()
    branch_sha256 = hashlib.sha256(branch_bytes).hexdigest()
    comparison_sha256 = hashlib.sha256(COMPARISON_BYTES).hexdigest()
    checks = [
        {
            "code": code,
            "passed": True,
            "severity": "hard",
            "message": code,
            "evidence": {},
        }
        for code in REQUIRED_QA_CODES
    ]

    with SessionLocal() as db:
        db.add(DesignFamily(
            id="fam_shared",
            owner="usr_designer",
            title="Three stone ring",
            tags=[],
            created_at=now,
            updated_at=now,
        ))
        db.add_all([
            ImageAsset(
                id="ast_source",
                root_id="ast_source",
                parent_asset_id=None,
                design_id=None,
                design_version=None,
                capability="CREATIVE_RENDER",
                image=SOURCE_BYTES,
                media_type="image/png",
                created_by="usr_designer",
                created_at=now,
            ),
            ImageAsset(
                id="ast_source_three_quarter",
                root_id="ast_source",
                parent_asset_id="ast_source",
                design_id=None,
                design_version=None,
                capability="CREATIVE_COMPARISON_THREE_QUARTER",
                image=COMPARISON_BYTES,
                media_type="image/png",
                created_by="usr_designer",
                created_at=now,
            ),
            ImageAsset(
                id="ast_legacy_branch",
                root_id="ast_legacy_branch",
                parent_asset_id=None,
                design_id=None,
                design_version=None,
                capability="VARIATION_BRANCH",
                image=branch_bytes,
                media_type="image/png",
                created_by=branch_owner,
                created_at=now,
            ),
        ])
        db.flush()
        db.add_all([
            Project(
                root_id="ast_source",
                owner="usr_designer",
                collection=None,
                title="Three stone ring",
                tags=[],
                family_id="fam_shared",
                variation_index=1,
                variation_label="Original",
                selected_candidate_asset_id="ast_source",
                created_at=now,
                updated_at=now,
            ),
            Project(
                root_id="ast_legacy_branch",
                owner=branch_owner,
                collection=None,
                title="Three stone ring",
                tags=[],
                family_id="fam_shared",
                variation_index=2,
                variation_label="Direction 2",
                selected_candidate_asset_id="ast_legacy_branch",
                branched_from_project_root_id="ast_source",
                branched_from_asset_id="ast_source",
                created_at=now,
                updated_at=now,
            ),
            ImageRun(
                id="run_comparison",
                project_root_id="ast_source",
                source_asset_id="ast_source",
                operation=ImageOperation.REFERENCE_RENDER.value,
                normalized_intent={},
                prompt_version="creative-comparison-v1",
                input_hash="a" * 64,
                source_hash=source_sha256,
                variant=0,
                status="review_required",
                accepted_asset_id=None,
                created_by="usr_designer",
                created_at=now,
            ),
            StudioJobRecord(
                id="job_create",
                owner="usr_designer",
                action_id="create",
                lane="fast_visual",
                status="succeeded",
                progress=1.0,
                active_design_id="ast_source",
                source_revision_id=None,
                requested_outputs=1,
                credits_per_output=15,
                completed_outputs=1,
                charged_outputs=1,
                created_at=now,
                updated_at=now,
            ),
        ])
        db.flush()
        db.add_all([
            ImageAttempt(
                id="iat_comparison",
                run_id="run_comparison",
                attempt_number=1,
                provider="test",
                model="test-image",
                qa_verdict="warn",
                qa_checks=checks,
                output_hash=comparison_sha256,
                usage={},
                error_category=None,
                created_at=now,
            ),
            ProjectRevisionRecord(
                id="prr_legacy_branch",
                asset_id="ast_legacy_branch",
                action="created",
                raw_intent={
                    "kind": "save_as_variation",
                    "source_project_id": "ast_source",
                    "source_asset_id": "ast_source",
                    "label": "Direction 2",
                },
                interpretation={
                    "operation": "fork_variation",
                    "source_preserved_exactly": True,
                    "independent_revision_history": True,
                    "source_asset_id": "ast_source",
                    "source_sha256": source_sha256,
                    "output_sha256": branch_sha256,
                },
                change_summary="Saved as an independent variation.",
                created_by=branch_owner,
                created_at=now,
            ),
        ])
        db.commit()


def _branch_views(SessionLocal) -> list[dict[str, object]]:
    with SessionLocal() as db:
        project = db.get(Project, "ast_legacy_branch")
        assert project is not None
        detail = project_detail(db, project)
        return detail["active_revision"].get("views", [])


def test_identical_legacy_branch_reads_validated_source_companion(
    SessionLocal,
) -> None:
    _seed_legacy_branch(SessionLocal)
    views = _branch_views(SessionLocal)
    assert [view["view"] for view in views] == ["primary", "three_quarter"]
    assert views[0]["asset_id"] == "ast_legacy_branch"
    assert views[1]["asset_id"] == "ast_source_three_quarter"


def test_legacy_branch_compatibility_does_not_mutate_lineage_jobs_or_charges(
    SessionLocal,
) -> None:
    _seed_legacy_branch(SessionLocal)
    with SessionLocal() as db:
        project = db.get(Project, "ast_legacy_branch")
        assert project is not None
        before = {
            "assets": db.scalar(select(func.count()).select_from(ImageAsset)),
            "runs": db.scalar(select(func.count()).select_from(ImageRun)),
            "attempts": db.scalar(select(func.count()).select_from(ImageAttempt)),
            "revisions": db.scalar(
                select(func.count()).select_from(ProjectRevisionRecord)
            ),
            "jobs": db.scalar(select(func.count()).select_from(StudioJobRecord)),
            "charged": db.scalar(
                select(func.sum(StudioJobRecord.charged_outputs))
            ),
        }
        detail = project_detail(db, project)
        assert detail["active_revision"]["views"]
        after = {
            "assets": db.scalar(select(func.count()).select_from(ImageAsset)),
            "runs": db.scalar(select(func.count()).select_from(ImageRun)),
            "attempts": db.scalar(select(func.count()).select_from(ImageAttempt)),
            "revisions": db.scalar(
                select(func.count()).select_from(ProjectRevisionRecord)
            ),
            "jobs": db.scalar(select(func.count()).select_from(StudioJobRecord)),
            "charged": db.scalar(
                select(func.sum(StudioJobRecord.charged_outputs))
            ),
        }

        assert before == after
        assert not db.new and not db.dirty and not db.deleted


def test_legacy_branch_comparison_fails_closed_on_primary_hash_mismatch(
    SessionLocal,
) -> None:
    _seed_legacy_branch(SessionLocal, branch_bytes=b"different-primary-raster")
    assert _branch_views(SessionLocal) == []


def test_legacy_branch_comparison_fails_closed_across_owner_boundary(
    SessionLocal,
) -> None:
    _seed_legacy_branch(SessionLocal, branch_owner="usr_other")
    assert _branch_views(SessionLocal) == []

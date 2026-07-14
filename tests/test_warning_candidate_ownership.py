"""Ownership boundary for compatibility-only warning acceptance.

The generic warning route is deprecated, but it remains public while historical
clients migrate to durable Studio candidates.  Opaque candidate IDs therefore
cannot be treated as authority: creator, project, and run ownership must all be
verified before idempotent replay or any canonical write.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

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
    ProjectRevisionRecord,
    get_db,
    utcnow,
)
from facetta.image_identity import spec_visual_hash
from facetta.main import app
from facetta.spec import Spec
from facetta.trusted_revision import (
    WarningRevisionError,
    accept_warning_revision,
)
from facetta.warning_candidates import (
    MarkupWarningCandidate,
    MountingViewArtifactMetadata,
    clear_warning_candidates_for_tests,
    get_markup_warning_candidate,
    store_markup_warning_candidate,
)


OWNER_TOKEN = "warning-owner-session-token"
FOREIGN_TOKEN = "warning-foreign-session-token"
OWNER = "usr_warning_owner"
FOREIGN = "usr_warning_foreign"
ROOT_ID = "ast_warning_owner_root"
DESIGN_ID = "dsn_warning_owner"


def _png(color: tuple[int, int, int]) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), color).save(buffer, format="PNG")
    return buffer.getvalue()


SOURCE_IMAGE = _png((184, 177, 169))
CANDIDATE_IMAGE = _png((102, 96, 90))


@pytest.fixture()
def warning_owner_api(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    now = utcnow()
    raw_spec = copy.deepcopy(HALO_SPEC)
    raw_spec.update({
        "design_id": DESIGN_ID,
        "version": 1,
        "created_by": OWNER,
        "created_at": now.isoformat(),
    })
    spec = Spec.model_validate(raw_spec)
    with sessions() as db:
        db.add_all([
            Design(id=DESIGN_ID, created_by=OWNER, created_at=now),
            DesignVersion(
                design_id=DESIGN_ID,
                version=1,
                spec=spec.model_dump(mode="json"),
                created_by=OWNER,
                created_at=now,
            ),
            ImageAsset(
                id=ROOT_ID,
                root_id=ROOT_ID,
                parent_asset_id=None,
                design_id=DESIGN_ID,
                design_version=1,
                capability="SPEC_RENDER",
                image=SOURCE_IMAGE,
                media_type="image/png",
                created_by=OWNER,
                created_at=now,
            ),
            Project(
                root_id=ROOT_ID,
                owner=OWNER,
                title="Private warning review",
                tags=[],
                selected_candidate_asset_id=ROOT_ID,
                created_at=now,
                updated_at=now,
            ),
        ])
        db.commit()

    def override_db() -> Iterator[Session]:
        with sessions() as db:
            yield db

    clear_warning_candidates_for_tests()
    monkeypatch.setenv("FACETTA_AUTH_MODE", "opaque")
    monkeypatch.setenv("FACETTA_AUTH_PRINCIPALS_JSON", json.dumps({
        OWNER_TOKEN: OWNER,
        FOREIGN_TOKEN: FOREIGN,
    }))
    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            yield client, sessions
    finally:
        clear_warning_candidates_for_tests()
        app.dependency_overrides.clear()


def _store_candidate(
    sessions: sessionmaker[Session],
    promotion_kind: str,
) -> MarkupWarningCandidate:
    run_id = f"run_warning_{promotion_kind}"
    operation = (
        "MOUNTING_VIEW_GENERATE"
        if promotion_kind == "derived_only"
        else "LOCALIZED_EDIT"
    )
    source_hash = hashlib.sha256(SOURCE_IMAGE).hexdigest()
    with sessions() as db:
        spec_row = db.get(DesignVersion, (DESIGN_ID, 1))
        assert spec_row is not None
        visual_hash = spec_visual_hash(Spec.model_validate(spec_row.spec))
        db.add(ImageRun(
            id=run_id,
            project_root_id=ROOT_ID,
            source_asset_id=ROOT_ID,
            operation=operation,
            normalized_intent={},
            prompt_version="warning-owner.v1",
            input_hash="a" * 64,
            source_hash=source_hash,
            spec_visual_hash=visual_hash,
            source_spec_visual_hash=visual_hash,
            variant=0,
            status="review_required",
            created_by=OWNER,
        ))
        db.commit()

    metadata = None
    capability = "LOCALIZED_EDIT"
    if promotion_kind == "derived_only":
        capability = "FACTORY_REVIEW_MOUNTING_VIEW"
        metadata = MountingViewArtifactMetadata(
            view="front",
            source_hash=source_hash,
            spec_visual_hash=visual_hash,
        )
    return store_markup_warning_candidate(
        run_id=run_id,
        project_root_id=ROOT_ID,
        source_asset_id=ROOT_ID,
        expected_active_asset_id=ROOT_ID,
        expected_design_version=1,
        image_bytes=CANDIDATE_IMAGE,
        media_type="image/png",
        operation=operation,
        asset_capability=capability,
        requested_change="Review this private candidate.",
        region_description="designer-marked region",
        drift=None,
        next_spec=None,
        ignored_fields=(),
        qa={"verdict": "warn"},
        routing={"attempt_count": 1},
        created_by=OWNER,
        promotion_kind=promotion_kind,  # type: ignore[arg-type]
        artifact_metadata=metadata,
    )


def _canonical_snapshot(sessions: sessionmaker[Session]) -> tuple[object, ...]:
    with sessions() as db:
        project = db.get(Project, ROOT_ID)
        root = db.get(ImageAsset, ROOT_ID)
        assert project is not None and root is not None
        return (
            db.scalar(select(func.count()).select_from(ImageAsset)),
            db.scalar(select(func.count()).select_from(DesignVersion)),
            db.scalar(select(func.count()).select_from(ImageRunReview)),
            db.scalar(select(func.count()).select_from(DerivedArtifactMetadata)),
            db.scalar(select(func.count()).select_from(ProjectRevisionRecord)),
            project.selected_candidate_asset_id,
            project.updated_at,
            bytes(root.image),
            root.design_version,
        )


@pytest.mark.parametrize("promotion_kind", ["standard", "derived_only"])
def test_foreign_principal_cannot_accept_process_local_warning_candidate(
    warning_owner_api: tuple[TestClient, sessionmaker[Session]],
    promotion_kind: str,
) -> None:
    client, sessions = warning_owner_api
    candidate = _store_candidate(sessions, promotion_kind)
    before = _canonical_snapshot(sessions)

    response = client.post(
        f"/image-runs/{candidate.run_id}/candidates/"
        f"{candidate.candidate_id}/accept",
        headers={"Authorization": f"Bearer {FOREIGN_TOKEN}"},
        json={"expected_design_version": 1, "created_by": FOREIGN},
    )

    assert response.status_code == 403
    assert response.json() == {
        "detail": {
            "code": "image_run_access_denied",
            "error_category": "authorization",
            "detail": "the principal does not own this image-run evidence",
        },
    }
    assert _canonical_snapshot(sessions) == before
    assert get_markup_warning_candidate(
        candidate.run_id, candidate.candidate_id,
    ) is candidate

    # Defense in depth: internal callers cannot bypass the public image-run
    # authorization boundary and replay or append another owner's candidate.
    with sessions() as db:
        with pytest.raises(WarningRevisionError) as rejected:
            accept_warning_revision(
                db,
                candidate,
                expected_design_version=1,
                created_by=FOREIGN,
            )
        assert rejected.value.status_code == 404
        assert rejected.value.code == "warning_candidate_unavailable"
        db.rollback()
    assert _canonical_snapshot(sessions) == before

"""Studio pre-spec previews stay temporary until explicit review."""

from __future__ import annotations

import base64
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from facetta.api.studio import get_studio_visual_preview_generator
from facetta.db import (
    Base,
    Design,
    DesignVersion,
    ImageAsset,
    ImageRun,
    ImageRunReview,
    Project,
    ProjectRevisionRecord,
    get_db,
)
from facetta.image_agent import (
    ImageOperation,
    ImageQualityReport,
    JewelryImageAgent,
    ProviderImage,
    QualityVerdict,
    build_image_plan,
)
from facetta.main import app
from facetta.studio_visual_candidates import (
    clear_studio_visual_candidates_for_tests,
)


def _png(color: tuple[int, int, int]) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (48, 48), color).save(output, format="PNG")
    return output.getvalue()


SOURCE = _png((230, 225, 215))
CANDIDATE = _png((185, 150, 105))


@pytest.fixture
def studio_preview_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)

    def override_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    clear_studio_visual_candidates_for_tests()
    app.dependency_overrides[get_db] = override_db
    try:
        with Session() as db:
            root = ImageAsset(
                id="ast_selected",
                root_id="ast_selected",
                parent_asset_id=None,
                design_id=None,
                design_version=None,
                capability="CREATIVE_RENDER",
                instruction="Initial direction",
                image=SOURCE,
                media_type="image/png",
                created_by="usr_studio",
            )
            project = Project(
                root_id=root.id,
                owner="usr_studio",
                title="Pre-spec ring direction",
                tags=[],
                selected_candidate_asset_id=root.id,
            )
            db.add_all([root, project])
            db.commit()
        yield TestClient(app), Session
    finally:
        app.dependency_overrides.clear()
        clear_studio_visual_candidates_for_tests()


def _generator(calls: list[dict]):
    def generate(source, instruction, scope, mask, variant):
        calls.append({
            "source": source,
            "instruction": instruction,
            "scope": scope,
            "mask": mask,
            "variant": variant,
        })
        plan = build_image_plan(
            ImageOperation.REFERENCE_RENDER,
            instruction,
            source_image=source,
            mask_bytes=mask,
            mask_provenance=("test_markup" if mask is not None else None),
            variant=variant,
        )

        class Provider:
            def execute(self, *_args, **_kwargs):
                return ProviderImage(image_bytes=CANDIDATE)

        class Evaluator:
            def evaluate(self, *_args, **_kwargs):
                return ImageQualityReport(
                    verdict=QualityVerdict.PASS,
                    checks=(),
                    score=96,
                )

        return JewelryImageAgent(Provider(), Evaluator()).run(
            plan, source_image=source, mask_bytes=mask)

    return generate


def _preview(client: TestClient, **overrides):
    payload = {
        "created_by": "usr_studio",
        "expected_active_asset_id": "ast_selected",
        "instruction": "Give the visible metal a warmer rose-gold appearance",
        "scope": "appearance",
        "variant": 2,
    }
    payload.update(overrides)
    return client.post(
        "/studio/projects/ast_selected/visual-previews", json=payload)


def _counts(Session) -> dict[str, int]:
    with Session() as db:
        return {
            "assets": db.scalar(select(func.count()).select_from(ImageAsset)),
            "designs": db.scalar(select(func.count()).select_from(Design)),
            "versions": db.scalar(select(func.count()).select_from(DesignVersion)),
            "runs": db.scalar(select(func.count()).select_from(ImageRun)),
            "reviews": db.scalar(select(func.count()).select_from(ImageRunReview)),
            "records": db.scalar(
                select(func.count()).select_from(ProjectRevisionRecord)),
        }


def test_preview_does_not_mutate_canonical_history_and_apply_is_atomic(
    studio_preview_client,
):
    client, Session = studio_preview_client
    calls: list[dict] = []
    app.dependency_overrides[get_studio_visual_preview_generator] = (
        lambda: _generator(calls)
    )
    before = _counts(Session)

    preview = _preview(client)
    assert preview.status_code == 201, preview.text
    body = preview.json()
    assert body["source_asset_id"] == "ast_selected"
    assert body["candidate"]["verdict"] == "pass"
    assert len(calls) == 1
    after_preview = _counts(Session)
    assert after_preview == {**before, "runs": 1}
    image = client.get(body["candidate"]["preview_url"])
    assert image.status_code == 200
    assert image.content == CANDIDATE
    assert image.headers["cache-control"] == "private, no-store"

    accepted = client.post(
        f"/studio/image-runs/{body['image_run_id']}/visual-candidates/"
        f"{body['candidate']['candidate_id']}/accept",
        json={
            "created_by": "usr_studio",
            "expected_active_asset_id": "ast_selected",
        },
    )
    assert accepted.status_code == 201, accepted.text
    applied = accepted.json()
    assert applied["design_version"] is None
    assert applied["project"]["selected_candidate_asset_id"] == applied["new_asset_id"]
    assert applied["project"]["active_asset_id"] == applied["new_asset_id"]
    assert len(calls) == 1  # Apply never reruns the provider.

    with Session() as db:
        child = db.get(ImageAsset, applied["new_asset_id"])
        assert child is not None
        assert child.parent_asset_id == "ast_selected"
        assert child.capability == "CREATIVE_RENDER"
        assert child.design_id is None
        assert child.design_version is None
        assert bytes(child.image) == CANDIDATE
        project = db.get(Project, "ast_selected")
        assert project is not None
        assert project.selected_candidate_asset_id == child.id
        review = db.scalar(select(ImageRunReview))
        assert review is not None
        assert review.decision == "accepted"
        assert review.accepted_asset_id == child.id
        record = db.scalar(select(ProjectRevisionRecord))
        assert record is not None
        assert record.asset_id == child.id
        assert record.interpretation["specification_created"] is False
        assert record.interpretation["factory_authority"] is False
        assert db.scalar(select(func.count()).select_from(Design)) == 0
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 0

    assert client.get(body["candidate"]["preview_url"]).status_code == 410


def test_discard_is_terminal_and_creates_no_canonical_revision(
    studio_preview_client,
):
    client, Session = studio_preview_client
    app.dependency_overrides[get_studio_visual_preview_generator] = (
        lambda: _generator([])
    )
    preview = _preview(client).json()
    candidate_id = preview["candidate"]["candidate_id"]
    run_id = preview["image_run_id"]
    discarded = client.post(
        f"/studio/image-runs/{run_id}/visual-candidates/{candidate_id}/discard",
        json={
            "created_by": "usr_studio",
            "expected_active_asset_id": "ast_selected",
        },
    )
    assert discarded.status_code == 200, discarded.text
    assert discarded.json()["status"] == "discarded"
    assert _counts(Session) == {
        "assets": 1,
        "designs": 0,
        "versions": 0,
        "runs": 1,
        "reviews": 1,
        "records": 0,
    }
    assert client.post(
        f"/studio/image-runs/{run_id}/visual-candidates/{candidate_id}/accept",
        json={
            "created_by": "usr_studio",
            "expected_active_asset_id": "ast_selected",
        },
    ).status_code == 410


def test_apply_rejects_stale_selected_visual_and_source_hash(
    studio_preview_client,
):
    client, Session = studio_preview_client
    app.dependency_overrides[get_studio_visual_preview_generator] = (
        lambda: _generator([])
    )
    first = _preview(client).json()
    with Session() as db:
        sibling = ImageAsset(
            id="ast_other",
            root_id="ast_selected",
            parent_asset_id="ast_selected",
            design_version=None,
            capability="CREATIVE_RENDER",
            image=_png((100, 100, 100)),
            media_type="image/png",
            created_by="usr_studio",
        )
        db.add(sibling)
        db.get(Project, "ast_selected").selected_candidate_asset_id = sibling.id
        db.commit()
    stale = client.post(
        f"/studio/image-runs/{first['image_run_id']}/visual-candidates/"
        f"{first['candidate']['candidate_id']}/accept",
        json={
            "created_by": "usr_studio",
            "expected_active_asset_id": "ast_selected",
        },
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "stale_asset_revision"

    with Session() as db:
        db.get(Project, "ast_selected").selected_candidate_asset_id = "ast_selected"
        db.get(ImageAsset, "ast_selected").image = _png((1, 2, 3))
        db.commit()
    tampered = client.post(
        f"/studio/image-runs/{first['image_run_id']}/visual-candidates/"
        f"{first['candidate']['candidate_id']}/accept",
        json={
            "created_by": "usr_studio",
            "expected_active_asset_id": "ast_selected",
        },
    )
    assert tampered.status_code == 422
    assert tampered.json()["code"] == "visual_preview_source_hash_mismatch"


def test_structural_scope_is_rejected_before_generation(studio_preview_client):
    client, _Session = studio_preview_client
    calls: list[dict] = []
    app.dependency_overrides[get_studio_visual_preview_generator] = (
        lambda: _generator(calls)
    )
    response = _preview(
        client,
        scope="structural",
        instruction="Make the shank thinner and add two prongs",
    )
    assert response.status_code == 422
    assert calls == []


def test_owner_and_durable_run_lineage_fail_closed(studio_preview_client):
    client, Session = studio_preview_client
    calls: list[dict] = []
    app.dependency_overrides[get_studio_visual_preview_generator] = (
        lambda: _generator(calls)
    )
    denied = _preview(client, created_by="usr_intruder")
    assert denied.status_code == 404
    assert calls == []

    preview = _preview(client).json()
    with Session() as db:
        run = db.get(ImageRun, preview["image_run_id"])
        assert run is not None
        run.project_root_id = "ast_different_project"
        db.commit()
    rejected = client.post(
        f"/studio/image-runs/{preview['image_run_id']}/visual-candidates/"
        f"{preview['candidate']['candidate_id']}/accept",
        json={
            "created_by": "usr_studio",
            "expected_active_asset_id": "ast_selected",
        },
    )
    assert rejected.status_code == 422
    assert rejected.json()["code"] == "visual_preview_run_mismatch"
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 1
        assert db.scalar(select(func.count()).select_from(ImageRunReview)) == 0
        assert db.scalar(select(func.count()).select_from(ProjectRevisionRecord)) == 0


def test_marked_region_uses_exact_saved_markup_parent(studio_preview_client):
    client, Session = studio_preview_client
    calls: list[dict] = []
    app.dependency_overrides[get_studio_visual_preview_generator] = (
        lambda: _generator(calls)
    )
    marked = Image.open(io.BytesIO(SOURCE)).convert("RGB")
    draw = ImageDraw.Draw(marked)
    draw.rectangle((10, 10, 20, 20), outline=(255, 0, 0), width=3)
    output = io.BytesIO()
    marked.save(output, format="PNG")
    with Session() as db:
        db.add(ImageAsset(
            id="ast_markup",
            root_id="ast_selected",
            parent_asset_id="ast_selected",
            design_version=None,
            capability="MARKUP_NOTES",
            image=output.getvalue(),
            media_type="image/png",
            created_by="usr_studio",
        ))
        db.commit()

    response = _preview(
        client,
        scope="marked_region",
        markup_asset_id="ast_markup",
        instruction="Warm only the highlighted metal surface",
    )
    assert response.status_code == 201, response.text
    assert calls[0]["mask"] is not None
    assert calls[0]["scope"] == "marked_region"


def test_marked_region_rejects_markup_from_another_actor(studio_preview_client):
    client, Session = studio_preview_client
    calls: list[dict] = []
    app.dependency_overrides[get_studio_visual_preview_generator] = (
        lambda: _generator(calls)
    )
    with Session() as db:
        db.add(ImageAsset(
            id="ast_intruder_markup",
            root_id="ast_selected",
            parent_asset_id="ast_selected",
            design_version=None,
            capability="MARKUP_NOTES",
            image=SOURCE,
            media_type="image/png",
            created_by="usr_intruder",
        ))
        db.commit()

    response = _preview(
        client,
        scope="marked_region",
        markup_asset_id="ast_intruder_markup",
        instruction="Warm only the highlighted metal surface",
    )
    assert response.status_code == 422
    assert response.json()["code"] == "visual_preview_markup_invalid"
    assert calls == []

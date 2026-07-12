"""Pre-spec Client and Marketing outputs remain derived, review-only images."""

from __future__ import annotations

import hashlib
import io
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from facetta.api.studio import get_pre_spec_presentation_generator
from facetta.db import (
    ApprovalChecklist,
    Base,
    Design,
    DesignVersion,
    ImageAsset,
    ImageRun,
    ImageRunReview,
    Project,
    ProjectRevisionRecord,
    StudioJobRecord,
    StudioPresentationCandidateRecord,
    get_db,
    utcnow,
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
from facetta.studio_jobs import StudioJobAccountingError
from facetta.studio_presentation_candidates import (
    clear_studio_presentation_candidates_for_tests,
)
import facetta.studio_presentation_candidates as presentation_candidates


def _png(color: tuple[int, int, int]) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (48, 48), color).save(output, format="PNG")
    return output.getvalue()


SOURCE = _png((220, 215, 205))
CLIENT = _png((235, 230, 220))
MARKETING = _png((40, 38, 44))
SOURCE_HASH = hashlib.sha256(SOURCE).hexdigest()


@pytest.fixture
def presentation_client():
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

    clear_studio_presentation_candidates_for_tests()
    app.dependency_overrides[get_db] = override_db
    try:
        with Session() as db:
            source = ImageAsset(
                id="ast_direction",
                root_id="ast_direction",
                parent_asset_id=None,
                design_id=None,
                design_version=None,
                capability="CREATIVE_RENDER",
                instruction="Selected direction",
                image=SOURCE,
                media_type="image/png",
                created_by="usr_studio",
            )
            db.add_all([source, Project(
                root_id=source.id,
                owner="usr_studio",
                title="Selected pre-spec direction",
                tags=[],
                selected_candidate_asset_id=source.id,
            )])
            db.commit()
        yield TestClient(app), Session
    finally:
        app.dependency_overrides.clear()
        clear_studio_presentation_candidates_for_tests()


def _generator(calls: list[dict]):
    def generate(source, intent, constraints, expected_output, variant):
        calls.append({
            "source": source,
            "intent": intent,
            "constraints": constraints,
            "expected_output": expected_output,
            "variant": variant,
        })
        plan = build_image_plan(
            ImageOperation.REFERENCE_RENDER,
            intent,
            source_image=source,
            frozen=("exact visible jewelry",),
            style_constraints=constraints,
            expected_output=expected_output,
            variant=variant,
        )

        class Provider:
            def execute(self, *_args, **_kwargs):
                image = MARKETING if "marketing" in expected_output else CLIENT
                return ProviderImage(image_bytes=image)

        class Evaluator:
            def evaluate(self, *_args, **_kwargs):
                return ImageQualityReport(
                    verdict=QualityVerdict.PASS,
                    checks=(),
                    score=97,
                )

        return JewelryImageAgent(Provider(), Evaluator()).run(
            plan, source_image=source,
        )

    return generate


def _preview(client: TestClient, **overrides):
    payload = {
        "created_by": "usr_studio",
        "expected_active_asset_id": "ast_direction",
        "destination": "client",
        "client_format": "beauty",
        "preset": "luxury_studio",
        "framing": "portrait",
        "custom_instruction": "Soft daylight and generous negative space",
        "variant": 3,
    }
    payload.update(overrides)
    if "studio_job_id" not in payload:
        payload["studio_job_id"] = _presentation_job(client)["job_id"]
    return client.post(
        "/studio/projects/ast_direction/presentation-previews",
        json=payload,
    )


def _presentation_job(client: TestClient):
    response = client.post("/studio/jobs", json={
        "owner": "usr_studio",
        "action_id": "present",
        "lane": "fast_visual",
        "active_design_id": "ast_direction",
        "source_revision_id": "ast_direction",
        "requested_outputs": 1,
        "credits_per_output": 18,
    })
    assert response.status_code == 201, response.text
    created = response.json()
    running = client.patch(f"/studio/jobs/{created['job_id']}", json={
        "owner": "usr_studio",
        "status": "running",
        "progress": 0.1,
    })
    assert running.status_code == 200, running.text
    return running.json()


def _decision(client: TestClient, body: dict, action: str, **overrides):
    payload = {
        "created_by": "usr_studio",
        "expected_active_asset_id": "ast_direction",
        "expected_source_sha256": body["source_sha256"],
    }
    payload.update(overrides)
    candidate = body["candidate"]
    return client.post(
        f"/studio/image-runs/{candidate['image_run_id']}/"
        f"presentation-candidates/{candidate['candidate_id']}/{action}",
        json=payload,
    )


def test_client_beauty_preview_save_preserves_pre_spec_authority(
    presentation_client,
):
    client, Session = presentation_client
    calls: list[dict] = []
    app.dependency_overrides[get_pre_spec_presentation_generator] = (
        lambda: _generator(calls)
    )

    preview = _preview(client)
    assert preview.status_code == 201, preview.text
    body = preview.json()
    assert body["status"] == "review_required"
    assert body["source_sha256"] == SOURCE_HASH
    assert body["design_version"] is None
    assert body["destination"] == "client"
    assert body["candidate"]["capability"] == "CLIENT_BEAUTY_RENDER"
    assert len(calls) == 1
    assert "client-review" in calls[0]["expected_output"]
    candidate_image = client.get(body["candidate"]["preview_url"])
    assert candidate_image.content == CLIENT
    assert candidate_image.headers["cache-control"] == "private, no-store"

    saved = _decision(client, body, "accept")
    assert saved.status_code == 201, saved.text
    accepted = saved.json()
    assert accepted["design_version"] is None
    assert accepted["source_sha256"] == SOURCE_HASH
    assert accepted["project"]["active_asset_id"] == "ast_direction"
    assert accepted["project"]["selected_candidate_asset_id"] == "ast_direction"
    assert accepted["project"]["design_id"] is None
    assert accepted["project"]["factory_ready"] is False
    assert len(calls) == 1  # Save never reruns generation.

    with Session() as db:
        derived = db.get(ImageAsset, accepted["asset_id"])
        assert derived is not None
        assert derived.parent_asset_id == "ast_direction"
        assert derived.capability == "CLIENT_BEAUTY_RENDER"
        assert derived.design_id is None
        assert derived.design_version is None
        assert bytes(derived.image) == CLIENT
        assert db.scalar(select(func.count()).select_from(Design)) == 0
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 0
        assert db.scalar(select(func.count()).select_from(ApprovalChecklist)) == 0
        assert db.scalar(select(func.count()).select_from(ProjectRevisionRecord)) == 0
        review = db.scalar(select(ImageRunReview))
        assert review is not None
        assert review.decision == "accepted"
        assert review.accepted_asset_id == derived.id


def test_selectable_marketing_preview_discard_is_terminal_and_free_of_assets(
    presentation_client,
):
    client, Session = presentation_client
    calls: list[dict] = []
    app.dependency_overrides[get_pre_spec_presentation_generator] = (
        lambda: _generator(calls)
    )
    preview = _preview(
        client,
        destination="marketing",
        client_format="product",
        preset="dark_editorial",
        framing="square",
        variant=9,
    )
    assert preview.status_code == 201, preview.text
    body = preview.json()
    assert body["candidate"]["capability"] == "MARKETING_IMAGE"
    assert body["candidate"]["preset"] == "dark_editorial"
    assert calls[0]["variant"] == 9
    assert "marketing image" in calls[0]["expected_output"]

    stale_hash = _decision(
        client, body, "discard", expected_source_sha256="0" * 64,
    )
    assert stale_hash.status_code == 409
    assert stale_hash.json()["code"] == "stale_asset_revision"

    discarded = _decision(client, body, "discard")
    assert discarded.status_code == 200, discarded.text
    assert discarded.json()["design_version"] is None
    assert client.get(body["candidate"]["preview_url"]).status_code == 410
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 1
        assert db.scalar(select(func.count()).select_from(Design)) == 0
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 0
        review = db.scalar(select(ImageRunReview))
        assert review is not None and review.decision == "rejected"


def test_pre_spec_presentation_rejects_redesign_and_stale_selected_visual(
    presentation_client,
):
    client, Session = presentation_client
    app.dependency_overrides[get_pre_spec_presentation_generator] = (
        lambda: _generator([])
    )
    redesign = _preview(
        client,
        custom_instruction="Replace the center stone and widen the band",
    )
    assert redesign.status_code == 422
    assert redesign.json()["code"] == "presentation_scope_violation"

    preview = _preview(client).json()
    with Session() as db:
        source = db.get(ImageAsset, "ast_direction")
        assert source is not None
        child = ImageAsset(
            id="ast_new_direction",
            root_id=source.root_id,
            parent_asset_id=source.id,
            design_id=None,
            design_version=None,
            capability="CREATIVE_RENDER",
            instruction="New selected direction",
            image=_png((100, 100, 100)),
            media_type="image/png",
            created_by="usr_studio",
        )
        project = db.get(Project, source.root_id)
        assert project is not None
        project.selected_candidate_asset_id = child.id
        db.add(child)
        db.commit()

    stale = _decision(client, preview, "accept")
    assert stale.status_code == 409
    assert stale.json()["code"] == "stale_asset_revision"
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(Design)) == 0
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 0
        assert db.scalar(select(func.count()).select_from(ImageRunReview)) == 0


def test_pre_spec_lineage_mismatch_persists_failed_run_evidence(
    presentation_client,
):
    client, Session = presentation_client

    def wrong_source_generator(_source, intent, constraints, expected_output, variant):
        wrong_source = _png((12, 34, 56))
        plan = build_image_plan(
            ImageOperation.REFERENCE_RENDER,
            intent,
            source_image=wrong_source,
            frozen=("exact visible jewelry",),
            style_constraints=constraints,
            expected_output=expected_output,
            variant=variant,
        )

        class Provider:
            def execute(self, *_args, **_kwargs):
                return ProviderImage(image_bytes=CLIENT)

        class Evaluator:
            def evaluate(self, *_args, **_kwargs):
                return ImageQualityReport(
                    verdict=QualityVerdict.PASS,
                    checks=(),
                    score=97,
                )

        return JewelryImageAgent(Provider(), Evaluator()).run(
            plan, source_image=wrong_source,
        )

    app.dependency_overrides[get_pre_spec_presentation_generator] = (
        lambda: wrong_source_generator
    )
    response = _preview(client)
    assert response.status_code == 500, response.text
    assert response.json()["code"] == "presentation_lineage_incomplete"
    with Session() as db:
        run = db.get(ImageRun, response.json()["image_run_id"])
        assert run is not None
        assert run.status == "failed"
        assert run.source_asset_id == "ast_direction"


def test_pre_spec_presentation_owner_is_required_for_preview_and_decision(
    presentation_client,
):
    client, Session = presentation_client
    calls: list[dict] = []
    app.dependency_overrides[get_pre_spec_presentation_generator] = (
        lambda: _generator(calls)
    )
    hidden = _preview(client, created_by="usr_other")
    assert hidden.status_code == 404
    assert calls == []

    body = _preview(client).json()
    foreign_decision = _decision(
        client, body, "accept", created_by="usr_other",
    )
    assert foreign_decision.status_code == 404
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 1
        assert db.scalar(select(func.count()).select_from(Design)) == 0
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 0
        assert db.scalar(select(func.count()).select_from(ImageRunReview)) == 0

    # The creator can still make a terminal decision after a rejected foreign
    # attempt; the candidate and its exact-source hash were not consumed.
    accepted = _decision(client, body, "accept")
    assert accepted.status_code == 201
    assert accepted.json()["project"]["factory_ready"] is False


def test_presentation_job_is_required_and_reserved_before_provider_cost(
    presentation_client,
):
    client, _Session = presentation_client
    calls: list[dict] = []
    app.dependency_overrides[get_pre_spec_presentation_generator] = (
        lambda: _generator(calls)
    )
    base = {
        "created_by": "usr_studio",
        "expected_active_asset_id": "ast_direction",
        "destination": "client",
        "client_format": "product",
        "preset": "catalog_white",
    }
    missing = client.post(
        "/studio/projects/ast_direction/presentation-previews",
        json=base,
    )
    assert missing.status_code == 422
    unknown = client.post(
        "/studio/projects/ast_direction/presentation-previews",
        json={**base, "studio_job_id": "job_unknown"},
    )
    assert unknown.status_code == 404
    assert calls == []

    job = _presentation_job(client)
    first = client.post(
        "/studio/projects/ast_direction/presentation-previews",
        json={**base, "studio_job_id": job["job_id"]},
    )
    assert first.status_code == 201, first.text
    assert len(calls) == 1
    reused = client.post(
        "/studio/projects/ast_direction/presentation-previews",
        json={**base, "studio_job_id": job["job_id"]},
    )
    assert reused.status_code == 409
    assert reused.json()["code"] == "presentation_job_terminal"
    assert len(calls) == 1


def test_presentation_candidate_survives_refresh_and_is_owner_scoped(
    presentation_client,
):
    client, Session = presentation_client
    app.dependency_overrides[get_pre_spec_presentation_generator] = (
        lambda: _generator([])
    )
    body = _preview(client).json()
    candidate_id = body["candidate"]["candidate_id"]

    # The former process-local reset cannot erase durable review work. A new
    # client/session can resume the exact candidate and image bytes.
    clear_studio_presentation_candidates_for_tests()
    with TestClient(app) as restarted:
        resumed = restarted.get(
            "/studio/presentation-candidates",
            params={"owner": "usr_studio", "project_id": "ast_direction"},
        )
        assert resumed.status_code == 200
        assert [item["candidate_id"] for item in resumed.json()["candidates"]] == [
            candidate_id
        ]
        assert restarted.get(
            body["candidate"]["preview_url"]
        ).content == CLIENT
        assert restarted.get(
            body["candidate"]["preview_url"].replace(
                "owner=usr_studio", "owner=usr_other"
            )
        ).status_code == 404
        foreign = restarted.get(
            "/studio/presentation-candidates", params={"owner": "usr_other"}
        )
        assert foreign.json() == {"candidates": []}

    with Session() as db:
        record = db.get(StudioPresentationCandidateRecord, candidate_id)
        assert record is not None
        assert bytes(record.image) == CLIENT
        assert record.source_sha256 == SOURCE_HASH
        assert record.status == "reviewing"


def test_bound_job_is_charged_only_with_atomic_acceptance(
    presentation_client,
):
    client, Session = presentation_client
    app.dependency_overrides[get_pre_spec_presentation_generator] = (
        lambda: _generator([])
    )
    job = _presentation_job(client)
    body = _preview(client, studio_job_id=job["job_id"]).json()

    reviewing = client.get(
        f"/studio/jobs/{job['job_id']}", params={"owner": "usr_studio"}
    ).json()
    assert reviewing["status"] == "reviewing"
    assert reviewing["billing"]["charged_outputs"] == 0

    saved = _decision(client, body, "accept")
    assert saved.status_code == 201, saved.text
    completed = client.get(
        f"/studio/jobs/{job['job_id']}", params={"owner": "usr_studio"}
    ).json()
    assert completed["status"] == "succeeded"
    assert completed["billing"]["completed_outputs"] == 1
    assert completed["billing"]["charged_outputs"] == 1

    # A retry receives the same terminal result and never creates a second
    # asset, review, or charge.
    retried = _decision(client, body, "accept")
    assert retried.status_code == 201
    assert retried.json()["asset_id"] == saved.json()["asset_id"]
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(ImageRunReview)) == 1
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 2
        record = db.get(
            StudioPresentationCandidateRecord,
            body["candidate"]["candidate_id"],
        )
        assert record is not None and record.status == "accepted"
        assert bytes(record.image) == b""


def test_discard_cancels_bound_job_without_charge_and_is_idempotent(
    presentation_client,
):
    client, Session = presentation_client
    app.dependency_overrides[get_pre_spec_presentation_generator] = (
        lambda: _generator([])
    )
    job = _presentation_job(client)
    body = _preview(
        client, destination="marketing", studio_job_id=job["job_id"]
    ).json()
    first = _decision(client, body, "discard")
    second = _decision(client, body, "discard")
    assert first.status_code == second.status_code == 200

    canceled = client.get(
        f"/studio/jobs/{job['job_id']}", params={"owner": "usr_studio"}
    ).json()
    assert canceled["status"] == "canceled"
    assert canceled["billing"]["completed_outputs"] == 0
    assert canceled["billing"]["charged_outputs"] == 0
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(ImageRunReview)) == 1
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 1
        record = db.get(
            StudioPresentationCandidateRecord,
            body["candidate"]["candidate_id"],
        )
        assert record is not None and bytes(record.image) == b""


def test_expired_candidate_becomes_terminal_without_global_eviction(
    presentation_client,
):
    client, Session = presentation_client
    app.dependency_overrides[get_pre_spec_presentation_generator] = (
        lambda: _generator([])
    )
    first = _preview(client).json()
    second = _preview(client, variant=4).json()
    first_id = first["candidate"]["candidate_id"]
    second_id = second["candidate"]["candidate_id"]
    with Session() as db:
        expired = db.get(StudioPresentationCandidateRecord, first_id)
        assert expired is not None
        expired.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()

    gone = client.get(first["candidate"]["preview_url"])
    assert gone.status_code == 410
    resumed = client.get(
        "/studio/presentation-candidates", params={"owner": "usr_studio"}
    ).json()["candidates"]
    assert [item["candidate_id"] for item in resumed] == [second_id]
    with Session() as db:
        expired = db.get(StudioPresentationCandidateRecord, first_id)
        current = db.get(StudioPresentationCandidateRecord, second_id)
        assert expired is not None and expired.status == "expired"
        assert bytes(expired.image) == b""
        assert current is not None and current.status == "reviewing"


def test_job_accounting_failure_rolls_back_asset_review_and_candidate(
    presentation_client,
    monkeypatch,
):
    client, Session = presentation_client
    app.dependency_overrides[get_pre_spec_presentation_generator] = (
        lambda: _generator([])
    )
    job = _presentation_job(client)
    body = _preview(client, studio_job_id=job["job_id"]).json()

    def fail_accounting(*_args, **_kwargs):
        raise StudioJobAccountingError("injected accounting failure")

    monkeypatch.setattr(
        presentation_candidates,
        "record_accepted_studio_job_outputs",
        fail_accounting,
    )
    failed = _decision(client, body, "accept")
    assert failed.status_code == 409
    assert failed.json()["code"] == "presentation_job_resolution_conflict"

    with Session() as db:
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 1
        assert db.scalar(select(func.count()).select_from(ImageRunReview)) == 0
        candidate = db.get(
            StudioPresentationCandidateRecord,
            body["candidate"]["candidate_id"],
        )
        persisted_job = db.get(StudioJobRecord, job["job_id"])
        assert candidate is not None and candidate.status == "reviewing"
        assert candidate.accepted_asset_id is None
        assert persisted_job is not None and persisted_job.status == "reviewing"
        assert persisted_job.charged_outputs == 0

"""Pre-spec visual angles are one durable, atomic, review-only set."""

from __future__ import annotations

import hashlib
import io
import threading
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from facetta.api.studio import (
    generate_visual_angle,
    get_visual_angle_set_generator,
)
from facetta.db import (
    Base,
    ImageAsset,
    ImageRun,
    ImageRunReview,
    Project,
    StudioJobRecord,
    StudioVisualAngleCandidateRecord,
    StudioVisualAngleSetRecord,
    get_db,
    utcnow,
)
from facetta.image_agent import (
    CheckSeverity,
    ImageOperation,
    ImageQualityReport,
    JewelryImageAgent,
    ProviderImage,
    QualityCheck,
    QualityVerdict,
    build_image_plan,
)
from facetta.main import app
from facetta.image_agent.prompts import (
    compile_correction_prompt,
    compile_initial_prompt,
)
from facetta.studio_jobs import StudioJobAccountingError
import facetta.studio_visual_angle_sets as visual_angle_sets


OWNER = "usr_angles"
PROJECT_ID = "ast_selected_direction"


def _png(color: tuple[int, int, int]) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (40, 40), color).save(output, "PNG")
    return output.getvalue()


SOURCE = _png((205, 215, 225))
SOURCE_SHA = hashlib.sha256(SOURCE).hexdigest()
OUTPUTS = {
    "front": _png((220, 80, 90)),
    "three_quarter": _png((80, 220, 100)),
    "side": _png((80, 100, 220)),
}


def test_visual_angle_generator_binds_exact_source_and_explicit_camera_contract(
    monkeypatch,
):
    captured: list[tuple[object, bytes]] = []
    sentinel = object()

    class CapturingAgent:
        def run(self, plan, *, source_image, **_kwargs):
            captured.append((plan, source_image))
            return sentinel

    monkeypatch.setattr(
        "facetta.api.studio.JewelryImageAgent",
        lambda: CapturingAgent(),
    )

    for ordinal, view in enumerate(("front", "three_quarter", "side")):
        assert generate_visual_angle(SOURCE, view, 10 + ordinal) is sentinel

    assert [plan.camera_view for plan, _source in captured] == [
        "front", "three_quarter", "side",
    ]
    assert all(source == SOURCE for _plan, source in captured)
    assert all(plan.source_hash == SOURCE_SHA for plan, _source in captured)
    assert [plan.normalized_intent["requested_projections"]
            for plan, _source in captured] == [
        ["front"], ["three_quarter"], ["side"],
    ]
    assert all(plan.normalized_intent["camera_only"] is True
               for plan, _source in captured)
    prompts = [compile_initial_prompt(plan) for plan, _source in captured]
    assert all("CAMERA-ONLY DERIVATION" in prompt for prompt in prompts)
    assert "straight-on front elevation" in prompts[0]
    assert "three-quarter product perspective" in prompts[1]
    assert "true side profile" in prompts[2]
    assert all("minimum physically coherent continuation" in prompt
               for prompt in prompts)


def test_visual_angle_quality_retry_reanchors_without_expanding_scope():
    plan = build_image_plan(
        ImageOperation.REFERENCE_RENDER,
        "Show the exact selected ring from the side",
        source_image=SOURCE,
        camera_view="side",
    )
    failed = ImageQualityReport(
        verdict=QualityVerdict.FAIL,
        checks=(QualityCheck(
            code="source_design_preserved",
            passed=False,
            severity=CheckSeverity.HARD,
            message="candidate changed the selected setting",
        ),),
        score=12,
    )

    corrected, instruction = compile_correction_prompt(
        plan,
        compile_initial_prompt(plan),
        failed,
    )

    assert "CAMERA-STUDY RE-ANCHOR" in corrected
    assert "requested side camera view" in corrected
    assert "supplied source as the single design-identity anchor" in corrected
    assert "newly revealed surface minimal and review-only" in corrected
    assert "source_design_preserved" in instruction


@pytest.fixture
def angle_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_db():
        with Session() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with Session() as db:
        source = ImageAsset(
            id=PROJECT_ID,
            root_id=PROJECT_ID,
            parent_asset_id=None,
            design_id=None,
            design_version=None,
            capability="CREATIVE_RENDER",
            instruction="Selected ring direction",
            image=SOURCE,
            media_type="image/png",
            created_by=OWNER,
        )
        db.add_all([
            source,
            Project(
                root_id=PROJECT_ID,
                owner=OWNER,
                title="Selected direction",
                tags=[],
                selected_candidate_asset_id=PROJECT_ID,
            ),
        ])
        db.commit()
    try:
        yield TestClient(app), Session
    finally:
        app.dependency_overrides.clear()


def _generator(*, hard_fail_view: str | None = None):
    def generate(source: bytes, view: str, variant: int):
        plan = build_image_plan(
            ImageOperation.REFERENCE_RENDER,
            f"Exact {view} camera study",
            source_image=source,
            frozen=("exact selected jewelry",),
            expected_output=f"one {view} image",
            variant=variant,
        )

        class Provider:
            def execute(self, *_args, **_kwargs):
                return ProviderImage(image_bytes=OUTPUTS[view])

        class Evaluator:
            def evaluate(self, *_args, **_kwargs):
                return ImageQualityReport(
                    verdict=QualityVerdict.PASS,
                    checks=(QualityCheck(
                        code="angle_fidelity",
                        passed=True,
                        severity=CheckSeverity.HARD,
                        message="selected design remained exact",
                    ),),
                    score=96,
                )

        result = JewelryImageAgent(Provider(), Evaluator()).run(
            plan, source_image=source)
        if view == hard_fail_view:
            failed = ImageQualityReport(
                verdict=QualityVerdict.FAIL,
                checks=(QualityCheck(
                    code="angle_drift",
                    passed=False,
                    severity=CheckSeverity.HARD,
                    message="the jewelry design drifted",
                ),),
                score=12,
            )
            return result.model_copy(update={
                "quality": failed,
                "accepted": False,
                "review_required": False,
            })
        return result

    return generate


def _job(client: TestClient) -> str:
    created = client.post("/studio/jobs", json={
        "owner": OWNER,
        "action_id": "angles",
        "lane": "fast_visual",
        "active_design_id": PROJECT_ID,
        "source_revision_id": PROJECT_ID,
        "requested_outputs": 3,
        "credits_per_output": 18,
    })
    assert created.status_code == 201, created.text
    job_id = created.json()["job_id"]
    running = client.patch(f"/studio/jobs/{job_id}", json={
        "owner": OWNER,
        "status": "running",
        "progress": 0.1,
    })
    assert running.status_code == 200, running.text
    return job_id


def _create(client: TestClient, *, generator=None):
    if generator is not None:
        app.dependency_overrides[get_visual_angle_set_generator] = (
            lambda: generator
        )
    job_id = _job(client)
    response = client.post(
        f"/studio/projects/{PROJECT_ID}/visual-angle-sets",
        json={
            "created_by": OWNER,
            "expected_active_asset_id": PROJECT_ID,
            "studio_job_id": job_id,
            "variant": 7,
        },
    )
    return response, job_id


def _decision_payload() -> dict:
    return {
        "created_by": OWNER,
        "expected_project_id": PROJECT_ID,
        "expected_source_asset_id": PROJECT_ID,
        "expected_source_sha256": SOURCE_SHA,
    }


def test_activity_expires_unresolved_angle_set_without_charge(angle_client):
    client, Session = angle_client
    response, job_id = _create(client, generator=_generator())
    assert response.status_code == 201, response.text
    angle_set_id = response.json()["angle_set"]["angle_set_id"]
    with Session() as db:
        record = db.get(StudioVisualAngleSetRecord, angle_set_id)
        assert record is not None
        record.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()

    activity = client.get("/studio/jobs", params={"owner": OWNER})
    assert activity.status_code == 200, activity.text
    recovered = next(
        job for job in activity.json()["jobs"] if job["job_id"] == job_id
    )
    assert recovered["status"] == "canceled"
    assert recovered["billing"]["completed_outputs"] == 0
    assert recovered["billing"]["charged_outputs"] == 0

    with Session() as db:
        record = db.get(StudioVisualAngleSetRecord, angle_set_id)
        rows = list(db.scalars(select(
            StudioVisualAngleCandidateRecord,
        ).where(
            StudioVisualAngleCandidateRecord.angle_set_id == angle_set_id,
        )))
        assert record is not None and record.status == "expired"
        assert len(rows) == 3
        assert all(row.status == "expired" and bytes(row.image) == b""
                   for row in rows)


def test_job_lookup_fails_closed_before_an_angle_set_exists(angle_client):
    client, _Session = angle_client
    job_id = _job(client)

    response = client.get(
        f"/studio/visual-angle-sets/by-job/{job_id}",
        params={"owner": OWNER},
    )

    assert response.status_code == 404, response.text
    assert response.json() == {
        "code": "visual_angle_set_unavailable",
        "category": "not_found",
        "detail": "the visual angle set is unavailable",
    }


def test_create_and_accept_angle_set_is_atomic_and_does_not_advance_revision(
    angle_client,
):
    client, Session = angle_client
    response, job_id = _create(client, generator=_generator())
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["action_id"] == "angles"
    assert body["requested_outputs"] == 3
    assert body["credits_per_output"] == 18
    assert body["estimated_credits"] == 54
    assert "failed generation" in body["billing_policy"]
    angle_set = body["angle_set"]
    assert angle_set["source_sha256"] == SOURCE_SHA
    assert [item["view"] for item in angle_set["candidates"]] == [
        "front", "three_quarter", "side",
    ]
    assert all(item["routing"]["attempt_count"] == 1
               for item in angle_set["candidates"])
    assert all(item["qa"]["review_required"] is True
               for item in angle_set["candidates"])
    assert all(item["preview_url"].endswith(f"?owner={OWNER}")
               for item in angle_set["candidates"])

    recovered = client.get(
        f"/studio/visual-angle-sets/by-job/{job_id}",
        params={"owner": OWNER},
    )
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["action_id"] == "angles"
    assert recovered.json()["angle_set"] == angle_set
    hidden = client.get(
        f"/studio/visual-angle-sets/by-job/{job_id}",
        params={"owner": "usr_someone_else"},
    )
    assert hidden.status_code == 404, hidden.text
    assert hidden.json()["code"] == "visual_angle_set_unavailable"

    with Session() as db:
        assert db.scalar(select(func.count()).select_from(
            StudioVisualAngleCandidateRecord)) == 3
        assert db.scalar(select(func.count()).select_from(ImageAsset).where(
            ImageAsset.capability == "ANGLE_VIEW")) == 0
        assert db.scalar(select(func.count()).select_from(ImageRun)) == 3
        job = db.get(StudioJobRecord, job_id)
        assert job is not None
        assert job.action_id == "angles"
        assert (job.status, job.completed_outputs, job.charged_outputs) == (
            "reviewing", 0, 0,
        )

    accepted = client.post(
        f"/studio/visual-angle-sets/{angle_set['angle_set_id']}/accept",
        json=_decision_payload(),
    )
    assert accepted.status_code == 201, accepted.text
    accepted_body = accepted.json()
    assert accepted_body["capability"] == "ANGLE_VIEW"
    assert accepted_body["active_revision_unchanged"] is True
    assert len(accepted_body["asset_ids"]) == 3

    with Session() as db:
        project = db.get(Project, PROJECT_ID)
        job = db.get(StudioJobRecord, job_id)
        stored_set = db.get(
            StudioVisualAngleSetRecord, angle_set["angle_set_id"])
        assets = list(db.scalars(select(ImageAsset).where(
            ImageAsset.capability == "ANGLE_VIEW",
        ).order_by(ImageAsset.id)))
        assert project is not None and project.selected_candidate_asset_id == PROJECT_ID
        assert stored_set is not None and stored_set.status == "accepted"
        assert job is not None
        assert (job.status, job.completed_outputs, job.charged_outputs) == (
            "succeeded", 3, 3,
        )
        assert len(assets) == 3
        assert all(asset.parent_asset_id == PROJECT_ID for asset in assets)
        assert all(asset.design_id is None and asset.design_version is None
                   for asset in assets)
        assert db.scalar(select(func.count()).select_from(ImageRunReview).where(
            ImageRunReview.decision == "accepted")) == 3


def test_angle_generation_is_concurrent_but_returns_canonical_order(
    angle_client,
):
    client, _Session = angle_client
    barrier = threading.Barrier(3)
    base_generate = _generator()

    def generate(source: bytes, view: str, variant: int):
        barrier.wait(timeout=3)
        return base_generate(source, view, variant)

    response, _job_id = _create(client, generator=generate)
    assert response.status_code == 201, response.text
    assert [item["view"] for item in response.json()["angle_set"]["candidates"]] == [
        "front", "three_quarter", "side",
    ]


def test_hard_failure_creates_no_review_set_and_charges_nothing(angle_client):
    client, Session = angle_client
    response, job_id = _create(
        client, generator=_generator(hard_fail_view="side"))
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "visual_angle_failed_quality"
    assert response.json()["failed_view"] == "side"

    with Session() as db:
        assert db.scalar(select(func.count()).select_from(
            StudioVisualAngleSetRecord)) == 0
        assert db.scalar(select(func.count()).select_from(
            StudioVisualAngleCandidateRecord)) == 0
        assert db.scalar(select(func.count()).select_from(ImageAsset).where(
            ImageAsset.capability == "ANGLE_VIEW")) == 0
        job = db.get(StudioJobRecord, job_id)
        assert job is not None
        assert (job.status, job.completed_outputs, job.charged_outputs) == (
            "failed", 0, 0,
        )


def test_discard_rejects_whole_set_without_charge(angle_client):
    client, Session = angle_client
    response, job_id = _create(client, generator=_generator())
    assert response.status_code == 201, response.text
    angle_set_id = response.json()["angle_set"]["angle_set_id"]
    discarded = client.post(
        f"/studio/visual-angle-sets/{angle_set_id}/discard",
        json=_decision_payload(),
    )
    assert discarded.status_code == 200, discarded.text
    assert discarded.json()["charged_outputs"] == 0

    with Session() as db:
        job = db.get(StudioJobRecord, job_id)
        stored_set = db.get(StudioVisualAngleSetRecord, angle_set_id)
        assert job is not None
        assert (job.status, job.completed_outputs, job.charged_outputs) == (
            "canceled", 0, 0,
        )
        assert stored_set is not None and stored_set.status == "discarded"
        assert db.scalar(select(func.count()).select_from(ImageAsset).where(
            ImageAsset.capability == "ANGLE_VIEW")) == 0
        assert db.scalar(select(func.count()).select_from(ImageRunReview).where(
            ImageRunReview.decision == "rejected")) == 3


def test_accounting_failure_rolls_back_every_angle_and_review(
    angle_client, monkeypatch,
):
    client, Session = angle_client
    response, job_id = _create(client, generator=_generator())
    assert response.status_code == 201, response.text
    angle_set_id = response.json()["angle_set"]["angle_set_id"]

    def fail_accounting(*_args, **_kwargs):
        raise StudioJobAccountingError("injected accounting failure")

    monkeypatch.setattr(
        visual_angle_sets,
        "record_accepted_studio_job_outputs",
        fail_accounting,
    )
    failed = client.post(
        f"/studio/visual-angle-sets/{angle_set_id}/accept",
        json=_decision_payload(),
    )
    assert failed.status_code == 409, failed.text
    assert failed.json()["code"] == "visual_angle_resolution_conflict"

    with Session() as db:
        job = db.get(StudioJobRecord, job_id)
        stored_set = db.get(StudioVisualAngleSetRecord, angle_set_id)
        rows = list(db.scalars(select(StudioVisualAngleCandidateRecord).where(
            StudioVisualAngleCandidateRecord.angle_set_id == angle_set_id,
        )))
        assert job is not None
        assert (job.status, job.completed_outputs, job.charged_outputs) == (
            "reviewing", 0, 0,
        )
        assert stored_set is not None and stored_set.status == "reviewing"
        assert len(rows) == 3 and all(row.status == "reviewing" for row in rows)
        assert all(row.image for row in rows)
        assert db.scalar(select(func.count()).select_from(ImageAsset).where(
            ImageAsset.capability == "ANGLE_VIEW")) == 0
        assert db.scalar(select(func.count()).select_from(ImageRunReview)) == 0

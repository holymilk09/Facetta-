"""Studio pre-spec previews stay temporary until explicit review."""

from __future__ import annotations

import hashlib
import io
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from conftest import EXAMPLE_SPEC, audited_import_spec
from facetta.api import studio as studio_api
from facetta.api.studio import get_studio_visual_preview_generator
from facetta.db import (
    ApprovalChecklist,
    Base,
    Design,
    DesignVersion,
    ImageAsset,
    ImageRun,
    ImageRunReview,
    ImmutableImageAssetError,
    Project,
    ProjectRevisionRecord,
    PreviewCandidateRecord,
    get_db,
    StudioJobRecord,
    utcnow,
)
from facetta.image_agent import (
    CheckSeverity,
    ImageOperation,
    ImageProviderFailure,
    ImageQualityReport,
    JewelryImageAgent,
    ProviderImage,
    QualityCheck,
    QualityVerdict,
    build_image_plan,
)
from facetta.main import app
from facetta.spec import Spec
from facetta.studio_visual_candidates import (
    StudioVisualCandidateUnavailable,
    clear_studio_visual_candidates_for_tests,
    store_studio_visual_candidate,
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
                source_kind="photograph",
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
                    checks=(QualityCheck(
                        code="fixture_quality",
                        passed=True,
                        severity=CheckSeverity.HARD,
                        message="fixture candidate passed",
                    ),),
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


def _running_refine_job(client: TestClient) -> str:
    created = client.post("/studio/jobs", json={
        "owner": "usr_studio",
        "action_id": "refine",
        "lane": "trusted_structural",
        "active_design_id": "ast_selected",
        "source_revision_id": "ast_selected",
        "requested_outputs": 1,
        "credits_per_output": 20,
    })
    assert created.status_code == 201, created.text
    job_id = created.json()["job_id"]
    running = client.patch(f"/studio/jobs/{job_id}", json={
        "owner": "usr_studio",
        "status": "running",
        "progress": 0.05,
    })
    assert running.status_code == 200, running.text
    return job_id


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


@pytest.mark.parametrize(
    ("verdict", "qa"),
    [
        (
            "pass",
            {
                "verdict": "fail",
                "accepted": False,
                "review_required": False,
                "checks": [],
            },
        ),
        (
            "pass",
            {
                "verdict": "pass",
                "accepted": True,
                "review_required": False,
                "checks": [],
            },
        ),
        (
            "pass",
            {
                "verdict": "pass",
                "accepted": True,
                "review_required": False,
                "checks": [{
                    "code": "outside_drift",
                    "passed": False,
                    "severity": "hard",
                }],
            },
        ),
        (
            "warn",
            {
                "verdict": "warn",
                "accepted": False,
                "review_required": False,
                "checks": [],
            },
        ),
    ],
)
def test_visual_candidate_store_rejects_failed_or_inconsistent_qa_before_write(
    studio_preview_client,
    verdict,
    qa,
):
    _client, Session = studio_preview_client
    before = _counts(Session)
    with Session() as db:
        with pytest.raises(
            StudioVisualCandidateUnavailable,
            match="failed or has incomplete QA evidence",
        ):
            store_studio_visual_candidate(
                db,
                run_id="run_failed_qa",
                verdict=verdict,
                project_root_id="ast_selected",
                source_asset_id="ast_selected",
                expected_selected_candidate_asset_id="ast_selected",
                source_hash=hashlib.sha256(SOURCE).hexdigest(),
                image_bytes=CANDIDATE,
                media_type="image/png",
                requested_change="Make it warmer",
                scope="appearance",
                qa=qa,
                created_by="usr_studio",
            )
        assert db.scalar(
            select(func.count()).select_from(PreviewCandidateRecord)
        ) == 0
    assert _counts(Session) == before


def test_tampered_failed_qa_candidate_cannot_become_canonical(
    studio_preview_client,
):
    client, Session = studio_preview_client
    app.dependency_overrides[get_studio_visual_preview_generator] = (
        lambda: _generator([])
    )
    preview = _preview(client).json()
    candidate_id = preview["candidate"]["candidate_id"]
    run_id = preview["image_run_id"]
    with Session() as db:
        record = db.get(PreviewCandidateRecord, candidate_id)
        assert record is not None
        payload = dict(record.payload)
        payload["qa"] = {
            "verdict": "fail",
            "accepted": False,
            "review_required": False,
            "checks": [{
                "code": "outside_drift",
                "passed": False,
                "severity": "hard",
            }],
        }
        record.payload = payload
        db.commit()

    rejected = client.post(
        f"/studio/image-runs/{run_id}/visual-candidates/{candidate_id}/accept",
        json={
            "created_by": "usr_studio",
            "expected_active_asset_id": "ast_selected",
        },
    )
    assert rejected.status_code == 410, rejected.text
    assert rejected.json()["code"] == "visual_preview_unavailable"
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 1
        assert db.scalar(select(func.count()).select_from(ImageRunReview)) == 0
        assert db.scalar(select(func.count()).select_from(
            ProjectRevisionRecord)) == 0
        record = db.get(PreviewCandidateRecord, candidate_id)
        assert record is not None
        assert record.status == "expired"
        assert bytes(record.image) == b""


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
    reopened = client.get("/studio/projects/ast_selected/visual-candidates")
    assert reopened.status_code == 200
    assert [item["candidate_id"] for item in reopened.json()["candidates"]] == [
        body["candidate"]["candidate_id"]
    ]
    with Session() as db:
        durable = db.get(
            PreviewCandidateRecord, body["candidate"]["candidate_id"])
        assert durable is not None
        assert durable.status == "reviewing"
        assert bytes(durable.image) == CANDIDATE

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
        assert child.capability == "GLOBAL_RESTYLE"
        assert child.source_kind == "photograph"
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
        durable = db.get(
            PreviewCandidateRecord, body["candidate"]["candidate_id"])
        assert durable is not None
        assert durable.status == "applied"
        assert durable.terminal_asset_id == child.id
        assert durable.review_id == review.id
        assert bytes(durable.image) == b""

    assert client.get(body["candidate"]["preview_url"]).status_code == 410


def test_applied_pre_spec_child_is_the_only_confirmable_design_v1_source(
    studio_preview_client, monkeypatch,
):
    client, Session = studio_preview_client
    app.dependency_overrides[get_studio_visual_preview_generator] = (
        lambda: _generator([])
    )
    expected = Spec.model_validate(audited_import_spec(EXAMPLE_SPEC))
    monkeypatch.setattr(
        "facetta.api.projects.from_photo",
        lambda _request: expected,
    )

    original_confirmation = client.post(
        "/projects/ast_selected/creative-candidates/ast_selected/confirm-design",
        json={"created_by": "usr_studio"},
    )
    assert original_confirmation.status_code == 200, original_confirmation.text
    original_token = original_confirmation.json()["confirmation_token"]

    preview = _preview(client).json()
    accepted = client.post(
        f"/studio/image-runs/{preview['image_run_id']}/visual-candidates/"
        f"{preview['candidate']['candidate_id']}/accept",
        json={
            "created_by": "usr_studio",
            "expected_active_asset_id": "ast_selected",
        },
    )
    assert accepted.status_code == 201, accepted.text
    child_id = accepted.json()["new_asset_id"]
    applied_project = accepted.json()["project"]
    assert applied_project["active_asset_id"] == child_id
    assert applied_project["confirmable_pre_spec"] is True

    stale_confirmation = client.post(
        "/projects/ast_selected/creative-candidates/ast_selected/confirm-design",
        json={"created_by": "usr_studio"},
    )
    assert stale_confirmation.status_code == 409
    assert "current confirmable pre-spec revision" in (
        stale_confirmation.json()["detail"]
    )
    stale_promotion = client.post(
        "/projects/ast_selected/creative-candidates/ast_selected/promote",
        json={
            "created_by": "usr_studio",
            "confirmation_token": original_token,
        },
    )
    assert stale_promotion.status_code == 409
    assert stale_promotion.json()["code"] == (
        "creative_candidate_promotion_conflict"
    )

    child_confirmation = client.post(
        f"/projects/ast_selected/creative-candidates/{child_id}/confirm-design",
        json={"created_by": "usr_studio"},
    )
    assert child_confirmation.status_code == 200, child_confirmation.text
    child_review = child_confirmation.json()
    expected_sha256 = hashlib.sha256(CANDIDATE).hexdigest()
    assert child_review["candidate_id"] == child_id
    assert child_review["candidate_sha256"] == expected_sha256

    promoted = client.post(
        f"/projects/ast_selected/creative-candidates/{child_id}/promote",
        json={
            "created_by": "usr_studio",
            "confirmation_token": child_review["confirmation_token"],
        },
    )
    assert promoted.status_code == 200, promoted.text
    exact = promoted.json()
    assert exact["confirmable_pre_spec"] is False
    assert exact["latest_design_version"] == 1
    assert exact["active_design_version"] == 1
    assert exact["active_revision"]["parent_asset_id"] == child_id
    assert exact["active_revision"]["sha256"] == expected_sha256

    with Session() as db:
        active = db.get(ImageAsset, exact["active_asset_id"])
        version = db.scalar(select(DesignVersion))
        assert active is not None and bytes(active.image) == CANDIDATE
        assert version is not None and version.version == 1
        assert version.spec["design_id"] == exact["design_id"]
        record = db.scalar(select(ProjectRevisionRecord).where(
            ProjectRevisionRecord.asset_id == active.id
        ))
        assert record is not None
        assert record.raw_intent["selected_candidate_asset_id"] == child_id
        assert record.raw_intent["candidate_sha256"] == expected_sha256


def test_visual_apply_atomically_settles_accepted_studio_job(
    studio_preview_client,
):
    client, Session = studio_preview_client
    app.dependency_overrides[get_studio_visual_preview_generator] = (
        lambda: _generator([])
    )
    job_id = _running_refine_job(client)

    preview = _preview(client, studio_job_id=job_id)
    assert preview.status_code == 201, preview.text
    body = preview.json()
    accepted = client.post(
        f"/studio/image-runs/{body['image_run_id']}/visual-candidates/"
        f"{body['candidate']['candidate_id']}/accept",
        json={
            "created_by": "usr_studio",
            "expected_active_asset_id": "ast_selected",
        },
    )
    assert accepted.status_code == 201, accepted.text
    with Session() as db:
        job = db.get(StudioJobRecord, job_id)
        assert job is not None
        assert job.status == "succeeded"
        assert job.completed_outputs == 1
        assert job.charged_outputs == 1
        assert job.active_design_id == "ast_selected"
        assert job.source_revision_id == "ast_selected"


def test_visual_discard_atomically_cancels_bound_job_without_charge(
    studio_preview_client,
):
    client, Session = studio_preview_client
    app.dependency_overrides[get_studio_visual_preview_generator] = (
        lambda: _generator([])
    )
    job_id = _running_refine_job(client)
    preview = _preview(client, studio_job_id=job_id)
    assert preview.status_code == 201, preview.text
    body = preview.json()
    with Session() as db:
        reserved = db.get(StudioJobRecord, job_id)
        assert reserved is not None
        assert reserved.status == "reviewing"
        assert reserved.completed_outputs == 0
        assert reserved.charged_outputs == 0

    discarded = client.post(
        f"/studio/image-runs/{body['image_run_id']}/visual-candidates/"
        f"{body['candidate']['candidate_id']}/discard",
        json={
            "created_by": "usr_studio",
            "expected_active_asset_id": "ast_selected",
        },
    )
    assert discarded.status_code == 200, discarded.text
    with Session() as db:
        job = db.get(StudioJobRecord, job_id)
        candidate = db.get(
            PreviewCandidateRecord, body["candidate"]["candidate_id"])
        assert job is not None
        assert job.status == "canceled"
        assert job.progress == 1
        assert job.completed_outputs == 0
        assert job.charged_outputs == 0
        assert job.error_code is None
        assert candidate is not None and candidate.status == "discarded"
        assert db.scalar(select(func.count()).select_from(
            ProjectRevisionRecord)) == 0


def test_visual_reserved_job_rejects_public_terminal_transition(
    studio_preview_client,
):
    client, Session = studio_preview_client
    app.dependency_overrides[get_studio_visual_preview_generator] = (
        lambda: _generator([])
    )
    job_id = _running_refine_job(client)
    preview = _preview(client, studio_job_id=job_id)
    assert preview.status_code == 201, preview.text

    raced = client.patch(f"/studio/jobs/{job_id}", json={
        "owner": "usr_studio",
        "status": "failed",
        "progress": 1,
        "error_code": "stale_client_failure",
    })
    assert raced.status_code == 409, raced.text
    assert "candidate decision" in raced.json()["detail"]
    body = preview.json()
    discarded = client.post(
        f"/studio/image-runs/{body['image_run_id']}/visual-candidates/"
        f"{body['candidate']['candidate_id']}/discard",
        json={
            "created_by": "usr_studio",
            "expected_active_asset_id": "ast_selected",
        },
    )
    assert discarded.status_code == 200, discarded.text
    with Session() as db:
        job = db.get(StudioJobRecord, job_id)
        assert job is not None
        assert job.status == "canceled"
        assert job.reservation_kind is None
        assert job.completed_outputs == 0
        assert job.charged_outputs == 0


def test_orphaned_visual_reservation_expires_before_safe_retry(
    studio_preview_client,
):
    client, Session = studio_preview_client
    calls: list[dict] = []
    app.dependency_overrides[get_studio_visual_preview_generator] = (
        lambda: _generator(calls)
    )
    job_id = _running_refine_job(client)
    with Session() as db:
        job = db.get(StudioJobRecord, job_id)
        assert job is not None
        job.status = "reviewing"
        job.progress = 0.5
        job.reservation_kind = "studio_visual"
        job.updated_at = utcnow() - timedelta(minutes=16)
        db.commit()

    recovered = _preview(client, studio_job_id=job_id)
    assert recovered.status_code == 409, recovered.text
    assert recovered.json()["code"] == "visual_preview_job_reservation_expired"
    assert calls == []
    with Session() as db:
        job = db.get(StudioJobRecord, job_id)
        assert job is not None
        assert job.status == "failed"
        assert job.error_code == "visual_preview_reservation_expired"
        assert job.reservation_kind is None
        assert job.completed_outputs == 0
        assert job.charged_outputs == 0


def test_activity_read_recovers_orphaned_visual_reservation(
    studio_preview_client,
):
    client, Session = studio_preview_client
    job_id = _running_refine_job(client)
    with Session() as db:
        job = db.get(StudioJobRecord, job_id)
        assert job is not None
        job.status = "reviewing"
        job.progress = 0.5
        job.reservation_kind = "studio_visual"
        job.updated_at = utcnow() - timedelta(minutes=16)
        db.commit()

    activity = client.get("/studio/jobs", params={"owner": "usr_studio"})
    assert activity.status_code == 200, activity.text
    recovered = next(
        job for job in activity.json()["jobs"] if job["job_id"] == job_id
    )
    assert recovered["status"] == "failed"
    assert recovered["error_code"] == "visual_preview_reservation_expired"
    assert recovered["billing"]["charged_outputs"] == 0


def test_visual_reservation_rejects_foreign_invalid_reused_and_misbound_jobs(
    studio_preview_client,
):
    client, Session = studio_preview_client
    calls: list[dict] = []
    app.dependency_overrides[get_studio_visual_preview_generator] = (
        lambda: _generator(calls)
    )

    foreign_job = _running_refine_job(client)
    foreign = _preview(
        client, studio_job_id=foreign_job, created_by="usr_intruder",
    )
    assert foreign.status_code == 404
    assert foreign.json()["code"] == "visual_preview_job_unavailable"

    invalid_job = _running_refine_job(client)
    with Session() as db:
        job = db.get(StudioJobRecord, invalid_job)
        assert job is not None
        job.requested_outputs = 2
        db.commit()
    invalid = _preview(client, studio_job_id=invalid_job)
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "visual_preview_job_invalid"

    misbound_job = _running_refine_job(client)
    with Session() as db:
        job = db.get(StudioJobRecord, misbound_job)
        assert job is not None
        job.source_revision_id = "ast_other_revision"
        db.commit()
    misbound = _preview(client, studio_job_id=misbound_job)
    assert misbound.status_code == 422
    assert misbound.json()["code"] == "visual_preview_job_lineage_mismatch"

    reused_job = _running_refine_job(client)
    first = _preview(client, studio_job_id=reused_job)
    assert first.status_code == 201, first.text
    reused = _preview(client, studio_job_id=reused_job)
    assert reused.status_code == 409
    assert reused.json()["code"] == "visual_preview_job_terminal"
    assert len(calls) == 1


def test_visual_failure_reconciliation_preserves_evidence_after_trusted_race(
    studio_preview_client,
):
    client, Session = studio_preview_client
    job_id = _running_refine_job(client)

    def race_then_generate(source, instruction, scope, mask, variant):
        with Session() as race_db:
            job = race_db.get(StudioJobRecord, job_id)
            assert job is not None and job.status == "reviewing"
            job.status = "failed"
            job.progress = 1
            job.error_code = "trusted_competing_failure"
            job.reservation_kind = None
            race_db.commit()
        return _generator([])(source, instruction, scope, mask, variant)

    app.dependency_overrides[get_studio_visual_preview_generator] = (
        lambda: race_then_generate
    )
    failed = _preview(client, studio_job_id=job_id)
    assert failed.status_code == 409, failed.text
    assert failed.json()["code"] == "visual_preview_candidate_unavailable"
    with Session() as db:
        job = db.get(StudioJobRecord, job_id)
        runs = list(db.scalars(select(ImageRun)))
        assert job is not None
        assert job.status == "failed"
        assert job.error_code == "trusted_competing_failure"
        assert job.completed_outputs == 0
        assert job.charged_outputs == 0
        assert len(runs) == 1
        assert runs[0].status == "failed"
        assert db.scalar(select(func.count()).select_from(
            PreviewCandidateRecord)) == 0


def test_visual_provider_failure_atomically_fails_bound_job_without_charge(
    studio_preview_client,
):
    client, Session = studio_preview_client

    def fail_provider(source, instruction, scope, mask, variant):
        plan = build_image_plan(
            ImageOperation.REFERENCE_RENDER,
            instruction,
            source_image=source,
            mask_bytes=mask,
            mask_provenance=("test_markup" if mask is not None else None),
            variant=variant,
        )
        raise ImageProviderFailure("provider unavailable", plan=plan)

    app.dependency_overrides[get_studio_visual_preview_generator] = (
        lambda: fail_provider
    )
    job_id = _running_refine_job(client)
    failed = _preview(client, studio_job_id=job_id)
    assert failed.status_code == 502, failed.text
    assert failed.json()["code"] == "image_provider_failed"
    with Session() as db:
        job = db.get(StudioJobRecord, job_id)
        run = db.scalar(select(ImageRun))
        assert job is not None
        assert job.status == "failed"
        assert job.progress == 1
        assert job.completed_outputs == 0
        assert job.charged_outputs == 0
        assert job.error_code == "image_provider_failed"
        assert run is not None and run.status == "failed"
        assert db.scalar(select(func.count()).select_from(
            PreviewCandidateRecord)) == 0


def test_visual_qa_failure_atomically_fails_bound_job_without_charge(
    studio_preview_client,
):
    client, Session = studio_preview_client

    def fail_quality(source, instruction, scope, mask, variant):
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
                    verdict=QualityVerdict.FAIL,
                    checks=(QualityCheck(
                        code="source_design_preserved",
                        passed=False,
                        severity=CheckSeverity.HARD,
                        message="geometry drifted",
                    ),),
                    score=20,
                )

        return JewelryImageAgent(Provider(), Evaluator()).run(
            plan, source_image=source, mask_bytes=mask)

    app.dependency_overrides[get_studio_visual_preview_generator] = (
        lambda: fail_quality
    )
    job_id = _running_refine_job(client)
    failed = _preview(client, studio_job_id=job_id)
    assert failed.status_code == 422, failed.text
    assert failed.json()["code"] == "image_quality_failed"
    with Session() as db:
        job = db.get(StudioJobRecord, job_id)
        run = db.scalar(select(ImageRun))
        assert job is not None
        assert job.status == "failed"
        assert job.completed_outputs == 0
        assert job.charged_outputs == 0
        assert job.error_code == "image_quality_failed"
        assert run is not None and run.status == "failed"
        assert db.scalar(select(func.count()).select_from(
            PreviewCandidateRecord)) == 0


def test_visual_candidate_store_failure_preserves_failed_evidence_and_job(
    studio_preview_client,
    monkeypatch,
):
    client, Session = studio_preview_client
    app.dependency_overrides[get_studio_visual_preview_generator] = (
        lambda: _generator([])
    )

    def reject_candidate(*_args, **_kwargs):
        raise StudioVisualCandidateUnavailable(
            "the generated output could not be bound to the reserved job")

    monkeypatch.setattr(
        studio_api, "store_studio_visual_candidate", reject_candidate)
    job_id = _running_refine_job(client)
    failed = _preview(client, studio_job_id=job_id)
    assert failed.status_code == 409, failed.text
    assert failed.json()["code"] == "visual_preview_candidate_unavailable"
    with Session() as db:
        job = db.get(StudioJobRecord, job_id)
        runs = list(db.scalars(select(ImageRun)))
        assert job is not None
        assert job.status == "failed"
        assert job.completed_outputs == 0
        assert job.charged_outputs == 0
        assert job.error_code == "visual_preview_candidate_unavailable"
        assert len(runs) == 1
        assert runs[0].status == "failed"
        assert db.scalar(select(func.count()).select_from(
            PreviewCandidateRecord)) == 0


def test_stale_visual_request_fails_reserved_job_before_provider_work(
    studio_preview_client,
):
    client, Session = studio_preview_client
    calls: list[dict] = []
    app.dependency_overrides[get_studio_visual_preview_generator] = (
        lambda: _generator(calls)
    )
    job_id = _running_refine_job(client)
    with Session() as db:
        sibling = ImageAsset(
            id="ast_new_selection",
            root_id="ast_selected",
            parent_asset_id="ast_selected",
            design_version=None,
            capability="CREATIVE_RENDER",
            image=CANDIDATE,
            media_type="image/png",
            created_by="usr_studio",
        )
        db.add(sibling)
        db.flush()
        db.get(Project, "ast_selected").selected_candidate_asset_id = sibling.id
        db.commit()

    failed = _preview(client, studio_job_id=job_id)
    assert failed.status_code == 409, failed.text
    assert failed.json()["code"] == "stale_asset_revision"
    assert calls == []
    with Session() as db:
        job = db.get(StudioJobRecord, job_id)
        assert job is not None
        assert job.status == "failed"
        assert job.completed_outputs == 0
        assert job.charged_outputs == 0
        assert job.error_code == "stale_asset_revision"
        assert db.scalar(select(func.count()).select_from(ImageRun)) == 0
        assert db.scalar(select(func.count()).select_from(
            PreviewCandidateRecord)) == 0


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
    with Session() as db:
        durable = db.get(PreviewCandidateRecord, candidate_id)
        assert durable is not None
        assert durable.status == "discarded"
        assert durable.decided_by == "usr_studio"
        assert durable.review_id is not None
        assert bytes(durable.image) == b""
    assert client.post(
        f"/studio/image-runs/{run_id}/visual-candidates/{candidate_id}/accept",
        json={
            "created_by": "usr_studio",
            "expected_active_asset_id": "ast_selected",
        },
    ).status_code == 410


def test_visual_preview_saves_directly_as_independent_variation(
    studio_preview_client,
):
    client, Session = studio_preview_client
    app.dependency_overrides[get_studio_visual_preview_generator] = (
        lambda: _generator([])
    )
    preview = _preview(client).json()
    candidate_id = preview["candidate"]["candidate_id"]
    run_id = preview["image_run_id"]

    saved = client.post(
        f"/studio/image-runs/{run_id}/visual-candidates/{candidate_id}/"
        "save-as-variation",
        json={"created_by": "usr_studio", "label": "Warm metal"},
    )
    assert saved.status_code == 201, saved.text
    body = saved.json()
    assert body["status"] == "saved_as_variation"
    sibling_id = body["project"]["root_id"]
    with Session() as db:
        original = db.get(Project, "ast_selected")
        sibling = db.get(Project, sibling_id)
        asset = db.get(ImageAsset, sibling_id)
        durable = db.get(PreviewCandidateRecord, candidate_id)
        review = db.scalar(select(ImageRunReview).where(
            ImageRunReview.run_id == run_id
        ))
        assert original is not None and sibling is not None and asset is not None
        assert original.selected_candidate_asset_id == "ast_selected"
        assert sibling.family_id == original.family_id
        assert sibling.variation_label == "Warm metal"
        assert sibling.branched_from_project_root_id == original.root_id
        assert bytes(asset.image) == CANDIDATE
        assert asset.design_id is None and asset.design_version is None
        assert durable is not None
        assert durable.status == "saved_as_variation"
        assert durable.terminal_asset_id == sibling_id
        assert review is not None and review.accepted_asset_id == sibling_id
    repeated = client.post(
        f"/studio/image-runs/{run_id}/visual-candidates/{candidate_id}/"
        "save-as-variation",
        json={"created_by": "usr_studio", "label": "Duplicate"},
    )
    assert repeated.status_code == 410


def test_bound_visual_save_as_variation_charges_exactly_one_output(
    studio_preview_client,
):
    client, Session = studio_preview_client
    app.dependency_overrides[get_studio_visual_preview_generator] = (
        lambda: _generator([])
    )
    job_id = _running_refine_job(client)
    preview = _preview(client, studio_job_id=job_id)
    assert preview.status_code == 201, preview.text
    body = preview.json()

    saved = client.post(
        f"/studio/image-runs/{body['image_run_id']}/visual-candidates/"
        f"{body['candidate']['candidate_id']}/save-as-variation",
        json={"created_by": "usr_studio", "label": "Bound warm metal"},
    )
    assert saved.status_code == 201, saved.text
    with Session() as db:
        job = db.get(StudioJobRecord, job_id)
        source = db.get(Project, "ast_selected")
        candidate = db.get(
            PreviewCandidateRecord, body["candidate"]["candidate_id"])
        assert job is not None
        assert job.status == "succeeded"
        assert job.completed_outputs == 1
        assert job.charged_outputs == 1
        assert job.reservation_kind is None
        assert source is not None
        assert source.selected_candidate_asset_id == "ast_selected"
        assert candidate is not None
        assert candidate.status == "saved_as_variation"
        assert candidate.terminal_asset_id == saved.json()["project"]["root_id"]


def test_visual_apply_resolution_failure_rolls_back_canonical_append(
    studio_preview_client, monkeypatch,
):
    client, Session = studio_preview_client
    app.dependency_overrides[get_studio_visual_preview_generator] = (
        lambda: _generator([])
    )
    preview = _preview(client).json()
    monkeypatch.setattr(
        "facetta.api.studio.remove_studio_visual_candidate",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("resolution failed")
        ),
    )
    with pytest.raises(RuntimeError, match="resolution failed"):
        client.post(
            f"/studio/image-runs/{preview['image_run_id']}/visual-candidates/"
            f"{preview['candidate']['candidate_id']}/accept",
            json={
                "created_by": "usr_studio",
                "expected_active_asset_id": "ast_selected",
            },
        )
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 1
        assert db.scalar(select(func.count()).select_from(ImageRunReview)) == 0
        assert db.scalar(select(func.count()).select_from(
            ProjectRevisionRecord)) == 0
        durable = db.get(
            PreviewCandidateRecord, preview["candidate"]["candidate_id"])
        assert durable is not None and durable.status == "reviewing"


def test_apply_rejects_stale_selected_visual_and_source_hash(
    studio_preview_client,
):
    client, Session = studio_preview_client
    app.dependency_overrides[get_studio_visual_preview_generator] = (
        lambda: _generator([])
    )
    job_id = _running_refine_job(client)
    first = _preview(client, studio_job_id=job_id).json()
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
    assert stale.status_code == 410
    assert stale.json()["code"] == "visual_preview_unavailable"
    unavailable = client.post(
        f"/studio/image-runs/{first['image_run_id']}/visual-candidates/"
        f"{first['candidate']['candidate_id']}/discard",
        json={
            "created_by": "usr_studio",
            "expected_active_asset_id": "ast_selected",
        },
    )
    assert unavailable.status_code == 410

    with Session() as db:
        candidate = db.get(
            PreviewCandidateRecord, first["candidate"]["candidate_id"])
        assert candidate is not None
        assert candidate.status == "expired"
        assert candidate.resolved_at is not None
        assert bytes(candidate.image) == b""
        job = db.get(StudioJobRecord, job_id)
        assert job is not None
        assert job.status == "failed"
        assert job.progress == 1
        assert job.completed_outputs == 0
        assert job.charged_outputs == 0
        assert job.error_code == "visual_preview_unavailable"
        assert db.scalar(select(func.count()).select_from(ImageRunReview)) == 0
        assert db.scalar(select(func.count()).select_from(
            ProjectRevisionRecord)) == 0

    with Session() as db:
        db.get(Project, "ast_selected").selected_candidate_asset_id = "ast_selected"
        db.commit()
        db.get(ImageAsset, "ast_selected").image = _png((1, 2, 3))
        with pytest.raises(
            ImmutableImageAssetError, match="image assets are immutable",
        ):
            db.commit()
        db.rollback()


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
    assert rejected.status_code == 410
    assert rejected.json()["code"] == "visual_preview_unavailable"
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


def test_pre_spec_branch_and_restore_assets_cannot_gain_approval_authority(
    studio_preview_client,
):
    client, Session = studio_preview_client
    with Session() as db:
        branch = ImageAsset(
            id="ast_prespec_branch",
            root_id="ast_prespec_branch",
            parent_asset_id=None,
            design_id=None,
            design_version=None,
            capability="VARIATION_BRANCH",
            image=CANDIDATE,
            media_type="image/png",
            created_by="usr_studio",
        )
        branch_project = Project(
            root_id=branch.id,
            owner="usr_studio",
            title="Pre-spec branch",
            tags=[],
        )
        restored = ImageAsset(
            id="ast_prespec_restore",
            root_id="ast_selected",
            parent_asset_id="ast_selected",
            design_id=None,
            design_version=None,
            capability="RESTORED_REVISION",
            image=SOURCE,
            media_type="image/png",
            created_by="usr_studio",
        )
        db.add_all([branch, branch_project, restored])
        db.commit()

    for asset_id in ("ast_prespec_branch", "ast_prespec_restore"):
        pin = client.post(f"/assets/{asset_id}/pin")
        assert pin.status_code == 409
        assert pin.json()["code"] == "creative_candidate_requires_spec_promotion"
        checklist = client.post(f"/assets/{asset_id}/checklist", json={
            "created_by": "usr_studio",
            "mode": "explicit_pin",
            "spec": EXAMPLE_SPEC,
        })
        assert checklist.status_code == 409
        assert checklist.json()["code"] == "creative_candidate_requires_spec_promotion"

    with Session() as db:
        assert db.scalar(select(func.count()).select_from(ApprovalChecklist)) == 0
        assert db.get(ImageAsset, "ast_prespec_branch").pinned_at is None
        assert db.get(ImageAsset, "ast_prespec_restore").pinned_at is None


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

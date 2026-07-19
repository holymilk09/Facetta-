"""Studio pre-spec previews stay temporary until explicit review."""

from __future__ import annotations

import base64
import hashlib
import io
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy import create_engine, func, select, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from conftest import EXAMPLE_SPEC, audited_import_spec
from facetta import studio_preview_candidates as preview_seam
from facetta.api import studio as studio_api
from facetta.api.studio import get_studio_visual_preview_generator
from facetta.auth import AuthenticatedPrincipal, require_principal_boundary
from facetta.creative_symmetry import (
    JEWELRY_SYMMETRY_CONTRACT,
    JEWELRY_SYMMETRY_REPAIR_CONTRACT,
    SIX_LEAF_RUBY_PATTERN_CONTRACT,
)
from facetta.db import (
    ApprovalChecklist,
    Base,
    Design,
    DesignVersion,
    ImageAsset,
    ImageAssetProviderAffinity,
    ImageRun,
    ImageRunReview,
    ImmutableImageAssetError,
    Project,
    ProjectRevisionRecord,
    PreviewCandidateRecord,
    StudioContinuationPromptRecord,
    get_db,
    StudioJobRecord,
    utcnow,
)
from facetta.image_agent import (
    CheckSeverity,
    ImageOperation,
    ImagePlanValidationError,
    ImageProviderFailure,
    ImageQualityReport,
    JewelryImageAgent,
    ProviderImage,
    QualityCheck,
    QualityVerdict,
    build_image_plan,
)
from facetta.jewelry_intent import (
    BRAIDED_WHITE_GOLD_CHAIN_CONTRACT,
    SEQUENTIAL_JEWELRY_EDIT_CONTRACT,
    SMALL_DIAMOND_VISUAL_CONTRACT,
    with_sequential_jewelry_edit_contract,
)
from facetta.main import app
from facetta.spec import Spec
from facetta.studio_visual_candidates import (
    StudioVisualCandidateUnavailable,
    clear_studio_visual_candidates_for_tests,
    lock_studio_visual_candidate_for_decision,
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


def _advance_active_visual(Session, *, asset_id: str = "ast_newer") -> None:
    """Append a newer immutable visual without touching the preview source."""

    with Session() as db:
        newer = ImageAsset(
            id=asset_id,
            root_id="ast_selected",
            parent_asset_id="ast_selected",
            design_version=None,
            capability="GLOBAL_RESTYLE",
            source_kind="photograph",
            instruction="A later accepted direction",
            image=_png((100, 110, 120)),
            media_type="image/png",
            created_by="usr_studio",
        )
        db.add(newer)
        db.flush()
        project = db.get(Project, "ast_selected")
        assert project is not None
        project.selected_candidate_asset_id = newer.id
        db.commit()


def test_production_visual_preview_requires_job_before_generator(
    studio_preview_client,
    monkeypatch,
):
    client, _Session = studio_preview_client
    calls: list[dict] = []
    app.dependency_overrides[get_studio_visual_preview_generator] = (
        lambda: _generator(calls)
    )
    monkeypatch.setenv("FACETTA_ENV", "production")

    response = _preview(client)

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "studio_job_required"
    assert calls == []


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


def test_cross_provider_candidate_cannot_append_revision(
    studio_preview_client,
):
    client, Session = studio_preview_client
    app.dependency_overrides[get_studio_visual_preview_generator] = (
        lambda: _generator([])
    )
    with Session() as db:
        db.add(ImageAssetProviderAffinity(
            asset_id="ast_selected",
            provider="openai",
            model="gpt-image-2",
            source_run_id=None,
            source_attempt_id=None,
            derivation="test_provenance",
        ))
        db.commit()

    preview = _preview(client)
    assert preview.status_code == 201, preview.text
    body = preview.json()
    rejected = client.post(
        f"/studio/image-runs/{body['image_run_id']}/visual-candidates/"
        f"{body['candidate']['candidate_id']}/accept",
        json={
            "created_by": "usr_studio",
            "expected_active_asset_id": "ast_selected",
        },
    )
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["code"] == "revision_provider_mismatch"
    with Session() as db:
        project = db.get(Project, "ast_selected")
        assert project.selected_candidate_asset_id == "ast_selected"
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 1
        assert db.scalar(select(func.count()).select_from(ImageRunReview)) == 0
        assert db.scalar(select(func.count()).select_from(
            ProjectRevisionRecord)) == 0


def test_normalized_visual_preview_contract_is_owned_cas_guarded_and_idempotent(
    studio_preview_client,
):
    client, Session = studio_preview_client
    app.dependency_overrides[get_studio_visual_preview_generator] = (
        lambda: _generator([])
    )
    before = _counts(Session)
    created = _preview(client)
    assert created.status_code == 201, created.text
    legacy = created.json()
    candidate_id = legacy["candidate"]["candidate_id"]

    # Creating and reopening a normalized candidate never appends canonical
    # image/spec/revision truth.
    listed = client.get("/studio/projects/ast_selected/preview-candidates")
    assert listed.status_code == 200, listed.text
    candidates = listed.json()["candidates"]
    assert [item["kind"] for item in candidates] == ["visual"]
    assert candidates[0]["candidate_id"] == candidate_id
    assert candidates[0]["available_decisions"] == [
        "apply", "save_as_variation", "discard",
    ]
    assert candidates[0]["preview_url"].endswith("?owner=usr_studio")
    image = client.get(candidates[0]["preview_url"])
    assert image.status_code == 200 and image.content == CANDIDATE
    reopened = client.get(
        f"/studio/preview-candidates/{candidate_id}",
        params={"owner": "usr_studio"},
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["source_sha256"] == hashlib.sha256(SOURCE).hexdigest()
    assert _counts(Session) == {**before, "runs": 1}

    foreign = client.get(
        f"/studio/preview-candidates/{candidate_id}",
        params={"owner": "usr_someone_else"},
    )
    assert foreign.status_code == 404

    stale = client.post(
        f"/studio/preview-candidates/{candidate_id}/decision",
        json={
            "created_by": "usr_studio",
            "decision": "apply",
            "expected_active_asset_id": "ast_not_the_source",
        },
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["code"] == "preview_candidate_lineage_mismatch"
    assert _counts(Session) == {**before, "runs": 1}

    applied = client.post(
        f"/studio/preview-candidates/{candidate_id}/decision",
        json={
            "created_by": "usr_studio",
            "decision": "apply",
            "expected_active_asset_id": "ast_selected",
        },
    )
    assert applied.status_code == 200, applied.text
    result = applied.json()
    assert result["kind"] == "visual" and result["status"] == "applied"
    assert result["terminal_asset_id"] is not None

    replay = client.post(
        f"/studio/preview-candidates/{candidate_id}/decision",
        json={
            "created_by": "usr_studio",
            "decision": "apply",
            "expected_active_asset_id": "ast_selected",
        },
    )
    assert replay.status_code == 200, replay.text
    assert replay.json() == result
    after = _counts(Session)
    assert after == {
        **before,
        "assets": before["assets"] + 1,
        "runs": before["runs"] + 1,
        "reviews": before["reviews"] + 1,
        "records": before["records"] + 1,
    }


def test_normalized_visual_preview_rejects_tampered_qa_without_canonical_write(
    studio_preview_client,
):
    client, Session = studio_preview_client
    app.dependency_overrides[get_studio_visual_preview_generator] = (
        lambda: _generator([])
    )
    created = _preview(client).json()
    candidate_id = created["candidate"]["candidate_id"]
    with Session() as db:
        record = db.get(PreviewCandidateRecord, candidate_id)
        assert record is not None
        record.payload = {
            **record.payload,
            "qa": {
                "verdict": "fail",
                "accepted": False,
                "review_required": False,
                "checks": [{
                    "code": "outside_drift",
                    "passed": False,
                    "severity": "hard",
                }],
            },
        }
        db.commit()

    rejected = client.post(
        f"/studio/preview-candidates/{candidate_id}/decision",
        json={
            "created_by": "usr_studio",
            "decision": "apply",
            "expected_active_asset_id": "ast_selected",
        },
    )
    assert rejected.status_code == 410, rejected.text
    assert rejected.json()["code"] == "preview_candidate_unavailable"
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 1
        assert db.scalar(select(func.count()).select_from(ImageRunReview)) == 0
        assert db.scalar(select(func.count()).select_from(
            ProjectRevisionRecord)) == 0
        durable = db.get(PreviewCandidateRecord, candidate_id)
        assert durable is not None and durable.status == "expired"
        assert bytes(durable.image) == b""


def test_normalized_visual_stale_discard_is_terminal_without_canonical_write(
    studio_preview_client,
):
    client, Session = studio_preview_client
    app.dependency_overrides[get_studio_visual_preview_generator] = (
        lambda: _generator([])
    )
    created = _preview(client).json()
    candidate_id = created["candidate"]["candidate_id"]
    _advance_active_visual(Session)
    before_discard = _counts(Session)

    discarded = client.post(
        f"/studio/preview-candidates/{candidate_id}/decision",
        json={
            "created_by": "usr_studio",
            "decision": "discard",
            "expected_active_asset_id": "ast_selected",
        },
    )
    assert discarded.status_code == 200, discarded.text
    assert discarded.json()["status"] == "discarded"
    after_discard = _counts(Session)
    assert after_discard == {
        **before_discard,
        "reviews": before_discard["reviews"] + 1,
    }
    with Session() as db:
        project = db.get(Project, "ast_selected")
        durable = db.get(PreviewCandidateRecord, candidate_id)
        assert project is not None
        assert project.selected_candidate_asset_id == "ast_newer"
        assert durable is not None and durable.status == "discarded"
        assert bytes(durable.image) == b""


def test_normalized_visual_variation_replay_binds_exact_label(
    studio_preview_client,
):
    client, Session = studio_preview_client
    app.dependency_overrides[get_studio_visual_preview_generator] = (
        lambda: _generator([])
    )
    preview = _preview(client).json()
    candidate_id = preview["candidate"]["candidate_id"]
    run_id = preview["image_run_id"]
    request = {
        "created_by": "usr_studio",
        "decision": "save_as_variation",
        "expected_active_asset_id": "ast_selected",
        "variation_label": "Warm rose study",
    }
    saved = client.post(
        f"/studio/preview-candidates/{candidate_id}/decision",
        json=request,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["status"] == "saved_as_variation"
    replay = client.post(
        f"/studio/preview-candidates/{candidate_id}/decision",
        json=request,
    )
    assert replay.status_code == 200 and replay.json() == saved.json()
    legacy_replay = client.post(
        f"/studio/image-runs/{run_id}/visual-candidates/{candidate_id}/"
        "save-as-variation",
        json={"created_by": "usr_studio", "label": "Warm rose study"},
    )
    assert legacy_replay.status_code == 201, legacy_replay.text
    assert legacy_replay.json()["project"]["root_id"] == (
        saved.json()["result_project_id"]
    )
    legacy_conflict = client.post(
        f"/studio/image-runs/{run_id}/visual-candidates/{candidate_id}/"
        "save-as-variation",
        json={"created_by": "usr_studio", "label": "Another name"},
    )
    assert legacy_conflict.status_code == 409, legacy_conflict.text
    assert legacy_conflict.json()["code"] == (
        "preview_candidate_variation_conflict"
    )

    for conflicting_label, expected_status in (
        ("Another name", 409),
        (None, 422),
    ):
        conflicting = client.post(
            f"/studio/preview-candidates/{candidate_id}/decision",
            json={**request, "variation_label": conflicting_label},
        )
        assert conflicting.status_code == expected_status, conflicting.text
    contradictory = client.post(
        f"/studio/preview-candidates/{candidate_id}/decision",
        json={
            "created_by": "usr_studio",
            "decision": "discard",
            "expected_active_asset_id": "ast_selected",
        },
    )
    assert contradictory.status_code == 409, contradictory.text
    with Session() as db:
        durable = db.get(PreviewCandidateRecord, candidate_id)
        assert durable is not None
        assert durable.payload["resolved_variation_label"] == "Warm rose study"


def test_normalized_visual_authenticated_foreign_candidate_is_not_enumerable(
    studio_preview_client,
):
    client, _Session = studio_preview_client
    app.dependency_overrides[get_studio_visual_preview_generator] = (
        lambda: _generator([])
    )
    candidate_id = _preview(client).json()["candidate"]["candidate_id"]
    app.dependency_overrides[require_principal_boundary] = lambda: (
        AuthenticatedPrincipal(subject="usr_someone_else")
    )

    foreign = client.get(f"/studio/preview-candidates/{candidate_id}")
    assert foreign.status_code == 404, foreign.text
    foreign_image = client.get(
        f"/studio/preview-candidates/{candidate_id}/image"
    )
    assert foreign_image.status_code == 404, foreign_image.text


def test_normalized_visual_apply_rolls_back_job_credit_and_canonical_rows(
    studio_preview_client,
    monkeypatch,
):
    client, Session = studio_preview_client
    app.dependency_overrides[get_studio_visual_preview_generator] = (
        lambda: _generator([])
    )
    job_id = _running_refine_job(client)
    candidate_id = _preview(client, studio_job_id=job_id).json()["candidate"][
        "candidate_id"
    ]
    before = _counts(Session)
    monkeypatch.setattr(
        preview_seam,
        "remove_studio_visual_candidate",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("resolution failed")
        ),
    )

    with pytest.raises(RuntimeError, match="resolution failed"):
        client.post(
            f"/studio/preview-candidates/{candidate_id}/decision",
            json={
                "created_by": "usr_studio",
                "decision": "apply",
                "expected_active_asset_id": "ast_selected",
            },
        )
    assert _counts(Session) == before
    with Session() as db:
        durable = db.get(PreviewCandidateRecord, candidate_id)
        job = db.get(StudioJobRecord, job_id)
        assert durable is not None and durable.status == "reviewing"
        assert durable.terminal_asset_id is None
        assert job is not None and job.status == "reviewing"
        assert (job.completed_outputs, job.charged_outputs) == (0, 0)


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


def test_continuation_prompts_keep_raw_order_and_exact_apply_discard_outcomes(
    studio_preview_client,
):
    client, Session = studio_preview_client
    app.dependency_overrides[get_studio_visual_preview_generator] = (
        lambda: _generator([])
    )
    internal_suffix = (
        "PRESERVE EVERY UNMARKED PIXEL AND KEEP ALL OTHER DETAILS FIXED."
    )
    first_words = "Mirror the necklace links from left to right."
    first_job_id = _running_refine_job(client)
    first = _preview(
        client,
        studio_job_id=first_job_id,
        instruction=f"{first_words} {internal_suffix}",
        raw_user_instruction=first_words,
        input_mode="symmetry",
    )
    assert first.status_code == 201, first.text
    first_body = first.json()
    first_prompt = first_body["continuation_prompt"]
    assert first_prompt["sequence"] == 1
    assert first_prompt["prompt"] == first_words
    assert internal_suffix not in first_prompt["prompt"]
    assert first_prompt["state"] == "preview_ready"

    first_discard = client.post(
        f"/studio/image-runs/{first_body['image_run_id']}/visual-candidates/"
        f"{first_body['candidate']['candidate_id']}/discard",
        json={
            "created_by": "usr_studio",
            "expected_active_asset_id": "ast_selected",
        },
    )
    assert first_discard.status_code == 200, first_discard.text

    second_words = "Change the center stone to a deep green tsavorite."
    second_job_id = _running_refine_job(client)
    second = _preview(
        client,
        studio_job_id=second_job_id,
        instruction=f"{second_words} {internal_suffix}",
        raw_user_instruction=second_words,
        input_mode="describe",
    )
    assert second.status_code == 201, second.text
    second_body = second.json()
    second_prompt = second_body["continuation_prompt"]
    assert second_prompt["sequence"] == 2
    assert second_prompt["source_asset_id"] == "ast_selected"

    second_accept = client.post(
        f"/studio/image-runs/{second_body['image_run_id']}/visual-candidates/"
        f"{second_body['candidate']['candidate_id']}/accept",
        json={
            "created_by": "usr_studio",
            "expected_active_asset_id": "ast_selected",
        },
    )
    assert second_accept.status_code == 201, second_accept.text
    applied_asset_id = second_accept.json()["new_asset_id"]

    history = client.get(
        "/studio/projects/ast_selected/continuation-prompts"
    )
    assert history.status_code == 200, history.text
    prompts = history.json()["prompts"]
    assert [item["sequence"] for item in prompts] == [1, 2]
    assert [item["prompt"] for item in prompts] == [first_words, second_words]
    assert [item["state"] for item in prompts] == ["discarded", "applied"]
    assert prompts[0]["applied_asset_id"] is None
    assert prompts[1]["applied_asset_id"] == applied_asset_id
    assert all(internal_suffix not in item["prompt"] for item in prompts)

    with Session() as db:
        records = list(db.scalars(select(
            StudioContinuationPromptRecord
        ).order_by(StudioContinuationPromptRecord.sequence)))
        assert [record.source_asset_id for record in records] == [
            "ast_selected", "ast_selected",
        ]
        assert all(
            record.source_sha256 == hashlib.sha256(SOURCE).hexdigest()
            for record in records
        )
        first_job = db.get(StudioJobRecord, first_job_id)
        second_job = db.get(StudioJobRecord, second_job_id)
        assert first_job is not None and first_job.status == "canceled"
        assert (first_job.completed_outputs, first_job.charged_outputs) == (0, 0)
        assert second_job is not None and second_job.status == "succeeded"
        assert (second_job.completed_outputs, second_job.charged_outputs) == (1, 1)
        project = db.get(Project, "ast_selected")
        child = db.get(ImageAsset, applied_asset_id)
        revision = db.scalar(select(ProjectRevisionRecord).where(
            ProjectRevisionRecord.asset_id == applied_asset_id,
        ))
        assert project is not None
        assert project.selected_candidate_asset_id == applied_asset_id
        assert child is not None and child.parent_asset_id == "ast_selected"
        assert child.instruction == second_words
        assert revision is not None
        assert revision.raw_intent["continuation_prompt_id"] == records[1].id
        assert revision.raw_intent["instruction"] == second_words
        assert internal_suffix not in revision.raw_intent["instruction"]
        compiled = (
            f"OVERALL DESIGNER REQUEST: {second_words} {internal_suffix}"
        )
        assert records[1].intent["compiled_instruction"] == compiled
        assert records[1].intent["compiled_instruction_sha256"] == (
            hashlib.sha256(compiled.encode("utf-8")).hexdigest()
        )
        assert revision.interpretation["compiled_instruction_sha256"] == (
            hashlib.sha256(compiled.encode("utf-8")).hexdigest()
        )


def test_raw_refine_instruction_mismatch_is_rejected_before_job_reservation(
    studio_preview_client,
):
    client, Session = studio_preview_client
    calls = 0

    def generate(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("provider must not run for an unbound instruction")

    app.dependency_overrides[get_studio_visual_preview_generator] = (
        lambda: generate
    )
    job_id = _running_refine_job(client)
    rejected = _preview(
        client,
        studio_job_id=job_id,
        instruction="Make the center stone blue.",
        raw_user_instruction="Remove the necklace chain.",
    )
    assert rejected.status_code == 422, rejected.text
    assert calls == 0
    with Session() as db:
        job = db.get(StudioJobRecord, job_id)
        assert job is not None and job.status == "running"
        assert (job.completed_outputs, job.charged_outputs) == (0, 0)
        assert db.scalar(select(func.count()).select_from(ImageRun)) == 0
        assert db.scalar(select(func.count()).select_from(
            StudioContinuationPromptRecord
        )) == 0


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
    raw_words = "Make the chain links slightly narrower."
    failed = _preview(
        client,
        studio_job_id=job_id,
        instruction=(
            f"{raw_words} PRESERVE EVERY OTHER ACCEPTED DESIGN DETAIL."
        ),
        raw_user_instruction=raw_words,
        input_mode="point",
    )
    assert failed.status_code == 502, failed.text
    assert failed.json()["code"] == "image_provider_failed"
    history = client.get(
        "/studio/projects/ast_selected/continuation-prompts"
    )
    assert history.status_code == 200, history.text
    prompt = history.json()["prompts"][0]
    assert prompt["prompt"] == raw_words
    assert prompt["input_mode"] == "point"
    assert prompt["state"] == "failed"
    assert prompt["outcome_code"] == "image_provider_failed"
    assert "PRESERVE EVERY OTHER" not in prompt["prompt"]
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
        persisted_prompt = db.scalar(select(StudioContinuationPromptRecord))
        assert persisted_prompt is not None
        assert persisted_prompt.prompt == raw_words
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


@pytest.mark.parametrize(
    ("contract_failure", "expected_status", "expected_code"),
    [
        ("unreviewable_result", 422, "visual_preview_failed_quality"),
        ("wrong_source", 500, "visual_preview_lineage_incomplete"),
    ],
)
def test_visual_result_contract_failure_is_evidence_only_and_zero_charge(
    studio_preview_client,
    contract_failure,
    expected_status,
    expected_code,
):
    """A malformed generator return cannot become a preview or billable work.

    The normal image-agent raises hard QA failures. This regression covers a
    provider adapter or future orchestrator that instead returns an internally
    inconsistent result, so the HTTP seam remains fail-closed independently.
    """

    client, Session = studio_preview_client

    def malformed_result(source, instruction, scope, mask, variant):
        result = _generator([])(source, instruction, scope, mask, variant)
        if contract_failure == "wrong_source":
            return result.model_copy(update={
                "plan": result.plan.model_copy(update={
                    "source_hash": hashlib.sha256(b"another revision").hexdigest(),
                }),
            })
        failed_quality = ImageQualityReport(
            verdict=QualityVerdict.FAIL,
            checks=(QualityCheck(
                code="source_design_preserved",
                passed=False,
                severity=CheckSeverity.HARD,
                message="the result drifted from the source design",
            ),),
            score=10,
        )
        return result.model_copy(update={
            "quality": failed_quality,
            "accepted": False,
            "review_required": False,
        })

    app.dependency_overrides[get_studio_visual_preview_generator] = (
        lambda: malformed_result
    )
    job_id = _running_refine_job(client)
    before = _counts(Session)

    failed = _preview(client, studio_job_id=job_id)

    assert failed.status_code == expected_status, failed.text
    assert failed.json()["code"] == expected_code
    with Session() as db:
        job = db.get(StudioJobRecord, job_id)
        runs = list(db.scalars(select(ImageRun)))
        assert job is not None and job.status == "failed"
        assert job.error_code == expected_code
        assert job.reservation_kind is None
        assert (job.completed_outputs, job.charged_outputs) == (0, 0)
        assert len(runs) == 1 and runs[0].status == "failed"
        assert runs[0].accepted_asset_id is None
        assert db.scalar(select(func.count()).select_from(
            PreviewCandidateRecord)) == 0
        assert db.scalar(select(func.count()).select_from(
            ProjectRevisionRecord)) == before["records"]
        assert db.scalar(select(func.count()).select_from(
            ImageAsset)) == before["assets"]


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


def test_visual_decision_lock_requires_active_source_unless_branching_history(
    studio_preview_client,
):
    client, Session = studio_preview_client
    app.dependency_overrides[get_studio_visual_preview_generator] = (
        lambda: _generator([])
    )
    preview = _preview(client).json()
    candidate_id = preview["candidate"]["candidate_id"]
    run_id = preview["image_run_id"]
    _advance_active_visual(Session)

    with Session() as db:
        with pytest.raises(
            StudioVisualCandidateUnavailable,
            match="no longer matches the exact selected source",
        ):
            lock_studio_visual_candidate_for_decision(
                db,
                run_id,
                candidate_id,
                owner="usr_studio",
            )

        candidate, record = lock_studio_visual_candidate_for_decision(
            db,
            run_id,
            candidate_id,
            owner="usr_studio",
            require_active=False,
        )

    assert candidate.source_asset_id == "ast_selected"
    assert candidate.expected_selected_candidate_asset_id == "ast_selected"
    assert candidate.source_hash == hashlib.sha256(SOURCE).hexdigest()
    assert candidate.output_hash == hashlib.sha256(CANDIDATE).hexdigest()
    assert record.status == "reviewing"
    with Session() as db:
        project = db.get(Project, "ast_selected")
        assert project is not None
        assert project.selected_candidate_asset_id == "ast_newer"
        assert db.scalar(select(func.count()).select_from(ImageRunReview)) == 0
        assert db.scalar(select(func.count()).select_from(
            ProjectRevisionRecord)) == 0


@pytest.mark.parametrize(
    "tamper",
    ["source_hash", "candidate_bytes", "missing_run_source"],
)
def test_historical_visual_decision_lock_fails_closed_on_lineage_tampering(
    studio_preview_client,
    tamper,
):
    client, Session = studio_preview_client
    app.dependency_overrides[get_studio_visual_preview_generator] = (
        lambda: _generator([])
    )
    job_id = _running_refine_job(client)
    preview = _preview(client, studio_job_id=job_id).json()
    candidate_id = preview["candidate"]["candidate_id"]
    run_id = preview["image_run_id"]
    _advance_active_visual(Session)

    with Session() as db:
        record = db.get(PreviewCandidateRecord, candidate_id)
        run = db.get(ImageRun, run_id)
        assert record is not None and run is not None
        if tamper == "source_hash":
            record.source_sha256 = "0" * 64
        elif tamper == "candidate_bytes":
            record.image = b"tampered candidate bytes"
        else:
            # Simulate corruption outside the guarded ORM write path so this
            # test can still exercise the downstream fail-closed reader.
            db.execute(
                update(ImageRun)
                .where(ImageRun.id == run.id)
                .values(source_asset_id=None)
            )
        db.commit()

    with Session() as db:
        with pytest.raises(
            StudioVisualCandidateUnavailable,
            match="no longer matches the exact selected source",
        ):
            lock_studio_visual_candidate_for_decision(
                db,
                run_id,
                candidate_id,
                owner="usr_studio",
                require_active=False,
            )

        job = db.get(StudioJobRecord, job_id)
        candidate = db.get(PreviewCandidateRecord, candidate_id)
        project = db.get(Project, "ast_selected")
        assert job is not None and candidate is not None and project is not None
        assert job.completed_outputs == 0
        assert job.charged_outputs == 0
        assert candidate.status == "reviewing"
        assert candidate.terminal_asset_id is None
        assert project.selected_candidate_asset_id == "ast_newer"
        assert db.scalar(select(func.count()).select_from(ImageRunReview)) == 0
        assert db.scalar(select(func.count()).select_from(
            ProjectRevisionRecord)) == 0


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
    _advance_active_visual(Session)

    saved = client.post(
        f"/studio/image-runs/{run_id}/visual-candidates/{candidate_id}/"
        "save-as-variation",
        json={"created_by": "usr_studio", "label": "Warm metal"},
    )
    assert saved.status_code == 201, saved.text
    body = saved.json()
    assert body["status"] == "saved_as_variation"
    assert body["source_project_id"] == "ast_selected"
    assert body["source_asset_id"] == "ast_selected"
    sibling_id = body["project"]["root_id"]
    with Session() as db:
        original = db.get(Project, "ast_selected")
        sibling = db.get(Project, sibling_id)
        asset = db.get(ImageAsset, sibling_id)
        affinity = db.get(ImageAssetProviderAffinity, sibling_id)
        durable = db.get(PreviewCandidateRecord, candidate_id)
        review = db.scalar(select(ImageRunReview).where(
            ImageRunReview.run_id == run_id
        ))
        assert original is not None and sibling is not None and asset is not None
        assert affinity is not None
        assert (affinity.provider, affinity.model) == ("xai", "grok_direct")
        assert original.selected_candidate_asset_id == "ast_newer"
        assert sibling.family_id == original.family_id
        assert sibling.variation_label == "Warm metal"
        assert sibling.branched_from_project_root_id == original.root_id
        assert sibling.branched_from_asset_id == "ast_selected"
        assert bytes(asset.image) == CANDIDATE
        assert asset.design_id is None and asset.design_version is None
        assert durable is not None
        assert durable.status == "saved_as_variation"
        assert durable.terminal_asset_id == sibling_id
        assert durable.payload["resolved_variation_label"] == "Warm metal"
        assert review is not None and review.accepted_asset_id == sibling_id
    normalized_replay = client.post(
        f"/studio/preview-candidates/{candidate_id}/decision",
        json={
            "created_by": "usr_studio",
            "decision": "save_as_variation",
            "expected_active_asset_id": "ast_selected",
            "variation_label": "Warm metal",
        },
    )
    assert normalized_replay.status_code == 200, normalized_replay.text
    assert normalized_replay.json()["result_project_id"] == sibling_id
    normalized_conflict = client.post(
        f"/studio/preview-candidates/{candidate_id}/decision",
        json={
            "created_by": "usr_studio",
            "decision": "save_as_variation",
            "expected_active_asset_id": "ast_selected",
            "variation_label": "Duplicate",
        },
    )
    assert normalized_conflict.status_code == 409, normalized_conflict.text
    assert normalized_conflict.json()["code"] == (
        "preview_candidate_variation_conflict"
    )
    exact_legacy_replay = client.post(
        f"/studio/image-runs/{run_id}/visual-candidates/{candidate_id}/"
        "save-as-variation",
        json={"created_by": "usr_studio", "label": "Warm metal"},
    )
    assert exact_legacy_replay.status_code == 201, exact_legacy_replay.text
    assert exact_legacy_replay.json()["project"]["root_id"] == sibling_id


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
        # Simulate an out-of-band database rewrite; normal ORM writes are
        # rejected by the ImageRun append-only guard.
        db.execute(
            update(ImageRun)
            .where(ImageRun.id == run.id)
            .values(project_root_id="ast_different_project")
        )
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


def test_marked_region_rejects_bilateral_repair_before_provider(
    studio_preview_client,
):
    client, _Session = studio_preview_client
    calls: list[dict] = []
    app.dependency_overrides[get_studio_visual_preview_generator] = (
        lambda: _generator(calls)
    )

    response = _preview(
        client,
        scope="marked_region",
        mask_base64=base64.b64encode(SOURCE).decode("ascii"),
        instruction="Make the left and right sides symmetrical.",
    )

    assert response.status_code == 422, response.text
    assert "use the Symmetry tool" in response.text
    assert calls == []


def test_visual_generator_rejects_marked_symmetry_without_building_plan():
    with pytest.raises(ImagePlanValidationError) as error:
        studio_api.generate_studio_visual_preview(
            SOURCE,
            "Mirror the corresponding elements on both sides.",
            "marked_region",
            SOURCE,
            0,
        )

    assert error.value.code == "marked_symmetry_scope_conflict"


def test_marked_region_plan_authorizes_only_explicit_local_geometry(monkeypatch):
    plans = []
    sentinel = object()

    class FakeAgent:
        def __init__(self, *_args, **_kwargs):
            pass

        def run(self, plan, *, source_image, mask_bytes):
            plans.append(plan)
            assert source_image == SOURCE
            assert mask_bytes == SOURCE
            return sentinel

    monkeypatch.setattr(studio_api, "JewelryImageAgent", FakeAgent)
    monkeypatch.setattr(
        studio_api,
        "RoutedImageProvider",
        lambda **_kwargs: object(),
    )

    result = studio_api.generate_studio_visual_preview(
        SOURCE,
        (
            "OVERALL DESIGNER REQUEST: Keep the band unchanged. "
            "1. Inside 'left stone': Make the stone pale blue. "
            "2. Inside 'right prongs': Make the prongs finer."
        ),
        "marked_region",
        SOURCE,
        0,
    )

    assert result is sentinel
    assert len(plans) == 1
    plan = plans[0]
    assert plan.normalized_intent["localization"]["mode"] == (
        "designer_marked_pre_spec_region"
    )
    assert plan.normalized_intent["localization"][
        "authorized_change_domains"
    ] == ["appearance", "local_geometry"]
    assert plan.normalized_intent["localization"]["marked_region_count"] == 2
    assert plan.region_description == "designer-marked edit regions"
    assert "local color, surface, finish, or visible contour" in plan.intent
    assert "Make the stone pale blue" in plan.intent
    assert "Make the prongs finer" in plan.intent
    assert "all unrequested construction and setting details" in plan.frozen
    assert "all construction and setting details" not in plan.frozen
    assert "no unrelated drift" in plan.expected_output


def test_preservation_language_does_not_authorize_local_geometry(monkeypatch):
    plans = []

    class FakeAgent:
        def __init__(self, *_args, **_kwargs):
            pass

        def run(self, plan, *, source_image, mask_bytes):
            plans.append(plan)
            return object()

    monkeypatch.setattr(studio_api, "JewelryImageAgent", FakeAgent)
    monkeypatch.setattr(
        studio_api,
        "RoutedImageProvider",
        lambda **_kwargs: object(),
    )

    studio_api.generate_studio_visual_preview(
        SOURCE,
        "1. Inside 'right prongs': Keep the prongs unchanged.",
        "marked_region",
        SOURCE,
        0,
    )

    localization = plans[0].normalized_intent["localization"]
    assert localization["authorized_change_domains"] == ["appearance"]
    assert localization["marked_region_count"] == 1


def test_prong_color_request_does_not_authorize_geometry():
    domains, count = studio_api._marked_region_contract(
        "1. Inside 'right prongs': Change the prongs to pale blue."
    )

    assert domains == ("appearance",)
    assert count == 1


def test_described_plan_allows_named_changes_and_freezes_unmentioned(monkeypatch):
    plans = []

    class FakeAgent:
        def __init__(self, *_args, **_kwargs):
            pass

        def run(self, plan, *, source_image, mask_bytes):
            plans.append(plan)
            return object()

    monkeypatch.setattr(studio_api, "JewelryImageAgent", FakeAgent)
    monkeypatch.setattr(
        studio_api,
        "RoutedImageProvider",
        lambda **_kwargs: object(),
    )

    studio_api.generate_studio_visual_preview(
        SOURCE,
        (
            "Change the six ruby surrounds to alternating diamond and "
            "tsavorite leaves, and make the gold links satin."
        ),
        "appearance",
        None,
        0,
    )

    assert len(plans) == 1
    assert "PRE-SPEC DESCRIBED VISUAL REFINEMENT" in plans[0].intent
    assert "Apply every explicitly requested visible change together" in (
        plans[0].intent
    )
    assert "alternating diamond and tsavorite leaves" in plans[0].intent
    assert "all unmentioned jewelry geometry and silhouette" in plans[0].frozen
    assert "all unmentioned topology, component count, proportions, and placement" in (
        plans[0].frozen
    )
    assert any(
        "all unmentioned stones, settings, metal and pave treatments" in item
        for item in plans[0].frozen
    )
    assert JEWELRY_SYMMETRY_CONTRACT in plans[0].intent


def test_described_six_leaf_ruby_pattern_authorizes_exact_requested_delta(
    monkeypatch,
):
    plans = []

    class FakeAgent:
        def __init__(self, *_args, **_kwargs):
            pass

        def run(self, plan, *, source_image, mask_bytes):
            plans.append(plan)
            return object()

    monkeypatch.setattr(studio_api, "JewelryImageAgent", FakeAgent)
    monkeypatch.setattr(
        studio_api,
        "RoutedImageProvider",
        lambda **_kwargs: object(),
    )

    studio_api.generate_studio_visual_preview(
        SOURCE,
        (
            "Surrounding the ruby is 6 leaves half are white diamonds and "
            "other is tsavorite, so its a pattern."
        ),
        "appearance",
        None,
        0,
    )

    assert len(plans) == 1
    plan = plans[0]
    assert "PRE-SPEC DESCRIBED VISUAL REFINEMENT" in plan.intent
    assert SIX_LEAF_RUBY_PATTERN_CONTRACT in plan.intent
    assert "three leaves use white-diamond treatment" in plan.intent
    assert "three leaves use tsavorite treatment" in plan.intent
    assert any(
        "all unmentioned topology, component count" in item
        for item in plan.frozen
    )
    assert all(
        "exact topology, component count" not in item
        for item in plan.frozen
    )


def test_sequential_chain_edit_reaches_plan_with_prior_leaf_pattern_locked(
    monkeypatch,
):
    plans = []

    class FakeAgent:
        def __init__(self, *_args, **_kwargs):
            pass

        def run(self, plan, *, source_image, mask_bytes):
            plans.append(plan)
            return object()

    monkeypatch.setattr(studio_api, "JewelryImageAgent", FakeAgent)
    monkeypatch.setattr(
        studio_api,
        "RoutedImageProvider",
        lambda **_kwargs: object(),
    )

    instruction = with_sequential_jewelry_edit_contract(
        "Make the chain white-gold intertwined and braided.",
        accepted_instructions=(
            "Ruby on a gold necklace.",
            (
                "Add leaf design surrounding the ruby, 3 leaves each side; "
                "small white diamonds and the other half green tsavorites."
            ),
        ),
    )
    studio_api.generate_studio_visual_preview(
        SOURCE,
        instruction,
        "appearance",
        None,
        0,
    )

    assert len(plans) == 1
    intent = plans[0].intent
    assert SEQUENTIAL_JEWELRY_EDIT_CONTRACT in intent
    assert SMALL_DIAMOND_VISUAL_CONTRACT in intent
    assert BRAIDED_WHITE_GOLD_CHAIN_CONTRACT in intent
    assert SIX_LEAF_RUBY_PATTERN_CONTRACT in intent
    assert "three-per-side bilateral arrangement" in intent
    assert "all unmentioned stones, settings, metal" in " ".join(
        plans[0].frozen
    )


def test_endpoint_supplies_accepted_visual_history_without_persisting_contracts(
    studio_preview_client,
):
    client, Session = studio_preview_client
    calls: list[dict] = []
    app.dependency_overrides[get_studio_visual_preview_generator] = (
        lambda: _generator(calls)
    )
    leaf_instruction = (
        "Add leaf design surrounding the ruby, 3 leaves each side; small "
        "white diamonds and the other half green tsavorites."
    )
    with Session() as db:
        leaf = ImageAsset(
            id="ast_leaf",
            root_id="ast_selected",
            parent_asset_id="ast_selected",
            design_version=None,
            capability="GLOBAL_RESTYLE",
            source_kind="photograph",
            instruction=leaf_instruction,
            image=_png((190, 30, 45)),
            media_type="image/png",
            created_by="usr_studio",
        )
        db.add(leaf)
        db.flush()
        db.get(Project, "ast_selected").selected_candidate_asset_id = leaf.id
        db.commit()

    chain_instruction = "Make the chain white-gold intertwined and braided."
    response = _preview(
        client,
        expected_active_asset_id="ast_leaf",
        instruction=chain_instruction,
    )

    assert response.status_code == 201, response.text
    provider_instruction = calls[0]["instruction"]
    assert "ACCEPTED SOURCE CONTEXT" in provider_instruction
    assert "Initial direction" in provider_instruction
    assert leaf_instruction in provider_instruction
    assert chain_instruction in provider_instruction
    assert BRAIDED_WHITE_GOLD_CHAIN_CONTRACT in provider_instruction
    with Session() as db:
        record = db.scalar(select(PreviewCandidateRecord).where(
            PreviewCandidateRecord.id
            == response.json()["candidate"]["candidate_id"],
        ))
        assert record is not None
        assert record.payload["requested_change"] == (
            f"OVERALL DESIGNER REQUEST: {chain_instruction}"
        )
        assert "ACCEPTED SOURCE CONTEXT" not in record.payload[
            "requested_change"
        ]


def test_explicit_symmetry_repair_binds_hard_gate_and_preserves_center(monkeypatch):
    plans = []

    class FakeAgent:
        def __init__(self, *_args, **_kwargs):
            pass

        def run(self, plan, *, source_image, mask_bytes):
            plans.append(plan)
            return object()

    monkeypatch.setattr(studio_api, "JewelryImageAgent", FakeAgent)
    monkeypatch.setattr(
        studio_api,
        "RoutedImageProvider",
        lambda **_kwargs: object(),
    )

    studio_api.generate_studio_visual_preview(
        SOURCE,
        (
            "Make the left and right sides symmetrical around the centerline. "
            "Mirror corresponding jewelry elements link by link."
        ),
        "appearance",
        None,
        0,
    )

    assert len(plans) == 1
    plan = plans[0]
    assert JEWELRY_SYMMETRY_CONTRACT in plan.intent
    assert JEWELRY_SYMMETRY_REPAIR_CONTRACT in plan.intent
    assert any("exact center element" in item for item in plan.frozen)
    assert any("camera, crop, scale" in item for item in plan.frozen)
    assert "matching corresponding left/right jewelry elements" in (
        plan.expected_output
    )


def test_multiple_marked_changes_reach_one_temporary_preview_without_history(
    studio_preview_client,
):
    client, Session = studio_preview_client
    calls: list[dict] = []
    app.dependency_overrides[get_studio_visual_preview_generator] = (
        lambda: _generator(calls)
    )
    marked = Image.open(io.BytesIO(SOURCE)).convert("RGB")
    draw = ImageDraw.Draw(marked)
    draw.rectangle((4, 4, 14, 14), outline=(255, 0, 0), width=3)
    draw.rectangle((30, 30, 42, 42), outline=(255, 0, 0), width=3)
    output = io.BytesIO()
    marked.save(output, format="PNG")
    with Session() as db:
        db.add(ImageAsset(
            id="ast_multi_markup",
            root_id="ast_selected",
            parent_asset_id="ast_selected",
            design_version=None,
            capability="MARKUP_NOTES",
            image=output.getvalue(),
            media_type="image/png",
            created_by="usr_studio",
        ))
        db.commit()
    before = _counts(Session)

    response = _preview(
        client,
        scope="marked_region",
        markup_asset_id="ast_multi_markup",
        instruction="Keep the ring identity and camera unchanged.",
        annotations=[
            {
                "region_description": "left shoulder",
                "change_instruction": "make the surface satin",
            },
            {
                "region_description": "center stone",
                "change_instruction": "shift the visible color toward teal",
            },
        ],
    )

    assert response.status_code == 201, response.text
    assert len(calls) == 1
    assert calls[0]["mask"] is not None
    assert calls[0]["scope"] == "marked_region"
    assert "OVERALL DESIGNER REQUEST" in calls[0]["instruction"]
    assert "APPLY ALL MARKED CHANGES IN ONE PREVIEW" in calls[0]["instruction"]
    assert "Inside 'left shoulder': make the surface satin" in calls[0]["instruction"]
    assert "Inside 'center stone': shift the visible color toward teal" in calls[0]["instruction"]
    body = response.json()
    with Session() as db:
        project = db.get(Project, "ast_selected")
        candidate = db.get(
            PreviewCandidateRecord, body["candidate"]["candidate_id"])
        assert project is not None
        assert project.selected_candidate_asset_id == "ast_selected"
        assert candidate is not None and candidate.status == "reviewing"
        requested_change = candidate.payload["requested_change"]
        assert requested_change.count(
            "Keep the ring identity and camera unchanged."
        ) == 1
        assert requested_change.count("make the surface satin") == 1
        assert requested_change.count("shift the visible color toward teal") == 1
        assert requested_change.index("make the surface satin") < (
            requested_change.index("shift the visible color toward teal")
        )
    assert _counts(Session) == {**before, "runs": before["runs"] + 1}


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

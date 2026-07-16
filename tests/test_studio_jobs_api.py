"""Persistent Studio Activity lifecycle and outcome-based billing."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Iterator
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from conftest import EXAMPLE_SPEC

from facetta.db import (
    ApprovalChecklist,
    ApprovalResponse,
    Base,
    Design,
    DesignVersion,
    ImageAsset,
    ImageRun,
    ImageRunReview,
    PreviewCandidateRecord,
    Project,
    ProjectRevisionRecord,
    StudioJobRecord,
    StudioMarkupCandidateRecord,
    StudioPresentationCandidateRecord,
    StudioViewCandidateRecord,
    _migrate_studio_job_action_constraint,
    get_db,
    utcnow,
)
from facetta.main import app
from facetta.studio_jobs import (
    STUDIO_JOB_ACTIONS,
    StudioJobAccountingError,
    record_accepted_studio_job_outputs,
    settle_create_studio_job_selection,
)
from facetta.studio_view_candidates import reserve_studio_view_job


@pytest.fixture()
def client() -> Iterator[TestClient]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db() -> Iterator[Session]:
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as test_client:
            test_client.app_state["session_factory"] = sessions
            yield test_client
    finally:
        app.dependency_overrides.clear()


def _create(
    client: TestClient,
    *,
    owner: str = "usr_designer",
    outputs: int = 2,
    credits: int = 15,
    action_id: str = "create",
    lane: str = "fast_visual",
    active_design_id: str | None = None,
    source_revision_id: str | None = None,
) -> dict:
    response = client.post("/studio/jobs", json={
        "owner": owner,
        "action_id": action_id,
        "lane": lane,
        "active_design_id": active_design_id,
        "source_revision_id": source_revision_id,
        "requested_outputs": outputs,
        "credits_per_output": credits,
    })
    assert response.status_code == 201
    return response.json()


def _seed_project(
    client: TestClient,
    *,
    project_id: str,
    owner: str = "usr_designer",
    exact_specification: bool = False,
    factory_eligible: bool = False,
) -> tuple[str, str]:
    sessions = client.app_state["session_factory"]
    # A Project root_id is the primary chain root's exact asset id.
    asset_id = project_id
    design_id = f"dsn_{project_id}"
    now = utcnow()
    with sessions() as db:
        if exact_specification or factory_eligible:
            db.add(Design(id=design_id, created_by=owner))
        if exact_specification:
            spec = copy.deepcopy(EXAMPLE_SPEC)
            spec.update({
                "design_id": design_id,
                "version": 1,
                "created_by": owner,
            })
            db.add(DesignVersion(
                design_id=design_id,
                version=1,
                spec=spec,
                created_by=owner,
            ))
        db.add(ImageAsset(
            id=asset_id,
            root_id=asset_id,
            parent_asset_id=None,
            design_id=(
                design_id if exact_specification or factory_eligible else None
            ),
            design_version=1 if exact_specification else None,
            capability="JEWELRY_RENDER",
            image=b"studio-job-test-image",
            media_type="image/png",
            pinned_at=now if factory_eligible else None,
            created_by=owner,
            created_at=now,
        ))
        db.add(Project(
            root_id=project_id,
            owner=owner,
            title="Studio job context",
            tags=[],
            selected_candidate_asset_id=(
                asset_id if not exact_specification else None
            ),
        ))
        if factory_eligible:
            db.add(ApprovalChecklist(
                id=f"chk_{project_id}",
                asset_id=asset_id,
                design_id=design_id,
                design_version=1 if exact_specification else None,
                mode="explicit_pin",
                items=[{
                    "key": "stone",
                    "label": "Stone",
                    "fact": "round center stone",
                    "section": "center_stone",
                }],
                created_by=owner,
            ))
            db.add(ApprovalResponse(
                checklist_id=f"chk_{project_id}",
                item_key="stone",
                approved=True,
                created_by=owner,
            ))
        db.commit()
    return project_id, asset_id


def _transition(
    client: TestClient,
    job_id: str,
    status: str,
    progress: float,
    **extra,
):
    return client.patch(f"/studio/jobs/{job_id}", json={
        "owner": "usr_designer",
        "status": status,
        "progress": progress,
        **extra,
    })


def _mark_job_reviewing_from_candidate(
    client: TestClient,
    job_id: str,
    *,
    active_design_id: str | None = None,
) -> None:
    """Model the server-owned candidate reservation used by focused API tests."""

    sessions = client.app_state["session_factory"]
    with sessions() as db:
        job = db.get(StudioJobRecord, job_id)
        assert job is not None and job.status == "running"
        if active_design_id is not None:
            job.active_design_id = active_design_id
        job.status = "reviewing"
        job.progress = max(job.progress, 0.9)
        job.updated_at = utcnow()
        db.commit()


def _create_running_candidate_job(
    client: TestClient,
    action_id: str,
) -> dict:
    project_id = None
    source_id = None
    if action_id != "create":
        project_id, source_id = _seed_project(
            client,
            project_id=f"project_{action_id}_public_lifecycle",
            exact_specification=action_id == "views",
        )
    definition = STUDIO_JOB_ACTIONS[action_id]
    job = _create(
        client,
        outputs=definition.min_requested_outputs,
        action_id=action_id,
        lane=definition.lane,
        credits=definition.credits_per_output,
        active_design_id=project_id,
        source_revision_id=source_id,
    )
    running = _transition(client, job["job_id"], "running", 0.2)
    assert running.status_code == 200, running.text
    return running.json()


def _seed_expired_activity_candidate(
    client: TestClient,
    *,
    candidate_kind: str,
    owner: str = "usr_designer",
) -> tuple[str, type, str]:
    action_id = {
        "catalog_revision": "refine",
        "studio_visual": "refine",
        "markup": "refine",
        "view": "views",
        "presentation": "present",
    }[candidate_kind]
    suffix = f"{candidate_kind[:8]}_{owner[-5:]}"
    project_id, source_id = _seed_project(
        client,
        project_id=f"prj_exp_{suffix}",
        owner=owner,
        exact_specification=True,
    )
    definition = STUDIO_JOB_ACTIONS[action_id]
    job = _create(
        client,
        owner=owner,
        outputs=1,
        action_id=action_id,
        lane=definition.lane,
        credits=definition.credits_per_output,
        active_design_id=project_id,
        source_revision_id=source_id,
    )
    actor = "usr_designer" if owner == "usr_designer" else owner
    response = client.patch(f"/studio/jobs/{job['job_id']}", json={
        "owner": actor, "status": "running", "progress": 0.2,
    })
    assert response.status_code == 200
    now = utcnow()
    image = f"expired-{candidate_kind}".encode()
    source_hash = hashlib.sha256(b"studio-job-test-image").hexdigest()
    output_hash = hashlib.sha256(image).hexdigest()
    candidate_id = f"cand_exp_{suffix}"
    run_id = f"run_exp_{suffix}"
    sessions = client.app_state["session_factory"]
    with sessions() as db:
        stored_job = db.get(StudioJobRecord, job["job_id"])
        assert stored_job is not None and stored_job.status == "running"
        stored_job.status = "reviewing"
        stored_job.progress = 0.9
        stored_job.updated_at = now
        db.add(ImageRun(
            id=run_id,
            project_root_id=project_id,
            source_asset_id=source_id,
            operation="VISUAL_ONLY_EDIT",
            normalized_intent={},
            prompt_version="activity-expiry-test.v1",
            source_hash=source_hash,
            variant=0,
            status="review_required",
            created_by=owner,
        ))
        common = {
            "id": candidate_id,
            "image_run_id": run_id,
            "owner": owner,
            "project_root_id": project_id,
            "source_asset_id": source_id,
            "image": image,
            "media_type": "image/png",
            "status": "reviewing",
            "studio_job_id": job["job_id"],
            "created_at": now - timedelta(hours=2),
            "expires_at": now - timedelta(hours=1),
        }
        if candidate_kind in {"catalog_revision", "studio_visual"}:
            record = PreviewCandidateRecord(
                **common,
                expected_active_asset_id=source_id,
                expected_design_version=1,
                source_sha256=source_hash,
                output_sha256=output_hash,
                kind=candidate_kind,
                payload={},
            )
            model = PreviewCandidateRecord
        elif candidate_kind == "markup":
            record = StudioMarkupCandidateRecord(
                **common,
                expected_active_asset_id=source_id,
                design_version=1,
                source_sha256=source_hash,
                output_sha256=output_hash,
                source_spec_visual_hash="a" * 16,
                target_spec_visual_hash="b" * 16,
                operation="VISUAL_ONLY_EDIT",
                asset_capability="JEWELRY_RENDER",
                requested_change="Expire temporary markup",
                region_description="center stone",
                payload={},
            )
            model = StudioMarkupCandidateRecord
        elif candidate_kind == "view":
            record = StudioViewCandidateRecord(
                **common,
                source_sha256=source_hash,
                output_sha256=output_hash,
                spec_visual_hash="a" * 16,
                design_version=1,
                view="front",
                requested_change="Expire temporary view",
                qa={},
                routing={},
            )
            model = StudioViewCandidateRecord
        else:
            record = StudioPresentationCandidateRecord(
                **common,
                expected_active_asset_id=source_id,
                source_sha256=source_hash,
                output_sha256=output_hash,
                destination="marketing",
                capability="MARKETING_IMAGE",
                requested_change="Expire temporary presentation",
                preset="luxury_studio",
                framing="portrait",
                qa={},
                design_version=None,
            )
            model = StudioPresentationCandidateRecord
        db.add(record)
        db.commit()
    return job["job_id"], model, candidate_id


def test_fresh_schema_contains_persistent_studio_jobs():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    inspector = inspect(engine)

    assert StudioJobRecord.__tablename__ in inspector.get_table_names()
    assert {
        "owner", "action_id", "lane", "status", "progress",
        "requested_outputs", "credits_per_output", "completed_outputs",
        "charged_outputs", "accepted_output_sha256", "created_at", "updated_at",
    } <= {
        column["name"]
        for column in inspector.get_columns(StudioJobRecord.__tablename__)
    }


@pytest.mark.parametrize(
    ("status", "progress", "extra"),
    [
        ("running", 0.25, {}),
        ("reviewing", 0.8, {}),
        ("succeeded", 1, {"completed_outputs": 1}),
        ("failed", 1, {"error_code": "client_report"}),
        ("canceled", 1, {}),
    ],
)
def test_factory_job_lifecycle_is_owned_exclusively_by_backend_transaction(
    client, status, progress, extra,
):
    project_id, source_id = _seed_project(
        client,
        project_id="project_factory_lifecycle",
        exact_specification=True,
        factory_eligible=True,
    )
    definition = STUDIO_JOB_ACTIONS["factory"]
    job = _create(
        client,
        outputs=1,
        action_id="factory",
        lane=definition.lane,
        credits=definition.credits_per_output,
        active_design_id=project_id,
        source_revision_id=source_id,
    )
    job_id = job["job_id"]

    assert job["status"] == "queued"
    assert job["billing"] == {
        "requested_outputs": 1,
        "credits_per_output": 28,
        "estimated_credits": 28,
        "completed_outputs": 0,
        "charged_outputs": 0,
        "charged_credits": 0,
        "policy": (
            "Only requested outputs accepted by a backend decision are charged. "
            "Client completion reports, internal retries, and failed review "
            "attempts are not charged."
        ),
    }
    # Activity responses must not leak execution-provider vocabulary.
    serialized_keys = str((tuple(job), tuple(job["billing"]))).lower()
    assert "provider" not in serialized_keys
    assert "model" not in serialized_keys
    assert "attempt" not in serialized_keys

    blocked = _transition(client, job_id, status, progress, **extra)
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == (
        "this factory job is owned by its backend transaction; "
        "use its dedicated preparation action"
    )

    persisted = client.get(
        f"/studio/jobs/{job_id}", params={"owner": "usr_designer"},
    )
    assert persisted.status_code == 200
    unchanged = persisted.json()
    assert unchanged["status"] == "queued"
    assert unchanged["progress"] == 0
    assert unchanged["accepted_output_sha256"] is None
    assert unchanged["billing"]["completed_outputs"] == 0
    assert unchanged["billing"]["charged_outputs"] == 0


def test_instant_transaction_cannot_create_or_orphan_a_studio_job(client):
    project_id, source_id = _seed_project(
        client, project_id="project_vary_atomic_only",
    )
    definition = STUDIO_JOB_ACTIONS["vary"]
    response = client.post("/studio/jobs", json={
        "owner": "usr_designer",
        "action_id": "vary",
        "lane": definition.lane,
        "active_design_id": project_id,
        "source_revision_id": source_id,
        "requested_outputs": 1,
        "credits_per_output": definition.credits_per_output,
    })

    assert response.status_code == 422
    assert "atomic Studio transaction" in response.json()["detail"]
    listed = client.get("/studio/jobs", params={"owner": "usr_designer"})
    assert listed.status_code == 200
    assert listed.json() == {"jobs": []}


_CANDIDATE_DECISION_ACTION_IDS = tuple(
    action_id
    for action_id, definition in STUDIO_JOB_ACTIONS.items()
    if definition.review_authority == "candidate_decision"
)


@pytest.mark.parametrize("action_id", _CANDIDATE_DECISION_ACTION_IDS)
@pytest.mark.parametrize(
    ("reported_status", "extra"),
    [
        ("reviewing", {}),
        ("succeeded", {"completed_outputs": 1}),
        ("canceled", {}),
    ],
)
def test_public_patch_cannot_author_candidate_review_success_or_cancellation(
    client,
    action_id,
    reported_status,
    extra,
):
    running = _create_running_candidate_job(client, action_id)

    blocked = _transition(
        client,
        running["job_id"],
        reported_status,
        1 if reported_status in {"succeeded", "canceled"} else 0.8,
        **extra,
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == (
        f"public lifecycle reports for this {action_id} job may only set "
        "running or failed; use its dedicated candidate or cancellation action"
    )

    persisted = client.get(
        f"/studio/jobs/{running['job_id']}", params={"owner": "usr_designer"},
    )
    assert persisted.status_code == 200
    unchanged = persisted.json()
    assert unchanged["status"] == "running"
    assert unchanged["progress"] == 0.2
    assert unchanged["billing"]["completed_outputs"] == 0
    assert unchanged["billing"]["charged_outputs"] == 0


@pytest.mark.parametrize("action_id", _CANDIDATE_DECISION_ACTION_IDS)
def test_running_candidate_job_can_still_fail_before_review(client, action_id):
    running = _create_running_candidate_job(client, action_id)

    failed = _transition(
        client,
        running["job_id"],
        "failed",
        1,
        error_code="generation_unavailable",
    )

    assert failed.status_code == 200
    assert failed.json()["status"] == "failed"
    assert failed.json()["billing"]["completed_outputs"] == 0
    assert failed.json()["billing"]["charged_outputs"] == 0

    persisted = client.get(
        f"/studio/jobs/{running['job_id']}", params={"owner": "usr_designer"},
    ).json()
    assert persisted["status"] == "failed"
    assert persisted["billing"]["charged_outputs"] == 0


@pytest.mark.parametrize("action_id", _CANDIDATE_DECISION_ACTION_IDS)
def test_reviewing_candidate_job_rejects_generic_failure(client, action_id):
    running = _create_running_candidate_job(client, action_id)
    _mark_job_reviewing_from_candidate(
        client,
        running["job_id"],
        active_design_id=running.get("active_design_id"),
    )

    blocked = _transition(
        client,
        running["job_id"],
        "failed",
        1,
        error_code="late_generic_failure",
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == (
        f"this {action_id} job is owned by its candidate decision; "
        "use its Apply, Save, or Discard action"
    )

    persisted = client.get(
        f"/studio/jobs/{running['job_id']}",
        params={"owner": "usr_designer"},
    )
    assert persisted.status_code == 200
    unchanged = persisted.json()
    assert unchanged["status"] == "reviewing"
    assert unchanged["progress"] == 0.9
    assert unchanged["billing"]["completed_outputs"] == 0
    assert unchanged["billing"]["charged_outputs"] == 0


def test_activity_read_expires_orphaned_view_reservation_without_charge(client):
    project_id, source_id = _seed_project(
        client, project_id="project_views_orphaned", exact_specification=True,
    )
    definition = STUDIO_JOB_ACTIONS["views"]
    job = _create(
        client,
        outputs=1,
        action_id="views",
        lane=definition.lane,
        credits=definition.credits_per_output,
        active_design_id=project_id,
        source_revision_id=source_id,
    )
    assert _transition(client, job["job_id"], "running", 0.2).status_code == 200
    sessions = client.app_state["session_factory"]
    with sessions() as db:
        reserve_studio_view_job(
            db,
            job_id=job["job_id"],
            owner="usr_designer",
            project_root_id=project_id,
            source_asset_id=source_id,
        )
        record = db.get(StudioJobRecord, job["job_id"])
        assert record is not None
        record.updated_at = utcnow() - timedelta(minutes=16)
        db.commit()

    expired = client.get(
        f"/studio/jobs/{job['job_id']}", params={"owner": "usr_designer"},
    )
    assert expired.status_code == 200
    assert expired.json()["status"] == "failed"
    assert expired.json()["error_code"] == "view_reservation_expired"
    assert expired.json()["billing"]["completed_outputs"] == 0
    assert expired.json()["billing"]["charged_outputs"] == 0


@pytest.mark.parametrize("candidate_kind", [
    "catalog_revision",
    "studio_visual",
    "markup",
    "view",
    "presentation",
])
def test_activity_read_reconciles_expired_candidate_without_canonical_writes(
    client,
    candidate_kind,
):
    job_id, model, candidate_id = _seed_expired_activity_candidate(
        client, candidate_kind=candidate_kind,
    )
    sessions = client.app_state["session_factory"]
    with sessions() as db:
        before = {
            "assets": db.scalar(select(func.count()).select_from(ImageAsset)),
            "versions": db.scalar(select(func.count()).select_from(DesignVersion)),
            "revisions": db.scalar(
                select(func.count()).select_from(ProjectRevisionRecord)
            ),
            "reviews": db.scalar(
                select(func.count()).select_from(ImageRunReview)
            ),
        }

    reconciled = client.get(
        f"/studio/jobs/{job_id}", params={"owner": "usr_designer"},
    )
    assert reconciled.status_code == 200, reconciled.text
    assert reconciled.json()["status"] == "canceled"
    assert reconciled.json()["progress"] == 1
    assert reconciled.json()["billing"]["completed_outputs"] == 0
    assert reconciled.json()["billing"]["charged_outputs"] == 0
    assert reconciled.json()["billing"]["charged_credits"] == 0

    # Repeated reads are idempotent, and status-filtered Activity sees the
    # newly reconciled terminal truth instead of an unusable review action.
    repeated = client.get(
        f"/studio/jobs/{job_id}", params={"owner": "usr_designer"},
    )
    assert repeated.status_code == 200
    assert repeated.json() == reconciled.json()
    reviewing = client.get("/studio/jobs", params={
        "owner": "usr_designer", "status": "reviewing",
    })
    canceled = client.get("/studio/jobs", params={
        "owner": "usr_designer", "status": "canceled",
    })
    assert job_id not in {item["job_id"] for item in reviewing.json()["jobs"]}
    assert job_id in {item["job_id"] for item in canceled.json()["jobs"]}

    with sessions() as db:
        candidate = db.get(model, candidate_id)
        assert candidate is not None
        assert candidate.status == "expired"
        assert bytes(candidate.image) == b""
        assert candidate.resolved_at is not None
        assert {
            "assets": db.scalar(select(func.count()).select_from(ImageAsset)),
            "versions": db.scalar(select(func.count()).select_from(DesignVersion)),
            "revisions": db.scalar(
                select(func.count()).select_from(ProjectRevisionRecord)
            ),
            "reviews": db.scalar(
                select(func.count()).select_from(ImageRunReview)
            ),
        } == before


def test_activity_candidate_reconciliation_is_owner_scoped(client):
    job_id, model, candidate_id = _seed_expired_activity_candidate(
        client, candidate_kind="studio_visual", owner="usr_other",
    )
    mine = client.get("/studio/jobs", params={"owner": "usr_designer"})
    assert mine.status_code == 200
    assert job_id not in {item["job_id"] for item in mine.json()["jobs"]}

    sessions = client.app_state["session_factory"]
    with sessions() as db:
        candidate = db.get(model, candidate_id)
        job = db.get(StudioJobRecord, job_id)
        assert candidate is not None and candidate.status == "reviewing"
        assert job is not None and job.status == "reviewing"

    theirs = client.get(
        f"/studio/jobs/{job_id}", params={"owner": "usr_other"},
    )
    assert theirs.status_code == 200
    assert theirs.json()["status"] == "canceled"


def test_owner_filtering_and_cross_owner_reads_fail_closed(client):
    mine = _create(client, owner="usr_designer")
    other = _create(client, owner="usr_other")

    response = client.get("/studio/jobs", params={"owner": "usr_designer"})
    assert response.status_code == 200
    assert [job["job_id"] for job in response.json()["jobs"]] == [mine["job_id"]]

    hidden = client.get(
        f"/studio/jobs/{other['job_id']}",
        params={"owner": "usr_designer"},
    )
    assert hidden.status_code == 404
    missing_owner = client.get("/studio/jobs")
    assert missing_owner.status_code == 422


def test_create_rejects_client_authored_lane_or_price(client):
    payload = {
        "owner": "usr_designer",
        "action_id": "create",
        "lane": "fast_visual",
        "active_design_id": None,
        "source_revision_id": None,
        "requested_outputs": 1,
        "credits_per_output": 0,
    }
    free = client.post("/studio/jobs", json=payload)
    assert free.status_code == 422
    assert "credits_per_output" in free.json()["detail"]

    wrong_lane = client.post("/studio/jobs", json={
        **payload,
        "lane": "instant",
        "credits_per_output": 15,
    })
    assert wrong_lane.status_code == 422
    assert "lane" in wrong_lane.json()["detail"]


def test_server_registry_is_canonical_for_every_studio_action(client):
    pre_spec = _seed_project(client, project_id="project_prespec")
    exact = _seed_project(
        client, project_id="project_exact", exact_specification=True,
    )
    eligible = _seed_project(
        client,
        project_id="project_factory",
        exact_specification=True,
        factory_eligible=True,
    )
    for action_id, definition in STUDIO_JOB_ACTIONS.items():
        if definition.execution_mode == "instant_transaction":
            continue
        context = (
            eligible if action_id == "factory"
            else exact if "exact_specification" in definition.context_requirements
            else pre_spec if definition.context_requirements
            else (None, None)
        )
        created = _create(
            client,
            outputs=definition.min_requested_outputs,
            action_id=action_id,
            lane=definition.lane,
            credits=definition.credits_per_output,
            active_design_id=context[0],
            source_revision_id=context[1],
        )
        assert created["lane"] == definition.lane
        assert created["billing"]["credits_per_output"] == (
            definition.credits_per_output
        )


@pytest.mark.parametrize("action_id", ["create", "present"])
@pytest.mark.parametrize("outputs", [1, 2, 3, 4])
def test_multi_output_actions_accept_their_canonical_range(
    client,
    action_id,
    outputs,
):
    definition = STUDIO_JOB_ACTIONS[action_id]
    project_id = None
    source_id = None
    if action_id == "present":
        project_id, source_id = _seed_project(
            client,
            project_id=f"project_present_{outputs}",
        )

    created = _create(
        client,
        outputs=outputs,
        action_id=action_id,
        lane=definition.lane,
        credits=definition.credits_per_output,
        active_design_id=project_id,
        source_revision_id=source_id,
    )

    assert created["billing"]["requested_outputs"] == outputs
    assert created["billing"]["estimated_credits"] == (
        outputs * definition.credits_per_output
    )


def test_angles_action_requires_exactly_three_requested_outputs(client):
    definition = STUDIO_JOB_ACTIONS["angles"]
    project_id, source_id = _seed_project(
        client, project_id="project_angles_three_outputs",
    )
    accepted = _create(
        client,
        outputs=3,
        action_id="angles",
        lane=definition.lane,
        credits=definition.credits_per_output,
        active_design_id=project_id,
        source_revision_id=source_id,
    )
    assert accepted["action_id"] == "angles"
    assert accepted["billing"]["requested_outputs"] == 3
    assert accepted["billing"]["estimated_credits"] == 54

    for outputs in (1, 2, 4):
        rejected = client.post("/studio/jobs", json={
            "owner": "usr_designer",
            "action_id": "angles",
            "lane": definition.lane,
            "active_design_id": project_id,
            "source_revision_id": source_id,
            "requested_outputs": outputs,
            "credits_per_output": definition.credits_per_output,
        })
        assert rejected.status_code == 422
        assert "angles requires 3 requested outputs" in rejected.json()["detail"]


@pytest.mark.parametrize("action_id", ["refine", "views", "factory"])
def test_single_output_actions_reject_multiple_outputs_before_persistence(
    client,
    action_id,
):
    definition = STUDIO_JOB_ACTIONS[action_id]
    project_id, source_id = _seed_project(
        client,
        project_id=f"project_single_output_{action_id}",
        exact_specification=action_id in {"views", "factory"},
        factory_eligible=action_id == "factory",
    )

    rejected = client.post("/studio/jobs", json={
        "owner": "usr_designer",
        "action_id": action_id,
        "lane": definition.lane,
        "active_design_id": project_id,
        "source_revision_id": source_id,
        "requested_outputs": 2,
        "credits_per_output": definition.credits_per_output,
    })

    assert rejected.status_code == 422
    assert f"{action_id} requires 1 requested output" in rejected.json()["detail"]
    listed = client.get("/studio/jobs", params={"owner": "usr_designer"})
    assert listed.status_code == 200
    assert listed.json() == {"jobs": []}


def test_server_registry_matches_designer_action_contract():
    expected = {
        "create": ("brief_or_reference", "design_revision", "design_record", "candidate_job", "candidate_decision"),
        "vary": ("direction", "variation_set", "design_record", "instant_transaction", "none"),
        "refine": ("instruction", "design_revision", "design_record", "candidate_job", "candidate_decision"),
        "views": ("view_set", "view_set", "visual_preview", "candidate_job", "candidate_decision"),
        "angles": (
            "angle_set", "visual_angle_set", "visual_preview", "candidate_job", "candidate_decision",
        ),
        "present": (
            "destination", "presentation_pack", "visual_preview", "candidate_job", "candidate_decision",
        ),
        "factory": (None, "factory_review_pack", "production_review", "terminal_job", "backend_transaction"),
    }
    for action_id, (
        required_input, output_type, authority, execution_mode, review_authority,
    ) in expected.items():
        definition = STUDIO_JOB_ACTIONS[action_id]
        if required_input is not None:
            assert required_input in definition.input_requirements
        assert output_type == definition.output_type
        assert authority == definition.authority
        assert execution_mode == definition.execution_mode
        assert review_authority == definition.review_authority
        if required_input not in {None, "brief_or_reference"}:
            assert required_input in {
                field.id for field in definition.ui_schema if field.required
            }
    create = STUDIO_JOB_ACTIONS["create"]
    assert create.input_requirements == ("brief_or_reference",)
    assert {field.reference_role for field in create.ui_schema} >= {
        "master_geometry",
    }
    assert {field.id for field in create.ui_schema} == {"brief", "master"}
    assert {
        action_id: (
            definition.min_requested_outputs,
            definition.max_requested_outputs,
        )
        for action_id, definition in STUDIO_JOB_ACTIONS.items()
    } == {
        "create": (1, 4),
        "vary": (0, 0),
        "refine": (1, 1),
        "views": (1, 1),
        "angles": (3, 3),
        "present": (1, 4),
        "factory": (1, 1),
    }


@pytest.mark.parametrize(
    "action_id", [
        action_id
        for action_id, definition in STUDIO_JOB_ACTIONS.items()
        if "active_project" in definition.context_requirements
        and definition.execution_mode != "instant_transaction"
    ],
)
def test_design_jobs_reject_missing_active_project_context(client, action_id):
    definition = STUDIO_JOB_ACTIONS[action_id]
    response = client.post("/studio/jobs", json={
        "owner": "usr_designer",
        "action_id": action_id,
        "lane": definition.lane,
        "active_design_id": None,
        "source_revision_id": None,
        "requested_outputs": 1,
        "credits_per_output": definition.credits_per_output,
    })
    assert response.status_code == 422
    assert "active project and revision" in response.json()["detail"]


def test_design_jobs_fail_closed_for_foreign_or_stale_context(client):
    foreign = _seed_project(
        client, project_id="project_foreign", owner="usr_other",
    )
    definition = STUDIO_JOB_ACTIONS["refine"]
    hidden = client.post("/studio/jobs", json={
        "owner": "usr_designer",
        "action_id": "refine",
        "lane": definition.lane,
        "active_design_id": foreign[0],
        "source_revision_id": foreign[1],
        "requested_outputs": 1,
        "credits_per_output": definition.credits_per_output,
    })
    assert hidden.status_code == 404

    owned = _seed_project(client, project_id="project_owned")
    stale = client.post("/studio/jobs", json={
        "owner": "usr_designer",
        "action_id": "refine",
        "lane": definition.lane,
        "active_design_id": owned[0],
        "source_revision_id": "ast_stale_revision",
        "requested_outputs": 1,
        "credits_per_output": definition.credits_per_output,
    })
    assert stale.status_code == 409
    assert "not the project's active revision" in stale.json()["detail"]


def test_exact_specification_action_rejects_pre_spec_revision(client):
    project_id, asset_id = _seed_project(
        client, project_id="project_no_exact_spec",
    )
    definition = STUDIO_JOB_ACTIONS["views"]
    response = client.post("/studio/jobs", json={
        "owner": "usr_designer",
        "action_id": "views",
        "lane": definition.lane,
        "active_design_id": project_id,
        "source_revision_id": asset_id,
        "requested_outputs": 1,
        "credits_per_output": definition.credits_per_output,
    })
    assert response.status_code == 422
    assert "exact validated specification" in response.json()["detail"]


def test_factory_job_uses_persisted_exact_revision_eligibility(client):
    factory = STUDIO_JOB_ACTIONS["factory"]
    exact = _seed_project(
        client, project_id="project_not_eligible", exact_specification=True,
    )
    ineligible = client.post("/studio/jobs", json={
        "owner": "usr_designer",
        "action_id": "factory",
        "lane": factory.lane,
        "active_design_id": exact[0],
        "source_revision_id": exact[1],
        "requested_outputs": 1,
        "credits_per_output": factory.credits_per_output,
    })
    assert ineligible.status_code == 409
    assert "not eligible" in ineligible.json()["detail"]

    # A legacy pinned/checklisted image can report factory_ready, but it has no
    # immutable spec binding and therefore cannot authorize a Factory job.
    legacy = _seed_project(
        client,
        project_id="project_legacy_ready",
        factory_eligible=True,
    )
    no_exact_binding = client.post("/studio/jobs", json={
        "owner": "usr_designer",
        "action_id": "factory",
        "lane": factory.lane,
        "active_design_id": legacy[0],
        "source_revision_id": legacy[1],
        "requested_outputs": 1,
        "credits_per_output": factory.credits_per_output,
    })
    assert no_exact_binding.status_code == 422
    assert "exact validated specification" in no_exact_binding.json()["detail"]

    eligible = _seed_project(
        client,
        project_id="project_eligible",
        exact_specification=True,
        factory_eligible=True,
    )
    queued = _create(
        client,
        outputs=1,
        action_id="factory",
        lane=factory.lane,
        credits=factory.credits_per_output,
        active_design_id=eligible[0],
        source_revision_id=eligible[1],
    )
    assert queued["status"] == "queued"
    assert queued["active_design_id"] == eligible[0]
    assert queued["source_revision_id"] == eligible[1]


def test_factory_pack_preparation_is_backend_authoritative_and_charges_once(client):
    factory = STUDIO_JOB_ACTIONS["factory"]
    project_id, source_id = _seed_project(
        client,
        project_id="project_factory_pack_settlement",
        exact_specification=True,
        factory_eligible=True,
    )
    checklist = client.post(
        f"/assets/{source_id}/checklist",
        json={"mode": "auto_pin", "created_by": "usr_designer"},
    )
    assert checklist.status_code == 201, checklist.text
    for item in checklist.json()["items"]:
        confirmed = client.post(
            f"/assets/{source_id}/checklist/respond",
            json={
                "item_key": item["key"],
                "approved": True,
                "created_by": "usr_designer",
            },
        )
        assert confirmed.status_code == 201, confirmed.text
    queued = _create(
        client,
        outputs=1,
        action_id="factory",
        lane=factory.lane,
        credits=factory.credits_per_output,
        active_design_id=project_id,
        source_revision_id=source_id,
    )

    prepared = client.post(
        f"/projects/{project_id}/factory-pack",
        json={"studio_job_id": queued["job_id"], "owner": "usr_designer"},
    )
    assert prepared.status_code == 200, prepared.text
    assert prepared.json()["project_id"] == project_id
    assert prepared.json()["asset_id"] == source_id

    settled = client.get(
        f"/studio/jobs/{queued['job_id']}",
        params={"owner": "usr_designer"},
    ).json()
    assert settled["status"] == "succeeded"
    assert settled["billing"]["completed_outputs"] == 1
    assert settled["billing"]["charged_outputs"] == 1
    assert settled["billing"]["charged_credits"] == factory.credits_per_output
    expected_evidence = hashlib.sha256((
        json.dumps(
            prepared.json(), indent=2, sort_keys=True, ensure_ascii=False,
        ) + "\n"
    ).encode("utf-8")).hexdigest()
    assert settled["accepted_output_sha256"] == expected_evidence

    repeated = client.post(
        f"/projects/{project_id}/factory-pack",
        json={"studio_job_id": queued["job_id"], "owner": "usr_designer"},
    )
    assert repeated.status_code == 409
    after = client.get(
        f"/studio/jobs/{queued['job_id']}",
        params={"owner": "usr_designer"},
    ).json()
    assert after["billing"]["charged_outputs"] == 1


def test_factory_pack_preparation_failure_is_terminal_and_never_charged(client):
    factory = STUDIO_JOB_ACTIONS["factory"]
    project_id, source_id = _seed_project(
        client,
        project_id="project_factory_pack_incomplete",
        exact_specification=True,
        factory_eligible=True,
    )
    queued = _create(
        client,
        outputs=1,
        action_id="factory",
        lane=factory.lane,
        credits=factory.credits_per_output,
        active_design_id=project_id,
        source_revision_id=source_id,
    )

    rejected = client.post(
        f"/projects/{project_id}/factory-pack",
        json={"studio_job_id": queued["job_id"], "owner": "usr_designer"},
    )
    assert rejected.status_code == 409
    assert rejected.json()["code"] == "factory_fact_confirmation_incomplete"
    failed = client.get(
        f"/studio/jobs/{queued['job_id']}",
        params={"owner": "usr_designer"},
    ).json()
    assert failed["status"] == "failed"
    assert failed["billing"]["completed_outputs"] == 0
    assert failed["billing"]["charged_outputs"] == 0
    assert failed["billing"]["charged_credits"] == 0


def test_factory_pack_preparation_rejects_a_non_factory_job_token(client):
    project_id, source_id = _seed_project(
        client,
        project_id="project_factory_wrong_job_action",
        exact_specification=True,
        factory_eligible=True,
    )
    refine = STUDIO_JOB_ACTIONS["refine"]
    queued = _create(
        client,
        outputs=1,
        action_id="refine",
        lane=refine.lane,
        credits=refine.credits_per_output,
        active_design_id=project_id,
        source_revision_id=source_id,
    )

    rejected = client.post(
        f"/projects/{project_id}/factory-pack",
        json={"studio_job_id": queued["job_id"], "owner": "usr_designer"},
    )

    assert rejected.status_code == 409
    assert "not a Factory job" in rejected.json()["detail"]
    unchanged = client.get(
        f"/studio/jobs/{queued['job_id']}",
        params={"owner": "usr_designer"},
    ).json()
    assert unchanged["status"] == "queued"
    assert unchanged["billing"]["completed_outputs"] == 0
    assert unchanged["billing"]["charged_outputs"] == 0
    assert unchanged["billing"]["charged_credits"] == 0


def test_factory_job_rechecks_under_lock_before_insert(client, monkeypatch):
    factory = STUDIO_JOB_ACTIONS["factory"]
    project_id, source_id = _seed_project(
        client,
        project_id="project_factory_race",
        exact_specification=True,
        factory_eligible=True,
    )
    sessions = client.app_state["session_factory"]

    def land_revision_n_plus_one():
        with sessions() as writer:
            writer.add(ImageAsset(
                id="ast_factory_race_n2",
                root_id=project_id,
                parent_asset_id=source_id,
                design_version=1,
                capability="JEWELRY_RENDER",
                image=b"new-active-revision",
                media_type="image/png",
                created_by="usr_designer",
                created_at=utcnow(),
            ))
            writer.commit()

    monkeypatch.setattr(
        "facetta.api.studio._factory_job_pre_insert_hook",
        land_revision_n_plus_one,
    )
    rejected = client.post("/studio/jobs", json={
        "owner": "usr_designer",
        "action_id": "factory",
        "lane": factory.lane,
        "active_design_id": project_id,
        "source_revision_id": source_id,
        "requested_outputs": 1,
        "credits_per_output": factory.credits_per_output,
    })
    assert rejected.status_code == 409, rejected.text
    assert "no longer the active revision" in rejected.json()["detail"]
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(StudioJobRecord)) == 0


def test_factory_job_revalidates_again_before_running_provider_work(client):
    factory = STUDIO_JOB_ACTIONS["factory"]
    project_id, source_id = _seed_project(
        client,
        project_id="project_factory_execution_race",
        exact_specification=True,
        factory_eligible=True,
    )
    queued = _create(
        client,
        outputs=1,
        action_id="factory",
        lane=factory.lane,
        credits=factory.credits_per_output,
        active_design_id=project_id,
        source_revision_id=source_id,
    )
    sessions = client.app_state["session_factory"]
    with sessions() as writer:
        writer.add(ImageAsset(
            id="ast_factory_execution_n2",
            root_id=project_id,
            parent_asset_id=source_id,
            design_version=1,
            capability="JEWELRY_RENDER",
            image=b"new-active-before-provider",
            media_type="image/png",
            created_by="usr_designer",
            created_at=utcnow(),
        ))
        writer.commit()

    blocked = client.post(
        f"/projects/{project_id}/factory-pack",
        json={"studio_job_id": queued["job_id"], "owner": "usr_designer"},
    )
    assert blocked.status_code == 409
    with sessions() as db:
        job = db.get(StudioJobRecord, queued["job_id"])
        assert job is not None
        assert job.status == "failed"
        assert job.error_code == "stale_factory_context"
        assert job.completed_outputs == 0
        assert job.charged_outputs == 0


def test_factory_approval_generation_serializes_both_race_orders(client):
    """Whichever actor gets the Project lock first determines a safe result.

    Factory-first freezes the exact positive generation. Writer-first appends
    the negative generation, which Factory must observe and reject.
    """

    factory = STUDIO_JOB_ACTIONS["factory"]
    project_id, source_id = _seed_project(
        client,
        project_id="project_factory_approval_race",
        exact_specification=True,
        factory_eligible=True,
    )
    queued = _create(
        client,
        outputs=1,
        action_id="factory",
        lane=factory.lane,
        credits=factory.credits_per_output,
        active_design_id=project_id,
        source_revision_id=source_id,
    )

    # Factory won the serialization point: neither a negative response, a new
    # checklist generation, nor a re-pin can alter its approval truth.
    for path, body in (
        (
            f"/assets/{source_id}/checklist/respond",
            {"item_key": "stone", "approved": False, "note": "change it"},
        ),
        (f"/assets/{source_id}/checklist", {}),
        (f"/assets/{source_id}/pin", None),
    ):
        blocked = client.post(path, json=body) if body is not None else client.post(path)
        assert blocked.status_code == 409, blocked.text
        assert blocked.json()["detail"]["code"] == (
            "factory_approval_generation_locked"
        )

    sessions = client.app_state["session_factory"]
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(
            ApprovalResponse,
        )) == 1
        assert db.scalar(select(func.count()).select_from(
            ApprovalChecklist,
        )) == 1

    canceled = client.post(
        f"/studio/jobs/{queued['job_id']}/cancel",
        json={"owner": "usr_designer"},
    )
    assert canceled.status_code == 200, canceled.text

    # Writer won the next serialization point: the negative append is durable,
    # and the next Factory request revalidates that newer generation.
    declined = client.post(
        f"/assets/{source_id}/checklist/respond",
        json={"item_key": "stone", "approved": False, "note": "change it"},
    )
    assert declined.status_code == 201, declined.text
    rejected = client.post("/studio/jobs", json={
        "owner": "usr_designer",
        "action_id": "factory",
        "lane": factory.lane,
        "active_design_id": project_id,
        "source_revision_id": source_id,
        "requested_outputs": 1,
        "credits_per_output": factory.credits_per_output,
    })
    assert rejected.status_code == 409, rejected.text
    assert "not eligible" in rejected.json()["detail"]


def test_factory_job_rejects_caller_authored_eligibility(client):
    factory = STUDIO_JOB_ACTIONS["factory"]
    response = client.post("/studio/jobs", json={
        "owner": "usr_designer",
        "action_id": "factory",
        "lane": factory.lane,
        "active_design_id": None,
        "source_revision_id": None,
        "requested_outputs": 1,
        "credits_per_output": factory.credits_per_output,
        "factory_eligible": True,
    })
    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "extra_forbidden"


def test_backend_acceptance_helper_is_the_only_charge_authority():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    now = utcnow()
    with Session(engine, expire_on_commit=False) as db:
        db.add(StudioJobRecord(
            id="job_backend_accept",
            owner="usr_designer",
            action_id="present",
            lane="fast_visual",
            status="reviewing",
            progress=0.9,
            requested_outputs=2,
            credits_per_output=18,
            completed_outputs=0,
            charged_outputs=0,
            created_at=now,
            updated_at=now,
        ))
        db.commit()

        accepted = record_accepted_studio_job_outputs(
            db,
            job_id="job_backend_accept",
            owner="usr_designer",
            completed_outputs=1,
            active_design_id="project_selected",
            source_revision_id="presentation_saved",
        )
        assert accepted.status == "succeeded"
        assert accepted.completed_outputs == 1
        assert accepted.charged_outputs == 1
        assert accepted.credits_per_output == 18
        repeated = record_accepted_studio_job_outputs(
            db,
            job_id="job_backend_accept",
            owner="usr_designer",
            completed_outputs=1,
            active_design_id="project_selected",
            source_revision_id="presentation_saved",
        )
        assert repeated is accepted
        with pytest.raises(StudioJobAccountingError, match="already bound"):
            record_accepted_studio_job_outputs(
                db,
                job_id="job_backend_accept",
                owner="usr_designer",
                completed_outputs=1,
                active_design_id="different_project",
                source_revision_id="presentation_saved",
            )
        # The helper flushes but deliberately leaves transaction ownership to
        # the backend decision that accepts the canonical output.
        db.rollback()


def test_factory_success_requires_backend_pack_evidence_and_exact_charge(client):
    project_id, source_id = _seed_project(
        client,
        project_id="project_factory_invariants",
        exact_specification=True,
        factory_eligible=True,
    )
    definition = STUDIO_JOB_ACTIONS["factory"]
    job_id = _create(
        client,
        outputs=1,
        action_id="factory",
        lane=definition.lane,
        credits=definition.credits_per_output,
        active_design_id=project_id,
        source_revision_id=source_id,
    )["job_id"]
    sessions = client.app_state["session_factory"]
    with sessions() as db:
        job = db.get(StudioJobRecord, job_id)
        assert job is not None
        job.status = "succeeded"
        job.progress = 1
        job.completed_outputs = 1
        job.charged_outputs = 1
        with pytest.raises(ValueError, match="SHA-256 evidence"):
            db.commit()
        db.rollback()

        with pytest.raises(IntegrityError):
            db.execute(text(
                "UPDATE studio_jobs SET status = 'succeeded', progress = 1, "
                "completed_outputs = 1, charged_outputs = 1 "
                "WHERE id = :job_id"
            ), {"job_id": job_id})
            db.commit()
        db.rollback()

    unchanged = client.get(
        f"/studio/jobs/{job_id}", params={"owner": "usr_designer"},
    ).json()
    assert unchanged["status"] == "queued"
    assert unchanged["accepted_output_sha256"] is None
    assert unchanged["billing"]["completed_outputs"] == 0
    assert unchanged["billing"]["charged_outputs"] == 0


def test_existing_sqlite_job_ledger_migrates_to_first_class_angles_action():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE studio_jobs (
                id VARCHAR(32) PRIMARY KEY,
                owner VARCHAR(32) NOT NULL,
                action_id VARCHAR(24) NOT NULL,
                lane VARCHAR(24) NOT NULL,
                status VARCHAR(16) NOT NULL,
                progress FLOAT NOT NULL,
                active_design_id VARCHAR(32),
                source_revision_id VARCHAR(32),
                requested_outputs INTEGER NOT NULL,
                credits_per_output INTEGER NOT NULL,
                completed_outputs INTEGER NOT NULL,
                charged_outputs INTEGER NOT NULL,
                error_code VARCHAR(64),
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                CONSTRAINT ck_studio_job_action CHECK (
                    action_id IN (
                        'create', 'vary', 'refine', 'views',
                        'present', 'factory'
                    )
                )
            )
        """))
        connection.execute(text(
            "CREATE INDEX ix_studio_jobs_owner ON studio_jobs (owner)"
        ))
        connection.execute(text("""
            INSERT INTO studio_jobs (
                id, owner, action_id, lane, status, progress,
                active_design_id, source_revision_id, requested_outputs,
                credits_per_output, completed_outputs, charged_outputs,
                created_at, updated_at
            ) VALUES (
                'job_legacy', 'usr_designer', 'present', 'fast_visual',
                'queued', 0, 'ast_project', 'ast_source', 1, 18, 0, 0,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
        """))
        connection.execute(text("""
            CREATE TABLE child_job_evidence (
                id VARCHAR(32) PRIMARY KEY,
                studio_job_id VARCHAR(32) NOT NULL
                    REFERENCES studio_jobs(id)
            )
        """))
        connection.execute(text(
            "INSERT INTO child_job_evidence VALUES "
            "('evidence_legacy', 'job_legacy')"
        ))

    _migrate_studio_job_action_constraint(engine)

    with engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO studio_jobs (
                id, owner, action_id, lane, status, progress,
                active_design_id, source_revision_id, requested_outputs,
                credits_per_output, completed_outputs, charged_outputs,
                created_at, updated_at
            ) VALUES (
                'job_angles', 'usr_designer', 'angles', 'fast_visual',
                'queued', 0, 'ast_project', 'ast_source', 3, 18, 0, 0,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
        """))
        actions = connection.execute(text(
            "SELECT action_id FROM studio_jobs ORDER BY id"
        )).scalars().all()
        violations = connection.execute(text(
            "PRAGMA foreign_key_check"
        )).fetchall()
    assert actions == ["angles", "present"]
    assert violations == []
    assert "ix_studio_jobs_owner" in {
        item["name"] for item in inspect(engine).get_indexes("studio_jobs")
    }


def test_creation_job_lineage_can_bind_once_but_never_drift(client):
    job_id = _create(client)["job_id"]
    running = client.patch(f"/studio/jobs/{job_id}", json={
        "owner": "usr_designer", "status": "running", "progress": 0.2,
    })
    assert running.status_code == 200
    _mark_job_reviewing_from_candidate(
        client,
        job_id,
        active_design_id="project_created",
    )

    drift = client.patch(f"/studio/jobs/{job_id}", json={
        "owner": "usr_designer", "status": "succeeded", "progress": 1,
        "completed_outputs": 1,
        "active_design_id": "different_project",
        "source_revision_id": "candidate_selected",
    })
    assert drift.status_code == 409

    generic_acceptance = client.patch(f"/studio/jobs/{job_id}", json={
        "owner": "usr_designer", "status": "succeeded", "progress": 1,
        "completed_outputs": 1,
        "active_design_id": "project_created",
        "source_revision_id": "candidate_selected",
    })
    assert generic_acceptance.status_code == 409

    sessions = client.app_state["session_factory"]
    with sessions() as db:
        accepted = settle_create_studio_job_selection(
            db,
            job_id=job_id,
            owner="usr_designer",
            project_root_id="project_created",
            source_revision_id="candidate_selected",
            available_outputs=1,
        )
        db.commit()
        assert accepted.status == "succeeded"
        assert accepted.source_revision_id == "candidate_selected"
        assert accepted.charged_outputs == 1

    persisted = client.get(
        f"/studio/jobs/{job_id}", params={"owner": "usr_designer"},
    ).json()
    assert persisted["status"] == "succeeded"
    assert persisted["source_revision_id"] == "candidate_selected"
    assert persisted["billing"]["charged_outputs"] == 1


def test_failed_and_canceled_jobs_never_charge(client):
    failed_id = _create(client)["job_id"]
    failed = _transition(
        client, failed_id, "failed", 0.1, error_code="generation_unavailable",
    )
    assert failed.status_code == 200
    assert failed.json()["billing"]["charged_credits"] == 0

    canceled_id = _create(client)["job_id"]
    canceled = client.post(
        f"/studio/jobs/{canceled_id}/cancel",
        json={"owner": "usr_designer"},
    )
    assert canceled.status_code == 200
    assert canceled.json()["billing"]["charged_credits"] == 0

    reviewing_id = _create(client)["job_id"]
    assert _transition(client, reviewing_id, "running", 0.1).status_code == 200
    _mark_job_reviewing_from_candidate(client, reviewing_id)
    dismissed = client.post(
        f"/studio/jobs/{reviewing_id}/cancel",
        json={"owner": "usr_designer"},
    )
    assert dismissed.status_code == 409
    assert dismissed.json()["detail"] == (
        "Studio job cannot be canceled from reviewing"
    )
    still_reviewing = client.get(
        f"/studio/jobs/{reviewing_id}",
        params={"owner": "usr_designer"},
    )
    assert still_reviewing.status_code == 200
    assert still_reviewing.json()["status"] == "reviewing"
    assert still_reviewing.json()["billing"]["charged_credits"] == 0

    cancel_again = client.post(
        f"/studio/jobs/{canceled_id}/cancel",
        json={"owner": "usr_designer"},
    )
    assert cancel_again.status_code == 409

    invalid_charge = _create(client)["job_id"]
    invalid = _transition(
        client, invalid_charge, "failed", 0.1, completed_outputs=1,
    )
    assert invalid.status_code == 422

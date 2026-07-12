"""Persistent Studio Activity lifecycle and outcome-based billing."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from facetta.db import Base, StudioJobRecord, get_db, utcnow
from facetta.main import app
from facetta.studio_jobs import (
    STUDIO_JOB_ACTIONS,
    StudioJobAccountingError,
    record_accepted_studio_job_outputs,
)


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
) -> dict:
    response = client.post("/studio/jobs", json={
        "owner": owner,
        "action_id": action_id,
        "lane": lane,
        "active_design_id": None,
        "source_revision_id": None,
        "requested_outputs": outputs,
        "credits_per_output": credits,
    })
    assert response.status_code == 201
    return response.json()


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


def test_fresh_schema_contains_persistent_studio_jobs():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    inspector = inspect(engine)

    assert StudioJobRecord.__tablename__ in inspector.get_table_names()
    assert {
        "owner", "action_id", "lane", "status", "progress",
        "requested_outputs", "credits_per_output", "completed_outputs",
        "charged_outputs", "created_at", "updated_at",
    } <= {
        column["name"]
        for column in inspector.get_columns(StudioJobRecord.__tablename__)
    }


def test_job_lifecycle_is_persistent_and_client_completion_never_charges(client):
    job = _create(client, outputs=3)
    job_id = job["job_id"]

    assert job["status"] == "queued"
    assert job["billing"] == {
        "requested_outputs": 3,
        "credits_per_output": 15,
        "estimated_credits": 45,
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

    assert _transition(client, job_id, "running", 0.25).status_code == 200
    assert _transition(client, job_id, "reviewing", 0.8).status_code == 200
    succeeded = _transition(
        client, job_id, "succeeded", 0.8, completed_outputs=2,
    )
    assert succeeded.status_code == 200
    result = succeeded.json()
    assert result["status"] == "succeeded"
    assert result["progress"] == 1
    assert result["billing"]["completed_outputs"] == 2
    assert result["billing"]["charged_outputs"] == 0
    assert result["billing"]["charged_credits"] == 0

    persisted = client.get(
        f"/studio/jobs/{job_id}", params={"owner": "usr_designer"},
    )
    assert persisted.status_code == 200
    assert persisted.json() == result

    immutable = _transition(client, job_id, "running", 1)
    assert immutable.status_code == 409


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
    for action_id, definition in STUDIO_JOB_ACTIONS.items():
        created = _create(
            client,
            outputs=1,
            action_id=action_id,
            lane=definition.lane,
            credits=definition.credits_per_output,
        )
        assert created["lane"] == definition.lane
        assert created["billing"]["credits_per_output"] == (
            definition.credits_per_output
        )


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


def test_progress_and_charge_invariants_reject_inconsistent_updates(client):
    job_id = _create(client, outputs=1)["job_id"]
    assert _transition(client, job_id, "running", 0.6).status_code == 200

    backward = _transition(client, job_id, "reviewing", 0.5)
    assert backward.status_code == 409
    reviewing = _transition(client, job_id, "reviewing", 0.9)
    assert reviewing.status_code == 200

    no_output_count = _transition(client, job_id, "succeeded", 1)
    assert no_output_count.status_code == 422
    too_many = _transition(
        client, job_id, "succeeded", 1, completed_outputs=2,
    )
    assert too_many.status_code == 422

    self_charge = client.patch(f"/studio/jobs/{job_id}", json={
        "owner": "usr_designer",
        "status": "succeeded",
        "progress": 1,
        "completed_outputs": 1,
        "charged_outputs": 1,
    })
    assert self_charge.status_code == 422


def test_creation_job_lineage_can_bind_once_but_never_drift(client):
    job_id = _create(client)["job_id"]
    running = client.patch(f"/studio/jobs/{job_id}", json={
        "owner": "usr_designer", "status": "running", "progress": 0.2,
    })
    assert running.status_code == 200
    reviewing = client.patch(f"/studio/jobs/{job_id}", json={
        "owner": "usr_designer", "status": "reviewing", "progress": 0.9,
        "active_design_id": "project_created",
    })
    assert reviewing.status_code == 200
    assert reviewing.json()["active_design_id"] == "project_created"

    drift = client.patch(f"/studio/jobs/{job_id}", json={
        "owner": "usr_designer", "status": "succeeded", "progress": 1,
        "completed_outputs": 1,
        "active_design_id": "different_project",
        "source_revision_id": "candidate_selected",
    })
    assert drift.status_code == 409

    accepted = client.patch(f"/studio/jobs/{job_id}", json={
        "owner": "usr_designer", "status": "succeeded", "progress": 1,
        "completed_outputs": 1,
        "active_design_id": "project_created",
        "source_revision_id": "candidate_selected",
    })
    assert accepted.status_code == 200
    assert accepted.json()["source_revision_id"] == "candidate_selected"


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
    assert _transition(client, reviewing_id, "reviewing", 0.9).status_code == 200
    dismissed = client.post(
        f"/studio/jobs/{reviewing_id}/cancel",
        json={"owner": "usr_designer"},
    )
    assert dismissed.status_code == 200
    assert dismissed.json()["status"] == "canceled"
    assert dismissed.json()["billing"]["charged_credits"] == 0

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

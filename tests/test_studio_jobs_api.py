"""Persistent Studio Activity lifecycle and outcome-based billing."""

from __future__ import annotations

import copy
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, inspect, select
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
    Project,
    StudioJobRecord,
    get_db,
    utcnow,
)
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
        context = (
            eligible if action_id == "factory"
            else exact if "exact_specification" in definition.context_requirements
            else pre_spec if definition.context_requirements
            else (None, None)
        )
        created = _create(
            client,
            outputs=1,
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


def test_server_registry_matches_designer_action_contract():
    expected = {
        "create": ("brief_or_reference", "design_revision", "design_record"),
        "vary": ("direction", "variation_set", "design_record"),
        "refine": ("instruction", "design_revision", "design_record"),
        "views": ("view_set", "view_set", "visual_preview"),
        "present": (
            "destination", "presentation_pack", "visual_preview",
        ),
        "factory": (None, "factory_review_pack", "production_review"),
    }
    for action_id, (required_input, output_type, authority) in expected.items():
        definition = STUDIO_JOB_ACTIONS[action_id]
        if required_input is not None:
            assert required_input in definition.input_requirements
        assert output_type == definition.output_type
        assert authority == definition.authority
        if required_input not in {None, "brief_or_reference"}:
            assert required_input in {
                field.id for field in definition.ui_schema if field.required
            }
    create = STUDIO_JOB_ACTIONS["create"]
    assert create.input_requirements == ("brief_or_reference",)
    assert {field.reference_role for field in create.ui_schema} >= {
        "master_geometry", "material_style", "construction_detail",
        "brand_direction",
    }


@pytest.mark.parametrize(
    "action_id", ["vary", "refine", "views", "present", "factory"],
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

    blocked = _transition(client, queued["job_id"], "running", 0.1)
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

    canceled = _transition(client, queued["job_id"], "canceled", 1)
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

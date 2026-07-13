"""Provider work is authorized by the server-owned Studio job ledger."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from facetta.db import Base, StudioJobRecord, utcnow
from facetta.provider_job_gate import (
    ProviderStudioJobError,
    require_provider_studio_job,
)
from facetta.studio_jobs import studio_job_action_definition


def _job(
    db: Session,
    *,
    job_id: str,
    action_id: str = "refine",
    owner: str = "usr_designer",
    requested_outputs: int = 1,
    project_id: str | None = "ast_project",
    source_id: str | None = "ast_source",
) -> StudioJobRecord:
    action = studio_job_action_definition(action_id)
    now = utcnow()
    record = StudioJobRecord(
        id=job_id,
        owner=owner,
        action_id=action_id,
        lane=action.lane,
        status="running",
        progress=0.05,
        active_design_id=project_id,
        source_revision_id=source_id,
        requested_outputs=requested_outputs,
        credits_per_output=action.credits_per_output,
        completed_outputs=0,
        charged_outputs=0,
        created_at=now,
        updated_at=now,
    )
    db.add(record)
    db.commit()
    return record


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_missing_job_is_production_only_requirement(db, monkeypatch):
    monkeypatch.setenv("FACETTA_ENV", "test")
    assert require_provider_studio_job(
        db,
        job_id=None,
        owner="usr_designer",
        action_id="refine",
        requested_outputs=1,
        active_design_id="ast_project",
        source_revision_id="ast_source",
    ) is None

    monkeypatch.setenv("FACETTA_ENV", "production")
    with pytest.raises(ProviderStudioJobError) as caught:
        require_provider_studio_job(
            db,
            job_id=None,
            owner="usr_designer",
            action_id="refine",
            requested_outputs=1,
            active_design_id="ast_project",
            source_revision_id="ast_source",
        )
    assert caught.value.code == "studio_job_required"
    assert caught.value.status_code == 422


def test_job_gate_validates_authority_pricing_lifecycle_and_lineage(
    db,
    monkeypatch,
):
    monkeypatch.setenv("FACETTA_ENV", "production")
    valid = _job(db, job_id="job_valid")
    assert require_provider_studio_job(
        db,
        job_id=valid.id,
        owner="usr_designer",
        action_id="refine",
        requested_outputs=1,
        active_design_id="ast_project",
        source_revision_id="ast_source",
    ).id == valid.id

    cases = (
        ({"owner": "usr_other"}, "studio_job_unavailable"),
        ({"action_id": "views"}, "studio_job_invalid"),
        ({"requested_outputs": 2}, "studio_job_invalid"),
        ({"active_design_id": "ast_other"}, "studio_job_lineage_mismatch"),
        ({"source_revision_id": "ast_other"}, "studio_job_lineage_mismatch"),
    )
    base = {
        "job_id": valid.id,
        "owner": "usr_designer",
        "action_id": "refine",
        "requested_outputs": 1,
        "active_design_id": "ast_project",
        "source_revision_id": "ast_source",
    }
    for update, code in cases:
        with pytest.raises(ProviderStudioJobError) as caught:
            require_provider_studio_job(db, **{**base, **update})
        assert caught.value.code == code

    valid.status = "reviewing"
    db.commit()
    with pytest.raises(ProviderStudioJobError) as caught:
        require_provider_studio_job(db, **base)
    assert caught.value.code == "studio_job_terminal"


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    (
        ({"lane": "fast_visual"}, "studio_job_invalid"),
        ({"credits_per_output": 999}, "studio_job_invalid"),
        ({"completed_outputs": 1}, "studio_job_terminal"),
        ({"status": "queued"}, "studio_job_terminal"),
        ({"status": "reviewing"}, "studio_job_terminal"),
        ({"status": "succeeded", "completed_outputs": 1,
          "charged_outputs": 1}, "studio_job_terminal"),
        ({"status": "failed"}, "studio_job_terminal"),
        ({"status": "canceled"}, "studio_job_terminal"),
    ),
)
def test_job_gate_rejects_tampered_pricing_and_non_running_lifecycle(
    db,
    monkeypatch,
    mutation,
    expected_code,
):
    monkeypatch.setenv("FACETTA_ENV", "production")
    job = _job(db, job_id="job_tampered")
    for field, value in mutation.items():
        setattr(job, field, value)
    db.commit()

    with pytest.raises(ProviderStudioJobError) as caught:
        require_provider_studio_job(
            db,
            job_id=job.id,
            owner="usr_designer",
            action_id="refine",
            requested_outputs=1,
            active_design_id="ast_project",
            source_revision_id="ast_source",
        )
    assert caught.value.code == expected_code


def test_job_gate_rejects_unknown_and_already_bound_create_jobs(db, monkeypatch):
    monkeypatch.setenv("FACETTA_ENV", "production")
    with pytest.raises(ProviderStudioJobError) as missing:
        require_provider_studio_job(
            db,
            job_id="job_unknown",
            owner="usr_designer",
            action_id="create",
            requested_outputs=1,
        )
    assert missing.value.code == "studio_job_unavailable"

    create_job = _job(
        db,
        job_id="job_create",
        action_id="create",
        project_id=None,
        source_id=None,
    )
    assert require_provider_studio_job(
        db,
        job_id=create_job.id,
        owner="usr_designer",
        action_id="create",
        requested_outputs=1,
    ) is create_job

    create_job.active_design_id = "ast_created"
    db.commit()
    with pytest.raises(ProviderStudioJobError) as replay:
        require_provider_studio_job(
            db,
            job_id=create_job.id,
            owner="usr_designer",
            action_id="create",
            requested_outputs=1,
        )
    assert replay.value.code == "studio_job_terminal"

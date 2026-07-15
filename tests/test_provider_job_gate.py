"""Provider work is authorized by the server-owned Studio job ledger."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from facetta.db import (
    Base,
    STUDIO_REFINE_INTENT_SCHEMA_VERSION,
    StudioJobRecord,
    StudioRefineIntentRecord,
    studio_refine_intent_sha256,
    utcnow,
)
from facetta.provider_job_gate import (
    ProviderStudioJobError,
    bind_or_require_studio_refine_intent,
    require_provider_studio_job,
    studio_create_intent_record,
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
    creative_intent: dict[str, str] | None = None,
    bind_create_intent: bool = True,
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
    db.flush()
    if action_id == "create" and bind_create_intent:
        db.add(studio_create_intent_record(
            studio_job_id=job_id,
            owner=owner,
            creative_intent=creative_intent,
        ))
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


def test_create_gate_requires_exact_bound_visual_intent(db, monkeypatch):
    monkeypatch.setenv("FACETTA_ENV", "production")
    intent = {"metal_color": "rose", "visual_mood": "romantic"}
    create_job = _job(
        db,
        job_id="job_create_intent",
        action_id="create",
        project_id=None,
        source_id=None,
        creative_intent=intent,
    )
    assert require_provider_studio_job(
        db,
        job_id=create_job.id,
        owner="usr_designer",
        action_id="create",
        requested_outputs=1,
        creative_intent=intent,
    ) is create_job

    with pytest.raises(ProviderStudioJobError) as changed:
        require_provider_studio_job(
            db,
            job_id=create_job.id,
            owner="usr_designer",
            action_id="create",
            requested_outputs=1,
            creative_intent={"visual_mood": "minimal"},
        )
    assert changed.value.code == "studio_create_intent_mismatch"

    unbound = _job(
        db,
        job_id="job_create_unbound",
        action_id="create",
        project_id=None,
        source_id=None,
        bind_create_intent=False,
    )
    with pytest.raises(ProviderStudioJobError) as missing:
        require_provider_studio_job(
            db,
            job_id=unbound.id,
            owner="usr_designer",
            action_id="create",
            requested_outputs=1,
        )
    assert missing.value.code == "studio_create_intent_unbound"


def test_refine_job_is_claimed_by_one_exact_append_only_request(db):
    job = _job(db, job_id="job_refine_intent")
    intent = {
        "intent_kind": "catalog",
        "request": {
            "component_path": "metal.color",
            "option_id": "rose_gold_18k",
            "variant": 0,
            "execution_mode": "provider",
        },
    }

    bound = bind_or_require_studio_refine_intent(
        db,
        studio_job_id=job.id,
        owner="usr_designer",
        active_design_id="ast_project",
        source_revision_id="ast_source",
        refine_intent=intent,
    )
    db.commit()

    durable = db.get(StudioRefineIntentRecord, job.id)
    assert durable is not None
    assert durable.schema_version == STUDIO_REFINE_INTENT_SCHEMA_VERSION
    assert durable.refine_intent == intent
    assert durable.refine_intent_sha256 == studio_refine_intent_sha256(intent)
    assert bound.refine_intent_sha256 == durable.refine_intent_sha256

    replay = bind_or_require_studio_refine_intent(
        db,
        studio_job_id=job.id,
        owner="usr_designer",
        active_design_id="ast_project",
        source_revision_id="ast_source",
        refine_intent=intent,
    )
    assert replay.refine_intent == intent

    changed = {
        **intent,
        "request": {**intent["request"], "option_id": "white_gold_18k"},
    }
    with pytest.raises(ProviderStudioJobError) as mismatch:
        bind_or_require_studio_refine_intent(
            db,
            studio_job_id=job.id,
            owner="usr_designer",
            active_design_id="ast_project",
            source_revision_id="ast_source",
            refine_intent=changed,
        )
    assert mismatch.value.code == "studio_refine_intent_mismatch"
    assert db.get(StudioRefineIntentRecord, job.id).refine_intent == intent

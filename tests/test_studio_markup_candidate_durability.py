"""Exact Refine candidates survive restarts and resolve once, atomically."""

from __future__ import annotations

import copy
import hashlib
import io
from time import monotonic

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from conftest import EXAMPLE_SPEC, audited_import_spec
from facetta.db import (
    Base,
    Design,
    DesignVersion,
    ImageAsset,
    ImageRun,
    ImageRunReview,
    Project,
    ProjectRevisionRecord,
    StudioJobRecord,
    StudioMarkupCandidateRecord,
    get_db,
)
from facetta.image_identity import spec_visual_hash
from facetta.main import app
from facetta.spec import Spec
from facetta.studio_markup_candidates import (
    StudioMarkupError,
    lock_studio_markup_candidate_for_decision,
    store_studio_markup_candidate,
)
from facetta.warning_candidates import (
    MarkupWarningCandidate,
    clear_warning_candidates_for_tests,
)


OWNER = "usr_markup_durable"


def _png(seed: int) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (24, 24), (seed, 90, 130)).save(output, "PNG")
    return output.getvalue()


@pytest.fixture
def markup_candidates():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db():
        with Session() as db:
            yield db

    spec = audited_import_spec(EXAMPLE_SPEC)
    version = int(spec["version"])
    source = _png(40)
    with Session() as db:
        db.add_all([
            Design(id="dsn_markup", created_by=OWNER),
            DesignVersion(
                design_id="dsn_markup", version=version, spec=spec,
                created_by=OWNER,
            ),
            ImageAsset(
                id="ast_markup", root_id="ast_markup", parent_asset_id=None,
                design_id="dsn_markup", design_version=version,
                capability="JEWELRY_RENDER", image=source,
                media_type="image/png", created_by=OWNER,
            ),
            Project(
                root_id="ast_markup", owner=OWNER, title="Durable markup",
                tags=[], created_at=None, updated_at=None,
            ),
        ])
        db.commit()

    app.dependency_overrides[get_db] = override_db
    clear_warning_candidates_for_tests()
    try:
        yield TestClient(app), Session, spec, version, source
    finally:
        app.dependency_overrides.clear()
        clear_warning_candidates_for_tests()


def _store(
    Session,
    spec: dict,
    version: int,
    source: bytes,
    *,
    suffix: str,
    next_spec: Spec | None = None,
    with_job: bool = True,
    qa: dict | None = None,
    job_source_asset_id: str = "ast_markup",
):
    output = _png(120 + len(suffix))
    source_spec_hash = spec_visual_hash(Spec.model_validate(spec))
    target_spec_hash = spec_visual_hash(next_spec or Spec.model_validate(spec))
    mask_hash = ("a" * 64 if next_spec is not None else None)
    normalized_intent = (
        {
            "localization": {
                "mode": "caller_supplied_mask",
                "mask_hash": mask_hash,
            },
        }
        if mask_hash is not None else {}
    )
    run_id = f"run_markup_{suffix}"
    job_id = f"job_markup_{suffix}" if with_job else None
    with Session() as db:
        db.add(ImageRun(
            id=run_id,
            project_root_id="ast_markup",
            source_asset_id="ast_markup",
            operation=("LOCAL_EDIT" if next_spec is not None else "VISUAL_ONLY_EDIT"),
            normalized_intent={"change": suffix, **normalized_intent},
            prompt_version="test.v1",
            input_hash=hashlib.sha256(output).hexdigest(),
            source_hash=hashlib.sha256(source).hexdigest(),
            mask_hash=mask_hash,
            spec_visual_hash=target_spec_hash,
            source_spec_visual_hash=source_spec_hash,
            variant=0,
            status="review_required",
            accepted_asset_id=None,
            created_by=OWNER,
        ))
        if job_id is not None:
            db.add(StudioJobRecord(
                id=job_id, owner=OWNER, action_id="refine",
                lane="trusted_structural", status="running", progress=0.2,
                active_design_id="ast_markup",
                source_revision_id=job_source_asset_id,
                requested_outputs=1, credits_per_output=20,
                completed_outputs=0, charged_outputs=0,
            ))
        db.commit()
        compatibility = MarkupWarningCandidate(
            candidate_id=f"cand_markup_{suffix}",
            run_id=run_id,
            project_root_id="ast_markup",
            source_asset_id="ast_markup",
            expected_active_asset_id="ast_markup",
            reserved_asset_id=None,
            expected_design_version=version,
            image_bytes=output,
            media_type="image/png",
            operation=("LOCAL_EDIT" if next_spec is not None else "VISUAL_ONLY_EDIT"),
            asset_capability="LOCALIZED_EDIT",
            requested_change=f"Refine {suffix}",
            region_description="the marked region",
            drift=0.01,
            next_spec=next_spec,
            ignored_fields=(),
            qa=qa if qa is not None else {
                "verdict": "pass",
                "accepted": True,
                "review_required": False,
                "checks": [{
                    "code": "markup_fidelity",
                    "passed": True,
                    "severity": "hard",
                }],
            },
            routing={"attempt_count": 1},
            created_by=OWNER,
            expires_at=monotonic() + 3600,
        )
        return store_studio_markup_candidate(
            db, compatibility, studio_job_id=job_id)


def test_restart_resume_legacy_image_and_atomic_apply(markup_candidates):
    client, Session, spec, version, source = markup_candidates
    candidate = _store(Session, spec, version, source, suffix="apply")

    # The old in-memory authority is empty, simulating a fresh API worker.
    clear_warning_candidates_for_tests()
    listed = client.get("/studio/projects/ast_markup/markup-candidates")
    assert listed.status_code == 200, listed.text
    assert [item["candidate_id"] for item in listed.json()["candidates"]] == [
        candidate.candidate_id,
    ]
    legacy_image = client.get(
        f"/image-runs/{candidate.run_id}/candidates/"
        f"{candidate.candidate_id}/image"
    )
    assert legacy_image.status_code == 200
    assert legacy_image.content == candidate.image_bytes

    applied = client.post(
        f"/studio/markup-candidates/{candidate.run_id}/"
        f"{candidate.candidate_id}/accept",
        json={
            "created_by": OWNER,
            "expected_active_asset_id": "ast_markup",
            "expected_design_version": version,
        },
    )
    assert applied.status_code == 201, applied.text
    child_id = applied.json()["asset_id"]
    assert child_id != "ast_markup"

    with Session() as db:
        durable = db.get(StudioMarkupCandidateRecord, candidate.candidate_id)
        child = db.get(ImageAsset, child_id)
        job = db.get(StudioJobRecord, candidate.studio_job_id)
        review = db.scalar(select(ImageRunReview).where(
            ImageRunReview.run_id == candidate.run_id))
        revision = db.scalar(select(ProjectRevisionRecord).where(
            ProjectRevisionRecord.asset_id == child_id))
        assert durable is not None and durable.status == "applied"
        assert durable.image == b"" and durable.terminal_asset_id == child_id
        assert child is not None and child.parent_asset_id == "ast_markup"
        assert child.design_version == version and bytes(child.image) == candidate.image_bytes
        assert review is not None and review.accepted_asset_id == child_id
        assert revision is not None
        assert revision.interpretation["source_sha256"] == hashlib.sha256(source).hexdigest()
        assert job is not None and job.status == "succeeded"
        assert job.completed_outputs == 1 and job.charged_outputs == 1
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 1

    # Apply is idempotent, while a contradictory terminal decision fails.
    repeated = client.post(
        f"/studio/markup-candidates/{candidate.run_id}/"
        f"{candidate.candidate_id}/accept",
        json={
            "created_by": OWNER,
            "expected_active_asset_id": "ast_markup",
            "expected_design_version": version,
        },
    )
    assert repeated.status_code == 201
    assert repeated.json()["asset_id"] == child_id
    conflict = client.post(
        f"/studio/markup-candidates/{candidate.run_id}/"
        f"{candidate.candidate_id}/discard",
        json={
            "created_by": OWNER,
            "expected_active_asset_id": "ast_markup",
            "expected_design_version": version,
        },
    )
    assert conflict.status_code == 409


def test_save_as_variation_preserves_exact_spec_and_settles_job(markup_candidates):
    client, Session, spec, version, source = markup_candidates
    next_raw = copy.deepcopy(spec)
    next_raw["metal"]["finish"] = "satin"
    next_spec = Spec.model_validate(next_raw)
    candidate = _store(
        Session, spec, version, source,
        suffix="variation", next_spec=next_spec,
    )
    clear_warning_candidates_for_tests()

    newer_raw = copy.deepcopy(spec)
    newer_raw.update({"version": version + 1})
    with Session() as db:
        db.add_all([
            DesignVersion(
                design_id="dsn_markup",
                version=version + 1,
                spec=newer_raw,
                created_by=OWNER,
            ),
            ImageAsset(
                id="ast_markup_newer",
                root_id="ast_markup",
                parent_asset_id="ast_markup",
                design_id=None,
                design_version=version + 1,
                capability="LOCALIZED_EDIT",
                image=_png(212),
                media_type="image/png",
                created_by=OWNER,
            ),
        ])
        db.commit()

    saved = client.post(
        f"/studio/markup-candidates/{candidate.run_id}/"
        f"{candidate.candidate_id}/save-as-variation",
        json={"created_by": OWNER, "label": "Satin marked study"},
    )
    assert saved.status_code == 201, saved.text
    payload = saved.json()
    assert payload["source_project_id"] == "ast_markup"
    assert payload["source_asset_id"] == "ast_markup"
    sibling = payload["project"]
    assert sibling["root_id"] != "ast_markup"
    assert sibling["active_design_version"] == 1
    assert sibling["spec"]["metal"]["finish"] == "satin"

    original = client.get("/projects/ast_markup")
    assert original.status_code == 200
    assert original.json()["active_asset_id"] == "ast_markup_newer"
    assert original.json()["active_design_version"] == version + 1
    assert original.json()["spec"]["metal"]["finish"] != "satin"
    with Session() as db:
        durable = db.get(StudioMarkupCandidateRecord, candidate.candidate_id)
        job = db.get(StudioJobRecord, candidate.studio_job_id)
        assert durable is not None and durable.status == "saved_as_variation"
        assert durable.terminal_asset_id == sibling["active_asset_id"]
        assert job is not None and job.status == "succeeded"
        assert job.charged_outputs == 1


def test_historical_source_lock_is_variation_only_and_does_not_charge(
    markup_candidates,
):
    _client, Session, spec, version, source = markup_candidates
    candidate = _store(
        Session,
        spec,
        version,
        source,
        suffix="historical_variation",
    )
    with Session() as db:
        next_raw = copy.deepcopy(spec)
        next_raw.update({"version": version + 1})
        db.add_all([
            DesignVersion(
                design_id="dsn_markup",
                version=version + 1,
                spec=next_raw,
                created_by=OWNER,
            ),
            ImageAsset(
                id="ast_markup_active",
                root_id="ast_markup",
                parent_asset_id="ast_markup",
                design_id=None,
                design_version=version + 1,
                capability="LOCALIZED_EDIT",
                image=_png(211),
                media_type="image/png",
                created_by=OWNER,
            ),
        ])
        db.commit()

    with Session() as db:
        with pytest.raises(StudioMarkupError) as active_only:
            lock_studio_markup_candidate_for_decision(
                db,
                candidate.run_id,
                candidate.candidate_id,
                owner=OWNER,
            )
        assert active_only.value.code == "markup_candidate_lineage_mismatch"
        db.rollback()

        historical, record = lock_studio_markup_candidate_for_decision(
            db,
            candidate.run_id,
            candidate.candidate_id,
            owner=OWNER,
            require_active=False,
        )
        assert historical.source_asset_id == "ast_markup"
        assert historical.design_version == version
        assert historical.source_hash == hashlib.sha256(source).hexdigest()
        assert historical.source_component_map_state == "unmapped"
        assert historical.source_component_map_hash is None
        assert record.status == "reviewing"

        job = db.get(StudioJobRecord, candidate.studio_job_id)
        project = db.get(Project, "ast_markup")
        assert job is not None and job.status == "reviewing"
        assert (job.completed_outputs, job.charged_outputs) == (0, 0)
        assert project is not None and project.root_id == "ast_markup"
        assert db.scalar(select(func.count()).select_from(ImageRunReview)) == 0
        assert db.scalar(select(func.count()).select_from(
            ProjectRevisionRecord)) == 0


@pytest.mark.parametrize("corruption", ["mask", "map", "run", "candidate"])
def test_historical_source_lock_fails_closed_for_tampered_exact_lineage(
    markup_candidates,
    corruption: str,
):
    _client, Session, spec, version, source = markup_candidates
    next_raw = copy.deepcopy(spec)
    next_raw["metal"]["finish"] = "satin"
    candidate = _store(
        Session,
        spec,
        version,
        source,
        suffix=f"historical_tamper_{corruption}",
        next_spec=Spec.model_validate(next_raw),
    )
    with Session() as db:
        record = db.get(StudioMarkupCandidateRecord, candidate.candidate_id)
        assert record is not None
        if corruption == "mask":
            payload = dict(record.payload)
            payload["target_mask_sha256"] = "0" * 64
            record.payload = payload
        elif corruption == "map":
            payload = dict(record.payload)
            payload.update({
                "source_component_map_state": "mapped",
                "source_component_map_sha256": "0" * 64,
            })
            record.payload = payload
        elif corruption == "run":
            run = db.get(ImageRun, candidate.run_id)
            assert run is not None
            run.operation = "VISUAL_ONLY_EDIT"
        else:
            record.image = _png(223)
        db.commit()

    with Session() as db:
        with pytest.raises(StudioMarkupError) as rejected:
            lock_studio_markup_candidate_for_decision(
                db,
                candidate.run_id,
                candidate.candidate_id,
                owner=OWNER,
                require_active=False,
            )
        assert rejected.value.code == "markup_candidate_lineage_mismatch"
        db.rollback()
        durable = db.get(StudioMarkupCandidateRecord, candidate.candidate_id)
        job = db.get(StudioJobRecord, candidate.studio_job_id)
        assert durable is not None and durable.status == "reviewing"
        assert durable.terminal_asset_id is None
        assert job is not None and job.status == "reviewing"
        assert (job.completed_outputs, job.charged_outputs) == (0, 0)
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 1
        assert db.scalar(select(func.count()).select_from(ImageRunReview)) == 0
        assert db.scalar(select(func.count()).select_from(
            ProjectRevisionRecord)) == 0


def test_stale_active_revision_rejects_without_partial_terminal_rows(
    markup_candidates,
):
    client, Session, spec, version, source = markup_candidates
    candidate = _store(Session, spec, version, source, suffix="stale")
    with Session() as db:
        next_raw = copy.deepcopy(spec)
        next_raw.update({"version": version + 1})
        db.add_all([
            DesignVersion(
                design_id="dsn_markup", version=version + 1,
                spec=next_raw, created_by=OWNER,
            ),
            ImageAsset(
                id="ast_markup_new", root_id="ast_markup",
                parent_asset_id="ast_markup", design_id=None,
                design_version=version + 1, capability="LOCALIZED_EDIT",
                image=_png(210), media_type="image/png", created_by=OWNER,
            ),
        ])
        db.commit()

    rejected = client.post(
        f"/studio/markup-candidates/{candidate.run_id}/"
        f"{candidate.candidate_id}/accept",
        json={
            "created_by": OWNER,
            "expected_active_asset_id": "ast_markup",
            "expected_design_version": version,
        },
    )
    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["code"] == "markup_candidate_lineage_mismatch"
    discarded = client.post(
        f"/studio/markup-candidates/{candidate.run_id}/"
        f"{candidate.candidate_id}/discard",
        json={
            "created_by": OWNER,
            "expected_active_asset_id": "ast_markup",
            "expected_design_version": version,
        },
    )
    assert discarded.status_code == 200, discarded.text
    with Session() as db:
        durable = db.get(StudioMarkupCandidateRecord, candidate.candidate_id)
        job = db.get(StudioJobRecord, candidate.studio_job_id)
        assert durable is not None and durable.status == "discarded"
        assert durable.image == b""
        assert job is not None and job.status == "canceled"
        assert job.charged_outputs == 0
        assert db.scalar(select(func.count()).select_from(ImageRunReview)) == 1
        assert db.scalar(select(func.count()).select_from(ProjectRevisionRecord)) == 0


def test_markup_warn_qa_remains_reviewable(markup_candidates):
    client, Session, spec, version, source = markup_candidates
    candidate = _store(
        Session,
        spec,
        version,
        source,
        suffix="warning",
        qa={
            "verdict": "warn",
            "accepted": False,
            "review_required": True,
            "checks": [{
                "code": "minor_material_uncertainty",
                "passed": False,
                "severity": "warning",
            }],
        },
    )
    listed = client.get("/studio/projects/ast_markup/markup-candidates")
    assert listed.status_code == 200
    assert candidate.candidate_id in {
        item["candidate_id"] for item in listed.json()["candidates"]
    }


def test_markup_invalid_store_fails_only_the_exact_bound_job(markup_candidates):
    client, Session, spec, version, source = markup_candidates
    with pytest.raises(StudioMarkupError) as captured:
        _store(
            Session, spec, version, source,
            suffix="invalid_store", qa={},
        )
    assert captured.value.code == "markup_candidate_qa_invalid"
    with Session() as db:
        job = db.get(StudioJobRecord, "job_markup_invalid_store")
        assert job is not None and job.status == "failed"
        assert job.error_code == "markup_candidate_qa_invalid"
        assert (job.completed_outputs, job.charged_outputs) == (0, 0)
        assert db.get(
            StudioMarkupCandidateRecord, "cand_markup_invalid_store"
        ) is None

    with pytest.raises(StudioMarkupError) as wrong_binding:
        _store(
            Session, spec, version, source,
            suffix="wrong_job", qa={},
            job_source_asset_id="ast_unrelated",
        )
    assert wrong_binding.value.code == "markup_job_lineage_mismatch"
    with Session() as db:
        unrelated = db.get(StudioJobRecord, "job_markup_wrong_job")
        assert unrelated is not None and unrelated.status == "running"
        assert unrelated.error_code is None
        assert unrelated.charged_outputs == 0

    candidate = _store(
        Session, spec, version, source, suffix="tampered_job_link")
    with Session() as db:
        db.add(StudioJobRecord(
            id="job_markup_unrelated",
            owner=OWNER,
            action_id="refine",
            lane="trusted_structural",
            status="running",
            progress=0.2,
            active_design_id="ast_markup",
            source_revision_id="ast_unrelated",
            requested_outputs=1,
            credits_per_output=20,
            completed_outputs=0,
            charged_outputs=0,
        ))
        record = db.get(StudioMarkupCandidateRecord, candidate.candidate_id)
        assert record is not None
        record.studio_job_id = "job_markup_unrelated"
        db.commit()
    assert client.get(
        "/studio/projects/ast_markup/markup-candidates"
    ).json() == {"candidates": []}
    with Session() as db:
        record = db.get(StudioMarkupCandidateRecord, candidate.candidate_id)
        unrelated = db.get(StudioJobRecord, "job_markup_unrelated")
        assert record is not None and record.status == "expired"
        assert unrelated is not None and unrelated.status == "running"
        assert unrelated.error_code is None
        assert unrelated.charged_outputs == 0


def test_tampered_markup_qa_fails_closed_on_resume_image_and_decision(
    markup_candidates,
):
    client, Session, spec, version, source = markup_candidates
    candidate = _store(Session, spec, version, source, suffix="tampered_qa")
    with Session() as db:
        record = db.get(StudioMarkupCandidateRecord, candidate.candidate_id)
        assert record is not None
        payload = dict(record.payload)
        payload["qa"] = {}
        record.payload = payload
        db.commit()

    listed = client.get("/studio/projects/ast_markup/markup-candidates")
    assert listed.status_code == 200
    assert listed.json() == {"candidates": []}
    image = client.get(
        f"/studio/markup-candidates/{candidate.run_id}/"
        f"{candidate.candidate_id}/image"
    )
    assert image.status_code == 410
    decision = client.post(
        f"/studio/markup-candidates/{candidate.run_id}/"
        f"{candidate.candidate_id}/accept",
        json={
            "created_by": OWNER,
            "expected_active_asset_id": "ast_markup",
            "expected_design_version": version,
        },
    )
    assert decision.status_code == 409
    with Session() as db:
        record = db.get(StudioMarkupCandidateRecord, candidate.candidate_id)
        job = db.get(StudioJobRecord, candidate.studio_job_id)
        assert record is not None and record.status == "expired"
        assert bytes(record.image) == b""
        assert job is not None and job.status == "failed"
        assert job.error_code == "markup_candidate_qa_invalid"
        assert (job.completed_outputs, job.charged_outputs) == (0, 0)
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 1
        assert db.scalar(select(func.count()).select_from(ImageRunReview)) == 0
        assert db.scalar(select(func.count()).select_from(
            ProjectRevisionRecord)) == 0

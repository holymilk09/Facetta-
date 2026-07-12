"""Exact Studio View/Present review work is durable and settles atomically."""

from __future__ import annotations

import copy
import hashlib
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, func, inspect, select, text
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
    StudioJobRecord,
    StudioPresentationCandidateJobLink,
    StudioPresentationCandidateRecord,
    StudioViewCandidateRecord,
    _apply_additive_migrations,
    get_db,
)
from facetta.image_identity import spec_visual_hash
from facetta.main import app
from facetta.spec import Spec
from facetta.studio_presentation_candidates import (
    store_studio_presentation_candidate,
)
from facetta.studio_view_candidates import store_studio_view_candidate


OWNER = "usr_exact"
SOURCE = b"\x89PNG\r\n\x1a\n" + b"source-exact-revision"
SOURCE_SHA = hashlib.sha256(SOURCE).hexdigest()
QA = {"verdict": "pass", "review_required": True, "checks": []}


def _png(seed: int) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (24, 24), (seed, 80, 120)).save(output, "PNG")
    return output.getvalue()


@pytest.fixture
def exact_candidates():
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
    with Session() as db:
        db.add_all([
            Design(id="dsn_exact", created_by=OWNER),
            DesignVersion(
                design_id="dsn_exact", version=version, spec=spec,
                created_by=OWNER,
            ),
            ImageAsset(
                id="ast_exact", root_id="ast_exact", parent_asset_id=None,
                design_id="dsn_exact", design_version=version,
                capability="JEWELRY_RENDER", image=SOURCE,
                media_type="image/png", created_by=OWNER,
            ),
            Project(
                root_id="ast_exact", owner=OWNER, title="Exact ring", tags=[],
            ),
        ])
        db.commit()
    app.dependency_overrides[get_db] = override_db
    try:
        yield TestClient(app), Session, spec, version
    finally:
        app.dependency_overrides.clear()


def _job(db, job_id: str, action: str, outputs: int) -> None:
    db.add(StudioJobRecord(
        id=job_id,
        owner=OWNER,
        action_id=action,
        lane="fast_visual",
        status="running",
        progress=0.2,
        active_design_id="ast_exact",
        source_revision_id="ast_exact",
        requested_outputs=outputs,
        credits_per_output=15 if action == "views" else 18,
        completed_outputs=0,
        charged_outputs=0,
    ))
    db.commit()


def _run(db, run_id: str, operation: str, spec_hash: str) -> None:
    db.add(ImageRun(
        id=run_id,
        project_root_id="ast_exact",
        source_asset_id="ast_exact",
        operation=operation,
        normalized_intent={},
        prompt_version="test.v1",
        source_hash=SOURCE_SHA,
        spec_visual_hash=spec_hash,
        source_spec_visual_hash=spec_hash,
        variant=0,
        status="review_required",
        created_by=OWNER,
    ))
    db.commit()


def _view_candidate(Session, spec: dict, version: int, *, suffix: str):
    exact_hash = spec_visual_hash(Spec.model_validate(spec))
    with Session() as db:
        _job(db, f"job_view_{suffix}", "views", 1)
        _run(db, f"run_view_{suffix}", "VISUAL_ONLY_EDIT", exact_hash)
        return store_studio_view_candidate(
            db,
            run_id=f"run_view_{suffix}",
            project_root_id="ast_exact",
            source_asset_id="ast_exact",
            source_hash=SOURCE_SHA,
            output_bytes=_png(40),
            media_type="image/png",
            design_version=version,
            spec_hash=exact_hash,
            view="three_quarter",
            requested_change="Exact three-quarter line art",
            qa=QA,
            routing={},
            created_by=OWNER,
            studio_job_id=f"job_view_{suffix}",
        )


def _view_decision(candidate, action: str) -> tuple[str, dict]:
    return (
        f"/studio/view-candidates/{candidate.run_id}/"
        f"{candidate.candidate_id}/{action}",
        {
            "created_by": OWNER,
            "expected_project_id": "ast_exact",
            "expected_source_asset_id": "ast_exact",
            "expected_design_version": candidate.design_version,
        },
    )


def test_exact_view_survives_restart_is_owner_scoped_and_accepts_derived_once(
    exact_candidates,
):
    client, Session, spec, version = exact_candidates
    candidate = _view_candidate(Session, spec, version, suffix="accept")

    # A new API client and DB session can list and fetch the persisted raster.
    with TestClient(app) as restarted:
        listed = restarted.get("/studio/view-candidates", params={
            "owner": OWNER, "project_id": "ast_exact",
        })
        assert listed.status_code == 200, listed.text
        assert [item["candidate_id"] for item in listed.json()["candidates"]] == [
            candidate.candidate_id
        ]
        preview = listed.json()["candidates"][0]["preview_url"]
        assert restarted.get(preview).content == _png(40)
        assert restarted.get(preview.replace(OWNER, "usr_other")).status_code == 404
        foreign = restarted.get(
            "/studio/view-candidates", params={"owner": "usr_other"}
        )
        assert foreign.json() == {"candidates": []}

        path, payload = _view_decision(candidate, "accept")
        first = restarted.post(path, json=payload)
        second = restarted.post(path, json=payload)
        assert first.status_code == second.status_code == 201
        assert second.json()["asset_id"] == first.json()["asset_id"]
        assert first.json()["project"]["active_asset_id"] == "ast_exact"

    with Session() as db:
        accepted = db.get(StudioViewCandidateRecord, candidate.candidate_id)
        job = db.get(StudioJobRecord, "job_view_accept")
        derived = db.get(ImageAsset, first.json()["asset_id"])
        assert accepted is not None and accepted.status == "accepted"
        assert bytes(accepted.image) == b""
        assert derived is not None and derived.capability == "LINE_ART"
        assert derived.parent_asset_id == "ast_exact"
        assert db.scalar(select(func.count()).select_from(ImageRunReview)) == 1
        assert job is not None and job.status == "succeeded"
        assert (job.completed_outputs, job.charged_outputs) == (1, 1)


def test_exact_view_discard_is_idempotent_free_and_stale_cas_is_atomic(
    exact_candidates,
):
    client, Session, spec, version = exact_candidates
    discarded = _view_candidate(Session, spec, version, suffix="discard")
    path, payload = _view_decision(discarded, "discard")
    assert client.post(path, json=payload).status_code == 200
    assert client.post(path, json=payload).status_code == 200
    with Session() as db:
        job = db.get(StudioJobRecord, "job_view_discard")
        assert job is not None and job.status == "canceled"
        assert (job.completed_outputs, job.charged_outputs) == (0, 0)
        assert db.scalar(select(func.count()).select_from(ImageRunReview)) == 1

    stale = _view_candidate(Session, spec, version, suffix="stale")
    next_spec = copy.deepcopy(spec)
    next_spec["version"] = version + 1
    with Session() as db:
        db.add(DesignVersion(
            design_id="dsn_exact", version=version + 1,
            spec=next_spec, created_by=OWNER,
        ))
        db.commit()
    stale_path, stale_payload = _view_decision(stale, "accept")
    response = client.post(stale_path, json=stale_payload)
    assert response.status_code == 409
    assert response.json()["code"] == "stale_design_version"
    with Session() as db:
        record = db.get(StudioViewCandidateRecord, stale.candidate_id)
        job = db.get(StudioJobRecord, "job_view_stale")
        assert record is not None and record.status == "reviewing"
        assert record.accepted_asset_id is None
        assert job is not None and job.status == "reviewing"
        assert job.charged_outputs == 0
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 1


def _presentation_group(Session, spec: dict, version: int, count: int, suffix: str):
    exact_hash = spec_visual_hash(Spec.model_validate(spec))
    job_id = f"job_present_{suffix}"
    candidates = []
    with Session() as db:
        _job(db, job_id, "present", count)
        for ordinal in range(count):
            run_id = f"run_present_{suffix}_{ordinal}"
            _run(db, run_id, "VISUAL_ONLY_EDIT", exact_hash)
            candidates.append(store_studio_presentation_candidate(
                db,
                run_id=run_id,
                project_root_id="ast_exact",
                source_asset_id="ast_exact",
                source_hash=SOURCE_SHA,
                image_bytes=_png(60 + ordinal),
                media_type="image/png",
                destination="marketing",
                capability="MARKETING_IMAGE",
                requested_change=f"Marketing direction {ordinal + 1}",
                preset="luxury_studio",
                framing="portrait",
                qa=QA,
                created_by=OWNER,
                studio_job_id=job_id,
                design_version=version,
                output_ordinal=ordinal,
                expected_active_asset_id="ast_exact",
            ))
    return job_id, candidates


def _present_decision(candidate, action: str) -> tuple[str, dict]:
    return (
        f"/studio/presentation-candidates/{candidate.run_id}/"
        f"{candidate.candidate_id}/{action}",
        {
            "created_by": OWNER,
            "expected_project_id": "ast_exact",
            "expected_source_asset_id": "ast_exact",
            "expected_design_version": candidate.design_version,
        },
    )


@pytest.mark.parametrize("count", [1, 2, 3, 4])
def test_exact_present_groups_one_to_four_charge_only_the_accepted_output(
    exact_candidates, count: int,
):
    client, Session, spec, version = exact_candidates
    job_id, candidates = _presentation_group(
        Session, spec, version, count, f"accept_{count}")

    with TestClient(app) as restarted:
        resumed = restarted.get("/studio/presentation-candidates", params={
            "owner": OWNER, "project_id": "ast_exact",
        })
        assert resumed.status_code == 200
        ids = {item["candidate_id"] for item in resumed.json()["candidates"]}
        assert {item.candidate_id for item in candidates} <= ids

        accept_path, accept_body = _present_decision(candidates[0], "accept")
        accepted = restarted.post(accept_path, json=accept_body)
        assert accepted.status_code == 201, accepted.text
        assert accepted.json()["project"]["active_asset_id"] == "ast_exact"
        for candidate in candidates[1:]:
            path, body = _present_decision(candidate, "discard")
            assert restarted.post(path, json=body).status_code == 200
        replay = restarted.post(accept_path, json=accept_body)
        assert replay.status_code == 201
        assert replay.json()["asset_id"] == accepted.json()["asset_id"]

    with Session() as db:
        job = db.get(StudioJobRecord, job_id)
        assert job is not None and job.status == "succeeded"
        assert (job.completed_outputs, job.charged_outputs) == (1, 1)
        assert db.scalar(select(func.count()).select_from(
            StudioPresentationCandidateJobLink).where(
                StudioPresentationCandidateJobLink.studio_job_id == job_id
            )) == count
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 2
        assert db.scalar(select(func.count()).select_from(ImageRunReview)) == count


def test_exact_present_discard_all_is_free_and_stale_group_rolls_back(
    exact_candidates,
):
    client, Session, spec, version = exact_candidates
    job_id, candidates = _presentation_group(
        Session, spec, version, 4, "discard_all")
    for candidate in candidates:
        path, body = _present_decision(candidate, "discard")
        assert client.post(path, json=body).status_code == 200
        assert client.post(path, json=body).status_code == 200
    with Session() as db:
        job = db.get(StudioJobRecord, job_id)
        assert job is not None and job.status == "canceled"
        assert (job.completed_outputs, job.charged_outputs) == (0, 0)
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 1
        assert db.scalar(select(func.count()).select_from(ImageRunReview)) == 4

    stale_job, stale_candidates = _presentation_group(
        Session, spec, version, 2, "stale")
    next_spec = copy.deepcopy(spec)
    next_spec["version"] = version + 1
    with Session() as db:
        db.add(DesignVersion(
            design_id="dsn_exact", version=version + 1,
            spec=next_spec, created_by=OWNER,
        ))
        db.commit()
    path, body = _present_decision(stale_candidates[0], "accept")
    response = client.post(path, json=body)
    assert response.status_code == 409
    assert response.json()["code"] == "stale_design_version"
    with Session() as db:
        record = db.get(
            StudioPresentationCandidateRecord, stale_candidates[0].candidate_id)
        job = db.get(StudioJobRecord, stale_job)
        assert record is not None and record.status == "reviewing"
        assert record.accepted_asset_id is None
        assert job is not None and job.status == "reviewing"
        assert job.charged_outputs == 0
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 1


def test_exact_present_group_charges_two_accepted_and_one_discarded_once(
    exact_candidates,
):
    client, Session, spec, version = exact_candidates
    job_id, candidates = _presentation_group(
        Session, spec, version, 3, "accept_two")
    accepted_ids = []
    for candidate in candidates[:2]:
        path, body = _present_decision(candidate, "accept")
        response = client.post(path, json=body)
        assert response.status_code == 201, response.text
        accepted_ids.append(response.json()["asset_id"])
    discard_path, discard_body = _present_decision(candidates[2], "discard")
    assert client.post(discard_path, json=discard_body).status_code == 200

    replay_path, replay_body = _present_decision(candidates[0], "accept")
    replay = client.post(replay_path, json=replay_body)
    assert replay.status_code == 201
    assert replay.json()["asset_id"] == accepted_ids[0]
    with Session() as db:
        job = db.get(StudioJobRecord, job_id)
        assert job is not None and job.status == "succeeded"
        assert (job.completed_outputs, job.charged_outputs) == (2, 2)
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 3
        assert db.scalar(select(func.count()).select_from(ImageRunReview)) == 3


def test_failed_hard_qa_cannot_be_accepted_or_charged(exact_candidates):
    client, Session, spec, version = exact_candidates
    exact_hash = spec_visual_hash(Spec.model_validate(spec))
    failed_qa = {
        "verdict": "fail",
        "review_required": True,
        "checks": [{
            "code": "identity_drift",
            "passed": False,
            "severity": "hard",
            "message": "candidate changed the jewelry",
        }],
    }
    with Session() as db:
        _job(db, "job_view_failed_qa", "views", 1)
        _run(db, "run_view_failed_qa", "VISUAL_ONLY_EDIT", exact_hash)
        candidate = store_studio_view_candidate(
            db,
            run_id="run_view_failed_qa",
            project_root_id="ast_exact",
            source_asset_id="ast_exact",
            source_hash=SOURCE_SHA,
            output_bytes=_png(90),
            media_type="image/png",
            design_version=version,
            spec_hash=exact_hash,
            view="front",
            requested_change="Failed hard-QA line art",
            qa=failed_qa,
            routing={},
            created_by=OWNER,
            studio_job_id="job_view_failed_qa",
        )
    path, payload = _view_decision(candidate, "accept")
    rejected = client.post(path, json=payload)
    assert rejected.status_code == 422
    assert rejected.json()["code"] == "view_candidate_lineage_mismatch"
    with Session() as db:
        record = db.get(StudioViewCandidateRecord, candidate.candidate_id)
        job = db.get(StudioJobRecord, "job_view_failed_qa")
        assert record is not None and record.status == "reviewing"
        assert record.accepted_asset_id is None
        assert job is not None and job.charged_outputs == 0
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 1
        assert db.scalar(select(func.count()).select_from(ImageRunReview)) == 0


def test_additive_startup_preserves_old_presentation_rows_and_adds_ledgers():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE studio_presentation_candidates ("
            "id VARCHAR(32) PRIMARY KEY, image_run_id VARCHAR(32), "
            "owner VARCHAR(32), project_root_id VARCHAR(32), "
            "source_asset_id VARCHAR(32), source_sha256 VARCHAR(64), "
            "output_sha256 VARCHAR(64), image BLOB, media_type VARCHAR(24), "
            "destination VARCHAR(16), capability VARCHAR(32), "
            "requested_change TEXT, preset VARCHAR(32), framing VARCHAR(16), "
            "qa JSON, status VARCHAR(16), studio_job_id VARCHAR(32), "
            "accepted_asset_id VARCHAR(32), review_id VARCHAR(32), "
            "created_at DATETIME, expires_at DATETIME, resolved_at DATETIME)"
        ))
        connection.execute(text(
            "INSERT INTO studio_presentation_candidates "
            "(id, image_run_id, owner, project_root_id, source_asset_id, "
            "source_sha256, output_sha256, image, media_type, destination, "
            "capability, requested_change, preset, framing, qa, status, "
            "created_at, expires_at) VALUES "
            "('cand_old','run_old','usr_old','ast_old','ast_old',"
            ":digest,:digest,X'01','image/png','client',"
            "'CLIENT_BEAUTY_RENDER','old preview','studio','portrait','{}',"
            "'reviewing',CURRENT_TIMESTAMP,DATETIME('now','+1 hour'))"
        ), {"digest": "0" * 64})

    Base.metadata.create_all(engine)
    _apply_additive_migrations(engine)
    inspector = inspect(engine)
    columns = {
        item["name"]
        for item in inspector.get_columns("studio_presentation_candidates")
    }
    assert {"design_version", "expected_active_asset_id"} <= columns
    assert {
        "studio_view_candidates", "studio_presentation_candidate_job_links",
    } <= set(inspector.get_table_names())
    with engine.connect() as connection:
        assert connection.execute(text(
            "SELECT id, design_version, expected_active_asset_id "
            "FROM studio_presentation_candidates WHERE id='cand_old'"
        )).one() == ("cand_old", None, None)

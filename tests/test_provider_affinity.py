from __future__ import annotations

import hashlib

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from facetta.db import (
    Base,
    ImageAsset,
    ImageAttempt,
    ImageRun,
    ImageRunReview,
)
from facetta.provider_affinity import resolve_asset_provider_affinity


def _session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _asset(image: bytes = b"accepted-image") -> ImageAsset:
    return ImageAsset(
        id="ast_provenance",
        root_id="ast_provenance",
        parent_asset_id=None,
        capability="CREATIVE_RENDER",
        image=image,
        media_type="image/png",
        created_by="usr_test",
    )


def _run() -> ImageRun:
    return ImageRun(
        id="run_provenance",
        project_root_id="ast_provenance",
        source_asset_id=None,
        operation="reference_render",
        normalized_intent={},
        prompt_version="test",
        variant=0,
        status="review_required",
        created_by="usr_test",
    )


def test_reviewed_output_hash_backfills_exact_provider_affinity():
    db = _session()
    image = b"accepted-image"
    asset = _asset(image)
    run = _run()
    db.add_all([asset, run])
    db.flush()
    db.add_all([
        ImageAttempt(
            id="iat_failed", run_id=run.id, attempt_number=1,
            provider="xai", model="grok_direct", error_category="provider",
            output_hash=None,
        ),
        ImageAttempt(
            id="iat_winner", run_id=run.id, attempt_number=2,
            provider="openai", model="gpt-image-2", qa_verdict="pass",
            output_hash=hashlib.sha256(image).hexdigest(),
        ),
        ImageRunReview(
            id="irr_accepted", run_id=run.id, decision="accepted",
            accepted_asset_id=asset.id, created_by="usr_test",
        ),
    ])
    db.commit()

    affinity = resolve_asset_provider_affinity(db, asset)
    assert affinity is not None
    assert (affinity.provider, affinity.model, affinity.attempt_id) == (
        "openai", "gpt-image-2", "iat_winner"
    )


def test_ambiguous_hash_evidence_does_not_guess_provider():
    db = _session()
    image = b"accepted-image"
    asset = _asset(image)
    run = _run()
    run.accepted_asset_id = asset.id
    db.add_all([asset, run])
    db.flush()
    output_hash = hashlib.sha256(image).hexdigest()
    db.add_all([
        ImageAttempt(
            id="iat_one", run_id=run.id, attempt_number=1,
            provider="xai", model="grok_direct", qa_verdict="pass",
            output_hash=output_hash,
        ),
        ImageAttempt(
            id="iat_two", run_id=run.id, attempt_number=2,
            provider="openai", model="gpt-image-2", qa_verdict="warn",
            output_hash=output_hash,
        ),
    ])
    db.commit()

    assert resolve_asset_provider_affinity(db, asset) is None

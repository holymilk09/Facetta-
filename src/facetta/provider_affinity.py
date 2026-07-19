"""Hash-bound image-provider continuity for canonical Studio revisions."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from facetta.db import (
    ImageAsset,
    ImageAssetProviderAffinity,
    ImageAttempt,
    ImageRun,
    ImageRunReview,
)
from facetta.image_agent import ImageRoute


@dataclass(frozen=True)
class ProviderAffinity:
    provider: str
    model: str
    run_id: str
    attempt_id: str


def _unique_producing_attempt(
    db: Session, *, asset_id: str, image_bytes: bytes
) -> ProviderAffinity | None:
    output_hash = hashlib.sha256(image_bytes).hexdigest()
    rows = db.execute(
        select(ImageAttempt, ImageRun)
        .join(ImageRun, ImageRun.id == ImageAttempt.run_id)
        .outerjoin(ImageRunReview, ImageRunReview.run_id == ImageRun.id)
        .where(
            or_(
                ImageRun.accepted_asset_id == asset_id,
                ImageRunReview.accepted_asset_id == asset_id,
            ),
            ImageAttempt.output_hash == output_hash,
            ImageAttempt.error_category.is_(None),
            ImageAttempt.qa_verdict.in_(("pass", "warn")),
        )
    ).all()
    identities = {
        (attempt.provider, attempt.model, run.id, attempt.id)
        for attempt, run in rows
    }
    if len(identities) != 1:
        return None
    provider, model, run_id, attempt_id = identities.pop()
    return ProviderAffinity(provider, model, run_id, attempt_id)


def resolve_asset_provider_affinity(
    db: Session, asset: ImageAsset, *, persist_backfill: bool = True
) -> ProviderAffinity | None:
    row = db.get(ImageAssetProviderAffinity, asset.id)
    if row is not None:
        return ProviderAffinity(
            row.provider, row.model, row.source_run_id or "", row.source_attempt_id or ""
        )
    proven = _unique_producing_attempt(
        db, asset_id=asset.id, image_bytes=bytes(asset.image)
    )
    if proven is not None and persist_backfill:
        db.add(ImageAssetProviderAffinity(
            asset_id=asset.id,
            provider=proven.provider,
            model=proven.model,
            source_run_id=proven.run_id,
            source_attempt_id=proven.attempt_id,
            derivation="backfilled_attempt",
        ))
        db.flush()
    return proven


def resolve_run_output_affinity(
    db: Session, *, run_id: str, image_bytes: bytes
) -> ProviderAffinity | None:
    output_hash = hashlib.sha256(image_bytes).hexdigest()
    rows = db.scalars(select(ImageAttempt).where(
        ImageAttempt.run_id == run_id,
        ImageAttempt.output_hash == output_hash,
        ImageAttempt.error_category.is_(None),
        ImageAttempt.qa_verdict.in_(("pass", "warn")),
    )).all()
    identities = {(row.provider, row.model, row.id) for row in rows}
    if len(identities) != 1:
        return None
    provider, model, attempt_id = identities.pop()
    return ProviderAffinity(provider, model, run_id, attempt_id)


def locked_edit_routes(provider: str, model: str) -> tuple[ImageRoute, ...]:
    mapping = {
        ("openai", "gpt-image-2"): ImageRoute.OPENAI_EDIT,
        ("xai", "grok_direct"): ImageRoute.GROK_EDIT,
        ("fal", "flux_kontext"): ImageRoute.FLUX_KONTEXT_EDIT,
    }
    route = mapping.get((provider, model))
    if route is None:
        raise ValueError(f"unsupported revision provider affinity: {provider}/{model}")
    return (route, route, route)


def attach_asset_provider_affinity(
    db: Session, *, asset_id: str, affinity: ProviderAffinity, derivation: str
) -> None:
    db.add(ImageAssetProviderAffinity(
        asset_id=asset_id,
        provider=affinity.provider,
        model=affinity.model,
        source_run_id=affinity.run_id or None,
        source_attempt_id=affinity.attempt_id or None,
        derivation=derivation,
    ))

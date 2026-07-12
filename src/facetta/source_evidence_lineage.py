"""Verify source evidence across accepted, QA-recorded visual spec edits."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from facetta.db import ImageAsset, ImageRun, ImageRunReview
from facetta.source_component_coverage import SourceCoverageFactoryBlocker


_LINEAGE_RESOLVABLE_CODES = frozenset({
    "source_component_spec_audit_stale",
    "source_component_confirmation_stale",
})


def apply_trusted_lineage_to_blockers(
    blockers: tuple[SourceCoverageFactoryBlocker, ...],
    *,
    lineage_verified: bool,
) -> tuple[SourceCoverageFactoryBlocker, ...]:
    """Clear only hash-staleness blockers after an exact accepted edit path."""
    if not lineage_verified:
        return blockers
    return tuple(
        blocker for blocker in blockers
        if blocker.code not in _LINEAGE_RESOLVABLE_CODES
    )


def has_trusted_visual_spec_lineage(
    db: Session,
    *,
    active_asset: ImageAsset,
    source_spec_visual_hash: str | None,
    target_spec_visual_hash: str,
) -> bool:
    """Return true only for an unbroken accepted-run path to ``active_asset``.

    The function never mutates old source evidence. Every edge must be the
    exact source/target visual-spec hashes recorded before provider execution,
    and the produced asset must be the accepted result of that same run (either
    an automatic pass or an explicit warning-candidate review).
    """
    if source_spec_visual_hash is None:
        return False
    if source_spec_visual_hash == target_spec_visual_hash:
        return True

    ancestry: list[ImageAsset] = []
    cursor: ImageAsset | None = active_asset
    seen: set[str] = set()
    while cursor is not None and cursor.id not in seen:
        seen.add(cursor.id)
        ancestry.append(cursor)
        cursor = (
            db.get(ImageAsset, cursor.parent_asset_id)
            if cursor.parent_asset_id is not None else None
        )
    ancestry.reverse()

    current_hash = source_spec_visual_hash
    for index, asset in enumerate(ancestry[1:], start=1):
        runs = list(db.scalars(
            select(ImageRun)
            .where(
                ImageRun.project_root_id == active_asset.root_id,
                ImageRun.source_asset_id == asset.parent_asset_id,
                ImageRun.spec_visual_hash.is_not(None),
            )
            .order_by(ImageRun.created_at, ImageRun.id)
        ))
        matching: ImageRun | None = None
        for run in runs:
            accepted = run.accepted_asset_id
            if accepted is None:
                review = db.scalar(select(ImageRunReview).where(
                    ImageRunReview.run_id == run.id,
                    ImageRunReview.decision == "accepted",
                ))
                accepted = review.accepted_asset_id if review is not None else None
            if (accepted == asset.id
                    and run.source_spec_visual_hash == current_hash):
                matching = run
                break
        if matching is None:
            # Derived/non-image-agent nodes cannot silently carry source audit
            # authority to a different visual specification.
            if asset.design_version != ancestry[index - 1].design_version:
                return False
            continue
        current_hash = matching.spec_visual_hash or current_hash

    return current_hash == target_spec_visual_hash

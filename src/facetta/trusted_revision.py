"""Atomic persistence for an explicitly reviewed trusted image revision."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from facetta.db import (
    DerivedArtifactMetadata,
    DesignVersion,
    ImageAsset,
    ImageRun,
    ImageRunReview,
    Project,
    new_id,
    utcnow,
)
from facetta.project_backbone import is_primary_revision
from facetta.media import sniff_media_type
from facetta.image_agent import ImageAgentResult
from facetta.image_identity import spec_visual_hash
from facetta.specdiff import diff_specs
from facetta.spec import Spec
from facetta.validation import validate_spec
from facetta.vocabulary import get_vocabulary
from facetta.warning_candidates import MarkupWarningCandidate
from facetta.catalog_preview_candidates import CatalogPreviewCandidate


class WarningRevisionError(RuntimeError):
    def __init__(self, code: str, detail: str, *, status_code: int = 409) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status_code = status_code


class TrustedSpecRevisionError(RuntimeError):
    """A passed candidate can no longer be committed against its exact base."""

    def __init__(self, code: str, detail: str, *, status_code: int = 409) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True)
class AcceptedWarningRevision:
    asset_id: str
    design_id: str
    design_version: int
    spec_change: tuple[dict[str, object], ...]
    review_id: str


@dataclass(frozen=True)
class DiscardedWarningCandidate:
    project_root_id: str
    source_asset_id: str
    design_version: int
    review_id: str


@dataclass(frozen=True)
class AcceptedSpecImageRevision:
    """One accepted, atomically persisted image/spec/run revision."""

    asset_id: str
    design_id: str
    design_version: int
    image_run_id: str
    spec_change: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class AcceptedCatalogPreviewRevision:
    """One explicitly applied catalog preview and its append-only review."""

    asset_id: str
    design_id: str
    design_version: int
    spec_change: tuple[dict[str, object], ...]
    review_id: str


def _media_type(image: bytes) -> str:
    if image[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if image[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if image[:4] == b"RIFF" and image[8:12] == b"WEBP":
        return "image/webp"
    raise WarningRevisionError(
        "candidate_media_invalid",
        "the reviewed candidate is not a supported image",
        status_code=422,
    )


def _active_primary(db: Session, root_id: str) -> ImageAsset | None:
    chain = list(db.scalars(
        select(ImageAsset)
        .where(ImageAsset.root_id == root_id)
        .order_by(ImageAsset.created_at, ImageAsset.id)
    ))
    chain.sort(key=lambda asset: (
        asset.id != root_id, asset.created_at, asset.id,
    ))
    primary = [asset for asset in chain if is_primary_revision(asset)]
    return primary[-1] if primary else None


def _accept_derived_warning_candidate(
    db: Session,
    *,
    candidate: MarkupWarningCandidate,
    run: ImageRun,
    source: ImageAsset,
    root: ImageAsset,
    project: Project,
    design_version: int,
    created_by: str,
) -> AcceptedWarningRevision:
    """Persist a reviewed discussion artifact without creating a revision."""

    metadata = candidate.artifact_metadata
    if metadata is None or candidate.promotion_kind != "derived_only":
        raise WarningRevisionError(
            "derived_artifact_metadata_required",
            "the derived candidate is missing its typed artifact metadata",
            status_code=422,
        )
    if (candidate.asset_capability != "FACTORY_REVIEW_MOUNTING_VIEW"
            or candidate.operation != "MOUNTING_VIEW_GENERATE"
            or run.operation != "MOUNTING_VIEW_GENERATE"):
        raise WarningRevisionError(
            "derived_artifact_capability_invalid",
            "the reviewed candidate is not a canonical mounting view",
            status_code=422,
        )
    source_hash = hashlib.sha256(bytes(source.image)).hexdigest()
    if (run.project_root_id != project.root_id
            or run.source_asset_id != source.id
            or run.source_hash != source_hash
            or metadata.source_hash != source_hash
            or run.spec_visual_hash != metadata.spec_visual_hash):
        raise WarningRevisionError(
            "derived_artifact_lineage_mismatch",
            "the mounting view is not bound to this exact source and specification",
            status_code=422,
        )

    child = ImageAsset(
        id=candidate.reserved_asset_id or new_id("ast"),
        root_id=source.root_id,
        parent_asset_id=source.id,
        design_id=None,
        design_version=design_version,
        capability="FACTORY_REVIEW_MOUNTING_VIEW",
        instruction=candidate.requested_change,
        region=candidate.region_description,
        drift=None,
        image=candidate.image_bytes,
        media_type=_media_type(candidate.image_bytes),
        created_by=created_by,
    )
    review = ImageRunReview(
        id=new_id("irr"),
        run_id=candidate.run_id,
        decision="accepted",
        accepted_asset_id=child.id,
        created_by=created_by,
    )
    artifact = DerivedArtifactMetadata(
        asset_id=child.id,
        view=metadata.view,
        hidden_geometry_status="designer_confirmed_visual_proposal",
        source_asset_ids=[source.id],
        source_hashes={source.id: source_hash},
        design_version=design_version,
        spec_visual_hash=metadata.spec_visual_hash,
        image_run_id=run.id,
        review_id=review.id,
        production_authority=False,
        disclaimer=(
            "AI-generated, designer-reviewed visual proposal for factory "
            "discussion only. Do not measure or manufacture from this image."
        ),
    )
    project.updated_at = utcnow()
    db.add_all([child, review, artifact])
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return AcceptedWarningRevision(
        asset_id=child.id,
        design_id=root.design_id or "",
        design_version=design_version,
        spec_change=(),
        review_id=review.id,
    )


def _accept_presentation_warning_candidate(
    db: Session,
    *,
    candidate: MarkupWarningCandidate,
    run: ImageRun,
    source: ImageAsset,
    root: ImageAsset,
    project: Project,
    design_version: int,
    created_by: str,
) -> AcceptedWarningRevision:
    """Persist an exact-source presentation output without advancing design."""

    allowed = {
        "CLIENT_BEAUTY_RENDER": "SPEC_RENDER",
        "CLIENT_PRODUCT_PHOTO": "VISUAL_ONLY_EDIT",
        "MARKETING_IMAGE": "VISUAL_ONLY_EDIT",
    }
    expected_operation = allowed.get(candidate.asset_capability)
    if (candidate.promotion_kind != "presentation_only"
            or candidate.next_spec is not None
            or candidate.artifact_metadata is not None
            or expected_operation is None
            or candidate.operation != expected_operation
            or run.operation != expected_operation):
        raise WarningRevisionError(
            "presentation_candidate_invalid",
            "the reviewed candidate is not a presentation-only output",
            status_code=422,
        )
    source_hash = hashlib.sha256(bytes(source.image)).hexdigest()
    latest = db.get(DesignVersion, (root.design_id, design_version))
    if latest is None:
        raise WarningRevisionError(
            "spec_version_unavailable",
            "the exact source specification is unavailable",
            status_code=404,
        )
    expected_spec_hash = spec_visual_hash(Spec.model_validate(latest.spec))
    source_spec_hash_matches = (
        run.source_spec_visual_hash == expected_spec_hash
        if expected_operation == "VISUAL_ONLY_EDIT"
        else run.source_spec_visual_hash in {None, expected_spec_hash}
    )
    if (run.project_root_id != project.root_id
            or run.source_asset_id != source.id
            or run.source_hash != source_hash
            or run.spec_visual_hash != expected_spec_hash
            or not source_spec_hash_matches
            or run.created_by != candidate.created_by):
        raise WarningRevisionError(
            "presentation_candidate_lineage_mismatch",
            "the presentation is not bound to this exact source and specification",
            status_code=422,
        )

    child = ImageAsset(
        id=candidate.reserved_asset_id or new_id("ast"),
        root_id=source.root_id,
        parent_asset_id=source.id,
        design_id=None,
        design_version=design_version,
        capability=candidate.asset_capability,
        instruction=candidate.requested_change,
        region=candidate.region_description,
        drift=None,
        image=candidate.image_bytes,
        media_type=_media_type(candidate.image_bytes),
        created_by=created_by,
    )
    review = ImageRunReview(
        id=new_id("irr"),
        run_id=candidate.run_id,
        decision="accepted",
        accepted_asset_id=child.id,
        created_by=created_by,
    )
    project.updated_at = utcnow()
    db.add_all([child, review])
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise WarningRevisionError(
            "presentation_candidate_resolution_conflict",
            "another review decision was saved before this presentation",
        ) from exc
    except Exception:
        db.rollback()
        raise
    return AcceptedWarningRevision(
        asset_id=child.id,
        design_id=root.design_id or "",
        design_version=design_version,
        spec_change=(),
        review_id=review.id,
    )


def persist_spec_image_revision(
    db: Session,
    *,
    source_asset: ImageAsset,
    expected_design_version: int,
    next_spec: Spec,
    image_run: ImageAgentResult,
    instruction: str,
    region: str,
    created_by: str,
    capability: str = "LOCALIZED_EDIT",
    drift: float | None = None,
    asset_id: str | None = None,
) -> AcceptedSpecImageRevision:
    """Commit a QA-passed visual, immutable spec, and run as one transaction.

    Provider work is deliberately complete before this service is called.  The
    short write section rechecks both optimistic concurrency guards so a stale
    image can never be paired with a newer specification.  Validation is only
    a gate: ``next_spec`` is persisted byte-for-structure unchanged apart from
    immutable record metadata.
    """
    if not image_run.accepted or image_run.review_required:
        raise TrustedSpecRevisionError(
            "image_candidate_not_accepted",
            "only a QA-passed image candidate may be persisted automatically",
            status_code=422,
        )
    if capability not in {"LOCALIZED_EDIT"}:
        raise TrustedSpecRevisionError(
            "revision_capability_invalid",
            "a synchronized catalog change must be a localized edit",
            status_code=422,
        )

    root = db.get(ImageAsset, source_asset.root_id)
    project = db.get(Project, source_asset.root_id)
    if root is None or project is None or root.design_id is None:
        raise TrustedSpecRevisionError(
            "project_design_unavailable",
            "the source asset is not in a persisted, design-linked project",
            status_code=404,
        )
    active = _active_primary(db, source_asset.root_id)
    if active is None or active.id != source_asset.id:
        raise TrustedSpecRevisionError(
            "stale_asset_revision",
            "the active visual changed while the image candidate was prepared",
        )
    latest = db.scalar(select(func.max(DesignVersion.version)).where(
        DesignVersion.design_id == root.design_id))
    if (latest != expected_design_version
            or source_asset.design_version != expected_design_version):
        raise TrustedSpecRevisionError(
            "stale_design_version",
            "the specification changed while the image candidate was prepared",
        )
    before_row = db.get(
        DesignVersion, (root.design_id, expected_design_version))
    if before_row is None:
        raise TrustedSpecRevisionError(
            "spec_version_unavailable",
            "the exact source specification is unavailable",
            status_code=404,
        )

    before_spec = Spec.model_validate(before_row.spec)
    expected_source_hash = hashlib.sha256(bytes(source_asset.image)).hexdigest()
    if (image_run.plan.operation.value != "LOCAL_EDIT"
            or image_run.plan.source_hash != expected_source_hash
            or image_run.plan.source_spec_visual_hash
            != spec_visual_hash(before_spec)
            or image_run.plan.spec_visual_hash != spec_visual_hash(next_spec)):
        raise TrustedSpecRevisionError(
            "image_plan_spec_mismatch",
            "the accepted candidate was not evaluated against this exact source and result specification",
            status_code=422,
        )

    validated = validate_spec(next_spec, get_vocabulary())
    if not validated.ok:
        raise TrustedSpecRevisionError(
            "candidate_spec_invalid",
            "the deterministic result specification no longer passes validation",
            status_code=422,
        )
    next_payload = next_spec.model_dump(mode="json")
    changes = tuple(diff_specs(before_row.spec, next_payload))
    if not changes:
        raise TrustedSpecRevisionError(
            "spec_change_required",
            "the synchronized revision has no structural specification change",
            status_code=422,
        )

    now = utcnow()
    next_version = expected_design_version + 1
    stored = dict(next_payload)
    stored.update({
        "design_id": root.design_id,
        "version": next_version,
        "created_by": created_by,
        "created_at": now.isoformat().replace("+00:00", "Z"),
    })
    child = ImageAsset(
        id=asset_id or new_id("ast"),
        root_id=source_asset.root_id,
        parent_asset_id=source_asset.id,
        design_id=None,
        design_version=next_version,
        capability=capability,
        instruction=instruction,
        region=region,
        drift=drift,
        image=image_run.image_bytes,
        media_type=sniff_media_type(image_run.image_bytes),
        created_by=created_by,
        created_at=now,
    )
    version = DesignVersion(
        design_id=root.design_id,
        version=next_version,
        spec=stored,
        created_by=created_by,
        created_at=now,
    )
    db.add_all([version, child])
    from facetta.image_run_store import persist_image_agent_result

    run_id = persist_image_agent_result(
        db,
        image_run,
        project_root_id=source_asset.root_id,
        source_asset_id=source_asset.id,
        accepted_asset_id=child.id,
        created_by=created_by,
        commit=False,
    )
    project.updated_at = now
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise TrustedSpecRevisionError(
            "stale_design_version",
            "another revision was saved before this candidate could commit",
        ) from exc
    except Exception:
        db.rollback()
        raise
    return AcceptedSpecImageRevision(
        asset_id=child.id,
        design_id=root.design_id,
        design_version=next_version,
        image_run_id=run_id,
        spec_change=changes,
    )


def accept_warning_revision(
    db: Session,
    candidate: MarkupWarningCandidate,
    *,
    expected_design_version: int,
    created_by: str,
) -> AcceptedWarningRevision:
    """Promote one QA-warning candidate after explicit designer review.

    The provider already ran.  This function rechecks active asset and spec
    version, then commits the visual, optional immutable spec version, and
    review decision together in one short transaction.
    """
    if (candidate.promotion_kind == "presentation_only"
            and created_by != candidate.created_by):
        raise WarningRevisionError(
            "presentation_candidate_owner_mismatch",
            "only the candidate creator may accept this presentation",
            status_code=403,
        )
    existing = db.scalar(select(ImageRunReview).where(
        ImageRunReview.run_id == candidate.run_id))
    if existing is not None and existing.accepted_asset_id is not None:
        asset = db.get(ImageAsset, existing.accepted_asset_id)
        root = db.get(ImageAsset, asset.root_id) if asset is not None else None
        if asset is None or root is None or root.design_id is None:
            raise WarningRevisionError(
                "review_history_invalid",
                "the prior review decision cannot be resolved",
                status_code=500,
            )
        return AcceptedWarningRevision(
            asset_id=asset.id,
            design_id=root.design_id,
            design_version=asset.design_version or expected_design_version,
            spec_change=(),
            review_id=existing.id,
        )

    run = db.get(ImageRun, candidate.run_id)
    source = db.get(ImageAsset, candidate.source_asset_id)
    project = db.scalar(select(Project).where(
        Project.root_id == candidate.project_root_id
    ).with_for_update())
    root = db.get(ImageAsset, candidate.project_root_id)
    if run is None or run.status != "review_required":
        raise WarningRevisionError(
            "warning_run_unavailable",
            "the image run is not awaiting designer review",
            status_code=404,
        )
    if source is None or project is None or root is None or root.design_id is None:
        raise WarningRevisionError(
            "warning_project_unavailable",
            "the source project is no longer available",
            status_code=404,
        )
    if source.root_id != candidate.project_root_id:
        raise WarningRevisionError(
            "warning_source_mismatch",
            "the candidate does not belong to this project",
        )
    active = _active_primary(db, candidate.project_root_id)
    if (active is None
            or active.id != candidate.expected_active_asset_id):
        raise WarningRevisionError(
            "stale_asset_revision",
            "the active visual changed while this candidate was under review",
        )
    if expected_design_version != candidate.expected_design_version:
        raise WarningRevisionError(
            "stale_design_version",
            "the candidate was reviewed against a different specification version",
        )
    latest = db.scalar(select(func.max(DesignVersion.version)).where(
        DesignVersion.design_id == root.design_id))
    if latest != expected_design_version or source.design_version != latest:
        raise WarningRevisionError(
            "stale_design_version",
            "the specification changed while this candidate was under review",
        )

    if candidate.promotion_kind == "derived_only":
        return _accept_derived_warning_candidate(
            db,
            candidate=candidate,
            run=run,
            source=source,
            root=root,
            project=project,
            design_version=expected_design_version,
            created_by=created_by,
        )
    if candidate.promotion_kind == "presentation_only":
        return _accept_presentation_warning_candidate(
            db,
            candidate=candidate,
            run=run,
            source=source,
            root=root,
            project=project,
            design_version=expected_design_version,
            created_by=created_by,
        )

    next_version = expected_design_version
    changes: tuple[dict[str, object], ...] = ()
    if candidate.next_spec is not None:
        validated = validate_spec(candidate.next_spec, get_vocabulary())
        if not validated.ok:
            raise WarningRevisionError(
                "candidate_spec_invalid",
                "the candidate specification no longer passes validation",
                status_code=422,
            )
        next_version += 1
        before_row = db.get(DesignVersion, (root.design_id, expected_design_version))
        if before_row is None:
            raise WarningRevisionError(
                "spec_version_unavailable",
                "the candidate's base specification is unavailable",
                status_code=404,
            )
        now = utcnow()
        # Validation is a gate. Warning review must persist the exact scoped
        # candidate spec, not opportunistically populate an unrelated derived
        # field while the designer is accepting one visual revision.
        stored = candidate.next_spec.model_dump(mode="json")
        stored.update({
            "design_id": root.design_id,
            "version": next_version,
            "created_by": created_by,
            "created_at": now.isoformat().replace("+00:00", "Z"),
        })
        db.add(DesignVersion(
            design_id=root.design_id,
            version=next_version,
            spec=stored,
            created_by=created_by,
            created_at=now,
        ))
        changes = tuple(diff_specs(before_row.spec, stored))

    if candidate.asset_capability not in {
        "LOCALIZED_EDIT", "GLOBAL_RESTYLE", "PRODUCT_PHOTO",
        "MARKETING_IMAGE",
        "LINE_ART", "COLORED_LINE_ART", "SPEC_RENDER",
    }:
        raise WarningRevisionError(
            "candidate_capability_invalid",
            "the reviewed candidate does not declare a trusted revision capability",
            status_code=422,
        )
    child = ImageAsset(
        # A structural image edit may reserve its immutable asset identity
        # before persistence so the validated spec can bind its visual-form
        # reference to these exact bytes. Warning candidates keep that
        # identity through explicit designer review.
        id=candidate.reserved_asset_id or new_id("ast"),
        root_id=source.root_id,
        parent_asset_id=source.id,
        design_id=None,
        design_version=next_version,
        capability=candidate.asset_capability,
        instruction=candidate.requested_change,
        region=candidate.region_description,
        drift=candidate.drift,
        image=candidate.image_bytes,
        media_type=_media_type(candidate.image_bytes),
        created_by=created_by,
    )
    review = ImageRunReview(
        id=new_id("irr"),
        run_id=candidate.run_id,
        decision="accepted",
        accepted_asset_id=child.id,
        created_by=created_by,
    )
    project.updated_at = utcnow()
    db.add_all([child, review])
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return AcceptedWarningRevision(
        asset_id=child.id,
        design_id=root.design_id,
        design_version=next_version,
        spec_change=changes,
        review_id=review.id,
    )


def discard_warning_revision(
    db: Session,
    candidate: MarkupWarningCandidate,
    *,
    expected_design_version: int,
    created_by: str,
) -> DiscardedWarningCandidate:
    """Record a terminal rejection against the candidate's exact lineage."""

    if expected_design_version != candidate.expected_design_version:
        raise WarningRevisionError(
            "stale_design_version",
            "the candidate was reviewed against a different specification version",
        )
    existing = db.scalar(select(ImageRunReview).where(
        ImageRunReview.run_id == candidate.run_id))
    if existing is not None:
        raise WarningRevisionError(
            "warning_candidate_resolution_conflict",
            "this candidate already has a terminal review decision",
        )
    run = db.get(ImageRun, candidate.run_id)
    source = db.get(ImageAsset, candidate.source_asset_id)
    root = db.get(ImageAsset, candidate.project_root_id)
    project = db.get(Project, candidate.project_root_id)
    if (run is None or run.status != "review_required" or source is None
            or root is None or root.design_id is None or project is None):
        raise WarningRevisionError(
            "warning_candidate_unavailable",
            "the candidate's review lineage is no longer available",
            status_code=404,
        )
    active = _active_primary(db, candidate.project_root_id)
    latest = db.scalar(select(func.max(DesignVersion.version)).where(
        DesignVersion.design_id == root.design_id))
    source_hash = hashlib.sha256(bytes(source.image)).hexdigest()
    if (source.root_id != candidate.project_root_id
            or active is None
            or active.id != candidate.expected_active_asset_id
            or latest != expected_design_version
            or source.design_version != expected_design_version
            or run.project_root_id != candidate.project_root_id
            or run.source_asset_id != source.id
            or run.source_hash != source_hash
            or run.created_by != created_by):
        raise WarningRevisionError(
            "warning_candidate_lineage_mismatch",
            "the candidate is no longer bound to the exact active source",
        )
    review = ImageRunReview(
        id=new_id("irr"),
        run_id=run.id,
        decision="discarded",
        accepted_asset_id=None,
        created_by=created_by,
    )
    db.add(review)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise WarningRevisionError(
            "warning_candidate_resolution_conflict",
            "another review decision was saved before this candidate",
        ) from exc
    except Exception:
        db.rollback()
        raise
    return DiscardedWarningCandidate(
        project_root_id=project.root_id,
        source_asset_id=source.id,
        design_version=expected_design_version,
        review_id=review.id,
    )


def accept_catalog_preview_revision(
    db: Session,
    candidate: CatalogPreviewCandidate,
    *,
    expected_design_version: int,
    created_by: str,
    commit: bool = True,
) -> AcceptedCatalogPreviewRevision:
    """Atomically apply a previously evaluated pass-or-warn catalog preview.

    No provider or evaluator work occurs here.  The durable ImageRun plus the
    temporary candidate's hashes bind the bytes to the exact active source,
    source specification, and proposed specification before the short write
    transaction creates the visual and immutable specification together.
    """
    existing = db.scalar(select(ImageRunReview).where(
        ImageRunReview.run_id == candidate.run_id))
    if existing is not None and existing.accepted_asset_id is not None:
        asset = db.get(ImageAsset, existing.accepted_asset_id)
        root = db.get(ImageAsset, asset.root_id) if asset is not None else None
        if asset is None or root is None or root.design_id is None:
            raise WarningRevisionError(
                "review_history_invalid",
                "the prior catalog preview decision cannot be resolved",
                status_code=500,
            )
        return AcceptedCatalogPreviewRevision(
            asset_id=asset.id,
            design_id=root.design_id,
            design_version=asset.design_version or expected_design_version,
            spec_change=(),
            review_id=existing.id,
        )

    run = db.get(ImageRun, candidate.run_id)
    source = db.get(ImageAsset, candidate.source_asset_id)
    project = db.scalar(select(Project).where(
        Project.root_id == candidate.project_root_id
    ).with_for_update())
    root = db.get(ImageAsset, candidate.project_root_id)
    if (run is None or run.status not in {"preview_ready", "review_required"}
            or run.accepted_asset_id is not None):
        raise WarningRevisionError(
            "catalog_preview_run_unavailable",
            "the image run is not an uncommitted catalog preview",
            status_code=404,
        )
    if source is None or project is None or root is None or root.design_id is None:
        raise WarningRevisionError(
            "catalog_preview_project_unavailable",
            "the catalog preview source project is no longer available",
            status_code=404,
        )
    if (source.root_id != candidate.project_root_id
            or run.project_root_id != candidate.project_root_id
            or run.source_asset_id != candidate.source_asset_id):
        raise WarningRevisionError(
            "catalog_preview_source_mismatch",
            "the catalog preview does not belong to this exact project source",
        )
    active = _active_primary(db, candidate.project_root_id)
    if active is None or active.id != candidate.expected_active_asset_id:
        raise WarningRevisionError(
            "stale_asset_revision",
            "the active visual changed while this catalog preview was open",
        )
    if expected_design_version != candidate.expected_design_version:
        raise WarningRevisionError(
            "stale_design_version",
            "the catalog preview was opened against a different specification version",
        )
    latest = db.scalar(select(func.max(DesignVersion.version)).where(
        DesignVersion.design_id == root.design_id))
    if latest != expected_design_version or source.design_version != latest:
        raise WarningRevisionError(
            "stale_design_version",
            "the specification changed while this catalog preview was open",
        )
    before_row = db.get(DesignVersion, (root.design_id, expected_design_version))
    if before_row is None:
        raise WarningRevisionError(
            "spec_version_unavailable",
            "the catalog preview's exact source specification is unavailable",
            status_code=404,
        )

    source_spec = Spec.model_validate(before_row.spec)
    source_hash = hashlib.sha256(bytes(source.image)).hexdigest()
    source_spec_hash = spec_visual_hash(source_spec)
    target_spec_hash = spec_visual_hash(candidate.next_spec)
    if (candidate.source_hash != source_hash
            or candidate.source_spec_visual_hash != source_spec_hash
            or candidate.target_spec_visual_hash != target_spec_hash
            or run.source_hash != source_hash
            or run.source_spec_visual_hash != source_spec_hash
            or run.spec_visual_hash != target_spec_hash):
        raise WarningRevisionError(
            "catalog_preview_lineage_mismatch",
            "the catalog preview is not bound to this exact image and specification pair",
            status_code=422,
        )

    validated = validate_spec(candidate.next_spec, get_vocabulary())
    if not validated.ok:
        raise WarningRevisionError(
            "candidate_spec_invalid",
            "the catalog preview specification no longer passes validation",
            status_code=422,
        )
    next_payload = candidate.next_spec.model_dump(mode="json")
    changes = tuple(diff_specs(before_row.spec, next_payload))
    if not changes:
        raise WarningRevisionError(
            "spec_change_required",
            "the catalog preview has no specification change to apply",
            status_code=422,
        )

    now = utcnow()
    next_version = expected_design_version + 1
    stored = dict(next_payload)
    stored.update({
        "design_id": root.design_id,
        "version": next_version,
        "created_by": created_by,
        "created_at": now.isoformat().replace("+00:00", "Z"),
    })
    child = ImageAsset(
        id=new_id("ast"),
        root_id=source.root_id,
        parent_asset_id=source.id,
        design_id=None,
        design_version=next_version,
        capability="LOCALIZED_EDIT",
        instruction=candidate.requested_change,
        region=candidate.region_description,
        drift=candidate.drift,
        image=candidate.image_bytes,
        media_type=_media_type(candidate.image_bytes),
        created_by=created_by,
        created_at=now,
    )
    version = DesignVersion(
        design_id=root.design_id,
        version=next_version,
        spec=stored,
        created_by=created_by,
        created_at=now,
    )
    review = ImageRunReview(
        id=new_id("irr"),
        run_id=run.id,
        decision="accepted",
        accepted_asset_id=child.id,
        created_by=created_by,
    )
    project.updated_at = now
    db.add_all([version, child, review])
    try:
        if commit:
            db.commit()
        else:
            db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise WarningRevisionError(
            "stale_design_version",
            "another revision was saved before this catalog preview could apply",
        ) from exc
    except Exception:
        db.rollback()
        raise
    return AcceptedCatalogPreviewRevision(
        asset_id=child.id,
        design_id=root.design_id,
        design_version=next_version,
        spec_change=changes,
        review_id=review.id,
    )

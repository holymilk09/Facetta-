"""Canonical persistence primitives for trusted design projects.

Provider work and image QA happen outside this module. Once a candidate has
passed, this module writes its Design v1, primary image revision, optional
source references, and Project in one commit. Keeping that boundary explicit
prevents half-created projects when a provider, quality gate, or database write
fails.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Literal

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from facetta.db import (
    Design,
    DesignVersion,
    ImageAsset,
    ImageRun,
    ImageRunReview,
    Project,
    ProjectRevisionRecord,
    StudioConfirmationDraft,
    new_id,
    utcnow,
)
from facetta.image_identity import spec_visual_hash
from facetta.media import sniff_media_type
from facetta.revision_component_map_store import (
    copy_revision_component_map_for_identical_raster,
)
from facetta.spec import Spec
from facetta.studio_fact_changes import (
    StudioFactChangeError,
    prepare_studio_fact_changes,
)
from facetta.studio_confirm import studio_editable_fact_paths
from facetta.validation import validate_spec
from facetta.vocabulary import get_vocabulary

if TYPE_CHECKING:
    from facetta.db import StudioJobRecord
    from facetta.image_agent import ImageAgentError, ImageAgentResult


PRIMARY_REVISION_CAPABILITIES = frozenset({
    "CREATIVE_RENDER",
    "JEWELRY_RENDER",
    "SPEC_RENDER",
    "IMPORTED_REFERENCE",
    "LOCALIZED_EDIT",
    "GLOBAL_RESTYLE",
    "PRODUCT_PHOTO",
    "VARIATION_BRANCH",
    "RESTORED_REVISION",
})

CONFIRMABLE_PRE_SPEC_CAPABILITIES = frozenset({
    "CREATIVE_RENDER",
    "GLOBAL_RESTYLE",
    "LOCALIZED_EDIT",
})

PROVENANCE_BY_CAPABILITY = {
    "CREATIVE_RENDER": "pre_spec_creative_candidate",
    "CREATIVE_COMPARISON_THREE_QUARTER": (
        "pre_spec_creative_comparison_three_quarter"
    ),
    "CREATIVE_SOURCE": "designer_supplied_source",
    "CREATIVE_SOURCE_REGION": "designer_selected_source_region",
    "CREATIVE_REFERENCE_BOARD": "role_labeled_reference_board",
    "CREATIVE_REFERENCE_MATERIAL_STYLE": "material_style_reference",
    "CREATIVE_REFERENCE_CONSTRUCTION_DETAIL": "construction_detail_reference",
    "CREATIVE_REFERENCE_BRAND_DIRECTION": "brand_direction_reference",
    "SPEC_RENDER": "generated_spec_aligned",
    "JEWELRY_RENDER": "generated_render",
    "IMPORTED_REFERENCE": "imported_reference",
    "SOURCE_CONCEPT": "generated_concept",
    "LOCALIZED_EDIT": "localized_edit",
    "GLOBAL_RESTYLE": "visual_only_edit",
    "PRODUCT_PHOTO": "ecommerce_product_photo",
    "CLIENT_PRODUCT_PHOTO": "client_presentation_photo",
    "CLIENT_BEAUTY_RENDER": "client_presentation_beauty_render",
    "MARKETING_IMAGE": "ecommerce_marketing_derivative",
    "LINE_ART": "designer_confirmed_line_art",
    "COLORED_LINE_ART": "spec_colored_line_art",
    "ANGLE_VIEW": "derived_view",
    "MARKUP_NOTES": "markup_notes",
    "SPIN_VIDEO": "derived_video",
    "MANUFACTURING_TECHNICAL_DRAWING": "technical_artifact",
    "FACTORY_REVIEW_MOUNTING_VIEW": "designer_reviewed_mounting_proposal",
    "VARIATION_BRANCH": "studio_variation_branch",
    "RESTORED_REVISION": "restored_historical_revision",
}

CreativeSourceKind = Literal["drawing", "photograph", "finished_render"]


def is_primary_revision(asset: ImageAsset) -> bool:
    return asset.capability in PRIMARY_REVISION_CAPABILITIES


def is_canonical_revision(asset: ImageAsset) -> bool:
    """Whether an asset belongs to an accepted Variation revision history.

    Creative renders without a design-version binding are alternative directions
    awaiting selection.  They are durable provenance, but numbering them as
    revisions makes independent candidates look like edits of one another.
    """

    return is_primary_revision(asset) and not (
        asset.capability == "CREATIVE_RENDER" and asset.design_version is None
    )


def accepted_creative_candidate(
    chain: list[ImageAsset], active_asset_id: str | None,
) -> ImageAsset | None:
    """Return the creative direction on the active Variation's ancestor chain."""

    if active_asset_id is None:
        return None
    by_id = {asset.id: asset for asset in chain}
    cursor = by_id.get(active_asset_id)
    seen: set[str] = set()
    while cursor is not None and cursor.id not in seen:
        seen.add(cursor.id)
        if cursor.capability == "CREATIVE_RENDER" and cursor.design_version is None:
            return cursor
        cursor = (
            by_id.get(cursor.parent_asset_id)
            if cursor.parent_asset_id is not None else None
        )
    return None


def confirmable_pre_spec_asset(
    chain: list[ImageAsset],
    selected_asset_id: str | None,
) -> ImageAsset | None:
    """Return the one current visual that may become exact Design v1.

    A pre-spec refinement is canonical only after the designer applies it. The
    project selection therefore has to name the same asset that the canonical
    revision ordering considers active. This second comparison is intentional:
    it fails closed for stale historical rows where a child was appended but
    the selection pointer still names its parent.

    The asset must also descend from a real creative candidate and the entire
    project must remain pre-spec. A matching ``root_id`` alone is not enough to
    establish that provenance.
    """
    if selected_asset_id is None:
        return None
    by_id = {asset.id: asset for asset in chain}
    selected = by_id.get(selected_asset_id)
    root = by_id.get(selected.root_id) if selected is not None else None
    if selected is None or root is None:
        return None
    if (
        selected.capability not in CONFIRMABLE_PRE_SPEC_CAPABILITIES
        or selected.design_id is not None
        or selected.design_version is not None
        or root.design_id is not None
        or any(
            asset.design_id is not None or asset.design_version is not None
            for asset in chain
        )
    ):
        return None
    if accepted_creative_candidate(chain, selected.id) is None:
        return None

    canonical = [asset for asset in chain if is_canonical_revision(asset)]
    accepted = accepted_creative_candidate(chain, selected.id)
    if accepted is not None:
        canonical.insert(0, accepted)
    active = canonical[-1] if canonical else None
    return selected if active is not None and active.id == selected.id else None


class DesignAlreadyLinked(ValueError):
    def __init__(self, design_id: str, root_id: str):
        self.design_id = design_id
        self.root_id = root_id
        super().__init__(
            f"design '{design_id}' already belongs to project '{root_id}'")


def claim_creative_project_design(
    db: Session,
    *,
    root_id: str,
    design_id: str,
) -> bool:
    """Atomically claim one pre-spec root for exactly one confirmed design."""
    claim = db.execute(
        update(ImageAsset)
        .where(
            ImageAsset.id == root_id,
            ImageAsset.root_id == root_id,
            ImageAsset.design_id.is_(None),
        )
        .values(design_id=design_id)
        .execution_options(synchronize_session=False)
    )
    return claim.rowcount == 1


def ensure_design_chain_available(
    db: Session, design_id: str, candidate_root_id: str | None = None,
) -> None:
    """Reject a second primary root for one design.

    The partial unique index protects clean/new databases from a concurrent
    race. This explicit guard also protects upgraded legacy databases where the
    index was intentionally skipped because duplicate historical roots already
    existed and must remain readable.
    """
    roots = set(db.scalars(
        select(ImageAsset.root_id).where(
            ImageAsset.design_id == design_id,
            ImageAsset.parent_asset_id.is_(None),
        )
    ))
    conflicts = roots - ({candidate_root_id} if candidate_root_id else set())
    if conflicts:
        raise DesignAlreadyLinked(design_id, sorted(conflicts)[0])


@dataclass(frozen=True)
class SourceAssetInput:
    image: bytes
    capability: str
    instruction: str | None = None
    media_type: str | None = None
    image_run: ImageAgentResult | None = None
    reviewed_image_run_id: str | None = None


@dataclass(frozen=True)
class PersistedProjectInput:
    spec: Spec
    primary_image: bytes
    primary_capability: str
    primary_instruction: str | None = None
    primary_media_type: str | None = None
    primary_image_run: ImageAgentResult | None = None
    reviewed_primary_run_id: str | None = None
    sources: tuple[SourceAssetInput, ...] = ()


@dataclass(frozen=True)
class PersistedProjectResult:
    root_id: str
    design_id: str
    image_run_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class CreativeComparisonViewInput:
    """One metered review view derived from an exact creative candidate."""

    view: Literal["three_quarter"]
    image: bytes
    instruction: str
    image_run: ImageAgentResult


@dataclass(frozen=True)
class CreativeCandidateInput:
    image: bytes
    instruction: str
    image_run: ImageAgentResult
    comparison_views: tuple[CreativeComparisonViewInput, ...] = ()


@dataclass(frozen=True)
class PersistedCreativeProjectResult:
    root_id: str
    candidate_asset_ids: tuple[str, ...]
    image_run_ids: tuple[str, ...]


@dataclass(frozen=True)
class PersistedCreativePromotionResult:
    root_id: str
    design_id: str
    asset_id: str
    design_version: int = 1


@dataclass(frozen=True)
class PersistedProjectRevisionResult:
    asset_id: str
    root_id: str
    design_id: str
    design_version: int
    image_run_id: str | None = None


@dataclass(frozen=True)
class PersistedDerivedAssetResult:
    asset_id: str
    root_id: str
    design_id: str
    design_version: int
    image_run_id: str | None = None


def persist_project_derived_asset(
    db: Session,
    *,
    root_id: str,
    parent_asset_id: str,
    image: bytes,
    capability: str,
    instruction: str,
    design_version: int,
    created_by: str,
    image_run: ImageAgentResult | None = None,
) -> PersistedDerivedAssetResult:
    """Commit a non-revision visual artifact and its run evidence atomically."""
    if capability in PRIMARY_REVISION_CAPABILITIES:
        raise ValueError(f"'{capability}' is a primary revision, not a derived asset")
    project = db.get(Project, root_id)
    root = db.get(ImageAsset, root_id)
    parent = db.get(ImageAsset, parent_asset_id)
    if (project is None or root is None or root.design_id is None
            or parent is None or parent.root_id != root_id):
        raise ValueError("derived asset parent is not in a linked project")
    latest = db.scalar(select(DesignVersion.version).where(
        DesignVersion.design_id == root.design_id
    ).order_by(DesignVersion.version.desc()))
    if latest != design_version or parent.design_version != design_version:
        raise ValueError("design version changed before derived asset commit")
    asset = ImageAsset(
        id=new_id("ast"),
        root_id=root_id,
        parent_asset_id=parent.id,
        design_id=None,
        design_version=design_version,
        capability=capability,
        instruction=instruction,
        image=image,
        media_type=sniff_media_type(image),
        created_by=created_by,
        created_at=utcnow(),
    )
    db.add(asset)
    run_id = None
    if image_run is not None:
        from facetta.image_run_store import persist_image_agent_result

        run_id = persist_image_agent_result(
            db,
            image_run,
            project_root_id=root_id,
            source_asset_id=parent.id,
            accepted_asset_id=asset.id,
            created_by=created_by,
            commit=False,
        )
    project.updated_at = utcnow()
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return PersistedDerivedAssetResult(
        asset_id=asset.id,
        root_id=root_id,
        design_id=root.design_id,
        design_version=design_version,
        image_run_id=run_id,
    )


def persist_project_primary_revision(
    db: Session,
    *,
    root_id: str,
    image: bytes,
    capability: str,
    instruction: str,
    design_version: int,
    created_by: str,
    image_run: ImageAgentResult | None = None,
    source_asset_id: str | None = None,
) -> PersistedProjectRevisionResult:
    """Commit one accepted visual revision and its run evidence atomically."""
    if capability not in PRIMARY_REVISION_CAPABILITIES:
        raise ValueError(f"'{capability}' is not a primary revision")
    project = db.scalar(select(Project).where(
        Project.root_id == root_id
    ).with_for_update())
    root = db.get(ImageAsset, root_id)
    if project is None or root is None or root.design_id is None:
        raise ValueError("project root is not linked to a design")
    latest = db.scalar(select(DesignVersion.version).where(
        DesignVersion.design_id == root.design_id
    ).order_by(DesignVersion.version.desc()))
    if latest != design_version:
        raise ValueError("design version changed before visual revision commit")
    chain = list(db.scalars(
        select(ImageAsset).where(ImageAsset.root_id == root_id)
        .order_by(ImageAsset.created_at, ImageAsset.id)))
    chain.sort(key=lambda asset: (
        asset.id != root_id, asset.created_at, asset.id))
    primary = [asset for asset in chain if is_primary_revision(asset)]
    parent = primary[-1] if primary else root
    if source_asset_id is not None:
        selected_source = db.get(ImageAsset, source_asset_id)
        if (selected_source is None
                or selected_source.root_id != root_id):
            raise ValueError("visual revision source is not in this project")
        if selected_source.design_version != design_version:
            raise ValueError(
                "visual revision source does not represent the exact design version")
        parent = selected_source
    asset = ImageAsset(
        id=new_id("ast"),
        root_id=root_id,
        parent_asset_id=parent.id,
        design_id=None,
        design_version=design_version,
        capability=capability,
        instruction=instruction,
        image=image,
        media_type=sniff_media_type(image),
        created_by=created_by,
        created_at=utcnow(),
    )
    db.add(asset)
    run_id = None
    if image_run is not None:
        from facetta.image_run_store import persist_image_agent_result

        run_id = persist_image_agent_result(
            db,
            image_run,
            project_root_id=root_id,
            source_asset_id=parent.id,
            accepted_asset_id=asset.id,
            created_by=created_by,
            commit=False,
        )
    project.updated_at = utcnow()
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return PersistedProjectRevisionResult(
        asset_id=asset.id,
        root_id=root_id,
        design_id=root.design_id,
        design_version=design_version,
        image_run_id=run_id,
    )


def persist_project_v1(
    db: Session,
    prepared: PersistedProjectInput,
    *,
    owner: str,
    title: str,
    collection: str | None = None,
    tags: list[str] | None = None,
) -> PersistedProjectResult:
    """Atomically persist a fully generated and validated first revision."""
    if prepared.primary_capability not in PRIMARY_REVISION_CAPABILITIES:
        raise ValueError(
            f"'{prepared.primary_capability}' is not a primary revision")

    now = utcnow()
    design_id = new_id("dsn")
    root_id = new_id("ast")
    stored_spec = prepared.spec.model_dump(mode="json")
    stored_spec.update({
        "design_id": design_id,
        "version": 1,
        "created_by": owner,
        "created_at": now.isoformat().replace("+00:00", "Z"),
    })

    design = Design(
        id=design_id,
        created_by=owner,
        created_at=now,
        collection=collection,
    )
    version = DesignVersion(
        design_id=design_id,
        version=1,
        spec=stored_spec,
        created_by=owner,
        created_at=now,
    )
    root = ImageAsset(
        id=root_id,
        root_id=root_id,
        parent_asset_id=None,
        design_id=design_id,
        design_version=1,
        capability=prepared.primary_capability,
        instruction=prepared.primary_instruction,
        image=prepared.primary_image,
        media_type=(prepared.primary_media_type
                    or sniff_media_type(prepared.primary_image)),
        created_by=owner,
        created_at=now,
    )
    project = Project(
        root_id=root_id,
        owner=owner,
        collection=collection,
        title=(title.strip() or "Untitled ring")[:200],
        tags=sorted({tag.strip() for tag in (tags or []) if tag.strip()}),
        created_at=now,
        updated_at=now,
    )
    source_rows = [
        ImageAsset(
            id=new_id("ast"),
            root_id=root_id,
            parent_asset_id=root_id,
            design_id=None,
            design_version=None,
            capability=source.capability,
            instruction=source.instruction,
            image=source.image,
            media_type=source.media_type or sniff_media_type(source.image),
            created_by=owner,
            created_at=now,
        )
        for source in prepared.sources
    ]

    # One commit is the transaction boundary. A flush catches constraints
    # before commit; every exception rolls back all pending rows.
    try:
        ensure_design_chain_available(db, design_id)
        db.add_all([design, version, root, project, *source_rows])
        image_run_ids: list[str] = []
        if (prepared.primary_image_run is not None
                or any(source.image_run for source in prepared.sources)):
            from facetta.image_run_store import persist_image_agent_result

            if prepared.primary_image_run is not None:
                image_run_ids.append(persist_image_agent_result(
                    db,
                    prepared.primary_image_run,
                    project_root_id=root_id,
                    source_asset_id=(source_rows[0].id
                                     if source_rows else None),
                    accepted_asset_id=root_id,
                    created_by=owner,
                    commit=False,
                ))
            for source, row in zip(prepared.sources, source_rows):
                if source.image_run is not None:
                    image_run_ids.append(persist_image_agent_result(
                        db,
                        source.image_run,
                        project_root_id=root_id,
                        accepted_asset_id=row.id,
                        created_by=owner,
                        commit=False,
                    ))
        reviewed_bindings = [
            (prepared.reviewed_primary_run_id, root_id),
            *[
                (source.reviewed_image_run_id, row.id)
                for source, row in zip(prepared.sources, source_rows)
            ],
        ]
        for run_id, accepted_asset_id in reviewed_bindings:
            if run_id is None:
                continue
            run = db.get(ImageRun, run_id)
            if run is None or run.status != "review_required":
                raise ValueError(
                    f"image run '{run_id}' is not awaiting designer review")
            db.add(ImageRunReview(
                id=new_id("irr"),
                run_id=run_id,
                decision="accepted",
                accepted_asset_id=accepted_asset_id,
                created_by=owner,
                created_at=now,
            ))
            image_run_ids.append(run_id)
        db.flush()
        db.commit()
    except Exception:
        db.rollback()
        raise
    return PersistedProjectResult(
        root_id=root_id,
        design_id=design_id,
        image_run_ids=tuple(image_run_ids),
    )


def persist_creative_project(
    db: Session,
    *,
    source_image: bytes,
    source_media_type: str,
    source_kind: CreativeSourceKind,
    render_source_image: bytes | None = None,
    render_source_media_type: str | None = None,
    render_source_instruction: str | None = None,
    render_source_capability: Literal[
        "CREATIVE_SOURCE_REGION", "CREATIVE_REFERENCE_BOARD"
    ] = "CREATIVE_SOURCE_REGION",
    reference_sources: tuple[SourceAssetInput, ...] = (),
    candidates: tuple[CreativeCandidateInput, ...],
    owner: str,
    title: str,
    collection: str | None = None,
    tags: list[str] | None = None,
    studio_job: StudioJobRecord | None = None,
    rejected_image_results: tuple[ImageAgentResult, ...] = (),
) -> PersistedCreativeProjectResult:
    """Atomically store a pre-spec source and its reviewable render variants.

    No Design or DesignVersion is created here.  Creative candidates are useful
    project revisions, but they remain structurally incapable of factory
    approval/export until a designer confirms a specification in a later
    promotion step.
    """
    if not candidates:
        raise ValueError("a creative project requires at least one candidate")
    if source_kind not in {"drawing", "photograph", "finished_render"}:
        raise ValueError("creative source kind is invalid")
    if any(not candidate.image for candidate in candidates):
        raise ValueError("creative candidate image must not be empty")
    for candidate in candidates:
        views = [view.view for view in candidate.comparison_views]
        if len(views) != len(set(views)) or any(
            view != "three_quarter" for view in views
        ):
            raise ValueError("creative comparison views must be unique and supported")
        if any(not view.image for view in candidate.comparison_views):
            raise ValueError("creative comparison view image must not be empty")
    allowed_reference_capabilities = {
        "CREATIVE_REFERENCE_MATERIAL_STYLE",
        "CREATIVE_REFERENCE_CONSTRUCTION_DETAIL",
        "CREATIVE_REFERENCE_BRAND_DIRECTION",
    }
    if any(
        not source.image or source.capability not in allowed_reference_capabilities
        for source in reference_sources
    ):
        raise ValueError("creative role reference source is invalid")
    if len({source.capability for source in reference_sources}) != len(reference_sources):
        raise ValueError("creative role reference capabilities must be unique")

    now = utcnow()
    root_id = new_id("ast")
    root = ImageAsset(
        id=root_id,
        root_id=root_id,
        parent_asset_id=None,
        design_id=None,
        design_version=None,
        capability="CREATIVE_SOURCE",
        source_kind=source_kind,
        instruction="Designer-supplied creative source",
        image=source_image,
        media_type=source_media_type,
        created_by=owner,
        created_at=now,
    )
    render_source = None
    if render_source_image is not None:
        if not render_source_image:
            raise ValueError("creative source region image must not be empty")
        render_source = ImageAsset(
            id=new_id("ast"),
            root_id=root_id,
            parent_asset_id=root_id,
            design_id=None,
            design_version=None,
            capability=render_source_capability,
            source_kind=source_kind,
            instruction=(render_source_instruction or "Designer-selected source region"),
            image=render_source_image,
            media_type=(
                render_source_media_type or sniff_media_type(render_source_image)
            ),
            created_by=owner,
            created_at=now,
        )
    render_source_id = render_source.id if render_source is not None else root_id
    reference_rows = [
        ImageAsset(
            id=new_id("ast"),
            root_id=root_id,
            parent_asset_id=root_id,
            design_id=None,
            design_version=None,
            capability=source.capability,
            instruction=source.instruction,
            image=source.image,
            media_type=source.media_type or sniff_media_type(source.image),
            created_by=owner,
            created_at=now,
        )
        for source in reference_sources
    ]
    project = Project(
        root_id=root_id,
        owner=owner,
        collection=collection,
        title=(title.strip() or "Untitled jewelry concept")[:200],
        tags=sorted({tag.strip() for tag in (tags or []) if tag.strip()}),
        created_at=now,
        updated_at=now,
    )
    candidate_rows = [
        ImageAsset(
            id=new_id("ast"),
            root_id=root_id,
            parent_asset_id=render_source_id,
            design_id=None,
            design_version=None,
            capability="CREATIVE_RENDER",
            source_kind=source_kind,
            instruction=candidate.instruction,
            image=candidate.image,
            media_type=sniff_media_type(candidate.image),
            created_by=owner,
            created_at=now,
        )
        for candidate in candidates
    ]
    comparison_rows = [
        (
            candidate,
            view,
            ImageAsset(
                id=new_id("ast"),
                root_id=root_id,
                parent_asset_id=candidate_row.id,
                design_id=None,
                design_version=None,
                capability="CREATIVE_COMPARISON_THREE_QUARTER",
                source_kind=source_kind,
                instruction=view.instruction,
                image=view.image,
                media_type=sniff_media_type(view.image),
                created_by=owner,
                created_at=now,
            ),
        )
        for candidate, candidate_row in zip(candidates, candidate_rows)
        for view in candidate.comparison_views
    ]
    try:
        if studio_job is not None:
            if (
                studio_job.owner != owner
                or studio_job.action_id != "create"
                or studio_job.status != "running"
                or studio_job.active_design_id is not None
                or studio_job.source_revision_id is not None
                # Comparison views are an included internal companion to each
                # requested direction. They are evidenced, but never counted
                # as an additional billable Studio output.
                or studio_job.requested_outputs != len(candidates)
                or studio_job.completed_outputs != 0
                or studio_job.charged_outputs != 0
            ):
                raise ValueError(
                    "Studio Create job is not an unbound canonical request"
                )
            studio_job.active_design_id = root_id
            studio_job.status = "reviewing"
            studio_job.progress = max(studio_job.progress, 0.9)
            studio_job.error_code = None
            studio_job.updated_at = now
        db.add_all([
            root,
            project,
            *([render_source] if render_source is not None else []),
            *reference_rows,
            *candidate_rows,
            *(row for _candidate, _view, row in comparison_rows),
        ])
        from facetta.image_run_store import persist_image_agent_result

        image_run_ids = [
            persist_image_agent_result(
                db,
                candidate.image_run,
                project_root_id=root_id,
                source_asset_id=render_source_id,
                accepted_asset_id=row.id,
                created_by=owner,
                commit=False,
            )
            for candidate, row in zip(candidates, candidate_rows)
        ]
        image_run_ids.extend(
            persist_image_agent_result(
                db,
                view.image_run,
                project_root_id=root_id,
                source_asset_id=candidate_row.id,
                accepted_asset_id=row.id,
                created_by=owner,
                commit=False,
            )
            for candidate, candidate_row in zip(candidates, candidate_rows)
            for _owner_candidate, view, row in comparison_rows
            if _owner_candidate is candidate
        )
        image_run_ids.extend(
            persist_image_agent_result(
                db,
                rejected,
                project_root_id=root_id,
                source_asset_id=render_source_id,
                created_by=owner,
                status_override="failed",
                error_category_override="quality",
                commit=False,
            )
            for rejected in rejected_image_results
        )
        db.flush()
        db.commit()
    except Exception:
        db.rollback()
        raise
    return PersistedCreativeProjectResult(
        root_id=root_id,
        candidate_asset_ids=tuple(row.id for row in candidate_rows),
        image_run_ids=tuple(image_run_ids),
    )


def persist_prompt_creative_project(
    db: Session,
    *,
    candidates: tuple[CreativeCandidateInput, ...],
    reference_board: SourceAssetInput | None = None,
    reference_sources: tuple[SourceAssetInput, ...] = (),
    owner: str,
    title: str,
    collection: str | None = None,
    tags: list[str] | None = None,
    studio_job: StudioJobRecord | None = None,
    failed_image_errors: tuple[ImageAgentError, ...] = (),
    rejected_image_results: tuple[ImageAgentResult, ...] = (),
) -> PersistedCreativeProjectResult:
    """Atomically store independent prompt-generated, pre-spec candidates.

    The first candidate is the chain root because there is no uploaded source
    asset. Every candidate remains a selectable primary creative revision with
    no Design or DesignVersion until explicit designer promotion.
    """
    if not candidates:
        raise ValueError("a creative project requires at least one candidate")
    if any(not candidate.image for candidate in candidates):
        raise ValueError("creative candidate image must not be empty")
    for candidate in candidates:
        views = [view.view for view in candidate.comparison_views]
        if len(views) != len(set(views)) or any(
            view != "three_quarter" for view in views
        ):
            raise ValueError("creative comparison views must be unique and supported")
        if any(not view.image for view in candidate.comparison_views):
            raise ValueError("creative comparison view image must not be empty")
    if any(error.plan is None for error in failed_image_errors):
        raise ValueError("creative failure evidence requires an image plan")
    if reference_board is not None and (
        not reference_board.image
        or reference_board.capability != "CREATIVE_REFERENCE_BOARD"
    ):
        raise ValueError("prompt creative reference board is invalid")
    allowed_reference_capabilities = {
        "CREATIVE_REFERENCE_MATERIAL_STYLE",
        "CREATIVE_REFERENCE_CONSTRUCTION_DETAIL",
        "CREATIVE_REFERENCE_BRAND_DIRECTION",
    }
    if any(
        not source.image or source.capability not in allowed_reference_capabilities
        for source in reference_sources
    ):
        raise ValueError("prompt creative role reference source is invalid")
    if len({source.capability for source in reference_sources}) != len(reference_sources):
        raise ValueError("prompt creative role reference capabilities must be unique")
    if (reference_board is None) != (len(reference_sources) == 0):
        raise ValueError(
            "prompt creative advisory references require one canonical board"
        )

    now = utcnow()
    root_id = new_id("ast")
    rows = [
        ImageAsset(
            id=(root_id if index == 0 else new_id("ast")),
            root_id=root_id,
            parent_asset_id=(None if index == 0 else root_id),
            design_id=None,
            design_version=None,
            capability="CREATIVE_RENDER",
            instruction=candidate.instruction,
            image=candidate.image,
            media_type=sniff_media_type(candidate.image),
            created_by=owner,
            created_at=now,
        )
        for index, candidate in enumerate(candidates)
    ]
    comparison_rows = [
        (
            candidate,
            view,
            ImageAsset(
                id=new_id("ast"),
                root_id=root_id,
                parent_asset_id=candidate_row.id,
                design_id=None,
                design_version=None,
                capability="CREATIVE_COMPARISON_THREE_QUARTER",
                instruction=view.instruction,
                image=view.image,
                media_type=sniff_media_type(view.image),
                created_by=owner,
                created_at=now,
            ),
        )
        for candidate, candidate_row in zip(candidates, rows)
        for view in candidate.comparison_views
    ]
    reference_board_row = (
        ImageAsset(
            id=new_id("ast"),
            root_id=root_id,
            parent_asset_id=root_id,
            design_id=None,
            design_version=None,
            capability="CREATIVE_REFERENCE_BOARD",
            instruction=reference_board.instruction,
            image=reference_board.image,
            media_type=(
                reference_board.media_type
                or sniff_media_type(reference_board.image)
            ),
            created_by=owner,
            created_at=now,
        )
        if reference_board is not None else None
    )
    reference_rows = [
        ImageAsset(
            id=new_id("ast"),
            root_id=root_id,
            parent_asset_id=root_id,
            design_id=None,
            design_version=None,
            capability=source.capability,
            instruction=source.instruction,
            image=source.image,
            media_type=source.media_type or sniff_media_type(source.image),
            created_by=owner,
            created_at=now,
        )
        for source in reference_sources
    ]
    project = Project(
        root_id=root_id,
        owner=owner,
        collection=collection,
        title=(title.strip() or "Untitled jewelry concept")[:200],
        tags=sorted({tag.strip() for tag in (tags or []) if tag.strip()}),
        created_at=now,
        updated_at=now,
    )
    try:
        if studio_job is not None:
            if (
                studio_job.owner != owner
                or studio_job.action_id != "create"
                or studio_job.status != "running"
                or studio_job.active_design_id is not None
                or studio_job.source_revision_id is not None
                # Comparison views are included review evidence for each
                # direction, not a separately charged Studio output.
                or len(candidates) > studio_job.requested_outputs
                or studio_job.completed_outputs != 0
                or studio_job.charged_outputs != 0
            ):
                raise ValueError(
                    "Studio Create job is not an unbound canonical request"
                )
            studio_job.active_design_id = root_id
            studio_job.status = "reviewing"
            studio_job.progress = max(studio_job.progress, 0.9)
            studio_job.error_code = None
            studio_job.updated_at = now
        db.add_all([
            *rows,
            project,
            *([reference_board_row] if reference_board_row is not None else []),
            *reference_rows,
            *(row for _candidate, _view, row in comparison_rows),
        ])
        from facetta.image_run_store import (
            persist_image_agent_failure,
            persist_image_agent_result,
        )

        image_run_ids = [
            persist_image_agent_result(
                db,
                candidate.image_run,
                project_root_id=root_id,
                source_asset_id=(
                    reference_board_row.id
                    if reference_board_row is not None else None
                ),
                accepted_asset_id=row.id,
                created_by=owner,
                commit=False,
            )
            for candidate, row in zip(candidates, rows)
        ]
        image_run_ids.extend(
            persist_image_agent_result(
                db,
                view.image_run,
                project_root_id=root_id,
                source_asset_id=candidate_row.id,
                accepted_asset_id=row.id,
                created_by=owner,
                commit=False,
            )
            for candidate, candidate_row in zip(candidates, rows)
            for _owner_candidate, view, row in comparison_rows
            if _owner_candidate is candidate
        )
        image_run_ids.extend(
            persist_image_agent_failure(
                db,
                error.plan,
                error,
                project_root_id=root_id,
                source_asset_id=(
                    reference_board_row.id
                    if reference_board_row is not None else None
                ),
                created_by=owner,
                commit=False,
            )
            for error in failed_image_errors
            if error.plan is not None
        )
        image_run_ids.extend(
            persist_image_agent_result(
                db,
                rejected,
                project_root_id=root_id,
                source_asset_id=(
                    reference_board_row.id
                    if reference_board_row is not None else None
                ),
                created_by=owner,
                status_override="failed",
                error_category_override="quality",
                commit=False,
            )
            for rejected in rejected_image_results
        )
        db.flush()
        db.commit()
    except Exception:
        db.rollback()
        raise
    return PersistedCreativeProjectResult(
        root_id=root_id,
        candidate_asset_ids=tuple(row.id for row in rows),
        image_run_ids=tuple(image_run_ids),
    )


def promote_creative_candidate(
    db: Session,
    *,
    root_id: str,
    candidate_asset_id: str,
    created_by: str,
    confirmation_token: str,
    fact_corrections: dict[str, object] | None = None,
) -> PersistedCreativePromotionResult:
    """Create spec v1 from one explicitly selected creative candidate.

    The original candidate stays pre-spec provenance. A byte-identical new
    primary revision receives the exact specification binding, making the
    transition visible and preventing approval of an unconfirmed alternative.
    Source-review questions remain on the specification as optional Factory
    blockers; they do not prevent a designer from preserving and refining a
    Studio direction.
    """
    # Serialize confirmation against both the mutable project selection and
    # the exact candidate bytes the designer reviewed.  SQLite ignores
    # ``FOR UPDATE`` but still gets the same comparisons inside the single
    # write transaction; production databases additionally acquire row locks.
    token_sha256 = hashlib.sha256(confirmation_token.encode("utf-8")).hexdigest()
    draft = db.scalar(
        select(StudioConfirmationDraft)
        .where(StudioConfirmationDraft.token_sha256 == token_sha256)
        .with_for_update()
    )
    if draft is None:
        raise ValueError("confirmation draft is invalid or unavailable")
    project = db.scalar(
        select(Project)
        .where(Project.root_id == root_id)
        .with_for_update()
    )
    candidate = db.scalar(
        select(ImageAsset)
        .where(ImageAsset.id == candidate_asset_id)
        .with_for_update()
    )
    root = (
        candidate
        if candidate is not None and candidate.id == root_id
        else db.scalar(
            select(ImageAsset)
            .where(ImageAsset.id == root_id)
            .with_for_update()
        )
    )
    if project is None or root is None:
        raise ValueError("creative project does not exist")
    now = utcnow()
    expires_at = draft.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=now.tzinfo)
    if draft.consumed_at is not None:
        raise ValueError("confirmation draft has already been used")
    if expires_at <= now:
        raise ValueError("confirmation draft has expired")
    if draft.owner != created_by:
        raise ValueError("confirmation draft belongs to another designer")
    if draft.project_root_id != root_id:
        raise ValueError("confirmation draft belongs to another project")
    if draft.candidate_asset_id != candidate_asset_id:
        raise ValueError("confirmation draft belongs to another candidate")
    chain = list(db.scalars(
        select(ImageAsset)
        .where(ImageAsset.root_id == root_id)
        .order_by(ImageAsset.created_at, ImageAsset.id)
        .with_for_update()
    ))
    chain.sort(key=lambda asset: (
        asset.id != root_id, asset.created_at, asset.id))
    confirmable = confirmable_pre_spec_asset(
        chain,
        project.selected_candidate_asset_id,
    )
    if confirmable is None or confirmable.id != candidate_asset_id:
        raise ValueError(
            "the selected pre-spec revision changed before confirmation"
        )
    candidate = confirmable

    candidate_sha256 = hashlib.sha256(bytes(candidate.image)).hexdigest()
    if candidate_sha256 != draft.candidate_sha256:
        raise ValueError(
            "the selected creative candidate bytes changed before confirmation"
        )
    confirmed_spec = Spec.model_validate(draft.spec)
    confirmation_spec_visual_hash = spec_visual_hash(confirmed_spec)
    if confirmation_spec_visual_hash != draft.spec_visual_hash:
        raise ValueError("the confirmed design facts changed before promotion")
    try:
        corrections = fact_corrections or {}
        hidden_paths = sorted(
            set(corrections) - studio_editable_fact_paths(confirmed_spec)
        )
        if hidden_paths:
            raise StudioFactChangeError(
                "fact_path_not_reviewable",
                "these facts were not editable in Starting Facts: "
                + ", ".join(hidden_paths),
            )
        prepared = prepare_studio_fact_changes(
            confirmed_spec, corrections,
        )
        validated = validate_spec(prepared.spec, get_vocabulary())
        if not validated.ok:
            raise StudioFactChangeError(
                "fact_revision_invalid",
                "the corrected facts do not form a valid jewelry specification",
            )
    except StudioFactChangeError:
        db.rollback()
        raise
    spec = validated.spec
    current_spec_visual_hash = spec_visual_hash(spec)
    design_id = new_id("dsn")
    stored_spec = spec.model_dump(mode="json")
    stored_spec.update({
        "design_id": design_id,
        "version": 1,
        "created_by": created_by,
        "created_at": now.isoformat().replace("+00:00", "Z"),
    })
    design = Design(
        id=design_id,
        created_by=created_by,
        created_at=now,
        collection=project.collection,
    )
    version = DesignVersion(
        design_id=design_id,
        version=1,
        spec=stored_spec,
        created_by=created_by,
        created_at=now,
    )
    promoted = ImageAsset(
        id=new_id("ast"),
        root_id=root_id,
        parent_asset_id=candidate.id,
        design_id=None,
        design_version=1,
        capability="IMPORTED_REFERENCE",
        instruction="Designer-confirmed creative candidate and specification",
        image=bytes(candidate.image),
        media_type=candidate.media_type,
        created_by=created_by,
        created_at=now,
    )
    record = ProjectRevisionRecord(
        id=new_id("prr"),
        asset_id=promoted.id,
        action="edit",
        raw_intent={
            "kind": "confirm_design",
            "selected_candidate_asset_id": candidate.id,
            "candidate_sha256": candidate_sha256,
            "confirmation_spec_visual_hash": confirmation_spec_visual_hash,
            "spec_visual_hash": current_spec_visual_hash,
            "fact_corrections": dict(prepared.corrected_values),
            "original_fact_values": dict(prepared.original_values),
        },
        interpretation={
            "operation": "promote_creative_candidate",
            "design_id": design_id,
            "design_version": 1,
            "source_asset_id": candidate.id,
            "factory_authority": False,
            "fact_authority": {
                path: "designer_supplied"
                for path in prepared.corrected_values
            },
            "derived_fact_adjustments": {
                path: {
                    "before": prepared.derived_original_values[path],
                    "after": value,
                    "authority": "deterministic_component_rule",
                }
                for path, value in prepared.derived_values.items()
            },
            "untouched_inferred_facts_preserved": True,
        },
        change_summary=(
            "Confirmed design facts for the selected visual and created "
            "specification version 1; factory readiness remains separate."
        ),
        created_by=created_by,
        created_at=now,
    )
    project.updated_at = now
    draft.consumed_at = now
    try:
        # Insert the target design first so databases with immediate foreign
        # keys can accept the root claim. The conditional update is the
        # cross-database single-winner primitive: unlike row locks, it also
        # protects SQLite where ``FOR UPDATE`` is ignored.
        db.add_all([design, version])
        db.flush()
        if not claim_creative_project_design(
            db, root_id=root_id, design_id=design_id
        ):
            raise ValueError("creative project has already been promoted")
        db.add_all([promoted, record])
        ensure_design_chain_available(db, design_id, root_id)
        db.flush()
        copy_revision_component_map_for_identical_raster(
            db,
            source_asset_id=candidate.id,
            child_asset_id=promoted.id,
            child_image_bytes=bytes(promoted.image),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return PersistedCreativePromotionResult(
        root_id=root_id,
        design_id=design_id,
        asset_id=promoted.id,
    )


QualityVerdict = Literal["pass", "warn", "fail"]


@dataclass(frozen=True)
class BriefProjectGeneration:
    """Output contract implemented by the closed-loop image agent.

    Only ``pass`` may be persisted automatically. ``warn`` is a candidate for
    explicit designer review, and ``fail`` is terminal; neither is revision 1.
    """

    concept_image: bytes
    spec_render: bytes
    spec: Spec | None
    quality_verdict: QualityVerdict
    quality_report: dict[str, object]
    corrections: tuple[str, ...] = ()
    read: dict[str, object] = field(default_factory=dict)
    run_id: str | None = None
    concept_run: ImageAgentResult | None = None
    spec_render_run: ImageAgentResult | None = None


BriefProjectGenerator = Callable[[str, int], BriefProjectGeneration]


class BriefProjectGeneratorUnavailable(RuntimeError):
    pass


def unavailable_brief_project_generator(
    brief: str, variant: int,
) -> BriefProjectGeneration:
    """Explicit disabled adapter for deployments that turn providers off."""
    del brief, variant
    raise BriefProjectGeneratorUnavailable(
        "the trusted brief image agent is not configured")


def get_brief_project_generator() -> BriefProjectGenerator:
    """Production seam; tests can still inject deterministic generators."""
    from facetta.trusted_brief import generate_trusted_brief_project

    return generate_trusted_brief_project

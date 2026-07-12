"""Canonical persistence primitives for trusted design projects.

Provider work and image QA happen outside this module. Once a candidate has
passed, this module writes its Design v1, primary image revision, optional
source references, and Project in one commit. Keeping that boundary explicit
prevents half-created projects when a provider, quality gate, or database write
fails.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from facetta.db import (
    Design,
    DesignVersion,
    ImageAsset,
    ImageRun,
    ImageRunReview,
    Project,
    new_id,
    utcnow,
)
from facetta.media import sniff_media_type
from facetta.spec import Spec

if TYPE_CHECKING:
    from facetta.image_agent import ImageAgentResult


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

PROVENANCE_BY_CAPABILITY = {
    "CREATIVE_RENDER": "pre_spec_creative_candidate",
    "CREATIVE_SOURCE": "designer_supplied_source",
    "CREATIVE_SOURCE_REGION": "designer_selected_source_region",
    "SPEC_RENDER": "generated_spec_aligned",
    "JEWELRY_RENDER": "generated_render",
    "IMPORTED_REFERENCE": "imported_reference",
    "SOURCE_CONCEPT": "generated_concept",
    "LOCALIZED_EDIT": "localized_edit",
    "GLOBAL_RESTYLE": "visual_only_edit",
    "PRODUCT_PHOTO": "ecommerce_product_photo",
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


def is_primary_revision(asset: ImageAsset) -> bool:
    return asset.capability in PRIMARY_REVISION_CAPABILITIES


class DesignAlreadyLinked(ValueError):
    def __init__(self, design_id: str, root_id: str):
        self.design_id = design_id
        self.root_id = root_id
        super().__init__(
            f"design '{design_id}' already belongs to project '{root_id}'")


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
class CreativeCandidateInput:
    image: bytes
    instruction: str
    image_run: ImageAgentResult


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
    project = db.get(Project, root_id)
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
    render_source_image: bytes | None = None,
    render_source_media_type: str | None = None,
    render_source_instruction: str | None = None,
    candidates: tuple[CreativeCandidateInput, ...],
    owner: str,
    title: str,
    collection: str | None = None,
    tags: list[str] | None = None,
) -> PersistedCreativeProjectResult:
    """Atomically store a pre-spec source and its reviewable render variants.

    No Design or DesignVersion is created here.  Creative candidates are useful
    project revisions, but they remain structurally incapable of factory
    approval/export until a designer confirms a specification in a later
    promotion step.
    """
    if not candidates:
        raise ValueError("a creative project requires at least one candidate")
    if any(not candidate.image for candidate in candidates):
        raise ValueError("creative candidate image must not be empty")

    now = utcnow()
    root_id = new_id("ast")
    root = ImageAsset(
        id=root_id,
        root_id=root_id,
        parent_asset_id=None,
        design_id=None,
        design_version=None,
        capability="CREATIVE_SOURCE",
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
            capability="CREATIVE_SOURCE_REGION",
            instruction=(render_source_instruction or "Designer-selected source region"),
            image=render_source_image,
            media_type=(
                render_source_media_type or sniff_media_type(render_source_image)
            ),
            created_by=owner,
            created_at=now,
        )
    render_source_id = render_source.id if render_source is not None else root_id
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
            instruction=candidate.instruction,
            image=candidate.image,
            media_type=sniff_media_type(candidate.image),
            created_by=owner,
            created_at=now,
        )
        for candidate in candidates
    ]
    try:
        db.add_all([
            root,
            project,
            *([render_source] if render_source is not None else []),
            *candidate_rows,
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
    owner: str,
    title: str,
    collection: str | None = None,
    tags: list[str] | None = None,
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
        db.add_all([*rows, project])
        from facetta.image_run_store import persist_image_agent_result

        image_run_ids = [
            persist_image_agent_result(
                db,
                candidate.image_run,
                project_root_id=root_id,
                source_asset_id=None,
                accepted_asset_id=row.id,
                created_by=owner,
                commit=False,
            )
            for candidate, row in zip(candidates, rows)
        ]
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
    spec: Spec,
    created_by: str,
) -> PersistedCreativePromotionResult:
    """Create spec v1 from one explicitly selected creative candidate.

    The original candidate stays pre-spec provenance. A byte-identical new
    primary revision receives the exact specification binding, making the
    transition visible and preventing approval of an unconfirmed alternative.
    """
    project = db.get(Project, root_id)
    root = db.get(ImageAsset, root_id)
    candidate = db.get(ImageAsset, candidate_asset_id)
    if project is None or root is None:
        raise ValueError("creative project does not exist")
    if root.design_id is not None:
        raise ValueError("creative project has already been promoted")
    if (candidate is None
            or candidate.root_id != root_id
            or candidate.capability != "CREATIVE_RENDER"):
        raise ValueError("selected asset is not a creative candidate in this project")

    now = utcnow()
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
    root.design_id = design_id
    project.updated_at = now
    try:
        db.add_all([design, version, promoted])
        ensure_design_chain_available(db, design_id, root_id)
        db.flush()
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

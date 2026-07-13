"""Design-family branching and append-only Studio restoration services."""

from __future__ import annotations

from dataclasses import dataclass

import hashlib

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from facetta.db import (
    Design,
    DesignFamily,
    DesignVersion,
    ImageAsset,
    ImageRun,
    ImageRunReview,
    Project,
    ProjectRevisionRecord,
    new_id,
    utcnow,
)
from facetta.project_backbone import (
    accepted_creative_candidate,
    is_canonical_revision,
    is_primary_revision,
)
from facetta.catalog_component_targeting import (
    STRUCTURAL_CATALOG_PATHS,
    prepare_catalog_child_component_map,
    rebind_prepared_catalog_child_component_map,
)
from facetta.revision_component_map import ComponentMapError
from facetta.revision_component_map_store import add_revision_component_map
from facetta.revision_component_map_store import (
    copy_revision_component_map_for_identical_raster,
)
from facetta.specdiff import diff_specs, summarize_changes
from facetta.studio_visual_candidates import StudioVisualCandidate


class StudioHistoryError(RuntimeError):
    def __init__(self, code: str, detail: str, *, status_code: int = 409) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status_code = status_code


def _sha256(asset: ImageAsset) -> str:
    return hashlib.sha256(bytes(asset.image)).hexdigest()


def _verified_revision_hash(
    db: Session,
    asset: ImageAsset,
    *,
    mismatch_code: str,
) -> str:
    """Return canonical bytes' hash, rejecting recorded-lineage drift.

    Historical projects created before hash-bound revision records remain
    readable. Once a revision has a recorded output hash, branching and
    restoration fail closed if its bytes no longer match that evidence.
    """

    actual = _sha256(asset)
    record = db.scalar(
        select(ProjectRevisionRecord).where(ProjectRevisionRecord.asset_id == asset.id)
    )
    if record is None:
        return actual
    expected = (record.interpretation or {}).get("output_sha256")
    if expected is not None and expected != actual:
        raise StudioHistoryError(
            mismatch_code,
            "the selected revision bytes no longer match recorded lineage",
            status_code=422,
        )
    return actual


@dataclass(frozen=True)
class VariationBranchResult:
    family_id: str
    project_root_id: str
    asset_id: str
    design_id: str | None
    design_version: int | None
    variation_index: int


def fork_preview_candidate_variation(
    db: Session,
    *,
    kind: str,
    run_id: str,
    candidate_id: str,
    variation_label: str,
    created_by: str,
) -> VariationBranchResult:
    """Save reviewed candidate bytes directly into an independent sibling.

    The active project is never first mutated or advanced. Candidate lineage,
    the sibling asset/project, optional catalog Design v1, revision evidence,
    review decision, and terminal candidate state commit as one transaction.
    """

    from facetta.catalog_preview_candidates import (
        CatalogPreviewUnavailable,
        lock_catalog_preview_candidate_for_decision,
    )
    from facetta.studio_visual_candidates import (
        StudioVisualCandidateUnavailable,
        lock_studio_visual_candidate_for_decision,
    )
    from facetta.studio_markup_candidates import (
        StudioMarkupCandidateUnavailable,
        lock_studio_markup_candidate_for_decision,
    )

    label = variation_label.strip()
    if not label:
        raise StudioHistoryError(
            "variation_label_required",
            "name the variation before saving it",
            status_code=422,
        )
    try:
        if kind == "studio_visual":
            candidate, candidate_record = lock_studio_visual_candidate_for_decision(
                db,
                run_id,
                candidate_id,
                owner=created_by,
            )
            next_spec = None
        elif kind == "catalog_revision":
            candidate, candidate_record = lock_catalog_preview_candidate_for_decision(
                db,
                run_id,
                candidate_id,
                owner=created_by,
            )
            next_spec = candidate.next_spec
        elif kind == "studio_markup":
            candidate, candidate_record = lock_studio_markup_candidate_for_decision(
                db,
                run_id,
                candidate_id,
                owner=created_by,
            )
            next_spec = candidate.next_spec
            if next_spec is None:
                # Appearance-only exact refinements still fork the source's
                # confirmed design truth. A sibling must not silently become
                # a pre-spec project merely because its pixels changed while
                # its specification stayed identical.
                source_root = db.get(ImageAsset, candidate.project_root_id)
                source_version = (
                    db.get(
                        DesignVersion,
                        (
                            source_root.design_id,
                            candidate.design_version,
                        ),
                    )
                    if source_root is not None and source_root.design_id is not None
                    else None
                )
                if source_version is None:
                    raise StudioHistoryError(
                        "preview_candidate_spec_unavailable",
                        "the exact source specification is unavailable",
                        status_code=404,
                    )
                from facetta.spec import Spec

                next_spec = Spec.model_validate(source_version.spec)
        else:
            raise StudioHistoryError(
                "preview_candidate_kind_invalid",
                "the preview candidate kind is invalid",
                status_code=422,
            )
    except (
        StudioVisualCandidateUnavailable,
        CatalogPreviewUnavailable,
        StudioMarkupCandidateUnavailable,
    ) as exc:
        raise StudioHistoryError(
            "preview_candidate_unavailable",
            str(exc),
            status_code=410,
        ) from exc

    project = db.scalar(
        select(Project)
        .where(Project.root_id == candidate.project_root_id)
        .with_for_update()
    )
    source = db.get(ImageAsset, candidate.source_asset_id)
    run = db.get(ImageRun, run_id)
    if (
        project is None
        or source is None
        or run is None
        or project.owner != created_by
        or source.root_id != project.root_id
        or run.project_root_id != project.root_id
        or run.source_asset_id != source.id
        or run.created_by != created_by
        or run.status not in {"preview_ready", "review_required"}
        or run.accepted_asset_id is not None
    ):
        raise StudioHistoryError(
            "preview_candidate_unavailable",
            "the preview candidate lineage is unavailable",
            status_code=410,
        )

    new_root_id = new_id("ast")
    child_component_map = None
    if kind == "catalog_revision":
        assert next_spec is not None
        try:
            source_root = db.get(ImageAsset, source.root_id)
            source_version = (
                db.get(
                    DesignVersion,
                    (source_root.design_id, source.design_version),
                )
                if source_root is not None
                and source_root.design_id is not None
                and source.design_version is not None
                else None
            )
            if source_version is None:
                raise ComponentMapError(
                    "the exact source specification is unavailable",
                    code="spec_version_unavailable",
                )
            if candidate.component_path in STRUCTURAL_CATALOG_PATHS:
                if candidate.proposed_child_component_map is None:
                    raise ComponentMapError(
                        "the structural preview has no reviewed child component map",
                        code="component_mapping_unresolved",
                    )
                child_component_map = rebind_prepared_catalog_child_component_map(
                    candidate.proposed_child_component_map,
                    child_asset_id=new_root_id,
                    child_image=candidate.image_bytes,
                )
            else:
                candidate_changes = diff_specs(
                    source_version.spec,
                    next_spec.model_dump(mode="json"),
                )
                child_component_map = prepare_catalog_child_component_map(
                    db,
                    source_asset_id=source.id,
                    source_image=bytes(source.image),
                    child_asset_id=new_root_id,
                    child_image=candidate.image_bytes,
                    jewelry_type=next_spec.jewelry_type,
                    component_path=candidate.component_path,
                    target_component_ids=candidate.target_component_ids,
                    changed_spec_paths=tuple(
                        str(change["path"]) for change in candidate_changes
                    ),
                    instruction=candidate.requested_change,
                )
        except ComponentMapError as exc:
            db.rollback()
            raise StudioHistoryError(
                exc.code,
                exc.detail,
                status_code=(
                    409 if exc.code == "component_mapping_unresolved" else 422
                ),
            ) from exc

    family = ensure_project_family(db, project)
    if family.owner != created_by:
        raise StudioHistoryError(
            "design_family_owner_mismatch",
            "the project and design family have different owners",
            status_code=422,
        )
    highest = (
        db.scalar(
            select(func.max(Project.variation_index)).where(
                Project.family_id == family.id
            )
        )
        or 1
    )
    variation_index = highest + 1
    now = utcnow()
    design_id: str | None = None
    design_version: int | None = None
    if next_spec is not None:
        design_id = new_id("dsn")
        design_version = 1
        stored_spec = next_spec.model_dump(mode="json")
        stored_spec.update(
            {
                "design_id": design_id,
                "version": 1,
                "created_by": created_by,
                "created_at": now.isoformat().replace("+00:00", "Z"),
            }
        )
        db.add_all(
            [
                Design(
                    id=design_id,
                    created_by=created_by,
                    created_at=now,
                    collection=project.collection,
                ),
                DesignVersion(
                    design_id=design_id,
                    version=1,
                    spec=stored_spec,
                    created_by=created_by,
                    created_at=now,
                ),
            ]
        )

    new_asset = ImageAsset(
        id=new_root_id,
        root_id=new_root_id,
        parent_asset_id=None,
        design_id=design_id,
        design_version=design_version,
        capability="VARIATION_BRANCH",
        source_kind=source.source_kind,
        instruction=f"Saved reviewed candidate as variation from {source.id}",
        image=candidate.image_bytes,
        media_type=candidate.media_type,
        created_by=created_by,
        created_at=now,
    )
    new_project = Project(
        root_id=new_root_id,
        owner=created_by,
        collection=project.collection,
        title=project.title,
        tags=list(project.tags or []),
        family_id=family.id,
        variation_index=variation_index,
        variation_label=label,
        selected_candidate_asset_id=(new_root_id if next_spec is None else None),
        branched_from_project_root_id=project.root_id,
        branched_from_asset_id=source.id,
        created_at=now,
        updated_at=now,
    )
    review = ImageRunReview(
        id=new_id("irr"),
        run_id=run_id,
        decision="accepted",
        accepted_asset_id=new_root_id,
        created_by=created_by,
        created_at=now,
    )
    revision = ProjectRevisionRecord(
        id=new_id("prr"),
        asset_id=new_root_id,
        action="created",
        raw_intent={
            "kind": "save_preview_as_variation",
            "preview_kind": kind,
            "source_project_id": project.root_id,
            "source_asset_id": source.id,
            "image_run_id": run_id,
            "label": label,
        },
        interpretation={
            "operation": "fork_reviewed_preview",
            "source_sha256": candidate.source_hash,
            "output_sha256": candidate.output_hash,
            "independent_revision_history": True,
            "specification_created": next_spec is not None,
            "factory_authority": False,
        },
        change_summary=f"Saved reviewed preview as variation '{label}'.",
        created_by=created_by,
        created_at=now,
    )
    candidate_record.status = "saved_as_variation"
    candidate_record.terminal_asset_id = new_root_id
    candidate_record.review_id = review.id
    candidate_record.decided_by = created_by
    candidate_record.resolved_at = now
    candidate_record.image = b""
    family.updated_at = now
    project.updated_at = now
    db.add_all([new_asset, new_project, review, revision])
    studio_job_id = getattr(candidate, "studio_job_id", None)
    if studio_job_id is not None:
        from facetta.studio_jobs import (
            StudioJobAccountingError,
            record_accepted_studio_job_outputs,
        )

        try:
            record_accepted_studio_job_outputs(
                db,
                job_id=studio_job_id,
                owner=created_by,
                completed_outputs=1,
                active_design_id=project.root_id,
                source_revision_id=source.id,
            )
        except StudioJobAccountingError as exc:
            db.rollback()
            raise StudioHistoryError(
                "variation_job_resolution_conflict",
                str(exc),
            ) from exc
    try:
        db.flush()
        if child_component_map is not None:
            add_revision_component_map(
                db,
                child_component_map,
                image_bytes=candidate.image_bytes,
                parent_asset_id=source.id,
            )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise StudioHistoryError(
            "variation_conflict",
            "another preview decision or variation was saved first",
        ) from exc
    except Exception:
        db.rollback()
        raise
    return VariationBranchResult(
        family_id=family.id,
        project_root_id=new_root_id,
        asset_id=new_root_id,
        design_id=design_id,
        design_version=design_version,
        variation_index=variation_index,
    )


@dataclass(frozen=True)
class RestoreRevisionResult:
    project_root_id: str
    asset_id: str
    design_id: str | None
    design_version: int | None
    restored_from_asset_id: str
    spec_change: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class ApplyPreSpecVisualResult:
    project_root_id: str
    source_asset_id: str
    asset_id: str
    review_id: str


@dataclass(frozen=True)
class DiscardPreSpecVisualResult:
    project_root_id: str
    source_asset_id: str
    review_id: str


def _validate_pre_spec_visual_candidate(
    db: Session,
    *,
    candidate: StudioVisualCandidate,
    expected_active_asset_id: str,
    created_by: str,
    require_active: bool = True,
) -> tuple[Project, ImageAsset, ImageRun]:
    """Recheck the candidate's complete pre-spec authority boundary."""

    project = db.scalar(
        select(Project)
        .where(Project.root_id == candidate.project_root_id)
        .with_for_update()
    )
    source = db.get(ImageAsset, candidate.source_asset_id)
    root = db.get(ImageAsset, candidate.project_root_id)
    run = db.get(ImageRun, candidate.run_id)
    if project is None or source is None or root is None or run is None:
        raise StudioHistoryError(
            "visual_preview_unavailable",
            "the preview's project, source, or image run is unavailable",
            status_code=404,
        )
    if project.owner != created_by or candidate.created_by != created_by:
        raise StudioHistoryError(
            "visual_preview_unavailable",
            "the visual preview is not available to this designer",
            status_code=404,
        )
    if root.design_id is not None or source.design_version is not None:
        raise StudioHistoryError(
            "visual_preview_requires_pre_spec_project",
            "this Studio visual route cannot edit specification-linked work",
            status_code=422,
        )
    if source.root_id != project.root_id or not is_primary_revision(source):
        raise StudioHistoryError(
            "visual_preview_source_invalid",
            "the preview source is not a canonical pre-spec visual",
            status_code=422,
        )
    if (
        expected_active_asset_id != candidate.expected_selected_candidate_asset_id
        or candidate.source_asset_id != expected_active_asset_id
    ):
        raise StudioHistoryError(
            "stale_asset_revision",
            "the preview was not reviewed against this selected visual",
        )
    if (
        require_active
        and project.selected_candidate_asset_id != expected_active_asset_id
    ):
        raise StudioHistoryError(
            "stale_asset_revision",
            "the selected visual changed while the preview was under review",
        )
    source_hash = hashlib.sha256(bytes(source.image)).hexdigest()
    if source_hash != candidate.source_hash:
        raise StudioHistoryError(
            "visual_preview_source_hash_mismatch",
            "the selected source bytes no longer match the preview lineage",
            status_code=422,
        )
    if (
        run.project_root_id != project.root_id
        or run.source_asset_id != source.id
        or run.source_hash != source_hash
        or run.created_by != created_by
        or run.accepted_asset_id is not None
        or run.status not in {"preview_ready", "review_required"}
    ):
        raise StudioHistoryError(
            "visual_preview_run_mismatch",
            "the preview run is not bound to this exact project and source",
            status_code=422,
        )
    if (
        db.scalar(select(ImageRunReview).where(ImageRunReview.run_id == run.id))
        is not None
    ):
        raise StudioHistoryError(
            "visual_preview_already_reviewed",
            "the visual preview already has a terminal review decision",
        )
    return project, source, run


def apply_pre_spec_visual_candidate(
    db: Session,
    *,
    candidate: StudioVisualCandidate,
    expected_active_asset_id: str,
    created_by: str,
    commit: bool = True,
) -> ApplyPreSpecVisualResult:
    """Append one accepted visual while preserving an honest null spec."""

    project, source, run = _validate_pre_spec_visual_candidate(
        db,
        candidate=candidate,
        expected_active_asset_id=expected_active_asset_id,
        created_by=created_by,
    )
    now = utcnow()
    child = ImageAsset(
        id=new_id("ast"),
        root_id=project.root_id,
        parent_asset_id=source.id,
        design_id=None,
        design_version=None,
        capability=(
            "GLOBAL_RESTYLE"
            if candidate.scope == "appearance" else "LOCALIZED_EDIT"
        ),
        source_kind=source.source_kind,
        instruction=candidate.requested_change,
        region=(
            "designer-marked region" if candidate.scope == "marked_region" else None
        ),
        drift=None,
        image=candidate.image_bytes,
        media_type=candidate.media_type,
        created_by=created_by,
        created_at=now,
    )
    review = ImageRunReview(
        id=new_id("irr"),
        run_id=run.id,
        decision="accepted",
        accepted_asset_id=child.id,
        created_by=created_by,
        created_at=now,
    )
    record = ProjectRevisionRecord(
        id=new_id("prr"),
        asset_id=child.id,
        action="edit",
        raw_intent={
            "kind": "pre_spec_visual_refinement",
            "scope": candidate.scope,
            "instruction": candidate.requested_change,
            "source_asset_id": source.id,
            "image_run_id": run.id,
        },
        interpretation={
            "operation": "append_reviewed_visual",
            "specification_created": False,
            "factory_authority": False,
            "source_hash": candidate.source_hash,
            "source_sha256": candidate.source_hash,
            "output_sha256": hashlib.sha256(candidate.image_bytes).hexdigest(),
        },
        change_summary=(
            "Applied a reviewed pre-spec visual refinement; no specification "
            "or factory authority was created."
        ),
        created_by=created_by,
        created_at=now,
    )
    try:
        db.add_all([child, review, record])
        # Flush the append-only rows inside this transaction before the raw
        # compare-and-set update references the new asset. This is required
        # for databases with immediate foreign-key enforcement.
        db.flush()
        cas = db.execute(
            update(Project)
            .where(
                Project.root_id == project.root_id,
                Project.owner == created_by,
                Project.selected_candidate_asset_id == expected_active_asset_id,
            )
            .values(selected_candidate_asset_id=child.id, updated_at=now)
        )
        if cas.rowcount != 1:
            db.rollback()
            raise StudioHistoryError(
                "stale_asset_revision",
                "the selected visual changed before the preview could be applied",
            )
        if candidate.studio_job_id is not None:
            from facetta.studio_jobs import (
                StudioJobAccountingError,
                record_accepted_studio_job_outputs,
            )

            try:
                record_accepted_studio_job_outputs(
                    db,
                    job_id=candidate.studio_job_id,
                    owner=created_by,
                    completed_outputs=1,
                    active_design_id=project.root_id,
                    source_revision_id=source.id,
                )
            except StudioJobAccountingError as exc:
                db.rollback()
                raise StudioHistoryError(
                    "visual_preview_job_resolution_conflict",
                    str(exc),
                ) from exc
        if commit:
            db.commit()
        else:
            db.flush()
    except StudioHistoryError:
        raise
    except IntegrityError as exc:
        db.rollback()
        raise StudioHistoryError(
            "visual_preview_apply_conflict",
            "another review decision was saved before this preview",
        ) from exc
    except Exception:
        db.rollback()
        raise
    return ApplyPreSpecVisualResult(
        project_root_id=project.root_id,
        source_asset_id=source.id,
        asset_id=child.id,
        review_id=review.id,
    )


def discard_pre_spec_visual_candidate(
    db: Session,
    *,
    candidate: StudioVisualCandidate,
    expected_active_asset_id: str,
    created_by: str,
    commit: bool = True,
) -> DiscardPreSpecVisualResult:
    """Persist a terminal rejection without creating any project asset."""

    project, source, run = _validate_pre_spec_visual_candidate(
        db,
        candidate=candidate,
        expected_active_asset_id=expected_active_asset_id,
        created_by=created_by,
        require_active=False,
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
        if commit:
            db.commit()
        else:
            db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise StudioHistoryError(
            "visual_preview_discard_conflict",
            "another review decision was saved before this preview",
        ) from exc
    except Exception:
        db.rollback()
        raise
    return DiscardPreSpecVisualResult(
        project_root_id=project.root_id,
        source_asset_id=source.id,
        review_id=review.id,
    )


def _project_chain(db: Session, root_id: str) -> list[ImageAsset]:
    rows = list(
        db.scalars(
            select(ImageAsset)
            .where(ImageAsset.root_id == root_id)
            .order_by(ImageAsset.created_at, ImageAsset.id)
        )
    )
    rows.sort(
        key=lambda asset: (
            asset.id != root_id,
            asset.created_at,
            asset.id,
        )
    )
    return rows


def _active_primary(db: Session, root_id: str) -> ImageAsset | None:
    primary = [
        asset for asset in _project_chain(db, root_id) if is_primary_revision(asset)
    ]
    if not primary:
        return None
    project = db.get(Project, root_id)
    if (
        project is not None
        and project.selected_candidate_asset_id is not None
        and not any(asset.design_version is not None for asset in primary)
    ):
        selected = next(
            (
                asset
                for asset in primary
                if asset.id == project.selected_candidate_asset_id
                and asset.design_version is None
            ),
            None,
        )
        if selected is not None:
            return selected
    return primary[-1]


def ensure_project_family(db: Session, project: Project) -> DesignFamily:
    """Give every Studio project its Family -> Variation identity.

    Callers own the transaction. Keeping this operation explicit lets project
    creation and later branching share the same invariant without inventing a
    family in read paths.
    """
    if project.family_id is not None:
        family = db.get(DesignFamily, project.family_id)
        if family is None:
            raise StudioHistoryError(
                "design_family_unavailable",
                "the variation references a missing design family",
                status_code=500,
            )
        return family
    family = DesignFamily(
        id=new_id("fam"),
        owner=project.owner,
        title=project.title,
    )
    db.add(family)
    project.family_id = family.id
    project.variation_index = 1
    project.variation_label = project.variation_label or "Original"
    return family


def fork_project_variation(
    db: Session,
    *,
    project_root_id: str,
    source_asset_id: str,
    expected_active_asset_id: str,
    expected_design_version: int | None,
    variation_label: str,
    created_by: str,
    allow_unselected_creative_candidate: bool = False,
) -> VariationBranchResult:
    """Copy one exact revision into an independent sibling project."""

    project = db.scalar(
        select(Project).where(Project.root_id == project_root_id).with_for_update()
    )
    source = db.get(ImageAsset, source_asset_id)
    active = _active_primary(db, project_root_id)
    if project is None or source is None or source.root_id != project_root_id:
        raise StudioHistoryError(
            "variation_source_unavailable",
            "the selected variation source is not in this project",
            status_code=404,
        )
    if project.owner != created_by:
        # Do not disclose another designer's project or allow its history to
        # be extended by a caller-controlled attribution field.
        raise StudioHistoryError(
            "variation_source_unavailable",
            "the selected variation source is not in this project",
            status_code=404,
        )
    if not is_primary_revision(source):
        raise StudioHistoryError(
            "variation_source_not_revision",
            "only a primary visual revision can start a variation",
            status_code=422,
        )
    if active is None or active.id != expected_active_asset_id:
        raise StudioHistoryError(
            "stale_asset_revision",
            "the active design changed before the variation could be saved",
        )
    is_unselected_creative_candidate = (
        allow_unselected_creative_candidate
        and source.capability == "CREATIVE_RENDER"
        and source.design_version is None
    )
    if source.id != active.id and not is_unselected_creative_candidate:
        raise StudioHistoryError(
            "variation_source_not_active",
            "restore an older revision first or branch from the active design",
            status_code=422,
        )
    if active.design_version != expected_design_version:
        raise StudioHistoryError(
            "stale_design_version",
            "the specification changed before the variation could be saved",
        )
    label = variation_label.strip()
    if not label:
        raise StudioHistoryError(
            "variation_label_required",
            "name the variation before saving it",
            status_code=422,
        )

    source_sha256 = _verified_revision_hash(
        db,
        source,
        mismatch_code="variation_source_hash_mismatch",
    )

    family = ensure_project_family(db, project)
    if family.owner != project.owner:
        raise StudioHistoryError(
            "design_family_owner_mismatch",
            "the project and design family have different owners",
            status_code=422,
        )
    highest = (
        db.scalar(
            select(func.max(Project.variation_index)).where(
                Project.family_id == family.id
            )
        )
        or 1
    )
    variation_index = highest + 1
    now = utcnow()
    new_root_id = new_id("ast")
    new_design_id: str | None = None
    new_design_version: int | None = None
    root = db.get(ImageAsset, project_root_id)
    if root is not None and root.design_id is not None:
        if source.design_version is None:
            raise StudioHistoryError(
                "variation_spec_binding_unknown",
                "the selected visual has no exact specification binding",
                status_code=422,
            )
        source_version = db.get(DesignVersion, (root.design_id, source.design_version))
        if source_version is None:
            raise StudioHistoryError(
                "variation_spec_unavailable",
                "the selected revision's exact specification is unavailable",
                status_code=404,
            )
        new_design_id = new_id("dsn")
        new_design_version = 1
        stored_spec = dict(source_version.spec)
        stored_spec.update(
            {
                "design_id": new_design_id,
                "version": 1,
                "created_by": created_by,
                "created_at": now.isoformat().replace("+00:00", "Z"),
            }
        )
        db.add_all(
            [
                Design(
                    id=new_design_id,
                    created_by=created_by,
                    created_at=now,
                    collection=project.collection,
                ),
                DesignVersion(
                    design_id=new_design_id,
                    version=1,
                    spec=stored_spec,
                    created_by=created_by,
                    created_at=now,
                ),
            ]
        )

    new_asset = ImageAsset(
        id=new_root_id,
        root_id=new_root_id,
        parent_asset_id=None,
        design_id=new_design_id,
        design_version=new_design_version,
        capability="VARIATION_BRANCH",
        source_kind=source.source_kind,
        instruction=f"Saved as variation from {source.id}",
        image=bytes(source.image),
        media_type=source.media_type,
        created_by=created_by,
        created_at=now,
    )
    new_project = Project(
        root_id=new_root_id,
        owner=project.owner,
        collection=project.collection,
        title=project.title,
        tags=list(project.tags or []),
        family_id=family.id,
        variation_index=variation_index,
        variation_label=label,
        branched_from_project_root_id=project.root_id,
        branched_from_asset_id=source.id,
        # A visual-only branch starts with its copied root selected. Without
        # this binding the Studio preview seam treats the just-created branch
        # as stale and refuses the first refinement.
        selected_candidate_asset_id=(new_root_id if new_design_id is None else None),
        created_at=now,
        updated_at=now,
    )
    record = ProjectRevisionRecord(
        id=new_id("prr"),
        asset_id=new_asset.id,
        action="created",
        raw_intent={
            "kind": "save_as_variation",
            "source_project_id": project.root_id,
            "source_asset_id": source.id,
            "label": label,
        },
        interpretation={
            "operation": "fork_variation",
            "source_preserved_exactly": True,
            "independent_revision_history": True,
            "source_sha256": source_sha256,
            "output_sha256": source_sha256,
        },
        change_summary=f"Saved '{label}' as an independent variation.",
        created_by=created_by,
        created_at=now,
    )
    family.updated_at = now
    project.updated_at = now
    db.add_all([new_asset, new_project, record])
    try:
        db.flush()
        copy_revision_component_map_for_identical_raster(
            db,
            source_asset_id=source.id,
            child_asset_id=new_asset.id,
            child_image_bytes=bytes(new_asset.image),
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise StudioHistoryError(
            "variation_conflict",
            "another variation was saved at the same time; reload and retry",
        ) from exc
    except Exception:
        db.rollback()
        raise
    return VariationBranchResult(
        family_id=family.id,
        project_root_id=new_root_id,
        asset_id=new_asset.id,
        design_id=new_design_id,
        design_version=new_design_version,
        variation_index=variation_index,
    )


def restore_project_revision(
    db: Session,
    *,
    project_root_id: str,
    restore_asset_id: str,
    expected_active_asset_id: str,
    expected_design_version: int | None,
    created_by: str,
) -> RestoreRevisionResult:
    """Append a copy of a historical revision as the new active revision."""

    project = db.scalar(
        select(Project).where(Project.root_id == project_root_id).with_for_update()
    )
    selected = db.get(ImageAsset, restore_asset_id)
    active = _active_primary(db, project_root_id)
    root = db.get(ImageAsset, project_root_id)
    if (
        project is None
        or root is None
        or selected is None
        or selected.root_id != project_root_id
    ):
        raise StudioHistoryError(
            "restore_revision_unavailable",
            "the selected historical revision is not in this project",
            status_code=404,
        )
    if project.owner != created_by:
        raise StudioHistoryError(
            "restore_revision_unavailable",
            "the selected historical revision is not in this project",
            status_code=404,
        )
    accepted_candidate = accepted_creative_candidate(
        _project_chain(db, project_root_id), project.selected_candidate_asset_id,
    )
    if not (
        is_canonical_revision(selected)
        or selected.id == getattr(accepted_candidate, "id", None)
    ):
        raise StudioHistoryError(
            "restore_source_not_revision",
            "only an accepted variation revision can be restored",
            status_code=422,
        )
    if active is None or active.id != expected_active_asset_id:
        raise StudioHistoryError(
            "stale_asset_revision",
            "the active design changed before the restore could be saved",
        )
    if active.design_version != expected_design_version:
        raise StudioHistoryError(
            "stale_design_version",
            "the specification changed before the restore could be saved",
        )
    if selected.id == active.id:
        raise StudioHistoryError(
            "restore_source_is_active",
            "the selected revision is already active",
            status_code=422,
        )

    selected_sha256 = _verified_revision_hash(
        db,
        selected,
        mismatch_code="restore_source_hash_mismatch",
    )
    active_sha256 = _verified_revision_hash(
        db,
        active,
        mismatch_code="restore_parent_hash_mismatch",
    )

    now = utcnow()
    next_version: int | None = None
    design_id = root.design_id
    changes: tuple[dict[str, object], ...] = ()
    summary = "Restored the selected historical visual as a new revision."
    if design_id is not None:
        if selected.design_version is None or active.design_version is None:
            raise StudioHistoryError(
                "restore_spec_binding_unknown",
                "one of the selected revisions has unknown specification provenance",
                status_code=422,
            )
        selected_version = db.get(DesignVersion, (design_id, selected.design_version))
        active_version = db.get(DesignVersion, (design_id, active.design_version))
        latest = db.scalar(
            select(func.max(DesignVersion.version)).where(
                DesignVersion.design_id == design_id
            )
        )
        if (
            selected_version is None
            or active_version is None
            or latest != active.design_version
        ):
            raise StudioHistoryError(
                "restore_spec_unavailable",
                "the exact historical or active specification is unavailable",
                status_code=409,
            )
        next_version = active.design_version + 1
        restored_spec = dict(selected_version.spec)
        restored_spec.update(
            {
                "design_id": design_id,
                "version": next_version,
                "created_by": created_by,
                "created_at": now.isoformat().replace("+00:00", "Z"),
            }
        )
        changes = tuple(diff_specs(active_version.spec, restored_spec))
        summary = summarize_changes(list(changes)) or (
            "Restored the selected historical visual and specification."
        )
        db.add(
            DesignVersion(
                design_id=design_id,
                version=next_version,
                spec=restored_spec,
                created_by=created_by,
                created_at=now,
            )
        )

    restored_asset = ImageAsset(
        id=new_id("ast"),
        root_id=project_root_id,
        parent_asset_id=active.id,
        design_id=None,
        design_version=next_version,
        capability="RESTORED_REVISION",
        source_kind=selected.source_kind,
        instruction=f"Restored from revision asset {selected.id}",
        image=bytes(selected.image),
        media_type=selected.media_type,
        created_by=created_by,
        created_at=now,
    )
    record = ProjectRevisionRecord(
        id=new_id("prr"),
        asset_id=restored_asset.id,
        action="restore",
        raw_intent={
            "kind": "restore_revision",
            "selected_asset_id": selected.id,
        },
        interpretation={
            "operation": "append_historical_copy",
            "history_deleted": False,
            "visual_bytes_restored_exactly": True,
            "specification_restored": design_id is not None,
            "source_sha256": selected_sha256,
            "output_sha256": selected_sha256,
            "parent_sha256": active_sha256,
        },
        change_summary=summary,
        restored_from_asset_id=selected.id,
        created_by=created_by,
        created_at=now,
    )
    project.updated_at = now
    if design_id is None:
        # Pre-spec projects use the selected-candidate pointer as their exact
        # active visual. A restore must advance that pointer to the appended
        # child or reads would silently snap back to the old candidate.
        project.selected_candidate_asset_id = restored_asset.id
    db.add_all([restored_asset, record])
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise StudioHistoryError(
            "restore_conflict",
            "another revision was saved before the restore completed",
        ) from exc
    except Exception:
        db.rollback()
        raise
    return RestoreRevisionResult(
        project_root_id=project_root_id,
        asset_id=restored_asset.id,
        design_id=design_id,
        design_version=next_version,
        restored_from_asset_id=selected.id,
        spec_change=changes,
    )

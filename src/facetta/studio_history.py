"""Design-family branching and append-only Studio restoration services."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from facetta.db import (
    Design,
    DesignFamily,
    DesignVersion,
    ImageAsset,
    Project,
    ProjectRevisionRecord,
    new_id,
    utcnow,
)
from facetta.project_backbone import is_primary_revision
from facetta.specdiff import diff_specs, summarize_changes


class StudioHistoryError(RuntimeError):
    def __init__(self, code: str, detail: str, *, status_code: int = 409) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True)
class VariationBranchResult:
    family_id: str
    project_root_id: str
    asset_id: str
    design_id: str | None
    design_version: int | None
    variation_index: int


@dataclass(frozen=True)
class RestoreRevisionResult:
    project_root_id: str
    asset_id: str
    design_id: str | None
    design_version: int | None
    restored_from_asset_id: str
    spec_change: tuple[dict[str, object], ...]


def _project_chain(db: Session, root_id: str) -> list[ImageAsset]:
    rows = list(db.scalars(
        select(ImageAsset)
        .where(ImageAsset.root_id == root_id)
        .order_by(ImageAsset.created_at, ImageAsset.id)
    ))
    rows.sort(key=lambda asset: (
        asset.id != root_id, asset.created_at, asset.id,
    ))
    return rows


def _active_primary(db: Session, root_id: str) -> ImageAsset | None:
    primary = [
        asset for asset in _project_chain(db, root_id)
        if is_primary_revision(asset)
    ]
    return primary[-1] if primary else None


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
) -> VariationBranchResult:
    """Copy one exact revision into an independent sibling project."""

    project = db.get(Project, project_root_id)
    source = db.get(ImageAsset, source_asset_id)
    active = _active_primary(db, project_root_id)
    if project is None or source is None or source.root_id != project_root_id:
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
    if source.id != active.id:
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

    family = ensure_project_family(db, project)
    if family.owner != project.owner:
        raise StudioHistoryError(
            "design_family_owner_mismatch",
            "the project and design family have different owners",
            status_code=422,
        )
    highest = db.scalar(select(func.max(Project.variation_index)).where(
        Project.family_id == family.id)) or 1
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
        source_version = db.get(
            DesignVersion, (root.design_id, source.design_version))
        if source_version is None:
            raise StudioHistoryError(
                "variation_spec_unavailable",
                "the selected revision's exact specification is unavailable",
                status_code=404,
            )
        new_design_id = new_id("dsn")
        new_design_version = 1
        stored_spec = dict(source_version.spec)
        stored_spec.update({
            "design_id": new_design_id,
            "version": 1,
            "created_by": created_by,
            "created_at": now.isoformat().replace("+00:00", "Z"),
        })
        db.add_all([
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
        ])

    new_asset = ImageAsset(
        id=new_root_id,
        root_id=new_root_id,
        parent_asset_id=None,
        design_id=new_design_id,
        design_version=new_design_version,
        capability="VARIATION_BRANCH",
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
        },
        change_summary=f"Saved '{label}' as an independent variation.",
        created_by=created_by,
        created_at=now,
    )
    family.updated_at = now
    project.updated_at = now
    db.add_all([new_asset, new_project, record])
    try:
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

    project = db.get(Project, project_root_id)
    selected = db.get(ImageAsset, restore_asset_id)
    active = _active_primary(db, project_root_id)
    root = db.get(ImageAsset, project_root_id)
    if (project is None or root is None or selected is None
            or selected.root_id != project_root_id):
        raise StudioHistoryError(
            "restore_revision_unavailable",
            "the selected historical revision is not in this project",
            status_code=404,
        )
    if not is_primary_revision(selected):
        raise StudioHistoryError(
            "restore_source_not_revision",
            "only a primary visual revision can be restored",
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
        selected_version = db.get(
            DesignVersion, (design_id, selected.design_version))
        active_version = db.get(
            DesignVersion, (design_id, active.design_version))
        latest = db.scalar(select(func.max(DesignVersion.version)).where(
            DesignVersion.design_id == design_id))
        if (selected_version is None or active_version is None
                or latest != active.design_version):
            raise StudioHistoryError(
                "restore_spec_unavailable",
                "the exact historical or active specification is unavailable",
                status_code=409,
            )
        next_version = active.design_version + 1
        restored_spec = dict(selected_version.spec)
        restored_spec.update({
            "design_id": design_id,
            "version": next_version,
            "created_by": created_by,
            "created_at": now.isoformat().replace("+00:00", "Z"),
        })
        changes = tuple(diff_specs(active_version.spec, restored_spec))
        summary = summarize_changes(list(changes)) or (
            "Restored the selected historical visual and specification."
        )
        db.add(DesignVersion(
            design_id=design_id,
            version=next_version,
            spec=restored_spec,
            created_by=created_by,
            created_at=now,
        ))

    restored_asset = ImageAsset(
        id=new_id("ast"),
        root_id=project_root_id,
        parent_asset_id=active.id,
        design_id=None,
        design_version=next_version,
        capability="RESTORED_REVISION",
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
        },
        change_summary=summary,
        restored_from_asset_id=selected.id,
        created_by=created_by,
        created_at=now,
    )
    project.updated_at = now
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

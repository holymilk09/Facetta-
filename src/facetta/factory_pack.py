"""Deterministic factory-pack assembly for one approved project revision.

Only validated specification data creates schematic factory-review geometry and lettering.
The approved raster is included as a visual reference, never represented as
dimensional truth.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from facetta.chain_geometry import chain_factory_blockers
from facetta.checklist import checklist_status
from facetta.db import (
    ApprovalChecklist,
    ApprovalResponse,
    DesignVersion,
    ImageAttempt,
    ImageAsset,
    ImageRun,
    ImageRunReview,
    Project,
)
from facetta.dxf import DxfUnsupported, svg_to_dxf
from facetta.dimension_provenance import estimated_dimension_summary
from facetta.design_form import unresolved_form_factory_blockers
from facetta.json_types import JsonObject, JsonValue
from facetta.image_identity import spec_visual_hash
from facetta.factory_sheet_plan import (
    build_factory_sheet_fact_plan,
    pending_factory_fact_paths,
)
from facetta.factory_schedule_pages import render_factory_schedule_pages
from facetta.factory_scope import factory_category_blockers
from facetta.project_backbone import is_primary_revision
from facetta.spec import Spec
from facetta.source_component_coverage import (
    source_component_factory_blockers,
)
from facetta.source_component_resolution import (
    valid_source_component_spec_paths,
)
from facetta.source_evidence_lineage import (
    apply_trusted_lineage_to_blockers,
    has_trusted_visual_spec_lineage,
    source_confirmation_evidence_matches,
    source_evidence_anchor_asset,
)
from facetta.svg_sheet import SheetUnsupported, render_sheet
from facetta.validation import validate_spec
from facetta.vocabulary import get_vocabulary


class FactoryPackUnavailable(ValueError):
    def __init__(self, code: str, detail: str, *, status_code: int = 409):
        self.code = code
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


@dataclass(frozen=True)
class FactoryPack:
    manifest: JsonObject
    files: dict[str, bytes]


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json_bytes(value: JsonValue) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False)
            + "\n").encode("utf-8")


def factory_pack_manifest_sha256(pack: FactoryPack) -> str:
    """Return the byte-stable identity persisted with Factory acceptance."""

    return _sha256(_json_bytes(pack.manifest))


def _chain(db: Session, root_id: str) -> list[ImageAsset]:
    return list(db.scalars(
        select(ImageAsset)
        .where(ImageAsset.root_id == root_id)
        .order_by(ImageAsset.created_at, ImageAsset.id)
    ))


def _active_revision(chain: list[ImageAsset]) -> tuple[ImageAsset, int]:
    primary = [asset for asset in chain if is_primary_revision(asset)]
    if not primary:
        raise FactoryPackUnavailable(
            "no_primary_revision", "the project has no primary visual revision")
    return primary[-1], len(primary)


def _completed_checklist(
    db: Session, asset: ImageAsset,
) -> tuple[ApprovalChecklist, list[ApprovalResponse], JsonObject]:
    checklist = db.execute(
        select(ApprovalChecklist)
        .where(ApprovalChecklist.asset_id == asset.id)
        .order_by(ApprovalChecklist.created_at.desc(),
                  ApprovalChecklist.id.desc())
    ).scalars().first()
    if checklist is None:
        raise FactoryPackUnavailable(
            "approval_required",
            "the active revision needs a completed approval checklist")
    responses = list(db.scalars(
        select(ApprovalResponse)
        .where(ApprovalResponse.checklist_id == checklist.id)
        .order_by(ApprovalResponse.created_at, ApprovalResponse.id)
    ))
    status = checklist_status(checklist.items, responses)
    if not status["all_approved"]:
        raise FactoryPackUnavailable(
            "approval_incomplete",
            "every checklist item must be approved before factory handoff")
    if asset.pinned_at is None:
        raise FactoryPackUnavailable(
            "revision_not_pinned",
            "the completed active revision must be pinned before factory handoff")
    if (asset.design_version is None
            or checklist.design_version != asset.design_version):
        raise FactoryPackUnavailable(
            "approval_version_mismatch",
            "the checklist is not bound to the active revision's exact spec")
    root = db.get(ImageAsset, asset.root_id) or asset
    if not root.design_id or checklist.design_id != root.design_id:
        raise FactoryPackUnavailable(
            "approval_design_mismatch",
            "the checklist is not bound to the active revision's design")
    return checklist, responses, status


def _latest_answers(
    checklist: ApprovalChecklist, responses: list[ApprovalResponse],
) -> list[JsonObject]:
    latest: dict[str, ApprovalResponse] = {}
    for response in responses:
        latest[response.item_key] = response
    out: list[JsonObject] = []
    for item in checklist.items:
        response = latest.get(item["key"])
        out.append({
            "item_key": item["key"],
            "label": item.get("label"),
            "fact": item.get("fact"),
            "approved": bool(response.approved) if response else False,
            "note": response.note if response else None,
            "approved_by": response.created_by if response else None,
            "approved_at": (response.created_at.isoformat()
                            if response else None),
        })
    return out


def _qa_summary(db: Session, asset_id: str) -> JsonObject:
    run = db.execute(
        select(ImageRun)
        .where(ImageRun.accepted_asset_id == asset_id)
        .order_by(ImageRun.created_at.desc(), ImageRun.id.desc())
    ).scalars().first()
    reviewed = False
    if run is None:
        review = db.execute(
            select(ImageRunReview)
            .where(ImageRunReview.accepted_asset_id == asset_id)
            .order_by(ImageRunReview.created_at.desc(), ImageRunReview.id.desc())
        ).scalars().first()
        if review is not None:
            run = db.get(ImageRun, review.run_id)
            reviewed = True
    if run is None:
        return {"status": "legacy_not_recorded", "image_run_id": None}
    attempts = list(db.scalars(
        select(ImageAttempt)
        .where(ImageAttempt.run_id == run.id)
        .order_by(ImageAttempt.attempt_number, ImageAttempt.id)
    ))
    accepted = next(
        (attempt for attempt in reversed(attempts)
         if attempt.qa_verdict in {"pass", "warn"}),
        attempts[-1] if attempts else None,
    )
    return {
        "status": "accepted_after_designer_review" if reviewed else run.status,
        "image_run_id": run.id,
        "operation": run.operation,
        "prompt_version": run.prompt_version,
        "attempt_count": len(attempts),
        "verdict": accepted.qa_verdict if accepted else None,
        "checks": accepted.qa_checks if accepted else [],
    }


def build_factory_pack(db: Session, project_id: str) -> FactoryPack:
    project = db.get(Project, project_id)
    if project is None:
        raise FactoryPackUnavailable(
            "project_not_found", f"unknown project '{project_id}'",
            status_code=404)
    chain = _chain(db, project.root_id)
    active, revision = _active_revision(chain)
    root = db.get(ImageAsset, active.root_id) or active
    if (active.capability == "CREATIVE_RENDER"
            or not root.design_id
            or active.design_version is None):
        raise FactoryPackUnavailable(
            "creative_candidate_requires_spec_promotion",
            "select a creative candidate, confirm its exact specification, "
            "and create a spec-aligned revision before factory approval",
        )
    checklist, responses, approval_status = _completed_checklist(db, active)
    version = db.get(DesignVersion, (root.design_id, active.design_version))
    if version is None:
        raise FactoryPackUnavailable(
            "spec_version_not_found",
            "the approved asset's exact immutable specification is missing")
    validated = validate_spec(Spec.model_validate(version.spec), get_vocabulary())
    if not validated.ok:
        raise FactoryPackUnavailable(
            "spec_validation_failed",
            "the approved specification no longer passes validation",
            status_code=422)

    category_blockers = factory_category_blockers(validated.spec)
    if category_blockers:
        blocker = category_blockers[0]
        raise FactoryPackUnavailable(blocker.code, blocker.message)

    form_blockers = unresolved_form_factory_blockers(
        validated.spec.design_form)
    if form_blockers:
        element_ids = ", ".join(
            blocker.element_id for blocker in form_blockers)
        raise FactoryPackUnavailable(
            "design_form_not_dimensioned",
            "Factory release is blocked because these designer-confirmed "
            "forms are still visual_reference_only: " + element_ids
            + ". Supply or confirm a dimensioned profile or CAD definition "
              "before manufacturing.",
        )

    target_visual_hash = spec_visual_hash(validated.spec)
    source_evidence_hash = _sha256(bytes(source_evidence_anchor_asset(
        db,
        active_asset=active,
    ).image))
    source_blockers = source_component_factory_blockers(
        validated.spec.source_component_coverage,
        valid_spec_paths=valid_source_component_spec_paths(validated.spec),
        current_spec_visual_hash=target_visual_hash,
        current_source_hash=source_evidence_hash,
    )
    coverage = validated.spec.source_component_coverage
    source_blockers = apply_trusted_lineage_to_blockers(
        source_blockers,
        lineage_verified=has_trusted_visual_spec_lineage(
            db,
            active_asset=active,
            source_spec_visual_hash=(
                coverage.audited_spec_visual_hash if coverage is not None else None
            ),
            target_spec_visual_hash=target_visual_hash,
        ),
        source_confirmation_evidence_verified=(
            source_confirmation_evidence_matches(
                coverage,
                source_hash=source_evidence_hash,
            )
        ),
    )
    if source_blockers:
        blocker_summary = "; ".join(
            f"{blocker.component_id} ({blocker.code})"
            for blocker in source_blockers
        )
        raise FactoryPackUnavailable(
            "source_component_coverage_incomplete",
            "Factory release is blocked because visible source components "
            "are unresolved, mapped to removed spec paths, unaudited, or "
            "failed coverage review: "
            + blocker_summary
            + ". Map every visible component to the validated spec or a "
              "supported design-form element, then retain a passing "
              "independent component audit.",
        )

    chain_blockers = chain_factory_blockers(validated.spec)
    if chain_blockers:
        blocker_summary = "; ".join(
            f"{blocker.field_path} ({blocker.code})"
            for blocker in chain_blockers
        )
        raise FactoryPackUnavailable(
            "chain_manufacturing_incomplete",
            "Factory release is blocked because the necklace chain is only "
            "a visual/procurement description: " + blocker_summary + ". "
            "Confirm its physical geometry and exact stock/sample or custom "
            "drawing/CAD production reference before manufacturing.",
        )

    try:
        svg = render_sheet(validated.spec).encode("utf-8")
    except SheetUnsupported as exc:
        raise FactoryPackUnavailable(
            "factory_sheet_unsupported", str(exc), status_code=422) from exc
    try:
        dxf = svg_to_dxf(svg.decode("utf-8")).encode("utf-8")
    except DxfUnsupported as exc:
        raise FactoryPackUnavailable(
            "dxf_conversion_unsupported",
            "The deterministic SVG is valid, but its drawing-exchange DXF "
            f"cannot preserve the current geometry: {exc}",
            status_code=422,
        ) from exc
    spec_json = _json_bytes(version.spec)
    extension = {
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/webp": "webp",
    }.get(active.media_type, "bin")
    image_name = f"approved-reference.{extension}"
    files: dict[str, bytes] = {
        "validated-spec.json": spec_json,
        "facetta-sheet.svg": svg,
        "facetta-sheet.dxf": dxf,
        image_name: bytes(active.image),
    }
    discussion_names: list[str] = []
    # A confirmed drawing may be either a direct discussion child of the
    # approved visual, or an upstream control ancestor when the designer used
    # LINE_ART -> COLORED_LINE_ART -> beauty render.  Keep the ancestry exact;
    # an unrelated line drawing from the same version must not leak into the
    # factory pack merely because its version number matches.
    by_id = {asset.id: asset for asset in chain}
    ancestor_ids: set[str] = set()
    cursor = active
    while cursor.parent_asset_id is not None:
        parent = by_id.get(cursor.parent_asset_id)
        if parent is None or parent.id in ancestor_ids:
            break
        ancestor_ids.add(parent.id)
        cursor = parent
    confirmed_line_art = [
        asset for asset in chain
        if asset.capability == "LINE_ART"
        and asset.design_version == active.design_version
        and (asset.parent_asset_id == active.id or asset.id in ancestor_ids)
    ]
    if confirmed_line_art:
        drawing = confirmed_line_art[-1]
        drawing_extension = {
            "image/png": "png",
            "image/jpeg": "jpg",
            "image/webp": "webp",
        }.get(drawing.media_type, "bin")
        drawing_name = f"discussion-line-art.{drawing_extension}"
        files[drawing_name] = bytes(drawing.image)
        discussion_names.append(drawing_name)
    answers = _latest_answers(checklist, responses)
    dimensions = estimated_dimension_summary(validated.spec)
    fact_plan = build_factory_sheet_fact_plan(
        validated.spec,
        confirmed_sections={
            str(item["section"])
            for item in checklist.items
            if item.get("section")
        },
    )
    pending_facts = pending_factory_fact_paths(fact_plan)
    if pending_facts:
        raise FactoryPackUnavailable(
            "factory_fact_confirmation_incomplete",
            "Factory release is blocked because the approval checklist did "
            "not confirm every recorded manufacturing fact: "
            + ", ".join(pending_facts)
            + ". Start a checklist for the current exact revision and approve "
              "or revise each listed fact before generating the pack.",
        )
    schedule_names: list[str] = []
    for page_number, page in enumerate(
        render_factory_schedule_pages(fact_plan), start=1,
    ):
        name = f"facetta-schedule-{page_number}.svg"
        files[name] = page.encode("utf-8")
        schedule_names.append(name)
    last_approval = max(
        (response for response in responses if response.approved),
        key=lambda response: (response.created_at, response.id),
    )
    manifest = {
        "schema_version": "facetta.factory-pack.v1",
        "project_id": project.root_id,
        "design_id": root.design_id,
        "design_version": active.design_version,
        "asset_id": active.id,
        "visual_revision": revision,
        "approver": last_approval.created_by,
        "approved_at": last_approval.created_at.isoformat(),
        "pinned_at": active.pinned_at.isoformat(),
        "checklist": {
            "id": checklist.id,
            "mode": checklist.mode,
            "status": approval_status,
            "results": answers,
        },
        "qa_summary": _qa_summary(db, active.id),
        "dimensions": dimensions,
        "factory_sheet_fact_plan": fact_plan.model_dump(mode="json"),
        "authority": {
            "factory_truth": [
                "validated-spec.json",
                *schedule_names,
            ],
            "authoritative_fact_records": [
                "validated-spec.json",
                *schedule_names,
            ],
            "dimensional_diagram_only": ["facetta-sheet.svg"],
            "exchange_reference_only": ["facetta-sheet.dxf"],
            "visual_reference_only": [image_name],
            "discussion_only": discussion_names,
            "production_authority": [],
            "release_status": "factory_review_only",
            "note": ("Only the validated specification and confirmed fact "
                     "schedules are authoritative records. The deterministic "
                     "SVG is a schematic dimensional diagram, not a production "
                     "drawing: its generic circles, outlines, and template views "
                     "do not establish seats, prongs, galleries, joints, hidden "
                     "construction, tolerances, or buildable jewelry geometry. "
                     "The DXF is a "
                     "transform-aware 2D drawing-exchange reference only; curved "
                     "SVG geometry is represented by sampled R12 polylines and "
                     "must not be treated as solid or tolerance-bearing fabrication "
                     "geometry. "
                     + ("Fields explicitly marked ESTIMATED are reference-derived "
                        "prototyping values, not measurements, and must be verified "
                        "or adjusted before manufacturing. "
                        if dimensions["has_estimates"] else "")
                     + "Any discussion drawing is AI-derived, designer-reviewed "
                       "visual context and must not be measured or manufactured. "
                       "This pack is for factory review and clarification only; "
                       "production requires a designer-approved, design-derived "
                       "technical drawing and/or tolerance-bearing CAD/master "
                       "geometry."),
        },
        "files": [
            {
                "name": name,
                "sha256": _sha256(content),
                "bytes": len(content),
                "authoritative": name in {
                    "validated-spec.json",
                    *schedule_names,
                },
            }
            for name, content in files.items()
        ],
    }
    files["approval-manifest.json"] = _json_bytes(manifest)
    return FactoryPack(manifest=manifest, files=files)


def factory_pack_zip(pack: FactoryPack) -> bytes:
    """Create a byte-stable ZIP (fixed metadata, stable file order)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        ordered = [
            "validated-spec.json",
            "facetta-sheet.svg",
            "facetta-sheet.dxf",
            *sorted(key for key in pack.files
                    if key.startswith("facetta-schedule-")),
            next(key for key in pack.files if key.startswith("approved-reference.")),
            *sorted(key for key in pack.files
                    if key.startswith("discussion-line-art.")),
            "approval-manifest.json",
        ]
        for name in ordered:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, pack.files[name])
    return buffer.getvalue()

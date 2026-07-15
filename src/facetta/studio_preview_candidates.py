"""One owner-scoped Studio contract over every Refine preview candidate.

The three existing candidate stores remain the transaction authorities:

* ``studio_visual`` keeps pre-spec appearance work temporary;
* ``catalog_revision`` binds structural/material changes to image + spec truth;
* ``studio_markup`` binds natural-language or annotated exact refinements.

This module is deliberately an additive projection and dispatcher.  It does
not copy candidate bytes into a new table and it does not reimplement Apply,
Save as Variation, or Discard.  Terminal decisions continue to run through
the proven services that own locking, QA, provenance, immutable revisions,
job settlement, and credits.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from facetta.catalog_preview_candidates import (
    CatalogPreviewJobError,
    CatalogPreviewUnavailable,
    discard_catalog_preview_candidate,
    invalidate_catalog_preview_candidate,
    lock_catalog_preview_candidate_for_decision,
    resolve_catalog_preview_candidate,
    settle_catalog_preview_acceptance,
)
from facetta.db import (
    ImageAsset,
    PreviewCandidateRecord,
    Project,
    StudioMarkupCandidateRecord,
)
from facetta.json_types import JsonObject
from facetta.spec import Spec
from facetta.studio_history import (
    StudioHistoryError,
    apply_pre_spec_visual_candidate,
    discard_pre_spec_visual_candidate,
    fork_preview_candidate_variation,
)
from facetta.studio_markup_candidates import (
    StudioMarkupCandidateUnavailable,
    StudioMarkupError,
    accept_studio_markup_candidate,
    discard_studio_markup_candidate,
    lock_studio_markup_candidate_for_decision,
)
from facetta.studio_visual_candidates import (
    StudioVisualCandidateUnavailable,
    get_studio_visual_candidate,
    invalidate_studio_visual_candidate,
    remove_studio_visual_candidate,
)
from facetta.trusted_revision import (
    WarningRevisionError,
    accept_catalog_preview_revision,
)


StudioPreviewKind = Literal["visual", "catalog_revision", "markup"]
StudioPreviewStatus = Literal[
    "reviewing", "applied", "saved_as_variation", "discarded", "expired",
]
StudioPreviewDecision = Literal["apply", "save_as_variation", "discard"]
StudioPreviewDecisionStatus = Literal[
    "applied", "saved_as_variation", "discarded",
]


class StudioPreviewCandidateError(RuntimeError):
    """A normalized preview is foreign, invalid, stale, or already resolved."""

    def __init__(
        self,
        code: str,
        detail: str,
        *,
        status_code: int = 409,
    ) -> None:
        self.code = code
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


@dataclass(frozen=True)
class StudioPreviewCandidate:
    candidate_id: str
    kind: StudioPreviewKind
    status: StudioPreviewStatus
    image_run_id: str
    owner: str
    project_root_id: str
    source_asset_id: str
    expected_active_asset_id: str
    expected_design_version: int | None
    source_sha256: str
    output_sha256: str
    requested_change: str
    verdict: Literal["pass", "warn"] | None
    qa: JsonObject
    studio_job_id: str | None
    terminal_asset_id: str | None
    created_at: datetime
    expires_at: datetime
    resolved_at: datetime | None
    available_decisions: tuple[StudioPreviewDecision, ...]
    detail: JsonObject


@dataclass(frozen=True)
class StudioPreviewImage:
    image_bytes: bytes
    media_type: str


@dataclass(frozen=True)
class StudioPreviewDecisionResult:
    status: StudioPreviewDecisionStatus
    candidate_id: str
    kind: StudioPreviewKind
    source_project_id: str
    result_project_id: str
    terminal_asset_id: str | None
    studio_job_id: str | None
    family_id: str | None
    variation_index: int | None


CandidateRecord = PreviewCandidateRecord | StudioMarkupCandidateRecord


def _kind(record: CandidateRecord) -> StudioPreviewKind:
    if isinstance(record, StudioMarkupCandidateRecord):
        return "markup"
    if record.kind == "studio_visual":
        return "visual"
    if record.kind == "catalog_revision":
        return "catalog_revision"
    raise StudioPreviewCandidateError(
        "preview_candidate_kind_invalid",
        "the Studio preview candidate kind is invalid",
        status_code=422,
    )


def _record(
    db: Session,
    candidate_id: str,
    *,
    owner: str,
    for_update: bool = False,
) -> CandidateRecord:
    preview_query = select(PreviewCandidateRecord).where(
        PreviewCandidateRecord.id == candidate_id,
        PreviewCandidateRecord.owner == owner,
    )
    markup_query = select(StudioMarkupCandidateRecord).where(
        StudioMarkupCandidateRecord.id == candidate_id,
        StudioMarkupCandidateRecord.owner == owner,
    )
    if for_update:
        preview_query = preview_query.with_for_update()
        markup_query = markup_query.with_for_update()
    preview = db.scalar(preview_query)
    markup = db.scalar(markup_query)
    if preview is not None and markup is not None:
        raise StudioPreviewCandidateError(
            "preview_candidate_identity_conflict",
            "the Studio preview candidate identity is ambiguous",
            status_code=409,
        )
    record = preview or markup
    if record is None:
        # Owner is part of the lookup so a foreign candidate is indistinguishable
        # from a missing one.
        raise StudioPreviewCandidateError(
            "preview_candidate_unavailable",
            "the Studio preview candidate is unavailable",
            status_code=404,
        )
    return record


def _load_reviewing_candidate(
    db: Session,
    record: CandidateRecord,
):
    """Load through the existing fail-closed authority for this candidate."""

    kind = _kind(record)
    try:
        if kind == "visual":
            return get_studio_visual_candidate(
                db,
                record.image_run_id,
                record.id,
                owner=record.owner,
                require_active=False,
            )
        if kind == "catalog_revision":
            candidate, _ = lock_catalog_preview_candidate_for_decision(
                db,
                record.image_run_id,
                record.id,
                owner=record.owner,
                require_active=False,
            )
            return candidate
        candidate, _ = lock_studio_markup_candidate_for_decision(
            db,
            record.image_run_id,
            record.id,
            owner=record.owner,
            require_active=False,
        )
        return candidate
    except (
        StudioVisualCandidateUnavailable,
        CatalogPreviewUnavailable,
        StudioMarkupCandidateUnavailable,
        StudioMarkupError,
    ) as exc:
        raise StudioPreviewCandidateError(
            "preview_candidate_unavailable",
            str(exc),
            status_code=getattr(exc, "status_code", 410),
        ) from exc


def _safe_json(value: object) -> JsonObject:
    return value if isinstance(value, dict) else {}


def _catalog_next_spec(payload: JsonObject, *, candidate=None) -> JsonObject:
    """Project exact catalog truth without trusting an unvalidated JSON row.

    Reviewing candidates have already passed the catalog authority's complete
    durable-payload validation. Resolved candidates cannot be reopened by
    that authority, so their retained immutable proposal is independently
    parsed as a ``Spec`` before the normalized read exposes it.
    """

    raw_spec = (
        getattr(candidate, "next_spec", None)
        if candidate is not None else payload.get("next_spec")
    )
    try:
        spec = (
            raw_spec
            if isinstance(raw_spec, Spec)
            else Spec.model_validate(raw_spec)
        )
    except (TypeError, ValueError) as exc:
        raise StudioPreviewCandidateError(
            "preview_candidate_payload_invalid",
            "the catalog preview specification is incomplete or invalid",
            status_code=422,
        ) from exc
    return spec.model_dump(mode="json")


def _projection(
    record: CandidateRecord,
    *,
    candidate=None,
) -> StudioPreviewCandidate:
    kind = _kind(record)
    payload = _safe_json(record.payload)
    qa = _safe_json(
        getattr(candidate, "qa", None) if candidate is not None else payload.get("qa")
    )
    verdict = getattr(candidate, "verdict", None)
    if verdict is None:
        raw_verdict = payload.get("verdict") or qa.get("verdict")
        verdict = raw_verdict if raw_verdict in {"pass", "warn"} else None
    requested_change = (
        getattr(candidate, "requested_change", None)
        or (
            record.requested_change
            if isinstance(record, StudioMarkupCandidateRecord)
            else payload.get("requested_change")
        )
        or ""
    )
    if kind == "visual":
        detail: JsonObject = {
            "scope": getattr(candidate, "scope", None) or payload.get("scope"),
        }
        expected_design_version = record.expected_design_version
    elif kind == "catalog_revision":
        raw_changes = (
            list(candidate.spec_change)
            if candidate is not None
            else payload.get("spec_change", [])
        )
        detail = {
            "component_path": (
                getattr(candidate, "component_path", None)
                or payload.get("component_path")
            ),
            "option_id": (
                getattr(candidate, "option_id", None) or payload.get("option_id")
            ),
            "spec_change": raw_changes if isinstance(raw_changes, list) else [],
            "next_spec": _catalog_next_spec(payload, candidate=candidate),
        }
        expected_design_version = record.expected_design_version
    else:
        assert isinstance(record, StudioMarkupCandidateRecord)
        detail = {
            "operation": getattr(candidate, "operation", None) or record.operation,
            "region_description": (
                getattr(candidate, "region_description", None)
                or record.region_description
            ),
        }
        expected_design_version = record.design_version
    status = record.status
    if status not in {
        "reviewing", "applied", "saved_as_variation", "discarded", "expired",
    }:
        raise StudioPreviewCandidateError(
            "preview_candidate_status_invalid",
            "the Studio preview candidate status is invalid",
            status_code=422,
        )
    return StudioPreviewCandidate(
        candidate_id=record.id,
        kind=kind,
        status=status,
        image_run_id=record.image_run_id,
        owner=record.owner,
        project_root_id=record.project_root_id,
        source_asset_id=record.source_asset_id,
        expected_active_asset_id=record.expected_active_asset_id,
        expected_design_version=expected_design_version,
        source_sha256=record.source_sha256,
        output_sha256=record.output_sha256,
        requested_change=requested_change,
        verdict=verdict,
        qa=qa,
        studio_job_id=record.studio_job_id,
        terminal_asset_id=record.terminal_asset_id,
        created_at=record.created_at,
        expires_at=record.expires_at,
        resolved_at=record.resolved_at,
        available_decisions=(
            ("apply", "save_as_variation", "discard")
            if status == "reviewing" else ()
        ),
        detail=detail,
    )


def get_studio_preview_candidate(
    db: Session,
    candidate_id: str,
    *,
    owner: str,
) -> StudioPreviewCandidate:
    record = _record(db, candidate_id, owner=owner)
    candidate = (
        _load_reviewing_candidate(db, record)
        if record.status == "reviewing" else None
    )
    return _projection(record, candidate=candidate)


def list_studio_preview_candidates(
    db: Session,
    *,
    owner: str,
    project_root_id: str,
    include_resolved: bool = False,
) -> tuple[StudioPreviewCandidate, ...]:
    preview_query = select(PreviewCandidateRecord).where(
        PreviewCandidateRecord.owner == owner,
        PreviewCandidateRecord.project_root_id == project_root_id,
    )
    markup_query = select(StudioMarkupCandidateRecord).where(
        StudioMarkupCandidateRecord.owner == owner,
        StudioMarkupCandidateRecord.project_root_id == project_root_id,
    )
    if not include_resolved:
        preview_query = preview_query.where(PreviewCandidateRecord.status == "reviewing")
        markup_query = markup_query.where(
            StudioMarkupCandidateRecord.status == "reviewing"
        )
    records: list[CandidateRecord] = [
        *db.scalars(preview_query),
        *db.scalars(markup_query),
    ]
    records.sort(key=lambda item: (item.created_at, item.id), reverse=True)
    result: list[StudioPreviewCandidate] = []
    for record in records:
        try:
            candidate = (
                _load_reviewing_candidate(db, record)
                if record.status == "reviewing" else None
            )
            result.append(_projection(record, candidate=candidate))
        except StudioPreviewCandidateError:
            # The underlying service has already applied its fail-closed expiry
            # or invalidation policy where appropriate. Never expose malformed
            # bytes through the normalized list.
            continue
    return tuple(result)


def get_studio_preview_image(
    db: Session,
    candidate_id: str,
    *,
    owner: str,
) -> StudioPreviewImage:
    record = _record(db, candidate_id, owner=owner)
    if record.status != "reviewing":
        raise StudioPreviewCandidateError(
            "preview_candidate_image_unavailable",
            f"the Studio preview candidate was already {record.status}",
            status_code=410,
        )
    candidate = _load_reviewing_candidate(db, record)
    return StudioPreviewImage(
        image_bytes=bytes(candidate.image_bytes),
        media_type=candidate.media_type,
    )


def _guard_exact_decision(
    record: CandidateRecord,
    *,
    expected_active_asset_id: str,
    expected_design_version: int | None,
) -> None:
    if expected_active_asset_id != record.expected_active_asset_id:
        raise StudioPreviewCandidateError(
            "preview_candidate_lineage_mismatch",
            "the decision identifies another active visual revision",
        )
    required_version = (
        record.design_version
        if isinstance(record, StudioMarkupCandidateRecord)
        else record.expected_design_version
    )
    if required_version is not None and expected_design_version != required_version:
        raise StudioPreviewCandidateError(
            "preview_candidate_lineage_mismatch",
            "the decision identifies another specification revision",
        )
    if required_version is None and expected_design_version is not None:
        raise StudioPreviewCandidateError(
            "preview_candidate_lineage_mismatch",
            "this visual-only preview has no specification revision",
        )


def _terminal_result(
    db: Session,
    record: CandidateRecord,
    *,
    decision: StudioPreviewDecision,
) -> StudioPreviewDecisionResult:
    desired: StudioPreviewDecisionStatus = {
        "apply": "applied",
        "save_as_variation": "saved_as_variation",
        "discard": "discarded",
    }[decision]
    if record.status != desired:
        if record.status == "expired":
            raise StudioPreviewCandidateError(
                "preview_candidate_unavailable",
                "the Studio preview candidate expired before a decision",
                status_code=410,
            )
        raise StudioPreviewCandidateError(
            "preview_candidate_already_resolved",
            f"the Studio preview candidate was already {record.status}",
        )
    result_project_id = record.project_root_id
    family_id: str | None = None
    variation_index: int | None = None
    if desired == "saved_as_variation" and record.terminal_asset_id is not None:
        terminal = db.get(ImageAsset, record.terminal_asset_id)
        if terminal is None:
            raise StudioPreviewCandidateError(
                "preview_candidate_terminal_asset_unavailable",
                "the saved variation asset is unavailable",
                status_code=500,
            )
        result_project_id = terminal.root_id
        project = db.get(Project, result_project_id)
        if (
            project is None
            or project.owner != record.owner
            or project.root_id != terminal.root_id
            or project.family_id is None
            or project.variation_index is None
            or project.variation_index < 2
            or project.branched_from_project_root_id != record.project_root_id
            or project.branched_from_asset_id != record.source_asset_id
        ):
            raise StudioPreviewCandidateError(
                "preview_candidate_variation_corrupt",
                "the saved variation project lineage is incomplete",
                status_code=500,
            )
        family_id = project.family_id
        variation_index = project.variation_index
    return StudioPreviewDecisionResult(
        status=desired,
        candidate_id=record.id,
        kind=_kind(record),
        source_project_id=record.project_root_id,
        result_project_id=result_project_id,
        terminal_asset_id=record.terminal_asset_id,
        studio_job_id=record.studio_job_id,
        family_id=family_id,
        variation_index=variation_index,
    )


def _variation_label(value: str | None) -> str:
    label = (value or "").strip()
    if not label:
        raise StudioPreviewCandidateError(
            "variation_label_required",
            "name the variation before saving it",
            status_code=422,
        )
    return label


def _unavailable(
    exc: Exception,
    *,
    default_code: str = "preview_candidate_unavailable",
    default_status: int = 410,
) -> StudioPreviewCandidateError:
    return StudioPreviewCandidateError(
        getattr(exc, "code", default_code),
        getattr(exc, "detail", str(exc)),
        status_code=getattr(exc, "status_code", default_status),
    )


def decide_studio_preview_candidate(
    db: Session,
    candidate_id: str,
    *,
    owner: str,
    decision: StudioPreviewDecision,
    expected_active_asset_id: str,
    expected_design_version: int | None,
    variation_label: str | None = None,
) -> StudioPreviewDecisionResult:
    """Resolve one preview through its existing authoritative transaction."""

    record = _record(db, candidate_id, owner=owner, for_update=True)
    _guard_exact_decision(
        record,
        expected_active_asset_id=expected_active_asset_id,
        expected_design_version=expected_design_version,
    )
    kind = _kind(record)
    if record.status != "reviewing":
        if (
            decision == "save_as_variation"
            and record.status == "saved_as_variation"
        ):
            label = _variation_label(variation_label)
            try:
                result = fork_preview_candidate_variation(
                    db,
                    kind={
                        "visual": "studio_visual",
                        "catalog_revision": "catalog_revision",
                        "markup": "studio_markup",
                    }[kind],
                    run_id=record.image_run_id,
                    candidate_id=record.id,
                    variation_label=label,
                    created_by=owner,
                )
            except StudioHistoryError as exc:
                db.rollback()
                raise _unavailable(exc, default_status=exc.status_code) from exc
            return StudioPreviewDecisionResult(
                status="saved_as_variation",
                candidate_id=record.id,
                kind=kind,
                source_project_id=record.project_root_id,
                result_project_id=result.project_root_id,
                terminal_asset_id=result.asset_id,
                studio_job_id=record.studio_job_id,
                family_id=result.family_id,
                variation_index=result.variation_index,
            )
        return _terminal_result(db, record, decision=decision)
    if decision == "save_as_variation":
        label = _variation_label(variation_label)
        try:
            result = fork_preview_candidate_variation(
                db,
                kind={
                    "visual": "studio_visual",
                    "catalog_revision": "catalog_revision",
                    "markup": "studio_markup",
                }[kind],
                run_id=record.image_run_id,
                candidate_id=record.id,
                variation_label=label,
                created_by=owner,
            )
        except StudioHistoryError as exc:
            db.rollback()
            raise _unavailable(exc, default_status=exc.status_code) from exc
        return StudioPreviewDecisionResult(
            status="saved_as_variation",
            candidate_id=record.id,
            kind=kind,
            source_project_id=record.project_root_id,
            result_project_id=result.project_root_id,
            terminal_asset_id=result.asset_id,
            studio_job_id=record.studio_job_id,
            family_id=result.family_id,
            variation_index=result.variation_index,
        )

    if kind == "visual":
        try:
            candidate = get_studio_visual_candidate(
                db, record.image_run_id, record.id, owner=owner,
                require_active=(decision == "apply"),
            )
            if decision == "apply":
                accepted = apply_pre_spec_visual_candidate(
                    db,
                    candidate=candidate,
                    expected_active_asset_id=expected_active_asset_id,
                    created_by=owner,
                    commit=False,
                )
                remove_studio_visual_candidate(
                    db,
                    record.image_run_id,
                    record.id,
                    owner=owner,
                    review_id=accepted.review_id,
                    terminal_asset_id=accepted.asset_id,
                    commit=False,
                )
                terminal_asset_id = accepted.asset_id
            else:
                discarded = discard_pre_spec_visual_candidate(
                    db,
                    candidate=candidate,
                    expected_active_asset_id=expected_active_asset_id,
                    created_by=owner,
                    commit=False,
                )
                remove_studio_visual_candidate(
                    db,
                    record.image_run_id,
                    record.id,
                    owner=owner,
                    review_id=discarded.review_id,
                    commit=False,
                )
                terminal_asset_id = None
            db.commit()
        except StudioVisualCandidateUnavailable as exc:
            db.rollback()
            try:
                invalidate_studio_visual_candidate(
                    db,
                    record.image_run_id,
                    record.id,
                    owner=owner,
                )
            except StudioVisualCandidateUnavailable:
                db.rollback()
            raise _unavailable(exc) from exc
        except StudioHistoryError as exc:
            db.rollback()
            if exc.code in {
                "stale_asset_revision",
                "visual_preview_already_reviewed",
                "visual_preview_run_mismatch",
                "visual_preview_source_hash_mismatch",
                "visual_preview_unavailable",
            }:
                try:
                    invalidate_studio_visual_candidate(
                        db,
                        record.image_run_id,
                        record.id,
                        owner=owner,
                        error_code=exc.code,
                    )
                except StudioVisualCandidateUnavailable:
                    db.rollback()
            raise _unavailable(exc, default_status=exc.status_code) from exc
    elif kind == "catalog_revision":
        try:
            candidate, _ = lock_catalog_preview_candidate_for_decision(
                db, record.image_run_id, record.id, owner=owner,
                require_active=(decision == "apply"),
            )
            if decision == "apply":
                assert expected_design_version is not None
                accepted = accept_catalog_preview_revision(
                    db,
                    candidate,
                    expected_design_version=expected_design_version,
                    created_by=owner,
                    commit=False,
                )
                resolve_catalog_preview_candidate(
                    db,
                    record.image_run_id,
                    record.id,
                    owner=owner,
                    status="applied",
                    review_id=accepted.review_id,
                    terminal_asset_id=accepted.asset_id,
                    commit=False,
                )
                settle_catalog_preview_acceptance(db, candidate, owner=owner)
                terminal_asset_id = accepted.asset_id
                db.commit()
            else:
                discard_catalog_preview_candidate(
                    db, record.image_run_id, record.id, owner=owner,
                )
                terminal_asset_id = None
        except CatalogPreviewUnavailable as exc:
            db.rollback()
            try:
                invalidate_catalog_preview_candidate(
                    db,
                    record.image_run_id,
                    record.id,
                    owner=owner,
                )
            except CatalogPreviewJobError:
                db.rollback()
            raise _unavailable(exc) from exc
        except CatalogPreviewJobError as exc:
            db.rollback()
            raise _unavailable(
                exc,
                default_code="preview_candidate_job_conflict",
                default_status=409,
            ) from exc
        except WarningRevisionError as exc:
            db.rollback()
            raise _unavailable(exc, default_status=exc.status_code) from exc
    else:
        assert isinstance(record, StudioMarkupCandidateRecord)
        try:
            candidate, _ = lock_studio_markup_candidate_for_decision(
                db, record.image_run_id, record.id, owner=owner,
                require_active=(decision == "apply"),
            )
            assert expected_design_version is not None
            if decision == "apply":
                terminal_asset_id = accept_studio_markup_candidate(
                    db,
                    candidate,
                    expected_active_asset_id=expected_active_asset_id,
                    expected_design_version=expected_design_version,
                    created_by=owner,
                )
            else:
                discard_studio_markup_candidate(
                    db,
                    candidate,
                    expected_active_asset_id=expected_active_asset_id,
                    expected_design_version=expected_design_version,
                    created_by=owner,
                )
                terminal_asset_id = None
        except (StudioMarkupCandidateUnavailable, StudioMarkupError) as exc:
            db.rollback()
            raise _unavailable(exc) from exc
        except WarningRevisionError as exc:
            db.rollback()
            raise _unavailable(exc, default_status=exc.status_code) from exc

    status: StudioPreviewDecisionStatus = (
        "applied" if decision == "apply" else "discarded"
    )
    return StudioPreviewDecisionResult(
        status=status,
        candidate_id=record.id,
        kind=kind,
        source_project_id=record.project_root_id,
        result_project_id=record.project_root_id,
        terminal_asset_id=terminal_asset_id,
        studio_job_id=record.studio_job_id,
        family_id=None,
        variation_index=None,
    )

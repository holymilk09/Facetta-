"""Short-lived, non-asset storage for designer-review image candidates.

Warning bytes are deliberately kept outside the product asset chain.  The
cache is process-local and bounded: a restart or expiry asks the designer to
regenerate, while an explicit acceptance persists a new immutable revision and
an append-only review decision.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import re
from threading import Lock
from time import monotonic
from typing import Literal, TypedDict

from facetta.db import new_id
from facetta.json_types import JsonObject
from facetta.mounting_hardware import MountingView
from facetta.project_backbone import BriefProjectGeneration
from facetta.spec import Spec

_MAX_CANDIDATES = 64
_TTL_SECONDS = 2 * 60 * 60


WarningCandidatePromotionKind = Literal[
    "standard", "derived_only", "presentation_only",
]
MountingArtifactAuthority = Literal["factory_discussion_only"]


class MountingViewArtifactPayload(TypedDict):
    """JSON-safe metadata carried by one derived mounting-view candidate."""

    artifact_kind: Literal["mounting_view"]
    view: MountingView
    authority: MountingArtifactAuthority
    source_hash: str
    spec_visual_hash: str


@dataclass(frozen=True)
class MountingViewArtifactMetadata:
    """Immutable provenance for a non-primary mounting discussion view."""

    view: MountingView
    source_hash: str
    spec_visual_hash: str
    artifact_kind: Literal["mounting_view"] = "mounting_view"
    authority: MountingArtifactAuthority = "factory_discussion_only"

    def __post_init__(self) -> None:
        if self.artifact_kind != "mounting_view":
            raise ValueError("mounting artifact kind must be 'mounting_view'")
        if self.view not in {"plan", "front", "side", "section"}:
            raise ValueError("mounting artifact view is unsupported")
        if self.authority != "factory_discussion_only":
            raise ValueError(
                "mounting artifact authority must be factory_discussion_only"
            )
        if re.fullmatch(r"[0-9a-f]{64}", self.source_hash) is None:
            raise ValueError(
                "mounting artifact source_hash must be lowercase SHA-256 hex"
            )
        if re.fullmatch(r"[0-9a-f]{16}", self.spec_visual_hash) is None:
            raise ValueError(
                "mounting artifact spec_visual_hash must be 16 lowercase hex characters"
            )

    def to_payload(self) -> MountingViewArtifactPayload:
        """Return the typed transport payload without image bytes or secrets."""

        return {
            "artifact_kind": self.artifact_kind,
            "view": self.view,
            "authority": self.authority,
            "source_hash": self.source_hash,
            "spec_visual_hash": self.spec_visual_hash,
        }


@dataclass(frozen=True)
class MarkupWarningCandidate:
    candidate_id: str
    run_id: str
    project_root_id: str
    source_asset_id: str
    expected_active_asset_id: str
    reserved_asset_id: str | None
    expected_design_version: int
    image_bytes: bytes
    media_type: str
    operation: str
    asset_capability: str
    requested_change: str
    region_description: str
    drift: float | None
    next_spec: Spec | None
    ignored_fields: tuple[str, ...]
    qa: JsonObject
    routing: JsonObject
    created_by: str
    expires_at: float
    promotion_kind: WarningCandidatePromotionKind = "standard"
    artifact_metadata: MountingViewArtifactMetadata | None = None

    def __post_init__(self) -> None:
        if self.promotion_kind not in {
            "standard", "derived_only", "presentation_only",
        }:
            raise ValueError("warning candidate promotion_kind is unsupported")
        if self.artifact_metadata is not None and not isinstance(
            self.artifact_metadata, MountingViewArtifactMetadata,
        ):
            raise ValueError(
                "warning candidate artifact metadata must use the typed mounting contract"
            )
        if self.promotion_kind == "derived_only" and self.artifact_metadata is None:
            raise ValueError(
                "derived-only warning candidates require artifact metadata"
            )
        if self.promotion_kind == "standard" and self.artifact_metadata is not None:
            raise ValueError(
                "artifact metadata is only valid for derived-only candidates"
            )
        if self.promotion_kind == "derived_only" and self.next_spec is not None:
            raise ValueError(
                "derived-only warning candidates cannot propose a spec revision"
            )
        if (self.promotion_kind == "presentation_only"
                and self.artifact_metadata is not None):
            raise ValueError(
                "presentation-only candidates cannot carry factory artifact metadata"
            )
        if self.promotion_kind == "presentation_only" and self.next_spec is not None:
            raise ValueError(
                "presentation-only warning candidates cannot propose a spec revision"
            )
        if (self.promotion_kind == "presentation_only"
                and self.asset_capability not in {
                    "CLIENT_BEAUTY_RENDER", "CLIENT_PRODUCT_PHOTO",
                    "MARKETING_IMAGE",
                }):
            raise ValueError(
                "presentation-only candidate capability is unsupported"
            )

    @property
    def artifact_payload(self) -> MountingViewArtifactPayload | None:
        """Expose only typed provenance for clients that understand artifacts."""

        return (
            self.artifact_metadata.to_payload()
            if self.artifact_metadata is not None else None
        )


@dataclass(frozen=True)
class BriefWarningCandidate:
    candidate_id: str
    run_id: str
    stage: Literal["concept", "spec_render"]
    generation: BriefProjectGeneration
    brief: str
    variant: int
    owner: str
    title: str | None
    collection: str | None
    tags: tuple[str, ...]
    concept_warning_run_id: str | None
    image_bytes: bytes
    media_type: str
    expires_at: float


class WarningCandidateUnavailable(LookupError):
    """The requested temporary candidate is unknown, expired, or mismatched."""


_lock = Lock()
_candidates: OrderedDict[str, MarkupWarningCandidate] = OrderedDict()
_brief_candidates: OrderedDict[str, BriefWarningCandidate] = OrderedDict()


def _prune(now: float) -> None:
    expired = [
        candidate_id
        for candidate_id, candidate in _candidates.items()
        if candidate.expires_at <= now
    ]
    for candidate_id in expired:
        _candidates.pop(candidate_id, None)
    while len(_candidates) >= _MAX_CANDIDATES:
        _candidates.popitem(last=False)
    expired_brief = [
        candidate_id
        for candidate_id, candidate in _brief_candidates.items()
        if candidate.expires_at <= now
    ]
    for candidate_id in expired_brief:
        _brief_candidates.pop(candidate_id, None)
    while len(_brief_candidates) >= _MAX_CANDIDATES:
        _brief_candidates.popitem(last=False)


def store_markup_warning_candidate(
    *,
    run_id: str,
    project_root_id: str,
    source_asset_id: str,
    expected_active_asset_id: str,
    reserved_asset_id: str | None = None,
    expected_design_version: int,
    image_bytes: bytes,
    media_type: str,
    operation: str,
    asset_capability: str,
    requested_change: str,
    region_description: str,
    drift: float | None,
    next_spec: Spec | None,
    ignored_fields: tuple[str, ...],
    qa: JsonObject,
    routing: JsonObject,
    created_by: str,
    promotion_kind: WarningCandidatePromotionKind = "standard",
    artifact_metadata: MountingViewArtifactMetadata | None = None,
) -> MarkupWarningCandidate:
    now = monotonic()
    candidate = MarkupWarningCandidate(
        candidate_id=new_id("cand"),
        run_id=run_id,
        project_root_id=project_root_id,
        source_asset_id=source_asset_id,
        expected_active_asset_id=expected_active_asset_id,
        reserved_asset_id=reserved_asset_id,
        expected_design_version=expected_design_version,
        image_bytes=image_bytes,
        media_type=media_type,
        operation=operation,
        asset_capability=asset_capability,
        requested_change=requested_change,
        region_description=region_description,
        drift=drift,
        next_spec=next_spec,
        ignored_fields=ignored_fields,
        qa=qa,
        routing=routing,
        created_by=created_by,
        expires_at=now + _TTL_SECONDS,
        promotion_kind=promotion_kind,
        artifact_metadata=artifact_metadata,
    )
    with _lock:
        _prune(now)
        _candidates[candidate.candidate_id] = candidate
    return candidate


def get_markup_warning_candidate(
    run_id: str,
    candidate_id: str,
) -> MarkupWarningCandidate:
    now = monotonic()
    with _lock:
        _prune(now)
        candidate = _candidates.get(candidate_id)
        if candidate is None or candidate.run_id != run_id:
            raise WarningCandidateUnavailable(
                "the warning candidate expired or is no longer available")
        _candidates.move_to_end(candidate_id)
        return candidate


def discard_markup_warning_candidate(
    run_id: str,
    candidate_id: str,
    *,
    created_by: str,
) -> MarkupWarningCandidate:
    """Make a temporary candidate permanently unavailable to acceptance."""
    now = monotonic()
    with _lock:
        _prune(now)
        candidate = _candidates.get(candidate_id)
        if candidate is None or candidate.run_id != run_id:
            raise WarningCandidateUnavailable(
                "the warning candidate expired or is no longer available")
        if candidate.created_by != created_by:
            raise WarningCandidateUnavailable(
                "only the candidate creator may discard it")
        _candidates.pop(candidate_id, None)
        return candidate


def store_brief_warning_candidate(
    *,
    run_id: str,
    stage: Literal["concept", "spec_render"],
    generation: BriefProjectGeneration,
    brief: str,
    variant: int,
    owner: str,
    title: str | None,
    collection: str | None,
    tags: tuple[str, ...],
    concept_warning_run_id: str | None = None,
) -> BriefWarningCandidate:
    now = monotonic()
    image_bytes = (
        generation.concept_image if stage == "concept"
        else generation.spec_render
    )
    if image_bytes[:3] == b"\xff\xd8\xff":
        media_type = "image/jpeg"
    elif image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        media_type = "image/png"
    elif image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        media_type = "image/webp"
    else:
        raise ValueError("warning candidate is not a supported image")
    candidate = BriefWarningCandidate(
        candidate_id=new_id("cand"),
        run_id=run_id,
        stage=stage,
        generation=generation,
        brief=brief,
        variant=variant,
        owner=owner,
        title=title,
        collection=collection,
        tags=tags,
        concept_warning_run_id=concept_warning_run_id,
        image_bytes=image_bytes,
        media_type=media_type,
        expires_at=now + _TTL_SECONDS,
    )
    with _lock:
        _prune(now)
        _brief_candidates[candidate.candidate_id] = candidate
    return candidate


def get_brief_warning_candidate(candidate_id: str) -> BriefWarningCandidate:
    now = monotonic()
    with _lock:
        _prune(now)
        candidate = _brief_candidates.get(candidate_id)
        if candidate is None:
            raise WarningCandidateUnavailable(
                "the warning candidate expired or is no longer available")
        _brief_candidates.move_to_end(candidate_id)
        return candidate


def clear_warning_candidates_for_tests() -> None:
    """Keep isolated test databases from sharing process-local candidates."""
    with _lock:
        _candidates.clear()
        _brief_candidates.clear()

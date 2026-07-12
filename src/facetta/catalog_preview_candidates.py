"""Bounded, process-local storage for catalog previews awaiting Apply.

Image-run evidence is durable, while candidate bytes and the proposed spec are
deliberately temporary.  A catalog preview is not a product asset and cannot
become one unless the designer explicitly accepts it against the exact visual
and specification revision from which it was generated.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock
from time import monotonic
from typing import Literal

from facetta.db import new_id
from facetta.json_types import JsonObject
from facetta.spec import Spec


_MAX_CANDIDATES = 64
_TTL_SECONDS = 2 * 60 * 60


class CatalogPreviewUnavailable(LookupError):
    """The temporary preview is unknown, expired, discarded, or mismatched."""


@dataclass(frozen=True)
class CatalogPreviewCandidate:
    candidate_id: str
    run_id: str
    verdict: Literal["pass", "warn"]
    project_root_id: str
    source_asset_id: str
    expected_active_asset_id: str
    expected_design_version: int
    source_hash: str
    source_spec_visual_hash: str
    target_spec_visual_hash: str
    image_bytes: bytes
    media_type: str
    requested_change: str
    region_description: str
    drift: float | None
    next_spec: Spec
    component_path: str
    option_id: str
    spec_change: tuple[JsonObject, ...]
    qa: JsonObject
    routing: JsonObject
    created_by: str
    expires_at: float


_lock = Lock()
_candidates: OrderedDict[str, CatalogPreviewCandidate] = OrderedDict()


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


def store_catalog_preview_candidate(
    *,
    run_id: str,
    verdict: Literal["pass", "warn"],
    project_root_id: str,
    source_asset_id: str,
    expected_active_asset_id: str,
    expected_design_version: int,
    source_hash: str,
    source_spec_visual_hash: str,
    target_spec_visual_hash: str,
    image_bytes: bytes,
    media_type: str,
    requested_change: str,
    region_description: str,
    drift: float | None,
    next_spec: Spec,
    component_path: str,
    option_id: str,
    spec_change: tuple[JsonObject, ...],
    qa: JsonObject,
    routing: JsonObject,
    created_by: str,
) -> CatalogPreviewCandidate:
    now = monotonic()
    candidate = CatalogPreviewCandidate(
        candidate_id=new_id("cand"),
        run_id=run_id,
        verdict=verdict,
        project_root_id=project_root_id,
        source_asset_id=source_asset_id,
        expected_active_asset_id=expected_active_asset_id,
        expected_design_version=expected_design_version,
        source_hash=source_hash,
        source_spec_visual_hash=source_spec_visual_hash,
        target_spec_visual_hash=target_spec_visual_hash,
        image_bytes=image_bytes,
        media_type=media_type,
        requested_change=requested_change,
        region_description=region_description,
        drift=drift,
        next_spec=next_spec,
        component_path=component_path,
        option_id=option_id,
        spec_change=spec_change,
        qa=qa,
        routing=routing,
        created_by=created_by,
        expires_at=now + _TTL_SECONDS,
    )
    with _lock:
        _prune(now)
        _candidates[candidate.candidate_id] = candidate
    return candidate


def get_catalog_preview_candidate(
    run_id: str,
    candidate_id: str,
) -> CatalogPreviewCandidate:
    now = monotonic()
    with _lock:
        _prune(now)
        candidate = _candidates.get(candidate_id)
        if candidate is None or candidate.run_id != run_id:
            raise CatalogPreviewUnavailable(
                "the catalog preview expired, was discarded, or is no longer available"
            )
        _candidates.move_to_end(candidate_id)
        return candidate


def discard_catalog_preview_candidate(run_id: str, candidate_id: str) -> None:
    with _lock:
        candidate = _candidates.get(candidate_id)
        if candidate is None or candidate.run_id != run_id:
            raise CatalogPreviewUnavailable(
                "the catalog preview expired, was discarded, or is no longer available"
            )
        _candidates.pop(candidate_id, None)


def clear_catalog_preview_candidates_for_tests() -> None:
    with _lock:
        _candidates.clear()

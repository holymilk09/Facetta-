"""Bounded temporary storage for Studio pre-spec visual previews.

The durable image run records what the provider and QA system did. Candidate
bytes remain deliberately outside the canonical project asset chain until the
designer explicitly applies one against the exact selected visual it started
from.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock
from time import monotonic
from typing import Literal

from facetta.db import new_id
from facetta.json_types import JsonObject


_MAX_CANDIDATES = 64
_TTL_SECONDS = 2 * 60 * 60


class StudioVisualCandidateUnavailable(LookupError):
    """The candidate is unknown, expired, discarded, or already consumed."""


@dataclass(frozen=True)
class StudioVisualCandidate:
    candidate_id: str
    run_id: str
    verdict: Literal["pass", "warn"]
    project_root_id: str
    source_asset_id: str
    expected_selected_candidate_asset_id: str
    source_hash: str
    image_bytes: bytes
    media_type: str
    requested_change: str
    scope: Literal["appearance", "marked_region"]
    qa: JsonObject
    created_by: str
    expires_at: float


_lock = Lock()
_candidates: OrderedDict[str, StudioVisualCandidate] = OrderedDict()


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


def store_studio_visual_candidate(
    *,
    run_id: str,
    verdict: Literal["pass", "warn"],
    project_root_id: str,
    source_asset_id: str,
    expected_selected_candidate_asset_id: str,
    source_hash: str,
    image_bytes: bytes,
    media_type: str,
    requested_change: str,
    scope: Literal["appearance", "marked_region"],
    qa: JsonObject,
    created_by: str,
) -> StudioVisualCandidate:
    now = monotonic()
    candidate = StudioVisualCandidate(
        candidate_id=new_id("cand"),
        run_id=run_id,
        verdict=verdict,
        project_root_id=project_root_id,
        source_asset_id=source_asset_id,
        expected_selected_candidate_asset_id=(
            expected_selected_candidate_asset_id
        ),
        source_hash=source_hash,
        image_bytes=image_bytes,
        media_type=media_type,
        requested_change=requested_change,
        scope=scope,
        qa=qa,
        created_by=created_by,
        expires_at=now + _TTL_SECONDS,
    )
    with _lock:
        _prune(now)
        _candidates[candidate.candidate_id] = candidate
    return candidate


def get_studio_visual_candidate(
    run_id: str,
    candidate_id: str,
) -> StudioVisualCandidate:
    now = monotonic()
    with _lock:
        _prune(now)
        candidate = _candidates.get(candidate_id)
        if candidate is None or candidate.run_id != run_id:
            raise StudioVisualCandidateUnavailable(
                "the visual preview expired, was discarded, or was already applied"
            )
        _candidates.move_to_end(candidate_id)
        return candidate


def remove_studio_visual_candidate(
    run_id: str,
    candidate_id: str,
) -> None:
    with _lock:
        candidate = _candidates.get(candidate_id)
        if candidate is None or candidate.run_id != run_id:
            raise StudioVisualCandidateUnavailable(
                "the visual preview expired, was discarded, or was already applied"
            )
        _candidates.pop(candidate_id, None)


def clear_studio_visual_candidates_for_tests() -> None:
    with _lock:
        _candidates.clear()

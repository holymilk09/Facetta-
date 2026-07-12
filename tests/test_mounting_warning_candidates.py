"""Typed warning-candidate provenance for derived mounting views."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from facetta.spec import Spec
from facetta.warning_candidates import (
    MarkupWarningCandidate,
    MountingViewArtifactMetadata,
    clear_warning_candidates_for_tests,
    get_markup_warning_candidate,
    store_markup_warning_candidate,
)


SOURCE_HASH = "a" * 64
SPEC_VISUAL_HASH = "b" * 16


@pytest.fixture(autouse=True)
def isolated_warning_cache():
    clear_warning_candidates_for_tests()
    yield
    clear_warning_candidates_for_tests()


def _store(
    *,
    promotion_kind: str = "standard",
    metadata: MountingViewArtifactMetadata | None = None,
    next_spec: Spec | None = None,
) -> MarkupWarningCandidate:
    return store_markup_warning_candidate(
        run_id="run_mounting",
        project_root_id="ast_root",
        source_asset_id="ast_source",
        expected_active_asset_id="ast_active",
        expected_design_version=3,
        image_bytes=b"candidate-image",
        media_type="image/png",
        operation="VISUAL_ONLY_EDIT",
        asset_capability="MOUNTING_VIEW",
        requested_change="Create one side mounting view.",
        region_description="isolated side mounting view",
        drift=None,
        next_spec=next_spec,
        ignored_fields=(),
        qa={"verdict": "warn"},
        routing={"attempt_count": 1},
        created_by="usr_designer",
        promotion_kind=promotion_kind,  # type: ignore[arg-type]
        artifact_metadata=metadata,
    )


def test_existing_callers_default_to_standard_without_artifact_metadata() -> None:
    candidate = _store()

    assert candidate.promotion_kind == "standard"
    assert candidate.artifact_metadata is None
    assert candidate.artifact_payload is None
    assert get_markup_warning_candidate(
        candidate.run_id, candidate.candidate_id,
    ) is candidate


def test_derived_mounting_view_keeps_typed_discussion_only_provenance() -> None:
    metadata = MountingViewArtifactMetadata(
        view="side",
        source_hash=SOURCE_HASH,
        spec_visual_hash=SPEC_VISUAL_HASH,
    )
    candidate = _store(
        promotion_kind="derived_only",
        metadata=metadata,
    )

    assert candidate.promotion_kind == "derived_only"
    assert candidate.artifact_metadata is metadata
    assert candidate.artifact_payload == {
        "artifact_kind": "mounting_view",
        "view": "side",
        "authority": "factory_discussion_only",
        "source_hash": SOURCE_HASH,
        "spec_visual_hash": SPEC_VISUAL_HASH,
    }
    recovered = get_markup_warning_candidate(
        candidate.run_id, candidate.candidate_id,
    )
    assert recovered.artifact_payload == candidate.artifact_payload


def test_mounting_metadata_is_immutable() -> None:
    metadata = MountingViewArtifactMetadata(
        view="section",
        source_hash=SOURCE_HASH,
        spec_visual_hash=SPEC_VISUAL_HASH,
    )

    with pytest.raises(FrozenInstanceError):
        metadata.view = "front"  # type: ignore[misc]


def test_derived_only_requires_metadata() -> None:
    with pytest.raises(ValueError, match="require artifact metadata"):
        _store(promotion_kind="derived_only")


def test_standard_candidate_cannot_smuggle_derived_artifact_metadata() -> None:
    metadata = MountingViewArtifactMetadata(
        view="plan",
        source_hash=SOURCE_HASH,
        spec_visual_hash=SPEC_VISUAL_HASH,
    )

    with pytest.raises(ValueError, match="only valid for derived-only"):
        _store(metadata=metadata)


def test_derived_artifact_cannot_propose_a_spec_revision(example_spec: Spec) -> None:
    metadata = MountingViewArtifactMetadata(
        view="front",
        source_hash=SOURCE_HASH,
        spec_visual_hash=SPEC_VISUAL_HASH,
    )

    with pytest.raises(ValueError, match="cannot propose a spec revision"):
        _store(
            promotion_kind="derived_only",
            metadata=metadata,
            next_spec=example_spec,
        )


@pytest.mark.parametrize(
    "field, value, message",
    [
        ("source_hash", "ABC", "lowercase SHA-256"),
        ("spec_visual_hash", "f" * 15, "16 lowercase hex"),
        ("view", "perspective", "view is unsupported"),
        ("authority", "production_confirmed", "factory_discussion_only"),
        ("artifact_kind", "factory_sheet", "mounting_view"),
    ],
)
def test_mounting_metadata_rejects_untyped_or_unbound_payloads(
    field: str,
    value: str,
    message: str,
) -> None:
    values = {
        "view": "side",
        "source_hash": SOURCE_HASH,
        "spec_visual_hash": SPEC_VISUAL_HASH,
        "artifact_kind": "mounting_view",
        "authority": "factory_discussion_only",
    }
    values[field] = value

    with pytest.raises(ValueError, match=message):
        MountingViewArtifactMetadata(**values)  # type: ignore[arg-type]


def test_unknown_promotion_kind_is_rejected() -> None:
    with pytest.raises(ValueError, match="promotion_kind is unsupported"):
        _store(promotion_kind="primary")


def test_raw_metadata_dictionary_cannot_bypass_typed_hash_validation() -> None:
    with pytest.raises(ValueError, match="must use the typed mounting contract"):
        _store(
            promotion_kind="derived_only",
            metadata={  # type: ignore[arg-type]
                "artifact_kind": "mounting_view",
                "view": "side",
                "authority": "factory_discussion_only",
                "source_hash": "not-a-hash",
                "spec_visual_hash": SPEC_VISUAL_HASH,
            },
        )

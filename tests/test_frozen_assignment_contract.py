from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import facetta.frozen_assignment_contract as contract
from facetta.design_form import NormalizedPoint, NormalizedPolygon
from facetta.frozen_assignment_contract import (
    ASSIGNMENT_BUNDLE_SIGNATURE_DOMAIN,
    SIGNED_ASSIGNMENT_BUNDLE_SCHEMA,
    build_release_authority_decision_binding,
    canonical_assignment_bundle_payload,
    canonical_component_map_attestation_payload,
    verify_signed_assignment_bundle,
)
from facetta.revision_component_map import (
    RevisionComponent,
    RevisionComponentMap,
    component_map_hash,
    polygon_hash,
)
from facetta.ring_evals import (
    CANONICAL_RING_EDITS,
    RING_GOLDEN_CASES,
    apply_canonical_ring_edit,
    build_ring_golden_spec,
)


_RING_COMPONENTS = (
    ("center", "center_stone"),
    ("prongs", "prongs"),
    ("setting", "setting"),
    ("shank", "shank"),
    ("shoulders", "shoulders"),
    ("gallery", "gallery"),
    ("metal", "metal_zone"),
    ("background", "background"),
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")).hexdigest()


def _fixture(tmp_path: Path) -> tuple[
    Path,
    Ed25519PrivateKey,
    dict[str, object],
    dict[str, object],
]:
    root = tmp_path / "repo"
    root.mkdir()
    private_key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    public_key = root / "assignment-reviewer.pub"
    public_key.write_bytes(private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ))
    profile_sha256 = "a" * 64
    source_spec = build_ring_golden_spec(RING_GOLDEN_CASES[0])
    impossible_edit = next(
        edit for edit in CANONICAL_RING_EDITS
        if edit.id == "impossible-band-width"
    )
    target_spec, canonical_edit_issues = apply_canonical_ring_edit(
        source_spec,
        impossible_edit,
    )
    assert target_spec is None
    assert canonical_edit_issues
    config: dict[str, object] = {
        "assignment_reviewer_public_key": {
            "key_id": "assignment-reviewer-test-v1",
            "path": public_key.name,
            "sha256": _sha256(public_key),
            "reviewer_profile_sha256": profile_sha256,
        },
    }
    bundle: dict[str, object] = {
        "schema_version": SIGNED_ASSIGNMENT_BUNDLE_SCHEMA,
        "workload_sha256": "b" * 64,
        "corpus_run_id": "test-corpus-run-v1",
        "reviewer_key_id": "assignment-reviewer-test-v1",
        "reviewer_profile_sha256": profile_sha256,
        "reviewed_template_sha256": "c" * 64,
        "release_authority_decision": None,
        "assignments": [{
            "source_filename": "ring.png",
            "kind": "edit",
            "evaluation_id": impossible_edit.id,
            "binding": {
                "schema_version": "facetta-frozen-source-assignment.v1",
                "review_status": "approved",
                "applicability": "not_applicable",
                "not_applicable_reason": (
                    "canonical_delta_inapplicable/"
                    "canonical-edit-apply-failed.v1"
                ),
                "review_evidence_sha256": "1" * 64,
                "source_spec_evidence_sha256": "2" * 64,
                "component_map_sha256": "3" * 64,
                "region_evidence_sha256": "4" * 64,
                "source_sha256": "5" * 64,
                "source_spec": source_spec.model_dump(mode="json"),
                "canonical_edit_issues": canonical_edit_issues,
            },
        }],
        "signature": None,
    }
    _sign(bundle, private_key)
    return root, private_key, config, bundle


def _sign(bundle: dict[str, object], private_key: Ed25519PrivateKey) -> None:
    bundle["signature"] = {
        "algorithm": "Ed25519",
        "key_id": "assignment-reviewer-test-v1",
        "value": base64.b64encode(
            private_key.sign(canonical_assignment_bundle_payload(bundle))
        ).decode("ascii"),
    }


def _install_component_absence_binding(
    root: Path,
    config: dict[str, object],
    bundle: dict[str, object],
    *,
    resolve_required: bool = False,
) -> dict[str, object]:
    mapper_private_key = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
    mapper_public_key = root / "component-mapper.pub"
    mapper_public_key.write_bytes(
        mapper_private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    )
    mapper_key_id = "component-mapper-test-v1"
    config["component_mapper_public_key"] = {
        "key_id": mapper_key_id,
        "path": mapper_public_key.name,
        "sha256": _sha256(mapper_public_key),
    }
    calibration_sha256 = "8" * 64
    mapper_contract = root / "component-mapper-contract.json"
    mapper_contract.write_text(json.dumps({
        "schema_version": "facetta-frozen-component-mapper-contract.v1",
        "mapper_contract": "test.mapper-contract.v1",
        "calibration_evidence_sha256": calibration_sha256,
        "minimum_tested_source_count": 144,
        "required_component_kinds": [
            "background",
            "center_stone",
            "gallery",
            "metal_zone",
            "prongs",
            "setting",
            "shank",
            "shoulders",
        ],
        "coverage_policy": "all-required-kinds-unresolved.v1",
    }))
    config["frozen_components"] = {
        "assignment_component_mapper_contract": (
            f"{mapper_contract.name}@sha256:{_sha256(mapper_contract)}"
        ),
    }
    source_sha256 = "5" * 64
    required_kinds = {
        "prongs",
        "setting",
        "shank",
        "shoulders",
        "gallery",
        "metal_zone",
    }
    components: list[RevisionComponent] = []
    for index, (component_id, kind) in enumerate(_RING_COMPONENTS):
        offset = min(index, 4) * 0.01
        polygons = (NormalizedPolygon(points=(
            NormalizedPoint(x=0.20 + offset, y=0.20),
            NormalizedPoint(x=0.45 + offset, y=0.20),
            NormalizedPoint(x=0.45 + offset, y=0.45),
            NormalizedPoint(x=0.20 + offset, y=0.45),
        )),)
        resolved = kind not in required_kinds or resolve_required
        components.append(RevisionComponent(
            component_id=component_id,
            kind=kind,
            label=component_id,
            resolution="resolved" if resolved else "unresolved",
            polygons=polygons if resolved else (),
            polygon_sha256=polygon_hash(polygons) if resolved else None,
        ))
    component_map = RevisionComponentMap(
        asset_id="assignment-source-ring-v1",
        asset_sha256=source_sha256,
        raster_width=32,
        raster_height=24,
        jewelry_type="ring",
        mapper_contract="test.mapper-contract.v1",
        calibration_evidence_sha256=calibration_sha256,
        components=tuple(components),
    )
    component_map_sha256 = component_map_hash(component_map)
    attestation: dict[str, object] = {
        "schema_version": "facetta-frozen-component-map-attestation.v1",
        "source_sha256": source_sha256,
        "component_map_sha256": component_map_sha256,
        "mapper_contract": "test.mapper-contract.v1",
        "calibration_evidence_sha256": calibration_sha256,
        "corpus_run_id": bundle["corpus_run_id"],
        "run_id": "maprun_" + "6" * 64,
        "mapper_key_id": mapper_key_id,
        "signature": None,
    }
    attestation["signature"] = {
        "algorithm": "Ed25519",
        "key_id": mapper_key_id,
        "value": base64.b64encode(
            mapper_private_key.sign(
                canonical_component_map_attestation_payload(attestation)
            )
        ).decode("ascii"),
    }
    binding: dict[str, object] = {
        "schema_version": "facetta-frozen-source-assignment.v1",
        "review_status": "approved",
        "applicability": "not_applicable",
        "not_applicable_reason": (
            "source_component_absent/"
            "component-map-all-required-kinds-absent.v1"
        ),
        "review_evidence_sha256": "1" * 64,
        "source_spec_evidence_sha256": "2" * 64,
        "component_map_sha256": component_map_sha256,
        "region_evidence_sha256": "4" * 64,
        "source_sha256": source_sha256,
        "component_map": component_map.model_dump(mode="json"),
        "component_map_attestation": attestation,
        "component_map_attestation_sha256": _canonical_sha256(attestation),
    }
    assignments = bundle["assignments"]
    assert isinstance(assignments, list)
    assignments[0]["kind"] = "edit"
    assignments[0]["evaluation_id"] = "metal-color"
    assignments[0]["binding"] = binding
    return binding


def _active_authority_decision() -> dict[str, object]:
    return {
        "schema_version": "facetta-release-authority-bundle-decision.v2",
        "status": "pass",
        "decision_time": "2026-07-15T04:05:06Z",
        "verification_policy": "facetta-release-authority-policy-v1",
        "status_list": {
            "list_id": "release-status-test-v1",
            "sequence": 1,
        },
        "authorities": [
            {"role": "executor"},
            {"role": "canonical_api_runner"},
            {"role": "assignment_reviewer"},
            {"role": "gia_reviewer"},
            {"role": "founder"},
            {"role": "jewelry_designer"},
            {"role": "staging_reviewer"},
        ],
        "errors": [],
    }


def _bind_active_authority(
    bundle: dict[str, object],
    config: dict[str, object],
    private_key: Ed25519PrivateKey,
) -> dict[str, object]:
    decision = _active_authority_decision()
    config["release_authority_bundle"] = {
        "schema_version": "facetta-release-authority-bundle-config.v2",
        "fixture": "current-authority-set",
    }
    bundle["release_authority_decision"] = build_release_authority_decision_binding(
        config,
        decision,
        reviewed_at="2026-07-15T03:05:06Z",
    )
    _sign(bundle, private_key)
    return decision


def test_signed_assignment_bundle_verifies_enrolled_domain_separated_payload(
    tmp_path: Path,
):
    root, _, config, bundle = _fixture(tmp_path)

    reviewer = verify_signed_assignment_bundle(
        bundle,
        config,
        repository_root=root,
    )

    assert reviewer.key_id == "assignment-reviewer-test-v1"
    assert canonical_assignment_bundle_payload(bundle).startswith(
        ASSIGNMENT_BUNDLE_SIGNATURE_DOMAIN + b"{"
    )


@pytest.mark.parametrize(
    "production_config",
    [
        {"config_id": "founder-ring-90-85-90-v1"},
        {"corpus_id": "founder-reference-144-v1"},
        {"release_authority_bundle": {"configured": True}},
    ],
)
def test_null_authority_decision_is_allowed_only_for_unconfigured_synthetic_runs(
    tmp_path: Path,
    production_config: dict[str, object],
):
    root, _, config, bundle = _fixture(tmp_path)
    config.update(production_config)

    with pytest.raises(ValueError, match="release authority decision is required"):
        verify_signed_assignment_bundle(bundle, config, repository_root=root)


def test_signed_assignment_bundle_verifies_current_seven_role_authority_seam(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    root, private_key, config, bundle = _fixture(tmp_path)
    decision = _bind_active_authority(bundle, config, private_key)
    calls: list[tuple[dict[str, object], Path, datetime]] = []

    def verify_authority(
        actual_config: dict[str, object],
        repository_root: Path,
        decision_time: datetime,
    ) -> dict[str, object]:
        calls.append((actual_config, repository_root, decision_time))
        return decision

    monkeypatch.setattr(
        contract,
        "verify_release_authority_bundle",
        verify_authority,
    )

    reviewer = verify_signed_assignment_bundle(bundle, config, repository_root=root)

    assert reviewer.key_id == "assignment-reviewer-test-v1"
    assert calls == [(config, root, datetime(2026, 7, 15, 4, 5, 6, tzinfo=UTC))]
    assert bundle["release_authority_decision"]["reviewed_at"] == (
        "2026-07-15T03:05:06Z"
    )


@pytest.mark.parametrize("mismatch", ["config", "decision"])
def test_signed_assignment_bundle_rejects_current_authority_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mismatch: str,
):
    root, private_key, config, bundle = _fixture(tmp_path)
    decision = _bind_active_authority(bundle, config, private_key)
    if mismatch == "config":
        release_config = config["release_authority_bundle"]
        assert isinstance(release_config, dict)
        release_config["fixture"] = "rotated-authority-set"
        expected = "release authority config differs"
    else:
        decision = {**decision, "status_list": {"list_id": "new-list", "sequence": 2}}
        expected = "release authority decision differs"
    monkeypatch.setattr(
        contract,
        "verify_release_authority_bundle",
        lambda *_: decision,
    )

    with pytest.raises(ValueError, match=expected):
        verify_signed_assignment_bundle(bundle, config, repository_root=root)


def test_signed_authority_decision_field_tamper_invalidates_bundle_signature(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    root, private_key, config, bundle = _fixture(tmp_path)
    decision = _bind_active_authority(bundle, config, private_key)
    monkeypatch.setattr(
        contract,
        "verify_release_authority_bundle",
        lambda *_: decision,
    )
    authority_binding = bundle["release_authority_decision"]
    assert isinstance(authority_binding, dict)
    authority_binding["authority_decision_sha256"] = "0" * 64

    with pytest.raises(ValueError, match="signature is invalid"):
        verify_signed_assignment_bundle(bundle, config, repository_root=root)


@pytest.mark.parametrize("inactive_case", ["failed", "missing_reviewer"])
def test_signed_assignment_bundle_requires_active_assignment_reviewer_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    inactive_case: str,
):
    root, private_key, config, bundle = _fixture(tmp_path)
    decision = _bind_active_authority(bundle, config, private_key)
    if inactive_case == "failed":
        decision["status"] = "fail"
    else:
        authorities = decision["authorities"]
        assert isinstance(authorities, list)
        decision["authorities"] = [
            row for row in authorities if row.get("role") != "assignment_reviewer"
        ]
    authority_binding = bundle["release_authority_decision"]
    assert isinstance(authority_binding, dict)
    authority_binding["authority_decision_sha256"] = _canonical_sha256(decision)
    _sign(bundle, private_key)
    monkeypatch.setattr(
        contract,
        "verify_release_authority_bundle",
        lambda *_: decision,
    )

    with pytest.raises(ValueError, match="release authority decision is not active"):
        verify_signed_assignment_bundle(bundle, config, repository_root=root)


def test_signed_assignment_bundle_rejects_noncanonical_authority_decision_time(
    tmp_path: Path,
):
    root, private_key, config, bundle = _fixture(tmp_path)
    decision = _bind_active_authority(bundle, config, private_key)
    authority_binding = bundle["release_authority_decision"]
    assert isinstance(authority_binding, dict)
    authority_binding["decision_time"] = "2026-07-15T04:05:06+00:00"
    authority_binding["authority_decision_sha256"] = _canonical_sha256(decision)
    _sign(bundle, private_key)

    with pytest.raises(ValueError, match="decision time is not canonical UTC"):
        verify_signed_assignment_bundle(bundle, config, repository_root=root)


def test_signed_assignment_bundle_rejects_review_after_authority_decision(
    tmp_path: Path,
):
    root, private_key, config, bundle = _fixture(tmp_path)
    _bind_active_authority(bundle, config, private_key)
    authority_binding = bundle["release_authority_decision"]
    assert isinstance(authority_binding, dict)
    authority_binding["reviewed_at"] = "2026-07-15T05:05:06Z"
    _sign(bundle, private_key)

    with pytest.raises(ValueError, match="review time follows authority decision time"):
        verify_signed_assignment_bundle(bundle, config, repository_root=root)


def test_assignment_signature_cannot_be_replayed_from_undomained_json(
    tmp_path: Path,
):
    root, private_key, config, bundle = _fixture(tmp_path)
    unsigned = {key: value for key, value in bundle.items() if key != "signature"}
    raw_json = json.dumps(
        unsigned,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    bundle["signature"] = {
        "algorithm": "Ed25519",
        "key_id": "assignment-reviewer-test-v1",
        "value": base64.b64encode(private_key.sign(raw_json)).decode("ascii"),
    }

    with pytest.raises(ValueError, match="signature is invalid"):
        verify_signed_assignment_bundle(bundle, config, repository_root=root)


def test_signed_assignment_bundle_rejects_unknown_top_level_field(
    tmp_path: Path,
):
    root, _, config, bundle = _fixture(tmp_path)
    bundle["operator_note"] = "not part of the signed contract"

    with pytest.raises(ValueError, match="unexpected or missing fields"):
        verify_signed_assignment_bundle(bundle, config, repository_root=root)


def test_signed_assignment_bundle_rejects_unknown_row_field_after_signature(
    tmp_path: Path,
):
    root, private_key, config, bundle = _fixture(tmp_path)
    assignments = bundle["assignments"]
    assert isinstance(assignments, list)
    assignments[0]["provider"] = "operator-selected"
    _sign(bundle, private_key)

    with pytest.raises(ValueError, match="row has unexpected or missing fields"):
        verify_signed_assignment_bundle(bundle, config, repository_root=root)


def test_signed_assignment_bundle_accepts_exact_execute_binding(tmp_path: Path):
    root, private_key, config, bundle = _fixture(tmp_path)
    assignments = bundle["assignments"]
    assert isinstance(assignments, list)
    assignments[0]["binding"] = {
        "schema_version": "facetta-frozen-source-assignment.v1",
        "review_status": "approved",
        "applicability": "execute",
        "review_evidence_sha256": "1" * 64,
        "source_spec_evidence_sha256": "2" * 64,
        "component_map_sha256": "3" * 64,
        "region_evidence_sha256": "4" * 64,
        "source_spec": {"reviewed": "source"},
        "target_spec": {"reviewed": "target"},
        "instruction": "reviewed instruction",
        "region_description": None,
        "frozen_facts": ["reviewed fact"],
    }
    _sign(bundle, private_key)

    verify_signed_assignment_bundle(bundle, config, repository_root=root)


def test_signed_bundle_runtime_verifies_exact_mapper_attestation(tmp_path: Path):
    root, private_key, config, bundle = _fixture(tmp_path)
    _install_component_absence_binding(root, config, bundle)
    _sign(bundle, private_key)

    verify_signed_assignment_bundle(bundle, config, repository_root=root)


@pytest.mark.parametrize(
    "reason",
    (
        "source_component_absent-but-not-exact",
        "canonical_delta_inapplicable/canonical-edit-apply-failed.v2",
        "reviewed source is out of scope",
        "",
    ),
)
def test_signed_bundle_rejects_unknown_not_applicable_reason(
    tmp_path: Path,
    reason: str,
):
    root, private_key, config, bundle = _fixture(tmp_path)
    assignments = bundle["assignments"]
    assert isinstance(assignments, list)
    binding = assignments[0]["binding"]
    assert isinstance(binding, dict)
    binding["not_applicable_reason"] = reason
    _sign(bundle, private_key)

    with pytest.raises(ValueError, match="not-applicable reason is unsupported"):
        verify_signed_assignment_bundle(bundle, config, repository_root=root)


def test_signed_bundle_recomputes_canonical_delta_absence(tmp_path: Path):
    root, private_key, config, bundle = _fixture(tmp_path)
    assignments = bundle["assignments"]
    assert isinstance(assignments, list)
    assignments[0]["evaluation_id"] = "metal-color"
    _sign(bundle, private_key)

    with pytest.raises(
        ValueError,
        match="canonical-delta absence contradicts a valid canonical edit",
    ):
        verify_signed_assignment_bundle(bundle, config, repository_root=root)


def test_signed_bundle_rejects_render_not_applicable_at_contract_boundary(
    tmp_path: Path,
):
    root, private_key, config, bundle = _fixture(tmp_path)
    assignments = bundle["assignments"]
    assert isinstance(assignments, list)
    assignments[0]["kind"] = "render"
    assignments[0]["evaluation_id"] = "round-solitaire-yellow-4-narrow"
    _sign(bundle, private_key)

    with pytest.raises(ValueError, match="render cannot be not_applicable"):
        verify_signed_assignment_bundle(bundle, config, repository_root=root)


def test_signed_bundle_rejects_absence_when_required_components_are_resolved(
    tmp_path: Path,
):
    root, private_key, config, bundle = _fixture(tmp_path)
    _install_component_absence_binding(
        root,
        config,
        bundle,
        resolve_required=True,
    )
    _sign(bundle, private_key)

    with pytest.raises(
        ValueError,
        match="source-component absence contradicts resolved component kinds",
    ):
        verify_signed_assignment_bundle(bundle, config, repository_root=root)


@pytest.mark.parametrize("attack", ("arbitrary_hash", "forged_attestation"))
def test_assignment_reviewer_cannot_bypass_mapper_attestation_at_runtime(
    tmp_path: Path,
    attack: str,
):
    root, private_key, config, bundle = _fixture(tmp_path)
    binding = _install_component_absence_binding(root, config, bundle)
    if attack == "arbitrary_hash":
        binding["component_map_attestation_sha256"] = "9" * 64
        expected = "attestation hash differs"
    else:
        attestation = binding["component_map_attestation"]
        assert isinstance(attestation, dict)
        signature = attestation["signature"]
        assert isinstance(signature, dict)
        signature["value"] = base64.b64encode(bytes(64)).decode("ascii")
        binding["component_map_attestation_sha256"] = _canonical_sha256(attestation)
        expected = "attestation signature is invalid"
    _sign(bundle, private_key)

    with pytest.raises(ValueError, match=expected):
        verify_signed_assignment_bundle(bundle, config, repository_root=root)


def test_signed_bundle_rejects_rehashed_map_without_fresh_mapper_attestation(
    tmp_path: Path,
):
    root, private_key, config, bundle = _fixture(tmp_path)
    binding = _install_component_absence_binding(root, config, bundle)
    map_payload = binding["component_map"]
    assert isinstance(map_payload, dict)
    components = map_payload["components"]
    assert isinstance(components, list)
    components[0]["label"] = "reviewer-mutated-center"
    mutated_map = RevisionComponentMap.model_validate(map_payload)
    binding["component_map_sha256"] = component_map_hash(mutated_map)
    _sign(bundle, private_key)

    with pytest.raises(ValueError, match="component_map_sha256 binding differs"):
        verify_signed_assignment_bundle(bundle, config, repository_root=root)


def test_signed_bundle_rejects_component_map_source_mismatch(tmp_path: Path):
    root, private_key, config, bundle = _fixture(tmp_path)
    binding = _install_component_absence_binding(root, config, bundle)
    binding["source_sha256"] = "7" * 64
    _sign(bundle, private_key)

    with pytest.raises(ValueError, match="component map source differs"):
        verify_signed_assignment_bundle(bundle, config, repository_root=root)


def test_signed_bundle_rejects_mapper_reusing_reviewer_key(tmp_path: Path):
    root, private_key, config, bundle = _fixture(tmp_path)
    _install_component_absence_binding(root, config, bundle)
    reviewer_config = config["assignment_reviewer_public_key"]
    assert isinstance(reviewer_config, dict)
    config["component_mapper_public_key"] = {
        "key_id": reviewer_config["key_id"],
        "path": reviewer_config["path"],
        "sha256": reviewer_config["sha256"],
    }
    _sign(bundle, private_key)

    with pytest.raises(
        ValueError,
        match="component mapper enrollment must be distinct",
    ):
        verify_signed_assignment_bundle(bundle, config, repository_root=root)


@pytest.mark.parametrize("mutation", ("extra", "missing"))
def test_signed_assignment_bundle_rejects_shadow_or_missing_binding_fields(
    tmp_path: Path,
    mutation: str,
):
    root, private_key, config, bundle = _fixture(tmp_path)
    assignments = bundle["assignments"]
    assert isinstance(assignments, list)
    binding = assignments[0]["binding"]
    assert isinstance(binding, dict)
    if mutation == "extra":
        binding["provider_override"] = "ignored by not-applicable resolver"
    else:
        del binding["region_evidence_sha256"]
    _sign(bundle, private_key)

    with pytest.raises(
        ValueError,
        match="binding has unexpected or missing fields",
    ):
        verify_signed_assignment_bundle(bundle, config, repository_root=root)


def test_signed_assignment_bundle_rejects_unenrolled_or_drifted_reviewer(
    tmp_path: Path,
):
    root, _, config, bundle = _fixture(tmp_path)
    enrollment = config["assignment_reviewer_public_key"]
    assert isinstance(enrollment, dict)
    enrollment["reviewer_profile_sha256"] = "d" * 64

    with pytest.raises(ValueError, match="reviewer profile differs"):
        verify_signed_assignment_bundle(bundle, config, repository_root=root)


def test_unsigned_v1_assignment_bundle_is_rejected(tmp_path: Path):
    root, _, config, bundle = _fixture(tmp_path)
    bundle.clear()
    bundle.update({
        "schema_version": "facetta-frozen-assignment-bundle.v1",
        "workload_sha256": "b" * 64,
        "corpus_run_id": "legacy-unsigned-run",
        "assignments": [],
    })

    with pytest.raises(ValueError, match="schema is unsupported"):
        verify_signed_assignment_bundle(bundle, config, repository_root=root)

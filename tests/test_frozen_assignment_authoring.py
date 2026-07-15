from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import sys
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import util
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from PIL import Image

import facetta.frozen_assignment_authoring as authoring
from facetta.design_form import NormalizedPoint, NormalizedPolygon
from facetta.frozen_assignment_authoring import (
    ASSIGNMENT_REGION_EVIDENCE_SCHEMA,
    ASSIGNMENT_REVIEW_EVIDENCE_SCHEMA,
    COMPONENT_MAP_ATTESTATION_SCHEMA,
    COMPONENT_MAP_CALIBRATION_EVIDENCE_SCHEMA,
    COMPONENT_MAPPER_CONTRACT_SCHEMA,
    SOURCE_SPEC_EVIDENCE_SCHEMA,
    AssignmentCompilation,
    build_assignment_authoring_template,
    canonical_component_map_attestation_payload,
    finalize_signed_assignment_bundle,
    validate_completed_assignment_template,
)
from facetta.frozen_assignment_contract import (
    EnrolledAssignmentReviewer,
    load_enrolled_assignment_reviewer,
    verify_signed_assignment_bundle,
)
from facetta.frozen_capture_workload import canonical_object_sha256, file_sha256
from facetta.revision_component_map import (
    RevisionComponent,
    RevisionComponentMap,
    component_map_hash,
    polygon_hash,
)
from facetta.ring_evals import RING_GOLDEN_CASES, build_ring_golden_spec


REQUIRED_COMPONENTS = (
    ("center", "center_stone"),
    ("prongs", "prongs"),
    ("setting", "setting"),
    ("shank", "shank"),
    ("shoulders", "shoulders"),
    ("gallery", "gallery"),
    ("metal", "metal_zone"),
    ("background", "background"),
)


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _png() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (32, 24), (192, 164, 96)).save(output, format="PNG")
    return output.getvalue()


def _component_map(
    image: bytes,
    *,
    unresolved_kinds: frozenset[str] = frozenset(),
    extra_components: tuple[tuple[str, str], ...] = (),
    calibration_evidence_sha256: str | None = None,
) -> RevisionComponentMap:
    components: list[RevisionComponent] = []
    for index, (component_id, kind) in enumerate(
        REQUIRED_COMPONENTS + extra_components
    ):
        offset = min(index, 4) * 0.01
        polygons = (NormalizedPolygon(points=(
            NormalizedPoint(x=0.20 + offset, y=0.20),
            NormalizedPoint(x=0.45 + offset, y=0.20),
            NormalizedPoint(x=0.45 + offset, y=0.45),
            NormalizedPoint(x=0.20 + offset, y=0.45),
        )),)
        resolved = kind not in unresolved_kinds
        components.append(RevisionComponent(
            component_id=component_id,
            kind=kind,
            label=component_id,
            resolution="resolved" if resolved else "unresolved",
            polygons=polygons if resolved else (),
            polygon_sha256=polygon_hash(polygons) if resolved else None,
        ))
    return RevisionComponentMap(
        asset_id="assignment-source-ring-v1",
        asset_sha256=hashlib.sha256(image).hexdigest(),
        raster_width=32,
        raster_height=24,
        jewelry_type="ring",
        mapper_contract="test.assignment-reviewer-map.v1",
        calibration_evidence_sha256=calibration_evidence_sha256,
        components=tuple(components),
    )


@dataclass(frozen=True)
class Fixture:
    repository_root: Path
    evidence_root: Path
    manifest: Path
    config: Path
    workload: Path
    source_path: Path
    spec_path: Path
    map_path: Path
    calibration_path: Path
    mapper_contract_path: Path
    attestation_path: Path
    reviewer: EnrolledAssignmentReviewer
    private_key: Ed25519PrivateKey
    private_key_path: Path
    mapper_private_key: Ed25519PrivateKey


def _fixture(tmp_path: Path) -> Fixture:
    repository_root = tmp_path / "repo"
    evidence_root = repository_root / "retained-evidence"
    source_path = evidence_root / "sources" / "ring.png"
    image = _png()
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(image)

    manifest = repository_root / "manifest.json"
    config = repository_root / "config.json"
    workload = repository_root / "workload.json"
    source_sha256 = hashlib.sha256(image).hexdigest()
    _write(manifest, {
        "corpus_id": "assignment-authoring-fixture-v1",
        "expected_source_count": 1,
        "sources": [{"filename": "ring.png", "sha256": source_sha256}],
        "evaluation_slice": {
            "ring_source_filenames": ["ring.png"],
            "render_case_ids": ["round-solitaire-yellow-4-narrow"],
            "operation_ids": ["metal-color"],
            "operation_classes": {
                "quick_appearance": ["metal-color"],
                "structural": [],
            },
        },
    })
    _write(workload, {
        "schema_version": "facetta-frozen-capture-workload.v1",
        "workload_id": "assignment-authoring-workload-v1",
        "corpus_id": "assignment-authoring-fixture-v1",
        "config_id": "assignment-authoring-config-v1",
        "manifest_sha256": file_sha256(manifest),
        "expected_integrity_source_count": 1,
        "expected_quality_source_count": 1,
        "ring_quality_evaluation_set_id": "ring-full-v1",
        "evaluation_sets": {"ring-full-v1": [
            {
                "kind": "render",
                "evaluation_id": "round-solitaire-yellow-4-narrow",
                "operation_class": "render_conformance",
            },
            {
                "kind": "edit",
                "evaluation_id": "metal-color",
                "operation_class": "quick_appearance",
            },
        ]},
        "sources": [{
            "filename": "ring.png",
            "sha256": source_sha256,
            "integrity_required": True,
            "quality": {"slice": "ring", "evaluation_set_id": "ring-full-v1"},
        }],
    })

    routing_source = (
        Path(__file__).resolve().parents[1]
        / "docs/evals/frozen-founder-corpus-v1/routing-contract.v1.json"
    )
    routing = repository_root / "routing-contract.v1.json"
    routing.parent.mkdir(parents=True, exist_ok=True)
    routing.write_bytes(routing_source.read_bytes())

    private_key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    public_key = repository_root / "assignment-reviewer.pub"
    public_key.write_bytes(private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ))
    reviewer_profile_sha256 = "8" * 64
    _write(config, {
        "config_id": "assignment-authoring-config-v1",
        "manifest_sha256": file_sha256(manifest),
        "thresholds": {"max_attempts": 3},
        "assignment_reviewer_public_key": {
            "key_id": "assignment-reviewer-test-v1",
            "path": public_key.name,
            "sha256": file_sha256(public_key),
            "reviewer_profile_sha256": reviewer_profile_sha256,
        },
        "frozen_components": {
            "capture_workload": f"workload.json@sha256:{file_sha256(workload)}",
            "routing": "grok-primary-openai-fallback.v1",
            "routing_contract": (
                f"{routing.name}@sha256:{file_sha256(routing)}"
            ),
        },
    })
    reviewer = load_enrolled_assignment_reviewer(
        json.loads(config.read_text()),
        repository_root=repository_root,
    )

    spec_path = evidence_root / "specs" / "ring.json"
    source_spec = build_ring_golden_spec(RING_GOLDEN_CASES[0])
    _write(spec_path, {
        "schema_version": SOURCE_SPEC_EVIDENCE_SCHEMA,
        "source_filename": "ring.png",
        "source_sha256": source_sha256,
        "spec": source_spec.model_dump(mode="json"),
    })
    map_path = evidence_root / "maps" / "ring.json"
    _write(map_path, _component_map(image).model_dump(mode="json"))

    calibration_path = evidence_root / "calibration" / "component-map-v1.json"
    _write(calibration_path, {
        "schema_version": COMPONENT_MAP_CALIBRATION_EVIDENCE_SCHEMA,
        "mapper_contract": "test.assignment-reviewer-map.v1",
        "calibration_run_id": "component-map-calibration-v1",
        "status": "pass",
        "tested_source_count": 144,
        "required_component_kinds": sorted({kind for _, kind in REQUIRED_COMPONENTS}),
        "unresolved_false_absence_count": 0,
    })
    mapper_contract_path = repository_root / "component-map-contract.v1.json"
    _write(mapper_contract_path, {
        "schema_version": COMPONENT_MAPPER_CONTRACT_SCHEMA,
        "mapper_contract": "test.assignment-reviewer-map.v1",
        "calibration_evidence_sha256": file_sha256(calibration_path),
        "minimum_tested_source_count": 144,
        "required_component_kinds": sorted({kind for _, kind in REQUIRED_COMPONENTS}),
        "coverage_policy": "all-required-kinds-unresolved.v1",
    })
    config_value = json.loads(config.read_text())
    config_value["frozen_components"]["assignment_component_mapper_contract"] = (
        f"{mapper_contract_path.name}@sha256:{file_sha256(mapper_contract_path)}"
    )
    mapper_private_key = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
    mapper_public_key_path = repository_root / "component-mapper.pub"
    mapper_public_key_path.write_bytes(
        mapper_private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    )
    config_value["component_mapper_public_key"] = {
        "key_id": "component-mapper-test-v1",
        "path": mapper_public_key_path.name,
        "sha256": file_sha256(mapper_public_key_path),
    }
    _write(config, config_value)

    private_key_path = tmp_path / "operator-secrets" / "assignment-reviewer.key"
    private_key_path.parent.mkdir()
    private_key_path.write_bytes(private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    private_key_path.chmod(0o600)
    return Fixture(
        repository_root=repository_root,
        evidence_root=evidence_root,
        manifest=manifest,
        config=config,
        workload=workload,
        source_path=source_path,
        spec_path=spec_path,
        map_path=map_path,
        calibration_path=calibration_path,
        mapper_contract_path=mapper_contract_path,
        attestation_path=evidence_root / "maps" / "ring.attestation.json",
        reviewer=reviewer,
        private_key=private_key,
        private_key_path=private_key_path,
        mapper_private_key=mapper_private_key,
    )


def _write_component_map_attestation(
    fixture: Fixture,
    *,
    overrides: dict[str, object] | None = None,
    signing_key: Ed25519PrivateKey | None = None,
    unsigned: bool = False,
) -> None:
    component_map = RevisionComponentMap.model_validate(
        json.loads(fixture.map_path.read_text())
    )
    attestation: dict[str, object] = {
        "schema_version": COMPONENT_MAP_ATTESTATION_SCHEMA,
        "source_sha256": file_sha256(fixture.source_path),
        "component_map_sha256": component_map_hash(component_map),
        "mapper_contract": component_map.mapper_contract,
        "calibration_evidence_sha256": file_sha256(fixture.calibration_path),
        "corpus_run_id": "assignment-corpus-run-v1",
        "run_id": "maprun_" + "b" * 64,
        "mapper_key_id": "component-mapper-test-v1",
        "signature": None,
    }
    attestation.update(overrides or {})
    if not unsigned:
        private_key = signing_key or fixture.mapper_private_key
        attestation["signature"] = {
            "algorithm": "Ed25519",
            "key_id": "component-mapper-test-v1",
            "value": base64.b64encode(
                private_key.sign(
                    canonical_component_map_attestation_payload(attestation)
                )
            ).decode("ascii"),
        }
    _write(fixture.attestation_path, attestation)


def _completed_template(fixture: Fixture, *, edit_applicability: str) -> dict:
    if edit_applicability == "not_applicable":
        _write(
            fixture.map_path,
            _component_map(
                fixture.source_path.read_bytes(),
                unresolved_kinds=frozenset({
                    "prongs",
                    "setting",
                    "shank",
                    "shoulders",
                    "gallery",
                    "metal_zone",
                }),
                calibration_evidence_sha256=file_sha256(fixture.calibration_path),
            ).model_dump(mode="json"),
        )
        _write_component_map_attestation(fixture)
    result = build_assignment_authoring_template(
        fixture.manifest,
        fixture.config,
        fixture.workload,
        corpus_run_id="assignment-corpus-run-v1",
        reviewer=fixture.reviewer,
        repository_root=fixture.repository_root,
    )
    result["review"].update({
        "reviewer_id": "rvr_" + "a" * 64,
        "review_timezone": "Asia/Shanghai",
        "reviewed_at": "2026-07-15T09:00:00+08:00",
    })
    source = result["review"]["sources"][0]
    source["source_spec_evidence_ref"] = fixture.spec_path.relative_to(
        fixture.evidence_root
    ).as_posix()
    source["component_map_evidence_ref"] = fixture.map_path.relative_to(
        fixture.evidence_root
    ).as_posix()
    source["component_map_calibration_evidence_ref"] = (
        fixture.calibration_path.relative_to(fixture.evidence_root).as_posix()
    )
    source["component_map_attestation_ref"] = (
        fixture.attestation_path.relative_to(fixture.evidence_root).as_posix()
        if edit_applicability == "not_applicable"
        else None
    )
    for evaluation in source["evaluations"]:
        is_edit = evaluation["kind"] == "edit"
        applicability = edit_applicability if is_edit else "execute"
        reason_code = (
            "source_component_absent"
            if is_edit and applicability == "not_applicable"
            else None
        )
        detail_code = (
            "component-map-all-required-kinds-absent.v1"
            if reason_code == "source_component_absent"
            else None
        )
        stem = f"{evaluation['kind']}--{evaluation['evaluation_id']}"
        review_path = fixture.evidence_root / "reviews" / f"{stem}.json"
        _write(review_path, {
            "schema_version": ASSIGNMENT_REVIEW_EVIDENCE_SCHEMA,
            "source_filename": "ring.png",
            "source_sha256": hashlib.sha256(fixture.source_path.read_bytes()).hexdigest(),
            "kind": evaluation["kind"],
            "evaluation_id": evaluation["evaluation_id"],
            "applicability": applicability,
            "not_applicable_reason_code": reason_code,
            "not_applicable_detail_code": detail_code,
            "reviewer_key_id": fixture.reviewer.key_id,
            "reviewer_profile_sha256": fixture.reviewer.reviewer_profile_sha256,
        })
        evaluation.update({
            "applicability": applicability,
            "review_evidence_ref": review_path.relative_to(
                fixture.evidence_root
            ).as_posix(),
            "not_applicable_reason_code": reason_code,
            "not_applicable_detail_code": detail_code,
        })
        if applicability == "execute":
            region_path = fixture.evidence_root / "regions" / f"{stem}.json"
            expected_region = None if not is_edit else "all metal surfaces"
            _write(region_path, {
                "schema_version": ASSIGNMENT_REGION_EVIDENCE_SCHEMA,
                "source_filename": "ring.png",
                "source_sha256": hashlib.sha256(
                    fixture.source_path.read_bytes()
                ).hexdigest(),
                "kind": evaluation["kind"],
                "evaluation_id": evaluation["evaluation_id"],
                "region_description": expected_region,
                "component_ids": (
                    [
                        "gallery",
                        "metal",
                        "prongs",
                        "setting",
                        "shank",
                        "shoulders",
                    ]
                    if is_edit
                    else []
                ),
            })
            evaluation["region_evidence_ref"] = region_path.relative_to(
                fixture.evidence_root
            ).as_posix()
    return result


def _compile(fixture: Fixture, *, edit_applicability: str = "execute") -> tuple[dict, AssignmentCompilation]:
    completed = _completed_template(
        fixture,
        edit_applicability=edit_applicability,
    )
    compilation = validate_completed_assignment_template(
        fixture.manifest,
        fixture.config,
        fixture.workload,
        completed,
        reviewer=fixture.reviewer,
        evidence_root=fixture.evidence_root,
        source_dir=Path("sources"),
        repository_root=fixture.repository_root,
    )
    return completed, compilation


def _allow_active_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(authoring, "verify_release_authority_bundle", lambda *_: {
        "status": "pass",
        "authorities": [{"role": "assignment_reviewer"}],
    })


def _rewrite_review_evidence(fixture: Fixture, response: dict) -> None:
    review_path = fixture.evidence_root / response["review_evidence_ref"]
    evidence = json.loads(review_path.read_text())
    evidence["not_applicable_reason_code"] = response[
        "not_applicable_reason_code"
    ]
    evidence["not_applicable_detail_code"] = response[
        "not_applicable_detail_code"
    ]
    _write(review_path, evidence)


def _replace_fixture_edit(fixture: Fixture, evaluation_id: str) -> None:
    manifest = json.loads(fixture.manifest.read_text())
    manifest["evaluation_slice"]["operation_ids"] = [evaluation_id]
    manifest["evaluation_slice"]["operation_classes"] = {
        "quick_appearance": [],
        "structural": [evaluation_id],
    }
    _write(fixture.manifest, manifest)

    workload = json.loads(fixture.workload.read_text())
    workload["manifest_sha256"] = file_sha256(fixture.manifest)
    edit = next(
        evaluation
        for evaluation in workload["evaluation_sets"]["ring-full-v1"]
        if evaluation["kind"] == "edit"
    )
    edit["evaluation_id"] = evaluation_id
    edit["operation_class"] = "structural"
    _write(fixture.workload, workload)

    config = json.loads(fixture.config.read_text())
    config["manifest_sha256"] = file_sha256(fixture.manifest)
    config["frozen_components"]["capture_workload"] = (
        f"workload.json@sha256:{file_sha256(fixture.workload)}"
    )
    _write(fixture.config, config)


def test_template_is_deterministic_and_locks_the_exact_frozen_scope(tmp_path: Path):
    fixture = _fixture(tmp_path)

    first = build_assignment_authoring_template(
        fixture.manifest,
        fixture.config,
        fixture.workload,
        corpus_run_id="assignment-corpus-run-v1",
        reviewer=fixture.reviewer,
        repository_root=fixture.repository_root,
    )
    second = build_assignment_authoring_template(
        fixture.manifest,
        fixture.config,
        fixture.workload,
        corpus_run_id="assignment-corpus-run-v1",
        reviewer=fixture.reviewer,
        repository_root=fixture.repository_root,
    )

    assert first == second
    assert first["bindings"]["manifest_sha256"] == file_sha256(fixture.manifest)
    assert first["bindings"]["config_sha256"] == file_sha256(fixture.config)
    assert first["bindings"]["workload_sha256"] == file_sha256(fixture.workload)
    assert first["bindings"]["sources"] == [{
        "source_filename": "ring.png",
        "source_sha256": hashlib.sha256(fixture.source_path.read_bytes()).hexdigest(),
        "evaluations": [
            {
                "kind": "edit",
                "evaluation_id": "metal-color",
                "operation_class": "quick_appearance",
            },
            {
                "kind": "render",
                "evaluation_id": "round-solitaire-yellow-4-narrow",
                "operation_class": "render_conformance",
            },
        ],
    }]


@pytest.mark.parametrize("target", ["template", "binding", "response"])
def test_completed_template_rejects_unknown_fields(tmp_path: Path, target: str):
    fixture = _fixture(tmp_path)
    completed = _completed_template(fixture, edit_applicability="execute")
    if target == "template":
        completed["operator_note"] = "not signed contract data"
    elif target == "binding":
        completed["bindings"]["operator_note"] = "not signed contract data"
    else:
        completed["review"]["sources"][0]["evaluations"][0][
            "operator_note"
        ] = "not signed contract data"

    with pytest.raises(ValueError, match="unexpected or missing fields"):
        validate_completed_assignment_template(
            fixture.manifest,
            fixture.config,
            fixture.workload,
            completed,
            reviewer=fixture.reviewer,
            evidence_root=fixture.evidence_root,
            source_dir=Path("sources"),
            repository_root=fixture.repository_root,
        )


def test_evidence_references_reject_symlink_escape(tmp_path: Path):
    fixture = _fixture(tmp_path)
    completed = _completed_template(fixture, edit_applicability="execute")
    outside = tmp_path / "outside-spec.json"
    outside.write_bytes(fixture.spec_path.read_bytes())
    link = fixture.evidence_root / "specs" / "escaped.json"
    link.symlink_to(outside)
    completed["review"]["sources"][0]["source_spec_evidence_ref"] = (
        link.relative_to(fixture.evidence_root).as_posix()
    )

    with pytest.raises(ValueError, match="escapes the evidence root"):
        validate_completed_assignment_template(
            fixture.manifest,
            fixture.config,
            fixture.workload,
            completed,
            reviewer=fixture.reviewer,
            evidence_root=fixture.evidence_root,
            source_dir=Path("sources"),
            repository_root=fixture.repository_root,
        )


def test_execute_compilation_hashes_real_raster_spec_map_and_review_evidence(
    tmp_path: Path,
):
    fixture = _fixture(tmp_path)
    _, compilation = _compile(fixture)

    assert compilation.validation["status"] == "pass"
    assert compilation.validation["provider_calls"] == 0
    assert compilation.validation["assignment_count"] == 2
    assert compilation.validation["execute_count"] == 2
    assert compilation.validation["not_applicable_count"] == 0
    assert compilation.validation["unresolved_count"] == 0
    artifacts = {
        row["path"]: row for row in compilation.validation["evidence_artifacts"]
    }
    assert artifacts["sources/ring.png"]["sha256"] == file_sha256(
        fixture.source_path
    )
    assert artifacts["specs/ring.json"]["sha256"] == file_sha256(fixture.spec_path)
    assert artifacts["maps/ring.json"]["sha256"] == file_sha256(fixture.map_path)
    for row in compilation.unsigned_bundle["assignments"]:
        binding = row["binding"]
        assert binding["source_spec_evidence_sha256"] == file_sha256(
            fixture.spec_path
        )
        assert binding["component_map_sha256"] == component_map_hash(
            RevisionComponentMap.model_validate(
                json.loads(fixture.map_path.read_text())
            )
        )
        assert binding["review_evidence_sha256"] != binding[
            "region_evidence_sha256"
        ]


def test_semantic_edit_policy_is_explicit_and_complete():
    expected = {
        "center-cut-shape": {"center_stone", "prongs", "setting"},
        "center-species-color": {"center_stone"},
        "band-width": {"shank"},
        "metal-color": {
            "prongs", "setting", "shank", "shoulders", "gallery", "metal_zone",
        },
        "metal-material": {
            "prongs", "setting", "shank", "shoulders", "gallery", "metal_zone",
        },
        "prong-setting": {"prongs", "setting"},
        "halo-add": {"center_stone", "setting", "stone_group"},
        "halo-remove": {"center_stone", "setting", "stone_group"},
        "halo-count": {"center_stone", "setting", "stone_group"},
        "leaf-motif-shape": {"shoulders", "stone_group"},
        "background-only": {"background"},
        "impossible-band-width": {"shank"},
    }

    assert {
        edit_id: set(component_kinds)
        for edit_id, component_kinds in authoring._EDIT_REQUIRED_COMPONENT_KINDS.items()
    } == expected
    assert authoring._required_component_kinds(
        "render", "round-solitaire-yellow-4-narrow"
    ) == frozenset()


@pytest.mark.parametrize("malformation", ["wrong_kind", "unresolved", "missing", "extra"])
def test_execute_region_requires_exact_resolved_semantic_component_scope(
    tmp_path: Path,
    malformation: str,
):
    fixture = _fixture(tmp_path)
    completed = _completed_template(fixture, edit_applicability="execute")
    edit_response = next(
        response
        for response in completed["review"]["sources"][0]["evaluations"]
        if response["kind"] == "edit"
    )
    region_path = fixture.evidence_root / edit_response["region_evidence_ref"]
    region = json.loads(region_path.read_text())
    if malformation == "wrong_kind":
        region["component_ids"].remove("shoulders")
        region["component_ids"].append("background")
        region["component_ids"].sort()
        expected = "required semantic scope"
    elif malformation == "unresolved":
        _write(
            fixture.map_path,
            _component_map(
                fixture.source_path.read_bytes(),
                unresolved_kinds=frozenset({"metal_zone"}),
            ).model_dump(mode="json"),
        )
        expected = "unresolved component"
    elif malformation == "missing":
        region["component_ids"].remove("gallery")
        expected = "required semantic scope"
    else:
        region["component_ids"].append("background")
        region["component_ids"].sort()
        expected = "required semantic scope"
    _write(region_path, region)

    with pytest.raises(ValueError, match=expected):
        validate_completed_assignment_template(
            fixture.manifest,
            fixture.config,
            fixture.workload,
            completed,
            reviewer=fixture.reviewer,
            evidence_root=fixture.evidence_root,
            source_dir=Path("sources"),
            repository_root=fixture.repository_root,
        )


def test_execute_region_requires_every_resolved_component_of_a_required_kind(
    tmp_path: Path,
):
    fixture = _fixture(tmp_path)
    completed = _completed_template(fixture, edit_applicability="execute")
    _write(
        fixture.map_path,
        _component_map(
            fixture.source_path.read_bytes(),
            extra_components=(("metal-secondary", "metal_zone"),),
        ).model_dump(mode="json"),
    )

    with pytest.raises(ValueError, match="required semantic scope"):
        validate_completed_assignment_template(
            fixture.manifest,
            fixture.config,
            fixture.workload,
            completed,
            reviewer=fixture.reviewer,
            evidence_root=fixture.evidence_root,
            source_dir=Path("sources"),
            repository_root=fixture.repository_root,
        )


def test_not_applicable_edit_compiles_without_provider_execution(tmp_path: Path):
    fixture = _fixture(tmp_path)
    _, compilation = _compile(fixture, edit_applicability="not_applicable")

    assert compilation.validation["provider_calls"] == 0
    assert compilation.validation["execute_count"] == 1
    assert compilation.validation["not_applicable_count"] == 1
    edit = next(
        row for row in compilation.unsigned_bundle["assignments"]
        if row["kind"] == "edit"
    )
    binding = edit["binding"]
    assert binding["applicability"] == "not_applicable"
    assert binding["not_applicable_reason"] == (
        "source_component_absent/"
        "component-map-all-required-kinds-absent.v1"
    )
    assert "source_spec" not in binding
    assert "target_spec" not in binding
    assert binding["region_evidence_sha256"] == binding[
        "review_evidence_sha256"
    ]
    assert binding["source_sha256"] == file_sha256(fixture.source_path)
    assert binding["component_map"] == json.loads(fixture.map_path.read_text())
    assert binding["component_map_attestation"] == json.loads(
        fixture.attestation_path.read_text()
    )
    assert binding["component_map_attestation_sha256"] == canonical_object_sha256(
        binding["component_map_attestation"]
    )
    attestation_artifact = next(
        row
        for row in compilation.validation["evidence_artifacts"]
        if "component_map_attestation_evidence" in row["roles"]
    )
    assert attestation_artifact["path"] == "maps/ring.attestation.json"
    assert attestation_artifact["sha256"] == file_sha256(
        fixture.attestation_path
    )


@pytest.mark.parametrize(
    ("attack", "expected"),
    [
        ("unsigned", "signature is malformed"),
        ("forged", "signature is invalid"),
        ("replayed", "corpus_run_id binding differs"),
        ("wrong_source", "source_sha256 binding differs"),
        ("wrong_map", "component_map_sha256 binding differs"),
        ("wrong_contract", "mapper_contract binding differs"),
        ("wrong_calibration", "calibration_evidence_sha256 binding differs"),
        ("nonopaque_run", "run_id must be opaque"),
    ],
)
def test_source_component_absent_requires_exact_signed_per_map_attestation(
    tmp_path: Path,
    attack: str,
    expected: str,
):
    fixture = _fixture(tmp_path)
    completed = _completed_template(fixture, edit_applicability="not_applicable")
    overrides: dict[str, object] = {}
    signing_key: Ed25519PrivateKey | None = None
    unsigned = attack == "unsigned"
    if attack == "forged":
        signing_key = Ed25519PrivateKey.generate()
    elif attack == "replayed":
        overrides["corpus_run_id"] = "assignment-corpus-run-prior"
    elif attack == "wrong_source":
        overrides["source_sha256"] = "0" * 64
    elif attack == "wrong_map":
        overrides["component_map_sha256"] = "1" * 64
    elif attack == "wrong_contract":
        overrides["mapper_contract"] = "forged.component-mapper.v1"
    elif attack == "wrong_calibration":
        overrides["calibration_evidence_sha256"] = "2" * 64
    elif attack == "nonopaque_run":
        overrides["run_id"] = "reviewer@example.com"
    _write_component_map_attestation(
        fixture,
        overrides=overrides,
        signing_key=signing_key,
        unsigned=unsigned,
    )

    with pytest.raises(ValueError, match=expected):
        validate_completed_assignment_template(
            fixture.manifest,
            fixture.config,
            fixture.workload,
            completed,
            reviewer=fixture.reviewer,
            evidence_root=fixture.evidence_root,
            source_dir=Path("sources"),
            repository_root=fixture.repository_root,
        )


@pytest.mark.parametrize("enrollment", ["missing", "reviewer_key_reuse"])
def test_source_component_absent_requires_separate_mapper_enrollment(
    tmp_path: Path,
    enrollment: str,
):
    fixture = _fixture(tmp_path)
    completed = _completed_template(fixture, edit_applicability="not_applicable")
    config = json.loads(fixture.config.read_text())
    if enrollment == "missing":
        config["component_mapper_public_key"] = None
        expected = "not completely configured"
    else:
        config["component_mapper_public_key"] = {
            "key_id": fixture.reviewer.key_id,
            "path": config["assignment_reviewer_public_key"]["path"],
            "sha256": config["assignment_reviewer_public_key"]["sha256"],
        }
        expected = "must be distinct"
    _write(fixture.config, config)
    completed["bindings"]["config_sha256"] = file_sha256(fixture.config)

    with pytest.raises(ValueError, match=expected):
        validate_completed_assignment_template(
            fixture.manifest,
            fixture.config,
            fixture.workload,
            completed,
            reviewer=fixture.reviewer,
            evidence_root=fixture.evidence_root,
            source_dir=Path("sources"),
            repository_root=fixture.repository_root,
        )


def test_source_component_absent_rejects_contradictory_resolved_coverage(
    tmp_path: Path,
):
    fixture = _fixture(tmp_path)
    completed = _completed_template(fixture, edit_applicability="not_applicable")
    _write(
        fixture.map_path,
        _component_map(fixture.source_path.read_bytes()).model_dump(mode="json"),
    )

    with pytest.raises(ValueError, match="every required component kind"):
        validate_completed_assignment_template(
            fixture.manifest,
            fixture.config,
            fixture.workload,
            completed,
            reviewer=fixture.reviewer,
            evidence_root=fixture.evidence_root,
            source_dir=Path("sources"),
            repository_root=fixture.repository_root,
        )


def test_source_component_absent_rejects_one_arbitrarily_unresolved_kind(
    tmp_path: Path,
):
    fixture = _fixture(tmp_path)
    completed = _completed_template(fixture, edit_applicability="not_applicable")
    _write(
        fixture.map_path,
        _component_map(
            fixture.source_path.read_bytes(),
            unresolved_kinds=frozenset({"metal_zone"}),
            calibration_evidence_sha256=file_sha256(fixture.calibration_path),
        ).model_dump(mode="json"),
    )

    with pytest.raises(ValueError, match="every required component kind"):
        validate_completed_assignment_template(
            fixture.manifest,
            fixture.config,
            fixture.workload,
            completed,
            reviewer=fixture.reviewer,
            evidence_root=fixture.evidence_root,
            source_dir=Path("sources"),
            repository_root=fixture.repository_root,
        )


def test_source_component_absent_rejects_forged_mapper_contract(tmp_path: Path):
    fixture = _fixture(tmp_path)
    completed = _completed_template(fixture, edit_applicability="not_applicable")
    forged = json.loads(fixture.mapper_contract_path.read_text())
    forged["minimum_tested_source_count"] = 1
    _write(fixture.mapper_contract_path, forged)

    with pytest.raises(ValueError, match="mapper contract hash differs"):
        validate_completed_assignment_template(
            fixture.manifest,
            fixture.config,
            fixture.workload,
            completed,
            reviewer=fixture.reviewer,
            evidence_root=fixture.evidence_root,
            source_dir=Path("sources"),
            repository_root=fixture.repository_root,
        )


def test_canonical_delta_inapplicable_rejects_a_valid_deterministic_edit(
    tmp_path: Path,
):
    fixture = _fixture(tmp_path)
    completed = _completed_template(fixture, edit_applicability="not_applicable")
    response = next(
        row
        for row in completed["review"]["sources"][0]["evaluations"]
        if row["kind"] == "edit"
    )
    response["not_applicable_reason_code"] = "canonical_delta_inapplicable"
    response["not_applicable_detail_code"] = "canonical-edit-apply-failed.v1"
    _rewrite_review_evidence(fixture, response)

    with pytest.raises(ValueError, match="contradicts a deterministic valid"):
        validate_completed_assignment_template(
            fixture.manifest,
            fixture.config,
            fixture.workload,
            completed,
            reviewer=fixture.reviewer,
            evidence_root=fixture.evidence_root,
            source_dir=Path("sources"),
            repository_root=fixture.repository_root,
        )


def test_canonical_delta_inapplicable_requires_and_accepts_deterministic_failure(
    tmp_path: Path,
):
    fixture = _fixture(tmp_path)
    _replace_fixture_edit(fixture, "halo-count")
    completed = _completed_template(fixture, edit_applicability="not_applicable")
    response = next(
        row
        for row in completed["review"]["sources"][0]["evaluations"]
        if row["kind"] == "edit"
    )
    response["not_applicable_reason_code"] = "canonical_delta_inapplicable"
    response["not_applicable_detail_code"] = "canonical-edit-apply-failed.v1"
    _rewrite_review_evidence(fixture, response)

    compilation = validate_completed_assignment_template(
        fixture.manifest,
        fixture.config,
        fixture.workload,
        completed,
        reviewer=fixture.reviewer,
        evidence_root=fixture.evidence_root,
        source_dir=Path("sources"),
        repository_root=fixture.repository_root,
    )

    assert compilation.validation["not_applicable_count"] == 1
    edit_binding = next(
        row["binding"]
        for row in compilation.unsigned_bundle["assignments"]
        if row["kind"] == "edit"
    )
    assert edit_binding["not_applicable_reason"].startswith(
        "canonical_delta_inapplicable/"
    )
    assert edit_binding["source_sha256"] == file_sha256(fixture.source_path)
    assert edit_binding["source_spec"] == json.loads(
        fixture.spec_path.read_text()
    )["spec"]
    assert edit_binding["canonical_edit_issues"] == [{
        "code": "halo_required",
        "message": "halo-count edit requires a halo golden case",
    }]


def test_not_applicable_edit_cannot_smuggle_an_ignored_region_evidence_ref(
    tmp_path: Path,
):
    fixture = _fixture(tmp_path)
    completed = _completed_template(fixture, edit_applicability="not_applicable")
    response = completed["review"]["sources"][0]["evaluations"][0]
    assert response["kind"] == "edit"
    response["region_evidence_ref"] = response["review_evidence_ref"]

    with pytest.raises(ValueError, match="cannot declare region evidence"):
        validate_completed_assignment_template(
            fixture.manifest,
            fixture.config,
            fixture.workload,
            completed,
            reviewer=fixture.reviewer,
            evidence_root=fixture.evidence_root,
            source_dir=Path("sources"),
            repository_root=fixture.repository_root,
        )


def test_not_applicable_free_text_field_is_rejected_and_not_retained(tmp_path: Path):
    fixture = _fixture(tmp_path)
    completed = _completed_template(fixture, edit_applicability="not_applicable")
    response = completed["review"]["sources"][0]["evaluations"][0]
    assert response["kind"] == "edit"
    response["not_applicable_rationale"] = "api_key=do-not-retain-this"

    with pytest.raises(ValueError, match="unexpected or missing fields"):
        validate_completed_assignment_template(
            fixture.manifest,
            fixture.config,
            fixture.workload,
            completed,
            reviewer=fixture.reviewer,
            evidence_root=fixture.evidence_root,
            source_dir=Path("sources"),
            repository_root=fixture.repository_root,
        )


@pytest.mark.parametrize(
    "reviewer_id",
    [
        "reviewer-opaque-v1",
        "rvr_short",
        "rvr_person@example.com",
        "RVR_assignment01",
        "rvr_MattFBaker",
        "rvr_14155551212",
        "rvr_matt_fbaker",
    ],
)
def test_reviewer_id_requires_strict_opaque_rvr_token(
    tmp_path: Path,
    reviewer_id: str,
):
    fixture = _fixture(tmp_path)
    completed = _completed_template(fixture, edit_applicability="execute")
    completed["review"]["reviewer_id"] = reviewer_id

    with pytest.raises(ValueError, match="opaque rvr_ token"):
        validate_completed_assignment_template(
            fixture.manifest,
            fixture.config,
            fixture.workload,
            completed,
            reviewer=fixture.reviewer,
            evidence_root=fixture.evidence_root,
            source_dir=Path("sources"),
            repository_root=fixture.repository_root,
        )


@pytest.mark.parametrize(
    "timezone",
    ["UTC+8", "+08:00", "Shanghai", "Asia/Not_A_Zone", " Asia/Shanghai"],
)
def test_review_timezone_requires_canonical_iana_zoneinfo(
    tmp_path: Path,
    timezone: str,
):
    fixture = _fixture(tmp_path)
    completed = _completed_template(fixture, edit_applicability="execute")
    completed["review"]["review_timezone"] = timezone

    with pytest.raises(ValueError, match="canonical IANA"):
        validate_completed_assignment_template(
            fixture.manifest,
            fixture.config,
            fixture.workload,
            completed,
            reviewer=fixture.reviewer,
            evidence_root=fixture.evidence_root,
            source_dir=Path("sources"),
            repository_root=fixture.repository_root,
        )


def test_source_raster_tamper_is_detected_before_compilation(tmp_path: Path):
    fixture = _fixture(tmp_path)
    completed = _completed_template(fixture, edit_applicability="execute")
    fixture.source_path.write_bytes(_png() + b"tamper")

    with pytest.raises(ValueError, match="source hash differs"):
        validate_completed_assignment_template(
            fixture.manifest,
            fixture.config,
            fixture.workload,
            completed,
            reviewer=fixture.reviewer,
            evidence_root=fixture.evidence_root,
            source_dir=Path("sources"),
            repository_root=fixture.repository_root,
        )


def test_finalize_reopens_evidence_and_rejects_post_compilation_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    fixture = _fixture(tmp_path)
    _, compilation = _compile(fixture)
    _allow_active_authority(monkeypatch)
    fixture.spec_path.write_text(fixture.spec_path.read_text() + "\n")

    with pytest.raises(ValueError, match="evidence.*(?:hash|drift)"):
        finalize_signed_assignment_bundle(
            compilation,
            json.loads(fixture.config.read_text()),
            reviewer=fixture.reviewer,
            private_key_path=fixture.private_key_path,
            decision_time=datetime(2026, 7, 15, tzinfo=UTC),
            repository_root=fixture.repository_root,
            evidence_root=fixture.evidence_root,
        )


@pytest.mark.parametrize(
    "mutation",
    ["unsigned_bundle", "validation", "bundle_and_validation_hash"],
)
def test_finalize_rejects_post_validation_compilation_mutation_before_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
):
    fixture = _fixture(tmp_path)
    _, compilation = _compile(fixture, edit_applicability="not_applicable")
    authority_called = False

    def authority_must_not_run(*_: object) -> dict:
        nonlocal authority_called
        authority_called = True
        return {
            "status": "pass",
            "authorities": [{"role": "assignment_reviewer"}],
        }

    monkeypatch.setattr(
        authoring,
        "verify_release_authority_bundle",
        authority_must_not_run,
    )
    if mutation in {"unsigned_bundle", "bundle_and_validation_hash"}:
        compilation.unsigned_bundle["assignments"][0]["binding"][
            "not_applicable_reason"
        ] = "source_component_absent: post-validation mutation"
    if mutation == "validation":
        compilation.validation["not_applicable_count"] = 0
    elif mutation == "bundle_and_validation_hash":
        compilation.validation["unsigned_bundle_sha256"] = (
            authoring.canonical_object_sha256(compilation.unsigned_bundle)
        )

    with pytest.raises(ValueError, match="compilation integrity"):
        finalize_signed_assignment_bundle(
            compilation,
            json.loads(fixture.config.read_text()),
            reviewer=fixture.reviewer,
            private_key_path=fixture.private_key_path,
            decision_time=datetime(2026, 7, 15, tzinfo=UTC),
            repository_root=fixture.repository_root,
            evidence_root=fixture.evidence_root,
        )

    assert authority_called is False


def test_finalize_rejects_incoherent_validation_before_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    fixture = _fixture(tmp_path)
    _, compilation = _compile(fixture)
    validation = deepcopy(compilation.validation)
    validation["unsigned_bundle_sha256"] = "0" * 64
    incoherent = AssignmentCompilation(
        unsigned_bundle=deepcopy(compilation.unsigned_bundle),
        validation=validation,
    )
    authority_called = False

    def authority_must_not_run(*_: object) -> dict:
        nonlocal authority_called
        authority_called = True
        return {
            "status": "pass",
            "authorities": [{"role": "assignment_reviewer"}],
        }

    monkeypatch.setattr(
        authoring,
        "verify_release_authority_bundle",
        authority_must_not_run,
    )

    with pytest.raises(ValueError, match="validation differs from the unsigned bundle"):
        finalize_signed_assignment_bundle(
            incoherent,
            json.loads(fixture.config.read_text()),
            reviewer=fixture.reviewer,
            private_key_path=fixture.private_key_path,
            decision_time=datetime(2026, 7, 15, tzinfo=UTC),
            repository_root=fixture.repository_root,
            evidence_root=fixture.evidence_root,
        )

    assert authority_called is False


@pytest.mark.parametrize("malformation", ["unknown_field", "duplicate", "noncanonical"])
def test_finalize_rejects_malformed_or_duplicate_evidence_artifact_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    malformation: str,
):
    fixture = _fixture(tmp_path)
    _, compilation = _compile(fixture)
    _allow_active_authority(monkeypatch)
    artifacts = compilation.validation["evidence_artifacts"]
    if malformation == "unknown_field":
        artifacts[0]["operator_note"] = "unsigned metadata"
        expected = "unexpected or missing fields"
    elif malformation == "duplicate":
        artifacts.append(dict(artifacts[0]))
        expected = "paths must be unique"
    else:
        artifacts[0]["path"] = f"sources/../{artifacts[0]['path']}"
        expected = "path is not canonical"

    with pytest.raises(ValueError, match=expected):
        finalize_signed_assignment_bundle(
            compilation,
            json.loads(fixture.config.read_text()),
            reviewer=fixture.reviewer,
            private_key_path=fixture.private_key_path,
            decision_time=datetime(2026, 7, 15, tzinfo=UTC),
            repository_root=fixture.repository_root,
            evidence_root=fixture.evidence_root,
        )


@pytest.mark.parametrize("tamper", ["missing", "symlink_escape"])
def test_finalize_fails_closed_when_compiled_evidence_is_missing_or_redirected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
):
    fixture = _fixture(tmp_path)
    _, compilation = _compile(fixture)
    _allow_active_authority(monkeypatch)
    artifact = next(
        row for row in compilation.validation["evidence_artifacts"]
        if "assignment_review_evidence" in row["roles"]
    )
    evidence_path = fixture.evidence_root / artifact["path"]
    original = evidence_path.read_bytes()
    evidence_path.unlink()
    if tamper == "symlink_escape":
        outside = tmp_path / "redirected-review-evidence.json"
        outside.write_bytes(original)
        evidence_path.symlink_to(outside)
        expected = "escapes the evidence root"
    else:
        expected = "is unavailable"

    with pytest.raises(ValueError, match=expected):
        finalize_signed_assignment_bundle(
            compilation,
            json.loads(fixture.config.read_text()),
            reviewer=fixture.reviewer,
            private_key_path=fixture.private_key_path,
            decision_time=datetime(2026, 7, 15, tzinfo=UTC),
            repository_root=fixture.repository_root,
            evidence_root=fixture.evidence_root,
        )


def test_finalize_requires_active_assignment_reviewer_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    fixture = _fixture(tmp_path)
    _, compilation = _compile(fixture)
    monkeypatch.setattr(authoring, "verify_release_authority_bundle", lambda *_: {
        "status": "fail",
        "authorities": [],
    })

    with pytest.raises(ValueError, match="active assignment reviewer"):
        finalize_signed_assignment_bundle(
            compilation,
            json.loads(fixture.config.read_text()),
            reviewer=fixture.reviewer,
            private_key_path=fixture.private_key_path,
            decision_time=datetime(2026, 7, 15, tzinfo=UTC),
            repository_root=fixture.repository_root,
            evidence_root=fixture.evidence_root,
        )


@pytest.mark.parametrize("key_case", ["inside_root", "unsafe_mode", "wrong_key"])
def test_finalize_rejects_untrusted_or_wrong_private_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    key_case: str,
):
    fixture = _fixture(tmp_path)
    _, compilation = _compile(fixture)
    _allow_active_authority(monkeypatch)
    key_path = fixture.private_key_path
    expected = ""
    if key_case == "inside_root":
        key_path = fixture.evidence_root / "leaked-private.key"
        key_path.write_bytes(fixture.private_key_path.read_bytes())
        key_path.chmod(0o600)
        expected = "outside the repository"
    elif key_case == "unsafe_mode":
        key_path.chmod(0o644)
        expected = "group- or world-accessible"
    else:
        key_path.write_bytes(Ed25519PrivateKey.generate().private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        ))
        expected = "differs from enrollment"

    with pytest.raises(ValueError, match=expected):
        finalize_signed_assignment_bundle(
            compilation,
            json.loads(fixture.config.read_text()),
            reviewer=fixture.reviewer,
            private_key_path=key_path,
            decision_time=datetime(2026, 7, 15, tzinfo=UTC),
            repository_root=fixture.repository_root,
            evidence_root=fixture.evidence_root,
        )


def test_finalize_signs_and_self_verifies_the_exact_compiled_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    fixture = _fixture(tmp_path)
    _, compilation = _compile(fixture, edit_applicability="not_applicable")
    _allow_active_authority(monkeypatch)
    config = json.loads(fixture.config.read_text())

    bundle, validation, pin = finalize_signed_assignment_bundle(
        compilation,
        config,
        reviewer=fixture.reviewer,
        private_key_path=fixture.private_key_path,
        decision_time=datetime(2026, 7, 15, tzinfo=UTC),
        repository_root=fixture.repository_root,
        evidence_root=fixture.evidence_root,
    )

    verified = verify_signed_assignment_bundle(
        bundle,
        config,
        repository_root=fixture.repository_root,
    )
    assert verified.key_id == fixture.reviewer.key_id
    assert validation["signature_status"] == "verified"
    assert pin["bundle_canonical_sha256"] == validation["signed_bundle_sha256"]
    assert pin["reviewed_template_sha256"] == bundle[
        "reviewed_template_sha256"
    ]
    assert pin["release_authority_decision"] == bundle[
        "release_authority_decision"
    ]
    assert validation["release_authority_decision"] == bundle[
        "release_authority_decision"
    ]
    assert pin["installation_status"] == "review_required"


def _load_cli_module():
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts/author_frozen_assignment_bundle.py"
    )
    module_spec = util.spec_from_file_location("author_frozen_assignment_bundle", script)
    assert module_spec is not None and module_spec.loader is not None
    module = util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def test_cli_template_output_is_fresh_atomic_and_never_clobbered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    fixture = _fixture(tmp_path)
    cli = _load_cli_module()
    monkeypatch.setattr(cli, "ROOT", fixture.repository_root)
    output = fixture.evidence_root / "authoring" / "template.json"
    output.parent.mkdir()
    argv = [
        "author_frozen_assignment_bundle.py",
        "template",
        "--evidence-root", str(fixture.evidence_root),
        "--manifest", str(fixture.manifest),
        "--config", str(fixture.config),
        "--workload", str(fixture.workload),
        "--corpus-run-id", "assignment-corpus-run-v1",
        "--out", "authoring/template.json",
    ]
    monkeypatch.setattr(sys, "argv", argv)

    assert cli.main() == 0
    before = output.read_bytes()
    before_inode = os.stat(output).st_ino
    with pytest.raises(ValueError, match="already exists"):
        cli.main()
    assert output.read_bytes() == before
    assert os.stat(output).st_ino == before_inode
    assert not list(output.parent.glob(".*.staging-*"))


def test_cli_submit_canonicalizes_one_hash_verified_external_workbook(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    fixture = _fixture(tmp_path)
    completed = _completed_template(fixture, edit_applicability="execute")
    working_path = tmp_path / "reviewer-working" / "completed.json"
    working_path.parent.mkdir()
    # Deliberately non-canonical formatting proves the retained copy is parsed
    # and rendered, rather than blindly copied from the working location.
    working_path.write_text(json.dumps(completed), encoding="utf-8")
    expected_sha256 = hashlib.sha256(working_path.read_bytes()).hexdigest()
    retained_path = fixture.evidence_root / "authoring" / "completed.json"
    retained_path.parent.mkdir()
    cli = _load_cli_module()
    monkeypatch.setattr(cli, "ROOT", fixture.repository_root)
    argv = [
        "author_frozen_assignment_bundle.py",
        "submit",
        "--evidence-root", str(fixture.evidence_root),
        "--manifest", str(fixture.manifest),
        "--config", str(fixture.config),
        "--workload", str(fixture.workload),
        "--completed-input", str(working_path),
        "--expected-sha256", expected_sha256,
        "--out", "authoring/completed.json",
    ]
    monkeypatch.setattr(sys, "argv", argv)

    assert cli.main() == 0
    assert json.loads(retained_path.read_text()) == completed
    assert retained_path.read_bytes() == (
        json.dumps(completed, indent=2, sort_keys=True) + "\n"
    ).encode()
    assert hashlib.sha256(working_path.read_bytes()).hexdigest() == expected_sha256
    before = retained_path.read_bytes(), os.stat(retained_path).st_ino
    with pytest.raises(ValueError, match="already exists"):
        cli.main()
    assert (retained_path.read_bytes(), os.stat(retained_path).st_ino) == before


@pytest.mark.parametrize("failure", ["hash", "input-confinement", "output-confinement"])
def test_cli_submit_fails_closed_before_persisting_untrusted_or_escaped_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
):
    fixture = _fixture(tmp_path)
    completed = _completed_template(fixture, edit_applicability="execute")
    working_path = tmp_path / "working-completed.json"
    _write(working_path, completed)
    output = "authoring/completed.json"
    expected_sha256 = hashlib.sha256(working_path.read_bytes()).hexdigest()
    if failure == "hash":
        expected_sha256 = "0" * 64
    elif failure == "input-confinement":
        working_path = fixture.evidence_root / "working-completed.json"
        _write(working_path, completed)
        expected_sha256 = hashlib.sha256(working_path.read_bytes()).hexdigest()
    else:
        output = "../escaped-completed.json"
    (fixture.evidence_root / "authoring").mkdir()
    cli = _load_cli_module()
    monkeypatch.setattr(cli, "ROOT", fixture.repository_root)
    monkeypatch.setattr(sys, "argv", [
        "author_frozen_assignment_bundle.py",
        "submit",
        "--evidence-root", str(fixture.evidence_root),
        "--manifest", str(fixture.manifest),
        "--config", str(fixture.config),
        "--workload", str(fixture.workload),
        "--completed-input", str(working_path),
        "--expected-sha256", expected_sha256,
        "--out", output,
    ])

    expected = {
        "hash": "SHA-256 differs",
        "input-confinement": "outside the retained evidence root",
        "output-confinement": "escapes the evidence root",
    }[failure]
    with pytest.raises(ValueError, match=expected):
        cli.main()
    assert not (fixture.evidence_root / "authoring" / "completed.json").exists()


def test_cli_finalize_writes_one_fresh_atomic_batch_and_never_clobbers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    fixture = _fixture(tmp_path)
    completed = _completed_template(fixture, edit_applicability="not_applicable")
    completed_path = fixture.evidence_root / "authoring" / "completed.json"
    _write(completed_path, completed)
    output_dir = fixture.evidence_root / "final"
    output_dir.mkdir()
    cli = _load_cli_module()
    monkeypatch.setattr(cli, "ROOT", fixture.repository_root)
    _allow_active_authority(monkeypatch)
    argv = [
        "author_frozen_assignment_bundle.py",
        "finalize",
        "--evidence-root", str(fixture.evidence_root),
        "--manifest", str(fixture.manifest),
        "--config", str(fixture.config),
        "--workload", str(fixture.workload),
        "--source-dir", "sources",
        "--template", "authoring/completed.json",
        "--private-key", str(fixture.private_key_path),
        "--decision-time", "2026-07-15T01:00:00Z",
        "--bundle-out", "final/bundle.json",
        "--validation-out", "final/validation.json",
        "--pin-out", "final/pin.json",
    ]
    monkeypatch.setattr(sys, "argv", argv)

    assert cli.main() == 0
    outputs = [
        output_dir / "bundle.json",
        output_dir / "validation.json",
        output_dir / "pin.json",
    ]
    before = {path: (path.read_bytes(), os.stat(path).st_ino) for path in outputs}
    pin = json.loads(outputs[2].read_text())
    assert pin["source_artifact"] == "final/bundle.json"
    assert pin["source_file_sha256"] == hashlib.sha256(
        outputs[0].read_bytes()
    ).hexdigest()
    assert "resolved_assignment_bundle_pin" not in pin
    assert pin["reviewed_template_artifact"] == "authoring/completed.json"
    assert pin["reviewed_template_file_sha256"] == hashlib.sha256(
        completed_path.read_bytes()
    ).hexdigest()
    with pytest.raises(ValueError, match="already exists"):
        cli.main()
    assert {
        path: (path.read_bytes(), os.stat(path).st_ino) for path in outputs
    } == before
    assert not list(output_dir.glob(".*.staging-*"))


def test_cli_install_verifies_and_atomically_copies_to_an_installable_repo_pin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    fixture = _fixture(tmp_path)
    _, compilation = _compile(fixture, edit_applicability="not_applicable")
    _allow_active_authority(monkeypatch)
    bundle, _validation, _pin = finalize_signed_assignment_bundle(
        compilation,
        json.loads(fixture.config.read_text()),
        reviewer=fixture.reviewer,
        private_key_path=fixture.private_key_path,
        decision_time=datetime(2026, 7, 15, tzinfo=UTC),
        repository_root=fixture.repository_root,
        evidence_root=fixture.evidence_root,
    )
    retained_bundle = fixture.evidence_root / "final" / "bundle.json"
    _write(retained_bundle, bundle)
    source_sha256 = hashlib.sha256(retained_bundle.read_bytes()).hexdigest()
    install_dir = fixture.repository_root / "assignment-bundles"
    install_dir.mkdir()
    installed = install_dir / "assignment-corpus-run-v1.json"
    cli = _load_cli_module()
    monkeypatch.setattr(cli, "ROOT", fixture.repository_root)
    monkeypatch.setattr(sys, "argv", [
        "author_frozen_assignment_bundle.py",
        "install",
        "--evidence-root", str(fixture.evidence_root),
        "--manifest", str(fixture.manifest),
        "--config", str(fixture.config),
        "--workload", str(fixture.workload),
        "--bundle", "final/bundle.json",
        "--expected-sha256", source_sha256,
        "--out", "assignment-bundles/assignment-corpus-run-v1.json",
    ])

    assert cli.main() == 0
    assert installed.read_bytes() == retained_bundle.read_bytes()
    assert (
        "assignment-bundles/assignment-corpus-run-v1.json@sha256:"
        + source_sha256
    ) == (
        installed.relative_to(fixture.repository_root).as_posix()
        + "@sha256:"
        + hashlib.sha256(installed.read_bytes()).hexdigest()
    )
    before = installed.read_bytes(), os.stat(installed).st_ino
    with pytest.raises(ValueError, match="already exists"):
        cli.main()
    assert (installed.read_bytes(), os.stat(installed).st_ino) == before


@pytest.mark.parametrize("failure", ["hash", "source-confinement", "output-confinement"])
def test_cli_install_rejects_unverified_or_noncanonical_locations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
):
    fixture = _fixture(tmp_path)
    (fixture.repository_root / "assignment-bundles").mkdir()
    retained_bundle = fixture.evidence_root / "final" / "bundle.json"
    _write(retained_bundle, {"schema_version": "not-a-signed-bundle"})
    expected_sha256 = hashlib.sha256(retained_bundle.read_bytes()).hexdigest()
    bundle_arg = "final/bundle.json"
    output = "assignment-bundles/bundle.json"
    if failure == "hash":
        expected_sha256 = "0" * 64
    elif failure == "source-confinement":
        outside = tmp_path / "outside-bundle.json"
        outside.write_bytes(retained_bundle.read_bytes())
        bundle_arg = str(outside)
    else:
        output = "bundle.json"
    cli = _load_cli_module()
    monkeypatch.setattr(cli, "ROOT", fixture.repository_root)
    monkeypatch.setattr(sys, "argv", [
        "author_frozen_assignment_bundle.py",
        "install",
        "--evidence-root", str(fixture.evidence_root),
        "--manifest", str(fixture.manifest),
        "--config", str(fixture.config),
        "--workload", str(fixture.workload),
        "--bundle", bundle_arg,
        "--expected-sha256", expected_sha256,
        "--out", output,
    ])

    expected = {
        "hash": "SHA-256 differs",
        "source-confinement": "must be evidence-root-relative",
        "output-confinement": "config-adjacent assignment-bundles",
    }[failure]
    with pytest.raises(ValueError, match=expected):
        cli.main()
    assert not (fixture.repository_root / "assignment-bundles" / "bundle.json").exists()

from __future__ import annotations

import base64
import copy

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import facetta.api.specs as specs_module
from facetta.image_identity import spec_visual_hash
from facetta.main import app
from facetta.source_component_resolution import (
    SourceComponentResolution,
    SourceCoverageResolutionInvalid,
    resolve_source_component_coverage,
    valid_source_component_spec_paths,
)
from facetta.source_component_coverage import (
    IndependentComponentAudit,
    SourceComponentCoverage,
    SourceVisibleComponent,
)
from facetta.spec import Spec


def _audit(verdict: str = "pass") -> IndependentComponentAudit:
    return IndependentComponentAudit(
        kind="independent_component_audit",
        verdict=verdict,
        auditor="skeptical-source-component-audit.v1",
        source_view="three_quarter",
        observed_description="The component mapping agrees with the source.",
        evidence_sha256="a" * 64,
    )


def _coverage() -> SourceComponentCoverage:
    return SourceComponentCoverage(
        source_kind="imported_reference",
        components=(
            SourceVisibleComponent(
                component_id="stone.center",
                source_view="three_quarter",
                source_description="Oval blue center stone.",
                source_confidence=0.94,
                canonical_spec_paths=("stone",),
                independent_audit=_audit(),
            ),
            SourceVisibleComponent(
                component_id="assembly.shoulder",
                source_view="three_quarter",
                source_description="Sculpted mirrored shoulder architecture.",
                source_confidence=0.83,
                unresolved_reason="No supported structured form captures it.",
                independent_audit=_audit("fail"),
            ),
        ),
    )


def _stale_side_group_coverage() -> SourceComponentCoverage:
    return SourceComponentCoverage(
        source_kind="imported_reference",
        components=(SourceVisibleComponent(
            component_id="stone.group.002",
            source_view="three_quarter",
            source_description="Second shoulder group retained from an older draft.",
            source_confidence=0.88,
            canonical_spec_paths=("side_stones[1]",),
            independent_audit=_audit(),
        ),),
    )


def _spec(example_spec: dict, *, coverage: SourceComponentCoverage | None = None) -> Spec:
    raw = copy.deepcopy(example_spec)
    if coverage is not None:
        raw["source_component_coverage"] = coverage.model_dump(mode="json")
    spec = Spec.model_validate(raw)
    if coverage is None or coverage.audited_spec_visual_hash is not None:
        return spec
    return spec.model_copy(update={
        "source_component_coverage": coverage.model_copy(update={
            "audited_spec_visual_hash": spec_visual_hash(spec),
        }),
    })


def test_valid_paths_are_real_present_spec_fields_not_freeform_claims(example_spec):
    spec = _spec(example_spec, coverage=_coverage())

    paths = valid_source_component_spec_paths(spec)

    assert "jewelry_type" in paths
    assert "stone" in paths
    assert "stone.species" in paths
    assert "stone.dimensions_mm.length" in paths
    assert "setting.prong_count" in paths
    assert "band.width_mm" in paths
    assert "chain" not in paths
    assert "chain.style" not in paths
    assert "stone.fake_path" not in paths
    assert "notes_to_factory" not in paths
    assert "dimension_provenance" not in paths
    assert not any("cad" in path for path in paths)


def test_existing_audited_mapping_becomes_blocked_when_its_spec_path_is_removed(
    example_spec,
):
    coverage = _stale_side_group_coverage()
    spec = _spec(example_spec, coverage=coverage)

    result = resolve_source_component_coverage(
        coverage,
        (),
        valid_spec_paths=valid_source_component_spec_paths(spec),
    )

    assert result.factory_ready is False
    assert [(blocker.component_id, blocker.code) for blocker in result.blockers] == [
        ("stone.group.002", "source_component_path_missing"),
    ]
    assert result.coverage == coverage


def test_batch_maps_existing_component_and_invalidates_only_its_old_audit(
    example_spec,
):
    spec = _spec(example_spec, coverage=_coverage())
    original = spec.source_component_coverage
    assert original is not None

    result = resolve_source_component_coverage(
        original,
        (SourceComponentResolution(
            component_id="assembly.shoulder",
            canonical_spec_paths=("band", "setting"),
        ),),
        valid_spec_paths=valid_source_component_spec_paths(spec),
    )

    assert result.coverage is not None
    assert tuple(item.component_id for item in result.coverage.components) == (
        "stone.center",
        "assembly.shoulder",
    )
    assert result.coverage.components[0] == original.components[0]
    changed = result.coverage.components[1]
    assert changed.source_description == original.components[1].source_description
    assert changed.source_view == original.components[1].source_view
    assert changed.source_confidence == original.components[1].source_confidence
    assert changed.canonical_spec_paths == ("band", "setting")
    assert changed.unresolved_reason is None
    assert changed.independent_audit is None
    assert result.changed_component_ids == ("assembly.shoulder",)
    assert result.invalidated_audit_component_ids == ("assembly.shoulder",)
    assert result.factory_ready is False
    assert {
        blocker.code for blocker in result.blockers
    } == {"source_component_not_independently_audited"}
    # Inputs remain exact immutable values after the failed-readiness draft.
    assert original.components[1].unresolved_reason is not None
    assert original.components[1].independent_audit is not None


def test_designer_can_explicitly_keep_component_unresolved_with_new_reason(
    example_spec,
):
    spec = _spec(example_spec, coverage=_coverage())
    coverage = spec.source_component_coverage
    assert coverage is not None

    result = resolve_source_component_coverage(
        coverage,
        (SourceComponentResolution(
            component_id="assembly.shoulder",
            unresolved_reason=(
                "Designer must supply a supported form definition before release."
            ),
        ),),
        valid_spec_paths=valid_source_component_spec_paths(spec),
    )

    assert result.coverage is not None
    changed = result.coverage.components[1]
    assert changed.canonical_spec_paths == ()
    assert changed.unresolved_reason == (
        "Designer must supply a supported form definition before release."
    )
    assert changed.independent_audit is None
    codes = {blocker.code for blocker in result.blockers}
    assert codes == {
        "source_component_unresolved",
        "source_component_not_independently_audited",
    }


def test_semantically_identical_mapping_order_is_noop_and_preserves_audit(
    example_spec,
):
    coverage = _coverage()
    shoulder_raw = coverage.components[1].model_dump(mode="python")
    shoulder_raw.update({
        "canonical_spec_paths": ("band", "setting"),
        "unresolved_reason": None,
        "independent_audit": _audit().model_dump(mode="python"),
    })
    coverage = SourceComponentCoverage(
        source_kind=coverage.source_kind,
        components=(
            coverage.components[0],
            SourceVisibleComponent.model_validate(shoulder_raw),
        ),
    )
    spec = _spec(example_spec, coverage=coverage)

    result = resolve_source_component_coverage(
        coverage,
        (SourceComponentResolution(
            component_id="assembly.shoulder",
            canonical_spec_paths=("setting", "band"),
        ),),
        valid_spec_paths=valid_source_component_spec_paths(spec),
    )

    assert result.changed_component_ids == ()
    assert result.invalidated_audit_component_ids == ()
    assert result.coverage is not None
    assert result.coverage.components[1] == coverage.components[1]
    assert result.factory_ready is True


@pytest.mark.parametrize(
    "resolutions, message",
    [
        (
            (
                SourceComponentResolution(
                    component_id="invented.component",
                    canonical_spec_paths=("stone",),
                ),
            ),
            "unknown stable source component",
        ),
        (
            (
                SourceComponentResolution(
                    component_id="stone.center",
                    canonical_spec_paths=("stone",),
                ),
                SourceComponentResolution(
                    component_id="stone.center",
                    unresolved_reason="Duplicate command must fail atomically.",
                ),
            ),
            "IDs must be unique",
        ),
        (
            (
                SourceComponentResolution(
                    component_id="stone.center",
                    canonical_spec_paths=("stone.fake_path",),
                ),
            ),
            "paths absent from this draft",
        ),
        (
            (
                SourceComponentResolution(
                    component_id="stone.center",
                    canonical_spec_paths=("chain.style",),
                ),
            ),
            "paths absent from this draft",
        ),
    ],
)
def test_batch_rejects_invented_duplicate_or_absent_targets_atomically(
    example_spec,
    resolutions,
    message,
):
    coverage = _coverage()
    before = coverage.model_dump(mode="json")
    spec = _spec(example_spec, coverage=coverage)

    with pytest.raises(SourceCoverageResolutionInvalid, match=message):
        resolve_source_component_coverage(
            coverage,
            resolutions,
            valid_spec_paths=valid_source_component_spec_paths(spec),
        )

    assert coverage.model_dump(mode="json") == before


@pytest.mark.parametrize(
    "payload",
    [
        {"component_id": "stone.center"},
        {
            "component_id": "stone.center",
            "canonical_spec_paths": ["stone"],
            "unresolved_reason": "Cannot map and remain unresolved.",
        },
        {
            "component_id": "stone.center",
            "canonical_spec_paths": ["stone", "stone"],
        },
        {
            "component_id": "stone.center",
            "canonical_spec_paths": ["cad.profile"],
        },
        {
            "component_id": "stone.center",
            "unresolved_reason": "Keep unresolved.",
            "delete": True,
        },
    ],
)
def test_resolution_contract_rejects_ambiguous_duplicate_cad_or_delete(payload):
    with pytest.raises(ValidationError):
        SourceComponentResolution.model_validate(payload)


def test_legacy_missing_coverage_remains_readable_but_cannot_be_backfilled(
    example_spec,
):
    spec = _spec(example_spec)
    paths = valid_source_component_spec_paths(spec)

    no_op = resolve_source_component_coverage(
        None,
        (),
        valid_spec_paths=paths,
    )
    assert no_op.coverage is None
    assert no_op.legacy_provenance is True
    assert no_op.factory_ready is True
    assert no_op.blockers == ()

    with pytest.raises(SourceCoverageResolutionInvalid, match="cannot invent"):
        resolve_source_component_coverage(
            None,
            (SourceComponentResolution(
                component_id="stone.center",
                canonical_spec_paths=("stone",),
            ),),
            valid_spec_paths=paths,
        )


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_draft_api_applies_batch_without_persistence_and_returns_readiness(
    client,
    example_spec,
):
    spec = _spec(example_spec, coverage=_coverage())

    response = client.post("/specs/source-coverage/resolve", json={
        "spec": spec.model_dump(mode="json"),
        "resolutions": [{
            "component_id": "assembly.shoulder",
            "canonical_spec_paths": ["band", "setting"],
        }],
        "created_by": "usr_designer",
        "run_independent_audit": False,
    })

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source_kind"] == "imported_reference"
    assert [item["component_id"] for item in body["components"]] == [
        "stone.center",
        "assembly.shoulder",
    ]
    assert body["changed_component_ids"] == ["assembly.shoulder"]
    assert body["invalidated_audit_component_ids"] == ["assembly.shoulder"]
    assert body["resolved_by"] == "usr_designer"
    assert body["audit"] == {
        "requested": False,
        "status": "not_requested",
        "audited_component_ids": [],
        "blocker_count": 2,
    }
    assert body["factory_ready"] is False
    assert [item["code"] for item in body["blockers"]] == [
        "source_component_spec_audit_missing",
        "source_component_not_independently_audited",
    ]
    assert all(item["message"] for item in body["blockers"])
    assert "stone.fake_path" not in body["valid_spec_paths"]
    assert body["spec"]["version"] == spec.version
    assert body["spec"]["source_component_coverage"] == {
        "source_kind": body["source_kind"],
        "components": body["components"],
        "audited_spec_visual_hash": None,
        "audited_source_sha256": None,
    }


def test_draft_api_can_explicitly_rerun_independent_audit(
    client,
    monkeypatch,
    example_spec,
):
    spec = _spec(example_spec, coverage=_coverage())

    def successful_audit(
        _image: bytes,
        coverage: SourceComponentCoverage,
        *,
        spec: Spec,
    ):
        components = tuple(
            SourceVisibleComponent.model_validate({
                **component.model_dump(mode="python"),
                "independent_audit": _audit().model_dump(mode="python"),
            })
            for component in coverage.components
        )
        return SourceComponentCoverage(
            source_kind=coverage.source_kind,
            components=components,
            audited_spec_visual_hash=spec_visual_hash(spec),
        )

    monkeypatch.setattr(
        specs_module,
        "audit_source_component_coverage",
        successful_audit,
    )
    response = client.post("/specs/source-coverage/resolve", json={
        "spec": spec.model_dump(mode="json"),
        "source_image_base64": base64.b64encode(b"reference").decode(),
        "resolutions": [{
            "component_id": "assembly.shoulder",
            "canonical_spec_paths": ["band", "setting"],
        }],
        "created_by": "usr_designer",
        "run_independent_audit": True,
    })

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["audit"] == {
        "requested": True,
        "status": "pass",
        "audited_component_ids": ["stone.center", "assembly.shoulder"],
        "blocker_count": 0,
    }
    assert body["factory_ready"] is True
    assert body["blockers"] == []


def test_draft_api_retries_one_structurally_invalid_audit_contract(
    client,
    monkeypatch,
    example_spec,
):
    from facetta.source_component_audit import SourceComponentAuditInvalid

    spec = _spec(example_spec, coverage=_coverage())
    calls = 0

    def eventually_valid_audit(
        _image: bytes,
        coverage: SourceComponentCoverage,
        *,
        spec: Spec,
    ) -> SourceComponentCoverage:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise SourceComponentAuditInvalid(
                "mapping response does not match the audit contract"
            )
        return SourceComponentCoverage(
            source_kind=coverage.source_kind,
            components=tuple(component.model_copy(update={
                "unresolved_reason": None,
                "independent_audit": _audit(),
            }) for component in coverage.components),
            audited_spec_visual_hash=spec_visual_hash(spec),
        )

    monkeypatch.setattr(
        specs_module,
        "audit_source_component_coverage",
        eventually_valid_audit,
    )
    response = client.post("/specs/source-coverage/resolve", json={
        "spec": spec.model_dump(mode="json"),
        "source_image_base64": base64.b64encode(b"reference").decode(),
        "resolutions": [{
            "component_id": "assembly.shoulder",
            "canonical_spec_paths": ["band", "setting"],
        }],
        "created_by": "usr_designer",
        "run_independent_audit": True,
    })

    assert response.status_code == 200, response.text
    assert calls == 2
    assert response.json()["audit"]["status"] == "pass"
    assert response.json()["factory_ready"] is True


def test_draft_api_refuses_to_reaudit_mapping_to_removed_spec_path(
    client,
    monkeypatch,
    example_spec,
):
    spec = _spec(example_spec, coverage=_stale_side_group_coverage())
    provider_called = False

    def must_not_audit(_image: bytes, _coverage: SourceComponentCoverage):
        nonlocal provider_called
        provider_called = True
        raise AssertionError("stale paths must be corrected before vision audit")

    monkeypatch.setattr(
        specs_module,
        "audit_source_component_coverage",
        must_not_audit,
    )
    response = client.post("/specs/source-coverage/resolve", json={
        "spec": spec.model_dump(mode="json"),
        "source_image_base64": base64.b64encode(b"reference").decode(),
        "resolutions": [],
        "run_independent_audit": True,
    })

    assert response.status_code == 200, response.text
    body = response.json()
    assert provider_called is False
    assert body["audit"] == {
        "requested": True,
        "status": "invalid",
        "audited_component_ids": [],
        "blocker_count": 1,
    }
    assert body["factory_ready"] is False
    assert body["blockers"][0]["code"] == "source_component_path_missing"
    assert "side_stones[1]" in body["blockers"][0]["message"]


def test_draft_api_keeps_changed_draft_blocked_when_audit_is_unavailable(
    client,
    monkeypatch,
    example_spec,
):
    spec = _spec(example_spec, coverage=_coverage())

    def unavailable(_image, _coverage, *, spec):
        from facetta.source_component_audit import SourceComponentAuditUnavailable

        raise SourceComponentAuditUnavailable("provider unavailable")

    monkeypatch.setattr(
        specs_module,
        "audit_source_component_coverage",
        unavailable,
    )
    response = client.post("/specs/source-coverage/resolve", json={
        "spec": spec.model_dump(mode="json"),
        "source_image_base64": base64.b64encode(b"reference").decode(),
        "resolutions": [{
            "component_id": "assembly.shoulder",
            "canonical_spec_paths": ["band", "setting"],
        }],
        "run_independent_audit": True,
    })

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["audit"]["status"] == "unavailable"
    assert body["audit"]["blocker_count"] == 2
    assert body["factory_ready"] is False
    assert body["components"][1]["independent_audit"] is None


@pytest.mark.parametrize(
    "payload, detail",
    [
        (
            {"run_independent_audit": True},
            "source_image_base64 is required",
        ),
        (
            {
                "run_independent_audit": True,
                "source_image_base64": "not-base64!",
            },
            "not valid base64",
        ),
        (
            {
                "resolutions": [{
                    "component_id": "new.invented.component",
                    "canonical_spec_paths": ["stone"],
                }],
            },
            "unknown stable source component",
        ),
    ],
)
def test_draft_api_rejects_missing_source_invalid_base64_and_invented_ids(
    client,
    example_spec,
    payload,
    detail,
):
    spec = _spec(example_spec, coverage=_coverage())
    response = client.post("/specs/source-coverage/resolve", json={
        "spec": spec.model_dump(mode="json"),
        **payload,
    })

    assert response.status_code == 422
    assert detail in response.json()["detail"]


def test_draft_api_preserves_legacy_spec_without_guessing_components(
    client,
    example_spec,
):
    spec = _spec(example_spec)

    response = client.post("/specs/source-coverage/resolve", json={
        "spec": spec.model_dump(mode="json"),
        "resolutions": [],
        "run_independent_audit": False,
    })

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["spec"]["source_component_coverage"] is None
    assert body["source_kind"] is None
    assert body["components"] == []
    assert body["legacy_provenance"] is True
    assert body["factory_ready"] is True
    assert body["audit"]["status"] == "legacy_provenance"

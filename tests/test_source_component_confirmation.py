"""Human confirmation resolves uncertainty without overriding audit failures."""

from __future__ import annotations

import base64
import hashlib
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from conftest import HALO_SPEC
from facetta.image_identity import spec_visual_hash
from facetta.main import app
from facetta.source_component_confirmation import (
    SourceComponentConfirmationInput,
    SourceComponentConfirmationInvalid,
    confirm_source_components,
)
from facetta.source_component_coverage import (
    IndependentComponentAudit,
    SourceComponentCoverage,
    source_component_factory_blockers,
)
from facetta.source_component_resolution import valid_source_component_spec_paths
from facetta.source_component_seed import seed_imported_reference_coverage
from facetta.spec import Spec


def _png(color=(200, 180, 160)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (96, 96), color).save(out, format="PNG")
    return out.getvalue()


def _spec_with_audit(verdict: str = "inconclusive") -> Spec:
    spec = Spec.model_validate(HALO_SPEC)
    seeded = seed_imported_reference_coverage(spec)
    components = tuple(component.model_copy(update={
        "independent_audit": IndependentComponentAudit(
            kind="independent_component_audit",
            verdict=verdict,
            auditor="independent-test-audit.v1",
            source_view="three_quarter",
            observed_description="visible fact requires human confirmation",
            evidence_sha256=hashlib.sha256(_png()).hexdigest(),
        ),
    }) for component in seeded.components)
    coverage = SourceComponentCoverage(
        source_kind="imported_reference",
        components=components,
        audited_spec_visual_hash=spec_visual_hash(spec),
    )
    return spec.model_copy(update={"source_component_coverage": coverage})


def _confirmations(spec: Spec) -> tuple[SourceComponentConfirmationInput, ...]:
    return tuple(SourceComponentConfirmationInput(
        component_id=component.component_id,
        basis=("designer_defined_target" if component.component_id == "band.shank"
               else "visible_source"),
        confirmed_description=(
            "Designer defines the half-round shank target."
            if component.component_id == "band.shank"
            else f"Designer confirms {component.source_description}."
        ),
    ) for component in spec.source_component_coverage.components)


def test_confirmation_clears_only_exact_inconclusive_component_blockers():
    source = _png()
    spec = _spec_with_audit()
    confirmed = confirm_source_components(
        spec,
        source,
        _confirmations(spec),
        reviewer="usr_designer",
    )
    blockers = source_component_factory_blockers(
        confirmed.source_component_coverage,
        valid_spec_paths=valid_source_component_spec_paths(confirmed),
        current_spec_visual_hash=spec_visual_hash(confirmed),
        current_source_hash=hashlib.sha256(source).hexdigest(),
    )
    assert blockers == ()
    band = next(component for component in confirmed.source_component_coverage.components
                if component.component_id == "band.shank")
    assert band.independent_audit.verdict == "inconclusive"
    assert band.designer_confirmation.basis == "designer_defined_target"
    assert band.designer_confirmation.reviewer == "usr_designer"


def test_confirmation_cannot_override_failed_or_missing_audit():
    source = _png()
    failed = _spec_with_audit("fail")
    with pytest.raises(SourceComponentConfirmationInvalid, match="audit is fail"):
        confirm_source_components(
            failed, source, _confirmations(failed), reviewer="usr_designer")

    missing = _spec_with_audit()
    first = missing.source_component_coverage.components[0]
    coverage = missing.source_component_coverage.model_copy(update={
        "components": (
            first.model_copy(update={"independent_audit": None}),
            *missing.source_component_coverage.components[1:],
        ),
    })
    missing = missing.model_copy(update={"source_component_coverage": coverage})
    with pytest.raises(SourceComponentConfirmationInvalid, match="audit is missing"):
        confirm_source_components(
            missing, source, _confirmations(missing), reviewer="usr_designer")


def test_confirmation_is_stale_for_different_source_bytes():
    source = _png()
    spec = _spec_with_audit()
    confirmed = confirm_source_components(
        spec, source, _confirmations(spec), reviewer="usr_designer")
    blockers = source_component_factory_blockers(
        confirmed.source_component_coverage,
        valid_spec_paths=valid_source_component_spec_paths(confirmed),
        current_spec_visual_hash=spec_visual_hash(confirmed),
        current_source_hash=hashlib.sha256(_png((1, 2, 3))).hexdigest(),
    )
    assert {blocker.code for blocker in blockers} == {
        "source_component_confirmation_stale"}


def test_confirmation_api_returns_typed_replacement_spec():
    source = _png()
    spec = _spec_with_audit()
    response = TestClient(app).post("/specs/source-coverage/confirm", json={
        "spec": spec.model_dump(mode="json"),
        "source_image_base64": base64.b64encode(source).decode(),
        "confirmations": [item.model_dump(mode="json")
                          for item in _confirmations(spec)],
        "created_by": "usr_designer",
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["factory_ready"] is True
    assert body["blockers"] == []
    assert body["confirmed_by"] == "usr_designer"
    assert len(body["confirmed_component_ids"]) == len(
        spec.source_component_coverage.components)

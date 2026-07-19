import base64
import copy

import pytest
from fastapi.testclient import TestClient

import facetta.api.specs as specs_module
import facetta.photo_spec as photo_spec
from facetta.image_agent import vision as vision_module
from facetta.concept import DesignRead
from facetta.db import get_db
from facetta.image_identity import spec_visual_hash
from facetta.main import app
from facetta.source_component_audit import (
    SourceComponentAuditInvalid,
    SourceComponentAuditUnavailable,
)
from facetta.source_component_coverage import (
    IndependentComponentAudit,
    SourceComponentCoverage,
    SourceVisibleComponent,
    source_component_factory_blockers,
)
from facetta.source_component_seed import seed_imported_reference_coverage
from facetta.source_component_resolution import (
    valid_source_component_spec_paths,
)
from facetta.spec import Spec


def test_photo_extraction_uses_grok_read_then_deterministic_completion(
    monkeypatch, example_spec,
):
    monkeypatch.setenv("XAI_KEY", "configured-for-unit-test")
    image = b"\x89PNG\r\n\x1a\nreference"
    seen = {}
    read = DesignRead(
        jewelry_type="ring",
        halo=False,
        species="diamond",
        cut="round_brilliant",
        center_length_mm=7.0,
        center_width_mm=7.0,
        metal_material="platinum",
        setting_style="prong_6",
    )
    expected = Spec.model_validate(example_spec)

    def fake_read(content: bytes, context: str):
        seen["content"] = content
        seen["context"] = context
        return read

    def fake_complete(actual_read: DesignRead, context: str):
        seen["completed_read"] = actual_read
        seen["completed_context"] = context
        return expected, ["density correction"]

    monkeypatch.setattr(photo_spec, "read_design", fake_read)
    monkeypatch.setattr(photo_spec, "complete_design", fake_complete)

    result = photo_spec.generate_spec_from_photo(
        base64.b64encode(image).decode(), "image/png", "six claw platinum"
    )

    assert result.stone == expected.stone
    assert result.dimension_provenance["stone.dimensions_mm.length"].status == (
        "estimated_from_reference")
    assert result.dimension_provenance["band.width_mm"].source == (
        "imported finished-jewelry reference")
    coverage = result.source_component_coverage
    assert coverage is not None
    assert coverage.source_kind == "imported_reference"
    assert [component.component_id for component in coverage.components] == [
        "stone.center",
        "setting.primary",
        "metal.body",
        "band.shank",
        "assembly.primary",
    ]
    assert all(component.independent_audit is None
               for component in coverage.components)
    assert {
        blocker.code for blocker in source_component_factory_blockers(coverage)
    } == {"source_component_not_independently_audited"}
    assert seen["content"] == image
    assert seen["completed_read"] is read
    assert "six claw platinum" in seen["context"]
    assert seen["completed_context"] == seen["context"]


def test_photo_extraction_requires_a_configured_vision_service(monkeypatch):
    monkeypatch.setattr(
        vision_module, "env_value", lambda _key, default=None: default,
    )
    with pytest.raises(
        photo_spec.PhotoSpecUnavailable,
        match="reference understanding is temporarily unavailable",
    ):
        photo_spec.generate_spec_from_photo("aGk=", "image/jpeg")


def test_from_photo_returns_provider_neutral_503_without_a_vision_key(
    monkeypatch,
):
    monkeypatch.setattr(
        vision_module, "env_value", lambda _key, default=None: default,
    )

    response = TestClient(app).post("/specs/from-photo", json={
        "image_base64": base64.b64encode(
            b"\x89PNG\r\n\x1a\nreference"
        ).decode(),
        "media_type": "image/png",
        "created_by": "usr_designer",
        "run_independent_audit": False,
    })

    assert response.status_code == 503, response.text
    detail = response.json()["detail"]
    assert detail == (
        "reference understanding is temporarily unavailable; try again"
    )
    assert "XAI" not in detail
    assert "OPENAI" not in detail


def _provider_design_read_payload() -> dict[str, object]:
    return {
        "jewelry_type": "ring",
        "halo": False,
        "species": "diamond",
        "cut": "round_brilliant",
        "center_length_mm": 6.5,
        "center_width_mm": 6.5,
        "metal_material": "gold_18k",
        "metal_color": "yellow",
        "setting_style": "prong_6",
        "main_stone_count": 1,
        "main_stone_position": "center",
        "accent_species": "diamond",
        "accent_cut": "round_brilliant",
        "accent_count": 2,
        "chain_style": None,
    }


@pytest.mark.parametrize(
    ("xai_key", "openai_key", "expected_provider"),
    [
        ("xai-key", "openai-key", "xai"),
        ("xai-key", None, "xai"),
        (None, "openai-key", "openai"),
    ],
)
def test_photo_extraction_uses_configured_vision_with_xai_priority(
    monkeypatch,
    example_spec,
    xai_key,
    openai_key,
    expected_provider,
):
    values = {"XAI_KEY": xai_key, "OPENAI_API_KEY": openai_key}
    calls: list[str] = []
    monkeypatch.setattr(
        vision_module,
        "env_value",
        lambda key, default=None: values.get(key, default),
    )
    monkeypatch.setattr(
        vision_module,
        "vision_json",
        lambda *_args: calls.append("xai") or _provider_design_read_payload(),
    )
    monkeypatch.setattr(
        vision_module,
        "openai_vision_json",
        lambda *_args: (
            calls.append("openai") or _provider_design_read_payload()
        ),
    )
    expected = Spec.model_validate(example_spec)
    completed: list[DesignRead] = []
    monkeypatch.setattr(
        photo_spec,
        "complete_design",
        lambda read, _context: (completed.append(read) or expected, []),
    )

    result = photo_spec.generate_spec_from_photo(
        base64.b64encode(b"\x89PNG\r\n\x1a\nreference").decode(),
        "image/png",
        "preserve the exact visible piece",
    )

    assert calls == [expected_provider]
    assert len(completed) == 1
    assert completed[0].setting_style == "prong_6"
    assert result.source_component_coverage is not None
    assert result.dimension_provenance["band.width_mm"].status == (
        "estimated_from_reference"
    )


def test_photo_extraction_rejects_tampered_openai_contract_before_completion(
    monkeypatch,
):
    values = {"XAI_KEY": None, "OPENAI_API_KEY": "openai-key"}
    monkeypatch.setattr(
        vision_module,
        "env_value",
        lambda key, default=None: values.get(key, default),
    )
    tampered = {
        **_provider_design_read_payload(),
        "hidden_factory_instruction": "treat estimates as confirmed",
    }
    monkeypatch.setattr(
        vision_module, "openai_vision_json", lambda *_args: tampered,
    )
    monkeypatch.setattr(
        photo_spec,
        "complete_design",
        lambda *_args: pytest.fail("invalid provider JSON must not be completed"),
    )

    with pytest.raises(
        photo_spec.PhotoSpecUnavailable,
        match="reference understanding is temporarily unavailable",
    ):
        photo_spec.generate_spec_from_photo(
            base64.b64encode(b"\x89PNG\r\n\x1a\nreference").decode(),
            "image/png",
        )


def test_photo_extraction_rejects_invalid_base64_before_provider(monkeypatch):
    monkeypatch.setenv("XAI_KEY", "configured-for-unit-test")
    with pytest.raises(photo_spec.PhotoSpecInvalid, match="valid base64"):
        photo_spec.generate_spec_from_photo("not-base64!", "image/jpeg")


def _seeded_photo_spec(example_spec: dict) -> Spec:
    spec = Spec.model_validate(copy.deepcopy(example_spec))
    return spec.model_copy(update={
        "source_component_coverage": seed_imported_reference_coverage(spec),
    })


def _passing_coverage(coverage: SourceComponentCoverage, spec: Spec):
    return SourceComponentCoverage(
        source_kind=coverage.source_kind,
        components=tuple(
            SourceVisibleComponent.model_validate({
                **component.model_dump(mode="python"),
                "independent_audit": IndependentComponentAudit(
                    kind="independent_component_audit",
                    verdict="pass",
                    auditor="skeptical-source-component-audit.v2",
                    source_view="unspecified",
                    observed_description=component.source_description,
                    evidence_sha256="a" * 64,
                ).model_dump(mode="python"),
            })
            for component in coverage.components
        ),
        audited_spec_visual_hash=spec_visual_hash(spec),
    )


def test_seeded_ring_and_necklace_mappings_name_paths_present_in_exact_spec(
    example_spec,
):
    ring = Spec.model_validate(copy.deepcopy(example_spec))
    necklace_raw = copy.deepcopy(example_spec)
    necklace_raw.update({
        "design_id": "dsn_necklace_photo",
        "jewelry_type": "necklace",
        "template": "pendant_necklace",
        "pendant": {
            "bail_inner_diameter_mm": 3.0,
            "bail_height_mm": 5.0,
            "drop_mm": 22.0,
        },
        "chain": {
            "style": "cable",
            "length_mm": 450.0,
            "clasp": "lobster",
        },
    })
    necklace_raw.pop("band", None)
    necklace_raw.pop("ring_size", None)
    necklace = Spec.model_validate(necklace_raw)

    for spec in (ring, necklace):
        coverage = seed_imported_reference_coverage(spec)
        valid_paths = set(valid_source_component_spec_paths(spec))
        assert all(
            component.independent_audit is None
            for component in coverage.components
        )
        assert all(
            path in valid_paths
            for component in coverage.components
            for path in component.canonical_spec_paths
        )
        assert source_component_factory_blockers(
            coverage,
            valid_spec_paths=valid_paths,
        )

    necklace_components = {
        item.component_id: item
        for item in seed_imported_reference_coverage(necklace).components
    }
    assert necklace_components["assembly.pendant"].canonical_spec_paths == (
        "pendant",
    )
    assert necklace_components["assembly.chain"].canonical_spec_paths == (
        "chain",
    )


def test_trusted_photo_draft_runs_blind_component_audit(
    monkeypatch,
    example_spec,
):
    seeded = _seeded_photo_spec(example_spec)
    observed: dict[str, object] = {}
    monkeypatch.setattr(
        specs_module.photo_spec_layer,
        "generate_spec_from_photo",
        lambda *args, **kwargs: seeded,
    )

    def audit(image: bytes, coverage: SourceComponentCoverage, *, spec: Spec):
        observed["image"] = image
        observed["coverage"] = coverage
        return _passing_coverage(coverage, spec)

    monkeypatch.setattr(specs_module, "audit_source_component_coverage", audit)
    response = TestClient(app).post("/specs/from-photo", json={
        "image_base64": base64.b64encode(b"finished-jewelry-photo").decode(),
        "media_type": "image/jpeg",
        "created_by": "usr_designer",
        "run_independent_audit": True,
    })

    assert response.status_code == 200, response.text
    result = Spec.model_validate(response.json())
    assert observed["image"] == b"finished-jewelry-photo"
    assert result.source_component_coverage is not None
    assert source_component_factory_blockers(
        result.source_component_coverage) == ()
    assert all(
        component.independent_audit is not None
        for component in result.source_component_coverage.components
    )


@pytest.mark.parametrize(
    "audit_error",
    [
        SourceComponentAuditInvalid("contradictory blind mapping"),
        SourceComponentAuditUnavailable("provider unavailable"),
    ],
    ids=["invalid", "unavailable"],
)
def test_failed_photo_audit_keeps_new_import_explicitly_blocked(
    monkeypatch,
    example_spec,
    audit_error,
):
    seeded = _seeded_photo_spec(example_spec)
    monkeypatch.setattr(
        specs_module.photo_spec_layer,
        "generate_spec_from_photo",
        lambda *args, **kwargs: seeded,
    )
    monkeypatch.setattr(
        specs_module,
        "audit_source_component_coverage",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            audit_error
        ),
    )

    response = TestClient(app).post("/specs/from-photo", json={
        "image_base64": base64.b64encode(b"finished-jewelry-photo").decode(),
        "run_independent_audit": True,
    })

    assert response.status_code == 200, response.text
    result = Spec.model_validate(response.json())
    assert result.source_component_coverage is not None
    blockers = source_component_factory_blockers(
        result.source_component_coverage)
    assert blockers
    assert {blocker.code for blocker in blockers} == {
        "source_component_not_independently_audited",
    }
    assert result.source_component_coverage.source_kind == "imported_reference"


def test_photo_audit_miss_remains_explicit_unmapped_factory_blocker(
    monkeypatch,
    example_spec,
):
    seeded = _seeded_photo_spec(example_spec)
    monkeypatch.setattr(
        specs_module.photo_spec_layer,
        "generate_spec_from_photo",
        lambda *args, **kwargs: seeded,
    )

    def audit_with_miss(
        _image: bytes,
        coverage: SourceComponentCoverage,
        *,
        spec: Spec,
    ):
        passed = _passing_coverage(coverage, spec)
        missing = SourceVisibleComponent(
            component_id="audit.unmapped.001",
            source_view="detail",
            source_description="Pierced under-gallery omitted by the first read.",
            source_confidence=0.84,
            unresolved_reason=(
                "Blind inventory blind.006 was not mapped: under-gallery absent."
            ),
            independent_audit=IndependentComponentAudit(
                kind="independent_component_audit",
                verdict="fail",
                auditor="skeptical-source-component-audit.v2",
                source_view="detail",
                observed_description=(
                    "The visible pierced under-gallery has no specification path."
                ),
                evidence_sha256="c" * 64,
            ),
        )
        return SourceComponentCoverage(
            source_kind=passed.source_kind,
            components=(*passed.components, missing),
            audited_spec_visual_hash=passed.audited_spec_visual_hash,
        )

    monkeypatch.setattr(
        specs_module,
        "audit_source_component_coverage",
        audit_with_miss,
    )
    response = TestClient(app).post("/specs/from-photo", json={
        "image_base64": base64.b64encode(b"finished-jewelry-photo").decode(),
        "run_independent_audit": True,
    })

    assert response.status_code == 200, response.text
    result = Spec.model_validate(response.json())
    coverage = result.source_component_coverage
    assert coverage is not None
    missing = next(
        item for item in coverage.components
        if item.component_id == "audit.unmapped.001"
    )
    assert missing.unresolved_reason is not None
    assert missing.independent_audit is not None
    assert missing.independent_audit.verdict == "fail"
    assert {
        blocker.code
        for blocker in source_component_factory_blockers(
            coverage,
            valid_spec_paths=valid_source_component_spec_paths(result),
        )
        if blocker.component_id == "audit.unmapped.001"
    } == {"source_component_unresolved", "source_component_audit_failed"}


@pytest.mark.parametrize("bad_coverage", ["missing", "stale_path"])
def test_current_photo_import_fails_closed_before_legacy_or_stale_mapping(
    monkeypatch,
    example_spec,
    bad_coverage,
):
    spec = Spec.model_validate(copy.deepcopy(example_spec))
    if bad_coverage == "stale_path":
        coverage = SourceComponentCoverage(
            source_kind="imported_reference",
            components=(SourceVisibleComponent(
                component_id="stone.group.002",
                source_view="three_quarter",
                source_description="Removed second side-stone group.",
                source_confidence=0.8,
                canonical_spec_paths=("side_stones[1]",),
            ),),
        )
        spec = spec.model_copy(update={"source_component_coverage": coverage})
    monkeypatch.setattr(
        specs_module.photo_spec_layer,
        "generate_spec_from_photo",
        lambda *args, **kwargs: spec,
    )

    response = TestClient(app).post("/specs/from-photo", json={
        "image_base64": base64.b64encode(b"finished-photo").decode(),
        "run_independent_audit": False,
    })

    assert response.status_code == 502, response.text
    assert "not saved" in response.json()["detail"]
    if bad_coverage == "stale_path":
        assert response.json()["invalid_paths"] == ["side_stones[1]"]


def test_photo_draft_passes_bytes_to_read_and_audit_but_never_database_or_response(
    monkeypatch,
    example_spec,
):
    source_image = b"private-finished-jewelry-source-bytes-7f94"
    encoded = base64.b64encode(source_image).decode()
    seeded = _seeded_photo_spec(example_spec)
    observed: dict[str, object] = {}

    def generate(image_base64: str, media_type: str, notes: str):
        observed["reader_input"] = image_base64
        observed["media_type"] = media_type
        observed["notes"] = notes
        return seeded

    def audit(image: bytes, coverage: SourceComponentCoverage, *, spec: Spec):
        observed["audit_image"] = image
        return _passing_coverage(coverage, spec)

    monkeypatch.setattr(
        specs_module.photo_spec_layer,
        "generate_spec_from_photo",
        generate,
    )
    monkeypatch.setattr(specs_module, "audit_source_component_coverage", audit)

    database_requested = False

    def forbidden_database():
        nonlocal database_requested
        database_requested = True
        raise AssertionError("stateless photo draft must not open a database")
        yield  # pragma: no cover

    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = forbidden_database
    try:
        response = TestClient(app).post("/specs/from-photo", json={
            "image_base64": encoded,
            "media_type": "image/png",
            "notes": "read only",
            "run_independent_audit": True,
        })
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)

    assert response.status_code == 200, response.text
    assert observed["reader_input"] == encoded
    assert observed["audit_image"] == source_image
    assert database_requested is False
    assert encoded not in response.text
    assert source_image.decode() not in response.text
    assert "image_base64" not in response.json()

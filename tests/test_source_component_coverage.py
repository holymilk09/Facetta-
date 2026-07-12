from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from facetta.image_identity import spec_visual_hash
from facetta.plate_spec import compile_plate_spec
from facetta.source_component_coverage import (
    IndependentComponentAudit,
    SourceComponentCoverage,
    SourceVisibleComponent,
    source_component_factory_blockers,
)
from facetta.source_component_resolution import (
    valid_source_component_spec_paths,
)
from facetta.spec import Spec


def _audit(verdict: str = "pass") -> IndependentComponentAudit:
    return IndependentComponentAudit(
        kind="independent_component_audit",
        verdict=verdict,
        auditor="skeptical-vision-audit.v1",
        source_view="plate_composite",
        observed_description="The source component and mapped spec agree.",
        evidence_sha256="a" * 64,
    )


def _mapped_component(
    component_id: str = "stone.center",
    *,
    audit: IndependentComponentAudit | None = None,
) -> SourceVisibleComponent:
    return SourceVisibleComponent(
        component_id=component_id,
        source_view="plate_composite",
        source_description="Oval blue center stone.",
        source_confidence=0.82,
        canonical_spec_paths=("stone",),
        independent_audit=audit,
    )


def test_legacy_spec_without_coverage_is_readable_and_nonblocking(example_spec):
    legacy = copy.deepcopy(example_spec)
    legacy.pop("source_component_coverage", None)

    spec = Spec.model_validate(legacy)

    assert spec.source_component_coverage is None
    assert source_component_factory_blockers(spec.source_component_coverage) == ()


def test_component_requires_mapping_xor_explicit_unresolved_reason():
    common = {
        "component_id": "stone.center",
        "source_view": "plate_composite",
        "source_description": "Center stone visible but identity unclear.",
        "source_confidence": 0.4,
    }

    with pytest.raises(ValidationError, match="canonical spec paths or"):
        SourceVisibleComponent(**common)

    with pytest.raises(ValidationError, match="but not both"):
        SourceVisibleComponent(
            **common,
            canonical_spec_paths=("stone",),
            unresolved_reason="The group cannot yet be identified.",
        )


@pytest.mark.parametrize("component_id", [
    "Stone.Center",
    "stone center",
    "stone/center",
    "_stone",
    "stone..center",
    "",
])
def test_visible_component_ids_are_stable_and_machine_safe(component_id):
    with pytest.raises(ValidationError):
        _mapped_component(component_id)


def test_coverage_rejects_duplicate_ids_and_noncanonical_paths():
    component = _mapped_component()
    with pytest.raises(ValidationError, match="IDs must be unique"):
        SourceComponentCoverage(
            source_kind="designer_plate",
            components=(component, component),
        )

    raw = component.model_dump(mode="json")
    raw["canonical_spec_paths"] = ["invented_cad.profile"]
    with pytest.raises(ValidationError):
        SourceVisibleComponent.model_validate(raw)


def test_coverage_can_map_an_organic_component_to_one_stable_form_element():
    mapped = SourceVisibleComponent(
        component_id="assembly.shoulders",
        source_view="three_quarter",
        source_description="Bilateral Art Deco shoulder architecture.",
        source_confidence=0.91,
        canonical_spec_paths=(
            "design_form.elements[shoulder_architecture]",
        ),
        independent_audit=_audit(),
    )

    assert mapped.canonical_spec_paths == (
        "design_form.elements[shoulder_architecture]",
    )


def test_coverage_cannot_smuggle_guessed_dimensions_or_cad():
    raw = _mapped_component().model_dump(mode="json")
    raw["estimated_width_mm"] = 3.4
    raw["cad_spline"] = [[0, 0], [1, 1]]

    with pytest.raises(ValidationError):
        SourceVisibleComponent.model_validate(raw)

    audit = _audit().model_dump(mode="json")
    audit["estimated_height_mm"] = 8.2
    with pytest.raises(ValidationError):
        IndependentComponentAudit.model_validate(audit)


def test_factory_blockers_report_unresolved_unaudited_and_failed_states():
    unresolved = SourceVisibleComponent(
        component_id="assembly.primary",
        source_view="plate_composite",
        source_description="Leaf-form shoulders around the center.",
        source_confidence=0.73,
        unresolved_reason="No supported form definition captures the leaves.",
    )
    unaudited = _mapped_component()
    failed = _mapped_component("stone.group.001", audit=_audit("fail"))
    coverage = SourceComponentCoverage(
        source_kind="designer_plate",
        components=(unresolved, unaudited, failed),
    )

    blockers = source_component_factory_blockers(coverage)
    codes_by_id = {}
    for blocker in blockers:
        codes_by_id.setdefault(blocker.component_id, set()).add(blocker.code)

    assert codes_by_id["assembly.primary"] == {
        "source_component_unresolved",
        "source_component_not_independently_audited",
    }
    assert codes_by_id["stone.center"] == {
        "source_component_not_independently_audited",
    }
    assert codes_by_id["stone.group.001"] == {
        "source_component_audit_failed",
    }


def test_passed_independent_audit_clears_mapped_component_blocker():
    coverage = SourceComponentCoverage(
        source_kind="designer_plate",
        components=(_mapped_component(audit=_audit()),),
    )

    assert source_component_factory_blockers(coverage) == ()


def test_exact_spec_audit_hash_is_required_only_at_current_workflow_boundary(
    example_spec,
):
    spec = Spec.model_validate(example_spec)
    current_hash = spec_visual_hash(spec)
    legacy_style = SourceComponentCoverage(
        source_kind="designer_plate",
        components=(_mapped_component(audit=_audit()),),
    )

    # Historical and low-level reads remain compatible until an exact current
    # spec is explicitly supplied by a trusted product boundary.
    assert source_component_factory_blockers(legacy_style) == ()
    missing = source_component_factory_blockers(
        legacy_style,
        current_spec_visual_hash=current_hash,
    )
    assert [(item.component_id, item.code) for item in missing] == [
        ("audit.spec", "source_component_spec_audit_missing"),
    ]

    stale = legacy_style.model_copy(update={
        "audited_spec_visual_hash": "0" * 16,
    })
    blockers = source_component_factory_blockers(
        stale,
        current_spec_visual_hash=current_hash,
    )
    assert [(item.component_id, item.code) for item in blockers] == [
        ("audit.spec", "source_component_spec_audit_stale"),
    ]

    current = legacy_style.model_copy(update={
        "audited_spec_visual_hash": current_hash,
    })
    assert source_component_factory_blockers(
        current,
        current_spec_visual_hash=current_hash,
    ) == ()


def test_passing_audit_cannot_clear_mapping_to_path_missing_from_current_spec(
    example_spec,
):
    spec = Spec.model_validate(example_spec)
    stale = SourceVisibleComponent(
        component_id="stone.group.002",
        source_view="three_quarter",
        source_description="Second shoulder stone group from an earlier draft.",
        source_confidence=0.9,
        canonical_spec_paths=("side_stones[1]",),
        independent_audit=_audit(),
    )
    coverage = SourceComponentCoverage(
        source_kind="imported_reference",
        components=(stale,),
    )

    valid_paths = valid_source_component_spec_paths(spec)
    assert "side_stones[1]" not in valid_paths
    blockers = source_component_factory_blockers(
        coverage,
        valid_spec_paths=valid_paths,
    )

    assert [(blocker.component_id, blocker.code) for blocker in blockers] == [
        ("stone.group.002", "source_component_path_missing"),
    ]
    assert "side_stones[1]" in blockers[0].message


def test_plate_compiler_accounts_for_every_group_and_major_ring_component():
    spec, _ = compile_plate_spec({
        "jewelry_type": "ring",
        "source_view": "top",
        "stones": [
            {"qty": 1, "type": "oval sapphire", "confidence": 0.91},
            {"qty": 12, "type": "round diamond halo", "confidence": 0.88},
            {"qty": 6, "type": "marquise diamond shoulders", "confidence": 0.79},
        ],
        "metal": "18k yellow gold",
        "metal_confidence": 0.9,
        "assembly": "four-prong ring with a halo and diamond shoulders",
        "assembly_confidence": 0.84,
        "measurements": [{
            "label": "shank width",
            "value": "2.4 mm",
            "raw": "2.4 mm shank",
            "status": "designer_confirmed",
            "confidence": 1.0,
        }],
    })

    coverage = spec.source_component_coverage
    assert coverage is not None
    components = {item.component_id: item for item in coverage.components}

    assert components["stone.center"].canonical_spec_paths == ("stone",)
    assert components["stone.group.001"].canonical_spec_paths == (
        "side_stones[0]",
    )
    assert components["stone.group.002"].canonical_spec_paths == (
        "side_stones[1]",
    )
    assert components["setting.primary"].canonical_spec_paths == ("setting",)
    assert components["metal.body"].canonical_spec_paths == ("metal",)
    assert components["band.shank"].canonical_spec_paths == ("band",)
    assert components["band.shank"].source_description == "2.4 mm shank"
    assert all(item.source_view == "top" for item in coverage.components)


def test_plate_compiler_does_not_silently_drop_leaf_diamonds_from_assembly():
    spec, _ = compile_plate_spec({
        "jewelry_type": "ring",
        "stones": [
            {"qty": 1, "type": "emerald-cut green center stone",
             "confidence": 0.8},
        ],
        "metal": "18k yellow gold",
        "assembly": "four-prong ring with diamond pavé leaf shoulders",
        "assembly_confidence": 0.77,
    })

    assert spec.side_stones == []
    coverage = spec.source_component_coverage
    assert coverage is not None
    components = {item.component_id: item for item in coverage.components}
    missing = components["stone.assembly_hint.shoulder"]
    assert missing.canonical_spec_paths == ()
    assert "no distinct stone group" in (missing.unresolved_reason or "")
    assert components["assembly.primary"].unresolved_reason is not None


def test_plate_compiler_marks_ambiguous_and_malformed_groups_unresolved():
    spec, _ = compile_plate_spec({
        "jewelry_type": "ring",
        "stones": [
            {"qty": 1, "type": "TBD", "status": "ambiguous",
             "confidence": 0.2},
            "unstructured possible accent stones",
        ],
        "metal": "TBD",
        "assembly": "",
    })

    coverage = spec.source_component_coverage
    assert coverage is not None
    components = {item.component_id: item for item in coverage.components}
    assert components["stone.center"].unresolved_reason is not None
    assert components["stone.unparsed.001"].unresolved_reason is not None
    assert components["assembly.primary"].unresolved_reason is not None
    assert components["metal.body"].unresolved_reason is not None
    assert components["band.shank"].unresolved_reason is not None


def test_plate_compiler_preserves_valid_independent_audit_evidence():
    audit = _audit().model_dump(mode="json")
    spec, _ = compile_plate_spec({
        "jewelry_type": "ring",
        "stones": [{
            "qty": 1,
            "type": "oval sapphire",
            "confidence": 0.9,
        }],
        "metal": "18k yellow gold",
        "assembly": "four-prong ring",
        "component_audits": {"stone.center": audit},
    })

    coverage = spec.source_component_coverage
    assert coverage is not None
    center = next(
        item for item in coverage.components if item.component_id == "stone.center"
    )
    assert center.independent_audit == _audit()

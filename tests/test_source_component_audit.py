from __future__ import annotations

import copy
import hashlib
import json

import pytest

import facetta.source_component_audit as audit_module
from facetta.image_identity import spec_visual_hash
from facetta.spec import Spec
from facetta.source_component_audit import (
    AUDITOR_VERSION,
    SourceComponentAuditInvalid,
    SourceComponentAuditUnavailable,
    audit_source_component_coverage,
)
from facetta.source_component_coverage import (
    SourceComponentCoverage,
    SourceVisibleComponent,
    source_component_factory_blockers,
)


def _coverage(*, unresolved: bool = False) -> SourceComponentCoverage:
    stone = SourceVisibleComponent(
        component_id="stone.center",
        source_view="three_quarter",
        source_description="Oval blue center stone.",
        source_confidence=0.91,
        canonical_spec_paths=("stone",),
    )
    if unresolved:
        shoulder = SourceVisibleComponent(
            component_id="assembly.shoulder",
            source_view="three_quarter",
            source_description="Sculpted bilateral shoulder motif.",
            source_confidence=0.78,
            unresolved_reason="No supported form definition captures the motif.",
        )
    else:
        shoulder = SourceVisibleComponent(
            component_id="assembly.shoulder",
            source_view="three_quarter",
            source_description="Sculpted bilateral shoulder motif.",
            source_confidence=0.78,
            canonical_spec_paths=(
                "design_form.elements[shoulder_architecture]",
            ),
        )
    return SourceComponentCoverage(
        source_kind="designer_plate",
        components=(stone, shoulder),
    )


def _inventory(*, include_unmapped: bool = False) -> dict:
    components = [
        {
            "inventory_id": "blind.001",
            "source_view": "three_quarter",
            "observed_description": "Oval blue center stone in a raised head.",
            "confidence": 0.94,
        },
        {
            "inventory_id": "blind.002",
            "source_view": "three_quarter",
            "observed_description": "Mirrored sculpted shoulders flank the head.",
            "confidence": 0.88,
        },
    ]
    if include_unmapped:
        components.append({
            "inventory_id": "blind.003",
            "source_view": "detail",
            "observed_description": "A distinct pierced gallery sits below the head.",
            "confidence": 0.83,
        })
    return {"components": components}


def _mapping(
    *,
    stone_verdict: str = "pass",
    shoulder_verdict: str = "pass",
    include_unmapped: bool = False,
) -> dict:
    accounting = [
        {
            "inventory_id": "blind.001",
            "coverage_component_ids": ["stone.center"],
            "unmapped_reason": None,
        },
        {
            "inventory_id": "blind.002",
            "coverage_component_ids": ["assembly.shoulder"],
            "unmapped_reason": None,
        },
    ]
    if include_unmapped:
        accounting.append({
            "inventory_id": "blind.003",
            "coverage_component_ids": [],
            "unmapped_reason": "The pierced gallery has no coverage component.",
        })
    return {
        "component_audits": [
            {
                "component_id": "stone.center",
                "verdict": stone_verdict,
                "source_view": "three_quarter",
                "observed_description": (
                    "The visible center stone is accounted for by the stone path."
                ),
                "matched_inventory_ids": ["blind.001"],
            },
            {
                "component_id": "assembly.shoulder",
                "verdict": shoulder_verdict,
                "source_view": "three_quarter",
                "observed_description": (
                    "The mirrored shoulder form is accounted for by one stable element."
                ),
                "matched_inventory_ids": ["blind.002"],
            },
        ],
        "inventory_accounting": accounting,
    }


def _standard_halo_coverage() -> SourceComponentCoverage:
    components = (
        ("stone.center", "Oval blue center stone.", ("stone",)),
        (
            "stone.group.001",
            "Halo group of small round colorless stones.",
            ("side_stones[0]",),
        ),
        (
            "assembly.primary",
            "Complete oval-center halo ring assembly.",
            ("template",),
        ),
        (
            "setting.primary",
            "Open center-stone head and gallery.",
            ("setting",),
        ),
        ("metal.body", "White metal throughout the ring.", ("metal",)),
        ("band.shank", "Plain lower ring shank.", ("band",)),
    )
    return SourceComponentCoverage(
        source_kind="designer_plate",
        components=tuple(
            SourceVisibleComponent(
                component_id=component_id,
                source_view="plate_composite",
                source_description=description,
                source_confidence=0.9,
                canonical_spec_paths=paths,
            )
            for component_id, description, paths in components
        ),
    )


def _standard_halo_inventory() -> dict:
    descriptions = (
        "Complete halo ring with oval center, surrounding halo, and shank.",
        "Oval blue center stone.",
        "Halo group of eight small round colorless stones.",
        "Open metal head and gallery setting with four visible prongs.",
        "White-metal lower shank.",
    )
    return {
        "components": [
            {
                "inventory_id": f"blind.{index:03d}",
                "source_view": "plate_composite",
                "observed_description": description,
                "confidence": 0.9,
            }
            for index, description in enumerate(descriptions, start=1)
        ],
    }


def _standard_halo_mapping(*, composite_direction_omission: bool) -> dict:
    component_audits = [
        {
            "component_id": "stone.center",
            "verdict": "pass",
            "source_view": "plate_composite",
            "observed_description": "The oval center stone is represented.",
            "matched_inventory_ids": ["blind.001", "blind.002"],
        },
        {
            "component_id": "stone.group.001",
            "verdict": "pass",
            "source_view": "plate_composite",
            "observed_description": "The repeated halo group is represented.",
            "matched_inventory_ids": ["blind.001", "blind.003"],
        },
        {
            "component_id": "assembly.primary",
            "verdict": "pass",
            "source_view": "plate_composite",
            "observed_description": "The complete halo assembly is represented.",
            "matched_inventory_ids": ["blind.001"],
        },
        {
            "component_id": "setting.primary",
            "verdict": "pass",
            "source_view": "plate_composite",
            "observed_description": "The visible head and gallery are represented.",
            "matched_inventory_ids": ["blind.004"],
        },
        {
            "component_id": "metal.body",
            "verdict": "pass",
            "source_view": "plate_composite",
            "observed_description": "The visible metal body is represented.",
            "matched_inventory_ids": ["blind.004", "blind.005"],
        },
        {
            "component_id": "band.shank",
            "verdict": "pass",
            "source_view": "plate_composite",
            "observed_description": "The lower shank is represented.",
            "matched_inventory_ids": ["blind.005"],
        },
    ]
    broad_ids = [
        "assembly.primary",
        "stone.center",
        "stone.group.001",
    ]
    if composite_direction_omission:
        # A common model formatting error: inventory accounting names only
        # the whole assembly while the reverse direction also names the
        # center/halo members supported by that same broad observation.
        broad_ids = ["assembly.primary"]
    return {
        "component_audits": component_audits,
        "inventory_accounting": [
            {
                "inventory_id": "blind.001",
                "coverage_component_ids": broad_ids,
                "unmapped_reason": None,
            },
            {
                "inventory_id": "blind.002",
                "coverage_component_ids": ["stone.center"],
                "unmapped_reason": None,
            },
            {
                "inventory_id": "blind.003",
                "coverage_component_ids": ["stone.group.001"],
                "unmapped_reason": None,
            },
            {
                "inventory_id": "blind.004",
                "coverage_component_ids": ["setting.primary", "metal.body"],
                "unmapped_reason": None,
            },
            {
                "inventory_id": "blind.005",
                "coverage_component_ids": ["metal.body", "band.shank"],
                "unmapped_reason": None,
            },
        ],
    }


class _TwoPassInspector:
    def __init__(self, inventory: dict, mapping: dict):
        self.responses = [inventory, mapping]
        self.calls: list[tuple[str, bytes, str]] = []

    def __call__(self, system: str, image: bytes, user_text: str) -> dict:
        self.calls.append((system, image, user_text))
        return copy.deepcopy(self.responses[len(self.calls) - 1])


def test_standard_halo_composite_overlap_is_normalized_not_rejected():
    coverage = _standard_halo_coverage()
    audited = audit_source_component_coverage(
        b"standard-halo-source",
        coverage,
        inspect=_TwoPassInspector(
            _standard_halo_inventory(),
            _standard_halo_mapping(composite_direction_omission=True),
        ),
    )

    assert audited is not coverage
    assert [component.component_id for component in audited.components] == [
        "stone.center",
        "stone.group.001",
        "assembly.primary",
        "setting.primary",
        "metal.body",
        "band.shank",
    ]
    assert all(
        component.independent_audit is not None
        and component.independent_audit.verdict == "pass"
        for component in audited.components
    )
    assert source_component_factory_blockers(audited) == ()


def test_nonaggregate_one_to_many_identity_conflict_still_fails_with_raw_debug():
    mapping = _standard_halo_mapping(composite_direction_omission=False)
    # blind.002 is the specific center-stone observation. Claiming it for the
    # halo group in only the component-audit direction is a real identity
    # contradiction, not aggregate/member overlap.
    mapping["component_audits"][1]["matched_inventory_ids"].append(
        "blind.002"
    )

    with pytest.raises(
        SourceComponentAuditInvalid,
        match=r"blind\.002 has contradictory bidirectional mapping",
    ) as raised:
        audit_source_component_coverage(
            b"standard-halo-source",
            _standard_halo_coverage(),
            inspect=_TwoPassInspector(_standard_halo_inventory(), mapping),
        )

    debug = raised.value.debug_evidence
    assert debug is not None
    assert debug["source_sha256"] == hashlib.sha256(
        b"standard-halo-source"
    ).hexdigest()
    assert debug["blind_inventory_pass"] == _standard_halo_inventory()
    assert debug["independent_mapping_pass"] == mapping
    assert "source_image" not in debug


def test_aggregate_component_cannot_relabel_a_specific_center_observation():
    mapping = _standard_halo_mapping(composite_direction_omission=False)
    # The specific center-only blind item is not evidence for the whole ring,
    # even though assembly.primary is a valid aggregate elsewhere.
    mapping["component_audits"][2]["matched_inventory_ids"].append(
        "blind.002"
    )

    with pytest.raises(
        SourceComponentAuditInvalid,
        match=r"blind\.002 has contradictory bidirectional mapping",
    ):
        audit_source_component_coverage(
            b"standard-halo-source",
            _standard_halo_coverage(),
            inspect=_TwoPassInspector(_standard_halo_inventory(), mapping),
        )


def test_audit_is_blind_first_then_maps_exact_coverage_without_mutating_input():
    coverage = _coverage()
    original = coverage.model_dump(mode="json")
    inspector = _TwoPassInspector(_inventory(), _mapping())

    audited = audit_source_component_coverage(
        b"source-image",
        coverage,
        inspect=inspector,
    )

    assert coverage.model_dump(mode="json") == original
    assert audited is not coverage
    assert len(inspector.calls) == 2
    assert inspector.calls[0][1] == b"source-image"
    blind_prompt = inspector.calls[0][0] + inspector.calls[0][2]
    assert "stone.center" not in blind_prompt
    assert "Oval blue center stone." not in blind_prompt
    assert "design_form.elements[shoulder_architecture]" not in blind_prompt

    mapping_payload = json.loads(inspector.calls[1][2])
    exact_components = mapping_payload["coverage_to_audit"]["components"]
    assert exact_components == [
        {
            "component_id": "stone.center",
            "source_view": "three_quarter",
            "source_description": "Oval blue center stone.",
            "canonical_spec_paths": ["stone"],
            "unresolved_reason": None,
        },
        {
            "component_id": "assembly.shoulder",
            "source_view": "three_quarter",
            "source_description": "Sculpted bilateral shoulder motif.",
            "canonical_spec_paths": [
                "design_form.elements[shoulder_architecture]",
            ],
            "unresolved_reason": None,
        },
    ]

    for component in audited.components:
        assert component.independent_audit is not None
        assert component.independent_audit.verdict == "pass"
        assert component.independent_audit.auditor == AUDITOR_VERSION
        assert len(component.independent_audit.evidence_sha256 or "") == 64
    assert source_component_factory_blockers(audited) == ()


def test_unmapped_blind_inventory_is_appended_as_explicit_failed_component():
    audited = audit_source_component_coverage(
        b"source-image",
        _coverage(),
        inspect=_TwoPassInspector(
            _inventory(include_unmapped=True),
            _mapping(include_unmapped=True),
        ),
    )

    unmapped = audited.components[-1]
    assert unmapped.component_id == "audit.unmapped.001"
    assert unmapped.source_view == "detail"
    assert unmapped.source_description == (
        "A distinct pierced gallery sits below the head."
    )
    assert unmapped.canonical_spec_paths == ()
    assert unmapped.unresolved_reason == (
        "Blind inventory blind.003 was not mapped: "
        "The pierced gallery has no coverage component."
    )
    assert unmapped.independent_audit is not None
    assert unmapped.independent_audit.verdict == "fail"

    blocker_codes = {
        blocker.code
        for blocker in source_component_factory_blockers(audited)
        if blocker.component_id == "audit.unmapped.001"
    }
    assert blocker_codes == {
        "source_component_unresolved",
        "source_component_audit_failed",
    }


def test_evidence_sha_content_addresses_source_and_both_raw_passes():
    inventory = _inventory()
    mapping = _mapping()
    snapshots: list[dict[str, object]] = []
    audited = audit_source_component_coverage(
        b"source-A",
        _coverage(),
        inspect=_TwoPassInspector(inventory, mapping),
        evidence_sink=snapshots.append,
    )
    evidence_sha = audited.components[0].independent_audit.evidence_sha256  # type: ignore[union-attr]
    expected_payload = {
        "source_sha256": hashlib.sha256(b"source-A").hexdigest(),
        "coverage_to_audit": {
            "source_kind": "designer_plate",
            "components": [
                {
                    "component_id": "stone.center",
                    "source_view": "three_quarter",
                    "source_description": "Oval blue center stone.",
                    "canonical_spec_paths": ["stone"],
                    "unresolved_reason": None,
                },
                {
                    "component_id": "assembly.shoulder",
                    "source_view": "three_quarter",
                    "source_description": "Sculpted bilateral shoulder motif.",
                    "canonical_spec_paths": [
                        "design_form.elements[shoulder_architecture]",
                    ],
                    "unresolved_reason": None,
                },
            ],
        },
        "blind_inventory_pass": inventory,
        "independent_mapping_pass": mapping,
    }
    expected_sha = hashlib.sha256(json.dumps(
        expected_payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")).hexdigest()
    assert evidence_sha == expected_sha
    assert snapshots[0] == {
        "stage": "blind_inventory_complete",
        "auditor": AUDITOR_VERSION,
        "source_sha256": hashlib.sha256(b"source-A").hexdigest(),
        "coverage_to_audit": expected_payload["coverage_to_audit"],
        "blind_inventory_pass": inventory,
    }
    assert snapshots[1] == {
        "stage": "complete",
        "auditor": AUDITOR_VERSION,
        "source_sha256": hashlib.sha256(b"source-A").hexdigest(),
        "coverage_to_audit": expected_payload["coverage_to_audit"],
        "blind_inventory_pass": inventory,
        "independent_mapping_pass": mapping,
        "evidence_sha256": expected_sha,
    }
    assert "source_image" not in snapshots[1]

    changed_source = audit_source_component_coverage(
        b"source-B",
        _coverage(),
        inspect=_TwoPassInspector(inventory, mapping),
    )
    assert (
        changed_source.components[0].independent_audit.evidence_sha256  # type: ignore[union-attr]
        != evidence_sha
    )

    changed_mapping = copy.deepcopy(mapping)
    changed_mapping["component_audits"][0]["observed_description"] = (
        "Independent evidence changed while the verdict stayed the same."
    )
    changed_pass = audit_source_component_coverage(
        b"source-A",
        _coverage(),
        inspect=_TwoPassInspector(inventory, changed_mapping),
    )
    assert (
        changed_pass.components[0].independent_audit.evidence_sha256  # type: ignore[union-attr]
        != evidence_sha
    )


def test_audit_binds_exact_visible_spec_facts_and_hash(halo_spec):
    spec = Spec.model_validate(halo_spec)
    inspector = _TwoPassInspector(
        _standard_halo_inventory(),
        _standard_halo_mapping(composite_direction_omission=False),
    )

    audited = audit_source_component_coverage(
        b"standard-halo-source",
        _standard_halo_coverage(),
        spec=spec,
        inspect=inspector,
    )

    expected_hash = spec_visual_hash(spec)
    assert audited.audited_spec_visual_hash == expected_hash
    mapping_payload = json.loads(inspector.calls[1][2])
    assert mapping_payload["coverage_to_audit"]["audited_spec_visual_hash"] == (
        expected_hash
    )
    components = {
        item["component_id"]: item
        for item in mapping_payload["coverage_to_audit"]["components"]
    }
    assert components["stone.group.001"]["mapped_visible_spec_facts"][
        "side_stones[0]"
    ]["count"] == 8
    assert "dimensions_mm" not in components["stone.group.001"][
        "mapped_visible_spec_facts"
    ]["side_stones[0]"]
    assert source_component_factory_blockers(
        audited,
        current_spec_visual_hash=expected_hash,
    ) == ()


def test_visible_halo_count_conflict_overrides_false_model_pass(halo_spec):
    spec = Spec.model_validate(halo_spec)
    inventory = _standard_halo_inventory()
    inventory["components"][2]["observed_description"] = (
        "Halo of 20 small round colorless stones."
    )

    audited = audit_source_component_coverage(
        b"standard-halo-source",
        _standard_halo_coverage(),
        spec=spec,
        inspect=_TwoPassInspector(
            inventory,
            _standard_halo_mapping(composite_direction_omission=False),
        ),
    )

    halo = next(
        item for item in audited.components
        if item.component_id == "stone.group.001"
    )
    assert halo.independent_audit is not None
    assert halo.independent_audit.verdict == "fail"
    assert "count 8" in halo.independent_audit.observed_description
    assert "says 20" in halo.independent_audit.observed_description


def test_missing_blind_count_cannot_be_upgraded_to_pass_by_mapping(halo_spec):
    spec = Spec.model_validate(halo_spec)
    inventory = _standard_halo_inventory()
    inventory["components"][2]["observed_description"] = (
        "Halo group of small round colorless stones."
    )

    audited = audit_source_component_coverage(
        b"standard-halo-source",
        _standard_halo_coverage(),
        spec=spec,
        inspect=_TwoPassInspector(
            inventory,
            _standard_halo_mapping(composite_direction_omission=False),
        ),
    )

    halo = next(
        item for item in audited.components
        if item.component_id == "stone.group.001"
    )
    assert halo.independent_audit is not None
    assert halo.independent_audit.verdict == "inconclusive"
    assert "blind inventory did not state" in (
        halo.independent_audit.observed_description
    )


def test_silver_tone_cannot_hard_fail_a_platinum_spec_from_pixels(halo_spec):
    raw = copy.deepcopy(halo_spec)
    raw["metal"] = {
        "material": "platinum",
        "karat": None,
        "color": None,
        "finish": "high_polish",
    }
    spec = Spec.model_validate(raw)
    coverage = SourceComponentCoverage(
        source_kind="imported_reference",
        components=(SourceVisibleComponent(
            component_id="metal.body",
            source_view="front",
            source_description="platinum metal body",
            source_confidence=0.8,
            canonical_spec_paths=("metal",),
        ),),
    )
    inventory = {"components": [{
        "inventory_id": "blind.001",
        "source_view": "front",
        "observed_description": "Silver-tone white metal throughout the piece.",
        "confidence": 0.92,
    }]}
    mapping = {
        "component_audits": [{
            "component_id": "metal.body",
            "verdict": "fail",
            "source_view": "front",
            "observed_description": "The source looks silver, not proven platinum.",
            "matched_inventory_ids": ["blind.001"],
        }],
        "inventory_accounting": [{
            "inventory_id": "blind.001",
            "coverage_component_ids": ["metal.body"],
            "unmapped_reason": None,
        }],
    }

    audited = audit_source_component_coverage(
        b"source-image",
        coverage,
        spec=spec,
        inspect=_TwoPassInspector(inventory, mapping),
    )

    evidence = audited.components[0].independent_audit
    assert evidence is not None
    assert evidence.verdict == "inconclusive"
    assert "cannot prove the exact platinum alloy" in evidence.observed_description


def test_generic_template_cannot_claim_distinctive_vine_topology(necklace_spec):
    spec = Spec.model_validate(necklace_spec)
    coverage = SourceComponentCoverage(
        source_kind="imported_reference",
        components=(SourceVisibleComponent(
            component_id="assembly.primary",
            source_view="front",
            source_description="cluster_pendant primary assembly topology",
            source_confidence=0.9,
            canonical_spec_paths=("template",),
        ),),
    )
    inventory = {"components": [{
        "inventory_id": "blind.001",
        "source_view": "front",
        "observed_description": (
            "Asymmetric branching vine pendant with botanical leaf motifs."
        ),
        "confidence": 0.94,
    }]}
    mapping = {
        "component_audits": [{
            "component_id": "assembly.primary",
            "verdict": "pass",
            "source_view": "front",
            "observed_description": "The vine cluster is represented.",
            "matched_inventory_ids": ["blind.001"],
        }],
        "inventory_accounting": [{
            "inventory_id": "blind.001",
            "coverage_component_ids": ["assembly.primary"],
            "unmapped_reason": None,
        }],
    }

    audited = audit_source_component_coverage(
        b"source-image",
        coverage,
        spec=spec,
        inspect=_TwoPassInspector(inventory, mapping),
    )

    evidence = audited.components[0].independent_audit
    assert evidence is not None
    assert evidence.verdict == "fail"
    assert "stable design_form element" in evidence.observed_description


@pytest.mark.parametrize("failed_call", [1, 2])
def test_provider_failure_has_specific_unavailable_error(failed_call):
    call_count = 0

    def inspect(_system: str, _image: bytes, _user_text: str) -> dict:
        nonlocal call_count
        call_count += 1
        if call_count == failed_call:
            raise TimeoutError("provider timed out with secret detail")
        return _inventory()

    with pytest.raises(
        SourceComponentAuditUnavailable,
        match="source-component .* pass unavailable",
    ) as raised:
        audit_source_component_coverage(
            b"source-image",
            _coverage(),
            inspect=inspect,
        )
    assert "secret detail" not in str(raised.value)
    if failed_call == 2:
        assert raised.value.debug_evidence is not None
        assert raised.value.debug_evidence["blind_inventory_pass"] == _inventory()
        assert "independent_mapping_pass" not in raised.value.debug_evidence
    else:
        assert raised.value.debug_evidence is None


def test_evidence_sink_retains_blind_pass_when_mapping_provider_fails():
    snapshots: list[dict[str, object]] = []
    call_count = 0

    def inspect(_system: str, _image: bytes, _user_text: str) -> dict:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise TimeoutError("mapping unavailable")
        return _inventory()

    with pytest.raises(SourceComponentAuditUnavailable):
        audit_source_component_coverage(
            b"source-image",
            _coverage(),
            inspect=inspect,
            evidence_sink=snapshots.append,
        )

    assert len(snapshots) == 1
    assert snapshots[0]["stage"] == "blind_inventory_complete"
    assert snapshots[0]["blind_inventory_pass"] == _inventory()
    assert "independent_mapping_pass" not in snapshots[0]


def test_default_transport_is_provider_injectable_without_network(monkeypatch):
    inspector = _TwoPassInspector(_inventory(), _mapping())
    monkeypatch.setattr(audit_module, "vision_json", inspector)

    audited = audit_source_component_coverage(b"source-image", _coverage())

    assert len(inspector.calls) == 2
    assert all(item.independent_audit is not None for item in audited.components)


@pytest.mark.parametrize(
    "mutate, message",
    [
        (
            lambda value: value["component_audits"].pop(),
            "every exact coverage component ID once",
        ),
        (
            lambda value: value["inventory_accounting"][0].update(
                {"coverage_component_ids": ["assembly.shoulder"]}
            ),
            "contradictory bidirectional mapping",
        ),
        (
            lambda value: value["component_audits"][0].update(
                {"estimated_width_mm": 2.4}
            ),
            "mapping response does not match",
        ),
        (
            lambda value: value["component_audits"][0].update(
                {"observed_description": "The stone measures 7.2 mm."}
            ),
            "mapping response does not match",
        ),
    ],
)
def test_invalid_or_manufacturing_claimed_mapping_is_rejected(mutate, message):
    mapping = _mapping()
    mutate(mapping)

    with pytest.raises(SourceComponentAuditInvalid, match=message):
        audit_source_component_coverage(
            b"source-image",
            _coverage(),
            inspect=_TwoPassInspector(_inventory(), mapping),
        )


def test_blind_inventory_rejects_nonsequential_ids_and_cad_fields():
    inventory = _inventory()
    inventory["components"][0]["inventory_id"] = "blind.002"
    with pytest.raises(SourceComponentAuditInvalid, match="sequential"):
        audit_source_component_coverage(
            b"source-image",
            _coverage(),
            inspect=_TwoPassInspector(inventory, _mapping()),
        )

    inventory = _inventory()
    inventory["components"][0]["cad_spline"] = [[0, 0], [1, 1]]
    with pytest.raises(SourceComponentAuditInvalid, match="inventory response"):
        audit_source_component_coverage(
            b"source-image",
            _coverage(),
            inspect=_TwoPassInspector(inventory, _mapping()),
        )


def test_unresolved_component_cannot_receive_passing_audit():
    with pytest.raises(SourceComponentAuditInvalid, match="cannot pass"):
        audit_source_component_coverage(
            b"source-image",
            _coverage(unresolved=True),
            inspect=_TwoPassInspector(_inventory(), _mapping()),
        )


def test_failed_and_inconclusive_component_audits_remain_factory_blockers():
    audited = audit_source_component_coverage(
        b"source-image",
        _coverage(),
        inspect=_TwoPassInspector(
            _inventory(),
            _mapping(stone_verdict="fail", shoulder_verdict="inconclusive"),
        ),
    )

    codes = {
        (blocker.component_id, blocker.code)
        for blocker in source_component_factory_blockers(audited)
    }
    assert codes == {
        ("stone.center", "source_component_audit_failed"),
        ("assembly.shoulder", "source_component_audit_inconclusive"),
    }


def test_deterministic_setting_check_overrides_false_model_pass():
    coverage = SourceComponentCoverage(
        source_kind="designer_plate",
        components=(SourceVisibleComponent(
            component_id="setting.primary",
            source_view="plate_composite",
            source_description="Center stone in a full bezel setting.",
            source_confidence=0.8,
            canonical_spec_paths=("setting",),
        ),),
    )
    inventory = {"components": [{
        "inventory_id": "blind.001",
        "source_view": "plate_composite",
        "observed_description": "Center stone held by four visible prongs.",
        "confidence": 0.91,
    }]}
    mapping = {
        "component_audits": [{
            "component_id": "setting.primary",
            "verdict": "pass",
            "source_view": "plate_composite",
            "observed_description": "The setting is mapped.",
            "matched_inventory_ids": ["blind.001"],
        }],
        "inventory_accounting": [{
            "inventory_id": "blind.001",
            "coverage_component_ids": ["setting.primary"],
            "unmapped_reason": None,
        }],
    }

    audited = audit_source_component_coverage(
        b"source-image",
        coverage,
        inspect=_TwoPassInspector(inventory, mapping),
    )

    audit = audited.components[0].independent_audit
    assert audit is not None
    assert audit.verdict == "fail"
    assert "bezel" in audit.observed_description
    assert "prong" in audit.observed_description


def test_exact_spec_prong_count_overrides_generic_coverage_description(halo_spec):
    spec = Spec.model_validate({
        **halo_spec,
        "setting": {
            **halo_spec["setting"],
            "style": "6_prong_basket",
            "prong_count": 6,
        },
    })
    coverage = SourceComponentCoverage(
        source_kind="designer_plate",
        components=(SourceVisibleComponent(
            component_id="setting.primary",
            source_view="plate_composite",
            source_description="Raised prong basket supporting the center.",
            source_confidence=0.9,
            canonical_spec_paths=("setting",),
        ),),
    )
    inventory = {"components": [{
        "inventory_id": "blind.001",
        "source_view": "plate_composite",
        "observed_description": "Center stone held by four visible prongs.",
        "confidence": 0.94,
    }]}
    mapping = {
        "component_audits": [{
            "component_id": "setting.primary",
            "verdict": "pass",
            "source_view": "plate_composite",
            "observed_description": "The setting path represents the basket.",
            "matched_inventory_ids": ["blind.001"],
        }],
        "inventory_accounting": [{
            "inventory_id": "blind.001",
            "coverage_component_ids": ["setting.primary"],
            "unmapped_reason": None,
        }],
    }

    audited = audit_source_component_coverage(
        b"source-image",
        coverage,
        spec=spec,
        inspect=_TwoPassInspector(inventory, mapping),
    )

    audit = audited.components[0].independent_audit
    assert audit is not None
    assert audit.verdict == "fail"
    assert "says 6-prong" in audit.observed_description
    assert "says 4-prong" in audit.observed_description


def test_empty_source_has_specific_invalid_error_and_never_calls_provider():
    def inspect(_system: str, _image: bytes, _user_text: str) -> dict:
        raise AssertionError("provider must not be called")

    with pytest.raises(SourceComponentAuditInvalid, match="image bytes"):
        audit_source_component_coverage(b"", _coverage(), inspect=inspect)

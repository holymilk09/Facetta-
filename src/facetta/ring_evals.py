"""Versioned ring golden set and internal-release gate calculations."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Literal

from facetta.concept import DesignRead, complete_design
from facetta.creative_symmetry import with_jewelry_symmetry_contract
from facetta.json_types import JsonObject
from facetta.spec import Spec
from facetta.validation import validate_spec
from facetta.vocabulary import get_vocabulary


StartingPoint = Literal["spec_render", "imported_reference"]
RingTemplate = Literal[
    "solitaire_prong", "halo_prong", "leaf_shoulder_prong",
]
EditCategory = Literal[
    "center_shape",
    "center_identity",
    "band_geometry",
    "metal_color",
    "metal_material",
    "setting",
    "stone_inventory",
    "motif_shape",
    "presentation",
    "invalid_geometry",
]


@dataclass(frozen=True)
class RingGoldenCase:
    id: str
    center_cut: str
    center_species: str
    metal_color: Literal["yellow", "white", "rose"]
    halo: bool
    prong_count: Literal[4, 6]
    band_width_mm: float
    starting_point: StartingPoint
    factory_sheet_supported: bool = True
    template: RingTemplate | None = None

    @property
    def requires_reference(self) -> bool:
        """Whether the live case must exercise the reference-backed route."""
        return self.starting_point == "imported_reference"


RING_GOLDEN_CASES: tuple[RingGoldenCase, ...] = (
    RingGoldenCase(
        "round-solitaire-yellow-4-narrow", "round_brilliant", "diamond",
        "yellow", False, 4, 1.8, "spec_render"),
    RingGoldenCase(
        "oval-solitaire-white-6-wide", "oval_brilliant", "sapphire",
        "white", False, 6, 3.2, "imported_reference"),
    RingGoldenCase(
        "emerald-halo-rose-4-exact", "emerald_cut", "emerald",
        "rose", True, 4, 2.2, "spec_render"),
    RingGoldenCase(
        "cushion-halo-white-6-wide", "cushion", "ruby",
        "white", True, 6, 3.0, "imported_reference"),
    RingGoldenCase(
        "marquise-solitaire-yellow-4", "marquise", "diamond",
        "yellow", False, 4, 2.0, "spec_render",
        factory_sheet_supported=False),
    RingGoldenCase(
        "oval-halo-yellow-6-imported", "oval_brilliant", "sapphire",
        "yellow", True, 6, 2.4, "imported_reference"),
    RingGoldenCase(
        "round-leaf-yellow-4-imported", "round_brilliant", "diamond",
        "yellow", False, 4, 2.2, "imported_reference", True,
        "leaf_shoulder_prong"),
)


@dataclass(frozen=True)
class CanonicalRingEdit:
    id: str
    golden_case_id: str
    region: str
    instruction: str
    visual_only: bool = False
    expected_valid: bool = True
    category: EditCategory = "band_geometry"
    allowed_delta_prefixes: tuple[str, ...] = ()
    frozen_facts: tuple[str, ...] = ()
    requires_spec_delta: bool = True


CANONICAL_RING_EDITS: tuple[CanonicalRingEdit, ...] = (
    CanonicalRingEdit(
        "center-cut-shape", "oval-solitaire-white-6-wide",
        "the center stone and its prong seats",
        "change the oval brilliant center stone to an emerald cut while keeping "
        "the same face-up dimensions, species, color, orientation, and six-prong setting",
        category="center_shape",
        allowed_delta_prefixes=("stone.cut", "stone.carat"),
        frozen_facts=(
            "center-stone species, visible color, dimensions, and orientation",
            "six-prong count and setting style",
            "halo inventory, band, metal, camera, lighting, and background",
        )),
    CanonicalRingEdit(
        "center-species-color", "round-solitaire-yellow-4-narrow",
        "the center stone",
        "change the center stone to a vivid blue sapphire",
        category="center_identity",
        allowed_delta_prefixes=(
            "stone.species", "stone.color", "stone.carat"),
        frozen_facts=(
            "center-stone cut, dimensions, orientation, and setting",
            "band, metal, camera, lighting, and background",
        )),
    CanonicalRingEdit(
        "band-width", "oval-solitaire-white-6-wide", "the lower shank",
        "increase the lower shank band width from 3.2 mm to 3.8 mm (a visibly wider band)",
        category="band_geometry",
        allowed_delta_prefixes=("band.width_mm",),
        frozen_facts=(
            "inner ring diameter and band thickness",
            "center stone, setting, shoulders, metal, camera, lighting, and background",
        )),
    CanonicalRingEdit(
        "metal-color", "oval-halo-yellow-6-imported", "all metal surfaces",
        "change the metal to 18k rose gold",
        category="metal_color",
        allowed_delta_prefixes=("metal.color",),
        frozen_facts=(
            "every stone identity, cut, color, count, and position",
            "all ring geometry, setting, prongs, camera, lighting, and background",
        )),
    CanonicalRingEdit(
        "metal-material", "oval-solitaire-white-6-wide", "all metal surfaces",
        "change the 18k white gold construction to platinum",
        category="metal_material",
        allowed_delta_prefixes=(
            "metal.material", "metal.karat", "metal.color"),
        frozen_facts=(
            "every stone identity, cut, color, count, and position",
            "all ring geometry, setting, prongs, camera, lighting, and background",
        )),
    CanonicalRingEdit(
        "prong-setting", "oval-solitaire-white-6-wide", "the center setting",
        "change the center setting from six prongs to four prongs",
        category="setting",
        allowed_delta_prefixes=(
            "setting.style", "setting.prong_count"),
        frozen_facts=(
            "center-stone identity, dimensions, color, and orientation",
            "side-stone inventory, band, metal, camera, lighting, and background",
        )),
    CanonicalRingEdit(
        "halo-add", "round-solitaire-yellow-4-narrow",
        "the perimeter immediately around the center stone",
        "add one halo of exactly 12 round colorless diamonds around the center stone",
        category="stone_inventory",
        allowed_delta_prefixes=("template", "side_stones"),
        frozen_facts=(
            "center-stone identity, size, orientation, and setting",
            "band, metal, camera, lighting, and background",
        )),
    CanonicalRingEdit(
        "halo-remove", "emerald-halo-rose-4-exact", "the halo",
        "remove the complete diamond halo and leave the center setting as a solitaire",
        category="stone_inventory",
        allowed_delta_prefixes=("template", "side_stones"),
        frozen_facts=(
            "center-stone identity, size, orientation, and setting",
            "band, metal, camera, lighting, and background",
        )),
    CanonicalRingEdit(
        "halo-count", "emerald-halo-rose-4-exact", "the halo",
        "reduce the halo by exactly one stone",
        category="stone_inventory",
        allowed_delta_prefixes=("side_stones.0.count",),
        frozen_facts=(
            "halo stone species, cut, size, color, mount, and spacing pattern",
            "center stone, setting, band, metal, camera, lighting, and background",
        )),
    CanonicalRingEdit(
        "leaf-motif-shape", "round-leaf-yellow-4-imported",
        "the mirrored diamond leaf elements on both shoulders",
        with_jewelry_symmetry_contract(
            "reshape all 12 marquise diamond leaf elements into pear-cut diamond "
            "leaf elements without changing their count, dimensions, positions, "
            "or metalwork"
        ),
        category="motif_shape",
        allowed_delta_prefixes=(
            "side_stones.0.cut", "side_stones.0.carat"),
        frozen_facts=(
            "leaf count, dimensions, mirrored placement, and round pave inventory",
            "center stone, setting, lower shank, metal, camera, lighting, and background",
        )),
    CanonicalRingEdit(
        "intentional-shoulder-asymmetry", "round-leaf-yellow-4-imported",
        "the three outermost diamond leaf elements on the left shoulder only",
        with_jewelry_symmetry_contract(
            "intentionally reshape only the three outermost marquise diamond leaf "
            "elements on the left shoulder into pear-cut diamond leaves. Keep every "
            "element on the right shoulder unchanged. The unequal left/right motif "
            "treatment is deliberate designer-requested asymmetry"
        ),
        category="motif_shape",
        frozen_facts=(
            "all right-shoulder leaf elements and their marquise cuts",
            "all remaining leaf count, dimensions, positions, and metalwork",
            "center stone, setting, lower shank, metal, camera, lighting, and background",
        ),
        requires_spec_delta=False),
    CanonicalRingEdit(
        "background-only", "marquise-solitaire-yellow-4", "the background",
        "change only the background to warm ivory", visual_only=True,
        category="presentation",
        frozen_facts=("the complete validated ring specification",),
        requires_spec_delta=False),
    CanonicalRingEdit(
        "impossible-band-width", "round-solitaire-yellow-4-narrow", "the band",
        "set the band width to 20 mm", expected_valid=False,
        category="invalid_geometry"),
)


def _density_carat(spec: Spec) -> float:
    vocabulary = get_vocabulary()
    stone = spec.stone
    dimensions = stone.dimensions_mm
    return round(
        dimensions.length * dimensions.width * dimensions.depth
        * vocabulary.species(stone.species).sg
        * vocabulary.cut(stone.cut).shape_factor / 200,
        3,
    )


def _stone_carat(stone: dict) -> float:
    vocabulary = get_vocabulary()
    dimensions = stone["dimensions_mm"]
    return round(
        float(dimensions["length"])
        * float(dimensions["width"])
        * float(dimensions["depth"])
        * vocabulary.species(str(stone["species"])).sg
        * vocabulary.cut(str(stone["cut"])).shape_factor / 200,
        3,
    )


def _leaf_shoulder_inventory() -> list[dict]:
    groups = [
        {
            "species": "diamond",
            "cut": "marquise",
            "carat": 0.001,
            "dimensions_mm": {"length": 2.5, "width": 1.3, "depth": 0.8},
            "color": {"trade": "F", "gia": "colorless"},
            "count": 12,
            "position": "pave_leaves",
            "phenomena": [],
        },
        {
            "species": "diamond",
            "cut": "round_brilliant",
            "carat": 0.001,
            "dimensions_mm": {"length": 1.2, "width": 1.2, "depth": 0.73},
            "color": {"trade": "F", "gia": "colorless"},
            "count": 24,
            "position": "pave_leaves",
            "phenomena": [],
        },
    ]
    for group in groups:
        group["carat"] = _stone_carat(group)
    return groups


def _halo_inventory(count: int) -> list[dict]:
    group = {
        "species": "diamond",
        "cut": "round_brilliant",
        "carat": 0.001,
        "dimensions_mm": {"length": 1.3, "width": 1.3, "depth": 0.8},
        "color": {"trade": "F", "gia": "colorless"},
        "count": count,
        "position": "halo",
        "phenomena": [],
    }
    group["carat"] = _stone_carat(group)
    return [group]


def build_ring_golden_spec(case: RingGoldenCase) -> Spec:
    read_cut = ("oval_brilliant" if case.center_cut == "marquise"
                else case.center_cut)
    spec, _ = complete_design(DesignRead(
        jewelry_type="ring",
        halo=case.halo,
        species=case.center_species,
        cut=read_cut,
        center_length_mm=10.0 if read_cut != "round_brilliant" else 7.5,
        center_width_mm=7.5,
        metal_material="gold",
        metal_color=case.metal_color,
        setting_style=f"prong_{case.prong_count}",
    ), brief=f"golden evaluation case {case.id}")
    spec.band.width_mm = case.band_width_mm
    if case.center_cut == "marquise":
        spec.stone.cut = "marquise"
        spec.stone.carat = _density_carat(spec)
    if case.template == "leaf_shoulder_prong":
        raw = spec.model_dump(mode="json")
        raw["template"] = case.template
        raw["side_stones"] = _leaf_shoulder_inventory()
        spec = Spec.model_validate(raw)
    result = validate_spec(spec, get_vocabulary())
    if not result.ok:
        details = "; ".join(str(issue.as_detail()) for issue in result.issues)
        raise ValueError(f"invalid ring golden case '{case.id}': {details}")
    return result.spec


def apply_canonical_ring_edit(
    spec: Spec, edit: CanonicalRingEdit,
) -> tuple[Spec | None, list[JsonObject]]:
    data = spec.model_dump(mode="json")
    if edit.id == "center-species-color":
        data["stone"]["species"] = "sapphire"
        data["stone"]["color"] = {
            "trade": "Royal Blue",
            "gia": "vivid blue, medium-dark tone, strong saturation",
        }
        candidate = Spec.model_validate(data)
        candidate.stone.carat = _density_carat(candidate)
    elif edit.id == "center-cut-shape":
        data["stone"]["cut"] = "emerald_cut"
        candidate = Spec.model_validate(data)
        candidate.stone.carat = _density_carat(candidate)
    elif edit.id == "band-width":
        data["band"]["width_mm"] = round(
            float(data["band"]["width_mm"]) + 0.6, 1)
        candidate = Spec.model_validate(data)
    elif edit.id == "metal-color":
        data["metal"] = {
            "material": "gold", "karat": 18,
            "color": "rose", "finish": data["metal"].get("finish"),
        }
        candidate = Spec.model_validate(data)
    elif edit.id == "metal-material":
        data["metal"] = {
            "material": "platinum", "karat": None,
            "color": None, "finish": data["metal"].get("finish"),
        }
        candidate = Spec.model_validate(data)
    elif edit.id == "prong-setting":
        count = 6 if int(data["setting"].get("prong_count") or 4) == 4 else 4
        data["setting"]["prong_count"] = count
        data["setting"]["style"] = f"{count}_prong_basket"
        candidate = Spec.model_validate(data)
    elif edit.id == "halo-count":
        if not data["side_stones"]:
            return None, [{
                "code": "halo_required",
                "message": "halo-count edit requires a halo golden case",
            }]
        data["side_stones"][0]["count"] = max(
            1, int(data["side_stones"][0]["count"]) - 1)
        candidate = Spec.model_validate(data)
    elif edit.id == "halo-add":
        data["template"] = "halo_prong"
        data["side_stones"] = _halo_inventory(12)
        candidate = Spec.model_validate(data)
    elif edit.id == "halo-remove":
        data["template"] = "solitaire_prong"
        data["side_stones"] = []
        candidate = Spec.model_validate(data)
    elif edit.id == "leaf-motif-shape":
        if (not data["side_stones"]
                or data["side_stones"][0].get("position") != "pave_leaves"):
            return None, [{
                "code": "leaf_inventory_required",
                "message": "leaf-motif edit requires a pave-leaves golden case",
            }]
        data["side_stones"][0]["cut"] = "pear"
        data["side_stones"][0]["carat"] = _stone_carat(
            data["side_stones"][0])
        candidate = Spec.model_validate(data)
    elif edit.id == "intentional-shoulder-asymmetry":
        # The canonical ring schema stores a repeated inventory group, not
        # per-side visual variants.  Keep the validated product facts fixed;
        # the reviewed source region and explicit instruction authorize this
        # image-only structural asymmetry for the temporary candidate.
        candidate = Spec.model_validate(data)
    elif edit.id == "background-only":
        candidate = Spec.model_validate(data)
    elif edit.id == "impossible-band-width":
        return None, [{
            "code": "invalid_band_width",
            "message": "20 mm exceeds the validated ring-band range",
        }]
    else:
        raise KeyError(f"unknown canonical ring edit '{edit.id}'")
    result = validate_spec(candidate, get_vocabulary())
    return ((result.spec if result.ok else None),
            [issue.as_detail() for issue in result.issues])


def evaluate_release_gates(
    rows: list[JsonObject],
    *,
    persistence_evidence: JsonObject | None = None,
) -> JsonObject:
    """Calculate gates without treating missing persistence proof as success.

    The image-engine harness does not itself call the project APIs. Evidence
    that rejected candidates never became active assets must therefore come
    from a named canonical-API integration result. Omitting that evidence is
    an honest failing gate, not an implicit zero.
    """
    render_rows = [row for row in rows if row.get("kind") == "render"]
    edit_rows = [row for row in rows if row.get("kind") == "edit"]
    valid_edit_rows = [
        row for row in edit_rows if row.get("expected_valid", True)]
    hard_passes = sum(bool(row.get("hard_gate_pass")) for row in render_rows)
    hard_rate = hard_passes / len(render_rows) if render_rows else 0.0
    render_scores = [float(row["score"]) for row in render_rows
                     if isinstance(row.get("score"), (int, float))]
    edit_scores = [float(row["score"]) for row in edit_rows
                   if isinstance(row.get("score"), (int, float))]
    all_edits = bool(valid_edit_rows) and all(
        bool(row.get("applied")) and int(row.get("attempts") or 99) <= 3
        for row in valid_edit_rows)
    no_major_drift = bool(valid_edit_rows) and all(
        row.get("severity") != "major" for row in valid_edit_rows)
    evidence = persistence_evidence or {}
    rejected_count = evidence.get("rejected_active_asset_count")
    persistence_verified = (
        evidence.get("verified") is True
        and isinstance(evidence.get("method"), str)
        and bool(str(evidence.get("method")).strip())
        and isinstance(evidence.get("result_set"), str)
        and bool(str(evidence.get("result_set")).strip())
        and type(rejected_count) is int
        and rejected_count >= 0
    )
    no_rejected_persisted = persistence_verified and rejected_count == 0
    render_mean = mean(render_scores) if render_scores else 0.0
    edit_mean = mean(edit_scores) if edit_scores else 0.0
    gates: JsonObject = {
        "hard_gate_pass_rate": round(hard_rate, 4),
        "hard_gate_pass": hard_rate >= 0.90,
        "mean_spec_render_conformance": round(render_mean, 2),
        "spec_render_conformance_pass": render_mean >= 85,
        "all_localized_edits_within_three_attempts": all_edits,
        "mean_edit_fidelity": round(edit_mean, 2),
        "edit_fidelity_pass": edit_mean >= 90,
        "zero_major_unintended_drift": no_major_drift,
        "persistence_evidence_verified": persistence_verified,
        "zero_rejected_candidates_persisted": no_rejected_persisted,
    }
    gates["automated_gates_pass"] = all((
        gates["hard_gate_pass"],
        gates["spec_render_conformance_pass"],
        gates["all_localized_edits_within_three_attempts"],
        gates["edit_fidelity_pass"],
        gates["zero_major_unintended_drift"],
        gates["persistence_evidence_verified"],
        gates["zero_rejected_candidates_persisted"],
    ))
    gates["blocking_enabled"] = False
    gates["blocking_note"] = (
        "GIA-trained cofounder false-positive/false-negative review is required "
        "before these gates become blocking.")
    return gates

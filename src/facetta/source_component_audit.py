"""Independent, blind-first audit of imported-source component coverage.

The first vision call sees neither the specification nor any expected
component list. A second call reconciles that blind inventory with the exact
coverage IDs, canonical paths, and raster-visible facts from the validated
specification. The result is a new frozen coverage value bound to the exact
visual-spec hash; the input values are unchanged.

The audit proves only visible component accounting.  It never estimates a
dimension and never creates a CAD/manufacturing contour.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from facetta.image_agent.vision import vision_json
from facetta.image_identity import spec_visual_hash
from facetta.json_types import JsonValue
from facetta.spec import Spec
from facetta.source_component_coverage import (
    IndependentComponentAudit,
    SourceComponentCoverage,
    SourceView,
    SourceVisibleComponent,
    VisibleComponentId,
)


AUDITOR_VERSION = "skeptical-source-component-audit.v4"

ComponentAuditInspector: TypeAlias = Callable[[str, bytes, str], dict]
ComponentAuditEvidenceSink: TypeAlias = Callable[[dict[str, object]], None]


class SourceComponentAuditError(RuntimeError):
    """Base error for independent source-component auditing."""


class SourceComponentAuditUnavailable(SourceComponentAuditError):
    """The independent vision provider could not complete an audit pass."""

    def __init__(
        self,
        message: str,
        *,
        debug_evidence: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.debug_evidence = debug_evidence


class SourceComponentAuditInvalid(SourceComponentAuditError):
    """The provider returned incomplete, contradictory, or unsafe evidence."""

    def __init__(
        self,
        message: str,
        *,
        debug_evidence: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.debug_evidence = debug_evidence


class _AuditResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


BlindInventoryId: TypeAlias = Annotated[
    str,
    Field(strict=True, pattern=r"^blind\.(?:00[1-9]|0[1-9][0-9]|[1-9][0-9]{2})$"),
]


_MEASUREMENT_CLAIM = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:mm|millimeters?|cm|centimeters?|"
    r"inches?|carats?|cts?)\b",
    re.IGNORECASE,
)
_CAD_CLAIM = re.compile(
    r"\b(?:cad|nurbs|b-?rep|stl|step|iges|manufacturing spline|"
    r"toolpath|mesh coordinates?)\b",
    re.IGNORECASE,
)


def _reject_manufacturing_claim(value: str) -> str:
    if value != value.strip() or not value:
        raise ValueError("audit text must be non-blank and trimmed")
    if _MEASUREMENT_CLAIM.search(value):
        raise ValueError("component audit cannot infer physical measurements")
    if _CAD_CLAIM.search(value):
        raise ValueError("component audit cannot infer CAD or manufacturing geometry")
    return value


class _BlindInventoryItem(_AuditResponse):
    inventory_id: BlindInventoryId
    source_view: SourceView
    observed_description: Annotated[
        str,
        Field(strict=True, min_length=1, max_length=1200),
    ]
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]

    _validate_description = field_validator("observed_description")(
        _reject_manufacturing_claim
    )


class _BlindInventoryPass(_AuditResponse):
    components: Annotated[
        tuple[_BlindInventoryItem, ...],
        Field(min_length=1, max_length=999),
    ]


class _ComponentAuditResult(_AuditResponse):
    component_id: VisibleComponentId
    verdict: Literal["pass", "fail", "inconclusive"]
    source_view: SourceView
    observed_description: Annotated[
        str,
        Field(strict=True, min_length=1, max_length=1000),
    ]
    matched_inventory_ids: tuple[BlindInventoryId, ...] = ()

    _validate_description = field_validator("observed_description")(
        _reject_manufacturing_claim
    )


class _InventoryAccounting(_AuditResponse):
    inventory_id: BlindInventoryId
    coverage_component_ids: tuple[VisibleComponentId, ...] = ()
    unmapped_reason: Annotated[
        str,
        Field(strict=True, min_length=1, max_length=1000),
    ] | None = None

    @field_validator("unmapped_reason")
    @classmethod
    def validate_reason(cls, value: str | None) -> str | None:
        return None if value is None else _reject_manufacturing_claim(value)


class _MappingPass(_AuditResponse):
    component_audits: Annotated[
        tuple[_ComponentAuditResult, ...],
        Field(min_length=1),
    ]
    inventory_accounting: Annotated[
        tuple[_InventoryAccounting, ...],
        Field(min_length=1),
    ]


_BLIND_INVENTORY_SYSTEM = """\
You are the blind first pass in an independent fine-jewelry source audit.
Inventory every visually distinct MAJOR jewelry component visible in this one
source image. You have not been given a specification or an expected component
list. Do not guess what another reader may have recorded.

Major components include the body/shank/chain, center stone, each visibly
distinct side-stone or halo group, setting/head, clasp/bail/pendant, and any
structural shoulder, gallery, motif, or material zone whose omission would
change the design. Group repeated like-for-like stones when they form one
visible group. Do not inventory lighting, shadows, labels, dimension arrows, or
background objects.

Report only visible identity, form, arrangement, and count when the count is
actually visible. Never estimate millimeters, carats, physical dimensions, CAD,
splines, meshes, or manufacturing geometry. Return JSON exactly:
{"components":[{"inventory_id":"blind.001","source_view":"front|top|side|three_quarter|detail|plate_composite|unspecified","observed_description":"...","confidence":0.0}]}
Use sequential IDs blind.001, blind.002, and so on. Output JSON only."""


_MAPPING_SYSTEM = """\
You are the independent second pass in a fine-jewelry source-component audit.
You receive the source image, a BLIND inventory produced without expectations,
and the exact component-coverage record to test. That record includes
mapped_visible_spec_facts for each canonical path. Compare the image and blind
inventory against every coverage component ID, source description, canonical
spec path, and raster-visible fact. Do not add assumptions from jewelry
convention.

A component passes only when the visible source component is genuinely and
accurately accounted for by its stated canonical paths. Use fail for a clear
omission or mismatch and inconclusive when the source view cannot prove the
mapping. A component with an unresolved reason cannot pass.
Path names alone are never proof. When visible, exact stone/group counts, cut
family, species, visible color, metal color/material, setting family, and prong
count must agree with mapped_visible_spec_facts. If a supplied fact is not
visually assessable from this source view, use inconclusive rather than
silently accepting it. Ignore physical measurements and carat values because
raster evidence cannot prove them.
Do not echo the supplied description as evidence: if the blind inventory says
prongs while coverage says bezel (or gives a different prong count), the
setting component must fail.

Account for every blind inventory ID: map it to all exact coverage component
IDs that capture it, or provide an unmapped reason. A passing component must cite at least one blind
inventory ID. The two directions of the mapping must agree exactly.

A blind item may describe a whole assembly while more specific blind items
describe its center stone, halo, head, or shank. In that case either cite the
whole-assembly item only for the aggregate coverage component in BOTH
directions, or list the same aggregate-plus-constituent component IDs in BOTH
directions. Never return different partial constituent lists for the two
directions. Repeated like-for-like stones should remain one blind group rather
than being split into invented individual identities.

Do not infer or validate millimeters, carats, dimensions, CAD, contours,
splines, meshes, or manufacturability. Return JSON exactly:
{"component_audits":[{"component_id":"...","verdict":"pass|fail|inconclusive","source_view":"front|top|side|three_quarter|detail|plate_composite|unspecified","observed_description":"...","matched_inventory_ids":["blind.001"]}],"inventory_accounting":[{"inventory_id":"blind.001","coverage_component_ids":["..."],"unmapped_reason":null}]}
Return exactly one component_audit per supplied coverage component and exactly
one inventory_accounting item per supplied blind item. Output JSON only."""


def _setting_signature(text: str) -> tuple[str | None, int | None]:
    lowered = text.lower().replace("-", " ")
    style = "bezel" if "bezel" in lowered else (
        "prong" if "prong" in lowered else None)
    count = None
    numeric = re.search(
        r"\b([2-8])(?:\s+[a-z]+){0,2}\s+prongs?\b",
        lowered,
    )
    if numeric:
        count = int(numeric.group(1))
    else:
        for word, value in (("four", 4), ("six", 6)):
            if re.search(
                rf"\b{word}(?:\s+[a-z]+){{0,2}}\s+prongs?\b",
                lowered,
            ):
                count = value
                break
    return style, count


def _setting_conflict(
    component: SourceVisibleComponent,
    result: _ComponentAuditResult,
    inventory_by_id: dict[str, _BlindInventoryItem],
    spec: Spec | None = None,
) -> str | None:
    """Catch a model accepting a bezel/prong contradiction in its own evidence."""
    if component.component_id != "setting.primary" or result.verdict != "pass":
        return None
    expected_style, expected_count = _setting_signature(
        component.source_description)
    if spec is not None and any(
        path == "setting" or path.startswith("setting.")
        for path in component.canonical_spec_paths
    ):
        setting_style = spec.setting.style.lower()
        expected_style = (
            "bezel" if "bezel" in setting_style
            else "prong" if "prong" in setting_style else expected_style
        )
        expected_count = spec.setting.prong_count or expected_count
    blind_text = " ".join(
        inventory_by_id[item_id].observed_description
        for item_id in result.matched_inventory_ids
    )
    observed_style, observed_count = _setting_signature(blind_text)
    if (expected_style is not None and observed_style is not None
            and expected_style != observed_style):
        return (
            f"source description says {expected_style}, while the blind "
            f"inventory says {observed_style}"
        )
    if (expected_count is not None and observed_count is not None
            and expected_count != observed_count):
        return (
            f"source description says {expected_count}-prong, while the blind "
            f"inventory says {observed_count}-prong"
        )
    return None


def _setting_evidence_gap(
    component: SourceVisibleComponent,
    result: _ComponentAuditResult,
    inventory_by_id: dict[str, _BlindInventoryItem],
    spec: Spec | None,
) -> str | None:
    """Require the blind pass—not the spec-aware pass—to state prong count."""
    if spec is None or result.verdict != "pass":
        return None
    if not any(
        path == "setting" or path.startswith("setting.")
        for path in component.canonical_spec_paths
    ):
        return None
    expected_count = spec.setting.prong_count
    if expected_count is None:
        return None
    blind_text = " ".join(
        inventory_by_id[item_id].observed_description
        for item_id in result.matched_inventory_ids
    )
    _, observed_count = _setting_signature(blind_text)
    if observed_count is None:
        return (
            f"the specification says {expected_count}-prong, but the blind "
            "inventory did not state an assessable prong count"
        )
    return None


def _run_pass(
    inspect: ComponentAuditInspector,
    *,
    system: str,
    source_image: bytes,
    user_text: str,
    pass_name: str,
) -> dict:
    try:
        result = inspect(system, source_image, user_text)
    except SourceComponentAuditError:
        raise
    except Exception as exc:
        raise SourceComponentAuditUnavailable(
            f"independent source-component {pass_name} pass unavailable"
        ) from exc
    if not isinstance(result, dict):
        raise SourceComponentAuditInvalid(
            f"independent source-component {pass_name} pass returned non-object JSON"
        )
    return result


def _validate_blind_inventory(raw: dict) -> _BlindInventoryPass:
    try:
        inventory = _BlindInventoryPass.model_validate(raw)
    except ValidationError as exc:
        raise SourceComponentAuditInvalid(
            "blind inventory response does not match the audit contract"
        ) from exc

    expected_ids = tuple(
        f"blind.{index:03d}" for index in range(1, len(inventory.components) + 1)
    )
    actual_ids = tuple(item.inventory_id for item in inventory.components)
    if actual_ids != expected_ids:
        raise SourceComponentAuditInvalid(
            "blind inventory IDs must be unique, sequential, and ordered"
        )
    return inventory


_NON_RASTER_FACT_KEYS = {
    "carat",
    "dimensions_mm",
    "depth_pct",
    "table_pct",
    "girdle",
    "culet",
    "prong_tip_mm",
    "gallery_height_mm",
    "width_mm",
    "thickness_mm",
    "length_mm",
    "geometry",
    "production",
}


def _raster_visible_value(value: JsonValue) -> JsonValue:
    if isinstance(value, dict):
        return {
            key: _raster_visible_value(item)
            for key, item in value.items()
            if key not in _NON_RASTER_FACT_KEYS and item is not None
        }
    if isinstance(value, list):
        return [_raster_visible_value(item) for item in value]
    return value


_INDEXED_PATH = re.compile(r"^([a-z][a-z0-9_]*)\[([^\]]+)\](?:\.(.*))?$")


def _value_at_path(spec: Spec, path: str) -> JsonValue | None:
    value: object = spec.model_dump(mode="json")
    segments = path.split(".")
    index = 0
    while index < len(segments):
        segment = segments[index]
        indexed = _INDEXED_PATH.match(segment)
        if indexed:
            root, key, inline_tail = indexed.groups()
            if not isinstance(value, dict) or root not in value:
                return None
            value = value[root]
            if isinstance(value, list):
                if key.isdigit():
                    if int(key) >= len(value):
                        return None
                    value = value[int(key)]
                else:
                    value = next(
                        (
                            item
                            for item in value
                            if isinstance(item, dict)
                            and item.get("element_id") == key
                        ),
                        None,
                    )
                    if value is None:
                        return None
            elif isinstance(value, dict):
                elements = value.get("elements")
                if not isinstance(elements, list):
                    return None
                value = next(
                    (
                        item
                        for item in elements
                        if isinstance(item, dict)
                        and item.get("element_id") == key
                    ),
                    None,
                )
                if value is None:
                    return None
            else:
                return None
            if inline_tail:
                segments[index:index + 1] = inline_tail.split(".")
                continue
        else:
            if not isinstance(value, dict) or segment not in value:
                return None
            value = value[segment]
        index += 1
    if isinstance(value, (dict, list, str, int, float, bool)) or value is None:
        return _raster_visible_value(value)
    return None


def _coverage_payload(
    coverage: SourceComponentCoverage,
    spec: Spec | None,
) -> dict:
    payload = {
        "source_kind": coverage.source_kind,
        "components": [
            {
                "component_id": item.component_id,
                "source_view": item.source_view,
                "source_description": item.source_description,
                "canonical_spec_paths": list(item.canonical_spec_paths),
                "unresolved_reason": item.unresolved_reason,
            }
            for item in coverage.components
        ],
    }
    if spec is not None:
        payload["audited_spec_visual_hash"] = spec_visual_hash(spec)
        for item, component_payload in zip(
            coverage.components,
            payload["components"],
            strict=True,
        ):
            component_payload["mapped_visible_spec_facts"] = {
                path: _value_at_path(spec, path)
                for path in item.canonical_spec_paths
            }
    return payload


_COUNT_WORDS = {
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "twenty-one": 21,
    "twenty-two": 22,
    "twenty-three": 23,
    "twenty-four": 24,
    "twenty-five": 25,
    "twenty-six": 26,
    "twenty-seven": 27,
    "twenty-eight": 28,
    "twenty-nine": 29,
    "thirty": 30,
}
_COUNT_TOKEN = rf"(?:[2-9]|[1-9][0-9]|{'|'.join(_COUNT_WORDS)})"
_REPEATED_STONE_COUNT_PATTERNS = (
    re.compile(
        rf"\b({_COUNT_TOKEN})\s+(?:(?:small|round|accent|side|halo|pav[eé]|melee|diamond|gem|colored|colourless|colorless)\s+){{0,5}}(?:stones?|diamonds?|gems?|melee)\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:halo|surround|cluster|row|group)\s+(?:of|with|containing)\s+({_COUNT_TOKEN})\b",
        re.IGNORECASE,
    ),
)


def _count_values(value: JsonValue | None) -> tuple[int, ...]:
    values: list[int] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "count" and isinstance(item, int) and not isinstance(item, bool):
                values.append(item)
            else:
                values.extend(_count_values(item))
    elif isinstance(value, list):
        for item in value:
            values.extend(_count_values(item))
    return tuple(values)


def _observed_repeated_stone_counts(text: str) -> tuple[int, ...]:
    values: list[int] = []
    for pattern in _REPEATED_STONE_COUNT_PATTERNS:
        for match in pattern.finditer(text.lower()):
            token = match.group(1)
            values.append(int(token) if token.isdigit() else _COUNT_WORDS[token])
    return tuple(dict.fromkeys(values))


def _repeated_stone_count_conflict(
    component: SourceVisibleComponent,
    result: _ComponentAuditResult,
    inventory_by_id: dict[str, _BlindInventoryItem],
    spec: Spec | None,
) -> str | None:
    """Reject a model pass that contradicts an assessable repeated-stone count."""
    if spec is None or result.verdict != "pass":
        return None
    if not (
        component.component_id.startswith("stone.group.")
        or re.search(r"\b(?:halo|side|accent|pav[eé]|melee|cluster)\b", component.source_description, re.IGNORECASE)
    ):
        return None
    expected = tuple(dict.fromkeys(
        count
        for path in component.canonical_spec_paths
        for count in _count_values(_value_at_path(spec, path))
        if count > 1
    ))
    if not expected:
        return None
    blind_text = " ".join(
        inventory_by_id[item_id].observed_description
        for item_id in result.matched_inventory_ids
    )
    observed = _observed_repeated_stone_counts(blind_text)
    if observed and not set(expected).intersection(observed):
        return (
            "validated specification says repeated-stone count "
            f"{', '.join(map(str, expected))}, while blind source evidence says "
            f"{', '.join(map(str, observed))}"
        )
    return None


def _repeated_stone_count_evidence_gap(
    component: SourceVisibleComponent,
    result: _ComponentAuditResult,
    inventory_by_id: dict[str, _BlindInventoryItem],
    spec: Spec | None,
) -> str | None:
    """Require exact repeated-stone count to originate in the blind pass."""
    if spec is None or result.verdict != "pass":
        return None
    if not (
        component.component_id.startswith("stone.group.")
        or re.search(
            r"\b(?:halo|side|accent|pav[eé]|melee|cluster)\b",
            component.source_description,
            re.IGNORECASE,
        )
    ):
        return None
    expected = tuple(dict.fromkeys(
        count
        for path in component.canonical_spec_paths
        for count in _count_values(_value_at_path(spec, path))
        if count > 1
    ))
    if not expected:
        return None
    blind_text = " ".join(
        inventory_by_id[item_id].observed_description
        for item_id in result.matched_inventory_ids
    )
    if not _observed_repeated_stone_counts(blind_text):
        return (
            "the specification says repeated-stone count "
            f"{', '.join(map(str, expected))}, but the blind inventory did "
            "not state an assessable repeated-stone count"
        )
    return None


def _white_metal_material_evidence_gap(
    component: SourceVisibleComponent,
    result: _ComponentAuditResult,
    inventory_by_id: dict[str, _BlindInventoryItem],
    spec: Spec | None,
) -> str | None:
    """Do not turn white-metal appearance into a false alloy contradiction.

    A raster can distinguish yellow/rose from white metal, but cannot prove
    platinum versus silver versus white gold. A model that reports a silver-
    colored body against a platinum spec therefore needs designer confirmation,
    not a hard mismatch. This only downgrades an otherwise failed same-color
    comparison; an actual visible color contradiction remains a failure.
    """
    if (
        spec is None
        or spec.metal is None
        or component.component_id != "metal.body"
        or result.verdict != "fail"
    ):
        return None
    expected_white = (
        spec.metal.material in {"platinum", "silver"}
        or (spec.metal.material == "gold" and spec.metal.color == "white")
    )
    if not expected_white:
        return None
    evidence = " ".join([
        result.observed_description,
        *(
            inventory_by_id[item_id].observed_description
            for item_id in result.matched_inventory_ids
        ),
    ]).lower()
    visible_white = bool(re.search(
        r"\b(?:white[ -]?metal|silver(?:y|[ -]?tone|[ -]?colored)?|"
        r"platinum[ -]?tone|cool white)\b",
        evidence,
    ))
    visible_nonwhite = bool(re.search(
        r"\b(?:yellow gold|yellow[ -]?metal|rose gold|pink[ -]?metal)\b",
        evidence,
    ))
    if visible_white and not visible_nonwhite:
        return (
            "the source establishes a white-metal appearance but cannot prove "
            f"the exact {spec.metal.material} alloy"
        )
    return None


_DISTINCTIVE_FORM_PATTERN = re.compile(
    r"\b(?:asymmetr(?:ic|ical)|vine|branch(?:ing)?|floral|botanical|"
    r"leaf[ -]?motif|ribbon|serpentine|octopus|tentacle|sculptural|"
    r"figurative|organic openwork)\b",
    re.IGNORECASE,
)


def _distinctive_form_mapping_conflict(
    component: SourceVisibleComponent,
    result: _ComponentAuditResult,
    inventory_by_id: dict[str, _BlindInventoryItem],
) -> str | None:
    """A generic template ID cannot encode a distinctive visible topology."""
    if (
        component.component_id != "assembly.primary"
        or any(path.startswith("design_form.elements[")
               for path in component.canonical_spec_paths)
    ):
        return None
    evidence = " ".join([
        component.source_description,
        result.observed_description,
        *(
            inventory_by_id[item_id].observed_description
            for item_id in result.matched_inventory_ids
        ),
    ])
    if _DISTINCTIVE_FORM_PATTERN.search(evidence):
        return (
            "distinctive visible topology is mapped only to a generic template; "
            "a stable design_form element must represent the confirmed form"
        )
    return None


def _is_aggregate_component(component: SourceVisibleComponent) -> bool:
    """Whether a coverage record intentionally represents a whole assembly.

    Component IDs alone are not sufficient: ``assembly.shoulder`` can be one
    local form rather than the whole piece.  The canonical aggregate paths are
    the proof that overlap with individual visible members is intentional.
    """
    return any(
        path == "template"
        or path == "composition"
        or path.startswith("composition.")
        for path in component.canonical_spec_paths
    )


def _paths_overlap(left: str, right: str) -> bool:
    return (
        left == right
        or left.startswith(right + ".")
        or right.startswith(left + ".")
    )


_COMPOSITE_OBSERVATION_PATTERNS = (
    re.compile(r"\b(?:center stone|center gem|solitaire)\b", re.IGNORECASE),
    re.compile(r"\b(?:halo|side stones?|accent stones?|pav[eé])\b", re.IGNORECASE),
    re.compile(
        r"\b(?:setting|head|gallery|basket|prongs?|bezel|mount)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:shank|band|chain|bracelet|bangle)\b", re.IGNORECASE),
    re.compile(r"\b(?:metal|gold|silver|platinum)\b", re.IGNORECASE),
    re.compile(r"\b(?:pendant|bail|clasp)\b", re.IGNORECASE),
    re.compile(r"\b(?:shoulders?|motif|ornament|cluster)\b", re.IGNORECASE),
)
_WHOLE_ASSEMBLY_OBSERVATION = re.compile(
    r"\b(?:whole|complete|entire)\s+(?:ring|jewel(?:ry)?|piece|assembly)\b",
    re.IGNORECASE,
)


def _is_composite_observation(item: _BlindInventoryItem) -> bool:
    description = item.observed_description
    if _WHOLE_ASSEMBLY_OBSERVATION.search(description):
        return True
    matched_categories = sum(
        bool(pattern.search(description))
        for pattern in _COMPOSITE_OBSERVATION_PATTERNS
    )
    return matched_categories >= 2


def _is_legitimate_aggregate_overlap(
    forward_ids: set[str],
    reverse_ids: set[str],
    *,
    coverage_by_id: dict[str, SourceVisibleComponent],
    inventory_item: _BlindInventoryItem,
) -> bool:
    """Recognize only aggregate/member direction-list omissions.

    The second pass sometimes lists ``assembly.primary`` plus its members in
    one direction and only the aggregate (or only the already-shared members)
    in the other.  A subset/superset relation is safe to canonicalize when the
    union contains a component mapped to an actual aggregate spec path.

    Crossing lists remain contradictory.  For example
    ``{assembly, center}`` versus ``{assembly, halo}`` is not normalized.  Nor
    are two non-aggregate identities that happen to share one blind item.
    """
    if not forward_ids or not reverse_ids:
        return False
    if not (forward_ids < reverse_ids or reverse_ids < forward_ids):
        return False
    if not _is_composite_observation(inventory_item):
        return False

    combined = forward_ids | reverse_ids
    aggregate_ids = {
        component_id
        for component_id in combined
        if _is_aggregate_component(coverage_by_id[component_id])
    }
    if not aggregate_ids:
        return False

    # Two different non-aggregate coverage identities for the same canonical
    # object are not "members" of an aggregate; they are competing mappings.
    member_components = [
        coverage_by_id[component_id]
        for component_id in combined - aggregate_ids
    ]
    for index, left in enumerate(member_components):
        for right in member_components[index + 1:]:
            if any(
                _paths_overlap(left_path, right_path)
                for left_path in left.canonical_spec_paths
                for right_path in right.canonical_spec_paths
            ):
                return False
    return True


def _validate_mapping(
    raw: dict,
    *,
    inventory: _BlindInventoryPass,
    coverage: SourceComponentCoverage,
) -> _MappingPass:
    try:
        mapping = _MappingPass.model_validate(raw)
    except ValidationError as exc:
        raise SourceComponentAuditInvalid(
            "mapping response does not match the audit contract"
        ) from exc

    inventory_ids = tuple(item.inventory_id for item in inventory.components)
    coverage_ids = tuple(item.component_id for item in coverage.components)

    audit_ids = tuple(item.component_id for item in mapping.component_audits)
    if len(set(audit_ids)) != len(audit_ids) or set(audit_ids) != set(coverage_ids):
        raise SourceComponentAuditInvalid(
            "mapping must audit every exact coverage component ID once"
        )

    accounting_ids = tuple(item.inventory_id for item in mapping.inventory_accounting)
    if (
        len(set(accounting_ids)) != len(accounting_ids)
        or set(accounting_ids) != set(inventory_ids)
    ):
        raise SourceComponentAuditInvalid(
            "mapping must account for every exact blind inventory ID once"
        )

    inventory_id_set = set(inventory_ids)
    inventory_by_id = {
        item.inventory_id: item for item in inventory.components
    }
    coverage_id_set = set(coverage_ids)
    coverage_by_id = {item.component_id: item for item in coverage.components}
    audit_by_id = {item.component_id: item for item in mapping.component_audits}

    for audit in mapping.component_audits:
        if len(set(audit.matched_inventory_ids)) != len(audit.matched_inventory_ids):
            raise SourceComponentAuditInvalid(
                f"{audit.component_id} repeats a blind inventory ID"
            )
        if not set(audit.matched_inventory_ids).issubset(inventory_id_set):
            raise SourceComponentAuditInvalid(
                f"{audit.component_id} references an unknown blind inventory ID"
            )
        if audit.verdict == "pass" and not audit.matched_inventory_ids:
            raise SourceComponentAuditInvalid(
                f"passing component {audit.component_id} has no blind evidence"
            )
        if (
            coverage_by_id[audit.component_id].unresolved_reason is not None
            and audit.verdict == "pass"
        ):
            raise SourceComponentAuditInvalid(
                f"unresolved component {audit.component_id} cannot pass"
            )

    resolved_by_inventory: dict[str, set[str]] = {}
    for accounting in mapping.inventory_accounting:
        if len(set(accounting.coverage_component_ids)) != len(
            accounting.coverage_component_ids
        ):
            raise SourceComponentAuditInvalid(
                f"{accounting.inventory_id} repeats a coverage component ID"
            )
        if not set(accounting.coverage_component_ids).issubset(coverage_id_set):
            raise SourceComponentAuditInvalid(
                f"{accounting.inventory_id} references an unknown coverage component ID"
            )
        is_mapped = bool(accounting.coverage_component_ids)
        has_reason = accounting.unmapped_reason is not None
        if is_mapped == has_reason:
            raise SourceComponentAuditInvalid(
                f"{accounting.inventory_id} must be mapped or explicitly unmapped"
            )

        reverse_ids = {
            component_id
            for component_id, audit in audit_by_id.items()
            if accounting.inventory_id in audit.matched_inventory_ids
        }
        forward_ids = set(accounting.coverage_component_ids)
        if reverse_ids != forward_ids:
            if not _is_legitimate_aggregate_overlap(
                forward_ids,
                reverse_ids,
                coverage_by_id=coverage_by_id,
                inventory_item=inventory_by_id[accounting.inventory_id],
            ):
                raise SourceComponentAuditInvalid(
                    f"{accounting.inventory_id} has contradictory "
                    "bidirectional mapping: component_audits="
                    f"{sorted(reverse_ids)!r}, inventory_accounting="
                    f"{sorted(forward_ids)!r}"
                )
            resolved_by_inventory[accounting.inventory_id] = (
                forward_ids | reverse_ids
            )
        else:
            resolved_by_inventory[accounting.inventory_id] = forward_ids

    # Canonicalize a legitimate aggregate/member overlap to the union in both
    # directions.  The evidence hash still covers the provider's raw response;
    # this normalized value is only the safe relation consumed downstream.
    normalized_audits = tuple(
        audit.model_copy(update={
            "matched_inventory_ids": tuple(
                inventory_id
                for inventory_id in inventory_ids
                if audit.component_id in resolved_by_inventory[inventory_id]
            ),
        })
        for audit in mapping.component_audits
    )
    normalized_accounting = tuple(
        accounting.model_copy(update={
            "coverage_component_ids": tuple(
                component_id
                for component_id in coverage_ids
                if component_id in resolved_by_inventory[accounting.inventory_id]
            ),
        })
        for accounting in mapping.inventory_accounting
    )
    return mapping.model_copy(update={
        "component_audits": normalized_audits,
        "inventory_accounting": normalized_accounting,
    })


def _evidence_sha256(
    *,
    source_image: bytes,
    coverage_payload: dict,
    raw_inventory: dict,
    raw_mapping: dict,
) -> str:
    payload = {
        "source_sha256": hashlib.sha256(source_image).hexdigest(),
        "coverage_to_audit": coverage_payload,
        "blind_inventory_pass": raw_inventory,
        "independent_mapping_pass": raw_mapping,
    }
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SourceComponentAuditInvalid(
            "audit evidence is not canonical JSON"
        ) from exc
    return hashlib.sha256(encoded).hexdigest()


def _debug_evidence(
    *,
    source_image: bytes,
    validation_error: str,
    raw_inventory: dict,
    raw_mapping: dict | None = None,
) -> dict[str, object]:
    """Return JSON-safe local diagnostics without retaining source bytes."""
    payload: dict[str, object] = {
        "source_sha256": hashlib.sha256(source_image).hexdigest(),
        "validation_error": validation_error,
        "blind_inventory_pass": raw_inventory,
    }
    if raw_mapping is not None:
        payload["independent_mapping_pass"] = raw_mapping
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        snapshot = json.loads(encoded)
    except (TypeError, ValueError):
        return {
            "source_sha256": hashlib.sha256(source_image).hexdigest(),
            "validation_error": validation_error,
            "evidence_serializable": False,
        }
    if not isinstance(snapshot, dict):  # pragma: no cover - payload is a dict
        raise AssertionError("audit debug snapshot must be an object")
    return snapshot


def audit_source_component_coverage(
    source_image: bytes,
    coverage: SourceComponentCoverage,
    *,
    spec: Spec | None = None,
    inspect: ComponentAuditInspector | None = None,
    evidence_sink: ComponentAuditEvidenceSink | None = None,
) -> SourceComponentCoverage:
    """Return immutable coverage enriched by a blind, independent audit.

    The injected ``inspect`` callable uses the same signature as
    :func:`facetta.image_agent.vision.vision_json`, making tests and alternate
    transports network-free without weakening the two-pass contract.
    """

    if not isinstance(source_image, bytes) or not source_image:
        raise SourceComponentAuditInvalid("source image bytes are required")

    inspector = inspect or vision_json
    raw_inventory = _run_pass(
        inspector,
        system=_BLIND_INVENTORY_SYSTEM,
        source_image=source_image,
        user_text=(
            "Blindly inventory every visible major jewelry component. "
            "You have no expected specification or coverage list."
        ),
        pass_name="blind inventory",
    )
    try:
        inventory = _validate_blind_inventory(raw_inventory)
    except SourceComponentAuditInvalid as exc:
        raise SourceComponentAuditInvalid(
            str(exc),
            debug_evidence=_debug_evidence(
                source_image=source_image,
                validation_error=str(exc),
                raw_inventory=raw_inventory,
            ),
        ) from exc

    inventory_payload = inventory.model_dump(mode="json")
    coverage_payload = _coverage_payload(coverage, spec)
    mapping_user_text = json.dumps(
        {
            "blind_inventory": inventory_payload,
            "coverage_to_audit": coverage_payload,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    if evidence_sink is not None:
        evidence_sink({
            "stage": "blind_inventory_complete",
            "auditor": AUDITOR_VERSION,
            "source_sha256": hashlib.sha256(source_image).hexdigest(),
            "coverage_to_audit": coverage_payload,
            "blind_inventory_pass": raw_inventory,
        })
    try:
        raw_mapping = _run_pass(
            inspector,
            system=_MAPPING_SYSTEM,
            source_image=source_image,
            user_text=mapping_user_text,
            pass_name="mapping",
        )
    except SourceComponentAuditUnavailable as exc:
        detail = str(exc)
        raise SourceComponentAuditUnavailable(
            detail,
            debug_evidence=_debug_evidence(
                source_image=source_image,
                validation_error=detail,
                raw_inventory=raw_inventory,
            ),
        ) from exc
    try:
        mapping = _validate_mapping(
            raw_mapping,
            inventory=inventory,
            coverage=coverage,
        )
    except SourceComponentAuditInvalid as exc:
        raise SourceComponentAuditInvalid(
            str(exc),
            debug_evidence=_debug_evidence(
                source_image=source_image,
                validation_error=str(exc),
                raw_inventory=raw_inventory,
                raw_mapping=raw_mapping,
            ),
        ) from exc
    evidence_sha = _evidence_sha256(
        source_image=source_image,
        coverage_payload=coverage_payload,
        raw_inventory=raw_inventory,
        raw_mapping=raw_mapping,
    )
    if evidence_sink is not None:
        evidence_sink({
            "stage": "complete",
            "auditor": AUDITOR_VERSION,
            "source_sha256": hashlib.sha256(source_image).hexdigest(),
            "coverage_to_audit": coverage_payload,
            "blind_inventory_pass": raw_inventory,
            "independent_mapping_pass": raw_mapping,
            "evidence_sha256": evidence_sha,
        })

    audits = {item.component_id: item for item in mapping.component_audits}
    inventory_by_id = {
        item.inventory_id: item for item in inventory.components
    }
    updated_components: list[SourceVisibleComponent] = []
    for component in coverage.components:
        result = audits[component.component_id]
        setting_conflict = _setting_conflict(
            component, result, inventory_by_id, spec)
        count_conflict = _repeated_stone_count_conflict(
            component,
            result,
            inventory_by_id,
            spec,
        )
        form_conflict = _distinctive_form_mapping_conflict(
            component,
            result,
            inventory_by_id,
        )
        deterministic_conflict = (
            setting_conflict or count_conflict or form_conflict
        )
        evidence_gap = (
            _setting_evidence_gap(component, result, inventory_by_id, spec)
            or _repeated_stone_count_evidence_gap(
                component,
                result,
                inventory_by_id,
                spec,
            )
            or _white_metal_material_evidence_gap(
                component,
                result,
                inventory_by_id,
                spec,
            )
        )
        verdict = (
            "fail" if deterministic_conflict is not None
            else "inconclusive" if evidence_gap is not None
            else result.verdict
        )
        observed_description = result.observed_description
        if deterministic_conflict is not None:
            observed_description = (
                "Deterministic visible-fact evidence conflict: "
                + deterministic_conflict + "."
            )
        elif evidence_gap is not None:
            observed_description = (
                "Blind visible-fact evidence is insufficient: "
                + evidence_gap + "."
            )
        audit = IndependentComponentAudit(
            kind="independent_component_audit",
            verdict=verdict,
            auditor=AUDITOR_VERSION,
            source_view=result.source_view,
            observed_description=observed_description,
            evidence_sha256=evidence_sha,
        )
        updated_components.append(component.model_copy(update={
            "independent_audit": audit,
        }))

    unmapped_items = [
        item
        for item in mapping.inventory_accounting
        if not item.coverage_component_ids
    ]
    for index, accounting in enumerate(unmapped_items, start=1):
        blind = inventory_by_id[accounting.inventory_id]
        reason = accounting.unmapped_reason
        if reason is None:  # guarded by _validate_mapping
            raise SourceComponentAuditInvalid(
                f"{accounting.inventory_id} has no unmapped reason"
            )
        updated_components.append(SourceVisibleComponent(
            component_id=f"audit.unmapped.{index:03d}",
            source_view=blind.source_view,
            source_description=blind.observed_description,
            source_confidence=float(blind.confidence),
            unresolved_reason=(
                f"Blind inventory {accounting.inventory_id} was not mapped: {reason}"
            ),
            independent_audit=IndependentComponentAudit(
                kind="independent_component_audit",
                verdict="fail",
                auditor=AUDITOR_VERSION,
                source_view=blind.source_view,
                observed_description=(
                    f"Blind inventory {accounting.inventory_id} is visible but "
                    f"absent from coverage: {reason}"
                ),
                evidence_sha256=evidence_sha,
            ),
        ))

    return SourceComponentCoverage(
        source_kind=coverage.source_kind,
        components=tuple(updated_components),
        audited_spec_visual_hash=(
            spec_visual_hash(spec) if spec is not None else None
        ),
        audited_source_sha256=hashlib.sha256(source_image).hexdigest(),
    )

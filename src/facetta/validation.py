"""Vocabulary and physical-consistency validation for Spec objects.

Everything here is data-driven from the vocabulary file. Each failed rule
produces a ValidationIssue shaped like FastAPI's 422 detail entries
(loc / msg / type) plus, where the rules table in docs/SPEC_SCHEMA.md calls
for it, the list of valid options or the computed expected values.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from facetta.density import check_density
from facetta.spec import RingSize, Spec, Stone
from facetta.vocabulary import Vocabulary

# US ring size -> inner diameter: linear model, size 3 = 14.07 mm, +0.8128 mm per size
US_SIZE_BASE_MM = 11.63
US_SIZE_STEP_MM = 0.8128
RING_DIAMETER_TOLERANCE_MM = 0.1

# multi-stone fit constants (mm)
HALO_MARGIN_MM = 0.3   # gap between center stone girdle and melee
STONE_GAP_MM = 0.2     # minimum gap between adjacent surround stones
STATION_GAP_MM = 1.0   # minimum metal between bangle station stones

RING_TEMPLATES = ("solitaire_prong", "halo_prong")


def ellipse_perimeter_mm(a: float, b: float) -> float:
    """Ramanujan's approximation for an ellipse with semi-axes a, b."""
    h = ((a - b) / (a + b)) ** 2
    return math.pi * (a + b) * (1 + 3 * h / (10 + math.sqrt(4 - 3 * h)))


@dataclass
class ValidationIssue:
    loc: tuple
    msg: str
    type: str
    valid_options: list[str] | None = None
    expected: dict | None = None

    def as_detail(self) -> dict:
        detail = {"loc": list(self.loc), "msg": self.msg, "type": self.type}
        if self.valid_options is not None:
            detail["valid_options"] = self.valid_options
        if self.expected is not None:
            detail["expected"] = self.expected
        return detail


@dataclass
class ValidationResult:
    spec: Spec
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues


def expected_inner_diameter_mm(ring_size: RingSize) -> float:
    return round(US_SIZE_BASE_MM + US_SIZE_STEP_MM * ring_size.value, 2)


PENDANT_LINK_GAP_MM = 1.0  # jump-ring gap between bail, cluster, and drop stone


def pendant_drop_mm(spec: Spec) -> float:
    """Overall pendant drop (bail top to lowest point), derived from the parts."""
    assert spec.pendant is not None
    melee = next((s for s in spec.side_stones if s.position in ("halo", "surround")), None)
    surround = HALO_MARGIN_MM + melee.dimensions_mm.width if melee else 0.0
    cluster_l = spec.stone.dimensions_mm.length + 2 * surround
    drop = spec.pendant.bail_height_mm + PENDANT_LINK_GAP_MM + cluster_l
    drop_stone = next((s for s in spec.side_stones if s.position in ("under_center", "drop")), None)
    if drop_stone is not None:
        drop += PENDANT_LINK_GAP_MM + drop_stone.dimensions_mm.width
    return round(drop, 2)


def _validate_stone(stone: Stone, loc: tuple, vocab: Vocabulary, issues: list[ValidationIssue]) -> None:
    species = vocab.species(stone.species)
    if species is None:
        issues.append(ValidationIssue(
            loc=(*loc, "species"),
            msg=f"unknown species '{stone.species}'",
            type="vocabulary",
            valid_options=vocab.species_ids(),
        ))

    cut = vocab.cut(stone.cut)
    if cut is None:
        issues.append(ValidationIssue(
            loc=(*loc, "cut"),
            msg=f"unknown cut '{stone.cut}'",
            type="vocabulary",
            valid_options=vocab.cut_ids(),
        ))

    if species is None:
        return  # every remaining rule cascades from the species

    trade_names = vocab.trade_color_names(stone.species)
    if trade_names and stone.color.trade not in trade_names:
        issues.append(ValidationIssue(
            loc=(*loc, "color", "trade"),
            msg=f"'{stone.color.trade}' is not a known trade color term for {species.display}",
            type="vocabulary",
            valid_options=trade_names,
        ))

    if stone.clarity.system not in species.clarity_systems:
        issues.append(ValidationIssue(
            loc=(*loc, "clarity", "system"),
            msg=f"clarity system '{stone.clarity.system}' does not apply to {species.display}",
            type="vocabulary",
            valid_options=list(species.clarity_systems),
        ))
    else:
        grades = vocab.clarity_grades(stone.clarity.system)
        if stone.clarity.grade not in grades:
            issues.append(ValidationIssue(
                loc=(*loc, "clarity", "grade"),
                msg=f"unknown grade '{stone.clarity.grade}' for clarity system '{stone.clarity.system}'",
                type="vocabulary",
                valid_options=grades,
            ))

    for i, phenomenon in enumerate(stone.phenomena):
        if phenomenon not in species.allowed_phenomena:
            issues.append(ValidationIssue(
                loc=(*loc, "phenomena", i),
                msg=f"phenomenon '{phenomenon}' is not documented for {species.display}",
                type="vocabulary",
                valid_options=list(species.allowed_phenomena),
            ))

    if cut is not None:
        d = stone.dimensions_mm
        result = check_density(
            sg=species.sg,
            shape_factor=cut.shape_factor,
            length_mm=d.length,
            width_mm=d.width,
            depth_mm=d.depth,
            carat=stone.carat,
        )
        if not result.ok:
            issues.append(ValidationIssue(
                loc=(*loc, "carat"),
                msg=result.message,
                type="density",
                expected={
                    "expected_carat": result.expected_carat,
                    "expected_depth_mm": result.expected_depth_mm,
                    "deviation": result.deviation,
                },
            ))


def _surround_fit(center_span_a: float, center_span_b: float, stone: Stone,
                  gap: float, margin: float) -> tuple[int, float]:
    """How many `stone`s fit around an ellipse with the given semi-axes.

    Returns (max_count, ring_perimeter_mm): the surround stones sit on the
    ellipse offset outward from the center by margin + half a stone width.
    """
    w = stone.dimensions_mm.width
    a = center_span_a + margin + w / 2
    b = center_span_b + margin + w / 2
    perimeter = ellipse_perimeter_mm(a, b)
    return int(perimeter // (w + gap)), perimeter


def _validate_assembly(spec: Spec, issues: list[ValidationIssue]) -> None:
    """Template section requirements and multi-stone physical fit."""
    if spec.template in RING_TEMPLATES:
        if spec.band is None:
            issues.append(ValidationIssue(
                loc=("band",), type="template",
                msg=f"template '{spec.template}' is a ring and requires a band section",
            ))
        if spec.ring_size is None:
            issues.append(ValidationIssue(
                loc=("ring_size",), type="template",
                msg=f"template '{spec.template}' is a ring and requires a ring_size section",
            ))
    if spec.template == "love_bangle" and spec.bracelet is None:
        issues.append(ValidationIssue(
            loc=("bracelet",), type="template",
            msg="template 'love_bangle' requires a bracelet section",
        ))
    if spec.template == "cluster_pendant" and spec.pendant is None:
        issues.append(ValidationIssue(
            loc=("pendant",), type="template",
            msg="template 'cluster_pendant' requires a pendant section",
        ))

    # halo / surround stones must physically fit around the center stone
    center = spec.stone.dimensions_mm
    for i, stone in enumerate(spec.side_stones):
        if stone.position not in ("halo", "surround"):
            continue
        max_count, perimeter = _surround_fit(
            center.width / 2, center.length / 2, stone, STONE_GAP_MM, HALO_MARGIN_MM
        )
        if stone.count > max_count:
            issues.append(ValidationIssue(
                loc=("side_stones", i, "count"),
                type="fit",
                msg=(
                    f"{stone.count} x {stone.dimensions_mm.width} mm stones cannot fit around "
                    f"the {center.length} x {center.width} mm center "
                    f"({perimeter:.1f} mm of halo, {STONE_GAP_MM} mm gaps) — "
                    f"at most {max_count} fit"
                ),
                expected={"max_count": max_count, "halo_perimeter_mm": round(perimeter, 1)},
            ))

    # bangle stations must fit on the band centerline
    if spec.bracelet is not None:
        stations = [(("stone",), spec.stone)] if spec.stone.position == "stations" else []
        stations += [
            (("side_stones", i), s) for i, s in enumerate(spec.side_stones)
            if s.position == "stations"
        ]
        a = (spec.bracelet.inner_length_mm + spec.bracelet.thickness_mm) / 2
        b = (spec.bracelet.inner_width_mm + spec.bracelet.thickness_mm) / 2
        perimeter = ellipse_perimeter_mm(a, b)
        for loc, stone in stations:
            w = stone.dimensions_mm.width
            max_count = int(perimeter // (w + STATION_GAP_MM))
            if stone.count > max_count:
                issues.append(ValidationIssue(
                    loc=(*loc, "count"),
                    type="fit",
                    msg=(
                        f"{stone.count} x {w} mm stations exceed the bangle's "
                        f"{perimeter:.1f} mm centerline (min {STATION_GAP_MM} mm between "
                        f"stations) — at most {max_count} fit"
                    ),
                    expected={"max_count": max_count, "band_perimeter_mm": round(perimeter, 1)},
                ))
            if w > spec.bracelet.width_mm - 1.0:
                issues.append(ValidationIssue(
                    loc=(*loc, "dimensions_mm", "width"),
                    type="fit",
                    msg=(
                        f"a {w} mm stone does not leave 0.5 mm of metal on each side of a "
                        f"{spec.bracelet.width_mm} mm wide band"
                    ),
                    expected={"max_stone_width_mm": round(spec.bracelet.width_mm - 1.0, 2)},
                ))


def validate_spec(spec: Spec, vocab: Vocabulary) -> ValidationResult:
    """Validate vocabulary membership and physical consistency.

    Returns the spec (with ring inner diameter auto-derived when absent) and
    any issues found. The caller decides how to surface the issues.
    """
    issues: list[ValidationIssue] = []

    _validate_stone(spec.stone, ("stone",), vocab, issues)
    for i, stone in enumerate(spec.side_stones):
        _validate_stone(stone, ("side_stones", i), vocab, issues)
    _validate_assembly(spec, issues)

    if spec.pendant is not None and spec.pendant.drop_mm is None:
        spec = spec.model_copy(deep=True)
        spec.pendant.drop_mm = pendant_drop_mm(spec)

    if spec.ring_size is not None:
        expected = expected_inner_diameter_mm(spec.ring_size)
        if spec.ring_size.inner_diameter_mm is None:
            spec = spec.model_copy(deep=True)
            spec.ring_size.inner_diameter_mm = expected
        elif abs(spec.ring_size.inner_diameter_mm - expected) > RING_DIAMETER_TOLERANCE_MM:
            issues.append(ValidationIssue(
                loc=("ring_size", "inner_diameter_mm"),
                msg=(
                    f"inner diameter {spec.ring_size.inner_diameter_mm} mm contradicts "
                    f"{spec.ring_size.system} size {spec.ring_size.value} "
                    f"(expected about {expected} mm)"
                ),
                type="ring_size",
                expected={"inner_diameter_mm": expected},
            ))

    return ValidationResult(spec=spec, issues=issues)

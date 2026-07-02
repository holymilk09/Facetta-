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
BRACELET_TEMPLATES = ("love_bangle", "cuff", "link_bracelet")
UNMOUNTED_TEMPLATES = ("loose_stone",)  # no setting/metal — the stone is the piece


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


@dataclass(frozen=True)
class NestingClearance:
    """How two pieces stack or nest, per docs/SPEC_SCHEMA.md stacking rules."""

    kind: str                      # "bangle_in_bangle" | "ring_stack"
    nests: bool
    clearance_x_mm: float | None = None   # bangle-in-bangle, per side
    clearance_y_mm: float | None = None
    stack_height_mm: float | None = None  # ring stack: combined band width
    diameter_delta_mm: float | None = None

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None}


def nesting_clearance(spec_a: Spec, spec_b: Spec) -> NestingClearance:
    """Clearance between two pieces worn together.

    Bangle in bangle: outer envelope of the smaller vs inner opening of the
    larger, per axis (negative = they do not nest). Ring on ring: they sit
    adjacent on the finger — combined stack height and inner-diameter delta.
    """
    if spec_a.bracelet is not None and spec_b.bracelet is not None:
        pair = sorted((spec_a.bracelet, spec_b.bracelet),
                      key=lambda b: b.inner_length_mm + 2 * b.thickness_mm)
        inner_piece, outer_piece = pair
        cx = (outer_piece.inner_length_mm
              - (inner_piece.inner_length_mm + 2 * inner_piece.thickness_mm)) / 2
        cy = (outer_piece.inner_width_mm
              - (inner_piece.inner_width_mm + 2 * inner_piece.thickness_mm)) / 2
        return NestingClearance(
            kind="bangle_in_bangle",
            nests=cx > 0 and cy > 0,
            clearance_x_mm=round(cx, 2),
            clearance_y_mm=round(cy, 2),
        )
    if (spec_a.band is not None and spec_a.ring_size is not None
            and spec_b.band is not None and spec_b.ring_size is not None):
        d1 = spec_a.ring_size.inner_diameter_mm or expected_inner_diameter_mm(spec_a.ring_size)
        d2 = spec_b.ring_size.inner_diameter_mm or expected_inner_diameter_mm(spec_b.ring_size)
        return NestingClearance(
            kind="ring_stack",
            nests=True,
            stack_height_mm=round(spec_a.band.width_mm + spec_b.band.width_mm, 2),
            diameter_delta_mm=round(abs(d1 - d2), 2),
        )
    raise ValueError(
        "stacking supports two bangles/cuffs (nesting) or two rings (finger stack); "
        f"got templates '{spec_a.template}' and '{spec_b.template}'"
    )


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

    if stone.girdle is not None and stone.girdle not in vocab.girdle_grades():
        issues.append(ValidationIssue(
            loc=(*loc, "girdle"),
            msg=f"unknown girdle thickness '{stone.girdle}'",
            type="vocabulary",
            valid_options=vocab.girdle_grades(),
        ))

    if stone.depth_pct is not None:
        computed = stone.dimensions_mm.depth / stone.dimensions_mm.width * 100
        if abs(stone.depth_pct - computed) > 2.5:
            issues.append(ValidationIssue(
                loc=(*loc, "depth_pct"),
                msg=(
                    f"depth {stone.depth_pct}% contradicts the measurements: "
                    f"{stone.dimensions_mm.depth} / {stone.dimensions_mm.width} mm "
                    f"= {computed:.1f}%"
                ),
                type="proportions",
                expected={"computed_depth_pct": round(computed, 1)},
            ))

    if stone.table_pct is not None and cut is not None:
        low, high = (55, 75) if cut.category == "step" else (50, 70)
        if not (low <= stone.table_pct <= high):
            issues.append(ValidationIssue(
                loc=(*loc, "table_pct"),
                msg=(
                    f"table {stone.table_pct}% is outside the workable range for a "
                    f"{cut.category} cut ({low}–{high}%)"
                ),
                type="proportions",
                expected={"min_pct": low, "max_pct": high},
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


def _validate_assembly(spec: Spec, vocab: Vocabulary, issues: list[ValidationIssue]) -> None:
    """Template section requirements and multi-stone physical fit."""
    if spec.template not in UNMOUNTED_TEMPLATES:
        if spec.setting is None:
            issues.append(ValidationIssue(
                loc=("setting",), type="template",
                msg=f"template '{spec.template}' is a mounted piece and requires a setting section",
            ))
        if spec.metal is None:
            issues.append(ValidationIssue(
                loc=("metal",), type="template",
                msg=f"template '{spec.template}' is a mounted piece and requires a metal section",
            ))
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
    if spec.template in BRACELET_TEMPLATES and spec.bracelet is None:
        issues.append(ValidationIssue(
            loc=("bracelet",), type="template",
            msg=f"template '{spec.template}' requires a bracelet section",
        ))
    if spec.bracelet is not None:
        if spec.template == "cuff" and spec.bracelet.gap_width_mm is None:
            issues.append(ValidationIssue(
                loc=("bracelet", "gap_width_mm"), type="template",
                msg="template 'cuff' requires bracelet.gap_width_mm (the wrist opening)",
            ))
        if spec.template == "link_bracelet" and spec.bracelet.link_count is None:
            issues.append(ValidationIssue(
                loc=("bracelet", "link_count"), type="template",
                msg="template 'link_bracelet' requires bracelet.link_count",
            ))
        if (spec.bracelet.gap_width_mm is not None
                and spec.bracelet.gap_width_mm >= spec.bracelet.inner_width_mm):
            issues.append(ValidationIssue(
                loc=("bracelet", "gap_width_mm"), type="fit",
                msg=(
                    f"a {spec.bracelet.gap_width_mm} mm gap in a "
                    f"{spec.bracelet.inner_width_mm} mm opening is no longer a cuff"
                ),
                expected={"max_gap_mm": spec.bracelet.inner_width_mm - 1},
            ))
    if spec.template == "cluster_pendant" and spec.pendant is None:
        issues.append(ValidationIssue(
            loc=("pendant",), type="template",
            msg="template 'cluster_pendant' requires a pendant section",
        ))
    if spec.chain is not None:
        if spec.chain.style not in vocab.chain_style_ids():
            issues.append(ValidationIssue(
                loc=("chain", "style"),
                msg=f"unknown chain style '{spec.chain.style}'",
                type="vocabulary",
                valid_options=vocab.chain_style_ids(),
            ))
        if spec.chain.clasp not in vocab.clasp_type_ids():
            issues.append(ValidationIssue(
                loc=("chain", "clasp"),
                msg=f"unknown clasp type '{spec.chain.clasp}'",
                type="vocabulary",
                valid_options=vocab.clasp_type_ids(),
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
        if spec.bracelet.gap_width_mm is not None:
            perimeter -= spec.bracelet.gap_width_mm  # stones live on the arc only
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
    _validate_assembly(spec, vocab, issues)

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

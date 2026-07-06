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
BROOCH_TEMPLATES = ("leaf_spray_brooch",)

# leaf-spray cluster constants (mm)
CLUSTER_HUB_MM = 1.6    # metal frame + hub a quatrefoil adds beyond its petals
SPRAY_END_MM = 5.0      # stem run-out and catch ring past the last cluster


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


def expected_inner_diameter_mm(ring_size: RingSize, vocab: Vocabulary | None = None) -> float | None:
    """Inner diameter for a ring size in any supported system.

    US follows the linear formula; UK/EU/JP/HK look up the vocabulary's
    international conversion table (diameter_mm is the canonical column).
    Returns None when the size value isn't a listed one for its system.
    """
    if ring_size.system == "US" and not isinstance(ring_size.value, str):
        return round(US_SIZE_BASE_MM + US_SIZE_STEP_MM * ring_size.value, 2)
    if vocab is None:
        from facetta.vocabulary import get_vocabulary
        vocab = get_vocabulary()
    key = ring_size.system.lower()
    for row in vocab.ring_size_rows():
        listed = row[key]
        if isinstance(ring_size.value, str):
            if str(listed).replace(" ", "").upper() == ring_size.value.replace(" ", "").upper():
                return row["diameter_mm"]
        elif isinstance(listed, (int, float)) and float(listed) == float(ring_size.value):
            return row["diameter_mm"]
    return None


def ring_size_options(system: str, vocab: Vocabulary) -> list[str]:
    key = system.lower()
    return [str(row[key]) for row in vocab.ring_size_rows()]


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
        if d1 is None or d2 is None:
            raise ValueError("ring sizes must resolve to inner diameters before stacking")
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


# alloy densities in g/cm^3 — factories quote castings from estimated weight
GOLD_DENSITY = {9: 11.2, 14: 13.6, 18: 15.5, 22: 17.8, 24: 19.3}
METAL_DENSITY = {"platinum": 21.45, "silver": 10.36}


def estimate_metal_g(spec: Spec) -> float | None:
    """Rough cast-weight estimate from the metal cross-sections (stones excluded).

    Ring: hoop annulus x band width. Bangle/cuff/link: centerline perimeter x
    band section (cuffs lose the gap share). Pendants vary too much to guess.
    """
    if spec.metal is None:
        return None
    if spec.metal.material == "gold":
        density = GOLD_DENSITY.get(spec.metal.karat or 18, 15.5)
    else:
        density = METAL_DENSITY.get(spec.metal.material)
    if density is None:
        return None

    volume_mm3 = None
    if spec.band is not None and spec.ring_size is not None:
        inner_d = spec.ring_size.inner_diameter_mm or expected_inner_diameter_mm(spec.ring_size)
        if inner_d is None:
            return None
        r_i = inner_d / 2
        r_o = r_i + spec.band.thickness_mm
        volume_mm3 = math.pi * (r_o**2 - r_i**2) * spec.band.width_mm
    elif spec.bracelet is not None:
        br = spec.bracelet
        a = (br.inner_length_mm + br.thickness_mm) / 2
        b = (br.inner_width_mm + br.thickness_mm) / 2
        length = ellipse_perimeter_mm(a, b)
        if br.gap_width_mm is not None:
            length -= br.gap_width_mm
        volume_mm3 = length * br.width_mm * br.thickness_mm
    if volume_mm3 is None:
        return None
    return round(volume_mm3 * density / 1000, 1)


PENDANT_LINK_GAP_MM = 1.0  # jump-ring gap between bail, cluster, and drop stone


def pendant_drop_mm(spec: Spec) -> float:
    """Overall pendant drop (bail top to lowest point), derived from the parts."""
    assert spec.pendant is not None
    surround_stones = [s for s in spec.side_stones if s.position in ("halo", "surround")]
    melee = max(surround_stones, key=lambda s: s.dimensions_mm.width) if surround_stones else None
    surround = HALO_MARGIN_MM + melee.dimensions_mm.width if melee else 0.0
    cluster_l = spec.stone.dimensions_mm.length + 2 * surround
    drop = spec.pendant.bail_height_mm + PENDANT_LINK_GAP_MM + cluster_l
    drop_stone = next((s for s in spec.side_stones if s.position in ("under_center", "drop")), None)
    if drop_stone is not None:
        # the drop stone hangs point-down: its LENGTH is the vertical extent
        # (identical to width for rounds, longer for pears and ovals)
        drop += PENDANT_LINK_GAP_MM + drop_stone.dimensions_mm.length
    return round(drop, 2)


def spray_cluster_row(spec: Spec) -> list[tuple[Stone, float]]:
    """The leaf-spray's quatrefoil clusters from the tip inward: the terminal
    (the center stone's four petals) first, then one cluster per four petals
    of each 'quatrefoil_stations' group, in side-stone order — spec order IS
    the designer's cluster order along the branch. Each entry is (petal stone,
    cluster diameter): petals point at the hub, so a cluster spans two petal
    lengths plus the metal hub and frame."""
    row = [(spec.stone, 2 * spec.stone.dimensions_mm.length + CLUSTER_HUB_MM)]
    for stone in spec.side_stones:
        if stone.position != "quatrefoil_stations":
            continue
        d = 2 * stone.dimensions_mm.length + CLUSTER_HUB_MM
        row += [(stone, d)] * (stone.count // 4)
    return row


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

    if stone.clarity is not None:  # optional: absent = best available, sourced on approval
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

    if stone.lab is not None and stone.lab not in vocab.grading_labs():
        issues.append(ValidationIssue(
            loc=(*loc, "lab"),
            msg=f"unknown grading lab '{stone.lab}'",
            type="vocabulary",
            valid_options=vocab.grading_labs(),
        ))

    if stone.mount is not None:
        technique = vocab.setting_technique(stone.mount)
        if technique is None:
            issues.append(ValidationIssue(
                loc=(*loc, "mount"),
                msg=f"unknown setting technique '{stone.mount}'",
                type="vocabulary",
                valid_options=[t["id"] for t in vocab.setting_techniques()],
            ))
        else:
            role = {"halo": "side", "surround": "side", "stations": "station",
                    "under_center": "drop", "drop": "drop"}.get(
                        stone.position or "", "center")
            if role not in technique["holds"]:
                issues.append(ValidationIssue(
                    loc=(*loc, "mount"),
                    msg=(f"{technique['display']} cannot hold a {role} stone — "
                         f"it holds: {', '.join(technique['holds'])}"),
                    type="mount",
                    valid_options=[t["id"] for t in vocab.setting_techniques()
                                   if role in t["holds"]],
                ))
            width = stone.dimensions_mm.width
            lo = technique.get("min_stone_mm")
            hi = technique.get("max_stone_mm")
            if (lo is not None and width < lo) or (hi is not None and width > hi):
                bounds = f"{lo}–{hi or '∞'} mm"
                issues.append(ValidationIssue(
                    loc=(*loc, "mount"),
                    msg=(f"a {width} mm stone is outside {technique['display']}'s "
                         f"workable range ({bounds})"),
                    type="mount",
                    expected={"min_stone_mm": lo, "max_stone_mm": hi},
                ))

    if stone.culet is not None and stone.culet not in vocab.culet_grade_ids():
        issues.append(ValidationIssue(
            loc=(*loc, "culet"),
            msg=f"unknown culet size '{stone.culet}'",
            type="vocabulary",
            valid_options=vocab.culet_grade_ids(),
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
        # a thick girdle hides real weight: the appraisal girdle-correction
        # multiplier scales the expected carat (and its depth inverse)
        gc = (vocab.girdle_weight_correction(stone.cut, stone.girdle)
              if stone.girdle else 1.0)
        result = check_density(
            sg=species.sg,
            shape_factor=cut.shape_factor * gc,
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


def _validate_metal(metal, vocab: Vocabulary, issues: list[ValidationIssue]) -> None:
    """Alloy logic from the metals vocabulary: parameters that don't apply to a
    material must be absent (silver has one color; platinum isn't karated), so
    an illogical combination can never reach a sheet or an image-gen prompt."""
    rules = vocab.metal(metal.material)
    if rules is None:
        issues.append(ValidationIssue(
            loc=("metal", "material"), type="vocabulary",
            msg=f"unknown metal '{metal.material}'",
            valid_options=[m["id"] for m in vocab.metals()],
        ))
        return
    if rules["karats"]:
        if metal.karat is None or metal.karat not in rules["karats"]:
            issues.append(ValidationIssue(
                loc=("metal", "karat"), type="vocabulary",
                msg=f"{metal.material} requires a karat",
                valid_options=[str(k) for k in rules["karats"]],
            ))
    elif metal.karat is not None:
        issues.append(ValidationIssue(
            loc=("metal", "karat"), type="vocabulary",
            msg=f"{metal.material} is not karated — omit karat",
        ))
    if rules["colors"]:
        if metal.color is None or metal.color not in rules["colors"]:
            issues.append(ValidationIssue(
                loc=("metal", "color"), type="vocabulary",
                msg=f"{metal.material} requires an alloy color",
                valid_options=rules["colors"],
            ))
    elif metal.color is not None:
        issues.append(ValidationIssue(
            loc=("metal", "color"), type="vocabulary",
            msg=f"{metal.material} has a single natural color — omit color",
        ))


def _validate_spray(spec: Spec, issues: list[ValidationIssue]) -> None:
    """Leaf-spray cluster arithmetic and fit: quatrefoils come in fours, every
    cluster carries one center, and the cluster row must fit the spray."""
    if spec.brooch is None:
        issues.append(ValidationIssue(
            loc=("brooch",), type="template",
            msg=f"template '{spec.template}' requires a brooch section",
        ))
    counts_ok = True
    if spec.stone.count != 4:
        counts_ok = False
        issues.append(ValidationIssue(
            loc=("stone", "count"), type="fit",
            msg="the terminal quatrefoil is four petals — stone.count must be 4",
            expected={"count": 4},
        ))
    for i, stone in enumerate(spec.side_stones):
        if stone.position == "quatrefoil_stations" and stone.count % 4:
            counts_ok = False
            issues.append(ValidationIssue(
                loc=("side_stones", i, "count"), type="fit",
                msg=(f"quatrefoil stations come in fours — {stone.count} "
                     "petals leave a partial cluster"),
            ))
    if not counts_ok:
        return
    row = spray_cluster_row(spec)
    centers = sum(s.count for s in spec.side_stones
                  if s.position == "quatrefoil_centers")
    if centers and centers != len(row):
        issues.append(ValidationIssue(
            loc=("side_stones",), type="fit",
            msg=(f"{len(row)} quatrefoil clusters need {len(row)} center stones "
                 f"— the spec carries {centers}"),
            expected={"center_count": len(row)},
        ))
    if spec.composition is not None:
        if len(spec.composition.clusters) != len(row):
            issues.append(ValidationIssue(
                loc=("composition", "clusters"), type="fit",
                msg=(f"the traced composition anchors {len(spec.composition.clusters)} "
                     f"clusters but the stones describe {len(row)} — the artwork "
                     "and the stone list disagree"),
                expected={"cluster_count": len(row)},
            ))
    if spec.brooch is None:
        return
    if spec.composition is None:
        # straight-row fit only applies when the layout is synthesized; a
        # traced composition carries its own (curved) cluster positions
        need = round(sum(d for _, d in row) + STATION_GAP_MM * (len(row) - 1)
                     + SPRAY_END_MM, 2)
        if need > spec.brooch.length_mm:
            issues.append(ValidationIssue(
                loc=("brooch", "length_mm"), type="fit",
                msg=(f"the cluster row needs {need} mm of spray (clusters + "
                     f"{STATION_GAP_MM} mm gaps + {SPRAY_END_MM} mm stem run-out) "
                     f"but the spray is {spec.brooch.length_mm} mm"),
                expected={"min_length_mm": need},
            ))
    terminal_d = row[0][1]
    if spec.brooch.width_mm < terminal_d + 4:
        issues.append(ValidationIssue(
            loc=("brooch", "width_mm"), type="fit",
            msg=(f"the terminal cluster is {terminal_d} mm across — the spray "
                 "needs at least 4 mm of leaf above it"),
            expected={"min_width_mm": round(terminal_d + 4, 2)},
        ))


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
    if spec.metal is not None:
        _validate_metal(spec.metal, vocab, issues)
    if (spec.template in RING_TEMPLATES and spec.setting is not None
            and spec.setting.gallery_height_mm is not None):
        # factory rule: the culet must clear the finger rail (skin) — pavilion
        # is ~71% of stone depth under our 26% crown / thin girdle split
        min_rail = vocab.manufacturing_tolerances()["culet_to_finger_rail_mm"]
        required = round(0.71 * spec.stone.dimensions_mm.depth + min_rail, 2)
        if spec.setting.gallery_height_mm < required:
            issues.append(ValidationIssue(
                loc=("setting", "gallery_height_mm"),
                msg=(
                    f"gallery {spec.setting.gallery_height_mm} mm sits the culet "
                    f"closer than {min_rail} mm to the finger rail — casting "
                    f"workshops reject this for skin comfort"
                ),
                type="manufacturing",
                expected={"min_gallery_height_mm": required},
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
    if spec.template in BROOCH_TEMPLATES:
        _validate_spray(spec, issues)
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

    # alternating surrounds share one ring: their combined arc must also fit
    surround_groups = [s for s in spec.side_stones
                       if s.position in ("halo", "surround")]
    if len(surround_groups) > 1:
        widest = max(surround_groups, key=lambda s: s.dimensions_mm.width)
        _, perimeter = _surround_fit(
            center.width / 2, center.length / 2, widest, STONE_GAP_MM, HALO_MARGIN_MM
        )
        needed = sum(s.count * (s.dimensions_mm.width + STONE_GAP_MM)
                     for s in surround_groups)
        if needed > perimeter:
            issues.append(ValidationIssue(
                loc=("side_stones",),
                type="fit",
                msg=(
                    f"the combined surround needs {needed:.1f} mm of ring but only "
                    f"{perimeter:.1f} mm exists around the center — reduce counts "
                    f"or stone sizes"
                ),
                expected={"ring_perimeter_mm": round(perimeter, 1),
                          "needed_mm": round(needed, 1)},
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
        expected = expected_inner_diameter_mm(spec.ring_size, vocab)
        if expected is None:
            issues.append(ValidationIssue(
                loc=("ring_size", "value"),
                msg=(f"'{spec.ring_size.value}' is not a listed "
                     f"{spec.ring_size.system} ring size"),
                type="ring_size",
                valid_options=ring_size_options(spec.ring_size.system, vocab),
            ))
        elif spec.ring_size.inner_diameter_mm is None:
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

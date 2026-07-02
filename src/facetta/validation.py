"""Vocabulary and physical-consistency validation for Spec objects.

Everything here is data-driven from the vocabulary file. Each failed rule
produces a ValidationIssue shaped like FastAPI's 422 detail entries
(loc / msg / type) plus, where the rules table in docs/SPEC_SCHEMA.md calls
for it, the list of valid options or the computed expected values.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from facetta.density import check_density
from facetta.spec import RingSize, Spec, Stone
from facetta.vocabulary import Vocabulary

# US ring size -> inner diameter: linear model, size 3 = 14.07 mm, +0.8128 mm per size
US_SIZE_BASE_MM = 11.63
US_SIZE_STEP_MM = 0.8128
RING_DIAMETER_TOLERANCE_MM = 0.1


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


def validate_spec(spec: Spec, vocab: Vocabulary) -> ValidationResult:
    """Validate vocabulary membership and physical consistency.

    Returns the spec (with ring inner diameter auto-derived when absent) and
    any issues found. The caller decides how to surface the issues.
    """
    issues: list[ValidationIssue] = []

    _validate_stone(spec.stone, ("stone",), vocab, issues)
    for i, stone in enumerate(spec.side_stones):
        _validate_stone(stone, ("side_stones", i), vocab, issues)

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

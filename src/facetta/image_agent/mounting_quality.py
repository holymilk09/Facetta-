"""Automated QA for AI-drawn mounting and hardware view proposals.

This module deliberately owns no image operation, routing, prompt compilation,
or persistence.  It provides the evaluator seam used by ``JewelryImageAgent``:
candidate-only structural evidence is combined with a source/candidate fidelity
audit and normalized into the existing ``ImageQualityReport`` contract.

Every visual proposal remains non-authoritative even when all hard visual gates
pass.  A designer must confirm the proposed mounting before it can support any
factory discussion, and tolerance-bearing CAD or a verified master remains the
production authority.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from facetta.image_agent.contracts import (
    CheckSeverity,
    ImageAgentPlan,
    ImageQualityReport,
    QualityCheck,
    QualityVerdict,
)
from facetta.image_agent.vision import vision_json, vision_json_pair


MountingProjection = Literal["plan", "front", "side", "section"]


class _InspectionModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class MountingProjectionInspection(_InspectionModel):
    projection: MountingProjection
    present: bool | None = None
    notes: tuple[str, ...] = ()


class MountingSectionInspection(_InspectionModel):
    """Evidence that a panel is a true cut, not another exterior elevation."""

    panel_present: bool | None = None
    center_axis_cut: bool | None = None
    stone_cross_section_visible: bool | None = None
    seat_or_bearing_visible: bool | None = None
    pavilion_clearance_visible: bool | None = None
    cut_metal_surfaces_visible: bool | None = None
    exterior_elevation_only: bool | None = None
    evidence: tuple[str, ...] = ()


class MountingCandidateInspection(_InspectionModel):
    """Candidate-only observations, intentionally blind to expected spec facts."""

    checked: bool = True
    projections: tuple[MountingProjectionInspection, ...] = ()
    hardware_continuity: bool | None = None
    interpenetration_detected: bool | None = None
    text_or_dimensions_detected: bool | None = None
    complete_piece_visible: bool | None = None
    section: MountingSectionInspection = Field(
        default_factory=MountingSectionInspection
    )
    score: float | None = Field(default=None, ge=0, le=100)
    notes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def require_unique_projection_rows(self) -> MountingCandidateInspection:
        values = tuple(item.projection for item in self.projections)
        if len(values) != len(set(values)):
            raise ValueError("mounting projection observations must be unique")
        return self


class MountingFidelityInspection(_InspectionModel):
    """Source/spec comparison limited to visually supportable identity facts."""

    checked: bool = True
    center_shape_matches_source: bool | None = None
    center_shape_matches_spec: bool | None = None
    center_visual_identity_matches_spec: bool | None = None
    major_components_match: bool | None = None
    stone_count_matches: bool | None = None
    prong_count_matches: bool | None = None
    differences: tuple[str, ...] = ()
    score: float | None = Field(default=None, ge=0, le=100)
    notes: tuple[str, ...] = ()


CandidateAuditResult = MountingCandidateInspection | Mapping[str, object]
FidelityAuditResult = MountingFidelityInspection | Mapping[str, object]
CandidateAudit = Callable[[ImageAgentPlan, bytes], CandidateAuditResult]
FidelityAudit = Callable[[ImageAgentPlan, bytes, bytes], FidelityAuditResult]


_MOUNTING_CANDIDATE_AUDIT_SYSTEM = """\
You are a skeptical technical-illustration QA inspector. Inspect ONE candidate
mounting-view composite without assuming the requested labels are correct.
Identify plan, front, side, and section panels by their actual geometry.

Return JSON only:
{"checked": true,
 "projections": [
   {"projection": "plan|front|side|section", "present": true|false|null,
    "notes": ["specific panel evidence"]}],
 "hardware_continuity": true|false|null,
 "interpenetration_detected": true|false|null,
 "text_or_dimensions_detected": true|false|null,
 "complete_piece_visible": true|false|null,
 "section": {
   "panel_present": true|false|null,
   "center_axis_cut": true|false|null,
   "stone_cross_section_visible": true|false|null,
   "seat_or_bearing_visible": true|false|null,
   "pavilion_clearance_visible": true|false|null,
   "cut_metal_surfaces_visible": true|false|null,
   "exterior_elevation_only": true|false|null,
   "evidence": ["specific section evidence"]},
 "score": 0-100,
 "notes": ["brief structural evidence"]}

A true section must cut through the center-stone axis and expose the stone
profile, seat/bearing relationship, pavilion clearance, and cut/interior metal
through the gallery, undergallery, or head connection. Another exterior front
or side elevation is NOT a section, even if it shows prongs or transparent-like
interior lines. hardware_continuity is false for a floating stone, a prong that
does not root in metal, a broken gallery or undergallery, or a head that does
not connect to shoulders/shank. interpenetration_detected is true when metal
passes impossibly through a stone or solid components occupy the same space.
Dimension leaders, arrows, tick marks, numeric callouts, captions, labels,
logos, signatures, or watermarks all count as text_or_dimensions_detected;
blank dimension arrows still count. complete_piece_visible requires every
requested view to show the entire relevant piece without crop or omission.
Use null only when the pixels genuinely cannot establish a fact."""


_MOUNTING_FIDELITY_AUDIT_SYSTEM = """\
You compare TWO images. The FIRST is the approved jewelry source and the SECOND
is an AI-drawn mounting-view composite. Judge only visible design fidelity; do
not claim that pixels prove hidden construction, exact dimensions, material
assay, manufacturability, or factory authority.

Return JSON only:
{"checked": true,
 "center_shape_matches_source": true|false|null,
 "center_shape_matches_spec": true|false|null,
 "center_visual_identity_matches_spec": true|false|null,
 "major_components_match": true|false|null,
 "stone_count_matches": true|false|null,
 "prong_count_matches": true|false|null,
 "differences": ["specific source/spec-to-candidate difference"],
 "score": 0-100,
 "notes": ["brief evidence"]}

Center shape covers the visible outline and cut family: cushion, oval, round,
emerald/step-cut, pear, marquise, and other families are not interchangeable.
center_visual_identity_matches_spec covers only spec facts a line drawing can
show, such as center role, outline/cut family, setting relationship, and prong
topology; do not pretend linework proves gemstone species or color. Inventory
every major visible component and count center prongs separately from halo or
side-stone hardware. A visually attractive redraw still fails when it changes
shape, component inventory, stone count, prong count, or topology. Use null
only when occlusion or projection makes a complete comparison impossible."""


def _requested_projections(plan: ImageAgentPlan) -> tuple[MountingProjection, ...]:
    """Read future canonical plan shapes while retaining a safe first default."""

    normalized = plan.normalized_intent
    raw: object = normalized.get("requested_projections")
    mounting = normalized.get("mounting_hardware")
    if raw is None and isinstance(mounting, dict):
        raw = mounting.get("required_views") or mounting.get("views")

    values: list[str] = []
    if isinstance(raw, (list, tuple)):
        for item in raw:
            value = item.get("view") if isinstance(item, dict) else item
            if isinstance(value, str):
                values.append(value.lower().strip())
    allowed = {"plan", "front", "side", "section"}
    selected = tuple(dict.fromkeys(
        value for value in values if value in allowed
    ))
    return selected or ("plan", "front", "side", "section")


def _default_candidate_audit(
    plan: ImageAgentPlan,
    candidate: bytes,
) -> MountingCandidateInspection:
    requested = _requested_projections(plan)
    data = vision_json(
        _MOUNTING_CANDIDATE_AUDIT_SYSTEM,
        candidate,
        "REQUESTED PROJECTIONS: " + json.dumps(requested),
    )
    return MountingCandidateInspection.model_validate(data)


def _default_fidelity_audit(
    plan: ImageAgentPlan,
    source: bytes,
    candidate: bytes,
) -> MountingFidelityInspection:
    data = vision_json_pair(
        _MOUNTING_FIDELITY_AUDIT_SYSTEM,
        source,
        candidate,
        "VISUALLY RELEVANT VALIDATED SPEC FACTS: "
        + json.dumps(plan.spec_facts, sort_keys=True),
    )
    return MountingFidelityInspection.model_validate(data)


def _tri_state_all(values: tuple[bool | None, ...]) -> bool | None:
    if any(value is False for value in values):
        return False
    if values and all(value is True for value in values):
        return True
    return None


def _projection_result(
    item: MountingCandidateInspection,
    requested: tuple[MountingProjection, ...],
) -> tuple[bool | None, dict[str, object]]:
    observed = {row.projection: row.present for row in item.projections}
    if not item.checked:
        result = None
    else:
        values = tuple(observed.get(projection, False) for projection in requested)
        result = _tri_state_all(values)
    return result, {
        "requested": list(requested),
        "observed": observed,
    }


def _section_result(
    item: MountingCandidateInspection,
) -> tuple[bool | None, dict[str, object]]:
    section = item.section
    required = (
        section.panel_present,
        section.center_axis_cut,
        section.stone_cross_section_visible,
        section.seat_or_bearing_visible,
        section.pavilion_clearance_visible,
        section.cut_metal_surfaces_visible,
    )
    if not item.checked:
        result = None
    elif section.exterior_elevation_only is True or any(
        value is False for value in required
    ):
        result = False
    elif all(value is True for value in required) and (
        section.exterior_elevation_only is False
    ):
        result = True
    else:
        result = None
    return result, section.model_dump(mode="json")


def _hardware_result(
    item: MountingCandidateInspection,
) -> tuple[bool | None, dict[str, object]]:
    if not item.checked:
        result = None
    elif item.hardware_continuity is False or (
        item.interpenetration_detected is True
    ):
        result = False
    elif item.hardware_continuity is True and (
        item.interpenetration_detected is False
    ):
        result = True
    else:
        result = None
    return result, {
        "hardware_continuity": item.hardware_continuity,
        "interpenetration_detected": item.interpenetration_detected,
    }


def _center_result(
    item: MountingFidelityInspection,
) -> tuple[bool | None, dict[str, object]]:
    result = (
        None if not item.checked else
        _tri_state_all((
            item.center_shape_matches_source,
            item.center_shape_matches_spec,
            item.center_visual_identity_matches_spec,
        ))
    )
    return result, {
        "center_shape_matches_source": item.center_shape_matches_source,
        "center_shape_matches_spec": item.center_shape_matches_spec,
        "center_visual_identity_matches_spec": (
            item.center_visual_identity_matches_spec
        ),
        "differences": list(item.differences),
    }


def _component_result(
    item: MountingFidelityInspection,
) -> tuple[bool | None, dict[str, object]]:
    result = (
        None if not item.checked else
        _tri_state_all((
            item.major_components_match,
            item.stone_count_matches,
            item.prong_count_matches,
        ))
    )
    return result, {
        "major_components_match": item.major_components_match,
        "stone_count_matches": item.stone_count_matches,
        "prong_count_matches": item.prong_count_matches,
        "differences": list(item.differences),
    }


def _observed_check(
    code: str,
    observed: bool | None,
    *,
    passed_message: str,
    failed_message: str,
    unknown_message: str,
    evidence: dict[str, object] | None = None,
) -> QualityCheck:
    if observed is True:
        return QualityCheck(
            code=code,
            passed=True,
            severity=CheckSeverity.HARD,
            message=passed_message,
            evidence=evidence or {},
        )
    if observed is False:
        return QualityCheck(
            code=code,
            passed=False,
            severity=CheckSeverity.HARD,
            message=failed_message,
            evidence=evidence or {},
        )
    return QualityCheck(
        code=code,
        passed=False,
        severity=CheckSeverity.WARNING,
        message=unknown_message,
        evidence=evidence or {},
    )


def _report(
    checks: list[QualityCheck],
    *,
    score: float | None,
    notes: tuple[str, ...],
) -> ImageQualityReport:
    if any(
        not check.passed and check.severity is CheckSeverity.HARD
        for check in checks
    ):
        verdict = QualityVerdict.FAIL
    elif any(not check.passed for check in checks):
        verdict = QualityVerdict.WARN
    else:
        verdict = QualityVerdict.PASS
    return ImageQualityReport(
        verdict=verdict,
        checks=tuple(checks),
        score=score,
        notes=notes,
    )


class MountingViewQualityEvaluator:
    """Quality evaluator compatible with ``JewelryImageAgent.evaluate`` calls."""

    def __init__(
        self,
        *,
        candidate_audit: CandidateAudit | None = None,
        fidelity_audit: FidelityAudit | None = None,
    ) -> None:
        self._candidate_audit = candidate_audit or _default_candidate_audit
        self._fidelity_audit = fidelity_audit or _default_fidelity_audit

    def evaluate(
        self,
        plan: ImageAgentPlan,
        candidate: bytes,
        *,
        source_image: bytes | None,
        mask_bytes: bytes | None,
    ) -> ImageQualityReport:
        del mask_bytes  # Mounting sheets are full-composite proposals, not mask edits.

        candidate_audit_available = True
        try:
            raw_candidate = self._candidate_audit(plan, candidate)
            candidate_item = (
                raw_candidate if isinstance(
                    raw_candidate, MountingCandidateInspection
                ) else MountingCandidateInspection.model_validate(raw_candidate)
            )
        except Exception as exc:
            candidate_audit_available = False
            candidate_item = MountingCandidateInspection(
                checked=False,
                notes=(f"candidate mounting audit unavailable: {exc}",),
            )

        fidelity_audit_available = source_image is not None
        if source_image is None:
            fidelity_item = MountingFidelityInspection(
                checked=False,
                notes=("source image unavailable for mounting fidelity audit",),
            )
        else:
            try:
                raw_fidelity = self._fidelity_audit(
                    plan, source_image, candidate
                )
                fidelity_item = (
                    raw_fidelity if isinstance(
                        raw_fidelity, MountingFidelityInspection
                    ) else MountingFidelityInspection.model_validate(raw_fidelity)
                )
            except Exception as exc:
                fidelity_audit_available = False
                fidelity_item = MountingFidelityInspection(
                    checked=False,
                    notes=(f"mounting fidelity audit unavailable: {exc}",),
                )

        requested = _requested_projections(plan)
        projection, projection_evidence = _projection_result(
            candidate_item, requested
        )
        center, center_evidence = _center_result(fidelity_item)
        components, component_evidence = _component_result(fidelity_item)
        hardware, hardware_evidence = _hardware_result(candidate_item)
        section, section_evidence = _section_result(candidate_item)

        checks: list[QualityCheck] = []
        if not candidate_audit_available or not candidate_item.checked:
            checks.append(QualityCheck(
                code="mounting:candidate_audit_unavailable",
                passed=False,
                severity=CheckSeverity.WARNING,
                message=(
                    "candidate mounting structure could not be independently "
                    "audited; designer review is required"
                ),
            ))
        if not fidelity_audit_available or not fidelity_item.checked:
            checks.append(QualityCheck(
                code="mounting:fidelity_audit_unavailable",
                passed=False,
                severity=CheckSeverity.WARNING,
                message=(
                    "source-to-candidate mounting fidelity could not be "
                    "independently audited; designer review is required"
                ),
            ))

        checks.extend((
            _observed_check(
                "mounting:requested_projections",
                projection,
                passed_message="every requested mounting projection is present",
                failed_message=(
                    "one or more requested mounting projections are missing or "
                    "misidentified"
                ),
                unknown_message=(
                    "complete requested-projection coverage could not be confirmed"
                ),
                evidence=projection_evidence,
            ),
            _observed_check(
                "mounting:center_identity",
                center,
                passed_message=(
                    "center outline, cut family, and visually expressible spec "
                    "identity match the approved source/spec"
                ),
                failed_message=(
                    "center outline, cut family, or visually expressible spec "
                    "identity drifted from the approved source/spec"
                ),
                unknown_message=(
                    "center shape and spec identity could not be fully confirmed"
                ),
                evidence=center_evidence,
            ),
            _observed_check(
                "mounting:component_count_fidelity",
                components,
                passed_message=(
                    "major components, stone inventory, and prong count remain faithful"
                ),
                failed_message=(
                    "major components, stone inventory, or prong count changed"
                ),
                unknown_message=(
                    "complete component and count fidelity could not be confirmed"
                ),
                evidence=component_evidence,
            ),
            _observed_check(
                "mounting:hardware_continuity",
                hardware,
                passed_message=(
                    "stones and mounting hardware form continuous, non-intersecting "
                    "structural relationships"
                ),
                failed_message=(
                    "mounting contains disconnected/floating hardware or impossible "
                    "metal-through-stone/component interpenetration"
                ),
                unknown_message=(
                    "mounting continuity and non-interpenetration could not be "
                    "fully confirmed"
                ),
                evidence=hardware_evidence,
            ),
        ))
        if "section" in requested:
            checks.append(_observed_check(
                "mounting:true_section",
                section,
                passed_message=(
                    "candidate includes a true center-axis cut section with stone, "
                    "seat, clearance, and cut/interior metal evidence"
                ),
                failed_message=(
                    "candidate is missing a true center-axis cut section or "
                    "substitutes an exterior elevation"
                ),
                unknown_message=(
                    "true center-axis section evidence could not be confirmed"
                ),
                evidence=section_evidence,
            ))

        no_text = (
            None if not candidate_item.checked
            or candidate_item.text_or_dimensions_detected is None
            else not candidate_item.text_or_dimensions_detected
        )
        checks.extend((
            _observed_check(
                "mounting:no_text_or_dimensions",
                no_text,
                passed_message=(
                    "candidate contains no model-authored text, dimensions, "
                    "leaders, arrows, branding, or watermark"
                ),
                failed_message=(
                    "candidate contains model-authored text, dimension graphics, "
                    "branding, or watermark"
                ),
                unknown_message=(
                    "absence of model-authored text and dimensions could not be "
                    "confirmed"
                ),
                evidence={
                    "text_or_dimensions_detected": (
                        candidate_item.text_or_dimensions_detected
                    ),
                },
            ),
            _observed_check(
                "mounting:complete_uncropped_piece",
                (
                    candidate_item.complete_piece_visible
                    if candidate_item.checked else None
                ),
                passed_message=(
                    "every requested view shows the complete uncropped piece"
                ),
                failed_message=(
                    "one or more requested views crop or omit part of the piece"
                ),
                unknown_message=(
                    "complete uncropped piece coverage could not be confirmed"
                ),
                evidence={
                    "complete_piece_visible": (
                        candidate_item.complete_piece_visible
                    ),
                },
            ),
            QualityCheck(
                code="factory_authority",
                passed=False,
                severity=CheckSeverity.WARNING,
                message=(
                    "AI-drawn mounting geometry is a designer-review proposal, "
                    "not factory authority; designer confirmation and "
                    "tolerance-bearing CAD or a verified master are required"
                ),
                evidence={
                    "factory_authoritative": False,
                    "designer_confirmation_required": True,
                },
            ),
        ))

        scores = [
            value for value in (candidate_item.score, fidelity_item.score)
            if value is not None
        ]
        score = min(scores) if scores else None
        return _report(
            checks,
            score=score,
            notes=(
                *candidate_item.notes,
                *candidate_item.section.evidence,
                *fidelity_item.notes,
                *fidelity_item.differences,
            ),
        )

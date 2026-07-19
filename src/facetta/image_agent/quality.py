"""Jewelry-specific QA gates for render and edit candidates."""

from __future__ import annotations

import json
import io
from collections.abc import Callable
from typing import Protocol

from facetta.config import env_value
from facetta.creative_symmetry import (
    JEWELRY_SYMMETRY_CONTRACT,
    JEWELRY_SYMMETRY_REPAIR_CONTRACT,
    SIX_LEAF_RUBY_PATTERN_CONTRACT,
)
from facetta.image_agent.contracts import (
    BlindCountInspection,
    ChainStyleEditInspection,
    CheckSeverity,
    CreativeRenderInspection,
    DesignerEditDomain,
    EditCrossInspection,
    EditInspection,
    ImageAgentPlan,
    ImageOperation,
    ImageQualityReport,
    NecklaceSymmetryAudit,
    QualityCheck,
    QualityVerdict,
    RenderCrossInspection,
    RenderInspection,
    SixLeafRubyPatternInspection,
)
from facetta.image_agent.drift import (
    inside_mask_effect,
    inside_mask_region_effects,
    outside_mask_drift,
)
from facetta.image_agent.localization import (
    center_stone_footprint_evidence,
    crop_chromatic_center_assembly,
)
from facetta.necklace_symmetry import evaluate_necklace_symmetry_audits
from facetta.ruby_leaf_pattern import (
    canonical_six_leaf_coverage_audits,
    evaluate_six_leaf_ruby_pattern_audits,
)
from facetta.image_agent.vision import (
    VisionProviderUnavailable,
    check_design_consistency,
    openai_vision_json,
    openai_vision_json_pair,
    vision_json,
    vision_json_pair,
)
from facetta.image_agent.providers import (
    is_xai_quota_exhaustion,
    note_xai_quota_exhausted,
    xai_quota_cooldown_active,
)


def _qa_vision_json(
    system: str,
    image: bytes,
    user_text: str,
    response_schema: dict | None = None,
) -> dict:
    """Keep Grok primary, retrying only provider-unavailable QA with OpenAI."""

    if xai_quota_cooldown_active() and env_value("OPENAI_API_KEY"):
        return openai_vision_json(
            system,
            image,
            user_text,
            response_schema=response_schema,
        )
    try:
        return vision_json(system, image, user_text)
    except VisionProviderUnavailable as exc:
        if is_xai_quota_exhaustion(exc):
            note_xai_quota_exhausted()
        if not env_value("OPENAI_API_KEY"):
            raise
        return openai_vision_json(
            system,
            image,
            user_text,
            response_schema=response_schema,
        )


def _qa_vision_json_pair(
    system: str,
    image_a: bytes,
    image_b: bytes,
    user_text: str,
) -> dict:
    """Keep Grok primary for pair QA with one narrow availability fallback."""

    if xai_quota_cooldown_active() and env_value("OPENAI_API_KEY"):
        return openai_vision_json_pair(system, image_a, image_b, user_text)
    try:
        return vision_json_pair(system, image_a, image_b, user_text)
    except VisionProviderUnavailable as exc:
        if is_xai_quota_exhaustion(exc):
            note_xai_quota_exhausted()
        if not env_value("OPENAI_API_KEY"):
            raise
        return openai_vision_json_pair(system, image_a, image_b, user_text)


class ImageInspector(Protocol):
    def inspect_render(
        self,
        plan: ImageAgentPlan,
        candidate: bytes,
        *,
        reference: bytes | None,
    ) -> RenderInspection: ...

    def inspect_edit(
        self,
        plan: ImageAgentPlan,
        reference: bytes,
        candidate: bytes,
    ) -> EditInspection: ...


class EditCrossInspector(Protocol):
    def inspect_edit(
        self,
        plan: ImageAgentPlan,
        reference: bytes,
        candidate: bytes,
    ) -> EditCrossInspection: ...


class RenderCrossInspector(Protocol):
    def inspect_render(
        self,
        plan: ImageAgentPlan,
        candidate: bytes,
    ) -> RenderCrossInspection: ...


class CreativeRenderInspector(Protocol):
    def inspect_render(
        self,
        plan: ImageAgentPlan,
        reference: bytes,
        candidate: bytes,
    ) -> CreativeRenderInspection: ...


class PromptCreativeRenderInspector(Protocol):
    def inspect_render(
        self,
        plan: ImageAgentPlan,
        candidate: bytes,
    ) -> CreativeRenderInspection: ...


class SixLeafRubyPatternInspector(Protocol):
    def inspect_render(
        self,
        plan: ImageAgentPlan,
        candidate: bytes,
        necklace_audits: tuple[NecklaceSymmetryAudit, ...],
    ) -> SixLeafRubyPatternInspection: ...


_RENDER_QA_SYSTEM = """\
You are the visual QA guard for a fine-jewelry manufacturing workflow. Inspect
the candidate ring against the expected facts supplied by the user. Do not
claim that a raster image proves millimeters or carat weight.

Return JSON only:
{"jewelry_type_matches": true|false|null,
 "center_species_matches": true|false|null,
 "cut_family_matches": true|false|null,
 "center_color_matches": true|false|null,
 "metal_matches": true|false|null,
 "major_components_match": true|false|null,
 "setting_matches": true|false|null,
 "stone_count_matches": true|false|null,
 "text_or_branding_detected": true|false|null,
 "reference_consistent": true|false|null,
 "exact_dimensions_credible": true|false|null,
 "exact_carat_credible": true|false|null,
 "score": 0-100,
 "notes": ["brief evidence"]}

Use null only when a fact truly cannot be visually assessed. Any added or
missing major component, wrong center stone/cut/color, wrong metal, visibly
wrong setting/prongs, assessable count mismatch, text, logo, watermark, or
invented brand is a real mismatch. exact_dimensions_credible and
exact_carat_credible mean merely visually plausible, never measured proof."""


_RENDER_QA_WITH_REFERENCE_SYSTEM = _RENDER_QA_SYSTEM + """

The FIRST image is the approved source/reference and the SECOND is the
candidate. reference_consistent is false for any unrequested design identity,
component, proportion, setting, stone, or metal change. Ignore presentation,
lighting, and background differences unless those are frozen by the request."""


_CREATIVE_RENDER_QA_SYSTEM = """\
You compare a designer-supplied jewelry image or drawing with a generated
beauty render. The FIRST image is the source and the SECOND is the candidate.
Do not score, label, or infer whether the source is rough, professional,
complete, skilled, or attractive. Judge only the generated candidate.

Return JSON only:
{"observed_jewelry_type": "ring|necklace|earrings|bracelet|brooch|other|unclear",
 "coherent_jewelry_render": true|false|null,
 "complete_piece_visible": true|false|null,
 "source_design_preserved": true|false|null,
 "visible_components_preserved": true|false|null,
 "local_geometry_preserved": true|false|null,
 "repeated_element_pattern_preserved": true|false|null,
 "stone_shape_and_cut_family_preserved": true|false|null,
 "requested_presentation_applied": true|false|null,
 "symmetry_expectation_matches": true|false|null,
 "symmetry_observations": ["specific left/right or radial evidence"],
 "six_leaf_ruby_pattern_audits": [{"side":"left","position_from_center":1,"ruby_component":"specific ruby motif","complete_motif_assessable":true|false|null,"leaf_count":6,"diamond_leaf_count":3,"tsavorite_leaf_count":3,"material_sequence":["diamond","tsavorite","diamond","tsavorite","diamond","tsavorite"],"whole_leaf_treatments":true|false|null,"observation":"specific sequence evidence"}],
 "necklace_symmetry_audits": [{"expectation":"bilateral|explicit_asymmetry|source_asymmetry","centerline_anchor":"visible center element","complete_piece_assessable":true|false|null,"left_count":1,"right_count":1,"pair_audits":[{"position_from_center":1,"left_component":"specific element","right_component":"specific element","motif_order_matches":true|false|null,"orientation_matches":true|false|null,"spacing_matches":true|false|null,"scale_matches":true|false|null,"metal_treatment_matches":true|false|null,"pave_coverage_matches":true|false|null,"gemstone_treatment_matches":true|false|null,"connection_type_matches":true|false|null,"authorized_differences":[],"observation":"specific comparison"}],"unpaired_left":[],"unpaired_right":[],"unpaired_elements_authorized":false,"requested_asymmetry_preserved":null,"unrequested_differences_absent":true|false|null}],
 "text_or_branding_detected": true|false|null,
 "major_unintended_changes": ["specific visible difference"],
 "score": 0-100,
 "notes": ["brief visual evidence"]}

source_design_preserved covers the visible silhouette, topology, distinctive
motifs, relative proportions, stone placement, and component arrangement.
visible_components_preserved is false if a visible stone, link, setting,
decorative element, or major component was added, removed, replaced, or moved
without instruction. Before answering, inventory the source from center outward
and compare each visible local region independently: center stone and setting,
surround/halo panels, left and right shoulders, gallery, and shank.
local_geometry_preserved is false when any visible contour, opening, support,
panel shape, shoulder transition, gallery edge, or shank profile is silently
rounded, simplified, or redesigned. repeated_element_pattern_preserved is false
when the candidate changes the count, shape, order, spacing, or type of a
visible repeated motif, panel, link, channel, stone row, or ladder pattern. For
example, rectangular shank panels becoming a row of round pavé stones is false
even if both versions look attractive. stone_shape_and_cut_family_preserved is
false when a visible center or side stone outline/cut family changes, including
step-cut versus brilliant-style facet architecture when assessable. A polished
material interpretation is allowed; a silent redesign is not. Do not claim
pixels prove dimensions, carat, hidden geometry, manufacturability, or a factory
specification. Use null only when the selected view truly cannot establish a
fact, and identify the exact occlusion in notes.

symmetry_expectation_matches means the candidate preserves the source's
visible intentional symmetry or intentional asymmetry. Compare corresponding
left/right shoulders, strands, links, motifs, stone treatments, metal/pave
coverage, and repeated sequences. A mismatch is false unless the source or
designer instruction explicitly authorizes that difference. Record the exact
corresponding elements inspected in symmetry_observations.
For a necklace, pendant, choker, collar, lariat, torque, or neckpiece, return
exactly one necklace_symmetry_audits entry. Inventory both strands completely
from the named centerline anchor outward. One pair_audits row is required for
every corresponding position. A bilateral row must assess every match field;
left_count and right_count are strand inventory counts, and each must exactly
equal the number of pair_audits rows when there are no unpaired elements.
Do not summarize several unlike links as one row. authorized_differences stays
empty unless the designer explicitly requested that exact difference or the
identity source visibly establishes it.

text_or_branding_detected is an ABSOLUTE inspection of the SECOND candidate
image only. Ignore labels, arrows, handwriting, captions, dimensions, logos,
signatures, or watermarks that appear only in the FIRST source image. Removing
source annotation or overlay text is permitted output hygiene and is not a
jewelry design change. It is true only when non-jewelry text or branding is
visible in the SECOND candidate; do not count a physical jewelry engraving."""


_SKEPTICAL_CREATIVE_RENDER_AUDIT_SYSTEM = """\
You are the independent skeptical source-fidelity auditor. The FIRST image is
one designer-selected view of a jewelry design. The SECOND is a proposed beauty
render. An attractive, coherent result is still a failure if it silently
redesigns visible geometry.

Work in two stages before returning JSON: first inventory the FIRST image from
center outward without looking for confirmation; then compare the SECOND image
region by region. Explicitly inspect center outline and facet family, every
surround panel, repeated motif count/shape/order/spacing, left shoulder, right
shoulder, gallery openings/supports, and the visible shank profile/pattern.

Return JSON only:
{"observed_jewelry_type": "ring|necklace|earrings|bracelet|brooch|other|unclear",
 "coherent_jewelry_render": true|false|null,
 "complete_piece_visible": true|false|null,
 "source_design_preserved": true|false|null,
 "visible_components_preserved": true|false|null,
 "local_geometry_preserved": true|false|null,
 "repeated_element_pattern_preserved": true|false|null,
 "stone_shape_and_cut_family_preserved": true|false|null,
 "requested_presentation_applied": true|false|null,
 "symmetry_expectation_matches": true|false|null,
 "symmetry_observations": ["specific left/right or radial evidence"],
 "six_leaf_ruby_pattern_audits": [{"side":"left","position_from_center":1,"ruby_component":"specific ruby motif","complete_motif_assessable":true|false|null,"leaf_count":6,"diamond_leaf_count":3,"tsavorite_leaf_count":3,"material_sequence":["diamond","tsavorite","diamond","tsavorite","diamond","tsavorite"],"whole_leaf_treatments":true|false|null,"observation":"specific sequence evidence"}],
 "necklace_symmetry_audits": [{"expectation":"bilateral|explicit_asymmetry|source_asymmetry","centerline_anchor":"visible center element","complete_piece_assessable":true|false|null,"left_count":1,"right_count":1,"pair_audits":[{"position_from_center":1,"left_component":"specific element","right_component":"specific element","motif_order_matches":true|false|null,"orientation_matches":true|false|null,"spacing_matches":true|false|null,"scale_matches":true|false|null,"metal_treatment_matches":true|false|null,"pave_coverage_matches":true|false|null,"gemstone_treatment_matches":true|false|null,"connection_type_matches":true|false|null,"authorized_differences":[],"observation":"specific comparison"}],"unpaired_left":[],"unpaired_right":[],"unpaired_elements_authorized":false,"requested_asymmetry_preserved":null,"unrequested_differences_absent":true|false|null}],
 "text_or_branding_detected": true|false|null,
 "major_unintended_changes": ["specific source-to-candidate difference"],
 "score": 0-100,
 "notes": ["brief region-specific evidence"]}

Do not excuse rectangular panels becoming round pavé, a ladder/channel pattern
being simplified, step-cut facets becoming brilliant-style facets, altered
shoulder transitions, missing gallery members, or rounded angular contours.
Ignore only lighting, background, and legitimate material realism. Do not infer
dimensions, hidden geometry, manufacturability, or source skill. Use null only
for a fact genuinely occluded in the selected source view.

Audit corresponding left/right or radial components independently. Set
symmetry_expectation_matches false for any unrequested mismatch in component
count, motif order, orientation, spacing, scale, metal treatment, pave
coverage, stone treatment, or connection type. Preserve intentional asymmetry
that is visibly present in the source or explicitly named by the designer.
Record the compared elements in symmetry_observations.
For every necklace-family piece, also return exactly one structured
necklace_symmetry_audits entry and inventory every corresponding position from
the visible centerline outward. Assess every pair field independently. Never
set left_count or right_count to a representative value: each must exactly
equal the number of pair_audits rows when there are no unpaired elements. Never
authorize a difference merely because the generated candidate contains it.

text_or_branding_detected inspects the SECOND candidate image only. Ignore
labels, arrows, handwriting, captions, dimension text, logos, signatures, or
watermarks that appear only in the FIRST source. Their removal is permitted
output hygiene, not jewelry drift. Return true only for non-jewelry text or
branding visible in the SECOND candidate; do not count physical engraving."""


_COMPARISON_VIEW_QA_CONTEXT = """\
COMPARISON-ANGLE QA MODE: The FIRST image is the exact primary direction and
the SECOND is deliberately rendered as a different camera view of that same
physical design. A changed projection is authorized; a changed design is not.

Do not compare raw 2D pixel coordinates or projected outlines. Perspective,
foreshortening, apparent spacing, overlap, and visibility of side/gallery
surfaces naturally change with camera rotation. Those projection effects alone
must never make source_design_preserved, visible_components_preserved,
local_geometry_preserved, repeated_element_pattern_preserved, or
stone_shape_and_cut_family_preserved false. If camera occlusion prevents an
exact comparison, return null for only that unassessable fact, not false.

Instead establish same-design identity from view-invariant evidence. Inventory
and compare the center stone outline/cut/color, the exact assessable center
holding-claw count and arrangement, each left/right side-stone count and shape,
repeated-element count/order, setting topology, band/shank construction and
profile, material, and finish. Set the preservation fields true when those
physical facts correspond despite the new projection. Keep them false for a
real count mismatch; an added, missing, replaced, or relocated component; a
changed stone outline/cut; a changed prong or setting; a split or ornamented
band replacing a plain band; or any actual topology/design-form change.
requested_presentation_applied is true only if the SECOND image supplies the
prescribed three-quarter review angle while keeping the complete piece
reviewable. Never relax identity, count, shape, setting, or topology checks."""


_MARKED_REGION_EDIT_QA_CONTEXT = """\
MARKED-REGION EDIT QA MODE: The designer explicitly authorized the numbered
changes named in the request, each only inside its named marked region. Judge
preservation relative to those requested changes, not against literal identity
inside the authorized regions.

Do not set source_design_preserved, visible_components_preserved,
local_geometry_preserved, repeated_element_pattern_preserved, or
stone_shape_and_cut_family_preserved false merely because the SECOND image
applies an explicitly requested local color, surface, finish, contour, setting,
or construction-detail change in the named region. For example, making named
prongs finer is an authorized local contour change when the request says so.
Set the relevant preservation field true when the requested local change is the
only visible difference affecting that fact.

Remain strict about everything not requested. A preservation field is false for
any added, removed, replaced, or moved component; changed count, topology,
order, spacing, stone shape, setting, or contour that was not explicitly named;
or any unrelated redesign inside or outside the marked regions.
requested_presentation_applied is true only when every numbered marked change is
visibly applied. The deterministic mask check independently enforces that all
pixels outside the combined authorized mask remain fixed. Never infer factory
authority from this review-only visual candidate."""


_DESCRIBED_VISUAL_EDIT_QA_CONTEXT = """\
DESCRIBED VISUAL EDIT QA MODE: The designer explicitly authorized every visible
change named in the request, and may have requested several changes together.
Judge preservation relative to those named changes rather than requiring
literal source identity for an attribute the designer asked to change.

Do not set source_design_preserved, visible_components_preserved,
local_geometry_preserved, repeated_element_pattern_preserved, or
stone_shape_and_cut_family_preserved false merely because the SECOND image
applies an explicitly requested change to color, material, surface, finish,
stones, repeated motifs, visible contour, setting, or construction detail. Set
the relevant preservation field true when the requested changes are the only
visible differences affecting that fact. requested_presentation_applied is
true only when every requested change is visibly applied.

Remain strict about every unmentioned region and attribute. Any added, removed,
replaced, moved, or redesigned element that the request did not name is drift.
When a request names a bilateral or repeated class without limiting it to one
side, require the change to be applied consistently to corresponding elements;
an explicitly side-specific request may authorize only that named difference.
Never infer specification, dimensional, manufacturing, or factory authority
from this temporary review candidate."""


_SYMMETRY_REPAIR_QA_CONTEXT = """\
This is an EXPLICIT BILATERAL SYMMETRY REPAIR. The designer has identified the
source's unmatched left/right treatment as the defect to correct. Do not fail a
preservation field merely because the candidate fixes that explicitly named
mismatch. Treat source_design_preserved, visible_components_preserved,
local_geometry_preserved, and repeated_element_pattern_preserved as true when
the only difference is the minimum corresponding left/right change needed to
make the sequence match.

Remain strict about the center element and every unmentioned detail. Set the
relevant preservation field false for any unrelated change to component count,
motif order, spacing, orientation, scale, metal or pave treatment, gemstone
treatment, connection, camera, crop, background, or presentation. Set
symmetry_expectation_matches true only after comparing corresponding elements
from the centerline outward and confirming that each left/right pair now
matches the designer's requested pattern."""


_ROUGH_DRAWING_INTERPRETATION_QA_CONTEXT = """\
ROUGH-DRAWING INTERPRETATION QA MODE: The FIRST image is a low-information
designer sketch, not a finished design that can support literal local-geometry
comparison. Judge whether the SECOND image is a useful professional
interpretation of the sketch and written direction.

Require one coherent, complete jewelry piece; the requested concept; the
observable overall silhouette, center-element placement, side-element rhythm,
and balance; expected symmetry unless asymmetry was explicitly requested or is
clearly established by the sketch; and no text, logo, signature, watermark, or
invented branding. Set source_design_preserved true when those observable
high-level design signals are preserved, even when professional judgment was
needed to resolve loose or missing lines.

Do not require pixel matching, literal local contours, exact repeated-motif
topology, prong counts, or stone cut/facet identity that the rough lines cannot
establish. Polishing ambiguous geometry is not an unintended redesign. Do not
infer dimensions, hidden construction, manufacturability, or factory authority.
Photos and finished renders never use this relaxed contract."""


def _is_rough_drawing_interpretation(plan: ImageAgentPlan) -> bool:
    return "ROUGH DRAWING INTENT FALLBACK" in plan.intent


_SIX_LEAF_RUBY_QA_GUIDANCE = """\
When the direction contains SIX-LEAF RUBY PATTERN INTERPRETATION, return one
six_leaf_ruby_pattern_audits row for every governed ruby-and-leaf motif that is
visible. Count whole leaves individually; diamond_leaf_count plus
tsavorite_leaf_count must equal leaf_count. material_sequence must list all
leaves around that ruby. For a center motif, begin at the top leaf and proceed
clockwise. For a left or right motif, begin at the leaf nearest the necklace
centerline and proceed toward the top in mirrored reading directions, so equal
left/right arrays prove the same reflected material phase. Do not infer
alternation from the necklace's overall balance: record every leaf in order.
If any motif is cropped or ambiguous, set complete_motif_assessable false."""


_FOCUSED_SIX_LEAF_RUBY_QA_SYSTEM = """\
You perform one narrow forensic inventory of ruby-and-leaf motifs in a single
jewelry image. Return only the focused audit contract. Do not judge beauty,
factory readiness, or overall necklace quality.

Inventory EVERY visible ruby motif surrounded by leaves. Never return a
representative sample. The broad necklace inventory supplied by the user is a
coverage checklist: for every pair whose component description names a ruby
flower, floral ruby, or an explicit six-leaf ruby surround, return both a left
and a right audit with that exact position_from_center. Do not treat an
incidental ruby accent beside one or two ordinary leaf links as a governed
six-leaf motif. Return a center row only when the center ruby visibly has the
governed six-leaf surround. If a required motif is cropped or ambiguous, still
return its row and mark
complete_motif_assessable false instead of omitting it.

Count six whole leaves individually. Count diamond and tsavorite leaves
separately. material_sequence must contain one entry per visible leaf. For a
center motif begin at the top and proceed clockwise. For a left or right motif
begin at the leaf nearest the necklace centerline and proceed toward the top in
mirrored reading directions. Do not infer a sequence from overall color
balance. Record only what the pixels establish."""


def _creative_review_system(
    system: str,
    plan: ImageAgentPlan,
) -> str:
    """Add camera-aware semantics only to prescribed same-design comparisons."""

    contexts: list[str] = []
    if plan.intent.startswith("COMPARISON VIEW CONTRACT:"):
        contexts.append(_COMPARISON_VIEW_QA_CONTEXT)
    if plan.intent.startswith("PRE-SPEC DESCRIBED VISUAL REFINEMENT."):
        contexts.append(_DESCRIBED_VISUAL_EDIT_QA_CONTEXT)
    localization = plan.normalized_intent.get("localization")
    if (
        isinstance(localization, dict)
        and localization.get("mode") == "designer_marked_pre_spec_region"
    ):
        contexts.append(_MARKED_REGION_EDIT_QA_CONTEXT)
    if JEWELRY_SYMMETRY_REPAIR_CONTRACT in plan.intent:
        contexts.append(_SYMMETRY_REPAIR_QA_CONTEXT)
    if _is_rough_drawing_interpretation(plan):
        contexts.append(_ROUGH_DRAWING_INTERPRETATION_QA_CONTEXT)
    augmented = system + "\n\n" + _SIX_LEAF_RUBY_QA_GUIDANCE
    if not contexts:
        return augmented
    return augmented + "\n\n" + "\n\n".join(contexts)


_PROMPT_CREATIVE_RENDER_QA_SYSTEM = """\
You inspect one generated fine-jewelry concept against a designer's written
direction. Do not assume the requested piece is a ring. The candidate may be a
ring, necklace, pendant, chain, bracelet, earring, brooch, or another wearable
fine-jewelry piece.

Return JSON only:
{"observed_jewelry_type": "ring|necklace|earrings|bracelet|brooch|other|unclear",
 "coherent_jewelry_render": true|false|null,
 "complete_piece_visible": true|false|null,
 "source_design_preserved": null,
 "visible_components_preserved": null,
 "requested_presentation_applied": true|false|null,
 "explicit_counts_match": true|false,
 "explicit_stone_facts_match": true|false,
 "symmetry_expectation_matches": true|false|null,
 "symmetry_observations": ["specific left/right or radial evidence"],
 "six_leaf_ruby_pattern_audits": [{"side":"left","position_from_center":1,"ruby_component":"specific ruby motif","complete_motif_assessable":true|false|null,"leaf_count":6,"diamond_leaf_count":3,"tsavorite_leaf_count":3,"material_sequence":["diamond","tsavorite","diamond","tsavorite","diamond","tsavorite"],"whole_leaf_treatments":true|false|null,"observation":"specific sequence evidence"}],
 "necklace_symmetry_audits": [{"expectation":"bilateral|explicit_asymmetry|source_asymmetry","centerline_anchor":"visible center element","complete_piece_assessable":true|false|null,"left_count":1,"right_count":1,"pair_audits":[{"position_from_center":1,"left_component":"specific element","right_component":"specific element","motif_order_matches":true|false|null,"orientation_matches":true|false|null,"spacing_matches":true|false|null,"scale_matches":true|false|null,"metal_treatment_matches":true|false|null,"pave_coverage_matches":true|false|null,"gemstone_treatment_matches":true|false|null,"connection_type_matches":true|false|null,"authorized_differences":[],"observation":"specific comparison"}],"unpaired_left":[],"unpaired_right":[],"unpaired_elements_authorized":false,"requested_asymmetry_preserved":null,"unrequested_differences_absent":true|false|null}],
 "text_or_branding_detected": true|false|null,
 "major_unintended_changes": ["specific contradiction of the direction"],
 "score": 0-100,
 "notes": ["brief visual evidence"]}

coherent_jewelry_render means the result reads as one physically coherent
wearable jewelry design: connections, settings, stones, repeated components,
symmetry, and material response are visually plausible. It does not mean that
pixels prove manufacturability, hidden geometry, dimensions, carat, material
identity, or a factory specification. requested_presentation_applied means the
visible piece category and explicitly requested design, stone, material, color,
form, and presentation cues are present without a contradictory silent redesign.
Before deciding, inventory and count every visible repeated stone and design
element named with an explicit quantity, including quantities written as words.
explicit_counts_match must be false if any named count is higher or lower than
requested; "five" means exactly five, not five or more. Set it true when every
explicit count matches or the direction contains no explicit count.
complete_piece_visible is false when any part of the jewelry silhouette, chain
run, endpoints/clasp, pendant, or requested drop is cropped or omitted.
Before judging explicit_stone_facts_match, inventory each named gemstone group
and compare its species, visible color, cut/outline shape, and role. It is false
if a requested round-diamond group contains leaf, marquise, pear, square, or
another alternate shape, or if any other named stone fact is contradicted. Set
it true when all named stone facts match or none were specified.

Unless the designer direction explicitly requests asymmetry, conventional
jewelry symmetry is mandatory. For necklaces and pendants compare the left and
right sequence from the centerline outward, link by link, including count,
motif order, orientation, spacing, scale, metal treatment, pave coverage,
stone treatment, and connection type. For rings compare both shoulders and
bilateral halo/side-stone patterns. For earring pairs compare construction; for
bracelets and radial designs compare the repeated sequence around the piece.
Set symmetry_expectation_matches false for any unrequested mismatch, including
one corresponding element being full metal while the other is partly pave.
Set it true when the expected symmetry is visibly consistent, when an explicit
asymmetric direction is followed, or when symmetry genuinely does not apply.
Use null only when the complete-piece view cannot establish the relationship,
and record the exact evidence in symmetry_observations.
For every necklace-family piece, return exactly one structured
necklace_symmetry_audits entry. Inventory every corresponding element from the
visible centerline outward and assess each match field. left_count and
right_count must each exactly equal the number of pair_audits rows when there
are no unpaired elements; use an empty audit only
when the complete piece is genuinely not assessable.
Use null only when the candidate truly cannot establish a requested visual fact."""


_EDIT_QA_SYSTEM = """\
You compare two images of the same fine-jewelry ring. The FIRST is the source;
the SECOND is a requested edit. Judge whether the requested change happened
and whether the rest of the jewelry stayed fixed.

Return JSON only:
{"change_applied": true|false|null,
 "unintended_severity": "none|minor|major|unknown",
 "unintended_changes": ["brief concrete difference"],
 "protected_regions_preserved": true|false|null,
 "geometry_preserved": true|false|null,
 "spec_change_matches": true|false|null,
 "domain_matches": {"<required edit domain id>": true|false|null},
 "side_stone_inventory": {
   "source_visible_count": 0|null,
   "source_count_complete": true|false|null,
   "candidate_visible_count": 0|null,
   "candidate_count_complete": true|false|null,
   "source_role_counts": {"halo": 0},
   "candidate_role_counts": {"halo": 0},
   "notes": ["counting evidence"]}|null,
 "text_or_branding_detected": true|false|null,
 "score": 0-100,
 "notes": ["brief evidence"]}

major means an unrequested change to geometry, stone, count, setting, prong,
metal, or proportion. minor is presentation noise only. For visual-only work,
geometry_preserved must cover the entire jewelry design. For a spec-linked
local edit, spec_change_matches says the visible change matches the supplied
validated result facts.

The user message supplies REQUIRED EDIT DOMAINS. domain_matches must contain
exactly those domain ids and no others. Judge every required domain against the
source facts, validated result facts, and exact spec delta. Use false for an
observed mismatch and null only when that domain truly cannot be assessed in
the supplied view. Examples: center_stone_shape audits outline and facet family;
center_stone_identity/color audit the intended optical stone identity without
spillover; side_stone_inventory audits visible add/remove/count and placement;
side_stone_shape audits every affected repeated element; setting audits style
and prong count; metal_identity audits all metal surfaces without tinting gems;
band_geometry audits the requested silhouette change; design_form audits only
the explicitly changed topology. Frozen facts must remain unchanged.

When side_stone_inventory is required, count only actual non-center gemstones;
do not count prongs, beads, reflections, or the center stone. Record source and
candidate counts before deciding domain_matches. Mark a count complete only
when the view shows the complete relevant inventory. Provide per-role counts
when roles such as halo or shoulders are visually separable."""


_NECKLACE_CHAIN_EDIT_QA_SYSTEM = """\
You compare two images of the same fine-jewelry necklace. The FIRST is the
approved source and the SECOND is a requested chain-style edit. Audit the
entire visible chain before examining the frozen pendant assembly. A chain
style change is complete only when every visible chain segment and link, from
both bail connections through the visible endpoints or clasp, uses the target
link construction. Changing a few prominent links is not sufficient.

Return JSON only:
{"change_applied": true|false|null,
 "unintended_severity": "none|minor|major|unknown",
 "unintended_changes": ["brief concrete difference"],
 "protected_regions_preserved": true|false|null,
 "geometry_preserved": true|false|null,
 "spec_change_matches": true|false|null,
 "domain_matches": {"chain_style": true|false|null},
 "chain_style": {
   "target_style_matches": true|false|null,
   "complete_visible_run_matches": true|false|null,
   "chain_connections_preserved": true|false|null,
   "pendant_count_preserved": true|false|null,
   "pendant_geometry_preserved": true|false|null,
   "bail_preserved": true|false|null,
   "stones_preserved": true|false|null,
   "setting_preserved": true|false|null,
   "clasp_preserved": true|false|null,
   "source_clasp_visible": true|false|null,
   "candidate_clasp_visible": true|false|null,
   "chain_length_and_drape_preserved": true|false|null,
   "non_chain_geometry_preserved": true|false|null,
   "candidate_contains_non_jewelry_text_or_branding": true|false|null},
 "text_or_branding_detected": true|false|null,
 "score": 0-100,
 "notes": ["brief evidence"]}

Use false for an observed mismatch and null only when the view cannot establish
the fact. Any old-style link left in the visible run, missing or added pendant,
changed pendant or bail geometry, altered stone/setting/clasp, changed chain
endpoints or apparent drape, or invented component is a real mismatch. Report
source_clasp_visible and candidate_clasp_visible independently: if the source
does not show a clasp, a newly visible candidate clasp is an added component,
even when the specification names the off-frame clasp type.

candidate_contains_non_jewelry_text_or_branding is an ABSOLUTE inspection of
the SECOND image only, not a comparison. It is true for any visible caption,
handwritten signature, logo, watermark, social/platform ID, or invented brand,
even if the same overlay existed in the source. Do not count a physical jewelry
engraving explicitly represented by the spec. Removing source overlay text is
permitted output hygiene and is not unintended jewelry drift. Compare endpoints
and overall drape; treat visible link scale as qualitative only. Do not claim
that pixels prove exact chain length, link gauge, pitch, thickness, or any other
dimension."""


_SKEPTICAL_EDIT_AUDIT_SYSTEM = """\
You are the independent second reviewer for a high-trust jewelry edit. The
FIRST image is the source and the SECOND is the candidate. Another reviewer may
have already approved it; do not defer to that judgment. Start by comparing the
entire jewelry piece component by component, then decide whether the one
authorized delta happened and every frozen fact stayed fixed.

Return JSON only:
{"checked": true,
 "change_applied": true|false|null,
 "frozen_facts_preserved": true|false|null,
 "unintended_severity": "none|minor|major|unknown",
 "unintended_changes": ["specific observed difference"],
 "domain_mismatches": ["required domain id that visibly misses its target"],
 "notes": ["brief visual evidence"]}

List differences before judging them. A changed center-stone size, cut, color,
setting, prong count, side-stone count/placement, metal assignment, band
silhouette, camera/crop, or component topology is major unless the exact spec
delta authorizes it. Lighting/reflection noise alone may be minor. Use null or
unknown only when the view genuinely cannot establish the fact. Do not infer
exact millimeters or carat from pixels."""


_SKEPTICAL_NECKLACE_CHAIN_EDIT_AUDIT_SYSTEM = """\
You are the independent second reviewer for a high-trust necklace chain-style
edit. The FIRST image is the approved source and the SECOND is the candidate.
Another reviewer may have approved it; do not defer. Trace both visible chain
runs link by link from the bail connections to the clasp or endpoints. Then
compare pendant count and geometry, bail, every stone and setting, clasp,
apparent chain length/drape, metal assignment, and all non-chain geometry.

Return JSON only:
{"checked": true,
 "change_applied": true|false|null,
 "frozen_facts_preserved": true|false|null,
 "unintended_severity": "none|minor|major|unknown",
 "unintended_changes": ["specific observed difference"],
 "domain_mismatches": ["chain_style"],
 "notes": ["brief visual evidence"]}

The chain_style domain mismatches if the target link family is wrong, remains
mixed with the source style, or does not cover the complete visible chain run.
Any added/removed pendant or change to pendant, bail, stones, setting, clasp,
chain endpoints/drape, or non-chain geometry is major. A clasp visible only in
the candidate is an added component, even if the specification names a clasp
that was off-frame in the source. Any candidate caption, signature, logo,
watermark, or platform/social ID is a major output-hygiene failure; removing
such a source overlay is permitted and is not jewelry drift. Use null/unknown
when evidence is genuinely insufficient so the designer reviews it. Never infer
exact link gauge, pitch, thickness, chain length, or other dimensions from
pixels."""


_SKEPTICAL_RENDER_AUDIT_SYSTEM = """\
You are the independent second reviewer for a validated fine-jewelry ring
render. Audit the candidate against the exact specification. Another reviewer
may have already approved it; do not defer to that judgment. Inspect the center
stone, setting, individual prongs, side-stone inventory, metal, and every major
component separately before deciding.

Return JSON only:
{"checked": true,
 "jewelry_type_matches": true|false|null,
 "center_identity_matches": true|false|null,
 "center_cut_matches": true|false|null,
 "metal_matches": true|false|null,
 "setting_style_matches": true|false|null,
 "prong_count_matches": true|false|null,
 "observed_prong_count": 0|null,
 "side_stone_inventory_matches": true|false|null,
 "observed_side_stone_count": 0|null,
 "major_components_match": true|false|null,
 "differences": ["specific observed mismatch"],
 "notes": ["brief visual evidence"]}

Count actual visible center-setting prongs; do not treat halo beads or side-
stone claws as center prongs. If occlusion truly prevents an exact count, use
null rather than guessing. Count side stones only when assessable in the view.
Wrong cut family, visible species/color identity, metal assignment, setting
style, prong count, assessable side-stone inventory, or a missing/added major
component is a mismatch. Reflections are not a material change. A raster never
proves millimeters or carat."""


_BLIND_COMPONENT_COUNT_SYSTEM = """\
You are doing an expectation-free component count on one jewelry image. You
are not given a specification and must not infer what the design was supposed
to contain.

Return JSON only:
{"center_prongs_visible": 0|null,
 "center_prong_count_complete": true|false|null,
 "side_stones_visible": 0|null,
 "side_stone_count_complete": true|false|null,
 "notes": ["brief counting evidence"]}

First identify the center gemstone. Count only distinct metal prongs or claws
that physically contact and hold that center stone. Do not count halo beads,
side-stone claws, reflections, or decorative balls as center prongs. Set
center_prong_count_complete true only when the view shows the complete setting
well enough that the visible count is the total count; otherwise return the
visible count and false. Count side stones separately, excluding the center
stone. If occlusion prevents an exact total, mark the side count incomplete.
Do not guess a hidden count and do not use a typical jewelry convention."""


class GrokVisionInspector:
    """Default production inspector over the existing Grok vision seams."""

    def inspect_render(
        self,
        plan: ImageAgentPlan,
        candidate: bytes,
        *,
        reference: bytes | None,
    ) -> RenderInspection:
        ask = (
            f"Operation: {plan.operation.value}\n"
            f"Intent: {plan.intent}\n"
            "Expected facts: " + json.dumps(plan.spec_facts, sort_keys=True)
        )
        if reference:
            data = _qa_vision_json_pair(
                _RENDER_QA_WITH_REFERENCE_SYSTEM,
                reference,
                candidate,
                ask,
            )
        else:
            data = _qa_vision_json(_RENDER_QA_SYSTEM, candidate, ask)
        return RenderInspection.model_validate(data)

    def inspect_edit(
        self,
        plan: ImageAgentPlan,
        reference: bytes,
        candidate: bytes,
    ) -> EditInspection:
        delta = plan.normalized_intent.get("spec_delta", [])
        ask = (
            f"Operation: {plan.operation.value}\n"
            f"Requested change: {plan.intent}\n"
            f"Region: {plan.region_description or 'presentation only'}\n"
            "Source facts: " +
            json.dumps(plan.source_spec_facts or {}, sort_keys=True) + "\n"
            "Validated result facts: " +
            json.dumps(plan.spec_facts, sort_keys=True) + "\n"
            "Exact spec delta: " + json.dumps(delta, sort_keys=True) + "\n"
            "Frozen facts: " + json.dumps(list(plan.frozen)) + "\n"
            "REQUIRED EDIT DOMAINS: " + json.dumps(
                [domain.value for domain in plan.edit_domains]) + "\n"
            "SIDE-STONE INVENTORY CONTRACT: " + json.dumps(
                plan.normalized_intent.get(
                    "side_stone_inventory_contract", {}),
                sort_keys=True,
            ) + "\nSETTING TOPOLOGY CONTRACT: " + json.dumps(
                plan.normalized_intent.get(
                    "setting_topology_contract", {}),
                sort_keys=True,
            )
        )
        data = _qa_vision_json_pair(
            (_NECKLACE_CHAIN_EDIT_QA_SYSTEM
             if plan.is_necklace_chain_style_edit else _EDIT_QA_SYSTEM),
            reference,
            candidate,
            ask,
        )
        return EditInspection.model_validate(data)


class OpenAIVisionInspector:
    """OpenAI visual QA for renders and source-preserving image edits."""

    def inspect_render(
        self,
        plan: ImageAgentPlan,
        candidate: bytes,
        *,
        reference: bytes | None,
    ) -> RenderInspection:
        ask = (
            f"Operation: {plan.operation.value}\n"
            f"Intent: {plan.intent}\n"
            "Expected facts: " + json.dumps(plan.spec_facts, sort_keys=True)
        )
        data = (
            openai_vision_json_pair(
                _RENDER_QA_WITH_REFERENCE_SYSTEM, reference, candidate, ask)
            if reference
            else openai_vision_json(_RENDER_QA_SYSTEM, candidate, ask)
        )
        return RenderInspection.model_validate(data)

    def inspect_edit(
        self,
        plan: ImageAgentPlan,
        reference: bytes,
        candidate: bytes,
    ) -> EditInspection:
        ask = (
            f"Operation: {plan.operation.value}\n"
            f"Requested change: {plan.intent}\n"
            f"Region: {plan.region_description or 'presentation only'}\n"
            "Source facts: "
            + json.dumps(plan.source_spec_facts or {}, sort_keys=True) + "\n"
            "Validated result facts: "
            + json.dumps(plan.spec_facts, sort_keys=True) + "\n"
            "Exact spec delta: "
            + json.dumps(
                plan.normalized_intent.get("spec_delta", []), sort_keys=True)
            + "\nFrozen facts: " + json.dumps(list(plan.frozen)) + "\n"
            "REQUIRED EDIT DOMAINS: "
            + json.dumps([domain.value for domain in plan.edit_domains])
        )
        data = openai_vision_json_pair(
            (_NECKLACE_CHAIN_EDIT_QA_SYSTEM
             if plan.is_necklace_chain_style_edit else _EDIT_QA_SYSTEM),
            reference,
            candidate,
            ask,
        )
        return EditInspection.model_validate(data)


class GrokCreativeRenderInspector:
    """Neutral source-to-beauty comparative review for pre-spec candidates."""

    def inspect_render(
        self,
        plan: ImageAgentPlan,
        reference: bytes,
        candidate: bytes,
    ) -> CreativeRenderInspection:
        ask = (
            f"Designer direction: {plan.intent}\n"
            "Frozen source facts: " + json.dumps(list(plan.frozen)) + "\n"
            f"Expected output: {plan.expected_output}"
        )
        payload = _qa_vision_json_pair(
            _creative_review_system(_CREATIVE_RENDER_QA_SYSTEM, plan),
            reference,
            candidate,
            ask,
        )
        return CreativeRenderInspection.model_validate(
            _normalize_authorized_necklace_differences(payload)
        )


class OpenAICreativeRenderInspector:
    """OpenAI source-fidelity review for pre-spec visual candidates."""

    def inspect_render(
        self,
        plan: ImageAgentPlan,
        reference: bytes,
        candidate: bytes,
    ) -> CreativeRenderInspection:
        ask = (
            f"Designer direction: {plan.intent}\n"
            "Frozen source facts: " + json.dumps(list(plan.frozen)) + "\n"
            f"Expected output: {plan.expected_output}"
        )
        payload = openai_vision_json_pair(
            _creative_review_system(_CREATIVE_RENDER_QA_SYSTEM, plan),
            reference,
            candidate,
            ask,
        )
        return CreativeRenderInspection.model_validate(
            _normalize_authorized_necklace_differences(payload)
        )


class GrokSkepticalCreativeRenderInspector:
    """Prompt-diverse comparative audit that can veto attractive drift."""

    def inspect_render(
        self,
        plan: ImageAgentPlan,
        reference: bytes,
        candidate: bytes,
    ) -> CreativeRenderInspection:
        ask = (
            f"Designer direction: {plan.intent}\n"
            f"Selected source region: {plan.region_description or 'full source'}\n"
            "Frozen source facts: " + json.dumps(list(plan.frozen))
        )
        payload = _qa_vision_json_pair(
            _creative_review_system(
                _SKEPTICAL_CREATIVE_RENDER_AUDIT_SYSTEM, plan),
            reference,
            candidate,
            ask,
        )
        return CreativeRenderInspection.model_validate(
            _normalize_authorized_necklace_differences(payload)
        )


class OpenAISkepticalCreativeRenderInspector:
    """Second OpenAI pass that holds attractive but drifting references."""

    def inspect_render(
        self,
        plan: ImageAgentPlan,
        reference: bytes,
        candidate: bytes,
    ) -> CreativeRenderInspection:
        ask = (
            f"Designer direction: {plan.intent}\n"
            f"Selected source region: {plan.region_description or 'full source'}\n"
            "Frozen source facts: " + json.dumps(list(plan.frozen))
        )
        payload = openai_vision_json_pair(
            _creative_review_system(
                _SKEPTICAL_CREATIVE_RENDER_AUDIT_SYSTEM, plan),
            reference,
            candidate,
            ask,
        )
        return CreativeRenderInspection.model_validate(
            _normalize_authorized_necklace_differences(payload)
        )


_CREATIVE_MATCH_FIELDS = (
    "coherent_jewelry_render",
    "complete_piece_visible",
    "source_design_preserved",
    "visible_components_preserved",
    "local_geometry_preserved",
    "repeated_element_pattern_preserved",
    "stone_shape_and_cut_family_preserved",
    "requested_presentation_applied",
    "explicit_counts_match",
    "explicit_stone_facts_match",
    "symmetry_expectation_matches",
)


def _merge_creative_inspections(
    primary: CreativeRenderInspection,
    skeptical: CreativeRenderInspection,
) -> CreativeRenderInspection:
    """Conservative two-judge consensus for source-faithful rendering."""

    update: dict[str, object] = {}
    for field in _CREATIVE_MATCH_FIELDS:
        values = (getattr(primary, field), getattr(skeptical, field))
        update[field] = (
            False if False in values else
            True if values == (True, True) else
            None
        )
    observed_types = {
        value for value in (
            primary.observed_jewelry_type,
            skeptical.observed_jewelry_type,
        )
        if value is not None
    }
    update["observed_jewelry_type"] = (
        "necklace" if "necklace" in observed_types else
        next(iter(observed_types)) if len(observed_types) == 1 else
        "unclear" if observed_types else None
    )
    branding = (
        primary.text_or_branding_detected,
        skeptical.text_or_branding_detected,
    )
    update["text_or_branding_detected"] = (
        True if True in branding else
        False if branding == (False, False) else
        None
    )
    scores = [
        score for score in (primary.score, skeptical.score)
        if score is not None
    ]
    update["score"] = min(scores) if scores else None
    update["major_unintended_changes"] = tuple(dict.fromkeys((
        *primary.major_unintended_changes,
        *skeptical.major_unintended_changes,
    )))
    update["symmetry_observations"] = tuple(dict.fromkeys((
        *primary.symmetry_observations,
        *skeptical.symmetry_observations,
    )))
    update["necklace_symmetry_audits"] = (
        *primary.necklace_symmetry_audits,
        *skeptical.necklace_symmetry_audits,
    )
    update["six_leaf_ruby_pattern_audits"] = (
        *primary.six_leaf_ruby_pattern_audits,
        *skeptical.six_leaf_ruby_pattern_audits,
    )
    update["notes"] = (
        *(f"primary audit: {note}" for note in primary.notes),
        *(f"skeptical audit: {note}" for note in skeptical.notes),
    )
    return primary.model_copy(update=update)


def _normalize_redundant_necklace_counts(
    inspection: CreativeRenderInspection,
) -> CreativeRenderInspection:
    """Prefer a complete detailed pair ledger over an undercounted summary.

    Vision models sometimes emit the example value ``1`` for left_count and
    right_count while returning several ordered pair rows. Only the safe
    undercount case is normalized: bilateral counts must agree, the pair rows
    must form a complete center-outward sequence, and no unpaired elements may
    exist. Overcounts remain a fail-closed signal for missing pair evidence.
    """

    normalized: list[NecklaceSymmetryAudit] = []
    changed = False
    for audit in inspection.necklace_symmetry_audits:
        pair_count = len(audit.pair_audits)
        positions = tuple(
            pair.position_from_center for pair in audit.pair_audits
        )
        can_use_pair_ledger = (
            audit.expectation == "bilateral"
            and audit.left_count == audit.right_count
            and audit.left_count < pair_count
            and not audit.unpaired_left
            and not audit.unpaired_right
            and positions == tuple(range(1, pair_count + 1))
        )
        if can_use_pair_ledger:
            audit = audit.model_copy(update={
                "left_count": pair_count,
                "right_count": pair_count,
            })
            changed = True
        normalized.append(audit)
    if not changed:
        return inspection
    return inspection.model_copy(update={
        "necklace_symmetry_audits": tuple(normalized),
    })


_NECKLACE_DIFFERENCE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "motif_order": ("motif", "order", "sequence"),
    "orientation": ("orientation", "angle", "direction"),
    "spacing": ("spacing", "gap", "distance"),
    "scale": ("scale", "size", "proportion"),
    "metal_treatment": ("metal",),
    "pave_coverage": ("pave", "pavé"),
    "gemstone_treatment": (
        "gemstone", "stone", "color", "colour", "emerald", "tsavorite",
        "ruby", "sapphire", "diamond",
    ),
    "connection_type": ("connection", "connector", "link", "join"),
}


def _normalize_authorized_necklace_differences(payload: dict) -> dict:
    """Canonicalize one unambiguous model-authored difference description.

    Pair-audit schemas accept only typed symmetry dimensions, but vision models
    occasionally restate the authorized local change in prose.  Map prose only
    when it names exactly one domain. Unknown or multi-domain descriptions are
    deliberately left untouched so Pydantic still rejects them fail-closed.
    """

    audits = payload.get("necklace_symmetry_audits")
    if not isinstance(audits, list):
        return payload
    changed = False
    normalized_payload = dict(payload)
    normalized_audits: list[object] = []
    for raw_audit in audits:
        if not isinstance(raw_audit, dict):
            normalized_audits.append(raw_audit)
            continue
        pair_audits = raw_audit.get("pair_audits")
        if not isinstance(pair_audits, list):
            normalized_audits.append(raw_audit)
            continue
        normalized_pairs: list[object] = []
        audit_changed = False
        for raw_pair in pair_audits:
            if not isinstance(raw_pair, dict):
                normalized_pairs.append(raw_pair)
                continue
            differences = raw_pair.get("authorized_differences")
            if not isinstance(differences, list):
                normalized_pairs.append(raw_pair)
                continue
            normalized: list[object] = []
            pair_changed = False
            for difference in differences:
                if not isinstance(difference, str):
                    normalized.append(difference)
                    continue
                if difference in _NECKLACE_DIFFERENCE_KEYWORDS:
                    normalized.append(difference)
                    continue
                lowered = difference.casefold()
                matches = [
                    domain for domain, keywords in
                    _NECKLACE_DIFFERENCE_KEYWORDS.items()
                    if any(keyword in lowered for keyword in keywords)
                ]
                if len(matches) == 1:
                    normalized.append(matches[0])
                    pair_changed = True
                else:
                    normalized.append(difference)
            if pair_changed:
                raw_pair = dict(raw_pair)
                raw_pair["authorized_differences"] = list(dict.fromkeys(
                    normalized
                ))
                audit_changed = True
            normalized_pairs.append(raw_pair)
        if audit_changed:
            raw_audit = dict(raw_audit)
            raw_audit["pair_audits"] = normalized_pairs
            changed = True
        normalized_audits.append(raw_audit)
    if changed:
        normalized_payload["necklace_symmetry_audits"] = normalized_audits
    return normalized_payload


class GrokPromptCreativeRenderInspector:
    """Single-candidate review for category-neutral prompt concepts."""

    def inspect_render(
        self,
        plan: ImageAgentPlan,
        candidate: bytes,
    ) -> CreativeRenderInspection:
        ask = (
            f"Designer direction: {plan.intent}\n"
            "Frozen facts: " + json.dumps(list(plan.frozen)) + "\n"
            f"Expected output: {plan.expected_output}"
        )
        return CreativeRenderInspection.model_validate(_qa_vision_json(
            _PROMPT_CREATIVE_RENDER_QA_SYSTEM
            + "\n\n" + _SIX_LEAF_RUBY_QA_GUIDANCE,
            candidate,
            ask,
            CreativeRenderInspection.model_json_schema(),
        ))


class OpenAIPromptCreativeRenderInspector:
    """OpenAI vision QA fallback for category-neutral prompt concepts."""

    def inspect_render(
        self,
        plan: ImageAgentPlan,
        candidate: bytes,
    ) -> CreativeRenderInspection:
        ask = (
            f"Designer direction: {plan.intent}\n"
            "Frozen facts: " + json.dumps(list(plan.frozen)) + "\n"
            f"Expected output: {plan.expected_output}"
        )
        return CreativeRenderInspection.model_validate(openai_vision_json(
            _PROMPT_CREATIVE_RENDER_QA_SYSTEM
            + "\n\n" + _SIX_LEAF_RUBY_QA_GUIDANCE,
            candidate,
            ask,
            response_schema=CreativeRenderInspection.model_json_schema(),
        ))


class FocusedSixLeafRubyPatternInspector:
    """Independent exhaustive motif inventory for governed ruby necklaces."""

    def inspect_render(
        self,
        plan: ImageAgentPlan,
        candidate: bytes,
        necklace_audits: tuple[NecklaceSymmetryAudit, ...],
    ) -> SixLeafRubyPatternInspection:
        ask = (
            f"Designer direction: {plan.intent}\n"
            "Broad necklace coverage checklist: "
            + json.dumps([
                audit.model_dump(mode="json") for audit in necklace_audits
            ], sort_keys=True)
        )
        payload = _qa_vision_json(
            _FOCUSED_SIX_LEAF_RUBY_QA_SYSTEM,
            candidate,
            ask,
            SixLeafRubyPatternInspection.model_json_schema(),
        )
        return SixLeafRubyPatternInspection.model_validate(payload)


def _default_prompt_creative_inspector() -> PromptCreativeRenderInspector:
    """Choose a configured fail-closed vision reviewer for prompt concepts."""
    if env_value("XAI_KEY"):
        return GrokPromptCreativeRenderInspector()
    if env_value("OPENAI_API_KEY"):
        return OpenAIPromptCreativeRenderInspector()
    # Preserve the established missing-credential failure when neither
    # reviewer is configured; candidates must never bypass QA silently.
    return GrokPromptCreativeRenderInspector()


class GrokSkepticalEditInspector:
    """Prompt-diverse second pass that can veto or hold a primary QA pass."""

    def inspect_edit(
        self,
        plan: ImageAgentPlan,
        reference: bytes,
        candidate: bytes,
    ) -> EditCrossInspection:
        ask = (
            f"Authorized instruction: {plan.intent}\n"
            f"Authorized region: {plan.region_description or 'none'}\n"
            "Source facts: "
            + json.dumps(plan.source_spec_facts or {}, sort_keys=True) + "\n"
            "Validated result facts: "
            + json.dumps(plan.spec_facts, sort_keys=True) + "\n"
            "EXACT AUTHORIZED DELTA: "
            + json.dumps(
                plan.normalized_intent.get("spec_delta", []), sort_keys=True)
            + "\nFROZEN FACTS: " + json.dumps(list(plan.frozen))
            + "\nREQUIRED EDIT DOMAINS: " + json.dumps(
                [domain.value for domain in plan.edit_domains])
            + "\nSIDE-STONE INVENTORY CONTRACT: " + json.dumps(
                plan.normalized_intent.get(
                    "side_stone_inventory_contract", {}),
                sort_keys=True,
            )
        )
        data = _qa_vision_json_pair(
            (_SKEPTICAL_NECKLACE_CHAIN_EDIT_AUDIT_SYSTEM
             if plan.is_necklace_chain_style_edit
             else _SKEPTICAL_EDIT_AUDIT_SYSTEM),
            reference,
            candidate,
            ask,
        )
        return EditCrossInspection.model_validate(data)


class OpenAISkepticalEditInspector:
    """Independent OpenAI audit that vetoes edits with outside-region drift."""

    def inspect_edit(
        self,
        plan: ImageAgentPlan,
        reference: bytes,
        candidate: bytes,
    ) -> EditCrossInspection:
        ask = (
            f"Authorized instruction: {plan.intent}\n"
            f"Authorized region: {plan.region_description or 'none'}\n"
            "Source facts: "
            + json.dumps(plan.source_spec_facts or {}, sort_keys=True)
            + "\nEXACT AUTHORIZED DELTA: "
            + json.dumps(
                plan.normalized_intent.get("spec_delta", []), sort_keys=True)
            + "\nFROZEN FACTS: " + json.dumps(list(plan.frozen))
            + "\nREQUIRED EDIT DOMAINS: "
            + json.dumps([domain.value for domain in plan.edit_domains])
        )
        data = openai_vision_json_pair(
            (_SKEPTICAL_NECKLACE_CHAIN_EDIT_AUDIT_SYSTEM
             if plan.is_necklace_chain_style_edit
             else _SKEPTICAL_EDIT_AUDIT_SYSTEM),
            reference,
            candidate,
            ask,
        )
        return EditCrossInspection.model_validate(data)


class GrokSkepticalRenderInspector:
    """Independent component/count audit for validated spec renders."""

    def inspect_render(
        self,
        plan: ImageAgentPlan,
        candidate: bytes,
    ) -> RenderCrossInspection:
        ask = (
            "VALIDATED SPEC FACTS: "
            + json.dumps(plan.spec_facts, sort_keys=True)
            + "\nEXPECTED SETTING: "
            + json.dumps(plan.spec_facts.get("setting"), sort_keys=True)
            + "\nEXPECTED SIDE-STONE INVENTORY: "
            + json.dumps(plan.spec_facts.get("side_stones", []), sort_keys=True)
            + "\nFROZEN FACTS: " + json.dumps(list(plan.frozen))
        )
        data = _qa_vision_json(
            _SKEPTICAL_RENDER_AUDIT_SYSTEM,
            candidate,
            ask,
        )
        broad = RenderCrossInspection.model_validate(data)
        focused = crop_chromatic_center_assembly(candidate)
        blind_candidate = (
            focused.image_bytes if focused is not None else candidate)
        try:
            blind_data = _qa_vision_json(
                _BLIND_COMPONENT_COUNT_SYSTEM,
                blind_candidate,
                "Count only what is visibly present in this image. This may be "
                "a deterministic crop of the complete center assembly; do not "
                "treat crop edges as missing jewelry.",
            )
            blind = BlindCountInspection.model_validate(blind_data)
        except Exception:
            blind = BlindCountInspection(
                notes=("blind component count unavailable",),
            )

        setting = plan.spec_facts.get("setting")
        expected_prongs = (setting.get("prong_count")
                           if isinstance(setting, dict) else None)
        prong_match = broad.prong_count_matches
        if isinstance(expected_prongs, int):
            prong_match = (
                blind.center_prongs_visible == expected_prongs
                if (blind.center_prong_count_complete is True
                    and blind.center_prongs_visible is not None)
                else None
            )

        groups = plan.spec_facts.get("side_stones")
        expected_side_count = 0
        side_inventory_known = isinstance(groups, list)
        if side_inventory_known:
            for group in groups:
                if not isinstance(group, dict) or not isinstance(
                        group.get("count"), int):
                    side_inventory_known = False
                    break
                expected_side_count += group["count"]
        side_match = broad.side_stone_inventory_matches
        count_notes: tuple[str, ...] = ()
        if side_inventory_known:
            if (blind.side_stone_count_complete is True
                    and blind.side_stones_visible is not None):
                blind_side_match = (
                    blind.side_stones_visible == expected_side_count)
                if (broad.side_stone_inventory_matches is not None
                        and broad.side_stone_inventory_matches
                        is not blind_side_match):
                    # Pavé beads/prongs are easy to misclassify as stones. Two
                    # independent vision reads that disagree are insufficient
                    # for either acceptance or a hard rejection; surface a
                    # warning candidate for explicit designer counting.
                    side_match = None
                    count_notes = (
                        "broad and blind side-stone inventory audits disagree; "
                        "designer count review required",
                    )
                else:
                    side_match = blind_side_match
            else:
                side_match = None

        focus_notes: tuple[str, ...] = ()
        if focused is not None:
            focus_notes = (
                "blind center-prong audit used deterministic focused crop: "
                + json.dumps(focused.evidence, sort_keys=True),
            )
        return broad.model_copy(update={
            "prong_count_matches": prong_match,
            "observed_prong_count": blind.center_prongs_visible,
            "observed_prong_count_complete": (
                blind.center_prong_count_complete),
            "side_stone_inventory_matches": side_match,
            "observed_side_stone_count": blind.side_stones_visible,
            "observed_side_stone_count_complete": (
                blind.side_stone_count_complete),
            "notes": (
                *broad.notes, *blind.notes, *count_notes, *focus_notes),
        })


class ExistingEvalInspector:
    """Compatibility adapter over ``facetta.evals`` scoring primitives.

    It is useful for offline/golden-set comparisons. The richer production
    inspector above is preferred because the older scores cannot observe cut,
    setting, branding, or every major component.
    """

    def inspect_render(
        self,
        plan: ImageAgentPlan,
        candidate: bytes,
        *,
        reference: bytes | None,
    ) -> RenderInspection:
        from facetta.evals import score_spec_conformance
        from facetta.spec import Spec

        spec = Spec.model_validate(plan.spec_facts)
        score = score_spec_conformance(spec, candidate)
        parts = score["components"]
        consistent = None
        notes: list[str] = []
        if reference:
            checked = check_design_consistency(reference, candidate)
            consistent = (bool(checked["consistent"])
                          if checked.get("checked") else None)
            notes.extend(str(item) for item in checked.get("differences", []))
        return RenderInspection(
            center_species_matches=parts["species_named"] == 1.0,
            metal_matches=parts["metal_matched"] == 1.0,
            stone_count_matches=parts["stone_count"] >= 0.95,
            exact_dimensions_credible=parts["centre_size"] >= 0.75,
            exact_carat_credible=parts["centre_carat"] >= 0.75,
            reference_consistent=consistent,
            score=score["score"],
            notes=tuple(notes),
        )

    def inspect_edit(
        self,
        plan: ImageAgentPlan,
        reference: bytes,
        candidate: bytes,
    ) -> EditInspection:
        from facetta.evals import score_edit_fidelity

        score = score_edit_fidelity(reference, candidate, plan.intent)
        return EditInspection(
            change_applied=score["change_applied"],
            unintended_severity=score["severity"],
            unintended_changes=tuple(score["unintended_changes"]),
            protected_regions_preserved=score["severity"] != "major",
            score=score["score"],
            notes=(score.get("note") or "",),
        )


def _match_check(code: str, observed: bool | None, mismatch: str,
                 unknown: str) -> QualityCheck:
    if observed is True:
        return QualityCheck(
            code=code,
            passed=True,
            severity=CheckSeverity.HARD,
            message="visual evidence matches the requested fact",
        )
    if observed is False:
        return QualityCheck(
            code=code,
            passed=False,
            severity=CheckSeverity.HARD,
            message=mismatch,
        )
    return QualityCheck(
        code=code,
        passed=False,
        severity=CheckSeverity.WARNING,
        message=unknown,
    )


def _necklace_chain_style_checks(
    plan: ImageAgentPlan,
    inspection: ChainStyleEditInspection | None,
) -> list[QualityCheck]:
    """Convert chain-specific comparative evidence into category-safe gates."""

    if not plan.is_necklace_chain_style_edit:
        return []
    item = inspection or ChainStyleEditInspection()
    fields = (
        (
            "chain_style_target",
            item.target_style_matches,
            "visible chain links do not match the selected target style",
            "target chain style could not be confirmed across the visible links",
        ),
        (
            "chain_style_complete_run",
            item.complete_visible_run_matches,
            "the selected style was not applied to the complete visible chain run",
            "complete-run chain-style coverage could not be visually confirmed",
        ),
        (
            "chain_connections",
            item.chain_connections_preserved,
            "a chain-to-bail, clasp, or endpoint connection changed unexpectedly",
            "chain connection preservation could not be visually confirmed",
        ),
        (
            "pendant_count",
            item.pendant_count_preserved,
            "the edit added or removed a pendant",
            "the exact pendant count could not be visually confirmed",
        ),
        (
            "pendant_geometry",
            item.pendant_geometry_preserved,
            "the frozen pendant geometry changed",
            "pendant-geometry preservation could not be visually confirmed",
        ),
        (
            "bail",
            item.bail_preserved,
            "the frozen bail geometry changed",
            "bail preservation could not be visually confirmed",
        ),
        (
            "stones",
            item.stones_preserved,
            "a frozen gemstone identity, count, cut, color, scale, or position changed",
            "gemstone preservation could not be visually confirmed",
        ),
        (
            "setting",
            item.setting_preserved,
            "the frozen stone setting changed",
            "setting preservation could not be visually confirmed",
        ),
        (
            "clasp",
            item.clasp_preserved,
            "the frozen clasp type, geometry, or position changed",
            "clasp preservation could not be visually confirmed",
        ),
        (
            "chain_length_and_drape",
            item.chain_length_and_drape_preserved,
            "the chain endpoints, apparent length, or drape changed",
            "relative chain length and drape preservation could not be confirmed",
        ),
        (
            "non_chain_geometry",
            item.non_chain_geometry_preserved,
            "non-chain jewelry geometry changed outside the authorized edit",
            "preservation of all non-chain geometry could not be confirmed",
        ),
    )
    checks = [
        _match_check(code, observed, mismatch, unknown)
        for code, observed, mismatch, unknown in fields
    ]
    source_clasp = item.source_clasp_visible
    candidate_clasp = item.candidate_clasp_visible
    if source_clasp is False and candidate_clasp is True:
        checks.append(QualityCheck(
            code="clasp_visibility",
            passed=False,
            severity=CheckSeverity.HARD,
            message=(
                "candidate added a visible clasp that was not visible in the "
                "source framing"
            ),
            evidence={
                "source_clasp_visible": source_clasp,
                "candidate_clasp_visible": candidate_clasp,
            },
        ))
    elif source_clasp is None or candidate_clasp is None:
        checks.append(QualityCheck(
            code="clasp_visibility",
            passed=False,
            severity=CheckSeverity.WARNING,
            message=(
                "source-versus-candidate clasp visibility could not be "
                "independently established"
            ),
            evidence={
                "source_clasp_visible": source_clasp,
                "candidate_clasp_visible": candidate_clasp,
            },
        ))
    else:
        checks.append(QualityCheck(
            code="clasp_visibility",
            passed=True,
            severity=CheckSeverity.HARD,
            message="candidate did not reveal an off-frame source clasp",
            evidence={
                "source_clasp_visible": source_clasp,
                "candidate_clasp_visible": candidate_clasp,
            },
        ))

    candidate_branding = item.candidate_contains_non_jewelry_text_or_branding
    checks.append(_match_check(
        "candidate_text_or_branding",
        (None if candidate_branding is None else not candidate_branding),
        (
            "candidate contains a caption, signature, logo, watermark, "
            "platform ID, or other non-jewelry branding"
        ),
        (
            "candidate output hygiene could not confirm the absence of text, "
            "a signature, logo, watermark, or platform ID"
        ),
    ))
    checks.append(QualityCheck(
        code="exact_chain_dimensions",
        passed=False,
        severity=CheckSeverity.WARNING,
        message=(
            "pixels can support chain-style and relative-drape review but cannot "
            "prove exact link gauge, pitch, thickness, dimensions, or chain "
            "length; the validated spec and designer review are authoritative"
        ),
        evidence={
            "source_chain": (plan.source_spec_facts or {}).get("chain"),
            "target_chain": plan.spec_facts.get("chain"),
            "raster_dimensional_proof": False,
        },
    ))
    return checks


def _report(checks: list[QualityCheck], *, score: float | None,
            notes: tuple[str, ...]) -> ImageQualityReport:
    if any(not check.passed and check.severity is CheckSeverity.HARD
           for check in checks):
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


def _render_cross_checks(
    item: RenderCrossInspection,
    *,
    prefix: str,
) -> list[QualityCheck]:
    """Turn a skeptical full-spec audit into independent hard gates."""
    if not item.checked:
        return [QualityCheck(
            code=f"{prefix}:audit",
            passed=False,
            severity=CheckSeverity.WARNING,
            message=(
                "independent full-spec audit was unavailable; designer review "
                "is required"
            ),
        )]
    fields = (
        ("jewelry_type", item.jewelry_type_matches,
         "independent audit found the wrong jewelry type"),
        ("center_identity", item.center_identity_matches,
         "independent audit found the wrong center-stone identity"),
        ("center_cut", item.center_cut_matches,
         "independent audit found the wrong center-stone cut"),
        ("metal", item.metal_matches,
         "independent audit found the wrong metal assignment"),
        ("setting_style", item.setting_style_matches,
         "independent audit found the wrong setting style"),
        ("prong_count", item.prong_count_matches,
         "independent audit found the wrong center-prong count"),
        ("side_stone_inventory", item.side_stone_inventory_matches,
         "independent audit found a side-stone inventory mismatch"),
        ("major_components", item.major_components_match,
         "independent audit found a missing or added major component"),
    )
    checks: list[QualityCheck] = []
    for code, observed, mismatch in fields:
        check = _match_check(
            f"{prefix}:{code}",
            observed,
            mismatch,
            f"independent audit could not confirm {code.replace('_', ' ')}",
        )
        checks.append(check.model_copy(update={
            "evidence": {
                "observed_prong_count": item.observed_prong_count,
                "observed_prong_count_complete": (
                    item.observed_prong_count_complete),
                "observed_side_stone_count": item.observed_side_stone_count,
                "differences": list(item.differences),
            },
        }))
    return checks


def _white_metal_family(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    material = str(value.get("material") or "").lower()
    color = str(value.get("color") or "").lower()
    return material in {"platinum", "silver", "palladium"} or (
        material == "gold" and color == "white")


def _visually_ambiguous_metal_substitution(plan: ImageAgentPlan) -> bool:
    """True when a factory material change has no provable raster identity."""
    if plan.operation is not ImageOperation.LOCAL_EDIT:
        return False
    source = (plan.source_spec_facts or {}).get("metal")
    target = plan.spec_facts.get("metal")
    if not isinstance(source, dict) or not isinstance(target, dict):
        return False
    if source.get("material") == target.get("material"):
        return False
    visible_delta = source.get("finish") != target.get("finish")
    return (_white_metal_family(source) and _white_metal_family(target)
            and not visible_delta)


def _apply_ambiguous_metal_policy(
    checks: list[QualityCheck],
    plan: ImageAgentPlan,
) -> None:
    if not _visually_ambiguous_metal_substitution(plan):
        return
    message = (
        "white-metal material identity is factory-significant but cannot be "
        "proven from pixels; the validated spec is authoritative and explicit "
        "designer review is required"
    )
    direct_codes = {
        "requested_change",
        "spec_change",
        "edit_domain:metal_identity",
        "crosscheck_requested_change",
        "target_spec_crosscheck:metal",
    }
    for index, check in enumerate(checks):
        downgrade = check.code in direct_codes
        if check.code == "crosscheck_edit_domains":
            mismatches = check.evidence.get("domain_mismatches", [])
            downgrade = bool(mismatches) and set(mismatches) <= {
                DesignerEditDomain.METAL_IDENTITY.value}
        if downgrade and not check.passed:
            checks[index] = check.model_copy(update={
                "severity": CheckSeverity.WARNING,
                "message": message,
                "evidence": {
                    **check.evidence,
                    "visual_material_identity_unprovable": True,
                },
            })
    checks.append(QualityCheck(
        code="exact_metal_material",
        passed=False,
        severity=CheckSeverity.WARNING,
        message=message,
        evidence={
            "source_material": (plan.source_spec_facts or {}).get("metal"),
            "target_material": plan.spec_facts.get("metal"),
        },
    ))


def _deterministic_checks(
    candidate: bytes, *, source_image: bytes | None,
) -> list[QualityCheck]:
    """Cheap byte/raster gates that run before accepting vision judgment."""
    from PIL import Image

    checks: list[QualityCheck] = []
    try:
        image = Image.open(io.BytesIO(candidate))
        image.verify()
        width, height = image.size
        checks.append(QualityCheck(
            code="decodable_image",
            passed=True,
            severity=CheckSeverity.HARD,
            message="candidate is a decodable raster image",
            evidence={"width": width, "height": height,
                      "format": image.format or "unknown"},
        ))
        checks.append(QualityCheck(
            code="review_resolution",
            passed=min(width, height) >= 64,
            severity=CheckSeverity.WARNING,
            message=("candidate has reviewable raster dimensions"
                     if min(width, height) >= 64 else
                     "candidate resolution is too low for reliable review"),
            evidence={"width": width, "height": height},
        ))
    except Exception:
        checks.append(QualityCheck(
            code="decodable_image",
            passed=False,
            severity=CheckSeverity.HARD,
            message="provider output is not a decodable raster image",
        ))
    if source_image is not None:
        checks.append(QualityCheck(
            code="candidate_changed",
            passed=candidate != source_image,
            severity=CheckSeverity.HARD,
            message=("candidate bytes differ from the source"
                     if candidate != source_image else
                     "provider returned the unchanged source image"),
        ))
    return checks


class RingQualityEvaluator:
    """Apply ring gates plus the narrow, explicit necklace chain-edit gates."""

    def __init__(self, inspector: ImageInspector | None = None,
                 drift_measure=None,
                 edit_cross_inspector: EditCrossInspector | None = None,
                 require_cross_inspection: bool | None = None,
                 render_cross_inspector: RenderCrossInspector | None = None,
                 require_render_cross_inspection: bool | None = None,
                 creative_inspector: CreativeRenderInspector | None = None,
                 creative_cross_inspector: CreativeRenderInspector | None = None,
                 require_creative_cross_inspection: bool | None = None,
                 prompt_creative_inspector: PromptCreativeRenderInspector | None = None,
                 six_leaf_pattern_inspector: SixLeafRubyPatternInspector | None = None) -> None:
        primary_is_default = inspector is None
        if inspector is not None:
            self.inspector = inspector
        elif env_value("XAI_KEY"):
            self.inspector = GrokVisionInspector()
        elif env_value("OPENAI_API_KEY"):
            self.inspector = OpenAIVisionInspector()
        else:
            # Fail closed through the established missing-credential error.
            self.inspector = GrokVisionInspector()
        if require_cross_inspection is None:
            require_cross_inspection = primary_is_default
        self._edit_cross_inspector = edit_cross_inspector
        if self._edit_cross_inspector is None and require_cross_inspection:
            self._edit_cross_inspector = (
                GrokSkepticalEditInspector()
                if env_value("XAI_KEY") or not env_value("OPENAI_API_KEY")
                else OpenAISkepticalEditInspector()
            )
        if require_render_cross_inspection is None:
            require_render_cross_inspection = primary_is_default
        self._render_cross_inspector = render_cross_inspector
        if (self._render_cross_inspector is None
                and require_render_cross_inspection):
            self._render_cross_inspector = GrokSkepticalRenderInspector()
        self._drift_measure = drift_measure
        creative_primary_is_default = creative_inspector is None
        if creative_inspector is not None:
            self._creative_inspector = creative_inspector
        elif env_value("XAI_KEY"):
            self._creative_inspector = GrokCreativeRenderInspector()
        elif env_value("OPENAI_API_KEY"):
            self._creative_inspector = OpenAICreativeRenderInspector()
        else:
            self._creative_inspector = GrokCreativeRenderInspector()
        if require_creative_cross_inspection is None:
            require_creative_cross_inspection = creative_primary_is_default
        self._creative_cross_inspector = creative_cross_inspector
        if (self._creative_cross_inspector is None
                and require_creative_cross_inspection):
            self._creative_cross_inspector = (
                GrokSkepticalCreativeRenderInspector()
                if env_value("XAI_KEY") or not env_value("OPENAI_API_KEY")
                else OpenAISkepticalCreativeRenderInspector()
            )
        self._prompt_creative_inspector = (
            prompt_creative_inspector or _default_prompt_creative_inspector())
        self._six_leaf_pattern_inspector = six_leaf_pattern_inspector
        if (
            self._six_leaf_pattern_inspector is None
            and prompt_creative_inspector is None
            and creative_inspector is None
        ):
            self._six_leaf_pattern_inspector = (
                FocusedSixLeafRubyPatternInspector()
            )

    def evaluate_source_precondition(
        self,
        plan: ImageAgentPlan,
        source_image: bytes,
    ) -> ImageQualityReport | None:
        """Prove exact source topology before paying for a topology edit.

        A source spec that says six prongs while the raster visibly has four
        turns a requested six-to-four edit into an unchanged four-to-four
        image. That mismatch must stop before provider execution rather than
        becoming a beautiful false pass.
        """
        if (plan.operation is not ImageOperation.LOCAL_EDIT
                or plan.jewelry_type != "ring"
                or DesignerEditDomain.SETTING not in plan.edit_domains
                or not isinstance(plan.source_spec_facts, dict)
                or self._render_cross_inspector is None):
            return None
        source_plan = plan.model_copy(update={
            "spec_facts": plan.source_spec_facts,
            "source_spec_facts": None,
        })
        try:
            inspection = self._render_cross_inspector.inspect_render(
                source_plan, source_image)
        except Exception:
            inspection = RenderCrossInspection(
                checked=False,
                notes=("source topology audit unavailable",),
            )
        if not inspection.checked:
            checks = [QualityCheck(
                code="source_topology:audit",
                passed=False,
                severity=CheckSeverity.WARNING,
                message=(
                    "the source setting could not be independently audited; "
                    "choose a clearer view or confirm the source specification"
                ),
            )]
        else:
            checks = [
                _match_check(
                    "source_topology:setting_style",
                    inspection.setting_style_matches,
                    "the source image contradicts its recorded setting style",
                    "the source setting style is not visually assessable",
                ),
                _match_check(
                    "source_topology:prong_count",
                    inspection.prong_count_matches,
                    "the source image contradicts its recorded center-prong count",
                    "the complete source center-prong count is not visually assessable",
                ).model_copy(update={"evidence": {
                    "expected": (
                        plan.source_spec_facts.get("setting", {})
                        .get("prong_count")
                        if isinstance(
                            plan.source_spec_facts.get("setting"), dict)
                        else None
                    ),
                    "observed": inspection.observed_prong_count,
                    "complete": inspection.observed_prong_count_complete,
                }}),
            ]
        return _report(
            checks,
            score=(100.0 if all(check.passed for check in checks) else 0.0),
            notes=inspection.notes,
        )

    def evaluate(
        self,
        plan: ImageAgentPlan,
        candidate: bytes,
        *,
        source_image: bytes | None,
        mask_bytes: bytes | None,
    ) -> ImageQualityReport:
        if plan.operation is ImageOperation.CREATIVE_GENERATE:
            inspection = self._prompt_creative_inspector.inspect_render(
                plan, candidate)
            inspection = _normalize_redundant_necklace_counts(inspection)
            if (
                SIX_LEAF_RUBY_PATTERN_CONTRACT in plan.intent
                and self._six_leaf_pattern_inspector is not None
            ):
                focused = self._six_leaf_pattern_inspector.inspect_render(
                    plan,
                    candidate,
                    canonical_six_leaf_coverage_audits(
                        inspection.necklace_symmetry_audits
                    ),
                )
                inspection = inspection.model_copy(update={
                    "six_leaf_ruby_pattern_audits": focused.audits,
                    "notes": (*inspection.notes, *focused.notes),
                })
            return self._creative_render_report(
                plan,
                inspection,
                candidate=candidate,
                source_image=None,
                mask_bytes=None,
                enforce_explicit_counts=True,
            )
        if plan.operation is ImageOperation.REFERENCE_RENDER:
            if not source_image:
                raise ValueError("reference-render QA requires the source image")
            inspection = self._creative_inspector.inspect_render(
                plan, source_image, candidate)
            if self._creative_cross_inspector is not None:
                try:
                    skeptical = self._creative_cross_inspector.inspect_render(
                        plan, source_image, candidate)
                except Exception:
                    skeptical = CreativeRenderInspection(
                        notes=("skeptical source-fidelity audit unavailable",),
                    )
                inspection = _merge_creative_inspections(
                    inspection, skeptical)
            inspection = _normalize_redundant_necklace_counts(inspection)
            if (
                SIX_LEAF_RUBY_PATTERN_CONTRACT in plan.intent
                and self._six_leaf_pattern_inspector is not None
            ):
                focused = self._six_leaf_pattern_inspector.inspect_render(
                    plan,
                    candidate,
                    canonical_six_leaf_coverage_audits(
                        inspection.necklace_symmetry_audits
                    ),
                )
                inspection = inspection.model_copy(update={
                    "six_leaf_ruby_pattern_audits": focused.audits,
                    "notes": (*inspection.notes, *focused.notes),
                })
            return self._creative_render_report(
                plan,
                inspection,
                candidate=candidate,
                source_image=source_image,
                mask_bytes=mask_bytes,
                enforce_explicit_counts=False,
            )
        if plan.operation in {
            ImageOperation.CONCEPT_GENERATE,
            ImageOperation.SPEC_RENDER,
        }:
            inspection = self.inspector.inspect_render(
                plan,
                candidate,
                reference=source_image,
            )
            cross_inspection: RenderCrossInspection | None = None
            if (plan.operation is ImageOperation.SPEC_RENDER
                    and self._render_cross_inspector is not None):
                try:
                    cross_inspection = (
                        self._render_cross_inspector.inspect_render(
                            plan, candidate))
                except Exception:
                    cross_inspection = RenderCrossInspection(
                        checked=False,
                        notes=("independent render audit unavailable",),
                    )
            return self._render_report(
                plan, inspection, candidate,
                cross_inspection=cross_inspection,
                source_image=source_image)
        if not source_image:
            raise ValueError("edit QA requires the source image")
        inspection = self.inspector.inspect_edit(plan, source_image, candidate)
        cross_inspection: EditCrossInspection | None = None
        if self._edit_cross_inspector is not None:
            try:
                cross_inspection = self._edit_cross_inspector.inspect_edit(
                    plan, source_image, candidate)
            except Exception:
                cross_inspection = EditCrossInspection(
                    checked=False,
                    notes=("independent edit audit unavailable",),
                )
        target_spec_cross: RenderCrossInspection | None = None
        if (plan.operation is ImageOperation.LOCAL_EDIT
                and plan.jewelry_type == "ring"
                and self._render_cross_inspector is not None):
            try:
                target_spec_cross = self._render_cross_inspector.inspect_render(
                    plan, candidate)
            except Exception:
                target_spec_cross = RenderCrossInspection(
                    checked=False,
                    notes=("candidate full-spec audit unavailable",),
                )
        return self._edit_report(
            plan,
            inspection,
            cross_inspection=cross_inspection,
            target_spec_cross=target_spec_cross,
            source_image=source_image,
            candidate=candidate,
            mask_bytes=mask_bytes,
        )

    def _masked_change_checks(
        self,
        plan: ImageAgentPlan,
        source_image: bytes,
        candidate: bytes,
        mask_bytes: bytes,
    ) -> list[QualityCheck]:
        effect = inside_mask_effect(source_image, candidate, mask_bytes)
        visible = bool(
            effect.get("checked") and effect.get("change_visible")
        )
        checks = [QualityCheck(
            code="inside_mask_effect",
            passed=visible,
            severity=CheckSeverity.HARD,
            message=(
                "the authorized region contains a visible edit"
                if visible else
                "the masked candidate is unchanged, invalid, or too close "
                "to the source to count as the requested edit"
            ),
            evidence=effect,
        )]
        localization = plan.normalized_intent.get("localization", {})
        expected_region_count = (
            localization.get("marked_region_count")
            if isinstance(localization, dict) else None
        )
        region_effects = inside_mask_region_effects(
            source_image,
            candidate,
            mask_bytes,
            expected_region_count=(
                expected_region_count
                if isinstance(expected_region_count, int) else None
            ),
        )
        every_region_changed = bool(
            region_effects.get("checked")
            and region_effects.get("every_region_changed")
        )
        checks.append(QualityCheck(
            code="inside_each_mask_region_effect",
            passed=every_region_changed,
            severity=CheckSeverity.HARD,
            message=(
                "every designer-marked region contains a visible edit"
                if every_region_changed else
                "one or more designer-marked regions are missing, unchanged, "
                "or too close to the source to prove every requested edit"
            ),
            evidence=region_effects,
        ))
        if self._drift_measure is not None:
            drift = self._drift_measure(source_image, candidate, mask_bytes)
        elif effect.get("checked"):
            drift = outside_mask_drift(source_image, candidate, mask_bytes)
        else:
            return checks
        checks.append(QualityCheck(
            code="outside_mask_drift",
            passed=drift <= plan.drift_threshold,
            severity=CheckSeverity.HARD,
            message=(
                "outside-mask drift is within the calibrated threshold"
                if drift <= plan.drift_threshold else
                "outside-mask drift exceeds the calibrated threshold"
            ),
            evidence={
                "drift": round(float(drift), 6),
                "threshold": plan.drift_threshold,
            },
        ))
        return checks

    def _creative_render_report(
        self,
        plan: ImageAgentPlan,
        item: CreativeRenderInspection,
        *,
        candidate: bytes,
        source_image: bytes | None,
        mask_bytes: bytes | None,
        enforce_explicit_counts: bool,
    ) -> ImageQualityReport:
        checks = [
            *_deterministic_checks(candidate, source_image=source_image),
            _match_check(
                "coherent_jewelry_render",
                item.coherent_jewelry_render,
                "candidate is not a coherent, reviewable jewelry render",
                "candidate coherence could not be visually confirmed",
            ),
            _match_check(
                "complete_piece_visible",
                item.complete_piece_visible,
                "candidate crops or omits part of the complete jewelry piece",
                "complete-piece framing could not be visually confirmed",
            ),
            _match_check(
                "requested_presentation_applied",
                item.requested_presentation_applied,
                "candidate did not apply the requested render presentation",
                "requested presentation could not be visually confirmed",
            ),
            _match_check(
                "text_or_branding",
                (None if item.text_or_branding_detected is None
                 else not item.text_or_branding_detected),
                "candidate contains text, a logo, signature, watermark, or branding",
                "absence of text or branding could not be confirmed",
            ),
            QualityCheck(
                code="factory_authority",
                passed=False,
                severity=CheckSeverity.WARNING,
                message=(
                    "creative render is review-only and cannot establish hidden "
                    "geometry, dimensions, materials, stone identity, or factory facts"
                ),
                evidence={"factory_authoritative": False},
            ),
        ]
        if JEWELRY_SYMMETRY_CONTRACT in plan.intent:
            necklace_gate = evaluate_necklace_symmetry_audits(
                plan.intent,
                item.necklace_symmetry_audits,
                source_present=source_image is not None,
                observed_jewelry_type=item.observed_jewelry_type,
            )
            explicit_symmetry = item.symmetry_expectation_matches
            # A complete structured necklace audit is stronger evidence than a
            # nullable summary field from the same evaluator response. Never
            # rescue an explicit false or a failed/incomplete structured audit.
            observed_symmetry = (
                True
                if explicit_symmetry is None
                and necklace_gate.applicable
                and necklace_gate.passed
                else explicit_symmetry
            )
            checks.insert(-2, QualityCheck(
                code="jewelry_symmetry",
                passed=observed_symmetry is True,
                severity=CheckSeverity.HARD,
                message=(
                    "left/right or radial jewelry symmetry matches the design intent"
                    if observed_symmetry is True else
                    "candidate has unrequested or unverified left/right or radial "
                    "design asymmetry"
                ),
                evidence={
                    "observed": observed_symmetry,
                    "summary_observed": explicit_symmetry,
                    "confirmed_by_structured_necklace_audit": (
                        explicit_symmetry is None
                        and observed_symmetry is True
                    ),
                    "observations": list(item.symmetry_observations),
                    "default_symmetry_required": True,
                    "identity_source_or_explicit_asymmetry_may_override": True,
                },
            ))
            if necklace_gate.applicable:
                checks.insert(-2, QualityCheck(
                    code="necklace_sequence_symmetry",
                    passed=necklace_gate.passed,
                    severity=CheckSeverity.HARD,
                    message=(
                        "center-outward necklace elements satisfy the structured "
                        "symmetry contract"
                        if necklace_gate.passed else
                        "center-outward necklace symmetry evidence is missing, "
                        "incomplete, or contradicts the design intent"
                    ),
                    evidence={
                        "audit_count": necklace_gate.audit_count,
                        "observed_jewelry_type": item.observed_jewelry_type,
                        "reasons": list(necklace_gate.reasons),
                        "audits": [
                            audit.model_dump(mode="json")
                            for audit in item.necklace_symmetry_audits
                        ],
                        "provider_free_deterministic_validation": True,
                        "pixel_measurement_claimed": False,
                    },
                ))
        if SIX_LEAF_RUBY_PATTERN_CONTRACT in plan.intent:
            leaf_gate = evaluate_six_leaf_ruby_pattern_audits(
                plan.intent,
                item.six_leaf_ruby_pattern_audits,
                necklace_audits=item.necklace_symmetry_audits,
            )
            checks.insert(-2, QualityCheck(
                code="six_leaf_ruby_pattern",
                passed=leaf_gate.passed,
                severity=CheckSeverity.HARD,
                message=(
                    "every ruby motif has six whole leaves in a matched 3/3 "
                    "diamond-tsavorite alternating phase"
                    if leaf_gate.passed else
                    "six-leaf ruby motif evidence is missing, incomplete, "
                    "non-alternating, or phase-mismatched"
                ),
                evidence={
                    "audit_count": leaf_gate.audit_count,
                    "reasons": list(leaf_gate.reasons),
                    "audits": [
                        audit.model_dump(mode="json")
                        for audit in item.six_leaf_ruby_pattern_audits
                    ],
                    "provider_free_deterministic_validation": True,
                    "pixel_measurement_claimed": False,
                },
            ))
        if enforce_explicit_counts:
            checks.insert(-2, _match_check(
                "explicit_counts_match",
                item.explicit_counts_match,
                "candidate does not match an explicitly requested component count",
                "explicit requested counts could not be visually confirmed",
            ))
            checks.insert(-2, _match_check(
                "explicit_stone_facts_match",
                item.explicit_stone_facts_match,
                "candidate contradicts an explicitly requested gemstone fact",
                "explicit gemstone facts could not be visually confirmed",
            ))
        masked_checks: list[QualityCheck] = []
        if source_image is not None and mask_bytes is not None:
            masked_checks = self._masked_change_checks(
                plan,
                source_image,
                candidate,
                mask_bytes,
            )
        if source_image is not None:
            localization = plan.normalized_intent.get("localization", {})
            authorized_domains = (
                localization.get("authorized_change_domains", [])
                if isinstance(localization, dict) else []
            )
            bounded_marked_change = bool(
                localization.get("mode") == "designer_marked_pre_spec_region"
                if isinstance(localization, dict) else False
            ) and bool(masked_checks) and all(
                check.passed for check in masked_checks
                if check.severity is CheckSeverity.HARD
            ) and all(value is True for value in (
                item.coherent_jewelry_render,
                item.complete_piece_visible,
                item.visible_components_preserved,
                item.repeated_element_pattern_preserved,
                item.stone_shape_and_cut_family_preserved,
                item.requested_presentation_applied,
            )) and not item.major_unintended_changes
            source_design_preserved = item.source_design_preserved
            local_geometry_preserved = item.local_geometry_preserved
            if bounded_marked_change and "appearance" in authorized_domains:
                source_design_preserved = True
            if bounded_marked_change and "local_geometry" in authorized_domains:
                local_geometry_preserved = True
            source_design_check = _match_check(
                "source_design_preserved",
                source_design_preserved,
                "candidate materially changed the visible source design identity",
                "source-design preservation could not be visually confirmed",
            )
            if source_design_preserved is True and item.source_design_preserved is False:
                source_design_check = source_design_check.model_copy(update={
                    "evidence": {
                        "vision_observed": False,
                        "resolved_by": "bounded_marked_region_authorization",
                        "authorized_change_domains": authorized_domains,
                    },
                })
            local_geometry_check = _match_check(
                "local_geometry_preserved",
                local_geometry_preserved,
                "candidate changed visible local contours, panels, supports, gallery, shoulders, or shank geometry",
                "local source geometry could not be fully confirmed",
            )
            if local_geometry_preserved is True and item.local_geometry_preserved is False:
                local_geometry_check = local_geometry_check.model_copy(update={
                    "evidence": {
                        "vision_observed": False,
                        "resolved_by": "bounded_marked_region_authorization",
                        "authorized_change_domains": authorized_domains,
                    },
                })
            if _is_rough_drawing_interpretation(plan):
                # A sparse sketch cannot support literal local-geometry, motif,
                # or cut-family claims.  Keep the high-level design-identity
                # gate plus coherence, complete-piece, presentation, symmetry,
                # and branding gates above.
                checks[2:2] = [source_design_check]
            else:
                checks[2:2] = [
                    source_design_check,
                    _match_check(
                        "visible_components_preserved",
                        item.visible_components_preserved,
                        "candidate added, removed, replaced, or moved a visible component",
                        "visible component preservation could not be confirmed",
                    ),
                    local_geometry_check,
                    _match_check(
                        "repeated_element_pattern_preserved",
                        item.repeated_element_pattern_preserved,
                        "candidate changed a visible repeated motif's count, shape, order, spacing, or element type",
                        "repeated source-element topology could not be fully confirmed",
                    ),
                    _match_check(
                        "stone_shape_and_cut_family_preserved",
                        item.stone_shape_and_cut_family_preserved,
                        "candidate changed a visible center or side stone shape/cut family",
                        "source stone shape/cut preservation could not be fully confirmed",
                    ),
                ]
            checks.extend(masked_checks)
        return _report(
            checks,
            score=item.score,
            notes=(*item.notes, *item.major_unintended_changes),
        )

    def _render_report(self, plan: ImageAgentPlan,
                       item: RenderInspection,
                       candidate: bytes, *,
                       cross_inspection: RenderCrossInspection | None,
                       source_image: bytes | None) -> ImageQualityReport:
        checks = [
            *_deterministic_checks(candidate, source_image=source_image),
            _match_check(
                "jewelry_type",
                item.jewelry_type_matches,
                "candidate is not the requested ring type",
                "ring type could not be confirmed from the candidate",
            ),
            _match_check(
                "major_components",
                item.major_components_match,
                "candidate added, removed, or replaced a major component",
                "major component completeness could not be confirmed",
            ),
        ]
        has_spec = plan.operation is ImageOperation.SPEC_RENDER
        if has_spec:
            checks.extend([
                _match_check(
                    "center_species",
                    item.center_species_matches,
                    "center-stone species does not match the validated spec",
                    "center-stone species could not be visually confirmed",
                ),
                _match_check(
                    "cut_family",
                    item.cut_family_matches,
                    "center-stone cut family does not match the validated spec",
                    "center-stone cut family could not be visually confirmed",
                ),
                _match_check(
                    "center_color",
                    item.center_color_matches,
                    "visible center-stone color does not match the validated spec",
                    "center-stone color could not be visually confirmed",
                ),
                _match_check(
                    "metal",
                    item.metal_matches,
                    "metal material or color does not match the validated spec",
                    "metal material and color could not be visually confirmed",
                ),
                _match_check(
                    "setting",
                    item.setting_matches,
                    "setting or prong structure does not match the validated spec",
                    "setting and prong structure could not be visually confirmed",
                ),
                _match_check(
                    "stone_count",
                    item.stone_count_matches,
                    "visually assessable stone count does not match the validated spec",
                    "stone count is not reliably assessable in this view",
                ),
            ])
            if cross_inspection is not None:
                checks.extend(_render_cross_checks(
                    cross_inspection, prefix="render_crosscheck"))
        if item.text_or_branding_detected is True:
            checks.append(QualityCheck(
                code="text_or_branding",
                passed=False,
                severity=CheckSeverity.HARD,
                message="candidate contains text, a logo, watermark, or invented branding",
            ))
        elif item.text_or_branding_detected is False:
            checks.append(QualityCheck(
                code="text_or_branding",
                passed=True,
                severity=CheckSeverity.HARD,
                message="no text or branding detected",
            ))
        else:
            checks.append(QualityCheck(
                code="text_or_branding",
                passed=False,
                severity=CheckSeverity.WARNING,
                message="absence of text or branding could not be confirmed",
            ))
        if plan.source_hash is not None:
            checks.append(_match_check(
                "reference_consistency",
                item.reference_consistent,
                "candidate materially changed the source design identity",
                "source-design consistency could not be confirmed",
            ))
        for code, credible, label in (
            ("exact_dimensions", item.exact_dimensions_credible, "exact millimeters"),
            ("exact_carat", item.exact_carat_credible, "exact carat weight"),
        ):
            if credible is False:
                checks.append(QualityCheck(
                    code=code,
                    passed=False,
                    severity=CheckSeverity.WARNING,
                    message=f"the raster cannot substantiate {label}; use the spec as truth",
                ))
            elif credible is True:
                checks.append(QualityCheck(
                    code=code,
                    passed=True,
                    severity=CheckSeverity.WARNING,
                    message=f"{label} appears plausible but remains non-authoritative",
                ))
        cross_notes = (cross_inspection.notes
                       if cross_inspection is not None else ())
        reported_score = item.score
        if reported_score is not None:
            prong_checks = [
                check for check in checks
                if check.code == "render_crosscheck:prong_count"
            ]
            if any(
                not check.passed and check.severity is CheckSeverity.HARD
                for check in prong_checks
            ):
                reported_score = min(reported_score, 40.0)
            elif any(not check.passed for check in prong_checks):
                reported_score = min(reported_score, 60.0)
        return _report(
            checks, score=reported_score, notes=(*item.notes, *cross_notes))

    def _edit_report(
        self,
        plan: ImageAgentPlan,
        item: EditInspection,
        *,
        cross_inspection: EditCrossInspection | None,
        target_spec_cross: RenderCrossInspection | None,
        source_image: bytes,
        candidate: bytes,
        mask_bytes: bytes | None,
    ) -> ImageQualityReport:
        checks = [
            *_deterministic_checks(candidate, source_image=source_image),
            _match_check(
                "requested_change",
                item.change_applied,
                "the requested change was not visibly applied",
                "the requested change could not be visually confirmed",
            ),
            _match_check(
                "protected_regions",
                item.protected_regions_preserved,
                "protected jewelry regions changed outside the requested scope",
                "preservation of protected regions could not be confirmed",
            ),
        ]
        severity = item.unintended_severity
        checks.append(QualityCheck(
            code="unintended_drift",
            passed=severity == "none",
            severity=(CheckSeverity.HARD if severity == "major"
                      else CheckSeverity.WARNING),
            message=("no unintended changes detected" if severity == "none"
                     else "unintended changes: " +
                     (", ".join(item.unintended_changes) or severity)),
            evidence={"severity": severity,
                      "changes": list(item.unintended_changes)},
        ))
        if plan.operation is ImageOperation.LOCAL_EDIT:
            delta = plan.normalized_intent.get("spec_delta", [])
            spec_check = _match_check(
                "spec_change",
                item.spec_change_matches,
                "visible local change does not match the validated result spec",
                "result-spec conformance could not be confirmed",
            )
            checks.append(spec_check.model_copy(update={
                "evidence": {"spec_delta": delta},
            }))
            for domain in plan.edit_domains:
                observed = item.domain_matches.get(domain.value)
                domain_check = _match_check(
                    f"edit_domain:{domain.value}",
                    observed,
                    f"visible edit does not match the '{domain.value}' result facts",
                    f"'{domain.value}' conformance could not be visually confirmed",
                )
                checks.append(domain_check.model_copy(update={
                    "evidence": {
                        "domain": domain.value,
                        "spec_delta": delta,
                    },
                }))
            if DesignerEditDomain.SIDE_STONE_INVENTORY in plan.edit_domains:
                contract = plan.normalized_intent.get(
                    "side_stone_inventory_contract", {})
                source_contract = (
                    contract.get("source", {})
                    if isinstance(contract, dict) else {}
                )
                target_contract = (
                    contract.get("target", {})
                    if isinstance(contract, dict) else {}
                )
                expected_source = (
                    source_contract.get("total_count")
                    if isinstance(source_contract, dict) else None
                )
                expected_target = (
                    target_contract.get("total_count")
                    if isinstance(target_contract, dict) else None
                )
                observed = item.side_stone_inventory
                source_match: bool | None = None
                target_match: bool | None = None
                if observed is not None:
                    if (observed.source_count_complete is True
                            and observed.source_visible_count is not None
                            and isinstance(expected_source, int)):
                        source_match = (
                            observed.source_visible_count == expected_source)
                    if (observed.candidate_count_complete is True
                            and observed.candidate_visible_count is not None
                            and isinstance(expected_target, int)):
                        target_match = (
                            observed.candidate_visible_count == expected_target)
                checks.extend([
                    _match_check(
                        "inventory_source_count",
                        source_match,
                        "the approved source image visibly contradicts its side-stone inventory",
                        "the complete source side-stone count is not assessable in this view",
                    ).model_copy(update={"evidence": {
                        "expected": expected_source,
                        "observed": (
                            observed.source_visible_count
                            if observed is not None else None
                        ),
                        "complete": (
                            observed.source_count_complete
                            if observed is not None else None
                        ),
                        "role_counts": (
                            observed.source_role_counts
                            if observed is not None else {}
                        ),
                    }}),
                    _match_check(
                        "inventory_target_count",
                        target_match,
                        "candidate does not show the exact target side-stone count",
                        "the complete candidate side-stone count is not assessable in this view",
                    ).model_copy(update={"evidence": {
                        "expected": expected_target,
                        "observed": (
                            observed.candidate_visible_count
                            if observed is not None else None
                        ),
                        "complete": (
                            observed.candidate_count_complete
                            if observed is not None else None
                        ),
                        "role_counts": (
                            observed.candidate_role_counts
                            if observed is not None else {}
                        ),
                    }}),
                ])
            checks.extend(_necklace_chain_style_checks(
                plan, item.chain_style))
            if cross_inspection is not None:
                if not cross_inspection.checked:
                    checks.append(QualityCheck(
                        code="independent_edit_audit",
                        passed=False,
                        severity=CheckSeverity.WARNING,
                        message=(
                            "independent edit audit was unavailable; designer "
                            "review is required"
                        ),
                    ))
                else:
                    checks.extend([
                        _match_check(
                            "crosscheck_requested_change",
                            cross_inspection.change_applied,
                            "independent audit found the requested change missing",
                            "independent audit could not confirm the requested change",
                        ),
                        _match_check(
                            "crosscheck_frozen_facts",
                            cross_inspection.frozen_facts_preserved,
                            "independent audit found a frozen fact changed",
                            "independent audit could not confirm every frozen fact",
                        ),
                    ])
                    cross_severity = cross_inspection.unintended_severity
                    checks.append(QualityCheck(
                        code="crosscheck_unintended_drift",
                        passed=cross_severity == "none",
                        severity=(
                            CheckSeverity.HARD
                            if cross_severity == "major"
                            else CheckSeverity.WARNING
                        ),
                        message=(
                            "independent audit found no unintended changes"
                            if cross_severity == "none"
                            else "independent audit differences: "
                            + (", ".join(cross_inspection.unintended_changes)
                               or cross_severity)
                        ),
                        evidence={
                            "severity": cross_severity,
                            "changes": list(
                                cross_inspection.unintended_changes),
                        },
                    ))
                    checks.append(QualityCheck(
                        code="crosscheck_edit_domains",
                        passed=not cross_inspection.domain_mismatches,
                        severity=CheckSeverity.HARD,
                        message=(
                            "independent audit matched every required edit domain"
                            if not cross_inspection.domain_mismatches
                            else "independent audit domain mismatches: "
                            + ", ".join(cross_inspection.domain_mismatches)
                        ),
                        evidence={
                            "domain_mismatches": list(
                                cross_inspection.domain_mismatches),
                        },
                    ))
            if target_spec_cross is not None:
                checks.extend(_render_cross_checks(
                    target_spec_cross,
                    prefix="target_spec_crosscheck",
                ))
                if (DesignerEditDomain.SIDE_STONE_INVENTORY
                        in plan.edit_domains):
                    inventory_contract = plan.normalized_intent.get(
                        "side_stone_inventory_contract", {})
                    target_inventory = (
                        inventory_contract.get("target", {})
                        if isinstance(inventory_contract, dict) else {}
                    )
                    expected_count = (
                        target_inventory.get("total_count")
                        if isinstance(target_inventory, dict) else None
                    )
                    observed_count = (
                        target_spec_cross.observed_side_stone_count)
                    count_complete = (
                        target_spec_cross
                        .observed_side_stone_count_complete)
                    independent_count_match: bool | None = None
                    if (isinstance(expected_count, int)
                            and isinstance(observed_count, int)
                            and count_complete is True):
                        independent_count_match = (
                            observed_count == expected_count)
                    checks.append(_match_check(
                        "inventory_independent_target_count",
                        independent_count_match,
                        "independent blind count contradicts the exact target side-stone inventory",
                        "independent blind count could not prove the exact target side-stone inventory",
                    ).model_copy(update={"evidence": {
                        "expected": expected_count,
                        "observed": observed_count,
                        "complete": count_complete,
                    }}))
            _apply_ambiguous_metal_policy(checks, plan)
            source_band = (plan.source_spec_facts or {}).get("band")
            target_band = plan.spec_facts.get("band")
            before = (source_band.get("width_mm")
                      if isinstance(source_band, dict) else None)
            after = (target_band.get("width_mm")
                     if isinstance(target_band, dict) else None)
            if (isinstance(before, (int, float))
                    and isinstance(after, (int, float))
                    and before != after):
                from facetta.image_agent.band_drift import (
                    band_width_change_evidence,
                )

                evidence = band_width_change_evidence(
                    source_image,
                    candidate,
                    before_mm=float(before),
                    after_mm=float(after),
                )
                visible = bool(
                    evidence.get("checked") and evidence.get("change_visible"))
                framing_stable = bool(
                    evidence.get("checked") and evidence.get("framing_stable"))
                for index, check in enumerate(checks):
                    if check.code in {
                        "requested_change",
                        "spec_change",
                        "edit_domain:"
                        f"{DesignerEditDomain.BAND_GEOMETRY.value}",
                    }:
                        checks[index] = check.model_copy(update={
                            # Deterministic silhouette evidence is the final
                            # authority for this narrow geometric operation.
                            # A vision judge cannot waive an unchanged band or
                            # a changed camera/framing contract.
                            "passed": visible,
                            "message": (
                                "deterministic lower-shank silhouette evidence "
                                "confirms a visible band-width change"
                                if visible else
                                "camera/framing changed too much to verify an "
                                "isolated band-width edit"
                                if evidence.get("checked") and not framing_stable
                                else
                                "deterministic lower-shank silhouette evidence "
                                "did not confirm the requested width change"
                            ),
                            "evidence": {**check.evidence, **evidence},
                        })
                checks.append(QualityCheck(
                    code="band_edit_presentation_lock",
                    passed=framing_stable,
                    severity=CheckSeverity.HARD,
                    message=(
                        "camera, crop, scale, and framing stayed stable enough "
                        "for isolated band comparison"
                        if framing_stable else
                        "camera, crop, scale, or framing changed during the "
                        "band edit; the result is not an isolated adjustment"
                    ),
                    evidence=evidence,
                ))
                if visible:
                    checks.append(QualityCheck(
                        code="exact_band_width",
                        passed=False,
                        severity=CheckSeverity.WARNING,
                        message=(
                            "the width change is visible, but a raster image "
                            "cannot prove exact millimeters; review against the spec"
                        ),
                        evidence={
                            **evidence,
                            "before_mm": float(before),
                            "after_mm": float(after),
                        },
                    ))
            if DesignerEditDomain.SETTING in plan.edit_domains:
                footprint = center_stone_footprint_evidence(
                    source_image, candidate)
                if footprint.get("checked"):
                    stable = bool(footprint.get("stable"))
                    checks.append(QualityCheck(
                        code="setting_center_stone_footprint_lock",
                        passed=stable,
                        severity=CheckSeverity.HARD,
                        message=(
                            "center-stone face-up envelope stayed fixed during "
                            "the setting edit"
                            if stable else
                            "setting edit changed the center stone's apparent "
                            "face-up size, shape envelope, or position"
                        ),
                        evidence=footprint,
                    ))
        else:
            checks.append(_match_check(
                "geometry_preserved",
                item.geometry_preserved,
                "a presentation-only edit changed jewelry geometry or components",
                "geometry preservation could not be confirmed",
            ))
        if item.text_or_branding_detected is True:
            checks.append(QualityCheck(
                code="text_or_branding",
                passed=False,
                severity=CheckSeverity.HARD,
                message="edit introduced text, a logo, watermark, or invented branding",
            ))
        elif item.text_or_branding_detected is False:
            checks.append(QualityCheck(
                code="text_or_branding",
                passed=True,
                severity=CheckSeverity.HARD,
                message="no text or branding introduced",
            ))
        elif plan.is_necklace_chain_style_edit:
            checks.append(QualityCheck(
                code="text_or_branding",
                passed=False,
                severity=CheckSeverity.WARNING,
                message=(
                    "absence of text, a logo, watermark, or invented branding "
                    "could not be confirmed; designer review is required"
                ),
            ))
        if mask_bytes is not None:
            checks.extend(self._masked_change_checks(
                plan,
                source_image,
                candidate,
                mask_bytes,
            ))
        cross_notes = (cross_inspection.notes
                       if cross_inspection is not None else ())
        target_notes = (target_spec_cross.notes
                        if target_spec_cross is not None else ())
        reported_score = item.score
        if (reported_score is not None
                and DesignerEditDomain.SIDE_STONE_INVENTORY
                in plan.edit_domains):
            count_checks = [
                check for check in checks
                if check.code in {
                    "inventory_source_count",
                    "inventory_target_count",
                    "inventory_independent_target_count",
                }
            ]
            if any(
                not check.passed and check.severity is CheckSeverity.HARD
                for check in count_checks
            ):
                reported_score = min(reported_score, 40.0)
            elif any(not check.passed for check in count_checks):
                # An exact inventory edit that cannot be counted is useful for
                # designer review, but it must not advertise pass-level
                # confidence merely because its composition looks polished.
                reported_score = min(reported_score, 60.0)
        if reported_score is not None:
            topology_checks = [
                check for check in checks
                if check.code in {
                    "target_spec_crosscheck:setting_style",
                    "target_spec_crosscheck:prong_count",
                }
            ]
            if any(
                not check.passed and check.severity is CheckSeverity.HARD
                for check in topology_checks
            ):
                reported_score = min(reported_score, 40.0)
            elif any(not check.passed for check in topology_checks):
                reported_score = min(reported_score, 60.0)
        return _report(
            checks,
            score=reported_score,
            notes=(*item.notes, *cross_notes, *target_notes),
        )


MaterialAudit = Callable[[bytes, bytes], dict]
RasterMaterialAudit = Callable[[bytes, bytes], dict]
ColoredLineArtAudit = Callable[[bytes, bytes], dict]
ConfirmedLineArtAudit = Callable[[bytes, bytes, dict, str], dict]


class MaterialIdentityQualityEvaluator:
    """Add approved-source material identity to every colorization attempt.

    This decorator deliberately runs *inside* ``JewelryImageAgent``. A lost
    diamond or reassigned metal zone therefore becomes a structured QA failure
    that compiles into the second Grok attempt's targeted correction.
    """

    def __init__(
        self,
        approved_source: bytes,
        base: RingQualityEvaluator | None = None,
        *,
        material_audit: MaterialAudit | None = None,
        raster_audit: RasterMaterialAudit | None = None,
    ) -> None:
        self.approved_source = approved_source
        self.base = base or RingQualityEvaluator()
        self._material_audit = material_audit
        self._raster_audit = raster_audit

    def evaluate(
        self,
        plan: ImageAgentPlan,
        candidate: bytes,
        *,
        source_image: bytes | None,
        mask_bytes: bytes | None,
    ) -> ImageQualityReport:
        report = self.base.evaluate(
            plan,
            candidate,
            source_image=source_image,
            mask_bytes=mask_bytes,
        )
        check, differences = self._check(candidate)
        checks = (*report.checks, check)
        if not check.passed and check.severity is CheckSeverity.HARD:
            score = min(report.score or 100, 35)
        elif not check.passed:
            score = min(report.score or 100, 82)
        else:
            score = report.score
        return _report(
            list(checks),
            score=score,
            notes=(*report.notes, *differences),
        )

    def _check(self, candidate: bytes) -> tuple[QualityCheck, tuple[str, ...]]:
        from facetta.image_agent.material_drift import white_stone_to_gold_drift
        from facetta.image_agent.vision import check_material_identity

        raster_fn = self._raster_audit or white_stone_to_gold_drift
        raster = raster_fn(self.approved_source, candidate)
        raster_failed = bool(raster.get("checked") and raster.get("failed"))
        # Cross-modality pixel alignment (photo -> line illustration) can
        # over-count gold structural regions after small pose shifts. Raster
        # evidence therefore escalates review but cannot prove material loss
        # without at least one independent semantic audit agreeing.
        if self._material_audit is not None:
            samples = [
                self._material_audit(self.approved_source, candidate),
                self._material_audit(self.approved_source, candidate),
            ]
        else:
            samples = [
                check_material_identity(
                    self.approved_source,
                    candidate,
                    focus=(
                        "inventory every gemstone and metal group in the "
                        "source, then map each group to the candidate"
                    ),
                ),
                check_material_identity(
                    self.approved_source,
                    candidate,
                    focus=(
                        "adversarially search for white diamond, pave, leaf, "
                        "halo, or shoulder stone outlines that became gold or metal"
                    ),
                ),
            ]
        checked_samples = [sample for sample in samples if sample.get("checked")]
        consistent_samples = [
            sample for sample in checked_samples if sample.get("consistent")
        ]
        major_samples = [
            sample for sample in checked_samples
            if not sample.get("consistent") and sample.get("severity") == "major"
        ]
        differences = list(dict.fromkeys(
            str(item)
            for sample in samples
            for item in sample.get("differences", [])
        ))
        if raster_failed:
            differences.append(
                "deterministic raster audit found widespread white-stone "
                "regions converted to gold"
            )
        checked = bool(samples) and len(checked_samples) == len(samples)
        passed = (
            checked
            and len(consistent_samples) == len(samples)
            and bool(raster.get("checked"))
            and not raster_failed
        )
        hard_failure = (
            checked and len(major_samples) == len(samples)
        ) or (raster_failed and bool(major_samples))
        severity_value = (
            "none" if passed else
            "major" if hard_failure else
            "disagreement" if checked_samples else "unknown"
        )
        return QualityCheck(
            code="approved_source_material_identity",
            passed=passed,
            severity=(
                CheckSeverity.HARD if passed or hard_failure
                else CheckSeverity.WARNING
            ),
            message=(
                "all visible stone and metal zones match the approved source"
                if passed else
                (
                    "material assignment changed from the approved source: "
                    if hard_failure else
                    "material identity requires designer review because "
                    "automated checks disagree: "
                ) + (", ".join(differences) or severity_value)
            ),
            evidence={
                "checked": checked or bool(raster.get("checked")),
                "severity": severity_value,
                "differences": differences,
                "sample_verdicts": [
                    {
                        "checked": bool(sample.get("checked")),
                        "consistent": bool(sample.get("consistent")),
                        "severity": str(sample.get("severity") or "unknown"),
                    }
                    for sample in samples
                ],
                "raster_white_to_gold": raster,
            },
        ), tuple(differences)


class ConfirmedLineArtQualityEvaluator:
    """Guard the geometry-normalization stage before designer confirmation."""

    def __init__(
        self,
        base: RingQualityEvaluator | None = None,
        *,
        line_art_audit: ConfirmedLineArtAudit | None = None,
    ) -> None:
        self.base = base or RingQualityEvaluator(
            require_cross_inspection=False,
            require_render_cross_inspection=False,
        )
        self._line_art_audit = line_art_audit

    def evaluate(
        self,
        plan: ImageAgentPlan,
        candidate: bytes,
        *,
        source_image: bytes | None,
        mask_bytes: bytes | None,
    ) -> ImageQualityReport:
        if source_image is None:
            raise ValueError("line-art QA requires the imported source")
        report = self.base.evaluate(
            plan,
            candidate,
            source_image=source_image,
            mask_bytes=mask_bytes,
        )
        check, differences = self._check(plan, source_image, candidate)
        if not check.passed and check.severity is CheckSeverity.HARD:
            score = min(report.score or 100, 30)
        elif not check.passed:
            score = min(report.score or 100, 80)
        else:
            score = report.score
        return _report(
            [*report.checks, check],
            score=score,
            notes=(*report.notes, *differences),
        )

    def _check(
        self,
        plan: ImageAgentPlan,
        source: bytes,
        candidate: bytes,
    ) -> tuple[QualityCheck, tuple[str, ...]]:
        from facetta.image_agent.vision import (
            check_confirmed_line_art_contract,
        )

        expected = {
            "setting": plan.spec_facts.get("setting"),
            "side_stones": plan.spec_facts.get("side_stones", []),
            "jewelry_type": plan.spec_facts.get("jewelry_type"),
            "template": plan.spec_facts.get("template"),
        }
        focuses = (
            (
                "Count center prongs and every repeated stone group; compare "
                "the complete jewelry geometry component by component."
            ),
            (
                "Adversarially inspect the second image's bottom edge, corners, "
                "and faint regions for captions, signatures, watermarks, social "
                "IDs, logos, or any non-jewelry mark; then recount components."
            ),
        )
        if self._line_art_audit is None:
            samples = [
                check_confirmed_line_art_contract(
                    source,
                    candidate,
                    expected_facts=expected,
                    focus=focus,
                )
                for focus in focuses
            ]
        else:
            samples = [
                self._line_art_audit(source, candidate, expected, focus)
                for focus in focuses
            ]
        checked_samples = [sample for sample in samples if sample.get("checked")]
        failures: set[str] = set()
        differences: list[str] = []
        for sample in samples:
            differences.extend(str(item) for item in sample.get("differences", []))
            if sample.get("black_line_art_on_white") is False:
                failures.add("black_line_art_on_white")
            if sample.get("single_assembled_view") is False:
                failures.add("single_assembled_view")
            if sample.get("source_geometry_preserved") is False:
                failures.add("source_geometry_preserved")
            if sample.get("center_prong_count_matches") is False:
                failures.add("center_prong_count_matches")
            if sample.get("side_stone_inventory_matches") is False:
                failures.add("side_stone_inventory_matches")
            if sample.get("candidate_text_or_branding_detected") is True:
                failures.add("candidate_text_or_branding")
            if sample.get("colored_or_photorealistic") is True:
                failures.add("colored_or_photorealistic")
        differences = list(dict.fromkeys(differences))
        desired = (
            ("black_line_art_on_white", True),
            ("single_assembled_view", True),
            ("source_geometry_preserved", True),
            ("center_prong_count_matches", True),
            ("side_stone_inventory_matches", True),
            ("candidate_text_or_branding_detected", False),
            ("colored_or_photorealistic", False),
        )
        passed = len(checked_samples) == len(samples) and not failures and all(
            all(sample.get(key) is expected_value for key, expected_value in desired)
            for sample in samples
        )
        hard_failure = bool(checked_samples) and bool(failures)
        if passed:
            message = (
                "candidate is clean single-view black line art with exact "
                "source geometry, validated counts, and no text or branding"
            )
        elif hard_failure:
            message = (
                "line-art candidate violated the confirmed drawing contract: "
                + ", ".join(sorted(failures))
                + ". Regenerate one clean black-on-white assembled view with "
                "the exact validated center-prong and side-stone counts; remove "
                "every caption, signature, watermark, social ID, logo, and brand"
            )
        else:
            message = (
                "line-art geometry, counts, or output hygiene could not be "
                "independently proven; explicit designer review is required"
            )
        return QualityCheck(
            code="confirmed_line_art_contract",
            passed=passed,
            severity=(
                CheckSeverity.HARD if passed or hard_failure
                else CheckSeverity.WARNING
            ),
            message=message,
            evidence={
                "expected": expected,
                "failures": sorted(failures),
                "differences": differences,
                "samples": [{
                    "checked": bool(sample.get("checked")),
                    "observed_center_prong_count": sample.get(
                        "observed_center_prong_count"
                    ),
                    "observed_side_stone_counts": sample.get(
                        "observed_side_stone_counts", []
                    ),
                    "candidate_text_or_branding_detected": sample.get(
                        "candidate_text_or_branding_detected"
                    ),
                    "severity": str(sample.get("severity") or "unknown"),
                } for sample in samples],
            },
        ), tuple(differences)


class ColoredLineArtQualityEvaluator:
    """Keep the confirmed line drawing as the color stage's exact substrate.

    A plausible photorealistic ring is still a failure here: beauty rendering
    is the next, separately reviewed operation. This decorator adds that
    workflow-specific hard gate after the existing geometry and approved-source
    material checks, so a failure becomes a targeted Grok correction.
    """

    def __init__(
        self,
        approved_source: bytes,
        base: MaterialIdentityQualityEvaluator | None = None,
        *,
        line_art_audit: ColoredLineArtAudit | None = None,
    ) -> None:
        self.base = base or MaterialIdentityQualityEvaluator(approved_source)
        self._line_art_audit = line_art_audit

    def evaluate(
        self,
        plan: ImageAgentPlan,
        candidate: bytes,
        *,
        source_image: bytes | None,
        mask_bytes: bytes | None,
    ) -> ImageQualityReport:
        if source_image is None:
            raise ValueError("colored-line-art QA requires confirmed line art")
        report = self.base.evaluate(
            plan,
            candidate,
            source_image=source_image,
            mask_bytes=mask_bytes,
        )
        check, differences = self._check(source_image, candidate)
        if not check.passed and check.severity is CheckSeverity.HARD:
            score = min(report.score or 100, 30)
        elif not check.passed:
            score = min(report.score or 100, 80)
        else:
            score = report.score
        return _report(
            [*report.checks, check],
            score=score,
            notes=(*report.notes, *differences),
        )

    def _check(
        self,
        confirmed_line_art: bytes,
        candidate: bytes,
    ) -> tuple[QualityCheck, tuple[str, ...]]:
        from facetta.image_agent.vision import check_colored_line_art_contract

        audit = (
            self._line_art_audit(confirmed_line_art, candidate)
            if self._line_art_audit is not None
            else check_colored_line_art_contract(
                confirmed_line_art, candidate
            )
        )
        checked = bool(audit.get("checked"))
        failures = {
            "linework_retained": audit.get("linework_retained") is False,
            "color_inside_existing_geometry": (
                audit.get("color_inside_existing_geometry") is False
            ),
            "technical_illustration_style": (
                audit.get("technical_illustration_style") is False
            ),
            "photorealistic_replacement": (
                audit.get("photorealistic_replacement") is True
            ),
            "geometry_consistent": audit.get("geometry_consistent") is False,
        }
        explicit_failures = [key for key, failed in failures.items() if failed]
        passed = checked and not explicit_failures and all(
            audit.get(key) is expected
            for key, expected in (
                ("linework_retained", True),
                ("color_inside_existing_geometry", True),
                ("technical_illustration_style", True),
                ("photorealistic_replacement", False),
                ("geometry_consistent", True),
            )
        )
        differences = tuple(dict.fromkeys(
            str(item) for item in audit.get("differences", [])
        ))
        hard_failure = checked and bool(explicit_failures)
        if passed:
            message = (
                "confirmed black technical linework remains visible and color "
                "is confined to the existing illustration geometry"
            )
        elif hard_failure:
            message = (
                "the color stage violated the confirmed-line-art contract: "
                + ", ".join(explicit_failures)
                + ". Retain the original black technical outlines and apply "
                "controlled color only inside that existing geometry; do not "
                "replace it with a photorealistic or newly rendered ring"
            )
        else:
            message = (
                "retention of the confirmed black technical linework could not "
                "be proven; designer review is required before beauty rendering"
            )
        return QualityCheck(
            code="colored_line_art_contract",
            passed=passed,
            severity=(
                CheckSeverity.HARD if passed or hard_failure
                else CheckSeverity.WARNING
            ),
            message=message,
            evidence={
                "checked": checked,
                "linework_retained": audit.get("linework_retained"),
                "color_inside_existing_geometry": audit.get(
                    "color_inside_existing_geometry"
                ),
                "technical_illustration_style": audit.get(
                    "technical_illustration_style"
                ),
                "photorealistic_replacement": audit.get(
                    "photorealistic_replacement"
                ),
                "geometry_consistent": audit.get("geometry_consistent"),
                "severity": str(audit.get("severity") or "unknown"),
                "differences": list(differences),
            },
        ), differences

"""Versioned prompt contracts and targeted QA corrections."""

from __future__ import annotations

import json

from facetta.image_agent.contracts import (
    CheckSeverity,
    DesignerEditDomain,
    ImageAgentPlan,
    ImageOperation,
    ImageQualityReport,
)
from facetta.image_agent.edit_prompt import compile_localized_edit_instruction
from facetta.drawing_intake import (
    DrawingIntakeFacts,
    build_drawing_processing_contract,
)
from facetta.mounting_hardware import compile_mounting_view_prompt
from facetta.spec import Spec


PROMPT_VERSIONS = {
    ImageOperation.CREATIVE_GENERATE: "creative-generate.v3",
    ImageOperation.CONCEPT_GENERATE: "concept-generate.v1",
    ImageOperation.REFERENCE_RENDER: "reference-render.v1",
    ImageOperation.SPEC_RENDER: "spec-render.v3",
    ImageOperation.LOCAL_EDIT: "local-edit.v8",
    ImageOperation.VISUAL_ONLY_EDIT: "visual-only-edit.v2",
    ImageOperation.MOUNTING_VIEW_GENERATE: "mounting-view.v1",
}

# Keep one conservative orchestration boundary below OpenAI's provider-level
# 32,000-character guard while leaving room for a bounded preservation
# correction. The prior 8,000-character ceiling admitted the initial Refine
# contract but mechanically rejected its first QA correction before execution.
MAX_PROVIDER_PROMPT_CHARS = 16_000

# These warnings concern the exact requested visual operation and can improve
# through a targeted retry. Other warnings (for example raster dimensional or
# alloy uncertainty) are designer-review facts, not reasons to regenerate.
RETRYABLE_VISUAL_WARNING_CODES = frozenset({
    "target_spec_crosscheck:prong_count",
    "target_spec_crosscheck:side_stone_inventory",
    "inventory_target_count",
    "inventory_independent_target_count",
})

_PROMPT_VISUAL_ROOTS = (
    "jewelry_type",
    "template",
    "stone",
    "setting",
    "metal",
    "band",
    "ring_size",
    "bracelet",
    "pendant",
    "chain",
    "brooch",
    "drop",
    "side_stones",
    "design_form",
)


def _prune_prompt_value(value: object) -> object | None:
    if value is None:
        return None
    if isinstance(value, dict):
        compact = {
            key: projected
            for key, item in value.items()
            if (projected := _prune_prompt_value(item)) is not None
        }
        return compact or None
    if isinstance(value, list):
        compact = [
            projected
            for item in value
            if (projected := _prune_prompt_value(item)) is not None
        ]
        return compact or None
    return value


def _compact_design_form(value: object) -> object | None:
    if not isinstance(value, dict) or not isinstance(value.get("elements"), list):
        return None
    elements = []
    for raw in value["elements"]:
        if not isinstance(raw, dict):
            continue
        elements.append({
            key: raw[key]
            for key in (
                "element_id",
                "role",
                "label",
                "confirmed_form_description",
                "symmetry",
                "instance_count",
            )
            if raw.get(key) is not None
        })
    return {"elements": elements} if elements else None


def _prompt_fact_payload(
    plan: ImageAgentPlan,
    *,
    source: bool = False,
) -> dict[str, object]:
    """Project the immutable spec into concise pixel-relevant instructions.

    Full specs remain on ``ImageAgentPlan`` for QA and persistence. Provider
    prompts exclude provenance, source-audit evidence, notes, procurement
    references, null/default fields, and image-space polygons. This is a prompt
    projection only; it never changes the spec hash or validation record.
    """

    raw = plan.source_spec_facts if source else plan.spec_facts
    if not isinstance(raw, dict):
        return {}
    projected: dict[str, object] = {}
    for key in _PROMPT_VISUAL_ROOTS:
        value = raw.get(key)
        if key == "design_form":
            compact = _compact_design_form(value)
        else:
            compact = _prune_prompt_value(value)
        if compact is not None:
            projected[key] = compact
        elif key == "side_stones":
            # An explicit empty inventory is a meaningful visual lock.
            projected[key] = []
    chain = projected.get("chain")
    if isinstance(chain, dict):
        chain.pop("production", None)
    return projected


def _facts(plan: ImageAgentPlan) -> str:
    return json.dumps(
        _prompt_fact_payload(plan), sort_keys=True, separators=(",", ":"))


def _locks(plan: ImageAgentPlan) -> str:
    return "\n".join(f"- {item}" for item in plan.frozen)


def _style(plan: ImageAgentPlan) -> str:
    if not plan.style_constraints:
        return "Fine-jewelry product presentation; physically coherent materials."
    return "\n".join(f"- {item}" for item in plan.style_constraints)


def _spec_delta(plan: ImageAgentPlan) -> str:
    changes = plan.normalized_intent.get("spec_delta", [])
    if not isinstance(changes, list) or not changes:
        return "No structural specification delta was supplied."
    lines: list[str] = []
    for change in changes:
        if isinstance(change, dict):
            label = change.get("label", change.get("path", "field"))
            before = change.get("from", "—")
            after = change.get("to", "—")
            lines.append(f"- {label}: {before} -> {after}")
    return "\n".join(lines) or "No structural specification delta was supplied."


def _geometry_execution(plan: ImageAgentPlan) -> str:
    """Translate numeric spec deltas into visible, model-actionable geometry."""
    if plan.operation is not ImageOperation.LOCAL_EDIT:
        return ""
    source_band = (plan.source_spec_facts or {}).get("band")
    target_band = plan.spec_facts.get("band")
    if not isinstance(source_band, dict) or not isinstance(target_band, dict):
        return ""
    before = source_band.get("width_mm")
    after = target_band.get("width_mm")
    if not isinstance(before, (int, float)) or not isinstance(after, (int, float)):
        return ""
    if before <= 0 or before == after:
        return ""
    percent = abs(after - before) / before * 100
    direction = "widen" if after > before else "narrow"
    edge_direction = "outward" if after > before else "inward"
    return (
        "BAND-WIDTH GEOMETRY EXECUTION (not a lighting or reflection change):\n"
        f"- {direction.upper()} the visible band from {before:g} mm to "
        f"{after:g} mm, approximately {percent:.1f}% in relative width.\n"
        f"- Move both visible outer shank edges {edge_direction} symmetrically "
        "about the existing band centerline throughout the highlighted lower shank.\n"
        "- Keep ring inner diameter/circumference, band thickness, camera, stone, "
        "setting, shoulders, reflections, and every non-band element fixed.\n"
        "- The silhouette must be visibly different; changing only highlight "
        "width, polish, brightness, or shadow does not satisfy this edit."
    )


def _target_fact(plan: ImageAgentPlan, key: str) -> str:
    return json.dumps(
        _prompt_fact_payload(plan).get(key),
        sort_keys=True,
        separators=(",", ":"),
    )


def _common_edit_execution(plan: ImageAgentPlan) -> str:
    """Compile validated deltas into jewelry-specific visual actions."""
    if plan.operation is not ImageOperation.LOCAL_EDIT:
        return ""
    domains = set(plan.edit_domains)
    clauses: list[str] = []

    if DesignerEditDomain.CENTER_STONE_SHAPE in domains:
        clauses.append(
            "CENTER-STONE SHAPE EXECUTION:\n"
            "- Reshape only the center-stone outline and facet pattern to the "
            "target cut; do not simulate the change with reflections.\n"
            "- Use the target face-up dimensions and orientation. If those facts "
            "did not change, preserve their apparent scale and orientation.\n"
            "- Preserve species and visible color unless explicitly changed. "
            "Adapt only the setting/prongs stated by the validated result facts.\n"
            f"- TARGET CENTER STONE: {_target_fact(plan, 'stone')}"
        )
    if (DesignerEditDomain.CENTER_STONE_IDENTITY in domains
            or DesignerEditDomain.CENTER_STONE_COLOR in domains):
        clauses.append(
            "CENTER-STONE MATERIAL/COLOR EXECUTION:\n"
            "- Change only the center stone's optical species/color character.\n"
            "- Preserve cut, face-up scale, orientation, setting, prongs, and all "
            "surrounding jewelry unless the exact spec delta names them.\n"
            "- Do not recolor metal or side stones as spillover.\n"
            f"- TARGET CENTER STONE: {_target_fact(plan, 'stone')}"
        )
    if DesignerEditDomain.SIDE_STONE_INVENTORY in domains:
        inventory_contract = plan.normalized_intent.get(
            "side_stone_inventory_contract", {})
        clauses.append(
            "SIDE-STONE INVENTORY EXECUTION:\n"
            "- Treat the structured source-to-target inventory below as one atomic "
            "operation. Render exactly the target groups, roles, shapes, identities, "
            "dimensions, and individually countable visible quantities.\n"
            "- Apply the exact total and per-group count delta. Do not fake a removal "
            "by hiding a stone, cropping it, merging two stones, shrinking stones into "
            "beads, or calling prongs/claws stones. Do not fake an addition with metal "
            "beads, reflections, or duplicated prongs.\n"
            "- When a complete halo remains, redistribute its target count evenly and "
            "coherently around the unchanged center while preserving each target "
            "stone's stated size and shape. When the target has no halo, remove the "
            "entire halo assembly without leaving residual melee or bead-set metal.\n"
            "- Preserve the center stone, setting, band, metal, and every unedited "
            "side-stone group. Do not replace stones with metal decoration.\n"
            "- SOURCE-TO-TARGET INVENTORY CONTRACT: "
            f"{json.dumps(inventory_contract, sort_keys=True, separators=(',', ':'))}\n"
            f"- TARGET SIDE-STONE INVENTORY: {_target_fact(plan, 'side_stones')}"
        )
    if DesignerEditDomain.SIDE_STONE_SHAPE in domains:
        clauses.append(
            "SIDE-STONE / MOTIF SHAPE EXECUTION:\n"
            "- Reshape only the affected side-stone or gem-built motif elements to "
            "the target cut and outline. Preserve their count, dimensions, position, "
            "spacing, material identity, and neighboring pave unless changed in the "
            "exact delta.\n"
            f"- TARGET SIDE-STONE FACTS: {_target_fact(plan, 'side_stones')}"
        )
    if DesignerEditDomain.SIDE_STONE_IDENTITY in domains:
        clauses.append(
            "SIDE-STONE MATERIAL/COLOR EXECUTION:\n"
            "- Change species/color only for the targeted side-stone group. Preserve "
            "cut, count, dimensions, placement, center stone, and metal unless the "
            "exact delta states otherwise.\n"
            f"- TARGET SIDE-STONE FACTS: {_target_fact(plan, 'side_stones')}"
        )
    if DesignerEditDomain.SETTING in domains:
        setting_contract = plan.normalized_intent.get(
            "setting_topology_contract", {})
        clauses.append(
            "SETTING / PRONG EXECUTION:\n"
            "- Treat the structured source-to-target topology below as one atomic "
            "setting operation. Show exactly the target number of distinct metal "
            "prongs that physically contact and hold the center stone.\n"
            "- Remove or add actual holding prongs and redistribute them coherently "
            "for the target cut. Do not fake removal by hiding, merging, shortening, "
            "or moving a prong behind the stone; do not count halo beads, reflections, "
            "decorative balls, or side-stone claws as center prongs.\n"
            "- Rebuild only the minimum crown/gallery geometry necessary for the "
            "target setting. Preserve the source camera and keep every target prong "
            "visibly distinguishable in the same reviewable view.\n"
            "- Preserve the center stone's identity, cut, scale, orientation, and "
            "position, plus the halo inventory, band, metal, and every unedited "
            "component.\n"
            "- SOURCE-TO-TARGET SETTING TOPOLOGY: "
            f"{json.dumps(setting_contract, sort_keys=True, separators=(',', ':'))}\n"
            f"- TARGET SETTING: {_target_fact(plan, 'setting')}"
        )
    if DesignerEditDomain.METAL_IDENTITY in domains:
        clauses.append(
            "METAL MATERIAL/COLOR EXECUTION:\n"
            "- Apply the target metal material and color consistently to every metal "
            "surface, including prongs, gallery, shoulders, and shank.\n"
            "- Never tint gemstones, replace stones with metal, or change geometry. "
            "Distinguish white gold from platinum by material response without "
            "inventing a structural change.\n"
            f"- TARGET METAL: {_target_fact(plan, 'metal')}"
        )
    if DesignerEditDomain.METAL_FINISH in domains:
        clauses.append(
            "METAL FINISH EXECUTION:\n"
            "- Change only the named surface finish across the applicable metal. "
            "Preserve material/color, geometry, stones, and setting.\n"
            f"- TARGET METAL: {_target_fact(plan, 'metal')}"
        )
    if DesignerEditDomain.BAND_GEOMETRY in domains:
        geometry = _geometry_execution(plan)
        clauses.append(geometry or (
            "BAND GEOMETRY EXECUTION:\n"
            "- Apply only the exact validated band profile, width, or thickness "
            "delta inside the selected shank region. Preserve ring centerline, inner "
            "diameter, shoulders, crown, stones, and camera unless explicitly changed.\n"
            f"- TARGET BAND: {_target_fact(plan, 'band')}"
        ))
    if DesignerEditDomain.RING_SIZE in domains:
        clauses.append(
            "RING-SIZE EXECUTION:\n"
            "- Preserve design identity while applying the validated inner-size "
            "change. The raster is only a visual reference and cannot prove the exact "
            "diameter; the specification remains authoritative.\n"
            f"- TARGET RING SIZE: {_target_fact(plan, 'ring_size')}"
        )
    if DesignerEditDomain.CHAIN_STYLE in domains:
        clauses.append(
            "NECKLACE CHAIN-STYLE EXECUTION:\n"
            "- Replace only the link construction across the COMPLETE VISIBLE "
            "CHAIN RUN: start at each chain-to-bail connection, continue through "
            "every visible segment and every link, and finish at the clasp or "
            "visible endpoint. Do not leave a cable-chain segment mixed into a "
            "curb-chain result or change only a few prominent links.\n"
            "- Preserve the exact pendant count and pendant geometry, bail, "
            "stones, setting, clasp, chain endpoints, apparent chain length and "
            "drape, metal identity, camera, and every non-chain component. Add "
            "or remove no pendant and do not redesign any frozen geometry.\n"
            "- Keep both chain-to-bail connections physically coherent. Do not "
            "copy links into the pendant, bail, clasp, or background.\n"
            "- Preserve the source framing and visible endpoints. If the source "
            "does not visibly show a clasp, do not reveal or invent one; a clasp "
            "named in the validated spec may remain off-frame.\n"
            "- Match the selected catalog link family and its visible construction "
            "consistently. A raster can show style and approximate scale but "
            "cannot prove exact link gauge, pitch, thickness, or dimensions; the "
            "validated specification and designer review remain authoritative.\n"
            f"- TARGET CHAIN: {_target_fact(plan, 'chain')}"
        )
    if DesignerEditDomain.DESIGN_FORM in domains:
        clauses.append(
            "DESIGN-FORM EXECUTION:\n"
            "- Reshape only the stable-ID design element named by the exact delta "
            "to its designer-confirmed target description and normalized marked "
            "region. Do not redesign an adjacent component.\n"
            "- Apply the change consistently to every declared mirrored or repeated "
            "instance of that same element, while preserving all other topology and "
            "all frozen geometry outside the selected region.\n"
            "- The pinned visual reference is image-space evidence only; do not "
            "invent measurements, CAD geometry, extra stones, or decorative details.\n"
            f"- TARGET DESIGN FORM: {_target_fact(plan, 'design_form')}"
        )
    return "\n\n".join(clause for clause in clauses if clause)


def compile_initial_prompt(plan: ImageAgentPlan) -> str:
    """Compile the provider-neutral contract for the first Grok attempt."""

    header = (
        f"FACETTA JEWELRY IMAGE CONTRACT {plan.prompt_version}\n"
        "Return one image only. The final output must contain no non-jewelry "
        "captions, labels, logos, signatures, watermarks, platform/social IDs, "
        "or invented branding. If any such overlay exists in the source, remove "
        "it cleanly; this hygiene cleanup is permitted and is not a jewelry "
        "design change. Preserve only a physical engraving explicitly named in "
        "the validated specification.\n"
    )
    if plan.operation is ImageOperation.CREATIVE_GENERATE:
        task = (
            "TASK: Create one polished, coherent fine-jewelry concept from the "
            f"designer's direction: {plan.intent}\n"
            "Interpret jewelry terminology professionally. The direction may "
            "describe a ring, necklace, pendant, chain, bracelet, earring, "
            "brooch, or another wearable fine-jewelry piece; do not silently "
            "convert it into a ring. Keep the complete piece visible inside "
            "the frame. For a necklace, show the full chain run and endpoints; "
            "do not crop or imply missing carrier sections. Make "
            "materials, settings, stones, connections, repetition, symmetry, "
            "and scale relationships physically coherent. Do not add design "
            "elements merely to fill space. Every explicitly stated numeric "
            "count, including a number written as a word, is an exact visual "
            "constraint: render exactly that many of the named stones or design "
            "elements, never 'at least' that many. Every explicitly named "
            "gemstone species, visible color, cut/shape, and role is exact for "
            "that group; never silently substitute or add another cut shape. "
            "This is a creative visual candidate "
            "for designer selection, not a specification, measured drawing, CAD "
            "model, or claim of manufacturability."
        )
    elif plan.operation is ImageOperation.CONCEPT_GENERATE:
        task = (
            "TASK: Create one coherent, manufacturable-looking fine-jewelry ring "
            f"concept from this designer brief: {plan.intent}\n"
            "The image is a creative reference, not dimensional proof."
        )
    elif plan.operation is ImageOperation.REFERENCE_RENDER:
        drawing_contract = build_drawing_processing_contract(
            DrawingIntakeFacts())
        task = (
            "TASK: Transform the supplied designer image or drawing into one "
            "polished, beautiful, client-reviewable fine-jewelry render. Treat "
            "the source as the design authority even when it is sparse, highly "
            "finished, photographed, scanned, annotated, or unconventional. "
            "Do not classify or grade the source.\n"
            f"DESIGNER DIRECTION: {plan.intent}\n"
            "SOURCE-HANDLING CONTRACT:\n- "
            + "\n- ".join(drawing_contract.prompt_facts)
            + "\nThis output is a creative candidate for designer review, not a "
            "specification, measurement, CAD model, or factory drawing."
        )
    elif plan.operation is ImageOperation.SPEC_RENDER:
        task = (
            "TASK: Render exactly the validated ring facts below. Do not substitute "
            "a different stone, cut family, visible color, metal, setting, prong "
            "structure, component, or assessable stone count. The image is an "
            "approved visual reference, never dimensional evidence.\n"
            f"VALIDATED FACTS: {_facts(plan)}"
        )
        setting = plan.spec_facts.get("setting")
        expected_prongs = (
            setting.get("prong_count") if isinstance(setting, dict) else None
        )
        if isinstance(expected_prongs, int):
            task += (
                "\nCENTER-SETTING VISIBILITY CONTRACT:\n"
                f"- Render exactly {expected_prongs} separate metal prongs that "
                "physically contact and hold the center stone. Every one of the "
                f"{expected_prongs} holding prongs must be individually visible "
                "and countable in this single image.\n"
                "- Choose a face-up or high three-quarter review angle that exposes "
                "the complete center setting. Do not place any holding prong fully "
                "behind the stone or merge two prongs into one silhouette.\n"
                "- Halo beads, side-stone claws, reflections, decorative balls, and "
                "gallery supports are not center prongs and do not satisfy the exact "
                "count. Do not add unlisted pave or shoulder stones."
            )
    elif plan.operation is ImageOperation.MOUNTING_VIEW_GENERATE:
        if plan.mounting_view is None:  # pragma: no cover - plan invariant
            raise ValueError("mounting-view plan is missing its requested view")
        task = compile_mounting_view_prompt(
            Spec.model_validate(plan.spec_facts),
            plan.mounting_view,
        ) + f"\nDESIGNER DIRECTION: {plan.intent}"
    elif plan.operation is ImageOperation.LOCAL_EDIT:
        task = compile_localized_edit_instruction(
            plan.region_description or "",
            plan.intent,
            kind="render",
            jewelry_type=plan.jewelry_type,
        ) + (
            "\nSOURCE SPEC FACTS (before edit): "
            f"{json.dumps(_prompt_fact_payload(plan, source=True), sort_keys=True, separators=(',', ':'))}"
            f"\nVALIDATED RESULT FACTS (after edit): {_facts(plan)}"
            "\nEXACT SPEC DELTA (the visible edit must make this change):\n"
            f"{_spec_delta(plan)}"
        )
        edit_execution = _common_edit_execution(plan)
        if edit_execution:
            task += "\n" + edit_execution
        if plan.mask_hash:
            task += (
                "\nMASK INPUT ORDER: IMAGE 1 is the untouched source. IMAGE 2 "
                "is the localization guide; only its magenta-tinted, "
                "white-outlined region may change. Guide colors must not "
                "appear in the output."
            )
    else:
        region = (f" inside '{plan.region_description}'" if plan.region_description
                  else " across the presentation")
        task = (
            f"TASK: Apply this presentation-only change{region}: {plan.intent}.\n"
            "VISUAL-ONLY LOCK: preserve the exact ring geometry, proportions, "
            "stone identities and counts, setting and prong structure, metal "
            "identity, and all validated design facts. Change no physical design "
            f"property.\nVALIDATED FACTS: {_facts(plan)}"
            "\nSPEC DELTA (must not be visually applied; presentation only):\n"
            f"{_spec_delta(plan)}"
        )

    return "\n\n".join([
        header,
        task,
        "FROZEN — THESE MUST NOT CHANGE:\n" + _locks(plan),
        "STYLE CONSTRAINTS:\n" + _style(plan),
        "EXPECTED OUTPUT: " + plan.expected_output,
    ])


def compile_correction_prompt(
    plan: ImageAgentPlan,
    original_prompt: str,
    report: ImageQualityReport,
) -> tuple[str, str]:
    """Turn observed failures into a specific correction, never "try again"."""

    # Advisory holds (for example, pre-spec factory authority) are product
    # review facts, not visual defects the image model can correct.
    failures = tuple(
        check for check in report.failed_checks
        if (check.severity is CheckSeverity.HARD
            or check.code in RETRYABLE_VISUAL_WARNING_CODES)
    )
    if not failures:
        raise ValueError("a corrective prompt requires at least one failed QA check")
    correction_lines = []
    for check in failures:
        correction_evidence = check.evidence
        if (
            check.code in {
                "six_leaf_ruby_pattern",
                "necklace_sequence_symmetry",
            }
            and isinstance(check.evidence, dict)
        ):
            # Full structured inventories can be thousands of characters and
            # are historical audit evidence, not image-generation instructions.
            # Keep them in the run ledger; send only a bounded failure summary.
            reasons = check.evidence.get("reasons", [])
            if not isinstance(reasons, list):
                reasons = []
            correction_evidence = {
                "failure_count": len(reasons),
                "representative_reasons": reasons[:5],
            }
        serialized_evidence = (
            json.dumps(correction_evidence, sort_keys=True)
            if correction_evidence else ""
        )
        if len(serialized_evidence) > 600:
            serialized_evidence = serialized_evidence[:599] + "…"
        evidence = (
            f" Evidence: {serialized_evidence}"
            if serialized_evidence else ""
        )
        correction_lines.append(f"- {check.code}: {check.message}.{evidence}")
    correction = "\n".join(correction_lines)
    unchanged_notice = ""
    if any(check.code in {"requested_change", "crosscheck_requested_change"}
           for check in failures):
        unchanged_notice = (
            "\nThe previous candidate did not visibly apply the requested edit. "
            "Do not return an unchanged source image. Regenerate the full image "
            "with the requested geometry visibly changed inside the edit scope, "
            "using the exact source-to-result specification delta above.\n"
        )
    prompt = (
        f"{original_prompt}\n\n"
        "TARGETED CORRECTION — CORRECT ONLY THESE OBSERVED QA FAILURES:\n"
        f"{correction}\n"
        f"{unchanged_notice}"
        "Do not compensate by changing another component. Re-apply every FROZEN "
        "constraint above. This is a correction of the same task, not a redesign."
    )
    return prompt, correction

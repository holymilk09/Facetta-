"""The edit-loop agent: natural-language change → validated new version.

The founder's JEWELRY-OS wanted one model to author the spec sheet, letter the
dimensions, and enforce tolerances by instruction — the exact failure this
whole product is built to prevent. So our agent keeps the LOOP they love and
routes each job to the engine that can be trusted with it:

  language → spec DELTA   ·  Claude (translation only, this module)
  is it physically real?  ·  the validator (density + vocabulary + fit)
  paint the piece         ·  Grok (render / blueprint)
  letter every number     ·  deterministic code (sheets / overlay)

Claude never writes a final number into the record unchallenged: whatever it
returns is re-validated with the same rules as a hand-built spec, and an
impossible ask (0.20 ct on a 4.5 × 2.25 mm marquise) is REJECTED with the
density correction rather than quietly saved. Multi-turn memory is the
immutable version chain itself — each accepted edit is a new version.
"""

from __future__ import annotations

import os
import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from facetta.prose import DEFAULT_MODEL, ProseUnavailable, system_prompt
from facetta.spec import Spec

EDIT_SYSTEM_PROMPT = """\
You are the edit planner for Facetta, a jewelry design-to-manufacturing platform.
You are given a design's CURRENT spec object (Schema v1 JSON) and one plain-language
edit instruction from the designer. Return the COMPLETE edited spec plus a short
summary of what changed.

Hard rules:
- Change ONLY what the instruction requires. Copy every other field through unchanged,
  byte for byte — same stones, counts, positions, metal, setting, everything.
- Honor every number the designer states EXPLICITLY, exactly as given, even if it looks
  physically inconsistent. Do NOT silently "fix" a contradiction — the server validates
  the result and reports any impossibility with a correction. Only derive a value the
  designer did NOT specify (e.g. if they change carat but not depth, recompute depth so
  carat ≈ length × width × depth × SG × shape_factor / 200).
- You only translate language into numbers and controlled-vocabulary values; never
  invent trade terms, species, cuts, or grades outside the vocabulary below.
- Keep the identity fields exactly as they are in the current spec — the server assigns
  the new version number and timestamps.

Also report:
- changed_fields: one short string per change, "path old → new"
  (e.g. "stone.carat 4.03 → 3.20", "stone.dimensions_mm.depth 6.3 → 5.0").
- isolate_ref: the stone-schedule letter of the stone the edit targets — "A" is the
  centre stone, "B" the first side_stones entry, "C" the second, and so on. Null if the
  edit touches metal or band rather than a specific stone.
- message: one friendly sentence for the designer describing the change.

{vocabulary}
"""


class EditResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec: Spec
    changed_fields: list[str] = Field(default_factory=list)
    isolate_ref: str | None = None
    message: str = ""


def edit_system_prompt() -> str:
    # reuse the prose layer's vocabulary digest, swap in the edit rules
    base = system_prompt()
    vocab = base[base.index("Controlled vocabulary:"):]
    return EDIT_SYSTEM_PROMPT.format(vocabulary=vocab)


def plan_edit(instruction: str, current: Spec) -> EditResult:
    """One Claude call: current spec + instruction in, edited spec + summary
    out. The result is NOT trusted — the caller re-validates it and only then
    writes a new version."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ProseUnavailable(
            "ANTHROPIC_API_KEY is not set; the edit agent needs a Claude API key")
    import anthropic

    client = anthropic.Anthropic()
    user = (
        "CURRENT SPEC:\n"
        + current.model_dump_json(indent=2)
        + "\n\nEDIT INSTRUCTION:\n" + instruction
    )
    response = client.messages.parse(
        model=os.environ.get("FACETTA_CLAUDE_MODEL", DEFAULT_MODEL),
        max_tokens=16000,
        system=edit_system_prompt(),
        messages=[{"role": "user", "content": user}],
        output_format=EditResult,
    )
    return response.parsed_output


# --- surgical annotation edits ---------------------------------------------------
#
# The designer taps a spot on the spec sheet and says "make THIS bigger." The
# agent must change that ONE element and nothing else — a promise no prompt can
# keep on its own, because a language model will happily "improve" a neighbour.
# So the guarantee is structural, not persuasive: we resolve the annotation to a
# single subtree of the spec, let the model propose a whole edited spec, then
# throw ALL of it away except that one subtree, which we graft onto an untouched
# copy of the current spec. Changing anything else is not discouraged — it is
# impossible. The validator then gates the result: if the scoped change alone is
# physically impossible, nothing is saved and the correction is reported, so the
# only way to make a broader change is to ask for it.

# where each editable subtree lives, and the schedule letter that isolates it
_SECTION_ALIASES = {
    "stone": ("stone", None), "center": ("stone", None), "centre": ("stone", None),
    "center_stone": ("stone", None), "metal": ("metal", None),
    "stone_shape": ("stone_assembly", None),
    "center_shape": ("stone_assembly", None),
    "centre_shape": ("stone_assembly", None),
    "center_cut": ("stone_assembly", None),
    "band": ("band", None), "shank": ("band", None),
    "setting": ("setting", None), "mount": ("setting", None),
    "ring_size": ("ring_size", None), "size": ("ring_size", None),
    # non-ring construction sections — scope_guard's generic branch grafts any
    # top-level subtree, so these resolve the same way band/setting do
    "drop": ("drop", None), "hook": ("drop", None), "earring": ("drop", None),
    "pendant": ("pendant", None), "bail": ("pendant", None),
    "chain": ("chain", None), "clasp": ("chain", None),
    "bracelet": ("bracelet", None), "cuff": ("bracelet", None),
    "bangle": ("bracelet", None), "brooch": ("brooch", None),
    "notes_to_factory": ("notes_to_factory", None),
    "factory_notes": ("notes_to_factory", None),
    "factory_instructions": ("notes_to_factory", None),
}
# sections that address a side_stones entry — need an index (default 0 if unique)
_SIDE_ALIASES = ("side_stones", "side_stone", "side", "halo", "melee", "surround",
                 "accent", "accents", "pave", "pavé")

_SPECIFIC_CENTER_SHAPE = (
    r"(?:marquise|oval|cushion|round|pear|princess|asscher|radiant|trillion|"
    r"emerald(?:[ _-]?cut)?)"
)
_CENTER_SHAPE_CHANGE_PATTERNS = tuple(re.compile(pattern) for pattern in (
    # The designer names the property itself: "change the center stone cut".
    r"\b(?:change|alter|modify|reshape|set)\s+"
    r"(?:(?:the|this|its)\s+)?"
    r"(?:(?:center|centre)(?:\s+stone)?\s+)?(?:stone\s+)?"
    r"(?:shape|cut|outline|silhouette)\b",
    # The designer names the center as the object and a new shape as result.
    rf"\b(?:change|switch|convert|turn|make|set|reshape)\s+"
    rf"(?:(?:the|this)\s+)?"
    rf"(?:(?:center|centre)(?:\s+stone)?|stone|it)\s+"
    rf"(?:(?:from\s+{_SPECIFIC_CENTER_SHAPE}\s+)?"
    rf"(?:to|into|as)\s+)?(?:(?:a|an)\s+)?"
    rf"{_SPECIFIC_CENTER_SHAPE}\b",
    # An explicit before -> after shape conversion.
    rf"\b(?:change|switch|convert|turn|reshape)\s+"
    rf"(?:(?:the|this)\s+)?{_SPECIFIC_CENTER_SHAPE}\s+"
    rf"(?:center(?:\s+stone)?\s+)?(?:to|into|as)\s+"
    rf"(?:(?:a|an)\s+)?{_SPECIFIC_CENTER_SHAPE}\b",
    rf"\b(?:replace|swap)\s+(?:(?:the|this)\s+)?"
    rf"{_SPECIFIC_CENTER_SHAPE}\s+(?:with|for)\s+"
    rf"(?:(?:a|an)\s+)?{_SPECIFIC_CENTER_SHAPE}\b",
    # "use a pear silhouette" is explicit even without naming the center.
    rf"\buse\s+(?:(?:a|an)\s+)?{_SPECIFIC_CENTER_SHAPE}\s+"
    rf"(?:shape|cut|outline|silhouette)\b",
    rf"\b{_SPECIFIC_CENTER_SHAPE}\s+(?:to|into|->|→)\s+"
    rf"{_SPECIFIC_CENTER_SHAPE}\b",
))


def _changes_center_shape(instruction: str) -> bool:
    """Whether prose grants authority to change the center outline/cut.

    Shape words frequently describe the current stone while the actual change
    targets color/species ("yellow on the oval stone").  Only positive shape-
    change grammar may widen a center edit into the coupled stone-and-setting
    scope.  Ambiguous mentions stay in the narrower stone scope; callers can
    remove all ambiguity by sending the explicit ``center_shape`` section.
    """
    lowered = instruction.lower()
    return any(pattern.search(lowered)
               for pattern in _CENTER_SHAPE_CHANGE_PATTERNS)


class AnnotationUnresolved(Exception):
    """The annotation does not point at exactly one editable element."""


class Annotation(BaseModel):
    """One mark the designer placed on the spec sheet: WHERE (a schedule ref
    letter, or a named section, optionally with a tap location for provenance)
    and WHAT (the plain-language change)."""

    model_config = ConfigDict(extra="forbid")

    ref: str | None = None       # stone-schedule letter: A=centre, B=first side…
    section: str | None = None   # or a named section: stone/metal/band/setting…
    index: int | None = None     # which side_stones entry, when section is a side group
    target_element_id: str | None = None  # stable design_form component ID
    view: str | None = None      # top/side/front — where the mark was placed (audit)
    x_pct: float | None = None   # normalised tap location on the sheet (audit)
    y_pct: float | None = None
    instruction: Annotated[str, Field(min_length=1, max_length=2000)]


class ScopedEditResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec: Spec
    target: str                              # human label of what was edited
    isolate_ref: str | None = None           # schedule letter to ring on the sheet
    changed_fields: list[str] = Field(default_factory=list)
    ignored_fields: list[str] = Field(default_factory=list)  # out-of-scope, discarded
    message: str = ""


def _ref_to_target(spec: Spec, ref: str) -> tuple[str, int | None]:
    letter = ref.strip().upper()
    if letter == "A":
        return ("stone", None)
    i = ord(letter) - ord("B")
    if 0 <= i < len(spec.side_stones):
        return ("side_stones", i)
    raise AnnotationUnresolved(
        f"schedule ref '{ref}' has no matching stone in this design")


ScopedTarget = tuple[str, int | str | None]


def resolve_target(spec: Spec, annotation: Annotation) -> ScopedTarget:
    """Turn an annotation into the ONE subtree path it is allowed to edit.
    Raises AnnotationUnresolved if it does not name exactly one element."""
    if annotation.ref:
        target = _ref_to_target(spec, annotation.ref)
        if target == ("stone", None) and _changes_center_shape(
                annotation.instruction):
            return ("stone_assembly", None)
        return target
    section = (annotation.section or "").strip().lower()
    if section == "design_form":
        element_id = (annotation.target_element_id or "").strip()
        if not element_id:
            raise AnnotationUnresolved(
                "a design_form annotation must name one stable target_element_id")
        if all(element.element_id != element_id
               for element in spec.design_form.elements):
            raise AnnotationUnresolved(
                f"design-form element {element_id!r} does not exist")
        return ("design_form", element_id)
    if section in _SECTION_ALIASES:
        target = _SECTION_ALIASES[section]
        if target == ("stone", None) and _changes_center_shape(
                annotation.instruction):
            return ("stone_assembly", None)
        return target
    if section in _SIDE_ALIASES:
        idx = annotation.index
        # The explicit plural names the inventory itself. This is the safe
        # scope for adding/removing a group; aliases such as halo/melee still
        # require one unambiguous existing group.
        if section == "side_stones" and idx is None:
            return ("side_stones", None)
        if idx is None:
            if len(spec.side_stones) == 1:
                idx = 0
            else:
                raise AnnotationUnresolved(
                    f"'{section}' is ambiguous — {len(spec.side_stones)} side-stone "
                    "groups; specify which with a ref letter or index")
        if not (0 <= idx < len(spec.side_stones)):
            raise AnnotationUnresolved(f"side_stones[{idx}] does not exist")
        return ("side_stones", idx)
    raise AnnotationUnresolved(
        "annotation must carry a schedule ref (A, B, …) or a known section "
        "(stone, metal, band, setting, ring_size, halo, drop, pendant, "
        "chain, bracelet, brooch, design_form, notes_to_factory)")


def _target_ref(target: ScopedTarget) -> str | None:
    kind, idx = target
    if kind in {"stone", "stone_assembly"}:
        return "A"
    if kind == "side_stones":
        return (chr(ord("B") + idx)
                if isinstance(idx, int) else None)
    return None


def _target_label(target: ScopedTarget) -> str:
    kind, idx = target
    if kind == "side_stones":
        return (f"side_stones[{idx}]" if idx is not None
                else "side_stones inventory")
    if kind == "stone_assembly":
        return "center stone shape and its setting"
    if kind == "design_form":
        return f"design form element {idx}"
    return kind


def _diff_paths(before: dict, after: dict, prefix: str) -> list[str]:
    """'path old → new' for every leaf that differs between two subtrees."""
    out: list[str] = []
    if isinstance(before, dict) and isinstance(after, dict):
        for key in dict.fromkeys([*before, *after]):
            out += _diff_paths(before.get(key), after.get(key), f"{prefix}.{key}")
    elif isinstance(before, list) and isinstance(after, list):
        for i in range(max(len(before), len(after))):
            b = before[i] if i < len(before) else None
            a = after[i] if i < len(after) else None
            out += _diff_paths(b, a, f"{prefix}[{i}]")
    elif before != after:
        out.append(f"{prefix} {before!r} → {after!r}")
    return out


def scope_guard(current: Spec, target: ScopedTarget,
                edited: Spec) -> tuple[Spec, list[str], list[str]]:
    """Reconstruct a new spec that equals `current` everywhere EXCEPT the one
    target subtree, which is taken from `edited`. Returns (guarded_spec,
    changed_fields, ignored_fields). Anything the model changed outside the
    target is discarded and reported as ignored — 'nothing else unless
    directed', enforced by construction rather than by trust."""
    base = current.model_dump(mode="json")
    ed = edited.model_dump(mode="json")
    kind, idx = target

    new = current.model_dump(mode="json")
    if kind == "design_form":
        if not isinstance(idx, str):
            raise AnnotationUnresolved(
                "design_form scope requires one stable element ID")
        from facetta.design_form import apply_scoped_form_element

        try:
            guarded_form = apply_scoped_form_element(
                current.design_form,
                edited.design_form,
                element_id=idx,
            )
        except ValueError as exc:
            raise AnnotationUnresolved(str(exc)) from exc
        new["design_form"] = guarded_form.model_dump(mode="json")
        changed = _diff_paths(
            base["design_form"], new["design_form"], "design_form")
        ignored = _diff_paths(
            {key: value for key, value in base.items()
             if key != "design_form"},
            {key: value for key, value in ed.items()
             if key != "design_form"},
            "spec",
        )
    elif kind == "side_stones":
        if idx is None:
            new["side_stones"] = ed.get("side_stones", [])
            changed = _diff_paths(
                base["side_stones"], new["side_stones"], "side_stones")
            ignored = _diff_paths(
                {k: v for k, v in base.items() if k != "side_stones"},
                {k: v for k, v in ed.items() if k != "side_stones"},
                "spec",
            )
            from facetta.dimension_provenance import (
                reconcile_side_stone_inventory_provenance,
            )

            guarded = reconcile_side_stone_inventory_provenance(
                current, Spec.model_validate(new))
            return guarded, changed, ignored
        # keep the list and its length; swap only the targeted entry
        if idx < len(ed.get("side_stones", [])):
            new["side_stones"][idx] = ed["side_stones"][idx]
        changed = _diff_paths(base["side_stones"][idx], new["side_stones"][idx],
                              f"side_stones[{idx}]")
        ignored = _diff_paths({k: v for k, v in base.items() if k != "side_stones"},
                              {k: v for k, v in ed.items() if k != "side_stones"},
                              "spec")
        # plus other side-stone entries the model may have touched
        for i in range(len(base["side_stones"])):
            if i != idx:
                ignored += _diff_paths(base["side_stones"][i],
                                       ed.get("side_stones", [None] * (i + 1))[i]
                                       if i < len(ed.get("side_stones", [])) else None,
                                       f"side_stones[{i}]")
    elif kind == "stone_assembly":
        for section in ("stone", "setting"):
            new[section] = ed.get(section)
        changed = (
            _diff_paths(base["stone"], new["stone"], "stone")
            + _diff_paths(base["setting"], new["setting"], "setting")
        )
        ignored = _diff_paths(
            {k: v for k, v in base.items()
             if k not in {"stone", "setting"}},
            {k: v for k, v in ed.items()
             if k not in {"stone", "setting"}},
            "spec",
        )
    else:
        new[kind] = ed.get(kind)
        changed = _diff_paths(base[kind], new[kind], kind)
        ignored = _diff_paths({k: v for k, v in base.items() if k != kind},
                              {k: v for k, v in ed.items() if k != kind}, "spec")

    from facetta.dimension_provenance import mark_designer_adjusted_dimensions

    guarded = Spec.model_validate(new)
    guarded = mark_designer_adjusted_dimensions(current, guarded)
    return guarded, changed, ignored


def _frame_annotation(target: ScopedTarget, instruction: str) -> str:
    """Point the planner at the one element; the scope guard enforces it anyway,
    but a focused prompt wastes fewer tokens on changes we will only discard."""
    label = _target_label(target)
    if target[0] == "design_form":
        return (
            f"Edit ONLY the confirmed_form_description for stable {label}. "
            "Keep its element_id, role, label, symmetry, instance_count, regions, "
            "visual-reference definition, every other design-form element, and "
            "every non-design-form specification field EXACTLY unchanged. Rewrite "
            "the requested target as a concise declarative description of the "
            "resulting physical form, not as an imperative.\n\n"
            f"Form change requested: {instruction}"
        )
    if target[0] == "stone_assembly":
        return (
            "Edit ONLY the center stone shape/cut and the minimum setting or "
            "prong adaptation physically required to hold that new shape. Leave "
            "all side stones, metal, band, ring size, camera-facing design facts, "
            f"and every unrelated field EXACTLY unchanged.\n\nChange requested: "
            f"{instruction}"
        )
    if target == ("side_stones", None):
        return (
            "Edit ONLY the complete side_stones inventory. You may add or remove "
            "groups/counts exactly as requested, but leave the center stone, "
            "setting, metal, band, ring size, and every other section EXACTLY "
            f"unchanged.\n\nSide-stone inventory change requested: {instruction}"
        )
    return (
        f"Edit ONLY {label} (schedule ref {_target_ref(target) or '—'}). Leave "
        "every other stone, the metal, band, setting, and ring size EXACTLY as "
        f"they are.\n\nChange requested for {label}: {instruction}"
    )


def plan_scoped_edit(annotation: Annotation, current: Spec) -> ScopedEditResult:
    """Plan a single-element edit and force it to touch nothing else. The model
    proposes a whole spec; scope_guard keeps only the annotated subtree. The
    caller still re-validates the guarded spec before saving a version."""
    target = resolve_target(current, annotation)
    proposed = plan_edit(_frame_annotation(target, annotation.instruction), current)
    guarded, changed, ignored = scope_guard(current, target, proposed.spec)
    return ScopedEditResult(
        spec=guarded, target=_target_label(target), isolate_ref=_target_ref(target),
        changed_fields=changed, ignored_fields=ignored, message=proposed.message)

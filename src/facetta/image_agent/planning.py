"""Normalize image work into a content-addressed, category-safe plan."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from facetta.image_agent.contracts import (
    DesignerEditDomain,
    ImageAgentPlan,
    ImageOperation,
    ImageRoute,
)
from facetta.image_agent.edit_semantics import classify_spec_delta
from facetta.image_agent.errors import ImagePlanValidationError
from facetta.image_agent.prompts import PROMPT_VERSIONS
from facetta.image_identity import spec_visual_hash
from facetta.json_types import JsonObject, JsonValue
from facetta.spec import Spec
from facetta.specdiff import diff_specs


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_hash(value: JsonValue) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(body.encode()).hexdigest()


def _side_inventory_contract(
    source_facts: JsonObject | None,
    target_facts: JsonObject,
) -> JsonObject:
    def inventory(facts: JsonObject | None) -> JsonObject:
        raw = facts.get("side_stones", []) if facts else []
        groups: list[JsonObject] = []
        total = 0
        if isinstance(raw, list):
            for index, item in enumerate(raw):
                if not isinstance(item, dict):
                    continue
                count = item.get("count")
                if isinstance(count, int):
                    total += count
                color = item.get("color")
                groups.append({
                    "index": index,
                    "role": item.get("position"),
                    "count": count,
                    "cut": item.get("cut"),
                    "species": item.get("species"),
                    "color": color if isinstance(color, dict) else None,
                    "dimensions_mm": item.get("dimensions_mm"),
                })
        return {"total_count": total, "groups": groups}

    source = inventory(source_facts)
    target = inventory(target_facts)
    return {
        "source": source,
        "target": target,
        "total_count_delta": (
            int(target["total_count"]) - int(source["total_count"])
        ),
    }


def _setting_topology_contract(
    source_facts: JsonObject | None,
    target_facts: JsonObject,
) -> JsonObject:
    def setting(facts: JsonObject | None) -> JsonObject:
        raw = facts.get("setting") if facts else None
        if not isinstance(raw, dict):
            return {
                "style": None,
                "prong_count": None,
                "prong_tip_mm": None,
                "gallery_height_mm": None,
            }
        return {
            "style": raw.get("style"),
            "prong_count": raw.get("prong_count"),
            "prong_tip_mm": raw.get("prong_tip_mm"),
            "gallery_height_mm": raw.get("gallery_height_mm"),
        }

    return {
        "source": setting(source_facts),
        "target": setting(target_facts),
    }


def build_image_plan(
    operation: ImageOperation | str,
    intent: str,
    *,
    spec: Spec | JsonObject | None = None,
    source_spec: Spec | JsonObject | None = None,
    source_image: bytes | None = None,
    quality_source_image: bytes | None = None,
    mask_bytes: bytes | None = None,
    mask_provenance: str | None = None,
    region_description: str | None = None,
    mounting_view: str | None = None,
    frozen: Sequence[str] = (),
    style_constraints: Sequence[str] = (),
    expected_output: str | None = None,
    variant: int = 0,
    allow_fallback: bool = True,
    drift_threshold: float = 0.18,
) -> ImageAgentPlan:
    """Build and validate the immutable plan used by every attempt.

    Provider calls receive the image bytes separately.  Only content hashes
    enter the plan so the contract is safe to log and persist.
    """

    try:
        operation = ImageOperation(operation)
    except ValueError as exc:
        raise ImagePlanValidationError(f"unsupported image operation: {operation}") from exc

    intent = intent.strip()
    if not intent:
        raise ImagePlanValidationError("image intent must not be blank")
    if variant < 0:
        raise ImagePlanValidationError("image variant must be zero or greater")
    if not 0 <= drift_threshold <= 1:
        raise ImagePlanValidationError("drift threshold must be between zero and one")

    source_required = operation in {
        ImageOperation.REFERENCE_RENDER,
        ImageOperation.LOCAL_EDIT,
        ImageOperation.VISUAL_ONLY_EDIT,
        ImageOperation.MOUNTING_VIEW_GENERATE,
    }
    if source_required and not source_image:
        raise ImagePlanValidationError(f"{operation.value} requires a source image")
    if mask_bytes and not source_image:
        raise ImagePlanValidationError("a markup mask requires a source image")
    if quality_source_image is not None and not quality_source_image:
        raise ImagePlanValidationError("a quality source must not be empty")
    if quality_source_image is not None and not source_image:
        raise ImagePlanValidationError(
            "a quality source requires a provider source image")
    if mask_provenance is not None and not mask_bytes:
        raise ImagePlanValidationError(
            "mask provenance requires actual mask bytes")
    if operation is ImageOperation.LOCAL_EDIT and not (region_description or "").strip():
        raise ImagePlanValidationError("LOCAL_EDIT requires a specific highlighted region")
    allowed_mounting_views = {"plan", "front", "side", "section"}
    normalized_mounting_view = (
        mounting_view.strip().lower() if isinstance(mounting_view, str) else None
    )
    if operation is ImageOperation.MOUNTING_VIEW_GENERATE:
        if normalized_mounting_view not in allowed_mounting_views:
            raise ImagePlanValidationError(
                "MOUNTING_VIEW_GENERATE requires plan, front, side, or section"
            )
    elif normalized_mounting_view is not None:
        raise ImagePlanValidationError(
            "mounting_view is only valid for MOUNTING_VIEW_GENERATE"
        )

    requires_spec = operation not in {
        ImageOperation.CREATIVE_GENERATE,
        ImageOperation.CONCEPT_GENERATE,
        ImageOperation.REFERENCE_RENDER,
    }
    parsed_spec: Spec | None = None
    if spec is not None:
        try:
            parsed_spec = spec if isinstance(spec, Spec) else Spec.model_validate(spec)
        except Exception as exc:
            raise ImagePlanValidationError(f"invalid specification for image work: {exc}") from exc
        if parsed_spec.jewelry_type not in {"ring", "necklace"}:
            raise ImagePlanValidationError(
                "the trusted image-agent slice currently supports rings only")
        if (operation is ImageOperation.MOUNTING_VIEW_GENERATE
                and parsed_spec.jewelry_type != "ring"):
            raise ImagePlanValidationError(
                "mounting-view generation currently supports rings only")
    if requires_spec and parsed_spec is None:
        raise ImagePlanValidationError(f"{operation.value} requires a validated ring spec")
    if (operation in {ImageOperation.CREATIVE_GENERATE,
                      ImageOperation.CONCEPT_GENERATE,
                      ImageOperation.REFERENCE_RENDER}
            and parsed_spec is not None):
        raise ImagePlanValidationError(
            f"{operation.value} is pre-spec work; use SPEC_RENDER for a validated spec")

    parsed_source_spec: Spec | None = None
    if source_spec is not None:
        try:
            parsed_source_spec = (source_spec if isinstance(source_spec, Spec)
                                  else Spec.model_validate(source_spec))
        except Exception as exc:
            raise ImagePlanValidationError(
                f"invalid source specification for image work: {exc}") from exc
        if parsed_source_spec.jewelry_type not in {"ring", "necklace"}:
            raise ImagePlanValidationError(
                "the trusted image-agent slice currently supports rings only")
    if parsed_source_spec is not None and parsed_spec is None:
        raise ImagePlanValidationError(
            "a source specification requires a validated result specification")
    if (parsed_source_spec is not None and parsed_spec is not None
            and operation not in {ImageOperation.LOCAL_EDIT,
                                  ImageOperation.VISUAL_ONLY_EDIT}):
        raise ImagePlanValidationError(
            "source_spec is only valid for localized or visual-only edits")
    if (parsed_source_spec is not None and parsed_spec is not None
            and parsed_source_spec.jewelry_type != parsed_spec.jewelry_type):
        raise ImagePlanValidationError(
            "source and result specifications must use the same jewelry type")

    facts = (parsed_spec.model_dump(mode="json") if parsed_spec else
             {"jewelry_type": (
                 "jewelry" if operation in {
                     ImageOperation.CREATIVE_GENERATE,
                     ImageOperation.REFERENCE_RENDER,
                 }
                 else "ring")})
    # Coverage/audit evidence governs whether work may proceed, but it is not
    # a visual generation instruction and can contain hashes/reviewer prose.
    # The exact mapped spec and design-form facts remain below.
    facts.pop("source_component_coverage", None)
    source_facts = (parsed_source_spec.model_dump(mode="json")
                    if parsed_source_spec else None)
    if source_facts is not None:
        source_facts.pop("source_component_coverage", None)
    source_visual_hash = (spec_visual_hash(parsed_source_spec)
                          if parsed_source_spec else None)
    spec_delta = (diff_specs(source_facts, facts)
                  if source_facts is not None else [])
    jewelry_type = (parsed_spec.jewelry_type if parsed_spec else
                    ("jewelry" if operation in {
                        ImageOperation.CREATIVE_GENERATE,
                        ImageOperation.REFERENCE_RENDER,
                    }
                     else "ring"))
    if jewelry_type == "necklace":
        if operation is not ImageOperation.LOCAL_EDIT:
            raise ImagePlanValidationError(
                "necklace image-agent support is limited to chain.style LOCAL_EDIT")
        if parsed_source_spec is None:
            raise ImagePlanValidationError(
                "necklace chain.style LOCAL_EDIT requires a source specification")
        if parsed_spec.chain is None or parsed_source_spec.chain is None:
            raise ImagePlanValidationError(
                "necklace chain.style LOCAL_EDIT requires source and result chain facts")
        changed_paths = {
            str(change.get("path"))
            for change in spec_delta
            if isinstance(change, dict)
        }
        allowed = all(
            path == "chain.style"
            or path.startswith("chain.geometry")
            or path.startswith("chain.production")
            for path in changed_paths
        )
        if "chain.style" not in changed_paths or not allowed:
            raise ImagePlanValidationError(
                "necklace image-agent support requires a chain.style target "
                "with only chain geometry/production companion deltas")
        # Procurement/CAD references are authoritative persistence facts, not
        # image instructions or cache inputs. Keep their structural presence
        # in the allowlist above, then remove them from the visual plan.
        spec_delta = [
            change for change in spec_delta
            if not str(change.get("path", "")).startswith("chain.production")
        ]
        for payload in (facts, source_facts):
            if not isinstance(payload, dict):
                continue
            chain_facts = payload.get("chain")
            if isinstance(chain_facts, dict):
                chain_facts.pop("production", None)
    edit_domains = (classify_spec_delta(spec_delta)
                    if operation is ImageOperation.LOCAL_EDIT else ())
    if (jewelry_type == "necklace"
            and edit_domains != (DesignerEditDomain.CHAIN_STYLE,)):
        raise ImagePlanValidationError(
            "necklace image-agent support requires a chain-style visual delta")
    visual_hash = (spec_visual_hash(parsed_spec) if parsed_spec else
                   _canonical_hash(facts)[:16])
    source_hash = _hash_bytes(source_image) if source_image else None
    quality_source_hash = (
        _hash_bytes(quality_source_image) if quality_source_image else None
    )
    mask_hash = _hash_bytes(mask_bytes) if mask_bytes else None
    region = (region_description or "").strip() or None

    default_frozen = {
        ImageOperation.CREATIVE_GENERATE: (
            "one coherent fine-jewelry design that follows the designer direction",
            "no text, logos, watermarks, signatures, or invented branding",
        ),
        ImageOperation.CONCEPT_GENERATE: (
            "one coherent ring design",
            "no text, logos, watermarks, or invented branding",
        ),
        ImageOperation.REFERENCE_RENDER: (
            "the source's visible design identity, silhouette, component count, "
            "relative proportions, stone placement, and distinctive motifs",
            "no unrequested stones, components, engraving, text, logos, "
            "watermarks, signatures, or invented branding",
        ),
        ImageOperation.SPEC_RENDER: (
            "every validated stone, setting, metal, and component fact",
            "no text, logos, watermarks, or invented branding",
        ),
        ImageOperation.LOCAL_EDIT: (
            f"all pixels and jewelry structure outside {region}",
            "all validated facts not named by the requested change",
        ),
        ImageOperation.VISUAL_ONLY_EDIT: (
            "all jewelry geometry, stones, setting, proportions, and metal identity",
            "the complete validated specification",
        ),
        ImageOperation.MOUNTING_VIEW_GENERATE: (
            "the approved source design identity and every source-visible component",
            "the validated center-stone outline, setting, prong topology, side-stone inventory, metal, shoulders, and shank",
            "no text, dimensions, arrows, labels, logos, watermarks, or generic stock mounting",
        ),
    }[operation]
    if jewelry_type == "necklace":
        default_frozen = (
            "the exact pendant count and the complete pendant design and geometry",
            "the bail geometry and both chain-to-bail connection positions",
            "every gemstone identity, count, cut, color, scale, position, and setting",
            "the clasp type, clasp geometry, and clasp position",
            "the chain length, endpoints, overall drape, and placement",
            "the validated metal identity and finish",
            "all non-chain jewelry geometry",
            "no text, logos, watermarks, or invented branding",
        )
    if operation is ImageOperation.SPEC_RENDER and source_image is not None:
        default_frozen = (*default_frozen,
                          "the source concept's unique design identity, major "
                          "proportions, and component arrangement")
    frozen_values = tuple(dict.fromkeys(
        item.strip() for item in (*default_frozen, *frozen) if item.strip()))
    style_values = tuple(item.strip() for item in style_constraints if item.strip())
    expected = expected_output or {
        ImageOperation.CREATIVE_GENERATE: (
            "one polished, client-reviewable jewelry concept image faithful "
            "to the designer direction"
        ),
        ImageOperation.CONCEPT_GENERATE: "one client-reviewable ring concept image",
        ImageOperation.REFERENCE_RENDER: (
            "one polished, client-reviewable jewelry render faithful to the "
            "visible source design"
        ),
        ImageOperation.SPEC_RENDER: "one photorealistic image faithful to the validated spec",
        ImageOperation.LOCAL_EDIT: "the requested local change and no unrelated redesign",
        ImageOperation.VISUAL_ONLY_EDIT: "only the requested presentation change",
        ImageOperation.MOUNTING_VIEW_GENERATE: (
            f"one complete isolated {normalized_mounting_view} mounting view "
            "for explicit designer review"
        ),
    }[operation]
    if jewelry_type == "necklace" and expected_output is None:
        expected = (
            "one necklace image with the selected chain style applied to the "
            "complete visible chain-link run and no other visible change"
        )
    normalized_intent = {
        "instruction": intent,
        "region_description": region,
        "frozen": list(frozen_values),
        "style_constraints": list(style_values),
        "expected_output": expected,
        "spec_delta": spec_delta,
        "edit_domains": [domain.value for domain in edit_domains],
    }
    if quality_source_hash is not None:
        normalized_intent["quality_source"] = {
            "sha256": quality_source_hash,
            "authority": "source_preflight_and_candidate_fidelity",
            "provider_source_sha256": source_hash,
        }
    if normalized_mounting_view is not None:
        normalized_intent["requested_projections"] = [normalized_mounting_view]
        normalized_intent["mounting_hardware"] = {
            "required_views": [normalized_mounting_view],
            "authority": "factory_discussion_only",
            "designer_confirmation_required": True,
            "production_authority": False,
        }
    if DesignerEditDomain.SIDE_STONE_INVENTORY in edit_domains:
        normalized_intent["side_stone_inventory_contract"] = (
            _side_inventory_contract(source_facts, facts)
        )
    if DesignerEditDomain.SETTING in edit_domains:
        normalized_intent["setting_topology_contract"] = (
            _setting_topology_contract(source_facts, facts)
        )
    if mask_hash is not None:
        normalized_intent["localization"] = {
            "mode": (mask_provenance or "caller_supplied_mask"),
            "mask_hash": mask_hash,
        }
    hash_input = {
        "operation": operation.value,
        "prompt_version": PROMPT_VERSIONS[operation],
        "normalized_intent": normalized_intent,
        "source_hash": source_hash,
        "quality_source_hash": quality_source_hash,
        "mask_hash": mask_hash,
        "spec_visual_hash": visual_hash,
        "source_spec_visual_hash": source_visual_hash,
        "variant": variant,
    }
    return ImageAgentPlan(
        operation=operation,
        jewelry_type=jewelry_type,
        intent=intent,
        normalized_intent=normalized_intent,
        edit_domains=edit_domains,
        prompt_version=PROMPT_VERSIONS[operation],
        spec_facts=facts,
        source_spec_facts=source_facts,
        source_spec_visual_hash=source_visual_hash,
        source_hash=source_hash,
        quality_source_hash=quality_source_hash,
        mask_hash=mask_hash,
        spec_visual_hash=visual_hash,
        region_description=region,
        mounting_view=normalized_mounting_view,
        frozen=frozen_values,
        style_constraints=style_values,
        expected_output=expected,
        variant=variant,
        fallback_allowed=allow_fallback,
        drift_threshold=drift_threshold,
        input_hash=_canonical_hash(hash_input),
    )


def route_for_attempt(plan: ImageAgentPlan, number: int) -> ImageRoute | None:
    """Return the route for attempt 1..3, or ``None`` when fallback is unsafe."""

    editing = plan.operation in {
        ImageOperation.REFERENCE_RENDER,
        ImageOperation.LOCAL_EDIT,
        ImageOperation.VISUAL_ONLY_EDIT,
        ImageOperation.MOUNTING_VIEW_GENERATE,
    } or (plan.operation is ImageOperation.SPEC_RENDER
          and plan.source_hash is not None)
    if number in (1, 2):
        return ImageRoute.GROK_EDIT if editing else ImageRoute.GROK_GENERATE
    if number == 3 and plan.fallback_allowed:
        return (ImageRoute.FLUX_KONTEXT_EDIT if editing
                else ImageRoute.FLUX_GENERATE)
    return None


def bind_localization_mask(
    plan: ImageAgentPlan,
    mask_bytes: bytes,
    *,
    provenance: str,
    evidence: JsonObject,
) -> ImageAgentPlan:
    """Bind a deterministic mask and its audit provenance to an existing plan."""

    mask_hash = _hash_bytes(mask_bytes)
    localization: JsonObject = {
        "mode": provenance,
        "mask_hash": mask_hash,
        "evidence": evidence,
    }
    normalized = {
        **plan.normalized_intent,
        "localization": localization,
    }
    hash_input = {
        "operation": plan.operation.value,
        "prompt_version": plan.prompt_version,
        "normalized_intent": normalized,
        "source_hash": plan.source_hash,
        "quality_source_hash": plan.quality_source_hash,
        "mask_hash": mask_hash,
        "spec_visual_hash": plan.spec_visual_hash,
        "source_spec_visual_hash": plan.source_spec_visual_hash,
        "variant": plan.variant,
    }
    return plan.model_copy(update={
        "normalized_intent": normalized,
        "mask_hash": mask_hash,
        "input_hash": _canonical_hash(hash_input),
    })


def attempt_cache_key(
    plan: ImageAgentPlan, route: ImageRoute, prompt: str, model: str,
) -> str:
    return _canonical_hash({
        "input_hash": plan.input_hash,
        "route": route.value,
        "model": model,
        "prompt": prompt,
        "source_spec_visual_hash": plan.source_spec_visual_hash,
    })

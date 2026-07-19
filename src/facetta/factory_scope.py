"""Released category scope for optional Factory review.

This module owns product release scope, not schema readability.  Specifications
for other jewelry categories remain valid and historical projects remain
readable, but only categories listed here may become Factory-eligible or create
a new review pack.
"""

from __future__ import annotations

from dataclasses import dataclass

from facetta.spec import Spec


RELEASED_FACTORY_JEWELRY_TYPES = frozenset({"ring"})

# Factory release is narrower than schema/readability support.  These are the
# ring topologies for which the deterministic review-sheet renderer currently
# has an explicit implementation.  Keep unsupported specifications readable
# and editable in Studio, but do not invite a designer into Factory readiness
# for a topology that can only fail when the final pack is assembled.
RELEASED_FACTORY_RING_TEMPLATES = frozenset({
    "solitaire_prong",
    "halo_prong",
    "leaf_shoulder_prong",
})


@dataclass(frozen=True, slots=True)
class FactoryCategoryBlocker:
    code: str
    subject_id: str
    role: str
    label: str
    message: str
    required_resolution: str


def factory_category_blockers(
    spec: Spec,
) -> tuple[FactoryCategoryBlocker, ...]:
    """Return a release blocker without rejecting or rewriting the spec."""

    if spec.jewelry_type in RELEASED_FACTORY_JEWELRY_TYPES:
        return ()
    return (FactoryCategoryBlocker(
        code="factory_category_not_released",
        subject_id=spec.jewelry_type,
        role="factory_release_scope",
        label=f"{spec.jewelry_type.replace('_', ' ').title()} Factory review",
        message=(
            "Factory review is currently released for rings only. This "
            f"{spec.jewelry_type.replace('_', ' ')} remains fully available "
            "in Studio, Collections, Client, and Marketing, but it cannot be "
            "prepared as Factory review material yet."
        ),
        required_resolution=(
            "Keep the design and its immutable history in Studio; wait for a "
            "category-specific Factory workflow to be released."
        ),
    ),)


def factory_template_blockers(
    spec: Spec,
) -> tuple[FactoryCategoryBlocker, ...]:
    """Block Factory review when no exact topology renderer is released.

    Validation intentionally accepts additional templates so historical and
    future designs remain readable.  Factory eligibility must be stricter:
    unsupported topology cannot be represented by a different generic sheet.
    """

    if spec.jewelry_type != "ring":
        return ()
    if spec.template in RELEASED_FACTORY_RING_TEMPLATES:
        return ()
    label = spec.template.replace("_", " ")
    return (FactoryCategoryBlocker(
        code="factory_template_not_released",
        subject_id=spec.template,
        role="factory_template_scope",
        label=f"{label.title()} Factory review",
        message=(
            "Factory review does not yet support this "
            f"{label} ring topology. The exact revision remains available in "
            "Studio, Collections, Client, and Marketing, but Facetta will not "
            "substitute a generic or different ring drawing for Factory review."
        ),
        required_resolution=(
            "Keep the exact revision and its immutable history in Studio; wait "
            "for a topology-specific Factory review renderer to be released."
        ),
    ),)

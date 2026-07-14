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

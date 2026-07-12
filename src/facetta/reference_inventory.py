"""Advisory inventory contracts for founder-supplied design references.

This module deliberately classifies *workflow fit*, not jewelry truth.  A
contact-sheet read may help Facetta choose a varied evaluation sample, but it
must never author a specification, a measurement, or an approval decision.
"""

from __future__ import annotations

from collections import Counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ReferenceCategory = Literal[
    "ring",
    "earrings",
    "necklace",
    "pendant",
    "brooch",
    "bracelet",
    "loose_stone",
    "reference_chart",
    "mixed",
    "unknown",
]
ReferenceInputKind = Literal[
    "hand_drawing",
    "line_art",
    "colored_design_plate",
    "finished_jewelry_photo",
    "inspiration_product_composite",
    "technical_sheet",
    "reference_chart",
    "mixed",
    "unknown",
]
ReferenceWorkflow = Literal[
    "plate_read",
    "photo_read",
    "lineart_color",
    "beauty_render",
    "localized_edit",
    "product_photography",
    "factory_sheet",
    "catalog_reference",
    "reference_chart",
    "technical_benchmark",
    "exclude_as_source",
]


class ReferenceInventoryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(pattern=r"^image-(?:[1-9]|[1-9][0-9]|1[0-3][0-9]|14[0-4])\.jpg$")
    primary_category: ReferenceCategory
    input_kind: ReferenceInputKind
    workflow_fit: tuple[ReferenceWorkflow, ...]
    multi_design: bool
    watermark_or_branding: bool
    complexity: Literal["simple", "moderate", "complex"]
    confidence: float = Field(ge=0, le=1)
    notes: str = Field(min_length=1, max_length=240)


class ReferenceInventoryPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: tuple[ReferenceInventoryItem, ...]


def validate_inventory_page(
    expected_filenames: tuple[str, ...],
    payload: object,
) -> ReferenceInventoryPage:
    """Validate one vision page and prove every requested tile appears once."""

    page = ReferenceInventoryPage.model_validate(payload)
    observed = tuple(item.filename for item in page.items)
    duplicates = sorted(
        filename for filename, count in Counter(observed).items() if count > 1
    )
    missing = sorted(set(expected_filenames) - set(observed))
    unexpected = sorted(set(observed) - set(expected_filenames))
    if duplicates or missing or unexpected or len(observed) != len(expected_filenames):
        raise ValueError(
            "inventory page does not exactly cover its source tiles: "
            f"duplicates={duplicates}, missing={missing}, unexpected={unexpected}"
        )
    by_filename = {item.filename: item for item in page.items}
    return ReferenceInventoryPage(
        items=tuple(by_filename[filename] for filename in expected_filenames)
    )


def summarize_reference_inventory(
    items: tuple[ReferenceInventoryItem, ...],
) -> dict[str, object]:
    """Return deterministic counts without upgrading advisory labels to truth."""

    return {
        "item_count": len(items),
        "category_counts": dict(sorted(Counter(
            item.primary_category for item in items
        ).items())),
        "input_kind_counts": dict(sorted(Counter(
            item.input_kind for item in items
        ).items())),
        "complexity_counts": dict(sorted(Counter(
            item.complexity for item in items
        ).items())),
        "multi_design_count": sum(item.multi_design for item in items),
        "watermark_or_branding_count": sum(
            item.watermark_or_branding for item in items
        ),
        "low_confidence_count": sum(item.confidence < 0.65 for item in items),
        "workflow_counts": dict(sorted(Counter(
            workflow for item in items for workflow in item.workflow_fit
        ).items())),
        "advisory_only": True,
    }

from __future__ import annotations

import pytest

from facetta.reference_inventory import (
    ReferenceInventoryItem,
    summarize_reference_inventory,
    validate_inventory_page,
)


def _item(filename: str, **overrides) -> dict:
    value = {
        "filename": filename,
        "primary_category": "ring",
        "input_kind": "colored_design_plate",
        "workflow_fit": ["plate_read", "beauty_render"],
        "multi_design": False,
        "watermark_or_branding": True,
        "complexity": "moderate",
        "confidence": 0.9,
        "notes": "one ring in several views",
    }
    value.update(overrides)
    return value


def test_inventory_page_restores_source_order_and_requires_exact_coverage():
    page = validate_inventory_page(
        ("image-1.jpg", "image-2.jpg"),
        {"items": [_item("image-2.jpg"), _item("image-1.jpg")]},
    )
    assert [item.filename for item in page.items] == [
        "image-1.jpg", "image-2.jpg",
    ]

    with pytest.raises(ValueError, match=r"missing=\['image-2.jpg'\]"):
        validate_inventory_page(
            ("image-1.jpg", "image-2.jpg"),
            {"items": [_item("image-1.jpg")]},
        )
    with pytest.raises(ValueError, match=r"duplicates=\['image-1.jpg'\]"):
        validate_inventory_page(
            ("image-1.jpg",),
            {"items": [_item("image-1.jpg"), _item("image-1.jpg")]},
        )


def test_inventory_contract_rejects_spec_or_measurement_shaped_extras():
    with pytest.raises(ValueError):
        validate_inventory_page(
            ("image-1.jpg",),
            {"items": [{**_item("image-1.jpg"), "estimated_width_mm": 8.0}]},
        )


def test_inventory_summary_is_advisory_and_counts_workflow_breadth():
    items = (
        ReferenceInventoryItem.model_validate(_item("image-1.jpg")),
        ReferenceInventoryItem.model_validate(_item(
            "image-2.jpg",
            primary_category="reference_chart",
            input_kind="reference_chart",
            workflow_fit=["catalog_reference", "exclude_as_source"],
            multi_design=True,
            watermark_or_branding=False,
            complexity="simple",
            confidence=0.5,
        )),
    )
    summary = summarize_reference_inventory(items)
    assert summary["item_count"] == 2
    assert summary["category_counts"] == {"reference_chart": 1, "ring": 1}
    assert summary["workflow_counts"]["beauty_render"] == 1
    assert summary["multi_design_count"] == 1
    assert summary["low_confidence_count"] == 1
    assert summary["advisory_only"] is True

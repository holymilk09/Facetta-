"""Dense factory schedules continue onto deterministic, untruncated pages."""

from __future__ import annotations

import copy
import math

from conftest import HALO_SPEC

from facetta.factory_schedule_pages import (
    ROWS_PER_PAGE,
    factory_schedule_row_count,
    render_factory_schedule_pages,
)
from facetta.factory_sheet_plan import build_factory_sheet_fact_plan
from facetta.spec import Spec


def _dense_plan():
    raw = copy.deepcopy(HALO_SPEC)
    raw["side_stones"] = [
        copy.deepcopy(HALO_SPEC["side_stones"][0])
        for _ in range(8)
    ]
    raw["dimension_provenance"] = {
        "side_stones[7].dimensions_mm.width": {
            "status": "estimated_from_reference",
            "method": "reference_vision",
            "source": "designer reference image",
            "confidence": 0.4,
        },
    }
    return build_factory_sheet_fact_plan(
        Spec.model_validate(raw),
        confirmed_sections={
            "stone", "side_stones", "setting", "metal", "band", "ring_size",
        },
    )


def test_dense_schedule_uses_numbered_continuation_pages_without_truncation():
    plan = _dense_plan()
    pages = render_factory_schedule_pages(plan)
    expected = math.ceil(factory_schedule_row_count(plan) / ROWS_PER_PAGE)
    assert len(pages) == expected
    assert all(
        f"PAGE {index} / {expected}" in page
        for index, page in enumerate(pages, start=1)
    )
    combined = "".join(pages)
    assert "↳" not in combined
    assert "&gt;" in combined
    for dimension in plan.dimensions:
        assert combined.count(dimension.field_path) == 1
    for stone in plan.stones:
        assert combined.count(f"{stone.ref} · {stone.role}") == 1


def test_estimates_remain_visibly_labeled_on_their_actual_page():
    pages = render_factory_schedule_pages(_dense_plan())
    containing = next(page for page in pages
                      if "side_stones[7].dimensions_mm.width" in page)
    assert 'data-status="estimated_from_reference"' in containing
    assert "EST." in containing
    assert "designer reference image" in containing
    assert "not measurements" in containing


def test_schedule_pages_are_byte_stable_and_capacity_is_configurable():
    plan = _dense_plan()
    first = render_factory_schedule_pages(plan, rows_per_page=10)
    second = render_factory_schedule_pages(plan, rows_per_page=10)
    assert first == second
    expected = math.ceil(factory_schedule_row_count(plan) / 10)
    assert len(first) == expected
    assert f"PAGE {expected} / {expected}" in first[-1]


def test_empty_or_invalid_page_capacity_never_silently_drops_rows():
    plan = _dense_plan()
    try:
        render_factory_schedule_pages(plan, rows_per_page=0)
    except ValueError as exc:
        assert "positive" in str(exc)
    else:  # pragma: no cover - safety assertion
        raise AssertionError("invalid schedule capacity was accepted")

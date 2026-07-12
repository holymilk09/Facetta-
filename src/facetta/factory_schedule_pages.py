"""Deterministic continuation pages for dense factory fact schedules."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

from facetta.factory_sheet_plan import FactorySheetFactPlan, FactStatus
from facetta.svg_sheet import FONT, INK, MARGIN, PAPER, SHEET_H, SHEET_W


ROWS_PER_PAGE = 18


@dataclass(frozen=True)
class _ScheduleRow:
    section: str
    item: str
    fact: str
    status: FactStatus
    source: str = ""


def _status_label(status: FactStatus) -> str:
    return {
        "designer_confirmed": "CONFIRMED",
        "estimated_from_reference": "EST.",
        "pending_confirmation": "PENDING",
    }[status]


def _clip(value: str, length: int) -> str:
    cleaned = " ".join(value.split())
    return cleaned if len(cleaned) <= length else cleaned[:length - 1].rstrip() + "…"


def _wrap(value: str, width: int, lines: int) -> tuple[str, ...]:
    words = " ".join(value.split()).split()
    rows: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= width:
            current = candidate
        elif len(rows) < lines - 1:
            rows.append(current)
            current = word
        else:
            current = _clip(candidate, width)
            break
    if current:
        rows.append(current)
    return tuple(rows[:lines])


def _rows(plan: FactorySheetFactPlan) -> list[_ScheduleRow]:
    rows: list[_ScheduleRow] = []
    for material in plan.materials:
        karat = f"{material.karat}k " if material.karat is not None else ""
        color = f"{material.color} " if material.color else ""
        finish = f" · {material.finish.replace('_', ' ')}" if material.finish else ""
        rows.append(_ScheduleRow(
            "MATERIAL", "Metal",
            f"{karat}{color}{material.material}{finish}",
            material.fact_status,
        ))
    for stone in plan.stones:
        color = f" · {stone.visible_color}" if stone.visible_color else ""
        rows.append(_ScheduleRow(
            "STONE", f"{stone.ref} · {stone.role}",
            (f"{stone.count} × {stone.species} · {stone.cut.replace('_', ' ')}"
             f"{color} · {stone.carat_each:g} ct ea · {stone.carat_total:g} ct total"),
            stone.fact_status,
        ))
    for setting in plan.settings:
        prongs = f" · {setting.prong_count} prongs" if setting.prong_count else ""
        rows.append(_ScheduleRow(
            "SETTING", "Primary",
            setting.style.replace("_", " ") + prongs,
            setting.fact_status,
        ))
    for fact in plan.recorded_facts:
        rows.append(_ScheduleRow(
            "FACT",
            fact.field_path,
            f"{fact.label}: {fact.value}",
            fact.fact_status,
        ))
    for dimension in plan.dimensions:
        recorded_value = (
            f"{dimension.unit} {dimension.value:g}"
            if dimension.field_path == "ring_size.value"
            else f"{dimension.value:g} {dimension.unit}"
        )
        rows.append(_ScheduleRow(
            "DIMENSION",
            dimension.field_path,
            recorded_value,
            dimension.status,
            dimension.source or "",
        ))
    expanded: list[_ScheduleRow] = []
    for row in rows:
        fact_parts = _split_visible(row.fact, 72)
        source_parts = _split_visible(row.source, 28)
        part_count = max(len(fact_parts), len(source_parts))
        for index in range(part_count):
            expanded.append(_ScheduleRow(
                row.section if index == 0 else "↳",
                row.item if index == 0 else "continued",
                fact_parts[index] if index < len(fact_parts) else "",
                row.status,
                source_parts[index] if index < len(source_parts) else "",
            ))
    return expanded


def _split_visible(value: str, width: int) -> tuple[str, ...]:
    """Split long text over physical rows without ellipsis or hidden facts."""
    cleaned = " ".join(value.split())
    if not cleaned:
        return ("",)
    parts: list[str] = []
    remaining = cleaned
    while len(remaining) > width:
        boundary = remaining.rfind(" ", 0, width + 1)
        if boundary <= 0:
            boundary = width
        parts.append(remaining[:boundary])
        remaining = remaining[boundary:].lstrip()
    parts.append(remaining)
    return tuple(parts)


def _text(x: float, y: float, value: str, *, size: float = 3.0,
          anchor: str = "start", weight: str = "normal",
          fit_width: float | None = None, fit_chars: int | None = None) -> str:
    fit = (
        f' textLength="{fit_width:.2f}" lengthAdjust="spacingAndGlyphs"'
        if fit_width is not None and fit_chars is not None
        and len(value) > fit_chars else ""
    )
    return (
        f'<text x="{x:.2f}" y="{y:.2f}" font-family="{FONT}" '
        f'font-size="{size:.2f}" font-weight="{weight}" fill="{INK}" '
        f'text-anchor="{anchor}"{fit}>{escape(value)}</text>'
    )


def _render_page(
    plan: FactorySheetFactPlan,
    rows: list[_ScheduleRow],
    *,
    page: int,
    page_count: int,
) -> str:
    x_section, x_item, x_fact, x_status, x_source = 13, 43, 102, 225, 247
    top = 31.0
    row_height = 8.25
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SHEET_W:g} {SHEET_H:g}" '
        f'width="{SHEET_W:g}mm" height="{SHEET_H:g}mm">',
        f'<rect width="{SHEET_W:g}" height="{SHEET_H:g}" fill="{PAPER}"/>',
        f'<rect x="{MARGIN:g}" y="{MARGIN:g}" width="{SHEET_W - 2*MARGIN:g}" '
        f'height="{SHEET_H - 2*MARGIN:g}" fill="none" stroke="{INK}" stroke-width="0.3"/>',
        _text(MARGIN + 5, 17, "FACETTA FACTORY FACT SCHEDULE", size=4.6, weight="bold"),
        _text(SHEET_W - MARGIN - 5, 17, f"PAGE {page} / {page_count}",
              size=3.2, anchor="end"),
        _text(MARGIN + 5, 23,
              f"{plan.jewelry_type.upper()} · {plan.template.replace('_', ' ').upper()}",
              size=3.1),
        '<line x1="11" y1="27" x2="286" y2="27" '
        f'stroke="{INK}" stroke-width="0.25"/>',
        _text(x_section, top, "SECTION", size=2.6, weight="bold"),
        _text(x_item, top, "ITEM / FIELD", size=2.6, weight="bold"),
        _text(x_fact, top, "RECORDED FACT", size=2.6, weight="bold"),
        _text(x_status, top, "STATUS", size=2.6, weight="bold"),
        _text(x_source, top, "SOURCE", size=2.6, weight="bold"),
    ]
    for index, row in enumerate(rows, start=1):
        y = top + index * row_height
        parts.extend([
            f'<g data-status="{row.status}">',
            f'<line x1="11" y1="{y - 4.8:.2f}" x2="286" y2="{y - 4.8:.2f}" '
            'stroke="#b0b0b0" stroke-width="0.12"/>',
            _text(x_section, y, row.section, size=2.55),
            _text(x_item, y, row.item, size=2.65,
                  fit_width=54.0, fit_chars=38),
            _text(x_fact, y, row.fact, size=2.65),
            _text(x_status, y, _status_label(row.status), size=2.65,
                  weight="bold"),
            _text(x_source, y, row.source, size=2.45),
            '</g>',
        ])
    footer = (
        plan.estimate_disclaimer
        or "All recorded facts require the exact approved specification and revision."
    )
    footer_lines = _wrap(footer, 145, 2)
    parts.extend([
        *(
            _text(MARGIN + 5, SHEET_H - 14 + index * 3.0, line, size=2.25)
            for index, line in enumerate(footer_lines)
        ),
        _text(SHEET_W - MARGIN - 5, SHEET_H - 5,
              "FACETTA · DETERMINISTIC SPEC-DERIVED RECORD",
              size=2.15, anchor="end"),
        '</svg>',
    ])
    return "".join(parts)


def render_factory_schedule_pages(
    plan: FactorySheetFactPlan,
    *,
    rows_per_page: int = ROWS_PER_PAGE,
) -> tuple[str, ...]:
    """Render one or more A4 continuation pages without truncating facts."""
    if rows_per_page < 1:
        raise ValueError("rows_per_page must be positive")
    rows = _rows(plan)
    chunks = [rows[index:index + rows_per_page]
              for index in range(0, len(rows), rows_per_page)] or [[]]
    return tuple(
        _render_page(
            plan, chunk, page=index, page_count=len(chunks))
        for index, chunk in enumerate(chunks, start=1)
    )


def factory_schedule_row_count(plan: FactorySheetFactPlan) -> int:
    """Number of visible physical rows after lossless text continuation."""
    return len(_rows(plan))

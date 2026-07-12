"""The tap-to-approve checklist: facts from the record, one YES/NO each.

Before a version goes to factory the designer confirms the piece aspect by
aspect — the WHOOP-journal ritual: YES approves the fact, NO requires the
change note that flows straight into the edit loop. Items are derived from
WHICH SPEC SECTIONS ARE PRESENT, so the checklist is jewelry-type aware by
construction: a ring asks about its band and ring size, a drop earring about
its hook and drop length, a necklace about its chain — never a question that
doesn't apply. Every item carries the section/ref an agent edit resolves to
(agent.resolve_target), so a NO is executable by design, not by luck.

Pure code over the validated spec — no providers, no drawing imports.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from facetta.dimension_provenance import estimate_marker
from facetta.spec import (
    OpenLinkChainGeometry,
    SmoothChainGeometry,
    Spec,
    Stone,
    StrandedChainGeometry,
)

MODES = ("auto_pin", "explicit_pin", "optional")
DEFAULT_MODE = "auto_pin"


class ChecklistItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str            # stable id: "stone", "side_stones[0]", "band", ...
    ref: str | None     # stone-schedule letter (stones only) → Annotation.ref
    section: str        # agent-resolvable section name → Annotation.section
    index: int | None   # side_stones index, when the section is one
    target_element_id: str | None = None  # stable design-form component
    label: str          # "Center stone", "Band", "Chain & clasp"
    fact: str           # one-line FACT from the record
    question: str       # the tap copy


def _fmt(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _fmt_chain(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _dims(spec: Spec, stone: Stone, prefix: str) -> str:
    d = stone.dimensions_mm
    marker = estimate_marker(
        spec,
        f"{prefix}.dimensions_mm.length",
        f"{prefix}.dimensions_mm.width",
        f"{prefix}.dimensions_mm.depth",
    )
    return f"{_fmt(d.length)} × {_fmt(d.width)} × {_fmt(d.depth)} mm{marker}"


def _stone_fact(spec: Spec, stone: Stone, prefix: str) -> str:
    cut = stone.cut.replace("_", " ")
    base = (f"{stone.carat:.2f} ct {stone.species} · {cut} · "
            f"{_dims(spec, stone, prefix)}")
    if stone.count > 1:
        base = (f"{stone.count} × {stone.species} {cut} · "
                f"{_dims(spec, stone, prefix)} · "
                f"{stone.count * stone.carat:.2f} ct total")
    return base


def _metal_fact(metal) -> str:
    karat = f"{metal.karat}k " if metal.karat else ""
    color = f"{metal.color.title()} " if metal.color else ""
    material = metal.material.replace("_", " ").title()
    finish = f" · {metal.finish.replace('_', ' ')}" if metal.finish else ""
    return f"{karat}{color}{material}{finish}"


def _side_label(stone: Stone, i: int, total: int) -> str:
    position = (stone.position or "").lower()
    named = {"halo": "Halo stones", "surround": "Surround stones",
             "stations": "Station stones", "under_center": "Drop stone",
             "drop": "Drop stone", "accents": "Accent stones",
             "accent": "Accent stones"}
    if position in named:
        return named[position]
    return f"Side stones {i + 1}" if total > 1 else "Side stones"


def _chain_geometry_fact(spec: Spec) -> str:
    chain = spec.chain
    if chain is None or chain.geometry is None:
        return ""
    geometry = chain.geometry
    common = (
        f"width {_fmt_chain(geometry.chain_width_mm)} × profile "
        f"{_fmt_chain(geometry.profile_thickness_mm)} mm"
        + estimate_marker(
            spec,
            "chain.geometry.chain_width_mm",
            "chain.geometry.profile_thickness_mm",
        )
    )
    if isinstance(geometry, OpenLinkChainGeometry):
        links = "/".join(_fmt_chain(link.length_mm) for link in geometry.links)
        marker = estimate_marker(
            spec,
            "chain.geometry.link_thickness_mm",
            *(f"chain.geometry.links[{index}].length_mm"
              for index in range(len(geometry.links))),
        )
        detail = (
            f"links L {links} mm · section "
            f"{_fmt_chain(geometry.link_thickness_mm)} mm{marker}"
        )
    elif isinstance(geometry, StrandedChainGeometry):
        marker = estimate_marker(
            spec, "chain.geometry.strand_wire_diameter_mm")
        detail = (
            f"{geometry.strand_count} strands · wire ⌀ "
            f"{_fmt_chain(geometry.strand_wire_diameter_mm)} mm{marker}"
        )
    elif isinstance(geometry, SmoothChainGeometry):
        marker = estimate_marker(spec, "chain.geometry.plate_thickness_mm")
        detail = (
            f"smooth plate {_fmt_chain(geometry.plate_thickness_mm)} mm{marker}"
        )
    else:  # pragma: no cover - discriminated union is exhaustive
        detail = ""
    return f" · {common} · {detail}"


def build_checklist_items(spec: Spec) -> list[ChecklistItem]:
    """One item per aspect the piece actually has. Item keys/sections map 1:1
    onto agent.resolve_target's vocabulary, so every NO can prefill a scoped
    edit. Facts are values only — the designer confirms numbers, not vibes."""
    items = [ChecklistItem(
        key="stone", ref="A", section="stone", index=None,
        label="Center stone", fact=_stone_fact(spec, spec.stone, "stone"),
        question="Is the center stone right?")]

    for i, s in enumerate(spec.side_stones):
        items.append(ChecklistItem(
            key=f"side_stones[{i}]", ref=chr(ord("B") + i),
            section="side_stones", index=i,
            label=_side_label(s, i, len(spec.side_stones)),
            fact=_stone_fact(spec, s, f"side_stones[{i}]"),
            question=f"Are the {_side_label(s, i, len(spec.side_stones)).lower()} right?"))

    if spec.setting is not None:
        style = spec.setting.style.replace("_", " ").title()
        if (spec.setting.prong_count
                and str(spec.setting.prong_count) not in style):
            style += f" · {spec.setting.prong_count}-prong"
        if spec.setting.gallery_height_mm:
            style += (f" · gallery {_fmt(spec.setting.gallery_height_mm)} mm"
                      f"{estimate_marker(spec, 'setting.gallery_height_mm')}")
        items.append(ChecklistItem(
            key="setting", ref=None, section="setting", index=None,
            label="Setting", fact=style, question="Is the setting right?"))

    if spec.metal is not None:
        items.append(ChecklistItem(
            key="metal", ref=None, section="metal", index=None,
            label="Metal & finish", fact=_metal_fact(spec.metal),
            question="Are the metal and finish right?"))

    if spec.band is not None:
        b = spec.band
        items.append(ChecklistItem(
            key="band", ref=None, section="band", index=None,
            label="Band",
            fact=(f"{b.profile.replace('_', ' ')} · "
                  f"{_fmt(b.width_mm)} × {_fmt(b.thickness_mm)} mm"
                  f"{estimate_marker(spec, 'band.width_mm', 'band.thickness_mm')}"),
            question="Is the band right?"))

    if spec.ring_size is not None:
        rs = spec.ring_size
        fact = f"{rs.system} {rs.value}"
        if rs.inner_diameter_mm:
            fact += f" · ⌀ {_fmt(rs.inner_diameter_mm)} mm"
        fact += estimate_marker(
            spec, "ring_size.value", "ring_size.inner_diameter_mm")
        items.append(ChecklistItem(
            key="ring_size", ref=None, section="ring_size", index=None,
            label="Ring size", fact=fact, question="Is the ring size right?"))

    if spec.drop is not None:
        d = spec.drop
        fact = (f"hook {_fmt(d.hook_height_mm)} mm · "
                f"overall {_fmt(d.overall_length_mm)} mm")
        fact += estimate_marker(
            spec, "drop.hook_height_mm", "drop.overall_length_mm")
        if d.link_count:
            fact += f" · {d.link_count} links"
        items.append(ChecklistItem(
            key="drop", ref=None, section="drop", index=None,
            label="Drop construction", fact=fact,
            question="Are the hook and drop length right?"))

    if spec.pendant is not None:
        p = spec.pendant
        fact = (f"bail ⌀ {_fmt(p.bail_inner_diameter_mm)} mm · "
                f"h {_fmt(p.bail_height_mm)} mm")
        if p.drop_mm:
            fact += f" · drop {_fmt(p.drop_mm)} mm"
        fact += estimate_marker(
            spec, "pendant.bail_inner_diameter_mm", "pendant.bail_height_mm",
            "pendant.drop_mm")
        items.append(ChecklistItem(
            key="pendant", ref=None, section="pendant", index=None,
            label="Pendant & bail", fact=fact,
            question="Are the bail and drop right?"))

    if spec.chain is not None:
        c = spec.chain
        production = ""
        if c.production is not None:
            production = (
                f" · {c.production.mode} "
                f"{c.production.reference_kind.replace('_', ' ')} "
                f"{c.production.reference}"
            )
        connection = (
            " · " + c.pendant_connection.replace("_", " ")
            if c.pendant_connection is not None
            else ""
        )
        items.append(ChecklistItem(
            key="chain", ref=None, section="chain", index=None,
            label="Chain & clasp",
            fact=(f"{c.style.replace('_', ' ')} · {_fmt(c.length_mm)} mm · "
                  f"{c.clasp.replace('_', ' ')}"
                  f"{estimate_marker(spec, 'chain.length_mm')}"
                  f"{_chain_geometry_fact(spec)}{connection}{production}"),
            question="Are the chain and clasp right?"))

    if spec.bracelet is not None:
        br = spec.bracelet
        fact = (f"inner {_fmt(br.inner_length_mm)} × "
                f"{_fmt(br.inner_width_mm)} mm · band "
                f"{_fmt(br.width_mm)} × {_fmt(br.thickness_mm)} mm")
        fact += estimate_marker(
            spec, "bracelet.inner_length_mm", "bracelet.inner_width_mm",
            "bracelet.width_mm", "bracelet.thickness_mm")
        items.append(ChecklistItem(
            key="bracelet", ref=None, section="bracelet", index=None,
            label="Bangle fit", fact=fact,
            question="Are the opening and band right?"))

    if spec.brooch is not None:
        items.append(ChecklistItem(
            key="brooch", ref=None, section="brooch", index=None,
            label="Brooch footprint",
            fact=(f"{_fmt(spec.brooch.length_mm)} × "
                  f"{_fmt(spec.brooch.width_mm)} mm"
                  f"{estimate_marker(spec, 'brooch.length_mm', 'brooch.width_mm')}"),
            question="Is the footprint right?"))

    for element in spec.design_form.elements:
        definition = element.definition
        if definition.kind == "dimensioned_profile":
            authority = (
                "designer-confirmed estimate"
                if definition.dimension_status == "designer_confirmed_estimate"
                else "designer-supplied dimensioned profile"
            )
            form_fact = (
                f"{element.confirmed_form_description} · {authority} · "
                f"{definition.view.replace('_', ' ')} view · "
                f"{len(definition.paths)} path(s)"
            )
        else:
            form_fact = (
                element.confirmed_form_description
                + " · visual reference only"
            )
        items.append(ChecklistItem(
            key=f"design_form:{element.element_id}",
            ref=None,
            section="design_form",
            index=None,
            target_element_id=element.element_id,
            label=element.label,
            fact=form_fact,
            question=f"Is the confirmed {element.label.lower()} form right?",
        ))

    if spec.notes_to_factory:
        items.append(ChecklistItem(
            key="notes_to_factory", ref=None, section="notes_to_factory",
            index=None, label="Factory instructions",
            fact=spec.notes_to_factory,
            question="Are the factory instructions complete and correct?",
        ))

    return items


def checklist_status(items: list[dict], responses) -> dict:
    """Roll up the taps: latest response per item wins (responses ordered
    oldest-first). outstanding = unanswered or declined — everything that
    still blocks an all-approved state."""
    latest: dict[str, bool] = {}
    for r in responses:
        latest[r.item_key] = bool(r.approved)
    keys = [i["key"] for i in items]
    approved = [k for k in keys if latest.get(k) is True]
    declined = [k for k in keys if latest.get(k) is False]
    outstanding = [k for k in keys if latest.get(k) is not True]
    return {
        "total": len(keys),
        "answered": sum(1 for k in keys if k in latest),
        "approved": len(approved),
        "declined": declined,
        "outstanding": outstanding,
        "all_approved": len(approved) == len(keys) and len(keys) > 0,
    }


def approval_footer_line(status: dict, approver: str, when) -> str:
    """The line the official frame letters in the footer:
    'approved 7/7 · usr_ana · 2026-07-08'."""
    return (f"approved {status['approved']}/{status['total']} · {approver} · "
            f"{when.date().isoformat()}")

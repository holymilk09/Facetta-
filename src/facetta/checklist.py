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

from facetta.spec import Spec, Stone

MODES = ("auto_pin", "explicit_pin", "optional")
DEFAULT_MODE = "auto_pin"


class ChecklistItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str            # stable id: "stone", "side_stones[0]", "band", ...
    ref: str | None     # stone-schedule letter (stones only) → Annotation.ref
    section: str        # agent-resolvable section name → Annotation.section
    index: int | None   # side_stones index, when the section is one
    label: str          # "Center stone", "Band", "Chain & clasp"
    fact: str           # one-line FACT from the record
    question: str       # the tap copy


def _fmt(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _dims(stone: Stone) -> str:
    d = stone.dimensions_mm
    return f"{_fmt(d.length)} × {_fmt(d.width)} × {_fmt(d.depth)} mm"


def _stone_fact(stone: Stone) -> str:
    cut = stone.cut.replace("_", " ")
    base = f"{stone.carat:.2f} ct {stone.species} · {cut} · {_dims(stone)}"
    if stone.count > 1:
        base = (f"{stone.count} × {stone.species} {cut} · {_dims(stone)} · "
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


def build_checklist_items(spec: Spec) -> list[ChecklistItem]:
    """One item per aspect the piece actually has. Item keys/sections map 1:1
    onto agent.resolve_target's vocabulary, so every NO can prefill a scoped
    edit. Facts are values only — the designer confirms numbers, not vibes."""
    items = [ChecklistItem(
        key="stone", ref="A", section="stone", index=None,
        label="Center stone", fact=_stone_fact(spec.stone),
        question="Is the center stone right?")]

    for i, s in enumerate(spec.side_stones):
        items.append(ChecklistItem(
            key=f"side_stones[{i}]", ref=chr(ord("B") + i),
            section="side_stones", index=i,
            label=_side_label(s, i, len(spec.side_stones)),
            fact=_stone_fact(s),
            question=f"Are the {_side_label(s, i, len(spec.side_stones)).lower()} right?"))

    if spec.setting is not None:
        style = spec.setting.style.replace("_", " ").title()
        if (spec.setting.prong_count
                and str(spec.setting.prong_count) not in style):
            style += f" · {spec.setting.prong_count}-prong"
        if spec.setting.gallery_height_mm:
            style += f" · gallery {_fmt(spec.setting.gallery_height_mm)} mm"
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
                  f"{_fmt(b.width_mm)} × {_fmt(b.thickness_mm)} mm"),
            question="Is the band right?"))

    if spec.ring_size is not None:
        rs = spec.ring_size
        fact = f"{rs.system} {rs.value}"
        if rs.inner_diameter_mm:
            fact += f" · ⌀ {_fmt(rs.inner_diameter_mm)} mm"
        items.append(ChecklistItem(
            key="ring_size", ref=None, section="ring_size", index=None,
            label="Ring size", fact=fact, question="Is the ring size right?"))

    if spec.drop is not None:
        d = spec.drop
        fact = (f"hook {_fmt(d.hook_height_mm)} mm · "
                f"overall {_fmt(d.overall_length_mm)} mm")
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
        items.append(ChecklistItem(
            key="pendant", ref=None, section="pendant", index=None,
            label="Pendant & bail", fact=fact,
            question="Are the bail and drop right?"))

    if spec.chain is not None:
        c = spec.chain
        items.append(ChecklistItem(
            key="chain", ref=None, section="chain", index=None,
            label="Chain & clasp",
            fact=(f"{c.style.replace('_', ' ')} · {_fmt(c.length_mm)} mm · "
                  f"{c.clasp.replace('_', ' ')}"),
            question="Are the chain and clasp right?"))

    if spec.bracelet is not None:
        br = spec.bracelet
        fact = (f"inner {_fmt(br.inner_length_mm)} × "
                f"{_fmt(br.inner_width_mm)} mm · band "
                f"{_fmt(br.width_mm)} × {_fmt(br.thickness_mm)} mm")
        items.append(ChecklistItem(
            key="bracelet", ref=None, section="bracelet", index=None,
            label="Bangle fit", fact=fact,
            question="Are the opening and band right?"))

    if spec.brooch is not None:
        items.append(ChecklistItem(
            key="brooch", ref=None, section="brooch", index=None,
            label="Brooch footprint",
            fact=(f"{_fmt(spec.brooch.length_mm)} × "
                  f"{_fmt(spec.brooch.width_mm)} mm"),
            question="Is the footprint right?"))

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

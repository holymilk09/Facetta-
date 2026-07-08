"""Human-readable diffs between two spec versions.

Versions are immutable, so every edit is a new version and the previous exact
numbers are never lost. This turns two stored specs into a plain-language list
of what changed — "center stone length 14 → 13.5 mm" — so a designer who
adjusts a dimension (and forgets the old value) can always see, and revert to,
the previous correct one. Structural, not agent-reported: it compares the
specs themselves, so it cannot mis-state a change.
"""

from __future__ import annotations

from typing import Any

# metadata and traced geometry are not designer-facing dimensions — skip them
_SKIP_TOP = {"design_id", "version", "created_by", "created_at",
             "schema_version", "composition"}

# friendly names for the path segments a designer recognizes
_SECTION = {
    "stone": "center stone", "side_stones": "side stone",
    "band": "band", "ring_size": "ring size", "metal": "metal",
    "setting": "setting", "drop": "drop", "pendant": "pendant",
    "bracelet": "bracelet", "chain": "chain", "brooch": "brooch",
    "dimensions_mm": "", "color": "colour", "clarity": "clarity",
}
_LEAF = {
    "length": "length", "width": "width", "depth": "depth",
    "carat": "weight", "count": "count", "species": "type", "cut": "cut",
    "width_mm": "width", "thickness_mm": "thickness", "profile": "profile",
    "value": "size", "system": "system", "inner_diameter_mm": "inner diameter",
    "overall_length_mm": "overall length", "hook_height_mm": "hook height",
    "link_count": "links", "link_pitch_mm": "link pitch",
    "prong_count": "prongs", "gallery_height_mm": "gallery height",
    "material": "material", "karat": "karat", "color": "colour",
    "finish": "finish", "style": "style", "position": "position",
    "trade": "trade colour", "grade": "grade",
    "notes_to_factory": "factory notes",
}


def _unit(path: str, leaf: str) -> str:
    if leaf == "carat":
        return "ct"
    if leaf.endswith("_mm") or "dimensions_mm" in path:
        return "mm"
    return ""


def _label(path: list[str]) -> str:
    """Turn a path like ['side_stones', '0', 'dimensions_mm', 'length'] into
    'side stone 2 length'."""
    words: list[str] = []
    i = 0
    while i < len(path):
        seg = path[i]
        if seg.isdigit():
            i += 1
            continue
        if i + 1 < len(path) and path[i] == "side_stones" and path[i + 1].isdigit():
            words.append(f"side stone {int(path[i + 1]) + 1}")
            i += 2
            continue
        name = _SECTION.get(seg) if i < len(path) - 1 else _LEAF.get(seg, seg)
        if name is None:
            name = _LEAF.get(seg, seg.replace("_", " "))
        if name:
            words.append(name)
        i += 1
    return " ".join(words) or ".".join(path)


def _fmt(value: Any, unit: str) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        text = f"{value:.2f}".rstrip("0").rstrip(".")
    elif isinstance(value, (int, str)):
        text = str(value)
    else:
        return str(value)
    return f"{text} {unit}".strip() if unit else text


def _walk(before: Any, after: Any, path: list[str], out: list[dict]) -> None:
    if isinstance(before, dict) or isinstance(after, dict):
        b = before if isinstance(before, dict) else {}
        a = after if isinstance(after, dict) else {}
        for key in sorted(set(b) | set(a)):
            if not path and key in _SKIP_TOP:
                continue
            _walk(b.get(key), a.get(key), path + [key], out)
        return
    if isinstance(before, list) or isinstance(after, list):
        b = before if isinstance(before, list) else []
        a = after if isinstance(after, list) else []
        for idx in range(max(len(b), len(a))):
            bv = b[idx] if idx < len(b) else None
            av = a[idx] if idx < len(a) else None
            _walk(bv, av, path + [str(idx)], out)
        return
    if before == after:
        return
    leaf = path[-1] if path else ""
    unit = _unit(".".join(path), leaf)
    kind = "changed"
    if before is None:
        kind = "added"
    elif after is None:
        kind = "removed"
    out.append({
        "path": ".".join(path),
        "label": _label(path),
        "from": _fmt(before, unit),
        "to": _fmt(after, unit),
        "kind": kind,
    })


def diff_specs(before: dict, after: dict) -> list[dict]:
    """Every leaf that changed between two stored specs, as a flat list of
    {path, label, from, to, kind}. Empty when the two specs are identical."""
    out: list[dict] = []
    _walk(before or {}, after or {}, [], out)
    return out


def summarize_changes(changes: list[dict]) -> str:
    """A one-line human summary of a diff — 'band width 2.2 → 2 mm; center
    stone weight 3.83 → 4.10 ct'. Empty string when nothing changed."""
    parts = []
    for c in changes:
        if c["kind"] == "changed":
            parts.append(f"{c['label']} {c['from']} → {c['to']}")
        elif c["kind"] == "added":
            parts.append(f"{c['label']} set to {c['to']}")
        else:
            parts.append(f"{c['label']} removed")
    return "; ".join(parts)

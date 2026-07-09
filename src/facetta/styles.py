"""The design-style library: eras and archetypes for the from-scratch assistant.

The founder asked whether we need a library of styles, years, and types — yes,
and like the gemological vocabulary it lives in data, not code. This loader
gives the assistant two things: a compact digest to ground its questions (so it
asks about Art Deco hallmarks instead of inventing them), and a lookup from a
chosen type to the sheet template that draws it. Extend the library by editing
data/design_styles.json with the same field shape — never by special-casing.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

STYLES_PATH = Path(__file__).resolve().parents[2] / "data" / "design_styles.json"


class StyleLibrary:
    def __init__(self, raw: dict):
        self._raw = raw
        self._eras = {e["id"]: e for e in raw.get("eras", [])}
        self._types = {t["id"]: t for t in raw.get("types", [])}

    def eras(self) -> list[dict]:
        return list(self._eras.values())

    def types(self) -> list[dict]:
        return list(self._types.values())

    def era(self, era_id: str) -> dict | None:
        return self._eras.get(era_id)

    def type(self, type_id: str) -> dict | None:
        return self._types.get(type_id)

    def era_ids(self) -> list[str]:
        return list(self._eras)

    def type_ids(self) -> list[str]:
        return list(self._types)

    def template_for(self, type_id: str) -> str | None:
        t = self._types.get(type_id)
        return t.get("template") if t else None

    def digest(self) -> str:
        """A compact, prompt-ready summary of the library."""
        lines = ["Design-style library (hints only; gemology vocabulary is the "
                 "source of stone/metal truth):", "", "Eras:"]
        for e in self.eras():
            lines.append(
                f"- {e['id']} ({e['label']}, {e.get('years', '')}): "
                f"{', '.join(e.get('hallmarks', []))}")
        lines.append("")
        lines.append("Types:")
        for t in self.types():
            lines.append(
                f"- {t['id']} ({t['label']}): {t.get('description', '')} "
                f"[needs: {', '.join(t.get('needs', []))}]")
        return "\n".join(lines)


@lru_cache(maxsize=1)
def get_styles(path: Path = STYLES_PATH) -> StyleLibrary:
    with open(path, encoding="utf-8") as f:
        return StyleLibrary(json.load(f))

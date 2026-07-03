"""Loader and typed accessors for data/gemology_vocabulary.json.

The vocabulary file is the single source of gemological truth. Extend it via
data, never by special-casing in code.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

VOCABULARY_PATH = Path(__file__).resolve().parents[2] / "data" / "gemology_vocabulary.json"


@dataclass(frozen=True)
class Species:
    id: str
    display: str
    sg: float
    clarity_systems: tuple[str, ...]
    trade_color_keys: tuple[str, ...]
    allowed_phenomena: tuple[str, ...]


@dataclass(frozen=True)
class Cut:
    id: str
    name: str
    category: str
    shape_factor: float


@dataclass(frozen=True)
class TradeColorTerm:
    term: str
    gia: str
    meaning: str = ""
    origin_tie: str = ""
    notes: str = ""
    extras: dict = field(default_factory=dict, compare=False)


class Vocabulary:
    def __init__(self, raw: dict):
        self.raw = raw
        self._species = {
            sid: Species(
                id=sid,
                display=entry["display"],
                sg=entry["sg"],
                clarity_systems=tuple(entry["clarity_systems"]),
                trade_color_keys=tuple(entry["trade_color_keys"]),
                allowed_phenomena=tuple(entry["allowed_phenomena"]),
            )
            for sid, entry in raw["species"].items()
            if sid != "note"
        }
        factors = raw["shape_factors"]["factors"]
        self._cuts = {
            c["id"]: Cut(id=c["id"], name=c["name"], category=c["category"], shape_factor=factors[c["id"]])
            for c in raw["cuts_and_shapes"]
        }

    # --- species ---

    def species_ids(self) -> list[str]:
        return list(self._species)

    def species(self, species_id: str) -> Species | None:
        return self._species.get(species_id)

    # --- cuts ---

    def cut_ids(self) -> list[str]:
        return list(self._cuts)

    def cut(self, cut_id: str) -> Cut | None:
        return self._cuts.get(cut_id)

    # --- colors ---

    def trade_color_terms(self, species_id: str) -> list[TradeColorTerm]:
        sp = self._species.get(species_id)
        if sp is None:
            return []
        terms = []
        for key in sp.trade_color_keys:
            for entry in self.raw["trade_color_terms"].get(key, []):
                known = {k: entry[k] for k in ("term", "gia", "meaning", "origin_tie", "notes") if k in entry}
                extras = {k: v for k, v in entry.items() if k not in known}
                terms.append(TradeColorTerm(**known, extras=extras))
        return terms

    def trade_color_names(self, species_id: str) -> list[str]:
        return [t.term for t in self.trade_color_terms(species_id)]

    # --- clarity ---

    def clarity_grade_entries(self, system: str) -> list[dict]:
        """Grade + meaning entries for a spec-facing clarity system id,
        e.g. 'gia_type_ii' or 'gia_diamond'."""
        key = system.removeprefix("gia_")
        return self.raw["clarity_grades_by_type"].get(key) or self.raw["clarity_grades_by_type"].get(system, [])

    def clarity_grades(self, system: str) -> list[str]:
        return [e["grade"] for e in self.clarity_grade_entries(system)]

    def clarity_systems(self) -> list[str]:
        return ["gia_" + k for k in self.raw["clarity_grades_by_type"]
                if not k.startswith("gia_")] + [k for k in self.raw["clarity_grades_by_type"] if k.startswith("gia_")]

    # --- phenomena ---

    def phenomena_ids(self) -> list[str]:
        return [k for k, v in self.raw["phenomena"].items() if isinstance(v, dict) and "definition" in v]

    # --- findings (metalwork) and gem-ID scales ---

    def chain_styles(self) -> list[dict]:
        return self.raw["findings"]["chain_styles"]

    def chain_style_ids(self) -> list[str]:
        return [c["id"] for c in self.chain_styles()]

    def clasp_types(self) -> list[dict]:
        return self.raw["findings"]["clasp_types"]

    def clasp_type_ids(self) -> list[str]:
        return [c["id"] for c in self.clasp_types()]

    def girdle_grades(self) -> list[str]:
        return self.raw["girdle_thickness_scale"]

    def metals(self) -> list[dict]:
        return self.raw["metals"]["materials"]

    def metal(self, material: str) -> dict | None:
        return next((m for m in self.metals() if m["id"] == material), None)

    def culet_grades(self) -> list[dict]:
        return self.raw["culet_size_scale"]["grades"]

    def culet_grade_ids(self) -> list[str]:
        return [g["id"] for g in self.culet_grades()]

    def girdle_detail(self, grade: str) -> dict | None:
        return self.raw["girdle_thickness_detail"].get(grade)

    def girdle_weight_correction(self, cut: str, grade: str) -> float:
        table = self.raw["girdle_weight_correction"]
        row = table.get(cut, table["default"])
        return row.get(grade, 1.0)

    def ring_size_rows(self) -> list[dict]:
        return self.raw["ring_size_conversion"]["rows"]

    def manufacturing_tolerances(self) -> dict:
        return self.raw["manufacturing_tolerances"]

    def grading_labs(self) -> list[str]:
        return self.raw["grading_labs"]["labs"]

    # --- organic / amorphous gems with their own parameter sets ---

    ORGANIC_PARAMETER_SETS = ("pearl", "opal")

    def parameter_set(self, stone_id: str) -> dict | None:
        """The dedicated parameter set for stones outside the crystalline
        gemstone schema (pearls, opals)."""
        if stone_id in self.ORGANIC_PARAMETER_SETS:
            return self.raw[stone_id]
        return None

    def stone_ids(self) -> list[str]:
        """Everything a designer can pick as a stone: crystalline species plus
        the organic/amorphous gems that carry their own parameter sets."""
        return self.species_ids() + list(self.ORGANIC_PARAMETER_SETS)


@lru_cache(maxsize=1)
def get_vocabulary(path: Path = VOCABULARY_PATH) -> Vocabulary:
    with open(path, encoding="utf-8") as f:
        return Vocabulary(json.load(f))

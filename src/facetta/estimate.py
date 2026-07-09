"""The math assist: deterministic code as the CALCULATOR, never the designer.

Two directions, one density model (the same formula the validator trusts,
density.py: carat ≈ L × W × D × SG × shape_factor / 200):

- a designer types dimensions → derive the carat, or the depth a claimed
  carat physically requires (estimate_carat / required_depth_mm);
- Grok estimates stones from a render → physics-check each one, correct a
  carat that contradicts its own size, fill a missing carat, and move the
  per-value confidence accordingly (physics_check_estimates).

Everything here is pure arithmetic over the vocabulary's SG and shape-factor
tables. No LLM, no cache, and — the founder's rule — absolutely no drawing:
this module never touches an image.
"""

from __future__ import annotations

import re

from facetta.density import TOLERANCE, check_density
from facetta.vocabulary import Vocabulary

# confidence never claims certainty: a physics-consistent estimate is still
# an estimate of a render, so the bump is capped below 1.0
_CONFIDENCE_BUMP = 0.15
_CONFIDENCE_CAP = 0.95


class EstimateError(ValueError):
    """Unknown species/cut or unusable dimensions — carries valid options."""


def _lookup(vocab: Vocabulary, species: str, cut: str):
    sp = vocab.species(species)
    if sp is None:
        raise EstimateError(
            f"unknown species '{species}'; options: {vocab.species_ids()}")
    c = vocab.cut(cut)
    if c is None:
        raise EstimateError(
            f"unknown cut '{cut}'; options: {vocab.cut_ids()}")
    return sp, c


def estimate_carat(vocab: Vocabulary, species: str, cut: str,
                   length_mm: float, width_mm: float,
                   depth_mm: float | None = None) -> dict:
    """The modeled carat for a stone of these dimensions. When no depth is
    given, the cut's typical depth ratio fills it in (an estimation default —
    a stated depth always wins). Returns
    {"carat", "depth_used_mm", "depth_assumed"}."""
    sp, c = _lookup(vocab, species, cut)
    if length_mm <= 0 or width_mm <= 0 or (depth_mm is not None and depth_mm <= 0):
        raise EstimateError("dimensions must be positive millimetres")
    assumed = depth_mm is None
    depth = round(width_mm * c.typical_depth_ratio, 2) if assumed else depth_mm
    carat = length_mm * width_mm * depth * sp.sg * c.shape_factor / 200
    return {"carat": round(carat, 3), "depth_used_mm": depth,
            "depth_assumed": assumed}


def required_depth_mm(vocab: Vocabulary, species: str, cut: str,
                      carat: float, length_mm: float, width_mm: float) -> float:
    """The depth that makes a claimed carat physically consistent with L × W —
    the inverse of the density model, for 'I want 2 ct at 8 × 6 mm'."""
    sp, c = _lookup(vocab, species, cut)
    if carat <= 0 or length_mm <= 0 or width_mm <= 0:
        raise EstimateError("carat and dimensions must be positive")
    return round(carat * 200 / (length_mm * width_mm * sp.sg * c.shape_factor), 2)


_SIZE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*[×x*]\s*(\d+(?:\.\d+)?)(?:\s*[×x*]\s*(\d+(?:\.\d+)?))?")
_ROUND_RE = re.compile(r"[⌀ø]?\s*(\d+(?:\.\d+)?)\s*(?:mm)?\s*$")


def parse_size_mm(text) -> tuple[float, float, float | None] | None:
    """Tolerant parse of an estimated size string ('8 × 6', '~8.5 x 6.5 mm',
    '7×5×3.2', '⌀1.4') → (length, width, depth|None), or None when no usable
    numbers are present. A single number reads as a round stone's diameter."""
    if not isinstance(text, str):
        return None
    m = _SIZE_RE.search(text)
    if m:
        length, width = float(m.group(1)), float(m.group(2))
        depth = float(m.group(3)) if m.group(3) else None
        return (length, width, depth) if length > 0 and width > 0 else None
    m = _ROUND_RE.search(text.strip().lstrip("~"))
    if m and float(m.group(1)) > 0:
        d = float(m.group(1))
        return (d, d, None)
    return None


def match_stone_words(vocab: Vocabulary, type_text: str) -> tuple[str | None, str | None]:
    """Match a free-text stone description ('diamond oval brilliant') against
    the vocabulary registry. Longest match wins; NO match means the caller
    must leave the stone alone — an SG is never guessed."""
    lowered = f" {type_text.lower()} "
    species = None
    for sid in vocab.species_ids():
        needle = sid.replace("_", " ")
        if f" {needle} " in lowered or lowered.strip().startswith(needle):
            if species is None or len(needle) > len(species.replace("_", " ")):
                species = sid
    cut = None
    for cid in vocab.cut_ids():
        needle = cid.replace("_", " ")
        if needle in lowered:
            if cut is None or len(needle) > len(cut.replace("_", " ")):
                cut = cid
    # trade shorthand: 'round' and 'brilliant' alone mean round brilliant
    if cut is None and ("round" in lowered or "brilliant" in lowered):
        cut = "round_brilliant" if vocab.cut("round_brilliant") else None
    return species, cut


def physics_check_estimates(vocab: Vocabulary, estimates: dict) -> dict:
    """Run every Grok-estimated stone through the density model — pure code,
    zero API calls, the drawing untouched. Per stone (species+cut matched from
    its own description, size parseable):

    - carat present and consistent with the size → confidence raised (capped);
    - carat contradicts the size → carat replaced with the modeled value and
      the correction noted (the size is what Grok SAW; the carat is derived);
    - carat missing → filled from the model, noted as modeled.

    A stone whose species/cut/size cannot be resolved is left exactly as
    read — the model never guesses an SG. Sets estimates['physics_checked']
    when at least one stone was actually checked."""
    checked_any = False
    for stone in estimates.get("stones") or []:
        species, cut = match_stone_words(vocab, str(stone.get("type", "")))
        size = parse_size_mm(stone.get("size_mm"))
        if species is None or cut is None or size is None:
            continue
        length, width, depth = size
        modeled = estimate_carat(vocab, species, cut, length, width, depth)
        checked_any = True
        carat = stone.get("carat_each")
        if carat is None:
            stone["carat_each"] = modeled["carat"]
            stone["note"] = "carat modeled from size (density model)"
            continue
        sp, c = _lookup(vocab, species, cut)
        result = check_density(
            sg=sp.sg, shape_factor=c.shape_factor, length_mm=length,
            width_mm=width, depth_mm=modeled["depth_used_mm"],
            carat=float(carat),
            # an assumed depth loosens the gate: the ratio itself is ±
            tolerance=TOLERANCE * (2.5 if modeled["depth_assumed"] else 1.0))
        if result.ok:
            stone["confidence"] = min(
                _CONFIDENCE_CAP,
                float(stone.get("confidence") or 0.5) + _CONFIDENCE_BUMP)
            stone["note"] = "physics ✓ (carat consistent with size)"
        else:
            stone["carat_each"] = modeled["carat"]
            stone["note"] = (f"carat adjusted from {carat} to match the "
                             f"estimated size (density model)")
    if checked_any:
        estimates["physics_checked"] = True
    return estimates

"""The engine evaluation harness: same specs, same instructions, different
engines — scored identically, so an engine claim is a measured number, not an
impression.

Research tooling, not product surface. Scoring leans on the checkers the
platform already trusts:

- spec conformance: Grok vision READS the generated image back into estimated
  values (read_sheet_specs), the density model corrects them
  (physics_check_estimates), and code compares the read against the actual
  validated spec — species named, metal matched, stone count, centre carat.
- edit fidelity: a two-image vision check — did the intended change happen,
  and did the rest of the design hold static (the founder's passing bar for
  image-to-image editing).

Every scoring call is LIVE (vision is never cached); the generations
themselves ride the normal content-addressed engine cache.
"""

from __future__ import annotations

import re

from facetta.estimate import parse_size_mm, physics_check_estimates
from facetta.spec import Spec
from facetta.vocabulary import get_vocabulary

# ---------------------------------------------------------------------------
# spec conformance: does the image show the spec?
# ---------------------------------------------------------------------------


def _spec_stone_total(spec: Spec) -> int:
    return spec.stone.count + sum(s.count for s in spec.side_stones)


def score_spec_conformance(spec: Spec, image_bytes: bytes) -> dict:
    """Read the image back and compare against the record. Returns component
    scores in [0, 1] and a composite in [0, 100]. The read itself is Grok
    vision (live); every comparison after it is pure code."""
    from facetta.specagent import read_sheet_specs

    est = physics_check_estimates(
        get_vocabulary(), read_sheet_specs(image_bytes))
    stones = est.get("stones") or []
    all_types = " ".join(str(s.get("type", "")).lower() for s in stones)

    # the centre species must be visible in the read
    species_named = 1.0 if spec.stone.species.lower() in all_types else 0.0

    # the metal material must be visible in the read's metal line
    material = spec.metal.material.replace("_", " ").lower()
    metal_matched = 1.0 if material in str(est.get("metal", "")).lower() else 0.0

    # stone count: relative error, floored at zero credit for 100% off
    expected_count = _spec_stone_total(spec)
    read_count = sum(int(s.get("qty") or 0) for s in stones)
    count_score = max(0.0, 1.0 - abs(read_count - expected_count) / max(expected_count, 1))

    # centre carat: best-matching read stone vs the spec, relative error
    carat_score = 0.0
    read_carats = [float(s["carat_each"]) for s in stones
                   if s.get("carat_each") is not None]
    if read_carats:
        closest = min(read_carats, key=lambda c: abs(c - spec.stone.carat))
        rel_err = abs(closest - spec.stone.carat) / spec.stone.carat
        carat_score = max(0.0, 1.0 - rel_err)

    # centre size: best-matching read size vs the spec's mm, relative error
    size_score = 0.0
    sizes = [parse_size_mm(s.get("size_mm")) for s in stones]
    sizes = [z for z in sizes if z]
    if sizes:
        want = spec.stone.dimensions_mm
        best = min(sizes, key=lambda z: abs(z[0] - want.length) + abs(z[1] - want.width))
        rel = (abs(best[0] - want.length) / want.length
               + abs(best[1] - want.width) / want.width) / 2
        size_score = max(0.0, 1.0 - rel)

    components = {
        "species_named": species_named,
        "metal_matched": metal_matched,
        "stone_count": round(count_score, 3),
        "centre_carat": round(carat_score, 3),
        "centre_size": round(size_score, 3),
    }
    composite = round(100 * (
        0.25 * species_named + 0.20 * metal_matched + 0.20 * count_score
        + 0.15 * carat_score + 0.20 * size_score), 1)
    return {"components": components, "score": composite,
            "read": {"stones": stones, "metal": est.get("metal")}}


# ---------------------------------------------------------------------------
# edit fidelity: did the change happen, did the rest hold static?
# ---------------------------------------------------------------------------

_EDIT_EVAL_SYSTEM = """\
You compare two images of jewelry for a manufacturing platform's engine
evaluation. The FIRST image is the original design; the SECOND is the result
of an instructed edit. You will be told the ONE intended change.

Answer as JSON only, exactly this shape:
{"change_applied": true, "change_note": "what actually changed",
 "unintended_changes": ["anything else that differs beyond the intended change"],
 "severity": "none|minor|major"}

severity rates the UNINTENDED drift only: 'none' = the rest of the design is
identical; 'minor' = lighting/angle/reflection noise; 'major' = a different
stone, count, setting, or proportion that was NOT asked for. Judge strictly —
this measures whether the engine can edit one thing and hold the rest static."""


def score_edit_fidelity(reference_bytes: bytes, edited_bytes: bytes,
                        intended_change: str) -> dict:
    """Two-image vision judgement of one edit. Composite in [0, 100]:
    the intended change happening is most of the score; unintended MAJOR
    drift zeroes the static-hold component (the founder's passing bar)."""
    from facetta.specagent import _vision_json_2img

    data = _vision_json_2img(
        _EDIT_EVAL_SYSTEM, reference_bytes, edited_bytes,
        f"Intended change: {intended_change}. Did it happen, and did "
        "everything else hold static?")
    applied = bool(data.get("change_applied"))
    severity = str(data.get("severity", "major")).lower()
    static_hold = {"none": 1.0, "minor": 0.7}.get(severity, 0.0)
    composite = round(100 * (0.6 * (1.0 if applied else 0.0)
                             + 0.4 * static_hold), 1)
    return {"change_applied": applied,
            "unintended_changes": list(data.get("unintended_changes") or []),
            "severity": severity,
            "static_hold": static_hold,
            "score": composite,
            "note": str(data.get("change_note", ""))}


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]


def summarize_engine_scores(rows: list[dict]) -> dict:
    """Per-engine means from a list of {engine, kind, score} rows — the one
    table the comparison report leads with."""
    out: dict[str, dict] = {}
    for row in rows:
        e = out.setdefault(row["engine"], {"render": [], "edit": []})
        e[row["kind"]].append(row["score"])
    return {
        engine: {
            "render_avg": round(sum(v["render"]) / len(v["render"]), 1)
            if v["render"] else None,
            "edit_avg": round(sum(v["edit"]) / len(v["edit"]), 1)
            if v["edit"] else None,
            "runs": len(v["render"]) + len(v["edit"]),
        }
        for engine, v in out.items()
    }

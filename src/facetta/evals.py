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

The live wrappers never cache their vision observations.  Their matching
``*_from_observation`` functions are provider-free, deterministic replay
seams for retained evidence.
"""

from __future__ import annotations

from copy import deepcopy
from math import isfinite
import re

from facetta.estimate import parse_size_mm, physics_check_estimates
from facetta.spec import Spec
from facetta.vocabulary import get_vocabulary

# ---------------------------------------------------------------------------
# spec conformance: does the image show the spec?
# ---------------------------------------------------------------------------


def _spec_stone_total(spec: Spec) -> int:
    return spec.stone.count + sum(s.count for s in spec.side_stones)


def _require_finite_number(value: object, field: str, *, minimum: float,
                           maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a JSON number")
    number = float(value)
    if not isfinite(number) or number < minimum:
        raise ValueError(f"{field} must be finite and >= {minimum}")
    if maximum is not None and number > maximum:
        raise ValueError(f"{field} must be <= {maximum}")
    return number


def _validate_spec_observation(observation: object) -> dict:
    """Validate the normalized ``read_sheet_specs`` evidence without
    coercion.  Optional normalized metadata is checked when present even
    though it does not affect the score."""
    if not isinstance(observation, dict):
        raise ValueError("spec observation must be an object")
    allowed = {"stones", "metal", "measurements", "scaled", "scale_anchor"}
    unknown = set(observation) - allowed
    if unknown:
        raise ValueError(
            f"spec observation has unsupported fields: {sorted(unknown)}")
    if "stones" not in observation or not isinstance(observation["stones"], list):
        raise ValueError("spec observation.stones must be a list")
    if "metal" not in observation or not isinstance(observation["metal"], str):
        raise ValueError("spec observation.metal must be a string")

    allowed_stone = {
        "qty", "type", "size_mm", "carat_each", "confidence", "position",
        "qty_status", "source_views", "written_labels",
    }
    for index, stone in enumerate(observation["stones"]):
        prefix = f"spec observation.stones[{index}]"
        if not isinstance(stone, dict):
            raise ValueError(f"{prefix} must be an object")
        unknown_stone = set(stone) - allowed_stone
        if unknown_stone:
            raise ValueError(
                f"{prefix} has unsupported fields: {sorted(unknown_stone)}")
        required = {"qty", "type", "size_mm", "carat_each", "confidence"}
        missing = required - set(stone)
        if missing:
            raise ValueError(f"{prefix} is missing fields: {sorted(missing)}")
        if isinstance(stone["qty"], bool) or not isinstance(stone["qty"], int):
            raise ValueError(f"{prefix}.qty must be an integer")
        if stone["qty"] <= 0:
            raise ValueError(f"{prefix}.qty must be positive")
        if not isinstance(stone["type"], str) or not stone["type"].strip():
            raise ValueError(f"{prefix}.type must be a non-empty string")
        if not isinstance(stone["size_mm"], str):
            raise ValueError(f"{prefix}.size_mm must be a string")
        if stone["carat_each"] is not None:
            _require_finite_number(
                stone["carat_each"], f"{prefix}.carat_each", minimum=0.0)
        _require_finite_number(
            stone["confidence"], f"{prefix}.confidence", minimum=0.0,
            maximum=1.0)
        for field in ("position", "qty_status"):
            if field in stone and not isinstance(stone[field], str):
                raise ValueError(f"{prefix}.{field} must be a string")
        for field in ("source_views", "written_labels"):
            if field in stone:
                values = stone[field]
                if (not isinstance(values, list)
                        or any(not isinstance(value, str) for value in values)):
                    raise ValueError(f"{prefix}.{field} must be a string list")

    if "measurements" in observation:
        measurements = observation["measurements"]
        if not isinstance(measurements, list):
            raise ValueError("spec observation.measurements must be a list")
        allowed_measurement = {"label", "value", "confidence", "raw", "status"}
        for index, measurement in enumerate(measurements):
            prefix = f"spec observation.measurements[{index}]"
            if not isinstance(measurement, dict):
                raise ValueError(f"{prefix} must be an object")
            unknown_measurement = set(measurement) - allowed_measurement
            if unknown_measurement:
                raise ValueError(
                    f"{prefix} has unsupported fields: "
                    f"{sorted(unknown_measurement)}")
            required = {"label", "value", "confidence"}
            missing = required - set(measurement)
            if missing:
                raise ValueError(f"{prefix} is missing fields: {sorted(missing)}")
            for field in ("label", "value"):
                if not isinstance(measurement[field], str):
                    raise ValueError(f"{prefix}.{field} must be a string")
            _require_finite_number(
                measurement["confidence"], f"{prefix}.confidence", minimum=0.0,
                maximum=1.0)
            for field in ("raw", "status"):
                if field in measurement and not isinstance(measurement[field], str):
                    raise ValueError(f"{prefix}.{field} must be a string")
    if "scaled" in observation and not isinstance(observation["scaled"], bool):
        raise ValueError("spec observation.scaled must be a boolean")
    if ("scale_anchor" in observation
            and observation["scale_anchor"] is not None
            and not isinstance(observation["scale_anchor"], str)):
        raise ValueError("spec observation.scale_anchor must be a string or null")
    return observation


def score_spec_conformance_from_observation(
        spec: Spec, observation: dict) -> dict:
    """Score one retained, normalized vision observation with no provider
    calls.  Malformed evidence fails closed instead of being coerced into a
    plausible score."""
    validated = _validate_spec_observation(observation)

    est = physics_check_estimates(
        get_vocabulary(), deepcopy(validated))
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


def score_spec_conformance(spec: Spec, image_bytes: bytes) -> dict:
    """Read an image live, then score its retained observation."""
    from facetta.specagent import read_sheet_specs

    return score_spec_conformance_from_observation(
        spec, read_sheet_specs(image_bytes))


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


def score_edit_fidelity_from_observation(observation: dict) -> dict:
    """Score a retained two-image judgement with no provider calls.

    The evaluator intentionally rejects truthy strings, scalar substitutes
    for lists, and unknown severity values so replay cannot silently turn
    malformed evidence into an accepted result.
    """
    if not isinstance(observation, dict):
        raise ValueError("edit observation must be an object")
    allowed = {
        "change_applied", "change_note", "unintended_changes", "severity",
    }
    unknown = set(observation) - allowed
    if unknown:
        raise ValueError(
            f"edit observation has unsupported fields: {sorted(unknown)}")
    required = {"change_applied", "unintended_changes", "severity"}
    missing = required - set(observation)
    if missing:
        raise ValueError(f"edit observation is missing fields: {sorted(missing)}")
    applied = observation["change_applied"]
    if not isinstance(applied, bool):
        raise ValueError("edit observation.change_applied must be a boolean")
    changes = observation["unintended_changes"]
    if (not isinstance(changes, list)
            or any(not isinstance(change, str) for change in changes)):
        raise ValueError(
            "edit observation.unintended_changes must be a string list")
    severity_value = observation["severity"]
    if not isinstance(severity_value, str):
        raise ValueError("edit observation.severity must be a string")
    severity = severity_value.lower()
    if severity not in {"none", "minor", "major"}:
        raise ValueError(
            "edit observation.severity must be none, minor, or major")
    note = observation.get("change_note", "")
    if not isinstance(note, str):
        raise ValueError("edit observation.change_note must be a string")
    static_hold = {"none": 1.0, "minor": 0.7}.get(severity, 0.0)
    composite = round(100 * (0.6 * (1.0 if applied else 0.0)
                             + 0.4 * static_hold), 1)
    return {"change_applied": applied,
            "unintended_changes": list(changes),
            "severity": severity,
            "static_hold": static_hold,
            "score": composite,
            "note": note}


def score_edit_fidelity(reference_bytes: bytes, edited_bytes: bytes,
                        intended_change: str) -> dict:
    """Judge an edit live, then score its retained observation. Composite is
    in [0, 100]; major unintended drift zeroes the static-hold component."""
    from facetta.specagent import _vision_json_2img

    observation = _vision_json_2img(
        _EDIT_EVAL_SYSTEM, reference_bytes, edited_bytes,
        f"Intended change: {intended_change}. Did it happen, and did "
        "everything else hold static?")
    return score_edit_fidelity_from_observation(observation)


def derive_quality_verdict(quality_report: dict) -> str:
    """Recompute a canonical image-agent verdict from retained checks.

    A report with missing/malformed checks or a declared verdict that differs
    from the checks is invalid.  Callers can therefore gate only on an
    independently derived ``"pass"`` rather than trusting a stored scalar.
    """
    if not isinstance(quality_report, dict):
        raise ValueError("quality report must be an object")
    allowed = {"verdict", "checks", "score", "notes"}
    unknown = set(quality_report) - allowed
    if unknown:
        raise ValueError(
            f"quality report has unsupported fields: {sorted(unknown)}")
    missing = allowed - set(quality_report)
    if missing:
        raise ValueError(f"quality report is missing fields: {sorted(missing)}")
    declared = quality_report["verdict"]
    if declared not in {"pass", "warn", "fail"}:
        raise ValueError("quality report.verdict must be pass, warn, or fail")
    checks = quality_report["checks"]
    if not isinstance(checks, list) or not checks:
        raise ValueError("quality report.checks must be a non-empty list")
    notes = quality_report["notes"]
    if (not isinstance(notes, list)
            or any(not isinstance(note, str) for note in notes)):
        raise ValueError("quality report.notes must be a string list")
    score = quality_report["score"]
    if score is not None:
        _require_finite_number(
            score, "quality report.score", minimum=0.0, maximum=100.0)

    any_failed = False
    any_hard_failed = False
    expected_check_fields = {"code", "passed", "severity", "message", "evidence"}
    for index, check in enumerate(checks):
        prefix = f"quality report.checks[{index}]"
        if not isinstance(check, dict):
            raise ValueError(f"{prefix} must be an object")
        if set(check) != expected_check_fields:
            raise ValueError(
                f"{prefix} fields must be {sorted(expected_check_fields)}")
        for field in ("code", "message"):
            if not isinstance(check[field], str) or not check[field].strip():
                raise ValueError(f"{prefix}.{field} must be a non-empty string")
        if not isinstance(check["passed"], bool):
            raise ValueError(f"{prefix}.passed must be a boolean")
        if check["severity"] not in {"hard", "warning"}:
            raise ValueError(f"{prefix}.severity must be hard or warning")
        if not isinstance(check["evidence"], dict):
            raise ValueError(f"{prefix}.evidence must be an object")
        if not check["passed"]:
            any_failed = True
            any_hard_failed = (
                any_hard_failed or check["severity"] == "hard")

    derived = "fail" if any_hard_failed else "warn" if any_failed else "pass"
    if declared != derived:
        raise ValueError(
            f"quality report.verdict is {declared!r}, but checks derive "
            f"{derived!r}")
    return derived


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

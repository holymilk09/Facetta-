"""Carat ↔ mm cross-validation via the density model (docs/SPEC_SCHEMA.md).

carat ≈ length × width × depth × SG × shape_factor / 200

SG (specific gravity) comes from the species registry and shape_factor from
the per-cut table, both in data/gemology_vocabulary.json. A spec whose claimed
carat deviates from the modeled carat by more than the tolerance is physically
impossible and must be rejected with a corrective suggestion.
"""

from __future__ import annotations

from dataclasses import dataclass

TOLERANCE = 0.12


@dataclass(frozen=True)
class DensityCheck:
    ok: bool
    expected_carat: float
    deviation: float
    expected_depth_mm: float
    message: str


def check_density(
    *,
    sg: float,
    shape_factor: float,
    length_mm: float,
    width_mm: float,
    depth_mm: float,
    carat: float,
    tolerance: float = TOLERANCE,
) -> DensityCheck:
    expected_carat = length_mm * width_mm * depth_mm * sg * shape_factor / 200
    deviation = (carat - expected_carat) / expected_carat
    # depth that would make the claimed carat physically consistent with L x W
    expected_depth_mm = carat * 200 / (length_mm * width_mm * sg * shape_factor)
    ok = abs(deviation) <= tolerance
    if ok:
        message = (
            f"carat {carat} is within {tolerance:.0%} of the modeled "
            f"{expected_carat:.2f} ct for {length_mm} x {width_mm} x {depth_mm} mm"
        )
    else:
        message = (
            f"carat {carat} deviates {deviation:+.0%} from the modeled "
            f"{expected_carat:.2f} ct for {length_mm} x {width_mm} x {depth_mm} mm; "
            f"expected about {expected_carat:.2f} ct at these dimensions, "
            f"or a depth of about {expected_depth_mm:.1f} mm at {carat} ct"
        )
    return DensityCheck(
        ok=ok,
        expected_carat=round(expected_carat, 3),
        deviation=round(deviation, 4),
        expected_depth_mm=round(expected_depth_mm, 2),
        message=message,
    )

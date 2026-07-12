"""Deterministic image-drift measurements with no provider dependency."""

from __future__ import annotations

import io

from PIL import Image


def outside_mask_drift(
    parent_bytes: bytes,
    child_bytes: bytes,
    mask_bytes: bytes,
) -> float:
    """Measure normalized grayscale change outside a white edit mask."""
    parent = Image.open(io.BytesIO(parent_bytes)).convert("L")
    child = Image.open(io.BytesIO(child_bytes)).convert("L")
    mask = Image.open(io.BytesIO(mask_bytes)).convert("L")
    if child.size != parent.size:
        child = child.resize(parent.size)
    if mask.size != parent.size:
        mask = mask.resize(parent.size)

    total = 0
    count = 0
    for parent_value, child_value, mask_value in zip(
        parent.tobytes(), child.tobytes(), mask.tobytes(), strict=True,
    ):
        if mask_value < 128:
            total += abs(parent_value - child_value)
            count += 1
    if count == 0:
        return 0.0
    return total / count / 255.0

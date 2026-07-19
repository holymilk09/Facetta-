"""Deterministic image-drift measurements with no provider dependency."""

from __future__ import annotations

import io
import math

from PIL import Image, UnidentifiedImageError


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


def inside_mask_effect(
    parent_bytes: bytes,
    child_bytes: bytes,
    mask_bytes: bytes,
) -> dict[str, object]:
    """Measure whether a masked candidate made a non-trivial visible change.

    The check is deliberately scoped to white mask pixels. Global appearance
    edits carry no mask and are unaffected. A few noisy pixels do not count as
    a completed local edit, while hue-only changes remain visible through RGB
    channel deltas even when luminance is nearly unchanged.
    """

    try:
        parent = Image.open(io.BytesIO(parent_bytes)).convert("RGB")
        child = Image.open(io.BytesIO(child_bytes)).convert("RGB")
        mask = Image.open(io.BytesIO(mask_bytes)).convert("L")
    except (OSError, UnidentifiedImageError, ValueError):
        return {"checked": False, "change_visible": False}
    if child.size != parent.size:
        child = child.resize(parent.size)
    if mask.size != parent.size:
        mask = mask.resize(parent.size)

    active_pixels = 0
    changed_pixels = 0
    total_channel_delta = 0
    for before, after, authorized in zip(
        parent.getdata(),
        child.getdata(),
        mask.getdata(),
        strict=True,
    ):
        if authorized < 128:
            continue
        active_pixels += 1
        channel_deltas = tuple(
            abs(before[index] - after[index]) for index in range(3)
        )
        total_channel_delta += sum(channel_deltas)
        if max(channel_deltas) >= 6:
            changed_pixels += 1
    if active_pixels == 0:
        return {"checked": False, "change_visible": False}

    changed_fraction = changed_pixels / active_pixels
    mean_absolute_delta = (
        total_channel_delta / active_pixels / 3 / 255.0
    )
    minimum_changed_pixels = max(4, math.ceil(active_pixels * 0.01))
    change_visible = (
        changed_pixels >= minimum_changed_pixels
        and mean_absolute_delta >= 0.001
    )
    return {
        "checked": True,
        "change_visible": change_visible,
        "active_pixels": active_pixels,
        "changed_pixels": changed_pixels,
        "changed_fraction": round(changed_fraction, 6),
        "mean_absolute_delta": round(mean_absolute_delta, 6),
        "minimum_changed_pixels": minimum_changed_pixels,
    }


def inside_mask_region_effects(
    parent_bytes: bytes,
    child_bytes: bytes,
    mask_bytes: bytes,
    *,
    expected_region_count: int | None = None,
) -> dict[str, object]:
    """Prove that every disconnected authorized region changed visibly.

    A union mask can otherwise hide an omitted annotation: one successful edit
    makes the aggregate :func:`inside_mask_effect` pass even when another
    designer-marked region is untouched.  The semantic markup compositor emits
    one filled component or local hotspot per mark, so connected components are
    the deterministic boundary available to QA without another model call.
    """

    try:
        parent = Image.open(io.BytesIO(parent_bytes)).convert("RGB")
        child = Image.open(io.BytesIO(child_bytes)).convert("RGB")
        mask = Image.open(io.BytesIO(mask_bytes)).convert("L")
    except (OSError, UnidentifiedImageError, ValueError):
        return {
            "checked": False,
            "every_region_changed": False,
            "region_count_matches": False,
        }
    if child.size != parent.size:
        child = child.resize(parent.size)
    if mask.size != parent.size:
        mask = mask.resize(parent.size)

    width, height = parent.size
    authorized = bytearray(value >= 128 for value in mask.tobytes())
    before_pixels = list(parent.get_flattened_data())
    after_pixels = list(child.get_flattened_data())
    components: list[list[int]] = []

    for start, enabled in enumerate(authorized):
        if not enabled:
            continue
        authorized[start] = 0
        stack = [start]
        component: list[int] = []
        while stack:
            index = stack.pop()
            component.append(index)
            x = index % width
            y = index // width
            for ny in range(max(0, y - 1), min(height, y + 2)):
                row = ny * width
                for nx in range(max(0, x - 1), min(width, x + 2)):
                    neighbor = row + nx
                    if authorized[neighbor]:
                        authorized[neighbor] = 0
                        stack.append(neighbor)
        if len(component) >= 4:
            components.append(component)
            if len(components) > 32:
                return {
                    "checked": False,
                    "every_region_changed": False,
                    "region_count_matches": False,
                    "reason": "authorization mask contains too many regions",
                    "region_count": len(components),
                }

    if not components:
        return {
            "checked": False,
            "every_region_changed": False,
            "region_count_matches": False,
            "region_count": 0,
        }

    regions: list[dict[str, object]] = []
    for component in components:
        changed_pixels = 0
        total_channel_delta = 0
        xs: list[int] = []
        ys: list[int] = []
        for index in component:
            before = before_pixels[index]
            after = after_pixels[index]
            channel_deltas = tuple(
                abs(before[channel] - after[channel]) for channel in range(3)
            )
            total_channel_delta += sum(channel_deltas)
            if max(channel_deltas) >= 6:
                changed_pixels += 1
            xs.append(index % width)
            ys.append(index // width)
        active_pixels = len(component)
        minimum_changed_pixels = max(4, math.ceil(active_pixels * 0.01))
        mean_absolute_delta = (
            total_channel_delta / active_pixels / 3 / 255.0
        )
        change_visible = (
            changed_pixels >= minimum_changed_pixels
            and mean_absolute_delta >= 0.001
        )
        regions.append({
            "bbox": [min(xs), min(ys), max(xs) + 1, max(ys) + 1],
            "active_pixels": active_pixels,
            "changed_pixels": changed_pixels,
            "changed_fraction": round(changed_pixels / active_pixels, 6),
            "mean_absolute_delta": round(mean_absolute_delta, 6),
            "minimum_changed_pixels": minimum_changed_pixels,
            "change_visible": change_visible,
        })

    regions.sort(key=lambda region: (region["bbox"][1], region["bbox"][0]))
    region_count = len(regions)
    count_matches = (
        expected_region_count is None or region_count == expected_region_count
    )
    return {
        "checked": True,
        "every_region_changed": (
            count_matches
            and all(bool(region["change_visible"]) for region in regions)
        ),
        "region_count_matches": count_matches,
        "expected_region_count": expected_region_count,
        "region_count": region_count,
        "regions": regions,
    }

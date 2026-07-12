"""Conservative deterministic localization for narrow jewelry edit domains."""

from __future__ import annotations

import io
import statistics
from dataclasses import dataclass

from PIL import Image, ImageChops, ImageFilter

from facetta.image_agent.contracts import (
    DesignerEditDomain,
    ImageAgentPlan,
    ImageOperation,
)
from facetta.json_types import JsonObject


@dataclass(frozen=True)
class AutomaticLocalization:
    mask_bytes: bytes
    provenance: str
    evidence: JsonObject


@dataclass(frozen=True)
class CenterAssemblyCrop:
    image_bytes: bytes
    evidence: JsonObject


def _png(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _edge_background(image: Image.Image) -> tuple[float, float, float]:
    edge = max(2, round(min(image.size) * 0.045))
    pixels = [
        image.getpixel((x, y))
        for y in range(image.height)
        for x in range(image.width)
        if (x < edge or x >= image.width - edge
            or y < edge or y >= image.height - edge)
    ]
    return tuple(
        float(statistics.median(channel))
        for channel in zip(*pixels, strict=True)
    )


def _bbox(points: list[tuple[int, int]]) -> tuple[int, int, int, int] | None:
    if not points:
        return None
    xs, ys = zip(*points, strict=True)
    return min(xs), min(ys), max(xs), max(ys)


def _odd(value: int) -> int:
    value = max(3, value)
    return value if value % 2 else value + 1


def crop_chromatic_center_assembly(
    source_bytes: bytes,
    *,
    analysis_edge: int = 384,
) -> CenterAssemblyCrop | None:
    """Focus a blind topology audit on a colored center and its prongs.

    Segmentation chooses only the crop; it never asserts a prong count. The
    generous perimeter retains the full crown/gallery so the independent
    vision counter sees less shank and background without losing topology.
    """
    try:
        original = Image.open(io.BytesIO(source_bytes)).convert("RGB")
    except Exception:
        return None
    if min(original.size) < 96:
        return None
    scale = min(1.0, analysis_edge / max(original.size))
    analysis = original.resize((
        max(96, round(original.width * scale)),
        max(96, round(original.height * scale)),
    ), Image.Resampling.LANCZOS)
    background = _edge_background(analysis)
    chromatic: list[tuple[int, int]] = []
    for y in range(analysis.height):
        for x in range(analysis.width):
            pixel = analysis.getpixel((x, y))
            saturation = max(pixel) - min(pixel)
            brightness = sum(pixel) / 3
            distance_sq = sum(
                (float(value) - background[index]) ** 2
                for index, value in enumerate(pixel)
            )
            if (
                analysis.width * 0.12 <= x <= analysis.width * 0.88
                and saturation >= 62
                and brightness <= 235
                and distance_sq > 34 * 34
            ):
                chromatic.append((x, y))
    stone = _bbox(chromatic)
    if stone is None:
        return None
    width = stone[2] - stone[0] + 1
    height = stone[3] - stone[1] + 1
    if (
        len(chromatic) < analysis.width * analysis.height * 0.006
        or width < analysis.width * 0.10
        or height < analysis.height * 0.08
    ):
        return None
    pad_x = max(round(width * 0.34), round(analysis.width * 0.035))
    pad_top = max(round(height * 0.34), round(analysis.height * 0.025))
    pad_bottom = max(round(height * 0.42), round(analysis.height * 0.04))
    box = (
        max(0, stone[0] - pad_x),
        max(0, stone[1] - pad_top),
        min(analysis.width, stone[2] + pad_x + 1),
        min(analysis.height, stone[3] + pad_bottom + 1),
    )
    crop_fraction = (
        (box[2] - box[0]) * (box[3] - box[1])
        / (analysis.width * analysis.height)
    )
    if not 0.04 <= crop_fraction <= 0.72:
        return None
    original_box = (
        max(0, round(box[0] / analysis.width * original.width)),
        max(0, round(box[1] / analysis.height * original.height)),
        min(original.width, round(box[2] / analysis.width * original.width)),
        min(original.height, round(box[3] / analysis.height * original.height)),
    )
    cropped = original.crop(original_box)
    return CenterAssemblyCrop(
        image_bytes=_png(cropped),
        evidence={
            "mode": "automatic_chromatic_center_assembly_v1",
            "source_size": [original.width, original.height],
            "crop_box": list(original_box),
            "crop_size": [cropped.width, cropped.height],
            "crop_fraction": round(crop_fraction, 6),
            "chromatic_center_pixels": len(chromatic),
        },
    )


def derive_ring_setting_mask(
    source_bytes: bytes,
    *,
    analysis_edge: int = 384,
) -> AutomaticLocalization | None:
    """Expose a colored solitaire's prong perimeter, not its stone center."""
    try:
        original = Image.open(io.BytesIO(source_bytes)).convert("RGB")
    except Exception:
        return None
    if min(original.size) < 96:
        return None
    scale = min(1.0, analysis_edge / max(original.size))
    analysis = original.resize((
        max(96, round(original.width * scale)),
        max(96, round(original.height * scale)),
    ), Image.Resampling.LANCZOS)
    background = _edge_background(analysis)
    chromatic: list[tuple[int, int]] = []
    for y in range(analysis.height):
        for x in range(analysis.width):
            pixel = analysis.getpixel((x, y))
            saturation = max(pixel) - min(pixel)
            brightness = sum(pixel) / 3
            distance_sq = sum(
                (float(value) - background[index]) ** 2
                for index, value in enumerate(pixel)
            )
            if (
                analysis.width * 0.12 <= x <= analysis.width * 0.88
                and saturation >= 62
                and brightness <= 235
                and distance_sq > 34 * 34
            ):
                chromatic.append((x, y))
    stone = _bbox(chromatic)
    if stone is None:
        return None
    width = stone[2] - stone[0] + 1
    height = stone[3] - stone[1] + 1
    if (
        len(chromatic) < analysis.width * analysis.height * 0.006
        or width < analysis.width * 0.10
        or height < analysis.height * 0.08
    ):
        return None
    center_x = (stone[0] + stone[2]) / 2
    center_y = (stone[1] + stone[3]) / 2
    outer_x = max(width * 0.66, analysis.width * 0.045)
    outer_y_top = max(height * 0.66, analysis.height * 0.04)
    outer_y_bottom = max(height * 0.78, analysis.height * 0.05)
    inner_x = max(width * 0.46, 3)
    inner_y = max(height * 0.46, 3)
    selected = Image.new("L", analysis.size, 0)
    pixels = selected.load()
    for y in range(analysis.height):
        outer_y = outer_y_bottom if y >= center_y else outer_y_top
        for x in range(analysis.width):
            outer = (
                ((x - center_x) / outer_x) ** 2
                + ((y - center_y) / outer_y) ** 2
            )
            inner = (
                ((x - center_x) / inner_x) ** 2
                + ((y - center_y) / inner_y) ** 2
            )
            if outer <= 1.0 and inner >= 1.0:
                pixels[x, y] = 255
    editable = sum(value >= 128 for value in selected.tobytes())
    fraction = editable / (analysis.width * analysis.height)
    if not 0.025 <= fraction <= 0.32:
        return None
    if selected.size != original.size:
        selected = selected.resize(original.size, Image.Resampling.NEAREST)
    return AutomaticLocalization(
        mask_bytes=_png(selected),
        provenance="automatic_chromatic_center_setting_v2",
        evidence={
            "mode": "automatic_chromatic_center_setting_v2",
            "editable_fraction": round(fraction, 6),
            "analysis_size": [analysis.width, analysis.height],
            "chromatic_center_box": [
                round(stone[0] / analysis.width, 6),
                round(stone[1] / analysis.height, 6),
                round(width / analysis.width, 6),
                round(height / analysis.height, 6),
            ],
            "stone_center_protected": True,
            "protected_stone_radius_fraction": 0.92,
            "outside_mask_pixel_lock": True,
        },
    )


def center_stone_footprint_evidence(
    source_bytes: bytes,
    candidate_bytes: bytes,
    *,
    analysis_edge: int = 384,
) -> JsonObject:
    """Compare a colored center's face-up envelope after a setting edit."""
    def envelope(content: bytes) -> tuple[float, float, float, float] | None:
        try:
            original = Image.open(io.BytesIO(content)).convert("RGB")
        except Exception:
            return None
        scale = min(1.0, analysis_edge / max(original.size))
        image = original.resize((
            max(96, round(original.width * scale)),
            max(96, round(original.height * scale)),
        ), Image.Resampling.LANCZOS)
        background = _edge_background(image)
        points: list[tuple[int, int]] = []
        for y in range(image.height):
            for x in range(image.width):
                pixel = image.getpixel((x, y))
                saturation = max(pixel) - min(pixel)
                brightness = sum(pixel) / 3
                distance_sq = sum(
                    (float(value) - background[index]) ** 2
                    for index, value in enumerate(pixel)
                )
                if (
                    image.width * 0.12 <= x <= image.width * 0.88
                    and saturation >= 62
                    and brightness <= 235
                    and distance_sq > 34 * 34
                ):
                    points.append((x, y))
        box = _bbox(points)
        if box is None or len(points) < image.width * image.height * 0.006:
            return None
        return (
            box[0] / image.width,
            box[1] / image.height,
            (box[2] - box[0] + 1) / image.width,
            (box[3] - box[1] + 1) / image.height,
        )

    source = envelope(source_bytes)
    candidate = envelope(candidate_bytes)
    if source is None or candidate is None or source[2] <= 0 or source[3] <= 0:
        return {"checked": False, "stable": False}
    width_ratio = candidate[2] / source[2]
    height_ratio = candidate[3] / source[3]
    source_center = (source[0] + source[2] / 2, source[1] + source[3] / 2)
    candidate_center = (
        candidate[0] + candidate[2] / 2,
        candidate[1] + candidate[3] / 2,
    )
    center_shift = (
        ((candidate_center[0] - source_center[0]) / source[2]) ** 2
        + ((candidate_center[1] - source_center[1]) / source[3]) ** 2
    ) ** 0.5
    stable = (
        0.94 <= width_ratio <= 1.06
        and 0.94 <= height_ratio <= 1.06
        and center_shift <= 0.06
    )
    return {
        "checked": True,
        "stable": stable,
        "source_box": [round(value, 6) for value in source],
        "candidate_box": [round(value, 6) for value in candidate],
        "width_ratio": round(width_ratio, 6),
        "height_ratio": round(height_ratio, 6),
        "center_shift": round(center_shift, 6),
        "width_ratio_range": [0.94, 1.06],
        "height_ratio_range": [0.94, 1.06],
        "maximum_center_shift": 0.06,
    }


def derive_ring_shank_mask(
    source_bytes: bytes,
    *,
    analysis_edge: int = 384,
) -> AutomaticLocalization | None:
    """Select a visible shank while protecting a chromatic center assembly.

    This deliberately declines colorless/ambiguous centers. A designer mask is
    safer than pretending a generic central rectangle understands the crown.
    White means editable and black means frozen.
    """

    try:
        original = Image.open(io.BytesIO(source_bytes)).convert("RGB")
    except Exception:
        return None
    if min(original.size) < 96:
        return None
    scale = min(1.0, analysis_edge / max(original.size))
    size = (
        max(96, round(original.width * scale)),
        max(96, round(original.height * scale)),
    )
    image = original.resize(size, Image.Resampling.LANCZOS)
    background = _edge_background(image)

    foreground: list[tuple[int, int]] = []
    chromatic: list[tuple[int, int]] = []
    center_left = round(image.width * 0.20)
    center_right = round(image.width * 0.80)
    for y in range(image.height):
        for x in range(image.width):
            pixel = image.getpixel((x, y))
            distance_sq = sum(
                (float(value) - background[index]) ** 2
                for index, value in enumerate(pixel)
            )
            if distance_sq > 28 * 28:
                foreground.append((x, y))
            saturation = max(pixel) - min(pixel)
            brightness = sum(pixel) / 3
            if (
                center_left <= x <= center_right
                and saturation >= 62
                and brightness <= 225
                and distance_sq > 34 * 34
            ):
                chromatic.append((x, y))

    foreground_bbox = _bbox(foreground)
    stone_bbox = _bbox(chromatic)
    if foreground_bbox is None or stone_bbox is None:
        return None
    fg_left, fg_top, fg_right, fg_bottom = foreground_bbox
    fg_width = fg_right - fg_left + 1
    fg_height = fg_bottom - fg_top + 1
    stone_width = stone_bbox[2] - stone_bbox[0] + 1
    stone_height = stone_bbox[3] - stone_bbox[1] + 1
    if (
        fg_width < image.width * 0.28
        or fg_height < image.height * 0.18
        or len(chromatic) < image.width * image.height * 0.008
        or stone_width < fg_width * 0.10
        or stone_height < fg_height * 0.16
    ):
        return None

    # Protect the stone plus the immediately touching prongs/basket. Expansion
    # is intentionally generous; a width edit owns the shank, not the crown.
    pad_x = max(round(stone_width * 0.24), round(fg_width * 0.045))
    pad_top = max(round(stone_height * 0.16), round(fg_height * 0.035))
    pad_bottom = max(round(stone_height * 0.25), round(fg_height * 0.06))
    protected = (
        max(0, stone_bbox[0] - pad_x),
        max(0, stone_bbox[1] - pad_top),
        min(image.width - 1, stone_bbox[2] + pad_x),
        min(image.height - 1, stone_bbox[3] + pad_bottom),
    )
    crown = Image.new("L", image.size, 0)
    crown_pixels = crown.load()
    for x, y in chromatic:
        crown_pixels[x, y] = 255
    crown_radius = max(
        round(stone_width * 0.14),
        round(fg_width * 0.025),
    )
    crown = crown.filter(ImageFilter.MaxFilter(_odd(crown_radius * 2 + 1)))
    # Protect every existing foreground component inside the conservative
    # center envelope as well. This captures low-saturation metal prongs that
    # chromatic stone segmentation cannot see, without reverting to a solid
    # rectangular cutout through the background.
    center_components = Image.new("L", image.size, 0)
    component_pixels = center_components.load()
    for x, y in foreground:
        if (
            protected[0] <= x <= protected[2]
            and protected[1] <= y <= protected[3]
        ):
            component_pixels[x, y] = 255
    center_components = center_components.filter(ImageFilter.MaxFilter(5))
    crown = ImageChops.lighter(crown, center_components)
    # The automatic slice is intentionally front-facing: select the upper
    # side runs that visibly pass behind/beside the center, never lower floor
    # reflections. Three-quarter/full-hoop views should use designer markup.
    corridor_top = max(
        fg_top,
        stone_bbox[1] - round(stone_height * 0.22),
    )
    corridor_bottom = min(
        fg_bottom,
        stone_bbox[1] + round(stone_height * 0.62),
    )

    selected = Image.new("L", image.size, 0)
    selected_pixels = selected.load()
    for x, y in foreground:
        if corridor_top <= y <= corridor_bottom:
            selected_pixels[x, y] = 255

    expansion = _odd(round(min(fg_width, fg_height) * 0.065))
    selected = selected.filter(ImageFilter.MaxFilter(expansion))
    # Never let dilation leak back through the shape-following protected crown.
    pixels = selected.load()
    crown_data = crown.load()
    for y in range(image.height):
        for x in range(image.width):
            if crown_data[x, y] >= 128:
                pixels[x, y] = 0

    selected_count = sum(value >= 128 for value in selected.tobytes())
    fraction = selected_count / (image.width * image.height)
    left_count = sum(
        selected.getpixel((x, y)) >= 128
        for y in range(image.height)
        for x in range(0, protected[0])
    )
    right_count = sum(
        selected.getpixel((x, y)) >= 128
        for y in range(image.height)
        for x in range(protected[2] + 1, image.width)
    )
    minimum_side = image.width * image.height * 0.008
    if not 0.025 <= fraction <= 0.46 or min(left_count, right_count) < minimum_side:
        return None

    if selected.size != original.size:
        selected = selected.resize(original.size, Image.Resampling.NEAREST)
    normalized = {
        "x": round(protected[0] / image.width, 6),
        "y": round(protected[1] / image.height, 6),
        "width": round((protected[2] - protected[0] + 1) / image.width, 6),
        "height": round((protected[3] - protected[1] + 1) / image.height, 6),
    }
    return AutomaticLocalization(
        mask_bytes=_png(selected),
        provenance="automatic_chromatic_center_shank_v3",
        evidence={
            "protected_center_box": normalized,
            "editable_fraction": round(fraction, 6),
            "chromatic_center_pixels": len(chromatic),
            "analysis_size": [image.width, image.height],
            "expansion_pixels": expansion,
            "protected_crown_expansion_pixels": crown_radius,
            "shank_corridor": {
                "y": round(corridor_top / image.height, 6),
                "height": round(
                    (corridor_bottom - corridor_top + 1) / image.height,
                    6,
                ),
            },
        },
    )


def derive_automatic_localization(
    plan: ImageAgentPlan,
    source_image: bytes | None,
) -> AutomaticLocalization | None:
    if (source_image is None
            or plan.operation is not ImageOperation.LOCAL_EDIT
            or plan.jewelry_type != "ring"):
        return None
    if plan.edit_domains == (DesignerEditDomain.SETTING,):
        source_groups = (plan.source_spec_facts or {}).get("side_stones", [])
        target_groups = plan.spec_facts.get("side_stones", [])
        if source_groups == [] and target_groups == []:
            return derive_ring_setting_mask(source_image)
        return None
    if DesignerEditDomain.BAND_GEOMETRY in plan.edit_domains:
        return derive_ring_shank_mask(source_image)
    return None

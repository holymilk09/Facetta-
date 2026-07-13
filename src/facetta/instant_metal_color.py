"""Deterministic, mask-bounded previews for controlled ring gold colors."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import json
import warnings

from PIL import Image, UnidentifiedImageError

from facetta.json_types import JsonObject


TRANSFORM_VERSION = "facetta.instant-gold-color.v1"
MAX_INSTANT_PIXELS = 16_777_216
MAX_INSTANT_EDGE = 8_192
_LUMA = (0.2126, 0.7152, 0.0722)
_TARGET_RGB: dict[str, tuple[int, int, int]] = {
    "yellow": (214, 171, 61),
    "white": (202, 210, 220),
    "rose": (211, 128, 108),
}


class InstantMetalColorError(ValueError):
    """The deterministic preview cannot safely satisfy its exact contract."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class InstantMetalColorResult:
    image_bytes: bytes
    source_sha256: str
    mask_sha256: str
    transform_contract: JsonObject
    transform_contract_sha256: str
    input_sha256: str
    output_sha256: str
    width: int
    height: int
    changed_inside_pixels: int
    max_luminance_delta: float


def transform_contract_sha256(payload: JsonObject) -> str:
    """Hash a transform contract using the canonical persisted encoding."""

    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def instant_input_sha256(
    source_sha256: str,
    mask_sha256: str,
    transform_sha256: str,
) -> str:
    """Bind the exact source, component mask, and transform contract."""

    return hashlib.sha256(
        source_sha256.encode("ascii")
        + b":"
        + mask_sha256.encode("ascii")
        + b":"
        + transform_sha256.encode("ascii")
    ).hexdigest()


def _validate_raster_size(size: tuple[int, int]) -> None:
    width, height = size
    if (
        width <= 0
        or height <= 0
        or width > MAX_INSTANT_EDGE
        or height > MAX_INSTANT_EDGE
        or width * height > MAX_INSTANT_PIXELS
    ):
        raise InstantMetalColorError(
            "instant_gold_color_raster_too_large",
            "the source image exceeds the released quick-preview raster limit",
        )


def _bounded_chroma(
    rgb: tuple[int, int, int], target: tuple[int, int, int]
) -> tuple[float, float, float]:
    source_luminance = sum(channel * weight for channel, weight in zip(rgb, _LUMA))
    target_luminance = sum(channel * weight for channel, weight in zip(target, _LUMA))
    chroma = tuple(channel - target_luminance for channel in target)
    scale = 1.0
    for delta in chroma:
        if delta > 0:
            scale = min(scale, (255.0 - source_luminance) / delta)
        elif delta < 0:
            scale = min(scale, source_luminance / -delta)
    scale = max(0.0, min(1.0, scale))
    return tuple(source_luminance + scale * delta for delta in chroma)


def transform_ring_gold_color(
    source_bytes: bytes,
    mask_bytes: bytes,
    *,
    controlled_color: str,
) -> InstantMetalColorResult:
    """Return a PNG whose decoded pixels differ only inside the supplied mask.

    The transform replaces chroma while preserving per-pixel Rec.709 luminance,
    alpha, raster dimensions, and every decoded pixel outside the exact mask.
    It intentionally has no provider, prompt, retry, or billing dependency.
    """

    target = _TARGET_RGB.get(controlled_color)
    if target is None:
        raise InstantMetalColorError(
            "instant_gold_color_unsupported",
            f"controlled gold color {controlled_color!r} is not released",
        )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(source_bytes)) as source_image:
                _validate_raster_size(source_image.size)
                orientation = source_image.getexif().get(274, 1)
                if orientation not in (None, 1):
                    raise InstantMetalColorError(
                        "instant_gold_color_orientation_unsupported",
                        "quick preview requires source pixels with normalized orientation",
                    )
                source_mode = source_image.mode
                source_had_alpha = (
                    "A" in source_image.getbands()
                    or "transparency" in source_image.info
                )
                source_icc = source_image.info.get("icc_profile")
                if source_icc is not None and source_mode not in {"RGB", "RGBA"}:
                    raise InstantMetalColorError(
                        "instant_gold_color_profile_unsupported",
                        "quick preview cannot safely preserve this source color profile",
                    )
                source_image.load()
                source = source_image.convert("RGBA")
            with Image.open(io.BytesIO(mask_bytes)) as mask_image:
                _validate_raster_size(mask_image.size)
                mask_image.load()
                mask = mask_image.convert("L")
    except InstantMetalColorError:
        raise
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
        OSError,
        ValueError,
    ) as exc:
        raise InstantMetalColorError(
            "instant_gold_color_raster_invalid",
            "the source image or exact component mask is not a readable raster",
        ) from exc
    if mask.size != source.size:
        raise InstantMetalColorError(
            "instant_gold_color_mask_mismatch",
            "the exact component mask does not match the source raster dimensions",
        )
    if mask.getbbox() is None:
        raise InstantMetalColorError(
            "instant_gold_color_mask_empty",
            "the exact component mask contains no editable pixels",
        )

    source_pixels = source.tobytes()
    mask_pixels = mask.tobytes()
    output_pixels = bytearray(source_pixels)
    changed = 0
    max_luminance_delta = 0.0
    for index, coverage in enumerate(mask_pixels):
        if coverage == 0:
            continue
        offset = index * 4
        red, green, blue, alpha = source_pixels[offset:offset + 4]
        if alpha == 0:
            continue
        recolored = _bounded_chroma((red, green, blue), target)
        mix = coverage / 255.0
        next_rgb = tuple(
            max(0, min(255, round(original + mix * (replacement - original))))
            for original, replacement in zip((red, green, blue), recolored)
        )
        next_pixel = bytes((*next_rgb, alpha))
        output_pixels[offset:offset + 4] = next_pixel
        if next_pixel != source_pixels[offset:offset + 4]:
            changed += 1
        before_luminance = red * _LUMA[0] + green * _LUMA[1] + blue * _LUMA[2]
        after_luminance = sum(
            channel * weight for channel, weight in zip(next_rgb, _LUMA)
        )
        max_luminance_delta = max(
            max_luminance_delta,
            abs(before_luminance - after_luminance),
        )
    if changed == 0:
        raise InstantMetalColorError(
            "instant_gold_color_no_visible_change",
            "the requested controlled color produced no visible masked change",
        )

    output = Image.frombytes("RGBA", source.size, bytes(output_pixels))
    encoded = io.BytesIO()
    save_options = {
        "format": "PNG",
        "optimize": False,
        **({"icc_profile": source_icc} if source_icc is not None else {}),
    }
    if source_had_alpha:
        output.save(encoded, **save_options)
    else:
        output.convert("RGB").save(encoded, **save_options)
    image_bytes = encoded.getvalue()

    # Re-open the encoded artifact and verify the invariants against the bytes
    # that review and Apply will actually consume.
    with Image.open(io.BytesIO(image_bytes)) as verified_image:
        verified = verified_image.convert("RGBA")
        verified.load()
    verified_pixels = verified.tobytes()
    if verified.size != source.size:
        raise InstantMetalColorError(
            "instant_gold_color_verification_failed",
            "the preview raster dimensions changed during encoding",
        )
    if any(
        verified_pixels[index * 4:(index + 1) * 4]
        != source_pixels[index * 4:(index + 1) * 4]
        for index, coverage in enumerate(mask_pixels)
        if coverage == 0
    ):
        raise InstantMetalColorError(
            "instant_gold_color_verification_failed",
            "pixels outside the exact component mask changed",
        )
    if any(
        verified_pixels[index] != source_pixels[index]
        for index in range(3, len(source_pixels), 4)
    ):
        raise InstantMetalColorError(
            "instant_gold_color_verification_failed",
            "source transparency changed during the preview transform",
        )

    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    mask_sha256 = hashlib.sha256(mask_bytes).hexdigest()
    transform_contract: JsonObject = {
        "version": TRANSFORM_VERSION,
        "operation": "masked_gold_color_chroma_transform",
        "controlled_color": controlled_color,
        "target_rgb": list(target),
        "luminance_model": "rec709",
        "preserves": [
            "raster_dimensions",
            "source_alpha",
            "per_pixel_luminance",
            "outside_mask_decoded_pixels",
        ],
        "mask_blend": "coverage",
        "gamut_policy": "bounded_chroma",
    }
    transform_hash = transform_contract_sha256(transform_contract)
    input_sha256 = instant_input_sha256(
        source_sha256,
        mask_sha256,
        transform_hash,
    )
    return InstantMetalColorResult(
        image_bytes=image_bytes,
        source_sha256=source_sha256,
        mask_sha256=mask_sha256,
        transform_contract=transform_contract,
        transform_contract_sha256=transform_hash,
        input_sha256=input_sha256,
        output_sha256=hashlib.sha256(image_bytes).hexdigest(),
        width=source.width,
        height=source.height,
        changed_inside_pixels=changed,
        max_luminance_delta=round(max_luminance_delta, 6),
    )

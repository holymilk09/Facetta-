from __future__ import annotations

import io

from PIL import Image, ImageDraw

from facetta.image_agent.band_drift import band_width_change_evidence


def _ring(stroke: int) -> bytes:
    image = Image.new("RGB", (256, 256), (200, 212, 226))
    draw = ImageDraw.Draw(image)
    draw.ellipse((55, 35, 205, 225), outline=(80, 85, 90), width=stroke)
    draw.ellipse((105, 20, 155, 70), fill=(30, 50, 180))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_visible_widening_is_detected_without_claiming_millimeters():
    evidence = band_width_change_evidence(
        _ring(10), _ring(14), before_mm=3.2, after_mm=3.8)
    assert evidence["checked"] is True
    assert evidence["change_visible"] is True
    assert evidence["direction"] == "widen"
    assert evidence["foreground_median_width_ratio"] > 1.08
    assert evidence["framing_stable"] is True


def test_unchanged_silhouette_does_not_satisfy_requested_delta():
    evidence = band_width_change_evidence(
        _ring(10), _ring(10), before_mm=3.2, after_mm=3.8)
    assert evidence["checked"] is True
    assert evidence["change_visible"] is False
    assert evidence["foreground_median_width_ratio"] == 1.0


def test_visible_narrowing_is_detected_symmetrically():
    evidence = band_width_change_evidence(
        _ring(14), _ring(10), before_mm=3.8, after_mm=3.2)
    assert evidence["change_visible"] is True
    assert evidence["direction"] == "narrow"
    assert evidence["foreground_median_width_ratio"] < 0.92


def test_reframed_ring_cannot_masquerade_as_a_width_change():
    source = _ring(10)
    image = Image.open(io.BytesIO(_ring(16))).convert("RGB")
    reframed = Image.new("RGB", (256, 256), (200, 212, 226))
    reframed.paste(image.resize((190, 190)), (45, 5))
    output = io.BytesIO()
    reframed.save(output, format="PNG")

    evidence = band_width_change_evidence(
        source, output.getvalue(), before_mm=3.2, after_mm=3.8)

    assert evidence["checked"] is True
    assert evidence["framing_stable"] is False
    assert evidence["change_visible"] is False


def test_stable_partial_visual_widening_is_reviewable_not_exact_mm_proof():
    source = _ring(10)
    candidate = _ring(12)
    evidence = band_width_change_evidence(
        source, candidate, before_mm=3.2, after_mm=3.8)
    assert evidence["framing_stable"] is True
    assert evidence["change_visible"] is True
    assert evidence["foreground_median_width_ratio"] > 1.08
    assert evidence["target_relative_change"] == 0.1875

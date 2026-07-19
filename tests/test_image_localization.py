"""Automatic localization is deterministic and declines ambiguous jewelry."""

from __future__ import annotations

import io

import pytest
from PIL import Image, ImageDraw

from facetta.image_agent import (
    CheckSeverity,
    ImageOperation,
    ImageQualityReport,
    ImageRoute,
    JewelryImageAgent,
    ProviderImage,
    QualityCheck,
    QualityVerdict,
    build_image_plan,
)
from facetta.image_agent.localization import (
    crop_chromatic_center_assembly,
    center_stone_footprint_evidence,
    derive_ring_setting_mask,
    derive_ring_shank_mask,
)
from facetta.image_agent.drift import inside_mask_region_effects
from facetta.ring_evals import (
    CANONICAL_RING_EDITS,
    RING_GOLDEN_CASES,
    apply_canonical_ring_edit,
    build_ring_golden_spec,
)


def _ring(*, stone_color: tuple[int, int, int]) -> bytes:
    image = Image.new("RGB", (320, 280), (246, 246, 244))
    draw = ImageDraw.Draw(image)
    draw.ellipse((30, 72, 290, 242), outline=(112, 116, 120), width=22)
    draw.ellipse((116, 34, 204, 178), fill=stone_color)
    for box in ((108, 62, 126, 86), (194, 62, 212, 86),
                (108, 146, 126, 170), (194, 146, 212, 170)):
        draw.ellipse(box, fill=(150, 154, 158))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _band_specs():
    case = next(
        case for case in RING_GOLDEN_CASES
        if case.id == "oval-solitaire-white-6-wide"
    )
    edit = next(
        edit for edit in CANONICAL_RING_EDITS if edit.id == "band-width"
    )
    source = build_ring_golden_spec(case)
    target, issues = apply_canonical_ring_edit(source, edit)
    assert target is not None, issues
    return source, target


def test_chromatic_center_produces_symmetric_shank_mask():
    localized = derive_ring_shank_mask(_ring(stone_color=(20, 50, 190)))
    assert localized is not None
    mask = Image.open(io.BytesIO(localized.mask_bytes)).convert("L")

    assert mask.getpixel((160, 105)) == 0  # center stone / crown protected
    assert mask.getpixel((117, 74)) == 0  # left setting prong protected
    assert mask.getpixel((203, 74)) == 0  # right setting prong protected
    assert mask.getpixel((55, 105)) == 255  # left shank selected
    assert mask.getpixel((265, 105)) == 255  # right shank selected
    assert mask.getpixel((55, 230)) == 0  # lower reflection/hoop is not guessed
    assert mask.getpixel((5, 5)) == 0  # remote background frozen
    assert localized.provenance == "automatic_chromatic_center_shank_v3"
    assert localized.evidence["editable_fraction"] < 0.46


def test_colorless_or_low_saturation_center_declines_automatic_guess():
    assert derive_ring_shank_mask(
        _ring(stone_color=(185, 190, 195))
    ) is None


def test_chromatic_center_crop_retains_prong_perimeter_and_removes_shank():
    focused = crop_chromatic_center_assembly(
        _ring(stone_color=(20, 50, 190)))
    assert focused is not None
    crop = Image.open(io.BytesIO(focused.image_bytes)).convert("RGB")

    assert crop.width < 320
    assert crop.height < 280
    assert focused.evidence["mode"] == (
        "automatic_chromatic_center_assembly_v1")
    left, top, right, bottom = focused.evidence["crop_box"]
    assert left <= 108 and right >= 212
    assert top <= 34 and bottom >= 178


def test_setting_mask_exposes_prongs_but_freezes_stone_center_and_shank():
    localized = derive_ring_setting_mask(
        _ring(stone_color=(20, 50, 190)))
    assert localized is not None
    mask = Image.open(io.BytesIO(localized.mask_bytes)).convert("L")

    assert mask.getpixel((160, 105)) == 0
    assert mask.getpixel((117, 74)) == 255
    assert mask.getpixel((203, 74)) == 255
    assert mask.getpixel((55, 105)) == 0
    assert mask.getpixel((5, 5)) == 0
    assert localized.provenance == "automatic_chromatic_center_setting_v2"
    assert localized.evidence["outside_mask_pixel_lock"] is True


def test_center_stone_footprint_detects_setting_edit_redesign():
    source = _ring(stone_color=(20, 50, 190))
    changed = Image.open(io.BytesIO(source)).convert("RGB")
    draw = ImageDraw.Draw(changed)
    draw.ellipse((128, 42, 192, 188), fill=(20, 50, 190))
    output = io.BytesIO()
    changed.save(output, format="PNG")

    unchanged = center_stone_footprint_evidence(source, source)
    drifted = center_stone_footprint_evidence(source, output.getvalue())

    assert unchanged["stable"] is True
    assert drifted["checked"] is True
    assert drifted["stable"] is False


@pytest.mark.parametrize("modern_pillow_api", [True, False])
def test_every_disconnected_marked_region_must_change_visibly(
    monkeypatch,
    modern_pillow_api,
):
    if not modern_pillow_api:
        monkeypatch.setattr(
            Image.Image,
            "get_flattened_data",
            None,
            raising=False,
        )
    source = Image.new("RGB", (80, 40), (240, 240, 240))
    candidate = source.copy()
    candidate_draw = ImageDraw.Draw(candidate)
    candidate_draw.rectangle((5, 5, 24, 24), fill=(120, 170, 220))
    mask = Image.new("L", source.size, 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rectangle((5, 5, 24, 24), fill=255)
    mask_draw.rectangle((55, 5, 74, 24), fill=255)

    def encoded(image: Image.Image) -> bytes:
        output = io.BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()

    incomplete = inside_mask_region_effects(
        encoded(source),
        encoded(candidate),
        encoded(mask),
        expected_region_count=2,
    )
    assert incomplete["checked"] is True
    assert incomplete["region_count"] == 2
    assert incomplete["region_count_matches"] is True
    assert incomplete["every_region_changed"] is False
    assert [region["change_visible"] for region in incomplete["regions"]] == [
        True,
        False,
    ]

    candidate_draw.rectangle((55, 5, 74, 24), fill=(220, 160, 120))
    complete = inside_mask_region_effects(
        encoded(source),
        encoded(candidate),
        encoded(mask),
        expected_region_count=2,
    )
    assert complete["every_region_changed"] is True


class _Provider:
    def __init__(self) -> None:
        self.calls = []

    def execute(self, plan, route, prompt, *, source_image, mask_bytes):
        self.calls.append((plan, route, prompt, source_image, mask_bytes))
        return ProviderImage(image_bytes=b"candidate")


class _PassEvaluator:
    def evaluate(self, plan, candidate, *, source_image, mask_bytes):
        assert candidate == b"candidate"
        assert source_image is not None
        assert mask_bytes is not None
        return ImageQualityReport(
            verdict=QualityVerdict.PASS,
            checks=(QualityCheck(
                code="test",
                passed=True,
                severity=CheckSeverity.HARD,
                message="localized",
            ),),
            score=100,
        )


def test_agent_binds_automatic_mask_hash_and_provenance_before_execution():
    source_spec, target_spec = _band_specs()
    source_image = _ring(stone_color=(20, 50, 190))
    plan = build_image_plan(
        ImageOperation.LOCAL_EDIT,
        "increase the lower shank from 3.2 mm to 3.8 mm",
        spec=target_spec,
        source_spec=source_spec,
        source_image=source_image,
        region_description="the lower shank",
    )
    provider = _Provider()

    result = JewelryImageAgent(
        provider,
        _PassEvaluator(),
        attempt_routes=(ImageRoute.GROK_EDIT,),
    ).run(plan, source_image=source_image)

    executed_plan, _, _, _, mask = provider.calls[0]
    assert mask is not None
    assert executed_plan.mask_hash is not None
    assert result.plan.mask_hash == executed_plan.mask_hash
    localization = result.plan.normalized_intent["localization"]
    assert localization["mode"] == "automatic_chromatic_center_shank_v3"
    assert localization["mask_hash"] == result.plan.mask_hash
    assert result.plan.input_hash != plan.input_hash


def test_caller_mask_provenance_is_hashed_into_the_normalized_plan():
    source_spec, target_spec = _band_specs()
    source_image = _ring(stone_color=(20, 50, 190))
    mask = derive_ring_shank_mask(source_image)
    assert mask is not None

    plan = build_image_plan(
        ImageOperation.LOCAL_EDIT,
        "widen only the marked shank",
        spec=target_spec,
        source_spec=source_spec,
        source_image=source_image,
        mask_bytes=mask.mask_bytes,
        mask_provenance="persisted_designer_markup",
        region_description="the designer-marked shank",
    )

    localization = plan.normalized_intent["localization"]
    assert localization == {
        "mode": "persisted_designer_markup",
        "mask_hash": plan.mask_hash,
    }

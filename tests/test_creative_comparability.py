"""Request-level presentation comparability is strict but design-neutral."""

import hashlib
import io

import pytest
from PIL import Image, ImageDraw

from facetta import creative_comparability as comparability
from facetta.creative_comparability import (
    MainViewComparabilityAudit,
    PresentationNormalizationError,
    PresentationSubjectBounds,
)


def _studio_ring(
    bounds: tuple[int, int, int, int],
    *,
    size: tuple[int, int] = (256, 256),
) -> bytes:
    image = Image.new("RGB", size, (246, 242, 234))
    draw = ImageDraw.Draw(image)
    draw.ellipse(bounds, outline=(155, 105, 28), width=14)
    left, top, right, _bottom = bounds
    center_x = (left + right) // 2
    stone_y = top + 18
    for offset, radius in ((-28, 12), (0, 17), (28, 12)):
        draw.ellipse(
            (
                center_x + offset - radius,
                stone_y - radius,
                center_x + offset + radius,
                stone_y + radius,
            ),
            fill=(204, 224, 235),
            outline=(105, 72, 24),
            width=4,
        )
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_main_view_audit_uses_design_neutral_pair_contract(monkeypatch):
    observed: dict[str, object] = {}

    def inspect(system: str, first: bytes, second: bytes, user: str) -> dict:
        observed.update({
            "system": system,
            "first": first,
            "second": second,
            "user": user,
        })
        return {
            "first_complete_piece_visible": True,
            "second_complete_piece_visible": True,
            "camera_view_matches": True,
            "camera_elevation_matches": True,
            "image_plane_rotation_matches": True,
            "crop_and_frame_fill_match": True,
            "review_scale_matches": True,
            "background_family_matches": True,
            "comparable": True,
            "differences": [],
            "score": 96,
            "notes": ["same camera and review scale"],
        }

    monkeypatch.setattr(comparability, "configured_vision_json_pair", inspect)
    audit = comparability.inspect_main_view_comparability(b"first", b"second")

    assert audit.passed is True
    assert observed["first"] == b"first"
    assert observed["second"] == b"second"
    assert observed["user"] == comparability.MAIN_VIEW_CONTRACT
    assert "designs are expected\nto differ" in str(observed["system"])
    assert "Do not compare stone count" in str(observed["system"])


def test_main_view_audit_fails_closed_on_unknown_or_mismatched_evidence():
    unknown = MainViewComparabilityAudit(
        first_complete_piece_visible=True,
        second_complete_piece_visible=True,
        camera_view_matches=True,
        camera_elevation_matches=None,
        image_plane_rotation_matches=True,
        crop_and_frame_fill_match=True,
        review_scale_matches=True,
        background_family_matches=True,
        comparable=True,
    )
    mismatch = unknown.model_copy(update={
        "camera_elevation_matches": False,
        "comparable": False,
    })

    assert unknown.passed is False
    assert mismatch.passed is False


def test_framing_only_mismatch_requires_every_nonframing_field_to_pass():
    framing_only = MainViewComparabilityAudit(
        first_complete_piece_visible=True,
        second_complete_piece_visible=True,
        camera_view_matches=True,
        camera_elevation_matches=True,
        image_plane_rotation_matches=True,
        crop_and_frame_fill_match=False,
        review_scale_matches=False,
        background_family_matches=True,
        comparable=False,
    )
    unknown_camera = framing_only.model_copy(update={
        "camera_view_matches": None,
    })

    assert framing_only.framing_only_mismatch is True
    assert unknown_camera.framing_only_mismatch is False


def test_bounded_adjudication_promotes_two_framing_only_exact_pair_votes():
    first = b"immutable reference pixels"
    second = b"immutable candidate pixels"
    camera_claim = MainViewComparabilityAudit(
        first_complete_piece_visible=True,
        second_complete_piece_visible=True,
        camera_view_matches=False,
        camera_elevation_matches=True,
        image_plane_rotation_matches=True,
        crop_and_frame_fill_match=False,
        review_scale_matches=False,
        background_family_matches=True,
        comparable=False,
    )
    framing_only = camera_claim.model_copy(update={
        "camera_view_matches": True,
        "differences": ("candidate is smaller in the frame",),
    })
    challenges = iter((framing_only, framing_only))

    decision = comparability.adjudicate_main_view_comparability(
        first,
        second,
        inspect=lambda _first, _second: next(challenges),
        initial_audit=camera_claim,
    )

    assert decision.disposition == "framing_only_consensus"
    assert decision.audit.framing_only_mismatch is True
    assert len(decision.observations) == 3
    evidence = decision.evidence()
    assert evidence["reference_sha256"] == hashlib.sha256(first).hexdigest()
    assert evidence["candidate_sha256"] == hashlib.sha256(second).hexdigest()
    assert evidence["observation_count"] == 3


def test_bounded_adjudication_marks_camera_disagreement_uncertain():
    camera_claim = MainViewComparabilityAudit(
        first_complete_piece_visible=True,
        second_complete_piece_visible=True,
        camera_view_matches=False,
        camera_elevation_matches=True,
        image_plane_rotation_matches=True,
        crop_and_frame_fill_match=False,
        review_scale_matches=False,
        background_family_matches=True,
        comparable=False,
    )
    framing_only = camera_claim.model_copy(update={
        "camera_view_matches": True,
    })
    challenges = iter((framing_only, camera_claim))

    decision = comparability.adjudicate_main_view_comparability(
        b"reference",
        b"candidate",
        inspect=lambda _first, _second: next(challenges),
        initial_audit=camera_claim,
    )

    assert decision.uncertain is True
    assert decision.disposition == "uncertain_disagreement"


def test_bounded_adjudication_authorizes_only_unanimous_camera_repair():
    mismatch = MainViewComparabilityAudit(
        first_complete_piece_visible=True,
        second_complete_piece_visible=True,
        camera_view_matches=False,
        camera_elevation_matches=False,
        image_plane_rotation_matches=True,
        crop_and_frame_fill_match=False,
        review_scale_matches=False,
        background_family_matches=True,
        comparable=False,
    )

    decision = comparability.adjudicate_main_view_comparability(
        b"reference",
        b"candidate",
        inspect=lambda _first, _second: mismatch,
        initial_audit=mismatch,
    )

    assert decision.disposition == "unanimous_non_framing_mismatch"
    assert decision.uncertain is False
    assert decision.audit is mismatch


def test_presentation_normalization_is_deterministic_and_affine_only():
    reference = _studio_ring((32, 70, 224, 180))
    candidate = _studio_ring((58, 100, 198, 182))

    first, first_evidence = comparability.normalize_main_view_presentation(
        reference,
        candidate,
    )
    second, second_evidence = comparability.normalize_main_view_presentation(
        reference,
        candidate,
    )

    assert first == second
    assert hashlib.sha256(first).hexdigest() == first_evidence["output_sha256"]
    assert first_evidence == second_evidence
    assert first_evidence["provider_calls"] == 0
    assert first_evidence["generative_model_used"] is False
    assert first_evidence["source_pixels_resampled"] is True
    assert first_evidence["new_jewelry_content_created"] is False
    source_bounds = first_evidence["source_bounds"]
    normalized_bounds = first_evidence["normalized_bounds"]
    reference_bounds = first_evidence["reference_bounds"]
    assert source_bounds["longest_fill"] < reference_bounds["longest_fill"]
    assert normalized_bounds["longest_fill"] == pytest.approx(
        reference_bounds["longest_fill"],
        abs=0.035,
    )
    assert normalized_bounds["center_x"] == pytest.approx(
        reference_bounds["center_x"],
        abs=0.035,
    )
    assert normalized_bounds["center_y"] == pytest.approx(
        reference_bounds["center_y"],
        abs=0.035,
    )
    # Solid source interiors remain the same source colors. The transform may
    # interpolate edges, but it cannot introduce a new jewelry design layer.
    normalized = Image.open(io.BytesIO(first)).convert("RGB")
    colors = normalized.getcolors(maxcolors=normalized.width * normalized.height)
    assert colors is not None
    palette = {color for _count, color in colors}
    assert (155, 105, 28) in palette
    assert (204, 224, 235) in palette


def test_reference_frame_accepts_measured_84375_percent_cached_boundary(
    monkeypatch,
):
    """A conservative cached bound 0.00375 above the old ceiling is valid."""

    reference = _studio_ring((20, 79, 236, 194))
    candidate = _studio_ring((22, 88, 234, 188))
    measured_reference = PresentationSubjectBounds(
        left=20,
        top=79,
        right=236,
        bottom=194,
        canvas_width=256,
        canvas_height=256,
        center_x=0.5,
        center_y=0.533203,
        longest_fill=0.84375,
        foreground_fraction=0.275269,
        background_rgb=(252, 246, 242),
        threshold=18,
        segmentation_mode="edge_background_rgb",
    )
    measured_candidate = PresentationSubjectBounds(
        left=22,
        top=88,
        right=234,
        bottom=188,
        canvas_width=256,
        canvas_height=256,
        center_x=0.5,
        center_y=0.539062,
        longest_fill=0.828125,
        foreground_fraction=0.231522,
        background_rgb=(251, 247, 243),
        threshold=18,
        segmentation_mode="edge_background_rgb",
    )
    normalized_bounds = measured_reference.model_copy(update={
        "center_y": measured_reference.center_y,
    })
    bounds = iter((
        measured_reference,
        measured_candidate,
        normalized_bounds,
    ))
    monkeypatch.setattr(
        comparability,
        "detect_presentation_subject_bounds",
        lambda _image: next(bounds),
    )

    normalized, evidence = comparability.normalize_main_view_presentation(
        reference,
        candidate,
    )

    assert normalized
    assert evidence["reference_bounds"]["longest_fill"] == 0.84375
    assert evidence["source_bounds"]["longest_fill"] == 0.828125
    assert evidence["forward_scale"] == pytest.approx(
        0.84375 / 0.828125,
        abs=1e-8,
    )


def test_presentation_normalization_fails_closed_on_ambiguous_background():
    reference = _studio_ring((32, 70, 224, 180))
    ambiguous = Image.new("RGB", (256, 256))
    draw = ImageDraw.Draw(ambiguous)
    for y in range(0, 256, 16):
        for x in range(0, 256, 16):
            color = (245, 245, 245) if (x + y) // 16 % 2 else (80, 80, 80)
            draw.rectangle((x, y, x + 15, y + 15), fill=color)
    output = io.BytesIO()
    ambiguous.save(output, format="PNG")

    with pytest.raises(PresentationNormalizationError) as caught:
        comparability.normalize_main_view_presentation(
            reference,
            output.getvalue(),
        )

    assert caught.value.code in {
        "presentation_background_ambiguous",
        "presentation_subject_edge_clipped",
    }


def test_presentation_normalization_preserves_meaningful_alpha():
    def transparent_ring(bounds: tuple[int, int, int, int]) -> bytes:
        image = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.ellipse(bounds, outline=(170, 118, 34, 255), width=16)
        output = io.BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()

    reference = transparent_ring((32, 32, 224, 224))
    candidate = transparent_ring((62, 76, 194, 208))
    normalized, evidence = comparability.normalize_main_view_presentation(
        reference,
        candidate,
    )

    output = Image.open(io.BytesIO(normalized))
    assert output.mode == "RGBA"
    assert output.getchannel("A").getextrema() == (0, 255)
    assert evidence["source_bounds"]["segmentation_mode"] == "alpha"
    assert evidence["normalized_bounds"]["segmentation_mode"] == "alpha"


def test_presentation_normalization_retains_disconnected_pair_envelope():
    def earrings(*, offset_y: int, radius: int, spacing: int) -> bytes:
        image = Image.new("RGB", (256, 256), (246, 242, 234))
        draw = ImageDraw.Draw(image)
        for center_x in (128 - spacing, 128 + spacing):
            draw.ellipse(
                (
                    center_x - radius,
                    offset_y - radius,
                    center_x + radius,
                    offset_y + radius,
                ),
                fill=(100, 65, 26),
            )
        output = io.BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()

    reference = earrings(offset_y=128, radius=42, spacing=54)
    candidate = earrings(offset_y=150, radius=30, spacing=39)
    normalized, evidence = comparability.normalize_main_view_presentation(
        reference,
        candidate,
    )

    normalized_bounds = evidence["normalized_bounds"]
    reference_bounds = evidence["reference_bounds"]
    assert normalized_bounds["longest_fill"] == pytest.approx(
        reference_bounds["longest_fill"],
        abs=0.035,
    )
    # Both disconnected foreground components remain visible after a single
    # whole-raster affine transform; no component-specific compositing occurs.
    image = Image.open(io.BytesIO(normalized)).convert("RGB")
    left = image.crop((0, 0, 128, 256))
    right = image.crop((128, 0, 256, 256))
    background = (246, 242, 234)
    assert any(pixel != background for pixel in left.getdata())
    assert any(pixel != background for pixel in right.getdata())


def test_main_view_repair_instruction_is_numeric_and_design_preserving():
    audit = MainViewComparabilityAudit(
        first_complete_piece_visible=True,
        second_complete_piece_visible=True,
        camera_view_matches=False,
        camera_elevation_matches=False,
        image_plane_rotation_matches=True,
        crop_and_frame_fill_match=False,
        review_scale_matches=False,
        background_family_matches=True,
        comparable=False,
        differences=("Second direction is lower and fills more of the frame",),
        score=38,
    )

    instruction = comparability.compile_main_view_repair_instruction(
        "A yellow-gold ring with exactly three round diamonds.",
        audit=audit,
        reference_direction=1,
        candidate_direction=2,
    )

    assert comparability.MAIN_VIEW_REPAIR_CONTRACT in instruction
    assert "azimuth to 0 degrees" in instruction
    assert "elevation to 25 degrees" in instruction
    assert "75 percent" in instruction
    assert "lower and fills more" in instruction
    assert "do not add, remove, or substitute components" in instruction

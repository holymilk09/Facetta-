from __future__ import annotations

import pytest

from facetta.presentation import (
    PresentationScopeError,
    compile_product_photo_brief,
)


def test_catalog_brief_is_designer_facing_and_freezes_product_identity():
    brief = compile_product_photo_brief(
        "catalog_white",
        "portrait",
        "Softer shadow and slightly more breathing room.",
    )
    assert "ecommerce catalog" in brief.intent
    assert "Designer presentation direction" in brief.intent
    assert any("4:5" in rule for rule in brief.style_constraints)
    assert "jewelry unchanged" in brief.expected_output


def test_product_photo_rejects_physical_design_mutation():
    with pytest.raises(PresentationScopeError, match="confirmed design revision"):
        compile_product_photo_brief(
            "luxury_studio",
            custom_instruction="Smooth the Art Deco shank and remove the side stones.",
        )


def test_product_photo_allows_material_appearance_direction_without_mutation():
    brief = compile_product_photo_brief(
        "dark_editorial",
        custom_instruction="Keep the yellow gold reflections readable in the shadows.",
    )
    assert "yellow gold reflections" in brief.intent

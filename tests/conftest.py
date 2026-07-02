import copy

import pytest

from facetta.vocabulary import get_vocabulary

# The exact example spec from docs/SPEC_SCHEMA.md
EXAMPLE_SPEC = {
    "schema_version": 1,
    "design_id": "dsn_8Kx2",
    "version": 3,
    "created_by": "usr_ana",
    "created_at": "2026-07-02T18:40:00Z",
    "jewelry_type": "ring",
    "template": "solitaire_prong",
    "mode": "pro",
    "stone": {
        "species": "sapphire",
        "cut": "oval_brilliant",
        "carat": 2.0,
        "dimensions_mm": {"length": 8.6, "width": 6.4, "depth": 4.1},
        "color": {
            "trade": "Royal Blue",
            "gia": "vivid violetish blue, tone 6, saturation 6",
            "hue_code": "vB", "tone": 6, "saturation": 6,
        },
        "clarity": {"system": "gia_type_ii", "grade": "VS", "eye_clean": True},
        "origin": "Sri Lanka",
        "treatment": "heated",
        "phenomena": [],
    },
    "setting": {
        "style": "4_prong_basket",
        "prong_count": 4,
        "prong_tip_mm": 0.9,
        "gallery_height_mm": 4.5,
    },
    "metal": {"material": "gold", "karat": 18, "color": "yellow", "finish": "high_polish"},
    "band": {"profile": "half_round", "width_mm": 1.8, "thickness_mm": 1.6},
    "ring_size": {"system": "US", "value": 6.5, "inner_diameter_mm": 16.9},
    "side_stones": [],
    "notes_to_factory": "Slightly higher gallery to clear a future wedding band.",
}


# A 1.00 ct round-brilliant diamond variant of the example (the classic bench stone)
ROUND_SPEC = copy.deepcopy(EXAMPLE_SPEC)
ROUND_SPEC["stone"] = {
    "species": "diamond",
    "cut": "round_brilliant",
    "carat": 1.0,
    "dimensions_mm": {"length": 6.5, "width": 6.5, "depth": 3.9},
    "color": {"trade": "D", "gia": "colorless"},
    "clarity": {"system": "gia_diamond", "grade": "VS1", "eye_clean": True},
    "phenomena": [],
}


@pytest.fixture
def example_spec() -> dict:
    return copy.deepcopy(EXAMPLE_SPEC)


@pytest.fixture
def round_spec() -> dict:
    return copy.deepcopy(ROUND_SPEC)


@pytest.fixture(scope="session")
def vocab():
    return get_vocabulary()

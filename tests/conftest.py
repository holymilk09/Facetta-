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


# Halo ring: 1.5 ct oval diamond center, 8 x 0.25 ct round melee, 18k white gold
HALO_SPEC = {
    "schema_version": 1,
    "design_id": "dsn_halo",
    "version": 1,
    "created_by": "usr_ana",
    "created_at": "2026-07-02T18:40:00Z",
    "jewelry_type": "ring",
    "template": "halo_prong",
    "mode": "pro",
    "stone": {
        "species": "diamond",
        "cut": "oval_brilliant",
        "carat": 1.5,
        "dimensions_mm": {"length": 8.6, "width": 6.4, "depth": 4.0},
        "color": {"trade": "D", "gia": "colorless"},
        "clarity": {"system": "gia_diamond", "grade": "VS1", "eye_clean": True},
        "phenomena": [],
    },
    "setting": {
        "style": "4_prong_basket",
        "prong_count": 4,
        "prong_tip_mm": 0.9,
        "gallery_height_mm": 4.5,
    },
    "metal": {"material": "gold", "karat": 18, "color": "white", "finish": "high_polish"},
    "band": {"profile": "half_round", "width_mm": 2.0, "thickness_mm": 1.7},
    "ring_size": {"system": "US", "value": 6.5},
    "side_stones": [{
        "species": "diamond",
        "cut": "round_brilliant",
        "carat": 0.25,
        "dimensions_mm": {"length": 4.1, "width": 4.1, "depth": 2.5},
        "color": {"trade": "F", "gia": "colorless"},
        "clarity": {"system": "gia_diamond", "grade": "VS2"},
        "count": 8,
        "position": "halo",
        "phenomena": [],
    }],
    "notes_to_factory": "Shared prongs between halo melee; keep the gallery open.",
}

# Love-style oval bangle: 8 princess diamonds evenly spaced, 18k yellow gold
BANGLE_SPEC = {
    "schema_version": 1,
    "design_id": "dsn_bangle",
    "version": 1,
    "created_by": "usr_ana",
    "created_at": "2026-07-02T18:40:00Z",
    "jewelry_type": "bracelet",
    "template": "love_bangle",
    "mode": "pro",
    "stone": {
        "species": "diamond",
        "cut": "princess",
        "carat": 0.14,
        "dimensions_mm": {"length": 2.9, "width": 2.9, "depth": 2.0},
        "color": {"trade": "F", "gia": "colorless"},
        "clarity": {"system": "gia_diamond", "grade": "VS1"},
        "count": 8,
        "position": "stations",
        "phenomena": [],
    },
    "setting": {"style": "flush_set"},
    "metal": {"material": "gold", "karat": 18, "color": "yellow", "finish": "high_polish"},
    "bracelet": {
        "inner_length_mm": 56.0,
        "inner_width_mm": 46.0,
        "width_mm": 6.1,
        "thickness_mm": 2.6,
    },
    "side_stones": [],
    "notes_to_factory": "Hinged oval bangle; stations flush-set, screw-motif free.",
}

# Cluster pendant: emerald-cut emerald, diamond surround, sapphire drop
PENDANT_SPEC = {
    "schema_version": 1,
    "design_id": "dsn_pendant",
    "version": 1,
    "created_by": "usr_ana",
    "created_at": "2026-07-02T18:40:00Z",
    "jewelry_type": "pendant",
    "template": "cluster_pendant",
    "mode": "pro",
    "stone": {
        "species": "emerald",
        "cut": "emerald_cut",
        "carat": 1.9,
        "dimensions_mm": {"length": 9.0, "width": 7.0, "depth": 4.5},
        "color": {"trade": "Muzo Green", "gia": "vivid slightly bluish green, tone 5, saturation 5"},
        "clarity": {"system": "gia_type_iii", "grade": "VS", "eye_clean": True},
        "origin": "Colombia",
        "treatment": "minor oil",
        "phenomena": [],
    },
    "setting": {"style": "prong_cluster", "prong_count": 4, "prong_tip_mm": 0.8},
    "metal": {"material": "gold", "karat": 18, "color": "white", "finish": "high_polish"},
    "pendant": {"bail_inner_diameter_mm": 3.5, "bail_height_mm": 5.5},
    "side_stones": [
        {
            "species": "diamond",
            "cut": "round_brilliant",
            "carat": 0.05,
            "dimensions_mm": {"length": 2.3, "width": 2.3, "depth": 1.5},
            "color": {"trade": "F", "gia": "colorless"},
            "clarity": {"system": "gia_diamond", "grade": "VS2"},
            "count": 12,
            "position": "surround",
            "phenomena": [],
        },
        {
            "species": "sapphire",
            "cut": "round_brilliant",
            "carat": 0.8,
            "dimensions_mm": {"length": 5.5, "width": 5.5, "depth": 3.4},
            "color": {"trade": "Royal Blue", "gia": "vivid violetish blue, tone 6, saturation 6"},
            "clarity": {"system": "gia_type_ii", "grade": "VS", "eye_clean": True},
            "count": 1,
            "position": "under_center",
            "phenomena": [],
        },
    ],
    "notes_to_factory": "Sapphire drop articulated on a jump ring below the cluster.",
}


@pytest.fixture
def example_spec() -> dict:
    return copy.deepcopy(EXAMPLE_SPEC)


@pytest.fixture
def halo_spec() -> dict:
    return copy.deepcopy(HALO_SPEC)


@pytest.fixture
def bangle_spec() -> dict:
    return copy.deepcopy(BANGLE_SPEC)


@pytest.fixture
def pendant_spec() -> dict:
    return copy.deepcopy(PENDANT_SPEC)


@pytest.fixture
def round_spec() -> dict:
    return copy.deepcopy(ROUND_SPEC)


@pytest.fixture(scope="session")
def vocab():
    return get_vocabulary()

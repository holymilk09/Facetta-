import copy
import os

import pytest

# API tests explicitly exercise the local/test boundary unless a test opts
# into required bearer authentication.
os.environ.setdefault("FACETTA_AUTH_MODE", "test")

from facetta.image_identity import spec_visual_hash
from facetta.spec import Spec
from facetta.validation import validate_spec
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


# Open cuff: 5 princess stations on the arc, 25 mm wrist gap
CUFF_SPEC = copy.deepcopy(BANGLE_SPEC)
CUFF_SPEC.update({"design_id": "dsn_cuff", "template": "cuff"})
CUFF_SPEC["bracelet"] = {
    "inner_length_mm": 58.0,
    "inner_width_mm": 48.0,
    "width_mm": 5.0,
    "thickness_mm": 2.2,
    "gap_width_mm": 25.0,
}
CUFF_SPEC["stone"] = {**copy.deepcopy(BANGLE_SPEC["stone"]), "count": 5}
CUFF_SPEC["notes_to_factory"] = "Open cuff; ease the tips, no hinge."

# Articulated link bracelet: 14 links, stones on alternating links
LINK_SPEC = copy.deepcopy(BANGLE_SPEC)
LINK_SPEC.update({"design_id": "dsn_link", "template": "link_bracelet"})
LINK_SPEC["bracelet"] = {
    "inner_length_mm": 56.0,
    "inner_width_mm": 46.0,
    "width_mm": 6.0,
    "thickness_mm": 2.4,
    "link_count": 14,
}
LINK_SPEC["stone"] = {**copy.deepcopy(BANGLE_SPEC["stone"]), "count": 7}
LINK_SPEC["metal"]["color"] = "white"
LINK_SPEC["notes_to_factory"] = "Articulated links, hinge pins between every link."

# Pendant necklace: the cluster pendant on a cable chain
NECKLACE_SPEC = copy.deepcopy(PENDANT_SPEC)
NECKLACE_SPEC.update({"design_id": "dsn_necklace", "jewelry_type": "necklace"})
NECKLACE_SPEC["chain"] = {"style": "cable", "length_mm": 450.0, "clasp": "lobster"}

# Loose stone / Gem ID: 2 ct round diamond with lab-report proportions
LOOSE_SPEC = {
    "schema_version": 1,
    "design_id": "dsn_gem",
    "version": 1,
    "created_by": "usr_ana",
    "created_at": "2026-07-02T18:40:00Z",
    "jewelry_type": "loose_stone",
    "template": "loose_stone",
    "mode": "pro",
    "stone": {
        "species": "diamond",
        "cut": "round_brilliant",
        "carat": 2.0,
        "dimensions_mm": {"length": 8.1, "width": 8.1, "depth": 4.9},
        "color": {"trade": "D", "gia": "colorless"},
        "clarity": {"system": "gia_diamond", "grade": "VS1", "eye_clean": True},
        "table_pct": 57.0,
        "depth_pct": 60.5,
        "girdle": "medium",
        "inscription": "FCT-2141Z",
        "phenomena": [],
    },
    "side_stones": [],
    "notes_to_factory": None,
}

# A larger bangle the BANGLE_SPEC piece nests inside (stacking fixture)
OUTER_BANGLE_SPEC = copy.deepcopy(BANGLE_SPEC)
OUTER_BANGLE_SPEC["design_id"] = "dsn_outer_bangle"
OUTER_BANGLE_SPEC["bracelet"] = {
    "inner_length_mm": 66.0,
    "inner_width_mm": 56.0,
    "width_mm": 6.1,
    "thickness_mm": 2.6,
}


def audited_import_spec(raw: dict) -> dict:
    """Attach synthetic all-pass source accounting for endpoint unit tests.

    Production callers never receive this helper. Test rasters are generated
    color blocks with no inspectable jewelry, so fixtures explicitly declare
    the canonical sections each synthetic source is standing in for.
    """
    data = copy.deepcopy(raw)
    if data.get("source_component_coverage") is not None:
        validated = validate_spec(Spec.model_validate(data), get_vocabulary())
        data["source_component_coverage"]["audited_spec_visual_hash"] = (
            spec_visual_hash(validated.spec)
        )
        return data
    components: list[tuple[str, str, list[str]]] = [
        ("assembly.primary", "Complete synthetic jewelry assembly.", ["template"]),
        ("stone.center", "Synthetic center-stone group.", ["stone"]),
    ]
    optional_sections = (
        ("setting", "setting.primary", "Synthetic primary setting."),
        ("metal", "metal.body", "Synthetic metal body."),
        ("band", "band.shank", "Synthetic ring shank."),
        ("ring_size", "ring.size", "Synthetic ring-size record."),
        ("pendant", "pendant.body", "Synthetic pendant body."),
        ("chain", "chain.body", "Synthetic carrier chain."),
        ("bracelet", "bracelet.body", "Synthetic bracelet body."),
        ("brooch", "brooch.body", "Synthetic brooch body."),
        ("drop", "drop.body", "Synthetic drop assembly."),
        ("composition", "composition.primary", "Synthetic composition."),
    )
    for path, component_id, description in optional_sections:
        if data.get(path) is not None:
            components.append((component_id, description, [path]))
    for index, _stone in enumerate(data.get("side_stones", []), start=1):
        components.append((
            f"stone.group.{index:03d}",
            f"Synthetic side-stone group {index}.",
            [f"side_stones[{index - 1}]"],
        ))
    data["source_component_coverage"] = {
        "source_kind": "imported_reference",
        "components": [{
            "component_id": component_id,
            "source_view": "unspecified",
            "source_description": description,
            "source_confidence": 1.0,
            "canonical_spec_paths": paths,
            "unresolved_reason": None,
            "independent_audit": {
                "kind": "independent_component_audit",
                "verdict": "pass",
                "auditor": "synthetic-test-source-audit.v1",
                "source_view": "unspecified",
                "observed_description": description,
                "evidence_sha256": "0" * 64,
            },
        } for component_id, description, paths in components],
    }
    validated = validate_spec(Spec.model_validate(data), get_vocabulary())
    data["source_component_coverage"]["audited_spec_visual_hash"] = (
        spec_visual_hash(validated.spec)
    )
    return data


@pytest.fixture
def example_spec() -> dict:
    return copy.deepcopy(EXAMPLE_SPEC)


@pytest.fixture
def cuff_spec() -> dict:
    return copy.deepcopy(CUFF_SPEC)


@pytest.fixture
def link_spec() -> dict:
    return copy.deepcopy(LINK_SPEC)


@pytest.fixture
def necklace_spec() -> dict:
    return copy.deepcopy(NECKLACE_SPEC)


@pytest.fixture
def loose_spec() -> dict:
    return copy.deepcopy(LOOSE_SPEC)


@pytest.fixture
def outer_bangle_spec() -> dict:
    return copy.deepcopy(OUTER_BANGLE_SPEC)


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


@pytest.fixture
def spray_spec() -> dict:
    """The leaf-spray brooch extracted from the designer's artwork — the
    checked-in example IS the fixture, so the tests pin the real file."""
    import json
    from pathlib import Path

    path = Path(__file__).parent.parent / "docs" / "examples" / "leaf_spray_brooch.json"
    return json.loads(path.read_text())


@pytest.fixture(scope="session")
def vocab():
    return get_vocabulary()

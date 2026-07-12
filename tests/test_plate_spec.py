from __future__ import annotations

from facetta.plate_spec import compile_plate_spec
from facetta.validation import validate_spec
from facetta.vocabulary import get_vocabulary


def test_plate_compiler_preserves_multiple_groups_and_marks_uncertainty():
    spec, notes = compile_plate_spec({
        "jewelry_type": "ring",
        "stones": [
            {"qty": 1, "type": "green square-cut stone (species TBD)"},
            {"qty": 2, "type": "green rectangular-cut stone (species TBD)"},
            {"qty": 1, "type": "diamond pavé and baguette"},
        ],
        "metal": "120 gold",
        "assembly": "central square green stone with leaf-motif pavé shoulders",
        "measurements": [{"label": "Diamond width", "value": "2 mm",
                          "status": "designer_confirmed"}],
    })

    assert spec.jewelry_type == "ring"
    assert len(spec.side_stones) == 2
    assert spec.side_stones[0].count == 2
    assert spec.side_stones[1].cut == "baguette"
    assert spec.band.width_mm == 2.0  # the confirmed number is stone width, not shank
    assert "placeholder" in spec.notes_to_factory
    assert any("species" in note for note in notes)
    assert validate_spec(spec, get_vocabulary()).ok


def test_plate_compiler_rejects_categories_outside_ring_and_necklace():
    try:
        compile_plate_spec({"jewelry_type": "earrings", "stones": []})
    except ValueError as exc:
        assert "supports rings and necklaces only" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("unsupported plate silently compiled")


def test_necklace_plate_preserves_custom_assembly_and_ambiguous_factory_facts():
    spec, notes = compile_plate_spec(
        {
            "jewelry_type": "necklace",
            "stones": [
                {"qty": 1, "type": "emerald pear shape"},
                {"qty": 2, "type": "emerald pear shape"},
                {"qty": 1, "type": "emerald buff top"},
                {"qty": 4, "type": "emerald pear shape"},
            ],
            "metal": "white gold or platinum",
            "assembly": (
                "collar necklace with articulated geometric diamond links and "
                "multiple pear emerald pendants"
            ),
            "measurements": [
                {"label": "2.49", "raw": "2.49", "status": "ambiguous"},
                {"label": "3.25", "raw": "3.25", "status": "ambiguous"},
            ],
        },
        source_asset_id="plate_emerald_necklace",
        source_asset_sha256="9" * 64,
    )

    assert spec.jewelry_type == "necklace"
    assert spec.template == "cluster_pendant"
    assert spec.stone.species == "emerald"
    assert spec.stone.cut == "pear"
    assert [stone.count for stone in spec.side_stones] == [2, 1, 4]
    assert spec.design_form.elements[0].element_id == "necklace_assembly"
    assert spec.design_form.elements[0].definition.asset_sha256 == "9" * 64
    coverage = spec.source_component_coverage
    assert coverage is not None
    components = {item.component_id: item for item in coverage.components}
    assert components["assembly.primary"].canonical_spec_paths == (
        "template",
        "design_form.elements[necklace_assembly]",
    )
    assert components["setting.primary"].unresolved_reason is not None
    assert components["metal.body"].unresolved_reason is not None
    assert components["assembly.chain"].unresolved_reason is not None
    assert "2.49" in spec.notes_to_factory
    assert "3.25" in spec.notes_to_factory
    assert any("chain production reference" in note for note in notes)
    assert validate_spec(spec, get_vocabulary()).ok


def test_necklace_plate_preserves_physical_roles_for_similar_stone_groups():
    spec, _ = compile_plate_spec(
        {
            "jewelry_type": "necklace",
            "stones": [
                {
                    "qty": 1,
                    "qty_status": "visible_count",
                    "position": "center drop",
                    "written_labels": ["3.25"],
                    "type": "emerald pear shape",
                },
                {
                    "qty": 2,
                    "qty_status": "visible_count",
                    "position": "inner flanking drops",
                    "written_labels": ["2.84", "3.06"],
                    "type": "emerald pear shape",
                },
                {
                    "qty": 2,
                    "qty_status": "visible_count",
                    "position": "outer flanking drops",
                    "written_labels": ["2.49", "2.66"],
                    "type": "emerald pear shape",
                },
            ],
            "assembly": "articulated collar with five pear emerald drops",
            "metal": "white gold or platinum",
        },
        source_asset_id="plate_necklace",
        source_asset_sha256="8" * 64,
    )

    assert spec.stone.position == "center_drop"
    assert [stone.position for stone in spec.side_stones] == [
        "inner_flanking_drops", "outer_flanking_drops",
    ]
    assert [stone.count for stone in spec.side_stones] == [2, 2]
    coverage = spec.source_component_coverage
    assert coverage is not None
    descriptions = {
        component.component_id: component.source_description
        for component in coverage.components
    }
    assert descriptions["stone.center"].startswith("center drop:")
    assert "2.84" in descriptions["stone.group.001"]
    assert "2.49" in descriptions["stone.group.002"]


def test_necklace_plate_keeps_generic_white_metal_factory_unresolved():
    spec, notes = compile_plate_spec(
        {
            "jewelry_type": "necklace",
            "stones": [{
                "qty": 1,
                "position": "center drop",
                "type": "emerald pear shape",
            }],
            "assembly": "white-metal collar with one emerald drop",
            "metal": "white metal",
        },
        source_asset_id="plate_white_metal",
        source_asset_sha256="7" * 64,
    )

    # The valid Spec still carries a visibly white placeholder for preview,
    # but source coverage forbids treating it as confirmed 18k white gold.
    assert spec.metal.material == "gold"
    assert spec.metal.karat == 18
    assert any("metal karat is not explicit" in note for note in notes)
    coverage = spec.source_component_coverage
    assert coverage is not None
    metal = next(
        item for item in coverage.components if item.component_id == "metal.body"
    )
    assert metal.canonical_spec_paths == ()
    assert metal.unresolved_reason is not None


def test_necklace_plate_retains_assembly_named_missing_diamond_group():
    spec, _ = compile_plate_spec(
        {
            "jewelry_type": "necklace",
            "stones": [{"qty": 1, "type": "emerald pear shape"}],
            "assembly": "articulated collar with emerald drop and diamond clusters",
            "metal": "18k white gold",
        },
        source_asset_id="plate_missing_group",
        source_asset_sha256="6" * 64,
    )

    coverage = spec.source_component_coverage
    assert coverage is not None
    components = {item.component_id: item for item in coverage.components}
    missing = components["stone.assembly_hint.diamond"]
    assert missing.canonical_spec_paths == ()
    assert "no distinct structured stone group" in missing.unresolved_reason
    metal = components["metal.body"]
    assert metal.canonical_spec_paths == ("metal",)


def test_plate_compiler_routes_diamond_leaf_shoulders_to_leaf_template():
    spec, _ = compile_plate_spec({
        "jewelry_type": "ring",
        "stones": [
            {"qty": 1, "type": "emerald emerald-cut center 8 x 8 mm"},
            {"qty": 12, "type": "marquise diamond pave leaf shoulder 2.5 x 1.3 mm"},
            {"qty": 24, "type": "round diamond pave leaf shoulder 1.2 x 1.2 mm"},
        ],
        "metal": "18k yellow gold",
        "assembly": "four-prong ring with mirrored diamond leaf shoulders",
    })

    assert spec.template == "leaf_shoulder_prong"
    assert [stone.position for stone in spec.side_stones] == [
        "pave_leaves", "pave_leaves"]
    assert validate_spec(spec, get_vocabulary()).ok


def test_plate_compiler_routes_generic_side_group_from_explicit_halo_assembly():
    spec, _ = compile_plate_spec({
        "jewelry_type": "ring",
        "stones": [
            {"qty": 1, "type": "blue oval faceted stone (species TBD)"},
            {"qty": 14, "type": "round white stone (species TBD)"},
        ],
        "metal": "white gold or platinum",
        "assembly": (
            "oval blue center stone surrounded by halo of round stones in a "
            "raised prong setting, mounted on a plain rounded band"
        ),
    })

    assert spec.template == "halo_prong"
    assert spec.side_stones[0].position == "halo"
    coverage = spec.source_component_coverage
    assert coverage is not None
    components = {item.component_id: item for item in coverage.components}
    assert "stone.assembly_hint.halo" not in components
    assert "stone.assembly_hint.shoulder" not in components
    assert components["setting.primary"].canonical_spec_paths == ("setting",)
    assert validate_spec(spec, get_vocabulary()).ok


def test_plain_band_language_does_not_invent_a_gem_bearing_shoulder_group():
    spec, _ = compile_plate_spec({
        "jewelry_type": "ring",
        "stones": [{"qty": 1, "type": "oval sapphire 8 x 6 mm"}],
        "metal": "18k white gold",
        "assembly": "oval sapphire in a four-prong setting on a plain rounded band",
    })

    coverage = spec.source_component_coverage
    assert coverage is not None
    assert "stone.assembly_hint.shoulder" not in {
        item.component_id for item in coverage.components
    }


def test_plate_compiler_preserves_confirmed_band_and_marks_other_dimensions():
    spec, _ = compile_plate_spec({
        "jewelry_type": "ring",
        "stones": [{"qty": 1, "type": "oval sapphire 8 x 6 mm"}],
        "metal": "18k yellow gold",
        "measurements": [{
            "label": "shank width",
            "value": "2.4 mm",
            "status": "designer_confirmed",
        }],
    })

    assert spec.band.width_mm == 2.4
    assert spec.dimension_provenance["band.width_mm"].status == "designer_confirmed"
    assert spec.dimension_provenance["stone.dimensions_mm.length"].status == (
        "estimated_from_reference")
    assert spec.dimension_provenance["band.thickness_mm"].method == (
        "reference_vision")

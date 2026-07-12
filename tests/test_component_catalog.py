"""Contract tests for catalog-directed component changes.

The catalog is a deterministic control surface for the image agent: a stable
option selects an exact factory-spec patch and supplies enough visual/isolation
facts to localize the edit.  It does not make necklaces supported by the
ring-only trusted image agent before necklace QA and routing exist.
"""

from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import BaseModel

from facetta.component_catalog import (
    CatalogSelectionError,
    ComponentCatalogOption,
    apply_catalog_selection,
    get_component_catalog,
)
from facetta.image_agent import (
    DesignerEditDomain,
    ImageOperation,
    build_image_plan,
)
from facetta.image_agent.edit_semantics import classify_spec_delta
from facetta.spec import Spec
from facetta.validation import validate_spec
from facetta.vocabulary import get_vocabulary


REQUIRED_CHAIN_FROZEN_FACTS = {
    "stone",
    "side_stones",
    "setting",
    "metal",
    "pendant",
    "chain.length_mm",
    "chain.clasp",
    "chain.pendant_connection",
}


def _chain_options() -> dict[str, ComponentCatalogOption]:
    return {
        option.id: option
        for option in get_component_catalog("chain.style")
    }


def test_chain_catalog_is_typed_and_carries_image_and_factory_control_facts():
    options = _chain_options()
    assert {"cable", "curb"} <= options.keys()

    for option_id in ("cable", "curb"):
        option = options[option_id]
        assert isinstance(option, BaseModel)
        assert option.id == option_id
        assert isinstance(option.display, str) and option.display.strip()
        assert isinstance(option.visual_geometry, tuple)
        assert option.visual_geometry
        assert all(isinstance(fact, str) and fact.strip()
                   for fact in option.visual_geometry)
        assert isinstance(option.isolation_target, str)
        assert "chain" in option.isolation_target.lower()
        assert isinstance(option.frozen_facts, tuple)
        assert REQUIRED_CHAIN_FROZEN_FACTS <= set(option.frozen_facts)
        assert option.factory_fields == {"chain.style": option_id}
        requirements = " ".join(option.selection_requirements).lower()
        assert "designer-confirmed target geometry" in requirements
        assert "supplier sku" in requirements
        assert "cad" in requirements
        assert "never reuse" in requirements

    assert "round" in " ".join(options["cable"].visual_geometry).lower()
    curb_geometry = " ".join(options["curb"].visual_geometry).lower()
    assert "link" in curb_geometry
    assert "flat" in curb_geometry


def test_cable_to_curb_selection_has_one_exact_factory_delta(necklace_spec):
    source = Spec.model_validate(necklace_spec)
    source_snapshot = source.model_dump(mode="json")

    selected = apply_catalog_selection(
        source,
        component_path="chain.style",
        option_id="curb",
    )

    assert selected.spec.chain is not None
    assert selected.spec.chain.style == "curb"
    assert selected.spec_change == ({
        "path": "chain.style",
        "before": "cable",
        "after": "curb",
        "label": "chain style",
    },)
    assert selected.isolation_target == _chain_options()["curb"].isolation_target
    assert selected.frozen_facts == _chain_options()["curb"].frozen_facts
    # Catalog application is pure; persistence owns the next immutable version.
    assert source.model_dump(mode="json") == source_snapshot


def test_chain_style_selection_freezes_every_unnamed_necklace_fact(necklace_spec):
    source = Spec.model_validate(necklace_spec)
    selected = apply_catalog_selection(
        source,
        component_path="chain.style",
        option_id="curb",
    ).spec

    before = source.model_dump(mode="json")
    after = selected.model_dump(mode="json")
    assert after["chain"]["style"] == "curb"

    # Length and clasp belong to the same chain object but are not authorized
    # by a style selection.  Pendant, gems, alloy, and setting are also frozen.
    assert after["chain"]["length_mm"] == before["chain"]["length_mm"]
    assert after["chain"]["clasp"] == before["chain"]["clasp"]
    for section in ("pendant", "stone", "side_stones", "metal", "setting"):
        assert after[section] == before[section], section

    expected = deepcopy(before)
    expected["chain"]["style"] = "curb"
    assert after == expected


def test_unknown_chain_catalog_option_is_rejected_with_valid_options(necklace_spec):
    source = Spec.model_validate(necklace_spec)

    with pytest.raises(CatalogSelectionError) as caught:
        apply_catalog_selection(
            source,
            component_path="chain.style",
            option_id="spaghetti",
        )

    assert caught.value.component_path == "chain.style"
    assert caught.value.option_id == "spaghetti"
    assert {"cable", "curb"} <= set(caught.value.valid_options)
    assert source.chain is not None and source.chain.style == "cable"


def test_chain_catalog_rejects_a_non_necklace_spec(halo_spec):
    raw = deepcopy(halo_spec)
    raw["chain"] = {
        "style": "cable",
        "length_mm": 450.0,
        "clasp": "lobster",
    }
    source = Spec.model_validate(raw)

    with pytest.raises(CatalogSelectionError, match="requires a necklace"):
        apply_catalog_selection(
            source,
            component_path="chain.style",
            option_id="curb",
        )


def test_necklace_catalog_builds_a_chain_only_local_edit_plan(necklace_spec):
    source = Spec.model_validate(necklace_spec)
    target = apply_catalog_selection(
        source,
        component_path="chain.style",
        option_id="curb",
    ).spec

    plan = build_image_plan(
        ImageOperation.LOCAL_EDIT,
        "change only the necklace chain from cable to curb",
        spec=target,
        source_spec=source,
        source_image=b"source-necklace-image",
        region_description="the visible chain links, excluding pendant and clasp",
        frozen=_chain_options()["curb"].frozen_facts,
    )

    assert plan.edit_domains == (DesignerEditDomain.CHAIN_STYLE,)
    assert plan.jewelry_type == "necklace"


def test_chain_style_delta_has_a_stable_future_image_edit_domain(necklace_spec):
    source = Spec.model_validate(necklace_spec)
    selection = apply_catalog_selection(
        source,
        component_path="chain.style",
        option_id="curb",
    )

    assert classify_spec_delta(selection.spec_change) == (
        DesignerEditDomain.CHAIN_STYLE,
    )


def _options(component_path: str) -> dict[str, ComponentCatalogOption]:
    return {
        option.id: option
        for option in get_component_catalog(component_path)
    }


def test_center_cut_catalog_exposes_only_current_factory_sheet_shapes():
    options = _options("stone.cut")

    assert set(options) == {
        "round_brilliant",
        "oval_brilliant",
        "emerald_cut",
        "cushion",
    }
    # Pointed cuts need explicit V-prong/tip semantics that the current
    # Setting record cannot represent safely.  Do not offer a fake shortcut.
    assert {"pear", "marquise", "princess"}.isdisjoint(options)
    for option in options.values():
        assert option.factory_fields == {"stone.cut": option.id}
        assert option.derived_factory_fields == ("stone.carat",)
        assert "center-stone" in option.isolation_target
        assert "stone.dimensions_mm" in option.frozen_facts
        assert "setting" not in option.frozen_facts
        assert {
            "setting.style",
            "setting.prong_count",
            "setting.prong_tip_mm",
            "setting.gallery_height_mm",
        } <= set(option.frozen_facts)
        assert option.visual_geometry
        assert any("contact points" in fact for fact in option.visual_geometry)
        assert option.selection_requirements


def test_center_cut_selection_recomputes_only_modeled_carat_at_fixed_mm(halo_spec):
    source = Spec.model_validate(halo_spec)
    snapshot = source.model_dump(mode="json")

    selection = apply_catalog_selection(
        source,
        component_path="stone.cut",
        option_id="emerald_cut",
    )

    assert selection.spec.stone.cut == "emerald_cut"
    assert selection.spec.stone.carat != source.stone.carat
    assert selection.spec.stone.dimensions_mm == source.stone.dimensions_mm
    assert [change["path"] for change in selection.spec_change] == [
        "stone.cut",
        "stone.carat",
    ]
    assert classify_spec_delta(selection.spec_change) == (
        DesignerEditDomain.CENTER_STONE_SHAPE,
    )
    assert validate_spec(selection.spec, get_vocabulary()).ok

    expected = deepcopy(snapshot)
    expected["stone"]["cut"] = "emerald_cut"
    expected["stone"]["carat"] = selection.spec.stone.carat
    assert selection.spec.model_dump(mode="json") == expected
    assert source.model_dump(mode="json") == snapshot


def test_center_cut_catalog_refuses_to_guess_new_face_up_dimensions(halo_spec):
    source = Spec.model_validate(halo_spec)

    with pytest.raises(CatalogSelectionError, match="confirm a new diameter"):
        apply_catalog_selection(
            source,
            component_path="stone.cut",
            option_id="round_brilliant",
        )

    raw = deepcopy(halo_spec)
    raw["stone"]["cut"] = "cushion"
    raw["stone"]["dimensions_mm"]["length"] = 6.4
    raw["stone"]["carat"] = 0.82
    square_source = Spec.model_validate(raw)
    with pytest.raises(CatalogSelectionError, match="confirm those dimensions"):
        apply_catalog_selection(
            square_source,
            component_path="stone.cut",
            option_id="oval_brilliant",
        )


def test_center_cut_catalog_preserves_setting_compatibility(halo_spec):
    raw = deepcopy(halo_spec)
    raw["setting"]["style"] = "6_prong_basket"
    raw["setting"]["prong_count"] = 6
    source = Spec.model_validate(raw)

    with pytest.raises(CatalogSelectionError, match="requires one of these exact"):
        apply_catalog_selection(
            source,
            component_path="stone.cut",
            option_id="emerald_cut",
        )


def test_metal_material_catalog_uses_complete_alloy_presets():
    options = _options("metal.material")

    assert {
        "gold_14_yellow",
        "gold_14_white",
        "gold_14_rose",
        "gold_18_yellow",
        "gold_18_white",
        "gold_18_rose",
        "platinum",
        "silver",
    } == set(options)
    assert "gold" not in options  # a bare gold material lacks karat and color
    assert options["gold_18_rose"].factory_fields == {
        "metal.material": "gold",
        "metal.karat": 18,
        "metal.color": "rose",
    }
    assert options["platinum"].factory_fields == {
        "metal.material": "platinum",
        "metal.karat": None,
        "metal.color": None,
    }


def test_white_gold_to_platinum_is_one_exact_coupled_selection(halo_spec):
    source = Spec.model_validate(halo_spec)
    snapshot = source.model_dump(mode="json")
    selection = apply_catalog_selection(
        source,
        component_path="metal.material",
        option_id="platinum",
    )

    assert selection.spec.metal is not None
    assert selection.spec.metal.material == "platinum"
    assert selection.spec.metal.karat is None
    assert selection.spec.metal.color is None
    assert selection.spec.metal.finish == source.metal.finish
    assert [change["path"] for change in selection.spec_change] == [
        "metal.material",
        "metal.karat",
        "metal.color",
    ]
    assert classify_spec_delta(selection.spec_change) == (
        DesignerEditDomain.METAL_IDENTITY,
    )
    assert validate_spec(selection.spec, get_vocabulary()).ok

    expected = deepcopy(snapshot)
    expected["metal"].update({
        "material": "platinum",
        "karat": None,
        "color": None,
    })
    assert selection.spec.model_dump(mode="json") == expected
    assert source.model_dump(mode="json") == snapshot


def test_gold_color_is_a_leaf_delta_and_rejects_non_gold(halo_spec):
    source = Spec.model_validate(halo_spec)
    selection = apply_catalog_selection(
        source,
        component_path="metal.color",
        option_id="rose",
    )
    assert selection.spec.metal is not None
    assert selection.spec.metal.material == "gold"
    assert selection.spec.metal.karat == 18
    assert selection.spec.metal.color == "rose"
    assert selection.spec_change == ({
        "path": "metal.color",
        "before": "white",
        "after": "rose",
        "label": "gold color",
    },)

    platinum = apply_catalog_selection(
        source,
        component_path="metal.material",
        option_id="platinum",
    ).spec
    with pytest.raises(CatalogSelectionError, match="applies only to gold"):
        apply_catalog_selection(
            platinum,
            component_path="metal.color",
            option_id="yellow",
        )


def test_setting_catalog_couples_style_count_and_tip(halo_spec):
    options = _options("setting.style")
    assert set(options) == {
        "4_prong_basket",
        "6_prong_basket",
        "bezel",
        "semi_bezel",
    }
    assert options["6_prong_basket"].factory_fields == {
        "setting.style": "6_prong_basket",
        "setting.prong_count": 6,
    }
    assert options["bezel"].factory_fields == {
        "setting.style": "bezel",
        "setting.prong_count": None,
        "setting.prong_tip_mm": None,
    }

    source = Spec.model_validate(halo_spec)
    six = apply_catalog_selection(
        source,
        component_path="setting.style",
        option_id="6_prong_basket",
    )
    assert six.spec.setting is not None
    assert six.spec.setting.style == "6_prong_basket"
    assert six.spec.setting.prong_count == 6
    assert six.spec.setting.prong_tip_mm == 0.9
    assert [change["path"] for change in six.spec_change] == [
        "setting.style",
        "setting.prong_count",
    ]
    assert classify_spec_delta(six.spec_change) == (
        DesignerEditDomain.SETTING,
    )
    assert validate_spec(six.spec, get_vocabulary()).ok

    bezel = apply_catalog_selection(
        source,
        component_path="setting.style",
        option_id="bezel",
    )
    assert bezel.spec.setting is not None
    assert bezel.spec.setting.style == "bezel"
    assert bezel.spec.setting.prong_count is None
    assert bezel.spec.setting.prong_tip_mm is None
    assert [change["path"] for change in bezel.spec_change] == [
        "setting.style",
        "setting.prong_count",
        "setting.prong_tip_mm",
    ]

    bezel_without_gauge = bezel.spec
    with pytest.raises(CatalogSelectionError, match="designer-confirmed prong-tip"):
        apply_catalog_selection(
            bezel_without_gauge,
            component_path="setting.style",
            option_id="4_prong_basket",
        )


def test_six_prong_catalog_does_not_guess_corner_placement(halo_spec):
    raw = deepcopy(halo_spec)
    raw["stone"]["cut"] = "emerald_cut"
    source = Spec.model_validate(raw)

    with pytest.raises(CatalogSelectionError, match="not an exact catalog setting"):
        apply_catalog_selection(
            source,
            component_path="setting.style",
            option_id="6_prong_basket",
        )


@pytest.mark.parametrize(
    ("species", "known_term"),
    [
        ("diamond", "D Colorless"),
        ("ruby", "Pigeon's Blood"),
        ("sapphire", "Royal Blue"),
        ("emerald", "Muzo Green"),
        ("tourmaline", "Paraiba"),
    ],
)
def test_center_stone_color_catalog_is_a_compact_species_scoped_palette(
    species,
    known_term,
):
    """Quick choices stay familiar without turning the editor into a list.

    The catalog is deliberately scoped by the center-stone species.  A color
    label is not a globally valid token: for example, Royal Blue is a sapphire
    direction and cannot silently become a ruby or emerald factory claim.
    """
    options = get_component_catalog(
        "stone.color",
        stone_species=species,
    )

    assert 5 <= len(options) <= 7
    by_id = {option.id: option for option in options}
    assert known_term in by_id
    assert all(option.factory_fields["stone.species"] == species
               for option in options)
    assert all("stone.color" in option.factory_fields for option in options)
    assert all("center-stone" in option.isolation_target
               for option in options)
    assert all({
        "stone.cut",
        "stone.dimensions_mm",
        "stone.count",
        "setting",
        "side_stones",
        "metal",
        "band",
        "ring_size",
    } <= set(option.frozen_facts) for option in options)


def test_center_stone_color_catalog_changes_species_color_and_carat_atomically(
    halo_spec,
):
    """A quick color chip can also make an explicit, paired species swap.

    Species-specific grading claims are cleared rather than copied into the
    new gem.  The structural ring facts remain frozen; an image-agent revision
    owns the corresponding pixels later in the persisted route.
    """
    source = Spec.model_validate(halo_spec)
    before = source.model_dump(mode="json")

    selection = apply_catalog_selection(
        source,
        component_path="stone.color",
        option_id="Royal Blue",
        stone_species="sapphire",
    )

    after = selection.spec.model_dump(mode="json")
    assert after["stone"]["species"] == "sapphire"
    assert after["stone"]["color"]["trade"] == "Royal Blue"
    assert after["stone"]["carat"] != before["stone"]["carat"]
    assert after["stone"]["clarity"] is None
    assert after["stone"]["origin"] is None
    assert after["stone"]["treatment"] is None
    assert after["stone"]["phenomena"] == []
    assert after["stone"]["cut"] == before["stone"]["cut"]
    assert after["stone"]["dimensions_mm"] == before["stone"]["dimensions_mm"]
    for path in ("setting", "side_stones", "metal", "band", "ring_size", "design_form"):
        assert after[path] == before[path], path
    assert [change["path"] for change in selection.spec_change] == [
        "stone.species",
        "stone.color",
        "stone.carat",
        "stone.clarity",
    ]
    assert source.model_dump(mode="json") == before
    assert validate_spec(selection.spec, get_vocabulary()).ok


def test_center_stone_color_catalog_rejects_unknown_species_and_cross_species_term(
    halo_spec,
):
    source = Spec.model_validate(halo_spec)

    with pytest.raises(CatalogSelectionError, match="requires a known center-stone species"):
        get_component_catalog("stone.color", stone_species="jadeite")

    with pytest.raises(CatalogSelectionError) as caught:
        apply_catalog_selection(
            source,
            component_path="stone.color",
            option_id="Royal Blue",
            stone_species="ruby",
        )
    assert caught.value.component_path == "stone.color"
    assert "Pigeon's Blood" in caught.value.valid_options
    assert "Royal Blue" not in caught.value.valid_options

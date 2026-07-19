"""Sequential Studio edits preserve accepted jewelry intent without guessing."""

from facetta.creative_symmetry import (
    SIX_LEAF_RUBY_PATTERN_CONTRACT,
    requests_six_leaf_ruby_pattern,
    with_jewelry_symmetry_contract,
)
from facetta.jewelry_intent import (
    BRAIDED_WHITE_GOLD_CHAIN_CONTRACT,
    SEQUENTIAL_JEWELRY_EDIT_CONTRACT,
    SMALL_DIAMOND_VISUAL_CONTRACT,
    requests_braided_white_gold_chain,
    requests_small_diamond_visual_accents,
    with_sequential_jewelry_edit_contract,
)


LEAF_EDIT = (
    "Add a leaf design surrounding the ruby, 3 leaves each side; small "
    "white diamonds and the other half green tsavorites."
)
CHAIN_EDIT = "Make the chain white-gold intertwined and braided."


def test_three_leaves_each_side_compiles_to_six_mirrored_pattern_leaves():
    assert requests_six_leaf_ruby_pattern(LEAF_EDIT) is True

    compiled = with_jewelry_symmetry_contract(LEAF_EDIT)

    assert SIX_LEAF_RUBY_PATTERN_CONTRACT in compiled
    assert "six discrete leaves total" in compiled
    assert "three leaves use white-diamond treatment" in compiled
    assert "three leaves use tsavorite treatment" in compiled
    assert "requested green tone when the designer names green" in compiled
    assert "same material phase and order" in compiled


def test_small_without_a_diamond_noun_never_infers_melee_or_pave():
    instruction = "Make the ruby smaller and keep the leaves unchanged."

    assert requests_small_diamond_visual_accents(instruction) is False
    compiled = with_sequential_jewelry_edit_contract(instruction)
    assert SMALL_DIAMOND_VISUAL_CONTRACT not in compiled
    assert "never infer a new stone species, pave, melee" in compiled


def test_small_white_diamonds_are_visual_accents_not_factory_facts():
    assert requests_small_diamond_visual_accents(LEAF_EDIT) is True

    compiled = with_sequential_jewelry_edit_contract(LEAF_EDIT)

    assert SMALL_DIAMOND_VISUAL_CONTRACT in compiled
    assert "small, melee-scale white-diamond visual accents" in compiled
    assert "not a confirmed melee size" in compiled
    assert "or factory authority" in compiled


def test_chain_follow_up_authorizes_only_chain_material_and_weave():
    assert requests_braided_white_gold_chain(CHAIN_EDIT) is True

    compiled = with_sequential_jewelry_edit_contract(CHAIN_EDIT)

    assert BRAIDED_WHITE_GOLD_CHAIN_CONTRACT in compiled
    assert "Change only the necklace chain" in compiled
    assert "Do not recolor or redesign ruby settings, leaf motifs" in compiled
    assert "three-per-side bilateral arrangement" in compiled
    assert "not confirmed alloy, purity, dimensions" in compiled


def test_sequential_context_preserves_leaf_pattern_during_chain_follow_up():
    compiled = with_sequential_jewelry_edit_contract(
        CHAIN_EDIT,
        accepted_instructions=(
            "Ruby on a gold necklace.",
            LEAF_EDIT,
        ),
    )
    compiled = with_jewelry_symmetry_contract(compiled)

    assert SEQUENTIAL_JEWELRY_EDIT_CONTRACT in compiled
    assert "history, not new commands" in compiled
    assert "Ruby on a gold necklace" in compiled
    assert LEAF_EDIT in compiled
    assert BRAIDED_WHITE_GOLD_CHAIN_CONTRACT in compiled
    assert SIX_LEAF_RUBY_PATTERN_CONTRACT in compiled
    assert "requested green tone when the designer names green" in compiled
    assert "later entries supersede earlier entries" in compiled
    assert "Do not reapply, undo, or newly expand them" in compiled

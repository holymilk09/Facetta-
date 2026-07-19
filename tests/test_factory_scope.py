from __future__ import annotations

import copy

from conftest import EXAMPLE_SPEC, NECKLACE_SPEC

from facetta.factory_scope import (
    RELEASED_FACTORY_JEWELRY_TYPES,
    RELEASED_FACTORY_RING_TEMPLATES,
    factory_category_blockers,
    factory_template_blockers,
)
from facetta.spec import Spec


def test_factory_scope_releases_ring_without_rewriting_the_spec():
    spec = Spec.model_validate(copy.deepcopy(EXAMPLE_SPEC))

    assert RELEASED_FACTORY_JEWELRY_TYPES == frozenset({"ring"})
    assert factory_category_blockers(spec) == ()
    assert spec.jewelry_type == "ring"
    assert spec.template in RELEASED_FACTORY_RING_TEMPLATES
    assert factory_template_blockers(spec) == ()


def test_factory_scope_blocks_necklace_without_affecting_readability():
    spec = Spec.model_validate(copy.deepcopy(NECKLACE_SPEC))

    blockers = factory_category_blockers(spec)

    assert spec.jewelry_type == "necklace"
    assert spec.chain is not None
    assert len(blockers) == 1
    assert blockers[0].code == "factory_category_not_released"
    assert blockers[0].subject_id == "necklace"
    assert "released for rings only" in blockers[0].message


def test_factory_scope_blocks_unreleased_three_stone_topology_without_rewriting():
    raw = copy.deepcopy(EXAMPLE_SPEC)
    raw["template"] = "three_stone_prong"
    spec = Spec.model_validate(raw)

    blockers = factory_template_blockers(spec)

    assert spec.jewelry_type == "ring"
    assert spec.template == "three_stone_prong"
    assert len(blockers) == 1
    assert blockers[0].code == "factory_template_not_released"
    assert blockers[0].subject_id == "three_stone_prong"
    assert "does not yet support" in blockers[0].message
    assert "will not substitute a generic or different ring drawing" in (
        blockers[0].message
    )

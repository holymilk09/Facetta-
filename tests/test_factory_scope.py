from __future__ import annotations

import copy

from conftest import EXAMPLE_SPEC, NECKLACE_SPEC

from facetta.factory_scope import (
    RELEASED_FACTORY_JEWELRY_TYPES,
    factory_category_blockers,
)
from facetta.spec import Spec


def test_factory_scope_releases_ring_without_rewriting_the_spec():
    spec = Spec.model_validate(copy.deepcopy(EXAMPLE_SPEC))

    assert RELEASED_FACTORY_JEWELRY_TYPES == frozenset({"ring"})
    assert factory_category_blockers(spec) == ()
    assert spec.jewelry_type == "ring"


def test_factory_scope_blocks_necklace_without_affecting_readability():
    spec = Spec.model_validate(copy.deepcopy(NECKLACE_SPEC))

    blockers = factory_category_blockers(spec)

    assert spec.jewelry_type == "necklace"
    assert spec.chain is not None
    assert len(blockers) == 1
    assert blockers[0].code == "factory_category_not_released"
    assert blockers[0].subject_id == "necklace"
    assert "released for rings only" in blockers[0].message

"""The tap-to-approve checklist: facts from the record, jewelry-type aware.

Pure code under test — no providers, no DB. The structural promise checked
here: every item a checklist generates can be resolved by the edit agent
(agent.resolve_target), so a NO note is executable by construction.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from facetta.agent import Annotation, resolve_target
from facetta.checklist import (
    approval_footer_line, build_checklist_items, checklist_status,
)
from facetta.spec import Spec

from conftest import BANGLE_SPEC, HALO_SPEC, PENDANT_SPEC


def _items(raw) -> dict:
    spec = Spec.model_validate(raw)
    return {i.key: i for i in build_checklist_items(spec)}


class TestItemDerivation:
    def test_ring_checklist_asks_ring_questions(self):
        items = _items(HALO_SPEC)
        assert {"stone", "side_stones[0]", "setting", "metal", "band",
                "ring_size"} <= set(items)
        # never a question that doesn't apply
        assert "chain" not in items and "drop" not in items
        assert items["stone"].fact == ("1.50 ct diamond · oval brilliant · "
                                       "8.6 × 6.4 × 4 mm")
        assert items["side_stones[0]"].label == "Halo stones"
        assert "8 × diamond round brilliant" in items["side_stones[0]"].fact
        assert "2.00 ct total" in items["side_stones[0]"].fact
        assert items["band"].fact == "half round · 2 × 1.7 mm"
        assert items["ring_size"].fact.startswith("US 6.5")

    def test_drop_earring_checklist_asks_about_the_drop(self):
        raw = json.loads((Path(__file__).parent.parent / "docs" / "examples"
                          / "marquise_drop_earring.json").read_text())
        items = _items(raw)
        assert "drop" in items
        assert "hook" in items["drop"].fact and "overall" in items["drop"].fact
        assert "band" not in items and "ring_size" not in items

    def test_pendant_checklist_asks_about_the_bail(self):
        items = _items(PENDANT_SPEC)
        assert "pendant" in items
        assert items["pendant"].fact.startswith("bail ⌀")
        assert "band" not in items

    def test_bangle_checklist_asks_about_the_opening(self):
        items = _items(BANGLE_SPEC)
        assert "bracelet" in items
        assert "inner 56 × 46 mm" in items["bracelet"].fact

    def test_every_item_is_resolvable_by_the_edit_agent(self):
        """The transparency guarantee: a NO on ANY item maps onto exactly one
        spec subtree the scoped edit can touch."""
        for raw in (HALO_SPEC, PENDANT_SPEC, BANGLE_SPEC):
            spec = Spec.model_validate(raw)
            for item in build_checklist_items(spec):
                target = resolve_target(spec, Annotation(
                    ref=item.ref, section=item.section, index=item.index,
                    instruction="x"))
                assert target[0] in ("stone", "side_stones", "setting",
                                     "metal", "band", "ring_size", "drop",
                                     "pendant", "chain", "bracelet", "brooch")

    def test_setting_fact_does_not_stutter_prongs(self):
        items = _items(HALO_SPEC)
        # style '4_prong_basket' already carries the 4 — no '· 4-prong' suffix
        assert items["setting"].fact.startswith("4 Prong Basket")
        assert "4-prong" not in items["setting"].fact


class TestStatus:
    def _resp(self, key, ok):
        return SimpleNamespace(item_key=key, approved=ok)

    def test_all_approved_requires_every_item(self):
        items = [{"key": "stone"}, {"key": "band"}]
        s = checklist_status(items, [self._resp("stone", True)])
        assert s["approved"] == 1 and not s["all_approved"]
        assert s["outstanding"] == ["band"]
        s = checklist_status(items, [self._resp("stone", True),
                                     self._resp("band", True)])
        assert s["all_approved"] and s["outstanding"] == []

    def test_latest_tap_wins(self):
        items = [{"key": "stone"}]
        s = checklist_status(items, [self._resp("stone", False),
                                     self._resp("stone", True)])
        assert s["all_approved"]
        s = checklist_status(items, [self._resp("stone", True),
                                     self._resp("stone", False)])
        assert not s["all_approved"] and s["declined"] == ["stone"]

    def test_footer_line(self):
        from datetime import datetime

        s = {"approved": 7, "total": 7}
        line = approval_footer_line(s, "usr_ana", datetime(2026, 7, 8, 12))
        assert line == "approved 7/7 · usr_ana · 2026-07-08"

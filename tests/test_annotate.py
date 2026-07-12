"""Surgical annotation edits: the agent changes the ONE annotated element and
nothing else — enforced by the scope guard, not by trusting the model.

plan_edit (the LLM) is mocked; the point under test is the guarantee: whatever
the model proposes, only the resolved target subtree survives, everything else
is the current spec byte-for-byte, and an out-of-scope change is discarded and
reported. The validator still gates the scoped result, so an impossible lone
change saves nothing.
"""

import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import facetta.agent as agent_mod
from facetta.agent import (
    Annotation, AnnotationUnresolved, EditResult, resolve_target, scope_guard,
)
from facetta.db import Base, get_db
from facetta.main import app
from facetta.spec import Spec

RUBY = json.loads(
    (Path(__file__).parent.parent / "docs" / "examples" / "ruby_sunburst_ring.json").read_text())


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False)

    def override():
        s = TestSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


def _design(client) -> str:
    r = client.post("/designs", json={"created_by": "usr_ana", "spec": RUBY})
    assert r.status_code == 201, r.text
    return r.json()["design_id"]


class TestResolveTarget:
    def test_ref_letters_map_to_subtrees(self):
        spec = Spec.model_validate(RUBY)
        assert resolve_target(spec, Annotation(ref="A", instruction="x")) == ("stone", None)
        assert resolve_target(spec, Annotation(ref="B", instruction="x")) == ("side_stones", 0)
        assert resolve_target(spec, Annotation(ref="C", instruction="x")) == ("side_stones", 1)

    def test_named_sections(self):
        spec = Spec.model_validate(RUBY)
        assert resolve_target(spec, Annotation(section="metal", instruction="x")) == ("metal", None)
        assert resolve_target(spec, Annotation(section="band", instruction="x")) == ("band", None)

    def test_full_side_stone_inventory_is_an_explicit_collection_target(self):
        spec = Spec.model_validate(RUBY)
        assert resolve_target(
            spec,
            Annotation(
                section="side_stones",
                instruction="remove the outer halo and add two shoulder stones",
            ),
        ) == ("side_stones", None)

    @pytest.mark.parametrize(
        "instruction",
        (
            "change the center stone shape to emerald cut",
            "make the center a marquise",
            "use a pear silhouette",
        ),
    )
    def test_center_shape_change_includes_required_setting_adaptation(
            self, instruction):
        spec = Spec.model_validate(RUBY)
        assert resolve_target(
            spec,
            Annotation(ref="A", instruction=instruction),
        ) == ("stone_assembly", None)

    def test_color_wording_does_not_accidentally_become_a_shape_change(self):
        spec = Spec.model_validate(RUBY)
        # The word "around" contains "round" but is not a request for a
        # round-cut stone. Shape detection must use complete words.
        assert resolve_target(
            spec,
            Annotation(
                section="stone",
                instruction="make the color around the center more saturated",
            ),
        ) == ("stone", None)

    def test_unresolvable_annotation_raises(self):
        spec = Spec.model_validate(RUBY)
        with pytest.raises(AnnotationUnresolved):
            resolve_target(spec, Annotation(instruction="just do something"))
        with pytest.raises(AnnotationUnresolved):
            resolve_target(spec, Annotation(ref="Z", instruction="x"))  # no such stone
        with pytest.raises(AnnotationUnresolved):
            # 'halo' is ambiguous here: three side-stone groups
            resolve_target(spec, Annotation(section="halo", instruction="x"))


class TestScopeGuard:
    def test_only_the_target_survives(self):
        """The crown: the model tries to change the centre stone AND the metal AND
        a side stone; only the centre stone change is kept."""
        current = Spec.model_validate(RUBY)
        proposed = copy.deepcopy(RUBY)
        proposed["stone"]["carat"] = 3.10                 # the intended change (A)
        proposed["metal"]["material"] = "gold"            # OUT of scope
        proposed["metal"]["karat"] = 18
        proposed["side_stones"][0]["count"] = 12          # OUT of scope
        edited = Spec.model_validate(proposed)

        guarded, changed, ignored = scope_guard(current, ("stone", None), edited)

        assert guarded.stone.carat == 3.10                # target applied
        assert guarded.metal == current.metal             # metal untouched
        assert guarded.side_stones == current.side_stones  # every side stone untouched
        assert any("stone.carat" in c for c in changed)
        assert any("metal" in i for i in ignored)         # discard is reported
        assert any("side_stones[0]" in i for i in ignored)

    def test_side_stone_target_leaves_siblings_alone(self):
        current = Spec.model_validate(RUBY)
        proposed = copy.deepcopy(RUBY)
        proposed["side_stones"][0]["count"] = 10          # intended (B)
        proposed["side_stones"][1]["count"] = 16          # OUT of scope
        proposed["stone"]["carat"] = 1.0                  # OUT of scope
        edited = Spec.model_validate(proposed)

        guarded, changed, ignored = scope_guard(current, ("side_stones", 0), edited)

        assert guarded.side_stones[0].count == 10
        assert guarded.side_stones[1] == current.side_stones[1]
        assert guarded.stone == current.stone
        assert any("side_stones[0].count" in c for c in changed)
        assert any("side_stones[1]" in i for i in ignored)
        assert any("stone" in i for i in ignored)

    def test_full_side_stone_inventory_can_add_and_remove_groups_only(self):
        current = Spec.model_validate(RUBY)
        proposed = copy.deepcopy(RUBY)
        proposed["side_stones"] = [
            {**proposed["side_stones"][0], "count": 10},
            {
                **proposed["side_stones"][1],
                "count": 4,
                "position": "shoulder_accent",
            },
        ]
        proposed["metal"]["material"] = "gold"          # OUT of scope
        proposed["metal"]["karat"] = 18
        proposed["band"]["width_mm"] = 3.5             # OUT of scope
        edited = Spec.model_validate(proposed)

        guarded, changed, ignored = scope_guard(
            current, ("side_stones", None), edited)

        assert guarded.side_stones == edited.side_stones
        assert len(guarded.side_stones) == 2
        assert guarded.metal == current.metal
        assert guarded.band == current.band
        assert any("side_stones" in path for path in changed)
        assert any("metal" in path for path in ignored)
        assert any("band.width_mm" in path for path in ignored)

    def test_center_shape_scope_keeps_only_stone_and_setting(self):
        current = Spec.model_validate(RUBY)
        proposed = copy.deepcopy(RUBY)
        proposed["stone"]["cut"] = "emerald_cut"
        proposed["setting"]["style"] = "4_prong_cathedral"
        proposed["setting"]["gallery_height_mm"] = 5.4
        proposed["band"]["width_mm"] = 3.0              # OUT of scope
        proposed["metal"]["finish"] = "satin"          # OUT of scope
        edited = Spec.model_validate(proposed)

        guarded, changed, ignored = scope_guard(
            current, ("stone_assembly", None), edited)

        assert guarded.stone == edited.stone
        assert guarded.setting == edited.setting
        assert guarded.band == current.band
        assert guarded.metal == current.metal
        assert any("stone.cut" in path for path in changed)
        assert any("setting" in path for path in changed)
        assert any("band.width_mm" in path for path in ignored)
        assert any("metal.finish" in path for path in ignored)


def _mock_plan(monkeypatch, result: EditResult):
    monkeypatch.setattr(agent_mod, "plan_edit", lambda instruction, current: result)


class TestAnnotateEndpoint:
    def test_scoped_edit_writes_new_version_touching_only_target(self, client, monkeypatch):
        did = _design(client)
        # the model over-reaches: it changes the ruby AND the metal
        edited = copy.deepcopy(RUBY)
        edited["stone"]["carat"] = 3.2
        edited["stone"]["dimensions_mm"]["depth"] = 5.0   # keep carat consistent
        edited["metal"]["material"] = "gold"              # will be discarded
        edited["metal"]["karat"] = 18
        _mock_plan(monkeypatch, EditResult(
            spec=Spec.model_validate(edited), isolate_ref="A",
            message="Ruby down to 3.2 ct."))

        r = client.post(f"/designs/{did}/annotate",
                        json={"ref": "A", "instruction": "make the ruby 3.2 ct",
                              "created_by": "usr_ana"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["new_version"] == 2
        assert body["target"] == "stone" and body["isolate_ref"] == "A"
        assert body["spec"]["stone"]["carat"] == 3.2
        # the metal over-reach was discarded and reported
        assert body["spec"]["metal"]["material"] == "platinum"
        assert any("metal" in f for f in body["ignored_fields"])

    def test_impossible_scoped_edit_saves_nothing(self, client, monkeypatch):
        did = _design(client)
        bad = copy.deepcopy(RUBY)
        bad["side_stones"][0]["carat"] = 0.20  # physically impossible for its mm
        _mock_plan(monkeypatch, EditResult(
            spec=Spec.model_validate(bad), isolate_ref="B",
            message="Halo stones up to 0.20 ct."))

        r = client.post(f"/designs/{did}/annotate",
                        json={"ref": "B", "instruction": "make each halo stone 0.20 ct"})
        assert r.status_code == 422, r.text
        body = r.json()
        assert body["rejected"] is True and body["target"] == "side_stones[0]"
        assert client.get(f"/designs/{did}/versions/2").status_code == 404

    def test_unresolved_annotation_is_422(self, client, monkeypatch):
        did = _design(client)
        # even without a key, resolution happens before any model call
        r = client.post(f"/designs/{did}/annotate",
                        json={"instruction": "make it prettier"})
        assert r.status_code == 422
        assert "ref" in r.json()["detail"] or "section" in r.json()["detail"]

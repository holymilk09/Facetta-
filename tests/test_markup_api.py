"""Markup-driven surgical edits: the designer draws on the piece, the agent
reads it, echoes its understanding, and — only after confirmation — changes
exactly what was marked while the linked design's spec moves in lockstep.

Vision, edit, and planner calls are all mocked; mask_from_markup and the
chain/version bookkeeping run for real.
"""

import base64
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import facetta.api.assets as assets_mod
import facetta.specagent as agent
from facetta.db import Base, get_db
from facetta.main import app

from conftest import HALO_SPEC


def _png(color=(200, 200, 200), size=(200, 300)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _marked(base: bytes) -> bytes:
    """The designer's canvas: a red circle + a stroke on the base render."""
    im = Image.open(io.BytesIO(base)).convert("RGB")
    d = ImageDraw.Draw(im)
    d.ellipse([60, 40, 140, 120], outline=(255, 0, 0), width=4)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


READING = {
    "annotations": [
        {"region_description": "the halo, upper arc",
         "change_instruction": "raise the melee to 1.3 mm",
         "target_section": "side_stones", "handwriting": "melee → 1.3",
         "confidence": 0.92}],
    "understood_as": "Understood as: (1) raise the halo melee to 1.3 mm — "
                     "nothing else changes.",
    "needs_clarification": False, "clarification": "",
}


@pytest.fixture
def client(monkeypatch):
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
    monkeypatch.setattr(assets_mod, "jewelry_render",
                        lambda *a, **k: (_png(), False))
    monkeypatch.setattr(assets_mod, "check_design_consistency",
                        lambda ref, cand: {"consistent": True,
                                           "differences": [],
                                           "severity": "none", "checked": True})
    yield TestClient(app)
    app.dependency_overrides.clear()


def _design(client) -> str:
    r = client.post("/designs", json={"created_by": "usr_ana",
                                      "spec": HALO_SPEC})
    assert r.status_code == 201, r.text
    return r.json()["design_id"]


def _linked_asset(client) -> tuple[str, str]:
    design_id = _design(client)
    r = client.post("/assets/render",
                    json={"piece_description": "a halo ring",
                          "design_id": design_id})
    assert r.status_code == 201, r.text
    return r.json()["asset_id"], design_id


class TestReadMarkup:
    def test_reader_normalizes_and_gates_confidence(self, monkeypatch):
        monkeypatch.setattr(agent, "_vision_json_2img",
                            lambda *a, **k: dict(READING))
        out = agent.read_markup(b"clean", b"marked")
        assert out["annotations"][0]["target_section"] == "side_stones"
        assert not out["needs_clarification"]
        low = dict(READING)
        low["annotations"] = [dict(READING["annotations"][0], confidence=0.3)]
        monkeypatch.setattr(agent, "_vision_json_2img", lambda *a, **k: low)
        out = agent.read_markup(b"clean", b"marked")
        assert out["needs_clarification"] and out["clarification"]

    def test_mask_from_markup_finds_the_strokes(self):
        clean = _png()
        marked = _marked(clean)
        mask = agent.mask_from_markup(clean, marked)
        im = Image.open(io.BytesIO(mask)).convert("L")
        assert im.getpixel((100, 40)) == 255       # on the circle → edit
        assert im.getpixel((10, 280)) == 0         # far away → preserve
        # different raster (a photographed printout) → no mask, honestly
        assert agent.mask_from_markup(clean, _png(size=(90, 90))) is None
        # identical images → no marks → None
        assert agent.mask_from_markup(clean, clean) is None


class TestMarkupEndpoints:
    def test_read_echoes_and_files_the_notes_leaf(self, client, monkeypatch):
        monkeypatch.setattr(assets_mod, "read_markup",
                            lambda clean, marked: dict(READING))
        aid, design_id = _linked_asset(client)
        marked = _marked(_png())
        r = client.post(f"/assets/{aid}/markup/read",
                        json={"marked_image_base64":
                              base64.b64encode(marked).decode()})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["understood_as"].startswith("Understood as")
        assert body["design_linked"] is True and body["design_id"] == design_id
        # the marked upload is an audit leaf, capability MARKUP_NOTES
        leaf = client.get(f"/assets/{body['markup_asset_id']}").json()
        assert leaf["capability"] == "MARKUP_NOTES"

    def test_unreadable_marks_are_a_422_question(self, client, monkeypatch):
        monkeypatch.setattr(assets_mod, "read_markup",
                            lambda clean, marked: {
                                "annotations": [], "understood_as": "",
                                "needs_clarification": True,
                                "clarification": "which stone did you circle?"})
        aid, _ = _linked_asset(client)
        r = client.post(f"/assets/{aid}/markup/read",
                        json={"marked_image_base64":
                              base64.b64encode(_png()).decode()})
        assert r.status_code == 422
        assert "which stone" in r.json()["detail"]

    def _mock_apply(self, monkeypatch, drift=0.02):
        import facetta.grokedit as grokedit
        from facetta.agent import ScopedEditResult
        from facetta.spec import Spec

        def fake_scoped(annotation, current):
            edited = current.model_dump(mode="json")
            edited["side_stones"][0]["dimensions_mm"]["length"] = 1.3
            edited["side_stones"][0]["dimensions_mm"]["width"] = 1.3
            edited["side_stones"][0]["dimensions_mm"]["depth"] = 0.85
            edited["side_stones"][0]["carat"] = 0.01
            return ScopedEditResult(
                spec=Spec.model_validate(edited), target="side_stones[0]",
                isolate_ref="B",
                changed_fields=["side_stones[0].dimensions_mm.length 4.1 → 1.3"],
                ignored_fields=[], message="melee to 1.3")

        monkeypatch.setattr(grokedit, "grok_plan_scoped_edit", fake_scoped)
        monkeypatch.setattr(
            assets_mod, "localized_edit",
            lambda image_bytes, **k: {"image": _png((90, 90, 90)),
                                      "changed": "halo", "frozen": "rest",
                                      "retried": False, "drift": drift,
                                      "cached": False})

    def test_apply_moves_image_and_spec_in_lockstep(self, client, monkeypatch):
        self._mock_apply(monkeypatch)
        aid, design_id = _linked_asset(client)
        r = client.post(f"/assets/{aid}/markup/apply", json={
            "annotations": [{
                "region_description": "the halo, upper arc",
                "change_instruction": "raise the melee to 1.3 mm",
                "target_section": "side_stones", "index": 0}]})
        assert r.status_code == 201, r.text
        body = r.json()
        step = body["steps"][0]
        assert step["spec_synced"] is True
        assert step["new_spec_version"] == 2
        assert "1.3" in step["changes_summary"]
        assert body["consistency"]["checked"] is True
        # the design really has a v2 with the new melee size
        v2 = client.get(f"/designs/{design_id}/versions/2").json()
        assert v2["side_stones"][0]["dimensions_mm"]["length"] == 1.3
        # and v1 is untouched
        v1 = client.get(f"/designs/{design_id}/versions/1").json()
        assert v1["side_stones"][0]["dimensions_mm"]["length"] == 4.1

    def test_sequential_annotations_chain_parent_to_child(self, client,
                                                          monkeypatch):
        self._mock_apply(monkeypatch)
        aid, _ = _linked_asset(client)
        r = client.post(f"/assets/{aid}/markup/apply", json={
            "annotations": [
                {"region_description": "the halo",
                 "change_instruction": "melee 1.3", "target_section": None},
                {"region_description": "the shank",
                 "change_instruction": "matte finish", "target_section": None},
            ]})
        assert r.status_code == 201, r.text
        steps = r.json()["steps"]
        history = client.get(f"/assets/{aid}/history").json()["history"]
        by_id = {h["asset_id"]: h for h in history}
        assert by_id[steps[1]["asset_id"]]["parent_asset_id"] == \
            steps[0]["asset_id"]
        assert by_id[steps[0]["asset_id"]]["parent_asset_id"] == aid

    def test_unlinked_chain_is_image_only(self, client, monkeypatch):
        self._mock_apply(monkeypatch)
        r = client.post("/assets/render", json={"piece_description": "a ring"})
        aid = r.json()["asset_id"]
        r = client.post(f"/assets/{aid}/markup/apply", json={
            "annotations": [{"region_description": "the halo",
                             "change_instruction": "melee 1.3",
                             "target_section": "side_stones", "index": 0}]})
        assert r.status_code == 201, r.text
        step = r.json()["steps"][0]
        assert step["spec_synced"] is False
        assert "link-design" in step["spec_note"]
        assert step["asset_id"]                    # the image edit still ran

    def test_impossible_spec_change_skips_the_image_edit_too(self, client,
                                                             monkeypatch):
        import facetta.grokedit as grokedit
        from facetta.agent import ScopedEditResult
        from facetta.spec import Spec

        def bad_scoped(annotation, current):
            edited = current.model_dump(mode="json")
            edited["stone"]["carat"] = 9.5          # physically impossible
            return ScopedEditResult(spec=Spec.model_validate(edited),
                                    target="stone", isolate_ref="A")

        monkeypatch.setattr(grokedit, "grok_plan_scoped_edit", bad_scoped)
        monkeypatch.setattr(
            assets_mod, "localized_edit",
            lambda image_bytes, **k: pytest.fail("image edit must not run"))
        aid, design_id = _linked_asset(client)
        r = client.post(f"/assets/{aid}/markup/apply", json={
            "annotations": [{"region_description": "the center",
                             "change_instruction": "9.5 carats",
                             "target_ref": "A"}]})
        assert r.status_code == 201
        step = r.json()["steps"][0]
        assert step["rejected"] is True and step["detail"]
        assert r.json()["final_asset_id"] is None
        # no new version was written either — lockstep or nothing
        versions = client.get(f"/designs/{design_id}").json()["versions"]
        assert len(versions) == 1

    def test_technical_drawing_letters_the_linked_spec(self, client,
                                                       monkeypatch):
        self._mock_apply(monkeypatch)
        monkeypatch.setattr(assets_mod, "generate_spec_sheet",
                            lambda image, **k: (_png((5, 5, 5)), {
                                "mode": "M", "piece_type": "RING_ENGAGEMENT",
                                "region": "DUAL", "factory_notes": []}, False))
        aid, design_id = _linked_asset(client)
        client.post(f"/assets/{aid}/markup/apply", json={
            "annotations": [{"region_description": "the halo",
                             "change_instruction": "melee 1.3",
                             "target_section": "side_stones", "index": 0}]})
        r = client.post(f"/assets/{aid}/technical-drawing",
                        json={"use_this_asset": True,
                              "facetta_template": True})
        assert r.status_code == 200, r.text
        body = r.json()
        # the panel lettered the design's LATEST version — v2, the markup edit
        assert body["spec_source"] == f"design:{design_id} v2"
        assert "1.3" in body["framed_svg"]         # the new melee size
        assert "ESTIMATED" not in body["framed_svg"]

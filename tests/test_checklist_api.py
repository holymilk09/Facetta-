"""The approval ritual over the API: tap YES/NO, the WHOOP no-note rule, the
agent-ready prefill, the understood-as echo, and the three pin modes.

Engines and the interpreter are mocked — a checklist tap must never touch the
network unless the designer explicitly asks for the interpretation.
"""

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import facetta.api.assets as assets_mod
from facetta.db import Base, get_db
from facetta.main import app

from conftest import HALO_SPEC


def _png(color=(200, 200, 200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (200, 300), color).save(buf, format="PNG")
    return buf.getvalue()


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
    yield TestClient(app)
    app.dependency_overrides.clear()


def _asset(client) -> str:
    r = client.post("/assets/render", json={"piece_description": "a halo ring"})
    assert r.status_code == 201, r.text
    return r.json()["asset_id"]


def _checklist(client, asset_id, mode="auto_pin") -> dict:
    r = client.post(f"/assets/{asset_id}/checklist",
                    json={"spec": HALO_SPEC, "mode": mode,
                          "created_by": "usr_ana"})
    assert r.status_code == 201, r.text
    return r.json()


def _approve_all(client, asset_id, body, skip=()):
    last = None
    for item in body["items"]:
        if item["key"] in skip:
            continue
        last = client.post(f"/assets/{asset_id}/checklist/respond",
                           json={"item_key": item["key"], "approved": True,
                                 "created_by": "usr_ana"})
        assert last.status_code == 201, last.text
    return last.json() if last else None


class TestChecklistLifecycle:
    def test_items_derive_from_the_spec(self, client):
        aid = _asset(client)
        body = _checklist(client, aid)
        keys = {i["key"] for i in body["items"]}
        assert {"stone", "side_stones[0]", "band", "ring_size"} <= keys
        assert body["status"]["all_approved"] is False
        r = client.get(f"/assets/{aid}/checklist")
        assert r.status_code == 200
        assert r.json()["pin_state"] == {"pinned": False, "gated": True}

    def test_no_spec_and_no_link_is_409(self, client):
        aid = _asset(client)
        r = client.post(f"/assets/{aid}/checklist", json={})
        assert r.status_code == 409
        assert "link-design" in r.json()["detail"]

    def test_no_without_note_is_422(self, client):
        aid = _asset(client)
        _checklist(client, aid)
        r = client.post(f"/assets/{aid}/checklist/respond",
                        json={"item_key": "band", "approved": False})
        assert r.status_code == 422
        assert "change note" in r.json()["detail"]

    def test_unknown_item_lists_valid_keys(self, client):
        aid = _asset(client)
        _checklist(client, aid)
        r = client.post(f"/assets/{aid}/checklist/respond",
                        json={"item_key": "tiara", "approved": True})
        assert r.status_code == 422 and "stone" in r.json()["detail"]

    def test_no_returns_the_agent_ready_prefill(self, client):
        aid = _asset(client)
        _checklist(client, aid)
        r = client.post(f"/assets/{aid}/checklist/respond",
                        json={"item_key": "band", "approved": False,
                              "note": "too heavy — width to 2.0"})
        assert r.status_code == 201, r.text
        cr = r.json()["change_request"]
        assert cr["workflow"] == "markup_read_then_apply"
        assert cr["annotation_prefill"]["target_section"] == "band"
        assert cr["annotation_prefill"]["change_instruction"] == \
            "too heavy — width to 2.0"
        assert cr["annotation_prefill"]["region_description"] == "the band"
        assert cr["markup_read"] == {
            "method": "POST",
            "endpoint": f"/assets/{aid}/markup/read",
            "body_requires": ["marked_image_base64"],
            "mutates_project": False,
        }
        assert cr["markup_apply"]["endpoint"] == \
            f"/assets/{aid}/markup/apply"
        assert cr["markup_apply"]["body"]["annotations"] == [
            cr["annotation_prefill"]]
        assert cr["endpoints"] == [
            f"POST /assets/{aid}/markup/read",
            f"POST /assets/{aid}/markup/apply",
        ]
        assert "annotate" not in cr and "localized_edit" not in cr
        # the halo stones item prefills its schedule ref + index
        r = client.post(f"/assets/{aid}/checklist/respond",
                        json={"item_key": "side_stones[0]", "approved": False,
                              "note": "melee to 1.3 mm"})
        cr = r.json()["change_request"]
        prefill = cr["annotation_prefill"]
        assert prefill["target_ref"] == "B" and prefill["index"] == 0

    def test_interpret_stores_the_understood_as_echo(self, client, monkeypatch):
        import facetta.grokedit as grokedit

        echo = {"understood_as": "Understood as: band width 2 → 2.2 mm; "
                                 "nothing else changes.",
                "action": "both", "instruction": "widen the band to 2.2 mm",
                "region_description": "the band", "target_section": "band",
                "confidence": 0.94, "clarification": "",
                "assistant_name": "Atelier"}
        monkeypatch.setattr(grokedit, "interpret_change_note",
                            lambda note, **k: echo)
        aid = _asset(client)
        _checklist(client, aid)
        r = client.post(f"/assets/{aid}/checklist/respond",
                        json={"item_key": "band", "approved": False,
                              "note": "bit thin, 2.2 wide", "interpret": True})
        assert r.status_code == 201, r.text
        assert r.json()["interpretation"] == echo
        # the echo is on the audit row
        answers = client.get(f"/assets/{aid}/checklist").json()["answers"]
        assert answers["band"]["understood_as"].startswith("Understood as")

    def test_audit_appends_and_latest_wins(self, client):
        aid = _asset(client)
        _checklist(client, aid)
        client.post(f"/assets/{aid}/checklist/respond",
                    json={"item_key": "stone", "approved": False,
                          "note": "wrong cut"})
        client.post(f"/assets/{aid}/checklist/respond",
                    json={"item_key": "stone", "approved": True})
        state = client.get(f"/assets/{aid}/checklist").json()
        assert state["answers"]["stone"]["approved"] is True
        assert "stone" not in state["status"]["outstanding"]


class TestPinModes:
    def test_auto_pin_pins_on_the_last_yes(self, client):
        aid = _asset(client)
        body = _checklist(client, aid, mode="auto_pin")
        last = _approve_all(client, aid, body)
        assert last["pinned"] is True and "pinned_version" in last
        assert client.get(f"/assets/{aid}").json()["pinned"] is True

    def test_gated_pin_409s_until_complete(self, client):
        aid = _asset(client)
        body = _checklist(client, aid, mode="explicit_pin")
        r = client.post(f"/assets/{aid}/pin")
        assert r.status_code == 409
        assert set(r.json()["outstanding"]) == {i["key"] for i in body["items"]}
        _approve_all(client, aid, body)
        # explicit mode never auto-pins — the designer taps pin themselves
        assert client.get(f"/assets/{aid}").json()["pinned"] is False
        assert client.post(f"/assets/{aid}/pin").status_code == 200

    def test_optional_mode_never_gates(self, client):
        aid = _asset(client)
        _checklist(client, aid, mode="optional")
        assert client.post(f"/assets/{aid}/pin").status_code == 200

    def test_no_checklist_pin_behaves_as_before(self, client):
        aid = _asset(client)
        assert client.post(f"/assets/{aid}/pin").status_code == 200

    def test_a_declined_item_blocks_the_gate(self, client):
        aid = _asset(client)
        body = _checklist(client, aid, mode="explicit_pin")
        _approve_all(client, aid, body, skip=("band",))
        client.post(f"/assets/{aid}/checklist/respond",
                    json={"item_key": "band", "approved": False,
                          "note": "narrower"})
        r = client.post(f"/assets/{aid}/pin")
        assert r.status_code == 409 and r.json()["outstanding"] == ["band"]

    def test_completed_checklist_letters_the_approval_on_the_sheet(
            self, client, monkeypatch):
        """The factory sheet carries the sign-off: 'approved N/N · who ·
        when', code-lettered from the approval record — never invented."""
        monkeypatch.setattr(assets_mod, "generate_spec_sheet",
                            lambda image, **k: (_png((5, 5, 5)), {
                                "mode": "M", "piece_type": "RING_ENGAGEMENT",
                                "region": "DUAL", "factory_notes": []}, False))
        aid = _asset(client)
        body = _checklist(client, aid, mode="auto_pin")
        _approve_all(client, aid, body)            # auto-pins
        r = client.post(f"/assets/{aid}/technical-drawing",
                        json={"facetta_template": True, "spec": HALO_SPEC})
        assert r.status_code == 200, r.text
        out = r.json()
        n = len(body["items"])
        assert out["approval"] == out["approval"]  # present
        assert f"approved {n}/{n} · usr_ana" in out["approval"]
        assert out["approval"] in out["framed_svg"]

    def test_unapproved_sheet_has_no_approval_line(self, client, monkeypatch):
        monkeypatch.setattr(assets_mod, "generate_spec_sheet",
                            lambda image, **k: (_png((5, 5, 5)), {
                                "mode": "M", "piece_type": "RING_ENGAGEMENT",
                                "region": "DUAL", "factory_notes": []}, False))
        aid = _asset(client)
        _checklist(client, aid, mode="optional")   # exists but incomplete
        client.post(f"/assets/{aid}/pin")
        r = client.post(f"/assets/{aid}/technical-drawing",
                        json={"facetta_template": True, "spec": HALO_SPEC})
        assert r.status_code == 200
        assert r.json()["approval"] is None
        assert "approved" not in r.json()["framed_svg"]

    def test_a_new_version_has_no_checklist(self, client, monkeypatch):
        monkeypatch.setattr(
            assets_mod, "localized_edit",
            lambda image_bytes, **k: {"image": _png((90, 90, 90)),
                                      "changed": "x", "frozen": "y",
                                      "retried": False, "drift": 0.01,
                                      "cached": False})
        aid = _asset(client)
        body = _checklist(client, aid)
        _approve_all(client, aid, body)
        child = client.post(f"/assets/{aid}/localized-edit",
                            json={"region_description": "the band",
                                  "change_instruction": "narrower"}
                            ).json()["asset_id"]
        assert client.get(f"/assets/{child}/checklist").status_code == 404

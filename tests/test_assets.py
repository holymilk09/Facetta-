"""The iteration chain: A → many C → pin → B on demand.

Designers always adjust, so MODE C is the primary loop. Under test (engines
mocked, zero network): every render/edit is an immutable asset with a parent;
history/compare/revert are chain reads; the manufacturing technical drawing
is gated by the PIN — it draws from the approved version, never silently from
"latest" — and five consecutive edits do not make drift blow up.
"""

import base64
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import facetta.api.assets as assets_mod
import facetta.specagent as agent_mod
from facetta.db import Base, get_db
from facetta.main import app


def _png(color) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (200, 300), color).save(buf, format="PNG")
    return buf.getvalue()


def _mask_top() -> bytes:
    """White (edit) over the top third, black (preserve) below."""
    m = Image.new("L", (200, 300), 0)
    for y in range(100):
        for x in range(200):
            m.putpixel((x, y), 255)
    buf = io.BytesIO()
    m.save(buf, format="PNG")
    return buf.getvalue()


ROOT_PNG = _png((200, 200, 200))
SUMMARY = {"mode": "MANUFACTURING_TECHNICAL_DRAWING",
           "piece_type": "EARRINGS_DROP", "region": "DUAL",
           "confirmed_from_reference": [], "designer_must_confirm": [],
           "factory_notes": [], "dimension_status": "nominal_from_reference",
           "disclaimer": "x"}


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


def _mock_engines(monkeypatch):
    """Renders return the root PNG; edits return a child almost identical to
    the parent (a few pixels change inside the editable top), so drift stays
    near zero hop after hop — the well-behaved-provider baseline."""
    monkeypatch.setattr(assets_mod, "jewelry_render",
                        lambda *a, **k: (ROOT_PNG, False))

    def fake_edit(image_bytes, **kwargs):
        im = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        for x in range(10):  # a small change inside the top (edit) region
            im.putpixel((x, 5), (255, 0, 0))
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        child = buf.getvalue()
        drift = None
        if kwargs.get("mask_bytes") is not None:
            drift = agent_mod._outside_drift(image_bytes, child,
                                             kwargs["mask_bytes"])
        return {"image": child,
                "changed": f"inside '{kwargs['region_description']}': "
                           f"{kwargs['change_instruction']}",
                "frozen": "everything outside: " + kwargs["region_description"],
                "retried": False, "drift": drift, "cached": False}

    monkeypatch.setattr(assets_mod, "localized_edit", fake_edit)


class TestIterationChain:
    def test_five_edits_pin_then_drawing_from_pinned(self, client, monkeypatch):
        """The founder's regression: 5× C on one chain → pin v4 → 1× B, and B
        draws from the PINNED asset, not the latest; drift never blows up."""
        _mock_engines(monkeypatch)
        captured = {}

        def fake_sheet(image_bytes, **kwargs):
            captured["source_bytes"] = image_bytes
            return (b"drawing-bytes", dict(SUMMARY), False)

        monkeypatch.setattr(assets_mod, "generate_spec_sheet", fake_sheet)

        r = client.post("/assets/render",
                        json={"piece_description": "marquise drop earring"})
        assert r.status_code == 201, r.text
        root = r.json()
        assert root["version"] == 1 and root["parent_asset_id"] is None

        mask_b64 = base64.b64encode(_mask_top()).decode()
        head = root
        drifts = []
        for i in range(5):
            r = client.post(f"/assets/{head['asset_id']}/localized-edit",
                            json={"region_description": "the ear hook",
                                  "change_instruction": f"adjust hook pass {i}",
                                  "mask_base64": mask_b64})
            assert r.status_code == 201, r.text
            child = r.json()
            assert child["parent_asset_id"] == head["asset_id"]
            assert child["version"] == i + 2
            drifts.append(child["drift"])
            head = child

        # five hops of a well-behaved edit: drift stays flat, never compounds
        assert all(d is not None and d < 0.05 for d in drifts)
        assert not all(a < b for a, b in zip(drifts, drifts[1:])), \
            "drift must not monotonically increase across the chain"

        # pin version 4 (the 3rd edit) — NOT the latest
        pinned_id = None
        r = client.get(f"/assets/{head['asset_id']}/history")
        history = r.json()["history"]
        assert len(history) == 6
        pinned_id = history[3]["asset_id"]          # version 4
        r = client.post(f"/assets/{pinned_id}/pin")
        assert r.status_code == 200
        assert r.json()["pinned_version"] == 4

        # B from any asset in the chain resolves the PIN, not the head
        r = client.post(f"/assets/{head['asset_id']}/technical-drawing",
                        json={})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["source_asset_id"] == pinned_id
        assert body["from_pinned_version"] == 4
        assert body["source_note"] == "From pinned version 4"
        # and it really drew from the pinned asset's bytes (the drawing draws
        # from the CLEAN stored bytes; the delivered b64 carries the client
        # accuracy disclaimer, so compare against the stamped form)
        from facetta.disclaimer import stamp_image
        v4 = client.get(f"/assets/{pinned_id}").json()
        assert stamp_image(captured["source_bytes"]) == \
            base64.b64decode(v4["image_b64"])

    def test_unpinned_chain_blocks_drawing_with_409(self, client, monkeypatch):
        _mock_engines(monkeypatch)
        r = client.post("/assets/render",
                        json={"piece_description": "a pendant"})
        asset_id = r.json()["asset_id"]
        r = client.post(f"/assets/{asset_id}/technical-drawing", json={})
        assert r.status_code == 409
        assert "pin" in r.json()["detail"]

    def test_use_this_asset_is_the_explicit_override(self, client, monkeypatch):
        _mock_engines(monkeypatch)
        monkeypatch.setattr(assets_mod, "generate_spec_sheet",
                            lambda image_bytes, **k: (b"d", dict(SUMMARY), False))
        r = client.post("/assets/render",
                        json={"piece_description": "a pendant"})
        asset_id = r.json()["asset_id"]
        r = client.post(f"/assets/{asset_id}/technical-drawing",
                        json={"use_this_asset": True})
        assert r.status_code == 200
        body = r.json()
        assert body["source_asset_id"] == asset_id
        assert body["from_pinned_version"] is None
        assert "override" in body["source_note"]

    def test_no_region_blocks_with_canvas_message(self, client, monkeypatch):
        _mock_engines(monkeypatch)
        r = client.post("/assets/render",
                        json={"piece_description": "a pendant"})
        asset_id = r.json()["asset_id"]
        r = client.post(f"/assets/{asset_id}/localized-edit",
                        json={"region_description": "  ",
                              "change_instruction": "make it nicer"})
        assert r.status_code == 422
        assert "select the area on the canvas" in r.json()["detail"]

    def test_revert_is_a_chain_read(self, client, monkeypatch):
        """Revert = the app selects the parent: parent_asset_id is on every
        response and the parent's image is addressable unchanged."""
        _mock_engines(monkeypatch)
        r = client.post("/assets/render",
                        json={"piece_description": "a pendant"})
        root = r.json()
        r = client.post(f"/assets/{root['asset_id']}/localized-edit",
                        json={"region_description": "the bail",
                              "change_instruction": "thicker bail"})
        child = r.json()
        parent = client.get(f"/assets/{child['parent_asset_id']}").json()
        assert parent["asset_id"] == root["asset_id"]
        assert parent["image_b64"] == root["image_b64"]   # immutable


class TestMultiView:
    """Extra angles are derived from the HERO render (design-locked), so the
    designer gets a consistent turntable in one request — never re-generated
    per angle (which would invent a different piece)."""

    def _mock(self, monkeypatch):
        monkeypatch.setattr(assets_mod, "jewelry_render",
                            lambda *a, **k: (_png((200, 200, 200)), False))
        seen = {}

        def fake_view_set(image_bytes, angles, **k):
            seen["source"] = image_bytes    # every angle derives from the hero
            return [{"angle": ang, "image": _png((10 * i, 20, 30)),
                     "cached": False} for i, ang in enumerate(angles, 1)]

        monkeypatch.setattr(assets_mod, "render_view_set", fake_view_set)
        return seen

    def test_render_with_angles_returns_a_view_set(self, client, monkeypatch):
        seen = self._mock(monkeypatch)
        r = client.post("/assets/render",
                        json={"piece_description": "a solitaire ring",
                              "angles": ["top", "front", "side"]})
        assert r.status_code == 201, r.text
        body = r.json()
        assert [v["angle"] for v in body["views"]] == ["top", "front", "side"]
        # every angle derived from the CLEAN hero bytes (views are design-locked
        # to the stored render); the delivered image_b64 carries the disclaimer,
        # so the source is the clean mock hero, not the stamped delivered bytes
        assert seen["source"] == _png((200, 200, 200))
        # each view is its own chain child of the hero
        for v in body["views"]:
            child = client.get(f"/assets/{v['asset_id']}").json()
            assert child["parent_asset_id"] == body["asset_id"]
            assert child["capability"] == "ANGLE_VIEW"

    def test_render_without_angles_is_unchanged(self, client, monkeypatch):
        self._mock(monkeypatch)
        r = client.post("/assets/render",
                        json={"piece_description": "a solitaire ring"})
        assert r.status_code == 201
        assert r.json()["views"] == []

    def test_views_on_existing_asset(self, client, monkeypatch):
        self._mock(monkeypatch)
        r = client.post("/assets/render",
                        json={"piece_description": "a ring"})
        asset_id = r.json()["asset_id"]
        r = client.post(f"/assets/{asset_id}/views",
                        json={"angles": ["top", "back"]})
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["parent_asset_id"] == asset_id
        assert [v["angle"] for v in body["views"]] == ["top", "back"]
        assert "three_quarter" in body["known_presets"]

    def test_view_instruction_is_design_locked(self):
        from facetta.specagent import compile_view_instruction

        text = compile_view_instruction("top")
        assert "IDENTITY LOCK" in text and "SAME piece" in text
        assert "top-down" in text            # the preset expanded
        assert "Only the camera" in text or "camera viewpoint changes" in text
        # a free-text angle passes through
        assert "from below" in compile_view_instruction("from below")


class TestWornValidation:
    """A worn shot is vision-validated: a ring across two fingers must never
    ship. The check re-rolls until the ring is on one finger, or refuses."""

    def test_retries_until_single_finger(self, monkeypatch):
        import facetta.specagent as agent
        calls = {"edit": 0}

        def fake_edit(image_bytes, instruction, model):
            calls["edit"] += 1
            return (b"IMG" + str(calls["edit"]).encode(), False)

        # first attempt fails the check, second passes
        checks = iter([
            {"single_finger": False, "one_hand": True, "anatomy_ok": True,
             "issue": "ring across two fingers"},
            {"single_finger": True, "one_hand": True, "anatomy_ok": True,
             "issue": ""}])
        monkeypatch.setattr(agent, "edit_image", fake_edit)
        monkeypatch.setattr(agent, "check_worn_render", lambda img: next(checks))

        r = agent.render_worn_view(b"hero", "hand", max_attempts=3)
        assert r["ok"] is True and r["attempts"] == 2
        assert calls["edit"] == 2

    def test_refuses_after_max_attempts(self, monkeypatch):
        import facetta.specagent as agent
        monkeypatch.setattr(agent, "edit_image",
                            lambda *a, **k: (b"BAD", False))
        monkeypatch.setattr(agent, "check_worn_render",
                            lambda img: {"single_finger": False, "one_hand": True,
                                         "anatomy_ok": True, "issue": "two fingers"})
        r = agent.render_worn_view(b"hero", "hand", max_attempts=2)
        assert r["ok"] is False and r["attempts"] == 2
        assert "finger" in r["issue"]

    def test_endpoint_does_not_file_a_rejected_worn_view(self, client, monkeypatch):
        monkeypatch.setattr(assets_mod, "jewelry_render",
                            lambda *a, **k: (_png((1, 1, 1)), False))

        def fake_view_set(image_bytes, angles, **k):
            # the hand shot failed validation; a normal angle passes
            return [{"angle": "top", "image": _png((2, 2, 2)), "cached": False,
                     "ok": True, "issue": ""},
                    {"angle": "hand", "image": _png((3, 3, 3)), "cached": False,
                     "ok": False, "issue": "ring across two fingers"}]

        monkeypatch.setattr(assets_mod, "render_view_set", fake_view_set)
        r = client.post("/assets/render",
                        json={"piece_description": "a ring",
                              "angles": ["top", "hand"]})
        assert r.status_code == 201, r.text
        views = {v["angle"]: v for v in r.json()["views"]}
        assert views["top"]["asset_id"] is not None
        # the rejected worn shot is flagged and NOT stored
        assert views["hand"]["ok"] is False
        assert views["hand"]["asset_id"] is None
        assert views["hand"]["rejected"] is True
        assert "finger" in views["hand"]["issue"]


class TestConsistencyValidation:
    """A derived view must be the SAME piece as the hero — same stones, same
    setting, and the SAME SIZE (a 2 ct centre must not read bigger on one
    skin tone than another, or the client is misled). A view that drifts the
    design is re-rolled, and refused if it never matches."""

    def test_rerolls_until_consistent(self, monkeypatch):
        import facetta.specagent as agent
        calls = {"edit": 0}

        def fake_edit(image_bytes, instruction, model):
            calls["edit"] += 1
            return (b"IMG" + str(calls["edit"]).encode(), False)

        # first derived view drifts the design (major), second matches
        checks = iter([
            {"consistent": False, "differences": ["stone bigger"],
             "severity": "major", "checked": True},
            {"consistent": True, "differences": [], "severity": "none",
             "checked": True}])
        monkeypatch.setattr(agent, "edit_image", fake_edit)
        monkeypatch.setattr(agent, "check_design_consistency",
                            lambda ref, cand: next(checks))

        r = agent.render_checked_view(b"hero", "top", max_attempts=3)
        assert r["ok"] is True and r["consistent"] is True
        assert r["attempts"] == 2 and calls["edit"] == 2

    def test_refuses_after_max_drift(self, monkeypatch):
        import facetta.specagent as agent
        monkeypatch.setattr(agent, "edit_image",
                            lambda *a, **k: (b"BAD", False))
        monkeypatch.setattr(agent, "check_design_consistency",
                            lambda ref, cand: {
                                "consistent": False,
                                "differences": ["halo count changed"],
                                "severity": "major", "checked": True})
        r = agent.render_checked_view(b"hero", "side", max_attempts=2)
        assert r["consistent"] is False and r["attempts"] == 2
        assert "halo count changed" in r["differences"]

    def test_minor_drift_is_tolerated(self, monkeypatch):
        import facetta.specagent as agent
        calls = {"edit": 0}

        def fake_edit(image_bytes, instruction, model):
            calls["edit"] += 1
            return (b"IMG", False)

        # a minor difference passes on the first try (no re-roll storm)
        monkeypatch.setattr(agent, "edit_image", fake_edit)
        monkeypatch.setattr(agent, "check_design_consistency",
                            lambda ref, cand: {
                                "consistent": True, "differences": ["reflection"],
                                "severity": "minor", "checked": True})
        r = agent.render_checked_view(b"hero", "front", max_attempts=3)
        assert r["attempts"] == 1 and calls["edit"] == 1

    def test_worn_view_gated_on_both_finger_and_design(self, monkeypatch):
        """A hand shot must pass the single-finger check AND stay the same
        design — the worn view's two-layer gate."""
        import facetta.specagent as agent
        monkeypatch.setattr(agent, "edit_image",
                            lambda *a, **k: (b"IMG", False))
        monkeypatch.setattr(agent, "check_worn_render",
                            lambda img: {"single_finger": True, "one_hand": True,
                                         "anatomy_ok": True, "gesture_ok": True,
                                         "issue": ""})
        seen = {"consistency": 0}

        def fake_consistency(ref, cand):
            seen["consistency"] += 1
            return {"consistent": True, "differences": [], "severity": "none",
                    "checked": True}

        monkeypatch.setattr(agent, "check_design_consistency", fake_consistency)
        r = agent.render_checked_view(b"hero", "hand", max_attempts=2)
        assert r["ok"] is True and r["consistent"] is True
        assert seen["consistency"] == 1        # design also verified for worn

    def test_offensive_gesture_is_rejected(self, monkeypatch):
        """The rude-gesture net: a hand making an isolated-finger gesture fails
        the worn check even if it is otherwise on one finger."""
        import facetta.specagent as agent
        assert agent._worn_ok({"single_finger": True, "one_hand": True,
                               "anatomy_ok": True, "gesture_ok": False}) is False
        assert agent._worn_ok({"single_finger": True, "one_hand": True,
                               "anatomy_ok": True, "gesture_ok": True}) is True

    def test_can_disable_consistency_check(self, monkeypatch):
        import facetta.specagent as agent
        monkeypatch.setattr(agent, "edit_image",
                            lambda *a, **k: (b"IMG", False))

        def boom(ref, cand):
            raise AssertionError("consistency should not be called when disabled")

        monkeypatch.setattr(agent, "check_design_consistency", boom)
        r = agent.render_checked_view(b"hero", "top", check_consistency=False)
        assert r["consistent"] is True and r["attempts"] == 1

    def test_endpoint_does_not_file_a_drifted_view(self, client, monkeypatch):
        monkeypatch.setattr(assets_mod, "jewelry_render",
                            lambda *a, **k: (_png((1, 1, 1)), False))

        def fake_view_set(image_bytes, angles, **k):
            # 'top' matches the hero; 'front' drifted the design
            return [
                {"angle": "top", "image": _png((2, 2, 2)), "cached": False,
                 "ok": True, "consistent": True, "differences": [], "issue": ""},
                {"angle": "front", "image": _png((3, 3, 3)), "cached": False,
                 "ok": True, "consistent": False,
                 "differences": ["stone reads larger"], "issue": ""}]

        monkeypatch.setattr(assets_mod, "render_view_set", fake_view_set)
        r = client.post("/assets/render",
                        json={"piece_description": "a ring",
                              "angles": ["top", "front"]})
        assert r.status_code == 201, r.text
        views = {v["angle"]: v for v in r.json()["views"]}
        assert views["top"]["asset_id"] is not None
        # the drifted view is flagged and NOT stored
        assert views["front"]["consistent"] is False
        assert views["front"]["asset_id"] is None
        assert views["front"]["rejected"] is True
        assert "larger" in views["front"]["differences"][0]


class TestSpinVideo:
    """The showcase clip: a slow spin from the render, design-locked. The mp4
    lives on a media host that a network policy may gate, so bytes are
    optional — the url always comes back."""

    def test_spin_prompt_is_design_locked_and_gentle(self):
        from facetta.specagent import compile_spin_prompt

        p = compile_spin_prompt("turntable")
        assert "EXACT piece" in p and "do not redesign" in p
        assert "slow" in p and ("turntable" in p or "rotation" in p)
        assert "watermark" not in p or "no text or watermark" in p

    def test_endpoint_with_bytes_stores_a_video_child(self, client, monkeypatch):
        from facetta.render import VideoResult
        monkeypatch.setattr(assets_mod, "jewelry_render",
                            lambda *a, **k: (_png((1, 1, 1)), False))
        monkeypatch.setattr(
            assets_mod, "render_spin_video",
            lambda image_bytes, **k: VideoResult(
                "https://media.example/clip.mp4", b"MP4DATA", 8, False))
        r = client.post("/assets/render", json={"piece_description": "a ring"})
        aid = r.json()["asset_id"]
        r = client.post(f"/assets/{aid}/video", json={"motion": "turntable"})
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["video_url"] == "https://media.example/clip.mp4"
        assert body["duration_seconds"] == 8
        assert base64.b64decode(body["video_b64"]) == b"MP4DATA"
        child = client.get(f"/assets/{body['asset_id']}").json()
        assert child["capability"] == "SPIN_VIDEO"
        assert child["parent_asset_id"] == aid

    def test_endpoint_without_bytes_returns_url_only(self, client, monkeypatch):
        """Media host gated: the clip exists at a url but the server has no
        bytes — no child asset, a note, and still a 201."""
        from facetta.render import VideoResult
        monkeypatch.setattr(assets_mod, "jewelry_render",
                            lambda *a, **k: (_png((1, 1, 1)), False))
        monkeypatch.setattr(
            assets_mod, "render_spin_video",
            lambda image_bytes, **k: VideoResult(
                "https://vidgen.example/clip.mp4", None, 8, False))
        r = client.post("/assets/render", json={"piece_description": "a ring"})
        aid = r.json()["asset_id"]
        r = client.post(f"/assets/{aid}/video", json={})
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["video_url"] == "https://vidgen.example/clip.mp4"
        assert body["video_b64"] is None and body["asset_id"] is None
        assert "media host" in body["note"]

    def test_generate_video_polls_then_caches(self, monkeypatch, tmp_path):
        """The async loop: submit → poll pending → done → fetch mp4 → cache."""
        import facetta.render as render_mod
        from facetta.render import generate_video

        monkeypatch.setattr(render_mod, "CACHE_DIR", tmp_path)
        monkeypatch.setattr(render_mod, "_provider_key", lambda env: "k")
        calls = {"poll": 0, "get_mp4": 0}

        class Resp:
            def __init__(self, code, js=None, content=b""):
                self.status_code = code
                self._js = js or {}
                self.content = content

            def raise_for_status(self):
                pass

            def json(self):
                return self._js

        import httpx

        def fake_post(url, **k):
            return Resp(200, {"request_id": "rid-1"})

        def fake_get(url, **k):
            if url.endswith("/clip.mp4"):
                calls["get_mp4"] += 1
                return Resp(200, content=b"MP4BYTES")
            calls["poll"] += 1
            if calls["poll"] < 2:
                return Resp(202, {"status": "pending", "progress": 40})
            return Resp(200, {"status": "done",
                              "video": {"url": "https://m/clip.mp4", "duration": 8}})

        monkeypatch.setattr(httpx, "post", fake_post)
        monkeypatch.setattr(httpx, "get", fake_get)

        v1 = generate_video(b"\x89PNG\r\n\x1a\nx", "spin", sleep=lambda s: None)
        assert v1.data == b"MP4BYTES" and v1.duration == 8 and v1.cached is False
        # second call for the same (image, prompt, model) is served from disk
        v2 = generate_video(b"\x89PNG\r\n\x1a\nx", "spin", sleep=lambda s: None)
        assert v2.data == b"MP4BYTES" and v2.cached is True
        assert calls["get_mp4"] == 1  # provider fetched once, then cached


class TestGlobalRestyle:
    def test_inference_routes_whole_piece_changes(self):
        from facetta.specagent import infer_capability

        assert infer_capability("make it more art deco everywhere") == \
            "GLOBAL_RESTYLE"
        assert infer_capability("widen the whole shank") == "GLOBAL_RESTYLE"
        assert infer_capability("restyle the overall look") == "GLOBAL_RESTYLE"
        # localized language still routes localized
        assert infer_capability("change only this part") == "LOCALIZED_EDIT"

    def test_instruction_is_reference_locked_without_freeze(self):
        from facetta.specagent import compile_global_restyle_instruction

        text = compile_global_restyle_instruction("more milgrain everywhere")
        assert "IDENTITY LOCK" in text and "SAME design" in text
        assert "across the whole piece" in text
        assert "FORBIDDEN" not in text          # no region freeze — that's the point

    def test_endpoint_returns_warning_not_drift_gate(self, client, monkeypatch):
        _mock_engines(monkeypatch)
        monkeypatch.setattr(
            assets_mod, "global_restyle",
            lambda image_bytes, **k: {"image": _png((90, 60, 30)),
                                      "changed": "across the whole piece: x",
                                      "frozen": "piece identity",
                                      "warning": "global restyle — compare",
                                      "cached": False})
        r = client.post("/assets/render",
                        json={"piece_description": "a pendant"})
        asset_id = r.json()["asset_id"]
        r = client.post(f"/assets/{asset_id}/global-restyle",
                        json={"instruction": "make it bolder everywhere"})
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["capability"] == "GLOBAL_RESTYLE"
        assert "warning" in body and "drift" not in body["warning"]
        assert body["parent_asset_id"] == asset_id

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
        # and it really drew from the pinned asset's bytes
        v4 = client.get(f"/assets/{pinned_id}").json()
        assert captured["source_bytes"] == base64.b64decode(v4["image_b64"])

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
        hero_png = base64.b64decode(body["image_b64"])
        assert [v["angle"] for v in body["views"]] == ["top", "front", "side"]
        # every angle was derived from the hero render's bytes, design-locked
        assert seen["source"] == hero_png
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

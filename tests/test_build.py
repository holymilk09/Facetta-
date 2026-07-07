"""The one-call build: brief in, the whole piece out.

Generation, vision, and the client render are mocked; the point under test is
the composition — the assistant's output choice decides which visual layers
come back, a downstream render hiccup degrades to a warning (never loses the
spec), and persist=true saves a design the annotation loop can edit.
"""

import base64
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import facetta.api.specs as specs_mod
import facetta.concept as concept_mod
from facetta.concept import DesignRead
from facetta.db import Base, get_db
from facetta.main import app

def _real_png(color=(210, 205, 198)) -> bytes:
    import io as _io

    from PIL import Image
    buf = _io.BytesIO()
    Image.new("RGB", (600, 900), color).save(buf, format="PNG")
    return buf.getvalue()


FAKE_PNG = _real_png()   # a decodable concept image so the render-matched sheet works
RENDER_PNG = b"\x89PNG\r\n\x1a\nclient-render"


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


def _mock_origination(monkeypatch):
    """Grok invents + vision reads are mocked; complete_design/validate run for real
    so the returned spec is genuinely buildable."""
    monkeypatch.setattr(concept_mod, "generate_concept",
                        lambda brief, model="grok_direct", variant=0: (FAKE_PNG, False))
    monkeypatch.setattr(concept_mod, "read_design",
                        lambda image, brief="": DesignRead(
                            halo=True, species="emerald", cut="emerald",
                            center_length_mm=12, center_width_mm=9,
                            metal_material="platinum", setting_style="bezel"))


class TestBuild:
    def test_both_returns_concept_spec_sheet_and_render(self, client, monkeypatch):
        _mock_origination(monkeypatch)
        monkeypatch.setattr(specs_mod, "render_finished_image",
                            lambda spec, *a, **k: (RENDER_PNG, False))

        r = client.post("/specs/build", json={"brief": "art deco emerald halo ring",
                                              "output": "both"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert base64.b64decode(body["concept_image_b64"]) == FAKE_PNG
        assert body["spec"]["template"] == "halo_prong"
        assert body["spec"]["setting"]["style"] == "bezel"      # setting flowed through
        assert body["sheet_svg"].startswith("<svg")             # factory sheet present
        assert base64.b64decode(body["client_render_b64"]) == RENDER_PNG
        assert body["warnings"] == []

    def test_sheet_only_skips_the_render(self, client, monkeypatch):
        _mock_origination(monkeypatch)
        called = {"render": False}

        def _should_not_run(*a, **k):
            called["render"] = True
            return (RENDER_PNG, False)

        monkeypatch.setattr(specs_mod, "render_finished_image", _should_not_run)
        r = client.post("/specs/build", json={"brief": "emerald halo ring",
                                              "output": "sheet"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["sheet_svg"].startswith("<svg")
        assert body["client_render_b64"] is None
        assert called["render"] is False           # render engine never touched

    def test_render_failure_is_a_warning_not_a_failure(self, client, monkeypatch):
        _mock_origination(monkeypatch)
        from facetta.render import RenderUnavailable

        def boom(spec, *a, **k):
            raise RenderUnavailable("render provider failed: blocked")

        monkeypatch.setattr(specs_mod, "render_finished_image", boom)
        r = client.post("/specs/build", json={"brief": "emerald halo ring",
                                              "output": "both"})
        assert r.status_code == 200, r.text          # the spec still ships
        body = r.json()
        assert body["client_render_b64"] is None
        assert body["sheet_svg"].startswith("<svg")
        assert any("client render unavailable" in w for w in body["warnings"])

    def test_persist_saves_a_design_ready_to_annotate(self, client, monkeypatch):
        _mock_origination(monkeypatch)
        monkeypatch.setattr(specs_mod, "render_finished_image",
                            lambda spec, *a, **k: (RENDER_PNG, False))

        r = client.post("/specs/build", json={"brief": "emerald halo ring",
                                              "output": "sheet", "persist": True,
                                              "created_by": "usr_ana"})
        assert r.status_code == 200, r.text
        body = r.json()
        did = body["design_id"]
        assert did and body["version"] == 1
        assert body["spec"]["design_id"] == did      # stored spec carries identity
        # the saved version is real and addressable
        got = client.get(f"/designs/{did}/versions/1")
        assert got.status_code == 200
        assert got.json()["template"] == "halo_prong"

    def test_earring_brief_builds_the_drop_archetype(self, client, monkeypatch):
        import io as _io

        from PIL import Image
        buf = _io.BytesIO()
        Image.new("RGB", (600, 900), (210, 205, 198)).save(buf, format="PNG")
        real_png = buf.getvalue()
        # the archetype is built WITH origination: an earring read → an earring
        monkeypatch.setattr(concept_mod, "generate_concept",
                            lambda brief, model="grok_direct", variant=0: (real_png, False))
        monkeypatch.setattr(concept_mod, "read_design",
                            lambda image, brief="": DesignRead(
                                jewelry_type="earring", halo=True, species="diamond",
                                cut="marquise", center_length_mm=14, center_width_mm=9,
                                metal_material="gold", metal_color="yellow"))
        monkeypatch.setattr(specs_mod, "render_finished_image",
                            lambda spec, *a, **k: (RENDER_PNG, False))

        r = client.post("/specs/build", json={"brief": "modern marquise drop earring",
                                              "output": "both"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["spec"]["template"] == "deco_drop_earring"    # earring, not a ring
        assert body["spec"]["drop"]["overall_length_mm"] > 0
        assert "DROP EARRING" in body["sheet_svg"]                # native dimensioned sheet
        # the render-matched sheet: the concept image IS the drawing + lettered dims
        assert body["sheet_over_render_svg"] is not None
        assert "overall length" in body["sheet_over_render_svg"]
        assert base64.b64decode(body["client_render_b64"]) == RENDER_PNG

    def test_missing_key_is_503(self, client, monkeypatch):
        from facetta.render import RenderUnavailable

        def boom(brief, model="grok_direct", variant=0):
            raise RenderUnavailable("no XAI_KEY configured — set it")

        monkeypatch.setattr(concept_mod, "generate_concept", boom)
        r = client.post("/specs/build", json={"brief": "a ring", "output": "both"})
        assert r.status_code == 503

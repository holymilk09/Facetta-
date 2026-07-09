"""The Jewelry Manufacturing Spec Agent: the AGENT draws, math only assists.

Every provider path is mocked at module level (the vision helper, the edit
primitive, httpx.post) — this environment carries live keys, so a missed mock
would silently hit the network. The points under test: the prompt pack
compiles correctly, the validated spec's numbers reach the prompt as text,
the pipeline degrades (summary) and propagates (sheet) on the right failures,
edits are cached by content, and the module never touches the deterministic
drawing code.
"""

import base64
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import facetta.api.specs as specs_mod
import facetta.render as render_mod
import facetta.specagent as agent
from facetta.main import app
from facetta.render import RenderUnavailable
from facetta.spec import Spec

PNG = b"\x89PNG\r\n\x1a\nrender"


def _real_png(size=(600, 900), color=(255, 255, 255)) -> bytes:
    """A decodable PNG — the official frame reads the drawing's size."""
    import io

    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


REAL_PNG = _real_png()

SUMMARY = {"mode": agent.TASK_MODE, "piece_type": "EARRINGS_DROP",
           "region": "DUAL",
           "confirmed_from_reference": ["drop silhouette"],
           "designer_must_confirm": ["hook gauge"],
           "factory_notes": ["cast frame"],
           "dimension_status": "nominal_from_reference",
           "disclaimer": agent.DISCLAIMER}


@pytest.fixture
def drop_spec() -> Spec:
    path = (Path(__file__).parent.parent / "docs" / "examples"
            / "marquise_drop_earring.json")
    return Spec.model_validate(json.loads(path.read_text()))


class TestCompileSheetInstruction:
    def test_mode_region_and_universal_suffix(self):
        text = agent.compile_sheet_instruction("EARRINGS_DROP", "US")
        assert "drop earrings manufacturing technical drawing" in text
        assert "side profile showing drop length" in text  # the mode's views
        assert "inches optional on shank lines" in text    # the US region line
        assert agent.G0_SUFFIX in text                     # the G0 tail
        assert text.endswith(agent.HONESTY_RULE)           # honesty always last

    def test_all_13_modes_open_with_the_task_line(self):
        assert len(agent.MODES) == 13
        for mode in agent.MODES:
            text = agent.compile_sheet_instruction(mode)
            assert text.startswith(agent.TASK_LINE)        # founder's opener
            assert agent.G0_SUFFIX in text
            assert text.endswith(agent.HONESTY_RULE)

    def test_default_instruction_keeps_the_model_drawn_title_block(self):
        text = agent.compile_sheet_instruction("RING_ENGAGEMENT")
        assert "Title block with METAL, JOB REF, REV A." in text
        assert "the platform's official template" not in text
        assert "Never invent designer names" in text

    def test_templated_draws_clean_and_letters_nothing(self):
        # the factory-sheet path: Grok draws the actual piece, writes NO text;
        # the code panel letters every number. No title block, no stray text.
        text = agent.compile_sheet_instruction("RING_ENGAGEMENT",
                                               templated=True)
        assert "Title block with METAL" not in text
        assert "write NO text of ANY kind" in text
        assert "no title block" in text
        assert "Never invent designer names" in text       # honesty rule stays
        assert text.startswith(agent.TASK_LINE)

    def test_templated_forbids_all_painted_text(self):
        # Grok can't reliably letter text ('Pullish', 'G6.91') and invented
        # phantom 'PLAN'/'SECTION A-A'. Templated mode forbids ALL text so the
        # drawing is clean and the code panel owns every number and label.
        text = agent.compile_sheet_instruction("RING_ENGAGEMENT",
                                               templated=True)
        for banned in ("'PLAN'", "'SECTION'", "'TBD'", "no numbers",
                       "no title block", "no legend"):
            assert banned in text, banned
        assert "mark TBD" not in text          # no TBD-leader flooding
        assert "Dimension lines with arrowheads" not in text
        # untemplated legacy mode still lets the model letter its own numbers
        assert "write NO text of ANY kind" not in agent.compile_sheet_instruction(
            "RING_ENGAGEMENT")
        # the legibility repair pass inherits the no-text rule
        assert "write NO text of ANY kind" in agent._legibility_instruction(
            templated=True)

    def test_terminology_constants_exist_for_the_app(self):
        assert agent.TASK_MODE == "MANUFACTURING_TECHNICAL_DRAWING"
        assert agent.UI_LABELS["button"] == "Create manufacturing drawing"
        assert agent.UI_LABELS["subtitle"] == (
            "True-scale views, dimensions, materials & stones for production")
        assert agent.UI_LABELS["synonyms"] == agent.SYNONYMS_LINE
        assert "factory drawing" in agent.SYNONYMS_LINE
        assert agent.TASK_LINE in agent.MASTER_SYSTEM      # near the top
        assert agent.SYNONYMS_LINE in agent.MASTER_SYSTEM

    def test_dims_block_is_designer_authoritative(self):
        text = agent.compile_sheet_instruction(
            "RING_ENGAGEMENT", "DUAL",
            dims=["center stone: round brilliant diamond 6.5 mm"],
            notes="keep the cathedral shoulders")
        assert "Designer-authoritative dimensions" in text
        assert "- center stone: round brilliant diamond 6.5 mm" in text
        assert "Designer notes: keep the cathedral shoulders" in text
        assert "mark TBD with a leader line" in text       # the TBD policy

    def test_no_dims_no_block(self):
        text = agent.compile_sheet_instruction("PENDANT")
        assert "Designer-authoritative dimensions" not in text

    def test_unknown_mode_and_region_raise(self):
        with pytest.raises(ValueError):
            agent.compile_sheet_instruction("TIARA")
        with pytest.raises(ValueError):
            agent.compile_sheet_instruction("PENDANT", region="JP")


class TestAuthoritativeDims:
    def test_marquise_drop_earring_numbers_reach_the_text(self, drop_spec):
        text = "\n".join(agent.authoritative_dims(drop_spec))
        assert "marquise diamond 14 × 9 × 5.4 mm" in text   # center stone
        assert "3.832 ct" in text
        assert "halo stones: 20 ×" in text                  # the halo count
        assert "overall drop length: 37 mm" in text
        assert "18k yellow gold" in text
        assert "prong 4, 4 prongs" in text                  # setting, as stated

    def test_only_stdlib_and_spec_are_imported(self):
        # math is ASSISTANCE: the agent must not import anything that draws
        src = Path(agent.__file__).read_text()
        banned = re.compile(r"(?<![A-Za-z_])(svg_sheet|plate|prototype)(?![A-Za-z_])")
        assert banned.search(src) is None, banned.search(src)
        assert "facetta.plate" not in src
        assert "facetta.prototype" not in src
        assert "facetta.svg_sheet" not in src


class TestRouteDesign:
    def test_parses_the_router_json(self, monkeypatch):
        monkeypatch.setattr(agent, "_vision_json",
                            lambda system, image, text: {
                                "mode": "RING_ENGAGEMENT", "region": "US",
                                "confidence": 0.92, "occlusion": "med",
                                "extra_field": "ignored"})
        route = agent.route_design(PNG, "engagement ring, US client")
        assert route.mode == "RING_ENGAGEMENT"
        assert route.region == "US"
        assert route.confidence == 0.92
        assert route.occlusion == "med"

    def test_unknown_mode_coerces_to_generic(self, monkeypatch):
        monkeypatch.setattr(agent, "_vision_json",
                            lambda system, image, text: {
                                "mode": "TIARA", "region": "Mars",
                                "confidence": 0.4, "occlusion": "high"})
        route = agent.route_design(PNG)
        assert route.mode == "GENERIC"
        assert route.region == "DUAL"

    def test_provider_failure_raises(self, monkeypatch):
        def boom(system, image, text):
            raise RenderUnavailable("vision inspect failed: blocked")

        monkeypatch.setattr(agent, "_vision_json", boom)
        with pytest.raises(RenderUnavailable):
            agent.route_design(PNG)


class TestGenerateSpecSheet:
    def test_returns_sheet_summary_cached(self, monkeypatch):
        edits = []

        def fake_edit(image, instruction, model="grok_direct", variant=0):
            edits.append(instruction)
            return b"sheet", False

        monkeypatch.setattr(agent, "edit_image", fake_edit)
        monkeypatch.setattr(agent, "inspect_render",
                            lambda image, notes, mode, region: dict(SUMMARY))

        sheet, summary, cached = agent.generate_spec_sheet(
            PNG, mode="EARRINGS_DROP")
        assert sheet == b"sheet" and cached is False
        assert summary["mode"] == agent.TASK_MODE     # the CAPABILITY
        assert summary["piece_type"] == "EARRINGS_DROP"
        assert len(edits) == 1
        assert agent.G0_SUFFIX in edits[0]
        assert edits[0].endswith(agent.HONESTY_RULE)

    def test_legibility_makes_exactly_two_edit_calls(self, monkeypatch):
        edits = []

        def fake_edit(image, instruction, model="grok_direct", variant=0):
            edits.append((image, instruction))
            return b"sheet-" + bytes([len(edits)]), False

        monkeypatch.setattr(agent, "edit_image", fake_edit)
        monkeypatch.setattr(agent, "inspect_render",
                            lambda image, notes, mode, region: dict(SUMMARY))

        sheet, _, _ = agent.generate_spec_sheet(
            PNG, mode="PENDANT", legibility=True)
        assert len(edits) == 2
        assert edits[1][0] == b"sheet-\x01"        # G6 repairs the FIRST sheet
        assert edits[1][1] == agent.G6_LEGIBILITY  # verbatim repair prompt
        assert sheet == b"sheet-\x02"

    def test_legibility_repair_stays_honest(self):
        # both modes: the repair pass closes with the same honesty rule as
        # the first edit — no invented job refs or dates on the second pass
        assert agent.G6_LEGIBILITY.endswith(agent.HONESTY_RULE)

    def test_templated_legibility_repair_keeps_clean_margins(self, monkeypatch):
        # legibility=True + templated=True: the repair pass must not undo
        # the clean-margins rule by reinstating the model-drawn title block,
        # and it must close with the honesty rule
        edits = []

        def fake_edit(image, instruction, model="grok_direct", variant=0):
            edits.append(instruction)
            return b"sheet-" + bytes([len(edits)]), False

        monkeypatch.setattr(agent, "edit_image", fake_edit)
        monkeypatch.setattr(agent, "inspect_render",
                            lambda image, notes, mode, region: dict(SUMMARY))

        agent.generate_spec_sheet(PNG, mode="PENDANT", legibility=True,
                                  templated=True)
        assert len(edits) == 2
        assert "Title block with METAL" not in edits[1]
        assert "write NO text of ANY kind" in edits[1]      # clean repair pass
        assert edits[1].endswith(agent.HONESTY_RULE)

    def test_summary_hiccup_degrades_but_the_sheet_ships(self, monkeypatch):
        def inspect_boom(image, notes, mode, region):
            raise RenderUnavailable("vision inspect failed: 429")

        monkeypatch.setattr(agent, "inspect_render", inspect_boom)
        monkeypatch.setattr(agent, "edit_image",
                            lambda image, instruction, model="grok_direct", variant=0:
                            (b"sheet", True))

        sheet, summary, cached = agent.generate_spec_sheet(PNG, mode="BROOCH")
        assert sheet == b"sheet" and cached is True
        assert summary["mode"] == agent.TASK_MODE
        assert summary["piece_type"] == "BROOCH"
        assert summary["region"] == "DUAL"
        assert set(summary) == {"mode", "piece_type", "region",
                                "confirmed_from_reference",
                                "designer_must_confirm", "factory_notes",
                                "dimension_status", "disclaimer"}
        assert summary["dimension_status"] == "nominal_from_reference"
        assert any("summary unavailable" in n for n in summary["factory_notes"])

    def test_spec_picks_the_mode_and_injects_dims(self, monkeypatch, drop_spec):
        edits = []

        def fake_edit(image, instruction, model="grok_direct", variant=0):
            edits.append(instruction)
            return b"sheet", False

        monkeypatch.setattr(agent, "edit_image", fake_edit)
        monkeypatch.setattr(agent, "inspect_render",
                            lambda image, notes, mode, region: dict(SUMMARY))
        # no router call: the spec's own record decides the mode
        monkeypatch.setattr(agent, "route_design",
                            lambda *a, **k: pytest.fail("router must not run"))

        _, summary, _ = agent.generate_spec_sheet(PNG, spec=drop_spec)
        assert summary["piece_type"] == "EARRINGS_DROP"  # from MODE_FOR_TEMPLATE
        # the validated spec's numbers were injected → designer_supplied
        assert summary["dimension_status"] == "designer_supplied"
        assert "marquise diamond 14 × 9 × 5.4 mm" in edits[0]
        assert "Designer-authoritative dimensions" in edits[0]

    def test_templated_reaches_the_edit_instruction(self, monkeypatch):
        edits = []

        def fake_edit(image, instruction, model="grok_direct", variant=0):
            edits.append(instruction)
            return b"sheet", False

        monkeypatch.setattr(agent, "edit_image", fake_edit)
        monkeypatch.setattr(agent, "inspect_render",
                            lambda image, notes, mode, region: dict(SUMMARY))

        agent.generate_spec_sheet(PNG, mode="PENDANT", templated=True)
        assert "Title block with METAL" not in edits[0]
        assert "write NO text of ANY kind" in edits[0]       # clean drawing
        assert "mark TBD" not in edits[0]
        assert edits[0].endswith(agent.HONESTY_RULE)

    def test_router_fills_mode_and_default_region(self, monkeypatch):
        monkeypatch.setattr(agent, "route_design",
                            lambda image, notes="": agent.Route(
                                mode="PENDANT", region="EU", confidence=0.8))
        monkeypatch.setattr(agent, "inspect_render",
                            lambda image, notes, mode, region: dict(
                                SUMMARY, piece_type=mode, region=region))
        monkeypatch.setattr(agent, "edit_image",
                            lambda image, instruction, model="grok_direct", variant=0:
                            (b"sheet", False))

        _, summary, _ = agent.generate_spec_sheet(PNG)
        assert summary["piece_type"] == "PENDANT"
        assert summary["region"] == "EU"             # default DUAL → router's call


class TestEditImageCache:
    def test_identical_edits_pay_the_provider_once(self, monkeypatch, tmp_path):
        monkeypatch.setattr(render_mod, "CACHE_DIR", tmp_path)
        monkeypatch.setattr(render_mod, "_provider_key", lambda env: "test:key")
        calls = []

        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"data": [{"b64_json":
                                  base64.b64encode(b"edited").decode()}]}

        import httpx

        def fake_post(url, **kwargs):
            calls.append(url)
            # the provider must receive our render and instruction
            assert kwargs["json"]["image"]["url"].startswith(
                "data:image/png;base64,")
            assert agent.G0_SUFFIX in kwargs["json"]["prompt"]
            return FakeResponse()

        monkeypatch.setattr(httpx, "post", fake_post)

        instruction = agent.compile_sheet_instruction("PENDANT")
        a, cached_a = render_mod.edit_image(PNG, instruction)
        b, cached_b = render_mod.edit_image(PNG, instruction)
        assert a == b == b"edited"
        assert (cached_a, cached_b) == (False, True)
        assert len(calls) == 1                       # paid once, served forever

    def test_unknown_model_fails_loudly(self):
        with pytest.raises(RenderUnavailable) as err:
            render_mod.edit_image(PNG, "x", model="dalle_1999")
        assert "grok_direct" in str(err.value)


class TestTechnicalDrawingEndpoint:
    def test_returns_sheet_and_echoed_summary(self, monkeypatch):
        # facetta_template=false is the raw-drawing escape hatch
        monkeypatch.setattr(specs_mod, "generate_spec_sheet",
                            lambda image, **kwargs: (PNG, dict(SUMMARY), False))
        r = TestClient(app).post("/specs/technical-drawing", json={
            "image_base64": base64.b64encode(PNG).decode(),
            "notes": "modern drop", "facetta_template": False})
        assert r.status_code == 200, r.text
        body = r.json()
        assert base64.b64decode(body["sheet_b64"]) == PNG
        assert body["media_type"] == "image/png"
        assert body["mode"] == "EARRINGS_DROP"       # echoed from the summary
        assert body["region"] == "DUAL"
        assert body["summary"]["disclaimer"] == agent.DISCLAIMER
        assert body["cached"] is False
        assert body["framed_svg"] is None            # raw mode: no frame

    def test_official_template_is_the_default(self, monkeypatch):
        """The founder's rule as the default: a plain request gets the
        official sheet — Grok's clean drawing in the code-lettered frame.
        The self-lettered legacy mode only comes from an explicit opt-out."""
        seen = {}

        def fake_generate(image, **kwargs):
            seen.update(kwargs)
            return REAL_PNG, dict(SUMMARY), False

        monkeypatch.setattr(specs_mod, "generate_spec_sheet", fake_generate)
        r = TestClient(app).post("/specs/technical-drawing", json={
            "image_base64": base64.b64encode(PNG).decode()})
        assert r.status_code == 200, r.text
        assert seen["templated"] is True             # clean-drawing instruction
        assert r.json()["framed_svg"].startswith("<svg")

    def test_agent_sheet_alias_still_answers(self, monkeypatch):
        monkeypatch.setattr(specs_mod, "generate_spec_sheet",
                            lambda image, **kwargs: (PNG, dict(SUMMARY), False))
        r = TestClient(app).post("/specs/agent-sheet", json={
            "image_base64": base64.b64encode(PNG).decode(),
            "facetta_template": False})
        assert r.status_code == 200, r.text
        assert base64.b64decode(r.json()["sheet_b64"]) == PNG

    def test_facetta_template_frames_the_drawing(self, monkeypatch):
        seen = {}

        def fake_generate(image, **kwargs):
            seen.update(kwargs)
            return REAL_PNG, dict(SUMMARY), False

        monkeypatch.setattr(specs_mod, "generate_spec_sheet", fake_generate)
        r = TestClient(app).post("/specs/technical-drawing", json={
            "image_base64": base64.b64encode(PNG).decode(),
            "facetta_template": True, "signature": "Ana V."})
        assert r.status_code == 200, r.text
        body = r.json()
        assert seen["templated"] is True             # clean-margin instruction
        assert body["framed_svg"].startswith("<svg")
        assert "FACETTA" in body["framed_svg"]       # the official masthead
        assert "Ana V." in body["framed_svg"]        # the designer's hand
        assert "dsn_pending · v1" in body["framed_svg"]  # no spec: placeholders

    def test_assist_specs_letters_an_estimated_panel(self, monkeypatch):
        """The ballpark designer's assist: no spec → Grok vision-reads the
        RENDER, code letters the panel marked ESTIMATED, and the same
        estimates ride back to prefill a spec form. Never painted text."""
        monkeypatch.setattr(specs_mod, "generate_spec_sheet",
                            lambda image, **kwargs: (REAL_PNG, dict(SUMMARY),
                                                     False))
        est = {"stones": [{"qty": 1, "type": "diamond oval brilliant",
                           "size_mm": "8.5 × 6.5", "carat_each": 1.5,
                           "confidence": 0.7},
                          {"qty": 8, "type": "diamond round brilliant",
                           "size_mm": "1.4 × 1.4", "carat_each": None,
                           "confidence": 0.4}],
               "metal": "18k white gold, high polish",
               "measurements": [{"label": "band width", "value": "~2 mm",
                                 "confidence": 0.3}],
               "scaled": False, "scale_anchor": None}
        monkeypatch.setattr(agent, "read_sheet_specs",
                            lambda image, **kwargs: est)
        r = TestClient(app).post("/specs/technical-drawing", json={
            "image_base64": base64.b64encode(PNG).decode(),
            "facetta_template": True, "assist_specs": True})
        assert r.status_code == 200, r.text
        body = r.json()
        svg = body["framed_svg"]
        assert "ESTIMATED SPECIFICATIONS" in svg
        assert "diamond oval brilliant" in svg
        assert "confirm every value before production" in svg
        assert "estimated from render" in svg          # the footer line
        assert body["estimated_specs"] == est          # the form-prefill ride

    def test_assist_is_skipped_when_a_spec_letters_the_panel(self, monkeypatch,
                                                             drop_spec):
        # a validated record always wins: assist must not even be called
        monkeypatch.setattr(specs_mod, "generate_spec_sheet",
                            lambda image, **kwargs: (REAL_PNG, dict(SUMMARY),
                                                     False))
        monkeypatch.setattr(agent, "read_sheet_specs",
                            lambda image: pytest.fail("assist must not run"))
        r = TestClient(app).post("/specs/technical-drawing", json={
            "image_base64": base64.b64encode(PNG).decode(),
            "facetta_template": True, "assist_specs": True,
            "spec": drop_spec.model_dump(mode="json")})
        assert r.status_code == 200, r.text
        body = r.json()
        assert "STONE SCHEDULE" in body["framed_svg"]  # the record panel
        assert "ESTIMATED SPECIFICATIONS" not in body["framed_svg"]
        assert body["estimated_specs"] is None

    def test_read_sheet_specs_normalizes_the_vision_read(self, monkeypatch):
        monkeypatch.setattr(agent, "_vision_json", lambda *a, **k: {
            "stones": [{"qty": "2", "type": "sapphire pear",
                        "size_mm": "7 × 5"},
                       {"no_type": True}],           # junk entry dropped
            "measurements": [["drop length", "38 mm"], ["bad"]],
        })
        est = agent.read_sheet_specs(b"img")
        assert est["stones"] == [{"qty": 2, "type": "sapphire pear",
                                  "size_mm": "7 × 5", "carat_each": None,
                                  "confidence": 0.5}]
        assert est["metal"] == "TBD"                  # missing → honest TBD
        assert est["measurements"] == [{"label": "drop length",
                                        "value": "38 mm", "confidence": 0.5}]
        assert est["scaled"] is False and est["scale_anchor"] is None

    def test_missing_key_is_503(self, monkeypatch):
        def boom(image, **kwargs):
            raise RenderUnavailable("no XAI_KEY configured — set it")

        monkeypatch.setattr(specs_mod, "generate_spec_sheet", boom)
        r = TestClient(app).post("/specs/agent-sheet", json={
            "image_base64": base64.b64encode(PNG).decode()})
        assert r.status_code == 503

    def test_bad_base64_is_422(self, monkeypatch):
        monkeypatch.setattr(specs_mod, "generate_spec_sheet",
                            lambda image, **kwargs: pytest.fail("must not run"))
        r = TestClient(app).post("/specs/agent-sheet", json={
            "image_base64": "not base64!!!"})
        assert r.status_code == 422

    def test_invalid_spec_is_422_before_any_call(self, monkeypatch, drop_spec):
        monkeypatch.setattr(specs_mod, "generate_spec_sheet",
                            lambda image, **kwargs: pytest.fail("must not run"))
        bad = drop_spec.model_dump(mode="json")
        bad["stone"]["carat"] = 99.0                 # physically impossible
        r = TestClient(app).post("/specs/agent-sheet", json={
            "image_base64": base64.b64encode(PNG).decode(), "spec": bad})
        assert r.status_code == 422
        assert r.json()["detail"]                    # carries the issues

    def test_unknown_mode_is_422(self, monkeypatch):
        def raise_value_error(image, **kwargs):
            raise ValueError("unknown mode 'TIARA'")

        monkeypatch.setattr(specs_mod, "generate_spec_sheet", raise_value_error)
        r = TestClient(app).post("/specs/agent-sheet", json={
            "image_base64": base64.b64encode(PNG).decode(), "mode": "TIARA"})
        assert r.status_code == 422


class TestBuildWiring:
    """POST /specs/build now ships the agent-drawn factory sheet; the
    parametric artifacts come only on the explicit include_cad_sheet request
    (Section H hard rule) — same fixture pattern as test_build.py."""

    @pytest.fixture
    def client(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool

        from facetta.db import Base, get_db

        engine = create_engine("sqlite://",
                               connect_args={"check_same_thread": False},
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

    def _mock_origination(self, monkeypatch):
        import io

        from PIL import Image

        import facetta.concept as concept_mod
        from facetta.concept import DesignRead

        buf = io.BytesIO()
        Image.new("RGB", (600, 900), (210, 205, 198)).save(buf, format="PNG")
        png = buf.getvalue()
        monkeypatch.setattr(concept_mod, "generate_concept",
                            lambda brief, model="grok_direct", variant=0:
                            (png, False))
        monkeypatch.setattr(concept_mod, "read_design",
                            lambda image, brief="": DesignRead(
                                halo=True, species="emerald", cut="emerald",
                                center_length_mm=12, center_width_mm=9,
                                metal_material="platinum"))
        monkeypatch.setattr(specs_mod, "render_from_spec",
                            lambda spec, *a, **k: (png, False))

    def test_build_ships_the_technical_drawing(self, client, monkeypatch):
        self._mock_origination(monkeypatch)
        seen = {}

        def fake_generate(image, **kwargs):
            seen.update(kwargs)
            return REAL_PNG, dict(SUMMARY, piece_type="RING_ENGAGEMENT"), False

        monkeypatch.setattr(specs_mod, "generate_spec_sheet", fake_generate)
        r = client.post("/specs/build", json={"brief": "emerald halo ring",
                                              "output": "sheet",
                                              "house": "Maison V",
                                              "signature": "Ana V."})
        assert r.status_code == 200, r.text
        body = r.json()
        assert base64.b64decode(body["technical_drawing_b64"]) == REAL_PNG
        assert body["manufacturing_summary"]["piece_type"] == "RING_ENGAGEMENT"
        # the build's agent call is templated: the official frame letters
        # identity, so the model must leave clean margins
        assert seen["templated"] is True
        framed = body["technical_drawing_framed_svg"]
        assert framed.startswith("<svg")
        assert "MAISON V" in framed.upper()           # the build's branding
        assert "Ana V." in framed
        assert "made with FACETTA" in framed
        # Section H hard rule: the agent transaction never calls the legacy
        # math spec module — no parametric artifacts unless explicitly asked
        assert body["sheet_svg"] is None
        assert body["sheet_over_render_svg"] is None
        # the validated spec rode along as the assistance numbers
        assert seen["spec"] is not None
        assert seen["spec"].template == "halo_prong"

    def test_cad_handoff_is_a_separate_explicit_request(self, client,
                                                        monkeypatch):
        self._mock_origination(monkeypatch)
        monkeypatch.setattr(specs_mod, "generate_spec_sheet",
                            lambda image, **kwargs: (REAL_PNG,
                                                     dict(SUMMARY), False))
        r = client.post("/specs/build", json={"brief": "emerald halo ring",
                                              "output": "sheet",
                                              "include_cad_sheet": True})
        assert r.status_code == 200, r.text
        body = r.json()
        assert base64.b64decode(body["technical_drawing_b64"]) == REAL_PNG
        assert body["sheet_svg"].startswith("<svg")   # explicit CAD handoff
        assert body["sheet_over_render_svg"] is not None

    def test_agent_drawing_failure_is_a_warning_not_a_failure(self, client,
                                                              monkeypatch):
        self._mock_origination(monkeypatch)

        def boom(image, **kwargs):
            raise RenderUnavailable("render provider failed: 429")

        monkeypatch.setattr(specs_mod, "generate_spec_sheet", boom)
        r = client.post("/specs/build", json={"brief": "emerald halo ring",
                                              "output": "both"})
        assert r.status_code == 200, r.text           # the spec still ships
        body = r.json()
        assert body["technical_drawing_b64"] is None
        assert body["manufacturing_summary"] is None
        assert body["technical_drawing_framed_svg"] is None
        assert any("agent spec sheet unavailable" in w for w in body["warnings"])

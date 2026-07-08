"""MODE A (JEWELRY_RENDER) + MODE C (LOCALIZED_EDIT) + the capability router.

Every provider path is mocked (this environment carries live keys). The
points under test: the Section 1 inference rules and their precedence, the
Section 4A render prompt compiles cleanly (no 'Metal: .' artifacts, no
dimension strings), the Section 4C preservation contract carries PRESERVE /
EDIT SCOPE / FORBIDDEN in every edit prompt, the drift QA retries exactly
once with stronger preserve language and keeps the lower-drift child, and
the three new endpoints follow the module's error conventions.
"""

import base64
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import facetta.api.specs as specs_mod
import facetta.specagent as agent
from facetta.main import app
from facetta.render import RenderUnavailable

PNG = b"\x89PNG\r\n\x1a\nrender"


def _png(pixels, size=(40, 40)) -> bytes:
    """A real grayscale PNG from a fill value or a per-pixel function."""
    img = Image.new("L", size)
    if callable(pixels):
        img.putdata([pixels(x, y) for y in range(size[1])
                     for x in range(size[0])])
    else:
        img.paste(pixels, (0, 0, *size))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _right_half_mask(size=(40, 40)) -> bytes:
    """White (=edit) right half, black (=preserve) left half."""
    return _png(lambda x, y: 255 if x >= size[0] // 2 else 0, size)


PARENT = _png(200)                                   # uniform gray parent
MASK = _right_half_mask()
# identical to the parent outside the mask, changed inside the white region
CHILD_CLEAN = _png(lambda x, y: 30 if x >= 20 else 200)
# drifted everywhere — the preserve region moved too
CHILD_DRIFTED = _png(60)


class TestInferCapability:
    def test_render_signals(self):
        for text in ("render this ring", "make it realistic",
                     "show me the piece", "a client visualization",
                     "product photo please"):
            assert agent.infer_capability(text) == "JEWELRY_RENDER"

    def test_drawing_signals(self):
        for text in ("technical drawing please", "send it to the factory",
                     "manufacturing handoff", "add the dimensions",
                     "orthographic views", "ready for production",
                     "make the spec sheet"):
            assert agent.infer_capability(text) == \
                "MANUFACTURING_TECHNICAL_DRAWING"

    def test_edit_signals(self):
        for text in ("change only this part", "I highlight the prongs",
                     "edit the selected area", "don't change the rest",
                     "widen this area", "just the gallery"):
            assert agent.infer_capability(text) == "LOCALIZED_EDIT"

    def test_edit_signals_win_over_render_and_drawing(self):
        # an edit OF a render is an edit, not a new render
        assert agent.infer_capability(
            "highlight the shank and render it wider") == "LOCALIZED_EDIT"
        assert agent.infer_capability(
            "on the technical drawing, change just the bail") == \
            "LOCALIZED_EDIT"

    def test_drawing_signals_win_over_render(self):
        assert agent.infer_capability(
            "render the factory drawing") == "MANUFACTURING_TECHNICAL_DRAWING"

    def test_case_insensitive_and_default(self):
        assert agent.infer_capability("SHOW ME the ring") == "JEWELRY_RENDER"
        # the default journey starts at MODE A
        assert agent.infer_capability("an emerald halo ring") == \
            "JEWELRY_RENDER"

    def test_capabilities_constant(self):
        assert agent.CAPABILITIES == (
            "JEWELRY_RENDER", "MANUFACTURING_TECHNICAL_DRAWING",
            "LOCALIZED_EDIT", "GLOBAL_RESTYLE")
        for capability in agent.CAPABILITIES:
            assert capability in agent.AGENT_SYSTEM


class TestAgentSystem:
    def test_contract_sections_present(self):
        text = agent.AGENT_SYSTEM
        assert "never mix behaviors" in text
        assert "DEFAULT JOURNEY" in text
        assert "MODE INFERENCE" in text
        assert "DOMAIN GUARDRAILS" in text
        assert "ERROR HANDLING" in text
        assert "CHAT RESPONSE FORMAT" in text
        assert "YOU MUST NOT" in text
        assert "ask the user to select the area" in text.lower() \
            or "select the area" in text

    def test_top_level_message_is_not_the_mode_b_system(self):
        assert agent.AGENT_SYSTEM != agent.MASTER_SYSTEM
        assert agent.TASK_LINE in agent.MASTER_SYSTEM  # MODE B's stays intact


class TestCompileRenderInstruction:
    def test_verbatim_spine_and_full_clauses(self):
        text = agent.compile_render_instruction(
            "emerald halo engagement ring", metal="platinum",
            stones="2ct emerald center, diamond melee halo",
            setting_details="Four-prong cathedral setting")
        assert text.startswith(
            "Photorealistic fine jewelry product photograph, "
            "emerald halo engagement ring.")
        assert "Metal: platinum." in text
        assert "Stones: 2ct emerald center, diamond melee halo." in text
        assert "Four-prong cathedral setting." in text
        assert ("Studio lighting, soft gradient neutral background, sharp "
                "focus, no watermark, no text overlay, no factory "
                "dimensions.") in text
        assert text.endswith("Professional jewelry campaign quality, "
                             "accurate proportions, three-quarter product "
                             "view.")

    def test_empty_clauses_are_omitted_cleanly(self):
        text = agent.compile_render_instruction("gold signet ring")
        assert "Metal:" not in text
        assert "Stones:" not in text
        assert "Metal: ." not in text
        assert ": ." not in text
        assert ". ." not in text                     # no empty-clause stutter
        assert "  " not in text

    def test_no_dimension_strings_in_a_beauty_render(self):
        text = agent.compile_render_instruction("diamond pendant")
        assert "no factory dimensions" in text
        assert "mm" not in text
        assert "TBD" not in text

    def test_view_angle_is_configurable(self):
        text = agent.compile_render_instruction("ring", view_angle="top-down")
        assert text.endswith("accurate proportions, top-down.")


class TestJewelryRender:
    def test_compiles_and_generates(self, monkeypatch):
        seen = {}

        def fake_generate(prompt, model="grok_direct", variant=0):
            seen.update(prompt=prompt, model=model, variant=variant)
            return b"image", False

        monkeypatch.setattr(agent, "generate_image", fake_generate)
        image, cached = agent.jewelry_render(
            "ruby cluster ring", metal="18k yellow gold", variant=2)
        assert (image, cached) == (b"image", False)
        assert seen["variant"] == 2
        assert seen["prompt"].startswith(
            "Photorealistic fine jewelry product photograph, "
            "ruby cluster ring.")
        assert "Metal: 18k yellow gold." in seen["prompt"]


class TestCompileLocalizedEditInstruction:
    def test_preservation_contract_blocks(self):
        text = agent.compile_localized_edit_instruction(
            "upper gallery and six prongs", "make the prongs longer")
        assert text.startswith("Jewelry render edit.")
        assert ("PRESERVE: All design elements outside 'upper gallery and "
                "six prongs'") in text
        assert ("EDIT SCOPE: Inside 'upper gallery and six prongs' only: "
                "make the prongs longer.") in text
        assert "FORBIDDEN: Any change outside the highlighted region" in text
        assert "no crop; no zoom; no global redesign" in text
        assert "CRITICAL" not in text                # only when strengthened

    def test_technical_kind_adds_the_view_box_rule(self):
        text = agent.compile_localized_edit_instruction(
            "the bail detail inset", "thicken the bail wall", kind="technical")
        assert text.startswith("Jewelry technical drawing edit.")
        assert ("Do not move other view boxes or unrelated dimension "
                "strings.") in text
        render_text = agent.compile_localized_edit_instruction(
            "the bail detail inset", "thicken the bail wall", kind="render")
        assert "view boxes" not in render_text

    def test_strengthen_prepends_critical_and_repeats_preserve(self):
        text = agent.compile_localized_edit_instruction(
            "the shank", "add milgrain", strengthen=True)
        assert text.startswith("CRITICAL:")
        assert text.count("PRESERVE: All design elements outside") == 2

    def test_unknown_kind_raises(self):
        with pytest.raises(ValueError):
            agent.compile_localized_edit_instruction("a", "b", kind="sketch")


class TestOutsideDrift:
    def test_identical_images_zero(self):
        assert agent._outside_drift(PARENT, PARENT, MASK) == 0.0

    def test_change_only_inside_the_white_region_is_zero(self):
        assert agent._outside_drift(PARENT, CHILD_CLEAN, MASK) == \
            pytest.approx(0.0, abs=0.01)

    def test_fully_different_outside_the_mask_is_high(self):
        drift = agent._outside_drift(PARENT, CHILD_DRIFTED, MASK)
        assert drift == pytest.approx((200 - 60) / 255, abs=0.02)
        assert drift > 0.18

    def test_child_and_mask_are_resized_to_the_parent(self):
        small_child = _png(200, size=(20, 20))
        small_mask = _right_half_mask(size=(20, 20))
        assert agent._outside_drift(PARENT, small_child, small_mask) == 0.0


class TestLocalizedEdit:
    def test_missing_region_or_change_raises(self):
        with pytest.raises(ValueError, match="select the area"):
            agent.localized_edit(PARENT, region_description="  ",
                                 change_instruction="longer prongs")
        with pytest.raises(ValueError, match="select the area"):
            agent.localized_edit(PARENT, region_description="the prongs",
                                 change_instruction="")

    def test_happy_path_without_mask(self, monkeypatch):
        calls = []

        def fake_edit(image, instruction, model="grok_direct"):
            calls.append(instruction)
            return b"child", False

        monkeypatch.setattr(agent, "edit_image", fake_edit)
        result = agent.localized_edit(
            PNG, region_description="upper gallery",
            change_instruction="longer prongs")
        assert result["image"] == b"child"
        assert result["changed"] == "inside 'upper gallery': longer prongs"
        assert result["frozen"] == "everything outside: upper gallery"
        assert result["retried"] is False
        assert result["drift"] is None               # no mask, no QA
        assert result["cached"] is False
        assert len(calls) == 1
        assert "PRESERVE:" in calls[0] and "EDIT SCOPE:" in calls[0] \
            and "FORBIDDEN:" in calls[0]             # the contract, always

    def test_clean_edit_with_mask_passes_qa_without_retry(self, monkeypatch):
        calls = []

        def fake_edit(image, instruction, model="grok_direct"):
            calls.append(instruction)
            return CHILD_CLEAN, False

        monkeypatch.setattr(agent, "edit_image", fake_edit)
        result = agent.localized_edit(
            PARENT, region_description="right half of the piece",
            change_instruction="darken the stones", mask_bytes=MASK)
        assert result["image"] == CHILD_CLEAN
        assert result["retried"] is False
        assert result["drift"] == pytest.approx(0.0, abs=0.01)
        assert len(calls) == 1

    def test_drift_triggers_exactly_one_stronger_retry(self, monkeypatch):
        calls = []

        def fake_edit(image, instruction, model="grok_direct"):
            calls.append(instruction)
            # first attempt drifts everywhere; the strengthened retry is clean
            return (CHILD_DRIFTED, False) if len(calls) == 1 \
                else (CHILD_CLEAN, False)

        monkeypatch.setattr(agent, "edit_image", fake_edit)
        result = agent.localized_edit(
            PARENT, region_description="right half of the piece",
            change_instruction="darken the stones", mask_bytes=MASK)
        assert len(calls) == 2                       # exactly one retry
        assert "CRITICAL" not in calls[0]
        assert calls[1].startswith("CRITICAL:")      # stronger preserve
        assert calls[1] != calls[0]                  # a different cache key
        assert result["retried"] is True
        assert result["image"] == CHILD_CLEAN        # the lower-drift child
        assert result["drift"] == pytest.approx(0.0, abs=0.01)

    def test_worse_retry_keeps_the_first_child(self, monkeypatch):
        worse = _png(0)                              # drifts even further

        def fake_edit(image, instruction, model="grok_direct"):
            return (worse, False) if instruction.startswith("CRITICAL") \
                else (CHILD_DRIFTED, True)

        monkeypatch.setattr(agent, "edit_image", fake_edit)
        result = agent.localized_edit(
            PARENT, region_description="right half",
            change_instruction="darken", mask_bytes=MASK)
        assert result["retried"] is True
        assert result["image"] == CHILD_DRIFTED      # lower drift wins
        assert result["cached"] is True              # kept with its child
        assert result["drift"] == pytest.approx((200 - 60) / 255, abs=0.02)


class TestJewelryRenderEndpoint:
    def test_returns_image_and_the_compiled_prompt(self, monkeypatch):
        seen = {}

        def fake_generate(prompt, model="grok_direct", variant=0):
            seen.update(prompt=prompt, variant=variant)
            return PNG, False

        monkeypatch.setattr(specs_mod, "generate_image", fake_generate)
        r = TestClient(app).post("/specs/jewelry-render", json={
            "piece_description": "emerald halo ring",
            "metal": "platinum", "variant": 1})
        assert r.status_code == 200, r.text
        body = r.json()
        assert base64.b64decode(body["image_b64"]) == PNG
        assert body["media_type"] == "image/png"
        assert body["capability"] == "JEWELRY_RENDER"
        assert body["prompt"] == seen["prompt"]      # what the engine was told
        assert "Metal: platinum." in body["prompt"]
        assert "no factory dimensions" in body["prompt"]
        assert seen["variant"] == 1

    def test_missing_key_is_503(self, monkeypatch):
        def boom(prompt, model="grok_direct", variant=0):
            raise RenderUnavailable("no XAI_KEY configured — set it")

        monkeypatch.setattr(specs_mod, "generate_image", boom)
        r = TestClient(app).post("/specs/jewelry-render", json={
            "piece_description": "emerald halo ring"})
        assert r.status_code == 503

    def test_provider_failure_is_502(self, monkeypatch):
        def boom(prompt, model="grok_direct", variant=0):
            raise RenderUnavailable("generation provider failed: 429")

        monkeypatch.setattr(specs_mod, "generate_image", boom)
        r = TestClient(app).post("/specs/jewelry-render", json={
            "piece_description": "emerald halo ring"})
        assert r.status_code == 502

    def test_extra_fields_are_rejected(self):
        r = TestClient(app).post("/specs/jewelry-render", json={
            "piece_description": "a ring", "mode": "B"})
        assert r.status_code == 422


class TestLocalizedEditEndpoint:
    def test_returns_edit_and_contract_echo(self, monkeypatch):
        seen = {}

        def fake_edit(image_bytes, **kwargs):
            seen.update(kwargs)
            return {"image": PNG,
                    "changed": "inside 'the prongs': make them longer",
                    "frozen": "everything outside: the prongs",
                    "retried": True, "drift": 0.02, "cached": False}

        monkeypatch.setattr(specs_mod, "localized_edit", fake_edit)
        r = TestClient(app).post("/specs/localized-edit", json={
            "image_base64": base64.b64encode(PNG).decode(),
            "region_description": "the prongs",
            "change_instruction": "make them longer",
            "mask_base64": base64.b64encode(MASK).decode(),
            "kind": "technical"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert base64.b64decode(body["image_b64"]) == PNG
        assert body["media_type"] == "image/png"
        assert body["capability"] == "LOCALIZED_EDIT"
        assert body["changed"] == "inside 'the prongs': make them longer"
        assert body["frozen"] == "everything outside: the prongs"
        assert body["retried"] is True
        assert body["drift"] == 0.02
        assert body["cached"] is False
        assert seen["kind"] == "technical"
        assert seen["mask_bytes"] == MASK            # decoded, not b64

    def test_bad_base64_is_422(self, monkeypatch):
        monkeypatch.setattr(specs_mod, "localized_edit",
                            lambda *a, **k: pytest.fail("must not run"))
        r = TestClient(app).post("/specs/localized-edit", json={
            "image_base64": "not base64!!!",
            "region_description": "the prongs",
            "change_instruction": "longer"})
        assert r.status_code == 422
        r = TestClient(app).post("/specs/localized-edit", json={
            "image_base64": base64.b64encode(PNG).decode(),
            "mask_base64": "not base64!!!",
            "region_description": "the prongs",
            "change_instruction": "longer"})
        assert r.status_code == 422

    def test_empty_region_is_422(self, monkeypatch):
        monkeypatch.setattr(specs_mod, "localized_edit",
                            lambda *a, **k: pytest.fail("must not run"))
        r = TestClient(app).post("/specs/localized-edit", json={
            "image_base64": base64.b64encode(PNG).decode(),
            "region_description": "",
            "change_instruction": "longer prongs"})
        assert r.status_code == 422                  # pydantic min_length

    def test_whitespace_region_is_422_asking_for_the_area(self):
        # no mock needed: localized_edit raises before any provider call
        r = TestClient(app).post("/specs/localized-edit", json={
            "image_base64": base64.b64encode(PNG).decode(),
            "region_description": "   ",
            "change_instruction": "longer prongs"})
        assert r.status_code == 422
        assert "select the area" in r.json()["detail"]

    def test_unknown_kind_is_422(self):
        r = TestClient(app).post("/specs/localized-edit", json={
            "image_base64": base64.b64encode(PNG).decode(),
            "region_description": "the prongs",
            "change_instruction": "longer", "kind": "sketch"})
        assert r.status_code == 422

    def test_missing_key_is_503(self, monkeypatch):
        def boom(image_bytes, **kwargs):
            raise RenderUnavailable("no XAI_KEY configured — set it")

        monkeypatch.setattr(specs_mod, "localized_edit", boom)
        r = TestClient(app).post("/specs/localized-edit", json={
            "image_base64": base64.b64encode(PNG).decode(),
            "region_description": "the prongs",
            "change_instruction": "longer"})
        assert r.status_code == 503


class TestInferCapabilityEndpoint:
    def test_routes_the_message(self):
        client = TestClient(app)
        r = client.post("/specs/infer-capability",
                        json={"text": "don't change the rest of the ring"})
        assert r.status_code == 200
        assert r.json() == {"capability": "LOCALIZED_EDIT"}
        r = client.post("/specs/infer-capability",
                        json={"text": "factory drawing please"})
        assert r.json() == {"capability": "MANUFACTURING_TECHNICAL_DRAWING"}
        r = client.post("/specs/infer-capability",
                        json={"text": "a sapphire cuff"})
        assert r.json() == {"capability": "JEWELRY_RENDER"}

    def test_empty_text_is_422(self):
        r = TestClient(app).post("/specs/infer-capability", json={"text": ""})
        assert r.status_code == 422

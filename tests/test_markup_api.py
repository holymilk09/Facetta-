"""Markup-driven surgical edits: the designer draws on the piece, the agent
reads it, echoes its understanding, and — only after confirmation — changes
exactly what was marked while the linked design's spec moves in lockstep.

Vision, edit, and planner calls are all mocked; mask_from_markup and the
chain/version bookkeeping run for real.
"""

import base64
import copy
import hashlib
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import facetta.api.assets as assets_mod
import facetta.specagent as agent
from facetta.db import (
    Base,
    DesignVersion,
    ImageAsset,
    ImageRun,
    ProjectRevisionRecord,
    StudioJobRecord,
    StudioMarkupCandidateRecord,
    get_db,
    utcnow,
)
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
    test_client = TestClient(app)
    # Keep the public fixture shape unchanged while allowing authority tests
    # to inspect the same in-memory ledger used by the HTTP request.
    test_client._facetta_session_factory = TestSession
    yield test_client
    app.dependency_overrides.clear()


def _design(client) -> str:
    r = client.post("/designs", json={"created_by": "usr_ana",
                                      "spec": HALO_SPEC})
    assert r.status_code == 201, r.text
    return r.json()["design_id"]


def _linked_asset(
    client,
    *,
    created_by: str = "usr_pending",
) -> tuple[str, str]:
    design_id = _design(client)
    r = client.post("/assets/render",
                    json={"piece_description": "a halo ring",
                          "design_id": design_id,
                          "created_by": created_by})
    assert r.status_code == 201, r.text
    return r.json()["asset_id"], design_id


def _running_refine_job(
    client,
    *,
    job_id: str,
    owner: str,
    asset_id: str,
) -> None:
    Session = client._facetta_session_factory
    now = utcnow()
    with Session() as db:
        db.add(StudioJobRecord(
            id=job_id,
            owner=owner,
            action_id="refine",
            lane="trusted_structural",
            status="running",
            progress=0.05,
            active_design_id=asset_id,
            source_revision_id=asset_id,
            requested_outputs=1,
            credits_per_output=20,
            completed_outputs=0,
            charged_outputs=0,
            created_at=now,
            updated_at=now,
        ))
        db.commit()


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
    def test_markup_read_forwards_normalized_designer_instruction(
        self,
        client,
        monkeypatch,
    ):
        captured: dict[str, object] = {}

        def reader(
            clean: bytes,
            marked: bytes,
            form_elements=(),
            *,
            designer_instruction: str,
        ) -> dict:
            captured.update(
                clean=clean,
                marked=marked,
                form_elements=form_elements,
                designer_instruction=designer_instruction,
            )
            reading = dict(READING)
            reading["annotations"] = [dict(
                READING["annotations"][0],
                change_instruction=designer_instruction,
            )]
            reading["understood_as"] = (
                "Understood as: apply the typed instruction only to the mark."
            )
            return reading

        monkeypatch.setattr(assets_mod, "read_markup", reader)
        asset_id, _design_id = _linked_asset(client)
        marked = _marked(_png())

        response = client.post(f"/assets/{asset_id}/markup/read", json={
            "marked_image_base64": base64.b64encode(marked).decode(),
            "instruction": "  Make the visible metal rose gold  ",
            "created_by": "usr_pending",
        })

        assert response.status_code == 200, response.text
        assert captured["designer_instruction"] == (
            "Make the visible metal rose gold"
        )
        assert response.json()["interpretation"]["requested_change"] == (
            "Make the visible metal rose gold"
        )

    def test_markup_read_keeps_location_ambiguity_fail_closed_with_instruction(
        self,
        client,
        monkeypatch,
    ):
        captured: dict[str, str] = {}

        def reader(
            _clean: bytes,
            _marked: bytes,
            _form_elements=(),
            *,
            designer_instruction: str,
        ) -> dict:
            captured["designer_instruction"] = designer_instruction
            return {
                "annotations": [],
                "understood_as": "",
                "needs_clarification": True,
                "clarification": "which shoulder does the arrow point to?",
            }

        monkeypatch.setattr(assets_mod, "read_markup", reader)
        asset_id, _design_id = _linked_asset(client)

        response = client.post(f"/assets/{asset_id}/markup/read", json={
            "marked_image_base64": base64.b64encode(_marked(_png())).decode(),
            "instruction": "Make the visible metal rose gold",
        })

        assert response.status_code == 422
        assert captured["designer_instruction"] == (
            "Make the visible metal rose gold"
        )
        assert response.json()["detail"] == (
            "which shoulder does the arrow point to?"
        )

    def test_markup_read_rejects_blank_designer_instruction(
        self,
        client,
        monkeypatch,
    ):
        monkeypatch.setattr(
            assets_mod,
            "read_markup",
            lambda *_args, **_kwargs: pytest.fail(
                "blank instruction must fail before vision"
            ),
        )
        asset_id, _design_id = _linked_asset(client)

        response = client.post(f"/assets/{asset_id}/markup/read", json={
            "marked_image_base64": base64.b64encode(_marked(_png())).decode(),
            "instruction": "   ",
        })

        assert response.status_code == 422
        assert "instruction must contain a change request" in response.text

    def test_markup_read_uses_openai_pair_when_xai_is_unconfigured(
        self,
        client,
        monkeypatch,
    ):
        values = {"XAI_KEY": None, "OPENAI_API_KEY": "openai-key"}
        calls: list[tuple[bytes, bytes, str]] = []
        monkeypatch.setattr(
            "facetta.image_agent.vision.env_value",
            lambda key, default=None: values.get(key, default),
        )
        monkeypatch.setattr(
            "facetta.image_agent.vision.vision_json_pair",
            lambda *_args: pytest.fail("XAI must not run without XAI_KEY"),
        )
        monkeypatch.setattr(
            "facetta.image_agent.vision.openai_vision_json_pair",
            lambda _system, clean, marked, ask: (
                calls.append((clean, marked, ask)) or dict(READING)
            ),
        )
        asset_id, _design_id = _linked_asset(client)
        with client._facetta_session_factory() as db:
            clean_asset = db.get(ImageAsset, asset_id)
            assert clean_asset is not None
            clean = bytes(clean_asset.image)
        marked = _marked(clean)

        response = client.post(f"/assets/{asset_id}/markup/read", json={
            "marked_image_base64": base64.b64encode(marked).decode(),
            "created_by": "usr_pending",
        })

        assert response.status_code == 200, response.text
        assert len(calls) == 1
        assert calls[0][0] == clean
        assert calls[0][1] == marked
        assert calls[0][2].startswith(
            "Read the designer's marks on the second image."
        )
        assert "A visible mark alone does not state change intent" in calls[0][2]
        assert response.json()["annotations"][0]["target_section"] == (
            "side_stones"
        )

    def test_production_preview_requires_job_before_edit_planning(
        self,
        client,
        monkeypatch,
    ):
        calls: list[bool] = []
        monkeypatch.setattr(
            "facetta.grokedit.grok_plan_scoped_edit",
            lambda *_args, **_kwargs: calls.append(True),
        )
        monkeypatch.setenv("FACETTA_ENV", "production")
        asset_id, _design_id = _linked_asset(client)

        response = client.post(f"/assets/{asset_id}/markup/apply", json={
            "expected_design_version": 1,
            "annotations": [{
                "region_description": "the background",
                "change_instruction": "make the background warmer",
            }],
            "created_by": "usr_ana",
            "preview_only": True,
            "update_spec": False,
        })

        assert response.status_code == 422, response.text
        assert response.json()["code"] == "studio_job_required"
        assert calls == []

    @pytest.mark.parametrize(
        ("job_id", "request_changes", "expected_code"),
        [
            ("job_missing_version", {}, "expected_design_version_required"),
        ],
    )
    def test_production_preview_rejects_noncanonical_request_before_planning(
        self,
        client,
        monkeypatch,
        job_id,
        request_changes,
        expected_code,
    ):
        planner_calls: list[bool] = []
        provider_calls: list[bool] = []
        monkeypatch.setattr(
            "facetta.grokedit.grok_plan_scoped_edit",
            lambda *_args, **_kwargs: planner_calls.append(True),
        )
        monkeypatch.setattr(
            assets_mod,
            "_trusted_image_agent",
            lambda: provider_calls.append(True),
        )
        monkeypatch.setenv("FACETTA_ENV", "production")
        asset_id, _design_id = _linked_asset(client, created_by="usr_ana")
        _running_refine_job(
            client,
            job_id=job_id,
            owner="usr_ana",
            asset_id=asset_id,
        )
        request = {
            "annotations": [{
                "region_description": "the background",
                "change_instruction": "make the background warmer",
            }],
            "created_by": "usr_ana",
            "preview_only": True,
            "update_spec": False,
            "studio_job_id": job_id,
            **request_changes,
        }

        response = client.post(f"/assets/{asset_id}/markup/apply", json=request)

        assert response.status_code == 422, response.text
        assert response.json()["code"] == expected_code
        assert planner_calls == []
        assert provider_calls == []
        Session = client._facetta_session_factory
        with Session() as db:
            job = db.get(StudioJobRecord, job_id)
            assert job is not None and job.status == "running"

    def test_production_preview_requires_linked_exact_design_before_planning(
        self,
        client,
        monkeypatch,
    ):
        planner_calls: list[bool] = []
        provider_calls: list[bool] = []
        monkeypatch.setattr(
            "facetta.grokedit.grok_plan_scoped_edit",
            lambda *_args, **_kwargs: planner_calls.append(True),
        )
        monkeypatch.setattr(
            assets_mod,
            "_trusted_image_agent",
            lambda: provider_calls.append(True),
        )
        monkeypatch.setenv("FACETTA_ENV", "production")
        rendered = client.post("/assets/render", json={
            "piece_description": "an unlinked halo ring",
            "created_by": "usr_ana",
        })
        assert rendered.status_code == 201, rendered.text
        asset_id = rendered.json()["asset_id"]
        _running_refine_job(
            client,
            job_id="job_unlinked_design",
            owner="usr_ana",
            asset_id=asset_id,
        )

        response = client.post(f"/assets/{asset_id}/markup/apply", json={
            "expected_design_version": 1,
            "annotations": [{
                "region_description": "the halo",
                "change_instruction": "raise the melee to 1.3 mm",
                "target_section": "side_stones",
                "index": 0,
            }],
            "created_by": "usr_ana",
            "preview_only": True,
            "studio_job_id": "job_unlinked_design",
        })

        assert response.status_code == 409, response.text
        assert response.json()["code"] == "design_not_linked"
        assert planner_calls == []
        assert provider_calls == []
        Session = client._facetta_session_factory
        with Session() as db:
            job = db.get(StudioJobRecord, "job_unlinked_design")
            assert job is not None and job.status == "running"

    def test_production_preview_rejects_stale_active_visual_before_provider(
        self,
        client,
        monkeypatch,
    ):
        self._mock_apply(monkeypatch)
        monkeypatch.setenv("FACETTA_ENV", "test")
        asset_id, _design_id = _linked_asset(client, created_by="usr_ana")
        _running_refine_job(
            client,
            job_id="job_stale_visual_source",
            owner="usr_ana",
            asset_id=asset_id,
        )

        advanced = client.post(f"/assets/{asset_id}/markup/apply", json={
            "annotations": [{
                "region_description": "the background",
                "change_instruction": "make the background warmer",
            }],
            "created_by": "usr_ana",
            "update_spec": False,
        })
        assert advanced.status_code == 201, advanced.text
        advanced_step = advanced.json()["steps"][0]
        assert advanced_step["asset_id"] != asset_id
        assert advanced_step["design_version"] == 1

        planner_calls: list[bool] = []
        provider_calls: list[bool] = []
        monkeypatch.setattr(
            "facetta.grokedit.grok_plan_scoped_edit",
            lambda *_args, **_kwargs: planner_calls.append(True),
        )
        monkeypatch.setattr(
            assets_mod,
            "_trusted_image_agent",
            lambda: provider_calls.append(True),
        )
        monkeypatch.setenv("FACETTA_ENV", "production")

        response = client.post(f"/assets/{asset_id}/markup/apply", json={
            "expected_design_version": 1,
            "annotations": [{
                "region_description": "the background",
                "change_instruction": "soften the shadow",
            }],
            "created_by": "usr_ana",
            "preview_only": True,
            "update_spec": False,
            "studio_job_id": "job_stale_visual_source",
        })

        assert response.status_code == 409, response.text
        body = response.json()
        assert body["code"] == "stale_active_revision"
        assert body["expected_active_asset_id"] == asset_id
        assert body["current_active_asset_id"] == advanced_step["asset_id"]
        assert planner_calls == []
        assert provider_calls == []
        Session = client._facetta_session_factory
        with Session() as db:
            job = db.get(StudioJobRecord, "job_stale_visual_source")
            assert job is not None and job.status == "running"

    def test_studio_preview_run_candidate_and_job_commit_atomically(
        self,
        client,
        monkeypatch,
    ):
        from facetta.image_agent import (
            CheckSeverity,
            ImageQualityReport,
            JewelryImageAgent,
            ProviderImage,
            QualityCheck,
            QualityVerdict,
        )
        from facetta.studio_markup_candidates import (
            store_studio_markup_candidate as real_store_candidate,
        )

        provider_calls: list[bool] = []

        class Provider:
            def execute(self, plan, route, prompt, *, source_image, mask_bytes):
                provider_calls.append(True)
                return ProviderImage(image_bytes=_png((76, 68, 61)))

        class PassingEvaluator:
            def evaluate(self, plan, candidate, *, source_image, mask_bytes):
                return ImageQualityReport(
                    verdict=QualityVerdict.PASS,
                    checks=(QualityCheck(
                        code="geometry_preserved",
                        passed=True,
                        severity=CheckSeverity.HARD,
                        message="jewelry geometry stayed fixed",
                    ),),
                    score=98,
                )

        monkeypatch.setattr(
            assets_mod,
            "_trusted_image_agent",
            lambda: JewelryImageAgent(Provider(), PassingEvaluator()),
        )
        self._mock_apply(monkeypatch)
        monkeypatch.setenv("FACETTA_ENV", "production")
        asset_id, _design_id = _linked_asset(client, created_by="usr_ana")
        Session = client._facetta_session_factory
        _running_refine_job(
            client,
            job_id="job_markup_atomic",
            owner="usr_ana",
            asset_id=asset_id,
        )

        request = {
            "expected_design_version": 1,
            "update_spec": True,
            "preview_only": True,
            "created_by": "usr_ana",
            "studio_job_id": "job_markup_atomic",
            "annotations": [{
                "region_description": "the halo, upper arc",
                "change_instruction": "raise the melee to 1.3 mm",
                "target_section": "side_stones",
                "index": 0,
            }],
        }

        def fail_candidate_store(*_args, **_kwargs):
            raise RuntimeError("simulated candidate persistence failure")

        monkeypatch.setattr(
            "facetta.studio_markup_candidates.store_studio_markup_candidate",
            fail_candidate_store,
        )
        with pytest.raises(RuntimeError, match="candidate persistence"):
            client.post(f"/assets/{asset_id}/markup/apply", json=request)

        with Session() as db:
            job = db.get(StudioJobRecord, "job_markup_atomic")
            assert job is not None and job.status == "running"
            assert db.scalar(select(func.count()).select_from(ImageRun)) == 0
            assert db.scalar(
                select(func.count()).select_from(StudioMarkupCandidateRecord)
            ) == 0

        monkeypatch.setattr(
            "facetta.studio_markup_candidates.store_studio_markup_candidate",
            real_store_candidate,
        )
        created = client.post(f"/assets/{asset_id}/markup/apply", json=request)
        assert created.status_code == 201, created.text
        warning = created.json()["warning_candidate"]
        assert warning["preview_url"] == (
            f"/studio/markup-candidates/{warning['run_id']}/"
            f"{warning['candidate_id']}/image"
        )
        with Session() as db:
            job = db.get(StudioJobRecord, "job_markup_atomic")
            assert job is not None and job.status == "reviewing"
            assert db.scalar(select(func.count()).select_from(ImageRun)) == 1
            assert db.scalar(
                select(func.count()).select_from(StudioMarkupCandidateRecord)
            ) == 1

        replay = client.post(f"/assets/{asset_id}/markup/apply", json=request)
        assert replay.status_code == 409, replay.text
        assert replay.json()["code"] == "studio_job_terminal"
        assert provider_calls == [True, True]

    def test_openai_only_one_mark_stone_color_preview_stays_temporary(
        self,
        client,
        monkeypatch,
    ):
        """The live local configuration has OpenAI but no xAI chat key."""
        import facetta.grokedit as grokedit
        from facetta.image_agent import (
            CheckSeverity,
            ImageQualityReport,
            JewelryImageAgent,
            ProviderImage,
            QualityCheck,
            QualityVerdict,
        )

        class Provider:
            def execute(self, plan, route, prompt, *, source_image, mask_bytes):
                return ProviderImage(image_bytes=_png((246, 241, 225)))

        class PassingEvaluator:
            def evaluate(self, plan, candidate, *, source_image, mask_bytes):
                return ImageQualityReport(
                    verdict=QualityVerdict.PASS,
                    checks=(QualityCheck(
                        code="outside_mask_preserved",
                        passed=True,
                        severity=CheckSeverity.HARD,
                        message="unmarked jewelry stayed fixed",
                    ),),
                    score=98,
                )

        openai_calls: list[str] = []

        def openai_proposal(_key, _system, user):
            openai_calls.append(user)
            edited = copy.deepcopy(HALO_SPEC)
            edited["side_stones"][0]["color"] = {
                "trade": "Fancy Yellow",
                "gia": "yellow diamond appearance, fancy yellow direction",
            }
            return {
                "spec": edited,
                "changed_fields": [
                    "side_stones[0].color: F -> Fancy Yellow",
                ],
                "isolate_ref": None,
                "message": "Made the marked side stones fancy yellow.",
            }

        monkeypatch.delenv("XAI_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "openai-test-key")
        monkeypatch.setattr(
            grokedit,
            "_xai_chat_json",
            lambda *_args: pytest.fail("xAI must not run in OpenAI-only mode"),
        )
        monkeypatch.setattr(grokedit, "_openai_chat_json", openai_proposal)
        monkeypatch.setattr(
            assets_mod,
            "_trusted_image_agent",
            lambda: JewelryImageAgent(Provider(), PassingEvaluator()),
        )
        monkeypatch.setenv("FACETTA_ENV", "production")
        asset_id, _design_id = _linked_asset(client, created_by="usr_ana")
        _running_refine_job(
            client,
            job_id="job_openai_stone_color",
            owner="usr_ana",
            asset_id=asset_id,
        )

        response = client.post(f"/assets/{asset_id}/markup/apply", json={
            "expected_design_version": 1,
            "update_spec": True,
            "preview_only": True,
            "created_by": "usr_ana",
            "studio_job_id": "job_openai_stone_color",
            "annotations": [{
                "region_description": "the marked side stones",
                "change_instruction": "make the side diamonds fancy yellow",
                "target_section": "side_stones",
                "index": 0,
            }],
        })

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["warning_candidate"]["candidate_id"]
        assert body["final_asset_id"] is None
        assert body["revision"] is None
        assert openai_calls and "fancy yellow" in openai_calls[0]
        Session = client._facetta_session_factory
        with Session() as db:
            job = db.get(StudioJobRecord, "job_openai_stone_color")
            assert job is not None and job.status == "reviewing"
            assert (job.completed_outputs, job.charged_outputs) == (0, 0)
            assert db.scalar(select(func.count()).select_from(ImageAsset)) == 1
            assert db.scalar(select(func.count()).select_from(DesignVersion)) == 1
            assert db.scalar(
                select(func.count()).select_from(StudioMarkupCandidateRecord)
            ) == 1

    def test_scoped_edit_unavailable_response_is_structured_and_redacted(
        self,
        client,
        monkeypatch,
    ):
        import facetta.grokedit as grokedit

        def unavailable(*_args, **_kwargs):
            raise grokedit.GrokEditUnavailable(
                "no OPENAI_API_KEY configured",
                code="edit_provider_not_configured",
                retryable=False,
                status_code=503,
            )

        monkeypatch.setattr(grokedit, "grok_plan_scoped_edit", unavailable)
        monkeypatch.setenv("FACETTA_ENV", "test")
        asset_id, _design_id = _linked_asset(client)

        response = client.post(f"/assets/{asset_id}/markup/apply", json={
            "annotations": [{
                "region_description": "the marked side stones",
                "change_instruction": "make the side diamonds fancy yellow",
                "target_section": "side_stones",
                "index": 0,
            }],
        })

        assert response.status_code == 503, response.text
        body = response.json()
        assert body["code"] == "edit_provider_not_configured"
        assert body["operation_code"] == "spec_interpretation_unavailable"
        assert body["category"] == "provider"
        assert body["retryable"] is False
        assert "KEY" not in body["detail"]
        assert "OpenAI" not in body["detail"]

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
        assert leaf["revision"] is None
        assert leaf["derived_from_revision"] == 1

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
        assert step["design_version"] == 2
        assert "1.3" in step["changes_summary"]
        assert step["spec_change"]
        assert body["consistency"]["checked"] is True
        # the design really has a v2 with the new melee size
        v2 = client.get(f"/designs/{design_id}/versions/2").json()
        assert v2["side_stones"][0]["dimensions_mm"]["length"] == 1.3
        # and v1 is untouched
        v1 = client.get(f"/designs/{design_id}/versions/1").json()
        assert v1["side_stones"][0]["dimensions_mm"]["length"] == 4.1
        image = client.get(f"/assets/{step['asset_id']}").json()
        assert image["design_version"] == 2

    def test_visual_only_edit_inherits_spec_without_new_version(
            self, client, monkeypatch):
        self._mock_apply(monkeypatch)
        aid, design_id = _linked_asset(client)
        response = client.post(f"/assets/{aid}/markup/apply", json={
            "annotations": [{
                "region_description": "the background",
                "change_instruction": "make the background warmer",
            }],
        })
        assert response.status_code == 201, response.text
        step = response.json()["steps"][0]
        assert step["spec_synced"] is False
        assert step["design_version"] == 1
        assert len(client.get(f"/designs/{design_id}").json()["versions"]) == 1

    def test_trusted_warning_promotes_only_after_explicit_review(
            self, client, monkeypatch):
        from facetta.image_agent import (
            CheckSeverity, ImageQualityReport, JewelryImageAgent,
            ProviderImage, QualityCheck, QualityVerdict,
        )

        class Provider:
            def execute(self, plan, route, prompt, *, source_image,
                        mask_bytes):
                return ProviderImage(image_bytes=_png((80, 70, 60)))

        class WarningEvaluator:
            def evaluate(self, plan, candidate, *, source_image, mask_bytes):
                return ImageQualityReport(
                    verdict=QualityVerdict.WARN,
                    checks=(QualityCheck(
                        code="presentation_drift", passed=False,
                        severity=CheckSeverity.WARNING,
                        message="background tone needs designer review"),),
                    score=88,
                )

        monkeypatch.setattr(
            assets_mod, "_trusted_image_agent",
            lambda: JewelryImageAgent(Provider(), WarningEvaluator()))
        self._mock_apply(monkeypatch)
        aid, design_id = _linked_asset(client)
        response = client.post(f"/assets/{aid}/markup/apply", json={
            "expected_design_version": 1,
            "annotations": [{
                "region_description": "the halo, upper arc",
                "change_instruction": "raise the melee to 1.3 mm",
                "target_section": "side_stones",
                "index": 0,
            }],
        })
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["revision"] is None
        candidate = body["warning_candidate"]
        assert candidate["qa"]["verdict"] == "warn"
        assert candidate["candidate_id"].startswith("cand_")
        preview = client.get(candidate["preview_url"])
        assert preview.status_code == 200
        assert preview.headers["content-type"] == "image/png"
        assert len(client.get(
            f"/assets/{aid}/history").json()["history"]) == 1
        assert len(client.get(f"/designs/{design_id}").json()["versions"]) == 1
        run = client.get(f"/image-runs/{body['image_run_id']}")
        assert run.status_code == 200, run.text
        assert run.json()["status"] == "review_required"
        assert run.json()["accepted_asset_id"] is None

        stale_accept = client.post(
            f"/image-runs/{body['image_run_id']}/candidates/"
            f"{candidate['candidate_id']}/accept",
            json={"expected_design_version": 2,
                  "created_by": "usr_designer"},
        )
        assert stale_accept.status_code == 409
        assert stale_accept.json()["code"] == "stale_design_version"
        assert len(client.get(
            f"/assets/{aid}/history").json()["history"]) == 1

        accepted = client.post(
            f"/image-runs/{body['image_run_id']}/candidates/"
            f"{candidate['candidate_id']}/accept",
            json={"expected_design_version": 1,
                  "created_by": "usr_designer"},
        )
        assert accepted.status_code == 201, accepted.text
        project = accepted.json()
        assert project["primary_revision_count"] == 2
        assert project["active_design_version"] == 2
        assert len(client.get(
            f"/assets/{aid}/history").json()["history"]) == 2
        assert len(client.get(f"/designs/{design_id}").json()["versions"]) == 2

        reviewed_run = client.get(
            f"/image-runs/{body['image_run_id']}").json()
        assert reviewed_run["status"] == "accepted"
        assert reviewed_run["stored_status"] == "review_required"
        assert reviewed_run["review_decision"] == "accepted"
        assert reviewed_run["accepted_asset_id"] == project["active_asset_id"]

        checklist = client.post(
            f"/assets/{project['active_asset_id']}/checklist",
            json={"created_by": "usr_designer", "mode": "auto_pin"},
        ).json()
        for item in checklist["items"]:
            approved = client.post(
                f"/assets/{project['active_asset_id']}/checklist/respond",
                json={
                    "item_key": item["key"],
                    "approved": True,
                    "created_by": "usr_designer",
                },
            )
            assert approved.status_code == 201
        manifest = client.get(
            f"/projects/{project['root_id']}/factory-pack").json()
        assert manifest["qa_summary"]["status"] == (
            "accepted_after_designer_review")
        assert manifest["qa_summary"]["verdict"] == "warn"

        replay = client.post(
            f"/image-runs/{body['image_run_id']}/candidates/"
            f"{candidate['candidate_id']}/accept",
            json={"expected_design_version": 1,
                  "created_by": "usr_designer"},
        )
        assert replay.status_code == 201
        assert replay.json()["active_asset_id"] == project["active_asset_id"]

    def test_trusted_pass_promotes_asset_and_logs_the_accepted_run(
            self, client, monkeypatch):
        from facetta.image_agent import (
            CheckSeverity, ImageQualityReport, JewelryImageAgent,
            ProviderImage, QualityCheck, QualityVerdict,
        )

        class Provider:
            def execute(self, plan, route, prompt, *, source_image,
                        mask_bytes):
                return ProviderImage(image_bytes=_png((80, 70, 60)))

        class PassingEvaluator:
            def evaluate(self, plan, candidate, *, source_image, mask_bytes):
                return ImageQualityReport(
                    verdict=QualityVerdict.PASS,
                    checks=(QualityCheck(
                        code="geometry_preserved", passed=True,
                        severity=CheckSeverity.HARD,
                        message="jewelry geometry stayed fixed"),),
                    score=97,
                )

        monkeypatch.setattr(
            assets_mod, "_trusted_image_agent",
            lambda: JewelryImageAgent(Provider(), PassingEvaluator()))
        aid, design_id = _linked_asset(client)
        response = client.post(f"/assets/{aid}/markup/apply", json={
            "expected_design_version": 1,
            "update_spec": False,
            "annotations": [{
                "region_description": "the background",
                "change_instruction": "make the background warmer",
            }],
        })
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["revision"]["asset"]["design_version"] == 1
        assert body["qa"]["verdict"] == "pass"
        assert len(client.get(f"/designs/{design_id}").json()["versions"]) == 1
        run = client.get(f"/image-runs/{body['image_run_id']}").json()
        assert run["status"] == "accepted"
        assert run["accepted_asset_id"] == body["final_asset_id"]

    def test_studio_pass_remains_temporary_until_apply_and_discard_is_terminal(
            self, client, monkeypatch):
        from facetta.image_agent import (
            CheckSeverity, ImageQualityReport, JewelryImageAgent,
            ProviderImage, QualityCheck, QualityVerdict,
        )

        class Provider:
            def execute(self, plan, route, prompt, *, source_image,
                        mask_bytes):
                return ProviderImage(image_bytes=_png((76, 68, 61)))

        class PassingEvaluator:
            def evaluate(self, plan, candidate, *, source_image, mask_bytes):
                return ImageQualityReport(
                    verdict=QualityVerdict.PASS,
                    checks=(QualityCheck(
                        code="geometry_preserved", passed=True,
                        severity=CheckSeverity.HARD,
                        message="jewelry geometry stayed fixed"),),
                    score=98,
                )

        monkeypatch.setattr(
            assets_mod, "_trusted_image_agent",
            lambda: JewelryImageAgent(Provider(), PassingEvaluator()))
        aid, design_id = _linked_asset(client)
        before_history = client.get(f"/assets/{aid}/history").json()["history"]

        response = client.post(f"/assets/{aid}/markup/apply", json={
            "expected_design_version": 1,
            "update_spec": False,
            "preview_only": True,
            "created_by": "usr_designer",
            "annotations": [{
                "region_description": "the full presentation background",
                "change_instruction": "make the background warmer",
            }],
        })

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["revision"] is None
        assert body["final_asset_id"] is None
        assert body["qa"]["verdict"] == "pass"
        candidate = body["warning_candidate"]
        assert candidate["candidate_id"]
        assert client.get(f"/assets/{aid}/history").json()["history"] == before_history
        assert len(client.get(f"/designs/{design_id}").json()["versions"]) == 1
        run = client.get(f"/image-runs/{body['image_run_id']}").json()
        assert run["status"] == "review_required"
        assert run["accepted_asset_id"] is None

        discarded = client.post(
            f"/image-runs/{candidate['run_id']}/candidates/"
            f"{candidate['candidate_id']}/discard",
            json={"created_by": "usr_designer"},
        )
        assert discarded.status_code == 200, discarded.text
        assert discarded.json()["status"] == "discarded"
        replay = client.post(
            f"/image-runs/{candidate['run_id']}/candidates/"
            f"{candidate['candidate_id']}/accept",
            json={"expected_design_version": 1,
                  "created_by": "usr_designer"},
        )
        assert replay.status_code == 410
        assert client.get(f"/assets/{aid}/history").json()["history"] == before_history

    def test_stale_expected_version_returns_409_before_image_work(
            self, client, monkeypatch):
        aid, design_id = _linked_asset(client)
        advanced = client.post(f"/designs/{design_id}/versions", json={
            "created_by": "usr_other", "spec": HALO_SPEC})
        assert advanced.status_code == 201, advanced.text
        monkeypatch.setattr(
            assets_mod, "localized_edit",
            lambda *args, **kwargs: pytest.fail("stale request must not render"))
        response = client.post(f"/assets/{aid}/markup/apply", json={
            "expected_design_version": 1,
            "annotations": [{
                "region_description": "the band",
                "change_instruction": "make it wider",
                "target_section": "band",
            }],
        })
        assert response.status_code == 409
        assert response.json()["code"] == "stale_design_version"
        assert response.json()["current_design_version"] == 2

    def test_image_and_spec_write_roll_back_together_on_db_failure(
            self, client, monkeypatch):
        import facetta.api.designs as designs_mod

        self._mock_apply(monkeypatch)
        aid, design_id = _linked_asset(client)

        def fail_version(*args, **kwargs):
            raise RuntimeError("simulated version insert failure")

        monkeypatch.setattr(designs_mod, "_store_version", fail_version)
        with pytest.raises(RuntimeError, match="simulated version"):
            client.post(f"/assets/{aid}/markup/apply", json={
                "annotations": [{
                    "region_description": "the halo",
                    "change_instruction": "melee 1.3",
                    "target_section": "side_stones", "index": 0,
                }],
            })
        history = client.get(f"/assets/{aid}/history").json()["history"]
        assert [item["asset_id"] for item in history] == [aid]
        assert len(client.get(f"/designs/{design_id}").json()["versions"]) == 1

    def test_sequential_annotations_chain_parent_to_child(self, client,
                                                          monkeypatch):
        """The multi-step form remains only for pre-trusted callers."""
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

    def test_trusted_multi_region_preview_is_one_union_masked_atomic_revision(
        self,
        client,
        monkeypatch,
    ):
        from facetta.image_agent import (
            CheckSeverity,
            ImageQualityReport,
            JewelryImageAgent,
            ProviderImage,
            QualityCheck,
            QualityVerdict,
        )

        monkeypatch.setenv("FACETTA_ENV", "production")
        aid, design_id = _linked_asset(client, created_by="usr_ana")
        _running_refine_job(
            client,
            job_id="job_multi_region",
            owner="usr_ana",
            asset_id=aid,
        )
        Session = client._facetta_session_factory
        with Session() as db:
            source_asset = db.get(ImageAsset, aid)
            assert source_asset is not None
            source = bytes(source_asset.image)
            before_assets = db.scalar(select(func.count()).select_from(ImageAsset))
            before_versions = db.scalar(
                select(func.count()).select_from(DesignVersion)
            )
            before_revisions = db.scalar(
                select(func.count()).select_from(ProjectRevisionRecord)
            )

        def mask_box(box):
            mask = Image.new("L", (200, 300), 0)
            ImageDraw.Draw(mask).rectangle(box, fill=255)
            output = io.BytesIO()
            mask.save(output, format="PNG")
            return output.getvalue()

        first_mask = mask_box((10, 10, 55, 55))
        second_mask = mask_box((145, 235, 190, 285))
        calls: list[dict[str, object]] = []

        class Provider:
            def execute(self, plan, route, prompt, *, source_image, mask_bytes):
                union = Image.open(io.BytesIO(mask_bytes)).convert("L")
                candidate = Image.open(io.BytesIO(source_image)).convert("RGB")
                overlay = Image.new("RGB", candidate.size, (76, 68, 61))
                candidate.paste(overlay, mask=union)
                output = io.BytesIO()
                candidate.save(output, format="PNG")
                calls.append({
                    "plan": plan,
                    "mask": mask_bytes,
                    "source": source_image,
                })
                return ProviderImage(image_bytes=output.getvalue())

        class PassingEvaluator:
            def evaluate(self, plan, candidate, *, source_image, mask_bytes):
                return ImageQualityReport(
                    verdict=QualityVerdict.PASS,
                    checks=(
                        QualityCheck(
                            code="inside_mask_effect",
                            passed=True,
                            severity=CheckSeverity.HARD,
                            message="both marked regions changed",
                        ),
                        QualityCheck(
                            code="outside_mask_drift",
                            passed=True,
                            severity=CheckSeverity.HARD,
                            message="outside union stayed fixed",
                            evidence={"drift": 0.0, "threshold": 0.18},
                        ),
                    ),
                    score=99,
                )

        monkeypatch.setattr(
            assets_mod,
            "_trusted_image_agent",
            lambda: JewelryImageAgent(Provider(), PassingEvaluator()),
        )
        annotations = [
            {
                "region_description": "upper-left halo segment",
                "change_instruction": "warm this metal segment",
                "mask_base64": base64.b64encode(first_mask).decode(),
            },
            {
                "region_description": "lower-right shank segment",
                "change_instruction": "soften this reflection",
                "mask_base64": base64.b64encode(second_mask).decode(),
            },
        ]
        created = client.post(f"/assets/{aid}/markup/apply", json={
            "expected_design_version": 1,
            "update_spec": False,
            "preview_only": True,
            "created_by": "usr_ana",
            "studio_job_id": "job_multi_region",
            "annotations": annotations,
        })

        assert created.status_code == 201, created.text
        body = created.json()
        assert body["final_asset_id"] is None and body["revision"] is None
        assert len(calls) == 1
        assert [
            item["change_instruction"]
            for item in body["warning_candidate"]["annotations"]
        ] == ["warm this metal segment", "soften this reflection"]
        union_bytes = calls[0]["mask"]
        assert isinstance(union_bytes, bytes)
        union = Image.open(io.BytesIO(union_bytes)).convert("L")
        assert union.getpixel((20, 20)) == 255
        assert union.getpixel((170, 260)) == 255
        assert union.getpixel((100, 150)) == 0
        assert calls[0]["plan"].mask_hash == hashlib.sha256(union_bytes).hexdigest()

        candidate_id = body["warning_candidate"]["candidate_id"]
        preview = client.get(body["warning_candidate"]["preview_url"])
        assert preview.status_code == 200
        source_image = Image.open(io.BytesIO(source)).convert("RGB")
        preview_image = Image.open(io.BytesIO(preview.content)).convert("RGB")
        assert preview_image.getpixel((100, 150)) == source_image.getpixel((100, 150))
        assert preview_image.getpixel((20, 20)) != source_image.getpixel((20, 20))
        assert preview_image.getpixel((170, 260)) != source_image.getpixel((170, 260))

        with Session() as db:
            durable = db.get(StudioMarkupCandidateRecord, candidate_id)
            job = db.get(StudioJobRecord, "job_multi_region")
            assert durable is not None and durable.status == "reviewing"
            assert [
                item["region_description"]
                for item in durable.payload["annotations"]
            ] == ["upper-left halo segment", "lower-right shank segment"]
            assert durable.payload["target_mask_sha256"] == hashlib.sha256(
                union_bytes
            ).hexdigest()
            assert job is not None and job.status == "reviewing"
            assert (job.completed_outputs, job.charged_outputs) == (0, 0)
            assert db.scalar(select(func.count()).select_from(ImageAsset)) == (
                before_assets
            )
            assert db.scalar(select(func.count()).select_from(DesignVersion)) == (
                before_versions
            )
            assert db.scalar(
                select(func.count()).select_from(ProjectRevisionRecord)
            ) == before_revisions

        normalized = client.get(
            f"/studio/preview-candidates/{candidate_id}?owner=usr_ana"
        )
        assert normalized.status_code == 200, normalized.text
        assert [
            {
                "region_description": item["region_description"],
                "change_instruction": item["change_instruction"],
            }
            for item in normalized.json()["annotations"]
        ] == [
            {
                "region_description": item["region_description"],
                "change_instruction": item["change_instruction"],
            }
            for item in annotations
        ]

        wrong_lineage = client.post(
            f"/studio/preview-candidates/{candidate_id}/decision",
            json={
                "created_by": "usr_ana",
                "decision": "apply",
                "expected_active_asset_id": "ast_wrong_revision",
                "expected_design_version": 1,
            },
        )
        assert wrong_lineage.status_code == 409
        with Session() as db:
            job = db.get(StudioJobRecord, "job_multi_region")
            assert job is not None and job.charged_outputs == 0
            assert db.scalar(select(func.count()).select_from(ImageAsset)) == (
                before_assets
            )

        applied = client.post(
            f"/studio/preview-candidates/{candidate_id}/decision",
            json={
                "created_by": "usr_ana",
                "decision": "apply",
                "expected_active_asset_id": aid,
                "expected_design_version": 1,
            },
        )
        assert applied.status_code == 200, applied.text
        child_id = applied.json()["terminal_asset_id"]
        with Session() as db:
            child = db.get(ImageAsset, child_id)
            job = db.get(StudioJobRecord, "job_multi_region")
            revision = db.scalar(select(ProjectRevisionRecord).where(
                ProjectRevisionRecord.asset_id == child_id
            ))
            assert child is not None and child.parent_asset_id == aid
            assert job is not None and job.status == "succeeded"
            assert (job.completed_outputs, job.charged_outputs) == (1, 1)
            assert db.scalar(select(func.count()).select_from(ImageAsset)) == (
                before_assets + 1
            )
            assert db.scalar(select(func.count()).select_from(DesignVersion)) == (
                before_versions
            )
            assert db.scalar(
                select(func.count()).select_from(ProjectRevisionRecord)
            ) == before_revisions + 1
            assert revision is not None
            assert len(revision.raw_intent["annotations"]) == 2
        assert len(client.get(
            f"/assets/{aid}/history"
        ).json()["history"]) == 2
        assert len(client.get(f"/designs/{design_id}").json()["versions"]) == 1

    def test_trusted_multi_region_validation_failure_is_atomic_and_zero_charge(
        self,
        client,
        monkeypatch,
    ):
        monkeypatch.setenv("FACETTA_ENV", "production")
        aid, design_id = _linked_asset(client, created_by="usr_ana")
        _running_refine_job(
            client,
            job_id="job_multi_invalid",
            owner="usr_ana",
            asset_id=aid,
        )
        monkeypatch.setattr(
            assets_mod,
            "_trusted_image_agent",
            lambda: pytest.fail("invalid batch must fail before provider work"),
        )
        mask = Image.new("L", (200, 300), 0)
        ImageDraw.Draw(mask).rectangle((10, 10, 40, 40), fill=255)
        output = io.BytesIO()
        mask.save(output, format="PNG")

        response = client.post(f"/assets/{aid}/markup/apply", json={
            "expected_design_version": 1,
            "update_spec": False,
            "preview_only": True,
            "created_by": "usr_ana",
            "studio_job_id": "job_multi_invalid",
            "annotations": [
                {
                    "region_description": "halo",
                    "change_instruction": "warm it",
                    "mask_base64": base64.b64encode(output.getvalue()).decode(),
                },
                {
                    "region_description": "shank",
                    "change_instruction": "soften it",
                },
            ],
        })

        assert response.status_code == 422, response.text
        assert response.json()["code"] == "multi_region_mask_required"
        Session = client._facetta_session_factory
        with Session() as db:
            job = db.get(StudioJobRecord, "job_multi_invalid")
            assert job is not None and job.status == "running"
            assert (job.completed_outputs, job.charged_outputs) == (0, 0)
            assert db.scalar(
                select(func.count()).select_from(StudioMarkupCandidateRecord)
            ) == 0
            assert db.scalar(select(func.count()).select_from(ImageRun)) == 0
            assert db.scalar(select(func.count()).select_from(ImageAsset)) == 1
            assert db.scalar(select(func.count()).select_from(DesignVersion)) == 1
            assert db.scalar(
                select(func.count()).select_from(ProjectRevisionRecord)
            ) == 0
        assert len(client.get(f"/designs/{design_id}").json()["versions"]) == 1

    def test_trusted_multi_region_qa_failure_is_evidence_only_and_zero_charge(
        self,
        client,
        monkeypatch,
    ):
        from facetta.image_agent import (
            CheckSeverity,
            ImageQualityFailure,
            ImageQualityReport,
            QualityCheck,
            QualityVerdict,
        )

        monkeypatch.setenv("FACETTA_ENV", "production")
        aid, _design_id = _linked_asset(client, created_by="usr_ana")
        _running_refine_job(
            client,
            job_id="job_multi_qa_failed",
            owner="usr_ana",
            asset_id=aid,
        )
        mask = Image.new("L", (200, 300), 0)
        ImageDraw.Draw(mask).rectangle((10, 10, 190, 285), fill=255)
        output = io.BytesIO()
        mask.save(output, format="PNG")
        encoded_mask = base64.b64encode(output.getvalue()).decode()
        failed_report = ImageQualityReport(
            verdict=QualityVerdict.FAIL,
            checks=(QualityCheck(
                code="outside_mask_drift",
                passed=False,
                severity=CheckSeverity.HARD,
                message="candidate changed protected pixels",
                evidence={"drift": 0.42, "threshold": 0.18},
            ),),
            score=10,
        )

        class FailingAgent:
            calls = 0

            def run(self, plan, *, source_image, mask_bytes):
                del source_image, mask_bytes
                self.calls += 1
                raise ImageQualityFailure(
                    "candidate failed union-mask QA",
                    report=failed_report,
                    plan=plan,
                )

        agent = FailingAgent()
        monkeypatch.setattr(assets_mod, "_trusted_image_agent", lambda: agent)
        response = client.post(f"/assets/{aid}/markup/apply", json={
            "expected_design_version": 1,
            "update_spec": False,
            "preview_only": True,
            "created_by": "usr_ana",
            "studio_job_id": "job_multi_qa_failed",
            "annotations": [
                {
                    "region_description": "halo",
                    "change_instruction": "warm it",
                    "mask_base64": encoded_mask,
                },
                {
                    "region_description": "shank",
                    "change_instruction": "soften it",
                    "mask_base64": encoded_mask,
                },
            ],
        })

        assert response.status_code == 422, response.text
        assert response.json()["code"] == "image_quality_failed"
        assert agent.calls == 1
        Session = client._facetta_session_factory
        with Session() as db:
            job = db.get(StudioJobRecord, "job_multi_qa_failed")
            runs = list(db.scalars(select(ImageRun)))
            assert job is not None
            assert (job.completed_outputs, job.charged_outputs) == (0, 0)
            assert len(runs) == 1 and runs[0].status == "failed"
            assert runs[0].accepted_asset_id is None
            assert db.scalar(
                select(func.count()).select_from(StudioMarkupCandidateRecord)
            ) == 0
            assert db.scalar(select(func.count()).select_from(ImageAsset)) == 1
            assert db.scalar(select(func.count()).select_from(DesignVersion)) == 1
            assert db.scalar(
                select(func.count()).select_from(ProjectRevisionRecord)
            ) == 0

    def test_development_unlinked_chain_uses_compatibility_image_only(
        self,
        client,
        monkeypatch,
    ):
        monkeypatch.setenv("FACETTA_ENV", "test")
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
        # Exact provenance: an override from the original visual letters the
        # original spec, never a newer spec that this raster does not depict.
        assert body["spec_source"] == f"design:{design_id} v1"

        edited_id = client.get(f"/assets/{aid}/history").json()["history"][-1][
            "asset_id"]
        edited = client.post(
            f"/assets/{edited_id}/technical-drawing",
            json={"use_this_asset": True, "facetta_template": True},
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["spec_source"] == f"design:{design_id} v2"
        assert "1.3" in edited.json()["framed_svg"]  # the new melee size
        assert "ESTIMATED" not in body["framed_svg"]

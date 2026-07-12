"""Trusted project persistence, provenance, and revision grouping."""

from __future__ import annotations

import base64
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from conftest import audited_import_spec

from facetta.db import (
    ApprovalChecklist,
    ApprovalResponse,
    Base,
    Design,
    DesignVersion,
    ImageAsset,
    ImageAttempt,
    ImageRun,
    ImageRunReview,
    Project,
    _apply_additive_migrations,
    get_db,
    utcnow,
)
from facetta.main import app
from facetta.image_agent import (
    CheckSeverity,
    ImageOperation,
    ImageQualityFailure,
    ImageQualityReport,
    JewelryImageAgent,
    ProviderImage,
    QualityCheck,
    QualityVerdict,
    build_image_plan,
)
from facetta.project_backbone import (
    BriefProjectGeneration,
    DesignAlreadyLinked,
    PersistedProjectInput,
    ensure_design_chain_available,
    get_brief_project_generator,
    persist_project_v1,
)
from facetta.render import RenderUnavailable
from facetta.spec import Spec


def _png(color=(200, 200, 200)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (40, 40), color).save(out, format="PNG")
    return out.getvalue()


def _warning_brief_generation(raw_spec: dict) -> BriefProjectGeneration:
    spec = Spec.model_validate(raw_spec)
    source = _png()
    plan = build_image_plan(
        ImageOperation.SPEC_RENDER,
        "spec render needing review",
        spec=spec,
        source_image=source,
    )

    class Provider:
        def execute(self, *_args, **_kwargs):
            return ProviderImage(image_bytes=_png((50, 50, 50)))

    class Evaluator:
        def evaluate(self, *_args, **_kwargs):
            return ImageQualityReport(
                verdict=QualityVerdict.WARN,
                checks=(QualityCheck(
                    code="band_width_estimate",
                    passed=False,
                    severity=CheckSeverity.WARNING,
                    message="band width needs designer review",
                ),),
                score=88,
            )

    result = JewelryImageAgent(Provider(), Evaluator()).run(
        plan, source_image=source)
    return BriefProjectGeneration(
        concept_image=source,
        spec_render=result.image_bytes,
        spec=spec,
        quality_verdict="warn",
        quality_report={
            "verdict": "warn",
            "stage": "spec_render",
            "checks": ["band width"],
        },
        spec_render_run=result,
    )


def _warning_concept_generation() -> BriefProjectGeneration:
    plan = build_image_plan(
        ImageOperation.CONCEPT_GENERATE,
        "oval sapphire solitaire",
    )

    class Provider:
        def execute(self, *_args, **_kwargs):
            return ProviderImage(image_bytes=_png((70, 80, 90)))

    class Evaluator:
        def evaluate(self, *_args, **_kwargs):
            return ImageQualityReport(
                verdict=QualityVerdict.WARN,
                checks=(QualityCheck(
                    code="presentation_scale",
                    passed=False,
                    severity=CheckSeverity.WARNING,
                    message="presentation scale needs designer review",
                ),),
                score=87,
            )

    result = JewelryImageAgent(Provider(), Evaluator()).run(plan)
    return BriefProjectGeneration(
        concept_image=result.image_bytes,
        spec_render=b"",
        spec=None,
        quality_verdict="warn",
        quality_report={
            "verdict": "warn",
            "stage": "concept",
            "checks": ["presentation scale"],
        },
        concept_run=result,
    )


@pytest.fixture
def project_client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False)

    def override():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override
    try:
        yield TestClient(app), TestSession
    finally:
        app.dependency_overrides.clear()


def _image_request(example_spec: dict) -> dict:
    return {
        "image_base64": base64.b64encode(_png()).decode(),
        "media_type": "image/png",
        "spec": audited_import_spec(example_spec),
        "owner": "usr_ana",
        "title": "Royal blue solitaire",
        "collection": "Sarah K",
        "tags": [" sapphire ", "ring", "sapphire"],
    }


def _counts(Session) -> dict[str, int]:
    with Session() as db:
        return {
            "designs": db.scalar(select(func.count()).select_from(Design)),
            "versions": db.scalar(
                select(func.count()).select_from(DesignVersion)),
            "assets": db.scalar(select(func.count()).select_from(ImageAsset)),
            "projects": db.scalar(select(func.count()).select_from(Project)),
        }


def test_from_image_atomically_creates_confirmed_ring_project(
    project_client, example_spec,
):
    client, Session = project_client
    response = client.post("/projects/from-image", json=_image_request(example_spec))
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["state"] == "refining"
    assert body["primary_revision_count"] == 1
    assert body["item_count"] == 1
    assert body["active_revision"]["capability"] == "IMPORTED_REFERENCE"
    assert body["active_revision"]["provenance"] == "imported_reference"
    assert body["active_revision"]["design_version"] == 1
    assert body["active_revision"]["revision"] == 1
    assert body["active_revision"]["image_url"].endswith("/image")
    assert "image_b64" not in body["active_revision"]
    assert body["spec"]["design_id"] == body["design_id"]
    assert body["spec"]["version"] == 1
    assert body["tags"] == ["ring", "sapphire"]
    assert _counts(Session) == {
        "designs": 1, "versions": 1, "assets": 1, "projects": 1}


def test_from_image_without_source_coverage_writes_nothing(
    project_client,
    example_spec,
):
    client, Session = project_client
    request = _image_request(example_spec)
    request["spec"] = example_spec

    response = client.post("/projects/from-image", json=request)

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "source_component_coverage_required"
    assert _counts(Session) == {
        "designs": 0, "versions": 0, "assets": 0, "projects": 0,
    }


def test_project_render_persists_qa_approved_revision_and_rejects_stale_version(
    project_client, example_spec, monkeypatch,
):
    client, Session = project_client
    created = client.post("/projects/from-image", json=_image_request(example_spec))
    assert created.status_code == 201, created.text
    root_id = created.json()["root_id"]

    source = _png()
    spec = Spec.model_validate(example_spec)
    plan = build_image_plan(
        ImageOperation.SPEC_RENDER,
        "render the designer-confirmed ring",
        spec=spec,
        source_image=source,
    )

    class Provider:
        def execute(self, *_args, **_kwargs):
            return ProviderImage(image_bytes=_png((20, 30, 40)),
                                 provider_request_id="req_render")

    class Evaluator:
        def evaluate(self, *_args, **_kwargs):
            return ImageQualityReport(
                verdict=QualityVerdict.PASS,
                checks=(QualityCheck(code="metal", passed=True,
                                     severity=CheckSeverity.HARD,
                                     message="metal matches"),),
                score=96,
            )

    result = JewelryImageAgent(Provider(), Evaluator()).run(
        plan, source_image=source)

    class FakeAgent:
        def run(self, *_args, **_kwargs):
            return result

    monkeypatch.setattr("facetta.image_agent.JewelryImageAgent",
                        lambda: FakeAgent())

    stale = client.post(f"/projects/{root_id}/render", json={
        "created_by": "usr_ana", "expected_design_version": 2,
    })
    assert stale.status_code == 409
    assert stale.json()["error_category"] == "stale_version"

    accepted = client.post(f"/projects/{root_id}/render", json={
        "created_by": "usr_ana", "expected_design_version": 1,
    })
    assert accepted.status_code == 201, accepted.text
    body = accepted.json()
    assert body["status"] == "accepted"
    assert body["asset_id"] != root_id
    assert body["project"]["primary_revision_count"] == 2
    assert body["project"]["active_revision"]["provenance"] == "generated_spec_aligned"
    with Session() as db:
        run = db.get(ImageRun, body["image_run_id"])
        assert run.status == "accepted"
        assert run.accepted_asset_id == body["asset_id"]
        asset = db.get(ImageAsset, body["asset_id"])
        assert asset.design_version == 1


def test_product_photo_is_visual_only_and_warning_acceptance_keeps_spec_version(
    project_client, example_spec, monkeypatch,
):
    client, Session = project_client
    created = client.post("/projects/from-image", json=_image_request(example_spec))
    assert created.status_code == 201, created.text
    project = created.json()
    root_id = project["root_id"]
    source_id = project["active_asset_id"]
    source = _png()
    spec = Spec.model_validate(example_spec)

    plan = build_image_plan(
        ImageOperation.VISUAL_ONLY_EDIT,
        "restage on a clean white ecommerce background",
        spec=spec,
        source_spec=spec,
        source_image=source,
    )

    class Provider:
        def execute(self, *_args, **_kwargs):
            return ProviderImage(image_bytes=_png((245, 245, 245)),
                                 provider_request_id="req_product_photo")

    class WarningEvaluator:
        def evaluate(self, *_args, **_kwargs):
            return ImageQualityReport(
                verdict=QualityVerdict.WARN,
                checks=(QualityCheck(
                    code="presentation_detail",
                    passed=False,
                    severity=CheckSeverity.WARNING,
                    message="reflection needs designer review",
                ),),
                score=88,
            )

    result = JewelryImageAgent(Provider(), WarningEvaluator()).run(
        plan, source_image=source)

    class FakeAgent:
        def run(self, *_args, **_kwargs):
            return result

    monkeypatch.setattr("facetta.image_agent.JewelryImageAgent",
                        lambda: FakeAgent())

    scoped_out = client.post(f"/projects/{root_id}/product-photo", json={
        "created_by": "usr_ana",
        "expected_asset_id": source_id,
        "expected_design_version": 1,
        "preset": "catalog_white",
        "custom_instruction": "Remove the side stones and smooth the shank.",
    })
    assert scoped_out.status_code == 422
    assert scoped_out.json()["code"] == "presentation_scope_violation"

    warned = client.post(f"/projects/{root_id}/product-photo", json={
        "created_by": "usr_ana",
        "expected_asset_id": source_id,
        "expected_design_version": 1,
        "preset": "catalog_white",
        "framing": "portrait",
    })
    assert warned.status_code == 202, warned.text
    warning = warned.json()["warning_candidate"]
    assert warning["operation"] == "VISUAL_ONLY_EDIT"
    assert client.get(warning["preview_url"]).status_code == 200

    accepted = client.post(
        f"/image-runs/{warning['run_id']}/candidates/{warning['candidate_id']}/accept",
        json={"expected_design_version": 1, "created_by": "usr_ana"},
    )
    assert accepted.status_code == 201, accepted.text
    body = accepted.json()
    assert body["active_revision"]["capability"] == "PRODUCT_PHOTO"
    assert body["active_revision"]["provenance"] == "ecommerce_product_photo"
    assert body["active_design_version"] == 1
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 1


def test_product_photo_pass_atomically_persists_visual_revision(
    project_client, example_spec, monkeypatch,
):
    client, Session = project_client
    created = client.post("/projects/from-image", json=_image_request(example_spec))
    project = created.json()
    source = _png()
    spec = Spec.model_validate(example_spec)
    plan = build_image_plan(
        ImageOperation.VISUAL_ONLY_EDIT,
        "clean white ecommerce presentation",
        spec=spec,
        source_spec=spec,
        source_image=source,
    )

    class Provider:
        def execute(self, *_args, **_kwargs):
            return ProviderImage(image_bytes=_png((250, 250, 250)))

    class Evaluator:
        def evaluate(self, *_args, **_kwargs):
            return ImageQualityReport(
                verdict=QualityVerdict.PASS,
                checks=(QualityCheck(
                    code="geometry_preserved", passed=True,
                    severity=CheckSeverity.HARD,
                    message="approved ring geometry preserved",
                ),),
                score=97,
            )

    result = JewelryImageAgent(Provider(), Evaluator()).run(
        plan, source_image=source)

    class FakeAgent:
        def run(self, *_args, **_kwargs):
            return result

    monkeypatch.setattr("facetta.image_agent.JewelryImageAgent",
                        lambda: FakeAgent())
    response = client.post(
        f"/projects/{project['root_id']}/product-photo",
        json={
            "created_by": "usr_ana",
            "expected_asset_id": project["active_asset_id"],
            "expected_design_version": 1,
            "preset": "luxury_studio",
            "framing": "square",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "accepted"
    assert body["presentation"]["preset"] == "luxury_studio"
    assert body["project"]["active_revision"]["capability"] == "PRODUCT_PHOTO"
    assert body["project"]["active_design_version"] == 1
    delivered = client.get(f"/assets/{body['asset_id']}/image")
    assert delivered.status_code == 200
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 1
        run = db.get(ImageRun, body["image_run_id"])
        assert run.operation == "VISUAL_ONLY_EDIT"
        assert run.accepted_asset_id == body["asset_id"]
        assert delivered.content == bytes(db.get(ImageAsset, body["asset_id"]).image)


def test_line_art_requires_confirmation_then_color_persists_as_derived(
    project_client, example_spec, monkeypatch,
):
    client, Session = project_client
    created = client.post("/projects/from-image", json=_image_request(example_spec))
    project = created.json()
    source = _png()
    line_image = _png((248, 248, 248))
    colored_image = _png((20, 80, 140))
    spec = Spec.model_validate(example_spec)

    def passing_result(source_image: bytes, output: bytes, intent: str):
        plan = build_image_plan(
            ImageOperation.VISUAL_ONLY_EDIT,
            intent,
            spec=spec,
            source_spec=spec,
            source_image=source_image,
        )

        class Provider:
            def execute(self, *_args, **_kwargs):
                return ProviderImage(image_bytes=output)

        class Evaluator:
            def evaluate(self, *_args, **_kwargs):
                return ImageQualityReport(
                    verdict=QualityVerdict.PASS,
                    checks=(QualityCheck(
                        code="geometry_preserved", passed=True,
                        severity=CheckSeverity.HARD,
                        message="confirmed geometry preserved",
                    ),),
                    score=96,
                )

        return JewelryImageAgent(Provider(), Evaluator()).run(
            plan, source_image=source_image)

    line_result = passing_result(source, line_image, "make line art")
    color_result = passing_result(line_image, colored_image, "color confirmed line art")

    class FakeAgent:
        def run(self, _plan, *, source_image=None, **_kwargs):
            return line_result if source_image == source else color_result

    monkeypatch.setattr("facetta.image_agent.JewelryImageAgent",
                        lambda *_args, **_kwargs: FakeAgent())
    line = client.post(f"/projects/{project['root_id']}/line-art", json={
        "created_by": "usr_ana",
        "expected_asset_id": project["active_asset_id"],
        "expected_design_version": 1,
        "view": "three_quarter",
    })
    assert line.status_code == 202, line.text
    line_body = line.json()
    assert line_body["status"] == "confirmation_required"
    assert line_body["quality_report"]["verdict"] == "pass"
    assert client.get(line_body["candidate"]["preview_url"]).status_code == 200

    confirmed = client.post(
        f"/image-runs/{line_body['image_run_id']}/candidates/"
        f"{line_body['candidate']['candidate_id']}/accept",
        json={"expected_design_version": 1, "created_by": "usr_ana"},
    )
    assert confirmed.status_code == 201, confirmed.text
    confirmed_project = confirmed.json()
    assert confirmed_project["primary_revision_count"] == 1
    line_asset = next(
        item for item in confirmed_project["derived_assets"]
        if item["capability"] == "LINE_ART"
    )
    assert line_asset["provenance"] == "designer_confirmed_line_art"

    color = client.post(
        f"/projects/{project['root_id']}/line-art/{line_asset['asset_id']}/colorize",
        json={
            "created_by": "usr_ana",
            "expected_asset_id": project["active_asset_id"],
            "expected_design_version": 1,
        },
    )
    assert color.status_code == 201, color.text
    color_body = color.json()
    assert color_body["status"] == "accepted"
    assert color_body["project"]["primary_revision_count"] == 1
    colored = next(
        item for item in color_body["project"]["derived_assets"]
        if item["capability"] == "COLORED_LINE_ART"
    )
    assert colored["provenance"] == "spec_colored_line_art"
    assert color_body["project"]["active_asset_id"] == project["active_asset_id"]
    material_report = ImageQualityReport(
        verdict=QualityVerdict.FAIL,
        checks=(QualityCheck(
            code="approved_source_material_identity",
            passed=False,
            severity=CheckSeverity.HARD,
            message="diamond leaf stones became plain gold",
        ),),
        score=35,
    )

    class FailingMaterialAgent:
        def run(self, plan, **_kwargs):
            raise ImageQualityFailure(
                "no candidate passed jewelry QA: approved_source_material_identity",
                report=material_report,
                attempts=color_result.run.attempts,
                plan=plan,
            )

    monkeypatch.setattr(
        "facetta.image_agent.JewelryImageAgent",
        lambda *_args, **_kwargs: FailingMaterialAgent(),
    )
    rejected = client.post(
        f"/projects/{project['root_id']}/line-art/{line_asset['asset_id']}/colorize",
        json={
            "created_by": "usr_ana",
            "expected_asset_id": project["active_asset_id"],
            "expected_design_version": 1,
            "variant": 1,
        },
    )
    assert rejected.status_code == 422
    assert rejected.json()["code"] == "approved_source_material_identity_failed"
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 1
        assert db.get(ImageRun, line_body["image_run_id"]).status == "review_required"
        colored_count = db.scalar(select(func.count()).select_from(ImageAsset).where(
            ImageAsset.capability == "COLORED_LINE_ART"))
        assert colored_count == 1
        rejected_run = db.get(ImageRun, rejected.json()["image_run_id"])
        assert rejected_run.status == "failed"
        assert rejected_run.accepted_asset_id is None


def test_invalid_or_non_ring_spec_writes_nothing(project_client, example_spec):
    client, Session = project_client
    example_spec["stone"]["carat"] = 9.5
    invalid = client.post(
        "/projects/from-image", json=_image_request(example_spec))
    assert invalid.status_code == 422
    assert invalid.json()["error_category"] == "validation_failure"
    assert _counts(Session) == {
        "designs": 0, "versions": 0, "assets": 0, "projects": 0}


def test_brief_provider_and_quality_failures_write_nothing(
    project_client, example_spec,
):
    client, Session = project_client
    request = {"brief": "oval sapphire solitaire", "owner": "usr_ana"}

    def provider_failure(_brief: str, _variant: int):
        raise RenderUnavailable("provider timed out")

    app.dependency_overrides[get_brief_project_generator] = (
        lambda: provider_failure)
    failed = client.post("/projects/from-brief", json=request)
    assert failed.status_code == 502
    assert failed.json()["error_category"] == "provider_failure"

    def warning(_brief: str, _variant: int):
        return _warning_brief_generation(example_spec)

    app.dependency_overrides[get_brief_project_generator] = lambda: warning
    warned = client.post("/projects/from-brief", json=request)
    assert warned.status_code == 202
    warning_body = warned.json()
    assert warning_body["status"] == "review_required"
    assert warning_body["warning_candidate"]["candidate_id"].startswith("cand_")
    preview = client.get(warning_body["warning_candidate"]["preview_url"])
    assert preview.status_code == 200

    def quality_failure(_brief: str, _variant: int):
        return BriefProjectGeneration(
            concept_image=_png(), spec_render=_png((40, 40, 40)),
            spec=Spec.model_validate(example_spec), quality_verdict="fail",
            quality_report={"verdict": "fail", "checks": ["wrong metal"]},
            run_id="run_fail",
        )

    app.dependency_overrides[get_brief_project_generator] = (
        lambda: quality_failure)
    rejected = client.post("/projects/from-brief", json=request)
    assert rejected.status_code == 422
    assert rejected.json()["error_category"] == "quality_failure"
    assert _counts(Session) == {
        "designs": 0, "versions": 0, "assets": 0, "projects": 0}


def test_brief_warning_can_be_reviewed_and_atomically_promoted(
    project_client, example_spec,
):
    client, Session = project_client
    app.dependency_overrides[get_brief_project_generator] = lambda: (
        lambda _brief, _variant: _warning_brief_generation(example_spec))
    warned = client.post("/projects/from-brief", json={
        "brief": "oval sapphire solitaire",
        "owner": "usr_ana",
        "title": "Reviewed concept",
    })
    candidate = warned.json()["warning_candidate"]
    accepted = client.post(
        f"/projects/from-brief/candidates/{candidate['candidate_id']}/accept",
        json={"created_by": "usr_ana"},
    )
    assert accepted.status_code == 200, accepted.text
    body = accepted.json()
    assert body["primary_revision_count"] == 1
    assert body["active_design_version"] == 1
    assert _counts(Session) == {
        "designs": 1, "versions": 1, "assets": 2, "projects": 1}
    with Session() as db:
        review = db.scalar(select(ImageRunReview).where(
            ImageRunReview.run_id == warned.json()["image_run_id"]))
        assert review.accepted_asset_id == body["active_asset_id"]
        stored_run = db.get(ImageRun, warned.json()["image_run_id"])
        assert stored_run.status == "review_required"
        assert stored_run.accepted_asset_id is None


def test_reviewed_concept_continues_to_spec_before_project_creation(
    project_client, example_spec, monkeypatch,
):
    client, Session = project_client
    generated_concept = _warning_concept_generation()
    app.dependency_overrides[get_brief_project_generator] = lambda: (
        lambda _brief, _variant: generated_concept)
    warned = client.post("/projects/from-brief", json={
        "brief": "oval sapphire solitaire",
        "owner": "usr_ana",
    })
    assert warned.status_code == 202
    assert _counts(Session)["projects"] == 0

    def continue_after_review(brief, variant, concept):
        assert brief == "oval sapphire solitaire"
        assert variant == 0
        assert concept is generated_concept.concept_run
        return BriefProjectGeneration(
            concept_image=generated_concept.concept_image,
            spec_render=_png((40, 60, 80)),
            spec=Spec.model_validate(example_spec),
            quality_verdict="pass",
            quality_report={"verdict": "pass", "stage": "spec_render"},
            concept_run=generated_concept.concept_run,
        )

    monkeypatch.setattr(
        "facetta.trusted_brief.continue_trusted_brief_project",
        continue_after_review,
    )
    candidate_id = warned.json()["warning_candidate"]["candidate_id"]
    accepted = client.post(
        f"/projects/from-brief/candidates/{candidate_id}/accept",
        json={"created_by": "usr_ana"},
    )
    assert accepted.status_code == 200, accepted.text
    body = accepted.json()
    assert body["active_revision"]["capability"] == "SPEC_RENDER"
    source = next(item for item in body["derived_assets"]
                  if item["capability"] == "SOURCE_CONCEPT")
    with Session() as db:
        review = db.scalar(select(ImageRunReview).where(
            ImageRunReview.run_id == warned.json()["image_run_id"]))
        assert review.accepted_asset_id == source["asset_id"]


def test_default_brief_agent_logs_provider_failure_without_partial_project(
    project_client, monkeypatch,
):
    client, Session = project_client
    monkeypatch.delenv("XAI_KEY", raising=False)
    monkeypatch.delenv("FAL_KEY", raising=False)
    monkeypatch.setattr(
        "facetta.image_agent.providers.configured_fallback_provider",
        lambda: None,
    )
    monkeypatch.setattr("facetta.render._provider_key", lambda _name: None)
    response = client.post("/projects/from-brief", json={
        "brief": "oval sapphire solitaire", "owner": "usr_ana"})
    assert response.status_code == 503, response.text
    assert response.json()["error_category"] == "provider_failure"
    run_id = response.json()["image_run_id"]
    assert run_id
    assert _counts(Session) == {
        "designs": 0, "versions": 0, "assets": 0, "projects": 0}
    with Session() as db:
        run = db.get(ImageRun, run_id)
        assert run.status == "failed"
        assert run.error_category == "provider"
        assert run.input_hash
        assert run.mask_hash is None
        attempts = list(db.scalars(
            select(ImageAttempt)
            .where(ImageAttempt.run_id == run_id)
            .order_by(ImageAttempt.attempt_number)))
        assert [attempt.attempt_number for attempt in attempts] == [1, 2, 3]
        assert all(attempt.output_hash is None for attempt in attempts)
        assert all(attempt.prompt_hash for attempt in attempts)
        assert all(attempt.cache_key for attempt in attempts)


def test_brief_pass_persists_spec_render_and_derived_source(
    project_client, example_spec,
):
    client, Session = project_client

    def passing(_brief: str, _variant: int):
        return BriefProjectGeneration(
            concept_image=_png((220, 180, 80)),
            spec_render=_png((80, 90, 100)),
            spec=Spec.model_validate(example_spec),
            quality_verdict="pass",
            quality_report={"verdict": "pass", "checks": []},
            corrections=("band corrected",),
            run_id="run_pass",
        )

    app.dependency_overrides[get_brief_project_generator] = lambda: passing
    response = client.post("/projects/from-brief", json={
        "brief": "oval sapphire solitaire", "owner": "usr_ana"})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["title"] == "oval sapphire solitaire"
    assert body["primary_revision_count"] == 1
    assert body["item_count"] == 2
    assert body["active_revision"]["capability"] == "SPEC_RENDER"
    assert body["active_revision"]["provenance"] == "generated_spec_aligned"
    assert [a["capability"] for a in body["derived_assets"]] == [
        "SOURCE_CONCEPT"]
    assert body["derived_assets"][0]["provenance"] == "generated_concept"
    assert _counts(Session)["assets"] == 2


def test_persistence_rolls_back_every_row_when_flush_fails(example_spec):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)
    db = Session()
    original_flush = db.flush

    def fail_after_flush(*args, **kwargs):
        original_flush(*args, **kwargs)
        raise RuntimeError("simulated database failure")

    db.flush = fail_after_flush  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="simulated database failure"):
        persist_project_v1(
            db,
            PersistedProjectInput(
                spec=Spec.model_validate(example_spec),
                primary_image=_png(),
                primary_capability="IMPORTED_REFERENCE",
            ),
            owner="usr_ana", title="Must roll back",
        )
    db.close()
    assert _counts(Session) == {
        "designs": 0, "versions": 0, "assets": 0, "projects": 0}


def test_accepted_image_run_is_atomically_bound_to_revision_one(example_spec):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)
    spec = Spec.model_validate(example_spec)
    plan = build_image_plan(
        ImageOperation.SPEC_RENDER, "spec-aligned hero", spec=spec)

    class Provider:
        def execute(self, *_args, **_kwargs):
            return ProviderImage(
                image_bytes=_png((70, 80, 90)),
                provider_request_id="req_project_v1",
                usage={"images": 1},
                cost=0.02,
            )

    class Evaluator:
        def evaluate(self, *_args, **_kwargs):
            return ImageQualityReport(
                verdict=QualityVerdict.PASS,
                checks=(QualityCheck(
                    code="metal", passed=True, severity=CheckSeverity.HARD,
                    message="metal matches"),),
                score=98,
            )

    agent_result = JewelryImageAgent(Provider(), Evaluator()).run(plan)
    with Session() as db:
        stored = persist_project_v1(
            db,
            PersistedProjectInput(
                spec=spec,
                primary_image=agent_result.image_bytes,
                primary_capability="SPEC_RENDER",
                primary_image_run=agent_result,
            ),
            owner="usr_ana", title="Observed ring",
        )
        assert len(stored.image_run_ids) == 1
        run = db.get(ImageRun, stored.image_run_ids[0])
        assert run.project_root_id == stored.root_id
        assert run.accepted_asset_id == stored.root_id
        assert run.status == "accepted"
        assert run.input_hash == plan.input_hash
        assert run.mask_hash == plan.mask_hash
        attempt = db.scalar(select(ImageAttempt).where(
            ImageAttempt.run_id == run.id))
        assert attempt.attempt_number == 1
        assert attempt.qa_verdict == "pass"
        assert attempt.provider_request_id == "req_project_v1"
        assert attempt.prompt_hash == agent_result.run.attempts[0].prompt_hash
        assert attempt.cache_key == agent_result.run.attempts[0].cache_key


def test_detail_groups_primary_revisions_and_derivatives_and_derives_state(
    project_client, example_spec,
):
    client, Session = project_client
    with Session() as db:
        now = utcnow()
        design_id = "dsn_legacy"
        db.add(Design(id=design_id, created_by="usr_ana"))
        db.add(DesignVersion(
            design_id=design_id, version=1, spec=example_spec,
            created_by="usr_ana"))
        root = ImageAsset(
            id="ast_root", root_id="ast_root", parent_asset_id=None,
            design_id=design_id, design_version=None,
            capability="JEWELRY_RENDER", image=_png(),
            media_type="image/png", created_by="usr_ana", created_at=now)
        view = ImageAsset(
            id="ast_view", root_id="ast_root", parent_asset_id="ast_root",
            capability="ANGLE_VIEW", image=_png(), media_type="image/png",
            created_by="usr_ana", created_at=now)
        edit = ImageAsset(
            id="ast_edit", root_id="ast_root", parent_asset_id="ast_root",
            capability="LOCALIZED_EDIT", design_version=None,
            image=_png(), media_type="image/png", created_by="usr_ana",
            created_at=now)
        db.add_all([root, view, edit, Project(
            root_id="ast_root", owner="usr_ana", title="Legacy ring", tags=[])])
        db.commit()

    first = client.get("/projects/ast_root")
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["state"] == "refining"
    assert body["primary_revision_count"] == 2
    assert [r["revision"] for r in body["revisions"]] == [1, 2]
    assert [a["asset_id"] for a in body["derived_assets"]] == ["ast_view"]
    assert all(r["legacy_provenance"] for r in body["revisions"])
    assert body["active_revision"]["asset_id"] == "ast_edit"

    # Approval of an older pinned revision cannot make a newer active edit
    # factory-ready.
    with Session() as db:
        db.get(ImageAsset, "ast_root").pinned_at = utcnow()
        db.add(ApprovalChecklist(
            id="chk_old", asset_id="ast_root", design_id="dsn_legacy",
            design_version=None, mode="auto_pin", items=[{"key": "stone"}],
            created_by="usr_ana"))
        db.add(ApprovalResponse(
            checklist_id="chk_old", item_key="stone", approved=True,
            created_by="usr_ana"))
        db.commit()
    old_approval = client.get("/projects/ast_root").json()
    assert old_approval["state"] == "refining"
    assert old_approval["pinned_revision"]["asset_id"] == "ast_root"

    with Session() as db:
        checklist = ApprovalChecklist(
            id="chk_active", asset_id="ast_edit", design_id="dsn_legacy",
            design_version=None, mode="explicit_pin",
            items=[{"key": "stone"}], created_by="usr_ana")
        db.add(checklist)
        db.commit()
    assert client.get("/projects/ast_root").json()["state"] == \
        "approval_required"

    with Session() as db:
        db.add(ApprovalResponse(
            checklist_id="chk_active", item_key="stone", approved=True,
            created_by="usr_ana"))
        db.commit()
    assert client.get("/projects/ast_root").json()["state"] == "approved"

    with Session() as db:
        db.get(ImageAsset, "ast_edit").pinned_at = utcnow()
        db.commit()
    ready = client.get("/projects/ast_root").json()
    assert ready["state"] == "factory_ready"
    assert ready["pinned_revision"]["asset_id"] == "ast_edit"
    assert ready["approval"]["design_id"] == "dsn_legacy"
    assert ready["approval"]["approved_count"] == 1
    assert ready["approval"]["answers"]["stone"]["approved"] is True


def test_duplicate_design_chain_is_rejected_by_service_and_database():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)
    with Session() as db:
        db.add(Design(id="dsn_one", created_by="usr_ana"))
        db.add(ImageAsset(
            id="ast_a", root_id="ast_a", parent_asset_id=None,
            design_id="dsn_one", capability="JEWELRY_RENDER", image=_png(),
            media_type="image/png", created_by="usr_ana"))
        db.commit()
        ensure_design_chain_available(db, "dsn_one", "ast_a")  # idempotent
        with pytest.raises(DesignAlreadyLinked) as caught:
            ensure_design_chain_available(db, "dsn_one", "ast_b")
        assert caught.value.root_id == "ast_a"
        db.add(ImageAsset(
            id="ast_b", root_id="ast_b", parent_asset_id=None,
            design_id="dsn_one", capability="JEWELRY_RENDER", image=_png(),
            media_type="image/png", created_by="usr_ana"))
        with pytest.raises(IntegrityError):
            db.commit()


def test_additive_bootstrap_preserves_legacy_null_version_and_adds_run_tables():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE designs (id VARCHAR(32) PRIMARY KEY, "
            "created_by VARCHAR(32), created_at DATETIME)"))
        conn.execute(text(
            "CREATE TABLE image_assets (id VARCHAR(32) PRIMARY KEY, "
            "root_id VARCHAR(32), parent_asset_id VARCHAR(32), "
            "capability VARCHAR(48), image BLOB, media_type VARCHAR(24), "
            "created_by VARCHAR(32), created_at DATETIME)"))
        conn.execute(text(
            "CREATE TABLE image_runs (id VARCHAR(32) PRIMARY KEY)"))
        conn.execute(text(
            "CREATE TABLE image_attempts (id VARCHAR(32) PRIMARY KEY, "
            "run_id VARCHAR(32))"))
        conn.execute(text(
            "INSERT INTO image_assets "
            "(id, root_id, capability, image, media_type, created_by) "
            "VALUES ('ast_old', 'ast_old', 'JEWELRY_RENDER', X'00', "
            "'image/png', 'usr_old')"))
        conn.execute(text(
            "INSERT INTO image_runs (id) VALUES ('run_old')"))
        conn.execute(text(
            "INSERT INTO image_attempts (id, run_id) "
            "VALUES ('iat_old', 'run_old')"))

    # This is get_engine's production order: create missing additive tables,
    # then add columns to tables that already existed.
    Base.metadata.create_all(engine)
    _apply_additive_migrations(engine)
    inspector = inspect(engine)
    columns = {c["name"] for c in inspector.get_columns("image_assets")}
    assert {"design_id", "design_version"} <= columns
    run_columns = {c["name"] for c in inspector.get_columns("image_runs")}
    assert {"input_hash", "mask_hash"} <= run_columns
    attempt_columns = {
        c["name"] for c in inspector.get_columns("image_attempts")}
    assert {"prompt_hash", "cache_key"} <= attempt_columns
    feedback_columns = {
        c["name"] for c in inspector.get_columns("feedback_events")}
    assert {"image_run_id", "subject_kind"} <= feedback_columns
    assert {
        ImageRun.__tablename__, ImageAttempt.__tablename__,
        ImageRunReview.__tablename__,
    } <= set(
        inspector.get_table_names())
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT design_id, design_version FROM image_assets "
            "WHERE id='ast_old'"))
        assert row.one() == (None, None)
        legacy_run = conn.execute(text(
            "SELECT input_hash, mask_hash FROM image_runs "
            "WHERE id='run_old'"))
        assert legacy_run.one() == (None, None)
        legacy_attempt = conn.execute(text(
            "SELECT prompt_hash, cache_key FROM image_attempts "
            "WHERE id='iat_old'"))
        assert legacy_attempt.one() == (None, None)

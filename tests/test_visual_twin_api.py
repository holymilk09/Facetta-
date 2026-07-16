"""Visual Twin views are independent AI proposals with explicit promotion."""

from __future__ import annotations

import base64
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from conftest import EXAMPLE_SPEC, audited_import_spec
from facetta.api.projects import get_mounting_view_generator
from facetta.db import (
    Base,
    DerivedArtifactMetadata,
    DesignVersion,
    ImageAsset,
    ImageRun,
    ImageRunReview,
    get_db,
)
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
from facetta.main import app
from facetta.warning_candidates import clear_warning_candidates_for_tests


def _png(color: tuple[int, int, int]) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (128, 128), color).save(output, format="PNG")
    return output.getvalue()


SOURCE = _png((210, 210, 210))


@pytest.fixture
def visual_twin_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db():
        with Session() as db:
            yield db

    clear_warning_candidates_for_tests()
    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    try:
        yield client, Session
    finally:
        app.dependency_overrides.clear()
        clear_warning_candidates_for_tests()


def _project(client: TestClient) -> dict:
    response = client.post("/projects/from-image", json={
        "image_base64": base64.b64encode(SOURCE).decode(),
        "media_type": "image/png",
        "spec": audited_import_spec(EXAMPLE_SPEC),
        "owner": "usr_designer",
        "title": "Oval sapphire variation",
    })
    assert response.status_code == 201, response.text
    return response.json()


def _result(spec, source: bytes, view: str, variant: int):
    plan = build_image_plan(
        ImageOperation.MOUNTING_VIEW_GENERATE,
        f"Create the design-specific {view} mounting view.",
        spec=spec,
        source_image=source,
        mounting_view=view,
        variant=variant,
    )

    class Provider:
        def execute(self, *_args, **_kwargs):
            return ProviderImage(image_bytes=_png((30 + variant, 40, 50)))

    class Evaluator:
        def evaluate(self, *_args, **_kwargs):
            return ImageQualityReport(
                verdict=QualityVerdict.WARN,
                checks=(QualityCheck(
                    code="factory_authority",
                    passed=False,
                    severity=CheckSeverity.WARNING,
                    message="designer confirmation required",
                    evidence={
                        "factory_authoritative": False,
                        "designer_confirmation_required": True,
                    },
                ),),
                score=96,
            )

    return JewelryImageAgent(Provider(), Evaluator()).run(
        plan, source_image=source)


def _request(project: dict, views: list[str]) -> dict[str, object]:
    return {
        "created_by": "usr_designer",
        "expected_asset_id": project["active_asset_id"],
        "expected_design_version": project["active_design_version"],
        "views": views,
        "starting_variant": 4,
    }


def test_visual_twin_candidates_wait_for_review_and_accept_as_derived(
    visual_twin_client,
):
    client, Session = visual_twin_client
    project = _project(client)
    calls: list[tuple[str, int]] = []

    def generate(spec, source, view, variant):
        calls.append((view, variant))
        return _result(spec, source, view, variant)

    app.dependency_overrides[get_mounting_view_generator] = lambda: generate
    response = client.post(
        f"/projects/{project['root_id']}/visual-twin/views",
        json=_request(project, ["side", "section"]),
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert calls == [("side", 4), ("section", 5)]
    assert body["status"] == "review_required"
    assert body["candidate_count"] == 2
    assert body["failed_count"] == 0
    assert body["maximum_provider_attempts"] == 8
    assert all(item["promotion_kind"] == "derived_only"
               for item in body["candidates"])
    assert all(item["authority"] == "factory_discussion_only"
               for item in body["candidates"])

    pending = client.get(f"/projects/{project['root_id']}").json()
    assert pending["active_asset_id"] == project["active_asset_id"]
    assert pending["primary_revision_count"] == 1
    assert not any(
        item["capability"] == "FACTORY_REVIEW_MOUNTING_VIEW"
        for item in pending["assets"]
    )

    side = body["candidates"][0]
    accepted = client.post(
        f"/image-runs/{side['image_run_id']}/candidates/"
        f"{side['candidate_id']}/accept",
        json={
            "expected_design_version": 1,
            "created_by": "usr_designer",
        },
    )
    assert accepted.status_code == 201, accepted.text
    after = accepted.json()
    assert after["active_asset_id"] == project["active_asset_id"]
    assert after["primary_revision_count"] == 1
    mounting = [
        item for item in after["derived_assets"]
        if item["capability"] == "FACTORY_REVIEW_MOUNTING_VIEW"
    ]
    assert len(mounting) == 1
    assert mounting[0]["provenance"] == (
        "designer_reviewed_mounting_proposal"
    )

    with Session() as db:
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 1
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 2
        assert db.scalar(select(func.count()).select_from(ImageRun)) == 2
        assert db.scalar(select(func.count()).select_from(ImageRunReview)) == 1
        metadata = db.scalar(select(DerivedArtifactMetadata))
        assert metadata is not None and metadata.view == "side"
        assert metadata.production_authority is False


def test_visual_twin_hard_failure_records_evidence_but_no_candidate_asset(
    visual_twin_client,
):
    client, Session = visual_twin_client
    project = _project(client)

    def generate(spec, source, view, variant):
        plan = build_image_plan(
            ImageOperation.MOUNTING_VIEW_GENERATE,
            f"Create {view}",
            spec=spec,
            source_image=source,
            mounting_view=view,
            variant=variant,
        )
        raise ImageQualityFailure(
            "wrong projection",
            report=ImageQualityReport(
                verdict=QualityVerdict.FAIL,
                checks=(QualityCheck(
                    code="mounting:requested_projections",
                    passed=False,
                    severity=CheckSeverity.HARD,
                    message="candidate is not the requested side profile",
                ),),
                score=20,
            ),
            attempts=[],
            plan=plan,
        )

    app.dependency_overrides[get_mounting_view_generator] = lambda: generate
    response = client.post(
        f"/projects/{project['root_id']}/visual-twin/views",
        json=_request(project, ["side"]),
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "failed"
    assert body["candidate_count"] == 0
    assert body["failed_count"] == 1
    assert body["failures"][0]["error_category"] == "quality"
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 1
        run = db.scalar(select(ImageRun))
        assert run is not None and run.status == "failed"
        assert run.accepted_asset_id is None


def test_visual_twin_rejects_duplicates_and_stale_source_before_generation(
    visual_twin_client,
):
    client, _Session = visual_twin_client
    project = _project(client)
    calls = 0

    def generate(*_args):
        nonlocal calls
        calls += 1
        raise AssertionError("provider must not run")

    app.dependency_overrides[get_mounting_view_generator] = lambda: generate
    duplicate = client.post(
        f"/projects/{project['root_id']}/visual-twin/views",
        json=_request(project, ["side", "side"]),
    )
    assert duplicate.status_code == 422
    stale_request = _request(project, ["side"])
    stale_request["expected_asset_id"] = "ast_stale"
    stale = client.post(
        f"/projects/{project['root_id']}/visual-twin/views",
        json=stale_request,
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "stale_asset_revision"
    assert calls == 0

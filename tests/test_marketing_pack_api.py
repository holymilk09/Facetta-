"""Ecommerce background packs remain derived from the approved design state."""

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
from facetta.db import (
    Base,
    DesignVersion,
    ImageAsset,
    ImageRun,
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
from facetta.presentation import get_marketing_image_generator
from facetta.warning_candidates import clear_warning_candidates_for_tests


def _png(color: tuple[int, int, int]) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (96, 96), color).save(out, format="PNG")
    return out.getvalue()


SOURCE = _png((210, 210, 210))


@pytest.fixture
def marketing_client():
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
        "title": "Approved-design source",
    })
    assert response.status_code == 201, response.text
    return response.json()


def _approve(client: TestClient, asset_id: str) -> None:
    created = client.post(f"/assets/{asset_id}/checklist", json={
        "created_by": "usr_designer",
        "mode": "auto_pin",
    })
    assert created.status_code == 201, created.text
    for item in created.json()["items"]:
        answered = client.post(
            f"/assets/{asset_id}/checklist/respond",
            json={
                "item_key": item["key"],
                "approved": True,
                "created_by": "usr_designer",
            },
        )
        assert answered.status_code == 201, answered.text


def _result(spec, source: bytes, brief, variant: int, *, warn: bool = False):
    plan = build_image_plan(
        ImageOperation.VISUAL_ONLY_EDIT,
        brief.intent,
        spec=spec,
        source_spec=spec,
        source_image=source,
        style_constraints=brief.style_constraints,
        expected_output=brief.expected_output,
        variant=variant,
    )

    class Provider:
        def execute(self, *_args, **_kwargs):
            return ProviderImage(image_bytes=_png((40 + variant, 50, 60)))

    class Evaluator:
        def evaluate(self, *_args, **_kwargs):
            verdict = QualityVerdict.WARN if warn else QualityVerdict.PASS
            return ImageQualityReport(
                verdict=verdict,
                checks=(QualityCheck(
                    code="designer_scene_review" if warn else "jewelry_frozen",
                    passed=not warn,
                    severity=(CheckSeverity.WARNING if warn
                              else CheckSeverity.HARD),
                    message=("lighting needs review" if warn
                             else "jewelry geometry is unchanged"),
                ),),
                score=86 if warn else 97,
            )

    return JewelryImageAgent(Provider(), Evaluator()).run(
        plan, source_image=source)


def _pack_request(project: dict, presets: list[str]) -> dict[str, object]:
    return {
        "created_by": "usr_designer",
        "expected_asset_id": project["active_asset_id"],
        "expected_design_version": project["active_design_version"],
        "presets": presets,
        "framing": "portrait",
        "custom_instruction": "Keep generous product margins.",
        "starting_variant": 5,
    }


def test_pack_candidates_are_reviewable_and_accept_as_derived_assets(
    marketing_client,
):
    client, Session = marketing_client
    project = _project(client)
    _approve(client, project["active_asset_id"])
    approved = client.get(f"/projects/{project['root_id']}").json()
    assert approved["state"] == "factory_ready"
    assert approved["pinned_revision"]["asset_id"] == project["active_asset_id"]
    calls: list[tuple[str, int]] = []

    def generate(spec, source, brief, variant):
        calls.append((brief.intent, variant))
        return _result(spec, source, brief, variant)

    app.dependency_overrides[get_marketing_image_generator] = lambda: generate
    response = client.post(
        f"/projects/{project['root_id']}/marketing-pack",
        json=_pack_request(project, [
            "catalog_white", "luxury_studio", "dark_editorial",
        ]),
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert [variant for _intent, variant in calls] == [5, 6, 7]
    assert body["status"] == "review_required"
    assert body["candidate_count"] == 3
    assert body["failed_count"] == 0
    assert body["maximum_provider_attempts"] == 9
    assert body["actual_attempts"] == 3
    assert all(candidate["preview_url"].startswith("/image-runs/")
               for candidate in body["candidates"])

    refreshed = client.get(f"/projects/{project['root_id']}").json()
    assert refreshed["state"] == "factory_ready"
    assert refreshed["active_asset_id"] == project["active_asset_id"]
    assert refreshed["primary_revision_count"] == 1
    assert not any(item["capability"] == "MARKETING_IMAGE"
                   for item in refreshed["assets"])

    first = body["candidates"][0]
    accepted = client.post(
        f"/image-runs/{first['image_run_id']}/candidates/"
        f"{first['candidate_id']}/accept",
        json={
            "expected_design_version": 1,
            "created_by": "usr_designer",
        },
    )
    assert accepted.status_code == 201, accepted.text
    after = accepted.json()
    assert after["state"] == "factory_ready"
    assert after["pinned_revision"]["asset_id"] == project["active_asset_id"]
    assert after["active_asset_id"] == project["active_asset_id"]
    assert after["primary_revision_count"] == 1
    marketing = [item for item in after["derived_assets"]
                 if item["capability"] == "MARKETING_IMAGE"]
    assert len(marketing) == 1
    assert marketing[0]["design_version"] == 1
    assert marketing[0]["provenance"] == "ecommerce_marketing_derivative"

    with Session() as db:
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 1
        assert db.scalar(select(func.count()).select_from(ImageRun)) == 3
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 2


def test_pack_continues_after_one_hard_failure_without_persisting_failed_bytes(
    marketing_client,
):
    client, Session = marketing_client
    project = _project(client)

    def generate(spec, source, brief, variant):
        if "dark editorial" in brief.intent:
            plan = build_image_plan(
                ImageOperation.VISUAL_ONLY_EDIT,
                brief.intent,
                spec=spec,
                source_spec=spec,
                source_image=source,
                variant=variant,
            )
            raise ImageQualityFailure(
                "candidate changed the jewelry",
                report=ImageQualityReport(
                    verdict=QualityVerdict.FAIL,
                    checks=(QualityCheck(
                        code="geometry_preserved",
                        passed=False,
                        severity=CheckSeverity.HARD,
                        message="ring geometry changed",
                    ),),
                    score=25,
                ),
                attempts=[],
                plan=plan,
            )
        return _result(spec, source, brief, variant, warn=True)

    app.dependency_overrides[get_marketing_image_generator] = lambda: generate
    response = client.post(
        f"/projects/{project['root_id']}/marketing-pack",
        json=_pack_request(project, ["catalog_white", "dark_editorial"]),
    )
    assert response.status_code == 202
    body = response.json()
    assert body["candidate_count"] == 1
    assert body["failed_count"] == 1
    assert body["failures"][0]["error_category"] == "quality"
    assert body["failures"][0]["image_run_id"].startswith("run_")
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 1
        runs = list(db.scalars(select(ImageRun).order_by(ImageRun.created_at)))
        assert {run.status for run in runs} == {"review_required", "failed"}
        assert all(run.accepted_asset_id is None for run in runs)


def test_pack_rejects_duplicates_stale_sources_and_design_mutation_before_calls(
    marketing_client,
):
    client, _Session = marketing_client
    project = _project(client)
    calls = 0

    def generate(*_args):
        nonlocal calls
        calls += 1
        raise AssertionError("provider must not run")

    app.dependency_overrides[get_marketing_image_generator] = lambda: generate
    duplicate = client.post(
        f"/projects/{project['root_id']}/marketing-pack",
        json=_pack_request(project, ["catalog_white", "catalog_white"]),
    )
    assert duplicate.status_code == 422

    stale = _pack_request(project, ["catalog_white"])
    stale["expected_asset_id"] = "ast_stale"
    assert client.post(
        f"/projects/{project['root_id']}/marketing-pack", json=stale,
    ).status_code == 409

    mutation = _pack_request(project, ["catalog_white"])
    mutation["custom_instruction"] = "Remove the side stones."
    rejected = client.post(
        f"/projects/{project['root_id']}/marketing-pack", json=mutation,
    )
    assert rejected.status_code == 422
    assert rejected.json()["code"] == "presentation_scope_violation"
    assert calls == 0

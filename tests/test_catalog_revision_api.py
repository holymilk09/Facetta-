"""Persisted catalog selections use one deterministic spec/image transaction."""

from __future__ import annotations

import base64
import hashlib
import io
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from conftest import NECKLACE_SPEC, audited_import_spec
from facetta.db import (
    Base,
    DesignVersion,
    ImageAsset,
    ImageRun,
    ImageRunReview,
    PreviewCandidateRecord,
    Project,
    StudioJobRecord,
    get_db,
)
from facetta.design_form import NormalizedPoint, NormalizedPolygon
from facetta.catalog_preview_candidates import (
    clear_catalog_preview_candidates_for_tests,
)
from facetta.component_catalog import get_component_catalog
from facetta.image_agent import (
    CheckSeverity,
    DesignerEditDomain,
    ImageQualityFailure,
    ImageQualityReport,
    JewelryImageAgent,
    ProviderImage,
    QualityCheck,
    QualityVerdict,
)
from facetta.main import app
from facetta.revision_component_map import (
    RevisionComponent,
    RevisionComponentMap,
    component_map_hash,
    polygon_hash,
    rasterize_component_masks,
)
from facetta.revision_component_map_store import load_revision_component_map
from facetta.revision_component_map_store import add_revision_component_map
from facetta.warning_candidates import clear_warning_candidates_for_tests


def _png(color: tuple[int, int, int] = (210, 210, 210)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (40, 40), color).save(out, format="PNG")
    return out.getvalue()


@pytest.fixture
def catalog_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
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

    clear_warning_candidates_for_tests()
    clear_catalog_preview_candidates_for_tests()
    app.dependency_overrides[get_db] = override
    try:
        yield TestClient(app), TestSession
    finally:
        app.dependency_overrides.clear()
        clear_warning_candidates_for_tests()
        clear_catalog_preview_candidates_for_tests()


_RING_COMPONENTS = (
    ("center", "center_stone"),
    ("prongs", "prongs"),
    ("setting", "setting"),
    ("shank", "shank"),
    ("shoulders", "shoulders"),
    ("gallery", "gallery"),
    ("metal", "metal_zone"),
    ("background", "background"),
)


def _component_map(
    asset_id: str,
    image: bytes,
    *,
    unresolved_kind: str | None = None,
) -> RevisionComponentMap:
    components = []
    for index, (component_id, kind) in enumerate(_RING_COMPONENTS):
        offset = min(index, 5) * 0.02
        polygons = (NormalizedPolygon(points=(
            NormalizedPoint(x=0.1 + offset, y=0.1 + offset),
            NormalizedPoint(x=0.45 + offset, y=0.1 + offset),
            NormalizedPoint(x=0.45 + offset, y=0.45 + offset),
            NormalizedPoint(x=0.1 + offset, y=0.45 + offset),
        )),)
        resolved = kind != unresolved_kind
        components.append(RevisionComponent(
            component_id=component_id,
            kind=kind,
            label=component_id.title(),
            resolution="resolved" if resolved else "unresolved",
            polygons=polygons if resolved else (),
            polygon_sha256=polygon_hash(polygons) if resolved else None,
        ))
    with Image.open(io.BytesIO(image)) as raster:
        width, height = raster.size
    return RevisionComponentMap(
        asset_id=asset_id,
        asset_sha256=hashlib.sha256(image).hexdigest(),
        raster_width=width,
        raster_height=height,
        jewelry_type="ring",
        mapper_contract="test.catalog-map.v1",
        components=tuple(components),
    )


def _map_project(
    SessionFactory: sessionmaker,
    project: dict,
    *,
    unresolved_kind: str | None = None,
) -> None:
    with SessionFactory() as db:
        asset = db.get(ImageAsset, project["active_asset_id"])
        assert asset is not None
        image = bytes(asset.image)
        add_revision_component_map(
            db,
            _component_map(
                asset.id, image, unresolved_kind=unresolved_kind),
            image_bytes=image,
            parent_asset_id=None,
        )
        db.commit()


def _create_project(
    client: TestClient,
    example_spec: dict,
    SessionFactory: sessionmaker | None = None,
    map_revision: bool = True,
    unresolved_kind: str | None = None,
) -> dict:
    response = client.post("/projects/from-image", json={
        "image_base64": base64.b64encode(_png()).decode(),
        "media_type": "image/png",
        "spec": audited_import_spec(example_spec),
        "owner": "usr_catalog",
        "title": "Catalog ring",
    })
    assert response.status_code == 201, response.text
    project = response.json()
    if example_spec["jewelry_type"] == "ring" and map_revision:
        assert SessionFactory is not None
        _map_project(
            SessionFactory, project, unresolved_kind=unresolved_kind)
    return project


def _open_link_geometry(*, width: float = 2.0) -> dict:
    thickness = 0.35 if width == 2.0 else 0.4
    inside_width = width - 2 * thickness
    inside_length = 3.1 if width == 2.0 else 3.2
    return {
        "construction": "open_link",
        "chain_width_mm": width,
        "profile_thickness_mm": 0.6 if width == 2.0 else 0.65,
        "end_ring_outer_diameter_mm": 1.8 if width == 2.0 else 2.0,
        "link_thickness_mm": thickness,
        "links_soldered": True,
        "links": [{
            "role": "standard",
            "length_mm": inside_length + 2 * thickness,
            "inside_length_mm": inside_length,
            "inside_width_mm": inside_width,
        }],
    }


def _production(reference: str) -> dict:
    return {
        "mode": "stock",
        "reference_kind": "supplier_sku",
        "reference": reference,
    }


def _necklace_spec(*, complete: bool = True) -> dict:
    spec = deepcopy(NECKLACE_SPEC)
    if complete:
        spec["chain"].update({
            "geometry": _open_link_geometry(),
            "production": _production("SOURCE-CABLE-2MM"),
            "pendant_connection": "slides_through_bail",
        })
    return spec


def _create_necklace_project(client: TestClient, *, complete: bool = True) -> dict:
    return _create_project(client, _necklace_spec(complete=complete))


def _request(**overrides) -> dict:
    body = {
        "component_path": "metal.color",
        "option_id": "rose",
        "expected_design_version": 1,
        "created_by": "usr_catalog",
        "variant": 0,
    }
    body.update(overrides)
    return body


def _studio_job(
    client: TestClient,
    project: dict,
    *,
    action_id: str = "refine",
) -> dict:
    definitions = {
        "refine": ("trusted_structural", 20),
        "views": ("fast_visual", 15),
    }
    lane, credits = definitions[action_id]
    queued = client.post("/studio/jobs", json={
        "owner": "usr_catalog",
        "action_id": action_id,
        "lane": lane,
        "active_design_id": project["root_id"],
        "source_revision_id": project["active_asset_id"],
        "requested_outputs": 1,
        "credits_per_output": credits,
    })
    assert queued.status_code == 201, queued.text
    job = queued.json()
    running = client.patch(f"/studio/jobs/{job['job_id']}", json={
        "owner": "usr_catalog", "status": "running", "progress": 0.05,
    })
    assert running.status_code == 200, running.text
    return running.json()


def _chain_request(**overrides) -> dict:
    body = {
        "component_path": "chain.style",
        "option_id": "curb",
        "expected_design_version": 1,
        "created_by": "usr_catalog",
        "variant": 0,
        "chain_geometry": _open_link_geometry(width=2.2),
        "chain_production": _production("TARGET-CURB-2.2MM"),
    }
    body.update(overrides)
    return body


def _counts(SessionFactory: sessionmaker) -> dict[str, int]:
    with SessionFactory() as db:
        return {
            "versions": db.scalar(
                select(func.count()).select_from(DesignVersion)),
            "assets": db.scalar(select(func.count()).select_from(ImageAsset)),
            "runs": db.scalar(select(func.count()).select_from(ImageRun)),
        }


class _ResultAgent:
    def __init__(self, verdict: QualityVerdict) -> None:
        self.verdict = verdict
        self.plans = []
        self.masks: list[bytes | None] = []

    def run(self, plan, *, source_image=None, mask_bytes=None):
        self.plans.append(plan)
        self.masks.append(mask_bytes)

        class Provider:
            def execute(self, *_args, **_kwargs):
                return ProviderImage(image_bytes=_png((220, 170, 175)))

        verdict = self.verdict

        class Evaluator:
            def evaluate(self, *_args, **_kwargs):
                if verdict is QualityVerdict.PASS:
                    return ImageQualityReport(
                        verdict=verdict,
                        checks=(QualityCheck(
                            code="catalog_component_conformance",
                            passed=True,
                            severity=CheckSeverity.HARD,
                            message="selected catalog geometry is isolated",
                        ),),
                        score=97,
                    )
                return ImageQualityReport(
                    verdict=verdict,
                    checks=(QualityCheck(
                        code="metal_identity_visual_ambiguity",
                        passed=False,
                        severity=CheckSeverity.WARNING,
                        message="designer should confirm the rose-metal read",
                    ),),
                    score=86,
                )

        return JewelryImageAgent(Provider(), Evaluator()).run(
            plan,
            source_image=source_image,
            mask_bytes=mask_bytes,
        )


@pytest.mark.parametrize("route", ("catalog/preview", "catalog/apply"))
def test_ring_catalog_rejects_unmapped_source_before_provider_or_persistence(
    catalog_client, example_spec, monkeypatch, route,
):
    client, SessionFactory = catalog_client
    project = _create_project(
        client, example_spec, map_revision=False)
    agent_factory_calls = []

    def agent_factory():
        agent_factory_calls.append(True)
        return _ResultAgent(QualityVerdict.PASS)

    monkeypatch.setattr(
        "facetta.api.catalog._trusted_image_agent", agent_factory)
    response = client.post(
        f"/assets/{project['active_asset_id']}/{route}",
        json=_request(),
    )

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "component_map_not_found"
    assert response.json()["source_asset_id"] == project["active_asset_id"]
    assert agent_factory_calls == []
    with SessionFactory() as db:
        assert db.scalar(select(func.count()).select_from(ImageRun)) == 0
        assert db.scalar(
            select(func.count()).select_from(PreviewCandidateRecord)) == 0
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 1
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 1


def test_ring_catalog_rejects_unresolved_target_member_before_provider(
    catalog_client, example_spec, monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_project(
        client,
        example_spec,
        SessionFactory,
        unresolved_kind="gallery",
    )
    agent_factory_calls = []
    monkeypatch.setattr(
        "facetta.api.catalog._trusted_image_agent",
        lambda: agent_factory_calls.append(True),
    )

    response = client.post(
        f"/assets/{project['active_asset_id']}/catalog/preview",
        json=_request(),
    )

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "target_component_unresolved"
    assert response.json()["required_component_kinds"] == [
        "prongs", "setting", "shank", "shoulders", "gallery", "metal_zone",
    ]
    assert agent_factory_calls == []
    with SessionFactory() as db:
        assert db.scalar(select(func.count()).select_from(ImageRun)) == 0
        assert db.scalar(
            select(func.count()).select_from(PreviewCandidateRecord)) == 0
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 1
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 1


def test_catalog_pass_preview_is_temporary_until_explicit_apply(
    catalog_client, example_spec, monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    agent = _ResultAgent(QualityVerdict.PASS)
    monkeypatch.setattr(
        "facetta.api.catalog._trusted_image_agent", lambda: agent)

    preview = client.post(
        f"/assets/{project['active_asset_id']}/catalog/preview",
        json=_request(),
    )

    assert preview.status_code == 201, preview.text
    body = preview.json()
    assert body["status"] == "preview_ready"
    assert body["candidate"]["verdict"] == "pass"
    assert body["design_version"] == 1
    assert body["next_spec"]["metal"]["color"] == "rose"
    assert body["project"]["active_asset_id"] == project["active_asset_id"]
    assert _counts(SessionFactory) == {"versions": 1, "assets": 1, "runs": 1}
    with SessionFactory() as db:
        component_map = load_revision_component_map(
            db, project["active_asset_id"])
        assert component_map is not None
        expected_ids = (
            "prongs", "setting", "shank", "shoulders", "gallery", "metal",
        )
        expected_mask = rasterize_component_masks(
            component_map, expected_ids)
        expected_map_hash = component_map_hash(component_map)
    assert agent.masks == [expected_mask]
    plan = agent.plans[0]
    assert plan.mask_hash == hashlib.sha256(expected_mask).hexdigest()
    assert plan.normalized_intent["localization"] == {
        "mode": "revision_component_map",
        "mask_hash": plan.mask_hash,
        "evidence": {
            "schema_version": "facetta.revision-component-map.v1",
            "source_asset_id": project["active_asset_id"],
            "component_map_sha256": expected_map_hash,
            "target_component_ids": list(expected_ids),
            "target_component_kinds": [
                "prongs", "setting", "shank", "shoulders", "gallery",
                "metal_zone",
            ],
            "mask_sha256": plan.mask_hash,
            "authority": "exact_source_revision_image_editing_only",
        },
    }
    assert client.get(body["candidate"]["preview_url"]).status_code == 200
    reopened = client.get(
        f"/assets/{project['active_asset_id']}/catalog/previews")
    assert reopened.status_code == 200, reopened.text
    assert [item["candidate_id"] for item in reopened.json()["candidates"]] == [
        body["candidate"]["candidate_id"]
    ]
    assert reopened.json()["candidates"][0]["next_spec"]["metal"][
        "color"
    ] == "rose"

    accepted = client.post(body["candidate"]["accept_url"], json={
        "expected_design_version": 1,
        "created_by": "usr_catalog",
    })

    assert accepted.status_code == 201, accepted.text
    accepted_body = accepted.json()
    assert accepted_body["status"] == "accepted"
    assert accepted_body["design_version"] == 2
    assert accepted_body["project"]["spec"]["metal"]["color"] == "rose"
    assert len(agent.plans) == 1, "Apply must not rerun the image provider"
    assert _counts(SessionFactory) == {"versions": 2, "assets": 2, "runs": 1}
    with SessionFactory() as db:
        run = db.get(ImageRun, body["image_run_id"])
        review = db.scalar(select(ImageRunReview).where(
            ImageRunReview.run_id == run.id))
        assert run.status == "preview_ready"
        assert run.accepted_asset_id is None
        assert review is not None
        assert review.accepted_asset_id == accepted_body["asset_id"]
        durable = db.get(
            PreviewCandidateRecord, body["candidate"]["candidate_id"])
        assert durable is not None
        assert durable.status == "applied"
        assert durable.terminal_asset_id == accepted_body["asset_id"]
        assert durable.review_id == review.id
        assert bytes(durable.image) == b""
        assert run.mask_hash == plan.mask_hash
        assert durable.payload["component_map_sha256"] == expected_map_hash
        assert durable.payload["target_component_ids"] == list(expected_ids)
        assert durable.payload["target_mask_sha256"] == plan.mask_hash


def test_catalog_warning_preview_can_be_applied_without_regeneration(
    catalog_client, example_spec, monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    agent = _ResultAgent(QualityVerdict.WARN)
    monkeypatch.setattr(
        "facetta.api.catalog._trusted_image_agent", lambda: agent)

    preview = client.post(
        f"/assets/{project['active_asset_id']}/catalog/preview",
        json=_request(),
    )
    assert preview.status_code == 202, preview.text
    body = preview.json()
    assert body["status"] == "review_required"
    assert body["candidate"]["verdict"] == "warn"
    assert _counts(SessionFactory) == {"versions": 1, "assets": 1, "runs": 1}

    accepted = client.post(body["candidate"]["accept_url"], json={
        "expected_design_version": 1,
        "created_by": "usr_catalog",
    })
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["project"]["spec"]["metal"]["color"] == "rose"
    assert len(agent.plans) == 1
    assert _counts(SessionFactory) == {"versions": 2, "assets": 2, "runs": 1}


def test_catalog_preview_reopen_fails_closed_when_mask_lineage_is_tampered(
    catalog_client, example_spec, monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    agent = _ResultAgent(QualityVerdict.PASS)
    monkeypatch.setattr(
        "facetta.api.catalog._trusted_image_agent", lambda: agent)
    preview = client.post(
        f"/assets/{project['active_asset_id']}/catalog/preview",
        json=_request(),
    ).json()
    candidate_id = preview["candidate"]["candidate_id"]
    with SessionFactory() as db:
        record = db.get(PreviewCandidateRecord, candidate_id)
        assert record is not None
        record.payload = {
            **record.payload,
            "target_mask_sha256": "0" * 64,
        }
        db.commit()

    reopened = client.get(preview["candidate"]["preview_url"])
    accepted = client.post(preview["candidate"]["accept_url"], json={
        "expected_design_version": 1,
        "created_by": "usr_catalog",
    })

    assert reopened.status_code == 410
    assert reopened.json()["code"] == "catalog_preview_unavailable"
    assert accepted.status_code == 410
    assert len(agent.plans) == 1, "lineage rejection must never regenerate"
    assert _counts(SessionFactory) == {"versions": 1, "assets": 1, "runs": 1}


def test_catalog_preview_saves_exact_spec_directly_as_variation(
    catalog_client, example_spec, monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    monkeypatch.setattr(
        "facetta.api.catalog._trusted_image_agent",
        lambda: _ResultAgent(QualityVerdict.PASS),
    )
    preview = client.post(
        f"/assets/{project['active_asset_id']}/catalog/preview",
        json=_request(),
    ).json()
    saved = client.post(
        f"/image-runs/{preview['image_run_id']}/catalog-candidates/"
        f"{preview['candidate']['candidate_id']}/save-as-variation",
        json={"created_by": "usr_catalog", "label": "Rose direction"},
    )
    assert saved.status_code == 201, saved.text
    body = saved.json()
    assert body["status"] == "saved_as_variation"
    assert body["design_version"] == 1
    assert body["project"]["spec"]["metal"]["color"] == "rose"
    sibling_id = body["project"]["root_id"]
    with SessionFactory() as db:
        original = db.get(Project, project["root_id"])
        sibling = db.get(Project, sibling_id)
        asset = db.get(ImageAsset, sibling_id)
        durable = db.get(
            PreviewCandidateRecord, preview["candidate"]["candidate_id"])
        review = db.scalar(select(ImageRunReview).where(
            ImageRunReview.run_id == preview["image_run_id"]
        ))
        assert original is not None and sibling is not None and asset is not None
        assert project["active_asset_id"] == original.root_id
        assert sibling.family_id == original.family_id
        assert sibling.variation_label == "Rose direction"
        assert asset.design_id == body["design_id"]
        assert asset.design_version == 1
        assert durable is not None
        assert durable.status == "saved_as_variation"
        assert durable.terminal_asset_id == sibling_id
        assert review is not None and review.accepted_asset_id == sibling_id


def test_catalog_apply_resolution_failure_rolls_back_asset_spec_and_review(
    catalog_client, example_spec, monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    monkeypatch.setattr(
        "facetta.api.catalog._trusted_image_agent",
        lambda: _ResultAgent(QualityVerdict.PASS),
    )
    preview = client.post(
        f"/assets/{project['active_asset_id']}/catalog/preview",
        json=_request(),
    ).json()
    monkeypatch.setattr(
        "facetta.api.catalog.resolve_catalog_preview_candidate",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("resolution failed")
        ),
    )
    with pytest.raises(RuntimeError, match="resolution failed"):
        client.post(preview["candidate"]["accept_url"], json={
            "expected_design_version": 1,
            "created_by": "usr_catalog",
        })
    with SessionFactory() as db:
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 1
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 1
        assert db.scalar(select(func.count()).select_from(ImageRunReview)) == 0
        durable = db.get(
            PreviewCandidateRecord, preview["candidate"]["candidate_id"])
        assert durable is not None and durable.status == "reviewing"


def test_catalog_preview_accept_rejects_stale_exact_source_without_rerun(
    catalog_client, example_spec, monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    agent = _ResultAgent(QualityVerdict.PASS)
    monkeypatch.setattr(
        "facetta.api.catalog._trusted_image_agent", lambda: agent)
    preview = client.post(
        f"/assets/{project['active_asset_id']}/catalog/preview",
        json=_request(),
    ).json()

    newer = client.post(
        f"/assets/{project['active_asset_id']}/catalog/apply",
        json=_request(option_id="white"),
    )
    assert newer.status_code == 201, newer.text
    assert _counts(SessionFactory) == {"versions": 2, "assets": 2, "runs": 2}

    stale = client.post(preview["candidate"]["accept_url"], json={
        "expected_design_version": 1,
        "created_by": "usr_catalog",
    })
    assert stale.status_code == 410, stale.text
    assert stale.json()["code"] == "catalog_preview_unavailable"
    assert len(agent.plans) == 2
    assert _counts(SessionFactory) == {"versions": 2, "assets": 2, "runs": 2}


def test_catalog_preview_discard_removes_only_temporary_bytes(
    catalog_client, example_spec, monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    agent = _ResultAgent(QualityVerdict.PASS)
    monkeypatch.setattr(
        "facetta.api.catalog._trusted_image_agent", lambda: agent)
    body = client.post(
        f"/assets/{project['active_asset_id']}/catalog/preview",
        json=_request(),
    ).json()

    discarded = client.delete(body["candidate"]["discard_url"])
    assert discarded.status_code == 204
    assert client.get(body["candidate"]["preview_url"]).status_code == 410
    unavailable = client.post(body["candidate"]["accept_url"], json={
        "expected_design_version": 1,
        "created_by": "usr_catalog",
    })
    assert unavailable.status_code == 410
    assert unavailable.json()["code"] == "catalog_preview_unavailable"
    assert _counts(SessionFactory) == {"versions": 1, "assets": 1, "runs": 1}
    with SessionFactory() as db:
        durable = db.get(
            PreviewCandidateRecord, body["candidate"]["candidate_id"])
        assert durable is not None
        assert durable.status == "discarded"
        assert durable.decided_by == "usr_catalog"
        assert durable.terminal_asset_id is None
        assert bytes(durable.image) == b""


def test_catalog_preview_expiry_keeps_evidence_but_no_product_candidate(
    catalog_client, example_spec, monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    agent = _ResultAgent(QualityVerdict.PASS)
    monkeypatch.setattr(
        "facetta.api.catalog._trusted_image_agent", lambda: agent)
    monkeypatch.setattr(
        "facetta.catalog_preview_candidates._TTL_SECONDS", -1)

    body = client.post(
        f"/assets/{project['active_asset_id']}/catalog/preview",
        json=_request(),
    ).json()

    expired = client.get(body["candidate"]["preview_url"])
    assert expired.status_code == 410
    assert expired.json()["code"] == "catalog_preview_unavailable"
    assert _counts(SessionFactory) == {"versions": 1, "assets": 1, "runs": 1}
    with SessionFactory() as db:
        durable = db.get(
            PreviewCandidateRecord, body["candidate"]["candidate_id"])
        assert durable is not None
        assert durable.status == "expired"
        assert durable.resolved_at is not None
        assert bytes(durable.image) == b""


def test_catalog_preview_rejects_non_refine_job_before_provider_or_evidence(
    catalog_client, example_spec, monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    wrong_job = _studio_job(client, project, action_id="views")
    provider_calls: list[bool] = []
    monkeypatch.setattr(
        "facetta.api.catalog._trusted_image_agent",
        lambda: provider_calls.append(True),
    )

    response = client.post(
        f"/assets/{project['active_asset_id']}/catalog/preview",
        json=_request(studio_job_id=wrong_job["job_id"]),
    )

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "catalog_preview_job_invalid"
    assert provider_calls == []
    with SessionFactory() as db:
        assert db.scalar(select(func.count()).select_from(ImageRun)) == 0
        assert db.scalar(
            select(func.count()).select_from(PreviewCandidateRecord)) == 0
        job = db.get(StudioJobRecord, wrong_job["job_id"])
        assert job is not None and job.status == "running"
        assert job.completed_outputs == 0 and job.charged_outputs == 0


@pytest.mark.parametrize("decision", ("apply", "variation"))
def test_catalog_preview_acceptance_atomically_settles_one_refine_output(
    catalog_client, example_spec, monkeypatch, decision,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    job = _studio_job(client, project)
    monkeypatch.setattr(
        "facetta.api.catalog._trusted_image_agent",
        lambda: _ResultAgent(QualityVerdict.PASS),
    )
    preview_response = client.post(
        f"/assets/{project['active_asset_id']}/catalog/preview",
        json=_request(studio_job_id=job["job_id"]),
    )
    assert preview_response.status_code == 201, preview_response.text
    preview = preview_response.json()
    assert preview["candidate"]["studio_job_id"] == job["job_id"]
    reopened = client.get(
        f"/assets/{project['active_asset_id']}/catalog/previews")
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["candidates"][0]["studio_job_id"] == job["job_id"]
    with SessionFactory() as db:
        durable = db.get(
            PreviewCandidateRecord, preview["candidate"]["candidate_id"])
        current_job = db.get(StudioJobRecord, job["job_id"])
        assert durable is not None and durable.studio_job_id == job["job_id"]
        assert current_job is not None and current_job.status == "reviewing"
        assert current_job.completed_outputs == current_job.charged_outputs == 0

    if decision == "apply":
        terminal = client.post(preview["candidate"]["accept_url"], json={
            "expected_design_version": 1, "created_by": "usr_catalog",
        })
    else:
        terminal = client.post(
            preview["candidate"]["save_as_variation_url"],
            json={"created_by": "usr_catalog", "label": "Rose job direction"},
        )
    assert terminal.status_code == 201, terminal.text
    with SessionFactory() as db:
        current_job = db.get(StudioJobRecord, job["job_id"])
        assert current_job is not None and current_job.status == "succeeded"
        assert current_job.completed_outputs == 1
        assert current_job.charged_outputs == 1
        assert current_job.credits_per_output == 20

    # A replay cannot create another revision, variation, or hidden charge.
    if decision == "apply":
        repeated = client.post(preview["candidate"]["accept_url"], json={
            "expected_design_version": 1, "created_by": "usr_catalog",
        })
    else:
        repeated = client.post(
            preview["candidate"]["save_as_variation_url"],
            json={"created_by": "usr_catalog", "label": "Duplicate"},
        )
    assert repeated.status_code == 410
    with SessionFactory() as db:
        current_job = db.get(StudioJobRecord, job["job_id"])
        assert current_job is not None
        assert current_job.completed_outputs == current_job.charged_outputs == 1


@pytest.mark.parametrize("decision", ("discard", "expire"))
def test_catalog_preview_zero_output_decisions_cancel_without_charge(
    catalog_client, example_spec, monkeypatch, decision,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    job = _studio_job(client, project)
    monkeypatch.setattr(
        "facetta.api.catalog._trusted_image_agent",
        lambda: _ResultAgent(QualityVerdict.PASS),
    )
    if decision == "expire":
        monkeypatch.setattr(
            "facetta.catalog_preview_candidates._TTL_SECONDS", -1)
    preview = client.post(
        f"/assets/{project['active_asset_id']}/catalog/preview",
        json=_request(studio_job_id=job["job_id"]),
    ).json()

    terminal = (
        client.delete(preview["candidate"]["discard_url"])
        if decision == "discard"
        else client.get(preview["candidate"]["preview_url"])
    )
    assert terminal.status_code == (204 if decision == "discard" else 410)
    with SessionFactory() as db:
        current_job = db.get(StudioJobRecord, job["job_id"])
        durable = db.get(
            PreviewCandidateRecord, preview["candidate"]["candidate_id"])
        assert current_job is not None and current_job.status == "canceled"
        assert current_job.completed_outputs == current_job.charged_outputs == 0
        assert durable is not None
        assert durable.status == ("discarded" if decision == "discard" else "expired")



def test_catalog_preview_hard_failure_has_evidence_and_no_candidate(
    catalog_client, example_spec, monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    calls = []

    class FailingAgent:
        def run(self, plan, **_kwargs):
            calls.append(plan)
            report = ImageQualityReport(
                verdict=QualityVerdict.FAIL,
                checks=(QualityCheck(
                    code="outside_mask_drift",
                    passed=False,
                    severity=CheckSeverity.HARD,
                    message="protected jewelry changed outside the target",
                ),),
                score=20,
            )
            raise ImageQualityFailure(
                "no candidate passed jewelry QA: outside_mask_drift",
                report=report,
                plan=plan,
            )

    monkeypatch.setattr(
        "facetta.api.catalog._trusted_image_agent", lambda: FailingAgent())
    failed = client.post(
        f"/assets/{project['active_asset_id']}/catalog/preview",
        json=_request(),
    )

    assert failed.status_code == 422, failed.text
    body = failed.json()
    assert body["code"] == "image_quality_failed"
    assert "candidate" not in body
    assert len(calls) == 1
    assert _counts(SessionFactory) == {"versions": 1, "assets": 1, "runs": 1}
    with SessionFactory() as db:
        run = db.get(ImageRun, body["image_run_id"])
        assert run.status == "failed"
        assert run.accepted_asset_id is None


def test_catalog_preview_accept_database_failure_rolls_back_atomic_pair(
    catalog_client, example_spec, monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    agent = _ResultAgent(QualityVerdict.PASS)
    monkeypatch.setattr(
        "facetta.api.catalog._trusted_image_agent", lambda: agent)
    body = client.post(
        f"/assets/{project['active_asset_id']}/catalog/preview",
        json=_request(),
    ).json()
    baseline = _counts(SessionFactory)

    def fail_commit(_session: Session) -> None:
        raise RuntimeError("simulated preview acceptance transaction failure")

    monkeypatch.setattr(SessionFactory.class_, "commit", fail_commit)
    with pytest.raises(
        RuntimeError,
        match="simulated preview acceptance transaction failure",
    ):
        client.post(body["candidate"]["accept_url"], json={
            "expected_design_version": 1,
            "created_by": "usr_catalog",
        })
    assert _counts(SessionFactory) == baseline


def test_catalog_pass_uses_exact_specs_and_persists_one_atomic_revision(
    catalog_client, example_spec, monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    agent = _ResultAgent(QualityVerdict.PASS)
    monkeypatch.setattr(
        "facetta.api.catalog._trusted_image_agent", lambda: agent)

    response = client.post(
        f"/assets/{project['active_asset_id']}/catalog/apply",
        json=_request(),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "accepted"
    assert body["design_version"] == 2
    assert body["spec_change"] == [{
        "path": "metal.color",
        "before": "yellow",
        "after": "rose",
        "label": "gold color",
    }]
    assert body["project"]["active_asset_id"] == body["asset_id"]
    assert body["project"]["active_design_version"] == 2
    assert body["project"]["spec"]["metal"]["color"] == "rose"

    assert len(agent.plans) == 1
    plan = agent.plans[0]
    assert plan.source_spec_facts["metal"]["color"] == "yellow"
    assert plan.spec_facts["metal"]["color"] == "rose"
    assert plan.region_description.startswith("all visible metal surfaces")
    assert "metal.material" in plan.frozen
    assert "uniform color" in plan.intent
    rose = next(option for option in get_component_catalog("metal.color")
                if option.id == "rose")
    assert plan.style_constraints == rose.visual_geometry
    assert plan.normalized_intent["spec_delta"][0]["path"] == "metal.color"

    assert _counts(SessionFactory) == {"versions": 2, "assets": 2, "runs": 1}
    with SessionFactory() as db:
        run = db.get(ImageRun, body["image_run_id"])
        child = db.get(ImageAsset, body["asset_id"])
        version = db.get(DesignVersion, (project["design_id"], 2))
        assert run is not None and run.accepted_asset_id == child.id
        assert run.source_asset_id == project["active_asset_id"]
        assert child.parent_asset_id == project["active_asset_id"]
        assert child.design_version == 2
        assert version.spec["metal"]["color"] == "rose"


def test_catalog_center_stone_color_persists_one_paired_species_revision(
    catalog_client, halo_spec, monkeypatch,
):
    """A quick color choice is one image/spec revision, never two writes.

    The UI sends the selected palette species explicitly.  That permits a
    designer to go from a diamond to Royal Blue sapphire with one action while
    preventing an unscoped color string from being promoted as a fact.
    """
    client, SessionFactory = catalog_client
    project = _create_project(client, halo_spec, SessionFactory)
    agent = _ResultAgent(QualityVerdict.PASS)
    monkeypatch.setattr(
        "facetta.api.catalog._trusted_image_agent", lambda: agent)

    response = client.post(
        f"/assets/{project['active_asset_id']}/catalog/apply",
        json=_request(
            component_path="stone.color",
            option_id="Royal Blue",
            stone_species="sapphire",
        ),
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "accepted"
    assert body["design_version"] == 2
    assert [change["path"] for change in body["spec_change"]] == [
        "stone.species",
        "stone.color",
        "stone.carat",
        "stone.clarity",
    ]
    assert body["project"]["spec"]["stone"]["species"] == "sapphire"
    assert body["project"]["spec"]["stone"]["color"]["trade"] == "Royal Blue"
    assert body["project"]["spec"]["stone"]["clarity"] is None

    assert len(agent.plans) == 1
    plan = agent.plans[0]
    assert plan.source_spec_facts["stone"]["species"] == "diamond"
    assert plan.spec_facts["stone"]["species"] == "sapphire"
    assert "center-stone" in plan.region_description
    assert "stone.dimensions_mm" in plan.frozen

    assert _counts(SessionFactory) == {"versions": 2, "assets": 2, "runs": 1}
    with SessionFactory() as db:
        source = db.get(DesignVersion, (project["design_id"], 1))
        version = db.get(DesignVersion, (project["design_id"], 2))
        assert source.spec["stone"]["species"] == "diamond"
        assert version.spec["stone"]["species"] == "sapphire"
        assert version.spec["stone"]["color"]["trade"] == "Royal Blue"


@pytest.mark.parametrize(
    ("payload", "status", "code"),
    [
        (_request(expected_design_version=2), 409, "stale_design_version"),
        (_request(option_id="ultraviolet"), 422, "catalog_selection_invalid"),
        (_request(option_id="yellow"), 422, "catalog_selection_no_change"),
        (
            _request(component_path="chain.style", option_id="curb"),
            422,
            "catalog_not_applicable",
        ),
    ],
)
def test_stale_unsafe_and_inapplicable_selections_never_call_provider_or_write(
    catalog_client, example_spec, monkeypatch, payload, status, code,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    agent = _ResultAgent(QualityVerdict.PASS)
    monkeypatch.setattr(
        "facetta.api.catalog._trusted_image_agent", lambda: agent)

    response = client.post(
        f"/assets/{project['active_asset_id']}/catalog/apply",
        json=payload,
    )
    assert response.status_code == status, response.text
    assert response.json()["code"] == code
    assert agent.plans == []
    assert _counts(SessionFactory) == {"versions": 1, "assets": 1, "runs": 0}


def test_catalog_warning_keeps_next_spec_temporary_until_explicit_review(
    catalog_client, example_spec, monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    agent = _ResultAgent(QualityVerdict.WARN)
    monkeypatch.setattr(
        "facetta.api.catalog._trusted_image_agent", lambda: agent)

    warned = client.post(
        f"/assets/{project['active_asset_id']}/catalog/apply",
        json=_request(),
    )
    assert warned.status_code == 202, warned.text
    body = warned.json()
    assert body["status"] == "review_required"
    assert "asset_id" not in body
    assert body["design_version"] == 1
    assert body["next_spec"]["metal"]["color"] == "rose"
    assert body["project"]["active_asset_id"] == project["active_asset_id"]
    assert body["project"]["active_design_version"] == 1
    assert _counts(SessionFactory) == {"versions": 1, "assets": 1, "runs": 1}

    candidate = body["warning_candidate"]
    assert client.get(candidate["preview_url"]).status_code == 200
    accepted = client.post(
        f"/image-runs/{candidate['run_id']}/candidates/"
        f"{candidate['candidate_id']}/accept",
        json={
            "expected_design_version": 1,
            "created_by": "usr_catalog",
        },
    )
    assert accepted.status_code == 201, accepted.text
    accepted_project = accepted.json()
    assert accepted_project["active_design_version"] == 2
    assert accepted_project["spec"]["metal"]["color"] == "rose"
    assert _counts(SessionFactory) == {"versions": 2, "assets": 2, "runs": 1}


def test_catalog_quality_failure_writes_evidence_only(
    catalog_client, example_spec, monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    calls = []

    class FailingAgent:
        def run(self, plan, **_kwargs):
            calls.append(plan)
            report = ImageQualityReport(
                verdict=QualityVerdict.FAIL,
                checks=(QualityCheck(
                    code="metal_geometry_drift",
                    passed=False,
                    severity=CheckSeverity.HARD,
                    message="the candidate changed ring geometry",
                ),),
                score=35,
            )
            raise ImageQualityFailure(
                "no candidate passed jewelry QA: metal_geometry_drift",
                report=report,
                plan=plan,
            )

    monkeypatch.setattr(
        "facetta.api.catalog._trusted_image_agent", lambda: FailingAgent())
    response = client.post(
        f"/assets/{project['active_asset_id']}/catalog/apply",
        json=_request(),
    )
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "image_quality_failed"
    assert len(calls) == 1
    assert _counts(SessionFactory) == {"versions": 1, "assets": 1, "runs": 1}
    with SessionFactory() as db:
        run = db.get(ImageRun, response.json()["image_run_id"])
        assert run.status == "failed"
        assert run.accepted_asset_id is None


def test_catalog_database_failure_rolls_back_image_spec_and_run_together(
    catalog_client, example_spec, monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    agent = _ResultAgent(QualityVerdict.PASS)
    monkeypatch.setattr(
        "facetta.api.catalog._trusted_image_agent", lambda: agent)
    baseline = _counts(SessionFactory)

    def fail_commit(_session: Session) -> None:
        raise RuntimeError("simulated catalog transaction failure")

    monkeypatch.setattr(SessionFactory.class_, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="simulated catalog transaction failure"):
        client.post(
            f"/assets/{project['active_asset_id']}/catalog/apply",
            json=_request(),
        )
    assert _counts(SessionFactory) == baseline


def test_old_primary_asset_is_rejected_before_provider(
    catalog_client, example_spec, monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    first_agent = _ResultAgent(QualityVerdict.PASS)
    monkeypatch.setattr(
        "facetta.api.catalog._trusted_image_agent", lambda: first_agent)
    accepted = client.post(
        f"/assets/{project['active_asset_id']}/catalog/apply",
        json=_request(),
    )
    assert accepted.status_code == 201

    second_agent = _ResultAgent(QualityVerdict.PASS)
    monkeypatch.setattr(
        "facetta.api.catalog._trusted_image_agent", lambda: second_agent)
    stale = client.post(
        f"/assets/{project['active_asset_id']}/catalog/apply",
        json=_request(option_id="white", expected_design_version=2),
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "stale_asset_revision"
    assert second_agent.plans == []
    assert _counts(SessionFactory) == {"versions": 2, "assets": 2, "runs": 1}


def test_catalog_selection_preserves_every_non_catalog_spec_fact(
    catalog_client, example_spec, monkeypatch,
):
    client, SessionFactory = catalog_client
    source = deepcopy(example_spec)
    project = _create_project(client, source, SessionFactory)
    agent = _ResultAgent(QualityVerdict.PASS)
    monkeypatch.setattr(
        "facetta.api.catalog._trusted_image_agent", lambda: agent)

    response = client.post(
        f"/assets/{project['active_asset_id']}/catalog/apply",
        json=_request(),
    )
    assert response.status_code == 201
    with SessionFactory() as db:
        stored = db.get(DesignVersion, (project["design_id"], 2)).spec
        before = db.get(DesignVersion, (project["design_id"], 1)).spec
        before = deepcopy(before)
        before["metal"]["color"] = "rose"
        for field in ("design_id", "version", "created_by", "created_at"):
            before.pop(field, None)
            stored.pop(field, None)
        assert stored == before
        assert db.get(Project, project["root_id"]) is not None


def test_confirmed_necklace_import_and_chain_catalog_pass_are_one_exact_pair(
    catalog_client, monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_necklace_project(client)
    assert project["spec"]["jewelry_type"] == "necklace"
    assert project["factory_blockers"] == []
    source_asset_id = project["active_asset_id"]
    agent = _ResultAgent(QualityVerdict.PASS)
    monkeypatch.setattr(
        "facetta.api.catalog._trusted_image_agent", lambda: agent)

    response = client.post(
        f"/assets/{source_asset_id}/catalog/apply",
        json=_chain_request(),
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "accepted"
    assert body["component_path"] == "chain.style"
    assert body["design_version"] == 2
    assert body["project"]["active_asset_id"] == body["asset_id"]
    target_chain = body["project"]["spec"]["chain"]
    assert target_chain["style"] == "curb"
    assert target_chain["geometry"] == _open_link_geometry(width=2.2)
    assert target_chain["production"] == _production("TARGET-CURB-2.2MM")
    assert target_chain["pendant_connection"] == "slides_through_bail"
    paths = {change["path"] for change in body["spec_change"]}
    assert {
        "chain.style",
        "chain.geometry.chain_width_mm",
        "chain.geometry.profile_thickness_mm",
        "chain.production.reference",
    } <= paths

    assert len(agent.plans) == 1
    plan = agent.plans[0]
    assert plan.jewelry_type == "necklace"
    assert plan.edit_domains == (DesignerEditDomain.CHAIN_STYLE,)
    assert plan.spec_facts["chain"]["style"] == "curb"
    assert plan.spec_facts["chain"]["geometry"] == _open_link_geometry(width=2.2)
    assert "production" not in plan.spec_facts["chain"]
    assert "production" not in plan.source_spec_facts["chain"]
    visual_paths = {
        change["path"] for change in plan.normalized_intent["spec_delta"]
    }
    assert "chain.style" in visual_paths
    assert any(path.startswith("chain.geometry") for path in visual_paths)
    assert not any(path.startswith("chain.production") for path in visual_paths)
    assert "chain.length_mm" in plan.frozen
    assert "chain.clasp" in plan.frozen
    assert "pendant" in plan.frozen

    assert _counts(SessionFactory) == {"versions": 2, "assets": 2, "runs": 1}
    with SessionFactory() as db:
        source_version = db.get(DesignVersion, (project["design_id"], 1))
        target_version = db.get(DesignVersion, (project["design_id"], 2))
        child = db.get(ImageAsset, body["asset_id"])
        run = db.get(ImageRun, body["image_run_id"])
        assert source_version.spec["chain"]["style"] == "cable"
        assert source_version.spec["chain"]["production"]["reference"] == (
            "SOURCE-CABLE-2MM")
        assert target_version.spec["chain"] == target_chain
        provenance = target_version.spec["dimension_provenance"]
        geometry_paths = {
            path for path in provenance if path.startswith("chain.geometry.")
        }
        assert {
            "chain.geometry.chain_width_mm",
            "chain.geometry.profile_thickness_mm",
            "chain.geometry.links[0].inside_length_mm",
            "chain.geometry.links[0].inside_width_mm",
        } <= geometry_paths
        assert all(
            provenance[path]["status"] == "designer_confirmed"
            and provenance[path]["method"] == "designer_input"
            and "usr_catalog" in provenance[path]["source"]
            for path in geometry_paths
        )
        assert child.parent_asset_id == source_asset_id
        assert child.design_version == 2
        assert run.source_asset_id == source_asset_id
        assert run.accepted_asset_id == child.id


@pytest.mark.parametrize(
    ("payload_factory", "complete_source", "code"),
    [
        (
            lambda: {
                key: value for key, value in _chain_request().items()
                if key not in {"chain_geometry", "chain_production"}
            },
            True,
            "chain_target_data_required",
        ),
        (
            lambda: _chain_request(
                option_id="rope",
                chain_production=_production("TARGET-ROPE-2.2MM"),
            ),
            True,
            "chain_target_incompatible",
        ),
        (
            lambda: _chain_request(
                chain_geometry=_open_link_geometry(),
                chain_production=_production("SOURCE-CABLE-2MM"),
            ),
            True,
            "chain_target_production_reused",
        ),
        (
            lambda: _chain_request(expected_design_version=2),
            True,
            "stale_design_version",
        ),
        (
            _chain_request,
            False,
            "chain_connection_required",
        ),
    ],
)
def test_chain_catalog_preflight_failures_never_call_provider_or_write(
    catalog_client,
    monkeypatch,
    payload_factory,
    complete_source,
    code,
):
    client, SessionFactory = catalog_client
    project = _create_necklace_project(client, complete=complete_source)
    agent = _ResultAgent(QualityVerdict.PASS)
    monkeypatch.setattr(
        "facetta.api.catalog._trusted_image_agent", lambda: agent)

    response = client.post(
        f"/assets/{project['active_asset_id']}/catalog/apply",
        json=payload_factory(),
    )

    assert response.status_code in {409, 422}, response.text
    assert response.json()["code"] == code
    assert agent.plans == []
    assert _counts(SessionFactory) == {"versions": 1, "assets": 1, "runs": 0}


def test_chain_catalog_warning_stays_temporary_then_accepts_exact_target(
    catalog_client,
    monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_necklace_project(client)
    agent = _ResultAgent(QualityVerdict.WARN)
    monkeypatch.setattr(
        "facetta.api.catalog._trusted_image_agent", lambda: agent)

    warned = client.post(
        f"/assets/{project['active_asset_id']}/catalog/apply",
        json=_chain_request(),
    )

    assert warned.status_code == 202, warned.text
    body = warned.json()
    assert body["status"] == "review_required"
    assert "asset_id" not in body
    assert body["design_version"] == 1
    assert body["next_spec"]["chain"]["style"] == "curb"
    assert body["next_spec"]["chain"]["geometry"] == (
        _open_link_geometry(width=2.2))
    assert body["next_spec"]["chain"]["production"] == (
        _production("TARGET-CURB-2.2MM"))
    warned_provenance = body["next_spec"]["dimension_provenance"]
    assert warned_provenance[
        "chain.geometry.chain_width_mm"]["status"] == "designer_confirmed"
    assert body["project"]["active_asset_id"] == project["active_asset_id"]
    assert body["project"]["active_design_version"] == 1
    assert _counts(SessionFactory) == {"versions": 1, "assets": 1, "runs": 1}

    candidate = body["warning_candidate"]
    accepted = client.post(
        f"/image-runs/{candidate['run_id']}/candidates/"
        f"{candidate['candidate_id']}/accept",
        json={
            "expected_design_version": 1,
            "created_by": "usr_catalog",
        },
    )
    assert accepted.status_code == 201, accepted.text
    accepted_project = accepted.json()
    assert accepted_project["active_design_version"] == 2
    assert accepted_project["spec"]["chain"] == body["next_spec"]["chain"]
    assert accepted_project["spec"]["dimension_provenance"] == (
        warned_provenance)
    assert accepted_project["active_asset_id"] != project["active_asset_id"]
    assert _counts(SessionFactory) == {"versions": 2, "assets": 2, "runs": 1}


def test_from_image_necklace_must_remain_the_supported_confirmed_template(
    catalog_client,
):
    client, _ = catalog_client
    invalid = _necklace_spec()
    invalid["template"] = "solitaire_prong"

    response = client.post("/projects/from-image", json={
        "image_base64": base64.b64encode(_png()).decode(),
        "media_type": "image/png",
        "spec": invalid,
        "owner": "usr_catalog",
        "title": "Invalid necklace",
    })

    assert response.status_code == 422
    assert "cluster_pendant" in response.json()["detail"]

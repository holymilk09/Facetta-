"""Persisted catalog selections use one deterministic spec/image transaction."""

from __future__ import annotations

import base64
import hashlib
import io
from copy import deepcopy
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, func, select, update
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from conftest import NECKLACE_SPEC, audited_import_spec
from facetta.db import (
    Base,
    DesignVersion,
    ImageAsset,
    ImageAttempt,
    ImageRun,
    ImageRunReview,
    PreviewCandidateRecord,
    Project,
    ProjectRevisionRecord,
    RevisionComponentMapRecord,
    StudioJobRecord,
    StudioMarkupCandidateRecord,
    get_db,
    new_id,
    utcnow,
)
from facetta.api.catalog import StudioComponentTargetingResponse
from facetta.design_form import NormalizedPoint, NormalizedPolygon
from facetta.catalog_preview_candidates import (
    CatalogPreviewJobError,
    CatalogPreviewUnavailable,
    clear_catalog_preview_candidates_for_tests,
    list_catalog_preview_candidates,
    lock_catalog_preview_candidate_for_decision,
)
from facetta import catalog_component_targeting
from facetta.component_catalog import get_component_catalog
from facetta.image_agent import (
    CheckSeverity,
    DesignerEditDomain,
    ImageQualityFailure,
    ImageQualityReport,
    ImageProviderFailure,
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


def _textured_rgba_png() -> bytes:
    image = Image.new("RGBA", (40, 40))
    pixels = []
    for y in range(40):
        for x in range(40):
            value = 80 + ((x * 7 + y * 11) % 150)
            pixels.append((
                min(255, value + 18),
                value,
                max(0, value - 22),
                80 + ((x * 13 + y * 17) % 176),
            ))
    image.putdata(pixels)
    out = io.BytesIO()
    image.save(out, format="PNG")
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
    catalog_component_targeting.configure_catalog_structural_component_mapper(None)
    app.dependency_overrides[get_db] = override
    try:
        yield TestClient(app), TestSession
    finally:
        app.dependency_overrides.clear()
        catalog_component_targeting.configure_catalog_structural_component_mapper(None)
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
        polygons = (
            NormalizedPolygon(
                points=(
                    NormalizedPoint(x=0.1 + offset, y=0.1 + offset),
                    NormalizedPoint(x=0.45 + offset, y=0.1 + offset),
                    NormalizedPoint(x=0.45 + offset, y=0.45 + offset),
                    NormalizedPoint(x=0.1 + offset, y=0.45 + offset),
                )
            ),
        )
        resolved = kind != unresolved_kind
        components.append(
            RevisionComponent(
                component_id=component_id,
                kind=kind,
                label=component_id.title(),
                resolution="resolved" if resolved else "unresolved",
                polygons=polygons if resolved else (),
                polygon_sha256=polygon_hash(polygons) if resolved else None,
            )
        )
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
            _component_map(asset.id, image, unresolved_kind=unresolved_kind),
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
    image: bytes | None = None,
) -> dict:
    response = client.post(
        "/projects/from-image",
        json={
            "image_base64": base64.b64encode(image or _png()).decode(),
            "media_type": "image/png",
            "spec": audited_import_spec(example_spec),
            "owner": "usr_catalog",
            "title": "Catalog ring",
        },
    )
    assert response.status_code == 201, response.text
    project = response.json()
    if example_spec["jewelry_type"] == "ring" and map_revision:
        assert SessionFactory is not None
        _map_project(SessionFactory, project, unresolved_kind=unresolved_kind)
    return project


def _targeting(client: TestClient, asset_id: str) -> StudioComponentTargetingResponse:
    response = client.get(f"/assets/{asset_id}/studio-component-targeting")
    assert response.status_code == 200, response.text
    return StudioComponentTargetingResponse.model_validate(response.json())


def test_studio_component_targeting_reports_mapped_ring_truthfully(
    catalog_client,
    example_spec,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)

    capability = _targeting(client, project["active_asset_id"])

    assert capability.component_map.state == "ready"
    assert capability.component_map.scope == "ring_v1"
    assert capability.component_map.map_sha256 is not None
    paths = {item.component_path: item for item in capability.catalog_paths}
    assert paths["metal.color"].status == "ready"
    assert paths["stone.color"].status == "ready"
    # Source geometry is mapped, but accepting a structural child cannot
    # preserve target continuity until a calibrated child mapper is installed.
    assert paths["stone.cut"].status == "unresolved"
    assert paths["stone.cut"].reason_code == ("structural_child_mapping_unavailable")
    assert paths["setting.style"].status == "unresolved"


def test_studio_component_targeting_reports_unmapped_ring(
    catalog_client,
    example_spec,
):
    client, _ = catalog_client
    project = _create_project(client, example_spec, map_revision=False)

    capability = _targeting(client, project["active_asset_id"])

    assert capability.component_map.state == "unmapped"
    assert capability.component_map.scope == "ring_v1"
    assert {item.status for item in capability.catalog_paths} == {"unmapped"}
    assert {item.reason_code for item in capability.catalog_paths} == {
        "component_map_not_found"
    }


def test_studio_component_targeting_reports_path_level_unresolved_ring(
    catalog_client,
    example_spec,
):
    client, SessionFactory = catalog_client
    project = _create_project(
        client,
        example_spec,
        SessionFactory,
        unresolved_kind="metal_zone",
    )

    capability = _targeting(client, project["active_asset_id"])

    assert capability.component_map.state == "unresolved"
    paths = {item.component_path: item for item in capability.catalog_paths}
    assert paths["metal.color"].status == "unresolved"
    assert paths["metal.color"].reason_code == "target_component_unresolved"
    assert paths["stone.color"].status == "ready"
    assert paths["stone.cut"].status == "unresolved"
    assert paths["stone.cut"].reason_code == ("structural_child_mapping_unavailable")


def test_studio_component_targeting_reports_non_ring_scope(
    catalog_client,
):
    client, _ = catalog_client
    project = _create_necklace_project(client)

    capability = _targeting(client, project["active_asset_id"])

    assert capability.jewelry_type == "necklace"
    assert capability.component_map.state == "unmapped"
    assert capability.component_map.scope == "not_released"
    assert [
        (item.component_path, item.status, item.reason_code)
        for item in capability.catalog_paths
    ] == [
        (
            "chain.style",
            "unmapped",
            "component_mapping_not_released_for_category",
        )
    ]


def test_structural_catalog_preview_rejects_before_provider_without_child_mapper(
    catalog_client,
    example_spec,
    monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    provider_calls: list[bool] = []
    monkeypatch.setattr(
        "facetta.api.catalog._trusted_image_agent",
        lambda: provider_calls.append(True),
    )

    response = client.post(
        f"/assets/{project['active_asset_id']}/catalog/preview",
        json=_request(component_path="setting.style", option_id="6_prong_basket"),
    )

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "component_mapping_unresolved"
    assert provider_calls == []
    assert _counts(SessionFactory) == {"versions": 1, "assets": 1, "runs": 0}


def test_structural_mapper_activation_requires_attested_calibration_and_health():
    def mapper(**_kwargs):
        return None

    with pytest.raises(ValueError, match="mapper_contract"):
        catalog_component_targeting.configure_catalog_structural_component_mapper(
            mapper,
            calibration_evidence_sha256="a" * 64,
            supported_paths={"setting.style"},
            readiness_probe=lambda: True,
        )
    with pytest.raises(ValueError, match="calibration_evidence_sha256"):
        catalog_component_targeting.configure_catalog_structural_component_mapper(
            mapper,
            mapper_contract="mapper.v1",
            calibration_evidence_sha256="not-a-digest",
            supported_paths={"setting.style"},
            readiness_probe=lambda: True,
        )
    with pytest.raises(ValueError, match="supported_paths"):
        catalog_component_targeting.configure_catalog_structural_component_mapper(
            mapper,
            mapper_contract="mapper.v1",
            calibration_evidence_sha256="a" * 64,
            supported_paths={"metal.color"},
            readiness_probe=lambda: True,
        )
    with pytest.raises(ValueError, match="readiness_probe"):
        catalog_component_targeting.configure_catalog_structural_component_mapper(
            mapper,
            mapper_contract="mapper.v1",
            calibration_evidence_sha256="a" * 64,
            supported_paths={"setting.style"},
        )

    status = catalog_component_targeting.catalog_structural_component_mapper_status()
    assert status.state == "unconfigured"
    assert not catalog_component_targeting.catalog_structural_component_mapper_available(
        "setting.style"
    )


def test_structural_mapper_readiness_is_path_specific_and_operationally_visible(
    catalog_client,
    example_spec,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    catalog_component_targeting.configure_catalog_structural_component_mapper(
        lambda **_kwargs: None,
        mapper_contract="approved.stone-cut-mapper.v3",
        calibration_evidence_sha256="c" * 64,
        supported_paths={"stone.cut"},
        readiness_probe=lambda: True,
    )

    capability = _targeting(client, project["active_asset_id"])
    paths = {item.component_path: item for item in capability.catalog_paths}
    assert paths["stone.cut"].status == "ready"
    assert paths["setting.style"].status == "unresolved"
    assert paths["setting.style"].reason_code == (
        "structural_child_mapping_unavailable"
    )
    health = client.get("/health").json()["capabilities"][
        "structural_component_mapping"
    ]
    assert health == {
        "state": "ready",
        "mapper_contract": "approved.stone-cut-mapper.v3",
        "calibration_evidence_sha256": "c" * 64,
        "supported_paths": ["stone.cut"],
        "reason_code": None,
    }


def test_attested_source_mapper_prepares_exact_revision_targeting_idempotently(
    catalog_client,
    example_spec,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    source_mapper_calls: list[str] = []

    class SourceMapper:
        def __call__(self, **_kwargs):
            raise AssertionError("source preparation must not run the child mapper")

        def map_source(self, *, asset_id, image):
            source_mapper_calls.append(asset_id)
            return _component_map(asset_id, image)

    with SessionFactory() as db:
        db.execute(RevisionComponentMapRecord.__table__.delete())
        db.commit()
    catalog_component_targeting.configure_catalog_structural_component_mapper(
        SourceMapper(),
        mapper_contract="test.catalog-map.v1",
        calibration_evidence_sha256="f" * 64,
        supported_paths={"stone.cut"},
        readiness_probe=lambda: True,
    )

    prepared = client.post(
        f"/assets/{project['active_asset_id']}/studio-component-map"
    )
    replay = client.post(
        f"/assets/{project['active_asset_id']}/studio-component-map"
    )

    assert prepared.status_code == 200, prepared.text
    assert replay.status_code == 200, replay.text
    assert source_mapper_calls == [project["active_asset_id"]]
    body = prepared.json()
    assert body["authority"] == "exact_revision_image_editing_only"
    assert body["component_map"]["state"] == "ready"
    paths = {item["component_path"]: item for item in body["catalog_paths"]}
    assert paths["stone.cut"]["status"] == "ready"
    assert paths["stone.cut"]["required_component_kinds"] == [
        "center_stone",
        "prongs",
        "setting",
    ]
    assert paths["setting.style"]["status"] == "unresolved"
    with SessionFactory() as db:
        stored = load_revision_component_map(db, project["active_asset_id"])
        assert stored is not None
        assert stored.calibration_evidence_sha256 == "f" * 64
        assert db.scalar(
            select(func.count()).select_from(RevisionComponentMapRecord)
        ) == 1


def test_unhealthy_structural_mapper_never_advertises_targetability(
    catalog_client,
    example_spec,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    catalog_component_targeting.configure_catalog_structural_component_mapper(
        lambda **_kwargs: None,
        mapper_contract="approved.mapper.v1",
        calibration_evidence_sha256="d" * 64,
        supported_paths={"stone.cut", "setting.style"},
        readiness_probe=lambda: False,
    )

    capability = _targeting(client, project["active_asset_id"])
    paths = {item.component_path: item for item in capability.catalog_paths}
    assert paths["stone.cut"].status == "unresolved"
    assert paths["setting.style"].status == "unresolved"
    health = client.get("/health").json()["capabilities"][
        "structural_component_mapping"
    ]
    assert health["state"] == "unhealthy"
    assert health["reason_code"] == "structural_child_mapper_unhealthy"


def test_calibrated_structural_mapper_reconciles_and_persists_child_map(
    catalog_client,
    example_spec,
    monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    mapper_calls: list[str] = []

    def mapper(
        *,
        parent_map,
        child_asset_id,
        child_image,
        **_kwargs,
    ):
        mapper_calls.append(child_asset_id)
        components = tuple(
            component.model_copy(
                update={
                    "parent_component_id": component.component_id,
                }
            )
            for component in parent_map.components
        )
        return RevisionComponentMap(
            asset_id=child_asset_id,
            asset_sha256=hashlib.sha256(child_image).hexdigest(),
            raster_width=parent_map.raster_width,
            raster_height=parent_map.raster_height,
            jewelry_type="ring",
            mapper_contract="test.calibrated-child-map.v1",
            components=components,
        )

    catalog_component_targeting.configure_catalog_structural_component_mapper(
        mapper,
        mapper_contract="test.calibrated-child-map.v1",
        calibration_evidence_sha256="a" * 64,
        supported_paths={"setting.style"},
        readiness_probe=lambda: True,
    )
    monkeypatch.setattr(
        "facetta.api.catalog._trusted_image_agent",
        lambda: _ResultAgent(QualityVerdict.PASS),
    )
    capability = _targeting(client, project["active_asset_id"])
    paths = {item.component_path: item for item in capability.catalog_paths}
    assert paths["setting.style"].status == "ready"
    preview = client.post(
        f"/assets/{project['active_asset_id']}/catalog/preview",
        json=_request(component_path="setting.style", option_id="6_prong_basket"),
    )
    assert preview.status_code == 201, preview.text
    assert len(mapper_calls) == 1
    with SessionFactory() as db:
        candidate = db.get(
            PreviewCandidateRecord,
            preview.json()["candidate"]["candidate_id"],
        )
        assert candidate is not None
        proposed = RevisionComponentMap.model_validate(
            candidate.payload["proposed_child_component_map"]
        )
        assert proposed.asset_id == candidate.id
        assert proposed.calibration_evidence_sha256 == "a" * 64

    accepted = client.post(
        preview.json()["candidate"]["accept_url"],
        json={
            "expected_design_version": 1,
            "created_by": "usr_catalog",
        },
    )

    assert accepted.status_code == 201, accepted.text
    assert len(mapper_calls) == 1, "Apply must not rerun structural mapping"
    with SessionFactory() as db:
        child_map = load_revision_component_map(db, accepted.json()["asset_id"])
        assert child_map is not None
        assert child_map.mapper_contract == "test.calibrated-child-map.v1"
        assert child_map.calibration_evidence_sha256 == "a" * 64
        assert all(
            component.parent_component_id == component.component_id
            for component in child_map.components
        )


def test_structural_mapper_output_contract_mismatch_fails_during_preview(
    catalog_client,
    example_spec,
    monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    job = _studio_job(client, project)

    def mapper(*, parent_map, child_asset_id, child_image, **_kwargs):
        return RevisionComponentMap(
            asset_id=child_asset_id,
            asset_sha256=hashlib.sha256(child_image).hexdigest(),
            raster_width=parent_map.raster_width,
            raster_height=parent_map.raster_height,
            jewelry_type="ring",
            mapper_contract="different.unapproved-contract.v1",
            components=tuple(
                component.model_copy(
                    update={"parent_component_id": component.component_id}
                )
                for component in parent_map.components
            ),
        )

    catalog_component_targeting.configure_catalog_structural_component_mapper(
        mapper,
        mapper_contract="approved.mapper-contract.v1",
        calibration_evidence_sha256="e" * 64,
        supported_paths={"setting.style"},
        readiness_probe=lambda: True,
    )
    monkeypatch.setattr(
        "facetta.api.catalog._trusted_image_agent",
        lambda: _ResultAgent(QualityVerdict.PASS),
    )
    preview = client.post(
        f"/assets/{project['active_asset_id']}/catalog/preview",
        json=_request(
            component_path="setting.style",
            option_id="6_prong_basket",
            studio_job_id=job["job_id"],
        ),
    )
    assert preview.status_code == 409, preview.text
    assert preview.json()["code"] == "component_mapping_unresolved"
    assert _counts(SessionFactory) == {"versions": 1, "assets": 1, "runs": 1}
    with SessionFactory() as db:
        assert db.scalar(
            select(func.count()).select_from(PreviewCandidateRecord)
        ) == 0
        run = db.get(ImageRun, preview.json()["image_run_id"])
        current_job = db.get(StudioJobRecord, job["job_id"])
        assert run is not None and run.status == "failed"
        assert current_job is not None and current_job.status == "failed"
        assert current_job.completed_outputs == current_job.charged_outputs == 0
        assert current_job.error_code == "component_mapping_unresolved"


def test_structural_warning_never_creates_accept_capability_or_charges_job(
    catalog_client,
    example_spec,
    monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    job = _studio_job(client, project)

    def mapper(**_kwargs):
        raise AssertionError("warning structural output must not reach child mapping")

    catalog_component_targeting.configure_catalog_structural_component_mapper(
        mapper,
        mapper_contract="test.warning-gate.v1",
        calibration_evidence_sha256="f" * 64,
        supported_paths={"setting.style"},
        readiness_probe=lambda: True,
    )
    monkeypatch.setattr(
        "facetta.api.catalog._trusted_image_agent",
        lambda: _ResultAgent(QualityVerdict.WARN),
    )

    preview = client.post(
        f"/assets/{project['active_asset_id']}/catalog/preview",
        json=_request(
            component_path="setting.style",
            option_id="6_prong_basket",
            studio_job_id=job["job_id"],
        ),
    )

    assert preview.status_code == 422, preview.text
    body = preview.json()
    assert body["code"] == "catalog_structural_qa_unresolved"
    assert "candidate" not in body
    with SessionFactory() as db:
        run = db.get(ImageRun, body["image_run_id"])
        current_job = db.get(StudioJobRecord, job["job_id"])
        assert run is not None and run.status == "failed"
        assert run.accepted_asset_id is None
        assert db.scalar(
            select(func.count()).select_from(PreviewCandidateRecord)
        ) == 0
        assert current_job is not None and current_job.status == "failed"
        assert current_job.completed_outputs == current_job.charged_outputs == 0
        assert current_job.error_code == "catalog_structural_qa_unresolved"


@pytest.mark.parametrize("decision", ("apply", "variation"))
def test_structural_decision_fails_atomically_if_child_mapper_becomes_unavailable(
    catalog_client,
    example_spec,
    monkeypatch,
    decision,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    def mapper(*, parent_map, child_asset_id, child_image, **_kwargs):
        return RevisionComponentMap(
            asset_id=child_asset_id,
            asset_sha256=hashlib.sha256(child_image).hexdigest(),
            raster_width=parent_map.raster_width,
            raster_height=parent_map.raster_height,
            jewelry_type="ring",
            mapper_contract="test.unavailable-after-preview.v1",
            components=tuple(
                component.model_copy(
                    update={"parent_component_id": component.component_id}
                )
                for component in parent_map.components
            ),
        )

    catalog_component_targeting.configure_catalog_structural_component_mapper(
        mapper,
        mapper_contract="test.unavailable-after-preview.v1",
        calibration_evidence_sha256="b" * 64,
        supported_paths={"setting.style"},
        readiness_probe=lambda: True,
    )
    monkeypatch.setattr(
        "facetta.api.catalog._trusted_image_agent",
        lambda: _ResultAgent(QualityVerdict.PASS),
    )
    preview = client.post(
        f"/assets/{project['active_asset_id']}/catalog/preview",
        json=_request(component_path="setting.style", option_id="6_prong_basket"),
    )
    assert preview.status_code == 201, preview.text
    body = preview.json()
    catalog_component_targeting.configure_catalog_structural_component_mapper(None)

    if decision == "apply":
        terminal = client.post(
            body["candidate"]["accept_url"],
            json={
                "expected_design_version": 1,
                "created_by": "usr_catalog",
            },
        )
    else:
        terminal = client.post(
            body["candidate"]["save_as_variation_url"],
            json={"created_by": "usr_catalog", "label": "Oval direction"},
        )

    assert terminal.status_code == 410, terminal.text
    assert terminal.json()["code"] in {
        "catalog_preview_unavailable",
        "preview_candidate_unavailable",
    }
    assert _counts(SessionFactory) == {"versions": 1, "assets": 1, "runs": 1}
    with SessionFactory() as db:
        durable = db.get(PreviewCandidateRecord, body["candidate"]["candidate_id"])
        assert durable is not None and durable.status == "expired"
        assert bytes(durable.image) == b""
        assert db.scalar(select(func.count()).select_from(ImageRunReview)) == 0


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
        "links": [
            {
                "role": "standard",
                "length_mm": inside_length + 2 * thickness,
                "inside_length_mm": inside_length,
                "inside_width_mm": inside_width,
            }
        ],
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
        spec["chain"].update(
            {
                "geometry": _open_link_geometry(),
                "production": _production("SOURCE-CABLE-2MM"),
                "pendant_connection": "slides_through_bail",
            }
        )
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


def test_instant_gold_color_preview_is_exact_masked_and_zero_provider(
    catalog_client,
    example_spec,
    monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_project(
        client, example_spec, SessionFactory, image=_textured_rgba_png()
    )
    provider_calls: list[bool] = []
    monkeypatch.setattr(
        "facetta.api.catalog._trusted_image_agent",
        lambda: provider_calls.append(True),
    )

    response = client.post(
        f"/assets/{project['active_asset_id']}/catalog/preview",
        json=_request(execution_mode="instant"),
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "preview_ready"
    assert body["candidate"]["studio_job_id"] is None
    assert body["routing"]["execution_mode"] == "instant_masked_transform"
    assert body["routing"]["provider_calls"] == 0
    assert body["routing"]["attempt_count"] == 0
    assert provider_calls == []
    preview_response = client.get(body["candidate"]["preview_url"])
    assert preview_response.status_code == 200, preview_response.text

    with SessionFactory() as db:
        source = db.get(ImageAsset, project["active_asset_id"])
        component_map = load_revision_component_map(db, project["active_asset_id"])
        run = db.get(ImageRun, body["image_run_id"])
        candidate = db.get(
            PreviewCandidateRecord, body["candidate"]["candidate_id"]
        )
        assert source is not None and component_map is not None
        assert run is not None and candidate is not None
        mask_bytes = rasterize_component_masks(
            component_map,
            ("prongs", "setting", "shank", "shoulders", "gallery", "metal"),
        )
        assert db.scalar(select(func.count()).select_from(ImageAttempt)) == 0
        assert db.scalar(select(func.count()).select_from(StudioJobRecord)) == 0
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 1
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 1
        source_bytes = bytes(source.image)
        assert run.prompt_version == "facetta.instant-gold-color.v1"
        assert run.normalized_intent["execution_mode"] == (
            "instant_masked_transform"
        )
        assert run.normalized_intent["source_sha256"] == hashlib.sha256(
            source_bytes
        ).hexdigest()
        assert run.normalized_intent["mask_sha256"] == hashlib.sha256(
            mask_bytes
        ).hexdigest()
        assert candidate.payload["transform_contract_sha256"] == (
            run.normalized_intent["transform_contract_sha256"]
        )
        assert candidate.payload["routing"] == body["routing"]

    with Image.open(io.BytesIO(source_bytes)) as source_image:
        source_pixels = list(
            source_image.convert("RGBA").get_flattened_data()
        )
        source_size = source_image.size
    with Image.open(io.BytesIO(preview_response.content)) as preview_image:
        preview_pixels = list(
            preview_image.convert("RGBA").get_flattened_data()
        )
        assert preview_image.size == source_size
    with Image.open(io.BytesIO(mask_bytes)) as mask_image:
        mask_pixels = list(mask_image.convert("L").get_flattened_data())
    assert all(
        preview_pixels[index] == source_pixels[index]
        for index, coverage in enumerate(mask_pixels)
        if coverage == 0
    )
    assert all(
        preview[3] == source[3]
        for preview, source in zip(preview_pixels, source_pixels)
    )
    changed = [
        index
        for index, coverage in enumerate(mask_pixels)
        if coverage > 0 and preview_pixels[index] != source_pixels[index]
    ]
    assert changed
    for index in changed:
        source_luma = sum(
            channel * weight
            for channel, weight in zip(
                source_pixels[index][:3], (0.2126, 0.7152, 0.0722)
            )
        )
        preview_luma = sum(
            channel * weight
            for channel, weight in zip(
                preview_pixels[index][:3], (0.2126, 0.7152, 0.0722)
            )
        )
        assert abs(source_luma - preview_luma) <= 1.0


@pytest.mark.parametrize("decision", ("apply", "save", "discard"))
def test_instant_gold_color_preview_reuses_canonical_candidate_decisions(
    catalog_client,
    example_spec,
    monkeypatch,
    decision,
):
    client, SessionFactory = catalog_client
    project = _create_project(
        client, example_spec, SessionFactory, image=_textured_rgba_png()
    )
    monkeypatch.setattr(
        "facetta.api.catalog._trusted_image_agent",
        lambda: pytest.fail("instant preview must not construct a provider agent"),
    )
    response = client.post(
        f"/assets/{project['active_asset_id']}/catalog/preview",
        json=_request(execution_mode="instant"),
    )
    assert response.status_code == 201, response.text
    preview = response.json()

    if decision == "apply":
        decided = client.post(
            preview["candidate"]["accept_url"],
            json={"expected_design_version": 1, "created_by": "usr_catalog"},
        )
        assert decided.status_code == 201, decided.text
        terminal_asset_id = decided.json()["asset_id"]
        expected_status = "applied"
    elif decision == "save":
        decided = client.post(
            preview["candidate"]["save_as_variation_url"],
            json={"created_by": "usr_catalog", "label": "Rose instant"},
        )
        assert decided.status_code == 201, decided.text
        terminal_asset_id = decided.json()["project"]["root_id"]
        expected_status = "saved_as_variation"
    else:
        decided = client.delete(preview["candidate"]["discard_url"])
        assert decided.status_code == 204, decided.text
        terminal_asset_id = None
        expected_status = "discarded"

    with SessionFactory() as db:
        candidate = db.get(
            PreviewCandidateRecord, preview["candidate"]["candidate_id"]
        )
        assert candidate is not None and candidate.status == expected_status
        assert candidate.terminal_asset_id == terminal_asset_id
        assert db.scalar(select(func.count()).select_from(ImageAttempt)) == 0
        assert db.scalar(select(func.count()).select_from(StudioJobRecord)) == 0
        if decision == "discard":
            assert db.scalar(select(func.count()).select_from(ImageAsset)) == 1
            assert db.scalar(select(func.count()).select_from(DesignVersion)) == 1
        else:
            revision = db.scalar(select(ProjectRevisionRecord).where(
                ProjectRevisionRecord.asset_id == terminal_asset_id
            ))
            assert revision is not None
            assert revision.interpretation["transform_contract_sha256"] == (
                candidate.payload["transform_contract_sha256"]
            )


def test_instant_gold_color_preview_fails_closed_for_other_catalog_paths(
    catalog_client,
    example_spec,
    monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    provider_calls: list[bool] = []
    monkeypatch.setattr(
        "facetta.api.catalog._trusted_image_agent",
        lambda: provider_calls.append(True),
    )

    response = client.post(
        f"/assets/{project['active_asset_id']}/catalog/preview",
        json=_request(
            component_path="metal.material",
            option_id="platinum",
            execution_mode="instant",
        ),
    )

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "instant_preview_path_unsupported"
    assert provider_calls == []
    with SessionFactory() as db:
        assert db.scalar(select(func.count()).select_from(ImageRun)) == 0
        assert db.scalar(select(func.count()).select_from(PreviewCandidateRecord)) == 0
        assert db.scalar(select(func.count()).select_from(StudioJobRecord)) == 0


def test_instant_gold_color_preview_fails_closed_without_exact_map(
    catalog_client,
    example_spec,
    monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, map_revision=False)
    monkeypatch.setattr(
        "facetta.api.catalog._trusted_image_agent",
        lambda: pytest.fail("unmapped instant preview must not call a provider"),
    )

    response = client.post(
        f"/assets/{project['active_asset_id']}/catalog/preview",
        json=_request(execution_mode="instant"),
    )

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "component_map_not_found"
    with SessionFactory() as db:
        assert db.scalar(select(func.count()).select_from(ImageRun)) == 0
        assert db.scalar(select(func.count()).select_from(PreviewCandidateRecord)) == 0


@pytest.mark.parametrize(
    "corruption",
    (
        "routing_mode_removed",
        "run_input_hash",
        "intent_source_hash",
        "intent_mask_hash",
        "intent_output_hash",
        "transform_color",
        "payload_option",
        "prompt_version",
        "provider_attempt",
    ),
)
def test_instant_gold_color_preview_fails_closed_for_lineage_tampering(
    catalog_client,
    example_spec,
    corruption,
):
    client, SessionFactory = catalog_client
    project = _create_project(
        client, example_spec, SessionFactory, image=_textured_rgba_png()
    )
    response = client.post(
        f"/assets/{project['active_asset_id']}/catalog/preview",
        json=_request(execution_mode="instant"),
    )
    assert response.status_code == 201, response.text
    preview = response.json()

    with SessionFactory() as db:
        record = db.get(
            PreviewCandidateRecord, preview["candidate"]["candidate_id"]
        )
        run = db.get(ImageRun, preview["image_run_id"])
        assert record is not None and run is not None
        payload = dict(record.payload)
        routing = dict(payload["routing"])
        intent = dict(run.normalized_intent)
        contract = dict(intent["transform_contract"])
        run_updates = {}
        if corruption == "routing_mode_removed":
            routing.pop("execution_mode")
        elif corruption == "run_input_hash":
            run_updates["input_hash"] = "0" * 64
        elif corruption == "intent_source_hash":
            intent["source_sha256"] = "0" * 64
            run_updates["normalized_intent"] = intent
        elif corruption == "intent_mask_hash":
            intent["mask_sha256"] = "0" * 64
            run_updates["normalized_intent"] = intent
        elif corruption == "intent_output_hash":
            intent["output_sha256"] = "0" * 64
            run_updates["normalized_intent"] = intent
        elif corruption == "transform_color":
            contract["controlled_color"] = "white"
            intent["transform_contract"] = contract
            run_updates["normalized_intent"] = intent
        elif corruption == "payload_option":
            payload["option_id"] = "white"
        elif corruption == "prompt_version":
            run_updates["prompt_version"] = (
                "facetta.instant-gold-color.tampered"
            )
        elif corruption == "provider_attempt":
            db.add(ImageAttempt(
                id=new_id("att"),
                run_id=run.id,
                attempt_number=1,
                provider="tampered",
                model="tampered",
            ))
        payload["routing"] = routing
        record.payload = payload
        if run_updates:
            # These cases simulate database corruption outside the guarded ORM
            # path so the downstream lineage reader remains independently
            # fail-closed.
            db.execute(
                update(ImageRun)
                .where(ImageRun.id == run.id)
                .values(**run_updates)
            )
        db.commit()

    reopened = client.get(preview["candidate"]["preview_url"])
    assert reopened.status_code == 410, reopened.text
    assert reopened.json()["code"] == "catalog_preview_unavailable"
    with SessionFactory() as db:
        durable = db.get(
            PreviewCandidateRecord, preview["candidate"]["candidate_id"]
        )
        assert durable is not None and durable.status == "expired"
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 1
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 1
        assert db.scalar(select(func.count()).select_from(ImageRunReview)) == 0


def test_instant_gold_color_preview_rejects_job_without_settling_or_charging_it(
    catalog_client,
    example_spec,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    job = _studio_job(client, project)

    response = client.post(
        f"/assets/{project['active_asset_id']}/catalog/preview",
        json=_request(execution_mode="instant", studio_job_id=job["job_id"]),
    )

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "instant_preview_job_not_allowed"
    with SessionFactory() as db:
        durable_job = db.get(StudioJobRecord, job["job_id"])
        assert durable_job is not None and durable_job.status == "running"
        assert durable_job.progress == pytest.approx(0.05)
        assert durable_job.completed_outputs == durable_job.charged_outputs == 0
        assert durable_job.error_code is None
        assert db.scalar(select(func.count()).select_from(ImageRun)) == 0
        assert db.scalar(select(func.count()).select_from(ImageAttempt)) == 0
        assert db.scalar(select(func.count()).select_from(PreviewCandidateRecord)) == 0


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
    queued = client.post(
        "/studio/jobs",
        json={
            "owner": "usr_catalog",
            "action_id": action_id,
            "lane": lane,
            "active_design_id": project["root_id"],
            "source_revision_id": project["active_asset_id"],
            "requested_outputs": 1,
            "credits_per_output": credits,
        },
    )
    assert queued.status_code == 201, queued.text
    job = queued.json()
    running = client.patch(
        f"/studio/jobs/{job['job_id']}",
        json={
            "owner": "usr_catalog",
            "status": "running",
            "progress": 0.05,
        },
    )
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
            "versions": db.scalar(select(func.count()).select_from(DesignVersion)),
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
                        checks=(
                            QualityCheck(
                                code="catalog_component_conformance",
                                passed=True,
                                severity=CheckSeverity.HARD,
                                message="selected catalog geometry is isolated",
                            ),
                        ),
                        score=97,
                    )
                return ImageQualityReport(
                    verdict=verdict,
                    checks=(
                        QualityCheck(
                            code="metal_identity_visual_ambiguity",
                            passed=False,
                            severity=CheckSeverity.WARNING,
                            message="designer should confirm the rose-metal read",
                        ),
                    ),
                    score=86,
                )

        return JewelryImageAgent(Provider(), Evaluator()).run(
            plan,
            source_image=source_image,
            mask_bytes=mask_bytes,
        )


def test_normalized_catalog_preview_projects_and_applies_exact_revision(
    catalog_client,
    example_spec,
):
    client, SessionFactory = catalog_client
    project = _create_project(
        client,
        example_spec,
        SessionFactory,
        image=_textured_rgba_png(),
    )
    preview = client.post(
        f"/assets/{project['active_asset_id']}/catalog/preview",
        json=_request(execution_mode="instant"),
    )
    assert preview.status_code == 201, preview.text
    preview_payload = preview.json()
    candidate_id = preview_payload["candidate"]["candidate_id"]
    before_apply = _counts(SessionFactory)

    listed = client.get(
        f"/studio/projects/{project['root_id']}/preview-candidates"
    )
    assert listed.status_code == 200, listed.text
    normalized = listed.json()["candidates"]
    assert len(normalized) == 1
    assert normalized[0]["candidate_id"] == candidate_id
    assert normalized[0]["kind"] == "catalog_revision"
    assert normalized[0]["component_path"] == "metal.color"
    assert normalized[0]["option_id"] == "rose"
    assert normalized[0]["expected_design_version"] == 1
    assert normalized[0]["next_spec"] == preview_payload["next_spec"]
    image = client.get(normalized[0]["preview_url"])
    assert image.status_code == 200, image.text

    applied = client.post(
        f"/studio/preview-candidates/{candidate_id}/decision",
        json={
            "created_by": "usr_catalog",
            "decision": "apply",
            "expected_active_asset_id": project["active_asset_id"],
            "expected_design_version": 1,
        },
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["kind"] == "catalog_revision"
    assert applied.json()["status"] == "applied"
    assert applied.json()["terminal_asset_id"] is not None
    assert applied.json()["family_id"] is None
    assert applied.json()["variation_index"] is None
    assert _counts(SessionFactory) == {
        **before_apply,
        "versions": before_apply["versions"] + 1,
        "assets": before_apply["assets"] + 1,
    }


def test_normalized_catalog_preview_saves_exact_variation(
    catalog_client,
    example_spec,
):
    client, SessionFactory = catalog_client
    project = _create_project(
        client,
        example_spec,
        SessionFactory,
        image=_textured_rgba_png(),
    )
    preview = client.post(
        f"/assets/{project['active_asset_id']}/catalog/preview",
        json=_request(execution_mode="instant"),
    )
    assert preview.status_code == 201, preview.text
    preview_payload = preview.json()
    candidate_id = preview_payload["candidate"]["candidate_id"]

    saved = client.post(
        f"/studio/preview-candidates/{candidate_id}/decision",
        json={
            "created_by": "usr_catalog",
            "decision": "save_as_variation",
            "expected_active_asset_id": project["active_asset_id"],
            "expected_design_version": 1,
            "variation_label": "Rose catalog direction",
        },
    )
    assert saved.status_code == 200, saved.text
    result = saved.json()
    assert result["kind"] == "catalog_revision"
    assert result["status"] == "saved_as_variation"
    assert result["source_project_id"] == project["root_id"]
    assert result["result_project_id"] != project["root_id"]
    assert result["terminal_asset_id"] is not None
    assert result["family_id"] is not None
    assert result["variation_index"] == 2
    legacy_replay = client.post(
        preview_payload["candidate"]["save_as_variation_url"],
        json={
            "created_by": "usr_catalog",
            "label": "Rose catalog direction",
        },
    )
    assert legacy_replay.status_code == 201, legacy_replay.text
    assert legacy_replay.json()["project"]["root_id"] == (
        result["result_project_id"]
    )
    legacy_conflict = client.post(
        preview_payload["candidate"]["save_as_variation_url"],
        json={"created_by": "usr_catalog", "label": "Another direction"},
    )
    assert legacy_conflict.status_code == 409, legacy_conflict.text
    assert legacy_conflict.json()["code"] == (
        "preview_candidate_variation_conflict"
    )
    with SessionFactory() as db:
        durable = db.get(PreviewCandidateRecord, candidate_id)
        sibling = db.get(Project, result["result_project_id"])
        terminal = db.get(ImageAsset, result["terminal_asset_id"])
        assert durable is not None and durable.status == "saved_as_variation"
        assert durable.payload["resolved_variation_label"] == (
            "Rose catalog direction"
        )
        assert sibling is not None and sibling.root_id != project["root_id"]
        assert sibling.family_id == result["family_id"]
        assert sibling.variation_index == result["variation_index"]
        assert terminal is not None and terminal.root_id == sibling.root_id


def test_normalized_catalog_stale_discard_preserves_canonical_revision(
    catalog_client,
    example_spec,
    monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_project(
        client,
        example_spec,
        SessionFactory,
        image=_textured_rgba_png(),
    )
    preview = client.post(
        f"/assets/{project['active_asset_id']}/catalog/preview",
        json=_request(execution_mode="instant"),
    )
    assert preview.status_code == 201, preview.text
    candidate_id = preview.json()["candidate"]["candidate_id"]
    monkeypatch.setattr(
        "facetta.api.catalog._trusted_image_agent",
        lambda: _ResultAgent(QualityVerdict.PASS),
    )
    newer = client.post(
        f"/assets/{project['active_asset_id']}/catalog/apply",
        json=_request(option_id="white"),
    )
    assert newer.status_code == 201, newer.text
    before_discard = _counts(SessionFactory)

    discarded = client.post(
        f"/studio/preview-candidates/{candidate_id}/decision",
        json={
            "created_by": "usr_catalog",
            "decision": "discard",
            "expected_active_asset_id": project["active_asset_id"],
            "expected_design_version": 1,
        },
    )
    assert discarded.status_code == 200, discarded.text
    assert discarded.json()["status"] == "discarded"
    assert discarded.json()["family_id"] is None
    assert discarded.json()["variation_index"] is None
    assert _counts(SessionFactory) == before_discard
    with SessionFactory() as db:
        durable = db.get(PreviewCandidateRecord, candidate_id)
        active = db.get(ImageAsset, newer.json()["asset_id"])
        assert durable is not None and durable.status == "discarded"
        assert bytes(durable.image) == b""
        assert active is not None


def test_normalized_catalog_decision_is_owner_scoped_and_exact_cas(
    catalog_client,
    example_spec,
):
    client, SessionFactory = catalog_client
    project = _create_project(
        client,
        example_spec,
        SessionFactory,
        image=_textured_rgba_png(),
    )
    preview = client.post(
        f"/assets/{project['active_asset_id']}/catalog/preview",
        json=_request(execution_mode="instant"),
    )
    assert preview.status_code == 201, preview.text
    candidate_id = preview.json()["candidate"]["candidate_id"]
    before = _counts(SessionFactory)

    foreign = client.post(
        f"/studio/preview-candidates/{candidate_id}/decision",
        json={
            "created_by": "usr_someone_else",
            "decision": "apply",
            "expected_active_asset_id": project["active_asset_id"],
            "expected_design_version": 1,
        },
    )
    assert foreign.status_code == 404, foreign.text
    assert foreign.json()["code"] == "preview_candidate_unavailable"

    stale = client.post(
        f"/studio/preview-candidates/{candidate_id}/decision",
        json={
            "created_by": "usr_catalog",
            "decision": "apply",
            "expected_active_asset_id": project["active_asset_id"],
            "expected_design_version": 2,
        },
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["code"] == "preview_candidate_lineage_mismatch"
    assert _counts(SessionFactory) == before
    with SessionFactory() as db:
        durable = db.get(PreviewCandidateRecord, candidate_id)
        assert durable is not None and durable.status == "reviewing"
        assert durable.terminal_asset_id is None


def test_normalized_resolved_catalog_projection_fails_closed_on_invalid_spec(
    catalog_client,
    example_spec,
):
    client, SessionFactory = catalog_client
    project = _create_project(
        client,
        example_spec,
        SessionFactory,
        image=_textured_rgba_png(),
    )
    preview = client.post(
        f"/assets/{project['active_asset_id']}/catalog/preview",
        json=_request(execution_mode="instant"),
    )
    assert preview.status_code == 201, preview.text
    candidate_id = preview.json()["candidate"]["candidate_id"]
    discarded = client.post(
        f"/studio/preview-candidates/{candidate_id}/decision",
        json={
            "created_by": "usr_catalog",
            "decision": "discard",
            "expected_active_asset_id": project["active_asset_id"],
            "expected_design_version": 1,
        },
    )
    assert discarded.status_code == 200, discarded.text
    before = _counts(SessionFactory)
    with SessionFactory() as db:
        durable = db.get(PreviewCandidateRecord, candidate_id)
        assert durable is not None and durable.status == "discarded"
        durable.payload = {**durable.payload, "next_spec": "not-a-specification"}
        db.commit()

    detail = client.get(
        f"/studio/preview-candidates/{candidate_id}",
        params={"owner": "usr_catalog"},
    )
    assert detail.status_code == 422, detail.text
    assert detail.json()["code"] == "preview_candidate_payload_invalid"
    listed = client.get(
        f"/studio/projects/{project['root_id']}/preview-candidates",
        params={"include_resolved": True},
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["candidates"] == []
    assert _counts(SessionFactory) == before


@pytest.mark.parametrize("route", ("catalog/preview", "catalog/apply"))
def test_ring_catalog_rejects_unmapped_source_before_provider_or_persistence(
    catalog_client,
    example_spec,
    monkeypatch,
    route,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, map_revision=False)
    agent_factory_calls = []

    def agent_factory():
        agent_factory_calls.append(True)
        return _ResultAgent(QualityVerdict.PASS)

    monkeypatch.setattr("facetta.api.catalog._trusted_image_agent", agent_factory)
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
        assert db.scalar(select(func.count()).select_from(PreviewCandidateRecord)) == 0
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 1
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 1


def test_ring_catalog_rejects_unresolved_target_member_before_provider(
    catalog_client,
    example_spec,
    monkeypatch,
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
        "prongs",
        "setting",
        "shank",
        "shoulders",
        "gallery",
        "metal_zone",
    ]
    assert agent_factory_calls == []
    with SessionFactory() as db:
        assert db.scalar(select(func.count()).select_from(ImageRun)) == 0
        assert db.scalar(select(func.count()).select_from(PreviewCandidateRecord)) == 0
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 1
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 1


def test_catalog_pass_preview_is_temporary_until_explicit_apply(
    catalog_client,
    example_spec,
    monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    agent = _ResultAgent(QualityVerdict.PASS)
    monkeypatch.setattr("facetta.api.catalog._trusted_image_agent", lambda: agent)

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
        component_map = load_revision_component_map(db, project["active_asset_id"])
        assert component_map is not None
        expected_ids = (
            "prongs",
            "setting",
            "shank",
            "shoulders",
            "gallery",
            "metal",
        )
        expected_mask = rasterize_component_masks(component_map, expected_ids)
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
                "prongs",
                "setting",
                "shank",
                "shoulders",
                "gallery",
                "metal_zone",
            ],
            "mask_sha256": plan.mask_hash,
            "authority": "exact_source_revision_image_editing_only",
        },
    }
    assert client.get(body["candidate"]["preview_url"]).status_code == 200
    reopened = client.get(f"/assets/{project['active_asset_id']}/catalog/previews")
    assert reopened.status_code == 200, reopened.text
    assert [item["candidate_id"] for item in reopened.json()["candidates"]] == [
        body["candidate"]["candidate_id"]
    ]
    assert reopened.json()["candidates"][0]["next_spec"]["metal"]["color"] == "rose"

    accepted = client.post(
        body["candidate"]["accept_url"],
        json={
            "expected_design_version": 1,
            "created_by": "usr_catalog",
        },
    )

    assert accepted.status_code == 201, accepted.text
    accepted_body = accepted.json()
    assert accepted_body["status"] == "accepted"
    assert accepted_body["design_version"] == 2
    assert accepted_body["project"]["spec"]["metal"]["color"] == "rose"
    assert len(agent.plans) == 1, "Apply must not rerun the image provider"
    assert _counts(SessionFactory) == {"versions": 2, "assets": 2, "runs": 1}
    with SessionFactory() as db:
        run = db.get(ImageRun, body["image_run_id"])
        review = db.scalar(
            select(ImageRunReview).where(ImageRunReview.run_id == run.id)
        )
        revision = db.scalar(
            select(ProjectRevisionRecord).where(
                ProjectRevisionRecord.asset_id == accepted_body["asset_id"]
            )
        )
        assert run.status == "preview_ready"
        assert run.accepted_asset_id is None
        assert review is not None
        assert review.accepted_asset_id == accepted_body["asset_id"]
        assert revision is not None and revision.action == "edit"
        assert revision.raw_intent["component_path"] == "metal.color"
        assert revision.interpretation["source_sha256"] == plan.source_hash
        assert revision.interpretation["output_sha256"] == hashlib.sha256(
            _png((220, 170, 175))
        ).hexdigest()
        durable = db.get(PreviewCandidateRecord, body["candidate"]["candidate_id"])
        assert durable is not None
        assert durable.status == "applied"
        assert durable.terminal_asset_id == accepted_body["asset_id"]
        assert durable.review_id == review.id
        assert bytes(durable.image) == b""
        assert run.mask_hash == plan.mask_hash
        assert durable.payload["component_map_sha256"] == expected_map_hash
        assert durable.payload["target_component_ids"] == list(expected_ids)
        assert durable.payload["target_mask_sha256"] == plan.mask_hash
        child_map = load_revision_component_map(db, accepted_body["asset_id"])
        assert child_map is not None
        assert child_map.mapper_contract == "facetta.material-only-map-copy.v1"
        assert (
            child_map.asset_sha256
            == hashlib.sha256(
                bytes(db.get(ImageAsset, accepted_body["asset_id"]).image)
            ).hexdigest()
        )
        assert child_map.components == component_map.components


def test_catalog_warning_preview_can_be_applied_without_regeneration(
    catalog_client,
    example_spec,
    monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    agent = _ResultAgent(QualityVerdict.WARN)
    monkeypatch.setattr("facetta.api.catalog._trusted_image_agent", lambda: agent)

    preview = client.post(
        f"/assets/{project['active_asset_id']}/catalog/preview",
        json=_request(),
    )
    assert preview.status_code == 202, preview.text
    body = preview.json()
    assert body["status"] == "review_required"
    assert body["candidate"]["verdict"] == "warn"
    assert _counts(SessionFactory) == {"versions": 1, "assets": 1, "runs": 1}

    accepted = client.post(
        body["candidate"]["accept_url"],
        json={
            "expected_design_version": 1,
            "created_by": "usr_catalog",
        },
    )
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["project"]["spec"]["metal"]["color"] == "rose"
    assert len(agent.plans) == 1
    assert _counts(SessionFactory) == {"versions": 2, "assets": 2, "runs": 1}


def test_catalog_preview_reopen_fails_closed_when_mask_lineage_is_tampered(
    catalog_client,
    example_spec,
    monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    job = _studio_job(client, project)
    agent = _ResultAgent(QualityVerdict.PASS)
    monkeypatch.setattr("facetta.api.catalog._trusted_image_agent", lambda: agent)
    preview = client.post(
        f"/assets/{project['active_asset_id']}/catalog/preview",
        json=_request(studio_job_id=job["job_id"]),
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
    assert reopened.status_code == 410
    assert reopened.json()["code"] == "catalog_preview_unavailable"
    # A failed review read is itself terminal lifecycle evidence. The user
    # must not need to attempt Apply before Activity leaves `reviewing`.
    with SessionFactory() as db:
        durable = db.get(PreviewCandidateRecord, candidate_id)
        current_job = db.get(StudioJobRecord, job["job_id"])
        assert durable is not None and durable.status == "expired"
        assert durable.resolved_at is not None and bytes(durable.image) == b""
        assert current_job is not None and current_job.status == "failed"
        assert current_job.completed_outputs == current_job.charged_outputs == 0
        assert current_job.error_code == "catalog_preview_unavailable"

    accepted = client.post(
        preview["candidate"]["accept_url"],
        json={
            "expected_design_version": 1,
            "created_by": "usr_catalog",
        },
    )

    assert accepted.status_code == 410
    assert len(agent.plans) == 1, "lineage rejection must never regenerate"
    assert _counts(SessionFactory) == {"versions": 1, "assets": 1, "runs": 1}
    with SessionFactory() as db:
        durable = db.get(PreviewCandidateRecord, candidate_id)
        current_job = db.get(StudioJobRecord, job["job_id"])
        assert durable is not None and durable.status == "expired"
        assert durable.resolved_at is not None and bytes(durable.image) == b""
        assert current_job is not None and current_job.status == "failed"
        assert current_job.completed_outputs == current_job.charged_outputs == 0
        assert current_job.error_code == "catalog_preview_unavailable"


def test_catalog_preview_list_terminalizes_tampered_reviewing_job(
    catalog_client,
    example_spec,
    monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    job = _studio_job(client, project)
    monkeypatch.setattr(
        "facetta.api.catalog._trusted_image_agent",
        lambda: _ResultAgent(QualityVerdict.PASS),
    )
    preview = client.post(
        f"/assets/{project['active_asset_id']}/catalog/preview",
        json=_request(studio_job_id=job["job_id"]),
    ).json()
    candidate_id = preview["candidate"]["candidate_id"]
    with SessionFactory() as db:
        record = db.get(PreviewCandidateRecord, candidate_id)
        assert record is not None
        record.output_sha256 = "0" * 64
        db.commit()

    reopened = client.get(
        f"/assets/{project['active_asset_id']}/catalog/previews"
    )

    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["candidates"] == []
    with SessionFactory() as db:
        durable = db.get(PreviewCandidateRecord, candidate_id)
        current_job = db.get(StudioJobRecord, job["job_id"])
        assert durable is not None and durable.status == "expired"
        assert durable.resolved_at is not None and bytes(durable.image) == b""
        assert current_job is not None and current_job.status == "failed"
        assert current_job.completed_outputs == current_job.charged_outputs == 0
        assert current_job.error_code == "catalog_preview_unavailable"


def test_catalog_preview_tampered_variation_settles_reviewing_job_without_branch(
    catalog_client,
    example_spec,
    monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    job = _studio_job(client, project)
    monkeypatch.setattr(
        "facetta.api.catalog._trusted_image_agent",
        lambda: _ResultAgent(QualityVerdict.PASS),
    )
    preview = client.post(
        f"/assets/{project['active_asset_id']}/catalog/preview",
        json=_request(studio_job_id=job["job_id"]),
    ).json()
    candidate_id = preview["candidate"]["candidate_id"]
    with SessionFactory() as db:
        record = db.get(PreviewCandidateRecord, candidate_id)
        assert record is not None
        record.output_sha256 = "0" * 64
        db.commit()

    rejected = client.post(
        preview["candidate"]["save_as_variation_url"],
        json={"created_by": "usr_catalog", "label": "Tampered direction"},
    )

    assert rejected.status_code == 410, rejected.text
    assert rejected.json()["code"] == "preview_candidate_unavailable"
    with SessionFactory() as db:
        durable = db.get(PreviewCandidateRecord, candidate_id)
        current_job = db.get(StudioJobRecord, job["job_id"])
        assert db.scalar(select(func.count()).select_from(Project)) == 1
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 1
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 1
        assert db.scalar(select(func.count()).select_from(ImageRunReview)) == 0
        assert durable is not None and durable.status == "expired"
        assert durable.resolved_at is not None and bytes(durable.image) == b""
        assert current_job is not None and current_job.status == "failed"
        assert current_job.completed_outputs == current_job.charged_outputs == 0
        assert current_job.error_code == "catalog_preview_unavailable"


def test_catalog_preview_saves_exact_spec_directly_as_variation(
    catalog_client,
    example_spec,
    monkeypatch,
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
    newer = client.post(
        f"/assets/{project['active_asset_id']}/catalog/apply",
        json=_request(option_id="white"),
    )
    assert newer.status_code == 201, newer.text
    saved = client.post(
        f"/image-runs/{preview['image_run_id']}/catalog-candidates/"
        f"{preview['candidate']['candidate_id']}/save-as-variation",
        json={"created_by": "usr_catalog", "label": "Rose direction"},
    )
    assert saved.status_code == 201, saved.text
    body = saved.json()
    assert body["status"] == "saved_as_variation"
    assert body["source_project_id"] == project["root_id"]
    assert body["source_asset_id"] == project["active_asset_id"]
    assert body["design_version"] == 1
    assert body["project"]["spec"]["metal"]["color"] == "rose"
    sibling_id = body["project"]["root_id"]
    current = client.get(f"/projects/{project['root_id']}")
    assert current.status_code == 200, current.text
    assert current.json()["active_asset_id"] == newer.json()["asset_id"]
    with SessionFactory() as db:
        original = db.get(Project, project["root_id"])
        sibling = db.get(Project, sibling_id)
        asset = db.get(ImageAsset, sibling_id)
        durable = db.get(PreviewCandidateRecord, preview["candidate"]["candidate_id"])
        review = db.scalar(
            select(ImageRunReview).where(
                ImageRunReview.run_id == preview["image_run_id"]
            )
        )
        assert original is not None and sibling is not None and asset is not None
        assert original.root_id == project["root_id"]
        assert newer.json()["asset_id"] != project["active_asset_id"]
        assert sibling.family_id == original.family_id
        assert sibling.variation_label == "Rose direction"
        assert sibling.branched_from_asset_id == project["active_asset_id"]
        assert asset.design_id == body["design_id"]
        assert asset.design_version == 1
        assert durable is not None
        assert durable.status == "saved_as_variation"
        assert durable.terminal_asset_id == sibling_id
        assert durable.payload["resolved_variation_label"] == "Rose direction"
        assert review is not None and review.accepted_asset_id == sibling_id
        child_map = load_revision_component_map(db, sibling_id)
        assert child_map is not None
        assert child_map.mapper_contract == "facetta.material-only-map-copy.v1"
    normalized_replay = client.post(
        f"/studio/preview-candidates/"
        f"{preview['candidate']['candidate_id']}/decision",
        json={
            "created_by": "usr_catalog",
            "decision": "save_as_variation",
            "expected_active_asset_id": project["active_asset_id"],
            "expected_design_version": 1,
            "variation_label": "Rose direction",
        },
    )
    assert normalized_replay.status_code == 200, normalized_replay.text
    assert normalized_replay.json()["result_project_id"] == sibling_id
    normalized_conflict = client.post(
        f"/studio/preview-candidates/"
        f"{preview['candidate']['candidate_id']}/decision",
        json={
            "created_by": "usr_catalog",
            "decision": "save_as_variation",
            "expected_active_asset_id": project["active_asset_id"],
            "expected_design_version": 1,
            "variation_label": "Another direction",
        },
    )
    assert normalized_conflict.status_code == 409, normalized_conflict.text
    assert normalized_conflict.json()["code"] == (
        "preview_candidate_variation_conflict"
    )


def test_catalog_apply_resolution_failure_rolls_back_asset_spec_and_review(
    catalog_client,
    example_spec,
    monkeypatch,
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
        client.post(
            preview["candidate"]["accept_url"],
            json={
                "expected_design_version": 1,
                "created_by": "usr_catalog",
            },
        )
    with SessionFactory() as db:
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 1
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 1
        assert db.scalar(select(func.count()).select_from(ImageRunReview)) == 0
        durable = db.get(PreviewCandidateRecord, preview["candidate"]["candidate_id"])
        assert durable is not None and durable.status == "reviewing"


def test_catalog_preview_accept_rejects_stale_exact_source_without_rerun(
    catalog_client,
    example_spec,
    monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    job = _studio_job(client, project)
    agent = _ResultAgent(QualityVerdict.PASS)
    monkeypatch.setattr("facetta.api.catalog._trusted_image_agent", lambda: agent)
    preview = client.post(
        f"/assets/{project['active_asset_id']}/catalog/preview",
        json=_request(studio_job_id=job["job_id"]),
    ).json()

    newer = client.post(
        f"/assets/{project['active_asset_id']}/catalog/apply",
        json=_request(option_id="white"),
    )
    assert newer.status_code == 201, newer.text
    assert _counts(SessionFactory) == {"versions": 2, "assets": 2, "runs": 2}

    stale = client.post(
        preview["candidate"]["accept_url"],
        json={
            "expected_design_version": 1,
            "created_by": "usr_catalog",
        },
    )
    assert stale.status_code == 410, stale.text
    assert stale.json()["code"] == "catalog_preview_unavailable"
    assert len(agent.plans) == 2
    assert _counts(SessionFactory) == {"versions": 2, "assets": 2, "runs": 2}
    with SessionFactory() as db:
        durable = db.get(
            PreviewCandidateRecord, preview["candidate"]["candidate_id"])
        current_job = db.get(StudioJobRecord, job["job_id"])
        assert durable is not None and durable.status == "expired"
        assert durable.resolved_at is not None and bytes(durable.image) == b""
        assert current_job is not None and current_job.status == "failed"
        assert current_job.completed_outputs == current_job.charged_outputs == 0
        assert current_job.error_code == "catalog_preview_unavailable"


def test_catalog_candidate_historical_branch_mode_preserves_exact_source_authority(
    catalog_client,
    example_spec,
    monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    agent = _ResultAgent(QualityVerdict.PASS)
    monkeypatch.setattr("facetta.api.catalog._trusted_image_agent", lambda: agent)
    exact_child = client.post(
        f"/assets/{project['active_asset_id']}/catalog/apply",
        json=_request(option_id="white"),
    )
    assert exact_child.status_code == 201, exact_child.text
    source_asset_id = exact_child.json()["asset_id"]
    with SessionFactory() as db:
        source_asset = db.get(ImageAsset, source_asset_id)
        assert source_asset is not None
        assert load_revision_component_map(db, source_asset_id) is not None
    preview = client.post(
        f"/assets/{source_asset_id}/catalog/preview",
        json=_request(expected_design_version=2),
    ).json()
    newer = client.post(
        f"/assets/{source_asset_id}/catalog/apply",
        json=_request(option_id="yellow", expected_design_version=2),
    )
    assert newer.status_code == 201, newer.text

    run_id = preview["image_run_id"]
    candidate_id = preview["candidate"]["candidate_id"]
    with SessionFactory() as db:
        with pytest.raises(CatalogPreviewUnavailable):
            lock_catalog_preview_candidate_for_decision(
                db,
                run_id,
                candidate_id,
                owner="usr_catalog",
            )
        with pytest.raises(CatalogPreviewUnavailable):
            lock_catalog_preview_candidate_for_decision(
                db,
                run_id,
                candidate_id,
                owner="usr_other",
                require_active=False,
            )
        candidate, record = lock_catalog_preview_candidate_for_decision(
            db,
            run_id,
            candidate_id,
            owner="usr_catalog",
            require_active=False,
        )
        assert candidate.source_asset_id == source_asset_id
        assert candidate.expected_active_asset_id == source_asset_id
        assert candidate.expected_design_version == 2
        assert candidate.source_asset_id != newer.json()["asset_id"]
        assert record.status == "reviewing"
        reopened = list_catalog_preview_candidates(
            db,
            project_root_id=project["root_id"],
            owner="usr_catalog",
        )
        assert [item.candidate_id for item in reopened] == [candidate_id]
        assert db.scalar(select(func.count()).select_from(Project)) == 1


@pytest.mark.parametrize(
    "corruption",
    (
        "tampered_source_bytes",
        "missing_component_map",
        "tampered_run_binding",
        "tampered_candidate_qa",
    ),
)
def test_catalog_candidate_historical_branch_mode_fails_closed_on_lineage_drift(
    catalog_client,
    example_spec,
    monkeypatch,
    corruption,
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
    newer = client.post(
        f"/assets/{project['active_asset_id']}/catalog/apply",
        json=_request(option_id="white"),
    )
    assert newer.status_code == 201, newer.text

    run_id = preview["image_run_id"]
    candidate_id = preview["candidate"]["candidate_id"]
    with SessionFactory() as db:
        if corruption == "tampered_source_bytes":
            db.execute(
                ImageAsset.__table__.update()
                .where(ImageAsset.id == project["active_asset_id"])
                .values(image=_png((1, 2, 3)))
            )
        elif corruption == "missing_component_map":
            db.execute(
                RevisionComponentMapRecord.__table__.delete().where(
                    RevisionComponentMapRecord.asset_id
                    == project["active_asset_id"]
                )
            )
        elif corruption == "tampered_run_binding":
            db.execute(
                ImageRun.__table__.update()
                .where(ImageRun.id == run_id)
                .values(source_asset_id=newer.json()["asset_id"])
            )
        else:
            record = db.get(PreviewCandidateRecord, candidate_id)
            assert record is not None
            payload = dict(record.payload)
            payload["qa"] = {}
            record.payload = payload
        db.commit()

    with SessionFactory() as db:
        with pytest.raises(CatalogPreviewUnavailable):
            lock_catalog_preview_candidate_for_decision(
                db,
                run_id,
                candidate_id,
                owner="usr_catalog",
                require_active=False,
            )
        assert db.scalar(select(func.count()).select_from(Project)) == 1
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 2
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 2


def test_catalog_preview_discard_removes_only_temporary_bytes(
    catalog_client,
    example_spec,
    monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    agent = _ResultAgent(QualityVerdict.PASS)
    monkeypatch.setattr("facetta.api.catalog._trusted_image_agent", lambda: agent)
    body = client.post(
        f"/assets/{project['active_asset_id']}/catalog/preview",
        json=_request(),
    ).json()

    discarded = client.delete(body["candidate"]["discard_url"])
    assert discarded.status_code == 204
    assert client.get(body["candidate"]["preview_url"]).status_code == 410
    unavailable = client.post(
        body["candidate"]["accept_url"],
        json={
            "expected_design_version": 1,
            "created_by": "usr_catalog",
        },
    )
    assert unavailable.status_code == 410
    assert unavailable.json()["code"] == "catalog_preview_unavailable"
    assert _counts(SessionFactory) == {"versions": 1, "assets": 1, "runs": 1}
    with SessionFactory() as db:
        durable = db.get(PreviewCandidateRecord, body["candidate"]["candidate_id"])
        assert durable is not None
        assert durable.status == "discarded"
        assert durable.decided_by == "usr_catalog"
        assert durable.terminal_asset_id is None
        assert bytes(durable.image) == b""


def test_catalog_preview_expiry_keeps_evidence_but_no_product_candidate(
    catalog_client,
    example_spec,
    monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    agent = _ResultAgent(QualityVerdict.PASS)
    monkeypatch.setattr("facetta.api.catalog._trusted_image_agent", lambda: agent)
    monkeypatch.setattr("facetta.catalog_preview_candidates._TTL_SECONDS", -1)

    body = client.post(
        f"/assets/{project['active_asset_id']}/catalog/preview",
        json=_request(),
    ).json()

    expired = client.get(body["candidate"]["preview_url"])
    assert expired.status_code == 410
    assert expired.json()["code"] == "catalog_preview_unavailable"
    assert _counts(SessionFactory) == {"versions": 1, "assets": 1, "runs": 1}
    with SessionFactory() as db:
        durable = db.get(PreviewCandidateRecord, body["candidate"]["candidate_id"])
        assert durable is not None
        assert durable.status == "expired"
        assert durable.resolved_at is not None
        assert bytes(durable.image) == b""


def test_catalog_preview_rejects_non_refine_job_before_provider_or_evidence(
    catalog_client,
    example_spec,
    monkeypatch,
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
        assert db.scalar(select(func.count()).select_from(PreviewCandidateRecord)) == 0
        job = db.get(StudioJobRecord, wrong_job["job_id"])
        assert job is not None and job.status == "running"
        assert job.completed_outputs == 0 and job.charged_outputs == 0


def test_production_catalog_preview_requires_job_before_provider(
    catalog_client,
    example_spec,
    monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    provider_calls: list[bool] = []
    monkeypatch.setattr(
        "facetta.api.catalog._trusted_image_agent",
        lambda: provider_calls.append(True),
    )
    monkeypatch.setenv("FACETTA_ENV", "production")

    response = client.post(
        f"/assets/{project['active_asset_id']}/catalog/preview",
        json=_request(),
    )

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "studio_job_required"
    assert provider_calls == []
    with SessionFactory() as db:
        assert db.scalar(select(func.count()).select_from(ImageRun)) == 0
        assert db.scalar(
            select(func.count()).select_from(PreviewCandidateRecord)
        ) == 0


def test_catalog_preview_replay_rejects_reviewing_job_before_provider(
    catalog_client,
    example_spec,
    monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    job = _studio_job(client, project)
    agent = _ResultAgent(QualityVerdict.PASS)
    monkeypatch.setattr("facetta.api.catalog._trusted_image_agent", lambda: agent)
    request = _request(studio_job_id=job["job_id"])

    first = client.post(
        f"/assets/{project['active_asset_id']}/catalog/preview",
        json=request,
    )
    replay = client.post(
        f"/assets/{project['active_asset_id']}/catalog/preview",
        json=request,
    )

    assert first.status_code == 201, first.text
    assert replay.status_code == 409, replay.text
    assert replay.json()["code"] == "catalog_preview_job_invalid"
    assert len(agent.plans) == 1
    with SessionFactory() as db:
        assert db.scalar(select(func.count()).select_from(ImageRun)) == 1
        assert db.scalar(select(func.count()).select_from(
            PreviewCandidateRecord)) == 1
        current_job = db.get(StudioJobRecord, job["job_id"])
        assert current_job is not None and current_job.status == "reviewing"
        assert current_job.completed_outputs == current_job.charged_outputs == 0


def test_catalog_preview_candidate_binding_failure_leaves_no_preview_ready_run(
    catalog_client,
    example_spec,
    monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    job = _studio_job(client, project)
    agent = _ResultAgent(QualityVerdict.PASS)
    monkeypatch.setattr("facetta.api.catalog._trusted_image_agent", lambda: agent)

    def reject_binding(*_args, **_kwargs):
        raise CatalogPreviewJobError("simulated concurrent job settlement")

    monkeypatch.setattr(
        "facetta.api.catalog.store_catalog_preview_candidate",
        reject_binding,
    )

    rejected = client.post(
        f"/assets/{project['active_asset_id']}/catalog/preview",
        json=_request(studio_job_id=job["job_id"]),
    )

    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["code"] == "catalog_preview_job_invalid"
    assert len(agent.plans) == 1
    with SessionFactory() as db:
        assert db.scalar(select(func.count()).select_from(ImageRun)) == 0
        assert db.scalar(select(func.count()).select_from(
            PreviewCandidateRecord)) == 0
        current_job = db.get(StudioJobRecord, job["job_id"])
        assert current_job is not None and current_job.status == "running"
        assert current_job.completed_outputs == current_job.charged_outputs == 0


def test_catalog_preview_store_rejects_invalid_qa_and_settles_job_without_charge(
    catalog_client,
    example_spec,
    monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    job = _studio_job(client, project)
    agent = _ResultAgent(QualityVerdict.PASS)
    monkeypatch.setattr("facetta.api.catalog._trusted_image_agent", lambda: agent)
    monkeypatch.setattr(
        "facetta.api.catalog._quality_payload",
        lambda _result: {
            "verdict": "fail",
            "accepted": False,
            "review_required": False,
            "checks": [{
                "code": "outside_mask_drift",
                "passed": False,
                "severity": "hard",
                "message": "protected jewelry changed outside the target",
            }],
        },
    )

    rejected = client.post(
        f"/assets/{project['active_asset_id']}/catalog/preview",
        json=_request(studio_job_id=job["job_id"]),
    )

    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["code"] == "catalog_preview_qa_invalid"
    assert len(agent.plans) == 1
    with SessionFactory() as db:
        assert db.scalar(select(func.count()).select_from(
            PreviewCandidateRecord)) == 0
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 1
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 1
        assert db.scalar(select(func.count()).select_from(ImageRunReview)) == 0
        runs = list(db.scalars(select(ImageRun)))
        assert len(runs) == 1
        assert runs[0].status == "failed"
        assert runs[0].error_category == "catalog_preview_qa_invalid"
        current_job = db.get(StudioJobRecord, job["job_id"])
        assert current_job is not None and current_job.status == "failed"
        assert current_job.progress == 1
        assert current_job.completed_outputs == current_job.charged_outputs == 0
        assert current_job.error_code == "catalog_preview_qa_invalid"


@pytest.mark.parametrize(
    ("surface", "corruption"),
    (
        ("list", "missing_next_spec"),
        ("image", "invalid_next_spec"),
        ("apply", "missing_spec_lineage"),
        ("list", "missing_qa_fields"),
        ("image", "hard_failure_qa"),
        ("apply", "qa_verdict_mismatch"),
    ),
)
def test_catalog_preview_malformed_payload_fails_closed_and_settles_job(
    catalog_client,
    example_spec,
    monkeypatch,
    surface,
    corruption,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    job = _studio_job(client, project)
    agent = _ResultAgent(QualityVerdict.PASS)
    monkeypatch.setattr("facetta.api.catalog._trusted_image_agent", lambda: agent)
    preview_response = client.post(
        f"/assets/{project['active_asset_id']}/catalog/preview",
        json=_request(studio_job_id=job["job_id"]),
    )
    assert preview_response.status_code == 201, preview_response.text
    preview = preview_response.json()
    candidate_id = preview["candidate"]["candidate_id"]
    with SessionFactory() as db:
        record = db.get(PreviewCandidateRecord, candidate_id)
        assert record is not None
        payload = dict(record.payload)
        if corruption == "missing_next_spec":
            payload.pop("next_spec")
        elif corruption == "invalid_next_spec":
            payload["next_spec"] = "not-a-specification"
        elif corruption == "missing_spec_lineage":
            payload.pop("source_spec_visual_hash")
        elif corruption == "missing_qa_fields":
            payload["qa"] = {}
        elif corruption == "hard_failure_qa":
            payload["qa"] = {
                "verdict": "fail",
                "accepted": False,
                "review_required": False,
                "checks": [{
                    "code": "outside_mask_drift",
                    "passed": False,
                    "severity": "hard",
                }],
            }
        else:
            qa = dict(payload["qa"])
            qa["verdict"] = "warn"
            payload["qa"] = qa
        record.payload = payload
        db.commit()

    if surface == "list":
        rejected = client.get(
            f"/assets/{project['active_asset_id']}/catalog/previews"
        )
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["candidates"] == []
    elif surface == "image":
        rejected = client.get(preview["candidate"]["preview_url"])
        assert rejected.status_code == 410, rejected.text
        assert rejected.json()["code"] == "catalog_preview_unavailable"
    else:
        rejected = client.post(
            preview["candidate"]["accept_url"],
            json={
                "expected_design_version": 1,
                "created_by": "usr_catalog",
            },
        )
        assert rejected.status_code == 410, rejected.text
        assert rejected.json()["code"] == "catalog_preview_unavailable"

    assert len(agent.plans) == 1
    with SessionFactory() as db:
        durable = db.get(PreviewCandidateRecord, candidate_id)
        current_job = db.get(StudioJobRecord, job["job_id"])
        assert durable is not None and durable.status == "expired"
        assert durable.resolved_at is not None and bytes(durable.image) == b""
        assert current_job is not None and current_job.status == "failed"
        assert current_job.progress == 1
        assert current_job.completed_outputs == current_job.charged_outputs == 0
        assert current_job.error_code == "catalog_preview_unavailable"
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 1
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 1
        assert db.scalar(select(func.count()).select_from(ImageRunReview)) == 0


@pytest.mark.parametrize("decision", ("apply", "variation"))
def test_catalog_preview_acceptance_atomically_settles_one_refine_output(
    catalog_client,
    example_spec,
    monkeypatch,
    decision,
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
    reopened = client.get(f"/assets/{project['active_asset_id']}/catalog/previews")
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["candidates"][0]["studio_job_id"] == job["job_id"]
    with SessionFactory() as db:
        durable = db.get(PreviewCandidateRecord, preview["candidate"]["candidate_id"])
        current_job = db.get(StudioJobRecord, job["job_id"])
        assert durable is not None and durable.studio_job_id == job["job_id"]
        assert current_job is not None and current_job.status == "reviewing"
        assert current_job.completed_outputs == current_job.charged_outputs == 0

    if decision == "apply":
        terminal = client.post(
            preview["candidate"]["accept_url"],
            json={
                "expected_design_version": 1,
                "created_by": "usr_catalog",
            },
        )
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
        repeated = client.post(
            preview["candidate"]["accept_url"],
            json={
                "expected_design_version": 1,
                "created_by": "usr_catalog",
            },
        )
        assert repeated.status_code == 410
    else:
        repeated = client.post(
            preview["candidate"]["save_as_variation_url"],
            json={
                "created_by": "usr_catalog",
                "label": "Rose job direction",
            },
        )
        assert repeated.status_code == 201, repeated.text
        conflict = client.post(
            preview["candidate"]["save_as_variation_url"],
            json={"created_by": "usr_catalog", "label": "Duplicate"},
        )
        assert conflict.status_code == 409, conflict.text
        assert conflict.json()["code"] == "preview_candidate_variation_conflict"
    with SessionFactory() as db:
        current_job = db.get(StudioJobRecord, job["job_id"])
        assert current_job is not None
        assert current_job.completed_outputs == current_job.charged_outputs == 1


@pytest.mark.parametrize("decision", ("apply", "save_as_variation", "discard"))
def test_direct_catalog_terminal_decision_rejects_cross_store_job_binding(
    catalog_client,
    example_spec,
    monkeypatch,
    decision,
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
    candidate_id = preview["candidate"]["candidate_id"]
    sibling_bytes = _png((85, 115, 145))
    sibling_run_id = f"run_legacy_markup_catalog_{decision}"
    sibling_id = f"cand_legacy_markup_catalog_{decision}"
    with SessionFactory() as db:
        source = db.get(ImageAsset, project["active_asset_id"])
        assert source is not None
        source_bytes = bytes(source.image)
        db.add(ImageRun(
            id=sibling_run_id,
            project_root_id=project["root_id"],
            source_asset_id=project["active_asset_id"],
            operation="LOCAL_EDIT",
            normalized_intent={"change": "legacy dual binding"},
            prompt_version="test.v1",
            input_hash=hashlib.sha256(sibling_bytes).hexdigest(),
            source_hash=hashlib.sha256(source_bytes).hexdigest(),
            mask_hash=None,
            spec_visual_hash=None,
            source_spec_visual_hash=None,
            variant=0,
            status="review_required",
            accepted_asset_id=None,
            created_by="usr_catalog",
        ))
        db.flush()
        db.add(StudioMarkupCandidateRecord(
            id=sibling_id,
            image_run_id=sibling_run_id,
            owner="usr_catalog",
            project_root_id=project["root_id"],
            source_asset_id=project["active_asset_id"],
            expected_active_asset_id=project["active_asset_id"],
            design_version=1,
            source_sha256=hashlib.sha256(source_bytes).hexdigest(),
            output_sha256=hashlib.sha256(sibling_bytes).hexdigest(),
            source_spec_visual_hash="a" * 16,
            target_spec_visual_hash="a" * 16,
            image=sibling_bytes,
            media_type="image/png",
            operation="LOCAL_EDIT",
            asset_capability="LOCALIZED_EDIT",
            requested_change="legacy dual binding",
            region_description="legacy region",
            payload={"qa": {"verdict": "pass"}},
            status="reviewing",
            studio_job_id=job["job_id"],
            created_at=utcnow(),
            expires_at=utcnow() + timedelta(hours=2),
        ))
        db.commit()
    before = _counts(SessionFactory)

    if decision == "apply":
        rejected = client.post(
            preview["candidate"]["accept_url"],
            json={"expected_design_version": 1, "created_by": "usr_catalog"},
        )
        expected_code = "catalog_preview_job_conflict"
    elif decision == "save_as_variation":
        rejected = client.post(
            preview["candidate"]["save_as_variation_url"],
            json={"created_by": "usr_catalog", "label": "Blocked direction"},
        )
        expected_code = "preview_candidate_job_binding_conflict"
    else:
        rejected = client.delete(preview["candidate"]["discard_url"])
        expected_code = "catalog_preview_job_conflict"
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["code"] == expected_code
    assert _counts(SessionFactory) == before
    with SessionFactory() as db:
        candidate = db.get(PreviewCandidateRecord, candidate_id)
        sibling = db.get(StudioMarkupCandidateRecord, sibling_id)
        durable_job = db.get(StudioJobRecord, job["job_id"])
        durable_project = db.get(Project, project["root_id"])
        assert candidate is not None and candidate.status == "reviewing"
        assert sibling is not None and sibling.status == "reviewing"
        assert durable_job is not None and durable_job.status == "reviewing"
        assert (durable_job.completed_outputs, durable_job.charged_outputs) == (0, 0)
        assert durable_project is not None
        assert durable_project.selected_candidate_asset_id in {
            None,
            project["active_asset_id"],
        }


@pytest.mark.parametrize("decision", ("discard", "expire"))
def test_catalog_preview_zero_output_decisions_cancel_without_charge(
    catalog_client,
    example_spec,
    monkeypatch,
    decision,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    job = _studio_job(client, project)
    monkeypatch.setattr(
        "facetta.api.catalog._trusted_image_agent",
        lambda: _ResultAgent(QualityVerdict.PASS),
    )
    if decision == "expire":
        monkeypatch.setattr("facetta.catalog_preview_candidates._TTL_SECONDS", -1)
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
        durable = db.get(PreviewCandidateRecord, preview["candidate"]["candidate_id"])
        assert current_job is not None and current_job.status == "canceled"
        assert current_job.completed_outputs == current_job.charged_outputs == 0
        assert durable is not None
        assert durable.status == ("discarded" if decision == "discard" else "expired")


def test_catalog_preview_hard_failure_has_evidence_and_no_candidate(
    catalog_client,
    example_spec,
    monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    calls = []

    class FailingAgent:
        def run(self, plan, **_kwargs):
            calls.append(plan)
            report = ImageQualityReport(
                verdict=QualityVerdict.FAIL,
                checks=(
                    QualityCheck(
                        code="outside_mask_drift",
                        passed=False,
                        severity=CheckSeverity.HARD,
                        message="protected jewelry changed outside the target",
                    ),
                ),
                score=20,
            )
            raise ImageQualityFailure(
                "no candidate passed jewelry QA: outside_mask_drift",
                report=report,
                plan=plan,
            )

    monkeypatch.setattr(
        "facetta.api.catalog._trusted_image_agent", lambda: FailingAgent()
    )
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


@pytest.mark.parametrize(
    ("failure_kind", "expected_status", "expected_code"),
    (
        ("provider", 502, "image_provider_failed"),
        ("quality", 422, "image_quality_failed"),
    ),
)
def test_catalog_preview_execution_failure_settles_refine_job_without_charge(
    catalog_client,
    example_spec,
    monkeypatch,
    failure_kind,
    expected_status,
    expected_code,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    job = _studio_job(client, project)

    class FailingAgent:
        def run(self, plan, **_kwargs):
            if failure_kind == "provider":
                raise ImageProviderFailure(
                    "the image provider failed",
                    plan=plan,
                )
            report = ImageQualityReport(
                verdict=QualityVerdict.FAIL,
                checks=(
                    QualityCheck(
                        code="outside_mask_drift",
                        passed=False,
                        severity=CheckSeverity.HARD,
                        message="protected jewelry changed outside the target",
                    ),
                ),
                score=20,
            )
            raise ImageQualityFailure(
                "no candidate passed jewelry QA: outside_mask_drift",
                report=report,
                plan=plan,
            )

    monkeypatch.setattr(
        "facetta.api.catalog._trusted_image_agent", lambda: FailingAgent(),
    )
    failed = client.post(
        f"/assets/{project['active_asset_id']}/catalog/preview",
        json=_request(studio_job_id=job["job_id"]),
    )

    assert failed.status_code == expected_status, failed.text
    body = failed.json()
    assert body["code"] == expected_code
    assert body["image_run_id"] is not None
    assert _counts(SessionFactory) == {"versions": 1, "assets": 1, "runs": 1}
    with SessionFactory() as db:
        run = db.get(ImageRun, body["image_run_id"])
        current_job = db.get(StudioJobRecord, job["job_id"])
        assert run is not None and run.status == "failed"
        assert run.accepted_asset_id is None
        assert db.scalar(select(func.count()).select_from(
            PreviewCandidateRecord)) == 0
        assert current_job is not None and current_job.status == "failed"
        assert current_job.progress == 1
        assert current_job.completed_outputs == current_job.charged_outputs == 0
        assert current_job.error_code == expected_code


def test_catalog_preview_lineage_incomplete_persists_failure_and_settles_job(
    catalog_client,
    example_spec,
    monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    job = _studio_job(client, project)
    delegate = _ResultAgent(QualityVerdict.PASS)

    class IncompleteLineageAgent:
        def run(self, plan, **kwargs):
            result = delegate.run(plan, **kwargs)
            plan.source_hash = None
            return result.model_copy(update={"plan": plan})

    monkeypatch.setattr(
        "facetta.api.catalog._trusted_image_agent",
        lambda: IncompleteLineageAgent(),
    )
    failed = client.post(
        f"/assets/{project['active_asset_id']}/catalog/preview",
        json=_request(studio_job_id=job["job_id"]),
    )

    assert failed.status_code == 500, failed.text
    body = failed.json()
    assert body["code"] == "catalog_preview_lineage_incomplete"
    assert body["image_run_id"] is not None
    assert len(delegate.plans) == 1
    with SessionFactory() as db:
        run = db.get(ImageRun, body["image_run_id"])
        current_job = db.get(StudioJobRecord, job["job_id"])
        assert run is not None and run.status == "failed"
        assert run.accepted_asset_id is None
        assert run.source_hash is None
        assert run.error_category == "catalog_preview_lineage_incomple"
        assert db.scalar(select(func.count()).select_from(
            PreviewCandidateRecord)) == 0
        assert current_job is not None and current_job.status == "failed"
        assert current_job.progress == 1
        assert current_job.completed_outputs == current_job.charged_outputs == 0
        assert current_job.error_code == "catalog_preview_lineage_incomplete"
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 1
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 1


def test_catalog_preview_accept_database_failure_rolls_back_atomic_pair(
    catalog_client,
    example_spec,
    monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    agent = _ResultAgent(QualityVerdict.PASS)
    monkeypatch.setattr("facetta.api.catalog._trusted_image_agent", lambda: agent)
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
        client.post(
            body["candidate"]["accept_url"],
            json={
                "expected_design_version": 1,
                "created_by": "usr_catalog",
            },
        )
    assert _counts(SessionFactory) == baseline


def test_catalog_pass_uses_exact_specs_and_persists_one_atomic_revision(
    catalog_client,
    example_spec,
    monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    agent = _ResultAgent(QualityVerdict.PASS)
    monkeypatch.setattr("facetta.api.catalog._trusted_image_agent", lambda: agent)

    response = client.post(
        f"/assets/{project['active_asset_id']}/catalog/apply",
        json=_request(),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "accepted"
    assert body["design_version"] == 2
    assert body["spec_change"] == [
        {
            "path": "metal.color",
            "before": "yellow",
            "after": "rose",
            "label": "gold color",
        }
    ]
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
    rose = next(
        option for option in get_component_catalog("metal.color") if option.id == "rose"
    )
    assert plan.style_constraints == rose.visual_geometry
    assert plan.normalized_intent["spec_delta"][0]["path"] == "metal.color"

    assert _counts(SessionFactory) == {"versions": 2, "assets": 2, "runs": 1}
    with SessionFactory() as db:
        run = db.get(ImageRun, body["image_run_id"])
        child = db.get(ImageAsset, body["asset_id"])
        version = db.get(DesignVersion, (project["design_id"], 2))
        revision = db.scalar(
            select(ProjectRevisionRecord).where(
                ProjectRevisionRecord.asset_id == body["asset_id"]
            )
        )
        source_map = load_revision_component_map(db, project["active_asset_id"])
        child_map = load_revision_component_map(db, body["asset_id"])
        assert run is not None and run.accepted_asset_id == child.id
        assert run.source_asset_id == project["active_asset_id"]
        assert child.parent_asset_id == project["active_asset_id"]
        assert child.design_version == 2
        assert version.spec["metal"]["color"] == "rose"
        assert revision is not None and revision.action == "edit"
        assert revision.raw_intent == {
            "kind": "trusted_spec_image_revision",
            "instruction": plan.intent,
            "region": plan.region_description,
            "source_asset_id": project["active_asset_id"],
            "image_run_id": body["image_run_id"],
        }
        assert revision.interpretation["source_sha256"] == plan.source_hash
        assert (
            revision.interpretation["output_sha256"]
            == hashlib.sha256(bytes(child.image)).hexdigest()
        )
        assert revision.interpretation["source_spec_visual_hash"] == (
            plan.source_spec_visual_hash
        )
        assert revision.interpretation["target_spec_visual_hash"] == (
            plan.spec_visual_hash
        )
        assert source_map is not None and child_map is not None
        assert child_map.asset_id == child.id
        assert child_map.asset_sha256 == hashlib.sha256(bytes(child.image)).hexdigest()
        assert child_map.components == source_map.components
        assert child_map.mapper_contract == "facetta.material-only-map-copy.v1"
        assert revision.interpretation["component_map_state"] == "ready"
        assert revision.interpretation["component_map_sha256"] == (
            component_map_hash(child_map)
        )
        assert revision.interpretation["target_component_ids"] == [
            "prongs",
            "setting",
            "shank",
            "shoulders",
            "gallery",
            "metal",
        ]
        assert revision.interpretation["factory_authority"] is False


def test_catalog_center_stone_color_persists_one_paired_species_revision(
    catalog_client,
    halo_spec,
    monkeypatch,
):
    """A quick color choice is one image/spec revision, never two writes.

    The UI sends the selected palette species explicitly.  That permits a
    designer to go from a diamond to Royal Blue sapphire with one action while
    preventing an unscoped color string from being promoted as a fact.
    """
    client, SessionFactory = catalog_client
    project = _create_project(client, halo_spec, SessionFactory)
    agent = _ResultAgent(QualityVerdict.PASS)
    monkeypatch.setattr("facetta.api.catalog._trusted_image_agent", lambda: agent)

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
    catalog_client,
    example_spec,
    monkeypatch,
    payload,
    status,
    code,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    agent = _ResultAgent(QualityVerdict.PASS)
    monkeypatch.setattr("facetta.api.catalog._trusted_image_agent", lambda: agent)

    response = client.post(
        f"/assets/{project['active_asset_id']}/catalog/apply",
        json=payload,
    )
    assert response.status_code == status, response.text
    assert response.json()["code"] == code
    assert agent.plans == []
    assert _counts(SessionFactory) == {"versions": 1, "assets": 1, "runs": 0}


def test_catalog_warning_keeps_next_spec_temporary_until_explicit_review(
    catalog_client,
    example_spec,
    monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    agent = _ResultAgent(QualityVerdict.WARN)
    monkeypatch.setattr("facetta.api.catalog._trusted_image_agent", lambda: agent)

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
    catalog_client,
    example_spec,
    monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    calls = []

    class FailingAgent:
        def run(self, plan, **_kwargs):
            calls.append(plan)
            report = ImageQualityReport(
                verdict=QualityVerdict.FAIL,
                checks=(
                    QualityCheck(
                        code="metal_geometry_drift",
                        passed=False,
                        severity=CheckSeverity.HARD,
                        message="the candidate changed ring geometry",
                    ),
                ),
                score=35,
            )
            raise ImageQualityFailure(
                "no candidate passed jewelry QA: metal_geometry_drift",
                report=report,
                plan=plan,
            )

    monkeypatch.setattr(
        "facetta.api.catalog._trusted_image_agent", lambda: FailingAgent()
    )
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
        assert db.scalar(select(func.count()).select_from(
            ProjectRevisionRecord
        )) == 0


def test_catalog_database_failure_rolls_back_image_spec_and_run_together(
    catalog_client,
    example_spec,
    monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    agent = _ResultAgent(QualityVerdict.PASS)
    monkeypatch.setattr("facetta.api.catalog._trusted_image_agent", lambda: agent)
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
    with SessionFactory() as db:
        assert db.scalar(select(func.count()).select_from(
            ProjectRevisionRecord
        )) == 0


def test_catalog_component_map_failure_rolls_back_entire_canonical_revision(
    catalog_client,
    example_spec,
    monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    agent = _ResultAgent(QualityVerdict.PASS)
    monkeypatch.setattr("facetta.api.catalog._trusted_image_agent", lambda: agent)
    baseline = _counts(SessionFactory)

    def fail_component_map(*_args, **_kwargs):
        raise RuntimeError("simulated component-map transaction failure")

    monkeypatch.setattr(
        "facetta.trusted_revision.add_revision_component_map",
        fail_component_map,
    )
    with pytest.raises(
        RuntimeError,
        match="simulated component-map transaction failure",
    ):
        client.post(
            f"/assets/{project['active_asset_id']}/catalog/apply",
            json=_request(),
        )

    assert _counts(SessionFactory) == baseline
    with SessionFactory() as db:
        assert db.scalar(select(func.count()).select_from(ProjectRevisionRecord)) == 0
        assert (
            db.scalar(select(func.count()).select_from(RevisionComponentMapRecord)) == 1
        )


def test_old_primary_asset_is_rejected_before_provider(
    catalog_client,
    example_spec,
    monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_project(client, example_spec, SessionFactory)
    first_agent = _ResultAgent(QualityVerdict.PASS)
    monkeypatch.setattr("facetta.api.catalog._trusted_image_agent", lambda: first_agent)
    accepted = client.post(
        f"/assets/{project['active_asset_id']}/catalog/apply",
        json=_request(),
    )
    assert accepted.status_code == 201

    second_agent = _ResultAgent(QualityVerdict.PASS)
    monkeypatch.setattr(
        "facetta.api.catalog._trusted_image_agent", lambda: second_agent
    )
    stale = client.post(
        f"/assets/{project['active_asset_id']}/catalog/apply",
        json=_request(option_id="white", expected_design_version=2),
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "stale_asset_revision"
    assert second_agent.plans == []
    assert _counts(SessionFactory) == {"versions": 2, "assets": 2, "runs": 1}


def test_catalog_selection_preserves_every_non_catalog_spec_fact(
    catalog_client,
    example_spec,
    monkeypatch,
):
    client, SessionFactory = catalog_client
    source = deepcopy(example_spec)
    project = _create_project(client, source, SessionFactory)
    agent = _ResultAgent(QualityVerdict.PASS)
    monkeypatch.setattr("facetta.api.catalog._trusted_image_agent", lambda: agent)

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
    catalog_client,
    monkeypatch,
):
    client, SessionFactory = catalog_client
    project = _create_necklace_project(client)
    assert project["spec"]["jewelry_type"] == "necklace"
    assert [blocker["code"] for blocker in project["factory_blockers"]] == [
        "factory_category_not_released",
    ]
    source_asset_id = project["active_asset_id"]
    agent = _ResultAgent(QualityVerdict.PASS)
    monkeypatch.setattr("facetta.api.catalog._trusted_image_agent", lambda: agent)

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
    visual_paths = {change["path"] for change in plan.normalized_intent["spec_delta"]}
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
            "SOURCE-CABLE-2MM"
        )
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
                key: value
                for key, value in _chain_request().items()
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
    monkeypatch.setattr("facetta.api.catalog._trusted_image_agent", lambda: agent)

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
    monkeypatch.setattr("facetta.api.catalog._trusted_image_agent", lambda: agent)

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
    assert body["next_spec"]["chain"]["geometry"] == (_open_link_geometry(width=2.2))
    assert body["next_spec"]["chain"]["production"] == (
        _production("TARGET-CURB-2.2MM")
    )
    warned_provenance = body["next_spec"]["dimension_provenance"]
    assert (
        warned_provenance["chain.geometry.chain_width_mm"]["status"]
        == "designer_confirmed"
    )
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
    assert accepted_project["spec"]["dimension_provenance"] == (warned_provenance)
    assert accepted_project["active_asset_id"] != project["active_asset_id"]
    assert _counts(SessionFactory) == {"versions": 2, "assets": 2, "runs": 1}


def test_from_image_necklace_must_remain_the_supported_confirmed_template(
    catalog_client,
):
    client, _ = catalog_client
    invalid = _necklace_spec()
    invalid["template"] = "solitaire_prong"

    response = client.post(
        "/projects/from-image",
        json={
            "image_base64": base64.b64encode(_png()).decode(),
            "media_type": "image/png",
            "spec": invalid,
            "owner": "usr_catalog",
            "title": "Invalid necklace",
        },
    )

    assert response.status_code == 422
    assert "cluster_pendant" in response.json()["detail"]

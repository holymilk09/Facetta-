"""Revision component identity, masks, API routing, and atomic apply."""

from __future__ import annotations

import hashlib
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import facetta.api.assets as assets_mod
from facetta.db import (
    Base,
    DesignVersion,
    ImageAsset,
    ImmutableRevisionComponentMapError,
    RevisionComponentMapRecord,
    Project,
    get_db,
)
from facetta.design_form import NormalizedPoint, NormalizedPolygon
from facetta.image_agent import (
    CheckSeverity,
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
    polygon_hash,
    rasterize_component_mask,
)
from facetta.revision_component_map_store import (
    add_revision_component_map,
    load_revision_component_map,
)
from facetta.studio_history import fork_project_variation

from conftest import HALO_SPEC


def _png(color=(200, 200, 200), size=(200, 300)) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, format="PNG")
    return output.getvalue()


def _polygon(offset: float = 0.0) -> tuple[NormalizedPolygon, ...]:
    polygon = NormalizedPolygon(points=(
        NormalizedPoint(x=0.25 + offset, y=0.2),
        NormalizedPoint(x=0.55 + offset, y=0.2),
        NormalizedPoint(x=0.55 + offset, y=0.5),
        NormalizedPoint(x=0.25 + offset, y=0.5),
    ))
    return (polygon,)


REQUIRED = (
    ("center", "center_stone"),
    ("prongs", "prongs"),
    ("setting", "setting"),
    ("shank", "shank"),
    ("shoulders", "shoulders"),
    ("gallery", "gallery"),
    ("metal", "metal_zone"),
    ("background", "background"),
)


def _map(
    asset_id: str,
    image: bytes,
    *,
    child: bool = False,
) -> RevisionComponentMap:
    components = []
    for index, (component_id, kind) in enumerate(REQUIRED):
        polygons = _polygon(min(index, 4) * 0.01)
        components.append(RevisionComponent(
            component_id=(f"mapped.{component_id}" if child else component_id),
            parent_component_id=(component_id if child else None),
            kind=kind,
            label=component_id.replace("_", " ").title(),
            resolution="resolved",
            polygons=polygons,
            polygon_sha256=polygon_hash(polygons),
        ))
    with Image.open(io.BytesIO(image)) as raster:
        width, height = raster.size
    return RevisionComponentMap(
        asset_id=asset_id,
        asset_sha256=hashlib.sha256(image).hexdigest(),
        raster_width=width,
        raster_height=height,
        jewelry_type="ring",
        mapper_contract="test.mapper.v1",
        components=tuple(components),
    )


def test_exact_variation_branch_carries_component_identity_map():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False)() as db:
        image = _png()
        source = ImageAsset(
            id="ast_mapped_source", root_id="ast_mapped_source",
            parent_asset_id=None, design_version=None,
            capability="IMPORTED_REFERENCE", image=image, media_type="image/png",
            created_by="designer",
        )
        project = Project(
            root_id=source.id, owner="designer", title="Mapped variation", tags=[],
        )
        db.add_all([source, project])
        db.flush()
        add_revision_component_map(
            db, _map(source.id, image), image_bytes=image, parent_asset_id=None,
        )
        db.commit()

        result = fork_project_variation(
            db,
            project_root_id=project.root_id,
            source_asset_id=source.id,
            expected_active_asset_id=source.id,
            expected_design_version=None,
            variation_label="Mapped sibling",
            created_by="designer",
        )

        child_map = load_revision_component_map(db, result.asset_id)
        assert child_map is not None
        assert child_map.asset_id == result.asset_id
        assert child_map.asset_sha256 == hashlib.sha256(image).hexdigest()
        assert child_map.mapper_contract == "facetta.byte-identical-map-copy.v1"
        assert {component.component_id for component in child_map.components} == {
            component.component_id for component in _map(source.id, image).components
        }


@pytest.fixture
def component_client(monkeypatch):
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

    app.dependency_overrides[get_db] = override
    monkeypatch.setattr(
        assets_mod, "jewelry_render", lambda *args, **kwargs: (_png(), False)
    )
    yield TestClient(app), TestSession
    app.dependency_overrides.clear()


def _mapped_asset(client: TestClient, Session) -> tuple[str, str, bytes]:
    design = client.post(
        "/designs", json={"created_by": "usr_ana", "spec": HALO_SPEC}
    )
    assert design.status_code == 201, design.text
    design_id = design.json()["design_id"]
    rendered = client.post(
        "/assets/render",
        json={"piece_description": "a halo ring", "design_id": design_id},
    )
    assert rendered.status_code == 201, rendered.text
    asset_id = rendered.json()["asset_id"]
    with Session() as db:
        asset = db.get(ImageAsset, asset_id)
        image = bytes(asset.image)
        add_revision_component_map(
            db,
            _map(asset_id, image),
            image_bytes=image,
            parent_asset_id=None,
        )
        db.commit()
    return asset_id, design_id, image


def test_ring_inventory_is_strict_and_mask_is_bound_to_component():
    image = _png()
    valid = _map("ast_parent", image)
    center_mask = Image.open(io.BytesIO(
        rasterize_component_mask(valid, "center")
    )).convert("L")
    assert center_mask.size == (200, 300)
    assert center_mask.getpixel((80, 100)) == 255
    assert center_mask.getpixel((10, 280)) == 0

    with pytest.raises(ValidationError, match="missing required kinds"):
        RevisionComponentMap.model_validate({
            **valid.model_dump(mode="json"),
            "components": valid.model_dump(mode="json")["components"][:-1],
        })


def test_component_map_and_mask_get_apis(component_client):
    client, Session = component_client
    asset_id, _, _ = _mapped_asset(client, Session)
    mapped = client.get(f"/assets/{asset_id}/component-map")
    assert mapped.status_code == 200, mapped.text
    assert mapped.json()["asset_id"] == asset_id
    assert len(mapped.json()["components"]) == 8

    mask = client.get(f"/assets/{asset_id}/components/center/mask")
    assert mask.status_code == 200
    assert mask.headers["content-type"] == "image/png"
    raster = Image.open(io.BytesIO(mask.content)).convert("L")
    assert raster.getpixel((80, 100)) == 255
    assert raster.getpixel((10, 280)) == 0

    missing = client.get(
        f"/assets/{asset_id}/components/nonexistent/mask"
    )
    assert missing.status_code == 404
    assert missing.json()["code"] == "target_component_not_found"

    without_target = client.post(f"/assets/{asset_id}/markup/apply", json={
        "expected_design_version": 1,
        "update_spec": False,
        "annotations": [{
            "region_description": "the center stone",
            "change_instruction": "cool the reflections",
        }],
    })
    assert without_target.status_code == 422
    assert without_target.json()["code"] == "target_component_required"

    with Session() as db:
        record = db.get(RevisionComponentMapRecord, asset_id)
        record.map_json = {"tampered": True}
        with pytest.raises(ImmutableRevisionComponentMapError):
            db.commit()
        db.rollback()
    assert client.get(f"/assets/{asset_id}/component-map").status_code == 200


def test_target_id_drives_plan_mask_and_child_map_commits_atomically(
    component_client,
    monkeypatch,
):
    client, Session = component_client
    asset_id, _, _ = _mapped_asset(client, Session)
    provider_masks: list[bytes] = []

    class Provider:
        def execute(self, plan, route, prompt, *, source_image, mask_bytes):
            provider_masks.append(mask_bytes)
            return ProviderImage(image_bytes=_png((120, 110, 100)))

    class PassingEvaluator:
        def evaluate(self, plan, candidate, *, source_image, mask_bytes):
            return ImageQualityReport(
                verdict=QualityVerdict.PASS,
                checks=(QualityCheck(
                    code="component_edit_preserved",
                    passed=True,
                    severity=CheckSeverity.HARD,
                    message="selected component changed and all else stayed fixed",
                ),),
                score=98,
            )

    monkeypatch.setattr(
        assets_mod,
        "_trusted_image_agent",
        lambda: JewelryImageAgent(Provider(), PassingEvaluator()),
    )

    mapper_calls = []

    def mapper(**kwargs):
        mapper_calls.append(kwargs)
        return _map(
            kwargs["child_asset_id"], kwargs["child_image"], child=True
        )

    monkeypatch.setattr(assets_mod, "_revision_component_mapper", mapper)
    response = client.post(f"/assets/{asset_id}/markup/apply", json={
        "expected_design_version": 1,
        "update_spec": False,
        "annotations": [{
            "region_description": "the center stone",
            "change_instruction": "cool the center stone reflections",
            "target_component_id": "center",
        }],
    })
    assert response.status_code == 201, response.text
    body = response.json()
    child_id = body["final_asset_id"]
    assert body["steps"][0]["target_component_id"] == "center"
    assert body["steps"][0]["component_map_url"] == (
        f"/assets/{child_id}/component-map"
    )
    expected_mask = client.get(
        f"/assets/{asset_id}/components/center/mask"
    ).content
    assert len(provider_masks) == 1
    assert provider_masks[0] == expected_mask
    assert mapper_calls[0]["target_component_id"] == "center"
    child_map = client.get(f"/assets/{child_id}/component-map").json()
    assert {item["component_id"] for item in child_map["components"]} == {
        component_id for component_id, _ in REQUIRED
    }
    assert child_map["asset_sha256"] == hashlib.sha256(
        _png((120, 110, 100))
    ).hexdigest()


def test_unresolved_mapping_and_map_write_failure_leave_no_child(
    component_client,
    monkeypatch,
):
    client, Session = component_client
    asset_id, design_id, _ = _mapped_asset(client, Session)

    class Provider:
        def execute(self, plan, route, prompt, *, source_image, mask_bytes):
            return ProviderImage(image_bytes=_png((90, 90, 90)))

    class PassingEvaluator:
        def evaluate(self, plan, candidate, *, source_image, mask_bytes):
            return ImageQualityReport(
                verdict=QualityVerdict.PASS,
                checks=(QualityCheck(
                    code="pass", passed=True, severity=CheckSeverity.HARD,
                    message="pass",
                ),),
                score=99,
            )

    monkeypatch.setattr(
        assets_mod,
        "_trusted_image_agent",
        lambda: JewelryImageAgent(Provider(), PassingEvaluator()),
    )
    request = {
        "expected_design_version": 1,
        "update_spec": False,
        "annotations": [{
            "region_description": "the center stone",
            "change_instruction": "cool the center stone reflections",
            "target_component_id": "center",
        }],
    }
    unresolved = client.post(f"/assets/{asset_id}/markup/apply", json=request)
    assert unresolved.status_code == 422
    assert unresolved.json()["code"] == "component_mapping_unresolved"

    monkeypatch.setattr(
        assets_mod,
        "_revision_component_mapper",
        lambda **kwargs: _map(
            kwargs["child_asset_id"], kwargs["child_image"], child=True
        ),
    )
    original_add = assets_mod.add_revision_component_map

    def fail_map_write(*args, **kwargs):
        raise RuntimeError("simulated map write failure")

    monkeypatch.setattr(
        assets_mod, "add_revision_component_map", fail_map_write
    )
    with pytest.raises(RuntimeError, match="simulated map write failure"):
        client.post(f"/assets/{asset_id}/markup/apply", json=request)

    with Session() as db:
        assets = db.scalar(select(func.count(ImageAsset.id)))
        maps = db.scalar(select(func.count(RevisionComponentMapRecord.asset_id)))
        versions = db.scalar(select(func.count(DesignVersion.version)).where(
            DesignVersion.design_id == design_id
        ))
    assert assets == 1
    assert maps == 1
    assert versions == 1
    monkeypatch.setattr(
        assets_mod, "add_revision_component_map", original_add
    )

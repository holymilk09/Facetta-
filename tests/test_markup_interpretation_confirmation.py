"""Markup reading must be confirmed durably before marked generation."""

import base64
import hashlib
import io
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy import create_engine, func, select, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import facetta.api.assets as assets_mod
from conftest import HALO_SPEC
from facetta.db import (
    Base,
    DesignVersion,
    ImageAsset,
    ImageRun,
    StudioMarkupInterpretationRecord,
    get_db,
    utcnow,
)
from facetta.design_form import NormalizedPoint, NormalizedPolygon
from facetta.main import app
from facetta.image_agent import (
    CheckSeverity,
    ImageOperation,
    ImageQualityReport,
    JewelryImageAgent,
    ProviderImage,
    QualityCheck,
    QualityVerdict,
)
from facetta.revision_component_map import (
    RevisionComponent,
    RevisionComponentMap,
    polygon_hash,
)
from facetta.revision_component_map_store import add_revision_component_map


def _png(color=(200, 200, 200)) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (120, 120), color).save(output, format="PNG")
    return output.getvalue()


def _marked() -> bytes:
    image = Image.open(io.BytesIO(_png())).convert("RGB")
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 20, 70, 70), outline=(255, 0, 0), width=4)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


READING = {
    "annotations": [{
        "region_description": "the highlighted metal surface",
        "change_instruction": "make only the highlighted metal warmer",
        "confidence": 0.96,
    }],
    "understood_as": (
        "Warm only the highlighted metal surface; keep the jewelry unchanged."
    ),
    "needs_clarification": False,
    "clarification": "",
}


def _component_map(asset_id: str, image: bytes) -> RevisionComponentMap:
    polygon = NormalizedPolygon(points=(
        NormalizedPoint(x=0.2, y=0.2),
        NormalizedPoint(x=0.5, y=0.2),
        NormalizedPoint(x=0.5, y=0.5),
        NormalizedPoint(x=0.2, y=0.5),
    ))
    polygons = (polygon,)
    kinds = (
        ("center", "center_stone"),
        ("prongs", "prongs"),
        ("setting", "setting"),
        ("shank", "shank"),
        ("shoulders", "shoulders"),
        ("gallery", "gallery"),
        ("metal", "metal_zone"),
        ("background", "background"),
    )
    return RevisionComponentMap(
        asset_id=asset_id,
        asset_sha256=hashlib.sha256(image).hexdigest(),
        raster_width=120,
        raster_height=120,
        jewelry_type="ring",
        mapper_contract="test.markup-confirmation.v1",
        components=tuple(
            RevisionComponent(
                component_id=component_id,
                kind=kind,
                label=component_id.title(),
                resolution="resolved",
                polygons=polygons,
                polygon_sha256=polygon_hash(polygons),
            )
            for component_id, kind in kinds
        ),
    )


@pytest.fixture
def confirmation_client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)

    def override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    monkeypatch.setenv("FACETTA_ENV", "test")
    monkeypatch.setattr(
        assets_mod,
        "jewelry_render",
        lambda *_args, **_kwargs: (_png(), False),
    )
    monkeypatch.setattr(
        assets_mod,
        "read_markup",
        lambda *_args, **_kwargs: dict(READING),
    )
    try:
        yield TestClient(app), Session
    finally:
        app.dependency_overrides.clear()


def _source(client: TestClient, *, owner: str = "usr_ana") -> tuple[str, str]:
    design = client.post("/designs", json={
        "created_by": owner,
        "spec": HALO_SPEC,
    })
    assert design.status_code == 201, design.text
    design_id = design.json()["design_id"]
    rendered = client.post("/assets/render", json={
        "piece_description": "a halo ring",
        "design_id": design_id,
        "created_by": owner,
    })
    assert rendered.status_code == 201, rendered.text
    return rendered.json()["asset_id"], design_id


def _read(client: TestClient, source_id: str, *, owner: str = "usr_ana") -> dict:
    response = client.post(f"/assets/{source_id}/markup/read", json={
        "marked_image_base64": base64.b64encode(_marked()).decode(),
        "created_by": owner,
    })
    assert response.status_code == 200, response.text
    return response.json()


def _confirm(
    client: TestClient,
    source_id: str,
    reading: dict,
    *,
    owner: str = "usr_ana",
):
    return client.post(
        f"/assets/{source_id}/markup/interpretations/"
        f"{reading['interpretation_id']}/confirm",
        json={"created_by": owner},
    )


def _apply_payload(reading: dict) -> dict:
    interpreted = reading["annotations"][0]
    annotation = {
        "region_description": interpreted["region_description"],
        "change_instruction": interpreted["change_instruction"],
        "target_section": interpreted.get("target_section"),
        "target_ref": interpreted.get("target_ref"),
        "index": interpreted.get("index"),
        "target_component_id": interpreted.get("target_component_id"),
        "target_element_id": interpreted.get("target_element_id"),
        "form_view": interpreted.get("form_view") or "three_quarter",
        "mask_base64": None,
    }
    return {
        "annotations": [annotation],
        "markup_asset_id": reading["markup_asset_id"],
        "confirmed_interpretation_id": reading["interpretation_id"],
        "update_spec": False,
        "created_by": "usr_ana",
    }


def test_interpretation_persists_without_generation_and_confirm_replays(
    confirmation_client,
    monkeypatch,
):
    client, Session = confirmation_client
    generation_calls: list[bool] = []
    monkeypatch.setattr(
        assets_mod,
        "localized_edit",
        lambda *_args, **_kwargs: generation_calls.append(True),
    )
    source_id, _design_id = _source(client)

    reading = _read(client, source_id)

    assert reading["interpretation_status"] == "awaiting_confirmation"
    assert reading["interpretation_id"].startswith("mki_")
    assert generation_calls == []
    with Session() as db:
        record = db.get(
            StudioMarkupInterpretationRecord,
            reading["interpretation_id"],
        )
        assert record is not None and record.status == "awaiting_confirmation"
        assert record.source_asset_id == source_id
        assert record.markup_asset_id == reading["markup_asset_id"]
        assert record.source_design_version == 1
        assert record.source_component_map_state == "unmapped"
        assert record.source_component_map_sha256 is None
        assert db.scalar(select(func.count()).select_from(ImageRun)) == 0

    first = _confirm(client, source_id, reading)
    second = _confirm(client, source_id, reading)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["status"] == "confirmed"
    assert first.json()["annotation"] == {
        "region_description": "the highlighted metal surface",
        "change_instruction": "make only the highlighted metal warmer",
        "impact": "visual_only",
        "form_view": "three_quarter",
        "index": None,
        "mask_base64": None,
        "target_component_id": None,
        "target_element_id": None,
        "target_ref": None,
        "target_section": None,
    }
    assert generation_calls == []


def test_foreign_source_is_rejected_before_markup_provider(
    confirmation_client,
    monkeypatch,
):
    client, _Session = confirmation_client
    source_id, _design_id = _source(client)
    provider_calls: list[bool] = []

    def read_forbidden(*_args, **_kwargs):
        provider_calls.append(True)
        return dict(READING)

    monkeypatch.setattr(assets_mod, "read_markup", read_forbidden)
    response = client.post(f"/assets/{source_id}/markup/read", json={
        "marked_image_base64": base64.b64encode(_marked()).decode(),
        "created_by": "usr_intruder",
    })

    assert response.status_code == 404
    assert response.json()["code"] == (
        "markup_interpretation_project_unavailable"
    )
    assert provider_calls == []


def test_component_map_change_invalidates_interpretation(
    confirmation_client,
):
    client, Session = confirmation_client
    source_id, _design_id = _source(client)
    reading = _read(client, source_id)

    with Session() as db:
        source = db.get(ImageAsset, source_id)
        assert source is not None
        image = bytes(source.image)
        add_revision_component_map(
            db,
            _component_map(source_id, image),
            image_bytes=image,
            parent_asset_id=source.parent_asset_id,
        )
        db.commit()

    response = _confirm(client, source_id, reading)
    assert response.status_code == 409
    assert response.json()["code"] == (
        "stale_markup_interpretation_component_map"
    )


def test_marked_generation_requires_confirmation_and_rejects_substitution(
    confirmation_client,
    monkeypatch,
):
    client, _Session = confirmation_client
    calls: list[dict] = []

    def generate(image_bytes, **kwargs):
        calls.append(kwargs)
        return {
            "image": _png((90, 80, 70)),
            "changed": "highlighted metal",
            "frozen": "everything else",
            "retried": False,
            "drift": 0.01,
            "cached": False,
        }

    monkeypatch.setattr(assets_mod, "localized_edit", generate)
    source_id, _design_id = _source(client)
    reading = _read(client, source_id)
    payload = _apply_payload(reading)

    unconfirmed = client.post(
        f"/assets/{source_id}/markup/apply", json=payload)
    assert unconfirmed.status_code == 409
    assert unconfirmed.json()["code"] == "markup_interpretation_unconfirmed"
    assert calls == []

    assert _confirm(client, source_id, reading).status_code == 200
    substituted = dict(payload)
    substituted["annotations"] = [{
        **substituted["annotations"][0],
        "change_instruction": "replace the center stone",
    }]
    rejected = client.post(
        f"/assets/{source_id}/markup/apply", json=substituted)
    assert rejected.status_code == 422
    assert rejected.json()["code"] == "markup_interpretation_substitution"
    assert calls == []

    created = client.post(f"/assets/{source_id}/markup/apply", json=payload)
    assert created.status_code == 201, created.text
    assert len(calls) == 1


def test_raw_client_mask_cannot_bypass_confirmation(
    confirmation_client,
    monkeypatch,
):
    client, _Session = confirmation_client
    provider_calls: list[bool] = []

    monkeypatch.setattr(
        assets_mod,
        "_trusted_image_agent",
        lambda: provider_calls.append(True),
    )
    monkeypatch.setattr(
        assets_mod,
        "localized_edit",
        lambda *_args, **_kwargs: provider_calls.append(True),
    )
    source_id, _design_id = _source(client)

    response = client.post(f"/assets/{source_id}/markup/apply", json={
        "expected_design_version": 1,
        "created_by": "usr_ana",
        "update_spec": False,
        "annotations": [{
            "region_description": "the highlighted metal surface",
            "change_instruction": "make only the highlighted metal warmer",
            "mask_base64": base64.b64encode(_marked()).decode(),
        }],
    })

    assert response.status_code == 422
    assert response.json()["code"] == (
        "confirmed_markup_interpretation_required"
    )
    assert provider_calls == []


def test_confirmed_markup_without_usable_region_fails_before_provider(
    confirmation_client,
    monkeypatch,
):
    client, _Session = confirmation_client
    provider_calls: list[bool] = []
    monkeypatch.setattr(
        assets_mod,
        "_trusted_image_agent",
        lambda: provider_calls.append(True),
    )
    monkeypatch.setattr(
        assets_mod,
        "localized_edit",
        lambda *_args, **_kwargs: provider_calls.append(True),
    )
    source_id, _design_id = _source(client)
    read_response = client.post(f"/assets/{source_id}/markup/read", json={
        # The provider seam reports an interpretation, but the persisted
        # canvas is pixel-identical and therefore has no authorized region.
        "marked_image_base64": base64.b64encode(_png()).decode(),
        "created_by": "usr_ana",
    })
    assert read_response.status_code == 200, read_response.text
    reading = read_response.json()
    assert _confirm(client, source_id, reading).status_code == 200

    response = client.post(
        f"/assets/{source_id}/markup/apply",
        json={**_apply_payload(reading), "expected_design_version": 1},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "confirmed_markup_mask_required"
    assert provider_calls == []


def test_confirmed_visual_only_markup_keeps_saved_region_localization(
    confirmation_client,
    monkeypatch,
):
    client, _Session = confirmation_client
    executions: list[dict] = []

    class Provider:
        def execute(self, plan, route, prompt, *, source_image, mask_bytes):
            executions.append({
                "plan": plan,
                "prompt": prompt,
                "mask_bytes": mask_bytes,
            })
            return ProviderImage(image_bytes=_png((90, 80, 70)))

    class PassingEvaluator:
        def evaluate(self, plan, candidate, *, source_image, mask_bytes):
            return ImageQualityReport(
                verdict=QualityVerdict.PASS,
                checks=(QualityCheck(
                    code="outside_mask_drift",
                    passed=True,
                    severity=CheckSeverity.HARD,
                    message="unmarked pixels stayed fixed",
                    evidence={"drift": 0.01},
                ),),
                score=99,
            )

    monkeypatch.setattr(
        assets_mod,
        "_trusted_image_agent",
        lambda: JewelryImageAgent(Provider(), PassingEvaluator()),
    )
    source_id, _design_id = _source(client)
    reading = _read(client, source_id)
    assert _confirm(client, source_id, reading).status_code == 200
    payload = {
        **_apply_payload(reading),
        "expected_design_version": 1,
    }

    response = client.post(f"/assets/{source_id}/markup/apply", json=payload)

    assert response.status_code == 201, response.text
    assert len(executions) == 1
    execution = executions[0]
    plan = execution["plan"]
    assert plan.operation is ImageOperation.LOCAL_EDIT
    assert plan.region_description == "the highlighted metal surface"
    assert plan.mask_hash is not None
    assert plan.normalized_intent["localization"]["mode"] == (
        "persisted_designer_markup"
    )
    assert execution["mask_bytes"] is not None
    assert "MASK INPUT ORDER" in execution["prompt"]
    assert "only its magenta-tinted" in execution["prompt"]
    assert response.json()["design_version"] == 1


def test_confirmation_rejects_cross_owner_project_stale_and_tampered_evidence(
    confirmation_client,
    monkeypatch,
):
    client, Session = confirmation_client
    monkeypatch.setattr(
        assets_mod,
        "localized_edit",
        lambda *_args, **_kwargs: pytest.fail("rejected evidence must not render"),
    )
    source_id, design_id = _source(client)
    other_source_id, _other_design_id = _source(client)
    reading = _read(client, source_id)

    cross_owner = _confirm(client, source_id, reading, owner="usr_intruder")
    assert cross_owner.status_code == 404
    assert cross_owner.json()["code"] == "markup_interpretation_unavailable"

    cross_project = client.post(
        f"/assets/{other_source_id}/markup/apply",
        json={**_apply_payload(reading), "markup_asset_id": None},
    )
    assert cross_project.status_code == 409
    assert cross_project.json()["code"] == "markup_interpretation_project_mismatch"

    with Session() as db:
        v1 = db.get(DesignVersion, (design_id, 1))
        assert v1 is not None
        db.add(DesignVersion(
            design_id=design_id,
            version=2,
            spec=v1.spec,
            created_by="usr_ana",
        ))
        db.commit()
    stale = _confirm(client, source_id, reading)
    assert stale.status_code == 409
    assert stale.json()["code"] == "stale_markup_interpretation_spec"

    fresh_source_id, _fresh_design_id = _source(client)
    fresh = _read(client, fresh_source_id)
    assert _confirm(client, fresh_source_id, fresh).status_code == 200
    with Session() as db:
        db.execute(
            update(ImageAsset)
            .where(ImageAsset.id == fresh["markup_asset_id"])
            .values(image=_png((1, 2, 3)))
        )
        db.commit()
    tampered = client.post(
        f"/assets/{fresh_source_id}/markup/apply",
        json=_apply_payload(fresh),
    )
    assert tampered.status_code == 409
    assert tampered.json()["code"] == "markup_interpretation_markup_tampered"

    source_tamper_id, _source_tamper_design_id = _source(client)
    source_tamper = _read(client, source_tamper_id)
    assert _confirm(client, source_tamper_id, source_tamper).status_code == 200
    with Session() as db:
        db.execute(
            update(ImageAsset)
            .where(ImageAsset.id == source_tamper_id)
            .values(image=_png((4, 5, 6)))
        )
        db.commit()
    stale_source = client.post(
        f"/assets/{source_tamper_id}/markup/apply",
        json=_apply_payload(source_tamper),
    )
    assert stale_source.status_code == 409
    assert stale_source.json()["code"] == "stale_markup_interpretation_source"


def test_expired_confirmation_cannot_authorize_generation(
    confirmation_client,
):
    client, Session = confirmation_client
    source_id, _design_id = _source(client)
    reading = _read(client, source_id)
    with Session() as db:
        db.execute(
            update(StudioMarkupInterpretationRecord)
            .where(
                StudioMarkupInterpretationRecord.id
                == reading["interpretation_id"]
            )
            .values(expires_at=utcnow() - timedelta(seconds=1))
        )
        db.commit()

    expired = _confirm(client, source_id, reading)
    assert expired.status_code == 410
    assert expired.json()["code"] == "markup_interpretation_expired"

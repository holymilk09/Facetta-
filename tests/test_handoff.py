"""Factory handoff: DXF export, discussion threads, photo endpoints."""

import base64
import copy
import hashlib
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from facetta.db import Base, get_db
import facetta.api.specs as specs_mod
from facetta.dxf import svg_to_dxf
from facetta.image_identity import spec_visual_hash
from facetta.image_agent import vision as vision_module
from facetta.main import app
from facetta.spec import Spec


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False)

    def override():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_dxf_converts_all_sheet_entity_kinds(example_spec):
    from facetta.spec import Spec
    from facetta.svg_sheet import render_sheet

    dxf = svg_to_dxf(render_sheet(Spec.model_validate(example_spec)))
    assert dxf.startswith("0\nSECTION")
    assert dxf.rstrip().endswith("EOF")
    assert "CIRCLE" in dxf          # hoop, prong tips
    assert "POLYLINE" in dxf        # stone outline, capsules
    assert "ANNOTATION" in dxf      # dimension/witness layer
    assert "%%c 16.9 mm" in dxf     # diameter symbol translated for CAD text
    assert svg_to_dxf(render_sheet(Spec.model_validate(example_spec))) == dxf


def test_dxf_endpoints(client, example_spec):
    stateless = client.post("/specs/sheet.dxf", json=example_spec)
    assert stateless.status_code == 200
    assert stateless.headers["content-type"].startswith("application/dxf")
    assert ".dxf" in stateless.headers["content-disposition"]

    stored = client.post("/designs", json={"created_by": "usr_ana",
                                           "spec": example_spec}).json()
    r = client.get(f"/designs/{stored['design_id']}/versions/1/sheet.dxf")
    assert r.status_code == 200
    assert "ENTITIES" in r.text


def test_design_discussion_thread(client, example_spec):
    stored = client.post("/designs", json={"created_by": "usr_ana",
                                           "spec": example_spec}).json()
    design_id = stored["design_id"]
    assert client.get(f"/designs/{design_id}/messages").json()["messages"] == []

    m1 = client.post(f"/designs/{design_id}/messages",
                     json={"author": "usr_ana", "body": "Gallery down 0.5 mm?"})
    assert m1.status_code == 201
    m2 = client.post(f"/designs/{design_id}/messages",
                     json={"author": "usr_wei", "author_label": "Golden Lotus Mfg",
                           "body": "Yes — reflected in v2.", "version": 2})
    assert m2.status_code == 201
    thread = client.get(f"/designs/{design_id}/messages").json()["messages"]
    assert [m["author"] for m in thread] == ["usr_ana", "usr_wei"]
    assert thread[1]["author_label"] == "Golden Lotus Mfg"
    assert thread[1]["version"] == 2

    missing = client.post("/designs/dsn_nope/messages",
                          json={"author": "x", "body": "y"})
    assert missing.status_code == 404


def test_designs_list_carries_search_fields(client, example_spec):
    client.post("/designs", json={"created_by": "usr_ana", "spec": example_spec,
                                  "collection": "Client — Sarah K"})
    listing = client.get("/designs").json()["designs"]
    assert listing[0]["jewelry_type"] == "ring"
    assert listing[0]["template"] == "solitaire_prong"
    assert "sapphire" in listing[0]["summary"]


def test_from_photo_without_key_returns_503(client, monkeypatch):
    monkeypatch.setattr(
        vision_module, "env_value", lambda _key, default=None: default,
    )
    r = client.post("/specs/from-photo", json={"image_base64": "aGk=",
                                               "media_type": "image/jpeg"})
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert detail == (
        "reference understanding is temporarily unavailable; try again"
    )
    assert "XAI" not in detail
    assert "OPENAI" not in detail


def test_from_photo_rejects_invalid_base64(client, monkeypatch):
    monkeypatch.setenv("XAI_KEY", "configured-for-unit-test")
    r = client.post("/specs/from-photo", json={"image_base64": "not-base64!",
                                               "media_type": "image/jpeg"})
    assert r.status_code == 422
    assert "valid base64" in r.json()["detail"]


def test_from_plate_returns_rich_draft_and_uncertainty(client, monkeypatch,
                                                       example_spec):
    monkeypatch.setattr(specs_mod, "read_design_plate", lambda image, **kwargs: {
        "jewelry_type": "ring", "stones": [{"qty": 1, "type": "emerald square"},
                                              {"qty": 4, "type": "diamond marquise"}],
        "metal": "18k yellow gold", "assembly": "four prongs and shoulders",
        "measurements": [], "hand_written": [], "source": "plate",
    })
    monkeypatch.setattr(specs_mod.plate_spec_layer, "compile_plate_spec",
                        lambda read, **kwargs: (
                            Spec.model_validate(example_spec),
                            ["ring size requires confirmation"],
                        ))
    r = client.post("/specs/from-plate", json={
        "image_base64": base64.b64encode(b"plate").decode(),
        "created_by": "usr_ana",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provenance"] == "grok_vision_hand_plate_draft"
    assert body["requires_designer_confirmation"] is True
    assert body["uncertainties"] == ["ring size requires confirmation"]
    assert body["spec"]["template"] == "solitaire_prong"


def test_from_plate_can_run_blind_independent_component_audit(
    client, monkeypatch, example_spec,
):
    raw = copy.deepcopy(example_spec)
    raw["source_component_coverage"] = {
        "source_kind": "designer_plate",
        "components": [{
            "component_id": "stone.center",
            "source_view": "plate_composite",
            "source_description": "Oval center stone.",
            "source_confidence": 0.9,
            "canonical_spec_paths": ["stone"],
        }],
    }
    draft = Spec.model_validate(raw)
    audited_raw = draft.model_dump(mode="json")
    audited_raw["source_component_coverage"]["components"][0][
        "independent_audit"] = {
            "kind": "independent_component_audit",
            "verdict": "pass",
            "auditor": "skeptical-source-component-audit.v1",
            "source_view": "plate_composite",
            "observed_description": (
                "The blind inventory and exact center-stone mapping agree."
            ),
            "evidence_sha256": "a" * 64,
        }
    audited = Spec.model_validate(audited_raw).source_component_coverage

    monkeypatch.setattr(specs_mod, "read_design_plate", lambda image, **kwargs: {
        "jewelry_type": "ring",
        "stones": [{"qty": 1, "type": "oval sapphire"}],
        "metal": "18k yellow gold",
        "assembly": "four-prong ring",
    })
    monkeypatch.setattr(
        specs_mod.plate_spec_layer,
        "compile_plate_spec",
        lambda read, **kwargs: (
            draft,
            ["INDEPENDENT SOURCE-COVERAGE AUDIT REQUIRED before factory release"],
        ),
    )
    monkeypatch.setattr(
        specs_mod,
        "audit_source_component_coverage",
        lambda image, coverage, *, spec: audited.model_copy(update={
            "audited_spec_visual_hash": spec_visual_hash(spec),
        }),
    )

    response = client.post("/specs/from-plate", json={
        "image_base64": base64.b64encode(b"plate").decode(),
        "created_by": "usr_ana",
        "run_independent_audit": True,
    })

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source_coverage_audit"] == {
        "status": "pass",
        "blocker_count": 0,
    }
    assert body["uncertainties"] == []
    audit = body["spec"]["source_component_coverage"]["components"][0][
        "independent_audit"]
    assert audit["verdict"] == "pass"
    assert audit["evidence_sha256"] == "a" * 64


def test_from_plate_returns_necklace_draft_bound_to_exact_source(
    client,
    monkeypatch,
):
    monkeypatch.setattr(specs_mod, "read_design_plate", lambda image, **kwargs: {
        "jewelry_type": "necklace",
        "stones": [
            {"qty": 1, "type": "emerald pear shape"},
            {"qty": 4, "type": "emerald pear shape"},
        ],
        "metal": "white gold or platinum",
        "assembly": (
            "collar necklace with articulated geometric diamond links and "
            "multiple pear emerald pendants"
        ),
        "measurements": [{
            "label": "3.25",
            "raw": "3.25",
            "status": "ambiguous",
        }],
    })
    source = b"necklace-plate"

    response = client.post("/specs/from-plate", json={
        "image_base64": base64.b64encode(source).decode(),
        "created_by": "usr_necklace_designer",
        "run_independent_audit": False,
    })

    assert response.status_code == 200, response.text
    body = response.json()
    spec = body["spec"]
    assert spec["jewelry_type"] == "necklace"
    assert spec["template"] == "cluster_pendant"
    definition = spec["design_form"]["elements"][0]["definition"]
    digest = hashlib.sha256(source).hexdigest()
    assert definition == {
        "kind": "visual_reference_only",
        "asset_id": f"plate:{digest[:16]}",
        "asset_sha256": digest,
    }
    assert spec["stone"]["cut"] == "pear"
    assert "3.25" in spec["notes_to_factory"]
    unresolved = {
        item["component_id"]
        for item in spec["source_component_coverage"]["components"]
        if item["unresolved_reason"] is not None
    }
    assert unresolved >= {"setting.primary", "metal.body", "assembly.chain"}


def test_restage_request(client):
    r = client.post("/specs/restage-request",
                    json={"jewelry_type": "ring", "lighting": "natural",
                          "worn_on": "finger"})
    assert r.status_code == 200
    body = r.json()
    assert "EXACTLY as it is" in body["instruction"]
    assert "ring finger" in body["instruction"]

    bad = client.post("/specs/restage-request",
                      json={"jewelry_type": "necklace", "worn_on": "finger"})
    assert bad.status_code == 422
    assert bad.json()["valid_options"] == ["product", "neck"]

"""Studio beta routes authorize from a first-party principal, not body labels."""

from __future__ import annotations

import hashlib
import json
import time
from uuid import UUID, uuid4

from cryptography.hazmat.primitives.asymmetric import ec, rsa
import jwt
from jwt import PyJWKClient, algorithms
from jwt.exceptions import PyJWKClientConnectionError
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from conftest import HALO_SPEC
from facetta.db import (
    ApprovalChecklist, ApprovalResponse, Base, Design, DesignFamily,
    FeedbackEvent, ImageAsset, ImageRun, Project, get_db, utcnow,
)
from facetta.auth import validate_auth_configuration
from facetta.main import app
from facetta.studio_visual_candidates import store_studio_visual_candidate


OWNER_TOKEN = "owner-session-token-1234"
OTHER_TOKEN = "other-session-token-1234"
SUPABASE_URL = "https://facetta-test.supabase.co"


def _supabase_access_token(
    private_key,
    subject: str,
    *,
    algorithm: str = "RS256",
    kid: str = "facetta-test-key",
    **overrides,
) -> str:
    now = int(time.time())
    claims = {
        "iss": f"{SUPABASE_URL}/auth/v1",
        "aud": "authenticated",
        "exp": now + 600,
        "iat": now,
        "sub": subject,
        "role": "authenticated",
        "session_id": str(uuid4()),
        "is_anonymous": False,
    }
    claims.update(overrides)
    claims = {key: value for key, value in claims.items() if value is not None}
    return jwt.encode(
        claims,
        private_key,
        algorithm=algorithm,
        headers={"kid": kid},
    )


def _public_jwk(public_key, algorithm: str, kid: str) -> dict:
    converter = (
        algorithms.RSAAlgorithm if algorithm == "RS256"
        else algorithms.ECAlgorithm
    )
    jwk = converter.to_jwk(public_key, as_dict=True)
    jwk.update({"alg": algorithm, "kid": kid, "use": "sig"})
    return jwk


def _mock_jwks(monkeypatch, keys: list[dict]) -> None:
    client = PyJWKClient("https://jwks.invalid", cache_jwk_set=False)
    client.fetch_data = lambda: {"keys": keys}
    monkeypatch.setattr("facetta.auth._jwks_client", lambda _issuer: client)


@pytest.fixture
def auth_client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    now = utcnow()
    with Session() as db:
        root = ImageAsset(
            id="ast_auth_root",
            root_id="ast_auth_root",
            parent_asset_id=None,
            design_id=None,
            design_version=None,
            capability="CREATIVE_RENDER",
            instruction="Authenticated concept",
            image=b"auth-image",
            media_type="image/png",
            created_by="usr_owner",
            created_at=now,
        )
        orphan = ImageAsset(
            id="ast_orphan",
            root_id="ast_orphan",
            parent_asset_id=None,
            design_id=None,
            design_version=None,
            capability="CREATIVE_RENDER",
            instruction="Legacy orphan",
            image=b"orphan-image",
            media_type="image/png",
            created_by="usr_owner",
            created_at=now,
        )
        ownerless = ImageAsset(
            id="ast_ownerless",
            root_id="ast_ownerless",
            parent_asset_id=None,
            design_id=None,
            design_version=None,
            capability="CREATIVE_RENDER",
            instruction="Ownerless legacy asset",
            image=b"ownerless-image",
            media_type="image/png",
            created_by="",
            created_at=now,
        )
        other_orphan = ImageAsset(
            id="ast_other_orphan",
            root_id="ast_other_orphan",
            parent_asset_id=None,
            design_id=None,
            design_version=None,
            capability="CREATIVE_RENDER",
            instruction="Other private instruction",
            image=b"other-image",
            media_type="image/png",
            created_by="usr_other",
            created_at=now,
        )
        approval_asset = ImageAsset(
            id="ast_auth_approval",
            root_id="ast_auth_approval",
            parent_asset_id=None,
            design_id=None,
            design_version=None,
            capability="JEWELRY_RENDER",
            instruction="Approval actor fixture",
            image=b"approval-image",
            media_type="image/png",
            created_by="usr_owner",
            created_at=now,
        )
        project = Project(
            root_id=root.id,
            owner="usr_owner",
            title="Private project",
            tags=[],
            selected_candidate_asset_id=root.id,
            created_at=now,
            updated_at=now,
        )
        db.add_all([
            root, orphan, ownerless, other_orphan, approval_asset, project,
        ])
        db.add_all([
            Design(
                id="dsn_owner", created_by="usr_owner", created_at=now,
                collection=None,
            ),
            Design(
                id="dsn_other", created_by="usr_other", created_at=now,
                collection=None,
            ),
            FeedbackEvent(
                asset_id=root.id, action="accepted", created_by="usr_owner",
            ),
            FeedbackEvent(
                asset_id=other_orphan.id, action="rejected",
                created_by="usr_other",
            ),
        ])
        db.add(ImageRun(
            id="run_owner",
            project_root_id=root.id,
            source_asset_id=root.id,
            operation="CREATIVE_GENERATE",
            normalized_intent={},
            prompt_version="auth-test.v1",
            variant=0,
            status="review_required",
            created_by="usr_owner",
            created_at=now,
        ))
        db.add_all([
            DesignFamily(
                id="fam_owner", owner="usr_owner", title="Owner family",
                created_at=now, updated_at=now,
            ),
            DesignFamily(
                id="fam_other", owner="usr_other", title="Other family",
                created_at=now, updated_at=now,
            ),
        ])
        db.commit()

    def override_db():
        with Session() as db:
            yield db

    monkeypatch.setenv("FACETTA_AUTH_MODE", "opaque")
    monkeypatch.setenv("FACETTA_AUTH_PRINCIPALS_JSON", json.dumps({
        OWNER_TOKEN: "usr_owner",
        OTHER_TOKEN: "usr_other",
    }))
    app.dependency_overrides[get_db] = override_db
    try:
        yield TestClient(app), Session
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize(
    ("header", "code"),
    [
        (None, "authentication_required"),
        ("Bearer invalid-session-token", "invalid_authentication_token"),
    ],
)
def test_project_routes_fail_closed_for_missing_or_invalid_token(
    auth_client,
    header: str | None,
    code: str,
):
    client, _Session = auth_client
    headers = {} if header is None else {"Authorization": header}
    response = client.get("/projects/ast_auth_root", headers=headers)
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == code


def test_cross_owner_project_read_is_denied(auth_client):
    client, _Session = auth_client
    response = client.get(
        "/projects/ast_auth_root",
        headers={"Authorization": f"Bearer {OTHER_TOKEN}"},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "project_access_denied"


def test_studio_routes_share_the_same_required_principal_boundary(auth_client):
    client, _Session = auth_client
    for url in (
        "/studio/jobs?owner=usr_owner",
        "/studio/families",
        "/assets/ast_auth_root/image",
        "/image-runs/run_owner",
    ):
        response = client.get(url)
        assert response.status_code == 401
        assert response.json()["detail"]["code"] == "authentication_required"


def test_factory_capability_is_server_sourced_exact_principal_and_fail_closed(
    auth_client, monkeypatch,
):
    client, _Session = auth_client
    owner = {"Authorization": f"Bearer {OWNER_TOKEN}"}
    other = {"Authorization": f"Bearer {OTHER_TOKEN}"}
    monkeypatch.delenv("FACETTA_FACTORY_ENTITLED_PRINCIPALS_JSON", raising=False)

    disabled = client.get("/studio/capabilities", headers=owner)
    assert disabled.status_code == 200
    assert disabled.json() == {
        "factory_review": {"enabled": False, "scope": "principal"},
        "workspace_entitlements_available": False,
    }

    monkeypatch.setenv(
        "FACETTA_FACTORY_ENTITLED_PRINCIPALS_JSON",
        json.dumps(["usr_owner"]),
    )
    assert client.get("/studio/capabilities", headers=owner).json()[
        "factory_review"
    ]["enabled"] is True
    assert client.get("/studio/capabilities", headers=other).json()[
        "factory_review"
    ]["enabled"] is False


def test_factory_pack_routes_enforce_entitlement_before_pack_lookup(
    auth_client, monkeypatch,
):
    client, _Session = auth_client
    owner = {"Authorization": f"Bearer {OWNER_TOKEN}"}
    monkeypatch.setenv("FACETTA_FACTORY_ENTITLED_PRINCIPALS_JSON", "[]")

    response = client.get(
        "/projects/ast_auth_root/factory-pack", headers=owner,
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "factory_entitlement_required"

    job = client.post("/studio/jobs", headers=owner, json={
        "owner": "usr_owner",
        "action_id": "factory",
        "lane": "trusted_structural",
        "active_design_id": "ast_auth_root",
        "source_revision_id": "ast_auth_root",
        "requested_outputs": 1,
        "credits_per_output": 28,
    })
    assert job.status_code == 403
    assert job.json()["detail"]["code"] == "factory_entitlement_required"


def test_owner_and_created_by_fields_cannot_spoof_principal(auth_client):
    client, _Session = auth_client
    response = client.post(
        "/projects/ast_auth_root/creative-candidates/ast_auth_root/select",
        headers={"Authorization": f"Bearer {OWNER_TOKEN}"},
        json={"created_by": "usr_other"},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "principal_actor_mismatch"
    confirm = client.post(
        "/projects/ast_auth_root/creative-candidates/ast_auth_root/confirm-design",
        headers={"Authorization": f"Bearer {OWNER_TOKEN}"},
        json={"created_by": "usr_other"},
    )
    assert confirm.status_code == 403
    assert confirm.json()["detail"]["code"] == "principal_actor_mismatch"

    markup = client.post(
        "/assets/ast_auth_root/markup/read",
        headers={"Authorization": f"Bearer {OWNER_TOKEN}"},
        json={
            "marked_image_base64": "aW1hZ2U=",
            "created_by": "usr_other",
        },
    )
    assert markup.status_code == 403
    assert markup.json()["detail"]["code"] == "principal_actor_mismatch"


def test_approval_audit_actor_is_the_authenticated_principal(auth_client):
    client, Session = auth_client
    owner = {"Authorization": f"Bearer {OWNER_TOKEN}"}
    spoofed_create = client.post(
        "/assets/ast_auth_root/checklist",
        headers=owner,
        json={"created_by": "usr_other"},
    )
    assert spoofed_create.status_code == 403
    assert spoofed_create.json()["detail"]["code"] == "principal_actor_mismatch"
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(ApprovalChecklist)) == 0
        db.add(ApprovalChecklist(
            id="chk_auth_actor",
            asset_id="ast_auth_root",
            mode="explicit_pin",
            items=[{
                "key": "stone", "label": "Stone", "fact": "round",
                "section": "center_stone",
            }],
            created_by="usr_owner",
        ))
        db.commit()

    canonical_create = client.post(
        "/assets/ast_auth_approval/checklist",
        headers=owner,
        json={"spec": HALO_SPEC, "mode": "explicit_pin"},
    )
    assert canonical_create.status_code == 201, canonical_create.text
    with Session() as db:
        checklist = db.get(
            ApprovalChecklist, canonical_create.json()["checklist_id"],
        )
        assert checklist is not None
        assert checklist.created_by == "usr_owner"

    spoofed_response = client.post(
        "/assets/ast_auth_root/checklist/respond",
        headers=owner,
        json={
            "item_key": "stone", "approved": True,
            "created_by": "usr_other",
        },
    )
    assert spoofed_response.status_code == 403
    assert spoofed_response.json()["detail"]["code"] == "principal_actor_mismatch"
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(ApprovalResponse)) == 0

    canonical = client.post(
        "/assets/ast_auth_root/checklist/respond",
        headers=owner,
        json={"item_key": "stone", "approved": True},
    )
    assert canonical.status_code == 201, canonical.text
    with Session() as db:
        response = db.scalar(select(ApprovalResponse))
        assert response is not None
        assert response.created_by == "usr_owner"


def test_authenticated_owner_can_read_own_project(auth_client):
    client, _Session = auth_client
    response = client.get(
        "/projects/ast_auth_root",
        headers={"Authorization": f"Bearer {OWNER_TOKEN}"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["owner"] == "usr_owner"


def test_production_markup_cannot_skip_temporary_preview(
    auth_client,
    monkeypatch,
):
    client, _Session = auth_client
    monkeypatch.setenv("FACETTA_ENV", "production")
    response = client.post(
        "/assets/ast_auth_root/markup/apply",
        headers={"Authorization": f"Bearer {OWNER_TOKEN}"},
        json={
            "annotations": [{
                "region_description": "center stone",
                "change_instruction": "make it blue",
            }],
            "created_by": "usr_owner",
            "preview_only": False,
        },
    )
    assert response.status_code == 409
    assert response.json()["code"] == "studio_preview_required"


def test_supabase_jwt_maps_uuid_subject_to_canonical_owner(
    auth_client,
    monkeypatch,
):
    client, Session = auth_client
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = str(uuid4())
    canonical_subject = UUID(subject).hex
    with Session() as db:
        project = db.get(Project, "ast_auth_root")
        assert project is not None
        project.owner = canonical_subject
        db.commit()
    monkeypatch.setenv("FACETTA_AUTH_MODE", "supabase")
    monkeypatch.setenv("FACETTA_SUPABASE_URL", SUPABASE_URL)
    monkeypatch.setenv("FACETTA_SUPABASE_AUDIENCE", "authenticated")
    monkeypatch.setattr(
        "facetta.auth._supabase_signing_key",
        lambda _token, _issuer: private_key.public_key(),
    )
    token = _supabase_access_token(private_key, subject)
    response = client.get(
        "/projects/ast_auth_root",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["owner"] == canonical_subject
    assert len(canonical_subject) == 32


@pytest.mark.parametrize("algorithm", ["RS256", "ES256"])
def test_supabase_jwt_uses_real_jwks_key_selection(
    auth_client,
    monkeypatch,
    algorithm,
):
    client, Session = auth_client
    private_key = (
        rsa.generate_private_key(public_exponent=65537, key_size=2048)
        if algorithm == "RS256"
        else ec.generate_private_key(ec.SECP256R1())
    )
    subject = str(uuid4())
    canonical_subject = UUID(subject).hex
    with Session() as db:
        project = db.get(Project, "ast_auth_root")
        assert project is not None
        project.owner = canonical_subject
        db.commit()
    monkeypatch.setenv("FACETTA_AUTH_MODE", "supabase")
    monkeypatch.setenv("FACETTA_SUPABASE_URL", SUPABASE_URL)
    _mock_jwks(
        monkeypatch,
        [_public_jwk(private_key.public_key(), algorithm, "current-key")],
    )
    token = _supabase_access_token(
        private_key,
        subject,
        algorithm=algorithm,
        kid="current-key",
    )
    response = client.get(
        "/projects/ast_auth_root",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text


def test_supabase_unknown_kid_is_invalid_but_empty_jwks_is_retryable(
    auth_client,
    monkeypatch,
):
    client, _Session = auth_client
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setenv("FACETTA_AUTH_MODE", "supabase")
    monkeypatch.setenv("FACETTA_SUPABASE_URL", SUPABASE_URL)
    token = _supabase_access_token(private_key, str(uuid4()), kid="unknown")
    _mock_jwks(
        monkeypatch,
        [_public_jwk(private_key.public_key(), "RS256", "known")],
    )
    unknown = client.get(
        "/projects/ast_auth_root",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert unknown.status_code == 401
    assert unknown.json()["detail"]["code"] == "invalid_authentication_token"
    _mock_jwks(monkeypatch, [])
    empty = client.get(
        "/projects/ast_auth_root",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert empty.status_code == 503
    assert empty.json()["detail"]["code"] == (
        "authentication_verifier_unavailable"
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"iss": "https://attacker.example/auth/v1"},
        {"aud": "service_role"},
        {"role": "service_role"},
        {"session_id": None},
        {"session_id": "not-a-uuid"},
        {"is_anonymous": None},
        {"is_anonymous": True},
        {"exp": 1},
        {"nbf": int(time.time()) + 600},
        {"sub": "not-a-uuid"},
    ],
)
def test_supabase_jwt_rejects_untrusted_claims(
    auth_client,
    monkeypatch,
    overrides,
):
    client, _Session = auth_client
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setenv("FACETTA_AUTH_MODE", "supabase")
    monkeypatch.setenv("FACETTA_SUPABASE_URL", SUPABASE_URL)
    monkeypatch.setattr(
        "facetta.auth._supabase_signing_key",
        lambda _token, _issuer: private_key.public_key(),
    )
    token = _supabase_access_token(private_key, str(uuid4()), **overrides)
    response = client.get(
        "/projects/ast_auth_root",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_authentication_token"


def test_supabase_jwt_rejects_wrong_signature(auth_client, monkeypatch):
    client, _Session = auth_client
    signer = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setenv("FACETTA_AUTH_MODE", "supabase")
    monkeypatch.setenv("FACETTA_SUPABASE_URL", SUPABASE_URL)
    monkeypatch.setattr(
        "facetta.auth._supabase_signing_key",
        lambda _token, _issuer: other.public_key(),
    )
    response = client.get(
        "/projects/ast_auth_root",
        headers={
            "Authorization": (
                f"Bearer {_supabase_access_token(signer, str(uuid4()))}"
            ),
        },
    )
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_authentication_token"


def test_supabase_jwks_outage_is_retryable_and_does_not_erase_identity(
    auth_client,
    monkeypatch,
):
    client, _Session = auth_client
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setenv("FACETTA_AUTH_MODE", "supabase")
    monkeypatch.setenv("FACETTA_SUPABASE_URL", SUPABASE_URL)

    def unavailable(_token, _issuer):
        raise PyJWKClientConnectionError("temporary JWKS outage")

    monkeypatch.setattr("facetta.auth._supabase_signing_key", unavailable)
    response = client.get(
        "/projects/ast_auth_root",
        headers={
            "Authorization": (
                f"Bearer {_supabase_access_token(private_key, str(uuid4()))}"
            ),
        },
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == (
        "authentication_verifier_unavailable"
    )


@pytest.mark.parametrize("mode", ["test", "local", "opaque", "required"])
def test_production_rejects_non_supabase_auth_modes(monkeypatch, mode):
    monkeypatch.setenv("FACETTA_ENV", "production")
    monkeypatch.setenv("FACETTA_AUTH_MODE", mode)
    with pytest.raises(RuntimeError, match="production requires"):
        validate_auth_configuration()


def test_production_accepts_complete_supabase_auth_configuration(monkeypatch):
    monkeypatch.setenv("FACETTA_ENV", "production")
    monkeypatch.setenv("FACETTA_AUTH_MODE", "supabase")
    monkeypatch.setenv("FACETTA_SUPABASE_URL", SUPABASE_URL)
    validate_auth_configuration()


def test_application_lifespan_refuses_unsafe_production_mode(monkeypatch):
    monkeypatch.setenv("FACETTA_ENV", "production")
    monkeypatch.setenv("FACETTA_AUTH_MODE", "opaque")
    with pytest.raises(RuntimeError, match="production requires"):
        with TestClient(app):
            pass


@pytest.mark.parametrize("environment", ["prod", "staging", ""])
def test_unknown_or_missing_environment_fails_closed(monkeypatch, environment):
    monkeypatch.setenv("FACETTA_ENV", environment)
    monkeypatch.setenv("FACETTA_AUTH_MODE", "test")
    with pytest.raises(RuntimeError):
        validate_auth_configuration()


@pytest.mark.parametrize("audience", ["", "service_role", "anon"])
def test_supabase_mode_requires_authenticated_audience(monkeypatch, audience):
    monkeypatch.setenv("FACETTA_ENV", "production")
    monkeypatch.setenv("FACETTA_AUTH_MODE", "supabase")
    monkeypatch.setenv("FACETTA_SUPABASE_URL", SUPABASE_URL)
    monkeypatch.setenv("FACETTA_SUPABASE_AUDIENCE", audience)
    if audience == "":
        # Empty env values fall back to the documented default.
        validate_auth_configuration()
    else:
        with pytest.raises(RuntimeError, match="audience=authenticated"):
            validate_auth_configuration()


@pytest.mark.parametrize(
    "url",
    [
        "http://facetta-test.supabase.co",
        "http://localhost:54321",
        "https://facetta-test.supabase.co/auth/v1",
        "https://user@facetta-test.supabase.co",
        "https://facetta-test.supabase.co?redirect=https://attacker.example",
    ],
)
def test_supabase_mode_rejects_untrusted_project_urls(monkeypatch, url):
    monkeypatch.setenv("FACETTA_AUTH_MODE", "supabase")
    monkeypatch.setenv("FACETTA_SUPABASE_URL", url)
    with pytest.raises(RuntimeError, match="valid FACETTA_SUPABASE_URL"):
        validate_auth_configuration()


def test_family_list_and_detail_are_scoped_to_principal(auth_client):
    client, _Session = auth_client
    headers = {"Authorization": f"Bearer {OWNER_TOKEN}"}
    listed = client.get("/studio/families", headers=headers)
    assert listed.status_code == 200, listed.text
    assert [item["family_id"] for item in listed.json()["families"]] == [
        "fam_owner"
    ]
    denied = client.get("/studio/families/fam_other", headers=headers)
    assert denied.status_code == 404
    spoof = client.get(
        "/studio/families", params={"owner": "usr_other"}, headers=headers)
    assert spoof.status_code == 403
    assert spoof.json()["detail"]["code"] == "principal_actor_mismatch"
    jobs = client.get(
        "/studio/jobs", params={"owner": "usr_other"}, headers=headers)
    assert jobs.status_code == 403
    assert jobs.json()["detail"]["code"] == "principal_actor_mismatch"


def test_history_asset_and_visual_candidate_reads_deny_other_principal(
    auth_client,
):
    client, Session = auth_client
    headers = {"Authorization": f"Bearer {OTHER_TOKEN}"}
    history = client.get(
        "/studio/projects/ast_auth_root/history", headers=headers)
    assert history.status_code == 403
    assert history.json()["detail"]["code"] == "project_access_denied"
    asset = client.get("/assets/ast_auth_root/image", headers=headers)
    assert asset.status_code == 403
    assert asset.json()["detail"]["code"] == "asset_access_denied"

    with Session() as db:
        source = db.get(ImageAsset, "ast_auth_root")
        run = db.get(ImageRun, "run_owner")
        assert source is not None and run is not None
        source_hash = hashlib.sha256(bytes(source.image)).hexdigest()
        run.project_root_id = "ast_auth_root"
        run.source_asset_id = "ast_auth_root"
        run.source_hash = source_hash
        run.created_by = "usr_owner"
        db.commit()
        candidate = store_studio_visual_candidate(
            db,
            run_id="run_owner",
            verdict="pass",
            project_root_id="ast_auth_root",
            source_asset_id="ast_auth_root",
            expected_selected_candidate_asset_id="ast_auth_root",
            source_hash=source_hash,
            image_bytes=b"private-preview",
            media_type="image/png",
            requested_change="polish",
            scope="appearance",
            qa={},
            created_by="usr_owner",
        )
    preview = client.get(
        f"/studio/image-runs/{candidate.run_id}/visual-candidates/"
        f"{candidate.candidate_id}/image",
        headers=headers,
    )
    assert preview.status_code == 404


def test_orphan_and_ownerless_assets_fail_closed(auth_client):
    client, _Session = auth_client
    other = {"Authorization": f"Bearer {OTHER_TOKEN}"}
    assert client.get("/assets/ast_orphan/image", headers=other).status_code == 403
    owner = {"Authorization": f"Bearer {OWNER_TOKEN}"}
    assert client.get(
        "/assets/ast_ownerless/image", headers=owner).status_code == 403


def test_trusted_image_run_evidence_denies_other_principal(auth_client):
    client, _Session = auth_client
    response = client.get(
        "/image-runs/run_owner",
        headers={"Authorization": f"Bearer {OTHER_TOKEN}"},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "image_run_access_denied"


def test_catalog_provider_and_candidate_routes_share_canonical_ownership(
    auth_client,
):
    client, _Session = auth_client
    other = {"Authorization": f"Bearer {OTHER_TOKEN}"}
    preview = client.post(
        "/assets/ast_auth_root/catalog/preview",
        headers=other,
        json={
            "component_path": "metal.color",
            "option_id": "rose",
            "expected_design_version": 1,
            "created_by": "usr_other",
        },
    )
    assert preview.status_code == 403
    assert preview.json()["detail"]["code"] == "asset_access_denied"
    spoof = client.post(
        "/assets/ast_auth_root/catalog/preview",
        headers={"Authorization": f"Bearer {OWNER_TOKEN}"},
        json={
            "component_path": "metal.color",
            "option_id": "rose",
            "expected_design_version": 1,
            "created_by": "usr_other",
        },
    )
    assert spoof.status_code == 403
    assert spoof.json()["detail"]["code"] == "principal_actor_mismatch"
    candidate = client.get(
        "/image-runs/run_owner/catalog-candidates/missing/image",
        headers=other,
    )
    assert candidate.status_code == 403
    assert candidate.json()["detail"]["code"] == "image_run_access_denied"


def test_render_actor_design_link_and_insights_are_tenant_scoped(
    auth_client,
    monkeypatch,
):
    client, _Session = auth_client
    headers = {"Authorization": f"Bearer {OWNER_TOKEN}"}
    render_calls: list[str] = []

    def unexpected_render(*_args, **_kwargs):
        render_calls.append("called")
        raise AssertionError("foreign-design render reached the provider")

    monkeypatch.setattr("facetta.api.assets.jewelry_render", unexpected_render)
    spoofed_render = client.post("/assets/render", headers=headers, json={
        "piece_description": "A private solitaire ring",
        "created_by": "usr_other",
    })
    assert spoofed_render.status_code == 403
    assert spoofed_render.json()["detail"]["code"] == (
        "principal_actor_mismatch"
    )
    foreign_design_render = client.post("/assets/render", headers=headers, json={
        "piece_description": "A private solitaire ring",
        "created_by": "usr_owner",
        "design_id": "dsn_other",
    })
    assert foreign_design_render.status_code == 403
    assert foreign_design_render.json()["detail"]["code"] == (
        "design_access_denied"
    )
    assert render_calls == []

    link = client.patch(
        "/assets/ast_auth_root/link-design",
        headers=headers,
        json={"design_id": "dsn_other"},
    )
    assert link.status_code == 403
    assert link.json()["detail"]["code"] == "design_access_denied"

    stats = client.get("/assets/insights/instruction-stats", headers=headers)
    assert stats.status_code == 200, stats.text
    assert stats.json()["events"] == 1
    assert stats.json()["by_capability"]["CREATIVE_RENDER"]["accepted"] == 1
    assert stats.json()["by_capability"]["CREATIVE_RENDER"]["rejected"] == 0


def test_feedback_actor_spoof_is_rejected_without_append(auth_client):
    client, Session = auth_client
    response = client.post(
        "/assets/ast_auth_root/feedback",
        headers={"Authorization": f"Bearer {OWNER_TOKEN}"},
        json={"action": "accepted", "created_by": "usr_other"},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "principal_actor_mismatch"
    with Session() as db:
        events = list(db.query(FeedbackEvent).filter(
            FeedbackEvent.asset_id == "ast_auth_root"
        ))
        assert len(events) == 1

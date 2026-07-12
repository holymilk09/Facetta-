"""The Internet-facing beta mounts only the authenticated Studio surface."""

from fastapi.testclient import TestClient

from facetta.main import create_app


def test_production_hides_legacy_admin_and_protects_spec_adapters(monkeypatch):
    monkeypatch.setenv("FACETTA_ENV", "production")
    monkeypatch.setenv("FACETTA_AUTH_MODE", "supabase")
    monkeypatch.setenv(
        "FACETTA_SUPABASE_URL", "https://facetta-test.supabase.co",
    )
    production_app = create_app()
    assert production_app.openapi_url is None
    assert production_app.docs_url is None
    with TestClient(production_app) as client:
        assert client.get("/health").status_code == 200
        for method, path in (
            ("post", "/specs/from-photo"),
            ("post", "/specs/from-plate"),
            ("post", "/specs/validate"),
            ("post", "/specs/catalog/select"),
            ("post", "/specs/stone/select"),
            ("post", "/specs/sheet.svg"),
            ("post", "/specs/source-coverage/resolve"),
            ("post", "/specs/source-coverage/confirm"),
            ("get", "/projects/missing"),
            ("get", "/studio/families"),
            ("post", "/assets/known/markup/read"),
            ("post", "/assets/known/markup/apply"),
            ("get", "/assets/known/image"),
            ("post", "/assets/known/catalog/preview"),
        ):
            protected = (
                client.post(path, json={}) if method == "post"
                else client.get(path)
            )
            assert protected.status_code == 401
            assert protected.json()["detail"]["code"] == "authentication_required"
        for method, path in (
            ("get", "/designs"),
            ("get", "/library"),
            ("get", "/users"),
            ("get", "/stones"),
            ("post", "/designs/known/versions/1/share"),
            ("post", "/specs/build"),
            ("post", "/specs/jewelry-render"),
            ("post", "/assets/known/catalog/apply"),
            ("post", "/assets/render"),
            ("post", "/assets/known/views"),
            ("post", "/assets/known/localized-edit"),
            ("post", "/assets/known/global-restyle"),
            ("post", "/assets/known/video"),
            ("post", "/assets/known/pin"),
            ("post", "/assets/known/technical-drawing"),
        ):
            hidden = (
                client.post(path, json={}) if method == "post"
                else client.get(path)
            )
            assert hidden.status_code == 404


def test_production_rejects_wildcard_cors(monkeypatch):
    monkeypatch.setenv("FACETTA_ENV", "production")
    monkeypatch.setenv("FACETTA_AUTH_MODE", "supabase")
    monkeypatch.setenv(
        "FACETTA_SUPABASE_URL", "https://facetta-test.supabase.co",
    )
    monkeypatch.setenv("FACETTA_CORS_ORIGINS", "*")
    try:
        create_app()
    except RuntimeError as exc:
        assert "cannot use '*'" in str(exc)
    else:  # pragma: no cover - explicit fail-closed contract
        raise AssertionError("production wildcard CORS must fail closed")

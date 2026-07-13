"""The Internet-facing beta mounts only the authenticated Studio surface."""

from fastapi.testclient import TestClient

from facetta.main import create_app


def _operations(method: str, *paths: str) -> set[tuple[str, str]]:
    return {(method, path) for path in paths}


EXPECTED_PRODUCTION_OPERATIONS = (
    _operations("GET", "/health")
    | _operations(
        "GET",
        "/vocabulary/components/{component_path}",
        "/vocabulary/findings",
        "/vocabulary/stones",
        "/vocabulary/stones/{stone_id}/options",
        "/assets/{asset_id}/image",
        "/assets/{asset_id}/studio-component-targeting",
        "/assets/{asset_id}/checklist",
        "/assets/{active_asset_id}/catalog/previews",
        "/image-runs/{run_id}/catalog-candidates/{candidate_id}/image",
        "/image-runs/{run_id}/candidates/{candidate_id}/image",
        "/projects/{root_id}",
        "/projects/{project_id}/factory-pack",
        "/projects/{project_id}/factory-pack.zip",
        "/studio/jobs",
        "/studio/jobs/{job_id}",
        "/studio/capabilities",
        "/studio/projects/{project_root_id}/visual-candidates",
        "/studio/projects/{project_root_id}/markup-candidates",
        "/studio/markup-candidates/{run_id}/{candidate_id}/image",
        "/studio/view-candidates",
        "/studio/view-candidates/{run_id}/{candidate_id}/image",
        "/studio/presentation-candidates",
        "/studio/image-runs/{run_id}/visual-candidates/{candidate_id}/image",
        "/studio/image-runs/{run_id}/presentation-candidates/{candidate_id}/image",
        "/studio/projects/{project_root_id}/history",
        "/studio/families",
        "/studio/families/{family_id}",
    )
    | _operations(
        "POST",
        "/assets/{asset_id}/markup/read",
        "/assets/{asset_id}/markup/apply",
        "/assets/{asset_id}/studio-component-map",
        "/assets/{asset_id}/checklist",
        "/assets/{asset_id}/checklist/respond",
        "/assets/{active_asset_id}/catalog/preview",
        "/image-runs/{run_id}/catalog-candidates/{candidate_id}/accept",
        "/image-runs/{run_id}/catalog-candidates/{candidate_id}/save-as-variation",
        "/image-runs/{run_id}/candidates/{candidate_id}/accept",
        "/image-runs/{run_id}/candidates/{candidate_id}/discard",
        "/projects/from-prompt",
        "/projects/from-drawing",
        "/projects/{project_id}/creative-directions/commit",
        "/projects/{project_id}/creative-candidates/{candidate_id}/confirm-design",
        "/projects/{project_id}/creative-candidates/{candidate_id}/promote",
        "/projects/{root_id}/marketing-pack",
        "/projects/{root_id}/line-art",
        "/projects/{project_id}/factory-pack",
        "/studio/projects/import-confirmed",
        "/studio/jobs",
        "/studio/jobs/{job_id}/cancel",
        "/studio/projects/{root_id}/beauty-render",
        "/studio/projects/{root_id}/product-photo",
        "/studio/projects/{project_id}/visual-previews",
        "/studio/image-runs/{run_id}/visual-candidates/{candidate_id}/accept",
        "/studio/image-runs/{run_id}/visual-candidates/{candidate_id}/discard",
        "/studio/image-runs/{run_id}/visual-candidates/{candidate_id}/save-as-variation",
        "/studio/markup-candidates/{run_id}/{candidate_id}/accept",
        "/studio/markup-candidates/{run_id}/{candidate_id}/discard",
        "/studio/markup-candidates/{run_id}/{candidate_id}/save-as-variation",
        "/studio/projects/{project_id}/presentation-previews",
        "/studio/view-candidates/{run_id}/{candidate_id}/accept",
        "/studio/view-candidates/{run_id}/{candidate_id}/discard",
        "/studio/image-runs/{run_id}/presentation-candidates/{candidate_id}/accept",
        "/studio/image-runs/{run_id}/presentation-candidates/{candidate_id}/discard",
        "/studio/presentation-candidates/{run_id}/{candidate_id}/accept",
        "/studio/presentation-candidates/{run_id}/{candidate_id}/discard",
        "/studio/projects/{project_root_id}/variations",
        "/studio/projects/{project_root_id}/creative-candidates/{candidate_id}/variations",
        "/studio/projects/{project_root_id}/revisions/{asset_id}/restore",
        "/studio/projects/{project_root_id}/facts/revise",
    )
    | _operations("PATCH", "/studio/jobs/{job_id}")
    | _operations(
        "DELETE", "/image-runs/{run_id}/catalog-candidates/{candidate_id}",
    )
)


def test_production_method_path_surface_is_exact(monkeypatch):
    monkeypatch.setenv("FACETTA_ENV", "production")
    production_app = create_app()
    actual = {
        (method.upper(), path)
        for path, operations in production_app.openapi()["paths"].items()
        for method in operations
        if method.lower() in {"get", "post", "put", "patch", "delete"}
    }
    assert actual == EXPECTED_PRODUCTION_OPERATIONS


def test_production_hides_legacy_admin_and_stateless_spec_adapters(monkeypatch):
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
            ("post", "/studio/projects/import-confirmed"),
            ("post", "/projects/known/creative-directions/commit"),
            ("get", "/projects/missing"),
            ("get", "/studio/families"),
            ("post", "/assets/known/markup/read"),
            ("post", "/assets/known/markup/apply"),
            ("get", "/assets/known/image"),
            ("get", "/assets/known/studio-component-targeting"),
            ("post", "/assets/known/checklist"),
            ("get", "/assets/known/checklist"),
            ("post", "/assets/known/checklist/respond"),
            ("post", "/assets/known/catalog/preview"),
            ("get", "/assets/known/catalog/previews"),
            ("post", "/projects/known/factory-pack"),
            ("get", "/studio/projects/known/visual-candidates"),
            ("post", "/studio/projects/known/facts/revise"),
            ("post", "/studio/image-runs/known/visual-candidates/known/save-as-variation"),
            ("post", "/image-runs/known/catalog-candidates/known/save-as-variation"),
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
            ("post", "/specs/from-photo"),
            ("post", "/specs/from-plate"),
            ("post", "/specs/validate"),
            ("post", "/specs/catalog/select"),
            ("post", "/specs/stone/select"),
            ("post", "/specs/sheet.svg"),
            ("post", "/specs/source-coverage/resolve"),
            ("post", "/specs/source-coverage/confirm"),
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
            ("get", "/assets/known/component-map"),
            ("post", "/projects/from-brief"),
            ("get", "/projects/from-brief/candidates/known/image"),
            ("post", "/projects/from-brief/candidates/known/accept"),
            ("post", "/projects/from-image"),
            ("post", "/projects/known/creative-candidates/candidate/select"),
            ("post", "/projects/known/render"),
            ("post", "/projects/known/product-photo"),
            ("post", "/projects/known/visual-twin/views"),
            ("post", "/projects/known/creative-candidates/candidate/draft"),
            ("post", "/projects/known/line-art/line-art/colorize"),
            ("get", "/image-runs/known"),
            ("post", "/image-runs/known/feedback"),
        ):
            hidden = (
                client.post(path, json={}) if method == "post"
                else client.get(path)
            )
            # A removed static operation may collide with the retained
            # `/projects/{root_id}` shape and return method-not-allowed; it
            # must never resolve to an authenticated product handler.
            assert hidden.status_code in {404, 405}


def test_structured_ring_brief_routes_are_deprecated_compatibility(
    monkeypatch,
):
    monkeypatch.setenv("FACETTA_ENV", "test")
    test_app = create_app()
    paths = test_app.openapi()["paths"]

    assert paths["/projects/from-prompt"]["post"].get("deprecated") is not True
    assert paths["/projects/from-brief"]["post"]["deprecated"] is True
    assert (
        paths["/projects/from-brief/candidates/{candidate_id}/image"]["get"]
        ["deprecated"]
        is True
    )
    assert (
        paths["/projects/from-brief/candidates/{candidate_id}/accept"]["post"]
        ["deprecated"]
        is True
    )


def test_legacy_creative_selection_is_deprecated_compatibility(monkeypatch):
    monkeypatch.setenv("FACETTA_ENV", "test")
    test_app = create_app()
    paths = test_app.openapi()["paths"]

    legacy_select = (
        "/projects/{project_id}/creative-candidates/{candidate_id}/select"
    )
    atomic_commit = "/projects/{project_id}/creative-directions/commit"
    assert paths[legacy_select]["post"]["deprecated"] is True
    assert paths[atomic_commit]["post"].get("deprecated") is not True


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

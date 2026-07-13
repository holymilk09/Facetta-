"""Facetta API."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from facetta import __version__
from facetta.config import env_value, load_env_file

# Load .env before importing routers: provider modules are allowed to inspect
# their environment during import, while real exported values still win.
load_env_file()

from facetta.api import (  # noqa: E402 - env must load before router imports
    assets, catalog, designs, library, projects, share, specs, stones, studio,
    studio_facts, trusted, users, vocabulary,
)
from facetta.auth import (  # noqa: E402
    require_authenticated_principal,
    validate_auth_configuration,
)
from facetta.catalog_component_targeting import (  # noqa: E402
    catalog_structural_component_mapper_status,
)
from facetta.catalog_structural_mapper_composition import (  # noqa: E402
    configure_attested_catalog_structural_mapper_from_environment,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    validate_auth_configuration()
    configure_attested_catalog_structural_mapper_from_environment()
    yield

def health() -> dict:
    mapper = catalog_structural_component_mapper_status()
    return {
        "status": "ok",
        "service": "facetta",
        "version": __version__,
        # Structural component refinement is optional.  The service remains
        # healthy while this capability is disabled, but operators can see
        # whether an attested mapper is absent, unhealthy, or ready.
        "capabilities": {
            "structural_component_mapping": {
                "state": mapper.state,
                "mapper_contract": mapper.mapper_contract,
                "calibration_evidence_sha256": (
                    mapper.calibration_evidence_sha256
                ),
                "supported_paths": list(mapper.supported_paths),
                "reason_code": mapper.reason_code,
            }
        },
    }


PRODUCTION_SPEC_PATHS = frozenset({
    "/specs/validate",
    "/specs/catalog/select",
    "/specs/stone/select",
    "/specs/sheet.svg",
    "/specs/from-photo",
    "/specs/from-plate",
    "/specs/source-coverage/resolve",
    "/specs/source-coverage/confirm",
})

PRODUCTION_ASSET_PATHS = frozenset({
    "/assets/{asset_id}/markup/read",
    "/assets/{asset_id}/markup/apply",
    "/assets/{asset_id}/image",
    "/assets/{asset_id}/checklist",
    "/assets/{asset_id}/checklist/respond",
})

PRODUCTION_CATALOG_PATHS = frozenset({
    "/assets/{active_asset_id}/catalog/preview",
    "/assets/{active_asset_id}/catalog/previews",
    "/assets/{asset_id}/studio-component-targeting",
    "/assets/{asset_id}/studio-component-map",
})

PRODUCTION_TRUSTED_PATHS = frozenset({
    "/image-runs/{run_id}/candidates/{candidate_id}/image",
    "/image-runs/{run_id}/candidates/{candidate_id}/accept",
    "/image-runs/{run_id}/candidates/{candidate_id}/discard",
    "/projects/{project_id}/factory-pack",
    "/projects/{project_id}/factory-pack.zip",
})

RouteOperation = tuple[str, str]

PRODUCTION_CATALOG_PREVIEW_OPERATIONS: frozenset[RouteOperation] = frozenset({
    ("GET", "/image-runs/{run_id}/catalog-candidates/{candidate_id}/image"),
    ("DELETE", "/image-runs/{run_id}/catalog-candidates/{candidate_id}"),
    ("POST", "/image-runs/{run_id}/catalog-candidates/{candidate_id}/accept"),
    (
        "POST",
        "/image-runs/{run_id}/catalog-candidates/{candidate_id}/save-as-variation",
    ),
})

PRODUCTION_PROJECT_OPERATIONS: frozenset[RouteOperation] = frozenset({
    ("POST", "/projects/from-prompt"),
    ("POST", "/projects/from-drawing"),
    (
        "POST",
        "/projects/{project_id}/creative-candidates/{candidate_id}/select",
    ),
    (
        "POST",
        "/projects/{project_id}/creative-directions/commit",
    ),
    (
        "POST",
        "/projects/{project_id}/creative-candidates/{candidate_id}/confirm-design",
    ),
    (
        "POST",
        "/projects/{project_id}/creative-candidates/{candidate_id}/promote",
    ),
    ("GET", "/projects/{root_id}"),
    ("POST", "/projects/{root_id}/marketing-pack"),
    ("POST", "/projects/{root_id}/visual-twin/views"),
    ("POST", "/projects/{root_id}/line-art"),
})

PRODUCTION_STUDIO_OPERATIONS: frozenset[RouteOperation] = frozenset({
    ("GET", "/studio/capabilities"),
    ("POST", "/studio/projects/import-confirmed"),
    ("POST", "/studio/jobs"),
    ("GET", "/studio/jobs"),
    ("GET", "/studio/jobs/{job_id}"),
    ("PATCH", "/studio/jobs/{job_id}"),
    ("POST", "/studio/jobs/{job_id}/cancel"),
    ("POST", "/studio/projects/{root_id}/beauty-render"),
    ("POST", "/studio/projects/{root_id}/product-photo"),
    ("POST", "/studio/projects/{project_id}/visual-previews"),
    (
        "GET",
        "/studio/image-runs/{run_id}/visual-candidates/{candidate_id}/image",
    ),
    (
        "POST",
        "/studio/image-runs/{run_id}/visual-candidates/{candidate_id}/accept",
    ),
    (
        "POST",
        "/studio/image-runs/{run_id}/visual-candidates/{candidate_id}/discard",
    ),
    (
        "POST",
        "/studio/image-runs/{run_id}/visual-candidates/{candidate_id}/save-as-variation",
    ),
    ("GET", "/studio/projects/{project_root_id}/visual-candidates"),
    ("GET", "/studio/projects/{project_root_id}/markup-candidates"),
    ("GET", "/studio/markup-candidates/{run_id}/{candidate_id}/image"),
    ("POST", "/studio/markup-candidates/{run_id}/{candidate_id}/accept"),
    ("POST", "/studio/markup-candidates/{run_id}/{candidate_id}/discard"),
    (
        "POST",
        "/studio/markup-candidates/{run_id}/{candidate_id}/save-as-variation",
    ),
    ("POST", "/studio/projects/{project_id}/presentation-previews"),
    ("GET", "/studio/view-candidates"),
    ("GET", "/studio/view-candidates/{run_id}/{candidate_id}/image"),
    ("POST", "/studio/view-candidates/{run_id}/{candidate_id}/accept"),
    ("POST", "/studio/view-candidates/{run_id}/{candidate_id}/discard"),
    ("GET", "/studio/presentation-candidates"),
    (
        "GET",
        "/studio/image-runs/{run_id}/presentation-candidates/{candidate_id}/image",
    ),
    (
        "POST",
        "/studio/image-runs/{run_id}/presentation-candidates/{candidate_id}/accept",
    ),
    (
        "POST",
        "/studio/image-runs/{run_id}/presentation-candidates/{candidate_id}/discard",
    ),
    (
        "POST",
        "/studio/presentation-candidates/{run_id}/{candidate_id}/accept",
    ),
    (
        "POST",
        "/studio/presentation-candidates/{run_id}/{candidate_id}/discard",
    ),
    ("POST", "/studio/projects/{project_root_id}/variations"),
    (
        "POST",
        "/studio/projects/{project_root_id}/creative-candidates/{candidate_id}/variations",
    ),
    (
        "POST",
        "/studio/projects/{project_root_id}/revisions/{asset_id}/restore",
    ),
    ("GET", "/studio/projects/{project_root_id}/history"),
    ("GET", "/studio/families"),
    ("GET", "/studio/families/{family_id}"),
})

PRODUCTION_STUDIO_FACT_OPERATIONS: frozenset[RouteOperation] = frozenset({
    ("POST", "/studio/projects/{project_root_id}/facts/revise"),
})


def _production_spec_router() -> APIRouter:
    router = APIRouter()
    router.routes.extend(
        route for route in specs.router.routes
        if getattr(route, "path", None) in PRODUCTION_SPEC_PATHS
    )
    return router


def _filtered_router(source: APIRouter, paths: frozenset[str]) -> APIRouter:
    router = APIRouter()
    router.routes.extend(
        route for route in source.routes
        if getattr(route, "path", None) in paths
    )
    return router


def _operation_filtered_router(
    source: APIRouter,
    operations: frozenset[RouteOperation],
) -> APIRouter:
    """Select an exact public method/path surface and reject stale entries."""
    router = APIRouter()
    selected: set[RouteOperation] = set()
    for route in source.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", set()) or set()
        available_operations = {
            (method.upper(), path)
            for method in methods
            if path is not None
        }
        route_operations = available_operations & operations
        if route_operations:
            unexpected = available_operations - operations
            if unexpected:
                raise RuntimeError(
                    "production route object includes non-allowlisted methods: "
                    f"{sorted(unexpected)}"
                )
            router.routes.append(route)
            selected.update(route_operations)
    missing = operations - selected
    if missing:
        raise RuntimeError(
            f"production route allowlist references missing operations: {sorted(missing)}"
        )
    return router


def create_app() -> FastAPI:
    environment = (env_value("FACETTA_ENV") or "production").strip().lower()
    production = environment == "production"
    application = FastAPI(
        title="Facetta",
        version=__version__,
        lifespan=lifespan,
        docs_url=None if production else "/docs",
        redoc_url=None if production else "/redoc",
        openapi_url=None if production else "/openapi.json",
    )
    configured_origins = [
        value.strip() for value in (
            env_value("FACETTA_CORS_ORIGINS") or ""
        ).split(",") if value.strip()
    ]
    if production and "*" in configured_origins:
        raise RuntimeError("production CORS origins must be exact and cannot use '*'")
    application.add_middleware(
        CORSMiddleware,
        allow_origins=configured_origins if production else ["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Production exposes only the canonical Studio control plane plus the
    # authenticated specification adapters it still consumes. Legacy Builder,
    # design/library/user/stone administration, and capability-share routes
    # remain available in test/development for migration, never on the public
    # beta surface.
    application.include_router(vocabulary.router)
    application.include_router(
        _production_spec_router() if production else specs.router,
        dependencies=[Depends(require_authenticated_principal)],
    )
    application.include_router(
        _filtered_router(assets.router, PRODUCTION_ASSET_PATHS)
        if production else assets.router
    )
    application.include_router(
        _filtered_router(catalog.router, PRODUCTION_CATALOG_PATHS)
        if production else catalog.router
    )
    application.include_router(
        _operation_filtered_router(
            catalog.preview_router, PRODUCTION_CATALOG_PREVIEW_OPERATIONS,
        ) if production else catalog.preview_router
    )
    application.include_router(
        _operation_filtered_router(
            projects.router, PRODUCTION_PROJECT_OPERATIONS,
        ) if production else projects.router
    )
    application.include_router(
        _operation_filtered_router(
            studio.router, PRODUCTION_STUDIO_OPERATIONS,
        ) if production else studio.router
    )
    application.include_router(
        _operation_filtered_router(
            studio_facts.router, PRODUCTION_STUDIO_FACT_OPERATIONS,
        ) if production else studio_facts.router
    )
    application.include_router(
        _filtered_router(trusted.router, PRODUCTION_TRUSTED_PATHS)
        if production else trusted.router
    )
    if not production:
        application.include_router(designs.router)
        application.include_router(share.router)
        application.include_router(users.router)
        application.include_router(stones.router)
        application.include_router(library.router)
    application.add_api_route("/health", health, methods=["GET"])
    return application


app = create_app()

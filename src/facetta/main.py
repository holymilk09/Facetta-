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


@asynccontextmanager
async def lifespan(_app: FastAPI):
    validate_auth_configuration()
    yield

def health() -> dict:
    return {"status": "ok", "service": "facetta", "version": __version__}


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
    "/assets/{asset_id}/pin",
})

PRODUCTION_CATALOG_PATHS = frozenset({
    "/assets/{active_asset_id}/catalog/preview",
    "/assets/{active_asset_id}/catalog/previews",
})

PRODUCTION_TRUSTED_PATHS = frozenset({
    "/image-runs/{run_id}/candidates/{candidate_id}/image",
    "/image-runs/{run_id}/candidates/{candidate_id}/accept",
    "/image-runs/{run_id}/candidates/{candidate_id}/discard",
    "/projects/{project_id}/factory-pack",
    "/projects/{project_id}/factory-pack.zip",
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
    application.include_router(catalog.preview_router)
    application.include_router(projects.router)
    application.include_router(studio.router)
    application.include_router(studio_facts.router)
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

"""Facetta API."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from facetta import __version__
from facetta.config import load_env_file

# Load .env before importing routers: provider modules are allowed to inspect
# their environment during import, while real exported values still win.
load_env_file()

from facetta.api import (  # noqa: E402 - env must load before router imports
    assets, catalog, designs, library, projects, share, specs, stones, studio,
    trusted, users, vocabulary,
)
from facetta.auth import validate_auth_configuration  # noqa: E402


@asynccontextmanager
async def lifespan(_app: FastAPI):
    validate_auth_configuration()
    yield

app = FastAPI(title="Facetta", version=__version__, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # dev default; lock down before exposing publicly
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(vocabulary.router)
app.include_router(specs.router)
app.include_router(designs.router)
app.include_router(share.router)
app.include_router(users.router)
app.include_router(stones.router)
app.include_router(assets.router)
app.include_router(catalog.router)
app.include_router(catalog.preview_router)
app.include_router(projects.router)
app.include_router(library.router)
app.include_router(studio.router)
app.include_router(trusted.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "facetta", "version": __version__}

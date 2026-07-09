"""Facetta API."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from facetta import __version__
from facetta.api import stones, designs, share, specs, users, vocabulary
from facetta.config import load_env_file

# Load .env into the process environment before anything reads a key or the
# Anthropic SDK is constructed. A real exported env var always takes precedence.
load_env_file()

app = FastAPI(title="Facetta", version=__version__)

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


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "facetta", "version": __version__}

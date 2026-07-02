"""Facetta API."""

from __future__ import annotations

from fastapi import FastAPI

from facetta import __version__
from facetta.api import designs, share, specs, users, vocabulary

app = FastAPI(title="Facetta", version=__version__)

app.include_router(vocabulary.router)
app.include_router(specs.router)
app.include_router(designs.router)
app.include_router(share.router)
app.include_router(users.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "facetta", "version": __version__}

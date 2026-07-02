"""Facetta API."""

from __future__ import annotations

from fastapi import FastAPI

from facetta import __version__
from facetta.api import specs, vocabulary

app = FastAPI(title="Facetta", version=__version__)

app.include_router(vocabulary.router)
app.include_router(specs.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "facetta", "version": __version__}

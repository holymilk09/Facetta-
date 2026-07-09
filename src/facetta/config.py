"""Small shared config helpers.

Configuration values live in the environment; for zero-setup local development a
gitignored ``.env`` at the repo root is consulted as a fallback. This mirrors how
the render layer already resolves provider keys — the DB layer uses it for
``DATABASE_URL`` so a Supabase connection string can live in the same ``.env``.
"""

from __future__ import annotations

import os
from pathlib import Path


def env_value(key: str, default: str | None = None) -> str | None:
    """Return ``key`` from the environment, falling back to a repo-root ``.env``.

    The ``.env`` format is deliberately minimal: ``KEY=value`` lines, ``#``
    comments, blank lines ignored, optional surrounding quotes stripped. An
    exported environment variable always wins over the file.
    """
    if os.environ.get(key):
        return os.environ[key]
    env_file = Path(".env")
    if env_file.exists():
        for raw in env_file.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            if name.strip() != key:
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            return value
    return default

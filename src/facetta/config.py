"""Small shared config helpers.

Configuration — connection strings and provider API keys — lives in the
environment. For zero-setup local development gitignored repo-root env files
are the local home for all of it: ``DATABASE_URL`` plus the optional
``ANTHROPIC_API_KEY`` / ``FAL_KEY`` / ``XAI_KEY`` / ``OPENAI_API_KEY``.
``load_env_file()`` (called at app startup) copies those into the process
environment so every consumer picks them up. A real exported environment
variable always wins over local files, and ``.env.local`` wins over ``.env``.
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_FILE = Path(".env")
LOCAL_ENV_FILE = Path(".env.local")
DEFAULT_ENV_FILES = (LOCAL_ENV_FILE, ENV_FILE)


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse a minimal ``.env``: ``KEY=value`` lines, ``#`` comments and blank
    lines ignored, optional surrounding quotes stripped. Missing file -> ``{}``."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name, value = name.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if name:
            values[name] = value
    return values


def env_value(key: str, default: str | None = None) -> str | None:
    """Return ``key`` from the environment, falling back to local env files.

    Exported variables always win. For local files, ``.env.local`` is checked
    before the shared ``.env`` default.
    """
    if os.environ.get(key):
        return os.environ[key]
    for path in DEFAULT_ENV_FILES:
        value = _parse_env_file(path).get(key)
        if value is not None:
            return value
    return default


def load_env_file(path: Path | str | None = None) -> list[str]:
    """Copy local env-file values into ``os.environ`` for missing keys.

    Real environment variables win — this only fills gaps, so it is safe to call
    unconditionally at startup. With no explicit path, ``.env.local`` is loaded
    before ``.env``. Returns the keys it loaded (for logging/tests).
    """
    loaded: list[str] = []
    paths = DEFAULT_ENV_FILES if path is None else (Path(path),)
    for env_path in paths:
        for name, value in _parse_env_file(Path(env_path)).items():
            if name not in os.environ:
                os.environ[name] = value
                loaded.append(name)
    return loaded

"""Keep the staged route-deletion ledger synchronized with FastAPI."""

from __future__ import annotations

import re
from pathlib import Path

from facetta.main import app


INVENTORY = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "trusted-workflow-route-inventory.md"
)
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
ROW = re.compile(
    r"^\| `(GET|POST|PUT|PATCH|DELETE) ([^`]+)` \| "
    r"(Canonical|Internal primitive|Deprecated compatibility|Dead/conflicting) \|",
    re.MULTILINE,
)


def test_every_openapi_operation_is_classified_once() -> None:
    classified = ROW.findall(INVENTORY.read_text())
    documented = [(method, path) for method, path, _ in classified]
    assert len(documented) == len(set(documented)), "duplicate inventory row"

    openapi = {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
        if method.lower() in HTTP_METHODS
    }
    assert set(documented) == openapi

    schema = app.openapi()["paths"]
    for method, path, classification in classified:
        if classification in {"Deprecated compatibility", "Dead/conflicting"}:
            assert schema[path][method.lower()].get("deprecated") is True, (
                f"{method} {path} is staged for removal but is not marked "
                "deprecated in OpenAPI")

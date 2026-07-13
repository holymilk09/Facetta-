"""Portable, root-confined path and artifact-index helpers for frozen evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal


Json = dict[str, Any]
ARTIFACT_INDEX_SCHEMA = "facetta-frozen-artifact-index.v1"


def evidence_root(path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_dir():
        raise ValueError("evidence root is unavailable")
    return resolved


def confined_path(
    root: Path,
    value: Path | str,
    *,
    label: str,
    kind: Literal["file", "directory"],
    require_relative: bool = False,
) -> Path:
    raw = Path(value)
    if require_relative and raw.is_absolute():
        raise ValueError(f"{label} must be evidence-root-relative")
    candidate = raw if raw.is_absolute() else root / raw
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"{label} escapes the evidence root")
    exists = resolved.is_file() if kind == "file" else resolved.is_dir()
    if not exists:
        raise ValueError(f"{label} is unavailable")
    return resolved


def confined_output_path(root: Path, value: Path | str, *, label: str) -> Path:
    raw = Path(value)
    candidate = raw if raw.is_absolute() else root / raw
    resolved = candidate.resolve(strict=False)
    if not resolved.is_relative_to(root):
        raise ValueError(f"{label} escapes the evidence root")
    parent = resolved.parent.resolve()
    if not parent.is_relative_to(root):
        raise ValueError(f"{label} parent escapes the evidence root")
    return resolved


def relative_artifact_path(root: Path, path: Path, *, label: str) -> str:
    resolved = confined_path(root, path, label=label, kind="file")
    return resolved.relative_to(root).as_posix()


def canonical_object_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_artifact_index(
    artifacts: list[tuple[str, str, str]],
) -> Json:
    """Build a deterministic path/hash index with sorted semantic roles."""

    merged: dict[str, Json] = {}
    for path, sha256, role in artifacts:
        current = merged.setdefault(path, {"path": path, "sha256": sha256, "roles": []})
        if current["sha256"] != sha256:
            raise ValueError(f"artifact index hash conflicts for {path}")
        if role not in current["roles"]:
            current["roles"].append(role)
    rows = sorted(merged.values(), key=lambda row: row["path"])
    for row in rows:
        row["roles"].sort()
    return {
        "schema_version": ARTIFACT_INDEX_SCHEMA,
        "path_contract": "evidence-root-relative.v1",
        "artifacts_sha256": canonical_object_sha256(rows),
        "artifacts": rows,
    }


def validate_artifact_index(index: object, root: Path) -> list[str]:
    if not isinstance(index, dict):
        return ["artifact_index must be an object"]
    errors: list[str] = []
    if index.get("schema_version") != ARTIFACT_INDEX_SCHEMA:
        errors.append("artifact_index schema_version is unsupported")
    if index.get("path_contract") != "evidence-root-relative.v1":
        errors.append("artifact_index path contract is unsupported")
    rows = index.get("artifacts")
    if not isinstance(rows, list):
        return errors + ["artifact_index artifacts must be a list"]
    if any(not isinstance(row, dict) for row in rows):
        return errors + ["artifact_index rows must be objects"]
    if index.get("artifacts_sha256") != canonical_object_sha256(rows):
        errors.append("artifact_index canonical hash differs")
    paths = [str(row.get("path") or "") for row in rows]
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        errors.append("artifact_index paths must be unique and sorted")
    for row in rows:
        path = row.get("path")
        digest = row.get("sha256")
        roles = row.get("roles")
        try:
            artifact = confined_path(
                root,
                str(path or ""),
                label=f"artifact index entry {path}",
                kind="file",
                require_relative=True,
            )
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if not isinstance(digest, str) or hashlib.sha256(artifact.read_bytes()).hexdigest() != digest:
            errors.append(f"artifact index hash differs for {path}")
        if not isinstance(roles, list) or not roles or roles != sorted(set(roles)):
            errors.append(f"artifact index roles are invalid for {path}")
    return errors

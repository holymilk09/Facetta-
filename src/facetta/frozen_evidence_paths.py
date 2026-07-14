"""Root-confined path and artifact-index helpers for frozen evidence."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sys
from pathlib import Path
from typing import Any, Callable, Literal, Mapping


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


def _lexical_path(path: Path) -> Path:
    return Path(os.path.abspath(path))


def _artifact_target(path: Path, root: Path | None) -> Path:
    if root is None:
        return path.parent.resolve() / path.name
    normalized_root = _lexical_path(root)
    candidate = path if path.is_absolute() else normalized_root / path
    target = _lexical_path(candidate)
    if not target.is_relative_to(normalized_root):
        raise ValueError("retained artifact escapes the evidence root")
    return target


def _directory_flags() -> int:
    flags = os.O_RDONLY
    flags |= getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    return flags


def _open_parent_directory(parent: Path, root: Path | None) -> int:
    if root is None:
        return os.open(parent, _directory_flags())

    normalized_root = _lexical_path(root)
    relative = parent.relative_to(normalized_root)
    descriptor = os.open(normalized_root, _directory_flags())
    try:
        for component in relative.parts:
            child = os.open(component, _directory_flags(), dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _open_artifact_targets(
    paths: list[Path], root: Path | None,
) -> tuple[list[tuple[Path, int]], set[int]]:
    normalized: set[Path] = set()
    parent_descriptors: dict[Path, int] = {}
    targets: list[tuple[Path, int]] = []
    try:
        for path in paths:
            target = _artifact_target(path, root)
            if target in normalized:
                raise ValueError("retained artifact targets must be unique")
            normalized.add(target)
            descriptor = parent_descriptors.get(target.parent)
            if descriptor is None:
                try:
                    descriptor = _open_parent_directory(target.parent, root)
                except FileNotFoundError as exc:
                    raise ValueError(
                        f"retained artifact parent is unavailable: {target.parent}"
                    ) from exc
                except OSError as exc:
                    raise ValueError(
                        f"retained artifact parent is not a trusted directory: "
                        f"{target.parent}"
                    ) from exc
                parent_descriptors[target.parent] = descriptor
            targets.append((target, descriptor))
        return targets, set(parent_descriptors.values())
    except BaseException:
        for descriptor in parent_descriptors.values():
            os.close(descriptor)
        raise


def _target_exists(target: Path, descriptor: int) -> bool:
    try:
        os.stat(target.name, dir_fd=descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return True


def _require_fresh_targets(targets: list[tuple[Path, int]]) -> None:
    for target, descriptor in targets:
        if _target_exists(target, descriptor):
            raise ValueError(f"retained artifact already exists: {target}")


def require_new_artifact_paths(
    paths: list[Path], *, root: Path | None = None,
) -> None:
    """Fail before work when a retained artifact target is not fresh."""

    targets, descriptors = _open_artifact_targets(paths, root)
    try:
        _require_fresh_targets(targets)
    finally:
        for descriptor in descriptors:
            os.close(descriptor)


def _fsync_directories(descriptors: set[int]) -> None:
    for descriptor in descriptors:
        os.fsync(descriptor)


def write_new_artifacts(
    artifacts: Mapping[Path, bytes], *, root: Path | None = None,
) -> None:
    """Install each fresh artifact atomically, with best-effort batch rollback."""

    if not artifacts:
        raise ValueError("retained artifact batch must not be empty")
    opened_targets, descriptors = _open_artifact_targets(list(artifacts), root)
    targets = [
        (target, descriptor, artifacts[path])
        for path, (target, descriptor) in zip(artifacts, opened_targets, strict=True)
    ]
    staged: list[tuple[int, str, Path]] = []
    installed: list[tuple[int, str, Path]] = []
    try:
        _require_fresh_targets([
            (target, descriptor) for target, descriptor, _ in targets
        ])
        for target, parent_descriptor, value in targets:
            temporary_name = (
                f".{target.name}.staging-{secrets.token_hex(12)}"
            )
            file_descriptor = os.open(
                temporary_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=parent_descriptor,
            )
            staged.append((parent_descriptor, temporary_name, target))
            with os.fdopen(file_descriptor, "wb") as handle:
                handle.write(value)
                handle.flush()
                os.fsync(handle.fileno())
        for parent_descriptor, temporary_name, target in staged:
            try:
                os.link(
                    temporary_name,
                    target.name,
                    src_dir_fd=parent_descriptor,
                    dst_dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
            except FileExistsError as exc:
                raise ValueError(f"retained artifact already exists: {target}") from exc
            installed.append((parent_descriptor, temporary_name, target))
        _fsync_directories(descriptors)
    except BaseException as primary_error:
        cleanup_errors: list[BaseException] = []
        for parent_descriptor, temporary_name, target in reversed(installed):
            try:
                temporary_stat = os.stat(
                    temporary_name,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
                target_stat = os.stat(
                    target.name,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
                if (temporary_stat.st_dev, temporary_stat.st_ino) == (
                    target_stat.st_dev, target_stat.st_ino,
                ):
                    os.unlink(target.name, dir_fd=parent_descriptor)
            except FileNotFoundError:
                pass
            except BaseException as exc:
                cleanup_errors.append(exc)
        try:
            _fsync_directories(descriptors)
        except BaseException as exc:
            cleanup_errors.append(exc)
        for cleanup_error in cleanup_errors:
            primary_error.add_note(f"retained artifact cleanup also failed: {cleanup_error}")
        raise
    finally:
        cleanup_errors: list[BaseException] = []
        for parent_descriptor, temporary_name, _target in staged:
            try:
                os.unlink(temporary_name, dir_fd=parent_descriptor)
            except FileNotFoundError:
                pass
            except BaseException as exc:
                cleanup_errors.append(exc)
        try:
            _fsync_directories(descriptors)
        except BaseException as exc:
            cleanup_errors.append(exc)
        for descriptor in descriptors:
            try:
                os.close(descriptor)
            except BaseException as exc:
                cleanup_errors.append(exc)
        active_error = sys.exc_info()[1]
        if active_error is not None:
            for cleanup_error in cleanup_errors:
                active_error.add_note(
                    f"retained artifact cleanup also failed: {cleanup_error}"
                )
        elif cleanup_errors:
            raise cleanup_errors[0]


def write_new_text_artifact(
    path: Path, value: str, *, root: Path | None = None,
) -> None:
    """Atomically create one retained UTF-8 artifact without replacement."""

    write_new_artifacts({path: value.encode("utf-8")}, root=root)


def retained_cli_entrypoint(main: Callable[[], int]) -> int:
    """Return stable JSON for expected retained-evidence operational failures."""

    try:
        return main()
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({
            "schema_version": "facetta-retained-evidence-error.v1",
            "status": "fail",
            "provider_calls": 0,
            "error": str(exc),
            "corpus_gate_ready": False,
        }, indent=2, sort_keys=True))
        return 2


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

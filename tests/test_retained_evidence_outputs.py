from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from facetta import frozen_evidence_paths
from facetta.frozen_evidence_paths import (
    confined_output_path,
    require_new_artifact_paths,
    write_new_artifacts,
    write_new_text_artifact,
)


def _staging_files(directory: Path) -> list[Path]:
    return list(directory.glob(".*.staging-*"))


def test_fresh_artifacts_are_written_exactly_with_private_permissions(
    tmp_path: Path,
):
    binary = tmp_path / "results.bin"
    text = tmp_path / "report.txt"

    write_new_artifacts({binary: b"\x00retained\xff"})
    write_new_text_artifact(text, "reviewed\n")

    assert binary.read_bytes() == b"\x00retained\xff"
    assert text.read_bytes() == b"reviewed\n"
    assert stat.S_IMODE(binary.stat().st_mode) == 0o600
    assert stat.S_IMODE(text.stat().st_mode) == 0o600
    assert _staging_files(tmp_path) == []


def test_existing_artifact_is_never_replaced(tmp_path: Path):
    target = tmp_path / "decision.json"
    target.write_bytes(b"signed-sentinel")

    with pytest.raises(ValueError, match="retained artifact already exists"):
        write_new_artifacts({target: b"replacement"})

    assert target.read_bytes() == b"signed-sentinel"
    assert _staging_files(tmp_path) == []


def test_symlink_artifact_is_rejected_without_touching_its_destination(
    tmp_path: Path,
):
    destination = tmp_path / "signed-original.json"
    destination.write_bytes(b"signed-original")
    target = tmp_path / "decision.json"
    target.symlink_to(destination)

    with pytest.raises(ValueError, match="retained artifact already exists"):
        write_new_text_artifact(target, "replacement\n")

    assert target.is_symlink()
    assert destination.read_bytes() == b"signed-original"
    assert _staging_files(tmp_path) == []


def test_batch_preflight_prevents_partial_install(tmp_path: Path):
    fresh = tmp_path / "results.json"
    existing = tmp_path / "report.md"
    existing.write_bytes(b"signed-report")

    with pytest.raises(ValueError, match="retained artifact already exists"):
        write_new_artifacts({fresh: b"new-results", existing: b"new-report"})

    assert not fresh.exists()
    assert existing.read_bytes() == b"signed-report"
    assert _staging_files(tmp_path) == []


def test_normalized_duplicate_targets_are_rejected(tmp_path: Path):
    nested = tmp_path / "nested"
    nested.mkdir()
    canonical = tmp_path / "artifact.json"
    equivalent = nested / ".." / "artifact.json"

    with pytest.raises(ValueError, match="targets must be unique"):
        write_new_artifacts({canonical: b"one", equivalent: b"two"})

    assert not canonical.exists()
    assert _staging_files(tmp_path) == []


def test_missing_parent_remains_an_error(tmp_path: Path):
    target = tmp_path / "missing" / "artifact.json"

    with pytest.raises(ValueError, match="parent is unavailable"):
        require_new_artifact_paths([target])
    with pytest.raises(ValueError, match="parent is unavailable"):
        write_new_artifacts({target: b"value"})

    assert not target.exists()


def test_install_failure_rolls_back_the_entire_batch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    first = tmp_path / "results.json"
    second = tmp_path / "report.md"
    real_link = os.link
    calls = 0

    def fail_second_link(
        source: str,
        destination: str,
        **kwargs: object,
    ) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected link failure")
        real_link(source, destination, **kwargs)

    monkeypatch.setattr(frozen_evidence_paths.os, "link", fail_second_link)

    with pytest.raises(OSError, match="injected link failure"):
        write_new_artifacts({first: b"results", second: b"report"})

    assert not first.exists()
    assert not second.exists()
    assert _staging_files(tmp_path) == []


def test_target_created_after_preflight_wins_without_overwrite(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    target = tmp_path / "decision.json"
    real_link = os.link

    def create_competing_target(
        source: str,
        destination: str,
        **kwargs: object,
    ) -> None:
        destination_fd = kwargs["dst_dir_fd"]
        assert isinstance(destination_fd, int)
        descriptor = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
            dir_fd=destination_fd,
        )
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(b"concurrent-winner")
        real_link(source, destination, **kwargs)

    monkeypatch.setattr(
        frozen_evidence_paths.os, "link", create_competing_target,
    )

    with pytest.raises(ValueError, match="retained artifact already exists"):
        write_new_artifacts({target: b"late-replacement"})

    assert target.read_bytes() == b"concurrent-winner"
    assert _staging_files(tmp_path) == []


def test_parent_symlink_swap_cannot_escape_evidence_root(tmp_path: Path):
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    run_directory = evidence_root / "run-001"
    run_directory.mkdir()
    target = confined_output_path(
        evidence_root, run_directory / "decision.json", label="decision output",
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    run_directory.rmdir()
    run_directory.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="not a trusted directory"):
        write_new_text_artifact(target, "blocked\n", root=evidence_root)

    assert not (outside / "decision.json").exists()

"""Regression checks for the one-command local Facetta stack runner."""

from __future__ import annotations

import subprocess

import pytest

from scripts import run_local_preview


def test_wait_until_reports_a_process_that_exits_during_startup() -> None:
    process = subprocess.Popen(["sh", "-c", "exit 7"])

    with pytest.raises(RuntimeError, match="exited during startup with code 7"):
        run_local_preview.wait_until(
            lambda: False,
            process=process,
            label="test service",
            timeout=1,
        )


def test_stop_process_ignores_an_already_finished_process() -> None:
    process = subprocess.Popen(["sh", "-c", "exit 0"])
    process.wait(timeout=1)

    run_local_preview.stop_process(process)


def test_check_stack_requires_both_services(monkeypatch, capsys) -> None:
    monkeypatch.setattr(run_local_preview, "api_is_healthy", lambda: True)
    monkeypatch.setattr(
        run_local_preview,
        "port_is_open",
        lambda port: port == 8081,
    )

    assert run_local_preview.check_stack() == 0
    assert "API 8000: healthy" in capsys.readouterr().out

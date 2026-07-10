"""The .env loader: keys placed in .env reach the process environment so every
consumer — DB, render/AI key reads, and the Anthropic SDK — picks them up, while
a real exported variable always wins."""

import os

import pytest

from facetta.config import env_value, load_env_file


@pytest.fixture(autouse=True)
def _restore_environ():
    # load_env_file writes os.environ directly (so the Anthropic SDK sees the
    # key), which monkeypatch can't auto-undo — snapshot and restore ourselves
    # so nothing leaks into other tests.
    saved = os.environ.copy()
    yield
    os.environ.clear()
    os.environ.update(saved)


def _write(tmp_path, body):
    env = tmp_path / ".env"
    env.write_text(body)
    return env


def test_load_fills_missing_keys(tmp_path):
    os.environ.pop("ANTHROPIC_API_KEY", None)
    os.environ.pop("FAL_KEY", None)
    env = _write(tmp_path, "ANTHROPIC_API_KEY=sk-ant-xxx\nFAL_KEY=fal-yyy\n")

    loaded = load_env_file(env)

    assert set(loaded) == {"ANTHROPIC_API_KEY", "FAL_KEY"}
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-xxx"
    assert os.environ["FAL_KEY"] == "fal-yyy"


def test_exported_env_wins_over_file(tmp_path):
    os.environ["ANTHROPIC_API_KEY"] = "real-exported"
    env = _write(tmp_path, "ANTHROPIC_API_KEY=from-dotenv\n")

    loaded = load_env_file(env)

    assert "ANTHROPIC_API_KEY" not in loaded  # not overridden
    assert os.environ["ANTHROPIC_API_KEY"] == "real-exported"


def test_comments_blanks_and_quotes(tmp_path):
    os.environ.pop("XAI_KEY", None)
    os.environ.pop("DATABASE_URL", None)
    env = _write(
        tmp_path,
        '# a comment\n\nXAI_KEY = "xai-quoted"\nDATABASE_URL=postgres://u:p@h:5432/db\n',
    )

    load_env_file(env)

    assert os.environ["XAI_KEY"] == "xai-quoted"  # surrounding quotes stripped
    assert os.environ["DATABASE_URL"] == "postgres://u:p@h:5432/db"


def test_missing_file_is_noop(tmp_path):
    assert load_env_file(tmp_path / "does-not-exist") == []


def test_env_value_prefers_environment(monkeypatch):
    monkeypatch.setenv("FACETTA_TEST_KEY", "from-env")
    assert env_value("FACETTA_TEST_KEY") == "from-env"


def test_env_value_default_when_absent(monkeypatch):
    monkeypatch.delenv("FACETTA_ABSENT_KEY", raising=False)
    assert env_value("FACETTA_ABSENT_KEY", "fallback") == "fallback"

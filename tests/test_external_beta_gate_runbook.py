"""Regression checks for collision-safe external-beta runbook examples."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANONICAL_RUNBOOK = ROOT / "docs" / "STUDIO_EXTERNAL_BETA_GATES.md"
CORPUS_README = (
    ROOT / "docs" / "evals" / "frozen-founder-corpus-v1" / "README.md"
)


def _bash_blocks(text: str) -> list[str]:
    return re.findall(r"```bash\n(.*?)```", text, flags=re.DOTALL)


def _assert_redirects_are_noclobber_protected(text: str) -> None:
    protected_blocks = 0
    for block in _bash_blocks(text):
        redirect_offsets = [
            match.start() for match in re.finditer(r"\s>\s*\"\$", block)
        ]
        if not redirect_offsets:
            continue
        protected_blocks += 1
        noclobber_offset = block.find("set -C")
        assert noclobber_offset >= 0, block
        assert noclobber_offset < min(redirect_offsets), block
        for line in block.splitlines():
            if line.startswith("printf ") and ">" in line:
                assert line.endswith("|| exit 1"), line
    assert protected_blocks > 0


def _assert_fresh_run_directory(
    text: str,
    *,
    run_id: str,
    directory: str,
    requirement: str,
) -> None:
    assignment = f'{run_id}="${{{run_id}:?{requirement}}}"'
    root_variable = f"{run_id.removesuffix('_ID')}_ROOT"
    path_binding = f'{directory}="${root_variable}/${run_id}"'
    plain_mkdir = f'mkdir "${directory}"'

    assert assignment in text
    assert path_binding in text
    assert plain_mkdir in text
    assert f'{plain_mkdir} || exit 1' in text
    assert text.index(assignment) < text.index(path_binding) < text.index(plain_mkdir)


def test_canonical_external_beta_runbook_uses_fresh_collision_safe_directories() -> None:
    text = CANONICAL_RUNBOOK.read_text(encoding="utf-8")
    bash = "\n".join(_bash_blocks(text))

    _assert_fresh_run_directory(
        text,
        run_id="CORPUS_RUN_ID",
        directory="CORPUS_DIR",
        requirement="preassign a fresh corpus run ID",
    )
    _assert_fresh_run_directory(
        text,
        run_id="STAGING_RUN_ID",
        directory="STAGING_DIR",
        requirement="preassign a fresh staging run ID",
    )
    _assert_fresh_run_directory(
        text,
        run_id="EXTERNAL_RELEASE_RUN_ID",
        directory="EXTERNAL_RELEASE_DIR",
        requirement="preassign a fresh external-release run ID",
    )
    assert "mkdir -p" not in bash
    assert '--outdir "$EXTERNAL_RELEASE_DIR"' in bash
    assert '--outdir "$EVIDENCE_ROOT/gate-artifacts/external-beta"' not in bash
    assert '> "$EXTERNAL_RELEASE_DIR/command-result.json"' in bash
    assert '> "$EXTERNAL_RELEASE_DIR/exit-code.txt"' in bash
    _assert_redirects_are_noclobber_protected(text)


def test_zsh_noclobber_preserves_existing_evidence(tmp_path: Path) -> None:
    artifact = tmp_path / "retained.txt"
    artifact.write_text("signed-original\n", encoding="utf-8")

    completed = subprocess.run(
        [
            "/bin/zsh",
            "-c",
            'set -C; printf "%s\\n" replacement > "$1"',
            "facetta-noclobber-test",
            str(artifact),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert artifact.read_text(encoding="utf-8") == "signed-original\n"


def test_staging_runbook_declares_every_v5_seed_binding() -> None:
    text = CANONICAL_RUNBOOK.read_text(encoding="utf-8")

    for label in ("A", "B"):
        prefix = f"FACETTA_STAGING_USER_{label}"
        for suffix in (
            "ACCESS_TOKEN",
            "PROJECT_ID",
            "FAMILY_ID",
            "ASSET_ID",
            "JOB_ID",
            "CANDIDATE_FIXTURES_JSON",
        ):
            assert f"{prefix}_{suffix}" in text
    for kind in ("catalog", "visual", "markup", "view", "presentation"):
        assert f"`{kind}`" in text
    assert "fresh,\nQA-valid reviewing candidate" in text
    assert "facetta-staging-isolation.v5" in text or "The v5 probe" in text


def test_frozen_corpus_readme_retains_run_identity_and_noclobber_guards() -> None:
    text = CORPUS_README.read_text(encoding="utf-8")
    bash = "\n".join(_bash_blocks(text))

    _assert_fresh_run_directory(
        text,
        run_id="CORPUS_RUN_ID",
        directory="CORPUS_DIR",
        requirement="preassign a fresh corpus run ID",
    )
    assert "mkdir -p" not in bash
    assert "preassign fresh `STAGING_RUN_ID` and `EXTERNAL_RELEASE_RUN_ID`" in text
    assert "external-beta/$EXTERNAL_RELEASE_RUN_ID" in text
    assert '> "$CORPUS_DIR/command-result.json"' in bash
    assert '> "$CORPUS_DIR/final-command-result.json"' in bash
    assert '> "$CORPUS_DIR/exit-code.txt"' in bash
    assert '> "$CORPUS_DIR/final-exit-code.txt"' in bash
    _assert_redirects_are_noclobber_protected(text)

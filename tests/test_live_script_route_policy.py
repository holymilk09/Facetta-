from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize(
    "relative_path",
    (
        "scripts/run_designer_corrected_e2e.py",
        "scripts/run_standard_halo_full_e2e.py",
        "scripts/run_live_edit_factory_e2e.py",
        "scripts/run_necklace_chain_catalog_eval.py",
    ),
)
def test_exact_reference_scripts_use_canonical_studio_import(
    relative_path: str,
) -> None:
    source = (ROOT / relative_path).read_text()

    assert "/studio/projects/import-confirmed" in source
    assert "/projects/from-image" not in source


@pytest.mark.parametrize(
    "relative_path",
    (
        "scripts/run_live_edit_factory_e2e.py",
        "scripts/run_necklace_chain_catalog_eval.py",
    ),
)
def test_live_catalog_scripts_never_use_direct_apply(relative_path: str) -> None:
    source = (ROOT / relative_path).read_text()

    assert "/catalog/apply" not in source
    assert "/catalog/preview" in source
    assert '["preview_url"]' in source
    assert '["discard_url"]' in source


def test_factory_edit_requires_explicit_acceptance_before_revision() -> None:
    source = (ROOT / "scripts/run_live_edit_factory_e2e.py").read_text()

    assert 'candidate["accept_url"]' in source
    assert 'sys.stdin.readline().strip() != "ACCEPT"' in source
    assert 'candidate["discard_url"]' in source


def test_necklace_direction_is_review_only_or_saved_as_variation() -> None:
    source = (ROOT / "scripts/run_necklace_chain_catalog_eval.py").read_text()

    assert 'choices=("save-as-variation", "discard")' in source
    assert 'candidate["save_as_variation_url"]' in source
    assert '"catalog_preview_review_required"' in source
    assert '"catalog_variation_saved"' in source


def test_active_studio_sentence_creation_uses_category_neutral_prompt() -> None:
    workspace = (ROOT / "mobile/src/studio/StudioCreateWorkspace.tsx").read_text()
    app_shell = (ROOT / "mobile/App.tsx").read_text()

    assert "'createFromPrompt' | 'createFromDrawing'" in workspace
    assert "gateway.createFromPrompt" in workspace
    assert "createFromBrief" not in workspace
    assert "TrustedWorkflowScreen" not in app_shell


def test_structured_ring_brief_is_evaluation_compatibility_only() -> None:
    harness = (ROOT / "scripts/run_prompt_brief_e2e.py").read_text()
    inventory = (ROOT / "docs/trusted-workflow-route-inventory.md").read_text()
    client = (ROOT / "mobile/src/trusted/client.ts").read_text()
    gateway = (ROOT / "mobile/src/studio/gateway.ts").read_text()

    assert '"/projects/from-brief"' in harness
    assert "`POST /projects/from-brief` | Deprecated compatibility" in inventory
    assert "Active Studio sentence creation uses `POST /projects/from-prompt`" in inventory
    assert "@deprecated Hidden structured-ring compatibility" in client
    assert "@deprecated Hidden structured-ring compatibility" in gateway

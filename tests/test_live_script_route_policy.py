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


def test_legacy_trusted_workspace_is_quarantined_from_active_mobile_surface() -> None:
    mobile_root = ROOT / "mobile"
    studio_root = mobile_root / "src/studio"
    active_sources = [mobile_root / "App.tsx"] + sorted(
        path
        for pattern in ("*.ts", "*.tsx")
        for path in studio_root.glob(pattern)
        if ".test." not in path.name
    )
    compatibility_symbols = (
        "TrustedWorkflowScreen",
        "TrustedWorkspaceEntry",
        "TRUSTED_WORKSPACE_ENABLED",
        "useTrustedWorkflow",
        "workflowState",
    )

    for path in active_sources:
        source = path.read_text()
        for symbol in compatibility_symbols:
            assert symbol not in source, f"{path.relative_to(ROOT)} imports {symbol}"

    trusted_barrel = (mobile_root / "src/trusted/index.ts").read_text()
    for symbol in compatibility_symbols:
        assert symbol not in trusted_barrel

    # Preserve the hidden harness and its migration callers until the founder,
    # history, OpenAPI, and replacement-coverage deletion gates pass.
    compatibility_entry = mobile_root / "src/trusted/TrustedWorkspaceEntry.tsx"
    compatibility_screen = mobile_root / "src/trusted/TrustedWorkflowScreen.tsx"
    compatibility_workflow = mobile_root / "src/trusted/useTrustedWorkflow.ts"
    compatibility_state = mobile_root / "src/trusted/workflowState.ts"
    assert all(path.is_file() for path in (
        compatibility_entry,
        compatibility_screen,
        compatibility_workflow,
        compatibility_state,
    ))
    assert "TrustedWorkflowScreen" in compatibility_entry.read_text()
    workflow_source = compatibility_workflow.read_text()
    assert "api.createBeautyRender(" in workflow_source
    assert "api.createProductPhoto(" in workflow_source


def test_structured_ring_brief_is_evaluation_compatibility_only() -> None:
    harness = (ROOT / "scripts/run_prompt_brief_e2e.py").read_text()
    inventory = (ROOT / "docs/trusted-workflow-route-inventory.md").read_text()
    client = (ROOT / "mobile/src/trusted/client.ts").read_text()
    trusted_workflow = (ROOT / "mobile/src/trusted/useTrustedWorkflow.ts").read_text()
    gateway = (ROOT / "mobile/src/studio/gateway.ts").read_text()

    assert '"/projects/from-brief"' in harness
    assert "`POST /projects/from-brief` | Deprecated compatibility" in inventory
    assert "Active Studio sentence creation uses `POST /projects/from-prompt`" in inventory
    assert "@deprecated Hidden structured-ring compatibility" in client
    assert "createProjectFromBrief(request" in client
    assert "createFromBrief" in trusted_workflow
    assert "createFromBrief" not in gateway
    assert "createProjectFromBrief" not in gateway
    assert "CreateProjectFromBriefRequest" not in gateway


def test_legacy_creative_selection_is_not_an_active_studio_boundary() -> None:
    inventory = (ROOT / "docs/trusted-workflow-route-inventory.md").read_text()
    client = (ROOT / "mobile/src/trusted/client.ts").read_text()
    gateway = (ROOT / "mobile/src/studio/gateway.ts").read_text()
    workspace = (ROOT / "mobile/src/studio/StudioCreateWorkspace.tsx").read_text()
    acceptance = (
        ROOT / "mobile/scripts/studio_client_api_acceptance.ts"
    ).read_text()

    assert (
        "`POST /projects/{project_id}/creative-candidates/{candidate_id}/select` "
        "| Deprecated compatibility"
    ) in inventory
    assert "@deprecated Compatibility-only selection" in client
    assert "selectCreativeCandidate" not in gateway
    assert "selectCreativeDirection" not in gateway
    assert "completeCreativeDirectionReview" in workspace
    assert "gateway.selectCreativeDirection" not in acceptance
    assert "trustedClient.selectCreativeCandidate" not in acceptance


def test_active_studio_presentations_cannot_fall_back_to_legacy_project_routes() -> None:
    client = (ROOT / "mobile/src/trusted/client.ts").read_text()
    gateway = (ROOT / "mobile/src/studio/gateway.ts").read_text()
    compatibility_workflow = (
        ROOT / "mobile/src/trusted/useTrustedWorkflow.ts"
    ).read_text()

    beauty_method = client.split(
        "    createStudioBeautyRender(", 1,
    )[1].split("async createProductPhoto", 1)[0]
    product_method = client.split(
        "    createStudioProductPhoto(", 1,
    )[1].split("async createMarketingPack", 1)[0]

    assert "/studio/projects/" in beauty_method
    assert "`/projects/" not in beauty_method
    assert "/studio/projects/" in product_method
    assert "`/projects/" not in product_method
    assert "client.createStudioBeautyRender(" in gateway
    assert "client.createStudioProductPhoto(" in gateway
    assert "client.createBeautyRender(" not in gateway
    assert "client.createProductPhoto(" not in gateway

    # Compatibility remains isolated until the founder and history gates pass.
    assert "api.createBeautyRender(" in compatibility_workflow
    assert "api.createProductPhoto(" in compatibility_workflow

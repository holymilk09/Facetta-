import runpy
from pathlib import Path

from facetta.api.projects import ProjectFromBriefRequest

HARNESS = runpy.run_path(str(
    Path(__file__).resolve().parent.parent / "scripts" / "run_prompt_brief_e2e.py"
))
DEFAULT_BRIEF = HARNESS["DEFAULT_BRIEF"]
EXPECTED_PROMPT_VERSIONS = HARNESS["EXPECTED_PROMPT_VERSIONS"]
TEST_ACTOR = HARNESS["TEST_ACTOR"]
run_contract = HARNESS["run_contract"]
run_preflight = HARNESS["run_preflight"]


def _request() -> ProjectFromBriefRequest:
    return ProjectFromBriefRequest(
        brief=DEFAULT_BRIEF,
        owner=TEST_ACTOR,
        title="Offline prompt workflow contract",
        collection="Evaluation",
        tags=["contract"],
        variant=0,
    )


def test_prompt_brief_preflight_compiles_current_contracts_without_provider_calls(
    tmp_path,
):
    outdir = tmp_path / "preflight"
    outdir.mkdir()

    result = run_preflight(outdir, _request())

    assert result["provider_calls"] == 0
    contracts = result["prompt_contracts"]
    assert contracts["observed_versions"] == EXPECTED_PROMPT_VERSIONS
    assert all(
        length <= contracts["provider_prompt_limit_chars"]
        for length in contracts["prompt_lengths"].values()
    )
    assert result["review_policy"]["warning_auto_accept"] is False
    assert (outdir / "results.json").exists()


def test_prompt_brief_contract_stops_at_warnings_and_proves_failure_atomicity(
    tmp_path,
):
    outdir = tmp_path / "contract"
    outdir.mkdir()

    result = run_contract(
        outdir,
        _request(),
        test_accept_concept_warning=False,
        test_accept_spec_warning=False,
    )

    assert result["provider_calls"] == 0
    assert result["provider_cost"] == 0
    concept = result["scenarios"]["concept_warning"]
    spec = result["scenarios"]["spec_warning"]
    assert concept["status"] == "stopped_for_concept_review"
    assert spec["status"] == "stopped_for_spec_render_review"
    assert concept["accepted_warning_stages"] == []
    assert spec["accepted_warning_stages"] == []
    assert concept["database_after"]["projects"] == 0
    assert spec["database_after"]["projects"] == 0
    assert list((outdir / "concept-warning").glob("*warning-preview.png"))
    assert list((outdir / "spec-warning").glob("*warning-preview.png"))
    terminal = result["scenarios"]["terminal_failure"]
    assert terminal["http_status"] == 422
    assert terminal["partial_product_records"] is False
    assert terminal["product_counts_after"] == {
        "designs": 0,
        "versions": 0,
        "assets": 0,
        "projects": 0,
    }


def test_prompt_brief_contract_accepts_warnings_only_with_explicit_test_flags(
    tmp_path,
):
    outdir = tmp_path / "contract-accept"
    outdir.mkdir()

    result = run_contract(
        outdir,
        _request(),
        test_accept_concept_warning=True,
        test_accept_spec_warning=True,
    )

    concept = result["scenarios"]["concept_warning"]
    spec = result["scenarios"]["spec_warning"]
    assert concept["status"] == "project_created"
    assert spec["status"] == "project_created"
    assert concept["accepted_warning_stages"] == ["concept"]
    assert spec["accepted_warning_stages"] == ["spec_render"]
    assert concept["acceptance_role"] == "unapproved_test_actor"
    assert spec["acceptance_role"] == "unapproved_test_actor"
    assert concept["founder_approval"] is False
    assert spec["founder_approval"] is False

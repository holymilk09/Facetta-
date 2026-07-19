import base64
import json
import re
from urllib.parse import parse_qs, urlparse

import pytest

from scripts.run_staging_two_user_isolation import (
    CandidateFixture,
    HttpResult,
    StagingConfig,
    StagingIdentity,
    load_config,
    run_probe,
)


def _candidate(kind: str, suffix: str) -> dict[str, object]:
    run_id = f"{kind}-run-{suffix}"
    candidate_id = f"{kind}-candidate-{suffix}"
    studio_job_id = f"{kind}-job-{suffix}"
    expires_at = "2099-01-01T00:00:00+00:00"
    source_hash = suffix * 64
    base: dict[str, object] = {
        "candidate_id": f"{kind}-candidate-{suffix}",
        "image_run_id": f"{kind}-run-{suffix}",
        "source_asset_id": f"asset-{suffix}",
        "studio_job_id": studio_job_id,
    }
    if kind == "catalog":
        path = f"/image-runs/{run_id}/catalog-candidates/{candidate_id}"
        return {
            **base,
            "component_path": "ring.band",
            "option_id": "white-gold",
            "requested_change": "Change the visible metal finish.",
            "verdict": "review_required",
            "preview_url": f"{path}/image",
            "save_as_variation_url": f"{path}/save-as-variation",
            "next_spec": {},
            "spec_change": [],
            "qa": {},
            "routing": {},
            "expires_at": expires_at,
        }
    if kind == "visual":
        path = f"/studio/image-runs/{run_id}/visual-candidates/{candidate_id}"
        return {
            **base,
            "preview_url": f"{path}/image",
            "save_as_variation_url": f"{path}/save-as-variation",
            "verdict": "review_required",
            "requested_change": "Change the visible metal finish.",
            "scope": "appearance",
            "qa": {},
            "expires_at": expires_at,
        }
    if kind == "markup":
        path = f"/studio/markup-candidates/{run_id}/{candidate_id}"
        return {
            **base,
            "project_root_id": f"project-{suffix}",
            "expected_active_asset_id": f"asset-{suffix}",
            "design_version": 1,
            "source_sha256": source_hash,
            "output_sha256": ("c" if suffix == "a" else "d") * 64,
            "operation": "reference_render",
            "requested_change": "Refine the marked prong.",
            "region_description": "upper-left prong",
            "qa": {},
            "routing": {},
            "status": "reviewing",
            "expires_at": expires_at,
            "preview_url": f"{path}/image",
            "accept_url": f"{path}/accept",
            "discard_url": f"{path}/discard",
            "save_as_variation_url": f"{path}/save-as-variation",
        }
    if kind == "view":
        path = f"/studio/view-candidates/{run_id}/{candidate_id}"
        return {
            **base,
            "project_id": f"project-{suffix}",
            "source_sha256": source_hash,
            "design_version": 1,
            "view": "front",
            "qa": {},
            "status": "reviewing",
            "accepted_asset_id": None,
            "expires_at": expires_at,
            "preview_url": f"{path}/image?owner={suffix * 32}",
        }
    if kind == "presentation":
        path = (
            f"/studio/image-runs/{run_id}/presentation-candidates/{candidate_id}"
        )
        return {
            **base,
            "project_id": f"project-{suffix}",
            "source_sha256": source_hash,
            "design_version": 1,
            "destination": "client",
            "capability": "lookbook",
            "preset": "editorial",
            "framing": "centered",
            "qa": {},
            "status": "reviewing",
            "accepted_asset_id": None,
            "expires_at": expires_at,
            "preview_url": f"{path}/image?owner={suffix * 32}",
        }
    raise AssertionError(f"unsupported candidate kind: {kind}")


def _job(job_id: str, suffix: str) -> dict[str, object]:
    return {
        "job_id": job_id,
        "owner": suffix * 32,
        "action_id": "refine",
        "lane": "fast_visual",
        "status": "reviewing",
        "progress": 0.5,
        "active_design_id": f"project-{suffix}",
        "source_revision_id": f"asset-{suffix}",
        "accepted_output_sha256": None,
        "error_code": None,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:01:00+00:00",
        "billing": {
            "requested_outputs": 1,
            "credits_per_output": 3,
            "estimated_credits": 3,
            "completed_outputs": 1,
            "charged_outputs": 0,
            "charged_credits": 0,
            "policy": "Only accepted outputs are charged.",
        },
    }


def _jobs(suffix: str) -> list[dict[str, object]]:
    return [
        _job(f"job-{suffix}", suffix),
        *[
            _job(f"{kind}-job-{suffix}", suffix)
            for kind in ("catalog", "visual", "markup", "view", "presentation")
        ],
    ]


def _jwt(subject: str) -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps({"sub": subject}).encode()
    ).decode()
    return f"fixture.{payload.rstrip('=')}.signature"


def _candidate_fixture_json(suffix: str) -> str:
    return json.dumps({
        kind: {
            "run_id": f"{kind}-run-{suffix}",
            "candidate_id": f"{kind}-candidate-{suffix}",
            "source_asset_id": f"asset-{suffix}",
            "studio_job_id": f"{kind}-job-{suffix}",
        }
        for kind in ("catalog", "visual", "markup", "view", "presentation")
    })


def _config() -> StagingConfig:
    def identity(label: str, token: str, actor: str) -> StagingIdentity:
        suffix = label.lower()
        return StagingIdentity(
            label,
            token,
            actor,
            f"project-{suffix}",
            f"family-{suffix}",
            f"asset-{suffix}",
            f"job-{suffix}",
            tuple(
                CandidateFixture(
                    kind,
                    f"{kind}-run-{suffix}",
                    f"{kind}-candidate-{suffix}",
                    f"asset-{suffix}",
                    f"{kind}-job-{suffix}",
                )
                for kind in (
                    "catalog", "markup", "presentation", "view", "visual",
                )
            ),
        )

    return StagingConfig(
        base_url="https://staging.facetta.test",
        deployment_revision="0123456789abcdef",
        staging_run_id="staging-run-fixture-v1",
        external_release_run_id="external-release-fixture-v1",
        first=identity("A", "secret-a", "a" * 32),
        second=identity("B", "secret-b", "b" * 32),
    )


def test_load_config_requires_and_binds_seeded_jobs_and_candidates(monkeypatch):
    monkeypatch.setenv("FACETTA_STAGING_BASE_URL", "https://staging.facetta.test")
    monkeypatch.setenv("FACETTA_STAGING_DEPLOYMENT_REVISION", "0123456789abcdef")
    monkeypatch.setenv("FACETTA_STAGING_RUN_ID", "staging-run-fixture-v1")
    monkeypatch.setenv(
        "FACETTA_EXTERNAL_RELEASE_RUN_ID", "external-release-fixture-v1",
    )
    for label, suffix, subject in (
        ("A", "a", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        ("B", "b", "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
    ):
        prefix = f"FACETTA_STAGING_USER_{label}"
        monkeypatch.setenv(f"{prefix}_ACCESS_TOKEN", _jwt(subject))
        monkeypatch.setenv(f"{prefix}_PROJECT_ID", f"project-{suffix}")
        monkeypatch.setenv(f"{prefix}_FAMILY_ID", f"family-{suffix}")
        monkeypatch.setenv(f"{prefix}_ASSET_ID", f"asset-{suffix}")
        monkeypatch.setenv(f"{prefix}_JOB_ID", f"job-{suffix}")
        monkeypatch.setenv(
            f"{prefix}_CANDIDATE_FIXTURES_JSON",
            _candidate_fixture_json(suffix),
        )

    config = load_config()

    assert config.first.job_id == "job-a"
    assert config.second.job_id == "job-b"
    assert config.staging_run_id == "staging-run-fixture-v1"
    assert config.external_release_run_id == "external-release-fixture-v1"
    assert {candidate.kind for candidate in config.first.candidates} == {
        "catalog", "visual", "markup", "view", "presentation",
    }
    assert config.first.candidate("visual").candidate_id == "visual-candidate-a"
    assert config.first.candidate("visual").source_asset_id == "asset-a"
    assert config.first.candidate("visual").studio_job_id == "visual-job-a"


def test_load_config_rejects_incomplete_candidate_fixture_set(monkeypatch):
    monkeypatch.setenv("FACETTA_STAGING_BASE_URL", "https://staging.facetta.test")
    monkeypatch.setenv("FACETTA_STAGING_DEPLOYMENT_REVISION", "0123456789abcdef")
    monkeypatch.setenv("FACETTA_STAGING_RUN_ID", "staging-run-fixture-v1")
    monkeypatch.setenv(
        "FACETTA_EXTERNAL_RELEASE_RUN_ID", "external-release-fixture-v1",
    )
    for label, suffix, subject in (
        ("A", "a", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        ("B", "b", "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
    ):
        prefix = f"FACETTA_STAGING_USER_{label}"
        monkeypatch.setenv(f"{prefix}_ACCESS_TOKEN", _jwt(subject))
        monkeypatch.setenv(f"{prefix}_PROJECT_ID", f"project-{suffix}")
        monkeypatch.setenv(f"{prefix}_FAMILY_ID", f"family-{suffix}")
        monkeypatch.setenv(f"{prefix}_ASSET_ID", f"asset-{suffix}")
        monkeypatch.setenv(f"{prefix}_JOB_ID", f"job-{suffix}")
        fixtures = json.loads(_candidate_fixture_json(suffix))
        if label == "A":
            fixtures.pop("presentation")
        monkeypatch.setenv(
            f"{prefix}_CANDIDATE_FIXTURES_JSON",
            json.dumps(fixtures),
        )

    with pytest.raises(ValueError, match="must exactly cover"):
        load_config()


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda fixtures: fixtures["catalog"].pop("studio_job_id"),
            "candidate fixture is invalid",
        ),
        (
            lambda fixtures: fixtures["catalog"].update({
                "source_asset_id": "asset-foreign",
            }),
            "candidate identifiers are unsafe",
        ),
        (
            lambda fixtures: fixtures["catalog"].update({
                "studio_job_id": fixtures["visual"]["studio_job_id"],
            }),
            "must bind distinct Studio jobs",
        ),
    ],
)
def test_load_config_rejects_unbound_candidate_lineage(
    monkeypatch,
    mutate,
    message: str,
):
    monkeypatch.setenv("FACETTA_STAGING_BASE_URL", "https://staging.facetta.test")
    monkeypatch.setenv("FACETTA_STAGING_DEPLOYMENT_REVISION", "0123456789abcdef")
    monkeypatch.setenv("FACETTA_STAGING_RUN_ID", "staging-run-fixture-v1")
    monkeypatch.setenv(
        "FACETTA_EXTERNAL_RELEASE_RUN_ID", "external-release-fixture-v1",
    )
    for label, suffix, subject in (
        ("A", "a", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        ("B", "b", "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
    ):
        prefix = f"FACETTA_STAGING_USER_{label}"
        monkeypatch.setenv(f"{prefix}_ACCESS_TOKEN", _jwt(subject))
        monkeypatch.setenv(f"{prefix}_PROJECT_ID", f"project-{suffix}")
        monkeypatch.setenv(f"{prefix}_FAMILY_ID", f"family-{suffix}")
        monkeypatch.setenv(f"{prefix}_ASSET_ID", f"asset-{suffix}")
        monkeypatch.setenv(f"{prefix}_JOB_ID", f"job-{suffix}")
        fixtures = json.loads(_candidate_fixture_json(suffix))
        if label == "A":
            mutate(fixtures)
        monkeypatch.setenv(
            f"{prefix}_CANDIDATE_FIXTURES_JSON", json.dumps(fixtures),
        )

    with pytest.raises(ValueError, match=message):
        load_config()


def _transport(method: str, url: str, token: str) -> HttpResult:
    assert method in {"GET", "OPTIONS"}
    if method == "OPTIONS":
        return HttpResult(404)
    if url.endswith("/health"):
        return HttpResult(200, "application/json", {
            "status": "ok",
            "service": "facetta",
            "deployment_revision": "0123456789abcdef",
            "persistence_backend": "postgresql",
        })
    if token == "":
        return HttpResult(401)
    parsed = urlparse(url)
    path = parsed.path
    query = parse_qs(parsed.query)
    actor = "a" * 32 if token == "secret-a" else "b" * 32
    own_suffix = "a" if token == "secret-a" else "b"
    other_suffix = "b" if own_suffix == "a" else "a"
    if url.endswith(f"/projects/project-{own_suffix}"):
        return HttpResult(200, "application/json", {"owner": actor})
    if url.endswith(f"/projects/project-{other_suffix}"):
        return HttpResult(403)
    if url.endswith(f"/studio/projects/project-{own_suffix}/history"):
        return HttpResult(200, "application/json", {"project_id": f"project-{own_suffix}"})
    if url.endswith(f"/studio/projects/project-{other_suffix}/history"):
        return HttpResult(403)
    if url.endswith(f"/assets/asset-{own_suffix}/image"):
        return HttpResult(200, "image/png")
    if url.endswith(f"/assets/asset-{other_suffix}/image"):
        return HttpResult(403)
    if url.endswith(f"/studio/families/family-{own_suffix}"):
        return HttpResult(200, "application/json", {"family_id": f"family-{own_suffix}"})
    if url.endswith(f"/studio/families/family-{other_suffix}"):
        return HttpResult(404)

    for extension, content_type in (
        ("/factory-pack", "application/json"),
        ("/factory-pack.zip", "application/zip"),
    ):
        if path == f"/projects/project-{own_suffix}{extension}":
            return HttpResult(200, content_type)
        if path == f"/projects/project-{other_suffix}{extension}":
            return HttpResult(403)

    if path == f"/assets/asset-{own_suffix}/checklist":
        return HttpResult(200, "application/json", {"asset_id": f"asset-{own_suffix}"})
    if path == f"/assets/asset-{other_suffix}/checklist":
        return HttpResult(403)
    if path == f"/assets/asset-{own_suffix}/studio-component-targeting":
        return HttpResult(200, "application/json", {"asset_id": f"asset-{own_suffix}"})
    if path == f"/assets/asset-{other_suffix}/studio-component-targeting":
        return HttpResult(403)

    if path == f"/studio/jobs/{'job-' + own_suffix}":
        if query.get("owner") != [actor]:
            return HttpResult(403)
        return HttpResult(
            200,
            "application/json",
            _job(f"job-{own_suffix}", own_suffix),
        )
    if path == f"/studio/jobs/{'job-' + other_suffix}":
        if query.get("owner") != [actor]:
            return HttpResult(403)
        return HttpResult(404)
    if path == "/studio/jobs":
        if query.get("owner") != [actor]:
            return HttpResult(403)
        return HttpResult(
            200, "application/json", {"jobs": _jobs(own_suffix)},
        )

    if path == f"/assets/asset-{own_suffix}/catalog/previews":
        return HttpResult(200, "application/json", {
            "candidates": [_candidate("catalog", own_suffix)],
        })
    if path == f"/assets/asset-{other_suffix}/catalog/previews":
        return HttpResult(404)

    for kind in ("visual", "markup"):
        if path == f"/studio/projects/project-{own_suffix}/{kind}-candidates":
            return HttpResult(200, "application/json", {
                "candidates": [_candidate(kind, own_suffix)],
            })
        if path == f"/studio/projects/project-{other_suffix}/{kind}-candidates":
            return HttpResult(404)

    for kind, list_path in (
        ("view", "/studio/view-candidates"),
        ("presentation", "/studio/presentation-candidates"),
    ):
        if path == list_path:
            if (
                query.get("owner") != [actor]
                or query.get("project_id") != [f"project-{own_suffix}"]
            ):
                return HttpResult(403)
            return HttpResult(200, "application/json", {
                "candidates": [_candidate(kind, own_suffix)],
            })

    candidate_patterns = {
        "catalog": re.compile(
            r"^/image-runs/catalog-run-([ab])/catalog-candidates/"
            r"catalog-candidate-\1/image$"
        ),
        "visual": re.compile(
            r"^/studio/image-runs/visual-run-([ab])/visual-candidates/"
            r"visual-candidate-\1/image$"
        ),
        "markup": re.compile(
            r"^/studio/markup-candidates/markup-run-([ab])/"
            r"markup-candidate-\1/image$"
        ),
        "view": re.compile(
            r"^/studio/view-candidates/view-run-([ab])/"
            r"view-candidate-\1/image$"
        ),
        "presentation": re.compile(
            r"^/studio/image-runs/presentation-run-([ab])/"
            r"presentation-candidates/presentation-candidate-\1/image$"
        ),
    }
    for kind, pattern in candidate_patterns.items():
        match = pattern.fullmatch(path)
        if match is None:
            continue
        candidate_suffix = match.group(1)
        if kind in {"view", "presentation"}:
            candidate_actor = "a" * 32 if candidate_suffix == "a" else "b" * 32
            if query.get("owner") != [candidate_actor] or candidate_suffix != own_suffix:
                return HttpResult(403)
        elif candidate_suffix != own_suffix:
            return HttpResult(404)
        return HttpResult(200, "image/png")

    if f"owner={actor}" in url:
        return HttpResult(200, "application/json", {
            "families": [{"owner": actor, "family_id": f"family-{own_suffix}"}],
        })
    if "/studio/families?" in url:
        return HttpResult(403)
    return HttpResult(404)


def test_read_only_two_user_probe_passes_without_logging_secrets():
    result = run_probe(_config(), _transport)
    assert result["passed"] is True
    assert result["provider_calls"] == 0
    assert result["mutations"] == 0
    assert result["schema_version"] == "facetta-staging-isolation.v7"
    assert result["target"]["deployment_revision"] == "0123456789abcdef"
    assert result["target"]["staging_run_id"] == "staging-run-fixture-v1"
    assert (
        result["target"]["external_release_run_id"]
        == "external-release-fixture-v1"
    )
    assert len(result["target"]["origin_sha256"]) == 64
    assert len(result["target"]["fixture_set_sha256"]) == 64
    assert "secret-a" not in str(result)
    assert "secret-b" not in str(result)


def test_cross_tenant_project_success_fails_probe():
    def leaky_transport(method: str, url: str, token: str) -> HttpResult:
        result = _transport(method, url, token)
        if token == "secret-a" and url.endswith("/projects/project-b"):
            return HttpResult(200, "application/json", {"owner": "b" * 32})
        return result

    result = run_probe(_config(), leaky_transport)
    failed = {check["name"] for check in result["checks"] if not check["passed"]}
    assert "user_A_cannot_read_other_project" in failed
    assert result["passed"] is False


@pytest.mark.parametrize(
    ("path", "expected_check"),
    [
        (
            "/projects/project-b/factory-pack",
            "user_A_cannot_read_other_factory_pack",
        ),
        (
            "/projects/project-b/factory-pack.zip",
            "user_A_cannot_download_other_factory_pack",
        ),
        (
            "/assets/asset-b/checklist",
            "user_A_cannot_read_other_checklist",
        ),
        (
            "/assets/asset-b/studio-component-targeting",
            "user_A_cannot_read_other_component_targeting",
        ),
        (
            "/assets/asset-b/catalog/previews",
            "user_A_cannot_list_other_catalog_previews",
        ),
        (
            "/studio/projects/project-b/visual-candidates",
            "user_A_cannot_list_other_visual_candidates",
        ),
        (
            "/studio/projects/project-b/markup-candidates",
            "user_A_cannot_list_other_markup_candidates",
        ),
    ],
)
def test_cross_tenant_canonical_read_leak_fails_probe(
    path: str,
    expected_check: str,
):
    def leaky_transport(method: str, url: str, token: str) -> HttpResult:
        if method == "GET" and token == "secret-a" and urlparse(url).path == path:
            return HttpResult(200, "application/json", {})
        return _transport(method, url, token)

    result = run_probe(_config(), leaky_transport)
    failed = {check["name"] for check in result["checks"] if not check["passed"]}
    assert failed == {expected_check}
    assert result["passed"] is False


@pytest.mark.parametrize(
    ("path", "expected_check"),
    [
        (
            "/image-runs/catalog-run-b/catalog-candidates/"
            "catalog-candidate-b/image",
            "user_A_cannot_read_other_catalog_candidate_image",
        ),
        (
            "/studio/image-runs/visual-run-b/visual-candidates/"
            "visual-candidate-b/image",
            "user_A_cannot_read_other_visual_candidate_image",
        ),
        (
            "/studio/markup-candidates/markup-run-b/markup-candidate-b/image",
            "user_A_cannot_read_other_markup_candidate_image",
        ),
        (
            "/studio/view-candidates/view-run-b/view-candidate-b/image",
            "user_A_cannot_read_other_view_candidate_image",
        ),
        (
            "/studio/image-runs/presentation-run-b/presentation-candidates/"
            "presentation-candidate-b/image",
            "user_A_cannot_read_other_presentation_candidate_image",
        ),
    ],
)
def test_cross_tenant_candidate_image_leak_fails_probe(
    path: str,
    expected_check: str,
):
    def leaky_transport(method: str, url: str, token: str) -> HttpResult:
        if method == "GET" and token == "secret-a" and urlparse(url).path == path:
            return HttpResult(200, "image/png")
        return _transport(method, url, token)

    result = run_probe(_config(), leaky_transport)
    failed = {check["name"] for check in result["checks"] if not check["passed"]}
    assert failed == {expected_check}
    assert result["passed"] is False


def test_studio_job_owner_spoof_and_cross_object_leaks_fail_probe():
    def leaky_transport(method: str, url: str, token: str) -> HttpResult:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        if method == "GET" and token == "secret-a":
            if parsed.path == "/studio/jobs" and query.get("owner") == ["b" * 32]:
                return HttpResult(200, "application/json", {"jobs": []})
            if parsed.path == "/studio/jobs/job-b":
                return HttpResult(200, "application/json", {
                    "job_id": "job-b", "owner": "b" * 32,
                })
        return _transport(method, url, token)

    result = run_probe(_config(), leaky_transport)
    failed = {check["name"] for check in result["checks"] if not check["passed"]}
    assert failed == {
        "user_A_cannot_read_other_job",
        "user_A_cannot_spoof_job_owner",
    }
    assert result["passed"] is False


def test_leaky_own_job_list_fails_tenant_scope_check():
    def leaky_transport(method: str, url: str, token: str) -> HttpResult:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        if (
            method == "GET"
            and token == "secret-a"
            and parsed.path == "/studio/jobs"
            and query.get("owner") == ["a" * 32]
        ):
            return HttpResult(200, "application/json", {
                "jobs": [
                    *_jobs("a"),
                    _job("job-b", "b"),
                ],
            })
        return _transport(method, url, token)

    result = run_probe(_config(), leaky_transport)
    failed = {check["name"] for check in result["checks"] if not check["passed"]}
    assert failed == {"user_A_job_results_are_tenant_scoped"}
    assert result["passed"] is False


@pytest.mark.parametrize(
    "jobs",
    [
        [*_jobs("a"), _job("job-a", "a")],
        [{**_jobs("a")[0], "active_design_id": "project-b"}, *_jobs("a")[1:]],
        [{**_jobs("a")[0], "source_revision_id": "asset-b"}, *_jobs("a")[1:]],
        [*_jobs("a"), {**_job("extra-job-a", "a"), "billing": "malformed"}],
    ],
)
def test_job_list_rejects_duplicates_malformed_rows_and_project_mismatches(
    jobs: list[object],
):
    def invalid_transport(method: str, url: str, token: str) -> HttpResult:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        if (
            method == "GET"
            and token == "secret-a"
            and parsed.path == "/studio/jobs"
            and query.get("owner") == ["a" * 32]
        ):
            return HttpResult(200, "application/json", {"jobs": jobs})
        return _transport(method, url, token)

    result = run_probe(_config(), invalid_transport)
    failed = {check["name"] for check in result["checks"] if not check["passed"]}
    assert failed == {"user_A_job_results_are_tenant_scoped"}
    assert result["passed"] is False


@pytest.mark.parametrize(
    ("kind", "path"),
    [
        ("catalog", "/assets/asset-a/catalog/previews"),
        ("visual", "/studio/projects/project-a/visual-candidates"),
        ("markup", "/studio/projects/project-a/markup-candidates"),
        ("view", "/studio/view-candidates"),
        ("presentation", "/studio/presentation-candidates"),
    ],
)
def test_leaky_own_candidate_lists_fail_tenant_scope_check(
    kind: str,
    path: str,
):
    def leaky_transport(method: str, url: str, token: str) -> HttpResult:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        is_own_scoped_query = kind not in {"view", "presentation"} or (
            query.get("owner") == ["a" * 32]
            and query.get("project_id") == ["project-a"]
        )
        if (
            method == "GET"
            and token == "secret-a"
            and parsed.path == path
            and is_own_scoped_query
        ):
            return HttpResult(200, "application/json", {
                "candidates": [_candidate(kind, "a"), _candidate(kind, "b")],
            })
        return _transport(method, url, token)

    result = run_probe(_config(), leaky_transport)
    failed = {check["name"] for check in result["checks"] if not check["passed"]}
    assert failed == {
        f"user_A_{kind}_candidate_results_are_tenant_scoped",
    }
    assert result["passed"] is False


@pytest.mark.parametrize(
    ("body", "kind", "path"),
    [
        (
            {"candidates": [_candidate("catalog", "a")] * 2},
            "catalog",
            "/assets/asset-a/catalog/previews",
        ),
        (
            {"candidates": [_candidate("visual", "a"), "malformed"]},
            "visual",
            "/studio/projects/project-a/visual-candidates",
        ),
        (
            {
                "candidates": [{
                    **_candidate("visual", "a"),
                    "studio_job_id": "foreign-job",
                }],
            },
            "visual",
            "/studio/projects/project-a/visual-candidates",
        ),
        (
            {
                "candidates": [{
                    **_candidate("markup", "a"),
                    "project_root_id": "project-b",
                }],
            },
            "markup",
            "/studio/projects/project-a/markup-candidates",
        ),
        (
            {
                "candidates": [{
                    **_candidate("presentation", "a"),
                    "source_asset_id": "asset-b",
                }],
            },
            "presentation",
            "/studio/presentation-candidates",
        ),
        (
            {
                "candidates": [{
                    **_candidate("view", "a"),
                    "preview_url": "/studio/view-candidates/wrong/image",
                }],
            },
            "view",
            "/studio/view-candidates",
        ),
    ],
)
def test_candidate_lists_reject_duplicates_malformed_rows_and_lineage_mismatches(
    body: dict[str, object],
    kind: str,
    path: str,
):
    def invalid_transport(method: str, url: str, token: str) -> HttpResult:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        is_own_scoped_query = kind not in {"view", "presentation"} or (
            query.get("owner") == ["a" * 32]
            and query.get("project_id") == ["project-a"]
        )
        if (
            method == "GET"
            and token == "secret-a"
            and parsed.path == path
            and is_own_scoped_query
        ):
            return HttpResult(200, "application/json", body)
        return _transport(method, url, token)

    result = run_probe(_config(), invalid_transport)
    failed = {check["name"] for check in result["checks"] if not check["passed"]}
    assert failed == {
        f"user_A_{kind}_candidate_results_are_tenant_scoped",
    }
    assert result["passed"] is False


@pytest.mark.parametrize(
    ("path", "expected_check"),
    [
        (
            "/studio/view-candidates",
            "user_A_cannot_list_other_view_candidates",
        ),
        (
            "/studio/presentation-candidates",
            "user_A_cannot_list_other_presentation_candidates",
        ),
    ],
)
def test_candidate_list_owner_spoof_fails_probe(
    path: str,
    expected_check: str,
):
    def leaky_transport(method: str, url: str, token: str) -> HttpResult:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        if (
            method == "GET"
            and token == "secret-a"
            and parsed.path == path
            and query.get("owner") == ["b" * 32]
        ):
            return HttpResult(200, "application/json", {"candidates": []})
        return _transport(method, url, token)

    result = run_probe(_config(), leaky_transport)
    failed = {check["name"] for check in result["checks"] if not check["passed"]}
    assert failed == {expected_check}
    assert result["passed"] is False


def test_operator_cannot_claim_a_revision_the_live_process_does_not_report():
    def mismatched_revision(method: str, url: str, token: str) -> HttpResult:
        if url.endswith("/health"):
            return HttpResult(200, "application/json", {
                "status": "ok",
                "service": "facetta",
                "deployment_revision": "different-live-revision",
                "persistence_backend": "postgresql",
            })
        return _transport(method, url, token)

    result = run_probe(_config(), mismatched_revision)
    failed = {check["name"] for check in result["checks"] if not check["passed"]}
    assert failed == {"live_deployment_revision_matches"}
    assert result["passed"] is False


def test_missing_live_revision_fails_closed():
    def missing_revision(method: str, url: str, token: str) -> HttpResult:
        if url.endswith("/health"):
            return HttpResult(200, "application/json", {
                "status": "ok", "service": "facetta",
                "persistence_backend": "postgresql",
            })
        return _transport(method, url, token)

    result = run_probe(_config(), missing_revision)
    failed = {check["name"] for check in result["checks"] if not check["passed"]}
    assert failed == {"live_deployment_revision_matches"}
    assert result["passed"] is False


def test_non_postgres_staging_persistence_fails_closed():
    def sqlite_backend(method: str, url: str, token: str) -> HttpResult:
        if url.endswith("/health"):
            return HttpResult(200, "application/json", {
                "status": "ok",
                "service": "facetta",
                "deployment_revision": "0123456789abcdef",
                "persistence_backend": "sqlite",
            })
        return _transport(method, url, token)

    result = run_probe(_config(), sqlite_backend)
    failed = {check["name"] for check in result["checks"] if not check["passed"]}
    assert failed == {"live_persistence_is_postgresql"}
    assert result["passed"] is False


def test_mounted_resource_route_cannot_false_pass_as_hidden_404():
    def mounted_transport(method: str, url: str, token: str) -> HttpResult:
        if method == "OPTIONS" and url.endswith("/share/e2e-hidden"):
            return HttpResult(405)
        return _transport(method, url, token)

    result = run_probe(_config(), mounted_transport)
    failed = {check["name"] for check in result["checks"] if not check["passed"]}
    assert "production_hides_share_e2e-hidden" in failed
    assert result["passed"] is False


def test_mounted_legacy_mutation_cannot_false_pass_as_hidden():
    def mounted_legacy_transport(
        method: str, url: str, token: str,
    ) -> HttpResult:
        if method == "OPTIONS" and url.endswith("/projects/from-brief"):
            return HttpResult(405, allowed_methods=frozenset({"GET", "POST"}))
        return _transport(method, url, token)

    result = run_probe(_config(), mounted_legacy_transport)
    failed = {check["name"] for check in result["checks"] if not check["passed"]}
    assert failed == {"production_disallows_project_from_brief"}
    assert result["passed"] is False


def test_mounted_raw_prompt_compiler_cannot_escape_release_probe():
    """Retired prompt-debug/compiler operations are release-critical exposure."""

    def mounted_compiler_transport(
        method: str, url: str, token: str,
    ) -> HttpResult:
        if method == "OPTIONS" and url.endswith("/specs/render-prompt"):
            return HttpResult(405, allowed_methods=frozenset({"POST"}))
        return _transport(method, url, token)

    result = run_probe(_config(), mounted_compiler_transport)
    failed = {check["name"] for check in result["checks"] if not check["passed"]}
    assert failed == {"production_disallows_specs_render_prompt"}
    assert result["passed"] is False


def test_dynamic_get_collision_does_not_hide_a_safe_production_surface():
    def production_collision_transport(
        method: str, url: str, token: str,
    ) -> HttpResult:
        if method == "OPTIONS" and url.endswith("/projects/from-image"):
            return HttpResult(405, allowed_methods=frozenset({"GET"}))
        return _transport(method, url, token)

    result = run_probe(_config(), production_collision_transport)
    assert result["passed"] is True


def test_method_not_allowed_without_allow_header_fails_closed():
    def stripped_allow_transport(
        method: str, url: str, token: str,
    ) -> HttpResult:
        if method == "OPTIONS" and url.endswith("/projects/from-brief"):
            return HttpResult(405)
        return _transport(method, url, token)

    result = run_probe(_config(), stripped_allow_transport)
    failed = {check["name"] for check in result["checks"] if not check["passed"]}
    assert failed == {"production_disallows_project_from_brief"}
    assert result["passed"] is False

from scripts.run_staging_two_user_isolation import (
    HttpResult,
    StagingConfig,
    StagingIdentity,
    run_probe,
)


def _config() -> StagingConfig:
    return StagingConfig(
        base_url="https://staging.facetta.test",
        deployment_revision="0123456789abcdef",
        first=StagingIdentity(
            "A", "secret-a", "a" * 32, "project-a", "family-a", "asset-a",
        ),
        second=StagingIdentity(
            "B", "secret-b", "b" * 32, "project-b", "family-b", "asset-b",
        ),
    )


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
    assert result["schema_version"] == "facetta-staging-isolation.v4"
    assert result["target"]["deployment_revision"] == "0123456789abcdef"
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

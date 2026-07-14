from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "scripts/generate_studio_action_manifest.py"


def test_mobile_studio_action_manifest_is_generated_from_canonical_source():
    spec = importlib.util.spec_from_file_location(
        "generate_studio_action_manifest", GENERATOR,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    generated = ROOT / "mobile/src/studio/generatedActionManifest.ts"
    assert generated.read_text(encoding="utf-8") == module.render()


@pytest.mark.parametrize("action", [
    {"execution_mode": "unknown", "review_authority": "none"},
    {"execution_mode": "candidate_job", "review_authority": "unknown"},
    {"execution_mode": "candidate_job", "review_authority": "none"},
])
def test_manifest_generator_rejects_invalid_orchestration(action):
    spec = importlib.util.spec_from_file_location(
        "generate_studio_action_manifest_validation", GENERATOR,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    with pytest.raises(ValueError):
        module._validate_orchestration("invalid", action)


@pytest.mark.parametrize("minimum,maximum", [
    (None, 1),
    (1, None),
    (-1, 1),
    (2, 1),
    (1, 5),
    (True, 1),
])
def test_manifest_generator_rejects_invalid_requested_output_ranges(
    minimum,
    maximum,
):
    spec = importlib.util.spec_from_file_location(
        "generate_studio_action_manifest_output_range", GENERATOR,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    with pytest.raises(ValueError, match="requested-output range"):
        module._validate_orchestration("invalid", {
            "execution_mode": "candidate_job",
            "review_authority": "candidate_decision",
            "min_requested_outputs": minimum,
            "max_requested_outputs": maximum,
        })


@pytest.mark.parametrize("execution_mode,review_authority,minimum,maximum", [
    ("instant_transaction", "none", 1, 1),
    ("candidate_job", "candidate_decision", 0, 1),
    ("terminal_job", "backend_transaction", 0, 0),
])
def test_manifest_generator_enforces_output_range_by_execution_mode(
    execution_mode,
    review_authority,
    minimum,
    maximum,
):
    spec = importlib.util.spec_from_file_location(
        "generate_studio_action_manifest_execution_range", GENERATOR,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    with pytest.raises(ValueError):
        module._validate_orchestration("invalid", {
            "execution_mode": execution_mode,
            "review_authority": review_authority,
            "min_requested_outputs": minimum,
            "max_requested_outputs": maximum,
        })

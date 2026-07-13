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

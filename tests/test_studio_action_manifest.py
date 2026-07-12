from __future__ import annotations

import importlib.util
from pathlib import Path


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

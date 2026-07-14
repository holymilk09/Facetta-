"""Integration checks for the checked-in frozen release implementation pins."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from facetta.frozen_corpus_gate import validate_frozen_component_pins


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "docs" / "evals" / "frozen-founder-corpus-v1" / "config.json"


def test_production_frozen_component_pins_match_the_working_tree() -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))

    assert validate_frozen_component_pins(config, ROOT) == []
    components = config["frozen_components"]
    for name, value in components.items():
        if name == "routing":
            assert value == "grok-primary-openai-fallback.v1"
            continue
        relative, separator, expected = value.rpartition("@sha256:")
        assert separator, name
        path = (ROOT / relative).resolve()
        assert path.is_relative_to(ROOT)
        assert path.is_file(), name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, name

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from facetta.frozen_corpus_gate import validate_frozen_component_pins


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "docs/evals/frozen-founder-corpus-v1/config.json"


@pytest.mark.parametrize(
    "deleted_pin",
    ["blind_review_ledger_authoring", "blind_review_ledger_authoring_cli"],
)
def test_production_config_cannot_delete_blind_ledger_authoring_pins(
    deleted_pin: str,
) -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    tampered = deepcopy(config)
    tampered["frozen_components"].pop(deleted_pin)

    errors = validate_frozen_component_pins(tampered, ROOT)

    assert f"config frozen component {deleted_pin} is not hash-pinned" in errors


def test_synthetic_fixture_config_does_not_inherit_production_authoring_pins(
    tmp_path: Path,
) -> None:
    component = tmp_path / "component.py"
    component.write_text("# frozen fixture\n", encoding="utf-8")
    digest = hashlib.sha256(component.read_bytes()).hexdigest()
    synthetic = {
        "schema_version": "facetta-frozen-gate-config.v1",
        "config_id": "synthetic-test-config",
        "corpus_id": "synthetic-test-corpus",
        "frozen_components": {
            name: f"component.py@sha256:{digest}"
            for name in (
                "ring_contract", "prompt_bundle", "evaluator_bundle",
                "routing_contract", "live_runner", "replay_verifier",
                "replay_runner", "release_verifier", "packet_builder",
                "packet_runner",
            )
        },
    }

    assert validate_frozen_component_pins(synthetic, tmp_path) == []

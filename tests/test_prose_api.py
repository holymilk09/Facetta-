import copy

from fastapi.testclient import TestClient

import facetta.prose as prose_layer
from facetta.main import app
from facetta.prose import system_prompt, vocabulary_digest
from facetta.spec import Spec
from facetta.vocabulary import get_vocabulary

client = TestClient(app)


def test_system_prompt_embeds_vocabulary_constraints():
    prompt = system_prompt()
    assert "Pigeon's Blood" in prompt
    assert "round_brilliant" in prompt
    assert "gia_type_ii" in prompt
    assert "never" in prompt  # never invent trade terms
    # deterministic — same vocabulary, same prompt bytes
    assert vocabulary_digest(get_vocabulary()) == vocabulary_digest(get_vocabulary())


def test_unconfigured_api_returns_503(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    response = client.post("/specs/from-prose", json={"prose": "a 2 carat royal blue sapphire ring"})
    assert response.status_code == 503
    assert "ANTHROPIC_API_KEY" in response.json()["detail"]


def _mock_model(monkeypatch, spec_dict):
    def fake_generate(prose: str) -> Spec:
        return Spec.model_validate(spec_dict)

    monkeypatch.setattr(prose_layer, "generate_spec", fake_generate)


def test_valid_model_output_is_revalidated_and_returned(monkeypatch, example_spec):
    example_spec.update({"design_id": "dsn_pending", "created_by": "usr_pending"})
    _mock_model(monkeypatch, example_spec)

    response = client.post("/specs/from-prose", json={
        "prose": "2ct royal blue oval sapphire, 18k yellow gold solitaire, size 6.5",
        "created_by": "usr_ana",
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["created_by"] == "usr_ana"
    assert body["stone"]["color"]["trade"] == "Royal Blue"
    assert body["stone"]["color"]["gia"]  # both layers stored


def test_invalid_model_output_never_reaches_the_db(monkeypatch, example_spec):
    # model hallucinates a physically impossible stone
    bad = copy.deepcopy(example_spec)
    bad["stone"]["carat"] = 9.0
    _mock_model(monkeypatch, bad)

    response = client.post("/specs/from-prose", json={"prose": "a huge sapphire"})
    assert response.status_code == 502
    issues = response.json()["issues"]
    assert any(i["type"] == "density" for i in issues)


def test_invented_trade_term_is_rejected(monkeypatch, example_spec):
    bad = copy.deepcopy(example_spec)
    bad["stone"]["color"]["trade"] = "Midnight Whisper"
    _mock_model(monkeypatch, bad)

    response = client.post("/specs/from-prose", json={"prose": "a moody blue sapphire"})
    assert response.status_code == 502
    issues = response.json()["issues"]
    trade_issue = next(i for i in issues if i["loc"] == ["stone", "color", "trade"])
    assert "Royal Blue" in trade_issue["valid_options"]

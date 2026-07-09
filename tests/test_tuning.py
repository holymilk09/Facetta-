"""The LoRA pipeline: fal training driven by API, the result registered as
the flux_lora engine. All provider calls mocked. Under test: the training
loop persists the record, failures are loud, the engine refuses to run
without a trained LoRA, and a retrained LoRA moves the generation cache key."""

import json

import pytest

import facetta.render as render_mod
import facetta.tuning as tuning
from facetta.render import RenderUnavailable


@pytest.fixture
def loras_file(tmp_path, monkeypatch):
    path = tmp_path / "loras.json"
    monkeypatch.setattr(tuning, "LORAS_PATH", path)
    return path


@pytest.fixture
def images(tmp_path):
    paths = []
    for i in range(5):
        p = tmp_path / f"img_{i}.png"
        p.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes([i]) * 32)
        paths.append(p)
    return paths


def _mock_train(monkeypatch, result=None, error=None):
    """Mock the storage initiate + PUT + training submit round-trip."""
    class R:
        def __init__(self, body):
            self.body = body
            self.text = json.dumps(body)
        def raise_for_status(self):
            if error:
                raise error
        def json(self):
            return self.body

    def fake_post(url, json=None, headers=None, timeout=None, content=None):
        if "storage" in url:
            return R({"upload_url": "https://storage.fal/put",
                      "file_url": "https://storage.fal/train.zip"})
        return R(result or {})

    import httpx
    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(httpx, "put",
                        lambda url, content=None, headers=None, timeout=None:
                        R({}))
    monkeypatch.setenv("FAL_KEY", "test-key")


class TestTrainStyleLora:
    def test_happy_path_persists_the_record(self, loras_file, images,
                                            monkeypatch):
        _mock_train(monkeypatch, {"diffusers_lora_file":
                                  {"url": "https://fal/lora.safetensors"}})
        record = tuning.train_style_lora(images)
        assert record["url"] == "https://fal/lora.safetensors"
        assert record["images"] == 5
        stored = json.loads(loras_file.read_text())
        assert stored["house_style"]["trigger_word"] == tuning.HOUSE_TRIGGER

    def test_failed_training_is_loud(self, loras_file, images, monkeypatch):
        _mock_train(monkeypatch, {}, error=RuntimeError("500 server error"))
        with pytest.raises(RenderUnavailable, match="training failed"):
            tuning.train_style_lora(images)
        assert not loras_file.exists()                 # nothing persisted

    def test_too_few_images_refused_before_any_spend(self, loras_file,
                                                     images, monkeypatch):
        monkeypatch.setenv("FAL_KEY", "test-key")
        with pytest.raises(RenderUnavailable, match="at least 4"):
            tuning.train_style_lora(images[:2])

    def test_completed_without_a_file_is_loud(self, loras_file, images,
                                              monkeypatch):
        _mock_train(monkeypatch, {"nothing": True})
        with pytest.raises(RenderUnavailable, match="no LoRA file"):
            tuning.train_style_lora(images)


class TestFluxLoraEngine:
    def test_untrained_engine_fails_loudly(self, loras_file, tmp_path,
                                           monkeypatch):
        monkeypatch.setattr(render_mod, "CACHE_DIR", tmp_path)
        monkeypatch.setenv("FAL_KEY", "test-key")
        with pytest.raises(RenderUnavailable, match="no house-style LoRA"):
            render_mod.generate_image("a ring", model="flux_lora")

    def test_lora_url_and_trigger_ride_the_call_and_the_key(
            self, loras_file, tmp_path, monkeypatch):
        loras_file.write_text(json.dumps({"house_style": {
            "url": "https://fal/lora-A.safetensors",
            "trigger_word": "FACETTASTYLE", "steps": 1000, "images": 7}}))
        monkeypatch.setattr(render_mod, "CACHE_DIR", tmp_path)
        monkeypatch.setenv("FAL_KEY", "test-key")

        import base64
        calls = []

        class R:
            def raise_for_status(self):
                pass
            def json(self):
                return {"images": [{"url": "data:image/png;base64,"
                                    + base64.b64encode(b"img").decode()}]}

        import httpx
        monkeypatch.setattr(httpx, "post",
                            lambda url, json=None, headers=None, timeout=None:
                            calls.append(json) or R())
        render_mod.generate_image("a ring", model="flux_lora")
        payload = calls[0]
        assert payload["loras"] == [{"path": "https://fal/lora-A.safetensors",
                                     "scale": 1.0}]
        assert payload["prompt"].startswith("FACETTASTYLE style.")

        # retrain → different URL → different cache key → a fresh engine call
        loras_file.write_text(json.dumps({"house_style": {
            "url": "https://fal/lora-B.safetensors",
            "trigger_word": "FACETTASTYLE", "steps": 1000, "images": 9}}))
        render_mod.generate_image("a ring", model="flux_lora")
        assert len(calls) == 2                          # no stale cache hit

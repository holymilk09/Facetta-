from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image

from facetta.frozen_corpus_packet import prepare_frozen_corpus_review_packet


def _json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value) + "\n")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    sources = tmp_path / "sources"
    sources.mkdir()
    source = sources / "image-1.png"
    candidate = tmp_path / "candidate.png"
    mask = tmp_path / "mask.png"
    for path, color in ((source, "white"), (candidate, "gray"), (mask, "black")):
        Image.new("RGB", (4, 4), color).save(path)
    manifest = tmp_path / "manifest.json"
    _json(manifest, {"sources": [{"filename": source.name, "sha256": _sha(source)}]})
    config = tmp_path / "config.json"
    _json(config, {"config": "frozen"})
    capture = tmp_path / "capture.json"
    _json(capture, {
        "schema_version": "facetta-frozen-capture.v1",
        "attempts": [{
            "kind": "edit", "evaluation_id": "metal-color",
            "source_filename": source.name, "attempt": 1,
            "accepted": True, "candidate_image": candidate.name,
            "mask_image": mask.name, "edit_fidelity_score": 95,
            "severity": "none", "change_applied": True,
        }],
        "persistence_evidence": {"verified": True},
    })
    return manifest, config, sources, capture


def test_packet_hashes_artifacts_but_never_claims_review(tmp_path: Path):
    manifest, config, sources, capture = _fixture(tmp_path)
    packet = prepare_frozen_corpus_review_packet(manifest, config, sources, capture)
    attempt = packet["attempts"][0]
    assert attempt["source_image_sha256"] == _sha(sources / "image-1.png")
    assert attempt["candidate_image_sha256"] == _sha(tmp_path / "candidate.png")
    assert packet["reviewer_review"]["completed"] is False
    assert packet["reviewer_review"]["decisions"][0]["accepted"] is None
    assert packet["signature"] is None
    assert packet["packet_status"] == "awaiting_GIA_trained_review_and_signature"


def test_packet_rejects_changed_frozen_source(tmp_path: Path):
    manifest, config, sources, capture = _fixture(tmp_path)
    Image.new("RGB", (4, 4), "red").save(sources / "image-1.png")
    try:
        prepare_frozen_corpus_review_packet(manifest, config, sources, capture)
    except ValueError as exc:
        assert "source hash differs" in str(exc)
    else:
        raise AssertionError("changed source should fail")


def test_packet_rejects_missing_candidate(tmp_path: Path):
    manifest, config, sources, capture = _fixture(tmp_path)
    (tmp_path / "candidate.png").unlink()
    try:
        prepare_frozen_corpus_review_packet(manifest, config, sources, capture)
    except ValueError as exc:
        assert "candidate_image is unavailable" in str(exc)
    else:
        raise AssertionError("missing candidate should fail")

"""Build an unsigned, hash-bound review packet from captured corpus attempts."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from facetta.frozen_corpus_gate import file_sha256


Json = dict[str, Any]


def _load_object(path: Path) -> Json:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def prepare_frozen_corpus_review_packet(
    manifest_path: Path,
    config_path: Path,
    source_dir: Path,
    capture_path: Path,
) -> Json:
    """Hash captured artifacts and produce a deliberately unsigned packet.

    The capture is machine output. Reviewer decisions and signatures are never
    inferred here; their placeholders remain incomplete until human review.
    """

    manifest = _load_object(manifest_path)
    capture = _load_object(capture_path)
    if capture.get("schema_version") != "facetta-frozen-capture.v1":
        raise ValueError("unsupported capture schema_version")
    attempts = capture.get("attempts")
    if not isinstance(attempts, list) or not attempts:
        raise ValueError("capture attempts must be a non-empty list")
    source_hashes = {
        str(row["filename"]): str(row["sha256"])
        for row in manifest.get("sources", [])
    }
    evidence_attempts: list[Json] = []
    coverage: dict[str, set[str]] = defaultdict(set)
    decision_keys: set[tuple[str, str, str]] = set()
    for index, raw in enumerate(attempts, 1):
        if not isinstance(raw, dict):
            raise ValueError(f"capture attempt {index} must be an object")
        kind = str(raw.get("kind") or "")
        evaluation_id = str(raw.get("evaluation_id") or "")
        filename = str(raw.get("source_filename") or "")
        if kind not in {"render", "edit"} or not evaluation_id:
            raise ValueError(f"capture attempt {index} has invalid identity")
        expected_source_hash = source_hashes.get(filename)
        source = source_dir / filename
        if expected_source_hash is None or not source.is_file():
            raise ValueError(f"capture attempt {index} has unavailable frozen source")
        if file_sha256(source) != expected_source_hash:
            raise ValueError(f"capture attempt {index} frozen source hash differs")
        row = dict(raw)
        row["source_sha256"] = expected_source_hash
        row["source_image"] = str(source.resolve())
        row["source_image_sha256"] = expected_source_hash
        for field in ("candidate_image", "mask_image"):
            if field == "mask_image" and kind != "edit":
                row.pop(field, None)
                row.pop(f"{field}_sha256", None)
                continue
            value = row.get(field)
            if not isinstance(value, str) or not value:
                raise ValueError(f"capture attempt {index} lacks {field}")
            artifact = Path(value)
            if not artifact.is_absolute():
                artifact = capture_path.parent / artifact
            if not artifact.is_file():
                raise ValueError(f"capture attempt {index} {field} is unavailable")
            row[field] = str(artifact.resolve())
            row[f"{field}_sha256"] = file_sha256(artifact)
        evidence_attempts.append(row)
        coverage[filename].add(evaluation_id)
        decision_keys.add((kind, evaluation_id, filename))

    return {
        "schema_version": "facetta-frozen-replay.v1",
        "manifest_sha256": file_sha256(manifest_path),
        "config_sha256": file_sha256(config_path),
        "source_coverage": [
            {
                "filename": filename,
                "source_sha256": source_hashes[filename],
                "evaluation_ids": sorted(coverage.get(filename, set())),
                "quality_status": "pending_review",
            }
            for filename in sorted(source_hashes)
        ],
        "attempts": evidence_attempts,
        "persistence_evidence": capture.get("persistence_evidence"),
        "reviewer_review": {
            "completed": False,
            "reviewer": None,
            "qualification": None,
            "false_positives": None,
            "false_negatives": None,
            "decisions": [
                {
                    "kind": kind,
                    "evaluation_id": evaluation_id,
                    "source_filename": filename,
                    "accepted": None,
                }
                for kind, evaluation_id, filename in sorted(decision_keys)
            ],
        },
        "signature": None,
        "packet_status": "awaiting_GIA_trained_review_and_signature",
    }

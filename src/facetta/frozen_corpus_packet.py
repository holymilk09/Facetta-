"""Build an unsigned, workload-bound review packet from a secured capture.

The 144-file manifest is an integrity prerequisite.  Human image-quality review
is intentionally narrower: it covers only the sources and evaluations assigned
by the pinned capture workload.  This module never calls a provider, supplies a
review decision, or signs reviewer evidence.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from facetta.frozen_capture_workload import (
    CAPTURE_SCHEMA,
    build_provider_call_plan,
    file_sha256,
    validate_capture_envelope,
)


Json = dict[str, Any]
PACKET_SCHEMA = "facetta-frozen-replay.v1"


def _load_object(path: Path, *, label: str | None = None) -> Json:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"{label or path} must be a JSON object")
    return value


def _capture_artifact(capture_path: Path, value: object, *, label: str) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError(f"{label} path is invalid")
    root = capture_path.parent.resolve()
    artifact = (root / value).resolve()
    if not artifact.is_relative_to(root) or not artifact.is_file():
        raise ValueError(f"{label} is unavailable")
    return artifact


def prepare_frozen_corpus_review_packet(
    manifest_path: Path,
    config_path: Path,
    workload_path: Path,
    source_dir: Path,
    capture_path: Path,
    *,
    capture_public_key_path: Path,
    capture_key_id: str,
    repository_root: Path | None = None,
) -> Json:
    """Convert one validated executor capture into an unsigned review packet.

    Capture validation is mandatory and includes the executor signature, the
    exact frozen plan, every candidate/mask artifact, and canonical persistence
    evidence.  The returned replay-shaped packet is still incomplete until a
    qualified human supplies every decision and signs the packet separately.
    """

    validation = validate_capture_envelope(
        capture_path,
        manifest_path,
        config_path,
        workload_path,
        capture_public_key_path=capture_public_key_path,
        capture_key_id=capture_key_id,
        repository_root=repository_root,
    )
    if validation["status"] != "pass":
        raise ValueError(
            "capture validation failed: " + "; ".join(validation["errors"])
        )

    manifest = _load_object(manifest_path)
    capture = _load_object(capture_path)
    if capture.get("schema_version") != CAPTURE_SCHEMA:
        # Kept explicit even though the secured validator already rejects it.
        raise ValueError("unsupported capture schema_version")
    plan = build_provider_call_plan(
        manifest_path,
        config_path,
        workload_path,
        repository_root=repository_root,
    )

    expected = {
        (row["kind"], row["evaluation_id"], row["source_filename"]): row
        for row in plan["items"]
    }
    manifest_hashes = {
        str(row["filename"]): str(row["sha256"])
        for row in manifest.get("sources", [])
        if isinstance(row, dict)
    }
    quality_sources = {
        filename: str(row["source_sha256"])
        for (_, _, filename), row in expected.items()
    }

    # Resolve and re-check only quality-slice sources here.  Full 144-source
    # integrity is a separate gate and is not inferred from this subset.
    source_paths: dict[str, Path] = {}
    for filename, expected_hash in quality_sources.items():
        source = (source_dir / filename).resolve()
        if (
            not source.is_relative_to(source_dir.resolve())
            or not source.is_file()
            or file_sha256(source) != expected_hash
        ):
            raise ValueError(f"quality source hash differs or is unavailable: {filename}")
        source_paths[filename] = source

    attempts = capture["attempts"]
    evidence_attempts: list[Json] = []
    coverage: dict[str, set[str]] = defaultdict(set)
    for index, raw in enumerate(attempts, 1):
        if not isinstance(raw, dict):  # Defensive; validator already enforces this.
            raise ValueError(f"capture attempt {index} must be an object")
        key = (
            str(raw.get("kind") or ""),
            str(raw.get("evaluation_id") or ""),
            str(raw.get("source_filename") or ""),
        )
        planned = expected.get(key)
        if planned is None:
            raise ValueError(f"capture attempt {index} is outside the quality workload")
        filename = key[2]
        row = dict(raw)
        row["operation_class"] = planned["operation_class"]
        row["source_image"] = str(source_paths[filename])
        row["source_image_sha256"] = planned["source_sha256"]
        for field in ("candidate_image", "mask_image"):
            if field == "mask_image" and key[0] != "edit":
                continue
            artifact = _capture_artifact(
                capture_path,
                row.get(field),
                label=f"capture attempt {index} {field}",
            )
            # Preserve the signed hash and replace only the path with an exact,
            # local path suitable for the offline human/replay process.
            row[field] = str(artifact)
        evidence_attempts.append(row)
        coverage[filename].add(key[1])

    persistence_ref = capture["persistence_evidence_ref"]
    persistence_path = _capture_artifact(
        capture_path,
        persistence_ref.get("relative_path"),
        label="capture persistence evidence",
    )
    persistence_evidence = _load_object(
        persistence_path,
        label="capture persistence evidence",
    )
    persistence_binding = {
        "artifact": str(persistence_path),
        "sha256": persistence_ref["sha256"],
        "capture_relative_path": persistence_ref["relative_path"],
    }

    capture_sha256 = file_sha256(capture_path)
    decision_keys = sorted(expected)
    return {
        "schema_version": PACKET_SCHEMA,
        "manifest_sha256": plan["manifest_sha256"],
        "config_sha256": plan["config_sha256"],
        "workload_sha256": plan["workload_sha256"],
        # Required at the replay schema's top level so the compiled result and
        # subsequent founder approval can bind the exact signed capture bytes.
        "capture_sha256": capture_sha256,
        "capture_provenance": {
            "schema_version": CAPTURE_SCHEMA,
            "capture_artifact": str(capture_path.resolve()),
            "capture_sha256": capture_sha256,
            "executor_key_id": capture_key_id,
            "executor_public_key_sha256": file_sha256(capture_public_key_path),
            "executor_signature": capture["signature"],
            "executor_signature_status": "verified",
            "capture_validation": validation,
        },
        "integrity_prerequisite": {
            "manifest_sha256": plan["manifest_sha256"],
            "expected_source_count": len(manifest_hashes),
            "status": "required_separately",
            "verified_source_count": None,
            "quality_inference_allowed": False,
        },
        "quality_scope": {
            "slice": "ring",
            "source_count": len(quality_sources),
            "evaluation_sequence_count": len(expected),
            "status": "pending_review",
        },
        "source_coverage": [
            {
                "filename": filename,
                "source_sha256": quality_sources[filename],
                "evaluation_ids": sorted(coverage[filename]),
                "quality_status": "pending_review",
            }
            for filename in sorted(quality_sources)
        ],
        "attempts": evidence_attempts,
        # Replay compatibility is explicit: the contents are embedded, while
        # the adjacent binding preserves the exact executor-captured bytes.
        "persistence_evidence": persistence_evidence,
        "persistence_evidence_binding": persistence_binding,
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
                for kind, evaluation_id, filename in decision_keys
            ],
        },
        "signature": None,
        "packet_status": "awaiting_GIA_trained_review_and_signature",
        "corpus_gate_ready": False,
    }

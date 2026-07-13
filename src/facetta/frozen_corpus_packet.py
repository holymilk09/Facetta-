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

from facetta.blind_jewelry_review import (
    GIA_VISUAL_FIDELITY_ROLE,
    build_blind_review_packet,
)
from facetta.frozen_capture_workload import (
    CAPTURE_SCHEMA,
    build_provider_call_plan,
    file_sha256,
    validate_capture_envelope,
)
from facetta.frozen_evidence_paths import (
    build_artifact_index,
    confined_path,
    evidence_root as resolve_evidence_root,
    relative_artifact_path,
)


Json = dict[str, Any]
PACKET_SCHEMA = "facetta-frozen-replay.v1"


def _load_object(path: Path, *, label: str | None = None) -> Json:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"{label or path} must be a JSON object")
    return value


def _capture_artifact(
    capture_path: Path,
    evidence_root: Path,
    value: object,
    *,
    label: str,
) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError(f"{label} must be capture-relative")
    artifact = confined_path(
        evidence_root,
        capture_path.parent / value,
        label=label,
        kind="file",
    )
    if not artifact.is_relative_to(capture_path.parent.resolve()):
        raise ValueError(f"{label} escapes the capture directory")
    return artifact


def prepare_frozen_corpus_review_packet(
    manifest_path: Path,
    config_path: Path,
    workload_path: Path,
    source_dir: Path,
    capture_path: Path,
    *,
    evidence_root: Path,
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

    root = resolve_evidence_root(evidence_root)
    resolved_source_dir = confined_path(
        root, source_dir, label="source directory", kind="directory",
    )
    resolved_capture_path = confined_path(
        root, capture_path, label="capture artifact", kind="file",
    )
    resolved_capture_public_key = confined_path(
        root,
        capture_public_key_path,
        label="executor public key",
        kind="file",
    )
    validation = validate_capture_envelope(
        resolved_capture_path,
        manifest_path,
        config_path,
        workload_path,
        capture_public_key_path=resolved_capture_public_key,
        capture_key_id=capture_key_id,
        repository_root=repository_root,
    )
    if validation["status"] != "pass":
        raise ValueError(
            "capture validation failed: " + "; ".join(validation["errors"])
        )

    manifest = _load_object(manifest_path)
    capture = _load_object(resolved_capture_path)
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
        if Path(filename).is_absolute() or len(Path(filename).parts) != 1:
            raise ValueError(f"quality source filename is not portable: {filename}")
        source = confined_path(
            root,
            resolved_source_dir / filename,
            label=f"quality source {filename}",
            kind="file",
        )
        if (
            not source.is_relative_to(resolved_source_dir)
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
        row["source_image"] = relative_artifact_path(
            root,
            source_paths[filename],
            label=f"quality source {filename}",
        )
        row["source_image_sha256"] = planned["source_sha256"]
        for field in ("candidate_image", "mask_image"):
            if field == "mask_image" and key[0] != "edit":
                continue
            artifact = _capture_artifact(
                resolved_capture_path,
                root,
                row.get(field),
                label=f"capture attempt {index} {field}",
            )
            # Preserve the signed hash and replace only the path with an exact,
            # local path suitable for the offline human/replay process.
            row[field] = relative_artifact_path(root, artifact, label=field)
        evidence_attempts.append(row)
        coverage[filename].add(key[1])

    persistence_ref = capture["persistence_evidence_ref"]
    persistence_path = _capture_artifact(
        resolved_capture_path,
        root,
        persistence_ref.get("relative_path"),
        label="capture persistence evidence",
    )
    persistence_evidence = _load_object(
        persistence_path,
        label="capture persistence evidence",
    )
    persistence_binding = {
        "artifact": relative_artifact_path(
            root, persistence_path, label="persistence evidence",
        ),
        "sha256": persistence_ref["sha256"],
        "capture_relative_path": persistence_ref["relative_path"],
    }

    capture_sha256 = file_sha256(resolved_capture_path)
    capture_artifact = relative_artifact_path(
        root, resolved_capture_path, label="capture artifact",
    )
    key_artifact = relative_artifact_path(
        root, resolved_capture_public_key, label="executor public key",
    )
    artifact_rows: list[tuple[str, str, str]] = [
        (capture_artifact, capture_sha256, "signed_capture"),
        (key_artifact, file_sha256(resolved_capture_public_key), "executor_public_key"),
        (
            persistence_binding["artifact"],
            persistence_binding["sha256"],
            "persistence_evidence",
        ),
    ]
    for filename, source in source_paths.items():
        artifact_rows.append((
            relative_artifact_path(root, source, label=f"quality source {filename}"),
            quality_sources[filename],
            f"quality_source:{filename}",
        ))
    for row in evidence_attempts:
        identity = (
            f"{row['kind']}:{row['evaluation_id']}:"
            f"{row['source_filename']}:attempt-{row['attempt']}"
        )
        artifact_rows.append((
            row["candidate_image"],
            row["candidate_image_sha256"],
            f"candidate:{identity}",
        ))
        if row["kind"] == "edit":
            artifact_rows.append((
                row["mask_image"], row["mask_image_sha256"], f"mask:{identity}",
            ))
    artifact_index = build_artifact_index(artifact_rows)
    decision_keys = sorted(expected)
    return {
        "schema_version": PACKET_SCHEMA,
        "manifest_sha256": plan["manifest_sha256"],
        "config_sha256": plan["config_sha256"],
        "workload_sha256": plan["workload_sha256"],
        # Required at the replay schema's top level so the compiled result and
        # subsequent founder approval can bind the exact signed capture bytes.
        "capture_sha256": capture_sha256,
        "artifact_index": artifact_index,
        "capture_provenance": {
            "schema_version": CAPTURE_SCHEMA,
            "corpus_run_id": capture["corpus_run_id"],
            "capture_artifact": capture_artifact,
            "capture_sha256": capture_sha256,
            "executor_key_id": capture_key_id,
            "executor_public_key_artifact": key_artifact,
            "executor_public_key_sha256": file_sha256(
                resolved_capture_public_key
            ),
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


def prepare_blind_frozen_corpus_review_packet_v2(
    manifest_path: Path,
    config_path: Path,
    workload_path: Path,
    source_dir: Path,
    capture_path: Path,
    *,
    evidence_root: Path,
    capture_public_key_path: Path,
    capture_key_id: str,
    review_seed: str,
    reviewer_role: str = GIA_VISUAL_FIDELITY_ROLE,
    repository_root: Path | None = None,
) -> Json:
    """Prepare the reviewer-visible, blind v2 artifact.

    The v1 converter remains the compatibility reader and secured capture
    validator.  This adapter deliberately projects only the machine-selected
    source/candidate/mask, their signed hashes, and the canonical reviewed
    intent into the v2 artifact.  Raw attempts, evaluator output, provider
    routing, retries, and machine verdicts never cross this seam.
    """

    machine_evidence = prepare_frozen_corpus_review_packet(
        manifest_path,
        config_path,
        workload_path,
        source_dir,
        capture_path,
        evidence_root=evidence_root,
        capture_public_key_path=capture_public_key_path,
        capture_key_id=capture_key_id,
        repository_root=repository_root,
    )
    plan = build_provider_call_plan(
        manifest_path,
        config_path,
        workload_path,
        repository_root=repository_root,
    )
    planned_by_key = {
        (row["kind"], row["evaluation_id"], row["source_filename"]): row
        for row in plan["items"]
    }
    attempts_by_key: dict[tuple[str, str, str], list[Json]] = defaultdict(list)
    for row in machine_evidence["attempts"]:
        key = (
            str(row["kind"]),
            str(row["evaluation_id"]),
            str(row["source_filename"]),
        )
        attempts_by_key[key].append(row)

    selected_items: list[Json] = []
    for key in sorted(planned_by_key):
        planned = planned_by_key[key]
        attempts = attempts_by_key.get(key, [])
        selected = [row for row in attempts if row.get("accepted") is True]
        if len(selected) != 1:
            raise ValueError(
                "blind v2 requires exactly one machine-selected candidate for "
                + ":".join(key)
            )
        row = selected[0]
        resolved = planned.get("resolved_inputs")
        execution = resolved.get("execution") if isinstance(resolved, dict) else None
        if not isinstance(execution, dict):
            raise ValueError(
                "blind v2 canonical review intent is unavailable for " + ":".join(key)
            )
        if row.get("resolved_inputs_sha256") != planned.get("resolved_inputs_sha256"):
            raise ValueError(
                "blind v2 selected candidate input binding differs for " + ":".join(key)
            )
        selected_items.append({
            "kind": planned["kind"],
            "operation_class": planned["operation_class"],
            "intent": {
                "intended_change": execution["intent"],
                "target_region": execution["region_description"],
                "frozen_facts": execution["frozen_facts"],
            },
            "source": {
                "path": row["source_image"],
                "sha256": row["source_image_sha256"],
            },
            "candidate": {
                "path": row["candidate_image"],
                "sha256": row["candidate_image_sha256"],
            },
            "mask": (
                {
                    "path": row["mask_image"],
                    "sha256": row["mask_image_sha256"],
                }
                if planned["kind"] == "edit" else None
            ),
        })

    return build_blind_review_packet(
        corpus_run_id=str(machine_evidence["capture_provenance"]["corpus_run_id"]),
        manifest_sha256=str(machine_evidence["manifest_sha256"]),
        config_sha256=str(machine_evidence["config_sha256"]),
        workload_sha256=str(machine_evidence["workload_sha256"]),
        capture_sha256=str(machine_evidence["capture_sha256"]),
        reviewer_role=reviewer_role,
        review_seed=review_seed,
        selected_items=selected_items,
    )


__all__ = [
    "PACKET_SCHEMA",
    "prepare_blind_frozen_corpus_review_packet_v2",
    "prepare_frozen_corpus_review_packet",
]

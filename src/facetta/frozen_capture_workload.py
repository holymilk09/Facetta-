"""Provider-free planning and validation for the frozen corpus capture workload.

The 144-file corpus is an integrity boundary.  Only the advisory 58-file ring
slice is a quality workload.  This module makes that distinction executable
without calling an image provider or manufacturing evidence.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key


Json = dict[str, Any]
WORKLOAD_SCHEMA = "facetta-frozen-capture-workload.v1"
PLAN_SCHEMA = "facetta-frozen-provider-call-plan.v1"
CAPTURE_SCHEMA = "facetta-frozen-capture.v1"


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_object(path: Path) -> Json:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _hex_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def _pinned_path(config: Json, key: str, root: Path) -> tuple[Path, str]:
    frozen = config.get("frozen_components")
    value = frozen.get(key) if isinstance(frozen, dict) else None
    if not isinstance(value, str) or "@sha256:" not in value:
        raise ValueError(f"config frozen component {key} is not hash-pinned")
    relative, expected_hash = value.rsplit("@sha256:", 1)
    candidate = (root.resolve() / relative).resolve()
    if (
        not relative
        or Path(relative).is_absolute()
        or not candidate.is_relative_to(root.resolve())
        or not candidate.is_file()
    ):
        raise ValueError(f"config frozen component {key} path is unavailable")
    if not _hex_digest(expected_hash) or file_sha256(candidate) != expected_hash:
        raise ValueError(f"config frozen component {key} implementation drifted")
    return candidate, expected_hash


def validate_workload_definition(
    manifest_path: Path,
    config_path: Path,
    workload_path: Path,
    *,
    repository_root: Path | None = None,
) -> Json:
    """Validate one explicit source-to-evaluation workload matrix.

    The returned object is a deterministic summary only.  A passing definition
    is not a capture, a quality result, or a release decision.
    """

    root = (repository_root or Path(__file__).resolve().parents[2]).resolve()
    manifest = _load_object(manifest_path)
    config = _load_object(config_path)
    workload = _load_object(workload_path)
    errors: list[str] = []

    if workload.get("schema_version") != WORKLOAD_SCHEMA:
        errors.append("unsupported workload schema_version")
    if workload.get("corpus_id") != manifest.get("corpus_id"):
        errors.append("workload corpus_id differs from manifest")
    if workload.get("manifest_sha256") != file_sha256(manifest_path):
        errors.append("workload manifest hash differs")
    if workload.get("config_id") != config.get("config_id"):
        errors.append("workload config_id differs from config")
    if config.get("manifest_sha256") != file_sha256(manifest_path):
        errors.append("config manifest hash differs")
    try:
        pinned_workload, _ = _pinned_path(config, "capture_workload", root)
        if pinned_workload != workload_path.resolve():
            errors.append("validated workload path differs from config pin")
    except ValueError as exc:
        errors.append(str(exc))

    manifest_rows = manifest.get("sources")
    if not isinstance(manifest_rows, list):
        manifest_rows = []
        errors.append("manifest sources must be a list")
    manifest_sources = {
        str(row.get("filename") or ""): str(row.get("sha256") or "")
        for row in manifest_rows
        if isinstance(row, dict)
    }
    expected_count = manifest.get("expected_source_count")
    if expected_count != len(manifest_sources):
        errors.append("manifest source count is inconsistent")

    matrix = workload.get("sources")
    if not isinstance(matrix, list):
        matrix = []
        errors.append("workload sources must be a list")
    source_rows = [row for row in matrix if isinstance(row, dict)]
    if len(source_rows) != len(matrix):
        errors.append("every workload source must be an object")
    names = [str(row.get("filename") or "") for row in source_rows]
    duplicates = _duplicates(names)
    if duplicates:
        errors.append("duplicate workload sources: " + ", ".join(duplicates))
    if set(names) != set(manifest_sources):
        missing = sorted(set(manifest_sources) - set(names))
        extra = sorted(set(names) - set(manifest_sources))
        if missing:
            errors.append("workload omits manifest sources: " + ", ".join(missing))
        if extra:
            errors.append("workload has unknown sources: " + ", ".join(extra))

    evaluation = manifest.get("evaluation_slice")
    if not isinstance(evaluation, dict):
        evaluation = {}
        errors.append("manifest evaluation_slice must be an object")
    ring_sources = set(map(str, evaluation.get("ring_source_filenames", [])))
    render_ids = list(map(str, evaluation.get("render_case_ids", [])))
    operation_ids = list(map(str, evaluation.get("operation_ids", [])))
    operation_classes = evaluation.get("operation_classes")
    quick_ids = set(map(
        str,
        operation_classes.get("quick_appearance", [])
        if isinstance(operation_classes, dict) else [],
    ))
    structural_ids = set(map(
        str,
        operation_classes.get("structural", [])
        if isinstance(operation_classes, dict) else [],
    ))
    expected_evaluations = {
        ("render", evaluation_id) for evaluation_id in render_ids
    } | {("edit", evaluation_id) for evaluation_id in operation_ids}

    evaluation_sets = workload.get("evaluation_sets")
    if not isinstance(evaluation_sets, dict):
        evaluation_sets = {}
        errors.append("workload evaluation_sets must be an object")
    ring_set_id = workload.get("ring_quality_evaluation_set_id")
    ring_set = evaluation_sets.get(ring_set_id) if isinstance(ring_set_id, str) else None
    if not isinstance(ring_set, list):
        ring_set = []
        errors.append("ring quality evaluation set is unavailable")
    declared_evaluations: set[tuple[str, str]] = set()
    for index, raw in enumerate(ring_set, 1):
        if not isinstance(raw, dict):
            errors.append(f"ring evaluation {index} must be an object")
            continue
        key = (str(raw.get("kind") or ""), str(raw.get("evaluation_id") or ""))
        if key in declared_evaluations:
            errors.append("duplicate ring evaluation: " + ":".join(key))
        declared_evaluations.add(key)
        expected_class = (
            "render_conformance"
            if key[0] == "render"
            else "quick_appearance"
            if key[1] in quick_ids
            else "structural"
            if key[1] in structural_ids
            else None
        )
        if raw.get("operation_class") != expected_class:
            errors.append("ring evaluation class differs: " + ":".join(key))
    if declared_evaluations != expected_evaluations:
        errors.append("ring evaluation set must match the manifest workload exactly")

    quality_names: set[str] = set()
    for row in source_rows:
        filename = str(row.get("filename") or "")
        if row.get("sha256") != manifest_sources.get(filename):
            errors.append(f"workload source hash differs for {filename}")
        if row.get("integrity_required") is not True:
            errors.append(f"source integrity is not required for {filename}")
        quality = row.get("quality")
        if filename in ring_sources:
            if quality != {"slice": "ring", "evaluation_set_id": ring_set_id}:
                errors.append(f"ring source has invalid quality assignment: {filename}")
            else:
                quality_names.add(filename)
        elif quality is not None:
            errors.append(f"non-ring source has a quality assignment: {filename}")

    if quality_names != ring_sources:
        errors.append("quality matrix does not exactly cover the declared ring slice")
    declared_integrity_count = workload.get("expected_integrity_source_count")
    declared_quality_count = workload.get("expected_quality_source_count")
    if declared_integrity_count != len(manifest_sources):
        errors.append("expected_integrity_source_count is inconsistent")
    if declared_quality_count != len(ring_sources):
        errors.append("expected_quality_source_count is inconsistent")

    summary: Json = {
        "schema_version": "facetta-frozen-capture-workload-validation.v1",
        "status": "pass" if not errors else "fail",
        "provider_calls": 0,
        "errors": errors,
        "manifest_sha256": file_sha256(manifest_path),
        "config_sha256": file_sha256(config_path),
        "workload_sha256": file_sha256(workload_path),
        "integrity_source_count": len(manifest_sources),
        "quality_source_count": len(quality_names),
        "quality_evaluations_per_source": len(declared_evaluations),
        "planned_evaluation_sequence_count": (
            len(quality_names) * len(declared_evaluations)
        ),
        "corpus_gate_ready": False,
        "release_boundary": (
            "A workload definition validates scope only. It contains no provider "
            "output, quality score, reviewer decision, or founder approval."
        ),
    }
    return summary


def build_provider_call_plan(
    manifest_path: Path,
    config_path: Path,
    workload_path: Path,
    *,
    repository_root: Path | None = None,
) -> Json:
    validation = validate_workload_definition(
        manifest_path,
        config_path,
        workload_path,
        repository_root=repository_root,
    )
    if validation["status"] != "pass":
        raise ValueError("invalid workload definition: " + "; ".join(validation["errors"]))
    workload = _load_object(workload_path)
    ring_set_id = str(workload["ring_quality_evaluation_set_id"])
    evaluations = workload["evaluation_sets"][ring_set_id]
    max_attempts = int(_load_object(config_path)["thresholds"]["max_attempts"])
    items: list[Json] = []
    for source in sorted(workload["sources"], key=lambda row: row["filename"]):
        quality = source.get("quality")
        if not isinstance(quality, dict):
            continue
        for evaluation in sorted(
            evaluations,
            key=lambda row: (row["kind"], row["evaluation_id"]),
        ):
            kind = str(evaluation["kind"])
            evaluation_id = str(evaluation["evaluation_id"])
            stem = f"{Path(source['filename']).stem}--{kind}--{evaluation_id}"
            items.append({
                "source_filename": source["filename"],
                "source_sha256": source["sha256"],
                "quality_slice": "ring",
                "kind": kind,
                "evaluation_id": evaluation_id,
                "operation_class": evaluation.get("operation_class"),
                "maximum_attempts": max_attempts,
                "candidate_artifact_stem": stem,
                "mask_artifact_stem": stem + "--mask" if kind == "edit" else None,
            })
    return {
        "schema_version": PLAN_SCHEMA,
        "status": "plan_ready",
        "corpus_id": workload["corpus_id"],
        "manifest_sha256": validation["manifest_sha256"],
        "config_sha256": validation["config_sha256"],
        "workload_sha256": validation["workload_sha256"],
        "provider_calls_executed": 0,
        "integrity_source_count": validation["integrity_source_count"],
        "quality_source_count": validation["quality_source_count"],
        "planned_evaluation_sequence_count": len(items),
        "maximum_provider_attempt_count": len(items) * max_attempts,
        "items": items,
        "capture_status": "not_run",
        "corpus_gate_ready": False,
    }


def canonical_capture_payload(capture: Json) -> bytes:
    unsigned = {key: value for key, value in capture.items() if key != "signature"}
    return json.dumps(
        unsigned,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _artifact_path(capture_path: Path, value: object) -> Path | None:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        return None
    root = capture_path.parent.resolve()
    candidate = (root / value).resolve()
    if not candidate.is_relative_to(root):
        return None
    return candidate


def _load_capture_public_key(path: Path) -> Ed25519PublicKey:
    content = path.read_bytes()
    if len(content) == 32:
        return Ed25519PublicKey.from_public_bytes(content)
    key = load_pem_public_key(content)
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("capture public key is not Ed25519")
    return key


def validate_capture_envelope(
    capture_path: Path,
    manifest_path: Path,
    config_path: Path,
    workload_path: Path,
    *,
    capture_public_key_path: Path,
    capture_key_id: str,
    repository_root: Path | None = None,
) -> Json:
    """Validate a secured executor's signed capture without replaying quality."""

    plan = build_provider_call_plan(
        manifest_path,
        config_path,
        workload_path,
        repository_root=repository_root,
    )
    capture = _load_object(capture_path)
    errors: list[str] = []
    if capture.get("schema_version") != CAPTURE_SCHEMA:
        errors.append("unsupported capture schema_version")
    for field in ("manifest_sha256", "config_sha256", "workload_sha256"):
        if capture.get(field) != plan[field]:
            errors.append(f"capture {field} differs from the frozen plan")

    expected = {
        (row["kind"], row["evaluation_id"], row["source_filename"]): row
        for row in plan["items"]
    }
    attempts = capture.get("attempts")
    if not isinstance(attempts, list):
        attempts = []
        errors.append("capture attempts must be a list")
    grouped: dict[tuple[str, str, str], list[Json]] = defaultdict(list)
    artifact_count = 0
    artifact_paths_seen: set[str] = set()
    for index, row in enumerate(attempts, 1):
        if not isinstance(row, dict):
            errors.append(f"capture attempt {index} must be an object")
            continue
        key = (
            str(row.get("kind") or ""),
            str(row.get("evaluation_id") or ""),
            str(row.get("source_filename") or ""),
        )
        planned = expected.get(key)
        if planned is None:
            errors.append("capture contains an unplanned assignment: " + ":".join(key))
            continue
        if row.get("source_sha256") != planned["source_sha256"]:
            errors.append(f"capture source hash differs for attempt {index}")
        if type(row.get("accepted")) is not bool:
            errors.append(f"capture attempt {index} accepted must be boolean")
        if key[0] == "render":
            if (
                type(row.get("render_conformance_score")) not in {int, float}
                or type(row.get("hard_gate_pass")) is not bool
            ):
                errors.append(f"capture render attempt {index} lacks machine scores")
        elif (
            type(row.get("edit_fidelity_score")) not in {int, float}
            or row.get("severity") not in {"none", "minor", "major"}
            or type(row.get("change_applied")) is not bool
        ):
            errors.append(f"capture edit attempt {index} lacks machine scores")
        grouped[key].append(row)
        for field in ("candidate_image", "mask_image"):
            if field == "mask_image" and key[0] != "edit":
                if row.get(field) is not None:
                    errors.append(f"render attempt {index} declares a mask")
                continue
            artifact = _artifact_path(capture_path, row.get(field))
            expected_hash = row.get(f"{field}_sha256")
            relative_path = row.get(field)
            if isinstance(relative_path, str) and relative_path in artifact_paths_seen:
                errors.append(f"capture artifact path is reused: {relative_path}")
            elif isinstance(relative_path, str):
                artifact_paths_seen.add(relative_path)
            if artifact is None or not artifact.is_file():
                errors.append(f"capture attempt {index} has invalid {field} path")
            elif not _hex_digest(expected_hash) or file_sha256(artifact) != expected_hash:
                errors.append(f"capture attempt {index} {field} hash differs")
            else:
                artifact_count += 1

    missing = sorted(set(expected) - set(grouped))
    if missing:
        errors.append(f"capture is missing {len(missing)} planned evaluation sequences")
    max_attempts = max((int(row["maximum_attempts"]) for row in expected.values()), default=0)
    for key, rows in grouped.items():
        indexes = [row.get("attempt") for row in rows]
        if (
            any(type(index) is not int for index in indexes)
            or sorted(indexes) != list(range(1, len(rows) + 1))
            or len(rows) > max_attempts
        ):
            errors.append("capture attempts are not contiguous/in-bounds: " + ":".join(key))
        accepted_indexes = [
            row.get("attempt") for row in rows if row.get("accepted") is True
        ]
        valid_indexes = [index for index in indexes if type(index) is int]
        if len(accepted_indexes) > 1 or (
            accepted_indexes
            and valid_indexes
            and accepted_indexes[0] != max(valid_indexes)
        ):
            errors.append("capture acceptance sequence is invalid: " + ":".join(key))

    persistence = capture.get("persistence_evidence_ref")
    if not isinstance(persistence, dict):
        errors.append("capture persistence_evidence_ref is missing")
    else:
        artifact = _artifact_path(capture_path, persistence.get("relative_path"))
        expected_hash = persistence.get("sha256")
        if artifact is None or not artifact.is_file():
            errors.append("capture persistence evidence path is invalid")
        elif not _hex_digest(expected_hash) or file_sha256(artifact) != expected_hash:
            errors.append("capture persistence evidence hash differs")

    signature = capture.get("signature")
    signature_status = "not_verified"
    try:
        public_key_hash = file_sha256(capture_public_key_path)
    except OSError:
        public_key_hash = None
        errors.append("capture public key is unavailable")
    if not capture_key_id.strip():
        errors.append("capture key_id is empty")
    if not isinstance(signature, dict):
        errors.append("capture is unsigned")
    elif (
        signature.get("algorithm") != "Ed25519"
        or signature.get("key_id") != capture_key_id
        or signature.get("public_key_sha256") != public_key_hash
        or not isinstance(signature.get("value"), str)
    ):
        errors.append("capture signature metadata is invalid")
    else:
        try:
            decoded = base64.b64decode(signature["value"], validate=True)
            _load_capture_public_key(capture_public_key_path).verify(
                decoded,
                canonical_capture_payload(capture),
            )
            signature_status = "verified"
        except (InvalidSignature, OSError, TypeError, ValueError):
            errors.append("capture signature is invalid")

    return {
        "schema_version": "facetta-frozen-capture-validation.v1",
        "status": "pass" if not errors else "fail",
        "provider_calls": 0,
        "errors": errors,
        "signature_status": signature_status,
        "planned_evaluation_sequence_count": len(expected),
        "captured_evaluation_sequence_count": len(set(expected) & set(grouped)),
        "captured_attempt_count": len(attempts),
        "verified_artifact_count": artifact_count,
        "corpus_gate_ready": False,
        "release_boundary": (
            "A signed capture proves executor provenance and artifact binding only. "
            "It is not the signed GIA review or founder release decision."
        ),
    }

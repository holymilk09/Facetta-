"""Provider-free validation and replay for a frozen image corpus gate.

The compiler deliberately separates source integrity from image quality.  It
can prove that a versioned corpus and configuration are unchanged without any
provider credentials.  Quality is only evaluated when a complete captured
replay is supplied; missing evidence is ``not_run`` and the release gate fails
closed.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from PIL import Image
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from facetta.image_agent.drift import outside_mask_drift
from facetta.ring_evals import evaluate_release_gates


Json = dict[str, Any]


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_evidence_payload(evidence: Json) -> bytes:
    """Return the exact bytes covered by the reviewer signature."""

    unsigned = {key: value for key, value in evidence.items() if key != "signature"}
    return json.dumps(
        unsigned,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _load_object(path: Path) -> Json:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _duplicate_values(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def _validate_manifest(manifest: Json) -> tuple[list[Json], list[str]]:
    errors: list[str] = []
    if manifest.get("schema_version") != "facetta-frozen-corpus.v1":
        errors.append("unsupported manifest schema_version")
    sources = manifest.get("sources")
    if not isinstance(sources, list):
        return [], errors + ["manifest sources must be a list"]
    rows = [row for row in sources if isinstance(row, dict)]
    if len(rows) != len(sources):
        errors.append("every manifest source must be an object")
    expected_count = manifest.get("expected_source_count")
    if type(expected_count) is not int or expected_count < 1:
        errors.append("expected_source_count must be a positive integer")
    elif len(rows) != expected_count:
        errors.append(
            f"manifest source count {len(rows)} does not equal {expected_count}"
        )
    names = [str(row.get("filename") or "") for row in rows]
    hashes = [str(row.get("sha256") or "") for row in rows]
    if any(not name or Path(name).name != name for name in names):
        errors.append("source filenames must be non-empty basenames")
    duplicate_names = _duplicate_values(names)
    if duplicate_names:
        errors.append("duplicate source filenames: " + ", ".join(duplicate_names))
    duplicate_hashes = _duplicate_values(hashes)
    if duplicate_hashes:
        errors.append("duplicate source hashes: " + ", ".join(duplicate_hashes))
    if any(len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest)
           for digest in hashes):
        errors.append("every source sha256 must be 64 lowercase hex characters")

    evaluation = manifest.get("evaluation_slice")
    if not isinstance(evaluation, dict):
        errors.append("evaluation_slice must be an object")
        return rows, errors
    ring_names = evaluation.get("ring_source_filenames")
    if not isinstance(ring_names, list) or not ring_names:
        errors.append("ring_source_filenames must be a non-empty list")
    else:
        unknown = sorted(set(map(str, ring_names)) - set(names))
        if unknown:
            errors.append("ring slice references unknown sources: " + ", ".join(unknown))
        duplicate_ring = _duplicate_values(list(map(str, ring_names)))
        if duplicate_ring:
            errors.append("duplicate ring slice sources: " + ", ".join(duplicate_ring))
    for field in ("render_case_ids", "operation_ids"):
        values = evaluation.get(field)
        if not isinstance(values, list) or not values:
            errors.append(f"{field} must be a non-empty list")
        elif _duplicate_values(list(map(str, values))):
            errors.append(f"{field} contains duplicates")
    return rows, errors


def _validate_config(
    config: Json,
    manifest: Json,
    manifest_hash: str,
    repository_root: Path,
) -> list[str]:
    errors: list[str] = []
    if config.get("schema_version") != "facetta-frozen-gate-config.v1":
        errors.append("unsupported config schema_version")
    if config.get("corpus_id") != manifest.get("corpus_id"):
        errors.append("config corpus_id does not match manifest")
    if config.get("manifest_sha256") != manifest_hash:
        errors.append("config manifest_sha256 does not match manifest bytes")
    thresholds = config.get("thresholds")
    required = {
        "render_hard_gate_pass_rate": 0.90,
        "mean_render_conformance": 85,
        "mean_edit_fidelity": 90,
        "max_attempts": 3,
        "max_outside_mask_drift": 0.18,
    }
    if not isinstance(thresholds, dict):
        errors.append("config thresholds must be an object")
    else:
        for key, expected in required.items():
            if thresholds.get(key) != expected:
                errors.append(
                    f"config threshold {key} must remain pinned to {expected}"
                )
    frozen = config.get("frozen_components")
    if not isinstance(frozen, dict) or any(
        not isinstance(frozen.get(key), str) or not frozen.get(key)
        for key in (
            "ring_contract", "prompt_bundle", "evaluator_bundle", "routing",
            "live_runner",
        )
    ):
        errors.append("config frozen_components are incomplete")
    elif isinstance(frozen, dict):
        root = repository_root.resolve()
        for key in (
            "ring_contract", "prompt_bundle", "evaluator_bundle", "live_runner",
        ):
            value = str(frozen[key])
            if "@sha256:" not in value:
                errors.append(f"config frozen component {key} is not hash-pinned")
                continue
            relative, expected_hash = value.rsplit("@sha256:", 1)
            candidate = (root / relative).resolve()
            if (
                not relative or Path(relative).is_absolute()
                or not candidate.is_relative_to(root)
                or not candidate.is_file()
            ):
                errors.append(f"config frozen component {key} path is unavailable")
                continue
            if file_sha256(candidate) != expected_hash:
                errors.append(f"config frozen component {key} implementation drifted")
    reviewer_key = config.get("reviewer_public_key")
    if reviewer_key is not None:
        if not isinstance(reviewer_key, dict):
            errors.append("reviewer_public_key must be null or an object")
        else:
            key_id = reviewer_key.get("key_id")
            relative = reviewer_key.get("path")
            expected_hash = reviewer_key.get("sha256")
            root = repository_root.resolve()
            candidate = (
                (root / str(relative)).resolve()
                if isinstance(relative, str) else None
            )
            if not isinstance(key_id, str) or not key_id.strip():
                errors.append("reviewer public key_id is missing")
            if (
                candidate is None or not isinstance(relative, str)
                or Path(relative).is_absolute()
                or not candidate.is_relative_to(root)
                or not candidate.is_file()
            ):
                errors.append("reviewer public-key file is unavailable")
            elif file_sha256(candidate) != expected_hash:
                errors.append("reviewer public-key file hash differs from config")
    return errors


def _verify_sources(rows: list[Json], source_dir: Path) -> Json:
    failures: list[Json] = []
    verified = 0
    for row in rows:
        filename = str(row.get("filename") or "")
        path = source_dir / filename
        if not path.is_file():
            failures.append({"filename": filename, "code": "missing"})
            continue
        digest = file_sha256(path)
        if digest != row.get("sha256"):
            failures.append({
                "filename": filename,
                "code": "sha256_mismatch",
                "expected": row.get("sha256"),
                "observed": digest,
            })
            continue
        try:
            with Image.open(path) as image:
                image.verify()
        except Exception as exc:
            failures.append({
                "filename": filename,
                "code": "not_decodable",
                "detail": str(exc),
            })
            continue
        verified += 1
    return {
        "status": "pass" if not failures and verified == len(rows) else "fail",
        "expected": len(rows),
        "verified": verified,
        "failures": failures,
    }


def _resolve_capture(base: Path, value: object) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else base / path


def _reviewer_public_key(
    config: Json,
    repository_root: Path,
) -> tuple[Ed25519PublicKey | None, str | None, str | None]:
    configured = config.get("reviewer_public_key")
    if not isinstance(configured, dict):
        return None, None, "reviewer public key is not configured"
    key_id = configured.get("key_id")
    relative = configured.get("path")
    if not isinstance(key_id, str) or not isinstance(relative, str):
        return None, None, "reviewer public-key configuration is incomplete"
    path = (repository_root / relative).resolve()
    if not path.is_file() or file_sha256(path) != configured.get("sha256"):
        return None, key_id, "reviewer public-key file failed its configured hash"
    content = path.read_bytes()
    try:
        if len(content) == 32:
            return Ed25519PublicKey.from_public_bytes(content), key_id, None
        key = load_pem_public_key(content)
        if not isinstance(key, Ed25519PublicKey):
            return None, key_id, "configured reviewer key is not Ed25519"
        return key, key_id, None
    except (TypeError, ValueError) as exc:
        return None, key_id, f"reviewer public key is invalid: {exc}"


def _verify_signature(
    evidence: Json,
    config: Json,
    repository_root: Path,
) -> Json:
    public_key, configured_key_id, key_error = _reviewer_public_key(
        config, repository_root,
    )
    signature = evidence.get("signature")
    if key_error:
        return {"status": "not_verified", "error": key_error}
    if not isinstance(signature, dict):
        return {"status": "not_verified", "error": "replay is unsigned"}
    if signature.get("algorithm") != "Ed25519":
        return {"status": "not_verified", "error": "signature algorithm is not Ed25519"}
    if signature.get("key_id") != configured_key_id:
        return {"status": "not_verified", "error": "signature key_id differs from config"}
    encoded = signature.get("value")
    if not isinstance(encoded, str):
        return {"status": "not_verified", "error": "signature value is missing"}
    try:
        decoded = base64.b64decode(encoded, validate=True)
        assert public_key is not None
        public_key.verify(decoded, canonical_evidence_payload(evidence))
    except (InvalidSignature, ValueError, TypeError):
        return {"status": "not_verified", "error": "replay signature is invalid"}
    return {"status": "verified", "key_id": configured_key_id}


def _verify_declared_artifact(
    row: Json,
    evidence_dir: Path,
    field: str,
    errors: list[str],
    label: str,
) -> Path | None:
    path = _resolve_capture(evidence_dir, row.get(field))
    expected_hash = row.get(f"{field}_sha256")
    if path is None or not path.is_file():
        errors.append(f"{label} lacks {field} artifact")
        return None
    if not isinstance(expected_hash, str) or file_sha256(path) != expected_hash:
        errors.append(f"{label} {field} artifact hash mismatch")
        return None
    return path


def _source_coverage(
    evidence: Json,
    manifest: Json,
    expected_evaluations: set[tuple[str, str]],
    verified_source_evaluations: dict[str, set[str]],
) -> Json:
    expected_sources = {
        str(row["filename"]): str(row["sha256"])
        for row in manifest["sources"]
    }
    rows = evidence.get("source_coverage")
    errors: list[str] = []
    if not isinstance(rows, list):
        rows = []
        errors.append("source_coverage must be a list")
    objects = [row for row in rows if isinstance(row, dict)]
    if len(objects) != len(rows):
        errors.append("every source_coverage row must be an object")
    names = [str(row.get("filename") or "") for row in objects]
    duplicates = _duplicate_values(names)
    if duplicates:
        errors.append("duplicate source coverage: " + ", ".join(duplicates))
    claimed: set[str] = set()
    failed: set[str] = set()
    expected_ids = {evaluation_id for _, evaluation_id in expected_evaluations}
    for row in objects:
        filename = str(row.get("filename") or "")
        if filename not in expected_sources:
            errors.append(f"source coverage references unknown source: {filename}")
            continue
        if row.get("source_sha256") != expected_sources[filename]:
            errors.append(f"source coverage hash differs for {filename}")
            continue
        evaluation_ids = row.get("evaluation_ids")
        if (
            not isinstance(evaluation_ids, list) or not evaluation_ids
            or any(str(item) not in expected_ids for item in evaluation_ids)
        ):
            errors.append(f"source coverage evaluations are invalid for {filename}")
            continue
        actual_ids = verified_source_evaluations.get(filename, set())
        if set(map(str, evaluation_ids)) != actual_ids:
            errors.append(
                f"source coverage evaluations do not match verified attempts for {filename}"
            )
            continue
        status = row.get("quality_status")
        if status not in {"pass", "fail"}:
            errors.append(f"source coverage quality_status is invalid for {filename}")
            continue
        claimed.add(filename)
        if status == "fail":
            failed.add(filename)
    completed = set(expected_sources) & set(verified_source_evaluations)
    missing = sorted(set(expected_sources) - completed)
    if missing:
        errors.append("missing artifact-verified source coverage: " + ", ".join(missing))
    unclaimed = sorted(completed - claimed)
    if unclaimed:
        errors.append("verified source attempts lack matching coverage rows: " + ", ".join(unclaimed))
    return {
        "status": "pass" if not errors and not failed else "fail",
        "expected_source_count": len(expected_sources),
        "completed_source_count": len(completed),
        "failed_source_count": len(failed),
        "missing_source_filenames": missing,
        "errors": errors,
    }


def _replay_quality(
    evidence: Json,
    evidence_path: Path,
    manifest: Json,
    config: Json,
    manifest_hash: str,
    config_hash: str,
    repository_root: Path,
) -> Json:
    errors: list[str] = []
    if evidence.get("schema_version") != "facetta-frozen-replay.v1":
        errors.append("unsupported replay schema_version")
    if evidence.get("manifest_sha256") != manifest_hash:
        errors.append("replay manifest hash differs from frozen manifest")
    if evidence.get("config_sha256") != config_hash:
        errors.append("replay config hash differs from frozen config")
    signature = _verify_signature(evidence, config, repository_root)
    if signature["status"] != "verified":
        errors.append(str(signature.get("error") or "replay signature is not verified"))
    attempts = evidence.get("attempts")
    if not isinstance(attempts, list) or not attempts:
        return {
            "status": "not_run",
            "errors": errors + ["no captured attempts were supplied"],
            "signature": signature,
            "source_coverage": {
                "status": "not_run",
                "expected_source_count": len(manifest.get("sources", [])),
                "completed_source_count": 0,
            },
            "release_gates": {"status": "not_evaluated"},
        }
    if any(not isinstance(row, dict) for row in attempts):
        errors.append("every captured attempt must be an object")
        attempts = [row for row in attempts if isinstance(row, dict)]

    evaluation = manifest["evaluation_slice"]
    expected = {
        ("render", str(value)) for value in evaluation["render_case_ids"]
    } | {
        ("edit", str(value)) for value in evaluation["operation_ids"]
    }
    grouped: dict[tuple[str, str, str], list[Json]] = defaultdict(list)
    for row in attempts:
        key = (
            str(row.get("kind") or ""),
            str(row.get("evaluation_id") or ""),
            str(row.get("source_filename") or ""),
        )
        grouped[key].append(row)
    observed_evaluations = {(kind, evaluation_id) for kind, evaluation_id, _ in grouped}
    missing = sorted(expected - observed_evaluations)
    unexpected = sorted(observed_evaluations - expected)
    if missing:
        errors.append("missing evaluations: " + ", ".join(f"{a}:{b}" for a, b in missing))
    if unexpected:
        errors.append("unexpected evaluations: " + ", ".join(f"{a}:{b}" for a, b in unexpected))

    thresholds = config["thresholds"]
    max_attempts = int(thresholds["max_attempts"])
    rows: list[Json] = []
    replayed_drift: list[Json] = []
    artifact_paths: dict[int, dict[str, Path]] = {}
    verified_source_evaluations: dict[str, set[str]] = defaultdict(set)
    manifest_sources = {
        str(row["filename"]): str(row["sha256"])
        for row in manifest["sources"]
    }
    for captured in attempts:
        label = (
            f"{captured.get('kind')}:{captured.get('evaluation_id')}:"
            f"attempt-{captured.get('attempt')}"
        )
        source_filename = str(captured.get("source_filename") or "")
        source_hash = captured.get("source_sha256")
        binding_valid = manifest_sources.get(source_filename) == source_hash
        if not binding_valid:
            errors.append(f"{label} is not bound to a frozen source filename/hash")
        paths: dict[str, Path] = {}
        for field in ("source_image", "candidate_image"):
            artifact = _verify_declared_artifact(
                captured, evidence_path.parent, field, errors, label,
            )
            if artifact is not None:
                paths[field] = artifact
        if "source_image" in paths and file_sha256(paths["source_image"]) != source_hash:
            errors.append(f"{label} source artifact differs from frozen source hash")
            binding_valid = False
        if captured.get("kind") == "edit":
            mask = _verify_declared_artifact(
                captured, evidence_path.parent, "mask_image", errors, label,
            )
            if mask is not None:
                paths["mask_image"] = mask
        artifact_paths[id(captured)] = paths
        required_artifacts = {"source_image", "candidate_image"}
        if captured.get("kind") == "edit":
            required_artifacts.add("mask_image")
        evaluation_pair = (
            str(captured.get("kind") or ""),
            str(captured.get("evaluation_id") or ""),
        )
        if (
            binding_valid
            and required_artifacts <= set(paths)
            and evaluation_pair in expected
        ):
            verified_source_evaluations[source_filename].add(evaluation_pair[1])
    coverage = _source_coverage(
        evidence, manifest, expected, verified_source_evaluations,
    )
    errors.extend(coverage["errors"])
    for sequence_key in sorted(grouped):
        key = sequence_key[:2]
        source_filename = sequence_key[2]
        if key not in expected:
            continue
        captured = sorted(grouped[sequence_key], key=lambda row: (
            row.get("attempt") if type(row.get("attempt")) is int else 10**9
        ))
        indexes = [row.get("attempt") for row in captured]
        if any(type(index) is not int or index < 1 for index in indexes):
            errors.append(f"{key[0]}:{key[1]} has invalid attempt indexes")
            continue
        if len(set(indexes)) != len(indexes):
            errors.append(f"{key[0]}:{key[1]} has duplicate attempt indexes")
        attempts_used = max(indexes, default=0)
        if attempts_used > max_attempts:
            errors.append(f"{key[0]}:{key[1]} exceeded {max_attempts} attempts")
        accepted = [row for row in captured if row.get("accepted") is True]
        if len(accepted) > 1:
            errors.append(f"{key[0]}:{key[1]} has multiple accepted attempts")
        selected = accepted[-1] if accepted else (captured[-1] if captured else {})
        if accepted and selected.get("attempt") != attempts_used:
            errors.append(f"{key[0]}:{key[1]} continued after acceptance")
        if key[0] == "render":
            score = selected.get("render_conformance_score")
            hard_pass = selected.get("hard_gate_pass")
            if not isinstance(score, (int, float)) or type(hard_pass) is not bool:
                errors.append(f"render:{key[1]} lacks scored capture evidence")
                continue
            rows.append({
                "kind": "render", "case": f"{key[1]}@{source_filename}", "score": score,
                "hard_gate_pass": hard_pass, "attempts": attempts_used,
            })
            continue

        score = selected.get("edit_fidelity_score")
        severity = selected.get("severity")
        applied = selected.get("change_applied")
        if (not isinstance(score, (int, float))
                or severity not in {"none", "minor", "major"}
                or type(applied) is not bool):
            errors.append(f"edit:{key[1]} lacks scored capture evidence")
            continue
        selected_paths = artifact_paths.get(id(selected), {})
        parent = selected_paths.get("source_image")
        child = selected_paths.get("candidate_image")
        mask = selected_paths.get("mask_image")
        if not all(path is not None for path in (parent, child, mask)):
            errors.append(f"edit:{key[1]} lacks replayable source/candidate/mask files")
            continue
        assert parent is not None and child is not None and mask is not None
        drift = outside_mask_drift(parent.read_bytes(), child.read_bytes(), mask.read_bytes())
        drift_pass = drift <= float(thresholds["max_outside_mask_drift"])
        replayed_drift.append({
            "evaluation_id": key[1], "source_filename": source_filename,
            "attempt": selected.get("attempt"),
            "outside_mask_drift": round(drift, 6), "pass": drift_pass,
        })
        rows.append({
            "kind": "edit", "case": f"{key[1]}@{source_filename}", "score": score,
            "applied": bool(selected.get("accepted")) and applied and drift_pass,
            "attempts": attempts_used, "severity": severity,
            "expected_valid": True,
        })

    persistence = evidence.get("persistence_evidence")
    if not isinstance(persistence, dict):
        persistence = {}
        errors.append("canonical persistence evidence is missing")
    release = evaluate_release_gates(rows, persistence_evidence=persistence)
    reviewer = evidence.get("reviewer_review")
    review_complete = (
        isinstance(reviewer, dict)
        and reviewer.get("completed") is True
        and isinstance(reviewer.get("reviewer"), str)
        and bool(reviewer.get("reviewer", "").strip())
        and reviewer.get("qualification") == "GIA-trained"
        and type(reviewer.get("false_positives")) is int
        and type(reviewer.get("false_negatives")) is int
    )
    if not review_complete:
        errors.append("GIA-trained reviewer evidence is incomplete")
    all_drift_pass = bool(replayed_drift) and all(row["pass"] for row in replayed_drift)
    passed = (
        not errors
        and observed_evaluations == expected
        and signature["status"] == "verified"
        and coverage["status"] == "pass"
        and release.get("automated_gates_pass") is True
        and all_drift_pass
        and review_complete
    )
    return {
        "status": "pass" if passed else "fail",
        "errors": errors,
        "signature": signature,
        "source_coverage": coverage,
        "captured_attempt_count": len(attempts),
        "expected_evaluation_count": len(expected),
        "completed_evaluation_count": len(observed_evaluations & expected),
        "outside_mask_replay": replayed_drift,
        "all_outside_mask_drift_pass": all_drift_pass,
        "release_gates": release,
        "reviewer_review_complete": review_complete,
    }


def compile_frozen_corpus_gate(
    manifest_path: Path,
    config_path: Path,
    source_dir: Path,
    evidence_path: Path | None = None,
    repository_root: Path | None = None,
) -> Json:
    manifest = _load_object(manifest_path)
    config = _load_object(config_path)
    manifest_hash = file_sha256(manifest_path)
    config_hash = file_sha256(config_path)
    rows, manifest_errors = _validate_manifest(manifest)
    resolved_repository_root = (
        repository_root or Path(__file__).resolve().parents[2]
    )
    config_errors = _validate_config(
        config,
        manifest,
        manifest_hash,
        resolved_repository_root,
    )
    source_integrity = _verify_sources(rows, source_dir) if rows else {
        "status": "fail", "expected": 0, "verified": 0,
        "failures": [{"code": "manifest_invalid"}],
    }
    if evidence_path is None:
        quality: Json = {
            "status": "not_run",
            "errors": ["no captured replay evidence was supplied"],
            "signature": {"status": "not_run"},
            "source_coverage": {
                "status": "not_run",
                "expected_source_count": len(rows),
                "completed_source_count": 0,
            },
            "release_gates": {"status": "not_evaluated"},
        }
    else:
        quality = _replay_quality(
            _load_object(evidence_path), evidence_path, manifest, config,
            manifest_hash, config_hash, resolved_repository_root,
        )
    definition_errors = manifest_errors + config_errors
    passed = (
        not definition_errors
        and source_integrity["status"] == "pass"
        and quality["status"] == "pass"
    )
    return {
        "run_kind": "provider_free_frozen_corpus_gate",
        "provider_calls": 0,
        "manifest": {
            "path": str(manifest_path), "sha256": manifest_hash,
            "corpus_id": manifest.get("corpus_id"),
        },
        "config": {"path": str(config_path), "sha256": config_hash},
        "definition": {
            "status": "pass" if not definition_errors else "fail",
            "errors": definition_errors,
        },
        "source_integrity": source_integrity,
        "quality": quality,
        "status": "pass" if passed else "incomplete_or_failed",
        "release_ready": passed,
        "release_boundary": (
            "Source integrity is not image quality. Missing captures, canonical "
            "persistence proof, or GIA-trained review fail closed and must never "
            "be reported as a quality pass."
        ),
    }

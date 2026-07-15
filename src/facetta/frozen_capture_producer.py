"""Fail-closed producer for signed frozen-corpus capture evidence.

The producer is intentionally transport-agnostic.  It validates the complete
frozen plan, source bytes, enrolled signer identities, output confinement, and
an executor's static inputs before the executor seam can run.  The bundled
JSON executor performs no provider calls; a secured deployment may supply a
different implementation of :class:`CaptureExecutor`.
"""

from __future__ import annotations

import base64
import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    load_pem_private_key,
    load_pem_public_key,
)

from facetta.frozen_capture_workload import (
    ATTEMPT_OUTCOME_FIELDS,
    ATTEMPT_ROUTING_FIELDS,
    CAPTURE_SCHEMA,
    build_provider_call_plan,
    canonical_capture_payload,
    canonical_object_sha256,
    attempt_sequence_errors,
    file_sha256,
    not_applicable_assignment_rows,
    validate_capture_envelope,
)
from facetta.frozen_evidence_paths import (
    build_artifact_index,
    confined_output_path,
    confined_path,
    evidence_root as resolve_evidence_root,
    validate_artifact_index,
)
from facetta.frozen_corpus_gate import validate_frozen_component_pins
from facetta.frozen_evaluator_report import validate_and_replay_evaluator_report
from facetta.frozen_persistence_attestation import (
    ATTESTATION_SCHEMA,
    CANONICAL_API_SCHEMA,
    RESULT_SET_SCHEMA,
    canonical_attestation_payload,
    canonical_result_set,
    result_set_sha256,
    verify_persistence_attestation,
)


Json = dict[str, Any]
EXECUTION_BUNDLE_SCHEMA = "facetta-frozen-execution-bundle.v2"
PERSISTENCE_OBSERVATIONS_SCHEMA = (
    "facetta-canonical-persistence-observations.v1"
)
PRODUCTION_SUMMARY_SCHEMA = "facetta-frozen-capture-production.v1"


def _load_object(path: Path) -> Json:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _sha256_value(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _git_sha(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) in {40, 64}
        and all(character in "0123456789abcdef" for character in value)
    )


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _public_key(path: Path) -> Ed25519PublicKey:
    content = path.read_bytes()
    if len(content) == 32:
        return Ed25519PublicKey.from_public_bytes(content)
    key = load_pem_public_key(content)
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("enrolled key is not Ed25519")
    return key


@dataclass(frozen=True)
class EnrolledKey:
    key_id: str
    path: Path
    file_sha256: str
    public_key: Ed25519PublicKey


class CaptureSigner(Protocol):
    """Signing seam whose identity is challenged against a frozen public key."""

    key_id: str

    def sign(self, payload: bytes) -> bytes:
        ...


@dataclass(frozen=True)
class Ed25519PrivateKeySigner:
    """In-memory signer loaded from a private key kept outside run evidence."""

    key_id: str
    private_key: Ed25519PrivateKey

    @classmethod
    def from_file(
        cls,
        path: Path,
        *,
        key_id: str,
        forbidden_roots: tuple[Path, ...] = (),
    ) -> "Ed25519PrivateKeySigner":
        resolved = path.resolve()
        if not resolved.is_file():
            raise ValueError("private signing key is unavailable")
        if any(resolved.is_relative_to(root.resolve()) for root in forbidden_roots):
            raise ValueError(
                "private signing key must remain outside the repository and evidence root"
            )
        content = resolved.read_bytes()
        try:
            if len(content) == 32:
                key = Ed25519PrivateKey.from_private_bytes(content)
            else:
                loaded = load_pem_private_key(content, password=None)
                if not isinstance(loaded, Ed25519PrivateKey):
                    raise ValueError("private signing key is not Ed25519")
                key = loaded
        except (TypeError, ValueError) as exc:
            raise ValueError("private signing key is invalid") from exc
        return cls(key_id=key_id, private_key=key)

    def sign(self, payload: bytes) -> bytes:
        return self.private_key.sign(payload)


class CaptureExecutor(Protocol):
    """Pluggable secured-execution seam.

    ``preflight`` must not call an image provider.  ``execute`` returns one to
    three already-scored attempts whose artifact paths remain inside the
    evidence root.
    """

    provider_calls_executed: int

    def preflight(self, *, plan: Json, evidence_root: Path) -> None:
        ...

    def execute(self, item: Json) -> list[Json]:
        ...


class PersistenceObservationRunner(Protocol):
    """Pluggable canonical-API observation seam.

    The runner returns observations, not an attestation.  The producer binds
    and signs those observations to the exact selected result set.
    """

    def preflight(self, *, plan: Json) -> None:
        ...

    def observe(self, *, selected_result_set: list[Json]) -> Json:
        ...


class BundleCaptureExecutor:
    """Provider-free adapter for externally produced execution artifacts."""

    provider_calls_executed = 0

    def __init__(self, bundle_path: Path):
        self.bundle_path = bundle_path
        self._bundle: Json | None = None
        self._rows: dict[tuple[str, str, str], Json] = {}

    def preflight(self, *, plan: Json, evidence_root: Path) -> None:
        bundle_path = confined_path(
            evidence_root,
            self.bundle_path,
            label="execution bundle",
            kind="file",
        )
        bundle = _load_object(bundle_path)
        errors: list[str] = []
        if bundle.get("schema_version") != EXECUTION_BUNDLE_SCHEMA:
            errors.append("execution bundle schema_version is unsupported")
        if bundle.get("corpus_run_id") != plan.get("corpus_run_id"):
            errors.append("execution bundle corpus_run_id differs from plan")
        if bundle.get("plan_sha256") != canonical_object_sha256(plan):
            errors.append("execution bundle plan hash differs")
        declared_calls = bundle.get("provider_calls_executed")
        if type(declared_calls) is not int or declared_calls < 0:
            errors.append("execution bundle provider call count is invalid")
            declared_calls = 0
        if declared_calls > int(plan.get("maximum_provider_attempt_count") or 0):
            errors.append("execution bundle exceeds the frozen provider-call ceiling")
        sequences = bundle.get("sequences")
        if not isinstance(sequences, list) or any(
            not isinstance(row, dict) for row in sequences
        ):
            errors.append("execution bundle sequences must be a list of objects")
            sequences = []
        expected = {
            (row["kind"], row["evaluation_id"], row["source_filename"]): row
            for row in plan["items"]
            if row["resolved_inputs"].get("execution_ready") is True
        }
        rows: dict[tuple[str, str, str], Json] = {}
        for index, row in enumerate(sequences, 1):
            key = (
                str(row.get("kind") or ""),
                str(row.get("evaluation_id") or ""),
                str(row.get("source_filename") or ""),
            )
            planned = expected.get(key)
            if planned is None:
                errors.append(
                    "execution bundle contains an unplanned sequence: " + ":".join(key)
                )
                continue
            if key in rows:
                errors.append(
                    "execution bundle contains a duplicate sequence: " + ":".join(key)
                )
                continue
            if row.get("resolved_inputs_sha256") != planned["resolved_inputs_sha256"]:
                errors.append(
                    "execution bundle resolved-input hash differs: " + ":".join(key)
                )
            attempts = row.get("attempts")
            if not isinstance(attempts, list) or any(
                not isinstance(attempt, dict) for attempt in attempts
            ):
                errors.append(f"execution bundle sequence {index} attempts are invalid")
                attempts = []
            if not attempts or len(attempts) > int(planned["maximum_attempts"]):
                errors.append(
                    "execution bundle sequence attempt count is out of bounds: "
                    + ":".join(key)
                )
            for attempt_index, attempt in enumerate(attempts, 1):
                if attempt.get("attempt_outcome") == "provider_failed":
                    continue
                for field in ("candidate_image", "mask_image", "evaluator_report"):
                    if field == "mask_image" and key[0] != "edit":
                        if attempt.get(field) is not None:
                            errors.append(
                                f"execution bundle render attempt {attempt_index} has a mask"
                            )
                        continue
                    try:
                        artifact = confined_path(
                            evidence_root,
                            str(attempt.get(field) or ""),
                            label=(
                                f"execution bundle {':'.join(key)} attempt "
                                f"{attempt_index} {field}"
                            ),
                            kind="file",
                            require_relative=True,
                        )
                    except ValueError as exc:
                        errors.append(str(exc))
                        continue
                    digest = attempt.get(f"{field}_sha256")
                    if not _sha256_value(digest) or file_sha256(artifact) != digest:
                        errors.append(
                            f"execution bundle {':'.join(key)} attempt "
                            f"{attempt_index} {field} hash differs"
                        )
            errors.extend(_attempt_errors(attempts, planned))
            rows[key] = row
        missing = sorted(set(expected) - set(rows))
        if missing:
            errors.append(
                f"execution bundle is missing {len(missing)} planned sequences"
            )
        if errors:
            raise ValueError("; ".join(errors))
        self.provider_calls_executed = int(declared_calls)
        self._bundle = bundle
        self._rows = rows

    def execute(self, item: Json) -> list[Json]:
        key = (item["kind"], item["evaluation_id"], item["source_filename"])
        row = self._rows.get(key)
        if row is None:
            raise ValueError("execution bundle was not preflighted for planned item")
        attempts = row.get("attempts")
        assert isinstance(attempts, list)
        return [dict(attempt) for attempt in attempts]


class FilePersistenceObservationRunner:
    """Provider-free adapter for canonical API observations captured elsewhere."""

    def __init__(self, path: Path, *, evidence_root: Path):
        self.path = confined_path(
            evidence_root,
            path,
            label="persistence observations",
            kind="file",
        )
        self._value: Json | None = None

    def preflight(self, *, plan: Json) -> None:
        value = _load_object(self.path)
        if value.get("schema_version") != PERSISTENCE_OBSERVATIONS_SCHEMA:
            raise ValueError("persistence observations schema_version is unsupported")
        if value.get("corpus_run_id") != plan.get("corpus_run_id"):
            raise ValueError("persistence observations corpus_run_id differs from plan")
        self._value = value

    def observe(self, *, selected_result_set: list[Json]) -> Json:
        if self._value is None:
            raise ValueError("persistence observations were not preflighted")
        expected_hash = result_set_sha256(selected_result_set)
        if self._value.get("result_set_schema_version") != RESULT_SET_SCHEMA:
            raise ValueError("persistence observations result-set schema is unsupported")
        if self._value.get("result_set_sha256") != expected_hash:
            raise ValueError("persistence observations result-set hash differs")
        if self._value.get("result_count") != len(selected_result_set):
            raise ValueError("persistence observations result count differs")
        checks = self._value.get("checks")
        if not isinstance(checks, dict):
            raise ValueError("persistence observations checks are missing")
        return {"checks": checks}


def _load_enrolled_executor_key(config: Json, root: Path) -> EnrolledKey:
    trust = config.get("executor_trust")
    if not isinstance(trust, dict) or trust.get("status") != "enrolled":
        raise ValueError("config executor trust is not enrolled")
    key_id = trust.get("key_id")
    value = trust.get("public_key")
    if not isinstance(key_id, str) or not key_id.strip():
        raise ValueError("config executor key_id is empty")
    if not isinstance(value, str) or "@sha256:" not in value:
        raise ValueError("config executor public key is not hash-pinned")
    relative, digest = value.rsplit("@sha256:", 1)
    path = confined_path(
        root,
        relative,
        label="config executor public key",
        kind="file",
        require_relative=True,
    )
    if not _sha256_value(digest) or file_sha256(path) != digest:
        raise ValueError("config executor public key drifted")
    return EnrolledKey(key_id, path, digest, _public_key(path))


def _load_enrolled_api_key(config: Json, root: Path) -> EnrolledKey:
    value = config.get("canonical_api_runner_public_key")
    if not isinstance(value, dict):
        raise ValueError("canonical API runner public key is not enrolled")
    key_id = value.get("key_id")
    relative = value.get("path")
    digest = value.get("sha256")
    if not isinstance(key_id, str) or not key_id.strip():
        raise ValueError("canonical API runner key_id is empty")
    path = confined_path(
        root,
        str(relative or ""),
        label="canonical API runner public key",
        kind="file",
        require_relative=True,
    )
    if not _sha256_value(digest) or file_sha256(path) != digest:
        raise ValueError("canonical API runner public key drifted")
    return EnrolledKey(key_id, path, str(digest), _public_key(path))


def _challenge_signer(signer: CaptureSigner, enrolled: EnrolledKey) -> None:
    if signer.key_id != enrolled.key_id:
        raise ValueError("signer key_id differs from the config-enrolled key")
    challenge = b"facetta-frozen-capture-signer-challenge.v1"
    try:
        enrolled.public_key.verify(signer.sign(challenge), challenge)
    except Exception as exc:  # cryptography raises InvalidSignature or ValueError
        raise ValueError("signer does not control the config-enrolled key") from exc


def _attempt_errors(attempts: list[Json], planned: Json) -> list[str]:
    key = ":".join((
        str(planned["kind"]),
        str(planned["evaluation_id"]),
        str(planned["source_filename"]),
    ))
    return attempt_sequence_errors(attempts, planned, label="executor " + key)


def _copy_verified_artifact(
    *,
    evidence_root: Path,
    staging_dir: Path,
    declared_path: object,
    declared_sha256: object,
    destination: Path,
    label: str,
) -> tuple[str, str]:
    source = confined_path(
        evidence_root,
        str(declared_path or ""),
        label=label,
        kind="file",
        require_relative=not Path(str(declared_path or "")).is_absolute(),
    )
    if not _sha256_value(declared_sha256) or file_sha256(source) != declared_sha256:
        raise ValueError(f"{label} hash differs")
    output = (staging_dir / destination).resolve(strict=False)
    if not output.is_relative_to(staging_dir.resolve()):
        raise ValueError(f"{label} destination escapes capture staging")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(source.read_bytes())
    return destination.as_posix(), str(declared_sha256)


def _artifact_suffix(path: object) -> str:
    suffix = Path(str(path or "")).suffix.lower()
    return suffix if suffix and len(suffix) <= 10 else ".bin"


class FrozenCaptureProducer:
    """Produce one self-contained, signed, and locally revalidated capture."""

    def __init__(
        self,
        *,
        repository_root: Path,
        evidence_root: Path,
        manifest_path: Path,
        config_path: Path,
        workload_path: Path,
        source_dir: Path,
        output_dir: Path,
        executor: CaptureExecutor,
        persistence_runner: PersistenceObservationRunner,
        executor_signer: CaptureSigner,
        api_signer: CaptureSigner,
        commit_sha: str,
        attestation_id: str,
    ):
        self.repository_root = repository_root.resolve()
        self.evidence_root = resolve_evidence_root(evidence_root)
        self.manifest_path = manifest_path
        self.config_path = config_path
        self.workload_path = workload_path
        self.source_dir = source_dir
        self.output_dir = output_dir
        self.executor = executor
        self.persistence_runner = persistence_runner
        self.executor_signer = executor_signer
        self.api_signer = api_signer
        self.commit_sha = commit_sha
        self.attestation_id = attestation_id

    def preflight(self) -> Json:
        plan = build_provider_call_plan(
            self.manifest_path,
            self.config_path,
            self.workload_path,
            repository_root=self.repository_root,
        )
        if plan["unresolved_sequence_count"]:
            raise ValueError("frozen plan contains unresolved assignments")
        if plan["resolved_sequence_count"] != plan[
            "planned_evaluation_sequence_count"
        ]:
            raise ValueError("frozen plan is not fully resolved")
        if plan["executor_trust"]["status"] != "enrolled":
            raise ValueError("frozen plan has no enrolled executor")
        if not _git_sha(self.commit_sha):
            raise ValueError("canonical persistence commit_sha is invalid")
        if not self.attestation_id.strip():
            raise ValueError("canonical persistence attestation_id is empty")

        config = _load_object(self.config_path)
        implementation_errors = validate_frozen_component_pins(
            config,
            self.repository_root,
        )
        if implementation_errors:
            raise ValueError(
                "frozen capture implementation drifted: "
                + "; ".join(implementation_errors)
            )
        executor_key = _load_enrolled_executor_key(config, self.repository_root)
        api_key = _load_enrolled_api_key(config, self.repository_root)
        _challenge_signer(self.executor_signer, executor_key)
        _challenge_signer(self.api_signer, api_key)

        source_dir = confined_path(
            self.evidence_root,
            self.source_dir,
            label="founder source directory",
            kind="directory",
        )
        source_rows: dict[str, tuple[Path, str]] = {}
        for planned in plan["items"]:
            filename = str(planned["source_filename"])
            if Path(filename).name != filename:
                raise ValueError("planned source filename is not a basename")
            source = confined_path(
                self.evidence_root,
                source_dir / filename,
                label=f"founder source {filename}",
                kind="file",
            )
            if file_sha256(source) != planned["source_sha256"]:
                raise ValueError(f"founder source hash differs for {filename}")
            source_rows[filename] = (source, str(planned["source_sha256"]))

        output_dir = confined_output_path(
            self.evidence_root,
            self.output_dir,
            label="capture output directory",
        )
        if output_dir.exists():
            raise ValueError("capture output directory already exists")
        if not output_dir.parent.is_dir():
            raise ValueError("capture output directory parent is unavailable")

        # These hooks are contract validation only. A secured executor must
        # never make provider calls from preflight.
        self.executor.preflight(plan=plan, evidence_root=self.evidence_root)
        declared_calls = self.executor.provider_calls_executed
        if type(declared_calls) is not int or declared_calls < 0:
            raise ValueError("executor provider call count is invalid")
        if declared_calls > int(plan["maximum_provider_attempt_count"]):
            raise ValueError("executor exceeds the frozen provider-call ceiling")
        self.persistence_runner.preflight(plan=plan)
        return {
            "plan": plan,
            "config": config,
            "workload": _load_object(self.workload_path),
            "executor_key": executor_key,
            "api_key": api_key,
            "source_rows": source_rows,
            "output_dir": output_dir,
        }

    def produce(self) -> Json:
        prepared = self.preflight()
        plan: Json = prepared["plan"]
        config: Json = prepared["config"]
        workload: Json = prepared["workload"]
        executor_key: EnrolledKey = prepared["executor_key"]
        api_key: EnrolledKey = prepared["api_key"]
        source_rows: dict[str, tuple[Path, str]] = prepared["source_rows"]
        output_dir: Path = prepared["output_dir"]

        staging_dir = Path(tempfile.mkdtemp(
            prefix=f".{output_dir.name}.staging-",
            dir=output_dir.parent,
        )).resolve()
        attempts: list[Json] = []
        selected_result_set: list[Json] = []
        artifact_rows: list[tuple[str, str, str]] = []
        artifact_destinations: set[str] = set()
        try:
            for filename, (source, source_hash) in sorted(source_rows.items()):
                relative = Path("sources") / filename
                if relative.as_posix() in artifact_destinations:
                    raise ValueError("capture source artifact path collides")
                artifact_destinations.add(relative.as_posix())
                destination = staging_dir / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(source.read_bytes())
                artifact_rows.append((relative.as_posix(), source_hash, "source-image"))

            execution_items = [
                row
                for row in plan["items"]
                if row["resolved_inputs"].get("execution_ready") is True
            ]
            for planned in execution_items:
                raw_attempts = self.executor.execute(planned)
                if not isinstance(raw_attempts, list) or any(
                    not isinstance(row, dict) for row in raw_attempts
                ):
                    raise ValueError("executor returned invalid attempts")
                errors = _attempt_errors(raw_attempts, planned)
                if errors:
                    raise ValueError("; ".join(errors))
                key_stem = str(planned["candidate_artifact_stem"])
                sequence_attempts: list[Json] = []
                for index, raw in enumerate(raw_attempts, 1):
                    if raw.get("attempt_outcome") == "provider_failed":
                        failed_row: Json = {
                            "kind": planned["kind"],
                            "evaluation_id": planned["evaluation_id"],
                            "operation_class": planned["operation_class"],
                            "source_filename": planned["source_filename"],
                            "source_sha256": planned["source_sha256"],
                            "source_image": (
                                Path("sources")
                                / str(planned["source_filename"])
                            ).as_posix(),
                            "source_image_sha256": planned["source_sha256"],
                            "resolved_inputs_sha256": planned[
                                "resolved_inputs_sha256"
                            ],
                            "attempt": index,
                            "accepted": False,
                            "candidate_image": None,
                            "candidate_image_sha256": None,
                            "mask_image": None,
                            "mask_image_sha256": None,
                        }
                        failed_row.update({
                            field: raw[field]
                            for field in (
                                *ATTEMPT_ROUTING_FIELDS,
                                *ATTEMPT_OUTCOME_FIELDS,
                            )
                        })
                        sequence_attempts.append(failed_row)
                        continue
                    candidate_relative = Path("artifacts") / (
                        f"{key_stem}--attempt-{index}"
                        + _artifact_suffix(raw.get("candidate_image"))
                    )
                    if candidate_relative.as_posix() in artifact_destinations:
                        raise ValueError("capture candidate artifact path collides")
                    artifact_destinations.add(candidate_relative.as_posix())
                    candidate_path, candidate_hash = _copy_verified_artifact(
                        evidence_root=self.evidence_root,
                        staging_dir=staging_dir,
                        declared_path=raw.get("candidate_image"),
                        declared_sha256=raw.get("candidate_image_sha256"),
                        destination=candidate_relative,
                        label=(
                            f"{planned['kind']}:{planned['evaluation_id']}:"
                            f"{planned['source_filename']} attempt {index} candidate"
                        ),
                    )
                    artifact_rows.append((
                        candidate_path,
                        candidate_hash,
                        "candidate-image",
                    ))
                    row: Json = {
                        "kind": planned["kind"],
                        "evaluation_id": planned["evaluation_id"],
                        "operation_class": planned["operation_class"],
                        "source_filename": planned["source_filename"],
                        "source_sha256": planned["source_sha256"],
                        "source_image": (
                            Path("sources") / str(planned["source_filename"])
                        ).as_posix(),
                        "source_image_sha256": planned["source_sha256"],
                        "resolved_inputs_sha256": planned["resolved_inputs_sha256"],
                        "attempt": index,
                        "candidate_image": candidate_path,
                        "candidate_image_sha256": candidate_hash,
                        "mask_image": None,
                        "mask_image_sha256": None,
                        "evaluator_report": None,
                        "evaluator_report_sha256": None,
                    }
                    if planned["kind"] == "edit":
                        mask_relative = Path("artifacts") / (
                            f"{planned['mask_artifact_stem']}--attempt-{index}"
                            + _artifact_suffix(raw.get("mask_image"))
                        )
                        if mask_relative.as_posix() in artifact_destinations:
                            raise ValueError("capture mask artifact path collides")
                        artifact_destinations.add(mask_relative.as_posix())
                        mask_path, mask_hash = _copy_verified_artifact(
                            evidence_root=self.evidence_root,
                            staging_dir=staging_dir,
                            declared_path=raw.get("mask_image"),
                            declared_sha256=raw.get("mask_image_sha256"),
                            destination=mask_relative,
                            label=(
                                f"edit:{planned['evaluation_id']}:"
                                f"{planned['source_filename']} attempt {index} mask"
                            ),
                        )
                        artifact_rows.append((mask_path, mask_hash, "edit-mask"))
                        row.update(
                            mask_image=mask_path,
                            mask_image_sha256=mask_hash,
                        )

                    report_relative = Path("artifacts") / (
                        f"{planned['evaluator_report_artifact_stem']}"
                        f"--attempt-{index}.json"
                    )
                    if report_relative.as_posix() in artifact_destinations:
                        raise ValueError("capture evaluator report path collides")
                    artifact_destinations.add(report_relative.as_posix())
                    report_path, report_hash = _copy_verified_artifact(
                        evidence_root=self.evidence_root,
                        staging_dir=staging_dir,
                        declared_path=raw.get("evaluator_report"),
                        declared_sha256=raw.get("evaluator_report_sha256"),
                        destination=report_relative,
                        label=(
                            f"{planned['kind']}:{planned['evaluation_id']}:"
                            f"{planned['source_filename']} attempt {index} "
                            "evaluator report"
                        ),
                    )
                    row.update(
                        evaluator_report=report_path,
                        evaluator_report_sha256=report_hash,
                    )
                    artifact_rows.append((
                        report_path,
                        report_hash,
                        "evaluator-report",
                    ))
                    report = _load_object(staging_dir / report_path)
                    derived = validate_and_replay_evaluator_report(
                        report,
                        planned,
                        row,
                    )
                    projection_fields = (
                        (
                            "accepted",
                            *ATTEMPT_OUTCOME_FIELDS,
                            "render_conformance_score",
                            "hard_gate_pass",
                        )
                        if planned["kind"] == "render"
                        else (
                            "accepted",
                            *ATTEMPT_OUTCOME_FIELDS,
                            "edit_fidelity_score",
                            "severity",
                            "change_applied",
                        )
                    )
                    supplied_projection = {
                        field: raw.get(field) for field in projection_fields
                    }
                    replayed_projection = {
                        field: derived.get(field) for field in projection_fields
                    }
                    if supplied_projection != replayed_projection:
                        raise ValueError(
                            f"{planned['kind']}:{planned['evaluation_id']}:"
                            f"{planned['source_filename']} attempt {index} "
                            "executor projection differs from evaluator replay"
                        )
                    row.update({
                        field: raw[field] for field in ATTEMPT_ROUTING_FIELDS
                    })
                    row.update(replayed_projection)
                    sequence_attempts.append(row)
                attempts.extend(sequence_attempts)
                selected = sequence_attempts[-1]
                selected_result_set.append({
                    "kind": planned["kind"],
                    "evaluation_id": planned["evaluation_id"],
                    "source_filename": planned["source_filename"],
                    "selected_attempt": selected["attempt"],
                    "candidate_image_sha256": selected["candidate_image_sha256"],
                })

            completed_calls = self.executor.provider_calls_executed
            if type(completed_calls) is not int or completed_calls < 0:
                raise ValueError("executor provider call count is invalid after execution")
            if completed_calls > int(plan["maximum_provider_attempt_count"]):
                raise ValueError(
                    "executor exceeded the frozen provider-call ceiling during execution"
                )
            selected_result_set = canonical_result_set(selected_result_set)
            observed = self.persistence_runner.observe(
                selected_result_set=selected_result_set,
            )
            checks = observed.get("checks") if isinstance(observed, dict) else None
            if not isinstance(checks, dict):
                raise ValueError("canonical persistence runner returned no checks")
            attestation: Json = {
                "schema_version": ATTESTATION_SCHEMA,
                "canonical_api_schema_version": CANONICAL_API_SCHEMA,
                "attestation_id": self.attestation_id,
                "corpus_run_id": plan["corpus_run_id"],
                "commit_sha": self.commit_sha,
                "config_id": config.get("config_id"),
                "config_sha256": plan["config_sha256"],
                "workload_id": workload.get("workload_id"),
                "workload_sha256": plan["workload_sha256"],
                "corpus_id": workload.get("corpus_id"),
                "result_set_schema_version": RESULT_SET_SCHEMA,
                "result_set": selected_result_set,
                "result_set_sha256": result_set_sha256(selected_result_set),
                "result_count": len(selected_result_set),
                "checks": checks,
            }
            attestation["signature"] = {
                "algorithm": "Ed25519",
                "key_id": api_key.key_id,
                "value": base64.b64encode(
                    self.api_signer.sign(canonical_attestation_payload(attestation))
                ).decode("ascii"),
            }
            verification = verify_persistence_attestation(
                attestation,
                config=config,
                repository_root=self.repository_root,
                config_sha256=plan["config_sha256"],
                workload_sha256=plan["workload_sha256"],
                workload_id=str(workload.get("workload_id") or ""),
                corpus_id=str(workload.get("corpus_id") or ""),
                expected_corpus_run_id=str(plan["corpus_run_id"]),
                expected_result_set=selected_result_set,
            )
            if verification["status"] != "pass":
                raise ValueError(
                    "canonical persistence attestation failed local verification: "
                    + "; ".join(verification["errors"])
                )
            persistence_relative = Path("persistence-attestation.json")
            if persistence_relative.as_posix() in artifact_destinations:
                raise ValueError("capture persistence artifact path collides")
            artifact_destinations.add(persistence_relative.as_posix())
            persistence_path = staging_dir / persistence_relative
            _write_json(persistence_path, attestation)
            persistence_hash = file_sha256(persistence_path)
            artifact_rows.append((
                persistence_relative.as_posix(),
                persistence_hash,
                "canonical-persistence-attestation",
            ))

            artifact_index = build_artifact_index(artifact_rows)
            artifact_errors = validate_artifact_index(artifact_index, staging_dir)
            if artifact_errors:
                raise ValueError(
                    "capture artifact index failed local verification: "
                    + "; ".join(artifact_errors)
                )
            capture: Json = {
                "schema_version": CAPTURE_SCHEMA,
                "corpus_run_id": plan["corpus_run_id"],
                "manifest_sha256": plan["manifest_sha256"],
                "config_sha256": plan["config_sha256"],
                "workload_sha256": plan["workload_sha256"],
                "assignment_bundle_sha256": plan["assignment_bundle"].get(
                    "bundle_sha256"
                ),
                "not_applicable_assignments": not_applicable_assignment_rows(
                    plan
                ),
                "provider_calls_executed": completed_calls,
                "attempts": attempts,
                "persistence_evidence_ref": {
                    "relative_path": persistence_relative.as_posix(),
                    "sha256": persistence_hash,
                },
                "artifact_index": artifact_index,
            }
            capture["signature"] = {
                "algorithm": "Ed25519",
                "key_id": executor_key.key_id,
                "public_key_sha256": executor_key.file_sha256,
                "value": base64.b64encode(
                    self.executor_signer.sign(canonical_capture_payload(capture))
                ).decode("ascii"),
            }
            capture_path = staging_dir / "capture.json"
            _write_json(capture_path, capture)
            validation = validate_capture_envelope(
                capture_path,
                self.manifest_path,
                self.config_path,
                self.workload_path,
                capture_public_key_path=executor_key.path,
                capture_key_id=executor_key.key_id,
                repository_root=self.repository_root,
            )
            if validation["status"] != "pass":
                raise ValueError(
                    "produced capture failed local verification: "
                    + "; ".join(validation["errors"])
                )
            staging_dir.replace(output_dir)
            final_capture = output_dir / "capture.json"
            return {
                "schema_version": PRODUCTION_SUMMARY_SCHEMA,
                "status": "pass",
                "provider_calls_executed": completed_calls,
                "corpus_run_id": plan["corpus_run_id"],
                "capture_path": final_capture.as_posix(),
                "capture_sha256": file_sha256(final_capture),
                "persistence_attestation_path": (
                    output_dir / persistence_relative
                ).as_posix(),
                "persistence_attestation_sha256": persistence_hash,
                "logical_evaluation_sequence_count": len(plan["items"]),
                "captured_evaluation_sequence_count": len(execution_items),
                "not_applicable_evaluation_sequence_count": len(
                    not_applicable_assignment_rows(plan)
                ),
                "captured_attempt_count": len(attempts),
                "signature_status": validation["signature_status"],
                "corpus_gate_ready": False,
            }
        except Exception:
            shutil.rmtree(staging_dir, ignore_errors=True)
            raise

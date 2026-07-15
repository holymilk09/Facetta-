#!/usr/bin/env python3
"""Create, validate, and sign provider-free frozen assignment workbooks."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from facetta.frozen_assignment_authoring import (  # noqa: E402
    build_assignment_authoring_template,
    finalize_signed_assignment_bundle,
    validate_completed_assignment_template,
)
from facetta.frozen_assignment_contract import (  # noqa: E402
    load_enrolled_assignment_reviewer,
    verify_signed_assignment_bundle,
)
from facetta.frozen_evidence_paths import (  # noqa: E402
    confined_output_path,
    confined_path,
    evidence_root,
    require_new_artifact_paths,
    retained_cli_entrypoint,
    write_new_artifacts,
    write_new_text_artifact,
)


Json = dict[str, Any]
DEFAULT_DIR = ROOT / "docs" / "evals" / "frozen-founder-corpus-v1"


def _object(path: Path, *, label: str) -> Json:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _render(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _expected_sha256(value: str, *, label: str) -> str:
    if (
        len(value) != 64
        or value.lower() != value
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{label} must be 64 lowercase hexadecimal characters")
    return value


def _verified_input_bytes(
    path: Path,
    expected_sha256: str,
    *,
    label: str,
) -> bytes:
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symbolic link")
    resolved = path.resolve()
    if not resolved.is_file():
        raise ValueError(f"{label} is unavailable")
    value = resolved.read_bytes()
    actual = hashlib.sha256(value).hexdigest()
    if actual != _expected_sha256(expected_sha256, label=f"{label} SHA-256"):
        raise ValueError(f"{label} SHA-256 differs")
    return value


def _canonical_object_bytes(value: bytes, *, label: str) -> tuple[Json, bytes]:
    try:
        parsed = json.loads(value.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must be one UTF-8 JSON object") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{label} must be a JSON object")
    return parsed, _render(parsed).encode("utf-8")


def _repository_install_path(config_path: Path, value: Path) -> Path:
    root = ROOT.resolve()
    config = config_path.resolve()
    if not config.is_file() or not config.is_relative_to(root):
        raise ValueError("frozen config must be a repository-confined file")
    if value.is_absolute():
        raise ValueError("installed assignment bundle path must be repository-relative")
    output = (root / value).resolve(strict=False)
    canonical_root = (config.parent / "assignment-bundles").resolve(strict=False)
    if output.parent != canonical_root or output.suffix != ".json":
        raise ValueError(
            "installed assignment bundle must be a JSON file directly inside "
            "the config-adjacent assignment-bundles directory"
        )
    return output


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_DIR / "manifest.json")
    parser.add_argument("--config", type=Path, default=DEFAULT_DIR / "config.json")
    parser.add_argument("--workload", type=Path, default=DEFAULT_DIR / "workload.json")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Author a signed, evidence-backed frozen assignment bundle without "
            "image-provider calls."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    template = commands.add_parser("template")
    _common(template)
    template.add_argument("--corpus-run-id", required=True)
    template.add_argument("--out", type=Path, required=True)

    submit = commands.add_parser("submit")
    _common(submit)
    submit.add_argument("--completed-input", type=Path, required=True)
    submit.add_argument("--expected-sha256", required=True)
    submit.add_argument("--out", type=Path, required=True)

    validate = commands.add_parser("validate")
    _common(validate)
    validate.add_argument("--source-dir", type=Path, required=True)
    validate.add_argument("--template", type=Path, required=True)
    validate.add_argument("--out", type=Path, required=True)

    finalize = commands.add_parser("finalize")
    _common(finalize)
    finalize.add_argument("--source-dir", type=Path, required=True)
    finalize.add_argument("--template", type=Path, required=True)
    finalize.add_argument("--private-key", type=Path, required=True)
    finalize.add_argument("--decision-time", required=True)
    finalize.add_argument("--bundle-out", type=Path, required=True)
    finalize.add_argument("--validation-out", type=Path, required=True)
    finalize.add_argument("--pin-out", type=Path, required=True)

    install = commands.add_parser("install")
    _common(install)
    install.add_argument("--bundle", type=Path, required=True)
    install.add_argument("--expected-sha256", required=True)
    install.add_argument("--out", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    retained_root = evidence_root(args.evidence_root)
    config = _object(args.config, label="frozen config")
    reviewer = load_enrolled_assignment_reviewer(config, repository_root=ROOT)
    if args.command == "template":
        output = confined_output_path(retained_root, args.out, label="assignment template")
        require_new_artifact_paths([output], root=retained_root)
        result = build_assignment_authoring_template(
            args.manifest,
            args.config,
            args.workload,
            corpus_run_id=args.corpus_run_id,
            reviewer=reviewer,
            repository_root=ROOT,
        )
        write_new_text_artifact(output, _render(result), root=retained_root)
        summary = {
            "status": "awaiting_human_review",
            "provider_calls": 0,
            "source_count": len(result["review"]["sources"]),
            "assignment_count": sum(
                len(source["evaluations"])
                for source in result["review"]["sources"]
            ),
            "artifact": output.relative_to(retained_root).as_posix(),
            "corpus_gate_ready": False,
        }
    elif args.command == "submit":
        working_path = args.completed_input.resolve()
        if working_path.is_relative_to(retained_root):
            raise ValueError(
                "completed workbook input must remain outside the retained evidence root"
            )
        working_bytes = _verified_input_bytes(
            args.completed_input,
            args.expected_sha256,
            label="completed workbook input",
        )
        _completed, canonical_bytes = _canonical_object_bytes(
            working_bytes,
            label="completed workbook input",
        )
        output = confined_output_path(
            retained_root,
            args.out,
            label="submitted assignment workbook",
        )
        require_new_artifact_paths([output], root=retained_root)
        write_new_artifacts({output: canonical_bytes}, root=retained_root)
        summary = {
            "status": "submitted_for_validation",
            "provider_calls": 0,
            "working_file_sha256": hashlib.sha256(working_bytes).hexdigest(),
            "submitted_file_sha256": hashlib.sha256(canonical_bytes).hexdigest(),
            "artifact": output.relative_to(retained_root).as_posix(),
            "corpus_gate_ready": False,
        }
    elif args.command == "install":
        source = confined_path(
            retained_root,
            args.bundle,
            label="signed assignment bundle",
            kind="file",
            require_relative=True,
        )
        source_bytes = _verified_input_bytes(
            source,
            args.expected_sha256,
            label="signed assignment bundle",
        )
        bundle, canonical_bytes = _canonical_object_bytes(
            source_bytes,
            label="signed assignment bundle",
        )
        if source_bytes != canonical_bytes:
            raise ValueError("signed assignment bundle is not canonical JSON")
        output = _repository_install_path(args.config, args.out)
        verify_signed_assignment_bundle(bundle, config, repository_root=ROOT)
        require_new_artifact_paths([output], root=ROOT.resolve())
        write_new_artifacts({output: source_bytes}, root=ROOT.resolve())
        installed_artifact = output.relative_to(ROOT.resolve()).as_posix()
        installed_sha256 = hashlib.sha256(source_bytes).hexdigest()
        summary = {
            "status": "installed_for_config_review",
            "provider_calls": 0,
            "installed_artifact": installed_artifact,
            "installed_file_sha256": installed_sha256,
            "resolved_assignment_bundle_pin": (
                f"{installed_artifact}@sha256:{installed_sha256}"
            ),
            "installation_status": "config_update_required",
            "corpus_gate_ready": False,
        }
    else:
        template_path = confined_path(
            retained_root,
            args.template,
            label="completed assignment template",
            kind="file",
        )
        completed = _object(template_path, label="completed assignment template")
        compilation = validate_completed_assignment_template(
            args.manifest,
            args.config,
            args.workload,
            completed,
            reviewer=reviewer,
            evidence_root=retained_root,
            source_dir=args.source_dir,
            repository_root=ROOT,
        )
        if args.command == "validate":
            output = confined_output_path(
                retained_root,
                args.out,
                label="assignment validation",
            )
            require_new_artifact_paths([output], root=retained_root)
            write_new_text_artifact(
                output,
                _render(compilation.validation),
                root=retained_root,
            )
            summary = {
                **compilation.validation,
                "artifact": output.relative_to(retained_root).as_posix(),
            }
        else:
            try:
                decision_time = datetime.fromisoformat(
                    args.decision_time.replace("Z", "+00:00")
                )
            except ValueError as exc:
                raise ValueError("decision-time must be ISO-8601") from exc
            if decision_time.tzinfo is None or decision_time.utcoffset() is None:
                raise ValueError("decision-time must include a timezone offset")
            outputs = {
                "bundle": confined_output_path(
                    retained_root,
                    args.bundle_out,
                    label="signed assignment bundle",
                ),
                "validation": confined_output_path(
                    retained_root,
                    args.validation_out,
                    label="final assignment validation",
                ),
                "pin": confined_output_path(
                    retained_root,
                    args.pin_out,
                    label="assignment pin proposal",
                ),
            }
            require_new_artifact_paths(list(outputs.values()), root=retained_root)
            bundle, validation, pin = finalize_signed_assignment_bundle(
                compilation,
                config,
                reviewer=reviewer,
                private_key_path=args.private_key,
                decision_time=decision_time,
                repository_root=ROOT,
                evidence_root=retained_root,
            )
            rendered_bundle = _render(bundle).encode("utf-8")
            pin["source_artifact"] = outputs["bundle"].relative_to(
                retained_root
            ).as_posix()
            pin["source_file_sha256"] = hashlib.sha256(
                rendered_bundle
            ).hexdigest()
            pin["reviewed_template_artifact"] = template_path.relative_to(
                retained_root
            ).as_posix()
            pin["reviewed_template_file_sha256"] = hashlib.sha256(
                template_path.read_bytes()
            ).hexdigest()
            write_new_artifacts(
                {
                    outputs["bundle"]: rendered_bundle,
                    outputs["validation"]: _render(validation).encode("utf-8"),
                    outputs["pin"]: _render(pin).encode("utf-8"),
                },
                root=retained_root,
            )
            summary = {
                "status": "signed_and_verified",
                "provider_calls": 0,
                "assignment_count": validation["assignment_count"],
                "execute_count": validation["execute_count"],
                "not_applicable_count": validation["not_applicable_count"],
                "artifacts": {
                    key: value.relative_to(retained_root).as_posix()
                    for key, value in outputs.items()
                },
                "installation_status": "review_required",
                "corpus_gate_ready": False,
            }
    print(_render(summary), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(retained_cli_entrypoint(main))

"""Verify the founder's decision against one exact frozen-corpus result."""

from __future__ import annotations

import base64
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from facetta.frozen_corpus_gate import file_sha256


Json = dict[str, Any]


def canonical_founder_approval_payload(approval: Json) -> bytes:
    unsigned = {key: value for key, value in approval.items() if key != "signature"}
    return json.dumps(
        unsigned, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")


def _load_object(path: Path) -> Json:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _public_key(config: Json, repository_root: Path) -> tuple[Ed25519PublicKey | None, str | None, str | None]:
    configured = config.get("founder_public_key")
    if not isinstance(configured, dict):
        return None, None, "founder public key is not configured"
    key_id = configured.get("key_id")
    relative = configured.get("path")
    if not isinstance(key_id, str) or not key_id.strip() or not isinstance(relative, str):
        return None, None, "founder public-key configuration is incomplete"
    root = repository_root.resolve()
    path = (root / relative).resolve()
    if (
        Path(relative).is_absolute()
        or not path.is_relative_to(root)
        or not path.is_file()
        or file_sha256(path) != configured.get("sha256")
    ):
        return None, key_id, "founder public-key file failed its configured hash"
    try:
        content = path.read_bytes()
        if len(content) == 32:
            return Ed25519PublicKey.from_public_bytes(content), key_id, None
        key = load_pem_public_key(content)
        if not isinstance(key, Ed25519PublicKey):
            return None, key_id, "configured founder key is not Ed25519"
        return key, key_id, None
    except (TypeError, ValueError) as exc:
        return None, key_id, f"founder public key is invalid: {exc}"


def verify_frozen_corpus_release(
    results_path: Path,
    config_path: Path,
    approval_path: Path,
    *,
    repository_root: Path | None = None,
) -> Json:
    results = _load_object(results_path)
    config = _load_object(config_path)
    approval = _load_object(approval_path)
    errors: list[str] = []
    results_hash = file_sha256(results_path)
    if results.get("status") != "pass" or results.get("release_ready") is not True:
        errors.append("frozen-corpus technical/GIA result is not release-ready")
    if approval.get("schema_version") != "facetta-founder-approval.v1":
        errors.append("unsupported founder approval schema_version")
    if approval.get("results_sha256") != results_hash:
        errors.append("founder approval does not bind the exact results bytes")
    if approval.get("decision") != "approved":
        errors.append("founder decision is not approved")
    for field in ("founder", "approved_at", "release_ticket"):
        value = approval.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"founder approval {field} is missing")
    approved_at = approval.get("approved_at")
    if isinstance(approved_at, str):
        try:
            parsed = datetime.fromisoformat(approved_at.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError
        except ValueError:
            errors.append("founder approval approved_at must include a timezone")

    root = repository_root or Path(__file__).resolve().parents[2]
    public_key, key_id, key_error = _public_key(config, root)
    signature = approval.get("signature")
    signature_status = "not_verified"
    if key_error:
        errors.append(key_error)
    elif not isinstance(signature, dict):
        errors.append("founder approval is unsigned")
    elif (
        signature.get("algorithm") != "Ed25519"
        or signature.get("key_id") != key_id
        or not isinstance(signature.get("value"), str)
    ):
        errors.append("founder approval signature metadata is invalid")
    else:
        try:
            assert public_key is not None
            public_key.verify(
                base64.b64decode(signature["value"], validate=True),
                canonical_founder_approval_payload(approval),
            )
            signature_status = "verified"
        except (InvalidSignature, ValueError, TypeError):
            errors.append("founder approval signature is invalid")

    passed = not errors and signature_status == "verified"
    return {
        "schema_version": "facetta-frozen-corpus-release-decision.v1",
        "status": "pass" if passed else "incomplete_or_failed",
        "external_beta_ready": passed,
        "provider_calls": 0,
        "results_sha256": results_hash,
        "approval_sha256": file_sha256(approval_path),
        "founder_signature": {"status": signature_status, "key_id": key_id},
        "errors": errors,
    }

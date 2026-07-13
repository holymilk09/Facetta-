"""Production composition for the attested ring structural mapper.

Activation is explicit and fail-closed.  A provider key or callable alone is
not a release: operators must pin an external calibration artifact by path and
SHA-256 and may enable only paths implemented by this exact mapper contract.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from facetta.catalog_component_targeting import (
    CatalogStructuralMapperStatus,
    catalog_structural_component_mapper_status,
    configure_catalog_structural_component_mapper,
)
from facetta.catalog_structural_mapper import (
    GROK_RING_COMPONENT_MAPPER_CONTRACT,
    GROK_RING_COMPONENT_MAPPER_PATHS,
    GrokRingComponentMapper,
)
from facetta.config import env_value


_ENABLED = "FACETTA_RING_STRUCTURAL_MAPPER_ENABLED"
_EVIDENCE_PATH = "FACETTA_RING_STRUCTURAL_MAPPER_EVIDENCE_PATH"
_EVIDENCE_SHA256 = "FACETTA_RING_STRUCTURAL_MAPPER_EVIDENCE_SHA256"
_SUPPORTED_PATHS = "FACETTA_RING_STRUCTURAL_MAPPER_SUPPORTED_PATHS"


def _flag(name: str) -> bool:
    value = env_value(name)
    if value is None or not value.strip():
        return False
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be an explicit boolean")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ValueError(
            "the structural mapper calibration evidence is unreadable"
        ) from exc
    return digest.hexdigest()


def configure_attested_catalog_structural_mapper_from_environment(
) -> CatalogStructuralMapperStatus:
    """Compose the known mapper only when every release attestation matches."""
    if not _flag(_ENABLED):
        configure_catalog_structural_component_mapper(None)
        return catalog_structural_component_mapper_status()

    raw_path = env_value(_EVIDENCE_PATH)
    expected_digest = env_value(_EVIDENCE_SHA256)
    raw_supported = env_value(_SUPPORTED_PATHS)
    if not raw_path or not expected_digest or not raw_supported:
        raise ValueError(
            "enabled structural mapping requires evidence path, SHA-256, "
            "and supported paths"
        )
    evidence_path = Path(raw_path).expanduser()
    if not evidence_path.is_file():
        raise ValueError(
            "the structural mapper calibration evidence must be a file"
        )
    observed_digest = _file_sha256(evidence_path)
    if observed_digest != expected_digest:
        raise ValueError(
            "the structural mapper calibration evidence SHA-256 does not match"
        )
    supported_paths = frozenset(
        item.strip() for item in raw_supported.split(",") if item.strip()
    )
    if not supported_paths or not supported_paths.issubset(
        GROK_RING_COMPONENT_MAPPER_PATHS
    ):
        raise ValueError(
            "the configured paths exceed this structural mapper release"
        )

    mapper = GrokRingComponentMapper()

    def readiness_probe() -> bool:
        # Re-verify the mounted release evidence on every capability read and
        # acceptance boundary. Revoking, replacing, or deleting the artifact
        # therefore makes the mapper unhealthy without a process restart.
        return (
            bool(env_value("XAI_KEY"))
            and _file_sha256(evidence_path) == observed_digest
        )

    configure_catalog_structural_component_mapper(
        mapper,
        mapper_contract=GROK_RING_COMPONENT_MAPPER_CONTRACT,
        calibration_evidence_sha256=observed_digest,
        supported_paths=supported_paths,
        # A health read must not perform a billable or latency-heavy provider
        # request. It verifies only credential presence and the small mounted
        # evidence artifact; mapping calls still fail closed on provider errors.
        readiness_probe=readiness_probe,
    )
    return catalog_structural_component_mapper_status()

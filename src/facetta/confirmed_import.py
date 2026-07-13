"""Canonical designer-confirmed reference import application service.

The Studio route and the deprecated project-route compatibility adapter share
this service.  It validates before writing and delegates the only transaction
to :func:`persist_project_v1`, so a rejected import cannot leave partial design
history behind.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.orm import Session

from facetta.image_identity import spec_visual_hash
from facetta.project_backbone import (
    DesignAlreadyLinked,
    PersistedProjectInput,
    PersistedProjectResult,
    persist_project_v1,
)
from facetta.source_component_coverage import source_component_factory_blockers
from facetta.source_component_resolution import valid_source_component_spec_paths
from facetta.spec import Spec
from facetta.validation import validate_spec
from facetta.vocabulary import get_vocabulary


ConfirmedImportMediaType = Literal[
    "image/png", "image/jpeg", "image/webp",
]
ConfirmedImportSourceAuditPolicy = Literal["exact", "legacy_compatible"]


@dataclass(frozen=True)
class ConfirmedImportCommand:
    image_base64: str
    media_type: ConfirmedImportMediaType | None
    spec: Spec
    actor: str
    title: str
    collection: str | None = None
    tags: tuple[str, ...] = ()
    source_audit_policy: ConfirmedImportSourceAuditPolicy = "exact"


class ConfirmedImportRejected(Exception):
    """HTTP-neutral rejection retaining the existing API error contract."""

    def __init__(self, status_code: int, content: dict[str, Any]):
        super().__init__(str(content.get("detail", "confirmed import rejected")))
        self.status_code = status_code
        self.content = content


def _reject(status_code: int, **content: Any) -> ConfirmedImportRejected:
    return ConfirmedImportRejected(status_code, content)


def _uploaded_media_type(image: bytes) -> ConfirmedImportMediaType | None:
    if image[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if image[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if image[:4] == b"RIFF" and image[8:12] == b"WEBP":
        return "image/webp"
    return None


def _validated_confirmed_spec(spec: Spec) -> Spec:
    if spec.jewelry_type == "ring":
        pass
    elif spec.jewelry_type != "necklace":
        raise _reject(
            422,
            error_category="validation_failure",
            detail=(
                "designer-confirmed project import currently supports rings "
                "and pendant necklaces only"
            ),
        )
    elif spec.template != "cluster_pendant" or spec.chain is None:
        raise _reject(
            422,
            error_category="validation_failure",
            detail=(
                "a trusted necklace import requires template "
                "'cluster_pendant' and an explicit carrier-chain section"
            ),
        )

    result = validate_spec(spec, get_vocabulary())
    if not result.ok:
        raise _reject(
            422,
            error_category="validation_failure",
            detail=[issue.as_detail() for issue in result.issues],
        )
    return result.spec


def _validate_source_coverage(
    spec: Spec,
    source_image: bytes,
    *,
    policy: ConfirmedImportSourceAuditPolicy,
) -> None:
    coverage = spec.source_component_coverage
    if coverage is None:
        raise _reject(
            422,
            error_category="validation_failure",
            code="source_component_coverage_required",
            detail=(
                "a new image import requires server-reviewed source-component "
                "coverage; extract the source, resolve every visible component, "
                "and complete the independent audit before project creation"
            ),
        )

    source_sha256 = hashlib.sha256(source_image).hexdigest()
    if policy == "exact":
        if coverage.audited_source_sha256 is None:
            raise _reject(
                422,
                error_category="validation_failure",
                code="source_component_source_audit_required",
                detail=(
                    "the confirmed source-component audit must name the exact "
                    "uploaded source SHA-256 before Studio project creation"
                ),
            )
        if coverage.audited_source_sha256 != source_sha256:
            raise _reject(
                409,
                error_category="validation_failure",
                code="source_component_source_audit_stale",
                detail=(
                    "the confirmed source-component audit belongs to different "
                    "source bytes; repeat the audit for this exact upload"
                ),
            )

    blockers = source_component_factory_blockers(
        coverage,
        valid_spec_paths=valid_source_component_spec_paths(spec),
        current_spec_visual_hash=spec_visual_hash(spec),
        current_source_hash=source_sha256,
    )
    if blockers:
        raise _reject(
            409,
            error_category="validation_failure",
            code="source_component_coverage_incomplete",
            detail=(
                "every visible source component must map to the exact confirmed "
                "specification and pass independent audit before project creation"
            ),
            factory_blockers=[
                blocker.model_dump(mode="json") for blocker in blockers
            ],
        )


def import_confirmed_project(
    db: Session,
    command: ConfirmedImportCommand,
) -> PersistedProjectResult:
    """Validate and atomically persist one exact confirmed reference."""
    try:
        image = base64.b64decode(command.image_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise _reject(
            422,
            error_category="validation_failure",
            detail="image_base64 is not valid base64",
        ) from exc

    detected = _uploaded_media_type(image)
    if detected is None:
        raise _reject(
            422,
            error_category="validation_failure",
            detail="upload must be a PNG, JPEG, or WebP image",
        )
    if command.media_type is not None and command.media_type != detected:
        raise _reject(
            422,
            error_category="validation_failure",
            detail=(
                f"media_type says {command.media_type}, but the upload is {detected}"
            ),
        )

    spec = _validated_confirmed_spec(command.spec)
    _validate_source_coverage(
        spec,
        image,
        policy=command.source_audit_policy,
    )
    try:
        return persist_project_v1(
            db,
            PersistedProjectInput(
                spec=spec,
                primary_image=image,
                primary_capability="IMPORTED_REFERENCE",
                primary_instruction="Designer-confirmed imported reference",
                primary_media_type=detected,
            ),
            owner=command.actor,
            title=command.title,
            collection=command.collection,
            tags=list(command.tags),
        )
    except DesignAlreadyLinked as exc:
        raise _reject(
            409,
            error_category="design_already_linked",
            detail=str(exc),
            existing_root_id=exc.root_id,
        ) from exc

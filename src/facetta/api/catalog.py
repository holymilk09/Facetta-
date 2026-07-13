"""Persisted, catalog-directed revisions for trusted ring/necklace projects."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from facetta.api.error_mapping import image_agent_error_response
from facetta.api.projects import ProjectDetail, project_chain, project_detail
from facetta.auth import (
    AuthenticatedPrincipal,
    principal_actor,
    require_asset_project_boundary,
    require_image_run_boundary,
    require_principal_boundary,
)
from facetta.catalog_preview_candidates import (
    CatalogPreviewJobError,
    CatalogPreviewUnavailable,
    discard_catalog_preview_candidate,
    get_catalog_preview_candidate,
    invalidate_catalog_preview_candidate,
    list_catalog_preview_candidates,
    resolve_catalog_preview_candidate,
    settle_catalog_preview_acceptance,
    settle_catalog_preview_refine_job_failure,
    store_catalog_preview_candidate,
    validate_catalog_preview_refine_job,
)
from facetta.catalog_component_targeting import (
    MATERIAL_ONLY_CATALOG_PATHS,
    RING_CATALOG_TARGET_KINDS,
    STRUCTURAL_CATALOG_PATHS,
    catalog_structural_component_mapper_available,
    prepare_catalog_child_component_map,
    prepare_catalog_source_component_map,
)
from facetta.chain_geometry import chain_factory_blockers
from facetta.component_catalog import (
    CatalogSelectionResult,
    CatalogSelectionError,
    ComponentCatalogOption,
    apply_catalog_selection,
    component_catalog_paths,
    get_component_catalog,
    get_component_catalog_descriptor,
)
from facetta.db import DesignVersion, ImageAsset, ImageRun, Project, get_db, new_id
from facetta.dimension_provenance import confirm_designer_dimension_subtree
from facetta.image_agent import (
    ImageAgentError,
    ImageAgentResult,
    ImageOperation,
    JewelryImageAgent,
    build_image_plan,
)
from facetta.image_agent.planning import bind_localization_mask
from facetta.image_run_store import (
    persist_image_agent_failure,
    persist_image_agent_result,
)
from facetta.json_types import JsonObject, JsonValue
from facetta.media import sniff_media_type
from facetta.project_backbone import is_primary_revision
from facetta.revision_component_map import (
    ComponentMapError,
    RevisionComponentMap,
    component_map_hash,
    rasterize_component_masks,
)
from facetta.revision_component_map_store import (
    add_revision_component_map,
    load_revision_component_map,
)
from facetta.spec import ChainGeometry, ChainProduction, Spec
from facetta.studio_history import StudioHistoryError, fork_preview_candidate_variation
from facetta.trusted_revision import (
    TrustedSpecRevisionError,
    WarningRevisionError,
    accept_catalog_preview_revision,
    persist_spec_image_revision,
)
from facetta.validation import validate_spec
from facetta.vocabulary import get_vocabulary
from facetta.warning_candidates import store_markup_warning_candidate

router = APIRouter(
    prefix="/assets",
    tags=["assets"],
    dependencies=[
        Depends(require_principal_boundary),
        Depends(require_asset_project_boundary),
    ],
)
preview_router = APIRouter(
    tags=["assets"],
    dependencies=[
        Depends(require_principal_boundary),
        Depends(require_image_run_boundary),
    ],
)
DbSession = Annotated[Session, Depends(get_db)]
PrincipalDep = Annotated[AuthenticatedPrincipal, Depends(require_principal_boundary)]


class CatalogApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_path: Annotated[str, Field(min_length=1, max_length=80)]
    option_id: Annotated[str, Field(min_length=1, max_length=80)]
    expected_design_version: Annotated[int, Field(ge=1)]
    created_by: Annotated[str, Field(min_length=1, max_length=32)]
    variant: Annotated[int, Field(ge=0, le=100)] = 0
    # A quick center-stone palette is scoped to one species. Supplying this
    # field with component_path=stone.color changes material identity and
    # controlled color together, so the immutable revision never carries a
    # color term from the previous species.
    stone_species: Annotated[str | None, Field(min_length=1, max_length=80)] = None
    # Required only for chain.style. A visual family selection cannot invent
    # its fabrication facts or silently retain a source-style stock record.
    chain_geometry: ChainGeometry | None = None
    chain_production: ChainProduction | None = None


class CatalogPreviewRequest(CatalogApplyRequest):
    """Catalog edit inputs plus the optional durable Studio review ledger."""

    studio_job_id: Annotated[str | None, Field(min_length=1, max_length=32)] = None


class CatalogPreviewAcceptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_design_version: Annotated[int, Field(ge=1)]
    created_by: Annotated[str, Field(min_length=1, max_length=32)]


class CatalogPreviewVariationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created_by: Annotated[str, Field(min_length=1, max_length=32)]
    label: Annotated[str, Field(min_length=1, max_length=120)]


class CatalogSpecChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    before: JsonValue
    after: JsonValue
    label: str


class CatalogWarningCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    candidate_id: str
    preview_url: str
    operation: Literal["LOCAL_EDIT"] = "LOCAL_EDIT"
    requested_change: str


class CatalogPreviewCandidateSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    candidate_id: str
    preview_url: str
    accept_url: str
    discard_url: str
    save_as_variation_url: str
    verdict: Literal["pass", "warn"]
    studio_job_id: str | None = None
    expires_in_seconds: int = 7200


class CatalogPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["preview_ready", "review_required"]
    component_path: str
    option_id: str
    isolation_target: str
    source_asset_id: str
    design_version: int
    image_run_id: str
    spec_change: tuple[CatalogSpecChange, ...]
    next_spec: Spec
    qa: JsonObject
    routing: JsonObject
    project: ProjectDetail
    candidate: CatalogPreviewCandidateSummary


class CatalogPreviewAcceptResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["accepted"] = "accepted"
    asset_id: str
    design_version: int
    image_run_id: str
    spec_change: tuple[CatalogSpecChange, ...]
    project: ProjectDetail


class CatalogApplyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["accepted", "review_required"]
    component_path: str
    option_id: str
    isolation_target: str
    asset_id: str | None = None
    design_version: int
    image_run_id: str
    spec_change: tuple[CatalogSpecChange, ...]
    next_spec: Spec | None = None
    qa: JsonObject
    routing: JsonObject
    project: ProjectDetail
    warning_candidate: CatalogWarningCandidate | None = None


class CatalogPathTargetability(BaseModel):
    """One released catalog path's truthful exact-revision target state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    component_path: str
    status: Literal["ready", "unmapped", "unresolved"]
    required_component_kinds: tuple[str, ...]
    component_ids: tuple[str, ...] = ()
    reason_code: str | None = None


class RevisionComponentMapCapability(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    state: Literal["ready", "unmapped", "unresolved"]
    scope: Literal["ring_v1", "not_released"]
    map_sha256: str | None = None
    mapper_contract: str | None = None
    raster_width: int | None = None
    raster_height: int | None = None


class StudioComponentTargetingResponse(BaseModel):
    """Designer-safe component targeting facts for one immutable raster."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["facetta.studio-component-targeting.v1"] = (
        "facetta.studio-component-targeting.v1"
    )
    asset_id: str
    asset_sha256: str
    jewelry_type: str
    component_map: RevisionComponentMapCapability
    catalog_paths: tuple[CatalogPathTargetability, ...]
    authority: Literal["exact_revision_image_editing_only"] = (
        "exact_revision_image_editing_only"
    )


class CatalogApplyError(RuntimeError):
    def __init__(
        self,
        code: str,
        detail: str,
        *,
        status_code: int = 422,
        category: str = "validation",
        context: JsonObject | None = None,
    ) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status_code = status_code
        self.category = category
        self.context = context or {}


@dataclass(frozen=True)
class _CatalogContext:
    asset: ImageAsset
    project: Project
    design_id: str
    design_version: int
    spec: Spec


@dataclass(frozen=True)
class _PreparedCatalogRevision:
    context: _CatalogContext
    option: ComponentCatalogOption
    selection: CatalogSelectionResult
    instruction: str


@dataclass(frozen=True)
class _CatalogComponentTarget:
    """One exact mapped region authorized for a ring catalog edit."""

    component_map: RevisionComponentMap
    component_ids: tuple[str, ...]
    component_kinds: tuple[str, ...]
    map_sha256: str
    mask_bytes: bytes
    mask_sha256: str


# Component-map v1 is deliberately ring-only.  Each released ring catalog
# path names the complete semantic region it is allowed to alter.  In
# particular, a metal edit is an aggregate of every resolved metal-bearing
# component; an unresolved member cannot be skipped to make the request pass.
def _trusted_image_agent() -> JewelryImageAgent:
    return JewelryImageAgent()


def _error_response(error: CatalogApplyError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content={
            "code": error.code,
            "category": error.category,
            "detail": error.detail,
            **error.context,
        },
    )


def _catalog_context(
    db: Session,
    asset_id: str,
    expected_design_version: int,
) -> _CatalogContext:
    asset = db.get(ImageAsset, asset_id)
    if asset is None:
        raise CatalogApplyError(
            "asset_not_found",
            f"unknown asset {asset_id!r}",
            status_code=404,
        )
    project = db.get(Project, asset.root_id)
    root = db.get(ImageAsset, asset.root_id)
    if project is None or root is None or root.design_id is None:
        raise CatalogApplyError(
            "project_design_unavailable",
            "catalog changes require a persisted, design-linked project",
            status_code=409,
            category="conflict",
        )
    primary = [
        candidate
        for candidate in project_chain(db, project.root_id)
        if is_primary_revision(candidate)
    ]
    active = primary[-1] if primary else None
    if active is None or active.id != asset.id:
        raise CatalogApplyError(
            "stale_asset_revision",
            "catalog changes must start from the active primary visual; reload first",
            status_code=409,
            category="stale_version",
            context={"current_asset_id": active.id if active else None},
        )
    latest = (
        db.execute(
            select(DesignVersion)
            .where(DesignVersion.design_id == root.design_id)
            .order_by(DesignVersion.version.desc())
        )
        .scalars()
        .first()
    )
    if latest is None:
        raise CatalogApplyError(
            "spec_version_unavailable",
            "the linked design has no immutable specification version",
            status_code=404,
        )
    if (
        latest.version != expected_design_version
        or asset.design_version != expected_design_version
    ):
        raise CatalogApplyError(
            "stale_design_version",
            "the image or specification changed while this selection was open; reload first",
            status_code=409,
            category="stale_version",
            context={
                "expected_design_version": expected_design_version,
                "current_design_version": latest.version,
                "asset_design_version": asset.design_version,
            },
        )
    try:
        spec = Spec.model_validate(latest.spec)
    except Exception as exc:
        raise CatalogApplyError(
            "spec_invalid",
            "the active specification cannot be read safely",
        ) from exc
    validated = validate_spec(spec, get_vocabulary())
    if not validated.ok:
        raise CatalogApplyError(
            "spec_invalid",
            "the active specification does not pass validation",
            context={
                "issues": [issue.as_detail() for issue in validated.issues],
            },
        )
    # Validation is a gate, never a catalog author. Preserve the exact stored
    # spec as the sole input to the deterministic selection compiler.
    return _CatalogContext(
        asset=asset,
        project=project,
        design_id=root.design_id,
        design_version=latest.version,
        spec=spec,
    )


def _asset_exact_spec(db: Session, asset: ImageAsset) -> Spec:
    root = db.get(ImageAsset, asset.root_id)
    if root is None or root.design_id is None or asset.design_version is None:
        raise CatalogApplyError(
            "revision_spec_binding_unknown",
            "component targeting requires an exact specification-bound revision",
            status_code=409,
            category="conflict",
        )
    version = db.get(DesignVersion, (root.design_id, asset.design_version))
    if version is None:
        raise CatalogApplyError(
            "spec_version_unavailable",
            "the exact revision specification is unavailable",
            status_code=404,
        )
    try:
        return Spec.model_validate(version.spec)
    except Exception as exc:
        raise CatalogApplyError(
            "spec_invalid",
            "the exact revision specification cannot be read safely",
        ) from exc


def _studio_component_targeting(
    db: Session,
    asset: ImageAsset,
) -> StudioComponentTargetingResponse:
    spec = _asset_exact_spec(db, asset)
    applicable_paths = tuple(
        path
        for path in component_catalog_paths()
        if spec.jewelry_type
        in get_component_catalog_descriptor(path).applicable_jewelry_types
    )
    image = bytes(asset.image)
    asset_hash = hashlib.sha256(image).hexdigest()
    if spec.jewelry_type != "ring":
        return StudioComponentTargetingResponse(
            asset_id=asset.id,
            asset_sha256=asset_hash,
            jewelry_type=spec.jewelry_type,
            component_map=RevisionComponentMapCapability(
                state="unmapped",
                scope="not_released",
            ),
            catalog_paths=tuple(
                CatalogPathTargetability(
                    component_path=path,
                    status="unmapped",
                    required_component_kinds=(),
                    reason_code="component_mapping_not_released_for_category",
                )
                for path in applicable_paths
            ),
        )

    component_map = load_revision_component_map(db, asset.id)
    if component_map is None:
        return StudioComponentTargetingResponse(
            asset_id=asset.id,
            asset_sha256=asset_hash,
            jewelry_type=spec.jewelry_type,
            component_map=RevisionComponentMapCapability(
                state="unmapped",
                scope="ring_v1",
            ),
            catalog_paths=tuple(
                CatalogPathTargetability(
                    component_path=path,
                    status="unmapped",
                    required_component_kinds=(RING_CATALOG_TARGET_KINDS.get(path, ())),
                    reason_code="component_map_not_found",
                )
                for path in applicable_paths
            ),
        )

    any_unresolved = any(
        component.resolution == "unresolved" for component in component_map.components
    )
    path_capabilities: list[CatalogPathTargetability] = []
    for path in applicable_paths:
        required_kinds = RING_CATALOG_TARGET_KINDS.get(path, ())
        components = tuple(
            component
            for component in component_map.components
            if component.kind in required_kinds
        )
        present = {component.kind for component in components}
        if not required_kinds or not set(required_kinds).issubset(present):
            status: Literal["ready", "unmapped", "unresolved"] = "unmapped"
            reason = "catalog_target_unmapped"
            component_ids: tuple[str, ...] = ()
        elif any(component.resolution == "unresolved" for component in components):
            status = "unresolved"
            reason = "target_component_unresolved"
            component_ids = tuple(component.component_id for component in components)
        elif (
            path not in MATERIAL_ONLY_CATALOG_PATHS
            and not catalog_structural_component_mapper_available(path)
        ):
            status = "unresolved"
            reason = "structural_child_mapping_unavailable"
            component_ids = tuple(component.component_id for component in components)
        else:
            status = "ready"
            reason = None
            component_ids = tuple(component.component_id for component in components)
        path_capabilities.append(
            CatalogPathTargetability(
                component_path=path,
                status=status,
                required_component_kinds=required_kinds,
                component_ids=component_ids,
                reason_code=reason,
            )
        )
    return StudioComponentTargetingResponse(
        asset_id=asset.id,
        asset_sha256=asset_hash,
        jewelry_type=spec.jewelry_type,
        component_map=RevisionComponentMapCapability(
            state="unresolved" if any_unresolved else "ready",
            scope="ring_v1",
            map_sha256=component_map_hash(component_map),
            mapper_contract=component_map.mapper_contract,
            raster_width=component_map.raster_width,
            raster_height=component_map.raster_height,
        ),
        catalog_paths=tuple(path_capabilities),
    )


def _catalog_option(
    component_path: str,
    option_id: str,
    *,
    stone_species: str | None = None,
) -> ComponentCatalogOption:
    options = get_component_catalog(
        component_path,
        stone_species=stone_species,
    )
    option = next(
        (candidate for candidate in options if candidate.id == option_id), None
    )
    if option is None:
        raise CatalogSelectionError(
            component_path,
            option_id,
            tuple(candidate.id for candidate in options),
        )
    return option


def _instruction(
    component_path: str,
    option: ComponentCatalogOption,
) -> str:
    geometry = "; ".join(option.visual_geometry)
    return (
        f"Apply the exact catalog selection {component_path}={option.id} "
        f"({option.display}). Required visible geometry: {geometry}. "
        "Change only the isolated component and preserve every frozen fact."
    )


_CHAIN_CHANGE_LABELS = {
    "chain.style": "chain style",
    "chain.geometry.construction": "chain construction",
    "chain.geometry.chain_width_mm": "chain width",
    "chain.geometry.profile_thickness_mm": "chain profile thickness",
    "chain.geometry.end_ring_outer_diameter_mm": "end ring outside diameter",
    "chain.geometry.link_thickness_mm": "link thickness",
    "chain.geometry.links_soldered": "links soldered",
    "chain.geometry.strand_wire_diameter_mm": "strand wire diameter",
    "chain.geometry.strand_count": "strand count",
    "chain.geometry.plate_thickness_mm": "plate thickness",
    "chain.production.mode": "chain production mode",
    "chain.production.reference_kind": "chain production reference type",
    "chain.production.reference": "chain production reference",
}


def _chain_change_label(path: str) -> str:
    known = _CHAIN_CHANGE_LABELS.get(path)
    if known is not None:
        return known
    if path.startswith("chain.geometry.links["):
        leaf = path.rsplit(".", 1)[-1]
        labels = {
            "role": "link role",
            "length_mm": "link length",
            "inside_length_mm": "link inside length",
            "inside_width_mm": "link inside width",
        }
        return labels.get(leaf, leaf.replace("_", " "))
    return path.replace("chain.", "chain ").replace("_", " ")


def _raw_chain_changes(before: Spec, after: Spec) -> tuple[JsonObject, ...]:
    """Return exact raw leaf changes for the chain target record."""
    out: list[JsonObject] = []

    def walk(left: JsonValue, right: JsonValue, path: str) -> None:
        if isinstance(left, dict) or isinstance(right, dict):
            old = left if isinstance(left, dict) else {}
            new = right if isinstance(right, dict) else {}
            for key in sorted(set(old) | set(new)):
                child = f"{path}.{key}" if path else key
                walk(old.get(key), new.get(key), child)
            return
        if isinstance(left, list) or isinstance(right, list):
            old = left if isinstance(left, list) else []
            new = right if isinstance(right, list) else []
            for index in range(max(len(old), len(new))):
                old_value = old[index] if index < len(old) else None
                new_value = new[index] if index < len(new) else None
                walk(old_value, new_value, f"{path}[{index}]")
            return
        if left == right:
            return
        out.append(
            {
                "path": path,
                "before": left,
                "after": right,
                "label": _chain_change_label(path),
            }
        )

    before_chain = before.model_dump(mode="json")["chain"]
    after_chain = after.model_dump(mode="json")["chain"]
    walk(before_chain, after_chain, "chain")
    return tuple(out)


def _prepare_chain_selection(
    source: Spec,
    request: CatalogApplyRequest,
    option: ComponentCatalogOption,
) -> CatalogSelectionResult:
    chain = source.chain
    if source.jewelry_type != "necklace" or chain is None:
        raise CatalogApplyError(
            "catalog_not_applicable",
            "chain.style requires a persisted necklace with a carrier chain",
        )
    if option.id == chain.style:
        raise CatalogApplyError(
            "catalog_selection_no_change",
            "the active specification already has this exact chain style",
        )
    missing = [
        name
        for name, value in (
            ("chain_geometry", request.chain_geometry),
            ("chain_production", request.chain_production),
        )
        if value is None
    ]
    if missing:
        raise CatalogApplyError(
            "chain_target_data_required",
            "a chain-style selection requires designer-confirmed target "
            "geometry and an exact stock/sample or custom drawing/CAD record",
            context={
                "missing_fields": missing,
                "required_fields": ["chain_geometry", "chain_production"],
            },
        )
    if chain.pendant_connection is None:
        raise CatalogApplyError(
            "chain_connection_required",
            "confirm how the chain connects to the pendant before changing style",
            context={"required_field": "chain.pendant_connection"},
        )
    target_geometry = request.chain_geometry
    target_production = request.chain_production
    assert target_geometry is not None and target_production is not None
    if (
        chain.production is not None
        and target_production == chain.production
        and target_production.reference_kind in {"supplier_sku", "approved_sample"}
    ):
        raise CatalogApplyError(
            "chain_target_production_reused",
            "a source-style supplier SKU or approved sample cannot become the "
            "target style's production reference; select the exact target item",
            context={
                "source_style": chain.style,
                "target_style": option.id,
                "reference_kind": target_production.reference_kind,
            },
        )

    raw = source.model_dump(mode="json")
    target_chain = raw["chain"]
    assert isinstance(target_chain, dict)
    target_chain["geometry"] = target_geometry.model_dump(mode="json")
    target_chain["production"] = target_production.model_dump(mode="json")
    staged = Spec.model_validate(raw)
    try:
        selected = apply_catalog_selection(
            staged,
            component_path="chain.style",
            option_id=option.id,
        )
    except CatalogSelectionError as exc:
        raise CatalogApplyError(
            "chain_target_incompatible",
            str(exc),
            context={
                "source_style": chain.style,
                "target_style": option.id,
                "target_construction": target_geometry.construction,
            },
        ) from exc

    confirmed = confirm_designer_dimension_subtree(
        selected.spec,
        prefix="chain.geometry",
        source=(f"designer-confirmed chain catalog target by {request.created_by}"),
        note="Confirmed with the target chain manufacturing record.",
    )
    blockers = chain_factory_blockers(confirmed)
    if blockers:
        raise CatalogApplyError(
            "chain_target_incomplete",
            "the target chain record is not manufacturing-complete",
            context={
                "factory_blockers": [
                    blocker.model_dump(mode="json") for blocker in blockers
                ],
            },
        )
    changes = _raw_chain_changes(source, confirmed)
    if not changes:
        raise CatalogApplyError(
            "catalog_selection_no_change",
            "the target chain record matches the active specification",
        )
    return selected.model_copy(
        update={
            "spec": confirmed,
            "spec_change": changes,
        }
    )


def _prepare_catalog_revision(
    db: Session,
    active_asset_id: str,
    request: CatalogApplyRequest,
) -> _PreparedCatalogRevision:
    """Compile one exact catalog delta without calling an image provider."""
    context = _catalog_context(db, active_asset_id, request.expected_design_version)
    descriptor = get_component_catalog_descriptor(request.component_path)
    if descriptor.image_agent_status != "catalog_ready":
        raise CatalogApplyError(
            "catalog_category_pending",
            f"{request.component_path} is cataloged but its category-specific "
            "image QA and routing are not yet released",
            status_code=409,
            category="capability",
            context={
                "status": "category_pending",
                "component_path": request.component_path,
                "applicable_jewelry_types": list(descriptor.applicable_jewelry_types),
            },
        )
    if context.spec.jewelry_type not in descriptor.applicable_jewelry_types:
        raise CatalogApplyError(
            "catalog_not_applicable",
            f"{request.component_path} is not applicable to this "
            f"{context.spec.jewelry_type}",
        )
    if request.stone_species is not None and request.component_path != "stone.color":
        raise CatalogApplyError(
            "stone_species_not_applicable",
            "stone_species is accepted only with component_path=stone.color",
        )
    palette_species = (
        request.stone_species or context.spec.stone.species
        if request.component_path == "stone.color"
        else None
    )
    option = _catalog_option(
        request.component_path,
        request.option_id,
        stone_species=palette_species,
    )
    if request.component_path == "chain.style":
        selection = _prepare_chain_selection(context.spec, request, option)
    else:
        if request.chain_geometry is not None or request.chain_production is not None:
            raise CatalogApplyError(
                "chain_target_data_not_applicable",
                "chain target manufacturing data is accepted only with "
                "component_path=chain.style",
            )
        selection = apply_catalog_selection(
            context.spec,
            component_path=request.component_path,
            option_id=request.option_id,
            stone_species=palette_species,
        )
    if not selection.spec_change:
        raise CatalogApplyError(
            "catalog_selection_no_change",
            "the active specification already has this exact catalog selection",
        )
    return _PreparedCatalogRevision(
        context=context,
        option=option,
        selection=selection,
        instruction=_instruction(request.component_path, option),
    )


def _catalog_component_target(
    db: Session,
    prepared: _PreparedCatalogRevision,
    *,
    component_path: str,
) -> _CatalogComponentTarget | None:
    """Resolve a ring catalog path to an immutable source-map mask.

    Necklace component maps are not part of the v1 contract.  Their existing
    category-specific chain path remains unchanged; all released ring material
    and structural paths fail closed before plan compilation/provider access.
    """
    if prepared.context.spec.jewelry_type != "ring":
        return None
    target_kinds = RING_CATALOG_TARGET_KINDS.get(component_path)
    if target_kinds is None:
        raise CatalogApplyError(
            "catalog_target_mapping_unavailable",
            "this ring catalog path has no released component-target policy",
            status_code=409,
            category="capability",
            context={"component_path": component_path},
        )
    if (
        component_path not in MATERIAL_ONLY_CATALOG_PATHS
        and not catalog_structural_component_mapper_available(component_path)
    ):
        raise CatalogApplyError(
            "component_mapping_unresolved",
            "a calibrated catalog child mapper is required before this "
            "structural edit can preserve exact component targeting",
            status_code=409,
            category="capability",
            context={
                "component_path": component_path,
                "source_asset_id": prepared.context.asset.id,
            },
        )
    try:
        component_map = load_revision_component_map(db, prepared.context.asset.id)
        if component_map is None:
            raise ComponentMapError(
                "the active ring revision is explicitly unmapped",
                code="component_map_not_found",
            )
        if component_map.jewelry_type != "ring":  # defensive for future maps
            raise ComponentMapError(
                "the active revision does not have a ring component map",
                code="component_map_jewelry_type_mismatch",
            )
        components = tuple(
            component
            for component in component_map.components
            if component.kind in target_kinds
        )
        present_kinds = {component.kind for component in components}
        missing_kinds = tuple(
            kind for kind in target_kinds if kind not in present_kinds
        )
        if missing_kinds:
            raise ComponentMapError(
                "the active revision is unmapped for catalog target kinds: "
                + ", ".join(missing_kinds),
                code="catalog_target_unmapped",
            )
        # rasterize_component_masks performs membership and resolution checks
        # for every identity and rejects an empty aggregate.
        component_ids = tuple(component.component_id for component in components)
        mask_bytes = rasterize_component_masks(component_map, component_ids)
    except ComponentMapError as exc:
        raise CatalogApplyError(
            exc.code,
            exc.detail,
            context={
                "component_path": component_path,
                "required_component_kinds": list(target_kinds),
                "source_asset_id": prepared.context.asset.id,
            },
        ) from exc
    map_sha256 = component_map_hash(component_map)
    return _CatalogComponentTarget(
        component_map=component_map,
        component_ids=component_ids,
        component_kinds=target_kinds,
        map_sha256=map_sha256,
        mask_bytes=mask_bytes,
        mask_sha256=hashlib.sha256(mask_bytes).hexdigest(),
    )


def _catalog_image_plan(
    prepared: _PreparedCatalogRevision,
    *,
    variant: int,
    target: _CatalogComponentTarget | None,
):
    context = prepared.context
    selection = prepared.selection
    option = prepared.option
    plan = build_image_plan(
        ImageOperation.LOCAL_EDIT,
        prepared.instruction,
        spec=selection.spec,
        source_spec=context.spec,
        source_image=bytes(context.asset.image),
        region_description=selection.isolation_target,
        frozen=(
            *selection.frozen_facts,
            "every specification path outside the exact catalog delta",
            "camera, framing, scale, lighting, and background",
        ),
        style_constraints=option.visual_geometry,
        expected_output=(
            f"only {option.display} applied inside {selection.isolation_target}"
        ),
        variant=variant,
    )
    if target is None:
        return plan
    return bind_localization_mask(
        plan,
        target.mask_bytes,
        provenance="revision_component_map",
        evidence={
            "schema_version": target.component_map.schema_version,
            "source_asset_id": context.asset.id,
            "component_map_sha256": target.map_sha256,
            "target_component_ids": list(target.component_ids),
            "target_component_kinds": list(target.component_kinds),
            "mask_sha256": target.mask_sha256,
            "authority": "exact_source_revision_image_editing_only",
        },
    )


def _quality_payload(result: ImageAgentResult) -> JsonObject:
    failed = list(result.quality.failed_checks)
    return {
        **result.quality.model_dump(mode="json"),
        "accepted": result.accepted,
        "review_required": result.review_required,
        "summary": (
            "Image checks passed."
            if result.accepted
            else "Image needs explicit designer review."
        ),
        "failed_checks": [check.code for check in failed],
        "warnings": [
            check.message for check in failed if check.severity.value == "warning"
        ],
    }


def _routing_payload(
    result: ImageAgentResult,
    run_id: str | None = None,
) -> JsonObject:
    attempts = result.run.attempts
    return {
        "attempt_count": len(attempts),
        "used_retry": len(attempts) > 1,
        "used_fallback": any(attempt.fallback for attempt in attempts),
        "cache_hit": any(attempt.cached for attempt in attempts),
        "run_id": run_id,
    }


def _candidate_drift(result: ImageAgentResult) -> float | None:
    value = next(
        (
            check.evidence.get("drift")
            for check in result.quality.checks
            if check.code == "outside_mask_drift"
        ),
        None,
    )
    return float(value) if isinstance(value, (int, float)) else None


def _catalog_selection_error_response(exc: CatalogSelectionError) -> JSONResponse:
    return _error_response(
        CatalogApplyError(
            "catalog_selection_invalid",
            str(exc),
            context={
                "component_path": exc.component_path,
                "option_id": exc.option_id,
                "valid_options": list(exc.valid_options),
            },
        )
    )


@router.post(
    "/{active_asset_id}/catalog/preview",
    status_code=201,
    response_model=CatalogPreviewResponse,
)
def preview_catalog_revision(
    active_asset_id: str,
    request: CatalogPreviewRequest,
    db: DbSession,
    principal: PrincipalDep,
):
    """Evaluate a catalog change and retain only a temporary candidate.

    Both pass and warning results require an explicit Apply.  The provider and
    jewelry QA finish before this route stores durable ImageRun evidence; no
    ImageAsset or DesignVersion is created here.
    """
    actor = principal_actor(principal, request.created_by)
    try:
        prepared = _prepare_catalog_revision(db, active_asset_id, request)
    except CatalogApplyError as exc:
        return _error_response(exc)
    except CatalogSelectionError as exc:
        return _catalog_selection_error_response(exc)

    context = prepared.context
    selection = prepared.selection
    if request.studio_job_id is not None:
        try:
            # Hold the exact job row through provider execution and candidate
            # persistence. PostgreSQL therefore serializes duplicate requests;
            # the winner moves the job to reviewing in the same transaction,
            # and every replay is rejected before any provider-backed work.
            validate_catalog_preview_refine_job(
                db,
                job_id=request.studio_job_id,
                owner=actor,
                project_root_id=context.project.root_id,
                source_asset_id=context.asset.id,
            )
        except CatalogPreviewJobError as exc:
            return _error_response(
                CatalogApplyError(
                    "catalog_preview_job_invalid",
                    str(exc),
                    status_code=409,
                    category="conflict",
                )
            )
    try:
        target = _catalog_component_target(
            db, prepared, component_path=request.component_path
        )
    except CatalogApplyError as exc:
        return _error_response(exc)
    try:
        plan = _catalog_image_plan(prepared, variant=request.variant, target=target)
        result = _trusted_image_agent().run(
            plan,
            source_image=bytes(context.asset.image),
            mask_bytes=(target.mask_bytes if target is not None else None),
        )
    except ImageAgentError as exc:
        run_id = None
        if exc.plan is not None:
            run_id = persist_image_agent_failure(
                db,
                exc.plan,
                exc,
                project_root_id=context.project.root_id,
                source_asset_id=context.asset.id,
                created_by=actor,
                commit=(request.studio_job_id is None),
            )
        if request.studio_job_id is not None:
            try:
                settle_catalog_preview_refine_job_failure(
                    db,
                    job_id=request.studio_job_id,
                    owner=actor,
                    project_root_id=context.project.root_id,
                    source_asset_id=context.asset.id,
                    error_code=exc.code,
                    commit=False,
                )
                db.commit()
            except CatalogPreviewJobError as job_exc:
                db.rollback()
                # The binding changed after preflight. Preserve one failure
                # run, but never pretend it was atomically settled to that job.
                if exc.plan is not None:
                    run_id = persist_image_agent_failure(
                        db,
                        exc.plan,
                        exc,
                        project_root_id=context.project.root_id,
                        source_asset_id=context.asset.id,
                        created_by=actor,
                    )
                return _error_response(
                    CatalogApplyError(
                        "catalog_preview_job_invalid",
                        str(job_exc),
                        status_code=409,
                        category="conflict",
                    )
                )
        return image_agent_error_response(
            exc,
            image_run_id=run_id,
            extra={
                "component_path": request.component_path,
                "option_id": request.option_id,
            },
        )

    # LOCAL_EDIT plans with source and target specifications always carry all
    # three lineage hashes.  Refuse to create an accept-capable candidate if a
    # future plan compiler ever violates that invariant.
    if (
        plan.source_hash is None
        or plan.source_spec_visual_hash is None
        or plan.spec_visual_hash is None
    ):
        lineage_error = CatalogApplyError(
            "catalog_preview_lineage_incomplete",
            "the evaluated preview is missing exact source/specification lineage",
            status_code=500,
            category="internal",
        )
        run_id = persist_image_agent_result(
            db,
            result,
            project_root_id=context.project.root_id,
            source_asset_id=context.asset.id,
            created_by=actor,
            status_override="failed",
            commit=False,
        )
        failed_run = db.get(ImageRun, run_id)
        if failed_run is not None:
            failed_run.error_category = lineage_error.code[:32]
        if request.studio_job_id is not None:
            try:
                settle_catalog_preview_refine_job_failure(
                    db,
                    job_id=request.studio_job_id,
                    owner=actor,
                    project_root_id=context.project.root_id,
                    source_asset_id=context.asset.id,
                    error_code=lineage_error.code,
                    commit=False,
                )
                db.commit()
            except CatalogPreviewJobError as job_exc:
                db.rollback()
                run_id = persist_image_agent_result(
                    db,
                    result,
                    project_root_id=context.project.root_id,
                    source_asset_id=context.asset.id,
                    created_by=actor,
                    status_override="failed",
                    commit=False,
                )
                failed_run = db.get(ImageRun, run_id)
                if failed_run is not None:
                    failed_run.error_category = lineage_error.code[:32]
                db.commit()
                return _error_response(
                    CatalogApplyError(
                        "catalog_preview_job_invalid",
                        str(job_exc),
                        status_code=409,
                        category="conflict",
                    )
                )
        else:
            db.commit()
        lineage_error.context["image_run_id"] = run_id
        return _error_response(lineage_error)

    qa = _quality_payload(result)
    verdict: Literal["pass", "warn"] = "pass" if result.accepted else "warn"
    raw_changes: tuple[JsonObject, ...] = tuple(
        dict(change) for change in selection.spec_change
    )
    proposed_child_component_map: RevisionComponentMap | None = None
    structural = request.component_path in STRUCTURAL_CATALOG_PATHS
    structural_error: CatalogApplyError | None = None
    if structural and not result.accepted:
        structural_error = CatalogApplyError(
            "catalog_structural_qa_unresolved",
            "structural refinement requires a fully passed jewelry QA result",
            status_code=422,
            category="quality",
            context={
                "component_path": request.component_path,
                "option_id": request.option_id,
                "qa": qa,
            },
        )
    elif structural:
        try:
            proposed_child_component_map = prepare_catalog_child_component_map(
                db,
                source_asset_id=context.asset.id,
                source_image=bytes(context.asset.image),
                child_asset_id=new_id("tmp"),
                child_image=result.image_bytes,
                jewelry_type=selection.spec.jewelry_type,
                component_path=request.component_path,
                target_component_ids=(
                    target.component_ids if target is not None else ()
                ),
                changed_spec_paths=tuple(
                    str(change["path"]) for change in raw_changes
                ),
                instruction=prepared.instruction,
            )
        except ComponentMapError as exc:
            structural_error = CatalogApplyError(
                exc.code,
                exc.detail,
                status_code=(
                    409 if exc.code == "component_mapping_unresolved" else 422
                ),
                category="capability",
                context={
                    "component_path": request.component_path,
                    "option_id": request.option_id,
                },
            )
    if structural_error is not None:
        run_id = persist_image_agent_result(
            db,
            result,
            project_root_id=context.project.root_id,
            source_asset_id=context.asset.id,
            created_by=actor,
            status_override="failed",
            commit=False,
        )
        failed_run = db.get(ImageRun, run_id)
        if failed_run is not None:
            failed_run.error_category = structural_error.code
        if request.studio_job_id is not None:
            try:
                settle_catalog_preview_refine_job_failure(
                    db,
                    job_id=request.studio_job_id,
                    owner=actor,
                    project_root_id=context.project.root_id,
                    source_asset_id=context.asset.id,
                    error_code=structural_error.code,
                    commit=False,
                )
                db.commit()
            except CatalogPreviewJobError as job_exc:
                db.rollback()
                run_id = persist_image_agent_result(
                    db,
                    result,
                    project_root_id=context.project.root_id,
                    source_asset_id=context.asset.id,
                    created_by=actor,
                    status_override="failed",
                    commit=False,
                )
                failed_run = db.get(ImageRun, run_id)
                if failed_run is not None:
                    failed_run.error_category = structural_error.code
                db.commit()
                return _error_response(
                    CatalogApplyError(
                        "catalog_preview_job_invalid",
                        str(job_exc),
                        status_code=409,
                        category="conflict",
                    )
                )
        else:
            db.commit()
        structural_error.context["image_run_id"] = run_id
        return _error_response(structural_error)

    run_id = persist_image_agent_result(
        db,
        result,
        project_root_id=context.project.root_id,
        source_asset_id=context.asset.id,
        created_by=actor,
        status_override=("preview_ready" if result.accepted else "review_required"),
        commit=False,
    )
    routing = _routing_payload(result, run_id)
    try:
        candidate = store_catalog_preview_candidate(
            db,
            run_id=run_id,
            verdict=verdict,
            project_root_id=context.project.root_id,
            source_asset_id=context.asset.id,
            expected_active_asset_id=context.asset.id,
            expected_design_version=context.design_version,
            source_hash=plan.source_hash,
            source_spec_visual_hash=plan.source_spec_visual_hash,
            target_spec_visual_hash=plan.spec_visual_hash,
            image_bytes=result.image_bytes,
            media_type=sniff_media_type(result.image_bytes),
            requested_change=prepared.instruction,
            region_description=selection.isolation_target,
            drift=_candidate_drift(result),
            next_spec=selection.spec,
            component_path=request.component_path,
            option_id=request.option_id,
            spec_change=raw_changes,
            qa=qa,
            routing=routing,
            created_by=actor,
            component_map_sha256=(target.map_sha256 if target is not None else None),
            target_component_ids=(target.component_ids if target is not None else ()),
            target_mask_sha256=(target.mask_sha256 if target is not None else None),
            proposed_child_component_map=proposed_child_component_map,
            studio_job_id=request.studio_job_id,
        )
    except (CatalogPreviewJobError, CatalogPreviewUnavailable) as exc:
        db.rollback()
        return _error_response(
            CatalogApplyError(
                "catalog_preview_job_invalid",
                str(exc),
                status_code=409,
                category="conflict",
            )
        )
    base_url = f"/image-runs/{run_id}/catalog-candidates/{candidate.candidate_id}"
    response = CatalogPreviewResponse(
        status=("preview_ready" if verdict == "pass" else "review_required"),
        component_path=request.component_path,
        option_id=request.option_id,
        isolation_target=selection.isolation_target,
        source_asset_id=context.asset.id,
        design_version=context.design_version,
        image_run_id=run_id,
        spec_change=tuple(
            CatalogSpecChange.model_validate(change) for change in selection.spec_change
        ),
        next_spec=selection.spec,
        qa=qa,
        routing=routing,
        project=ProjectDetail.model_validate(project_detail(db, context.project)),
        candidate=CatalogPreviewCandidateSummary(
            run_id=run_id,
            candidate_id=candidate.candidate_id,
            preview_url=f"{base_url}/image",
            accept_url=f"{base_url}/accept",
            discard_url=base_url,
            save_as_variation_url=f"{base_url}/save-as-variation",
            verdict=verdict,
            studio_job_id=candidate.studio_job_id,
        ),
    )
    if verdict == "warn":
        return JSONResponse(
            status_code=202,
            content=response.model_dump(mode="json"),
        )
    return response


@router.get(
    "/{asset_id}/studio-component-targeting",
    response_model=StudioComponentTargetingResponse,
)
def get_studio_component_targeting(asset_id: str, db: DbSession):
    """Read exact raster-bound targeting facts without exposing map geometry."""
    asset = db.get(ImageAsset, asset_id)
    if asset is None:
        return _error_response(
            CatalogApplyError(
                "asset_not_found",
                f"unknown asset {asset_id!r}",
                status_code=404,
            )
        )
    try:
        return _studio_component_targeting(db, asset)
    except ComponentMapError as exc:
        return _error_response(
            CatalogApplyError(
                exc.code,
                exc.detail,
                status_code=409,
                category="validation",
                context={"source_asset_id": asset_id},
            )
        )
    except CatalogApplyError as exc:
        return _error_response(exc)


@router.post(
    "/{asset_id}/studio-component-map",
    response_model=StudioComponentTargetingResponse,
)
def prepare_studio_component_map(asset_id: str, db: DbSession):
    """Prepare image-edit targeting for one exact ring revision.

    This endpoint creates only an immutable raster component map. It does not
    revise the design, create a candidate, charge generation credits, infer
    dimensions, or add Factory authority. Existing maps make the call
    idempotent.
    """
    # Serialize the provider-backed preparation on the immutable asset. The
    # second caller rechecks after acquiring the row lock and reuses the map
    # instead of paying for a duplicate vision request.
    asset = db.scalar(
        select(ImageAsset)
        .where(ImageAsset.id == asset_id)
        .with_for_update()
    )
    if asset is None:
        return _error_response(
            CatalogApplyError(
                "asset_not_found",
                f"unknown asset {asset_id!r}",
                status_code=404,
            )
        )
    try:
        existing = load_revision_component_map(db, asset.id)
        if existing is None:
            spec = _asset_exact_spec(db, asset)
            proposed = prepare_catalog_source_component_map(
                asset_id=asset.id,
                image=bytes(asset.image),
                jewelry_type=spec.jewelry_type,
            )
            add_revision_component_map(
                db,
                proposed,
                image_bytes=bytes(asset.image),
                parent_asset_id=asset.parent_asset_id,
            )
            db.commit()
        return _studio_component_targeting(db, asset)
    except IntegrityError:
        # Concurrent preparation is safe: immutable asset IDs permit exactly
        # one winner and the loser reopens the same canonical map.
        db.rollback()
        try:
            return _studio_component_targeting(db, asset)
        except (ComponentMapError, CatalogApplyError) as exc:
            if isinstance(exc, CatalogApplyError):
                return _error_response(exc)
            return _error_response(
                CatalogApplyError(
                    exc.code,
                    exc.detail,
                    status_code=409,
                    category="validation",
                )
            )
    except ComponentMapError as exc:
        db.rollback()
        return _error_response(
            CatalogApplyError(
                exc.code,
                exc.detail,
                status_code=409,
                category="capability",
                context={"source_asset_id": asset_id},
            )
        )
    except CatalogApplyError as exc:
        db.rollback()
        return _error_response(exc)


@router.get("/{active_asset_id}/catalog/previews")
def reopen_catalog_previews(
    active_asset_id: str,
    db: DbSession,
    principal: PrincipalDep,
):
    asset = db.get(ImageAsset, active_asset_id)
    project = db.get(Project, asset.root_id) if asset is not None else None
    if project is None or (
        not principal.local_unbound and project.owner != principal.subject
    ):
        return JSONResponse(
            status_code=404,
            content={
                "code": "project_not_found",
                "category": "conflict",
                "detail": "the catalog preview project is unavailable",
            },
        )
    candidates = list_catalog_preview_candidates(
        db,
        project_root_id=project.root_id,
        owner=project.owner,
    )
    return {
        "candidates": [
            {
                "candidate_id": candidate.candidate_id,
                "image_run_id": candidate.run_id,
                "source_asset_id": candidate.source_asset_id,
                "component_path": candidate.component_path,
                "option_id": candidate.option_id,
                "requested_change": candidate.requested_change,
                "verdict": candidate.verdict,
                "preview_url": (
                    f"/image-runs/{candidate.run_id}/catalog-candidates/"
                    f"{candidate.candidate_id}/image"
                ),
                "save_as_variation_url": (
                    f"/image-runs/{candidate.run_id}/catalog-candidates/"
                    f"{candidate.candidate_id}/save-as-variation"
                ),
                "next_spec": candidate.next_spec.model_dump(mode="json"),
                "spec_change": list(candidate.spec_change),
                "qa": candidate.qa,
                "routing": candidate.routing,
                "studio_job_id": candidate.studio_job_id,
                "expires_at": candidate.expires_at.isoformat(),
            }
            for candidate in candidates
        ]
    }


@preview_router.get("/image-runs/{run_id}/catalog-candidates/{candidate_id}/image")
def get_catalog_preview_image(
    run_id: str,
    candidate_id: str,
    db: DbSession,
    principal: PrincipalDep,
):
    run = db.get(ImageRun, run_id)
    if run is None or (
        not principal.local_unbound and run.created_by != principal.subject
    ):
        return JSONResponse(
            status_code=404,
            content={
                "code": "catalog_preview_unavailable",
                "category": "conflict",
                "detail": "the catalog preview is unavailable",
            },
        )
    try:
        candidate = get_catalog_preview_candidate(
            db,
            run_id,
            candidate_id,
            owner=run.created_by,
        )
    except CatalogPreviewUnavailable as exc:
        db.rollback()
        try:
            invalidate_catalog_preview_candidate(
                db,
                run_id,
                candidate_id,
                owner=run.created_by,
            )
        except CatalogPreviewJobError as job_exc:
            db.rollback()
            return JSONResponse(
                status_code=409,
                content={
                    "code": "catalog_preview_job_conflict",
                    "category": "conflict",
                    "detail": str(job_exc),
                },
            )
        return JSONResponse(
            status_code=410,
            content={
                "code": "catalog_preview_unavailable",
                "category": "conflict",
                "detail": str(exc),
            },
        )
    except CatalogPreviewJobError as exc:
        db.rollback()
        return JSONResponse(
            status_code=410,
            content={
                "code": "catalog_preview_unavailable",
                "category": "conflict",
                "detail": str(exc),
            },
        )
    return Response(
        content=candidate.image_bytes,
        media_type=candidate.media_type,
        headers={"Cache-Control": "private, no-store"},
    )


@preview_router.delete(
    "/image-runs/{run_id}/catalog-candidates/{candidate_id}",
    status_code=204,
)
def discard_catalog_preview(
    run_id: str,
    candidate_id: str,
    db: DbSession,
    principal: PrincipalDep,
):
    run = db.get(ImageRun, run_id)
    if run is None or (
        not principal.local_unbound and run.created_by != principal.subject
    ):
        return JSONResponse(
            status_code=404,
            content={
                "code": "catalog_preview_unavailable",
                "category": "conflict",
                "detail": "the catalog preview is unavailable",
            },
        )
    try:
        discard_catalog_preview_candidate(
            db,
            run_id,
            candidate_id,
            owner=run.created_by,
        )
    except (CatalogPreviewUnavailable, CatalogPreviewJobError) as exc:
        db.rollback()
        return JSONResponse(
            status_code=410,
            content={
                "code": "catalog_preview_unavailable",
                "category": "conflict",
                "detail": str(exc),
            },
        )
    return Response(status_code=204)


@preview_router.post(
    "/image-runs/{run_id}/catalog-candidates/{candidate_id}/accept",
    status_code=201,
    response_model=CatalogPreviewAcceptResponse,
)
def accept_catalog_preview(
    run_id: str,
    candidate_id: str,
    request: CatalogPreviewAcceptRequest,
    db: DbSession,
    principal: PrincipalDep,
):
    actor = principal_actor(principal, request.created_by)
    try:
        candidate = get_catalog_preview_candidate(
            db,
            run_id,
            candidate_id,
            owner=actor,
        )
        accepted = accept_catalog_preview_revision(
            db,
            candidate,
            expected_design_version=request.expected_design_version,
            created_by=actor,
            commit=False,
        )
        resolve_catalog_preview_candidate(
            db,
            run_id,
            candidate_id,
            owner=actor,
            status="applied",
            review_id=accepted.review_id,
            terminal_asset_id=accepted.asset_id,
            commit=False,
        )
        settle_catalog_preview_acceptance(db, candidate, owner=actor)
        db.commit()
    except CatalogPreviewUnavailable as exc:
        try:
            invalidate_catalog_preview_candidate(
                db,
                run_id,
                candidate_id,
                owner=actor,
            )
        except CatalogPreviewJobError as job_exc:
            db.rollback()
            return JSONResponse(
                status_code=409,
                content={
                    "code": "catalog_preview_job_conflict",
                    "category": "conflict",
                    "detail": str(job_exc),
                },
            )
        return JSONResponse(
            status_code=410,
            content={
                "code": "catalog_preview_unavailable",
                "category": "conflict",
                "detail": str(exc),
            },
        )
    except CatalogPreviewJobError as exc:
        db.rollback()
        return JSONResponse(
            status_code=409,
            content={
                "code": "catalog_preview_job_conflict",
                "category": "conflict",
                "detail": str(exc),
            },
        )
    except WarningRevisionError as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.code,
                "category": (
                    "stale_version"
                    if exc.code.startswith("stale_")
                    else "validation"
                    if exc.status_code == 422
                    else "conflict"
                ),
                "detail": exc.detail,
            },
        )
    project = db.get(Project, candidate.project_root_id)
    if project is None:
        return _error_response(
            CatalogApplyError(
                "project_not_found",
                "the accepted catalog preview project is unavailable",
                status_code=404,
            )
        )
    return CatalogPreviewAcceptResponse(
        asset_id=accepted.asset_id,
        design_version=accepted.design_version,
        image_run_id=run_id,
        spec_change=tuple(
            CatalogSpecChange.model_validate(change) for change in candidate.spec_change
        ),
        project=ProjectDetail.model_validate(project_detail(db, project)),
    )


@preview_router.post(
    "/image-runs/{run_id}/catalog-candidates/{candidate_id}/save-as-variation",
    status_code=201,
)
def save_catalog_preview_as_variation(
    run_id: str,
    candidate_id: str,
    request: CatalogPreviewVariationRequest,
    db: DbSession,
    principal: PrincipalDep,
):
    actor = principal_actor(principal, request.created_by)
    try:
        result = fork_preview_candidate_variation(
            db,
            kind="catalog_revision",
            run_id=run_id,
            candidate_id=candidate_id,
            variation_label=request.label,
            created_by=actor,
        )
    except StudioHistoryError as exc:
        if exc.code == "preview_candidate_unavailable":
            try:
                invalidate_catalog_preview_candidate(
                    db,
                    run_id,
                    candidate_id,
                    owner=actor,
                )
            except CatalogPreviewJobError as job_exc:
                db.rollback()
                return JSONResponse(
                    status_code=409,
                    content={
                        "code": "catalog_preview_job_conflict",
                        "category": "conflict",
                        "detail": str(job_exc),
                    },
                )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.code,
                "category": "conflict",
                "detail": exc.detail,
            },
        )
    project = db.get(Project, result.project_root_id)
    if project is None:  # pragma: no cover
        return _error_response(
            CatalogApplyError(
                "project_not_found",
                "the variation is unavailable",
                status_code=500,
            )
        )
    return {
        "status": "saved_as_variation",
        "family_id": result.family_id,
        "variation_index": result.variation_index,
        "design_id": result.design_id,
        "design_version": result.design_version,
        "project": ProjectDetail.model_validate(project_detail(db, project)),
    }


@router.post(
    "/{active_asset_id}/catalog/apply",
    status_code=201,
    response_model=CatalogApplyResponse,
    response_model_exclude_none=True,
    deprecated=True,
)
def apply_catalog_revision(
    active_asset_id: str,
    request: CatalogApplyRequest,
    db: DbSession,
    principal: PrincipalDep,
):
    """Apply one deterministic catalog choice through the trusted image loop."""
    actor = principal_actor(principal, request.created_by)
    try:
        prepared = _prepare_catalog_revision(db, active_asset_id, request)
    except CatalogApplyError as exc:
        return _error_response(exc)
    except CatalogSelectionError as exc:
        return _catalog_selection_error_response(exc)

    context = prepared.context
    selection = prepared.selection
    instruction = prepared.instruction
    try:
        target = _catalog_component_target(
            db, prepared, component_path=request.component_path
        )
    except CatalogApplyError as exc:
        return _error_response(exc)
    try:
        plan = _catalog_image_plan(prepared, variant=request.variant, target=target)
        result = _trusted_image_agent().run(
            plan,
            source_image=bytes(context.asset.image),
            mask_bytes=(target.mask_bytes if target is not None else None),
        )
    except ImageAgentError as exc:
        run_id = None
        if exc.plan is not None:
            run_id = persist_image_agent_failure(
                db,
                exc.plan,
                exc,
                project_root_id=context.project.root_id,
                source_asset_id=context.asset.id,
                created_by=actor,
            )
        return image_agent_error_response(
            exc,
            image_run_id=run_id,
            extra={
                "component_path": request.component_path,
                "option_id": request.option_id,
            },
        )

    qa = _quality_payload(result)
    routing = _routing_payload(result)
    changes = tuple(
        CatalogSpecChange.model_validate(change) for change in selection.spec_change
    )
    if result.review_required:
        run_id = persist_image_agent_result(
            db,
            result,
            project_root_id=context.project.root_id,
            source_asset_id=context.asset.id,
            created_by=actor,
        )
        routing = _routing_payload(result, run_id)
        candidate = store_markup_warning_candidate(
            run_id=run_id,
            project_root_id=context.project.root_id,
            source_asset_id=context.asset.id,
            expected_active_asset_id=context.asset.id,
            expected_design_version=context.design_version,
            image_bytes=result.image_bytes,
            media_type=sniff_media_type(result.image_bytes),
            operation=ImageOperation.LOCAL_EDIT.value,
            asset_capability="LOCALIZED_EDIT",
            requested_change=instruction,
            region_description=selection.isolation_target,
            drift=_candidate_drift(result),
            next_spec=selection.spec,
            ignored_fields=(),
            qa=qa,
            routing=routing,
            created_by=actor,
        )
        response = CatalogApplyResponse(
            status="review_required",
            component_path=request.component_path,
            option_id=request.option_id,
            isolation_target=selection.isolation_target,
            design_version=context.design_version,
            image_run_id=run_id,
            spec_change=changes,
            next_spec=selection.spec,
            qa=qa,
            routing=routing,
            project=ProjectDetail.model_validate(project_detail(db, context.project)),
            warning_candidate=CatalogWarningCandidate(
                run_id=run_id,
                candidate_id=candidate.candidate_id,
                preview_url=(
                    f"/image-runs/{run_id}/candidates/{candidate.candidate_id}/image"
                ),
                requested_change=instruction,
            ),
        )
        return JSONResponse(
            status_code=202,
            content=response.model_dump(mode="json", exclude_none=True),
        )

    try:
        persisted = persist_spec_image_revision(
            db,
            source_asset=context.asset,
            expected_design_version=context.design_version,
            next_spec=selection.spec,
            image_run=result,
            instruction=instruction,
            region=selection.isolation_target,
            created_by=actor,
            drift=_candidate_drift(result),
        )
    except TrustedSpecRevisionError as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.code,
                "category": (
                    "stale_version" if exc.code.startswith("stale_") else "validation"
                ),
                "detail": exc.detail,
            },
        )
    routing = _routing_payload(result, persisted.image_run_id)
    return CatalogApplyResponse(
        status="accepted",
        component_path=request.component_path,
        option_id=request.option_id,
        isolation_target=selection.isolation_target,
        asset_id=persisted.asset_id,
        design_version=persisted.design_version,
        image_run_id=persisted.image_run_id,
        spec_change=changes,
        qa=qa,
        routing=routing,
        project=ProjectDetail.model_validate(project_detail(db, context.project)),
    )

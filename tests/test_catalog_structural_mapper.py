from __future__ import annotations

import hashlib
import io

from PIL import Image, ImageDraw
import pytest

from facetta import catalog_component_targeting
from facetta.catalog_structural_mapper import (
    GROK_RING_COMPONENT_MAPPER_CONTRACT,
    GrokRingComponentMapper,
)
from facetta.catalog_structural_mapper_composition import (
    configure_attested_catalog_structural_mapper_from_environment,
)
from facetta.design_form import NormalizedPoint, NormalizedPolygon
from facetta.revision_component_map import (
    ComponentMappingUnresolved,
    RevisionComponent,
    RevisionComponentMap,
    polygon_hash,
    reconcile_parent_component_ids,
)


Box = tuple[float, float, float, float]


# Visible semantic regions rather than loose component bounding boxes.  The
# aggregate metal zone is intentionally allowed to overlap the metal leaves;
# background is limited to genuinely empty frame strips.
_INVENTORY: tuple[tuple[str, str, str, tuple[Box, ...]], ...] = (
    ("center_stone.main", "center_stone", "Center stone", ((0.42, 0.28, 0.58, 0.44),)),
    (
        "stone_group.side",
        "stone_group",
        "Side stones",
        ((0.24, 0.30, 0.32, 0.38), (0.68, 0.30, 0.76, 0.38)),
    ),
    (
        "prongs.center",
        "prongs",
        "Center prongs",
        (
            (0.39, 0.25, 0.42, 0.30),
            (0.58, 0.25, 0.61, 0.30),
            (0.39, 0.42, 0.42, 0.47),
            (0.58, 0.42, 0.61, 0.47),
        ),
    ),
    (
        "setting.center",
        "setting",
        "Center setting",
        (
            (0.35, 0.20, 0.65, 0.24),
            (0.35, 0.24, 0.39, 0.50),
            (0.61, 0.24, 0.65, 0.50),
            (0.39, 0.47, 0.61, 0.51),
        ),
    ),
    (
        "shank.main",
        "shank",
        "Shank",
        (
            (0.30, 0.64, 0.38, 0.86),
            (0.62, 0.64, 0.70, 0.86),
            (0.38, 0.78, 0.62, 0.86),
        ),
    ),
    (
        "shoulders.main",
        "shoulders",
        "Shoulders",
        ((0.27, 0.54, 0.37, 0.64), (0.63, 0.54, 0.73, 0.64)),
    ),
    ("gallery.main", "gallery", "Gallery", ((0.42, 0.53, 0.58, 0.59),)),
    ("metal_zone.main", "metal_zone", "Visible metal", ((0.20, 0.18, 0.80, 0.86),)),
    (
        "background.main",
        "background",
        "Background",
        (
            (0.00, 0.00, 1.00, 0.14),
            (0.00, 0.91, 1.00, 1.00),
            (0.00, 0.15, 0.14, 0.90),
            (0.86, 0.15, 1.00, 0.90),
        ),
    ),
)


def _png(*, changed_box: tuple[int, int, int, int] | None = None) -> bytes:
    image = Image.new("RGB", (100, 100), "white")
    if changed_box is not None:
        ImageDraw.Draw(image).rectangle(changed_box, fill="red")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _polygon(box: tuple[float, float, float, float]) -> NormalizedPolygon:
    left, top, right, bottom = box
    return NormalizedPolygon(points=(
        NormalizedPoint(x=float(left), y=float(top)),
        NormalizedPoint(x=float(right), y=float(top)),
        NormalizedPoint(x=float(right), y=float(bottom)),
        NormalizedPoint(x=float(left), y=float(bottom)),
    ))


def _parent_map(image: bytes) -> RevisionComponentMap:
    components = []
    for component_id, kind, label, boxes in _INVENTORY:
        polygons = tuple(_polygon(box) for box in boxes)
        components.append(RevisionComponent(
            component_id=component_id,
            kind=kind,
            label=label,
            resolution="resolved",
            polygons=polygons,
            polygon_sha256=polygon_hash(polygons),
        ))
    return RevisionComponentMap(
        asset_id="ast_parent",
        asset_sha256=hashlib.sha256(image).hexdigest(),
        raster_width=100,
        raster_height=100,
        jewelry_type="ring",
        mapper_contract="test.source-map.v1",
        components=tuple(components),
    )


def _observed(
    *,
    omit: str | None = None,
    override_box: dict[str, Box] | None = None,
    extra_box: dict[str, Box] | None = None,
    unresolved: set[str] | None = None,
) -> dict:
    boxes = override_box or {}
    extras = extra_box or {}
    unresolved_ids = unresolved or set()
    components = []
    for component_id, kind, _label, default_boxes in _INVENTORY:
        if component_id == omit:
            continue
        is_unresolved = component_id in unresolved_ids
        component_boxes = (
            (boxes[component_id],)
            if component_id in boxes
            else default_boxes
        )
        if component_id in extras:
            component_boxes = (*component_boxes, extras[component_id])
        components.append({
            "parent_component_id": component_id,
            "kind": kind,
            "resolution": "unresolved" if is_unresolved else "resolved",
            "polygons": [] if is_unresolved else [
                {"points": [
                    {"x": left, "y": top},
                    {"x": right, "y": top},
                    {"x": right, "y": bottom},
                    {"x": left, "y": bottom},
                ]}
                for left, top, right, bottom in component_boxes
            ],
        })
    return {"components": components}


@pytest.fixture(autouse=True)
def _reset_mapper():
    catalog_component_targeting.configure_catalog_structural_component_mapper(None)
    yield
    catalog_component_targeting.configure_catalog_structural_component_mapper(None)


def test_cut_target_authorizes_the_coupled_stone_prong_and_setting_region():
    assert catalog_component_targeting.RING_CATALOG_TARGET_KINDS["stone.cut"] == (
        "center_stone",
        "prongs",
        "setting",
    )


def test_grok_child_mapper_reconciles_inventory_and_validates_change_coverage():
    parent_image = _png()
    child_image = _png(changed_box=(40, 25, 60, 45))
    parent = _parent_map(parent_image)
    mapper = GrokRingComponentMapper(
        inspect_pair=lambda *_args: _observed(),
    )

    proposed = mapper(
        parent_map=parent,
        parent_image=parent_image,
        child_asset_id="run_preview",
        child_image=child_image,
        target_component_ids=(
            "center_stone.main",
            "prongs.center",
            "setting.center",
        ),
        component_path="stone.cut",
        instruction="Change the center cut while preserving setting facts.",
    )
    reconciled = reconcile_parent_component_ids(parent, proposed)

    assert proposed.mapper_contract == GROK_RING_COMPONENT_MAPPER_CONTRACT
    assert {item.parent_component_id for item in proposed.components} == {
        item.component_id for item in parent.components
    }
    assert {item.component_id for item in reconciled.components} == {
        item.component_id for item in parent.components
    }


@pytest.mark.parametrize(
    ("response", "child_image", "detail"),
    (
        (_observed(omit="gallery.main"), _png(changed_box=(40, 25, 60, 45)), "inventory"),
        (
            _observed(override_box={"shank.main": (0.17, 0.65, 0.25, 0.88)}),
            _png(changed_box=(40, 25, 60, 45)),
            "non-target component",
        ),
        (
            _observed(),
            _png(changed_box=(2, 2, 18, 18)),
            "source authorization",
        ),
        (_observed(), _png(), "did not make a visible"),
    ),
)
def test_grok_child_mapper_fails_closed_on_unsafe_evidence(
    response,
    child_image,
    detail,
):
    parent_image = _png()
    parent = _parent_map(parent_image)
    mapper = GrokRingComponentMapper(inspect_pair=lambda *_args: response)

    with pytest.raises(ComponentMappingUnresolved, match=detail):
        mapper(
            parent_map=parent,
            parent_image=parent_image,
            child_asset_id="run_preview",
            child_image=child_image,
            target_component_ids=(
                "center_stone.main",
                "prongs.center",
                "setting.center",
            ),
            component_path="stone.cut",
            instruction="Change the center cut.",
        )


def test_source_mapper_requires_the_released_coupled_region_but_allows_optional_unresolved():
    image = _png()
    mapper = GrokRingComponentMapper(
        inspect_single=lambda *_args: _observed(
            unresolved={"stone_group.side", "gallery.main"}
        ),
    )

    component_map = mapper.map_source(asset_id="ast_source", image=image)

    assert component_map.asset_id == "ast_source"
    assert component_map.component("center_stone.main").kind == "center_stone"
    assert component_map.component("prongs.center").kind == "prongs"
    assert component_map.component("setting.center").kind == "setting"
    assert next(
        item for item in component_map.components
        if item.component_id == "stone_group.side"
    ).resolution == "unresolved"
    assert all(item.parent_component_id is None for item in component_map.components)


def test_source_mapper_rejects_an_unresolved_cut_target():
    mapper = GrokRingComponentMapper(
        inspect_single=lambda *_args: _observed(unresolved={"prongs.center"}),
    )

    with pytest.raises(ComponentMappingUnresolved, match="coupled cut region"):
        mapper.map_source(asset_id="ast_source", image=_png())


def test_source_mapper_rejects_a_whole_frame_target_polygon():
    mapper = GrokRingComponentMapper(
        inspect_single=lambda *_args: _observed(
            override_box={"center_stone.main": (0.0, 0.0, 1.0, 1.0)}
        ),
    )

    with pytest.raises(
        ComponentMappingUnresolved,
        match="source center_stone semantic area",
    ):
        mapper.map_source(asset_id="ast_source", image=_png())


def test_source_mapper_rejects_background_covering_visible_jewelry():
    mapper = GrokRingComponentMapper(
        inspect_single=lambda *_args: _observed(
            override_box={"background.main": (0.0, 0.0, 1.0, 1.0)}
        ),
    )

    with pytest.raises(
        ComponentMappingUnresolved,
        match="source background semantic mask covers visible jewelry",
    ):
        mapper.map_source(asset_id="ast_source", image=_png())


def test_source_mapper_rejects_target_overlapping_unrelated_shank():
    mapper = GrokRingComponentMapper(
        inspect_single=lambda *_args: _observed(
            extra_box={"shank.main": (0.40, 0.23, 0.60, 0.51)}
        ),
    )

    with pytest.raises(
        ComponentMappingUnresolved,
        match="source cut target overlaps unrelated shank pixels",
    ):
        mapper.map_source(asset_id="ast_source", image=_png())


def test_child_mapper_rejects_a_whole_frame_target_polygon():
    parent_image = _png()
    mapper = GrokRingComponentMapper(
        inspect_pair=lambda *_args: _observed(
            override_box={
                "center_stone.main": (0.0, 0.0, 1.0, 1.0),
                "prongs.center": (0.0, 0.0, 1.0, 1.0),
                "setting.center": (0.0, 0.0, 1.0, 1.0),
            }
        ),
    )

    with pytest.raises(
        ComponentMappingUnresolved,
        match="child center_stone semantic area",
    ):
        mapper(
            parent_map=_parent_map(parent_image),
            parent_image=parent_image,
            child_asset_id="run_preview",
            child_image=_png(changed_box=(40, 25, 60, 45)),
            target_component_ids=(
                "center_stone.main",
                "prongs.center",
                "setting.center",
            ),
            component_path="stone.cut",
            instruction="Change the center cut.",
        )


def test_child_polygons_cannot_authorize_pixels_outside_the_source_envelope():
    parent_image = _png()
    mapper = GrokRingComponentMapper(
        inspect_pair=lambda *_args: _observed(
            extra_box={"setting.center": (0.25, 0.42, 0.30, 0.46)}
        ),
    )

    with pytest.raises(ComponentMappingUnresolved, match="source authorization"):
        mapper(
            parent_map=_parent_map(parent_image),
            parent_image=parent_image,
            child_asset_id="run_preview",
            child_image=_png(changed_box=(25, 42, 30, 46)),
            target_component_ids=(
                "center_stone.main",
                "prongs.center",
                "setting.center",
            ),
            component_path="stone.cut",
            instruction="Change the center cut.",
        )


def test_child_mapper_rejects_a_shifted_center_even_when_areas_remain_bounded():
    parent_image = _png()
    mapper = GrokRingComponentMapper(
        inspect_pair=lambda *_args: _observed(
            override_box={"center_stone.main": (0.45, 0.315, 0.65, 0.405)}
        ),
    )

    with pytest.raises(ComponentMappingUnresolved, match="child center stone"):
        mapper(
            parent_map=_parent_map(parent_image),
            parent_image=parent_image,
            child_asset_id="run_preview",
            child_image=_png(changed_box=(40, 25, 60, 45)),
            target_component_ids=(
                "center_stone.main",
                "prongs.center",
                "setting.center",
            ),
            component_path="stone.cut",
            instruction="Change the center cut.",
        )


def test_environment_composition_requires_verified_external_evidence(
    tmp_path,
    monkeypatch,
):
    evidence = tmp_path / "ring-cut-calibration.json"
    evidence.write_text('{"review":"approved frozen ring corpus"}')
    digest = hashlib.sha256(evidence.read_bytes()).hexdigest()
    monkeypatch.setenv("FACETTA_RING_STRUCTURAL_MAPPER_ENABLED", "true")
    monkeypatch.setenv(
        "FACETTA_RING_STRUCTURAL_MAPPER_EVIDENCE_PATH", str(evidence)
    )
    monkeypatch.setenv("FACETTA_RING_STRUCTURAL_MAPPER_EVIDENCE_SHA256", digest)
    monkeypatch.setenv("FACETTA_RING_STRUCTURAL_MAPPER_SUPPORTED_PATHS", "stone.cut")
    monkeypatch.setenv("XAI_KEY", "test-readiness-key")

    status = configure_attested_catalog_structural_mapper_from_environment()

    assert status.state == "ready"
    assert status.mapper_contract == GROK_RING_COMPONENT_MAPPER_CONTRACT
    assert status.calibration_evidence_sha256 == digest
    assert status.supported_paths == ("stone.cut",)

    evidence.write_text('{"review":"replaced after activation"}')
    drifted = catalog_component_targeting.catalog_structural_component_mapper_status()
    assert drifted.state == "unhealthy"
    assert drifted.reason_code == "structural_child_mapper_unhealthy"
    assert not catalog_component_targeting.catalog_structural_component_mapper_available(
        "stone.cut"
    )


def test_environment_composition_rejects_digest_or_path_scope_drift(
    tmp_path,
    monkeypatch,
):
    evidence = tmp_path / "ring-cut-calibration.json"
    evidence.write_text("approved")
    monkeypatch.setenv("FACETTA_RING_STRUCTURAL_MAPPER_ENABLED", "true")
    monkeypatch.setenv(
        "FACETTA_RING_STRUCTURAL_MAPPER_EVIDENCE_PATH", str(evidence)
    )
    monkeypatch.setenv("FACETTA_RING_STRUCTURAL_MAPPER_EVIDENCE_SHA256", "0" * 64)
    monkeypatch.setenv("FACETTA_RING_STRUCTURAL_MAPPER_SUPPORTED_PATHS", "stone.cut")

    with pytest.raises(ValueError, match="SHA-256 does not match"):
        configure_attested_catalog_structural_mapper_from_environment()

    monkeypatch.setenv(
        "FACETTA_RING_STRUCTURAL_MAPPER_EVIDENCE_SHA256",
        hashlib.sha256(evidence.read_bytes()).hexdigest(),
    )
    monkeypatch.setenv(
        "FACETTA_RING_STRUCTURAL_MAPPER_SUPPORTED_PATHS",
        "stone.cut,setting.style",
    )
    with pytest.raises(ValueError, match="exceed this structural mapper release"):
        configure_attested_catalog_structural_mapper_from_environment()

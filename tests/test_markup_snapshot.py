"""Secure schema-v1 annotation-canvas bridge into markup/read."""

from __future__ import annotations

import base64
import io
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageChops
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import facetta.api.assets as assets_mod
from facetta.db import Base, get_db
from facetta.main import app
from facetta.markup_snapshot import (
    MAX_SOURCE_IMAGE_DIMENSION,
    MarkupSnapshot,
    MarkupSnapshotImageError,
    composite_markup_snapshot,
)

from conftest import HALO_SPEC


def _png(
    color: tuple[int, int, int] = (238, 238, 238),
    size: tuple[int, int] = (321, 123),
) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, format="PNG")
    return output.getvalue()


def _annotation_base(annotation_id: str = "annotation-1") -> dict[str, object]:
    return {
        "id": annotation_id,
        "color": "#b42318",
        "stroke_width": 0.02,
    }


def _snapshot(*annotations: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "coordinate_space": "normalized_image",
        "source_uri": "asset://immutable-source",
        "annotations": list(annotations),
    }


def _rectangle(annotation_id: str = "annotation-1") -> dict[str, object]:
    return {
        **_annotation_base(annotation_id),
        "type": "rectangle",
        "start": {"x": 0.1, "y": 0.1},
        "end": {"x": 0.4, "y": 0.5},
    }


def _circle(annotation_id: str = "annotation-1") -> dict[str, object]:
    return {
        **_annotation_base(annotation_id),
        "type": "circle",
        "start": {"x": 0.2, "y": 0.2},
        "end": {"x": 0.6, "y": 0.7},
    }


def _arrow(annotation_id: str = "annotation-1") -> dict[str, object]:
    return {
        **_annotation_base(annotation_id),
        "type": "arrow",
        "start": {"x": 0.1, "y": 0.8},
        "end": {"x": 0.8, "y": 0.2},
    }


def _freehand(annotation_id: str = "annotation-1") -> dict[str, object]:
    return {
        **_annotation_base(annotation_id),
        "type": "freehand",
        "points": [
            {"x": 0.1, "y": 0.9},
            {"x": 0.4, "y": 0.6},
            {"x": 0.9, "y": 0.8},
        ],
    }


def _text(annotation_id: str = "annotation-1") -> dict[str, object]:
    return {
        **_annotation_base(annotation_id),
        "type": "text",
        "anchor": {"x": 0.25, "y": 0.25},
        "text": "Widen only this shoulder",
        "font_size": 0.08,
    }


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine, autoflush=False)

    def override() -> Iterator:
        session = test_session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override
    monkeypatch.setattr(
        assets_mod,
        "jewelry_render",
        lambda *args, **kwargs: (_png(), False),
    )
    monkeypatch.setattr(
        assets_mod,
        "check_design_consistency",
        lambda *args, **kwargs: {
            "consistent": True,
            "differences": [],
            "severity": "none",
            "checked": True,
        },
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


def _linked_asset(client: TestClient) -> tuple[str, str]:
    design = client.post(
        "/designs",
        json={"created_by": "usr_canvas", "spec": HALO_SPEC},
    )
    assert design.status_code == 201, design.text
    design_id = design.json()["design_id"]
    rendered = client.post(
        "/assets/render",
        json={
            "piece_description": "a halo ring for structured markup",
            "design_id": design_id,
            "created_by": "usr_canvas",
        },
    )
    assert rendered.status_code == 201, rendered.text
    return rendered.json()["asset_id"], design_id


@pytest.mark.parametrize(
    ("annotation", "expected_region"),
    [
        (_rectangle(), (15, 5, 35, 30)),
        (_circle(), (70, 18, 100, 40)),
        (_arrow(), (15, 95, 40, 130)),
        (_freehand(), (15, 110, 40, 135)),
        (_text(), (45, 20, 200, 80)),
    ],
    ids=["rectangle", "circle", "arrow", "freehand", "text"],
)
def test_each_canvas_tool_composites_visible_normalized_markup(
    annotation: dict[str, object],
    expected_region: tuple[int, int, int, int],
) -> None:
    clean = _png(size=(211, 137))
    snapshot = MarkupSnapshot.model_validate(_snapshot(annotation))

    marked = composite_markup_snapshot(clean, snapshot)

    clean_image = Image.open(io.BytesIO(clean)).convert("RGB")
    marked_image = Image.open(io.BytesIO(marked)).convert("RGB")
    assert marked[:8] == b"\x89PNG\r\n\x1a\n"
    assert marked_image.size == clean_image.size == (211, 137)
    difference = ImageChops.difference(clean_image, marked_image)
    assert difference.getbbox() is not None
    assert difference.crop(expected_region).getbbox() is not None
    assert marked_image.getpixel((210, 136)) == clean_image.getpixel((210, 136))


def test_compositor_preserves_source_dimensions_and_rejects_unsafe_sources() -> None:
    snapshot = MarkupSnapshot.model_validate(_snapshot(_rectangle()))
    marked = composite_markup_snapshot(_png(size=(321, 123)), snapshot)
    assert Image.open(io.BytesIO(marked)).size == (321, 123)

    with pytest.raises(MarkupSnapshotImageError, match="safely decodable"):
        composite_markup_snapshot(b"not an image", snapshot)

    too_wide = _png(size=(MAX_SOURCE_IMAGE_DIMENSION + 1, 1))
    with pytest.raises(MarkupSnapshotImageError, match="dimensions exceed"):
        composite_markup_snapshot(too_wide, snapshot)


def test_snapshot_validation_rejects_total_point_amplification() -> None:
    annotations = []
    points = [{"x": index / 1_023, "y": (index % 2)} for index in range(1_024)]
    for index in range(5):
        annotations.append({
            **_annotation_base(f"annotation-{index + 1}"),
            "type": "freehand",
            "points": points,
        })
    with pytest.raises(ValidationError, match="4096 total points"):
        MarkupSnapshot.model_validate(_snapshot(*annotations))


def test_endpoint_composites_all_tools_for_reader_without_creating_revision(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, bytes] = {}

    def reader(clean: bytes, marked: bytes) -> dict[str, object]:
        captured.update(clean=clean, marked=marked)
        return {
            "annotations": [{
                "region_description": "the marked shoulder",
                "change_instruction": "smooth only this shoulder",
                "target_section": "band",
                "handwriting": "smooth shoulder",
                "confidence": 0.98,
            }],
            "understood_as": "Smooth only the marked shoulder.",
            "needs_clarification": False,
            "clarification": "",
        }

    monkeypatch.setattr(assets_mod, "read_markup", reader)
    asset_id, design_id = _linked_asset(client)
    history_before = client.get(f"/assets/{asset_id}/history").json()["history"]
    versions_before = client.get(f"/designs/{design_id}").json()["versions"]
    snapshot = _snapshot(
        _circle("annotation-1"),
        _rectangle("annotation-2"),
        _arrow("annotation-3"),
        _freehand("annotation-4"),
        _text("annotation-5"),
    )

    response = client.post(
        f"/assets/{asset_id}/markup/read",
        json={"markup_snapshot": snapshot, "created_by": "usr_canvas"},
    )

    assert response.status_code == 200, response.text
    assert captured["clean"] == _png()
    clean_image = Image.open(io.BytesIO(captured["clean"])).convert("RGB")
    marked_image = Image.open(io.BytesIO(captured["marked"])).convert("RGB")
    assert marked_image.size == clean_image.size == (321, 123)
    assert ImageChops.difference(clean_image, marked_image).getbbox() is not None

    body = response.json()
    notes = client.get(f"/assets/{body['markup_asset_id']}").json()
    assert notes["capability"] == "MARKUP_NOTES"
    assert notes["revision"] is None
    assert notes["derived_from_revision"] == 1
    history_after = client.get(f"/assets/{asset_id}/history").json()["history"]
    assert len(history_after) == len(history_before) + 1
    assert len([item for item in history_after if item["revision"] is not None]) == 1
    assert client.get(f"/designs/{design_id}").json()["versions"] == versions_before


@pytest.mark.parametrize(
    "body",
    [
        {},
        {
            "marked_image_base64": base64.b64encode(_png()).decode(),
            "markup_snapshot": _snapshot(_rectangle()),
        },
        {"markup_snapshot": {**_snapshot(_rectangle()), "schema_version": 2}},
        {"markup_snapshot": {**_snapshot(_rectangle()), "schema_version": True}},
        {"markup_snapshot": {
            **_snapshot(_rectangle()),
            "source_uri": "a" * 4_097,
        }},
        {"markup_snapshot": {
            **_snapshot(_rectangle()),
            "coordinate_space": "pixels",
        }},
        {"markup_snapshot": _snapshot({
            **_rectangle(),
            "end": {"x": 1.01, "y": 0.5},
        })},
        {"markup_snapshot": _snapshot({
            **_rectangle(),
            "stroke_width": "0.02",
        })},
        {"markup_snapshot": _snapshot({
            **_annotation_base(),
            "type": "polygon",
            "points": [{"x": 0.1, "y": 0.1}, {"x": 0.2, "y": 0.2}],
        })},
        {"markup_snapshot": _snapshot(_rectangle(), _rectangle())},
        {"markup_snapshot": {**_snapshot(_rectangle()), "annotations": []}},
        {"markup_snapshot": _snapshot({
            **_text(),
            "text": "x" * 501,
        })},
        {"markup_snapshot": _snapshot({
            **_freehand(),
            "points": [{"x": 0.5, "y": 0.5}] * 1_025,
        })},
    ],
    ids=[
        "neither-input",
        "both-inputs",
        "wrong-schema",
        "boolean-schema",
        "oversized-source-uri",
        "wrong-coordinate-space",
        "out-of-bounds",
        "string-number",
        "unsupported-tool",
        "duplicate-id",
        "empty-annotations",
        "oversized-text",
        "oversized-freehand",
    ],
)
def test_endpoint_rejects_malformed_or_ambiguous_snapshot_inputs(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    body: dict[str, object],
) -> None:
    monkeypatch.setattr(
        assets_mod,
        "read_markup",
        lambda *args, **kwargs: pytest.fail("reader must not run"),
    )
    asset_id, _ = _linked_asset(client)

    response = client.post(f"/assets/{asset_id}/markup/read", json=body)

    assert response.status_code == 422

"""Secure schema-v1 annotation-canvas bridge into markup/read."""

from __future__ import annotations

import base64
import io
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageChops
from PIL.PngImagePlugin import PngInfo
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import facetta.api.assets as assets_mod
from facetta.db import Base, get_db
from facetta.main import app
from facetta.markup_snapshot import (
    MAX_SOURCE_IMAGE_DIMENSION,
    MARKUP_AUTHORIZATION_MASK_KEY,
    MarkupSnapshot,
    MarkupSnapshotImageError,
    composite_markup_snapshot,
)
from facetta.specagent import mask_from_markup

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


def _closed_freehand(annotation_id: str = "annotation-1") -> dict[str, object]:
    return {
        **_annotation_base(annotation_id),
        "type": "freehand",
        "points": [
            {"x": 0.2, "y": 0.2},
            {"x": 0.7, "y": 0.2},
            {"x": 0.7, "y": 0.7},
            {"x": 0.2, "y": 0.7},
            {"x": 0.2, "y": 0.2},
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


def _semantic_mask(annotation: dict[str, object]) -> Image.Image:
    clean = _png(size=(200, 200))
    snapshot = MarkupSnapshot.model_validate(_snapshot(annotation))
    marked = composite_markup_snapshot(clean, snapshot)
    encoded_mask = mask_from_markup(clean, marked)
    assert encoded_mask is not None
    return Image.open(io.BytesIO(encoded_mask)).convert("L")


@pytest.mark.parametrize(
    ("annotation", "interior"),
    [
        (_rectangle(), (50, 50)),
        (_circle(), (80, 90)),
        (_closed_freehand(), (90, 90)),
    ],
    ids=["rectangle", "circle", "closed-freehand"],
)
def test_area_tools_authorize_filled_interiors(
    annotation: dict[str, object],
    interior: tuple[int, int],
) -> None:
    mask = _semantic_mask(annotation)

    assert mask.getpixel(interior) == 255
    assert mask.getpixel((190, 190)) == 0


def test_arrow_authorizes_endpoint_hotspot_without_its_shaft() -> None:
    mask = _semantic_mask(_arrow())

    assert mask.getpixel((159, 40)) == 255
    assert mask.getpixel((90, 100)) == 0
    assert mask.getpixel((20, 159)) == 0


def test_arrow_hotspot_stays_bounded_at_maximum_valid_stroke_width() -> None:
    annotation = {**_arrow(), "stroke_width": 0.1}
    clean = _png(size=(1_000, 1_000))
    marked = composite_markup_snapshot(
        clean,
        MarkupSnapshot.model_validate(_snapshot(annotation)),
    )
    encoded_mask = mask_from_markup(clean, marked)
    assert encoded_mask is not None
    mask = Image.open(io.BytesIO(encoded_mask)).convert("L")

    assert mask.getpixel((799, 200)) == 255
    assert mask.getpixel((863, 200)) == 255
    assert mask.getpixel((870, 200)) == 0


def test_text_authorizes_anchor_hotspot_without_the_rendered_label() -> None:
    mask = _semantic_mask(_text())

    assert mask.getpixel((50, 50)) == 255
    assert mask.getpixel((150, 50)) == 0


def test_open_freehand_remains_valid_and_authorizes_its_stroke() -> None:
    mask = _semantic_mask(_freehand())

    assert mask.getpixel((20, 179)) == 255
    assert mask.getpixel((80, 80)) == 0


def test_corrupt_reserved_mask_metadata_fails_closed_without_ink_fallback() -> None:
    clean = _png(size=(200, 200))
    valid = composite_markup_snapshot(
        clean,
        MarkupSnapshot.model_validate(_snapshot(_arrow())),
    )
    image = Image.open(io.BytesIO(valid)).convert("RGBA")
    metadata = PngInfo()
    metadata.add_text(MARKUP_AUTHORIZATION_MASK_KEY, "not-valid-base64")
    corrupted = io.BytesIO()
    image.save(corrupted, format="PNG", pnginfo=metadata)

    assert mask_from_markup(clean, corrupted.getvalue()) is None


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


def test_local_instructions_do_not_change_composited_markup_pixels() -> None:
    clean = _png(size=(211, 137))
    without_instruction = MarkupSnapshot.model_validate(_snapshot(_rectangle()))
    with_instruction = MarkupSnapshot.model_validate(_snapshot({
        **_rectangle(),
        "instruction": "Change this shoulder to rose gold",
    }))

    assert composite_markup_snapshot(
        clean, without_instruction
    ) == composite_markup_snapshot(clean, with_instruction)


def test_snapshot_validation_counts_all_local_instruction_text() -> None:
    annotations = [
        {
            **_rectangle(f"annotation-{index + 1}"),
            "instruction": "x" * 401,
        }
        for index in range(5)
    ]

    with pytest.raises(ValidationError, match="2000 text characters"):
        MarkupSnapshot.model_validate(_snapshot(*annotations))


def test_endpoint_composites_all_tools_for_reader_without_creating_revision(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def reader(
        clean: bytes,
        marked: bytes,
        _form_elements=(),
        *,
        designer_instruction: str,
        ordered_local_instructions: tuple[str | None, ...],
    ) -> dict[str, object]:
        captured.update(
            clean=clean,
            marked=marked,
            designer_instruction=designer_instruction,
            ordered_local_instructions=ordered_local_instructions,
        )
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
        json={
            "markup_snapshot": snapshot,
            "instruction": "  Smooth only this shoulder  ",
            "created_by": "usr_canvas",
        },
    )

    assert response.status_code == 200, response.text
    assert captured["clean"] == _png()
    clean_image = Image.open(io.BytesIO(captured["clean"])).convert("RGB")
    marked_image = Image.open(io.BytesIO(captured["marked"])).convert("RGB")
    assert marked_image.size == clean_image.size == (321, 123)
    assert ImageChops.difference(clean_image, marked_image).getbbox() is not None
    assert captured["designer_instruction"] == "Smooth only this shoulder"
    assert captured["ordered_local_instructions"] == (
        None, None, None, None, "Widen only this shoulder",
    )

    body = response.json()
    notes = client.get(f"/assets/{body['markup_asset_id']}").json()
    assert notes["capability"] == "MARKUP_NOTES"
    assert notes["revision"] is None
    assert notes["derived_from_revision"] == 1
    history_after = client.get(f"/assets/{asset_id}/history").json()["history"]
    assert len(history_after) == len(history_before) + 1
    assert len([item for item in history_after if item["revision"] is not None]) == 1
    assert client.get(f"/designs/{design_id}").json()["versions"] == versions_before


def test_endpoint_forwards_two_local_text_edits_and_one_global_context_in_order(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def reader(
        _clean: bytes,
        _marked: bytes,
        _form_elements=(),
        *,
        designer_instruction: str,
        ordered_local_instructions: tuple[str | None, ...],
    ) -> dict[str, object]:
        captured["designer_instruction"] = designer_instruction
        captured["ordered_local_instructions"] = ordered_local_instructions
        return {
            "annotations": [{
                "region_description": "the left side diamond",
                "change_instruction": ordered_local_instructions[0],
                "target_section": "side_stones",
                "handwriting": ordered_local_instructions[0],
                "confidence": 0.99,
            }, {
                "region_description": "the right side diamond",
                "change_instruction": ordered_local_instructions[1],
                "target_section": "side_stones",
                "handwriting": ordered_local_instructions[1],
                "confidence": 0.99,
            }],
            "understood_as": "Apply both local edits; preserve everything else.",
            "needs_clarification": False,
            "clarification": "",
        }

    monkeypatch.setattr(assets_mod, "read_markup", reader)
    asset_id, _design_id = _linked_asset(client)
    first = {
        **_text("annotation-1"),
        "anchor": {"x": 0.25, "y": 0.5},
        "text": "Make this diamond yellow",
    }
    second = {
        **_text("annotation-2"),
        "anchor": {"x": 0.75, "y": 0.5},
        "text": "Make this diamond blue",
    }

    response = client.post(f"/assets/{asset_id}/markup/read", json={
        "markup_snapshot": _snapshot(first, second),
        "instruction": "Keep the ring identity and camera unchanged.",
        "created_by": "usr_canvas",
    })

    assert response.status_code == 200, response.text
    assert captured == {
        "designer_instruction": "Keep the ring identity and camera unchanged.",
        "ordered_local_instructions": (
            "Make this diamond yellow",
            "Make this diamond blue",
        ),
    }
    assert [
        item["change_instruction"] for item in response.json()["annotations"]
    ] == ["Make this diamond yellow", "Make this diamond blue"]


def test_endpoint_forwards_ordered_non_text_local_instructions_without_global_context(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def reader(
        _clean: bytes,
        _marked: bytes,
        _form_elements=(),
        *,
        designer_instruction: str | None,
        ordered_local_instructions: tuple[str | None, ...],
    ) -> dict[str, object]:
        captured["designer_instruction"] = designer_instruction
        captured["ordered_local_instructions"] = ordered_local_instructions
        return {
            "annotations": [{
                "region_description": "the left shoulder",
                "change_instruction": ordered_local_instructions[0],
                "target_section": "band",
                "handwriting": "",
                "confidence": 0.99,
            }, {
                "region_description": "the center setting",
                "change_instruction": ordered_local_instructions[1],
                "target_section": "setting",
                "handwriting": "",
                "confidence": 0.99,
            }],
            "understood_as": "Apply both ordered local edits.",
            "needs_clarification": False,
            "clarification": "",
        }

    monkeypatch.setattr(assets_mod, "read_markup", reader)
    asset_id, _design_id = _linked_asset(client)
    first = {
        **_rectangle("annotation-1"),
        "instruction": "Change this shoulder to rose gold",
    }
    second = {
        **_arrow("annotation-2"),
        "instruction": "Lower this setting slightly",
    }

    response = client.post(f"/assets/{asset_id}/markup/read", json={
        "markup_snapshot": _snapshot(first, second),
        "created_by": "usr_canvas",
    })

    assert response.status_code == 200, response.text
    assert captured == {
        "designer_instruction": None,
        "ordered_local_instructions": (
            "Change this shoulder to rose gold",
            "Lower this setting slightly",
        ),
    }
    assert [
        item["change_instruction"] for item in response.json()["annotations"]
    ] == [
        "Change this shoulder to rose gold",
        "Lower this setting slightly",
    ]


def test_apply_uses_snapshot_arrow_endpoint_mask_not_visible_shaft(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from facetta.image_agent import (
        CheckSeverity,
        ImageQualityReport,
        JewelryImageAgent,
        ProviderImage,
        QualityCheck,
        QualityVerdict,
    )

    captured: dict[str, bytes] = {}

    def reader(
        _clean: bytes,
        _marked: bytes,
        _form_elements=(),
        *,
        designer_instruction: str,
        ordered_local_instructions: tuple[str | None, ...],
    ) -> dict[str, object]:
        assert ordered_local_instructions == (None,)
        return {
            "annotations": [{
                "region_description": "the center diamond",
                "change_instruction": designer_instruction,
                "target_section": None,
                "handwriting": "",
                "confidence": 0.99,
            }],
            "understood_as": "Make only the center diamond pale yellow.",
            "needs_clarification": False,
            "clarification": "",
        }

    class Provider:
        def execute(self, plan, route, prompt, *, source_image, mask_bytes):
            assert mask_bytes is not None
            captured["mask"] = mask_bytes
            return ProviderImage(image_bytes=_png((210, 190, 130)))

    class PassingEvaluator:
        def evaluate(self, plan, candidate, *, source_image, mask_bytes):
            return ImageQualityReport(
                verdict=QualityVerdict.PASS,
                checks=(QualityCheck(
                    code="requested_change",
                    passed=True,
                    severity=CheckSeverity.HARD,
                    message="requested local color change is visible",
                ),),
                score=98,
            )

    monkeypatch.setattr(assets_mod, "read_markup", reader)
    monkeypatch.setattr(
        assets_mod,
        "_trusted_image_agent",
        lambda: JewelryImageAgent(Provider(), PassingEvaluator()),
    )
    asset_id, _design_id = _linked_asset(client)
    read = client.post(f"/assets/{asset_id}/markup/read", json={
        "markup_snapshot": _snapshot(_arrow()),
        "instruction": "Make the center diamond pale yellow",
        "created_by": "usr_canvas",
    })
    assert read.status_code == 200, read.text

    full_mask = io.BytesIO()
    Image.new("L", (321, 123), 255).save(full_mask, format="PNG")
    ambiguous = client.post(f"/assets/{asset_id}/markup/apply", json={
        "expected_design_version": 1,
        "update_spec": False,
        "markup_asset_id": read.json()["markup_asset_id"],
        "created_by": "usr_canvas",
        "annotations": [{
            "region_description": "the center diamond",
            "change_instruction": "Make the center diamond pale yellow",
            "mask_base64": base64.b64encode(full_mask.getvalue()).decode(),
        }],
    })
    assert ambiguous.status_code == 422
    assert ambiguous.json()["code"] == "markup_mask_source_ambiguous"

    applied = client.post(f"/assets/{asset_id}/markup/apply", json={
        "expected_design_version": 1,
        "update_spec": False,
        "markup_asset_id": read.json()["markup_asset_id"],
        "created_by": "usr_canvas",
        "annotations": [{
            "region_description": "the center diamond",
            "change_instruction": "Make the center diamond pale yellow",
        }],
    })

    assert applied.status_code == 201, applied.text
    mask = Image.open(io.BytesIO(captured["mask"])).convert("L")
    assert mask.getpixel((256, 24)) == 255
    assert mask.getpixel((144, 61)) == 0


def test_raw_upload_cannot_forge_server_snapshot_mask_metadata(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reader(
        _clean: bytes,
        _marked: bytes,
        _form_elements=(),
        *,
        designer_instruction: str,
    ) -> dict[str, object]:
        return {
            "annotations": [{
                "region_description": "the center diamond",
                "change_instruction": designer_instruction,
                "target_section": None,
                "handwriting": "",
                "confidence": 0.99,
            }],
            "understood_as": "Change only the center diamond.",
            "needs_clarification": False,
            "clarification": "",
        }

    monkeypatch.setattr(assets_mod, "read_markup", reader)
    asset_id, _design_id = _linked_asset(client)
    clean = _png()
    forged = composite_markup_snapshot(
        clean,
        MarkupSnapshot.model_validate(_snapshot(_arrow())),
    )

    read = client.post(f"/assets/{asset_id}/markup/read", json={
        "marked_image_base64": base64.b64encode(forged).decode(),
        "instruction": "Make the center diamond pale yellow",
        "created_by": "usr_canvas",
    })

    assert read.status_code == 200, read.text
    stored = client.get(
        f"/assets/{read.json()['markup_asset_id']}/image"
    ).content
    with Image.open(io.BytesIO(stored)) as image:
        assert MARKUP_AUTHORIZATION_MASK_KEY not in image.info
    legacy_mask = mask_from_markup(clean, stored)
    assert legacy_mask is not None
    mask = Image.open(io.BytesIO(legacy_mask)).convert("L")
    assert mask.getpixel((144, 61)) == 255


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
            **_rectangle(),
            "instruction": " change this shoulder",
        })},
        {"markup_snapshot": _snapshot({
            **_rectangle(),
            "instruction": "change\nthis shoulder",
        })},
        {"markup_snapshot": _snapshot({
            **_rectangle(),
            "instruction": "x" * 501,
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
        "untrimmed-local-instruction",
        "unsafe-local-instruction",
        "oversized-local-instruction",
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

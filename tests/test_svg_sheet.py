from pathlib import Path

import pytest

from facetta.spec import Spec
from facetta.svg_sheet import SheetUnsupported, render_sheet

GOLDEN_DIR = Path(__file__).parent / "golden"


def _assert_matches_golden(svg: str, name: str):
    golden = GOLDEN_DIR / name
    assert golden.exists(), f"golden file missing: {golden}"
    assert svg == golden.read_text(), (
        f"sheet no longer matches {name} — if the change is intentional, "
        f"regenerate the golden file and review the visual diff"
    )


def test_oval_sapphire_sheet_matches_golden(example_spec):
    svg = render_sheet(Spec.model_validate(example_spec))
    _assert_matches_golden(svg, "oval_sapphire_sheet.svg")


def test_round_diamond_sheet_matches_golden(round_spec):
    svg = render_sheet(Spec.model_validate(round_spec))
    _assert_matches_golden(svg, "round_diamond_sheet.svg")


def test_sheet_is_byte_stable(example_spec):
    spec = Spec.model_validate(example_spec)
    assert render_sheet(spec) == render_sheet(spec)


def test_exact_dimension_callouts_present(example_spec):
    svg = render_sheet(Spec.model_validate(example_spec))
    for text in (">8.6 mm<", ">6.4 mm<",      # stone L x W
                 ">1.8 mm<",                   # band width
                 ">⌀ 16.9 mm<",               # inner diameter
                 ">4.5 mm gallery<",           # gallery height
                 ">4.1 mm<"):                  # stone depth
        assert text in svg, f"missing callout {text}"


def test_title_block_contents(example_spec):
    svg = render_sheet(Spec.model_validate(example_spec))
    assert "dsn_8Kx2" in svg and "v3" in svg
    assert "2.00 ct sapphire, oval brilliant" in svg
    assert "usr_ana" in svg and "2026-07-02" in svg
    assert "SCALE 3:1" in svg


def test_unsupported_cut_fails_loudly(example_spec):
    example_spec["stone"]["cut"] = "cabochon"
    with pytest.raises(SheetUnsupported, match="cabochon"):
        render_sheet(Spec.model_validate(example_spec))


def test_sheet_endpoint_returns_svg(example_spec):
    from fastapi.testclient import TestClient

    from facetta.main import app

    response = TestClient(app).post("/specs/sheet.svg", json=example_spec)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert response.text.startswith("<svg")


def test_sheet_endpoint_rejects_invalid_spec(example_spec):
    from fastapi.testclient import TestClient

    from facetta.main import app

    example_spec["stone"]["carat"] = 9.9
    response = TestClient(app).post("/specs/sheet.svg", json=example_spec)
    assert response.status_code == 422

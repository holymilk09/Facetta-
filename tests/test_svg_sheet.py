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


# --- multi-stone templates ----------------------------------------------------


def _validated(raw):
    from facetta.validation import validate_spec
    from facetta.vocabulary import get_vocabulary

    result = validate_spec(Spec.model_validate(raw), get_vocabulary())
    assert result.ok, [i.msg for i in result.issues]
    return result.spec


def test_halo_ring_sheet_matches_golden(halo_spec):
    svg = render_sheet(_validated(halo_spec))
    _assert_matches_golden(svg, "halo_ring_sheet.svg")
    for text in (">6.4 mm<", ">8.6 mm<",             # center stone
                 ">15.2 mm halo<", ">17.4 mm halo<",  # halo outer envelope
                 ">2 mm<", ">⌀ 16.9 mm<"):            # band width, inner diameter
        assert text in svg, f"missing callout {text}"
    assert "8 × ⌀4.1 mm melee" in svg
    # 8 melee in the top view + 2 flanking in the side profile = 10 melee circles
    assert svg.count('r="6.15"') == 10


def test_love_bangle_sheet_matches_golden(bangle_spec):
    svg = render_sheet(_validated(bangle_spec))
    _assert_matches_golden(svg, "love_bangle_sheet.svg")
    for text in (">56 mm<", ">46 mm<",                # opening
                 ">6.1 mm<", ">2.6 mm<", ">2.9 mm<"):  # band section + stone
        assert text in svg, f"missing callout {text}"
    assert "8 × 2.9 mm princess" in svg
    assert svg.count("<rect") >= 9  # 8 stations + section band (+ page furniture)


def test_cluster_pendant_sheet_matches_golden(pendant_spec):
    svg = render_sheet(_validated(pendant_spec))
    _assert_matches_golden(svg, "cluster_pendant_sheet.svg")
    for text in (">7 mm<", ">9 mm<",       # emerald center
                 ">⌀ 5.5 mm<",             # sapphire drop
                 ">27.2 mm drop<",         # derived overall drop
                 ">4.5 mm<", ">3.4 mm<"):  # depths in side profile
        assert text in svg, f"missing callout {text}"
    assert "12 × ⌀2.3 mm melee" in svg
    assert "bail ⌀3.5 mm inside" in svg


def test_new_templates_are_byte_stable(halo_spec, bangle_spec, pendant_spec):
    for raw in (halo_spec, bangle_spec, pendant_spec):
        spec = _validated(raw)
        assert render_sheet(spec) == render_sheet(spec)


def test_bangle_requires_square_cut(bangle_spec):
    bangle_spec["stone"]["cut"] = "round_brilliant"
    with pytest.raises(SheetUnsupported, match="square cut"):
        render_sheet(Spec.model_validate(bangle_spec))


def test_halo_requires_melee_entry(halo_spec):
    halo_spec["side_stones"] = []
    with pytest.raises(SheetUnsupported, match="position 'halo'"):
        render_sheet(_validated(halo_spec))  # validation derives the inner diameter

import os
from pathlib import Path

import pytest

from facetta.spec import Spec
from facetta.svg_sheet import SheetUnsupported, render_sheet

GOLDEN_DIR = Path(__file__).parent / "golden"


def _assert_matches_golden(svg: str, name: str):
    golden = GOLDEN_DIR / name
    if os.environ.get("FACETTA_REGEN_GOLDEN"):  # intentional visual change
        golden.write_text(svg)
        return
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
    assert "2.00 ct Sapphire" in svg and "oval brilliant" in svg
    assert "usr_ana" in svg and "2026-07-02" in svg
    assert "SCALE 3:1" in svg
    assert "FACETTA" in svg  # maker's mark present with no designer branding


def test_branding_stamps_house_and_signature(example_spec):
    from facetta.svg_sheet import Branding

    svg = render_sheet(Spec.model_validate(example_spec),
                       branding=Branding(house="Maison Verre",
                                         signature="A. Rossi"))
    assert "Maison Verre" in svg          # the designer's house leads
    assert "A. Rossi" in svg and "SIGNED" in svg
    assert "made with FACETTA" in svg     # platform mark kept, subordinate


def test_bezel_setting_draws_a_collar_not_prongs():
    from facetta.concept import DesignRead, complete_design

    read = DesignRead(species="diamond", cut="round", center_length_mm=7,
                      center_width_mm=7, metal_material="platinum",
                      setting_style="bezel")
    bezel_spec, _ = complete_design(read, "bezel-set solitaire")
    svg = render_sheet(bezel_spec)
    assert 'fill-rule="evenodd"' in svg  # the collar annulus, top view

    prong_read = DesignRead(species="diamond", cut="round", center_length_mm=7,
                            center_width_mm=7, metal_material="platinum")
    prong_spec, _ = complete_design(prong_read, "prong solitaire")
    assert 'fill-rule="evenodd"' not in render_sheet(prong_spec)


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


def test_technical_drawing_endpoint_is_code_owned(example_spec):
    from fastapi.testclient import TestClient

    from facetta.main import app

    response = TestClient(app).post("/specs/technical-drawing.svg",
                                    json=example_spec,
                                    params={"piece_name": "The Solitaire"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert response.text.startswith("<svg")
    assert "<image" not in response.text          # official frame, pure code
    assert "The Solitaire" in response.text and "STONE SCHEDULE" in response.text


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
                 ">2 mm<", ">⌀ 16.9 mm<",             # band width, inner diameter
                 ">5.8 mm rise<",                     # front view: setting height
                 "FRONT VIEW"):
        assert text in svg, f"missing callout {text}"
    assert "8 × round brilliant ⌀4.1" in svg
    assert "EST. 3.1 g" in svg  # cast-weight estimate in the title block
    # 8 melee top view + 2 side profile + 2 front view = 12 melee circles
    assert svg.count('r="6.15"') == 12
    # sheet v2: gemstone key with circled refs and true totals
    assert "GEMSTONE KEY &amp; PRODUCTION NOTES" in svg
    assert "TOTAL SET WEIGHT" in svg
    assert "CONFIDENTIAL — FACTORY PRODUCTION ONLY" in svg


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
    assert "12 × ⌀2.3 mm diamond" in svg
    assert "bail ⌀3.5 mm inside" in svg


def test_new_templates_are_byte_stable(halo_spec, bangle_spec, pendant_spec):
    for raw in (halo_spec, bangle_spec, pendant_spec):
        spec = _validated(raw)
        assert render_sheet(spec) == render_sheet(spec)


def test_bangle_requires_square_cut(bangle_spec):
    bangle_spec["stone"]["cut"] = "round_brilliant"
    with pytest.raises(SheetUnsupported, match="square cut"):
        render_sheet(Spec.model_validate(bangle_spec))


def test_cuff_sheet_matches_golden(cuff_spec):
    svg = render_sheet(_validated(cuff_spec))
    _assert_matches_golden(svg, "cuff_sheet.svg")
    for text in (">58 mm<", ">48 mm<", ">25 mm gap<", ">5 mm<", ">2.2 mm<"):
        assert text in svg, f"missing callout {text}"
    assert "5 × 2.9 mm princess on the arc" in svg


def test_link_bracelet_sheet_matches_golden(link_spec):
    svg = render_sheet(_validated(link_spec))
    _assert_matches_golden(svg, "link_bracelet_sheet.svg")
    assert "14 articulated links" in svg
    assert ">pitch 12.0 mm<" in svg
    assert "LINK DETAIL — 6:1" in svg
    assert svg.count("rx=\"1.6\"") == 14  # every link drawn


def test_pendant_necklace_sheet_matches_golden(necklace_spec):
    svg = render_sheet(_validated(necklace_spec))
    _assert_matches_golden(svg, "pendant_necklace_sheet.svg")
    assert "PENDANT NECKLACE" in svg
    assert "cable · 450 mm · lobster clasp" in svg
    assert ">27.2 mm drop<" in svg  # drop still measured from the bail top


def test_loose_stone_sheet_matches_golden(loose_spec):
    svg = render_sheet(_validated(loose_spec))
    _assert_matches_golden(svg, "loose_stone_sheet.svg")
    for text in (">table 57% = 4.62 mm<", ">4.9 mm (60.5%)<", ">8.1 mm<"):
        assert text in svg, f"missing callout {text}"
    assert "girdle: medium" in svg
    assert 'laser inscription on girdle: "FCT-2141Z"' in svg
    assert "SCALE 8:1" in svg  # single-focus scale ladder picked 8:1
    assert "Loose stone — unmounted" in svg
    # GIA proportion callouts derived from the drawn geometry
    assert "crown " in svg and "pavilion " in svg and "°" in svg
    assert "culet pointed" in svg


def test_clarity_is_optional_finest_available(example_spec):
    example_spec["stone"].pop("clarity")
    svg = render_sheet(_validated(example_spec))
    assert "finest available" in svg  # title block notes the sourcing default


def test_facet_patterns_drawn_per_cut(example_spec, loose_spec, pendant_spec):
    # oval brilliant: 8-main / 8-star pattern -> a table polygon + many facet lines
    oval = render_sheet(_validated(example_spec))
    assert oval.count("<polygon") >= 2  # stone profile + face-up table
    # step cut: concentric rows
    pendant = render_sheet(_validated(pendant_spec))
    assert pendant.count("<polygon") >= 4  # outline + 3 step rows on the emerald


def test_halo_requires_melee_entry(halo_spec):
    halo_spec["side_stones"] = []
    with pytest.raises(SheetUnsupported, match="position 'halo'"):
        render_sheet(_validated(halo_spec))  # validation derives the inner diameter


def test_sunburst_halo_draws_every_stone_cut_true():
    """The ruby sunburst: 8 marquise petals as rotated marquise, 8 rounds
    nested between, 14 pavé per shoulder — counts from the spec, never taste."""
    import json

    spec = _validated(json.loads(
        (GOLDEN_DIR.parent.parent / "docs" / "examples" /
         "ruby_sunburst_ring.json").read_text()))
    svg = render_sheet(spec)
    top_view = svg[:svg.index("FRONT VIEW")]
    assert top_view.count("<g transform=\"rotate(") == 8   # marquise petals
    assert top_view.count(f'r="{2.5 / 2 * 3:.2f}"') == 8   # nested rounds
    assert "14 × ⌀1.1 mm pavé per shoulder" in svg
    assert svg.count(f'r="{1.15 / 2 * 3:.2f}"') == 14 + 28  # front col + side arcs
    assert "comfort-fit inner profile" in svg
    assert "TOTAL SET WEIGHT" in svg and ">5.33<" in svg


def test_sheet_dxf_has_no_grid_pollution():
    """The drafting grid lives in <defs>: the DXF export must not inherit a
    page of grid lines."""
    import json

    from fastapi.testclient import TestClient

    from facetta.main import app

    raw = json.loads((GOLDEN_DIR.parent.parent / "docs" / "examples" /
                      "ruby_sunburst_ring.json").read_text())
    response = TestClient(app).post("/specs/sheet.dxf", json=raw)
    assert response.status_code == 200
    # a gridded page would carry thousands of LINE entities; the drawing
    # itself carries a few hundred
    assert response.text.count("\nLINE\n") < 600

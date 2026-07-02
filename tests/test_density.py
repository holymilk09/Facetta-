import pytest

from facetta.density import check_density


def test_one_carat_round_diamond_benchmark():
    # The classic reference stone: 6.5 mm round brilliant diamond ≈ 1.00 ct
    result = check_density(
        sg=3.52, shape_factor=0.36,
        length_mm=6.5, width_mm=6.5, depth_mm=3.9, carat=1.0,
    )
    assert result.ok
    assert result.expected_carat == pytest.approx(1.04, abs=0.01)


def test_impossible_carat_fails_with_corrective_values():
    result = check_density(
        sg=3.52, shape_factor=0.36,
        length_mm=6.5, width_mm=6.5, depth_mm=3.9, carat=2.0,
    )
    assert not result.ok
    assert result.expected_carat == pytest.approx(1.04, abs=0.01)
    # the depth a real 2 ct stone of this footprint would need
    assert result.expected_depth_mm == pytest.approx(7.47, abs=0.05)
    assert "2.0" in result.message and "1.04" in result.message


def test_spec_schema_example_oval_sapphire_passes():
    # docs/SPEC_SCHEMA.md example: 2.0 ct oval sapphire, 8.6 x 6.4 x 4.1 mm
    result = check_density(
        sg=4.00, shape_factor=0.40,
        length_mm=8.6, width_mm=6.4, depth_mm=4.1, carat=2.0,
    )
    assert result.ok
    assert abs(result.deviation) <= 0.12


def test_tolerance_boundary():
    base = dict(sg=3.52, shape_factor=0.36, length_mm=6.5, width_mm=6.5, depth_mm=3.9)
    expected = check_density(**base, carat=1.0).expected_carat
    assert check_density(**base, carat=expected * 1.11).ok
    assert not check_density(**base, carat=expected * 1.13).ok

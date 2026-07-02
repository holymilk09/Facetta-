import pytest
from pydantic import ValidationError

from facetta.spec import Spec


def test_spec_schema_example_validates(example_spec):
    spec = Spec.model_validate(example_spec)
    assert spec.schema_version == 1
    assert spec.stone.dimensions_mm.length == 8.6
    assert spec.ring_size.inner_diameter_mm == 16.9


def test_string_typed_dimensions_rejected(example_spec):
    example_spec["stone"]["dimensions_mm"]["length"] = "8.6"
    with pytest.raises(ValidationError, match="length"):
        Spec.model_validate(example_spec)


def test_string_typed_carat_rejected(example_spec):
    example_spec["stone"]["carat"] = "2.0"
    with pytest.raises(ValidationError, match="carat"):
        Spec.model_validate(example_spec)


def test_band_width_outside_manufacturable_bounds_rejected(example_spec):
    example_spec["band"]["width_mm"] = 0.5
    with pytest.raises(ValidationError, match="width_mm"):
        Spec.model_validate(example_spec)


def test_prong_tip_outside_manufacturable_bounds_rejected(example_spec):
    example_spec["setting"]["prong_tip_mm"] = 2.4
    with pytest.raises(ValidationError, match="prong_tip_mm"):
        Spec.model_validate(example_spec)


def test_unknown_fields_rejected(example_spec):
    example_spec["stone"]["sparkliness"] = 11
    with pytest.raises(ValidationError, match="sparkliness"):
        Spec.model_validate(example_spec)


def test_schema_version_pinned(example_spec):
    example_spec["schema_version"] = 2
    with pytest.raises(ValidationError, match="schema_version"):
        Spec.model_validate(example_spec)

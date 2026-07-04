"""The presentation plate: sketch aesthetic, engineering truth.

The AI-sketch experiment drew ~15 stations on a 9-station bangle. These tests
pin the property that motivated the plate: the drawing always carries exactly
the spec's counts and the spec's numbers, rendered deterministically.
"""

import xml.etree.ElementTree as ET

from fastapi.testclient import TestClient

from facetta.main import app
from facetta.plate import render_presentation_plate
from facetta.spec import Spec
from facetta.validation import validate_spec
from facetta.vocabulary import get_vocabulary

client = TestClient(app)


def _render(raw: dict) -> str:
    result = validate_spec(Spec.model_validate(raw), get_vocabulary())
    assert result.ok, [i.msg for i in result.issues]
    return render_presentation_plate(result.spec)


def test_exact_station_count(bangle_spec):
    svg = _render(bangle_spec)
    stations = svg.count('<g transform="rotate(')
    assert stations == bangle_spec["stone"]["count"]  # the AI drew 15; we don't


def test_measurements_come_from_the_spec(bangle_spec):
    svg = _render(bangle_spec)
    br = bangle_spec["bracelet"]
    assert f"{br['inner_length_mm']:g} mm inside" in svg
    assert f"{br['inner_width_mm']:g} mm" in svg
    assert f"band {br['width_mm']:g} mm wide" in svg


def test_manifest_counts_and_no_species_stutter(bangle_spec):
    svg = _render(bangle_spec)
    count = bangle_spec["stone"]["count"]
    assert f"{count} ×" in svg          # the main stone group carries its count
    assert "spinel spinel" not in svg.lower()
    assert "diamond diamond" not in svg.lower()


def test_plate_is_deterministic_and_valid_xml(pendant_spec):
    a, b = _render(pendant_spec), _render(pendant_spec)
    assert a == b
    ET.fromstring(a)  # loud if any label broke the markup


def test_every_template_has_a_plate(example_spec, halo_spec, bangle_spec,
                                    cuff_spec, link_spec, pendant_spec,
                                    loose_spec):
    for raw in (example_spec, halo_spec, bangle_spec, cuff_spec, link_spec,
                pendant_spec, loose_spec):
        svg = _render(raw)
        assert "FACETTA" in svg and "drawn to specification" in svg


def test_plate_endpoint(example_spec):
    response = client.post("/specs/plate.svg", json=example_spec)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert "drawn to specification" in response.text

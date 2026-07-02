"""Multi-layer stacking: overlay sheets and nesting clearance."""

import copy

import pytest
from fastapi.testclient import TestClient

from facetta.main import app
from facetta.spec import Spec
from facetta.validation import nesting_clearance

client = TestClient(app)


def test_bangle_in_bangle_clearance(bangle_spec, outer_bangle_spec):
    c = nesting_clearance(Spec.model_validate(outer_bangle_spec), Spec.model_validate(bangle_spec))
    assert c.kind == "bangle_in_bangle"
    assert c.nests
    # (66 - (56 + 2*2.6)) / 2 and (56 - (46 + 2*2.6)) / 2
    assert c.clearance_x_mm == pytest.approx(2.4)
    assert c.clearance_y_mm == pytest.approx(2.4)


def test_argument_order_does_not_matter(bangle_spec, outer_bangle_spec):
    a = nesting_clearance(Spec.model_validate(outer_bangle_spec), Spec.model_validate(bangle_spec))
    b = nesting_clearance(Spec.model_validate(bangle_spec), Spec.model_validate(outer_bangle_spec))
    assert a == b


def test_ring_stack_height(example_spec, halo_spec):
    a = Spec.model_validate(example_spec)
    b = Spec.model_validate(halo_spec)
    c = nesting_clearance(a, b)
    assert c.kind == "ring_stack"
    assert c.stack_height_mm == pytest.approx(1.8 + 2.0)


def test_stack_endpoint_renders_overlay(bangle_spec, outer_bangle_spec):
    response = client.post("/specs/stack.svg",
                           json={"spec_a": outer_bangle_spec, "spec_b": bangle_spec})
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("image/svg+xml")
    svg = response.text
    assert "STACKING SHEET — NESTING CLEARANCE" in svg
    assert ">2.4 mm<" in svg
    assert "dsn_outer_bangle v1" in svg and "dsn_bangle v1" in svg


def test_non_nesting_pair_rejected_with_negative_clearance(bangle_spec, outer_bangle_spec):
    # shrink the outer piece until the inner one cannot fit
    outer_bangle_spec["bracelet"]["inner_length_mm"] = 58.0
    outer_bangle_spec["bracelet"]["inner_width_mm"] = 48.0
    response = client.post("/specs/stack.svg",
                           json={"spec_a": outer_bangle_spec, "spec_b": bangle_spec})
    assert response.status_code == 422
    body = response.json()
    assert "do not nest" in body["detail"]
    assert body["clearance"]["clearance_y_mm"] < 0


def test_unsupported_pair_rejected(bangle_spec, pendant_spec):
    response = client.post("/specs/stack.svg",
                           json={"spec_a": bangle_spec, "spec_b": pendant_spec})
    assert response.status_code == 422
    assert "stacking supports" in response.json()["detail"]


def test_stack_sheet_is_deterministic(bangle_spec, outer_bangle_spec):
    payload = {"spec_a": outer_bangle_spec, "spec_b": bangle_spec}
    assert client.post("/specs/stack.svg", json=payload).text == \
        client.post("/specs/stack.svg", json=payload).text
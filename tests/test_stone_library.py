"""The curated stone library and the mount-only swap rule."""

import copy
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from facetta.db import Base, get_db
from facetta.main import app


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False)

    def override():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


SMALLER_DIAMOND = {
    "species": "diamond", "cut": "oval_brilliant", "carat": 1.1,
    "dimensions_mm": {"length": 7.8, "width": 5.8, "depth": 3.7},
    "color": {"trade": "D", "gia": "colorless, highest grade"},
    "lab": "GIA", "inscription": "GIA-2141556890", "phenomena": [],
}


def test_save_and_list_stones(client):
    r = client.post("/stones", json={"created_by": "usr_ana",
                                     "label": "Client stone — 1.10 ct oval D",
                                     "stone": SMALLER_DIAMOND})
    assert r.status_code == 201, r.text
    assert r.json()["stone_id"].startswith("stn_")
    listing = client.get("/stones", params={"created_by": "usr_ana"}).json()["stones"]
    assert len(listing) == 1 and listing[0]["stone"]["lab"] == "GIA"


def test_saved_stones_are_validated(client):
    impossible = dict(SMALLER_DIAMOND, carat=9.9)
    r = client.post("/stones", json={"created_by": "usr_ana", "label": "bad",
                                     "stone": impossible})
    assert r.status_code == 422  # density check rejects it at filing time


def test_swap_changes_mounting_only(client, halo_spec):
    """The founder rule: trying a different stone in a design resizes the
    mounting (halo envelope hugging the stone) and NOTHING else — band width,
    inner diameter, melee, metal all stay exactly as designed."""
    from facetta.spec import Spec
    from facetta.svg_sheet import render_sheet
    from facetta.validation import validate_spec
    from facetta.vocabulary import get_vocabulary

    stone_id = client.post("/stones", json={
        "created_by": "usr_ana", "label": "alt oval", "stone": SMALLER_DIAMOND,
    }).json()["stone_id"]

    r = client.post("/specs/swap-stone", json={"spec": halo_spec,
                                               "stone_id": stone_id})
    assert r.status_code == 200, r.text
    swapped = r.json()

    original = validate_spec(Spec.model_validate(copy.deepcopy(halo_spec)),
                             get_vocabulary()).spec.model_dump(mode="json")
    # only the stone moved
    assert swapped["stone"]["dimensions_mm"]["width"] == 5.8
    assert swapped["band"] == original["band"]
    assert swapped["ring_size"] == original["ring_size"]
    assert swapped["side_stones"] == original["side_stones"]
    assert swapped["metal"] == original["metal"]

    # and on paper: the hoop and band are byte-identical, the halo envelope adapts
    svg_a = render_sheet(Spec.model_validate(original))
    svg_b = render_sheet(Spec.model_validate(swapped))
    hoop_r = original["ring_size"]["inner_diameter_mm"] / 2 * 3  # x SCALE
    hoop = re.compile(rf'<circle[^>]*r="{hoop_r:.2f}"')
    assert hoop.search(svg_a) and hoop.search(svg_b)
    halo_a = re.search(r">([\d.]+) mm halo<", svg_a).group(1)
    halo_b = re.search(r">([\d.]+) mm halo<", svg_b).group(1)
    assert halo_a != halo_b  # the mounting hugged the new stone


def test_swap_that_breaks_fit_fails_loudly(client, halo_spec):
    # a much smaller center shrinks the halo perimeter: 8 melee no longer fit
    tiny = dict(SMALLER_DIAMOND, carat=0.73,  # density-true for 6.5 x 5 x 3.2
                dimensions_mm={"length": 6.5, "width": 5.0, "depth": 3.2})
    stone_id = client.post("/stones", json={
        "created_by": "usr_ana", "label": "too small for this halo", "stone": tiny,
    }).json()["stone_id"]
    r = client.post("/specs/swap-stone", json={"spec": halo_spec,
                                               "stone_id": stone_id})
    assert r.status_code == 422
    assert any("fit" in d["msg"] or "halo" in d["msg"]
               for d in r.json()["detail"])


def test_lab_prefix_on_gem_sheet(client, loose_spec):
    loose_spec["stone"]["lab"] = "GIA"
    r = client.post("/specs/sheet.svg", json=loose_spec)
    assert 'laser inscription on girdle: GIA "FCT-2141Z"' in r.text

    loose_spec["stone"]["lab"] = "MallKiosk"
    r = client.post("/specs/validate", json=loose_spec)
    assert r.status_code == 422
    assert "GIA" in str(r.json())

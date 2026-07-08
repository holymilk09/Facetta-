"""The version diff: what changed between two immutable specs, in plain words.

Structural (compares the specs, not an agent's self-report), so it can never
mis-state a change — the safety net for a designer who moves a dimension and
forgets the previous correct value.
"""

from facetta.specdiff import diff_specs, summarize_changes


def _spec() -> dict:
    return {
        "design_id": "dsn_x", "version": 1, "created_by": "u", "created_at": "t",
        "schema_version": 1, "mode": "pro", "jewelry_type": "ring",
        "template": "solitaire",
        "stone": {"species": "diamond", "cut": "round", "carat": 2.0,
                  "dimensions_mm": {"length": 8.1, "width": 8.1, "depth": 4.9}},
        "band": {"profile": "comfort", "width_mm": 2.2, "thickness_mm": 1.6},
        "side_stones": [
            {"species": "diamond", "cut": "round", "carat": 0.01, "count": 20,
             "dimensions_mm": {"length": 1.4, "width": 1.4, "depth": 0.8}}],
    }


def test_no_changes_is_empty():
    assert diff_specs(_spec(), _spec()) == []
    assert summarize_changes([]) == ""


def test_reports_a_dimension_change_before_and_after():
    a = _spec()
    b = _spec()
    b["band"]["width_mm"] = 2.0
    changes = diff_specs(a, b)
    assert len(changes) == 1
    c = changes[0]
    assert c["path"] == "band.width_mm"
    assert c["label"] == "band width"
    assert c["from"] == "2.2 mm" and c["to"] == "2 mm"
    assert c["kind"] == "changed"
    assert summarize_changes(changes) == "band width 2.2 mm → 2 mm"


def test_carat_carries_ct_units_and_stone_label():
    a, b = _spec(), _spec()
    b["stone"]["carat"] = 2.4
    (c,) = diff_specs(a, b)
    assert c["label"] == "center stone weight"
    assert c["from"] == "2 ct" and c["to"] == "2.4 ct"


def test_center_stone_dimension_label():
    a, b = _spec(), _spec()
    b["stone"]["dimensions_mm"]["length"] = 8.3
    (c,) = diff_specs(a, b)
    assert c["label"] == "center stone length"
    assert c["from"] == "8.1 mm" and c["to"] == "8.3 mm"


def test_side_stone_group_is_numbered_from_one():
    a, b = _spec(), _spec()
    b["side_stones"][0]["count"] = 24
    (c,) = diff_specs(a, b)
    assert c["label"] == "side stone 1 count"
    assert c["from"] == "20" and c["to"] == "24"       # count has no unit


def test_metadata_and_geometry_are_ignored():
    a, b = _spec(), _spec()
    b["version"] = 2
    b["created_at"] = "later"
    b["composition"] = {"clusters": [[0, 0, 1]]}
    assert diff_specs(a, b) == []


def test_added_and_removed_sections():
    a, b = _spec(), _spec()
    del b["band"]
    changes = {c["path"]: c for c in diff_specs(a, b)}
    assert changes["band.width_mm"]["kind"] == "removed"
    assert changes["band.width_mm"]["to"] == "—"

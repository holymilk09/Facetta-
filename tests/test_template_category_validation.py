from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

from conftest import EXAMPLE_SPEC
from facetta.main import app
from facetta.spec import Spec
from facetta.validation import TEMPLATE_JEWELRY_TYPES, validate_spec
from facetta.vocabulary import get_vocabulary


EXPECTED_TEMPLATE_JEWELRY_TYPES = {
    "solitaire_prong": frozenset({"ring"}),
    "halo_prong": frozenset({"ring"}),
    "leaf_shoulder_prong": frozenset({"ring"}),
    "three_stone_prong": frozenset({"ring"}),
    "multi_stone_prong": frozenset({"ring"}),
    "love_bangle": frozenset({"bracelet"}),
    "cuff": frozenset({"bracelet"}),
    "link_bracelet": frozenset({"bracelet"}),
    "cluster_pendant": frozenset({"necklace", "pendant"}),
    "loose_stone": frozenset({"loose_stone"}),
    "leaf_spray_brooch": frozenset({"brooch"}),
    "deco_drop_earring": frozenset({"earring"}),
}


def _category_issues(*, template: str, jewelry_type: str):
    raw = copy.deepcopy(EXAMPLE_SPEC)
    raw["template"] = template
    raw["jewelry_type"] = jewelry_type
    result = validate_spec(Spec.model_validate(raw), get_vocabulary())
    return [issue for issue in result.issues if issue.loc == ("jewelry_type",)]


def test_every_current_factory_template_has_an_explicit_category_contract():
    assert TEMPLATE_JEWELRY_TYPES == EXPECTED_TEMPLATE_JEWELRY_TYPES


@pytest.mark.parametrize(
    ("template", "jewelry_type"),
    [
        (template, jewelry_type)
        for template, allowed in EXPECTED_TEMPLATE_JEWELRY_TYPES.items()
        for jewelry_type in sorted(allowed)
    ],
)
def test_current_template_accepts_its_supported_category(
    template: str,
    jewelry_type: str,
):
    assert _category_issues(
        template=template,
        jewelry_type=jewelry_type,
    ) == []


@pytest.mark.parametrize(
    ("template", "wrong_category", "expected_categories"),
    [
        ("solitaire_prong", "necklace", ["ring"]),
        ("love_bangle", "ring", ["bracelet"]),
        ("cluster_pendant", "ring", ["necklace", "pendant"]),
        ("loose_stone", "earring", ["loose_stone"]),
        ("leaf_spray_brooch", "bracelet", ["brooch"]),
        ("deco_drop_earring", "pendant", ["earring"]),
    ],
)
def test_known_template_rejects_mismatched_category(
    template: str,
    wrong_category: str,
    expected_categories: list[str],
):
    issues = _category_issues(
        template=template,
        jewelry_type=wrong_category,
    )

    assert len(issues) == 1
    issue = issues[0]
    assert issue.type == "template"
    assert issue.valid_options == expected_categories
    assert issue.expected == {
        "template": template,
        "jewelry_type": expected_categories,
    }
    assert wrong_category in issue.msg


def test_unknown_legacy_template_remains_schema_readable():
    raw = copy.deepcopy(EXAMPLE_SPEC)
    raw["template"] = "legacy_custom_template"
    spec = Spec.model_validate(raw)

    assert spec.template == "legacy_custom_template"
    assert _category_issues(
        template=spec.template,
        jewelry_type=spec.jewelry_type,
    ) == []


def test_validate_endpoint_rejects_known_template_category_mismatch():
    raw = copy.deepcopy(EXAMPLE_SPEC)
    raw["jewelry_type"] = "necklace"

    response = TestClient(app).post("/specs/validate", json=raw)

    assert response.status_code == 422
    category_issue = next(
        issue for issue in response.json()["detail"]
        if issue["loc"] == ["jewelry_type"]
    )
    assert category_issue["type"] == "template"
    assert category_issue["valid_options"] == ["ring"]

from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from facetta.design_form import (
    DesignForm,
    DesignFormElement,
    DesignFormRegion,
    DimensionedProfileDefinition,
    DimensionedProfilePath,
    DimensionedProfilePoint,
    NormalizedPoint,
    NormalizedPolygon,
    VisualReferenceOnlyDefinition,
    apply_scoped_form_element,
    unresolved_form_factory_blockers,
)
from facetta.spec import Spec


def _polygon(*, x_offset: float = 0.0) -> NormalizedPolygon:
    return NormalizedPolygon(points=(
        NormalizedPoint(x=0.10 + x_offset, y=0.20),
        NormalizedPoint(x=0.30 + x_offset, y=0.20),
        NormalizedPoint(x=0.28 + x_offset, y=0.45),
        NormalizedPoint(x=0.12 + x_offset, y=0.45),
    ))


def _element(
    element_id: str = "shoulder.left",
    *,
    description: str = "Three stepped Art Deco planes rising to the center.",
    asset_id: str = "ast_imported_reference",
    asset_sha256: str = "a" * 64,
    x_offset: float = 0.0,
) -> DesignFormElement:
    return DesignFormElement(
        element_id=element_id,
        role="shoulder_architecture",
        label="Left shoulder",
        confirmed_form_description=description,
        symmetry="bilateral",
        instance_count=2,
        regions=(DesignFormRegion(
            view="three-quarter",
            polygons=(_polygon(x_offset=x_offset),),
        ),),
        definition=VisualReferenceOnlyDefinition(
            kind="visual_reference_only",
            asset_id=asset_id,
            asset_sha256=asset_sha256,
        ),
    )


def test_legacy_spec_defaults_to_an_empty_design_form(example_spec):
    legacy = copy.deepcopy(example_spec)
    legacy.pop("design_form", None)

    spec = Spec.model_validate(legacy)

    assert spec.design_form == DesignForm()
    assert spec.design_form.model_dump(mode="json") == {"elements": []}


def test_form_element_records_confirmed_reference_and_exact_regions():
    element = _element()

    dumped = element.model_dump(mode="json")

    assert dumped["element_id"] == "shoulder.left"
    assert dumped["role"] == "shoulder_architecture"
    assert dumped["instance_count"] == 2
    assert dumped["definition"] == {
        "kind": "visual_reference_only",
        "asset_id": "ast_imported_reference",
        "asset_sha256": "a" * 64,
    }
    assert dumped["regions"][0]["view"] == "three-quarter"
    assert dumped["regions"][0]["polygons"][0]["points"][0] == {
        "x": 0.1,
        "y": 0.2,
    }


@pytest.mark.parametrize("element_id", [
    "Shoulder.Left",
    "shoulder left",
    "shoulder/left",
    "_shoulder",
    "shoulder..left",
    "",
])
def test_invalid_or_unstable_element_ids_are_rejected(element_id):
    with pytest.raises(ValidationError):
        _element(element_id)


@pytest.mark.parametrize("asset_id", [
    "asset with spaces",
    "asset/path",
    "@asset",
    "",
])
def test_invalid_asset_ids_are_rejected(asset_id):
    with pytest.raises(ValidationError):
        _element(asset_id=asset_id)


@pytest.mark.parametrize("digest", [
    "a" * 63,
    "a" * 65,
    "A" * 64,
    "g" * 64,
    "sha256:" + "a" * 64,
])
def test_reference_requires_exact_canonical_sha256(digest):
    with pytest.raises(ValidationError):
        _element(asset_sha256=digest)


@pytest.mark.parametrize("points", [
    # Outside normalized image space.
    ((-0.1, 0.1), (0.3, 0.1), (0.2, 0.4)),
    # A repeated/explicit closing vertex is not a canonical exact polygon.
    ((0.1, 0.1), (0.3, 0.1), (0.2, 0.4), (0.1, 0.1)),
    # Collinear vertices enclose no region.
    ((0.1, 0.1), (0.2, 0.2), (0.3, 0.3)),
    # Self-intersecting bow tie.
    ((0.1, 0.1), (0.4, 0.4), (0.1, 0.4), (0.4, 0.1)),
])
def test_invalid_normalized_polygon_regions_are_rejected(points):
    with pytest.raises(ValidationError):
        NormalizedPolygon(points=tuple(
            NormalizedPoint(x=x, y=y) for x, y in points
        ))


def test_each_element_has_exactly_one_region_group_per_view():
    region = DesignFormRegion(
        view="top",
        polygons=(_polygon(),),
    )
    with pytest.raises(ValidationError, match="each view only once"):
        DesignFormElement(
            element_id="shoulder.pair",
            role="shoulder_architecture",
            label="Shoulder pair",
            confirmed_form_description="Mirrored stepped shoulders.",
            symmetry="bilateral",
            instance_count=2,
            regions=(region, region),
            definition=VisualReferenceOnlyDefinition(
                kind="visual_reference_only",
                asset_id="ast_reference",
                asset_sha256="b" * 64,
            ),
        )


def test_duplicate_form_element_ids_are_rejected():
    with pytest.raises(ValidationError, match="IDs must be unique"):
        DesignForm(elements=(_element(), _element()))


def test_definition_is_discriminated_and_rejects_dimension_invention():
    raw = _element().model_dump(mode="json")
    raw["definition"] = {
        "kind": "dimensioned_contour",
        "asset_id": "ast_reference",
        "asset_sha256": "a" * 64,
        "width_mm": 4.2,
    }

    with pytest.raises(ValidationError):
        DesignFormElement.model_validate(raw)

    raw["definition"] = {
        "kind": "visual_reference_only",
        "asset_id": "ast_reference",
        "asset_sha256": "a" * 64,
        "inferred_width_mm": 4.2,
    }
    with pytest.raises(ValidationError):
        DesignFormElement.model_validate(raw)


def _dimensioned_definition() -> DimensionedProfileDefinition:
    return DimensionedProfileDefinition(
        kind="dimensioned_profile",
        scope="full_assembly",
        view="front",
        paths=(DimensionedProfilePath(
            path_id="assembly.outline",
            purpose="outline",
            closed=True,
            points=(
                DimensionedProfilePoint(x_mm=-10.0, y_mm=-20.0),
                DimensionedProfilePoint(x_mm=10.0, y_mm=-20.0),
                DimensionedProfilePoint(x_mm=8.0, y_mm=20.0),
                DimensionedProfilePoint(x_mm=-8.0, y_mm=20.0),
            ),
        ),),
        profile_thickness_mm=1.4,
        dimension_status="designer_confirmed_estimate",
        source_asset_id="ast_confirmed_drawing",
        source_asset_sha256="c" * 64,
        confirmed_by="usr_designer",
        confirmed_at="2026-07-12T10:30:00Z",
        manufacturing_notes=(
            "Front outline and thickness confirmed for prototype review."
        ),
    )


def test_dimensioned_full_assembly_profile_resolves_visual_form_blocker():
    visual = _element()
    dimensioned = visual.model_copy(update={
        "definition": _dimensioned_definition(),
    })

    form = DesignForm(elements=(dimensioned,))

    assert unresolved_form_factory_blockers(form) == ()
    dumped = form.model_dump(mode="json")["elements"][0]["definition"]
    assert dumped["kind"] == "dimensioned_profile"
    assert dumped["dimension_status"] == "designer_confirmed_estimate"
    assert dumped["paths"][0]["points"][0] == {
        "x_mm": -10.0,
        "y_mm": -20.0,
    }


@pytest.mark.parametrize(
    "mutate, message",
    [
        (
            lambda value: value["paths"][0].update({"closed": False}),
            "outline must be closed",
        ),
        (
            lambda value: value["paths"][0].update({
                "points": [
                    {"x_mm": 0.0, "y_mm": 0.0},
                    {"x_mm": 1.0, "y_mm": 1.0},
                    {"x_mm": 2.0, "y_mm": 2.0},
                ],
            }),
            "must enclose area",
        ),
        (
            lambda value: value["paths"][0].update({
                "points": [
                    {"x_mm": 0.0, "y_mm": 0.0},
                    {"x_mm": 4.0, "y_mm": 0.0},
                    {"x_mm": 0.0, "y_mm": 4.0},
                    {"x_mm": 4.0, "y_mm": 4.0},
                    {"x_mm": 2.0, "y_mm": 1.0},
                ],
            }),
            "must not self-intersect",
        ),
        (
            lambda value: value.update({"confirmed_at": "2026-07-12T10:30:00"}),
            "include timezone",
        ),
    ],
)
def test_invalid_dimensioned_profile_cannot_claim_factory_geometry(
    mutate,
    message,
):
    raw = _dimensioned_definition().model_dump(mode="json")
    mutate(raw)
    with pytest.raises(ValidationError, match=message):
        DimensionedProfileDefinition.model_validate(raw)


def test_scoped_apply_adds_exactly_one_element_to_legacy_empty_form():
    current = DesignForm()
    proposed = DesignForm(elements=(_element(),))

    result = apply_scoped_form_element(
        current,
        proposed,
        element_id="shoulder.left",
    )

    assert current == DesignForm()
    assert result.elements == proposed.elements


def test_scoped_apply_replaces_only_target_and_ignores_proposal_drift():
    target = _element()
    frozen = _element(
        "gallery.rail",
        description="A continuous scalloped gallery rail.",
        asset_id="ast_gallery",
        asset_sha256="b" * 64,
        x_offset=0.4,
    )
    current = DesignForm(elements=(target, frozen))
    changed_target = _element(
        description="A smooth uninterrupted shoulder taper.",
        asset_id="ast_accepted_edit",
        asset_sha256="c" * 64,
    )
    drifted_frozen = _element(
        "gallery.rail",
        description="Invented unrelated gallery change.",
        asset_id="ast_drift",
        asset_sha256="d" * 64,
        x_offset=0.4,
    )
    invented = _element(
        "motif.unrequested",
        description="Unrequested new motif.",
        asset_id="ast_drift",
        asset_sha256="d" * 64,
        x_offset=0.6,
    )
    proposed = DesignForm(elements=(
        drifted_frozen,
        invented,
        changed_target,
    ))

    result = apply_scoped_form_element(
        current,
        proposed,
        element_id="shoulder.left",
    )

    assert tuple(element.element_id for element in result.elements) == (
        "shoulder.left",
        "gallery.rail",
    )
    assert result.elements[0] == changed_target
    assert result.elements[1] == frozen
    assert current.elements == (target, frozen)


def test_scoped_apply_rejects_invalid_missing_and_noop_targets():
    element = _element()
    current = DesignForm(elements=(element,))

    with pytest.raises(ValidationError):
        apply_scoped_form_element(
            current,
            current,
            element_id="Shoulder Left",
        )
    with pytest.raises(ValueError, match="does not contain target"):
        apply_scoped_form_element(
            current,
            DesignForm(),
            element_id="shoulder.left",
        )
    with pytest.raises(ValueError, match="no confirmed form change"):
        apply_scoped_form_element(
            current,
            current,
            element_id="shoulder.left",
        )


def test_reference_defined_contour_reports_unresolved_factory_blocker():
    form = DesignForm(elements=(_element(),))

    blockers = unresolved_form_factory_blockers(form)

    assert len(blockers) == 1
    assert blockers[0].code == "visual_reference_not_dimensioned"
    assert blockers[0].element_id == "shoulder.left"
    assert "not dimensioned factory geometry" in blockers[0].message
    assert "CAD" in blockers[0].required_resolution
    assert unresolved_form_factory_blockers(DesignForm()) == ()

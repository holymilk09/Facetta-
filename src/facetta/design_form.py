"""Pure domain contract for reference-defined jewelry form elements.

``DesignForm`` records *what a designer confirmed visually* and the exact
image-space regions where that form appears.  It is deliberately not a CAD
profile or a set of inferred factory dimensions.  A reference-defined shoulder,
metal motif, chain silhouette, or other arbitrary contour therefore remains a
factory blocker until a later, explicit dimensioned/CAD contract resolves it.

The models are immutable and contain no persistence or provider behavior.  The
scoped apply function is likewise pure: it adds or replaces exactly one target
element and preserves every unrelated element from the current record.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)


class _FrozenStrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


FormElementId: TypeAlias = Annotated[
    str,
    Field(
        strict=True,
        min_length=1,
        # Checklist response keys use ``design_form:<element_id>`` and are
        # persisted in a 48-character legacy column. 32 keeps the complete
        # stable identity lossless across that public approval boundary.
        max_length=32,
        pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$",
    ),
]
FormRole: TypeAlias = Annotated[
    str,
    Field(
        strict=True,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$",
    ),
]
FormView: TypeAlias = Annotated[
    str,
    Field(
        strict=True,
        min_length=1,
        max_length=48,
        pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$",
    ),
]
AssetId: TypeAlias = Annotated[
    str,
    Field(
        strict=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]
Sha256Hex: TypeAlias = Annotated[
    str,
    Field(strict=True, pattern=r"^[0-9a-f]{64}$"),
]
NormalizedCoordinate: TypeAlias = Annotated[
    float,
    Field(strict=True, ge=0.0, le=1.0),
]


class NormalizedPoint(_FrozenStrictModel):
    """One coordinate in the referenced image, normalized to ``[0, 1]``."""

    x: NormalizedCoordinate
    y: NormalizedCoordinate


def _cross(
    first: NormalizedPoint,
    second: NormalizedPoint,
    third: NormalizedPoint,
) -> float:
    return ((second.x - first.x) * (third.y - first.y)
            - (second.y - first.y) * (third.x - first.x))


def _point_on_segment(
    point: NormalizedPoint,
    start: NormalizedPoint,
    end: NormalizedPoint,
) -> bool:
    epsilon = 1e-12
    return (
        abs(_cross(start, end, point)) <= epsilon
        and min(start.x, end.x) - epsilon <= point.x
        <= max(start.x, end.x) + epsilon
        and min(start.y, end.y) - epsilon <= point.y
        <= max(start.y, end.y) + epsilon
    )


def _segments_intersect(
    first_start: NormalizedPoint,
    first_end: NormalizedPoint,
    second_start: NormalizedPoint,
    second_end: NormalizedPoint,
) -> bool:
    first_a = _cross(first_start, first_end, second_start)
    first_b = _cross(first_start, first_end, second_end)
    second_a = _cross(second_start, second_end, first_start)
    second_b = _cross(second_start, second_end, first_end)
    epsilon = 1e-12

    if ((first_a > epsilon and first_b < -epsilon)
            or (first_a < -epsilon and first_b > epsilon)):
        if ((second_a > epsilon and second_b < -epsilon)
                or (second_a < -epsilon and second_b > epsilon)):
            return True

    return (
        (abs(first_a) <= epsilon
         and _point_on_segment(second_start, first_start, first_end))
        or (abs(first_b) <= epsilon
            and _point_on_segment(second_end, first_start, first_end))
        or (abs(second_a) <= epsilon
            and _point_on_segment(first_start, second_start, second_end))
        or (abs(second_b) <= epsilon
            and _point_on_segment(first_end, second_start, second_end))
    )


class NormalizedPolygon(_FrozenStrictModel):
    """A non-self-intersecting image-space polygon, not a factory contour."""

    points: Annotated[tuple[NormalizedPoint, ...], Field(min_length=3)]

    @model_validator(mode="after")
    def validate_polygon(self) -> NormalizedPolygon:
        coordinates = tuple((point.x, point.y) for point in self.points)
        if len(set(coordinates)) != len(coordinates):
            raise ValueError("polygon vertices must be unique and unclosed")

        twice_area = sum(
            first.x * second.y - second.x * first.y
            for first, second in zip(
                self.points,
                self.points[1:] + self.points[:1],
                strict=True,
            )
        )
        if abs(twice_area) <= 1e-12:
            raise ValueError("polygon must enclose a non-zero area")

        edge_count = len(self.points)
        for first_index in range(edge_count):
            first_end_index = (first_index + 1) % edge_count
            for second_index in range(first_index + 1, edge_count):
                second_end_index = (second_index + 1) % edge_count
                if (
                    first_index == second_index
                    or first_end_index == second_index
                    or second_end_index == first_index
                ):
                    continue
                if _segments_intersect(
                    self.points[first_index],
                    self.points[first_end_index],
                    self.points[second_index],
                    self.points[second_end_index],
                ):
                    raise ValueError("polygon edges must not self-intersect")
        return self


class DesignFormRegion(_FrozenStrictModel):
    """Exact isolation polygons for one named view of the reference asset."""

    view: FormView
    polygons: Annotated[tuple[NormalizedPolygon, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def reject_duplicate_polygons(self) -> DesignFormRegion:
        signatures = tuple(
            tuple((point.x, point.y) for point in polygon.points)
            for polygon in self.polygons
        )
        if len(set(signatures)) != len(signatures):
            raise ValueError("regions in one view must not repeat a polygon")
        return self


class VisualReferenceOnlyDefinition(_FrozenStrictModel):
    """Visual truth pinned to immutable source bytes.

    The SHA-256 is lowercase canonical hex.  This definition is sufficient for
    image-agent isolation and consistency checks, but intentionally contains no
    inferred millimeters, splines, or manufacturing geometry.
    """

    kind: Literal["visual_reference_only"]
    asset_id: AssetId
    asset_sha256: Sha256Hex


ProfilePathId: TypeAlias = Annotated[
    str,
    Field(
        strict=True,
        min_length=1,
        max_length=32,
        pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$",
    ),
]
MillimeterCoordinate: TypeAlias = Annotated[
    float,
    Field(strict=True, ge=-1000.0, le=1000.0),
]
PositiveMillimeter: TypeAlias = Annotated[
    float,
    Field(strict=True, gt=0.0, le=1000.0),
]


class DimensionedProfilePoint(_FrozenStrictModel):
    """One designer-supplied millimeter point; x right and y up from datum."""

    x_mm: MillimeterCoordinate
    y_mm: MillimeterCoordinate


def _profile_cross(
    first: DimensionedProfilePoint,
    second: DimensionedProfilePoint,
    third: DimensionedProfilePoint,
) -> float:
    return (
        (second.x_mm - first.x_mm) * (third.y_mm - first.y_mm)
        - (second.y_mm - first.y_mm) * (third.x_mm - first.x_mm)
    )


def _profile_point_on_segment(
    point: DimensionedProfilePoint,
    start: DimensionedProfilePoint,
    end: DimensionedProfilePoint,
) -> bool:
    epsilon = 1e-9
    return (
        abs(_profile_cross(start, end, point)) <= epsilon
        and min(start.x_mm, end.x_mm) - epsilon <= point.x_mm
        <= max(start.x_mm, end.x_mm) + epsilon
        and min(start.y_mm, end.y_mm) - epsilon <= point.y_mm
        <= max(start.y_mm, end.y_mm) + epsilon
    )


def _profile_segments_intersect(
    first_start: DimensionedProfilePoint,
    first_end: DimensionedProfilePoint,
    second_start: DimensionedProfilePoint,
    second_end: DimensionedProfilePoint,
) -> bool:
    first_a = _profile_cross(first_start, first_end, second_start)
    first_b = _profile_cross(first_start, first_end, second_end)
    second_a = _profile_cross(second_start, second_end, first_start)
    second_b = _profile_cross(second_start, second_end, first_end)
    epsilon = 1e-9
    if ((first_a > epsilon and first_b < -epsilon)
            or (first_a < -epsilon and first_b > epsilon)):
        if ((second_a > epsilon and second_b < -epsilon)
                or (second_a < -epsilon and second_b > epsilon)):
            return True
    return (
        (abs(first_a) <= epsilon
         and _profile_point_on_segment(second_start, first_start, first_end))
        or (abs(first_b) <= epsilon
            and _profile_point_on_segment(second_end, first_start, first_end))
        or (abs(second_a) <= epsilon
            and _profile_point_on_segment(first_start, second_start, second_end))
        or (abs(second_b) <= epsilon
            and _profile_point_on_segment(first_end, second_start, second_end))
    )


class DimensionedProfilePath(_FrozenStrictModel):
    """A closed outline or width-bearing construction centerline in millimeters."""

    path_id: ProfilePathId
    purpose: Literal["outline", "centerline", "stone_seat", "attachment"]
    closed: bool
    points: Annotated[tuple[DimensionedProfilePoint, ...], Field(min_length=2)]
    nominal_width_mm: PositiveMillimeter | None = None

    @model_validator(mode="after")
    def validate_path(self) -> DimensionedProfilePath:
        coordinates = tuple((point.x_mm, point.y_mm) for point in self.points)
        if len(set(coordinates)) != len(coordinates):
            raise ValueError("dimensioned profile vertices must be unique and unclosed")
        if self.closed and len(self.points) < 3:
            raise ValueError("a closed dimensioned profile needs at least three points")
        if self.purpose == "outline" and not self.closed:
            raise ValueError("a dimensioned outline must be closed")
        if self.purpose == "centerline":
            if self.closed:
                raise ValueError("a construction centerline must remain open")
            if self.nominal_width_mm is None:
                raise ValueError("a construction centerline needs nominal_width_mm")
        if self.closed:
            twice_area = sum(
                first.x_mm * second.y_mm - second.x_mm * first.y_mm
                for first, second in zip(
                    self.points,
                    self.points[1:] + self.points[:1],
                    strict=True,
                )
            )
            if abs(twice_area) <= 1e-9:
                raise ValueError("a closed dimensioned profile must enclose area")
        edges = list(zip(self.points, self.points[1:], strict=False))
        if self.closed:
            edges.append((self.points[-1], self.points[0]))
        for first_index, first_edge in enumerate(edges):
            for second_index in range(first_index + 1, len(edges)):
                second_edge = edges[second_index]
                if (
                    second_index == first_index + 1
                    or (
                        self.closed
                        and first_index == 0
                        and second_index == len(edges) - 1
                    )
                ):
                    continue
                if _profile_segments_intersect(*first_edge, *second_edge):
                    raise ValueError(
                        "dimensioned profile paths must not self-intersect"
                    )
        return self


class DimensionedProfileDefinition(_FrozenStrictModel):
    """Designer-confirmed 2D full-assembly geometry embedded in the spec.

    This first trusted variant is intentionally limited to a complete front
    assembly. Partial profiles cannot be placed against unrelated template
    geometry without a shared manufacturing datum, so they stay visual-only.
    The geometry is explicit millimeter data and may be marked as either
    supplied measurement or a designer-confirmed estimate.
    """

    kind: Literal["dimensioned_profile"]
    scope: Literal["full_assembly"]
    view: FormView
    coordinate_system: Literal["x_right_y_up"] = "x_right_y_up"
    paths: Annotated[tuple[DimensionedProfilePath, ...], Field(min_length=1)]
    profile_thickness_mm: PositiveMillimeter
    dimension_status: Literal["designer_supplied", "designer_confirmed_estimate"]
    source_asset_id: AssetId
    source_asset_sha256: Sha256Hex
    confirmed_by: Annotated[str, Field(strict=True, min_length=1, max_length=120)]
    confirmed_at: datetime
    manufacturing_notes: Annotated[
        str,
        Field(strict=True, min_length=1, max_length=1000),
    ]

    @field_validator("confirmed_by", "manufacturing_notes")
    @classmethod
    def reject_blank_profile_text(cls, value: str) -> str:
        if value != value.strip() or not value:
            raise ValueError("dimensioned profile text must be non-blank and trimmed")
        return value

    @model_validator(mode="after")
    def validate_profile(self) -> DimensionedProfileDefinition:
        path_ids = tuple(path.path_id for path in self.paths)
        if len(set(path_ids)) != len(path_ids):
            raise ValueError("dimensioned profile path IDs must be unique")
        if not any(path.purpose in {"outline", "centerline"} for path in self.paths):
            raise ValueError("dimensioned profile needs an outline or centerline")
        if self.confirmed_at.tzinfo is None:
            raise ValueError("dimensioned profile confirmation time must include timezone")
        return self


FormDefinition: TypeAlias = Annotated[
    VisualReferenceOnlyDefinition | DimensionedProfileDefinition,
    Field(discriminator="kind"),
]

FormSymmetry: TypeAlias = Literal[
    "asymmetric",
    "bilateral",
    "rotational",
    "radial",
    "repeated",
]


class DesignFormElement(_FrozenStrictModel):
    """One stable, designer-confirmed visual component of a jewelry design."""

    element_id: FormElementId
    role: FormRole
    label: Annotated[str, Field(strict=True, min_length=1, max_length=120)]
    confirmed_form_description: Annotated[
        str,
        Field(strict=True, min_length=1, max_length=1000),
    ]
    symmetry: FormSymmetry
    instance_count: Annotated[int, Field(strict=True, ge=1, le=1024)]
    regions: Annotated[tuple[DesignFormRegion, ...], Field(min_length=1)]
    definition: FormDefinition

    @field_validator("label", "confirmed_form_description")
    @classmethod
    def reject_ambiguous_whitespace(cls, value: str) -> str:
        if value != value.strip() or not value.strip():
            raise ValueError("confirmed form text must be non-blank and trimmed")
        return value

    @model_validator(mode="after")
    def require_one_region_group_per_view(self) -> DesignFormElement:
        views = tuple(region.view for region in self.regions)
        if len(set(views)) != len(views):
            raise ValueError("an element may define each view only once")
        return self


class DesignForm(_FrozenStrictModel):
    """Reference-defined form elements attached to one immutable spec version."""

    elements: tuple[DesignFormElement, ...] = ()

    @model_validator(mode="after")
    def require_unique_element_ids(self) -> DesignForm:
        element_ids = tuple(element.element_id for element in self.elements)
        if len(set(element_ids)) != len(element_ids):
            raise ValueError("design-form element IDs must be unique")
        full_profiles = tuple(
            element
            for element in self.elements
            if element.definition.kind == "dimensioned_profile"
        )
        if len(full_profiles) > 1:
            raise ValueError(
                "a specification may contain only one dimensioned full-assembly profile"
            )
        return self


class FormFactoryBlocker(_FrozenStrictModel):
    """A visual form that cannot yet be represented as factory truth."""

    code: Literal["visual_reference_not_dimensioned"] = (
        "visual_reference_not_dimensioned")
    element_id: FormElementId
    role: FormRole
    label: str
    message: str
    required_resolution: str


_ELEMENT_ID_ADAPTER = TypeAdapter(FormElementId)


def apply_scoped_form_element(
    current: DesignForm,
    proposed: DesignForm,
    *,
    element_id: str,
) -> DesignForm:
    """Add or replace exactly ``element_id`` while preserving all other form.

    ``proposed`` may contain unrelated model drift.  Only its named target is
    read.  If the ID already exists, it is replaced in its stable position; if
    it is new, it is appended.  Deletion is intentionally outside this
    contract.  The input models are never mutated.
    """

    target_id = _ELEMENT_ID_ADAPTER.validate_python(element_id)
    proposed_by_id = {
        element.element_id: element for element in proposed.elements
    }
    replacement = proposed_by_id.get(target_id)
    if replacement is None:
        raise ValueError(
            f"proposed design form does not contain target {target_id!r}")

    current_by_id = {
        element.element_id: element for element in current.elements
    }
    existing = current_by_id.get(target_id)
    if existing == replacement:
        raise ValueError(f"target {target_id!r} has no confirmed form change")

    replacement_copy = replacement.model_copy(deep=True)
    if existing is None:
        elements = tuple(
            element.model_copy(deep=True) for element in current.elements
        ) + (replacement_copy,)
    else:
        elements = tuple(
            replacement_copy
            if element.element_id == target_id
            else element.model_copy(deep=True)
            for element in current.elements
        )
    return DesignForm(elements=elements)


def unresolved_form_factory_blockers(
    design_form: DesignForm,
) -> tuple[FormFactoryBlocker, ...]:
    """Report visual-only contours that still lack factory-resolvable geometry."""

    return tuple(
        FormFactoryBlocker(
            element_id=element.element_id,
            role=element.role,
            label=element.label,
            message=(
                f"{element.label} is confirmed only by pinned visual reference; "
                "its contour is not dimensioned factory geometry."
            ),
            required_resolution=(
                "Designer must supply or confirm a dimensioned profile or CAD "
                "definition before factory release."
            ),
        )
        for element in design_form.elements
        if element.definition.kind == "visual_reference_only"
    )

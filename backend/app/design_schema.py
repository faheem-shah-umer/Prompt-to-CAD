from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Value = float | int | str
Vector3 = tuple[Value, Value, Value]
Point2 = tuple[Value, Value]
Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,47}$")]
Operation = Literal["new", "add", "cut", "intersect"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_default=True)


class Placement(StrictModel):
    translation: Vector3 = (0, 0, 0)
    rotation: Vector3 = (0, 0, 0)


class FeatureBase(StrictModel):
    id: Identifier


class SolidFeature(FeatureBase):
    operation: Operation = "add"
    placement: Placement = Field(default_factory=Placement)


class Box(SolidFeature):
    type: Literal["box"]
    size: Vector3
    centered: bool = True


class Cylinder(SolidFeature):
    type: Literal["cylinder"]
    radius: Value
    height: Value


class Cone(SolidFeature):
    type: Literal["cone"]
    radius_bottom: Value
    radius_top: Value
    height: Value


class Sphere(SolidFeature):
    type: Literal["sphere"]
    radius: Value


class Sketch(FeatureBase):
    type: Literal["sketch"]
    plane: Literal["XY", "XZ", "YZ"] = "XY"
    origin: Vector3 = (0, 0, 0)
    profile: Literal["circle", "rectangle", "ellipse", "polygon", "spline"]
    radius: Value | None = None
    width: Value | None = None
    height: Value | None = None
    points: list[Point2] = Field(default_factory=list, max_length=256)
    centre: Point2 = (0, 0)

    @model_validator(mode="after")
    def profile_fields(self):
        if self.profile == "circle":
            valid = self.radius is not None and self.width is None and self.height is None and not self.points
        elif self.profile in ("rectangle", "ellipse"):
            valid = self.width is not None and self.height is not None and self.radius is None and not self.points
        else:
            valid = len(self.points) >= 3 and self.radius is None and self.width is None and self.height is None
        if not valid:
            raise ValueError("Use only the fields for this profile. One sketch is one closed contour; use a hole feature or pattern for multiple holes.")
        return self


class Hole(FeatureBase):
    type: Literal["hole"]
    radius: Value
    centres: list[Point2] = Field(min_length=1, max_length=64)
    axis: Literal["X", "Y", "Z"] = "Z"
    depth: Value | None = None


class Extrude(SolidFeature):
    type: Literal["extrude"]
    sketch: Identifier
    distance: Value
    symmetric: bool = False


class Revolve(SolidFeature):
    type: Literal["revolve"]
    sketch: Identifier
    angle: Value = 360
    axis_start: Vector3 = (0, 0, 0)
    axis_end: Vector3 = (0, 0, 1)


class Loft(SolidFeature):
    type: Literal["loft"]
    sketches: list[Identifier] = Field(min_length=2, max_length=12)
    ruled: bool = False


class Sweep(SolidFeature):
    type: Literal["sweep"]
    sketch: Identifier
    path: list[Vector3] = Field(min_length=2, max_length=128)
    smooth: bool = False
    frenet: bool = False


class EdgeTreatment(FeatureBase):
    type: Literal["fillet", "chamfer"]
    size: Value
    edges: str = Field(default="|Z", max_length=80)


class LinearPattern(SolidFeature):
    type: Literal["linear_pattern"]
    feature: Identifier
    count: int = Field(ge=2, le=64)
    step: Vector3


class CircularPattern(SolidFeature):
    type: Literal["circular_pattern"]
    feature: Identifier
    count: int = Field(ge=2, le=128)
    angle: Value = 360
    axis_start: Vector3 = (0, 0, 0)
    axis_end: Vector3 = (0, 0, 1)


class Mirror(SolidFeature):
    type: Literal["mirror"]
    feature: Identifier
    normal: Vector3 = (1, 0, 0)
    origin: Vector3 = (0, 0, 0)


class Boolean(SolidFeature):
    type: Literal["boolean"]
    component: Identifier


class Thread(SolidFeature):
    type: Literal["thread"]
    major_radius: Value
    minor_radius: Value
    pitch: Value
    length: Value
    left_hand: bool = False
    internal: bool = False


Feature = Annotated[
    Box | Cylinder | Cone | Sphere | Sketch | Extrude | Revolve | Loft | Sweep
    | EdgeTreatment | LinearPattern | CircularPattern | Mirror | Boolean | Thread | Hole,
    Field(discriminator="type"),
]


class Component(StrictModel):
    id: Identifier
    name: str = Field(min_length=1, max_length=100)
    color: str = Field(default="#b69bce", pattern=r"^#[0-9a-fA-F]{6}$")
    parameters: dict[Identifier, Value] = Field(default_factory=dict, max_length=64)
    features: list[Feature] = Field(min_length=1, max_length=96)
    placement: Placement = Field(default_factory=Placement)
    expected_size: Vector3 | None = None

    @model_validator(mode="after")
    def unique_features(self):
        ids = [feature.id for feature in self.features]
        if len(ids) != len(set(ids)):
            raise ValueError(f"Feature IDs must be unique within {self.id}.")
        return self


class Relationship(StrictModel):
    id: Identifier
    type: Literal["coaxial", "contact"]
    component_a: Identifier
    component_b: Identifier
    point_a: Vector3 = (0, 0, 0)
    point_b: Vector3 = (0, 0, 0)
    axis_a: Vector3 = (0, 0, 1)
    axis_b: Vector3 = (0, 0, 1)
    tolerance: float = Field(default=0.01, gt=0, le=0.1)


class Design(StrictModel):
    schema_version: Literal[1] = 1
    name: str = Field(min_length=1, max_length=120)
    units: Literal["mm"] = "mm"
    parameters: dict[Identifier, Value] = Field(default_factory=dict, max_length=64)
    components: list[Component] = Field(min_length=1, max_length=32)
    relationships: list[Relationship] = Field(default_factory=list, max_length=64)
    allowed_intersections: list[tuple[Identifier, Identifier]] = Field(default_factory=list, max_length=64)

    @model_validator(mode="after")
    def check_references(self):
        ids = [component.id for component in self.components]
        if len(ids) != len(set(ids)):
            raise ValueError("Component IDs must be unique.")
        relation_ids = [relation.id for relation in self.relationships]
        if len(relation_ids) != len(set(relation_ids)):
            raise ValueError("Relationship IDs must be unique.")
        pairs = [(r.component_a, r.component_b) for r in self.relationships] + self.allowed_intersections
        for a, b in pairs:
            if a not in ids or b not in ids or a == b:
                raise ValueError("An assembly relationship must reference two different existing components.")
        return self


class DesignPlan(StrictModel):
    status: Literal["ready", "needs_input", "unsupported"]
    description: str = Field(max_length=1000)
    questions: list[str] = Field(default_factory=list, max_length=8)
    assumptions: list[str] = Field(default_factory=list, max_length=12)
    design: Design | None = None

    @model_validator(mode="after")
    def ready_has_design(self):
        if (self.status == "ready") != (self.design is not None):
            raise ValueError("Only a ready plan must contain a design.")
        return self


class SetParameters(StrictModel):
    type: Literal["set_parameters"]
    component_id: Identifier | None = None
    values: dict[Identifier, Value] = Field(min_length=1, max_length=64)


class ReplaceFeature(StrictModel):
    type: Literal["replace_feature"]
    component_id: Identifier
    feature: Feature


class AddFeature(StrictModel):
    type: Literal["add_feature"]
    component_id: Identifier
    feature: Feature
    after: Identifier | None = None


class RemoveFeature(StrictModel):
    type: Literal["remove_feature"]
    component_id: Identifier
    feature_id: Identifier


class SetPlacement(StrictModel):
    type: Literal["set_placement"]
    component_id: Identifier
    placement: Placement


class AddComponent(StrictModel):
    type: Literal["add_component"]
    component: Component


class RemoveComponent(StrictModel):
    type: Literal["remove_component"]
    component_id: Identifier


class SetRelationship(StrictModel):
    type: Literal["set_relationship"]
    relationship: Relationship


class RemoveRelationship(StrictModel):
    type: Literal["remove_relationship"]
    relationship_id: Identifier


Change = Annotated[
    SetParameters | ReplaceFeature | AddFeature | RemoveFeature | SetPlacement
    | AddComponent | RemoveComponent | SetRelationship | RemoveRelationship,
    Field(discriminator="type"),
]


class EditPlan(StrictModel):
    status: Literal["ready", "needs_input", "unsupported"]
    description: str = Field(max_length=1000)
    questions: list[str] = Field(default_factory=list, max_length=8)
    assumptions: list[str] = Field(default_factory=list, max_length=12)
    changes: list[Change] = Field(default_factory=list, max_length=48)

    @model_validator(mode="after")
    def ready_has_changes(self):
        if (self.status == "ready") != bool(self.changes):
            raise ValueError("Only a ready edit must contain changes.")
        return self


class EditRequest(StrictModel):
    prompt: str = Field(min_length=5, max_length=8000)
    selected_component_id: Identifier | None = None
    base_revision_id: UUID


class RevisionRequest(StrictModel):
    base_revision_id: UUID

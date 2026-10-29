from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Value = float | int | str
Vector3 = tuple[Value, Value, Value]
Point2 = tuple[Value, Value]
Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,47}$")]
Operation = Literal["new", "add", "cut", "intersect"]
FeatureKind = Literal[
    "box",
    "cylinder",
    "cone",
    "sphere",
    "sketch",
    "extrude",
    "revolve",
    "loft",
    "sweep",
    "fillet",
    "chamfer",
    "linear_pattern",
    "circular_pattern",
    "mirror",
    "boolean",
    "thread",
    "hole",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", allow_inf_nan=False, validate_default=True
    )


class Placement(StrictModel):
    translation: Vector3 = (0, 0, 0)
    rotation: Vector3 = (0, 0, 0)


class Attachment(StrictModel):
    parent: Identifier
    axis: Literal["X", "Y", "Z"] = "Z"
    side: Literal[-1, 1] = 1
    offset: Point2 = (0, 0)
    gap: Value = 0


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
            valid = (
                self.radius is not None
                and self.width is None
                and self.height is None
                and not self.points
            )
        elif self.profile in ("rectangle", "ellipse"):
            valid = (
                self.width is not None
                and self.height is not None
                and self.radius is None
                and not self.points
            )
        else:
            valid = (
                len(self.points) >= 3
                and self.radius is None
                and self.width is None
                and self.height is None
            )
        if not valid:
            raise ValueError(
                "Use only the fields for this profile. One sketch is one closed contour; use a hole feature or pattern for multiple holes."
            )
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


class LoftSection(StrictModel):
    station: Value
    width: Value
    height: Value
    centre: Point2 = (0, 0)


class Loft(SolidFeature):
    type: Literal["loft"]
    sketches: list[Identifier] = Field(default_factory=list, max_length=12)
    sections: list[LoftSection] = Field(default_factory=list, max_length=12)
    plane: Literal["XY", "XZ", "YZ"] = "XY"
    profile: Literal["ellipse", "rectangle"] = "ellipse"
    ruled: bool = False

    @model_validator(mode="after")
    def one_section_source(self):
        if not (
            (len(self.sketches) >= 2 and not self.sections)
            or (len(self.sections) >= 2 and not self.sketches)
        ):
            raise ValueError(
                "A loft needs either 2-12 earlier sketch IDs or 2-12 inline sections, not both."
            )
        return self


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
    Box
    | Cylinder
    | Cone
    | Sphere
    | Sketch
    | Extrude
    | Revolve
    | Loft
    | Sweep
    | EdgeTreatment
    | LinearPattern
    | CircularPattern
    | Mirror
    | Boolean
    | Thread
    | Hole,
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
    attachment: Attachment | None = None

    @model_validator(mode="after")
    def unique_features(self):
        ids = [feature.id for feature in self.features]
        if len(ids) != len(set(ids)):
            raise ValueError(f"Feature IDs must be unique within {self.id}.")
        return self


class Relationship(StrictModel):
    id: Identifier
    type: Literal["coaxial", "contact", "distance"]
    component_a: Identifier
    component_b: Identifier
    point_a: Vector3 = (0, 0, 0)
    point_b: Vector3 = (0, 0, 0)
    axis_a: Vector3 = (0, 0, 1)
    axis_b: Vector3 = (0, 0, 1)
    tolerance: float = Field(default=0.01, gt=0, le=0.1)
    distance: Value | None = None

    @model_validator(mode="after")
    def distance_target(self):
        if (self.type == "distance") != (self.distance is not None):
            raise ValueError("Only a distance relationship needs a target distance.")
        return self


class Design(StrictModel):
    schema_version: Literal[1] = 1
    name: str = Field(min_length=1, max_length=120)
    units: Literal["mm"] = "mm"
    parameters: dict[Identifier, Value] = Field(default_factory=dict, max_length=64)
    components: list[Component] = Field(min_length=1, max_length=32)
    relationships: list[Relationship] = Field(default_factory=list, max_length=64)
    allowed_intersections: list[tuple[Identifier, Identifier]] = Field(
        default_factory=list, max_length=64
    )

    @model_validator(mode="after")
    def check_references(self):
        ids = [component.id for component in self.components]
        if len(ids) != len(set(ids)):
            raise ValueError("Component IDs must be unique.")
        relation_ids = [relation.id for relation in self.relationships]
        if len(relation_ids) != len(set(relation_ids)):
            raise ValueError("Relationship IDs must be unique.")
        pairs = [
            (r.component_a, r.component_b) for r in self.relationships
        ] + self.allowed_intersections
        pairs += [
            (part.id, part.attachment.parent)
            for part in self.components
            if part.attachment
        ]
        for a, b in pairs:
            if a not in ids or b not in ids or a == b:
                raise ValueError(
                    "An assembly relationship must reference two different existing components."
                )
        return self

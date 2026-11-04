from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


CAD_TURN_TIMEOUT_SECONDS = 45 * 60
CAD_TURN_TIMEOUT_MESSAGE = (
    f"The CAD turn reached its {CAD_TURN_TIMEOUT_SECONDS // 60}-minute time limit. "
    "Unaccepted changes were discarded."
)


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


Vector = tuple[float, float, float]


class Selection(Contract):
    revision_id: str
    instance_id: str
    kind: Literal["body", "face", "edge", "vertex"] = "body"
    index: int = Field(default=0, ge=0)


class Targeted(Contract):
    instance_id: str


class Hole(Targeted):
    type: Literal["hole"]
    diameter: float = Field(gt=0, le=2000)
    centres: list[tuple[float, float]] = Field(min_length=1, max_length=100)
    axis: Literal["X", "Y", "Z"] = "Z"
    depth: float | None = Field(default=None, gt=0, le=10000)


class EdgeTreatment(Targeted):
    type: Literal["fillet", "chamfer"]
    size: float = Field(gt=0, le=2000)
    edge_indices: list[int] = Field(min_length=1, max_length=256)


class Extrusion(Targeted):
    type: Literal["extrude"]
    origin: Vector = (0, 0, 0)
    normal: Vector = (0, 0, 1)
    x_direction: Vector = (1, 0, 0)
    profile: list[tuple[float, float]] = Field(min_length=3, max_length=128)
    distance: float = Field(gt=-10000, lt=10000)
    operation: Literal["add", "cut", "intersect"] = "cut"


class FaceOffset(Targeted):
    type: Literal["offset_face"]
    face_index: int = Field(ge=1)
    distance: float = Field(gt=-10000, lt=10000)


class FaceHoles(Targeted):
    type: Literal["face_holes"]
    face_index: int = Field(ge=1)
    diameter: float = Field(gt=0, le=2000)
    centres: list[tuple[float, float]] = Field(min_length=1, max_length=100)
    depth: float = Field(gt=0, le=10000)


class Transform(Targeted):
    type: Literal["transform"]
    translation: Vector = (0, 0, 0)
    rotation: Vector = (0, 0, 0)


class Boolean(Targeted):
    type: Literal["boolean"]
    tool_instance_id: str
    operation: Literal["add", "cut", "intersect"]


class Pattern(Targeted):
    type: Literal["pattern"]
    seed: Hole | Extrusion
    mode: Literal["linear", "circular"] = "linear"
    count: int = Field(ge=2, le=100)
    step: Vector = (10, 0, 0)
    axis_origin: Vector = (0, 0, 0)
    axis_direction: Vector = (0, 0, 1)
    angle: float = Field(default=360, gt=0, le=360)

    @model_validator(mode="after")
    def same_target(self):
        if self.seed.instance_id != self.instance_id:
            raise ValueError("A pattern seed must target the same component instance.")
        return self


class Parameters(Targeted):
    type: Literal["parameters"]
    values: dict[str, float] = Field(min_length=1, max_length=64)


class MeshColor(Targeted):
    type: Literal["mesh_color"]
    color: tuple[int, int, int]
    triangle_indices: list[int] = Field(default_factory=list, max_length=200000)


class MeshRegionMove(Targeted):
    type: Literal["mesh_region_move"]
    translation: Vector
    triangle_indices: list[int] = Field(min_length=1, max_length=200000)


class MeshSeparate(Targeted):
    type: Literal["mesh_separate"]
    triangle_indices: list[int] = Field(min_length=1, max_length=200000)


class MeshScale(Targeted):
    type: Literal["mesh_scale"]
    factor: float = Field(ge=0.001, le=1000)


class MeshSmooth(Targeted):
    type: Literal["mesh_smooth"]
    iterations: int = Field(default=3, ge=1, le=30)


Command = Annotated[Hole | EdgeTreatment | Extrusion | FaceOffset | FaceHoles | Transform | Boolean | Pattern | Parameters | MeshColor | MeshRegionMove | MeshSeparate | MeshScale | MeshSmooth,
                    Field(discriminator="type")]


class WorkspaceError(Exception):
    def __init__(self, message, code="invalid_operation", details=None):
        super().__init__(message)
        self.code = code
        self.details = details or {}

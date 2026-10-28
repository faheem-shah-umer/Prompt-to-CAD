from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


Command = Annotated[Hole | EdgeTreatment | Extrusion | Transform | Boolean | Pattern | Parameters,
                    Field(discriminator="type")]


class AgentAction(Contract):
    status: Literal["tool", "done", "needs_input", "unsupported"]
    message: str = Field(min_length=1, max_length=3000)
    command: Command | None = None

    @model_validator(mode="after")
    def tool_has_command(self):
        if (self.status == "tool") != (self.command is not None):
            raise ValueError("Only a tool action must contain a command.")
        return self


class WorkspaceError(Exception):
    def __init__(self, message, code="invalid_operation"):
        super().__init__(message)
        self.code = code

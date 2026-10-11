from math import dist
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PlateSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    description: str = Field(default="Parametric plate", max_length=500)
    units: Literal["mm"] = "mm"
    length: float = Field(gt=0, le=2000)
    width: float = Field(gt=0, le=2000)
    thickness: float = Field(gt=0, le=2000)
    hole_diameter: float = Field(gt=0, le=2000)
    hole_centres: list[tuple[float, float]] = Field(default_factory=list, max_length=64)

    @model_validator(mode="after")
    def check_holes(self):
        radius = self.hole_diameter / 2
        for x, y in self.hole_centres:
            if abs(x) + radius >= self.length / 2 or abs(y) + radius >= self.width / 2:
                raise ValueError("Each hole must fit completely inside the plate.")
        for index, centre in enumerate(self.hole_centres):
            if any(dist(centre, other) <= 2 * radius for other in self.hole_centres[index + 1 :]):
                raise ValueError("Hole centres must leave separate, non-touching holes.")
        return self


class ModelResult(BaseModel):
    model_id: UUID
    created_at: str
    specification: PlateSpec
    validation: dict
    downloads: dict[str, str]


class PromptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    prompt: str = Field(min_length=5, max_length=4000)


class HoleCentre(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    x: float
    y: float


class PlateInterpretation(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    status: Literal["ready", "needs_input", "unsupported"]
    description: str = Field(max_length=500)
    length: float | None = Field(gt=0, le=2000)
    width: float | None = Field(gt=0, le=2000)
    thickness: float | None = Field(gt=0, le=2000)
    hole_diameter: float | None = Field(gt=0, le=2000)
    hole_centres: list[HoleCentre] = Field(max_length=64)
    questions: list[str] = Field(max_length=6)
    assumptions: list[str] = Field(max_length=6)


class PlanningResult(BaseModel):
    provider: str
    model: str
    seconds: float
    interpretation: PlateInterpretation
    specification: PlateSpec | None


class GenerationResult(BaseModel):
    plan: PlanningResult
    model: ModelResult | None
    seconds: float

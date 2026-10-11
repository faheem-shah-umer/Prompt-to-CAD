from typing import Literal

from pydantic import Field, model_validator

from .design_schema import Attachment, Feature, FeatureKind, Identifier, Placement, Relationship, StrictModel, Value, Vector3


class ComponentBrief(StrictModel):
    id: Identifier
    name: str = Field(min_length=1, max_length=100)
    color: str = Field(default="#b69bce", pattern=r"^#[0-9a-fA-F]{6}$")
    parameters: dict[Identifier, Value] = Field(default_factory=dict, max_length=64)
    placement: Placement = Field(default_factory=Placement)
    expected_size: Vector3 | None = None
    requirements: str = Field(min_length=1, max_length=4000)
    depends_on: list[Identifier] = Field(default_factory=list, max_length=32)
    operations: list[FeatureKind] = Field(default_factory=list, max_length=17)
    attachment: Attachment | None = None


class AssemblyBrief(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    units: Literal["mm"] = "mm"
    parameters: dict[Identifier, Value] = Field(default_factory=dict, max_length=64)
    components: list[ComponentBrief] = Field(min_length=1, max_length=32)
    relationships: list[Relationship] = Field(default_factory=list, max_length=64)
    allowed_intersections: list[tuple[Identifier, Identifier]] = Field(default_factory=list, max_length=64)

    @model_validator(mode="after")
    def consistent_components(self):
        ids = [part.id for part in self.components]
        if len(ids) != len(set(ids)):
            raise ValueError("Every separately selectable part needs a unique component ID.")
        remaining = {part.id: set(part.depends_on) for part in self.components}
        for part in self.components:
            if part.attachment:
                remaining[part.id].add(part.attachment.parent)
            if part.id in part.depends_on or not set(part.depends_on).issubset(ids):
                raise ValueError(f"Invalid component dependencies for {part.id}.")
            if part.attachment and (part.attachment.parent == part.id or part.attachment.parent not in ids):
                raise ValueError(f"Invalid attachment parent for {part.id}.")
        visited = set()
        while remaining:
            ready = [key for key, dependencies in remaining.items() if dependencies.issubset(visited)]
            if not ready:
                raise ValueError("The component dependency graph contains a cycle.")
            for key in ready:
                visited.add(key)
                del remaining[key]
        return self


class AssemblyPlan(StrictModel):
    status: Literal["ready", "needs_input", "unsupported"]
    description: str = Field(max_length=1000)
    questions: list[str] = Field(default_factory=list, max_length=8)
    assumptions: list[str] = Field(default_factory=list, max_length=12)
    assembly: AssemblyBrief | None = None

    @model_validator(mode="after")
    def ready_has_assembly(self):
        if (self.status == "ready") != (self.assembly is not None):
            raise ValueError("Only a ready plan must contain an assembly brief.")
        return self


class ComponentRecipe(StrictModel):
    id: Identifier
    parameters: dict[Identifier, Value] = Field(default_factory=dict, max_length=64)
    features: list[Feature] = Field(min_length=1, max_length=96)


class ComponentBatch(StrictModel):
    components: list[ComponentRecipe] = Field(min_length=1, max_length=3)

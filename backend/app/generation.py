from time import perf_counter

from . import planner, service
from .schemas import GenerationResult


def create_from_prompt(prompt: str) -> GenerationResult:
    started = perf_counter()
    plan = planner.plan_plate(prompt)
    model = service.create_model(plan.specification) if plan.specification is not None else None
    return GenerationResult(plan=plan, model=model, seconds=perf_counter() - started)

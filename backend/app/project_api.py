import logging
from time import perf_counter
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from . import design_planner, projects
from .design_edits import apply_changes
from .design_schema import Design, EditPlan, EditRequest, RevisionRequest
from .llm_client import LLMError
from .parameters import DesignError
from .schemas import PromptRequest

router = APIRouter(prefix="/api/projects", tags=["editable projects"])
logger = logging.getLogger(__name__)


def api_error(error):
    if isinstance(error, FileNotFoundError):
        return HTTPException(404, "Project or revision not found.")
    if isinstance(error, projects.RevisionConflict):
        return HTTPException(409, str(error))
    if isinstance(error, DesignError):
        return HTTPException(422, str(error))
    if isinstance(error, LLMError):
        code = {"configuration": 503, "quota": 429, "timeout": 504, "invalid_plan": 422}.get(error.code, 502)
        return HTTPException(code, str(error))
    logger.exception("Project operation failed")
    return HTTPException(500, "The project operation failed; check the backend log.")


@router.get("")
def saved_projects():
    return projects.list_projects()


@router.post("")
def create_project(request: PromptRequest):
    started = perf_counter()
    try:
        plan, inference = design_planner.interpret(request.prompt)
        project = projects.save_revision(plan.design, summary=plan.description, assumptions=plan.assumptions) if plan.design else None
        return {"plan": plan.model_dump(mode="json"), "project": project, "inference": inference,
                "seconds": round(perf_counter() - started, 3)}
    except Exception as error:
        raise api_error(error) from error


@router.post("/from-spec")
def create_from_spec(design: Design):
    """Reopen an editable .cad.json as a new project, or exercise the deterministic CAD API."""
    try:
        return projects.save_revision(design, summary="Opened editable project specification")
    except Exception as error:
        raise api_error(error) from error


@router.get("/{project_id}")
def open_project(project_id: UUID):
    try:
        return projects.read_project(project_id)
    except Exception as error:
        raise api_error(error) from error


@router.post("/{project_id}/edits")
def edit_project(project_id: UUID, request: EditRequest):
    started = perf_counter()
    try:
        original = projects.check_revision(project_id, request.base_revision_id)
        plan, inference = design_planner.interpret(request.prompt, original, request.selected_component_id)
        updated = None
        if plan.status == "ready":
            design = apply_changes(Design.model_validate(original["design"]), plan, request.selected_component_id)
            updated = projects.save_revision(design, project_id=project_id, base_revision_id=request.base_revision_id,
                                             summary=plan.description, assumptions=list(dict.fromkeys(original["assumptions"] + plan.assumptions)))
        return {"plan": plan.model_dump(mode="json"), "project": updated, "inference": inference,
                "seconds": round(perf_counter() - started, 3)}
    except Exception as error:
        raise api_error(error) from error


@router.post("/{project_id}/changes")
def apply_parameterised_changes(project_id: UUID, request: RevisionRequest, plan: EditPlan):
    """Deterministic edit endpoint for learning FastAPI and testing feature changes without inference."""
    try:
        original = projects.check_revision(project_id, request.base_revision_id)
        candidate = apply_changes(Design.model_validate(original["design"]), plan, None)
        return projects.save_revision(candidate, project_id=project_id, base_revision_id=request.base_revision_id,
                                      summary=plan.description, assumptions=plan.assumptions)
    except Exception as error:
        raise api_error(error) from error


@router.post("/{project_id}/undo")
def undo(project_id: UUID, request: RevisionRequest):
    try:
        return projects.move_revision(project_id, request.base_revision_id, -1)
    except Exception as error:
        raise api_error(error) from error


@router.post("/{project_id}/redo")
def redo(project_id: UUID, request: RevisionRequest):
    try:
        return projects.move_revision(project_id, request.base_revision_id, 1)
    except Exception as error:
        raise api_error(error) from error


@router.get("/{project_id}/revisions/{revision_id}/files/{kind}")
def export(project_id: UUID, revision_id: UUID, kind: Literal["step", "stl", "report", "project"]):
    try:
        path = projects.revision_file(project_id, revision_id, kind)
        media = {"step": "application/octet-stream", "stl": "model/stl",
                 "report": "application/json", "project": "application/json"}[kind]
        return FileResponse(path, filename=path.name, media_type=media)
    except Exception as error:
        raise api_error(error) from error


@router.get("/{project_id}/revisions/{revision_id}/components/{component_id}.stl")
def component_preview(project_id: UUID, revision_id: UUID, component_id: str):
    try:
        return FileResponse(projects.component_file(project_id, revision_id, component_id), media_type="model/stl")
    except Exception as error:
        raise api_error(error) from error

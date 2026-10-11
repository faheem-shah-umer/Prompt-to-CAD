import logging
from typing import Literal
from uuid import UUID

import cadquery as cq
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import generation, planner, service
from .config import FRONTEND_DIST, FRONTEND_ORIGINS
from .llm_client import LLMError, public_status
from .design_jobs import router as design_job_router
from .project_api import router as project_router
from .schemas import GenerationResult, ModelResult, PlateSpec, PlanningResult, PromptRequest

logger = logging.getLogger(__name__)
app = FastAPI(
    title="Prompt to CAD API",
    version="0.5.0",
    description="Parametric, editable CAD projects with component selection, feature histories, assemblies and verified revisions. The earlier plate endpoints remain available.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
app.include_router(design_job_router)


@app.get("/api/health", tags=["status"])
async def health():
    return {"status": "ok", "cadquery_version": cq.__version__, "units": "mm"}


@app.get("/api/llm", tags=["planning"])
def llm_status():
    return public_status()


def provider_error(error: LLMError) -> HTTPException:
    status = {"configuration": 503, "quota": 429, "timeout": 504,
              "invalid_plan": 422, "invalid_geometry": 422}.get(error.code, 502)
    return HTTPException(status_code=status, detail=str(error))


@app.post("/api/generations", response_model=GenerationResult, tags=["generation"])
def create_from_description(request: PromptRequest):
    """Interpret, validate, build and verify; incomplete ideas return a plan with no model."""
    try:
        return generation.create_from_prompt(request.prompt)
    except LLMError as error:
        raise provider_error(error) from error
    except service.CadBuildError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        logger.exception("CAD generation failed")
        raise HTTPException(status_code=500, detail="CAD construction failed; check the backend log.") from error


@app.post("/api/plans", response_model=PlanningResult, tags=["planning"])
def interpret_prompt(request: PromptRequest):
    try:
        return planner.plan_plate(request.prompt)
    except LLMError as error:
        raise provider_error(error) from error


@app.post("/api/models", response_model=ModelResult, status_code=201, tags=["models"])
def create_model(specification: PlateSpec):
    try:
        return service.create_model(specification)
    except service.CadBuildError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        logger.exception("CAD construction failed")
        raise HTTPException(status_code=500, detail="CAD construction failed; check the backend log.") from error


@app.get("/api/models/{model_id}", response_model=ModelResult, tags=["models"])
def get_model(model_id: UUID):
    try:
        return service.read_model(model_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="Model not found.") from error


@app.get("/api/models/{model_id}/files/{kind}", tags=["models"])
def download_file(model_id: UUID, kind: Literal["step", "stl", "report"]):
    try:
        path = service.exported_file(model_id, kind)
        if not path.is_file():
            raise FileNotFoundError(path)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="Model file not found.") from error
    media_type = {"step": "application/octet-stream", "stl": "model/stl", "report": "application/json"}[kind]
    return FileResponse(path, filename=path.name, media_type=media_type)


app.include_router(project_router)

if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="interface")

import copy
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import Field, model_validator

from . import design_planner, projects
from .config import GENERATION_JOBS_DIR
from .design_edits import apply_changes
from .design_schema import Design, Identifier, StrictModel
from .llm_client import load_settings
from .project_api import api_error

router = APIRouter(prefix="/api/design-jobs", tags=["generation jobs"])
executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cad-generation")
lock = threading.Lock()
jobs = {}


class JobRequest(StrictModel):
    prompt: str = Field(min_length=5, max_length=16000)
    project_id: UUID | None = None
    base_revision_id: UUID | None = None
    selected_component_id: Identifier | None = None

    @model_validator(mode="after")
    def edit_has_revision(self):
        if (self.project_id is None) != (self.base_revision_id is None):
            raise ValueError("Editing requires both project_id and base_revision_id.")
        if self.project_id is None and self.selected_component_id is not None:
            raise ValueError("A new design cannot have a selected component.")
        if len(self.prompt.strip()) < 5:
            raise ValueError("Describe the design in at least five characters.")
        if self.project_id and len(self.prompt) > 8000:
            raise ValueError("An edit prompt can contain at most 8,000 characters.")
        return self


def snapshot(job_id):
    with lock:
        job = jobs.get(str(job_id))
        if job is None:
            raise HTTPException(404, "Generation job not found. Reopen your saved project if the application restarted.")
        result = copy.deepcopy(job)
    started = result.pop("started")
    result["elapsed_seconds"] = round(time.monotonic() - started, 1) if result.get("finished_seconds") is None else result["finished_seconds"]
    return result


def run_job(job_id, request):
    folder = GENERATION_JOBS_DIR / job_id
    journal = {"job_id": job_id, "request": request.model_dump(mode="json"), "attempts": []}

    def update(values):
        with lock:
            jobs[job_id].update(values)

    def trace(values):
        journal["attempts"].append(values)
        projects.write_json(folder / "diagnostics.json", journal)

    try:
        folder.mkdir(parents=True, exist_ok=True)
        projects.write_json(folder / "diagnostics.json", journal)
        update({"status": "running"})
        original = projects.check_revision(request.project_id, request.base_revision_id) if request.project_id else None
        plan, inference = design_planner.interpret(request.prompt.strip(), original, request.selected_component_id,
                                                 progress=update, trace=trace)
        result_project = None
        if plan.status == "ready":
            update({"stage": "exporting", "message": "Checking STEP exchange and saving the accepted revision…"})
            if original:
                design = apply_changes(Design.model_validate(original["design"]), plan, request.selected_component_id)
                assumptions = list(dict.fromkeys(original["assumptions"] + plan.assumptions))
                result_project = projects.save_revision(design, project_id=request.project_id,
                                                       base_revision_id=request.base_revision_id,
                                                       summary=plan.description, assumptions=assumptions)
            else:
                result_project = projects.save_revision(plan.design, summary=plan.description, assumptions=plan.assumptions)
        with lock:
            elapsed = round(time.monotonic() - jobs[job_id]["started"], 3)
        result = {"plan": plan.model_dump(mode="json"), "project": result_project,
                  "inference": inference, "seconds": elapsed}
        journal["result"] = {"status": plan.status, "inference": inference,
                             "project_id": result_project["project_id"] if result_project else None,
                             "revision_id": result_project["revision_id"] if result_project else None}
        projects.write_json(folder / "diagnostics.json", journal)
        update({"status": "completed", "stage": "completed", "message": "Revision saved" if result_project else plan.description,
                "result": result, "finished_seconds": elapsed})
    except Exception as error:
        failure = api_error(error)
        journal["error"] = {"message": failure.detail, "http_status": failure.status_code}
        try:
            projects.write_json(folder / "diagnostics.json", journal)
        except OSError:
            pass
        with lock:
            elapsed = round(time.monotonic() - jobs[job_id]["started"], 3)
        update({"status": "failed", "stage": "failed", "message": "Generation stopped",
                "error": journal["error"], "finished_seconds": elapsed})


@router.post("", status_code=202)
def start_job(request: JobRequest):
    try:
        load_settings().check()
        if request.project_id:
            original = projects.check_revision(request.project_id, request.base_revision_id)
            if request.selected_component_id and not any(part["id"] == request.selected_component_id for part in original["design"]["components"]):
                raise HTTPException(422, "The selected component no longer exists.")
        with lock:
            if any(job["status"] in ("queued", "running") for job in jobs.values()):
                raise HTTPException(409, "A generation is already running in this application. Wait for it to finish.")
            expired = [key for key, value in jobs.items() if time.monotonic() - value["started"] > 3600]
            for key in expired:
                del jobs[key]
            if len(jobs) >= 50:
                del jobs[min(jobs, key=lambda key: jobs[key]["started"])]
            job_id = str(uuid4())
            jobs[job_id] = {"job_id": job_id, "status": "queued", "stage": "planning",
                            "message": "Preparing your design…", "started": time.monotonic(),
                            "finished_seconds": None, "components_completed": 0, "components_total": 0,
                            "requests_used": 0, "max_requests": design_planner.MAX_REQUESTS,
                            "error": None, "result": None, "diagnostics_url": f"/api/design-jobs/{job_id}/diagnostics"}
        executor.submit(run_job, job_id, request)
        return snapshot(job_id)
    except HTTPException:
        raise
    except Exception as error:
        raise api_error(error) from error


@router.get("/{job_id}")
def job_status(job_id: UUID):
    return snapshot(job_id)


@router.get("/{job_id}/diagnostics")
def job_diagnostics(job_id: UUID):
    path = GENERATION_JOBS_DIR / str(job_id) / "diagnostics.json"
    if not path.is_file():
        raise HTTPException(404, "Generation diagnostics not found.")
    return FileResponse(path, filename=f"generation-{job_id}.json", media_type="application/json")

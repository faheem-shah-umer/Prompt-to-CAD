import json
from datetime import datetime, timezone
from threading import Lock
from uuid import UUID, uuid4

import cadquery as cq

from .cad import build_plate, measure_plate
from .config import RUNS_DIR
from .schemas import ModelResult, PlateSpec

CAD_LOCK = Lock()
EXPORT_FILES = {"step": "plate.step", "stl": "plate.stl", "report": "validation.json"}


class CadBuildError(Exception):
    pass


def create_model(specification: PlateSpec) -> ModelResult:
    spec = specification.model_dump(mode="json")
    # Keep the first local CAD worker sequential while HTTP remains responsive.
    with CAD_LOCK:
        plate = build_plate(spec)
        report = measure_plate(plate, spec)
        if not report["passed"]:
            raise CadBuildError("The constructed solid failed geometry checks.")
        model_id = uuid4()
        folder = RUNS_DIR / str(model_id)
        folder.mkdir(parents=True)
        cq.exporters.export(plate, str(folder / EXPORT_FILES["step"]))
        cq.exporters.export(plate, str(folder / EXPORT_FILES["stl"]))
        report["step_roundtrip"] = measure_plate(
            cq.importers.importStep(str(folder / EXPORT_FILES["step"])), spec
        )
        report["passed"] = report["passed"] and report["step_roundtrip"]["passed"]
        (folder / EXPORT_FILES["report"]).write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        if not report["passed"]:
            raise CadBuildError("The STEP export failed geometry checks after re-import.")
    result = ModelResult(
        model_id=model_id,
        created_at=datetime.now(timezone.utc).isoformat(),
        specification=specification,
        validation=report,
        downloads={kind: f"/api/models/{model_id}/files/{kind}" for kind in EXPORT_FILES},
    )
    (folder / "model.json").write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return result


def read_model(model_id: UUID) -> ModelResult:
    return ModelResult.model_validate_json((RUNS_DIR / str(model_id) / "model.json").read_text(encoding="utf-8"))


def exported_file(model_id: UUID, kind: str):
    read_model(model_id)
    return RUNS_DIR / str(model_id) / EXPORT_FILES[kind]

import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from uuid import UUID, uuid4

import cadquery as cq

from .config import PROJECTS_DIR
from .design_schema import Design
from .modelling import Builder, measure, verify_assembly
from .parameters import DesignError
from .project_lock import revision_lock
from .service import CAD_LOCK

PROJECT_LOCK = RLock()
logger = logging.getLogger(__name__)
EXPORTS = {"step": "assembly.step", "stl": "assembly.stl",
           "report": "verification.json", "project": "design.cad.json"}


class RevisionConflict(Exception):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_index(project_id):
    path = PROJECTS_DIR / str(UUID(str(project_id))) / "project.json"
    return json.loads(path.read_text(encoding="utf-8"))


def read_project(project_id):
    with PROJECT_LOCK:
        index = read_index(project_id)
        revision_id = index["revisions"][index["cursor"]]
        folder = PROJECTS_DIR / index["project_id"] / "revisions" / revision_id
        revision = json.loads((folder / "revision.json").read_text(encoding="utf-8"))
        revision.update(revision_number=index["cursor"] + 1, revision_count=len(index["revisions"]),
                        can_undo=index["cursor"] > 0, can_redo=index["cursor"] < len(index["revisions"]) - 1,
                        history=[json.loads((folder.parent / rid / "summary.json").read_text(encoding="utf-8"))
                                 for rid in index["revisions"]])
        return revision


def list_projects():
    with PROJECT_LOCK:
        result = []
        if not PROJECTS_DIR.exists():
            return result
        for path in PROJECTS_DIR.glob("*/project.json"):
            try:
                index = json.loads(path.read_text(encoding="utf-8"))
                result.append({key: index[key] for key in ("project_id", "name", "created_at", "updated_at")})
            except (OSError, KeyError, ValueError):
                continue
        return sorted(result, key=lambda item: item["updated_at"], reverse=True)


def check_revision(project_id, base_revision_id):
    project = read_project(project_id)
    if project["revision_id"] != str(base_revision_id):
        raise RevisionConflict("The project has changed. Reopen it before applying this edit.")
    return project


def verify_step(path, parts):
    imported = cq.importers.importStep(str(path)).solids().vals()
    remaining = list(imported)
    matched = []
    for part in parts:
        expected = measure(part.shape)
        found = None
        for index, shape in enumerate(remaining):
            actual = measure(shape)
            same = shape.isValid() and actual["solid_count"] == 1 and math.isclose(
                actual["volume_mm3"], expected["volume_mm3"], abs_tol=0.01, rel_tol=1e-5)
            same = same and all(math.isclose(a, b, abs_tol=0.01, rel_tol=1e-5)
                for a, b in zip(sum(actual["bounds_mm"], []), sum(expected["bounds_mm"], [])))
            if same:
                found = index
                break
        matched.append({"component_id": part.component.id, "passed": found is not None})
        if found is not None:
            remaining.pop(found)
    return {"passed": all(item["passed"] for item in matched) and not remaining,
            "solid_count": len(imported), "components": matched}


def save_revision(design: Design, *, project_id=None, base_revision_id=None,
                  summary="Created project", assumptions=None):
    is_new = project_id is None
    project_id = str(uuid4()) if is_new else str(UUID(str(project_id)))
    with PROJECT_LOCK, revision_lock(PROJECTS_DIR / project_id):
        return _save_revision(design, project_id=project_id, base_revision_id=base_revision_id,
                              summary=summary, assumptions=assumptions, is_new=is_new)


def _save_revision(design, *, project_id, base_revision_id, summary, assumptions, is_new):
    with PROJECT_LOCK:
        timestamp = now()
        previous = None
        if is_new:
            index = {"project_id": project_id, "name": design.name, "created_at": timestamp,
                     "updated_at": timestamp, "revisions": [], "cursor": -1}
        else:
            project_id = str(UUID(str(project_id)))
            previous = check_revision(project_id, base_revision_id)
            index = read_index(project_id)
        revision_id = str(uuid4())
        folder = PROJECTS_DIR / project_id / "revisions" / revision_id
        try:
            with CAD_LOCK:
                builder = Builder(design)
                parts = builder.build()
                validation = verify_assembly(builder, parts)
                if previous is not None:
                    old_parameters = {f"shared.{key}": value for key, value in previous["design"]["parameters"].items()}
                    for old_part in previous["design"]["components"]:
                        old_parameters.update({f"{old_part['id']}.{key}": value for key, value in old_part["parameters"].items()})
                    unused_changes = [key for key in validation["unused_parameters"]
                                      if old_parameters.get(key) != builder.parameters.raw[key]]
                    if unused_changes:
                        raise DesignError("The changed parameter does not drive geometry: " + ", ".join(unused_changes)
                                          + ". Update the feature values or link them to this parameter first.")
                folder.mkdir(parents=True)
                preview_folder = folder / "components"
                preview_folder.mkdir()
                assembly = cq.Assembly(name="project")
                component_results = []
                base_url = f"/api/projects/{project_id}/revisions/{revision_id}"
                for part in parts:
                    red, green, blue = (int(part.component.color[offset:offset + 2], 16) / 255 for offset in (1, 3, 5))
                    assembly.add(part.shape, name=part.component.id, color=cq.Color(red, green, blue))
                    cq.exporters.export(part.shape, str(preview_folder / f"{part.component.id}.stl"),
                                        tolerance=0.08, angularTolerance=0.15)
                    component_results.append({"id": part.component.id, "name": part.component.name,
                                              "color": part.component.color, "parameters": part.parameters,
                                              "features": part.features, "validation": part.validation,
                                              "preview_url": f"{base_url}/components/{part.component.id}.stl"})
                assembly.export(str(folder / EXPORTS["step"]), mode="default")
                cq.exporters.export(cq.Compound.makeCompound([part.shape for part in parts]),
                                    str(folder / EXPORTS["stl"]), tolerance=0.08, angularTolerance=0.15)
                validation["step_roundtrip"] = verify_step(folder / EXPORTS["step"], parts)
                validation["checks"]["step_roundtrip_valid"] = validation["step_roundtrip"]["passed"]
                validation["passed"] = all(validation["checks"].values())
                write_json(folder / EXPORTS["report"], validation)
                if not validation["passed"]:
                    raise DesignError("The STEP export did not preserve the separate solids, dimensions and volumes.")
                write_json(folder / EXPORTS["project"], design.model_dump(mode="json"))
        except DesignError:
            raise
        except Exception as error:
            logger.exception("CAD revision build or export failed")
            raise DesignError("The CAD revision could not be built or exported. The previous revision is still saved.") from error
        revision = {"project_id": project_id, "revision_id": revision_id, "name": design.name,
                    "created_at": index["created_at"], "saved_at": timestamp, "summary": summary,
                    "assumptions": assumptions or [], "design": design.model_dump(mode="json"),
                    "components": component_results, "validation": validation,
                    "downloads": {kind: f"{base_url}/files/{kind}" for kind in EXPORTS}}
        write_json(folder / "revision.json", revision)
        write_json(folder / "summary.json", {"revision_id": revision_id, "saved_at": timestamp, "summary": summary})
        index["revisions"] = index["revisions"][:index["cursor"] + 1] + [revision_id]
        index.update(cursor=len(index["revisions"]) - 1, updated_at=timestamp, name=design.name)
        # This atomic write is the only point at which a candidate becomes the current design.
        write_json(folder.parents[1] / "project.json", index)
        return read_project(project_id)


def move_revision(project_id, base_revision_id, delta):
    with PROJECT_LOCK, revision_lock(PROJECTS_DIR / str(UUID(str(project_id)))):
        check_revision(project_id, base_revision_id)
        index = read_index(project_id)
        cursor = index["cursor"] + delta
        if not 0 <= cursor < len(index["revisions"]):
            raise RevisionConflict("There is no revision to undo." if delta < 0 else "There is no revision to redo.")
        index.update(cursor=cursor, updated_at=now())
        write_json(PROJECTS_DIR / index["project_id"] / "project.json", index)
        return read_project(project_id)


def revision_file(project_id, revision_id, kind):
    read_index(project_id)
    folder = PROJECTS_DIR / str(UUID(str(project_id))) / "revisions" / str(UUID(str(revision_id)))
    path = folder / EXPORTS[kind]
    if not (folder / "revision.json").is_file() or not path.is_file():
        raise FileNotFoundError(path)
    return path


def component_file(project_id, revision_id, component_id):
    folder = revision_file(project_id, revision_id, "project").parent
    design = Design.model_validate_json((folder / EXPORTS["project"]).read_text(encoding="utf-8"))
    if component_id not in {part.id for part in design.components}:
        raise FileNotFoundError(component_id)
    path = folder / "components" / f"{component_id}.stl"
    if not path.is_file():
        raise FileNotFoundError(path)
    return path

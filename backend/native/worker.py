import json
import os
import sys
from pathlib import Path

# OCCT writes STEP transfer diagnostics directly to fd 1.
protocol = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8", buffering=1)
os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
sys.stdout = sys.stderr

from . import geometry
from .contracts import WorkspaceError
from .runtime_identity import RuntimeIdentity

RUNTIME_IDENTITY = RuntimeIdentity("geometry")

def checked_intersections(folder, before, after, command, **kwargs):
    stats = {}
    try:
        geometry.check_new_intersections(folder, before, after, command, stats=stats, **kwargs)
    except WorkspaceError as error:
        error.details = {**getattr(error, "details", {}), "intersection": dict(stats)}
        raise
    except Exception as error:
        error.details = {**getattr(error, "details", {}), "intersection": dict(stats)}
        raise
    after["_intersection_stats"] = stats
    return after


def emit(method, params):
    protocol.write(json.dumps({"jsonrpc": "2.0", "method": method, "params": params}, allow_nan=False) + "\n")


def dispatch(method, params):
    RUNTIME_IDENTITY.ensure_current()
    folder = params.get("project_dir")
    if method == "hello":
        import OCP
        return {"protocol_version": 1, "occt_version": OCP.__version__, "worker_pid": os.getpid(),
                "runtime_identity": RUNTIME_IDENTITY.report(private=True)}
    if method in ("standard_parts", "standard_part"):
        from backend.v2.process_limits import constrain_worker
        constrain_worker()
        from backend.v2.standard_parts import catalog, generate
        if method == "standard_parts":
            return catalog(params.get("request", {}))
        stats = {}
        try:
            return generate(folder, params["snapshot"], params["request"], intersection_stats=stats)
        except WorkspaceError as error:
            error.details = {**getattr(error, "details", {}), "intersection": dict(stats)}
            raise
        except Exception as error:
            error.details = {**getattr(error, "details", {}), "intersection": dict(stats)}
            raise
    if method == "import_step":
        return geometry.import_step(params["path"], folder)
    if method == "catalog_insert":
        from backend.v2.process_limits import constrain_worker

        constrain_worker()
        stats = {}
        try:
            return geometry.append_catalog_step(folder, params["snapshot"], params["path"],
                                                params["provenance"], params["placement"], stats)
        except WorkspaceError as error:
            error.details = {**getattr(error, "details", {}), "intersection": dict(stats)}
            raise
        except Exception as error:
            error.details = {**getattr(error, "details", {}), "intersection": dict(stats)}
            raise
    if method == "scale_mesh_scene":
        from backend.v2.meshes import load as load_mesh, store as store_mesh
        import copy
        candidate = copy.deepcopy(params["snapshot"])
        for part in candidate["components"]:
            mesh = load_mesh(folder, part)
            mesh.apply_scale(params["factor"])
            part.update(store_mesh(folder, mesh))
        return candidate
    if method == "import_mesh":
        from backend.v2.meshes import import_mesh
        return import_mesh(params["path"], folder, params["mm_per_unit"])
    if method == "from_recipe":
        return geometry.from_recipe(params["recipe"], folder)
    if method == "capabilities":
        from backend.v2.scripts import METHODS, CONSTRUCTORS
        import cadquery as cq
        receivers = {"Workplane": cq.Workplane, "Solid": cq.Solid, "Shape": cq.Shape,
                     "Compound": cq.Compound, "Face": cq.Face, "Wire": cq.Wire, "Edge": cq.Edge}
        return {"methods_by_receiver": {key: sorted(name for name in METHODS if callable(getattr(value, name, None))) for key, value in receivers.items()},
                "constructors": {key: sorted(name for name in value[1] if callable(getattr(value[0], name, None))) for key, value in CONSTRUCTORS.items()},
                "entry_points": ["cq.Workplane", "cq.Plane", "cq.Vector"],
                "statements": ["assignment", "tuple_unpacking", "subscript_assignment", "if", "bounded_for"],
                "instruction_budget": 30000, "collection_limit": 1000}
    if method == "inspect":
        return geometry.inspect(folder, params["snapshot"], params.get("instance_id"), params.get("limit", 128), params.get("offset", 0))
    if method == "measure":
        return geometry.measure_entities(folder, params["snapshot"], params["first"], params["second"])
    if method == "script":
        from backend.v2.scripts import execute
        from backend.v2.process_limits import constrain_worker
        constrain_worker()
        candidate = execute(folder, params["snapshot"], params["source"], params.get("parameters", {}), params.get("instance_id"), params.get("source_instance_ids"))
        return checked_intersections(folder, params["snapshot"], candidate, {"type": "script"})
    if method == "restructure":
        from backend.v2.component_edits import restructure
        from backend.v2.process_limits import constrain_worker
        constrain_worker()
        candidate = restructure(folder, params["snapshot"], params["request"])
        return checked_intersections(folder, params["snapshot"], candidate, {"type": "restructure"})
    if method == "apply_batch":
        stats = {}
        try:
            return geometry.apply_face_batch(folder, params["snapshot"], params["commands"], stats)
        except WorkspaceError as error:
            error.details = {**getattr(error, "details", {}), "intersection": dict(stats)}
            raise
        except Exception as error:
            error.details = {**getattr(error, "details", {}), "intersection": dict(stats)}
            raise
    if method == "apply":
        if params["command"].get("type") == "parameters" and any(
                p.get("standard_part") and p["instance_id"] == params["command"].get("instance_id")
                for p in params["snapshot"]["components"]):
            from backend.v2.process_limits import constrain_worker
            constrain_worker()
        candidate = geometry.apply_command(folder, params["snapshot"], params["command"])
        return checked_intersections(folder, params["snapshot"], candidate, params["command"])
    if method == "verify":
        snapshot = params["snapshot"]
        from backend.v2.meshes import verify as verify_meshes
        meshes = verify_meshes(folder, snapshot)
        import time
        started = time.perf_counter()
        timing = {}
        solids = {**snapshot, "components": [p for p in snapshot["components"] if p.get("representation") != "mesh"]}
        # Solid validity depends only on the stored asset: check each unique asset once (instances share it).
        checked = set()
        for part in solids["components"]:
            key = (part["asset_hash"], part.get("shape_kind") == "compound")
            if key in checked:
                continue
            geometry.check_solid(geometry.load_shape(folder, part), allow_compound=key[1])
            checked.add(key)
        timing["solid_checks_seconds"] = time.perf_counter() - started
        timing["unique_solids_checked"] = len(checked)
        if not solids["components"]:
            return {"passed": bool(meshes), "meshes": meshes, "mesh_interference": "Not evaluated; meshes are visual geometry, not engineering solids."}
        import tempfile
        with tempfile.TemporaryDirectory(dir=folder) as temporary:
            path = Path(temporary) / "verified.step"
            step_started = time.perf_counter()
            geometry.export_step(folder, solids, path)
            timing["step_export_seconds"] = time.perf_counter() - step_started
            report = geometry.verify_export(folder, solids, path, timing)
            timing["total_seconds"] = time.perf_counter() - started
            return {**report, "step_timing": timing, "meshes": meshes, "mesh_interference": "Not evaluated" if meshes else "No meshes"}
    if method == "export":
        snapshot = params["snapshot"]
        destination = Path(params["path"])
        import tempfile
        destination.parent.mkdir(parents=True, exist_ok=True)
        suffix = destination.suffix.lower()
        if suffix in (".step", ".stp") and any(p.get("representation") == "mesh" for p in snapshot["components"]):
            raise WorkspaceError("STEP export requires engineering solids. Export visual meshes as GLB or STL.")
        if suffix not in (".step", ".stp", ".stl", ".glb"):
            raise WorkspaceError("Choose a STEP or STL destination.")
        fd, temporary = tempfile.mkstemp(suffix=suffix, dir=destination.parent)
        os.close(fd)
        try:
            if suffix == ".glb" or (suffix == ".stl" and any(p.get("representation") == "mesh" for p in snapshot["components"])):
                import trimesh
                from backend.v2.meshes import load as load_mesh
                scene = trimesh.Scene()
                for part in snapshot["components"]:
                    if part.get("representation") == "mesh":
                        mesh = load_mesh(folder, part)
                        import numpy as np
                        pose = np.eye(4); pose[:3] = np.asarray(part["matrix"]).reshape(3,4)
                        mesh.apply_transform(pose)
                    else:
                        points, faces = geometry.world_shape(folder, part).tessellate(0.1)
                        mesh = trimesh.Trimesh(vertices=[p.toTuple() for p in points], faces=faces, process=False)
                    if part.get("representation") != "mesh" or part.get("color_override") is not None:
                        color = part.get("color_override", part["color"])
                        mesh.visual.face_colors = [round(value * 255) for value in color] + [255]
                    if suffix == ".glb":
                        mesh.unmerge_vertices()
                    scene.add_geometry(mesh, node_name=part["instance_id"], geom_name=part["name"])
                if suffix == ".stl":
                    scene.to_geometry().export(temporary, file_type="stl")
                else:
                    scene.export(temporary, file_type="glb")
                verification = {"passed": True, "format": suffix[1:].upper(), "retains_solid_topology": False}
            elif suffix == ".stl":
                import cadquery as cq
                cq.Compound.makeCompound([geometry.world_shape(folder, p) for p in snapshot["components"]]).exportStl(temporary)
                verification = {"passed": True, "format": "STL", "retains_solid_topology": False}
            else:
                geometry.export_step(folder, snapshot, temporary)
                verification = geometry.verify_export(folder, snapshot, temporary)
            os.replace(temporary, destination)
            return {"path": str(destination), "verification": verification,
                    "appearance": "STL does not retain component colours." if suffix == ".stl" else "Component colours encoded in export.",
                    "engineering_metadata": "Tolerances, dimensions and annotations remain in the project; STEP PMI and drawing export are not supported."}
        finally:
            Path(temporary).unlink(missing_ok=True)
    raise WorkspaceError("Unknown geometry method: " + method, "method_not_found")


def main():
    for line in sys.stdin:
        request = None
        try:
            request = json.loads(line)
            if request.get("jsonrpc") != "2.0" or not isinstance(request.get("params", {}), dict):
                raise WorkspaceError("Expected a JSON-RPC 2.0 object.", "invalid_request")
            result = dispatch(request["method"], request.get("params", {}))
            response = {"jsonrpc": "2.0", "id": request["id"], "result": result}
        except Exception as error:
            response = {"jsonrpc": "2.0", "id": request.get("id") if isinstance(request, dict) else None,
                        "error": {"code": -32000, "message": str(error),
                                  "data": {"code": getattr(error, "code", "geometry_failed"),
                                           **getattr(error, "details", {})}}}
        response["runtime_identity"] = RUNTIME_IDENTITY.report()
        protocol.write(json.dumps(response, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()

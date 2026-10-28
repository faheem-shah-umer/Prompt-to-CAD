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


def emit(method, params):
    protocol.write(json.dumps({"jsonrpc": "2.0", "method": method, "params": params}, allow_nan=False) + "\n")


def dispatch(method, params):
    folder = params.get("project_dir")
    if method == "hello":
        import OCP
        return {"protocol_version": 1, "occt_version": OCP.__version__, "worker_pid": os.getpid()}
    if method == "import_step":
        return geometry.import_step(params["path"], folder)
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
    if method == "inspect":
        return geometry.inspect(folder, params["snapshot"], params.get("instance_id"), params.get("limit", 128), params.get("offset", 0))
    if method == "measure":
        return geometry.measure_entities(folder, params["snapshot"], params["first"], params["second"])
    if method == "script":
        from backend.v2.scripts import execute
        from backend.v2.process_limits import constrain_worker
        constrain_worker()
        candidate = execute(folder, params["snapshot"], params["source"], params.get("parameters", {}), params.get("instance_id"))
        geometry.check_new_intersections(folder, params["snapshot"], candidate, {"type": "script"})
        return candidate
    if method == "apply":
        candidate = geometry.apply_command(folder, params["snapshot"], params["command"])
        geometry.check_new_intersections(folder, params["snapshot"], candidate, params["command"])
        return candidate
    if method == "verify":
        snapshot = params["snapshot"]
        from backend.v2.meshes import verify as verify_meshes
        meshes = verify_meshes(folder, snapshot)
        solids = {**snapshot, "components": [p for p in snapshot["components"] if p.get("representation") != "mesh"]}
        for part in solids["components"]:
            geometry.store_shape(folder, geometry.load_shape(folder, part))
        if not solids["components"]:
            return {"passed": bool(meshes), "meshes": meshes, "mesh_interference": "Not evaluated; meshes are visual geometry, not engineering solids."}
        import tempfile
        with tempfile.TemporaryDirectory(dir=folder) as temporary:
            path = Path(temporary) / "verified.step"
            geometry.export_step(folder, solids, path)
            return {**geometry.verify_export(folder, solids, path), "meshes": meshes, "mesh_interference": "Not evaluated" if meshes else "No meshes"}
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
            return {"path": str(destination), "verification": verification}
        finally:
            Path(temporary).unlink(missing_ok=True)
    if method == "generate":
        from backend.app import design_planner
        plan, inference = design_planner.interpret(params["prompt"], progress=lambda event: emit("progress", event))
        if plan.status != "ready":
            return {"status": plan.status, "message": plan.description, "questions": plan.questions}
        snapshot = geometry.from_recipe(plan.design.model_dump(mode="json"), folder)
        return {"status": "ready", "snapshot": snapshot, "inference": inference,
                "message": plan.description, "assumptions": plan.assumptions}
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
                                  "data": {"code": getattr(error, "code", "geometry_failed")}}}
        protocol.write(json.dumps(response, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()

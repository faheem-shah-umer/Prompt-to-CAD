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
    if method == "from_recipe":
        return geometry.from_recipe(params["recipe"], folder)
    if method == "inspect":
        return geometry.inspect(folder, params["snapshot"], params.get("instance_id"))
    if method == "apply":
        candidate = geometry.apply_command(folder, params["snapshot"], params["command"])
        geometry.check_new_intersections(folder, params["snapshot"], candidate, params["command"])
        return candidate
    if method == "verify":
        snapshot = params["snapshot"]
        for part in snapshot["components"]:
            geometry.store_shape(folder, geometry.load_shape(folder, part))
        import tempfile
        with tempfile.TemporaryDirectory(dir=folder) as temporary:
            path = Path(temporary) / "verified.step"
            geometry.export_step(folder, snapshot, path)
            return geometry.verify_export(folder, snapshot, path)
    if method == "export":
        snapshot = params["snapshot"]
        destination = Path(params["path"])
        import tempfile
        destination.parent.mkdir(parents=True, exist_ok=True)
        suffix = destination.suffix.lower()
        if suffix not in (".step", ".stp", ".stl"):
            raise WorkspaceError("Choose a STEP or STL destination.")
        fd, temporary = tempfile.mkstemp(suffix=suffix, dir=destination.parent)
        os.close(fd)
        try:
            if suffix == ".stl":
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

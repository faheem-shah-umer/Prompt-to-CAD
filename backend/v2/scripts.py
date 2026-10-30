"""A deliberately restricted CAD language, interpreted without Python exec/eval."""

import ast
import copy
import math
import operator
from types import SimpleNamespace

import cadquery as cq
from backend.native import geometry
from backend.native.contracts import WorkspaceError

METHODS = set(
    "box sphere cylinder cone rect circle ellipse polygon polyline lineTo moveTo move line hLine vLine hLineTo vLineTo threePointArc radiusArc spline bezier close wire toPending workplane center transformed pushPoints rarray polarArray extrude revolve loft sweep hole cutBlind cutThruAll shell fillet chamfer union cut intersect add faces edges vertices wires solids vals val translate rotate mirror clean fuse makeBox makeCylinder makeSphere makeCone makeTorus makePolygon makeCircle makeEllipse makeLine makeThreePointArc makeSpline makeLoft extrudeLinear".split()
)


def bounded_range(n):
    if type(n) != int or not 0 <= n <= 1000:
        raise WorkspaceError("CAD loops require an integer from 0 to 1,000.")
    return range(n)


class Interpreter:
    def __init__(self, parameters, selected=None):
        self.scope = {
            "cq": SimpleNamespace(Workplane=cq.Workplane, Plane=cq.Plane, Vector=cq.Vector),
            "params": parameters,
            "selected": selected,
            "pi": math.pi,
            "sin": math.sin,
            "cos": math.cos,
            "sqrt": math.sqrt,
            "range": bounded_range,
            "min": min,
            "max": max,
            "abs": abs,
        }
        self.steps = 0

    def evaluate(self, node):
        self.steps += 1
        if self.steps > 30000:
            raise WorkspaceError("The CAD script exceeded its instruction budget.")
        ev = self.evaluate
        if isinstance(node, ast.Constant) and isinstance(node.value, (str, int, float, bool, type(None))):
            if isinstance(node.value, str) and len(node.value) > 2000:
                raise WorkspaceError("CAD script string is too long.")
            return node.value
        if isinstance(node, ast.Name) and not node.id.startswith("_"):
            return self.scope[node.id]
        if isinstance(node, (ast.List, ast.Tuple)):
            return [ev(x) for x in node.elts]
        if isinstance(node, ast.Dict):
            return {ev(k): ev(v) for k, v in zip(node.keys, node.values)}
        if isinstance(node, ast.Subscript):
            value, key = ev(node.value), ev(node.slice)
            if not isinstance(value, (dict, list, tuple)):
                raise WorkspaceError("Only parameters and literal collections support indexing.")
            return value[key]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            value = ev(node.operand)
            if type(value) not in (int, float):
                raise WorkspaceError("Unary arithmetic requires a number.")
            return -value if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.BinOp):
            a, b = ev(node.left), ev(node.right)
            operations = {
                ast.Add: operator.add,
                ast.Sub: operator.sub,
                ast.Mult: operator.mul,
                ast.Div: operator.truediv,
                ast.Mod: operator.mod,
            }
            if type(a) not in (int, float) or type(b) not in (int, float) or type(node.op) not in operations:
                raise WorkspaceError("CAD script arithmetic supports finite numbers only.")
            result = operations[type(node.op)](a, b)
            if not math.isfinite(result) or abs(result) > 1e9:
                raise WorkspaceError("CAD script arithmetic exceeded its numeric range.")
            return result
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id not in ("range", "min", "max", "abs", "sin", "cos", "sqrt"):
                    raise WorkspaceError("This function is not in the CAD language.")
                function = self.scope[node.func.id]
            elif isinstance(node.func, ast.Attribute):
                target, name = ev(node.func.value), node.func.attr
                if target is self.scope["cq"] and name in ("Workplane", "Plane", "Vector"):
                    function = getattr(target, name)
                elif isinstance(target, (cq.Workplane, cq.Shape)) and name in METHODS:
                    function = getattr(target, name)
                else:
                    raise WorkspaceError("This CAD method is not allowed: " + name)
            else:
                raise WorkspaceError("Only named CAD calls are allowed.")
            if any(k.arg is None for k in node.keywords) or any(isinstance(x, ast.Starred) for x in node.args):
                raise WorkspaceError("Argument expansion is not supported.")
            return function(*[ev(x) for x in node.args], **{x.arg: ev(x.value) for x in node.keywords})
        raise WorkspaceError("Unsupported CAD language expression: " + type(node).__name__)

    def statements(self, statements):
        for node in statements:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                if name.startswith("_") or name in (
                    "cq",
                    "selected",
                    "params",
                    "range",
                    "min",
                    "max",
                    "abs",
                    "sin",
                    "cos",
                    "sqrt",
                ):
                    raise WorkspaceError("This name is reserved by the CAD language.")
                self.scope[name] = self.evaluate(node.value)
            elif isinstance(node, ast.Expr):
                self.evaluate(node.value)
            elif isinstance(node, ast.For) and isinstance(node.target, ast.Name) and not node.orelse:
                values = self.evaluate(node.iter)
                if not isinstance(values, (list, tuple, range)) or len(values) > 1000 or node.target.id in self.scope:
                    raise WorkspaceError("Use a fresh loop variable and at most 1,000 literal iterations.")
                for value in values:
                    self.scope[node.target.id] = value
                    self.statements(node.body)
                self.scope.pop(node.target.id, None)
            else:
                raise WorkspaceError("Unsupported CAD statement: " + type(node).__name__)


def execute(folder, snapshot, source, parameters, instance_id=None):
    if not isinstance(source, str) or len(source) > 50000:
        raise WorkspaceError("Use a CAD script of at most 50,000 characters.")
    if len(parameters) > 64 or any(
        not isinstance(k, str) or type(v) not in (float, int) or not math.isfinite(v) or abs(v) > 1e6
        for k, v in parameters.items()
    ):
        raise WorkspaceError("CAD parameters must be named finite numbers.")
    target = next((p for p in snapshot["components"] if p["instance_id"] == instance_id), None)
    if instance_id and not target:
        raise WorkspaceError("The target is no longer present.", "stale_selection")
    interpreter = Interpreter(parameters, geometry.load_shape(folder, target) if target else None)
    interpreter.statements(ast.parse(source, mode="exec").body)
    parts = interpreter.scope.get("parts")
    if not isinstance(parts, dict) or not 1 <= len(parts) <= 100:
        raise WorkspaceError("Assign parts = {name: solid, ...}. Each part must contain exactly one solid.")
    if target and (len(parts) != 1 or next(iter(parts)) != instance_id):
        raise WorkspaceError(
            "A selected-component script must return only its existing instance ID.", "scope_violation"
        )
    candidate = copy.deepcopy(snapshot)
    components = []
    for name, result in parts.items():
        if not isinstance(name, str) or not name or len(name) > 128:
            raise WorkspaceError("Part IDs must be short names.")
        if isinstance(result, cq.Workplane):
            values = result.vals()
            if len(values) != 1:
                raise WorkspaceError("Each part must return one solid, not a stack of shapes.")
            result = values[0]
        if not isinstance(result, cq.Shape):
            raise WorkspaceError("Each script result must be CAD geometry.")
        old = next((p for p in snapshot["components"] if p["instance_id"] == name), None)
        component = (
            copy.deepcopy(old)
            if old
            else {
                "instance_id": name,
                "name": name,
                "parent_id": None,
                "color": [0.55, 0.72, 0.9],
                "matrix": geometry.IDENTITY,
            }
        )
        component.update(geometry.store_shape(folder, result), definition_id=name + "-script", parameters=parameters)
        components.append(component)
    if target:
        replacement = components[0]
        candidate["components"] = [
            replacement if p["instance_id"] == instance_id else p for p in candidate["components"]
        ]
    else:
        # Creation adds parts, without silently removing an existing assembly.
        old_ids = {p["instance_id"] for p in snapshot["components"]}
        if old_ids.intersection(parts):
            raise WorkspaceError("Select an existing component before replacing it.")
        candidate["components"].extend(components)
    candidate.update(origin="script", direct_edits=True)
    candidate.setdefault("scripts", []).append(
        {
            "source": source,
            "parameters": parameters,
            "instance_id": instance_id,
            "part_ids": list(parts),
            "input_components": copy.deepcopy(snapshot["components"]),
            "output_hashes": {p["instance_id"]: p["asset_hash"] for p in components},
        }
    )
    return candidate


def change_parameters(folder, snapshot, instance_id, values):
    definition = next((s for s in reversed(snapshot.get("scripts", [])) if instance_id in s.get("part_ids", [])), None)
    if not definition or not values.keys() <= definition["parameters"].keys():
        raise WorkspaceError("Only existing named script parameters can be changed.")
    current = next(p for p in snapshot["components"] if p["instance_id"] == instance_id)
    if current["asset_hash"] != definition.get("output_hashes", {}).get(instance_id):
        raise WorkspaceError("Undo downstream solid edits before regenerating this script definition.")
    parameters = {**definition["parameters"], **values}
    base = {
        "components": copy.deepcopy(definition["input_components"]),
        "assembly_nodes": snapshot.get("assembly_nodes", []),
    }
    rebuilt = execute(folder, base, definition["source"], parameters, definition["instance_id"])
    target = next(p for p in rebuilt["components"] if p["instance_id"] == instance_id)
    candidate = copy.deepcopy(snapshot)
    current = next(p for p in candidate["components"] if p["instance_id"] == instance_id)
    # Manual assembly placement survives regeneration of the local definition.
    target["matrix"], target["parent_id"] = current["matrix"], current["parent_id"]
    candidate["components"] = [target if p["instance_id"] == instance_id else p for p in candidate["components"]]
    candidate["scripts"].append(
        {
            **copy.deepcopy(definition),
            "parameters": parameters,
            "part_ids": [instance_id],
            "output_hashes": {instance_id: target["asset_hash"]},
        }
    )
    return candidate

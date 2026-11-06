"""A deliberately restricted CAD language, interpreted without Python exec/eval."""

import ast
import copy
import math
import operator
from types import SimpleNamespace
from uuid import uuid4

import cadquery as cq
from backend.native import geometry
from backend.native.contracts import WorkspaceError
from .gears import gear, planet_mesh_rotation, ring_mesh_rotation

METHODS = set(
    "box sphere cylinder cone rect circle ellipse polygon polyline lineTo moveTo move line hLine vLine hLineTo vLineTo threePointArc radiusArc spline bezier close wire toPending workplane center transformed pushPoints rarray polarArray extrude revolve loft sweep hole cutBlind cutThruAll shell fillet chamfer union cut intersect add faces edges vertices wires solids vals val translate rotate mirror clean fuse makeBox makeCylinder makeSphere makeCone makeTorus makePolygon makeCircle makeEllipse makeLine makeThreePointArc makeSpline makeLoft extrudeLinear".split()
)
METHODS.update("split Solids Faces Edges Wires Vertices Volume Center BoundingBox copy tag workplaneFromTagged offset2D text size item end newObject toTuple".split())
CONSTRUCTORS = {
    "Solid": (cq.Solid, {"makeBox", "makeCylinder", "makeSphere", "makeCone", "makeTorus", "makeLoft", "extrudeLinear"}),
    "Compound": (cq.Compound, {"makeCompound"}),
    "Face": (cq.Face, {"makeFromWires", "makePlane"}),
    "Wire": (cq.Wire, {"makePolygon", "makeCircle", "makeEllipse"}),
    "Edge": (cq.Edge, {"makeLine", "makeCircle", "makeEllipse", "makeSpline", "makeThreePointArc"}),
}


def bounded_range(n):
    if type(n) != int or not 0 <= n <= 1000:
        raise WorkspaceError("CAD loops require an integer from 0 to 1,000.")
    return range(n)


def cad_string(value):
    if type(value) not in (str, int, float, bool):
        raise WorkspaceError("str accepts literal values only.", "script_syntax")
    return str(value)


def cad_integer(value):
    if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 1e6:
        raise WorkspaceError("int requires a bounded finite number.", "script_limit")
    return int(value)


class Interpreter:
    def __init__(self, parameters, selected=None, inputs=None):
        self.scope = {
            "cq": SimpleNamespace(Workplane=cq.Workplane, Plane=cq.Plane, Vector=cq.Vector,
                                  **{name: value[0] for name, value in CONSTRUCTORS.items()}),
            "params": parameters,
            "selected": selected,
            "inputs": inputs or {},
            "pi": math.pi,
            "sin": math.sin,
            "cos": math.cos,
            "sqrt": math.sqrt,
            "range": bounded_range,
            "min": min,
            "max": max,
            "abs": abs,
            "len": len,
            "str": cad_string,
            "int": cad_integer,
            "tan": math.tan,
            "atan2": math.atan2,
            "asin": math.asin,
            "acos": math.acos,
            "floor": math.floor,
            "ceil": math.ceil,
            "round": round,
            "involute_gear": gear,
            "planet_mesh_rotation": planet_mesh_rotation,
            "ring_mesh_rotation": ring_mesh_rotation,
        }
        self.reserved = set(self.scope)
        self.steps = 0

    def bounded(self, value):
        if isinstance(value, (list, tuple, dict)) and len(value) > 1000:
            raise WorkspaceError("CAD collections are limited to 1,000 entries.", "script_limit")
        if isinstance(value, str) and len(value) > 2000:
            raise WorkspaceError("CAD strings are limited to 2,000 characters.", "script_limit")
        return value

    def assign(self, target, value):
        if isinstance(target, ast.Name):
            if target.id.startswith("_") or target.id in self.reserved:
                raise WorkspaceError("This name is reserved by the CAD language.", "script_syntax")
            self.scope[target.id] = self.bounded(value)
        elif isinstance(target, (ast.Tuple, ast.List)):
            if not isinstance(value, (list, tuple)) or len(target.elts) != len(value):
                raise WorkspaceError("Tuple assignment needs matching values.", "script_syntax")
            for name, entry in zip(target.elts, value):
                self.assign(name, entry)
        elif isinstance(target, ast.Subscript):
            container, key = self.evaluate(target.value), self.evaluate(target.slice)
            if not isinstance(container, (list, dict)) or container is self.scope["params"] or container is self.scope["inputs"]:
                raise WorkspaceError("Only script-owned collections can be assigned.", "script_syntax")
            if isinstance(container, dict) and not isinstance(key, (str, int)):
                raise WorkspaceError("Collection keys must be strings or integers.", "script_syntax")
            container[key] = value
            self.bounded(container)
        else:
            raise WorkspaceError("This assignment is not allowed.", "script_syntax")

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
            return self.bounded([ev(x) for x in node.elts])
        if isinstance(node, ast.Dict):
            if any(k is None for k in node.keys):
                raise WorkspaceError("Dictionary expansion is not supported.", "script_syntax")
            return self.bounded({ev(k): ev(v) for k, v in zip(node.keys, node.values)})
        if isinstance(node, ast.Attribute):
            target, name = ev(node.value), node.attr
            if target is self.scope["cq"] and name in CONSTRUCTORS:
                return CONSTRUCTORS[name][0]
            if isinstance(target, cq.Vector) and name in ("x", "y", "z", "Length"):
                return getattr(target, name)
            if isinstance(target, cq.BoundBox) and name in ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax", "xlen", "ylen", "zlen", "DiagonalLength"):
                return getattr(target, name)
            raise WorkspaceError("This CAD attribute is not available: " + name, "unsupported_operation")
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
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return not bool(ev(node.operand))
        if isinstance(node, ast.BoolOp):
            result = ev(node.values[0])
            for item in node.values[1:]:
                if isinstance(node.op, ast.And) and not result or isinstance(node.op, ast.Or) and result:
                    break
                result = ev(item)
            return result
        if isinstance(node, ast.Compare):
            first = ev(node.left)
            comparisons = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt,
                           ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge,
                           ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b}
            for op, other in zip(node.ops, node.comparators):
                second = ev(other)
                if type(op) not in comparisons:
                    raise WorkspaceError("Unsupported comparison.", "script_syntax")
                if not comparisons[type(op)](first, second):
                    return False
                first = second
            return True
        if isinstance(node, ast.IfExp):
            return ev(node.body if ev(node.test) else node.orelse)
        if isinstance(node, ast.JoinedStr):
            return self.bounded("".join(ev(value) for value in node.values))
        if isinstance(node, ast.FormattedValue):
            if node.format_spec is not None or node.conversion not in (-1, 115):
                raise WorkspaceError("Use simple literal f-strings without format specifications.", "script_syntax")
            return cad_string(ev(node.value))
        if isinstance(node, ast.BinOp):
            a, b = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Add) and isinstance(a, str) and isinstance(b, str):
                return self.bounded(a + b)
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
                if node.func.id not in ("range", "min", "max", "abs", "sin", "cos", "sqrt", "len", "str", "int", "tan", "atan2", "asin", "acos", "floor", "ceil", "round",
                                        "involute_gear", "planet_mesh_rotation", "ring_mesh_rotation"):
                    raise WorkspaceError("This function is not in the CAD language.")
                function = self.scope[node.func.id]
            elif isinstance(node.func, ast.Attribute):
                target, name = ev(node.func.value), node.func.attr
                if target is self.scope["cq"] and name in ("Workplane", "Plane", "Vector"):
                    function = getattr(target, name)
                elif any(target is value[0] and name in value[1] for value in CONSTRUCTORS.values()):
                    function = getattr(target, name)
                elif isinstance(target, (cq.Workplane, cq.Shape)) and name in METHODS:
                    function = getattr(target, name)
                elif isinstance(target, cq.Vector) and name in ("add", "sub", "multiply", "normalized", "dot", "cross", "toTuple"):
                    function = getattr(target, name)
                elif isinstance(target, list) and name == "append" and len(target) < 1000:
                    function = target.append
                elif isinstance(target, dict) and name in ("keys", "values", "items", "get"):
                    function = lambda *args: list(getattr(target, name)(*args)) if name != "get" else target.get(*args)
                else:
                    raise WorkspaceError("This CAD method is not allowed: " + name)
            else:
                raise WorkspaceError("Only named CAD calls are allowed.")
            if any(k.arg is None for k in node.keywords) or any(isinstance(x, ast.Starred) for x in node.args):
                raise WorkspaceError("Argument expansion is not supported.")
            if any(k.arg == "fontPath" for k in node.keywords):
                raise WorkspaceError("Text geometry uses installed font names, not filesystem font paths.", "unsupported_operation")
            if isinstance(node.func, ast.Attribute) and node.func.attr == "text" and len(node.args) > 6 and ev(node.args[6]) is not None:
                raise WorkspaceError("Text geometry cannot load a font path.", "unsupported_operation")
            return self.bounded(function(*[ev(x) for x in node.args], **{x.arg: ev(x.value) for x in node.keywords}))
        raise WorkspaceError("Unsupported CAD language expression: " + type(node).__name__)

    def statements(self, statements):
        for node in statements:
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                self.assign(node.targets[0], self.evaluate(node.value))
            elif isinstance(node, ast.Expr):
                self.evaluate(node.value)
            elif isinstance(node, ast.If):
                self.statements(node.body if self.evaluate(node.test) else node.orelse)
            elif isinstance(node, ast.For) and isinstance(node.target, (ast.Name, ast.Tuple)) and not node.orelse:
                values = self.evaluate(node.iter)
                if not isinstance(values, (list, tuple, range)) or len(values) > 1000:
                    raise WorkspaceError("Use at most 1,000 literal iterations.")
                for value in values:
                    self.assign(node.target, value)
                    self.statements(node.body)
            else:
                raise WorkspaceError("Unsupported CAD statement: " + type(node).__name__)


def run_source(source, parameters, inputs=None):
    parts, colors, _ = run_script(source, parameters, inputs)
    return parts, colors


def run_script(source, parameters, inputs=None):
    """Run a CAD script; returns parts, colours and optional instances of identical parts."""
    if not isinstance(source, str) or not source.strip() or len(source) > 50000:
        raise WorkspaceError("Use a CAD script of 1–50,000 characters.", "script_syntax")
    if not isinstance(parameters, dict) or len(parameters) > 64 or any(
        not isinstance(k, str) or type(v) not in (float, int) or not math.isfinite(v) or abs(v) > 1e6
        for k, v in parameters.items()
    ):
        raise WorkspaceError("CAD parameters must be named finite numbers.", "invalid_parameters")
    inputs = inputs or {}
    interpreter = Interpreter(parameters, next(iter(inputs.values())) if len(inputs) == 1 else None, inputs)
    try:
        interpreter.statements(ast.parse(source, mode="exec").body)
    except SyntaxError as error:
        raise WorkspaceError(f"CAD script syntax error at line {error.lineno}: {error.msg}", "script_syntax") from None
    except (KeyError, AttributeError, TypeError, ValueError, IndexError) as error:
        raise WorkspaceError("CAD script failed: " + str(error), "script_failed") from None
    return interpreter.scope.get("parts"), interpreter.scope.get("colors", {}), interpreter.scope.get("instances")


def execute(folder, snapshot, source, parameters, instance_id=None, source_instance_ids=None):
    from .component_edits import targets, input_shapes, publish

    identities = source_instance_ids if source_instance_ids is not None else [instance_id] if instance_id else []
    sources = targets(snapshot, identities) if identities else []
    outputs, colors, instances = run_script(source, parameters, input_shapes(folder, snapshot, sources))
    return publish(folder, snapshot, sources, outputs, kind="replace" if sources else "create",
                   parameters=parameters, source=source, colors=colors, instances=instances)


def change_parameters(folder, snapshot, instance_id, values):
    definition = next((s for s in reversed(snapshot.get("scripts", [])) if instance_id in s.get("part_ids", [])), None)
    if not definition or not values.keys() <= definition["parameters"].keys():
        raise WorkspaceError("Only existing named script parameters can be changed.", "missing_parameter")
    lookup = {p["instance_id"]: p for p in snapshot["components"]}
    for identity in definition["part_ids"]:
        if identity not in lookup or lookup[identity]["asset_hash"] != definition.get("output_hashes", {}).get(identity):
            raise WorkspaceError("Undo downstream edits to this definition before regenerating its parameters.", "definition_conflict")
    parameters = {**definition["parameters"], **values}
    base = {"components": copy.deepcopy(definition["input_components"]),
            "assembly_nodes": snapshot.get("assembly_nodes", [])}
    rebuilt = execute(folder, base, definition["source"], parameters, definition.get("instance_id"), definition.get("source_instance_ids"))
    fresh = rebuilt["scripts"][-1]
    old_names = definition.get("output_names", {identity: identity for identity in definition["part_ids"]})
    if set(fresh["output_names"]) != set(old_names):
        raise WorkspaceError("This parameter changes the output component set. Use an explicit replacement transaction.", "component_set_changed")
    rebuilt_parts = {p["instance_id"]: p for p in rebuilt["components"]}
    candidate = copy.deepcopy(snapshot)
    replacements = {}
    for label, old_id in old_names.items():
        target = copy.deepcopy(rebuilt_parts[fresh["output_names"][label]])
        current = lookup[old_id]
        generated = definition.get("instance_matrices", {}).get(old_id)
        for key in ("matrix", "parent_id", "name", "color", "color_override"):
            # An instance placement still at its generated value follows the new parameters.
            if key == "matrix" and generated is not None and current.get("matrix") == generated:
                continue
            if key in current:
                target[key] = copy.deepcopy(current[key])
        target["instance_id"] = old_id
        replacements[old_id] = target
    candidate["components"] = [replacements.get(p["instance_id"], p) for p in candidate["components"]]
    candidate.setdefault("scripts", []).append({**copy.deepcopy(definition), "parameters": parameters,
        "output_hashes": {identity: p["asset_hash"] for identity, p in replacements.items()},
        "instance_matrices": {identity: list(replacements[identity]["matrix"])
                              for identity in definition.get("instance_matrices", {}) if identity in replacements}})
    from .definitions import stage
    stage(candidate, "parameters-" + uuid4().hex + ".cad.py", definition["source"], list(replacements), parameters)
    return candidate

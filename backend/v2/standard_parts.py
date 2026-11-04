"""Controlled cq_warehouse generators; import only in disposable workers.

Bearing construction and native-copy adapters derive from cq_warehouse
bearing.py/extensions.py, Copyright 2022 Gumyr, Apache License 2.0.
Modified for separate physical members and CadQuery 2.7 native shape copying.
See docs/licenses/cq-warehouse.md for attribution and the full license.
"""

import copy
import importlib
import inspect
import math
import warnings
from uuid import uuid4

import cadquery as cq
from cadquery.occ_impl.shapes import downcast
from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy

from backend.native import geometry
from backend.native.contracts import WorkspaceError

REVISION = "a57bb7a24762d367d66369f280a24c38a64e73dd"
GENERATORS = {
    "fastener": (
        "DomedCapNut", "BradTeeNut", "HeatSetNut", "HexNut", "HexNutWithFlange",
        "UnchamferedHexagonNut", "SquareNut", "ButtonHeadScrew",
        "ButtonHeadWithCollarScrew", "CheeseHeadScrew", "CounterSunkScrew",
        "HexHeadScrew", "HexHeadWithFlangeScrew", "PanHeadScrew",
        "PanHeadWithCollarScrew", "RaisedCheeseHeadScrew",
        "RaisedCounterSunkOvalHeadScrew", "SetScrew", "SocketHeadCapScrew",
        "PlainWasher", "ChamferedWasher", "CheeseHeadWasher",
    ),
    "bearing": (
        "SingleRowDeepGrooveBallBearing", "SingleRowCappedDeepGrooveBallBearing",
        "SingleRowAngularContactBallBearing", "SingleRowCylindricalRollerBearing",
        "SingleRowTaperedRollerBearing",
    ),
    "sprocket": ("Sprocket",),
    "chain": ("Chain",),
    "thread": ("Thread", "IsoThread", "AcmeThread", "MetricTrapezoidalThread", "PlasticBottleThread"),
}


def generator(identity):
    if not isinstance(identity, str) or identity.count(".") != 1:
        raise WorkspaceError("Choose a generator_id from cad_standard_parts.", "invalid_generator")
    family, name = identity.split(".")
    if name not in GENERATORS.get(family, ()):
        raise WorkspaceError("This physical generator is not registered.", "invalid_generator")
    try:
        # Upstream fasteners and assemblies rely on these monkeypatches.
        import cq_warehouse.extensions  # noqa: F401
        cq.Shape.copy = _copy_shape
        cq.Shape.__deepcopy__ = _deepcopy_shape
        module = importlib.import_module("cq_warehouse." + family)
        if family == "fastener":
            # CQ 2.7 already queues closed wires. Upstream's extra toPending()
            # duplicates the washer profile and produces overlapping shells.
            module.Washer.make_washer = _make_washer
        elif family == "bearing":
            module.Bearing.make_bearing = _make_bearing
        return getattr(module, name)
    except ImportError as error:
        raise WorkspaceError("Install the pinned cq_warehouse dependency from requirements.txt in this runtime.", "dependency_missing") from error


def _make_washer(washer):
    return washer.washer_profile().revolve()


def _make_bearing(bearing):
    # Keep the upstream race/roller/cap geometry as separate physical members,
    # rather than fusing it into one solid (cq_warehouse bearing.py, Apache-2.0).
    members = [cq.Workplane("XZ").add(section().val()).toPending().revolve().val()
               for section in (bearing.outer_race_section, bearing.inner_race_section)]
    if bearing.capped:
        members.extend([bearing.cap().val(), bearing.cap().mirror("XY").val().translate((0, 0, bearing.bearing_dict["B"]))])
    else:
        for location in cq.Workplane("XY").polarArray(bearing.race_center_radius, 0, 360, bearing.roller_count).vals():
            members.append(bearing.roller().located(location * cq.Location(cq.Vector(0, 0, bearing.bearing_dict["B"] / 2))))
        if bearing.method_exists("cage"):
            members.append(bearing.cage())
    return cq.Compound.makeCompound([solid for member in members for solid in member.Solids()])


def _copy_shape(shape, mesh=False, memo=None):
    # Upstream deepcopy uses CQ 2.7's pickle reducer, which can fail reading
    # spline edges. Copy native topology directly while retaining subclass data.
    memo = {} if memo is None else memo
    if id(shape) in memo:
        return memo[id(shape)]
    result = type(shape).__new__(type(shape))
    memo[id(shape)] = result
    result.__dict__.update({key: copy.deepcopy(value, memo) for key, value in shape.__dict__.items() if key != "wrapped"})
    result.wrapped = downcast(BRepBuilderAPI_Copy(shape.wrapped, True, mesh).Shape())
    return result


def _deepcopy_shape(shape, memo):
    return _copy_shape(shape, memo=memo)


def parameter_schema(name, parameter):
    if name in ("simple", "external"):
        spec = {"type": "boolean"}
    elif name in ("size", "fastener_type", "bearing_type"):
        spec = {"type": "string", "maxLength": 100}
    elif name == "hand":
        spec = {"enum": ["right", "left"]}
    elif name == "end_finishes":
        spec = {"type": "array", "minItems": 2, "maxItems": 2,
                "items": {"enum": ["raw", "square", "fade", "chamfer"]}}
    elif name == "spkt_teeth":
        spec = {"type": "array", "minItems": 2, "maxItems": 32,
                "items": {"type": "integer", "minimum": 3, "maximum": 1000}}
    elif name == "positive_chain_wrap":
        spec = {"type": "array", "minItems": 2, "maxItems": 32, "items": {"type": "boolean"}}
    elif name in ("spkt_locations", "spkt_normal"):
        vector = {"type": "array", "minItems": 2 if name == "spkt_locations" else 3,
                  "maxItems": 3, "items": {"type": "number", "minimum": -10000, "maximum": 10000}}
        spec = {"type": "array", "minItems": 2, "maxItems": 32, "items": vector} if name == "spkt_locations" else vector
    elif name in ("num_teeth", "num_mount_bolts"):
        spec = {"type": "integer", "minimum": 3 if name == "num_teeth" else 0, "maximum": 1000}
    else:
        spec = {"type": "number", "minimum": -10000, "maximum": 10000}
        if name == "taper_angle":
            spec["nullable"] = True
    if parameter.default is not inspect.Parameter.empty:
        spec["default"] = False if name == "simple" else parameter.default
    return spec


def describe(identity, standard=None):
    cls = generator(identity)
    fields = {name: parameter_schema(name, p) for name, p in inspect.signature(cls).parameters.items()}
    types = sorted(cls.types()) if hasattr(cls, "types") else []
    if standard is not None and standard not in types:
        raise WorkspaceError("Choose a standard reported by this generator.", "invalid_parameters")
    sizes = {kind: list(cls.sizes(kind)) for kind in ([standard] if standard else types)}
    if not types and hasattr(cls, "sizes"):
        sizes = {"sizes": list(cls.sizes())}
    return {"generator_id": identity, "dependency_revision": REVISION,
            "parameters": fields, "required": [n for n, s in fields.items() if "default" not in s],
            "standards": types, "sizes": sizes, "units": "mm (including imperial catalog sizes converted by upstream)",
            "thread_geometry": "Detailed by default; simple must be explicitly requested where available."}


def catalog(request):
    if request.get("generator_id"):
        return describe(request["generator_id"], request.get("standard"))
    family = request.get("family")
    if family and family not in GENERATORS:
        raise WorkspaceError("Unknown component family.", "invalid_generator")
    return {"dependency_revision": REVISION, "families": {
        key: [key + "." + name for name in names]
        for key, names in GENERATORS.items() if not family or key == family}}


def validate_value(value, spec, name):
    if value is None and spec.get("nullable"):
        return
    valid = True
    kind = spec.get("type")
    if "enum" in spec:
        valid = isinstance(value, str) and value in spec["enum"]
    elif kind == "boolean":
        valid = type(value) is bool
    elif kind in ("number", "integer"):
        valid = type(value) in ((int,) if kind == "integer" else (int, float)) and math.isfinite(value) and spec["minimum"] <= value <= spec["maximum"]
    elif kind == "string":
        valid = isinstance(value, str) and 0 < len(value) <= spec["maxLength"]
    elif kind == "array":
        valid = isinstance(value, (list, tuple)) and spec["minItems"] <= len(value) <= spec["maxItems"]
        if valid:
            for child in value:
                validate_value(child, spec["items"], name)
    if not valid:
        raise WorkspaceError(f"Invalid typed parameter '{name}'; consult cad_standard_parts.", "invalid_parameters")


def checked_parameters(identity, values):
    description = describe(identity)
    fields = description["parameters"]
    if not isinstance(values, dict) or values.keys() - fields.keys():
        raise WorkspaceError("Only registered generator parameters are accepted.", "invalid_parameters")
    result = {name: copy.deepcopy(spec["default"]) for name, spec in fields.items() if "default" in spec}
    result.update(values)
    if set(description["required"]) - result.keys():
        raise WorkspaceError("Missing parameters: " + ", ".join(sorted(set(description["required"]) - result.keys())), "invalid_parameters")
    for name, value in result.items():
        validate_value(value, fields[name], name)
    standard = result.get("fastener_type", result.get("bearing_type"))
    if standard is not None and (standard not in description["standards"] or result["size"] not in description["sizes"][standard]):
        raise WorkspaceError("Unsupported standard/size combination; consult cad_standard_parts.", "invalid_parameters")
    if identity == "chain.Chain" and len({len(result[k]) for k in ("spkt_teeth", "spkt_locations", "positive_chain_wrap")}) != 1:
        raise WorkspaceError("Chain sprocket arrays must have equal lengths.", "invalid_parameters")
    if identity.startswith("thread.") and result.get("simple"):
        raise WorkspaceError("Standalone threads require detailed geometry; simple produces no physical solid.", "invalid_parameters")
    if "end_finishes" in result:
        result["end_finishes"] = list(result["end_finishes"])
    return result


def generate(folder, snapshot, request, intersection_stats=None):
    candidate = copy.deepcopy(snapshot)
    target = request.get("instance_id")
    part = next((p for p in candidate["components"] if p["instance_id"] == target), None) if target else None
    if target and part is None:
        raise WorkspaceError("The component no longer exists.", "stale_selection")
    retained = (part or {}).get("standard_part")
    if part and not retained:
        raise WorkspaceError("Only an existing standard part can be regenerated.", "invalid_target")
    identity = request.get("generator_id") or (retained or {}).get("generator_id")
    if retained:
        if identity != retained["generator_id"] or retained["dependency_revision"] != REVISION:
            raise WorkspaceError("Regeneration must use the retained generator and dependency revision.", "invalid_generator")
        if part["asset_hash"] != retained["generated_asset_hash"]:
            raise WorkspaceError("Undo downstream topology edits before regenerating this standard part.", "downstream_edits")
    supplied = request.get("parameters", {})
    if not isinstance(supplied, dict):
        raise WorkspaceError("parameters must be a typed parameter object.", "invalid_parameters")
    values = {**(retained or {}).get("parameters", {}), **supplied}
    values = checked_parameters(identity, values)
    cls = generator(identity)
    arguments = {**values}
    if "end_finishes" in arguments:
        arguments["end_finishes"] = tuple(arguments["end_finishes"])
    if "spkt_locations" in arguments:
        arguments["spkt_locations"] = [tuple(point) for point in arguments["spkt_locations"]]
        arguments["spkt_normal"] = tuple(arguments["spkt_normal"])
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        generated = cls(**arguments)
        shape = generated if isinstance(generated, cq.Shape) else generated.cq_object.toCompound()
    asset = geometry.store_shape(folder, shape, allow_compound=True)
    if part is None:
        part = {"instance_id": str(uuid4()), "parent_id": None, "matrix": list(geometry.IDENTITY),
                "color": [0.65, 0.72, 0.82], "parameters": {}}
        candidate["components"].append(part)
    placement = request.get("placement")
    if placement is not None:
        if not isinstance(placement, dict) or placement.keys() - {"translation", "rotation"}:
            raise WorkspaceError("Placement uses translation and rotation vectors.", "invalid_parameters")
        vectors = [placement.get(key, [0, 0, 0]) for key in ("translation", "rotation")]
        for vector in vectors:
            validate_value(vector, {"type": "array", "minItems": 3, "maxItems": 3, "items": {"type": "number", "minimum": -10000, "maximum": 10000}}, "placement")
        part["matrix"] = geometry.matrix(cq.Location(*(tuple(vector) for vector in vectors)).wrapped.Transformation())
    name = request.get("name", part.get("name", identity.split(".")[1]))
    if not isinstance(name, str) or not 0 < len(name.strip()) <= 200:
        raise WorkspaceError("Choose a component name of 1–200 characters.", "invalid_parameters")
    part.update(asset, name=name, definition_id=str(uuid4()), editable_definition_kind="standard_part",
                standard_part={"generator_id": identity, "dependency_revision": REVISION,
                               "parameters": values, "generated_asset_hash": asset["asset_hash"]})
    consumed = [target] if target else []
    candidate["_component_transaction"] = {"operation": "standard_part", "consumed": consumed,
        "outputs": [part["instance_id"]], "mapping": {target: [target]} if target else {}}
    candidate["warnings"] = list(dict.fromkeys([*candidate.get("warnings", []), *[str(w.message) for w in caught]]))
    geometry.check_new_intersections(
        folder, snapshot, candidate, {"type": "standard_part"},
        stats=intersection_stats,
    )
    candidate["_intersection_stats"] = intersection_stats or {}
    return candidate

"""Trusted component transactions. Scripts supply shapes, never ownership records."""

import copy
import math
from uuid import uuid4

import cadquery as cq

from backend.native import geometry
from backend.native.contracts import WorkspaceError


def targets(snapshot, identities):
    if not isinstance(identities, list) or not 1 <= len(identities) <= 100:
        raise WorkspaceError("Choose 1–100 source components.", "invalid_target")
    if any(not isinstance(identity, str) or not identity for identity in identities):
        raise WorkspaceError("Source components need valid IDs.", "invalid_target")
    if len(set(identities)) != len(identities):
        raise WorkspaceError("Source component IDs must be distinct.", "invalid_target")
    lookup = {p["instance_id"]: p for p in snapshot["components"]}
    if any(identity not in lookup for identity in identities):
        raise WorkspaceError("A source component is no longer present.", "stale_selection")
    parts = [lookup[identity] for identity in identities]
    if any(p.get("representation") == "mesh" for p in parts):
        raise WorkspaceError("Solid restructuring needs engineering bodies; use mesh separation for triangles.", "unsupported_representation")
    return parts


def common_parent(snapshot, sources):
    nodes = {n["id"]: n.get("parent_id") for n in snapshot.get("assembly_nodes", [])}
    def ancestry(part):
        chain, current = [], part.get("parent_id")
        while current is not None:
            if current in chain or current not in nodes:
                raise WorkspaceError("The assembly parent structure is invalid.", "invalid_project")
            chain.append(current)
            current = nodes[current]
        return chain + [None]
    chains = [ancestry(p) for p in sources]
    return next(p for p in chains[0] if all(p in chain for chain in chains)) if chains else None


def input_shapes(folder, snapshot, sources):
    return {p["instance_id"]: geometry.load_shape(folder, p) if len(sources) == 1
            else geometry.world_shape(folder, p) for p in sources}


def publish(folder, snapshot, sources, outputs, *, kind, parameters=None, source=None, colors=None, instances=None):
    from .engineering import rgb

    if not isinstance(outputs, dict) or not 1 <= len(outputs) <= 100:
        raise WorkspaceError("Return parts={name: solid, ...} with 1–100 outputs.", "invalid_output")
    if instances is not None and (not isinstance(instances, dict) or len(outputs) + len(instances) > 100):
        raise WorkspaceError("instances must be {name: [part_name, [tx, ty, tz], [rx, ry, rz]]} with at most 100 parts in total.", "invalid_output")
    if not isinstance(colors or {}, dict) or set(colors or {}) - set(outputs) - set(instances or {}):
        raise WorkspaceError("Output colours must refer to returned part names.", "invalid_output")
    candidate = copy.deepcopy(snapshot)
    consumed = [p["instance_id"] for p in sources]
    old_ids = {p["instance_id"] for p in snapshot["components"]}
    frame = sources[0]["matrix"] if len(sources) == 1 else geometry.IDENTITY
    parent = common_parent(snapshot, sources)
    built, output_names = [], {}
    for label, shape in outputs.items():
        if not isinstance(label, str) or not label.strip() or len(label) > 128:
            raise WorkspaceError("Output names must contain 1–128 characters.", "invalid_output")
        if isinstance(shape, cq.Workplane):
            values = shape.vals()
            if len(values) != 1:
                raise WorkspaceError("Each output must contain one solid. Return separate entries for separate solids.", "invalid_output")
            shape = values[0]
        if not isinstance(shape, cq.Shape):
            raise WorkspaceError("Each output must be CAD geometry.", "invalid_output")
        if len(sources) == 1 and len(outputs) == 1:
            identity = consumed[0]
        elif not sources and label not in old_ids:
            identity = label  # Preserve the legacy creation-script naming contract.
        else:
            identity = uuid4().hex
        if not sources and label in old_ids:
            raise WorkspaceError("Select a component before replacing it.", "insufficient_selection")
        part = copy.deepcopy(sources[0]) if len(sources) == 1 and len(outputs) == 1 else {}
        inherited = sources[0].get("color", [0.55, 0.72, 0.9]) if sources else [0.55, 0.72, 0.9]
        part.update(
            instance_id=identity, definition_id=uuid4().hex,
            name=sources[0]["name"] if sources and label == consumed[0] else label,
            parent_id=parent, matrix=list(frame),
            color=rgb((colors or {}).get(label, inherited)), parameters=parameters or {},
            **geometry.store_shape(folder, shape),
        )
        part.pop("editable_definition_kind", None)
        if source is not None:
            part["editable_definition_kind"] = "script"
        built.append(part)
        output_names[label] = identity
    instance_matrices = {}
    for label, spec in (instances or {}).items():
        # Identical repeated parts reuse the stored asset and definition; only the placement differs.
        if not isinstance(label, str) or not label.strip() or len(label) > 128 or label in outputs:
            raise WorkspaceError("Instance names must be new 1–128 character names distinct from parts.", "invalid_output")
        if (not isinstance(spec, (list, tuple)) or len(spec) not in (2, 3)
                or not isinstance(spec[0], str) or spec[0] not in outputs):
            raise WorkspaceError("Each instance needs [part_name, [tx, ty, tz], [rx, ry, rz]] naming a returned part.", "invalid_output")
        vectors = [spec[1], spec[2] if len(spec) == 3 else [0, 0, 0]]
        if any(not isinstance(v, (list, tuple)) or len(v) != 3 or
               any(type(x) not in (int, float) or not math.isfinite(x) or abs(x) > 10000 for x in v) for v in vectors):
            raise WorkspaceError("Instance translation and rotation need three finite numbers within ±10,000.", "invalid_output")
        if not sources and label in old_ids:
            raise WorkspaceError("Select a component before replacing it.", "insufficient_selection")
        identity = label if not sources else uuid4().hex
        base = next(p for p in built if p["instance_id"] == output_names[spec[0]])
        placement = cq.Location(tuple(float(x) for x in vectors[0]), tuple(float(x) for x in vectors[1])).wrapped.Transformation()
        part = copy.deepcopy(base)
        part.update(instance_id=identity, name=label,
                    matrix=geometry.matrix(geometry.transform(frame).Multiplied(placement)),
                    color=rgb((colors or {}).get(label, base["color"])))
        built.append(part)
        output_names[label] = identity
        instance_matrices[identity] = list(part["matrix"])
    if len({p["instance_id"] for p in built}) != len(built):
        raise WorkspaceError("Output and instance names must be distinct.", "invalid_output")
    candidate["components"] = [p for p in candidate["components"] if p["instance_id"] not in consumed] + built
    mapping = {identity: [p["instance_id"] for p in built] for identity in consumed}
    transaction = {"operation": kind, "consumed": consumed,
                   "outputs": [p["instance_id"] for p in built], "mapping": mapping}
    candidate["_component_transaction"] = transaction
    candidate.setdefault("component_history", []).append(copy.deepcopy(transaction))
    candidate.update(origin="script" if source is not None else "direct", direct_edits=True)
    if source is not None:
        from .definitions import stage
        label = "model-" + built[0]["definition_id"] + ".cad.py"
        stage(candidate, label, source, [p["instance_id"] for p in built], parameters)
        candidate.setdefault("scripts", []).append({
            "source": source, "parameters": parameters or {},
            "instance_id": consumed[0] if len(consumed) == 1 else None,
            "source_instance_ids": consumed, "part_ids": [p["instance_id"] for p in built],
            "output_names": output_names, "colors": colors or {},
            "input_components": copy.deepcopy(snapshot["components"]),
            "output_hashes": {p["instance_id"]: p["asset_hash"] for p in built},
            "instance_matrices": instance_matrices,
        })
    return candidate


def restructure(folder, snapshot, request):
    operation = request.get("operation")
    sources = targets(snapshot, request.get("source_instance_ids")) if request.get("source_instance_ids") else []
    if not sources and not (operation == "create" and request.get("recipe")):
        raise WorkspaceError("Choose source components for restructuring.", "insufficient_selection")
    shapes = input_shapes(folder, snapshot, sources)
    if request.get("recipe") and operation in ("create", "replace"):
        built = geometry.from_recipe(request["recipe"], folder)
        outputs = {p["instance_id"]: geometry.world_shape(folder, p) for p in built["components"]}
        colors = {p["instance_id"]: p["color"] for p in built["components"]}
        candidate = publish(folder, snapshot, sources, outputs, kind=operation, colors=colors)
        mapping = dict(zip(outputs, candidate["_component_transaction"]["outputs"]))
        fresh = {p["instance_id"]: p for p in candidate["components"]}
        for original in built["components"]:
            fresh[mapping[original["instance_id"]]].update(name=original["name"], parameters=original.get("parameters", {}), editable_definition_kind="recipe")
        candidate.setdefault("recipe_runs", []).append({"recipe": copy.deepcopy(request["recipe"]),
            "source_instance_ids": [p["instance_id"] for p in sources],
            "input_components": copy.deepcopy(snapshot["components"]), "output_names": mapping,
            "output_hashes": {identity: fresh[identity]["asset_hash"] for identity in mapping.values()}})
        from .definitions import stage
        import json
        stage(candidate, "recipe-" + uuid4().hex + ".cad.json", json.dumps(request["recipe"], indent=2), list(mapping.values()))
        return candidate
    if operation == "replace":
        from .scripts import run_script
        outputs, colors, instances = run_script(request.get("source", ""), request.get("parameters", {}), shapes)
        return publish(folder, snapshot, sources, outputs, kind="replace", source=request["source"],
                       parameters=request.get("parameters", {}), colors=colors, instances=instances)
    if operation == "merge":
        if len(sources) < 2:
            raise WorkspaceError("Select at least two bodies to merge.", "insufficient_selection")
        shape = shapes[sources[0]["instance_id"]]
        for part in sources[1:]:
            shape = shape.fuse(shapes[part["instance_id"]]).clean()
        if len(shape.Solids()) != 1:
            raise WorkspaceError("These bodies do not form one connected solid. Add connecting material or keep separate components.", "disconnected_union")
        return publish(folder, snapshot, sources, {request.get("name") or "Merged component": shape},
                       kind="merge", colors={request.get("name") or "Merged component": request["color"]} if "color" in request else None)
    if operation != "split":
        raise WorkspaceError("Supported restructuring operations: split, merge, replace.", "unsupported_operation")
    if len(sources) != 1:
        raise WorkspaceError("Split one source body at a time.", "invalid_target")
    body = next(iter(shapes.values()))
    if request.get("tool_instance_id"):
        tool = targets(snapshot, [request["tool_instance_id"]])[0]
        if tool["instance_id"] == sources[0]["instance_id"]:
            raise WorkspaceError("Choose a different cutting component.", "invalid_target")
        cutter = geometry.world_shape(folder, tool).moved(cq.Location(geometry.transform(sources[0]["matrix"]).Inverted()))
        pieces = body.split(cutter).Solids()
    else:
        plane = request.get("plane")
        if not isinstance(plane, dict) or "origin" not in plane or "normal" not in plane:
            raise WorkspaceError("Specify a split plane origin and normal in source-local millimetres.", "missing_dimensions")
        from .engineering import vector
        origin, normal = vector(plane["origin"]), vector(plane["normal"])
        if cq.Vector(*normal).Length < 1e-9:
            raise WorkspaceError("The split plane needs a nonzero normal.", "invalid_target")
        pieces = [s for value in cq.Workplane(cq.Plane(origin=origin, normal=normal)).add(body).split(keepTop=True, keepBottom=True).vals() for s in value.Solids()]
    if not 2 <= len(pieces) <= 100:
        raise WorkspaceError("The cutting plane/tool did not divide the body into 2–100 solids.", "no_split")
    volume = body.Volume()
    tolerance = max(1e-7, volume * 1e-5)
    combined = pieces[0]
    for piece in pieces[1:]:
        combined = combined.fuse(piece)
    if (abs(sum(p.Volume() for p in pieces) - volume) > tolerance or
            body.cut(combined).Volume() > tolerance or combined.cut(body).Volume() > tolerance):
        raise WorkspaceError("The split failed geometry conservation checks.", "verification_failed")
    names = request.get("names", [])
    if names and (len(names) != len(pieces) or len(set(names)) != len(names)):
        raise WorkspaceError("Provide one distinct name per split output.", "invalid_output")
    pieces.sort(key=lambda p: (*p.Center().toTuple(), p.Volume()))
    return publish(folder, snapshot, sources,
                   {names[i] if names else f"{sources[0]['name']} {i + 1}": p for i, p in enumerate(pieces)}, kind="split")


def change_recipe_parameters(folder, snapshot, instance_id, values):
    run = next(r for r in reversed(snapshot["recipe_runs"]) if instance_id in r["output_names"].values())
    parts = {p["instance_id"]: p for p in snapshot["components"]}
    for identity, digest in run["output_hashes"].items():
        if identity not in parts or parts[identity]["asset_hash"] != digest:
            raise WorkspaceError("Undo downstream edits before regenerating this recipe.", "definition_conflict")
    recipe = copy.deepcopy(run["recipe"])
    name = next(k for k, v in run["output_names"].items() if v == instance_id)
    target = next(p for p in recipe["components"] if p["id"] == name)
    if not values.keys() <= target.get("parameters", {}).keys():
        raise WorkspaceError("Only existing named recipe parameters can be changed.", "missing_parameter")
    target["parameters"].update(values)
    base = {"components": copy.deepcopy(run["input_components"]), "assembly_nodes": snapshot.get("assembly_nodes", [])}
    rebuilt = restructure(folder, base, {"operation": "replace" if run["source_instance_ids"] else "create",
                          "source_instance_ids": run["source_instance_ids"], "recipe": recipe})
    new_run = rebuilt["recipe_runs"][-1]
    fresh = {p["instance_id"]: p for p in rebuilt["components"]}
    candidate = copy.deepcopy(snapshot)
    replacement = {}
    for label, old_id in run["output_names"].items():
        updated = copy.deepcopy(fresh[new_run["output_names"][label]])
        for field in ("matrix", "parent_id", "name", "color", "color_override"):
            if field in parts[old_id]:
                updated[field] = copy.deepcopy(parts[old_id][field])
        updated["instance_id"] = old_id
        replacement[old_id] = updated
    candidate["components"] = [replacement.get(p["instance_id"], p) for p in candidate["components"]]
    candidate["recipe_runs"].append({**copy.deepcopy(run), "recipe": recipe,
        "output_hashes": {identity: p["asset_hash"] for identity, p in replacement.items()}})
    from .definitions import stage
    import json
    stage(candidate, "parameters-" + uuid4().hex + ".cad.json", json.dumps(recipe, indent=2), list(replacement))
    return candidate

import copy
import hashlib
import math
from pathlib import Path
from uuid import uuid4

import cadquery as cq
from OCP.gp import gp_Trsf
from OCP.IFSelect import IFSelect_RetDone
from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB
from OCP.STEPCAFControl import STEPCAFControl_Reader, STEPCAFControl_Writer
from OCP.STEPControl import STEPControl_AsIs
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDF import TDF_Label, TDF_LabelSequence, TDF_ChildIterator
from OCP.TDocStd import TDocStd_Document
from OCP.TopAbs import TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX
from OCP.TopExp import TopExp
from OCP.TopLoc import TopLoc_Location
from OCP.TopTools import TopTools_IndexedMapOfShape
from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ColorType

from backend.native.design_schema import Design
from backend.native.modelling import Builder, measure, verify_assembly
from .contracts import Command, WorkspaceError
from .documents import asset_path
from pydantic import TypeAdapter

COMMAND = TypeAdapter(Command)
IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0]


def matrix(transform):
    return [transform.Value(row, col) for row in range(1, 4) for col in range(1, 5)]


def transform(values):
    if len(values) != 12 or not all(math.isfinite(v) for v in values):
        raise WorkspaceError("An instance placement must be a finite 3x4 matrix.", "invalid_project")
    trsf = gp_Trsf()
    trsf.SetValues(*values)
    return trsf


def indexed(shape, kind):
    shapes = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape.wrapped, kind, shapes)
    return [cq.Shape.cast(shapes.FindKey(i)) for i in range(1, shapes.Extent() + 1)]


def load_shape(folder, part):
    if part.get("representation") == "mesh":
        raise WorkspaceError("This component is a mesh. Use mesh operations; original CAD faces and features are unavailable.")
    path = asset_path(folder, part["brep"])
    if hashlib.sha256(path.read_bytes()).hexdigest() != part["asset_hash"]:
        raise WorkspaceError("The body asset has changed.", "invalid_project")
    return cq.Shape.importBrep(str(path))


def world_shape(folder, part):
    return load_shape(folder, part).moved(cq.Location(transform(part["matrix"])))


def has_auxiliary_geometry(shape, solids):
    for kind in (TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX):
        members = TopTools_IndexedMapOfShape()
        for solid in solids:
            TopExp.MapShapes_s(solid.wrapped, kind, members)
        if any(not members.Contains(entity.wrapped) for entity in indexed(shape, kind)):
            return True
    return False


def store_shape(folder, shape, allow_compound=False):
    report = measure(shape)
    solids = shape.Solids()
    count_ok = 1 <= len(solids) <= 1000 if allow_compound else len(solids) == 1
    if (not report["brep_valid"] or not count_ok or report["volume_mm3"] <= 1e-7
            or any(not s.isValid() or s.Volume() <= 1e-7 for s in solids)):
        raise WorkspaceError("An operation must leave one valid solid with positive volume.")
    # Reject loose faces/edges alongside solids, even for an explicit compound part.
    if has_auxiliary_geometry(shape, solids):
        raise WorkspaceError("Compound parts may contain valid solids only.")
    folder = Path(folder)
    assets = folder / "assets"
    assets.mkdir(exist_ok=True)
    temporary = assets / f"{uuid4().hex}.brep"
    shape.exportBrep(str(temporary))
    digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
    target = assets / f"{digest}.brep"
    if target.exists():
        temporary.unlink()
    else:
        temporary.replace(target)
    # The viewer enumerates this exact persisted shape, not the transient builder shape.
    persisted = cq.Shape.importBrep(str(target))
    return {"brep": f"assets/{digest}.brep", "asset_hash": digest, "metrics": measure(persisted),
            "shape_kind": "compound" if len(solids) > 1 else "solid",
            "topology": {"faces": len(indexed(persisted, TopAbs_FACE)),
                         "edges": len(indexed(persisted, TopAbs_EDGE)),
                         "vertices": len(indexed(persisted, TopAbs_VERTEX))}}


def label_name(label, fallback):
    attr = TDataStd_Name()
    return attr.Get().ToExtString() if label.FindAttribute(TDataStd_Name.GetID_s(), attr) else fallback


def import_step(path, folder):
    document = TDocStd_Document(TCollection_ExtendedString("BinXCAF"))
    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    reader.SetColorMode(True)
    if reader.ReadFile(str(path)) != IFSelect_RetDone or not reader.Transfer(document):
        raise WorkspaceError("OpenCascade could not read this STEP file.", "import_failed")
    tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    colors = XCAFDoc_DocumentTool.ColorTool_s(document.Main())
    roots = TDF_LabelSequence()
    tool.GetFreeShapes(roots)
    components, nodes, definitions = [], [], {}
    skipped_instances = 0
    trimmed_definitions = set()

    def visit(label, parent, placement, inherited_color, ancestry):
        nonlocal skipped_instances
        if len(ancestry) > 64:
            raise WorkspaceError("The assembly nesting exceeds 64 levels.")
        referred = TDF_Label()
        definition = label
        if tool.IsReference_s(label):
            tool.GetReferredShape_s(label, referred)
            definition = referred
        key = definition.Tag()
        # Tags are only unique under a parent; the full entry identifies a definition.
        from OCP.TDF import TDF_Tool
        from OCP.TCollection import TCollection_AsciiString
        entry = TCollection_AsciiString()
        TDF_Tool.Entry_s(definition, entry)
        key = entry.ToCString()
        if key in ancestry:
            raise WorkspaceError("The STEP assembly contains a circular reference.")
        location = placement.Multiplied(tool.GetLocation_s(label).Transformation())
        color = Quantity_Color()
        rgb = inherited_color
        has_color = False
        for candidate in (label, definition):
            if colors.GetColor_s(candidate, XCAFDoc_ColorType.XCAFDoc_ColorGen, color) or colors.GetColor_s(
                    candidate, XCAFDoc_ColorType.XCAFDoc_ColorSurf, color):
                rgb = [color.Red(), color.Green(), color.Blue()]
                has_color = True
                break
        name = label_name(label, label_name(definition, f"Component {len(nodes) + len(components) + 1}"))
        node_id = str(uuid4())
        if tool.IsAssembly_s(definition):
            nodes.append({"id": node_id, "parent_id": parent, "name": name, "matrix": matrix(location)})
            children = TDF_LabelSequence()
            tool.GetComponents_s(definition, children)
            for i in range(1, children.Length() + 1):
                visit(children.Value(i), node_id, location, rgb, ancestry + [key])
        else:
            if not has_color:
                # STEP writes a compound's uniform colour onto its solid sublabels.
                child = TDF_ChildIterator(definition, True)
                child_colors = []
                while child.More():
                    if colors.GetColor_s(child.Value(), XCAFDoc_ColorType.XCAFDoc_ColorGen, color) or colors.GetColor_s(child.Value(), XCAFDoc_ColorType.XCAFDoc_ColorSurf, color):
                        child_colors.append([color.Red(), color.Green(), color.Blue()])
                    child.Next()
                if child_colors and all(all(abs(a - b) < 1e-6 for a, b in zip(c, child_colors[0])) for c in child_colors):
                    rgb = child_colors[0]
            if key not in definitions:
                raw_shape = tool.GetShape_s(definition)
                shape = None if raw_shape.IsNull() else cq.Shape.cast(raw_shape).located(cq.Location())
                solids = shape.Solids() if shape is not None else []
                definitions[key] = []
                if solids:
                    if has_auxiliary_geometry(shape, solids):
                        shape = solids[0] if len(solids) == 1 else cq.Compound.makeCompound(solids)
                        trimmed_definitions.add(key)
                    definitions[key] = [(store_shape(folder, shape, allow_compound=len(solids) > 1), str(uuid4()))]
            if not definitions[key]:
                skipped_instances += 1
                return
            for position, (asset, definition_id) in enumerate(definitions[key]):
                components.append({"instance_id": str(uuid4()), "definition_id": definition_id,
                                   "parent_id": parent, "name": name if len(definitions[key]) == 1 else f"{name} {position + 1}",
                                   "color": rgb, "matrix": matrix(location), **asset})
        if len(components) > 1000:
            raise WorkspaceError("This workspace limits imports to 1,000 solid instances.")

    for i in range(1, roots.Length() + 1):
        visit(roots.Value(i), None, gp_Trsf(), [0.65, 0.72, 0.82], [])
    if not components:
        raise WorkspaceError("The STEP file contains no solid bodies. Surface-only STEP editing is not supported.", "import_failed")
    warnings = []
    if skipped_instances:
        warnings.append(f"Skipped {skipped_instances} auxiliary STEP representation instance(s) with no solid bodies. "
                        "Surfaces, curves and reference geometry are not imported for editing.")
    if trimmed_definitions:
        warnings.append(f"Ignored auxiliary surface, curve or reference geometry in {len(trimmed_definitions)} "
                        "solid-bearing STEP definition(s). Their solid bodies were retained.")
    if len(components) > 100:
        warnings.append("This assembly exceeds the 100-component tested target.")
    return {"components": components, "assembly_nodes": nodes, "origin": "step",
            "warnings": warnings}


def from_recipe(recipe, folder):
    design = Design.model_validate(recipe)
    builder = Builder(design)
    parts = builder.build()
    verification = verify_assembly(builder, parts)
    components = []
    for part in parts:
        components.append({"instance_id": part.component.id, "definition_id": part.component.id,
                           "parent_id": None, "name": part.component.name,
                           "color": [int(part.component.color[i:i + 2], 16) / 255 for i in (1, 3, 5)],
                           "matrix": IDENTITY, "parameters": part.parameters,
                           **store_shape(folder, part.shape)})
    return {"components": components, "assembly_nodes": [], "origin": "recipe",
            "recipe": design.model_dump(mode="json"), "verification": verification, "direct_edits": False}


def inspect(folder, snapshot, instance_id=None, limit=128, offset=0):
    limit, offset = max(1, min(int(limit), 256)), max(0, int(offset))
    descriptions = []
    for part in snapshot["components"]:
        if instance_id and part["instance_id"] != instance_id:
            continue
        if part.get("representation") == "mesh":
            from backend.v2.meshes import inspect as mesh_inspect
            descriptions.append(mesh_inspect(folder, part, offset, limit))
            continue
        shape = load_shape(folder, part)
        faces, edges = indexed(shape, TopAbs_FACE), indexed(shape, TopAbs_EDGE)
        description = {key: part[key] for key in ("instance_id", "name", "metrics", "matrix", "topology")}
        description.update(parameters=part.get("parameters", {}), definition_id=part.get("definition_id"), parent_id=part.get("parent_id"), representation="solid")
        description.update(shape_kind=part.get("shape_kind", "solid"), standard_part=part.get("standard_part"), asset_hash=part["asset_hash"])
        description["faces"] = [{"index": i, "type": face.geomType(), "area_mm2": face.Area(),
                                 "centre": face.Center().toTuple(),
                                 "normal": face.normalAt().toTuple() if face.geomType() == "PLANE" else None,
                                 "x_direction": cq.Plane(origin=face.Center(), normal=face.normalAt()).xDir.toTuple() if face.geomType() == "PLANE" else None}
                                for i, face in enumerate(faces[offset:offset + limit], offset + 1)]
        description["edges"] = [{"index": i, "type": edge.geomType(), "length_mm": edge.Length(),
                                 "centre": edge.Center().toTuple(),
                                 "start": edge.startPoint().toTuple(), "end": edge.endPoint().toTuple()}
                                for i, edge in enumerate(edges[offset:offset + limit], offset + 1)]
        vertices = indexed(shape, TopAbs_VERTEX)
        description["vertices"] = [{"index": i, "point": vertex.toTuple()} for i, vertex in enumerate(vertices[offset:offset + limit], offset + 1)]
        description["truncated"] = len(faces) > offset + limit or len(edges) > offset + limit
        description["next_offset"] = offset + limit if description["truncated"] else None
        descriptions.append(description)
    if instance_id and not descriptions:
        raise WorkspaceError("The selected component no longer exists.", "stale_selection")
    return {"revision_id": snapshot.get("revision_id"), "components": descriptions,
            "component_count": len(descriptions), "solid_count": sum(d.get("metrics", {}).get("solid_count", 0) for d in descriptions),
            "coordinates": "Operation coordinates and topology measurements are local to each body; matrix maps to world mm."}


def hole_tool(command, body):
    bounds = body.BoundingBox()
    axis = "XYZ".index(command.axis)
    lowers = [bounds.xmin, bounds.ymin, bounds.zmin]
    uppers = [bounds.xmax, bounds.ymax, bounds.zmax]
    direction = [0, 0, 0]
    direction[axis] = -1
    remaining_axes = [i for i in range(3) if i != axis]
    depth = command.depth
    tools = []
    for centre in command.centres:
        origin = [0., 0., 0.]
        origin[axis] = uppers[axis] + 0.01
        for i, coordinate in zip(remaining_axes, centre):
            origin[i] = coordinate
        length = depth + 0.01 if depth else uppers[axis] - lowers[axis] + 0.02
        tool = cq.Solid.makeCylinder(command.diameter / 2, length, cq.Vector(*origin), cq.Vector(*direction))
        if body.intersect(tool).Volume() <= 1e-7:
            raise WorkspaceError("A hole does not intersect the selected body's material.")
        if any(tool.intersect(other).Volume() > 1e-7 for other in tools):
            raise WorkspaceError("Hole centres overlap; use distinct centres.")
        tools.append(tool)
    return tools


def extrusion_tool(command):
    if abs(command.distance) < 1e-7:
        raise WorkspaceError("An extrusion needs a nonzero distance.")
    plane = cq.Plane(command.origin, command.x_direction, command.normal)
    return cq.Workplane(plane).polyline(command.profile).close().extrude(command.distance).val()


def boolean_apply(body, tool, operation):
    before = body.Volume()
    solids = body.Solids()
    if len(solids) > 1:
        if operation == "add":
            affected = [s for s in solids if s.distance(tool) < 1e-7]
            if not affected:
                raise WorkspaceError("An added feature must connect to the component's material.")
            merged = affected[0].fuse(tool, *affected[1:]).clean()
            members = [s for s in solids if not any(s.isSame(a) for a in affected)] + merged.Solids()
        else:
            members = []
            for solid in solids:
                if solid.intersect(tool).Volume() <= 1e-7:
                    if operation == "cut":
                        members.append(solid)
                    continue
                members.extend((solid.cut(tool) if operation == "cut" else solid.intersect(tool)).clean().Solids())
        candidate = cq.Compound.makeCompound(members)
    else:
        candidate = {"add": body.fuse, "cut": body.cut, "intersect": body.intersect}[operation](tool).clean()
    if abs(candidate.Volume() - before) < 1e-7:
        raise WorkspaceError("The operation did not change the solid.")
    return candidate


def owning_solid(body, entity, kind):
    owners = [i for i, solid in enumerate(body.Solids())
              if any(entity.isSame(member) for member in indexed(solid, kind))]
    if len(owners) != 1:
        raise WorkspaceError("The topology reference has no unambiguous owning solid.", "stale_selection")
    return owners[0]


def replace_member(body, index, replacement):
    members = body.Solids()
    members[index:index + 1] = replacement.Solids()
    return cq.Compound.makeCompound(members)


def apply_command(folder, snapshot, command_data):
    command = COMMAND.validate_python(command_data)
    if command.type.startswith("mesh_"):
        from backend.v2.meshes import apply as mesh_apply
        return mesh_apply(folder, snapshot, command.model_dump(mode="json"))
    candidate = copy.deepcopy(snapshot)
    part = next((p for p in candidate["components"] if p["instance_id"] == command.instance_id), None)
    if part is None:
        raise WorkspaceError("The command targets a missing component.", "stale_selection")
    if command.type == "parameters":
        if part.get("standard_part"):
            from backend.v2.standard_parts import generate
            previous = part["standard_part"]["parameters"]
            values = {key: int(value) if type(previous.get(key)) is int and value.is_integer() else value
                      for key, value in command.values.items()}
            return generate(folder, candidate, {"instance_id": command.instance_id, "parameters": values})
        if part.get("editable_definition_kind") == "recipe" and any(command.instance_id in r["output_names"].values() for r in candidate.get("recipe_runs", [])):
            from backend.v2.component_edits import change_recipe_parameters
            return change_recipe_parameters(folder, candidate, command.instance_id, command.values)
        if any(command.instance_id in s.get("part_ids", []) for s in candidate.get("scripts", [])):
            from backend.v2.scripts import change_parameters
            return change_parameters(folder, candidate, command.instance_id, command.values)
        if candidate.get("origin") != "recipe" or candidate.get("direct_edits"):
            raise WorkspaceError("Undo downstream direct edits before changing recipe parameters.")
        recipe = copy.deepcopy(candidate["recipe"])
        target = next(p for p in recipe["components"] if p["id"] == command.instance_id)
        if not command.values.keys() <= target["parameters"].keys():
            raise WorkspaceError("Only existing named parameters can be edited.")
        target["parameters"].update(command.values)
        rebuilt = from_recipe(recipe, folder)
        candidate.update(rebuilt)
        return candidate
    if command.type == "transform":
        delta = cq.Location(command.translation, command.rotation).wrapped.Transformation()
        part["matrix"] = matrix(delta.Multiplied(transform(part["matrix"])))
        candidate["direct_edits"] = True
        return candidate
    body = load_shape(folder, part)
    if command.type == "hole":
        for tool in hole_tool(command, body):
            body = boolean_apply(body, tool, "cut")
    elif command.type in ("fillet", "chamfer"):
        edges = indexed(body, TopAbs_EDGE)
        if len(set(command.edge_indices)) != len(command.edge_indices) or any(
                i < 1 or i > len(edges) for i in command.edge_indices):
            raise WorkspaceError("An edge reference is invalid. Inspect the current body again.", "stale_selection")
        selected = [edges[i - 1] for i in command.edge_indices]
        if part.get("shape_kind") == "compound":
            groups = {}
            for edge in selected:
                groups.setdefault(owning_solid(body, edge, TopAbs_EDGE), []).append(edge)
            members = body.Solids()
            for index, selected_edges in groups.items():
                solid = members[index]
                members[index] = solid.fillet(command.size, selected_edges) if command.type == "fillet" else solid.chamfer(command.size, None, selected_edges)
            body = cq.Compound.makeCompound(members)
        else:
            body = body.fillet(command.size, selected) if command.type == "fillet" else body.chamfer(command.size, None, selected)
    elif command.type in ("offset_face", "face_holes"):
        faces = indexed(body, TopAbs_FACE)
        if command.face_index > len(faces):
            raise WorkspaceError("Inspect the current topology before using this face.", "stale_selection")
        face = faces[command.face_index - 1]
        compound = body if part.get("shape_kind") == "compound" else None
        owner = owning_solid(body, face, TopAbs_FACE) if compound is not None else None
        if compound is not None:
            body = compound.Solids()[owner]
        if face.geomType() != "PLANE":
            raise WorkspaceError("This operation requires a planar face.")
        normal = face.normalAt()
        if command.type == "offset_face":
            if abs(command.distance) < 1e-6:
                raise WorkspaceError("Choose a nonzero thickness change.")
            prism = cq.Solid.extrudeLinear(face.outerWire(), face.innerWires(), normal.multiply(command.distance))
            body = boolean_apply(body, prism, "add" if command.distance > 0 else "cut")
        else:
            plane = cq.Plane(origin=face.Center(), normal=normal)
            for x, y in command.centres:
                origin = plane.toWorldCoords((x, y))
                tool = cq.Solid.makeCylinder(command.diameter / 2, command.depth + 0.02,
                                             origin.add(normal.multiply(0.01)), normal.multiply(-1))
                body = boolean_apply(body, tool, "cut")
        if compound is not None:
            body = replace_member(compound, owner, body)
    elif command.type == "extrude":
        body = boolean_apply(body, extrusion_tool(command), command.operation)
    elif command.type == "pattern":
        tools = hole_tool(command.seed, body) if command.seed.type == "hole" else [extrusion_tool(command.seed)]
        operation = "cut" if command.seed.type == "hole" else command.seed.operation
        patterned = []
        for n in range(command.count):
            for seed in tools:
                if command.mode == "linear":
                    patterned.append(seed.translate(tuple(n * v for v in command.step)))
                else:
                    end = tuple(a + b for a, b in zip(command.axis_origin, command.axis_direction))
                    angle = command.angle * n / (command.count if command.angle == 360 else command.count - 1)
                    patterned.append(seed.rotate(command.axis_origin, end, angle))
        for tool in patterned:
            body = boolean_apply(body, tool, operation)
    elif command.type == "boolean":
        other = next((p for p in candidate["components"] if p["instance_id"] == command.tool_instance_id), None)
        if other is None or other["instance_id"] == part["instance_id"]:
            raise WorkspaceError("A boolean needs a different, existing tool component.")
        tool = world_shape(folder, other).moved(cq.Location(transform(part["matrix"]).Inverted()))
        body = boolean_apply(body, tool, command.operation)
    part.update(store_shape(folder, body, allow_compound=part.get("shape_kind") == "compound"))
    part["definition_id"] = str(uuid4())
    candidate["direct_edits"] = True
    return candidate


def export_step(folder, snapshot, path):
    doc = TDocStd_Document(TCollection_ExtendedString("BinXCAF"))
    tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    colors = XCAFDoc_DocumentTool.ColorTool_s(doc.Main())
    root = tool.NewShape()
    TDataStd_Name.Set_s(root, TCollection_ExtendedString(snapshot.get("name", "Assembly")))
    groups = {None: root}
    matrices = {None: gp_Trsf()}
    for node in snapshot.get("assembly_nodes", []):
        parent = groups[node["parent_id"]]
        label = tool.NewShape()
        local = matrices[node["parent_id"]].Inverted().Multiplied(transform(node["matrix"]))
        instance = tool.AddComponent(parent, label, TopLoc_Location(local))
        TDataStd_Name.Set_s(label, TCollection_ExtendedString(node["name"]))
        TDataStd_Name.Set_s(instance, TCollection_ExtendedString(node["name"]))
        groups[node["id"]] = label
        matrices[node["id"]] = transform(node["matrix"])
    definitions = {}
    for part in snapshot["components"]:
        key = (part["definition_id"], tuple(part["color"]))
        if key not in definitions:
            label = tool.AddShape(load_shape(folder, part).wrapped, False)
            definitions[key] = label
            TDataStd_Name.Set_s(label, TCollection_ExtendedString(part["name"]))
        label = definitions[key]
        local = matrices[part["parent_id"]].Inverted().Multiplied(transform(part["matrix"]))
        instance = tool.AddComponent(groups[part["parent_id"]], label, TopLoc_Location(local))
        TDataStd_Name.Set_s(instance, TCollection_ExtendedString(part["name"]))
        rgb = part["color"]
        colors.SetColor(instance, Quantity_Color(*rgb, Quantity_TOC_RGB), XCAFDoc_ColorType.XCAFDoc_ColorGen)
        if part.get("shape_kind") == "compound":
            colors.SetColor(label, Quantity_Color(*rgb, Quantity_TOC_RGB), XCAFDoc_ColorType.XCAFDoc_ColorGen)
    tool.UpdateAssemblies()
    writer = STEPCAFControl_Writer()
    writer.SetNameMode(True)
    writer.SetColorMode(True)
    if not writer.Transfer(doc, STEPControl_AsIs) or writer.Write(str(path)) != IFSelect_RetDone:
        raise WorkspaceError("STEP export failed.", "export_failed")
    return path


def verify_export(folder, snapshot, path):
    # Import into a disposable project directory; source and accepted assets stay immutable.
    import tempfile
    with tempfile.TemporaryDirectory(dir=folder) as temporary:
        imported = import_step(path, temporary)
        expected = snapshot["components"]
        remaining = list(imported["components"])
        for part in expected:
            expected_shape = world_shape(folder, part)
            found = None
            for i, other in enumerate(remaining):
                if part["name"] != other["name"]:
                    continue
                actual_shape = world_shape(temporary, other)
                if (part["name"] == other["name"] and
                    all(abs(a - b) < 0.01 for a, b in zip(measure(expected_shape)["dimensions_mm"],
                                                        measure(actual_shape)["dimensions_mm"])) and
                    abs(expected_shape.Volume() - actual_shape.Volume()) < max(0.01, expected_shape.Volume() * 1e-5) and
                    len(expected_shape.Solids()) == len(actual_shape.Solids()) and
                    expected_shape.Center().sub(actual_shape.Center()).Length < 0.01 and
                    all(abs(a - b) < 1 / 255 + 1e-5 for a, b in zip(part["color"], other["color"]))):
                    found = i
                    break
            if found is None:
                raise WorkspaceError(f"STEP round-trip verification failed for '{part['name']}'.", "verification_failed")
            remaining.pop(found)
        if remaining:
            raise WorkspaceError("STEP round-trip changed the number of solid instances.", "verification_failed")
        expected_groups = [n["name"] for n in snapshot.get("assembly_nodes", [])]
        actual_groups = [n["name"] for n in imported.get("assembly_nodes", [])]
        if expected_groups and not all(actual_groups.count(name) >= expected_groups.count(name) for name in expected_groups):
            raise WorkspaceError("STEP round-trip lost assembly groups.", "verification_failed")
    return {"passed": True, "component_count": len(expected),
            "solid_count": sum(len(load_shape(folder, p).Solids()) for p in expected), "names_colors_placements": True}


def check_new_intersections(folder, before, after, command):
    previous = {p["instance_id"]: p for p in before["components"]}
    changed = {p["instance_id"] for p in after["components"] if
               p["instance_id"] not in previous or
               p["asset_hash"] != previous[p["instance_id"]]["asset_hash"] or
               p["matrix"] != previous[p["instance_id"]]["matrix"]}
    cache = {}
    transaction = after.get("_component_transaction", {})
    def ancestors(part):
        if part["instance_id"] in previous:
            return {part["instance_id"]}
        return {identity for identity, outputs in transaction.get("mapping", {}).items()
                if part["instance_id"] in outputs and identity in previous}
    def old_shape(identities):
        result = None
        for identity in identities:
            old = shape(previous[identity])
            result = old if result is None else result.fuse(old)
        return result
    def shape(part):
        key = (part["instance_id"], part["asset_hash"], tuple(part["matrix"]))
        if key not in cache:
            cache[key] = world_shape(folder, part)
        return cache[key]
    for i, a in enumerate(after["components"]):
        for b in after["components"][i + 1:]:
            if a.get("representation") == "mesh" or b.get("representation") == "mesh":
                continue
            ids = {a["instance_id"], b["instance_id"]}
            if not ids.intersection(changed):
                continue
            if command["type"] == "boolean" and ids == {command["instance_id"], command["tool_instance_id"]}:
                continue
            first, second = shape(a), shape(b)
            box_a, box_b = first.BoundingBox(), second.BoundingBox()
            if any(min(getattr(box_a, axis + "max"), getattr(box_b, axis + "max")) -
                   max(getattr(box_a, axis + "min"), getattr(box_b, axis + "min")) <= 1e-6 for axis in "xyz"):
                continue
            overlap = first.intersect(second).Volume()
            if overlap <= 1e-5:
                continue
            old_a, old_b = ancestors(a), ancestors(b)
            old_overlap = old_shape(old_a).intersect(old_shape(old_b)).Volume() if old_a and old_b and not old_a.intersection(old_b) else 0
            if overlap > old_overlap + 1e-5:
                raise WorkspaceError(f"The edit introduces an unexpected intersection between '{a['name']}' and '{b['name']}'.")


def measure_entities(folder, snapshot, first, second):
    def entity(reference):
        part = next((p for p in snapshot["components"] if p["instance_id"] == reference["instance_id"]), None)
        if not part:
            raise WorkspaceError("Measurement component is missing.", "stale_selection")
        if reference.get("asset_hash") and reference["asset_hash"] != part["asset_hash"]:
            raise WorkspaceError("Measurement topology changed; inspect the current body.", "stale_selection")
        shape = load_shape(folder, part)
        kind = reference.get("kind", "body")
        if kind != "body":
            kinds = {"face": TopAbs_FACE, "edge": TopAbs_EDGE, "vertex": TopAbs_VERTEX}
            if kind not in kinds:
                raise WorkspaceError("Choose a body, face, edge or vertex.")
            entities = indexed(shape, kinds[kind])
            index = reference.get("index", 0)
            if not isinstance(index, int) or not 1 <= index <= len(entities):
                raise WorkspaceError("Inspect measurement topology again.", "stale_selection")
            shape = entities[index - 1]
        return shape.moved(cq.Location(transform(part["matrix"])))
    a, b = entity(first), entity(second)
    return {"minimum_distance_mm": a.distance(b), "centre_distance_mm": (a.Center() - b.Center()).Length,
            "coordinates": "assembly world", "units": "mm"}


def apply_face_batch(folder, snapshot, values):
    if not isinstance(values, list) or not 1 <= len(values) <= 32:
        raise WorkspaceError("Use a batch of 1–32 face commands.")
    commands = [COMMAND.validate_python(value) for value in values]
    candidate = copy.deepcopy(snapshot)
    originals, operations, used = {}, {}, set()
    for command in commands:
        if command.type not in ("offset_face", "face_holes"):
            raise WorkspaceError("Atomic face batches support planar offsets and holes only.")
        part = next((p for p in candidate["components"] if p["instance_id"] == command.instance_id), None)
        if not part or part.get("representation") == "mesh":
            raise WorkspaceError("A face batch requires existing solid components.")
        if command.instance_id not in originals:
            originals[command.instance_id] = load_shape(folder, part)
        faces = indexed(originals[command.instance_id], TopAbs_FACE)
        if command.face_index > len(faces):
            raise WorkspaceError("A batch face reference is stale.", "stale_selection")
        key = (command.instance_id, command.face_index)
        if key in used:
            raise WorkspaceError("Combine edits to the same face into one batch command.")
        used.add(key)
        face = faces[command.face_index-1]
        owner = owning_solid(originals[command.instance_id], face, TopAbs_FACE) if part.get("shape_kind") == "compound" else None
        if face.geomType() != "PLANE":
            raise WorkspaceError("This batch requires planar faces.")
        normal = face.normalAt()
        tools = operations.setdefault(command.instance_id, [])
        if command.type == "offset_face":
            if abs(command.distance) < 1e-6:
                raise WorkspaceError("Choose a nonzero face offset.")
            tools.append((owner, "add" if command.distance > 0 else "cut", cq.Solid.extrudeLinear(face.outerWire(), face.innerWires(), normal.multiply(command.distance))))
        else:
            plane = cq.Plane(origin=face.Center(), normal=normal)
            for x, y in command.centres:
                origin = plane.toWorldCoords((x, y))
                tools.append((owner, "cut", cq.Solid.makeCylinder(command.diameter/2, command.depth+0.02, origin.add(normal.multiply(0.01)), normal.multiply(-1))))
    for part in candidate["components"]:
        if part["instance_id"] not in originals:
            continue
        body = originals[part["instance_id"]]
        members = body.Solids()
        for owner, operation, tool in operations[part["instance_id"]]:
            if owner is None:
                body = boolean_apply(body, tool, operation)
            else:
                members[owner] = boolean_apply(members[owner], tool, operation)
                if len(members[owner].Solids()) != 1:
                    raise WorkspaceError("A planar face edit must retain its owning solid.")
        if part.get("shape_kind") == "compound":
            body = cq.Compound.makeCompound(members)
        part.update(store_shape(folder, body, allow_compound=part.get("shape_kind") == "compound"))
        part["definition_id"] = str(uuid4())
    candidate["direct_edits"] = True
    check_new_intersections(folder, snapshot, candidate, {"type": "batch"})
    return candidate

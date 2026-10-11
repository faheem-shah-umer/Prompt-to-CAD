import math
from dataclasses import dataclass

import cadquery as cq
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib

from .design_schema import Component, Design, Placement
from .parameters import DesignError, Parameters

TOLERANCE = 1e-5


def measure(shape):
    box = Bnd_Box()
    # Measure the BREP directly; cached tessellation can change a loft's approximate bounds.
    BRepBndLib.AddOptimal_s(shape.wrapped, box, False, False)
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    if any(face.geomType() in ("BSPLINE", "BEZIER") for face in shape.Faces()):
        # OCCT's spline bounding algorithm can undershoot extrema after a loft.
        # Distances to six covering planes find the geometric coordinate extrema.
        extent = max(abs(value) for value in (xmin, ymin, zmin, xmax, ymax, zmax)) + max(xmax - xmin, ymax - ymin, zmax - zmin) + 10
        limits = []
        for axis in range(3):
            pair = []
            for sign in (-1, 1):
                origin, normal = [0, 0, 0], [0, 0, 0]
                origin[axis], normal[axis] = sign * extent, 1
                wire = cq.Workplane(cq.Plane(origin=tuple(origin), normal=tuple(normal))).rect(2 * extent + 10, 2 * extent + 10).val()
                distance = shape.distance(cq.Face.makeFromWires(wire))
                pair.append(sign * (extent - distance))
            limits.append(pair)
        (xmin, xmax), (ymin, ymax), (zmin, zmax) = limits
    return {"brep_valid": shape.isValid(), "solid_count": len(shape.Solids()),
            "volume_mm3": shape.Volume(tol=1e-8), "dimensions_mm": [xmax - xmin, ymax - ymin, zmax - zmin],
            "bounds_mm": [[xmin, ymin, zmin], [xmax, ymax, zmax]]}


def pose(shape, placement: Placement, parameters: Parameters, component: str):
    angles = parameters.vector(placement.rotation, component)
    translation = parameters.vector(placement.translation, component)
    if any(abs(value) > 10000 for value in translation):
        raise DesignError("Component positions must be within +/-10,000 mm.")
    for axis, angle in zip([(1, 0, 0), (0, 1, 0), (0, 0, 1)], angles):
        if angle:
            shape = shape.rotate((0, 0, 0), axis, angle)
    return shape.translate(translation)


def posed_vector(values, placement, parameters, component, direction=False):
    result = cq.Vector(*parameters.vector(values, component))
    for axis, angle in zip([(1, 0, 0), (0, 1, 0), (0, 0, 1)], parameters.vector(placement.rotation, component)):
        if angle:
            # Use the same rotations as the solid without inventing another Euler convention.
            point = cq.Vertex.makeVertex(*result.toTuple()).rotate((0, 0, 0), axis, angle)
            result = point.Center()
    if not direction:
        result += cq.Vector(*parameters.vector(placement.translation, component))
    return result


@dataclass
class BuiltComponent:
    component: Component
    local_shape: cq.Shape
    shape: cq.Shape
    parameters: dict
    validation: dict
    features: list[dict]


class Builder:
    def __init__(self, design: Design):
        self.design = design
        if sum(len(c.features) for c in design.components) > 256:
            raise DesignError("This CAD worker accepts up to 256 features per project.")
        self.parameters = Parameters(design)
        self.parts = {part.id: part for part in design.components}
        self.built: dict[str, BuiltComponent] = {}
        self.active: set[str] = set()
        self.component_dependencies: dict[str, set[str]] = {part.id: set() for part in design.components}

    def number(self, value, component):
        return self.parameters.value(value, component)

    def size(self, value, component, allow_zero=False):
        result = self.number(value, component)
        if not (0 <= result <= 2000 if allow_zero else 0 < result <= 2000):
            raise DesignError("Feature dimensions must be positive and no larger than 2,000 mm.")
        return result

    def build(self):
        for part in self.design.components:
            self.component(part.id)
        return [self.built[part.id] for part in self.design.components]

    def component(self, component_id):
        if component_id in self.built:
            return self.built[component_id]
        if component_id not in self.parts:
            raise DesignError(f"Unknown component '{component_id}'.")
        if component_id in self.active:
            raise DesignError(f"Circular geometry dependency involving '{component_id}'.")
        self.active.add(component_id)
        part = self.parts[component_id]
        body = None
        sketches, tools, feature_report = {}, {}, []
        for feature in part.features:
            try:
                if feature.type == "sketch":
                    sketches[feature.id] = self.sketch(feature, part.id)
                    feature_report.append({"id": feature.id, "type": feature.type, "passed": True})
                    continue
                if feature.type in ("fillet", "chamfer"):
                    if body is None:
                        raise DesignError("An edge treatment needs an existing solid.")
                    amount = self.size(feature.size, part.id)
                    workplane = cq.Workplane(obj=body).edges(feature.edges)
                    if not workplane.vals():
                        raise DesignError("The edge selector did not match any edges.")
                    body = getattr(workplane, feature.type)(amount).val()
                else:
                    if feature.type == "hole":
                        tool = self.holes(feature, part.id, body)
                    else:
                        tool = self.tool(feature, part.id, sketches, tools)
                        tool = pose(tool, feature.placement, self.parameters, part.id)
                    if not tool.isValid() or not tool.Solids():
                        raise DesignError("The feature produced invalid or empty geometry.")
                    tools[feature.id] = tool
                    operation = "cut" if feature.type == "hole" or feature.type == "thread" and feature.internal else feature.operation
                    previous_volume = body.Volume() if body else None
                    if body is None:
                        if operation not in ("new", "add"):
                            raise DesignError("The first solid feature must create material.")
                        body = tool
                    elif operation == "new":
                        raise DesignError("Use a separate component for a separate body.")
                    elif operation == "add":
                        body = body.fuse(tool).clean()
                    elif operation == "cut":
                        body = body.cut(tool).clean()
                    else:
                        body = body.intersect(tool).clean()
                    if previous_volume is not None and operation == "cut" and body.Volume() >= previous_volume - TOLERANCE:
                        raise DesignError("The cut did not remove material; check its position.")
                checked = measure(body)
                passed = checked["brep_valid"] and checked["solid_count"] == 1 and checked["volume_mm3"] > TOLERANCE
                if not passed:
                    raise DesignError("The feature must leave one valid, connected solid per component.")
                feature_report.append({"id": feature.id, "type": feature.type, "passed": True,
                                       "volume_mm3": checked["volume_mm3"]})
            except Exception as error:
                message = str(error) if isinstance(error, DesignError) else "CadQuery could not construct this feature; check its dimensions, references and edge selector."
                if feature.type in ("fillet", "chamfer") and not isinstance(error, DesignError) and body is not None:
                    dimensions = measure(body)["dimensions_mm"]
                    message += f" Edge size={amount:g} mm, selector={feature.edges!r}, current local body size={dimensions} mm. "
                    message += "Try a feasible edge selector. For both circular rims, the fillet radius must be strictly smaller than half the rim separation."
                raise DesignError(f"{part.name} / {feature.id} ({feature.type}): {message}") from error
        if body is None:
            raise DesignError(f"{part.name} only has sketches; add a solid operation.")
        local_report = measure(body)
        if any(dimension > 10000 for dimension in local_report["dimensions_mm"]):
            raise DesignError(f"{part.name}: the part exceeds this worker's 10,000 mm overall size limit.")
        checks = {"brep_valid": local_report["brep_valid"], "one_solid": local_report["solid_count"] == 1,
                  "positive_volume": local_report["volume_mm3"] > TOLERANCE,
                  "feature_history_valid": all(feature["passed"] for feature in feature_report)}
        if part.expected_size is not None:
            expected = self.parameters.vector(part.expected_size, part.id)
            checks["expected_dimensions_match"] = all(
                math.isclose(actual, target, abs_tol=0.01, rel_tol=1e-5)
                for actual, target in zip(local_report["dimensions_mm"], expected))
        if not all(checks.values()):
            requested = self.parameters.vector(part.expected_size, part.id) if part.expected_size else None
            raise DesignError(f"{part.name}: geometry or requested dimensions failed verification. "
                              f"Measured local size: {local_report['dimensions_mm']}; expected: {requested}.")
        world = pose(body, part.placement, self.parameters, part.id)
        attachment_report = None
        if part.attachment:
            attachment = part.attachment
            parent = self.component(attachment.parent)
            self.component_dependencies[part.id].add(parent.component.id)
            parent_bounds = parent.validation["bounds_mm"]
            child_bounds = measure(world)["bounds_mm"]
            axis = "XYZ".index(attachment.axis)
            offsets = iter(self.parameters.vector(attachment.offset, part.id))
            gap = self.parameters.value(attachment.gap, part.id)
            if not 0 <= gap <= 2000:
                raise DesignError("An attachment gap must be between 0 and 2,000 mm.")
            delta = []
            for index in range(3):
                if index == axis:
                    parent_face = parent_bounds[1 if attachment.side > 0 else 0][index]
                    child_face = child_bounds[0 if attachment.side > 0 else 1][index]
                    delta.append(parent_face - child_face + attachment.side * gap)
                else:
                    parent_centre = (parent_bounds[0][index] + parent_bounds[1][index]) / 2
                    child_centre = (child_bounds[0][index] + child_bounds[1][index]) / 2
                    delta.append(parent_centre + next(offsets) - child_centre)
            if any(abs(value) > 10000 for value in delta):
                raise DesignError("Attachment positions must stay within +/-10,000 mm.")
            world = world.translate(tuple(delta))
            attachment_report = {"parent": attachment.parent, "axis": attachment.axis,
                                 "side": attachment.side, "translation_adjustment_mm": delta}
        report = measure(world)
        report.update(checks=checks, passed=True, local_dimensions_mm=local_report["dimensions_mm"])
        if attachment_report:
            report["attachment"] = attachment_report
        result = BuiltComponent(part, body, world, self.parameters.for_component(part.id), report, feature_report)
        self.built[part.id] = result
        self.active.remove(part.id)
        return result

    def sketch(self, feature, component):
        plane = cq.Plane.named(feature.plane)
        plane.origin = cq.Vector(*self.parameters.vector(feature.origin, component))
        work = cq.Workplane(plane).center(*self.parameters.vector(feature.centre, component))
        if feature.profile == "circle":
            work = work.circle(self.size(feature.radius, component))
        elif feature.profile == "rectangle":
            work = work.rect(self.size(feature.width, component), self.size(feature.height, component))
        elif feature.profile == "ellipse":
            work = work.ellipse(self.size(feature.width, component) / 2, self.size(feature.height, component) / 2)
        else:
            points = [self.parameters.vector(point, component) for point in feature.points]
            if len(points) < 3:
                raise DesignError("A closed profile needs at least three points.")
            if feature.profile == "polygon":
                work = work.polyline(points).close()
            else:
                work = work.spline(points, periodic=True)
        wire = work.val()
        if not isinstance(wire, cq.Wire):
            wire = cq.Wire.assembleEdges([wire])
        face = cq.Face.makeFromWires(wire)
        if not face.isValid() or face.Area() <= TOLERANCE:
            raise DesignError("The sketch must be a valid closed profile without self intersections.")
        return wire, plane.zDir

    @staticmethod
    def lookup(items, name, kind):
        if name not in items:
            raise DesignError(f"Reference '{name}' must point to an earlier {kind} in this component.")
        return items[name]

    def holes(self, feature, component, body):
        if body is None:
            raise DesignError("Drilling requires an existing body.")
        bounds = measure(body)["bounds_mm"]
        axis = "XYZ".index(feature.axis)
        transverse = [index for index in range(3) if index != axis]
        radius = self.size(feature.radius, component)
        centres = [self.parameters.vector(centre, component) for centre in feature.centres]
        for index, centre in enumerate(centres):
            if any(math.dist(centre, other) <= 2 * radius for other in centres[index + 1:]):
                raise DesignError("Distinct holes must not overlap or touch; use a pocket or cylinder cuts for a slot.")
        top = bounds[1][axis]
        bottom = bounds[0][axis] - 1
        if feature.depth is not None:
            depth = self.size(feature.depth, component)
            if depth >= top - bounds[0][axis]:
                raise DesignError("A blind-hole depth must be smaller than the part extent; use depth=null for through holes.")
            bottom = top - depth
        direction = [0, 0, 0]
        direction[axis] = 1
        tools = []
        for centre in centres:
            origin = [0, 0, 0]
            origin[axis] = bottom
            for index, value in zip(transverse, centre):
                origin[index] = value
            tool = cq.Solid.makeCylinder(radius, top + 1 - bottom, tuple(origin), tuple(direction))
            if body.intersect(tool).Volume() <= TOLERANCE:
                raise DesignError("Every hole centre must intersect material.")
            tools.append(tool)
        return cq.Compound.makeCompound(tools)

    def tool(self, feature, component, sketches, tools):
        n = lambda value: self.number(value, component)
        size = lambda value: self.size(value, component)
        vector = lambda value: self.parameters.vector(value, component)
        kind = feature.type
        if kind == "box":
            lengths = [size(value) for value in feature.size]
            return cq.Workplane("XY").box(*lengths, centered=feature.centered).val()
        if kind == "cylinder":
            return cq.Solid.makeCylinder(size(feature.radius), size(feature.height))
        if kind == "cone":
            bottom, top = self.size(feature.radius_bottom, component, True), self.size(feature.radius_top, component, True)
            if bottom == top == 0:
                raise DesignError("A cone needs a nonzero radius.")
            return cq.Solid.makeCone(bottom, top, size(feature.height))
        if kind == "sphere":
            return cq.Solid.makeSphere(size(feature.radius), angleDegrees1=-90, angleDegrees2=90)
        if kind == "extrude":
            wire, normal = self.lookup(sketches, feature.sketch, "sketch")
            distance = n(feature.distance)
            if not 0 < abs(distance) <= 2000:
                raise DesignError("Extrusion distance must be nonzero and within +/-2,000 mm.")
            if feature.symmetric:
                wire = wire.translate(normal * (-distance / 2))
            return cq.Solid.extrudeLinear(wire, [], normal * distance)
        if kind == "revolve":
            wire, _ = self.lookup(sketches, feature.sketch, "sketch")
            angle = n(feature.angle)
            if not 0 < angle <= 360:
                raise DesignError("Revolution angle must be between 0 and 360 degrees.")
            return cq.Solid.revolve(wire, [], angle, vector(feature.axis_start), vector(feature.axis_end))
        if kind == "loft":
            if feature.sections:
                plane = cq.Plane.named(feature.plane)
                sections = []
                for section in feature.sections:
                    station = n(section.station)
                    if abs(station) > 10000:
                        raise DesignError("Loft section stations must be within +/-10,000 mm.")
                    located = cq.Plane(origin=plane.zDir * station, xDir=plane.xDir, normal=plane.zDir)
                    work = cq.Workplane(located).center(*vector(section.centre))
                    width, height = size(section.width), size(section.height)
                    work = work.ellipse(width / 2, height / 2) if feature.profile == "ellipse" else work.rect(width, height)
                    sections.append((work.val(), plane.zDir))
            else:
                sections = [self.lookup(sketches, name, "sketch") for name in feature.sketches]
            for (previous, normal), (current, next_normal) in zip(sections, sections[1:]):
                parallel = normal.cross(next_normal).Length < TOLERANCE
                if parallel and abs((current.Center() - previous.Center()).dot(normal)) < TOLERANCE:
                    axis = "XYZ"[max(range(3), key=lambda index: abs(normal.toTuple()[index]))]
                    raise DesignError(f"Loft sections are coplanar. Separate their sketch origins along {axis}, the plane normal. "
                                      "XY sections vary Z; XZ sections vary Y; YZ sections vary X. "
                                      "Use local section origins and apply the component's world placement only once.")
            wires = [wire for wire, _ in sections]
            return cq.Solid.makeLoft(wires, ruled=feature.ruled)
        if kind == "sweep":
            wire, _ = self.lookup(sketches, feature.sketch, "sketch")
            points = [cq.Vector(*vector(point)) for point in feature.path]
            path = cq.Edge.makeSpline(points) if feature.smooth else cq.Wire.makePolygon(points)
            return cq.Solid.sweep(wire, [], path, isFrenet=feature.frenet, transitionMode="round")
        if kind in ("linear_pattern", "circular_pattern"):
            original = self.lookup(tools, feature.feature, "solid feature")
            instances = []
            if kind == "linear_pattern":
                step = cq.Vector(*vector(feature.step))
                if step.Length < TOLERANCE:
                    raise DesignError("A pattern needs a nonzero step.")
                instances = [original.translate(step * index) for index in range(1, feature.count)]
            else:
                angle = n(feature.angle)
                if not 0 < abs(angle) <= 360:
                    raise DesignError("Pattern angle must be nonzero and within +/-360 degrees.")
                increment = angle / (feature.count if math.isclose(abs(angle), 360) else feature.count - 1)
                instances = [original.rotate(vector(feature.axis_start), vector(feature.axis_end), increment * index)
                             for index in range(1, feature.count)]
            # The seed was already applied. Pattern only the new instances of its tool.
            return cq.Compound.makeCompound(instances)
        if kind == "mirror":
            original = self.lookup(tools, feature.feature, "solid feature")
            return original.mirror(vector(feature.normal), vector(feature.origin))
        if kind == "boolean":
            self.component_dependencies[component].add(feature.component)
            return self.component(feature.component).local_shape.copy()
        if kind == "thread":
            major, minor, pitch, length = size(feature.major_radius), size(feature.minor_radius), size(feature.pitch), size(feature.length)
            if not 0 < minor < major or major - minor >= pitch * 0.8:
                raise DesignError("A thread needs minor radius < major radius and a depth smaller than 0.8 times its pitch.")
            if length / pitch > 48:
                raise DesignError("This worker limits a helical thread to 48 turns.")
            helix = cq.Wire.makeHelix(pitch, length, minor, lefthand=feature.left_hand)
            overlap = min(0.02, minor * 0.02)
            profile = cq.Wire.makePolygon([(minor - overlap, 0, -pitch * 0.35),
                                          (major, 0, 0), (minor - overlap, 0, pitch * 0.35)], close=True)
            ridge = cq.Solid.sweep(profile, [], helix, isFrenet=True)
            trim = cq.Solid.makeCylinder(major + 0.1, length)
            core = cq.Solid.makeCylinder(minor, length)
            return core.fuse(ridge.intersect(trim)).clean()
        raise DesignError(f"Unknown modelling operation '{kind}'.")


def verify_assembly(builder: Builder, components: list[BuiltComponent]):
    lookup = {part.component.id: part for part in components}
    relations, attachments, failures = [], [], []

    def anchor(part, point):
        result = posed_vector(point, part.component.placement, builder.parameters, part.component.id)
        delta = part.validation.get("attachment", {}).get("translation_adjustment_mm", (0, 0, 0))
        return result.add(cq.Vector(*delta))

    for part in components:
        if part.component.attachment:
            rule = part.component.attachment
            parent = lookup[rule.parent]
            distance = part.shape.distance(parent.shape)
            expected = builder.parameters.value(rule.gap, part.component.id)
            passed = math.isclose(distance, expected, abs_tol=0.01, rel_tol=1e-5)
            attachments.append({"component_id": part.component.id, "parent": rule.parent,
                                "distance_mm": distance, "expected_gap_mm": expected, "passed": passed})
            if not passed:
                failures.append(f"Attachment '{part.component.id}' to '{rule.parent}' failed: actual surface distance "
                                f"{distance:.3f} mm, expected gap {expected:.3f} mm. Correct the attachment offset or geometry; "
                                "aligned bounding faces alone do not establish contact.")

    for relationship in builder.design.relationships:
        a, b = lookup[relationship.component_a], lookup[relationship.component_b]
        if relationship.type == "contact":
            distance = a.shape.distance(b.shape)
            check = {"id": relationship.id, "type": "contact", "distance_mm": distance,
                     "passed": distance <= relationship.tolerance}
        elif relationship.type == "distance":
            pa, pb = anchor(a, relationship.point_a), anchor(b, relationship.point_b)
            target = builder.parameters.value(relationship.distance, a.component.id)
            if target < 0 or target > 10000:
                raise DesignError("An anchor distance must be between 0 and 10,000 mm.")
            distance = (pb - pa).Length
            check = {"id": relationship.id, "type": "distance", "distance_mm": distance,
                     "expected_distance_mm": target, "passed": abs(distance - target) <= relationship.tolerance}
        else:
            pa, pb = anchor(a, relationship.point_a), anchor(b, relationship.point_b)
            aa = posed_vector(relationship.axis_a, a.component.placement, builder.parameters, a.component.id, True)
            ab = posed_vector(relationship.axis_b, b.component.placement, builder.parameters, b.component.id, True)
            if min(aa.Length, ab.Length) < TOLERANCE:
                raise DesignError("Assembly axes must be nonzero vectors.")
            aa, ab = aa.normalized(), ab.normalized()
            deviation = aa.cross(ab).Length
            distance = (pb - pa).cross(aa).Length
            check = {"id": relationship.id, "type": "coaxial", "axis_deviation": deviation,
                     "axis_distance_mm": distance, "passed": deviation <= 1e-5 and distance <= relationship.tolerance}
        relations.append(check)
        if not check["passed"]:
            separation = check.get("distance_mm", check.get("axis_distance_mm", 0))
            detail = f"expected {check['expected_distance_mm']:.3f} mm anchor distance" if relationship.type == "distance" else "revise the component placements"
            bounds_a, bounds_b = a.validation["bounds_mm"], b.validation["bounds_mm"]
            failures.append(f"Assembly relationship '{relationship.id}' failed ({separation:.3f} mm separation); {detail}. "
                            f"{a.component.id} world bounds={bounds_a}; {b.component.id} world bounds={bounds_b}.")
    allowed = {frozenset(pair) for pair in builder.design.allowed_intersections}
    interferences = []
    for index, a in enumerate(components):
        for b in components[index + 1:]:
            overlap = a.shape.intersect(b.shape).Volume()
            significant = overlap > max(1e-4, min(a.shape.Volume(), b.shape.Volume()) * 1e-7)
            if significant:
                permitted = frozenset((a.component.id, b.component.id)) in allowed
                interferences.append({"components": [a.component.id, b.component.id],
                                      "volume_mm3": overlap, "explicitly_allowed": permitted})
                if not permitted:
                    failures.append(f"Parts '{a.component.id}' and '{b.component.id}' intersect ({overlap:.3f} mm³). "
                                    "Correct their placements/features. Do not permit an intersection unless the user requests it.")
    unused = sorted(set(builder.parameters.raw) - builder.parameters.used_parameters())
    if failures:
        if unused:
            failures.append("Parameters not linked to geometry: " + ", ".join(unused) + ". Use them in the feature/placement expressions.")
        raise DesignError("\n".join(failures))
    compound = cq.Compound.makeCompound([part.shape for part in components])
    report = measure(compound)
    report.update(passed=True, checks={"all_components_valid": True, "relationships_pass": True,
                                      "attachment_contacts_valid": True,
                                      "no_unexpected_intersections": True},
                  relationships=relations, attachments=attachments, interferences=interferences,
                  parameter_dependencies={key: sorted(value) for key, value in builder.parameters.dependencies.items()},
                  component_dependencies={key: sorted(value) for key, value in builder.component_dependencies.items()},
                  unused_parameters=unused,
                  warnings=(["Intentional part intersections are present."] if interferences else [])
                  + (["Parameters not linked to features or placements: " + ", ".join(unused)] if unused else []))
    return report

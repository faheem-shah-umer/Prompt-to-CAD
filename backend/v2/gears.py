"""Parametric involute gears for the controlled CAD language.

One call builds a spur, helical or herringbone gear (external or internal ring) from
module, tooth count, face width and helix angle, so agents do not hand-write tooth
profiles. Results are cached per worker process, so script retries and repeated
gears with the same parameters reuse the same geometry.
"""

import math
from collections import OrderedDict

import cadquery as cq

from backend.native.contracts import WorkspaceError

_CACHE = OrderedDict()
_CACHE_SIZE = 16
_FLANK_SAMPLES = 9


def _number(value, name, low, high):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise WorkspaceError(f"gear {name} must be a number from {low} to {high}.", "invalid_parameters")
    return float(value)


def _teeth(value, low):
    if type(value) is float and value.is_integer():
        value = int(value)
    if type(value) is not int or not low <= value <= 400:
        raise WorkspaceError(f"gear teeth must be a whole number from {low} to 400.", "invalid_parameters")
    return value


def _involute(angle):
    return math.tan(angle) - angle


def _point(radius, angle):
    return cq.Vector(radius * math.cos(angle), radius * math.sin(angle), 0)


def _profile(module, teeth, addendum, dedendum, pressure, thickness):
    """Closed tooth outline with one tooth centred on +X (angle 0)."""
    pitch = module * teeth / 2
    base = pitch * math.cos(pressure)
    tip, root = pitch + addendum, pitch - dedendum
    if root <= 0:
        raise WorkspaceError("gear root radius must be positive; use more teeth or a smaller module.", "invalid_parameters")
    start = max(root, base)
    half = thickness / (2 * pitch) + _involute(pressure)

    def flank_angle(radius):
        return half - _involute(math.acos(min(1.0, base / radius)))

    tip_half, start_half = flank_angle(tip), flank_angle(start)
    if tip_half <= 1e-4:
        raise WorkspaceError("gear teeth become pointed before the tip circle; reduce the module or backlash, or change the tooth count.",
                             "invalid_parameters")
    if 2 * start_half >= 2 * math.pi / teeth - 1e-4:
        raise WorkspaceError("gear teeth overlap at the root circle; increase the tooth count or backlash.", "invalid_parameters")
    radii = [start + (tip - start) * i / (_FLANK_SAMPLES - 1) for i in range(_FLANK_SAMPLES)]
    edges = []
    step = 2 * math.pi / teeth
    for index in range(teeth):
        centre = index * step
        rising = [_point(r, centre - flank_angle(r)) for r in radii]
        falling = [_point(r, centre + flank_angle(r)) for r in reversed(radii)]
        if root < start:
            edges.append(cq.Edge.makeLine(_point(root, centre - start_half), rising[0]))
        edges.append(cq.Edge.makeSpline(rising))
        edges.append(cq.Edge.makeThreePointArc(rising[-1], _point(tip, centre), falling[0]))
        edges.append(cq.Edge.makeSpline(falling))
        root_start = _point(root, centre + start_half)
        if root < start:
            edges.append(cq.Edge.makeLine(falling[-1], root_start))
        else:
            root_start = falling[-1]
        following = ((index + 1) % teeth) * step
        root_end = _point(root, following - start_half) if root < start else _point(start, following - start_half)
        edges.append(cq.Edge.makeThreePointArc(root_start, _point(root, centre + step / 2), root_end))
    return cq.Wire.assembleEdges(edges)


def _extrude(outer, inner, width, twist_degrees):
    if abs(twist_degrees) < 1e-9:
        return cq.Solid.extrudeLinear(outer, inner, cq.Vector(0, 0, width))
    return cq.Solid.extrudeLinearWithRotation(outer, inner, cq.Vector(0, 0, 0), cq.Vector(0, 0, width), twist_degrees)


def _single_solid(shape):
    solids = shape.Solids()
    if len(solids) != 1 or not solids[0].isValid():
        raise WorkspaceError("The gear did not form one valid solid; adjust its parameters.", "script_failed")
    return solids[0]


def _build(module, teeth, face_width, helix_angle, herringbone, internal, rim_width, bore_diameter,
           pressure_angle, backlash):
    pressure = math.radians(pressure_angle)
    pitch = module * teeth / 2
    circular = math.pi * module / 2
    if internal:
        # The ring's tooth space is the conjugate of an external tooth: cut that cavity from an annulus.
        cavity = _profile(module, teeth, 1.25 * module, module, pressure, circular + backlash)
        outer_radius = pitch + 1.25 * module + rim_width
        outer = cq.Wire.makeCircle(outer_radius, cq.Vector(0, 0, 0), cq.Vector(0, 0, 1))
        inner = [cavity]
    else:
        outer = _profile(module, teeth, module, 1.25 * module, pressure, circular - backlash)
        inner = []
        if bore_diameter:
            if bore_diameter / 2 >= pitch - 1.25 * module - 0.5:
                raise WorkspaceError("gear bore_diameter must leave at least 0.5 mm of material below the tooth roots.",
                                     "invalid_parameters")
            inner = [cq.Wire.makeCircle(bore_diameter / 2, cq.Vector(0, 0, 0), cq.Vector(0, 0, 1))]
    # Helix angle is measured at the pitch radius: twist over height h is h * tan(beta) / r.
    if not herringbone:
        twist = math.degrees(face_width * math.tan(math.radians(helix_angle)) / pitch)
        return _single_solid(_extrude(outer, inner, face_width, twist))
    half = face_width / 2
    twist = math.degrees(half * math.tan(math.radians(helix_angle)) / pitch)
    lower = _extrude(outer, inner, half, twist)
    axis_start, axis_end = (0, 0, 0), (0, 0, 1)
    upper_outer = outer.rotate(axis_start, axis_end, twist).translate((0, 0, half))
    upper_inner = [w.rotate(axis_start, axis_end, twist).translate((0, 0, half)) for w in inner]
    upper = cq.Solid.extrudeLinearWithRotation(upper_outer, upper_inner, cq.Vector(0, 0, half),
                                               cq.Vector(0, 0, half), -twist) if abs(twist) > 1e-9 else \
        cq.Solid.extrudeLinear(upper_outer, upper_inner, cq.Vector(0, 0, half))
    joined = lower.fuse(upper, glue=True).clean()
    try:
        return _single_solid(joined)
    except WorkspaceError:
        return _single_solid(lower.fuse(upper).clean())


def gear(module, teeth, face_width, helix_angle=0, herringbone=False, internal=False, rim_width=None,
         bore_diameter=0, pressure_angle=20, backlash=0.1):
    """Involute gear solid centred on the Z axis, from z=0 to z=face_width.

    External gears have a tooth centred on +X; internal (ring) gears have a tooth space on +X.
    helix_angle (degrees, at the pitch circle) twists counter-clockwise going up when positive.
    Meshing hands: external pairs use opposite signs; a ring uses the same sign as its planets.
    backlash (mm) thins each external tooth and widens each internal space at the pitch circle.
    """
    module = _number(module, "module", 0.1, 50)
    teeth = _teeth(teeth, 12 if internal else 6)
    face_width = _number(face_width, "face_width", 0.1, 2000)
    helix_angle = _number(helix_angle, "helix_angle", -45, 45)
    pressure_angle = _number(pressure_angle, "pressure_angle", 14, 30)
    backlash = _number(backlash, "backlash", 0, module * 0.5)
    if type(herringbone) is not bool or type(internal) is not bool:
        raise WorkspaceError("gear herringbone and internal must be True or False.", "invalid_parameters")
    if herringbone and abs(helix_angle) < 1e-9:
        raise WorkspaceError("A herringbone gear needs a nonzero helix_angle.", "invalid_parameters")
    if internal:
        rim_width = _number(3 * module if rim_width is None else rim_width, "rim_width", 0.1, 2000)
        if bore_diameter:
            raise WorkspaceError("bore_diameter applies to external gears; set rim_width for a ring gear.", "invalid_parameters")
    else:
        rim_width = 0.0
    bore_diameter = _number(bore_diameter, "bore_diameter", 0, 4000)
    key = (module, teeth, face_width, helix_angle, herringbone, internal, rim_width, bore_diameter,
           pressure_angle, backlash)
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    try:
        shape = _build(*key)
    except WorkspaceError:
        raise
    except Exception as error:  # OCCT construction failures become a normal script error.
        raise WorkspaceError("Gear construction failed: " + str(error), "script_failed") from None
    _CACHE[key] = shape
    while len(_CACHE) > _CACHE_SIZE:
        _CACHE.popitem(last=False)
    return shape


def planet_mesh_rotation(sun_teeth, planet_teeth, planet_angle_deg):
    """Rotation (degrees, about the planet's own axis) that meshes a planet placed at planet_angle_deg around the sun.

    Assumes gear() orientation: the sun has a tooth on +X before any rotation.
    """
    sun, planet = _teeth(sun_teeth, 6), _teeth(planet_teeth, 6)
    angle = _number(planet_angle_deg, "planet_angle_deg", -3600, 3600)
    rotation = angle * (1 + sun / planet) + 180 - 180 / planet
    return rotation % (360 / planet)


def ring_mesh_rotation(ring_teeth, planet_teeth):
    """Ring rotation (degrees) that meshes with planets phased by planet_mesh_rotation.

    Valid when (sun_teeth + ring_teeth) is divisible by the number of equally spaced planets.
    """
    ring, planet = _teeth(ring_teeth, 12), _teeth(planet_teeth, 6)
    return ((180 / ring) * (1 - planet)) % (360 / ring)

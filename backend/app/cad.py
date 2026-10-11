"""Construct and measure geometry, independently of HTTP or the interface."""

from math import isclose, pi

import cadquery as cq
from OCP.BRepAdaptor import BRepAdaptor_Surface


def build_plate(spec):
    plate = cq.Workplane("XY").box(spec["length"], spec["width"], spec["thickness"])
    if spec["hole_centres"]:
        plate = (
            plate.faces(">Z").workplane()
            .pushPoints([tuple(centre) for centre in spec["hole_centres"]])
            .hole(spec["hole_diameter"])
        )
    return plate


def measure_plate(plate, spec):
    shape = plate.val()
    bounds = shape.BoundingBox()
    measured_holes = []
    for face in shape.Faces():
        if face.geomType() == "CYLINDER":
            cylinder = BRepAdaptor_Surface(face.wrapped).Cylinder()
            centre = cylinder.Location()
            measured_holes.append({
                "centre_xy_mm": [centre.X(), centre.Y()],
                "diameter_mm": 2 * cylinder.Radius(),
            })
    volume_expected = (
        spec["length"] * spec["width"] * spec["thickness"]
        - len(spec["hole_centres"]) * pi * (spec["hole_diameter"] / 2) ** 2 * spec["thickness"]
    )
    actual_dimensions = [bounds.xlen, bounds.ylen, bounds.zlen]
    expected_dimensions = [spec[k] for k in ("length", "width", "thickness")]

    def close(a, b):
        return isclose(a, b, rel_tol=1e-8, abs_tol=1e-6)

    checks = {
        "brep_valid": shape.isValid(),
        "one_solid": len(plate.solids().vals()) == 1,
        "dimensions_match": all(close(a, b) for a, b in zip(actual_dimensions, expected_dimensions)),
        "volume_matches": close(shape.Volume(), volume_expected),
        "hole_count_matches": len(measured_holes) == len(spec["hole_centres"]),
        "hole_geometry_matches": all(
            any(
                close(hole["centre_xy_mm"][0], x)
                and close(hole["centre_xy_mm"][1], y)
                and close(hole["diameter_mm"], spec["hole_diameter"])
                for hole in measured_holes
            )
            for x, y in spec["hole_centres"]
        ),
    }
    return {
        "checks": checks,
        "passed": all(checks.values()),
        "dimensions_mm": actual_dimensions,
        "volume_mm3": shape.Volume(),
        "expected_volume_mm3": volume_expected,
        "measured_holes": measured_holes,
    }

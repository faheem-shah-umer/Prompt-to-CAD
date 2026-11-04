"""Measure exact assembly intersections before and after the broad phase."""

import argparse
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import cadquery as cq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.native.modelling import verify_assembly


def builder():
    return SimpleNamespace(
        design=SimpleNamespace(relationships=[], allowed_intersections=[]),
        parameters=SimpleNamespace(raw={}, used_parameters=lambda: set(), dependencies={}),
        component_dependencies={},
    )


def components(count):
    result = []
    width = max(1, int(count**0.5))
    for index in range(count):
        x, y = index % width, index // width
        shape = cq.Workplane("XY").box(1, 1, 1).translate((x * 3, y * 3, 0)).val()
        result.append(SimpleNamespace(
            component=SimpleNamespace(id=f"part-{index}", attachment=None),
            shape=shape,
            validation={"bounds_mm": [[x * 3 - 0.5, y * 3 - 0.5, -0.5], [x * 3 + 0.5, y * 3 + 0.5, 0.5]]},
        ))
    return result


def legacy_exact(parts):
    started = time.perf_counter()
    checked = 0
    for index, first in enumerate(parts):
        for second in parts[index + 1:]:
            first.shape.intersect(second.shape).Volume()
            checked += 1
    return {"wall_seconds": time.perf_counter() - started, "exact_intersections_checked": checked}


def run(count):
    parts = components(count)
    before = legacy_exact(parts)
    started = time.perf_counter()
    report = verify_assembly(builder(), parts)
    after = {
        "wall_seconds": time.perf_counter() - started,
        **report["verification_timing"],
    }
    return {"components": count, "before": before, "after": after}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--small", type=int, default=8)
    parser.add_argument("--large", type=int, default=64)
    args = parser.parse_args()
    print(json.dumps({"small": run(args.small), "large": run(args.large)}, indent=2))

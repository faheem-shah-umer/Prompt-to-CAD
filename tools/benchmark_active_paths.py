"""Benchmark the active mutation intersection guard and final exact checks.

This keeps CAD generation out of the measurement so the reported numbers isolate
the geometry checks used by script, catalog insertion, and standard-part paths.
"""

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

import cadquery as cq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.native.geometry import check_new_intersections
from backend.native.geometry import store_shape
from backend.native.worker_client import GeometryWorker


def scene(count):
    shapes = {}
    before = {"components": []}
    after = {"components": []}
    width = max(1, int(count**0.5))
    for index in range(count):
        x, y = index % width, index // width
        identity = f"part-{index}"
        shape = cq.Workplane("XY").box(1, 1, 1).translate((x * 3, y * 3, 0)).val()
        shapes[identity] = shape
        component = {
            "instance_id": identity,
            "name": identity,
            "asset_hash": f"asset-{index}",
            "matrix": [1, 0, 0, x * 3, 0, 1, 0, y * 3, 0, 0, 1, 0],
        }
        before["components"].append(component)
        after["components"].append({**component, "asset_hash": f"changed-{index}"} if index == 0 else component)
    return before, after, shapes


def active_guard(count, path):
    before, after, shapes = scene(count)
    stats = {}
    started = time.perf_counter()
    check_new_intersections(
        ".",
        before,
        after,
        {"type": path},
        shape_for=lambda part: shapes[part["instance_id"]],
        stats=stats,
    )
    return {"wall_seconds": time.perf_counter() - started, **stats}


def final_exact(count):
    _, _, shapes = scene(count)
    values = list(shapes.values())
    started = time.perf_counter()
    checked = 0
    for index, first in enumerate(values):
        for second in values[index + 1:]:
            first.intersect(second).Volume()
            checked += 1
    return {"wall_seconds": time.perf_counter() - started, "exact_intersections_checked": checked}


def worker_snapshot(folder, count):
    shape = cq.Workplane("XY").box(1, 1, 1).val()
    asset = store_shape(folder, shape)
    components = []
    width = max(1, int(count**0.5))
    for index in range(count):
        x, y = index % width, index // width
        components.append({
            "instance_id": "base" if index == 0 else f"base-{index}",
            "name": "base" if index == 0 else f"base-{index}",
            "definition_id": f"definition-{index}",
            "parent_id": None,
            "matrix": [1, 0, 0, x * 3, 0, 1, 0, y * 3, 0, 0, 1, 0],
            "color": [0.65, 0.72, 0.82],
            **asset,
        })
    return {
        "document_id": "benchmark",
        "revision_id": "benchmark",
        "components": components,
        "assembly_nodes": [],
        "engineering": [],
        "definitions": [],
    }


def worker_call(folder, method, params):
    worker = GeometryWorker(folder / "logs", timeout=120)
    started = time.perf_counter()
    try:
        result = worker.call(method, params)
        return {"wall_seconds": time.perf_counter() - started, "status": "succeeded", "result": result}
    except Exception as error:
        log = folder / "logs" / "geometry.log"
        detail = log.read_text(encoding="utf-8", errors="replace")[-2000:] if log.exists() else ""
        return {"wall_seconds": time.perf_counter() - started, "status": "failed",
                "error_code": getattr(error, "code", "failed"), "error": str(error),
                "worker_log_tail": detail}
    finally:
        worker.close()


def worker_paths(count):
    repository_tmp = Path(__file__).resolve().parents[1] / "tmp"
    repository_tmp.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="prompt-to-cad-benchmark-", dir=repository_tmp) as raw:
        folder = Path(raw)
        folder.mkdir(exist_ok=True)
        snapshot = worker_snapshot(folder, count)
        offset = count * 4
        script = worker_call(
            folder,
            "script",
            {
                "project_dir": str(folder),
                "snapshot": snapshot,
                "source": f"parts = {{'new': cq.Workplane('XY').box(1,1,1).translate(({offset},0,0))}}",
                "parameters": {},
                "source_instance_ids": [],
            },
        )
        catalog_path = folder / "catalog.step"
        cq.exporters.export(cq.Workplane("XY").box(1, 1, 1).val(), str(catalog_path))
        catalog = worker_call(
            folder,
            "catalog_insert",
            {
                "project_dir": str(folder),
                "snapshot": snapshot,
                "path": str(catalog_path),
                "provenance": {"name": "benchmark", "catalog_id": 1, "fingerprint": "0" * 64},
                "placement": {"translation": [offset, 0, 0], "rotation": [0, 0, 0]},
            },
        )
        standard = worker_call(
            folder,
            "standard_part",
            {
                "project_dir": str(folder),
                "snapshot": snapshot,
                "request": {
                    "generator_id": "bearing.SingleRowDeepGrooveBallBearing",
                    "parameters": {"size": "M8-22-7", "bearing_type": "SKT"},
                    "placement": {"translation": [offset, 0, 0], "rotation": [0, 0, 0]},
                },
            },
        )
        mutations = {
            "script_worker": script,
            "catalog_worker": catalog,
            "standard_part_worker": standard,
        }
        validations = {}
        for name, result in mutations.items():
            if result["status"] != "succeeded":
                validations[name.replace("_worker", "_final_validation")] = {
                    "status": "not_run",
                    "reason": "mutation scenario failed",
                }
                continue
            validations[name.replace("_worker", "_final_validation")] = worker_call(
                folder,
                "verify",
                {"project_dir": str(folder), "snapshot": result["result"]},
            )
        return {"mutations": mutations, "final_validations": validations}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--components", type=int, default=64)
    args = parser.parse_args()
    report = {
        "script": active_guard(args.components, "script"),
        "catalog_insert": active_guard(args.components, "catalog_insert"),
        "standard_part": active_guard(args.components, "standard_part"),
        "final_exact_baseline": final_exact(args.components),
        "worker_entry_points": worker_paths(args.components),
    }
    print(json.dumps(report, indent=2))
    worker_report = report["worker_entry_points"]
    failures = [
        name for name, result in worker_report["mutations"].items()
        if result["status"] != "succeeded"
    ]
    failures.extend(
        name for name, result in worker_report["final_validations"].items()
        if result["status"] != "succeeded"
    )
    if failures:
        print(f"Required worker benchmark scenarios failed: {', '.join(failures)}", file=sys.stderr)
        raise SystemExit(1)

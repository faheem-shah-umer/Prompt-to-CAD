import argparse
import json
import os
import platform
import time
from datetime import datetime, timezone
from pathlib import Path

import cadquery as cq
import psutil

from backend.native.service import Workspace

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Exercise the configured model on the imported plate.")
    parser.add_argument("--benchmark", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/native-validation")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    report = {"timestamp_utc": datetime.now(timezone.utc).isoformat(),
              "hardware": {"platform": platform.platform(), "processor": platform.processor(),
                           "logical_cpus": os.cpu_count(), "memory_gb": round(psutil.virtual_memory().total / 1024**3, 2)},
              "scope": "Representative simple mechanical solids; these results do not establish arbitrary CAD/model reliability."}
    previous_report = args.output / "report.json"
    if not args.live and previous_report.exists():
        previous = json.loads(previous_report.read_text(encoding="utf-8"))
        if "live" in previous:
            report["live"] = previous["live"]
    ws = Workspace(args.output / "projects", lambda event: print(event.get("stage"), event.get("message"), flush=True)
                   if event.get("stage") != "candidate" else None)
    try:
        if args.live:
            plate = args.output / "acceptance-plate.step"
            cq.exporters.export(cq.Workplane("XY").box(80, 60, 8).val(), str(plate))
            doc = ws.dispatch("document.import", {"path": str(plate)})
            id = doc["components"][0]["instance_id"]
            prompt = ("Add four 6 mm diameter through holes at local XY centres (-30,-20), (-30,20), (30,-20), (30,20). "
                      "Then fillet only the four outside vertical corner edges to radius 2 mm. "
                      "Keep the 80 x 60 x 8 mm outer dimensions. Complete both operations.")
            started = time.monotonic()
            try:
                result = ws.dispatch("agent.run", {"base_revision_id": doc["revision_id"], "prompt": prompt,
                                                  "selection": {"revision_id": doc["revision_id"], "instance_id": id}})
                final = ws.document.current()
                expected = (80*60 - 4*3.141592653589793*9 - (4-3.141592653589793)*4)*8
                report["live"] = {"status": result["status"], "seconds": time.monotonic() - started,
                                  "message": result["message"], "commands": final["commands"],
                                  "volume_matches_acceptance": abs(final["components"][0]["metrics"]["volume_mm3"] - expected) < 0.01,
                                  "dimensions_mm": final["components"][0]["metrics"]["dimensions_mm"],
                                  "verification": final["verification"], "project_dir": str(ws.document.folder)}
                if report["live"]["volume_matches_acceptance"]:
                    ws.dispatch("document.export", {"base_revision_id": final["revision_id"], "path": str(args.output / "agent-edited-plate.step")})
            except Exception as error:
                report["live"] = {"status": "failed", "message": str(error), "seconds": time.monotonic() - started,
                                  "accepted_revision_preserved": ws.document.current()["revision_id"] == doc["revision_id"]}
        if args.benchmark:
            benchmarks = []
            for count in (1, 25, 100):
                assembly = cq.Assembly(name=f"Benchmark {count}")
                body = cq.Workplane("XY").box(10, 8, 6).val()
                for n in range(count):
                    assembly.add(body, name=f"Part {n:03}", color=cq.Color(0.6, 0.65, 0.8),
                                 loc=cq.Location(((n % 10) * 20, (n // 10) * 20, 0)))
                source = args.output / f"assembly-{count}.step"
                assembly.export(str(source))
                started = time.monotonic()
                doc = ws.dispatch("document.import", {"path": str(source)})
                imported = time.monotonic() - started
                target = doc["components"][0]
                started = time.monotonic()
                changed = ws.dispatch("document.command", {"base_revision_id": doc["revision_id"],
                    "command": {"type": "hole", "instance_id": target["instance_id"], "diameter": 2, "centres": [[0, 0]]}})["document"]
                editing = time.monotonic() - started
                unchanged = all(a == b for a, b in zip(doc["components"][1:], changed["components"][1:]))
                worker_pid = ws.geometry("hello", {})["worker_pid"]
                worker_memory = psutil.Process(worker_pid).memory_info().rss / 1024**2
                benchmarks.append({"components": count, "import_and_verification_seconds": imported,
                                   "edit_and_verification_seconds": editing, "worker_rss_mb": round(worker_memory, 2),
                                   "faces": sum(p["topology"]["faces"] for p in changed["components"]),
                                   "edges": sum(p["topology"]["edges"] for p in changed["components"]),
                                   "unmodified_instances_preserved": unchanged, "project_dir": str(ws.document.folder)})
            report["benchmarks"] = benchmarks
    finally:
        ws.worker.close()
        path = args.output / "report.json"
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(path, flush=True)
    if args.live and not report.get("live", {}).get("volume_matches_acceptance"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

"""Render synthetic bearing/chain fixtures with the isolated native viewer target."""

import argparse
import json
import subprocess
from uuid import uuid4

from backend.native.workspace import Workspace
from tools.build_native import ROOT, add_sdk_arguments, build_environment, resolve_sdks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_sdk_arguments(parser)
    parser.set_defaults(build_dir=ROOT / ".local/cq-warehouse-check/viewer-build")
    args = resolve_sdks(parser.parse_args())
    executable = args.build_dir / "bin/PromptCadViewerCheck.exe"
    if not executable.is_file():
        parser.error("Build the viewer-check target first; see docs/standard-parts.md.")
    output = ROOT / ".local/cq-warehouse-check" / ("viewer-" + uuid4().hex[:8])
    output.mkdir(parents=True)
    env = build_environment(args.qt_prefix, args.occt_prefix, compiler=False)
    env["PROMPTCAD_HOME"] = str(output / "app-data")
    workspace = Workspace(output / "workers")
    cases = [
        ("bearing", "bearing.SingleRowDeepGrooveBallBearing", {"size": "M8-22-7", "bearing_type": "SKT"}),
        ("chain", "chain.Chain", {"spkt_teeth": [16, 16], "spkt_locations": [[-76.2, 40], [76.2, 40]], "positive_chain_wrap": [True, True]}),
    ]
    reports = []
    try:
        for family, identity, parameters in cases:
            folder = output / family
            folder.mkdir()
            snapshot = workspace.geometry("standard_part", {"project_dir": str(folder),
                "snapshot": {"components": [], "assembly_nodes": []},
                "request": {"generator_id": identity, "parameters": parameters}})
            snapshot.update(project_dir=str(folder), document_id="synthetic-" + family, revision_id="synthetic")
            fixture = folder / "snapshot.json"
            fixture.write_text(json.dumps(snapshot), encoding="utf-8")
            result = subprocess.run([str(executable), str(fixture), str(folder / "viewport.png")],
                cwd=ROOT, env=env, capture_output=True, text=True, timeout=45, check=False)
            (folder / "output.log").write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
            if result.returncode:
                raise RuntimeError(f"{family}: native viewer check failed ({result.returncode}). See {folder / 'output.log'}")
            reports.append({"family": family, "passed": True, "component_count": 1,
                "solid_count": snapshot["components"][0]["metrics"]["solid_count"]})
            print(family + ": native rendering, face selection and component selection passed", flush=True)
    finally:
        workspace.worker.close()
    (output / "report.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

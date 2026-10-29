"""Exercise the real Windows viewport at multiple sizes/scales; no agent inference."""

import json
import os
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import trimesh

from backend.native.documents import write_json
from backend.v2.workspace import WorkspaceV2
from tools.build_native import ROOT, build_environment


def main():
    output = ROOT / "artifacts/validation"
    output.mkdir(parents=True, exist_ok=True)
    fixtures = ROOT / "tmp" / ("ui-fixture-" + uuid4().hex[:8])
    fixtures.mkdir()
    scene = trimesh.Scene()
    sphere = trimesh.creation.icosphere(subdivisions=2, radius=10)
    sphere.visual.vertex_colors = [80, 160, 210, 255]
    scene.add_geometry(sphere, node_name="Visual sphere")
    box = trimesh.creation.box([8, 8, 25])
    box.apply_translation([28, 0, 0])
    box.visual.vertex_colors = [210, 150, 70, 255]
    scene.add_geometry(box, node_name="Separate mesh component")
    source = fixtures / "mesh.glb"
    scene.export(source)
    workspace = WorkspaceV2(fixtures / "data")
    try:
        workspace.dispatch("v2.project.create", {"name": "Mesh viewport validation"})
        document = workspace.dispatch(
            "v2.import", {"path": str(source), "mm_per_unit": 1}
        )["document"]
        mesh_path = document["project_dir"]
    finally:
        workspace.worker.close()
    qt = Path(
        os.getenv("CAD_QT_PREFIX", str(Path.home() / "anaconda3/envs/occenv/Library"))
    )
    occt = Path(
        os.getenv("CAD_OCCT_PREFIX", str(ROOT / ".native-runtime/occt/Library"))
    )
    base = build_environment(qt, occt)
    cases = [
        (
            "laptop-solid",
            "1280x800",
            "1",
            str(ROOT / "examples/spindle-assembly.cad.json"),
        ),
        ("scaled-mesh", "1100x700", "1.5", mesh_path),
        (
            "large-solid",
            "1600x950",
            "1",
            str(ROOT / "examples/spindle-assembly.cad.json"),
        ),
    ]
    reports = []
    for name, size, scale, model in cases:
        env = {
            **base,
            "QT_SCALE_FACTOR": scale,
            "PROMPTCAD_HOME": str(fixtures / name),
            "CAD_UI_LOG": str(ROOT / "tmp" / (name + ".log")),
        }
        command = [
            str(ROOT / ".native-build/bin/PromptToCAD.exe"),
            "--workspace",
            str(ROOT),
            "--smoke-test",
            "--smoke-size",
            size,
            "--open",
            model,
        ]
        result = subprocess.run(
            command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=180
        )
        if result.returncode:
            raise RuntimeError(
                name
                + " (exit "
                + str(result.returncode)
                + "): "
                + result.stderr[-3000:]
            )
        report = json.loads((ROOT / "tmp/native-smoke-report.json").read_text())
        if not report["passed"] or min(report.get("viewport_size", [0, 0])) < 300:
            raise RuntimeError("Viewport acceptance failed: " + name)
        report.update(
            case=name,
            requested_size=size,
            requested_scale=scale,
            real_viewport=True,
            mocked=False,
        )
        shutil.copyfile(ROOT / "tmp/native-workspace.png", output / (name + ".png"))
        if name == "laptop-solid":
            shutil.copyfile(ROOT / "tmp/native-settings.png", output / "settings.png")
        reports.append(report)
        print(name + ": passed", flush=True)
    write_json(
        output / "ui.json", {"passed": True, "cases": reports, "agent_inference": False}
    )
    shutil.copyfile(
        output / "large-solid.png", ROOT / "docs/assets/workspace.png"
    )


if __name__ == "__main__":
    main()

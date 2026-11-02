"""Exercise the real Windows viewport at multiple sizes/scales; no agent inference."""

import json
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import trimesh

from backend.native.documents import write_json
from backend.v2.workspace import WorkspaceV2
from backend.v2.projects import Projects
from tools.build_native import ROOT, build_environment, add_sdk_arguments, resolve_sdks
from tools.fixtures import write_assembly


def main():
    parser = argparse.ArgumentParser()
    add_sdk_arguments(parser)
    parser.add_argument("--launcher", action="store_true", help="Exercise Run-PromptToCAD.cmd from outside the checkout.")
    parser.add_argument(
        "--case", choices=("laptop-solid", "scaled-mesh", "large-solid")
    )
    args = parser.parse_args()
    resolve_sdks(args)
    output = ROOT / "artifacts/validation"
    output.mkdir(parents=True, exist_ok=True)
    fixtures = ROOT / "tmp" / ("ui-fixture-" + uuid4().hex[:8])
    fixtures.mkdir()
    solid_path = str(write_assembly(fixtures))
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
    base = build_environment(args.qt_prefix, args.occt_prefix, args.toolchain_env, compiler=False)
    cases = [
        (
            "laptop-solid",
            "1280x800",
            "1",
            solid_path,
            "dark",
        ),
        ("scaled-mesh", "1100x700", "1.5", mesh_path, "light"),
        (
            "large-solid",
            "1600x950",
            "1",
            solid_path,
            "light",
        ),
    ]
    if args.case:
        cases = [case for case in cases if case[0] == args.case]
    reports = []
    for name, size, scale, model, theme in cases:
        case_home = fixtures / name
        collection = Projects(case_home / "projects")
        missing = collection.create("Unavailable fixture")
        collection.project_path(missing["project_id"]).rename(
            fixtures / (name + "-moved-project")
        )
        env = {
            **base,
            "QT_SCALE_FACTOR": scale,
            "CAD_UI_THEME": theme,
            "CAD_UI_MISSING_PROJECT_FIXTURE": "1",
            "PROMPTCAD_HOME": str(fixtures / name),
            "CAD_UI_LOG": str(ROOT / "tmp" / (name + ".log")),
        }
        application_args = [
            "--smoke-test",
            "--smoke-size",
            size,
            "--open",
            model,
        ]
        command = [str(args.build_dir / "bin/PromptToCAD.exe"), "--workspace", str(ROOT),
                   "--python", sys.executable, *application_args]
        launch_options = {"cwd": ROOT}
        if args.launcher:
            processor = os.environ.get("COMSPEC", "C:/Windows/System32/cmd.exe")
            arguments = [str(ROOT / "Run-PromptToCAD.cmd"), "--qt-prefix", str(args.qt_prefix),
                         "--occt-prefix", str(args.occt_prefix), "--build-dir", str(args.build_dir),
                         "--", *application_args]
            command = f'"{processor}" /d /s /c "call {subprocess.list2cmdline(arguments)}"'
            launch_options = {"cwd": fixtures, "executable": processor}
            env["CI"] = "true"
        result = subprocess.run(
            command, **launch_options, env=env, capture_output=True, text=True, timeout=180
        )
        if result.returncode:
            ui_log = Path(env["CAD_UI_LOG"])
            diagnostics = ui_log.read_text(encoding="utf-8", errors="replace")[-6000:] if ui_log.is_file() else "No native UI log was written."
            raise RuntimeError(
                name
                + " (exit "
                + str(result.returncode)
                + "): "
                + result.stderr[-3000:]
                + "\n" + diagnostics
            )
        report = json.loads((ROOT / "tmp/native-smoke-report.json").read_text())
        if not report["passed"] or min(report.get("viewport_size", [0, 0])) < 300:
            raise RuntimeError("Viewport acceptance failed: " + name)
        if (
            report.get("theme") != theme
            or not report.get("named_project_folder")
            or not report.get("startup_logo_captured")
        ):
            raise RuntimeError(
                "Theme, named storage or startup validation failed: " + name
            )
        report.update(
            case=name,
            requested_size=size,
            requested_scale=scale,
            real_viewport=True,
            geometry_mocked=False,
            provider_activity_and_usage_are_fixtures=True,
        )
        shutil.copyfile(ROOT / "tmp/native-workspace.png", output / (name + ".png"))
        for capture in (
            "settings",
            "onboarding",
            "notification",
            "account-details",
            "library",
            "model-picker",
            "usage",
            "appearance",
            "startup",
            "agent-working",
            "agent-completed",
        ):
            path = ROOT / ("tmp/native-" + capture + ".png")
            if path.exists():
                shutil.copyfile(path, output / (name + "-" + capture + ".png"))
        reports.append(report)
        print(name + ": passed", flush=True)
    write_json(
        output / "ui.json", {"passed": True, "cases": reports, "agent_inference": False}
    )


if __name__ == "__main__":
    main()

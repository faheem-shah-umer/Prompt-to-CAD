"""Relocate a staged package and test offline operations with no SDK on PATH."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile
from tools.fixtures import write_assembly
from tools.build_native import ROOT


def isolated_environment(folder):
    keep = {"SystemRoot", "WINDIR", "TEMP", "TMP", "COMSPEC", "LOCALAPPDATA", "APPDATA", "USERPROFILE", "PROCESSOR_ARCHITECTURE"}
    env = {name: value for name, value in os.environ.items() if name in keep}
    env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
    env.update(PROMPTCAD_HOME=str(folder / "state"), PROMPTCAD_PROJECTS_DIR=str(folder / "projects"),
        PROMPTCAD_IDENTITY_HOME=str(folder / "identity"), CAD_CHECK_OUTPUT=str(folder / "capture"),
        CAD_UI_LOG=str(folder / "ui.log"), PYTHONNOUSERSITE="1")
    return env


def check_package(bundle):
    # A short, separate path avoids MAX_PATH failures in legacy Windows copy APIs.
    output = Path(tempfile.mkdtemp(prefix="pc-check-", dir=ROOT.parent))
    relocated = output / "App with spaces"
    archive_extracted = bundle.is_file()
    if archive_extracted:
        from tools.verify_archive import verify
        verify(bundle)
        with zipfile.ZipFile(bundle) as archive:
            prefix = archive.namelist()[0].split('/')[0]
            archive.extractall(output)
        (output / prefix).rename(relocated)
    else:
        shutil.copytree(bundle, relocated)
    fixture = write_assembly(output / "synthetic-input")
    env = isolated_environment(output)
    env["CAD_SYNTHETIC_INPUT"] = str(fixture)
    program = """
import json, os, pathlib, sys
import cadquery, jwt, PIL, httpx, scipy, trimesh, pydantic
from backend.v2.workspace import WorkspaceV2
root = pathlib.Path(sys.executable).resolve().parent.parent
assert all('site-packages' not in p or pathlib.Path(p).resolve().is_relative_to(root) for p in sys.path)
w = WorkspaceV2(os.environ['PROMPTCAD_HOME'])
try:
    w.dispatch('v2.project.create', {'name': 'Synthetic portable check'})
    d = w.dispatch('v2.import', {'path': os.environ['CAD_SYNTHETIC_INPUT']})['document']
    assert len(d['components']) == 3
    w.dispatch('v2.export', {'path': str(pathlib.Path(os.environ['PROMPTCAD_HOME']) / 'roundtrip.step'), 'base_revision_id': d['revision_id']})
finally:
    w.worker.close()
print('Bundled Python imports and offline CAD import/export passed')
"""
    subprocess.run([str(relocated / "python/python.exe"), "-B", "-c", program],
        cwd=output, env=env, check=True, timeout=240)
    subprocess.run([str(relocated / "bin/PromptToCAD.exe"), "--portable-smoke", "--open", str(fixture)],
        cwd=output, env=env, check=True, timeout=180)
    report = json.loads((output / "capture/distribution-smoke.json").read_text())
    if not report.get("passed"):
        raise RuntimeError("Native portable smoke check failed.")
    hosted_windows = os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("RUNNER_OS") == "Windows"
    report.update(relocated=True, path_with_spaces=True, sdk_on_path=False,
                  archive_extracted=archive_extracted, clean_windows_runner=hosted_windows)
    target = ROOT / "artifacts/release-checks"
    target.mkdir(parents=True, exist_ok=True)
    (target / "portable-smoke.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    check_package(args.directory.resolve())


if __name__ == "__main__":
    main()

import argparse
import importlib.metadata as metadata
import json
import os
import platform
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

from packaging.requirements import Requirement
from tools.build_native import ROOT, build_environment


def dependency_closure():
    pending = ["cadquery", "fastapi", "pydantic", "uvicorn", "httpx", "python-dotenv"]
    distributions = {}
    while pending:
        distribution = metadata.distribution(pending.pop())
        name = distribution.metadata["Name"].lower().replace("_", "-")
        if name in distributions:
            continue
        distributions[name] = distribution
        for specification in distribution.requires or []:
            requirement = Requirement(specification)
            if requirement.marker is None or requirement.marker.evaluate({"extra": ""}):
                pending.append(requirement.name)
    return distributions


def copy_python(destination):
    base = Path(sys.base_prefix)
    destination.mkdir(parents=True)
    for source in base.iterdir():
        if source.is_file() and (source.suffix.lower() == ".dll" or source.name in ("python.exe", "pythonw.exe", "LICENSE.txt")):
            shutil.copy2(source, destination / source.name)
    shutil.copytree(base / "DLLs", destination / "DLLs",
                    ignore=shutil.ignore_patterns("*.pdb", "*_test*", "_tkinter.pyd"))
    with zipfile.ZipFile(destination / "python311.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for source in (base / "Lib").rglob("*"):
            relative = source.relative_to(base / "Lib")
            if any(part in ("site-packages", "__pycache__", "test", "tests", "idlelib", "tkinter", "ensurepip", "venv") for part in relative.parts):
                continue
            if source.is_file() and source.suffix != ".pyc":
                archive.write(source, relative.as_posix())
    site = destination / "Lib/site-packages"
    site.mkdir(parents=True)
    packages = dependency_closure()
    for distribution in packages.values():
        package_root = Path(distribution.locate_file("")).resolve()
        for relative in distribution.files or []:
            source = Path(distribution.locate_file(relative)).resolve()
            if not source.is_file() or not source.is_relative_to(package_root) or "__pycache__" in source.parts:
                continue
            target = site / source.relative_to(package_root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    (destination / "python311._pth").write_text("python311.zip\nDLLs\nLib/site-packages\n.\n../app\nimport site\n")
    return {name: distribution.version for name, distribution in sorted(packages.items())}


def copy_native(destination, qt, occt, env):
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / ".native-build/PromptToCAD.exe", destination)
    plugins = destination / "plugins/platforms"
    plugins.mkdir(parents=True, exist_ok=True)
    shutil.copy2(qt / "lib/qt6/plugins/platforms/qwindows.dll", plugins)
    (destination / "qt.conf").write_text("[Paths]\nPrefix=.\nPlugins=plugins\n")
    dumpbin = shutil.which("dumpbin", path=env["PATH"])
    if not dumpbin:
        raise RuntimeError("dumpbin is needed to collect the native runtime dependencies.")
    search = [occt / "bin", qt / "bin", Path(sys.base_prefix), Path(sys.base_prefix) / "DLLs",
              Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32"]
    pending = [destination / "PromptToCAD.exe", plugins / "qwindows.dll"]
    copied = set()
    while pending:
        source = pending.pop()
        output = subprocess.run([dumpbin, "/DEPENDENTS", str(source)], env=env, check=True,
                                capture_output=True, text=True).stdout
        for name in re.findall(r"^\s+([A-Za-z0-9_.+-]+\.dll)\s*$", output, re.MULTILINE | re.IGNORECASE):
            if name.lower() in copied or name.lower().startswith(("api-ms-", "ext-ms-")):
                continue
            copied.add(name.lower())
            candidates = [folder / name for folder in search if (folder / name).is_file()]
            if not candidates:
                raise RuntimeError(f"Missing native dependency: {name}")
            dependency = candidates[0]
            if dependency.parent == search[-1]:
                continue
            target = destination / dependency.name
            shutil.copy2(dependency, target)
            pending.append(target)
    resources = occt / "share/opencascade/resources"
    if resources.exists():
        shutil.copytree(resources, destination / "resources", dirs_exist_ok=True)


def copy_sources(destination):
    app = destination / "app"
    for module in ("app", "native"):
        shutil.copytree(ROOT / "backend" / module, app / "backend" / module, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(ROOT / "backend/__init__.py", app / "backend/__init__.py")
    shutil.copy2(ROOT / "backend/.env.example", app / "backend/.env.example")
    shutil.copytree(ROOT / "examples", app / "examples", dirs_exist_ok=True)
    (app / "tmp").mkdir(exist_ok=True)
    shutil.copy2(ROOT / "docs/native-workspace.md", destination / "README.md")
    source = destination / "source"
    shutil.copytree(ROOT / "native", source / "native", dirs_exist_ok=True)
    shutil.copytree(ROOT / "tools", source / "tools", dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(ROOT / "backend", source / "backend", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns(".env", "__pycache__", "*.pyc"))
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(ROOT / name, destination / name)


def nsis_string(text):
    return str(text).replace("$", "$$").replace('"', '$\\"')


def installer(bundle, compiler, output):
    files = sorted(path for path in bundle.rglob("*") if path.is_file())
    directories = sorted((path for path in bundle.rglob("*") if path.is_dir()), key=lambda path: len(path.parts), reverse=True)
    script = [
        "Unicode true", "RequestExecutionLevel user", "SetCompressor zlib",
        'Name "Prompt to CAD Native"', f'OutFile "{nsis_string(output)}"',
        'InstallDir "$LOCALAPPDATA\\Programs\\PromptToCADNative"',
        "Page directory", "Page instfiles", "UninstPage uninstConfirm", "UninstPage instfiles",
        'Section "Application"', 'SetOutPath "$INSTDIR"', f'File /r "{nsis_string(bundle)}\\*"',
        'WriteUninstaller "$INSTDIR\\Uninstall.exe"',
        'CreateShortcut "$SMPROGRAMS\\Prompt to CAD Native.lnk" "$INSTDIR\\bin\\PromptToCAD.exe"',
        'WriteRegStr HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\PromptToCADNative" "DisplayName" "Prompt to CAD Native"',
        'WriteRegStr HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\PromptToCADNative" "DisplayVersion" "0.2.0"',
        'WriteRegStr HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\PromptToCADNative" "UninstallString" \'"$INSTDIR\\Uninstall.exe"\'',
        "SectionEnd", 'Section "Uninstall"'
    ]
    # Delete the installed inventory only; user-added files and local project data survive uninstall.
    script += [f'Delete "$INSTDIR\\{nsis_string(path.relative_to(bundle))}"' for path in files]
    script += [f'RMDir "$INSTDIR\\{nsis_string(path.relative_to(bundle))}"' for path in directories]
    script += ['Delete "$INSTDIR\\Uninstall.exe"', 'RMDir "$INSTDIR"',
               'Delete "$SMPROGRAMS\\Prompt to CAD Native.lnk"',
               'DeleteRegKey HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\PromptToCADNative"', "SectionEnd"]
    path = ROOT / "tmp/native-installer.nsi"
    path.write_text("\n".join(script), encoding="utf-8")
    subprocess.run([str(compiler), "/V2", str(path)], check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "dist-native/PromptToCAD-0.2.0")
    parser.add_argument("--qt-prefix", type=Path, default=Path(os.getenv("CAD_QT_PREFIX", str(Path.home() / "anaconda3/envs/occenv/Library"))))
    parser.add_argument("--occt-prefix", type=Path, default=Path(os.getenv("CAD_OCCT_PREFIX", str(ROOT / ".native-runtime/occt/Library"))))
    parser.add_argument("--installer", type=Path, help="Path to makensis.exe")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--refresh", action="store_true", help="Reuse a staged runtime under dist-native and refresh application/source files.")
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 11):
        parser.error("Build this package with the pinned Python 3.11 runtime.")
    bundle = args.output.resolve()
    refreshing = bundle.exists() and args.refresh
    if bundle.exists() and not refreshing:
        parser.error("The package output already exists. Choose a new output directory, or --refresh a staged build.")
    if refreshing and not bundle.is_relative_to((ROOT / "dist-native").resolve()):
        parser.error("Only a staged package under dist-native can be refreshed.")
    bundle.mkdir(parents=True, exist_ok=True)
    env = build_environment(args.qt_prefix, args.occt_prefix)
    if refreshing:
        existing = json.loads((bundle / "runtime-manifest.json").read_text())
        packages = {name: distribution.version for name, distribution in dependency_closure().items()}
        if packages != existing["packages"]:
            parser.error("The dependency set changed. Build a new package directory.")
    else:
        print("Copying isolated Python runtime and modelling dependencies…", flush=True)
        packages = copy_python(bundle / "python")
    copy_native(bundle / "bin", args.qt_prefix, args.occt_prefix, env)
    copy_sources(bundle)
    licences = bundle / "licences"
    licences.mkdir(exist_ok=True)
    for name, location in {"occt": args.occt_prefix / "share/doc/opencascade",
                           "qt": Path.home() / "anaconda3/pkgs/qt6-main-6.9.0-h83cda92_0/info/licenses"}.items():
        if location.exists():
            shutil.copytree(location, licences / name, dirs_exist_ok=True)
    qt_version = subprocess.run([str(args.qt_prefix / "bin/qtpaths6.exe"), "--qt-version"], env=env, check=True, capture_output=True, text=True).stdout.strip()
    (bundle / "runtime-manifest.json").write_text(json.dumps({"version": "0.2.0", "python": platform.python_version(),
        "native": {"qt": qt_version, "occt": "7.8.1"}, "packages": packages}, indent=2))
    if args.smoke_test:
        test_env = {key: value for key, value in os.environ.items() if not key.startswith(("QT_", "PYTHON", "LLM_"))}
        test_env["PATH"] = str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32")
        test_env["CAD_UI_LOG"] = str(ROOT / "tmp/packaged-ui.log")
        command = [str(bundle / "bin/PromptToCAD.exe"), "--smoke-test", "--open", str(bundle / "app/examples/spindle-assembly.cad.json")]
        subprocess.run(command, cwd=bundle, env=test_env, check=True, timeout=180)
        report = json.loads((bundle / "app/tmp/native-smoke-report.json").read_text())
        if not report["passed"]:
            raise RuntimeError("The isolated packaged smoke test failed.")
        shutil.copy2(bundle / "app/tmp/native-workspace.png", ROOT / "tmp/packaged-native-workspace.png")
        shutil.copy2(bundle / "app/tmp/native-smoke-report.json", ROOT / "tmp/packaged-smoke-report.json")
        for name in ("native-smoke-report.json", "native-workspace.png", "native-viewport.png"):
            (bundle / "app/tmp" / name).unlink(missing_ok=True)
        print("Packaged application passed with only Windows System32 on PATH.", flush=True)
    if args.installer:
        installer(bundle, args.installer, bundle.parent / "PromptToCAD-Native-0.2.0-Setup.exe")
    print(bundle, flush=True)


if __name__ == "__main__":
    main()

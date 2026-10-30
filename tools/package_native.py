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
from tools.fixtures import write_assembly
from tools.source_policy import is_public_source


def dependency_closure():
    pending = [
        "cadquery",
        "pydantic",
        "httpx",
        "PyJWT",
        "cryptography",
        "trimesh",
        "scipy",
        "Pillow",
    ]
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
        if source.is_file() and (
            source.suffix.lower() == ".dll"
            or source.name in ("python.exe", "pythonw.exe", "LICENSE.txt")
        ):
            shutil.copy2(source, destination / source.name)
    shutil.copytree(
        base / "DLLs",
        destination / "DLLs",
        ignore=shutil.ignore_patterns("*.pdb", "*_test*", "_tkinter.pyd"),
    )
    with zipfile.ZipFile(
        destination / "python311.zip", "w", zipfile.ZIP_DEFLATED
    ) as archive:
        for source in (base / "Lib").rglob("*"):
            relative = source.relative_to(base / "Lib")
            if any(
                part
                in (
                    "site-packages",
                    "__pycache__",
                    "test",
                    "tests",
                    "idlelib",
                    "tkinter",
                    "ensurepip",
                    "venv",
                )
                for part in relative.parts
            ):
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
            if (
                not source.is_file()
                or not source.is_relative_to(package_root)
                or "__pycache__" in source.parts
            ):
                continue
            target = site / source.relative_to(package_root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    (destination / "python311._pth").write_text(
        "python311.zip\nDLLs\nLib/site-packages\n.\n../app\nimport site\n"
    )
    return {
        name: distribution.version for name, distribution in sorted(packages.items())
    }


def copy_native(destination, qt, occt, env):
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / ".native-build/bin/PromptToCAD.exe", destination)
    plugins = destination / "plugins/platforms"
    plugins.mkdir(parents=True, exist_ok=True)
    shutil.copy2(qt / "lib/qt6/plugins/platforms/qwindows.dll", plugins)
    (destination / "qt.conf").write_text("[Paths]\nPrefix=.\nPlugins=plugins\n")
    dumpbin = shutil.which("dumpbin", path=env["PATH"])
    if not dumpbin:
        raise RuntimeError(
            "dumpbin is needed to collect the native runtime dependencies."
        )
    search = [
        occt / "bin",
        qt / "bin",
        Path(sys.base_prefix),
        Path(sys.base_prefix) / "DLLs",
        Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32",
    ]
    pending = [destination / "PromptToCAD.exe", plugins / "qwindows.dll"]
    copied = set()
    while pending:
        source = pending.pop()
        output = subprocess.run(
            [dumpbin, "/DEPENDENTS", str(source)],
            env=env,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        for name in re.findall(
            r"^\s+([A-Za-z0-9_.+-]+\.dll)\s*$", output, re.MULTILINE | re.IGNORECASE
        ):
            if name.lower() in copied or name.lower().startswith(
                ("api-ms-", "ext-ms-")
            ):
                continue
            copied.add(name.lower())
            candidates = [
                folder / name for folder in search if (folder / name).is_file()
            ]
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
    tracked = None
    if (ROOT / ".git").exists():
        tracked = set(
            subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
            .decode()
            .split("\0")
        )

    def copy_public(folder, target):
        for path in (ROOT / folder).rglob("*"):
            relative = path.relative_to(ROOT).as_posix()
            if (
                not path.is_file()
                or not is_public_source(relative)
                or (tracked is not None and relative not in tracked)
            ):
                continue
            output = target / path.relative_to(ROOT / folder)
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, output)

    for module in ("native", "v2"):
        copy_public("backend/" + module, app / "backend" / module)
    shutil.copy2(ROOT / "backend/__init__.py", app / "backend/__init__.py")
    (app / "tmp").mkdir(exist_ok=True)
    copy_public("docs", destination / "docs")
    (destination / "README.md").write_text(
        '# Prompt to CAD\n\n<img src="assets/app-icon.svg" alt="Prompt to CAD logo" width="80">\n\nRun bin/PromptToCAD.exe. Python, Qt and the CAD engine are included. Install Codex separately and connect your own eligible ChatGPT plan from Settings → AI connection. No credentials or model weights are included.\n\nSee [setup and capabilities](docs/setup.md), THIRD_PARTY_NOTICES.md, licences/, and source/ for buildable application source. This build is unsigned.\n',
        encoding="utf-8",
    )
    source = destination / "source"
    copy_public("assets", destination / "assets")
    for folder in ("assets", "native", "tools", "backend"):
        copy_public(folder, source / folder)
    for name in ("requirements.txt", "requirements-dev.txt"):
        shutil.copy2(ROOT / name, source / name)
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(ROOT / name, destination / name)


def nsis_string(text):
    return str(text).replace("$", "$$").replace('"', '$\\"')


def distribution_files(bundle):
    files = []
    for folder in ("bin", "python", "licences", "source", "app", "docs", "assets"):
        for path in (bundle / folder).rglob("*"):
            if not path.is_file():
                continue
            if not path.resolve().is_relative_to(bundle.resolve()):
                raise RuntimeError("A distribution file leaves its bundle directory.")
            relative = path.relative_to(bundle / folder).as_posix()
            if folder == "source" and not is_public_source(relative):
                continue
            if folder == "app" and not (
                relative.startswith("backend/") and is_public_source(relative)
            ):
                continue
            if folder in ("docs", "assets") and not is_public_source(
                folder + "/" + relative
            ):
                continue
            if path.suffix == ".dpapi" or path.name in (
                "auth.json",
                ".env",
                "credentials.json",
            ):
                raise RuntimeError("Credential material cannot be packaged.")
            files.append(path)
    files += [
        bundle / name
        for name in (
            "LICENSE",
            "README.md",
            "THIRD_PARTY_NOTICES.md",
            "runtime-manifest.json",
        )
        if (bundle / name).is_file()
    ]
    return sorted(files)


def installer(bundle, compiler, output):
    files = distribution_files(bundle)
    directories = sorted(
        {
            parent
            for path in files
            for parent in path.parents
            if parent != bundle and parent.is_relative_to(bundle)
        },
        key=lambda path: len(path.parts),
        reverse=True,
    )
    script = [
        "Unicode true",
        "RequestExecutionLevel user",
        "SetCompressor zlib",
        'Name "Prompt to CAD"',
        f'Icon "{nsis_string(bundle / "assets/app-icon.ico")}"',
        f'UninstallIcon "{nsis_string(bundle / "assets/app-icon.ico")}"',
        f'OutFile "{nsis_string(output)}"',
        'InstallDir "$LOCALAPPDATA\\Programs\\PromptToCADV2"',
        "Page directory",
        "Page instfiles",
        "UninstPage uninstConfirm",
        "UninstPage instfiles",
        'Section "Application"',
    ]
    previous = None
    for path in files:
        folder = path.parent.relative_to(bundle)
        if folder != previous:
            location = (
                "$INSTDIR"
                if folder == Path(".")
                else "$INSTDIR\\" + nsis_string(folder)
            )
            script.append(f'SetOutPath "{location}"')
            previous = folder
        script.append(f'File "{nsis_string(path)}"')
    script += [
        'SetOutPath "$INSTDIR"',
        'WriteUninstaller "$INSTDIR\\Uninstall.exe"',
        'CreateShortcut "$SMPROGRAMS\\Prompt to CAD.lnk" "$INSTDIR\\bin\\PromptToCAD.exe" "" "$INSTDIR\\bin\\PromptToCAD.exe" 0',
        'WriteRegStr HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\PromptToCADV2" "DisplayName" "Prompt to CAD"',
        'WriteRegStr HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\PromptToCADV2" "DisplayVersion" "0.4.0"',
        'WriteRegStr HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\PromptToCADV2" "DisplayIcon" \'"$INSTDIR\\bin\\PromptToCAD.exe",0\'',
        'WriteRegStr HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\PromptToCADV2" "UninstallString" \'"$INSTDIR\\Uninstall.exe"\'',
        "SectionEnd",
        'Section "Uninstall"',
    ]
    # Delete the installed inventory only; user-added files and local project data survive uninstall.
    script += [
        f'Delete "$INSTDIR\\{nsis_string(path.relative_to(bundle))}"' for path in files
    ]
    script += [
        f'RMDir "$INSTDIR\\{nsis_string(path.relative_to(bundle))}"'
        for path in directories
    ]
    script += [
        'Delete "$INSTDIR\\Uninstall.exe"',
        'RMDir "$INSTDIR"',
        'Delete "$SMPROGRAMS\\Prompt to CAD.lnk"',
        'DeleteRegKey HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\PromptToCADV2"',
        "SectionEnd",
    ]
    path = ROOT / "tmp/native-installer.nsi"
    path.write_text("\n".join(script), encoding="utf-8")
    subprocess.run([str(compiler), "/V2", str(path)], check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path, default=ROOT / "dist-native/PromptToCAD-0.4.0"
    )
    parser.add_argument(
        "--qt-prefix",
        type=Path,
        default=Path(
            os.getenv(
                "CAD_QT_PREFIX", str(Path.home() / "anaconda3/envs/occenv/Library")
            )
        ),
    )
    parser.add_argument(
        "--occt-prefix",
        type=Path,
        default=Path(
            os.getenv("CAD_OCCT_PREFIX", str(ROOT / ".native-runtime/occt/Library"))
        ),
    )
    parser.add_argument("--installer", type=Path, help="Path to makensis.exe")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Reuse a staged runtime under dist-native and refresh application/source files.",
    )
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 11):
        parser.error("Build this package with the pinned Python 3.11 runtime.")
    bundle = args.output.resolve()
    refreshing = bundle.exists() and args.refresh
    if bundle.exists() and not refreshing:
        parser.error(
            "The package output already exists. Choose a new output directory, or --refresh a staged build."
        )
    if refreshing and not bundle.is_relative_to((ROOT / "dist-native").resolve()):
        parser.error("Only a staged package under dist-native can be refreshed.")
    if refreshing and any(
        path.is_file()
        for folder in (
            bundle / "Projects",
            bundle / ".promptcad",
            bundle / "app/Projects",
            bundle / "app/.promptcad",
        )
        for path in folder.rglob("*")
    ):
        parser.error(
            "This output contains local project or account data. Choose a fresh output directory; user data was not changed."
        )
    bundle.mkdir(parents=True, exist_ok=True)
    env = build_environment(args.qt_prefix, args.occt_prefix)
    if refreshing:
        existing = json.loads((bundle / "runtime-manifest.json").read_text())
        packages = {
            name: distribution.version
            for name, distribution in dependency_closure().items()
        }
        if packages != existing["packages"]:
            parser.error("The dependency set changed. Build a new package directory.")
    else:
        print("Copying isolated Python runtime and modelling dependencies…", flush=True)
        packages = copy_python(bundle / "python")
    copy_native(bundle / "bin", args.qt_prefix, args.occt_prefix, env)
    copy_sources(bundle)
    licences = bundle / "licences"
    licences.mkdir(exist_ok=True)
    for name, location in {
        "occt": args.occt_prefix / "share/doc/opencascade",
        "qt": Path.home() / "anaconda3/pkgs/qt6-main-6.9.0-h83cda92_0/info/licenses",
    }.items():
        if location.exists():
            shutil.copytree(location, licences / name, dirs_exist_ok=True)
    qt_version = subprocess.run(
        [str(args.qt_prefix / "bin/qtpaths6.exe"), "--qt-version"],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    (bundle / "runtime-manifest.json").write_text(
        json.dumps(
            {
                "version": "0.4.0",
                "python": platform.python_version(),
                "native": {"qt": qt_version, "occt": "7.8.1"},
                "packages": packages,
            },
            indent=2,
        )
    )
    if args.smoke_test:
        test_env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(
                (
                    "QT_",
                    "PYTHON",
                    "LLM_",
                    "OPENAI_",
                    "CODEX_",
                    "ANTHROPIC_",
                    "PROMPTCAD_",
                )
            )
        }
        test_env["PATH"] = str(
            Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32"
        )
        test_env["PROMPTCAD_HOME"] = str(ROOT / "tmp/packaged-v2-state")
        test_env["CAD_UI_LOG"] = str(ROOT / "tmp/packaged-ui.log")
        command = [
            str(bundle / "bin/PromptToCAD.exe"),
            "--smoke-test",
            "--open",
            str(write_assembly(ROOT / "tmp/packaged-fixture")),
        ]
        runtime_check = "import jwt, trimesh, scipy; from cryptography.hazmat.primitives.asymmetric import rsa; key=rsa.generate_private_key(public_exponent=65537,key_size=2048); token=jwt.encode({'sub':'package-test'},key,algorithm='RS256'); assert jwt.decode(token,key.public_key(),algorithms=['RS256'])['sub']=='package-test'; assert trimesh.Scene(trimesh.creation.box()).export(file_type='glb')[:4]==b'glTF'; print('V2 packaged authentication and mesh dependencies passed')"
        subprocess.run(
            [str(bundle / "python/python.exe"), "-B", "-c", runtime_check],
            cwd=bundle / "app",
            env=test_env,
            check=True,
            timeout=60,
        )
        subprocess.run(command, cwd=bundle, env=test_env, check=True, timeout=180)
        report = json.loads((bundle / "app/tmp/native-smoke-report.json").read_text())
        if not report["passed"]:
            raise RuntimeError("The isolated packaged smoke test failed.")
        shutil.copy2(
            bundle / "app/tmp/native-workspace.png",
            ROOT / "tmp/packaged-native-workspace.png",
        )
        shutil.copy2(
            bundle / "app/tmp/native-smoke-report.json",
            ROOT / "tmp/packaged-smoke-report.json",
        )
        for path in bundle.rglob("*"):
            if path.is_file() and (
                path.suffix == ".dpapi" or path.name in ("auth.json", ".env")
            ):
                raise RuntimeError(
                    "Credential material must not be present in a distribution: "
                    + str(path.relative_to(bundle))
                )
        for name in (
            "native-smoke-report.json",
            "native-workspace.png",
            "native-viewport.png",
            "native-settings.png",
            "native-startup.png",
            "native-appearance.png",
            "native-agent-working.png",
            "native-agent-completed.png",
        ):
            (bundle / "app/tmp" / name).unlink(missing_ok=True)
        print(
            "Packaged application passed with only Windows System32 on PATH.",
            flush=True,
        )
    if args.installer:
        installer(
            bundle, args.installer, bundle.parent / "PromptToCAD-0.4.0-Setup.exe"
        )
    print(bundle, flush=True)


if __name__ == "__main__":
    main()

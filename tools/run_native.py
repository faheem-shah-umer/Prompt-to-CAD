"""Launch the developer build without machine-specific paths."""
import argparse
from importlib import metadata
import subprocess
import sys
import sysconfig
from tools.build_native import ROOT, add_sdk_arguments, resolve_sdks, build_environment


INSTALL = r".venv\Scripts\python.exe -m pip install -r requirements-dev.txt"


def check_python():
    if sysconfig.get_platform() != "win-amd64" or sys.maxsize < 2**32:
        raise RuntimeError("Use Windows x64 and CPython 3.11 x64. See docs/setup.md.")
    if sys.version_info[:2] != (3, 11):
        raise RuntimeError("Use CPython 3.11 x64. Recreate .venv with py -3.11 -m venv .venv, then run " + INSTALL)


def check_dependencies():
    try:
        from packaging.requirements import Requirement
    except ImportError as error:
        raise RuntimeError("Python dependencies are missing. Run " + INSTALL) from error
    missing = []
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        requirement = Requirement(line)
        if requirement.marker and not requirement.marker.evaluate():
            continue
        try:
            version = metadata.version(requirement.name)
        except metadata.PackageNotFoundError:
            missing.append(requirement.name)
            continue
        if version not in requirement.specifier:
            missing.append(f"{requirement.name}{requirement.specifier} (installed: {version})")
    if missing:
        raise RuntimeError("Missing or incompatible Python dependencies: " + ", ".join(missing) + ". Run " + INSTALL)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_sdk_arguments(parser)
    parser.add_argument("application_args", nargs=argparse.REMAINDER, help="Native application arguments following --.")
    args = parser.parse_args()
    check_python()
    check_dependencies()
    resolve_sdks(args)
    executable = args.build_dir / "bin/PromptToCAD.exe"
    if not executable.is_file():
        raise RuntimeError(f"Application missing: {executable}. Build first: .venv\\Scripts\\python.exe -m tools.build_native --build-dir \"{args.build_dir}\"")
    application_args = args.application_args
    if application_args[:1] == ["--"]:
        application_args = application_args[1:]
    subprocess.run([str(executable), "--workspace", str(ROOT), "--python", sys.executable, *application_args], cwd=ROOT,
                   env=build_environment(args.qt_prefix, args.occt_prefix, args.toolchain_env, compiler=False), check=True)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        if sys.stderr is None:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, str(error), 'Prompt to CAD could not start', 0x10)
        else:
            print(str(error), file=sys.stderr)
        raise SystemExit(error.returncode if isinstance(error, subprocess.CalledProcessError) else 1)

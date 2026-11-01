"""Build the Windows application with configured or discovered SDKs."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUILD = ROOT / "build"


def sdk_prefix(value, variable):
    candidate = value or os.getenv(variable) or os.getenv("CAD_SDK_PREFIX")
    if not candidate and os.getenv("CONDA_PREFIX"):
        candidate = Path(os.environ["CONDA_PREFIX"]) / "Library"
    return Path(candidate or ROOT / ".sdk/windows/Library").resolve()


def add_sdk_arguments(parser):
    parser.add_argument("--qt-prefix", type=Path, help="Qt Library prefix; also CAD_QT_PREFIX/CAD_SDK_PREFIX.")
    parser.add_argument("--occt-prefix", type=Path, help="OCCT Library prefix; also CAD_OCCT_PREFIX/CAD_SDK_PREFIX.")
    parser.add_argument("--toolchain-env", type=Path, help="Optional private compiler environment JSON.")
    parser.add_argument("--build-dir", type=Path, default=DEFAULT_BUILD)


def resolve_sdks(args):
    args.qt_prefix = sdk_prefix(args.qt_prefix, "CAD_QT_PREFIX")
    args.occt_prefix = sdk_prefix(args.occt_prefix, "CAD_OCCT_PREFIX")
    args.build_dir = args.build_dir.resolve()
    for name, path in (("Qt", args.qt_prefix / "lib/cmake/Qt6/Qt6Config.cmake"),
                       ("OCCT", args.occt_prefix / "lib/cmake/opencascade/OpenCASCADEConfig.cmake")):
        if not path.is_file():
            raise RuntimeError(f"{name} SDK missing. Run python -m tools.setup_windows --download-sdk or configure its prefix. See docs/setup.md.")
    return args


def build_environment(qt_prefix, occt_prefix, toolchain_env=None):
    env = os.environ.copy()
    if toolchain_env:
        values = json.loads(Path(toolchain_env).read_text(encoding="utf-8"))
        for name in ("PATH", "INCLUDE", "LIB", "LIBPATH"):
            if name in values:
                env[name] = values[name] + (os.pathsep + env.get(name, "") if name == "PATH" else "")
    if os.name == "nt" and not shutil.which("cl", path=env.get("PATH")):
        vswhere = Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Microsoft Visual Studio/Installer/vswhere.exe"
        if not vswhere.is_file():
            raise RuntimeError("Install Visual Studio 2022 Build Tools: Desktop development with C++ and a Windows SDK, or use its x64 developer prompt.")
        installation = subprocess.check_output([str(vswhere), "-latest", "-products", "*", "-requires",
            "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"], text=True).strip()
        setup = Path(installation) / "Common7/Tools/VsDevCmd.bat"
        if not installation or not setup.is_file():
            raise RuntimeError("The Visual Studio C++ x64 workload is missing.")
        result = subprocess.run(["cmd.exe", "/d", "/s", "/c",
            f'""{setup}" -no_logo -arch=x64 -host_arch=x64 >nul && set"'],
            capture_output=True, text=True, check=True)
        for line in result.stdout.splitlines():
            name, separator, value = line.partition("=")
            if separator and name.upper() in ("PATH", "INCLUDE", "LIB", "LIBPATH"):
                env[name.upper()] = value
    env["PATH"] = os.pathsep.join([str(occt_prefix / "bin"), str(qt_prefix / "bin"),
        str(Path(sys.executable).parent), env.get("PATH", "")])
    env["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(qt_prefix / "lib/qt6/plugins/platforms")
    shaders = occt_prefix / "share/opencascade/resources/Shaders"
    if shaders.is_dir():
        env["CSF_ShadersDirectory"] = str(shaders)
    return env


def build(args):
    resolve_sdks(args)
    env = build_environment(args.qt_prefix, args.occt_prefix, args.toolchain_env)
    required = {name: shutil.which(name, path=env["PATH"]) for name in ("cl", "rc", "cmake", "ninja")}
    missing = [name for name, path in required.items() if not path]
    if missing:
        raise RuntimeError("Missing build tools: " + ", ".join(missing) + ". Install requirements-dev.txt and the x64 C++ workload.")
    subprocess.run([required["cmake"], "-S", str(ROOT / "native"), "-B", str(args.build_dir), "-G", "Ninja",
        "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_TRY_COMPILE_CONFIGURATION=Release",
        "-DCMAKE_CXX_COMPILER=" + Path(required["cl"]).as_posix(),
        "-DCMAKE_RC_COMPILER=" + Path(required["rc"]).as_posix(),
        "-DCMAKE_PREFIX_PATH=" + ";".join(map(str, (args.qt_prefix, args.occt_prefix))),
        "-DOpenCASCADE_DIR=" + str(args.occt_prefix / "lib/cmake/opencascade"),
        "-DCMAKE_MAKE_PROGRAM=" + required["ninja"]], env=env, check=True)
    subprocess.run([required["cmake"], "--build", str(args.build_dir), "--parallel", "4"], env=env, check=True)
    if getattr(args, "test", False):
        ctest = shutil.which("ctest", path=env["PATH"])
        if not ctest:
            raise RuntimeError("ctest is missing; install requirements-dev.txt.")
        subprocess.run([ctest, "--test-dir", str(args.build_dir), "--output-on-failure"], env=env, check=True)
    return args.build_dir / "bin/PromptToCAD.exe"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_sdk_arguments(parser)
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args()
    try:
        print(build(args))
    except RuntimeError as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()

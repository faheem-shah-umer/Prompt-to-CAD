import argparse
import os
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def build_environment(qt_prefix, occt_prefix, toolchain_env=None):
    env = os.environ.copy()
    if toolchain_env:
        values = json.loads(toolchain_env.read_text(encoding="utf-8"))
        for name in ("PATH", "INCLUDE", "LIB"):
            if name in values:
                env[name] = values[name] + (os.pathsep + env.get(name, "") if name == "PATH" else "")
    if os.name == "nt" and not shutil.which("cl", path=env.get("PATH")):
        setup = ROOT / ".build-tools/msvc/setup_x64.bat"
        if not setup.exists():
            raise SystemExit("Use an x64 Visual Studio developer prompt or pass --toolchain-env for an isolated compiler. See docs/setup.md.")
        for line in setup.read_text().splitlines():
            if line.lower().startswith("set "):
                name, value = line[4:].split("=", 1)
                name = name.upper()
                value = value.replace("%~dp0", str(setup.parent) + os.sep)
                value = value.replace("%PATH%", env.get("PATH", ""))
                env[name] = value
    env["PATH"] = os.pathsep.join([str(occt_prefix / "bin"), str(qt_prefix / "bin"),
                                    str(ROOT / ".venv/Scripts"), env.get("PATH", "")])
    env["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(qt_prefix / "lib/qt6/plugins/platforms")
    return env


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--qt-prefix", type=Path, default=Path(os.getenv("CAD_QT_PREFIX", str(Path.home() / "anaconda3/envs/occenv/Library"))))
    parser.add_argument("--occt-prefix", type=Path, default=Path(os.getenv("CAD_OCCT_PREFIX", str(ROOT / ".native-runtime/occt/Library"))))
    parser.add_argument("--build-dir", type=Path, default=ROOT.parent / (ROOT.name + "-build"))
    parser.add_argument("--toolchain-env", type=Path, help="Isolated MSVC PATH/INCLUDE/LIB JSON file.")
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args()
    args.qt_prefix = args.qt_prefix.resolve()
    args.occt_prefix = args.occt_prefix.resolve()
    for prefix in (args.qt_prefix, args.occt_prefix):
        if not prefix.is_dir():
            parser.error(f"Native SDK directory not found: {prefix}. See docs/setup.md.")
    env = build_environment(args.qt_prefix, args.occt_prefix, args.toolchain_env)
    cmake = str(ROOT / ".venv/Scripts/cmake.exe") if (ROOT / ".venv/Scripts/cmake.exe").exists() else "cmake"
    build = args.build_dir.resolve()
    subprocess.run([cmake, "-S", str(ROOT / "native"), "-B", str(build), "-G", "Ninja",
                    "-DCMAKE_BUILD_TYPE=Release",
                    "-DCMAKE_TRY_COMPILE_CONFIGURATION=Release",
                    "-DCMAKE_CXX_COMPILER=" + Path(shutil.which("cl", path=env["PATH"]) or "cl").as_posix(),
                    "-DCMAKE_RC_COMPILER=" + Path(shutil.which("rc", path=env["PATH"]) or "rc").as_posix(),
                    "-DCMAKE_PREFIX_PATH=" + ";".join(map(str, (args.qt_prefix, args.occt_prefix))),
                    "-DOpenCASCADE_DIR=" + str(args.occt_prefix / "lib/cmake/opencascade"),
                    "-DCMAKE_MAKE_PROGRAM=" + str(ROOT / ".venv/Scripts/ninja.exe")], env=env, check=True)
    subprocess.run([cmake, "--build", str(build), "--parallel", "4"], env=env, check=True)
    if args.test:
        ctest = str(ROOT / ".venv/Scripts/ctest.exe")
        subprocess.run([ctest, "--test-dir", str(build), "--output-on-failure"], env=env, check=True)


if __name__ == "__main__":
    main()

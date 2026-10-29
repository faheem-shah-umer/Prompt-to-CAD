import argparse
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def create_launcher():
    if os.name != "nt":
        return
    def literal(path):
        return "'" + str(path).replace("'", "''") + "'"
    script = (
        "$shell = New-Object -ComObject WScript.Shell; "
        "$shortcut = $shell.CreateShortcut(" + literal(ROOT / "Prompt to CAD V2.lnk") + "); "
        "$shortcut.TargetPath = " + literal(Path(os.environ["SystemRoot"]) / "System32/wscript.exe") + "; "
        "$shortcut.Arguments = " + literal('"' + str(ROOT / "Prompt to CAD V2.vbs") + '"') + "; "
        "$shortcut.WorkingDirectory = " + literal(ROOT) + "; "
        "$shortcut.IconLocation = " + literal(str(ROOT / "assets/app-icon.ico") + ",0") + "; "
        "$shortcut.Description = 'Prompt to CAD V2'; $shortcut.Save()"
    )
    subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                   check=True, creationflags=subprocess.CREATE_NO_WINDOW)


def build_environment(qt_prefix, occt_prefix):
    env = os.environ.copy()
    if os.name == "nt" and not shutil.which("cl"):
        setup = ROOT / ".build-tools/msvc/setup_x64.bat"
        if not setup.exists():
            raise SystemExit("Use an x64 Visual Studio developer prompt, or install a workspace-local compiler at .build-tools/msvc.")
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
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--launch", action="store_true")
    parser.add_argument("--open")
    args = parser.parse_args()
    for prefix in (args.qt_prefix, args.occt_prefix):
        if not prefix.is_dir():
            parser.error(f"Native SDK directory not found: {prefix}. See docs/setup.md.")
    env = build_environment(args.qt_prefix, args.occt_prefix)
    cmake = str(ROOT / ".venv/Scripts/cmake.exe") if (ROOT / ".venv/Scripts/cmake.exe").exists() else "cmake"
    build = ROOT / ".native-build"
    subprocess.run([cmake, "-S", str(ROOT / "native"), "-B", str(build), "-G", "Ninja",
                    "-DCMAKE_BUILD_TYPE=Release",
                    "-DCMAKE_TRY_COMPILE_CONFIGURATION=Release",
                    "-DCMAKE_CXX_COMPILER=" + Path(shutil.which("cl", path=env["PATH"]) or "cl").as_posix(),
                    "-DCMAKE_RC_COMPILER=" + Path(shutil.which("rc", path=env["PATH"]) or "rc").as_posix(),
                    "-DCMAKE_PREFIX_PATH=" + ";".join(map(str, (args.qt_prefix, args.occt_prefix))),
                    "-DCMAKE_MAKE_PROGRAM=" + str(ROOT / ".venv/Scripts/ninja.exe")], env=env, check=True)
    subprocess.run([cmake, "--build", str(build), "--parallel", "4"], env=env, check=True)
    create_launcher()
    if args.test:
        ctest = str(ROOT / ".venv/Scripts/ctest.exe")
        subprocess.run([ctest, "--test-dir", str(build), "--output-on-failure"], env=env, check=True)
    if args.launch:
        command = [str(build / "bin/PromptToCAD.exe"), "--workspace", str(ROOT)]
        if args.open:
            command += ["--open", args.open]
        subprocess.Popen(command, env=env, cwd=ROOT)


if __name__ == "__main__":
    main()

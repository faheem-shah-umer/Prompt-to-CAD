import argparse
import ctypes
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--open")
    args = parser.parse_args()
    executable = ROOT / ".native-build/PromptToCAD.exe"
    if not executable.exists():
        raise RuntimeError("Build the native app first: .venv\\Scripts\\python.exe tools\\build_native.py")
    qt = Path(os.getenv("CAD_QT_PREFIX", str(Path.home() / "anaconda3/envs/occenv/Library")))
    occt = Path(os.getenv("CAD_OCCT_PREFIX", str(ROOT / ".native-runtime/occt/Library")))
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join([str(occt / "bin"), str(qt / "bin"), env.get("PATH", "")])
    env["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(qt / "lib/qt6/plugins/platforms")
    command = [str(executable), "--workspace", str(ROOT)]
    if args.open:
        command += ["--open", str(Path(args.open).resolve())]
    logs = ROOT / "tmp"
    logs.mkdir(exist_ok=True)
    with (logs / "native-launch.log").open("ab") as stream:
        subprocess.Popen(command, cwd=ROOT, env=env, stdout=stream, stderr=stream)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        if os.name == "nt":
            ctypes.windll.user32.MessageBoxW(None, str(error), "Prompt to CAD Native", 0x10)
        else:
            raise

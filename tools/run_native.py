"""Launch the developer build without machine-specific paths."""
import argparse
import subprocess
import sys
from tools.build_native import ROOT, add_sdk_arguments, resolve_sdks, build_environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_sdk_arguments(parser)
    args = parser.parse_args()
    resolve_sdks(args)
    executable = args.build_dir / "bin/PromptToCAD.exe"
    if not executable.is_file():
        parser.error("Build first: python -m tools.build_native")
    subprocess.run([str(executable), "--workspace", str(ROOT)], cwd=ROOT,
                   env=build_environment(args.qt_prefix, args.occt_prefix, args.toolchain_env, compiler=False), check=True)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError) as error:
        if sys.stderr is None:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, str(error), 'Prompt to CAD could not start', 0x10)
        else:
            print(str(error), file=sys.stderr)
        raise SystemExit(1)

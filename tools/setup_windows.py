"""Check prerequisites; optionally download a checksum-pinned Windows SDK environment."""
import argparse
import hashlib
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
from tools.build_native import ROOT, add_sdk_arguments, resolve_sdks, build_environment

MAMBA_URL = "https://github.com/mamba-org/micromamba-releases/releases/download/2.3.3-0/micromamba-win-64.exe"
MAMBA_SHA256 = "90085767d811e08a0fe240f7cb7a713915e1e5f24e3b0acfad9b37daa64c98fe"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_sdk_arguments(parser)
    parser.add_argument("--download-sdk", action="store_true")
    args = parser.parse_args()
    if os.name != "nt" or platform.machine().lower() not in ("amd64", "x86_64") or sys.maxsize < 2**32:
        parser.exit(1, "Supported build target: Windows x64.\n")
    if sys.version_info[:2] != (3, 11):
        parser.exit(1, "Use CPython 3.11 x64 (reference version 3.11.9).\n")
    if args.download_sdk:
        cache = ROOT / ".sdk"
        cache.mkdir(exist_ok=True)
        executable = cache / "micromamba-2.3.3.exe"
        if not executable.is_file():
            with urllib.request.urlopen(MAMBA_URL, timeout=120) as response:
                data = response.read()
            if hashlib.sha256(data).hexdigest() != MAMBA_SHA256:
                parser.exit(1, "Micromamba checksum mismatch; no executable installed.\n")
            executable.write_bytes(data)
        if hashlib.sha256(executable.read_bytes()).hexdigest() != MAMBA_SHA256:
            parser.exit(1, "Cached micromamba checksum mismatch.\n")
        prefix = cache / "windows"
        command = "install" if (prefix / "conda-meta/history").is_file() else "create"
        lockfile = ROOT / "tools/locks/sdk-win-64.lock"
        specifications = ["--file", str(lockfile)] if lockfile.is_file() else ["qt6-main=6.9.0=h83cda92_0", "occt=7.8.1=novtk_hdfbec02_103"]
        subprocess.run([str(executable), command, "--yes", "--no-rc", "--override-channels", "--root-prefix", str(cache / "cache"),
            "--prefix", str(prefix), "--channel", "conda-forge", "--strict-channel-priority",
            *specifications], check=True)
        lock = subprocess.check_output([str(executable), "list", "--prefix", str(prefix), "--explicit"], text=True)
        (cache / "resolved-win-64.txt").write_text(lock, encoding="utf-8")
    try:
        resolve_sdks(args)
        env = build_environment(args.qt_prefix, args.occt_prefix, args.toolchain_env)
        for name in ("cl", "rc", "cmake", "ninja", "dumpbin"):
            if not shutil.which(name, path=env["PATH"]):
                raise RuntimeError(f"Missing {name}. Install requirements-dev.txt and Visual Studio C++ x64 tools.")
        subprocess.run([sys.executable, "-m", "pip", "check"], check=True)
        subprocess.run([shutil.which("cmake", path=env["PATH"]), "--version"], env=env, check=True)
        print("Prerequisite checks passed. Run the build and clean-runner workflow next; this check is not clean-build proof.")
    except RuntimeError as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()

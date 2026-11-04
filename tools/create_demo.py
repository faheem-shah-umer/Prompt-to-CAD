"""Capture original public screenshots from a fresh synthetic app session."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
from uuid import uuid4
from tools.build_native import ROOT, add_sdk_arguments, resolve_sdks, build_environment
from tools.fixtures import write_assembly


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_sdk_arguments(parser)
    args = parser.parse_args()
    resolve_sdks(args)
    output = ROOT / "artifacts" / ("public-demo-" + uuid4().hex[:8])
    fixture = write_assembly(output / "input")
    assets = ROOT / "site/assets"
    assets.mkdir(parents=True, exist_ok=True)
    hashes = []
    for theme in ("dark", "light"):
        env = build_environment(args.qt_prefix, args.occt_prefix, args.toolchain_env)
        env = {name: value for name, value in env.items() if not name.startswith(("OPENAI_", "CODEX_", "ANTHROPIC_", "PROMPTCAD_"))}
        env["CAD_UI_THEME"] = theme
        subprocess.run([str(args.build_dir / "bin/PromptToCAD.exe"), "--workspace", str(ROOT),
            "--open", str(fixture), "--demo-capture", str(output / theme), "--smoke-size", "1600x1000"],
            cwd=ROOT, env=env, check=True, timeout=150)
        # Re-encode pixels only: strips metadata and never samples existing user images.
        from PIL import Image
        target = assets / f"workspace-{theme}.png"
        with Image.open(output / theme / target.name) as image:
            image.convert("RGB").save(target, optimize=True)
        hashes.append(f"- `{target.name}` SHA-256: `{hashlib.sha256(target.read_bytes()).hexdigest()}`")
    (assets / "PROVENANCE.md").write_text("# Public demo media\n\nOriginal captures of the real native app, generated with `python -m tools.create_demo` using only `tools.fixtures.assembly_definition()`. Every run uses a fresh isolated project, identity and settings directory. The prompt and response are labelled synthetic fixtures, not evidence of live AI inference. No personal project, chat, account, image or CAD file was opened. Images are re-encoded without metadata.\n\nPrompt: Create a 64 × 44 × 8 mm mounting plate with four holes, a central 20 mm column and a lofted cap. Use separate components.\n\nResult: three independently rendered CAD solids from the local backend.\n\n" + "\n".join(hashes) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

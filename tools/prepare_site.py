"""Prepare the buildless project website and a project-subpath local preview."""
from pathlib import Path
import shutil
from tools.build_native import ROOT


def main():
    site = ROOT / "site"
    (site / "assets").mkdir(exist_ok=True)
    shutil.copy2(ROOT / "assets/app-icon.svg", site / "assets/app-icon.svg")
    preview = ROOT / "site-preview/Prompt-to-CAD"
    preview.mkdir(parents=True, exist_ok=True)
    for path in site.rglob("*"):
        if path.is_file():
            target = preview / path.relative_to(site)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    print("Preview: python -m http.server 8080 --bind 127.0.0.1 --directory site-preview")
    print("Open http://127.0.0.1:8080/Prompt-to-CAD/")


if __name__ == "__main__":
    main()

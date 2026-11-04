"""Reviewed source and approved public-media inclusion rules."""
from pathlib import PurePosixPath
from tools.generate_icons import ICONS

ROOT_FILES = {".gitattributes", ".gitignore", "LICENSE", "README.md", "VERSION",
    "THIRD_PARTY_NOTICES.md", "Prompt to CAD.vbs", "Run-PromptToCAD.cmd", "requirements.txt", "requirements-dev.txt", "requirements-runtime-lock.txt"}
BRANDING = {"assets/README.md", "assets/app-icon.svg", "assets/app-icon.png", "assets/app-icon.ico"}
SITE_FILES = {"site/index.html", "site/styles.css", "site/main.js", "site/assets/app-icon.svg",
    "site/assets/workspace-dark.png", "site/assets/workspace-light.png", "site/assets/PROVENANCE.md",
    "site/assets/pen-plotter-demo.gif", "site/assets/pen-plotter-workspace.png"}


def is_public_source(relative):
    path = PurePosixPath(str(relative).replace("\\", "/"))
    name = path.as_posix()
    if name in ROOT_FILES or name in BRANDING or name in SITE_FILES or name == "tools/locks/sdk-win-64.lock":
        return True
    if len(path.parts) < 2 or any(part.startswith(".") or part == "__pycache__" for part in path.parts[1:]):
        return False
    if path.parts[:2] == ("assets", "icons"):
        return path.name in {item + ".svg" for item in ICONS} | {"LICENSE", "README.md"}
    if path.parts[0] == "backend":
        return path.suffix == ".py" or name == "backend/v2/CAD_INSTRUCTIONS.md"
    if path.parts[0] == "tools":
        return path.suffix == ".py" or name == "tools/check_website.mjs"
    if path.parts[0] == "native":
        return path.suffix in (".cpp", ".h", ".qrc", ".in") or name in ("native/CMakeLists.txt", "native/requirements-build.txt")
    if path.parts[0] == "docs":
        return path.suffix == ".md"
    return path.parts[:2] == (".github", "workflows") and path.suffix in (".yml", ".yaml")

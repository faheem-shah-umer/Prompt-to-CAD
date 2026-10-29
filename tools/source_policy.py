"""Files permitted in the source repository and packaged application source."""

from pathlib import PurePosixPath

ROOT_FILES = {
    ".gitattributes", ".gitignore", "LICENSE", "README.md", "THIRD_PARTY_NOTICES.md",
    "requirements.txt", "requirements-dev.txt", "native-app.py", "Prompt to CAD V2.vbs",
}
BRANDING = {"assets/README.md", "assets/app-icon.svg", "assets/app-icon.png", "assets/app-icon.ico"}


def is_public_source(relative):
    path = PurePosixPath(str(relative).replace("\\", "/"))
    if any(part.startswith(".") or part == "__pycache__" for part in path.parts[1:]):
        return False
    name = path.as_posix()
    if name in ROOT_FILES or name in BRANDING:
        return True
    if len(path.parts) < 2:
        return False
    if path.parts[0] == "backend":
        return path.suffix == ".py" or name == "backend/v2/CAD_INSTRUCTIONS.md"
    if path.parts[0] == "tools":
        return path.suffix == ".py"
    if path.parts[0] == "native":
        return path.suffix in (".cpp", ".h", ".qrc", ".in") or name in (
            "native/CMakeLists.txt", "native/requirements-build.txt",
        )
    if path.parts[0] == "docs":
        return path.suffix == ".md"
    return path.parts[:2] == (".github", "workflows") and path.suffix in (".yml", ".yaml")

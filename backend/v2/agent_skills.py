"""Read-only registry for the application's bundled agent workflow skills."""

import hashlib
import re
from pathlib import Path

from backend.native.contracts import WorkspaceError

SKILLS_ROOT = Path(__file__).resolve().parents[2] / "skills"
SKILL_IDS = (
    "promptcad-modeling",
    "promptcad-catalog",
    "promptcad-review",
)
MAX_SKILL_BYTES = 32_000
FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)


def _load(skill_id):
    if not isinstance(skill_id, str) or skill_id not in SKILL_IDS:
        raise WorkspaceError("Choose a registered Prompt to CAD skill ID.", "invalid_skill")

    root = SKILLS_ROOT.resolve()
    directory = SKILLS_ROOT / skill_id
    path = directory / "SKILL.md"
    try:
        if directory.is_symlink() or path.is_symlink():
            raise WorkspaceError("Skill files cannot use filesystem links.", "invalid_skill")
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
        raw = resolved.read_bytes()
    except WorkspaceError:
        raise
    except (OSError, ValueError) as error:
        raise WorkspaceError(
            "A bundled Prompt to CAD skill is missing or unreadable.", "skill_unavailable"
        ) from error

    if not raw or len(raw) > MAX_SKILL_BYTES:
        raise WorkspaceError("The bundled skill has an invalid size.", "invalid_skill")
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise WorkspaceError("The bundled skill is not UTF-8 text.", "invalid_skill") from error
    match = FRONTMATTER.match(content)
    if not match:
        raise WorkspaceError("The bundled skill manifest is invalid.", "invalid_skill")

    fields = {}
    for line in match.group(1).splitlines():
        key, separator, value = line.partition(":")
        if separator:
            fields[key.strip()] = value.strip().strip("\"'")
    if fields.get("name") != skill_id or not fields.get("description") or not fields.get("version"):
        raise WorkspaceError("The bundled skill manifest is incomplete.", "invalid_skill")
    return {
        "id": skill_id,
        "name": fields["name"],
        "description": fields["description"],
        "version": fields["version"],
        "sha256": hashlib.sha256(raw).hexdigest(),
        "content": content,
    }


def describe():
    """Return skill routing metadata without filesystem paths or full instructions."""
    skills = []
    for skill_id in SKILL_IDS:
        try:
            skill = _load(skill_id)
            skills.append({key: skill[key] for key in ("id", "name", "description", "version", "sha256")})
        except WorkspaceError as error:
            skills.append({"id": skill_id, "available": False, "error": error.code})
    return {"available": skills}


def read(skill_id):
    """Return one registered skill's instructions; callers cannot choose a path."""
    return _load(skill_id)


def list_or_read(action, skill_id=None):
    if action == "list":
        return describe()
    if action == "read":
        return {"skill": read(skill_id)}
    raise WorkspaceError("Choose the list or read skill action.", "invalid_skill_action")

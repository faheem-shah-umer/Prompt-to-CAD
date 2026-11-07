"""Local draft checkpoints for agent turns.

After every successful CAD operation the task's candidate is written to
``<document>/draft.json``. Geometry is not copied: the record points at the
content-addressed asset files the operation already stored. Drafts are kept
apart from accepted revisions (``project.json`` / ``revisions/``) and become a
revision only through the normal validation and acceptance path.
"""

import copy
import hashlib
import json
import time
from uuid import uuid4

from backend.native.contracts import WorkspaceError
from backend.native.documents import asset_path, write_json

DRAFT_FILE = "draft.json"


def _path(document):
    return document.folder / DRAFT_FILE


def read(document):
    path = _path(document)
    if not path.is_file():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) and isinstance(record.get("snapshot"), dict) else None


def save(document, tools, task):
    """Checkpoint the candidate after a successful operation; atomic, so a failure keeps the previous one."""
    previous = read(document)
    resumed = getattr(tools, "resumed_draft", None) or {}
    # The same turn, or a turn continuing this draft, extends it; any other turn starts a new draft.
    continuing = previous is not None and (previous.get("task_id") == task["task_id"]
                                           or previous.get("draft_id") == resumed.get("draft_id"))
    snapshot = copy.deepcopy(tools.candidate)
    snapshot.pop("_component_transaction", None)
    snapshot.pop("project_dir", None)
    record = {
        "schema_version": 1,
        "draft_id": previous["draft_id"] if continuing else uuid4().hex,
        "task_id": task["task_id"],
        "conversation_id": task["conversation_id"],
        "document_id": tools.original.get("document_id"),
        "base_revision_id": tools.original.get("revision_id"),
        "prompt": task.get("prompt", "")[:16000],
        "checkpoint": (previous.get("checkpoint", 0) if continuing else 0) + 1,
        "created_at": previous.get("created_at") if continuing else time.time(),
        "updated_at": time.time(),
        "status": "running",
        "stop_reason": None,
        "snapshot": snapshot,
        "commands": copy.deepcopy(list(getattr(tools, "prior_commands", [])) + list(tools.commands)),
        "created": sorted(tools.created),
        "retired": sorted(tools.retired),
        "transactions": copy.deepcopy(tools.transactions),
        "catalog_groups": copy.deepcopy(tools.catalog_groups),
        "decisions": copy.deepcopy(tools.decisions),
    }
    write_json(_path(document), record)
    return record


def summary(document, current_revision_id):
    record = read(document)
    if record is None:
        return None
    components = record["snapshot"].get("components", [])
    return {
        "draft_id": record.get("draft_id"),
        "task_id": record.get("task_id"),
        "conversation_id": record.get("conversation_id"),
        "checkpoint": record.get("checkpoint", 0),
        "operations": len(record.get("commands", [])),
        "component_count": len(components),
        "component_names": [p.get("name", "") for p in components[:12]],
        "updated_at": record.get("updated_at"),
        "status": record.get("status"),
        "stop_reason": record.get("stop_reason"),
        "stale": record.get("base_revision_id") != current_revision_id,
    }


def load(document, draft_id, base_revision_id):
    """The draft record, verified against the current revision and the assets on disk."""
    record = read(document)
    if record is None or record.get("draft_id") != draft_id:
        raise WorkspaceError("This draft is no longer available.", "draft_missing")
    if record.get("base_revision_id") != base_revision_id:
        raise WorkspaceError("The document changed after this draft was saved. Preview or discard the draft; "
                             "it can no longer be continued.", "draft_stale")
    snapshot = record["snapshot"]
    for part in snapshot.get("components", []):
        path = asset_path(document.folder, part.get("mesh", part.get("brep", "")))
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != part.get("asset_hash"):
            raise WorkspaceError("A geometry file used by this draft is missing or changed. Discard the draft.",
                                 "asset_integrity")
    from .definitions import read as read_definition
    from .engineering import validate_records
    for definition in snapshot.get("definitions", []):
        if "source" not in definition:
            read_definition(document.folder, definition)
    validate_records(snapshot)
    return record


def mark_stopped(document, task_id, reason, draft_id=None):
    record = read(document)
    if record is None or (record.get("task_id") != task_id and (draft_id is None or record.get("draft_id") != draft_id)):
        return None
    record.update(status="stopped", stop_reason=str(reason)[:600], updated_at=time.time())
    write_json(_path(document), record)
    return record


def discard(document, draft_id=None):
    record = read(document)
    if record is None:
        return False
    if draft_id is not None and record.get("draft_id") != draft_id:
        raise WorkspaceError("This draft is no longer available.", "draft_missing")
    _path(document).unlink(missing_ok=True)
    return True

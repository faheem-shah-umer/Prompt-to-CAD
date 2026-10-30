import copy
import hashlib
import json
import os
import shutil
from pathlib import Path
from uuid import uuid4

from .contracts import WorkspaceError
from backend.native.project_lock import revision_lock


def write_json(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(content, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def asset_path(folder, relative):
    folder = Path(folder).resolve()
    path = (folder / relative).resolve()
    if not path.is_relative_to(folder):
        raise WorkspaceError("A project asset points outside the project directory.", "invalid_project")
    return path


class Document:
    def __init__(self, folder):
        self.folder = Path(folder).resolve()
        self.index_path = self.folder / "project.json"

    @classmethod
    def create(cls, folder, name):
        doc = cls(folder)
        doc.folder.mkdir(parents=True, exist_ok=True)
        if any(doc.folder.iterdir()):
            raise WorkspaceError("Choose an empty directory for a new project.", "destination_exists")
        write_json(doc.index_path, {"schema_version": 2, "document_id": str(uuid4()), "name": name,
                                   "revisions": [], "cursor": -1})
        return doc

    def index(self):
        index = json.loads(self.index_path.read_text(encoding="utf-8"))
        if index.get("schema_version") != 2:
            raise WorkspaceError("This is not a version-2 native CAD project.", "invalid_project")
        return index

    def current(self, index=None):
        index = self.index() if index is None else index
        if index["cursor"] < 0:
            raise WorkspaceError("The project has no accepted geometry.", "empty_project")
        revision = index["revisions"][index["cursor"]]
        snapshot = json.loads(asset_path(self.folder, f"revisions/{revision}.json").read_text(encoding="utf-8"))
        if snapshot["revision_id"] != revision or snapshot["document_id"] != index["document_id"]:
            raise WorkspaceError("The project revision does not match its index.", "invalid_project")
        for part in snapshot["components"]:
            path = asset_path(self.folder, part.get("mesh", part.get("brep", "")))
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != part["asset_hash"]:
                raise WorkspaceError("A geometry asset is missing or has changed.", "invalid_project")
        from backend.v2.definitions import read
        for record in snapshot.get("definitions", []):
            read(self.folder, record)
        from backend.v2.engineering import validate_records
        validate_records(snapshot)
        return snapshot

    def view(self):
        index = self.index()
        snapshot = self.current(index)
        snapshot["project_dir"] = str(self.folder)
        snapshot["can_undo"] = index["cursor"] > 0
        snapshot["can_redo"] = index["cursor"] < len(index["revisions"]) - 1
        snapshot["history"] = [{"revision_id": rid, "summary": json.loads(
            asset_path(self.folder, f"revisions/{rid}.json").read_text(encoding="utf-8"))["summary"]}
            for rid in index["revisions"]]
        return snapshot

    def check(self, base_revision):
        snapshot = self.current()
        if snapshot["revision_id"] != base_revision:
            raise WorkspaceError("The document changed. Inspect the current revision before editing.", "revision_conflict")
        return snapshot

    def commit(self, candidate, base_revision=None, summary="Imported CAD", conversation=None, commands=None):
        with revision_lock(self.folder):
            index = self.index()
            if index["cursor"] >= 0:
                self.check(base_revision)
            elif base_revision is not None:
                raise WorkspaceError("A new project cannot have a base revision.", "revision_conflict")
            snapshot = copy.deepcopy(candidate)
            snapshot.pop("_component_transaction", None)
            from backend.v2.definitions import materialize
            materialize(self.folder, snapshot)
            snapshot.update(schema_version=2, document_id=index["document_id"], revision_id=str(uuid4()),
                            name=index["name"], units="mm", summary=summary, parent_revision_id=base_revision)
            snapshot.pop("project_dir", None)
            snapshot["commands"] = commands or []
            snapshot["conversation"] = conversation if conversation is not None else snapshot.get("conversation", [])
            write_json(self.folder / "revisions" / f"{snapshot['revision_id']}.json", snapshot)
            index["revisions"] = index["revisions"][:index["cursor"] + 1] + [snapshot["revision_id"]]
            index["cursor"] = len(index["revisions"]) - 1
            write_json(self.index_path, index)
        return self.view()

    def move_history(self, direction, base_revision):
        with revision_lock(self.folder):
            self.check(base_revision)
            index = self.index()
            cursor = index["cursor"] + direction
            if not 0 <= cursor < len(index["revisions"]):
                raise WorkspaceError("There is no further revision in that direction.", "history_limit")
            index["cursor"] = cursor
            write_json(self.index_path, index)
        return self.view()

    def restore(self, revision_id, base_revision):
        with revision_lock(self.folder):
            self.check(base_revision)
            index = self.index()
            if revision_id not in index["revisions"]:
                # Task links still address immutable snapshots after a new edit replaces the redo path.
                path = asset_path(self.folder, f"revisions/{revision_id}.json")
                if not path.is_file():
                    raise WorkspaceError("This revision is not available in the document history.")
                proposed = {**index, "revisions": [revision_id], "cursor": 0}
                self.current(proposed)
                index["revisions"] = index["revisions"][:index["cursor"]+1] + [revision_id]
            index["cursor"] = index["revisions"].index(revision_id)
            write_json(self.index_path, index)
        return self.view()

    def save_as(self, destination):
        destination = Path(destination).resolve()
        if destination == self.folder or destination.is_relative_to(self.folder):
            raise WorkspaceError("Save a copy outside the current project directory.")
        if destination.exists():
            raise WorkspaceError("Choose a new project directory.", "destination_exists")
        staging = destination.with_name(destination.name + "." + uuid4().hex + ".tmp")
        try:
            with revision_lock(self.folder):
                shutil.copytree(self.folder, staging, ignore=shutil.ignore_patterns("*.lock", "*.tmp", "pending.json"))
            os.replace(staging, destination)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        return Document(destination)

    def journal(self, status, **details):
        write_json(self.folder / "pending.json", {"status": status, **details})

    def recover(self):
        pending = self.folder / "pending.json"
        if pending.exists():
            state = json.loads(pending.read_text(encoding="utf-8"))
            if state.get("status") == "running":
                self.journal("interrupted", message="The previous task was interrupted; the accepted revision was preserved.")
                return "The previous task was interrupted. The last accepted revision has been restored."
        return ""

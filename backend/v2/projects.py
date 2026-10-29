"""Atomic local project metadata, independent conversations and durable task links."""

import hashlib
import json
import re
import shutil
import time
from pathlib import Path
from uuid import uuid4

from backend.native.documents import Document, write_json
from backend.native.contracts import WorkspaceError
from backend.native.project_lock import revision_lock
from backend.native.project_lock import RevisionConflict


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", value):
        raise WorkspaceError("Invalid project entity identifier.")
    return value


class Projects:
    def __init__(self, folder):
        self.folder = Path(folder).resolve()
        self.folder.mkdir(parents=True, exist_ok=True)
        self.catalog = self.folder / "catalog.json"
        if not self.catalog.exists():
            write_json(self.catalog, {"version": 1, "projects": [], "active": None})
        # An interrupted task never becomes an accepted revision on restart.
        for path in self.folder.glob("*/tasks/*.json"):
            record = json.loads(path.read_text(encoding="utf-8"))
            if record.get("status") == "running":
                project = self.read(path.parent.parent / "workspace.json")
                entry = next((d for d in project["documents"] if d["document_id"] == record.get("document_id")), None)
                if entry:
                    try:
                        with revision_lock(Path(entry["path"]) / ".task-lock"):
                            record.update(
                                status="interrupted",
                                message="Application stopped. The accepted document was preserved.",
                            )
                            write_json(path, record)
                    except RevisionConflict:
                        pass

    def read(self, path):
        return json.loads(Path(path).read_text(encoding="utf-8"))

    def project_path(self, project_id):
        return self.folder / identifier(project_id)

    def project(self, project_id):
        return self.read(self.project_path(project_id) / "workspace.json")

    def listing(self):
        catalog = self.read(self.catalog)
        projects = []
        for pid in catalog["projects"]:
            project = self.project(pid)
            project["conversation_summaries"] = [
                {k: c.get(k) for k in ("conversation_id", "document_id", "title", "archived", "trashed")}
                for c in (self.conversation(pid, cid) for cid in project["conversations"])
            ]
            projects.append(project)
        return {**catalog, "projects": projects}

    def create(self, name):
        name = str(name).strip()[:120] or "Untitled project"
        project_id = uuid4().hex[:16]
        base = self.project_path(project_id)
        document = Document.create(base / "documents" / uuid4().hex[:16], name)
        did = document.index()["document_id"]
        project = {
            "project_id": project_id,
            "name": name,
            "archived": False,
            "documents": [{"document_id": did, "path": str(document.folder), "name": name}],
            "active_document_id": did,
            "conversations": [],
            "active_conversation_id": None,
            "created_at": time.time(),
        }
        write_json(base / "workspace.json", project)
        with revision_lock(self.folder):
            catalog = self.read(self.catalog)
            catalog["projects"].append(project_id)
            catalog["active"] = project_id
            write_json(self.catalog, catalog)
        self.new_conversation(project_id, did)
        return self.project(project_id)

    def update(self, project_id, **values):
        base = self.project_path(project_id)
        with revision_lock(base):
            project = self.project(project_id)
            project.update(values)
            write_json(base / "workspace.json", project)
        return project

    def activate(self, project_id):
        project = self.project(project_id)
        with revision_lock(self.folder):
            catalog = self.read(self.catalog)
            catalog["active"] = project_id
            catalog["projects"] = [project_id] + [p for p in catalog["projects"] if p != project_id]
            write_json(self.catalog, catalog)
        return project

    def document(self, project, document_id=None):
        wanted = document_id or project["active_document_id"]
        entry = next((d for d in project["documents"] if d["document_id"] == wanted), None)
        if not entry:
            raise WorkspaceError("The conversation's document is not in this project.")
        return Document(entry["path"])

    def adopt(self, project_id, document):
        project = self.project(project_id)
        index = document.index()
        entries = [d for d in project["documents"] if d["document_id"] != index["document_id"]]
        entries.append({"document_id": index["document_id"], "path": str(document.folder), "name": index["name"]})
        self.update(project_id, documents=entries, active_document_id=index["document_id"])
        existing = next(
            (
                c
                for c in (self.conversation(project_id, cid) for cid in reversed(project["conversations"]))
                if c["document_id"] == index["document_id"] and not c.get("archived") and not c.get("trashed")
            ),
            None,
        )
        if existing:
            self.update(project_id, active_conversation_id=existing["conversation_id"])
            return existing
        return self.new_conversation(project_id, index["document_id"], index["name"])

    def new_conversation(self, project_id, document_id=None, title="New conversation"):
        project = self.project(project_id)
        doc = self.document(project, document_id)
        conversation = {
            "conversation_id": uuid4().hex,
            "document_id": doc.index()["document_id"],
            "title": str(title)[:120],
            "archived": False,
            "messages": [],
            "tasks": [],
            "provider_session": None,
            "provider_account": None,
        }
        base = self.project_path(project_id)
        write_json(base / "conversations" / (conversation["conversation_id"] + ".json"), conversation)
        self.update(
            project_id,
            conversations=project["conversations"] + [conversation["conversation_id"]],
            active_conversation_id=conversation["conversation_id"],
            active_document_id=conversation["document_id"],
        )
        return conversation

    def conversation(self, project_id, conversation_id=None):
        project = self.project(project_id)
        cid = identifier(conversation_id or project["active_conversation_id"])
        if cid not in project["conversations"]:
            raise WorkspaceError("Unknown conversation.")
        return self.read(self.project_path(project_id) / "conversations" / (cid + ".json"))

    def save_conversation(self, project_id, conversation):
        write_json(
            self.project_path(project_id) / "conversations" / (identifier(conversation["conversation_id"]) + ".json"),
            conversation,
        )

    def task(self, project_id, task):
        write_json(self.project_path(project_id) / "tasks" / (identifier(task["task_id"]) + ".json"), task)

    def view(self, project_id):
        project = self.project(project_id)
        conversation = self.conversation(project_id)
        doc = self.document(project, conversation["document_id"])
        if doc.index()["cursor"] < 0:
            snapshot = {
                "components": [],
                "assembly_nodes": [],
                "revision_id": None,
                "document_id": doc.index()["document_id"],
                "name": doc.index()["name"],
                "units": "mm",
                "project_dir": str(doc.folder),
                "history": [],
                "can_undo": False,
                "can_redo": False,
            }
        else:
            snapshot = doc.view()
        return {
            "project": project,
            "document": snapshot,
            "conversation": conversation,
            "conversations": [
                {k: c.get(k) for k in ("conversation_id", "document_id", "title", "archived", "trashed")}
                for c in (self.conversation(project_id, cid) for cid in project["conversations"])
            ],
            "catalog": self.listing(),
        }

    def reference(self, project_id, source):
        source = Path(source).resolve()
        if source.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp") or source.stat().st_size > 20 * 1024 * 1024:
            raise WorkspaceError("Attach an image of at most 20 MB (PNG, JPEG or WebP).")
        from PIL import Image

        with Image.open(source) as image:
            image.verify()
        data = source.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        target = self.project_path(project_id) / "references" / (digest + source.suffix.lower())
        target.parent.mkdir(exist_ok=True)
        if not target.exists():
            shutil.copyfile(source, target)
        return {"asset_id": digest, "sha256": digest, "path": str(target), "name": source.name, "type": "image"}

    @staticmethod
    def check_reference(reference):
        path = Path(reference["path"])
        if hashlib.sha256(path.read_bytes()).hexdigest() != reference["sha256"]:
            raise WorkspaceError("A reference image changed after attachment.", "asset_integrity")
        return path

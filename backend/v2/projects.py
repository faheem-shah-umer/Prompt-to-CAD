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


def folder_name(name):
    name = (
        re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(name)).strip(" .")[:80].rstrip(" .")
    )
    name = name or "Untitled project"
    if name.split(".")[0].upper() in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }:
        name = "_" + name
    return name


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
                entry = next(
                    (
                        d
                        for d in project["documents"]
                        if d["document_id"] == record.get("document_id")
                    ),
                    None,
                )
                if entry:
                    try:
                        with revision_lock(
                            self.document(project, record["document_id"]).folder
                            / ".task-lock"
                        ):
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
        project_id = identifier(project_id)
        name = self.read(self.catalog).get("folders", {}).get(project_id, project_id)
        path = (self.folder / name).resolve()
        if path.parent != self.folder:
            raise WorkspaceError("Invalid project folder.")
        return path

    def project(self, project_id):
        return self.read(self.project_path(project_id) / "workspace.json")

    def listing(self):
        catalog = self.read(self.catalog)
        projects = []
        for pid in catalog["projects"]:
            project = self.project(pid)
            project["folder_path"] = str(self.project_path(pid))
            project["conversation_summaries"] = [
                {
                    k: c.get(k)
                    for k in (
                        "conversation_id",
                        "document_id",
                        "title",
                        "archived",
                        "trashed",
                    )
                }
                for c in (
                    self.conversation(pid, cid) for cid in project["conversations"]
                )
            ]
            projects.append(project)
        return {**catalog, "projects": projects}

    def create(self, name):
        name = str(name).strip()[:120] or "Untitled project"
        project_id = uuid4().hex[:16]
        with revision_lock(self.folder):
            stem = folder_name(name)
            directory = stem
            number = 2
            while (self.folder / directory).exists():
                directory = f"{stem} ({number})"
                number += 1
            base = self.folder / directory
            if base.resolve().parent != self.folder:
                raise WorkspaceError("Invalid project folder.")
            document = Document.create(base / "documents" / uuid4().hex[:16], name)
            did = document.index()["document_id"]
            project = {
                "project_id": project_id,
                "name": name,
                "archived": False,
                "documents": [
                    {
                        "document_id": did,
                        "path": str(document.folder.relative_to(base)),
                        "name": name,
                    }
                ],
                "active_document_id": did,
                "conversations": [],
                "active_conversation_id": None,
                "created_at": time.time(),
            }
            write_json(base / "workspace.json", project)
            catalog = self.read(self.catalog)
            catalog.setdefault("folders", {})[project_id] = directory
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

    def import_project(self, source):
        source = Path(source).resolve()
        project = self.read(source / "workspace.json")
        pid = identifier(project["project_id"])
        with revision_lock(self.folder):
            catalog = self.read(self.catalog)
            if pid in catalog["projects"]:
                if self.project_path(pid) == source:
                    return pid
                raise WorkspaceError(
                    "This project is already in the Projects folder. Open that copy to continue."
                )
            stem = folder_name(project["name"])
            name, number = stem, 2
            while (self.folder / name).exists():
                name, number = f"{stem} ({number})", number + 1
            target = (self.folder / name).resolve()
            temporary = (self.folder / (".import-" + uuid4().hex)).resolve()
            if target.parent != self.folder or temporary.parent != self.folder:
                raise WorkspaceError("Invalid project folder.")
            try:
                shutil.copytree(source, temporary)
                for entry in project["documents"]:
                    original = Path(entry["path"])
                    original = original if original.is_absolute() else source / original
                    original = original.resolve()
                    if original.is_relative_to(source):
                        copied = temporary / original.relative_to(source)
                    else:
                        copied = (
                            temporary / "documents" / identifier(entry["document_id"])
                        )
                        shutil.copytree(original, copied)
                    document = Document(copied)
                    index = document.index()
                    if index["document_id"] != entry["document_id"]:
                        raise WorkspaceError(
                            "A project document does not match its index."
                        )
                    if index["cursor"] >= 0:
                        document.current()
                    entry["path"] = str(copied.relative_to(temporary))
                for cid in project["conversations"]:
                    path = temporary / "conversations" / (identifier(cid) + ".json")
                    conversation = self.read(path)
                    conversation.update(provider_session=None, provider_account=None)
                    write_json(path, conversation)
                write_json(temporary / "workspace.json", project)
                temporary.rename(target)
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
            catalog.setdefault("folders", {})[pid] = name
            catalog["projects"].append(pid)
            catalog["active"] = pid
            write_json(self.catalog, catalog)
        return pid

    def activate(self, project_id):
        project = self.project(project_id)
        with revision_lock(self.folder):
            catalog = self.read(self.catalog)
            catalog["active"] = project_id
            catalog["projects"] = [project_id] + [
                p for p in catalog["projects"] if p != project_id
            ]
            write_json(self.catalog, catalog)
        return project

    def document(self, project, document_id=None):
        wanted = document_id or project["active_document_id"]
        entry = next(
            (d for d in project["documents"] if d["document_id"] == wanted), None
        )
        if not entry:
            raise WorkspaceError("The conversation's document is not in this project.")
        path = Path(entry["path"])
        return Document(
            path
            if path.is_absolute()
            else self.project_path(project["project_id"]) / path
        )

    def adopt(self, project_id, document):
        project = self.project(project_id)
        index = document.index()
        base = self.project_path(project_id)
        if not document.folder.is_relative_to(base):
            target = base / "documents" / index["document_id"]
            if target.exists() and Document(target).index() != index:
                raise WorkspaceError(
                    "This document was already imported and has diverged. Open it in a new project to keep both versions."
                )
            if not target.exists():
                shutil.copytree(document.folder, target)
            document = Document(target)
            if document.index()["cursor"] >= 0:
                document.current()
        entries = [
            d for d in project["documents"] if d["document_id"] != index["document_id"]
        ]
        entries.append(
            {
                "document_id": index["document_id"],
                "path": str(document.folder.relative_to(base)),
                "name": index["name"],
            }
        )
        self.update(
            project_id, documents=entries, active_document_id=index["document_id"]
        )
        existing = next(
            (
                c
                for c in (
                    self.conversation(project_id, cid)
                    for cid in reversed(project["conversations"])
                )
                if c["document_id"] == index["document_id"]
                and not c.get("archived")
                and not c.get("trashed")
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
        write_json(
            base / "conversations" / (conversation["conversation_id"] + ".json"),
            conversation,
        )
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
        return self.read(
            self.project_path(project_id) / "conversations" / (cid + ".json")
        )

    def save_conversation(self, project_id, conversation):
        write_json(
            self.project_path(project_id)
            / "conversations"
            / (identifier(conversation["conversation_id"]) + ".json"),
            conversation,
        )

    def task(self, project_id, task):
        write_json(
            self.project_path(project_id)
            / "tasks"
            / (identifier(task["task_id"]) + ".json"),
            task,
        )

    def view(self, project_id):
        project = self.project(project_id)
        project["folder_path"] = str(self.project_path(project_id))
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
                {
                    k: c.get(k)
                    for k in (
                        "conversation_id",
                        "document_id",
                        "title",
                        "archived",
                        "trashed",
                    )
                }
                for c in (
                    self.conversation(project_id, cid)
                    for cid in project["conversations"]
                )
            ],
            "catalog": self.listing(),
        }

    def reference(self, project_id, source):
        source = Path(source).resolve()
        if (
            source.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp")
            or source.stat().st_size > 20 * 1024 * 1024
        ):
            raise WorkspaceError(
                "Attach an image of at most 20 MB (PNG, JPEG or WebP)."
            )
        from PIL import Image

        with Image.open(source) as image:
            image.verify()
        data = source.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        target = (
            self.project_path(project_id)
            / "references"
            / (digest + source.suffix.lower())
        )
        target.parent.mkdir(exist_ok=True)
        if not target.exists():
            shutil.copyfile(source, target)
        return {
            "asset_id": digest,
            "sha256": digest,
            "path": str(target),
            "name": source.name,
            "type": "image",
        }

    @staticmethod
    def check_reference(reference):
        path = Path(reference["path"])
        if hashlib.sha256(path.read_bytes()).hexdigest() != reference["sha256"]:
            raise WorkspaceError(
                "A reference image changed after attachment.", "asset_integrity"
            )
        return path

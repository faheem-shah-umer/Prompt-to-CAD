"""Atomic local project metadata, independent conversations and durable task links."""

from contextlib import ExitStack, contextmanager
import hashlib
import json
import math
import os
import re
import shutil
import time
import threading
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
        self._mutex = threading.RLock()
        self._lock_depth = 0
        if not self.catalog.exists():
            write_json(self.catalog, {"version": 1, "projects": [], "active": None})
        self.reconcile()
        # An interrupted task never becomes an accepted revision on restart.
        for path in self.folder.glob("*/tasks/*.json"):
            try:
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
                        self.document(project, record["document_id"]).index()
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
            except (OSError, ValueError, KeyError, TypeError, WorkspaceError):
                # A missing project must not prevent recovery of the other projects.
                continue

    @contextmanager
    def write_lock(self):
        with self._mutex:
            if self._lock_depth:
                yield
            else:
                with revision_lock(self.folder):
                    self._lock_depth = 1
                    try:
                        yield
                    finally:
                        self._lock_depth = 0

    def read(self, path):
        return json.loads(Path(path).read_text(encoding="utf-8"))

    def project_path(self, project_id):
        project_id = identifier(project_id)
        catalog = self.read(self.catalog)
        if project_id not in catalog["projects"]:
            raise WorkspaceError("Unknown project.")
        name = catalog.get("folders", {}).get(project_id, project_id)
        path = (self.folder / name).resolve()
        if path.parent != self.folder:
            raise WorkspaceError("Invalid project folder.")
        return path

    def project(self, project_id):
        return self.read(self.project_path(project_id) / "workspace.json")

    def reconcile(self):
        """Project folders are authoritative; the catalogue is only an index."""
        try:
            return self._reconcile()
        except RevisionConflict:
            return self.listing()

    def _reconcile(self):
        with self.write_lock():
            try:
                catalog = self.read(self.catalog)
            except (OSError, ValueError):
                catalog = {"version": 1, "projects": [], "active": None}
            if not isinstance(catalog, dict):
                catalog = {}
            if not isinstance(catalog.get("projects"), list) or not all(
                isinstance(p, str) for p in catalog.get("projects", [])
            ):
                catalog["projects"] = []
            found, diagnostics = {}, []
            preferred = catalog.get("folders", {})
            if not isinstance(preferred, dict):
                preferred = {}
            folders = sorted(self.folder.iterdir(), key=lambda p: p.name.casefold())
            folders.sort(key=lambda p: p.name not in preferred.values())
            for base in folders:
                if not base.is_dir() or base.name.startswith("."):
                    continue
                try:
                    if base.resolve().parent != self.folder or base.is_symlink():
                        raise WorkspaceError("Project folder links are not supported.")
                    project = self.read(base / "workspace.json")
                    pid = identifier(project["project_id"])
                    if not isinstance(project["name"], str) or not isinstance(
                        project["conversations"], list
                    ):
                        raise WorkspaceError("Invalid project metadata.")
                    if pid in found:
                        raise WorkspaceError(
                            "Duplicate project ID; open or import a distinct project copy."
                        )
                    if (
                        not isinstance(project["documents"], list)
                        or not project["documents"]
                    ):
                        raise WorkspaceError("A project must contain a document.")
                    for entry in project["documents"]:
                        identifier(entry["document_id"])
                        path = Path(entry["path"])
                        path = path if path.is_absolute() else base / path
                        if (
                            not path.is_dir()
                            or Document(path).index()["document_id"]
                            != entry["document_id"]
                        ):
                            raise WorkspaceError(
                                "A project document is missing or does not match its index."
                            )
                    for cid in project["conversations"]:
                        chat = self.read(
                            base / "conversations" / (identifier(cid) + ".json")
                        )
                        if chat["conversation_id"] != cid or chat[
                            "document_id"
                        ] not in {d["document_id"] for d in project["documents"]}:
                            raise WorkspaceError(
                                "A conversation does not match its project."
                            )
                    self.initialize_timestamps(base, project)
                    found[pid] = base.name
                except (
                    OSError,
                    ValueError,
                    KeyError,
                    TypeError,
                    WorkspaceError,
                ) as error:
                    # Unrelated folders without project metadata are not projects.
                    if (
                        base / "workspace.json"
                    ).exists() or base.name in preferred.values():
                        diagnostics.append(
                            {
                                "name": base.name,
                                "folder_path": str(base),
                                "reason": str(error)
                                if isinstance(error, WorkspaceError)
                                else "Project metadata could not be read.",
                            }
                        )
            order = [pid for pid in catalog.get("projects", []) if pid in found]
            order.extend(pid for pid in found if pid not in order)
            updated = {
                "version": 1,
                "projects": order,
                "folders": found,
                "active": catalog.get("active")
                if catalog.get("active") in found
                else None,
            }
            if updated != catalog:
                write_json(self.catalog, updated)
            self.diagnostics = diagnostics
        return self.listing()

    def listing(self):
        catalog = self.read(self.catalog)
        projects = []
        for pid in catalog["projects"]:
            try:
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
            except (OSError, ValueError, KeyError, TypeError, WorkspaceError):
                continue
        return {
            **catalog,
            "projects": projects,
            "unavailable": [],
            "diagnostics": getattr(self, "diagnostics", []),
        }

    def initialize_timestamps(self, base, project):
        def valid(key):
            value = project.get(key)
            return type(value) in (int, float) and math.isfinite(value) and value >= 0

        if all(
            valid(key)
            for key in ("created_at", "content_modified_at", "last_opened_at")
        ):
            return
        if not valid("created_at"):
            project["created_at"] = (base / "workspace.json").stat().st_ctime
        if not valid("content_modified_at"):
            stamps = [project["created_at"]]
            for entry in project["documents"]:
                path = Path(entry["path"])
                path = path if path.is_absolute() else base / path
                stamps.append((path / "project.json").stat().st_mtime)
            stamps.extend(
                (base / "conversations" / (identifier(cid) + ".json")).stat().st_mtime
                for cid in project["conversations"]
            )
            project["content_modified_at"] = max(stamps)
        if not valid("last_opened_at"):
            project["last_opened_at"] = 0
        with revision_lock(base):
            write_json(base / "workspace.json", project)

    def touch(self, project_id):
        self.update(project_id, content_modified_at=time.time())

    def purge(self, project_id, conversation_id=None):
        # Workspace writers take the same root lock before document locks.
        with self.write_lock():
            base = self.project_path(project_id)
            project = self.project(project_id)
            with ExitStack() as locks:
                for entry in project["documents"]:
                    document = self.document(project, entry["document_id"])
                    if document.folder.exists():
                        locks.enter_context(
                            revision_lock(document.folder / ".task-lock")
                        )
            if conversation_id:
                cid = identifier(conversation_id)
                chat = self.conversation(project_id, cid)
                if not chat.get("trashed"):
                    raise WorkspaceError(
                        "Move the conversation to trash before deleting it permanently."
                    )
                paths = [base / "conversations" / (cid + ".json")]
                for path in (base / "tasks").glob("*.json"):
                    record = self.read(path)
                    if record.get("conversation_id") == cid:
                        paths.append(path)
                for path in paths:
                    if not path.resolve().is_relative_to(base):
                        raise WorkspaceError("Invalid conversation file path.")
                for path in paths:
                    path.unlink(missing_ok=True)
                project["conversations"].remove(cid)
                if project.get("active_conversation_id") == cid:
                    project["active_conversation_id"] = None
                project["content_modified_at"] = time.time()
                write_json(base / "workspace.json", project)
            else:
                if not project.get("trashed"):
                    raise WorkspaceError(
                        "Move the project to trash before deleting it permanently."
                    )
                # Refuse junctions and symlinks before recursively removing a project.
                for parent, directories, files in os.walk(base, followlinks=False):
                    for path in [
                        Path(parent),
                        *(Path(parent) / name for name in directories + files),
                    ]:
                        if (
                            path.is_symlink()
                            or getattr(path.lstat(), "st_file_attributes", 0) & 0x400
                        ):
                            raise WorkspaceError(
                                "Remove filesystem links before permanently deleting this project."
                            )
                if base.resolve().parent != self.folder:
                    raise WorkspaceError("Invalid project folder.")
                shutil.rmtree(base)
                catalog = self.read(self.catalog)
                catalog["projects"] = [
                    p for p in catalog["projects"] if p != project_id
                ]
                catalog.get("folders", {}).pop(project_id, None)
                if catalog.get("active") == project_id:
                    catalog["active"] = None
                write_json(self.catalog, catalog)

    def create(self, name):
        self.reconcile()
        name = str(name).strip()[:120] or "Untitled project"
        project_id = uuid4().hex[:16]
        with self.write_lock():
            catalog = self.read(self.catalog)
            reserved = {
                catalog.get("folders", {}).get(pid, pid).casefold()
                for pid in catalog["projects"]
            }
            stem = folder_name(name)
            directory = stem
            number = 2
            while (
                self.folder / directory
            ).exists() or directory.casefold() in reserved:
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
                "content_modified_at": time.time(),
                "last_opened_at": 0,
            }
            write_json(base / "workspace.json", project)
            catalog.setdefault("folders", {})[project_id] = directory
            catalog["projects"].append(project_id)
            catalog["active"] = project_id
            write_json(self.catalog, catalog)
        self.new_conversation(project_id, did)
        return self.project(project_id)

    def update(self, project_id, **values):
        with self.write_lock():
            base = self.project_path(project_id)
            with revision_lock(base):
                project = self.project(project_id)
                changed = {k for k, v in values.items() if project.get(k) != v}
                project.update(values)
                if changed & {"name", "archived", "trashed", "documents", "conversations"}:
                    project["content_modified_at"] = time.time()
                if changed:
                    write_json(base / "workspace.json", project)
        return project

    def import_project(self, source):
        self.reconcile()
        source = Path(source).resolve()
        project = self.read(source / "workspace.json")
        pid = identifier(project["project_id"])
        with self.write_lock():
            catalog = self.read(self.catalog)
            if pid in catalog["projects"]:
                if self.project_path(pid) == source:
                    return pid
                raise WorkspaceError(
                    "This project is already in the Projects folder. Open that copy to continue."
                )
            reserved = {
                catalog.get("folders", {}).get(pid, pid).casefold()
                for pid in catalog["projects"]
            }
            stem = folder_name(project["name"])
            name, number = stem, 2
            while (self.folder / name).exists() or name.casefold() in reserved:
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
                project["content_modified_at"] = time.time()
                project["last_opened_at"] = 0
                write_json(temporary / "workspace.json", project)
                self.initialize_timestamps(temporary, project)
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
        with self.write_lock():
            project = self.update(project_id, last_opened_at=time.time())
            catalog = self.read(self.catalog)
            catalog["active"] = project_id
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
        with self.write_lock():
            base = self.project_path(project_id)
            with revision_lock(base):
                path = base / "conversations" / (
                    identifier(conversation["conversation_id"]) + ".json"
                )
                previous = self.read(path) if path.exists() else {}
                write_json(path, conversation)
                if any(
                    previous.get(k) != conversation.get(k)
                    for k in ("title", "messages", "archived", "trashed", "document_id")
                ):
                    project = self.project(project_id)
                    project["content_modified_at"] = time.time()
                    write_json(base / "workspace.json", project)

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
        conversation = (
            self.conversation(project_id)
            if project.get("active_conversation_id")
            else None
        )
        if conversation and (
            conversation.get("archived") or conversation.get("trashed")
        ):
            conversation = None
        doc = self.document(
            project, conversation["document_id"] if conversation else None
        )
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

    def batch_conversations(self, items, action):
        if (
            action not in ("archive", "trash", "restore", "unarchive", "purge")
            or not isinstance(items, list)
            or not 1 <= len(items) <= 256
        ):
            raise WorkspaceError("Choose 1–256 conversations and a supported action.")
        unique = list(
            dict.fromkeys(
                (identifier(i["project_id"]), identifier(i["conversation_id"]))
                for i in items
            )
        )
        results = []
        with self.write_lock():
            prepared = []
            for pid, cid in unique:
                try:
                    prepared.append((pid, cid, self.conversation(pid, cid)))
                except (OSError, ValueError, WorkspaceError) as error:
                    results.append(
                        {
                            "project_id": pid,
                            "conversation_id": cid,
                            "passed": False,
                            "error": str(error),
                        }
                    )
            for pid, cid, chat in prepared:
                try:
                    if action == "purge":
                        self.purge(pid, cid)
                    else:
                        if action == "archive":
                            if chat.get("trashed"):
                                raise WorkspaceError(
                                    "Restore this conversation from Trash before archiving it."
                                )
                            chat["archived"] = True
                        elif action == "trash":
                            chat["trashed"] = True
                        elif action == "restore":
                            chat["trashed"] = False
                        else:
                            if chat.get("trashed"):
                                raise WorkspaceError(
                                    "Restore this conversation from Trash first."
                                )
                            chat["archived"] = False
                        self.save_conversation(pid, chat)
                        project = self.project(pid)
                        if project.get("active_conversation_id") == cid and (
                            chat.get("trashed") or chat.get("archived")
                        ):
                            self.update(pid, active_conversation_id=None)
                    results.append(
                        {"project_id": pid, "conversation_id": cid, "passed": True}
                    )
                except (OSError, ValueError, WorkspaceError, RevisionConflict) as error:
                    results.append(
                        {
                            "project_id": pid,
                            "conversation_id": cid,
                            "passed": False,
                            "error": str(error),
                        }
                    )
        return results

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
    def check_reference(reference, base=None):
        path = Path(reference["path"])
        if not path.is_absolute():
            if base is None:
                raise WorkspaceError("A relative reference needs its owning project.", "invalid_attachment")
            from .attachments import resolve
            return resolve(base, reference)
        if hashlib.sha256(path.read_bytes()).hexdigest() != reference["sha256"]:
            raise WorkspaceError(
                "A reference image changed after attachment.", "asset_integrity"
            )
        return path

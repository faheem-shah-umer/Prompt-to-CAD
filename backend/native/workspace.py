"""Document and geometry primitives shared by the current CAD workspace."""

import json
import os
import shutil
import threading
import time
from pathlib import Path
from uuid import uuid4

from .contracts import Selection, WorkspaceError
from .documents import Document
from .worker_client import GeometryWorker


class Workspace:
    def __init__(self, projects_dir, notify=lambda event: None):
        self.projects_dir = Path(projects_dir)
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self.worker = GeometryWorker(
            self.projects_dir / ".logs",
            timeout=float(os.getenv("CAD_GEOMETRY_TIMEOUT", "120")),
        )
        self.document = None
        self.cancelled = threading.Event()
        self.notify = notify
        self.task_deadline = None

    def geometry(self, method, params, timeout=None):
        if self.task_deadline is not None:
            remaining = self.task_deadline - time.monotonic()
            if remaining <= 0:
                raise WorkspaceError(
                    "The agent reached its ten-minute task limit.", "timeout"
                )
            timeout = min(
                timeout if timeout is not None else self.worker.timeout, remaining
            )
        command = params.get("command", {})
        standard_parameters = (method == "apply" and command.get("type") == "parameters" and
            any(p.get("standard_part") and p["instance_id"] == command.get("instance_id")
                for p in params.get("snapshot", {}).get("components", [])))
        if method in ("standard_parts", "standard_part") or standard_parameters:
            worker = GeometryWorker(self.projects_dir / ".logs", timeout=self.worker.timeout)
            try:
                return worker.call(method, params, cancel=self.cancelled, progress=self.notify, timeout=timeout)
            finally:
                worker.close()
        return self.worker.call(
            method, params, cancel=self.cancelled, progress=self.notify, timeout=timeout
        )

    def required(self, params, revision=True):
        if self.document is None:
            raise WorkspaceError(
                "Open or generate a CAD document first.", "no_document"
            )
        return (
            self.document.check(params["base_revision_id"])
            if revision
            else self.document.current()
        )

    def view(self):
        return self.document.view()

    def verify(self, doc, candidate):
        self.notify(
            {"stage": "verifying", "message": "Checking solids and STEP round-trip."}
        )
        report = self.geometry(
            "verify", {"project_dir": str(doc.folder), "snapshot": candidate}
        )
        if self.cancelled.is_set():
            raise WorkspaceError("Task cancelled before commit.", "cancelled")
        candidate["verification"] = report

    def dispatch(self, method, params):
        if method == "workspace.hello":
            return {"protocol_version": 1, **self.geometry("hello", {})}
        if method == "document.import":
            source = Path(params["path"]).resolve()
            if source.suffix.lower() not in (".step", ".stp", ".json"):
                raise WorkspaceError("Open a STEP file or an editable .cad.json file.")
            doc = Document.create(
                params.get("destination") or self.projects_dir / str(uuid4()),
                source.stem,
            )
            doc.journal("running", action="import")
            try:
                candidate = (
                    self.geometry(
                        "from_recipe",
                        {
                            "project_dir": str(doc.folder),
                            "recipe": json.loads(source.read_text(encoding="utf-8")),
                        },
                    )
                    if source.suffix.lower() == ".json"
                    else self.geometry(
                        "import_step",
                        {"project_dir": str(doc.folder), "path": str(source)},
                    )
                )
                candidate["name"] = source.stem
                self.verify(doc, candidate)
                original = doc.folder / "source" / source.name
                original.parent.mkdir(exist_ok=True)
                shutil.copy2(source, original)
                candidate["original_source"] = original.relative_to(
                    doc.folder
                ).as_posix()
                doc.commit(candidate, summary="Imported " + source.name)
                doc.journal("completed")
                self.document = doc
                return self.view()
            except Exception:
                doc.journal("failed")
                raise
        if method == "document.open":
            source = Path(params["path"])
            doc = Document(source.parent if source.is_file() else source)
            doc.current()
            warning = doc.recover()
            self.document = doc
            return {**self.view(), "recovery_message": warning}
        if method == "document.current":
            self.required(params, False)
            return self.view()
        if method == "document.save_as":
            self.required(params)
            self.document = self.document.save_as(params["destination"])
            return self.view()
        if method in ("document.undo", "document.redo"):
            self.required(params)
            self.document.move_history(
                -1 if method.endswith("undo") else 1, params["base_revision_id"]
            )
            return self.view()
        if method == "document.inspect":
            snapshot = self.required(params)
            return self.geometry(
                "inspect",
                {
                    "project_dir": str(self.document.folder),
                    "snapshot": snapshot,
                    "instance_id": params.get("instance_id"),
                },
            )
        if method == "document.export":
            snapshot = self.required(params)
            destination = Path(params["path"]).resolve()
            if destination.is_relative_to(self.document.folder):
                raise WorkspaceError(
                    "Export outside the CAD document directory to preserve its assets."
                )
            return self.geometry(
                "export",
                {
                    "project_dir": str(self.document.folder),
                    "snapshot": snapshot,
                    "path": str(destination),
                },
            )
        if method == "document.command":
            original = self.required(params)
            selected = (
                Selection.model_validate(params["selection"])
                if params.get("selection")
                else None
            )
            if selected and selected.revision_id != original["revision_id"]:
                raise WorkspaceError(
                    "The selection belongs to an older revision.", "stale_selection"
                )
            command = params["command"]
            if selected and command["instance_id"] != selected.instance_id:
                raise WorkspaceError(
                    "This edit is restricted to the selected component."
                )
            doc = self.document
            doc.journal(
                "running", action=method, base_revision_id=original["revision_id"]
            )
            try:
                candidate = self.geometry(
                    "apply",
                    {
                        "project_dir": str(doc.folder),
                        "snapshot": original,
                        "command": command,
                    },
                )
                before = {
                    p["instance_id"]: (p["asset_hash"], p["matrix"])
                    for p in original["components"]
                }
                after = {
                    p["instance_id"]: (p["asset_hash"], p["matrix"])
                    for p in candidate["components"]
                }
                if before == after:
                    raise WorkspaceError(
                        "The operation did not change the geometry.", "no_change"
                    )
                self.verify(doc, candidate)
                doc.commit(
                    candidate,
                    original["revision_id"],
                    summary=command["type"].capitalize(),
                    commands=[command],
                )
                doc.journal("completed")
                return {
                    "status": "done",
                    "message": command["type"].capitalize(),
                    "document": self.view(),
                }
            except Exception as error:
                doc.journal(getattr(error, "code", "failed"), message=str(error))
                raise
        raise WorkspaceError("Unknown document method: " + method, "method_not_found")

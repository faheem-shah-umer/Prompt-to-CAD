import argparse
import json
import os
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

from .agent import run_agent
from .contracts import Selection, WorkspaceError
from .documents import Document, write_json
from .worker_client import GeometryWorker


class Workspace:
    def __init__(self, projects_dir, notify=lambda event: None):
        self.projects_dir = Path(projects_dir)
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self.worker = GeometryWorker(self.projects_dir / ".logs", timeout=float(os.getenv("CAD_GEOMETRY_TIMEOUT", "120")))
        from . import settings
        settings.load()
        self.document = None
        self.cancelled = threading.Event()
        self.notify = notify
        self.task_deadline = None

    def geometry(self, method, params, timeout=None):
        if self.task_deadline is not None:
            remaining = self.task_deadline - time.monotonic()
            if remaining <= 0:
                raise WorkspaceError("The agent reached its ten-minute task limit.", "timeout")
            timeout = min(timeout if timeout is not None else self.worker.timeout, remaining)
        return self.worker.call(method, params, cancel=self.cancelled, progress=self.notify, timeout=timeout)

    def required(self, params, revision=True):
        if self.document is None:
            raise WorkspaceError("Open or generate a CAD document first.", "no_document")
        if revision:
            return self.document.check(params["base_revision_id"])
        return self.document.current()

    def new_document(self, params, name):
        return Document.create(params.get("destination") or self.projects_dir / str(uuid4()), name)

    def conversation(self):
        path = self.document.folder / "conversation.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []

    def chat_message(self, role, content):
        messages = self.conversation()
        messages.append({"role": role, "content": content})
        write_json(self.document.folder / "conversation.json", messages)

    def view(self):
        snapshot = self.document.view()
        snapshot["conversation"] = self.conversation()
        return snapshot

    def verify(self, doc, candidate):
        self.notify({"stage": "verifying", "message": "Checking solids and STEP round-trip."})
        report = self.geometry("verify", {"project_dir": str(doc.folder), "snapshot": candidate})
        if self.cancelled.is_set():
            raise WorkspaceError("Task cancelled before commit.", "cancelled")
        candidate["verification"] = report

    def dispatch(self, method, params):
        self.task_deadline = time.monotonic() + 600 if method in ("agent.run", "document.generate") else None
        if method == "workspace.model":
            from .settings import public
            return public()
        if method == "workspace.configure":
            from .settings import save
            configuration = save(params)
            self.worker.close()
            return configuration
        if method == "workspace.hello":
            hello = self.geometry("hello", {})
            from backend.app.llm_client import public_status
            return {"protocol_version": 1, "application_version": "0.2.0", **hello, "model": public_status()}
        if method == "document.import":
            source = Path(params["path"]).resolve()
            if source.suffix.lower() not in (".step", ".stp", ".json"):
                raise WorkspaceError("Open a STEP file or an editable .cad.json file.")
            doc = self.new_document(params, source.stem)
            doc.journal("running", action="import")
            try:
                if source.suffix.lower() == ".json":
                    candidate = self.geometry("from_recipe", {"project_dir": str(doc.folder),
                                                              "recipe": json.loads(source.read_text(encoding="utf-8"))})
                else:
                    candidate = self.geometry("import_step", {"project_dir": str(doc.folder), "path": str(source)})
                candidate["name"] = source.stem
                self.verify(doc, candidate)
                original = doc.folder / "source" / source.name
                original.parent.mkdir(exist_ok=True)
                shutil.copy2(source, original)
                candidate["original_source"] = str(original.relative_to(doc.folder)).replace("\\", "/")
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
            self.document.move_history(-1 if method.endswith("undo") else 1, params["base_revision_id"])
            return self.view()
        if method == "document.inspect":
            snapshot = self.required(params)
            return self.geometry("inspect", {"project_dir": str(self.document.folder), "snapshot": snapshot,
                                             "instance_id": params.get("instance_id")})
        if method == "document.export":
            snapshot = self.required(params)
            destination = Path(params["path"]).resolve()
            if destination.is_relative_to(self.document.folder):
                raise WorkspaceError("Export outside the native project directory to preserve its assets.")
            return self.geometry("export", {"project_dir": str(self.document.folder), "snapshot": snapshot,
                                             "path": str(destination)})
        if method == "document.generate":
            prompt = params["prompt"].strip()
            if not 5 <= len(prompt) <= 16000:
                raise WorkspaceError("Describe the design in 5–16,000 characters.")
            doc = self.new_document(params, "Generated design")
            doc.journal("running", action="generate", prompt=prompt)
            try:
                generated = self.geometry("generate", {"project_dir": str(doc.folder), "prompt": prompt}, timeout=600)
                if generated["status"] != "ready":
                    doc.journal(generated["status"])
                    return generated
                candidate = generated["snapshot"]
                doc_index = doc.index()
                doc_index["name"] = candidate.get("recipe", {}).get("name", "Generated design")
                write_json(doc.index_path, doc_index)
                self.verify(doc, candidate)
                doc.commit(candidate, summary=generated["message"], conversation=[])
                self.document = doc
                self.chat_message("user", prompt)
                self.chat_message("assistant", generated["message"])
                doc.journal("completed")
                return {"status": "done", "message": generated["message"], "document": self.view()}
            except Exception:
                doc.journal("failed")
                raise
        if method in ("document.command", "agent.run"):
            original = self.required(params)
            doc = self.document
            selected = Selection.model_validate(params["selection"]) if params.get("selection") else None
            if selected and selected.revision_id != original["revision_id"]:
                raise WorkspaceError("The selection belongs to an older revision.", "stale_selection")
            selected_id = selected.instance_id if selected else None
            if selected_id and not any(p["instance_id"] == selected_id for p in original["components"]):
                raise WorkspaceError("The selected instance no longer exists.", "stale_selection")
            doc.journal("running", action=method, base_revision_id=original["revision_id"])

            def execute(snapshot, command):
                if selected_id and command["instance_id"] != selected_id:
                    raise WorkspaceError("This edit is restricted to the selected component.")
                candidate = self.geometry("apply", {"project_dir": str(doc.folder), "snapshot": snapshot, "command": command})
                before = {part["instance_id"]: (part["asset_hash"], part["matrix"]) for part in snapshot["components"]}
                after = {part["instance_id"]: (part["asset_hash"], part["matrix"]) for part in candidate["components"]}
                if before == after:
                    raise WorkspaceError("The operation did not change the geometry.", "no_change")
                return candidate

            try:
                if method == "document.command":
                    command = params["command"]
                    candidate = execute(original, command)
                    commands, summary = [command], command["type"].capitalize()
                else:
                    prompt = params["prompt"].strip()
                    if not 1 <= len(prompt) <= 8000:
                        raise WorkspaceError("Describe the change in 1–8,000 characters.")
                    history = self.conversation()
                    self.chat_message("user", prompt)

                    def inspect(snapshot, instance_id):
                        observation = self.geometry("inspect", {"project_dir": str(doc.folder),
                                                                "snapshot": snapshot, "instance_id": instance_id})
                        if selected:
                            observation["initial_selection"] = selected.model_dump()
                            observation["initial_selection_note"] = "The index refers to the original revision; re-identify geometry after each tool."
                        return observation

                    result = run_agent(prompt, original, history, selected_id, execute, inspect,
                                       self.cancelled, self.notify)
                    self.chat_message("assistant", result["message"])
                    if result["status"] != "done" or not result["commands"]:
                        doc.journal(result["status"])
                        return {"status": result["status"], "message": result["message"], "document": self.view()}
                    candidate, commands, summary = result["snapshot"], result["commands"], result["message"]
                self.verify(doc, candidate)
                doc.commit(candidate, original["revision_id"], summary=summary, commands=commands)
                doc.journal("completed")
                return {"status": "done", "message": summary, "document": self.view()}
            except Exception as error:
                doc.journal(getattr(error, "code", "failed"), message=str(error))
                raise
        raise WorkspaceError("Unknown application method: " + method, "method_not_found")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--projects-dir", type=Path, default=Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "PromptToCAD" / "projects")
    args = parser.parse_args()
    output_lock = threading.Lock()
    state_lock = threading.Lock()
    busy = False
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cad-service")

    def send(message):
        with output_lock:
            sys.stdout.write(json.dumps(message, ensure_ascii=False, allow_nan=False) + "\n")
            sys.stdout.flush()

    workspace = Workspace(args.projects_dir, lambda event: send({"jsonrpc": "2.0", "method": "progress", "params": event}))

    def respond(request):
        nonlocal busy
        try:
            result = workspace.dispatch(request["method"], request.get("params", {}))
            reply = {"jsonrpc": "2.0", "id": request["id"], "result": result}
        except Exception as error:
            reply = {"jsonrpc": "2.0", "id": request["id"],
                     "error": {"code": -32000, "message": str(error),
                               "data": {"code": getattr(error, "code", "application_error")}}}
        with state_lock:
            busy = False
            send(reply)

    try:
        for line in sys.stdin:
            request = None
            try:
                request = json.loads(line)
                if not isinstance(request, dict) or request.get("jsonrpc") != "2.0" or "id" not in request:
                    raise WorkspaceError("Expected an identified JSON-RPC 2.0 request.", "invalid_request")
                if not isinstance(request.get("params", {}), dict):
                    raise WorkspaceError("RPC parameters must be an object.", "invalid_request")
                method = request["method"]
                if method == "workspace.cancel":
                    with state_lock:
                        workspace.cancelled.set()
                    send({"jsonrpc": "2.0", "id": request["id"], "result": {"cancellation_requested": True}})
                    continue
                if method == "workspace.shutdown":
                    workspace.cancelled.set()
                    send({"jsonrpc": "2.0", "id": request["id"], "result": {}})
                    break
                with state_lock:
                    if busy:
                        raise WorkspaceError("Another task is running. Wait or cancel it first.", "busy")
                    busy = True
                    workspace.cancelled.clear()
                executor.submit(respond, request)
            except Exception as error:
                send({"jsonrpc": "2.0", "id": request.get("id") if isinstance(request, dict) else None,
                      "error": {"code": -32600, "message": str(error), "data": {"code": getattr(error, "code", "invalid_request")}}})
    finally:
        workspace.cancelled.set()
        executor.shutdown(wait=True, cancel_futures=True)
        workspace.worker.close()


if __name__ == "__main__":
    main()

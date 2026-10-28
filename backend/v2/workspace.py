import copy
import json
import os
import sys
import time
from pathlib import Path
from uuid import uuid4

from backend.native.service import Workspace
from backend.native.documents import write_json, Document
from backend.native.contracts import WorkspaceError
from backend.app.project_lock import revision_lock
from backend.app.projects import RevisionConflict
from .auth import Connections
from .cad_tools import TOOLS, TaskTools, ToolBridge, fingerprint
from .projects import Projects
from .provider import CodexAppServer

INSTRUCTIONS = Path(__file__).with_name("CAD_INSTRUCTIONS.md").read_text(encoding="utf-8")


class WorkspaceV2(Workspace):
    def __init__(self, home, notify=lambda event: None):
        self.home = Path(home).resolve()
        super().__init__(self.home / "geometry", notify, load_model=False)
        self.projects = Projects(self.home / "projects")
        self.connections = Connections(self.home / "identity", notify)
        self.project_id = self.projects.read(self.projects.catalog)["active"]
        self.runtime = None
        self.configuration_path = self.home / "settings.json"
        self.configuration = self.projects.read(self.configuration_path) if self.configuration_path.exists() else {}
        if self.project_id:
            self.activate(self.project_id)

    def activate(self, project_id):
        project = self.projects.activate(project_id)
        self.project_id = project_id
        conversation = self.projects.conversation(project_id)
        self.document = self.projects.document(project, conversation["document_id"])
        try:
            with revision_lock(self.document.folder / ".task-lock"):
                self.document.recover()
        except RevisionConflict:
            pass
        return self.state()

    def state(self):
        return {
            **(self.projects.view(self.project_id) if self.project_id else {"catalog": self.projects.listing()}),
            "provider": self.connections.status(),
            "runtime": {"executable": self.configuration.get("codex_path", ""), "provider": "Codex App Server"},
        }

    def dispatch(self, method, params):
        writers = {"v2.task", "v2.command", "v2.script", "v2.undo", "v2.redo", "v2.restore", "v2.image_generate"}
        if method in writers and self.document:
            with revision_lock(self.document.folder / ".task-lock"):
                return self._dispatch(method, params)
        return self._dispatch(method, params)

    def _dispatch(self, method, params):
        self.task_deadline = None
        if method == "v2.state":
            return self.state()
        if method == "v2.project.create":
            return self.activate(self.projects.create(params.get("name", "Untitled project"))["project_id"])
        if method == "v2.project.open":
            return self.activate(params["project_id"])
        if method == "v2.project.update":
            project_id = params.get("project_id", self.project_id)
            values = {k: params[k] for k in ("name", "archived", "trashed") if k in params}
            if "name" in values:
                values["name"] = str(values["name"]).strip()[:120] or "Untitled project"
            self.projects.update(project_id, **values)
            return self.state()
        if method == "v2.conversation.new":
            self.projects.new_conversation(self.project_id, params.get("document_id"))
            return self.activate(self.project_id)
        if method == "v2.conversation.open":
            pid = params.get("project_id", self.project_id)
            chat = self.projects.conversation(pid, params["conversation_id"])
            self.projects.update(
                pid, active_conversation_id=chat["conversation_id"], active_document_id=chat["document_id"]
            )
            return self.activate(pid)
        if method == "v2.document.open":
            project = self.projects.project(self.project_id)
            did = params["document_id"]
            self.projects.document(project, did)
            chats = [self.projects.conversation(self.project_id, cid) for cid in project["conversations"]]
            chat = next(
                (
                    c
                    for c in reversed(chats)
                    if c["document_id"] == did and not c.get("archived") and not c.get("trashed")
                ),
                None,
            )
            if chat:
                self.projects.update(
                    self.project_id, active_document_id=did, active_conversation_id=chat["conversation_id"]
                )
            else:
                self.projects.new_conversation(self.project_id, did)
            return self.activate(self.project_id)
        if method == "v2.conversation.restart_session":
            chat = self.projects.conversation(self.project_id)
            chat["provider_session"] = None
            self.projects.save_conversation(self.project_id, chat)
            return self.state()
        if method == "v2.restore":
            self.document.restore(params["revision_id"], params["base_revision_id"])
            return self.state()
        if method == "v2.conversation.update":
            pid = params.get("project_id", self.project_id)
            chat = self.projects.conversation(pid, params["conversation_id"])
            for key in ("title", "archived", "trashed"):
                if key in params:
                    chat[key] = str(params[key])[:120] if key == "title" else bool(params[key])
            self.projects.save_conversation(pid, chat)
            return self.state()
        if method == "v2.reference.add":
            if not self.project_id:
                raise WorkspaceError("Create a project before adding references.")
            return self.projects.reference(self.project_id, params["path"])
        if method == "provider.status":
            return self.connections.status()
        if method == "provider.login":
            return self.connections.begin(params.get("account_id"))
        if method == "provider.cancel_login":
            return self.connections.cancel_login()
        if method == "provider.api_key":
            return self.connections.api_key(params["key"])
        if method == "provider.select":
            return self.connections.select(params["account_id"])
        if method == "provider.disconnect":
            return self.connections.disconnect()
        if method == "provider.models":
            return self.connections.models()
        if method == "provider.configure":
            path = str(params.get("codex_path", "")).strip()
            if path and not Path(path).is_file():
                raise WorkspaceError("Select the installed Codex executable.")
            self.configuration["codex_path"] = path
            write_json(self.configuration_path, self.configuration)
            return self.state()
        if method == "provider.probe":
            runtime = CodexAppServer(
                self.home / "runtime" / "probe", executable=self.configuration.get("codex_path") or None
            )
            try:
                return {
                    "connected": True,
                    "server": runtime.info,
                    "authenticated": False,
                    "message": "Live App Server handshake succeeded. Account/model inference remains unverified.",
                }
            finally:
                runtime.close()
        if method == "image.configure":
            with self.connections.vault.lock, revision_lock(self.connections.vault.folder):
                data = self.connections.vault.read()
                key = str(params.get("key", "")).strip()
                if key and len(key) < 20:
                    raise WorkspaceError("Enter a valid Tripo API key.")
                data["tripo_key"] = key
                self.connections.vault.write(data)
            return {"connected": bool(key), "billing": "Separate Tripo API credits"}
        if method == "image.status":
            with self.connections.vault.lock:
                connected = bool(self.connections.vault.read().get("tripo_key"))
            return {
                "connected": connected,
                "provider": "Tripo v3",
                "billing": "Separate Tripo API credits",
                "live_generation_verified": False,
            }
        if method == "v2.image_generate":
            return self.generate_image(params)
        if method == "v2.import":
            source = Path(params["path"]).resolve()
            if source.suffix.lower() not in (".step", ".stp", ".json", ".glb", ".stl", ".obj", ".ply"):
                raise WorkspaceError("Choose a supported engineering CAD or visual mesh file.")
            if source.stat().st_size > 100 * 1024 * 1024:
                raise WorkspaceError("This build supports source files up to 100 MB.")
            if not self.project_id:
                self.activate(self.projects.create(source.stem)["project_id"])
            doc = (
                self.document
                if self.document.index()["cursor"] < 0
                else Document.create(
                    self.projects.project_path(self.project_id) / "documents" / uuid4().hex[:16], source.stem
                )
            )
            if source.suffix.lower() in (".glb", ".stl", ".obj", ".ply"):
                if "mm_per_unit" not in params:
                    raise WorkspaceError("Specify source mesh units before import.")
                candidate = self.geometry(
                    "import_mesh",
                    {"project_dir": str(doc.folder), "path": str(source), "mm_per_unit": params["mm_per_unit"]},
                )
            elif source.suffix.lower() == ".json":
                candidate = self.geometry(
                    "from_recipe",
                    {"project_dir": str(doc.folder), "recipe": json.loads(source.read_text(encoding="utf-8"))},
                )
            else:
                candidate = self.geometry("import_step", {"project_dir": str(doc.folder), "path": str(source)})
            self.verify(doc, candidate)
            import hashlib
            import shutil

            original = doc.folder / "source" / source.name
            original.parent.mkdir(exist_ok=True)
            shutil.copyfile(source, original)
            candidate.update(
                original_source="source/" + original.name,
                original_source_sha256=hashlib.sha256(original.read_bytes()).hexdigest(),
            )
            index = doc.index()
            index["name"] = source.stem
            write_json(doc.index_path, index)
            doc.commit(candidate, summary="Imported " + source.name)
            self.document = doc
            self.projects.adopt(self.project_id, doc)
            return self.state()
        if method == "v2.open_native":
            super().dispatch("document.open", params)
            document = self.document
            if not self.project_id:
                self.activate(self.projects.create(document.index()["name"])["project_id"])
            self.projects.adopt(self.project_id, document)
            return self.activate(self.project_id)
        if method in ("v2.command", "v2.script"):
            snapshot = self.state()["document"] if self.document.index()["cursor"] < 0 else self.required(params)
            tools = TaskTools(self, self.document, snapshot, params.get("selection"), self.project_id, uuid4().hex)
            if method == "v2.command":
                tools.call("cad_apply", {"candidate_id": tools.candidate_id, "command": params["command"]})
            else:
                tools.call(
                    "cad_script",
                    {
                        "candidate_id": tools.candidate_id,
                        "source": params["source"],
                        "parameters": params.get("parameters", {}),
                        "instance_id": params.get("instance_id"),
                    },
                )
            report = tools.call("cad_validate", {"candidate_id": tools.candidate_id})
            tools.candidate["verification"] = report
            self.document.commit(
                tools.candidate,
                snapshot["revision_id"],
                summary=params.get("command", {}).get("type", "CAD script"),
                commands=tools.commands,
            )
            return self.state()
        if method in ("v2.undo", "v2.redo"):
            super().dispatch("document.undo" if method.endswith("undo") else "document.redo", params)
            return self.state()
        if method == "v2.export":
            return super().dispatch("document.export", params)
        if method == "v2.measure":
            snapshot = self.required(params)
            return self.geometry(
                "measure",
                {
                    "project_dir": str(self.document.folder),
                    "snapshot": snapshot,
                    "first": params["first"],
                    "second": params["second"],
                },
            )
        if method == "v2.inspect":
            return super().dispatch("document.inspect", params)
        if method == "v2.task":
            return self.run_task(params)
        if method == "workspace.hello":
            return {
                **super().dispatch(method, params),
                "application_version": "0.3.0",
                "product_name": "Prompt to CAD V2",
            }
        raise WorkspaceError("Unknown V2 method: " + method, "method_not_found")

    def run_task(self, params):
        if not self.project_id:
            raise WorkspaceError("Create a project first.")
        prompt = str(params.get("prompt", "")).strip()
        if not 1 <= len(prompt) <= 16000:
            raise WorkspaceError("Describe the task in 1–16,000 characters.")
        model = str(params.get("model", "")).strip()
        if not model:
            raise WorkspaceError("Discover and select a model in the conversation panel.", "model_required")
        account_id, account = self.connections.credential()
        state = self.projects.view(self.project_id)
        original = state["document"]
        if params.get("base_revision_id") != original.get("revision_id"):
            raise WorkspaceError(
                "The document changed before task submission. Inspect and submit again.", "revision_conflict"
            )
        images = copy.deepcopy(params.get("attachments", []))
        viewport = (
            self.projects.reference(self.project_id, params["viewport_path"]) if params.get("viewport_path") else None
        )
        # Only previously imported application-owned references are accepted.
        reference_root = (self.projects.project_path(self.project_id) / "references").resolve()
        for reference in images:
            if not Path(reference["path"]).resolve().is_relative_to(reference_root):
                raise WorkspaceError("Attach reference images through the application first.")
            self.projects.check_reference(reference)
        task = {
            "task_id": uuid4().hex,
            "document_id": original["document_id"],
            "conversation_id": state["conversation"]["conversation_id"],
            "base_revision_id": original.get("revision_id"),
            "status": "running",
            "prompt": prompt,
            "attachments": images,
            "submitted_selection": copy.deepcopy(params.get("selection")),
            "started_at": time.time(),
            "model": model,
            "provider_account": account_id,
        }
        tools = TaskTools(self, self.document, original, task["submitted_selection"], self.project_id, task["task_id"])
        tools.viewport = viewport
        tools.references = images
        tools.allow_images = params.get("authorize_image_billing") is True
        task["viewport"] = viewport
        task["submitted_selection"] = tools.selection
        conversation = state["conversation"]
        conversation["messages"].append(
            {
                "role": "user",
                "content": prompt,
                "selection": tools.selection,
                "attachments": images,
                "task_id": task["task_id"],
            }
        )
        conversation["tasks"].append(task["task_id"])
        if conversation["title"] == "New conversation":
            conversation["title"] = prompt[:60]
        self.projects.save_conversation(self.project_id, conversation)
        self.projects.task(self.project_id, task)
        bridge = ToolBridge(tools)
        self.task_deadline = time.monotonic() + 600
        self.document.journal(
            "running", action="codex", task_id=task["task_id"], base_revision_id=original.get("revision_id")
        )
        try:
            source_root = Path(__file__).resolve().parents[2]
            # Use the real interpreter, avoiding the Windows venv launcher process.
            python = getattr(sys, "_base_executable", sys.executable)
            paths = [str(source_root)] + [p for p in sys.path if "site-packages" in p]
            mcp = {
                "default_tools_approval_mode": "approve",
                "enabled_tools": [t["name"] for t in TOOLS],
                "command": python,
                "args": ["-B", "-m", "backend.v2.mcp_server"],
                "required": True,
                "env": {
                    "PYTHONPATH": os.pathsep.join(paths),
                    "PROMPTCAD_TOOL_URL": bridge.url,
                    "PROMPTCAD_TOOL_TOKEN": bridge.token,
                },
                "startup_timeout_sec": 30,
                "tool_timeout_sec": 660,
            }
            self.notify(
                {
                    "stage": "connecting",
                    "message": "Starting Codex App Server · "
                    + ("ChatGPT plan" if account["mode"] == "chatgpt" else "API billing"),
                }
            )
            self.runtime = CodexAppServer(
                self.home / "runtime" / account_id,
                self.configuration.get("codex_path") or None,
                account.get("access_token", account.get("api_key")),
                account["mode"],
                mcp,
            )
            session = (
                conversation.get("provider_session") if conversation.get("provider_account") == account_id else None
            )
            resuming = bool(session)
            try:
                session = self.runtime.start_thread(INSTRUCTIONS, model, session)
            except WorkspaceError:
                if not session:
                    raise
                # Only a missing/expired runtime session should start a replacement.
                self.notify(
                    {
                        "stage": "session",
                        "message": "The prior provider session could not resume. Its local conversation is preserved; reconnect to start a new session.",
                    }
                )
                raise
            conversation.update(provider_session=session, provider_account=account_id)
            self.projects.save_conversation(self.project_id, conversation)
            context = json.dumps(tools.context(), allow_nan=False)
            if not resuming:
                history = "\n".join(m["role"] + ": " + m["content"] for m in conversation["messages"][:-1][-20:])[
                    -24000:
                ]
                context += "\nPrior local conversation (context data, may reference older revisions):\n" + history
            text = "Current application state (fresh for this turn):\n" + context + "\n\nUser request:\n" + prompt
            message = self.runtime.run(
                text,
                model,
                self.cancelled,
                self.notify,
                [r["path"] for r in images] + ([viewport["path"]] if viewport else []),
                timeout=max(1, self.task_deadline - time.monotonic()),
            )
            if self.cancelled.is_set():
                raise WorkspaceError("Task cancelled before acceptance.", "cancelled")
            if tools.commands:
                self.notify(
                    {"stage": "verifying", "message": "Checking resulting solids, export and unrelated components."}
                )
                report = tools.call("cad_validate", {"candidate_id": tools.candidate_id})
                tools.candidate["verification"] = report
                tools.candidate["task_id"] = task["task_id"]
                self.document.commit(
                    tools.candidate,
                    original.get("revision_id"),
                    summary=message[:3000] or "Codex CAD task",
                    commands=tools.commands,
                )
                task.update(
                    result_revision_id=self.document.current()["revision_id"],
                    validation=report,
                    affected_components=[
                        p["instance_id"]
                        for p in tools.candidate["components"]
                        if fingerprint(original).get(p["instance_id"]) != fingerprint(tools.candidate)[p["instance_id"]]
                    ],
                )
            if not tools.commands:
                message += "\n\nApplication: no geometry revision was created by this turn."
            task.update(
                status="completed" if tools.commands else "completed_no_change",
                message=message,
                completed_at=time.time(),
            )
            conversation["messages"].append(
                {
                    "role": "assistant",
                    "content": message,
                    "task_id": task["task_id"],
                    "change": {
                        k: task[k] for k in ("result_revision_id", "validation", "affected_components") if k in task
                    },
                }
            )
            self.document.journal("completed", task_id=task["task_id"])
        except Exception as error:
            task.update(
                status="cancelled" if self.cancelled.is_set() else "failed",
                message=str(error),
                completed_at=time.time(),
            )
            conversation["messages"].append({"role": "system", "content": str(error), "task_id": task["task_id"]})
            self.document.journal(task["status"], task_id=task["task_id"])
            raise
        finally:
            tools.closed = True
            bridge.close()
            if self.runtime:
                self.runtime.close()
                self.runtime = None
            self.projects.task(self.project_id, task)
            self.projects.save_conversation(self.project_id, conversation)
            self.task_deadline = None
        return {**self.state(), "task": task}

    def reconstruct_image(self, reference, target_size_mm, parent_task_id=None, resume=None):
        references = (self.projects.project_path(self.project_id) / "references").resolve()
        if not Path(reference["path"]).resolve().is_relative_to(references):
            raise WorkspaceError("Attach the reference image through the application first.")
        self.projects.check_reference(reference)
        with self.connections.vault.lock:
            key = self.connections.vault.read().get("tripo_key")
        if not key:
            raise WorkspaceError(
                "Connect a user-supplied Tripo key in Account settings. This uses separate API credits.",
                "image_not_connected",
            )
        from .image_backend import Tripo

        task_id = uuid4().hex
        source = self.document.folder / "source" / (task_id + ".glb")
        record_path = self.projects.project_path(self.project_id) / "tasks" / (task_id + ".json")
        context = {
            "task_id": task_id,
            "parent_task_id": parent_task_id,
            "document_id": self.document.index()["document_id"],
            "conversation_id": self.projects.conversation(self.project_id)["conversation_id"],
        }
        generation = Tripo(key, self.cancelled, self.notify).generate(
            reference, target_size_mm, source, record_path, resume=resume, context=context
        )
        candidate = self.geometry(
            "import_mesh", {"project_dir": str(self.document.folder), "path": str(source), "mm_per_unit": 1}
        )
        bounds = [p["metrics"]["bounds_mm"] for p in candidate["components"]]
        largest = max(max(b[1][axis] for b in bounds) - min(b[0][axis] for b in bounds) for axis in range(3))
        candidate = self.geometry(
            "scale_mesh_scene",
            {"project_dir": str(self.document.folder), "snapshot": candidate, "factor": target_size_mm / largest},
        )
        generation.update(original_glb="source/" + source.name, status="candidate")
        self.projects.task(self.project_id, generation)
        return candidate, generation

    def generate_image(self, params):
        if params.get("authorize_separate_billing") is not True:
            raise WorkspaceError(
                "Image reconstruction requires an explicit choice to use separately billed Tripo credits."
            )
        if not self.project_id:
            raise WorkspaceError("Create a project before image reconstruction.")
        original = self.state()["document"]
        if original.get("revision_id") != params.get("base_revision_id"):
            raise WorkspaceError("The document changed before generation.", "revision_conflict")
        self.task_deadline = time.monotonic() + 600
        try:
            generated, generation = self.reconstruct_image(params["reference"], params["target_size_mm"])
            candidate = copy.deepcopy(original)
            candidate["components"].extend(generated["components"])
            candidate.setdefault("image_generations", []).append(generation)
            self.verify(self.document, candidate)
            self.document.commit(
                candidate,
                original.get("revision_id"),
                summary="Image reconstruction · approximate visual mesh",
                commands=[{"type": "image_generation", "task_id": generation["task_id"]}],
            )
            generation.update(
                status="completed",
                result_revision_id=self.document.current()["revision_id"],
                base_revision_id=original.get("revision_id"),
            )
            self.projects.task(self.project_id, generation)
            conversation = self.projects.conversation(self.project_id)
            conversation["tasks"].append(generation["task_id"])
            conversation["messages"].append(
                {
                    "role": "assistant",
                    "content": "Created an approximate visual mesh from the attached image. Longest dimension: "
                    + str(params["target_size_mm"])
                    + " mm (user supplied). Other dimensions and hidden geometry are inferred. Tripo credits are separate from Codex usage.",
                    "attachments": [params["reference"]],
                    "task_id": generation["task_id"],
                }
            )
            self.projects.save_conversation(self.project_id, conversation)
            return {**self.state(), "image_task": generation}
        finally:
            self.task_deadline = None

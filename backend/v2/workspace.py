import copy
import json
import os
import sys
import threading
import time
from pathlib import Path
from uuid import uuid4

from backend.native.project_lock import revision_lock
from backend.native.project_lock import RevisionConflict
from backend.native.contracts import WorkspaceError
from backend.native.documents import Document, write_json
from backend.native.workspace import Workspace

from .auth import Connections
from .cad_tools import TOOLS, TaskTools, ToolBridge, fingerprint
from .projects import Projects
from .provider import CodexAppServer, discover_executable
from .usage import allowance, merge_allowance, tokens

INSTRUCTIONS = (
    Path(__file__).with_name("CAD_INSTRUCTIONS.md").read_text(encoding="utf-8")
)


class WorkspaceV2(Workspace):
    def __init__(
        self, home, notify=lambda event: None, identity_home=None, projects_dir=None
    ):
        self.home = Path(home).resolve()
        self.active_task = None
        self.task_state = "disconnected"
        self.acceptance_lock = threading.RLock()
        self.output = notify
        super().__init__(self.home / "geometry", self.emit)
        self.projects = Projects(
            Path(projects_dir) if projects_dir else self.home / "projects"
        )
        self.provider_usage = {
            "available": False,
            "message": "Refresh to check reported allowance.",
        }
        self.usage_account = None
        self.token_usage = {}
        self.connections = Connections(
            Path(identity_home) if identity_home else self.home / "identity", self.emit
        )
        self.project_id = self.projects.read(self.projects.catalog)["active"]
        self.runtime = None
        self.configuration_path = self.home / "settings.json"
        self.configuration = (
            self.projects.read(self.configuration_path)
            if self.configuration_path.exists()
            else {}
        )
        self.startup_notice = ""
        if self.project_id:
            try:
                self.activate(self.project_id)
            except (OSError, json.JSONDecodeError, WorkspaceError):
                self.project_id = None
                self.document = None
                self.startup_notice = (
                    "The last project could not be opened. Open another project or restore its files. "
                    "Your project catalog and saved files have not been removed."
                )

    def emit(self, event):
        event = dict(event)
        if event.get("stage") == "usage":
            if event.get("kind") == "tokens":
                self.token_usage = tokens(event.get("observation", {}))
                event["tokens"] = self.token_usage
            elif event.get("kind") == "allowance":
                self.provider_usage = merge_allowance(
                    self.provider_usage
                    if self.active_task
                    and self.usage_account == self.active_task.get("provider_account")
                    else {},
                    event.get("observation", {}),
                )
                self.usage_account = (
                    self.active_task.get("provider_account")
                    if self.active_task
                    else None
                )
                event["usage"] = self.provider_usage
            event.pop("observation", None)
        stages = {
            "connecting": "connecting",
            "agent_running": "running",
            "clarification": "waiting_for_input",
            "verifying": "running",
        }
        if event.get("stage") in stages:
            event["state"] = stages[event["stage"]]
        if "state" in event:
            self.task_state = event["state"]
        if self.active_task:
            task = self.active_task
            event.update(
                task_id=task["task_id"],
                conversation_id=task["conversation_id"],
                document_id=task["document_id"],
            )
            if event.get("stage") not in (
                "assistant_delta",
                "assistant_message",
                "candidate",
                "usage",
            ):
                task.setdefault("activity", []).append(
                    {k: event[k] for k in ("stage", "state", "message") if k in event}
                )
        self.output(event)

    def cancel(self):
        with self.acceptance_lock:
            self.cancelled.set()
            if self.active_task:
                self.emit(
                    {
                        "stage": "task_state",
                        "state": "cancelling",
                        "message": "Stopping; unaccepted changes will be discarded.",
                    }
                )

    def activate(self, project_id):
        project = self.projects.project(project_id)
        conversation = self.projects.conversation(project_id)
        document = self.projects.document(project, conversation["document_id"])
        document.index()
        try:
            with revision_lock(document.folder / ".task-lock"):
                document.recover()
        except RevisionConflict:
            pass
        # Validate before changing the active project or replacing the current document.
        self.projects.view(project_id)
        self.projects.activate(project_id)
        self.project_id = project_id
        self.document = document
        self.startup_notice = ""
        return self.state()

    def state(self):
        provider = self.connections.status()
        active = provider.get("active") or {}
        if (
            active.get("connected")
            and active.get("id") == self.usage_account
            and self.usage_account
        ):
            provider["usage"] = self.provider_usage
        return {
            **(
                self.projects.view(self.project_id)
                if self.project_id
                else {"catalog": self.projects.listing()}
            ),
            "provider": provider,
            "projects_root": str(self.projects.folder),
            "startup_notice": self.startup_notice,
            "task_state": self.task_state
            if self.active_task
            or self.task_state
            in (
                "completed",
                "completed_no_change",
                "cancelled",
                "failed",
                "usage_limit",
            )
            else self.connections.status()["state"],
            "runtime": {
                "executable": discover_executable(self.configuration.get("codex_path"))
                or "",
                "provider": "Codex App Server",
            },
        }

    def dispatch(self, method, params):
        writers = {
            "v2.task",
            "v2.command",
            "v2.script",
            "v2.undo",
            "v2.redo",
            "v2.restore",
        }
        if method in writers and self.document:
            with revision_lock(self.document.folder / ".task-lock"):
                try:
                    return self._dispatch(method, params)
                except WorkspaceError as error:
                    if method == "v2.task":
                        self.emit(
                            {
                                "stage": "task_state",
                                "state": "usage_limit"
                                if error.code == "usage_limit"
                                else "cancelled"
                                if error.code == "cancelled"
                                else "failed",
                                "message": str(error),
                            }
                        )
                    raise
        return self._dispatch(method, params)

    def _dispatch(self, method, params):
        self.task_deadline = None
        if method == "v2.state":
            return self.state()
        if method == "v2.project.create":
            return self.activate(
                self.projects.create(params.get("name", "Untitled project"))[
                    "project_id"
                ]
            )
        if method == "v2.project.open":
            return self.activate(params["project_id"])
        if method == "v2.project.update":
            project_id = params.get("project_id", self.project_id)
            values = {
                k: params[k] for k in ("name", "archived", "trashed") if k in params
            }
            if "name" in values:
                values["name"] = str(values["name"]).strip()[:120] or "Untitled project"
            self.projects.update(project_id, **values)
            return self.state()
        if method == "v2.conversation.new":
            if not self.project_id:
                raise WorkspaceError(
                    "Create or open a project before starting a conversation.",
                    "project_required",
                )
            self.projects.new_conversation(self.project_id, params.get("document_id"))
            return self.activate(self.project_id)
        if method == "v2.conversation.open":
            pid = params.get("project_id", self.project_id)
            chat = self.projects.conversation(pid, params["conversation_id"])
            self.projects.update(
                pid,
                active_conversation_id=chat["conversation_id"],
                active_document_id=chat["document_id"],
            )
            return self.activate(pid)
        if method == "v2.document.open":
            project = self.projects.project(self.project_id)
            did = params["document_id"]
            self.projects.document(project, did)
            chats = [
                self.projects.conversation(self.project_id, cid)
                for cid in project["conversations"]
            ]
            chat = next(
                (
                    c
                    for c in reversed(chats)
                    if c["document_id"] == did
                    and not c.get("archived")
                    and not c.get("trashed")
                ),
                None,
            )
            if chat:
                self.projects.update(
                    self.project_id,
                    active_document_id=did,
                    active_conversation_id=chat["conversation_id"],
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
                    chat[key] = (
                        str(params[key])[:120] if key == "title" else bool(params[key])
                    )
            self.projects.save_conversation(pid, chat)
            return self.state()
        if method == "provider.status":
            return self.state()["provider"]
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
        if method == "provider.usage":
            return self.read_usage()
        if method == "provider.configure":
            path = str(params.get("codex_path", "")).strip()
            if path and not Path(path).is_file():
                raise WorkspaceError("Select the installed Codex executable.")
            self.configuration["codex_path"] = path
            write_json(self.configuration_path, self.configuration)
            return self.state()
        if method == "provider.probe":
            runtime = CodexAppServer(
                self.home / "runtime" / "probe",
                executable=self.configuration.get("codex_path") or None,
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
        if method == "v2.import":
            source = Path(params["path"]).resolve()
            if source.suffix.lower() not in (
                ".step",
                ".stp",
                ".json",
                ".glb",
                ".stl",
                ".obj",
                ".ply",
            ):
                raise WorkspaceError(
                    "Choose a supported engineering CAD or visual mesh file."
                )
            if source.stat().st_size > 100 * 1024 * 1024:
                raise WorkspaceError("This build supports source files up to 100 MB.")
            if not self.project_id:
                self.activate(self.projects.create(source.stem)["project_id"])
            doc = (
                self.document
                if self.document.index()["cursor"] < 0
                else Document.create(
                    self.projects.project_path(self.project_id)
                    / "documents"
                    / uuid4().hex[:16],
                    source.stem,
                )
            )
            if source.suffix.lower() in (".glb", ".stl", ".obj", ".ply"):
                if "mm_per_unit" not in params:
                    raise WorkspaceError("Specify source mesh units before import.")
                candidate = self.geometry(
                    "import_mesh",
                    {
                        "project_dir": str(doc.folder),
                        "path": str(source),
                        "mm_per_unit": params["mm_per_unit"],
                    },
                )
            elif source.suffix.lower() == ".json":
                candidate = self.geometry(
                    "from_recipe",
                    {
                        "project_dir": str(doc.folder),
                        "recipe": json.loads(source.read_text(encoding="utf-8")),
                    },
                )
            else:
                candidate = self.geometry(
                    "import_step", {"project_dir": str(doc.folder), "path": str(source)}
                )
            self.verify(doc, candidate)
            import hashlib
            import shutil

            original = doc.folder / "source" / source.name
            original.parent.mkdir(exist_ok=True)
            shutil.copyfile(source, original)
            candidate.update(
                original_source="source/" + original.name,
                original_source_sha256=hashlib.sha256(
                    original.read_bytes()
                ).hexdigest(),
            )
            index = doc.index()
            index["name"] = source.stem
            write_json(doc.index_path, index)
            doc.commit(candidate, summary="Imported " + source.name)
            self.document = doc
            self.projects.adopt(self.project_id, doc)
            return self.state()
        if method == "v2.open_native":
            folder = Path(params["path"]).resolve()
            if (folder / "workspace.json").is_file():
                return self.activate(self.projects.import_project(folder))
            super().dispatch("document.open", params)
            document = self.document
            if not self.project_id:
                self.activate(
                    self.projects.create(document.index()["name"])["project_id"]
                )
            self.projects.adopt(self.project_id, document)
            return self.activate(self.project_id)
        if method in ("v2.command", "v2.script"):
            snapshot = (
                self.state()["document"]
                if self.document.index()["cursor"] < 0
                else self.required(params)
            )
            tools = TaskTools(
                self,
                self.document,
                snapshot,
                params.get("selection"),
                self.project_id,
                uuid4().hex,
            )
            if method == "v2.command":
                tools.call(
                    "cad_apply",
                    {"candidate_id": tools.candidate_id, "command": params["command"]},
                )
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
            super().dispatch(
                "document.undo" if method.endswith("undo") else "document.redo", params
            )
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
                "application_version": "0.4.0",
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
            raise WorkspaceError(
                "Discover and select a model in the conversation panel.",
                "model_required",
            )
        account_id, account = self.connections.credential()
        state = self.projects.view(self.project_id)
        original = state["document"]
        if params.get("base_revision_id") != original.get("revision_id"):
            raise WorkspaceError(
                "The document changed before task submission. Inspect and submit again.",
                "revision_conflict",
            )
        if params.get("attachments"):
            raise WorkspaceError(
                "This release accepts text requests and internal viewport observations only."
            )
        viewport = (
            self.projects.reference(self.project_id, params["viewport_path"])
            if params.get("viewport_path")
            else None
        )
        task_id = str(params.get("task_id") or uuid4().hex)
        if len(task_id) != 32 or any(c not in "0123456789abcdef" for c in task_id):
            raise WorkspaceError("Invalid task submission identifier.")
        if (
            self.projects.project_path(self.project_id) / "tasks" / (task_id + ".json")
        ).exists():
            raise WorkspaceError(
                "This submission has already been received. Reopen the conversation to inspect its outcome.",
                "duplicate_submission",
            )
        task = {
            "task_id": task_id,
            "document_id": original["document_id"],
            "conversation_id": state["conversation"]["conversation_id"],
            "base_revision_id": original.get("revision_id"),
            "status": "running",
            "prompt": prompt,
            "submitted_selection": copy.deepcopy(params.get("selection")),
            "started_at": time.time(),
            "model": model,
            "provider_account": account_id,
        }
        tools = TaskTools(
            self,
            self.document,
            original,
            task["submitted_selection"],
            self.project_id,
            task["task_id"],
        )
        tools.viewport = viewport
        task["viewport"] = viewport
        task["submitted_selection"] = tools.selection
        conversation = state["conversation"]
        conversation["messages"].append(
            {
                "role": "user",
                "content": prompt,
                "selection": tools.selection,
                "task_id": task["task_id"],
            }
        )
        conversation["tasks"].append(task["task_id"])
        if conversation["title"] == "New conversation":
            conversation["title"] = prompt[:60]
        self.projects.save_conversation(self.project_id, conversation)
        self.projects.task(self.project_id, task)
        self.active_task = task
        bridge = None
        self.task_deadline = time.monotonic() + 600
        self.document.journal(
            "running",
            action="codex",
            task_id=task["task_id"],
            base_revision_id=original.get("revision_id"),
        )
        try:
            bridge = ToolBridge(tools)
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
                    + (
                        "ChatGPT plan"
                        if account["mode"] == "chatgpt"
                        else "API billing"
                    ),
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
                conversation.get("provider_session")
                if conversation.get("provider_account") == account_id
                else None
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
                history = "\n".join(
                    m["role"] + ": " + m["content"]
                    for m in conversation["messages"][:-1][-20:]
                )[-24000:]
                context += (
                    "\nPrior local conversation (context data, may reference older revisions):\n"
                    + history
                )
            text = (
                "Current application state (fresh for this turn):\n"
                + context
                + "\n\nUser request:\n"
                + prompt
            )
            self.token_usage = conversation.get("token_usage", {})
            message = self.runtime.run(
                text,
                model,
                self.cancelled,
                self.notify,
                [viewport["path"]] if viewport else [],
                timeout=max(1, self.task_deadline - time.monotonic()),
            )
            if self.cancelled.is_set():
                raise WorkspaceError("Task cancelled before acceptance.", "cancelled")
            if tools.commands:
                self.notify(
                    {
                        "stage": "verifying",
                        "message": "Checking resulting solids, export and unrelated components.",
                    }
                )
                report = tools.call(
                    "cad_validate", {"candidate_id": tools.candidate_id}
                )
                tools.candidate["verification"] = report
                tools.candidate["task_id"] = task["task_id"]
                with self.acceptance_lock:
                    if self.cancelled.is_set():
                        raise WorkspaceError(
                            "Task cancelled before acceptance.", "cancelled"
                        )
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
                        if fingerprint(original).get(p["instance_id"])
                        != fingerprint(tools.candidate)[p["instance_id"]]
                    ],
                )
            if not tools.commands:
                message += (
                    "\n\nApplication: no geometry revision was created by this turn."
                )
            task.update(
                status="completed" if tools.commands else "completed_no_change",
                message=message,
                completed_at=time.time(),
            )
            conversation["messages"].append(
                {
                    "role": "assistant",
                    "content": message,
                    "activity": task.get("activity", []),
                    "elapsed_seconds": max(
                        0, task["completed_at"] - task["started_at"]
                    ),
                    "task_id": task["task_id"],
                    "change": {
                        k: task[k]
                        for k in (
                            "result_revision_id",
                            "validation",
                            "affected_components",
                        )
                        if k in task
                    },
                }
            )
            self.document.journal("completed", task_id=task["task_id"])
        except Exception as error:
            task.update(
                status="cancelled"
                if self.cancelled.is_set()
                else "usage_limit"
                if getattr(error, "code", "") == "usage_limit"
                else "failed",
                message=str(error),
                completed_at=time.time(),
            )
            conversation["messages"].append(
                {
                    "role": "system",
                    "content": str(error),
                    "task_id": task["task_id"],
                    "activity": task.get("activity", []),
                    "elapsed_seconds": max(
                        0, task["completed_at"] - task["started_at"]
                    ),
                }
            )
            self.document.journal(task["status"], task_id=task["task_id"])
            raise
        finally:
            with tools.lock:
                tools.closed = True
            if bridge:
                bridge.close()
            if self.runtime:
                self.runtime.close()
                self.runtime = None
            self.projects.task(self.project_id, task)
            conversation["token_usage"] = self.token_usage
            self.projects.save_conversation(self.project_id, conversation)
            self.task_deadline = None
            self.emit(
                {
                    "stage": "task_state",
                    "state": task["status"],
                    "message": task.get("message", "")[:300],
                }
            )
            self.active_task = None
        return {**self.state(), "task": task}

    def read_usage(self):
        account_id, account = self.connections.credential()
        usage = {
            "available": False,
            "message": "API billing is separate. View costs in the API usage dashboard.",
        }
        if account["mode"] == "chatgpt":
            runtime = None
            try:
                runtime = CodexAppServer(
                    self.home / "runtime/usage",
                    self.configuration.get("codex_path") or None,
                    account.get("access_token"),
                    account["mode"],
                )
                usage = allowance(
                    runtime.request("account/rateLimits/read", {}, timeout=15)
                )
            except WorkspaceError:
                usage = {
                    "available": False,
                    "message": "This authorized connection does not report allowance. Open provider usage for current limits.",
                }
            finally:
                if runtime:
                    runtime.close()
        self.provider_usage, self.usage_account = usage, account_id
        return {"usage": usage}

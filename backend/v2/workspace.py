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
from backend.native.contracts import CAD_TURN_TIMEOUT_SECONDS, WorkspaceError
from backend.native.documents import Document, write_json
from backend.native.workspace import Workspace
from backend.native.runtime_identity import RuntimeIdentity

from .auth import Connections, provider_of
from .claude_provider import (CLAUDE_AGENT, ClaudeCodeRuntime, ClaudeProviderOptions, auth_status, describe,
                              discover_claude, open_sign_in)
from .cad_tools import TOOLS, TaskTools, ToolBridge, fingerprint
from .projects import Projects
from .provider import CODEX_AGENT, CodexAppServer, CodexProviderOptions, discover_executable
from .provider_options import ProviderOptions, capture_effort
from .usage import allowance, merge_allowance, tokens

INSTRUCTIONS = (
    Path(__file__).with_name("CAD_INSTRUCTIONS.md").read_text(encoding="utf-8")
)

# Requests that only change which project/conversation is shown; they may run while a task works.
BACKGROUND_NAVIGATION = {
    "v2.state",
    "v2.project.open",
    "v2.project.create",
    "v2.conversation.open",
    "v2.conversation.new",
    "v2.document.open",
    "v2.projects.refresh",
}


class WorkspaceV2(Workspace):
    def __init__(
        self, home, notify=lambda event: None, identity_home=None, projects_dir=None
    ):
        self.home = Path(home).resolve()
        self.application_runtime = RuntimeIdentity("backend", tools=TOOLS, instructions=INSTRUCTIONS)
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
        self.capability_cache = {}
        self.note_cache = {}
        self.claude_code_auth = None
        self.provider_adapters: dict[str, ProviderOptions] = {
            "codex": CodexProviderOptions(),
            "claude": ClaudeProviderOptions(),
        }
        self.image_bounds = {}
        self.connections = Connections(
            Path(identity_home) if identity_home else self.home / "identity", self.emit
        )
        self.project_id = None
        self.document = None
        self.runtime = None
        self.configuration_path = self.home / "settings.json"
        self.configuration = (
            self.projects.read(self.configuration_path)
            if self.configuration_path.exists()
            else {}
        )
        self.startup_notice = ""
        write_json(self.home / "runtime" / ("backend-" + str(os.getpid()) + ".json"),
                   self.application_runtime.report(private=True))

    @property
    def provider_id(self):
        return self.connections.status().get("provider_id", "codex")

    @property
    def provider_options(self) -> ProviderOptions:
        return self.provider_adapters.get(self.provider_id, self.provider_adapters["codex"])

    def executable_for(self, provider_id):
        if provider_id == "claude":
            return describe(discover_claude(self.configuration.get("claude_path")))
        return discover_executable(self.configuration.get("codex_path")) or ""

    def make_runtime(self, home, account=None, mcp=None, provider_id=None):
        provider_id = provider_id or (provider_of(account["mode"]) if account else self.provider_id)
        token = account.get("access_token", account.get("api_key")) if account else None
        if provider_id == "claude":
            mode = account["mode"] if account and account.get("mode") == "claude_code" else "anthropic"
            return ClaudeCodeRuntime(home, self.configuration.get("claude_path") or None, token, mode, mcp)
        return CodexAppServer(home, self.configuration.get("codex_path") or None, token,
                              account["mode"] if account else "chatgpt", mcp)

    def emit(self, event):
        event = dict(event)
        if event.get("stage") == "usage":
            if event.get("kind") == "tokens":
                observed = tokens(event.get("observation", {}))
                if event.get("observation", {}).get("increment"):
                    observed = {key: self.token_usage.get(key, 0) + value for key, value in observed.items()}
                self.token_usage = observed
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
            event.setdefault(
                "elapsed_seconds",
                max(0, time.time() - task["started_at"]),
            )
            event.update(
                task_id=task["task_id"],
                conversation_id=task["conversation_id"],
                document_id=task["document_id"],
                agent=copy.deepcopy(task.get("agent", CODEX_AGENT)),
            )
            if event.get("stage") not in (
                "assistant_delta",
                "assistant_message",
                "candidate",
                "usage",
            ):
                task.setdefault("activity", []).append(
                    {k: event[k] for k in (
                        "stage", "state", "message", "elapsed_seconds",
                        "operations_used", "operations_limit", "operations_remaining",
                    ) if k in event}
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
        if project.get("trashed") or project.get("archived"):
            raise WorkspaceError("Restore this project before opening it.")
        conversation = (
            self.projects.conversation(project_id)
            if project.get("active_conversation_id")
            else None
        )
        if conversation and (
            conversation.get("archived") or conversation.get("trashed")
        ):
            conversation = None
        document = self.projects.document(
            project, conversation["document_id"] if conversation else None
        )
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

    def claude_code_status(self, refresh=False):
        """Claude Code's own sign-in state, cached briefly because it runs a subprocess."""
        cached = self.claude_code_auth
        if cached and not refresh and time.monotonic() - cached[0] < 30:
            return copy.deepcopy(cached[1])
        report = auth_status(discover_claude(self.configuration.get("claude_path")))
        self.claude_code_auth = (time.monotonic(), report)
        return copy.deepcopy(report)

    def state(self):
        provider = self.connections.status()
        active = provider.get("active") or {}
        if active.get("connection") == "claude_code" and active.get("connected"):
            report = self.claude_code_status()
            provider["claude_code"] = report
            if not report["signed_in"]:
                provider["state"] = "disconnected"
                provider["error"] = report["message"]
        elif self.claude_code_auth:
            provider["claude_code"] = copy.deepcopy(self.claude_code_auth[1])
        if (
            active.get("connected")
            and active.get("id") == self.usage_account
            and self.usage_account
        ):
            provider["usage"] = self.provider_usage
        result = {
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
                "executable": self.executable_for(provider["provider_id"]),
                "provider": "Claude Code" if provider["provider_id"] == "claude" else "Codex App Server",
                "agent": copy.deepcopy(self.provider_adapters[provider["provider_id"]].identity),
                "executables": {
                    "codex": self.executable_for("codex"),
                    "claude": self.executable_for("claude"),
                },
            },
        }
        if self.project_id and result.get("conversation"):
            from .attachments import public
            base = self.projects.project_path(self.project_id)
            for message in result["conversation"].get("messages", []):
                if message.get("attachments"):
                    message["attachments"] = [public(base, item) for item in message["attachments"]]
                revision = (message.get("change") or {}).get("result_revision_id")
                if message.get("role") == "assistant" and revision and self.document:
                    notes = self.turn_design_notes(self.document.folder, revision)
                    if notes:
                        message["design_notes"] = notes
        return result

    def turn_design_notes(self, folder, revision_id):
        """Notes an agent turn added or changed, read from its immutable result revision and parent."""
        from backend.native.documents import asset_path

        key = (str(folder), revision_id)
        if key in self.note_cache:
            return copy.deepcopy(self.note_cache[key])

        def snapshot(identity):
            if not isinstance(identity, str) or not identity:
                return {}
            return json.loads(asset_path(folder, f"revisions/{identity}.json").read_text(encoding="utf-8"))

        try:
            after = snapshot(revision_id)
            before = snapshot(after.get("parent_revision_id"))
            earlier = {r.get("id"): r for r in before.get("engineering", []) if r.get("kind") == "note"}
            names = {p.get("instance_id"): p.get("name") for p in after.get("components", [])}
            notes = [
                {
                    "id": record.get("id"),
                    "instance_id": record.get("instance_id"),
                    "component_name": names.get(record.get("instance_id")) or "Component",
                    "text": record.get("text", ""),
                    "status": record.get("status", "current"),
                }
                for record in after.get("engineering", [])
                if record.get("kind") == "note"
                and (earlier.get(record.get("id")) or {}).get("text") != record.get("text")
            ]
        except (OSError, ValueError, TypeError, AttributeError, WorkspaceError):
            notes = []  # A missing or foreign revision simply has no notes to show.
        self.note_cache[key] = notes
        return copy.deepcopy(notes)

    def capability_key(self, account_id):
        provider_id = self.provider_id
        executable = self.executable_for(provider_id)
        stamp = Path(executable).stat().st_mtime_ns if executable and Path(executable).is_file() else 0
        return provider_id, account_id, executable, stamp

    def discover_models(self, refresh=False):
        account_id, account = self.connections.credential()
        key = self.capability_key(account_id)
        cached = self.capability_cache.get(key)
        if cached and not refresh and time.monotonic() - cached[0] < 600:
            return copy.deepcopy(cached[1])
        result = self.connections.models(refresh)
        result["provider_id"] = self.provider_options.identity["id"]
        result["connection_id"] = account_id
        runtime, reported = None, {}
        if result["provider_id"] == "claude":
            # The Anthropic catalogue is authoritative; Claude Code needs no model handshake.
            reported = {m["id"]: m for m in result["models"]}
            if not self.executable_for("claude"):
                result["capability_diagnostic"] = "Install Claude Code to run Claude tasks. Models are listed from your API key."
        else:
            try:
                runtime = self.make_runtime(self.home / "runtime" / account_id, account)
                reported = {m.get("model", m.get("id")): m for m in runtime.model_catalogue()}
            except WorkspaceError as error:
                result["capability_diagnostic"] = str(error)
            finally:
                if runtime:
                    runtime.close()
        for model in result["models"]:
            model["provider_id"] = result["provider_id"]
            model["connection_id"] = account_id
            model["reasoning_effort"] = self.provider_options.reasoning_effort(reported.get(model["id"]))
            provider_modes = model.get("inputModalities")
            runtime_modes = reported.get(model["id"], {}).get("inputModalities")
            declarations = [m for m in (provider_modes, runtime_modes) if isinstance(m, list)]
            model["image_support"] = ("unsupported" if any("image" not in m for m in declarations)
                                      else "supported" if declarations else "unknown")
            model["capability_source"] = "provider/runtime metadata" if declarations else "not reported"
            model["inputModalities"] = sorted(set.intersection(*(set(m) for m in declarations))) if declarations else None
        self.capability_cache[key] = (time.monotonic(), copy.deepcopy(result))
        if refresh:
            self.image_bounds = {k: v for k, v in self.image_bounds.items() if k[0] != key}
        return result

    def image_support(self, model):
        account_id, account = self.connections.credential()
        entry = next((m for m in self.discover_models()["models"] if m["id"] == model), None)
        if not entry or entry.get("image_support") != "supported":
            raise WorkspaceError("Image input is " + ((entry or {}).get("image_support", "unknown")) +
                " for this model. Refresh capabilities or choose a model that reports image support. Your draft was retained.", "image_capability_required")
        key = self.capability_key(account_id), model
        cached = self.image_bounds.get(key)
        if cached and time.monotonic() - cached[0] < 600:
            if not cached[1]:
                raise WorkspaceError("The configured provider excludes image input for this model.", "image_unsupported")
            return entry
        if provider_of(account["mode"]) == "claude":
            self.image_bounds[key] = time.monotonic(), True
            return entry
        runtime = self.make_runtime(self.home / "runtime" / account_id, account)
        try:
            bounds = runtime.input_bounds(model)
        finally:
            runtime.close()
        supported = bounds is None or "image" in bounds
        self.image_bounds[key] = time.monotonic(), supported
        if not supported:
            cached_models = self.capability_cache.get(self.capability_key(account_id))
            if cached_models:
                for item in cached_models[1]["models"]:
                    if item["id"] == model:
                        item.update(image_support="unsupported", capability_source="configured provider bounds")
            raise WorkspaceError("The configured provider excludes image input for this model. Your draft was retained.", "image_unsupported")
        return entry

    def dispatch(self, method, params):
        if method == "workspace.runtime":
            self.application_runtime.ensure_current()
            worker = self.geometry("hello", {})["runtime_identity"]
            self.application_runtime.verify_peer(worker, "geometry")
            return {"backend": self.application_runtime.report(private=True), "geometry": worker}
        if method.startswith("v2.") and method != "v2.state":
            if self.active_task and method not in BACKGROUND_NAVIGATION:
                raise WorkspaceError(
                    "A task is running in the background. You can open other conversations and projects; "
                    "wait for it or stop it before changing documents.",
                    "busy",
                )
            if method == "v2.task":
                return self.dispatch_task(params)
            with self.projects.write_lock():
                if (
                    method
                    in {
                        "v2.command",
                        "v2.command_batch",
                        "v2.script",
                        "v2.undo",
                        "v2.redo",
                        "v2.restore",
                        "v2.appearance",
                        "v2.engineering",
                        "v2.restructure",
                        "v2.definition",
                    }
                    and self.document
                ):
                    with revision_lock(self.document.folder / ".task-lock"):
                        return self._dispatch(method, params)
                return self._dispatch(method, params)
        return self._dispatch(method, params)

    def dispatch_task(self, params):
        # Capture the submitting project and document: the user may open others while the task runs.
        with self.projects.write_lock():
            project_id, document = self.project_id, self.document
        try:
            if document is None:
                return self.run_task(params, project_id, document)
            # Only the task's own document is locked, so navigation and other projects stay available.
            with revision_lock(document.folder / ".task-lock"):
                return self.run_task(params, project_id, document)
        except WorkspaceError as error:
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

    def _dispatch(self, method, params):
        self.task_deadline = None
        if method == "v2.state":
            return self.state()
        if method == "v2.projects.refresh":
            catalog = self.projects.reconcile()
            if self.project_id:
                if self.project_id not in {
                    p["project_id"] for p in catalog["projects"]
                }:
                    self.project_id = None
                    self.document = None
                else:
                    project = self.projects.project(self.project_id)
                    self.document = self.projects.document(project)
            return self.state()
        if method in ("v2.project.purge", "v2.conversation.purge"):
            pid = params["project_id"]
            self.projects.purge(
                pid,
                params["conversation_id"]
                if method == "v2.conversation.purge"
                else None,
            )
            if pid == self.project_id and method == "v2.project.purge":
                self.project_id = None
                self.document = None
            return self.state()
        if method == "v2.project.save":
            if not self.project_id:
                raise WorkspaceError("Open a project first.")
            project = self.projects.project(self.project_id)
            for entry in project["documents"]:
                doc = self.projects.document(project, entry["document_id"])
                if doc.index()["cursor"] >= 0:
                    doc.current()
                write_json(doc.index_path, doc.index())
            write_json(
                self.projects.project_path(self.project_id) / "workspace.json", project
            )
            return self.state()
        if method == "v2.project.save_as":
            from .project_copy import clone

            if not self.project_id:
                raise WorkspaceError("Open a project first.")
            return self.activate(clone(self.projects, self.project_id, params["name"]))
        if method == "v2.conversations.batch":
            results = self.projects.batch_conversations(
                params["items"], params["action"]
            )
            return {**self.state(), "results": results}
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
            if project_id == self.project_id and (
                values.get("trashed") or values.get("archived")
            ):
                self.project_id = None
                self.document = None
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
            if chat.get("trashed") or chat.get("archived"):
                raise WorkspaceError("Restore this conversation before opening it.")
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
                self.projects.update(
                    self.project_id, active_document_id=did, active_conversation_id=None
                )
            return self.activate(self.project_id)
        if method == "v2.conversation.restart_session":
            chat = self.projects.conversation(self.project_id)
            chat["provider_session"] = None
            self.projects.save_conversation(self.project_id, chat)
            return self.state()
        if method == "v2.restore":
            self.document.restore(params["revision_id"], params["base_revision_id"])
            self.projects.touch(self.project_id)
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
            project = self.projects.project(pid)
            if project.get("active_conversation_id") == chat["conversation_id"] and (
                chat.get("trashed") or chat.get("archived")
            ):
                self.projects.update(pid, active_conversation_id=None)
            return self.state()
        if method == "provider.status":
            return self.state()["provider"]
        if method == "provider.login":
            return self.connections.begin(
                params.get("account_id"), bool(params.get("new_registration"))
            )
        if method == "provider.cancel_login":
            return self.connections.cancel_login()
        if method == "provider.forget":
            return self.connections.forget(params["account_id"])
        if method == "provider.api_key":
            return self.connections.api_key(params["key"])
        if method == "provider.anthropic_key":
            return self.connections.anthropic_key(params["key"])
        if method == "provider.claude_code":
            report = self.claude_code_status(refresh=True)
            if not report["installed"]:
                raise WorkspaceError("Install Claude Code, then try again.", "runtime_missing")
            self.connections.claude_code()
            return self.state()
        if method == "provider.claude_code_sign_in":
            open_sign_in(discover_claude(self.configuration.get("claude_path")))
            self.claude_code_auth = None
            return {"opened": True}
        if method == "provider.claude_code_status":
            self.claude_code_status(refresh=True)
            return self.state()
        if method == "provider.use":
            return self.connections.use_provider(str(params.get("provider_id", "")))
        if method == "provider.select":
            return self.connections.select(params["account_id"])
        if method == "provider.disconnect":
            return self.connections.disconnect(params.get("account_id"))
        if method == "provider.models":
            return self.discover_models(bool(params.get("refresh")))
        if method == "provider.image_support":
            return self.image_support(params["model"])
        if method == "v2.attachment.add":
            if not self.project_id:
                raise WorkspaceError("Create or open a project before attaching images.", "project_required")
            from .attachments import store, public
            base = self.projects.project_path(self.project_id)
            return {"attachment": public(base, store(base, params["path"]))}
        if method == "provider.usage":
            return self.read_usage()
        if method == "provider.configure":
            for key, name in (("codex_path", "Codex"), ("claude_path", "Claude Code")):
                if key not in params:
                    continue
                path = str(params.get(key, "")).strip()
                if path and not Path(path).is_file():
                    raise WorkspaceError("Select the installed " + name + " executable.")
                self.configuration[key] = path
            write_json(self.configuration_path, self.configuration)
            return self.state()
        if method == "provider.probe":
            provider_id = str(params.get("provider_id") or self.provider_id)
            runtime = self.make_runtime(self.home / "runtime" / "probe", provider_id=provider_id)
            try:
                if provider_id == "claude":
                    version = runtime.version()
                    return {
                        "connected": True,
                        "server": {**runtime.info, "version": version},
                        "authenticated": False,
                        "message": "Claude Code " + version + " started. API key and model inference remain unverified.",
                    }
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
            self.projects.touch(self.project_id)
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
        if method in ("v2.command", "v2.command_batch", "v2.script", "v2.appearance", "v2.engineering", "v2.restructure", "v2.definition"):
            if not self.document:
                raise WorkspaceError("Open or create a document first.", "no_document")
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
            if method in ("v2.appearance", "v2.engineering", "v2.restructure", "v2.definition"):
                name = {"v2.appearance": "cad_appearance", "v2.engineering": "cad_engineering",
                        "v2.restructure": "cad_restructure", "v2.definition": "cad_files"}[method]
                tools.call(name, {"candidate_id": tools.candidate_id,
                    **{k: v for k, v in params.items() if k not in ("base_revision_id", "selection", "project_id", "document_id")}})
            elif method == "v2.command_batch":
                tools.call(
                    "cad_apply_batch",
                    {
                        "candidate_id": tools.candidate_id,
                        "commands": params["commands"],
                    },
                )
            elif method == "v2.command":
                tools.call(
                    "cad_apply",
                    {"candidate_id": tools.candidate_id, "command": params["command"]},
                )
            else:
                tools.call(
                    "cad_script",
                    {
                        "candidate_id": tools.candidate_id,
                        **{key: params[key] for key in ("source", "definition_id", "parameters", "instance_id", "source_instance_ids") if key in params},
                    },
                )
            report = tools.call("cad_validate", {"candidate_id": tools.candidate_id})
            tools.candidate["verification"] = report
            self.document.commit(
                tools.candidate,
                snapshot["revision_id"],
                summary=params.get("command", {}).get("type", method.removeprefix("v2.").replace("_", " ")),
                commands=tools.commands,
            )
            self.projects.touch(self.project_id)
            return self.state()
        if method in ("v2.undo", "v2.redo"):
            super().dispatch(
                "document.undo" if method.endswith("undo") else "document.redo", params
            )
            self.projects.touch(self.project_id)
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
                "product_name": "Prompt to CAD",
            }
        raise WorkspaceError("Unknown V2 method: " + method, "method_not_found")

    def run_task(self, params, project_id=None, document=None):
        self.application_runtime.ensure_current()
        if project_id is None and document is None:
            project_id, document = self.project_id, self.document
        if not project_id:
            raise WorkspaceError("Create a project first.")
        if not self.projects.project(project_id).get("active_conversation_id"):
            raise WorkspaceError(
                "Start or open a conversation before sending a request.",
                "conversation_required",
            )
        chat = self.projects.conversation(project_id)
        if chat.get("trashed") or chat.get("archived"):
            raise WorkspaceError(
                "Restore or start a conversation before sending a request.",
                "conversation_required",
            )
        raw_prompt = str(params.get("prompt", ""))
        prompt = raw_prompt.strip()
        if not prompt and params.get("attachments"):
            prompt = "Inspect the attached references and clarify what should be created or changed before modifying geometry."
        if not 1 <= len(prompt) <= 16000 or len(raw_prompt) > 16000:
            raise WorkspaceError("Describe the task in 1–16,000 characters.")
        model = str(params.get("model", "")).strip()
        if not model:
            raise WorkspaceError(
                "Discover and select a model in the conversation panel.",
                "model_required",
            )
        account_id, account = self.connections.credential()
        if account["mode"] == "claude_code" and not self.claude_code_status(refresh=True)["signed_in"]:
            raise WorkspaceError("Claude Code is not signed in. Sign in from Settings → AI connection, then send again. "
                                 "Your draft was retained.", "reauthorization_required")
        provider_id = self.provider_options.identity["id"]
        if params.get("provider_id", provider_id) != provider_id:
            raise WorkspaceError("The selected provider changed. Review the model and submit again.", "provider_changed")
        state = self.projects.view(project_id)
        original = state["document"]
        if params.get("base_revision_id") != original.get("revision_id"):
            raise WorkspaceError(
                "The document changed before task submission. Inspect and submit again.",
                "revision_conflict",
            )
        from .attachments import submission
        attached = submission(self.projects.project_path(project_id), params.get("attachments", []))
        if attached:
            self.image_support(model)
        cached = self.capability_cache.get(self.capability_key(account_id))
        if params.get("reasoning_effort") is not None and (not cached or time.monotonic() - cached[0] >= 600):
            self.discover_models()
            cached = self.capability_cache.get(self.capability_key(account_id))
        model_entry = next((m for m in (cached[1]["models"] if cached and time.monotonic() - cached[0] < 600 else []) if m["id"] == model), {})
        effort = capture_effort(provider_id, model, model_entry.get("reasoning_effort") or
                                self.provider_options.reasoning_effort(None), params.get("reasoning_effort"))
        turn_options = self.provider_options.turn_options(effort)
        supports_images = model_entry.get("image_support") == "supported"
        bounds = self.image_bounds.get((self.capability_key(account_id), model))
        if bounds and time.monotonic() - bounds[0] < 600 and not bounds[1]:
            supports_images = False
        viewport = (
            self.projects.reference(project_id, params["viewport_path"])
            if params.get("viewport_path")
            else None
        )
        task_id = str(params.get("task_id") or uuid4().hex)
        if len(task_id) != 32 or any(c not in "0123456789abcdef" for c in task_id):
            raise WorkspaceError("Invalid task submission identifier.")
        if (
            self.projects.project_path(project_id) / "tasks" / (task_id + ".json")
        ).exists():
            raise WorkspaceError(
                "This submission has already been received. Reopen the conversation to inspect its outcome.",
                "duplicate_submission",
            )
        task = {
            "task_id": task_id,
            "application_runtime": self.application_runtime.report(),
            "document_id": original["document_id"],
            "conversation_id": state["conversation"]["conversation_id"],
            "base_revision_id": original.get("revision_id"),
            "status": "running",
            "prompt": prompt,
            "submitted_selection": copy.deepcopy(params.get("selection")),
            "started_at": time.time(),
            "model": model,
            "provider_account": account_id,
            "agent": copy.deepcopy(self.provider_options.identity),
            "reasoning_effort": copy.deepcopy(effort),
            "attachments": [copy.deepcopy(reference) for reference, _ in attached],
        }
        tools = TaskTools(
            self,
            document,
            original,
            task["submitted_selection"],
            project_id,
            task["task_id"],
        )
        from .turn_logs import TurnLog
        turn_log = TurnLog(self.projects.project_path(project_id), task, project_id,
            notify=lambda message: self.notify({"stage": "logging", "message": message}))
        turn_log.event("backend_runtime_verified", self.application_runtime.report())
        tools.turn_log = turn_log
        turn_log.catalog_evidence("discovery", tools.catalog.initial)
        task["turn_log"] = "logs/turns/" + task["task_id"]
        tools.viewport = viewport if supports_images else None
        tools.image_supported = supports_images
        tools.references = {r["asset_id"]: r for message in state["conversation"]["messages"]
                            for r in message.get("attachments", []) if r.get("asset_id")}
        tools.references.update({r["asset_id"]: r for r, _ in attached})
        task["viewport"] = viewport
        task["submitted_selection"] = tools.selection
        conversation = state["conversation"]
        conversation["messages"].append(
            {
                "role": "user",
                "content": raw_prompt,
                "selection": tools.selection,
                "task_id": task["task_id"],
                "attachments": copy.deepcopy(task["attachments"]),
            }
        )
        conversation["tasks"].append(task["task_id"])
        if conversation["title"] == "New conversation":
            conversation["title"] = prompt[:60] if raw_prompt.strip() else "Image reference"
        self.projects.save_conversation(project_id, conversation)
        self.projects.task(project_id, task)
        self.active_task = task
        self.notify({
            "stage": "budget",
            "message": "CAD operation budget: 0/32 used (32 remaining).",
            "operations_used": 0,
            "operations_limit": 32,
            "operations_remaining": 32,
        })
        bridge = None
        deadline = time.monotonic() + CAD_TURN_TIMEOUT_SECONDS
        tools.deadline = deadline
        document.journal(
            "running",
            action=provider_id,
            task_id=task["task_id"],
            base_revision_id=original.get("revision_id"),
        )
        try:
            bridge = ToolBridge(tools)
            source_root = Path(__file__).resolve().parents[2]
            # Use the real interpreter, avoiding the Windows venv launcher process.
            python = getattr(sys, "_base_executable", sys.executable)
            if os.name == "nt":
                # Codex launches MCP itself, so our CREATE_NO_WINDOW flag does not apply.
                python = str(Path(python).with_name("pythonw.exe"))
                if not Path(python).is_file():
                    raise WorkspaceError(
                        "The Python windowless interpreter is missing. Repair the Python installation before starting an agent task.",
                        "runtime_missing",
                    )
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
                    **self.application_runtime.environment(),
                },
                "startup_timeout_sec": 30,
                "tool_timeout_sec": 660,
            }
            self.notify(
                {
                    "stage": "connecting",
                    "message": "Starting Claude Code · your Claude Code sign-in"
                    if account["mode"] == "claude_code"
                    else "Starting Claude Code · Anthropic API billing"
                    if provider_id == "claude"
                    else "Starting Codex App Server · "
                    + (
                        "ChatGPT plan"
                        if account["mode"] == "chatgpt"
                        else "API billing"
                    ),
                }
            )
            self.runtime = self.make_runtime(self.home / "runtime" / account_id, account, mcp)
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
            self.projects.save_conversation(project_id, conversation)
            context_data = tools.context()
            context = json.dumps(context_data, allow_nan=False)
            if not resuming:
                history = "\n".join(
                    m["role"] + ": " + m["content"] + ("\nReference assets: " + json.dumps(m["attachments"], allow_nan=False) if m.get("attachments") else "")
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
            def turn_notify(event):
                if event.get("stage") == "agent_running":
                    turn_log.catalog_evidence("context_submitted", context_data["step_catalog"])
                self.notify(event)

            provider_started = time.monotonic()
            try:
                message = self.runtime.run(
                    text,
                    model,
                    self.cancelled,
                    turn_notify,
                    [str(path) for _, path in attached] + ([viewport["path"]] if viewport and supports_images and len(attached) < 8
                        and sum(path.stat().st_size for _, path in attached) + Path(viewport["path"]).stat().st_size <= 50 * 1024 * 1024 else []),
                    timeout=max(1, deadline - time.monotonic()),
                    turn_options=turn_options,
                )
            except Exception:
                total_elapsed = time.monotonic() - provider_started
                tool_elapsed = turn_log.tool_elapsed()
                turn_log.phase("provider_turn", total_elapsed, failed=True)
                turn_log.phase("provider_transport_wait", max(0, total_elapsed - tool_elapsed), failed=True)
                raise
            total_elapsed = time.monotonic() - provider_started
            tool_elapsed = turn_log.tool_elapsed()
            turn_log.phase("provider_turn", total_elapsed)
            turn_log.phase("provider_transport_wait", max(0, total_elapsed - tool_elapsed))
            if self.cancelled.is_set():
                raise WorkspaceError("Task cancelled before acceptance.", "cancelled")
            if tools.commands:
                self.application_runtime.ensure_current()
                if tools.mcp_runtime is None:
                    raise WorkspaceError("The CAD MCP tool contract was not verified. Restart the application before generating geometry.", "runtime_mismatch")
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
                    document.commit(
                        tools.candidate,
                        original.get("revision_id"),
                        summary=message[:3000] or task["agent"]["display_name"] + " CAD task",
                        commands=tools.commands,
                    )
                task.update(
                    result_revision_id=document.current()["revision_id"],
                    validation=report,
                    affected_components=[
                        p["instance_id"]
                        for p in tools.candidate["components"]
                        if fingerprint(original).get(p["instance_id"])
                        != fingerprint(tools.candidate)[p["instance_id"]]
                    ],
                    created_components=sorted(set(fingerprint(tools.candidate)) - set(fingerprint(original))),
                    consumed_components=sorted(set(fingerprint(original)) - set(fingerprint(tools.candidate))),
                    replaced_components=sorted(identity for identity in set(fingerprint(original)) & set(fingerprint(tools.candidate))
                                               if fingerprint(original)[identity] != fingerprint(tools.candidate)[identity]),
                    component_transactions=copy.deepcopy(tools.transactions),
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
            if attached:
                task["image_access"] = "observed_success_for_this_request"
                cached_models = self.capability_cache.get(self.capability_key(account_id))
                if cached_models:
                    for item in cached_models[1]["models"]:
                        if item["id"] == model:
                            item["image_access"] = "Observed successful image request; future access is not guaranteed."
            conversation["messages"].append(
                {
                    "role": "assistant",
                    "agent": copy.deepcopy(task["agent"]),
                    "reasoning_effort": copy.deepcopy(task["reasoning_effort"]),
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
                            "created_components",
                            "consumed_components",
                            "replaced_components",
                            "component_transactions",
                        )
                        if k in task
                    },
                }
            )
            document.journal("completed", task_id=task["task_id"])
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
            document.journal(task["status"], task_id=task["task_id"])
            raise
        finally:
            with tools.lock:
                tools.closed = True
                turn_log.finish(task)
                if turn_log.error:
                    task["log_warning"] = "Project turn log could not be fully written: " + turn_log.error
            if bridge:
                bridge.close()
            if self.runtime:
                self.runtime.close()
                self.runtime = None
            self.projects.task(project_id, task)
            conversation["token_usage"] = self.token_usage
            try:
                # Keep renames or archive changes made elsewhere while the task ran in the background.
                stored = self.projects.conversation(project_id, conversation["conversation_id"])
                for key in ("title", "archived", "trashed"):
                    if key in stored:
                        conversation[key] = stored[key]
            except (OSError, ValueError, KeyError, WorkspaceError):
                pass
            self.projects.save_conversation(project_id, conversation)
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
        if account["mode"] == "claude_code":
            usage = {
                "available": False,
                "message": "Usage counts against the account Claude Code is signed in with. Check it with /usage in Claude Code.",
            }
        if account["mode"] == "anthropic":
            usage = {
                "available": False,
                "message": "Anthropic API billing is separate. View costs in the Claude Console.",
            }
        if account["mode"] == "chatgpt":
            runtime = None
            try:
                runtime = self.make_runtime(self.home / "runtime/usage", account)
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

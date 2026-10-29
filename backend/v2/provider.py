"""Codex App Server transport; CAD semantics live in the application tools."""

import json
import os
import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path

from backend.native.contracts import WorkspaceError

from .process_limits import ProcessTree


def discover_executable(configured=None):
    if configured:
        return str(configured) if Path(configured).is_file() else None
    explicit = os.getenv("PROMPTCAD_CODEX")
    if explicit:
        return explicit if Path(explicit).is_file() else None
    installed = shutil.which("codex.exe" if os.name == "nt" else "codex")
    if installed:
        return installed
    if os.name == "nt":
        folder = Path(os.getenv("LOCALAPPDATA", "")) / "OpenAI" / "Codex" / "bin"
        candidates = list(folder.glob("*/codex.exe"))
        if candidates:
            return str(max(candidates, key=lambda p: p.stat().st_mtime))
    return None


def provider_failure(error):
    info = error.get("codexErrorInfo", "")
    code = info if isinstance(info, str) else next(iter(info), "")
    if code in ("usageLimitExceeded", "rateLimitExceeded", "insufficientQuota"):
        return (
            "The connected account has reached its usage limit. Manage its allowance or credits, then retry. Billing was not changed.",
            "usage_limit",
        )
    if code in ("unauthorized", "authenticationError"):
        return (
            "Authorization expired or was revoked. Reconnect the same account in Settings.",
            "reauthorization_required",
        )
    return error.get(
        "message", "The agent task failed. Unaccepted changes were discarded."
    ), "provider_task_failed"


class CodexAppServer:
    def __init__(self, home, executable=None, token=None, mode="chatgpt", mcp=None):
        self.home = Path(home).resolve()
        self.home.mkdir(parents=True, exist_ok=True)
        self.cwd = self.home / "workspace"
        self.cwd.mkdir(exist_ok=True)
        self.executable = discover_executable(executable)
        if not self.executable:
            raise WorkspaceError(
                "Install the Codex CLI and select its executable in Account settings.",
                "runtime_missing",
            )
        config = {
            "model_provider": "promptcad",
            "model_providers.promptcad.name": "ChatGPT plan"
            if mode == "chatgpt"
            else "User API key (separate billing)",
            "model_providers.promptcad.base_url": "https://api.openai.com/v1",
            "model_providers.promptcad.env_key": "PROMPTCAD_PROVIDER_TOKEN",
            "model_providers.promptcad.wire_api": "responses",
            "model_providers.promptcad.requires_openai_auth": False,
            "model_providers.promptcad.supports_websockets": False,
            "web_search": "disabled",
            "features.shell_tool": False,
            "features.unified_exec": False,
            "features.apps": False,
            "features.in_app_browser": False,
            "features.multi_agent": False,
        }
        if mcp:
            config["mcp_servers.cad"] = mcp
        args = [self.executable, "app-server", "--listen", "stdio://"]
        for key, value in config.items():
            # TOML accepts JSON strings/booleans/arrays; tables need inline TOML syntax.
            def toml(v):
                if isinstance(v, dict):
                    return (
                        "{ "
                        + ", ".join(
                            json.dumps(k) + " = " + toml(x) for k, x in v.items()
                        )
                        + " }"
                    )
                return json.dumps(v)

            args += ["-c", key + "=" + toml(value)]
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("OPENAI_", "CODEX_", "ANTHROPIC_", "LLM_"))
        }
        env.update(
            CODEX_HOME=str(self.home), PROMPTCAD_PROVIDER_TOKEN=token or "not-connected"
        )
        self.secret = token
        self.process = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=self.cwd,
            env=env,
            text=True,
            encoding="utf-8",
            bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            self.process_tree = ProcessTree(self.process)
        except Exception:
            self.process.kill()
            self.process.wait(timeout=2)
            raise
        self.inbox = queue.Queue()
        self.events = queue.Queue()
        self.sequence = 0
        self.write_lock = threading.Lock()
        self.thread_id = None
        self.turn_id = None
        self.pending_inputs = {}

        def reader():
            try:
                for line in self.process.stdout:
                    if len(line) > 8 * 1024 * 1024:
                        break
                    self.inbox.put(json.loads(line))
            except (ValueError, OSError):
                pass
            finally:
                self.inbox.put(None)

        self.reader = threading.Thread(target=reader, daemon=True)
        self.reader.start()
        try:
            self.info = self.request(
                "initialize",
                {
                    "clientInfo": {
                        "name": "Prompt to CAD V2",
                        "title": "Prompt to CAD V2",
                        "version": "0.4.0",
                    }
                },
            )
            self.send({"method": "initialized", "params": {}})
        except Exception:
            self.close()
            raise

    def send(self, message):
        with self.write_lock:
            try:
                self.process.stdin.write(json.dumps(message, allow_nan=False) + "\n")
                self.process.stdin.flush()
            except (OSError, ValueError):
                raise WorkspaceError(
                    "The Codex runtime disconnected.", "runtime_disconnected"
                ) from None

    def receive(self, timeout=0.2):
        try:
            event = self.inbox.get(timeout=timeout)
        except queue.Empty:
            return {}
        if event is None:
            raise WorkspaceError(
                "The Codex runtime stopped. Reconnect and resume the conversation.",
                "runtime_disconnected",
            )
        return event

    def request(self, method, params, timeout=30):
        self.sequence += 1
        identity = self.sequence
        self.send({"id": identity, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            event = self.receive()
            if event.get("id") == identity and "method" not in event:
                if "error" in event:
                    message = event["error"].get(
                        "message", "App Server rejected the request."
                    )
                    if self.secret:
                        message = message.replace(self.secret, "[credential]")
                    raise WorkspaceError(message, "app_server_error")
                return event.get("result", {})
            if event:
                self.events.put(event)
        raise WorkspaceError(
            "The Codex runtime did not respond in time.", "runtime_timeout"
        )

    def start_thread(self, instructions, model, thread_id=None):
        params = {
            "cwd": str(self.cwd),
            "model": model,
            "modelProvider": "promptcad",
            "sandbox": "read-only",
            "approvalPolicy": "never",
            "developerInstructions": instructions,
        }
        if thread_id:
            params["threadId"] = thread_id
        result = self.request(
            "thread/resume" if thread_id else "thread/start", params, timeout=60
        )
        self.thread_id = result["thread"]["id"]
        return self.thread_id

    def run(self, text, model, cancelled, notify, images=(), timeout=600):
        if cancelled.is_set():
            raise WorkspaceError("Task cancelled before inference.", "cancelled")
        inputs = [{"type": "text", "text": text}]
        inputs += [
            {"type": "localImage", "path": str(Path(p).resolve())} for p in images
        ]
        result = self.request(
            "turn/start", {"threadId": self.thread_id, "input": inputs, "model": model}
        )
        self.turn_id = result["turn"]["id"]
        notify(
            {
                "stage": "agent_running",
                "message": "Codex is working with the current CAD document.",
            }
        )
        deadline = time.monotonic() + timeout
        interrupted_at = None
        messages = {}
        phases = {}
        while True:
            if (
                cancelled.is_set() or time.monotonic() >= deadline
            ) and interrupted_at is None:
                self.sequence += 1
                self.send(
                    {
                        "id": self.sequence,
                        "method": "turn/interrupt",
                        "params": {"threadId": self.thread_id, "turnId": self.turn_id},
                    }
                )
                interrupted_at = time.monotonic()
            if interrupted_at and time.monotonic() - interrupted_at > 5:
                raise WorkspaceError(
                    "Task stopped; candidate changes were discarded.",
                    "cancelled" if cancelled.is_set() else "runtime_timeout",
                )
            event = self.events.get() if not self.events.empty() else self.receive()
            method, params = event.get("method"), event.get("params", {})
            if params.get("threadId", self.thread_id) != self.thread_id:
                continue
            if params.get("turnId", self.turn_id) != self.turn_id:
                continue
            if (
                method == "turn/completed"
                and params.get("turn", {}).get("id", self.turn_id) != self.turn_id
            ):
                continue
            if "id" in event and method:
                if method == "item/tool/requestUserInput" and not any(
                    q.get("isSecret") for q in params.get("questions", [])
                ):
                    self.pending_inputs[event["id"]] = params.get("questions", [])
                    notify(
                        {
                            "stage": "clarification",
                            "message": "The CAD task needs your input.",
                            "request_id": event["id"],
                            "questions": params.get("questions", []),
                        }
                    )
                elif method in (
                    "item/commandExecution/requestApproval",
                    "item/fileChange/requestApproval",
                ):
                    self.send({"id": event["id"], "result": {"decision": "decline"}})
                    notify(
                        {
                            "stage": "approval",
                            "message": "An action outside the CAD tool boundary was declined. The agent can continue with the CAD tools.",
                        }
                    )
                elif method == "mcpServer/elicitation/request":
                    self.send({"id": event["id"], "result": {"action": "decline"}})
                else:
                    self.send(
                        {
                            "id": event["id"],
                            "error": {
                                "code": -32601,
                                "message": "Use CAD tools. Ask ordinary modelling questions in conversation; do not request secrets.",
                            },
                        }
                    )
            elif method == "thread/tokenUsage/updated":
                notify({"stage": "usage", "kind": "tokens", "observation": params})
            elif method == "account/rateLimits/updated":
                notify({"stage": "usage", "kind": "allowance", "observation": params})
            elif (
                method == "item/started"
                and params.get("item", {}).get("type") == "agentMessage"
            ):
                item = params["item"]
                phases[item["id"]] = item.get("phase")
            elif method == "item/agentMessage/delta":
                delta = params.get("delta", "")
                key = params.get("itemId", "message")
                messages[key] = messages.get(key, "") + delta
                notify(
                    {
                        "stage": "assistant_delta",
                        "message": delta,
                        "item_id": key,
                        "phase": phases.get(key),
                    }
                )
            elif (
                method == "item/completed"
                and params.get("item", {}).get("type") == "agentMessage"
            ):
                item = params["item"]
                key = item["id"]
                messages[key] = item.get("text", messages.get(key, ""))
                phases[key] = item.get("phase", phases.get(key))
                if phases[key] == "commentary":
                    notify({"stage": "agent_progress", "message": messages[key]})
                notify(
                    {
                        "stage": "assistant_message",
                        "message": messages[key],
                        "item_id": key,
                        "phase": phases[key],
                    }
                )
            elif method == "turn/completed":
                turn = params["turn"]
                if interrupted_at or turn["status"] != "completed":
                    error = turn.get("error") or {}
                    message, failure_code = provider_failure(error)
                    if cancelled.is_set() or turn["status"] == "interrupted":
                        message = "Task cancelled; unaccepted changes were discarded."
                    if self.secret:
                        message = message.replace(self.secret, "[credential]")
                    raise WorkspaceError(
                        message,
                        ("cancelled" if cancelled.is_set() else "runtime_timeout")
                        if interrupted_at
                        else "cancelled"
                        if turn["status"] == "interrupted"
                        else failure_code,
                    )
                return "\n\n".join(
                    text
                    for key, text in messages.items()
                    if phases.get(key) != "commentary"
                )
            elif method == "error":
                notify(
                    {
                        "stage": "provider_error",
                        "message": "The provider reported an error; awaiting final task status.",
                    }
                )

    def respond(self, identity, answers):
        questions = self.pending_inputs.get(identity)
        if questions is None:
            raise WorkspaceError("This clarification request is no longer active.")
        expected = {q["id"] for q in questions}
        if not isinstance(answers, dict) or set(answers) != expected:
            raise WorkspaceError("Answer each question in this clarification request.")
        for answer in answers.values():
            if (
                not isinstance(answer, dict)
                or not isinstance(answer.get("answers"), list)
                or not all(
                    isinstance(v, str) and len(v) <= 4000 for v in answer["answers"]
                )
            ):
                raise WorkspaceError("Clarification answers must be short text values.")
        self.pending_inputs.pop(identity)
        self.send({"id": identity, "result": {"answers": answers}})
        return {"answered": True}

    def close(self):
        if getattr(self, "process", None):
            try:
                self.process.stdin.close()
                self.process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                self.process.kill()
                self.process.wait(timeout=2)
            finally:
                if getattr(self, "process_tree", None):
                    self.process_tree.close()
                if getattr(self, "reader", None):
                    self.reader.join(timeout=1)
                self.process.stdout.close()
                self.pending_inputs.clear()

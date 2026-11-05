"""Claude Code headless transport (API-key billing); CAD semantics live in the application tools."""

import base64
import json
import mimetypes
import os
import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path
from uuid import uuid4

from backend.native.contracts import CAD_TURN_TIMEOUT_MESSAGE, CAD_TURN_TIMEOUT_SECONDS, WorkspaceError

from .process_limits import ProcessTree

CLAUDE_AGENT = {"id": "claude", "display_name": "Claude"}
# Effort levels documented for `claude --effort`; availability depends on the model.
STANDARD_EFFORTS = ("low", "medium", "high")
EXTENDED_EFFORTS = ("xhigh", "max")
EFFORT_DESCRIPTIONS = {
    "low": "Fastest responses with the least deliberation.",
    "medium": "Balanced speed and depth.",
    "high": "Deeper reasoning for complex parts and assemblies.",
    "xhigh": "Extended reasoning for difficult modelling tasks.",
    "max": "Maximum reasoning depth; slowest and most expensive.",
}


class ClaudeProviderOptions:
    identity = CLAUDE_AGENT

    def reasoning_effort(self, model):
        if not isinstance(model, dict) or not isinstance(model.get("id"), str):
            return {
                "state": "unavailable", "options": [], "default_id": None,
                "message": "Effort options appear after the Claude model catalogue loads. Refresh models to retry.",
            }
        identity = model["id"].lower()
        levels = list(STANDARD_EFFORTS)
        if "opus" in identity or "fable" in identity:
            levels += EXTENDED_EFFORTS
        return {
            "state": "supported",
            "options": [{"id": level, "label": level.capitalize() if level != "xhigh" else "Extra high",
                         "description": EFFORT_DESCRIPTIONS[level]} for level in levels],
            "presentation": "steps",
            "default_id": None,
            "message": "Claude Code applies the selected effort for this turn. Levels depend on the model "
                       "and do not guarantee a fixed token or time budget.",
        }

    def turn_options(self, effort):
        if effort["provider_id"] != self.identity["id"]:
            raise WorkspaceError("Reasoning effort belongs to another provider.", "effort_invalid")
        return {"effort": effort["option_id"]} if effort["option_id"] is not None else {}


def _npm_command(script):
    """Run an npm-installed Claude Code without routing JSON arguments through cmd.exe."""
    package = Path(script).parent / "node_modules" / "@anthropic-ai" / "claude-code"
    for name in ("cli.js", "cli.mjs"):
        entry = package / name
        node = shutil.which("node")
        if entry.is_file() and node:
            return [node, str(entry)]
    native = package / "bin" / ("claude.exe" if os.name == "nt" else "claude")
    return [str(native)] if native.is_file() else None


def desktop_bundled(path):
    parts = [part.lower() for part in Path(path).parts]
    return "claude-code" in parts and "claude" in parts


def discover_claude(configured=None):
    """Return the command list that starts Claude Code, or None when it is not installed."""
    def command(path):
        path = Path(path)
        if not path.is_file():
            return None
        if path.suffix.lower() in (".cmd", ".bat", ".ps1"):
            return _npm_command(path)
        if path.suffix.lower() in (".js", ".mjs"):
            node = shutil.which("node")
            return [node, str(path)] if node else None
        return [str(path)]

    if configured:
        resolved = command(configured)
        if resolved or not desktop_bundled(configured):
            return resolved
        # A saved desktop-app copy disappears when the app updates; find the current one instead.
    explicit = os.getenv("PROMPTCAD_CLAUDE")
    if explicit:
        return command(explicit)
    candidates = []
    for name in (("claude.exe", "claude.cmd") if os.name == "nt" else ("claude",)):
        found = shutil.which(name)
        if found:
            candidates.append(found)
    home = Path.home()
    candidates += [home / ".local" / "bin" / ("claude.exe" if os.name == "nt" else "claude"),
                   home / ".claude" / "local" / ("claude.exe" if os.name == "nt" else "claude")]
    if os.name == "nt" and os.getenv("APPDATA"):
        candidates.append(Path(os.environ["APPDATA"]) / "npm" / "claude.cmd")
        # Last resort: the unmodified Claude Code that the Claude desktop app keeps up to date.
        bundled = Path(os.environ["APPDATA"]) / "Claude" / "claude-code"
        if bundled.is_dir():
            candidates += sorted(bundled.glob("*/*/claude.exe"), key=lambda p: p.stat().st_mtime, reverse=True)
    for candidate in candidates:
        resolved = command(candidate)
        if resolved:
            return resolved
    return None


def describe(command):
    return command[-1] if command else ""


AUTH_METHODS = {
    "claude.ai": "Claude plan sign-in",
    "oauth_token": "Claude OAuth token",
    "api_key": "API key",
    "api_key_helper": "API key helper",
    "third_party": "Cloud provider",
}


def user_environment():
    """The user's own environment, untouched apart from unrelated OpenAI/Codex variables."""
    return {k: v for k, v in os.environ.items() if not k.startswith(("OPENAI_", "CODEX_"))}


def auth_status(command, timeout=20):
    """Ask the installed Claude Code which sign-in it would use. Credentials stay inside Claude Code."""
    if not command:
        return {"installed": False, "signed_in": False, "method": "", "message": "Claude Code is not installed."}
    try:
        result = subprocess.run(
            command + ["auth", "status"], capture_output=True, text=True, timeout=timeout,
            env=user_environment(), encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"installed": True, "signed_in": False, "method": "",
                "message": "Claude Code did not answer. Check the installation."}
    try:
        report = json.loads(result.stdout or "{}")
    except ValueError:
        report = {}
    report = report if isinstance(report, dict) else {}
    method = str(report.get("authMethod") or "")
    signed_in = result.returncode == 0 and method not in ("", "none")
    account = report.get("account") if isinstance(report.get("account"), dict) else {}
    email = report.get("email") or account.get("email") or ""
    return {
        "installed": True,
        "signed_in": signed_in,
        "method": AUTH_METHODS.get(method, method.replace("_", " ")) if signed_in else "",
        "email": email if isinstance(email, str) else "",
        "message": "" if signed_in else "Claude Code is not signed in. Use Sign in, finish in the Claude Code window, then Check again.",
    }


def open_sign_in(command):
    """Open Claude Code's own sign-in in a console window; the app never sees the credentials."""
    if not command:
        raise WorkspaceError("Install Claude Code first.", "runtime_missing")
    flags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0
    try:
        subprocess.Popen(command + ["auth", "login"], env=user_environment(), creationflags=flags,
                         stdin=None, stdout=None, stderr=None, close_fds=True)
    except OSError:
        raise WorkspaceError("Claude Code could not start its sign-in. Run “claude auth login” in a terminal.",
                             "runtime_missing") from None


def provider_failure(text, subtype="", mode="anthropic"):
    lowered = (text or "").lower()
    if mode == "claude_code":
        if "not logged in" in lowered or "/login" in lowered or "login expired" in lowered or "please run" in lowered:
            return ("Claude Code is not signed in, or its sign-in expired. Sign in again in Settings → AI connection.",
                    "reauthorization_required")
        if "usage limit" in lowered or "limit reached" in lowered or "rate limit" in lowered or "429" in lowered:
            return ("The usage limit of the account Claude Code is signed in with was reached. Try again after it resets. "
                    "Billing was not changed.", "usage_limit")
    if "credit balance" in lowered or "billing" in lowered or "quota" in lowered:
        return ("The Anthropic account has insufficient API credits. Add credits in the Claude Console, then retry. "
                "Billing was not changed.", "usage_limit")
    if "rate limit" in lowered or "rate_limit" in lowered or "429" in lowered:
        return ("The Anthropic API rate limit was reached. Wait a moment, then retry. Billing was not changed.",
                "usage_limit")
    if ("invalid api key" in lowered or "authentication" in lowered or "401" in lowered
            or "invalid x-api-key" in lowered):
        return ("The Anthropic API key was rejected. Replace it in Settings → AI connection.",
                "reauthorization_required")
    if subtype == "error_max_turns":
        return ("Claude reached its turn limit before finishing. Unaccepted changes were discarded.",
                "provider_task_failed")
    return (text or "The agent task failed. Unaccepted changes were discarded.")[:2000], "provider_task_failed"


def mcp_document(mcp):
    """Translate the shared CAD MCP launch description into Claude Code's --mcp-config schema."""
    if not mcp:
        return None
    return {"mcpServers": {"cad": {
        "type": "stdio",
        "command": mcp["command"],
        "args": list(mcp.get("args", [])),
        "env": dict(mcp.get("env", {})),
    }}}


class ClaudeCodeRuntime:
    """One Claude Code print-mode process per turn; sessions resume by ID."""

    def __init__(self, home, executable=None, token=None, mode="anthropic", mcp=None):
        self.home = Path(home).resolve()
        self.home.mkdir(parents=True, exist_ok=True)
        self.cwd = self.home / "workspace"
        self.cwd.mkdir(exist_ok=True)
        self.mode = mode
        self.config_dir = self.home / "claude-config"
        if mode != "claude_code":
            self.config_dir.mkdir(exist_ok=True)
        self.command = discover_claude(executable)
        if not self.command:
            raise WorkspaceError(
                "Install Claude Code and select its executable in Settings → Advanced.",
                "runtime_missing",
            )
        self.executable = describe(self.command)
        self.secret = token
        self.mcp = mcp
        self.tool_names = [tool for tool in (mcp or {}).get("enabled_tools", [])]
        self.session_id = None
        self.resuming = False
        self.instructions = ""
        self.process = None
        self.process_tree = None
        self.reader = None
        self.pending_inputs = {}
        self.info = {"runtime": "Claude Code", "executable": self.executable}

    # Environment ---------------------------------------------------------------------------
    def environment(self):
        startup = int((self.mcp or {}).get("startup_timeout_sec", 30)) * 1000
        tool = int((self.mcp or {}).get("tool_timeout_sec", 660)) * 1000
        if self.mode == "claude_code":
            # Run as the user set Claude Code up: their config folder, sign-in and auth settings.
            env = user_environment()
            env.update(MCP_TIMEOUT=str(startup), MCP_TOOL_TIMEOUT=str(tool))
            return env
        keep = ("CLAUDE_CODE_GIT_BASH_PATH",)
        env = {
            k: v for k, v in os.environ.items()
            if k in keep or not k.startswith(("OPENAI_", "CODEX_", "ANTHROPIC_", "CLAUDE_", "LLM_"))
        }
        env.update(
            ANTHROPIC_API_KEY=self.secret or "not-connected",
            CLAUDE_CONFIG_DIR=str(self.config_dir),
            CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1",
            DISABLE_AUTOUPDATER="1",
            MCP_TIMEOUT=str(startup),
            MCP_TOOL_TIMEOUT=str(tool),
        )
        return env

    def version(self, timeout=20):
        try:
            result = subprocess.run(
                self.command + ["--version"], capture_output=True, text=True, timeout=timeout,
                cwd=self.cwd, env=self.environment(), encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise WorkspaceError("Claude Code did not start. Check the installation.", "runtime_missing") from None
        if result.returncode:
            raise WorkspaceError("Claude Code did not report its version. Check the installation.", "runtime_missing")
        return result.stdout.strip()

    # Session -----------------------------------------------------------------------------
    def start_thread(self, instructions, model, thread_id=None):
        self.instructions = instructions
        self.resuming = bool(thread_id)
        self.session_id = thread_id or str(uuid4())
        return self.session_id

    def model_catalogue(self):
        return []

    def input_bounds(self, model):
        return None  # Current Claude models accept image input; the API reports any exception per request.

    def arguments(self, model, turn_options):
        prompt_file = self.home / "system-prompt.md"
        prompt_file.write_text(self.instructions, encoding="utf-8")
        args = self.command + [
            "-p",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--model", model,
            "--system-prompt-file", str(prompt_file),
            "--tools", "",
            "--permission-mode", "dontAsk",
        ]
        document = mcp_document(self.mcp)
        if document:
            config = self.home / "mcp-config.json"
            config.write_text(json.dumps(document, allow_nan=False), encoding="utf-8")
            args += ["--mcp-config", str(config), "--strict-mcp-config"]
            if self.tool_names:
                args += ["--allowedTools", ",".join("mcp__cad__" + name for name in self.tool_names)]
        else:
            args += ["--strict-mcp-config"]
        args += ["--resume", self.session_id] if self.resuming else ["--session-id", self.session_id]
        effort = (turn_options or {}).get("effort")
        if effort:
            args += ["--effort", effort]
        return args

    @staticmethod
    def user_message(text, images):
        content = [{"type": "text", "text": text}]
        for path in images:
            path = Path(path).resolve()
            media = mimetypes.guess_type(path.name)[0] or "image/png"
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": media,
                "data": base64.b64encode(path.read_bytes()).decode("ascii")}})
        return {"type": "user", "message": {"role": "user", "content": content}}

    def launch(self, args, message):
        self.process = subprocess.Popen(
            args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=self.cwd, env=self.environment(), text=True, encoding="utf-8", errors="replace",
            bufsize=1, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            self.process_tree = ProcessTree(self.process)
        except Exception:
            self.process.kill()
            self.process.wait(timeout=2)
            raise
        self.inbox = queue.Queue()
        self.stderr_tail = []

        def reader():
            try:
                for line in self.process.stdout:
                    if len(line) > 8 * 1024 * 1024:
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        self.inbox.put(json.loads(line))
                    except ValueError:
                        continue
            except OSError:
                pass
            finally:
                self.inbox.put(None)

        def errors():
            try:
                for line in self.process.stderr:
                    self.stderr_tail = (self.stderr_tail + [line.rstrip()])[-20:]
            except OSError:
                pass

        self.reader = threading.Thread(target=reader, daemon=True)
        self.reader.start()
        threading.Thread(target=errors, daemon=True).start()
        try:
            self.process.stdin.write(json.dumps(message, allow_nan=False) + "\n")
            self.process.stdin.flush()
            self.process.stdin.close()
        except (OSError, ValueError):
            raise WorkspaceError("Claude Code stopped before receiving the request.", "runtime_disconnected") from None

    def scrub(self, text):
        return text.replace(self.secret, "[credential]") if self.secret and text else text

    def run(self, text, model, cancelled, notify, images=(), timeout=CAD_TURN_TIMEOUT_SECONDS, turn_options=None):
        if cancelled.is_set():
            raise WorkspaceError("Task cancelled before inference.", "cancelled")
        if not self.session_id:
            raise WorkspaceError("Start a Claude session before running a turn.", "runtime_disconnected")
        self.launch(self.arguments(model, turn_options), self.user_message(text, images))
        notify({"stage": "agent_running", "message": "Claude is working with the current CAD document."})
        return self.consume(cancelled, notify, time.monotonic() + timeout)

    def consume(self, cancelled, notify, deadline):
        texts, order, tool_messages, current = {}, [], set(), None
        while True:
            if cancelled.is_set():
                self.stop()
                raise WorkspaceError("Task cancelled; unaccepted changes were discarded.", "cancelled")
            if time.monotonic() >= deadline:
                self.stop()
                raise WorkspaceError(CAD_TURN_TIMEOUT_MESSAGE, "runtime_timeout")
            try:
                event = self.inbox.get(timeout=0.2)
            except queue.Empty:
                continue
            if event is None:
                detail = self.scrub(" ".join(self.stderr_tail[-3:]).strip())
                message, code = provider_failure(detail, mode=self.mode) if detail else (
                    "Claude Code stopped before finishing. Unaccepted changes were discarded.", "runtime_disconnected")
                raise WorkspaceError(message, code)
            if event.get("parent_tool_use_id"):
                continue
            kind = event.get("type")
            if kind == "system" and event.get("subtype") == "init":
                if event.get("session_id"):
                    self.session_id = event["session_id"]
                for server in event.get("mcp_servers", []) or []:
                    if server.get("name") == "cad" and server.get("status") not in ("connected", "pending", None):
                        self.stop()
                        raise WorkspaceError("The CAD tools could not start inside Claude Code. Restart the application and retry.",
                                             "runtime_mismatch")
            elif kind == "stream_event":
                inner = event.get("event", {})
                if inner.get("type") == "message_start":
                    current = inner.get("message", {}).get("id") or uuid4().hex
                    if current not in texts:
                        texts[current] = ""
                        order.append(current)
                elif inner.get("type") == "content_block_delta" and inner.get("delta", {}).get("type") == "text_delta":
                    key = current or "message"
                    if key not in texts:
                        texts[key] = ""
                        order.append(key)
                    delta = inner["delta"].get("text", "")
                    texts[key] += delta
                    notify({"stage": "assistant_delta", "message": delta, "item_id": key, "phase": None})
            elif kind == "assistant":
                message = event.get("message", {})
                key = message.get("id") or current or uuid4().hex
                blocks = message.get("content", []) or []
                text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
                if key not in texts:
                    texts[key] = ""
                    order.append(key)
                if text and not texts[key]:
                    texts[key] = text  # Streaming deltas were unavailable for this message.
                if any(b.get("type") == "tool_use" for b in blocks) and key not in tool_messages:
                    tool_messages.add(key)
                    if texts[key].strip():
                        notify({"stage": "agent_progress", "message": texts[key]})
                    notify({"stage": "assistant_message", "message": texts[key], "item_id": key, "phase": "commentary"})
            elif kind == "result":
                usage = event.get("usage") or {}
                counts = {
                    "inputTokens": int(usage.get("input_tokens") or 0) + int(usage.get("cache_creation_input_tokens") or 0)
                                   + int(usage.get("cache_read_input_tokens") or 0),
                    "cachedInputTokens": int(usage.get("cache_read_input_tokens") or 0),
                    "outputTokens": int(usage.get("output_tokens") or 0),
                }
                counts["totalTokens"] = counts["inputTokens"] + counts["outputTokens"]
                notify({"stage": "usage", "kind": "tokens",
                        "observation": {"tokenUsage": {"total": counts}, "increment": True}})
                if event.get("session_id"):
                    self.session_id = event["session_id"]
                if event.get("is_error") or event.get("subtype") != "success":
                    detail = self.scrub(str(event.get("result") or " ".join(event.get("errors", []) or [])))
                    message, code = provider_failure(detail, event.get("subtype", ""), self.mode)
                    raise WorkspaceError(self.scrub(message), code)
                finals = [key for key in order if key not in tool_messages and texts[key].strip()]
                for key in finals:
                    notify({"stage": "assistant_message", "message": texts[key], "item_id": key, "phase": "final_answer"})
                answer = "\n\n".join(texts[key] for key in finals)
                return answer or str(event.get("result") or "")

    def respond(self, identity, answers):
        raise WorkspaceError("Claude asks clarifying questions in the conversation. Reply in the composer.")

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.kill()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        if self.process_tree:
            self.process_tree.close()  # Kill-on-close ends MCP children too.
            self.process_tree = None

    def close(self):
        if self.process:
            try:
                if self.process.poll() is None:
                    self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
            self.stop()
            if self.reader:
                self.reader.join(timeout=1)
            for stream in (self.process.stdout, self.process.stderr):
                try:
                    stream.close()
                except (OSError, AttributeError):
                    pass
            self.process = None
        self.pending_inputs.clear()

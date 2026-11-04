import os
import queue
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.native.contracts import WorkspaceError
from backend.v2.claude_provider import ClaudeCodeRuntime, ClaudeProviderOptions, mcp_document

ROOT = Path(__file__).resolve().parents[2]


def runtime(events=(), secret="sk-ant-fixture-secret"):
    item = ClaudeCodeRuntime.__new__(ClaudeCodeRuntime)
    item.secret = secret
    item.session_id = "fixture-session"
    item.process = None
    item.process_tree = None
    item.reader = None
    item.pending_inputs = {}
    item.stderr_tail = []
    item.inbox = queue.Queue()
    for event in events:
        item.inbox.put(event)
    return item


def delta(text):
    return {"type": "stream_event", "event": {"type": "content_block_delta",
                                              "delta": {"type": "text_delta", "text": text}}}


def start(message_id):
    return {"type": "stream_event", "event": {"type": "message_start", "message": {"id": message_id}}}


class ClaudeStreamTests(unittest.TestCase):
    def consume(self, events):
        notes = []
        item = runtime(events)
        return item, item.consume(threading.Event(), notes.append, float("inf")), notes

    def test_tool_commentary_is_activity_and_final_text_is_the_answer(self):
        _, answer, notes = self.consume([
            {"type": "system", "subtype": "init", "session_id": "resolved-session",
             "mcp_servers": [{"name": "cad", "status": "connected"}]},
            start("m1"), delta("Inspecting the plate."),
            {"type": "assistant", "message": {"id": "m1", "content": [
                {"type": "text", "text": "Inspecting the plate."},
                {"type": "tool_use", "id": "t1", "name": "mcp__cad__cad_inspect", "input": {}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1"}]}},
            start("m2"), delta("Added a 4 mm "), delta("fillet."),
            {"type": "assistant", "message": {"id": "m2", "content": [{"type": "text", "text": "Added a 4 mm fillet."}]}},
            {"type": "result", "subtype": "success", "is_error": False, "result": "Added a 4 mm fillet.",
             "session_id": "resolved-session",
             "usage": {"input_tokens": 10, "cache_read_input_tokens": 5, "output_tokens": 3}},
        ])
        self.assertEqual(answer, "Added a 4 mm fillet.")
        self.assertIn({"stage": "agent_progress", "message": "Inspecting the plate."}, notes)
        phases = {n["item_id"]: n["phase"] for n in notes if n["stage"] == "assistant_message"}
        self.assertEqual(phases, {"m1": "commentary", "m2": "final_answer"})
        usage = next(n for n in notes if n["stage"] == "usage")
        self.assertTrue(usage["observation"]["increment"])
        self.assertEqual(usage["observation"]["tokenUsage"]["total"],
                         {"inputTokens": 15, "cachedInputTokens": 5, "outputTokens": 3, "totalTokens": 18})

    def test_session_id_reported_by_runtime_is_retained(self):
        item, _, _ = self.consume([
            {"type": "system", "subtype": "init", "session_id": "resolved-session"},
            {"type": "result", "subtype": "success", "result": "Done.", "session_id": "resolved-session"},
        ])
        self.assertEqual(item.session_id, "resolved-session")

    def test_credit_failure_is_a_usage_limit_without_leaking_the_key(self):
        item = runtime([{"type": "result", "subtype": "success", "is_error": True,
                         "result": "Credit balance is too low for sk-ant-fixture-secret"}])
        with self.assertRaises(WorkspaceError) as failed:
            item.consume(threading.Event(), lambda e: None, float("inf"))
        self.assertEqual(failed.exception.code, "usage_limit")
        self.assertNotIn("sk-ant-fixture-secret", str(failed.exception))

    def test_rejected_key_requests_reconnection(self):
        item = runtime([{"type": "result", "subtype": "success", "is_error": True,
                         "result": "Invalid API key · Fix external API key"}])
        with self.assertRaises(WorkspaceError) as failed:
            item.consume(threading.Event(), lambda e: None, float("inf"))
        self.assertEqual(failed.exception.code, "reauthorization_required")

    def test_unexpected_exit_reports_disconnection(self):
        item = runtime([None])
        with self.assertRaises(WorkspaceError) as failed:
            item.consume(threading.Event(), lambda e: None, float("inf"))
        self.assertEqual(failed.exception.code, "runtime_disconnected")

    def test_cancellation_stops_before_completion(self):
        cancelled = threading.Event()
        cancelled.set()
        item = runtime([{"type": "result", "subtype": "success", "result": "Done."}])
        with self.assertRaises(WorkspaceError) as stopped:
            item.consume(cancelled, lambda e: None, float("inf"))
        self.assertEqual(stopped.exception.code, "cancelled")

    def test_subagent_messages_are_ignored(self):
        _, answer, _ = self.consume([
            {"type": "assistant", "parent_tool_use_id": "x",
             "message": {"id": "sub", "content": [{"type": "text", "text": "subagent"}]}},
            {"type": "assistant", "message": {"id": "m", "content": [{"type": "text", "text": "Main."}]}},
            {"type": "result", "subtype": "success", "result": "Main."},
        ])
        self.assertEqual(answer, "Main.")

    def test_clarification_answers_are_given_in_conversation(self):
        with self.assertRaises(WorkspaceError):
            runtime().respond(1, {})


class ClaudeLaunchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT / "tmp")
        self.home = Path(self.temporary.name)
        self.fake = self.home / "claude.exe"
        self.fake.write_bytes(b"")
        self.mcp = {"command": "pythonw.exe", "args": ["-B", "-m", "backend.v2.mcp_server"],
                    "env": {"PROMPTCAD_TOOL_TOKEN": "fixture"}, "enabled_tools": ["cad_inspect", "cad_apply"],
                    "startup_timeout_sec": 30, "tool_timeout_sec": 660}

    def tearDown(self):
        self.temporary.cleanup()

    def test_arguments_isolate_cad_tools_and_resume_sessions(self):
        item = ClaudeCodeRuntime(self.home, str(self.fake), "sk-ant-fixture", mcp=self.mcp)
        item.start_thread("CAD instructions", "claude-sonnet-fixture")
        args = item.arguments("claude-sonnet-fixture", {"effort": "high"})
        self.assertEqual(args[args.index("--tools") + 1], "")
        self.assertEqual(args[args.index("--permission-mode") + 1], "dontAsk")
        self.assertIn("--strict-mcp-config", args)
        self.assertEqual(args[args.index("--allowedTools") + 1], "mcp__cad__cad_inspect,mcp__cad__cad_apply")
        self.assertEqual(args[args.index("--session-id") + 1], item.session_id)
        self.assertEqual(args[args.index("--effort") + 1], "high")
        self.assertEqual((self.home / "system-prompt.md").read_text(encoding="utf-8"), "CAD instructions")
        item.start_thread("CAD instructions", "claude-sonnet-fixture", "earlier-session")
        args = item.arguments("claude-sonnet-fixture", {})
        self.assertEqual(args[args.index("--resume") + 1], "earlier-session")
        self.assertNotIn("--effort", args)

    def test_environment_uses_only_the_connected_key_and_private_config(self):
        item = ClaudeCodeRuntime(self.home, str(self.fake), "sk-ant-fixture", mcp=self.mcp)
        with patch.dict(os.environ, {"ANTHROPIC_BASE_URL": "https://example.invalid", "CLAUDE_CONFIG_DIR": "user",
                                     "OPENAI_API_KEY": "other"}):
            env = item.environment()
        self.assertEqual(env["ANTHROPIC_API_KEY"], "sk-ant-fixture")
        self.assertEqual(env["CLAUDE_CONFIG_DIR"], str(item.config_dir))
        self.assertNotIn("ANTHROPIC_BASE_URL", env)
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertEqual(env["MCP_TOOL_TIMEOUT"], "660000")

    def test_missing_runtime_explains_installation(self):
        with self.assertRaises(WorkspaceError) as missing:
            ClaudeCodeRuntime(self.home, str(self.home / "absent.exe"))
        self.assertEqual(missing.exception.code, "runtime_missing")

    def test_mcp_document_uses_claude_schema(self):
        server = mcp_document(self.mcp)["mcpServers"]["cad"]
        self.assertEqual(server["type"], "stdio")
        self.assertEqual(server["args"], ["-B", "-m", "backend.v2.mcp_server"])
        self.assertNotIn("enabled_tools", server)

    def test_effort_levels_depend_on_model_family(self):
        options = ClaudeProviderOptions()
        sonnet = [o["id"] for o in options.reasoning_effort({"id": "claude-sonnet-5-5"})["options"]]
        opus = [o["id"] for o in options.reasoning_effort({"id": "claude-opus-5-5"})["options"]]
        self.assertEqual(sonnet, ["low", "medium", "high"])
        self.assertEqual(opus, ["low", "medium", "high", "xhigh", "max"])
        self.assertEqual(options.reasoning_effort(None)["state"], "unavailable")


@unittest.skipUnless(os.name == "nt", "DPAPI credential storage requires Windows")
class ClaudeConnectionTests(unittest.TestCase):
    def setUp(self):
        from backend.v2.auth import Connections
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT / "tmp")
        self.connections = Connections(Path(self.temporary.name))

    def tearDown(self):
        self.temporary.cleanup()

    def test_key_shape_is_checked_before_any_request(self):
        with patch("backend.v2.auth.request_json") as request:
            for key in ("sk-proj-openai-style-key-000000", "sk-ant-admin01-fixture-000000000"):
                with self.assertRaises(WorkspaceError):
                    self.connections.anthropic_key(key)
        request.assert_not_called()

    def test_validated_key_becomes_the_active_claude_connection(self):
        with patch("backend.v2.auth.request_json", return_value={"data": []}) as request:
            status = self.connections.anthropic_key("sk-ant-api03-fixture-key-000000")
        self.assertEqual(request.call_args.kwargs["headers"]["x-api-key"], "sk-ant-api03-fixture-key-000000")
        self.assertEqual(status["state"], "ready")
        self.assertEqual(status["provider_id"], "claude")
        self.assertEqual(status["billing"], "Anthropic API billing (separate)")
        self.assertTrue(status["providers"]["claude"]["saved"])
        self.assertNotIn("sk-ant-api03", str(status))

    def test_switching_providers_keeps_each_saved_credential(self):
        with patch("backend.v2.auth.request_json", return_value={"data": []}):
            self.connections.api_key("fixture-openai-key-never-transmitted")
            self.connections.anthropic_key("sk-ant-api03-fixture-key-000000")
        codex = self.connections.use_provider("codex")
        self.assertEqual(codex["provider_id"], "codex")
        self.assertEqual(codex["active"]["connection"], "api")
        claude = self.connections.use_provider("claude")
        self.assertEqual(claude["active"]["connection"], "anthropic")

    def test_choosing_an_unconnected_provider_waits_for_its_credential(self):
        with patch("backend.v2.auth.request_json", return_value={"data": []}):
            self.connections.anthropic_key("sk-ant-api03-fixture-key-000000")
        status = self.connections.use_provider("codex")
        self.assertEqual(status["provider_id"], "codex")
        self.assertEqual(status["state"], "disconnected")
        self.assertTrue(status["providers"]["claude"]["saved"])

    def test_claude_catalogue_lists_image_capable_models(self):
        with patch("backend.v2.auth.request_json", return_value={"data": []}):
            self.connections.anthropic_key("sk-ant-api03-fixture-key-000000")
        page = {"data": [{"id": "claude-sonnet-fixture", "display_name": "Claude Sonnet Fixture"}], "has_more": False}
        with patch("backend.v2.auth.request_json", return_value=page):
            models = self.connections.models(True)["models"]
        self.assertEqual(models[0]["name"], "Claude Sonnet Fixture")
        self.assertEqual(models[0]["inputModalities"], ["text", "image"])


if __name__ == "__main__":
    unittest.main()

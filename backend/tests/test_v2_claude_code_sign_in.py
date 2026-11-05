import json
import os
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.native.contracts import WorkspaceError
from backend.v2 import claude_provider
from backend.v2.claude_provider import ClaudeCodeRuntime, auth_status, provider_failure
from backend.tests.test_v2_claude_provider import runtime

ROOT = Path(__file__).resolve().parents[2]


def completed(code, payload):
    return subprocess.CompletedProcess([], code, stdout=json.dumps(payload), stderr="")


class ClaudeCodeSignInRuntimeTests(unittest.TestCase):
    """Using the user's own Claude Code sign-in: run as installed, never touch credentials."""

    def setUp(self):
        (ROOT / "tmp").mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT / "tmp")
        self.home = Path(self.temporary.name)
        self.fake = self.home / "claude.exe"
        self.fake.write_bytes(b"")

    def tearDown(self):
        self.temporary.cleanup()

    def test_environment_keeps_the_users_own_claude_setup(self):
        item = ClaudeCodeRuntime(self.home, str(self.fake), None, "claude_code")
        user = {"CLAUDE_CONFIG_DIR": "fixture-user-claude-config", "ANTHROPIC_API_KEY": "sk-ant-users-own",
                "CLAUDE_CODE_USE_BEDROCK": "1", "OPENAI_API_KEY": "unrelated"}
        base = {k: v for k, v in os.environ.items()
                if not k.startswith(("ANTHROPIC_", "CLAUDE_", "OPENAI_")) and k != "DISABLE_AUTOUPDATER"}
        with patch.dict(os.environ, {**base, **user}, clear=True):
            env = item.environment()
        self.assertEqual(env["CLAUDE_CONFIG_DIR"], "fixture-user-claude-config")
        self.assertEqual(env["ANTHROPIC_API_KEY"], "sk-ant-users-own")
        self.assertEqual(env["CLAUDE_CODE_USE_BEDROCK"], "1")
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("DISABLE_AUTOUPDATER", env)
        self.assertFalse((self.home / "claude-config").exists())

    def test_app_injects_no_credential_when_the_user_has_none_in_their_environment(self):
        item = ClaudeCodeRuntime(self.home, str(self.fake), None, "claude_code")
        clean = {k: v for k, v in os.environ.items() if not k.startswith(("ANTHROPIC_", "CLAUDE_"))}
        with patch.dict(os.environ, clean, clear=True):
            env = item.environment()
        self.assertFalse(any(k.startswith(("ANTHROPIC_", "CLAUDE_")) for k in env))

    def test_turn_still_isolates_cad_tools(self):
        item = ClaudeCodeRuntime(self.home, str(self.fake), None, "claude_code",
                                 {"command": "py", "args": [], "env": {}, "enabled_tools": ["cad_inspect"]})
        item.start_thread("CAD instructions", "sonnet")
        args = item.arguments("sonnet", {})
        self.assertEqual(args[args.index("--tools") + 1], "")
        self.assertIn("--strict-mcp-config", args)
        self.assertEqual(args[args.index("--allowedTools") + 1], "mcp__cad__cad_inspect")

    def test_sign_in_failures_ask_the_user_to_sign_in_again(self):
        message, code = provider_failure("Not logged in · Please run /login", mode="claude_code")
        self.assertEqual(code, "reauthorization_required")
        self.assertIn("Sign in again", message)
        _, code = provider_failure("Claude usage limit reached · resets 5pm", mode="claude_code")
        self.assertEqual(code, "usage_limit")

    def test_stream_failure_uses_sign_in_wording(self):
        item = runtime([{"type": "result", "subtype": "success", "is_error": True, "result": "Login expired · Please run /login"}],
                       secret=None, mode="claude_code")
        with self.assertRaises(WorkspaceError) as failed:
            item.consume(threading.Event(), lambda e: None, float("inf"))
        self.assertEqual(failed.exception.code, "reauthorization_required")


class ClaudeCodeDiscoveryTests(unittest.TestCase):
    """The Claude desktop app keeps its own copy of Claude Code; use it when no CLI is installed."""

    def setUp(self):
        (ROOT / "tmp").mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT / "tmp")
        self.appdata = Path(self.temporary.name)
        self.bundle = self.appdata / "Claude" / "claude-code"

    def tearDown(self):
        self.temporary.cleanup()

    def install(self, version, stamp):
        path = self.bundle / version / "build" / "claude.exe"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"")
        os.utime(path, (stamp, stamp))
        return path

    def discover(self, configured=None):
        with patch.dict(os.environ, {"APPDATA": str(self.appdata), "PROMPTCAD_CLAUDE": ""}),                 patch.object(claude_provider.shutil, "which", return_value=None),                 patch.object(claude_provider.Path, "home", return_value=self.appdata / "home"),                 patch.object(claude_provider.os, "name", "nt"):
            return claude_provider.discover_claude(configured)

    def test_newest_desktop_copy_is_found(self):
        self.install("2.1.300", 1000)
        newest = self.install("2.1.317", 2000)
        self.assertEqual(self.discover(), [str(newest)])

    def test_saved_desktop_copy_that_was_updated_away_falls_back(self):
        current = self.install("2.1.317", 2000)
        self.assertEqual(self.discover(str(self.bundle / "2.1.300" / "build" / "claude.exe")), [str(current)])

    def test_other_missing_saved_paths_stay_missing(self):
        self.install("2.1.317", 2000)
        self.assertIsNone(self.discover(str(self.appdata / "elsewhere" / "claude.exe")))


class ClaudeCodeAuthStatusTests(unittest.TestCase):
    def test_signed_in_plan_is_reported_by_method_only(self):
        with patch.object(claude_provider.subprocess, "run", return_value=completed(0, {"authMethod": "claude.ai"})) as run:
            report = auth_status(["claude.exe"])
        self.assertEqual(run.call_args.args[0], ["claude.exe", "auth", "status"])
        self.assertTrue(report["signed_in"])
        self.assertEqual(report["method"], "Claude plan sign-in")

    def test_not_signed_in(self):
        with patch.object(claude_provider.subprocess, "run", return_value=completed(1, {"authMethod": "none"})):
            report = auth_status(["claude.exe"])
        self.assertFalse(report["signed_in"])
        self.assertIn("Sign in", report["message"])

    def test_missing_or_unresponsive_runtime(self):
        self.assertFalse(auth_status(None)["installed"])
        with patch.object(claude_provider.subprocess, "run", side_effect=subprocess.TimeoutExpired("claude", 20)):
            report = auth_status(["claude.exe"])
        self.assertTrue(report["installed"])
        self.assertFalse(report["signed_in"])

    def test_sign_in_opens_claude_codes_own_flow(self):
        with patch.object(claude_provider.subprocess, "Popen") as popen:
            claude_provider.open_sign_in(["claude.exe"])
        self.assertEqual(popen.call_args.args[0], ["claude.exe", "auth", "login"])


@unittest.skipUnless(os.name == "nt", "DPAPI credential storage requires Windows")
class ClaudeCodeConnectionTests(unittest.TestCase):
    def setUp(self):
        from backend.v2.auth import Connections
        (ROOT / "tmp").mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT / "tmp")
        self.connections = Connections(Path(self.temporary.name))

    def tearDown(self):
        self.temporary.cleanup()

    def test_using_claude_code_stores_no_secret(self):
        status = self.connections.claude_code()
        self.assertEqual(status["provider_id"], "claude")
        self.assertEqual(status["state"], "ready")
        self.assertEqual(status["active"]["connection"], "claude_code")
        account_id, account = self.connections.credential()
        self.assertFalse(any(k in account for k in ("api_key", "access_token", "refresh_token")))

    def test_aliases_are_offered_without_a_network_request(self):
        self.connections.claude_code()
        with patch("backend.v2.auth.request_json") as request:
            models = [m["id"] for m in self.connections.models(True)["models"]]
        request.assert_not_called()
        self.assertEqual(models, ["sonnet", "opus", "haiku"])

    def test_stop_using_and_switching_back(self):
        with patch("backend.v2.auth.request_json", return_value={"data": []}):
            self.connections.api_key("fixture-openai-key-never-transmitted")
        self.connections.claude_code()
        self.assertEqual(self.connections.use_provider("codex")["active"]["connection"], "api")
        self.assertEqual(self.connections.use_provider("claude")["active"]["connection"], "claude_code")
        stopped = self.connections.disconnect()
        self.assertIn("stay signed in to Claude Code", stopped["message"])
        self.assertEqual(self.connections.use_provider("claude")["state"], "disconnected")
        self.assertEqual(self.connections.claude_code()["state"], "ready")


if __name__ == "__main__":
    unittest.main()

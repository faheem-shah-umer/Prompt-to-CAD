"""Focused tests for bundled CAD skills and project-local load evidence."""

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.native.contracts import WorkspaceError
from backend.v2 import agent_skills
from backend.v2.cad_tools import TOOLS, TaskTools
from backend.v2.turn_logs import TurnLog

ROOT = Path(__file__).resolve().parents[2]


class AgentSkillTests(unittest.TestCase):
    def test_registered_skills_have_valid_manifests(self):
        descriptor = agent_skills.describe()
        self.assertEqual([item["id"] for item in descriptor["available"]], list(agent_skills.SKILL_IDS))
        for item in descriptor["available"]:
            skill = agent_skills.read(item["id"])
            self.assertEqual(skill["name"], item["id"])
            self.assertEqual(skill["version"], "1.0.0")
            self.assertEqual(skill["sha256"], item["sha256"])
            self.assertTrue(skill["content"].startswith("---\n"))
            self.assertNotIn("PROMPTCAD_TOOL_TOKEN", skill["content"])
            self.assertNotRegex(skill["content"], r"[A-Za-z]:\\Users\\")

    def test_skill_reader_accepts_only_registered_ids(self):
        for invalid in (None, "../promptcad-modeling", "C:/private/SKILL.md", "other-skill"):
            with self.subTest(invalid=invalid), self.assertRaises(WorkspaceError) as failure:
                agent_skills.read(invalid)
            self.assertEqual(failure.exception.code, "invalid_skill")

    def test_missing_skill_is_reported_without_blocking_discovery(self):
        with patch.object(agent_skills, "SKILLS_ROOT", ROOT / ".local" / "missing-skills-fixture"):
            descriptor = agent_skills.describe()
        self.assertEqual(len(descriptor["available"]), len(agent_skills.SKILL_IDS))
        self.assertTrue(all(item.get("available") is False for item in descriptor["available"]))
        self.assertTrue(all("path" not in item for item in descriptor["available"]))

    def test_skill_tool_is_registered_as_read_only_and_fixed_id(self):
        tool = next(tool for tool in TOOLS if tool["name"] == "cad_skills")
        self.assertTrue(tool["annotations"]["readOnlyHint"])
        self.assertEqual(tool["inputSchema"]["properties"]["skill_id"]["enum"], list(agent_skills.SKILL_IDS))
        self.assertFalse(tool["inputSchema"]["additionalProperties"])

    def test_task_tools_dispatches_fixed_skill_reads_without_candidate_mutation(self):
        class WorkspaceStub:
            application_runtime = None
            cancelled = threading.Event()

        tools = TaskTools.__new__(TaskTools)
        tools.workspace = WorkspaceStub()
        tools.closed = False
        tools.lock = threading.RLock()
        result = tools._call("cad_skills", {"action": "read", "skill_id": "promptcad-catalog"})
        self.assertEqual(result["skill"]["id"], "promptcad-catalog")
        with self.assertRaises(WorkspaceError):
            tools._call("cad_skills", {"action": "read", "skill_id": "../outside"})

    def test_plugin_manifests_point_to_the_canonical_skill_folders(self):
        for relative in (".codex-plugin/plugin.json", ".claude-plugin/plugin.json"):
            manifest = json.loads((ROOT / relative).read_text(encoding="utf-8"))
            self.assertEqual(manifest["skills"], "./skills/")
            self.assertTrue((ROOT / "skills" / "promptcad-modeling" / "SKILL.md").is_file())

    def test_turn_log_records_availability_and_load_without_copying_skill_text(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".local") as temporary:
            project = Path(temporary) / "project"
            project.mkdir()
            task = {"task_id": "skill-test", "started_at": time.time(), "prompt": "Review the design."}
            log = TurnLog(project, task, "synthetic-project")
            descriptor = agent_skills.describe()
            log.skill_availability(descriptor)
            result = agent_skills.list_or_read("read", "promptcad-review")
            call = log.tool_started("cad_skills", {"action": "read", "skill_id": "promptcad-review"})
            log.tool_finished(call, result=result)
            log.finish({"status": "completed_no_change", "completed_at": time.time(), "message": "reviewed"})

            summary = json.loads((log.folder / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["agent_skills_usage"]["available_ids"], list(agent_skills.SKILL_IDS))
            self.assertEqual(summary["agent_skills_usage"]["loaded"][0]["id"], "promptcad-review")
            self.assertEqual(summary["agent_skills_usage"]["loaded"][0]["status"], "loaded")
            events = [json.loads(line) for line in (log.folder / "events.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertTrue(any(event["event"] == "skills_available" for event in events))
            loaded = next(event for event in events if event["event"] == "tool_succeeded" and event.get("name") == "cad_skills")
            self.assertEqual(loaded["result"]["content"], "[skill instructions omitted from log]")
            self.assertNotIn("Use this workflow when checking", json.dumps(events))


if __name__ == "__main__":
    unittest.main()

"""Synthetic project-local audit evidence; no live provider or private projects."""

import copy
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend.native.contracts import WorkspaceError
from backend.v2.cad_tools import TaskTools
from backend.v2.projects import Projects
from backend.v2.turn_logs import TurnLog, folder, record_folder, safe

ROOT = Path(__file__).resolve().parents[2]


class TurnLogTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "tmp").mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT / "tmp")
        self.project = Path(self.temporary.name)
        self.task = {"task_id": "synthetic-turn", "document_id": "doc", "conversation_id": "chat",
            "started_at": time.time(), "prompt": "Add a synthetic M6 screw.", "model": "test-model"}
        self.log = TurnLog(self.project, self.task, "synthetic-project")

    def tearDown(self):
        self.temporary.cleanup()

    def summary(self):
        return json.loads((self.log.folder / "summary.json").read_text(encoding="utf-8"))

    def tools(self):
        workspace = SimpleNamespace(cancelled=threading.Event())
        snapshot = {"components": [], "document_id": "doc", "revision_id": None}
        tools = TaskTools(workspace, SimpleNamespace(folder=self.project), snapshot, None, "project", "task")
        tools.turn_log = self.log
        return tools

    def test_stated_reasons_are_separate_from_generation_and_acceptance(self):
        tools = self.tools()
        token = tools.candidate_id
        tools.call("cad_decision", {"candidate_id": token, "summary": "Use a catalog fastener.",
            "cq_warehouse": {"choice": "use", "reason": "The ISO standard and dimensions match."},
            "alternatives": ["A custom script would duplicate the catalog geometry."]})
        self.assertEqual(tools.candidate_id, token)
        self.assertEqual(tools.commands, [])
        discovered = self.log.tool_started("cad_standard_parts", {"family": "fastener"})
        self.log.tool_finished(discovered, {"families": {"fastener": []}})
        self.assertEqual(self.summary()["cq_warehouse"]["generation_attempts"], 0)
        attempt = self.log.tool_started("cad_standard_part", {"generator_id": "fastener.HexNut"}, True, "fastener.HexNut")
        self.log.tool_finished(attempt, {"candidate_id": "next"})
        self.log.finish({"status": "completed", "result_revision_id": "accepted", "completed_at": time.time()})
        summary = self.summary()
        self.assertEqual(summary["cq_warehouse"]["successful_calls_in_accepted_turn"], 1)
        self.assertEqual(summary["decisions"][0]["cq_warehouse"]["reason"], "The ISO standard and dimensions match.")
        self.assertIn("Use a catalog fastener.", (self.log.folder / "summary.md").read_text(encoding="utf-8"))

    def test_failed_tools_retain_error_and_do_not_fake_library_success(self):
        tools = self.tools()
        before = copy.deepcopy(tools.candidate)
        with patch.object(tools, "_call", side_effect=WorkspaceError("Unsupported size", "invalid_parameters")), self.assertRaises(WorkspaceError):
            tools.call("cad_standard_part", {"generator_id": "fastener.HexNut"})
        self.assertEqual(tools.candidate, before)
        self.log.finish({"status": "failed", "message": "Unsupported size"})
        summary = self.summary()
        self.assertEqual(summary["tools"][0]["error"]["code"], "invalid_parameters")
        self.assertEqual(summary["cq_warehouse"]["successful_generation_calls"], 0)
        self.assertEqual(summary["cq_warehouse"]["explanation_status"], "not_provided")
        self.assertEqual(summary["decisions"], [])

    def test_successful_candidate_in_cancelled_turn_is_not_accepted(self):
        call = self.log.tool_started("cad_standard_part", {}, True, "sprocket.Sprocket")
        self.log.tool_finished(call, {"candidate_id": "unaccepted"})
        self.log.finish({"status": "cancelled"})
        usage = self.summary()["cq_warehouse"]
        self.assertEqual((usage["successful_generation_calls"], usage["successful_calls_in_accepted_turn"]), (1, 0))

    def test_numeric_standard_regeneration_is_recorded_as_library_use(self):
        tools = self.tools()
        tools.candidate["components"] = [{"instance_id": "nut", "standard_part": {"generator_id": "fastener.HexNut"}}]
        with patch.object(tools, "_call", return_value={"candidate_id": "updated"}):
            tools.call("cad_apply", {"command": {"type": "parameters", "instance_id": "nut", "values": {"length": 12}}})
        self.assertEqual(self.summary()["cq_warehouse"]["generator_ids"], ["fastener.HexNut"])

    def test_known_secrets_paths_images_and_source_are_not_dumped(self):
        key = "sk-" + "synthetic" * 8
        payload = {"access_token": key, "image_data": "synthetic-pixels", "source": "parts = {'private': '" + key + "'}",
            "message": "Authorization: Bearer " + key + " at C:\\Users\\Example\\private.step",
            "email": "person@example.invalid", "parameter": {"diameter": 6}}
        result = safe(payload)
        output = json.dumps(result)
        self.assertNotIn(key, output)
        self.assertNotIn("synthetic-pixels", output)
        self.assertNotIn("parts =", output)
        self.assertNotIn("private.step", output)
        self.assertEqual(result["parameter"]["diameter"], 6)

    def test_restart_marks_pending_calls_interrupted_without_inventing_reason(self):
        self.log.tool_started("cad_standard_part", {}, True, "chain.Chain")
        events = self.log.folder / "events.jsonl"
        with events.open("a", encoding="utf-8") as stream:
            stream.write('{"partial":')
        TurnLog.recover(self.project, {**self.task, "turn_log": "logs/turns/" + self.task["task_id"], "status": "interrupted"})
        summary = self.summary()
        self.assertEqual(summary["status"], "interrupted")
        self.assertEqual(summary["tools"][0]["status"], "interrupted")
        self.assertEqual(summary["cq_warehouse"]["acceptance"], "unknown")
        last = json.loads(events.read_text(encoding="utf-8").splitlines()[-1])
        self.assertGreater(last["sequence"], 1)

    def test_logging_write_failure_does_not_turn_a_successful_tool_into_failure(self):
        tools = self.tools()
        with patch("backend.v2.turn_logs.write_json", side_effect=OSError("synthetic disk failure")), patch.object(tools, "_call", return_value={"ok": True}):
            self.assertEqual(tools.call("cad_context", {}), {"ok": True})
        self.assertEqual(self.log.error, "OSError")

    def test_log_paths_cannot_escape_the_project(self):
        with self.assertRaises(WorkspaceError):
            folder(self.project, "../outside")
        with self.assertRaises(WorkspaceError):
            record_folder(self.project, {"turn_log": "../summary.json"})

    def test_phase_timings_are_local_and_privacy_safe(self):
        self.log.phase("provider_transport_wait", 1.25)
        self.log.phase(
            "assembly_verification",
            0.5,
            candidate_pairs=12,
            skipped_pairs=10,
            exact_intersections_checked=2,
        )
        self.log.finish({"status": "completed", "message": "done"})
        summary = self.summary()
        self.assertEqual(summary["phase_timings"]["assembly_verification"]["candidate_pairs"], 12)
        self.assertEqual(summary["phase_timings"]["assembly_verification"]["skipped_pairs"], 10)
        self.assertNotIn(str(self.project), json.dumps(summary))
        self.assertTrue((self.log.folder / "events.jsonl").is_file())

    def test_provider_turn_and_transport_wait_are_distinct_diagnostic_phases(self):
        call = self.log.tool_started("cad_script", {"source": "private"})
        self.log.tool_finished(call, {"candidate_id": "candidate"})
        self.log.phase("provider_turn", 4.0)
        self.log.phase("provider_transport_wait", 3.0)
        self.log.finish({"status": "completed", "message": "done"})
        summary = self.summary()
        self.assertEqual(summary["phase_timings"]["provider_turn"]["elapsed_seconds"], 4.0)
        self.assertEqual(summary["phase_timings"]["provider_transport_wait"]["elapsed_seconds"], 3.0)
        self.assertAlmostEqual(
            self.log.tool_elapsed(),
            summary["phase_timings"]["script_execution"]["elapsed_seconds"],
            places=5,
        )

    def test_conversation_purge_removes_its_log_files(self):
        projects = Projects(self.project / "collection")
        project = projects.create("Synthetic audit project")
        pid = project["project_id"]
        chat = projects.conversation(pid)
        task = {**self.task, "conversation_id": chat["conversation_id"], "document_id": chat["document_id"],
            "status": "completed", "turn_log": "logs/turns/" + self.task["task_id"]}
        log = TurnLog(projects.project_path(pid), task, pid)
        log.finish(task)
        projects.task(pid, task)
        chat["trashed"] = True
        projects.save_conversation(pid, chat)
        projects.purge(pid, chat["conversation_id"])
        self.assertFalse((log.folder / "events.jsonl").exists())
        self.assertFalse((log.folder / "summary.md").exists())


if __name__ == "__main__":
    unittest.main()

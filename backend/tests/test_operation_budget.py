import copy
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend.native.contracts import WorkspaceError
from backend.v2.cad_tools import TOOLS, TaskTools


class OperationBudgetTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = {
            "document_id": "doc",
            "revision_id": "rev",
            "components": [{
                "instance_id": "part",
                "name": "Part",
                "asset_hash": "asset",
                "matrix": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0],
                "metrics": {},
                "topology": {},
            }],
            "engineering": [],
            "definitions": [],
        }
        self.workspace = SimpleNamespace(
            cancelled=threading.Event(),
            application_runtime=None,
            notify=lambda event: None,
            geometry=lambda method, params, timeout=None: {},
        )
        self.document = SimpleNamespace(folder=Path("."))
        self.tools = TaskTools(self.workspace, self.document, self.snapshot, None, "project", "task")

    def fake_write(self, name="Part"):
        candidate = copy.deepcopy(self.tools.candidate)
        candidate["components"][0]["name"] = name if name != "Part" else f"Part-{len(self.tools.commands) + 1}"
        return candidate

    def test_normal_budget_is_32_and_read_only_calls_are_free(self):
        self.assertEqual(self.tools.context()["operation_budget"], {"used": 0, "limit": 32, "remaining": 32, "mode": "normal"})
        self.tools.call("cad_context", {})
        self.tools.call("cad_capabilities", {})
        self.assertEqual(len(self.tools.commands), 0)
        self.assertEqual(self.tools.call("cad_capabilities", {})["operation_budget"]["limit"], 32)

    def test_agent_declared_complex_mode_allows_64(self):
        result = self.tools.call("cad_capabilities", {"complex_design": True})
        self.assertEqual(result["limits"]["operations"], 64)
        self.assertEqual(result["operation_budget"]["remaining"], 64)

    def test_batch_schema_and_worker_policy_remain_32(self):
        batch = next(tool for tool in TOOLS if tool["name"] == "cad_apply_batch")
        self.assertEqual(batch["inputSchema"]["properties"]["commands"]["maxItems"], 32)
        with patch("backend.native.geometry.COMMAND.validate_python"), self.assertRaises(WorkspaceError) as error:
            from backend.native.geometry import apply_face_batch
            apply_face_batch(".", {}, [{}] * 33)
        self.assertIn("1–32", str(error.exception))

    def test_batch_accounts_each_contained_edit_and_failed_mutation_rolls_back(self):
        batch = [{"type": "offset_face", "instance_id": "part", "face_index": 1, "distance": 1}] * 3
        with patch("backend.v2.cad_tools.check_command"), patch.object(self.tools, "geometry", return_value=self.fake_write()):
            result = self.tools.call("cad_apply_batch", {"candidate_id": self.tools.candidate_id, "commands": batch})
        self.assertEqual(result["operation_budget"], {"used": 3, "limit": 32, "remaining": 29})
        before = copy.deepcopy(self.tools.candidate)
        with patch("backend.v2.cad_tools.check_command"), patch.object(
            self.tools, "geometry", side_effect=WorkspaceError("bad geometry", "geometry_failed")
        ), self.assertRaises(WorkspaceError):
            self.tools.call("cad_apply", {
                "candidate_id": self.tools.candidate_id,
                "command": {"type": "transform", "instance_id": "part"},
            })
        self.assertEqual(self.tools.candidate, before)
        self.assertEqual(len(self.tools.commands), 3)

    def test_budget_rejects_at_32_then_complex_mode_continues_saved_candidate(self):
        with patch("backend.v2.cad_tools.check_command"), patch.object(self.tools, "geometry", side_effect=lambda *args, **kwargs: self.fake_write()):
            for _ in range(32):
                self.tools.call("cad_apply", {
                    "candidate_id": self.tools.candidate_id,
                    "command": {"type": "transform", "instance_id": "part"},
                })
        with patch("backend.v2.cad_tools.check_command"), self.assertRaises(WorkspaceError) as error:
            self.tools.call("cad_apply", {
                "candidate_id": self.tools.candidate_id,
                "command": {"type": "transform", "instance_id": "part"},
            })
        self.assertEqual(error.exception.code, "operation_limit")
        self.assertIn("in-memory candidate is not saved", str(error.exception))
        self.assertIn("Validate and accept", str(error.exception))
        self.tools.call("cad_capabilities", {"complex_design": True})
        with patch("backend.v2.cad_tools.check_command"), patch.object(self.tools, "geometry", return_value=self.fake_write("continued")):
            result = self.tools.call("cad_apply", {
                "candidate_id": self.tools.candidate_id,
                "command": {"type": "transform", "instance_id": "part"},
            })
        self.assertEqual(result["operation_budget"]["used"], 33)


if __name__ == "__main__":
    unittest.main()

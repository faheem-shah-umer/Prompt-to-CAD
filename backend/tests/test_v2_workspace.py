import json
import math
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.native.contracts import WorkspaceError
from backend.v2.cad_tools import TaskTools
from backend.v2.workspace import WorkspaceV2

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(os.name == "nt", "V2 native workers and DPAPI require Windows")
class V2WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT / "tmp")
        self.folder = Path(self.temporary.name)
        self.workspace = WorkspaceV2(self.folder)
        self.workspace.dispatch("v2.project.create", {"name": "Fixture assembly"})

    def tearDown(self):
        self.workspace.worker.close()
        self.temporary.cleanup()

    def assembly(self):
        return self.workspace.dispatch(
            "v2.script",
            {
                "base_revision_id": None,
                "source": "parts = {'plate': cq.Workplane('XY').box(params['width'],60,8), 'post': cq.Workplane('XY').box(10,10,20).translate((70,0,0))}",
                "parameters": {"width": 80},
            },
        )["document"]

    def tools(self, document, **selection):
        selected = {
            "revision_id": document["revision_id"],
            "instance_id": "plate",
            "kind": "body",
            **selection,
        }
        return TaskTools(
            self.workspace,
            self.workspace.document,
            document,
            selected,
            self.workspace.project_id,
            "test-task",
        )

    def test_named_project_collection_moves_with_verified_geometry(self):
        import shutil

        original = self.assembly()
        conversation = self.workspace.state()["conversation"]["conversation_id"]
        previous_root = self.workspace.projects.folder
        self.workspace.worker.close()
        relocated = self.folder / "Relocated projects"
        shutil.move(str(previous_root), str(relocated))
        self.workspace = WorkspaceV2(self.folder, projects_dir=relocated)
        current = self.workspace.state()
        self.assertEqual(current["document"]["revision_id"], original["revision_id"])
        self.assertEqual(current["conversation"]["conversation_id"], conversation)
        self.assertTrue(
            Path(current["document"]["project_dir"]).is_relative_to(relocated)
        )
        self.assertEqual(
            {
                p["instance_id"]: p["asset_hash"]
                for p in current["document"]["components"]
            },
            {p["instance_id"]: p["asset_hash"] for p in original["components"]},
        )

    def test_selected_plate_thickening_scope_undo_reopen_and_conversation_switch(self):
        doc = self.assembly()
        first_chat = self.workspace.state()["conversation"]["conversation_id"]
        tools = self.tools(doc)
        context = tools.context()
        observation = tools.call(
            "cad_inspect",
            {"candidate_id": context["candidate_id"], "instance_id": "plate"},
        )
        face = next(
            f
            for f in observation["components"][0]["faces"]
            if f["normal"] == [0.0, 0.0, 1.0]
        )
        old_token = tools.candidate_id
        result = tools.call(
            "cad_apply",
            {
                "candidate_id": old_token,
                "command": {
                    "type": "offset_face",
                    "instance_id": "plate",
                    "face_index": face["index"],
                    "distance": 4,
                },
            },
        )
        with self.assertRaises(WorkspaceError) as stale:
            tools.call("cad_inspect", {"candidate_id": old_token})
        self.assertEqual(stale.exception.code, "stale_selection")
        self.assertEqual(tools.candidate["components"][1], doc["components"][1])
        self.assertAlmostEqual(
            tools.candidate["components"][0]["metrics"]["dimensions_mm"][2], 12
        )
        report = tools.call("cad_validate", result)
        self.assertTrue(report["geometry"]["passed"])
        self.assertEqual(report["scope"]["unrelated_components_checked"], 1)
        self.workspace.document.commit(
            tools.candidate,
            doc["revision_id"],
            summary="Plate +4 mm",
            commands=tools.commands,
        )
        changed = self.workspace.document.current()
        self.workspace.dispatch("v2.conversation.new", {})
        self.workspace.dispatch("v2.conversation.open", {"conversation_id": first_chat})
        self.assertEqual(
            self.workspace.document.current()["revision_id"], changed["revision_id"]
        )
        undo = self.workspace.dispatch(
            "v2.undo", {"base_revision_id": changed["revision_id"]}
        )["document"]
        redo = self.workspace.dispatch(
            "v2.redo", {"base_revision_id": undo["revision_id"]}
        )["document"]
        self.assertEqual(redo["revision_id"], changed["revision_id"])
        self.workspace.worker.close()
        reopened = WorkspaceV2(self.folder)
        try:
            self.assertEqual(
                reopened.state()["document"]["revision_id"], changed["revision_id"]
            )
            self.assertEqual(
                reopened.state()["conversation"]["conversation_id"], first_chat
            )
            self.assertEqual(
                reopened.state()["document"]["components"][1], doc["components"][1]
            )
        finally:
            reopened.worker.close()

    def test_scope_and_stale_selection_cannot_be_bypassed(self):
        doc = self.assembly()
        tools = self.tools(doc)
        with self.assertRaises(WorkspaceError) as scope:
            tools.call(
                "cad_apply",
                {
                    "candidate_id": tools.candidate_id,
                    "command": {
                        "type": "transform",
                        "instance_id": "post",
                        "translation": [20, 0, 0],
                    },
                },
            )
        self.assertEqual(scope.exception.code, "scope_violation")
        with self.assertRaises(WorkspaceError):
            self.tools(doc, revision_id="old-revision")
        with self.assertRaises(WorkspaceError):
            self.tools(doc, kind="face", index=999)
        self.assertEqual(tools.candidate, doc)

    def test_face_holes_have_expected_volume_and_import_history_is_honest(self):
        doc = self.assembly()
        tools = self.tools(doc)
        info = tools.call(
            "cad_inspect", {"candidate_id": tools.candidate_id, "instance_id": "plate"}
        )
        face = next(
            f for f in info["components"][0]["faces"] if f["normal"] == [0.0, 0.0, 1.0]
        )
        tools.call(
            "cad_apply",
            {
                "candidate_id": tools.candidate_id,
                "command": {
                    "type": "face_holes",
                    "instance_id": "plate",
                    "face_index": face["index"],
                    "diameter": 6,
                    "centres": [[-25, -20], [-25, 20], [25, -20], [25, 20]],
                    "depth": 20,
                },
            },
        )
        volume = tools.candidate["components"][0]["metrics"]["volume_mm3"]
        self.assertAlmostEqual(volume, 80 * 60 * 8 - 4 * math.pi * 3**2 * 8, places=4)
        self.assertTrue(
            tools.call("cad_validate", {"candidate_id": tools.candidate_id})[
                "geometry"
            ]["passed"]
        )

    def test_script_denies_os_access_and_preserves_accepted_geometry(self):
        doc = self.assembly()
        tools = self.tools(doc)
        for source in (
            "import os",
            "parts = {'plate': selected.__class__()}",
            "parts = {'plate': cq.Workplane('XY').box(2,2,2).export('secret.step')}",
            "while True: pass",
            "parts = {'plate': eval('1')}",
        ):
            with self.subTest(source=source), self.assertRaises(WorkspaceError):
                tools.call(
                    "cad_script",
                    {
                        "candidate_id": tools.candidate_id,
                        "source": source,
                        "instance_id": "plate",
                    },
                )
        self.assertEqual(
            self.workspace.document.current()["revision_id"], doc["revision_id"]
        )
        self.assertEqual(tools.candidate, doc)

    def test_failed_or_cancelled_provider_turn_never_accepts_partial_tools(self):
        doc = self.assembly()
        with patch("backend.v2.auth.request_json", return_value={"data": []}):
            self.workspace.connections.api_key("fixture-only-key-not-a-real-credential")
        workspace = self.workspace

        class FailedProvider:
            def __init__(self, *args, **kwargs):
                pass

            def start_thread(self, *args, **kwargs):
                return "fixture-session"

            def run(self, *args, **kwargs):
                # Exercise real geometry through the same task tool boundary, with a fake provider outcome.
                bridge = active_bridge[0]
                tools = bridge.tools
                tools.call(
                    "cad_apply",
                    {
                        "candidate_id": tools.candidate_id,
                        "command": {
                            "type": "transform",
                            "instance_id": "plate",
                            "translation": [0, 0, 20],
                        },
                    },
                )
                raise WorkspaceError(
                    "Fixture stream failed after tool success", "provider_task_failed"
                )

            def close(self):
                pass

        from backend.v2.cad_tools import ToolBridge

        active_bridge = []

        def bridge_factory(tools):
            bridge = ToolBridge(tools)
            active_bridge.append(bridge)
            return bridge

        with (
            patch("backend.v2.workspace.CodexAppServer", FailedProvider),
            patch("backend.v2.workspace.ToolBridge", bridge_factory),
        ):
            with self.assertRaises(WorkspaceError):
                workspace.dispatch(
                    "v2.task",
                    {
                        "base_revision_id": doc["revision_id"],
                        "selection": {
                            "revision_id": doc["revision_id"],
                            "instance_id": "plate",
                            "kind": "body",
                        },
                        "model": "fixture-model",
                        "prompt": "Move the plate",
                    },
                )
        self.assertEqual(
            workspace.document.current()["revision_id"], doc["revision_id"]
        )
        chat = workspace.state()["conversation"]
        self.assertEqual(len(chat["messages"]), 2)
        self.assertGreaterEqual(chat["messages"][-1]["elapsed_seconds"], 0)
        self.assertTrue(chat["messages"][-1]["activity"])
        task_file = (
            workspace.projects.project_path(workspace.project_id)
            / "tasks"
            / (chat["tasks"][0] + ".json")
        )
        self.assertEqual(json.loads(task_file.read_text())["status"], "failed")

    def test_duplicate_submission_and_bridge_failure_are_persisted_without_geometry(
        self,
    ):
        from unittest.mock import Mock

        with patch("backend.v2.auth.request_json", return_value={"data": []}):
            self.workspace.connections.api_key("fixture-only-key-not-a-real-credential")
        provider = Mock()
        provider.start_thread.return_value = "fixture-session"
        provider.run.return_value = "Inspected. No change requested."
        request = {
            "base_revision_id": None,
            "model": "fixture",
            "prompt": "Inspect",
            "task_id": "a" * 32,
        }
        observed = []
        self.workspace.output = observed.append
        with patch(
            "backend.v2.workspace.CodexAppServer", return_value=provider
        ) as factory:
            result = self.workspace.dispatch("v2.task", request)
            with self.assertRaises(WorkspaceError) as duplicate:
                self.workspace.dispatch("v2.task", request)
            self.assertEqual(factory.call_count, 1)
        self.assertEqual(duplicate.exception.code, "duplicate_submission")
        self.assertEqual(result["task"]["status"], "completed_no_change")
        self.assertIsNone(result["document"]["revision_id"])
        response = result["conversation"]["messages"][-1]
        self.assertGreaterEqual(response["elapsed_seconds"], 0)
        saved = self.workspace.projects.conversation(self.workspace.project_id)
        self.assertEqual(
            saved["messages"][-1]["elapsed_seconds"], response["elapsed_seconds"]
        )
        task_events = [e for e in observed if e.get("task_id")]
        self.assertTrue(task_events)
        self.assertTrue(
            all(
                e["conversation_id"] == result["conversation"]["conversation_id"]
                for e in task_events
            )
        )
        request["task_id"] = "b" * 32
        with patch(
            "backend.v2.workspace.ToolBridge",
            side_effect=RuntimeError("fixture bridge failure"),
        ):
            with self.assertRaises(RuntimeError):
                self.workspace.dispatch("v2.task", request)
        chat = self.workspace.state()["conversation"]
        path = (
            self.workspace.projects.project_path(self.workspace.project_id)
            / "tasks"
            / (request["task_id"] + ".json")
        )
        self.assertEqual(json.loads(path.read_text())["status"], "failed")
        self.assertIsNone(self.workspace.active_task)
        self.assertEqual(len(chat["tasks"]), 2)

    def test_script_parameters_keep_other_instances_and_guard_downstream_edits(self):
        doc = self.assembly()
        changed = self.workspace.dispatch(
            "v2.command",
            {
                "base_revision_id": doc["revision_id"],
                "selection": {
                    "revision_id": doc["revision_id"],
                    "instance_id": "plate",
                    "kind": "body",
                },
                "command": {
                    "type": "parameters",
                    "instance_id": "plate",
                    "values": {"width": 100},
                },
            },
        )["document"]
        self.assertAlmostEqual(
            changed["components"][0]["metrics"]["dimensions_mm"][0], 100
        )
        self.assertEqual(changed["components"][1], doc["components"][1])
        drilled = self.workspace.dispatch(
            "v2.command",
            {
                "base_revision_id": changed["revision_id"],
                "command": {
                    "type": "hole",
                    "instance_id": "plate",
                    "diameter": 4,
                    "centres": [[0, 0]],
                },
            },
        )["document"]
        with self.assertRaises(WorkspaceError):
            self.workspace.dispatch(
                "v2.command",
                {
                    "base_revision_id": drilled["revision_id"],
                    "command": {
                        "type": "parameters",
                        "instance_id": "plate",
                        "values": {"width": 90},
                    },
                },
            )
        self.assertEqual(
            self.workspace.document.current()["revision_id"], drilled["revision_id"]
        )

    def test_other_window_cannot_write_a_document_with_an_active_task_lock(self):
        from backend.native.project_lock import revision_lock
        from backend.native.project_lock import RevisionConflict

        doc = self.assembly()
        with revision_lock(self.workspace.document.folder / ".task-lock"):
            other = WorkspaceV2(self.folder)
            try:
                with self.assertRaises(RevisionConflict):
                    other.dispatch(
                        "v2.command",
                        {
                            "base_revision_id": doc["revision_id"],
                            "command": {
                                "type": "transform",
                                "instance_id": "plate",
                                "translation": [20, 0, 0],
                            },
                        },
                    )
            finally:
                other.worker.close()
        self.assertEqual(
            self.workspace.document.current()["revision_id"], doc["revision_id"]
        )

    def test_task_revision_link_can_restore_a_snapshot_after_a_new_history_branch(self):
        original = self.assembly()
        moved = self.workspace.dispatch(
            "v2.command",
            {
                "base_revision_id": original["revision_id"],
                "command": {
                    "type": "transform",
                    "instance_id": "plate",
                    "translation": [20, 0, 0],
                },
            },
        )["document"]
        self.workspace.dispatch("v2.undo", {"base_revision_id": moved["revision_id"]})
        branch = self.workspace.dispatch(
            "v2.command",
            {
                "base_revision_id": original["revision_id"],
                "command": {
                    "type": "transform",
                    "instance_id": "plate",
                    "translation": [0, 20, 0],
                },
            },
        )["document"]
        self.assertNotIn(
            moved["revision_id"], [r["revision_id"] for r in branch["history"]]
        )
        restored = self.workspace.dispatch(
            "v2.restore",
            {
                "base_revision_id": branch["revision_id"],
                "revision_id": moved["revision_id"],
            },
        )["document"]
        self.assertEqual(restored["components"], moved["components"])
        self.assertEqual(restored["revision_id"], moved["revision_id"])

    def test_agent_inspection_exposes_actual_structure_and_editable_definition(self):
        document = self.assembly()
        tools = self.tools(document)
        context = tools.context()
        self.assertIn("assembly_nodes", context)
        self.assertEqual(context["components"][0]["parameters"]["width"], 80)
        definition = tools.call(
            "cad_definition",
            {"candidate_id": tools.candidate_id, "instance_id": "plate"},
        )
        self.assertIn("cq.Workplane", definition["script"]["source"])
        self.assertEqual(definition["parameters"]["width"], 80)
        observation = tools.call(
            "cad_inspect", {"candidate_id": tools.candidate_id, "instance_id": "plate"}
        )
        self.assertEqual(observation["components"][0]["parameters"]["width"], 80)

    def test_dpapi_vault_contains_no_plaintext_credentials(self):
        key = "fixture-only-secret-value-123456"
        with patch("backend.v2.auth.request_json", return_value={"data": []}):
            self.workspace.connections.api_key(key)
        path = self.workspace.connections.vault.path
        self.assertNotIn(key.encode(), path.read_bytes())
        self.assertNotIn(key, json.dumps(self.workspace.connections.status()))
        _, account = self.workspace.connections.credential()
        self.assertEqual(account["api_key"], key)
        self.workspace.connections.disconnect()
        self.assertNotIn(
            "api_key",
            next(iter(self.workspace.connections.vault.read()["accounts"].values())),
        )


if __name__ == "__main__":
    unittest.main()

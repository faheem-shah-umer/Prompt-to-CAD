"""Real geometry and isolated storage checks for workspace selection/copy changes."""

import copy
import hashlib
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
from backend.native.contracts import WorkspaceError
from backend.native.documents import write_json
from backend.v2.workspace import WorkspaceV2
from backend.v2.cad_tools import TaskTools, fingerprint

ROOT = Path(__file__).resolve().parents[2]


class WorkspacePolishTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "tmp")
        self.base = Path(self.temp.name)
        self.app = WorkspaceV2(self.base)
        self.app.dispatch("v2.project.create", {"name": "Synthetic assembly"})

    def tearDown(self):
        self.app.worker.close()
        self.temp.cleanup()

    def assembly(self):
        return self.app.dispatch(
            "v2.script",
            {
                "base_revision_id": None,
                "source": "parts = {'left': cq.Workplane('XY').box(20,20,4), 'right': cq.Workplane('XY').box(20,20,4).translate((50,0,0)), 'untouched': cq.Workplane('XY').box(4,4,4).translate((100,0,0))}",
                "parameters": {},
            },
        )["document"]

    def selected_faces(self, doc):
        entities = []
        for target in ("left", "right"):
            info = self.app.geometry(
                "inspect",
                {
                    "project_dir": str(self.app.document.folder),
                    "snapshot": doc,
                    "instance_id": target,
                    "offset": 0,
                    "limit": 128,
                },
            )
            face = next(
                f
                for f in info["components"][0]["faces"]
                if f["normal"] == [0.0, 0.0, 1.0]
            )
            entities.append(
                {"instance_id": target, "kind": "face", "index": face["index"]}
            )
        return {
            "version": 2,
            "project_id": self.app.project_id,
            "document_id": doc["document_id"],
            "revision_id": doc["revision_id"],
            "entities": entities,
        }

    def test_atomic_faces_across_components_scope_staleness_undo_and_redo(self):
        doc = self.assembly()
        selection = self.selected_faces(doc)
        tools = TaskTools(
            self.app, self.app.document, doc, selection, self.app.project_id, "fixture"
        )
        selection["entities"].clear()
        self.assertEqual(len(tools.selection["entities"]), 2)
        commands = [
            {
                "type": "offset_face",
                "instance_id": e["instance_id"],
                "face_index": e["index"],
                "distance": 2,
            }
            for e in tools.selection["entities"]
        ]
        token = tools.candidate_id
        tools.call("cad_apply_batch", {"candidate_id": token, "commands": commands})
        self.assertEqual(tools.candidate["components"][2], doc["components"][2])
        for part in tools.candidate["components"][:2]:
            self.assertAlmostEqual(part["metrics"]["volume_mm3"], 2400, places=3)
        with self.assertRaises(WorkspaceError) as stale:
            tools.call(
                "cad_apply",
                {"candidate_id": tools.candidate_id, "command": commands[0]},
            )
        self.assertEqual(stale.exception.code, "stale_selection")
        report = tools.call("cad_validate", {"candidate_id": tools.candidate_id})
        self.assertEqual(report["scope"]["unrelated_components_checked"], 1)
        self.app.document.commit(
            tools.candidate,
            doc["revision_id"],
            "Selected face batch",
            commands=commands,
        )
        changed = self.app.document.current()["revision_id"]
        undo = self.app.dispatch("v2.undo", {"base_revision_id": changed})["document"]
        self.assertEqual(undo["revision_id"], doc["revision_id"])
        self.assertEqual(
            self.app.dispatch("v2.redo", {"base_revision_id": doc["revision_id"]})[
                "document"
            ]["revision_id"],
            changed,
        )

    def test_failed_batch_and_cancel_keep_candidate_and_face_permissions(self):
        doc = self.assembly()
        selection = self.selected_faces(doc)
        tools = TaskTools(
            self.app, self.app.document, doc, selection, self.app.project_id, "fixture"
        )
        command = {
            "type": "offset_face",
            "instance_id": "left",
            "face_index": selection["entities"][0]["index"],
            "distance": 2,
        }
        for bad in (
            {**command, "instance_id": "untouched"},
            {"type": "transform", "instance_id": "left", "translation": [1, 0, 0]},
        ):
            with self.assertRaises(WorkspaceError):
                tools.call(
                    "cad_apply", {"candidate_id": tools.candidate_id, "command": bad}
                )
        before = copy.deepcopy(tools.candidate)
        with self.assertRaises(WorkspaceError):
            tools.call(
                "cad_apply_batch",
                {
                    "candidate_id": tools.candidate_id,
                    "commands": [
                        command,
                        {**command, "instance_id": "right", "face_index": 999},
                    ],
                },
            )
        self.assertEqual(tools.candidate, before)
        # A geometry failure after scope validation must also leave the candidate intact.
        right = {
            "type": "offset_face",
            "instance_id": "right",
            "face_index": selection["entities"][1]["index"],
            "distance": 0,
        }
        with self.assertRaises(WorkspaceError):
            tools.call(
                "cad_apply_batch",
                {"candidate_id": tools.candidate_id, "commands": [command, right]},
            )
        self.assertEqual(tools.candidate, before)
        self.app.cancelled.set()
        with self.assertRaises(WorkspaceError):
            tools.call(
                "cad_apply_batch",
                {"candidate_id": tools.candidate_id, "commands": [command]},
            )
        self.assertEqual(self.app.document.current()["revision_id"], doc["revision_id"])

    def test_save_as_rewrites_history_links_and_preserves_source_and_geometry(self):
        doc = self.assembly()
        pid = self.app.project_id
        chat = self.app.projects.conversation(pid)
        cid = chat["conversation_id"]
        from PIL import Image

        image = self.base / "synthetic-reference.png"
        Image.new("RGB", (8, 8), (80, 140, 180)).save(image)
        asset = self.app.projects.reference(pid, image)
        rid = str(uuid4())
        orphan = self.app.document.current()
        orphan["revision_id"] = rid
        orphan["summary"] = "Synthetic retained branch"
        write_json(self.app.document.folder / "revisions" / (rid + ".json"), orphan)
        chat.update(
            provider_session="fixture-session",
            provider_account="fixture-account",
            tasks=["fixture-task"],
            messages=[
                {
                    "role": "assistant",
                    "content": "Synthetic response",
                    "task_id": "fixture-task",
                    "change": {"result_revision_id": rid},
                    "viewport": asset,
                }
            ],
        )
        self.app.projects.save_conversation(pid, chat)
        self.app.projects.task(
            pid,
            {
                "task_id": "fixture-task",
                "conversation_id": cid,
                "document_id": doc["document_id"],
                "base_revision_id": rid,
                "result_revision_id": rid,
                "provider_account": "fixture-account",
                "status": "completed",
            },
        )
        source = self.app.projects.project_path(pid)
        original = {
            str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in source.rglob("*")
            if p.is_file() and not p.name.endswith(".lock")
        }
        copied = self.app.dispatch("v2.project.save_as", {"name": "Independent copy"})
        self.assertNotEqual(copied["project"]["project_id"], pid)
        self.assertNotEqual(copied["document"]["document_id"], doc["document_id"])
        self.assertNotEqual(copied["document"]["revision_id"], rid)
        self.assertNotEqual(copied["conversation"]["conversation_id"], cid)
        self.assertIsNone(copied["conversation"]["provider_session"])
        self.assertEqual(fingerprint(copied["document"]), fingerprint(doc))
        message = copied["conversation"]["messages"][0]
        mapped_branch = message["change"]["result_revision_id"]
        self.assertNotEqual(mapped_branch, rid)
        self.assertNotEqual(mapped_branch, copied["document"]["revision_id"])
        self.app.document.restore(mapped_branch, copied["document"]["revision_id"])
        self.app.document.restore(copied["document"]["revision_id"], mapped_branch)
        reference = copied["conversation"]["messages"][0]["viewport"]
        self.assertNotEqual(reference["path"], asset["path"])
        self.assertTrue(
            Path(reference["path"]).is_relative_to(
                Path(copied["project"]["folder_path"])
            )
        )
        self.assertEqual(
            hashlib.sha256(Path(reference["path"]).read_bytes()).hexdigest(),
            asset["sha256"],
        )
        task = self.app.projects.read(
            self.app.projects.project_path(self.app.project_id)
            / "tasks"
            / (message["task_id"] + ".json")
        )
        self.assertEqual(
            task["conversation_id"], copied["conversation"]["conversation_id"]
        )
        self.assertIsNone(task["provider_account"])
        self.assertEqual(
            original,
            {
                str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in source.rglob("*")
                if p.is_file() and not p.name.endswith(".lock")
            },
        )
        cursor = self.app.document.index()["cursor"]
        self.app.dispatch("v2.project.save", {})
        self.assertEqual(self.app.document.index()["cursor"], cursor)
        self.app.dispatch(
            "v2.command",
            {
                "base_revision_id": copied["document"]["revision_id"],
                "command": {
                    "type": "transform",
                    "instance_id": "left",
                    "translation": [0, 0, 1],
                },
            },
        )
        self.app.dispatch("v2.project.open", {"project_id": pid})
        self.assertEqual(fingerprint(self.app.state()["document"]), fingerprint(doc))

    def test_copy_failure_cleans_staging_and_bulk_lifecycle_has_per_item_results(self):
        pid = self.app.project_id
        cid = self.app.state()["conversation"]["conversation_id"]
        other = self.app.projects.create("Other fixture")
        otherid = other["project_id"]
        otherchat = self.app.projects.conversation(otherid)["conversation_id"]
        items = [
            {"project_id": pid, "conversation_id": cid},
            {"project_id": otherid, "conversation_id": otherchat},
        ]
        result = self.app.dispatch(
            "v2.conversations.batch", {"items": items + items, "action": "archive"}
        )
        self.assertEqual(len(result["results"]), 2)
        self.app.dispatch("v2.conversations.batch", {"items": items, "action": "trash"})
        self.app.dispatch(
            "v2.conversations.batch", {"items": items, "action": "restore"}
        )
        self.app.dispatch(
            "v2.conversations.batch", {"items": items, "action": "restore"}
        )
        self.assertTrue(self.app.projects.conversation(pid, cid)["archived"])
        self.assertFalse(self.app.projects.conversation(pid, cid)["trashed"])
        self.app.dispatch("v2.conversations.batch", {"items": items, "action": "trash"})
        result = self.app.dispatch(
            "v2.conversations.batch",
            {
                "items": items + [{"project_id": pid, "conversation_id": "missing"}],
                "action": "purge",
            },
        )
        self.assertEqual(sum(r["passed"] for r in result["results"]), 2)
        self.assertEqual(len(result["results"]), 3)
        self.assertTrue(self.app.document.index_path.exists())
        with patch(
            "backend.v2.project_copy.shutil.copytree",
            side_effect=OSError("Synthetic copy failure"),
        ):
            with self.assertRaises(OSError):
                self.app.dispatch("v2.project.save_as", {"name": "Failed copy"})
        self.assertFalse((self.app.projects.folder / "Failed copy").exists())
        self.assertEqual(list(self.app.projects.folder.glob(".copy-*")), [])


if __name__ == "__main__":
    unittest.main()

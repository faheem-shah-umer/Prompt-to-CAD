import copy
import math
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import cadquery as cq

from backend.native.contracts import WorkspaceError
from backend.native.documents import Document, asset_path
from backend.native.geometry import inspect, world_shape
from backend.native.worker_client import GeometryWorker
from backend.native.workspace import Workspace
from tools.fixtures import write_assembly

ROOT = Path(__file__).resolve().parents[2]


class NativeWorkspaceTestCase(unittest.TestCase):
    def setUp(self):
        (ROOT / "tmp").mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT / "tmp")
        self.folder = Path(self.temporary.name)
        self.workspace = Workspace(self.folder / "projects")
        self.source = self.folder / "plate.step"
        cq.exporters.export(cq.Workplane("XY").box(80, 60, 8).val(), str(self.source))

    def tearDown(self):
        self.workspace.worker.close()
        self.temporary.cleanup()

    def open_plate(self):
        return self.workspace.dispatch("document.import", {"path": str(self.source)})

    def command(self, doc, command, selection=None):
        params = {"base_revision_id": doc["revision_id"], "command": command}
        if selection:
            params["selection"] = selection
        return self.workspace.dispatch("document.command", params)["document"]


class NativeWorkspaceTests(NativeWorkspaceTestCase):
    def test_acceptance_import_holes_fillets_history_reopen_and_exports(self):
        original = self.open_plate()
        part = original["components"][0]
        drilled = self.command(
            original,
            {
                "type": "hole",
                "instance_id": part["instance_id"],
                "diameter": 6,
                "centres": [[-30, -20], [-30, 20], [30, -20], [30, 20]],
            },
        )
        inspection = self.workspace.dispatch(
            "document.inspect",
            {
                "base_revision_id": drilled["revision_id"],
                "instance_id": part["instance_id"],
            },
        )
        corners = [
            e["index"]
            for e in inspection["components"][0]["edges"]
            if abs(e["length_mm"] - 8) < 1e-6
            and abs(abs(e["centre"][0]) - 40) < 1e-6
            and abs(abs(e["centre"][1]) - 30) < 1e-6
        ]
        self.assertEqual(len(corners), 4)
        finished = self.command(
            drilled,
            {
                "type": "fillet",
                "instance_id": part["instance_id"],
                "size": 2,
                "edge_indices": corners,
            },
        )
        expected_volume = (80 * 60 - 4 * math.pi * 3**2 - (4 - math.pi) * 2**2) * 8
        self.assertAlmostEqual(
            finished["components"][0]["metrics"]["volume_mm3"],
            expected_volume,
            places=4,
        )
        self.assertEqual(
            finished["components"][0]["metrics"]["dimensions_mm"], [80, 60, 8]
        )
        self.assertTrue(finished["verification"]["passed"])
        undone = self.workspace.dispatch(
            "document.undo", {"base_revision_id": finished["revision_id"]}
        )
        self.assertEqual(undone["revision_id"], drilled["revision_id"])
        redone = self.workspace.dispatch(
            "document.redo", {"base_revision_id": undone["revision_id"]}
        )
        self.assertEqual(redone["revision_id"], finished["revision_id"])
        reopened = self.workspace.dispatch(
            "document.open", {"path": finished["project_dir"]}
        )
        self.assertEqual(reopened["components"], finished["components"])
        copied = self.workspace.dispatch(
            "document.save_as",
            {
                "base_revision_id": reopened["revision_id"],
                "destination": str(self.folder / "copy.cadproj"),
            },
        )
        self.assertEqual(
            Document(copied["project_dir"]).current()["components"],
            finished["components"],
        )
        for extension in ("step", "stl"):
            path = self.folder / f"result.{extension}"
            exported = self.workspace.dispatch(
                "document.export",
                {"base_revision_id": copied["revision_id"], "path": str(path)},
            )
            self.assertTrue(path.stat().st_size > 100)
            self.assertTrue(exported["verification"]["passed"])
        self.assertTrue(self.source.exists())
        self.assertEqual(
            Document(original["project_dir"]).current()["revision_id"],
            finished["revision_id"],
        )

    def test_bad_geometry_and_stale_references_preserve_the_accepted_revision(self):
        doc = self.open_plate()
        id = doc["components"][0]["instance_id"]
        for command in (
            {"type": "fillet", "instance_id": id, "size": 1000, "edge_indices": [1]},
            {"type": "hole", "instance_id": id, "diameter": 6, "centres": [[500, 500]]},
            {"type": "fillet", "instance_id": id, "size": 1, "edge_indices": [999]},
            {
                "type": "hole",
                "instance_id": id,
                "diameter": 6,
                "centres": [[0, 0], [0, 0]],
            },
        ):
            with self.subTest(command=command), self.assertRaises(WorkspaceError):
                self.command(doc, command)
            self.assertEqual(
                self.workspace.document.current()["revision_id"], doc["revision_id"]
            )
        changed = self.command(
            doc, {"type": "hole", "instance_id": id, "diameter": 6, "centres": [[0, 0]]}
        )
        with self.assertRaises(WorkspaceError) as conflict:
            self.command(
                doc,
                {
                    "type": "hole",
                    "instance_id": id,
                    "diameter": 3,
                    "centres": [[10, 0]],
                },
            )
        self.assertEqual(conflict.exception.code, "revision_conflict")
        with self.assertRaises(WorkspaceError):
            self.command(
                changed,
                {
                    "type": "hole",
                    "instance_id": id,
                    "diameter": 3,
                    "centres": [[10, 0]],
                },
                {"revision_id": doc["revision_id"], "instance_id": id},
            )
        self.assertEqual(
            self.workspace.document.current()["revision_id"], changed["revision_id"]
        )

    def test_nested_assembly_instances_names_colors_and_placements_round_trip(self):
        body = cq.Workplane("XY").box(10, 8, 6).val()
        inner = cq.Assembly(name="Pair")
        inner.add(
            body,
            name="Red block",
            color=cq.Color(0.8, 0.1, 0.2),
            loc=cq.Location((0, 0, 0)),
        )
        inner.add(
            body,
            name="Blue block",
            color=cq.Color(0.1, 0.2, 0.8),
            loc=cq.Location((30, 0, 0)),
        )
        assembly = cq.Assembly(name="Fixture")
        assembly.add(
            inner, name="Rotated pair", loc=cq.Location((5, 12, 0), (0, 0, 90))
        )
        path = self.folder / "assembly.step"
        assembly.export(str(path))
        doc = self.workspace.dispatch("document.import", {"path": str(path)})
        self.assertEqual(len(doc["components"]), 2)
        self.assertGreaterEqual(len(doc["assembly_nodes"]), 2)
        self.assertTrue(doc["verification"]["passed"])
        names = {part["name"] for part in doc["components"]}
        self.assertIn("Red block", names)
        self.assertIn("Blue block", names)
        target = doc["components"][0]
        untouched = copy.deepcopy(doc["components"][1])
        changed = self.command(
            doc,
            {
                "type": "hole",
                "instance_id": target["instance_id"],
                "diameter": 2,
                "centres": [[0, 0]],
            },
        )
        self.assertEqual(changed["components"][1], untouched)
        self.assertNotEqual(
            changed["components"][0]["asset_hash"], target["asset_hash"]
        )

    def test_recipe_compatibility_and_downstream_parameter_guard(self):
        source = write_assembly(self.folder)
        before_bytes = source.read_bytes()
        doc = self.workspace.dispatch("document.import", {"path": str(source)})
        original = next(p for p in doc["components"] if p["instance_id"] == "post")
        edited = self.command(
            doc, {"type": "parameters", "instance_id": "post", "values": {"height": 48}}
        )
        post = next(p for p in edited["components"] if p["instance_id"] == "post")
        self.assertAlmostEqual(post["metrics"]["dimensions_mm"][2], 48)
        self.assertNotEqual(post["asset_hash"], original["asset_hash"])
        base = edited["components"][0]
        direct = self.command(
            edited,
            {
                "type": "hole",
                "instance_id": base["instance_id"],
                "diameter": 2,
                "centres": [[0, 0]],
            },
        )
        with self.assertRaises(WorkspaceError):
            self.command(
                direct,
                {"type": "parameters", "instance_id": "post", "values": {"height": 40}},
            )
        self.assertEqual(source.read_bytes(), before_bytes)

    def test_chamfer_extrude_pattern_and_transform(self):
        doc = self.open_plate()
        id = doc["components"][0]["instance_id"]
        cut = self.command(
            doc,
            {
                "type": "extrude",
                "instance_id": id,
                "origin": [0, 0, -5],
                "profile": [[-3, -3], [3, -3], [3, 3], [-3, 3]],
                "distance": 10,
                "operation": "cut",
            },
        )
        self.assertAlmostEqual(
            cut["components"][0]["metrics"]["volume_mm3"], 38400 - 36 * 8
        )
        patterned = self.command(
            cut,
            {
                "type": "pattern",
                "instance_id": id,
                "mode": "linear",
                "count": 4,
                "step": [10, 0, 0],
                "seed": {
                    "type": "hole",
                    "instance_id": id,
                    "diameter": 2,
                    "centres": [[-15, 15]],
                },
            },
        )
        self.assertAlmostEqual(
            patterned["components"][0]["metrics"]["volume_mm3"],
            38400 - 36 * 8 - 4 * math.pi * 8,
            places=4,
        )
        info = inspect(patterned["project_dir"], patterned, id)["components"][0]
        corner = next(
            e["index"]
            for e in info["edges"]
            if abs(e["centre"][0] - 40) < 1e-6 and abs(e["length_mm"] - 8) < 1e-6
        )
        chamfered = self.command(
            patterned,
            {"type": "chamfer", "instance_id": id, "size": 1, "edge_indices": [corner]},
        )
        moved = self.command(
            chamfered,
            {
                "type": "transform",
                "instance_id": id,
                "translation": [10, 5, 2],
                "rotation": [0, 0, 90],
            },
        )
        shape = world_shape(moved["project_dir"], moved["components"][0])
        bounds = shape.BoundingBox()
        self.assertAlmostEqual(bounds.xlen, 60)
        self.assertAlmostEqual(bounds.ylen, 80)

    def test_interrupted_journal_and_tampered_asset_detection(self):
        doc = self.open_plate()
        self.workspace.document.journal("running", action="cad_task")
        recovered = self.workspace.dispatch(
            "document.open", {"path": doc["project_dir"]}
        )
        self.assertIn("interrupted", recovered["recovery_message"])
        self.assertEqual(recovered["revision_id"], doc["revision_id"])
        with self.assertRaises(WorkspaceError):
            asset_path(Path(doc["project_dir"]), "../outside.brep")
        asset = asset_path(Path(doc["project_dir"]), doc["components"][0]["brep"])
        asset.write_bytes(asset.read_bytes() + b"\nchanged")
        with self.assertRaises(WorkspaceError):
            self.workspace.document.current()

    def test_cancel_and_worker_crash_can_restart_without_losing_document(self):
        doc = self.open_plate()
        self.workspace.cancelled.set()
        with self.assertRaises(WorkspaceError) as cancelled:
            self.workspace.geometry(
                "inspect", {"project_dir": doc["project_dir"], "snapshot": doc}
            )
        self.assertEqual(cancelled.exception.code, "cancelled")
        self.assertEqual(
            self.workspace.document.current()["revision_id"], doc["revision_id"]
        )
        self.workspace.cancelled.clear()
        result = self.workspace.geometry("hello", {})
        self.assertIn("occt_version", result)
        self.assertEqual(result["worker_pid"], self.workspace.worker.process.pid)
        self.workspace.worker.process.kill()
        self.workspace.worker.process.wait(timeout=5)
        hello = self.workspace.geometry("hello", {})
        self.assertNotEqual(hello["worker_pid"], result["worker_pid"])
        self.assertEqual(
            self.workspace.document.current()["revision_id"], doc["revision_id"]
        )

    def test_no_op_and_expired_task_budget_preserve_the_revision(self):
        doc = self.open_plate()
        id = doc["components"][0]["instance_id"]
        with self.assertRaises(WorkspaceError) as no_change:
            self.command(doc, {"type": "transform", "instance_id": id})
        self.assertEqual(no_change.exception.code, "no_change")
        self.workspace.task_deadline = time.monotonic() - 1
        with self.assertRaises(WorkspaceError) as timeout:
            self.workspace.geometry("hello", {})
        self.assertEqual(timeout.exception.code, "timeout")
        self.assertEqual(
            self.workspace.document.current()["revision_id"], doc["revision_id"]
        )
        for value in (-1, float("nan"), float("inf")):
            with self.assertRaises(WorkspaceError):
                GeometryWorker(self.folder / "logs", timeout=value)

    def test_step_inch_units_are_normalised_to_millimetres(self):
        from OCP.Interface import Interface_Static

        self.assertTrue(Interface_Static.SetCVal_s("write.step.unit", "INCH"))
        try:
            cq.exporters.export(
                cq.Workplane("XY").box(4, 3, 0.5).val(), str(self.source)
            )
        finally:
            Interface_Static.SetCVal_s("write.step.unit", "MM")
        self.assertIn("INCH", self.source.read_text().upper())
        doc = self.open_plate()
        for measured, expected in zip(
            doc["components"][0]["metrics"]["dimensions_mm"], (101.6, 76.2, 12.7)
        ):
            self.assertAlmostEqual(measured, expected, places=5)
        self.assertTrue(doc["verification"]["passed"])

    def test_new_intersection_is_rejected_and_boolean_preserves_tool_and_other_instances(
        self,
    ):
        assembly = cq.Assembly(name="Boolean fixture")
        block = cq.Workplane("XY").box(10, 10, 10).val()
        assembly.add(block, name="Target")
        assembly.add(block, name="Neighbour", loc=cq.Location((20, 0, 0)))
        assembly.add(cq.Workplane("XY").box(4, 4, 20).val(), name="Cutter")
        source = self.folder / "boolean.step"
        assembly.export(str(source))
        doc = self.workspace.dispatch("document.import", {"path": str(source)})
        parts = {p["name"]: p for p in doc["components"]}
        with self.assertRaises(WorkspaceError):
            self.command(
                doc,
                {
                    "type": "transform",
                    "instance_id": parts["Target"]["instance_id"],
                    "translation": [20, 0, 0],
                },
            )
        self.assertEqual(
            self.workspace.document.current()["revision_id"], doc["revision_id"]
        )
        cut = self.command(
            doc,
            {
                "type": "boolean",
                "instance_id": parts["Target"]["instance_id"],
                "tool_instance_id": parts["Cutter"]["instance_id"],
                "operation": "cut",
            },
        )
        result = {p["name"]: p for p in cut["components"]}
        self.assertAlmostEqual(result["Target"]["metrics"]["volume_mm3"], 840)
        self.assertEqual(parts["Neighbour"], result["Neighbour"])
        self.assertEqual(parts["Cutter"], result["Cutter"])

    def test_failed_index_swap_preserves_pointer_and_view_reads_a_single_index(self):
        doc = self.open_plate()
        import os

        replace = os.replace

        def interrupt(source, destination):
            if Path(destination) == self.workspace.document.index_path:
                raise OSError("Simulated interrupted index write")
            return replace(source, destination)

        with (
            patch("backend.native.documents.os.replace", side_effect=interrupt),
            self.assertRaises(OSError),
        ):
            self.workspace.document.commit(
                self.workspace.document.current(), doc["revision_id"], "Interrupted"
            )
        self.assertEqual(
            self.workspace.document.current()["revision_id"], doc["revision_id"]
        )
        with patch.object(
            self.workspace.document, "index", wraps=self.workspace.document.index
        ) as reads:
            view = self.workspace.document.view()
            self.assertEqual(reads.call_count, 1)
        self.assertEqual(view["revision_id"], doc["revision_id"])


if __name__ == "__main__":
    unittest.main()

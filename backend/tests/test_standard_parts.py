"""Synthetic cq_warehouse integration and compound regression checks (Windows)."""

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import cadquery as cq
from OCP.StdFail import StdFail_NotDone
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE

from backend.native import geometry
from backend.native.contracts import WorkspaceError
from backend.native.documents import Document
from backend.native.workspace import Workspace
from backend.v2.cad_tools import TaskTools

ROOT = Path(__file__).resolve().parents[2]


def sample(identity, description):
    types = description["standards"]
    values = {}
    if types:
        kind = "bearing_type" if identity.startswith("bearing.") else "fastener_type"
        values.update({kind: types[0], "size": description["sizes"][types[0]][0]})
    if "length" in description["parameters"]:
        values["length"] = 10
    values.update({
        "sprocket.Sprocket": {"num_teeth": 16},
        "chain.Chain": {"spkt_teeth": [16, 16], "spkt_locations": [[-76.2, 40], [76.2, 40]], "positive_chain_wrap": [True, True]},
        "thread.Thread": {"apex_radius": 10, "apex_width": 1, "root_radius": 8, "root_width": 1.5, "pitch": 2, "length": 6},
        "thread.IsoThread": {"major_diameter": 6, "pitch": 1, "length": 6},
        "thread.AcmeThread": {"size": "1/4", "length": 10},
        "thread.MetricTrapezoidalThread": {"size": "8x1.5", "length": 6},
        "thread.PlasticBottleThread": {"size": "M38SP444"},
    }.get(identity, {}))
    return values


@unittest.skipUnless(os.name == "nt", "Windows worker resource controls required")
class StandardPartTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "tmp").mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT / "tmp")
        self.folder = Path(self.temporary.name)
        self.workspace = Workspace(self.folder / "projects")
        self.doc = Document.create(self.folder / "fixture.cadproj", "Synthetic library fixture")
        self.empty = {"components": [], "assembly_nodes": [], "document_id": self.doc.index()["document_id"]}

    def tearDown(self):
        self.workspace.worker.close()
        self.temporary.cleanup()

    def call(self, method, snapshot=None, **request):
        return self.workspace.geometry(method, {"project_dir": str(self.doc.folder), "snapshot": snapshot or self.empty, "request": request})

    def create(self, identity, parameters, snapshot=None, **options):
        return self.call("standard_part", snapshot, generator_id=identity, parameters=parameters, **options)

    def test_every_concrete_generator_creates_valid_physical_geometry(self):
        catalog = self.call("standard_parts")
        self.assertEqual(set(catalog["families"]), {"fastener", "bearing", "sprocket", "chain", "thread"})
        for identities in catalog["families"].values():
            for identity in identities:
                with self.subTest(generator=identity):
                    description = self.call("standard_parts", generator_id=identity)
                    result = self.create(identity, sample(identity, description))
                    self.assertEqual(len(result["components"]), 1)
                    part = result["components"][0]
                    self.assertGreater(part["metrics"]["solid_count"], 0)
                    self.assertTrue(part["metrics"]["brep_valid"])
                    self.assertEqual(part["standard_part"]["generated_asset_hash"], part["asset_hash"])
                    self.assertNotIn("simple", part["parameters"])
                    if "simple" in description["parameters"]:
                        self.assertIs(part["standard_part"]["parameters"]["simple"], False)

    def test_registry_covers_public_concrete_generators(self):
        catalog = self.call("standard_parts")
        # Inspect upstream in a separate process so the ordinary test runtime
        # and its CadQuery classes remain unmodified.
        source = """
import importlib, inspect, json
result = {}
for family in ('fastener', 'bearing', 'sprocket', 'chain', 'thread'):
    module = importlib.import_module('cq_warehouse.' + family)
    result[family] = [name for name, cls in vars(module).items()
        if inspect.isclass(cls) and cls.__module__ == module.__name__
        and not inspect.isabstract(cls) and not name.startswith('_')]
print(json.dumps(result))
"""
        inventory = subprocess.check_output([sys.executable, "-B", "-c", source], cwd=ROOT, text=True)
        for family, names in json.loads(inventory).items():
            self.assertEqual(set(catalog["families"][family]), {family + "." + name for name in names})

    def test_chain_step_round_trip_preserves_one_component(self):
        result = self.create("chain.Chain", {"spkt_teeth": [16, 16], "spkt_locations": [[-76.2, 40], [76.2, 40]], "positive_chain_wrap": [True, True]})
        verification = self.workspace.geometry("verify", {"project_dir": str(self.doc.folder), "snapshot": result})
        self.assertEqual(verification["component_count"], 1)
        self.assertEqual(verification["solid_count"], result["components"][0]["metrics"]["solid_count"])
        self.assertGreater(verification["solid_count"], 1)

    def test_scoped_insertion_regeneration_history_reopen_and_save_as(self):
        block = cq.Workplane("XY").box(30, 30, 30).val()
        original = {**self.empty, "components": [{"instance_id": "block", "definition_id": "block", "name": "Block", "matrix": geometry.IDENTITY, "color": [0.2, 0.4, 0.6], "parent_id": None, **geometry.store_shape(self.doc.folder, block)}]}
        original = self.doc.commit(original)
        self.workspace.document = self.doc
        selected = {"revision_id": original["revision_id"], "instance_id": "block", "kind": "face", "index": 1}
        tools = TaskTools(self.workspace, self.doc, original, selected, "fixture", "test")
        params = {"candidate_id": tools.candidate_id, "generator_id": "bearing.SingleRowDeepGrooveBallBearing", "parameters": {"size": "M8-22-7", "bearing_type": "SKT"}}
        with self.assertRaises(WorkspaceError):
            tools.call("cad_standard_part", params)
        self.assertEqual(tools.candidate["components"], original["components"])
        params["placement"] = {"translation": [50, 0, 0]}
        tools.call("cad_standard_part", params)
        self.assertEqual(tools.candidate["components"][0], original["components"][0])
        part = tools.candidate["components"][1]
        identity = part["instance_id"]
        self.assertEqual(part["shape_kind"], "compound")
        self.assertGreater(part["metrics"]["solid_count"], 1)
        tools.call("cad_appearance", {"candidate_id": tools.candidate_id, "instance_ids": [identity], "color": "#AA6699"})
        before = copy.deepcopy(tools.candidate["components"][1])
        tools.call("cad_standard_part", {"candidate_id": tools.candidate_id, "instance_id": identity, "parameters": {"size": "M10-26-8"}})
        regenerated = tools.candidate["components"][1]
        self.assertEqual(regenerated["matrix"], before["matrix"])
        self.assertEqual(regenerated["color"], before["color"])
        definition = tools.call("cad_definition", {"candidate_id": tools.candidate_id, "instance_id": identity})
        self.assertEqual(definition["standard_part"]["parameters"]["size"], "M10-26-8")
        validation = tools.validate()
        self.assertEqual(validation["geometry"]["component_count"], 2)
        self.assertGreater(validation["geometry"]["solid_count"], 2)
        committed = self.doc.commit(tools.candidate, original["revision_id"], "Synthetic bearing")
        undone = self.doc.move_history(-1, committed["revision_id"])
        self.assertEqual(undone["components"], original["components"])
        redone = self.doc.move_history(1, undone["revision_id"])
        self.assertEqual(redone["components"], committed["components"])
        self.assertEqual(Document(self.doc.folder).current()["components"], committed["components"])
        copied = self.doc.save_as(self.folder / "copy.cadproj")
        self.assertEqual(copied.current()["components"], committed["components"])
        with self.assertRaises(WorkspaceError):
            tools.call("cad_standard_part", params)  # stale candidate token
        with self.assertRaises(WorkspaceError):
            tools.call("cad_standard_part", {"candidate_id": tools.candidate_id, "instance_id": "block", "parameters": {}})

    def test_invalid_parameters_and_worker_isolation(self):
        before = self.workspace.geometry("capabilities", {})
        for request in (
            {"generator_id": "os.system"},
            {"generator_id": "fastener.HexNut", "parameters": {"size": "M6-1", "fastener_type": "fake"}},
            {"generator_id": "fastener.HexNut", "parameters": {"size": "M6-1", "fastener_type": "iso4032", "simple": "false"}},
            {"generator_id": "thread.IsoThread", "parameters": {"major_diameter": True, "pitch": 1, "length": 5}},
            {"generator_id": "sprocket.Sprocket", "parameters": {"num_teeth": 10, "arbitrary": 3}},
        ):
            with self.subTest(request=request), self.assertRaises(WorkspaceError):
                self.call("standard_part", **request)
        self.create("sprocket.Sprocket", {"num_teeth": 16})
        self.assertEqual(self.workspace.geometry("capabilities", {}), before)
        self.assertFalse(hasattr(cq.Workplane, "clearanceHole"))
        self.workspace.cancelled.set()
        with self.assertRaises(WorkspaceError) as cancelled:
            self.call("standard_parts")
        self.assertEqual(cancelled.exception.code, "cancelled")

    def test_thread_variants_and_topology_regeneration_guard(self):
        for external, hand in ((True, "left"), (False, "right")):
            result = self.create("thread.IsoThread", {"major_diameter": 6, "pitch": 1, "length": 4,
                "external": external, "hand": hand, "end_finishes": ["fade", "fade"]})
            self.assertTrue(result["components"][0]["metrics"]["brep_valid"])
        original = self.create("sprocket.Sprocket", {"num_teeth": 16})
        part = original["components"][0]
        self.workspace.document = self.doc
        snapshot = self.doc.commit(original)
        drilled = self.workspace.geometry("apply", {"project_dir": str(self.doc.folder), "snapshot": snapshot,
            "command": {"type": "hole", "instance_id": part["instance_id"], "diameter": 3, "centres": [[0, 0]]}})
        changed = self.doc.commit(drilled, snapshot["revision_id"])
        with self.assertRaises(WorkspaceError) as dirty:
            self.call("standard_part", drilled, instance_id=part["instance_id"], parameters={"num_teeth": 18})
        self.assertEqual(dirty.exception.code, "downstream_edits")
        undone = self.doc.move_history(-1, changed["revision_id"])
        updated = self.call("standard_part", undone, instance_id=part["instance_id"], parameters={"num_teeth": 18})
        self.assertEqual(updated["components"][0]["instance_id"], part["instance_id"])
        # Numeric UI edits also dispatch through a fresh worker.
        numeric = self.workspace.geometry("apply", {"project_dir": str(self.doc.folder), "snapshot": updated,
            "command": {"type": "parameters", "instance_id": part["instance_id"], "values": {"num_teeth": 20}}})
        self.assertEqual(numeric["components"][0]["standard_part"]["parameters"]["num_teeth"], 20)


class CompoundEditTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "tmp").mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT / "tmp")
        self.folder = Path(self.temporary.name)
        self.solids = [cq.Workplane("XY").box(10, 10, 10).translate((x, 0, 0)).val() for x in (0, 30)]
        asset = geometry.store_shape(self.folder, cq.Compound.makeCompound(self.solids), allow_compound=True)
        self.part = {"instance_id": "compound", "definition_id": "compound", "name": "Synthetic pair", "parent_id": None, "matrix": geometry.IDENTITY, "color": [0.3, 0.4, 0.5], **asset}
        self.snapshot = {"components": [self.part], "assembly_nodes": []}

    def tearDown(self):
        self.temporary.cleanup()

    def apply(self, kind, **options):
        return geometry.apply_command(self.folder, self.snapshot, {"type": kind, "instance_id": "compound", **options})

    def unchanged_second(self, candidate):
        shape = geometry.load_shape(self.folder, candidate["components"][0])
        self.assertEqual(len(shape.Solids()), 2)
        other = next(s for s in shape.Solids() if s.Center().x > 20)
        self.assertAlmostEqual(other.Volume(), self.solids[1].Volume())
        self.assertAlmostEqual(other.intersect(self.solids[1]).Volume(), other.Volume())

    def test_direct_edge_face_hole_and_boolean_operations(self):
        body = geometry.load_shape(self.folder, self.part)
        edges = geometry.indexed(body, TopAbs_EDGE)
        index = next(i for i, edge in enumerate(edges, 1) if edge.Center().x < 10)
        for kind in ("fillet", "chamfer"):
            self.unchanged_second(self.apply(kind, size=1, edge_indices=[index]))
        self.unchanged_second(self.apply("hole", diameter=2, centres=[[0, 0]]))
        faces = geometry.indexed(body, TopAbs_FACE)
        top = next(i for i, f in enumerate(faces, 1) if f.Center().x < 10 and f.normalAt().z > 0.9)
        self.unchanged_second(self.apply("offset_face", face_index=top, distance=1))
        self.unchanged_second(self.apply("face_holes", face_index=top, diameter=2, centres=[[0, 0]], depth=2))
        moved = self.apply("transform", translation=[10, 5, 0], rotation=[0, 0, 90])
        world = geometry.world_shape(self.folder, moved["components"][0])
        self.assertEqual(len(world.Solids()), 2)
        self.assertAlmostEqual(world.BoundingBox().ylen, 40)
        self.assertEqual(moved["components"][0]["asset_hash"], self.part["asset_hash"])
        batch = geometry.apply_face_batch(self.folder, self.snapshot, [{"type": "offset_face", "instance_id": "compound", "face_index": top, "distance": 1}])
        self.unchanged_second(batch)
        tool = cq.Workplane("XY").box(2, 2, 20).val()
        tool_part = {**self.part, "instance_id": "tool", "definition_id": "tool", "name": "Cutter", **geometry.store_shape(self.folder, tool)}
        self.snapshot["components"].append(tool_part)
        changed = self.apply("boolean", tool_instance_id="tool", operation="cut")
        self.unchanged_second(changed)
        self.assertEqual(changed["components"][1], tool_part)

    def test_strict_storage_stale_references_and_round_trip(self):
        with self.assertRaises(WorkspaceError):
            geometry.store_shape(self.folder, cq.Compound.makeCompound(self.solids))
        for options in ({"size": 1, "edge_indices": [999]}, {"size": 1000, "edge_indices": [1]}):
            with self.assertRaises((WorkspaceError, StdFail_NotDone)):
                self.apply("fillet", **options)
        self.assertAlmostEqual(geometry.load_shape(self.folder, self.part).Volume(), 2000)
        path = self.folder / "pair.step"
        geometry.export_step(self.folder, self.snapshot, path)
        report = geometry.verify_export(self.folder, self.snapshot, path)
        self.assertEqual((report["component_count"], report["solid_count"]), (1, 2))
        imported = geometry.import_step(path, self.folder)
        self.assertEqual(len(imported["components"]), 1)
        self.assertEqual(imported["components"][0]["metrics"]["solid_count"], 2)
        self.assertNotIn("standard_part", imported["components"][0])


if __name__ == "__main__":
    unittest.main()

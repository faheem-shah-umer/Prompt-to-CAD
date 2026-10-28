import tempfile
import os
import unittest
from pathlib import Path

import numpy as np
import trimesh

from backend.native.contracts import WorkspaceError
from backend.v2.cad_tools import TaskTools
from backend.v2.meshes import load
from backend.v2.workspace import WorkspaceV2

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(os.name == "nt", "V2 native workers and DPAPI require Windows")
class MeshWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT / "tmp")
        self.folder = Path(self.temporary.name)
        self.workspace = WorkspaceV2(self.folder / "workspace")
        self.workspace.dispatch("v2.project.create", {"name": "Mesh fixture"})
        self.source = self.folder / "visual.glb"
        mesh = trimesh.creation.icosphere(subdivisions=2, radius=10)
        mesh.visual.face_colors = [120, 170, 220, 255]
        trimesh.Scene(mesh).export(self.source)
        self.document = self.workspace.dispatch("v2.import", {"path": str(self.source), "mm_per_unit": 1})["document"]
        self.part = self.document["components"][0]
        self.assertEqual(len(self.workspace.state()["project"]["documents"]), 1)
        self.assertEqual(len(self.workspace.state()["conversations"]), 1)

    def tearDown(self):
        self.workspace.worker.close()
        self.temporary.cleanup()

    def tools(self, region=False):
        selection = {
            "revision_id": self.document["revision_id"],
            "instance_id": self.part["instance_id"],
            "kind": "region" if region else "body",
            "index": 1 if region else 0,
        }
        if region:
            selection["triangle_indices"] = [1, 2, 3, 4]
        return TaskTools(
            self.workspace, self.workspace.document, self.document, selection, self.workspace.project_id, "mesh-test"
        )

    def test_mesh_round_trip_region_color_separation_and_reopen(self):
        self.assertEqual(self.part["representation"], "mesh")
        self.assertEqual(self.part["topology"]["faces"], 0)
        tools = self.tools(region=True)
        info = tools.call(
            "cad_inspect", {"candidate_id": tools.candidate_id, "instance_id": self.part["instance_id"], "limit": 7}
        )
        self.assertEqual(len(info["components"][0]["regions"]), 7)
        before = load(self.workspace.document.folder, self.part)
        tools.call(
            "cad_apply",
            {
                "candidate_id": tools.candidate_id,
                "command": {
                    "type": "mesh_color",
                    "instance_id": self.part["instance_id"],
                    "triangle_indices": [1, 2, 3, 4],
                    "color": [230, 60, 90],
                },
            },
        )
        after = load(self.workspace.document.folder, tools.candidate["components"][0])
        np.testing.assert_array_equal(before.vertices, after.vertices)
        np.testing.assert_array_equal(before.faces, after.faces)
        np.testing.assert_array_equal(before.visual.face_colors[4:], after.visual.face_colors[4:])
        with self.assertRaises(WorkspaceError):
            tools.call(
                "cad_apply",
                {
                    "candidate_id": tools.candidate_id,
                    "command": {
                        "type": "mesh_color",
                        "instance_id": self.part["instance_id"],
                        "triangle_indices": [5],
                        "color": [0, 0, 0],
                    },
                },
            )
        report = tools.call("cad_validate", {"candidate_id": tools.candidate_id})
        self.assertTrue(report["geometry"]["passed"])
        self.workspace.document.commit(
            tools.candidate, self.document["revision_id"], summary="Recolored explicit region", commands=tools.commands
        )
        current = self.workspace.document.current()
        self.assertEqual(current["components"][0]["asset_hash"], tools.candidate["components"][0]["asset_hash"])
        tools = TaskTools(
            self.workspace,
            self.workspace.document,
            current,
            {
                "revision_id": current["revision_id"],
                "instance_id": self.part["instance_id"],
                "kind": "region",
                "index": 1,
                "triangle_indices": [1, 2, 3, 4],
            },
            self.workspace.project_id,
            "separate",
        )
        tools.call(
            "cad_apply",
            {
                "candidate_id": tools.candidate_id,
                "command": {
                    "type": "mesh_separate",
                    "instance_id": self.part["instance_id"],
                    "triangle_indices": [1, 2, 3, 4],
                },
            },
        )
        self.assertEqual(len(tools.candidate["components"]), 2)
        self.assertEqual(sum(p["topology"]["triangles"] for p in tools.candidate["components"]), len(before.faces))
        self.assertTrue(tools.call("cad_validate", {"candidate_id": tools.candidate_id})["geometry"]["passed"])

    def test_mesh_export_formats_and_solid_operations_are_distinct(self):
        for extension in ("glb", "stl"):
            result = self.workspace.dispatch(
                "v2.export",
                {"base_revision_id": self.document["revision_id"], "path": str(self.folder / ("out." + extension))},
            )
            self.assertTrue(result["verification"]["passed"])
        with self.assertRaises(WorkspaceError):
            self.workspace.dispatch(
                "v2.export", {"base_revision_id": self.document["revision_id"], "path": str(self.folder / "out.step")}
            )
        tools = self.tools()
        with self.assertRaises(WorkspaceError):
            tools.call(
                "cad_apply",
                {
                    "candidate_id": tools.candidate_id,
                    "command": {
                        "type": "hole",
                        "instance_id": self.part["instance_id"],
                        "diameter": 2,
                        "centres": [[0, 0]],
                    },
                },
            )
        self.assertEqual(self.workspace.document.current()["revision_id"], self.document["revision_id"])

    def test_region_move_preserves_unselected_triangles(self):
        tools = self.tools()
        # A connected spherical cap has interior vertices and a fixed shared boundary.
        original = load(self.workspace.document.folder, self.part)
        ids = np.where(original.triangles_center[:, 2] > 2)[0]
        tools.call(
            "cad_apply",
            {
                "candidate_id": tools.candidate_id,
                "command": {
                    "type": "mesh_region_move",
                    "instance_id": self.part["instance_id"],
                    "triangle_indices": (ids + 1).tolist(),
                    "translation": [0, 0, 2],
                },
            },
        )
        changed = load(self.workspace.document.folder, tools.candidate["components"][0])
        untouched = np.setdiff1d(np.arange(len(original.faces)), ids)
        np.testing.assert_array_equal(original.triangles[untouched], changed.triangles[untouched])
        self.assertGreater(np.max(changed.vertices[:, 2]), np.max(original.vertices[:, 2]))


if __name__ == "__main__":
    unittest.main()

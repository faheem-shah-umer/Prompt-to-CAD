import unittest
from types import SimpleNamespace

import cadquery as cq

from backend.native.geometry import check_new_intersections
from backend.native.modelling import verify_assembly


class AssemblyBroadPhaseTests(unittest.TestCase):
    def builder(self):
        return SimpleNamespace(
            design=SimpleNamespace(relationships=[], allowed_intersections=[]),
            parameters=SimpleNamespace(raw={}, used_parameters=lambda: set(), dependencies={}),
            component_dependencies={},
        )

    def component(self, identity, x, bounds=None):
        shape = cq.Workplane("XY").box(1, 1, 1).translate((x, 0, 0)).val()
        return SimpleNamespace(
            component=SimpleNamespace(id=identity, attachment=None),
            shape=shape,
            validation={"bounds_mm": bounds or [[x - 0.5, -0.5, -0.5], [x + 0.5, 0.5, 0.5]]},
        )

    def test_separated_components_skip_exact_intersection(self):
        report = verify_assembly(self.builder(), [self.component("a", 0), self.component("b", 3)])
        self.assertEqual(report["verification_timing"]["candidate_pairs"], 1)
        self.assertEqual(report["verification_timing"]["skipped_pairs"], 1)
        self.assertEqual(report["verification_timing"]["exact_intersections_checked"], 0)

    def test_touching_and_overlapping_components_use_exact_intersection(self):
        touching = verify_assembly(self.builder(), [self.component("a", 0), self.component("b", 1)])
        self.assertEqual(touching["verification_timing"]["exact_intersections_checked"], 1)
        self.assertEqual(touching["interferences"], [])
        with self.assertRaises(Exception):
            verify_assembly(self.builder(), [self.component("a", 0), self.component("b", 0.75)])

    def test_uncertain_bounds_use_exact_intersection(self):
        uncertain = [[float("nan"), -0.5, -0.5], [0.5, 0.5, 0.5]]
        report = verify_assembly(self.builder(), [self.component("a", 0, uncertain), self.component("b", 3)])
        self.assertEqual(report["verification_timing"]["skipped_pairs"], 0)
        self.assertEqual(report["verification_timing"]["exact_intersections_checked"], 1)

    def test_active_intersection_stats_are_available_on_failure(self):
        first = self.component("a", 0)
        second = self.component("b", 0)
        before = {
            "components": [
                {"instance_id": "a", "asset_hash": "old-a", "matrix": []},
                {"instance_id": "b", "asset_hash": "old-b", "matrix": []},
            ]
        }
        after = {
            "components": [
                {"instance_id": "a", "name": "a", "asset_hash": "new-a", "matrix": []},
                {"instance_id": "b", "name": "b", "asset_hash": "old-b", "matrix": []},
            ]
        }
        stats = {}
        with self.assertRaises(Exception) as error:
            check_new_intersections(
                ".",
                before,
                after,
                {"type": "script"},
                shape_for=lambda part: (
                    first.shape if part["instance_id"] == "a" and part["asset_hash"] == "new-a"
                    else cq.Workplane("XY").box(1, 1, 1).translate((3, 0, 0)).val()
                    if part["instance_id"] == "a"
                    else second.shape
                ),
                stats=stats,
            )
        self.assertEqual(error.exception.details["intersection"], stats)
        self.assertEqual(stats["exact_intersections_checked"], 1)
        self.assertIn("elapsed_seconds", stats)


if __name__ == "__main__":
    unittest.main()

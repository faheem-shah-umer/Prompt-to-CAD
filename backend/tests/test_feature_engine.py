import math
import unittest
from pathlib import Path

from pydantic import ValidationError

from backend.native.design_schema import Design
from backend.native.modelling import Builder, verify_assembly
from backend.native.parameters import DesignError, Parameters

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def example():
    return Design.model_validate_json(
        (PROJECT_ROOT / "examples/spindle-assembly.cad.json").read_text()
    )


def single(features, parameters=None):
    return Design(
        name="Feature test",
        components=[
            {
                "id": "part",
                "name": "Part",
                "parameters": parameters or {},
                "features": features,
            }
        ],
    )


class FeatureEngineTests(unittest.TestCase):
    def test_drilling_through_blind_and_transverse_holes_rejects_unused_sketch_fields(
        self,
    ):
        for axis, depth, length in [("Z", None, 4), ("Z", 1.5, 1.5), ("X", None, 20)]:
            spec = single(
                [
                    {"id": "body", "type": "box", "size": [20, 20, 4]},
                    {
                        "id": "holes",
                        "type": "hole",
                        "radius": 1,
                        "centres": [[-5, 0], [5, 0]],
                        "axis": axis,
                        "depth": depth,
                    },
                ]
            )
            part = Builder(spec).build()[0]
            with self.subTest(axis=axis, depth=depth):
                self.assertAlmostEqual(
                    part.shape.Volume(), 1600 - 2 * math.pi * length, places=4
                )
        with self.assertRaises(ValidationError):
            single(
                [
                    {
                        "id": "bad",
                        "type": "sketch",
                        "profile": "circle",
                        "radius": 3,
                        "points": [[0, 26], [0, -26], [26, 0], [-26, 0]],
                    }
                ]
            )

    def test_parameter_dependencies_and_arithmetic_reject_code_and_cycles(self):
        spec = example()
        spec.parameters["clearance"] = 0.2
        spec.components[1].parameters["derived"] = (
            "base.thickness + shared.clearance + sqrt(4)"
        )
        parameters = Parameters(spec)
        self.assertAlmostEqual(parameters.resolved["post.derived"], 10.2)
        self.assertEqual(
            parameters.dependencies["post.derived"],
            {"base.thickness", "shared.clearance"},
        )
        for expression in [
            "__import__('os').system('echo unsafe')",
            "post.height",
            "2**100",
            "(1).__class__",
        ]:
            candidate = spec.model_copy(deep=True)
            candidate.components[1].parameters["height"] = expression
            with self.subTest(expression=expression), self.assertRaises(DesignError):
                Parameters(candidate)

    def test_assembly_patterns_loft_measurements_and_mates(self):
        builder = Builder(example())
        parts = builder.build()
        report = verify_assembly(builder, parts)
        self.assertEqual(report["solid_count"], 3)
        self.assertTrue(report["passed"])
        base = parts[0]
        expected = (
            80 * 60 - 4 * (3**2 - math.pi * 3**2 / 4)
        ) * 8 - 4 * math.pi * 3**2 * 8
        self.assertAlmostEqual(base.shape.Volume(), expected, places=4)
        self.assertEqual(len(base.features), 4)
        self.assertTrue(all(item["passed"] for item in report["relationships"]))

    def test_extrude_revolve_sweep_and_closed_spline_are_real_solids(self):
        cases = [
            (
                [
                    {
                        "id": "profile",
                        "type": "sketch",
                        "profile": "rectangle",
                        "width": 6,
                        "height": 4,
                    },
                    {
                        "id": "solid",
                        "type": "extrude",
                        "sketch": "profile",
                        "distance": 10,
                    },
                ],
                240,
            ),
            (
                [
                    {
                        "id": "profile",
                        "type": "sketch",
                        "plane": "XZ",
                        "profile": "polygon",
                        "points": [[2, 0], [5, 0], [5, 8], [2, 8]],
                    },
                    {"id": "solid", "type": "revolve", "sketch": "profile"},
                ],
                math.pi * (25 - 4) * 8,
            ),
            (
                [
                    {
                        "id": "profile",
                        "type": "sketch",
                        "profile": "circle",
                        "radius": 2,
                    },
                    {
                        "id": "solid",
                        "type": "sweep",
                        "sketch": "profile",
                        "path": [[0, 0, 0], [0, 0, 10]],
                    },
                ],
                math.pi * 4 * 10,
            ),
            (
                [
                    {
                        "id": "profile",
                        "type": "sketch",
                        "profile": "spline",
                        "points": [[5, 0], [0, 4], [-5, 0], [0, -4]],
                    },
                    {
                        "id": "solid",
                        "type": "extrude",
                        "sketch": "profile",
                        "distance": 3,
                    },
                ],
                None,
            ),
        ]
        for features, volume in cases:
            with self.subTest(operation=features[-1]["type"]):
                part = Builder(single(features)).build()[0]
                self.assertTrue(part.shape.isValid())
                self.assertEqual(len(part.shape.Solids()), 1)
                if volume:
                    self.assertAlmostEqual(part.shape.Volume(), volume, places=4)

    def test_linear_pattern_mirror_and_cross_component_boolean(self):
        spec = single(
            [
                {"id": "base", "type": "box", "size": [30, 20, 5]},
                {
                    "id": "hole",
                    "type": "cylinder",
                    "radius": 1,
                    "height": 10,
                    "placement": {"translation": [-8, 0, -5]},
                    "operation": "cut",
                },
                {
                    "id": "repeated",
                    "type": "linear_pattern",
                    "feature": "hole",
                    "count": 3,
                    "step": [8, 0, 0],
                    "operation": "cut",
                },
            ]
        )
        part = Builder(spec).build()[0]
        self.assertAlmostEqual(part.shape.Volume(), 3000 - 3 * math.pi * 5, places=4)
        mirrored = single(
            [
                {"id": "base", "type": "box", "size": [30, 20, 5]},
                {
                    "id": "hole",
                    "type": "cylinder",
                    "radius": 1,
                    "height": 10,
                    "placement": {"translation": [-8, 0, -5]},
                    "operation": "cut",
                },
                {
                    "id": "mirror",
                    "type": "mirror",
                    "feature": "hole",
                    "operation": "cut",
                },
            ]
        )
        self.assertAlmostEqual(
            Builder(mirrored).build()[0].shape.Volume(),
            3000 - 2 * math.pi * 5,
            places=4,
        )
        cross = Design(
            name="Boolean",
            components=[
                {
                    "id": "plate",
                    "name": "Plate",
                    "features": [
                        {"id": "block", "type": "box", "size": [20, 20, 4]},
                        {
                            "id": "bore",
                            "type": "boolean",
                            "component": "tool",
                            "operation": "cut",
                            "placement": {"translation": [0, 0, -3]},
                        },
                    ],
                },
                {
                    "id": "tool",
                    "name": "Tool",
                    "placement": {"translation": [40, 0, 0]},
                    "features": [
                        {"id": "drill", "type": "cylinder", "radius": 2, "height": 6}
                    ],
                },
            ],
        )
        builder = Builder(cross)
        parts = builder.build()
        self.assertAlmostEqual(
            parts[0].shape.Volume(), 1600 - math.pi * 4 * 4, places=4
        )
        self.assertEqual(builder.component_dependencies["plate"], {"tool"})

    def test_external_and_internal_threads_use_helical_geometry(self):
        bolt = Design.model_validate_json(
            (PROJECT_ROOT / "examples" / "threaded-bolt.cad.json").read_text()
        )
        part = Builder(bolt).build()[0]
        self.assertTrue(part.validation["passed"])
        self.assertGreater(len(part.local_shape.Faces()), 12)
        self.assertTrue(
            any(
                face.geomType() not in ("PLANE", "CYLINDER")
                for face in part.local_shape.Faces()
            )
        )
        nut = single(
            [
                {"id": "blank", "type": "cylinder", "radius": 7, "height": 5},
                {
                    "id": "thread",
                    "type": "thread",
                    "major_radius": 4,
                    "minor_radius": 3.4,
                    "pitch": 1.5,
                    "length": 5,
                    "internal": True,
                },
            ]
        )
        internal = Builder(nut).build()[0]
        self.assertLess(internal.local_shape.Volume(), math.pi * (49 - 3.4**2) * 5)
        self.assertTrue(internal.validation["passed"])

    def test_bad_cuts_dimensions_mates_and_interference_are_rejected(self):
        bad_cut = single(
            [
                {"id": "body", "type": "box", "size": [10, 10, 10]},
                {
                    "id": "missing_cut",
                    "type": "cylinder",
                    "radius": 1,
                    "height": 10,
                    "operation": "cut",
                    "placement": {"translation": [100, 0, 0]},
                },
            ]
        )
        with self.assertRaisesRegex(DesignError, "did not remove"):
            Builder(bad_cut).build()
        wrong_dimensions = single([{"id": "body", "type": "box", "size": [10, 10, 10]}])
        wrong_dimensions.components[0].expected_size = (20, 10, 10)
        with self.assertRaisesRegex(DesignError, "dimensions"):
            Builder(wrong_dimensions).build()
        for translation, expected in [
            ([0, 0, 8], "relationship"),
            ([0, 0, 0], "intersect"),
        ]:
            spec = example()
            spec.components[1].placement.translation = tuple(translation)
            if expected == "intersect":
                spec.relationships = []
            builder = Builder(spec)
            parts = builder.build()
            with (
                self.subTest(case=expected),
                self.assertRaisesRegex(DesignError, expected),
            ):
                verify_assembly(builder, parts)

import copy
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app import projects
from backend.app.config import PROJECT_ROOT
from backend.app.design_edits import apply_changes
from backend.app.design_schema import Design, DesignPlan, EditPlan
from backend.app.llm_client import LLMError, LLMResponse, LLMSettings
from backend.app.main import app
from backend.app.modelling import Builder, verify_assembly
from backend.app.parameters import DesignError, Parameters
from backend.app.project_lock import revision_lock


def example():
    return Design.model_validate_json((PROJECT_ROOT / "examples" / "spindle-assembly.cad.json").read_text())


def single(features, parameters=None):
    return Design(name="Feature test", components=[{"id": "part", "name": "Part",
                  "parameters": parameters or {}, "features": features}])


def edited_height(height):
    return EditPlan(status="ready", description=f"Set spindle height to {height} mm",
                    changes=[{"type": "set_parameters", "component_id": "post", "values": {"height": height}}])


class FeatureEngineTests(unittest.TestCase):
    def test_drilling_through_blind_and_transverse_holes_rejects_unused_sketch_fields(self):
        for axis, depth, length in [("Z", None, 4), ("Z", 1.5, 1.5), ("X", None, 20)]:
            spec = single([{"id": "body", "type": "box", "size": [20, 20, 4]},
                           {"id": "holes", "type": "hole", "radius": 1,
                            "centres": [[-5, 0], [5, 0]], "axis": axis, "depth": depth}])
            part = Builder(spec).build()[0]
            with self.subTest(axis=axis, depth=depth):
                self.assertAlmostEqual(part.shape.Volume(), 1600 - 2 * math.pi * length, places=4)
        with self.assertRaises(ValidationError):
            single([{"id": "bad", "type": "sketch", "profile": "circle", "radius": 3,
                     "points": [[0, 26], [0, -26], [26, 0], [-26, 0]]}])

    def test_parameter_dependencies_and_arithmetic_reject_code_and_cycles(self):
        spec = example()
        spec.parameters["clearance"] = 0.2
        spec.components[1].parameters["derived"] = "base.thickness + shared.clearance + sqrt(4)"
        parameters = Parameters(spec)
        self.assertAlmostEqual(parameters.resolved["post.derived"], 10.2)
        self.assertEqual(parameters.dependencies["post.derived"], {"base.thickness", "shared.clearance"})
        for expression in ["__import__('os').system('echo unsafe')", "post.height", "2**100", "(1).__class__"]:
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
        expected = (80 * 60 - 4 * (3**2 - math.pi * 3**2 / 4)) * 8 - 4 * math.pi * 3**2 * 8
        self.assertAlmostEqual(base.shape.Volume(), expected, places=4)
        self.assertEqual(len(base.features), 4)
        self.assertTrue(all(item["passed"] for item in report["relationships"]))

    def test_extrude_revolve_sweep_and_closed_spline_are_real_solids(self):
        cases = [
            ([{"id": "profile", "type": "sketch", "profile": "rectangle", "width": 6, "height": 4},
              {"id": "solid", "type": "extrude", "sketch": "profile", "distance": 10}], 240),
            ([{"id": "profile", "type": "sketch", "plane": "XZ", "profile": "polygon",
               "points": [[2, 0], [5, 0], [5, 8], [2, 8]]},
              {"id": "solid", "type": "revolve", "sketch": "profile"}], math.pi * (25 - 4) * 8),
            ([{"id": "profile", "type": "sketch", "profile": "circle", "radius": 2},
              {"id": "solid", "type": "sweep", "sketch": "profile", "path": [[0, 0, 0], [0, 0, 10]]}], math.pi * 4 * 10),
            ([{"id": "profile", "type": "sketch", "profile": "spline",
               "points": [[5, 0], [0, 4], [-5, 0], [0, -4]]},
              {"id": "solid", "type": "extrude", "sketch": "profile", "distance": 3}], None),
        ]
        for features, volume in cases:
            with self.subTest(operation=features[-1]["type"]):
                part = Builder(single(features)).build()[0]
                self.assertTrue(part.shape.isValid())
                self.assertEqual(len(part.shape.Solids()), 1)
                if volume:
                    self.assertAlmostEqual(part.shape.Volume(), volume, places=4)

    def test_linear_pattern_mirror_and_cross_component_boolean(self):
        spec = single([
            {"id": "base", "type": "box", "size": [30, 20, 5]},
            {"id": "hole", "type": "cylinder", "radius": 1, "height": 10,
             "placement": {"translation": [-8, 0, -5]}, "operation": "cut"},
            {"id": "repeated", "type": "linear_pattern", "feature": "hole", "count": 3,
             "step": [8, 0, 0], "operation": "cut"}])
        part = Builder(spec).build()[0]
        self.assertAlmostEqual(part.shape.Volume(), 3000 - 3 * math.pi * 5, places=4)
        mirrored = single([
            {"id": "base", "type": "box", "size": [30, 20, 5]},
            {"id": "hole", "type": "cylinder", "radius": 1, "height": 10,
             "placement": {"translation": [-8, 0, -5]}, "operation": "cut"},
            {"id": "mirror", "type": "mirror", "feature": "hole", "operation": "cut"}])
        self.assertAlmostEqual(Builder(mirrored).build()[0].shape.Volume(), 3000 - 2 * math.pi * 5, places=4)
        cross = Design(name="Boolean", components=[
            {"id": "plate", "name": "Plate", "features": [{"id": "block", "type": "box", "size": [20, 20, 4]},
             {"id": "bore", "type": "boolean", "component": "tool", "operation": "cut",
              "placement": {"translation": [0, 0, -3]}}]},
            {"id": "tool", "name": "Tool", "placement": {"translation": [40, 0, 0]},
             "features": [{"id": "drill", "type": "cylinder", "radius": 2, "height": 6}]}])
        builder = Builder(cross)
        parts = builder.build()
        self.assertAlmostEqual(parts[0].shape.Volume(), 1600 - math.pi * 4 * 4, places=4)
        self.assertEqual(builder.component_dependencies["plate"], {"tool"})

    def test_external_and_internal_threads_use_helical_geometry(self):
        bolt = Design.model_validate_json((PROJECT_ROOT / "examples" / "threaded-bolt.cad.json").read_text())
        part = Builder(bolt).build()[0]
        self.assertTrue(part.validation["passed"])
        self.assertGreater(len(part.local_shape.Faces()), 12)
        self.assertTrue(any(face.geomType() not in ("PLANE", "CYLINDER") for face in part.local_shape.Faces()))
        nut = single([
            {"id": "blank", "type": "cylinder", "radius": 7, "height": 5},
            {"id": "thread", "type": "thread", "major_radius": 4, "minor_radius": 3.4,
             "pitch": 1.5, "length": 5, "internal": True}])
        internal = Builder(nut).build()[0]
        self.assertLess(internal.local_shape.Volume(), math.pi * (49 - 3.4**2) * 5)
        self.assertTrue(internal.validation["passed"])

    def test_bad_cuts_dimensions_mates_and_interference_are_rejected(self):
        bad_cut = single([{"id": "body", "type": "box", "size": [10, 10, 10]},
                          {"id": "missing_cut", "type": "cylinder", "radius": 1, "height": 10,
                           "operation": "cut", "placement": {"translation": [100, 0, 0]}}])
        with self.assertRaisesRegex(DesignError, "did not remove"):
            Builder(bad_cut).build()
        wrong_dimensions = single([{"id": "body", "type": "box", "size": [10, 10, 10]}])
        wrong_dimensions.components[0].expected_size = (20, 10, 10)
        with self.assertRaisesRegex(DesignError, "dimensions"):
            Builder(wrong_dimensions).build()
        for translation, expected in [([0, 0, 8], "relationship"), ([0, 0, 0], "intersect")]:
            spec = example()
            spec.components[1].placement.translation = tuple(translation)
            if expected == "intersect":
                spec.relationships = []
            builder = Builder(spec)
            parts = builder.build()
            with self.subTest(case=expected), self.assertRaisesRegex(DesignError, expected):
                verify_assembly(builder, parts)

    def test_selected_edit_preserves_ids_and_other_part_definitions(self):
        spec = example()
        candidate = apply_changes(spec, edited_height(48), "post")
        self.assertEqual([c.id for c in candidate.components], [c.id for c in spec.components])
        self.assertEqual(candidate.components[0], spec.components[0])
        self.assertEqual(candidate.components[2], spec.components[2])
        parts = Builder(candidate).build()
        self.assertAlmostEqual(parts[2].validation["bounds_mm"][0][2], 52, places=4)
        with self.assertRaisesRegex(DesignError, "selected part"):
            apply_changes(spec, edited_height(48), "base")


class ProjectPersistenceTests(unittest.TestCase):
    def setUp(self):
        (PROJECT_ROOT / "tmp").mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "tmp")
        self.root_patch = patch.object(projects, "PROJECTS_DIR", Path(self.temporary.name))
        self.root_patch.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.root_patch.stop()
        self.temporary.cleanup()

    def create(self):
        response = self.client.post("/api/projects/from-spec", json=example().model_dump(mode="json"))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_another_window_lock_prevents_overwriting_a_revision(self):
        initial = self.create()
        path = f"/api/projects/{initial['project_id']}"
        with revision_lock(projects.PROJECTS_DIR / initial["project_id"]):
            rejected = self.client.post(path + "/changes", json={"request": {"base_revision_id": initial["revision_id"]},
                                        "plan": edited_height(48).model_dump(mode="json")})
        self.assertEqual(rejected.status_code, 409, rejected.text)
        self.assertIn("Another application window", rejected.text)
        self.assertEqual(self.client.get(path).json()["revision_id"], initial["revision_id"])

    def test_unused_parameter_change_cannot_be_saved_as_a_geometry_edit(self):
        spec = example()
        spec.components[0].parameters["unused_diameter"] = 52
        initial = projects.save_revision(spec)
        plan = EditPlan(status="ready", description="Change unused value", changes=[
            {"type": "set_parameters", "component_id": "base", "values": {"unused_diameter": 60}}])
        candidate = apply_changes(spec, plan, "base")
        with self.assertRaisesRegex(DesignError, "does not drive geometry"):
            projects.save_revision(candidate, project_id=initial["project_id"], base_revision_id=initial["revision_id"])
        self.assertEqual(projects.read_project(initial["project_id"])["revision_id"], initial["revision_id"])

    def test_exports_preserve_separate_components_and_editable_history(self):
        project = self.create()
        self.assertEqual(project["validation"]["step_roundtrip"]["solid_count"], 3)
        self.assertTrue(project["validation"]["checks"]["step_roundtrip_valid"])
        for part in project["components"]:
            response = self.client.get(part["preview_url"])
            self.assertEqual(response.status_code, 200)
            self.assertGreater(len(response.content), 100)
        editable = self.client.get(project["downloads"]["project"]).json()
        self.assertEqual(editable, example().model_dump(mode="json"))
        self.assertEqual(len(self.client.get("/api/projects").json()), 1)
        path = f"/api/projects/{project['project_id']}"
        self.assertEqual(self.client.get(path).json()["revision_id"], project["revision_id"])
        absent = project["components"][0]["preview_url"].replace("base.stl", "unknown.stl")
        self.assertEqual(self.client.get(absent).status_code, 404)

    def test_helical_thread_step_reimport_preserves_geometry(self):
        design = Design.model_validate_json((PROJECT_ROOT / "examples" / "threaded-bolt.cad.json").read_text())
        response = self.client.post("/api/projects/from-spec", json=design.model_dump(mode="json"))
        self.assertEqual(response.status_code, 200, response.text)
        project = response.json()
        self.assertTrue(project["validation"]["step_roundtrip"]["passed"])
        self.assertEqual(project["validation"]["step_roundtrip"]["solid_count"], 1)
        self.assertEqual(project["design"], design.model_dump(mode="json"))

    def test_revision_undo_redo_branch_and_stale_edit(self):
        first = self.create()
        path = f"/api/projects/{first['project_id']}"
        result = self.client.post(path + "/changes", json={"request": {"base_revision_id": first["revision_id"]},
                                  "plan": edited_height(48).model_dump(mode="json")})
        self.assertEqual(result.status_code, 200, result.text)
        second = result.json()
        self.assertEqual(second["revision_number"], 2)
        self.assertTrue(second["can_undo"])
        self.assertNotEqual(second["revision_id"], first["revision_id"])
        stale = self.client.post(path + "/changes", json={"request": {"base_revision_id": first["revision_id"]},
                                 "plan": edited_height(64).model_dump(mode="json")})
        self.assertEqual(stale.status_code, 409)
        undone = self.client.post(path + "/undo", json={"base_revision_id": second["revision_id"]}).json()
        self.assertEqual(undone["revision_id"], first["revision_id"])
        self.assertTrue(undone["can_redo"])
        redone = self.client.post(path + "/redo", json={"base_revision_id": first["revision_id"]}).json()
        self.assertEqual(redone["revision_id"], second["revision_id"])
        self.client.post(path + "/undo", json={"base_revision_id": second["revision_id"]})
        branch = self.client.post(path + "/changes", json={"request": {"base_revision_id": first["revision_id"]},
                                  "plan": edited_height(40).model_dump(mode="json")}).json()
        self.assertEqual(branch["revision_count"], 2)
        self.assertFalse(branch["can_redo"])
        self.assertEqual(self.client.get(second["downloads"]["project"]).status_code, 200)

    def test_failed_geometry_or_step_export_never_replaces_saved_revision(self):
        initial = self.create()
        path = f"/api/projects/{initial['project_id']}"
        invalid = edited_height(-3)
        failure = self.client.post(path + "/changes", json={"request": {"base_revision_id": initial["revision_id"]},
                                   "plan": invalid.model_dump(mode="json")})
        self.assertEqual(failure.status_code, 422)
        with patch.object(projects, "verify_step", return_value={"passed": False, "solid_count": 0, "components": []}):
            failure = self.client.post(path + "/changes", json={"request": {"base_revision_id": initial["revision_id"]},
                                       "plan": edited_height(40).model_dump(mode="json")})
        self.assertEqual(failure.status_code, 422)
        self.assertEqual(self.client.get(path).json()["revision_id"], initial["revision_id"])

    def test_llm_create_edit_questions_and_provider_failure(self):
        spec = example()
        create_plan = DesignPlan(status="ready", description="Created spindle assembly", design=spec)
        inference = {"provider": "custom", "model": "test", "seconds": 0}
        with patch("backend.app.design_planner.interpret", return_value=(create_plan, inference)) as llm:
            created = self.client.post("/api/projects", json={"prompt": "Create a spindle assembly"})
            self.assertEqual(created.status_code, 200, created.text)
            llm.assert_called_once()
        initial = created.json()["project"]
        path = f"/api/projects/{initial['project_id']}"
        request = {"prompt": "Make the selected spindle 48 mm tall",
                   "base_revision_id": initial["revision_id"], "selected_component_id": "post"}
        with patch("backend.app.design_planner.interpret", return_value=(edited_height(48), inference)) as llm:
            edited = self.client.post(path + "/edits", json=request)
            self.assertEqual(edited.status_code, 200, edited.text)
            self.assertEqual(llm.call_args.args[2], "post")
            self.assertEqual(edited.json()["project"]["design"]["components"][1]["parameters"]["height"], 48)
        current = edited.json()["project"]
        request["base_revision_id"] = current["revision_id"]
        incomplete = EditPlan(status="needs_input", description="Choose a diameter", questions=["What diameter?"])
        with patch("backend.app.design_planner.interpret", return_value=(incomplete, inference)):
            waiting = self.client.post(path + "/edits", json=request)
        self.assertEqual(waiting.status_code, 200)
        self.assertIsNone(waiting.json()["project"])
        with patch("backend.app.design_planner.interpret", side_effect=LLMError("Free quota reached", "quota")) as llm:
            quota = self.client.post(path + "/edits", json=request)
            self.assertEqual(quota.status_code, 429)
            llm.assert_called_once()
        self.assertEqual(self.client.get(path).json()["revision_id"], current["revision_id"])
        invalid_target = copy.deepcopy(request)
        invalid_target["selected_component_id"] = "base"
        with patch("backend.app.design_planner.interpret", return_value=(edited_height(60), inference)):
            rejected = self.client.post(path + "/edits", json=invalid_target)
        self.assertEqual(rejected.status_code, 422)
        self.assertEqual(self.client.get(path).json()["revision_id"], current["revision_id"])


class DesignPlanningTests(unittest.TestCase):
    def test_selected_context_contains_history_and_one_provider_call(self):
        from backend.app import design_planner
        project = {"design": example().model_dump(mode="json"), "assumptions": ["Concept design"]}
        response = LLMResponse(edited_height(48).model_dump_json(), 0.1, 10, 10)
        settings = LLMSettings("test-model", "https://models.example.test/v1", "test-key")
        with patch.object(design_planner, "load_settings", return_value=settings), \
             patch.object(design_planner, "generate_json", return_value=response) as provider:
            plan, inference = design_planner.interpret("Make the selected spindle 48 mm tall", project, "post")
        provider.assert_called_once()
        context = json.loads(provider.call_args.args[1])
        self.assertEqual(context["selected_component_id"], "post")
        self.assertEqual(context["current_design"]["selected_component"]["features"][0]["id"], "post_body")
        self.assertEqual({part["id"] for part in context["current_design"]["other_components"]}, {"base", "cap"})
        self.assertEqual(context["earlier_assumptions"], ["Concept design"])
        self.assertEqual(provider.call_args.kwargs["max_tokens"], 8192)
        self.assertEqual(inference["provider"], "custom")
        self.assertEqual(plan.status, "ready")


if __name__ == "__main__":
    unittest.main()

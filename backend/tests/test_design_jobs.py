import copy
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app import design_jobs, design_planner, projects
from backend.app.assembly_schema import AssemblyPlan, ComponentBatch
from backend.app.config import PROJECT_ROOT
from backend.app.design_schema import Design, DesignPlan, EditPlan
from backend.app.llm_client import LLMError, LLMResponse, LLMSettings
from backend.app.main import app
from backend.app.modelling import Builder, verify_assembly

SETTINGS = LLMSettings("test-model", "https://models.example.test/v1", "test-secret")


def response(value):
    text = value.model_dump_json() if hasattr(value, "model_dump_json") else json.dumps(value)
    return LLMResponse(text, 0.1, 100, 100)


def reference():
    return Design.model_validate_json((PROJECT_ROOT / "examples/gaming-controller.cad.json").read_text())


def outline(design):
    data = design.model_dump(mode="json")
    for part in data["components"]:
        del part["features"]
        part["requirements"] = "Preserve the dimensions and exterior geometry from the original request."
        part["depends_on"] = [] if part["id"] == data["components"][0]["id"] else [data["components"][0]["id"]]
    del data["schema_version"]
    return AssemblyPlan(status="ready", description="Editable concept", assembly=data)


def replies(design):
    parts = design.components
    result = [response(outline(design)), response(batch(parts[:1]))]
    if len(parts) > 3:
        result.insert(1, response(outline(design)))
    result.extend(response(batch(parts[i:i + 3])) for i in range(1, len(parts), 3))
    return result


def batch(parts):
    return ComponentBatch(components=[{"id": part.id, "features": part.features} for part in parts])


class StagedPlanningTests(unittest.TestCase):
    def test_bounding_face_attachment_cannot_accept_a_part_beyond_the_parent_footprint(self):
        spec = Design(name="False contact", components=[
            {"id": "body", "name": "Body", "features": [{"id": "blank", "type": "box", "size": [40, 40, 20]}]},
            {"id": "control", "name": "Control", "attachment": {"parent": "body", "offset": [30, 0]},
             "features": [{"id": "blank", "type": "cylinder", "radius": 4.5, "height": 3}]}])
        builder = Builder(spec)
        with self.assertRaisesRegex(ValueError, "actual surface distance 5.500 mm"):
            verify_assembly(builder, builder.build())

    def test_face_attachment_rebuilds_from_actual_geometry_after_parent_edit(self):
        spec = Design(name="Attached control", components=[
            {"id": "body", "name": "Body", "parameters": {"thickness": 20},
             "features": [{"id": "blank", "type": "box", "size": [40, 40, "thickness"]}]},
            {"id": "control", "name": "Control", "parameters": {"height": 3, "x_offset": 8},
             "features": [{"id": "blank", "type": "box", "size": [8, 8, "height"]}],
             "attachment": {"parent": "body", "offset": ["x_offset", 0]} }],
            relationships=[{"id": "rest", "type": "contact", "component_a": "body", "component_b": "control"}])
        builder = Builder(spec)
        parts = builder.build()
        self.assertAlmostEqual(parts[1].validation["bounds_mm"][0][2], 10)
        self.assertAlmostEqual(parts[1].validation["bounds_mm"][0][0], 4)
        self.assertEqual(verify_assembly(builder, parts)["unused_parameters"], [])
        spec.components[0].parameters["thickness"] = 30
        builder = Builder(spec)
        parts = builder.build()
        self.assertAlmostEqual(parts[1].validation["bounds_mm"][0][2], 15)
        self.assertTrue(verify_assembly(builder, parts)["passed"])
        self.assertIn("body", builder.component_dependencies["control"])
        from backend.app.design_schema import Relationship
        anchored = spec.model_copy(deep=True)
        anchored.relationships.append(Relationship(id="offset_check", type="distance", component_a="body", component_b="control",
                                                  point_a=(0, 0, 15), point_b=(0, 0, -1.5), distance=8))
        anchored_builder = Builder(anchored)
        self.assertTrue(verify_assembly(anchored_builder, anchored_builder.build())["passed"])
        from backend.app.design_edits import apply_changes
        moved = apply_changes(spec, EditPlan(status="ready", description="Move the control", changes=[
            {"type": "set_attachment", "component_id": "control", "attachment": {"parent": "body", "offset": [10, 0]}}]), "control")
        self.assertEqual(moved.components[0], spec.components[0])
        self.assertAlmostEqual(Builder(moved).build()[1].validation["bounds_mm"][0][0], 6)

    def test_local_alias_normalisation_preserves_geometry_and_makes_alias_editable(self):
        spec = Design(name="Alias", parameters={"width": 20}, components=[
            {"id": "part", "name": "Part", "parameters": {"width": "shared.width"},
             "features": [{"id": "blank", "type": "box", "size": ["shared.width", 10, 5]}]}])
        recipe = spec.components[0]
        before = Builder(spec).build()[0].shape.Volume()
        data = recipe.model_dump(mode="json")
        data["features"] = design_planner.localise_features(recipe.features, recipe.parameters)
        spec.components[0] = type(recipe).model_validate(data)
        builder = Builder(spec)
        self.assertAlmostEqual(before, builder.build()[0].shape.Volume())
        self.assertEqual(verify_assembly(builder, builder.build())["unused_parameters"], [])
        spec.components[0].parameters["width"] = 25
        self.assertEqual(Builder(spec).build()[0].validation["local_dimensions_mm"][0], 25)
    def test_repair_contract_keeps_edge_operations_and_excludes_parameter_changes(self):
        from backend.app.design_schema import GeometryRepairPlan
        contract = json.loads(design_planner.prompt_schema(GeometryRepairPlan, {"box", "fillet"}))
        self.assertIn("EdgeTreatment", contract["$defs"])
        self.assertNotIn("Thread", contract["$defs"])
        self.assertNotIn("SetParameters", contract["$defs"])
        plan = GeometryRepairPlan.model_validate({"description": "Move the part", "changes": [
            {"type": "set_placement", "component_id": "part", "placement": {"translation": [0, 0, 10]}}]})
        self.assertEqual(plan.changes[0].placement.translation, (0, 0, 10))

    def test_anchor_distance_checks_world_positions_and_tracks_spacing_parameter(self):
        spec = Design(name="Spacing", parameters={"pitch": 12}, components=[
            {"id": "a", "name": "A", "features": [{"id": "blank", "type": "cylinder", "radius": 4.5, "height": 3}]},
            {"id": "b", "name": "B", "placement": {"translation": ["shared.pitch", 0, 0]},
             "features": [{"id": "blank", "type": "cylinder", "radius": 4.5, "height": 3}]}],
            relationships=[{"id": "pitch", "type": "distance", "component_a": "a", "component_b": "b", "distance": "shared.pitch"}])
        builder = Builder(spec)
        report = verify_assembly(builder, builder.build())
        self.assertEqual(report["relationships"][0]["distance_mm"], 12)
        self.assertEqual(report["unused_parameters"], [])
        spec.components[1].placement.translation = (14, 0, 0)
        builder = Builder(spec)
        with self.assertRaisesRegex(ValueError, "expected 12.000 mm anchor distance"):
            verify_assembly(builder, builder.build())

    def test_feedback_includes_all_failed_contacts_in_one_repair(self):
        spec = reference()
        spec.components[3].placement.translation = (-25, -15, 20)
        spec.components[4].placement.translation = (25, -15, 20)
        builder = Builder(spec)
        with self.assertRaises(ValueError) as failure:
            verify_assembly(builder, builder.build())
        self.assertIn("body_left_joystick", str(failure.exception))
        self.assertIn("body_right_joystick", str(failure.exception))
        self.assertIn("world bounds", str(failure.exception))

    def test_inline_elliptical_loft_uses_plane_normal_and_retains_parametric_stations(self):
        spec = Design(name="Grip", components=[{"id": "grip", "name": "Grip",
                      "parameters": {"length": 40, "width": 20, "thickness": 12},
                      "features": [{"id": "loft", "type": "loft", "plane": "XZ",
                                    "sections": [{"station": 0, "width": "width", "height": "thickness"},
                                                 {"station": "length", "width": "width / 2", "height": "thickness / 2"}]}]}])
        part = Builder(spec).build()[0]
        self.assertAlmostEqual(part.validation["local_dimensions_mm"][1], 40)
        self.assertAlmostEqual(part.validation["bounds_mm"][0][1], -40)
        self.assertTrue(part.shape.isValid())
        encoded = spec.model_dump(mode="json")
        self.assertEqual(encoded["components"][0]["features"][0]["sections"][1]["station"], "length")

    def test_coplanar_loft_reports_the_correct_separation_axis(self):
        spec = reference()
        for feature in spec.components[1].features:
            if feature.type == "sketch":
                feature.origin = (0, 0, feature.origin[2])
        with self.assertRaisesRegex(ValueError, "Separate their sketch origins along Y"):
            Builder(spec).component("left_grip")

    def test_controller_geometry_matches_explicit_dimensions_and_button_pitch(self):
        builder = Builder(reference())
        parts = builder.build()
        report = verify_assembly(builder, parts)
        self.assertEqual(len(parts), 10)
        self.assertEqual(len(report["relationships"]), 9)
        self.assertEqual(parts[0].validation["local_dimensions_mm"], [140.0, 70.0, 20.0])
        buttons = parts[-4:]
        centres = [(part.validation["bounds_mm"][0][0] + part.validation["bounds_mm"][1][0]) / 2
                   for part in buttons]
        self.assertAlmostEqual(centres[1] - centres[0], 12 / math.sqrt(2))
        self.assertAlmostEqual(buttons[0].shape.distance(buttons[1].shape), 3, places=5)
        self.assertTrue(report["passed"])
        self.assertEqual(report["unused_parameters"], [])

    def test_large_design_is_split_into_complete_verified_batches(self):
        events = []
        with patch.object(design_planner, "load_settings", return_value=SETTINGS), \
             patch.object(design_planner, "generate_json", side_effect=replies(reference())) as model:
            plan, metadata = design_planner.interpret("Create the gaming controller as ten separate parts", progress=events.append)
        self.assertEqual(model.call_count, 6)
        self.assertEqual(metadata["requests"], 6)
        self.assertEqual(metadata["repairs"], 0)
        self.assertEqual(len(plan.design.components), 10)
        self.assertEqual(events[-1]["components_completed"], 10)
        self.assertEqual(events[-1]["components_total"], 10)
        batch_context = json.loads(model.call_args_list[3].args[1])
        self.assertIn("body", batch_context["built_component_measurements"])
        self.assertNotIn("request", batch_context)
        self.assertEqual(batch_context["component_ids"], [part.id for part in reference().components[1:4]])

    def test_unknown_placement_feature_receives_specific_schema_feedback_and_repair(self):
        spec = Design(name="Test", components=[{"id": "body", "name": "Body",
                      "features": [{"id": "blank", "type": "box", "size": [20, 20, 4]}]}])
        invalid = batch(spec.components).model_dump(mode="json")
        invalid["components"][0]["features"].append({"id": "move", "type": "placement", "translation": [0, 0, 0]})
        events = []
        with patch.object(design_planner, "load_settings", return_value=SETTINGS), \
             patch.object(design_planner, "generate_json", side_effect=[response(outline(spec)), response(invalid), response(batch(spec.components))]) as model:
            plan, metadata = design_planner.interpret("Create a small body", progress=events.append)
        repair = model.call_args_list[2]
        self.assertIn("Input tag 'placement'", json.loads(repair.args[1])["validation_errors"])
        self.assertIn("REPAIR REQUIRED", repair.args[0])
        self.assertEqual(metadata["repairs"], 1)
        self.assertEqual(plan.design, spec)
        self.assertTrue(any(event["stage"] == "repairing" for event in events))

    def test_bad_contact_is_repaired_using_actual_geometry_without_changing_sizes(self):
        spec = reference()
        spec.components = spec.components[:1] + spec.components[3:4]
        spec.relationships = [spec.relationships[2]]
        spec.parameters = {}
        spec.components[1].placement.translation = (-25, -15, 20)
        repair = EditPlan(status="ready", description="Rest the joystick on the body's top",
                          changes=[{"type": "set_placement", "component_id": "left_joystick",
                                    "placement": {"translation": ["x_offset", "y_offset", "body.thickness / 2"]}}])
        with patch.object(design_planner, "load_settings", return_value=SETTINGS), \
             patch.object(design_planner, "generate_json", side_effect=replies(spec) + [response(repair)]) as model:
            plan, metadata = design_planner.interpret("Make a body and attached joystick")
        feedback = json.loads(model.call_args.args[1])
        self.assertIn("10.000 mm separation", feedback["validation_errors"])
        self.assertIn("world_bounds_mm", feedback["component_measurements"]["body"])
        self.assertEqual(plan.design.components[1].parameters, spec.components[1].parameters)
        self.assertEqual(plan.design.components[0], spec.components[0])
        self.assertEqual(metadata["repairs"], 1)

    def test_selected_edit_repairs_scope_violation_without_mutating_original(self):
        spec = reference()
        original = {"design": spec.model_dump(mode="json"), "assumptions": []}
        before = copy.deepcopy(original)
        bad = EditPlan(status="ready", description="Wrong target", changes=[{"type": "set_parameters", "component_id": "body", "values": {"thickness": 25}}])
        good = EditPlan(status="ready", description="Taller button", changes=[{"type": "set_parameters", "component_id": "green_button", "values": {"height": 4}}])
        with patch.object(design_planner, "load_settings", return_value=SETTINGS), \
             patch.object(design_planner, "generate_json", side_effect=[response(bad), response(good)]) as model:
            plan, metadata = design_planner.interpret("Make this button 4 mm tall", original, "green_button")
        self.assertIn("limited to the selected part", json.loads(model.call_args.args[1])["validation_errors"])
        self.assertEqual(plan, good)
        self.assertEqual(metadata["repairs"], 1)
        self.assertEqual(original, before)

    def test_quota_is_not_retried_or_routed_to_another_provider(self):
        with patch.object(design_planner, "load_settings", return_value=SETTINGS), \
             patch.object(design_planner, "generate_json", side_effect=LLMError("Free quota reached", "quota")) as model:
            with self.assertRaisesRegex(LLMError, "Free quota reached"):
                design_planner.interpret("Create the controller")
        model.assert_called_once()

    def test_repeated_invalid_responses_stop_at_the_stage_budget(self):
        invalid = response({"status": "ready", "assembly": {"name": "Invalid", "components": []}})
        with patch.object(design_planner, "load_settings", return_value=SETTINGS), \
             patch.object(design_planner, "generate_json", return_value=invalid) as model:
            with self.assertRaisesRegex(LLMError, "after 3 attempts in planning"):
                design_planner.interpret("Create the controller")
        self.assertEqual(model.call_count, 3)

    def test_dependency_cycles_are_rejected_before_construction(self):
        data = outline(reference()).model_dump(mode="json")
        data["assembly"]["components"][0]["depends_on"] = ["left_grip"]
        with self.assertRaisesRegex(ValidationError, "cycle"):
            AssemblyPlan.model_validate(data)


class DesignJobApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        directory = Path(self.temporary.name)
        self.patches = [patch.object(projects, "PROJECTS_DIR", directory / "projects"),
                        patch.object(design_jobs, "GENERATION_JOBS_DIR", directory / "jobs"),
                        patch.object(design_jobs, "jobs", {}),
                        patch.object(design_jobs, "load_settings", return_value=SETTINGS)]
        for item in self.patches:
            item.start()
        self.client = TestClient(app)
        self.futures = []
        self.submit = design_jobs.executor.submit

    def tearDown(self):
        for future in self.futures:
            future.result(timeout=20)
        self.client.close()
        for item in reversed(self.patches):
            item.stop()
        self.temporary.cleanup()

    def track_submit(self, *args):
        future = self.submit(*args)
        self.futures.append(future)
        return future

    def test_background_job_returns_202_and_commits_only_verified_outputs(self):
        spec = Design(name="Test", components=[{"id": "body", "name": "Body", "features": [{"id": "blank", "type": "box", "size": [20, 20, 4]}]}])
        plan = DesignPlan(status="ready", description="Created body", design=spec)

        def interpret(*args, **kwargs):
            kwargs["progress"]({"stage": "components", "message": "Building body", "components_completed": 1, "components_total": 1})
            kwargs["trace"]({"stage": "components", "response": plan.model_dump_json()})
            return plan, {"provider": "custom", "model": "test", "seconds": 0, "requests": 1, "repairs": 0}

        with patch.object(design_planner, "interpret", side_effect=interpret), \
             patch.object(design_jobs.executor, "submit", side_effect=self.track_submit):
            start = self.client.post("/api/design-jobs", json={"prompt": "Create a small body"})
            self.assertEqual(start.status_code, 202)
            self.futures[-1].result(timeout=20)
        job = self.client.get(f"/api/design-jobs/{start.json()['job_id']}").json()
        self.assertEqual(job["status"], "completed")
        self.assertNotIn("started", job)
        self.assertTrue(job["result"]["project"]["validation"]["step_roundtrip"]["passed"])
        trace = self.client.get(job["diagnostics_url"])
        self.assertEqual(trace.status_code, 200)
        self.assertEqual(len(trace.json()["attempts"]), 1)
        self.assertNotIn("test-secret", trace.text)

    def test_failed_edit_keeps_the_accepted_revision_and_reports_quota(self):
        initial = self.client.post("/api/projects/from-spec", json=reference().model_dump(mode="json")).json()
        with patch.object(design_planner, "interpret", side_effect=LLMError("Free quota reached", "quota")), \
             patch.object(design_jobs.executor, "submit", side_effect=self.track_submit):
            start = self.client.post("/api/design-jobs", json={"prompt": "Change the green button", "project_id": initial["project_id"], "base_revision_id": initial["revision_id"], "selected_component_id": "green_button"})
            self.assertEqual(start.status_code, 202)
            self.futures[-1].result(timeout=20)
        job = self.client.get(f"/api/design-jobs/{start.json()['job_id']}").json()
        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["error"]["http_status"], 429)
        current = self.client.get(f"/api/projects/{initial['project_id']}").json()
        self.assertEqual(current["revision_id"], initial["revision_id"])

    def test_duplicate_job_and_incomplete_edit_are_rejected(self):
        with patch.object(design_jobs.executor, "submit") as submit:
            first = self.client.post("/api/design-jobs", json={"prompt": "Create a small body"})
            second = self.client.post("/api/design-jobs", json={"prompt": "Create another body"})
            self.assertEqual(first.status_code, 202)
            self.assertEqual(second.status_code, 409)
            submit.assert_called_once()
        invalid = self.client.post("/api/design-jobs", json={"prompt": "Edit this part", "selected_component_id": "body"})
        self.assertEqual(invalid.status_code, 422)


if __name__ == "__main__":
    unittest.main()

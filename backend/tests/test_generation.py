import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.llm_client import LLMError, LLMResponse, LLMSettings
from backend.app.main import app
from backend.app.service import CadBuildError

ROOT = Path(__file__).resolve().parents[2]
SETTINGS = LLMSettings("test-model", "https://models.example.test/v1", "test-secret-not-for-browser")


def plate_plan(**changes):
    values = {"status": "ready", "description": "Mounting plate", "length": 100,
              "width": 60, "thickness": 5, "hole_diameter": 4,
              "hole_centres": [{"x": x, "y": y} for x, y in [(-40, -20), (-40, 20), (40, -20), (40, 20)]],
              "questions": [], "assumptions": []}
    values.update(changes)
    return values


class GenerationApiTests(unittest.TestCase):
    def setUp(self):
        test_root = ROOT / "tmp" / "generation-tests"
        test_root.mkdir(parents=True, exist_ok=True)
        self.folder = tempfile.TemporaryDirectory(dir=test_root)
        self.storage = patch("backend.app.service.RUNS_DIR", Path(self.folder.name))
        self.storage.start()
        self.settings = patch("backend.app.planner.load_settings", return_value=SETTINGS)
        self.settings.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.settings.stop()
        self.storage.stop()
        self.folder.cleanup()

    def generate(self, values):
        text = values if isinstance(values, str) else json.dumps(values)
        reply = LLMResponse(text, 0.1, 10, 20)
        with patch("backend.app.planner.generate_json", return_value=reply) as provider:
            response = self.client.post("/api/generations", json={"prompt": "Create the specified mounting plate."})
            provider.assert_called_once()
        return response

    def test_one_create_builds_verified_cad_and_serves_both_exports(self):
        response = self.generate(plate_plan())
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result["plan"]["interpretation"]["status"], "ready")
        self.assertEqual(result["plan"]["provider"], "custom")
        model = result["model"]
        report = model["validation"]
        self.assertTrue(report["passed"])
        self.assertTrue(report["step_roundtrip"]["passed"])
        self.assertEqual(report["dimensions_mm"], [100, 60, 5])
        self.assertEqual(sorted(hole["centre_xy_mm"] for hole in report["measured_holes"]),
                         [[-40, -20], [-40, 20], [40, -20], [40, 20]])
        self.assertAlmostEqual(report["volume_mm3"], 100 * 60 * 5 - 4 * math.pi * 2 ** 2 * 5, places=5)
        step = self.client.get(model["downloads"]["step"])
        stl = self.client.get(model["downloads"]["stl"])
        self.assertEqual(step.status_code, 200)
        self.assertIn(b"ISO-10303-21", step.content)
        self.assertEqual(stl.status_code, 200)
        self.assertGreater(len(stl.content), 84)
        self.assertNotIn(SETTINGS.api_key, response.text)

    def test_missing_details_and_unsupported_features_stop_before_cad(self):
        for values in [plate_plan(status="needs_input", thickness=None, questions=["How thick should the plate be?"]),
                       plate_plan(status="unsupported", description="Gear teeth are not supported.")]:
            with self.subTest(status=values["status"]), patch("backend.app.service.create_model") as construct:
                response = self.generate(values)
                self.assertEqual(response.status_code, 200)
                self.assertIsNone(response.json()["model"])
                self.assertIsNone(response.json()["plan"]["specification"])
                construct.assert_not_called()
                self.assertEqual(list(Path(self.folder.name).iterdir()), [])

    def test_invalid_json_or_geometry_is_rejected_before_construction(self):
        for values in ["not a JSON object", plate_plan(hole_centres=[{"x": 100, "y": 0}])]:
            with self.subTest(values=values), patch("backend.app.service.create_model") as construct:
                response = self.generate(values)
                self.assertEqual(response.status_code, 422)
                construct.assert_not_called()
                self.assertEqual(list(Path(self.folder.name).iterdir()), [])

    def test_quota_or_timeout_does_not_retry_or_change_existing_files(self):
        previous = Path(self.folder.name) / "previous.step"
        previous.write_text("previous CAD export", encoding="utf-8")
        for code, status in [("quota", 429), ("timeout", 504)]:
            with self.subTest(code=code), \
                    patch("backend.app.planner.generate_json", side_effect=LLMError("Provider unavailable.", code)) as provider, \
                    patch("backend.app.service.create_model") as construct:
                response = self.client.post("/api/generations", json={"prompt": "Create a mounting plate."})
                self.assertEqual(response.status_code, status)
                provider.assert_called_once()
                construct.assert_not_called()
                self.assertEqual(previous.read_text(encoding="utf-8"), "previous CAD export")
                self.assertEqual(list(Path(self.folder.name).iterdir()), [previous])

    def test_failed_cad_verification_is_not_returned_as_a_success(self):
        with patch("backend.app.service.create_model", side_effect=CadBuildError("The STEP export failed geometry checks after re-import.")):
            response = self.generate(plate_plan())
        self.assertEqual(response.status_code, 422)
        self.assertIn("STEP export failed", response.json()["detail"])
        self.assertNotIn("downloads", response.json())

    def test_empty_idea_does_not_call_provider(self):
        with patch("backend.app.planner.generate_json") as provider:
            response = self.client.post("/api/generations", json={"prompt": "       "})
        self.assertEqual(response.status_code, 422)
        provider.assert_not_called()


if __name__ == "__main__":
    unittest.main()

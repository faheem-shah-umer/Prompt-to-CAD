import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.main import app

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class CadApiTests(unittest.TestCase):
    def setUp(self):
        test_root = PROJECT_ROOT / "tmp" / "api-tests"
        test_root.mkdir(parents=True, exist_ok=True)
        self.folder = tempfile.TemporaryDirectory(dir=test_root)
        self.assertTrue(Path(self.folder.name).resolve().is_relative_to(test_root.resolve()))
        self.storage = patch("backend.app.service.RUNS_DIR", Path(self.folder.name))
        self.storage.start()
        self.client = TestClient(app)
        self.spec = json.loads((Path(__file__).parent / "fixtures" / "plate.json").read_text(encoding="utf-8"))

    def tearDown(self):
        self.client.close()
        self.storage.stop()
        self.folder.cleanup()

    def test_build_and_export_preserve_geometry(self):
        response = self.client.post("/api/models", json=self.spec)
        self.assertEqual(response.status_code, 201, response.text)
        result = response.json()
        self.assertTrue(result["validation"]["passed"])
        self.assertTrue(result["validation"]["step_roundtrip"]["passed"])
        self.assertEqual(result["validation"]["dimensions_mm"], [80, 50, 6])
        self.assertEqual(len(result["validation"]["measured_holes"]), 4)
        self.assertAlmostEqual(result["validation"]["volume_mm3"], 23321.4159868246, places=5)
        step = self.client.get(result["downloads"]["step"])
        self.assertEqual(step.status_code, 200)
        self.assertIn(b"ISO-10303-21", step.content)
        stl = self.client.get(result["downloads"]["stl"])
        self.assertEqual(stl.status_code, 200)
        self.assertGreater(len(stl.content), 84)
        saved = self.client.get(f"/api/models/{result['model_id']}").json()
        self.assertEqual(saved["specification"], result["specification"])

    def test_invalid_holes_are_rejected_before_construction(self):
        self.spec["hole_centres"] = [[40, 0]]
        response = self.client.post("/api/models", json=self.spec)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(list(Path(self.folder.name).iterdir()), [])

    def test_missing_models_and_unknown_file_types(self):
        path = "/api/models/00000000-0000-0000-0000-000000000001"
        self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.client.get(f"{path}/files/stl").status_code, 404)
        self.assertEqual(self.client.get(f"{path}/files/secrets").status_code, 422)

    def test_docs_and_frontend_preflight(self):
        self.assertEqual(self.client.get("/docs").status_code, 200)
        schema = self.client.get("/openapi.json").json()
        self.assertIn("/api/models", schema["paths"])
        response = self.client.options("/api/models", headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], "http://127.0.0.1:5173")


if __name__ == "__main__":
    unittest.main()

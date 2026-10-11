import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from backend.app.llm_client import LLMError, LLMResponse, LLMSettings, generate_json, load_settings, public_status
from backend.app.main import app

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEST_SETTINGS = LLMSettings("test-model", "https://models.example.test/custom/v1",
                            "test-secret-not-for-browser", json_mode=True)


def interpretation(**changes):
    result = {"status": "ready", "description": "Plain plate", "length": 101.6,
              "width": 50.8, "thickness": 6.35, "hole_diameter": None,
              "hole_centres": [], "questions": [], "assumptions": []}
    result.update(changes)
    return result


class PlanningApiTests(unittest.TestCase):
    def setUp(self):
        test_root = PROJECT_ROOT / "tmp" / "planning-tests"
        test_root.mkdir(parents=True, exist_ok=True)
        self.folder = tempfile.TemporaryDirectory(dir=test_root)
        self.assertTrue(Path(self.folder.name).resolve().is_relative_to(test_root.resolve()))
        self.storage = patch("backend.app.service.RUNS_DIR", Path(self.folder.name))
        self.storage.start()
        self.settings = patch("backend.app.planner.load_settings", return_value=TEST_SETTINGS)
        self.settings.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.settings.stop()
        self.storage.stop()
        self.folder.cleanup()

    def plan(self, values):
        response = LLMResponse(json.dumps(values), 0.1, 10, 20)
        with patch("backend.app.planner.generate_json", return_value=response) as mock:
            result = self.client.post("/api/plans", json={"prompt": "Make a plate with the specified dimensions."})
            mock.assert_called_once()
        return result

    def test_plan_is_reviewable_before_real_cad_construction(self):
        response = self.plan(interpretation())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(list(Path(self.folder.name).iterdir()), [])
        spec = response.json()["specification"]
        self.assertEqual([spec["length"], spec["width"], spec["thickness"]], [101.6, 50.8, 6.35])
        built = self.client.post("/api/models", json=spec)
        self.assertEqual(built.status_code, 201, built.text)
        report = built.json()["validation"]
        self.assertTrue(report["passed"])
        self.assertTrue(report["step_roundtrip"]["passed"])
        self.assertEqual(report["measured_holes"], [])
        self.assertAlmostEqual(report["volume_mm3"], 101.6 * 50.8 * 6.35, places=5)

    def test_clarification_and_unsupported_features_produce_no_spec_or_files(self):
        for values in [interpretation(status="needs_input", thickness=None, questions=["What thickness in mm?"]),
                       interpretation(status="unsupported", description="Gear teeth are unsupported.")]:
            with self.subTest(status=values["status"]):
                response = self.plan(values)
                self.assertEqual(response.status_code, 200)
                self.assertIsNone(response.json()["specification"])
                self.assertEqual(list(Path(self.folder.name).iterdir()), [])

    def test_invalid_ready_plan_never_reaches_cad(self):
        for values in [interpretation(thickness=None),
                       interpretation(hole_diameter=6, hole_centres=[{"x": 100, "y": 0}])]:
            with self.subTest(values=values):
                response = self.plan(values)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(list(Path(self.folder.name).iterdir()), [])

    def test_quota_and_empty_prompts_do_not_trigger_another_provider(self):
        with patch("backend.app.planner.generate_json", side_effect=LLMError("Free quota reached.", "quota")) as mock:
            response = self.client.post("/api/plans", json={"prompt": "Build a plate."})
            self.assertEqual(response.status_code, 429)
            mock.assert_called_once()
        with patch("backend.app.planner.generate_json") as mock:
            self.assertEqual(self.client.post("/api/plans", json={"prompt": "       "}).status_code, 422)
            mock.assert_not_called()

    def test_public_model_status_excludes_credentials(self):
        with patch("backend.app.llm_client.load_settings", return_value=TEST_SETTINGS):
            response = self.client.get("/api/llm")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["configured"])
        self.assertNotIn(TEST_SETTINGS.api_key, response.text)
        self.assertNotIn("api_key", response.text)
        self.assertNotIn(TEST_SETTINGS.base_url, response.text)


class ProviderTransportTests(unittest.TestCase):
    def test_invalid_configuration_is_rejected_before_a_request(self):
        for changes in ({"model": ""}, {"base_url": ""}, {"timeout": float("nan")},
                        {"base_url": "https://user:password@example.test/v1"},
                        {"base_url": "https://example.test/v1?key=secret"}):
            with self.subTest(changes=changes), patch("backend.app.llm_client.httpx.Client") as client:
                with self.assertRaises(LLMError) as result:
                    generate_json("system", "prompt", replace(TEST_SETTINGS, **changes))
                self.assertEqual(result.exception.code, "configuration")
                client.assert_not_called()

    def test_custom_endpoint_and_header_auth_keep_the_key_out_of_the_url(self):
        observed = []

        def handler(request):
            observed.append(request)
            return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(interpretation())}}]})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        with patch("backend.app.llm_client.httpx.Client", return_value=client):
            response = generate_json("system", "prompt", TEST_SETTINGS)
        self.assertEqual(len(observed), 1)
        request = observed[0]
        self.assertNotIn(TEST_SETTINGS.api_key, str(request.url))
        self.assertEqual(str(request.url), f"{TEST_SETTINGS.base_url}/chat/completions")
        self.assertEqual(request.headers["Authorization"], f"Bearer {TEST_SETTINGS.api_key}")
        body = json.loads(request.content)
        self.assertEqual(body["model"], TEST_SETTINGS.model)
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertEqual(json.loads(response.text)["status"], "ready")

    def test_fenced_json_is_parsed_without_an_additional_provider_request(self):
        client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
            200, json={"choices": [{"finish_reason": "stop", "message": {"content": '```json\n{"ok": true}\n```'}}]})))
        with patch("backend.app.llm_client.httpx.Client", return_value=client):
            result = generate_json("system", "prompt", TEST_SETTINGS)
        self.assertEqual(json.loads(result.text), {"ok": True})

    def test_repair_history_reaches_the_same_endpoint_as_conversation_turns(self):
        observed = []

        def handler(request):
            observed.append(json.loads(request.content))
            return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        history = [{"role": "user", "content": "Original design"}, {"role": "assistant", "content": "Rejected plan"}]
        with patch("backend.app.llm_client.httpx.Client", return_value=client):
            generate_json("CAD schema", "Fix the placement", TEST_SETTINGS, history=history, temperature=0.15)
        self.assertEqual([item["role"] for item in observed[0]["messages"]], ["system", "user", "assistant", "user"])
        self.assertEqual(observed[0]["messages"][2]["content"], "Rejected plan")
        self.assertEqual(observed[0]["model"], TEST_SETTINGS.model)
        self.assertEqual(observed[0]["temperature"], 0.15)

    def test_local_server_needs_no_key_or_json_mode(self):
        observed = []

        def handler(request):
            observed.append(request)
            return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]})

        settings = LLMSettings("local-model", "http://localhost:11434/v1/")
        client = httpx.Client(transport=httpx.MockTransport(handler))
        with patch("backend.app.llm_client.httpx.Client", return_value=client):
            generate_json("system", "prompt", settings)
        self.assertEqual(str(observed[0].url), "http://localhost:11434/v1/chat/completions")
        self.assertNotIn("Authorization", observed[0].headers)
        self.assertNotIn("response_format", json.loads(observed[0].content))

    def test_fresh_clone_has_no_default_connection(self):
        with patch.dict(os.environ, {}, clear=True), patch("backend.app.llm_client.load_dotenv"):
            status = public_status()
            self.assertFalse(status["configured"])
            self.assertEqual(status["model"], "")

    def test_environment_settings_and_invalid_timeout(self):
        env = {"LLM_BASE_URL": "https://models.example.test/v1/", "LLM_MODEL": "my-model",
               "LLM_TIMEOUT_SECONDS": "120", "LLM_JSON_MODE": "true", "LLM_API_KEY": "private"}
        with patch.dict(os.environ, env, clear=True), patch("backend.app.llm_client.load_dotenv"):
            settings = load_settings()
            settings.check()
            self.assertEqual(settings.timeout, 120)
            self.assertTrue(settings.json_mode)
            self.assertEqual(settings.base_url, env["LLM_BASE_URL"].rstrip("/"))
            self.assertNotIn("private", repr(settings))
            os.environ["LLM_TIMEOUT_SECONDS"] = "invalid"
            self.assertFalse(public_status()["configured"])

    def test_rate_limit_returns_once_with_no_hidden_retries(self):
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(429, json={"error": "quota"})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        with patch("backend.app.llm_client.httpx.Client", return_value=client):
            with self.assertRaises(LLMError) as result:
                generate_json("system", "prompt", TEST_SETTINGS)
        self.assertEqual(result.exception.code, "quota")
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()

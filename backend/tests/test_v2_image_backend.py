import hashlib
import json
import tempfile
import os
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
import trimesh
from PIL import Image

from backend.native.contracts import WorkspaceError
from backend.v2.image_backend import Tripo
from backend.v2.workspace import WorkspaceV2
from backend.v2.cad_tools import TaskTools

ROOT = Path(__file__).resolve().parents[2]


class ImageBackendTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT / "tmp")
        self.folder = Path(self.temporary.name)
        self.path = self.folder / "reference.png"
        Image.new("RGB", (256, 256), "white").save(self.path)
        self.reference = {
            "path": str(self.path),
            "sha256": hashlib.sha256(self.path.read_bytes()).hexdigest(),
            "asset_id": "fixture",
            "name": "reference.png",
        }

    def tearDown(self):
        self.temporary.cleanup()

    def test_documented_v3_upload_task_download_contract_with_fixture_transport(self):
        payload = trimesh.Scene(trimesh.creation.box()).export(file_type="glb")
        calls = []

        def handler(request):
            calls.append(request)
            if request.url.path == "/v3/files":
                self.assertIn(b'name="file"', request.content)
                return httpx.Response(200, json={"code": 0, "data": {"file_token": "file_fixture"}})
            if request.url.path == "/v3/generation/image-to-model":
                body = json.loads(request.content)
                self.assertEqual(body["input"], "file_fixture")
                self.assertEqual(body["face_limit"], 20000)
                return httpx.Response(200, json={"code": 0, "data": {"task_id": "task_fixture"}})
            if request.url.path == "/v3/tasks/task_fixture":
                return httpx.Response(
                    200,
                    json={
                        "code": 0,
                        "data": {
                            "status": "success",
                            "progress": 100,
                            "credits_consumed": 30,
                            "output": {"model_url": "https://cdn.tripo3d.ai/model.glb?signature=fixture"},
                        },
                    },
                )
            self.assertNotIn("authorization", request.headers)
            return httpx.Response(200, content=payload)

        with (
            httpx.Client(transport=httpx.MockTransport(handler)) as client,
            patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("8.8.8.8", 443))]),
        ):
            result = Tripo("fixture-key", threading.Event(), client=client).generate(
                self.reference, 100, self.folder / "model.glb", self.folder / "task.json"
            )
        self.assertEqual(result["status"], "downloaded")
        self.assertEqual(result["credits_consumed"], 30)
        self.assertEqual(len(calls), 4)
        record = (self.folder / "task.json").read_text()
        self.assertNotIn("fixture-key", record)
        self.assertNotIn("signature=", record)
        self.assertEqual((self.folder / "model.glb").read_bytes(), payload)

    @unittest.skipUnless(os.name == "nt", "The application billing gate uses Windows DPAPI")
    def test_cancellation_before_submission_and_billing_gate_make_no_paid_request(self):
        cancelled = threading.Event()
        cancelled.set()
        client = httpx.Client(transport=httpx.MockTransport(lambda r: self.fail("No request should be sent")))
        try:
            with self.assertRaises(WorkspaceError):
                Tripo("fixture-key", cancelled, client=client).generate(
                    self.reference, 100, self.folder / "out.glb", self.folder / "task.json"
                )
        finally:
            client.close()
        workspace = WorkspaceV2(self.folder / "workspace")
        try:
            state = workspace.dispatch("v2.project.create", {"name": "Billing gate"})
            with self.assertRaises(WorkspaceError):
                workspace.dispatch(
                    "v2.image_generate", {"base_revision_id": None, "reference": self.reference, "target_size_mm": 100}
                )
            tools = TaskTools(
                workspace, workspace.document, state["document"], None, workspace.project_id, "billing-test"
            )
            with patch.object(workspace, "reconstruct_image") as generate:
                with self.assertRaises(WorkspaceError) as denied:
                    tools.call(
                        "cad_image_generate",
                        {"candidate_id": tools.candidate_id, "reference_asset_id": "fixture", "target_size_mm": 100},
                    )
                self.assertEqual(denied.exception.code, "image_billing_not_authorized")
                generate.assert_not_called()
        finally:
            workspace.worker.close()


if __name__ == "__main__":
    unittest.main()

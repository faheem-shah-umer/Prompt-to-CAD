"""Detect stale instructions, registries and code before CAD execution."""

import copy
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.native.contracts import WorkspaceError
from backend.native.runtime_identity import ROOT, RuntimeIdentity


class RuntimeIdentityTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "tmp").mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT / "tmp")
        self.root = Path(self.temporary.name)
        (self.root / "backend/v2").mkdir(parents=True)
        self.instructions = "Use cq_warehouse through cad_standard_part."
        (self.root / "backend/v2/CAD_INSTRUCTIONS.md").write_text(self.instructions, encoding="utf-8")
        self.tools = [{"name": "cad_standard_parts"}, {"name": "cad_standard_part"}]
        self.environment = patch.dict(os.environ, {key: "" for key in ("PROMPTCAD_WORKSPACE", "PROMPTCAD_EXPECTED_SOURCE", "PROMPTCAD_EXPECTED_TOOLS")})
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temporary.cleanup()

    def runtime(self, **values):
        return RuntimeIdentity("backend", root=self.root, tools=values.get("tools", self.tools), instructions=values.get("instructions", self.instructions))

    def test_source_change_requires_restart(self):
        runtime = self.runtime()
        (self.root / "backend/new_module.py").write_text("value = 1\n", encoding="utf-8")
        with self.assertRaises(WorkspaceError) as stale:
            runtime.ensure_current()
        self.assertEqual(stale.exception.code, "runtime_mismatch")

    def test_old_in_memory_instructions_are_rejected_even_with_current_disk_files(self):
        with self.assertRaises(WorkspaceError):
            self.runtime(instructions="Old CAD instructions without the library.")

    def test_old_or_mutated_registry_is_rejected(self):
        with self.assertRaises(WorkspaceError):
            self.runtime(tools=[{"name": "cad_script"}])
        runtime = self.runtime()
        self.tools.append({"name": "new_tool"})
        with self.assertRaises(WorkspaceError):
            runtime.ensure_current()

    def test_parent_child_code_and_registry_must_match(self):
        runtime = self.runtime()
        peer = {**runtime.report(), "role": "mcp"}
        runtime.verify_peer(peer, "mcp")
        for field in ("source_sha256", "instructions_sha256", "tools_sha256"):
            with self.subTest(field=field):
                changed = copy.deepcopy(peer)
                changed[field] = "different"
                with self.assertRaises(WorkspaceError):
                    runtime.verify_peer(changed, "mcp")

    def test_wrong_source_root_or_parent_fingerprint_is_rejected(self):
        for key, value in (("PROMPTCAD_WORKSPACE", str(self.root / "other")), ("PROMPTCAD_EXPECTED_SOURCE", "old"), ("PROMPTCAD_EXPECTED_TOOLS", "old")):
            with self.subTest(key=key), patch.dict(os.environ, {key: value}), self.assertRaises(WorkspaceError):
                self.runtime()

    def test_actual_mcp_catalog_advertises_both_standard_part_tools(self):
        from backend.v2.mcp_server import serve

        output = io.StringIO()
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ]
        with patch.dict(os.environ, {"PROMPTCAD_TOOL_URL": ""}):
            serve(io.StringIO("\n".join(json.dumps(r) for r in requests)), output)
        responses = [json.loads(line) for line in output.getvalue().splitlines()]
        names = {t["name"] for t in responses[-1]["result"]["tools"]}
        self.assertTrue({"cad_standard_parts", "cad_standard_part"} <= names)


if __name__ == "__main__":
    unittest.main()

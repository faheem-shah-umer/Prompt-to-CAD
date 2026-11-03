"""Synthetic catalog search, geometry insertion and per-turn evidence."""

import copy
from contextlib import closing
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import time
import unittest
from unittest.mock import patch

import cadquery as cq

from backend.native import geometry
from backend.native.contracts import WorkspaceError
from backend.native.documents import Document
from backend.native.runtime_identity import RuntimeIdentity
from backend.native.workspace import Workspace
from backend.v2.cad_tools import TOOLS, TaskTools, ToolBridge
from backend.v2.mcp_server import serve
from backend.v2.step_catalog import FIELDS, ROOT, StepCatalog, digest
from backend.v2.turn_logs import TurnLog, safe


class StepCatalogTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "tmp").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.directory = self.root / ".local" / "freecad-step-catalog"
        self.parts = self.directory / "parts"
        self.parts.mkdir(parents=True)
        self.db = self.directory / "catalog.sqlite3"
        self.asset = self.parts / "mount.STP"
        self.asset.write_bytes(b"synthetic")
        columns = ", ".join(field + (" INTEGER" if field in ("bytes", "step_signature_ok") else " TEXT")
                            for field in FIELDS if field != "id")
        self.update(f"""PRAGMA user_version = 1;
            CREATE TABLE parts (id INTEGER PRIMARY KEY, {columns}, asset_path TEXT);
            CREATE VIRTUAL TABLE part_search USING fts5(name, category, subcategory, description_hint,
                content='parts', content_rowid='id');
            INSERT INTO parts (id, name, category, bytes, step_signature_ok, asset_path, author_hint, source_url)
            VALUES (1, 'Motor mount', 'Mechanical', 9, 1, 'parts/mount.STP', 'maker@example.test', 'https://example.test/mount'),
                   (2, 'Motor enclosure', 'Electrical', 9, 1, 'parts/mount.STP', NULL, NULL);
            INSERT INTO part_search(part_search) VALUES ('rebuild');""")
        self.update("UPDATE parts SET sha256 = ?", (digest(self.asset),))

    def update(self, sql, params=None):
        with closing(sqlite3.connect(self.db)) as db, db:
            if params is None:
                db.executescript(sql)
            else:
                db.execute(sql, params)

    def inspect(self, catalog, identity=1):
        return catalog.query({"action": "inspect", "catalog_id": identity, "fingerprint": catalog.initial["fingerprint"]})

    def test_discovery_search_and_catalog_changes(self):
        catalog = StepCatalog(self.root)
        self.assertEqual(catalog.status()["schema_version"], 1)
        self.assertEqual(len(catalog.status()["categories"]), 2)
        self.assertEqual(catalog.query({"action": "search", "query": "motor", "limit": 1})["next_offset"], 1)
        results = catalog.query({"action": "search", "query": "motor", "category": "Mechanical"})["results"]
        self.assertEqual([item["catalog_id"] for item in results], [1])
        self.assertEqual(catalog.query({"action": "search", "query": "motor OR mount"})["results"], [])
        entry = self.inspect(catalog)["entry"]
        self.assertEqual(entry["source_url"], "https://example.test/mount")
        self.assertNotIn("asset_path", entry)
        self.assertEqual(entry["author_hint"], "[email omitted]")
        for identity in (False, -1, "1", 9999):
            with self.assertRaises(WorkspaceError) as failure:
                self.inspect(catalog, identity)
            self.assertEqual(failure.exception.code, "invalid_catalog_id")
        with self.assertRaises(WorkspaceError) as failure:
            catalog.lookup(1, "0" * 64)
        self.assertEqual(failure.exception.code, "catalog_changed")
        self.update("PRAGMA user_version = 2;")
        self.assertEqual(catalog.status()["error"]["code"], "catalog_changed")
        self.assertEqual(StepCatalog(self.root).status()["error"]["code"], "catalog_incompatible")
        self.assertEqual(StepCatalog(self.root / "absent").status()["error"]["code"], "catalog_missing")

    def test_asset_containment_and_integrity(self):
        from threading import Event

        for path in ("parts/../escape.step", "parts/C:/escape.step", "/parts/mount.STP",
                     "parts/mount.stl", "parts/\\\\server\\share\\part.step"):
            self.update("UPDATE parts SET asset_path = ? WHERE id = 1", (path,))
            catalog = StepCatalog(self.root)
            self.inspect(catalog)
            with self.assertRaises(WorkspaceError) as failure, catalog.stage(1, catalog.initial["fingerprint"], Event(), None):
                self.fail("Unexpected catalog asset")
            self.assertEqual(failure.exception.code, "catalog_path")
        self.update("UPDATE parts SET asset_path = 'parts/mount.STP';")
        catalog = StepCatalog(self.root)
        self.inspect(catalog)
        original_lstat = Path.lstat

        def junction(path):
            if path == self.parts:
                return type("Reparse", (), {"st_mode": stat.S_IFDIR,
                                            "st_file_attributes": stat.FILE_ATTRIBUTE_REPARSE_POINT})()
            return original_lstat(path)

        with patch.object(Path, "lstat", junction):
            self.assertEqual(StepCatalog(self.root).status()["error"]["code"], "catalog_path")
        def link(path):
            if path == self.asset:
                return type("Link", (), {"st_mode": stat.S_IFLNK})()
            return original_lstat(path)

        with patch.object(Path, "lstat", link), self.assertRaises(WorkspaceError) as failure:
            with catalog.stage(1, catalog.initial["fingerprint"], Event(), None):
                self.fail("Unexpected linked asset")
        self.assertEqual(failure.exception.code, "catalog_path")
        self.asset.write_bytes(b"corrupted")
        with self.assertRaises(WorkspaceError) as failure, catalog.stage(1, catalog.initial["fingerprint"], Event(), None):
            self.fail("Unexpected corrupt asset")
        self.assertEqual(failure.exception.code, "catalog_asset_integrity")

    def fixture_tools(self, *, available=True):
        workspace = Workspace(self.root / "geometry")
        self.addCleanup(workspace.worker.close)
        workspace.application_runtime = RuntimeIdentity("backend", tools=TOOLS)
        doc = Document.create(self.root / "sample.cadproj", "Sample")
        group = {"id": "existing-group", "parent_id": None, "name": "Existing group", "matrix": geometry.IDENTITY}
        block = self.component(doc.folder, "block", "existing-group")
        doc.commit({"components": [block], "assembly_nodes": [group]})
        original = doc.current()
        selection = {"revision_id": original["revision_id"], "instance_id": "block", "kind": "face", "index": 1}
        tools = TaskTools(workspace, doc, original, selection, "project", "turn")
        tools._catalog = StepCatalog(self.root if available else self.root / "absent")
        return tools, doc, original

    @staticmethod
    def component(folder, identity, parent, x=0):
        shape = cq.Workplane("XY").box(4, 4, 4).val()
        pose = geometry.IDENTITY.copy()
        pose[3] = x
        return {"instance_id": identity, "definition_id": identity, "parent_id": parent,
                "name": identity, "matrix": pose, "color": [0.3, 0.4, 0.5], **geometry.store_shape(folder, shape)}

    def make_assembly(self):
        nodes = [{"id": identity, "parent_id": parent, "name": identity, "matrix": geometry.IDENTITY}
                 for identity, parent in (("outer", None), ("inner", "outer"))]
        parts = [self.component(self.root, "first", "inner"), self.component(self.root, "second", "outer", 8)]
        geometry.export_step(self.root, {"components": parts, "assembly_nodes": nodes}, self.asset)
        self.update("UPDATE parts SET bytes = ?, sha256 = ?", (self.asset.stat().st_size, digest(self.asset)))

    def test_scoped_insert_rollback_and_history(self):
        self.make_assembly()
        tools, doc, original = self.fixture_tools()
        params = {"catalog_id": 1, "fingerprint": tools.catalog.initial["fingerprint"], "candidate_id": tools.candidate_id}
        with self.assertRaises(WorkspaceError) as failure:
            tools.call("cad_catalog_insert", params)
        self.assertEqual(failure.exception.code, "catalog_inspection_required")
        self.inspect(tools.catalog)
        before_assets = set((doc.folder / "assets").iterdir())
        with self.assertRaisesRegex(WorkspaceError, "unexpected intersection"):
            tools.call("cad_catalog_insert", params)
        self.assertEqual(tools.candidate, original)
        self.assertEqual(tools.candidate_id, params["candidate_id"])
        self.assertEqual(tools.commands, [])
        self.assertEqual(set((doc.folder / "assets").iterdir()), before_assets)
        self.assertEqual(doc.current(), original)
        result = tools.call("cad_catalog_insert", {**params, "placement": {"translation": [30, 0, 0]}})
        self.assertEqual(len(result["created_component_ids"]), 2)
        self.assertEqual(tools.candidate["components"][:1], original["components"])
        self.assertEqual(tools.candidate["assembly_nodes"][:1], original["assembly_nodes"])
        self.assertGreaterEqual(len(tools.candidate["assembly_nodes"]), 4)
        self.assertEqual([part["matrix"][3] for part in tools.candidate["components"][1:]], [30, 38])
        self.assertTrue(tools.validate()["scope"]["passed"])
        doc.commit(tools.candidate, original["revision_id"], commands=tools.commands)
        committed = doc.current()
        self.db.unlink()
        self.assertEqual(Document(doc.folder).current()["components"], committed["components"])
        doc.move_history(-1, committed["revision_id"])
        self.assertEqual(doc.current()["components"], original["components"])
        doc.move_history(1, original["revision_id"])
        self.assertEqual(doc.current()["components"], committed["components"])

    def test_external_reference_rejected_before_transfer(self):
        self.make_assembly()
        reader = geometry.STEPCAFControl_Reader()
        document = geometry.TDocStd_Document(geometry.TCollection_ExtendedString("BinXCAF"))
        self.assertEqual(reader.ReadFile(str(self.asset)), geometry.IFSelect_RetDone)
        self.assertTrue(reader.Transfer(document))
        writer = geometry.STEPCAFControl_Writer()
        self.assertTrue(writer.Transfer(document, geometry.STEPControl_AsIs, "external-"))
        external = self.parts / "linked.step"
        self.assertEqual(writer.Write(str(external)), geometry.IFSelect_RetDone)
        with self.assertRaises(WorkspaceError) as failure:
            geometry.import_step(external, self.root, self_contained=True)
        self.assertEqual(failure.exception.code, "catalog_external_reference")

    def test_invalid_step_rolls_back_and_single_solid_inserts_at_root(self):
        tools, doc, original = self.fixture_tools()
        self.inspect(tools.catalog)
        params = {"catalog_id": 1, "fingerprint": tools.catalog.initial["fingerprint"], "candidate_id": tools.candidate_id,
                  "placement": {"translation": [10, 0, 0]}}
        with self.assertRaises(WorkspaceError) as failure:
            tools.call("cad_catalog_insert", params)
        self.assertEqual(failure.exception.code, "import_failed")
        self.assertEqual(tools.candidate, original)
        self.assertEqual(tools.commands, [])
        self.assertEqual(doc.current(), original)
        cq.exporters.export(cq.Workplane("XY").box(2, 2, 2), str(self.asset), exportType="STEP")
        self.update("UPDATE parts SET bytes = ?, sha256 = ?", (self.asset.stat().st_size, digest(self.asset)))
        tools._catalog = StepCatalog(self.root)
        self.inspect(tools.catalog)
        result = tools.call("cad_catalog_insert", {**params, "fingerprint": tools.catalog.initial["fingerprint"]})
        self.assertEqual(len(result["created_component_ids"]), 1)
        self.assertIsNone(tools.candidate["components"][-1]["parent_id"])
        self.assertEqual(tools.candidate["assembly_nodes"], original["assembly_nodes"])

    def new_log(self, identity):
        return TurnLog(self.root, {"task_id": identity, "started_at": time.time()}, "project")

    def test_mcp_returned_list_and_search_evidence_when_catalog_missing(self):
        tools, _, _ = self.fixture_tools(available=False)
        log = tools.turn_log = self.new_log("missing")
        log.catalog_evidence("discovery", tools.catalog.initial)
        self.assertIsNone(log.catalog_usage()["tool_list_returned"])
        bridge = ToolBridge(tools)
        with closing(bridge), patch.dict(os.environ, {
            "PROMPTCAD_TOOL_URL": bridge.url, "PROMPTCAD_TOOL_TOKEN": bridge.token,
        }):
            source = io.StringIO(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n")
            output = io.StringIO()
            serve(source, output)
        reply = json.loads(output.getvalue())
        self.assertIn("result", reply, reply)
        names = {tool["name"] for tool in reply["result"]["tools"]}
        self.assertTrue({"cad_catalog", "cad_catalog_insert"}.issubset(names))
        evidence = log.catalog_usage()
        self.assertFalse(evidence["discovery"]["available"])
        self.assertTrue(evidence["tool_list_returned"]["catalog_tools_present"])
        with self.assertRaises(WorkspaceError):
            tools.call("cad_catalog", {"action": "search", "query": "mount"})
        self.assertEqual(log.catalog_usage()["successful_search_calls"], 0)

    def test_search_results_failures_and_candidate_acceptance_are_logged(self):
        self.make_assembly()
        tools, doc, original = self.fixture_tools()
        log = tools.turn_log = self.new_log("searched")
        log.catalog_evidence("context_submitted", tools.catalog.status())
        result = tools.call("cad_catalog", {"action": "search", "query": "mount", "category": "Mechanical"})
        events = [json.loads(line) for line in (log.folder / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(events[-1]["result"], safe(result))
        self.assertEqual(log.catalog_usage()["search_calls"], 1)
        self.assertEqual(log.catalog_usage()["insertion_attempts"], 0)
        self.assertEqual(log.catalog_usage()["explanation_status"], "not_provided")
        tools.call("cad_decision", {"candidate_id": tools.candidate_id, "summary": "Inspect the mount",
                                   "cq_warehouse": {"choice": "not_applicable", "reason": "Custom mount"},
                                   "catalog": {"choice": "do_not_use", "reason": "Origin conflicts", "result_ids": [1]}})
        self.assertEqual(log.catalog_usage()["explanation_status"], "provided")
        self.inspect(tools.catalog)
        params = {"catalog_id": 1, "fingerprint": tools.catalog.initial["fingerprint"], "candidate_id": tools.candidate_id}
        with self.assertRaises(WorkspaceError):
            tools.call("cad_catalog_insert", params)
        result = tools.call("cad_catalog_insert", {**params, "placement": {"translation": [30, 0, 0]}})
        self.assertEqual([item["status"] for item in log.catalog_usage()["insertions"]], ["failed", "succeeded"])
        self.assertEqual(log.catalog_usage()["insertions"][-1]["accepted_component_ids"], [])
        cancelled = self.new_log("cancelled")
        cancelled.data["tools"] = copy.deepcopy(log.data["tools"])
        cancelled.finish({"status": "cancelled"})
        self.assertEqual(cancelled.catalog_usage()["insertions"][-1]["accepted_component_ids"], [])
        doc.commit(tools.candidate, original["revision_id"], commands=tools.commands)
        log.finish({"status": "completed", "result_revision_id": doc.current()["revision_id"],
                    "created_components": result["created_component_ids"]})
        self.assertEqual(log.catalog_usage()["insertions"][-1]["accepted_component_ids"], result["created_component_ids"])
        removed = self.new_log("removed")
        removed.data["tools"] = copy.deepcopy(log.data["tools"])
        removed.finish({"status": "completed", "result_revision_id": "later-revision",
                        "created_components": result["created_component_ids"][1:]})
        self.assertEqual(removed.catalog_usage()["insertions"][-1]["accepted_component_ids"], result["created_component_ids"][1:])

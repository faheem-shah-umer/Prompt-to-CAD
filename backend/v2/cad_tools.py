"""Provider-independent, task-scoped CAD capabilities."""

import copy
import json
import math
import shutil
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

from pydantic import TypeAdapter

from backend.native.contracts import Command, FaceOffset, FaceHoles, WorkspaceError
from backend.native.documents import asset_path
from .selection import normalize, check_command
from .step_catalog import CATALOG_TOOLS, CHOICES, StepCatalog, digest


def schema(properties=None, required=()):
    return {
        "type": "object",
        "properties": properties or {},
        "required": list(required),
        "additionalProperties": False,
    }


ENTITY = schema(
    {
        "instance_id": {"type": "string"},
        "kind": {"enum": ["body", "face", "edge", "vertex"]},
        "index": {"type": "integer", "minimum": 0},
        "asset_hash": {"type": "string"},
    },
    ["instance_id"],
)

TOKEN = {
    "type": "string",
    "description": "Exact current candidate_id returned by inspection. Changes after each successful geometry write.",
}


def inline_schema(value):
    definitions = value.get("$defs", {})

    def expand(node):
        if isinstance(node, list):
            return [expand(n) for n in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            return expand(definitions[node["$ref"].split("/")[-1]])
        return {
            k: expand(v) for k, v in node.items() if k not in ("$defs", "discriminator")
        }

    return expand(value)


TOOLS = [
    {
        "name": "cad_definition",
        "description": "Read a component’s available editable recipe or retained CAD script and named parameters. Imported solids/meshes may have no original feature history.",
        "inputSchema": schema(
            {"candidate_id": TOKEN, "instance_id": {"type": "string"}},
            ["candidate_id", "instance_id"],
        ),
    },
    {
        "name": "cad_measure",
        "description": "Measure minimum clearance and centre distance between two current entities in assembly/world mm.",
        "inputSchema": schema(
            {"candidate_id": TOKEN, "first": ENTITY, "second": ENTITY},
            ["candidate_id", "first", "second"],
        ),
    },
    {
        "name": "cad_viewport",
        "description": "Retrieve the highlighted viewport image captured at task submission. It represents the BASE revision, not later candidate geometry.",
        "inputSchema": schema(),
    },
    {
        "name": "cad_context",
        "description": "Read actual current task, document, frozen selection and candidate ID. Always call at the start of a turn.",
        "inputSchema": schema(),
    },
    {
        "name": "cad_inspect",
        "description": "Inspect component topology and local mm measurements; paginate faces/edges using next_offset. Indices belong only to this candidate.",
        "inputSchema": schema(
            {
                "candidate_id": TOKEN,
                "instance_id": {"type": "string"},
                "offset": {"type": "integer", "minimum": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 256},
            },
            ["candidate_id"],
        ),
    },
    {
        "name": "cad_apply",
        "description": "Apply one CAD command to candidate geometry. Inspect after changes. Failure leaves the previous candidate intact. Transform is in assembly/world axes; solid operations are body-local mm.",
        "inputSchema": schema(
            {
                "candidate_id": TOKEN,
                "command": inline_schema(TypeAdapter(Command).json_schema()),
            },
            ["candidate_id", "command"],
        ),
    },
    {
        "name": "cad_script",
        "description": "Run restricted CadQuery CAD language. No imports, files, shell, eval, reflection, functions or general Python. Use cq.Workplane/Plane/Vector, numeric params, assignments, for i in range(n), ordinary geometry method chains. Return parts={instance_id: solid}. When selected, return ONLY selected instance ID using selected (local shape). Otherwise adds new named parts. Parameters and source are retained as editable definitions.",
        "inputSchema": schema(
            {
                "candidate_id": TOKEN,
                "source": {"type": "string", "maxLength": 50000},
                "parameters": {
                    "type": "object",
                    "additionalProperties": {"type": "number"},
                },
                "instance_id": {"type": "string"},
            },
            ["candidate_id", "source"],
        ),
    },
    {
        "name": "cad_validate",
        "description": "Check current candidate solid validity, unrelated component preservation and STEP export/reimport. Application repeats checks before accepting the turn.",
        "inputSchema": schema({"candidate_id": TOKEN}, ["candidate_id"]),
    },
]


TOOLS.append(
    {
        "name": "cad_apply_batch",
        "description": "Atomically apply planar face offsets/holes to multiple submitted faces and components. All face references resolve against this candidate before any topology changes. Failure leaves the prior candidate unchanged.",
        "inputSchema": schema(
            {
                "candidate_id": TOKEN,
                "commands": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 32,
                    "items": inline_schema(
                        TypeAdapter(FaceOffset | FaceHoles).json_schema()
                    ),
                },
            },
            ["candidate_id", "commands"],
        ),
    }
)


IDS = {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 256, "uniqueItems": True}
SOURCE_IDS = {**IDS, "maxItems": 100}
VEC = {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}
COLOUR = {"anyOf": [VEC, {"type": "string", "pattern": "^#[0-9a-fA-F]{6}$"}]}
CATALOG_ID = {"type": "integer", "minimum": 1, "maximum": 2**63 - 1}
CATALOG_FINGERPRINT = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
TOOLS.extend([
    {"name": "cad_decision", "description": "Record a brief public CAD decision summary for this turn's project log. State the chosen approach, supporting facts, alternatives and why cq_warehouse is suitable or unsuitable. This is a concise rationale, not private reasoning. Report before modelling, and update when the approach changes; no geometry or operation-budget change.",
     "inputSchema": schema({"candidate_id": TOKEN, "summary": {"type": "string", "minLength": 1, "maxLength": 2000},
        "cq_warehouse": schema({"choice": {"enum": ["use", "do_not_use", "not_applicable", "undecided"]},
            "reason": {"type": "string", "minLength": 1, "maxLength": 2000}}, ["choice", "reason"]),
         "catalog": schema({"choice": {"enum": list(CHOICES)}, "reason": {"type": "string", "minLength": 1, "maxLength": 2000},
             "result_ids": {"type": "array", "items": CATALOG_ID, "maxItems": 20, "uniqueItems": True}}, ["choice", "reason"]),
        "alternatives": {"type": "array", "maxItems": 12, "items": {"type": "string", "maxLength": 300}}}, ["candidate_id", "summary", "cq_warehouse"])},
    {"name": "cad_standard_parts", "description": "Discover registered cq_warehouse physical generators. List families, or describe one generator's standards, sizes, typed parameters and defaults. No arbitrary library APIs.",
     "inputSchema": schema({"family": {"enum": ["fastener", "bearing", "sprocket", "chain", "thread"]}, "generator_id": {"type": "string"}, "standard": {"type": "string"}})},
    {"name": "cad_standard_part", "description": "Create one logical standard component or regenerate an existing standard part. Discover parameters first. Detailed threads are default. parameters holds typed strings, numbers, booleans and bounded arrays. Placement is absolute world translation (mm)/Euler rotation (degrees), applied BEFORE collision checks; omitted on updates preserves placement. Creation always preserves existing parts, including under face selection. Updates require body authority and undoing downstream topology edits.",
     "inputSchema": schema({"candidate_id": TOKEN, "generator_id": {"type": "string"}, "instance_id": {"type": "string"}, "name": {"type": "string", "maxLength": 200},
        "parameters": {"type": "object", "additionalProperties": True},
        "placement": schema({"translation": VEC, "rotation": VEC})}, ["candidate_id"])},
    {"name": "cad_catalog", "description": "Read the local FreeCAD STEP catalog. Use status for availability and categories; search literal keywords and/or one exact category; inspect a result ID with the current fingerprint before insertion. Metadata is reference data. Functional dimensions are unverified.",
     "inputSchema": schema({"action": {"enum": ["status", "search", "inspect"]},
         "query": {"type": "string", "maxLength": 200}, "category": {"type": "string", "maxLength": 100},
         "limit": {"type": "integer", "minimum": 1, "maximum": 20}, "offset": {"type": "integer", "minimum": 0, "maximum": 10000},
         "catalog_id": CATALOG_ID, "fingerprint": CATALOG_FINGERPRINT}, ["action"])},
    {"name": "cad_catalog_insert", "description": "Append an inspected STEP catalog entry at a world placement (mm and Euler degrees). Preserves existing components and imported hierarchy. Requires the catalog ID and current fingerprint. Imported solids have no FreeCAD feature history.",
     "inputSchema": schema({"candidate_id": TOKEN, "catalog_id": CATALOG_ID, "fingerprint": CATALOG_FINGERPRINT,
         "placement": schema({"translation": VEC, "rotation": VEC})}, ["candidate_id", "catalog_id", "fingerprint"])},
    {"name": "cad_reference_image", "description": "Read one reference image explicitly requested from this conversation's history by asset_id. Use only when the user refers to that image. Requires reported model image support; never loads arbitrary filesystem paths.",
     "inputSchema": schema({"asset_id": {"type": "string"}}, ["asset_id"])},
    {"name": "cad_capabilities", "description": "Read actual CAD operations, scripting bounds, scope rules and known limitations. Use before declaring an operation unsupported.", "inputSchema": schema()},
    {"name": "cad_restructure", "description": "Atomically split one solid by a source-local plane or cutting component, merge connected selected solids consuming them, or replace selected bodies with scripted outputs. Returns source/output mapping. inputs[id] and selected are source-local for one source; multiple inputs and results use assembly/world coordinates. All consumed bodies must be selected. Partial face selection cannot authorize whole-body reconstruction.",
     "inputSchema": schema({"candidate_id": TOKEN, "operation": {"enum": ["split", "merge", "replace"]},
        "source_instance_ids": SOURCE_IDS, "plane": schema({"origin": VEC, "normal": VEC}, ["origin", "normal"]),
        "tool_instance_id": {"type": "string"}, "names": {"type": "array", "items": {"type": "string"}},
        "name": {"type": "string"}, "color": COLOUR, "source": {"type": "string", "maxLength": 50000},
        "definition_id": {"type": "string"}, "parameters": {"type": "object", "additionalProperties": {"type": "number"}}},
        ["candidate_id", "operation", "source_instance_ids"])},
    {"name": "cad_appearance", "description": "Assign uniform component RGB colour without changing geometry. Requires whole-component selection when scope is restricted. Reset mesh overrides with source_colors=true.",
     "inputSchema": schema({"candidate_id": TOKEN, "instance_ids": IDS, "color": COLOUR, "source_colors": {"type": "boolean"}}, ["candidate_id", "instance_ids"])},
    {"name": "cad_engineering", "description": "Add/update/remove saved dimension, label or note metadata. Notes appear in conversation and Properties. Viewport display defaults off; set viewport_visible=true only when the user explicitly requests viewport annotations. Tolerances do NOT resize geometry. Bind dimensions to existing named parameters or measured entity pairs; unbound nominal values remain declared/unverified. No GD&T/PMI export is claimed.",
     "inputSchema": schema({"candidate_id": TOKEN, "action": {"enum": ["upsert", "remove"]},
        "record": schema({"id": {"type": "string"}, "kind": {"enum": ["dimension", "label", "note"]},
            "instance_id": {"type": "string"}, "text": {"type": "string", "maxLength": 2000},
            "viewport_visible": {"type": "boolean", "description": "Display in the viewport only at the user's explicit request; defaults to false for new and legacy records."},
            "nominal": {"type": "number"}, "parameter": {"type": "string"},
            "units": {"enum": ["mm", "deg", "unitless"]},
            "anchor": schema({"kind": {"enum": ["body", "face", "edge", "vertex"]}, "index": {"type": "integer", "minimum": 1}, "asset_hash": {"type": "string"}, "position": VEC}, ["kind"]),
            "tolerance": schema({"mode": {"enum": ["plus_minus", "limits"]}, "value": {"type": "number"}, "minus": {"type": "number"}, "plus": {"type": "number"}, "lower": {"type": "number"}, "upper": {"type": "number"}}, ["mode"]),
            "measurement": schema({"first": ENTITY, "second": ENTITY}, ["first", "second"])})}, ["candidate_id", "record"])},
    {"name": "cad_files", "description": "List project CAD references/definitions, read a definition, or stage an editable .cad.py/.cad.json definition in the candidate. Paths, application source and credentials are never writable. Staging does not execute geometry. Use the definition_id with cad_script or cad_restructure to execute it.",
     "inputSchema": schema({"candidate_id": TOKEN, "action": {"enum": ["list", "read", "stage"]},
        "definition_id": {"type": "string"}, "name": {"type": "string"}, "source": {"type": "string", "maxLength": 50000}, "owner_ids": IDS,
        "parameters": {"type": "object", "additionalProperties": {"type": "number"}}}, ["candidate_id", "action"])},
])
for tool in TOOLS:
    if tool["name"] == "cad_script":
        tool["description"] = "Run the controlled CAD language: CadQuery workplanes and typed solid/compound constructors, selectors, splits, tags, profile offsets, text, bounded loops/collections, tuple unpacking and branching. Return parts={name: solid,...}; optionally colors={name: '#RRGGBB'}. selected is local for one source; inputs[id] supplies named source shapes (world coordinates for multiple sources). Multiple outputs replace consumed selected bodies atomically. No imports, filesystem, shell, reflection or arbitrary functions. Source/parameters are retained."
        tool["inputSchema"]["properties"].update(source_instance_ids=SOURCE_IDS, definition_id={"type": "string"})
        tool["inputSchema"]["required"] = ["candidate_id"]

for tool in TOOLS:
    tool["annotations"] = {
        "readOnlyHint": tool["name"]
        in (
            "cad_context",
            "cad_capabilities",
            "cad_decision",
            "cad_standard_parts",
            "cad_catalog",
            "cad_reference_image",
            "cad_definition",
            "cad_inspect",
            "cad_measure",
            "cad_viewport",
            "cad_validate",
        ),
        "destructiveHint": False,
        "openWorldHint": False,
    }


def fingerprint(snapshot):
    return {
        p["instance_id"]: json.dumps({"component": p,
            "engineering": [r for r in snapshot.get("engineering", []) if r.get("instance_id") == p["instance_id"]],
            "definitions": [r for r in snapshot.get("definitions", []) if p["instance_id"] in r.get("owner_ids", [])]},
            sort_keys=True, separators=(",", ":")) for p in snapshot["components"]
    }


def geometry_fingerprint(snapshot):
    return {p["instance_id"]: (p["asset_hash"], p["matrix"]) for p in snapshot["components"]}


def changed_state(before, after):
    return any(before.get(key, []) != after.get(key, []) for key in ("components", "engineering", "definitions"))


class TaskTools:
    def __init__(self, workspace, doc, snapshot, selection, project_id, task_id):
        self.workspace, self.document = workspace, doc
        self.original = copy.deepcopy(snapshot)
        self.candidate = copy.deepcopy(snapshot)
        self.selection = copy.deepcopy(selection)
        self.project_id, self.task_id = project_id, task_id
        self.candidate_id = uuid4().hex
        self.commands = []
        self.lock = threading.RLock()
        self.closed = False
        self.created = set()
        self.retired = set()
        self.transactions = []
        self.turn_log = None
        self.decisions = []
        self.mcp_runtime = None
        self._catalog = None
        self.catalog_groups = []
        self.selection = normalize(
            selection,
            snapshot,
            project_id,
            lambda target, offset: self.geometry(
                "inspect", instance_id=target, offset=offset, limit=1
            )["components"][0],
        )
        self.scope = (
            {e["instance_id"] for e in self.selection["entities"]}
            if self.selection
            else set()
        )

    def geometry(self, method, **params):
        scripted = method == "script" or (method == "restructure" and params.get("request", {}).get("operation") == "replace" and "source" in params.get("request", {}))
        return self.workspace.geometry(
            method,
            {
                "project_dir": str(self.document.folder),
                "snapshot": self.candidate,
                **params,
            },
            timeout=45 if scripted else None,
        )

    def write_selection(self):
        if not self.selection:
            return None
        selection = copy.deepcopy(self.selection)
        current_ids = {p["instance_id"] for p in self.candidate["components"]}
        selection["entities"] = [e for e in selection["entities"] if e["instance_id"] in current_ids]
        selection["entities"] += [{"instance_id": identity, "kind": "body"} for identity in self.created]
        return selection

    def require_bodies(self, identities):
        if not identities or len(identities) != len(set(identities)):
            raise WorkspaceError("Choose distinct current component IDs.", "invalid_target")
        current = {p["instance_id"] for p in self.candidate["components"]}
        if any(identity not in current for identity in identities):
            raise WorkspaceError("A target component is no longer present.", "stale_selection")
        for identity in identities:
            check_command(self.write_selection(), self.candidate, script_target=identity)
        return identities

    @property
    def catalog(self):
        if self._catalog is None:
            self._catalog = StepCatalog()
        return self._catalog

    def scope_check(self, candidate, transaction=None):
        before, after = fingerprint(self.original), fingerprint(candidate)
        removed, created = set(self.retired), set(self.created)
        if transaction:
            consumed = set(transaction["consumed"])
            outputs = set(transaction["outputs"])
            removed |= consumed - outputs
            created |= outputs - set(before)
        if self.scope:
            nodes = candidate.get("assembly_nodes", [])
            allowed_nodes = self.original.get("assembly_nodes", []) + self.catalog_groups
            if transaction and transaction["operation"] == "catalog_insert":
                added = nodes[len(allowed_nodes):]
                if [node["id"] for node in added] == transaction["added_groups"]:
                    allowed_nodes += added
            if nodes != allowed_nodes:
                raise WorkspaceError("This edit changes assembly groups outside component-only scope. Use document scope for assembly restructuring.", "scope_violation")
            unrelated = set(before) - self.scope
            changed = [identity for identity in unrelated if after.get(identity) != before[identity]]
            if changed:
                raise WorkspaceError("The edit also changes unselected components: " + ", ".join(changed) + ". Select those dependencies or restrict the change.", "scope_violation")
            if (set(before) - set(after)) - removed or (set(after) - set(before)) - created:
                raise WorkspaceError("Component additions/removals need an authorized restructuring transaction.", "scope_violation")
            original_globals = [d for d in self.original.get("definitions", []) if not d.get("owner_ids")]
            candidate_globals = [d for d in candidate.get("definitions", []) if not d.get("owner_ids")]
            if original_globals != candidate_globals:
                raise WorkspaceError("Document-wide definitions cannot be changed under a restricted selection.", "scope_violation")
        return {"passed": True, "unrelated_components_checked": len(before) - len(self.scope) if self.scope else 0,
                "scope": sorted(self.scope) if self.scope else "document", "component_count": len(candidate["components"])}

    def validate(self):
        from .engineering import rgb, validate_records
        from .definitions import read
        from backend.native.documents import asset_path
        import hashlib
        for part in self.candidate["components"]:
            rgb(part["color"])
            if part.get("color_override") is not None:
                rgb(part["color_override"])
        for definition in self.candidate.get("definitions", []):
            read(self.document.folder, definition)
        engineering = validate_records(self.candidate)
        prior = self.original.get("verification", {})
        prior_passed = prior.get("passed") or prior.get("geometry", {}).get("passed")
        if geometry_fingerprint(self.candidate) == geometry_fingerprint(self.original) and (prior_passed or not self.candidate["components"]):
            for part in self.candidate["components"]:
                path = asset_path(self.document.folder, part.get("mesh", part.get("brep", "")))
                if hashlib.sha256(path.read_bytes()).hexdigest() != part["asset_hash"]:
                    raise WorkspaceError("A retained geometry asset changed.", "asset_integrity")
            report = {"passed": True, "mode": "unchanged_geometry", "asset_integrity": True}
        else:
            report = self.geometry("verify")
            if not report.get("passed"):
                raise WorkspaceError("Candidate geometry did not pass verification.", "verification_failed")
        return {"geometry": report, "engineering": engineering, "scope": self.scope_check(self.candidate), "candidate_id": self.candidate_id}


    def context(self):
        return {
            "step_catalog": self.catalog.status(),
            "project_id": self.project_id,
            "document_id": self.original["document_id"],
            "base_revision_id": self.original.get("revision_id"),
            "candidate_id": self.candidate_id,
            "selection": self.selection,
            "assembly_nodes": self.candidate.get("assembly_nodes", []),
            "components": [
                {
                    **{
                        k: p[k]
                        for k in (
                            "instance_id",
                            "name",
                            "metrics",
                            "matrix",
                            "topology",
                        )
                    },
                    "parent_id": p.get("parent_id"),
                    "body_id": p.get("definition_id"),
                    "representation": p.get("representation", "solid"),
                    "shape_kind": p.get("shape_kind", "solid"),
                    "standard_generator": p.get("standard_part", {}).get("generator_id"),
                    "parameters": p.get("parameters", {}),
                    "color": p.get("color"),
                    "color_override": p.get("color_override"),
                    "asset_hash": p["asset_hash"],
                }
                for p in self.candidate["components"]
            ],
            "engineering": self.candidate.get("engineering", []),
            "component_transactions": self.transactions,
            "reference_images": self.reference_context(),
            "units": "mm",
            "rules": "Selection is frozen for this task. Reinspect after every successful write. Failed tools leave candidate unchanged. Changes are accepted only after final verification and successful provider completion.",
        }

    def reference_context(self):
        from .attachments import public
        result = []
        for reference in getattr(self, "references", {}).values():
            item = public(self.workspace.projects.project_path(self.project_id), reference)
            result.append({k: v for k, v in item.items() if k not in ("local_path", "path")})
        return result

    def call(self, name, params):
        with self.lock:
            log = self.turn_log
            if log is None or log.closed:
                return self._call(name, params)
            command = params.get("command", {})
            target = params.get("instance_id") or (command.get("instance_id") if isinstance(command, dict) else None)
            part = next((p for p in self.candidate["components"] if p["instance_id"] == target), {})
            numeric_regeneration = name == "cad_apply" and isinstance(command, dict) and command.get("type") == "parameters" and bool(part.get("standard_part"))
            generation = name == "cad_standard_part" or numeric_regeneration
            generator = params.get("generator_id") or part.get("standard_part", {}).get("generator_id")
            call = log.tool_started(name, params, generation, generator if generation else None)
            try:
                result = self._call(name, params)
            except Exception as error:
                log.tool_finished(call, error=error)
                raise
            log.tool_finished(call, result=result)
            return result

    def _call(self, name, params):
        with self.lock:
            runtime = getattr(self.workspace, "application_runtime", None)
            if runtime is not None:
                runtime.ensure_current()
            if self.closed or self.workspace.cancelled.is_set():
                raise WorkspaceError("This task is no longer writable.", "cancelled")
            if name == "cad_viewport":
                return {
                    "image": getattr(self, "viewport", None),
                    "revision_id": self.original.get("revision_id"),
                    "state": "base revision at submission",
                }
            if name == "cad_reference_image":
                if not getattr(self, "image_supported", False):
                    raise WorkspaceError("Choose a model with confirmed image-input metadata before using image references.", "image_capability_required")
                reference = getattr(self, "references", {}).get(params.get("asset_id"))
                if not reference:
                    raise WorkspaceError("That reference is not part of this conversation.", "invalid_attachment")
                from .attachments import resolve
                path = resolve(self.workspace.projects.project_path(self.project_id), reference)
                # MCP image content uses PNG independently of the source file format.
                from PIL import Image
                import io, base64
                with Image.open(path) as original:
                    output = io.BytesIO()
                    observation = original.convert("RGB")
                    observation.thumbnail((1200, 1200))
                    observation.save(output, format="PNG")
                return {"reference": {k: v for k, v in reference.items() if k != "path"},
                        "observation": "Downsampled to at most 1200 pixels per side for MCP transport. Reattach the preserved original for full-resolution turn input.",
                        "image_data": base64.b64encode(output.getvalue()).decode()}
            if name == "cad_context":
                return self.context()
            if name == "cad_catalog":
                return self.catalog.query(params)
            if name == "cad_standard_parts":
                return self.geometry("standard_parts", request=params)
            if name == "cad_capabilities":
                return {"tools": [t["name"] for t in TOOLS],
                    "application_runtime": runtime.report() if runtime is not None else None,
                    "script_language": self.geometry("capabilities"),
                    "restructure": ["split_by_local_plane", "split_by_component", "connected_union", "replace_selected_with_multiple_outputs"],
                    "solid_editing": ["hole", "extrude", "offset_planar_face", "face_holes", "fillet", "chamfer", "boolean", "pattern", "transform", "named_parameters"],
                    "standard_parts": "cad_standard_parts discovers the installed pinned library. Compound parts use one component ID with multiple valid solids; typed generator parameters are separate from numeric named parameters.",
                    "step_catalog": self.catalog.status(),
                    "scripting": "Typed CadQuery constructors/methods, branches, comparisons, tuple assignment, bounded collections/loops; parts and optional colors outputs. No imports, arbitrary functions, I/O, reflection or shell.",
                    "engineering": ["bound_or_declared_dimensions", "plus_minus_tolerance", "limit_tolerance", "label", "note"],
                    "appearance": "Uniform RGB per component, mesh source-colour reset; STEP solid and GLB colour export; STL has no colours.",
                    "limits": {"operations": 32, "task_seconds": 600, "script_seconds": 45, "script_outputs": 100, "restructure_sources": 100, "selected_entities": 256, "engineering_records": 1000},
                    "unavailable": ["full_GD&T", "STEP_PMI_export", "original_imported_feature_history", "arbitrary_mesh_to_solid", "image_to_3D_generation_service"],
                    "scope": "Body restructuring needs selected bodies; face/edge scope is never widened. All component outputs have trusted transaction lineage. Images provide references, not exact hidden geometry."}
            if params.get("candidate_id") != self.candidate_id:
                raise WorkspaceError(
                    "Candidate references are stale. Call cad_context and inspect again.",
                    "stale_selection",
                )
            if name == "cad_decision":
                if len(self.decisions) >= 64:
                    raise WorkspaceError("Use at most 64 concise decision summaries per turn.", "operation_limit")
                summary, choice = params.get("summary"), params.get("cq_warehouse")
                alternatives = params.get("alternatives", [])
                if (not isinstance(summary, str) or not 1 <= len(summary.strip()) <= 2000
                    or not isinstance(choice, dict) or choice.get("choice") not in ("use", "do_not_use", "not_applicable", "undecided")
                    or not isinstance(choice.get("reason"), str) or not 1 <= len(choice["reason"].strip()) <= 2000
                    or not isinstance(alternatives, list) or len(alternatives) > 12
                    or any(not isinstance(value, str) or len(value) > 300 for value in alternatives)):
                    raise WorkspaceError("Provide a concise decision summary and explicit cq_warehouse choice/reason.", "invalid_decision")
                decision = {"decision_id": uuid4().hex, "reported_at": time.time(),
                    "candidate_id": self.candidate_id, "summary": summary.strip(),
                    "cq_warehouse": {"choice": choice["choice"], "reason": choice["reason"].strip()}, "alternatives": alternatives}
                if "catalog" in params:
                    choice = params["catalog"]
                    if not isinstance(choice, dict) or choice.keys() - {"choice", "reason", "result_ids"}:
                        raise WorkspaceError("Provide a catalog choice and concise reason.", "invalid_decision")
                    reason, ids = choice.get("reason"), choice.get("result_ids", [])
                    if (choice.get("choice") not in CHOICES or not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 2000
                            or not isinstance(ids, list) or len(ids) > 20
                            or any(type(identity) is not int or not 0 < identity < 2**63 for identity in ids)
                            or len(set(ids)) != len(ids)):
                        raise WorkspaceError("Provide a catalog choice, concise reason and valid result IDs.", "invalid_decision")
                    decision["catalog"] = {"choice": choice["choice"], "reason": reason.strip(), "result_ids": ids}
                self.decisions.append(copy.deepcopy(decision))
                if self.turn_log is not None:
                    self.turn_log.decision(decision)
                return {"candidate_id": self.candidate_id, "decision_id": decision["decision_id"], "recorded": True}
            if name == "cad_definition":
                wanted = params["instance_id"]
                part = next(
                    (
                        p
                        for p in self.candidate["components"]
                        if p["instance_id"] == wanted
                    ),
                    None,
                )
                if not part:
                    raise WorkspaceError(
                        "The requested component is no longer present.",
                        "stale_selection",
                    )
                script = next(
                    (
                        d
                        for d in reversed(self.candidate.get("scripts", []))
                        if wanted in d.get("part_ids", [])
                    ),
                    None,
                )
                recipe = next(
                    (
                        d
                        for d in self.candidate.get("recipe", {}).get("components", [])
                        if d["id"] == wanted
                    ),
                    None,
                )
                return {
                    "candidate_id": self.candidate_id,
                    "instance_id": wanted,
                    "parameters": part.get("parameters", {}),
                    "standard_part": part.get("standard_part"),
                    "catalog_part": part.get("catalog_part"),
                    "standard_regeneration_allowed": bool(part.get("standard_part") and part["asset_hash"] == part["standard_part"]["generated_asset_hash"]),
                    "script": {
                        k: script.get(k) for k in ("source", "parameters", "instance_id", "source_instance_ids", "output_names")
                    }
                    if script
                    else None,
                    "recipe": recipe,
                    "recipe_run": next((r for r in reversed(self.candidate.get("recipe_runs", [])) if wanted in r["output_names"].values()), None),
                    "definitions": [{k: v for k, v in d.items() if k != "source"} for d in self.candidate.get("definitions", []) if wanted in d.get("owner_ids", [])],
                    "original_feature_history": "Only retained app definitions are available; imported history is not reconstructed.",
                }
            if name == "cad_measure":
                return {
                    **self.geometry(
                        "measure", first=params["first"], second=params["second"]
                    ),
                    "candidate_id": self.candidate_id,
                }
            if name == "cad_inspect":
                self.workspace.notify(
                    {
                        "stage": "inspecting",
                        "message": "Inspecting "
                        + params.get("instance_id", "document"),
                    }
                )
                return {
                    **self.geometry(
                        "inspect",
                        instance_id=params.get("instance_id"),
                        offset=params.get("offset", 0),
                        limit=params.get("limit", 128),
                    ),
                    "candidate_id": self.candidate_id,
                    "selection": self.selection,
                }
            if name == "cad_validate":
                return self.validate()
            from . import definitions
            if name == "cad_files" and params.get("action") == "list":
                return {"candidate_id": self.candidate_id,
                    "definitions": [{k: v for k, v in r.items() if k != "source"} for r in self.candidate.get("definitions", [])],
                    "cad_assets": [{"instance_id": p["instance_id"], "representation": p.get("representation", "solid"),
                                    "asset_hash": p["asset_hash"]} for p in self.candidate["components"]],
                    "original_source": self.candidate.get("original_source")}
            if name == "cad_files" and params.get("action") == "read":
                definition = definitions.find(self.candidate, params["definition_id"])
                return {"candidate_id": self.candidate_id, "definition": definition,
                        "source": definitions.read(self.document.folder, definition)}
            if name not in ("cad_apply", "cad_apply_batch", "cad_script", "cad_restructure", "cad_appearance", "cad_engineering", "cad_files", "cad_standard_part", "cad_catalog_insert"):
                raise WorkspaceError("Unknown CAD capability. Read cad_capabilities.", "unsupported_operation")
            if len(self.commands) >= 32:
                raise WorkspaceError("The task reached its 32-operation budget. Continue in a new turn.", "operation_limit")
            commands = params.get("commands", []) if name == "cad_apply_batch" else [params["command"]] if name == "cad_apply" else []
            if name == "cad_apply_batch" and not 1 <= len(commands) <= 32:
                raise WorkspaceError("Use a batch of 1–32 supported face operations.", "operation_limit")
            if len(self.commands) + max(1, len(commands)) > 32:
                raise WorkspaceError("The task reached its operation budget.", "operation_limit")
            for command in commands:
                check_command(self.write_selection(), self.candidate, command=command)
            self.workspace.notify({"stage": "modelling", "message": {
                "cad_restructure": "Restructuring selected components", "cad_script": "Running CAD definition",
                "cad_appearance": "Updating component colours", "cad_engineering": "Updating engineering information",
                "cad_files": "Staging editable definition", "cad_catalog_insert": "Importing catalog STEP part"}.get(name, "Applying CAD operation")})
            record = {"type": name, **copy.deepcopy(params)}
            record.pop("candidate_id", None)
            requested_sources = None
            if name == "cad_catalog_insert":
                requested_sources = set()
                updated = self.insert_catalog(params)
            elif name == "cad_standard_part":
                identity = params.get("instance_id")
                if identity:
                    self.require_bodies([identity])
                requested_sources = {identity} if identity else set()
                updated = self.geometry("standard_part", request={k: v for k, v in params.items() if k != "candidate_id"})
            elif name == "cad_apply_batch":
                updated = self.geometry("apply_batch", commands=commands)
                record = {"type": "batch", "commands": commands}
            elif name == "cad_apply":
                updated = self.geometry("apply", command=params["command"])
                record = params["command"]
            elif name in ("cad_script", "cad_restructure"):
                request = {k: copy.deepcopy(v) for k, v in params.items() if k != "candidate_id"}
                definition = definitions.find(self.candidate, request["definition_id"]) if request.get("definition_id") else None
                if definition and request.get("source"):
                    raise WorkspaceError("Specify source or definition_id, not both.", "invalid_definition")
                if definition:
                    request.setdefault("parameters", definition.get("parameters", {}))
                identities = request.get("source_instance_ids")
                if identities is None:
                    identities = [request["instance_id"]] if request.get("instance_id") else definition.get("owner_ids", []) if definition else []
                if identities:
                    self.require_bodies(identities)
                elif self.scope:
                    raise WorkspaceError("Specify selected source bodies for a script replacement.", "insufficient_selection")
                requested_sources = set(identities)
                if definition:
                    source = definitions.read(self.document.folder, definition)
                    if definition["name"].endswith(".cad.json"):
                        if request.get("parameters"):
                            raise WorkspaceError("Edit recipe parameter values in the staged JSON or use the named-parameter command.", "invalid_parameters")
                        request["recipe"] = json.loads(source)
                        request["operation"] = "replace" if identities else "create"
                        request["source_instance_ids"] = identities
                        updated = self.geometry("restructure", request=request)
                    else:
                        request["source"] = source
                        if name == "cad_script":
                            updated = self.geometry("script", source=source, parameters=request.get("parameters", {}), source_instance_ids=identities)
                        else:
                            request["source_instance_ids"] = identities
                            updated = self.geometry("restructure", request=request)
                elif name == "cad_script":
                    updated = self.geometry("script", source=request.get("source", ""), parameters=request.get("parameters", {}), source_instance_ids=identities)
                else:
                    request["source_instance_ids"] = identities
                    updated = self.geometry("restructure", request=request)
            elif name == "cad_appearance":
                from .engineering import appearance
                identities = self.require_bodies(params["instance_ids"])
                updated = appearance(self.candidate, identities, params.get("color"), params.get("source_colors", False))
            elif name == "cad_engineering":
                from .engineering import edit
                entry = copy.deepcopy(params["record"])
                existing = next((r for r in self.candidate.get("engineering", []) if r["id"] == entry.get("id")), None)
                target = entry.get("instance_id") or (existing or {}).get("instance_id")
                if not target:
                    raise WorkspaceError("Choose a component for the engineering record.", "invalid_target")
                if existing and existing["instance_id"] != target:
                    raise WorkspaceError("Remove an annotation before moving it to another component.", "invalid_target")
                anchor = entry.get("anchor", (existing or {}).get("anchor", {"kind": "body"}))
                entry["anchor"] = copy.deepcopy(anchor)
                if self.selection:
                    permitted = [e for e in self.write_selection()["entities"] if e["instance_id"] == target]
                    if not any(e["kind"] == "body" or (e["kind"] == anchor.get("kind") and e.get("index") == anchor.get("index")) for e in permitted):
                        raise WorkspaceError("Select the annotation's body or exact entity.", "scope_violation")
                    current = next((p for p in self.candidate["components"] if p["instance_id"] == target), None)
                    if current and not any(e["kind"] == "body" for e in permitted) and any(e.get("asset_hash") != current["asset_hash"] for e in permitted):
                        raise WorkspaceError("Selected annotation topology changed. Submit a fresh selection.", "stale_selection")
                def bind_entity(reference, default_target=None):
                    identity = reference.get("instance_id", default_target)
                    current = next((p for p in self.candidate["components"] if p["instance_id"] == identity), None)
                    if not current:
                        raise WorkspaceError("The referenced component is no longer present.", "stale_selection")
                    kind = reference.get("kind", "body")
                    if kind == "body":
                        return
                    if not reference.get("asset_hash") and self.selection:
                        matches = [e for e in self.write_selection()["entities"] if e["instance_id"] == identity and e["kind"] == kind and e.get("index") == reference.get("index")]
                        if matches:
                            reference["asset_hash"] = matches[0].get("asset_hash")
                    if reference.get("asset_hash") != current["asset_hash"]:
                        raise WorkspaceError("Entity annotations and bound measurements need the current asset_hash from inspection or a fresh selection.", "stale_selection")
                if params.get("action", "upsert") != "remove":
                    bind_entity(entry["anchor"], target)
                if entry.get("measurement") and params.get("action", "upsert") != "remove":
                    for reference in entry["measurement"].values():
                        bind_entity(reference)
                    measure = self.geometry("measure", **entry["measurement"])
                    entry["nominal"] = measure["minimum_distance_mm"]
                    entry["units"] = "mm"
                updated = edit(self.candidate, entry, params.get("action", "upsert"))
                if entry.get("measurement") and params.get("action", "upsert") != "remove":
                    item = updated["engineering"][-1]
                    item["verification"] = "measured"
                    item["measurement_assets"] = {r["instance_id"]: {"asset_hash": p["asset_hash"], "matrix": p["matrix"]}
                        for r in entry["measurement"].values() for p in self.candidate["components"] if p["instance_id"] == r["instance_id"]}
            else:
                if params.get("action") != "stage":
                    raise WorkspaceError("Use list, read or stage for project definitions.", "unsupported_operation")
                owners = params.get("owner_ids", [])
                if owners:
                    self.require_bodies(owners)
                elif self.scope:
                    raise WorkspaceError("Bind the definition to selected bodies.", "insufficient_selection")
                updated = copy.deepcopy(self.candidate)
                staged = definitions.stage(updated, params["name"], params["source"], owners, params.get("parameters"))
                record["definition_id"] = staged["id"]
            if self.closed or self.workspace.cancelled.is_set():
                raise WorkspaceError("Task cancelled; candidate discarded.", "cancelled")
            transaction = updated.pop("_component_transaction", None)
            if transaction and requested_sources is not None and set(transaction["consumed"]) != requested_sources:
                raise WorkspaceError("The component transaction consumed unexpected sources.", "scope_violation")
            # Mesh separation has its own trusted worker-generated result; agents cannot supply snapshots.
            if name == "cad_apply" and params["command"]["type"] == "mesh_separate":
                old_ids = {p["instance_id"] for p in self.candidate["components"]}
                created = [p["instance_id"] for p in updated["components"] if p["instance_id"] not in old_ids]
                transaction = {"operation": "mesh_separate", "consumed": [params["command"]["instance_id"]],
                               "outputs": [params["command"]["instance_id"], *created],
                               "mapping": {params["command"]["instance_id"]: [params["command"]["instance_id"], *created]}}
            from .engineering import refresh_anchors
            refresh_anchors(self.candidate, updated)
            self.scope_check(updated, transaction)
            if not changed_state(self.candidate, updated):
                raise WorkspaceError("This operation made no geometry, appearance or engineering-data change.", "no_change")
            if transaction:
                before_ids = {p["instance_id"] for p in self.original["components"]}
                self.retired.update(set(transaction["consumed"]) - set(transaction["outputs"]))
                self.created.update(set(transaction["outputs"]) - before_ids)
                self.transactions.append(copy.deepcopy(transaction))
                record["component_transaction"] = transaction
                if transaction["operation"] == "catalog_insert":
                    groups = set(transaction["added_groups"])
                    self.catalog_groups.extend(copy.deepcopy(node) for node in updated.get("assembly_nodes", []) if node["id"] in groups)
            self.candidate = updated
            self.candidate_id = uuid4().hex
            self.commands.extend(commands if name == "cad_apply_batch" else [record])
            self.workspace.notify({"stage": "candidate", "message": "Candidate updated; validating before acceptance.",
                "document": {**updated, "project_dir": str(self.document.folder), "revision_id": self.original.get("revision_id")},
                "candidate_id": self.candidate_id})
            return {"candidate_id": self.candidate_id, "changes": len(self.commands),
                    "component_transaction": transaction, "definition_id": record.get("definition_id"),
                    **({"catalog_id": params["catalog_id"], "fingerprint": params["fingerprint"],
                        "created_component_ids": transaction["outputs"], "warnings": updated["warnings"]}
                       if name == "cad_catalog_insert" else {}),
                    "observation": "Reinspect before further topology operations; affected entity references are invalidated."}

    def insert_catalog(self, params):
        placement = params.get("placement", {})
        if (params.keys() - {"candidate_id", "catalog_id", "fingerprint", "placement"}
                or not isinstance(placement, dict) or placement.keys() - {"translation", "rotation"}):
            raise WorkspaceError("Use a catalog ID, fingerprint and optional placement vectors.", "invalid_parameters")
        pose = {key: placement.get(key, [0, 0, 0]) for key in ("translation", "rotation")}
        if any(not isinstance(vector, list) or len(vector) != 3
               or any(type(value) not in (int, float) or not -10000 <= value <= 10000 or not math.isfinite(value)
                      for value in vector) for vector in pose.values()):
            raise WorkspaceError("Placement uses finite three-value translation and rotation vectors.", "invalid_parameters")
        with self.catalog.stage(params.get("catalog_id"), params.get("fingerprint"), self.workspace.cancelled,
                                getattr(self.workspace, "task_deadline", None)) as (path, entry):
            updated = self.geometry("catalog_insert", path=str(path), provenance=entry, placement=pose)
            if self.closed or self.workspace.cancelled.is_set():
                raise WorkspaceError("Task cancelled; candidate discarded.", "cancelled")
            transaction = updated["_component_transaction"]
            existing = self.candidate["components"]
            groups = self.candidate.get("assembly_nodes", [])
            added = updated["components"][len(existing):]
            if (updated["components"][:len(existing)] != existing or updated.get("assembly_nodes", [])[:len(groups)] != groups
                    or transaction["consumed"] or not added or [part["instance_id"] for part in added] != transaction["outputs"]
                    or any(updated.get(key) != self.candidate.get(key) for key in ("engineering", "definitions"))):
                raise WorkspaceError("Catalog insertion must preserve the existing document.", "scope_violation")
            self.scope_check(updated, transaction)
            self.catalog.current_database()
            for part in added:
                source = asset_path(path.parent, part["brep"])
                target = asset_path(self.document.folder, part["brep"])
                if target.exists():
                    if digest(target) != part["asset_hash"]:
                        raise WorkspaceError("A project geometry asset has changed.", "asset_integrity")
                    continue
                target.parent.mkdir(exist_ok=True)
                temporary = target.with_name(uuid4().hex + ".tmp")
                try:
                    shutil.copyfile(source, temporary)
                    if digest(temporary) != part["asset_hash"]:
                        raise WorkspaceError("The imported geometry asset changed.", "asset_integrity")
                    temporary.replace(target)
                finally:
                    temporary.unlink(missing_ok=True)
            return updated


class ToolBridge:
    def __init__(self, tools):
        self.tools = tools
        self.token = secrets.token_urlsafe(32)
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                if (
                    self.path != "/cad"
                    or self.headers.get("Authorization") != "Bearer " + owner.token
                    or self.headers.get("Origin")
                ):
                    self.send_error(403)
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 1024 * 1024:
                        raise WorkspaceError("Tool input exceeds the limit.")
                    message = json.loads(self.rfile.read(length))
                    if message["name"] == "_runtime_check":
                        with tools.lock:
                            if tools.closed:
                                raise WorkspaceError("The CAD tool session is closed.", "cancelled")
                            runtime = tools.workspace.application_runtime
                            peer = message.get("arguments", {})
                            runtime.verify_peer(peer, "mcp")
                            tools.mcp_runtime = peer
                            if tools.turn_log is not None:
                                tools.turn_log.event("mcp_tools_delivered", peer)
                        result = {"result": {"verified": True}}
                    elif message["name"] == "_runtime_list_returned":
                        with tools.lock:
                            peer = message.get("arguments", {})
                            tools.workspace.application_runtime.verify_peer(peer, "mcp")
                            if tools.mcp_runtime != peer:
                                raise WorkspaceError("The CAD tool list was not verified.", "runtime_mismatch")
                            if tools.turn_log is not None and not tools.turn_log.closed:
                                tools.turn_log.catalog_evidence("tool_list_returned", {
                                    "catalog_tools_present": CATALOG_TOOLS.issubset(peer["tool_names"]),
                                    "tools_sha256": peer["tools_sha256"], "tool_names": peer["tool_names"],
                                })
                        result = {"result": {"recorded": True}}
                    else:
                        if tools.mcp_runtime is None:
                            raise WorkspaceError("The CAD MCP tool registry has not been verified. Restart Prompt to CAD.", "runtime_mismatch")
                        result = {"result": tools.call(message["name"], message.get("arguments", {}))}
                except Exception as error:
                    result = {
                        "error": str(error),
                        "code": getattr(error, "code", "tool_failed"),
                    }
                data = json.dumps(result, allow_nan=False).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_port}/cad"

    def close(self):
        self.tools.closed = True
        self.server.shutdown()
        self.server.server_close()

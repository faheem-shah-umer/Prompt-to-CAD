"""Provider-independent, task-scoped CAD capabilities."""

import copy
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

from pydantic import TypeAdapter

from backend.native.contracts import Command, FaceOffset, FaceHoles, WorkspaceError
from .selection import normalize, check_command


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

for tool in TOOLS:
    tool["annotations"] = {
        "readOnlyHint": tool["name"]
        in (
            "cad_context",
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
        p["instance_id"]: (p["asset_hash"], p["matrix"]) for p in snapshot["components"]
    }


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
        return self.workspace.geometry(
            method,
            {
                "project_dir": str(self.document.folder),
                "snapshot": self.candidate,
                **params,
            },
            timeout=45 if method == "script" else None,
        )

    def scope_check(self, candidate):
        before, after = fingerprint(self.original), fingerprint(candidate)
        if self.scope:
            additions = [
                p for p in candidate["components"] if p["instance_id"] not in before
            ]
            allowed = all(
                p.get("source_instance_id") in self.scope
                and p.get("representation") == "mesh"
                for p in additions
            )
            if (
                not set(before) <= set(after)
                or not allowed
                or any(
                    after[k] != value
                    for k, value in before.items()
                    if k not in self.scope
                )
            ):
                raise WorkspaceError(
                    "The candidate changed an unrelated component. Nothing was accepted.",
                    "scope_violation",
                )
        return {
            "passed": True,
            "unrelated_components_checked": len(before) - len(self.scope)
            if self.scope
            else 0,
            "scope": sorted(self.scope) if self.scope else "document",
            "component_count": len(candidate["components"]),
        }

    def context(self):
        return {
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
                    "parameters": p.get("parameters", {}),
                }
                for p in self.candidate["components"]
            ],
            "units": "mm",
            "rules": "Selection is frozen for this task. Reinspect after every successful write. Failed tools leave candidate unchanged. Changes are accepted only after final verification and successful provider completion.",
        }

    def call(self, name, params):
        with self.lock:
            if self.closed or self.workspace.cancelled.is_set():
                raise WorkspaceError("This task is no longer writable.", "cancelled")
            if name == "cad_viewport":
                return {
                    "image": getattr(self, "viewport", None),
                    "revision_id": self.original.get("revision_id"),
                    "state": "base revision at submission",
                }
            if name == "cad_context":
                return self.context()
            if params.get("candidate_id") != self.candidate_id:
                raise WorkspaceError(
                    "Candidate references are stale. Call cad_context and inspect again.",
                    "stale_selection",
                )
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
                    "script": {
                        k: script[k] for k in ("source", "parameters", "instance_id")
                    }
                    if script
                    else None,
                    "recipe": recipe,
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
                return {
                    "geometry": self.geometry("verify"),
                    "scope": self.scope_check(self.candidate),
                    "candidate_id": self.candidate_id,
                }
            if name not in ("cad_apply", "cad_apply_batch", "cad_script"):
                raise WorkspaceError("Unknown CAD capability.", "method_not_found")
            if len(self.commands) >= 32:
                raise WorkspaceError(
                    "The task reached its 32-operation budget. Finish or ask for a smaller task.",
                    "operation_limit",
                )
            commands = (
                params.get("commands", [])
                if name == "cad_apply_batch"
                else [params["command"]]
                if name == "cad_apply"
                else []
            )
            if name == "cad_apply_batch" and (not commands or len(commands) > 32):
                raise WorkspaceError("Use a batch of 1–32 supported face operations.")
            if len(self.commands) + max(1, len(commands)) > 32:
                raise WorkspaceError(
                    "The task reached its operation budget.", "operation_limit"
                )
            for command in commands:
                check_command(self.selection, self.candidate, command=command)
            target = params.get("instance_id")
            if name == "cad_script":
                check_command(self.selection, self.candidate, script_target=target)
            self.workspace.notify(
                {
                    "stage": "modelling",
                    "message": "Applying selected geometry batch"
                    if name == "cad_apply_batch"
                    else "Running CAD script"
                    if name == "cad_script"
                    else "Applying " + commands[0]["type"],
                }
            )
            if name == "cad_apply_batch":
                updated = self.geometry("apply_batch", commands=commands)
                record = {"type": "batch", "commands": commands}
            elif name == "cad_apply":
                updated = self.geometry("apply", command=params["command"])
                record = params["command"]
            else:
                updated = self.geometry(
                    "script",
                    source=params["source"],
                    parameters=params.get("parameters", {}),
                    instance_id=target,
                )
                record = {
                    "type": "script",
                    "source": params["source"],
                    "parameters": params.get("parameters", {}),
                    "instance_id": target,
                }
            if self.closed or self.workspace.cancelled.is_set():
                raise WorkspaceError(
                    "Task cancelled; candidate was discarded.", "cancelled"
                )
            self.scope_check(updated)
            if fingerprint(updated) == fingerprint(self.candidate):
                raise WorkspaceError(
                    "This operation made no geometry or placement change.", "no_change"
                )
            self.candidate = updated
            self.candidate_id = uuid4().hex
            self.commands.extend(commands if name == "cad_apply_batch" else [record])
            self.workspace.notify(
                {
                    "stage": "candidate",
                    "message": "Candidate geometry updated; checking before acceptance.",
                    "document": {
                        **updated,
                        "project_dir": str(self.document.folder),
                        "revision_id": self.original.get("revision_id"),
                    },
                    "candidate_id": self.candidate_id,
                }
            )
            return {
                "candidate_id": self.candidate_id,
                "changes": len(self.commands),
                "observation": "Reinspect current geometry before using topology indices.",
            }


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
                    result = {
                        "result": tools.call(
                            message["name"], message.get("arguments", {})
                        )
                    }
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

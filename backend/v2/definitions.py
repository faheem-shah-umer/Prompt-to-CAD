"""Content-addressed project definitions; no agent-selected filesystem paths."""

import ast
import hashlib
import json
import re
import math
import copy
from pathlib import Path
from uuid import uuid4

from backend.native.contracts import WorkspaceError
from backend.native.documents import asset_path


def checked_parameters(values):
    if not isinstance(values, dict) or len(values) > 64 or any(
        not isinstance(key, str) or type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 1e6
        for key, value in values.items()
    ):
        raise WorkspaceError("Definition parameters must be bounded named numbers.", "invalid_parameters")
    return copy.deepcopy(values)


def stage(snapshot, name, source, owners, parameters=None):
    if (not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_. -]{0,99}", name)
            or ".." in name or not name.endswith((".cad.py", ".cad.json"))):
        raise WorkspaceError("Use a plain .cad.py or .cad.json definition filename.", "invalid_definition")
    if not isinstance(source, str) or not 0 < len(source) <= 50000:
        raise WorkspaceError("Definitions contain 1–50,000 characters.", "invalid_definition")
    try:
        if name.endswith(".cad.py"):
            ast.parse(source)
        else:
            from backend.native.design_schema import Design
            Design.model_validate(json.loads(source))
    except (SyntaxError, ValueError) as error:
        raise WorkspaceError("Invalid editable definition: " + str(error), "invalid_definition") from None
    record = {"id": uuid4().hex, "name": name, "source": source,
              "owner_ids": list(owners), "parameters": checked_parameters(parameters if parameters is not None else {}),
              "sha256": hashlib.sha256(source.encode()).hexdigest()}
    snapshot.setdefault("definitions", []).append(record)
    return record


def materialize(folder, snapshot):
    for record in snapshot.get("definitions", []):
        if "source" not in record:
            read(folder, record)
            continue
        data = record["source"].encode()
        digest = hashlib.sha256(data).hexdigest()
        if digest != record["sha256"]:
            raise WorkspaceError("An editable definition changed unexpectedly.", "asset_integrity")
        extension = ".cad.py" if record["name"].endswith(".cad.py") else ".cad.json"
        relative = "definitions/" + digest + extension
        path = asset_path(folder, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
            try:
                temporary.write_bytes(data)
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
        elif path.read_bytes() != data:
            raise WorkspaceError("An immutable definition asset does not match.", "asset_integrity")
        record["path"] = relative
        record.pop("source", None)


def read(folder, record):
    if not isinstance(record, dict):
        raise WorkspaceError("Definition records must be objects.", "invalid_definition")
    checked_parameters(record.get("parameters", {}))
    if "source" in record:
        source = record["source"]
    else:
        source = asset_path(folder, record["path"]).read_text(encoding="utf-8")
    if not isinstance(source, str) or hashlib.sha256(source.encode()).hexdigest() != record["sha256"]:
        raise WorkspaceError("Definition asset integrity check failed.", "asset_integrity")
    return source


def find(snapshot, identity):
    record = next((r for r in snapshot.get("definitions", []) if r["id"] == identity), None)
    if not record:
        raise WorkspaceError("The definition is not part of this candidate.", "stale_selection")
    return record

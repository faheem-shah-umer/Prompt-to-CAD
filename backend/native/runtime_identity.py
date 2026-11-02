"""Identify loaded CAD processes and reject source/tool drift between them."""

import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from .contracts import WorkspaceError

ROOT = Path(__file__).resolve().parents[2]
STANDARD_TOOLS = {"cad_standard_parts", "cad_standard_part"}


def source_hash(root=ROOT):
    digest = hashlib.sha256()
    for path in sorted((Path(root) / "backend").rglob("*")):
        if "tests" in path.parts or "__pycache__" in path.parts or not path.is_file():
            continue
        if path.suffix != ".py" and path.name != "CAD_INSTRUCTIONS.md":
            continue
        digest.update(path.relative_to(root).as_posix().encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def tools_hash(tools):
    return hashlib.sha256(json.dumps(tools, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def instructions_hash(text):
    return hashlib.sha256(text.encode()).hexdigest()


class RuntimeIdentity:
    def __init__(self, role, *, tools=None, instructions=None, root=ROOT):
        self.root = Path(root).resolve()
        self.role, self.tools = role, tools
        self.started_utc = datetime.now(UTC).isoformat()
        self.source_sha256 = source_hash(self.root)
        self.tools_sha256 = tools_hash(tools) if tools is not None else None
        path = self.root / "backend/v2/CAD_INSTRUCTIONS.md"
        self.instructions = instructions if instructions is not None else path.read_text(encoding="utf-8")
        self.instructions_sha256 = instructions_hash(self.instructions)
        self.ensure_current()

    def ensure_current(self):
        expected_root = os.getenv("PROMPTCAD_WORKSPACE")
        expected_source = os.getenv("PROMPTCAD_EXPECTED_SOURCE")
        expected_tools = os.getenv("PROMPTCAD_EXPECTED_TOOLS")
        current_instructions = (self.root / "backend/v2/CAD_INSTRUCTIONS.md").read_text(encoding="utf-8")
        mismatch = (
            (expected_root and Path(expected_root).resolve() != self.root)
            or source_hash(self.root) != self.source_sha256
            or (expected_source and expected_source != self.source_sha256)
            or instructions_hash(current_instructions) != self.instructions_sha256
        )
        if self.tools is not None:
            mismatch = mismatch or tools_hash(self.tools) != self.tools_sha256
            mismatch = mismatch or (expected_tools and expected_tools != self.tools_sha256)
            mismatch = mismatch or not STANDARD_TOOLS <= {t["name"] for t in self.tools}
        if mismatch:
            raise WorkspaceError(
                "The CAD runtime does not match the current application source, instructions or tools. "
                "Finish/cancel the current task, close Prompt to CAD and reopen it using this checkout's shortcut. "
                "No new CAD turn can use the stale runtime.", "runtime_mismatch")

    def environment(self):
        values = {"PROMPTCAD_WORKSPACE": str(self.root), "PROMPTCAD_EXPECTED_SOURCE": self.source_sha256,
                  "PYTHONNOUSERSITE": "1"}
        if self.tools_sha256:
            values["PROMPTCAD_EXPECTED_TOOLS"] = self.tools_sha256
        return values

    def report(self, *, private=False):
        result = {"role": self.role, "pid": os.getpid(), "parent_pid": os.getppid(),
            "started_utc": self.started_utc, "source_sha256": self.source_sha256,
            "instructions_sha256": self.instructions_sha256, "tools_sha256": self.tools_sha256,
            "tool_names": [t["name"] for t in self.tools] if self.tools is not None else [],
            "instructions_include_standard_parts": "cq_warehouse" in self.instructions and "cad_standard_part" in self.instructions}
        if private:
            result.update(source_root=str(self.root), executable=sys.executable,
                base_executable=getattr(sys, "_base_executable", sys.executable), cwd=os.getcwd(),
                module_search_paths=list(sys.path), module_files={name: str(module.__file__)
                    for name, module in list(sys.modules.items()) if name.startswith("backend.") and getattr(module, "__file__", None)})
        return result

    def verify_peer(self, report, role):
        self.ensure_current()
        if (report.get("role") != role or report.get("source_sha256") != self.source_sha256
            or report.get("instructions_sha256") != self.instructions_sha256
            or (role == "mcp" and report.get("tools_sha256") != self.tools_sha256)):
            raise WorkspaceError("The CAD subprocess loaded different application code or tools. Restart Prompt to CAD.", "runtime_mismatch")

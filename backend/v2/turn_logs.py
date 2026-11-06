"""Project-local evidence of CAD tool use and the assistant's stated decisions."""

import hashlib
import json
import math
import os
import re
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from backend.native.contracts import WorkspaceError
from backend.native.documents import write_json

SECRET_KEYS = re.compile(r"(?:api.?key|private.?key|token|auth|password|credential|secret|cookie|image_data|account|session|environment)", re.IGNORECASE)
SECRET_TEXT = re.compile(
    r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----"
    r"|\bBearer\s+[^\s\"'<>]+|\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{20,})"
    r"|\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", re.DOTALL)
ASSIGNMENT = re.compile(r"(?i)(\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|secret|authorization)\b[\"']?\s*[:=]\s*)[^\s,;\n]+")
LOCAL_PATH = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\n\"<>]*|(?:/home/|/Users/)[^\s\"<>]+")
EMAIL = re.compile(r"[\w.+%-]+@[\w.-]+\.[A-Za-z]{2,}")


def safe(value, depth=0):
    """Bound diagnostic payloads; exclude credentials, images, code and local paths."""
    if depth > 8:
        return "[depth limit]"
    if isinstance(value, dict):
        result = {}
        for key, child in list(value.items())[:80]:
            key = str(key)
            if SECRET_KEYS.search(key):
                result[key] = "[redacted]"
            elif key in ("source", "script", "recipe"):
                text = json.dumps(child, sort_keys=True, default=lambda _: "[unsupported]")
                result[key] = {"sha256": hashlib.sha256(text.encode()).hexdigest(), "characters": len(text), "content": "[code omitted]"}
            elif key in ("path", "project_dir", "local_path", "folder_path", "executable"):
                result[key] = "[local path omitted]"
            else:
                result[key] = safe(child, depth + 1)
        if len(value) > 80:
            result["omitted_fields"] = len(value) - 80
        return result
    if isinstance(value, (list, tuple)):
        return [safe(child, depth + 1) for child in value[:40]] + ([{"omitted_items": len(value) - 40}] if len(value) > 40 else [])
    if isinstance(value, str):
        value = SECRET_TEXT.sub("[redacted]", value)
        value = ASSIGNMENT.sub(r"\1[redacted]", value)
        value = EMAIL.sub("[email omitted]", value)
        return LOCAL_PATH.sub("[local path omitted]", value)[:4000]
    if value is None or type(value) in (bool, int):
        return value
    if type(value) is float:
        return value if math.isfinite(value) else "[non-finite]"
    return "[unsupported value]"


def folder(project, task_id):
    if not isinstance(task_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", task_id):
        raise WorkspaceError("Invalid turn log identifier.", "invalid_task")
    project = Path(project).resolve()
    path = project / "logs" / "turns" / task_id
    if path.resolve() != path:
        raise WorkspaceError("Turn logs cannot use filesystem links.", "invalid_project")
    return path


def text_block(value):
    text = str(value)
    fence = "`" * max(3, 1 + max((len(run) for run in re.findall(r"`+", text)), default=0))
    return f"{fence}text\n{text}\n{fence}"


def record_folder(project, task):
    relative = Path(task["turn_log"])
    if len(relative.parts) != 3 or relative.parts[:2] != ("logs", "turns"):
        raise WorkspaceError("Invalid project turn log path.", "invalid_project")
    return folder(project, relative.name)


class TurnLog:
    def __init__(self, project, task, project_id, notify=lambda message: None):
        self.folder = folder(project, task["task_id"])
        self.lock = threading.RLock()
        self.notify = notify
        self.error = None
        self.closed = False
        self.sequence = 0
        self.data = safe({"schema_version": 1, "project_id": project_id,
            **{key: task.get(key) for key in ("task_id", "document_id", "conversation_id", "base_revision_id", "started_at", "model")},
            "request": task.get("prompt", ""), "status": "running", "decisions": [], "tools": [],
            "phase_timings": {},
            "application_runtime": task.get("application_runtime"),
            "catalog_evidence": {},
            "agent_skills": {"available": [], "loads": []},
            "evidence": "Observed tool calls and concise assistant-stated reasons; not hidden reasoning or proof that a stated reason is correct."})
        try:
            self.folder.mkdir(parents=True, exist_ok=False)
        except OSError as error:
            raise WorkspaceError("Cannot create the project turn log. Check folder access and free disk space.", "log_unavailable") from error
        self.event("turn_started", {"task_id": task["task_id"]})
        self.checkpoint()

    def failed(self, error):
        if self.error is None:
            self.error = type(error).__name__
            self.notify("Project turn logging failed; check folder access and free disk space. CAD results are not changed by this logging error.")

    def event(self, kind, payload):
        if self.closed:
            return
        try:
            self.sequence += 1
            entry = {"sequence": self.sequence, "time_utc": datetime.now(UTC).isoformat(), "event": kind, **safe(payload)}
            with (self.folder / "events.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(entry, ensure_ascii=False, allow_nan=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as error:
            self.failed(error)

    def tool_started(self, name, arguments, library_operation=False, generator_id=None):
        with self.lock:
            call = {"call_id": uuid4().hex, "name": name, "started_at": time.time(),
                    "status": "running", "library_operation": library_operation, "generator_id": safe(generator_id),
                    "decision_id": self.data["decisions"][-1]["decision_id"] if self.data["decisions"] else None}
            if name == "cad_skills":
                call["skill_action"] = safe(arguments.get("action"))
                call["skill_id"] = safe(arguments.get("skill_id"))
            if name in ("cad_catalog", "cad_catalog_insert"):
                call["catalog_request"] = safe({key: arguments[key] for key in
                    ("action", "query", "category", "limit", "offset", "catalog_id", "fingerprint") if key in arguments})
            self.data["tools"].append(call)
            self.event("tool_started", {**call, "arguments": arguments})
            self.checkpoint()
            return call

    def tool_finished(self, call, result=None, error=None):
        with self.lock:
            call.update(status="failed" if error is not None else "succeeded", elapsed_seconds=max(0, time.time() - call["started_at"]))
            phase = {
                "cad_catalog": "catalog_search",
                "cad_catalog_insert": "catalog_import",
                "cad_script": "script_execution",
                "cad_restructure": "script_execution",
                "cad_validate": "final_validation",
            }.get(call["name"], "geometry_worker" if call["name"] in ("cad_apply", "cad_apply_batch", "cad_standard_part", "cad_appearance", "cad_engineering") else None)
            if phase:
                self.phase_finished(phase, call["elapsed_seconds"], failed=error is not None)
            if error is not None:
                call["error"] = safe({"code": getattr(error, "code", "tool_failed"), "message": str(error)})
                event_result = None
            elif call["name"] == "cad_skills":
                if call.get("skill_action") == "read":
                    skill = result.get("skill", {}) if isinstance(result, dict) else {}
                    load = {key: safe(skill.get(key)) for key in ("id", "version", "sha256")}
                    load["status"] = "loaded" if all(load.get(key) for key in ("id", "version", "sha256")) else "invalid_result"
                    call.update({"skill_version": load.get("version"), "skill_sha256": load.get("sha256"), "load_status": load["status"]})
                    self.data.setdefault("agent_skills", {"available": [], "loads": []})["loads"].append(load)
                    event_result = {**load, "content": "[skill instructions omitted from log]"}
                else:
                    available = result.get("available", []) if isinstance(result, dict) else []
                    event_result = {"available": [{key: safe(item.get(key)) for key in ("id", "version", "sha256", "available", "error") if key in item}
                                                   for item in available if isinstance(item, dict)]}
            elif call["name"] == "cad_catalog_insert":
                call["created_component_ids"] = [safe(identity) for identity in result["created_component_ids"]]
                event_result = result
            elif call["name"] == "cad_catalog" and call["catalog_request"].get("action") == "search":
                call["result_ids"] = [entry["catalog_id"] for entry in result["results"]]
                event_result = result
            elif error is None:
                event_result = result
            self.event("tool_" + call["status"], {**call, **({"result": event_result} if error is None else {})})
            self.checkpoint()

    def skill_availability(self, descriptor):
        with self.lock:
            available = safe(descriptor.get("available", [])) if isinstance(descriptor, dict) else []
            evidence = self.data.setdefault("agent_skills", {"available": [], "loads": []})
            if evidence.get("available") != available:
                evidence["available"] = available
                self.event("skills_available", {"skills": available})
                self.checkpoint()

    def phase_started(self, name):
        with self.lock:
            phase = self.data.setdefault("phase_timings", {}).setdefault(name, {
                "elapsed_seconds": 0.0, "calls": 0, "failed_calls": 0, "failed_elapsed_seconds": 0.0
            })
            phase["_started_at"] = time.time()

    def phase_finished(self, name, elapsed_seconds, failed=False):
        phase = self.data.setdefault("phase_timings", {}).setdefault(name, {
            "elapsed_seconds": 0.0, "calls": 0, "failed_calls": 0, "failed_elapsed_seconds": 0.0
        })
        elapsed_seconds = max(0, elapsed_seconds)
        phase["elapsed_seconds"] = round(phase.get("elapsed_seconds", 0.0) + elapsed_seconds, 6)
        phase["calls"] = phase.get("calls", 0) + 1
        phase["failed_calls"] = phase.get("failed_calls", 0) + int(failed)
        if failed:
            phase["failed_elapsed_seconds"] = round(
                phase.get("failed_elapsed_seconds", 0.0) + elapsed_seconds, 6
            )
        phase.pop("_started_at", None)

    def phase(self, name, elapsed_seconds, failed=False, **counts):
        with self.lock:
            self.phase_finished(name, elapsed_seconds, failed=failed)
            phase = self.data["phase_timings"][name]
            for key, value in counts.items():
                phase[key] = phase.get(key, 0) + value
            self.event("phase_finished", {"phase": name, **phase})
            self.checkpoint()

    def tool_elapsed(self):
        return sum(
            call.get("elapsed_seconds", 0)
            for call in self.data.get("tools", [])
            if call.get("status") in ("succeeded", "failed")
        )

    def decision(self, value):
        with self.lock:
            self.data["decisions"].append(safe(value))
            self.event("decision_reported", value)
            self.checkpoint()

    def catalog_evidence(self, kind, payload):
        with self.lock:
            self.data.setdefault("catalog_evidence", {})[kind] = safe(payload)
            self.event("catalog_" + kind, payload)
            self.checkpoint()

    def catalog_usage(self):
        evidence = self.data.get("catalog_evidence", {})
        tools = self.data["tools"]
        searches = [call for call in tools if call["name"] == "cad_catalog"
                    and call.get("catalog_request", {}).get("action") == "search"]
        insertions = [call for call in tools if call["name"] == "cad_catalog_insert"]
        accepted = {identity for identity in self.data.get("created_components") or () if isinstance(identity, str)} if self.data.get("result_revision_id") else set()
        return {
            "discovery": evidence.get("discovery"),
            "context_submitted": evidence.get("context_submitted"),
            "tool_list_returned": evidence.get("tool_list_returned"),
            "search_calls": len(searches),
            "successful_search_calls": sum(call["status"] == "succeeded" for call in searches),
            "insertion_attempts": len(insertions),
            "insertions": [{"catalog_id": call.get("catalog_request", {}).get("catalog_id"), "status": call["status"],
                            "candidate_component_ids": call.get("created_component_ids", []),
                            "accepted_component_ids": [identity for identity in call.get("created_component_ids", []) if identity in accepted]}
                           for call in insertions],
            "explanation_status": "provided" if any("catalog" in decision for decision in self.data["decisions"]) else "not_provided",
        }

    def usage(self):
        tools = self.data["tools"]
        attempts = [t for t in tools if t["library_operation"]]
        succeeded = [t for t in attempts if t["status"] == "succeeded"]
        return {"discovery_calls": sum(t["name"] == "cad_standard_parts" for t in tools),
            "generation_attempts": len(attempts), "successful_generation_calls": len(succeeded),
            "successful_calls_in_accepted_turn": len(succeeded) if self.data.get("result_revision_id") else 0,
            "acceptance": "accepted" if self.data.get("result_revision_id") else "unknown" if self.data["status"] in ("running", "interrupted") else "not_accepted",
            "generator_ids": sorted({t["generator_id"] for t in attempts if isinstance(t["generator_id"], str)}),
            "explanation_status": "provided" if self.data["decisions"] else "not_provided"}

    def checkpoint(self):
        try:
            self.data["cq_warehouse"] = self.usage()
            self.data["step_catalog"] = self.catalog_usage()
            self.data["agent_skills_usage"] = {
                "available_ids": [item.get("id") for item in self.data.get("agent_skills", {}).get("available", []) if item.get("version")],
                "loaded": list(self.data.get("agent_skills", {}).get("loads", [])),
            }
            write_json(self.folder / "summary.json", self.data)
            lines = ["# CAD turn log", "", "Task: " + self.data["task_id"],
                "Started (UTC): " + datetime.fromtimestamp(self.data["started_at"], UTC).isoformat(),
                "Status: " + self.data["status"], "", "## Request", "", text_block(self.data["request"]),
                "", "## cq_warehouse: observed use", "", text_block(json.dumps(self.data["cq_warehouse"], indent=2)),
                "", "## STEP catalog: observed access and use", "", text_block(json.dumps(self.data["step_catalog"], indent=2)),
                "", "## Agent skills: availability and loads", "", text_block(json.dumps(self.data["agent_skills_usage"], indent=2)),
                "", "## Phase timings", "", text_block(json.dumps(self.data.get("phase_timings", {}), indent=2)),
                "", "## Stated decisions", "", self.data["evidence"], ""]
            for decision in self.data["decisions"]:
                lines.extend(["### Approach", "", text_block(decision["summary"]),
                    "", "cq_warehouse choice: " + decision["cq_warehouse"]["choice"], "",
                    text_block(decision["cq_warehouse"]["reason"]), "", "Alternatives:", "",
                    text_block("\n".join(decision["alternatives"]) or "None reported.")])
                if "catalog" in decision:
                    lines.extend(["", "STEP catalog choice", "", text_block(json.dumps(decision["catalog"], ensure_ascii=False))])
            if not self.data["decisions"]:
                lines.append("No structured decision summary was provided. Inspect the final response if present; the logger does not infer a reason from tool absence.")
            lines.extend(["", "## Outcome", "", text_block(self.data.get("message") or "No final response recorded yet."),
                "", "Accepted revision: " + str(self.data.get("result_revision_id") or "not recorded")])
            lines.extend(["", "## Tool calls", ""])
            lines.extend(text_block(json.dumps(call, ensure_ascii=False)) for call in self.data["tools"])
            lines.extend(["", "Arguments and bounded results are in events.jsonl. Code and image payloads are omitted; known credential patterns and local paths are redacted.",
                          "These files remain private project data. Redaction is not a guarantee that arbitrary project text is safe to publish."])
            temporary = self.folder / (uuid4().hex + ".tmp")
            try:
                temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
                os.replace(temporary, self.folder / "summary.md")
            finally:
                temporary.unlink(missing_ok=True)
        except OSError as error:
            self.failed(error)

    def finish(self, task):
        with self.lock:
            self.data.update(safe({key: task.get(key) for key in ("status", "completed_at", "result_revision_id", "message", "validation", "affected_components", "created_components", "consumed_components")}))
            if task.get("created_components") is not None:
                self.data["created_components"] = [safe(identity) for identity in task["created_components"] if isinstance(identity, str)]
            self.event("turn_finished", {"status": task["status"], "result_revision_id": task.get("result_revision_id")})
            self.checkpoint()
            self.closed = True

    @classmethod
    def recover(cls, project, task):
        path = record_folder(project, task)
        if not (path / "summary.json").is_file():
            return
        log = cls.__new__(cls)
        log.folder, log.lock, log.notify = path, threading.RLock(), lambda message: None
        log.error, log.closed, log.sequence = None, False, 0
        log.data = json.loads((path / "summary.json").read_text(encoding="utf-8"))
        if not isinstance(log.data, dict) or not isinstance(log.data.get("tools"), list):
            raise TypeError("Invalid project turn log summary.")
        events = path / "events.jsonl"
        if events.is_file():
            with events.open(encoding="utf-8", errors="replace") as stream:
                for line in stream:
                    try:
                        entry = json.loads(line)
                        if isinstance(entry, dict):
                            log.sequence = max(log.sequence, entry.get("sequence", 0))
                    except (ValueError, TypeError):
                        continue
            with events.open("rb+") as stream:
                stream.seek(0, os.SEEK_END)
                if stream.tell():
                    stream.seek(-1, os.SEEK_END)
                    if stream.read(1) != b"\n":
                        stream.write(b"\n")
        for call in log.data.get("tools", []):
            if not isinstance(call, dict):
                raise TypeError("Invalid project turn log tool record.")
            if call["status"] == "running":
                call["status"] = "interrupted"
        log.finish({**task, "completed_at": time.time()})

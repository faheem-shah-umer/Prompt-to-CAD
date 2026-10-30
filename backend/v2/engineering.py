"""Revision-owned appearance and engineering information, separate from geometry."""

import copy
import math
import re
from uuid import uuid4

from backend.native.contracts import WorkspaceError


def number(value):
    if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 1e9:
        raise WorkspaceError("Use a finite engineering value.", "invalid_metadata")
    return value


def vector(value):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise WorkspaceError("Use three coordinates.", "invalid_metadata")
    return [number(v) for v in value]


def rgb(value):
    if isinstance(value, str) and len(value) == 7 and value.startswith("#"):
        try:
            value = [int(value[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        except ValueError:
            pass
    result = vector(value)
    if any(v < 0 or v > 1 for v in result):
        raise WorkspaceError("Colours use RGB values from zero to one or #RRGGBB.", "invalid_colour")
    return result


def appearance(snapshot, identities, color=None, source_colors=False):
    candidate = copy.deepcopy(snapshot)
    parts = {p["instance_id"]: p for p in candidate["components"]}
    if not identities or any(i not in parts for i in identities):
        raise WorkspaceError("Choose current components for colour editing.", "stale_selection")
    value = rgb(color) if not source_colors else None
    for identity in identities:
        part = parts[identity]
        if source_colors:
            if part.get("representation") != "mesh":
                raise WorkspaceError("Source-colour reset applies to imported meshes.", "unsupported_representation")
            part.pop("color_override", None)
        else:
            part["color"] = list(value)
            if part.get("representation") == "mesh":
                part["color_override"] = list(value)
    return candidate


def edit(snapshot, record, action="upsert"):
    candidate = copy.deepcopy(snapshot)
    records = candidate.setdefault("engineering", [])
    identity = record.get("id") or uuid4().hex
    if not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", identity):
        raise WorkspaceError("Use a valid engineering record ID.", "invalid_metadata")
    existing = next((r for r in records if r["id"] == identity), None)
    if action == "remove":
        if not existing:
            raise WorkspaceError("The engineering record no longer exists.", "stale_selection")
        candidate["engineering"] = [r for r in records if r["id"] != identity]
        return candidate
    if action != "upsert" or record.get("kind") not in ("dimension", "label", "note"):
        raise WorkspaceError("Use dimension, label or note records.", "invalid_metadata")
    parts = {p["instance_id"]: p for p in snapshot["components"]}
    target = record.get("instance_id")
    if target not in parts:
        raise WorkspaceError("Choose a current component for this record.", "stale_selection")
    item = {"id": identity, "kind": record["kind"], "instance_id": target,
            "text": str(record.get("text", ""))[:2000], "units": record.get("units", "mm")}
    if item["units"] not in ("mm", "deg", "unitless"):
        raise WorkspaceError("Engineering units must be mm, deg or unitless.", "invalid_metadata")
    if item["kind"] in ("label", "note") and not item["text"].strip():
        raise WorkspaceError("Labels and notes need text.", "invalid_metadata")
    if record.get("parameter") and record.get("measurement"):
        raise WorkspaceError("Bind a dimension to a parameter or a measurement, not both.", "invalid_metadata")
    item["anchor"] = copy.deepcopy(record.get("anchor", {"kind": "body"}))
    anchor = item["anchor"]
    if anchor.get("kind") not in ("body", "face", "edge", "vertex"):
        raise WorkspaceError("Choose a body, face, edge or vertex anchor.", "invalid_metadata")
    if anchor["kind"] != "body":
        key = {"face": "faces", "edge": "edges", "vertex": "vertices"}[anchor["kind"]]
        if type(anchor.get("index")) is not int or not 1 <= anchor["index"] <= parts[target]["topology"].get(key, 0):
            raise WorkspaceError("This annotation anchor is stale.", "stale_selection")
    anchor["asset_hash"] = parts[target]["asset_hash"]
    if "position" in anchor:
        anchor["position"] = vector(anchor["position"])
    item["status"] = "current"
    if item["kind"] == "dimension":
        if "nominal" not in record and not record.get("parameter"):
            raise WorkspaceError("Provide a nominal dimension or bind an existing parameter/measurement.", "missing_dimensions")
        item["nominal"] = number(record.get("nominal", 0))
        item["verification"] = "declared_unverified"
        if record.get("parameter"):
            name = record["parameter"]
            if name not in parts[target].get("parameters", {}):
                raise WorkspaceError("Bind dimensions to an existing named parameter.", "missing_parameter")
            item.update(parameter=name, nominal=parts[target]["parameters"][name], verification="named_parameter")
        if record.get("measurement"):
            item["measurement"] = copy.deepcopy(record["measurement"])
            item["verification"] = "measurement_pending"
        tolerance = record.get("tolerance")
        if tolerance:
            mode = tolerance.get("mode")
            if mode == "plus_minus":
                lower = number(tolerance.get("minus", tolerance.get("value")))
                upper = number(tolerance.get("plus", tolerance.get("value")))
                if min(lower, upper) < 0:
                    raise WorkspaceError("Tolerance magnitudes cannot be negative.", "invalid_metadata")
                item["tolerance"] = {"mode": mode, "minus": lower, "plus": upper}
            elif mode == "limits":
                lower, upper = number(tolerance.get("lower")), number(tolerance.get("upper"))
                if lower > upper:
                    raise WorkspaceError("The lower limit exceeds the upper limit.", "invalid_metadata")
                item["tolerance"] = {"mode": mode, "lower": lower, "upper": upper}
                item["within_limits"] = lower <= item["nominal"] <= upper
            else:
                raise WorkspaceError("Use plus_minus or limits tolerances.", "invalid_metadata")
    candidate["engineering"] = [r for r in records if r["id"] != identity] + [item]
    return candidate


def refresh_anchors(before, after):
    parts = {p["instance_id"]: p for p in after["components"]}
    for record in after.get("engineering", []):
        part = parts.get(record["instance_id"])
        anchor = record.get("anchor", {})
        if not part or (anchor.get("kind") != "body" and anchor.get("asset_hash") != part["asset_hash"]):
            record["status"] = "stale"
        elif record.get("kind") == "dimension" and record.get("parameter"):
            value = part.get("parameters", {}).get(record["parameter"])
            if value is None:
                record["status"] = "stale"
            else:
                record["nominal"] = value
                if record.get("tolerance", {}).get("mode") == "limits":
                    record["within_limits"] = record["tolerance"]["lower"] <= value <= record["tolerance"]["upper"]
        elif record.get("measurement"):
            references = record.get("measurement_assets", {})
            if any(identity not in parts or signature != {"asset_hash": parts[identity]["asset_hash"], "matrix": parts[identity]["matrix"]}
                   for identity, signature in references.items()):
                record["status"] = "stale"


def validate_records(snapshot):
    parts = {p["instance_id"]: p for p in snapshot["components"]}
    records = snapshot.get("engineering", [])
    if not isinstance(records, list) or len(records) > 1000:
        raise WorkspaceError("A revision supports at most 1,000 engineering records.", "invalid_metadata")
    seen = set()
    for record in records:
        if not isinstance(record, dict):
            raise WorkspaceError("Engineering records must be objects.", "invalid_metadata")
        identity = record.get("id")
        if not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", identity) or identity in seen:
            raise WorkspaceError("Engineering record IDs must be valid and distinct.", "invalid_metadata")
        seen.add(identity)
        if (record.get("kind") not in ("dimension", "label", "note") or record.get("status") not in ("current", "stale")
                or record.get("units") not in ("mm", "deg", "unitless")
                or not isinstance(record.get("text"), str) or len(record["text"]) > 2000):
            raise WorkspaceError("Invalid engineering record metadata.", "invalid_metadata")
        part = parts.get(record.get("instance_id"))
        anchor = record.get("anchor", {})
        if not isinstance(anchor, dict):
            raise WorkspaceError("Annotation anchors must be objects.", "invalid_metadata")
        kind = anchor.get("kind")
        if kind not in ("body", "face", "edge", "vertex"):
            raise WorkspaceError("Invalid annotation anchor kind.", "invalid_metadata")
        if record["status"] == "current":
            if not part:
                raise WorkspaceError("A current annotation needs a current component.", "stale_selection")
            if kind != "body":
                key = {"face": "faces", "edge": "edges", "vertex": "vertices"}[kind]
                if (anchor.get("asset_hash") != part["asset_hash"] or type(anchor.get("index")) is not int
                        or not 1 <= anchor["index"] <= part["topology"].get(key, 0)):
                    raise WorkspaceError("A current annotation has stale topology.", "stale_selection")
        if "position" in anchor:
            vector(anchor["position"])
        if record["kind"] == "dimension":
            number(record.get("nominal"))
            tolerance = record.get("tolerance")
            if tolerance:
                if not isinstance(tolerance, dict):
                    raise WorkspaceError("Tolerances must be structured records.", "invalid_metadata")
                if tolerance.get("mode") == "plus_minus":
                    if min(number(tolerance.get("minus")), number(tolerance.get("plus"))) < 0:
                        raise WorkspaceError("Tolerance magnitudes cannot be negative.", "invalid_metadata")
                elif tolerance.get("mode") == "limits":
                    if number(tolerance.get("lower")) > number(tolerance.get("upper")):
                        raise WorkspaceError("Tolerance limits are reversed.", "invalid_metadata")
                else:
                    raise WorkspaceError("Unsupported tolerance form.", "invalid_metadata")
    return {"passed": True, "records": len(records), "standards_compliance": "not evaluated"}

"""Frozen selection sets and component/entity write permissions."""

import copy
from backend.native.contracts import WorkspaceError


def normalize(selection, snapshot, project_id, inspect):
    if not selection:
        return None
    if (
        selection.get("revision_id") != snapshot.get("revision_id")
        or selection.get("document_id", snapshot["document_id"])
        != snapshot["document_id"]
        or selection.get("project_id", project_id) != project_id
    ):
        raise WorkspaceError(
            "Selection is stale. Select geometry in the current document.",
            "stale_selection",
        )
    raw = selection.get("entities", [selection])
    if not isinstance(raw, list) or not 1 <= len(raw) <= 256:
        raise WorkspaceError("Select between 1 and 256 geometry entities.")
    parts = {p["instance_id"]: p for p in snapshot["components"]}
    entities, seen = [], set()
    for value in raw:
        entity = copy.deepcopy(value)
        part = parts.get(entity.get("instance_id"))
        if (
            not part
            or entity.get("asset_hash", part["asset_hash"]) != part["asset_hash"]
        ):
            raise WorkspaceError(
                "A selected component changed or is missing.", "stale_selection"
            )
        kind, index = entity.get("kind", "body"), entity.get("index", 0)
        counts = {
            "face": "faces",
            "edge": "edges",
            "vertex": "vertices",
            "region": "triangles",
        }
        count = part["topology"].get(counts.get(kind, ""), 0)
        if kind not in ("body", *counts) or (
            kind != "body" and (type(index) is not int or not 1 <= index <= count)
        ):
            raise WorkspaceError(
                "Invalid selected topology reference.", "stale_selection"
            )
        if kind == "region":
            triangles = entity.get("triangle_indices", [index])
            if (
                not isinstance(triangles, list)
                or not triangles
                or len(triangles) > 200000
                or any(type(i) is not int or not 1 <= i <= count for i in triangles)
            ):
                raise WorkspaceError("Invalid selected mesh region.", "stale_selection")
            entity["triangle_indices"] = sorted(set(triangles))
        key = (
            part["instance_id"],
            kind,
            index,
            tuple(entity.get("triangle_indices", [])),
        )
        if key in seen:
            continue
        seen.add(key)
        entity.update(
            instance_id=part["instance_id"],
            kind=kind,
            index=index,
            body_id=part["definition_id"],
            asset_hash=part["asset_hash"],
            local_to_world=part["matrix"],
            units="mm",
            measurements=part["metrics"],
        )
        if kind != "body":
            info = inspect(part["instance_id"], index - 1)
            entries = info.get(
                {
                    "face": "faces",
                    "edge": "edges",
                    "vertex": "vertices",
                    "region": "regions",
                }[kind],
                [],
            )
            if entries:
                entity["local_entity"] = entries[0]
                point = entries[0].get("centre", entries[0].get("point"))
                if point:
                    pose = part["matrix"]
                    entity["world_position_mm"] = [
                        sum(pose[r * 4 + a] * point[a] for a in range(3))
                        + pose[r * 4 + 3]
                        for r in range(3)
                    ]
        entities.append(entity)
        # Legacy edge selection carried extra edges in a single object.
        if kind == "edge":
            for edge in value.get("edge_indices", []):
                if type(edge) is not int or not 1 <= edge <= count:
                    raise WorkspaceError("Invalid selected edge.", "stale_selection")
                if (part["instance_id"], "edge", edge, ()) not in seen:
                    extra = copy.deepcopy(entity)
                    extra.update(
                        index=edge,
                        local_entity=inspect(part["instance_id"], edge - 1).get(
                            "edges", [{}]
                        )[0],
                    )
                    entities.append(extra)
                    seen.add((part["instance_id"], "edge", edge, ()))
    bodies = {e["instance_id"] for e in entities if e["kind"] == "body"}
    entities = [
        e for e in entities if e["kind"] == "body" or e["instance_id"] not in bodies
    ]
    result = {
        "version": 2,
        "project_id": project_id,
        "document_id": snapshot["document_id"],
        "revision_id": snapshot.get("revision_id"),
        "entities": entities,
        "units": "mm",
    }
    if len(entities) == 1:
        result.update(entities[0])
    return result


def check_command(selection, candidate, command=None, script_target=None):
    if not selection:
        return
    target = command["instance_id"] if command else script_target
    entities = [e for e in selection["entities"] if e["instance_id"] == target]
    if not entities:
        raise WorkspaceError(
            "The operation targets a component outside the submitted selection.",
            "scope_violation",
        )
    if any(e["kind"] == "body" for e in entities):
        return
    current = next(p for p in candidate["components"] if p["instance_id"] == target)
    if any(e["asset_hash"] != current["asset_hash"] for e in entities):
        raise WorkspaceError(
            "Selected topology changed. Submit a fresh selection for further edits to this component.",
            "stale_selection",
        )
    if not command:
        raise WorkspaceError(
            "Scripts require a body selection; selected faces and regions cannot be widened silently.",
            "scope_violation",
        )
    kind = command["type"]
    if kind in ("offset_face", "face_holes"):
        requested, allowed = (
            {command["face_index"]},
            {e["index"] for e in entities if e["kind"] == "face"},
        )
    elif kind in ("fillet", "chamfer"):
        requested, allowed = (
            set(command["edge_indices"]),
            {e["index"] for e in entities if e["kind"] == "edge"},
        )
    elif kind in ("mesh_color", "mesh_region_move", "mesh_separate"):
        requested = set(command.get("triangle_indices", []))
        allowed = {
            i for e in entities if e["kind"] == "region" for i in e["triangle_indices"]
        }
    else:
        raise WorkspaceError(
            "This operation requires selecting the whole component.", "scope_violation"
        )
    if not requested or not requested <= allowed:
        raise WorkspaceError(
            "The operation references geometry outside the submitted selection.",
            "scope_violation",
        )

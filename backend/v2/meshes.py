"""Mesh representations remain meshes; no invented sketch or solid history."""

import copy
import hashlib
import json
import io
import math
import os
from pathlib import Path
from uuid import uuid4

import numpy as np
import trimesh
from backend.native.contracts import WorkspaceError
from backend.native.documents import asset_path

IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0]
MAX_FACES = 200000


def checked(mesh):
    if not isinstance(mesh, trimesh.Trimesh) or not 1 <= len(mesh.faces) <= MAX_FACES:
        raise WorkspaceError("Use a triangular mesh containing 1–200,000 faces.")
    if not np.isfinite(mesh.vertices).all() or np.abs(mesh.vertices).max() > 1e8 or len(mesh.vertices) > 600000:
        raise WorkspaceError("The mesh contains invalid coordinates or exceeds the size limit.")
    if np.any(mesh.area_faces < 1e-12):
        raise WorkspaceError("The mesh contains degenerate triangles. Repair the source before importing.")
    return mesh


def metrics(mesh):
    return {
        "dimensions_mm": mesh.extents.tolist(),
        "bounds_mm": mesh.bounds.tolist(),
        "surface_area_mm2": float(mesh.area),
        "volume_mm3": abs(float(mesh.volume)) if mesh.is_watertight and mesh.is_winding_consistent else None,
        "watertight": bool(mesh.is_watertight),
        "winding_consistent": bool(mesh.is_winding_consistent),
        "triangle_count": len(mesh.faces),
        "solid_count": 0,
        "representation": "mesh",
    }


def store(folder, mesh):
    checked(mesh)
    try:
        visual = mesh.visual.to_color() if hasattr(mesh.visual, "to_color") else mesh.visual
        colors = np.asarray(visual.face_colors, dtype=np.uint8)
    except Exception:
        colors = np.tile([155, 175, 205, 255], (len(mesh.faces), 1))
    data = json.dumps(
        {"vertices": mesh.vertices.tolist(), "triangles": mesh.faces.tolist(), "colors": colors[:, :3].tolist()},
        allow_nan=False,
        separators=(",", ":"),
    ).encode()
    digest = hashlib.sha256(data).hexdigest()
    path = Path(folder) / "assets" / (digest + ".mesh.json")
    path.parent.mkdir(exist_ok=True)
    if not path.exists():
        temporary = path.with_suffix("." + uuid4().hex + ".tmp")
        try:
            with temporary.open("wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    return {
        "representation": "mesh",
        "mesh": "assets/" + path.name,
        "asset_hash": digest,
        "metrics": metrics(mesh),
        "topology": {
            "regions": len(mesh.faces),
            "triangles": len(mesh.faces),
            "vertices": len(mesh.vertices),
            "faces": 0,
            "edges": 0,
        },
    }


def load(folder, part):
    path = asset_path(folder, part["mesh"])
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != part["asset_hash"]:
        raise WorkspaceError("Mesh asset checksum mismatch.", "asset_integrity")
    parsed = json.loads(data)
    mesh = trimesh.Trimesh(vertices=parsed["vertices"], faces=parsed["triangles"], process=False)
    mesh.visual.face_colors = parsed["colors"]
    return checked(mesh)


def import_mesh(path, folder, mm_per_unit):
    if not math.isfinite(mm_per_unit) or not 1e-6 <= mm_per_unit <= 1e6:
        raise WorkspaceError("Specify a valid conversion from source units to millimetres.")
    path = Path(path)
    if path.stat().st_size > 100 * 1024 * 1024:
        raise WorkspaceError("Mesh imports are limited to 100 MB.")
    if path.suffix.lower() not in (".glb", ".stl", ".obj", ".ply"):
        raise WorkspaceError("Supported mesh formats: GLB, STL, OBJ and PLY.")
    # Standalone payloads only: external OBJ materials and glTF resources are not resolved.
    scene = trimesh.load_scene(
        file_obj=io.BytesIO(path.read_bytes()), file_type=path.suffix[1:], resolver=None, allow_remote=False
    )
    components = []
    for node in scene.graph.nodes_geometry:
        transform, geometry_name = scene.graph[node]
        mesh = scene.geometry[geometry_name].copy()
        mesh.apply_transform(transform)
        mesh.apply_scale(mm_per_unit)
        pid = uuid4().hex[:16]
        components.append(
            {
                "instance_id": pid,
                "definition_id": pid,
                "parent_id": None,
                "name": str(node)[:120],
                "matrix": IDENTITY,
                "color": [0.6, 0.7, 0.8],
                "parameters": {},
                **store(folder, mesh),
            }
        )
    if not components or sum(p["topology"]["triangles"] for p in components) > MAX_FACES:
        raise WorkspaceError("The scene must contain at most 200,000 triangles in total.")
    return {
        "components": components,
        "assembly_nodes": [],
        "origin": "mesh",
        "direct_edits": False,
        "mesh_import": {
            "source_units_to_mm": mm_per_unit,
            "material_display": "sampled face colors; original file retained",
        },
    }


def inspect(folder, part, offset=0, limit=128):
    mesh = load(folder, part)
    offset, limit = max(0, int(offset)), max(1, min(256, int(limit)))
    return {
        **{k: part[k] for k in ("instance_id", "name", "metrics", "matrix", "topology")},
        "representation": "mesh",
        "regions": [
            {
                "index": i + 1,
                "centre": mesh.triangles_center[i].tolist(),
                "normal": mesh.face_normals[i].tolist(),
                "area_mm2": float(mesh.area_faces[i]),
            }
            for i in range(offset, min(offset + limit, len(mesh.faces)))
        ],
        "next_offset": offset + limit if offset + limit < len(mesh.faces) else None,
        "semantic_parts": "Not inferred. Regions are explicit triangle indices tied to this candidate.",
    }


def apply(folder, snapshot, command):
    candidate = copy.deepcopy(snapshot)
    part = next((p for p in candidate["components"] if p["instance_id"] == command["instance_id"]), None)
    if not part or part.get("representation") != "mesh":
        raise WorkspaceError("Choose a mesh component.")
    mesh = load(folder, part)
    kind = command["type"]
    indices = command.get("triangle_indices") or []
    if indices and (
        len(indices) != len(set(indices)) or any(type(i) != int or not 1 <= i <= len(mesh.faces) for i in indices)
    ):
        raise WorkspaceError("Mesh region references are stale or invalid.", "stale_selection")
    face_ids = np.array(indices, dtype=int) - 1 if indices else np.arange(len(mesh.faces))
    if kind == "mesh_color":
        color = command.get("color")
        if not isinstance(color, list) or len(color) != 3 or any(type(v) != int or not 0 <= v <= 255 for v in color):
            raise WorkspaceError("Use an RGB color with three integers from 0 to 255.")
        mesh.visual.face_colors[face_ids] = [*color, 255]
    elif kind == "mesh_region_move":
        if not indices:
            raise WorkspaceError("Explicitly select mesh triangles before moving a region.")
        vector = command.get("translation")
        if (
            not isinstance(vector, list)
            or len(vector) != 3
            or any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 10000 for v in vector)
        ):
            raise WorkspaceError("Use a finite local-mm translation vector.")
        vertices = np.unique(mesh.faces[face_ids])
        untouched = np.delete(mesh.faces, face_ids, axis=0)
        boundary = np.intersect1d(vertices, np.unique(untouched))
        movable = np.setdiff1d(vertices, boundary)
        if not len(movable):
            raise WorkspaceError(
                "This region has no interior vertices. Select a larger region or separate it first. Unselected triangles are preserved."
            )
        mesh.vertices[movable] += np.asarray(vector)
    elif kind == "mesh_separate":
        if not indices or len(face_ids) == len(mesh.faces):
            raise WorkspaceError("Select a proper subset of triangles to separate.")
        region = mesh.submesh([face_ids], append=True, repair=False)
        remaining = mesh.submesh([np.setdiff1d(np.arange(len(mesh.faces)), face_ids)], append=True, repair=False)
        separated = copy.deepcopy(part)
        new_id = uuid4().hex[:16]
        separated.update(
            instance_id=new_id,
            definition_id=new_id,
            name=part["name"] + " region",
            source_instance_id=part["instance_id"],
            **store(folder, region),
        )
        candidate["components"].append(separated)
        mesh = remaining
    elif kind == "mesh_scale":
        factor = command.get("factor")
        if type(factor) not in (int, float) or not math.isfinite(factor) or not 0.001 <= factor <= 1000:
            raise WorkspaceError("Use a mesh scale from 0.001 to 1,000.")
        mesh.vertices = (mesh.vertices - mesh.centroid) * factor + mesh.centroid
    elif kind == "mesh_smooth":
        iterations = command.get("iterations", 3)
        if type(iterations) != int or not 1 <= iterations <= 30:
            raise WorkspaceError("Use 1–30 smoothing iterations.")
        trimesh.smoothing.filter_laplacian(mesh, iterations=iterations, volume_constraint=False)
    else:
        raise WorkspaceError("Unsupported mesh operation.")
    part.update(store(folder, mesh), definition_id=uuid4().hex)
    candidate["direct_edits"] = True
    return candidate


def verify(folder, snapshot):
    reports = []
    for part in snapshot["components"]:
        if part.get("representation") != "mesh":
            continue
        mesh = load(folder, part)
        # GLB round-trip is appropriate for visual geometry, not STEP solid validation.
        exported = mesh.copy()
        exported.unmerge_vertices()
        payload = trimesh.Scene(exported).export(file_type="glb")
        import io

        restored = trimesh.load_scene(io.BytesIO(payload), file_type="glb").to_geometry()
        if len(restored.faces) != len(mesh.faces) or not np.allclose(
            restored.bounds, mesh.bounds, atol=1e-4, rtol=1e-6
        ):
            raise WorkspaceError("Mesh GLB round-trip changed topology or bounds.")
        reports.append({"instance_id": part["instance_id"], "passed": True, "glb_round_trip": True, **metrics(mesh)})
    return reports

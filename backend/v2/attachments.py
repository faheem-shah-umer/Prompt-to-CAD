"""Validated, immutable image references owned by one project."""

import hashlib
import io
import os
from pathlib import Path
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from backend.native.contracts import WorkspaceError
from backend.native.documents import asset_path

MAX_COUNT = 8
MAX_BYTES = 20 * 1024 * 1024
MAX_TOTAL = 50 * 1024 * 1024
MAX_PIXELS = 40_000_000
FORMATS = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}


def decoded(data):
    if not data or len(data) > MAX_BYTES:
        raise WorkspaceError("Attach images of at most 20 MB each.", "attachment_limit")
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in FORMATS or getattr(image, "n_frames", 1) != 1:
                raise WorkspaceError("Use a single-frame PNG, JPEG or WebP image.", "unsupported_attachment")
            if image.width * image.height > MAX_PIXELS:
                raise WorkspaceError("Images are limited to 40 million decoded pixels.", "attachment_limit")
            image.load()
            return image.format, image.width, image.height
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise WorkspaceError("The image cannot be decoded safely.", "invalid_attachment") from error


def store(project_dir, source):
    source = Path(source).resolve()
    if not source.is_file() or source.stat().st_size > MAX_BYTES:
        raise WorkspaceError("Choose an image file of at most 20 MB.", "attachment_limit")
    data = source.read_bytes()
    kind, width, height = decoded(data)
    digest = hashlib.sha256(data).hexdigest()
    relative = "references/" + digest + FORMATS[kind]
    target = asset_path(project_dir, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        temporary = target.with_name(target.name + "." + uuid4().hex + ".tmp")
        try:
            with temporary.open("wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    if target.read_bytes() != data:
        raise WorkspaceError("The stored image failed its integrity check.", "asset_integrity")
    return {"asset_id": digest, "sha256": digest, "path": relative,
            "name": source.name, "type": "image", "mime_type": Image.MIME[kind],
            "width": width, "height": height, "size_bytes": len(data)}


def resolve(project_dir, reference, verify_image=True):
    if not isinstance(reference, dict) or not isinstance(reference.get("path"), str) or not isinstance(reference.get("sha256"), str):
        raise WorkspaceError("Invalid project image reference.", "invalid_attachment")
    relative = Path(reference["path"])
    if ".." in relative.parts:
        raise WorkspaceError("Image references cannot traverse folders.", "invalid_attachment")
    path = asset_path(project_dir, relative)
    root = Path(project_dir).resolve()
    if not path.is_relative_to(root / "references"):
        raise WorkspaceError("The image is outside this project's reference assets.", "invalid_attachment")
    # asset_path resolves containment; reject links even when they point within the project.
    current = root / (relative if not relative.is_absolute() else relative.relative_to(root))
    for parent in [current, *current.parents]:
        if parent == root:
            break
        if parent.is_symlink() or (parent.exists() and getattr(parent.lstat(), "st_file_attributes", 0) & 0x400):
            raise WorkspaceError("Image references cannot contain filesystem links.", "invalid_attachment")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != reference["sha256"]:
        raise WorkspaceError("The reference image is missing or changed.", "asset_integrity")
    if verify_image:
        decoded(data)
    return path


def submission(project_dir, references):
    if not isinstance(references, list) or len(references) > MAX_COUNT:
        raise WorkspaceError("Attach at most eight images.", "attachment_limit")
    result, seen, total = [], set(), 0
    for reference in references:
        path = resolve(project_dir, reference)
        total += path.stat().st_size
        if total > MAX_TOTAL:
            raise WorkspaceError("Attached images are limited to 50 MB combined.", "attachment_limit")
        if reference["sha256"] not in seen:
            clean = {k: reference[k] for k in ("asset_id", "sha256", "name", "type", "mime_type", "width", "height") if k in reference}
            clean.update(asset_id=reference["sha256"], path=path.relative_to(Path(project_dir).resolve()).as_posix(), size_bytes=path.stat().st_size)
            result.append((clean, path))
            seen.add(reference["sha256"])
    return result


def public(project_dir, reference):
    if not isinstance(reference, dict):
        return {"name": "Invalid image reference", "available": False, "diagnostic": "The reference metadata is invalid."}
    result = dict(reference)
    try:
        path = resolve(project_dir, reference, verify_image=False)
        result.update(available=True, local_path=str(path))
    except (OSError, KeyError, ValueError, WorkspaceError):
        result.update(available=False, diagnostic="Reference image is missing, changed or unavailable.")
    return result

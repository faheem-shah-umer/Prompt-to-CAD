"""Independent project copies with rewritten structured identities."""

import copy
import hashlib
import os
import shutil
import time
from pathlib import Path
from uuid import uuid4
from backend.native.contracts import WorkspaceError
from backend.native.documents import Document, write_json


def clone(projects, project_id, name):
    from .projects import folder_name

    with projects.write_lock():
        projects.reconcile()
        source = projects.project_path(project_id)
        original = projects.project(project_id)
        name = str(name).strip()[:120]
        if not name:
            raise WorkspaceError("Enter a name for the project copy.")
        stem, number = folder_name(name), 2
        directory = stem
        while (projects.folder / directory).exists():
            directory, number = f"{stem} ({number})", number + 1
        target = (projects.folder / directory).resolve()
        staging = (projects.folder / (".copy-" + uuid4().hex)).resolve()
        if target.parent != projects.folder or staging.parent != projects.folder:
            raise WorkspaceError("Invalid copy destination.")
        for parent, directories, files in os.walk(source, followlinks=False):
            for path in [
                Path(parent),
                *(Path(parent) / n for n in directories + files),
            ]:
                if (
                    path.is_symlink()
                    or getattr(path.lstat(), "st_file_attributes", 0) & 0x400
                ):
                    raise WorkspaceError(
                        "Project copies cannot contain filesystem links."
                    )
        project = copy.deepcopy(original)
        identities = {project_id: uuid4().hex[:16]}
        documents = []
        for entry in original["documents"]:
            doc = projects.document(original, entry["document_id"])
            index = doc.index()
            identities[index["document_id"]] = str(uuid4())
            for path in (doc.folder / "revisions").glob("*.json"):
                identities[path.stem] = str(uuid4())
            documents.append((entry, doc))
        for cid in original["conversations"]:
            identities[cid] = uuid4().hex
        for path in (source / "tasks").glob("*.json"):
            identities[path.stem] = uuid4().hex

        def rewrite(value, key=""):
            if isinstance(value, dict):
                if value.get("sha256") and value.get("path"):
                    asset = projects.check_reference(value)
                    if not asset.is_relative_to(source):
                        if (
                            asset.suffix.lower()
                            not in (".png", ".jpg", ".jpeg", ".webp")
                            or asset.stat().st_size > 20 * 1024 * 1024
                        ):
                            raise WorkspaceError(
                                "Unsupported external reference asset in this project."
                            )
                        relative = Path("references") / (
                            value["sha256"] + asset.suffix.lower()
                        )
                        (staging / relative).parent.mkdir(exist_ok=True)
                        shutil.copyfile(asset, staging / relative)
                        value = {**value, "path": str(target / relative)}
                return {
                    k: None
                    if k in ("provider_session", "provider_account")
                    else rewrite(v, k)
                    for k, v in value.items()
                }
            if isinstance(value, list):
                return [rewrite(v, key) for v in value]
            if isinstance(value, str):
                if key.endswith("_id") or key in (
                    "revisions",
                    "conversations",
                    "tasks",
                    "scope",
                ):
                    return identities.get(value, value)
                if (
                    key in ("path", "project_dir", "folder_path")
                    and Path(value).is_absolute()
                ):
                    path = Path(value).resolve()
                    if path.is_relative_to(source):
                        return str(target / path.relative_to(source))
            return value

        published = False
        try:
            shutil.copytree(
                source,
                staging,
                ignore=shutil.ignore_patterns(
                    "*.lock", "*.tmp", "pending.json", ".logs", ".task-lock"
                ),
            )
            for entry, doc in documents:
                relative = Path(entry["path"])
                if relative.is_absolute():
                    relative = (
                        doc.folder.relative_to(source)
                        if doc.folder.is_relative_to(source)
                        else Path("documents") / identities[entry["document_id"]]
                    )
                    if not doc.folder.is_relative_to(source):
                        shutil.copytree(
                            doc.folder,
                            staging / relative,
                            ignore=shutil.ignore_patterns(
                                "*.lock", "*.tmp", "pending.json", ".logs", ".task-lock"
                            ),
                        )
                next(
                    d
                    for d in project["documents"]
                    if d["document_id"] == entry["document_id"]
                )["path"] = str(relative)
            records = [
                (path.relative_to(staging), projects.read(path))
                for path in staging.rglob("*.json")
                if path.name in ("workspace.json", "project.json")
                or path.parent.name in ("revisions", "conversations", "tasks")
            ]
            for relative, record in records:
                destination = (
                    relative.with_name(
                        identities.get(relative.stem, relative.stem) + relative.suffix
                    )
                    if relative.parent.name in ("revisions", "conversations", "tasks")
                    else relative
                )
                write_json(staging / destination, rewrite(record))
                if destination != relative:
                    (staging / relative).unlink()
            project = rewrite(project)
            now = time.time()
            project.update(name=name, archived=False, trashed=False,
                           created_at=now, content_modified_at=now, last_opened_at=0)
            write_json(staging / "workspace.json", project)
            for entry in project["documents"]:
                doc = Document(staging / entry["path"])
                index = doc.index()
                for path in (doc.folder / "revisions").glob("*.json"):
                    doc.current({**index, "revisions": [path.stem], "cursor": 0})
            for record in [
                projects.read(path)
                for path in staging.rglob("*.json")
                if path.parent.name in ("tasks", "conversations")
            ]:

                def validate_refs(value):
                    if isinstance(value, dict):
                        if value.get("sha256") and value.get("path"):
                            reference = Path(value["path"]).resolve()
                            if not reference.is_relative_to(target):
                                raise WorkspaceError(
                                    "A copied reference points outside the project."
                                )
                            if (
                                hashlib.sha256(
                                    (
                                        staging / reference.relative_to(target)
                                    ).read_bytes()
                                ).hexdigest()
                                != value["sha256"]
                            ):
                                raise WorkspaceError(
                                    "A copied reference failed its integrity check."
                                )
                        for child in value.values():
                            validate_refs(child)
                    elif isinstance(value, list):
                        for child in value:
                            validate_refs(child)

                validate_refs(record)
            staging.rename(target)
            published = True
            catalog = projects.read(projects.catalog)
            pid = project["project_id"]
            catalog["projects"].append(pid)
            catalog.setdefault("folders", {})[pid] = directory
            write_json(projects.catalog, catalog)
            return pid
        except Exception:
            if published and target.exists():
                shutil.rmtree(target)
            raise
        finally:
            if staging.exists():
                shutil.rmtree(staging)

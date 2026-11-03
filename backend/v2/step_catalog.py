"""Read-only access to the local FreeCAD STEP catalog."""

from contextlib import closing, contextmanager
import hashlib
from pathlib import Path, PureWindowsPath
import re
import sqlite3
import stat
import tempfile
import time
from urllib.parse import urlsplit

from backend.native.contracts import WorkspaceError
from .turn_logs import safe


ROOT = Path(__file__).resolve().parents[2]
CATALOG_TOOLS = frozenset(("cad_catalog", "cad_catalog_insert"))
CHOICES = ("use", "do_not_use", "not_applicable", "undecided")
EXTENSIONS = {".step", ".stp"}
FIELDS = ("id", "name", "category", "subcategory", "description_hint", "source_url",
          "history_url", "metadata_source_url", "author_hint", "model_license_note",
          "model_license_url", "sha256", "bytes", "step_signature_ok")
SELECT = ", ".join("p." + field for field in FIELDS)


def checked_path(root, segments):
    path = root
    for name in segments:
        if (not name or name in (".", "..") or name.endswith((".", " "))
                or re.search(r'[\\:<>"|?*\x00-\x1f]', name) or PureWindowsPath(name).is_reserved()):
            raise WorkspaceError("Catalog path is not a safe relative path.", "catalog_path")
        path /= name
        info = path.lstat()
        if (stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise WorkspaceError("Catalog paths cannot use links or junctions.", "catalog_path")
    if not path.resolve(strict=True).is_relative_to(root):
        raise WorkspaceError("Catalog path leaves the workspace.", "catalog_path")
    return path


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def public_entry(row):
    entry = {}
    for field in FIELDS:
        value = row[field]
        if isinstance(value, str):
            if field.endswith("_url"):
                try:
                    url = urlsplit(value)
                    value = value if url.scheme == "https" and url.hostname and url.username is None and url.password is None else None
                except ValueError:
                    value = None
            if value:
                value = safe(re.sub(r"\\\\[^\s]+", "[local path omitted]", value))[:500]
        entry[field] = value
    entry["catalog_id"] = entry.pop("id")
    entry["declared_library_license"] = "CC-BY-3.0"
    return entry


class StepCatalog:
    def __init__(self, workspace=ROOT):
        self.workspace = Path(workspace).resolve()
        self.directory = self.workspace / ".local" / "freecad-step-catalog"
        self.inspected = set()
        self.initial = self.discover()

    def database(self):
        path = checked_path(self.workspace, (".local", "freecad-step-catalog", "catalog.sqlite3"))
        parts = checked_path(self.directory, ("parts",))
        if not parts.is_dir():
            raise WorkspaceError("The catalog parts/ directory is unavailable.", "catalog_unreadable")
        if not path.is_file():
            raise WorkspaceError("The STEP catalog database must be a regular file.", "catalog_unreadable")
        if any(path.with_name(path.name + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
            raise WorkspaceError("Close the catalog writer and checkpoint the database before starting a turn.", "catalog_unreadable")
        return path

    @staticmethod
    def connect(path):
        db = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA trusted_schema = OFF")
        return db

    def discover(self):
        version = None
        fingerprint = None
        try:
            path = self.database()
            fingerprint = digest(path)
            with closing(self.connect(path)) as db:
                version = db.execute("PRAGMA user_version").fetchone()[0]
                if version != 1:
                    raise WorkspaceError("Use a schema version 1 FreeCAD STEP catalog.", "catalog_incompatible")
                db.execute(f"SELECT {SELECT}, p.asset_path FROM parts AS p LIMIT 0")
                db.execute("SELECT rowid FROM part_search WHERE part_search MATCH ? LIMIT 1", ('"catalog"',)).fetchone()
                categories = [{"category": safe(row[0]), "count": row[1]} for row in db.execute(
                    "SELECT category, COUNT(*) FROM parts WHERE step_signature_ok = 1 AND bytes > 0 GROUP BY category ORDER BY category")]
            if digest(self.database()) != fingerprint:
                raise WorkspaceError("The STEP catalog changed. Start a new turn.", "catalog_changed")
            return {"available": True, "schema_version": version, "fingerprint": fingerprint, "categories": categories}
        except FileNotFoundError:
            code, message = "catalog_missing", "Place catalog.sqlite3 and parts/ in .local/freecad-step-catalog."
        except WorkspaceError as error:
            code, message = error.code, str(error)
        except sqlite3.DatabaseError:
            code, message = "catalog_incompatible", "The STEP catalog schema or search index could not be read."
        except OSError:
            code, message = "catalog_unreadable", "Check read access to the STEP catalog."
        return {"available": False, "schema_version": version, "fingerprint": fingerprint,
                "error": {"code": code, "message": message}}

    def current_database(self):
        if not self.initial["available"]:
            error = self.initial["error"]
            raise WorkspaceError(error["message"], error["code"])
        try:
            path = self.database()
            if digest(path) == self.initial["fingerprint"]:
                return path
        except (OSError, WorkspaceError):
            pass
        raise WorkspaceError("The STEP catalog changed or disappeared. Start a new turn.", "catalog_changed")

    @contextmanager
    def read(self):
        path = self.current_database()
        try:
            with closing(self.connect(path)) as db:
                yield db
        except sqlite3.DatabaseError as error:
            raise WorkspaceError("The STEP catalog could not be queried. Check the database and start a new turn.",
                                 "catalog_unreadable") from error
        self.current_database()

    def status(self):
        if self.initial["available"]:
            try:
                self.current_database()
            except WorkspaceError as error:
                return {**self.initial, "available": False, "error": {"code": error.code, "message": str(error)}}
        return self.initial

    def lookup(self, identity, fingerprint):
        if type(identity) is not int or not 0 < identity < 2**63:
            raise WorkspaceError("Use a positive numeric catalog ID.", "invalid_catalog_id")
        with self.read() as db:
            if fingerprint != self.initial["fingerprint"]:
                raise WorkspaceError("Use the catalog fingerprint from this turn.", "catalog_changed")
            row = db.execute(f"SELECT {SELECT}, p.asset_path FROM parts AS p WHERE p.id = ? "
                             "AND p.step_signature_ok = 1 AND p.bytes > 0", (identity,)).fetchone()
            if row is None:
                raise WorkspaceError("That STEP catalog ID is unavailable.", "invalid_catalog_id")
        return row

    def query(self, params):
        action = params.get("action")
        allowed = {"status": set(), "search": {"query", "category", "limit", "offset"},
                   "inspect": {"catalog_id", "fingerprint"}}
        if not isinstance(action, str) or action not in allowed or params.keys() - (allowed[action] | {"action"}):
            raise WorkspaceError("Use status, search or inspect with its catalog fields.", "invalid_catalog_query")
        if action == "status":
            return self.status()
        if action == "inspect":
            row = self.lookup(params.get("catalog_id"), params.get("fingerprint"))
            entry = public_entry(row)
            self.inspected.add(entry["catalog_id"])
            return {"fingerprint": self.initial["fingerprint"], "entry": entry}
        query, category = params.get("query", ""), params.get("category")
        limit, offset = params.get("limit", 10), params.get("offset", 0)
        if (not isinstance(query, str) or len(query) > 200
                or category is not None and (not isinstance(category, str) or not 1 <= len(category) <= 100)
                or type(limit) is not int or not 1 <= limit <= 20
                or type(offset) is not int or not 0 <= offset <= 10000):
            raise WorkspaceError("Search with up to 200 characters, an exact category and a page of 1–20 results.",
                                 "invalid_catalog_query")
        words = re.findall(r"[^\W_]+", query)
        if len(words) > 20 or not words and not category:
            raise WorkspaceError("Provide a category or up to 20 searchable words.", "invalid_catalog_query")
        where = "WHERE p.step_signature_ok = 1 AND p.bytes > 0 AND (? IS NULL OR p.category = ?)"
        with self.read() as db:
            if words:
                rows = db.execute(f"SELECT {SELECT} FROM part_search JOIN parts AS p ON p.id = part_search.rowid "
                                  f"{where} AND part_search MATCH ? ORDER BY rank, p.id LIMIT ? OFFSET ?",
                                  (category, category, " AND ".join(f'"{word}"' for word in words), limit + 1, offset)).fetchall()
            else:
                rows = db.execute(f"SELECT {SELECT} FROM parts AS p {where} ORDER BY p.name, p.id LIMIT ? OFFSET ?",
                                  (category, category, limit + 1, offset)).fetchall()
        return {"fingerprint": self.initial["fingerprint"], "results": [public_entry(row) for row in rows[:limit]],
                "next_offset": offset + limit if len(rows) > limit else None}

    @contextmanager
    def stage(self, identity, fingerprint, cancelled, deadline):
        row = self.lookup(identity, fingerprint)
        if identity not in self.inspected:
            raise WorkspaceError("Inspect this catalog entry in the current turn before inserting it.", "catalog_inspection_required")
        if not isinstance(row["asset_path"], str) or type(row["bytes"]) is not int:
            raise WorkspaceError("The catalog entry has invalid asset metadata.", "catalog_asset_integrity")
        segments = row["asset_path"].split("/")
        suffix = Path(segments[-1]).suffix.lower()
        if len(segments) < 2 or segments[0] != "parts" or suffix not in EXTENSIONS:
            raise WorkspaceError("The catalog entry does not point to a STEP file under parts/.", "catalog_path")
        try:
            source = checked_path(self.directory, segments)
            if not source.is_file() or source.stat().st_size != row["bytes"]:
                raise WorkspaceError("The catalog asset is missing or its size has changed.", "catalog_asset_integrity")
            local = checked_path(self.workspace, (".local",))
            with tempfile.TemporaryDirectory(prefix="catalog-insert-", dir=local) as folder:
                path = Path(folder) / ("source" + suffix)
                count, checksum = 0, hashlib.sha256()
                with source.open("rb") as incoming, path.open("xb") as outgoing:
                    for block in iter(lambda: incoming.read(1024 * 1024), b""):
                        if cancelled.is_set():
                            raise WorkspaceError("Task cancelled.", "cancelled")
                        if deadline is not None and time.monotonic() >= deadline:
                            raise WorkspaceError("The CAD task timed out.", "timeout")
                        count += len(block)
                        if count > row["bytes"]:
                            raise WorkspaceError("The catalog asset size changed.", "catalog_asset_integrity")
                        checksum.update(block)
                        outgoing.write(block)
                if count != row["bytes"] or checksum.hexdigest() != row["sha256"]:
                    raise WorkspaceError("The catalog asset does not match its recorded hash.", "catalog_asset_integrity")
                self.current_database()
                yield path, {**public_entry(row), "fingerprint": fingerprint}
        except OSError as error:
            raise WorkspaceError("Cannot access or stage the catalog STEP asset.", "catalog_asset_unreadable") from error

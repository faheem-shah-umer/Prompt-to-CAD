import json
import tempfile
import unittest
from pathlib import Path

from backend.native.contracts import WorkspaceError
from backend.native.documents import Document
from backend.v2.projects import Projects, folder_name
from backend.v2.usage import allowance, merge_allowance, tokens

ROOT = Path(__file__).resolve().parents[2]


class StorageTests(unittest.TestCase):
    def test_missing_project_does_not_hide_valid_projects_or_remove_catalog_records(
        self,
    ):
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as temporary:
            base = Path(temporary)
            projects = Projects(base / "Projects")
            missing = projects.create("Missing fixture")
            healthy = projects.create("Healthy fixture")
            source = projects.project_path(missing["project_id"])
            source.rename(base / "temporarily-moved")
            original_catalog = projects.catalog.read_bytes()
            listing = Projects(projects.folder).listing()
            self.assertEqual(
                [p["project_id"] for p in listing["projects"]], [healthy["project_id"]]
            )
            self.assertEqual(
                listing["unavailable"][0]["project_id"], missing["project_id"]
            )
            self.assertEqual(projects.catalog.read_bytes(), original_catalog)
            self.assertFalse(source.exists())
            (base / "temporarily-moved").rename(source)
            restored = Projects(projects.folder).listing()
            self.assertEqual(restored["unavailable"], [])
            self.assertEqual(len(restored["projects"]), 2)

    def test_missing_project_folder_names_remain_reserved_for_their_original_identity(
        self,
    ):
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as temporary:
            base = Path(temporary)
            projects = Projects(base / "Projects")
            missing = projects.create("Bracket")
            source = projects.project_path(missing["project_id"])
            original = (source / "workspace.json").read_bytes()
            source.rename(base / "moved-project")
            replacement = projects.create("Bracket")
            self.assertEqual(
                projects.project_path(replacement["project_id"]).name, "Bracket (2)"
            )
            external = Projects(base / "external")
            imported = external.create("Bracket")
            imported_id = projects.import_project(
                external.project_path(imported["project_id"])
            )
            self.assertEqual(projects.project_path(imported_id).name, "Bracket (3)")
            self.assertFalse(source.exists())
            self.assertEqual(
                projects.listing()["unavailable"][0]["project_id"],
                missing["project_id"],
            )
            (base / "moved-project").rename(source)
            self.assertEqual((source / "workspace.json").read_bytes(), original)
            self.assertEqual(len(projects.listing()["projects"]), 3)
            self.assertEqual(projects.listing()["unavailable"], [])

    def test_unreadable_project_metadata_is_reported_without_replacing_it(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as temporary:
            projects = Projects(temporary)
            project = projects.create("Damaged fixture")
            metadata = projects.project_path(project["project_id"]) / "workspace.json"
            metadata.write_text("{interrupted fixture")
            listing = Projects(temporary).listing()
            self.assertEqual(listing["projects"], [])
            self.assertEqual(
                listing["unavailable"][0]["project_id"], project["project_id"]
            )
            self.assertEqual(metadata.read_text(), "{interrupted fixture")

    def test_orphaned_task_records_do_not_crash_startup_recovery(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as temporary:
            projects = Projects(temporary)
            project = projects.create("Healthy fixture")
            folder = Path(temporary) / "orphaned" / "tasks"
            folder.mkdir(parents=True)
            (folder / "running.json").write_text(json.dumps({"status": "running"}))
            (folder / "damaged.json").write_text("{invalid")
            listing = Projects(temporary).listing()
            self.assertEqual(
                listing["projects"][0]["project_id"], project["project_id"]
            )
            self.assertFalse((folder.parent / "workspace.json").exists())

    def test_opening_an_external_project_preserves_its_chat_and_copies_documents(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as temporary:
            base = Path(temporary)
            previous = Projects(base / "previous")
            project = previous.create("Existing bracket")
            pid = project["project_id"]
            conversation = previous.conversation(pid)
            conversation.update(
                messages=[{"role": "user", "content": "Synthetic history"}],
                provider_session="fixture-session",
            )
            previous.save_conversation(pid, conversation)
            source = previous.project_path(pid)
            original_bytes = (source / "workspace.json").read_bytes()
            current = Projects(base / "repository/Projects")
            imported = current.import_project(source)
            view = current.view(imported)
            self.assertEqual(view["conversation"]["messages"], conversation["messages"])
            self.assertIsNone(view["conversation"]["provider_session"])
            self.assertTrue(
                Path(view["document"]["project_dir"]).is_relative_to(current.folder)
            )
            self.assertEqual((source / "workspace.json").read_bytes(), original_bytes)

    def test_named_folders_collisions_and_reopening_keep_chat_association(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as temporary:
            projects = Projects(Path(temporary) / "Projects")
            first = projects.create("Motor bracket")
            second = projects.create("Motor bracket")
            self.assertEqual(
                projects.project_path(first["project_id"]).name, "Motor bracket"
            )
            self.assertEqual(
                projects.project_path(second["project_id"]).name, "Motor bracket (2)"
            )
            chat = projects.conversation(first["project_id"])
            chat["messages"] = [{"role": "user", "content": "Synthetic fixture"}]
            projects.save_conversation(first["project_id"], chat)
            reopened = Projects(projects.folder).view(first["project_id"])
            self.assertEqual(reopened["conversation"]["messages"], chat["messages"])
            self.assertTrue(
                Path(reopened["document"]["project_dir"]).is_relative_to(
                    Path(reopened["project"]["folder_path"])
                )
            )

    def test_project_folder_can_be_relocated_with_its_conversation_and_document(self):
        import shutil

        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as temporary:
            base = Path(temporary)
            projects = Projects(base / "before")
            project = projects.create("Portable bracket")
            shutil.move(str(projects.folder), str(base / "after"))
            reopened = Projects(base / "after").view(project["project_id"])
            self.assertTrue(
                Path(reopened["document"]["project_dir"]).is_relative_to(base / "after")
            )
            self.assertEqual(
                reopened["conversation"]["document_id"],
                reopened["document"]["document_id"],
            )

    def test_windows_names_and_untrusted_catalog_cannot_escape_project_root(self):
        self.assertEqual(folder_name("CON"), "_CON")
        self.assertEqual(folder_name("Mötor plate"), "Mötor plate")
        self.assertNotIn("/", folder_name("../../escape"))
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as temporary:
            projects = Projects(temporary)
            project = projects.create("Part")
            catalog = projects.read(projects.catalog)
            catalog["folders"][project["project_id"]] = "../outside"
            projects.catalog.write_text(json.dumps(catalog))
            with self.assertRaises(WorkspaceError):
                projects.project_path(project["project_id"])

    def test_adopted_documents_are_copied_inside_the_named_project(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as temporary:
            base = Path(temporary)
            projects = Projects(base / "Projects")
            project = projects.create("Imported fixture")
            original = Document.create(base / "external-document", "External")
            projects.adopt(project["project_id"], original)
            adopted = projects.document(projects.project(project["project_id"]))
            self.assertTrue(
                adopted.folder.is_relative_to(
                    projects.project_path(project["project_id"])
                )
            )
            self.assertEqual(adopted.index(), original.index())
            self.assertTrue(original.index_path.is_file())


class PackagingPrivacyTests(unittest.TestCase):
    def test_installer_inventory_excludes_local_projects_chats_and_credentials(self):
        from tools.package_native import distribution_files

        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as temporary:
            root = Path(temporary)
            for name in (
                "bin/PromptToCAD.exe",
                "app/backend/v2/service.py",
                "source/backend/v2/service.py",
                "docs/setup.md",
                "Projects/Private part/conversations/chat.json",
                ".promptcad/identity/credentials.dpapi",
                "app/tmp/native-viewport.png",
                "source/backend/private-model.cad.json",
            ):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("synthetic fixture")
            actual = {p.relative_to(root).as_posix() for p in distribution_files(root)}
            self.assertEqual(
                actual,
                {
                    "bin/PromptToCAD.exe",
                    "app/backend/v2/service.py",
                    "source/backend/v2/service.py",
                    "docs/setup.md",
                },
            )


class UsageTests(unittest.TestCase):
    def test_remaining_allowance_uses_reported_duration_and_never_tokens(self):
        report = allowance(
            {
                "rateLimitsByLimitId": {
                    "codex": {
                        "primary": {
                            "usedPercent": 14,
                            "windowDurationMins": 300,
                            "resetsAt": 2000000000,
                        },
                        "secondary": {"usedPercent": 101, "windowDurationMins": 10080},
                    }
                }
            }
        )
        self.assertTrue(report["available"])
        self.assertEqual(report["windows"][0]["remaining_percent"], 86)
        self.assertEqual(report["windows"][0]["label"], "5-hour")
        self.assertEqual(report["windows"][1]["remaining_percent"], 0)
        self.assertFalse(allowance({"tokenUsage": {"totalTokens": 123}})["available"])
        self.assertFalse(
            allowance({"rateLimits": {"primary": {"usedPercent": None}}})["available"]
        )
        self.assertFalse(
            allowance({"rateLimits": {"primary": {"usedPercent": float("nan")}}})[
                "available"
            ]
        )

    def test_sparse_quota_updates_preserve_the_other_reported_window(self):
        original = allowance(
            {
                "rateLimits": {
                    "primary": {"usedPercent": 10, "windowDurationMins": 300},
                    "secondary": {"usedPercent": 20, "windowDurationMins": 10080},
                }
            }
        )
        refreshed = merge_allowance(
            original,
            {"rateLimits": {"primary": {"usedPercent": 25, "windowDurationMins": 300}}},
        )
        self.assertEqual(len(refreshed["windows"]), 2)
        self.assertEqual(refreshed["windows"][0]["remaining_percent"], 75)
        self.assertEqual(refreshed["windows"][1]["remaining_percent"], 80)

    def test_missing_window_and_context_fields_are_not_invented(self):
        report = allowance({"rateLimits": {"primary": {"usedPercent": 0}}})
        self.assertEqual(report["windows"][0]["label"], "Usage window")
        self.assertIsNone(report["windows"][0]["duration_minutes"])
        self.assertEqual(
            tokens(
                {
                    "tokenUsage": {
                        "total": {"inputTokens": 0, "outputTokens": -1},
                        "modelContextWindow": 128000,
                    }
                }
            ),
            {"inputTokens": 0, "modelContextWindow": 128000},
        )


if __name__ == "__main__":
    unittest.main()

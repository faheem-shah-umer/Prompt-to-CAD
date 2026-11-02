"""Engineering information stays saved independently of viewport presentation."""

import copy
import unittest

from backend.native.contracts import WorkspaceError
from backend.v2.engineering import edit, validate_records


class AnnotationVisibilityTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = {"components": [{"instance_id": "part", "asset_hash": "synthetic",
            "topology": {"faces": 6}, "parameters": {}}]}
        self.note = {"id": "assumptions", "kind": "note", "instance_id": "part",
            "text": "Design assumptions: synthetic example, dimensions in mm."}

    def test_new_notes_labels_and_dimensions_are_hidden_by_default(self):
        for kind in ("note", "label", "dimension"):
            with self.subTest(kind=kind):
                result = edit(self.snapshot, {**self.note, "kind": kind, "nominal": 10})
                record = result["engineering"][0]
                self.assertIs(record["viewport_visible"], False)
                self.assertEqual(record["text"], self.note["text"])
                self.assertTrue(validate_records(result)["passed"])
        self.assertNotIn("engineering", self.snapshot)

    def test_explicit_display_is_saved_preserved_and_can_be_disabled(self):
        shown = edit(self.snapshot, {**self.note, "viewport_visible": True})
        changed = edit(shown, {**self.note, "text": "Updated synthetic assumptions."})
        self.assertIs(changed["engineering"][0]["viewport_visible"], True)
        hidden = edit(changed, {**changed["engineering"][0], "viewport_visible": False})
        self.assertIs(hidden["engineering"][0]["viewport_visible"], False)
        self.assertEqual(hidden["engineering"][0]["anchor"], shown["engineering"][0]["anchor"])

    def test_legacy_annotations_load_and_remain_editable_without_migration(self):
        legacy = edit(self.snapshot, self.note)
        legacy["engineering"][0].pop("viewport_visible")
        unchanged = copy.deepcopy(legacy)
        self.assertTrue(validate_records(legacy)["passed"])
        self.assertEqual(legacy, unchanged)
        updated = edit(legacy, {**self.note, "text": "Edited legacy note."})
        self.assertIs(updated["engineering"][0]["viewport_visible"], False)
        self.assertEqual(updated["engineering"][0]["id"], self.note["id"])

    def test_non_boolean_visibility_is_rejected_without_changing_saved_notes(self):
        saved = edit(self.snapshot, self.note)
        before = copy.deepcopy(saved)
        for value in ("false", 0, 1, None):
            with self.subTest(value=value), self.assertRaises(WorkspaceError):
                edit(saved, {**self.note, "viewport_visible": value})
        self.assertEqual(saved, before)
        invalid = copy.deepcopy(saved)
        invalid["engineering"][0]["viewport_visible"] = "false"
        with self.assertRaises(WorkspaceError):
            validate_records(invalid)


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from backend.v2.workspace import WorkspaceV2

ROOT = Path(__file__).resolve().parents[2]


def note(identity, text, instance="part-a"):
    return {"id": identity, "kind": "note", "instance_id": instance, "text": text, "status": "current"}


class TurnDesignNoteTests(unittest.TestCase):
    """Saved design notes belong to the agent turn whose revision added or changed them."""

    def setUp(self):
        (ROOT / "tmp").mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT / "tmp")
        self.folder = Path(self.temporary.name)
        (self.folder / "revisions").mkdir()
        self.owner = SimpleNamespace(note_cache={})

    def tearDown(self):
        self.temporary.cleanup()

    def revision(self, identity, parent, engineering):
        components = [{"instance_id": "part-a", "name": "Base plate"}, {"instance_id": "part-b", "name": "Carriage"}]
        (self.folder / "revisions" / f"{identity}.json").write_text(json.dumps(
            {"revision_id": identity, "parent_revision_id": parent, "components": components, "engineering": engineering}),
            encoding="utf-8")

    def notes(self, revision):
        return WorkspaceV2.turn_design_notes(self.owner, self.folder, revision)

    def test_each_turn_shows_only_the_notes_it_wrote(self):
        self.revision("r1", None, [note("n1", "Use 12 mm plate")])
        self.revision("r2", "r1", [note("n1", "Use 12 mm plate"), note("n2", "Belt tension idler", "part-b")])
        self.assertEqual([n["text"] for n in self.notes("r1")], ["Use 12 mm plate"])
        second = self.notes("r2")
        self.assertEqual([n["id"] for n in second], ["n2"])
        self.assertEqual(second[0]["component_name"], "Carriage")

    def test_an_edited_note_belongs_to_the_turn_that_edited_it(self):
        self.revision("r1", None, [note("n1", "Draft")])
        self.revision("r2", "r1", [note("n1", "Final")])
        self.assertEqual([n["text"] for n in self.notes("r2")], ["Final"])

    def test_turns_without_note_changes_and_missing_revisions_show_nothing(self):
        self.revision("r1", None, [note("n1", "Draft")])
        self.revision("r2", "r1", [note("n1", "Draft"), {"id": "d1", "kind": "dimension", "instance_id": "part-a", "text": ""}])
        self.assertEqual(self.notes("r2"), [])
        self.assertEqual(self.notes("missing"), [])

    def test_results_are_cached_and_callers_cannot_mutate_the_cache(self):
        self.revision("r1", None, [note("n1", "Draft")])
        self.notes("r1")[0]["text"] = "changed by caller"
        (self.folder / "revisions" / "r1.json").unlink()
        self.assertEqual(self.notes("r1")[0]["text"], "Draft")


if __name__ == "__main__":
    unittest.main()

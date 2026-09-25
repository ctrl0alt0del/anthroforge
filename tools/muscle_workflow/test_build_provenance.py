"""Git alone is insufficient when the addon has uncommitted implementation edits."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import build_provenance as provenance
from common import read_json


class BuildProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "implementation.py"
        self.source.write_text("original")
        self.addCleanup(patch.stopall)
        patch.dict("os.environ", AF_MUSCLE_WORKFLOW_HOME=str(self.root)).start()
        patch.object(provenance, "PROJECT", self.root).start()
        patch.object(provenance, "source_files", return_value=[Path("implementation.py")]).start()
        self.git = patch.object(provenance, "git_output", side_effect=lambda *a: "commit-a" if a[0] == "rev-parse" else " M implementation.py").start()

    def test_same_git_revision_different_dirty_source_has_different_version(self):
        first = provenance.capture_authoring()
        self.source.write_text("changed implementation")
        second = provenance.capture_authoring()
        self.assertEqual(first["git_commit"], second["git_commit"])
        self.assertNotEqual(first["source_manifest"], second["source_manifest"])
        self.assertTrue(read_json(second["source_manifest"]["path"])["working_tree_dirty"])

    def test_changed_commit_cannot_reuse_stale_manifest_commit(self):
        first = provenance.capture_authoring()
        self.git.side_effect = lambda *a: "commit-b" if a[0] == "rev-parse" else ""
        second = provenance.capture_authoring()
        self.assertNotEqual(first["source_manifest"], second["source_manifest"])
        self.assertEqual(read_json(second["source_manifest"]["path"])["git_commit"], "commit-b")

    def test_identical_sources_reuse_immutable_manifest(self):
        first = provenance.capture_authoring()
        second = provenance.capture_authoring()
        self.assertEqual(first["source_manifest"], second["source_manifest"])
        self.assertIsNone(second["native_build"])


if __name__ == "__main__":
    unittest.main()

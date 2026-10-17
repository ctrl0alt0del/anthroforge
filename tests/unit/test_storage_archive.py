"""Cold archives preserve every byte and never replace existing edited files."""
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/muscle_workflow'))
from storage_archive import create_archive, restore_archive, verify_archive, assert_retirable, retire_archives


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'runs/old/a.json'
        self.source.parent.mkdir(parents=True); self.source.write_bytes(b'{"old":true}\n')
        self.manifest = create_archive(self.root, 'runs/old')
        self.data = json.loads((self.root / self.manifest).read_text())

    def test_verified_roundtrip(self):
        original = self.source.read_bytes(); stamp = self.source.stat().st_mtime_ns
        self.source.unlink()
        restore_archive(self.root, self.manifest)
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(self.source.stat().st_mtime_ns, stamp)

    def test_restore_refuses_edited_destination(self):
        self.source.write_bytes(b'edited')
        with self.assertRaisesRegex(ValueError, 'overwrite'):
            restore_archive(self.root, self.manifest)
        self.assertEqual(self.source.read_bytes(), b'edited')

    def test_corrupt_archive_is_rejected(self):
        (self.root / self.data['archive']).write_bytes(b'broken')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            verify_archive(self.root, self.data)

    def test_current_catalogue_journal_cannot_be_retired(self):
        folder = self.root / 'catalogue'; folder.mkdir()
        value = dict(revision=1, families=[dict(current_build=dict(journal=str(self.source.parent)))])
        (folder / 'catalogue.json').write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'protected'):
            assert_retirable(self.root, self.data)

    def test_relative_current_catalogue_journal_cannot_be_retired(self):
        folder = self.root / 'catalogue'; folder.mkdir()
        value = dict(revision=1, families=[dict(current_build=dict(journal='runs/old'))])
        (folder / 'catalogue.json').write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'protected'):
            assert_retirable(self.root, self.data)
        self.assertTrue(self.source.exists())

    def test_archive_cannot_target_assets_through_parent_traversal(self):
        folder = self.root / 'assets'; folder.mkdir(); (folder / 'keep').write_bytes(b'keep')
        for relative in ('runs/../assets', 'assets', 'runs/old/../old'):
            with self.assertRaisesRegex(ValueError, 'canonical'):
                create_archive(self.root, relative)
        self.assertEqual((folder / 'keep').read_bytes(), b'keep')

    def test_retire_then_restore_history_preserves_original(self):
        catalogue = self.root / 'catalogue'; catalogue.mkdir()
        (catalogue / 'catalogue.json').write_text(json.dumps(dict(revision=1, families=[])))
        run = self.root / 'maintenance'; run.mkdir()
        (run / 'archives.json').write_text(json.dumps([self.manifest]))
        before = self.source.read_bytes()
        result = retire_archives(self.root, run)
        self.assertEqual(result[0]['removed_files'], 1); self.assertFalse(self.source.exists())
        restore_archive(self.root, self.manifest)
        self.assertEqual(self.source.read_bytes(), before)
